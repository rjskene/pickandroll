"""The read of one pending claim's page (#345 step 0): the due route (one public league with an
open placed claim, never the private one, nothing once a read is on file or under STOP), the
read's route (names and words only: a value, a query, a crumb or any other key refused; never
the private league) and the evening pass's opening. Nothing here opens a page."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_queue
from pickandroll.routine.routines import run
from pickandroll.routine.steps import claim_page_plan
from pickandroll.sources.yahoo import public
from tests.test_moves_queue import DAY, PRIVATE
from tests.test_routine import Clock, FakeAPI, FakeBrowser, due_answers, make_ctx
from tests.test_season import LEAGUE, season_client

DUE = "/autopilot/claim-page/due"
URL = f"/seasons/{LEAGUE}/autopilot/claim-page"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def put_queue(client, day, *entries: dict) -> None:
    path = season_queue.queue_path(client.data_dir, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": day.isoformat(), "entries": list(entries)}))


def claim(league: str = LEAGUE, **over) -> dict:
    return {
        "id": f"{league}:6038:6733",
        "league": league,
        "add": 6038,
        "drop": 6733,
        "outcome": "claimed",
        "bid_placed": 1,
        **over,
    }


def read_body(**over) -> dict:
    body = {
        "trigger": "routine_evening",
        "read_at": "2026-10-21T22:41:00-05:00",
        "claim": "4_6038_6733",
        "path": f"/nba/{LEAGUE}/4/viewwaiver",
        "heading": "Waiver Claim",
        "notes": ["Your claim is pending"],
        "forms": [
            {
                "id": "claim-form",
                "name": None,
                "method": "post",
                "action": f"/nba/{LEAGUE}/4/viewwaiver",
                "fields": [{"tag": "input", "type": "hidden", "name": "crumb", "id": None}],
                "controls": [
                    {
                        "tag": "input",
                        "type": "submit",
                        "name": "cancel",
                        "id": None,
                        "text": "Cancel Claim",
                        "path": None,
                    }
                ],
            }
        ],
        "controls": [],
        "extension": "0.11.10",
    }
    return {**body, **over}


def test_the_read_is_due_in_a_public_league_with_an_open_placed_claim_and_never_again(client):
    d = client.get(DUE).json()
    assert (d["due"], d["reads"], d["fragment"]) == (False, 0, ap.CLAIM_PAGE_FRAGMENT)
    assert d["reason"] == "no claim placed and open in a public league"
    # A claim settled, one only queued, one too old, the private league's: none of them.
    put_queue(
        client,
        DAY - timedelta(days=1),
        claim(id="won", resolved={"outcome": "won"}),
        claim(id="queued", outcome="would_claim"),
        claim(PRIVATE, id="private"),
    )
    put_queue(client, DAY - timedelta(days=season_queue.PENDING_DAYS + 1), claim(id="old"))
    assert client.get(DUE).json()["due"] is False
    # An open claim placed yesterday: my team page there, which links it.
    put_queue(client, DAY, claim(id="open", drop=None))
    d = client.get(DUE).json()
    assert d["due"] is True and d["league"] == LEAGUE
    assert (d["claim"], d["add"], d["drop"]) == ("open", 6038, None)
    assert d["page"] == public.team_url(LEAGUE, 4, DAY)
    # Under STOP nothing is due.
    stop = client.data_dir / "autopilot" / "STOP"
    stop.write_text("")
    assert client.get(DUE).json()["due"] is False
    stop.unlink()
    # Once a read is on file, never again.
    r = client.post(URL, json=read_body())
    assert r.status_code == 200, r.text
    d = client.get(DUE).json()
    assert (d["due"], d["reads"], d["reason"]) == (False, 1, "a read of the claim page is on file")


def test_the_read_is_filed_with_its_league_and_names_and_words_only(client):
    r = client.post(URL, json=read_body())
    assert r.status_code == 200, r.text
    [filed] = client.get("/autopilot/claim-page").json()["reads"]
    assert filed["league"] == LEAGUE and filed["claim"] == "4_6038_6733"
    assert filed["forms"][0]["fields"] == [
        {"tag": "input", "type": "hidden", "name": "crumb", "id": None}
    ]
    assert filed["forms"][0]["controls"][0]["text"] == "Cancel Claim"
    # A second read is kept beside the first, never over it.
    assert client.post(URL, json=read_body(heading="again")).status_code == 200
    assert [x["heading"] for x in ap.claim_page_reads(client.data_dir)] == ["Waiver Claim", "again"]


@pytest.mark.parametrize(
    "bad",
    [
        # A field's value, under any key.
        {"forms": [{"fields": [{"tag": "input", "name": "faab", "value": "3"}]}]},
        {"controls": [{"tag": "button", "text": "Back", "value": "1"}]},
        # A query or a fragment in a path.
        {"path": f"/nba/{LEAGUE}/4/viewwaiver?claim_id=4_6038_6733"},
        {"forms": [{"action": f"/nba/{LEAGUE}/4/viewwaiver?crumb=abc"}]},
        {"controls": [{"tag": "a", "text": "Cancel", "path": "/cancel#x"}]},
        # The crumb, as a key anywhere.
        {"crumb": "abc"},
        {"forms": [{"crumb": "abc"}]},
        # Any other key, and another trigger.
        {"html": "<html></html>"},
        {"trigger": "panel"},
    ],
)
def test_a_read_carrying_a_value_a_query_a_crumb_or_another_key_is_refused(client, bad):
    assert client.post(URL, json=read_body(**bad)).status_code == 422
    assert ap.claim_page_reads(client.data_dir) == []


def test_the_private_league_is_never_read_and_an_unknown_league_is_not_found(client):
    r = client.post(f"/seasons/{PRIVATE}/autopilot/claim-page", json=read_body())
    assert r.status_code == 409
    r = client.post("/seasons/999999/autopilot/claim-page", json=read_body())
    assert r.status_code in (404, 422)
    assert ap.claim_page_reads(client.data_dir) == []


# --------------------------------------------------------------------------- the routine


def plan_of(answer, tmp_path):
    api = FakeAPI({("GET", DUE): answer})
    ctx = make_ctx(api, Clock("2026-10-29 22:45"), tmp_path, routine="evening-pass")
    return claim_page_plan(ctx), ctx


def test_the_evening_pass_opens_my_team_page_with_the_reads_fragment_once_due(tmp_path):
    page = "https://basketball.fantasysports.yahoo.com/nba/252098/7?date=2026-10-29"
    due = {"due": True, "league": "252098", "page": page, "fragment": ap.CLAIM_PAGE_FRAGMENT}
    [o], _ = plan_of((200, due), tmp_path)
    assert (o.league, o.kind, o.url, o.wait_s) == (
        "252098",
        "claim_page",
        f"{page}#{ap.CLAIM_PAGE_FRAGMENT}",
        30.0,
    )
    # Not due, the route down, the private league, a page not the league's own: nothing.
    out, ctx = plan_of(
        (200, {"due": False, "reason": "a read of the claim page is on file"}), tmp_path
    )
    assert out == [] and ctx.notes["claim_page"] == "a read of the claim page is on file"
    out, ctx = plan_of((500, {}), tmp_path)
    assert out == [] and ctx.notes["claim_page"] == "due route answered 500"
    private = {**due, "league": "31822", "page": page.replace("252098", "31822")}
    assert plan_of((200, private), tmp_path)[0] == []
    other = {**due, "page": page.replace("252098", "230585")}
    assert plan_of((200, other), tmp_path)[0] == []


def test_the_evening_pass_reads_the_claim_page_after_its_claims(tmp_path):
    page = "https://basketball.fantasysports.yahoo.com/nba/252098/7?date=2026-10-29"
    api = FakeAPI(
        due_answers()
        | {
            ("GET", DUE): (
                200,
                {
                    "due": True,
                    "league": "252098",
                    "page": page,
                    "fragment": "pickandroll-claim-read",
                },
            ),
        }
    )
    clock = Clock("2026-10-29 22:45")
    browser = FakeBrowser(clock=clock)
    ctx = make_ctx(api, clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    assert browser.opened[-1] == (f"{page}#pickandroll-claim-read", 30.0)
    assert report.find("claim_page").status == "ok"
    # Nothing due: the step says so and opens nothing.
    api = FakeAPI(due_answers() | {("GET", DUE): (200, {"due": False, "reason": "not due"})})
    clock = Clock("2026-10-29 22:45")
    browser = FakeBrowser(clock=clock)
    ctx = make_ctx(api, clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    assert not any("claim-read" in u for u, _ in browser.opened)
    assert report.find("claim_page").detail == "nothing to open"
