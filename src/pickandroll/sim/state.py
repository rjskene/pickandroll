"""The simulated league's state (#172, PR 2b): what a run starts from and what an arm holds.

A :class:`Setup` is a league as read once for a run: its calendar, pairings, teams, players,
rosters, free-agent pool, the policy's projection on day one, the schedule, the roster slots and
the rules; ``run.replay_setup`` drafts one on a recorded season's logs. A :class:`SimState` is
what one arm holds on one day: rosters, the pool, the adds used this week, the moves landing
tomorrow with the held-slot moves they need, and every week's totals so far; in a waiver league
(PR Fa) also the players on waivers, the claims placed and not yet decided, and the waiver
priority; in a FAAB league (PR Fb) each team's dollars left and what its bids scale by; under
continuous waivers (PR Fc) every add a claim among them. The world
(``run.World``) is apart: lines, availability and the beliefs belong to the path, never to an
arm, so two arms of a pair see one world. Pure: frozen dataclasses,
advanced by ``replace``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from .engine import HELD, ONE_WIN, Calendar, Move, Player, Week, monday_of
from .league import LeagueSpec
from .shapes import ASSUMED, BOOK, CONTINUOUS, DROPPED

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


#: A claim's outcome on its clear morning (#172, PR Fa): it went to its team, it went to a team
#: with better priority, or its team was first and its roster could not take the player.
WON, LOST, FAILED = "won", "lost", "failed"
#: A seat's claim counts, as :attr:`SimState.claim_counts` keeps them: placed, won, lost to a
#: better priority, failed (won and not taken), and of those decided, how many had a team ahead
#: of theirs in the order when their player was decided and how many of those were lost.
CLAIM_COUNTS = ("placed", WON, LOST, FAILED, "behind", "behind_lost")
#: A FAAB league's claim counts besides (#172, PR Fb), the world's knowledge of every bid, which
#: no decision reads: claims won at $0, lost to a higher bid, lost on a tie, won with no other
#: claim on the player that morning; the dollars a won claim paid above the next bid that could
#: have been taken (its whole bid when there was none), and the dollars a lost claim fell short
#: of the winning bid by.
BID_COUNTS = ("won_free", "lost_bid", "lost_tie", "alone", "over", "short")


@dataclass(frozen=True)
class Waiting:
    """A player on waivers (#172, PR Fa): the morning his claims are decided (his clear date: the
    morning he left a roster plus the league's waiver days) and the team that dropped him."""

    clears: date
    by: int


@dataclass(frozen=True)
class Claim:
    """A waiver claim placed and not yet decided (#172, PR Fa): its move (the add on waivers, or
    under continuous waivers any add, PR Fc; the drop, made only if the claim is won, or None for
    an open spot), the day it was placed, its add's clear date (the morning it is decided: a
    dropped player's clear date, or under continuous waivers the next morning for a player nobody
    dropped lately), the week its add is charged to (the week of the day before it lands, so the
    plan's and the world's weeks agree; None outside the calendar), the held-slot moves it needs,
    made only if it is won, and whether its drop is a held player (a churn, #221), who leaves on
    his own the morning after the claim is placed. In a FAAB league (PR Fb) its sealed ``bid``,
    whole dollars set when it is placed (0 by priority)."""

    move: Move
    placed: date
    clears: date
    week: int | None
    held: tuple[tuple[int, str], ...] = ()
    churn: bool = False
    bid: int = 0

    @property
    def needs_spot(self) -> bool:
        """Whether its add takes an active spot of its own: no drop, or a churn's held drop."""
        return self.move.drop is None or self.churn


@dataclass(frozen=True)
class Resolved:
    """One claim decided on a clear morning (#172, PR Fa): the team, the add, the drop, the
    outcome (:data:`WON`, :data:`LOST`, :data:`FAILED`) and whether a team stood ahead of the
    claim's team in the order when its player was decided. In a FAAB league (PR Fb) its bid
    (None by priority)."""

    team: int
    add: int
    drop: int | None
    outcome: str
    behind: bool
    bid: int | None = None


@dataclass(frozen=True)
class Setup:
    """A league as a run starts it."""

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
    #: The market's view of each player, higher better: the shared projection's per-game value
    #: (a replay's: the run's forecaster's, on draft day).
    market: Mapping[int, float] = field(default_factory=dict)
    #: The rate at which a market rival moves when its arm names none: adds per team-day (a
    #: replay records none: zero).
    market_rate: float = 0.0
    #: The adds each team made this week before day one.
    adds_used: Mapping[int, int] = field(default_factory=dict)
    #: The bracket as read, or why it is not trusted (``league.BracketUnread``'s words).
    spec: LeagueSpec | None = None
    bracket_unread: str | None = None
    #: How dropped players are added back (#172, PR Fa, ``shapes.WAIVERS``): ``none``, every add a
    #: free agent the next morning; ``priority``, a dropped player waits ``waiver_days`` and a
    #: claim on him goes by rolling waiver priority.
    waivers: str = "none"
    waiver_days: int = 2
    #: A FAAB league's (PR Fb, ``waivers`` ``faab``): the whole dollars each team starts with,
    #: and what a market rival's bid is multiplied by.
    budget: int = 100
    rival_scale: float = 1.0
    #: A categories league's head-to-head format (the format PR, ``shapes.H2H``): ``one_win``, a
    #: week one result in the standings; ``each_category``, each category's. A points league
    #: holds the default and its week is one result on the points. A categories ``spec`` of
    #: another format is refused: the seats and the standings count one.
    h2h: str = ONE_WIN
    #: Which of a waiver league's adds are claims (PR Fc, ``shapes.WAIVER_RULES``): ``dropped``,
    #: a dropped player's in his wait, every other add a free agent's; ``continuous``, every add,
    #: a claim on a player nobody dropped lately decided the next morning. Read only with waivers.
    waiver_rule: str = DROPPED
    #: How a FAAB league's market rivals bid (PR Fd, ``shapes.RIVAL_BIDS``): ``assumed``, the
    #: assumed form (``policy.rival_bid``); ``book``, a draw on the price book, whose prices
    #: (share of the budget, count; the shares ascending, ``bids.prices_of``) it carries.
    rival_bids: str = ASSUMED
    rival_prices: tuple[tuple[float, int], ...] = ()

    def __post_init__(self) -> None:
        # The seat's half of the format and the standings' half are one rule of the run (the
        # format PR's review): a categories spec of another format is refused by name. A points
        # spec holds the default and names no format.
        if self.spec is not None and self.spec.scoring != "points" and self.spec.h2h != self.h2h:
            raise ValueError(
                f"head-to-head format {self.h2h!r} with a spec of the format {self.spec.h2h!r}: "
                "the seats and the standings count one format"
            )
        if self.rival_bids == BOOK and (not self.bidding or not self.rival_prices):
            raise ValueError(
                "rival bids on the book need a FAAB league and the book's prices: "
                f"waivers {self.waivers!r}, {len(self.rival_prices)} prices"
            )

    @property
    def waiting(self) -> bool:
        """Whether a dropped player waits: the league has waivers."""
        return self.waivers != "none"

    @property
    def bidding(self) -> bool:
        """Whether a claim carries a bid from its team's budget: a FAAB league (PR Fb)."""
        return self.waivers == "faab"

    @property
    def continuous(self) -> bool:
        """Whether every add is a claim: a waiver league under continuous waivers (PR Fc)."""
        return self.waiting and self.waiver_rule == CONTINUOUS

    @property
    def one_win(self) -> bool:
        """Whether a week is one result and its matchup's odds are what a seat weighs: a
        categories league of the ``one_win`` format."""
        return self.scoring != "points" and self.h2h == ONE_WIN

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
        from .engine import starting_slots

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
    #: The held-slot moves those moves need (player, slot), by team: made first when they land.
    pending_held: Mapping[int, tuple[tuple[int, str], ...]] = field(default_factory=dict)
    #: Every week's totals so far: week number to team to stat totals.
    totals: Mapping[int, Mapping[int, Mapping[str, float]]] = field(default_factory=dict)
    #: The moves landed (``executed``) and the moves lost because the add or its drop was gone
    #: (``gone``), by team.
    executed_by: Mapping[int, int] = field(default_factory=dict)
    gone_by: Mapping[int, int] = field(default_factory=dict)
    #: Active players the executor had to drop when a cleared held player came back over the
    #: league's spots (``policy.land``), by team: never an add, so neither executed nor gone.
    forced_by: Mapping[int, int] = field(default_factory=dict)
    #: Held-slot moves the executor did not make because the slot did not accept the player's
    #: status on the morning they were to land (``policy.land``), by team.
    held_refused_by: Mapping[int, int] = field(default_factory=dict)
    #: A waiver league's (#172, PR Fa; all empty without waivers): the players on waivers, by
    #: player; the claims placed and not yet decided, by team in the order placed; the held
    #: players churn claims drop, leaving on their own tomorrow morning, by team; the waiver
    #: priority, best first; the claims decided this morning, in the order decided; and each
    #: team's claim counts (:data:`CLAIM_COUNTS`, and :data:`BID_COUNTS` in a FAAB league).
    waivers: Mapping[int, Waiting] = field(default_factory=dict)
    claims: Mapping[int, tuple[Claim, ...]] = field(default_factory=dict)
    pending_drops: Mapping[int, tuple[int, ...]] = field(default_factory=dict)
    priority: tuple[int, ...] = ()
    resolved: tuple[Resolved, ...] = ()
    claim_counts: Mapping[int, Mapping[str, int]] = field(default_factory=dict)
    #: A FAAB league's (PR Fb; all empty otherwise): each team's dollars left; the gains of the
    #: moves each seat that bids by the live rule recommended over the fortnight, by team, each
    #: with its day (what its typical gain is over, ``autopilot.typical_gain``); and the market
    #: rivals' moves' gains on their view over the fortnight, pooled, each with its day.
    dollars: Mapping[int, int] = field(default_factory=dict)
    recent: Mapping[int, tuple[tuple[date, float], ...]] = field(default_factory=dict)
    market_recent: tuple[tuple[date, float], ...] = ()
    #: Whom each team's returning held players send (PR G), by team: (the held player, the
    #: active player its seat's plan drops for him), as the seat's decision named them today
    #: (``policy.sends_of``); tomorrow morning's alone (``policy.arrive`` spends them). Empty for
    #: a seat that names none. No decision reads it, so it is no part of :meth:`key`.
    sends: Mapping[int, tuple[tuple[int, int], ...]] = field(default_factory=dict)

    @property
    def executed(self) -> int:
        """The moves landed, every team's."""
        return sum(self.executed_by.values())

    @property
    def gone(self) -> int:
        """The moves lost, every team's."""
        return sum(self.gone_by.values())

    @property
    def forced_drops(self) -> int:
        """The drops forced by a returning held player, every team's."""
        return sum(self.forced_by.values())

    @property
    def held_refused(self) -> int:
        """The held-slot moves refused at landing, every team's."""
        return sum(self.held_refused_by.values())

    def key(self) -> tuple[Any, ...]:
        """What a decision depends on: two arms with the same key share one solve. In a waiver
        league also who is on waivers until when, the claims placed and the churns' held drops
        due (#172, PR Fa); the priority is read by no decision."""
        base = (
            self.day,
            tuple(sorted((t, tuple(sorted(r))) for t, r in self.rosters.items())),
            tuple(sorted(self.pool)),
            tuple(sorted(self.adds_used.items())),
            tuple(sorted((t, m) for t, m in self.pending.items() if m)),
            tuple(sorted((t, h) for t, h in self.pending_held.items() if h)),
        )
        if not (self.waivers or any(self.claims.values()) or any(self.pending_drops.values())):
            return base
        return (
            *base,
            tuple(sorted(self.waivers.items())),
            tuple(sorted((t, c) for t, c in self.claims.items() if c)),
            tuple(sorted((t, d) for t, d in self.pending_drops.items() if d)),
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
    """Day one's state from the setup. In a waiver league the first priority order is the
    reverse of the draft's (#172, PR Fa): the seat that picks last in the first round claims
    first (``snake_draft`` and ``board_draft`` take the seats in team order). Nobody is on
    waivers: the draft's leftovers are free agents, or under continuous waivers (PR Fc) players a
    claim decides from the first morning, with no wait. In a FAAB league every team starts with
    the league's budget (PR Fb)."""
    taken = {k for r in setup.rosters.values() for k, _ in r}
    return SimState(
        setup.start,
        {t: tuple(r) for t, r in setup.rosters.items()},
        frozenset(k for k in setup.pool if k not in taken),
        dict(setup.adds_used),
        priority=tuple(reversed(setup.teams)) if setup.waiting else (),
        dollars=dict.fromkeys(setup.teams, setup.budget) if setup.bidding else {},
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


def board_draft(
    boards: Mapping[int, Sequence[int]], teams: Sequence[int], spots: int
) -> dict[int, Roster]:
    """A snake in which every seat takes the best player left on its own board (#172, PR D4a),
    ``spots`` players each, everyone on the bench. A seat whose board has no one left takes no
    one at that pick. Every seat on one board is :func:`snake_draft` on that board's order."""
    taken: set[int] = set()
    at = dict.fromkeys(teams, 0)
    out: dict[int, list[tuple[int, str]]] = {t: [] for t in teams}
    order = list(teams)
    for rnd in range(spots):
        for t in order if rnd % 2 == 0 else order[::-1]:
            board = boards.get(t, ())
            i = at[t]
            while i < len(board) and board[i] in taken:
                i += 1
            if i < len(board):
                taken.add(board[i])
                out[t].append((board[i], BENCH))
                i += 1
            at[t] = i
    return {t: tuple(r) for t, r in out.items()}
