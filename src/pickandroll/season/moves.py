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

The season guard (#164, docs/ADD_DROP.md "The season guard") is a line every set searched must
hold beside :func:`feasible`: its moves' rest-of-season values, each move valued on its own from
its day as the decision log values it, sum to zero or more (:func:`season_guard`). The search,
its re-solves and the streaming plan never offer a set below it; nothing inside the allowed sets
ranks on it.

Players in held slots (IL, IL+, NA) stay on the roster, count as the season view counts them and
are dropped only as a churn (#221, below). :data:`HELD_ACCEPTS` says which statuses each held slot takes (#124,
docs/ADD_DROP.md, "Held slots"). IL is Yahoo's own rule for basketball, from its help page
(https://help.yahoo.com/kb/SLN6863.html): Out (O) and Out For Season (OFS) go there; Probable,
Questionable and Doubtful do not. IL+ and NA are unverified: the help page names neither for
basketball, IL+ comes from Yahoo's 2021 announcement (INJ, OFS, O and GTD), NA from its
baseball and hockey rules, and no league read so far has either slot. A status the table does
not know (:data:`KNOWN_STATUSES`) goes nowhere, and a suspension goes nowhere.

A player in a held slot whose status no longer fits it (his status cleared, :func:`cleared`)
makes the roster illegal: Yahoo refuses every add until he is activated, and activating him
takes an active spot. The move model activates him on the first day and drops the least
valuable active player then, him included, in every set and in none (:func:`comebacks`).

A held-slot move defers a drop; it does not avoid one (#97). The player moved comes back on
the first day of the first week the out rule lets him play (next Monday for an O), or on his
return date (``returns``, ESPN's) when later, and plays from then; INJ, OFS, SUSP and NA stay
out of every horizon and cost nothing. From the day he comes back the set drops its least
valuable active player by per-game value, him included, never one the keep rule keeps
(:func:`comebacks`). That is an approximation: the starters' own ranking, not each choice
re-valued. Several eligible players for fewer open slots: the latest to return goes first, roster
order breaking ties (:func:`held_moves`).

A player already in a held slot who comes back inside a horizon is charged the same way (#221,
the ruling's fifth condition): from his day back the set drops its least valuable active player,
him included, unless the set leaves an active spot open for him, in the base and in every set
(:func:`comebacks`). Without it the base counts his games and never the drop they force.

A **churn** (#221) is an add whose drop is a held player H: dropping H opens H's held slot,
an add still needs an active spot, so either one is open or an eligible injured active player
Y moves into the freed slot (:func:`held_moves`' ``freed``) and gives the add his spot. A churn
is offered only when its add is a free agent, or H is worth nothing net of his return
(:func:`churn_ok`): H goes first, on his own, and a lost claim must not leave him dropped for
something. A held player the keep rule keeps, or whose status cleared, is never H.

Ties go to the season (#221, the sixth condition): given ``season``, a set's rest of the
season, the searches take of two sets equal on their horizon the one worth more over the
season (:func:`search`), as a churn and the plain swap that drops Y instead tie when both are out
past the horizon.

The keep rule (#124, the user's of 2026-10-22, docs/AUTOPILOT.md section 4) is a forced keep, not
a value term: the three-week horizon, and the season the strategy engine reads from it, value a
player out three weeks at about nothing. A player of mine is **protected** when he is net positive
(his rest-of-season per-game value above the pool's average, ``average``), the best
available add's value does not beat his by the floor or more (``value + floor > best``, #164: a
higher floor protects more), and he returns this season (:func:`back_from`). A
player who passes the last two but not the first and is back within :data:`SHORT_ABSENCE_DAYS`
is kept on the bench for the solve. Neither is ever a drop on any horizon (``kept``,
:func:`drop_options`); a protected player out still goes to a held slot when one is open. His
value net of return (:func:`net_of_return`) only ranks the IL and is shown, never protects.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol

from . import weekly as wk
from .state import Player, Transaction

#: By how much the best add's rest-of-season per-game value must beat a player's to take him
#: off the protected list, by default: the keep rule's protection floor (#124, its side #164), a
#: knob the hill-climb may raise for more protection and bring back down, never below this
#: (docs/AUTOPILOT.md section 6, #150).
PROTECTION_FLOOR = 0.0

#: The statuses each held slot accepts (see the module docstring for the sources). The order is
#: the order a player is placed in: the most restrictive slot first.
HELD_ACCEPTS: Mapping[str, frozenset[str]] = {
    "NA": frozenset({"NA"}),
    "IL": frozenset({"O", "OFS"}),
    "IL+": frozenset({"INJ", "O", "OFS", "GTD"}),
}
#: Slots whose players are off the active roster.
HELD = frozenset(HELD_ACCEPTS)
#: The held slots whose rule Yahoo's help page states for basketball; the others are unverified.
HELD_CONFIRMED = frozenset({"IL"})
#: Every status the eligibility table knows: Yahoo's feed (P, Q, D, O, NA), the help page's
#: (OFS) and the 2021 announcement's (INJ, GTD), and a suspension. Another is eligible nowhere.
KNOWN_STATUSES = frozenset({"P", "Q", "D", "O", "OFS", "INJ", "GTD", "SUSP", "NA"})
#: Gains below this are equal: the search stops on them and a re-solve must beat it to count.
EPS = 1e-9
#: An absence shorter than this many days keeps a player better than the best add on the bench.
SHORT_ABSENCE_DAYS = 7
#: An NBA team's games per day over a season (82 in about 174 days): the rate for the days the
#: schedule has not been read, for a team with no read day.
GAMES_PER_DAY = 82 / 174

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
    #: In a streaming plan (#136) the drop may be an earlier move's add.
    drop: int | None = None
    #: The day the move counts from, at or after the add's effective day (a streaming plan's
    #: step); None for the effective day itself, as every single move has it.
    day: date | None = None


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
    #: The slot each of my held players sits in (``held``'s keys).
    held_slots: Mapping[int, str] = field(default_factory=dict)
    #: The keep rule's values (#124): each player's rest-of-season per-game value, mine and the
    #: candidates', Basketball Monster's line under the league's scorer whatever the system.
    season_value: Mapping[int, float] = field(default_factory=dict)
    #: The per-game value of an empty line under that scorer (a dead spot), and the pool's
    #: average (0 for a categories league's z-sums, the best players' mean in a points league).
    dead: float = 0.0
    average: float = 0.0
    #: The last day of the season's calendar.
    season_end: date | None = None
    #: By how much the best add's per-game value must beat a player's to unprotect him (a knob).
    floor: float = PROTECTION_FLOOR
    #: My players no move may drop: those the keep rule keeps (:func:`keep_rule`).
    kept: frozenset[int] = frozenset()
    #: The streaming plan's floor and its moves a day (knobs, #152); None for the stream's own
    #: defaults (``season.stream``).
    plan_floor: float | None = None
    daily_cap: int | None = None
    #: The candidates on waivers: an add of one is a claim, which may be lost (#221).
    claims: frozenset[int] = frozenset()


def day_of(problem: MoveProblem, move: Move) -> date:
    """The day ``move`` counts from: its own day, else its add's effective day."""
    return move.day if move.day is not None else problem.effective[move.add]


def timeline(
    problem: MoveProblem, moves: Iterable[Move]
) -> tuple[dict[int, date], dict[int, date]]:
    """A set of dated moves as a roster timeline: the day each add is available from and the
    day each dropped player is gone from (a streaming plan's earlier add among them)."""
    available, gone = {}, {}
    for m in moves:
        day = day_of(problem, m)
        available[m.add] = day
        if m.drop is not None:
            # A churn's held drop goes first, on its own (#221).
            gone[m.drop] = problem.first_day if is_churn(problem, m) else day
    return available, gone


# --------------------------------------------------------------------------- eligibility
def eligible(
    status: str | None, slot: str, accepts: Mapping[str, frozenset[str]] = HELD_ACCEPTS
) -> bool:
    """Whether a player of ``status`` may sit in held slot ``slot``."""
    return status is not None and status in accepts.get(slot, frozenset())


def held_slots_for(
    status: str | None, accepts: Mapping[str, frozenset[str]] = HELD_ACCEPTS
) -> tuple[str, ...]:
    """The held slots a player of ``status`` may sit in, most restrictive first."""
    return tuple(slot for slot in accepts if eligible(status, slot, accepts))


def is_cleared(
    status: str | None, slot: str, accepts: Mapping[str, frozenset[str]] = HELD_ACCEPTS
) -> bool:
    """Whether a player of ``status`` sitting in held slot ``slot`` no longer fits it: he blocks
    every add until he is activated. The one test the move model, the moves payload and the
    lineup route all use."""
    return slot in HELD and not eligible(status, slot, accepts)


def cleared(problem: MoveProblem) -> list[tuple[int, str]]:
    """My held players whose status no longer fits their slot, each with the slot: each blocks
    every add until he is activated."""
    players = dict(problem.held)
    return [
        (key, slot)
        for key, slot in problem.held_slots.items()
        if key in players and is_cleared(players[key].status, slot, problem.held_accepts)
    ]


# --------------------------------------------------------------------------- spots and limits
def open_spots(problem: MoveProblem) -> int:
    """Active spots free now, without a drop or a held-slot move."""
    return max(0, problem.spots - len(problem.roster))


def held_moves(
    problem: MoveProblem, dropped: Iterable[int] = (), freed: Mapping[str, int] | None = None
) -> list[tuple[int, str]]:
    """The active players (not in ``dropped``) that could move to an open held slot, each with
    the slot, placed most restrictive slot first: the latest to return first, roster order
    breaking ties (:func:`stash_order`). ``freed`` are the held slots a set's churns open."""
    out_ = set(dropped)
    open_ = dict(problem.held_open)
    for slot, n in (freed or {}).items():
        open_[slot] = open_.get(slot, 0) + n
    out: list[tuple[int, str]] = []
    for key, player in stash_order(problem):
        if key in out_:
            continue
        for slot in problem.held_accepts:
            if open_.get(slot, 0) > 0 and eligible(player.status, slot, problem.held_accepts):
                open_[slot] -= 1
                out.append((key, slot))
                break
    return out


def stash_order(problem: MoveProblem) -> tuple[Member, ...]:
    """My active players in the order a held slot takes them: the latest to return first (one
    out for the season before any), roster order breaking ties. Kept on the problem once made:
    every feasibility check of the searches asks for it."""
    cached = problem.__dict__.get("_stash_order")
    if cached is not None:
        return cached

    def later(item: tuple[int, Member]) -> tuple[int, int, int]:
        i, (key, player) = item
        back = back_from(problem, key, player)
        return (0, 0, i) if back is None else (1, -back.toordinal(), i)

    order = tuple(m for _, m in sorted(enumerate(problem.roster), key=later))
    object.__setattr__(problem, "_stash_order", order)
    return order


def held_kinds(problem: MoveProblem) -> tuple[str, ...]:
    """The league's held slot kinds, each of its slots open or taken, in placement order."""
    kinds = set(problem.held_open) | set(problem.held_slots.values())
    order = list(problem.held_accepts)
    return tuple(sorted(kinds, key=lambda s: (order.index(s) if s in order else len(order), s)))


@dataclass(frozen=True)
class Room:
    """The room an add without a drop has (#187)."""

    #: Active spots free now (:func:`open_spots`).
    open_spots: int
    #: Every held kind of the league with its open slots, a full one at zero.
    held_open: Mapping[str, int]
    #: My active players whose status fits one of those kinds, open or full, in the order a
    #: held slot takes them (:func:`stash_order`).
    eligible: tuple[int, ...]


def room(problem: MoveProblem) -> Room:
    """The room an add without a drop has today: the open active spots, the open slots of each
    held kind and who could go to one. It states the problem; the search decides the moves."""
    kinds = held_kinds(problem)
    accepts = problem.held_accepts
    return Room(
        open_spots(problem),
        {k: problem.held_open.get(k, 0) for k in kinds},
        tuple(
            key
            for key, player in stash_order(problem)
            if any(eligible(player.status, k, accepts) for k in kinds)
        ),
    )


def limit_of(problem: MoveProblem, day: date) -> AddLimit | None:
    return next((lim for lim in problem.limits if lim.start <= day <= lim.end), None)


def is_churn(problem: MoveProblem, move: Move) -> bool:
    """Whether ``move`` drops a held player (#221)."""
    return move.drop is not None and move.drop in problem.held_slots


def needs_spot(problem: MoveProblem, move: Move) -> bool:
    """Whether ``move``'s add needs an active spot of its own: no drop, or a held player's (a
    churn frees a held slot, not an active one)."""
    return move.drop is None or is_churn(problem, move)


def freed_by(problem: MoveProblem, moves: Iterable[Move]) -> dict[str, int]:
    """The held slots a set's churns open, by kind."""
    out: dict[str, int] = {}
    for m in moves:
        slot = problem.held_slots.get(m.drop) if m.drop is not None else None
        if slot is not None:
            out[slot] = out.get(slot, 0) + 1
    return out


def churn_ok(problem: MoveProblem, move: Move) -> bool:
    """Whether a churn may be offered (#221, the ruling's first answer): its add lands at once
    (a free agent), or the held player is worth nothing net of his return, so a lost claim
    costs nothing."""
    if move.add not in problem.claims or move.drop is None:
        return True
    player = dict(problem.held).get(move.drop)
    net = None if player is None else net_of_return(problem, move.drop, player)
    return net is not None and net <= EPS


def feasible(problem: MoveProblem, moves: Sequence[Move]) -> bool:
    """Whether the moves fit: distinct adds and drops, each add with a drop of an active player,
    or an active spot (an open one, or one a held-slot move of a player not dropped frees,
    churns' freed slots included), each churn allowed (:func:`churn_ok`), and each week's adds
    within its limit."""
    adds = [m.add for m in moves]
    drops = [m.drop for m in moves if m.drop is not None]
    if len(set(adds)) < len(adds) or len(set(drops)) < len(drops):
        return False
    if any(is_churn(problem, m) and not churn_ok(problem, m) for m in moves):
        return False
    need = sum(1 for m in moves if needs_spot(problem, m))
    if need > open_spots(problem) + len(held_moves(problem, drops, freed_by(problem, moves))):
        return False
    counts: dict[AddLimit, int] = {}
    for m in moves:
        lim = limit_of(problem, day_of(problem, m))
        if lim is not None and lim.adds is not None:
            counts[lim] = counts.get(lim, 0) + 1
            if counts[lim] > lim.adds:
                return False
    return True


#: A test every set searched must pass beside :func:`feasible` (the season guard's,
#: :func:`season_guard`).
Allowed = Callable[[Sequence[Move]], bool]
#: A set's rest of the season, the searches' tie-break (#221): :func:`season_total`'s.
Season = Callable[[Sequence[Move]], float]


def admitted(problem: MoveProblem, moves: Sequence[Move], allowed: Allowed | None) -> bool:
    """:func:`feasible`, and allowed by ``allowed`` when a guard is given."""
    return feasible(problem, moves) and (allowed is None or allowed(moves))


def season_total(ros: Callable[[Move], float | None], moves: Iterable[Move]) -> tuple[float, bool]:
    """A set's rest of the season by ``ros`` (each move's own value, None for none) and whether
    the total is partial: a move without a value counts as zero."""
    values = [ros(m) for m in moves]
    return sum(v for v in values if v is not None), any(v is None for v in values)


def season_guard(ros: Callable[[Move], float | None]) -> Allowed:
    """The season guard (#164): a set is allowed when its rest of the season
    (:func:`season_total`) is zero or more. A move without a value neither blocks the set nor
    pays for the rest of it."""

    def allowed(moves: Sequence[Move]) -> bool:
        return season_total(ros, moves)[0] >= -EPS

    return allowed


def held_used(problem: MoveProblem, moves: Sequence[Move]) -> list[tuple[int, str]]:
    """The held-slot moves a set of moves needs: its adds that need an active spot
    (:func:`needs_spot`) beyond the open spots."""
    need = sum(1 for m in moves if needs_spot(problem, m)) - open_spots(problem)
    if need <= 0:
        return []
    drops = [m.drop for m in moves if m.drop is not None]
    return held_moves(problem, drops, freed_by(problem, moves))[:need]


@dataclass(frozen=True)
class Comeback:
    """A player moved to a held slot who comes back inside a horizon, and whom he sends."""

    player: int
    slot: str
    day: date
    #: The least valuable active player on that day, by per-game value (maybe himself).
    drop: int
    #: A player already in a held slot whose return is charged (#221), not a set's held move.
    returning: bool = False


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


def returning(
    problem: MoveProblem, key: str, dropped: Iterable[int] = ()
) -> list[tuple[date, int, str]]:
    """My held players (not cleared, not in ``dropped``) who come back inside horizon ``key``,
    each with his day back and his slot (#221)."""
    out_ = set(dropped) | {k for k, _ in cleared(problem)}
    out = []
    for k, player in problem.held:
        slot = problem.held_slots.get(k)
        if k in out_ or slot is None:
            continue
        day = comes_back(problem, k, player, problem.horizons[key])
        if day is not None:
            out.append((day, k, slot))
    return out


def comebacks(problem: MoveProblem, key: str, moves: Iterable[Move]) -> list[Comeback]:
    """The deferred drops of ``moves`` over horizon ``key``: each held-slot move whose player
    comes back inside it sends the least valuable active player then, him included; each held
    player whose status cleared (:func:`cleared`) does so on the first day, moves or none; and
    each held player not dropped who comes back inside it (:func:`returning`) does so on his
    day back, unless the set leaves an active spot open for him (#221)."""
    moves = list(moves)
    held = held_used(problem, moves)
    back_now = cleared(problem)
    dropped = {m.drop for m in moves if m.drop is not None}
    back_later = returning(problem, key, dropped)
    if not held and not back_now and not back_later:
        return []
    players = dict(problem.roster)
    # A streaming plan's add that a later step drops is not there to send.
    active = [k for k, _ in problem.roster if k not in dropped]
    active += [m.add for m in moves if m.add not in dropped]
    # The active spots the set leaves open: a returning player takes one before he sends anyone.
    spare = problem.spots - (len(active) - len(held))
    active += [k for k, _ in back_now]
    backs = [(problem.first_day, k, slot, False) for k, slot in back_now]
    for k, slot in held:
        day = comes_back(problem, k, players[k], problem.horizons[key])
        if day is not None:
            backs.append((day, k, slot, False))
    backs += [(day, k, slot, True) for day, k, slot in back_later]
    out: list[Comeback] = []
    for day, k, slot, back in sorted(backs):
        if back:
            active.append(k)
            if spare > 0:
                spare -= 1
                continue
        # Never a player the keep rule keeps, while another can go.
        pool = [x for x in active if x not in problem.kept] or active
        weakest = min(pool, key=lambda x: (problem.value.get(x, 0.0), str(x)))
        active.remove(weakest)
        out.append(Comeback(k, slot, day, weakest, back))
    return out


# --------------------------------------------------------------------------- the keep rule
def back_from(problem: MoveProblem, key: int, player: Player) -> date | None:
    """The day ``player`` is back, as the keep rule reads it, never before his own first day (a
    candidate's move's): the day the move model brings him back inside the horizons
    (:func:`comes_back`: an O next Monday, a weekly export's games, a later return date); else
    his return date; else None when he does not return this season (OFS, or INJ, SUSP or NA with
    no return date), and the day after the horizons for one out through them all."""
    if player.status == "OFS":
        return None
    start = problem.effective.get(key, problem.first_day)
    spans = (*problem.horizons.get("week", ()), *problem.horizons.get("three", ()))
    day = comes_back(problem, key, player, spans)
    if day is not None:
        return max(start, day)
    ret = problem.returns.get(key)
    if ret is not None:
        return max(start, ret)
    if player.status in wk.OUT_ALL:
        return None
    last = max((d for span in spans for d in span.days), default=start)
    return max(start, last + timedelta(days=1))


def games_ahead(problem: MoveProblem, nba_team: str | None, start: date) -> tuple[int, float]:
    """The games ``nba_team`` plays from ``start`` to the season's last day, apart: the
    schedule's on the days it was read, and the team's rate over its read days on the others
    (:data:`GAMES_PER_DAY` when no day was read), extrapolated."""
    end = problem.season_end
    if end is None or not nba_team or start > end:
        return 0, 0.0
    read = list(problem.schedule)
    rate = sum(nba_team in problem.schedule[d] for d in read) / len(read) if read else 0.0
    rate = rate if read else GAMES_PER_DAY
    inside = [d for d in read if start <= d <= end]
    unread = (end - start).days + 1 - len(inside)
    return sum(nba_team in problem.schedule[d] for d in inside), unread * rate


def games_left(problem: MoveProblem, nba_team: str | None, start: date) -> float:
    """The games ``nba_team`` plays from ``start`` to the season's last day (:func:`games_ahead`,
    read and extrapolated together)."""
    read, extrapolated = games_ahead(problem, nba_team, start)
    return read + extrapolated


def net_of_return(problem: MoveProblem, key: int, player: Player) -> float | None:
    """His value net of return: his per-game value above a dead spot times his games from his
    return to the season's last day; 0 when he does not return, None without a season value.
    It ranks the IL and is shown; it never protects."""
    value = problem.season_value.get(key)
    if value is None:
        return None
    back = back_from(problem, key, player)
    if back is None:
        return 0.0
    return (value - problem.dead) * games_left(problem, player.nba_team, back)


@dataclass(frozen=True)
class Kept:
    """The keep rule on one of my players."""

    player: int
    #: His rest-of-season per-game value (None: no line) and the day he is back.
    value: float | None
    back: date | None
    #: Above the pool's average; not beaten by the best add's by the floor; back this season.
    net_positive: bool
    beats_best: bool
    returns: bool
    #: All three; or the last two and back within :data:`SHORT_ABSENCE_DAYS` (on the bench).
    protected: bool
    bench: bool


@dataclass(frozen=True)
class KeepRule:
    #: The best available add by rest-of-season per-game value, and that value.
    best: int | None
    best_value: float | None
    floor: float
    #: The rule on each of my active players.
    players: Mapping[int, Kept]
    #: The rule on each of my held players (#221): one it keeps is never a churn's drop.
    held: Mapping[int, Kept] = field(default_factory=dict)

    @property
    def kept(self) -> frozenset[int]:
        """The players no move may drop, active and held."""
        rows = [*self.players.items(), *self.held.items()]
        return frozenset(k for k, x in rows if x.protected or x.bench)


def kept_of(
    problem: MoveProblem, key: int, player: Player, best_value: float | None, floor: float
) -> Kept:
    """The keep rule's three tests on ``player`` against the best add's value."""
    value = problem.season_value.get(key)
    back = back_from(problem, key, player)
    net = value is not None and value > problem.average
    beats = value is not None and (best_value is None or value + floor > best_value)
    returns = back is not None
    protected = net and beats and returns
    away = back is not None and 0 < (back - problem.first_day).days < SHORT_ABSENCE_DAYS
    return Kept(key, value, back, net, beats, returns, protected, not protected and beats and away)


def keep_rule(problem: MoveProblem) -> KeepRule:
    """The keep rule on my active players, and apart on my held ones (#221), against the best
    available add (by rest-of-season per-game value, among the candidates with a line)."""
    priced = [
        (c, problem.season_value[c]) for c, _ in problem.candidates if c in problem.season_value
    ]
    best = max(priced, key=lambda x: (x[1], -x[0]), default=None)
    best_value = best[1] if best else None
    return KeepRule(
        best[0] if best else None,
        best_value,
        problem.floor,
        {k: kept_of(problem, k, pl, best_value, problem.floor) for k, pl in problem.roster},
        {k: kept_of(problem, k, pl, best_value, problem.floor) for k, pl in problem.held},
    )


# --------------------------------------------------------------------------- the IL advice
#: The advice for one of my players with an absence (#124, "can and should").
STASH, IL_FULL, BENCH, DROPPABLE = "stash", "il_full", "bench", "droppable"


@dataclass(frozen=True)
class Leave:
    """Who should leave a full held slot for an eligible active player."""

    player: int
    slot: str
    #: ``activate`` (a cleared occupant: the weakest active player is dropped) or ``drop``.
    how: str
    #: The player the move drops: the weakest active one, or the occupant himself.
    drop: int
    #: The occupant's value net of return, and whether the keep rule would protect him.
    net: float | None
    protected: bool


@dataclass(frozen=True)
class Advice:
    player: int
    status: str | None
    back: date | None
    #: The league's held slots his status allows, and the one the held move gives him (None:
    #: none open).
    slots: tuple[str, ...]
    slot: str | None
    protected: bool
    bench: bool
    #: His value net of return (:func:`net_of_return`).
    net: float | None
    #: :data:`STASH`, :data:`IL_FULL`, :data:`BENCH` or :data:`DROPPABLE`.
    advice: str
    leave: Leave | None = None


def leave_for(problem: MoveProblem, kinds: Iterable[str], rule: KeepRule) -> Leave | None:
    """Who should leave a full held slot of ``kinds``: a cleared occupant first, activated with
    the weakest active player dropped as his comeback drops him, else the occupant with the
    least value net of return, dropped; protected or not, marked."""
    kinds = set(kinds)
    held = dict(problem.held)
    sitting = [(k, s) for k, s in problem.held_slots.items() if s in kinds and k in held]
    if not sitting:
        return None
    back_now = [(k, s) for k, s in cleared(problem) if s in kinds]
    if back_now:
        k, s = back_now[0]
        sends = {c.player: c.drop for c in comebacks(problem, "week", ())}
        return Leave(k, s, "activate", sends.get(k, k), None, False)

    def net(item: tuple[int, str]) -> tuple[float, int]:
        k, _ = item
        v = net_of_return(problem, k, held[k])
        return (v if v is not None else 0.0, k)

    k, s = min(sitting, key=net)
    who = kept_of(problem, k, held[k], rule.best_value, rule.floor)
    return Leave(k, s, "drop", k, net((k, s))[0], who.protected)


def stash_advice(problem: MoveProblem, rule: KeepRule) -> list[Advice]:
    """For each of my active players with an absence (back after the first day, or not this
    season; a doubt who may play today is none): whether a held slot takes him, whether one is
    open, and what to do. A protected player goes to the open slot (:data:`STASH`), names who should leave a
    full one (:data:`IL_FULL`), or waits on the bench (:data:`BENCH`) when no slot takes him; a
    player the short-absence rule keeps waits on the bench; any other may be dropped
    (:data:`DROPPABLE`): the search decides."""
    assigned = dict(held_moves(problem))
    kinds = held_kinds(problem)
    out: list[Advice] = []
    for key, player in problem.roster:
        k = rule.players[key]
        if k.back is not None and k.back <= problem.first_day:
            continue
        slots = tuple(s for s in held_slots_for(player.status, problem.held_accepts) if s in kinds)
        slot = assigned.get(key)
        leave = None
        if k.protected and slot is not None:
            advice = STASH
        elif k.protected and slots:
            advice, leave = IL_FULL, leave_for(problem, slots, rule)
        elif k.protected or k.bench:
            advice = BENCH
        else:
            advice = DROPPABLE
        net = net_of_return(problem, key, player)
        out.append(
            Advice(
                key, player.status, k.back, slots, slot, k.protected, k.bench, net, advice, leave
            )
        )
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
            members, available, gone = self._after(key, moves)
            self._memo[memo] = sum(
                self._week(span, members, available, gone) for span in self.problem.horizons[key]
            )
        return self._memo[memo]

    def gain(self, key: str, moves: Iterable[Move]) -> float:
        return self.value(key, moves) - self.base[key]

    def _after(
        self, key: str, moves: frozenset[Move]
    ) -> tuple[list[Member], dict[int, date], dict[int, date]]:
        """The members with ``moves`` made, the day each add is available from and the day each
        dropped player is gone from (the comebacks' drops among them)."""
        p = self.problem
        available, gone = timeline(p, moves)
        for c in comebacks(p, key, moves):
            gone[c.drop] = c.day
        adds = [(m.add, self._by_id[m.add]) for m in moves]
        return [*p.held, *p.roster, *adds], available, gone

    def odds(self, key: str, moves: Iterable[Move]) -> list[list[list[wk.CategoryOdds]]]:
        """Each week's category odds over horizon ``key`` with ``moves`` made, one list per
        opponent."""
        members, available, gone = self._after(key, frozenset(moves))
        return [self._odds(span, members, available, gone) for span in self.problem.horizons[key]]

    def mine(self, key: str, moves: Iterable[Move]) -> list[wk.TeamWeek]:
        """My projected week for each week of horizon ``key`` with ``moves`` made."""
        members, available, gone = self._after(key, frozenset(moves))
        return [
            project_mine(self.problem, span, members, gone, available)
            for span in self.problem.horizons[key]
        ]

    def _week(
        self,
        span: WeekSpan,
        members: Sequence[Member],
        available: Mapping[int, date],
        gone: Mapping[int, date],
    ) -> float:
        odds = self._odds(span, members, available, gone)
        if not odds:
            return 0.0
        return sum(wk.expected_won(o) for o in odds) / len(odds)

    def _odds(
        self,
        span: WeekSpan,
        members: Sequence[Member],
        available: Mapping[int, date],
        gone: Mapping[int, date],
    ) -> list[list[wk.CategoryOdds]]:
        if not span.opponents:
            return []
        mine = project_mine(self.problem, span, members, gone, available)
        finals = wk.finals(mine, span.so_far, self.problem.cats)
        return [wk.odds_of(finals, theirs, self.problem.cats) for theirs in self._theirs[id(span)]]


def project_mine(
    problem: MoveProblem,
    span: WeekSpan,
    members: Sequence[Member] | None = None,
    gone: Mapping[int, date] | None = None,
    available: Mapping[int, date] | None = None,
) -> wk.TeamWeek:
    """My week over ``span`` with ``members`` (my roster, held slots included, when None), each
    player in ``gone`` stopped from his day on (a drop): his starts go to the bench. An add
    plays from his day in ``available`` (a dated move's, #136), else from his effective day."""
    p = problem
    return wk.project_week(
        [*p.held, *p.roster] if members is None else members,
        p.rates,
        span.days,
        p.schedule,
        p.slots,
        p.value,
        span.this_week,
        games=span.games,
        points=p.points,
        no_games=p.no_games,
        available_from={**p.effective, **p.returns, **(available or {})},
        gone_from=gone or {},
    )


# --------------------------------------------------------------------------- one move
def drop_options(
    problem: MoveProblem, taken: Sequence[Move] = (), keep: Iterable[int] = ()
) -> list[int | None]:
    """Whom one more add can replace given the moves ``taken``: nobody (an open spot or a
    held-slot move), every active player not dropped, kept (``keep``) or kept by the keep rule
    (``problem.kept``), and after them every such held player whose status has not cleared, a
    churn's drop (#221; :func:`feasible` says whether the churn is allowed)."""
    dropped = {m.drop for m in taken} | set(keep) | problem.kept
    back_now = {k for k, _ in cleared(problem)}
    held = [k for k, _ in problem.held if k not in dropped and k not in back_now]
    return [None, *(key for key, _ in problem.roster if key not in dropped), *held]


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
    allowed: Allowed | None = None,
    season: Season | None = None,
) -> tuple[Move, ...]:
    """The recommended moves over horizon ``key`` among the candidates of ``pool``: greedy, one
    best move at a time while it gains more than ``min_gain``, then each add and each drop
    replaced by its best alternative, or the move undone, until no change gains. ``exclude``
    are adds and ``keep`` drops the search may not use (a re-solve's forced choice); every set
    tried must pass ``allowed`` (the season guard) beside :func:`feasible`. Of two sets equal on
    ``key`` the one ``season`` values more is taken (#221: ties go to the season)."""
    p = ev.problem
    banned, kept = set(exclude), set(keep)
    adds_ok = [c for c in pool if c not in banned]
    moves: list[Move] = []
    current = ev.value(key, ())

    def tied_better(v: float, trial: Sequence[Move], than: float, other: Sequence[Move]) -> bool:
        return season is not None and abs(v - than) <= EPS and season(trial) > season(other) + EPS

    def better(v: float, trial: Sequence[Move], than: float, other: Sequence[Move]) -> bool:
        if season is None:
            return v > than
        return v > than + EPS or tied_better(v, trial, than, other)

    while True:
        used = {m.add for m in moves}
        best: tuple[float, Move] | None = None
        for cand in adds_ok:
            if cand in used:
                continue
            for drop in drop_options(p, moves, kept):
                trial = [*moves, Move(cand, drop)]
                if not admitted(p, trial, allowed):
                    continue
                v = ev.value(key, trial)
                if best is None or better(v, trial, best[0], [*moves, best[1]]):
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
                if not admitted(p, trial, allowed):
                    continue
                v = ev.value(key, trial)
                # Undoing a move needs it to have been worth less than min_gain.
                bar = best_v - (min_gain if trial is rest else 0.0)
                now = moves if best_set is None else best_set
                tie = trial is not rest and tied_better(v, trial, bar, now)
                if v > bar + EPS or tie:
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
    allowed: Allowed | None = None,
    season: Season | None = None,
) -> Recommendation:
    """The recommended set over horizon ``key`` with every move priced by a re-solve. A re-solve
    that beats the set replaces it (the search is a heuristic), at most ``rounds`` times. The set
    is the search's, or ``start`` (another solver's, which the caller has allowed); ``keep`` are
    drops nothing may use; the search and every re-solve keep to ``allowed`` and break ties on
    ``season``."""
    kept = frozenset(keep)
    moves = (
        tuple(start)
        if start is not None
        else search(ev, key, pool, keep=kept, min_gain=min_gain, allowed=allowed, season=season)
    )
    for attempt in range(rounds + 1):
        priced, better = _priced(ev, key, pool, moves, min_gain, kept, allowed, season)
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
    allowed: Allowed | None = None,
    season: Season | None = None,
) -> tuple[tuple[PricedMove, ...], tuple[Move, ...] | None]:
    """Each move of ``moves`` priced by its two re-solves (each kept to ``allowed``, ties broken
    on ``season``), and the best re-solve that beats the set, if one does."""
    value = ev.value(key, moves)
    priced: list[PricedMove] = []
    better: tuple[Move, ...] | None = None
    for move in moves:
        without = search(
            ev, key, pool, {move.add}, kept, min_gain=min_gain, allowed=allowed, season=season
        )
        keep = None
        if move.drop is not None:
            keep = search(
                ev,
                key,
                pool,
                keep=kept | {move.drop},
                min_gain=min_gain,
                allowed=allowed,
                season=season,
            )
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
