"""The record of a routine's execute pass while it runs (#201): the three calls, the logs' posts
given to the open pass, stale read rather than timed, and ``active`` and ``last_pass`` on the
day's queue. Nothing here opens a page: the posts are the extension's, faked.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_passes
from pickandroll.season import autopilot as qa
from tests.test_moves_queue import DAY, PRIVATE, check, pass_body, queued
from tests.test_season import LEAGUE, NOW, season_client

URL = "/autopilot/passes"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def lineup_body(**over) -> dict:
    body = {
        "day": "2026-10-21",
        "mode": "dry_run",
        "trigger": "routine",
        "outcome": "nothing_to_do",
    }
    return {**body, **over}


def record(client) -> list[dict]:
    return json.loads(season_passes.passes_path(client.data_dir, DAY).read_text())["passes"]


def test_a_pass_opens_once_a_kind_follows_the_routine_and_takes_the_logs_posts(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    ids = [e["id"] for e in on]
    # Open: the leagues in the order opened, the entries to check; none of the kind twice, but a
    # lineup pass beside a moves pass.
    r = client.post(
        URL, json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE], "entries": ids}
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["id"], p["end"], p["current"]) == ("2026-10-21:moves:1", None, None)
    assert p["leagues"] == {"done": 0, "total": 1, "order": [LEAGUE]}
    assert p["entries"] == {"done": 0, "total": len(ids)}
    again = client.post(URL, json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE]})
    assert (
        again.status_code == 409
        and again.json()["detail"] == "a moves pass is open: 2026-10-21:moves:1"
    )
    lineup = client.post(URL, json={"kind": "lineup", "trigger": "routine", "leagues": [LEAGUE]})
    assert lineup.status_code == 200 and lineup.json()["entries"] is None
    # The private league is never in a pass; an unknown league is not found.
    priv = client.post(URL, json={"kind": "moves", "trigger": "routine_late", "leagues": [PRIVATE]})
    assert priv.status_code == 409 and priv.json()["detail"] == qa.PRIVATE
    assert (
        client.post(
            URL, json={"kind": "moves", "trigger": "routine", "leagues": ["999"]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            URL, json={"kind": "moves", "trigger": "panel", "leagues": [LEAGUE]}
        ).status_code
        == 422
    )
    # Opening a league names it current; a league the pass did not name is refused.
    pid = p["id"]
    r = client.post(f"{URL}/{pid}/opening", json={"league": LEAGUE, "entry": ids[0]})
    assert r.status_code == 200 and r.json()["current"]["league"] == LEAGUE
    assert r.json()["current"]["entry"] == ids[0]
    assert client.post(f"{URL}/{pid}/opening", json={"league": PRIVATE}).status_code == 409
    got = client.get("/autopilot/queue").json()
    assert got["active"]["id"] == pid and got["active"]["current"]["league"] == LEAGUE
    assert got["last_pass"] is None
    # The extension's posts are given to the open pass of their kind; what they log and answer
    # is as it was.
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    skip = check(on[1], outcome="skipped", reason="page not read")
    r = client.post(url, json=pass_body([check(on[0]), skip], outcome="skipped"))
    assert r.status_code == 200, r.text
    assert set(r.json()) == {
        "at",
        "day",
        "mode",
        "trigger",
        "outcome",
        "reason",
        "entries",
        "extension",
    }
    logged = ap.read_log(client.data_dir, LEAGUE, DAY)["moves"]
    assert logged[-1] == r.json()
    active = client.get("/autopilot/queue").json()["active"]
    assert active["leagues"]["done"] == 1 and active["entries"] == {"done": 2, "total": len(ids)}
    assert active["results"] == {
        "would_claim": 1,
        "claimed": 0,
        "skipped": 1,
        "gone": 0,
        "failed": 0,
    }
    # Each entry counts by its latest post: the late read of the skipped one replaces it.
    assert client.post(url, json=pass_body([check(on[1])])).status_code == 200
    active = client.get("/autopilot/queue").json()["active"]
    assert active["results"]["would_claim"] == 2 and active["results"]["skipped"] == 0
    # A panel's post is the user's, never the routine's pass.
    panel = pass_body([check(on[0], outcome="skipped", reason="page not read")], trigger="panel")
    assert client.post(url, json=panel).status_code == 200
    assert client.get("/autopilot/queue").json()["active"]["results"]["would_claim"] == 2
    # A post the log refuses is not counted.
    assert client.post(url, json=pass_body([check(on[0], drop=1)])).status_code == 409
    assert client.get("/autopilot/queue").json()["active"]["entries"]["done"] == 2
    # The lineup pass takes the lineup posts, its own counts; the moves pass shows while both run.
    r = client.post(f"/seasons/{LEAGUE}/autopilot/lineup", json=lineup_body())
    assert r.status_code == 200, r.text
    lp = next(x for x in record(client) if x["kind"] == "lineup")
    assert season_passes.results(lp) == {
        "would_set": 0,
        "set": 0,
        "nothing_to_do": 1,
        "skipped": 0,
        "failed": 0,
    }
    assert client.get("/autopilot/queue").json()["active"]["kind"] == "moves"
    # Done closes it: the lineup pass shows, the moves pass is the day's last, and nothing more is
    # taken for it.
    r = client.post(f"{URL}/{pid}/done", json={"summary": "2 would claim"})
    assert r.status_code == 200 and (r.json()["end"], r.json()["current"]) == ("done", None)
    got = client.get("/autopilot/queue").json()
    assert got["active"]["kind"] == "lineup" and got["active"]["entries"] is None
    assert got["last_pass"]["id"] == pid and got["last_pass"]["summary"] == "2 would claim"
    assert got["last_pass"]["results"]["would_claim"] == 2
    for call in ("opening", "done"):
        r = client.post(f"{URL}/{pid}/{call}", json={"league": LEAGUE})
        assert r.status_code == 409 and r.json()["detail"] == f"the pass {pid} is done"
    assert client.post(f"{URL}/2026-10-21:moves:9/done").status_code == 404
    assert client.post(f"{URL}/not-a-pass/done").status_code == 404
    # With no moves pass open, a post is the log's alone.
    before = record(client)
    assert (
        client.post(url, json=pass_body([check(on[2])] if len(on) > 2 else [])).status_code == 200
    )
    assert record(client) == before
    # A second moves pass of the day is the next number.
    r = client.post(URL, json={"kind": "moves", "trigger": "routine_late", "leagues": [LEAGUE]})
    assert r.json()["id"] == "2026-10-21:moves:2" and r.json()["entries"]["total"] is None


def test_the_evening_routine_opens_a_moves_pass_and_its_posts_are_logged_and_taken(client):
    # #209: the evening routine's trigger word, through the record and the log.
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    lineup = {"kind": "lineup", "trigger": "routine_evening", "leagues": [LEAGUE]}
    r = client.post(URL, json=lineup)
    assert r.status_code == 409 and r.json()["detail"] == "the evening pass is a moves pass"
    r = client.post(
        URL,
        json={
            "kind": "moves",
            "trigger": "routine_evening",
            "leagues": [LEAGUE],
            "entries": [on[0]["id"]],
        },
    )
    assert r.status_code == 200, r.text
    assert (r.json()["trigger"], r.json()["entries"]["total"]) == ("routine_evening", 1)
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    r = client.post(url, json=pass_body([check(on[0])], trigger="routine_evening"))
    assert r.status_code == 200, r.text
    assert ap.read_log(client.data_dir, LEAGUE, DAY)["moves"][-1]["trigger"] == "routine_evening"
    active = client.get("/autopilot/queue").json()["active"]
    assert active["trigger"] == "routine_evening" and active["results"]["would_claim"] == 1
    # The queue's entry names the evening pass as its latest.
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert by[on[0]["id"]]["pass"]["trigger"] == "routine_evening"
    # A lineup run is never the evening's.
    r = client.post(
        f"/seasons/{LEAGUE}/autopilot/lineup", json=lineup_body(trigger="routine_evening")
    )
    assert r.status_code == 422


def test_a_pass_with_no_word_for_fifteen_minutes_reads_stale_and_the_next_open_writes_it(client):
    r = client.post(URL, json={"kind": "lineup", "trigger": "routine_late", "leagues": [LEAGUE]})
    pid = r.json()["id"]
    # Still open at fifteen minutes; stale after, ended fifteen minutes after its last word.
    client.app.state.seasons.clock = lambda: NOW + timedelta(minutes=15)
    assert client.get("/autopilot/queue").json()["active"]["id"] == pid
    client.app.state.seasons.clock = lambda: NOW + timedelta(minutes=16)
    got = client.get("/autopilot/queue").json()
    assert got["active"] is None
    assert (got["last_pass"]["end"], got["last_pass"]["ended"]) == (
        "stale",
        (NOW + timedelta(minutes=15)).isoformat(timespec="seconds"),
    )
    # Nothing is written by a read; the routine's calls are refused, a post is not taken.
    assert record(client)[0]["end"] is None
    for call in ("opening", "done"):
        r = client.post(f"{URL}/{pid}/{call}", json={"league": LEAGUE})
        assert (
            r.status_code == 409
            and r.json()["detail"] == f"the pass {pid} is stale: no word for 15 min"
        )
    assert client.post(f"/seasons/{LEAGUE}/autopilot/lineup", json=lineup_body()).status_code == 200
    assert season_passes.results(record(client)[0])["nothing_to_do"] == 0
    # The next open writes the stale end down and opens the next.
    r = client.post(URL, json={"kind": "lineup", "trigger": "routine_late", "leagues": [LEAGUE]})
    assert r.status_code == 200 and r.json()["id"] == "2026-10-21:lineup:2"
    first = record(client)[0]
    assert (first["end"], first["current"]) == ("stale", None)
    # Each word keeps it open: an opening at fourteen minutes holds it fifteen more.
    client.app.state.seasons.clock = lambda: NOW + timedelta(minutes=30)
    assert (
        client.post(f"{URL}/{r.json()['id']}/opening", json={"league": LEAGUE}).status_code == 200
    )
    client.app.state.seasons.clock = lambda: NOW + timedelta(minutes=44)
    assert client.get("/autopilot/queue").json()["active"]["id"] == r.json()["id"]


def test_a_record_that_does_not_read_leaves_the_queue_and_the_logs_answering(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    path = season_passes.passes_path(client.data_dir, DAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json")
    got = client.get("/autopilot/queue")
    assert got.status_code == 200 and (got.json()["active"], got.json()["last_pass"]) == (
        None,
        None,
    )
    r = client.post(URL, json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE]})
    assert r.status_code == 409 and "does not read" in r.json()["detail"]
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    assert client.post(url, json=pass_body([check(on[0])])).status_code == 200
    assert path.read_text() == "not json"
