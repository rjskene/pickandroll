"""The steps the routines are made of, over the API, the two scripts and the GitHub poster.
Each takes the ``Context`` and records one ``Step`` on its report; a step that must end the run
raises ``Stopped`` (STOP is set) or ``Abort`` (the API is down)."""

from __future__ import annotations

import math
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .api import Call, Unreachable
from .browser import Browser
from .clock import before, seconds_until
from .report import Report

REPO = "rjskene/pickandroll"
#: The tracker issues the routines post on: the breakout digest (#99) and AUTOPILOT (#127).
DIGEST_ISSUE = 99
AUTOPILOT_ISSUE = 127
#: Free leagues the user does not play; skipped wherever they appear.
IGNORED_LEAGUES = frozenset({"216752", "227293"})
#: The private league: fed by the extension, never refreshed, never in a pass.
PRIVATE_LEAGUE = "31822"
YAHOO = "https://basketball.fantasysports.yahoo.com"
#: Between one league's refresh and the next: twelve back to back trip Yahoo's limit (#180).
REFRESH_PACE_S = 60.0
#: The shortest cool-off before the retry pass after a 503.
RETRY_FLOOR_S = 600.0
REFRESH_TIMEOUT_S = 600.0
SOLVE_TIMEOUT_S = 300.0

RunScript = Callable[[Sequence[str]], tuple[int, str, str]]
Poster = Callable[[int, Path], tuple[int, str]]


class Stopped(RuntimeError):
    """The STOP file is set: the routine does nothing further."""


class Abort(RuntimeError):
    """The routine cannot go on (the API is down)."""


@dataclass
class Context:
    call: Call
    now: Callable[[], datetime]
    sleep: Callable[[float], None]
    report: Report
    data_dir: Path
    #: ``scripts/<name>.py <args...>`` with the checkout's interpreter: (code, stdout, stderr).
    run_script: RunScript
    #: ``gh issue comment <issue> --body-file <path>``: (code, stdout).
    post: Poster
    browser: Browser | None = None
    #: Reads only: the steps that write (refresh, solve, build, record, post, pass record) are
    #: reported as skipped. The plans are still computed from the live answers.
    dry_run: bool = False
    #: GitHub posts allowed (the soak runs with them off).
    posting: bool = True
    notes: dict[str, Any] = field(default_factory=dict)

    def get(self, path: str, timeout: float = 60.0) -> tuple[int, Any, dict[str, str]]:
        return self.call("GET", path, None, timeout)

    def post_json(
        self, path: str, body: Any = None, timeout: float = 60.0
    ) -> tuple[int, Any, dict[str, str]]:
        return self.call("POST", path, body, timeout)


# --------------------------------------------------------------------------- the API and STOP
def api_check(ctx: Context, start: bool = False) -> None:
    """``GET /seasons`` must answer 200. With ``start`` (the daily and the Monday recorder),
    a silent API is started once through the launch entries and asked again after ten
    seconds; otherwise, or if that fails, the routine aborts and the master is alerted."""
    code = _seasons_code(ctx)
    if code == 200:
        ctx.report.ok("api", "200 on first check, not restarted")
        return
    ctx.report.unreachable = isinstance(code, str)
    if start and not ctx.dry_run:
        rc, out, err = ctx.run_script(["draft_day.py", "servers", "--start"])
        ctx.sleep(10)
        code = _seasons_code(ctx)
        if code == 200:
            ctx.report.ok("api", f"started through launch.json (servers --start exit {rc})")
            ctx.report.unreachable = False
            return
        ctx.report.unreachable = isinstance(code, str)
        detail = f"down ({code}) and servers --start (exit {rc}) did not bring it up: {err or out}"
    else:
        detail = f"down ({code}); the routine never starts or restarts a server"
    ctx.report.failed("api", detail[:300])
    ctx.report.alert(f"the API was down at the {ctx.report.routine} routine: {detail[:200]}")
    raise Abort(detail)


def _seasons_code(ctx: Context) -> int | str:
    try:
        code, _, _ = ctx.get("/seasons", timeout=20)
        return code
    except Unreachable as exc:
        return f"unreachable: {exc}"


def stop_check(ctx: Context) -> None:
    if (ctx.data_dir / "autopilot" / "STOP").exists():
        ctx.report.stopped = True
        ctx.report.skipped("stop", "data/autopilot/STOP exists: nothing done")
        raise Stopped("STOP")


# --------------------------------------------------------------------------- the leagues
def seasons(ctx: Context) -> list[dict[str, Any]]:
    code, body, _ = ctx.get("/seasons", timeout=60)
    if code != 200 or not isinstance(body, list):
        raise Abort(f"GET /seasons answered {code}")
    return [r for r in body if isinstance(r, dict) and r.get("league")]


def public_leagues(rows: Iterable[dict[str, Any]]) -> list[str]:
    """The public leagues in the API's order: no error, not private, not ignored."""
    out = []
    for r in rows:
        league = str(r["league"])
        if r.get("error") or league in IGNORED_LEAGUES or league == PRIVATE_LEAGUE:
            continue
        if r.get("public") is False:
            continue
        out.append(league)
    return out


def all_leagues(rows: Iterable[dict[str, Any]]) -> list[str]:
    """Every league with a season read, the private one included (its solve belongs to the
    daily once its pages landed)."""
    return [
        str(r["league"])
        for r in rows
        if not r.get("error") and str(r["league"]) not in IGNORED_LEAGUES
    ]


# --------------------------------------------------------------------------- refresh and solve
def refresh_all(
    ctx: Context, leagues: Sequence[str], retry_before: str, name: str = "refresh"
) -> None:
    """One paced refresh per public league, then one retry pass for the leagues Yahoo's limit
    stopped (503, after the longest ``Retry-After`` and at least ten minutes) while the clock is
    before ``retry_before``; a 502 is retried once in the same pass. A league that fails twice is
    reported failed with its data a day old."""
    if ctx.dry_run:
        ctx.report.skipped(
            name, f"dry run: would refresh {len(leagues)} leagues, {REFRESH_PACE_S:.0f} s apart"
        )
        return
    codes: dict[str, int] = {}
    limited: dict[str, float] = {}
    for i, league in enumerate(leagues):
        if i:
            ctx.sleep(REFRESH_PACE_S)
        code, retry = _refresh(ctx, league)
        if code == 502:
            code, retry = _refresh(ctx, league)
        codes[league] = code
        if code == 503:
            limited[league] = retry
    if limited:
        wait = max(RETRY_FLOOR_S, max(limited.values()))
        if before(ctx.now(), retry_before) and seconds_until(ctx.now(), retry_before) > wait:
            ctx.sleep(wait)
            for i, league in enumerate(limited):
                if i:
                    ctx.sleep(REFRESH_PACE_S)
                codes[league], _ = _refresh(ctx, league)
        else:
            ctx.notes["refresh_retry"] = f"no retry pass: past {retry_before} or too close to it"
    failed = sorted(k for k, v in codes.items() if not 200 <= v < 300)
    done = [k for k in leagues if k not in failed]
    detail = f"{len(done)} leagues refreshed"
    if failed:
        detail += f"; failed, data a day old: {', '.join(f'{k} ({codes[k]})' for k in failed)}"
        if ctx.notes.get("refresh_retry"):
            detail += f" ({ctx.notes['refresh_retry']})"
        ctx.report.failed(name, detail, codes=codes)
    else:
        ctx.report.ok(name, detail, codes=codes)


def _refresh(ctx: Context, league: str) -> tuple[int, float]:
    try:
        code, _, headers = ctx.post_json(
            f"/seasons/{league}/refresh?wait=true", None, REFRESH_TIMEOUT_S
        )
    except Unreachable:
        return 599, 0.0
    retry = 0.0
    if code == 503:
        try:
            retry = float(headers.get("retry-after", "0"))
        except ValueError:
            retry = 0.0
    return code, retry


def solve_all(
    ctx: Context, leagues: Sequence[str], name: str = "solve", timeout: float = SOLVE_TIMEOUT_S
) -> dict[str, int]:
    """``GET /seasons/<id>/moves`` per league, one at a time: each writes the day's decision-log
    entry (#125); nothing is posted or changed by it."""
    if ctx.dry_run:
        ctx.report.skipped(name, f"dry run: would solve {len(leagues)} leagues")
        return {}
    codes: dict[str, int] = {}
    for league in leagues:
        try:
            code, _, _ = ctx.get(f"/seasons/{league}/moves", timeout)
        except Unreachable:
            code = 599
        codes[league] = code
    failed = [k for k, v in codes.items() if not 200 <= v < 300]
    detail = f"{len(leagues) - len(failed)} leagues solved"
    if failed:
        detail += f"; failed: {', '.join(f'{k} ({codes[k]})' for k in failed)}"
        ctx.report.failed(name, detail, codes=codes)
    else:
        ctx.report.ok(name, detail + ", all 200", codes=codes)
    return codes


def queue_build(ctx: Context, name: str = "queue_build") -> dict[str, Any] | None:
    """``POST /autopilot/queue/build``: the day's queue from the decision log; solves nothing,
    clicks nothing."""
    if ctx.dry_run:
        ctx.report.skipped(name, "dry run: would build the queue")
        return None
    try:
        code, body, _ = ctx.post_json("/autopilot/queue/build", None, 300)
    except Unreachable as exc:
        ctx.report.failed(name, f"unreachable: {exc}")
        return None
    if code != 200 or not isinstance(body, dict):
        ctx.report.failed(name, f"answered {code}")
        return None
    rows = body.get("leagues") or []
    entries = body.get("entries") or []
    by_status: dict[str, list[str]] = {}
    for r in rows:
        by_status.setdefault(str(r.get("status")), []).append(str(r.get("league")))
    queued = sum(1 for e in entries if e.get("queued"))
    superseded = sum(1 for e in entries if e.get("superseded_at"))
    detail = f"{queued} entries queued" + (f", {superseded} superseded" if superseded else "")
    detail += "; leagues " + ", ".join(f"{k} {len(v)}" for k, v in sorted(by_status.items()))
    ctx.report.ok(name, detail, leagues=by_status, queued=queued, superseded=superseded)
    return body


def resolve(ctx: Context, leagues: Sequence[str]) -> None:
    """The late pass's 4c: one re-solve per league whose page was opened, so the recommendations
    post-date the afternoon read; a failure is noted, never retried."""
    if not leagues:
        ctx.report.skipped("resolve", "no page opened: nothing to re-solve")
        return
    solve_all(ctx, leagues, name="resolve", timeout=120)


def status_check(ctx: Context, leagues: Sequence[str]) -> None:
    """``GET /seasons/status``: each re-solved league's moves row must be built after its last
    Yahoo read, else it is "still behind the Yahoo read"."""
    if not leagues:
        return
    code, body, _ = ctx.get("/seasons/status", 120)
    if code != 200 or not isinstance(body, dict):
        ctx.report.failed("status", f"answered {code}")
        return
    behind = behind_the_read(body, leagues)
    if behind:
        ctx.report.failed("status", "still behind the Yahoo read: " + ", ".join(behind))
    else:
        ctx.report.ok("status", f"{len(leagues)} leagues re-solved after their reads")


def behind_the_read(status: dict[str, Any], leagues: Sequence[str]) -> list[str]:
    """The leagues whose ``moves`` recommendation row was built before their newest Yahoo read.
    Pure, over the status payload."""
    rows = {str(r.get("league")): r for r in status.get("leagues") or [] if isinstance(r, dict)}
    behind = []
    for league in leagues:
        row = rows.get(league)
        if not row:
            behind.append(f"{league} (no status row)")
            continue
        reads = [
            _when(x.get("read_at"))
            for x in (row.get("yahoo") or {}).get("rows") or []
            if isinstance(x, dict)
        ]
        recs = [
            _when(x.get("built_at"))
            for x in (row.get("recommendations") or {}).get("rows") or []
            if isinstance(x, dict) and x.get("kind") == "moves"
        ]
        newest_read = max((r for r in reads if r), default=None)
        built = max((r for r in recs if r), default=None)
        if built is None or (newest_read is not None and built <= newest_read):
            behind.append(league)
    return behind


def _when(x: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(x)) if x else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- the plans
@dataclass
class Opening:
    """One page a pass opens: the league, the fragment's kind, the URL and the wait after it."""

    league: str
    kind: str
    url: str
    wait_s: float
    entry: str | None = None
    date: str | None = None


def league_page_ok(league: str, page: Any) -> bool:
    return isinstance(page, str) and page.startswith(f"{YAHOO}/nba/{league}/")


def add_page_ok(league: str, page: Any) -> bool:
    return isinstance(page, str) and page.startswith(f"/nba/{league}/addplayer?apid=")


def lineup_plan(
    ctx: Context, leagues: Sequence[str], tomorrow: bool, fragment: str
) -> list[Opening]:
    """The lineup executor's pages: each league's own team page for today (and tomorrow in the
    daily), from ``lineup/steps``, when the mode is not off and the day is open."""
    out: list[Opening] = []
    skipped: list[str] = []
    for league in leagues:
        code, body, _ = ctx.get(f"/seasons/{league}/lineup/steps", 120)
        if code != 200 or not isinstance(body, dict):
            skipped.append(f"{league} ({code})")
            continue
        days = [body]
        if tomorrow and body.get("date"):
            day = datetime.fromisoformat(str(body["date"])).date() + timedelta(days=1)
            code2, body2, _ = ctx.get(f"/seasons/{league}/lineup/steps?date={day}", 120)
            if code2 == 200 and isinstance(body2, dict):
                days.append(body2)
        for d in days:
            if d.get("mode") == "off" or not d.get("open"):
                continue
            page = d.get("page")
            if not league_page_ok(league, page):
                skipped.append(f"{league}: page not the league's own ({page!r})")
                continue
            out.append(Opening(league, "lineup", f"{page}#{fragment}", 8.0, date=d.get("date")))
    ctx.notes["lineup_skipped"] = skipped
    return out


def start_active_plan(
    ctx: Context, fragment: str, only: Sequence[str] | None = None
) -> list[Opening]:
    """``GET /autopilot/start-active/due``: the leagues that need Yahoo's Start Active Players
    (``need`` true, no error), their own team page with the pass's fragment, thirty seconds each.
    ``only`` limits it to the leagues a pass opened."""
    code, body, _ = ctx.get("/autopilot/start-active/due", 120)
    if code != 200 or not isinstance(body, dict):
        ctx.notes["start_active"] = f"due route answered {code}"
        return []
    if body.get("stop"):
        ctx.notes["start_active"] = "STOP: nothing due"
        return []
    out = []
    for row in body.get("leagues") or []:
        league = str(row.get("league"))
        if only is not None and league not in only:
            continue
        if not row.get("need") or row.get("error"):
            continue
        page = row.get("page")
        if not league_page_ok(league, page):
            ctx.notes.setdefault("start_active_skipped", []).append(league)
            continue
        reasons = ",".join(str(r) for r in row.get("reasons") or [])
        out.append(Opening(league, f"start_active:{reasons}", f"{page}#{fragment}", 30.0))
    return out


@dataclass
class MovesPlan:
    openings: list[Opening]
    #: The due entries' ids, in opening order (for the pass record).
    entries: list[str]
    leagues: list[str]
    reasons: dict[str, str]


def moves_plan(ctx: Context, leagues: Sequence[str], fragment: str, il_fragment: str) -> MovesPlan:
    """``GET /seasons/<id>/autopilot/moves/due`` per league: the IL moves first (each item's
    team page, thirty seconds), then the other due entries' add pages (twelve seconds), the
    page paths checked against the league. Off, STOP or nothing due is a reason, not a page."""
    openings: list[Opening] = []
    entries: list[str] = []
    opened: list[str] = []
    reasons: dict[str, str] = {}
    for league in leagues:
        code, body, _ = ctx.get(f"/seasons/{league}/autopilot/moves/due", 120)
        if code != 200 or not isinstance(body, dict):
            reasons[league] = f"due route answered {code}"
            continue
        if body.get("mode") == "off" or body.get("stop") or not body.get("entries"):
            reasons[league] = str(body.get("reason") or body.get("mode") or "nothing due")
            continue
        il_first = [i for i in body.get("il_first") or [] if isinstance(i, dict)]
        il_entries = {str(i.get("entry")) for i in il_first}
        league_openings: list[Opening] = []
        for item in il_first:
            page = item.get("page")
            if not league_page_ok(league, page):
                reasons[f"{league}:{item.get('entry')}"] = (
                    f"IL page not the league's own ({page!r})"
                )
                continue
            league_openings.append(
                Opening(
                    league,
                    "il",
                    f"{page}#{il_fragment}",
                    30.0,
                    str(item.get("entry")),
                    item.get("date"),
                )
            )
        for e in body["entries"]:
            if not isinstance(e, dict):
                continue
            eid = str(e.get("id"))
            if eid in il_entries:
                continue
            page = e.get("page")
            if not add_page_ok(league, page):
                reasons[f"{league}:{eid}"] = f"add page not the league's ({page!r})"
                continue
            league_openings.append(Opening(league, "moves", f"{YAHOO}{page}#{fragment}", 12.0, eid))
        if league_openings:
            opened.append(league)
            openings.extend(league_openings)
            entries.extend(o.entry for o in league_openings if o.entry)
        else:
            reasons[league] = "no page passed the checks"
    return MovesPlan(openings, entries, opened, reasons)


def plan_lines(openings: Sequence[Opening]) -> list[str]:
    return [f"{o.league} {o.kind} {o.url} ({o.wait_s:.0f} s)" for o in openings]


# --------------------------------------------------------------------------- the pass record
def pass_open(
    ctx: Context, kind: str, trigger: str, leagues: Sequence[str], entries: Sequence[str] | None
) -> str | None:
    """Open the pass (#201); None when refused (an older API, or one still open: 409), the pages
    are opened all the same."""
    if ctx.dry_run or not leagues:
        return None
    body: dict[str, Any] = {"kind": kind, "trigger": trigger, "leagues": list(leagues)}
    if entries is not None:
        body["entries"] = list(entries)
    try:
        code, answer, _ = ctx.post_json("/autopilot/passes", body, 30)
    except Unreachable:
        return None
    if code == 200 and isinstance(answer, dict) and answer.get("id"):
        return str(answer["id"])
    ctx.notes[f"pass_{kind}"] = f"record not opened ({code})"
    return None


def pass_opening(ctx: Context, pass_id: str | None, league: str, entry: str | None = None) -> None:
    if not pass_id:
        return
    body: dict[str, Any] = {"league": league}
    if entry:
        body["entry"] = entry
    try:
        code, _, _ = ctx.post_json(f"/autopilot/passes/{pass_id}/opening", body, 30)
    except Unreachable:
        return
    if code != 200:
        ctx.notes.setdefault("pass_opening_codes", []).append(f"{league}:{code}")


def pass_done(ctx: Context, pass_id: str | None, summary: str) -> None:
    if not pass_id:
        return
    try:
        ctx.post_json(f"/autopilot/passes/{pass_id}/done", {"summary": summary[:500]}, 30)
    except Unreachable:
        return


# --------------------------------------------------------------------------- the digest
def digest(ctx: Context) -> dict[str, Any] | None:
    try:
        code, body, _ = ctx.get("/flags/digest", 300)
    except Unreachable as exc:
        ctx.report.failed("digest", f"unreachable: {exc}")
        ctx.report.alert(f"the digest route did not answer: {exc}")
        return None
    if code != 200 or not isinstance(body, dict):
        ctx.report.failed("digest", f"answered {code}")
        ctx.report.alert(f"the digest route answered {code}")
        return None
    leagues = body.get("leagues") or []
    skipped = body.get("skipped") or []
    notes = body.get("notes") or []
    counts = []
    for league in leagues:
        if not isinstance(league, dict):
            continue
        flagged = league.get("players") or league.get("flagged") or []
        counts.append(f"{league.get('league')}: {len(flagged)}")
    detail = f"{len(leagues)} leagues, {len(skipped)} skipped, {len(notes)} notes"
    ctx.report.ok("digest", detail, counts=counts, skipped=skipped, notes=notes)
    return body


def post_markdown(
    ctx: Context, name: str, issue: int, markdown: str, retry_after_s: float = 30.0
) -> str | None:
    """Post ``markdown`` verbatim as one comment on ``issue``; retried once; nothing added."""
    if not ctx.posting or ctx.dry_run:
        ctx.report.skipped(name, "posting off" if not ctx.posting else "dry run: nothing posted")
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(markdown)
        path = Path(f.name)
    try:
        code, out = ctx.post(issue, path)
        if code != 0:
            ctx.sleep(retry_after_s)
            code, out = ctx.post(issue, path)
    finally:
        path.unlink(missing_ok=True)
    if code != 0:
        ctx.report.failed(name, f"gh issue comment {issue} failed twice: {out.strip()[:200]}")
        return None
    url = out.strip().splitlines()[-1] if out.strip() else f"#{issue}"
    ctx.report.ok(name, url, url=url)
    return url


def post_digest(ctx: Context, payload: dict[str, Any] | None) -> None:
    if payload is None:
        ctx.report.skipped("post", "no digest to post")
        return
    if not payload.get("leagues"):
        ctx.report.skipped("post", "no league with a season read: nothing posted")
        return
    markdown = payload.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        ctx.report.failed("post", "the digest has no markdown")
        return
    post_markdown(ctx, "post", DIGEST_ISSUE, markdown)


# --------------------------------------------------------------------------- the Monday scripts
def record_all(ctx: Context, api: str) -> list[str]:
    """``scripts/season.py record --all``: one line per league; non-zero only when the API is
    unreachable (then the routine aborts)."""
    if ctx.dry_run:
        ctx.report.skipped("record", "dry run: would run season.py record --all")
        return []
    rc, out, err = ctx.run_script(["season.py", "record", "--all", "--api", api])
    lines = [l for l in out.splitlines() if l.strip()]
    if rc != 0:
        ctx.report.failed("record", f"season.py record exit {rc}: {(err or out).strip()[:200]}")
        ctx.report.alert(
            f"the Monday recorder could not reach the API: {(err or out).strip()[:200]}"
        )
        raise Abort("record: API unreachable")
    failed = [l for l in lines if ": failed (" in l]
    needs = [l for l in lines if "needs pages" in l]
    detail = f"{len(lines)} leagues; {len(failed)} failed, {len(needs)} need pages"
    ctx.notes["record_lines"] = lines
    (ctx.report.failed if failed else ctx.report.ok)("record", detail, lines=lines)
    return lines


def record_retry(ctx: Context, api: str, lines: Sequence[str]) -> None:
    """Each ``failed (5xx)`` league once more after sixty seconds."""
    again = [l.split(":", 1)[0].split()[0] for l in lines if ": failed (5" in l]
    if not again or ctx.dry_run:
        return
    results = []
    for league in again:
        ctx.sleep(60)
        rc, out, _ = ctx.run_script(["season.py", "record", league, "--api", api])
        results.append(out.strip().splitlines()[-1] if out.strip() else f"{league}: exit {rc}")
    ctx.report.ok("record_retry", "; ".join(results)[:300], lines=results)


def scorecard(ctx: Context) -> None:
    """``season.py scorecard`` posted on #127 only when its first line is a week's heading."""
    if ctx.dry_run:
        ctx.report.skipped("scorecard", "dry run: would run season.py scorecard")
        return
    rc, out, _err = ctx.run_script(["season.py", "scorecard"])
    if rc == 2:
        ctx.report.failed("scorecard", "not posted, the API is unreachable")
        return
    first = out.splitlines()[0] if out.strip() else ""
    if not first.startswith("## Scorecard, week "):
        ctx.report.skipped("scorecard", "no week recorded, nothing posted")
        return
    post_markdown(ctx, "scorecard", AUTOPILOT_ISSUE, out)


def monday_step(ctx: Context, api: str) -> None:
    """``season.py monday --comment``: the hill-climb step (#152), its comment posted on #127
    when the script wrote one; exit 1 (refused) or 2 (unreachable) posts nothing."""
    if ctx.dry_run:
        ctx.report.skipped("monday", "dry run: would run season.py monday --comment")
        return
    rc, out, err = ctx.run_script(["season.py", "monday", "--api", api, "--comment"])
    line = err.strip().splitlines()[-1] if err.strip() else ""
    if rc != 0 or not out.strip():
        why = {1: "the API refused the step", 2: "the API is unreachable"}.get(
            rc, "no comment written"
        )
        ctx.report.skipped("monday", f"{why}: {line or out.strip()[:200]}")
        return
    url = post_markdown(ctx, "monday", AUTOPILOT_ISSUE, out)
    if url:
        ctx.report.steps[-1].detail = f"{line} | posted {url}"[:400]


def gh_comment(issue: int, path: Path) -> tuple[int, str]:
    """The real poster: ``gh issue comment``."""
    import subprocess

    r = subprocess.run(
        ["gh", "issue", "comment", str(issue), "--repo", REPO, "--body-file", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def script_runner(repo: Path, python: str) -> RunScript:
    """Run ``scripts/<name>.py`` with the checkout's interpreter, from the checkout."""
    import subprocess

    def run(args: Sequence[str]) -> tuple[int, str, str]:
        name, *rest = args
        r = subprocess.run(
            [python, str(repo / "scripts" / name), *rest],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
        return r.returncode, r.stdout, r.stderr

    return run


def ceil_minutes(seconds: float) -> int:
    return math.ceil(seconds / 60)
