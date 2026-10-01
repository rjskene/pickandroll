"""Append-only fidelity log: one JSON object per line, one file per Yahoo draft id.

The API writes what it sees (room picks, session picks, solves, attach and control changes)
and the room client posts what only it sees (turn starts, draft attempts, landed picks). The
scorecard is computed from this file alone, so it survives the session and the server, and
the attach record in it is what rebuilds a room after a restart.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DRAFT_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


def to_iso(value: Any) -> str:
    """ISO-8601 UTC with ms from an ISO string or epoch milliseconds; now when ``None``."""
    if value is None or value == "":
        return now_iso()
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC).isoformat(
            timespec="milliseconds"
        )
    text = str(value)
    if text.lstrip("-").replace(".", "", 1).isdigit():
        return to_iso(float(text))
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds")


def to_ms(value: str) -> float:
    """Epoch milliseconds of an ISO time."""
    return datetime.fromisoformat(value).timestamp() * 1000.0


class FidelityLog:
    """``<dir>/<draft_id>.jsonl``. Writes are serialized; every event gets a ``t``."""

    def __init__(self, directory: Path, draft_id: str) -> None:
        if not DRAFT_ID.match(draft_id):
            raise ValueError(f"bad draft id {draft_id!r}")
        self.draft_id = draft_id
        self.path = Path(directory) / f"{draft_id}.jsonl"
        self._lock = threading.Lock()

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        event = {"type": event["type"], "t": to_iso(event.get("t")), **event}
        event["t"] = to_iso(event["t"])
        line = json.dumps(event, separators=(",", ":"), default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        return event

    def read(self) -> list[dict[str, Any]]:
        return read_events(self.path)


def read_events(path: Path) -> list[dict[str, Any]]:
    if not Path(path).exists():
        return []
    events = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a crash; the rest of the log stands
    return events


def last_attach(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The attach record a room would resume from, unless a detach came after it."""
    current = None
    for event in events:
        if event.get("type") == "attach":
            current = event
        elif event.get("type") == "detach":
            current = None
    return current
