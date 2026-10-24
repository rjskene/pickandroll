"""The simulated league's state (#172, PR 2b): what a run starts from and what an arm holds.

A :class:`Setup` is a league as read once for a run: its calendar, pairings, teams, players,
rosters, free-agent pool, the policy's projection on day one, the schedule, the roster slots and
the rules; the readers (``api.season_sim``) build one from a season's parts or a replay's logs.
A :class:`SimState` is what one arm holds on one day: rosters, the pool, the adds used this week,
the moves landing tomorrow and every week's totals so far. The world (``run.World``) is apart:
truth, lines, availability and the shared beliefs belong to the path, never to an arm, so two
arms of a comparison see one world. Pure: frozen dataclasses, advanced by ``replace``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from ..calendar import Calendar, Week, monday_of
from ..moves import HELD, Move
from ..state import Player
from .league import LeagueSpec

Rates = Mapping[str, float]
#: A roster as the simulator holds it: each player with the slot he sits in.
Roster = tuple[tuple[int, str], ...]
#: Drafted players sit on the bench until the day's starters are chosen.
BENCH = "BN"


@dataclass(frozen=True)
class Member:
    """A player as the simulator knows him: key, name, NBA team and positions. Status and
    return date are the world's to tell (``run.World.seen``)."""

    key: int
    name: str
    nba_team: str | None
    positions: tuple[str, ...]

    def player(self, status: str | None = None) -> Player:
        return Player(self.key, self.name, self.nba_team, self.positions, status=status)


@dataclass(frozen=True)
class Setup:
    """A league as a run starts it."""

    league: str
    #: The first simulated day.
    start: date
    calendar: Calendar
    pairings: Mapping[int, tuple[tuple[int, int], ...]]
    teams: tuple[int, ...]
    players: Mapping[int, Member]
    rosters: Mapping[int, Roster]
    #: The free agents on day one.
    pool: tuple[int, ...]
    #: The policy's projection on day one (per-game rates in ``weekly.STATS`` names).
    projection: Mapping[int, Rates]
    schedule: Mapping[date, frozenset[str]]
    #: The league's roster positions in order, bench and held slots included.
    roster_slots: tuple[str, ...]
    cats: tuple[str, ...]
    scoring: str = "categories"
    points: Mapping[str, float] | None = None
    max_weekly_adds: int | None = None
    #: Statuses and return dates as read on day one, by player.
    statuses: Mapping[int, str] = field(default_factory=dict)
    returns: Mapping[int, date] = field(default_factory=dict)
    #: The gap between the policy's system and the market view, per player and stat (log scale).
    gap: Mapping[int, Mapping[str, float]] = field(default_factory=dict)
    #: The market's view of each player, higher better: the shared projection's per-game value,
    #: percent rostered breaking ties.
    market: Mapping[int, float] = field(default_factory=dict)
    #: The rate at which an opponent moves: adds per team-day over the recorded days.
    market_rate: float = 0.0
    #: The adds each team made this week before day one.
    adds_used: Mapping[int, int] = field(default_factory=dict)
    #: ESPN ids by player, for the fit's per-player figures; empty when unmatched.
    espn_ids: Mapping[int, str] = field(default_factory=dict)
    #: The bracket as read, or why it is not trusted (``league.BracketUnread``'s words).
    spec: LeagueSpec | None = None
    bracket_unread: str | None = None
    #: Regular weeks whose pairings were not read and were filled by a round robin.
    assumed_pairings: tuple[int, ...] = ()

    @property
    def season_end(self) -> date:
        return max(w.end for w in self.calendar.weeks)

    @property
    def days(self) -> list[date]:
        """Every day from the start to the season's end."""
        n = (self.season_end - self.start).days + 1
        return [self.start + timedelta(i) for i in range(max(0, n))]

    def week_of(self, day: date) -> Week | None:
        return self.calendar.week_of(day)

    def starting_slots(self) -> tuple[str, ...]:
        from ..weekly import starting_slots

        return starting_slots(self.roster_slots)

    def spots(self) -> int:
        """Active roster spots: the slots less the held ones."""
        return sum(1 for s in self.roster_slots if s not in HELD)


@dataclass(frozen=True)
class SimState:
    """One arm's position on one day."""

    day: date
    rosters: Mapping[int, Roster]
    pool: frozenset[int]
    #: Adds made this week, by team.
    adds_used: Mapping[int, int]
    #: Moves decided today that land tomorrow, by team.
    pending: Mapping[int, tuple[Move, ...]] = field(default_factory=dict)
    #: Every week's totals so far: week number to team to stat totals.
    totals: Mapping[int, Mapping[int, Mapping[str, float]]] = field(default_factory=dict)
    executed: int = 0
    gone: int = 0

    def key(self) -> tuple[Any, ...]:
        """What a decision depends on: two arms with the same key share one solve."""
        return (
            self.day,
            tuple(sorted((t, tuple(sorted(r))) for t, r in self.rosters.items())),
            tuple(sorted(self.pool)),
            tuple(sorted(self.adds_used.items())),
            tuple(sorted((t, m) for t, m in self.pending.items() if m)),
        )

    def active(self, team: int) -> tuple[int, ...]:
        return tuple(k for k, slot in self.rosters.get(team, ()) if slot not in HELD)

    def held(self, team: int) -> tuple[tuple[int, str], ...]:
        return tuple((k, slot) for k, slot in self.rosters.get(team, ()) if slot in HELD)

    def owner_of(self, player: int) -> int | None:
        for team, roster in self.rosters.items():
            if any(k == player for k, _ in roster):
                return team
        return None


def initial(setup: Setup) -> SimState:
    """Day one's state from the setup."""
    taken = {k for r in setup.rosters.values() for k, _ in r}
    return SimState(
        setup.start,
        {t: tuple(r) for t, r in setup.rosters.items()},
        frozenset(k for k in setup.pool if k not in taken),
        dict(setup.adds_used),
    )


def add_totals(state: SimState, week: int, team: int, line: Mapping[str, float]) -> SimState:
    """``line`` added to ``team``'s totals of ``week``."""
    weeks = dict(state.totals)
    teams = dict(weeks.get(week, {}))
    totals = dict(teams.get(team, {}))
    for stat, x in line.items():
        totals[stat] = totals.get(stat, 0.0) + float(x)
    teams[team] = totals
    weeks[week] = teams
    return replace(state, totals=weeks)


# --------------------------------------------------------------------------- a made-up league
def weeks_from(first: date, count: int) -> Calendar:
    """``count`` Monday-to-Sunday weeks from the Monday on or before ``first``, numbered from
    one: a replay's or a snake-drafted room's calendar."""
    monday = monday_of(first)
    weeks = tuple(
        Week(i + 1, monday + timedelta(7 * i), monday + timedelta(7 * i + 6)) for i in range(count)
    )
    return Calendar(weeks, estimated=True)


def round_robin(
    teams: Sequence[int], weeks: Iterable[int]
) -> dict[int, tuple[tuple[int, int], ...]]:
    """Every team against every other in turn (the circle method), a pairing a week, repeating
    once the round is done; an odd field gives one team a week off."""
    ids = list(teams)
    if len(ids) % 2:
        ids.append(-1)
    n = len(ids)
    rounds = []
    order = list(ids)
    for _ in range(n - 1):
        pairs = tuple(
            (order[i], order[n - 1 - i])
            for i in range(n // 2)
            if order[i] != -1 and order[n - 1 - i] != -1
        )
        rounds.append(tuple((min(a, b), max(a, b)) for a, b in pairs))
        order = [order[0], *order[-1:], *order[1:-1]]
    return {w: rounds[i % len(rounds)] for i, w in enumerate(weeks)}


def snake_draft(
    pool: Sequence[int], value: Mapping[int, float], teams: Sequence[int], spots: int
) -> dict[int, Roster]:
    """Twelve seats (or any) drafting the pool by ``value`` in a snake, ``spots`` players each,
    everyone on the bench: the day's starters are chosen when it is played."""
    ranked = sorted(pool, key=lambda k: (-value.get(k, 0.0), k))
    out: dict[int, list[tuple[int, str]]] = {t: [] for t in teams}
    order = list(teams)
    i = 0
    for rnd in range(spots):
        seats = order if rnd % 2 == 0 else order[::-1]
        for t in seats:
            if i >= len(ranked):
                break
            out[t].append((ranked[i], BENCH))
            i += 1
    return {t: tuple(r) for t, r in out.items()}
