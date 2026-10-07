"""Solve latency in a live room (#13): pre-solved branches, early plans, superseded solves and
the turn budget. Hermetic: the synthetic league of ``test_yahoo_room`` (room 2515267's
players plus bench filler)."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.api import solver as solver_module
from pickandroll.api.presolve import (
    MINE,
    ONE_AWAY,
    ONE_AWAY_MAX,
    OWN_EARLY,
    TWO_AWAY,
    BranchBook,
    board_key,
    branch_boards,
    likely_next,
    one_pick_left,
)
from pickandroll.api.solver import (
    SolveParams,
    Superseded,
    compute_recommendation,
    displaces,
    opening_payload,
)
from pickandroll.draft import Keeper
from pickandroll.fidelity.replay import settled_replay
from pickandroll.optim.horizon import CANDIDATE_COLUMNS, first_order_table
from pickandroll.optim.pool import BACKGROUND_NICE, LIVE_CORES, background_pool, background_size
from pickandroll.sources.yahoo import load_players_file

from .test_draft_state import make_state
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


def _recos(session, board):
    """The recos logged for ``board``. A reco is logged just after it is set
    (``Session.set_recommendation``): a test that sees it set from its own thread, not through
    an API call, waits for its log entry."""
    return [e for e in session.room.log.read() if e.get("type") == "reco" and e["board"] == board]


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
    # A branch still solving when its board is first looked at is pending, not a hit.
    running = book.add(branch, future=Future())
    assert book.take(branch.key) is running and book.status()["pending"] == 1
    assert book.status()["hits"] == 1


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
    # Past a bot room's pace the set grows on idle workers (#14 lever 5), never past the cap.
    assert ONE_AWAY <= status["presolve"]["launched"] <= ONE_AWAY_MAX
    likely = likely_next(session.state, None)
    yid = session.room.ids.yid(likely[0])
    _pick(client, 1, yid)
    plan = client.get("/rooms/p1/plan", params={"wait": 2}).json()
    assert plan["fresh"] and plan["waited_ms"] < 1000
    rec = session.recommendation
    assert rec["branch"] is True and rec["priced"] is False and rec["next_overall"] == 2
    assert _solver(client, sid)["presolve"]["hits"] == 1
    # The live solve then prices the same plan exactly.
    events = _until(lambda: (ev := _recos(session, 1)) and ev[-1]["priced"] and ev)
    assert events[0]["branch"] is True and events[-1]["priced"] is True
    # Each reco logs the objective behind its #1, whether it was capped, and (a live solve)
    # the pre-solves in flight while it ran.
    assert events[0]["capped"] is False and events[0]["branches_running"] is None
    assert events[0]["branch_late"] is False and events[-1]["branch_late"] is None
    assert events[-1]["top_objective"] >= events[0]["top_objective"]
    assert events[-1]["branches_running"] >= 0
    # The scorecard keeps priced solve times apart from the plans that came early or ready.
    d = client.get("/rooms/p1/fidelity").json()["diagnostics"]
    priced = [
        e
        for e in session.room.log.read()
        if e.get("type") == "reco" and e["priced"] and e.get("solve_ms") is not None
    ]
    assert d["D3"]["n"] == len(priced) and d["D3_plan"]["branch"] == 1


def test_a_branch_still_solving_at_the_turn_is_pending_and_logged_late(room, monkeypatch):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    # The branches and board 0's live solve, all done: under load they take far longer.
    _until(
        lambda: (
            _solver(client, sid)["presolve"]["solved"] >= ONE_AWAY and session.solver.inflight == 0
        ),
        timeout=300.0,
    )
    # Board 1's live solve waits for the late branch: neither can publish first by chance.
    gate = threading.Event()
    original = session.state.solve_plan

    def gated(problem, time_limit=None):
        gate.wait(120)
        return original(problem, time_limit)

    monkeypatch.setattr(session.state, "solve_plan", gated)
    likely = likely_next(session.state, None)
    entry = next(
        e for e in session.solver.book.entries.values() if e.branch.picks[0][2] == likely[0]
    )
    solution, entry.solution = entry.solution, None
    entry.future = Future()  # the board arrives while its branch is still solving
    try:
        _pick(client, 1, session.room.ids.yid(likely[0]))
        _until(lambda: session.solver.book.pending == 1)
        entry.solution = solution
        entry.future.set_result(solution)

        recos = _until(lambda: (r := _recos(session, 1)) and any(e["branch"] for e in r) and r)
    finally:
        gate.set()
    # My first pick is in round 1: the plan solved before the draft stands in at once (#14
    # lever 4), and the branch replaces it the moment it lands.
    assert recos[0]["opening"] is True
    branch = next(e for e in recos if e["branch"])
    assert branch["branch_late"] is True
    assert session.solver.book.hits == 0


def test_a_board_nobody_planned_is_solved_as_usual(room):
    client, store, picks = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    _until(lambda: _solver(client, sid)["presolve"]["solved"] >= ONE_AWAY)
    # The one-away set may have grown while the board waited (#14 lever 5).
    likely = set(likely_next(session.state, None, limit=ONE_AWAY_MAX))
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


def test_a_payload_keeps_its_own_timings_and_scale_when_another_solve_finishes(room, monkeypatch):
    client, store, _ = room
    sid = _attach(client, session=SESSION | {"objective": "win"})["session_id"]
    state = store.get(sid).state
    original = state.recommend_horizon

    def then_another_solve_lands(*args, **kwargs):
        out = original(*args, **kwargs)
        state.last_fallback = "sum"  # what a concurrent solve on this state leaves behind
        state.last_timings = {"total_ms": -1.0}
        return out

    monkeypatch.setattr(state, "recommend_horizon", then_another_solve_lands)
    payload = compute_recommendation(store.get(sid), SolveParams(n=2))
    assert payload["fallback"] is None and payload["scale"] == "wins"
    assert payload["timings"]["total_ms"] > 0 and "plan_ms" in payload["timings"]


def test_pruning_a_queued_solve_does_not_deadlock_the_book(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    state = store.get(sid).state
    branch = branch_boards(state, likely_next(state, None))[0]
    book = BranchBook()
    future: Future = Future()  # queued in the pool, not started
    entry = book.add(branch, future)
    future.add_done_callback(lambda f, e=entry: book.done(e, None))  # as _presolve wires it
    worker = threading.Thread(
        target=book.prune, args=((branch.key[0] + 1, branch.key[1], branch.key[2]),), daemon=True
    )
    worker.start()
    worker.join(5)
    assert not worker.is_alive() and future.cancelled() and book.status()["held"] == 0


def test_a_capped_plan_is_not_published_before_its_prices(room, monkeypatch):
    client, store, _ = room
    sid = _attach(client, session=SESSION)["session_id"]
    session = store.get(sid)
    original = session.state.solve_plan

    def capped(problem, time_limit=None):
        return replace(original(problem, time_limit), time_limited=True)

    monkeypatch.setattr(session.state, "solve_plan", capped)
    early: list[dict] = []
    payload = compute_recommendation(session, SolveParams(n=2, early=True), on_early=early.append)
    assert early == [] and payload["priced"] is True


def test_a_capped_branch_is_priced_not_served(room):
    client, store, _ = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    _until(lambda: _solver(client, sid)["presolve"]["solved"] >= ONE_AWAY)
    for entry in session.solver.book.entries.values():
        entry.solution = replace(entry.solution, time_limited=True)
    likely = likely_next(session.state, None)
    _pick(client, 1, session.room.ids.yid(likely[0]))
    plan = client.get("/rooms/p1/plan", params={"wait": 20}).json()
    assert plan["fresh"] and _solver(client, sid)["presolve"]["hits"] == 1
    # My first pick is in round 1: the plan solved before the draft stands in (#14 lever 4)
    # until the live solve prices the capped branch's plan.
    recos = _until(lambda: (r := _recos(session, 1)) and len(r) > 1 and r, timeout=300.0)
    assert recos[0]["opening"] is True
    assert recos[1]["priced"] is True and not any(e["branch"] for e in recos)


def test_the_plan_budget_follows_the_clock(room):
    client, store, _ = room
    cases = [
        ({}, 5.0),  # the mocks' 30 s clock
        ({"clock_s": 30}, 5.0),
        ({"clock_s": 40}, 15.0),
        ({"clock_s": 90}, 20.0),
        ({"clock_s": 90, "time_limit": 8}, 8.0),
    ]
    for i, (extra, want) in enumerate(cases):
        sid = _attach(client, draft_id=f"c{i}", session=SESSION, **extra)["session_id"]
        assert store.get(sid).state.plan_time_limit == want


def test_the_room_follows_the_clock_it_is_shown(room):
    client, store, _ = room
    sid = _attach(client, draft_id="k1", session=SESSION)["session_id"]
    session = store.get(sid)

    def turn(draft_id: str, clock: int) -> None:
        event = {"type": "turn_start", "overall": 1, "slot": 1, "clock_s": clock}
        r = client.post(f"/rooms/{draft_id}/events", json={"events": [event]})
        assert r.status_code == 200, r.text

    turn("k1", 30)  # the mocks' clock: the 5 s budget stands
    assert session.state.plan_time_limit == 5.0
    turn("k1", 90)
    assert session.state.plan_time_limit == 20.0 and session.state.price_time_limit == 10.0
    turn("k1", 40)  # a reconnect mid-pick shows less time: the longest clock stands
    assert session.state.plan_time_limit == 20.0
    notes = [e for e in session.room.log.read() if e.get("what") == "plan_budget"]
    assert [(n["clock_s"], n["time_limit"]) for n in notes] == [(90.0, 20.0)]
    # A time_limit given at attach is kept, whatever the clock.
    fixed = store.get(_attach(client, draft_id="k2", session=SESSION, time_limit=8)["session_id"])
    turn("k2", 90)
    assert fixed.state.plan_time_limit == 8.0


def test_branch_solves_run_below_the_live_ones():
    mine = os.nice(0)
    theirs = background_pool().submit(os.nice, 0).result(timeout=120)
    assert theirs >= min(mine + BACKGROUND_NICE, 19)
    # And on fewer workers than cores: the live solve has cores they never take.
    cores = os.cpu_count() or 2
    assert background_pool()._max_workers == background_size() == max(1, cores - LIVE_CORES)


def _reco(top, objective, *, priced=True, capped=False, version=5):
    return {
        "version": version,
        "candidates": [{"player": top}],
        "top_objective": objective,
        "capped": capped,
        "priced": priced,
    }


def test_a_reco_never_displaces_one_at_least_as_good():
    converged = _reco("a", 6.20, priced=False)
    # Pick 144's hypothesis (b): exact prices on a 5 s capped plan came out below the
    # converged branch: the branch stays.
    assert not displaces(_reco("b", 6.15, capped=True), converged)
    assert displaces(_reco("b", 6.25, capped=True), converged)  # a better plan is better
    # A tie: exact prices with the same #1 replace first-order ones; another #1 does not.
    assert displaces(_reco("a", 6.20), converged)
    assert not displaces(_reco("b", 6.20), converged)
    # A tie: converged beats capped, never the other way.
    assert displaces(_reco("b", 6.20, priced=False), _reco("a", 6.20, capped=True))
    assert not displaces(_reco("b", 6.20, capped=True), _reco("a", 6.20, priced=False))
    # Nothing priced replaces exact prices of the same objective.
    assert not displaces(_reco("a", 6.20, priced=False), _reco("a", 6.20))
    # The single-roster model has no objective: exact prices win, as before.
    roster = {"version": 5, "candidates": [{"player": "a"}], "priced": True}
    assert displaces(roster, {**roster, "priced": False})
    assert not displaces({**roster, "priced": False}, roster)


def test_the_exact_prices_cover_the_installed_plans_first_pick(room):
    client, store, _ = room
    sid = _attach(client, session=SESSION)["session_id"]
    session = store.get(sid)
    state = session.state
    with session.lock:
        listed = state.candidates(2, expected=True)
        outsider = next(p for p in state.candidates(40, expected=True) if p not in listed)
    # A plan already serving this board whose first pick the live list would not price.
    session.recommendation = {
        "version": session.version,
        "plan": [{"pick": state.next_overall, "player": outsider}],
    }
    payload = compute_recommendation(session, SolveParams(n=2))
    priced = {c["player"] for c in payload["candidates"]}
    assert outsider in priced and set(listed) <= priced
    assert payload["top_objective"] is not None and payload["capped"] in (True, False)


# --------------------------------------------------------------------------- keepers
def test_branch_boards_pass_a_keeper_slot_without_branching_on_it(pool):
    """Four teams, my seat 3, picks 4 to move: pick 5 is team 4's keeper, so my turn (6) is
    one real pick away, not two."""
    best = make_state(pool).z["total"].nlargest(4).index.tolist()
    kept = best[0]
    state = make_state(pool, position=3, num_teams=4, keepers=[Keeper(4, 2, kept)])
    state.sync([(1, "Team 1", best[1]), (2, "Team 2", best[2]), (3, "me", best[3])])
    assert (state.next_overall, state.my_next_pick) == (4, 6)
    likely = likely_next(state, limit=ONE_AWAY)
    assert kept not in likely
    branches = branch_boards(state, likely)
    assert len(branches) == len(likely) == ONE_AWAY
    assert all(len(b.picks) == 1 and b.picks[0][0] == 4 for b in branches)
    assert all(b.key[0] == 6 and kept in b.key[1] for b in branches)


def test_my_keeper_right_after_my_pick_is_not_back_to_back(pool):
    """Seat 4 of 4 owns picks 4 and 5; with my round-2 keeper at 5 there is no second pick of
    mine to branch on."""
    best = make_state(pool).z["total"].nlargest(5).index.tolist()
    mine = best[3:]
    plain = make_state(pool, position=4, num_teams=4)
    plain.sync([(1, "Team 1", best[0]), (2, "Team 2", best[1]), (3, "Team 3", best[2])])
    assert plain.on_the_clock and branch_boards(plain, [], mine)
    kept = make_state(pool, position=4, num_teams=4, keepers=[Keeper(None, 2, best[4])])
    kept.sync([(1, "Team 1", best[0]), (2, "Team 2", best[1]), (3, "Team 3", best[2])])
    assert kept.on_the_clock and kept.my_picks[:2] == [4, 12]
    assert branch_boards(kept, [], mine[:1]) == []


# --------------------------------------------------------------------------- #14 coverage
def test_one_away_grows_and_a_pairs_own_choice_starts_one_pick_early(room):
    """Slot 12 with pick 11 on the clock: one board per likely player (as many as the waiting
    allows), and, past a bot room's pace, the boards for pick 13 behind the likeliest picks at
    11 and my likely choices at 12, a choice the opponent took giving way to the next one."""
    client, store, _ = room
    state = store.get(_attach(client, slot=12, draft_id="p12")["session_id"]).state
    for k in range(1, 11):
        state.apply_pick(f"Team {k}", likely_next(state, None, limit=1)[0], k)
    assert state.next_overall == 11 and one_pick_left(state)
    likely = likely_next(state, None, limit=ONE_AWAY_MAX)
    mine = [likely[0], likely[7], likely[8]]
    plain = branch_boards(state, likely, mine)
    assert len(plain) == ONE_AWAY and all(len(b.picks) == 1 for b in plain)
    grown = branch_boards(state, likely, mine, one_away=ONE_AWAY_MAX, early=True)
    one = [b for b in grown if len(b.picks) == 1]
    own = [b for b in grown if len(b.picks) == 2]
    assert [b.picks[0][2] for b in one] == likely[:ONE_AWAY_MAX]
    assert len(own) == OWN_EARLY * MINE and all(b.key[0] == 13 for b in own)
    pairs = [(b.picks[0][2], b.picks[1][2]) for b in own]
    assert pairs[:MINE] == [(likely[0], likely[7]), (likely[0], likely[8])]
    assert pairs[MINE : 2 * MINE] == [(likely[1], likely[0]), (likely[1], likely[7])]
    assert all(b.picks[1][1] == state.my_team and b.picks[1][0] == 12 for b in own)
    # Boards already planned are not built again.
    known = {b.key for b in plain}
    rest = branch_boards(
        state, likely, mine, one_away=ONE_AWAY_MAX, early=True, skip=known.__contains__
    )
    assert {b.key for b in rest} == {b.key for b in grown} - known
    # Two picks before mine, or my pick on the clock: no one-away growth applies.
    state.apply_pick("Team 11", likely[0], 11)
    assert not one_pick_left(state)


def test_the_early_own_choice_set_needs_a_real_second_pick(pool):
    """Seat 4 of 4 with pick 3 on the clock: picks 4 and 5 are a pair, unless 5 is my keeper's
    round (keeper slots stay out of the branches)."""
    best = make_state(pool).z["total"].nlargest(6).index.tolist()
    plain = make_state(pool, position=4, num_teams=4)
    plain.sync([(1, "Team 1", best[0]), (2, "Team 2", best[1])])
    assert one_pick_left(plain)
    boards = branch_boards(plain, best[2:5], best[2:5], early=True)
    assert any(len(b.picks) == 2 for b in boards)
    kept = make_state(pool, position=4, num_teams=4, keepers=[Keeper(None, 2, best[5])])
    kept.sync([(1, "Team 1", best[0]), (2, "Team 2", best[1])])
    boards = branch_boards(kept, best[2:5], best[2:5], early=True)
    assert boards and all(len(b.picks) == 1 for b in boards)


def test_a_board_that_waits_grows_its_one_away_set_on_idle_workers(room, monkeypatch):
    """With no bot-pace grace and room on the pool, slot 2's board 0 ends with one branch per
    likely player up to the cap; slot 2 has no pair, so no own-choice boards."""
    monkeypatch.setattr(solver_module, "GROW_AFTER_S", 0.0)
    monkeypatch.setattr(solver_module, "background_size", lambda: ONE_AWAY + 2)
    client, store, _ = room
    sid = _attach(client)["session_id"]
    session = store.get(sid)
    _until(lambda: _solver(client, sid)["presolve"]["launched"] >= ONE_AWAY_MAX, timeout=300.0)
    time.sleep(1.0)  # nothing more comes
    assert _solver(client, sid)["presolve"]["launched"] == ONE_AWAY_MAX
    picks = [e.branch.picks for e in session.solver.book.entries.values()]
    assert all(len(p) == 1 and p[0][0] == 1 for p in picks)
    likely = likely_next(session.state, None, limit=ONE_AWAY_MAX)
    assert sorted(p[0][2] for p in picks) == sorted(likely)


def test_opening_payload_serves_the_first_pick_from_the_pre_draft_plan():
    opening = {
        "version": 1,
        "next_overall": 1,
        "mode": "horizon",
        "priced": True,
        "top_objective": 6.0,
        "candidates": [
            {"player": "a", "cost_vs_best": 0.0, "tie": False},
            {"player": "b", "cost_vs_best": 0.1, "tie": False},
            {"player": "c", "cost_vs_best": 0.3, "tie": False},
        ],
        "plan": [{"pick": 3, "player": "a"}, {"pick": 4, "player": "d"}],
        "score": {"version": 1},
    }
    prices = pd.Series({"a": 0.0, "b": 0.05, "c": 0.2, "d": 0.25, "e": 0.4, "f": float("nan")})
    snapshot = {"version": 7, "next_overall": 3, "on_the_clock": True, "my_next_pick": 3}
    names = pd.Series({p: p.upper() for p in "abcdef"})
    out = opening_payload(opening, prices, snapshot, frozenset({"a", "e"}), names)
    assert out is not None and out["opening"] is True and out["priced"] is False
    assert out["version"] == 7 and out["next_overall"] == 3 and out["score"] is None
    assert out["top_objective"] is None and out["branch"] is False
    rows = [(r["player"], r["cost_vs_best"]) for r in out["candidates"]]
    assert rows == [("b", 0.0), ("c", 0.2), ("d", None)]
    assert out["candidates"][2]["cost_first_order"] == 0.25
    assert [r["player"] for r in out["plan"]] == ["d"]
    assert opening_payload(opening, None, snapshot, frozenset("abc"), names) is None
    # Whatever is solved for the board replaces it, plan-only or capped.
    assert displaces(_reco("x", 1.0, priced=False, capped=True), out)


def test_my_first_pick_is_served_from_the_pre_draft_plan_at_once(room):
    """Slot 3: picks 1 and 2 go to players no branch planned for, so board 2 is a miss. My
    turn still has a reco at once, from the plan solved before the draft, and the board's own
    solve replaces it."""
    client, store, _ = room
    sid = _attach(client, slot=3)["session_id"]
    session = store.get(sid)
    state = session.state
    _until(
        lambda: (
            (rec := session.recommendation) is not None
            and rec["priced"]
            and rec["next_overall"] == 1
        ),
        timeout=300.0,
    )
    deep = [p for p in likely_next(state, None, limit=40)][ONE_AWAY_MAX:]
    yid = session.room.ids.yid
    _pick(client, 1, yid(deep[0]))
    _pick(client, 2, yid(deep[1]))
    plan = client.get("/rooms/p1/plan", params={"wait": 2}).json()
    assert plan["fresh"] and plan["waited_ms"] < 1000 and plan["next_overall"] == 3
    first = [e for e in session.room.log.read() if e.get("type") == "reco" and e["board"] == 2]
    assert first[0]["opening"] is True and first[0]["top_pid"] not in (deep[0], deep[1])
    _until(lambda: session.recommendation.get("opening") is not True, timeout=300.0)
    assert session.recommendation["version"] == plan["version"]
    _pick(client, 3, yid(first[0]["top_pid"]))
    rows = client.get("/rooms/p1/fidelity").json()["rows"]
    assert rows[0]["overall"] == 3 and rows[0]["presolve"] == "opening"
