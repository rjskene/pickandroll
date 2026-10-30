"""The routines' browser steps (#225 PR 2): the Chromium driver over a fake Playwright, the
export, private-page and Monday-page steps over fake browsers, and the script's wiring. No
network, no real browser, nothing under data/."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pickandroll.routine import chromium
from pickandroll.routine.browser import NO_BROWSER, refused
from pickandroll.routine.chromium import BBM_CHECK, YAHOO_CHECK, ChromiumBrowser
from pickandroll.routine.report import EXPORT_KINDS
from pickandroll.routine.routines import WINDOWS, run
from pickandroll.routine.steps import (
    IMPORTS,
    export_all,
    lineup_pages,
    monday_pages,
    parse_private_line,
    private_page_urls,
    private_pages,
    saved_name,
    script_runner,
)
from tests.test_routine import Clock, FakeAPI, base_answers, due_answers, make_ctx

YAHOO = "https://basketball.fantasysports.yahoo.com"
PRIVATE = f"{YAHOO}/nba/31822"
LOGOUT = 'a[href*="logout" i]'
DOWNLOADS = {
    "projections.aspx": "Projections.csv",
    "weeklyprojections.aspx": "WeeklyProjections.xls",
    "playerrankings.aspx": "BBM_PlayerRankings.xls",
}


# --------------------------------------------------------------------------- a fake Playwright
class FakeDownload:
    def __init__(self, name):
        self.suggested_filename = name

    def save_as(self, path):
        Path(path).write_bytes(b"player,games\nA,3\n")


class FakeExpect:
    def __init__(self, page):
        self.page, self.download = page, None

    def __enter__(self):
        self.page.expecting = self
        return self

    def __exit__(self, *exc):
        self.page.expecting = None
        return False

    @property
    def value(self):
        if self.download is None:
            raise TimeoutError("Timeout 60000ms exceeded while waiting for event download")
        return self.download


class FakeLocator:
    def __init__(self, page, name):
        self.page, self.name = page, name

    @property
    def first(self):
        return self

    def click(self):
        self.page.calls.append(("real_click", self.name))
        if self.page.expecting is not None:
            name = self.page.downloads.get(self.page.url.rsplit("/", 1)[-1])
            if name:
                self.page.expecting.download = FakeDownload(name)


class FakePage:
    """A page whose DOM is a few dicts: the selects by id, where a URL lands, counts by
    selector, the sign-in markers, the download each export page serves."""

    def __init__(
        self, *, landed=None, selects=None, counts=None, signed_out=False, downloads=None, refuse=()
    ):
        self.calls: list[tuple] = []
        self.url = "about:blank"
        self.expecting = None
        self.landed = landed or {}
        self.selects = dict(selects or {})
        self.counts = counts if counts is not None else {LOGOUT: 1}
        self.signed_out = signed_out
        self.downloads = downloads if downloads is not None else dict(DOWNLOADS)
        self.refuse = set(refuse)

    def goto(self, url, wait_until=None, timeout=None):
        self.calls.append(("goto", url))
        if url in self.refuse:
            raise TimeoutError(f"Timeout {timeout}ms exceeded: {url}")
        self.url = self.landed.get(url, url)

    def evaluate(self, js, arg=None):
        if js is chromium.SET_SELECT_JS:
            sid, label = arg
            self.calls.append(("select", sid, label))
            if sid not in self.selects:
                return f"no select#{sid}"
            if self.selects[sid] == label:
                return "same"
            self.selects[sid] = label
            return "set"
        if js is chromium.READ_SELECT_JS:
            return self.selects.get(arg)
        if js is chromium.CLICK_JS:
            self.calls.append(("js_click", arg))
            return True
        if js is chromium.COUNT_JS:
            return self.counts.get(arg, 0)
        if js is chromium.YAHOO_SIGNED_IN_JS:
            return not self.signed_out
        raise AssertionError(f"unexpected script {js[:40]}")

    def get_by_role(self, role, name=None, exact=False):
        assert role == "button" and exact
        return FakeLocator(self, name)

    def expect_download(self, timeout=None):
        return FakeExpect(self)

    def screenshot(self, path=None, full_page=False):
        Path(path).write_bytes(b"png")


class FakeContext:
    def __init__(self, page, workers=("worker.js",)):
        self.pages = [page]
        self.closed = False
        self.service_workers = [SimpleNamespace(url=f"chrome-extension://abc/{w}") for w in workers]

    def wait_for_event(self, event, timeout=None):
        raise TimeoutError(f"Timeout {timeout}ms exceeded while waiting for event {event!r}")

    def close(self):
        self.closed = True


class FakeDriver:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def launcher(page, workers=("worker.js",)):
    calls = []
    made = []

    def launch(profile, extension, headless):
        calls.append((Path(profile), Path(extension), headless))
        driver, context = FakeDriver(), FakeContext(page, workers)
        made.append((driver, context))
        return driver, context

    launch.calls = calls
    launch.made = made
    return launch


def browser_at(tmp_path, page, workers=("worker.js",), **kw):
    ext = tmp_path / "ext"
    ext.mkdir(exist_ok=True)
    (ext / "manifest.json").write_text("{}")
    sleeps: list[float] = []
    b = ChromiumBrowser(
        tmp_path / "profile",
        ext,
        tmp_path / "downloads",
        sleep=sleeps.append,
        launch=launcher(page, workers),
        **kw,
    )
    b.sleeps = sleeps
    return b


# --------------------------------------------------------------------------- the driver
def test_launch_makes_the_profile_private_empties_downloads_prunes_screens_and_needs_the_worker(
    tmp_path,
):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    (downloads / "Projections-stale.csv").write_text("old")
    screens = tmp_path / "screens"
    screens.mkdir()
    for i in range(25):
        p = screens / f"ros-{i:02d}.png"
        p.write_bytes(b"x")
        os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
    b = browser_at(tmp_path, FakePage())
    assert b.available() and b.available()  # cached
    assert len(b.launch.calls) == 1 and b.launch.calls[0][2] is False  # headed, launched once
    assert b.launch.calls[0][0] == tmp_path / "profile"
    assert (tmp_path / "profile").stat().st_mode & 0o777 == 0o700
    assert list(downloads.iterdir()) == []
    kept = sorted(p.name for p in screens.iterdir())
    assert len(kept) == 20 and kept[0] == "ros-05.png"
    assert b.workers == ["worker.js"]

    b = browser_at(tmp_path, FakePage(), workers=())
    assert b.available() is False
    assert "serviceworker" in b.reason
    assert b.launch.made[0][1].closed and b.launch.made[0][0].stopped


def test_signed_in_checks_each_site_once_and_opens_only_its_check_page(tmp_path):
    page = FakePage()
    b = browser_at(tmp_path, page)
    assert b.signed_in("bbm") and b.signed_in("yahoo")
    assert b.signed_in("bbm") and b.signed_in("yahoo")  # cached
    assert [c for c in page.calls if c[0] == "goto"] == [("goto", BBM_CHECK), ("goto", YAHOO_CHECK)]
    assert b.opened == [BBM_CHECK, YAHOO_CHECK]
    with pytest.raises(ValueError):
        b.signed_in("espn")


@pytest.mark.parametrize(
    "landed,signed_out",
    [
        ("https://login.yahoo.com/?.src=fantasy&.done=" + PRIVATE, False),  # the sign-in redirect
        ("https://guce.yahoo.com/consent?brandType=nonEu", False),  # the consent interstitial
        (PRIVATE, True),  # a sign-in form, or a page without the My Team link
    ],
)
def test_yahoo_signed_out_by_the_redirect_the_consent_page_or_a_page_without_my_team(
    tmp_path, landed, signed_out
):
    page = FakePage(landed={YAHOO_CHECK: landed}, signed_out=signed_out)
    b = browser_at(tmp_path, page)
    assert b.signed_in("yahoo") is False
    assert b.opened == [YAHOO_CHECK]  # nothing else opened

    b = browser_at(tmp_path, FakePage(counts={LOGOUT: 0}))
    assert b.signed_in("bbm") is False


def test_export_sets_the_selects_reads_them_back_refreshes_and_clicks_the_button_for_real(tmp_path):
    page = FakePage(
        selects={
            "PlayerFilterControl": "Top 150",
            "StatDisplayType": "Per Game",
            "DateFilterControl": "Season",
        }
    )
    b = browser_at(tmp_path, page)
    paths = {}
    for kind in EXPORT_KINDS:
        page.calls.clear()
        b.sleeps.clear()
        paths[kind] = b.export(kind)
        assert paths[kind].parent == tmp_path / "downloads" and paths[kind].stat().st_size > 0
    assert re.fullmatch(r"Projections-\d{6}\.csv", paths["ros"].name)
    assert re.fullmatch(r"WeeklyProjections-\d{6}\.xls", paths["week_next"].name)
    assert re.fullmatch(r"BBM_PlayerRankings-\d{6}\.xls", paths["actual_14d"].name)

    page.selects = {
        "PlayerFilterControl": "Top 150",
        "StatDisplayType": "Per Game",
        "DateFilterControl": "Season",
    }
    page.calls.clear()
    b.sleeps.clear()
    b.export("ros")
    assert page.calls == [
        ("goto", "https://basketballmonster.com/projections.aspx"),
        ("select", "PlayerFilterControl", "All Players"),
        ("select", "StatDisplayType", "Total Stats"),
        ("js_click", "#RefreshButton"),
        ("real_click", "Export to CSV"),
    ]
    assert b.sleeps == [4.0, 4.0, 5.0]  # two selects changed, the refresh

    page.calls.clear()
    b.sleeps.clear()
    b.export("week_this")
    assert page.calls == [
        ("goto", "https://basketballmonster.com/weeklyprojections.aspx"),
        ("js_click", "[name=RESTWEEK]"),
        ("select", "PlayerFilterControl", "All Players"),  # already All Players: confirmed, no wait
        ("js_click", "#RefreshButton"),
        ("real_click", "Export to Excel"),
    ]
    assert b.sleeps == [4.0, 5.0]

    page.calls.clear()
    b.export("actual_14d")
    assert ("select", "DateFilterControl", "Past 2 Weeks") in page.calls
    assert page.calls[-2:] == [("js_click", "#RefreshButton"), ("real_click", "Export to Excel")]


def test_export_fails_with_a_screenshot_when_a_select_is_missing_the_download_never_lands_or_the_page_is_signed_out(
    tmp_path,
):
    page = FakePage(selects={"PlayerFilterControl": "Top 150", "StatDisplayType": "Per Game"})
    b = browser_at(tmp_path, page)
    with pytest.raises(RuntimeError, match="no select#DateFilterControl"):
        b.export("actual_7d")
    shots = list((tmp_path / "screens").iterdir())
    assert len(shots) == 1 and shots[0].name.startswith("actual_7d-")

    page = FakePage(selects={"PlayerFilterControl": "x", "StatDisplayType": "y"}, downloads={})
    with pytest.raises(RuntimeError, match="download"):
        browser_at(tmp_path, page).export("ros")

    page = FakePage(
        selects={"PlayerFilterControl": "x", "StatDisplayType": "y"}, counts={LOGOUT: 0}
    )
    with pytest.raises(RuntimeError, match="signed out"):
        browser_at(tmp_path, page).export("ros")


def test_export_stops_at_the_ceiling(tmp_path):
    ticks = iter([0.0, 0.0, 200.0, 200.0, 200.0])
    page = FakePage(selects={"PlayerFilterControl": "x", "StatDisplayType": "y"})
    b = browser_at(tmp_path, page, clock=lambda: next(ticks))
    with pytest.raises(RuntimeError, match="120 s ceiling before select StatDisplayType"):
        b.export("ros")
    assert ("real_click", "Export to CSV") not in page.calls


def test_open_refuses_the_draft_client_and_foreign_hosts_and_reports_the_landed_url(tmp_path):
    assert refused(f"{YAHOO}/draftclient/abc?auth=x")
    assert refused("https://example.com/nba/252098")
    assert refused("http://basketball.fantasysports.yahoo.com/nba/252098")  # https only
    assert refused(f"{YAHOO}/nba/252098/2#pickandroll-lineup") is None
    assert refused("https://basketballmonster.com/projections.aspx") is None

    page = FakePage(landed={f"{PRIVATE}/3#pickandroll-il": f"{PRIVATE}/addplayer?apid=5"})
    b = browser_at(tmp_path, page)
    assert b.open(f"{PRIVATE}/3#pickandroll-il", 30.0) == f"{PRIVATE}/addplayer?apid=5"
    assert b.sleeps == [30.0] and b.opened == [f"{PRIVATE}/3#pickandroll-il"]
    with pytest.raises(ValueError, match="draft client"):
        b.open(f"{YAHOO}/draftclient/abc", 5.0)
    assert page.calls == [("goto", f"{PRIVATE}/3#pickandroll-il")]  # the refused one never loaded
    b.close()
    assert b.launch.made[0][1].closed and b.launch.made[0][0].stopped


# --------------------------------------------------------------------------- the steps
class ScriptedBrowser:
    """A ``Browser`` that records what the steps ask of it."""

    def __init__(self, tmp_path, signed=None, available=True, reason="", counts=None, land=None):
        self.tmp = tmp_path
        self.signed = signed or {"bbm": True, "yahoo": True}
        self._available = available
        self.reason = reason
        self.exports: list[str] = []
        self.opened: list[tuple[str, float]] = []
        self.closed = False
        self.counts = counts or (lambda url: 1)
        self.land = land
        self.fail_exports: set[str] = set()
        self.fail_opens: dict[str, int] = {}

    def available(self):
        return self._available

    def signed_in(self, site):
        return self.signed[site]

    def export(self, kind):
        self.exports.append(kind)
        if kind in self.fail_exports:
            raise RuntimeError(f"{kind}: TimeoutError: no download")
        p = self.tmp / "downloads" / f"{kind}.xls"
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(b"x")
        return p

    def open(self, url, wait_s):
        self.opened.append((url, wait_s))
        if self.fail_opens.get(url, 0) > 0:
            self.fail_opens[url] -= 1
            raise TimeoutError("Timeout 60000ms exceeded")
        return self.land(url) if self.land else url

    def count(self, selector):
        return self.counts(self.opened[-1][0])

    def close(self):
        self.closed = True


IMPORT_LINES = {
    ("draft_day.py", "projections"): (
        0,
        "saved data/bbm_projections_2026-10-29.csv from Projections-050301.csv: 523 players, exported Thu\nmovers against bbm_projections_2026-10-28.csv, top 150 by value:\n  none\n",
        "",
    ),
    ("draft_day.py", "week", "--this"): (
        0,
        "not saved: WeeklyProjections-050512.xls is identical to bbm_week_this_20261029-0201.xls, saved for Thu 2026-10-29 to Sun 2026-11-01\n",
        "",
    ),
    ("draft_day.py", "week", "--next"): (
        0,
        "saved data/bbm_week_next_20261029-0506.xls from WeeklyProjections-050601.xls: next week, Mon 2026-11-02 to Sun 2026-11-08\n",
        "",
    ),
    ("draft_day.py", "past-days", "--days", "7"): (
        1,
        "",
        "BBM_PlayerRankings-050701.xls has a player with 12 games, more than a team plays in 7 days: a season or longer export? Nothing saved\n",
    ),
    ("draft_day.py", "past-days", "--days", "14"): (
        0,
        "saved data/bbm_actual_14d_totals_20261029-0508.xls from BBM_PlayerRankings-050801.xls: 400 players with games over 14 days\n",
        "",
    ),
}


def importer(ctx, clock=None, seconds=0):
    calls = []

    def run_script(args):
        calls.append(tuple(args))
        if clock and seconds:
            clock.advance(seconds)
        return IMPORT_LINES.get(tuple(args), (0, "", ""))

    ctx.run_script = run_script
    return calls


def test_export_all_imports_each_export_as_it_lands_and_records_the_file_that_stands(tmp_path):
    clock = Clock("2026-10-29 05:01")  # a Thursday
    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(FakeAPI(base_answers()), clock, tmp_path, browser=browser)
    calls = importer(ctx)
    export_all(ctx, (6,), None)
    assert browser.exports == list(EXPORT_KINDS)
    assert calls == [IMPORTS[k] for k in EXPORT_KINDS]
    assert ctx.report.exports == {
        "ros": "bbm_projections_2026-10-29.csv",
        "week_this": "bbm_week_this_20261029-0201.xls",
        "week_next": "bbm_week_next_20261029-0506.xls",
        "actual_14d": "bbm_actual_14d_totals_20261029-0508.xls",
    }
    step = ctx.report.find("exports")
    assert step.status == "failed" and step.detail.startswith(
        "4 of 5 due saved; failed: actual_7d (BBM_PlayerRankings"
    )
    assert step.data["lines"]["ros"].startswith("saved data/bbm_projections")
    assert set(step.data["seconds"]) == set(EXPORT_KINDS)

    assert saved_name("saved data/x.xls from y: z") == "x.xls"
    assert saved_name("not saved: a.xls is identical to b.xls, so nothing") == "b.xls"
    assert saved_name("a.xls has a player with 12 games; nothing saved") is None


def test_an_export_that_fails_or_does_not_land_is_reported_and_never_imported(tmp_path):
    browser = ScriptedBrowser(tmp_path)
    browser.fail_exports = {"week_next"}
    ctx = make_ctx(FakeAPI(base_answers()), Clock("2026-10-29 05:01"), tmp_path, browser=browser)
    calls = importer(ctx)
    export_all(ctx, (6,), None)
    assert IMPORTS["week_next"] not in calls and len(calls) == 4
    step = ctx.report.find("exports")
    assert (
        "week_next (export failed: RuntimeError: week_next: TimeoutError: no download)"
        in step.detail
    )


def test_this_week_is_not_due_on_sunday_in_the_daily_and_on_saturday_or_sunday_in_the_evening(
    tmp_path,
):
    for when, not_due, made in [
        ("2026-11-01 05:01", (6,), False),  # Sunday, the daily
        ("2026-10-31 21:02", (5, 6), False),  # Saturday, the evening build
        ("2026-10-31 05:01", (6,), True),  # Saturday, the daily
        ("2026-10-30 21:02", (5, 6), True),  # Friday evening
    ]:
        browser = ScriptedBrowser(tmp_path)
        ctx = make_ctx(FakeAPI(base_answers()), Clock(when), tmp_path, browser=browser)
        importer(ctx)
        export_all(ctx, not_due, None)
        assert ("week_this" in browser.exports) is made, when
        step = ctx.report.find("exports")
        if not made:
            assert (
                step.status == "failed" and "this week not due on a" in step.detail
            )  # actual_7d refused
            assert "week_this" not in ctx.report.exports


def test_the_evening_exports_stop_at_21_15_and_name_the_kinds_left(tmp_path):
    clock = Clock("2026-10-29 21:13")
    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(FakeAPI(base_answers()), clock, tmp_path, browser=browser)
    importer(ctx, clock, seconds=90)  # each import moves the clock a minute and a half
    export_all(ctx, (5, 6), "21:15")
    assert browser.exports == ["ros", "week_this"]
    step = ctx.report.find("exports")
    # Said, not failed: nothing failed, the kinds skipped are named (the SKILL's rule), and a
    # failed step would wake the alert unit every evening the exports run long.
    assert (
        step.status == "ok"
        and "skipped past 21:15: week_next, actual_7d, actual_14d" in step.detail
    )
    assert step.data["late"] == ["week_next", "actual_7d", "actual_14d"]


def test_exports_with_bbm_signed_out_open_nothing_and_alert_once(tmp_path):
    browser = ScriptedBrowser(tmp_path, signed={"bbm": False, "yahoo": True})
    ctx = make_ctx(FakeAPI(base_answers()), Clock("2026-10-29 05:01"), tmp_path, browser=browser)
    calls = importer(ctx)
    export_all(ctx, (6,), None)
    step = ctx.report.find("exports")
    assert step.status == "failed" and "not signed in to bbm" in step.detail
    assert browser.exports == [] and calls == []
    assert ctx.report.alerts == ["the browser profile is signed out of bbm"]


def test_a_browser_that_cannot_start_skips_every_browser_step_with_its_reason_and_one_alert(
    tmp_path,
):
    browser = ScriptedBrowser(tmp_path, available=False, reason="RuntimeError: no DISPLAY")
    api = FakeAPI(base_answers() | {("GET", "/seasons/31822"): (200, {"week": 2, "fetched": {}})})
    ctx = make_ctx(api, Clock("2026-10-29 05:01"), tmp_path, browser=browser)
    report = run("daily", ctx, "http://api")
    for name in ("exports", "private_pages", "lineup_pages", "lineup"):
        step = report.find(name)
        assert (
            step.status == "skipped"
            and "browser unavailable (RuntimeError: no DISPLAY)" in step.detail
        ), name
    assert report.alerts == [
        "the browser could not start at the daily routine: RuntimeError: no DISPLAY"
    ]
    assert "/seasons/31822" not in api.paths()  # nothing read for pages that would not open
    assert report.find("refresh").status == "ok"  # the API steps still ran


def test_private_page_urls_follow_the_daily_skill_order(tmp_path):
    body = {"week": 2, "num_teams": 12, "my_team": {"team_id": 3}, "opponent": {"team_id": 7}}
    urls = private_page_urls(body)
    assert [u for u, _ in urls[:3]] == [PRIVATE, f"{PRIVATE}/1", f"{PRIVATE}/2"]
    assert urls[13] == (f"{PRIVATE}/matchup?date=totals&week=2&mid1=3&mid2=7", None)
    assert urls[14] == (f"{PRIVATE}/transactions", None)
    assert urls[15] == (
        f"{PRIVATE}/players?status=A&pos=P&stat1=R_O&sort=R_PO&sdir=1&count=0",
        "R_O",
    )
    assert urls[-1] == (
        f"{PRIVATE}/players?status=A&pos=P&stat1=S_PS7&sort=R_PO&sdir=1&count=275",
        "S_PS7",
    )
    assert len(urls) == 1 + 12 + 1 + 1 + 24
    assert all(u.startswith(PRIVATE) for u, _ in urls)
    without = private_page_urls(
        {"week": 2, "num_teams": 10, "my_team": {"team_id": 3}, "opponent": None}
    )
    assert len(without) == 1 + 10 + 1 + 24 and not any("matchup" in u for u, _ in without)


def test_private_pages_open_the_pages_stop_an_empty_view_and_read_the_league_back(tmp_path):
    reads = []

    def league(_body):
        reads.append(1)
        fetched = {"league": {}, "roster/3": {}} if len(reads) > 1 else {}
        return 200, {
            "week": 2,
            "num_teams": 12,
            "my_team": {"team_id": 3},
            "opponent": {"team_id": 7},
            "updated_at": "2026-10-29T10:13:00+00:00",
            "fetched": fetched,
        }

    api = FakeAPI(base_answers() | {("GET", "/seasons/31822"): league})
    browser = ScriptedBrowser(
        tmp_path, counts=lambda url: 0 if "stat1=R_O" in url and "count=50" in url else 1
    )
    ctx = make_ctx(api, Clock("2026-10-29 05:03"), tmp_path, browser=browser)
    private_pages(ctx)
    opened = [u for u, _ in browser.opened]
    assert len(opened) == 1 + 12 + 1 + 1 + 3 + 12  # the R_O view stopped after its third page
    assert all(w == 5.0 for _, w in browser.opened)
    assert opened[-1].endswith("stat1=S_PS7&sort=R_PO&sdir=1&count=275")
    step = ctx.report.find("private_pages")
    assert step.status == "ok"
    assert (
        step.detail
        == "30 pages opened; updated_at 2026-10-29T10:13:00+00:00, 2 fetched keys; views stopped early: R_O"
    )
    assert len(reads) == 2

    browser = ScriptedBrowser(tmp_path, signed={"bbm": True, "yahoo": False})
    ctx = make_ctx(api, Clock("2026-10-29 05:03"), tmp_path, browser=browser)
    private_pages(ctx)
    assert ctx.report.find("private_pages").status == "failed" and browser.opened == []
    assert ctx.report.alerts == ["the browser profile is signed out of yahoo"]

    ctx = make_ctx(
        api, Clock("2026-10-29 05:03"), tmp_path, browser=ScriptedBrowser(tmp_path), dry_run=True
    )
    private_pages(ctx)
    assert ctx.report.find("private_pages").detail.startswith("dry run: would open")


def test_a_page_that_fails_to_load_is_tried_once_more_then_counted_failed(tmp_path):
    api = FakeAPI(
        base_answers()
        | {
            ("GET", "/seasons/31822"): (
                200,
                {
                    "week": 2,
                    "num_teams": 2,
                    "my_team": {"team_id": 1},
                    "opponent": {"team_id": 2},
                    "fetched": {},
                },
            )
        }
    )
    browser = ScriptedBrowser(tmp_path)
    browser.fail_opens = {f"{PRIVATE}/1": 1, f"{PRIVATE}/2": 2}
    clock = Clock("2026-10-29 05:03")
    ctx = make_ctx(api, clock, tmp_path, browser=browser)
    private_pages(ctx)
    opened = [u for u, _ in browser.opened]
    assert opened.count(f"{PRIVATE}/1") == 2 and opened.count(f"{PRIVATE}/2") == 2
    assert ctx.notes["_sleeps"].calls == [10, 10]  # one wait before each retry, none after the last
    step = ctx.report.find("private_pages")
    assert (
        step.status == "failed"
        and "1 failed to open" in step.detail
        and f"{PRIVATE}/2: TimeoutError" in step.detail
    )


def test_lineup_pages_open_at_most_ten_and_say_when_they_did_not_land(tmp_path):
    needs = [f"{PRIVATE}/settings"] + [f"{PRIVATE}/3?date=2026-11-{d:02d}" for d in range(1, 12)]
    needs.append("https://example.com/nba/31822/3")
    answers = iter([needs, needs[:2]])

    api = FakeAPI(
        base_answers()
        | {("GET", "/seasons/31822/lineup"): lambda _b: (200, {"needs": next(answers)})}
    )
    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(api, Clock("2026-10-29 05:08"), tmp_path, browser=browser)
    lineup_pages(ctx)
    assert [u for u, _ in browser.opened] == needs[:10]
    step = ctx.report.find("lineup_pages")
    assert step.status == "failed"
    assert (
        step.detail
        == "10 of 10 pages opened, 2 left for the next run; skipped, not the league's: 1; lineup pages did not land: 2 still needed"
    )
    assert ctx.report.alerts == ["the private league's lineup pages did not land (2 still needed)"]

    answers = iter([needs[:3], []])
    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(api, Clock("2026-10-29 05:08"), tmp_path, browser=browser)
    lineup_pages(ctx)
    assert ctx.report.find("lineup_pages").detail == "3 of 3 pages opened; needs now empty"

    answers = iter([[]])
    ctx = make_ctx(api, Clock("2026-10-29 05:08"), tmp_path, browser=ScriptedBrowser(tmp_path))
    lineup_pages(ctx)
    assert ctx.report.find("lineup_pages").detail == "nothing needed"


def test_parse_private_line_reads_needs_lineup_and_schedule_pages():
    lines = [
        "252098 week 2: recorded (pages: taken 7)",
        f"31822 week 2: needs pages (2): {PRIVATE} {PRIVATE}/transactions; schedule pages (2): {PRIVATE}?matchup_week=5 {PRIVATE}?matchup_week=6; lineup pages (1): {PRIVATE}/settings",
    ]
    pages = parse_private_line(lines)
    assert pages.needs == [PRIVATE, f"{PRIVATE}/transactions"]
    assert pages.schedule == [f"{PRIVATE}?matchup_week=5", f"{PRIVATE}?matchup_week=6"]
    assert pages.lineup == [f"{PRIVATE}/settings"]
    recorded = parse_private_line(
        [f"31822 week 2: recorded (pages: taken 2); schedule pages (1): {PRIVATE}?matchup_week=7"]
    )
    assert (
        recorded.needs == []
        and recorded.lineup == []
        and recorded.schedule == [f"{PRIVATE}?matchup_week=7"]
    )
    assert parse_private_line(["252098 week 2: unchanged"]) is None
    assert parse_private_line(["31822: failed (502): yahoo"]).needs == []


def test_monday_pages_open_needs_then_lineup_then_schedule_with_the_record_runs_between(tmp_path):
    needs = [PRIVATE, f"{PRIVATE}/transactions"]
    lineup = [f"{PRIVATE}/settings"] + [f"{PRIVATE}/3?date=2026-10-{d}" for d in range(26, 29)]
    schedule = [f"{PRIVATE}?matchup_week={w}" for w in range(5, 45)]  # forty: the cap bites
    first = f"31822 week 2: needs pages (2): {' '.join(needs)}; schedule pages (40): {' '.join(schedule)}; lineup pages (4): {' '.join(lineup)}"
    after_needs = f"31822 week 2: recorded (pages: taken 2); schedule pages (40): {' '.join(schedule)}; lineup pages (4): {' '.join(lineup)}"
    after_lineup = f"31822 week 2: unchanged; schedule pages (40): {' '.join(schedule)}"
    records = iter([after_needs, after_lineup])
    scripts = []

    def run_script(args):
        scripts.append(tuple(args))
        return 0, next(records) + "\n", ""

    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(
        FakeAPI(base_answers()),
        Clock("2026-10-26 06:04"),
        tmp_path,
        routine="monday",
        browser=browser,
    )
    ctx.run_script = run_script
    monday_pages(ctx, "http://api", ["252098 week 2: recorded", first])
    opened = [u for u, _ in browser.opened]
    assert opened == needs + lineup + schedule[:26]  # 30 together, the lineup pages first
    assert scripts == [("season.py", "record", "31822", "--api", "http://api")] * 2
    assert ctx.notes["_sleeps"].calls == [10, 10]
    step = ctx.report.find("private_pages")
    assert step.status == "ok"
    assert step.detail == "2 needed pages opened in 1 round(s), 4 lineup, 26 schedule; 14 left"
    assert step.data["counts"] == {"needs": 2, "lineup": 4, "schedule": 26}


def test_monday_pages_try_the_needs_once_more_and_say_when_lineup_pages_did_not_land(tmp_path):
    still = f"31822 week 2: needs pages (1): {PRIVATE}/transactions; lineup pages (1): {PRIVATE}/settings"
    records = iter(
        [
            still,
            f"31822 week 2: recorded; lineup pages (1): {PRIVATE}/settings",
            f"31822 week 2: recorded; lineup pages (1): {PRIVATE}/settings",
        ]
    )
    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(
        FakeAPI(base_answers()),
        Clock("2026-10-26 06:04"),
        tmp_path,
        routine="monday",
        browser=browser,
    )
    ctx.run_script = lambda args: (0, next(records) + "\n", "")
    monday_pages(
        ctx, "http://api", [f"31822 week 2: needs pages (2): {PRIVATE} {PRIVATE}/transactions"]
    )
    opened = [u for u, _ in browser.opened]
    assert opened == [
        PRIVATE,
        f"{PRIVATE}/transactions",
        f"{PRIVATE}/transactions",
        f"{PRIVATE}/settings",
    ]
    step = ctx.report.find("private_pages")
    assert step.status == "failed" and "lineup pages did not land" in step.detail
    assert "2 needed pages" not in step.detail and step.data["counts"]["needs"] == 3
    assert ctx.report.alerts == [
        "the private league's lineup pages did not land at the Monday recorder"
    ]

    ctx = make_ctx(
        FakeAPI(base_answers()),
        Clock("2026-10-26 06:04"),
        tmp_path,
        routine="monday",
        browser=ScriptedBrowser(tmp_path),
    )
    monday_pages(ctx, "http://api", ["31822 week 2: unchanged"])
    assert ctx.report.find("private_pages").detail == "31822 needs no page"
    monday_pages(ctx, "http://api", ["252098 week 2: unchanged"], name="again")
    assert ctx.report.find("again").status == "skipped"


def test_the_monday_routine_runs_the_pages_between_the_record_and_its_retry(tmp_path):
    lines = {
        ("season.py", "record", "--all"): "252098 week 2: recorded\n31822 week 2: needs pages (1): "
        + PRIVATE
        + "\n",
        ("season.py", "record", "31822"): "31822 week 2: recorded (pages: taken 1)\n",
        ("season.py", "scorecard"): "## Scorecard\n\nNo week is recorded yet.\n",
        ("season.py", "monday"): "",
    }
    scripts = []

    def run_script(args):
        scripts.append(tuple(args[:3]))
        return (1 if args[1] == "monday" else 0), lines.get(tuple(args[:3]), ""), ""

    browser = ScriptedBrowser(tmp_path)
    ctx = make_ctx(
        FakeAPI(base_answers()),
        Clock("2026-10-26 06:04"),
        tmp_path,
        routine="monday",
        browser=browser,
    )
    ctx.run_script = run_script
    report = run("monday", ctx, "http://api")
    assert [u for u, _ in browser.opened] == [PRIVATE]
    assert scripts[:2] == [("season.py", "record", "--all"), ("season.py", "record", "31822")]
    assert report.find("private_pages").status == "ok" and browser.closed


def test_a_dry_run_launches_no_browser_and_opens_nothing(tmp_path):
    page = FakePage()
    b = browser_at(tmp_path, page)
    api = FakeAPI(base_answers() | {("GET", "/seasons/31822"): (200, {"week": 2, "fetched": {}})})
    ctx = make_ctx(api, Clock("2026-10-29 05:01"), tmp_path, browser=b, dry_run=True)
    report = run("daily", ctx, "http://api")
    assert b.launch.calls == [] and page.calls == []
    for name in ("exports", "private_pages", "lineup_pages", "lineup"):
        assert report.find(name).status == "skipped" and report.find(name).detail.startswith(
            "dry run:"
        ), name
    assert (
        report.find("exports").detail
        == "dry run: would export 5 kinds: ros, week_this, week_next, actual_7d, actual_14d"
    )

    b = browser_at(tmp_path, page)
    ctx = make_ctx(
        FakeAPI(due_answers()),
        Clock("2026-10-29 07:50"),
        tmp_path,
        routine="morning",
        browser=b,
        dry_run=True,
    )
    report = run("morning", ctx, "http://api")
    assert b.launch.calls == []
    assert report.find("moves").detail == "dry run: 2 pages would open"


def test_the_signin_routine_reports_both_sites_and_fails_when_one_is_out(tmp_path):
    assert WINDOWS["signin"] == ("00:00", "23:59")
    browser = ScriptedBrowser(tmp_path, signed={"bbm": True, "yahoo": False})
    api = FakeAPI({})
    ctx = make_ctx(api, Clock("2026-10-29 04:50"), tmp_path, routine="signin", browser=browser)
    report = run("signin", ctx, "http://api")
    assert api.calls == []  # no API needed
    assert [(s.name, s.status) for s in report.steps] == [
        ("browser", "ok"),
        ("bbm", "ok"),
        ("yahoo", "failed"),
    ]
    assert report.alerts == ["the browser profile is signed out of yahoo"] and report.any_failed
    assert browser.closed

    browser = ScriptedBrowser(tmp_path, available=False, reason="RuntimeError: no DISPLAY")
    ctx = make_ctx(api, Clock("2026-10-29 04:50"), tmp_path, routine="signin", browser=browser)
    report = run("signin", ctx, "http://api")
    assert (
        report.find("browser").status == "failed" and "no DISPLAY" in report.find("browser").detail
    )

    ctx = make_ctx(api, Clock("2026-10-29 04:50"), tmp_path, routine="signin")
    report = run("signin", ctx, "http://api")
    assert (
        report.find("browser").status == "skipped" and NO_BROWSER in report.find("browser").detail
    )


def test_a_pass_with_a_browser_names_a_page_that_failed_twice(tmp_path):
    api = FakeAPI(
        due_answers()
        | {
            ("POST", "/autopilot/passes"): (200, {"id": "p"}),
            ("POST", "/autopilot/passes/p/opening"): (200, {}),
            ("POST", "/autopilot/passes/p/done"): (200, {}),
            ("GET", "/seasons/252098/autopilot/moves"): (
                200,
                {"today": [{"trigger": "routine", "outcome": "would_claim"}]},
            ),
        }
    )
    browser = ScriptedBrowser(tmp_path)
    add_page = f"{YAHOO}/nba/252098/addplayer?apid=111#pickandroll-moves"
    browser.fail_opens = {add_page: 2}
    ctx = make_ctx(api, Clock("2026-10-29 07:50"), tmp_path, routine="morning", browser=browser)
    report = run("morning", ctx, "http://api")
    moves = report.find("moves")
    # The scripted browser lands where it is sent, so the IL tab stays and the pass opens e2's
    # add page itself; e1's add page fails twice.
    assert moves.status == "failed" and moves.detail.startswith(
        "2 pages opened in 1 leagues, add pages opened by the pass after an IL stay: e2, "
        "1 failed to open: e1"
    )
    assert moves.data["failed"] == ["e1"] and moves.data["stayed"] == ["e2"]
    assert [u for u, _ in browser.opened].count(add_page) == 2


def test_the_script_runner_passes_the_downloads_folder_to_the_importers(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "echo.py").write_text(
        "import os, sys; print(os.environ.get('PICKANDROLL_DOWNLOADS', 'unset')); print(' '.join(sys.argv[1:]))"
    )
    run_script = script_runner(
        tmp_path, sys.executable, {"PICKANDROLL_DOWNLOADS": str(tmp_path / "dl")}
    )
    code, out, _ = run_script(["echo.py", "week", "--this"])
    assert code == 0 and out.splitlines() == [str(tmp_path / "dl"), "week --this"]
    code, out, _ = script_runner(tmp_path, sys.executable)(["echo.py"])
    assert out.splitlines()[0] in ("unset", os.environ.get("PICKANDROLL_DOWNLOADS", "unset"))


def test_a_signed_out_check_page_that_does_not_load_counts_as_signed_out_with_the_reason(tmp_path):
    page = FakePage(refuse={YAHOO_CHECK})
    b = browser_at(tmp_path, page)
    assert b.signed_in("yahoo") is False and "TimeoutError" in b.reason
    assert b.opened == [YAHOO_CHECK]
