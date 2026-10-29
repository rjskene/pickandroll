"""Yahoo's can't-cut list at solve time (#220, docs/AUTOPILOT.md section 2): my players Yahoo
refuses to drop, as the moves executor last read them on an add page, in
``data/leagues/<league>/cantcut.json``.

Every logged moves pass row carries the page's can't-cut ids (``controls.cantcut``, #171 PR 2).
:func:`record` keeps the newest row's list with its ``read_at``: a newer read replaces the file,
an empty list included (none of mine is on the list now). A row whose page drew no drop table
(an open spot: no rows, so no icon to see) or that carries no list leaves the file alone. Nothing
expires; the next read replaces it. A league with no file has no can't-cut players as far as the
engine knows. :func:`load` is lenient: a file that does not read is none.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import leagues

CANTCUT_FILE = "cantcut.json"

_lock = threading.Lock()


def path_of(data_dir: Path, league: str) -> Path:
    return leagues.league_dir(data_dir, league) / CANTCUT_FILE


def newest(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The newest read among a pass's rows (``MoveCheck`` dumps) whose page drew the drop table:
    ``{"ids", "read_at"}``, None when no row has one."""
    best: dict[str, Any] | None = None
    for row in rows:
        c = row.get("controls") or {}
        ids, at = c.get("cantcut"), c.get("read_at")
        if not isinstance(ids, list) or not isinstance(at, str):
            continue
        # No drop box and no can't-cut row: the page drew no drop table to read the icons on.
        if not ids and not c.get("drops"):
            continue
        if best is None or at > best["read_at"]:
            best = {"ids": sorted({int(k) for k in ids}), "read_at": at}
    return best


def load_body(data_dir: Path, league: str) -> dict[str, Any] | None:
    try:
        body = json.loads(path_of(data_dir, league).read_text())
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def load(data_dir: Path, league: str) -> frozenset[int]:
    """My players on Yahoo's can't-cut list in ``league``, as last read; none without a file."""
    body = load_body(data_dir, league) or {}
    ids = body.get("ids")
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(int(k) for k in ids if isinstance(k, int) or str(k).isdigit())


def record(data_dir: Path, league: str, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Keep the newest read among ``rows`` when it is newer than the file's; answers what was
    written, None when nothing was. Written whole to a temporary file and moved into place."""
    read = newest(rows)
    if read is None:
        return None
    with _lock:
        old = load_body(data_dir, league)
        if (
            old is not None
            and isinstance(old.get("read_at"), str)
            and old["read_at"] >= read["read_at"]
        ):
            return None
        path = path_of(data_dir, league)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(read, indent=1) + "\n")
        os.replace(tmp, path)
    return read
