"""#10: act_at_s, when an armed turn acts. PATCH {mode, act_at_s} sets it (null: at once, the
default; at least 12 s, so the drafter's row clicks have room before the backstop); the control
event records it, the room summary carries it to the draft tab, a restart keeps it, and the
scorecard prints it next to D2."""

from __future__ import annotations

import pytest

from pickandroll.fidelity import analyze, markdown

from .test_yahoo_room import _ev, _events, app_for, attach, build_league, post_picks


@pytest.fixture
def league(tmp_path):
    return tmp_path, build_league(tmp_path)


def test_act_at_s_is_null_until_set_and_kept_when_left_out(league):
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        assert c.get("/rooms/d1").json()["act_at_s"] is None
        r = c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 20})
        assert r.status_code == 200, r.text
        assert r.json()["act_at_s"] == 20 and r.json()["control"] == "armed"
        # The side panel's mode switch sends the mode alone: the timing stays.
        assert c.patch("/rooms/d1", json={"mode": "mirror"}).json()["act_at_s"] == 20
        assert c.patch("/rooms/d1", json={"mode": "autopilot"}).json()["act_at_s"] == 20
        # null: at once again.
        r = c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": None})
        assert r.json()["act_at_s"] is None
    controls = [e for e in _events(directory, "d1") if e["type"] == "control" and e["src"] == "api"]
    assert [e["act_at_s"] for e in controls] == [None, 20, 20, 20, None]
    assert [e["mode"] for e in controls] == [
        "mirror",
        "autopilot",
        "mirror",
        "autopilot",
        "autopilot",
    ]


@pytest.mark.parametrize("act_at_s", [0, 11, 31, "soon"])
def test_act_at_s_out_of_range_is_refused(league, act_at_s):
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        r = c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": act_at_s})
        assert r.status_code == 422
        assert c.get("/rooms/d1").json()["mode"] == "mirror"


def test_act_at_s_alone_keeps_the_mode(league):
    """#20: the web's timing control sends act_at_s alone, so a stale cached mode can never
    re-arm a room the side panel just put in mirror."""
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        r = c.patch("/rooms/d1", json={"act_at_s": 15})
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "mirror" and r.json()["control"] == "mirror"
        assert r.json()["act_at_s"] == 15
        assert c.patch("/rooms/d1", json={"mode": "autopilot"}).json()["control"] == "armed"
        r = c.patch("/rooms/d1", json={"act_at_s": None})
        assert r.json()["mode"] == "autopilot" and r.json()["act_at_s"] is None
        assert c.patch("/rooms/d1", json={}).status_code == 422
        assert c.patch("/rooms/d1", json={"mode": None}).status_code == 422
        # An explicit null mode is refused with act_at_s too (#22): leave the field out.
        r = c.patch("/rooms/d1", json={"mode": None, "act_at_s": 15})
        assert r.status_code == 422 and "leave it out" in r.json()["detail"]
        assert c.get("/rooms/d1").json()["act_at_s"] is None, "nothing was set"


def test_a_rebuild_before_pick_1_restores_mode_and_act_at_s(league):
    """#20: an API restart in the waiting room (no picks yet) rebuilds the room armed as the
    user left it, not with the attach record's mirror and act_at_s null."""
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        assert c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 15}).status_code == 200
    with app_for(directory) as c:
        room = c.get("/rooms/d1").json()  # any room call rebuilds it
        assert room["resumed"] is False
        assert room["mode"] == "autopilot" and room["control"] == "armed"
        assert room["act_at_s"] == 15
    with app_for(directory) as c:  # and again: the rebuild wrote what it restored
        room = c.get("/rooms/d1").json()
        assert room["mode"] == "autopilot" and room["act_at_s"] == 15


def test_an_attach_after_a_detach_starts_afresh(league):
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        assert c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 15}).status_code == 200
        assert c.delete("/rooms/d1").status_code == 200
        room = attach(c)
        assert room["mode"] == "mirror" and room["act_at_s"] is None


def test_an_explicit_mode_wins_over_the_log_and_act_at_s_stays(league):
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        assert c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 20}).status_code == 200
    with app_for(directory) as c:
        room = attach(c, mode="mirror")  # the side panel's attach after the restart
        assert room["mode"] == "mirror" and room["act_at_s"] == 20


def test_an_explicit_mode_on_a_resumed_room_is_logged_and_kept_by_the_next_rebuild(league):
    """#22: the side panel's Attach (mirror) after a restart mid-draft writes an API control,
    so a second restart rebuilds the room in mirror, not armed as before the first."""
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:5])
        assert c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 15}).status_code == 200
    with app_for(directory) as c:
        room = attach(c, mode="mirror")
        assert room["resumed"] is True
        assert room["mode"] == "mirror" and room["control"] == "mirror"
    with app_for(directory) as c:
        room = c.get("/rooms/d1").json()  # a rebuild
        assert room["mode"] == "mirror" and room["control"] == "mirror"
        assert room["act_at_s"] == 15
    last = [e for e in _events(directory, "d1") if e["type"] == "control" and e["src"] == "api"]
    assert [e["mode"] for e in last[-2:]] == ["autopilot", "mirror"], "the PATCH, then the attach"


def test_a_restart_keeps_act_at_s(league):
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:5])
        assert c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": 15}).status_code == 200
    with app_for(directory) as c:
        room = c.post("/rooms", json={"draft_id": "d1"})
        assert room.status_code == 201, room.text
        assert room.json()["resumed"] is True and room.json()["act_at_s"] == 15


def test_the_scorecard_prints_act_at_s_next_to_d2():
    base = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=2, draft_id="r", mode="mirror"),
        _ev("control", 0, state="mirror", src="api"),
    ]
    card = analyze(base)
    assert card["diagnostics"]["act_at_s"] == []
    md = markdown(card)
    assert "| D2 turn to land | " in md and "armed turns act at once |" in md
    events = [
        *base,
        _ev("control", 1, state="armed", act_at_s=20, src="api"),
        _ev("control", 2, state="armed", act_at_s=20, src="api"),
        _ev("control", 3, state="armed", act_at_s=None, src="api"),
        _ev("control", 4, state="armed", mode="autopilot", src="client"),
    ]
    card = analyze(events)
    assert card["diagnostics"]["act_at_s"] == [20, None]
    assert "armed turns act at 20 s left, then at once |" in markdown(card)
