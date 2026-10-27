"""The IL move an open-spot claim needs first (#214): the due route's ``il_first`` (the held
player of each due claim behind an IL move, once, with the day his team page is read on), the
league's log under ``il`` and its checks, the queue entry's ``il`` (never its outcome or place),
the pass record's IL counts and the digest's words. Nothing here opens a page: the runs are the
extension's, faked.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_passes, season_queue
from pickandroll.season import autopilot as qa
from pickandroll.sources.yahoo import public
from tests.test_moves_queue import (
    DAY,
    PRIVATE,
    check,
    live_league,
    pass_body,
    placed,
    queued,
    strike,
)
from tests.test_season import LEAGUE, NOW, season_client

URL = f"/seasons/{LEAGUE}/autopilot/il"
DUE = f"/seasons/{LEAGUE}/autopilot/moves/due"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def held_spot(client, entry_id: str, player: int, slot: str = "IL") -> None:
    """Make a day's queue entry an add with no drop behind an IL move, as the solve gives one when
    the roster is full but a held player can go to a held slot."""

    def change(q):
        for e in q["entries"]:
            if e["id"] == entry_id:
                e.update(drop=None, basis="held", held_move={"player": player, "slot": slot})
        return q

    season_queue.update(client.data_dir, DAY, change)


def a_player(client) -> tuple[int, str]:
    """A player of the fixture's snapshot with an NBA team: the held player's id and team."""
    players = client.app.state.seasons.season(LEAGUE).players
    k = next(k for k, p in sorted(players.items()) if p.nba_team)
    return k, players[k].nba_team


def il_body(entry: str | None, player: int | None, **over) -> dict:
    body = {
        "day": "2026-10-21",
        "mode": "dry_run",
        "trigger": "routine",
        "outcome": "would_move",
        "entry": entry,
        "player": player,
        "from_slot": "C",
        "to_slot": "IL",
        "dated": "2026-10-21",
        "page": f"/nba/{LEAGUE}/4?date=2026-10-21",
        "controls": {"form": "roster-edit-form", "il_row": True, "token": True},
        "extension": "0.9.0",
    }
    return {**body, **over}


def write_tips(client, tips: dict[str, str]) -> None:
    path = client.data_dir / "schedule" / "2026-10-21.json"
    body = json.loads(path.read_text()) if path.exists() else {}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**body, "tips": tips}))


def entries_by_id(client) -> dict[str, dict]:
    return {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}


# --------------------------------------------------------------------------- il_first
def test_a_due_claim_behind_an_il_move_names_the_move_first_once_a_player(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, team = a_player(client)
    held_spot(client, on[0]["id"], k)
    # Nothing is due inside the window, so nothing is moved first.
    assert client.get(DUE).json()["il_first"] == []
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    d = client.get(DUE).json()
    # The held player once, on today's team page; a claim with a drop needs no IL move.
    assert d["il_first"] == [
        {
            "entry": on[0]["id"],
            "player": k,
            "slot": "IL",
            "date": "2026-10-21",
            "tip": None,
            "page": public.team_url(LEAGUE, 4, DAY),
        }
    ]
    # Two claims behind the same held player move him once, for the first in the queue's order.
    held_spot(client, on[1]["id"], k)
    assert [x["entry"] for x in client.get(DUE).json()["il_first"]] == [on[0]["id"]]
    # Once his team's game has tipped off, today's page is locked: the move is dated tomorrow.
    began = (NOW + timedelta(minutes=30)).isoformat()
    write_tips(client, {team: began})
    [x] = client.get(DUE).json()["il_first"]
    nxt = DAY + timedelta(days=1)
    assert (x["date"], x["tip"]) == (nxt.isoformat(), began)
    assert x["page"] == public.team_url(LEAGUE, 4, nxt)
    # A game still to come keeps today's page.
    write_tips(client, {team: (NOW + timedelta(hours=3)).isoformat()})
    assert client.get(DUE).json()["il_first"][0]["date"] == "2026-10-21"


def test_no_il_move_first_for_a_claim_that_cannot_go_in(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    held_spot(client, on[0]["id"], k)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    assert len(client.get(DUE).json()["il_first"]) == 1
    # A slot other than the held ones is never moved to.
    held_spot(client, on[0]["id"], k, slot="BN")
    assert client.get(DUE).json()["il_first"] == []
    held_spot(client, on[0]["id"], k, slot="IL+")
    assert client.get(DUE).json()["il_first"][0]["slot"] == "IL+"
    # A struck claim is not due, so its player stays.
    strike(client, on[0]["id"])
    assert client.get(DUE).json()["il_first"] == []
    strike(client, on[0]["id"], undo=True)
    # An add whose claim is open already moves nobody.
    held_spot(client, on[1]["id"], k + 1)

    def same_add(q):
        for e in q["entries"]:
            if e["id"] == on[1]["id"]:
                e["add"] = on[0]["add"]
        return q

    season_queue.update(client.data_dir, DAY, same_add)
    placed(client, on[0]["id"], "claimed")
    d = client.get(DUE).json()
    assert [e["id"] for e in d["entries"]] == [on[1]["id"]] and d["il_first"] == []
    # The day's cap reached: nothing is due to need a move.
    placed(client, on[1]["id"], "claimed")
    assert client.get(DUE).json()["il_first"] == []
    # STOP, an off league and the private league answer none.
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert client.get(DUE).json()["il_first"] == []
    priv = client.get(f"/seasons/{PRIVATE}/autopilot/moves/due").json()
    assert priv["reason"] == qa.PRIVATE and priv["il_first"] == []


# --------------------------------------------------------------------------- the log
def test_an_il_run_is_logged_under_il_and_a_live_move_goes_on_its_entry_not_its_place(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    held_spot(client, on[0]["id"], k)
    held_spot(client, on[1]["id"], k + 1, slot="IL+")
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    # A dry run says it would move him: logged beside the moves passes, nothing on the queue.
    ap.append_run(client.data_dir, LEAGUE, {"day": "2026-10-21", "mode": "dry_run"}, DAY)
    r = client.post(URL, json=il_body(on[0]["id"], k))
    assert r.status_code == 200, r.text
    log = json.loads(
        (client.data_dir / "leagues" / LEAGUE / "autopilot" / "2026-10-21.json").read_text()
    )
    assert len(log["lineup"]) == 1 and [x["outcome"] for x in log["il"]] == ["would_move"]
    by = entries_by_id(client)
    assert by[on[0]["id"]].get("il") is None and by[on[0]["id"]]["outcome"] is None
    assert by[on[0]["id"]]["il_pass"]["outcome"] == "would_move"
    assert by[on[0]["id"]]["il_pass"]["to_slot"] == "IL"
    assert by[on[1]["id"]]["il_pass"] is None
    view = client.get(f"/seasons/{LEAGUE}/autopilot/moves").json()
    assert [r["outcome"] for r in view["il_today"]] == ["would_move"]
    assert next(e for e in view["entries"] if e["id"] == on[0]["id"])["il_pass"]["player"] == k
    # A dry run moves nobody.
    r = client.post(URL, json=il_body(on[0]["id"], k, outcome="moved"))
    assert r.status_code == 409 and r.json()["detail"] == "a dry run moves nobody"
    # Live: a run moves him or says why not, never that it would.
    live_league(client)
    r = client.post(URL, json=il_body(on[0]["id"], k, mode="live"))
    assert r.status_code == 409 and "never says would" in r.json()["detail"]
    # A live skip stays off the entry: the late pass reads the team page again.
    skip = il_body(on[0]["id"], k, mode="live", outcome="skipped", reason="no IL row read")
    assert client.post(URL, json=skip).status_code == 200
    assert entries_by_id(client)[on[0]["id"]].get("il") is None
    assert [x["entry"] for x in client.get(DUE).json()["il_first"]] == [on[0]["id"], on[1]["id"]]
    moved = il_body(on[0]["id"], k, mode="live", outcome="moved", message="Roster saved")
    assert client.post(URL, json=moved).status_code == 200
    by = entries_by_id(client)
    assert by[on[0]["id"]]["il"]["outcome"] == "moved"
    assert by[on[0]["id"]]["il"]["message"] == "Roster saved"
    # The move is not the claim: the entry is still due, in its place, and its player is not
    # moved again that day.
    assert (by[on[0]["id"]]["outcome"], by[on[0]["id"]]["rank"]) == (None, on[0]["rank"])
    d = client.get(DUE).json()
    assert on[0]["id"] in [e["id"] for e in d["entries"]]
    assert [x["entry"] for x in d["il_first"]] == [on[1]["id"]]
    r = client.post(URL, json=moved)
    assert r.status_code == 409 and r.json()["detail"] == f"{k} was moved to the IL already today"
    # A failure goes on its entry and is never retried that day.
    failed = il_body(
        on[1]["id"], k + 1, mode="live", outcome="failed", to_slot="IL+", reason="not saved"
    )
    assert client.post(URL, json=failed).status_code == 200
    assert entries_by_id(client)[on[1]["id"]]["il"]["outcome"] == "failed"
    assert client.get(DUE).json()["il_first"] == []
    r = client.post(URL, json={**failed, "outcome": "moved"})
    assert r.status_code == 409 and "never retried that day" in r.json()["detail"]


def test_the_il_log_refuses_a_crumb_another_move_a_claim_with_a_drop_and_a_struck_entry(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    out = next(e for e in q["entries"] if not e["queued"])
    k, _ = a_player(client)
    held_spot(client, on[0]["id"], k)

    def refused(body, code=409, url=URL):
        r = client.post(url, json=body)
        assert r.status_code == code, r.text
        return r.json()["detail"]

    assert "crumb" in refused(il_body(on[0]["id"], k, controls={"crumb": "x"}), 422)
    # Only a held slot, and the run names its entry, player and slot.
    refused(il_body(on[0]["id"], k, to_slot="BN"), 422)
    assert "names its entry" in refused(il_body(None, k))
    assert "another IL move" in refused(il_body(on[0]["id"], k + 1))
    assert "another IL move" in refused(il_body(on[0]["id"], k, to_slot="IL+"))
    assert "not an open-spot claim" in refused(il_body(on[1]["id"], k))
    assert "not in the day's queue" in refused(il_body("2026-10-21:1:1:0", k))
    held_spot(client, out["id"], k)
    assert "struck or not queued" in refused(il_body(out["id"], k))
    strike(client, on[0]["id"])
    assert "struck or not queued" in refused(il_body(on[0]["id"], k))
    # A struck entry's move may be reported skipped.
    skipped = il_body(on[0]["id"], k, outcome="skipped", reason="struck")
    assert client.post(URL, json=skipped).status_code == 200
    strike(client, on[0]["id"], undo=True)
    # STOP: a run can only say it stopped, and a stopped run names nothing.
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert refused(il_body(on[0]["id"], k)).startswith("STOP is on")
    assert client.post(URL, json=il_body(None, None, outcome="stopped")).status_code == 200
    stop.unlink()
    # A live run in a dry-run league, an off league and the private league are refused.
    assert "not live" in refused(il_body(on[0]["id"], k, mode="live", outcome="moved"))
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert refused(il_body(on[0]["id"], k)) == qa.OFF
    priv = refused(il_body(on[0]["id"], k), url=f"/seasons/{PRIVATE}/autopilot/il")
    assert priv == qa.PRIVATE


# --------------------------------------------------------------------------- the pass record
def test_the_open_moves_pass_counts_the_il_runs_apart_from_its_claims(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    held_spot(client, on[0]["id"], k)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    ids = [e["id"] for e in on]
    r = client.post(
        "/autopilot/passes",
        json={"kind": "moves", "trigger": "routine", "leagues": [LEAGUE], "entries": ids},
    )
    assert r.status_code == 200, r.text
    assert r.json()["il"] is None
    # The IL run leaves the league to its add pages: not done, no claim counted.
    assert client.post(URL, json=il_body(on[0]["id"], k)).status_code == 200
    p = client.get("/autopilot/queue").json()["active"]
    assert p["il"] == {"would_move": 1, "moved": 0, "skipped": 0, "failed": 0}
    assert p["leagues"]["done"] == 0 and p["entries"]["done"] == 0
    assert sum(p["results"].values()) == 0
    # The claims' post marks the league done; the IL count stays apart.
    claim = check({**on[0], "drop": None}, reason="open spot after the IL move")
    r = client.post(f"/seasons/{LEAGUE}/autopilot/moves", json=pass_body([claim]))
    assert r.status_code == 200, r.text
    p = client.get("/autopilot/queue").json()["active"]
    assert p["leagues"]["done"] == 1 and p["results"]["would_claim"] == 1
    assert p["il"]["would_move"] == 1
    [stored] = json.loads(season_passes.passes_path(client.data_dir, DAY).read_text())["passes"]
    assert stored["il"] == {on[0]["id"]: "would_move"}
    assert stored["outcomes"] == {on[0]["id"]: "would_claim"}
    # A panel's run is never the routine's.
    panel = il_body(on[0]["id"], k, trigger="panel", outcome="skipped", reason="by hand")
    assert client.post(URL, json=panel).status_code == 200
    assert client.get("/autopilot/queue").json()["active"]["il"]["skipped"] == 0


# --------------------------------------------------------------------------- the digest
def test_the_digest_counts_the_il_moves_and_names_a_skip_on_its_league(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    k, _ = a_player(client)
    held_spot(client, on[0]["id"], k)
    held_spot(client, on[1]["id"], k + 1)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    assert client.post(URL, json=il_body(on[0]["id"], k)).status_code == 200
    skipped = il_body(on[1]["id"], k + 1, outcome="skipped", reason="no IL row read")
    assert client.post(URL, json=skipped).status_code == 200
    lines = client.get("/flags/digest").json()["moves_executor"]
    assert lines[0].endswith("0 would be claimed, 0 skipped, 0 failed, 1 would be moved to the IL.")
    assert lines[1] == f"- League {LEAGUE}: moves Wed IL move skipped (no IL row read)"
