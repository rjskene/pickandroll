"""Week plans (#221 part 2): dated sequences of moves over the rest of this week, the rules a
plan keeps, its steps' increments, the roster's own changes on their day, plan 1 and the plan the
queue takes. Every league here is made up (``test_moves``'s fixtures); the outcomes are set by
construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pickandroll.api import season_decisions
from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import moves as mv
from pickandroll.season import plans as pl
from pickandroll.season import weekly as wk

from .test_moves import WEEKS, build, il_full_league, player, rates, streaming_league
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
        # Each step waits on earlier steps only, those it does not stand without (#364).
        assert all(set(s["after"]) <= set(range(i)) for i, s in enumerate(w["steps"]))
        assert sum(s["gain"]["week"] for s in w["steps"]) == pytest.approx(
            w["total"]["week"], abs=1e-2
        )
        assert all(s["basis"] in ("open", "held", "drop", "churn") for s in w["steps"])
    # A later step with its own room and worth waits on nothing: placed the night it is due.
    assert any(not s["after"] for w in wp["plans"] for s in w["steps"][1:])
    churns = [s for w in wp["plans"] for s in w["steps"] if s["basis"] == "churn"]
    assert churns and all(s["held_drop"]["player"] == 7 for s in churns)
    # The stream's chains join the pool: a plan with a churn and a step dated after the first day.
    assert any(
        any(s["basis"] == "churn" for s in w["steps"])
        and any(s["from"] > FIRST.isoformat() for s in w["steps"])
        for w in wp["plans"]
    )
    assert wp["queue"] is None or 0 <= wp["queue"] < len(wp["plans"])


# --------------------------------------------------------------------------- the master's nits
def test_a_plan_the_rules_refuse_never_takes_the_queue_even_plan_one():
    # The week's set may take more moves a day than the cap: shown as plan 1, never queued.
    p = replace(full_league(), plan_floor=-1.0)
    moves = [mv.Move(10, 7), mv.Move(11, 3)]
    capped = replace(p, daily_cap=1)
    for problem, queued in ((p, True), (capped, False)):
        ev = mv.Evaluator(problem)
        w = pl.valued(ev, moves, pl.SET)
        assert pl.valid(problem, w.moves) is queued
        assert (pl.for_queue(ev, [w], []) is w) is queued


def test_plans_with_the_same_adds_and_days_are_one_the_best_week_kept():
    p = full_league()
    ev, swaps, week_set = solved(p)
    plans = pl.week_plans(ev, week_set, swaps)
    keys = [pl.key_of(p, w.moves) for w in plans]
    assert len(keys) == len(set(keys))
    # The search finds plans that differ by a drop only; each kept one is the best week of its kind.
    raw = [pl.valued(ev, m, pl.SEARCH) for m in pl.search(ev, pl.blocks(p, swaps))]
    best: dict = {}
    for w in raw:
        k = pl.key_of(p, w.moves)
        best[k] = max(best.get(k, -99.0), w.total["week"])
    assert len(best) < len(raw)
    for w in plans:
        if w.source == pl.SEARCH:
            assert w.total["week"] == pytest.approx(best[pl.key_of(p, w.moves)])


# --------------------------------------------------------------------------- the queue's choice
class Priced:
    """An evaluator with the gains set by hand, and each set's matchup odds, one category's."""

    def __init__(self, problem, gains, odds=None):
        self.problem = problem
        self.gains = {frozenset(k): v for k, v in gains.items()}
        self.odds_of = {frozenset(k): v for k, v in (odds or {}).items()}

    def gain(self, key, moves):
        # A set not priced costs everything, so none of its steps comes out by accident.
        if not moves:
            return 0.0
        return self.gains.get(frozenset(moves), (-99.0, -99.0))[0 if key == "week" else 1]

    value = gain

    def odds(self, key, moves):
        p_win = self.odds_of.get(frozenset(moves))
        if p_win is None:
            return [[]]
        return [[[wk.CategoryOdds("PTS", None, None, 1.0, p_win)]]]


def choice(p, *moves):
    return pl.WeekPlan(pl.SEARCH, tuple(pl.Step(m, FIRST, {}) for m in moves), (), {})


A, B, C = mv.Move(10, 7), mv.Move(11, 3), mv.Move(12, 2)


def test_a_plan_that_costs_the_three_weeks_but_wins_on_score_leads():
    p = replace(full_league(), plan_floor=0.1)
    # The set: 0.1 + 0.33 x 0.6 = 0.298. The plan: 0.8 + 0.33 x -0.2 = 0.734.
    ev = Priced(p, {(C,): (0.1, 0.6), (A, B): (0.8, -0.2)})
    w = choice(p, A, B)
    assert pl.for_queue(ev, [w], [C]) is w
    assert pl.score(ev, [A, B], 0.33) == pytest.approx(0.734)
    # At a weight that counts the three weeks in full the set holds.
    assert pl.for_queue(ev, [w], [C], weight=1.0) is None


def test_a_plan_under_the_floor_does_not_lead_and_the_best_score_does():
    p = replace(full_league(), plan_floor=0.1)
    ev = Priced(p, {(C,): (0.3, 0.0), (A,): (0.39, 0.0), (B,): (0.45, 0.0), (A, B): (0.6, 0.0)})
    assert pl.for_queue(ev, [choice(p, A)], [C]) is None
    assert pl.for_queue(ev, [choice(p, B)], [C]) is not None
    two = choice(p, A, B)
    assert pl.for_queue(ev, [choice(p, A), choice(p, B), two], [C]) is two


def test_a_plan_the_season_guard_or_the_rules_refuse_never_leads():
    p = replace(full_league(), plan_floor=0.0)
    ev = Priced(p, {(): (0.0, 0.0), (A, B): (1.0, 1.0)})
    w = choice(p, A, B)
    assert pl.for_queue(ev, [w], []) is w
    assert pl.for_queue(ev, [w], [], allowed=lambda moves: False) is None
    capped = Priced(replace(p, daily_cap=1), {(): (0.0, 0.0), (A, B): (1.0, 1.0)})
    assert pl.for_queue(capped, [w], []) is None


def test_a_playoff_week_chooses_on_the_matchup_odds_by_three_points():
    p = full_league()
    gains = {(C,): (0.9, 0.9), (A,): (0.0, -1.0), (B,): (0.0, 0.0)}
    odds = {(C,): 0.50, (A,): 0.54, (B,): 0.52}
    ev = Priced(p, gains, odds)
    a, b = choice(p, A), choice(p, B)
    # The score favours the set everywhere; the odds pick the plan and the three weeks don't count.
    assert pl.for_queue(ev, [a, b], [C]) is None
    assert pl.for_queue(ev, [a, b], [C], weight=0.0, playoff=True) is a
    assert pl.for_queue(ev, [b], [C], weight=0.0, playoff=True) is None
    assert pl.gate(ev, [A], 0.0, True) == pytest.approx(0.54)
    assert pl.gate_floor(p, True) == pl.PLAYOFF_FLOOR == 0.03


def test_a_playoff_week_with_no_opponent_read_leaves_the_three_weeks_set():
    p = full_league()
    ev = Priced(p, {(C,): (0.0, 0.0), (A,): (9.0, 9.0)})
    assert pl.matchup(ev, [C]) is None
    assert pl.for_queue(ev, [choice(p, A)], [C], weight=0.0, playoff=True) is None


def test_the_three_weeks_sets_moves_join_the_pool_whatever_they_gain_this_week():
    p = full_league()
    _, swaps, _ = solved(p)
    lasting = mv.Move(11, 2, WEEKS[0][3])
    assert (lasting,) not in pl.blocks(p, swaps)
    assert pl.blocks(p, swaps, three_set=[lasting])[-1] == (lasting,)


def test_the_beam_weighs_the_three_weeks_as_the_score_does(monkeypatch):
    p = replace(full_league(), plan_floor=0.0)
    # Two moves on one add: a plan takes one. The week picks the first, the score the second.
    quick, lasting = mv.Move(10, 7), mv.Move(10, 3)
    ev = Priced(p, {(quick,): (0.5, -1.0), (lasting,): (0.1, 2.0)})
    monkeypatch.setattr(pl, "EXACT", 1)
    pool = [(quick,), (lasting,)]
    assert pl.search(ev, pool) == [(quick,)]
    assert pl.search(ev, pool, weight=0.33) == [(lasting,)]


def test_a_step_scores_its_increments_and_the_shown_plans_keep_the_choice():
    step = pl.Step(A, FIRST, {"week": 0.4, "three": -0.3})
    assert pl.step_score(step, 0.33) == pytest.approx(0.301)
    assert pl.step_score(step, 0.0) == pytest.approx(0.4)
    plans = [
        pl.WeekPlan(pl.SEARCH, (pl.Step(mv.Move(20 + i, 7), FIRST, {}),), (), {"week": float(i)})
        for i in range(7)
    ]
    assert pl.shown(plans, None) == plans[:5]
    assert pl.shown(plans, plans[2]) == plans[:5]
    assert pl.shown(plans, plans[6]) == [*plans[:4], plans[6]]


def test_the_payload_gives_each_plans_score_and_odds_and_what_the_choice_was_made_on():
    p = full_league()
    out = sm.moves_payload(built_of(p, rule=mv.keep_rule(p)))["week_plans"]
    assert out["judged"]["weight"] == pl.THREE_WEIGHT and out["judged"]["playoff"] is False
    assert out["judged"]["floor"] == out["floor"]
    assert set(out["judged"]["set"]) == {"score", "matchup"}
    for w in out["plans"]:
        assert w["score"] == pytest.approx(
            w["total"]["week"] + pl.THREE_WEIGHT * w["total"]["three"], abs=1e-2
        )
        assert sum(s["score"] for s in w["steps"]) == pytest.approx(w["score"], abs=1e-2)


def test_the_payload_of_a_playoff_week_scores_on_the_odds():
    p = full_league()
    out = sm.moves_payload(built_of(p, rule=mv.keep_rule(p), playoff=True))["week_plans"]
    assert out["judged"]["playoff"] is True and out["judged"]["floor"] == pl.PLAYOFF_FLOOR
    for w in out["plans"]:
        assert w["score"] == pytest.approx(w["matchup"], abs=1e-3)
        for s in w["steps"]:
            assert s["score"] == pytest.approx(s["gain"]["week"], abs=1e-3)


def test_the_pool_takes_the_unguarded_chain_until_the_budget_is_out(monkeypatch):
    p = full_league()
    built = built_of(p, rule=mv.keep_rule(p))
    seen = []
    real = sm.stream_of

    def stream_of(built, ev, against, allowed=None, guard=True):
        seen.append(guard)
        return real(built, ev, against, allowed, guard)

    monkeypatch.setattr(sm, "stream_of", stream_of)
    sm.moves_payload(built)
    assert seen == [True, False]
    seen.clear()
    spent = mv.Budget.start(None)
    spent.spent = True
    sm.moves_payload(built, spent)
    assert seen == [True]


def test_the_best_line_shows_the_queues_plan_first():
    p = full_league()
    built = built_of(replace(p, plan_floor=-9.0), rule=mv.keep_rule(p))
    payload = sm.moves_payload(built)
    wp = payload["week_plans"]
    assert wp["queue"] is not None
    chosen = wp["plans"][wp["queue"]]
    out = sm.best_payload(built, payload)
    assert out["horizon"] == "week" and out["moves"] == len(chosen["steps"])
    assert out["gain"] == chosen["total"]["week"]
    assert [x["add"] for x in out["set"]] == [s["add"] for s in chosen["steps"]]
    assert out["plan"] == {
        "matchup": chosen["matchup"],
        "against": wp["judged"]["set"]["matchup"],
        "three": chosen["total"]["three"],
        "ros": chosen["ros"],
    }


def test_the_best_line_shows_the_three_weeks_set_when_no_plan_leads():
    p = full_league()
    built = built_of(replace(p, plan_floor=99.0), rule=mv.keep_rule(p))
    payload = sm.moves_payload(built)
    assert payload["week_plans"]["queue"] is None
    assert sm.best_payload(built, payload)["plan"] is None


# --------------------------------------------------------------------------- the trim
def wide_league():
    """The keep league with two more candidates and no daily cap to speak of."""
    p = replace(full_league(), plan_floor=0.1, daily_cap=4)
    more = (12, 13)
    return replace(
        p,
        candidates=(*p.candidates, *(player(k, "STR") for k in more)),
        effective={**p.effective, **dict.fromkeys(more, FIRST)},
    )


def test_a_step_that_gives_the_plan_nothing_comes_out_lowest_first():
    p = replace(full_league(), plan_floor=0.1)
    gains = {(A, B): (1.0, 0.0), (B,): (0.99, 0.0), (A,): (0.98, 0.0)}
    got = pl.trimmed(Priced(p, gains), choice(p, A, B), weight=0.0)
    # Both would pass; A costs the least, and a plan keeps a step.
    assert got.moves == (B,)
    # The trimmed plan is valued again, so its steps and total are what executes.
    assert got.total["week"] == pytest.approx(0.99)
    assert [s.gain["week"] for s in got.steps] == [pytest.approx(0.99)]


def test_a_four_step_plan_loses_its_idle_step_and_keeps_its_chain():
    # A league's real shape: a stream through one spot, each step dropping the last one's add, and
    # a step of its own. The chain's first steps gain almost nothing, yet cannot come out alone.
    p = wide_league()
    day = WEEKS[0]
    first = mv.Move(10, 7, day[0])
    second = mv.Move(11, 10, day[1])
    third = mv.Move(12, 11, day[2])
    idle = mv.Move(13, 3, day[2])
    full = (first, second, third, idle)
    assert pl.valid(p, full)
    assert not pl.valid(p, (second, third, idle)) and not pl.valid(p, (first, third, idle))
    gains = {
        full: (0.5, 0.0),
        (first, second, third): (0.49, 0.0),  # without the idle step: costs 0.01
        (first, second, idle): (0.1, 0.0),  # without the chain's end: costs 0.4
        (first, second): (0.0, 0.0),
        (first,): (0.0, 0.0),
    }
    got = pl.trimmed(Priced(p, gains), choice(p, *full), weight=0.0)
    assert set(got.moves) == {first, second, third}


def test_the_trim_goes_on_the_plans_cost_not_the_steps_increment():
    p = replace(full_league(), plan_floor=0.1)
    # A's increment is nil as the first step priced, but the plan without it loses 0.3.
    ev = Priced(p, {(A,): (0.0, 0.0), (A, B): (0.5, 0.0), (B,): (0.2, 0.0)})
    w = choice(p, A, B)
    assert pl.trimmed(ev, w, weight=0.0) is w


def test_a_plan_keeps_a_step_over_half_the_floor_and_at_least_one_step():
    p = replace(full_league(), plan_floor=0.1)
    w = choice(p, A, B)
    at_margin = Priced(p, {(A, B): (0.5, 0.0), (A,): (0.44, 0.0), (B,): (0.44, 0.0)})
    assert pl.trimmed(at_margin, w, weight=0.0) is w
    lone = choice(p, A)
    assert pl.trimmed(Priced(p, {(A,): (0.0, 0.0)}), lone, weight=0.0) is lone


def test_a_chain_step_a_later_step_drops_stays():
    p = replace(full_league(), plan_floor=0.1)
    first, second = mv.Move(10, 7, WEEKS[0][0]), mv.Move(11, 10, WEEKS[0][1])
    # The stream's chain: the second step drops the first's add. The first gives nothing, but the
    # plan without it would drop a player it does not hold.
    assert pl.valid(p, [first, second]) and not pl.valid(p, [second])
    ev = Priced(p, {(first, second): (0.5, 0.0), (second,): (0.5, 0.0), (first,): (0.1, 0.0)})
    w = choice(p, first, second)
    assert pl.trimmed(ev, w, weight=0.0) is w


def test_a_step_the_season_guard_needs_stays():
    p = replace(full_league(), plan_floor=0.1)
    ev = Priced(p, {(A, B): (0.5, 0.0), (B,): (0.5, 0.0), (A,): (0.1, 0.0)})
    w = choice(p, A, B)
    assert pl.trimmed(ev, w, weight=0.0, allowed=lambda moves: A in moves) is w


def test_a_trimmed_plan_faces_the_set_again():
    p = replace(full_league(), plan_floor=0.1)
    # The set 0.1; the line 0.2. The plan at 0.22 clears it, without its idle step at 0.18 it does
    # not, so the queue takes the set.
    gains = {(C,): (0.1, 0.0), (A, B): (0.22, 0.0), (A,): (0.18, 0.0), (B,): (0.01, 0.0)}
    assert pl.for_queue(Priced(p, gains), [choice(p, A, B)], [C], weight=0.0) is None
    # Clear of the line once trimmed, the trimmed plan leads.
    gains[(A, B)], gains[(A,)] = (0.5, 0.0), (0.48, 0.0)
    got = pl.for_queue(Priced(p, gains), [choice(p, A, B)], [C], weight=0.0)
    assert got.moves == (A,)


def test_a_playoff_week_trims_on_half_the_odds_floor():
    p = replace(full_league(), plan_floor=0.1)
    odds = {(C,): 0.5, (A, B): 0.6, (B,): 0.59, (A,): 0.4}
    ev = Priced(p, {}, odds)
    got = pl.for_queue(ev, [choice(p, A, B)], [C], weight=0.0, playoff=True)
    assert got.moves == (B,)
    # At two points the step is worth more than half the three-point floor.
    ev = Priced(p, {}, {**odds, (B,): 0.58})
    w = choice(p, A, B)
    assert pl.for_queue(ev, [w], [C], weight=0.0, playoff=True) is w


def test_the_card_keeps_the_searched_plan_and_the_queue_points_at_the_trimmed_one():
    p = replace(full_league(), plan_floor=0.1)
    searched, trim = choice(p, A, B), choice(p, A)
    assert pl.shown([searched], trim) == [searched, trim]
    assert pl.place(pl.shown([searched], trim), trim) == 1
    # A plan already listed with the trimmed moves stands for it.
    other = pl.WeekPlan(pl.SET, trim.steps, (), {"week": 1.0})
    assert pl.shown([searched, other], trim) == [searched, other]
    assert pl.place([searched, other], trim) == 1
    assert pl.place([searched], trim) is None
    # Five plans listed: it takes the last place.
    five = [choice(p, mv.Move(20 + i, 7)) for i in range(5)]
    assert pl.shown(five, trim) == [*five[:4], trim]


def test_the_queue_and_the_log_carry_the_trimmed_plan_and_the_card_the_searched_one(monkeypatch):
    def first_step(ev, plan, weight, playoff, allowed, out):
        return pl.valued(ev, plan.moves[:1], plan.source, out)

    monkeypatch.setattr(pl, "trimmed", first_step)
    p = full_league()
    built = built_of(replace(p, plan_floor=-9.0), rule=mv.keep_rule(p))
    payload = sm.moves_payload(built)
    wp = payload["week_plans"]
    chosen = wp["plans"][wp["queue"]]
    assert len(chosen["steps"]) == 1
    assert any(len(w["steps"]) > 1 for w in wp["plans"])
    entry = season_decisions.moves_entry(built, payload, datetime(2026, 10, 26, 12, tzinfo=UTC))
    logged = next(s for s in entry["sets"] if s["key"] == pl.QUEUE_PLAN)
    assert [m["add"] for m in logged["moves"]] == [s["add"] for s in chosen["steps"]]
    assert sm.best_payload(built, payload)["moves"] == 1
