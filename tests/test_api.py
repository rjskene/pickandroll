from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app

DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture
def client():
    if not (DATA / "bbm_sample_ros_totals.xls").exists():
        pytest.skip("no Basketball Monster sample export in data/")
    app = create_app(SessionStore(), data_dir=DATA)
    with TestClient(app) as c:
        yield c


def create(client, **overrides):
    """A small league on the sample export. Background solving is off unless a test asks
    for it, so the score history holds exactly the solves the test makes."""
    body = {
        "projection_file": "bbm_sample_ros_totals.xls",
        "num_teams": 4,
        "my_position": 2,
        "solve_ahead": False,
        "time_limit": 4.0,
    }
    body.update(overrides)
    r = client.post("/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_and_projection_listing(client):
    assert client.get("/health").json()["status"] == "ok"
    files = [f["file"] for f in client.get("/projections").json()]
    assert "bbm_sample_ros_totals.xls" in files


def test_create_session_and_board(client):
    s = create(client)
    assert s["num_teams"] == 4 and s["roster_size"] == 13 and s["my_picks"][0] == 2
    board = client.get(f"/sessions/{s['id']}/board?limit=5").json()
    assert len(board["players"]) == 5
    assert board["players"][0]["total"] >= board["players"][1]["total"]


def test_bad_projection_file_and_position(client):
    r = client.post("/sessions", json={"projection_file": "nope.xls"})
    assert r.status_code == 400
    r = client.post(
        "/sessions",
        json={"projection_file": "bbm_sample_ros_totals.xls", "num_teams": 4, "my_position": 9},
    )
    assert r.status_code == 400


def test_pick_flow_and_recommendation(client):
    s = create(client)
    sid = s["id"]
    assert s["objective"] == "win" and s["curve"]["source"].startswith("simulated league")
    assert s["availability_source"] == "adp" and s["survival"]["mode"] == "none"
    board = client.get(f"/sessions/{sid}/board?limit=3").json()["players"]
    first = client.post(
        f"/sessions/{sid}/picks", json={"team": "a", "player_id": board[0]["player_id"]}
    )
    assert first.status_code == 201 and first.json()["overall"] == 1
    dup = client.post(
        f"/sessions/{sid}/picks", json={"team": "b", "player_id": board[0]["player_id"]}
    )
    assert dup.status_code == 400
    summary = client.get(f"/sessions/{sid}").json()
    assert summary["on_the_clock"] is True and summary["next_overall"] == 2

    rec = client.post(f"/sessions/{sid}/recommend", json={"n": 4, "scenarios": 0}).json()
    assert rec["on_the_clock"] is True
    assert rec["mode"] == "horizon" and rec["objective"] == "win" and rec["scale"] == "wins"
    assert len(rec["candidates"]) >= 4
    top = rec["candidates"][0]
    assert {"cost_vs_best", "cost_first_order", "p_available_next", "time_limited"} <= set(top)
    assert top["cost_vs_best"] == 0.0
    planned = next(c for c in rec["candidates"] if c["player"] == rec["plan"][0]["player"])
    assert planned["cost_first_order"] == 0.0
    assert board[0]["player_id"] not in [c["player"] for c in rec["candidates"]]
    assert len(rec["best_roster"]["roster"]) == 13
    assert 0.0 < rec["best_roster"]["wins"] <= 9.0 and rec["wins"] == rec["best_roster"]["wins"]
    assert [p["pick"] for p in rec["plan"]] == s["my_picks"]
    assert rec["plan"][0]["availability"] == 1.0
    assert rec["adp_source"] == "bbm_rank" and rec["scenarios"] == []
    cats = rec["categories"]
    assert [c["cat"] for c in cats] == s["cats"]
    assert all(c["label"] in {"conceded", "contested", "secured"} for c in cats)
    assert all(0.0 <= c["odds"] <= 1.0 and c["slope"] >= 0.0 for c in cats)
    assert all(c["drafted"] == 0.0 and 0 <= c["beaten_now"] <= 3 for c in cats)
    league = rec["league"]
    assert len(league["opponents"]) == 3 and 0 <= league["matchups_won"] <= 3
    assert set(league["teams_beaten"]) == set(s["cats"])
    assert rec["score"]["wins"] == rec["wins"]

    roster_mode = client.post(
        f"/sessions/{sid}/recommend", json={"n": 4, "horizon": False, "scenarios": 0}
    ).json()
    assert roster_mode["mode"] == "roster" and roster_mode["plan"] == []
    assert len(roster_mode["categories"]) == 9

    mine = client.post(
        f"/sessions/{sid}/picks", json={"team": "me", "player_id": rec["candidates"][0]["player"]}
    )
    assert mine.status_code == 201
    assert client.get(f"/sessions/{sid}").json()["my_roster"] == [rec["candidates"][0]["player"]]

    undone = client.delete(f"/sessions/{sid}/picks/last").json()
    assert undone["player_id"] == rec["candidates"][0]["player"]
    assert client.get(f"/sessions/{sid}").json()["my_roster"] == []


def test_sync_applies_feed(client):
    s = create(client)
    sid = s["id"]
    board = client.get(f"/sessions/{sid}/board?limit=3").json()["players"]
    feed = [[1, "a", board[0]["player_id"]], [2, "me", board[1]["player_id"]]]
    r = client.post(f"/sessions/{sid}/sync", json={"picks": feed})
    assert [p["overall"] for p in r.json()["added"]] == [1, 2]
    r = client.post(f"/sessions/{sid}/sync", json={"picks": feed})
    assert r.json()["added"] == []
    assert len(client.get(f"/sessions/{sid}/picks").json()) == 2


def test_events_stream_receives_pick():
    """SSE needs a real server: Starlette's TestClient buffers whole responses."""
    if not (DATA / "bbm_sample_ros_totals.xls").exists():
        pytest.skip("no Basketball Monster sample export in data/")
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    app = create_app(SessionStore(), data_dir=DATA)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    base = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            s = create(client)
            sid = s["id"]
            board = client.get(f"/sessions/{sid}/board?limit=1").json()["players"]
            with client.stream("GET", f"/sessions/{sid}/events") as stream:
                lines = stream.iter_lines()
                assert next(line for line in lines if line.startswith("event:")) == "event: hello"
                client.post(
                    f"/sessions/{sid}/picks", json={"team": "a", "player_id": board[0]["player_id"]}
                )
                event = next(line for line in lines if line.startswith("event:"))
                assert event == "event: pick"
                data = next(line for line in lines if line.startswith("data:"))
                assert board[0]["player_id"] in data
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_yahoo_feed_attach_and_poll(client):
    from pickandroll.sources.yahoo import YahooLeague

    from .fakes import FakeQuery

    fake = FakeQuery(names=["Nikola Jokic", "Luka Doncic", "Nobody Real"])
    app = create_app(
        SessionStore(), data_dir=DATA, league_factory=lambda lid: YahooLeague(lid, query=fake)
    )
    with TestClient(app) as c:
        s = create(c, num_teams=12, my_position=5, objective="sum")
        sid = s["id"]
        r = c.post(f"/sessions/{sid}/yahoo", json={"league_id": "12345", "start": False})
        assert r.status_code == 201, r.text
        status = r.json()
        assert status["matched"] == 2
        assert [u["name"] for u in status["unmatched_yahoo"]] == ["Nobody Real"]
        # Attaching adopts the Yahoo team name and draft position of the team I own.
        assert status["session"]["my_team"] == "Me" and status["session"]["my_position"] == 2

        fake.picks = [("466.l.12345.t.2", "466.p.0"), ("466.l.12345.t.1", "466.p.1")]
        r = c.post(f"/sessions/{sid}/yahoo/poll")
        assert r.status_code == 200, r.text
        applied = r.json()["applied"]
        assert [(p["overall"], p["team"], p["name"]) for p in applied] == [
            (1, "Them", "Nikola Jokic"),
            (2, "Me", "Luka Doncic"),
        ]
        summary = c.get(f"/sessions/{sid}").json()
        assert summary["picks_made"] == 2 and len(summary["my_roster"]) == 1
        # Yahoo ADP for matched players now drives availability.
        rec = c.post(f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0}).json()
        assert rec["adp_source"] == "yahoo" and rec["objective"] == "sum"

        # Same feed again applies nothing; an unmapped player is reported, not applied.
        fake.picks.append(("466.l.12345.t.2", "466.p.2"))
        r = c.post(f"/sessions/{sid}/yahoo/poll").json()
        assert r["applied"] == []
        assert r["unmapped_picks"][0]["name"] == "Nobody Real"
        assert c.get(f"/sessions/{sid}/yahoo").json()["polls"] == 2
        assert c.delete(f"/sessions/{sid}/yahoo").json() == {"attached": False}
        assert c.get(f"/sessions/{sid}/yahoo").json() == {"attached": False}


def test_create_session_from_csv_with_positions(client):
    files = sorted(DATA.glob("bbm_projections_*.csv"))
    if not files or not (DATA / "bbm_sample_ros_totals.xls").exists():
        pytest.skip("no Basketball Monster CSV in data/")
    listing = client.get("/projections").json()
    assert any(f["kind"] == "csv" for f in listing)
    s = create(client, projection_file=files[-1].name, positions_file="bbm_sample_ros_totals.xls")
    assert s["unknown_positions"] < 586
    board = client.get(f"/sessions/{s['id']}/board?limit=3").json()["players"]
    assert board[0]["positions"] != "" or board[1]["positions"] != ""
    rec = client.post(f"/sessions/{s['id']}/recommend", json={"n": 3, "scenarios": 0}).json()
    assert rec["mode"] == "horizon" and len(rec["candidates"]) >= 3
    r = client.post(
        "/sessions", json={"projection_file": files[-1].name, "positions_file": "nope.csv"}
    )
    assert r.status_code == 400


def test_events_stream_ends_on_shutdown():
    """A reload or Ctrl-C must not wait forever on open event streams."""
    if not (DATA / "bbm_sample_ros_totals.xls").exists():
        pytest.skip("no Basketball Monster sample export in data/")
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    app = create_app(SessionStore(), data_dir=DATA)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=2
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        s = create(client)
        with client.stream("GET", f"/sessions/{s['id']}/events") as stream:
            lines = stream.iter_lines()
            assert next(line for line in lines if line.startswith("event:")) == "event: hello"
            server.should_exit = True
            started = time.time()
            try:
                for line in lines:
                    if line.startswith("event:"):
                        break
            except httpx.HTTPError:
                pass  # the server force-closed the stream after the graceful timeout
            assert time.time() - started < 8
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_recommend_reports_timings_and_prices_without_bumping_version(client):
    s = create(client)
    sid = s["id"]
    before = client.get(f"/sessions/{sid}").json()["version"]
    rec = client.post(f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0}).json()
    assert rec["mode"] == "horizon"
    assert {"plan_ms", "candidates_ms", "total_ms", "solver_players"} <= set(rec["timings"])
    assert client.get(f"/sessions/{sid}").json()["version"] == before
    # The latest solve is kept and served; the board carries first-order deviation costs.
    latest = client.get(f"/sessions/{sid}/recommendation").json()
    assert latest["solved_version"] == before and latest["stale"] is False
    assert latest["recommendation"]["candidates"] == rec["candidates"]
    board = client.get(f"/sessions/{sid}/board?limit=20").json()
    assert board["prices_version"] == before and board["scale"] == "wins"
    costs = {p["player_id"]: p["cost"] for p in board["players"]}
    assert costs[rec["plan"][0]["player"]] == 0.0
    assert all(c is None or c >= 0.0 for c in costs.values())
    # A solve on the sum objective prices on the z scale instead.
    plain = client.post(
        f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0, "objective": "sum"}
    ).json()
    assert plain["objective"] == "sum" and plain["scale"] == "z"
    assert plain["best_roster"]["value"] > 1.0


def test_autopick_simulates_other_teams(client):
    s = create(client)  # 4 teams, I pick second
    sid = s["id"]
    r = client.post(f"/sessions/{sid}/autopick", json={"noise": 0.0})
    assert r.status_code == 200, r.text
    added = r.json()["added"]
    assert [p["overall"] for p in added] == [1]
    assert added[0]["team"] == "Team 1"
    assert client.get(f"/sessions/{sid}").json()["on_the_clock"] is True
    # On the clock: a plain "sim to my pick" is refused, an explicit count still works.
    assert client.post(f"/sessions/{sid}/autopick", json={}).status_code == 400
    r = client.post(
        f"/sessions/{sid}/autopick", json={"count": 1, "until_my_pick": False, "seed": 1}
    )
    assert r.json()["added"][0]["team"] == "me"
    board = client.get(f"/sessions/{sid}/board?limit=3").json()
    assert board["next_pick"] == 7
    assert 0.0 <= board["players"][0]["p_next"] <= 1.0
    assert board["players"][0]["adp"] is not None


def test_score_benchmark_freezes_at_my_first_pick(client):
    s = create(client, objective="sum")  # 4 teams, I pick second: my picks are 2, 7, 10, 15, ...
    sid = s["id"]
    assert client.get(f"/sessions/{sid}/score").json()["benchmark"] is None
    client.post(f"/sessions/{sid}/autopick", json={"noise": 0.0, "strategy": "z"})
    first = client.post(f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0}).json()
    score = client.get(f"/sessions/{sid}/score").json()
    assert score["benchmark"]["wins"] == first["wins"]
    assert score["benchmark"]["value"] == first["value"]
    assert score["benchmark"]["next_overall"] == 2 and score["benchmark"]["on_the_clock"]
    assert score["drafted"] == 0 and score["drafted_wins"] == 0.0 and score["final"] is None
    # Draft the recommendation, let the others pick, solve again: the benchmark stays put.
    top = first["candidates"][0]["player"]
    client.post(f"/sessions/{sid}/picks", json={"team": "me", "player_id": top})
    client.post(f"/sessions/{sid}/autopick", json={"noise": 0.0, "strategy": "lp", "seed": 1})
    second = client.post(f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0}).json()
    score = client.get(f"/sessions/{sid}/score").json()
    assert score["benchmark"]["wins"] == first["wins"]
    assert score["latest"]["wins"] == second["wins"]
    assert score["best"]["wins"] == max(first["wins"], second["wins"])
    assert score["drafted"] == 1 and score["drafted_wins"] > 0 and score["drafted_value"] > 0
    assert [h["next_overall"] for h in score["history"]] == [2, 7]
    assert score["current_wins"] == score["latest"]["wins"]
    assert score["vs_benchmark"] == round(score["current_wins"] - score["benchmark"]["wins"], 4)
    assert all("matchups" in h for h in score["history"])


def test_recommend_refuses_when_no_picks_left_and_score_is_final(client):
    s = create(client, num_teams=4, my_position=1)
    sid = s["id"]
    client.post(
        f"/sessions/{sid}/autopick", json={"until_my_pick": False, "noise": 0.0, "strategy": "z"}
    )
    assert client.get(f"/sessions/{sid}").json()["complete"] is True
    r = client.post(f"/sessions/{sid}/recommend", json={"n": 3})
    assert r.status_code == 400
    score = client.get(f"/sessions/{sid}/score").json()
    final = score["final"]
    assert score["drafted"] == 13 and final is not None
    assert final["wins"] == score["drafted_wins"] and 0.0 <= final["wins"] <= 9.0
    assert len(final["opponents"]) == 3 and 0 <= final["matchups"] <= 3
    assert [c["cat"] for c in final["categories"]] == s["cats"]
    assert all(c["drafted"] == c["expected"] for c in final["categories"])
    assert score["current_wins"] == final["wins"]


def test_session_options_sum_objective_curve_file_and_sigma(tmp_path):
    import json
    import shutil

    sample = DATA / "bbm_sample_ros_totals.xls"
    if not sample.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    shutil.copy(sample, tmp_path / sample.name)
    mu = {c: 0.5 for c in ["pts", "threes", "reb", "ast", "stl", "blk", "tov", "fg_pct", "ft_pct"]}
    (tmp_path / "curve.json").write_text(json.dumps({"mu": mu, "sigma": dict.fromkeys(mu, 3.0)}))
    app = create_app(SessionStore(), data_dir=tmp_path)
    with TestClient(app) as client:
        base = {"projection_file": sample.name, "num_teams": 4, "solve_ahead": False}
        plain = client.post("/sessions", json={**base, "objective": "sum"}).json()
        assert plain["objective"] == "sum" and plain["curve"] is None
        curved = client.post(
            "/sessions", json={**base, "curve_file": "curve.json", "sigma_scale": 2.0}
        ).json()
        assert curved["objective"] == "win"
        assert curved["curve"]["mu"]["pts"] == 0.5 and curved["curve"]["sigma"]["pts"] == 6.0
        assert curved["curve"]["source"] == "file:curve.json, sigma x2"
        assert client.get("/files?kind=curve").json()[0]["file"] == "curve.json"
        r = client.post("/sessions", json={**base, "curve_file": "nope.json"})
        assert r.status_code == 400


def test_survival_file_option(tmp_path):
    import shutil

    import pandas as pd

    from pickandroll.availability import SurvivalTable

    sample = DATA / "bbm_sample_ros_totals.xls"
    if not sample.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    shutil.copy(sample, tmp_path / sample.name)
    picks = pd.DataFrame(
        {"sim": [1, 1], "player": ["james-harden", "anthony-davis"], "overall": [1, 2]}
    )
    SurvivalTable.from_pick_numbers(picks, total_picks=52, sims=1).save(tmp_path / "surv.csv")
    app = create_app(SessionStore(), data_dir=tmp_path)
    with TestClient(app) as client:
        assert [f["file"] for f in client.get("/files?kind=survival").json()] == ["surv.csv"]
        base = {"projection_file": sample.name, "num_teams": 4, "solve_ahead": False}
        r = client.post("/sessions", json={**base, "survival": "file", "survival_file": "surv.csv"})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["availability_source"] == "survival"
        assert s["survival"] == {
            "mode": "file",
            "status": "ready",
            "sims": 1,
            "source": "file:surv.csv",
        }
        r = client.post(
            "/sessions",
            json={**base, "num_teams": 6, "survival": "file", "survival_file": "surv.csv"},
        )
        assert r.status_code == 400 and "52 picks" in r.json()["detail"]
        r = client.post("/sessions", json={**base, "survival": "file"})
        assert r.status_code == 400


def test_teams_endpoint_tallies_the_league(client):
    s = create(client)
    sid = s["id"]
    client.post(f"/sessions/{sid}/autopick", json={"noise": 0.0, "strategy": "z"})
    teams = client.get(f"/sessions/{sid}/teams").json()
    assert teams["my_final_from"] == "replacement fill"
    rows = teams["teams"]
    assert [r["position"] for r in rows] == [1, 2, 3, 4]
    mine = next(r for r in rows if r["mine"])
    assert mine["team"] == "me" and mine["cats_beaten"] is None and mine["picks"] == 0
    other = next(r for r in rows if r["position"] == 1)
    assert other["team"] == "Team 1" and other["picks"] == 1 and other["cats_beaten"] is not None
    assert set(other["totals"]) == set(s["cats"]) and set(other["projected"]) == set(s["cats"])
    assert 0 <= teams["matchups_won"] <= 3
    rec = client.post(f"/sessions/{sid}/recommend", json={"n": 3, "scenarios": 0}).json()
    teams = client.get(f"/sessions/{sid}/teams").json()
    assert teams["my_final_from"] == "plan"
    assert teams["matchups_won"] == rec["league"]["matchups_won"]


def test_solve_ahead_builds_survival_then_recommends(client):
    """Setup with a simulated survival table: the table and the fitted curve land in the
    background, then the pre-draft plan solves itself and arrives at /recommendation."""
    import time

    s = create(
        client,
        num_teams=4,
        objective="win",
        survival="simulate",
        survival_sims=12,
        solve_ahead=True,
        time_limit=3.0,
    )
    sid = s["id"]
    assert s["survival"]["status"] == "building" and s["survival"]["sims"] == 12
    deadline = time.time() + 180
    while time.time() < deadline:
        s = client.get(f"/sessions/{sid}").json()
        if s["survival"]["status"] != "building":
            break
        time.sleep(0.5)
    assert s["survival"]["status"] == "ready", s["survival"]
    assert s["availability_source"] == "survival"
    assert s["curve"]["source"].startswith("simulated league (12 drafts, 4 teams")
    board = client.get(f"/sessions/{sid}/board?limit=5").json()
    assert all(0.0 <= p["p_next"] <= 1.0 for p in board["players"])
    while time.time() < deadline:
        latest = client.get(f"/sessions/{sid}/recommendation").json()
        if latest["recommendation"] is not None and not latest["solver"]["running"]:
            break
        time.sleep(0.5)
    assert latest["recommendation"] is not None and latest["stale"] is False
    assert latest["recommendation"]["availability_source"] == "survival"
    assert latest["solver"]["runs"] >= 1
    # A manual re-solve queues another background run.
    r = client.post(f"/sessions/{sid}/solve", json={"n": 3, "scenarios": 0})
    assert r.status_code == 202 and r.json()["queued"] is True
    while time.time() < deadline:
        status = client.get(f"/sessions/{sid}/solver").json()
        if status["runs"] >= 2 and not status["running"] and not status["pending"]:
            break
        time.sleep(0.5)
    assert status["runs"] >= 2 and status["survival"]["status"] == "ready"
