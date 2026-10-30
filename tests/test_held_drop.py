"""A churn's held drop on its own (#221 part 3): the due route's ``drop_first`` (each due churn's
held player H, on my team's drop page), the league's log under ``drop`` and its checks, the queue
entry's ``drop_run`` (never its outcome or place), the add held until H's drop landed and then due
with no drop behind its IL move, and the pass record's drop counts. Nothing here opens a page: the
runs are the extension's, faked.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_passes, season_queue
from pickandroll.season import autopilot as qa
from pickandroll.sources.yahoo import public
from tests.test_il_move import a_player, entries_by_id, il_body
from tests.test_moves_queue import (
    DAY,
    PRIVATE,
    check,
    live_league,
    pass_body,
    queued,
    strike,
)
from tests.test_season import LEAGUE, NOW, season_client

URL = f"/seasons/{LEAGUE}/autopilot/drop"
DUE = f"/seasons/{LEAGUE}/autopilot/moves/due"
HELD = 900101


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def churn(client, entry_id: str, h: int = HELD, y: int | None = None) -> None:
    """Make a day's queue entry a churn: drop held H from his IL slot, and (``y``) move the active
    player Y into it so the add has a spot."""

    def change(q):
        for e in q["entries"]:
            if e["id"] == entry_id:
                e.update(
                    drop=h,
                    basis=qa.CHURN,
                    held_drop={"player": h, "slot": "IL"},
                    held_move=None if y is None else {"player": y, "slot": "IL"},
                )
        return q

    season_queue.update(client.data_dir, DAY, change)


def drop_body(entry: str | None, player: int | None, **over) -> dict:
    body = {
        "day": "2026-10-21",
        "mode": "dry_run",
        "trigger": "routine",
        "outcome": "would_drop",
        "entry": entry,
        "player": player,
        "page": f"/nba/{LEAGUE}/4/dropplayer",
        "controls": {"stage": 1, "trigger": True, "name": True},
        "extension": "0.10.0",
    }
    return {**body, **over}


def refuse(client, body, code=409, url=URL) -> str:
    r = client.post(url, json=body)
    assert r.status_code == code, r.text
    return r.json()["detail"]


# --------------------------------------------------------------------------- drop_first
def test_a_due_churn_names_its_held_drop_first_and_its_add_waits_on_it(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    churn(client, on[0]["id"], y=k)
    # Nothing is due inside the window, so nothing is dropped first.
    assert client.get(DUE).json()["drop_first"] == []
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    d = client.get(DUE).json()
    assert d["drop_first"] == [
        {
            "entry": on[0]["id"],
            "player": HELD,
            "slot": "IL",
            "add": on[0]["add"],
            "page": public.drop_url(LEAGUE, 4),
        }
    ]
    # Its add is not on an add page, nor its IL move, until the drop landed: it waits.
    assert on[0]["id"] not in [e["id"] for e in d["entries"]] and d["il_first"] == []
    [h] = d["held"]
    assert (h["id"], h["waits"]["text"], h["waits"]["add"]) == (
        on[0]["id"],
        "waits for its held drop",
        HELD,
    )
    assert entries_by_id(client)[on[0]["id"]]["waits"]["text"] == "waits for its held drop"
    # A struck churn drops nobody; nor an off league, nor the private league.
    strike(client, on[0]["id"])
    assert client.get(DUE).json()["drop_first"] == []
    strike(client, on[0]["id"], undo=True)
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert client.get(DUE).json()["drop_first"] == []
    priv = client.get(f"/seasons/{PRIVATE}/autopilot/moves/due").json()
    assert priv["reason"] == qa.PRIVATE and priv["drop_first"] == []


# --------------------------------------------------------------------------- the log
def test_a_drop_run_is_logged_under_drop_and_a_live_drop_lets_the_add_go_on(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    churn(client, on[0]["id"], y=k)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    # A dry run says it would drop him: logged beside the passes, nothing on the queue.
    r = client.post(URL, json=drop_body(on[0]["id"], HELD))
    assert r.status_code == 200, r.text
    log = json.loads(
        (client.data_dir / "leagues" / LEAGUE / "autopilot" / "2026-10-21.json").read_text()
    )
    assert [x["outcome"] for x in log["drop"]] == ["would_drop"]
    by = entries_by_id(client)
    assert by[on[0]["id"]].get("drop_run") is None and by[on[0]["id"]]["outcome"] is None
    assert by[on[0]["id"]]["drop_pass"]["outcome"] == "would_drop"
    view = client.get(f"/seasons/{LEAGUE}/autopilot/moves").json()
    assert [r["outcome"] for r in view["drop_today"]] == ["would_drop"]
    assert next(e for e in view["entries"] if e["id"] == on[0]["id"])["drop_pass"]["player"] == HELD
    assert "a dry run drops nobody" in refuse(
        client, drop_body(on[0]["id"], HELD, outcome="dropped")
    )
    # Live: a run drops him or says why not, never that it would; a live skip stays off the entry.
    live_league(client)
    assert "never says would" in refuse(client, drop_body(on[0]["id"], HELD, mode="live"))
    skip = drop_body(on[0]["id"], HELD, mode="live", outcome="skipped", reason="no row")
    assert client.post(URL, json=skip).status_code == 200
    assert entries_by_id(client)[on[0]["id"]].get("drop_run") is None
    assert [x["entry"] for x in client.get(DUE).json()["drop_first"]] == [on[0]["id"]]
    # A claim with no drop before H's drop landed names another move than the queue's.
    claim = check({**on[0], "drop": None}, mode="live", outcome="claimed")
    body = pass_body([claim], mode="live", outcome="claimed")
    moves = f"/seasons/{LEAGUE}/autopilot/moves"
    assert "another move" in refuse(client, body, url=moves)
    assert "not an open-spot claim" in refuse(
        client,
        il_body(on[0]["id"], k, mode="live", outcome="moved"),
        url=f"/seasons/{LEAGUE}/autopilot/il",
    )
    dropped = drop_body(
        on[0]["id"], HELD, mode="live", outcome="dropped", message="You have successfully dropped"
    )
    assert client.post(URL, json=dropped).status_code == 200
    by = entries_by_id(client)
    assert by[on[0]["id"]]["drop_run"]["outcome"] == "dropped"
    assert (by[on[0]["id"]]["outcome"], by[on[0]["id"]]["rank"]) == (None, on[0]["rank"])
    assert by[on[0]["id"]]["waits"] is None
    # The add is due now, with no drop, behind Y's IL move; H is never dropped again.
    d = client.get(DUE).json()
    e = next(e for e in d["entries"] if e["id"] == on[0]["id"])
    assert e["drop"] is None and e["held_drop"] == {"player": HELD, "slot": "IL"}
    assert d["drop_first"] == [] and [x["entry"] for x in d["il_first"]] == [on[0]["id"]]
    assert refuse(client, dropped) == f"{HELD} was dropped already today"
    # The IL move and the claim with no drop are the queue's now.
    il = il_body(on[0]["id"], k, mode="live", outcome="moved", message="Roster saved")
    assert client.post(f"/seasons/{LEAGUE}/autopilot/il", json=il).status_code == 200
    # The claim with H as its drop is another move than the queue's now: H is gone.
    with_h = check({**on[0], "drop": HELD}, mode="live", outcome="claimed")
    assert "another move" in refuse(
        client, pass_body([with_h], mode="live", outcome="claimed"), url=moves
    )
    assert client.post(moves, json=body).status_code == 200
    assert entries_by_id(client)[on[0]["id"]]["outcome"] == "claimed"


def test_a_failed_or_unconfirmed_drop_holds_its_add_all_day_and_is_never_retried(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    churn(client, on[0]["id"])
    churn(client, on[1]["id"], h=HELD + 1)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    live_league(client)
    failed = drop_body(on[0]["id"], HELD, mode="live", outcome="failed", reason="the confirm")
    assert client.post(URL, json=failed).status_code == 200
    unsure = drop_body(on[1]["id"], HELD + 1, mode="live", outcome="unconfirmed")
    assert client.post(URL, json=unsure).status_code == 200
    d = client.get(DUE).json()
    assert d["drop_first"] == [] and d["entries"] == []
    assert {h["id"]: h["waits"]["text"] for h in d["held"]} == {
        on[0]["id"]: "its held drop failed: not claimed today",
        on[1]["id"]: "its held drop unconfirmed: not claimed today",
    }
    assert "never retried that day" in refuse(client, {**failed, "outcome": "dropped"})
    assert "never retried that day" in refuse(client, {**unsure, "outcome": "dropped"})
    # A rebuild keeps both as they are: H is never dropped twice.
    r = client.post("/autopilot/queue/build")
    assert r.status_code == 200, r.text
    by = entries_by_id(client)
    assert by[on[0]["id"]]["drop_run"]["outcome"] == "failed"
    assert by[on[1]["id"]]["drop_run"]["outcome"] == "unconfirmed"


def test_the_drop_log_refuses_a_crumb_another_drop_a_plain_move_and_a_struck_entry(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    out = next(e for e in q["entries"] if not e["queued"])
    churn(client, on[0]["id"])
    assert "crumb" in refuse(client, drop_body(on[0]["id"], HELD, controls={"crumb": "x"}), 422)
    refuse(client, drop_body(on[0]["id"], HELD, outcome="gone"), 422)
    assert "names its entry" in refuse(client, drop_body(None, HELD))
    assert "another drop" in refuse(client, drop_body(on[0]["id"], HELD + 1))
    assert "not a churn" in refuse(client, drop_body(on[1]["id"], on[1]["drop"] or 1))
    assert "not in the day's queue" in refuse(client, drop_body("2026-10-21:1:1:0", HELD))
    churn(client, out["id"])
    assert "struck or not queued" in refuse(client, drop_body(out["id"], HELD))
    strike(client, on[0]["id"])
    assert "struck or not queued" in refuse(client, drop_body(on[0]["id"], HELD))
    # A struck entry's drop may be reported skipped.
    skipped = drop_body(on[0]["id"], HELD, outcome="skipped", reason="struck")
    assert client.post(URL, json=skipped).status_code == 200
    strike(client, on[0]["id"], undo=True)
    # STOP: a run can only say it stopped, and a stopped run names nothing.
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert refuse(client, drop_body(on[0]["id"], HELD)).startswith("STOP is on")
    assert client.post(URL, json=drop_body(None, None, outcome="stopped")).status_code == 200
    stop.unlink()
    # A live run in a dry-run league, an off league and the private league are refused.
    assert "not live" in refuse(
        client, drop_body(on[0]["id"], HELD, mode="live", outcome="dropped")
    )
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert refuse(client, drop_body(on[0]["id"], HELD)) == qa.OFF
    priv = refuse(client, drop_body(on[0]["id"], HELD), url=f"/seasons/{PRIVATE}/autopilot/drop")
    assert priv == qa.PRIVATE


def test_a_protected_held_player_is_never_dropped():
    q = {"e": {"id": "e", "basis": qa.CHURN, "drop": 7, "held_drop": {"player": 7}, "queued": True}}
    run = ap.DropRun.model_validate(drop_body("e", 7, mode="live", outcome="dropped"))
    mode = {"mode": "live"}
    assert ap.check_drop_run(run, mode, False, q, {"ok": True}) is None
    assert (
        ap.check_drop_run(run, mode, False, q, {"ok": True}, {7}) == "7 is protected: never dropped"
    )
    assert ap.check_drop_run(run, mode, False, q, {"ok": False, "reason": "x"}) == "live refused: x"


# --------------------------------------------------------------------------- the pass record
def test_the_open_moves_pass_counts_the_drops_apart_from_its_claims(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    churn(client, on[0]["id"])
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    ids = [e["id"] for e in on]
    r = client.post(
        "/autopilot/passes",
        json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE], "entries": ids},
    )
    assert r.status_code == 200, r.text
    assert r.json()["drop"] is None
    assert client.post(URL, json=drop_body(on[0]["id"], HELD)).status_code == 200
    p = client.get("/autopilot/queue").json()["active"]
    assert p["drop"] == {"would_drop": 1, "dropped": 0, "skipped": 0, "failed": 0, "unconfirmed": 0}
    assert p["leagues"]["done"] == 0 and sum(p["results"].values()) == 0
    [stored] = json.loads(season_passes.passes_path(client.data_dir, DAY).read_text())["passes"]
    assert stored["drop"] == {on[0]["id"]: "would_drop"}
