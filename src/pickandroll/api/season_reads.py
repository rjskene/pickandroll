"""The stored reads of a league's transactions page (#383).

The page lists a fixed number of rows, newest first, so a busy league's newest read may no longer
reach back to the week's start. Every refresh and snapshot is kept as
``season/snapshots/<UTC time>-<source>.json`` (``api.seasons``), so the reads of the page made
since the week began are on disk: :func:`older_reads` hands them to ``season.moves.adds_used``,
which joins them to the newest read to count the week's adds. A snapshot never changes once
written, so each file's rows are parsed once (by path, size and time) and kept.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from ..season import Transaction
from . import leagues
from .season_week import NBA_TZ

#: The folders under a league's: ``api.seasons.SEASON_DIR`` and ``SNAPSHOTS``.
SEASON_DIR = "season"
SNAPSHOTS = "snapshots"
#: How long before the week's start a read may be and still join: a read from the day before
#: reaches past the start and shares its newest rows with Monday's first read.
BEFORE_START = timedelta(days=1)


def snapshots_dir(data_dir: Path, league: str) -> Path:
    return leagues.league_dir(data_dir, league) / SEASON_DIR / SNAPSHOTS


def older_reads(data_dir: Path, league: str, start: date) -> tuple[tuple[Transaction, ...], ...]:
    """The league's stored reads of the transactions page made on or after the day before
    ``start`` (US Eastern), newest first; none when nothing is stored. A file that cannot be
    read is passed over."""
    folder = snapshots_dir(data_dir, league)
    if not folder.is_dir():
        return ()
    first = start - BEFORE_START
    out: list[tuple[datetime, tuple[Transaction, ...]]] = []
    # The names start with the UTC time, so a day's margin keeps every read of an Eastern day.
    floor = (first - timedelta(days=1)).strftime("%Y%m%d")
    for path in folder.glob("*.json"):
        if path.name[:8] < floor:
            continue
        try:
            stat = path.stat()
            read = _read(str(path), stat.st_size, stat.st_mtime_ns)
        except OSError:
            continue
        if read is not None and read[0].astimezone(NBA_TZ).date() >= first:
            out.append(read)
    out.sort(key=lambda r: r[0], reverse=True)
    return tuple(rows for _, rows in out)


@lru_cache(maxsize=1024)
def _read(path: str, size: int, mtime_ns: int) -> tuple[datetime, tuple[Transaction, ...]] | None:
    """A snapshot's transactions part: when it was read and its rows; None without one."""
    del size, mtime_ns  # the cache's key: a rewritten file is read again
    try:
        part = (json.loads(Path(path).read_text()).get("parts") or {}).get("transactions")
        if not part or not part.get("fetched_at"):
            return None
        rows = (part.get("data") or {}).get("rows") or []
        return datetime.fromisoformat(part["fetched_at"]), tuple(
            Transaction.from_dict(r) for r in rows
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
