"""Traded picks: the pick-owner map (the draft position on each overall pick) in the engine,
through the API and in the room (``docs/KEEPERS.md`` §1, ``docs/YAHOO_SYNC.md`` §4). The map
is ``tests/fixtures/traded_picks_12.json``, anonymised: 12 teams, 13 rounds, ten picks on
another position's snake slot (positions 1 and 4 swap two early picks for two late ones, so
position 4 picks twice in round 13 and never in rounds 3 and 4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.draft import DraftState, Keeper, KeeperInvalid, LeagueSettings
from pickandroll.draft.settings import (
    check_pick_owners,
    pick_owner,
    position_pick,
    position_picks,
    round_of,
    snake_owners,
    snake_picks,
    traded_picks,
)
from pickandroll.fidelity.replay import replay
from pickandroll.projections import ProjectionSet
from tests.test_api_keepers import DATA, SAMPLE, best, create
from tests.test_yahoo_room import SESSION, _events, _name, app_for, attach, build_league, post_picks

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "traded_picks_12.json").read_text())
TRADES = {int(k): v for k, v in FIXTURE["trades"].items()}
TRADED = sorted(TRADES)
POS4 = [4, 21, 52, 69, 76, 93, 100, 117, 124, 141, 144, 145, 148]
POS1 = [1, 24, 25, 28, 45, 48, 49, 72, 73, 96, 97, 120, 121]
#: Draft position -> Yahoo team id, a fixed shuffle (a league room names teams by id).
TEAM_OF = [None, 7, 3, 12, 1, 9, 5, 11, 2, 10, 4, 8, 6]


# --------------------------------------------------------------------------- settings
def test_round_of_and_the_snake_as_a_map():
    assert [round_of(12, k) for k in (1, 12, 13, 156)] == [1, 1, 2, 13]
    with pytest.raises(ValueError):
        round_of(12, 0)
    owners = snake_owners(12, 13)
    assert len(owners) == 156 and owners[:14] == (*range(1, 13), 12, 11)
    assert all(owners[k - 1] == pick_owner(12, k)[1] for k in range(1, 157))


def test_check_pick_owners(traded):
    assert check_pick_owners(None, 12, 13) is None
    assert check_pick_owners(traded, 12, 13) == tuple(traded)
    with pytest.raises(ValueError, match="156 entries"):
        check_pick_owners([1, 2], 12, 13)
    bad = list(traded)
    bad[0] = 13
    with pytest.raises(ValueError, match=r"pick_owners\[0\] \(pick 1\)"):
        check_pick_owners(bad, 12, 13)
    bad[0] = True
    with pytest.raises(ValueError):
        check_pick_owners(bad, 12, 13)


def test_traded_picks_and_a_positions_picks(traded):
    assert traded_picks(traded, 12) == TRADED
    assert traded_picks(None, 12) == [] and traded_picks(list(snake_owners(12, 13)), 12) == []
    assert position_picks(traded, 12, 4, 13) == POS4
    assert position_picks(traded, 12, 1, 13) == POS1
    assert position_picks(None, 12, 4, 13) == snake_picks(12, 4, 13)
    # Round 3: position 1 holds 25 and 28 (the first is its pick there), position 4 none.
    assert position_pick(traded, 12, 1, 3, 13) == 25
    assert position_pick(traded, 12, 4, 3, 13) is None
    assert position_pick(traded, 12, 4, 13, 13) == 145  # 145 and 148
    assert position_pick(None, 12, 4, 3, 13) == 28


# --------------------------------------------------------------------------- engine
def make_state(pool, position=4, owners=None, keepers=()):
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    return DraftState(
        settings=LeagueSettings(num_teams=12),
        projections=ps,
        my_team="me",
        my_position=position,
        keepers=tuple(keepers),
        pick_owners=owners,
    )


def _draft(state, ids, through):
    """Picks 1..``through`` from ``ids``, each booked to the owner the state gives it."""
    for k in range(1, through + 1):
        state.apply_pick(state.team_names()[state.owner_of(k)[1]], ids[k - 1])


def test_my_slots_follow_the_map_and_a_snake_map_is_the_snake(big_pool, traded):
    s = make_state(big_pool, 4, traded)
    assert s.my_slots == POS4 and s.my_picks == POS4 and s.traded_picks == TRADED
    assert s.owner_of(28) == (3, 1) and s.owner_of(145) == (13, 4) and s.owner_of(5) == (1, 5)
    assert s.my_next_pick == 4
    assert make_state(big_pool, 1, traded).my_slots == POS1
    plain = make_state(big_pool, 4, list(snake_owners(12, 13)))
    assert plain.my_slots == snake_picks(12, 4, 13) and plain.traded_picks == []
    assert make_state(big_pool, 4).my_slots == plain.my_slots
    with pytest.raises(ValueError, match="156 entries"):
        make_state(big_pool, 4, [1, 2, 3])


def test_the_clock_and_the_rosters_follow_the_map(big_pool, traded):
    s = make_state(big_pool, 4, traded)
    ids = s.z["total"].nlargest(40).index.tolist()
    _draft(s, ids, 27)
    assert s.next_overall == 28 and not s.on_the_clock, "pick 28 is position 1's"
    assert s.my_next_pick == 52
    s.apply_pick("Team 1", ids[27])
    totals = s.team_totals()
    assert int(totals.loc["Team 1", "picks"]) == 4 and int(totals.loc["me", "picks"]) == 2
    assert s.my_roster == [ids[3], ids[20]]
    assert s.picks[27].team == "Team 1"


def test_a_keeper_by_overall_and_one_by_round_through_the_map(big_pool, traded):
    ids = make_state(big_pool).z["total"].nlargest(4).index.tolist()
    mine, theirs = Keeper(None, 13, ids[0], 145), Keeper(1, 3, ids[1])
    s = make_state(big_pool, 4, traded, keepers=[mine, theirs])
    assert s.keeper_overall(mine) == 145 and s.keeper_overall(theirs) == 25
    assert set(s.keeper_slots) == {25, 145}
    assert s.my_picks == [k for k in POS4 if k != 145] and s.my_slots == POS4
    assert ids[0] in s.my_roster and ids[0] in s.taken and ids[1] in s.taken
    assert s.keeper_team(mine) == "me" and s.keeper_team(theirs) == "Team 1"
    # Up to the keeper's slot his pick is logged for me.
    _draft(s, s.z["total"].nlargest(160).index.drop(ids[:2]).tolist(), 24)
    assert s.picks[24].player_id == ids[1] and s.picks[24].team == "Team 1"


@pytest.mark.parametrize(
    ("keeper", "reason"),
    [
        (("pos", 4, 3, None), "no pick in round 3"),
        (("me", None, 3, 28), "position 1"),
        (("me", None, 13, 28), "round 3"),
        (("me", None, 13, 157), "1-156"),
    ],
)
def test_a_keeper_the_map_contradicts_is_refused(big_pool, traded, keeper, reason):
    pid = make_state(big_pool).z["total"].idxmax()
    _, position, rnd, overall = keeper
    with pytest.raises(KeeperInvalid, match=reason):
        make_state(big_pool, 4, traded, keepers=[Keeper(position, rnd, pid, overall)])


def test_set_pick_owners_relabels_the_picks_logged(big_pool, traded):
    s = make_state(big_pool, 4)
    ids = s.z["total"].nlargest(40).index.tolist()
    _draft(s, ids, 28)
    assert s.picks[27].team == "me" and ids[27] in s.my_roster
    assert s.set_pick_owners(traded) == 1
    assert s.picks[27].team == "Team 1" and ids[27] not in s.my_roster
    assert s.my_slots == POS4 and s.my_next_pick == 52 and s.traded_picks == TRADED
    assert s.set_pick_owners(None) == 1 and s.picks[27].team == "me"
    # A keeper already logged whose slot the map moves: refused, nothing changes.
    k = make_state(big_pool, 4, keepers=[Keeper(None, 3, ids[0])])  # my round 3: 28 in the snake
    _draft(k, ids[1:], 27)
    assert k.picks[27].player_id == ids[0]
    with pytest.raises(ValueError):
        k.set_pick_owners(traded)
    assert k.pick_owners is None and k.picks[27].player_id == ids[0] and k.picks[27].team == "me"


def test_team_totals_group_by_the_booked_team_without_a_map(big_pool):
    """The 2026-10-14 draft on a session with no map: the room booked pick 28 (position 1's
    snake slot, traded to me) to me. Every team keeps its row, the pick is mine, and
    position 1 is not renamed after my label."""
    s = make_state(big_pool, 4)
    ids = s.z["total"].nlargest(40).index.tolist()
    for k in range(1, 28):
        s.apply_pick(s.team_names()[pick_owner(12, k)[1]], ids[k - 1])
    s.apply_pick("me", ids[27])
    assert s.team_names()[1] == "Team 1" and s.pick_position(s.picks[27]) == 4
    totals = s.team_totals()
    assert len(totals) == 12 and sorted(totals["position"]) == list(range(1, 13))
    assert int(totals.loc["me", "picks"]) == 3 and int(totals.loc["Team 1", "picks"]) == 3
    assert s.my_roster == [ids[3], ids[20], ids[27]]
    assert len(s.projected_finals()) == 12 and len(s.matchups()["opponents"]) == 11
    # A team the log names keeps its name.
    s.apply_pick("Hoopers", ids[28])  # pick 29: position 4's snake slot... position 1's in round 3
    assert s.team_names()[pick_owner(12, 29)[1]] == "Hoopers"


def test_set_my_position_with_a_map_moves_my_keepers(big_pool, traded):
    pid = make_state(big_pool).z["total"].idxmax()
    s = make_state(big_pool, 1, traded, keepers=[Keeper(None, 1, pid)])
    assert [p.overall for p in s.picks] == [1], "my round-1 keeper is logged at once"
    s.set_my_position(4)
    assert s.picks == [] and s.my_slots == POS4 and set(s.pending_keepers) == {4}
    s.set_my_position(4, None)
    assert s.my_slots == snake_picks(12, 4, 13) and s.pick_owners is None


# --------------------------------------------------------------------------- API
@pytest.fixture
def client():
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    with TestClient(create_app(SessionStore(), data_dir=DATA)) as c:
        yield c


def test_a_session_with_an_owner_map(client, traded):
    (a, _), (b, _) = best(client, 2)
    s = create(
        client,
        num_teams=12,
        my_position=4,
        pick_owners=traded,
        keepers=[{"overall": 145, "player_id": a}, {"position": 1, "round": 3, "player_id": b}],
    )
    assert s["pick_owners"] == traded and s["traded_picks"] == TRADED
    assert s["my_slots"] == POS4 and s["my_picks"] == [k for k in POS4 if k != 145]
    rows = {k["overall"]: k for k in s["keepers"]}
    assert rows[145]["mine"] and rows[145]["by_overall"] and rows[145]["round"] == 13
    assert rows[145]["position"] == 4 and rows[145]["team"] == "me"
    assert rows[25]["position"] == 1 and not rows[25]["by_overall"]
    assert a in s["my_roster"]
    teams = {t["position"]: t for t in client.get(f"/sessions/{s['id']}/teams").json()["teams"]}
    assert teams[4]["picks"] == 1 and teams[4]["mine"] and teams[1]["picks"] == 1

    e = create(
        client,
        status=400,
        num_teams=12,
        my_position=4,
        pick_owners=traded,
        keepers=[{"position": 4, "round": 3, "player_id": a}],
    )
    assert "keepers[0]" in e["detail"] and "no pick in round 3" in e["detail"]
    e = create(
        client,
        status=400,
        num_teams=12,
        my_position=4,
        pick_owners=traded,
        keepers=[{"overall": 28, "player_id": a}],
    )
    assert "position 1" in e["detail"]
    e = create(client, status=400, num_teams=12, my_position=4, keepers=[{"player_id": a}])
    assert "round or overall" in e["detail"]
    assert (
        "156 entries"
        in create(client, status=400, num_teams=12, my_position=4, pick_owners=traded[:10])[
            "detail"
        ]
    )

    # A keeper by overall needs no round; PATCH takes one too.
    s2 = create(
        client,
        num_teams=12,
        my_position=4,
        pick_owners=traded,
        keepers=[{"overall": 144, "player_id": a}],
    )
    assert [(k["overall"], k["round"]) for k in s2["keepers"]] == [(144, 12)]
    r = client.patch(
        f"/sessions/{s2['id']}/keepers", json={"keepers": [{"overall": 148, "player_id": a}]}
    )
    assert r.status_code == 200, r.text
    assert [k["overall"] for k in client.get(f"/sessions/{s2['id']}").json()["keepers"]] == [148]


def test_a_keepers_file_may_name_the_pick(tmp_path, traded):
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    (tmp_path / SAMPLE).symlink_to(DATA / SAMPLE)
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as c:
        (a, name), (b, other) = best(c, 2)
        (tmp_path / "keepers_traded.csv").write_text(
            f"position,round,overall,player\nme,,145,{name}\n1,3,,{other}\n"
        )
        rows = c.get("/keepers-file?file=keepers_traded.csv").json()["rows"]
        assert [(r["position"], r["round"], r["overall"]) for r in rows] == [
            (None, None, 145),
            (1, 3, None),
        ]
        s = create(
            c, num_teams=12, my_position=4, pick_owners=traded, keepers_file="keepers_traded.csv"
        )
        assert [(k["overall"], k["player_id"], k["by_overall"]) for k in s["keepers"]] == [
            (25, b, False),
            (145, a, True),
        ]
        # Without an owner map pick 145 is position 1's: the row is refused by its line.
        e = create(c, status=400, num_teams=12, my_position=4, keepers_file="keepers_traded.csv")
        assert "line 2" in e["detail"] and "position 1" in e["detail"]


# --------------------------------------------------------------------------- room
@pytest.fixture
def league(tmp_path):
    return tmp_path, build_league(tmp_path)


def _order_note(owners: list[int]) -> dict:
    """The client's ``draft order`` note for the R| frame of a room with these owners."""
    return {
        "type": "note",
        "what": "draft order",
        "entries": len(owners),
        "teams": 12,
        "traded": len(traded_picks(owners, 12)) if len(owners) == 156 else None,
        "head": "R|...",
        "owners": [TEAM_OF[p] if 1 <= p <= 12 else p for p in owners],
        "pick_owners": owners,
    }


def test_a_room_attached_with_the_map_books_every_pick_to_its_owner(league, traded):
    """The real draft's shape (2026-10-14): my keeper logged by Yahoo in a pick I acquired,
    his history frame before round 1 with the snake's slot on it, picks 28 and 45 traded
    away. Every pick goes to its owner, my roster has all 13."""
    directory, picks = league
    P = {p.overall: p for p in picks}
    with app_for(directory) as c:
        room = attach(
            c,
            draft_id="t1",
            slot=4,
            pick_owners=traded,
            session={
                **SESSION,
                "my_position": 4,
                "keepers": [{"overall": 145, "player": _name(P[145])}],
            },
        )
        assert room["pick_owners"] == traded and room["traded_picks"] == TRADED
        assert [(k["overall"], k["slot"], k["mine"]) for k in room["keepers"]] == [(145, 4, True)]
        sid = room["session_id"]
        s = c.get(f"/sessions/{sid}").json()
        assert s["my_slots"] == POS4 and s["my_picks"] == [k for k in POS4 if k != 145]
        post_picks(c, "t1", [P[145]], slot=1, src="history")
        post_picks(c, "t1", [P[k] for k in range(1, 145)])  # no slot: the map says whose
        post_picks(c, "t1", [P[k] for k in range(146, 157)])
        rows = {p["overall"]: p for p in c.get(f"/sessions/{sid}/picks").json()}
        assert rows[28]["team"] == "Team 1" and rows[45]["team"] == "Team 1"
        assert rows[144]["team"] == "me" and rows[148]["team"] == "me"
        assert rows[145]["team"] == "me" and rows[145]["keeper"]
        s = c.get(f"/sessions/{sid}").json()
        assert len(s["my_roster"]) == 13 and s["complete"]
        status = c.get("/rooms/t1/status").json()
        assert status["live"]["picks_applied"] == 156 and status["conflicts"] == 0
    events = _events(directory, "t1")
    assert next(e for e in events if e["type"] == "attach")["pick_owners"] == traded
    kept = next(e for e in events if e["type"] == "room_pick" and e["overall"] == 145)
    assert kept["src"] == "keeper" and kept["via"] == "history" and kept["slot"] == 1
    differs = [e for e in events if e.get("what") == "pick owner differs"]
    assert [(e["overall"], e["room_slot"], e["owner"]) for e in differs] == [(145, 1, 4)]
    assert not [e for e in events if e["type"] == "conflict"]


def test_a_room_adopts_the_order_the_client_read(league, traded):
    directory, picks = league
    P = {p.overall: p for p in picks}
    with app_for(directory) as c:
        room = attach(c, draft_id="t2", slot=4, session={**SESSION, "my_position": 4})
        assert room["pick_owners"] is None and room["traded_picks"] == []
        sid = room["session_id"]
        post_picks(c, "t2", [P[k] for k in range(1, 29)])
        assert c.get(f"/sessions/{sid}/picks").json()[27]["team"] == "me", "the snake's owner"
        r = c.post("/rooms/t2/events", json={"events": [_order_note(traded)]})
        assert r.status_code == 200, r.text
        room = c.get("/rooms/t2").json()
        assert room["pick_owners"] == traded and room["traded_picks"] == TRADED
        s = c.get(f"/sessions/{sid}").json()
        assert s["my_slots"] == POS4 and s["pick_owners"] == traded and s["my_next_pick"] == 52
        assert c.get(f"/sessions/{sid}/picks").json()[27]["team"] == "Team 1"
        assert len(s["my_roster"]) == 2
        # A different order later is noted, not taken.
        other = list(traded)
        other[0], other[1] = other[1], other[0]
        c.post("/rooms/t2/events", json={"events": [_order_note(other)]})
        assert c.get("/rooms/t2").json()["pick_owners"] == traded
        # One that does not fit is refused, in a room that has none.
        attach(c, draft_id="t3", slot=4, session={**SESSION, "my_position": 4})
        c.post("/rooms/t3/events", json={"events": [_order_note(traded[:100])]})
        assert c.get("/rooms/t3").json()["pick_owners"] is None
    events = _events(directory, "t2")
    taken = [e for e in events if e.get("what") == "pick owners"]
    assert len(taken) == 1 and taken[0]["traded_picks"] == TRADED and taken[0]["relabelled"] == 1
    differs = next(e for e in events if e.get("what") == "draft order differs")
    assert differs["differs_at"] == [1, 2]
    refused = [e for e in _events(directory, "t3") if e.get("what") == "draft order refused"]
    assert len(refused) == 1 and "156 entries" in refused[0]["reason"]


def test_a_rebuild_keeps_the_map(league, traded):
    directory, _ = league
    with app_for(directory) as c:
        attach(c, draft_id="t4", slot=4, pick_owners=traded, session={**SESSION, "my_position": 4})
        attach(c, draft_id="t5", slot=4, session={**SESSION, "my_position": 4})
        c.post("/rooms/t5/events", json={"events": [_order_note(traded)]})
    with app_for(directory) as c:
        for draft_id in ("t4", "t5"):
            room = c.get(f"/rooms/{draft_id}").json()  # a rebuild from the log
            assert room["pick_owners"] == traded, draft_id
            assert c.get(f"/sessions/{room['session_id']}").json()["my_slots"] == POS4


def test_tier1_replay_with_traded_picks(league, traded):
    """Room 2515267 replayed as a league with the fixture's trades, from position 4: the
    scorecard's turns are my real picks, and nothing is attributed to the snake."""
    directory, picks = league
    with app_for(directory) as c:
        result = replay(
            c,
            picks,
            draft_id="traded-replay",
            slot=4,
            session={**SESSION, "my_position": 4},
            solve={"n": 3, "scenarios": 0, "time_limit": 3.0},
            plan_wait=0.0,
            pick_owners=traded,
        )
    assert result["attach"]["traded_picks"] == TRADED
    card = result["scorecard"]
    assert card["picks_seen"] == 156
    assert card["guardrails"]["G1"] == {"agree": 156, "of": 156, "total": 156}
    assert card["standins"] == 0 and card["conflicts"] == 0
    assert card["traded_picks"] == 10 and card["my_picks"] == POS4
    assert [r["overall"] for r in card["rows"]] == POS4
    assert card["compliance"]["my_picks_seen"] == 13
    assert "10 traded picks" in card["markdown"]
    live = result["status"]["live"]
    assert live["picks_applied"] == 156 and live["complete"]
    events = _events(directory, "traded-replay")
    room_slot = {e["overall"]: e["slot"] for e in events if e["type"] == "room_pick"}
    assert room_slot[28] == 1 and room_slot[45] == 1 and room_slot[144] == 4 and room_slot[145] == 4
    assert not [e for e in events if e.get("what") == "pick owner differs"]
    turns = [e["overall"] for e in events if e["type"] == "turn_start"]
    assert [k for k in turns if k in (28, 45, 144, 145)] == [144, 145], "only my turns start"
