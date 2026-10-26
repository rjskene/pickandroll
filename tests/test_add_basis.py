"""An add's basis (#187): an open active spot, a held-slot move that makes room, or a drop, as the
moves payload states the room and each move, the decision log records the basis and the queue
copies it. The model is unchanged: these pin both no-drop paths and the full roster through
``moves_payload``. Every league here is made up (``test_moves``'s fixtures); the outcomes are set
by construction."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from pickandroll.api import season_decisions
from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import autopilot as qa
from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv

from .test_moves import (
    WEEKS,
    build,
    il_full_league,
    il_league,
    player,
    schedule,
    streaming_league,
)
from .test_season_guard import built_of

AT = datetime(2026, 10, 26, 12, tzinfo=UTC)
IL5 = {"player": 5, "slot": "IL"}


def solved(p: mv.MoveProblem):
    built = built_of(p)
    out = sm.moves_payload(built)
    return out, season_decisions.moves_entry(built, out, AT)


def pairs(rec) -> list[tuple[int, int | None]]:
    return [(m["add"], m["drop"]) for m in rec["moves"]]


def logged(entry, key: str) -> list[tuple[int, int | None, str, dict | None]]:
    s = next(s for s in entry["sets"] if s["key"] == key)
    return [(m["add"], m["drop"], m["basis"], m["held"]) for m in s["moves"]]


def swaps(p: mv.MoveProblem, key: str, cand: int) -> list[tuple[int | None, float]]:
    return [(g.drop, round(g.gain, 3)) for g in mv.single_swaps(mv.Evaluator(p), key)[cand]]


# --------------------------------------------------------------------------- the basis
def test_the_basis_is_a_drop_a_held_move_or_an_open_spot():
    assert dl.basis_of(3, None) == dl.DROP
    assert dl.basis_of(None, IL5) == dl.HELD
    assert dl.basis_of(None, None) == dl.OPEN


# --------------------------------------------------------------------------- (a) an open spot
def test_one_short_of_the_active_spots_the_best_add_takes_the_open_spot_with_no_drop():
    roster, cands, rate, sched, opponent, field = streaming_league()
    p = build(roster, cands, rate, sched, opponent, field, spots=4)
    out, entry = solved(p)
    assert out["room"] == {"open_spots": 1, "held_open": {}, "eligible": []}
    # The streamer is the week's best add, priced against nothing.
    row = out["candidates"]["10"]["week"]
    assert (row["drop"], row["held"]) == (None, None) and row["gain"] > 0
    assert swaps(p, "week", 10)[0][0] is None
    week = out["recommended"]["week"]
    assert pairs(week)[0] == (10, None) and week["moves"][0]["held"] is None
    assert week["held"] == []
    assert logged(entry, "week")[0] == (10, None, dl.OPEN, None)
    assert {m[2] for m in logged(entry, "week")[1:]} <= {dl.DROP}


# --------------------------------------------------------------------------- (b) a held move
def test_a_full_roster_with_an_open_il_and_an_out_player_moves_him_there_for_the_add():
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    out, entry = solved(p)
    assert out["room"] == {"open_spots": 0, "held_open": {"IL": 1}, "eligible": [5]}
    # On the week the held move beats dropping the player who barely plays (he still plays) and
    # ties dropping the out player, who plays no game this week either way: the tie goes to the
    # move with no drop, so the basis is the held move.
    week_10 = swaps(p, "week", 10)
    assert week_10[0] == (None, pytest.approx(week_10[1][1]))
    assert week_10[1][0] == 5 and dict(week_10)[3] < week_10[0][1]
    row = out["candidates"]["10"]["week"]
    assert (row["drop"], row["held"]) == (None, IL5)
    week = out["recommended"]["week"]
    assert pairs(week)[0] == (10, None) and week["moves"][0]["held"] == IL5
    assert week["held"] == [IL5]
    assert logged(entry, "week")[0] == (10, None, dl.HELD, IL5)


def test_a_plain_drop_wins_when_the_comeback_would_send_a_player_the_weeks_ahead_need():
    roster, cands, rate, sched, opponent, field, value = il_league()
    # Player 2 plays no game this week and every other day after; his per-game value ranks
    # him last, so the out player's return would send him, though the three weeks need him more
    # than the player who barely plays.
    two = schedule({"TWO": [7 + d for d in range(21) if d % 2 == 0]})
    sched = {d: sched[d] | two[d] for d in sched}
    roster = [roster[0], player(2, "TWO"), *roster[2:]]
    p = build(
        roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value | {2: 0.05}
    )
    assert mv.comebacks(p, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 2)]
    out, entry = solved(p)
    assert out["room"] == {"open_spots": 0, "held_open": {"IL": 1}, "eligible": [5]}
    # Priced against every drop, the held move loses on the three weeks to dropping player 3.
    three_11 = swaps(p, "three", 11)
    assert three_11[0][0] == 3 and dict(three_11)[None] < three_11[0][1]
    row = out["candidates"]["11"]["three"]
    assert (row["drop"], row["held"]) == (3, None)
    three = out["recommended"]["three"]
    assert pairs(three) == [(11, 3)] and three["held"] == []
    assert logged(entry, "three") == [(11, 3, dl.DROP, None)]
    # This week, where the comeback falls outside, the held move still wins.
    assert logged(entry, "week")[0] == (10, None, dl.HELD, IL5)


# --------------------------------------------------------------------------- (c) the IL full
def test_a_full_roster_with_the_il_full_gets_drops_only_and_the_same_sets():
    p = il_full_league([(7, "O")], {})
    out, entry = solved(p)
    # The full IL is stated at zero, with the out player who would take it.
    assert out["room"] == {"open_spots": 0, "held_open": {"IL": 0}, "eligible": [5]}
    ev = mv.Evaluator(p)
    allowed = mv.season_guard(sm.guard_ros(built_of(p)))
    for key in sm.HORIZONS:
        rec = out["recommended"][key]
        assert rec["moves"] and all(
            m["drop"] is not None and m["held"] is None for m in rec["moves"]
        )
        assert all(basis == dl.DROP for _, _, basis, _ in logged(entry, key))
        # No behaviour change: the sets are the guarded search's own.
        swapped = mv.single_swaps(ev, key)
        ranked = sorted(
            (c for c, g in swapped.items() if g and g[0].gain > sm.MIN_GAIN),
            key=lambda c: -swapped[c][0].gain,
        )
        direct = mv.recommend(ev, key, ranked[: sm.POOL], min_gain=sm.MIN_GAIN, allowed=allowed)
        assert pairs(rec) == [(pm.move.add, pm.move.drop) for pm in direct.moves]
    for row in out["candidates"].values():
        assert all(row[k] is None or row[k]["drop"] is not None for k in sm.HORIZONS)


def test_a_league_with_no_held_slots_states_none():
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = build(roster, cands, rate, sched, opponent, field, value=value)
    assert sm.room_payload(p) == {"open_spots": 0, "held_open": {}, "eligible": []}


def test_the_held_kinds_are_in_placement_order_and_the_eligible_in_stash_order():
    roster, cands, rate, sched, opponent, field, value = il_league()
    late = (6, Player(6, "Late", "MIN", ("C",), status="O"))
    p = build(
        [*roster, late],
        cands,
        {**rate, 6: rate[5]},
        sched,
        opponent,
        field,
        held_open={"IL+": 1, "IL": 0},
        value=value | {6: 1.0},
        returns={6: WEEKS[2][0]},
    )
    r = mv.room(p)
    assert list(r.held_open) == ["IL", "IL+"] and r.held_open == {"IL": 0, "IL+": 1}
    # The later return first, as a held slot takes them.
    assert r.eligible == (6, 5)


# --------------------------------------------------------------------------- the queue
def day_of(e) -> qa.LeagueDay:
    return qa.LeagueDay(
        league="900001",
        scoring="categories",
        entry=e,
        mode="dry_run",
        private=False,
        protected={},
        availability={},
        flags={},
        dropped=frozenset(),
        budget=100.0,
        cap=2,
        adds_left={},
    )


def test_the_queue_entry_copies_the_moves_basis_and_held_move():
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    _, entry = solved(p)
    (e,) = qa.queue_of(day_of(entry), date(2026, 10, 26), qa.noise_floor([], 0.1), (0.1, "x"), None)
    assert (e["add"], e["drop"], e["basis"], e["held_move"]) == (11, None, dl.HELD, IL5)
    # The set's held list stays beside it, as before.
    assert e["held"] == [IL5]
    # An entry logged before #187 has no basis: the queue says none rather than guess.
    for s in entry["sets"]:
        for m in s["moves"]:
            del m["basis"], m["held"]
    (e,) = qa.queue_of(day_of(entry), date(2026, 10, 26), qa.noise_floor([], 0.1), (0.1, "x"), None)
    assert (e["basis"], e["held_move"]) == (None, None)


# --------------------------------------------------------------------------- the landing (#191)
@pytest.mark.parametrize(
    ("league", "line", "names"),
    [
        ("held", (11, None, dl.HELD, IL5), {"11": "P11", "5": "Hurt"}),
        ("open", (11, None, dl.OPEN, None), {"11": "P11"}),
        ("drop", (11, 2, dl.DROP, None), {"11": "P11", "2": "P2", "5": "Hurt"}),
    ],
)
def test_the_landing_line_carries_the_set_with_each_basis_the_room_and_their_names(
    league, line, names
):
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = {
        "held": lambda: build(
            roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value
        ),
        "open": lambda: build(*streaming_league(), spots=4),
        "drop": lambda: il_full_league([(7, "O")], {}),
    }[league]()
    built = built_of(p)
    out = sm.moves_payload(built)
    b = sm.best_payload(built, out)
    rec = out["recommended"][b["horizon"]]
    assert b["horizon"] == "three" and pairs(rec) == [(m["add"], m["drop"]) for m in b["set"]]
    assert [(m["add"], m["drop"], m["basis"], m["held"]) for m in b["set"]] == [line]
    assert b["set"][0]["gain"] == rec["moves"][0]["marginal"]["three"] == b["move"]["gain"]
    # The room is the payload's; the names cover the held and the waiting players too.
    assert b["room"] == out["room"] and b["names"] == names
