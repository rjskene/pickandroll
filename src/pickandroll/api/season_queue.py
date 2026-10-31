"""The moves executor's queue (#171, docs/AUTOPILOT.md sections 2, 3 and 5): its store, the execute
time, and the reads a build makes of each league; the entries themselves are
``season.autopilot``'s. Nothing here solves, clicks or submits anything.

``GET /autopilot/queue?date=``
    A day's queue (today by default): every armed league's row (queued, not solved today, off,
    private or failed, with why), the floors and typical gains it was built with, and every
    entry with its bid, its place, when it executes and its outcome.
``POST /autopilot/queue/build``
    Build today's queue from each armed league's last moves solve of the day in the decision log
    (#125): never a solve. Again the same day, it keeps the entries struck or executed and gives
    an entry new to the queue its full veto window (``season.autopilot.merge``).
``POST /autopilot/queue/{id}/strike``
    The user's veto, from the dashboard: strike an entry, or its bid alone (a $0 claim), or undo
    either; refused once the entry executed.
``PUT /autopilot/queue/settings``
    The day's execute time on the Central clock (``HH:MM``, 07:00 until the user sets one), and
    Sunday's own (#209, null until set; null clears it), each sent alone or together; today's
    entries not executed are timed again by the one in force today, never sooner than a full
    window after queueing.
``GET /seasons/{league}/autopilot/moves``, ``…/moves/due``, ``POST …/moves``
    The league's Queue card (the mode, the live check, the passes, its entries); the entries due
    now for the extension's execute pass, with the players protected and why, the day's cap, the
    adds left as read, the budget and whether a pass may place its claims (``live``); a pass
    appended to the league's log under ``moves`` (``season_autopilot``), a live pass's placed,
    failed and gone outcomes set on the queue's entries.
``PUT /leagues/{league}/moves``
    The moves executor's mode and the user's own cap on the day's moves.

``data/autopilot/queue/<date>.json`` holds a day's queue, ``data/autopilot/executor.json`` the
execute times, the live guards' counts (``live_after`` for the moves executor,
``lineup_live_after`` for the lineup executor's, set by hand on the user's word) and the
assumed rival claim rate of a standard-waivers league (``rival_claim_rate``, #261); each
is written whole to a temporary file and moved into place, and a file that does not read is
refused, never overwritten. Nothing else writes under either.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import Season
from ..season import autopilot as qa
from ..season import moves as mv
from ..season import progress as pg
from . import season_scorecard
from .season_knobs import autopilot_dir
from .season_week import NBA_TZ

QUEUE_DIR = "queue"
SETTINGS = "executor.json"
#: The live guard's counts the settings file may set (``live_after``).
LIVE_AFTER = ("dry_run_days", "checked_days")
#: The settings file's keys for each executor's counts: the moves executor's (#171 PR 3) and the
#: lineup executor's (#170 PR 3).
MOVES_LIVE_AFTER = "live_after"
LINEUP_LIVE_AFTER = "lineup_live_after"
#: The settings file's key for the rate a rival claims a waiver player (#261).
RIVAL_CLAIM_RATE = "rival_claim_rate"
EXECUTE_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
#: The waiver days when a league's settings do not say: the public leagues' (read 2026-10-23).
WAIVER_DAYS = 2
#: How far back a build looks for claims placed and not yet processed.
PENDING_DAYS = 7
#: A league row's status in the queue.
QUEUED, NOT_SOLVED, OFF, PRIVATE, FAILED = "queued", "not_solved", "off", "private", "failed"
NOT_SOLVED_REASON = "not solved today: the build reads the decision log and never solves"

_lock = threading.Lock()


class QueueError(ValueError):
    """A queue or settings file that cannot be rewritten without losing what is in it."""


def queue_dir(data_dir: Path) -> Path:
    return autopilot_dir(data_dir) / QUEUE_DIR


def queue_path(data_dir: Path, day: date) -> Path:
    return queue_dir(data_dir) / f"{day.isoformat()}.json"


def _read(path: Path, kind: type) -> Any:
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise QueueError(f"{path.name} does not read: {exc}") from exc
    if not isinstance(body, kind):
        raise QueueError(f"{path.name} is not the moves executor's")
    return body


def _write(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=1) + "\n")
    os.replace(tmp, path)


def read(data_dir: Path, day: date) -> dict[str, Any] | None:
    """The day's queue, None when there is none; :class:`QueueError` when it does not read."""
    body = _read(queue_path(data_dir, day), dict)
    if body is not None and not isinstance(body.get("entries", []), list):
        raise QueueError(f"{day.isoformat()}.json is not the moves executor's")
    return body


def update(
    data_dir: Path, day: date, change: Callable[[dict[str, Any] | None], dict[str, Any]]
) -> dict[str, Any]:
    """Read the day's queue, ``change`` it and write it back, all under the store's lock: two
    writers never interleave. ``change`` may raise to write nothing."""
    with _lock:
        body = change(read(data_dir, day))
        _write(queue_path(data_dir, day), body)
        return body


def days(data_dir: Path) -> list[date]:
    """The days with a queue, oldest first."""
    folder = queue_dir(data_dir)
    out = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            out.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    return out


def latest(data_dir: Path, on_or_before: date) -> dict[str, Any] | None:
    """The newest queue on or before a day that reads, for the digest."""
    for day in reversed([d for d in days(data_dir) if d <= on_or_before]):
        try:
            body = read(data_dir, day)
        except QueueError:
            continue
        if body is not None:
            return body
    return None


def day_of(entry_id: str) -> date | None:
    """The day an entry id names (``season.autopilot.entry_id``)."""
    try:
        return date.fromisoformat(entry_id.split(":", 1)[0])
    except ValueError:
        return None


# --------------------------------------------------------------------------- the execute time
def settings(data_dir: Path, day: date | None = None) -> dict[str, Any]:
    """The execute time (``HH:MM`` on the Central clock) with who set it and when; the code's
    default until the user sets one (``set`` False). Sunday's own (#209), null until one is set,
    with its own who and when. With ``day``, ``in_force`` is the one that holds on it. A file
    that does not read is the default."""
    try:
        body = _read(autopilot_dir(data_dir) / SETTINGS, dict) or {}
    except QueueError:
        body = {}
    value = body.get("execute_time")
    if not isinstance(value, str) or not EXECUTE_TIME.match(value):
        out = {"execute_time": qa.EXECUTE_TIME, "at": None, "by": None, "set": False}
    else:
        out = {"execute_time": value, "at": body.get("at"), "by": body.get("by"), "set": True}
    sunday = body.get("sunday_execute_time")
    if isinstance(sunday, str) and EXECUTE_TIME.match(sunday):
        out |= {
            "sunday_execute_time": sunday,
            "sunday_at": body.get("sunday_at"),
            "sunday_by": body.get("sunday_by"),
        }
    else:
        out |= {"sunday_execute_time": None, "sunday_at": None, "sunday_by": None}
    if day is not None:
        out["in_force"] = in_force(out, day)
    return out


def in_force(s: Mapping[str, Any], day: date) -> str:
    """The execute time that holds on ``day`` by the settings ``s``."""
    return qa.day_time(day, s["execute_time"], s.get("sunday_execute_time"))


def live_after(data_dir: Path, key: str = MOVES_LIVE_AFTER) -> dict[str, int]:
    """An executor's live-guard counts set in the settings file under ``key`` (the moves
    executor's ``live_after``, #171 PR 3; the lineup executor's ``lineup_live_after``, #170 PR 3):
    ``dry_run_days`` and ``checked_days``, each a whole number of at least 0. A count missing or
    not such a number is left out, so the guard keeps its default; a file that does not read sets
    none. Read at request time: a change needs no restart."""
    try:
        body = _read(autopilot_dir(data_dir) / SETTINGS, dict) or {}
    except QueueError:
        body = {}
    raw = body.get(key)
    if not isinstance(raw, dict):
        return {}
    return {
        k: v
        for k in LIVE_AFTER
        if isinstance(v := raw.get(k), int) and not isinstance(v, bool) and v >= 0
    }


def rival_claim_rate(data_dir: Path) -> float:
    """The assumed chance a team ahead of me in a standard-waivers league claims the player I
    claim (#261), set in the settings file under ``rival_claim_rate``: a number from 0 to 1, else
    the default (``moves.RIVAL_CLAIM_RATE``), as with a file that does not read. Read at request
    time: a change needs no restart."""
    try:
        body = _read(autopilot_dir(data_dir) / SETTINGS, dict) or {}
    except QueueError:
        body = {}
    raw = body.get(RIVAL_CLAIM_RATE)
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not 0 <= raw <= 1:
        return mv.RIVAL_CLAIM_RATE
    return float(raw)


def set_execute_time(data_dir: Path, value: str, by: str) -> dict[str, Any]:
    """Record the execute time, the dashboard's own click; the file's other keys are kept."""
    if not EXECUTE_TIME.match(value):
        raise QueueError(f"an execute time is HH:MM, not {value!r}")
    with _lock:
        path = autopilot_dir(data_dir) / SETTINGS
        body = _read(path, dict) or {}
        at = datetime.now(UTC).isoformat(timespec="seconds")
        _write(path, {**body, "execute_time": value, "at": at, "by": by})
    return settings(data_dir)


def set_sunday_execute_time(data_dir: Path, value: str | None, by: str) -> dict[str, Any]:
    """Record Sunday's own execute time (#209), or clear it (None: Sunday keeps the day's); the
    file's other keys are kept."""
    if value is not None and not EXECUTE_TIME.match(value):
        raise QueueError(f"an execute time is HH:MM, not {value!r}")
    with _lock:
        path = autopilot_dir(data_dir) / SETTINGS
        body = _read(path, dict) or {}
        at = datetime.now(UTC).isoformat(timespec="seconds")
        _write(path, {**body, "sunday_execute_time": value, "sunday_at": at, "sunday_by": by})
    return settings(data_dir)


# --------------------------------------------------------------------------- a league's day
def day_entry(entries: Iterable[Mapping[str, Any]], day: date) -> Mapping[str, Any] | None:
    """The day's last moves solve in the decision log (the day on the NBA's clock)."""
    out = None
    for e in entries:
        if e.get("source") != "moves":
            continue
        if datetime.fromisoformat(e["at"]).astimezone(NBA_TZ).date() == day:
            out = e
    return out


def protected_of(rule: mv.KeepRule | None) -> dict[int, str]:
    """My players the keep rule protects (#124), Yahoo's can't-cut players with them (#220) and
    held ones too (#221), each with why, as the engine has them."""
    if rule is None:
        return {}
    return {
        k: qa.keep_reason(x.net_positive, x.beats_best, x.returns, x.bench, x.cantcut)
        for k, x in (*rule.players.items(), *rule.held.items())
        if x.protected or x.bench
    }


def dropped_recently(season: Season, today: date) -> frozenset[int]:
    """The players my team dropped within the league's waiver days: never added back the same
    stretch (a drop goes to waivers and a re-add would be a claim on my own drop)."""
    me = season.settings.my_team_id
    waiver = season.settings.waiver_days
    span = WAIVER_DAYS if waiver is None else waiver
    out = set()
    for t in season.transactions:
        if t.kind != "drop" or t.team_id != me:
            continue
        when = mv.when_date(t.when, today)
        if when is not None and (today - when).days <= span:
            out.add(t.player.yahoo_id)
    return frozenset(out)


def budget_of(season: Season) -> float | None:
    me = season.settings.my_team_id
    return next((t.faab for t in season.teams if t.team_id == me), None)


def _weeks(adds: Mapping[str, Any] | None) -> list[tuple[date, date, int | None]]:
    return [
        (date.fromisoformat(w["start"]), date.fromisoformat(w["end"]), w.get("adds"))
        for w in (adds or {}).get("weeks") or []
    ]


def adds_left(
    adds: Mapping[str, Any] | None, taken: Iterable[Mapping[str, Any]]
) -> dict[tuple[date, date], int | None]:
    """Each week's adds left as the solve read them (the league's page and transactions, #94),
    less the entries ``taken``: claims placed and not yet processed, and the day's entries a
    rebuild keeps that hold a place; each counts in the week of its clear date (a claim counts
    when it is placed, the ruling's point 5, whether or not it will win)."""
    out: dict[tuple[date, date], int | None] = {(s, e): n for s, e, n in _weeks(adds)}
    for x in taken:
        clear = date.fromisoformat(x["from"]) if x.get("from") else day_of(x["id"])
        week = next((w for w in out if clear is not None and w[0] <= clear <= w[1]), None)
        if week is not None and out[week] is not None:
            out[week] = max(0, out[week] - 1)
    return out


def pending(queues: Iterable[Mapping[str, Any]], league: str) -> list[dict[str, Any]]:
    """The league's claims placed on earlier days and not yet resolved."""
    return [
        dict(e)
        for q in queues
        for e in q.get("entries") or []
        if e.get("league") == league and e.get("outcome") in qa.PLACED and not e.get("resolved")
    ]


def resolutions(
    season: Season, entries: Iterable[Mapping[str, Any]], today: date
) -> dict[str, str]:
    """The placed claims the league's transactions now settle, by entry id: ``won`` when my team
    added the player on or after the claim's day, ``lost`` when another team did."""
    me = season.settings.my_team_id
    out = {}
    for e in entries:
        since = day_of(e["id"])
        added, elsewhere = set(), set()
        for t in season.transactions:
            when = mv.when_date(t.when, today)
            if t.kind != "add" or when is None or (since is not None and when < since):
                continue
            (added if t.team_id == me else elsewhere).add(t.player.yahoo_id)
        result = qa.resolve(e, frozenset(added), frozenset(elsewhere))
        if result is not None:
            out[e["id"]] = result
    return out


# --------------------------------------------------------------------------- floors and the bid
def scored_differences(
    payloads: Iterable[Mapping[str, Any]], scoring: Mapping[str, str]
) -> dict[str, list[float]]:
    """The public leagues' scored moves whose judging horizon is over, realized less projected on
    it in the scorer's units, by scoring (``categories``, ``points``): the noise floor's spread
    (``season.autopilot.noise_floor``). The private league is never pooled."""
    out: dict[str, list[float]] = {}
    for p in payloads:
        kind = scoring.get(p.get("league") or "")
        if not p.get("public") or kind is None:
            continue
        for card in p.get("weeks") or []:
            # A week plan's steps are one decision (#221 part 2): one difference, not one a step.
            for _, projected, realized in season_scorecard.compared_units(card.get("moves") or []):
                out.setdefault(kind, []).append(round(realized - projected, 4))
    return out


def recent_gains(
    entries: Iterable[Mapping[str, Any]], today: date, span: int = qa.TYPICAL_DAYS
) -> list[float]:
    """A league's recommended moves of the last ``span`` days, each day's last moves solve's
    three weeks' set: their gains on the judging horizon, for the typical gain."""
    last: dict[date, Mapping[str, Any]] = {}
    for e in entries:
        if e.get("source") != "moves":
            continue
        day = datetime.fromisoformat(e["at"]).astimezone(NBA_TZ).date()
        if today - timedelta(days=span) < day <= today:
            last[day] = e
    out = []
    for e in last.values():
        s = qa.three_set(e) or {}
        for m in s.get("moves") or []:
            gain = (m.get("gain") or {}).get(qa.JUDGED)
            if gain is not None:
                out.append(float(gain))
    return out


def plan_floor(knobs: Mapping[str, Any] | None, scoring: str) -> float:
    """The plan floor of the knobs a solve ran with, for the league's scoring."""
    key = "plan_floor_points" if scoring == "points" else "plan_floor_cats"
    value = (knobs or {}).get(key)
    return float(pg.DEFAULTS[key] if value is None else value)


def daily_cap(mode: Mapping[str, Any], knobs: Mapping[str, Any] | None) -> tuple[int, str]:
    """The day's cap on a league's moves: the user's own (``PUT /leagues/{id}/moves``), else the
    knob's (``daily_cap``, docs/AUTOPILOT.md section 6), with which."""
    if mode.get("cap") is not None:
        return int(mode["cap"]), "the user"
    value = (knobs or {}).get("daily_cap")
    return int(pg.DEFAULTS["daily_cap"] if value is None else value), "the knob"


def sort_key(e: Mapping[str, Any]) -> tuple[Any, ...]:
    """The queue's order: by league, the queued by rank, then the others by gain."""
    return (e["league"], not e.get("queued"), e.get("rank") or 0, -(e.get("gain") or 0.0), e["id"])
