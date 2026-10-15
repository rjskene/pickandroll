"""Players the ADP list lacks: their rank from another source (Yahoo's o_rank, or a ranks file)
mapped onto the list's ADP scale, never the projections' rank."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.availability import rank_to_adp
from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.projections import ProjectionSet

DATA = Path(__file__).resolve().parents[1] / "data"
SAMPLE = "bbm_sample_ros_totals.xls"


# --------------------------------------------------------------------------- the map
def test_rank_to_adp_fits_an_increasing_map_and_extends_it():
    adp = pd.Series(
        {"a": 1.0, "b": 2.0, "c": 4.0, "d": 3.0, "e": 6.0, "f": 8.0, "o": 7.0, "x": 5.0}
    )
    rank = pd.Series(
        {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "o": 40}
        | {"g": 2.5, "h": 10, "i": 0.5, "j": 4.5}  # the ones the list lacks
    )
    out = rank_to_adp(rank, adp)
    # Only the ranked players the list lacks ("x" has an ADP and no rank: not in the map).
    assert sorted(out.index) == ["g", "h", "i", "j"]
    # c and d break the order: both take their mean, 3.5.
    assert out["g"] == pytest.approx(2.75)  # halfway between rank 2 (2.0) and rank 3 (3.5)
    assert out["j"] == pytest.approx(4.75)  # halfway between rank 4 (3.5) and rank 5 (6.0)
    # Past the last pair, one pick per rank. "o" is listed but ranked far past the list's
    # length: in the fit, pooled with "f", he would hold everyone ranked 6 to 40 at 7.5.
    assert out["h"] == pytest.approx(12.0)
    assert out["i"] == pytest.approx(1.0)  # before the first, never below pick one
    ordered = out.sort_index(key=lambda idx: rank[idx])
    assert ordered.is_monotonic_increasing


def test_rank_to_adp_needs_two_shared_players():
    adp = pd.Series({"a": 1.0, "b": 2.0})
    assert rank_to_adp(pd.Series({"a": 1, "c": 3}), adp).empty
    assert rank_to_adp(pd.Series({"a": 1, "b": 2}), adp).empty  # nobody to map


# --------------------------------------------------------------------------- the state
def make_state(pool) -> DraftState:
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    return DraftState(
        settings=LeagueSettings(num_teams=4), projections=ps, my_team="me", my_position=2
    )


def test_the_state_prices_players_the_list_lacks_by_their_rank(pool):
    state = make_state(pool)
    order = list(state.z["total"].sort_values(ascending=False).index)
    listed = [p for i, p in enumerate(order[:40]) if i not in (5, 12)]
    state.set_adp(pd.Series({p: float(order.index(p) + 1) for p in listed}), "test")
    standin = state.effective_adp()
    assert state.adp_origin().value_counts().to_dict() == {"market": 38, "stand-in": 22}

    # Yahoo-style ranks for the first 50: the two the list lacks fill its gaps, the rest follow
    # it; the last ten are on neither list.
    state.set_adp_rank(pd.Series({p: float(i + 1) for i, p in enumerate(order[:50])}), "o_rank:t")
    adp = state.effective_adp()
    assert adp.notna().all()
    origin = state.adp_origin()
    assert origin.value_counts().to_dict() == {"market": 38, "rank": 12, "end": 10}
    assert (adp[order[5]], adp[order[12]]) == (6.0, 13.0)  # the list is the identity here
    assert adp[order[44]] == pytest.approx(45.0)  # past the list's last rank, a pick per rank
    assert (adp[origin == "end"] == state.settings.total_picks + 1).all()
    # The value-rank stand-in is gone: it put a player neither list knows at his z rank.
    assert (standin[order[55]], adp[order[55]]) == (56.0, 53.0)

    # A new ADP list (the Yahoo feed's) re-maps the same ranks.
    state.set_adp(pd.Series({p: 2.0 * (order.index(p) + 1) for p in listed}), "yahoo")
    assert state.effective_adp()[order[5]] == pytest.approx(12.0)


# --------------------------------------------------------------------------- the API
@pytest.fixture
def data_dir(tmp_path):
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    (tmp_path / SAMPLE).symlink_to(DATA / SAMPLE)
    return tmp_path


def _top(data_dir, n):
    """The sample's first ``n`` players by total z, with names and teams."""
    with TestClient(create_app(SessionStore(), data_dir=data_dir)) as c:
        body = {"projection_file": SAMPLE, "num_teams": 4, "solve_ahead": False}
        sid = c.post("/sessions", json={**body, "survival": "none"}).json()["id"]
        board = c.get(f"/sessions/{sid}/board?limit={n}").json()["players"]
    return [(p["player_id"], p["name"], p["team"]) for p in board]


def _players_json(path, players):
    """A Yahoo players response: these players, ranked in this order (o_rank)."""
    items = []
    for i, (_, name, team) in enumerate(players, start=1):
        first, _, last = name.partition(" ")
        items.append(
            {"id": 9000 + i, "fname": first, "lname": last, "team_abbr": team, "o_rank": i}
        )
    path.write_text(json.dumps({"service": {"player_list": items}}))


def test_a_session_ranks_the_players_its_adp_file_lacks(data_dir):
    top = _top(data_dir, 14)
    missing = {3, 7}
    lines = ["player,adp"] + [
        f"{name},{i + 1}" for i, (_, name, _) in enumerate(top[:12]) if i not in missing
    ]
    (data_dir / "adp.csv").write_text("\n".join(lines) + "\n")
    _players_json(data_dir / "yahoo_players_test.json", top)
    body = {"projection_file": SAMPLE, "num_teams": 4, "solve_ahead": False, "survival": "none"}
    with TestClient(create_app(SessionStore(), data_dir=data_dir)) as c:
        # Left out, the fallback is the newest Yahoo players file: its o_rank.
        s = c.post("/sessions", json=body).json()
        assert (s["adp_source"], s["adp_known"]) == ("file:adp.csv", 10)
        assert s["adp_fallback"] == 4
        assert s["adp_fallback_source"] == "o_rank:yahoo_players_test.json"
        rows = {
            p["player_id"]: p
            for p in c.get(f"/sessions/{s['id']}/board?limit=300").json()["players"]
        }
        by_rank = {top[i][0]: rows[top[i][0]] for i in range(14)}
        for i, (pid, _, _) in enumerate(top):
            expected = "market" if i < 12 and i not in missing else "rank"
            assert by_rank[pid]["adp_from"] == expected, (i, by_rank[pid])
        # The list is the identity on the ranks both know: the gaps fill at their rank, and
        # past the list's last rank a pick per rank.
        assert [by_rank[top[i][0]]["adp"] for i in (3, 7, 12, 13)] == [4.0, 8.0, 13.0, 14.0]
        rest = [p for pid, p in rows.items() if pid not in by_rank]
        assert rest and all(p["adp_from"] == "end" and p["adp"] == 53.0 for p in rest)

        # A ranks file named in the request wins, read as a rank (player,adp).
        ranks = ["player,adp"] + [f"{name},{i + 1}" for i, (_, name, _) in enumerate(top)]
        (data_dir / "ranks.csv").write_text("\n".join(ranks) + "\n")
        s = c.post("/sessions", json={**body, "adp_fallback_file": "ranks.csv"}).json()
        assert (s["adp_fallback"], s["adp_fallback_source"]) == (4, "rank:ranks.csv")
        r = c.post("/sessions", json={**body, "adp_fallback_file": "nope.csv"})
        assert r.status_code == 400 and "ADP fallback file not found" in r.json()["detail"]
        r = c.post("/sessions", json={**body, "adp_fallback_file": "../ranks.csv"})
        assert r.status_code == 400 and "must be a path inside data/" in r.json()["detail"]

    # No ADP list: nothing to map the ranks onto, and the board keeps the value-rank stand-in.
    (data_dir / "adp.csv").unlink()
    with TestClient(create_app(SessionStore(), data_dir=data_dir)) as c:
        s = c.post("/sessions", json=body).json()
        assert (s["adp_fallback"], s["adp_fallback_source"]) == (0, None)
        board = c.get(f"/sessions/{s['id']}/board?limit=5").json()["players"]
        assert {p["adp_from"] for p in board} == {"stand-in"}


def test_the_drafted_players_all_have_an_adp_with_the_fallback(data_dir):
    """Every player a draft takes has an ADP from the list or the rank map, none past the end,
    when the rank source knows them all (the real draft's check, on the sample)."""
    top = _top(data_dir, 30)
    lines = ["player,adp"] + [f"{name},{i + 1}" for i, (_, name, _) in enumerate(top) if i % 7 != 3]
    (data_dir / "adp.csv").write_text("\n".join(lines) + "\n")
    _players_json(data_dir / "yahoo_players_test.json", top)
    body = {"projection_file": SAMPLE, "num_teams": 4, "solve_ahead": False, "survival": "none"}
    with TestClient(create_app(SessionStore(), data_dir=data_dir)) as c:
        sid = c.post("/sessions", json=body).json()["id"]
        for i, (pid, _, _) in enumerate(top[:20]):
            team = "me" if c.get(f"/sessions/{sid}").json()["on_the_clock"] else f"Team {i}"
            r = c.post(f"/sessions/{sid}/picks", json={"team": team, "player_id": pid})
            assert r.status_code in (200, 201), r.text
        board = c.get(f"/sessions/{sid}/board?limit=300").json()["players"]
        drafted = [p for p in board if p["taken"]]
        assert len(drafted) == 20
        assert all(p["adp"] is not None and p["adp_from"] in ("market", "rank") for p in drafted)
        assert sum(p["adp_from"] == "rank" for p in drafted) == 3
        assert c.get(f"/sessions/{sid}").json()["adp_fallback"] == 4
