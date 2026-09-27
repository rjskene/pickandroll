"""Solve ahead of the clock: the recommendation payload and one background solver per session.

The board before the draft is known, so the first plan and the prices of every plausible
alternative are solved as soon as a session exists. During the draft each pick only removes
players: the session re-solves in the background after every change, prices the surviving
candidates (first-order prices at once, exact prices as the pool finishes them) and, while
someone else is on the clock, solves "if he is gone" scenarios for the candidates likely to
be taken before my turn. By the time the pick arrives the answer is at most one pick stale,
and the UI shows the latest result with a note when the board has moved since.

:func:`compute_recommendation` is the whole routine, shared by the synchronous
``POST /sessions/{id}/recommend`` and the background loop. It snapshots the board under the
session lock (building the problem takes milliseconds), then solves without the lock so picks
can land meanwhile.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .app import Session

Progress = Callable[[dict[str, Any]], None]

#: Candidates whose exact cost is within this much of the best are a tie: the model cannot
#: tell them apart, so the UI shows them as a group. Categories won, and z for the sum objective.
TIE_BAND = {"wins": 0.05, "z": 0.5}

#: Background solves run here rather than in the event loop's default executor, which
#: ``asyncio.run`` waits for at shutdown: a server reload must not wait out a 20 s solve.
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="solve")


def solver_executor() -> ThreadPoolExecutor:
    return _EXECUTOR


class SolveParams(BaseModel):
    n: int = Field(default=8, ge=1, le=30, description="candidates priced exactly")
    horizon: bool = Field(default=True, description="plan every remaining pick (else one roster)")
    scenarios: int = Field(
        default=3, ge=0, le=8, description="'if he is gone' plans while someone else picks"
    )
    objective: Literal["win", "sum"] | None = Field(
        default=None, description="override the session's objective for this solve"
    )


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _records(table: pd.DataFrame) -> list[dict[str, Any]]:
    if table.empty:
        return []
    out = table.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(4)
    rows = out.to_dict(orient="records")
    for row in rows:
        for key, value in row.items():
            if isinstance(value, float) and pd.isna(value):
                row[key] = None
    return rows


def _candidates(table: pd.DataFrame, scale: str, adp: pd.Series) -> list[dict[str, Any]]:
    """Candidate rows with each player's ADP and a ``tie`` flag: true when more than one
    candidate, this one included, sits within ``TIE_BAND`` of the best exact objective."""
    rows = _records(table)
    band = TIE_BAND[scale]
    close = [r for r in rows if r.get("cost_vs_best") is not None and r["cost_vs_best"] <= band]
    tied = {r["player"] for r in close} if len(close) > 1 else set()
    for row in rows:
        value = adp.get(row["player"])
        row["adp"] = None if value is None or pd.isna(value) else round(float(value), 1)
        row["tie"] = row["player"] in tied
    return rows


def compute_recommendation(
    session: Session,
    params: SolveParams,
    progress: Progress | None = None,
    workers: int | None = None,
) -> dict[str, Any]:
    """Next-pick candidates, the plan, the category report and the league tally for the
    board as it stands. Records the solve in the session's score history."""
    state = session.state
    names = state.projections.df["player"]
    started = time.perf_counter()
    curve_arg: Any = "default"
    if params.objective == "sum":
        curve_arg = None
    elif params.objective == "win" and state.curve is None:
        curve_arg = state.wins_curve()
    objective = params.objective or state.objective

    def report(update: dict[str, Any]) -> None:
        if progress is None:
            return
        payload = {**update, "elapsed_ms": round((time.perf_counter() - started) * 1000)}
        candidate = payload.get("candidate")
        if isinstance(candidate, dict) and "player" in candidate:
            payload["candidate"] = {
                **{
                    k: (None if isinstance(v, float) and pd.isna(v) else v)
                    for k, v in candidate.items()
                },
                "name": names.get(candidate["player"], candidate["player"]),
            }
        if payload.get("first_pick"):
            payload["first_pick_name"] = names.get(payload["first_pick"], payload["first_pick"])
        if payload.get("gone"):
            payload["gone_name"] = names.get(payload["gone"], payload["gone"])
        if "prices" in payload:
            payload["prices"] = {
                p: (None if v is None else round(float(v), 4)) for p, v in payload["prices"].items()
            }
        progress(payload)

    # Snapshot the board: everything that reads the pick log happens under the lock.
    with session.lock:
        version = session.version
        snapshot = {
            "version": version,
            "on_the_clock": state.on_the_clock,
            "next_overall": state.next_overall,
            "my_next_pick": state.my_next_pick,
            "drafted": len(state.my_roster),
        }
        if not state.my_remaining_picks:
            raise ValueError("you have no picks left; the final score is at /score")
        report({"stage": "start", "done": 0, "total": 1, "objective": objective})
        problem = None
        candidates: list[str] = []
        if params.horizon and not state.complete:
            try:
                problem = state.horizon_problem(curve=curve_arg)
                candidates = state.candidates(params.n, expected=True)
            except ValueError:
                problem = None  # picks and open slots disagree: single roster below

    if problem is not None:
        table, solution, _ = state.recommend_horizon(
            n=params.n,
            workers=workers,
            progress=report,
            problem=problem,
            candidates=candidates,
        )
        scenarios = (
            state.scenarios(
                problem, table, count=params.scenarios, workers=workers, progress=report
            )
            if params.scenarios
            else []
        )
        with session.lock:
            finals = state.raw_finals(solution)
            categories = state.category_report(finals)
            league = state.matchups(finals)
            wins = state.expected_wins(finals)
            value = float(solution.expected_totals.sum())
            prices = state.board_prices(problem, solution)
            entry = session.record_score(
                snapshot,
                mode="horizon",
                wins=wins,
                value=value,
                matchups=league["matchups_won"],
                top=names.get(solution.first_pick) if solution.first_pick else None,
            )
        scale = "wins" if problem.curve is not None and state.last_fallback is None else "z"
        candidate_rows = _candidates(table, scale, state.effective_adp())
        session.prices = prices
        session.exact_prices = {
            r["player"]: float(r["cost_vs_best"])
            for r in candidate_rows
            if r.get("cost_vs_best") is not None
        }
        session.prices_version = version
        payload = {
            **snapshot,
            "mode": "horizon",
            "objective": objective,
            "scale": scale,
            "tie_band": TIE_BAND[scale],
            "fallback": state.last_fallback,
            "timings": {k: round(v, 1) for k, v in state.last_timings.items()},
            "adp_source": state.adp_source,
            "availability_source": state.availability_source,
            "candidates": candidate_rows,
            "plan": [
                {
                    "pick": int(r.pick),
                    "player": r.player,
                    "name": names.at[r.player],
                    "availability": round(float(r.availability), 3),
                }
                for r in solution.plan.itertuples()
            ],
            "scenarios": [
                {
                    **row,
                    "objective": round(float(row["objective"]), 4),
                    "wins": None if row.get("wins") is None else round(float(row["wins"]), 4),
                }
                for row in scenarios
            ],
            "best_roster": {
                "objective": round(float(solution.objective), 4),
                "wins": round(wins, 4),
                "value": round(value, 3),
                "min_active_total": round(float(solution.min_active_total), 3),
                "cat_totals": {c: round(float(v), 3) for c, v in finals.items()},
                "roster": [
                    {**r, "name": names.at[r["player"]]}
                    for r in solution.roster.to_dict(orient="records")
                ],
                "solve_seconds": round(float(solution.solve_seconds), 3),
                "time_limited": bool(solution.time_limited),
            },
            "categories": categories,
            "league": league,
            "wins": round(wins, 4),
            "value": round(value, 3),
            "score": entry,
        }
        report({"stage": "done", "done": 1, "total": 1, "wins": round(wins, 4)})
        return payload

    # Single-roster model: picks and open slots disagree, or the caller asked for it.
    with session.lock:
        roster_curve = (
            None if curve_arg is None else (state.curve if curve_arg == "default" else curve_arg)
        )
        table = state.recommend(n=params.n, punt=frozenset(), curve=roster_curve)
        best = state.best_roster(punt=frozenset(), curve=roster_curve)
        cols = [c.value for c in state.settings.cats]
        finals = pd.Series(
            {c.value: float(best.cat_totals[c]) for c in state.settings.cats}
        ).reindex(cols)
        categories = state.category_report(finals)
        league = state.matchups(finals)
        wins = state.expected_wins(finals)
        value = state.roster_value() + float(
            (
                state.z.loc[[p for p in best.players if p not in state.my_roster], cols]
                - state.replacement_level()[cols]
            )
            .sum()
            .sum()
        )
        entry = session.record_score(
            snapshot,
            mode="roster",
            wins=wins,
            value=value,
            matchups=league["matchups_won"],
            top=names.at[table.iloc[0]["player"]] if len(table) else None,
        )
    session.prices = None
    session.exact_prices = {}
    session.prices_version = None
    report({"stage": "roster", "done": 1, "total": 1})
    scale = "wins" if roster_curve is not None else "z"
    payload = {
        **snapshot,
        "mode": "roster",
        "objective": objective,
        "scale": scale,
        "tie_band": TIE_BAND[scale],
        "fallback": None,
        "timings": {"total_ms": round((time.perf_counter() - started) * 1000, 1)},
        "adp_source": state.adp_source,
        "availability_source": state.availability_source,
        "candidates": _candidates(table, scale, state.effective_adp()),
        "plan": [],
        "scenarios": [],
        "best_roster": {
            "objective": round(float(best.objective), 4),
            "wins": round(wins, 4),
            "value": round(value, 3),
            "min_active_total": round(float(best.min_active_total), 3),
            "cat_totals": {c: round(float(v), 3) for c, v in finals.items()},
            "roster": [
                {**r, "name": names.at[r["player"]]} for r in best.roster.to_dict(orient="records")
            ],
            "solve_seconds": round(float(best.solve_seconds), 3),
            "time_limited": False,
        },
        "categories": categories,
        "league": league,
        "wins": round(wins, 4),
        "value": round(value, 3),
        "score": entry,
    }
    report({"stage": "done", "done": 1, "total": 1, "wins": round(wins, 4)})
    return payload


class BackgroundSolver:
    """Re-solves a session whenever its board changes, one solve at a time, coalescing
    changes that arrive while a solve runs into one more solve afterwards."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task | None = None
        self.dirty = False
        self.enabled = True
        self.running = False
        self.runs = 0
        self.last_started: str | None = None
        self.last_finished: str | None = None
        self.last_error: str | None = None
        self.solved_version: int | None = None
        self.force = False
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def kick(self, reason: str = "change", force: bool = False) -> bool:
        """Mark the board changed and make sure a solve runs. Safe from any thread. Returns
        whether a solve could be scheduled. ``force`` runs once even when the background
        solver is switched off (a manual re-solve)."""
        with self._lock:
            self.dirty = True
            if force:
                self.force = True
        loop = self.loop
        if loop is None or loop.is_closed() or not (self.enabled or force):
            return False
        try:
            loop.call_soon_threadsafe(self._ensure_task)
        except RuntimeError:
            return False
        return True

    def _ensure_task(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self._run())

    def _should_solve(self) -> bool:
        session = self.session
        state = session.state
        if session.survival_building:
            return False
        return bool(state.my_remaining_picks) and not state.complete

    async def _run(self) -> None:
        session = self.session
        while True:
            with self._lock:
                if not self.dirty or not (self.enabled or self.force):
                    self.force = False
                    return
                self.dirty = False
                self.force = False
            if not self._should_solve():
                continue
            self.running = True
            self.last_started = _now()
            self.last_error = None
            try:
                payload = await asyncio.get_running_loop().run_in_executor(
                    _EXECUTOR,
                    compute_recommendation,
                    session,
                    session.solve_params,
                    session.publish_threadsafe_solve,
                )
            except Exception as exc:  # noqa: BLE001 - the loop must survive a bad solve
                self.last_error = str(exc)
                session.publish("solve", {"stage": "error", "message": str(exc)}, bump=False)
            else:
                session.set_recommendation(payload)
                self.solved_version = payload["version"]
            finally:
                self.running = False
                self.runs += 1
                self.last_finished = _now()

    def status(self) -> dict[str, Any]:
        with self._lock:
            dirty = self.dirty
        return {
            "enabled": self.enabled,
            "running": self.running,
            "pending": dirty,
            "runs": self.runs,
            "solved_version": self.solved_version,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "last_error": self.last_error,
        }
