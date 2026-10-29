"""IL churn (#221): an add whose drop is a held player, the room it needs, when it is offered,
the held return it removes, the keep rule on held players, ties going to the season, and how the
payload, the decision log and the queue carry it. Every league here is made up
(``test_moves``'s fixtures); the outcomes are set by construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import season_decisions, season_queue
from pickandroll.api import season_moves as sm
from pickandroll.season import autopilot as qa
from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv

from .test_add_basis import day_of
from .test_moves import WEEKS, il_full_league
from .test_season_guard import built_of

AT = datetime(2026, 10, 26, 12, tzinfo=UTC)
MONDAY = WEEKS[1][0]
#: Past every horizon of the fixtures.
LATE = WEEKS[3][6] + timedelta(days=7)


def churn_league(status="OFS", season=None, **extra):
    """The keep league with its one IL slot taken by player 7 (``status``) and player 5 of mine
    out (O): a churn of 7 moves 5 into the slot 7 leaves."""
    p = il_full_league([(7, status)], season or {7: 0.1})
    return replace(p, **extra)


# --------------------------------------------------------------------------- the room
def test_a_held_drop_frees_its_slot_for_an_eligible_active_player_who_gives_the_add_his_spot():
    p = churn_league()
    churn = [mv.Move(11, 7)]
    assert mv.is_churn(p, churn[0]) and mv.needs_spot(p, churn[0])
    assert mv.freed_by(p, churn) == {"IL": 1}
    assert mv.feasible(p, churn)
    assert mv.held_used(p, churn) == [(5, "IL")]
    # An active player's drop needs no room and no held move.
    assert not mv.needs_spot(p, mv.Move(11, 3)) and mv.held_used(p, [mv.Move(11, 3)]) == []
    # With an active spot open the churn needs no one to move.
    roomy = replace(p, spots=p.spots + 1)
    assert mv.feasible(roomy, churn) and mv.held_used(roomy, churn) == []


def test_a_churn_with_no_one_to_take_the_freed_slot_and_no_open_spot_does_not_fit():
    p = churn_league()
    healthy = replace(p, roster=tuple(m for m in p.roster if m[0] != 5), spots=p.spots - 1)
    assert not mv.feasible(healthy, [mv.Move(11, 7)])
    # Two churns of one held player, or two adds for one freed slot, do not fit either.
    assert not mv.feasible(p, [mv.Move(11, 7), mv.Move(10, 7)])
    assert not mv.feasible(p, [mv.Move(11, 7), mv.Move(10)])


def test_the_drops_on_offer_take_held_players_last_never_a_kept_or_a_cleared_one():
    p = churn_league()
    assert mv.drop_options(p) == [None, 1, 2, 3, 5, 7]
    assert 7 not in mv.drop_options(replace(p, kept=frozenset({7})))
    cleared = il_full_league([(7, None)], {7: 0.1})
    assert mv.cleared(cleared) == [(7, "IL")] and 7 not in mv.drop_options(cleared)


# --------------------------------------------------------------------------- when it is offered
def test_a_churn_for_a_claim_needs_the_held_player_worth_nothing_net_of_his_return():
    # Out for the season: worth nothing net of return, so a claim may come with him.
    p = churn_league("OFS", claims=frozenset({11}))
    assert mv.net_of_return(p, 7, dict(p.held)[7]) == 0.0
    assert mv.churn_ok(p, mv.Move(11, 7)) and mv.feasible(p, [mv.Move(11, 7)])
    # Back next Monday and worth something: only a free agent's add may come with him.
    q = churn_league("O", {7: 0.5}, claims=frozenset({11}))
    assert mv.net_of_return(q, 7, dict(q.held)[7]) > 0
    assert not mv.churn_ok(q, mv.Move(11, 7)) and not mv.feasible(q, [mv.Move(11, 7)])
    assert mv.churn_ok(q, mv.Move(10, 7)) and mv.feasible(q, [mv.Move(10, 7)])
    # No season value to tell: no churn for a claim.
    r = replace(q, season_value={k: v for k, v in q.season_value.items() if k != 7})
    assert not mv.churn_ok(r, mv.Move(11, 7))


def test_a_churn_beats_the_plain_swap_this_week_when_it_keeps_a_playing_drop_on_the_roster():
    p = churn_league()
    ev = mv.Evaluator(p)
    churn, three, five = mv.Move(11, 7), mv.Move(11, 3), mv.Move(11, 5)
    # Dropping 3 for the holder loses 3's games this week; churning 7 (out for the season) and
    # moving 5 (out this week) into the slot keeps them, as dropping 5 does.
    assert ev.value("week", [churn]) > ev.value("week", [three])
    assert ev.value("week", [churn]) == pytest.approx(ev.value("week", [five]))
    # From Monday 5's return sends 3: the churn is worth dropping 3 then, and more than losing 5.
    assert mv.comebacks(p, "three", [churn]) == [mv.Comeback(5, "IL", MONDAY, 3)]
    assert ev.value("three", [churn]) == pytest.approx(ev.value("three", [three]))
    assert ev.value("three", [churn]) > ev.value("three", [five])
    # On each horizon no drop on offer beats it.
    for key in ("week", "three"):
        gains = {g.drop: g.gain for g in mv.single_swaps(ev, key, [11])[11]}
        assert gains[7] == pytest.approx(max(gains.values()))


# --------------------------------------------------------------------------- the held return
def test_a_held_player_coming_back_inside_a_horizon_is_charged_the_drop_his_return_forces():
    p = churn_league("O", {7: 1.0})
    # Back next Monday: nothing this week, the weakest active player then over the three weeks.
    assert mv.comebacks(p, "week", ()) == []
    assert mv.comebacks(p, "three", ()) == [mv.Comeback(7, "IL", MONDAY, 3, returning=True)]
    # The base is the roster with that player gone from Monday: the same as one without him and
    # a spot left open for the return.
    alone = replace(p, roster=tuple(m for m in p.roster if m[0] != 3))
    assert mv.comebacks(alone, "three", ()) == []
    assert mv.Evaluator(p).base["three"] == pytest.approx(mv.Evaluator(alone).base["three"])
    # A churn that drops him removes the charge; 5 moved into his slot is charged instead.
    assert mv.comebacks(p, "three", [mv.Move(10, 7)]) == [mv.Comeback(5, "IL", MONDAY, 3)]
    # A later return date moves the charge to it; past the horizon there is none.
    later = replace(p, returns={7: WEEKS[2][3]})
    assert [c.day for c in mv.comebacks(later, "three", ())] == [WEEKS[2][3]]
    assert mv.comebacks(replace(p, returns={7: LATE}), "three", ()) == []


def test_the_return_never_sends_a_kept_player_while_another_can_go():
    p = churn_league("O", {7: 1.0})
    kept = replace(p, kept=frozenset({3}))
    (c,) = mv.comebacks(kept, "three", ())
    assert c.drop != 3 and c.drop not in kept.kept


# --------------------------------------------------------------------------- the keep rule
def test_the_keep_rule_runs_its_three_tests_on_held_players_apart():
    p = churn_league("O", {7: 3.0})
    rule = mv.keep_rule(p)
    assert set(rule.players) == {1, 2, 3, 5} and set(rule.held) == {7}
    assert rule.held[7].protected and 7 in rule.kept
    # Kept, he is never a churn's drop.
    q = replace(p, kept=rule.kept)
    assert 7 not in mv.drop_options(q)
    # Out for the season he does not return, so the rule never protects him.
    assert not mv.keep_rule(churn_league("OFS", {7: 3.0})).held[7].protected


# --------------------------------------------------------------------------- ties go to the season
def test_a_churn_that_ties_the_plain_swap_on_the_horizon_is_decided_by_the_season():
    # Both out past every horizon: dropping either for the holder is worth the same on both.
    p = churn_league("O", {7: 0.5}, returns={5: LATE, 7: LATE})
    ev = mv.Evaluator(p)
    for key in ("week", "three"):
        assert ev.value(key, [mv.Move(11, 7)]) == pytest.approx(ev.value(key, [mv.Move(11, 5)]))
    # Without a tie-break the active drop comes first; the season takes the one worth less.
    assert mv.search(ev, "three", [11], min_gain=0.01) == (mv.Move(11, 5),)

    def season_of(worth):
        return lambda moves: -sum(worth.get(m.drop, 0.0) for m in moves)

    worth_5, worth_7 = season_of({5: 3.0, 7: 1.0}), season_of({5: 1.0, 7: 3.0})
    assert mv.search(ev, "three", [11], min_gain=0.01, season=worth_5) == (mv.Move(11, 7),)
    assert mv.search(ev, "three", [11], min_gain=0.01, season=worth_7) == (mv.Move(11, 5),)
    rec = mv.recommend(ev, "three", [11], 0.01, season=worth_5)
    (pm,) = rec.moves
    assert pm.move == mv.Move(11, 7) and pm.price_keep == pytest.approx(0.0, abs=1e-9)
    assert sm.decided_by(pm, "three", season_of({})) == dl.SEASON
    assert sm.decided_by(pm, "three", None) == "three"


# --------------------------------------------------------------------------- the season
def test_a_churns_rest_of_season_is_the_held_drop_net_of_his_return_and_the_guard_reads_it():
    gone = churn_league("OFS")
    ros = sm.ros_of(built_of(gone), 11, 7)
    # Out for the season: he gives up no games, so the churn is worth the add alone.
    assert ros is not None and ros["drop_games"] == 0
    assert ros["value"] == pytest.approx(sm.ros_of(built_of(gone), 11, None)["value"])
    # Back next Monday, the games he gives up start then: the guard sees the whole cost.
    back = churn_league("O", {7: 0.5})
    ros = sm.ros_of(built_of(back), 11, 7)
    assert ros["drop_games"] > 0 and ros["value"] < sm.ros_of(built_of(back), 11, None)["value"]
    guard = mv.season_guard(sm.guard_ros(built_of(back)))
    assert guard([mv.Move(11, 7)]) == (ros["value"] >= 0)


# --------------------------------------------------------------------------- the payload and the log
def test_the_payload_logs_and_queues_a_churn_with_its_held_drop_and_holds_it_read_only():
    p = churn_league()
    rule = mv.keep_rule(p)
    p = replace(p, kept=rule.kept)
    built = built_of(p, rule=rule)
    out = sm.moves_payload(built)
    week = out["recommended"]["week"]
    churn = next(m for m in week["moves"] if m["drop"] == 7)
    assert churn["held_drop"] == {"player": 7, "slot": "IL"}
    assert churn["held"] == {"player": 5, "slot": "IL"}
    assert churn["decided_by"] in ("week", dl.SEASON)
    assert out["candidates"]["11"]["week"]["held_drop"] == {"player": 7, "slot": "IL"}
    # The keep rule lists the held players apart; the IL advice names the churn of its occupant.
    assert [x["player"] for x in out["keep_rule"]["held"]] == [7]
    assert [x["player"] for x in out["keep_rule"]["players"]] == [1, 2, 3, 5]
    (stash,) = out["stash"]
    assert stash["advice"] == mv.IL_FULL and stash["leave"]["player"] == 7
    assert stash["churn"] is not None and stash["churn"] == sm.churn_of(out["recommended"], 7)
    # The decision log records the basis and both held fields.
    entry = season_decisions.moves_entry(built, out, AT)
    logged = next(s for s in entry["sets"] if s["key"] == "week")
    m = next(m for m in logged["moves"] if m["drop"] == 7)
    assert (m["basis"], m["held"], m["held_drop"]) == (
        dl.CHURN,
        {"player": 5, "slot": "IL"},
        {"player": 7, "slot": "IL"},
    )
    assert dl.basis_of(7, None, churn=True) == dl.CHURN and dl.basis_of(7, None) == dl.DROP


def test_the_queue_never_queues_a_churn_until_the_executor_drops_on_its_own():
    p = churn_league()
    rule = mv.keep_rule(p)
    p = replace(p, kept=rule.kept)
    built = built_of(p, rule=rule)
    entry = season_decisions.moves_entry(built, sm.moves_payload(built), AT)
    three = next(s for s in entry["sets"] if s["key"] == "three")
    three["moves"] = [
        {**m, "basis": dl.CHURN, "held_drop": {"player": 7, "slot": "IL"}} for m in three["moves"]
    ][:1]
    (e,) = qa.queue_of(day_of(entry), date(2026, 10, 26), qa.noise_floor([], 0.1), (0.1, "x"), None)
    assert (e["queued"], e["reason"]) == (False, qa.CHURN_HELD)
    assert e["held_drop"] == {"player": 7, "slot": "IL"}


def test_a_protected_held_player_is_named_protected_for_the_queue():
    rule = mv.keep_rule(churn_league("O", {7: 3.0}))
    assert 7 in season_queue.protected_of(rule)
