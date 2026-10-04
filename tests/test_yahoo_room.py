"""YAHOO SYNC room endpoints (#8): id map, ingestion, plan, events, restart, Tier 1 replay.

The hermetic tests build a synthetic league from the replay fixture itself: one projected
player and one Yahoo player per pick of room 2515267 (named after the Board label, keyed by the
real Yahoo id), plus bench filler. The real-data test runs only where the user's projection and
Yahoo players files exist in data/.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.cli import main as cli_main
from pickandroll.fidelity import analyze, guardrail_pass, markdown
from pickandroll.fidelity.replay import load_fixture, replay, timeline
from pickandroll.sources.matching import match_players
from pickandroll.sources.yahoo import build_id_map, label_key, load_players_file

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rooms" / "2515267.csv"
DATA = Path(__file__).resolve().parents[1] / "data"
POSITIONS = ("PG", "SG", "SF", "PF", "C")
CSV_COLUMNS = [
    "player_id", "last_name", "first_name", "games", "minutes", "field_goals_attempted",
    "field_goals", "free_throws_attempted", "free_throws", "threes", "threes_attempted",
    "offensive_rebounds", "defensive_rebounds", "assists", "blocks", "steals", "turnovers",
    "fouls", "technicals", "double_doubles", "triple_doubles", "comments",
]  # fmt: skip


# --------------------------------------------------------------------------- synthetic league
def _names(label: str, team: str) -> tuple[str, str]:
    """ "V. Wembanyama", "SAS" -> ("Vsas", "Wembanyama"): unique, same initial and last name."""
    initial, last = label.split(" ", 1)
    return f"{initial[0]}{team.lower()}", last


def build_league(directory: Path, extra: int = 80, seed: int = 11) -> list:
    """Projections CSV, positions CSV and Yahoo players JSON for the fixture's 156 players
    plus ``extra`` bench players (Yahoo ids from 900000), one Yahoo player with no projection
    (Yonly Human, 800000) and one projected player Yahoo does not list (Ponly Person)."""
    picks = load_fixture(FIXTURE)
    rng = np.random.default_rng(seed)
    people = [
        (*_names(p.label, p.team), p.team, p.yahoo_player_id, float(p.overall)) for p in picks
    ]
    people += [(f"Bench{i}", "Filler", "FA", str(900000 + i), None) for i in range(extra)]
    people += [("Ponly", "Person", "FA", None, None), ("Yonly", "Human", "FA", "800000", None)]
    assert len({(f, last) for f, last, *_ in people}) == len(people)
    rows, positions, yahoo = [], [], []
    for i, (first, last, team, yid, adp) in enumerate(people):
        pos = sorted(set(rng.choice(POSITIONS, int(rng.integers(1, 3))).tolist()))
        if yid is not None:
            yahoo.append(
                {
                    "id": int(yid),
                    "player_key": f"478.p.{yid}",
                    "fname": first,
                    "lname": last,
                    "team_abbr": team,
                    "average-pick": "-" if adp is None else f"{adp:.1f}",
                    "pos": [*pos, "Util"],
                }
            )
        if first == "Yonly":
            continue
        quality = 1.0 - min(i, 200) / 260.0 + rng.normal(0, 0.08)
        games = 70.0
        fga = max(4.0, 16 * quality) * games
        fta = max(1.0, 6 * quality) * games
        rows.append(
            {
                "player_id": 1000 + i,
                "last_name": last,
                "first_name": first,
                "games": games,
                "minutes": 32 * games,
                "field_goals_attempted": fga,
                "field_goals": fga * rng.uniform(0.42, 0.56),
                "free_throws_attempted": fta,
                "free_throws": fta * rng.uniform(0.65, 0.9),
                "threes": max(0.2, 2.5 * quality * rng.uniform(0.3, 1.5)) * games,
                "threes_attempted": 6 * games,
                "offensive_rebounds": max(0.3, 2 * quality * rng.uniform(0.3, 1.7)) * games,
                "defensive_rebounds": max(1.0, 6 * quality * rng.uniform(0.3, 1.7)) * games,
                "assists": max(0.5, 5 * quality * rng.uniform(0.3, 1.7)) * games,
                "blocks": max(0.1, 1.0 * quality * rng.uniform(0.2, 2.0)) * games,
                "steals": max(0.2, 1.1 * quality * rng.uniform(0.5, 1.5)) * games,
                "turnovers": max(0.5, 2.2 * quality * rng.uniform(0.6, 1.4)) * games,
                "fouls": 2 * games,
                "technicals": 0,
                "double_doubles": 0,
                "triple_doubles": 0,
                "comments": "",
            }
        )
        positions.append({"player": f"{first} {last}", "positions": "/".join(pos)})
    pd.DataFrame(rows, columns=CSV_COLUMNS).to_csv(directory / "proj.csv", index=False)
    pd.DataFrame(positions).to_csv(directory / "pos.csv", index=False)
    (directory / "yahoo_players_1.json").write_text(json.dumps({"service": {"player_list": yahoo}}))
    return picks


SESSION = {
    "projection_file": "proj.csv",
    "positions_file": "pos.csv",
    "num_teams": 12,
    "my_position": 1,
    "objective": "sum",
    "solve_ahead": False,
    "time_limit": 3.0,
}


@pytest.fixture
def league(tmp_path):
    picks = build_league(tmp_path)
    return tmp_path, picks


def app_for(directory: Path) -> TestClient:
    return TestClient(create_app(SessionStore(), data_dir=directory))


def post_picks(client, draft_id, picks, **extra):
    items = [{"overall": p.overall, "yahoo_player_id": p.yahoo_player_id, **extra} for p in picks]
    r = client.post(f"/rooms/{draft_id}/picks", json={"picks": items})
    assert r.status_code == 200, r.text
    return r.json()


def attach(client, draft_id="d1", slot=1, **overrides):
    body = {"draft_id": draft_id, "slot": slot, "session": SESSION, **overrides}
    r = client.post("/rooms", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- id map
def test_label_key_and_adp_tiebreak():
    assert label_key("V. Wembanyama") == label_key("Victor Wembanyama") == "v wembanyama"
    assert label_key("J. Jackson Jr.") == label_key("Jaren Jackson Jr.") == "j jackson"
    assert label_key("S. Gilgeous-Alexander") == label_key("Shai Gilgeous-Alexander")
    assert label_key("A. Şengün") == label_key("Alperen Sengun")
    players = pd.DataFrame(
        [
            ("4612", "478.p.4612", "Stephen Curry", "Stephen", "Curry", "GSW", "PG", 22.0),
            ("5000", "478.p.5000", "Seth Curry", "Seth", "Curry", "GSW", "SG", None),
            ("6702", "478.p.6702", "Jalen Williams", "Jalen", "Williams", "OKC", "SF", 31.0),
            ("6800", "478.p.6800", "Jaylin Williams", "Jaylin", "Williams", "OKC", "PF", 150.0),
            ("10094", "478.p.10094", "Victor Wembanyama", "Victor", "Wembanyama", "SAS", "C", 1.6),
        ],
        columns=["yahoo_id", "player_key", "name", "first", "last", "team", "positions", "adp"],
    ).set_index("yahoo_id")
    projections = pd.DataFrame(
        {"player": ["Stephen Curry", "Victor Wembanyama"], "team": ["", ""]},
        index=["stephen-curry", "victor-wembanyama"],
    )
    ids = build_id_map(players, projections)
    assert ids.resolve_label("S. Curry", "GSW") == "4612"
    assert ids.resolve_label("J. Williams", "OKC") == "6702"
    assert ids.resolve_label("V. Wembanyama", "SAS") == "10094"
    assert ids.resolve_label("V. Wembanyama", "NYK") == "10094"  # traded: any team
    assert ids.resolve_label("Z. Nobody", "SAS") is None
    assert ids.pid("10094") == "victor-wembanyama" and ids.yid("stephen-curry") == "4612"
    assert ids.row_name("10094") == {"ini": "V", "last": "Wembanyama", "team": "SAS"}


def test_short_first_names_match_but_initials_do_not():
    yahoo = pd.DataFrame(
        {
            "name": ["Nic Claxton", "Cameron Johnson", "Darius Brown", "Ronald Holland II"],
            "team": ["BKN", "DEN", "XXX", "DET"],
        },
        index=["k1", "k2", "k3", "k4"],
    )
    projections = pd.DataFrame(
        {"player": ["Nicolas Claxton", "Cam Johnson", "Dion Brown", "Ron Holland"]},
        index=["nicolas-claxton", "cam-johnson", "dion-brown", "ron-holland"],
    )
    result = match_players(yahoo, projections)
    assert result.mapping == {"k1": "nicolas-claxton", "k2": "cam-johnson", "k4": "ron-holland"}
    assert result.unmatched_yahoo == ["k3"] and result.unmatched_projection == ["dion-brown"]


def test_players_file_reader(league):
    directory, picks = league
    players = load_players_file(directory / "yahoo_players_1.json")
    assert len(players) == 156 + 80 + 1
    first = players.loc[picks[0].yahoo_player_id]
    assert first["name"] == "Vsas Wembanyama" and first["adp"] == 1.0
    assert players.loc["900000", "adp"] is None or pd.isna(players.loc["900000", "adp"])


# --------------------------------------------------------------------------- ingestion
def test_ingest_is_contiguous_idempotent_and_room_wins(league):
    directory, picks = league
    with app_for(directory) as c:
        room = attach(c)
        sid = room["session_id"]
        assert room["mapped"] == 236 and room["control"] == "mirror"
        assert room["session"]["my_position"] == 1 and room["session"]["objective"] == "sum"
        # Out of order: 3 and 2 wait for 1.
        r = post_picks(c, "d1", picks[2:0:-1])
        assert r["new"] == 2 and r["applied"] == 0 and r["waiting_for"] == 1
        r = post_picks(c, "d1", picks[:1])
        assert r["applied"] == 3 and r["synced_through"] == 3 and r["next_overall"] == 4
        # The whole history again changes nothing.
        r = post_picks(c, "d1", picks[:3])
        assert r["new"] == 0 and r["applied"] == 0 and r["replaced"] == 0
        # A label from the Board resolves like the socket's id.
        r = c.post(
            "/rooms/d1/picks",
            json={"picks": [{"overall": 4, "label": picks[3].label, "team": picks[3].team}]},
        ).json()
        assert r["applied"] == 1 and r["unresolved"] == []
        r = c.post(
            "/rooms/d1/picks", json={"picks": [{"overall": 5, "label": "Q. Nobody", "team": "X"}]}
        ).json()
        assert r["applied"] == 0 and r["unresolved"][0]["label"] == "Q. Nobody"
        # A session pick that disagrees with the room is replaced by the room's.
        board = c.get(f"/sessions/{sid}/board?limit=400").json()["players"]
        wrong = next(p for p in board if not p["taken"] and p["name"].startswith("Bench"))
        r = c.post(
            f"/sessions/{sid}/picks", json={"team": "Team 5", "player_id": wrong["player_id"]}
        )
        assert r.status_code == 201
        post_picks(c, "d1", picks[4:5])
        session_picks = c.get(f"/sessions/{sid}/picks").json()
        ids = build_id_map(load_players_file(directory / "yahoo_players_1.json"), _proj(c, sid))
        assert session_picks[4]["player_id"] == ids.pid(picks[4].yahoo_player_id)
        status = c.get("/rooms/d1").json()
        assert status["conflicts"][0]["session_pid"] == wrong["player_id"]
        events = _events(directory, "d1")
        assert [e["type"] for e in events].count("conflict") == 1
        # A Yahoo player with no projection becomes a stand-in; the ledger keeps the Yahoo id.
        r = c.post("/rooms/d1/picks", json={"picks": [{"overall": 6, "yahoo_player_id": "999999"}]})
        assert r.status_code == 200 and r.json()["applied"] == 1
        status = c.get("/rooms/d1").json()
        assert status["standins"][0]["overall"] == 6 and status["standins"][0]["yid"] == "999999"
        card = c.get("/rooms/d1/fidelity").json()
        # A stand-in is not the room's player: G1 counts it only once it is repaired.
        assert card["guardrails"]["G1"] == {"agree": 5, "of": 6, "total": 156}
        assert card["standins"] == 1 and card["conflicts"] == 1
        # One source at a time.
        assert c.post(f"/sessions/{sid}/yahoo", json={"league_id": "1"}).status_code == 409


def test_conflict_that_frees_a_player_repairs_his_standin(league):
    """The session holds W at 1 and X at 2 (entered in pickandroll). The room says X went at 1:
    X is held at 2, so 1 gets a stand-in. Then the room says Z went at 2: X is freed and must
    take his place at 1, leaving no stand-in and X in no other roster."""
    directory, picks = league
    with app_for(directory) as c:
        room = attach(c)
        sid = room["session_id"]
        players = load_players_file(directory / "yahoo_players_1.json")
        ids = build_id_map(players, _proj(c, sid))
        w, x, z = (picks[i].yahoo_player_id for i in (0, 1, 2))
        feed = [[1, "Team 1", ids.pid(w)], [2, "Team 2", ids.pid(x)]]
        assert c.post(f"/sessions/{sid}/sync", json={"picks": feed}).status_code == 200
        r = c.post("/rooms/d1/picks", json={"picks": [{"overall": 1, "yahoo_player_id": x}]})
        assert r.json()["replaced"] == 1
        assert c.get("/rooms/d1").json()["standins"][0]["yid"] == x
        r = c.post("/rooms/d1/picks", json={"picks": [{"overall": 2, "yahoo_player_id": z}]})
        assert r.json()["replaced"] == 2  # the conflict at 2 and the repair at 1
        held = [p["player_id"] for p in c.get(f"/sessions/{sid}/picks").json()]
        assert held == [ids.pid(x), ids.pid(z)]
        assert c.get("/rooms/d1").json()["standins"] == []
        events = _events(directory, "d1")
        kinds = [e["kind"] for e in events if e["type"] == "session_pick"]
        assert kinds == ["conflict", "conflict", "repair"]
        card = c.get("/rooms/d1/fidelity").json()
        assert card["guardrails"]["G1"]["agree"] == 2 and card["standins"] == 0


def test_alias_pin_repairs_a_standin(league):
    directory, picks = league
    with app_for(directory) as c:
        room = attach(c)
        sid = room["session_id"]
        assert room["unmatched_yahoo"][0]["yahoo_player_id"] == "800000"
        assert [p["name"] for p in room["unmatched_projection"]] == ["Ponly Person"]
        bad = {"draft_id": "d2", "slot": 1, "session": SESSION}
        for name in ("../yahoo_players_1.json", "sub/yahoo_players_1.json", ".."):
            r = c.post("/rooms", json={**bad, "players_file": name})
            assert r.status_code == 400 and "file name" in r.text
        post_picks(c, "d1", picks[:2])
        r = c.post(
            "/rooms/d1/picks", json={"picks": [{"overall": 3, "yahoo_player_id": "800000"}]}
        ).json()
        assert r["applied"] == 1
        assert c.get("/rooms/d1").json()["standins"][0]["yid"] == "800000"
        board = c.get(f"/sessions/{sid}/board?limit=400").json()["players"]
        target = next(p for p in board if p["name"] == "Ponly Person")["player_id"]
        bad = c.post("/rooms/d1/aliases", json={"yahoo_player_id": "1", "player_id": target})
        assert bad.status_code == 400
        r = c.post("/rooms/d1/aliases", json={"yahoo_player_id": "800000", "player_id": target})
        assert r.status_code == 200 and r.json()["repaired"] == [3]
        assert c.get(f"/sessions/{sid}/picks").json()[2]["player_id"] == target
        assert c.get("/rooms/d1").json()["standins"] == []
        saved = json.loads((directory / "aliases.json").read_text())
        assert saved == {"478.p.800000": target}
        card = c.get("/rooms/d1/fidelity").json()
        assert card["conflicts"] == 0 and card["standins"] == 0
        assert card["guardrails"]["G1"]["agree"] == card["guardrails"]["G1"]["of"] == 3


# --------------------------------------------------------------------------- plan and events
def test_plan_back_to_back_wait_and_bounds(league):
    directory, picks = league
    with app_for(directory) as c:
        attach(c, num_teams=12)
        post_picks(c, "d1", picks[:23])
        assert c.get("/rooms/d1/plan?wait=21").status_code == 422
        plan = c.get("/rooms/d1/plan?wait=15").json()
        assert plan["fresh"] is True and plan["board"] == 23 and plan["on_the_clock"] is True
        assert plan["my_next_pick"] == 24 and plan["second_pick"] == 25
        top = plan["candidates"][0]
        assert top["why"] == "candidate" and {"ini", "last", "team", "name"} <= set(top)
        drafted = {p.yahoo_player_id for p in picks[:23]}
        assert not drafted & {c_["yahoo_player_id"] for c_ in plan["candidates"]}
        assert plan["second"] and plan["second"][0]["player_id"] != top["player_id"]
        assert len(plan["candidates"]) >= 20
        # The solve was logged with its board and top candidate.
        reco = [e for e in _events(directory, "d1") if e["type"] == "reco"][-1]
        assert reco["board"] == 23 and reco["top_yid"] == top["yahoo_player_id"]
        assert reco["fresh"] is True and reco["solve_ms"] > 0
        assert reco["top_pid"] == top["player_id"] and reco["unmapped"] == []
        # Without a wait the plan comes back at once, marked stale after a new pick.
        post_picks(c, "d1", picks[23:24])
        plan = c.get("/rooms/d1/plan").json()
        assert plan["fresh"] is False and plan["second_pick"] is None


def test_plan_holds_for_the_clients_board(league):
    """The turn's client knows pick k-1 landed before the API may have applied it: asked for
    board k-1, the plan of board k-2 is not fresh, and the wait holds for the newer board."""
    directory, picks = league
    with app_for(directory) as c:
        attach(c, num_teams=12)
        post_picks(c, "d1", picks[:22])
        plan = c.get("/rooms/d1/plan?wait=15").json()
        assert plan["fresh"] is True and plan["board"] == 22
        assert c.get("/rooms/d1/plan?board=-1").status_code == 422
        plan = c.get("/rooms/d1/plan?wait=0.3&board=23").json()
        assert plan["fresh"] is False and plan["board"] == 22 and plan["waited_ms"] >= 300
        assert c.get("/rooms/d1/plan?board=22").json()["fresh"] is True
        post_picks(c, "d1", picks[22:23])
        plan = c.get("/rooms/d1/plan?wait=15&board=23").json()
        assert plan["fresh"] is True and plan["board"] == 23


def test_events_validation_heartbeats_and_control(league):
    directory, _picks = league
    with app_for(directory) as c:
        attach(c)
        # A server type and an event missing its overall are dropped, not the request.
        r = c.post("/rooms/d1/events", json={"events": [{"type": "room_pick", "overall": 1}]})
        assert r.status_code == 200 and r.json()["written"] == 0 and r.json()["ignored"] == 1
        r = c.post("/rooms/d1/events", json={"events": [{"type": "turn_start"}]})
        assert r.status_code == 200 and r.json()["ignored"] == 1
        r = c.post(
            "/rooms/d1/events",
            json={"events": [{"type": "heartbeat", "vis": "visible"} for _ in range(3)]},
        ).json()
        assert r["written"] == 1
        r = c.post(
            "/rooms/d1/events", json={"events": [{"type": "control", "state": "armed"}]}
        ).json()
        assert r["control"] == "armed"
        assert c.get("/rooms/d1").json()["heartbeat_age_s"] is not None
        assert c.patch("/rooms/d1", json={"mode": "autopilot"}).json()["control"] == "armed"
        cors = c.options(
            "/rooms/d1/picks",
            headers={
                "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert cors.headers["access-control-allow-origin"].startswith("chrome-extension://")
        assert c.delete("/rooms/d1").json()["attached"] is False
        assert c.get("/rooms/d1/fidelity").status_code == 200


def test_an_unknown_event_type_never_loses_the_batch(league):
    """An extension one event type ahead of the API: the known events are still recorded."""
    directory, _picks = league
    with app_for(directory) as c:
        attach(c)
        batch = [
            {"type": "draft_attempt", "overall": 1, "yid": "a", "method": "row", "attempt": 1},
            {"type": "queue_probe", "overall": 1, "outcome": "drafted"},
            {"type": "pick_landed", "overall": 1, "yid": "a", "how": "row"},
        ]
        r = c.post("/rooms/d1/events", json={"events": batch})
        assert r.status_code == 200
        assert r.json()["written"] == 2 and r.json()["ignored"] == 1
    events = _events(directory, "d1")
    kinds = [e["type"] for e in events]
    assert "draft_attempt" in kinds and "pick_landed" in kinds and "queue_probe" not in kinds
    notes = [e for e in events if e.get("what") == "client events ignored"]
    assert [n["ignored"] for n in notes] == [{"type 'queue_probe'": 1}]


def test_an_event_with_a_bad_time_never_loses_the_batch(league):
    """A note whose t is neither ISO-8601 nor epoch ms is dropped; the events with it stay."""
    directory, _picks = league
    with app_for(directory) as c:
        attach(c)
        batch = [
            {"type": "draft_attempt", "overall": 1, "yid": "a", "method": "row", "attempt": 1},
            {"type": "note", "what": "x", "t": "yesterday"},
            {"type": "pick_landed", "overall": 1, "yid": "a", "how": "row"},
        ]
        r = c.post("/rooms/d1/events", json={"events": batch})
        assert r.status_code == 200
        assert r.json()["written"] == 2 and r.json()["ignored"] == 1
    events = _events(directory, "d1")
    assert not [e for e in events if e.get("what") == "x"]
    notes = [e for e in events if e.get("what") == "client events ignored"]
    assert [n["ignored"] for n in notes] == [{"bad t": 1}]


def test_a_pick_outside_the_draft_is_dropped_never_the_batch(league):
    """Three picks, a pick 0 and a pick 157 in one batch: the three are recorded, 0 and 157
    are ignored."""
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        items = [{"overall": p.overall, "yahoo_player_id": p.yahoo_player_id} for p in picks[:3]]
        items.append({"overall": 157, "yahoo_player_id": picks[3].yahoo_player_id})
        items.append({"overall": 0, "yahoo_player_id": picks[4].yahoo_player_id})
        r = c.post("/rooms/d1/picks", json={"picks": items})
        assert r.status_code == 200
        assert r.json()["ignored"] == 2 and r.json()["synced_through"] == 3
        assert c.get("/rooms/d1").json()["synced_through"] == 3
    events = _events(directory, "d1")
    assert not [e for e in events if e.get("overall") in (0, 157)]
    notes = [e for e in events if e.get("what") == "room picks outside the draft ignored"]
    assert [n["overalls"] for n in notes] == [[0, 157]]


# --------------------------------------------------------------------------- restart
def test_room_survives_an_api_restart(league):
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:60])
        assert c.get("/rooms/d1").json()["picks_applied"] == 60
    # A new server: the session is gone, the log is not.
    with app_for(directory) as c:
        assert c.get("/rooms").json() == []
        room = c.post("/rooms", json={"draft_id": "d1"})
        assert room.status_code == 201, room.text
        room = room.json()
        assert room["resumed"] is True and room["picks_applied"] == 60
        assert room["slot"] == 1 and room["session"]["objective"] == "sum"
        sid = room["session_id"]
        names = [p["player_id"] for p in c.get(f"/sessions/{sid}/picks").json()]
        ids = build_id_map(load_players_file(directory / "yahoo_players_1.json"), _proj(c, sid))
        assert names == [ids.pid(p.yahoo_player_id) for p in picks[:60]]
        assert post_picks(c, "d1", picks[:60])["new"] == 0
        plan = c.get("/rooms/d1/plan?wait=15").json()
        assert plan["fresh"] is True and plan["my_next_pick"] == 72 and plan["candidates"]
        card = c.get("/rooms/d1/fidelity").json()
        assert card["guardrails"]["G1"]["agree"] == 60 and card["picks_seen"] == 60
    # Any room call resumes too, without an explicit attach.
    with app_for(directory) as c:
        r = c.post(
            "/rooms/d1/picks",
            json={"picks": [{"overall": 61, "yahoo_player_id": picks[60].yahoo_player_id}]},
        )
        assert r.status_code == 200 and r.json()["synced_through"] == 61


# --------------------------------------------------------------------------- scorecard
def _ev(kind, t, **fields):
    return {"type": kind, "t": f"2026-10-01T00:{t // 60:02d}:{t % 60:02d}.000+00:00", **fields}


def test_scorecard_labels_every_failure():
    """Twelve teams, slot 1, so my picks are 1, 24, 25, 48, 49, 72, 73, 96: one per label."""
    events = [
        _ev("attach", 0, slot=1, num_teams=12, rounds=13, draft_id="x", mode="autopilot"),
        _ev("control", 0, state="armed"),
    ]

    def pick(k, yid, t_room, t_session=None):
        events.append(_ev("room_pick", t_room, overall=k, yid=yid, name=f"P{yid}"))
        events.append(_ev("session_pick", t_session or t_room, overall=k, yid=yid))

    def others(first, last, t):
        for k in range(first, last + 1):
            pick(k, f"o{k}", t + k - first)

    events.append(_ev("turn_start", 2, overall=1))
    events.append(_ev("reco", 3, board=0, top_yid="a", cands=["a", "b"], solve_ms=900))
    events.append(_ev("pick_landed", 5, overall=1, yid="a", how="row", ms_from_turn=3000))
    pick(1, "a", 5)  # compliant
    others(2, 23, 6)
    events.append(_ev("reco", 30, board=23, top_yid="b", cands=["b", "c"], solve_ms=800))
    events.append(_ev("pick_landed", 32, overall=24, yid="c", how="row"))
    pick(24, "c", 32)  # fallback: rank 2 of the list
    events.append(_ev("pick_landed", 34, overall=25, yid="m", how="manual"))
    pick(25, "m", 34)  # manual
    others(26, 47, 35)
    events.append(_ev("pick_landed", 60, overall=48, yid="z", how="expiry"))
    pick(48, "z", 60)  # unsolved: no solve for board 47
    events.append(_ev("reco", 61, board=48, top_yid="d", cands=["d"], solve_ms=700))
    events.append(_ev("pick_landed", 63, overall=49, yid="q", how="row"))
    pick(49, "q", 63)  # wrong: not in the list
    others(50, 71, 64)
    events.append(_ev("reco", 90, board=71, top_yid="e", cands=["e"], solve_ms=650))
    events.append(_ev("pick_landed", 120, overall=72, yid="y", how="expiry"))
    pick(72, "y", 120, t_session=130)  # expired; reaches the session only at 130
    events.append(_ev("reco", 121, board=72, top_yid="f", cands=["f"]))
    events.append(_ev("pick_landed", 125, overall=73, yid="s", how="row"))
    pick(73, "s", 125)  # stale: pick 72 was not in the session when 73 landed
    events.append(_ev("control", 126, state="absent", reason="autopick"))
    others(74, 95, 127)
    pick(96, "w", 150)  # absent: the seat was in autopick mode
    events.append(_ev("intervention", 151, who="drone", what="turned autopick off"))

    card = analyze(events)
    labels = {r["overall"]: r["label"] for r in card["rows"]}
    assert labels == {
        1: "compliant",
        24: "fallback",
        25: "manual",
        48: "unsolved",
        49: "wrong",
        72: "expired",
        73: "stale",
        96: "absent",
    }
    assert card["compliance"] == {
        "compliant": 1,
        "denominator": 7,
        "manual": 1,
        "my_picks_seen": 8,
        "against_final": 1,
    }
    g = card["guardrails"]
    assert g["G1"]["agree"] == 96 and g["G2"]["max"] == 10000 and g["G3"]["interventions"] == 1
    assert g["G4"] == {"respected": 1, "manual": 1} and g["G5"]["autopick_flips"] == 1
    assert g["G6"]["entry_lead_s"] == 2.0
    d = card["diagnostics"]
    assert d["D3"]["n"] == 4 and d["D2"]["n"] == 6 and d["D1"]["n"] == 5
    text = markdown(card)
    assert "**Compliance 1/7**" in text and "| G5 autopick flips | 1 | 0 | **FAIL** |" in text


@pytest.mark.parametrize("entered_first", [True, False])
def test_scorecard_a_pick_learned_from_history_is_absent(entered_first):
    """Mock 3: attached armed minutes early, the tab entered at pick 19 and learned picks 1-18
    from Yahoo's history frame (P| on connect), stamped at the tab's receipt. Pick 1, ours,
    was Yahoo's autopick of a listed candidate: pickandroll was not there, so it is absent, not
    a fallback, whichever came first, the tab's "entered" note or the frame."""
    t_entry, t_frame = (100, 101) if entered_first else (101, 100)
    events = [
        _ev("attach", 0, slot=1, num_teams=12, rounds=13, draft_id="m3", mode="autopilot"),
        _ev("control", 0, state="armed", src="api"),
        _ev("reco", 5, board=0, top_yid="a", cands=["a", "b"], solve_ms=900),
        _ev("note", t_entry, what="entered", src="client"),
        _ev("control", t_entry, state="armed", src="client"),
    ]
    for k in range(1, 19):
        yid = "b" if k == 1 else f"o{k}"
        events.append(_ev("room_pick", t_frame, overall=k, yid=yid, src="history"))
        events.append(_ev("session_pick", t_frame, overall=k, yid=yid))
    # A live turn after the tab entered keeps its label.
    for k in range(19, 24):
        events.append(_ev("room_pick", 102 + k - 19, overall=k, yid=f"o{k}", src="socket"))
        events.append(_ev("session_pick", 102 + k - 19, overall=k, yid=f"o{k}"))
    events.append(_ev("turn_start", 108, overall=24))
    events.append(_ev("reco", 109, board=23, top_yid="c", cands=["c", "d"], solve_ms=800))
    events.append(_ev("draft_attempt", 110, overall=24, yid="c", method="row", board=23))
    events.append(_ev("pick_landed", 111, overall=24, yid="c", how="row"))
    events.append(_ev("room_pick", 111, overall=24, yid="c", src="socket"))
    events.append(_ev("session_pick", 111, overall=24, yid="c"))
    card = analyze(events)
    assert {r["overall"]: r["label"] for r in card["rows"]} == {1: "absent", 24: "compliant"}
    assert card["guardrails"]["G6"]["entry_from"] == "client"


@pytest.mark.parametrize(("method", "respected"), [("request", 1), ("row", 0)])
def test_scorecard_g4_a_request_click_noted_after_its_pick_is_not_an_intervention(
    method, respected
):
    """Mock 4, pick 50: the user's Draft in Yahoo landed at 29.663 s and the tab noted the
    request's click when it settled, 0.4 s later. That attempt is the manual pick itself; a row
    attempt after a hand pick is still the drafter acting on the user's pick."""
    events = [
        _ev("attach", 0, slot=1, num_teams=12, rounds=13, draft_id="m4", mode="autopilot"),
        _ev("control", 0, state="armed"),
        _ev("note", 1, what="entered", src="client"),
    ]
    for k in range(1, 24):
        events.append(_ev("room_pick", 2 + k, overall=k, yid=f"o{k}", src="socket"))
        events.append(_ev("session_pick", 2 + k, overall=k, yid=f"o{k}"))
    landed = "2026-10-01T00:00:29.663+00:00"
    clicked = "2026-10-01T00:00:30.063+00:00"
    events += [
        _ev("turn_start", 26, overall=24),
        _ev("reco", 27, board=23, top_yid="a", cands=["a", "b", "c", "m"], solve_ms=800),
        {**_ev("pick_landed", 0, overall=24, yid="m", how="manual"), "t": landed},
        {**_ev("room_pick", 0, overall=24, yid="m", src="socket"), "t": landed},
        {**_ev("session_pick", 0, overall=24, yid="m"), "t": landed},
        {**_ev("draft_attempt", 0, overall=24, yid="m", method=method, board=23), "t": clicked},
    ]
    card = analyze(events)
    assert {r["overall"]: r["label"] for r in card["rows"]}[24] == "manual"
    assert card["guardrails"]["G4"] == {"respected": respected, "manual": 1}


def test_scorecard_unmapped_top_is_a_fallback_and_entry_lead_from_the_client():
    base = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=1, draft_id="u"),
        _ev("control", 0, state="armed", src="api"),
        _ev("turn_start", 70, overall=1),
        _ev(
            "reco",
            71,
            board=0,
            top_yid="b",
            top_pid="ghost",
            cands=["b"],
            unmapped=[{"pid": "ghost", "name": "Ghost Player"}],
        ),
        _ev("room_pick", 72, overall=1, yid="b"),
        _ev("session_pick", 72, overall=1, yid="b"),
    ]
    card = analyze(base)
    row = card["rows"][0]
    assert row["label"] == "fallback" and row["ref_name"] == "Ghost Player"
    assert row["ref_pid"] == "ghost" and row["ref_yid"] is None
    assert card["guardrails"]["G6"] == {"entry_lead_s": 70.0, "entry_from": "attach"}
    assert "70.0 s (from attach)" in markdown(card)
    with_client = [*base[:2], _ev("heartbeat", 10, src="client"), *base[2:]]
    assert analyze(with_client)["guardrails"]["G6"] == {
        "entry_lead_s": 60.0,
        "entry_from": "client",
    }
    # The client's "entered" note was written before the attach and arrives after it: the
    # earliest client event by time counts, whatever its place in the log.
    entered = [*with_client, _ev("note", 5, what="entered", src="client")]
    assert analyze(entered)["guardrails"]["G6"]["entry_lead_s"] == 65.0
    # A note the API wrote is not the client's.
    api_note = [*with_client, _ev("note", 1, what="alias pinned")]
    assert analyze(api_note)["guardrails"]["G6"]["entry_lead_s"] == 60.0


@pytest.mark.parametrize(("lead_s", "passes"), [(44.8, True), (30.0, True), (29.0, False)])
def test_scorecard_g6_target_is_30_s(lead_s, passes):
    """G6 (user, 2026-10-03): entering through Yahoo's "Enter Draft" link at once leaves about
    45-47 s, 44.8 s in mock 4, which passes; under 30 s fails."""
    entered = f"2026-10-01T00:00:{60 - lead_s:06.3f}+00:00"
    events = [
        _ev("attach", 0, slot=2, num_teams=2, rounds=1, draft_id="g6"),
        _ev("control", 0, state="armed", src="api"),
        {**_ev("note", 0, what="entered", src="client"), "t": entered},
        _ev("turn_start", 60, overall=1),
        _ev("room_pick", 62, overall=1, yid="x"),
        _ev("session_pick", 62, overall=1, yid="x"),
    ]
    card = analyze(events)
    assert card["guardrails"]["G6"] == {"entry_lead_s": lead_s, "entry_from": "client"}
    assert guardrail_pass(card)["G6"] is passes
    assert f"| ≥ 30 s | {'pass' if passes else '**FAIL**'} |" in markdown(card)


def test_scorecard_stale_when_the_session_was_behind():
    events = [
        _ev("attach", 0, slot=2, num_teams=2, rounds=2, draft_id="s"),
        _ev("control", 0, state="armed"),
        _ev("room_pick", 1, overall=1, yid="a"),
        _ev("reco", 2, board=0, top_yid="x", cands=["x"]),
        _ev("room_pick", 3, overall=2, yid="b"),
        _ev("session_pick", 9, overall=1, yid="a"),  # pick 1 reached the session after pick 2
        _ev("session_pick", 10, overall=2, yid="b"),
    ]
    card = analyze(events)
    assert [r["label"] for r in card["rows"]] == ["stale"]
    assert card["guardrails"]["G2"]["max"] == 8000


def test_scorecard_judges_the_reco_acted_on_and_counts_churn():
    """Two teams, slot 1: my picks are 1 and 4. Pick 1 is drafted off the early plan, which the
    priced table then replaces with another #1 (churn). Pick 4 is drafted off board 2's plan
    while board 3's was there: stale, though the session was synced."""
    events = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=2, draft_id="c"),
        _ev("control", 0, state="armed"),
        _ev("turn_start", 1, overall=1),
        _ev(
            "reco",
            2,
            board=0,
            top_yid="a",
            top_pid="pa",
            top_name="A",
            cands=["a", "b"],
            priced=False,
            branch=False,
            solve_ms=200,
        ),
        _ev("draft_attempt", 3, overall=1, yid="a", method="row", attempt=1, board=0),
        _ev(
            "reco",
            4,
            board=0,
            top_yid="b",
            top_pid="pb",
            top_name="B",
            cands=["b", "a"],
            priced=True,
            solve_ms=500,
            branches_running=2,
        ),
        _ev("pick_landed", 5, overall=1, yid="a", how="row"),
        _ev("room_pick", 5, overall=1, yid="a"),
        _ev("session_pick", 5, overall=1, yid="a"),
        _ev("reco", 6, board=2, top_yid="x", top_pid="px", top_name="X", cands=["x", "d"]),
        _ev("room_pick", 7, overall=2, yid="o2"),
        _ev("session_pick", 7, overall=2, yid="o2"),
        _ev("room_pick", 8, overall=3, yid="x"),
        _ev("session_pick", 8, overall=3, yid="x"),
        _ev("turn_start", 8, overall=4),
        _ev(
            "reco",
            9,
            board=3,
            top_yid="c",
            top_pid="pc",
            top_name="C",
            cands=["c", "e"],
            priced=True,
            solve_ms=300,
            branches_running=0,
        ),
        _ev("draft_attempt", 10, overall=4, yid="d", method="row", attempt=1, board=2),
        _ev("pick_landed", 11, overall=4, yid="d", how="row"),
        _ev("room_pick", 11, overall=4, yid="d"),
        _ev("session_pick", 11, overall=4, yid="d"),
    ]
    card = analyze(events)
    first, second = card["rows"]
    assert first["label"] == "compliant" and first["ref_name"] == "A"
    assert first["ref_kind"] == "plan" and first["final_kind"] == "priced"
    assert first["churn"] is True and first["final_name"] == "B"
    assert second["label"] == "stale" and second["acted_board"] == 2
    assert second["churn"] is False
    assert card["compliance"]["compliant"] == 1 and card["compliance"]["against_final"] == 0
    d = card["diagnostics"]
    assert d["D6"] == {"churn": 1, "picks": [1]}
    assert d["D1_hit"]["n"] == 0 and d["D1_pending"]["n"] == 0 and d["D1_miss"]["n"] == 2
    plan = events[3]  # board 0's first reco (1 s into the turn): an installed branch instead

    def split(**fields):
        swap = [{**e, "branch": True, **fields} if e is plan else e for e in events]
        out = analyze(swap)["diagnostics"]
        return out["D1_hit"]["n"], out["D1_pending"]["n"], out["D1_miss"]["n"]

    assert split(branch_late=False) == (1, 0, 1)  # solved before the turn started
    assert split(branch_late=True) == (0, 1, 1)  # still solving then, installed when it landed
    # A log from before branch_late: 1 s after the turn start is past a solved branch's install.
    assert split() == (0, 1, 1)
    assert split(t="2026-10-01T00:00:01.100+00:00") == (1, 0, 1)  # in at 100 ms: a hit
    assert d["D3"]["n"] == 2 and d["D3_plan"]["n"] == 1
    assert d["D3_busy"]["max"] == 500 and d["D3_idle"]["max"] == 300
    text = markdown(card)
    assert "| D6 reco churn (target 0) | 1 at 1 |" in text
    assert "Compliance against the final reco (diagnostic): 0/2." in text
    assert "| 1 | A | plan | - | B | priced | - | to find |" in text
    # With objectives logged, a final reco that beat the one acted on is its own cause.
    scored = [
        {**e, "top_objective": 6.0 if e.get("top_yid") == "a" else 6.1}
        if e["type"] == "reco"
        else e
        for e in events
    ]
    row = analyze(scored)["rows"][0]
    assert row["churn_cause"] == "better plan after action"
    # Without an attempt (expiry, manual) the ref is the last reco before the landing.
    no_attempt = [e for e in events if e["type"] != "draft_attempt"]
    rows = analyze(no_attempt)["rows"]
    assert rows[0]["label"] == "fallback" and rows[0]["churn"] is False
    assert rows[1]["label"] == "wrong"  # judged against board 3's list, which lacks d


def test_scorecard_compliant_only_when_the_drafter_made_the_pick_and_g7():
    """Three teams, slot 1, two rounds: my picks are 1 and 6. Pick 1 expires and Yahoo's
    autopick happens to be ref_k: expired, not compliant. Pick 6 lands from the queue the
    drafter set: compliant. One heartbeat ran on DOM timers: G7 fails."""
    events = [
        _ev("attach", 0, slot=1, num_teams=3, rounds=2, draft_id="g"),
        _ev("control", 0, state="armed"),
        _ev("heartbeat", 1, worker=True, src="client"),
        _ev("turn_start", 1, overall=1),
        _ev("reco", 2, board=0, top_yid="a", cands=["a", "b"]),
        _ev("pick_landed", 31, overall=1, yid="a", how="expiry"),
        _ev("room_pick", 31, overall=1, yid="a"),
        _ev("session_pick", 31, overall=1, yid="a"),
        _ev("heartbeat", 32, worker=False, src="client"),
    ]
    for k in range(2, 6):
        events += [_ev("room_pick", 32 + k, overall=k, yid=f"o{k}")]
        events += [_ev("session_pick", 32 + k, overall=k, yid=f"o{k}")]
    events += [
        _ev("turn_start", 37, overall=6),
        _ev("reco", 38, board=5, top_yid="c", cands=["c"]),
        _ev("draft_attempt", 60, overall=6, yid="c", method="queue", attempt=1, board=5),
        _ev("pick_landed", 61, overall=6, yid="c", how="autopick"),
        _ev("room_pick", 61, overall=6, yid="c"),
        _ev("session_pick", 61, overall=6, yid="c"),
    ]
    card = analyze(events)
    assert [r["label"] for r in card["rows"]] == ["expired", "compliant"]
    g7 = card["guardrails"]["G7"]
    assert g7["heartbeats"] == 2 and g7["worker_off"] == 1
    assert g7["first_off"] == events[8]["t"]
    assert guardrail_pass(card)["G7"] is False
    assert "| G7 client timers on the Worker | 1 of 2 heartbeats without, first at" in markdown(
        card
    )


def test_scorecard_reports_the_queue_probe():
    """The probe's note is a diagnostic line: what Yahoo did with the star on my turn."""
    events = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=1, draft_id="p"),
        _ev("room_pick", 1, overall=1, yid="a"),
        _ev("session_pick", 1, overall=1, yid="a"),
    ]
    assert analyze(events)["queue_probe"] is None
    assert "Queue probe (diagnostic): not run." in markdown(analyze(events))
    events.append(
        _ev(
            "note",
            1,
            what="queue_probe",
            overall=1,
            yid="a",
            name="A",
            outcome="drafted",
            control="Draft",
            panel=None,
            src="client",
        )
    )
    card = analyze(events)
    assert card["queue_probe"]["outcome"] == "drafted"
    assert (
        'Queue probe (diagnostic): pick 1 (A) drafted; control "Draft"; queue panel unreadable.'
        in markdown(card)
    )


def test_scorecard_g2_judges_the_picks_after_the_attach():
    events = [
        _ev("room_pick", 1, overall=1, yid="a"),  # the room started before the attach
        _ev("attach", 20, slot=2, num_teams=2, rounds=2, draft_id="late"),
        _ev("control", 20, state="mirror"),
        _ev("session_pick", 21, overall=1, yid="a"),
        _ev("room_pick", 22, overall=2, yid="b"),
        _ev("session_pick", 23, overall=2, yid="b"),
    ]
    g = analyze(events)["guardrails"]
    assert g["G2"]["n"] == 1 and g["G2"]["max"] == 1000
    assert g["G2_all"] == {"n": 2, "p50": 1000, "p95": 20000, "max": 20000, "pre_attach": 1}
    assert "| G2 over all picks, 1 before the attach | p50 1000" in markdown(analyze(events))


def test_fidelity_report_cli(tmp_path, capsys):
    log = tmp_path / "r1.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                _ev("attach", 0, slot=1, num_teams=2, rounds=1, draft_id="r1"),
                _ev("room_pick", 1, overall=1, yid="a"),
                _ev("session_pick", 1, overall=1, yid="a"),
            ]
        )
        + "\n"
    )
    assert cli_main(["fidelity", "report", "r1", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## Room r1: fidelity scorecard") and "| 1 | 1 |" in out
    assert cli_main(["fidelity", "report", "nope", "--dir", str(tmp_path)]) == 1


# --------------------------------------------------------------------------- Tier 1 replay
def test_fixture_timeline():
    picks = load_fixture(FIXTURE)
    times = timeline(picks)
    assert len(picks) == 156 and times[0] == 0.0
    assert all(b >= a for a, b in pairwise(times))
    recorded = picks[84].t_ms - picks[83].t_ms
    assert times[84] - times[83] == pytest.approx(recorded)


def test_tier1_replay_synthetic(league):
    """Room 2515267 replayed back to back through the API with background solving on."""
    directory, picks = league
    with app_for(directory) as c:
        result = replay(
            c,
            picks,
            draft_id="2515267-replay",
            slot=1,
            session={**SESSION, "solve_ahead": True},
            solve={"n": 3, "scenarios": 0, "time_limit": 3.0},
            plan_wait=15.0,
        )
    card = result["scorecard"]
    assert card["picks_seen"] == 156
    assert card["guardrails"]["G1"] == {"agree": 156, "of": 156, "total": 156}
    assert card["standins"] == 0 and card["conflicts"] == 0
    assert card["guardrails"]["G2"]["n"] == 156 and card["guardrails"]["G2"]["p95"] < 2000
    assert len(card["rows"]) == 13 and card["compliance"]["my_picks_seen"] == 13
    assert card["mode"] == "mirror" and all(
        r["label"] in {"compliant", "absent"} for r in card["rows"]
    )
    assert card["diagnostics"]["D3"]["n"] > 0 and card["diagnostics"]["D1"]["n"] == 13
    assert len(result["plans"]) == 13 and all(p["fresh"] for p in result["plans"])
    assert [p["second"] is not None for p in result["plans"]] == [
        k % 24 == 0 for k in (1, 24, 25, 48, 49, 72, 73, 96, 97, 120, 121, 144, 145)
    ]
    status = result["status"]
    assert status["picks_seen"] == 156 and len(status["my_picks"]) == 13
    assert status["lag_ms"]["n"] == 156 and status["live"]["picks_applied"] == 156
    assert card["guardrails"]["G6"]["entry_from"] == "client"
    assert "| G1 board agreement | 156/156" in card["markdown"]
    # The final score is logged once my roster is full (my last pick is 145).
    events = _events(directory, "2515267-replay")
    assert [e["type"] for e in events].count("score") == 1


@pytest.mark.skipif(
    not (DATA / "yahoo_players_31822.json").exists()
    or not sorted(DATA.glob("bbm_projections_*.csv")),
    reason="needs the user's projections and Yahoo players files in data/",
)
def test_tier1_replay_real_data(tmp_path):
    """The same room on the real projections and Yahoo player list (local data only)."""
    picks = load_fixture(FIXTURE)
    ids_players = load_players_file(DATA / "yahoo_players_31822.json")
    projection = max(DATA.glob("bbm_projections_*.csv"))
    from pickandroll.sources.bbm import load_bbm

    ids = build_id_map(ids_players, load_bbm(projection).df)
    assert [ids.resolve_label(p.label, p.team) for p in picks] == [p.yahoo_player_id for p in picks]
    assert all(ids.pid(p.yahoo_player_id) for p in picks)
    session = {
        "projection_file": projection.name,
        "num_teams": 12,
        "my_position": 1,
        "objective": "sum",
        "solve_ahead": True,
        "time_limit": 3.0,
    }
    for name, key in (
        ("positions_yahoo_31822.csv", "positions_file"),
        ("adp_yahoo_31822.csv", "adp_file"),
    ):
        if (DATA / name).exists():
            session[key] = name
    app = create_app(SessionStore(), data_dir=DATA, fidelity_dir=tmp_path)
    with TestClient(app) as c:
        result = replay(
            c,
            picks,
            draft_id="2515267-real",
            slot=1,
            session=session,
            players_file="yahoo_players_31822.json",
            solve={"n": 3, "scenarios": 0, "time_limit": 3.0},
            plan_wait=15.0,
        )
    card = result["scorecard"]
    assert card["guardrails"]["G1"] == {"agree": 156, "of": 156, "total": 156}
    assert card["standins"] == 0 and card["conflicts"] == 0
    assert len(card["rows"]) == 13 and card["diagnostics"]["D5"] is not None


# --------------------------------------------------------------------------- helpers
def _events(directory: Path, draft_id: str) -> list[dict]:
    path = directory / "fidelity" / f"{draft_id}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _proj(client, sid) -> pd.DataFrame:
    board = client.get(f"/sessions/{sid}/board?limit=1000").json()["players"]
    return pd.DataFrame(
        {"player": [p["name"] for p in board], "team": [p["team"] for p in board]},
        index=[p["player_id"] for p in board],
    )
