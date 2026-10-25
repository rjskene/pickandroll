"""The season dashboard's freshness light (#153): whether the daily updates landed, for the
title bar's dot and its details sheet.

Four parts: the daily routine's run, the Basketball Monster exports (both shared by every
league), each league's Yahoo reads, and each league's recommendations against the inputs they
rest on. Every row has a state and a short reason: red when something failed, or is missing
once the routine's run is due (:data:`ROUTINE_DUE`); amber when something is stale or not due
yet; green otherwise. A section is its worst row, a league its worst section with the exports,
the whole its worst league with the exports and the run.

"Today" and the due time are the Mac's local clock, where the routine runs: every function takes
``now`` in that zone (``api.seasons.SeasonService.status`` converts the service's clock).

The run marker the routine writes as its last step, ``data/routine/daily.json``::

    {
      "started_at": "2026-10-23T05:00:12-05:00",
      "finished_at": "2026-10-23T05:52:40-05:00",
      "steps": {"<name>": {"status": "ok" | "failed" | "skipped", "detail": "<one line>"}},
      "exports": {"<kind>": "<file>"}
    }

with the step names the routine's own and the export kinds :data:`EXPORTS`'. A missing marker,
or one from another day, reads as no run recorded today.

Pure: ``api.season_status`` reads the files, the refresh jobs and the decision logs these work
on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time
from typing import Any

GREEN, AMBER, RED = "green", "amber", "red"
STATES = (GREEN, AMBER, RED)
#: The daily routine starts at 05:00 on the Mac's clock and has landed everything by then.
ROUTINE_DUE = time(6, 30)
EXPECTED = f"expected by {ROUTINE_DUE:%H:%M}"
STEP_STATUSES = ("ok", "failed", "skipped")

#: The five daily exports, by kind, with what each covers.
EXPORTS = {
    "ros": "rest of season",
    "week_this": "this week",
    "week_next": "next week",
    "actual_7d": "last 7 days",
    "actual_14d": "last 14 days",
}
#: The private league's pages the sheet lists, by their parts' key prefix.
PAGES = ("matchup", "lineup", "schedule", "transactions")
#: The exports a recommendation rests on (``api.seasons.SeasonService._moves_stamp``).
RESTS_ON = ("ros", "week_this", "week_next")


def worst(states: Iterable[str | None]) -> str:
    """The worst of ``states``, None left out; green when none is left."""
    ranked = [STATES.index(s) for s in states if s is not None]
    return STATES[max(ranked)] if ranked else GREEN


def day_of(at: datetime, now: datetime) -> date:
    """``at``'s day on ``now``'s clock."""
    return at.astimezone(now.tzinfo).date()


def due_at(now: datetime) -> datetime:
    """When today's run is due, on ``now``'s clock."""
    return datetime.combine(now.date(), ROUTINE_DUE, tzinfo=now.tzinfo)


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at is not None else None


def _when(x: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(x)) if x else None
    except ValueError:
        return None


def _section(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": worst(r["state"] for r in rows), "rows": rows}


def _today(at: datetime | None, now: datetime, missing: str) -> tuple[str, str]:
    """Something the routine makes every day: green from today; before the due time amber,
    expected; after it red, ``missing``."""
    if at is not None and day_of(at, now) == now.date():
        return GREEN, "today"
    if now < due_at(now):
        return AMBER, EXPECTED
    return RED, missing


# --------------------------------------------------------------------------- the routine
def routine_row(marker: Mapping[str, Any] | None, now: datetime) -> dict[str, Any]:
    """The routine's run today, from its marker: a failed step is red and a skipped one amber;
    no run recorded today, or one not finished, is amber before the due time and red after."""
    started = _when((marker or {}).get("started_at"))
    finished = _when((marker or {}).get("finished_at"))
    steps = (marker or {}).get("steps") or {}
    steps = steps if isinstance(steps, Mapping) else {}
    status = {k: (v or {}).get("status") for k, v in steps.items() if isinstance(v, Mapping)}
    if started is None or day_of(started, now) != now.date():
        state = AMBER if now < due_at(now) else RED
        reason = "no run recorded today" + (f", {EXPECTED}" if state == AMBER else "")
    elif failed := [k for k, s in status.items() if s == "failed"]:
        state, reason = RED, f"{', '.join(failed)} failed"
    elif finished is None:
        state, reason = (AMBER, "running") if now < due_at(now) else (RED, "not finished")
    elif skipped := [k for k, s in status.items() if s == "skipped"]:
        state, reason = AMBER, f"{', '.join(skipped)} skipped"
    else:
        state, reason = GREEN, "ran today"
    return {
        "kind": "routine",
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "steps": {
            k: {"status": v.get("status"), "detail": v.get("detail")}
            for k, v in steps.items()
            if isinstance(v, Mapping)
        },
        "state": state,
        "reason": reason,
    }


# --------------------------------------------------------------------------- the exports
#: The export the routine skips on the week's last day, and the light's words for it (#181):
#: on a Sunday Basketball Monster's Remaining Week covers that one day, a file nothing reads.
NOT_DUE_ON_SUNDAY = "week_this"
NOT_DUE = "not due on the week's last day"


def export_row(kind: str, file: str | None, as_of: datetime | None, now: datetime) -> dict:
    """One export: green from today; amber before the due time; red once it is due. The
    this-week export is not due on a Sunday on the light's clock (#181): green with
    :data:`NOT_DUE` unless today's file is there, whatever the file's own dates say."""
    state, reason = _today(as_of, now, "today's missing" if file else "missing")
    if kind == NOT_DUE_ON_SUNDAY and state != GREEN and now.weekday() == 6:
        state, reason = GREEN, NOT_DUE
    return {
        "kind": kind,
        "label": EXPORTS[kind],
        "file": file,
        "as_of": _iso(as_of),
        "state": state,
        "reason": reason,
    }


def exports(found: Mapping[str, tuple[str, datetime] | None], now: datetime) -> dict[str, Any]:
    """The five exports, each the newest file of its kind with its as-of (None: no file)."""
    rows = []
    for kind in EXPORTS:
        file, as_of = found.get(kind) or (None, None)
        rows.append(export_row(kind, file, as_of, now))
    return _section(rows)


# --------------------------------------------------------------------------- Yahoo
def refresh_row(
    job: Mapping[str, Any] | None,
    read_at: datetime | None,
    snapshot_at: datetime | None,
    now: datetime,
    live: bool = True,
) -> dict[str, Any]:
    """A public league's last refresh, judged by its newest read (``read_at``, the season's
    newest part) as the routine's other daily work. Its last job, the service's own (``live``)
    or else the last its log has, says a refresh failed (red), never finished (red: a logged
    start with no end, the service stopped during it), is running or skipped pages (amber).
    The job's times, step and error and the snapshot's time are shown."""
    job = job or {}
    status = job.get("status")
    if status in ("failed", "private"):
        state, reason = RED, "refresh failed"
    elif status == "running" and not live:
        state, reason = RED, "refresh never finished"
    elif status == "running":
        state, reason = AMBER, "refreshing"
    else:
        state, reason = _today(read_at, now, "not refreshed today")
        if state == GREEN and job.get("warnings"):
            state, reason = AMBER, "pages skipped"
    return {
        "kind": "refresh",
        "status": status,
        "read_at": _iso(read_at),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "step": job.get("step"),
        "done": job.get("done"),
        "total": job.get("total"),
        "error": job.get("error"),
        "warnings": dict(job.get("warnings") or {}),
        "logged": bool(job) and not live,
        "snapshot_at": _iso(snapshot_at),
        "state": state,
        "reason": reason,
    }


def newest_by_kind(fetched: Mapping[str, datetime]) -> dict[str, datetime]:
    """The newest read of each part kind (its key before the first ``/``)."""
    out: dict[str, datetime] = {}
    for key, at in fetched.items():
        kind = key.split("/", 1)[0]
        if kind not in out or at > out[kind]:
            out[kind] = at
    return out


def pages(fetched: Mapping[str, datetime], now: datetime) -> list[dict[str, Any]]:
    """The private league's pages the routine opens for the extension, each by its newest
    read."""
    newest = newest_by_kind(fetched)
    rows = []
    for kind in PAGES:
        at = newest.get(kind)
        state, reason = _today(at, now, "not read today" if at else "never read")
        rows.append({"kind": kind, "read_at": _iso(at), "state": state, "reason": reason})
    return rows


# --------------------------------------------------------------------------- recommendations
def _latest(entries: Sequence[Mapping[str, Any]], source: str) -> Mapping[str, Any] | None:
    found = [e for e in entries if e.get("source") == source and e.get("at")]
    return max(found, key=lambda e: e["at"], default=None)


def _built_row(
    kind: str,
    entry: Mapping[str, Any] | None,
    inputs: Mapping[str, datetime | None],
    now: datetime,
) -> dict[str, Any]:
    """A logged recommendation: amber when an input it rests on is newer (the view solves again
    when it opens), or before the due time with no solve today; red with no solve today once
    the run is due."""
    built = _when(entry["at"]) if entry else None
    newer = [k for k, at in inputs.items() if at is not None and built is not None and at > built]
    if built is None or day_of(built, now) != now.date():
        state, reason = _today(None, now, "not solved today")
    elif newer:
        state, reason = AMBER, f"{newer[0]} newer; re-solved on open"
    else:
        state, reason = GREEN, "on today's inputs"
    system = (entry or {}).get("system") or {}
    return {
        "kind": kind,
        "built_at": _iso(built),
        "system": system.get("key"),
        "projection_file": system.get("file"),
        "state": state,
        "reason": reason,
    }


def recommendations(
    entries: Sequence[Mapping[str, Any]],
    projection_at: datetime | None,
    yahoo_at: datetime | None,
    now: datetime,
    yahoo: str = "Yahoo",
) -> dict[str, Any]:
    """The moves set and the streaming plan (in the moves entry), the daily routine's solve,
    from its latest decision-log entry against the newest projection export and Yahoo read
    (named ``yahoo``: the private league's newest page, "lineup read newer"). The strategy run
    and the trade evaluation are made on request, so they carry no state: the strategy shows
    when it last ran and whether an input is newer since, the trades the inputs' own times."""
    inputs = {"projection": projection_at, f"{yahoo} read": yahoo_at}
    moves = _latest(entries, "moves")
    plan = _built_row("plan", moves, inputs, now)
    if moves is not None and not moves.get("plan"):
        plan = {**plan, "state": None, "reason": "no plan for this league"}
    strategy = _built_row("strategy", _latest(entries, "strategy"), inputs, now)
    ran = strategy["built_at"] is not None
    strategy = {
        **strategy,
        "state": None,
        "reason": strategy["reason"] if ran else "run on request",
    }
    rows = [
        _built_row("moves", moves, inputs, now),
        plan,
        strategy,
        {
            "kind": "trades",
            "built_at": None,
            "inputs": {k: _iso(v) for k, v in inputs.items()},
            "state": None,
            "reason": "evaluated on request, from the inputs above",
        },
    ]
    return {
        "state": worst(r["state"] for r in rows),
        "rows": rows,
        "inputs": {k: _iso(v) for k, v in inputs.items()},
    }


# --------------------------------------------------------------------------- the whole
def league(
    league_id: str,
    name: str | None,
    public: bool,
    yahoo_rows: list[dict[str, Any]],
    recs: dict[str, Any],
    exports_state: str,
) -> dict[str, Any]:
    yahoo = _section(yahoo_rows)
    return {
        "league": league_id,
        "name": name,
        "public": public,
        "state": worst([exports_state, yahoo["state"], recs["state"]]),
        "yahoo": yahoo,
        "recommendations": recs,
    }


def payload(
    routine: dict[str, Any],
    exports_section: dict[str, Any],
    leagues: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    """Everything the light and the sheet show: the worst of the run, the exports and every
    league over all."""
    states = [routine["state"], exports_section["state"], *(lg["state"] for lg in leagues)]
    return {
        "generated_at": now.isoformat(),
        "today": now.date().isoformat(),
        "due_at": due_at(now).isoformat(),
        "state": worst(states),
        "routine": routine,
        "exports": exports_section,
        "leagues": leagues,
    }
