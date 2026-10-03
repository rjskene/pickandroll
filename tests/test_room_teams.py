"""#17: a room whose team count the session gets wrong (mock 2: a 10-team room attached as 12).

The session then credits the room's picks to the wrong teams, its picks and open slots
disagree, and every recommendation falls back to the single-roster model. These tests hold the
two fixes and the guard: a pick never waits on that model's solves, the model keeps to the
room's budget and stops when the board moves, an attach the room contradicts is refused, a room
that shows another count turns to mirror, and the log says which model each reco came from.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.api import solver as solver_module
from pickandroll.api.solver import SolveParams, Superseded, compute_recommendation
from pickandroll.fidelity import analyze, markdown
from pickandroll.optim import roster as roster_module

from .test_yahoo_room import SESSION, _ev, _events, build_league


@pytest.fixture
def room(tmp_path):
    picks = build_league(tmp_path)
    store = SessionStore()
    client = TestClient(create_app(store, data_dir=tmp_path))
    with client:
        yield client, store, picks, tmp_path


def _attach(client, draft_id="m1", slot=1, session=SESSION, **extra):
    body = {"draft_id": draft_id, "slot": slot, "session": session, **extra}
    r = client.post("/rooms", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _owner(teams: int, overall: int) -> int:
    """The slot on the clock at ``overall`` in a snake of ``teams`` (protocol.js pickOwner)."""
    rnd, idx = divmod(overall - 1, teams)
    return idx + 1 if rnd % 2 == 0 else teams - idx


def _room_picks(client, picks, start=1, teams=10, draft_id="m1"):
    """The room's picks ``start``.. as a ``teams``-team room makes them, with their slots."""
    items = [
        {"overall": k, "yahoo_player_id": p.yahoo_player_id, "slot": _owner(teams, k)}
        for k, p in enumerate(picks, start=start)
    ]
    r = client.post(f"/rooms/{draft_id}/picks", json={"picks": items})
    assert r.status_code == 200, r.text
    return r.json()


def _mock2(room):
    """Slot 1 of a 10-team room attached as 12, after pick 21: my picks 1, 20 and 21 are in,
    the session's schedule says my next is 24, and the horizon plan cannot be built."""
    client, store, picks, _ = room
    session = store.get(_attach(client)["session_id"])
    _room_picks(client, picks[:21])
    assert len(session.state.my_roster) == 3
    return session


def test_a_pick_never_waits_on_a_roster_solve(room, monkeypatch):
    """Mock 2: the roster model's solves held the session lock, and every pick sync queued
    behind them for 13-30 s. Now a pick lands while a roster solve sleeps."""
    client, _, picks, _ = room
    session = _mock2(room)
    solving, release = threading.Event(), threading.Event()
    original = solver_module.solve_roster

    def sleepy(problem, **kw):
        solving.set()
        release.wait(5)
        return original(problem, **kw)

    monkeypatch.setattr(solver_module, "solve_roster", sleepy)
    out: dict = {}
    worker = threading.Thread(
        target=lambda: out.update(payload=compute_recommendation(session, SolveParams(n=2)))
    )
    worker.start()
    try:
        assert solving.wait(30), "the roster solve never started"
        started = time.perf_counter()
        _room_picks(client, picks[21:22], start=22)
        took = time.perf_counter() - started
    finally:
        release.set()
        worker.join(60)
    assert took < 1.0, f"pick 22 waited {took:.2f} s on the roster solve"
    assert out["payload"]["mode"] == "roster"
    assert "remaining picks" in out["payload"]["roster_reason"]


def test_the_roster_model_keeps_to_the_room_budget(room, monkeypatch):
    """In a room the roster model's solves share the plan and price budgets: each has the
    budget over (candidates + 1), and no candidate's solve starts after the budget is spent."""
    session = _mock2(room)
    session.state.plan_time_limit = 1.0
    session.state.price_time_limit = 1.0  # a 2 s budget
    original = roster_module.solve_roster
    limits: list = []

    def slow(problem, time_limit=10.0, **kw):
        limits.append(time_limit)
        time.sleep(0.6)
        return original(problem, time_limit=time_limit, **kw)

    monkeypatch.setattr(roster_module, "solve_roster", slow)
    monkeypatch.setattr(solver_module, "solve_roster", slow)
    started = time.perf_counter()
    payload = compute_recommendation(session, SolveParams(n=8))
    took = time.perf_counter() - started
    assert payload["mode"] == "roster"
    assert limits and all(x == pytest.approx(2.0 / 9) for x in limits)
    # The best roster, then candidates until 2 s are spent: 9 solves (5.4 s) without the cap.
    assert 2 <= len(limits) <= 5, limits
    assert took < 2.0 + 0.6 + 1.0, f"{took:.2f} s"
    assert 1 <= len(payload["candidates"]) == len(limits) - 1


def test_a_plain_session_keeps_the_solvers_own_limits(room, monkeypatch):
    session = _mock2(room)
    monkeypatch.setattr(session, "room", None)  # the same board outside a room
    original = roster_module.solve_roster
    limits: list = []

    def spy(problem, time_limit=10.0, **kw):
        limits.append(time_limit)
        return original(problem, time_limit=time_limit, **kw)

    monkeypatch.setattr(roster_module, "solve_roster", spy)
    monkeypatch.setattr(solver_module, "solve_roster", spy)
    payload = compute_recommendation(session, SolveParams(n=2))
    assert payload["mode"] == "roster" and len(payload["candidates"]) == 2
    assert limits == [10.0, 5.0, 5.0]  # solve_roster's and pick_pool's defaults


def test_a_roster_solve_stops_once_its_board_is_replaced(room, monkeypatch):
    session = _mock2(room)
    moved = {"board": False}
    original = solver_module.solve_roster
    priced: list = []

    def board_moves(problem, **kw):
        moved["board"] = True  # a pick lands while the best roster solves
        return original(problem, **kw)

    def candidate(problem, **kw):
        priced.append(problem)
        return original(problem, **kw)

    monkeypatch.setattr(solver_module, "solve_roster", board_moves)
    monkeypatch.setattr(roster_module, "solve_roster", candidate)
    with pytest.raises(Superseded):
        compute_recommendation(session, SolveParams(n=8), stop=lambda: moved["board"])
    assert priced == [], "no candidate was priced for a board already gone"


def test_an_attach_the_room_contradicts_is_refused_before_anything_is_built(room):
    client, store, _, directory = room
    r = client.post(
        "/rooms", json={"draft_id": "t1", "slot": 1, "session": SESSION, "room_teams": 10}
    )
    assert r.status_code == 422 and "10 teams" in r.text and "12" in r.text, r.text
    assert store.sessions == {} and client.get("/rooms/t1").status_code == 404
    assert not (directory / "fidelity" / "t1.jsonl").exists()
    sid = _attach(client, draft_id="t1", room_teams=12)["session_id"]  # the count agrees
    again = client.post(
        "/rooms", json={"draft_id": "t1", "slot": 1, "session_id": sid, "room_teams": 10}
    )
    assert again.status_code == 422 and "has 10 teams but is attached for 12" in again.text
    other = client.post(
        "/rooms", json={"draft_id": "t2", "slot": 1, "session_id": sid, "room_teams": 10}
    )
    assert other.status_code == 422, "an existing 12-team session is refused for a 10-team room"
    assert len(store.sessions) == 1
    # Without the room's count (the client has not seen the snake turn yet) the attach stands.
    _attach(client, draft_id="t3")


def test_a_room_that_shows_another_count_turns_to_mirror_once(room):
    client, store, _, directory = room
    session = store.get(_attach(client, mode="autopilot")["session_id"])

    def turn(overall: int, teams):
        event = {"type": "turn_start", "overall": overall, "slot": 1, "clock_s": 30}
        event["teams"] = teams
        r = client.post("/rooms/m1/events", json={"events": [event]})
        assert r.status_code == 200, r.text

    turn(1, None)  # not known yet
    turn(13, 12)  # agrees
    assert session.room.mode == "autopilot" and session.room.teams_mismatch is None
    turn(11, 10)
    view = client.get("/rooms/m1").json()
    assert view["mode"] == "mirror" and view["control"] == "mirror"
    assert view["teams_mismatch"] == 10
    turn(12, 10)
    notes = [e for e in _events(directory, "m1") if e.get("what") == "team count mismatch"]
    assert len(notes) == 1
    assert notes[0]["room_teams"] == 10 and notes[0]["num_teams"] == 12
    assert notes[0]["mode_was"] == "autopilot"
    refused = client.patch("/rooms/m1", json={"mode": "autopilot"})
    assert refused.status_code == 409 and "10 teams" in refused.text
    assert client.patch("/rooms/m1", json={"mode": "mirror"}).status_code == 200


def test_each_reco_logs_its_model_and_the_first_roster_one_why(room):
    client, _, picks, directory = room
    _attach(client)
    _room_picks(client, picks[:19])  # pick 20 is mine in the 10-team room: still consistent
    assert client.get("/rooms/m1/plan?wait=20").json()["fresh"] is True
    _room_picks(client, picks[19:21], start=20)
    assert client.get("/rooms/m1/plan?wait=20").json()["fresh"] is True
    _room_picks(client, picks[21:22], start=22)
    assert client.get("/rooms/m1/plan?wait=20").json()["fresh"] is True
    events = _events(directory, "m1")
    recos = [e for e in events if e["type"] == "reco"]
    assert sorted({(r["board"], r["model"]) for r in recos}) == [  # board 19: early, then priced
        (19, "horizon"),
        (21, "roster"),
        (22, "roster"),
    ]
    notes = [e for e in events if e.get("what") == "roster fallback"]
    assert len(notes) == 1 and notes[0]["board"] == 21
    assert "remaining picks" in notes[0]["reason"] and "open roster slots" in notes[0]["reason"]
    card = analyze(events)
    assert card["diagnostics"]["roster"] == {"recos": 2, "boards": [21, 22]}
    assert "| Recos from the roster fallback (goal 0 in a room) | 2 (boards 21, 22) |" in (
        markdown(card)
    )


def test_the_scorecard_shows_the_rooms_count_and_the_probes_row():
    events = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=1, draft_id="p"),
        _ev("turn_start", 1, overall=1, slot=1, clock_s=30, teams=None),
        _ev("room_pick", 1, overall=1, yid="a"),
        _ev("session_pick", 1, overall=1, yid="a"),
    ]
    assert "Team count (diagnostic): attached for 2; the room's own count was not seen." in (
        markdown(analyze(events))
    )
    events += [
        _ev("turn_start", 2, overall=2, slot=2, clock_s=30, teams=3),
        _ev("note", 2, what="team count mismatch", room_teams=3, num_teams=2, src="api"),
        _ev(
            "note",
            3,
            what="queue_probe",
            overall=1,
            yid="a",
            name="A",
            outcome="drafted",
            control="Draft",
            panel=[],
            panel_found=True,
            controls=[
                {"cell": 0, "pos": 0, "tag": "button", "labels": "Draft"},
                {"cell": 1, "pos": 0, "tag": "a", "labels": "A"},
            ],
            src="client",
        ),
    ]
    card = analyze(events)
    assert card["teams"] == {"attached": 2, "room": 3, "from_pick": 2, "mismatch": 3}
    text = markdown(card)
    assert (
        "Team count (diagnostic): the room showed 3 from pick 2, attached for 2; "
        "MISMATCH (3 teams): the API set the room to mirror." in text
    )
    assert 'queue panel empty; row controls: cell 0.0 button "Draft"; cell 1.0 a "A".' in text
