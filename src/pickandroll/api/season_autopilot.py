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

The moves executor (#171) logs its execute passes in the same file under ``moves``
(:class:`MovesRun`, :func:`append_run` by key), and has its own live check
(:func:`moves_live_check`, its counts the code's defaults unless the settings file's
``live_after`` sets them, read at request time: #171 PR 3) and digest line
(:func:`moves_digest_lines`); its queue is ``season_queue``'s. The queue's payload and the Queue card read each entry's latest line of the
queue's day and the day's tally from it (:func:`latest_passes`, :func:`pass_tally`, #200).

``data/autopilot/STOP`` stops every executor: the steps answer ``stop: true`` with none, and the
log takes only a run that says it stopped. Nothing here writes the file.

The page's crumb (Yahoo's form token) is never posted here: a run carrying a ``crumb`` key is
refused, and nothing here stores one.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..season import lineup as lu
from ..season import weekly as wk
from ..sources.yahoo import public
from . import leagues
from .season_knobs import autopilot_dir
from .season_queue import live_after

STOP = "STOP"
#: The executors' log under the league folder: one file per NBA date.
LOG_DIR = "autopilot"
LINEUP = "lineup"
#: The moves executor's execute passes, beside the lineup's runs in the same file (#171).
MOVES = "moves"
LOG_KEYS = (LINEUP, MOVES)
#: What started a pass: the morning routine, the late one, the side panel, and for the moves
#: executor alone the evening routine (#209).
TRIGGERS = ("routine", "routine_late", "panel", "routine_evening")
RUN_OUTCOMES = ("would_set", "nothing_to_do", "skipped", "set", "failed", "stopped")
STEP_OUTCOMES = ("would_set", "skipped", "set", "failed")
#: The dry run ``live`` waits for (the 2026-10-23 ruling on #170): dry-run lineup runs on this many
#: distinct days, and on this many of them a run whose steps all passed every check. The moves
#: executor's are the defaults of ``data/autopilot/executor.json``'s ``live_after`` (#171 PR 3).
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
    if not isinstance(body, dict) or not all(isinstance(body.get(k, []), list) for k in LOG_KEYS):
        raise LogError(f"{path.name} is not an autopilot log")
    return body


def runs(data_dir: Path, league: str, key: str = LINEUP) -> list[tuple[date, dict[str, Any]]]:
    """Every run logged for ``league`` under ``key`` (the lineup's or the moves'), oldest first,
    with its file's date; a file that does not read is left out."""
    out = []
    folder = log_dir(data_dir, league)
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            day = date.fromisoformat(path.stem)
            body = read_log(data_dir, league, day)
        except (ValueError, LogError):
            continue
        out += [(day, run) for run in (body or {}).get(key, []) if isinstance(run, dict)]
    return out


def lineup_runs(data_dir: Path, league: str) -> list[tuple[date, dict[str, Any]]]:
    """Every lineup run logged for ``league``: :func:`runs` of ``lineup``."""
    return runs(data_dir, league, LINEUP)


def append_run(
    data_dir: Path, league: str, run: Mapping[str, Any], today: date, key: str = LINEUP
) -> dict[str, Any]:
    """Append ``run`` to today's log under ``key``, never rewriting another run: the file's other
    key and runs stay as they are, and a file that does not read is refused, never overwritten.
    Written whole to a temporary file and moved into place."""
    if key not in LOG_KEYS:
        raise LogError(f"a log key is one of {', '.join(LOG_KEYS)}, not {key!r}")
    folder = log_dir(data_dir, league)
    with _lock:
        body = read_log(data_dir, league, today) or {}
        body = {**body, key: [*body.get(key, []), dict(run)]}
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
    dry = [(d, r) for d, r in lineup_runs(data_dir, league) if r.get("mode") == "dry_run"]
    days = {d for d, _ in dry}
    checked = {d for d, r in dry if checks_passed(r)}
    needs = {"dry_run_days": DRY_RUN_DAYS, "checked_days": CHECKED_DAYS}
    return _gate(data_dir, mode, days, checked, "with steps that passed every check", needs)


def _gate(
    data_dir: Path,
    mode: Mapping[str, Any],
    days: set[date],
    checked: set[date],
    what: str,
    needs: Mapping[str, int],
) -> dict[str, Any]:
    reason = None
    if mode.get("private"):
        reason = "the private league is never touched"
    elif stopped(data_dir):
        reason = "STOP is on (data/autopilot/STOP)"
    elif len(days) < needs["dry_run_days"]:
        reason = f"a dry run on {_days(needs['dry_run_days'])} first: {len(days)} so far"
    elif len(checked) < needs["checked_days"]:
        n = needs["checked_days"]
        reason = f"{n} dry-run {'day' if n == 1 else 'days'} {what} first: {len(checked)} so far"
    return {
        "ok": reason is None,
        "reason": reason,
        "dry_run_days": len(days),
        "checked_days": len(checked),
        "needs": dict(needs),
    }


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


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


# --------------------------------------------------------------------------- the moves executor
MOVE_OUTCOMES = ("would_claim", "claimed", "added", "skipped", "failed", "gone")
#: A live pass's outcomes that go on the queue's entry and take it out of the day's due ones: a
#: live skip stays due, so the late pass reads the page again (#171 PR 3).
STICKS = ("claimed", "added", "failed", "gone")
MOVES_RUN_OUTCOMES = ("would_claim", "nothing_due", "skipped", "claimed", "failed", "stopped")


class MoveCheck(BaseModel):
    """One queue entry as an execute pass saw it on the add page (#171)."""

    #: The queue entry's id (``season.autopilot.entry_id``).
    id: str
    add: int
    drop: int | None = None
    #: The bid the claim was (or in a dry run would be) placed with, in dollars.
    bid: int | None = None
    #: ``gone``: another team had the add before the pass reached him; never retried that day.
    outcome: Literal["would_claim", "claimed", "added", "skipped", "failed", "gone"]
    reason: str | None = None
    #: The add page's path.
    page: str | None = None
    #: What the page showed: the form's action and method, its field names (never a value), the
    #: drop's control and the bid's input.
    controls: dict[str, Any] | None = None
    #: Yahoo's message after a live submit, as the page printed it.
    message: str | None = None


class MovesRun(BaseModel):
    """An execute pass of the moves executor in one league, for the log (#171)."""

    day: date
    mode: Literal["dry_run", "live"]
    trigger: Literal["routine", "routine_late", "panel", "routine_evening"]
    outcome: Literal["would_claim", "nothing_due", "skipped", "claimed", "failed", "stopped"]
    reason: str | None = None
    entries: list[MoveCheck] = []
    extension: str | None = None


def check_moves_run(
    run: MovesRun,
    mode: Mapping[str, Any],
    stop: bool,
    queue: Mapping[str, Mapping[str, Any]],
    live: Mapping[str, Any] | None = None,
) -> str | None:
    """Why the log refuses an execute pass, None when it takes it. ``queue`` is the day's
    entries of the league by id: a pass reports only on those, and never executes one struck or
    not queued. ``live`` is :func:`moves_live_check`'s answer now: a live pass needs it to hold,
    and places a claim or says why not, never that it would (#171 PR 3)."""
    if mode.get("private"):
        return "the private league is never touched"
    if stop and run.outcome != "stopped":
        return "STOP is on: a pass can only say it stopped"
    if mode["mode"] == "off" and run.outcome != "stopped":
        return "the moves executor is off in this league"
    if run.mode == "live" and mode["mode"] != "live":
        return "a live pass in a league that is not live"
    if run.mode == "live" and live is not None and not live.get("ok"):
        return f"live refused: {live.get('reason')}"
    if run.mode == "live" and (
        run.outcome == "would_claim" or any(e.outcome == "would_claim" for e in run.entries)
    ):
        return "a live pass places a claim or says why not; it never says would"
    placed = ("claimed", "added")
    if run.mode == "dry_run" and (
        run.outcome == "claimed" or any(e.outcome in placed for e in run.entries)
    ):
        return "a dry run claims nothing"
    for e in run.entries:
        q = queue.get(e.id)
        if q is None:
            return f"{e.id} is not in the day's queue"
        if (e.add, e.drop) != (q.get("add"), q.get("drop")):
            return f"{e.id} names another move than the queue's"
        executed = e.outcome in ("would_claim", *placed)
        if executed and (not q.get("queued") or q.get("struck")):
            return f"{e.id} is struck or not queued: it is never executed"
        if q.get("outcome") in ("would_claim", *placed):
            return f"{e.id} was executed already"
        if q.get("outcome") in ("failed", "gone"):
            return f"{e.id} is {q['outcome']} today: it is never retried that day"
    return None


def moves_checked(run: Mapping[str, Any]) -> bool:
    """A pass that opened the add page and logged its controls for at least one entry (the
    ruling on #171): a pass that found nothing due is a dry-run day, never a checked one."""
    return any(e.get("controls") for e in run.get("entries") or [])


def moves_needs(data_dir: Path) -> dict[str, int]:
    """The moves executor's live-guard counts in force: :data:`DRY_RUN_DAYS` and
    :data:`CHECKED_DAYS` unless the settings file's ``live_after`` sets them (#171 PR 3)."""
    return {"dry_run_days": DRY_RUN_DAYS, "checked_days": CHECKED_DAYS, **live_after(data_dir)}


def moves_live_check(data_dir: Path, league: str, mode: Mapping[str, Any]) -> dict[str, Any]:
    """Whether the league's moves executor may be live: dry-run passes on the days
    :func:`moves_needs` asks, that many of them checked (:func:`moves_checked`), and STOP absent.
    It gates the switch to ``live`` and, in a live league, every pass that places a claim (``due``'s
    ``live``, #171 PR 3). The reviewed week on #127 and the user's click are the other gates."""
    dry = [(d, r) for d, r in runs(data_dir, league, MOVES) if r.get("mode") == "dry_run"]
    days = {d for d, _ in dry}
    checked = {d for d, r in dry if moves_checked(r)}
    needs = moves_needs(data_dir)
    return _gate(data_dir, mode, days, checked, "that read the add page", needs)


def moves_view(
    data_dir: Path,
    league: str,
    mode: Mapping[str, Any],
    today: date,
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """The Queue card's league: the mode, STOP, the live check, the last pass, today's passes
    and the league's entries of the day's queue."""
    passes = runs(data_dir, league, MOVES)
    todays = [r for d, r in passes if d == today]
    latest = latest_passes(r for r in todays if r.get("day") == today.isoformat())
    return {
        "league": league,
        "mode": dict(mode),
        "stop": stopped(data_dir),
        "live": moves_live_check(data_dir, league, mode),
        "last": passes[-1][1] if passes else None,
        "today": todays,
        "days": sorted({d.isoformat() for d, _ in passes}),
        "entries": [{**e, "pass": latest.get(str(e.get("id")))} for e in entries],
    }


# --------------------------------------------------------------------------- the pass results
def day_lines(data_dir: Path, league: str, day: date) -> list[dict[str, Any]]:
    """The league's moves passes of the queue's ``day`` (#200): its day file's lines whose ``day``
    is that day, oldest first; none when the file does not read."""
    try:
        body = read_log(data_dir, league, day) or {}
    except LogError:
        return []
    return [
        r for r in body.get(MOVES, []) if isinstance(r, dict) and r.get("day") == day.isoformat()
    ]


def latest_passes(lines: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each entry's latest line among ``lines`` (oldest first), by entry id (#200): the entry's own
    outcome and reason, with its pass's time, trigger and extension."""
    out: dict[str, dict[str, Any]] = {}
    for run in lines:
        for e in run.get("entries") or []:
            if isinstance(e, Mapping) and e.get("id"):
                out[str(e["id"])] = {
                    "at": run.get("at"),
                    "trigger": run.get("trigger"),
                    "outcome": e.get("outcome"),
                    "reason": e.get("reason"),
                    "extension": run.get("extension"),
                }
    return out


def pass_tally(lines_by_league: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any] | None:
    """The day's pass results over every league (#200): each entry counted once, by its latest
    line; ``claimed`` counts a live claim or add; ``pages`` every entry line logged (a page read,
    re-reads included); ``last`` the latest line that names an entry. None when none does."""
    latest: dict[str, dict[str, Any]] = {}
    pages, last = 0, None
    for lines in lines_by_league.values():
        for run in lines:
            named = [e for e in run.get("entries") or [] if isinstance(e, Mapping) and e.get("id")]
            at = _at(run.get("at"))
            if named and at is not None and (last is None or at > last):
                last = at
            pages += len(named)
        latest |= latest_passes(lines)
    if not latest:
        return None
    n = Counter(p["outcome"] for p in latest.values())
    return {
        "last": last.isoformat() if last is not None else None,
        "would_claim": n["would_claim"],
        "claimed": n["claimed"] + n["added"],
        "skipped": n["skipped"],
        "gone": n["gone"],
        "failed": n["failed"],
        "pages": pages,
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


def moves_digest_lines(
    data_dir: Path,
    modes: Mapping[str, Mapping[str, Any]],
    queue: Mapping[str, Any] | None,
    now: datetime,
) -> list[str]:
    """The digest's lines for the moves executor (#171): one summary over the armed leagues, the
    latest queue's entries (``queue``, ``season_queue``'s day) counted queued and struck and the
    entries the last day's passes reported counted by outcome, then a line per league only for
    what it skipped or failed, or placed with a reason (a claim whose answer was not read, #171
    PR 3). Leagues by id; no player, team or projection number."""
    armed = {
        lg: m["mode"] for lg, m in modes.items() if not m.get("private") and m["mode"] != "off"
    }
    if not armed:
        return []
    if stopped(data_dir):
        return ["- Moves executor: STOP is on (data/autopilot/STOP); nothing runs."]
    since = now - DIGEST_SPAN
    recent = {
        lg: [r for _, r in runs(data_dir, lg, MOVES) if (at := _at(r.get("at"))) and at >= since]
        for lg in armed
    }
    entries = [e for e in (queue or {}).get("entries") or [] if e.get("league") in armed]
    queued = sum(1 for e in entries if e.get("queued") and not e.get("struck"))
    struck = sum(1 for e in entries if e.get("struck"))
    checks = [e for rs in recent.values() for r in rs for e in r.get("entries") or []]
    count = Counter(e.get("outcome") for e in checks)
    by_mode = {m: [lg for lg, x in armed.items() if x == m] for m in ("dry_run", "live")}
    modes_text = ", ".join(
        f"{'dry run' if m == 'dry_run' else 'live'} in {len(lgs)}"
        for m, lgs in by_mode.items()
        if lgs
    )
    executed = count["would_claim"] + count["claimed"] + count["added"]
    if not by_mode["dry_run"]:
        verb = "claimed"
    else:
        verb = "would be claimed" if not by_mode["live"] else "claimed or would be claimed"
    day = (queue or {}).get("date")
    gone = f", {count['gone']} gone" if count["gone"] else ""
    lines = [
        f"- Moves executor ({modes_text}): "
        + (f"{_weekday(day)}'s queue " if day else "no queue; ")
        + (f"{queued} queued, {struck} struck; " if day else "")
        + f"{executed} {verb}, {count['skipped']} skipped, {count['failed']} failed{gone}."
    ]
    for lg in sorted(recent):
        parts = []
        for r in recent[lg]:
            bad = [
                e
                for e in r.get("entries") or []
                if e.get("outcome") in ("skipped", "failed")
                or (e.get("outcome") in ("claimed", "added") and e.get("reason"))
            ]
            if r.get("outcome") in ("skipped", "failed") and not bad:
                reason = f" ({r['reason']})" if r.get("reason") else ""
                parts.append(f"{_weekday(r['day'])} {r['outcome']}{reason}")
            for e in bad:
                reason = f" ({e['reason']})" if e.get("reason") else ""
                parts.append(f"{_weekday(r['day'])} {e['outcome']}{reason}")
        if parts:
            lines.append(f"- League {lg}: moves " + "; ".join(parts))
    return lines


def moves_digest_section(lines: Sequence[str]) -> str:
    """The digest's moves section; nothing without a line."""
    if not lines:
        return ""
    return "\n".join(["", "### Moves", "", *lines]) + "\n"


def _at(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
