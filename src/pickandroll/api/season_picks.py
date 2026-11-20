"""Your picks' store (#434, ``season.picks``): the players the user names for the moves solves.

``GET /autopilot/picks``
    The picks, each with its player's name, leagues (null: all), drop, bid, expiry, who set it
    and when, and the leagues it has left (its player on a team there); ``active`` says whether
    it is in force today.
``PUT /autopilot/picks``
    Set one pick (the dashboard's Queue screen, or a session on the user's word in chat): its
    player by Yahoo id, or by name as one league of the user's lists him; leagues, drop, bid and
    its days (7 by default) or its last day. A pick for a player already picked replaces it.
``DELETE /autopilot/picks/{player}``
    Remove a pick.

``data/autopilot/picks.json`` holds them, written whole to a temporary file and moved into place;
a file that does not read is refused, never overwritten (the solves then make no pick). Nothing
else writes it but :func:`mark_left`, which a league's moves solve calls before it builds.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ..season import picks as pk
from .season_knobs import autopilot_dir

PICKS_FILE = "picks.json"

_lock = threading.Lock()


class PicksError(ValueError):
    pass


def path_of(data_dir: Path) -> Path:
    return autopilot_dir(data_dir) / PICKS_FILE


def _read(data_dir: Path) -> list[pk.Pick]:
    path = path_of(data_dir)
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise PicksError(f"{path.name} does not read: {exc}") from exc
    rows = body.get("picks") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise PicksError(f"{path.name} is not the picks file")
    try:
        return [pk.Pick.from_dict(r) for r in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise PicksError(f"{path.name} holds a pick that does not read: {exc}") from exc


def _write(data_dir: Path, picks: Iterable[pk.Pick]) -> None:
    path = path_of(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"picks": [p.to_dict() for p in picks]}, indent=1) + "\n")
    os.replace(tmp, path)


def load(data_dir: Path) -> list[pk.Pick]:
    """The picks; :class:`PicksError` when the file does not read."""
    return _read(data_dir)


def in_force(data_dir: Path, league: str, today: date) -> list[pk.Pick]:
    """The picks in force in ``league`` today; none when the file does not read."""
    try:
        return pk.active(_read(data_dir), league, today)
    except PicksError:
        return []


def mark_left(data_dir: Path, league: str, rostered: Iterable[int], today: date) -> list[pk.Pick]:
    """Mark ``league`` left on each pick in force there whose player is on a team of it
    (``rostered``) and write the file when one changed; the picks in force there after. None
    in force, or a file that does not read, writes nothing."""
    with _lock:
        try:
            picks = _read(data_dir)
        except PicksError:
            return []
        if not pk.active(picks, league, today):
            return []
        marked = pk.left_in(picks, league, rostered, today)
        if marked != picks:
            _write(data_dir, marked)
        return pk.active(marked, league, today)


def set_pick(
    data_dir: Path,
    player: int,
    name: str | None,
    leagues: list[str] | None,
    drop: int | None,
    bid: int | None,
    expires: date,
    by: str,
) -> pk.Pick:
    """Set the pick of ``player``, replacing any pick of him."""
    at = datetime.now(UTC).isoformat(timespec="seconds")
    pick = pk.Pick(
        player,
        None if leagues is None else tuple(leagues),
        drop,
        bid,
        expires,
        by,
        at,
        name,
    )
    with _lock:
        picks = [p for p in _read(data_dir) if p.player != player]
        _write(data_dir, [*picks, pick])
    return pick


def remove(data_dir: Path, player: int) -> bool:
    """Remove the pick of ``player``; whether there was one."""
    with _lock:
        picks = _read(data_dir)
        kept = [p for p in picks if p.player != player]
        if len(kept) == len(picks):
            return False
        _write(data_dir, kept)
        return True


def payload(data_dir: Path, today: date) -> dict[str, Any]:
    """``GET /autopilot/picks``: the picks, each with whether it is in force today."""
    return {
        "picks": [{**p.to_dict(), "active": today <= p.expires} for p in _read(data_dir)],
        "days": pk.DAYS,
    }
