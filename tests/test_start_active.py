"""Yahoo's Start Active Players for the rest of the week (#215): the due route's need rule
(``no_run``, ``week_start``, ``roster_changed``, ``il_moved``), the league's log under
``start_active`` with the roster each run ran on, its checks, the pass record's counts, the
Queue's lines and the digest's words. Nothing here opens a page: the runs are the extension's,
faked.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.season import autopilot as qa
from pickandroll.sources.yahoo import public
from tests.test_moves_queue import DAY, PRIVATE, live_league, queued
from tests.test_season import LEAGUE, NOW, season_client, strategy_league

DUE = "/autopilot/start-active/due"
URL = f"/seasons/{LEAGUE}/autopilot/start-active"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def sa_body(**over) -> dict:
    body = {
        "day": "2026-10-21",
        "mode": "dry_run",
        "trigger": "routine_daily",
        "outcome": "would_start",
        "reasons": ["no_run"],
        "page": f"/nba/{LEAGUE}/4?date=2026-10-21",
        "controls": {"button": True, "interval": True, "locked": False},
        "extension": "0.9.0",
    }
    return {**body, **over}


def row(client, league: str = LEAGUE) -> dict | None:
    return next((r for r in client.get(DUE).json()["leagues"] if r["league"] == league), None)


def test_the_due_route_says_which_armed_leagues_want_a_run_and_why(client):
    strategy_league(client)
    r = row(client)
    # Never run: it is due, on today's team page, with my roster as last read.
    assert (r["need"], r["reasons"], r["last"]) == (True, ["no_run"], None)
    assert r["page"] == public.team_url(LEAGUE, 4, DAY) and r["team"] == 4
    assert r["week"] == {"start": "2026-10-19", "end": "2026-10-25"}
    roster = r["roster"]
    assert roster["players"] and roster["held"] == []
    # The private league never shows.
    assert row(client, PRIVATE) is None
    # A dry run that would start records the roster it ran on: nothing is due after it.
    assert client.post(URL, json=sa_body()).status_code == 200
    r = row(client)
    assert (r["need"], r["reasons"]) == (False, [])
    assert r["last"]["outcome"] == "would_start" and r["last"]["trigger"] == "routine_daily"
    # A roster the page showed before a claim landed: the claim's player is the change.
    k = roster["players"][0]
    before = {"players": roster["players"][1:], "held": []}
    assert client.post(URL, json=sa_body(roster=before)).status_code == 200
    r = row(client)
    assert (r["need"], r["reasons"]) == (True, ["roster_changed"])
    assert r["changes"] == {"added": [k], "dropped": [], "held": [], "returned": []}
    # Who is held counts too: a player now on the IL was active at the run.
    held = {"players": roster["players"], "held": [k]}
    assert client.post(URL, json=sa_body(roster=held)).status_code == 200
    assert row(client)["changes"] == {"added": [], "dropped": [], "held": [], "returned": [k]}
    # A run last week leaves the new week due, whatever the roster.
    assert client.post(URL, json=sa_body(day="2026-10-12")).status_code == 200
    assert row(client)["reasons"] == ["week_start"]
    assert client.post(URL, json=sa_body()).status_code == 200
    assert row(client)["need"] is False
    # A skip or a failure is not a run: the league stays as its last run left it.
    assert client.post(URL, json=sa_body(outcome="skipped", reason="no button")).status_code == 200
    assert row(client)["need"] is False
    # A live IL move landed since the run (#214) says so.
    later = (NOW + timedelta(minutes=5)).isoformat()
    ap.append_run(
        client.data_dir, LEAGUE, {"at": later, "mode": "live", "outcome": "moved"}, DAY, ap.IL
    )
    assert row(client)["reasons"] == ["il_moved"]


def test_a_league_switched_live_runs_again_and_stop_or_off_wants_none(client):
    strategy_league(client)
    assert client.post(URL, json=sa_body()).status_code == 200
    assert row(client)["need"] is False
    # The dry run's would-start pressed nothing: a live league has not run.
    live_league(client)
    r = row(client)
    assert (r["mode"], r["need"], r["reasons"]) == ("live", True, ["no_run"])
    started = sa_body(mode="live", outcome="started", message="6 lineups updated")
    assert client.post(URL, json=started).status_code == 200
    assert row(client)["need"] is False
    # Yahoo's "Already optimized" is a run as well.
    already = sa_body(mode="live", outcome="already", day="2026-10-12", message="Already optimized")
    assert client.post(URL, json=already).status_code == 200
    assert row(client)["reasons"] == ["week_start"]
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    d = client.get(DUE).json()
    assert d["stop"] is True and d["reason"] == "STOP is on (data/autopilot/STOP)"
    assert all(r["need"] is False for r in d["leagues"])
    stop.unlink()
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert row(client) is None


def test_the_log_refuses_a_crumb_a_dry_press_a_live_would_and_the_private_league(client):
    strategy_league(client)

    def refused(body, code=409, url=URL):
        r = client.post(url, json=body)
        assert r.status_code == code, r.text
        return r.json()["detail"]

    assert "crumb" in refused(sa_body(controls={"crumb": "x"}), 422)
    refused(sa_body(outcome="optimized"), 422)
    refused(sa_body(trigger="monday"), 422)
    assert refused(sa_body(outcome="started")) == "a dry run presses nothing"
    assert refused(sa_body(outcome="already")) == "a dry run presses nothing"
    assert (
        refused(sa_body(mode="live", outcome="started"))
        == "a live run in a league that is not live"
    )
    live_league(client)
    assert "never says would" in refused(sa_body(mode="live"))
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert refused(sa_body(mode="live", outcome="started")).startswith("STOP is on")
    assert client.post(URL, json=sa_body(mode="live", outcome="stopped")).status_code == 200
    stop.unlink()
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert refused(sa_body()) == qa.OFF
    priv = f"/seasons/{PRIVATE}/autopilot/start-active"
    assert refused(sa_body(), url=priv) == qa.PRIVATE


def test_the_runs_go_to_the_open_moves_pass_the_queue_and_the_card(client):
    q = queued(client)
    on = [e["id"] for e in q["entries"] if e["queued"]]
    r = client.post(
        "/autopilot/passes",
        json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE], "entries": on},
    )
    assert r.status_code == 200 and r.json()["start_active"] is None
    assert client.post(URL, json=sa_body(trigger="routine")).status_code == 200
    p = client.get("/autopilot/queue").json()["active"]
    assert p["start_active"] == {
        "would_start": 1,
        "started": 0,
        "already": 0,
        "skipped": 0,
        "failed": 0,
    }
    # The league is not done by it: its add pages come after.
    assert p["leagues"]["done"] == 0 and sum(p["results"].values()) == 0
    # The day's queue and the league's card read the runs from the log.
    q = client.get("/autopilot/queue").json()
    assert q["start_active"][LEAGUE]["outcome"] == "would_start"
    assert q["start_active"][LEAGUE]["roster"]["players"]
    card = client.get(f"/seasons/{LEAGUE}/autopilot/moves").json()
    assert [r["outcome"] for r in card["start_active_today"]] == ["would_start"]
    # The 05:00 daily opens no pass: its run is logged and goes to none.
    assert client.post(URL, json=sa_body(outcome="skipped", reason="no button")).status_code == 200
    assert client.get("/autopilot/queue").json()["active"]["start_active"]["skipped"] == 0


def test_the_digest_counts_the_leagues_it_ran_in_and_names_a_failure(client):
    queued(client)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    assert client.post(URL, json=sa_body()).status_code == 200
    failed = sa_body(outcome="failed", message="An error occurred, please try again")
    assert client.post(URL, json=failed).status_code == 200
    lines = client.get("/flags/digest").json()["moves_executor"]
    assert lines[0].endswith(
        "0 would be claimed, 0 skipped, 0 failed, Start Active would run in 1."
    )
    assert lines[1] == (
        f"- League {LEAGUE}: moves Wed Start Active failed (An error occurred, please try again)"
    )
