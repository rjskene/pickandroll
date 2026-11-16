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
    "WIDE_SLOTS",
    "Grid",
    "LeagueShape",
    "axis_values",
    "one",
]
