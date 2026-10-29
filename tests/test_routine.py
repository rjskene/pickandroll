"""The routines runner (#225): the sequences, their pacing, windows and reports, against a fake
API, a fixed clock and a recorded sleep. Nothing here touches a network or the data folder."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pickandroll.routine import CENTRAL, Context, Report, Unreachable, run
from pickandroll.routine.report import MARKER_STEPS, marker
from pickandroll.routine.routines import WINDOWS
from pickandroll.routine.steps import Opening, behind_the_read, moves_plan, refresh_all

YAHOO = "https://basketball.fantasysports.yahoo.com"
PUBLIC = ["252098", "230585"]
SEASONS = [
    {"league": "252098", "public": True},
    {"league": "230585", "public": True},
    {"league": "31822", "public": False},
    {"league": "227293", "public": True},
]


class FakeAPI:
    """Answers by (method, path): a tuple (code, body[, headers]) or a callable of the body."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, path, body=None, timeout=60.0):
        self.calls.append((method, path))
        key = (method, path)
        if key not in self.answers:
            key = (method, path.split("?")[0])
        answer = self.answers.get(key)
        if answer is None:
            return 404, {"detail": f"no fake for {method} {path}"}, {}
        if callable(answer):
            answer = answer(body)
        code, payload, *rest = answer
        return code, payload, (rest[0] if rest else {})

    def paths(self, method=None):
        return [p for m, p in self.calls if method is None or m == method]


class Clock:
    def __init__(self, start: str):
        self.t = datetime.fromisoformat(start).replace(tzinfo=CENTRAL)

    def __call__(self):
        return self.t

    def advance(self, seconds: float):
        self.t += timedelta(seconds=seconds)


class Sleeps:
    def __init__(self, clock: Clock):
        self.clock = clock
        self.calls: list[float] = []

    def __call__(self, s: float):
        self.calls.append(s)
        self.clock.advance(s)


def make_ctx(api, clock, tmp_path, **kw):
    sleeps = Sleeps(clock)
    report = Report(kw.pop("routine", "daily"), clock(), clock=clock)
    scripts: list[list[str]] = []

    def run_script(args):
        scripts.append(list(args))
        return kw.pop("script_answer", (0, "", "")) if "script_answer" in kw else (0, "", "")

    posts: list[tuple[int, str]] = []

    def post(issue, path):
        posts.append((issue, Path(path).read_text()))
        return 0, f"https://github.com/rjskene/pickandroll/issues/{issue}#issuecomment-1\n"

    ctx = Context(
        call=api,
        now=clock,
        sleep=sleeps,
        report=report,
        data_dir=tmp_path,
        run_script=run_script,
        post=post,
        **kw,
    )
    ctx.notes["_sleeps"] = sleeps
    ctx.notes["_scripts"] = scripts
    ctx.notes["_posts"] = posts
    return ctx


def base_answers(over=None):
    answers = {
        ("GET", "/seasons"): (200, SEASONS),
        ("POST", "/autopilot/queue/build"): (
            200,
            {
                "leagues": [{"league": k, "status": "queued"} for k in PUBLIC]
                + [{"league": "31822", "status": "private"}],
                "entries": [{"id": "a", "queued": True}, {"id": "b", "queued": False}],
            },
        ),
        ("GET", "/flags/digest"): (
            200,
            {
                "leagues": [{"league": "252098", "players": [1, 2]}],
                "skipped": [],
                "notes": [],
                "markdown": "## Breakout flags\n\nnothing of note\n",
            },
        ),
        ("GET", "/autopilot/start-active/due"): (200, {"stop": False, "leagues": []}),
    }
    for k in PUBLIC + ["31822"]:
        answers[("POST", f"/seasons/{k}/refresh")] = (202, {"refresh": {"status": "done"}})
        answers[("GET", f"/seasons/{k}/moves")] = (200, {"sets": []})
        answers[("GET", f"/seasons/{k}/lineup/steps")] = (
            200,
            {
                "mode": "dry_run",
                "open": True,
                "date": "2026-10-29",
                "page": f"{YAHOO}/nba/{k}/2?date=2026-10-29",
            },
        )
    answers.update(over or {})
    return answers


# --------------------------------------------------------------------------- the daily
def test_daily_refreshes_public_leagues_paced_and_solves_every_league(tmp_path):
    api = FakeAPI(base_answers())
    clock = Clock("2026-10-29 05:01")
    ctx = make_ctx(api, clock, tmp_path)
    report = run("daily", ctx, "http://api")

    refreshed = [p for p in api.paths("POST") if "/refresh" in p]
    assert refreshed == [
        f"/seasons/{k}/refresh?wait=true" for k in PUBLIC
    ]  # 31822 and 227293 never
    assert ctx.notes["_sleeps"].calls.count(60.0) == 1  # one pause between two leagues
    solved = [p for p in api.paths("GET") if p.endswith("/moves")]
    assert solved == [
        f"/seasons/{k}/moves" for k in PUBLIC + ["31822"]
    ]  # the private league solves
    assert api.paths("POST")[-1] == "/autopilot/queue/build"
    by_name = {s.name: s for s in report.steps}
    assert by_name["refresh"].status == "ok" and by_name["solve"].status == "ok"
    assert by_name["queue_build"].detail.startswith("1 entries queued")
    assert by_name["post"].status == "ok" and ctx.notes["_posts"][0][0] == 99
    assert ctx.notes["_posts"][0][1] == "## Breakout flags\n\nnothing of note\n"  # verbatim
    for name in ("exports", "private_pages", "lineup_pages", "lineup"):
        assert by_name[name].status == "skipped" and "no browser" in by_name[name].detail
    assert "4 pages would open" in by_name["lineup"].detail  # today and tomorrow, two leagues
    assert by_name["start_active"].detail == "nothing to open"  # no league needs it today
    assert not report.refused and report.finished is not None


def test_steps_are_timed_from_the_previous_step_and_the_summary_says_how_long(tmp_path):
    api = FakeAPI(base_answers())
    clock = Clock("2026-10-29 05:01")
    ctx = make_ctx(api, clock, tmp_path)
    report = run("daily", ctx, "http://api")
    refresh = report.find("refresh")
    assert (
        refresh.started == report.find("lineup_pages").finished
    )  # a step starts where the last ended
    assert refresh.finished == "2026-10-29T05:02:00-05:00"  # the one 60 s pause between two leagues
    assert "- refresh: ok, 2 leagues refreshed (60 s)" in report.summary()
    assert (
        "- api: ok, 200 on first check, not restarted\n" in report.summary()
    )  # untimed-looking: under 2 s
    logged = report.to_dict()["steps"][0]
    assert logged["started"] == "2026-10-29T05:01:00-05:00" and "finished" in logged


def test_daily_marker_has_the_eight_step_keys_and_no_exports(tmp_path):
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-29 05:01"), tmp_path)
    report = run("daily", ctx, "http://api")
    m = marker(report)
    assert tuple(m["steps"]) == MARKER_STEPS
    assert m["steps"]["refresh"] == {"status": "ok", "detail": "2 leagues refreshed"}
    assert m["steps"]["exports"]["status"] == "skipped"
    assert m["exports"] == {}
    assert m["started_at"].endswith("-05:00") and m["finished_at"] >= m["started_at"]


def test_daily_posts_nothing_with_posting_off_and_a_dry_run_writes_nothing(tmp_path):
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-29 05:01"), tmp_path, posting=False)
    report = run("daily", ctx, "http://api")
    assert report.find("post").status == "skipped" and not ctx.notes["_posts"]

    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-29 05:01"), tmp_path, dry_run=True)
    report = run("daily", ctx, "http://api")
    assert not api.paths("POST")  # no refresh, no build
    assert all(p == "/seasons" or "/moves" not in p for p in api.paths("GET"))
    assert {
        s.status for s in report.steps if s.name in ("refresh", "solve", "queue_build", "post")
    } == {"skipped"}
    assert report.find("digest").status == "ok"  # reads still run


def test_refresh_retries_a_503_after_the_cool_off_and_a_502_at_once(tmp_path):
    seen = {"252098": 0, "230585": 0}

    def limited(_body, league="252098"):
        seen[league] += 1
        if seen[league] == 1:
            return 503, {"detail": "999"}, {"retry-after": "900"}
        return 202, {"refresh": {}}

    def flaky(_body):
        seen["230585"] += 1
        return (502, {"detail": "yahoo"}) if seen["230585"] == 1 else (202, {})

    api = FakeAPI(
        base_answers(
            {
                ("POST", "/seasons/252098/refresh"): limited,
                ("POST", "/seasons/230585/refresh"): flaky,
            }
        )
    )
    clock = Clock("2026-10-29 05:05")
    ctx = make_ctx(api, clock, tmp_path)
    refresh_all(ctx, PUBLIC, "05:45")
    sleeps = ctx.notes["_sleeps"].calls
    assert sleeps == [60.0, 900.0]  # the pace, then the cool-off (max of Retry-After and 600 s)
    assert seen == {"252098": 2, "230585": 2}
    assert ctx.report.find("refresh").status == "ok"


def test_refresh_skips_the_retry_pass_past_the_cutoff_and_reports_the_league_failed(tmp_path):
    api = FakeAPI(
        base_answers(
            {
                ("POST", "/seasons/252098/refresh"): (
                    503,
                    {"detail": "999"},
                    {"retry-after": "300"},
                ),
            }
        )
    )
    ctx = make_ctx(api, Clock("2026-10-29 05:40"), tmp_path)
    refresh_all(ctx, PUBLIC, "05:45")
    step = ctx.report.find("refresh")
    assert step.status == "failed"
    assert "252098 (503)" in step.detail and "no retry pass" in step.detail
    assert ctx.notes["_sleeps"].calls == [60.0]


# --------------------------------------------------------------------------- windows, STOP, API
@pytest.mark.parametrize(
    "name,when",
    [
        ("daily", "2026-10-29 06:30"),
        ("morning", "2026-10-29 07:30"),
        ("evening-pass", "2026-10-29 22:58"),
        ("monday", "2026-10-26 13:00"),
    ],
)
def test_a_routine_outside_its_window_is_refused_and_calls_nothing(tmp_path, name, when):
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock(when), tmp_path, routine=name)
    report = run(name, ctx, "http://api")
    assert report.refused and name in report.refused or "Monday" in report.refused
    assert api.calls == [] and report.finished is not None


def test_monday_on_a_tuesday_is_refused_unless_forced(tmp_path):
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-27 06:05"), tmp_path, routine="monday")
    assert run("monday", ctx, "http://api").refused == "not a Monday (Tuesday)"
    ctx = make_ctx(FakeAPI(base_answers()), Clock("2026-10-27 06:05"), tmp_path, routine="monday")
    report = run("monday", ctx, "http://api", force=True)
    assert report.refused is None and report.find("window").detail.startswith("forced")


def test_stop_file_ends_a_pass_before_any_league_is_read(tmp_path):
    (tmp_path / "autopilot").mkdir()
    (tmp_path / "autopilot" / "STOP").write_text("")
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-29 07:50"), tmp_path, routine="morning")
    report = run("morning", ctx, "http://api")
    assert report.stopped and api.paths() == ["/seasons"]  # the API check only


def test_a_pass_never_starts_a_down_api_but_the_daily_tries_once(tmp_path):
    api = FakeAPI({("GET", "/seasons"): (503, {})})
    ctx = make_ctx(api, Clock("2026-10-29 07:50"), tmp_path, routine="morning")
    report = run("morning", ctx, "http://api")
    assert report.find("api").status == "failed" and ctx.notes["_scripts"] == []
    assert report.alerts and "down" in report.alerts[0]

    ctx = make_ctx(api, Clock("2026-10-29 05:02"), tmp_path)
    report = run("daily", ctx, "http://api")
    assert ctx.notes["_scripts"] == [["draft_day.py", "servers", "--start"]]
    assert ctx.notes["_sleeps"].calls == [10]
    assert report.any_failed and report.find("refresh") is None


def test_an_unreachable_api_is_reported_as_such(tmp_path):
    def down(method, path, body=None, timeout=60.0):
        raise Unreachable("http://api: refused")

    ctx = make_ctx(down, Clock("2026-10-29 21:05"), tmp_path, routine="evening-build")
    report = run("evening-build", ctx, "http://api")
    assert report.find("api").status == "failed" and "unreachable" in report.find("api").detail


# --------------------------------------------------------------------------- the passes' plans
def due_answers():
    return base_answers(
        {
            ("GET", "/seasons/252098/autopilot/moves/due"): (
                200,
                {
                    "mode": "live",
                    "stop": False,
                    "entries": [
                        {"id": "e1", "page": "/nba/252098/addplayer?apid=111"},
                        {"id": "e2", "page": "/nba/252098/addplayer?apid=222"},
                        {"id": "bad", "page": "/nba/999999/addplayer?apid=333"},
                    ],
                    "il_first": [
                        {
                            "entry": "e2",
                            "player": 5,
                            "slot": "IL",
                            "date": "2026-10-29",
                            "page": f"{YAHOO}/nba/252098/2?date=2026-10-29",
                        }
                    ],
                },
            ),
            ("GET", "/seasons/230585/autopilot/moves/due"): (
                200,
                {"mode": "off", "entries": [], "reason": "mode off"},
            ),
        }
    )


def test_moves_plan_puts_il_moves_first_and_checks_every_page(tmp_path):
    ctx = make_ctx(FakeAPI(due_answers()), Clock("2026-10-29 07:50"), tmp_path, routine="morning")
    plan = moves_plan(ctx, PUBLIC, "pickandroll-moves", "pickandroll-il")
    assert [o.kind for o in plan.openings] == ["il", "moves"]
    assert plan.openings[0].url == f"{YAHOO}/nba/252098/2?date=2026-10-29#pickandroll-il"
    assert plan.openings[0].wait_s == 30.0 and plan.openings[0].entry == "e2"
    assert plan.openings[1].url == f"{YAHOO}/nba/252098/addplayer?apid=111#pickandroll-moves"
    assert plan.entries == ["e2", "e1"] and plan.leagues == ["252098"]
    assert plan.reasons["230585"] == "mode off"
    assert "not the league's" in plan.reasons["252098:bad"]


def test_morning_without_a_browser_reports_the_plan_and_opens_no_pass_record(tmp_path):
    api = FakeAPI(due_answers())
    ctx = make_ctx(api, Clock("2026-10-29 07:50"), tmp_path, routine="morning")
    report = run("morning", ctx, "http://api")
    assert report.find("due").detail.startswith("2 entries due in 1 leagues")
    moves = report.find("moves")
    assert moves.status == "skipped" and "2 pages would open" in moves.detail
    assert len(moves.data["plan"]) == 2
    assert "/autopilot/passes" not in " ".join(api.paths("POST"))
    assert report.find("check") is None  # nothing opened, nothing to check


class FakeBrowser:
    reason = ""

    def __init__(self, signed=True, clock=None, land=None):
        self.signed, self.opened, self.closed, self.clock, self.land = (
            signed,
            [],
            False,
            clock,
            land,
        )

    def available(self):
        return True

    def signed_in(self, site):
        return self.signed

    def export(self, kind):
        return None

    def open(self, url, wait_s):
        self.opened.append((url, wait_s))
        if self.clock:
            self.clock.advance(wait_s)
        return self.land(url) if self.land else url

    def count(self, selector):
        return 1

    def close(self):
        self.closed = True


def test_morning_with_a_browser_opens_the_pages_and_keeps_the_pass_record(tmp_path):
    passes = []

    def open_pass(body):
        passes.append(("open", body))
        return 200, {"id": "2026-10-29:moves:1"}

    api = FakeAPI(
        due_answers()
        | {
            ("POST", "/autopilot/passes"): open_pass,
            ("POST", "/autopilot/passes/2026-10-29:moves:1/opening"): lambda b: (
                passes.append(("opening", b)),
                (200, {}),
            )[1],
            ("POST", "/autopilot/passes/2026-10-29:moves:1/done"): lambda b: (
                passes.append(("done", b)),
                (200, {}),
            )[1],
            ("GET", "/seasons/252098/autopilot/moves"): (
                200,
                {
                    "today": [{"trigger": "routine", "outcome": "would_claim", "reason": None}],
                    "il_today": [{"outcome": "would_move"}],
                    "start_active_today": [],
                },
            ),
        }
    )
    clock = Clock("2026-10-29 07:50")
    # The IL chain happened: after the IL wait the tab is on the entry's add page.
    chained = f"{YAHOO}/nba/252098/addplayer?apid=222#pickandroll-moves"
    browser = FakeBrowser(clock=clock, land=lambda u: chained if "#pickandroll-il" in u else u)
    ctx = make_ctx(api, clock, tmp_path, routine="morning", browser=browser)
    report = run("morning", ctx, "http://api")
    assert [u.split("#")[1] for u, _ in browser.opened] == ["pickandroll-il", "pickandroll-moves"]
    assert "il_stayed" not in ctx.notes
    assert passes[0] == (
        "open",
        {"kind": "moves", "trigger": "routine", "leagues": ["252098"], "entries": ["e2", "e1"]},
    )
    assert [p[1] for p in passes if p[0] == "opening"] == [
        {"league": "252098", "entry": "e2"},
        {"league": "252098", "entry": "e1"},
    ]
    assert passes[-1] == ("done", {"summary": "2 pages opened in 1 leagues"})
    assert report.find("moves").status == "ok"
    assert (
        report.find("check").status == "ok"
        and "would_claim" in report.find("check").data["lines"][0]
    )
    assert browser.closed


def test_an_il_opening_that_stays_on_the_team_page_gets_its_add_page_opened_by_the_pass(tmp_path):
    passes = []
    api = FakeAPI(
        due_answers()
        | {
            ("POST", "/autopilot/passes"): lambda b: (200, {"id": "2026-10-29:moves:1"}),
            ("POST", "/autopilot/passes/2026-10-29:moves:1/opening"): lambda b: (
                passes.append(b),
                (200, {}),
            )[1],
            ("POST", "/autopilot/passes/2026-10-29:moves:1/done"): lambda b: (
                passes.append(b),
                (200, {}),
            )[1],
            ("GET", "/seasons/252098/autopilot/moves"): (
                200,
                {"today": [{"trigger": "routine", "outcome": "would_claim", "reason": None}]},
            ),
        }
    )
    clock = Clock("2026-10-29 07:50")
    browser = FakeBrowser(clock=clock)  # lands where it is sent: the IL tab stays on the team page
    ctx = make_ctx(api, clock, tmp_path, routine="morning", browser=browser)
    report = run("morning", ctx, "http://api")
    # The IL page, then the entry's own add page opened by the pass (the moves fragment, twelve
    # seconds), then the other due entry.
    assert browser.opened == [
        (f"{YAHOO}/nba/252098/2?date=2026-10-29#pickandroll-il", 30.0),
        (f"{YAHOO}/nba/252098/addplayer?apid=222#pickandroll-moves", 12.0),
        (f"{YAHOO}/nba/252098/addplayer?apid=111#pickandroll-moves", 12.0),
    ]
    assert passes[:3] == [
        {"league": "252098", "entry": "e2"},
        {"league": "252098", "entry": "e2"},
        {"league": "252098", "entry": "e1"},
    ]
    assert passes[-1] == {
        "summary": "3 pages opened in 1 leagues, add pages opened by the pass after an IL stay: e2"
    }
    assert ctx.notes["il_stayed"] == ["e2"]
    step = report.find("moves")
    assert step.status == "ok" and step.data["stayed"] == ["e2"]
    assert step.data["plan"][0].endswith(
        "(30 s), then " + browser.opened[1][0] + " (12 s) if the tab stays"
    )


def test_a_signed_out_browser_opens_nothing_and_alerts(tmp_path):
    api = FakeAPI(due_answers())
    ctx = make_ctx(
        api,
        Clock("2026-10-29 07:50"),
        tmp_path,
        routine="morning",
        browser=FakeBrowser(signed=False),
    )
    report = run("morning", ctx, "http://api")
    assert (
        report.find("moves").status == "failed" and "not signed in" in report.find("moves").detail
    )
    assert report.alerts == ["the browser profile is signed out of yahoo"]
    assert "/autopilot/passes" not in " ".join(api.paths("POST"))


def test_evening_pass_stops_opening_at_22_58_and_names_the_unopened(tmp_path):
    many = [{"id": f"e{i}", "page": f"/nba/252098/addplayer?apid={i}"} for i in range(1, 6)]
    api = FakeAPI(
        due_answers()
        | {
            ("GET", "/seasons/252098/autopilot/moves/due"): (
                200,
                {"mode": "live", "stop": False, "entries": many, "il_first": []},
            ),
            ("POST", "/autopilot/passes"): (200, {"id": "p"}),
            ("POST", "/autopilot/passes/p/opening"): (200, {}),
            ("POST", "/autopilot/passes/p/done"): (200, {}),
            ("GET", "/seasons/252098/autopilot/moves"): (
                200,
                {"today": [{"trigger": "routine_evening", "outcome": "claimed"}]},
            ),
        }
    )
    clock = Clock("2026-10-29 22:57:40")  # 12 s a page: the second opening crosses 22:58
    browser = FakeBrowser(clock=clock)
    ctx = make_ctx(api, clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    assert len(browser.opened) == 2
    moves = report.find("moves")
    assert (
        moves.status == "ok"
        and "stopped at 22:58 with 3 entries unopened: e3, e4, e5" in moves.detail
    )
    assert moves.data["unopened"] == ["e3", "e4", "e5"]


def test_late_pass_resolves_only_the_leagues_it_opened_and_checks_the_light(tmp_path):
    status = {
        "leagues": [
            {
                "league": "252098",
                "yahoo": {"rows": [{"read_at": "2026-10-29T15:05:00-05:00"}]},
                "recommendations": {
                    "rows": [{"kind": "moves", "built_at": "2026-10-29T15:06:00-05:00"}]
                },
            },
            {
                "league": "230585",
                "yahoo": {"rows": [{"read_at": "2026-10-29T15:05:00-05:00"}]},
                "recommendations": {
                    "rows": [{"kind": "moves", "built_at": "2026-10-29T05:30:00-05:00"}]
                },
            },
        ]
    }
    assert behind_the_read(status, PUBLIC) == ["230585"]
    assert behind_the_read(status, ["999"]) == ["999 (no status row)"]

    api = FakeAPI(
        due_answers()
        | {
            ("GET", "/seasons/status"): (200, status),
            ("POST", "/autopilot/passes"): (200, {"id": "p"}),
            ("POST", "/autopilot/passes/p/opening"): (200, {}),
            ("POST", "/autopilot/passes/p/done"): (200, {}),
            ("GET", "/seasons/252098/autopilot"): (
                200,
                {"today": [{"trigger": "routine_late", "outcome": "would_set"}]},
            ),
            ("GET", "/seasons/230585/autopilot"): (
                200,
                {"today": [{"trigger": "routine_late", "outcome": "would_set"}]},
            ),
            ("GET", "/seasons/252098/autopilot/moves"): (200, {"today": []}),
            ("GET", "/seasons/230585/autopilot/moves"): (200, {"today": []}),
        }
    )
    clock = Clock("2026-10-29 15:02")
    ctx = make_ctx(api, clock, tmp_path, routine="late", browser=FakeBrowser(clock=clock))
    report = run("late", ctx, "http://api")
    assert report.find("lineup").status == "ok"  # both leagues' team pages (lineup steps open)
    resolved = [p for p in api.paths("GET") if p.endswith("/moves") and "autopilot" not in p]
    assert resolved == ["/seasons/252098/moves", "/seasons/230585/moves"]
    assert report.find("resolve").status == "ok"
    assert report.find("status").status == "failed" and "230585" in report.find("status").detail


# --------------------------------------------------------------------------- the Monday
def test_monday_runs_the_scripts_in_order_and_posts_only_real_output(tmp_path):
    answers = {
        ("season.py", "record"): (
            0,
            "252098 week 2: recorded (pages: taken 7)\n230585 week 2: failed (502): yahoo\n",
            "",
        ),
        ("season.py", "scorecard"): (0, "## Scorecard, week 2\n\n| league |\n", ""),
        ("season.py", "monday"): (
            0,
            "## Monday 2026-10-26\n\nno change\n",
            "2026-10-26: K1 kept\n",
        ),
    }

    def run_script(args):
        scripts.append(list(args))
        if args[:2] == ["season.py", "record"] and len(args) > 2 and args[2] != "--all":
            return 0, f"{args[2]} week 2: recorded\n", ""
        return answers.get(tuple(args[:2]), (0, "", ""))

    scripts: list[list[str]] = []
    api = FakeAPI(base_answers())
    ctx = make_ctx(api, Clock("2026-10-26 06:03"), tmp_path, routine="monday")
    ctx.run_script = run_script
    report = run("monday", ctx, "http://api")
    names = [a[1] for a in scripts if a[0] == "season.py"]
    assert names == ["record", "record", "scorecard", "monday"]  # the 5xx league once more
    assert ctx.notes["_sleeps"].calls == [60]
    posts = ctx.notes["_posts"]
    assert [p[0] for p in posts] == [127, 127]
    assert posts[0][1].startswith("## Scorecard, week 2") and posts[1][1].startswith("## Monday")
    assert report.find("record").status == "failed"  # a failed league is said as such
    assert report.find("monday").detail.startswith("2026-10-26: K1 kept | posted")
    assert api.paths("POST")[-1] == "/autopilot/queue/build"


def test_monday_scorecard_without_a_week_and_a_refused_step_post_nothing(tmp_path):
    def run_script(args):
        if args[1] == "scorecard":
            return 0, "## Scorecard\n\nNo week is recorded yet.\n", ""
        if args[1] == "monday":
            return 1, "", "2026-10-26: refused: no week recorded\n"
        return 0, "252098 week 1: unchanged\n", ""

    ctx = make_ctx(FakeAPI(base_answers()), Clock("2026-10-26 06:03"), tmp_path, routine="monday")
    ctx.run_script = run_script
    report = run("monday", ctx, "http://api")
    assert report.find("scorecard").detail == "no week recorded, nothing posted"
    assert report.find("monday").status == "skipped" and "refused" in report.find("monday").detail
    assert ctx.notes["_posts"] == []


# --------------------------------------------------------------------------- the script
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "routine.py"


def test_the_script_refuses_outside_the_window_and_writes_nothing(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("routine_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(
        [
            "morning",
            "--api",
            "http://127.0.0.1:9",
            "--data",
            str(tmp_path),
            "--now",
            "2026-10-29 03:00",
        ]
    )
    assert code == module.REFUSED
    assert "outside the morning window 07:45-14:30" in capsys.readouterr().out
    assert not (tmp_path / "routine").exists()


def test_the_script_reports_an_unreachable_api(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("routine_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(
        [
            "evening-build",
            "--api",
            "http://127.0.0.1:9",
            "--data",
            str(tmp_path),
            "--now",
            "2026-10-29 21:05",
            "--no-post",
        ]
    )
    assert code == module.UNREACHABLE
    out = capsys.readouterr().out
    assert "api: failed" in out and "unreachable" in out
    log = (
        json.loads((tmp_path / "routine" / "runs" / "2026-10-29-evening-build.json").read_text())
        if (tmp_path / "routine" / "runs").exists()
        else None
    )
    assert log is None  # an unreachable API writes no run log


def test_windows_cover_every_routine():
    assert set(WINDOWS) == {
        "daily",
        "morning",
        "late",
        "evening-build",
        "evening-pass",
        "monday",
        "signin",
    }
    o = Opening("252098", "moves", "u", 12.0)
    assert o.entry is None
