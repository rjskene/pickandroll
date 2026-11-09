"""The private league's pre-tip pass (#355): its knobs, its slates from the day's tip-offs, the
due rule and the day file (a slate is done only once an attempt's solve and push both
completed; a lock skip, a crash or a failed push leaves it due), the push's text (names and
teams only, no Basketball Monster number), the routes, the routine against a fake API, the
browser profile's lock and the private push. Nothing here opens a page or reaches ntfy."""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from pickandroll.api import season_pretip as pt
from pickandroll.api.season_knobs import autopilot_dir
from pickandroll.api.season_queue import SETTINGS
from pickandroll.api.season_week import exports_in_force
from pickandroll.routine.chromium import ChromiumBrowser
from pickandroll.routine.lock import BrowserBusy, BrowserLock
from pickandroll.routine.push import ntfy_pusher
from pickandroll.routine.routines import (
    LOCK_WAIT_S,
    PRETIP_LOCK_WAIT_S,
    lock_wait_s,
    run,
)
from pickandroll.routine.steps import ready_browser
from tests.test_routine import Clock, FakeAPI, FakeBrowser, make_ctx
from tests.test_season import LEAGUE, season_client

DAY = date(2026, 11, 9)
#: 18:00, 18:30 and 21:00 Central (CST) on the 9th.
TIPS = {
    "LAL": "2026-11-10T00:00:00Z",
    "BOS": "2026-11-10T00:30:00Z",
    "GSW": "2026-11-10T03:00:00Z",
}
ON = {"enabled": True}


def at(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"2026-11-09T{hhmm}:00").replace(tzinfo=pt.CENTRAL)


def knobs(tmp_path, **over) -> None:
    path = autopilot_dir(tmp_path) / SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pretip": over}))


def attempt(slate="first", started="17:05", **over) -> pt.PretipRun:
    body = {"slate": slate, "started_at": at(started), "outcome": "done", **over}
    return pt.PretipRun(**body)


# --------------------------------------------------------------------------- knobs and slates
def test_the_knobs_default_to_off_and_take_only_well_formed_values(tmp_path):
    assert pt.settings(tmp_path) == pt.DEFAULTS and pt.DEFAULTS["enabled"] is False
    knobs(tmp_path, enabled=True, lead_min=45, late_gap_min=0, latest_start="25:00", late_slate=1)
    s = pt.settings(tmp_path)
    assert s["enabled"] is True and s["lead_min"] == 45
    # Out of range, a bad clock and a non-bool keep their defaults.
    assert s["late_gap_min"] == 150 and s["latest_start"] == "20:40" and s["late_slate"] is True
    (autopilot_dir(tmp_path) / SETTINGS).write_text("{not json")
    assert pt.settings(tmp_path) == pt.DEFAULTS


def test_the_slates_are_the_first_tip_off_and_the_first_one_past_the_gap():
    s = pt.slates(TIPS, pt.DEFAULTS)
    assert [x["slate"] for x in s] == ["first", "late"]
    first, late = s
    assert (first["tip"], first["start_at"], first["until"]) == (
        at("18:00").isoformat(),
        at("17:00").isoformat(),
        at("17:45").isoformat(),
    )
    assert late["tip"] == at("21:00").isoformat() and late["start_at"] == at("20:00").isoformat()
    assert [x["slate"] for x in pt.slates(TIPS, {**pt.DEFAULTS, "late_slate": False})] == ["first"]
    # No tip-off is far enough after the first: one slate.
    assert len(pt.slates(TIPS, {**pt.DEFAULTS, "late_gap_min": 200})) == 1
    assert pt.slates({"X": "not a time"}, pt.DEFAULTS) == []


# --------------------------------------------------------------------------- the due rule
def test_nothing_is_due_off_under_stop_without_a_copy_or_without_a_game(tmp_path):
    def reason(**kw):
        args = {"now": at("17:10"), "day": DAY, "tips": TIPS, "stopped": False, **kw}
        out = pt.due(tmp_path, **args)
        assert out["due"] is False
        return out["reason"]

    assert "off" in reason()
    knobs(tmp_path, **ON)
    assert "STOP" in reason(stopped=True)
    assert reason(tips=None) == "no schedule copy for today"
    assert reason(tips={}) == "no game today"


def test_a_slate_is_due_from_its_start_until_fifteen_minutes_before_its_tip(tmp_path):
    knobs(tmp_path, **ON)

    def due(hhmm):
        return pt.due(tmp_path, at(hhmm), DAY, TIPS, False)

    assert due("16:55")["reason"] == "the first slate starts at 17:00"
    d = due("17:00")
    assert d["due"] and d["slate"] == "first" and d["push_only"] is False
    assert d["tip"] == at("18:00").isoformat()
    # Past the first slate's window, the late one waits for its own start.
    d = due("17:45")
    assert not d["due"] and d["reason"] == (
        "the first slate's time passed at 17:45; the late slate starts at 20:00"
    )
    assert due("20:10")["slate"] == "late"
    # No full pass starts past the latest start, whatever the window says.
    assert due("20:41")["reason"].endswith("the late slate would start past 20:40")


def test_only_a_completed_solve_and_push_mark_a_slate_done(tmp_path):
    """The rule the day file states: a lock skip leaves the slate due, a solve whose push failed
    leaves it due as a push alone, and only the solve with its push marks it done."""
    knobs(tmp_path, **ON)
    pt.record(tmp_path, DAY, attempt(outcome="skipped", reason="the browser profile is in use"))
    d = pt.due(tmp_path, at("17:10"), DAY, TIPS, False)
    assert d["due"] and d["push_only"] is False
    body = pt.record(
        tmp_path,
        DAY,
        attempt(outcome="failed", reason="the push failed", solved_at=at("17:12")),
    )
    assert body["slates"]["first"]["done"] is False and body["rule"] == pt.RULE
    d = pt.due(tmp_path, at("17:15"), DAY, TIPS, False)
    assert d["due"] and d["push_only"] is True
    # A crash (an attempt never logged) changes nothing: the next tick finds the same.
    assert pt.due(tmp_path, at("17:20"), DAY, TIPS, False)["push_only"] is True
    moves = [{"add": 6038, "drop": 6733}]
    body = pt.record(
        tmp_path,
        DAY,
        attempt(started="17:20", solved_at=at("17:12"), pushed_at=at("17:21"), moves=moves),
    )
    assert body["slates"]["first"]["done"] is True
    assert len(body["slates"]["first"]["attempts"]) == 3
    d = pt.due(tmp_path, at("17:25"), DAY, TIPS, False)
    assert not d["due"] and d["reason"].startswith("the first slate is done")
    assert d["first_moves"] == [{"add": 6038, "drop": 6733}]
    # The file on disk says the rule in words.
    on_disk = json.loads(pt.day_path(tmp_path, DAY).read_text())
    assert on_disk["rule"] == pt.RULE and "a failed push leaves it due" in pt.RULE


def test_a_late_slate_whose_set_is_the_firsts_is_done_without_a_push(tmp_path):
    knobs(tmp_path, **ON)
    body = pt.record(tmp_path, DAY, attempt("late", "20:05", solved_at=at("20:09"), unchanged=True))
    assert body["slates"]["late"]["done"] is True
    # A solve alone, with neither a push nor the unchanged mark, is never done.
    assert pt.done_of({"solved_at": "x"}) is False and pt.done_of({"pushed_at": "x"}) is False


def test_a_first_slate_never_pushed_leaves_the_late_slate_to_push_the_same_set(tmp_path):
    """The first slate solved but its push failed until its time ran out: the user never got
    that set, so a late slate that solves the same one pushes it, never logs it unchanged."""
    knobs(tmp_path, **ON)
    moves = [{"add": 6038, "drop": 6733}]
    for started, solved in (("17:05", "17:12"), ("17:15", "17:16"), ("17:40", "17:16")):
        pt.record(
            tmp_path,
            DAY,
            attempt(started=started, outcome="failed", solved_at=at(solved), moves=moves),
        )
    d = pt.due(tmp_path, at("20:05"), DAY, TIPS, False)
    assert d["due"] and d["slate"] == "late" and d["first_moves"] is None
    # Pushed once, the first slate's set is the one the late slate compares against.
    pt.record(
        tmp_path,
        DAY,
        attempt(started="17:42", solved_at=at("17:16"), pushed_at=at("17:43"), moves=moves),
    )
    assert pt.due(tmp_path, at("20:05"), DAY, TIPS, False)["first_moves"] == moves


def test_a_push_alone_may_finish_past_the_latest_start(tmp_path):
    knobs(tmp_path, **ON)
    pt.record(tmp_path, DAY, attempt("late", "20:05", outcome="failed", solved_at=at("20:10")))
    d = pt.due(tmp_path, at("20:42"), DAY, TIPS, False)
    assert d["due"] and d["slate"] == "late" and d["push_only"] is True
    # A solve from before the slate's start is not this slate's: a full pass, not a push alone.
    pt.record(tmp_path, DAY, attempt("late", "19:50", outcome="failed", solved_at=at("19:55")))
    assert pt.due(tmp_path, at("20:20"), DAY, TIPS, False)["push_only"] is False


def test_the_run_body_takes_no_other_key():
    with pytest.raises(ValueError):
        pt.PretipRun(slate="first", started_at=at("17:05"), outcome="done", value=1.5)
    with pytest.raises(ValueError):
        pt.PretipRun(slate="evening", started_at=at("17:05"), outcome="done")


# --------------------------------------------------------------------------- the push's text
NAMES = {1: "Ayo Dosunmu", 2: "Jalen Smith", 3: "Kevin Love", 4: "Nikola Jovic"}
TEAMS = {1: "CHI", 2: "CHI", 3: None, 4: "MIA"}
EXPORTS = {
    "ros": {"file": "bbm_projections_2026-11-09.xls", "at": "2026-11-09T16:58:12-06:00"},
    "week_this": {"file": "bbm_week_this_2026-11-09.xls", "at": "2026-11-09T05:03:00-06:00"},
    "week_next": None,
}


def test_the_push_names_the_moves_and_the_inputs_and_no_number():
    moves = [
        {"add": 1, "drop": 2, "gain": 0.4123, "value": 12.75, "from": "2026-11-09"},
        {"add": 3, "drop": None, "gain": 0.2, "from": "2026-11-11"},
        {"add": 4, "drop": 2, "held": {"player": 1, "slot": "IL"}},
    ]
    text = pt.markdown("31822", DAY, moves, NAMES, TEAMS, EXPORTS, "solved")
    assert text.splitlines() == [
        "League 31822, pre-tip suggestions for Mon Nov 9:",
        "- add Ayo Dosunmu (CHI), drop Jalen Smith (CHI)",
        "- add Kevin Love, open spot, from Wed",
        "- add Nikola Jovic (MIA), drop Jalen Smith (CHI); first move Ayo Dosunmu (CHI) to IL",
        "Inputs (Basketball Monster, pulled): projections 16:58, this week 05:03, next week none.",
    ]
    for number in ("0.41", "12.75", "0.2"):
        assert number not in text
    assert pt.markdown("31822", DAY, [], NAMES, TEAMS, EXPORTS, "solved").splitlines()[1] == (
        "- no move recommended"
    )
    assert "- not solved: no suggestion" in pt.markdown("31822", DAY, [], {}, {}, {}, "timeout")


def test_the_exports_in_force_carry_their_pull_time_on_the_central_clock(tmp_path):
    ros = tmp_path / "bbm_projections_2026-11-09.xls"
    ros.write_text("x")
    stamp = datetime(2026, 11, 9, 22, 58, 12, tzinfo=UTC).timestamp()
    os.utime(ros, (stamp, stamp))
    (tmp_path / "bbm_sample_ros_totals.xls").write_text("x")
    out = exports_in_force(tmp_path, pt.CENTRAL)
    assert out["ros"] == {"file": ros.name, "at": "2026-11-09T16:58:12-06:00"}
    assert out["week_this"] is None and out["week_next"] is None


# --------------------------------------------------------------------------- the routes
@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


PRIVATE = "100002"


def test_the_due_route_reads_todays_tip_offs_and_names_the_private_league(client):
    d = client.get("/autopilot/pretip/due").json()
    assert d["due"] is False and "off" in d["reason"] and d["league"] == PRIVATE
    knobs(client.data_dir, **ON)
    assert client.get("/autopilot/pretip/due").json()["reason"] == "no schedule copy for today"
    copy = client.data_dir / "schedule" / "2026-10-21.json"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(json.dumps({"date": "2026-10-21", "tips": {"ATL": "2026-10-21T23:00:00Z"}}))
    # 13:00 Central: the first slate starts at 17:00 (CDT).
    assert client.get("/autopilot/pretip/due").json()["reason"] == "the first slate starts at 17:00"
    client.app.state.seasons.clock = lambda: datetime(2026, 10, 21, 22, 10, tzinfo=UTC)
    d = client.get("/autopilot/pretip/due").json()
    assert d["due"] and d["slate"] == "first" and d["league"] == PRIVATE


def test_the_runs_route_keeps_the_day_file_and_refuses_another_key(client):
    run_at = "2026-10-21T17:05:00-05:00"
    body = {"slate": "first", "started_at": run_at, "outcome": "skipped", "reason": "busy"}
    r = client.post("/autopilot/pretip/runs", json=body)
    assert r.status_code == 200 and r.json()["slates"]["first"]["done"] is False
    done = {**body, "outcome": "done", "solved_at": run_at, "pushed_at": run_at}
    r = client.post("/autopilot/pretip/runs", json=done)
    assert r.json()["slates"]["first"]["done"] is True
    assert pt.day_path(client.data_dir, date(2026, 10, 21)).is_file()
    assert client.post("/autopilot/pretip/runs", json={**body, "value": 1}).status_code == 422


def test_the_pretip_route_is_the_private_leagues_only(client):
    r = client.get(f"/seasons/{LEAGUE}/pretip")
    assert r.status_code == 409


def test_the_pretip_suggestions_are_the_solved_set_by_name(client, monkeypatch):
    service = client.app.state.seasons
    best = {
        "status": "solved",
        "set": [{"add": 1, "drop": 2, "gain": 0.31, "value": 4.5, "from": "2026-10-21"}],
    }
    monkeypatch.setattr(service, "best", lambda league, system, solve=False: best)

    def player(name, team):
        return SimpleNamespace(name=name, nba_team=team)

    problem = SimpleNamespace(
        roster=[(2, player("Jalen Smith", "CHI"))],
        held=[],
        candidates=[(1, player("Ayo Dosunmu", "CHI"))],
    )
    monkeypatch.setattr(service, "_built", lambda league, system: SimpleNamespace(problem=problem))
    out = client.get(f"/seasons/{PRIVATE}/pretip").json()
    assert out["status"] == "solved" and out["moves"] == [{"add": 1, "drop": 2}]
    assert "- add Ayo Dosunmu (CHI), drop Jalen Smith (CHI)" in out["markdown"]
    assert "0.31" not in out["markdown"] and "4.5" not in out["markdown"]
    assert set(out["exports"]) == {"ros", "week_this", "week_next"}


# --------------------------------------------------------------------------- the routine
TIP = "2026-11-09T18:00:00-06:00"


class ExportBrowser(FakeBrowser):
    """A browser whose exports land, and whose lock may be held by another run."""

    def __init__(self, tmp_path, clock, busy=None):
        super().__init__(clock=clock)
        self.tmp, self.busy, self.exported = tmp_path, busy, []

    def available(self):
        return self.busy is None

    @property
    def reason(self):
        return self.busy or ""

    def export(self, kind):
        self.exported.append(kind)
        path = self.tmp / f"{kind}.xls"
        path.write_text("x")
        return path


def pretip_answers(due=None, pretip=None, solve=200, runs=None):
    due = {
        "due": True,
        "league": "31822",
        "slate": "first",
        "tip": TIP,
        "push_only": False,
        "first_moves": None,
        **(due or {}),
    }
    out = {
        ("GET", "/seasons"): (200, []),
        ("GET", "/autopilot/pretip/due"): (200, due),
        ("GET", "/seasons/31822"): (200, {"num_teams": 2, "updated_at": "x", "fetched": {}}),
        ("GET", "/seasons/31822/lineup"): (200, {"needs": []}),
        ("GET", "/seasons/31822/moves"): (solve, {}),
        ("GET", "/seasons/31822/pretip"): (
            200,
            pretip
            or {
                "moves": [{"add": 1, "drop": 2}],
                "markdown": "League 31822, pre-tip suggestions for Mon Nov 9:\n- add A, drop B\n",
            },
        ),
    }
    kept = runs if runs is not None else []

    def log(body):
        kept.append(body)
        done = body.get("solved_at") and (body.get("pushed_at") or body.get("unchanged"))
        return 200, {"slates": {body["slate"]: {"done": bool(done)}}}

    out[("POST", "/autopilot/pretip/runs")] = log
    return out


def pretip_ctx(tmp_path, answers, browser=True, busy=None, push=(True, "pushed (200)"), at="17:10"):
    clock = Clock(f"2026-11-09 {at}")
    api = FakeAPI(answers)
    b = ExportBrowser(tmp_path, clock, busy=busy) if browser else None
    ctx = make_ctx(api, clock, tmp_path, routine="pretip", browser=b)
    ctx.run_script = lambda args: (0, f"saved data/bbm_{args[1]}_2026-11-09.xls", "")
    pushes: list[tuple[str, str]] = []

    def pusher(title, text):
        pushes.append((title, text))
        return push

    ctx.push = pusher if push is not None else None
    ctx.notes["_pushes"] = pushes
    return ctx, api, b


def statuses(report):
    return [(s.name, s.status) for s in report.steps]


def test_not_due_is_refused_with_nothing_opened_and_nothing_logged(tmp_path):
    answers = pretip_answers({"due": False, "reason": "the first slate starts at 17:00"})
    ctx, api, b = pretip_ctx(tmp_path, answers)
    report = run("pretip", ctx, "http://api")
    assert report.refused == "not due: the first slate starts at 17:00"
    assert b.opened == [] and b.exported == [] and ctx.notes["_pushes"] == []
    assert api.paths("POST") == []


def test_a_due_slate_pulls_reads_solves_pushes_and_logs_done(tmp_path):
    runs: list[dict] = []
    ctx, api, b = pretip_ctx(tmp_path, pretip_answers(runs=runs))
    report = run("pretip", ctx, "http://api")
    # The two exports only: rest of season and this week (a Monday: due).
    assert b.exported == ["ros", "week_this"]
    assert any("/nba/31822" in u for u, _ in b.opened)
    gets = api.paths("GET")
    assert gets.index("/seasons/31822/moves") < gets.index("/seasons/31822/pretip")
    names = [n for n, _ in statuses(report)]
    assert names.index("solve") < names.index("push") < names.index("day_file")
    ((title, text),) = ctx.notes["_pushes"]
    assert title == "pickandroll 31822 pre-tip, first slate (tip 18:00)"
    assert text.endswith("This pass: projections pulled; this week pulled.\n")
    (logged,) = runs
    assert logged["outcome"] == "done" and logged["solved_at"] and logged["pushed_at"]
    assert logged["moves"] == [{"add": 1, "drop": 2}]
    assert report.find("day_file").detail == "first slate done"


def test_a_sunday_pass_keeps_the_last_this_week_copy(tmp_path):
    ctx, _, b = pretip_ctx(tmp_path, pretip_answers())
    ctx.now = Clock("2026-11-08 17:10")
    run("pretip", ctx, "http://api")
    assert b.exported == ["ros"]
    ((_, text),) = ctx.notes["_pushes"]
    assert "this week not pulled (not due on a Sunday): the last copy stands" in text


def test_a_held_browser_skips_the_pass_and_leaves_the_slate_due(tmp_path):
    runs: list[dict] = []
    busy = "the browser profile is in use by the late routine, pid 1, since 17:00:00 (waited 900 s)"
    ctx, api, b = pretip_ctx(tmp_path, pretip_answers(runs=runs), busy=busy)
    report = run("pretip", ctx, "http://api")
    assert b.exported == [] and b.opened == [] and ctx.notes["_pushes"] == []
    assert "/seasons/31822/moves" not in api.paths("GET")
    assert report.find("browser").status == "skipped"
    (logged,) = runs
    assert logged["outcome"] == "skipped" and logged["reason"] == busy
    assert "solved_at" not in logged
    assert report.find("day_file").detail == "first slate still due"


def test_a_failed_push_is_logged_solved_and_still_due(tmp_path):
    runs: list[dict] = []
    ctx, _, _ = pretip_ctx(
        tmp_path, pretip_answers(runs=runs), push=(False, "the push answered 500")
    )
    report = run("pretip", ctx, "http://api")
    assert report.find("push").status == "failed"
    (logged,) = runs
    assert logged["outcome"] == "failed" and logged["solved_at"] and "pushed_at" not in logged
    assert report.find("day_file").detail == "first slate still due"


def test_a_failed_solve_pushes_nothing_and_stays_due(tmp_path):
    runs: list[dict] = []
    ctx, api, _ = pretip_ctx(tmp_path, pretip_answers(solve=504, runs=runs))
    run("pretip", ctx, "http://api")
    assert ctx.notes["_pushes"] == [] and "/seasons/31822/pretip" not in api.paths("GET")
    (logged,) = runs
    assert logged["outcome"] == "failed" and "solved_at" not in logged


def test_a_push_alone_opens_nothing(tmp_path):
    runs: list[dict] = []
    ctx, api, b = pretip_ctx(tmp_path, pretip_answers({"push_only": True}, runs=runs))
    run("pretip", ctx, "http://api")
    assert b.opened == [] and b.exported == []
    assert "/seasons/31822/moves" not in api.paths("GET")
    assert len(ctx.notes["_pushes"]) == 1 and runs[0]["pushed_at"]


def test_a_late_slate_with_the_first_slates_set_pushes_nothing_and_is_done(tmp_path):
    runs: list[dict] = []
    due = {
        "slate": "late",
        "tip": "2026-11-09T21:00:00-06:00",
        "first_moves": [{"add": 1, "drop": 2}],
    }
    ctx, _, _ = pretip_ctx(tmp_path, pretip_answers(due, runs=runs), at="20:05")
    report = run("pretip", ctx, "http://api")
    assert ctx.notes["_pushes"] == []
    assert runs[0]["unchanged"] is True and runs[0]["outcome"] == "done"
    assert report.find("day_file").detail == "late slate done"


def test_a_late_slate_pushes_the_same_set_when_the_first_was_never_pushed(tmp_path):
    runs: list[dict] = []
    due = {"slate": "late", "tip": "2026-11-09T21:00:00-06:00", "first_moves": None}
    ctx, _, _ = pretip_ctx(tmp_path, pretip_answers(due, runs=runs), at="20:05")
    report = run("pretip", ctx, "http://api")
    assert len(ctx.notes["_pushes"]) == 1
    assert runs[0]["pushed_at"] and not runs[0].get("unchanged")
    assert report.find("day_file").detail == "late slate done"


def test_a_due_for_another_league_fails_and_opens_nothing(tmp_path):
    ctx, _, b = pretip_ctx(tmp_path, pretip_answers({"league": "252098"}))
    report = run("pretip", ctx, "http://api")
    assert report.find("pretip_due").status == "failed" and b.opened == [] and b.exported == []


def test_without_a_push_channel_the_slate_stays_due(tmp_path):
    runs: list[dict] = []
    ctx, _, _ = pretip_ctx(tmp_path, pretip_answers(runs=runs), push=None)
    run("pretip", ctx, "http://api")
    assert runs[0]["outcome"] == "failed" and runs[0]["reason"] == "no push channel"


# --------------------------------------------------------------------------- the lineups (PR 3)
#: The public leagues of the routine tests' seasons list; 31822 is the private one.
LEAGUES = [
    {"league": "252098", "public": True},
    {"league": "230585", "public": True},
    {"league": "31822", "public": False},
]
YAHOO = "https://basketball.fantasysports.yahoo.com"


def lineup_answers(runs_at="2026-11-09T17:20:00-06:00", steps=None, **kw):
    """A due first slate with the two public leagues' lineup steps open, their pass record, the
    re-solve and the light, and each league's lineup run logged at ``runs_at``."""
    out = pretip_answers(**kw)
    out[("GET", "/seasons")] = (200, LEAGUES)
    out[("POST", "/autopilot/passes")] = (200, {"id": "p"})
    out[("POST", "/autopilot/passes/p/opening")] = (200, {})
    out[("POST", "/autopilot/passes/p/done")] = (200, {})
    rows = []
    for k in ("252098", "230585"):
        out[("GET", f"/seasons/{k}/lineup/steps")] = (
            200,
            {
                "mode": "live",
                "open": True,
                "date": "2026-11-09",
                "page": f"{YAHOO}/nba/{k}/2?date=2026-11-09",
                **(steps or {}),
            },
        )
        out[("GET", f"/seasons/{k}/moves")] = (200, {"sets": []})
        run_row = {"trigger": "routine_late", "outcome": "set", "at": runs_at}
        if steps and steps.get("reason"):
            run_row = {**run_row, "outcome": "nothing_to_do", "reason": steps["reason"]}
        out[("GET", f"/seasons/{k}/autopilot")] = (200, {"today": [run_row]})
        rows.append(
            {
                "league": k,
                "yahoo": {"rows": [{"read_at": "2026-11-09T17:18:00-06:00"}]},
                "recommendations": {
                    "rows": [{"kind": "moves", "built_at": "2026-11-09T17:22:00-06:00"}]
                },
            }
        )
    out[("GET", "/seasons/status")] = (200, {"leagues": rows})
    return out


def test_a_slate_sets_the_public_lineups_after_the_private_push(tmp_path):
    ctx, api, b = pretip_ctx(tmp_path, lineup_answers())
    report = run("pretip", ctx, "http://api")
    lineup = [u for u, _ in b.opened if "#pickandroll-lineup-late" in u]
    # The late pass's lineup step as it was: each public league's own page, its fragment and
    # its trigger, thirty seconds each; never the private league's.
    assert [u.split("/nba/")[1].split("/")[0] for u in lineup] == ["252098", "230585"]
    assert {w for u, w in b.opened if u in lineup} == {30.0}
    assert not any("/nba/31822/" in u and "lineup" in u for u in lineup)
    calls = [p for _, p in api.calls]
    assert calls.index("/seasons/31822/pretip") < calls.index("/seasons/252098/lineup/steps")
    assert len(ctx.notes["_pushes"]) == 1
    assert {
        (n, s) for n, s in statuses(report) if n in ("lineup", "resolve", "check", "status")
    } == {
        ("lineup", "ok"),
        ("resolve", "ok"),
        ("check", "ok"),
        ("status", "ok"),
    }
    assert not [n for n, s in statuses(report) if s == "failed"]


def test_the_check_counts_only_the_runs_of_this_slate(tmp_path):
    """The slates and the late pass share the late trigger: a run from before the slate began
    (the 15:00 pass's, or the first slate's) is not this slate's."""
    ctx, _, _ = pretip_ctx(tmp_path, lineup_answers(runs_at="2026-11-09T15:05:00-06:00"))
    report = run("pretip", ctx, "http://api")
    assert report.find("check").status == "failed"
    assert report.alerts == ["the pretip pass opened pages but no run was logged"]


def test_a_started_game_is_a_skip_with_its_reason_never_a_failure(tmp_path):
    """The late slate on a weekend: the early games began, so the steps leave out every group
    with a player whose tip-off passed (the executor never moves him) and say why; the pass
    opens the page, the extension logs nothing to do with that reason, and nothing fails."""
    started = {
        "steps": [],
        "skipped": [
            {"reason": "tip-off passed", "players": [6038, 6733], "steps": []},
        ],
        "reason": "every change waits on a game that began",
    }
    due = {"slate": "late", "tip": "2026-11-08T21:00:00-06:00"}
    ctx, _, b = pretip_ctx(
        tmp_path,
        lineup_answers(runs_at="2026-11-08T20:12:00-06:00", steps=started, due=due),
        at="20:05",
    )
    ctx.now = Clock("2026-11-08 20:05")
    report = run("pretip", ctx, "http://api")
    assert len([u for u, _ in b.opened if "#pickandroll-lineup-late" in u]) == 2
    check = report.find("check")
    assert check.status == "ok"
    assert all(
        "nothing_to_do (every change waits on a game that began)" in line
        for line in check.data["lines"]
    )
    assert not [n for n, s in statuses(report) if s == "failed"]


def test_once_every_game_began_the_steps_move_nobody_and_say_why(client):
    """The steps the extension runs, on the real route: when every team of the day's changes has
    tipped off (a late slate after the early games), nobody is moved, every group is a skip
    with the tip-off reason, and the day stays open (nothing fails, nothing closes)."""
    from tests.test_lineup_executor import benched_saturday

    benched_saturday(client)
    lineup = client.get(f"/seasons/{LEAGUE}/lineup").json()
    day = next(d for d in lineup["days"] if d["date"] == "2026-10-24")
    teams = {lineup["players"][str(k)]["nba_team"] for k in day["start"]}
    began = datetime(2026, 10, 21, 18, 0, tzinfo=UTC).isoformat()
    path = client.data_dir / "schedule" / "2026-10-24.json"
    body = json.loads(path.read_text())
    path.write_text(json.dumps({**body, "tips": dict.fromkeys(teams, began)}))
    s = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": "2026-10-24"}).json()
    assert s["open"] is True and s["steps"] == []
    assert s["skipped"] and all(g["reason"] == "tip-off passed" for g in s["skipped"])
    assert s["reason"] == "every change waits on a game that began"
    # Everyone was benched: each recommended starter is held where Yahoo has him, in a skip.
    assert set(day["start"]) <= {p for g in s["skipped"] for p in g["players"]}


def test_a_push_alone_and_a_held_browser_set_no_lineup(tmp_path):
    ctx, api, b = pretip_ctx(tmp_path, lineup_answers(due={"push_only": True}))
    run("pretip", ctx, "http://api")
    assert "/seasons/252098/lineup/steps" not in api.paths("GET")
    busy = "the browser profile is in use by the late routine, pid 1, since 17:00:00 (waited 900 s)"
    ctx, api, b = pretip_ctx(tmp_path, lineup_answers(), busy=busy)
    run("pretip", ctx, "http://api")
    assert "/seasons/252098/lineup/steps" not in api.paths("GET") and b.opened == []


def test_a_failed_solve_still_sets_the_public_lineups(tmp_path):
    runs: list[dict] = []
    ctx, _, b = pretip_ctx(tmp_path, lineup_answers(solve=504, runs=runs))
    run("pretip", ctx, "http://api")
    assert runs[0]["outcome"] == "failed" and ctx.notes["_pushes"] == []
    assert len([u for u, _ in b.opened if "#pickandroll-lineup-late" in u]) == 2


def late_answers(due):
    out = lineup_answers()
    out[("GET", "/autopilot/pretip/due")] = due
    out[("GET", "/autopilot/start-active/due")] = (200, {"stop": False, "leagues": []})
    for k in ("252098", "230585"):
        out[("GET", f"/seasons/{k}/autopilot/moves")] = (200, {"today": [], "entries": []})
    return out


def test_the_late_pass_leaves_todays_lineups_to_the_pretip_pass_only_while_it_is_on(tmp_path):
    on = {
        "due": False,
        "knobs": {**pt.DEFAULTS, "enabled": True},
        "slates": [
            {"slate": "first", "tip": "2026-11-09T18:00:00-06:00"},
            {"slate": "late", "tip": "2026-11-09T21:00:00-06:00"},
        ],
    }
    clock = Clock("2026-11-09 15:02")
    browser = FakeBrowser(clock=clock)
    api = FakeAPI(late_answers((200, on)))
    report = run("late", make_ctx(api, clock, tmp_path, routine="late", browser=browser), "x")
    assert report.find("lineup").status == "skipped"
    assert report.find("lineup").detail == (
        "the pre-tip pass sets today's lineups (pretip.enabled; slates first 18:00, late 21:00)"
    )
    assert not any("lineup/steps" in p for p in api.paths("GET"))
    assert not any("#pickandroll-lineup-late" in u for u, _ in browser.opened)
    # Off, with no game today, or a due route that does not answer: the late pass sets them.
    for due in (
        (200, {**on, "knobs": pt.DEFAULTS}),
        (200, {**on, "slates": []}),
        (500, {"detail": "boom"}),
    ):
        clock = Clock("2026-11-09 15:02")
        browser = FakeBrowser(clock=clock)
        api = FakeAPI(late_answers(due))
        ctx = make_ctx(api, clock, tmp_path, routine="late", browser=browser)
        report = run("late", ctx, "x")
        assert report.find("lineup").status == "ok"
        assert sum("#pickandroll-lineup-late" in u for u, _ in browser.opened) == 2


def test_a_missed_slate_fails_the_check_once_with_an_alert(tmp_path):
    knobs(tmp_path, **ON)
    pt.record(tmp_path, DAY, attempt(outcome="skipped", reason="the browser profile is in use"))
    d = pt.due(tmp_path, at("17:50"), DAY, TIPS, False)
    assert not d["due"] and d["missed"] == [
        {"slate": "first", "tip": at("18:00").isoformat(), "attempts": 1}
    ]
    runs: list[dict] = []
    answers = pretip_answers(
        {"due": False, "reason": d["reason"], "missed": d["missed"]}, runs=runs
    )
    ctx, _, b = pretip_ctx(tmp_path, answers, at="17:50")
    report = run("pretip", ctx, "http://api")
    assert report.refused is None and report.find("pretip_missed").status == "failed"
    assert report.alerts == [
        (
            "the pre-tip pass missed a slate: the first slate (tip 18:00) passed without its"
            " solve and push (1 attempts): today's lineups are the daily's, its suggestions the"
            " 05:00 ones"
        )
    ]
    assert b.opened == [] and b.exported == [] and runs[0]["outcome"] == "missed"
    # Logged missed, the slate is never named again; it is not done.
    body = pt.record(tmp_path, DAY, pt.PretipRun(**{**runs[0], "started_at": at("17:50")}))
    assert body["slates"]["first"]["missed"] is True and body["slates"]["first"]["done"] is False
    assert pt.due(tmp_path, at("17:55"), DAY, TIPS, False)["missed"] == []
    # A slate done on time is never missed.
    pt.record(tmp_path, DAY, attempt("late", "20:05", solved_at=at("20:06"), pushed_at=at("20:07")))
    assert pt.due(tmp_path, at("20:50"), DAY, TIPS, False)["missed"] == []


# --------------------------------------------------------------------------- the lock
class Ticks:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_a_second_run_waits_for_the_lock_then_is_told_who_holds_it(tmp_path):
    path = tmp_path / "routine" / "browser.lock"
    first = BrowserLock(path, "the late routine", 0)
    first.acquire()
    assert first.held and "the late routine, pid" in path.read_text()
    ticks = Ticks()
    second = BrowserLock(path, "the pretip routine", 12, sleep=ticks.sleep, clock=ticks)
    with pytest.raises(BrowserBusy) as err:
        second.acquire()
    assert ticks.sleeps == [5.0, 5.0, 2.0]
    assert "in use by the late routine, pid" in str(err.value) and "(waited 12 s)" in str(err.value)
    assert not second.held
    first.release()
    second.acquire()
    assert second.held and "the pretip routine" in path.read_text()
    second.release()


def test_a_busy_profile_is_never_launched_and_fails_the_step_with_an_alert(tmp_path):
    path = tmp_path / "browser.lock"
    holder = BrowserLock(path, "the daily routine", 0)
    holder.acquire()
    launched = []
    b = ChromiumBrowser(
        tmp_path / "profile",
        tmp_path / "ext",
        tmp_path / "downloads",
        sleep=lambda s: None,
        launch=lambda *a, **k: launched.append(a),
        lock=path,
        holder="the evening-pass routine",
        lock_wait_s=0,
    )
    assert b.available() is False and launched == []
    assert b.busy and "the daily routine" in b.busy
    clock = Clock("2026-11-09 22:41")
    ctx = make_ctx(FakeAPI(), clock, tmp_path, routine="evening-pass", browser=b)
    assert ready_browser(ctx, "pages", "yahoo", "would open 3 pages") is None
    assert ctx.report.find("pages").status == "failed"
    assert ctx.report.alerts == [f"the evening-pass routine could not have the browser: {b.busy}"]
    b.close()
    holder.release()


def test_the_lock_waits_by_routine_and_the_evening_pass_never_past_its_hard_stop():
    assert lock_wait_s("pretip", at("17:00")) == PRETIP_LOCK_WAIT_S == 900
    assert lock_wait_s("late", at("15:00")) == LOCK_WAIT_S == 1200
    assert lock_wait_s("evening-pass", at("22:40")) == 18 * 60
    assert lock_wait_s("evening-pass", at("22:00")) == LOCK_WAIT_S


# --------------------------------------------------------------------------- the push
class Answer:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_push_posts_to_the_users_topic_and_never_names_it(tmp_path):
    topic = "secret-topic-123"
    sent = []

    def opener(request, timeout):
        sent.append(request)
        return Answer(200)

    push = ntfy_pusher(tmp_path, opener=opener)
    assert push("t", "x") == (False, f"no topic in {tmp_path / 'ntfy_topic'}: nothing pushed")
    (tmp_path / "ntfy_topic").write_text(f"  {topic}\n")
    ok, detail = push("pickandroll 31822 pre-tip — first", "- add A\n")
    assert ok and detail == "pushed (200)"
    (request,) = sent
    assert request.full_url == f"https://ntfy.sh/{topic}" and request.data == b"- add A\n"
    assert request.get_header("Title") == "pickandroll 31822 pre-tip ? first"
    assert request.get_header("Markdown") == "yes"

    def broken(request, timeout):
        raise OSError("connection refused")

    assert ntfy_pusher(tmp_path, opener=broken)("t", "x") == (
        False,
        "the push failed: OSError: connection refused",
    )
    ok, detail = ntfy_pusher(tmp_path, opener=lambda r, timeout: Answer(429))("t", "x")
    assert (ok, detail) == (False, "the push answered 429")
    for d in (detail, push("t", "x")[1]):
        assert topic not in d


def test_a_long_push_is_cut_to_ntfys_limit(tmp_path):
    (tmp_path / "ntfy_topic").write_text("t")
    sent = []
    ntfy_pusher(tmp_path, opener=lambda r, timeout: sent.append(r) or Answer(200))("t", "x" * 9000)
    assert len(sent[0].data) == 3800


def test_a_push_is_cut_on_a_character_boundary(tmp_path):
    """A name whose letter straddles the cut loses the whole letter, never half of it: a body
    that is not UTF-8 is an attachment to ntfy."""
    (tmp_path / "ntfy_topic").write_text("t")
    sent = []
    push = ntfy_pusher(tmp_path, opener=lambda r, timeout: sent.append(r) or Answer(200))
    # The ć of Jokić is bytes 3800 and 3801: the cut at 3800 would split it.
    push("t", "x" * 3795 + "Jokić and Dončić")
    assert sent[0].data.decode("utf-8") == "x" * 3795 + "Joki"
    push("t", "x" * 3799 + "ć")
    assert sent[1].data.decode("utf-8") == "x" * 3799
