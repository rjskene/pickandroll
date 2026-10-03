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
    assert [e.get("act_at_s", "-") for e in controls] == ["-", 20, 20, 20, None]


@pytest.mark.parametrize("act_at_s", [0, 11, 31, "soon"])
def test_act_at_s_out_of_range_is_refused(league, act_at_s):
    directory, _ = league
    with app_for(directory) as c:
        attach(c)
        r = c.patch("/rooms/d1", json={"mode": "autopilot", "act_at_s": act_at_s})
        assert r.status_code == 422
        assert c.get("/rooms/d1").json()["mode"] == "mirror"


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
