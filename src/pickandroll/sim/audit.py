"""The daily audit (#172, PR B2): the world holds every seat to the league's rules.

The policy decides; the world checks. Each simulated day, for every variant and every seat (the
rivals' seats too), the day is read at the point the day record is taken (``run.DayRecord``):
after the morning's moves have landed, the day's moves are queued and the lineup is set, before
the day's lines are scored. Each rule in :data:`RULES` is named and is a function of the setup,
the day (:class:`Day`) and the same variant's day before (None on the first day, when the
setup's rosters stand for it). It returns what it found, one ``(seat, what)`` a breach. A later
PR adds a rule by adding to the list. A waiver league is held to :data:`WAIVER_RULES` too (PR
Fa, :func:`rules_of`): a run without waivers reads only :data:`RULES`. A FAAB league (PR Fb) is
held to the wait and :data:`BID_RULES` instead: its claims go by bid, not by priority alone. A
league under continuous waivers (PR Fc) is held to :data:`CLAIMS_ONLY` after them: every add is a
claim. A league whose bracket is read and has a round (PR bracket, :func:`has_round`) is held to
:data:`BRACKET_PAIRS` after :data:`RULES`: the round's pairs a state holds are the league's. A
same-day league (PR today, ``Setup.same_day``) is held to :data:`LANDS_SAME_DAY` in the place of
``lands_next_day``: a free agent's add lands the day it is decided.

A breach voids its path: the runner records it (:class:`Breach`), the commands leave the path out
of every aggregate, list the breaches in the payload and exit non-zero after writing. Nothing is
repaired. Pure: the setup and the day come in, the breaches go out.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import league as lg
from .engine import HELD, mv, wk
from .shapes import CONTINUOUS, DROPPED
from .state import FAILED, LOST, WON, Roster, Setup, SimState

#: The statuses a seat that has heard them never starts (``policy.starters_of``).
OUT = wk.OUT_ALL | wk.OUT_THIS_WEEK


@dataclass(frozen=True)
class Day:
    """The audit's view of one variant's day: the state after the morning's landings with the
    day's moves queued (``state.pending``), the statuses the seats have heard and every team's
    starters (player to slot). Lighter than the day record: no beliefs."""

    day: date
    variant: int
    state: SimState
    status: Mapping[int, str | None]
    starters: Mapping[int, Mapping[int, str]]
    #: A same-day league's (PR today): the state once every seat had decided and queued, before
    #: the day's free-agent adds landed (``state`` is after them, its queue empty). None in a
    #: league of the default rule.
    decided: SimState | None = None


@dataclass(frozen=True)
class Breach:
    """A rule broken: where (path, day, variant, seat), which rule and what was found."""

    day: date
    variant: int
    seat: int | None
    rule: str
    found: str
    path: int | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "day": self.day.isoformat(),
            "variant": self.variant,
            "seat": self.seat,
            "rule": self.rule,
            "found": self.found,
        }


Found = Iterable[tuple[int | None, str]]
Check = Callable[[Setup, Day, "Day | None"], Found]


@dataclass(frozen=True)
class Rule:
    name: str
    check: Check
    #: One line on what the rule holds, for the payload.
    holds: str


def _rosters_before(setup: Setup, before: Day | None) -> Mapping[int, Roster]:
    return setup.rosters if before is None else before.state.rosters


# --------------------------------------------------------------------------- the rules
def roster_slots(setup: Setup, today: Day, before: Day | None) -> Found:
    """Each roster within the league's slots: no more players than slots, no more active players
    than active spots, no more players in a held kind than the league has of it."""
    slots = Counter(setup.roster_slots)
    spots = setup.spots()
    for team, roster in sorted(today.state.rosters.items()):
        if len(roster) > len(setup.roster_slots):
            yield team, f"{len(roster)} players on {len(setup.roster_slots)} slots"
        active = sum(1 for _, slot in roster if slot not in HELD)
        if active > spots:
            yield team, f"{active} active players on {spots} active spots"
        held = Counter(slot for _, slot in roster if slot in HELD)
        for kind, n in sorted(held.items()):
            if n > slots.get(kind, 0):
                yield team, f"{n} in {kind}, the league has {slots.get(kind, 0)}"


def one_place(setup: Setup, today: Day, before: Day | None) -> Found:
    """Nobody on two rosters (or twice on one), nobody on a roster and on the wire."""
    where: dict[int, list[int]] = {}
    for team, roster in sorted(today.state.rosters.items()):
        for k, _ in roster:
            where.setdefault(k, []).append(team)
    for k, teams in sorted(where.items()):
        if len(teams) > 1:
            yield teams[0], f"player {k} on rosters {teams}"
        if k in today.state.pool:
            yield teams[0], f"player {k} on roster {teams[0]} and on the wire"


def weekly_adds(setup: Setup, today: Day, before: Day | None) -> Found:
    """The week's adds within the cap: the adds charged to this week (landed, with the ones the
    seat queued today, which are charged to the day they are made, and in a waiver league the
    claims in flight charged to it, the week of the day before each lands; PR Fa) no more than
    the league's weekly limit. A drop the world forces when a held player returns is not an
    add."""
    limit = setup.max_weekly_adds
    if limit is None:
        return
    state = today.state
    week = setup.week_of(today.day)
    for team in setup.teams:
        used = int(state.adds_used.get(team, 0)) + len(state.pending.get(team, ()))
        if week is not None:
            used += sum(1 for c in state.claims.get(team, ()) if c.week == week.number)
        if used > limit:
            yield team, f"{used} adds this week on a cap of {limit}"


def lands_next_day(setup: Setup, today: Day, before: Day | None) -> Found:
    """A move decided on day d lands no earlier than d + 1: every player who joined a roster
    today is the add of a move the same team queued on the day before, or of a claim it had
    open the day before whose player clears today (a claim lands on its clear date, never the
    day it is made; #172, PR Fa); the setup's rosters and no queue on the first day."""
    was = _rosters_before(setup, before)
    queued = {} if before is None else before.state.pending
    claims = {} if before is None else before.state.claims
    for team, roster in sorted(today.state.rosters.items()):
        had = {k for k, _ in was.get(team, ())}
        due = {m.add for m in queued.get(team, ())} | {
            c.move.add for c in claims.get(team, ()) if c.clears <= today.day
        }
        for k, _ in roster:
            if k not in had and k not in due:
                yield team, f"player {k} joined without a move queued the day before"


def lands_same_day(setup: Setup, today: Day, before: Day | None) -> Found:
    """A same-day league's rule (PR today), in the place of :func:`lands_next_day`: a free
    agent's add decided on day d lands on d, and a claim on its clear date as before. Every
    player who joined a roster today is the add of a move the same team queued today
    (``Day.decided``'s queue) or of a claim it had open the day before whose player clears
    today; each move queued today whose add is not on the team's roster was lost at the day's
    landing (counted in the team's ``gone_by`` there: an earlier team of the rotation took
    him, his drop had gone, or no spot was open); and a player a move that landed today
    dropped starts nowhere for that team today, so no line of his day is credited to the team
    that let him go."""
    was = _rosters_before(setup, before)
    decided = today.decided
    queued = {} if decided is None else decided.pending
    claims = {} if before is None else before.state.claims
    for team, roster in sorted(today.state.rosters.items()):
        had = {k for k, _ in was.get(team, ())}
        due = {m.add for m in queued.get(team, ())} | {
            c.move.add for c in claims.get(team, ()) if c.clears <= today.day
        }
        for k, _ in roster:
            if k not in had and k not in due:
                yield team, f"player {k} joined without a move queued today or a claim clearing"
    if decided is None:
        return
    for team in setup.teams:
        moves = queued.get(team, ())
        if not moves:
            continue
        on = {k for k, _ in today.state.rosters.get(team, ())}
        absent = sum(1 for m in moves if m.add not in on)
        lost = int(today.state.gone_by.get(team, 0)) - int(decided.gone_by.get(team, 0))
        if absent != lost:
            yield team, f"{absent} of today's adds not on the roster, {lost} lost at the landing"
        starters = today.starters.get(team, {})
        for m in moves:
            if m.add in on and m.drop is not None and m.drop in starters:
                yield team, f"player {m.drop} starts the day his drop landed"


def held_kind(setup: Setup, today: Day, before: Day | None) -> Found:
    """A held slot takes only a player its kind accepts (``moves.eligible``) on the day he is
    placed: his status as the seat has heard it that day."""
    was = _rosters_before(setup, before)
    for team, roster in sorted(today.state.rosters.items()):
        had = set(was.get(team, ()))
        for k, slot in roster:
            if slot in HELD and (k, slot) not in had:
                status = today.status.get(k)
                if not mv.eligible(status, slot):
                    yield team, f"player {k} placed in {slot} with status {status!r}"


def lineup(setup: Setup, today: Day, before: Day | None) -> Found:
    """Each starter on his team's active roster and eligible for the slot he fills, no more
    starters in a slot than the league starts there, every starter's team playing that day and
    nobody started whom the seat had heard was out."""
    starting = Counter(setup.starting_slots())
    playing = setup.schedule.get(today.day, frozenset())
    for team, starters in sorted(today.starters.items()):
        active = set(today.state.active(team))
        used = Counter(starters.values())
        for slot, n in sorted(used.items()):
            if n > starting.get(slot, 0):
                yield team, f"{n} starters in {slot}, the league starts {starting.get(slot, 0)}"
        for k, slot in sorted(starters.items()):
            member = setup.players.get(k)
            if k not in active:
                yield team, f"starter {k} is not on the active roster"
            if member is None or not wk.accepts(slot, member.positions):
                yield team, f"starter {k} is not eligible for {slot}"
            if member is None or member.nba_team not in playing:
                yield team, f"starter {k}'s team does not play on {today.day}"
            if today.status.get(k) in OUT:
                yield team, f"starter {k} started though heard {today.status.get(k)}"


def waiver_wait(setup: Setup, today: Day, before: Day | None) -> Found:
    """No player who left a roster joins one before his clear date (PR Fa): everyone who joined
    a roster today was not on waivers the day before, or clears today or earlier."""
    if before is None:
        return
    was = before.state.rosters
    waiting = before.state.waivers
    for team, roster in sorted(today.state.rosters.items()):
        had = {k for k, _ in was.get(team, ())}
        for k, _ in roster:
            wait = waiting.get(k)
            if k not in had and wait is not None and wait.clears > today.day:
                yield team, f"player {k} joined before his clear date {wait.clears}"


def claim_priority(setup: Setup, today: Day, before: Day | None) -> Found:
    """Every contested claim went to the best priority that morning, and the winner is last
    after it (PR Fa): the morning's decisions (``state.resolved``), replayed on the day before's
    order, each won by the first team in that order with a claim open on its player (a team
    whose claim failed passed over), each winner then moved to the back; every lost claim's
    player went to another team; the order after them is the state's; every winner holds its
    player."""
    if before is None or not today.state.resolved:
        return
    order = list(before.state.priority)
    log = today.state.resolved
    won = {r.add: r.team for r in log if r.outcome == WON}
    for i, r in enumerate(log):
        if r.outcome == LOST:
            if won.get(r.add) in (None, r.team):
                yield r.team, f"claim on player {r.add} lost to no other team"
            continue
        if r.outcome not in (WON, FAILED):
            yield r.team, f"claim on player {r.add} decided as {r.outcome!r}"
            continue
        # The teams still holding an open claim at this point of the morning: every claim is
        # decided from here on, a claim lost to this one right after it.
        later = {x.team for x in log[i:]}
        first = next((t for t in order if t in later), None)
        if r.team != first:
            yield (
                r.team,
                (f"claim on player {r.add} {r.outcome} by team {r.team} with team {first} ahead"),
            )
        if r.outcome == WON:
            if r.team in order:
                order.remove(r.team)
            order.append(r.team)
            if r.add not in {k for k, _ in today.state.rosters.get(r.team, ())}:
                yield r.team, f"won claim on player {r.add} not on its roster"
    if tuple(order) != tuple(today.state.priority):
        yield None, f"priority after the morning {today.state.priority}, expected {tuple(order)}"


def budget_floor(setup: Setup, today: Day, before: Day | None) -> Found:
    """No team's dollars go below zero (PR Fb)."""
    for team, left in sorted(today.state.dollars.items()):
        if left < 0:
            yield team, f"dollars left {left}, below zero"


def _placed(before: Day | None) -> dict[tuple[int, int], int]:
    """The bids of the claims open the day before, by team and add."""
    if before is None:
        return {}
    return {(t, c.move.add): c.bid for t, cs in before.state.claims.items() for c in cs}


def bid_paid(setup: Setup, today: Day, before: Day | None) -> Found:
    """A won claim costs exactly its bid, and nothing else moves the dollars (PR Fb): each team's
    dollars left are the day before's (the budget on the first day) less the bids, as placed, of
    the claims it won this morning."""
    was = dict.fromkeys(setup.teams, setup.budget) if before is None else dict(before.state.dollars)
    bids = _placed(before)
    paid: Counter[int] = Counter()
    for r in today.state.resolved:
        if r.outcome != WON:
            continue
        bid = bids.get((r.team, r.add))
        if bid is None or r.bid != bid:
            yield r.team, f"won claim on player {r.add} paid {r.bid}, placed at {bid}"
        paid[r.team] += int(r.bid or 0)
    for team in sorted(set(was) | set(today.state.dollars)):
        expected = was.get(team, setup.budget) - paid[team]
        if today.state.dollars.get(team) != expected:
            yield team, f"dollars left {today.state.dollars.get(team)}, expected {expected}"


def bid_order(setup: Setup, today: Day, before: Day | None) -> Found:
    """Each player went to the highest bid among the claims open on him that morning that could
    be taken, a tie to the better priority (PR Fb): the morning's decisions (``state.resolved``)
    replayed on the day before's claims and order. Every claim on a won player that stood ahead
    of the winner (a higher bid, or the same bid and a better place in the order then) failed;
    every lost claim's player went to another team on a bid at least its own; the order rolls
    only on a win that broke a tie (another claim on him open with the same bid); the order
    after the morning is the state's; every winner holds its player."""
    if before is None or not today.state.resolved:
        return
    order = list(before.state.priority)
    bids = _placed(before)
    log = today.state.resolved
    won = {r.add: r for r in log if r.outcome == WON}
    on: dict[int, list[int]] = {}
    for team, add in bids:
        on.setdefault(add, []).append(team)
    failed: set[tuple[int, int]] = set()
    for r in log:
        if r.outcome == FAILED:
            failed.add((r.team, r.add))
            continue
        if r.outcome == LOST:
            w = won.get(r.add)
            if w is None or w.team == r.team or int(w.bid or 0) < int(r.bid or 0):
                yield r.team, f"claim on player {r.add} lost to no higher or equal bid"
            continue
        if r.outcome != WON:
            yield r.team, f"claim on player {r.add} decided as {r.outcome!r}"
            continue
        bid = int(r.bid or 0)
        rivals = [t for t in on.get(r.add, ()) if t != r.team]
        for t in rivals:
            other = bids[(t, r.add)]
            ahead = other > bid or (
                other == bid and t in order and order.index(t) < order.index(r.team)
            )
            if ahead and (t, r.add) not in failed:
                what = f"claim on player {r.add} won by team {r.team} at {bid}"
                yield r.team, f"{what} with team {t} ahead at {other}"
        if any(bids[(t, r.add)] == bid and (t, r.add) not in failed for t in rivals):
            if r.team in order:
                order.remove(r.team)
            order.append(r.team)
        if r.add not in {k for k, _ in today.state.rosters.get(r.team, ())}:
            yield r.team, f"won claim on player {r.add} not on its roster"
    if tuple(order) != tuple(today.state.priority):
        yield None, f"priority after the morning {today.state.priority}, expected {tuple(order)}"


def claims_only(setup: Setup, today: Day, before: Day | None) -> Found:
    """Nobody joins a roster but by a claim won that morning (PR Fc, continuous waivers): every
    player who joined a roster today is the add of a claim its team won on this morning's
    decisions (``state.resolved``). The draft's rosters stand for the day before the first."""
    was = _rosters_before(setup, before)
    won = {(r.team, r.add) for r in today.state.resolved if r.outcome == WON}
    for team, roster in sorted(today.state.rosters.items()):
        had = {k for k, _ in was.get(team, ())}
        for k, _ in roster:
            if k not in had and (team, k) not in won:
                yield team, f"player {k} joined without a claim won this morning"


def bracket_pairs(setup: Setup, today: Day, before: Day | None) -> Found:
    """On every day of a round of the bracket (PR bracket), the round's pairs the state holds
    for the week (``SimState.seeded``) are the pairs the league gives from the state's totals
    that day (``league.round_pairs``: the season's own bracket, which does not read the round's
    own week), and no team is in two of them. So a round that was never seeded, pairs another
    rule than the league's made, and pairs the totals of a finished week no longer give are each
    found; at the season's end the pairs held are the rounds the bracket played."""
    spec = setup.spec
    week = setup.week_of(today.day)
    if spec is None or week is None or week.number not in lg.round_weeks(spec):
        return
    held = today.state.seeded.get(week.number)
    if held is None:
        yield (
            None,
            f"week {week.number} is a round of the bracket and the state holds no pairs for it",
        )
        return
    due = lg.round_pairs(spec, today.state.totals, week.number)
    if tuple(held) != due:
        yield None, f"week {week.number}'s pairs {tuple(held)}, the league gives {due}"
    seen = Counter(team for pair in held for team in pair)
    for team, n in sorted(seen.items()):
        if n > 1:
            yield team, f"team {team} is in {n} pairs of week {week.number}"


#: The rules every day of every run is held to, in the order they are read.
RULES: tuple[Rule, ...] = (
    Rule(
        "roster_slots", roster_slots, "rosters within the slots, the active spots, each held kind"
    ),
    Rule("one_place", one_place, "nobody on two rosters, nobody on a roster and on the wire"),
    Rule("weekly_adds", weekly_adds, "the week's adds, landed and queued, within the cap"),
    Rule("lands_next_day", lands_next_day, "a move decided on day d lands on d + 1 or later"),
    Rule("held_kind", held_kind, "a held slot takes only a player its kind accepts that day"),
    Rule("lineup", lineup, "starters eligible, within the slots, playing, not heard out"),
)


#: The rules a waiver league's days are held to as well (PR Fa), after :data:`RULES`.
WAIVER_RULES: tuple[Rule, ...] = (
    Rule("waiver_wait", waiver_wait, "nobody who left a roster joins one before his clear date"),
    Rule(
        "claim_priority",
        claim_priority,
        "each contested claim to the best priority that morning, the winner then last",
    ),
)
#: A FAAB league's rules besides the wait (PR Fb), in place of ``claim_priority``, a priority
#: run's rule.
BID_RULES: tuple[Rule, ...] = (
    Rule("budget_floor", budget_floor, "no team's dollars below zero"),
    Rule("bid_paid", bid_paid, "a won claim costs exactly its bid, and nothing else moves dollars"),
    Rule(
        "bid_order",
        bid_order,
        "each player to the highest bid that could be taken, a tie to the better priority",
    ),
)


#: A same-day league's landing rule (PR today), in the place of ``lands_next_day``.
LANDS_SAME_DAY = Rule(
    "lands_same_day",
    lands_same_day,
    "a free agent's add decided on day d lands on d or is lost there, a claim on its clear date",
)


#: A league's rule under continuous waivers (PR Fc), after its waivers' rules.
CLAIMS_ONLY = Rule(
    "claims_only", claims_only, "nobody joins a roster but by a claim won that morning"
)


#: The rule of a league whose bracket is read and has a round (PR bracket), after :data:`RULES`.
BRACKET_PAIRS = Rule(
    "bracket_pairs",
    bracket_pairs,
    "on a day of a bracket round, the round's pairs a state holds are the league's from its totals",
)


def has_round(setup: Setup) -> bool:
    """Whether ``setup``'s bracket is read and has a round to play (``league.round_weeks``): the
    league :data:`BRACKET_PAIRS` is read in."""
    return setup.spec is not None and bool(lg.round_weeks(setup.spec))


def rules_of(
    waivers: str = "none", rule: str = DROPPED, bracket: bool = False, same_day: bool = False
) -> tuple[Rule, ...]:
    """The rules a run under ``waivers`` (``shapes.WAIVERS``) and the waiver ``rule``
    (``shapes.WAIVER_RULES``, PR Fc) is held to: :data:`RULES`, with :data:`LANDS_SAME_DAY` in
    the place of ``lands_next_day`` in a ``same_day`` league (PR today, ``Setup.same_day``;
    False by default); then :data:`BRACKET_PAIRS` when the league's ``bracket`` is read and has
    a round (PR bracket, :func:`has_round`; False by default, so a caller that names no bracket
    reads the rules as before); and after them :data:`WAIVER_RULES` in a league by priority, or
    the wait and :data:`BID_RULES` in a FAAB league, and :data:`CLAIMS_ONLY` last under
    continuous waivers."""
    own = (
        tuple(LANDS_SAME_DAY if r.name == "lands_next_day" else r for r in RULES)
        if same_day
        else RULES
    )
    base = (*own, BRACKET_PAIRS) if bracket else own
    if waivers == "none":
        return base
    more = (CLAIMS_ONLY,) if rule == CONTINUOUS else ()
    if waivers == "faab":
        return (*base, WAIVER_RULES[0], *BID_RULES, *more)
    return (*base, *WAIVER_RULES, *more)


class Auditor:
    """The rules over one run's days: it keeps each variant's day before (so a rule may compare
    with it) and every breach found, stamped with the path. The rules default to the setup's
    (:func:`rules_of` its waivers, its waiver rule and whether its bracket has a round)."""

    def __init__(self, setup: Setup, rules: Sequence[Rule] | None = None, path: int | None = None):
        self.setup = setup
        own = rules_of(setup.waivers, setup.waiver_rule, has_round(setup), setup.same_day)
        self.rules = tuple(own if rules is None else rules)
        self.path = path
        self.breaches: list[Breach] = []
        self._before: dict[int, Day] = {}

    def check(self, today: Day) -> list[Breach]:
        before = self._before.get(today.variant)
        found = [
            Breach(today.day, today.variant, seat, rule.name, what, self.path)
            for rule in self.rules
            for seat, what in rule.check(self.setup, today, before)
        ]
        self._before[today.variant] = today
        self.breaches.extend(found)
        return found


def names(rules: Sequence[Rule] | None = None) -> list[dict[str, str]]:
    """The rules for a payload."""
    return [{"name": r.name, "holds": r.holds} for r in (RULES if rules is None else rules)]


__all__ = [
    "BID_RULES",
    "BRACKET_PAIRS",
    "CLAIMS_ONLY",
    "OUT",
    "RULES",
    "WAIVER_RULES",
    "Auditor",
    "Breach",
    "Day",
    "Rule",
    "bid_order",
    "bid_paid",
    "bracket_pairs",
    "budget_floor",
    "claim_priority",
    "claims_only",
    "has_round",
    "held_kind",
    "lands_next_day",
    "lineup",
    "names",
    "one_place",
    "roster_slots",
    "rules_of",
    "waiver_wait",
    "weekly_adds",
]
