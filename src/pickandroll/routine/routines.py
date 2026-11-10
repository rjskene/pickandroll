"""The six routines as step sequences, with their windows on the Central clock, and the
sign-in check. ``run`` is the entry: it refuses a start outside the routine's window (a timer
that fires late after a reboot must not run a morning pass at night), runs the sequence, and
always finishes the report."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

from .api import Unreachable
from .browser import NO_BROWSER
from .clock import before, seconds_until
from .report import Report
from .steps import (
    MOVES_WAIT_S,
    PRIVATE_LEAGUE,
    SOLVE_TIMEOUT_S,
    Abort,
    Context,
    MovesPlan,
    Opening,
    Stopped,
    alert_once,
    all_leagues,
    api_check,
    cancel_plan,
    claim_page_plan,
    digest,
    export_all,
    lineup_pages,
    lineup_plan,
    monday_pages,
    monday_step,
    moves_plan,
    open_page,
    pass_done,
    pass_open,
    pass_opening,
    plan_lines,
    post_digest,
    private_pages,
    public_leagues,
    queue_build,
    ready_browser,
    record_all,
    record_retry,
    refresh_all,
    resolve,
    resolve_comebacks,
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
    "signin": ("00:00", "23:59"),
    # The pre-tip pass's check (#355): every five minutes; the due route says when a slate's pass
    # starts (no full pass past the knob's latest start, 20:40 by default; a push alone later).
    "pretip": ("09:00", "21:00"),
}
#: The daily's refresh retry pass runs only before this (the Monday recorder reads Yahoo at 06:00).
DAILY_RETRY_BEFORE = "05:45"
#: The evening build's exports must be over by this, its refresh retry pass before the next.
EVENING_EXPORTS_BY = "21:15"
EVENING_RETRY_BEFORE = "21:40"
#: The evening pass opens nothing from this minute: the queue's day ends at 23:00 Central.
EVENING_HARD_STOP = "22:58"
#: The this-week export is not due on these weekdays (the week's last day, or its last two for
#: the evening): Basketball Monster's Remaining Week then lists only the players with a game.
DAILY_WEEK_THIS_NOT_DUE = (6,)
EVENING_WEEK_THIS_NOT_DUE = (5, 6)
MONDAY = 0
#: The pre-tip pass's exports (#355): the rest of the season and this week, under the daily's
#: not-due rule for this week.
PRETIP_KINDS = ("ros", "week_this")
#: The same-day lineup pass's fragment: the late pass's, run by the pre-tip pass while it is on
#: (#355 PR 3), so the extension, its trigger and its record are unchanged.
LATE_LINEUP_FRAGMENT = "pickandroll-lineup-late"
#: How long a run waits for the browser profile's lock (#355): the pre-tip pass a quarter hour,
#: then skips and stays due; every other run twenty minutes, then fails with the alert; the
#: evening pass never past its hard stop.
PRETIP_LOCK_WAIT_S = 15 * 60.0
LOCK_WAIT_S = 20 * 60.0


def lock_wait_s(name: str, when: datetime) -> float:
    """The lock wait of routine ``name`` started at ``when``."""
    if name == "pretip":
        return PRETIP_LOCK_WAIT_S
    if name == "evening-pass":
        return min(LOCK_WAIT_S, seconds_until(when, EVENING_HARD_STOP))
    return LOCK_WAIT_S


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
    leagues whose pages were opened. In a dry run, without a browser, or signed out, the plan
    is reported and nothing opens."""
    if not openings:
        ctx.report.skipped(name, "nothing to open")
        return []
    plan = plan_lines(openings)
    browser = ready_browser(ctx, name, site, f"{len(openings)} pages would open", plan=plan)
    if browser is None:
        return []
    pass_id = (
        pass_open(ctx, record[0], record[1], [o.league for o in _dedupe(openings)], record[2])
        if record
        else None
    )
    opened: list[str] = []
    unopened: list[str] = []
    failed: list[str] = []
    stayed: list[str] = []
    pages = 0
    for o in openings:
        if hard_stop and not before(ctx.now(), hard_stop):
            unopened.append(o.entry or o.league)
            continue
        pass_opening(ctx, pass_id, o.league, o.entry)
        landed = open_page(ctx, browser, o.url, o.wait_s)
        if landed is None:
            failed.append(o.entry or o.league)
            continue
        pages += 1
        if o.league not in opened:
            opened.append(o.league)
        if o.kind == "il" and o.entry and on_team_page(landed, o.url):
            # Still on the team page (a build before 0.9.1, or STOP): the extension did not go on
            # to the entry's add page, so the pass opens it itself, as the Desktop routine did
            # ("open that entry's add page yourself as for any other entry").
            ctx.notes.setdefault("il_stayed", []).append(o.entry)
            if not o.then:
                continue
            if hard_stop and not before(ctx.now(), hard_stop):
                unopened.append(o.entry)
                continue
            pass_opening(ctx, pass_id, o.league, o.entry)
            if open_page(ctx, browser, o.then, MOVES_WAIT_S) is None:
                failed.append(o.entry)
                continue
            pages += 1
            stayed.append(o.entry)
    summary = f"{pages} pages opened in {len(opened)} leagues"
    if stayed:
        summary += ", add pages opened by the pass after an IL stay: " + ", ".join(stayed[:15])
    if failed:
        summary += f", {len(failed)} failed to open: " + ", ".join(failed[:15])
    if unopened:
        shown = ", ".join(unopened[:15]) + (
            f" and {len(unopened) - 15} more" if len(unopened) > 15 else ""
        )
        summary += f", stopped at {hard_stop} with {len(unopened)} entries unopened: {shown}"
    pass_done(ctx, pass_id, summary)
    detail = summary + ("" if pass_id else "; no pass record" if record else "")
    status = ctx.report.failed if failed else ctx.report.ok
    status(
        name, detail, plan=plan, pass_id=pass_id, unopened=unopened, failed=failed, stayed=stayed
    )
    return opened


def on_team_page(landed: str, url: str) -> bool:
    """The tab is still on the team page it was sent to (the path, any query, any fragment)."""
    return landed.split("#")[0].startswith(url.split("#")[0].split("?")[0])


def _from(at: Any, since: datetime) -> bool:
    """A run's ``at`` is ``since`` or later; one whose time does not read is counted."""
    try:
        when = datetime.fromisoformat(str(at))
    except ValueError:
        return True
    return when.tzinfo is None or when >= since


def _dedupe(openings: Sequence[Opening]) -> list[Opening]:
    seen: set[str] = set()
    out = []
    for o in openings:
        if o.league not in seen:
            seen.add(o.league)
            out.append(o)
    return out


def pass_check(
    ctx: Context,
    leagues: Sequence[str],
    kinds: Sequence[str],
    trigger: str,
    since: datetime | None = None,
) -> None:
    """After a pass: each league's runs logged today (the lineup's ``today``, the moves' ``today``,
    ``il_today`` and ``start_active_today``), by trigger; with ``since``, only the runs from then
    (the pre-tip slates share the late trigger). A league opened with none is "no run logged";
    none anywhere is an alert."""
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
                if isinstance(r, dict)
                and r.get("trigger") == trigger
                and (since is None or _from(r.get("at"), since))
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
    export_all(ctx, DAILY_WEEK_THIS_NOT_DUE, None)
    private_pages(ctx)
    lineup_pages(ctx)
    rows = seasons(ctx)
    pub = public_leagues(rows)
    refresh_all(ctx, pub, DAILY_RETRY_BEFORE)
    solve_all(ctx, all_leagues(rows))
    passes_from = ctx.now()
    sa = start_active_plan(ctx, "pickandroll-start-active-daily")
    opened = browser_pass(ctx, "start_active", sa)
    lineups = lineup_plan(ctx, pub, tomorrow=True, fragment="pickandroll-lineup")
    opened_lineups = browser_pass(ctx, "lineup", lineups)
    touched = sorted(set(opened) | set(opened_lineups))
    if touched:
        pass_check(ctx, touched, ["lineup", "moves"], "routine")
    # A comeback's drop changed the roster after the solve (#360): those leagues are solved
    # again, and only those, before the queue is built from the solve.
    resolve_comebacks(ctx, touched, passes_from)
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
    pretip_on = _pretip_sets_lineups(ctx)
    if pretip_on:
        ctx.report.skipped("lineup", pretip_on)
        opened: list[str] = []
    else:
        lineups = lineup_plan(ctx, pub, tomorrow=False, fragment=LATE_LINEUP_FRAGMENT)
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
    export_all(ctx, EVENING_WEEK_THIS_NOT_DUE, EVENING_EXPORTS_BY)
    pub = public_leagues(seasons(ctx))
    refresh_all(ctx, pub, EVENING_RETRY_BEFORE)
    solve_all(ctx, pub)
    queue_build(ctx)


def evening_pass(ctx: Context, api: str) -> None:
    api_check(ctx)
    stop_check(ctx)
    pub = public_leagues(seasons(ctx))
    # The pending claims judged again at 21:00 and cancelled (#345 PR 2): first, before the claims,
    # so the waiver run never processes one; the 05:00 daily never cancels.
    browser_pass(ctx, "cancel", cancel_plan(ctx), hard_stop=EVENING_HARD_STOP)
    plan = moves_plan(ctx, pub, "pickandroll-moves-evening", "pickandroll-il-evening")
    _report_plan(ctx, plan)
    opened = browser_pass(
        ctx, "moves", plan.openings, ("moves", "routine_evening", plan.entries), EVENING_HARD_STOP
    )
    sa = start_active_plan(ctx, "pickandroll-start-active-evening", only=opened)
    browser_pass(ctx, "start_active", sa, hard_stop=EVENING_HARD_STOP)
    # The one read of a pending claim's page (#345 step 0): after the claims, clicking nothing.
    browser_pass(ctx, "claim_page", claim_page_plan(ctx), hard_stop=EVENING_HARD_STOP)
    pass_check(ctx, opened, ["moves"], "routine_evening")
    if ctx.now().weekday() == 6:
        _sunday_adds(ctx)


def _pretip_sets_lineups(ctx: Context) -> str | None:
    """Why the late pass leaves today's lineups to the pre-tip pass (#355 PR 3, the user's Q2 =
    C), or None: only while ``pretip.enabled`` is on and today has a slate. A due route that
    does not answer, the pass off, no schedule copy or no game: the late pass sets them as ever."""
    try:
        code, body, _ = ctx.get("/autopilot/pretip/due", 60)
    except Unreachable:
        return None
    if code != 200 or not isinstance(body, dict):
        return None
    if not (body.get("knobs") or {}).get("enabled") or not body.get("slates"):
        return None
    tips = ", ".join(
        f"{s.get('slate')} {str(s.get('tip'))[11:16]}"
        for s in body["slates"]
        if isinstance(s, dict)
    )
    return f"the pre-tip pass sets today's lineups (pretip.enabled; slates {tips})"


def pretip(ctx: Context, api: str) -> None:
    """The private league's pre-tip pass (#355): when the due route names a slate, Basketball
    Monster's rest-of-season and this-week exports, the league's pages, its solve, and its
    suggestions pushed to the user's private channel; each attempt logged on the day file; then
    the public leagues' same-day lineups, the late pass's lineup step at the slate's time (PR 3).
    Not due: refused, no browser and no report. A lock skip, a failed solve or a failed push
    leaves the slate due for the next check; an attempt that solved and failed only its push is
    pushed again alone. A slate whose window passed without it done fails the check once, with
    an alert: the daily's lineups and suggestions stand. Suggestions only in the private league:
    nothing is clicked there."""
    api_check(ctx)
    stop_check(ctx)
    code, due, _ = ctx.get("/autopilot/pretip/due", 60)
    if code != 200 or not isinstance(due, dict):
        ctx.report.failed("pretip_due", f"the due route answered {code}")
        return
    _pretip_missed(ctx, due.get("missed") or [])
    if not due.get("due") and ctx.report.find("pretip_missed") is not None:
        return
    if not due.get("due"):
        reason = f"not due: {due.get('reason') or 'nothing due'}"
        ctx.report.refused = reason
        raise Refused(reason)
    league, slate = str(due.get("league") or ""), str(due["slate"])
    if league != PRIVATE_LEAGUE:
        ctx.report.failed("pretip_due", f"the due names league {league}, not {PRIVATE_LEAGUE}")
        return
    started = ctx.now()
    ctx.report.ok(
        "pretip_due",
        f"{slate} slate, tip {str(due['tip'])[11:16]}"
        + (", the push alone (the solve is in)" if due.get("push_only") else ""),
        slate=slate,
        tip=due["tip"],
        push_only=bool(due.get("push_only")),
    )
    attempt: dict[str, Any] = {"slate": slate, "started_at": started.isoformat()}
    if due.get("push_only"):
        _pretip_push(ctx, league, due, attempt, {})
        return
    browser = ctx.browser
    if browser is not None and not ctx.dry_run and not browser.available():
        busy = getattr(browser, "busy", None)
        if busy:
            ctx.report.skipped("browser", f"{busy}: the {slate} slate stays due")
            _pretip_log(ctx, {**attempt, "outcome": "skipped", "reason": busy})
            return
    export_all(ctx, DAILY_WEEK_THIS_NOT_DUE, None, kinds=PRETIP_KINDS)
    private_pages(ctx)
    lineup_pages(ctx)
    exports = ctx.report.find("exports")
    lines = dict((exports.data.get("lines") if exports else None) or {})
    pulls = {
        k: "pulled" if k in ctx.report.exports else lines.get(k, "not made") for k in PRETIP_KINDS
    }
    codes = solve_all(ctx, [league])
    if not ctx.dry_run:
        if codes.get(league) != 200:
            why = f"the solve answered {codes.get(league)}"
            _pretip_log(ctx, {**attempt, "outcome": "failed", "reason": why, "pulls": pulls})
        else:
            _pretip_push(ctx, league, due, {**attempt, "solved_at": ctx.now().isoformat()}, pulls)
    if due.get("lineups_done"):
        # Once per slate (#355 PR 3): a retry, after a failed solve or push, never runs them again.
        at = str(due.get("lineups_at") or "")[11:16]
        ctx.report.skipped("lineup", f"the {slate} slate's lineups ran at {at}: not again")
        return
    if _pretip_lineups(ctx, started) and not ctx.dry_run:
        logged = ctx.notes.get("pretip_logged")
        if logged is not None:
            _pretip_log(ctx, {**logged, "lineups_at": ctx.now().isoformat()}, "lineups_logged")


def _pretip_missed(ctx: Context, missed: Sequence[Mapping[str, Any]]) -> None:
    """Each slate whose window passed without it done (PR 3): a failed step and an alert, and the
    slate logged missed so the next check says nothing more of it."""
    for m in missed:
        slate = str(m.get("slate"))
        line = (
            f"the {slate} slate (tip {str(m.get('tip'))[11:16]}) passed without its solve and push"
            f" ({m.get('attempts', 0)} attempts): today's lineups are the daily's, its suggestions"
            " the 05:00 ones"
        )
        ctx.report.failed("pretip_missed", line, slate=slate)
        alert_once(ctx, f"the pre-tip pass missed a slate: {line}")
        _pretip_log(
            ctx,
            {"slate": slate, "started_at": ctx.now().isoformat(), "outcome": "missed"},
        )


def _pretip_lineups(ctx: Context, since: datetime) -> bool:
    """The public leagues' same-day lineups inside the slate (#355 PR 3): the late pass's lineup
    step as it was (its pages, fragment, trigger and record, the extension's steps, which leave
    out a group whose tip-off passed as a skip with its reason), then the re-solve and the light
    of the leagues opened. The daily's set for the day stays the baseline. True when the step
    ran: a page opened, or none was due; False when the browser never opened one."""
    pub = public_leagues(seasons(ctx))
    lineups = lineup_plan(ctx, pub, tomorrow=False, fragment=LATE_LINEUP_FRAGMENT)
    opened = browser_pass(ctx, "lineup", lineups, ("lineup", "routine_late", None))
    resolve(ctx, opened)
    pass_check(ctx, opened, ["lineup"], "routine_late", since=since)
    status_check(ctx, opened)
    return not lineups or bool(opened)


def _pull_line(pulls: Mapping[str, str]) -> str:
    """This pass's own pulls in words: the inputs' line has the times of the files in force."""
    if not pulls:
        return ""
    words = {"ros": "projections", "week_this": "this week"}
    parts = [
        f"{words.get(k, k)} {v}"
        if v == "pulled"
        else f"{words.get(k, k)} not pulled ({v}): the last copy stands"
        for k, v in pulls.items()
    ]
    return "This pass: " + "; ".join(parts) + ".\n"


def _pretip_push(
    ctx: Context,
    league: str,
    due: Mapping[str, Any],
    attempt: dict[str, Any],
    pulls: Mapping[str, str],
) -> None:
    """The suggestions pushed (or, for a late slate whose set is the first's, not needed), and the
    attempt logged with what completed."""
    slate = str(due["slate"])
    code, body, _ = ctx.get(f"/seasons/{league}/pretip", SOLVE_TIMEOUT_S)
    if code != 200 or not isinstance(body, dict):
        why = f"the pre-tip route answered {code}"
        ctx.report.failed("push", why)
        _pretip_log(ctx, {**attempt, "outcome": "failed", "reason": why, "pulls": dict(pulls)})
        return
    if not attempt.get("solved_at"):
        attempt = {**attempt, "solved_at": ctx.now().isoformat()}
    moves = [{"add": m["add"], "drop": m.get("drop")} for m in body.get("moves") or []]
    attempt = {**attempt, "moves": moves, "pulls": dict(pulls)}
    first = due.get("first_moves")
    if slate == "late" and first is not None and _same(moves, first):
        ctx.report.ok("push", "the late slate's set is the first's: nothing pushed")
        _pretip_log(ctx, {**attempt, "outcome": "done", "unchanged": True})
        return
    if ctx.dry_run or not ctx.posting:
        why = "dry run" if ctx.dry_run else "posting off"
        ctx.report.skipped("push", f"{why}: nothing pushed; the slate stays due")
        _pretip_log(ctx, {**attempt, "outcome": "skipped", "reason": why})
        return
    if ctx.push is None:
        ctx.report.failed("push", "no push channel in this run: the slate stays due")
        _pretip_log(ctx, {**attempt, "outcome": "failed", "reason": "no push channel"})
        return
    title = f"pickandroll {league} pre-tip, {slate} slate (tip {str(due['tip'])[11:16]})"
    ok, detail = ctx.push(title, str(body.get("markdown") or "") + _pull_line(pulls))
    if not ok:
        ctx.report.failed("push", f"{detail}; the slate stays due")
        _pretip_log(ctx, {**attempt, "outcome": "failed", "reason": detail})
        return
    ctx.report.ok("push", f"{len(moves)} suggestions pushed: {detail}", moves=moves)
    _pretip_log(ctx, {**attempt, "outcome": "done", "pushed_at": ctx.now().isoformat()})


def _same(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> bool:
    """The same set of moves, in any order."""

    def key(ms: Sequence[Mapping[str, Any]]) -> list[tuple[int, int]]:
        return sorted((int(m["add"]), -1 if m.get("drop") is None else int(m["drop"])) for m in ms)

    return key(a) == key(b)


def _pretip_log(ctx: Context, attempt: Mapping[str, Any], name: str = "day_file") -> None:
    """The attempt on the day file (``POST /autopilot/pretip/runs``), kept in the notes for the
    lineup step to log again; never in a dry run."""
    if ctx.dry_run:
        return
    code, body, _ = ctx.post_json("/autopilot/pretip/runs", dict(attempt), 60)
    if code != 200:
        ctx.report.failed(name, f"the attempt was not logged: {code} {str(body)[:200]}")
        return
    ctx.notes["pretip_logged"] = dict(attempt)
    slate = (body.get("slates") or {}).get(attempt["slate"]) or {}
    if name != "day_file":
        ctx.report.ok(name, f"{attempt['slate']} slate's lineups logged")
        return
    done = bool(slate.get("done"))
    ctx.report.ok(
        "day_file", f"{attempt['slate']} slate {'done' if done else 'still due'}", done=done
    )


def monday(ctx: Context, api: str) -> None:
    api_check(ctx, start=True)
    lines = record_all(ctx, api)
    monday_pages(ctx, api, lines)
    record_retry(ctx, api, lines)
    scorecard(ctx)
    monday_step(ctx, api)
    pub = public_leagues(seasons(ctx))
    solve_all(ctx, pub)
    queue_build(ctx)


def signin(ctx: Context, api: str) -> None:
    """The sign-in check (the 04:50 timer of the operations PR): the browser up with the
    extension's worker, then each site's state in the profile. A site signed out is a failed
    step and an alert; the routines still run their API steps that day. No API needed."""
    if ctx.dry_run or ctx.browser is None:
        ctx.report.skipped("browser", "dry run: nothing launched" if ctx.dry_run else NO_BROWSER)
        return
    browser = ctx.browser
    if not browser.available():
        ctx.report.failed("browser", f"unavailable ({browser.reason})")
        alert_once(ctx, f"the browser could not start at the signin routine: {browser.reason}")
        return
    ctx.report.ok("browser", "launched, the extension's worker up")
    for site in ("bbm", "yahoo"):
        if browser.signed_in(site):
            ctx.report.ok(site, "signed in")
        else:
            ctx.report.failed(
                site, "signed out: the profile needs the user's sign-in (docs/OPS.md)"
            )
            alert_once(ctx, f"the browser profile is signed out of {site}")


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
    "signin": signin,
    "pretip": pretip,
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
