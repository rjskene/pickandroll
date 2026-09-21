"""Parse Basketball Monster's CSV projection download.

The 2026 CSV layout is raw counting totals per player with no team, no positions and no points
column: ``player_id, last_name, first_name, games, minutes, field_goals_attempted, field_goals,
free_throws_attempted, free_throws, threes, threes_attempted, offensive_rebounds,
defensive_rebounds, assists, blocks, steals, turnovers, fouls, technicals, double_doubles,
triple_doubles, comments``. Points are rebuilt as ``2 * FGM + 3PM + FTM`` and rebounds as
``OREB + DREB``. Positions must be attached afterwards (``projections.positions``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from ...projections.names import slugify
from ...projections.schema import Horizon, ProjectionSet

CSV_COLUMNS = {
    "games": "games",
    "minutes": "minutes",
    "field_goals": "fgm",
    "field_goals_attempted": "fga",
    "free_throws": "ftm",
    "free_throws_attempted": "fta",
    "threes": "threes",
    "assists": "ast",
    "blocks": "blk",
    "steals": "stl",
    "turnovers": "tov",
}
EXTRA_COLUMNS = {
    "player_id": "bbm_player_id",
    "threes_attempted": "threepa",
    "offensive_rebounds": "oreb",
    "defensive_rebounds": "dreb",
    "fouls": "fouls",
    "technicals": "technicals",
    "double_doubles": "double_doubles",
    "triple_doubles": "triple_doubles",
    "comments": "injury",
}
CSV_MARKER = "field_goals_attempted"


def is_bbm_csv(raw: pd.DataFrame) -> bool:
    return CSV_MARKER in raw.columns and "last_name" in raw.columns


def normalize_bbm_csv(raw: pd.DataFrame) -> pd.DataFrame:
    required = set(CSV_COLUMNS) | {
        "first_name",
        "last_name",
        "offensive_rebounds",
        "defensive_rebounds",
    }
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"not a Basketball Monster CSV projection, missing columns: {missing}")
    out = pd.DataFrame(index=raw.index)
    first = raw["first_name"].fillna("").astype(str).str.strip()
    last = raw["last_name"].fillna("").astype(str).str.strip()
    out["player"] = (first + " " + last).str.strip()
    out["team"] = ""
    out["positions"] = ""
    for src, dst in CSV_COLUMNS.items():
        out[dst] = pd.to_numeric(raw[src], errors="coerce").fillna(0.0).astype(float)
    oreb = pd.to_numeric(raw["offensive_rebounds"], errors="coerce").fillna(0.0)
    dreb = pd.to_numeric(raw["defensive_rebounds"], errors="coerce").fillna(0.0)
    out["reb"] = (oreb + dreb).astype(float)
    out["pts"] = (2.0 * out["fgm"] + out["threes"] + out["ftm"]).astype(float)
    out["fgm"] = out[["fgm", "fga"]].min(axis=1)
    out["ftm"] = out[["ftm", "fta"]].min(axis=1)
    for src, dst in EXTRA_COLUMNS.items():
        if src in raw.columns:
            out[dst] = raw[src]
    if "injury" in out:
        out["injury"] = pd.Series(
            [None if pd.isna(v) or not str(v).strip() else str(v) for v in out["injury"]],
            index=out.index,
            dtype="object",
        )

    slugs = out["player"].map(slugify)
    counts = slugs.value_counts()
    ids = []
    for slug, pid in zip(slugs, raw.get("player_id", pd.Series(index=raw.index)), strict=True):
        ids.append(slug if counts[slug] == 1 else f"{slug}-{pid}")
    out.index = pd.Index(ids, name="player_id")
    return out


def load_bbm_csv(
    path: str | Path,
    horizon: Horizon = "season",
    label: str | None = None,
    as_of: datetime | None = None,
    start: date | None = None,
    end: date | None = None,
) -> ProjectionSet:
    path = Path(path)
    raw = pd.read_csv(path)
    df = normalize_bbm_csv(raw)
    if as_of is None:
        as_of = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    if label is None:
        label = f"BBM {horizon} (csv) {path.name}"
    return ProjectionSet(
        source="bbm", label=label, horizon=horizon, as_of=as_of, df=df, start=start, end=end
    )
