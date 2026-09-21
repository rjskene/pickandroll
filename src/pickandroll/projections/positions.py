"""Attach position eligibility to a projection table that lacks it.

Basketball Monster's CSV projections carry no positions or teams. Positions can come from any
table with a player name and a position string: a Basketball Monster Excel export (``Name`` and
``Pos``), a hand-kept ``positions.csv`` (``player,positions``), or the Yahoo player list.
Players with no match keep an empty position string and stay eligible for UTIL and bench slots
only, so they can still be drafted but never fill a positional slot in the optimizer.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .names import normalize_name
from .schema import split_positions

NAME_COLUMNS = ("player", "name", "Name", "Player", "PLAYER", "full_name", "player_name")
POSITION_COLUMNS = ("positions", "position", "pos", "Pos", "eligible_positions", "display_position")


def positions_from_table(table: pd.DataFrame) -> pd.Series:
    """Normalized name to a ``PG/SG`` string, from any table with name and position columns."""
    name_col = next((c for c in NAME_COLUMNS if c in table.columns), None)
    pos_col = next((c for c in POSITION_COLUMNS if c in table.columns), None)
    if name_col is None or pos_col is None:
        raise ValueError(
            f"need a name column {NAME_COLUMNS} and a position column {POSITION_COLUMNS}, "
            f"got {list(table.columns)}"
        )
    out: dict[str, str] = {}
    for name, pos in zip(table[name_col], table[pos_col], strict=True):
        if pd.isna(pos) or not str(pos).strip():
            continue
        try:
            parsed = split_positions(str(pos))
        except ValueError:
            continue
        out[normalize_name(name)] = "/".join(parsed)
    return pd.Series(out, dtype="object")


def load_positions(path: str | Path) -> pd.Series:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        table = pd.read_csv(path)
    elif path.suffix.lower() in {".xls", ".xlsx"}:
        table = pd.read_excel(path, sheet_name=0)
    else:
        raise ValueError(f"unsupported positions file {path.name}")
    return positions_from_table(table)


def apply_positions(
    df: pd.DataFrame, positions: pd.Series, overwrite: bool = False
) -> tuple[pd.DataFrame, list[str]]:
    """Fill the ``positions`` column by normalized player name. Returns the table and the ids
    still lacking positions."""
    out = df.copy()
    keys = out["player"].map(normalize_name)
    found = keys.map(positions)
    current = out["positions"].fillna("").astype(str)
    take = found.notna() & (overwrite | (current.str.strip() == ""))
    out.loc[take, "positions"] = found[take]
    missing = out.index[out["positions"].fillna("").astype(str).str.strip() == ""].tolist()
    return out, missing
