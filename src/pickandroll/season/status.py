"""The season dashboard's freshness light (#153): whether the daily updates landed, for the
title bar's dot and its details sheet.

Three sections: the Basketball Monster exports (shared by every league), each league's Yahoo
reads, and each league's recommendations against the inputs they rest on. Every row has a state
(green, amber or red) and a short reason; a section is its worst row, a league its worst section
(the exports included), the whole its worst league.

Pure: ``api.season_status`` reads the files, the refresh jobs and the decision logs these work
on, with the service's clock.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

GREEN, AMBER, RED = "green", "amber", "red"
STATES = (GREEN, AMBER, RED)
#: "Today" is the NBA's day, as everywhere in the season (``api.season_week.NBA_TZ``).
NBA_TZ = ZoneInfo("America/New_York")
#: The daily routine starts at 05:00 on the Mac's clock; its exports have landed by then.
DUE = time(6, 30)
#: A read older than this is red.
OLD = timedelta(days=1)

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


def day_of(at: datetime) -> date:
    return at.astimezone(NBA_TZ).date()


def due_at(today: date) -> datetime:
    """When today's exports are due."""
    return datetime.combine(today, DUE, tzinfo=NBA_TZ)


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at is not None else None


def _section(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"state": worst(r["state"] for r in rows), "rows": rows}


def _age(at: datetime | None, now: datetime) -> tuple[str, str]:
    """A read's state by its day: today green, within a day amber, older or never red."""
    if at is None:
        return RED, "never read"
    if day_of(at) == day_of(now):
        return GREEN, "today"
    if now - at <= OLD:
        return AMBER, "not today"
    return RED, "over a day old"


# --------------------------------------------------------------------------- the exports
def export_row(kind: str, file: str | None, as_of: datetime | None, now: datetime) -> dict:
    """One export: green from today; before today's due time yesterday's is amber; after it, or
    older, red."""
    today = day_of(now)
    if file is None or as_of is None:
        state, reason = RED, "missing"
    elif day_of(as_of) == today:
        state, reason = GREEN, "today"
    elif now < due_at(today) and day_of(as_of) == today - timedelta(days=1):
        state, reason = AMBER, "yesterday's, today's not due yet"
    else:
        state, reason = RED, "today's missing"
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
) -> dict[str, Any]:
    """A public league's last refresh, judged by the age of its newest read (``read_at``, the
    season's newest part): the service's job, when it has one (a restart forgets them), says a
    refresh is running, failed (red) or skipped pages (amber). The snapshot's time is shown."""
    status = (job or {}).get("status")
    if status == "running":
        state, reason = AMBER, "refreshing"
    elif status in ("failed", "private"):
        state, reason = RED, "refresh failed"
    else:
        state, reason = _age(read_at, now)
        if state == GREEN and (job or {}).get("warnings"):
            state, reason = AMBER, "pages skipped"
    return {
        "kind": "refresh",
        "status": status,
        "read_at": _iso(read_at),
        "finished_at": (job or {}).get("finished_at"),
        "error": (job or {}).get("error"),
        "warnings": dict((job or {}).get("warnings") or {}),
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
    """The private league's pages the extension reads, each by its newest read."""
    newest = newest_by_kind(fetched)
    rows = []
    for kind in PAGES:
        state, reason = _age(newest.get(kind), now)
        rows.append(
            {"kind": kind, "read_at": _iso(newest.get(kind)), "state": state, "reason": reason}
        )
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
    """A logged recommendation: red when an input it rests on is newer than it, amber when
    nothing was built today."""
    built = datetime.fromisoformat(entry["at"]) if entry else None
    newer = [k for k, at in inputs.items() if at is not None and (built is None or at > built)]
    if built is not None and newer:
        state, reason = RED, f"{newer[0]} newer"
    elif built is None or day_of(built) != day_of(now):
        state, reason = AMBER, "not built today"
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
) -> dict[str, Any]:
    """The moves set and the streaming plan (in the moves entry), the daily routine's solve,
    from its latest decision-log entry against the newest projection export and Yahoo read. The
    strategy run and the trade evaluation are made on request, so they carry no state: the
    strategy shows when it last ran and whether an input is newer since."""
    inputs = {"projection": projection_at, "Yahoo read": yahoo_at}
    moves = _latest(entries, "moves")
    plan = _built_row("plan", moves, inputs, now)
    if moves is not None and not moves.get("plan"):
        plan = {**plan, "state": None, "reason": "no plan for this league"}
    strategy = _built_row("strategy", _latest(entries, "strategy"), inputs, now)
    strategy = {
        **strategy,
        "state": None,
        "reason": "run on request" if strategy["built_at"] is None else strategy["reason"],
    }
    rows = [
        _built_row("moves", moves, inputs, now),
        plan,
        strategy,
        {
            "kind": "trades",
            "built_at": None,
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
    exports_section: dict[str, Any],
    leagues: list[dict[str, Any]],
    routine: Mapping[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    """Everything the light and the sheet show: the worst league's state over all."""
    return {
        "generated_at": now.isoformat(),
        "today": day_of(now).isoformat(),
        "due_at": due_at(day_of(now)).isoformat(),
        "state": worst([exports_section["state"], *(lg["state"] for lg in leagues)]),
        "routine": dict(routine) if routine else None,
        "exports": exports_section,
        "leagues": leagues,
    }
