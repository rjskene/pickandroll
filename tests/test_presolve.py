"""Solve latency in a live room (#13): pre-solved branches, early plans, superseded solves and
the turn budget. Hermetic: the synthetic league of ``test_yahoo_room`` (room 2515267's
players plus bench filler)."""

from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.api.presolve import (
    ONE_AWAY,
    TWO_AWAY,
    BranchBook,
    board_key,
    branch_boards,
    likely_next,
)
from pickandroll.api.solver import SolveParams, Superseded, compute_recommendation
from pickandroll.fidelity.replay import settled_replay
from pickandroll.optim.horizon import CANDIDATE_COLUMNS, first_order_table
from pickandroll.sources.yahoo import load_players_file

from .test_yahoo_room import SESSION, build_league

LIVE = {**SESSION, "solve_ahead": True}


@pytest.fixture
def room(tmp_path):
    """A live room for slot 2 (my first pick is one away), its store and the fixture picks."""
    picks = build_league(tmp_path)
    store = SessionStore()
    client = TestClient(create_app(store, data_dir=tmp_path))
    with client:
        yield client, store, picks


def _attach(client, slot=2, draft_id="p1", session=LIVE, **extra):
    body = {"draft_id": draft_id, "slot": slot, "session": session, **extra}
    r = client.post("/rooms", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _solver(client, sid):
    return client.get(f"/sessions/{sid}/solver").json()


def _until(fn, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("timed out")


def _pick(client, overall, yid):
    r = client.post(
        "/rooms/p1/picks", json={"picks": [{"overall": overall, "yahoo_player_id": yid}]}
    )
    assert r.status_code == 200, r.text


def test_players_file_reads_o_rank(tmp_path):
    (tmp_path / "p.json").write_text(
        '{"service": {"player_list": [{"id": 1, "fname": "A", "lname": "B", "o_rank": 7},'
        ' {"id": 2, "fname": "C", "lname": "D", "o_rank": "-"}]}}'
    )
    players = load_players_file(tmp_path / "p.json")
    assert players.loc["1", "o_rank"] == 7.0
    assert players.loc["2", "o_rank"] is None or pd.isna(players.loc["2", "o_rank"])


def test_likely_next_interleaves_o_rank_and_adp(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    state = store.get(sid).state
    adp = state.effective_adp().sort_values()
    by_adp = [str(p) for p in adp.index[:3]]
    # A made-up o_rank that reverses the ADP order of the top ten.
    o_rank = pd.Series({p: float(i) for i, p in enumerate(reversed(adp.index[:10]), start=1)})
    out = likely_next(state, o_rank, limit=4)
    assert out == [str(adp.index[9]), by_adp[0], str(adp.index[8]), by_adp[1]]
    assert likely_next(state, None, limit=3) == by_adp


def test_branch_boards_one_and_two_away_and_back_to_back(room):
    client, store, _ = room
    sid = _attach(client, slot=3)["session_id"]
    state = store.get(sid).state
    likely = likely_next(state, None, limit=ONE_AWAY)
    # Board 0, my pick is 3: two picks before it, so pairs of the top four.
    two = branch_boards(state, likely)
    assert len(two) == TWO_AWAY * (TWO_AWAY - 1) // 2
    assert all(len(b.picks) == 2 and b.key[0] == 3 for b in two)
    assert len({b.key for b in two}) == len(two)
    # One pick before mine: one board per likely player.
    state.apply_pick("Team 1", likely[0], 1)
    one = branch_boards(state, likely_next(state, None, limit=ONE_AWAY))
    assert len(one) == ONE_AWAY and all(b.key[0] == 3 for b in one)
    # The board each branch stands for is the one the pick produces.
    state.apply_pick("Team 2", one[0].picks[0][2], 2)
    assert board_key(state) == one[0].key
    # On the clock, with my next pick straight after (slot 12 picks 12 and 13): my own choices.
    s12 = store.get(_attach(client, slot=12, draft_id="p12")["session_id"]).state
    for k in range(1, 12):
        s12.apply_pick(f"Team {k}", likely_next(s12, None, limit=1)[0], k)
    mine = likely_next(s12, None, limit=2)
    b2b = branch_boards(s12, [], mine)
    assert [b.picks[0][1] for b in b2b] == [s12.my_team, s12.my_team]
    assert all(b.key[0] == 13 and len(b.key[2]) == 1 for b in b2b)


def test_branch_book_counts_each_turn_once_and_prunes(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    state = store.get(sid).state
    branch = branch_boards(state, likely_next(state, None))[0]
    book = BranchBook()
    entry = book.add(branch, future=None)
    book.done(entry, None)
    assert book.take(branch.key) is entry and book.take(branch.key) is entry
    assert book.take((99, frozenset(), frozenset())) is None
    assert book.status()["hits"] == 1 and book.status()["misses"] == 1
    book.prune((branch.key[0] + 1, branch.key[1], branch.key[2]))
    assert book.status()["held"] == 0


def test_branch_book_drops_the_pairs_a_pick_ruled_out(room):
    client, store, _ = room
    sid = _attach(client, slot=3)["session_id"]
    state = store.get(sid).state
    pairs = branch_boards(state, likely_next(state, None))  # picks 1 and 2 before my 3
    book = BranchBook()
    for b in pairs:
        book.add(b, future=None)
    first = pairs[0].picks[0][2]
    state.apply_pick("Team 1", first, 1)
    book.prune(board_key(state))
    kept = set(book.entries)
    assert kept == {b.key for b in pairs if first in b.key[1]} and len(kept) == TWO_AWAY - 1


def test_first_order_table_leads_with_the_plan_pick(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    state = store.get(sid).state
    problem = state.horizon_problem()
    solution = state.solve_plan(problem, time_limit=3.0)
    cands = state.candidates(4, expected=True)
    table = first_order_table(problem, solution, cands)
    assert list(table.columns) == CANDIDATE_COLUMNS
    assert table.iloc[0]["player"] == solution.first_pick and table.iloc[0]["cost_vs_best"] == 0
    assert set(cands) <= set(table["player"])
    costs = table["cost_vs_best"].iloc[1:].dropna()
    assert costs.is_monotonic_increasing


def test_a_presolved_board_is_the_recommendation_the_moment_it_arrives(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    # Board 0, my pick is 2: one board per likely first pick is planned ahead.
    status = _until(
        lambda: (s := _solver(client, sid))["presolve"]["solved"] >= ONE_AWAY and s or None
    )
    assert status["presolve"]["launched"] == ONE_AWAY
    likely = likely_next(session.state, None)
    yid = session.room.ids.yid(likely[0])
    _pick(client, 1, yid)
    plan = client.get("/rooms/p1/plan", params={"wait": 2}).json()
    assert plan["fresh"] and plan["waited_ms"] < 1000
    rec = session.recommendation
    assert rec["branch"] is True and rec["priced"] is False and rec["next_overall"] == 2
    assert _solver(client, sid)["presolve"]["hits"] == 1
    # The live solve then prices the same plan exactly.
    _until(
        lambda: (
            session.recommendation["priced"] and session.recommendation["version"] == rec["version"]
        )
    )
    events = [e for e in session.room.log.read() if e.get("type") == "reco" and e["board"] == 1]
    assert events[0]["branch"] is True and events[-1]["priced"] is True


def test_a_board_nobody_planned_is_solved_as_usual(room):
    client, store, picks = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    _until(lambda: _solver(client, sid)["presolve"]["solved"] >= ONE_AWAY)
    likely = set(likely_next(session.state, None))
    outsider = next(p for p in picks[30:] if session.room.ids.pid(p.yahoo_player_id) not in likely)
    _pick(client, 1, outsider.yahoo_player_id)
    plan = client.get("/rooms/p1/plan", params={"wait": 20}).json()
    assert plan["fresh"]
    assert session.recommendation["branch"] is False
    assert _solver(client, sid)["presolve"]["misses"] == 1


def test_a_solve_stops_once_its_board_is_replaced(room):
    client, store, _ = room
    sid = _attach(client, session=SESSION)["session_id"]
    session = store.get(sid)
    with pytest.raises(Superseded):
        compute_recommendation(session, SolveParams(n=2), stop=lambda: True)
    early: list[dict] = []
    calls = {"n": 0}

    def stop() -> bool:  # the board moves while the plan solves
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(Superseded):
        compute_recommendation(
            session, SolveParams(n=2, early=True), on_early=early.append, stop=stop
        )
    assert len(early) == 1 and early[0]["priced"] is False and early[0]["candidates"]


def test_my_turn_gets_the_turn_budget(room, monkeypatch):
    client, store, picks = room
    sid = _attach(client, slot=1, session=SESSION)["session_id"]
    session = store.get(sid)
    seen: list = []
    original = session.state.solve_plan

    def spy(problem, time_limit=None):
        seen.append(time_limit)
        return original(problem, time_limit)

    monkeypatch.setattr(session.state, "solve_plan", spy)
    params = SolveParams(n=3, turn_time_limit=1.5, turn_n=2)
    payload = compute_recommendation(session, params)  # board 0: my pick 1 is on the clock
    assert seen == [1.5] and len(payload["candidates"]) <= 3
    _pick(client, 1, picks[0].yahoo_player_id)
    compute_recommendation(session, params)  # off the clock: the normal budget
    assert seen[-1] is None


def test_settled_replay_drafts_the_fresh_top_and_shifts_collisions(room):
    client, _, picks = room
    rank = {p.yahoo_player_id: float(p.overall) for p in picks}
    out = settled_replay(
        client,
        picks,
        draft_id="s1",
        slot=6,
        rank=rank,
        session=SESSION | {"solve_ahead": True},
        solve={"presolve": False},
    )
    card = out["scorecard"]
    assert len(out["mine"]) == 13 and all(m["fresh"] for m in out["mine"])
    assert card["compliance"]["compliant"] == 13 and card["guardrails"]["G1"]["agree"] == 156
    # Every player I took that the room took later went to someone else instead.
    fixture_mine = {picks[m["overall"] - 1].yahoo_player_id for m in out["mine"]}
    collisions = {m["yid"] for m in out["mine"]} - fixture_mine
    assert out["shifted"] == len(
        [
            p
            for p in picks
            if p.yahoo_player_id in collisions
            and p.overall not in {m["overall"] for m in out["mine"]}
        ]
    )
    assert out["score"]["final"] is not None and out["score"]["final"]["wins"] > 0
