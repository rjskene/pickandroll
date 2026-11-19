"""The keep list's store (#442): players the user keeps, whom no moves solve ever drops.

The pinned private league is a keeper league, and the moves value a player only to the season's
end, so they could recommend dropping a player the user keeps for next season. A listed player
on my roster is protected by the keep rule (``season.moves.kept_of``, "on the keep list"): no
set, plan, comeback, held-slot or IL move, pick's drop or strategy run drops the player, and the
player is never one of the lift's marginal players.

``GET /autopilot/keep``
    The list: each entry's player, name, leagues (null: every league), who set it and when.
``PUT /autopilot/keep``
    Set one entry (a session on the user's word in chat): its player by Yahoo id, or by name as
    one league of the user's lists the player; its leagues. An entry for a player already listed
    replaces it. No expiry: an entry stays until it is removed.
``DELETE /autopilot/keep/{player}``
    Remove an entry.

``data/autopilot/keep.json`` holds the list, written whole to a temporary file and moved into
place; a file that does not read is refused, never overwritten, and the solves then keep no one
from it. The repo holds no name from it.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .season_knobs import autopilot_dir

KEEP_FILE = "keep.json"

_lock = threading.Lock()


class KeepError(ValueError):
    pass


@dataclass(frozen=True)
class Keep:
    """One entry of the keep list."""

    player: int
    #: The leagues it applies in; None for every league.
    leagues: tuple[str, ...] | None
    by: str
    at: str
    name: str | None = None

    def applies(self, league: str) -> bool:
        return self.leagues is None or str(league) in self.leagues

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player,
            "name": self.name,
            "leagues": None if self.leagues is None else list(self.leagues),
            "by": self.by,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Keep:
        leagues = d.get("leagues")
        if leagues is not None and not isinstance(leagues, list):
            raise ValueError(f"leagues {leagues!r} is not a list")
        return cls(
            int(d["player"]),
            None if leagues is None else tuple(str(x) for x in leagues),
            str(d.get("by") or "dashboard"),
            str(d.get("at") or ""),
            d.get("name"),
        )


def path_of(data_dir: Path) -> Path:
    return autopilot_dir(data_dir) / KEEP_FILE


def _read(data_dir: Path) -> list[Keep]:
    path = path_of(data_dir)
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise KeepError(f"{path.name} does not read: {exc}") from exc
    rows = body.get("keep") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise KeepError(f"{path.name} is not the keep list")
    try:
        return [Keep.from_dict(r) for r in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise KeepError(f"{path.name} holds an entry that does not read: {exc}") from exc


def _write(data_dir: Path, rows: Iterable[Keep]) -> None:
    path = path_of(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"keep": [k.to_dict() for k in rows]}, indent=1) + "\n")
    os.replace(tmp, path)


def load(data_dir: Path) -> list[Keep]:
    """The list; :class:`KeepError` when the file does not read."""
    return _read(data_dir)


def in_force(data_dir: Path, league: str) -> frozenset[int]:
    """The players listed for ``league``; none when the file is missing or does not read."""
    try:
        return frozenset(k.player for k in _read(data_dir) if k.applies(league))
    except KeepError:
        return frozenset()


def set_keep(
    data_dir: Path, player: int, name: str | None, leagues: list[str] | None, by: str
) -> Keep:
    """List ``player``, replacing any entry of the player."""
    at = datetime.now(UTC).isoformat(timespec="seconds")
    entry = Keep(player, None if leagues is None else tuple(leagues), by, at, name)
    with _lock:
        rows = [k for k in _read(data_dir) if k.player != player]
        _write(data_dir, [*rows, entry])
    return entry


def remove(data_dir: Path, player: int) -> bool:
    """Remove the entry of ``player``; whether there was one."""
    with _lock:
        rows = _read(data_dir)
        kept = [k for k in rows if k.player != player]
        if len(kept) == len(rows):
            return False
        _write(data_dir, kept)
        return True


def payload(data_dir: Path) -> dict[str, Any]:
    """``GET /autopilot/keep``: the list."""
    return {"keep": [k.to_dict() for k in _read(data_dir)]}
