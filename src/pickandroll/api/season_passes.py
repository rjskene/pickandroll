"""The record of a routine's execute pass while it runs (#201, docs/AUTOPILOT.md section 2): which
leagues it will open, which it is opening, and what each league's post said, so the Queue screen
shows the pass live. The record is written only by the routine's three calls and by the logs'
own posts (``attribute``); nothing here opens a page, solves or executes anything, and nothing
in it changes what a post logs or answers.

``POST /autopilot/passes``
    Open a pass of a kind (``moves`` or ``lineup``) with its trigger, the leagues in the order
    the routine will open them and, for a moves pass, the entries it will check; refused while a
    pass of that kind is open.
``POST /autopilot/passes/{id}/opening``
    The league (and entry) the routine is opening now.
``POST /autopilot/passes/{id}/done``
    The routine's end of the pass, with its summary.

A pass whose last word is older than :data:`STALE` reads as closed (``end: "stale"``); no timer
runs, and the next open of the day writes the stale end down. ``data/autopilot/passes/<date>.json``
holds a day's passes (the NBA day of the open), written whole to a temporary file and moved into
place under a lock; a file that does not read is refused, never overwritten. Nothing else writes
under it.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .season_knobs import autopilot_dir

PASSES_DIR = "passes"
KINDS = ("moves", "lineup")
#: A pass with no word for this long reads as closed.
STALE = timedelta(minutes=15)
#: A post's outcome as the pass counts it: a moves pass by entry, ``added`` with ``claimed``
#: (#200's tally); a lineup pass by team page, its own counts.
RESULTS: Mapping[str, tuple[str, ...]] = {
    "moves": ("would_claim", "claimed", "skipped", "gone", "failed"),
    "lineup": ("would_set", "set", "nothing_to_do", "skipped", "failed"),
}
JOINS = {"added": "claimed"}
#: A moves pass's IL runs (#214), each entry by its latest run, apart from its claims' outcomes;
#: its Start Active runs (#215), each league by its latest run.
IL_RESULTS = ("would_move", "moved", "skipped", "failed")
#: A moves pass's held drops of its churns (#221 part 3), counted apart like the IL runs.
DROP_RESULTS = ("would_drop", "dropped", "skipped", "failed", "unconfirmed")
SA_RESULTS = ("would_start", "started", "already", "skipped", "failed")

_lock = threading.Lock()


class PassError(ValueError):
    """A pass call the record refuses, or a day file that does not read."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


def passes_path(data_dir: Path, day: date) -> Path:
    return autopilot_dir(data_dir) / PASSES_DIR / f"{day.isoformat()}.json"


def _read(data_dir: Path, day: date) -> list[dict[str, Any]]:
    path = passes_path(data_dir, day)
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        raise PassError(f"{path.name} does not read: {exc}") from exc
    passes = body.get("passes") if isinstance(body, dict) else None
    if not isinstance(passes, list):
        raise PassError(f"{path.name} is not the pass record's")
    return passes


def _write(data_dir: Path, day: date, passes: list[dict[str, Any]]) -> None:
    path = passes_path(data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"passes": passes}, indent=1) + "\n")
    os.replace(tmp, path)


def _at(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def closed(p: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """The pass as it reads at ``now``: one still open with no word for :data:`STALE` is closed
    as ``stale``, ended :data:`STALE` after its last word, with nobody opening anything."""
    if p.get("end") is not None or now - _at(p["updated"]) <= STALE:
        return dict(p)
    ended = (_at(p["updated"]) + STALE).isoformat(timespec="seconds")
    return {**p, "end": "stale", "ended": ended, "current": None}


def read(data_dir: Path, day: date, now: datetime) -> list[dict[str, Any]]:
    """The day's passes as they read at ``now``, oldest first; none when there is no file."""
    return [closed(p, now) for p in _read(data_dir, day)]


def day_of(pass_id: str) -> date:
    try:
        return date.fromisoformat(pass_id.split(":", 1)[0])
    except ValueError as exc:
        raise PassError(f"no pass {pass_id}", 404) from exc


def open_pass(
    data_dir: Path,
    day: date,
    now: datetime,
    kind: str,
    trigger: str,
    leagues: list[str],
    entries: list[str] | None,
) -> dict[str, Any]:
    """Open a pass of ``kind``: refused while one of that kind is open and not stale. The day's
    stale passes are written closed first."""
    with _lock:
        passes = read(data_dir, day, now)
        busy = next((p for p in passes if p["kind"] == kind and p.get("end") is None), None)
        if busy is not None:
            raise PassError(f"a {kind} pass is open: {busy['id']}")
        stamp = now.isoformat(timespec="seconds")
        n = 1 + sum(1 for p in passes if p["kind"] == kind)
        new = {
            "id": f"{day.isoformat()}:{kind}:{n}",
            "kind": kind,
            "trigger": trigger,
            "leagues": list(leagues),
            "entries": list(entries) if entries is not None else None,
            "started": stamp,
            "updated": stamp,
            "current": None,
            "done": [],
            "outcomes": {},
            "ended": None,
            "end": None,
            "summary": None,
        }
        _write(data_dir, day, [*passes, new])
        return new


def _change(data_dir: Path, pass_id: str, now: datetime, change: Any) -> dict[str, Any]:
    """Apply ``change`` to the open pass ``pass_id`` under the lock; refused (404) for no such
    pass and (409) once it is done or stale. The day's stale passes are written closed too."""
    day = day_of(pass_id)
    with _lock:
        passes = read(data_dir, day, now)
        p = next((x for x in passes if x["id"] == pass_id), None)
        if p is None:
            raise PassError(f"no pass {pass_id}", 404)
        if p.get("end") == "stale":
            raise PassError(f"the pass {pass_id} is stale: no word for {_minutes(STALE)} min")
        if p.get("end") is not None:
            raise PassError(f"the pass {pass_id} is done")
        change(p)
        p["updated"] = now.isoformat(timespec="seconds")
        _write(data_dir, day, passes)
        return p


def opening(
    data_dir: Path, pass_id: str, now: datetime, league: str, entry: str | None
) -> dict[str, Any]:
    """The league (and entry) the routine is opening now; a league the pass did not name is
    refused."""

    def change(p: dict[str, Any]) -> None:
        if league not in p["leagues"]:
            raise PassError(f"the pass {pass_id} does not open league {league}")
        p["current"] = {
            "league": league,
            "entry": entry,
            "since": now.isoformat(timespec="seconds"),
        }

    return _change(data_dir, pass_id, now, change)


def done(
    data_dir: Path,
    pass_id: str,
    now: datetime,
    summary: str | None,
    held: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The routine's end of the pass, with the week plan's steps it left held on an earlier step
    (#221 part 2), each with what it waits for, by entry (a moves pass's only)."""

    def change(p: dict[str, Any]) -> None:
        p.update(end="done", ended=now.isoformat(timespec="seconds"), current=None, summary=summary)
        if p["kind"] == "moves":
            p["held"] = dict(held or {})

    return _change(data_dir, pass_id, now, change)


def attribute(
    data_dir: Path,
    day: date,
    now: datetime,
    kind: str,
    league: str,
    outcomes: Mapping[str, str],
    key: str = "outcomes",
) -> dict[str, Any] | None:
    """A post the league's log took, given to the open pass of its kind (the caller leaves out a
    panel's): the league done, each entry's (or the team page's) latest outcome, the pass's last
    word now. An IL run (``key`` ``il``, #214) keeps its entry's outcome apart from the claim's
    and leaves the league as it was: its add pages come after; so does a churn's held drop
    (``drop``, #221 part 3), and a Start Active run
    (``start_active``, #215), by league. None, and nothing written, when
    no such pass is open or it does not name the league; ``current`` stays until the next
    opening."""
    with _lock:
        passes = read(data_dir, day, now)
        p = next((x for x in passes if x["kind"] == kind and x.get("end") is None), None)
        if p is None or league not in p["leagues"]:
            return None
        if key == "outcomes" and league not in p["done"]:
            p["done"].append(league)
        p[key] = {**(p.get(key) or {}), **outcomes}
        p["updated"] = now.isoformat(timespec="seconds")
        _write(data_dir, day, passes)
        return p


def results(p: Mapping[str, Any]) -> dict[str, int]:
    """The pass's counts by outcome, each entry (or team page) by its latest post."""
    keys = RESULTS[p["kind"]]
    out = dict.fromkeys(keys, 0)
    for outcome in (p.get("outcomes") or {}).values():
        k = JOINS.get(outcome, outcome)
        if k in out:
            out[k] += 1
    return out


def il_results(p: Mapping[str, Any]) -> dict[str, int] | None:
    """A moves pass's IL runs by outcome, each entry by its latest run (#214); None before one."""
    return _side(p, "il", IL_RESULTS)


def drop_results(p: Mapping[str, Any]) -> dict[str, int] | None:
    """A moves pass's held drops by outcome, each entry by its latest run (#221 part 3); None
    before one."""
    return _side(p, "drop", DROP_RESULTS)


def start_active_results(p: Mapping[str, Any]) -> dict[str, int] | None:
    """A moves pass's Start Active runs by outcome, each league by its latest run (#215); None
    before one."""
    return _side(p, "start_active", SA_RESULTS)


def _side(p: Mapping[str, Any], key: str, keys: tuple[str, ...]) -> dict[str, int] | None:
    runs = p.get(key) or {}
    if not runs:
        return None
    out = dict.fromkeys(keys, 0)
    for outcome in runs.values():
        if outcome in out:
            out[outcome] += 1
    return out


def view(p: Mapping[str, Any]) -> dict[str, Any]:
    """A pass for the API: its progress (the leagues done of those named, in the order named; a
    moves pass's entries checked of those named, the total null without a list; a lineup pass's
    none), its results and a moves pass's IL runs (#214) and Start Active runs (#215), and the
    week plan's steps it left held (#221 part 2; None before it is done, or for a lineup pass)."""
    entries = p.get("entries")
    checked = [k for k in p.get("outcomes") or {} if entries is None or k in entries]
    return {
        "id": p["id"],
        "kind": p["kind"],
        "trigger": p["trigger"],
        "started": p["started"],
        "updated": p["updated"],
        "ended": p.get("ended"),
        "end": p.get("end"),
        "leagues": {"done": len(p["done"]), "total": len(p["leagues"]), "order": p["leagues"]},
        "entries": (
            {"done": len(checked), "total": None if entries is None else len(entries)}
            if p["kind"] == "moves"
            else None
        ),
        "current": p.get("current"),
        "results": results(p),
        "il": il_results(p),
        "drop": drop_results(p),
        "start_active": start_active_results(p),
        "held": p.get("held"),
        "summary": p.get("summary"),
    }


def active(passes: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The pass the Queue screen shows running: the newest open moves pass, else the newest open
    lineup pass; None when none is open."""
    running = [p for p in passes if p.get("end") is None]
    for kind in KINDS:
        mine = [p for p in running if p["kind"] == kind]
        if mine:
            return view(mine[-1])
    return None


def last_closed(passes: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The day's most recently closed pass (done or stale), None before one closes."""
    ended = [p for p in passes if p.get("end") is not None]
    if not ended:
        return None
    return view(max(ended, key=lambda p: _at(p["ended"])))


def _minutes(span: timedelta) -> int:
    return int(span.total_seconds() // 60)
