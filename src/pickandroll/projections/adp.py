"""Average draft position from a file, keyed by normalized player name.

Any table with a player name column and an ADP-like column works: a hand-kept ``adp.csv``
(``player,adp``), a FantasyPros export (``Player``, ``AVG``), or a Basketball Monster Excel
export, whose ``Rank`` column stands in for ADP when nothing better exists.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .names import normalize_name
from .positions import NAME_COLUMNS

ADP_COLUMNS = ("adp", "ADP", "AVG", "avg", "average_pick", "avg_pick", "Avg Pick", "Rank", "rank")


def adp_from_table(table: pd.DataFrame) -> pd.Series:
    name_col = next((c for c in NAME_COLUMNS if c in table.columns), None)
    adp_col = next((c for c in ADP_COLUMNS if c in table.columns), None)
    if name_col is None or adp_col is None:
        raise ValueError(
            f"need a name column {NAME_COLUMNS} and an ADP column {ADP_COLUMNS}, got {list(table.columns)}"
        )
    values = pd.to_numeric(table[adp_col], errors="coerce")
    out: dict[str, float] = {}
    for name, value in zip(table[name_col], values, strict=True):
        if pd.isna(value) or value <= 0:
            continue
        out.setdefault(normalize_name(name), float(value))
    return pd.Series(out, dtype="float")


def load_adp(path: str | Path) -> pd.Series:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        table = pd.read_csv(path)
    elif path.suffix.lower() in {".xls", ".xlsx"}:
        table = pd.read_excel(path, sheet_name=0)
    else:
        raise ValueError(f"unsupported ADP file {path.name}")
    return adp_from_table(table)


def adp_for_projections(df: pd.DataFrame, adp_by_name: pd.Series) -> pd.Series:
    """Re-key a name-based ADP series to projection ids (players without ADP are dropped)."""
    keys = df["player"].map(normalize_name)
    mapped = keys.map(adp_by_name)
    return mapped.dropna().astype(float)
