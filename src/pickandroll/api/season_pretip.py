"""The pre-tip pass for the private league (#355, docs/AUTOPILOT.md section 3): a Basketball
Monster pull and a re-solve of the private league shortly before the day's first tip-off, and
before the late slate's, so its same-day adds never rest on the 05:00 copy of the week's games.
Suggestions only: the pass clicks nothing in the private league, and its add/drop lines go to
the user's private push channel, never to a public issue.

The knobs live in ``data/autopilot/executor.json`` under ``pretip`` and are read at request time:
``enabled`` (false until the user says so), ``lead_min`` (how long before the tip-off a slate's
pass starts), ``late_slate`` (whether a late slate gets its own pass), ``late_gap_min`` (how far
after the first tip-off a tip-off starts the late slate) and ``latest_start`` (``HH:MM``
Central: no pass starts later, so it is over before the 21:00 build).

A slate is due from its start (its tip-off less the lead) until fifteen minutes before its
tip-off. The day file ``data/routine/pretip/<date>.json`` keeps every attempt of each slate, and
a slate is done only once an attempt's solve and push both completed (a late slate whose
recommended set is the first slate's needs no push). A lock skip, a crash or a failed push
leaves it due, so the next tick of the check timer tries again until fifteen minutes before the
tip-off; an attempt that solved and only failed to push is retried as a push alone.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from .season_knobs import autopilot_dir
from .season_queue import SETTINGS

CENTRAL = ZoneInfo("America/Chicago")
#: The knobs' defaults: off until the user turns the pass on.
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "lead_min": 60,
    "late_slate": True,
    "late_gap_min": 150,
    "latest_start": "20:40",
}
KNOB = "pretip"
#: A slate stays due until this long before its tip-off.
UNTIL_TIP_MIN = 15
FIRST, LATE = "first", "late"
SLATES = (FIRST, LATE)
DAY_DIR = ("routine", "pretip")
RULE = (
    "a slate is done only once an attempt's solve and push both completed (a late slate whose "
    "recommended set is the first's needs no push); a lock skip, a crash or a failed push leaves "
    f"it due until {UNTIL_TIP_MIN} minutes before its tip-off"
)
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_lock = threading.Lock()


def settings(data_dir: Path) -> dict[str, Any]:
    """The pass's knobs, each the file's when it reads as the right kind, else the default; a
    file that does not read gives the defaults."""
    try:
        body = json.loads((autopilot_dir(data_dir) / SETTINGS).read_text())
    except (OSError, ValueError):
        body = {}
    raw = body.get(KNOB) if isinstance(body, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULTS)
    for key in ("enabled", "late_slate"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    for key in ("lead_min", "late_gap_min"):
        v = raw.get(key)
        if isinstance(v, int) and not isinstance(v, bool) and 0 < v <= 600:
            out[key] = v
    if isinstance(raw.get("latest_start"), str) and _HHMM.match(raw["latest_start"]):
        out["latest_start"] = raw["latest_start"]
    return out


def tip_times(tips: Mapping[str, str]) -> list[datetime]:
    """The day's tip-offs (the schedule copy's ``tips``, UTC), each once, earliest first; one
    that does not read is left out."""
    out = set()
    for raw in tips.values():
        try:
            at = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if at.tzinfo is not None:
            out.add(at)
    return sorted(out)


def slates(tips: Mapping[str, str], knobs: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The day's slates: the first tip-off's, and with ``late_slate`` the first tip-off at least
    ``late_gap_min`` after it. Each is ``{slate, tip, start_at, until}`` on the Central clock."""
    times = tip_times(tips)
    if not times:
        return []
    lead = timedelta(minutes=knobs["lead_min"])
    picked = [(FIRST, times[0])]
    if knobs["late_slate"]:
        gap = times[0] + timedelta(minutes=knobs["late_gap_min"])
        later = next((t for t in times if t >= gap), None)
        if later is not None:
            picked.append((LATE, later))
    return [
        {
            "slate": name,
            "tip": tip.astimezone(CENTRAL).isoformat(),
            "start_at": (tip - lead).astimezone(CENTRAL).isoformat(),
            "until": (tip - timedelta(minutes=UNTIL_TIP_MIN)).astimezone(CENTRAL).isoformat(),
        }
        for name, tip in picked
    ]


def day_path(data_dir: Path, day: date) -> Path:
    return data_dir.joinpath(*DAY_DIR) / f"{day.isoformat()}.json"


def read_day(data_dir: Path, day: date) -> dict[str, Any]:
    """The day file: every attempt by slate, with whether the slate is done; empty when there is
    none or it does not read."""
    try:
        body = json.loads(day_path(data_dir, day).read_text())
    except (OSError, ValueError):
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("slates"), dict):
        return {"date": day.isoformat(), "rule": RULE, "slates": {}}
    return body


class PretipMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    add: int
    drop: int | None = None


class PretipRun(BaseModel):
    """One attempt of a slate, as the routine logs it. ``solved_at`` and ``pushed_at`` are set
    only when that step completed; ``unchanged``: a late slate's recommended set is the first's,
    so nothing was pushed and none is needed."""

    model_config = ConfigDict(extra="forbid")
    slate: Literal["first", "late"]
    started_at: datetime
    outcome: Literal["done", "skipped", "failed"]
    reason: str | None = Field(default=None, max_length=600)
    solved_at: datetime | None = None
    pushed_at: datetime | None = None
    unchanged: bool = False
    moves: list[PretipMove] = Field(default_factory=list, max_length=40)
    pulls: dict[str, str] = Field(default_factory=dict)


def done_of(attempt: Mapping[str, Any]) -> bool:
    """The rule: a completed solve and a completed push (or a late slate left unchanged)."""
    return bool(attempt.get("solved_at")) and bool(
        attempt.get("pushed_at") or attempt.get("unchanged")
    )


def record(data_dir: Path, day: date, run: PretipRun) -> dict[str, Any]:
    """Append ``run`` to the day file and mark its slate done by :func:`done_of`; written whole
    to a temporary file and moved into place."""
    row = run.model_dump(mode="json")
    path = day_path(data_dir, day)
    with _lock:
        body = read_day(data_dir, day)
        body["rule"] = RULE
        slate = body["slates"].setdefault(run.slate, {"done": False, "attempts": []})
        slate["attempts"].append(row)
        slate["done"] = bool(slate.get("done")) or done_of(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, indent=1) + "\n")
        os.replace(tmp, path)
    return body


def _hhmm(at: datetime) -> str:
    return f"{at.astimezone(CENTRAL):%H:%M}"


def due(
    data_dir: Path,
    now: datetime,
    day: date,
    tips: Mapping[str, str] | None,
    stopped: bool,
) -> dict[str, Any]:
    """Whether a slate's pass is due now, and which: ``{date, due, slate, tip, start_at, until,
    push_only, reason, slates, first_moves, knobs}``. ``push_only``: the slate's last attempt
    solved after its start and only its push is left. Nothing here opens a page."""
    knobs = settings(data_dir)
    body = read_day(data_dir, day)
    out: dict[str, Any] = {
        "date": day.isoformat(),
        "due": False,
        "slate": None,
        "tip": None,
        "start_at": None,
        "until": None,
        "push_only": False,
        "reason": None,
        "slates": [],
        "first_moves": None,
        "knobs": knobs,
        "rule": RULE,
    }
    first = body["slates"].get(FIRST) or {}
    solved = [a for a in first.get("attempts") or [] if a.get("solved_at")]
    if solved:
        out["first_moves"] = solved[-1].get("moves") or []
    if not knobs["enabled"]:
        return {**out, "reason": "the pre-tip pass is off (executor.json pretip.enabled)"}
    if stopped:
        return {**out, "reason": "STOP is on (data/autopilot/STOP)"}
    if tips is None:
        return {**out, "reason": "no schedule copy for today"}
    found = slates(tips, knobs)
    if not found:
        return {**out, "reason": "no game today"}
    latest = time.fromisoformat(knobs["latest_start"])
    reasons = []
    for s in found:
        kept = body["slates"].get(s["slate"]) or {}
        attempts = kept.get("attempts") or []
        s = {**s, "done": bool(kept.get("done")), "attempts": len(attempts)}
        out["slates"].append(s)
        start, until = datetime.fromisoformat(s["start_at"]), datetime.fromisoformat(s["until"])
        if s["done"]:
            reasons.append(f"the {s['slate']} slate is done")
            continue
        if now < start:
            reasons.append(f"the {s['slate']} slate starts at {_hhmm(start)}")
            break
        if now >= until:
            reasons.append(f"the {s['slate']} slate's time passed at {_hhmm(until)}")
            continue
        last = attempts[-1] if attempts else None
        push_only = bool(
            last
            and last.get("solved_at")
            and not last.get("pushed_at")
            and datetime.fromisoformat(last["solved_at"]) >= start
        )
        if not push_only and now.astimezone(CENTRAL).time() >= latest:
            reasons.append(f"the {s['slate']} slate would start past {knobs['latest_start']}")
            continue
        return {
            **out,
            "due": True,
            "slate": s["slate"],
            "tip": s["tip"],
            "start_at": s["start_at"],
            "until": s["until"],
            "push_only": push_only,
            "reason": None,
        }
    return {**out, "reason": "; ".join(reasons) or "nothing due"}


def move_lines(
    moves: Sequence[Mapping[str, Any]],
    names: Mapping[int, str],
    teams: Mapping[int, str | None],
    today: date,
) -> list[str]:
    """The recommended set as the push lists it: names and teams only, no number from Basketball
    Monster (the digest's public rule, kept here too)."""

    def who(k: int) -> str:
        team = teams.get(k)
        name = names.get(k, f"player {k}")
        return f"{name} ({team})" if team else name

    out = []
    for m in moves:
        drop = "open spot" if m.get("drop") is None else f"drop {who(m['drop'])}"
        when = ""
        if m.get("from") and str(m["from"]) > today.isoformat():
            when = f", from {date.fromisoformat(str(m['from'])):%a}"
        held = m.get("held") or {}
        first = (
            f"; first move {who(held['player'])} to {held['slot']}" if held.get("player") else ""
        )
        out.append(f"- add {who(m['add'])}, {drop}{when}{first}")
    return out


def exports_line(exports: Mapping[str, Mapping[str, Any] | None]) -> str:
    """The inputs' line: each export in force by its pull time on the Central clock."""
    parts = []
    for kind, label in (
        ("ros", "projections"),
        ("week_this", "this week"),
        ("week_next", "next week"),
    ):
        e = exports.get(kind)
        at = e.get("at") if e else None
        parts.append(f"{label} {_hhmm(datetime.fromisoformat(at))}" if at else f"{label} none")
    return "Inputs (Basketball Monster, pulled): " + ", ".join(parts) + "."


def markdown(
    league: str,
    day: date,
    moves: Sequence[Mapping[str, Any]],
    names: Mapping[int, str],
    teams: Mapping[int, str | None],
    exports: Mapping[str, Mapping[str, Any] | None],
    status: str,
) -> str:
    """The push's text: the league's recommended set (or why there is none) and the inputs' line."""
    lines = [f"League {league}, pre-tip suggestions for {day:%a %b} {day.day}:"]
    if status != "solved":
        lines.append("- not solved: no suggestion")
    elif not moves:
        lines.append("- no move recommended")
    else:
        lines += move_lines(moves, names, teams, day)
    lines.append(exports_line(exports))
    return "\n".join(lines) + "\n"
