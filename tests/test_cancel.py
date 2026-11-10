"""A pending claim's cancel on Yahoo (#345 PR 2): the cancels due (a waiver claim placed, open,
judged again ``cancel`` by today's build, its cancel never run live), never in the private
league, with the executor off or under STOP; the run's log (a dry run presses nothing, a live
run only where the league is live and its guard holds, the claim the queue's own); a live
press's record on the entry, ``cancelled`` resolving it as lapsed; the digest's and the queue's
lines; and the evening pass opening the cancels before its claims. Nothing here opens a page."""

from __future__ import annotations

import inspect
import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_queue
from pickandroll.routine import routines
from pickandroll.routine.routines import run
from pickandroll.routine.steps import cancel_plan
from pickandroll.season import autopilot as qa
from pickandroll.sources.yahoo import public
from tests.test_moves_queue import DAY, PRIVATE, live_league
from tests.test_routine import Clock, FakeAPI, FakeBrowser, due_answers, make_ctx
from tests.test_season import LEAGUE, season_client

ALL = "/autopilot/cancels/due"
DUE = f"/seasons/{LEAGUE}/autopilot/cancels"
LOG = f"/seasons/{LEAGUE}/autopilot/cancel"
YESTERDAY = DAY - timedelta(days=1)
ENTRY = f"{YESTERDAY.isoformat()}:{LEAGUE}:6038:6733"
CLAIM = "4_6038_6733"
#: Today's build's verdict (the clock is 2026-10-21 13:00 CDT), and yesterday's.
TODAY_AT = "2026-10-21T09:00:00-05:00"
OLD_AT = "2026-10-20T21:00:00-05:00"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def verdict(v: str | None = qa.CANCEL, at: str = TODAY_AT) -> dict:
    return {"at": at, "verdict": v, "reason": "with 6219 back his comeback would drop 6038"}


def claim(league: str = LEAGUE, **over) -> dict:
    return {
        "id": ENTRY.replace(LEAGUE, league),
        "league": league,
        "add": 6038,
        "drop": 6733,
        "outcome": "claimed",
        "bid_placed": 2,
        "rejudge": verdict(),
        **over,
    }


def put_queue(client, day, *entries: dict) -> None:
    path = season_queue.queue_path(client.data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": day.isoformat(), "entries": list(entries)}))


def entry_of(client, day=YESTERDAY, entry=ENTRY) -> dict:
    q = season_queue.read(client.data_dir, day) or {}
    return next(e for e in q["entries"] if e["id"] == entry)


def body(**over) -> dict:
    return {
        "day": DAY.isoformat(),
        "mode": "dry_run",
        "trigger": "routine_evening",
        "outcome": "would_cancel",
        "reason": None,
        "entry": ENTRY,
        "add": 6038,
        "drop": 6733,
        "claim": CLAIM,
        "page": f"/nba/{LEAGUE}/4/viewwaiver",
        "controls": {"action": f"/nba/{LEAGUE}/4/editwaiver", "cancel": 1},
        "extension": "0.11.11",
        **over,
    }


# --------------------------------------------------------------------------- the cancels due
def test_a_claim_judged_cancel_by_todays_build_is_due_with_its_yahoo_id(client):
    d = client.get(DUE).json()
    assert (d["cancels"], d["reason"], d["fragment"], d["team"]) == (
        [],
        "no claim to cancel",
        ap.CANCEL_FRAGMENT,
        4,
    )
    put_queue(
        client,
        YESTERDAY,
        claim(),
        # Settled, kept, judged by an older build, not judged, a free agent added, another's.
        claim(id="won", resolved="won"),
        claim(id="keep", rejudge=verdict(qa.KEEP)),
        claim(id="old", rejudge=verdict(at=OLD_AT)),
        claim(id="lapsed", rejudge=verdict(None)),
        claim(id="added", outcome="added"),
        claim(id="ran", cancel={"outcome": "not_cancelled", "at": TODAY_AT}),
        claim(PRIVATE),
    )
    d = client.get(DUE).json()
    assert d["reason"] is None and d["mode"] == "dry_run"
    assert d["cancels"] == [
        {
            "entry": ENTRY,
            "add": 6038,
            "drop": 6733,
            "bid": 2,
            "reason": "with 6219 back his comeback would drop 6038",
            "verdict_at": TODAY_AT,
            "claim": CLAIM,
        }
    ]
    # An open spot's claim is <team>_<add>_0.
    put_queue(client, DAY, claim(id=f"{DAY.isoformat()}:{LEAGUE}:7001:-", add=7001, drop=None))
    assert [c["claim"] for c in client.get(DUE).json()["cancels"]] == [CLAIM, "4_7001_0"]
    # The evening pass's list: my team page in each league with a cancel.
    a = client.get(ALL).json()
    assert a["leagues"] == [
        {
            "league": LEAGUE,
            "mode": "dry_run",
            "page": public.team_url(LEAGUE, 4, DAY),
            "cancels": [ENTRY, f"{DAY.isoformat()}:{LEAGUE}:7001:-"],
        }
    ]


def test_nothing_is_due_under_stop_with_the_executor_off_or_in_the_private_league(client):
    put_queue(client, YESTERDAY, claim(), claim(PRIVATE))
    stop = client.data_dir / "autopilot" / "STOP"
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.get(DUE).json()["cancels"] == []
    assert client.get(ALL).json()["leagues"] == []
    stop.unlink()
    d = client.get(f"/seasons/{PRIVATE}/autopilot/cancels").json()
    assert (d["cancels"], d["reason"]) == ([], qa.PRIVATE)
    assert [r["league"] for r in client.get(ALL).json()["leagues"]] == [LEAGUE]
    assert client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"}).status_code == 200
    d = client.get(DUE).json()
    assert (d["cancels"], d["reason"]) == ([], qa.OFF)
    assert client.get(ALL).json()["leagues"] == []


# --------------------------------------------------------------------------- the run's log
def test_a_dry_run_is_logged_and_never_touches_the_entry(client):
    put_queue(client, YESTERDAY, claim())
    r = client.post(LOG, json=body())
    assert r.status_code == 200, r.text
    [line] = ap.cancel_lines(client.data_dir, LEAGUE, DAY)
    assert (line["outcome"], line["claim"], line["entry"]) == ("would_cancel", CLAIM, ENTRY)
    assert "cancel" not in entry_of(client) and "resolved" not in entry_of(client)
    # A dry run presses nothing: it never says it cancelled.
    assert client.post(LOG, json=body(outcome="cancelled")).status_code == 409
    # Still due: a dry run is not a press.
    assert len(client.get(DUE).json()["cancels"]) == 1


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"mode": "live", "outcome": "cancelled"}, "not live"),
        ({"entry": f"{YESTERDAY.isoformat()}:{LEAGUE}:9:9"}, "not an open claim"),
        ({"add": 6039}, "another add or drop"),
        ({"claim": "5_6038_6733"}, "is 4_6038_6733"),
        ({"entry": None}, "not an open claim"),
    ],
)
def test_a_run_the_executor_should_not_have_made_is_refused(client, over, why):
    put_queue(client, YESTERDAY, claim())
    r = client.post(LOG, json=body(**over))
    assert r.status_code == 409 and why in r.json()["detail"]
    assert ap.cancel_lines(client.data_dir, LEAGUE, DAY) == []


def test_would_cancel_needs_a_cancel_due_now(client):
    put_queue(client, YESTERDAY, claim(rejudge=verdict(at=OLD_AT)))
    r = client.post(LOG, json=body())
    assert r.status_code == 409 and "not due a cancel" in r.json()["detail"]
    # A skip is taken: it says why nothing was pressed.
    assert (
        client.post(LOG, json=body(outcome="skipped", reason="not in the box")).status_code == 200
    )


@pytest.mark.parametrize(
    "bad",
    [{"crumb": "abc"}, {"controls": {"crumb": "abc"}}, {"html": "<p>"}, {"trigger": "routine"}],
)
def test_a_run_carrying_the_crumb_another_key_or_another_trigger_is_refused(client, bad):
    put_queue(client, YESTERDAY, claim())
    assert client.post(LOG, json=body(**bad)).status_code == 422
    assert (
        client.post(LOG, json=body(page=f"/nba/{LEAGUE}/4/viewwaiver?crumb=x")).status_code == 422
    )


def test_the_private_league_is_never_logged(client):
    put_queue(client, YESTERDAY, claim(PRIVATE))
    r = client.post(
        f"/seasons/{PRIVATE}/autopilot/cancel",
        json=body(entry=ENTRY.replace(LEAGUE, PRIVATE), claim="7_6038_6733"),
    )
    assert r.status_code == 409
    stopped = body(outcome="stopped", entry=None, add=None, drop=None, claim=None)
    assert client.post(f"/seasons/{PRIVATE}/autopilot/cancel", json=stopped).status_code == 409


def test_a_live_cancel_resolves_the_claim_as_lapsed_and_is_never_pressed_again(client):
    put_queue(client, YESTERDAY, claim())
    live_league(client)
    r = client.post(
        LOG, json=body(mode="live", outcome="cancelled", landed={"team": {"path": "/x"}})
    )
    assert r.status_code == 200, r.text
    e = entry_of(client)
    assert e["cancel"]["outcome"] == "cancelled"
    assert (e["resolved"], e["outcome"]) == (ap.CANCEL_RESOLVED, "claimed")
    # No longer due, and never pressed again.
    assert client.get(DUE).json()["cancels"] == []
    again = client.post(LOG, json=body(mode="live", outcome="cancelled"))
    assert again.status_code == 409 and "never pressed again" in again.json()["detail"]
    # Settled as lapsed, it no longer counts as pending on the league's next build.
    q = season_queue.read(client.data_dir, YESTERDAY)
    assert season_queue.pending([q], LEAGUE) == []


@pytest.mark.parametrize("outcome", ["not_cancelled", "failed", "unconfirmed"])
def test_a_live_press_that_did_not_take_sticks_on_the_entry_and_leaves_the_claim_open(
    client, outcome
):
    put_queue(client, YESTERDAY, claim())
    live_league(client)
    r = client.post(LOG, json=body(mode="live", outcome=outcome, reason="still in the box"))
    assert r.status_code == 200, r.text
    e = entry_of(client)
    assert e["cancel"]["outcome"] == outcome and "resolved" not in e
    assert client.get(DUE).json()["cancels"] == []
    # A live skip clicked nothing: it leaves the claim due.
    put_queue(client, YESTERDAY, claim())
    assert client.post(LOG, json=body(mode="live", outcome="skipped")).status_code == 200
    assert "cancel" not in entry_of(client)
    assert len(client.get(DUE).json()["cancels"]) == 1


def test_stop_lets_a_run_say_only_that_it_stopped(client):
    put_queue(client, YESTERDAY, claim())
    stop = client.data_dir / "autopilot" / "STOP"
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.post(LOG, json=body()).status_code == 409
    stopped = body(outcome="stopped", entry=None, add=None, drop=None, claim=None)
    assert client.post(LOG, json=stopped).status_code == 200


# --------------------------------------------------------------------------- the digest and queue
def test_the_digest_says_cancelled_on_yahoo_or_cancel_by_hand_with_the_executors_word(client):
    put_queue(client, YESTERDAY, claim())
    by_hand = (
        f"- League {LEAGUE}: cancel by hand the pending claim add 6038, drop 6733, $2: "
        "with 6219 back his comeback would drop 6038"
    )
    assert ap.cancel_digest_lines(client.data_dir, DAY) == [by_hand]
    live_league(client)
    client.post(LOG, json=body(mode="live", outcome="not_cancelled", reason="still in the box"))
    assert ap.cancel_digest_lines(client.data_dir, DAY) == [
        by_hand + " (the executor's cancel: not_cancelled, still in the box)"
    ]
    put_queue(client, YESTERDAY, claim())
    client.post(LOG, json=body(mode="live", outcome="cancelled"))
    [line] = ap.cancel_digest_lines(client.data_dir, DAY)
    assert line.startswith(f"- League {LEAGUE}: cancelled on Yahoo at 13:00 CT the pending claim")
    assert line.endswith("$2: with 6219 back his comeback would drop 6038")
    # The next morning it still says so; the day after, it is gone.
    assert ap.cancel_digest_lines(client.data_dir, DAY + timedelta(days=1)) == [line]
    assert ap.cancel_digest_lines(client.data_dir, DAY + timedelta(days=2)) == []


def test_the_queue_shows_an_earlier_days_claim_with_its_live_cancel(client):
    put_queue(client, YESTERDAY, claim())
    path = season_queue.queue_path(client.data_dir, DAY)
    row = {
        "league": LEAGUE,
        "status": season_queue.QUEUED,
        "pending": [{"id": ENTRY, "add": 6038, "drop": 6733, "from": None, "rejudge": verdict()}],
    }
    path.write_text(json.dumps({"date": DAY.isoformat(), "leagues": [row], "entries": []}))
    live_league(client)
    client.post(LOG, json=body(mode="live", outcome="cancelled"))
    q = client.get("/autopilot/queue").json()
    [mine] = [r for r in q["leagues"] if r["league"] == LEAGUE]
    assert mine["pending"][0]["cancel"]["outcome"] == "cancelled"


# --------------------------------------------------------------------------- the routine
def plan_of(answer, tmp_path):
    api = FakeAPI({("GET", ALL): answer})
    ctx = make_ctx(api, Clock("2026-11-10 22:45"), tmp_path, routine="evening-pass")
    return cancel_plan(ctx), ctx


PAGE = "https://basketball.fantasysports.yahoo.com/nba/252098/7?date=2026-11-10"


def test_the_evening_pass_opens_my_team_page_once_per_cancel_never_the_private_league(tmp_path):
    rows = [
        {"league": "252098", "page": PAGE, "cancels": ["a", "b"]},
        {"league": "31822", "page": PAGE.replace("252098", "31822"), "cancels": ["c"]},
        {"league": "230585", "page": PAGE, "cancels": ["d"]},
    ]
    out, ctx = plan_of((200, {"leagues": rows, "fragment": ap.CANCEL_FRAGMENT}), tmp_path)
    assert [(o.league, o.kind, o.url, o.wait_s, o.entry) for o in out] == [
        ("252098", "cancel", f"{PAGE}#{ap.CANCEL_FRAGMENT}", 45.0, "a"),
        ("252098", "cancel", f"{PAGE}#{ap.CANCEL_FRAGMENT}", 45.0, "b"),
    ]
    assert ctx.notes["cancel_refused"] == ["31822", "230585"]
    out, ctx = plan_of((200, {"leagues": [], "reason": "no claim to cancel"}), tmp_path)
    assert out == [] and ctx.notes["cancel"] == "no claim to cancel"
    out, ctx = plan_of((500, {}), tmp_path)
    assert out == [] and ctx.notes["cancel"] == "due route answered 500"


def test_the_evening_pass_cancels_before_its_claims_and_the_daily_never_cancels(tmp_path):
    rows = [{"league": "252098", "page": PAGE, "cancels": ["a"]}]
    answers = due_answers() | {
        ("GET", ALL): (200, {"leagues": rows, "fragment": ap.CANCEL_FRAGMENT})
    }
    clock = Clock("2026-11-10 22:40")
    browser = FakeBrowser(clock=clock)
    ctx = make_ctx(FakeAPI(answers), clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    assert browser.opened[0] == (f"{PAGE}#{ap.CANCEL_FRAGMENT}", 45.0)
    assert report.find("cancel").status == "ok"
    # Only the evening pass cancels: the daily, the late pass and the pre-tip pass never do.
    src = inspect.getsource(routines)
    assert src.count("cancel_plan(ctx)") == 1
    for fn in (routines.daily, routines.late, routines.pretip):
        assert "cancel" not in inspect.getsource(fn)
