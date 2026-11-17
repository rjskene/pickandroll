"""The league shapes (#172, PR D4b): the league a path is played in, and the ruled grid of them.

A **league shape** (:class:`LeagueShape`) is a league's team count, its roster slots, its weekly
add limit and its playoff format: what the user's ruling of 2026-11-06 lets a league generator
vary ("team count, roster slots, weekly add limit and playoff format, over modest ranges"), with
the weekly add limit a parameter beside the rest (2026-11-07). A shape says nothing of how a
league scores, what it holds or how it waives: those are the run's **league rules**
(:class:`LeagueRules`, PR D4c), the scoring (categories or points, with a points league's table)
and the held slots, and since PR Fa the waivers (none, or a dropped player's wait and claims by
priority), since the format PR a categories league's head-to-head format (one win per matchup,
or every category), one set for every path of a run and never an axis of a grid.

- :data:`FIXED` is the league every replay played in before PR D4b: twelve teams, the thirteen
  slots of :data:`SLOTS`, four adds a week, six playoff teams over three weeks. It is the
  default, and on it nothing moves.
- :data:`FULL` is the ruled grid: ten, twelve or fourteen teams; the thirteen slots or fifteen
  (two more bench); two, three or four adds a week or no limit; four playoff teams over two
  weeks, six over three or eight over three. Seventy-two shapes, in the order of
  ``itertools.product(playoffs, adds, slots, teams)``, so the team count turns fastest. The
  order is part of a run's record: it is never changed.

The name ``shape`` is taken twice already in the simulator (``replay --shape``, the oracle's error
shape, and ``policy.Shape``, what decides which knobs a seat reads): this module's thing is a
league shape, ``LeagueShape`` in code. ``rules`` is taken too (the audit's rules, a run's
``audit.rules``): the league's are ``LeagueRules``, ``league_rules`` where they are passed, and
the ``rules`` key of a run's ``league`` block. Pure: no I/O.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from .engine import EACH_CATEGORY, HELD, ONE_WIN, STATS

#: The thirteen roster slots of the fixed shape: the private league's without held slots.
SLOTS = ("PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN")
#: The fifteen: the thirteen and two more bench.
WIDE_SLOTS = (*SLOTS, "BN", "BN")


@dataclass(frozen=True)
class LeagueShape:
    """A league's team count, roster slots, weekly add limit (None: no limit) and playoff format
    (how many teams, over how many weeks)."""

    teams: int
    slots: tuple[str, ...]
    weekly_adds: int | None
    playoff_teams: int
    playoff_weeks: int

    def label(self) -> str:
        adds = "no add limit" if self.weekly_adds is None else f"{self.weekly_adds} adds a week"
        return (
            f"{self.teams} teams, {len(self.slots)} slots, {adds}, "
            f"{self.playoff_teams} playoff teams over {self.playoff_weeks} weeks"
        )

    def payload(self) -> dict[str, Any]:
        return {
            "teams": self.teams,
            "slots": list(self.slots),
            "weekly_adds": self.weekly_adds,
            "playoff_teams": self.playoff_teams,
            "playoff_weeks": self.playoff_weeks,
        }

    def setup_args(self) -> dict[str, Any]:
        """The shape as ``run.replay_setup``'s keywords."""
        return {
            "teams": self.teams,
            "slots": self.slots,
            "weekly_adds": self.weekly_adds,
            "playoff_teams": self.playoff_teams,
            "playoff_weeks": self.playoff_weeks,
        }

    @property
    def ids(self) -> tuple[int, ...]:
        """The seats as ``run.replay_setup`` numbers them: 1 to ``teams``."""
        return tuple(range(1, self.teams + 1))


@dataclass(frozen=True)
class Grid:
    """A grid of league shapes: every combination of its axes' values, in the order of
    ``itertools.product(playoffs, adds, rosters, teams)`` (the team count fastest). A grid of one
    value an axis is one shape."""

    name: str
    teams: tuple[int, ...]
    rosters: tuple[tuple[str, ...], ...]
    adds: tuple[int | None, ...]
    playoffs: tuple[tuple[int, int], ...]

    def __post_init__(self) -> None:
        # The visit rule places a shape by its playoff format modulo their count and by its adds
        # and slots modulo theirs (:func:`place`): the two counts must share no factor.
        if math.gcd(len(self.playoffs), len(self.adds) * len(self.rosters)) != 1:
            raise ValueError(
                f"grid {self.name!r}: {len(self.playoffs)} playoff formats and "
                f"{len(self.adds) * len(self.rosters)} adds-and-slots pairs share a factor"
            )

    @property
    def per_round(self) -> int:
        """The shapes of one team count: the turns a team count takes each round."""
        return len(self.playoffs) * len(self.adds) * len(self.rosters)

    @cached_property
    def shapes(self) -> tuple[LeagueShape, ...]:
        return tuple(
            LeagueShape(t, s, a, p, w)
            for (p, w), a, s, t in itertools.product(
                self.playoffs, self.adds, self.rosters, self.teams
            )
        )

    def axes(self) -> dict[str, tuple[Any, ...]]:
        """Each axis's values in the grid's order, as the record names them."""
        return {
            "playoffs": tuple(f"{p}/{w}" for p, w in self.playoffs),
            "weekly_adds": self.adds,
            "slots": tuple(len(s) for s in self.rosters),
            "teams": self.teams,
        }

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "axes": {k: list(v) for k, v in self.axes().items()},
            "shapes": [s.payload() for s in self.shapes],
        }


def one(name: str, shape: LeagueShape) -> Grid:
    """``shape`` as a grid of one."""
    return Grid(
        name,
        (shape.teams,),
        (shape.slots,),
        (shape.weekly_adds,),
        ((shape.playoff_teams, shape.playoff_weeks),),
    )


#: The league every replay played in before PR D4b, and the default.
FIXED = LeagueShape(12, SLOTS, 4, 6, 3)
#: The fixed shape as a grid of one (``replay --grid fixed``).
FIXED_GRID = one("fixed", FIXED)
#: The ruled grid (``replay --grid full``): seventy-two shapes, never reordered.
FULL = Grid(
    "full",
    (10, 12, 14),
    (SLOTS, WIDE_SLOTS),
    (2, 3, 4, None),
    ((4, 2), (6, 3), (8, 3)),
)


# --------------------------------------------------------------------------- the visit rule
#: How far a shape's place moves each round: a new seat each round (#172, PR D4b).
STRIDE = 5
#: The visit rule in a sentence, for a run's record.
VISIT_RULE = (
    "path i plays shape c = i mod N of the grid's N in round j = i div N; inside a round a team "
    "count's K shapes take K consecutive turns, each at its place x, the one x below K with "
    "x mod P = p and x mod (A S) = y = S a + r (p, a and r the shape's playoff format, adds "
    "and slots by index, P, A and S their counts; on the full grid x = (16 p + 9 y) mod 24); "
    "turn = K j + (x + 5 j) mod K; the pair's seat is teams[turn mod n] and the room's rotation "
    "is by the turn; the world's draws stay on (seed, path)"
)


@dataclass(frozen=True)
class Visit:
    """What a path plays (:func:`visit`): its league shape, the shape's index in the grid, and
    its turn, which decides its seats."""

    shape: LeagueShape
    index: int
    turn: int


def place(grid: Grid, p: int, a: int, r: int) -> int:
    """A shape's place inside its team count's run of turns: the one ``x`` in 0 to
    ``grid.per_round`` - 1 with ``x mod P = p`` and ``x mod (A S) = y``, ``y = S a + r`` (``P``,
    ``A`` and ``S`` the counts of the playoff formats, adds and slots; ``p``, ``a`` and ``r`` the
    shape's indices). On the full grid ``(16 p + 9 y) mod 24``. So the playoff formats take every
    P-th turn and the adds and slots the turn's remainder by A S: no axis's value drafts from
    one end of the order (the grid's own order would put one playoff format on the first picks
    and another on the last)."""
    big, small = len(grid.adds) * len(grid.rosters), len(grid.playoffs)
    y = len(grid.rosters) * a + r
    return next(x for x in range(grid.per_round) if x % small == p and x % big == y)


def visit(path: int, grid: Grid) -> Visit:
    """The league shape and the turn of ``path`` on ``grid`` (#172, PR D4b), a pure function of
    the two (:data:`VISIT_RULE`). With ``N`` shapes, ``c = path mod N`` and round
    ``j = path div N``: the shape is the grid's ``c``-th, and ``turn = K j + (x + 5 j) mod K``,
    ``x`` its place (:func:`place`) and ``K`` a team count's shapes. Each round a team count's shapes take ``K`` consecutive turns, so its seats
    are taken as evenly as the paths allow, and the stride moves a shape to a new seat each
    round. A grid of one shape gives ``turn = path``: the fixed shape's seats are as before."""
    n, k = len(grid.shapes), grid.per_round
    c, j = path % n, path // n
    p, rest = divmod(c // len(grid.teams), len(grid.adds) * len(grid.rosters))
    a, r = divmod(rest, len(grid.rosters))
    return Visit(grid.shapes[c], c, k * j + (place(grid, p, a, r) + STRIDE * j) % k)


def round_up(paths: int, grid: Grid, paired: bool) -> int:
    """A run's paths on ``grid``: a multiple of its shapes when it has more than one (every shape
    once a round), else for a pair a multiple of the shape's teams (every seat equally often),
    else as given."""
    paths = max(1, paths)
    if len(grid.shapes) > 1:
        step = len(grid.shapes)
    elif paired:
        step = grid.shapes[0].teams
    else:
        return paths
    return -(-paths // step) * step


#: ``--league``'s keys, in the order its help names them.
LEAGUE_KEYS = ("teams", "slots", "adds", "playoffs")


def parse_league(text: str) -> LeagueShape:
    """One league shape for a whole run (``replay --league``, #172, PR D4b), as
    ``teams=10,slots=15,adds=none,playoffs=4/2``: each key a value of the full grid's axis
    (``adds`` a count or ``none``, ``playoffs`` teams/weeks); a key left out takes the fixed
    shape's value. ValueError, in words, on anything else."""
    given: dict[str, str] = {}
    for part in (x.strip() for x in text.split(",") if x.strip()):
        key, eq, value = part.partition("=")
        key = key.strip()
        if not eq or key not in LEAGUE_KEYS:
            raise ValueError(f"--league {text!r}: {part!r} is not one of {', '.join(LEAGUE_KEYS)}=")
        if key in given:
            raise ValueError(f"--league {text!r}: {key} is named twice")
        given[key] = value.strip().lower()
    out = {
        "teams": FIXED.teams,
        "slots": FIXED.slots,
        "adds": FIXED.weekly_adds,
        "playoffs": (FIXED.playoff_teams, FIXED.playoff_weeks),
    }
    choices: dict[str, dict[str, Any]] = {
        "teams": {str(t): t for t in FULL.teams},
        "slots": {str(len(r)): r for r in FULL.rosters},
        "adds": {"none" if a is None else str(a): a for a in FULL.adds},
        "playoffs": {f"{p}/{w}": (p, w) for p, w in FULL.playoffs},
    }
    for key, value in given.items():
        if value not in choices[key]:
            raise ValueError(
                f"--league {key}={value}: the grid's {key} are {', '.join(choices[key])}"
            )
        out[key] = choices[key][value]
    playoff_teams, playoff_weeks = out["playoffs"]
    return LeagueShape(out["teams"], out["slots"], out["adds"], playoff_teams, playoff_weeks)


def axis_values(shape: LeagueShape) -> Mapping[str, Any]:
    """The shape's value on each axis, as :meth:`Grid.axes` names them."""
    return {
        "playoffs": f"{shape.playoff_teams}/{shape.playoff_weeks}",
        "weekly_adds": shape.weekly_adds,
        "slots": len(shape.slots),
        "teams": shape.teams,
    }


# --------------------------------------------------------------------------- the league rules
#: How a league may score (#172, PR D4c): the nine categories, or points on a table.
SCORINGS = ("categories", "points")
#: The held slots the league rules may hold, each with the most of it (the all-knobs plan, 3c:
#: ``IL`` 0 to 2, ``IL+`` 0 or 1), in the order the roster lists them after the bench.
HELD_MOST: Mapping[str, int] = {"IL": 2, "IL+": 1}
#: ESPN's default scoring for head-to-head points leagues, a stat's points per unit (ESPN's
#: article "ESPN Fantasy's default points-league scoring explained"): a platform's published
#: default, not a league's setting and not a measured figure. The working default table of a
#: points run (``replay --scoring points`` without ``--points``); the user may replace it.
POINTS_DEFAULT: tuple[tuple[str, float], ...] = (
    ("pts", 1.0),
    ("threes", 1.0),
    ("reb", 1.0),
    ("ast", 2.0),
    ("stl", 4.0),
    ("blk", 4.0),
    ("tov", -2.0),
    ("fgm", 2.0),
    ("fga", -1.0),
    ("ftm", 1.0),
    ("fta", -1.0),
)


#: A categories league's head-to-head format (#172, the format PR; the user's ruling of
#: 2026-11-17, #172 comment 6956804083), by the engine's own words (``season.state``): ``one_win``,
#: a week is one result in the standings, won by the side with more categories (the default);
#: ``each_category``, each category of each week is a win, a loss or a tie. A points league's
#: week is one result already and names none.
H2H = (ONE_WIN, EACH_CATEGORY)
#: Each format in words, for the label.
H2H_WORDS: Mapping[str, str] = {
    ONE_WIN: "one win per matchup",
    EACH_CATEGORY: "every category counted",
}


#: How a league's dropped players are added back (#172, PR Fa, PR Fb): ``none``, every add a free
#: agent who lands the next morning, as before the waivers; ``priority``, a dropped player waits his
#: waiver days and a claim on him goes by rolling waiver priority; ``faab``, he waits as with
#: priority and a claim on him carries a sealed bid from its team's budget: the highest bid takes
#: him, a tie to the better priority.
WAIVERS = ("none", "priority", "faab")
#: The waiver kind with a budget and sealed bids (PR Fb).
FAAB = "faab"
#: The whole days a dropped player waits by default, and the fewest and most a run may name
#: (the all-knobs plan, 3d: ``waiver_days``, default 2).
WAIVER_DAYS = 2
WAIVER_DAYS_RANGE = (1, 7)
#: A FAAB league's budget (PR Fb): the whole dollars each team starts the season with, by default
#: (a working default of the brief) and the fewest and most a run may name.
BUDGET = 100
BUDGET_RANGE = (1, 1000)
#: What a market rival's bid is multiplied by (PR Fb): an assumption a sweep names, not a fit;
#: 1 by default, any number above 0.
RIVAL_SCALE = 1.0


def _number(x: float) -> str:
    return f"{x:g}"


def _whole(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


_WORDS = {1: "one", 2: "two"}


@dataclass(frozen=True)
class LeagueRules:
    """How a run's league scores, what it holds and how it waives (#172, PR D4c, PR Fa, PR Fb):
    ``scoring`` (one of :data:`SCORINGS`), a points league's ``points`` table (stat and points
    per unit, in the order of the engine's ``STATS``; None in a categories league), the ``held``
    slots, in the roster's order after the bench (``IL`` up to twice, then ``IL+`` up to once),
    the ``waivers`` (one of :data:`WAIVERS`) with a dropped player's ``waiver_days`` (a whole
    number from 1 to 7, named only with waivers), and in a FAAB league the ``budget`` each team
    starts with (whole dollars, 1 to 1000) and the ``rival_scale`` a market rival's bid is
    multiplied by (above 0), both named only with ``faab``; a categories league's head-to-head
    format ``h2h`` (one of :data:`H2H`, ``one_win`` by default; a points league holds the default
    and names none). One set for every path of a run, never a grid axis; :data:`PLAIN` is today's
    league. ValueError, in words, on anything else."""

    scoring: str = "categories"
    points: tuple[tuple[str, float], ...] | None = None
    held: tuple[str, ...] = ()
    waivers: str = "none"
    waiver_days: int = WAIVER_DAYS
    budget: int = BUDGET
    rival_scale: float = RIVAL_SCALE
    h2h: str = ONE_WIN

    def __post_init__(self) -> None:
        self._check_scoring()
        self._check_waivers()
        self._check_h2h()

    def _check_h2h(self) -> None:
        if self.h2h not in H2H:
            raise ValueError(f"head-to-head format {self.h2h!r} is not one of {', '.join(H2H)}")
        if self.points is not None and self.h2h != ONE_WIN:
            raise ValueError(
                f"head-to-head format {self.h2h} with scoring points: a points league's week is "
                "one result already, a format is a categories league's"
            )

    def _check_waivers(self) -> None:
        if self.waivers not in WAIVERS:
            raise ValueError(f"waivers {self.waivers!r} is not one of {', '.join(WAIVERS)}")
        days = self.waiver_days
        lo, hi = WAIVER_DAYS_RANGE
        if not _whole(days):
            raise ValueError(f"waiver days {days!r}: a whole number of days")
        if not lo <= days <= hi:
            raise ValueError(f"waiver days {days}: a dropped player waits {lo} to {hi} days")
        if self.waivers == "none" and days != WAIVER_DAYS:
            raise ValueError(
                f"waiver days {days} with waivers none: a wait is a waiver league's, and a league "
                "without waivers has none"
            )
        self._check_budget()

    def _check_budget(self) -> None:
        budget, scale = self.budget, self.rival_scale
        if not _whole(budget):
            raise ValueError(f"budget {budget!r}: whole dollars")
        lo, hi = BUDGET_RANGE
        if not lo <= budget <= hi:
            raise ValueError(f"budget {budget}: a team starts with {lo} to {hi} dollars")
        number = isinstance(scale, int | float) and not isinstance(scale, bool)
        if not number or not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"rival scale {scale!r}: a number above 0")
        if self.waivers != FAAB and (budget != BUDGET or scale != RIVAL_SCALE):
            raise ValueError(
                f"budget {budget} and rival scale {_number(scale)} with waivers {self.waivers}: "
                "a budget and the rivals' bids are a FAAB league's"
            )

    def _check_scoring(self) -> None:
        if self.scoring not in SCORINGS:
            raise ValueError(f"scoring {self.scoring!r} is not one of {', '.join(SCORINGS)}")
        if (self.scoring == "points") != (self.points is not None):
            raise ValueError(
                "a points league scores on a table and a categories league has none: "
                f"scoring {self.scoring!r} with table {self.points!r}"
            )
        if self.points is not None:
            stats = [s for s, _ in self.points]
            unknown = [s for s in stats if s not in STATS]
            if unknown:
                raise ValueError(f"points table: {', '.join(unknown)} is no stat of a line")
            if not stats or stats != sorted(set(stats), key=STATS.index):
                raise ValueError(f"points table {self.points!r}: each stat once, in STATS order")
            if not any(w for _, w in self.points):
                raise ValueError("a points table that scores nothing: every week would tie")
        for kind in self.held:
            if kind not in HELD_MOST:
                raise ValueError(f"held slot {kind!r} is not one of {', '.join(HELD_MOST)}")
        if list(self.held) != sorted(self.held, key=list(HELD_MOST).index):
            raise ValueError(f"held slots {self.held!r}: IL first, then IL+")
        for kind, most in HELD_MOST.items():
            if self.held.count(kind) > most:
                raise ValueError(f"held slots {self.held!r}: at most {most} {kind}")

    @property
    def table(self) -> dict[str, float] | None:
        """The points table as the engine reads one (``Setup.points``, ``LeagueSpec.points``)."""
        return None if self.points is None else dict(self.points)

    def label(self) -> str:
        if self.points is None:
            scoring = "the nine categories"
        elif self.points == POINTS_DEFAULT:
            scoring = "points on ESPN's default table"
        else:
            scoring = "points on the table " + ", ".join(
                f"{s} {_number(w)}" for s, w in self.points
            )
        counts = [(self.held.count(k), k) for k in HELD_MOST if self.held.count(k)]
        held = (
            " and ".join(f"{_WORDS[n]} {k} slot{'s' if n > 1 else ''}" for n, k in counts)
            or "no held slot"
        )
        # The default format goes unsaid, as a league without waivers says none: the label of
        # today's league stays what it was. A league that counts every category says so.
        if self.h2h != ONE_WIN:
            scoring = f"{scoring}, {H2H_WORDS[self.h2h]}"
        if not self.waiting:
            return f"{scoring}, {held}"
        days = f"{self.waiver_days} day{'s' if self.waiver_days > 1 else ''}"
        if not self.bidding:
            return f"{scoring}, {held}, waivers by priority after {days}"
        return (
            f"{scoring}, {held}, waivers by FAAB after {days}, ${self.budget} a team, the "
            f"rivals' bids x{_number(self.rival_scale)}"
        )

    @property
    def waiting(self) -> bool:
        """Whether a dropped player waits: the league has waivers."""
        return self.waivers != "none"

    @property
    def bidding(self) -> bool:
        """Whether a claim carries a bid from its team's budget: a FAAB league (PR Fb)."""
        return self.waivers == FAAB

    @property
    def one_win(self) -> bool:
        """Whether a week is one result in the standings and a seat weighs the matchup's odds: a
        categories league of the ``one_win`` format (a points league's measure is its own)."""
        return self.points is None and self.h2h == ONE_WIN

    def payload(self) -> dict[str, Any]:
        """The record's ``league.rules``: the scoring, the table and the held slots, in a
        categories league its head-to-head format (the format PR), in a waiver league its waivers
        and waiver days, and in a FAAB league its budget and the rivals' bid scale (a league
        without waivers records the keys it did before PR Fa, and one by priority those it did
        before PR Fb, the format's beside them)."""
        out: dict[str, Any] = {
            "scoring": self.scoring,
            "points": self.table,
            "held": list(self.held),
        }
        if self.points is None:
            out["h2h"] = self.h2h
        if self.waiting:
            out |= {"waivers": self.waivers, "waiver_days": self.waiver_days}
        if self.bidding:
            out |= {"budget": self.budget, "rival_scale": float(self.rival_scale)}
        return out

    def slots(self, roster: tuple[str, ...]) -> tuple[str, ...]:
        """A league shape's ``roster`` with the held slots after it (the draft takes the active
        spots only, so a held slot starts the season empty)."""
        return (*roster, *self.held)


#: Today's league rules, and the default: the nine categories, no held slot.
PLAIN = LeagueRules()


def _pairs(text: str, flag: str) -> list[tuple[str, str]]:
    """``KEY=VALUE`` pairs of ``text``, a key named once; ValueError, in words, otherwise."""
    out: list[tuple[str, str]] = []
    for part in (x.strip() for x in text.split(",") if x.strip()):
        key, eq, value = part.partition("=")
        key, value = key.strip(), value.strip()
        if not eq or not key or not value:
            raise ValueError(f"{flag} {text!r}: {part!r} is not KEY=VALUE")
        if key in {k for k, _ in out}:
            raise ValueError(f"{flag} {text!r}: {key} is named twice")
        out.append((key, value))
    if not out:
        raise ValueError(f"{flag} {text!r}: names nothing")
    return out


def parse_held(text: str) -> tuple[str, ...]:
    """The held slots ``replay --held`` names (#172, PR D4c), as ``IL=2,IL+=1``: each key one of
    :data:`HELD_MOST`'s (``NA`` and any other refused), each count a whole number from zero to
    that slot's most; a slot left out holds none. In the roster's order."""
    counts = dict.fromkeys(HELD_MOST, 0)
    for key, value in _pairs(text, "--held"):
        kind = next((k for k in HELD_MOST if k.lower() == key.lower()), None)
        if kind is None:
            known = ", ".join(sorted(HELD))
            raise ValueError(
                f"--held {key}: the held slots a league may hold here are "
                f"{', '.join(HELD_MOST)} (the engine knows {known}; the plan names these two)"
            )
        try:
            n = int(value)
        except ValueError:
            raise ValueError(f"--held {key}={value}: a count is a whole number") from None
        if not 0 <= n <= HELD_MOST[kind]:
            raise ValueError(f"--held {key}={value}: {kind} is 0 to {HELD_MOST[kind]}")
        counts[kind] = n
    return tuple(k for k, n in counts.items() for _ in range(n))


def parse_points(text: str) -> tuple[tuple[str, float], ...]:
    """A points table ``replay --points`` names (#172, PR D4c), as ``pts=1,reb=1.2,...``: each
    key a stat of a line (the engine's ``STATS``), each value a finite number, not every one zero.
    The table is what is named: a stat left out scores nothing. In ``STATS`` order."""
    table: dict[str, float] = {}
    for key, value in _pairs(text, "--points"):
        if key not in STATS:
            raise ValueError(f"--points {key}: the stats of a line are {', '.join(STATS)}")
        try:
            w = float(value)
        except ValueError:
            raise ValueError(f"--points {key}={value}: points per unit are a number") from None
        if not math.isfinite(w):
            raise ValueError(f"--points {key}={value}: points per unit are a finite number")
        table[key] = w
    if not any(table.values()):
        raise ValueError(f"--points {text!r}: every weight is zero, so every week would tie")
    return tuple((s, table[s]) for s in STATS if s in table)


def parse_waivers(waivers: str, days: str | None = None) -> tuple[str, int]:
    """The waivers ``replay --waivers`` and ``--waiver-days`` name (#172, PR Fa, PR Fb):
    ``none``, ``priority`` or ``faab``, and the whole days a dropped player waits, 1 to 7, named
    only with waivers (the default 2 when not named). ValueError, in words, on anything else."""
    kind = waivers.strip().lower()
    if kind not in WAIVERS:
        raise ValueError(f"--waivers {waivers}: one of {', '.join(WAIVERS)}")
    if days is None:
        return kind, WAIVER_DAYS
    if kind == "none":
        raise ValueError(
            f"--waiver-days {days}: a dropped player's wait is a waiver league's; it is read only "
            "with --waivers priority or faab"
        )
    try:
        n = int(days)
    except ValueError:
        raise ValueError(f"--waiver-days {days}: a whole number of days") from None
    lo, hi = WAIVER_DAYS_RANGE
    if not lo <= n <= hi:
        raise ValueError(f"--waiver-days {days}: a dropped player waits {lo} to {hi} days")
    return kind, n


def parse_h2h(scoring: str, h2h: str | None) -> str:
    """The head-to-head format ``replay --h2h`` and ``validate --h2h`` name (#172, the format
    PR): ``one_win`` (the default when not named) or ``each_category``, named only in a categories
    league (``scoring`` as ``replay --scoring`` gives it): a points league's week is one result
    already. ValueError, in words, on anything else."""
    if h2h is None:
        return ONE_WIN
    if scoring == "points":
        raise ValueError(
            f"--h2h {h2h}: a points league's week is one result already; the format is read only "
            "with --scoring categories"
        )
    kind = h2h.strip().lower()
    if kind not in H2H:
        raise ValueError(f"--h2h {h2h}: one of {', '.join(H2H)}")
    return kind


def parse_budget(waivers: str, budget: str | None, scale: str | None) -> tuple[int, float]:
    """The budget and the rivals' bid scale ``replay --budget`` and ``--rival-scale`` name
    (#172, PR Fb), each read only with ``--waivers faab`` (``waivers`` as :func:`parse_waivers`
    gives it): whole dollars from 1 to 1000 (default 100), and a number above 0 (default 1).
    ValueError, in words, on anything else."""
    for flag, value in (("--budget", budget), ("--rival-scale", scale)):
        if value is not None and waivers != FAAB:
            raise ValueError(
                f"{flag} {value}: a budget and the rivals' bids are a FAAB league's; it is read "
                "only with --waivers faab"
            )
    dollars = BUDGET
    if budget is not None:
        try:
            dollars = int(budget)
        except ValueError:
            raise ValueError(f"--budget {budget}: whole dollars") from None
        lo, hi = BUDGET_RANGE
        if not lo <= dollars <= hi:
            raise ValueError(f"--budget {budget}: a team starts with {lo} to {hi} dollars")
    times = RIVAL_SCALE
    if scale is not None:
        try:
            times = float(scale)
        except ValueError:
            raise ValueError(f"--rival-scale {scale}: a number above 0") from None
        if not math.isfinite(times) or times <= 0:
            raise ValueError(f"--rival-scale {scale}: a number above 0")
    return dollars, times


__all__ = [
    "BUDGET",
    "BUDGET_RANGE",
    "FAAB",
    "FIXED",
    "FIXED_GRID",
    "FULL",
    "H2H",
    "H2H_WORDS",
    "HELD_MOST",
    "LEAGUE_KEYS",
    "PLAIN",
    "POINTS_DEFAULT",
    "RIVAL_SCALE",
    "SCORINGS",
    "SLOTS",
    "STRIDE",
    "VISIT_RULE",
    "WAIVERS",
    "WAIVER_DAYS",
    "WAIVER_DAYS_RANGE",
    "WIDE_SLOTS",
    "Grid",
    "LeagueRules",
    "LeagueShape",
    "Visit",
    "axis_values",
    "one",
    "parse_budget",
    "parse_h2h",
    "parse_held",
    "parse_league",
    "parse_points",
    "parse_waivers",
    "place",
    "round_up",
    "visit",
]
