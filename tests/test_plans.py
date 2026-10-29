"""Week plans (#221 part 2): dated sequences of moves over the rest of this week, the rules a
plan keeps, its steps' increments, the roster's own changes on their day, plan 1 and the plan the
queue takes. Every league here is made up (``test_moves``'s fixtures); the outcomes are set by
construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import moves as mv
from pickandroll.season import plans as pl

from .test_moves import WEEKS, build, il_full_league, rates, streaming_league
from .test_season_guard import built_of

FIRST = WEEKS[0][0]


def full_league():
    """The IL-full keep league (player 7 out for the season in the IL, 5 out this week), kept."""
    p = il_full_league([(7, "OFS")], {7: 0.1})
    return replace(p, kept=mv.keep_rule(p).kept)


def solved(p):
    ev = mv.Evaluator(p)
    swaps = mv.single_swaps(ev, "week")
    ranked = sorted((c for c, g in swaps.items() if g), key=lambda c: -swaps[c][0].gain)
    week_set = [pm.move for pm in mv.recommend(ev, "week", ranked, min_gain=0.01).moves]
    return ev, swaps, week_set


# --------------------------------------------------------------------------- the rules
def test_a_plan_keeps_the_steps_the_week_the_daily_cap_and_its_drops_on_the_roster():
    p = full_league()
    assert pl.valid(p, [mv.Move(10, 7), mv.Move(11, 3)])
    # More than four steps, a day outside the week, or more moves a day than the cap.
    five = [mv.Move(10 + i, d, FIRST + timedelta(i)) for i, d in enumerate((1, 2, 3, 5, 7))]
    assert not pl.valid(replace(p, candidates=p.candidates * 1), five)
    assert not pl.valid(p, [mv.Move(11, 3, WEEKS[1][0])])
    capped = replace(p, daily_cap=1)
    assert not pl.valid(capped, [mv.Move(10, 7), mv.Move(11, 3)])
    assert pl.valid(capped, [mv.Move(10, 7), mv.Move(11, 3, WEEKS[0][2])])
    # A drop of an add the plan does not make, or makes later, is refused; earlier is a stream step.
    assert not pl.valid(p, [mv.Move(11, 10, WEEKS[0][2])])
    assert not pl.valid(p, [mv.Move(11, 10, WEEKS[0][2]), mv.Move(10, 3, WEEKS[0][4])])
    assert pl.valid(p, [mv.Move(10, 3, WEEKS[0][1]), mv.Move(11, 10, WEEKS[0][4])])
    # Nobody added twice, and feasible's room.
    assert not pl.valid(p, [mv.Move(10, 3), mv.Move(10, 2, WEEKS[0][3])])
    assert not pl.valid(p, [mv.Move(10), mv.Move(11, 3)])


def test_the_pool_takes_the_weeks_best_single_moves_and_each_stream_chain_whole():
    p = full_league()
    _, swaps, _ = solved(p)
    pool = pl.blocks(p, swaps)
    assert all(len(b) == 1 for b in pool) and len(pool) == len(set(pool))
    best = max(swaps, key=lambda c: swaps[c][0].gain if swaps[c] else -1)
    assert pool[0] == (mv.Move(best, swaps[best][0].drop),)
    chain = (mv.Move(10, 3, WEEKS[0][1]), mv.Move(11, 10, WEEKS[0][4]))

    class Spot:
        steps = chain

    class Stream:
        spots = (Spot,)

    assert pl.blocks(p, swaps, Stream)[-1] == chain


# --------------------------------------------------------------------------- the values
def test_each_steps_increment_is_the_plan_up_to_it_less_before_and_they_sum_to_the_total():
    p = full_league()
    ev, swaps, week_set = solved(p)
    plans = pl.week_plans(ev, week_set, swaps)
    assert plans and len(plans) <= pl.WEEK_PLANS
    for w in plans:
        days = [s.day for s in w.steps]
        assert days == sorted(days)
        for h in p.horizons:
            assert sum(s.gain[h] for s in w.steps) == pytest.approx(w.total[h])
            assert w.total[h] == pytest.approx(ev.gain(h, w.moves))
        done: list[mv.Move] = []
        for s in w.steps:
            before = ev.value("week", done)
            done.append(s.move)
            assert s.gain["week"] == pytest.approx(ev.value("week", done) - before)
    # Distinct by move set, every one inside the rules.
    keys = [pl.key_of(p, w.moves) for w in plans]
    assert len(keys) == len(set(keys))
    assert all(pl.valid(p, w.moves) for w in plans if w.source == pl.SEARCH)


def test_plan_one_is_the_week_set_unless_a_plan_beats_its_week_by_the_floor():
    p = full_league()
    _, swaps, week_set = solved(p)
    high = pl.week_plans(mv.Evaluator(replace(p, plan_floor=99.0)), week_set, swaps)
    assert high[0].source == pl.SET and pl.key_of(p, high[0].moves) == pl.key_of(p, week_set)
    low = replace(p, plan_floor=0.0)
    plans = pl.week_plans(mv.Evaluator(low), week_set, swaps)
    best = max(plans, key=lambda w: w.total["week"])
    set_ = next(w for w in plans if w.source == pl.SET)
    if best.total["week"] > set_.total["week"] + mv.EPS:
        assert plans[0] is best and plans[0].source == pl.SEARCH
    # A churn is a step like any other.
    assert any(mv.is_churn(p, s.move) for w in plans for s in w.steps)


def test_the_season_guard_holds_every_searched_plan():
    p = full_league()
    ev, swaps, _ = solved(p)
    refused = mv.Move(10, 7)

    def allowed(moves):
        return refused not in moves

    plans = pl.week_plans(ev, [], swaps, allowed=allowed)
    assert all(refused not in w.moves for w in plans if w.source == pl.SEARCH)


# --------------------------------------------------------------------------- the roster's changes
def test_a_held_return_inside_the_week_is_a_zero_choice_step_with_its_own_increment():
    roster, cands, rate, sched, opponent, field = streaming_league()
    back = (7, Player(7, "Back", "MIN", ("C",), status="GTD"))
    p = build(
        roster,
        cands,
        rate | {7: rates(1.0)},
        sched,
        opponent,
        field,
        held=[back],
        held_slots={7: "IL+"},
        returns={7: WEEKS[0][3]},
        value={k: 1.0 for k in rate} | {1: 1.2, 3: 0.1, 7: 1.0},
    )
    assert mv.comebacks(p, "week", ()) == [mv.Comeback(7, "IL+", WEEKS[0][3], 3, returning=True)]
    ev, _, week_set = solved(p)
    out = pl.held_out(ev)
    w = pl.valued(ev, week_set, pl.SET, out)
    (b,) = [b for b in w.backs if b.player == 7]
    assert (b.day, b.returning) == (WEEKS[0][3], True)
    assert b.gain["week"] == pytest.approx(ev.value("week", w.moves) - out(7, "week", w.moves))
    # Never summed in the total.
    assert w.total["week"] == pytest.approx(ev.gain("week", w.moves))


# --------------------------------------------------------------------------- the queue's plan
def test_the_queue_takes_a_plan_only_when_it_beats_the_three_weeks_set_by_the_floor():
    p = full_league()
    ev, swaps, week_set = solved(p)
    plans = pl.week_plans(ev, week_set, swaps)
    best = max(plans, key=lambda w: ev.value("three", w.moves))
    assert pl.for_queue(ev, plans, []) is best
    assert pl.for_queue(ev, plans, best.moves) is None
    assert pl.for_queue(mv.Evaluator(replace(p, plan_floor=99.0)), plans, []) is None


# --------------------------------------------------------------------------- the payload
def test_the_payload_lists_each_plans_steps_their_waits_the_queue_and_the_seconds():
    p = full_league()
    out = sm.moves_payload(built_of(p, rule=mv.keep_rule(p)))
    wp = out["week_plans"]
    assert wp["limits"] == {"plans": 5, "steps": 4, "beam": 8, "exact": 8}
    assert wp["seconds"] >= 0 and out["search"]["seconds"] >= wp["seconds"]
    for w in wp["plans"]:
        assert [s["after"] for s in w["steps"]] == [list(range(i)) for i in range(len(w["steps"]))]
        assert sum(s["gain"]["week"] for s in w["steps"]) == pytest.approx(
            w["total"]["week"], abs=1e-2
        )
        assert all(s["basis"] in ("open", "held", "drop", "churn") for s in w["steps"])
    churns = [s for w in wp["plans"] for s in w["steps"] if s["basis"] == "churn"]
    assert churns and all(s["held_drop"]["player"] == 7 for s in churns)
    # The stream's chains join the pool: a plan with a churn and a step dated after the first day.
    assert any(
        any(s["basis"] == "churn" for s in w["steps"])
        and any(s["from"] > FIRST.isoformat() for s in w["steps"])
        for w in wp["plans"]
    )
    assert wp["queue"] is None or 0 <= wp["queue"] < len(wp["plans"])
