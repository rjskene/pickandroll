"""#10: "Draft in Yahoo" from the web app. The API takes the request only for my pick on the
clock and on the session's current board; it drops it when the turn ends (the pick lands, or
the session moves past it) or when the draft tab reports the click failed."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app

from .test_yahoo_room import SESSION, build_league


@pytest.fixture
def room(tmp_path):
    picks = build_league(tmp_path)
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as c:
        r = c.post("/rooms", json={"draft_id": "q1", "slot": 1, "session": SESSION})
        assert r.status_code == 201, r.text
        beat(c)  # the draft tab is open
        yield c, r.json()["session_id"], [str(p.yahoo_player_id) for p in picks]


def beat(c):
    r = c.post("/rooms/q1/events", json={"events": [{"type": "heartbeat", "vis": "visible"}]})
    assert r.status_code == 200, r.text


def ask(c, overall, board, yid):
    return c.post(
        "/rooms/q1/request", json={"overall": overall, "board": board, "yahoo_player_id": yid}
    )


def test_a_request_for_my_pick_on_the_clock_is_held_for_the_draft_tab(room):
    c, _, yids = room
    r = ask(c, 1, 0, yids[2])
    assert r.status_code == 200, r.text
    held = c.get("/rooms/q1").json()["request"]
    assert held["overall"] == 1 and held["board"] == 0 and held["yahoo_player_id"] == yids[2]
    assert held["name"] and held["last"], "what the tab's label guard and row search need"
    # A second request replaces the first: the user changed their mind.
    assert ask(c, 1, 0, yids[3]).status_code == 200
    assert c.get("/rooms/q1").json()["request"]["yahoo_player_id"] == yids[3]


@pytest.mark.parametrize(
    "overall, board, why",
    [(2, 0, "not mine on the clock"), (1, 1, "board 1"), (1, 0, "unknown Yahoo player")],
)
def test_a_request_off_my_turn_or_board_is_refused(room, overall, board, why):
    c, _, yids = room
    yid = "123456789" if why == "unknown Yahoo player" else yids[0]
    r = ask(c, overall, board, yid)
    assert r.status_code == 409 and why in r.json()["detail"]
    assert c.get("/rooms/q1").json()["request"] is None


def test_the_request_ends_with_the_turn(room):
    c, _, yids = room
    assert ask(c, 1, 0, yids[2]).status_code == 200
    items = [{"overall": 1, "yahoo_player_id": yids[0], "slot": 1}]
    assert c.post("/rooms/q1/picks", json={"picks": items}).status_code == 200
    assert c.get("/rooms/q1").json()["request"] is None, "the pick landed"
    r = ask(c, 2, 1, yids[2])
    assert r.status_code == 409, "pick 2 is not mine"


def test_a_drafted_player_cannot_be_requested(room):
    c, _, yids = room
    items = [{"overall": k, "yahoo_player_id": yids[k - 1]} for k in range(1, 24)]
    assert c.post("/rooms/q1/picks", json={"picks": items}).status_code == 200
    r = ask(c, 24, 23, yids[0])
    assert r.status_code == 409 and "drafted" in r.json()["detail"]
    assert ask(c, 24, 23, yids[30]).status_code == 200


def test_a_hand_pick_in_the_session_ends_it_too(room):
    c, sid, yids = room
    assert ask(c, 1, 0, yids[2]).status_code == 200
    board = c.get(f"/sessions/{sid}/board?limit=5").json()["players"]
    r = c.post(f"/sessions/{sid}/picks", json={"team": "me", "player_id": board[0]["player_id"]})
    assert r.status_code == 201, r.text
    assert c.get("/rooms/q1").json()["request"] is None


def test_a_failed_click_drops_the_request(room):
    c, _, yids = room
    assert ask(c, 1, 0, yids[2]).status_code == 200
    other = {"type": "note", "what": "request failed", "overall": 2}
    assert c.post("/rooms/q1/events", json={"events": [other]}).status_code == 200
    assert c.get("/rooms/q1").json()["request"] is not None, "another turn's note"
    failed = {"type": "note", "what": "request failed", "overall": 1, "yid": yids[2]}
    assert c.post("/rooms/q1/events", json={"events": [failed]}).status_code == 200
    assert c.get("/rooms/q1").json()["request"] is None


def test_a_replaced_request_outlives_the_first_ones_failure(room):
    """The user asks for B, then C while the tab still tries B: B's failure leaves C."""
    c, _, yids = room
    assert ask(c, 1, 0, yids[2]).status_code == 200
    assert ask(c, 1, 0, yids[3]).status_code == 200
    failed = {"type": "note", "what": "request failed", "overall": 1, "yid": yids[2]}
    assert c.post("/rooms/q1/events", json={"events": [failed]}).status_code == 200
    assert c.get("/rooms/q1").json()["request"]["yahoo_player_id"] == yids[3]


def test_a_failure_note_drops_only_the_request_it_names(room):
    """#22: the user asks for B again before the tab's failure note for the first B arrives:
    the note names the first request by its id, so the second stands."""
    c, _, yids = room
    first = ask(c, 1, 0, yids[2]).json()["request"]
    again = ask(c, 1, 0, yids[2]).json()["request"]
    assert again["id"] != first["id"], "two requests in the same millisecond too"
    failed = {"type": "note", "what": "request failed", "overall": 1, "yid": yids[2]}
    stale = {**failed, "request_id": first["id"]}
    assert c.post("/rooms/q1/events", json={"events": [stale]}).status_code == 200
    assert c.get("/rooms/q1").json()["request"]["id"] == again["id"]
    current = {**failed, "request_id": again["id"]}
    assert c.post("/rooms/q1/events", json={"events": [current]}).status_code == 200
    assert c.get("/rooms/q1").json()["request"] is None


def test_a_request_is_refused_while_the_draft_tab_is_silent(tmp_path, monkeypatch):
    """#20: with no draft tab to click it, a request would show "sent" for nobody."""
    picks = build_league(tmp_path)
    yids = [str(p.yahoo_player_id) for p in picks]
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as c:
        r = c.post("/rooms", json={"draft_id": "q1", "slot": 1, "session": SESSION})
        assert r.status_code == 201, r.text
        r = ask(c, 1, 0, yids[2])
        assert r.status_code == 409 and "heard from never" in r.json()["detail"]
        beat(c)
        assert ask(c, 1, 0, yids[2]).status_code == 200
        rooms = importlib.import_module("pickandroll.api.yahoo_room")
        monkeypatch.setattr(rooms, "SILENT_AFTER_S", -1.0)  # the last beat is now too old
        r = ask(c, 1, 0, yids[3])
        assert r.status_code == 409 and "not for" in r.json()["detail"]
