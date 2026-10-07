"""A pick the room never sends (docs/KEEPERS.md §2): a keeper the session's table does not know
about. Once the room's clock is past it for ``GAP_MARGIN_S`` the ledger records a pick with no
Yahoo id and the session a stand-in there; the room's own record repairs it, the session's pick
there stands, and the user names the keeper with ``PATCH /sessions/{id}/keepers``."""

from __future__ import annotations

import time

import pytest

from pickandroll.api import yahoo_room
from pickandroll.fidelity import guardrail_pass
from pickandroll.fidelity.replay import replay

from .test_yahoo_room import (
    SESSION,
    _events,
    _name,
    app_for,
    attach,
    build_league,
    keeper_board,
    post_picks,
)


@pytest.fixture
def league(tmp_path):
    return tmp_path, build_league(tmp_path)


def turn_start(client, draft_id, overall):
    event = {"type": "turn_start", "overall": overall, "slot": 1, "clock_s": 30}
    r = client.post(f"/rooms/{draft_id}/events", json={"events": [event]})
    assert r.status_code == 200, r.text


def wait_for(check, timeout=5.0):
    """Poll ``check`` (no room calls: those check the gaps themselves) until it is true."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def room_state(client, draft_id="d1"):
    """The live room and its session, read without an HTTP call."""
    return client.app.state.store.room(draft_id)


def test_a_skipped_pick_waits_for_the_margin_then_gets_a_stand_in(league, monkeypatch):
    """Pick 5 never comes while the clock moves on to 6, 7, 8: nothing before the margin, then
    the scheduled check fills the gap with no further call from the client."""
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 1.0)
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:4])
        turn_start(c, "d1", 5)
        turn_start(c, "d1", 6)  # the clock is past 5: the evidence
        for k in (6, 7, 8):
            out = post_picks(c, "d1", picks[k - 1 : k])
            turn_start(c, "d1", k + 1)
        assert out["synced_through"] == 4 and out["waiting_for"] == 5
        room, session = room_state(c)
        assert room.standins == {} and session.state.next_overall == 5
        # The fill applies 5-8 under the room lock, then publishes them one by one (lags, log):
        # wait for the last one published, not just applied.
        assert wait_for(lambda: room.synced_through == 8 and room.recent_lags[-1][0] == 8)
        assert session.state.next_overall == 9
        status = c.get("/rooms/d1").json()
        assert status["waiting_for"] is None
        [standin] = status["standins"]
        assert standin["overall"] == 5 and standin["gap"] and standin["yid"] is None
        assert session.state.picks[4].player_id == standin["as"]
        assert [k for k, _ in room.recent_lags] == [1, 2, 3, 4, 6, 7, 8]  # no lag for a gap
    events = _events(directory, "d1")
    [gap] = [e for e in events if e["type"] == "room_pick" and e["overall"] == 5]
    assert gap["src"] == "gap" and gap["yid"] is None and gap["evidence"] == 6
    [synced] = [e for e in events if e["type"] == "session_pick" and e["overall"] == 5]
    assert synced["standin"] and synced["gap"] and synced["kind"] == "new"
    assert synced["lag_ms"] is None


def test_a_racing_post_and_a_history_frame_make_no_gap(league, monkeypatch):
    """The turn after a pick can reach the API before the pick (two POSTs race), and a history
    frame can carry keepers' picks far ahead of the clock: neither fills anything."""
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.4)
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:3])
        turn_start(c, "d1", 5)  # the room is on pick 5; pick 4's POST is still on its way
        post_picks(c, "d1", picks[3:4])
        post_picks(c, "d1", picks[29:30], src="history")  # a keeper's pick sent ahead
        room, session = room_state(c)
        time.sleep(0.8)
        assert c.get("/rooms/d1").json()["standins"] == []
        assert room.synced_through == 4 and session.state.next_overall == 5
        assert not any(p.src == "gap" for p in room.ledger.values())


def test_the_rooms_late_record_repairs_the_stand_in(league, monkeypatch):
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.0)
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:4])
        out = post_picks(c, "d1", picks[5:6])  # the live pick 6 is the evidence; due at once
        assert out["synced_through"] == 6
        room, session = room_state(c)
        standin = room.standins[5]["as"]
        out = post_picks(c, "d1", picks[4:5], src="history")  # the room's record, on reconnect
        assert out["replaced"] == 1 and out["synced_through"] == 6
        status = c.get("/rooms/d1").json()
        assert status["standins"] == [] and status["conflicts"] == []
        real = room.ids.pid(picks[4].yahoo_player_id)
        assert session.state.picks[4].player_id == real and standin in session.state.available
    events = _events(directory, "d1")
    assert [e["kind"] for e in events if e["type"] == "session_pick" and e["overall"] == 5] == [
        "new",
        "repair",
    ]


def test_the_sessions_own_pick_at_a_gap_stands(league, monkeypatch):
    """A pick the user entered in the session where the room sent none: the room says someone
    was picked there, not who, so the session's pick is held."""
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.0)
    directory, picks = league
    with app_for(directory) as c:
        sid = attach(c)["session_id"]
        post_picks(c, "d1", picks[:4])
        _, session = room_state(c)
        mine = session.state.available[3]
        r = c.post(f"/sessions/{sid}/picks", json={"team": "Team 5", "player_id": mine})
        assert r.status_code == 201, r.text
        out = post_picks(c, "d1", picks[5:7])
        assert out["synced_through"] == 7 and out["replaced"] == 0
        assert session.state.picks[4].player_id == mine
        assert c.get("/rooms/d1").json()["standins"] == []
    held = [
        e for e in _events(directory, "d1") if e["type"] == "session_pick" and e["overall"] == 5
    ]
    assert [(e["kind"], e["standin"]) for e in held] == [("held", False)]


def test_naming_the_keeper_at_a_gap_replaces_the_stand_in(league, monkeypatch):
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.0)
    directory, picks = league
    with app_for(directory) as c:
        sid = attach(c)["session_id"]
        post_picks(c, "d1", picks[:4])
        post_picks(c, "d1", picks[5:10])
        room, session = room_state(c)
        state = session.state
        standin = room.standins[5]["as"]
        kept = room.ids.pid(picks[4].yahoo_player_id)
        assert kept in state.available  # still on the board: the plan could target him

        # A reached slot that is no gap still refuses a keeper; a player drafted elsewhere too.
        r = c.patch(
            f"/sessions/{sid}/keepers",
            json={"keepers": [{"position": 6, "round": 1, "player_id": kept}]},
        )
        assert r.status_code == 409, r.text
        taken = state.picks[6].player_id
        r = c.patch(
            f"/sessions/{sid}/keepers",
            json={"keepers": [{"position": 5, "round": 1, "player_id": taken}]},
        )
        assert r.status_code == 400 and "drafted with pick 7" in r.json()["detail"]
        assert state.picks[4].player_id == standin and not state.keepers

        r = c.patch(
            f"/sessions/{sid}/keepers",
            json={"keepers": [{"position": 5, "round": 1, "player_id": kept}]},
        )
        assert r.status_code == 200, r.text
        assert [(k["overall"], k["player_id"], k["applied"]) for k in r.json()["keepers"]] == [
            (5, kept, True)
        ]
        assert state.picks[4].player_id == kept and state.is_keeper_pick(state.picks[4])
        assert standin in state.available and kept not in state.available
        status = c.get("/rooms/d1").json()
        assert status["standins"] == [] and status["synced_through"] == 10
        assert [k["overall"] for k in status["keepers"]] == [5]
        published = [e for e in session.log if e["event"] == "pick"]
        assert published[-1]["source"] == "keeper" and published[-1]["replaced"] == standin

        # The room's own record of him later is held, not a conflict.
        out = post_picks(c, "d1", picks[4:5], src="history")
        assert out["replaced"] == 0 and c.get("/rooms/d1").json()["conflicts"] == []
    fixes = [
        e for e in _events(directory, "d1") if e["type"] == "session_pick" and e["overall"] == 5
    ]
    assert [(e["kind"], e.get("src"), e["pid"]) for e in fixes] == [
        ("new", None, standin),
        ("keeper_fix", "keeper", kept),
        ("held", None, kept),
    ]


def test_a_rebuilt_room_keeps_its_gaps(league, monkeypatch):
    """After an API restart the log's gap is a gap again (a stand-in until the room's record),
    and a gap the room later recorded comes back as that record."""
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.0)
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:4])
        post_picks(c, "d1", [*picks[5:8], *picks[9:12]])  # gaps at 5 and 9
        post_picks(c, "d1", picks[8:9], src="history")  # 9 comes after all
        assert c.get("/rooms/d1").json()["synced_through"] == 12
    with app_for(directory) as c:
        room = c.post("/rooms", json={"draft_id": "d1"}).json()
        assert room["resumed"] and room["synced_through"] == 12 and room["picks_applied"] == 12
        assert [(s["overall"], s["gap"]) for s in room["standins"]] == [(5, True)]
        sid = room["session_id"]
        names = [p["player_id"] for p in c.get(f"/sessions/{sid}/picks").json()]
        live = room_state(c)
        assert names[8] == live[0].ids.pid(picks[8].yahoo_player_id)


@pytest.mark.parametrize("named", [True, False])
def test_tier1_replay_with_a_gap_at_a_slot_of_mine(league, monkeypatch, named):
    """The keeper board with one more keeper of mine the table does not know (round 9, pick
    97) and the room never sends. Named mid-draft, the draft ends 156/156 with G1 green, the
    gap a keeper slot of mine; never named, G1 fails with the gap listed."""
    monkeypatch.setattr(yahoo_room, "GAP_MARGIN_S", 0.0)
    directory, picks = league
    board, keepers = keeper_board(picks)
    P = {p.overall: p for p in board}
    draft_id = f"gap-{named}"
    with app_for(directory) as c:

        def name_him(overall: int) -> None:
            if not named or overall != 100:
                return
            sid = c.get(f"/rooms/{draft_id}").json()["session_id"]
            table = [
                {"position": k["position"], "round": k["round"], "player_id": k["player_id"]}
                for k in c.get(f"/sessions/{sid}").json()["keepers"]
            ]
            listed = c.get(f"/sessions/{sid}/board?limit=1000").json()["players"]
            pid = next(p["player_id"] for p in listed if p["name"] == _name(P[97]))
            r = c.patch(
                f"/sessions/{sid}/keepers",
                json={"keepers": [*table, {"round": 9, "player_id": pid}]},
            )
            assert r.status_code == 200, r.text

        result = replay(
            c,
            board,
            draft_id=draft_id,
            slot=1,
            session={**SESSION, "keepers": keepers},
            solve={"n": 3, "scenarios": 0, "time_limit": 3.0},
            plan_wait=0.0,
            keepers="none",
            unsent=[97],
            after_pick=name_him,
        )
    card = result["scorecard"]
    live = result["status"]["live"]
    assert live["picks_applied"] == 156 and live["complete"] and live["synced_through"] == 156
    assert card["picks_seen"] == 152
    rows = [r["overall"] for r in card["rows"]]
    assert rows == [1, 24, 25, 48, 49, 72, 96, 120, 121, 144]  # 97 is no turn either way
    assert card["compliance"]["denominator"] == 10
    if named:
        assert card["kept_unseen"] == 4 and card["gaps_fixed"] == [97] and card["gaps"] == []
        assert card["my_keepers"] == [73, 97, 145]
        assert card["guardrails"]["G1"] == {"agree": 152, "of": 152, "total": 156}
        assert guardrail_pass(card)["G1"] is True
        assert "(1 named at a gap: 97)" in card["markdown"]
    else:
        assert card["kept_unseen"] == 3 and card["gaps"] == [97]
        assert card["my_keepers"] == [73, 145]
        assert guardrail_pass(card)["G1"] is False
        assert "1 gap with a stand-in: 97" in card["markdown"]
    assert [p["overall"] for p in result["plans"]] == rows
