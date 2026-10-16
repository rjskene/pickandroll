"""Scorecard and ledger hygiene after the real draft (#63): the final score is the final
roster's, the turns are the picks my seat owns, Yahoo's history frame stays out of the timing,
a keeper change is in the ledger, and ``fit_curve`` asks for a simulation.

The night of 2026-10-14 in miniature: twelve teams from position 4 with the traded-picks
fixture (28 and 45 went to position 1, 144 and 145 came to me), my keepers at 76 (pre-logged in
the history frame) and 148 (the table was wrong: the user drafted someone else there), other
teams' keepers pre-logged in the frame, one the table never knew, a keeper PATCH mid-draft
and recos from both models. A restart after a PATCH has its own test: a rebuilt session starts
a new score history, so the benchmark is only kept by a draft that runs on one API.
"""

from __future__ import annotations

import json
import time

import pytest

from pickandroll.fidelity import analyze, markdown
from tests.test_traded_picks import POS1, POS4
from tests.test_yahoo_room import (
    SESSION,
    _events,
    _name,
    app_for,
    attach,
    build_league,
    post_picks,
)

FRAME_AGE_MS = 2 * 3600 * 1000  # the history frame came two hours before the room's picks


@pytest.fixture
def league(tmp_path):
    return tmp_path, build_league(tmp_path)


def _turn(c, draft_id: str, overall: int, slot: int) -> None:
    event = {"type": "turn_start", "overall": overall, "slot": slot, "clock_s": 60}
    r = c.post(f"/rooms/{draft_id}/events", json={"events": [event]})
    assert r.status_code == 200, r.text


def _landed(c, draft_id: str, overall: int, yid: str, how: str) -> None:
    event = {"type": "pick_landed", "overall": overall, "yid": yid, "how": how, "ms_from_turn": 9}
    r = c.post(f"/rooms/{draft_id}/events", json={"events": [event]})
    assert r.status_code == 200, r.text


def _recommend(c, sid: str, horizon: bool) -> dict:
    body = {"n": 3, "scenarios": 0, "horizon": horizon}
    r = c.post(f"/sessions/{sid}/recommend", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_night_shaped_ledger(league, traded):
    directory, picks = league
    P = {p.overall: p for p in picks}
    other = "900000"  # Bench0 Filler: whom the user drafted at 148 instead of the keeper
    table = [
        {"round": 7, "player": _name(P[76])},
        {"overall": 148, "player": _name(P[148])},
        {"position": 11, "round": 3, "player": _name(P[35])},
        {"position": 9, "round": 12, "player": _name(P[136])},
    ]
    framed = [35, 63, 76, 136]  # 63's keeper is in no table: the frame's src stays "history"
    on_clock = sorted(set(range(1, 157)) - set(framed))
    draft_id = "night"

    def play(c, sid: str, upto: int) -> None:
        for k in [k for k in on_clock if k <= upto and k not in played]:
            if k == 4:
                _recommend(c, sid, horizon=True)  # the benchmark: before my first pick
            elif k == 52:
                _recommend(c, sid, horizon=False)  # the single-roster model
            elif k == 93:
                _recommend(c, sid, horizon=True)
            elif k == 61:
                # The user corrects the table mid-draft: 136's keeper was never one.
                r = c.patch(f"/sessions/{sid}/keepers", json={"keepers": table[:3]})
                assert r.status_code == 200, r.text
            _turn(c, draft_id, k, traded[k - 1])
            yid = other if k == 148 else P[k].yahoo_player_id
            if k in POS4:
                _landed(c, draft_id, k, yid, "manual")
            elif k in (28, 45):
                _landed(c, draft_id, k, yid, "unknown")  # the night's tab, on the snake
            r = c.post(
                f"/rooms/{draft_id}/picks",
                json={
                    "picks": [
                        {
                            "overall": k,
                            "yahoo_player_id": yid,
                            "slot": traded[k - 1],
                            "t_room": round(time.time() * 1000),
                            "src": "socket",
                        }
                    ]
                },
            )
            assert r.status_code == 200, r.text
            played.add(k)

    played: set[int] = set()
    with app_for(directory) as c:
        room = attach(
            c,
            draft_id=draft_id,
            slot=4,
            pick_owners=traded,
            session={**SESSION, "my_position": 4, "keepers": table},
        )
        sid = room["session_id"]
        assert [k["overall"] for k in room["keepers"]] == [35, 76, 136, 148]
        frame = round(time.time() * 1000) - FRAME_AGE_MS
        post_picks(c, draft_id, [P[k] for k in framed], src="history", t_room=frame)
        play(c, sid, 156)
        score = c.get(f"/sessions/{sid}/score").json()
        roster = c.get(f"/sessions/{sid}").json()["my_roster"]
        card = c.get(f"/rooms/{draft_id}/fidelity").json()
    events = _events(directory, draft_id)
    final = score["final"]
    assert final is not None and len(roster) == 13
    # The PATCH is in the ledger with the table it left.
    patches = [e for e in events if e["type"] == "keepers"]
    assert len(patches) == 1 and patches[0]["changed"] is True
    assert patches[0]["overalls"] == [35, 76, 148]

    # D5 is the final roster's score on the session's curve. The first score, logged when the
    # draft passed my keeper slot, still had the wrong keeper; the room's pick there replaced
    # him, and the score was logged again.
    scores = [e for e in events if e["type"] == "score"]
    assert len(scores) == 2 and scores[-1]["roster"] == roster
    d5 = card["diagnostics"]["D5"]
    assert d5["wins"] == final["wins"] and d5["model"] == "final"
    assert d5["benchmark"] == score["benchmark"]["wins"] and d5["benchmark_model"] == "horizon"
    best = max(score["history"], key=lambda h: h["wins"])
    assert d5["best"] == best["wins"] and d5["best_model"] == best["mode"]
    assert {h["mode"] for h in score["history"]} == {"horizon", "roster"}
    assert d5["vs_benchmark"] == round(final["wins"] - score["benchmark"]["wins"], 4)
    text = card["markdown"]
    assert f"{final['wins']}, the final roster on the session's curve" in text
    assert f"benchmark {d5['benchmark']} from the horizon model" in text

    # The turns are the picks my seat owns: 144, 145 and the overridden keeper slot 148 are
    # rows, 28 and 45 are not, and the tab's reports for them are counted apart.
    rows = {r["overall"]: r for r in card["rows"]}
    assert sorted(rows) == [k for k in POS4 if k != 76]
    assert not set(rows) & set(POS1)
    assert {r["label"] for r in rows.values()} == {"manual"}
    assert all(r["how"] != "unknown" for r in rows.values())
    assert card["landed_unowned"] == [28, 45]
    assert card["my_keepers"] == [76]
    assert "Landed reports for picks my seat does not own (no turns of mine): 28, 45." in text
    models = {r["overall"]: r["ref_model"] for r in card["rows"]}
    assert models[4] == "horizon" and models[52] == "roster" and models[93] == "horizon"

    # The history frame's picks are labelled: none is a plain new pick, none has a lag.
    synced = [e for e in events if e["type"] == "session_pick" and e["overall"] in framed]
    assert all(e.get("src") in ("keeper", "history") for e in synced)
    new = {e["overall"] for e in synced if e["kind"] == "new"}
    assert new == {63, 136}
    assert all(e["src"] == "history" and e["lag_ms"] is None for e in synced if e["kind"] == "new")
    assert not [e for e in synced if e["kind"] == "held" and e["lag_ms"] is not None]
    g = card["guardrails"]
    assert card["history_picks"] == 4 and g["G2_all"]["max"] < 5000
    assert g["G2"]["n"] == g["G2_all"]["n"] == 156 - len(framed)
    assert g["G1"] == {"agree": 156, "of": 156, "total": 156}


def test_a_rebuild_drafts_on_the_table_the_patch_left(league):
    """An API restart after a keepers PATCH: the rebuilt session takes the ``keepers`` event's
    table, not the one the attach recorded."""
    directory, picks = league
    P = {p.overall: p for p in picks}
    table = [
        {"position": 3, "round": 2, "player": _name(P[22])},
        {"position": 5, "round": 4, "player": _name(P[44])},
    ]
    with app_for(directory) as c:
        room = attach(c, draft_id="rb", slot=1, session={**SESSION, "keepers": table})
        sid = room["session_id"]
        post_picks(c, "rb", [P[k] for k in range(1, 6)])
        r = c.patch(f"/sessions/{sid}/keepers", json={"keepers": table[:1]})
        assert r.status_code == 200, r.text
    with app_for(directory) as c:
        room = c.get("/rooms/rb").json()
        session = c.get(f"/sessions/{room['session_id']}").json()
        assert [k["overall"] for k in session["keepers"]] == [22]
        assert room["synced_through"] == 5
    record = [e for e in _events(directory, "rb") if e["type"] == "attach"][-1]
    assert [(k["position"], k["round"]) for k in record["session"]["keepers"]] == [(3, 2)]


def test_without_an_owner_map_the_rooms_record_says_whose_pick(traded):
    """The night's own log: no owner map at the attach, the tab on the snake. The room's
    record of who made each pick decides the turns; a history pick waiting for its slot is out
    of the lag, and the score as logged then is printed as such."""

    def ev(event, t, **fields):
        return {"type": event, "t": f"2026-10-15T01:{t // 60:02d}:{t % 60:02d}.000+00:00", **fields}

    events = [
        ev("room_pick", 0, overall=145, slot=4, yid="y145", src="history"),
        ev("attach", 1, slot=4, num_teams=12, rounds=13, draft_id="31822", mode="mirror"),
        ev("control", 1, state="mirror", src="api"),
    ]
    for k in range(1, 157):
        t = 2 + k * 20
        if k in (28, 45):
            events.append(ev("pick_landed", t, overall=k, yid=f"y{k}", how="unknown"))
        if k != 145:
            events.append(ev("room_pick", t, overall=k, slot=traded[k - 1], yid=f"y{k}"))
        events.append(ev("session_pick", t, overall=k, yid=f"y{k}", kind="new"))
    events.append(ev("score", 3200, wins=5.2556, benchmark=5.1442, vs_benchmark=0.1114))
    card = analyze(events)
    assert card["my_picks"] == POS4
    assert [r["overall"] for r in card["rows"]] == POS4
    assert card["landed_unowned"] == [28, 45]
    assert card["rows"][POS4.index(144)]["how"] is None  # no report: not "unknown"
    assert card["history_picks"] == 1 and card["guardrails"]["G2_all"]["max"] == 0
    assert card["guardrails"]["G2_all"]["n"] == 155
    row = card["rows"][POS4.index(145)]
    assert row["lag_ms"] is None and row["reco_ready_ms"] is None
    assert "5.2556 as logged (benchmark 5.1442, +0.1114)" in markdown(card)


def test_fit_curve_asks_for_a_simulation(league):
    directory, _ = league
    body = {**SESSION, "fit_curve": True}  # survival "none"
    with app_for(directory) as c:
        r = c.post("/sessions", json=body)
        assert r.status_code == 400
        assert "fit_curve fits the curve from a simulated survival run" in r.json()["detail"]
        assert "survival is none" in r.json()["detail"]
        r = c.post("/rooms", json={"draft_id": "fc", "slot": 1, "session": body})
        assert r.status_code == 400 and "survival is none" in r.json()["detail"]
        # Left out, or false: accepted, and the session records that nothing is fitted.
        attach(c, draft_id="fc", slot=1)
        r = c.post("/sessions", json={**SESSION, "fit_curve": False})
        assert r.status_code == 201, r.text
    record = next(e for e in _events(directory, "fc") if e["type"] == "attach")
    assert record["session"]["fit_curve"] is False

    # A log from before #63 records fit_curve true beside survival none: its rebuild works.
    path = directory / "fidelity" / "fc.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    for e in lines:
        if e["type"] == "attach":
            e["session"]["fit_curve"] = True
    path.write_text("".join(json.dumps(e) + "\n" for e in lines))
    with app_for(directory) as c:
        r = c.get("/rooms/fc")
        assert r.status_code == 200, r.text


def test_a_keepers_patch_with_no_room_writes_no_ledger(league):
    directory, picks = league
    P = {p.overall: p for p in picks}
    with app_for(directory) as c:
        sid = c.post("/sessions", json=SESSION).json()["id"]
        keepers = [{"position": 2, "round": 3, "player": _name(P[35])}]
        r = c.patch(f"/sessions/{sid}/keepers", json={"keepers": keepers})
        assert r.status_code == 200, r.text
        attach(c, draft_id="kp", slot=1, session_id=sid, session=None)
        r = c.patch(f"/sessions/{sid}/keepers", json={"keepers": keepers})
        assert r.status_code == 200, r.text
    patches = [e for e in _events(directory, "kp") if e["type"] == "keepers"]
    assert len(patches) == 1 and patches[0]["changed"] is False
