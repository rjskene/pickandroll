"""``GET /seasons/status`` (#153): what the freshness light reads from the data folder, the
newest export of each kind, a league's newest public snapshot and the daily routine's run
marker, for ``season.status`` to judge. The service brings each league's parts, refresh job and
decision log; nothing here writes, and nothing calls GitHub.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from . import season_decisions, season_flags
from . import season_week as sw

#: The newest file of each export kind, by the patterns its readers use.
EXPORT_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "ros": sw.BBM_ROS,
    "week_this": (sw.BBM_THIS_WEEK,),
    "week_next": (sw.BBM_NEXT_WEEK,),
    "actual_7d": (season_flags.PAST_DAYS[7],),
    "actual_14d": (season_flags.PAST_DAYS[14],),
}
#: The daily routine's run marker, when it writes one: ``{"started_at", "finished_at"}``.
ROUTINE = Path("routine") / "daily.json"


def _as_of(path: Path) -> datetime:
    """An export's as-of: its sidecar's ``as_of`` when it has one, else when the file was saved."""
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
        return datetime.fromisoformat(meta["as_of"])
    except (OSError, ValueError, KeyError, TypeError):
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def exports_found(data_dir: Path) -> dict[str, tuple[str, datetime] | None]:
    """The newest export of each kind, its file and as-of; None for a kind with none."""
    out: dict[str, tuple[str, datetime] | None] = {}
    for kind, patterns in EXPORT_PATTERNS.items():
        path = sw._latest(data_dir, patterns)
        out[kind] = (path.name, _as_of(path)) if path is not None else None
    return out


def snapshot_at(snapshots: Path, source: str) -> datetime | None:
    """When the newest snapshot ``source`` saved was written, from its name."""
    stamps = sorted(p.name.split("-", 1)[0] for p in snapshots.glob(f"*-{source}.json"))
    for stamp in reversed(stamps):
        try:
            return datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def latest_entries(season_dir: Path, today: date, days: int = 2) -> list[dict[str, Any]]:
    """The decision log of the last ``days`` days to ``today``: the latest build of each
    recommendation, without reading the whole season's log."""
    folder = season_decisions.decisions_dir(season_dir)
    files = sorted(p for p in folder.glob("*.json") if p.stem <= today.isoformat())
    out: list[dict[str, Any]] = []
    for path in files[-days:]:
        try:
            out.extend(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return out


def routine_marker(data_dir: Path) -> dict[str, Any] | None:
    """The daily routine's last run, when it left a marker that reads."""
    try:
        marker = json.loads((data_dir / ROUTINE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(marker, dict):
        return None
    return {k: marker.get(k) for k in ("started_at", "finished_at")}
