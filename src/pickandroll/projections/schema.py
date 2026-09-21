"""Normalized projection schema shared by every source and every model.

Every source (Basketball Monster, CSV, ...) is parsed into one shape: a DataFrame indexed by a
player id with the columns in ``REQUIRED_COLS``. Stats are *totals over the projection horizon*,
never per game, so that team-level sums are meaningful and percentage categories can be rebuilt
from makes and attempts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

import pandas as pd


class Cat(StrEnum):
    """The nine standard head-to-head categories."""

    PTS = "pts"
    THREES = "threes"
    REB = "reb"
    AST = "ast"
    STL = "stl"
    BLK = "blk"
    TOV = "tov"
    FG_PCT = "fg_pct"
    FT_PCT = "ft_pct"


NINE_CAT: tuple[Cat, ...] = tuple(Cat)
COUNTING_CATS: tuple[Cat, ...] = (Cat.PTS, Cat.THREES, Cat.REB, Cat.AST, Cat.STL, Cat.BLK, Cat.TOV)
PCT_CATS: tuple[Cat, ...] = (Cat.FG_PCT, Cat.FT_PCT)
NEGATIVE_CATS: tuple[Cat, ...] = (Cat.TOV,)
# Raw columns each percentage category is built from: (makes, attempts).
PCT_COMPONENTS: dict[Cat, tuple[str, str]] = {
    Cat.FG_PCT: ("fgm", "fga"),
    Cat.FT_PCT: ("ftm", "fta"),
}

ID_COLS: tuple[str, ...] = ("player", "team", "positions", "games", "minutes")
STAT_COLS: tuple[str, ...] = (
    "pts",
    "threes",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
    "fgm",
    "fga",
    "ftm",
    "fta",
)
REQUIRED_COLS: tuple[str, ...] = ID_COLS + STAT_COLS

POSITIONS: tuple[str, ...] = ("PG", "SG", "SF", "PF", "C", "G", "F")
# Slot eligibility implied by a listed position. Yahoo lists guards as PG and/or SG, both of
# which can fill the G slot; some sources only give the coarse G/F groups, which we let fill
# either fine slot rather than leave PG/SG/SF/PF slots empty.
POSITION_EXPANSION: dict[str, frozenset[str]] = {
    "PG": frozenset({"PG", "G"}),
    "SG": frozenset({"SG", "G"}),
    "SF": frozenset({"SF", "F"}),
    "PF": frozenset({"PF", "F"}),
    "C": frozenset({"C"}),
    "G": frozenset({"PG", "SG", "G"}),
    "F": frozenset({"SF", "PF", "F"}),
}


def eligible_slots(positions) -> frozenset[str]:
    """Every slot token a player with these listed positions may fill (UTIL/BN excluded)."""
    out: set[str] = set()
    for token in positions:
        out |= POSITION_EXPANSION.get(str(token).upper(), frozenset())
    return frozenset(out)


Horizon = Literal["season", "week", "day", "custom"]


def split_positions(value: str) -> tuple[str, ...]:
    """Parse a position string such as ``"PG/SG"`` or ``"PF, C"`` into a tuple of positions."""
    tokens = [t.strip().upper() for t in str(value).replace(",", "/").split("/") if t.strip()]
    bad = [t for t in tokens if t not in POSITIONS]
    if bad:
        raise ValueError(f"unknown positions {bad!r} in {value!r}")
    return tuple(dict.fromkeys(tokens))


def validate(df: pd.DataFrame) -> None:
    """Raise ``ValueError`` if ``df`` is not a valid normalized projection table."""
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"projection table missing columns: {missing}")
    if not df.index.is_unique:
        dupes = df.index[df.index.duplicated()].unique().tolist()
        raise ValueError(f"projection table has duplicate player ids: {dupes[:5]}")
    for col in STAT_COLS + ("games", "minutes"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(f"column {col!r} must be numeric")
        if (df[col] < 0).any():
            raise ValueError(f"column {col!r} has negative values")
    for col, (makes, attempts) in ((c, PCT_COMPONENTS[c]) for c in PCT_CATS):
        if (df[makes] > df[attempts] + 1e-9).any():
            raise ValueError(f"{makes} exceeds {attempts} for some players ({col})")
    for pid, value in df["positions"].items():
        try:
            split_positions(value)
        except ValueError as exc:
            raise ValueError(f"player {pid!r}: {exc}") from exc


def per_game_to_totals(df: pd.DataFrame, games_col: str = "games") -> pd.DataFrame:
    """Return a copy with per-game stat columns multiplied by games played."""
    out = df.copy()
    for col in STAT_COLS + ("minutes",):
        out[col] = out[col] * out[games_col]
    return out


@dataclass
class ProjectionSet:
    """A projection table plus the metadata needed to tell snapshots apart."""

    source: str
    label: str
    horizon: Horizon
    as_of: datetime
    df: pd.DataFrame
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        validate(self.df)

    @property
    def players(self) -> list[str]:
        return self.df.index.tolist()

    def positions(self) -> dict[str, tuple[str, ...]]:
        """Player id to eligible positions."""
        return {pid: split_positions(v) for pid, v in self.df["positions"].items()}
