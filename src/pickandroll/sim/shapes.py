"""The league shapes (#172, PR D4b): the league a path is played in, and the ruled grid of them.

A **league shape** (:class:`LeagueShape`) is a league's team count, its roster slots, its weekly
add limit and its playoff format: what the user's ruling of 2026-11-06 lets a league generator
vary ("team count, roster slots, weekly add limit and playoff format, over modest ranges"), with
the weekly add limit a parameter beside the rest (2026-11-07). Every shape scores the nine
categories and holds no held slot: points leagues and held slots are a later PR's (D4c).

- :data:`FIXED` is the league every replay played in before this PR: twelve teams, the thirteen
  slots of :data:`SLOTS`, four adds a week, six playoff teams over three weeks. It is the
  default, and on it nothing moves.
- :data:`FULL` is the ruled grid: ten, twelve or fourteen teams; the thirteen slots or fifteen
  (two more bench); two, three or four adds a week or no limit; four playoff teams over two
  weeks, six over three or eight over three. Seventy-two shapes, in the order of
  ``itertools.product(playoffs, adds, slots, teams)``, so the team count turns fastest. The
  order is part of a run's record: it is never changed.

The name ``shape`` is taken twice already in the simulator (``replay --shape``, the oracle's error
shape, and ``policy.Shape``, what decides which knobs a seat reads): this module's thing is a
league shape, ``LeagueShape`` in code. Pure: no I/O.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any

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


#: The league every replay played in before this PR, and the default.
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
    "path p plays shape c = p mod N of the grid's N in round j = p div N; inside a round a team "
    "count's shapes take a run of consecutive turns, each at its place s (s mod the playoff "
    "formats' count is its playoff format, s mod the adds-and-slots pairs' count is y = "
    "slots' count x adds + slots, by index; on the full grid s = (16p + 9y) mod 24), and "
    "turn = K j + (s + 5 j) mod K for K a team count's shapes; the pair's seat is teams[turn mod "
    "n] and the room's rotation is by the turn; the world's draws stay on (seed, path)"
)


@dataclass(frozen=True)
class Visit:
    """What a path plays (:func:`visit`): its league shape, the shape's index in the grid, and
    its turn, which decides its seats."""

    shape: LeagueShape
    index: int
    turn: int


def place(grid: Grid, p: int, a: int, s: int) -> int:
    """A shape's place inside its team count's run of turns: the one ``x`` in 0 to
    ``grid.per_round`` - 1 with ``x mod P = p`` and ``x mod (A S) = y``, ``y = S a + s`` (``P``,
    ``A`` and ``S`` the counts of the playoff formats, adds and slots; ``p``, ``a`` and ``s`` the
    shape's indices). On the full grid ``(16 p + 9 y) mod 24``. So the playoff formats take every
    P-th turn and the adds and slots the turn's remainder by A S: no axis's value drafts from
    one end of the order (the grid's own order would put one playoff format on the first picks
    and another on the last)."""
    big, small = len(grid.adds) * len(grid.rosters), len(grid.playoffs)
    y = len(grid.rosters) * a + s
    return next(x for x in range(grid.per_round) if x % small == p and x % big == y)


def visit(path: int, grid: Grid) -> Visit:
    """The league shape and the turn of ``path`` on ``grid`` (#172, PR D4b), a pure function of
    the two. With ``N`` shapes, ``c = path mod N`` and round ``j = path div N``: the shape is
    the grid's ``c``-th, and ``turn = K j + (place + 5 j) mod K``, ``K`` a team count's shapes
    (:func:`place`). Each round a team count's shapes take ``K`` consecutive turns, so its seats
    are taken as evenly as the paths allow, and the stride moves a shape to a new seat each
    round. A grid of one shape gives ``turn = path``: the fixed shape's seats are as before."""
    n, k = len(grid.shapes), grid.per_round
    c, j = path % n, path // n
    p, rest = divmod(c // len(grid.teams), len(grid.adds) * len(grid.rosters))
    a, s = divmod(rest, len(grid.rosters))
    return Visit(grid.shapes[c], c, k * j + (place(grid, p, a, s) + STRIDE * j) % k)


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


def axis_values(shape: LeagueShape) -> Mapping[str, Any]:
    """The shape's value on each axis, as :meth:`Grid.axes` names them."""
    return {
        "playoffs": f"{shape.playoff_teams}/{shape.playoff_weeks}",
        "weekly_adds": shape.weekly_adds,
        "slots": len(shape.slots),
        "teams": shape.teams,
    }


__all__ = [
    "FIXED",
    "FIXED_GRID",
    "FULL",
    "SLOTS",
    "STRIDE",
    "VISIT_RULE",
    "WIDE_SLOTS",
    "Grid",
    "LeagueShape",
    "Visit",
    "axis_values",
    "one",
    "place",
    "round_up",
    "visit",
]
