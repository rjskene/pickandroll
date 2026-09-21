from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from ...projections.schema import Horizon, ProjectionSet
from .csv import is_bbm_csv, load_bbm_csv, normalize_bbm_csv
from .parse import is_per_game, load_bbm_export, normalize_bbm, read_bbm_export

PROJECTION_SUFFIXES = {".xls", ".xlsx", ".csv"}


def load_bbm(
    path: str | Path,
    horizon: Horizon = "season",
    label: str | None = None,
    as_of: datetime | None = None,
    start: date | None = None,
    end: date | None = None,
) -> ProjectionSet:
    """Load either export layout by file extension."""
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return load_bbm_csv(path, horizon=horizon, label=label, as_of=as_of, start=start, end=end)
    return load_bbm_export(path, horizon=horizon, label=label, as_of=as_of, start=start, end=end)


__all__ = [
    "PROJECTION_SUFFIXES",
    "is_bbm_csv",
    "is_per_game",
    "load_bbm",
    "load_bbm_csv",
    "load_bbm_export",
    "normalize_bbm",
    "normalize_bbm_csv",
    "read_bbm_export",
]
