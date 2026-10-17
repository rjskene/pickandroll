"""#67: a Yahoo league's folder in data/leagues/<id>/ sets up its sessions; a points league
drafts on one category, fantasy points from the league's weights; the user's own pre-arm in the
dashboard brings the league's draft room up in autopilot, and nothing else arms it."""

from __future__ import annotations

import json
import re
import shutil

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, leagues
from pickandroll.api.app import cors_origins
from pickandroll.optim.objective import SIMULATED_SOURCE, CategoryCurve
from pickandroll.optim.roster import ANY, GUARDS
from pickandroll.projections import POINTS_CAT, fantasy_points
from pickandroll.projections.schema import NINE_CAT, Cat

from .test_yahoo_room import build_league

ROSTER = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN", "IL", "IL"]
WEIGHTS = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}
#: What a league session sets for itself in these tests (no survival build, no solver).
QUICK = {"projection_file": "proj.csv", "solve_ahead": False, "survival": "none", "time_limit": 3.0}


def write_league(directory, league="555", players=True, **settings):
    folder = directory / "leagues" / league
    folder.mkdir(parents=True, exist_ok=True)
    body = {
        "league_id": int(league),
        "scoring": "points",
        "num_teams": 12,
        "draft": {"type": "live standard", "time": "2026-10-17T11:00:00-07:00", "pick_seconds": 60},
        "roster": ROSTER,
        "points": WEIGHTS,
        **settings,
    }
    (folder / "settings.json").write_text(json.dumps(body))
    if players:
        shutil.copy(directory / "yahoo_players_1.json", folder / "yahoo_players.json")
    return folder


@pytest.fixture
def league(tmp_path):
    build_league(tmp_path)
    write_league(tmp_path)
    return tmp_path


def app_for(directory):
    return TestClient(create_app(SessionStore(), data_dir=directory))


# --------------------------------------------------------------------------- the folder
def test_yahoo_roster_tokens_become_the_draft_slots():
    slots = leagues.league_slots(ROSTER)
    assert len(slots) == 13, "the injury slots are not drafted"
    assert [s.name for s in slots[:3]] == ["PG1", "SG1", "G1"]
    assert slots[2].eligible == GUARDS and slots[8].eligible == ANY and slots[-1].eligible == ANY
    with pytest.raises(leagues.LeagueError, match="unknown roster slot"):
        leagues.league_slots(["PG", "Rover"])


def test_session_defaults_from_the_folder(tmp_path):
    (tmp_path / "yahoo_players_1.json").write_text("[]")
    write_league(tmp_path)
    d = leagues.session_defaults(tmp_path, "555")
    players = "leagues/555/yahoo_players.json"
    assert d["num_teams"] == 12 and d["bench"] == 3, "Yahoo's default lineup keeps its names"
    assert d["points"] == WEIGHTS and "cats" not in d
    assert (d["adp_file"], d["positions_file"], d["adp_fallback_file"]) == (players,) * 3
    assert d["survival"] == "simulate", "another league's survival table is not this league's"
    (tmp_path / "leagues" / "555" / "survival_by_adp.csv").write_text("adp\n")
    d = leagues.session_defaults(tmp_path, "555")
    assert (d["survival"], d["survival_file"]) == ("league", "leagues/555/survival_by_adp.csv")

    write_league(
        tmp_path,
        "556",
        players=False,
        scoring="categories",
        categories=["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK"],
        roster=["PG", "C", "Util", "BN"],
    )
    d = leagues.session_defaults(tmp_path, "556")
    eight = [Cat.FG_PCT, Cat.FT_PCT, Cat.THREES, Cat.PTS, Cat.REB, Cat.AST, Cat.STL, Cat.BLK]
    assert d["cats"] == eight and "points" not in d
    assert "adp_file" not in d
    assert d["slots"] == [
        {"name": "PG1", "eligible": ["PG"]},
        {"name": "C1", "eligible": ["C"]},
        {"name": "UTIL1", "eligible": []},
        {"name": "BN1", "eligible": []},
    ]

    write_league(tmp_path, "557", players=False, points=None)
    with pytest.raises(leagues.LeagueError, match="needs its points weights"):
        leagues.session_defaults(tmp_path, "557")
    with pytest.raises(leagues.LeagueError, match="no league settings"):
        leagues.session_defaults(tmp_path, "999")


def test_fantasy_points_weigh_the_projection_columns():
    df = pd.DataFrame({"pts": [10.0, 20.0], "reb": [5.0, 0.0], "tov": [2.0, 4.0]})
    assert fantasy_points(df, {"pts": 1.0, "reb": 1.2, "tov": -1.0}).tolist() == [14.0, 16.0]
    with pytest.raises(ValueError, match="no projection column"):
        fantasy_points(df, {"dunks": 2.0})


def test_a_points_curve_says_its_default_is_flat():
    assert CategoryCurve.simulated(POINTS_CAT).source.startswith("flat default")
    assert CategoryCurve.simulated(NINE_CAT).source == SIMULATED_SOURCE
    mixed = CategoryCurve.simulated([Cat.PTS, Cat.FPTS]).source
    assert mixed == f"{SIMULATED_SOURCE}; flat default for fpts"


# --------------------------------------------------------------------------- a league session
def test_a_points_league_session_drafts_on_fantasy_points(league):
    folder = league / "leagues" / "555"
    # Yahoo's eligibility wins over the projections' positions file.
    raw = json.loads((folder / "yahoo_players.json").read_text())
    first = raw["service"]["player_list"][0]
    first["pos"] = ["C", "Util"]
    (folder / "yahoo_players.json").write_text(json.dumps(raw))
    with app_for(league) as c:
        r = c.post("/sessions", json={**QUICK, "league": "555"})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["cats"] == ["fpts"] and s["league"] == "555" and s["points"] == WEIGHTS
        assert s["num_teams"] == 12 and s["adp_source"] == "file:yahoo_players.json"
        board = c.get(f"/sessions/{s['id']}/board?limit=400").json()["players"]
        proj = c.app.state.store.get(s["id"]).state.projections.df
        for p in board[:20]:
            expected = sum(w * float(proj.at[p["player_id"], k]) for k, w in WEIGHTS.items())
            assert p["fpts"] == round(expected, 1)
            assert set(p["z"]) == {"fpts"}
        named = f"{first['fname']} {first['lname']}"
        assert next(p for p in board if p["name"] == named)["positions"] == "C"
        rec = c.post(f"/sessions/{s['id']}/recommend", json={"n": 3, "scenarios": 0})
        assert rec.status_code == 200, rec.text

        # Yahoo's stat names are read as the projection's columns.
        body = {**QUICK, "league": "555", "points": {"PTS": 1, "ST": 2, "TO": -1}}
        s = c.post("/sessions", json=body).json()
        assert s["points"] == {"PTS": 1.0, "ST": 2.0, "TO": -1.0} and s["cats"] == ["fpts"]


def test_a_points_session_is_checked(league):
    with app_for(league) as c:
        both = {**QUICK, "points": WEIGHTS, "cats": ["pts", "reb"]}
        r = c.post("/sessions", json=both)
        assert r.status_code == 400 and "leave cats out" in r.json()["detail"]
        r = c.post("/sessions", json={**QUICK, "cats": ["fpts"]})
        assert r.status_code == 400 and "points weights" in r.json()["detail"]
        r = c.post("/sessions", json={**QUICK, "points": {"dunks": 2.0}})
        assert r.status_code == 400 and "no projection column" in r.json()["detail"]
        r = c.post("/sessions", json={**QUICK, "league": "999"})
        assert r.status_code == 400 and "no league settings" in r.json()["detail"]
        assert c.post("/sessions", json={**QUICK, "league": "../x"}).status_code == 422
        # A request's own categories win over the folder's points.
        s = c.post("/sessions", json={**QUICK, "league": "555", "cats": ["pts", "reb"]}).json()
        assert s["cats"] == ["pts", "reb"] and s["points"] is None


# --------------------------------------------------------------------------- the form (#74)
def test_the_dashboard_lists_what_a_league_session_resolves_to(tmp_path):
    (tmp_path / "yahoo_players_1.json").write_text("[]")
    write_league(tmp_path)
    write_league(tmp_path, "556", roster=["PG", "Rover"])

    def resolved():
        with app_for(tmp_path) as c:
            rows = {row["league"]: row for row in c.get("/leagues").json()}
        # A roster that does not read lists the league with the reason, not a failed list.
        assert rows["556"]["resolved"] is None and "unknown roster slot" in rows["556"]["error"]
        assert rows["555"]["error"] is None
        return rows["555"]["resolved"]

    players = "leagues/555/yahoo_players.json"
    r = resolved()
    assert (r["survival"], r["survival_file"], r["note"], r["blend"]) == (
        "simulate",
        None,
        None,
        None,
    )
    assert (r["curve"], r["curve_drafts"], r["rounds"]) == ("simulated", None, 13)
    assert (r["adp_file"], r["positions_file"]) == (players, players)

    shared = leagues.shared_dir(tmp_path, "points")
    shared.mkdir(parents=True)
    report = {"table": None, "reason": "0.5 drafts, 18.5 players near ADP 90, under 20"}
    (shared / leagues.SURVIVAL_REPORT).write_text(json.dumps(report))
    assert resolved()["note"] == "archive: 0.5 drafts, 18.5 players near ADP 90, under 20"

    # The format's table, blended, with rosters in the other format's archive: league odds and
    # the league curve, as the draft-day attach asks for them.
    header = ",".join(["adp", *map(str, range(1, 157)), "undrafted"])
    (shared / leagues.SURVIVAL).write_text(header + "\n")
    blend = {"drafts": 1.5, "same_format": 1, "other_format": 1, "weight": 0.5}
    (shared / leagues.SURVIVAL_REPORT).write_text(json.dumps({"table": "t", "blend": blend}))
    assert resolved()["curve"] == "simulated", "no rosters in either archive yet"
    other = leagues.shared_dir(tmp_path, "categories")
    other.mkdir(parents=True)
    (other / leagues.PICKS).write_text("overall\n")
    r = resolved()
    assert (r["survival"], r["survival_file"]) == (
        "league",
        "leagues/_shared/points/survival_by_adp.csv",
    )
    assert (r["note"], r["blend"], r["curve"], r["curve_drafts"]) == (None, blend, "league", 1.5)

    # The league's own table: its own odds, no blend, the simulated curve.
    (tmp_path / "leagues" / "555" / leagues.SURVIVAL).write_text(header + "\n")
    r = resolved()
    assert (r["survival"], r["survival_file"]) == ("league", "leagues/555/survival_by_adp.csv")
    assert (r["blend"], r["curve"]) == (None, "simulated")


# --------------------------------------------------------------------------- the user's arm
def test_the_dashboard_arms_and_disarms_a_league(league):
    with app_for(league) as c:
        listed = c.get("/leagues").json()
        assert [(x["league"], x["scoring"], x["armed"]) for x in listed] == [
            ("555", "points", None)
        ]
        assert listed[0]["draft_time"] == "2026-10-17T11:00:00-07:00"
        assert listed[0]["players_file"] is True and listed[0]["survival_file"] is False
        r = c.put("/leagues/555/arm", json={"armed": True})
        assert r.status_code == 200, r.text
        assert r.json()["armed"]["by"] == "dashboard"
        record = json.loads((league / "leagues" / "555" / "armed.json").read_text())
        assert record["armed"] is True and record["at"]
        assert c.get("/leagues/555").json()["armed"] == record
        assert c.put("/leagues/555/arm", json={"armed": False}).json()["armed"] is None
        assert not (league / "leagues" / "555" / "armed.json").exists()
        assert c.put("/leagues/999/arm", json={"armed": True}).status_code == 404
        assert c.get("/leagues/999").status_code == 404
        assert c.put("/leagues/x1/arm", json={"armed": True}).status_code == 422


def _attach(c, draft_id="555", **extra):
    body = {"draft_id": draft_id, "slot": 4, "clock_s": 60, "session": {**QUICK, "league": "555"}}
    r = c.post("/rooms", json={**body, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_pre_armed_league_room_comes_up_in_autopilot(league):
    (league / "leagues" / "555" / "armed.json").write_text(json.dumps({"armed": True, "at": "t"}))
    with app_for(league) as c:
        room = _attach(c)
        assert room["mode"] == "autopilot"
        assert room["session"]["league"] == "555" and room["session"]["cats"] == ["fpts"]
        assert room["players_file"] == "leagues/555/yahoo_players.json"
        # Another draft id for the league's session, or a mode the attach names, is not armed.
        assert _attach(c, draft_id="777")["mode"] == "mirror"
        assert _attach(c, draft_id="778", mode="mirror")["mode"] == "mirror"
        assert room["pre_armed"] == {"armed": True, "at": "t"}
        assert _attach(c, draft_id="779", mode="mirror")["pre_armed"] is None
        # The user switches to mirror; the status still says how the room came up.
        assert c.patch("/rooms/555", json={"mode": "mirror"}).json()["mode"] == "mirror"
    log = (league / "fidelity" / "555.jsonl").read_text().splitlines()
    attach = next(json.loads(line) for line in log if json.loads(line)["type"] == "attach")
    assert attach["pre_armed"]["armed"] is True
    # A rebuild keeps the mode last set and the pre-arm on record.
    with app_for(league) as c:
        r = c.post("/rooms", json={"draft_id": "555"})
        assert r.status_code == 201, r.text
        assert r.json()["mode"] == "mirror" and r.json()["pre_armed"]["at"] == "t"


def test_an_unarmed_league_room_mirrors_and_a_later_arm_waits_for_the_next_draft(league):
    with app_for(league) as c:
        assert _attach(c)["mode"] == "mirror"
    (league / "leagues" / "555" / "armed.json").write_text(json.dumps({"armed": True, "at": "t"}))
    # A rebuild from the log keeps the mode it had; the pre-arm is read on a first attach only.
    with app_for(league) as c:
        r = c.post("/rooms", json={"draft_id": "555"})
        assert r.status_code == 201, r.text
        assert r.json()["session"]["league"] == "555" and r.json()["mode"] == "mirror"
        assert r.json()["pre_armed"] is None


# --------------------------------------------------------------------------- phone access
def test_cors_takes_the_extra_origins_exactly():
    pattern = re.compile(cors_origins("http://100.64.0.7:5173, https://mac.tail1234.ts.net"))
    assert pattern.fullmatch("http://100.64.0.7:5173")
    assert pattern.fullmatch("https://mac.tail1234.ts.net")
    assert pattern.fullmatch("http://localhost:5173")
    assert not pattern.fullmatch("http://100.64.0.7:5173.evil.example")
    assert not pattern.fullmatch("http://100.64.0.70:5173")
    assert cors_origins("") == cors_origins(" , ")
