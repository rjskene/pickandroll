"""The Strategy panel (#110, ``season.strategy``): the engine run behind ``GET`` and ``POST
/seasons/{league}/strategy``.

A run takes the league's move problem (``season_moves.build``) and the Moves panel's
single-move gains (today's moves, solved first when they are not), ranks the pool from them
(``strategy.pool_of``), and for each weight of the frontier:

1. runs the exact search on the weighted value, at once: the panel's first answer;
2. starts the program in the background process pool (``optim.pool``) from the search's set, one
   solve per weight, each within its time limit, and meanwhile prices the search's set here by
   exact re-solves (the add left out, the drop kept), as on the Moves panel, a re-solve that
   beats the set replacing it;
3. takes the program's set when it is better on the weighted value (``strategy.choose``), priced
   the same way, with every player's first-order value at the program's solution.

A run is kept per league and system for the day and the inputs it was made from (the moves'
stamp). GET never solves: with no such run it says ``not_solved``. POST starts a run, or returns
the one with the same settings; ``?wait=true`` answers once it is done. A GET during a run shows
the points filling in.

``program_only`` is option B of #110, kept as a small switch while the user decides between the
two: the linear program's set stands wherever it solved to the gap, and the search's set is only
its fallback where a solve hit the time limit or failed. Nothing else changes; the program's
set is priced but not replaced by a better re-solve.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from ..optim.pool import background_pool
from ..season import moves as mv
from ..season import strategy as st
from . import season_moves

#: The candidates both solvers search, and the most a run may ask for.
POOL = season_moves.POOL
MAX_POOL = 60
MIN_GAIN = season_moves.MIN_GAIN
SEASON_LABEL = "rest of season, from the three weeks ahead"
#: Runs work here, off the event loop; the programs go to the background process pool.
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="strategy")


@dataclass(frozen=True)
class Settings:
    pool: int = POOL
    weights: tuple[str, ...] = st.WEIGHT_KEYS
    #: My players no move may drop.
    keep: tuple[int, ...] = ()
    #: The linear program's set wherever it solved, the search only its fallback (#110's B).
    program_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "weights": list(self.weights),
            "keep": list(self.keep),
            "program_only": self.program_only,
        }


def gains_of(moves: dict[str, Any]) -> dict[str, dict[int, float]]:
    """The Moves panel's best single-move gain of each candidate on each horizon."""
    out: dict[str, dict[int, float]] = {}
    for key in season_moves.HORIZONS:
        out[key] = {
            int(c): row[key]["gain"] for c, row in moves["candidates"].items() if row.get(key)
        }
    return out


def _r(x: float) -> float:
    return round(float(x), 3)


class Run:
    """One engine run, its points filled in as they land."""

    def __init__(
        self,
        key: tuple[Any, ...],
        built: season_moves.Built,
        prepare: Callable[[], dict[str, Any]],
        settings: Settings,
        workers: int | None,
    ) -> None:
        self.key = key
        self.built = built
        self.prepare = prepare
        self.settings = settings
        self.workers = workers
        self.done = threading.Event()
        self._lock = threading.Lock()
        self.status = "solving"
        self.step = "reading the moves"
        self.error: str | None = None
        self.started = datetime.now(UTC)
        self.finished: datetime | None = None
        self.cancelled = False
        wl = built.weeks_left
        self.weights = [w for w in st.weights(wl) if w.key in settings.weights]
        self.pool: list[int] = []
        self.base: dict[str, float] = {}
        #: Seconds from the start: the moves read, every search's set in (the first answer),
        #: and the end.
        self.timing: dict[str, float] = {}
        self._t0 = time.perf_counter()
        self.points: dict[str, dict[str, Any]] = {
            w.key: {
                "key": w.key,
                "label": w.label,
                "lambda": round(w.lam, 4),
                "natural": w.natural,
                "stage": "waiting",
            }
            for w in self.weights
        }

    # ------------------------------------------------------------------ the payload
    def payload(self) -> dict[str, Any]:
        b = self.built
        with self._lock:
            horizons: dict[str, Any] = {
                key: {**b.horizons[key], "base": _r(self.base[key]) if key in self.base else None}
                for key in season_moves.HORIZONS
            }
            horizons["season"] = {
                "label": SEASON_LABEL,
                "weeks_left": b.weeks_left,
                "base": _r(self.base["season"]) if "season" in self.base else None,
            }
            return {
                "status": self.status,
                "step": self.step,
                "error": self.error,
                "system": b.system,
                "weeks_left": b.weeks_left,
                "settings": self.settings.to_dict(),
                "pool": list(self.pool),
                "horizons": horizons,
                "adds": b.adds,
                "points": [self.points[w.key] for w in self.weights],
                "time_limit": st.TIME_LIMIT,
                "min_gain": MIN_GAIN,
                "started_at": self.started.isoformat(),
                "finished_at": self.finished.isoformat() if self.finished else None,
                "timing": dict(self.timing),
            }

    def _set(self, key: str, **changes: Any) -> None:
        with self._lock:
            self.points[key] = {**self.points[key], **changes}

    def _step(self, step: str) -> None:
        with self._lock:
            self.step = step

    def _mark(self, name: str) -> None:
        with self._lock:
            self.timing[name] = round(time.perf_counter() - self._t0, 2)

    # ------------------------------------------------------------------ the run
    def run(self) -> None:
        try:
            self._run()
            status, error = ("cancelled" if self.cancelled else "solved"), None
        except Exception as exc:  # noqa: BLE001 - the run says what failed
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        self._mark("done")
        with self._lock:
            self.status, self.error = status, error
            self.step = None if status == "solved" else self.step
            self.finished = datetime.now(UTC)
        self.done.set()

    def _run(self) -> None:
        p = self.built.problem
        wl = self.built.weeks_left
        keep = frozenset(self.settings.keep)
        gains = gains_of(self.prepare())
        self._mark("moves")
        self._step("searching")
        ev = mv.Evaluator(p)
        weighted = {w.key: st.Weighted(ev, w.lam, wl) for w in self.weights}
        any_w = st.Weighted(ev, 0.5, wl)
        pool = st.pool_of(gains, self.settings.pool)
        with self._lock:
            self.pool = pool
            self.base = {**ev.base, "season": any_w.season(ev.base.get("three", 0.0))}
        curves = st.curves(ev)
        searched: dict[str, tuple[mv.Move, ...]] = {}
        for w in self.weights:
            t0 = time.perf_counter()
            moves = mv.search(weighted[w.key], st.WEIGHTED, pool, keep=keep, min_gain=MIN_GAIN)
            searched[w.key] = moves
            block = self._block(weighted[w.key], moves, time.perf_counter() - t0)
            self._set(w.key, stage="searched", search=block, **self._shown(weighted[w.key], moves))
            if self.cancelled:
                return
        self._mark("first")
        # The programs run in other processes while the searches' sets are priced here.
        futures: dict[str, Future[st.Milp]] = {}
        if self.workers != 1:
            ex = background_pool()
            for w in self.weights:
                futures[w.key] = ex.submit(
                    st.solve_milp, p, curves, pool, w.lam, wl, keep, searched[w.key]
                )
        for w in self.weights:
            self._set(w.key, milp={"status": "pending"})
        recs: dict[str, mv.Recommendation] = {}
        for w in self.weights:
            self._step(f"pricing the search's set: {w.label}")
            t0 = time.perf_counter()
            rec = mv.recommend(
                weighted[w.key], st.WEIGHTED, pool, MIN_GAIN, start=searched[w.key], keep=keep
            )
            recs[w.key] = rec
            moves = tuple(pm.move for pm in rec.moves)
            seconds = self.points[w.key]["search"]["seconds"]
            self._set(
                w.key,
                stage="priced",
                search={
                    **self._block(weighted[w.key], moves, seconds),
                    "pricing": round(time.perf_counter() - t0, 2),
                },
                **self._shown(weighted[w.key], moves, rec),
            )
            if self.cancelled:
                return
        only = self.settings.program_only
        for w in self.weights:
            self._step(f"linear program: {w.label}")
            if w.key in futures:
                milp = futures[w.key].result()
            else:
                milp = st.solve_milp(p, curves, pool, w.lam, wl, keep, searched[w.key])
            if self.cancelled:
                return
            wt = weighted[w.key]
            rec = recs[w.key]
            best = tuple(pm.move for pm in rec.moves)
            source, moves = st.choose(wt, best, milp, only)
            note = None
            if source == st.MILP:
                self._step(f"pricing the linear program's set: {w.label}")
                rounds = 0 if only else 3
                rec = mv.recommend(wt, st.WEIGHTED, pool, MIN_GAIN, rounds, moves, keep)
                priced = tuple(pm.move for pm in rec.moves)
                if frozenset(priced) != frozenset(moves):
                    # A re-solve of the program's set beat it: the search's own answer.
                    source, note = st.SEARCH, "a re-solve of the linear program's set"
                moves = priced
            other = milp.moves if source == st.SEARCH else best
            ahead = None
            if source != st.BOTH and milp.status != st.FAILED:
                ahead = _r(wt.value(st.WEIGHTED, moves) - wt.value(st.WEIGHTED, other))
            fo = {}
            if milp.status != st.FAILED and milp.slopes:
                shown = {*pool, *(k for k, _ in p.roster)}
                fo = {
                    k: v
                    for k, v in st.first_order(p, curves, milp, w.lam, wl).items()
                    if k in shown
                }
            self._set(
                w.key,
                stage="done",
                milp={
                    **self._block(wt, milp.moves, milp.seconds),
                    "status": milp.status,
                    "size": dict(milp.size),
                    "model": {h: _r(v) for h, v in milp.model.items()},
                },
                source=source,
                note=note,
                ahead=ahead,
                first_order={str(k): _r(v) for k, v in fo.items()},
                **self._shown(wt, moves, rec),
            )

    # ------------------------------------------------------------------ the blocks
    def _block(self, wt: st.Weighted, moves: tuple[mv.Move, ...], seconds: float) -> dict[str, Any]:
        """A solver's set and its exact gains."""
        p = self.built.problem
        return {
            "seconds": round(seconds, 2),
            "moves": [season_moves._move(m, p) for m in moves],
            "gain": self._gains(wt, moves),
        }

    def _gains(self, wt: st.Weighted, moves: tuple[mv.Move, ...]) -> dict[str, float]:
        three = wt.ev.gain("three", moves)
        return {
            "week": _r(wt.ev.gain("week", moves)),
            "three": _r(three),
            "season": _r(wt.season(three)),
            "weighted": _r(wt.gain(st.WEIGHTED, moves)),
        }

    def _shown(
        self, wt: st.Weighted, moves: tuple[mv.Move, ...], rec: mv.Recommendation | None = None
    ) -> dict[str, Any]:
        """The point's recommended set: its moves (priced once ``rec`` is in), gains and the
        per-category before and after on both horizons."""
        p = self.built.problem
        if rec is None:
            rows = [{**season_moves._move(m, p), "priced": False} for m in moves]
        else:
            rows = [
                {
                    **season_moves._move(pm.move, p),
                    "priced": True,
                    "marginal": {h: _r(v) for h, v in pm.marginal.items()},
                    "price_without": _r(pm.price_without),
                    "price_keep": None if pm.price_keep is None else _r(pm.price_keep),
                    "instead_without": [season_moves._move(m, p) for m in pm.instead_without],
                    "instead_keep": None
                    if pm.instead_keep is None
                    else [season_moves._move(m, p) for m in pm.instead_keep],
                }
                for pm in rec.moves
            ]
        cats = {
            key: {
                "before": season_moves._cats(wt.ev, key, []),
                "after": season_moves._cats(wt.ev, key, list(moves)),
            }
            for key in season_moves.HORIZONS
        }
        return {"moves": rows, "gain": self._gains(wt, moves), "cats": cats}


class Runs:
    """The latest run of each league and system."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[tuple[str, str], Run] = {}

    def get(self, league: str, system: str, today: date, stamp: tuple[Any, ...]) -> Run | None:
        """The run made today from these inputs, else None."""
        with self._lock:
            run = self._runs.get((league, system))
        if run is None or run.key[:2] != (today, stamp):
            return None
        return run

    def start(
        self,
        league: str,
        system: str,
        key: tuple[Any, ...],
        make: Callable[[], Run],
    ) -> Run:
        """The run with ``key`` (today, the stamp and the settings), started unless one is
        running or done; an older run of the league is cancelled."""
        with self._lock:
            run = self._runs.get((league, system))
            if run is not None and run.key == key and run.status in {"solving", "solved"}:
                return run
            if run is not None:
                run.cancelled = True
            run = make()
            self._runs[league, system] = run
        _EXECUTOR.submit(run.run)
        return run
