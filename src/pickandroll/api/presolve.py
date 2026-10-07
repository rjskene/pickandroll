"""Pre-solve on deck (#13): the plans for the boards my turn can start on, solved before it does.

A solve can only start once the board it is for exists, and in a Yahoo room the pick before
mine arrives the moment my clock starts. So while the picks before mine are still being made,
the solver plans the likely boards ahead: with one pick to go, one board per likely player;
with two, one per likely pair (the board depends only on who is gone, not in which order);
on my own turn with my next pick straight after it, the boards after my likely choices. Each
branch is a plan-only solve in the process pool. When a pick lands on a board that was
solved ahead, its plan is the recommendation at once; any other board is solved as usual.

Who is likely: Yahoo's ``o_rank`` (the order its autodraft follows, and the room's default
sort) interleaved with ADP (how people draft), best available first.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import pandas as pd

from ..draft.state import DraftState
from ..optim.horizon import HorizonProblem, HorizonSolution, solve_horizon

#: Branches per wave: one plan per pool worker, leaving room for the live solve's prices.
ONE_AWAY = 6  # likely players when one pick is left before mine
TWO_AWAY = 4  # likely players paired when two are left: C(4, 2) = 6 boards
MINE = 2  # my own likely choices on my turn, for the pick straight after it
#: A board that stays on the table this long is not a bot room's (bots pick about 2.3 s
#: apart): the one-away set then grows by one likely player per idle pool worker, up to
#: ``ONE_AWAY_MAX`` (#14 lever 5; see :func:`may_grow`). In mock 6 the pick one away from each
#: of my turns stood 2nd to 12th in :func:`likely_next`'s order.
GROW_AFTER_S = 4.0
ONE_AWAY_MAX = 12
#: Plan budget of a branch. It solves ahead of its board, off the clock, so it gets the plan's
#: full budget rather than a room's: in rounds 1-6 a plan needs 6-16 s to converge, and only a
#: converged branch is served unpriced.
BRANCH_TIME_LIMIT = 20.0

BoardKey = tuple[int, frozenset[str], frozenset[str]]


def board_key(state: DraftState) -> BoardKey:
    """What a plan depends on: the next pick, who is gone, and which of them are mine."""
    return (state.next_overall, state.taken, frozenset(state.my_roster))


def reachable(board: BoardKey, key: BoardKey) -> bool:
    """Whether the draft can still arrive at ``key`` from ``board``: nobody gone comes back."""
    return key[0] >= board[0] and key[1] >= board[1] and key[2] >= board[2]


def likely_next(
    state: DraftState, o_rank: pd.Series | None = None, limit: int = ONE_AWAY
) -> list[str]:
    """The available players most likely to go next: ``o_rank`` order and ADP order taken in
    turn, without repeats. ``o_rank`` maps player id to Yahoo's rank (missing or zero:
    unranked)."""
    taken = state.taken
    orders: list[list[str]] = []
    if o_rank is not None:
        ranked = o_rank[(o_rank > 0) & ~o_rank.index.isin(list(taken))].sort_values()
        orders.append([str(p) for p in ranked.index])
    adp = state.effective_adp()
    orders.append([str(p) for p in adp[~adp.index.isin(list(taken))].sort_values().index])
    out: list[str] = []
    for i in range(max((len(o) for o in orders), default=0)):
        for order in orders:
            if i < len(order) and order[i] not in out and order[i] in state.z.index:
                out.append(order[i])
                if len(out) >= limit:
                    return out
    return out


def may_grow(state: DraftState) -> bool:
    """Whether this board's one-away set may grow: exactly one pick, someone else's, is left
    before my next turn (keeper slots pass without a pick), and that turn is not the first of a
    back-to-back pair. A pair's own-choice boards for its second pick launch when its first goes
    on the clock, and grown branches still solving then hold the workers they need: in the #14
    slot-12 cell they queued behind them and came in after the live solve."""
    my_next = state.my_next_pick
    if my_next is None:
        return False
    mine = set(state.my_picks)
    kept = state.keeper_slots
    between = [o for o in range(state.next_overall, my_next) if o not in kept]
    return len(between) == 1 and between[0] not in mine and my_next + 1 not in mine


@dataclass(frozen=True)
class Branch:
    """A board my turn can start on: the picks that lead to it from the current one."""

    picks: tuple[tuple[int, str, str], ...]  # (overall, team, player id)
    key: BoardKey
    problem: HorizonProblem


def branch_boards(
    state: DraftState,
    likely: Sequence[str],
    mine: Sequence[str] = (),
    curve: Any = "default",
    *,
    one_away: int = ONE_AWAY,
    skip: Callable[[BoardKey], bool] | None = None,
) -> list[Branch]:
    """The boards to solve ahead from the current one; empty when my turn is not within two
    picks or the picks before it include one of mine.

    ``one_away``: likely players branched on with one pick left before mine. ``skip``: boards
    already planned, whose problems are not built again."""
    k = state.next_overall
    my_next = state.my_next_pick
    if my_next is None:
        return []
    my_picks = set(state.my_picks)
    team = state.my_team

    def owner(overall: int) -> str:
        return team if overall in my_picks else f"Team {state.owner_of(overall)[1]}"

    paths: list[tuple[tuple[int, str, str], ...]] = []
    # A keeper's slot is decided: the board passes it without a branch (his pick is logged
    # when the draft reaches it), so a keeper between makes my turn one pick nearer.
    kept = state.keeper_slots
    between = [o for o in range(k, my_next) if o not in kept]
    if not between:
        # On the clock: when my next pick follows straight on, branch on my own choice.
        if my_next + 1 in my_picks:
            paths = [((k, team, p),) for p in list(mine)[:MINE]]
    elif any(o in my_picks for o in between):
        return []
    elif len(between) == 1:
        (a,) = between
        paths = [((a, owner(a), p),) for p in list(likely)[:one_away]]
    elif len(between) == 2:
        a, b = between
        paths = [
            ((a, owner(a), x), (b, owner(b), y))
            for x, y in combinations(list(likely)[:TWO_AWAY], 2)
        ]
    out = []
    for path in paths:
        board = copy.copy(state)
        board.picks = list(state.picks)
        try:
            for overall, who, pid in path:
                board.apply_pick(who, pid, overall)
            key = board_key(board)
            if skip is not None and skip(key):
                continue
            problem = board.horizon_problem(curve=curve)
        except (KeyError, ValueError):
            continue
        out.append(Branch(picks=path, key=key, problem=problem))
    return out


def solve_branch(args: tuple[HorizonProblem, float, float]) -> HorizonSolution | None:
    """Plan one branch board (in a pool worker). ``None`` when no plan was found."""
    problem, time_limit, gap = args
    try:
        return solve_horizon(problem, time_limit=time_limit, gap=gap)
    except (RuntimeError, ValueError):
        return None


@dataclass
class Entry:
    branch: Branch
    started: float
    future: Future | None = None
    solution: HorizonSolution | None = None
    solve_ms: float | None = None


@dataclass
class BranchBook:
    """Branch plans by board, solved or in flight. Thread-safe: pool callbacks fill it."""

    entries: dict[BoardKey, Entry] = field(default_factory=dict)
    counted: set[BoardKey] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    launched: int = 0
    solved: int = 0
    hits: int = 0
    pending: int = 0
    misses: int = 0

    def known(self, key: BoardKey) -> bool:
        """Whether this board is solved or in flight."""
        with self.lock:
            return key in self.entries

    def wanted(self, branches: Sequence[Branch]) -> list[Branch]:
        """The branches not solved or in flight yet."""
        with self.lock:
            return [b for b in branches if b.key not in self.entries]

    def add(self, branch: Branch, future: Future) -> Entry:
        entry = Entry(branch=branch, started=time.perf_counter(), future=future)
        with self.lock:
            self.entries[branch.key] = entry
            self.launched += 1
        return entry

    def done(self, entry: Entry, solution: HorizonSolution | None) -> None:
        with self.lock:
            entry.solution = solution
            entry.solve_ms = (time.perf_counter() - entry.started) * 1000
            if solution is not None:
                self.solved += 1

    def take(self, key: BoardKey) -> Entry | None:
        """The entry for this board (solved or still running). The first look at a board
        counts as a hit (solved), pending (still solving: installed when it lands) or a miss."""
        with self.lock:
            entry = self.entries.get(key)
            if key not in self.counted:
                self.counted.add(key)
                if entry is None:
                    self.misses += 1
                elif (
                    entry.solution is None and entry.future is not None and not entry.future.done()
                ):
                    self.pending += 1
                else:
                    self.hits += 1
            return entry

    def prune(self, board: BoardKey) -> None:
        """Forget the boards the draft can no longer reach from ``board`` (it has moved past
        them, or a pick went another way) and cancel their solves that have not started, so a
        dead branch does not hold a worker the live ones need."""
        with self.lock:
            dead = [self.entries.pop(k) for k in list(self.entries) if not reachable(board, k)]
            self.counted = {k for k in self.counted if reachable(board, k)}
        # Outside the lock: cancelling a queued solve runs its done callback (``done``) at once,
        # in this thread, and that takes the lock.
        for entry in dead:
            if entry.future is not None:
                entry.future.cancel()

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "launched": self.launched,
                "solved": self.solved,
                "hits": self.hits,
                "pending": self.pending,
                "misses": self.misses,
                "held": len(self.entries),
            }
