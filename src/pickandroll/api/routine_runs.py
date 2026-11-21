"""The routines' run reports and live progress, read only (FLOOR PR 1, #458), for the floor.

``GET /routine/runs?date=YYYY-MM-DD&days=N``
    The run logs ``scripts/routine.py`` writes to ``data/routine/runs/<day>-<routine>.json``, for
    the day and the ``N - 1`` days before it (``N`` from 1 to 7; the day by default today on the
    Central clock, the routine host's). Each log is served as written, keyed by day and routine;
    a file that does not read is listed under its day's ``unread`` with the reason, never
    dropped. The private league's steps are included: the app is the user's own.
    Each day also carries ``pretip`` (#472), the pre-tip pass's slates for the floor's gates:
    the knobs' ``enabled`` and ``lead_min``, and each slate's ``tip``, ``start_at`` and
    ``until`` (planned from the day's tip-offs in the schedule copy, as ``season_pretip``
    plans them; null when the day has no copy), ``done``, ``missed`` and its attempts from the
    day file ``data/routine/pretip/<date>.json``: each attempt's ``started_at``, ``outcome``,
    ``reason``, ``solved_at``, ``pushed_at``, ``unchanged`` and ``lineups_at``, never its moves.
``GET /routine/live``
    The files in ``data/routine/live/`` (one a routine, rewritten after each step by FLOOR PR 2),
    each with when it was last written and ``stale`` when that is over an hour ago, since a run
    that died leaves its file behind. No folder or no file: an empty list.

Nothing here writes, reads Yahoo or changes a routine.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import season_pretip

CENTRAL = ZoneInfo("America/Chicago")
RUNS_DIR = ("routine", "runs")
LIVE_DIR = ("routine", "live")
#: The window ``days`` may take.
MIN_DAYS, MAX_DAYS = 1, 7
#: A live file last written longer ago than this is stale.
STALE_AFTER = timedelta(hours=1)
#: ``<day>-<routine>.json``; a routine's name may hold a hyphen (``evening-build``).
_RUN_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.json$")
#: What the floor reads of a pre-tip attempt: its times and outcome, never its moves or pulls.
ATTEMPT_FIELDS = (
    "started_at",
    "outcome",
    "reason",
    "solved_at",
    "pushed_at",
    "unchanged",
    "lineups_at",
)
#: A day's tip-offs (the schedule copy's ``tips``), None when the day has no copy.
TipsOf = Callable[[date], Mapping[str, str] | None]


def runs_dir(data_dir: Path) -> Path:
    return data_dir.joinpath(*RUNS_DIR)


def live_dir(data_dir: Path) -> Path:
    return data_dir.joinpath(*LIVE_DIR)


def _read_json(path: Path) -> tuple[Any, str | None]:
    """A file's JSON, or None and the reason it does not read."""
    try:
        return json.loads(path.read_text()), None
    except OSError as exc:
        return None, f"does not read: {exc.strerror or exc}"
    except ValueError as exc:
        return None, f"is not JSON: {exc}"


def pretip_day(data_dir: Path, day: date, tips: Mapping[str, str] | None) -> dict[str, Any]:
    """The pre-tip pass's slates on ``day``: those planned from its tip-offs, first and late,
    then any the day file kept that the plan does not name, each with its kept attempts."""
    knobs = season_pretip.settings(data_dir)
    planned = {s["slate"]: s for s in (season_pretip.slates(tips, knobs) if tips else [])}
    kept = season_pretip.read_day(data_dir, day)["slates"]
    out = []
    for name in season_pretip.SLATES:
        plan = planned.get(name) or {}
        slate = kept.get(name)
        slate = slate if isinstance(slate, dict) else {}
        if not plan and not slate:
            continue
        attempts = slate.get("attempts")
        out.append(
            {
                "slate": name,
                "tip": plan.get("tip"),
                "start_at": plan.get("start_at"),
                "until": plan.get("until"),
                "done": bool(slate.get("done")),
                "missed": bool(slate.get("missed")),
                "attempts": [
                    {k: a.get(k) for k in ATTEMPT_FIELDS}
                    for a in (attempts if isinstance(attempts, list) else [])
                    if isinstance(a, dict)
                ],
            }
        )
    return {"enabled": knobs["enabled"], "lead_min": knobs["lead_min"], "slates": out}


def runs(data_dir: Path, day: date, days: int = 1, tips_of: TipsOf | None = None) -> dict[str, Any]:
    """The run logs of ``day`` and the ``days - 1`` days before it, oldest day first, each day
    with its pre-tip slates (:func:`pretip_day`, planned from ``tips_of`` when given)."""
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise ValueError(f"days {days} is not from {MIN_DAYS} to {MAX_DAYS}")
    wanted = [day - timedelta(days=n) for n in range(days - 1, -1, -1)]
    found: dict[str, list[tuple[str, Path]]] = {d.isoformat(): [] for d in wanted}
    folder = runs_dir(data_dir)
    if folder.is_dir():
        for path in sorted(folder.iterdir()):
            m = _RUN_FILE.match(path.name)
            if m and m.group(1) in found and path.is_file():
                found[m.group(1)].append((m.group(2), path))
    out = []
    for d, files in found.items():
        logs: dict[str, Any] = {}
        unread: list[dict[str, Any]] = []
        for routine, path in files:
            body, reason = _read_json(path)
            if reason is None and not isinstance(body, dict):
                reason = "is not a run log (not a JSON object)"
            if reason is None:
                logs[routine] = body
            else:
                unread.append({"routine": routine, "file": path.name, "reason": reason})
        tips = tips_of(date.fromisoformat(d)) if tips_of is not None else None
        out.append(
            {
                "date": d,
                "runs": logs,
                "unread": unread,
                "pretip": pretip_day(data_dir, date.fromisoformat(d), tips),
            }
        )
    return {"date": day.isoformat(), "days": days, "by_day": out}


def live(data_dir: Path, now: datetime) -> dict[str, Any]:
    """Every live progress file, by routine, with when it was last written and whether stale."""
    folder = live_dir(data_dir)
    rows: list[dict[str, Any]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            if not path.is_file():
                continue
            try:
                written = datetime.fromtimestamp(path.stat().st_mtime, CENTRAL)
            except OSError:
                continue  # gone between the listing and the read: a run finished and removed it
            body, reason = _read_json(path)
            rows.append(
                {
                    "routine": path.stem,
                    "file": path.name,
                    "written_at": written.isoformat(timespec="seconds"),
                    "stale": now - written > STALE_AFTER,
                    "progress": body,
                    "reason": reason,
                }
            )
    return {"now": now.isoformat(timespec="seconds"), "live": rows}
