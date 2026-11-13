"""The daily audit (#172, PR B2): the world holds every seat to the league's rules.

The policy decides; the world checks. Each simulated day, for every variant and every seat (the
rivals' seats too), the day is read at the point the day record is taken (``run.DayRecord``):
after the morning's moves have landed, the day's moves are queued and the lineup is set, before
the day's lines are scored. Each rule in :data:`RULES` is named and is a function of the setup,
the day (:class:`Day`) and the same variant's day before (None on the first day, when the
setup's rosters stand for it). It returns what it found, one ``(seat, what)`` a breach. A later
PR adds a rule by adding to the list.

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

from .engine import HELD, mv, wk
from .state import Roster, Setup, SimState

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
    seat queued today, which are charged to the day they are made) no more than the league's
    weekly limit. A drop the world forces when a held player returns is not an add."""
    limit = setup.max_weekly_adds
    if limit is None:
        return
    state = today.state
    for team in setup.teams:
        used = int(state.adds_used.get(team, 0)) + len(state.pending.get(team, ()))
        if used > limit:
            yield team, f"{used} adds this week on a cap of {limit}"


def lands_next_day(setup: Setup, today: Day, before: Day | None) -> Found:
    """A move decided on day d lands no earlier than d + 1: every player who joined a roster
    today is the add of a move the same team queued on the day before (the setup's rosters and
    no queue on the first day)."""
    was = _rosters_before(setup, before)
    queued = {} if before is None else before.state.pending
    for team, roster in sorted(today.state.rosters.items()):
        had = {k for k, _ in was.get(team, ())}
        due = {m.add for m in queued.get(team, ())}
        for k, _ in roster:
            if k not in had and k not in due:
                yield team, f"player {k} joined without a move queued the day before"


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


class Auditor:
    """The rules over one run's days: it keeps each variant's day before (so a rule may compare
    with it) and every breach found, stamped with the path."""

    def __init__(self, setup: Setup, rules: Sequence[Rule] | None = None, path: int | None = None):
        self.setup = setup
        self.rules = tuple(RULES if rules is None else rules)
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
    "OUT",
    "RULES",
    "Auditor",
    "Breach",
    "Day",
    "Rule",
    "held_kind",
    "lands_next_day",
    "lineup",
    "names",
    "one_place",
    "roster_slots",
    "weekly_adds",
]
