"""The move model (#94, docs/ADD_DROP.md): which available player to add and whom to drop for
him, valued as expected categories won.

A roster's value over a horizon is the sum over the horizon's weeks of its expected categories
won (:func:`weekly.category_odds`), each week projected exactly as the season view projects it
(:func:`weekly.project_week`: the schedule, the out rule, a weekly export's games and the
starters chosen per day). A week is played against the teams of its :class:`WeekSpan`: the
named opponent, with the week so far, or the field, the other teams of the league, where the
odds against each team are taken on its own projected roster and then averaged.

A :class:`Move` is an add with a drop, or with nobody when a spot is open or a player can move to
a held slot. An add plays from the day his move counts: the first day for a free agent, the
clear date for a waiver claim. His drop plays until that same day (Yahoo's conditional drop
waits for the claim), so a drop paired with a free agent stops on the first day. A move counts
against the weekly add limit of the week it takes effect in.

The recommended moves come from an exact search on that value: every single move is evaluated
(:func:`single_swaps`), and a set under the add limit is built greedily, one best move at a
time, then improved by replacing any add or drop with any alternative until nothing gains
(:func:`search`). That is a strong heuristic, not a proof of optimality. The price of each
recommended move is the same search re-run with that add left out or that drop kept.

Players in held slots (IL, IL+, NA) stay on the roster, are never dropped and count as the
season view counts them. :data:`HELD_ACCEPTS` says which statuses each held slot takes. It is
a best guess, not yet checked against a league with IL slots: IL takes INJ, O and OFS, IL+ a
game-time decision as well, NA takes NA, and a suspension goes nowhere.

A held-slot move defers a drop; it does not avoid one (#97). The player moved comes back on
the first day of the first week the out rule lets him play (next Monday for an O), or on his
return date (``returns``, ESPN's) when later, and plays from then; INJ, OFS, SUSP and NA stay
out of every horizon and cost nothing. From the day he comes back the set drops its least
valuable active player by per-game value, him included (:func:`comebacks`). That is an
approximation: the starters' own ranking, not each choice re-valued.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from . import weekly as wk
from .state import Player, Transaction

#: The statuses each held slot accepts (unverified, see the module docstring). The order is the
#: order a player is placed in: the most restrictive slot first.
HELD_ACCEPTS: Mapping[str, frozenset[str]] = {
    "NA": frozenset({"NA"}),
    "IL": frozenset({"INJ", "O", "OFS"}),
    "IL+": frozenset({"INJ", "O", "OFS", "GTD"}),
}
#: Slots whose players are off the active roster.
HELD = frozenset(HELD_ACCEPTS)
#: Gains below this are equal: the search stops on them and a re-solve must beat it to count.
EPS = 1e-9

Member = tuple[int, Player]


@dataclass(frozen=True)
class WeekSpan:
    """One week of a horizon: the days a move can still affect, and whom it is played against."""

    days: tuple[date, ...]
    this_week: bool
    #: The opponents: the named one, or the field (every other team of the league).
    opponents: tuple[wk.TeamWeek, ...]
    #: The week so far, mine and each opponent's in the same order (empty for a later week).
    so_far: Mapping[str, float] = field(default_factory=dict)
    so_far_theirs: tuple[Mapping[str, float], ...] = ()
    #: A weekly export's games for the week, by player (``project_week``'s ``games``).
    games: Mapping[int, int] | None = None


@dataclass(frozen=True)
class AddLimit:
    """The adds a week allows for moves that take effect in it (None: no limit)."""

    start: date
    end: date
    adds: int | None


@dataclass(frozen=True)
class Move:
    add: int
    #: The player dropped for him, or None when the add takes an open spot or a held-slot move.
    drop: int | None = None


@dataclass(frozen=True)
class MoveProblem:
    #: My active players: the drop candidates.
    roster: tuple[Member, ...]
    #: My players in held slots.
    held: tuple[Member, ...]
    #: Active roster spots: the league's slots less the held ones.
    spots: int
    #: Open held slots, by kind.
    held_open: Mapping[str, int]
    #: The available players with a projection.
    candidates: tuple[Member, ...]
    #: The day each candidate's move takes effect: the first day, or a claim's clear date.
    effective: Mapping[int, date]
    #: The first day a move can count (today, or tomorrow once today's games began).
    first_day: date
    rates: Mapping[int, wk.Rates]
    schedule: Mapping[date, frozenset[str]]
    slots: tuple[str, ...]
    #: Per-game values that order the starters.
    value: Mapping[int, float]
    #: The categories the odds are taken on (``fpts`` alone in a points league).
    cats: tuple[str, ...]
    points: Mapping[str, float] | None
    no_games: frozenset[int]
    #: The horizons by key (``week``, ``three``), each a sequence of weeks.
    horizons: Mapping[str, tuple[WeekSpan, ...]]
    #: The weekly add limits, this week's net of the adds already made.
    limits: tuple[AddLimit, ...] = ()
    held_accepts: Mapping[str, frozenset[str]] = field(default_factory=lambda: HELD_ACCEPTS)
    #: My players held out until a day (an O's return date, when later than next Monday).
    returns: Mapping[int, date] = field(default_factory=dict)


# --------------------------------------------------------------------------- spots and limits
def open_spots(problem: MoveProblem) -> int:
    """Active spots free now, without a drop or a held-slot move."""
    return max(0, problem.spots - len(problem.roster))


def held_moves(problem: MoveProblem, dropped: Iterable[int] = ()) -> list[tuple[int, str]]:
    """The active players (not in ``dropped``) that could move to an open held slot, each with
    the slot, placed most restrictive slot first."""
    out_ = set(dropped)
    open_ = dict(problem.held_open)
    out: list[tuple[int, str]] = []
    for key, player in problem.roster:
        if key in out_:
            continue
        for slot, accepts in problem.held_accepts.items():
            if open_.get(slot, 0) > 0 and player.status in accepts:
                open_[slot] -= 1
                out.append((key, slot))
                break
    return out


def limit_of(problem: MoveProblem, day: date) -> AddLimit | None:
    return next((lim for lim in problem.limits if lim.start <= day <= lim.end), None)


def feasible(problem: MoveProblem, moves: Sequence[Move]) -> bool:
    """Whether the moves fit: distinct adds and drops, each add with a drop, an open spot or a
    held-slot move of a player not dropped, and each week's adds within its limit."""
    adds = [m.add for m in moves]
    drops = [m.drop for m in moves if m.drop is not None]
    if len(set(adds)) < len(adds) or len(set(drops)) < len(drops):
        return False
    free = sum(1 for m in moves if m.drop is None)
    if free > open_spots(problem) + len(held_moves(problem, drops)):
        return False
    counts: dict[AddLimit, int] = {}
    for m in moves:
        lim = limit_of(problem, problem.effective[m.add])
        if lim is not None and lim.adds is not None:
            counts[lim] = counts.get(lim, 0) + 1
            if counts[lim] > lim.adds:
                return False
    return True


def held_used(problem: MoveProblem, moves: Sequence[Move]) -> list[tuple[int, str]]:
    """The held-slot moves a set of moves needs: its adds without a drop beyond the open spots."""
    need = sum(1 for m in moves if m.drop is None) - open_spots(problem)
    if need <= 0:
        return []
    return held_moves(problem, [m.drop for m in moves if m.drop is not None])[:need]


@dataclass(frozen=True)
class Comeback:
    """A player moved to a held slot who comes back inside a horizon, and whom he sends."""

    player: int
    slot: str
    day: date
    #: The least valuable active player on that day, by per-game value (maybe himself).
    drop: int


def comes_back(
    problem: MoveProblem, key: int, player: Player, spans: Sequence[WeekSpan]
) -> date | None:
    """The day ``player`` comes back inside ``spans``: the first day of the first week the out
    rule (or a weekly export's games) lets him play, or his return date when later; None when
    he stays out through them."""
    back = problem.returns.get(key)
    for span in spans:
        if span.games is not None and key in span.games:
            out = span.games[key] <= 0
        else:
            out = wk.is_out(player, span.this_week, key in problem.no_games)
        days = [d for d in span.days if back is None or d >= back]
        if not out and days:
            return days[0]
    return None


def comebacks(problem: MoveProblem, key: str, moves: Iterable[Move]) -> list[Comeback]:
    """The deferred drops of ``moves`` over horizon ``key``: each held-slot move whose player
    comes back inside it sends the least valuable active player then, him included."""
    moves = list(moves)
    held = held_used(problem, moves)
    if not held:
        return []
    players = dict(problem.roster)
    dropped = {m.drop for m in moves if m.drop is not None}
    active = [k for k, _ in problem.roster if k not in dropped] + [m.add for m in moves]
    backs = []
    for k, slot in held:
        day = comes_back(problem, k, players[k], problem.horizons[key])
        if day is not None:
            backs.append((day, k, slot))
    out: list[Comeback] = []
    for day, k, slot in sorted(backs):
        weakest = min(active, key=lambda x: (problem.value.get(x, 0.0), str(x)))
        active.remove(weakest)
        out.append(Comeback(k, slot, day, weakest))
    return out


# --------------------------------------------------------------------------- the value
class Valued(Protocol):
    """What the searches value sets with: the :class:`Evaluator`, or a weighted horizon over it
    (the strategy engine's, #110)."""

    problem: MoveProblem
    #: The value of no moves on each horizon the searches may be asked about.
    base: Mapping[str, float]

    def value(self, key: str, moves: Iterable[Move]) -> float: ...

    def gain(self, key: str, moves: Iterable[Move]) -> float: ...


class Evaluator:
    """Values of move sets over the problem's horizons, remembered: the searches and their
    re-solves visit the same sets many times."""

    def __init__(self, problem: MoveProblem) -> None:
        self.problem = problem
        self._by_id = dict(problem.candidates)
        self._memo: dict[tuple[str, frozenset[Move]], float] = {}
        # The opponents' finals never change with my moves: once per week.
        self._theirs = {
            id(span): [
                wk.finals(opp, so_far, problem.cats)
                for opp, so_far in zip(
                    span.opponents,
                    span.so_far_theirs or tuple({} for _ in span.opponents),
                    strict=True,
                )
            ]
            for spans in problem.horizons.values()
            for span in spans
        }
        self.base = {key: self.value(key, ()) for key in problem.horizons}

    def value(self, key: str, moves: Iterable[Move]) -> float:
        """Expected categories won over horizon ``key`` with ``moves`` made, summed over its weeks."""
        moves = frozenset(moves)
        memo = (key, moves)
        if memo not in self._memo:
            members, gone = self._after(key, moves)
            self._memo[memo] = sum(
                self._week(span, members, gone) for span in self.problem.horizons[key]
            )
        return self._memo[memo]

    def gain(self, key: str, moves: Iterable[Move]) -> float:
        return self.value(key, moves) - self.base[key]

    def _after(self, key: str, moves: frozenset[Move]) -> tuple[list[Member], dict[int, date]]:
        p = self.problem
        gone = {m.drop: p.effective[m.add] for m in moves if m.drop is not None}
        for c in comebacks(p, key, moves):
            gone[c.drop] = c.day
        adds = [(m.add, self._by_id[m.add]) for m in moves]
        return [*p.held, *p.roster, *adds], gone

    def odds(self, key: str, moves: Iterable[Move]) -> list[list[list[wk.CategoryOdds]]]:
        """Each week's category odds over horizon ``key`` with ``moves`` made, one list per
        opponent."""
        members, gone = self._after(key, frozenset(moves))
        return [self._odds(span, members, gone) for span in self.problem.horizons[key]]

    def mine(self, key: str, moves: Iterable[Move]) -> list[wk.TeamWeek]:
        """My projected week for each week of horizon ``key`` with ``moves`` made."""
        members, gone = self._after(key, frozenset(moves))
        return [self._mine(span, members, gone) for span in self.problem.horizons[key]]

    def _week(self, span: WeekSpan, members: Sequence[Member], gone: Mapping[int, date]) -> float:
        odds = self._odds(span, members, gone)
        if not odds:
            return 0.0
        return sum(wk.expected_won(o) for o in odds) / len(odds)

    def _odds(
        self, span: WeekSpan, members: Sequence[Member], gone: Mapping[int, date]
    ) -> list[list[wk.CategoryOdds]]:
        if not span.opponents:
            return []
        finals = wk.finals(self._mine(span, members, gone), span.so_far, self.problem.cats)
        return [wk.odds_of(finals, theirs, self.problem.cats) for theirs in self._theirs[id(span)]]

    def _mine(
        self, span: WeekSpan, members: Sequence[Member], gone: Mapping[int, date]
    ) -> wk.TeamWeek:
        p = self.problem
        return wk.project_week(
            members,
            p.rates,
            span.days,
            p.schedule,
            p.slots,
            p.value,
            span.this_week,
            games=span.games,
            points=p.points,
            no_games=p.no_games,
            available_from={**p.effective, **p.returns},
            gone_from=gone,
        )


# --------------------------------------------------------------------------- one move
def drop_options(
    problem: MoveProblem, taken: Sequence[Move] = (), keep: Iterable[int] = ()
) -> list[int | None]:
    """Whom one more add can replace given the moves ``taken``: every active player not dropped
    or kept, and nobody (an open spot or a held-slot move)."""
    dropped = {m.drop for m in taken} | set(keep)
    return [None, *(key for key, _ in problem.roster if key not in dropped)]


@dataclass(frozen=True)
class SwapGain:
    #: The player dropped, or None when the add takes an open spot or a held-slot move.
    drop: int | None
    gain: float


def single_swaps(
    ev: Valued, key: str, candidates: Iterable[int] | None = None
) -> dict[int, list[SwapGain]]:
    """Each candidate's gain over horizon ``key`` with every drop he can come with, best first:
    the best of a single move with that add forced, and every other drop's price. A candidate
    whose move does not fit (the weekly limit) gets an empty list."""
    p = ev.problem
    pool = [c for c, _ in p.candidates] if candidates is None else list(candidates)
    out: dict[int, list[SwapGain]] = {}
    for cand in pool:
        gains = [
            SwapGain(drop, ev.gain(key, (Move(cand, drop),)))
            for drop in drop_options(p)
            if feasible(p, (Move(cand, drop),))
        ]
        gains.sort(key=lambda g: -g.gain)
        out[cand] = gains
    return out


# --------------------------------------------------------------------------- the search
def search(
    ev: Valued,
    key: str,
    pool: Sequence[int],
    exclude: Iterable[int] = (),
    keep: Iterable[int] = (),
    min_gain: float = 0.0,
) -> tuple[Move, ...]:
    """The recommended moves over horizon ``key`` among the candidates of ``pool``: greedy, one
    best move at a time while it gains more than ``min_gain``, then each add and each drop
    replaced by its best alternative, or the move undone, until no change gains. ``exclude``
    are adds and ``keep`` drops the search may not use (a re-solve's forced choice)."""
    p = ev.problem
    banned, kept = set(exclude), set(keep)
    adds_ok = [c for c in pool if c not in banned]
    moves: list[Move] = []
    current = ev.value(key, ())
    while True:
        used = {m.add for m in moves}
        best: tuple[float, Move] | None = None
        for cand in adds_ok:
            if cand in used:
                continue
            for drop in drop_options(p, moves, kept):
                trial = [*moves, Move(cand, drop)]
                if not feasible(p, trial):
                    continue
                v = ev.value(key, trial)
                if best is None or v > best[0]:
                    best = (v, Move(cand, drop))
        if best is None or best[0] - current <= max(min_gain, EPS):
            break
        current = best[0]
        moves.append(best[1])
    while moves:
        best_v, best_set = current, None
        for i, move in enumerate(moves):
            rest = moves[:i] + moves[i + 1 :]
            used = {m.add for m in rest}
            trials = [rest]
            trials += [
                [*rest, Move(c, move.drop)] for c in adds_ok if c not in used and c != move.add
            ]
            trials += [
                [*rest, Move(move.add, d)] for d in drop_options(p, rest, kept) if d != move.drop
            ]
            for trial in trials:
                if not feasible(p, trial):
                    continue
                v = ev.value(key, trial)
                # Undoing a move needs it to have been worth less than min_gain.
                bar = best_v - (min_gain if trial is rest else 0.0)
                if v > bar + EPS:
                    best_v, best_set = v, trial
        if best_set is None:
            break
        moves, current = best_set, best_v
    return tuple(moves)


@dataclass(frozen=True)
class PricedMove:
    move: Move
    #: What the move adds to the set on each horizon: the set's value less the set without it.
    marginal: Mapping[str, float]
    #: The set re-solved without this add, and with this drop kept: the recommended set's value
    #: less the re-solve's on the set's horizon (None for no drop to keep).
    price_without: float
    price_keep: float | None
    instead_without: tuple[Move, ...]
    instead_keep: tuple[Move, ...] | None


@dataclass(frozen=True)
class Recommendation:
    key: str
    moves: tuple[PricedMove, ...]
    #: The whole set's gain on each horizon.
    gain: Mapping[str, float]
    #: The held-slot moves the set needs (player, slot).
    held: tuple[tuple[int, str], ...]
    #: On each horizon, the drops the held players' returns force (:func:`comebacks`).
    comebacks: Mapping[str, tuple[Comeback, ...]] = field(default_factory=dict)


def recommend(
    ev: Valued,
    key: str,
    pool: Sequence[int],
    min_gain: float = 0.0,
    rounds: int = 3,
    start: Sequence[Move] | None = None,
    keep: Iterable[int] = (),
) -> Recommendation:
    """The recommended set over horizon ``key`` with every move priced by a re-solve. A re-solve
    that beats the set replaces it (the search is a heuristic), at most ``rounds`` times. The set
    is the search's, or ``start`` (another solver's); ``keep`` are drops nothing may use."""
    kept = frozenset(keep)
    moves = (
        tuple(start) if start is not None else search(ev, key, pool, keep=kept, min_gain=min_gain)
    )
    for attempt in range(rounds + 1):
        priced, better = _priced(ev, key, pool, moves, min_gain, kept)
        if better is None or attempt == rounds:
            gain = {h: ev.gain(h, moves) for h in ev.base}
            back = {h: tuple(comebacks(ev.problem, h, moves)) for h in ev.problem.horizons}
            return Recommendation(key, priced, gain, tuple(held_used(ev.problem, moves)), back)
        moves = better
    raise AssertionError("unreachable")


def _priced(
    ev: Valued,
    key: str,
    pool: Sequence[int],
    moves: tuple[Move, ...],
    min_gain: float,
    kept: frozenset[int] = frozenset(),
) -> tuple[tuple[PricedMove, ...], tuple[Move, ...] | None]:
    """Each move of ``moves`` priced by its two re-solves, and the best re-solve that beats the
    set, if one does."""
    value = ev.value(key, moves)
    priced: list[PricedMove] = []
    better: tuple[Move, ...] | None = None
    for move in moves:
        without = search(ev, key, pool, exclude={move.add}, keep=kept, min_gain=min_gain)
        keep = None
        if move.drop is not None:
            keep = search(ev, key, pool, keep=kept | {move.drop}, min_gain=min_gain)
        for alt in (without, keep):
            if alt is None or ev.value(key, alt) <= value + EPS:
                continue
            if better is None or ev.value(key, alt) > ev.value(key, better):
                better = alt
        rest = [m for m in moves if m != move]
        priced.append(
            PricedMove(
                move=move,
                marginal={h: ev.value(h, moves) - ev.value(h, rest) for h in ev.base},
                price_without=value - ev.value(key, without),
                price_keep=None if keep is None else value - ev.value(key, keep),
                instead_without=without,
                instead_keep=keep,
            )
        )
    return tuple(priced), better


# --------------------------------------------------------------------------- the weekly limit
_WHEN = re.compile(r"^([A-Z][a-z]{2})\w*\s+(\d{1,2})")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}


def when_date(when: str | None, today: date) -> date | None:
    """The date of a transaction as the page prints it (``Oct 20, 3:57 am``): the latest such
    date that is not after ``today``."""
    m = _WHEN.match((when or "").strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1)], int(m.group(2))
    for year in (today.year, today.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d <= today:
            return d
    return None


@dataclass(frozen=True)
class AddsUsed:
    count: int
    #: Whether the transactions read reach back past the week's start, so the count is all of
    #: them; otherwise it is a floor.
    complete: bool


def adds_used(
    transactions: Sequence[Transaction], team_id: int, start: date, end: date, today: date
) -> AddsUsed:
    """My adds in the week ``start``..``end``, from the league's transactions page (newest
    first, as far back as the page reaches)."""
    dates = [when_date(t.when, today) for t in transactions]
    groups = {
        t.group
        for t, d in zip(transactions, dates, strict=True)
        if t.kind == "add" and t.team_id == team_id and d is not None and start <= d <= end
    }
    known = [d for d in dates if d is not None]
    return AddsUsed(len(groups), not transactions or (bool(known) and min(known) < start))
