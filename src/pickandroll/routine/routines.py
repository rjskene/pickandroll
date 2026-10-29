"""The six routines as step sequences, with their windows on the Central clock. ``run`` is the
entry: it refuses a start outside the routine's window (a timer that fires late after a reboot
must not run a morning pass at night), runs the sequence, and always finishes the report."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from .browser import NO_BROWSER
from .clock import before
from .report import Report
from .steps import (
    Abort,
    Context,
    MovesPlan,
    Opening,
    Stopped,
    all_leagues,
    api_check,
    digest,
    lineup_plan,
    monday_step,
    moves_plan,
    pass_done,
    pass_open,
    pass_opening,
    plan_lines,
    post_digest,
    public_leagues,
    queue_build,
    record_all,
    record_retry,
    refresh_all,
    resolve,
    scorecard,
    seasons,
    solve_all,
    start_active_plan,
    status_check,
    stop_check,
)

#: When each routine may start (Central): the trigger minute and the latest start that still
#: lands inside its purpose. A timer that fires later (a reboot, a busy box) is refused.
WINDOWS: dict[str, tuple[str, str]] = {
    "daily": ("05:00", "06:20"),
    "morning": ("07:45", "14:30"),
    "late": ("15:00", "20:30"),
    "evening-build": ("21:00", "21:30"),
    "evening-pass": ("22:40", "22:58"),
    "monday": ("06:00", "12:00"),
}
#: The daily's refresh retry pass runs only before this (the Monday recorder reads Yahoo at 06:00).
DAILY_RETRY_BEFORE = "05:45"
#: The evening build's exports must be over by this, its refresh retry pass before the next.
EVENING_EXPORTS_BY = "21:15"
EVENING_RETRY_BEFORE = "21:40"
#: The evening pass opens nothing from this minute: the queue's day ends at 23:00 Central.
EVENING_HARD_STOP = "22:58"
MONDAY = 0


class Refused(RuntimeError):
    """Outside the routine's window: nothing ran."""


def check_window(ctx: Context, name: str, force: bool) -> None:
    start, end = WINDOWS[name]
    when = ctx.now()
    reason = None
    if name == "monday" and when.weekday() != MONDAY:
        reason = f"not a Monday ({when:%A})"
    elif before(when, start) or not before(when, end):
        reason = f"{when:%H:%M} is outside the {name} window {start}-{end} Central"
    if reason and not force:
        ctx.report.refused = reason
        raise Refused(reason)
    if reason:
        ctx.report.skipped("window", f"forced: {reason}")


# --------------------------------------------------------------------------- the browser passes
def browser_pass(
    ctx: Context,
    name: str,
    openings: Sequence[Opening],
    record: tuple[str, str, Sequence[str] | None] | None = None,
    hard_stop: str | None = None,
    site: str = "yahoo",
) -> list[str]:
    """Open each page in the routine's own tab and wait for the extension; with a pass record
    (kind, trigger, entries) the record is opened, told each opening and closed. Gives the
    leagues whose pages were opened. Without a browser, or signed out, the plan is reported
    and nothing opens."""
    if not openings:
        ctx.report.skipped(name, "nothing to open")
        return []
    plan = plan_lines(openings)
    browser = ctx.browser
    if browser is None or not browser.available():
        ctx.report.skipped(name, f"{NO_BROWSER}; {len(openings)} pages would open", plan=plan)
        return []
    if not browser.signed_in(site):
        ctx.report.failed(name, f"Chrome is not signed in to {site}: nothing opened", plan=plan)
        ctx.report.alert(f"the browser profile is signed out of {site}")
        return []
    pass_id = (
        pass_open(ctx, record[0], record[1], [o.league for o in _dedupe(openings)], record[2])
        if record
        else None
    )
    opened: list[str] = []
    unopened: list[str] = []
    for o in openings:
        if hard_stop and not before(ctx.now(), hard_stop):
            unopened.append(o.entry or o.league)
            continue
        pass_opening(ctx, pass_id, o.league, o.entry)
        landed = browser.open(o.url, o.wait_s)
        if (
            o.kind == "il"
            and o.entry
            and landed.split("#")[0].startswith(o.url.split("#")[0].split("?")[0])
        ):
            # Still on the team page (a build before 0.9.1, or STOP): the add page is opened as
            # for any other entry by the plan's next item carrying the same entry, if any.
            ctx.notes.setdefault("il_stayed", []).append(o.entry)
        if o.league not in opened:
            opened.append(o.league)
    summary = f"{len(openings) - len(unopened)} pages opened in {len(opened)} leagues"
    if unopened:
        shown = ", ".join(unopened[:15]) + (
            f" and {len(unopened) - 15} more" if len(unopened) > 15 else ""
        )
        summary += f", stopped at {hard_stop} with {len(unopened)} entries unopened: {shown}"
    pass_done(ctx, pass_id, summary)
    detail = summary + ("" if pass_id else "; no pass record" if record else "")
    ctx.report.ok(name, detail, plan=plan, pass_id=pass_id, unopened=unopened)
    return opened


def _dedupe(openings: Sequence[Opening]) -> list[Opening]:
    seen: set[str] = set()
    out = []
    for o in openings:
        if o.league not in seen:
            seen.add(o.league)
            out.append(o)
    return out


def pass_check(ctx: Context, leagues: Sequence[str], kinds: Sequence[str], trigger: str) -> None:
    """After a pass: each league's runs logged today (the lineup's ``today``, the moves' ``today``,
    ``il_today`` and ``start_active_today``), by trigger. A league opened with none is "no run
    logged"; none anywhere is an alert."""
    if not leagues:
        return
    lines = []
    logged_any = False
    for league in leagues:
        parts = []
        for kind in kinds:
            path = f"/seasons/{league}/autopilot" + ("/moves" if kind == "moves" else "")
            code, body, _ = ctx.get(path, 60)
            if code != 200 or not isinstance(body, dict):
                parts.append(f"{kind} route {code}")
                continue
            runs = [
                r
                for r in body.get("today") or []
                if isinstance(r, dict) and r.get("trigger") == trigger
            ]
            outcomes = ", ".join(
                f"{r.get('outcome')} ({r.get('reason')})"
                if r.get("reason")
                else str(r.get("outcome"))
                for r in runs
            )
            parts.append(f"{kind}: {len(runs)} run(s)" + (f": {outcomes}" if outcomes else ""))
            logged_any = logged_any or bool(runs)
            if kind == "moves":
                for extra in ("il_today", "start_active_today"):
                    rows = [r for r in body.get(extra) or [] if isinstance(r, dict)]
                    if rows:
                        parts.append(f"{extra}: " + ", ".join(str(r.get("outcome")) for r in rows))
        lines.append(f"{league}: " + "; ".join(parts))
    if not logged_any:
        ctx.report.failed("check", "no run logged in any league opened", lines=lines)
        ctx.report.alert(f"the {ctx.report.routine} pass opened pages but no run was logged")
    else:
        ctx.report.ok("check", f"{len(leagues)} leagues read", lines=lines)


# --------------------------------------------------------------------------- the six
def daily(ctx: Context, api: str) -> None:
    api_check(ctx, start=True)
    # The browser steps of the daily (the five exports, the private league's pages and its
    # lineup pages) land in PR 2; until then they are skipped and the marker says so.
    for name in ("exports", "private_pages", "lineup_pages"):
        ctx.report.skipped(name, NO_BROWSER)
    rows = seasons(ctx)
    pub = public_leagues(rows)
    refresh_all(ctx, pub, DAILY_RETRY_BEFORE)
    solve_all(ctx, all_leagues(rows))
    sa = start_active_plan(ctx, "pickandroll-start-active-daily")
    opened = browser_pass(ctx, "start_active", sa)
    lineups = lineup_plan(ctx, pub, tomorrow=True, fragment="pickandroll-lineup")
    opened_lineups = browser_pass(ctx, "lineup", lineups)
    if opened or opened_lineups:
        pass_check(ctx, sorted(set(opened) | set(opened_lineups)), ["lineup", "moves"], "routine")
    queue_build(ctx)
    post_digest(ctx, digest(ctx))


def morning(ctx: Context, api: str) -> None:
    api_check(ctx)
    stop_check(ctx)
    pub = public_leagues(seasons(ctx))
    plan = moves_plan(ctx, pub, "pickandroll-moves", "pickandroll-il")
    _report_plan(ctx, plan)
    opened = browser_pass(ctx, "moves", plan.openings, ("moves", "routine", plan.entries))
    sa = start_active_plan(ctx, "pickandroll-start-active", only=opened)
    browser_pass(ctx, "start_active", sa)
    pass_check(ctx, opened, ["moves"], "routine")


def late(ctx: Context, api: str) -> None:
    api_check(ctx)
    stop_check(ctx)
    pub = public_leagues(seasons(ctx))
    lineups = lineup_plan(ctx, pub, tomorrow=False, fragment="pickandroll-lineup-late")
    opened = browser_pass(ctx, "lineup", lineups, ("lineup", "routine_late", None))
    plan = moves_plan(ctx, pub, "pickandroll-moves-late", "pickandroll-il-late")
    _report_plan(ctx, plan)
    opened_moves = browser_pass(
        ctx, "moves", plan.openings, ("moves", "routine_late", plan.entries)
    )
    sa = start_active_plan(ctx, "pickandroll-start-active-late", only=opened_moves)
    browser_pass(ctx, "start_active", sa)
    touched = [k for k in pub if k in opened or k in opened_moves]
    resolve(ctx, touched)
    pass_check(ctx, touched, ["lineup", "moves"], "routine_late")
    status_check(ctx, touched)


def evening_build(ctx: Context, api: str) -> None:
    api_check(ctx)
    stop_check(ctx)
    ctx.report.skipped("exports", NO_BROWSER)
    pub = public_leagues(seasons(ctx))
    refresh_all(ctx, pub, EVENING_RETRY_BEFORE)
    solve_all(ctx, pub)
    queue_build(ctx)


def evening_pass(ctx: Context, api: str) -> None:
    api_check(ctx)
    stop_check(ctx)
    pub = public_leagues(seasons(ctx))
    plan = moves_plan(ctx, pub, "pickandroll-moves-evening", "pickandroll-il-evening")
    _report_plan(ctx, plan)
    opened = browser_pass(
        ctx, "moves", plan.openings, ("moves", "routine_evening", plan.entries), EVENING_HARD_STOP
    )
    sa = start_active_plan(ctx, "pickandroll-start-active-evening", only=opened)
    browser_pass(ctx, "start_active", sa, hard_stop=EVENING_HARD_STOP)
    pass_check(ctx, opened, ["moves"], "routine_evening")
    if ctx.now().weekday() == 6:
        _sunday_adds(ctx)


def monday(ctx: Context, api: str) -> None:
    api_check(ctx, start=True)
    lines = record_all(ctx, api)
    ctx.report.skipped("private_pages", NO_BROWSER)
    record_retry(ctx, api, lines)
    scorecard(ctx)
    monday_step(ctx, api)
    pub = public_leagues(seasons(ctx))
    solve_all(ctx, pub)
    queue_build(ctx)


def _report_plan(ctx: Context, plan: MovesPlan) -> None:
    reasons = "; ".join(f"{k}: {v}" for k, v in sorted(plan.reasons.items()))
    detail = f"{len(plan.entries)} entries due in {len(plan.leagues)} leagues"
    if reasons:
        detail += f"; skipped: {reasons}"
    ctx.report.ok(
        "due", detail[:600], entries=plan.entries, leagues=plan.leagues, reasons=plan.reasons
    )


def _sunday_adds(ctx: Context) -> None:
    """The Sunday report: each league's adds left in the new week (the queue payload's
    ``adds_left`` weeks starting Monday)."""
    code, body, _ = ctx.get("/autopilot/queue", 60)
    if code != 200 or not isinstance(body, dict):
        ctx.report.skipped("sunday", f"queue route answered {code}")
        return
    lines = []
    for row in body.get("leagues") or []:
        if not isinstance(row, dict):
            continue
        weeks = [w for w in row.get("adds_left") or [] if isinstance(w, dict)]
        nxt = next(
            (
                w
                for w in weeks
                if _weekday(w.get("start")) == MONDAY
                and str(w.get("start")) > str(ctx.now().date())
            ),
            None,
        )
        if nxt:
            lines.append(
                f"{row.get('league')}: {nxt.get('adds')} adds in the week of {nxt.get('start')}"
            )
    ctx.report.ok("sunday", f"{len(lines)} leagues' new-week adds read", lines=lines)


def _weekday(day: Any) -> int | None:
    try:
        return datetime.fromisoformat(str(day)).weekday()
    except ValueError:
        return None


ROUTINES: dict[str, Callable[[Context, str], None]] = {
    "daily": daily,
    "morning": morning,
    "late": late,
    "evening-build": evening_build,
    "evening-pass": evening_pass,
    "monday": monday,
}


def run(name: str, ctx: Context, api: str, force: bool = False) -> Report:
    """Run routine ``name``; the report is always finished, whatever ended the run."""
    report = ctx.report
    try:
        check_window(ctx, name, force)
        ROUTINES[name](ctx, api)
    except Refused:
        pass
    except Stopped:
        pass
    except Abort as exc:
        if not report.steps or report.steps[-1].status != "failed":
            report.failed("abort", str(exc)[:300])
    finally:
        report.finished = ctx.now()
        if ctx.browser is not None:
            with contextlib.suppress(Exception):  # closing is best effort
                ctx.browser.close()
    return report
