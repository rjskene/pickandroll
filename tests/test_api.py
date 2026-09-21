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
    body = {"projection_file": "bbm_sample_ros_totals.xls", "num_teams": 4, "my_position": 2}
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

    rec = client.post(f"/sessions/{sid}/recommend", json={"n": 4, "punt": ["tov", "ft_pct"]}).json()
    assert rec["on_the_clock"] is True
    assert len(rec["candidates"]) == 4
    assert board[0]["player_id"] not in [c["player"] for c in rec["candidates"]]
    assert rec["best_roster"]["punted"] == ["tov", "ft_pct"]
    assert len(rec["best_roster"]["roster"]) == 13

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
        s = create(c, num_teams=12, my_position=5)
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

        # Same feed again applies nothing; an unmapped player is reported, not applied.
        fake.picks.append(("466.l.12345.t.2", "466.p.2"))
        r = c.post(f"/sessions/{sid}/yahoo/poll").json()
        assert r["applied"] == []
        assert r["unmapped_picks"][0]["name"] == "Nobody Real"
        assert c.get(f"/sessions/{sid}/yahoo").json()["polls"] == 2
        assert c.delete(f"/sessions/{sid}/yahoo").json() == {"attached": False}
        assert c.get(f"/sessions/{sid}/yahoo").json() == {"attached": False}
