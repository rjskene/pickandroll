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

In a live room the clock decides (#13): a solve for a board that a pick has already replaced
stops at its next stage instead of holding up the new board's; the plan can be published
before its exact prices (``early``); my own turn can get a shorter plan budget
(``turn_time_limit``); and the boards my turn can start on are planned before it starts
(``presolve``, see :mod:`.presolve`).
"""

from __future__ import annotations

import asyncio
import copy
import functools
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..draft.state import plan_fallback
from ..optim.horizon import HorizonProblem, HorizonSolution, first_order_table
from ..optim.pool import shared_pool
from .presolve import (
    MINE,
    ONE_AWAY,
    BranchBook,
    Entry,
    board_key,
    branch_boards,
    likely_next,
    solve_branch,
)

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
    early: bool = Field(default=False, description="publish the plan before its exact prices")
    turn_time_limit: float | None = Field(
        default=None, ge=0.5, le=600.0, description="plan budget when my pick is on the clock"
    )
    turn_n: int | None = Field(
        default=None, ge=1, le=30, description="candidates priced when my pick is on the clock"
    )
    presolve: bool = Field(
        default=False, description="plan the boards my turn can start on before it starts"
    )


class Superseded(Exception):
    """A newer board arrived while this solve ran: the rest of it would be stale."""


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


def _snapshot(session: Session) -> dict[str, Any]:
    """The board a solve is for. Call under the session lock."""
    state = session.state
    return {
        "version": session.version,
        "on_the_clock": state.on_the_clock,
        "next_overall": state.next_overall,
        "my_next_pick": state.my_next_pick,
        "drafted": len(state.my_roster),
    }


def _horizon_payload(
    session: Session,
    snapshot: dict[str, Any],
    objective: str,
    problem: HorizonProblem,
    solution: HorizonSolution,
    table: pd.DataFrame,
    scenarios: list[dict[str, Any]],
    *,
    priced: bool,
    timings: dict[str, float],
    branch: bool = False,
) -> dict[str, Any]:
    """The recommendation for ``snapshot``'s board from its plan and candidate table: exactly
    priced (``priced``) or priced to first order only (an early or pre-solved plan)."""
    state = session.state
    names = state.projections.df["player"]
    version = snapshot["version"]
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
        fallback = plan_fallback(problem, solution)
        scale = "wins" if problem.curve is not None and fallback is None else "z"
        candidate_rows = _candidates(table, scale, state.effective_adp())
        if session.prices_version is None or version >= session.prices_version:
            session.prices = prices
            session.exact_prices = (
                {
                    r["player"]: float(r["cost_vs_best"])
                    for r in candidate_rows
                    if r.get("cost_vs_best") is not None
                }
                if priced
                else {}
            )
            session.prices_version = version
    return {
        **snapshot,
        "mode": "horizon",
        "objective": objective,
        "scale": scale,
        "tie_band": TIE_BAND[scale],
        "priced": priced,
        "branch": branch,
        "fallback": fallback,
        "timings": {k: round(v, 1) for k, v in timings.items()},
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


def compute_recommendation(
    session: Session,
    params: SolveParams,
    progress: Progress | None = None,
    workers: int | None = None,
    *,
    on_early: Callable[[dict[str, Any]], None] | None = None,
    stop: Callable[[], bool] | None = None,
    base: tuple[HorizonProblem, HorizonSolution] | None = None,
) -> dict[str, Any]:
    """Next-pick candidates, the plan, the category report and the league tally for the
    board as it stands. Records the solve in the session's score history.

    ``on_early`` receives the plan priced to first order before the exact prices are solved
    (when ``params.early``). ``stop`` is asked at every stage; once it says the board has
    moved on, the solve raises :class:`Superseded`. ``base`` is a plan already solved for
    this board (a pre-solved branch): only its prices are solved."""
    state = session.state
    names = state.projections.df["player"]
    started = time.perf_counter()
    curve_arg: Any = "default"
    if params.objective == "sum":
        curve_arg = None
    elif params.objective == "win" and state.curve is None:
        curve_arg = state.wins_curve()
    objective = params.objective or state.objective

    def check() -> None:
        if stop is not None and stop():
            raise Superseded

    def report(update: dict[str, Any]) -> None:
        if update.get("stage") == "candidates":
            check()
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

    check()
    # Snapshot the board: everything that reads the pick log happens under the lock.
    with session.lock:
        snapshot = _snapshot(session)
        if not state.my_remaining_picks:
            raise ValueError("you have no picks left; the final score is at /score")
        report({"stage": "start", "done": 0, "total": 1, "objective": objective})
        turn = bool(snapshot["on_the_clock"])
        n = params.turn_n if turn and params.turn_n else params.n
        plan_limit = params.turn_time_limit if turn and base is None else None
        problem = None
        candidates: list[str] = []
        if params.horizon and not state.complete:
            try:
                problem = base[0] if base is not None else state.horizon_problem(curve=curve_arg)
                candidates = state.candidates(n, expected=True)
            except ValueError:
                problem = None  # picks and open slots disagree: single roster below

    if problem is not None:

        def on_plan(
            solution: HorizonSolution, table: pd.DataFrame, so_far: dict[str, float]
        ) -> None:
            if on_early is not None and params.early:
                on_early(
                    _horizon_payload(
                        session,
                        snapshot,
                        objective,
                        problem,
                        solution,
                        table,
                        [],
                        priced=False,
                        timings=so_far,
                    )
                )
            check()

        timings: dict[str, float] = {}
        table, solution, _ = state.recommend_horizon(
            n=n,
            workers=workers,
            progress=report,
            problem=problem,
            candidates=candidates,
            plan_time_limit=plan_limit,
            on_plan=on_plan,
            base=None if base is None else base[1],
            timings=timings,
        )
        check()
        scenarios = (
            state.scenarios(
                problem, table, count=params.scenarios, workers=workers, progress=report
            )
            if params.scenarios
            else []
        )
        payload = _horizon_payload(
            session,
            snapshot,
            objective,
            problem,
            solution,
            table,
            scenarios,
            priced=True,
            timings=timings,
        )
        report({"stage": "done", "done": 1, "total": 1, "wins": payload["wins"]})
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
        "priced": True,
        "branch": False,
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
    """Re-solves a session whenever its board changes. A solve for a board a pick has replaced
    stops at its next stage, and the new board's solve starts at once rather than queueing
    behind it. With ``presolve`` it also plans the boards my turn can start on (see
    :mod:`.presolve`) and installs the matching one the moment the board arrives."""

    #: Live solves at once: the newest board's, and older ones winding down their stage.
    MAX_INFLIGHT = 3

    def __init__(self, session: Session) -> None:
        self.session = session
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task | None = None
        self.dirty = False
        self.enabled = True
        self.inflight = 0
        self.runs = 0
        self.abandoned = 0
        self.generation = 0
        self.last_started: str | None = None
        self.last_finished: str | None = None
        self.last_error: str | None = None
        self.solved_version: int | None = None
        self.force = False
        self.book = BranchBook()
        self._lock = threading.Lock()
        self._o_rank: tuple[Any, pd.Series | None] | None = None
        self._presolving = False
        self._presolve_again = False

    @property
    def running(self) -> bool:
        return self.inflight > 0

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
        while True:
            with self._lock:
                if not self.dirty or not (self.enabled or self.force):
                    self.force = False
                    return
                if self.inflight >= self.MAX_INFLIGHT:
                    return  # a finishing solve runs the loop again
                self.dirty = False
                self.force = False
            if not self._should_solve():
                continue
            self.generation += 1
            gen = self.generation
            base = self._take_branch(gen)
            self._start(gen, base)
            self._schedule_presolve()
            await asyncio.sleep(0)

    def _start(self, gen: int, base: tuple[HorizonProblem, HorizonSolution] | None) -> None:
        session = self.session
        loop = asyncio.get_running_loop()
        self.inflight += 1
        self.last_started = _now()
        self.last_error = None

        def early(payload: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(self._publish, payload)

        future = loop.run_in_executor(
            _EXECUTOR,
            functools.partial(
                compute_recommendation,
                session,
                session.solve_params,
                session.publish_threadsafe_solve,
                on_early=None if base is not None else early,
                stop=lambda: self.generation != gen,
                base=base,
            ),
        )
        future.add_done_callback(self._finished)

    def _finished(self, future: asyncio.Future) -> None:
        self.inflight -= 1
        self.runs += 1
        self.last_finished = _now()
        exc = None if future.cancelled() else future.exception()
        if isinstance(exc, Superseded):
            self.abandoned += 1
        elif exc is not None:
            self.last_error = str(exc)
            self.session.publish("solve", {"stage": "error", "message": str(exc)}, bump=False)
        elif not future.cancelled():
            self._publish(future.result())
        if self.dirty:
            self._ensure_task()

    def _publish(self, payload: dict[str, Any]) -> None:
        """Make ``payload`` the recommendation unless a newer board's, or an exactly priced one
        for the same board, is already there. Runs on the event loop."""
        rec = self.session.recommendation
        if rec is not None:
            if rec["version"] > payload["version"]:
                return
            if rec["version"] == payload["version"] and (
                rec.get("priced", True) or not payload.get("priced", True)
            ):
                return
        self.session.set_recommendation(payload)
        self.solved_version = payload["version"]
        if payload["version"] == self.session.version:
            self._schedule_presolve()

    # ------------------------------------------------------------------ pre-solve
    def _o_rank_series(self) -> pd.Series | None:
        """Yahoo's o_rank by player id, from the room's players file."""
        room = self.session.room
        if room is None:
            return None
        ids = room.ids
        if self._o_rank is None or self._o_rank[0] is not ids:
            col = ids.players["o_rank"] if "o_rank" in ids.players.columns else None
            ranks = None
            if col is not None:
                ranks = pd.Series(
                    {pid: col.get(yid) for yid, pid in ids.mapping.items()}, dtype=float
                ).dropna()
            self._o_rank = (ids, ranks)
        return self._o_rank[1]

    def _take_branch(self, gen: int) -> tuple[HorizonProblem, HorizonSolution] | None:
        """On a board my turn starts on, install its pre-solved plan, or install it the moment
        it lands when it is still solving. Returns the plan for the live solve to price."""
        session = self.session
        if not session.solve_params.presolve:
            return None
        state = session.state
        with session.lock:
            key = board_key(state)
            turn = state.on_the_clock
            snapshot = _snapshot(session)
        self.book.prune(key)
        if not turn:
            return None
        entry = self.book.take(key)
        if entry is None:
            return None
        if entry.solution is None:
            if entry.future is not None and not entry.future.done():
                loop = asyncio.get_running_loop()
                entry.future.add_done_callback(
                    lambda _f: loop.call_soon_threadsafe(self._late_branch, entry, gen, snapshot)
                )
            return None
        self._install(entry, snapshot)
        return entry.branch.problem, entry.solution

    def _late_branch(self, entry: Entry, gen: int, snapshot: dict[str, Any]) -> None:
        if self.generation == gen and entry.solution is not None:
            self._install(entry, snapshot)

    def _install(self, entry: Entry, snapshot: dict[str, Any]) -> None:
        session = self.session
        state = session.state
        problem, solution = entry.branch.problem, entry.solution
        assert solution is not None
        with session.lock:
            n = session.solve_params.turn_n or session.solve_params.n
            candidates = state.candidates(n, expected=True)
        table = first_order_table(problem, solution, candidates)
        if not table.empty:
            table.insert(1, "name", table["player"].map(state.projections.df["player"]))
        objective = session.solve_params.objective or state.objective
        timings = {"plan_ms": entry.solve_ms or 0.0, "branch": 1.0}
        payload = _horizon_payload(
            session,
            snapshot,
            objective,
            problem,
            solution,
            table,
            [],
            priced=False,
            timings=timings,
            branch=True,
        )
        self._publish(payload)

    def _schedule_presolve(self) -> None:
        if not self.session.solve_params.presolve or not self.enabled:
            return
        if self._presolving:
            self._presolve_again = True  # the board moved while branches were being built
            return
        self._presolving = True
        self._presolve_again = False
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(_EXECUTOR, self._presolve)

        def done(f: asyncio.Future) -> None:
            self._presolving = False
            if not f.cancelled() and f.exception() is not None:
                self.last_error = f"presolve: {f.exception()}"
            if self._presolve_again:
                self._schedule_presolve()

        future.add_done_callback(done)

    def _presolve(self) -> None:
        """Launch plan-only solves in the pool for the boards my turn can start on."""
        session = self.session
        state = session.state
        rec = session.recommendation
        with session.lock:
            if state.complete or not state.my_remaining_picks or session.survival_building:
                return
            board = copy.copy(state)
            board.picks = list(state.picks)
            fresh = rec is not None and rec["version"] == session.version
            mine = [c["player"] for c in rec["candidates"][:MINE]] if fresh else []
        curve: Any = None if session.solve_params.objective == "sum" else "default"
        likely = likely_next(board, self._o_rank_series(), limit=ONE_AWAY)
        branches = branch_boards(board, likely, mine, curve=curve)
        wanted = self.book.wanted(branches)
        if not wanted:
            return
        pool = shared_pool()
        for branch in wanted:
            future = pool.submit(
                solve_branch, (branch.problem, state.plan_time_limit, state.plan_gap)
            )
            entry = self.book.add(branch, future)
            future.add_done_callback(
                lambda f, e=entry: self.book.done(
                    e, None if f.cancelled() or f.exception() is not None else f.result()
                )
            )

    def status(self) -> dict[str, Any]:
        with self._lock:
            dirty = self.dirty
        return {
            "enabled": self.enabled,
            "running": self.running,
            "inflight": self.inflight,
            "pending": dirty,
            "runs": self.runs,
            "abandoned": self.abandoned,
            "solved_version": self.solved_version,
            "last_started": self.last_started,
            "last_finished": self.last_finished,
            "last_error": self.last_error,
            "presolve": self.book.status(),
        }
