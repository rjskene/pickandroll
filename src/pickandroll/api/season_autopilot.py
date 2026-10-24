"""The lineup executor's side of the API (#170, docs/AUTOPILOT.md section 2): its steps, its mode,
STOP, its log and the digest's line. The executor itself is the extension's content script on the
league's own team page; nothing here clicks or submits anything.

``GET /seasons/{league}/lineup/steps?date=``
    The changes that turn Yahoo's lineup as read into the recommended one for a day
    (:func:`steps_payload`), from the Lineup view's own day: nothing is solved again.
``PUT /leagues/{league}/lineups``
    The mode, ``off``, ``dry_run`` or ``live`` (``leagues.lineup_mode``), the dashboard's own
    click. ``live`` is refused until :func:`live_check` passes; the private league is refused.
``POST /seasons/{league}/autopilot/lineup``
    A run of the executor, appended to ``data/leagues/<id>/autopilot/<date>.json``
    (:func:`append_run`), the only writer there.
``GET /seasons/{league}/autopilot``
    The mode, STOP, the live check, the last run and today's runs, for the Lineup view.

``data/autopilot/STOP`` stops every executor: the steps answer ``stop: true`` with none, and the
log takes only a run that says it stopped. Nothing here writes the file.

The page's crumb (Yahoo's form token) is never posted here: a run carrying a ``crumb`` key is
refused, and nothing here stores one.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..season import lineup as lu
from ..season import weekly as wk
from ..sources.yahoo import public
from . import leagues
from .season_knobs import autopilot_dir

STOP = "STOP"
#: The executors' log under the league folder: one file per NBA date.
LOG_DIR = "autopilot"
LINEUP = "lineup"
TRIGGERS = ("routine", "routine_late", "panel")
RUN_OUTCOMES = ("would_set", "nothing_to_do", "skipped", "set", "failed", "stopped")
STEP_OUTCOMES = ("would_set", "skipped", "set", "failed")
#: The dry run ``live`` waits for (the 2026-10-23 ruling on #170): dry-run lineup runs on this many
#: distinct days, and on this many of them a run whose steps all passed every check.
DRY_RUN_DAYS = 7
CHECKED_DAYS = 2
#: The digest counts the runs of the last day.
DIGEST_SPAN = timedelta(hours=24)

_lock = threading.Lock()


class LogError(ValueError):
    """A log file that cannot be appended to without losing what is in it."""


def stop_path(data_dir: Path) -> Path:
    return autopilot_dir(data_dir) / STOP


def stopped(data_dir: Path) -> bool:
    return stop_path(data_dir).exists()


def log_dir(data_dir: Path, league: str) -> Path:
    return leagues.league_dir(data_dir, league) / LOG_DIR


# --------------------------------------------------------------------------- the steps
def _tip(tips: Mapping[str, str] | None, team: str | None) -> datetime | None:
    raw = (tips or {}).get(team or "")
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def steps_payload(
    league: str,
    team: int | None,
    day: date,
    today: date,
    now: datetime,
    lineup: Mapping[str, Any] | None,
    tips: Mapping[str, str] | None,
    mode: Mapping[str, Any],
    stop: bool,
) -> dict[str, Any]:
    """The executor's steps for ``day``: the Lineup view's ``lineup`` for the day's week, Yahoo's
    lineup as read turned into one that starts the recommended players
    (``season.lineup.target_lineup``, ``lineup_steps``).

    Each step is ``{player, from_slot, to_slot, with, tip, group}``: ``with`` is the player in
    ``to_slot`` who goes to ``from_slot``, ``tip`` his or the player's team's tip-off (null when
    the schedule's copy predates the tip-offs), ``group`` the step's group. A group with a
    player whose tip-off has passed is left out whole, under ``skipped``; the others run in the
    order of their first tip-off. ``target`` is each moved player's slot after the steps,
    ``games`` the starts that play as recommended, as read and after. ``slots`` are the league's
    starting slots and ``yahoo`` each player's slot as read, for the page's own check that it is
    the lineup the steps were built from and that an empty target slot is open. No steps when the mode is
    off, STOP is on, or the day is closed (``open`` false: past, before the rule's first day, a
    weekly league's day after the week opened) or not read; ``reason`` says which."""
    out: dict[str, Any] = {
        "league": league,
        "team": team,
        "date": day.isoformat(),
        "page": public.team_url(league, team, day) if team is not None else None,
        "mode": mode["mode"],
        "stop": stop,
        "open": False,
        "reason": None,
        "read": None,
        "steps": [],
        "skipped": [],
        "target": {},
        "games": None,
        "tips": tips is not None,
        "slots": [],
        "yahoo": {},
    }

    def closed(reason: str) -> dict[str, Any]:
        return {**out, "reason": reason}

    if mode.get("private"):
        return closed("the private league is never touched")
    if team is None:
        return closed("no team of mine in this league")
    days = {d["date"]: d for d in (lineup or {}).get("days", [])}
    d = days.get(day.isoformat())
    if lineup is None or d is None:
        return closed("the day is not one of the lineup's weeks")
    rule = lineup["rule"]
    if rule.get("changes") is None:
        return closed("the league's lineup rule is not read")
    if rule["changes"] == "weekly" and day.isoformat() != lineup["start"]:
        return closed("a weekly lineup is set on the week's first day")
    if day < today or d["past"] or d["recommended"] is None:
        return closed("the day takes no more changes")
    out["open"] = True
    if d["yahoo"] is None:
        return closed("Yahoo's lineup for the day is not read")
    out["read"] = {"at": d["yahoo"]["read_at"], "page": d["yahoo"]["page"]}
    out["slots"] = list(lineup["slots"])
    out["yahoo"] = {str(x["player"]): x["slot"] for x in d["yahoo"]["slots"]}
    if mode["mode"] == "off":
        return closed("the lineup executor is off in this league")
    if stop:
        return closed("STOP is on (data/autopilot/STOP)")

    players = lineup["players"]
    spots = [
        (x["slot"], x["player"], players.get(str(x["player"]), {}).get("positions", ()))
        for x in d["yahoo"]["slots"]
    ]
    target = lu.target_lineup(spots, d["start"], d["sit"], lineup["slots"])
    groups = lu.lineup_steps(spots, target, lineup["slots"]) if target is not None else None
    if groups is None:
        return closed("the recommended starters do not fit Yahoo's lineup as read")

    def tip(k: int | None) -> datetime | None:
        return None if k is None else _tip(tips, players.get(str(k), {}).get("nba_team"))

    kept: list[tuple[datetime | None, list[lu.Step[int]]]] = []
    for group in groups:
        moved = {k for s in group for k in (s.player, s.swapped) if k is not None}
        times = [t for t in map(tip, moved) if t is not None]
        if any(t <= now for t in times):
            out["skipped"].append(
                {
                    "reason": "tip-off passed",
                    "players": sorted(moved),
                    "steps": [_step(s, tip, None) for s in group],
                }
            )
            continue
        kept.append((min(times) if times else None, group))
    kept.sort(key=lambda x: (x[0] is None, x[0] or now))
    out["steps"] = [_step(s, tip, i) for i, (_, group) in enumerate(kept) for s in group]
    applied = [s for _, group in kept for s in group]
    after = lu.apply_steps(spots, applied)
    current = {k: slot for slot, k, _ in spots}
    out["target"] = {str(k): slot for k, slot in after.items() if slot != current[k]}
    playing = set(d["playing"])
    out["games"] = {
        "recommended": d["games"]["recommended"],
        "yahoo": d["games"]["yahoo"],
        "after": sum(
            1 for k, slot in after.items() if slot.upper() not in wk.NOT_STARTING and k in playing
        ),
    }
    if not out["steps"]:
        out["reason"] = (
            "every change waits on a game that began"
            if out["skipped"]
            else "Yahoo's lineup already starts the recommended players"
        )
    return out


def _step(step: lu.Step[int], tip: Any, group: int | None) -> dict[str, Any]:
    times = [t for t in (tip(step.player), tip(step.swapped)) if t is not None]
    return {
        "player": step.player,
        "from_slot": step.from_slot,
        "to_slot": step.to_slot,
        "with": step.swapped,
        "tip": min(times).isoformat() if times else None,
        "group": group,
    }


# --------------------------------------------------------------------------- the log
class StepRun(BaseModel):
    """One step of a run as the executor saw it on the page."""

    model_config = ConfigDict(populate_by_name=True)

    player: int
    from_slot: str
    to_slot: str
    with_: int | None = Field(None, alias="with")
    tip: str | None = None
    group: int | None = None
    outcome: Literal["would_set", "skipped", "set", "failed"]
    reason: str | None = None
    #: What the page showed for the step's players: the control (``select`` or ``locked``), the
    #: slot and the options.
    control: dict[str, Any] | None = None


class LineupRun(BaseModel):
    """A run of the lineup executor on one team page, for the log."""

    day: date
    mode: Literal["dry_run", "live"]
    trigger: Literal["routine", "routine_late", "panel"]
    outcome: Literal["would_set", "nothing_to_do", "skipped", "set", "failed", "stopped"]
    reason: str | None = None
    #: The team page's path and date.
    page: str | None = None
    #: The read the steps came from (the steps' ``read.at``).
    read_at: str | None = None
    steps: list[StepRun] = []
    #: The API's groups left out, as the steps gave them.
    skipped: list[dict[str, Any]] = []
    #: The form as the page had it: its action path and method, its field names (never a
    #: value), the swap labels counted.
    controls: dict[str, Any] | None = None
    #: The page's lineup before the run and after it (a dry run: the lineup the steps would
    #: leave), each player's slot by Yahoo id; the players whose games began.
    before: dict[str, str] | None = None
    after: dict[str, str] | None = None
    locked: list[int] = []
    #: Yahoo's save message, as the page printed it.
    message: str | None = None
    extension: str | None = None


def has_crumb(value: Any) -> bool:
    """Whether ``value`` carries a key naming Yahoo's form token anywhere."""
    if isinstance(value, Mapping):
        return any("crumb" in str(k).lower() or has_crumb(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(has_crumb(v) for v in value)
    return False


def read_log(data_dir: Path, league: str, day: date) -> dict[str, Any] | None:
    """A day's log file, None when there is none; :class:`LogError` when it is not a JSON
    object."""
    path = log_dir(data_dir, league) / f"{day.isoformat()}.json"
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise LogError(f"{path.name} does not read: {exc}") from exc
    if not isinstance(body, dict) or not isinstance(body.get(LINEUP, []), list):
        raise LogError(f"{path.name} is not an autopilot log")
    return body


def lineup_runs(data_dir: Path, league: str) -> list[tuple[date, dict[str, Any]]]:
    """Every lineup run logged for ``league``, oldest first, with its file's date; a file that
    does not read is left out."""
    out = []
    folder = log_dir(data_dir, league)
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            day = date.fromisoformat(path.stem)
            body = read_log(data_dir, league, day)
        except (ValueError, LogError):
            continue
        out += [(day, run) for run in (body or {}).get(LINEUP, []) if isinstance(run, dict)]
    return out


def append_run(data_dir: Path, league: str, run: Mapping[str, Any], today: date) -> dict[str, Any]:
    """Append ``run`` to today's log, never rewriting another run: the file's other keys (phase
    2's ``moves``) and runs stay as they are, and a file that does not read is refused, never
    overwritten. Written whole to a temporary file and moved into place."""
    folder = log_dir(data_dir, league)
    with _lock:
        body = read_log(data_dir, league, today) or {}
        body = {**body, LINEUP: [*body.get(LINEUP, []), dict(run)]}
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{today.isoformat()}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, indent=1) + "\n")
        os.replace(tmp, path)
    return dict(run)


def checks_passed(run: Mapping[str, Any]) -> bool:
    """A run with steps, every one of them through every check of the page."""
    steps = run.get("steps") or []
    return bool(steps) and all(s.get("outcome") in ("would_set", "set") for s in steps)


def live_check(data_dir: Path, league: str, mode: Mapping[str, Any]) -> dict[str, Any]:
    """Whether the league may be switched to ``live`` (the 2026-10-23 ruling on #170): dry-run
    lineup runs on :data:`DRY_RUN_DAYS` distinct days, on :data:`CHECKED_DAYS` of them a run
    whose steps all passed every check, and STOP absent. The review on #127 and the user's
    click are the other two gates."""
    runs = [(d, r) for d, r in lineup_runs(data_dir, league) if r.get("mode") == "dry_run"]
    days = {d for d, _ in runs}
    checked = {d for d, r in runs if checks_passed(r)}
    reason = None
    if mode.get("private"):
        reason = "the private league is never touched"
    elif stopped(data_dir):
        reason = "STOP is on (data/autopilot/STOP)"
    elif len(days) < DRY_RUN_DAYS:
        reason = f"a dry run on {DRY_RUN_DAYS} days first: {len(days)} so far"
    elif len(checked) < CHECKED_DAYS:
        reason = (
            f"{CHECKED_DAYS} dry-run days with steps that passed every check first: "
            f"{len(checked)} so far"
        )
    return {
        "ok": reason is None,
        "reason": reason,
        "dry_run_days": len(days),
        "checked_days": len(checked),
        "needs": {"dry_run_days": DRY_RUN_DAYS, "checked_days": CHECKED_DAYS},
    }


def check_run(run: LineupRun, mode: Mapping[str, Any], stop: bool) -> str | None:
    """Why the log refuses ``run``, None when it takes it."""
    if mode.get("private"):
        return "the private league is never touched"
    if stop and run.outcome != "stopped":
        return "STOP is on: a run can only say it stopped"
    if mode["mode"] == "off" and run.outcome != "stopped":
        return "the lineup executor is off in this league"
    if run.mode == "live" and mode["mode"] != "live":
        return "a live run in a league that is not live"
    sets = run.outcome == "set" or any(s.outcome == "set" for s in run.steps)
    if run.mode == "dry_run" and sets:
        return "a dry run sets nothing"
    return None


def view(data_dir: Path, league: str, mode: Mapping[str, Any], today: date) -> dict[str, Any]:
    """The Lineup view's panel: the mode, STOP, the live check, the last run, today's runs."""
    runs = lineup_runs(data_dir, league)
    return {
        "league": league,
        "mode": dict(mode),
        "stop": stopped(data_dir),
        "live": live_check(data_dir, league, mode),
        "last": runs[-1][1] if runs else None,
        "today": [r for d, r in runs if d == today],
        "days": sorted({d.isoformat() for d, _ in runs}),
    }


# --------------------------------------------------------------------------- the digest
def _counts(runs: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    days_set = {r["day"] for r in runs if r.get("outcome") in ("would_set", "set")}
    skipped = sum(
        1
        for r in runs
        if r.get("outcome") == "skipped"
        or r.get("skipped")
        or any(s.get("outcome") == "skipped" for s in r.get("steps") or [])
    )
    failed = sum(
        1
        for r in runs
        if r.get("outcome") == "failed"
        or any(s.get("outcome") == "failed" for s in r.get("steps") or [])
    )
    return {"set": len(days_set), "skipped": skipped, "failed": failed}


def _weekday(day: str) -> str:
    try:
        return f"{date.fromisoformat(day):%a}"
    except ValueError:
        return day


def digest_lines(
    data_dir: Path, modes: Mapping[str, Mapping[str, Any]], now: datetime
) -> list[str]:
    """The digest's lines for the lineup executor: one summary over the armed leagues
    (``modes``, a league's mode by id; the private league is left out), the runs of the last
    day counted, then a line per league only for what it skipped or failed. Leagues by id."""
    armed = {
        lg: m["mode"] for lg, m in modes.items() if not m.get("private") and m["mode"] != "off"
    }
    if not armed:
        return []
    if stopped(data_dir):
        return ["- Lineup executor: STOP is on (data/autopilot/STOP); nothing runs."]
    since = now - DIGEST_SPAN
    recent: dict[str, list[dict[str, Any]]] = {}
    for lg in armed:
        recent[lg] = [
            r
            for _, r in lineup_runs(data_dir, lg)
            if (at := _at(r.get("at"))) is not None and at >= since
        ]
    by_mode = {m: sorted(lg for lg, x in armed.items() if x == m) for m in ("dry_run", "live")}
    modes_text = ", ".join(
        f"{'dry run' if m == 'dry_run' else 'live'} in {len(lgs)}"
        for m, lgs in by_mode.items()
        if lgs
    )
    with_steps = [lg for lg, rs in recent.items() if any(r.get("steps") for r in rs)]
    without = [lg for lg, rs in recent.items() if rs and not any(r.get("steps") for r in rs)]
    not_run = [lg for lg, rs in recent.items() if not rs]
    counted = [_counts(rs) for rs in recent.values()]
    total = {k: sum(c[k] for c in counted) for k in ("set", "skipped", "failed")}
    if not by_mode["dry_run"]:
        verb = "set"
    else:
        verb = "would be set" if not by_mode["live"] else "set or would be set"
    summary = (
        f"- Lineup executor ({modes_text}): {len(with_steps)} with steps, {len(without)} with "
        f"none, {len(not_run)} not run; {total['set']} day{'s' if total['set'] != 1 else ''} "
        f"{verb}, {total['skipped']} skipped, {total['failed']} failed."
    )
    lines = [summary]
    for lg in sorted(recent):
        parts = []
        for r in recent[lg]:
            c = _counts([r])
            if c["skipped"] or c["failed"]:
                what = "failed" if c["failed"] else "skipped"
                reason = (
                    r.get("reason")
                    or next(
                        (
                            s.get("reason")
                            for s in r.get("steps") or []
                            if s.get("outcome") in ("failed", "skipped")
                        ),
                        None,
                    )
                    or next((g.get("reason") for g in r.get("skipped") or []), None)
                )
                parts.append(f"{_weekday(r['day'])} {what}" + (f" ({reason})" if reason else ""))
        if parts:
            lines.append(f"- League {lg}: " + "; ".join(parts))
    return lines


def _at(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
