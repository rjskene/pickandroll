"""The queue's rule (#172, PR E): an exact arm that executes ``queue`` takes the week plan the
engine's ``plans.for_queue`` takes instead of the three weeks' set, else the set.

The plans, the gate, the floor and the trim are the engine's, called through the door; what is
the simulator's is the order of the calls and what they are given (``policy.draw_queue``), the
decision made of the answer (``policy.queue_rule``), the executor queueing a leading plan's steps
due today (``policy.queue``), the steps' bids, the refusals and the counts. The parity cases are
problems, not seasons; a season is played only where a season is the point.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, pl, st, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import initial
from tests.sim import test_sim_split as split
from tests.sim.sim_league import KNOBS, arm, every_category, make_setup, recorded_lines
from tests.sim.test_no_peek import recorded
from tests.sim.test_sim_knobs import flip_setup, points_setup, weakened

DAY = timedelta(1)
FORMATS = (ONE_WIN, EACH_CATEGORY)


def built_on(setup, team: int = 1, day: int = 0, status=None, returns=None, **knobs):
    """``team``'s problem ``day`` days into the made-up season, on the day-one rosters. The
    cap is three a day unless the case says otherwise, so a plan may take several steps a day."""
    today = replace(initial(setup), day=setup.start + day * DAY)
    knobs = {**KNOBS, "daily_cap": 3, **knobs}
    return policy.problem_of(
        setup, today, team, knobs, setup.projection, status or {}, returns or {}
    )


def cats():
    """The made-up league of three weeks, the last the bracket's: one win per matchup."""
    return make_setup(seed=3, weeks=3, playoff_weeks=1)


def bracketed(setup):
    """``setup`` with the bracket week's matchups named, as no simulated season names them (a
    replay's bracket is decided at the season's end): a problem of that week then reads an
    opponent, so the engine's odds branch is really entered."""
    last = max(w.number for w in setup.calendar.weeks)
    return replace(setup, pairings={**setup.pairings, last: ((1, 2), (3, 4))})


def returning():
    """Seat 1 with a full active roster and a player in IL+ who is a game-time decision due back
    in two days: the one held status the engine brings back inside the week, so every plan
    lists his return and what it is worth (``plans.held_out``)."""
    setup = make_setup(seed=3, weeks=3, playoff_weeks=1, held_slots=("IL+",))
    pool = sorted(initial(setup).pool)
    held, extra = pool[0], pool[1]
    rosters = {**setup.rosters, 1: (*setup.rosters[1], (extra, "BN"), (held, "IL+"))}
    setup = replace(
        setup, rosters=rosters, pool=tuple(k for k in setup.pool if k not in (held, extra))
    )
    return setup, {held: "GTD"}, {held: setup.start + 2 * DAY}


# --------------------------------------------------------------------------- the arm's choice
def spec(**more) -> dict:
    return {"name": "Q", "tier": "exact", "knobs": dict(KNOBS), "executes": "queue", **more}


def test_queue_is_a_third_choice_of_executes_and_three_stays_the_default():
    assert policy.EXECUTES == ("three", "weighted", "queue") and policy.QUEUE == "queue"
    assert rn.arm_of({"name": "T", "tier": "exact", "knobs": dict(KNOBS)}).executes == "three"
    q = rn.arm_of(spec())
    assert (q.tier, q.executes) == ("exact", policy.QUEUE)
    # The seat it puts in a room takes the rule the same way: a rival that plans with the
    # engine is such a seat.
    assert q.seat().executes == policy.QUEUE and q.seat().tier == "exact"


@pytest.mark.parametrize("tier", ["surrogate", "ranking", "static"])
def test_queue_on_another_tier_is_refused_by_name(tier):
    words = f"executes 'queue' is the exact tier's: the {tier} tier draws no week plan"
    with pytest.raises(ValueError, match=words):
        rn.arm_of(spec(tier=tier))
    assert policy.queue_refused(tier, policy.QUEUE).startswith(words)
    assert policy.queue_refused(tier, policy.QUEUE_SET) is None
    assert policy.queue_refused("exact", policy.QUEUE) is None
    if tier != "static":
        with pytest.raises(ValueError, match=words):
            policy.decide(built_on(make_setup()), tier, policy.QUEUE)


@pytest.mark.parametrize("key", rn.PLAN_KEYS)
@pytest.mark.parametrize("value", [True, False])
def test_a_plan_switch_named_beside_queue_is_refused_whatever_it_says(key, value):
    """The rule draws and executes its own plan: a spec that names a switch beside it is asking
    for something the arm cannot do, so it is refused, not ignored."""
    with pytest.raises(ValueError, match=f"{key} is named beside executes 'queue'"):
        rn.arm_of(spec(**{key: value}))
    # Beside another choice the switch is the arm's as before.
    assert getattr(rn.arm_of(spec(executes="three", **{key: value})), key) is value


# --------------------------------------------------------------------------- the weight
def test_the_weight_is_the_arm_s_three_weight_and_zero_in_a_bracket_week():
    """As the live route sets it: the knob in the regular season, 0 in a week of the bracket,
    where the matchup decides who advances; a league whose bracket is not read has no such week."""
    setup = make_setup(weeks=3, playoff_weeks=1)
    for knob in (0.0, 0.33, 0.9):
        regular = built_on(setup, three_weight=knob)
        assert not policy.in_bracket(regular) and policy.queue_weight(regular) == knob
        last = built_on(setup, day=14, three_weight=knob)
        assert policy.in_bracket(last) and policy.queue_weight(last) == 0.0
    unread = make_setup(weeks=3, playoff_weeks=1, bracket=False)
    late = built_on(unread, day=14, three_weight=0.9)
    assert not policy.in_bracket(late) and policy.queue_weight(late) == 0.9


# --------------------------------------------------------------------------- the executor
def leading(setup):
    """A decision by hand: a set of one move, and a plan of two steps that leads, the first due
    tomorrow and the second three days on."""
    state = initial(setup)
    pool, roster = sorted(state.pool), state.active(1)
    tomorrow = state.day + DAY
    in_set = mv.Move(pool[0], roster[0])
    first = mv.Move(pool[1], roster[1], tomorrow)
    later = mv.Move(pool[2], roster[2], tomorrow + 2 * DAY)
    decision = policy.Decision((in_set,), (), (first, later), 3, "exact", None, True)
    return state, decision, in_set, first, later


def test_a_plan_that_leads_is_queued_instead_of_the_set_and_a_later_step_not_early():
    setup = make_setup()
    state, decision, in_set, first, later = leading(setup)
    queued = policy.queue(state, 1, decision, 3, 4)
    # The step due tomorrow, without its day; neither the set's move nor the later step.
    assert queued.pending[1] == (mv.Move(first.add, first.drop),)
    # The arm's execute_plan is not asked: the rule executes its own plan.
    assert policy.queue(state, 1, decision, 3, 4, execute_plan=True) == queued
    # On the later step's eve it is due.
    eve = replace(state, day=later.day - DAY)
    assert [m.add for m in policy.queue(eve, 1, decision, 3, 4).pending[1]] == [
        first.add,
        later.add,
    ]
    # The same decision with no plan leading queues the set, and the plan's step only when the
    # arm executes plans: the streaming plan beside the set, as before this PR.
    beside = replace(decision, plan_leads=False)
    assert policy.queue(state, 1, beside, 3, 4).pending[1] == (in_set,)
    assert [m.add for m in policy.queue(state, 1, beside, 3, 4, True).pending[1]] == [
        in_set.add,
        first.add,
    ]
    # The day's cap and the week's adds hold a leading plan as they hold a set.
    both_due = replace(decision, plan=(first, replace(later, day=first.day)))
    assert len(policy.queue(state, 1, both_due, 1, 4).pending[1]) == 1
    spent = replace(state, adds_used={1: 4})
    assert policy.queue(spent, 1, decision, 3, 4).pending[1] == ()


def test_the_decision_s_default_is_no_plan_leading():
    assert policy.Decision().plan_leads is False
    assert policy.Decision((), (), (), 0, "exact", None).plan_leads is False


# --------------------------------------------------------------------------- the counts
def test_the_queue_s_counts_are_kept_only_for_a_run_that_names_queue():
    """Rule 1's side of the counts: a tally not told of a queue arm has no such key, so a run
    that names no ``queue`` counts as on main; one told has both keys in every seat's row, 0
    for a seat whose queue took no plan."""
    setup = make_setup()
    state = initial(setup)
    plain = ct.Tally(setup).rows(state)
    assert all(not set(ct.PLANS) & set(row) for row in plain.values())
    assert ct.metrics_in(list(plain.values())) == ct.METRICS
    tally = ct.Tally(setup, True)
    tally.took(1, 2)
    tally.took(1, 0)
    rows = tally.rows(state)
    assert rows[1]["plan_days"] == 2.0 and rows[1]["plan_steps"] == 2.0
    assert all(rows[t]["plan_days"] == rows[t]["plan_steps"] == 0.0 for t in setup.teams if t != 1)
    assert {k: v for k, v in rows[2].items() if k not in ct.PLANS} == plain[2]
    assert ct.metrics_in(list(rows.values())) == (*ct.METRICS, *ct.PLANS)
    assert ct.PLANS == ("plan_days", "plan_steps")


def test_the_counts_note_says_the_queue_s_counts_only_when_an_arm_executes_queue():
    three = rn.arm_of(spec(executes="three", name="T"))
    queue = rn.arm_of(spec())
    assert not ss.queue_run([three, replace(three, executes=policy.WEIGHTED)])
    assert ss.queue_run([three, queue])
    for waivers in ("none", "priority", "faab"):
        before = ss.counts_note(waivers)
        assert ss.counts_note(waivers, False) == before and not set(ct.PLANS) & set(before)
        with_queue = ss.counts_note(waivers, True)
        assert list(with_queue) == [*before, *ct.PLANS]
        assert {k: with_queue[k] for k in before} == dict(before)
    assert ss.counts_note() is ss.COUNTS_NOTE
    assert "instead of the three weeks' set" in ss.PLANS_NOTE["plan_days"]
    assert "queued" in ss.PLANS_NOTE["plan_steps"]
    assert rn.queue_named([{1: queue.seat()}]) and not rn.queue_named([{1: three.seat()}])


# --------------------------------------------------------------------------- parity
def moves_of(plan) -> list[tuple]:
    return [(s.move.add, s.move.drop, s.day) for s in plan.steps]


def check_parity(built, weight: float, playoff: bool) -> policy.Drawn:
    """What the seat draws against the library called straight through the door: every input
    it hands the engine is the one the live route hands it (made here again, by the door's own
    names), and its choice is ``plans.for_queue``'s on them. ``weight`` and ``playoff`` are the
    case's, said by the test and not read off the seat."""
    p = built.problem
    drawn = policy.draw_queue(built)
    ev = mv.Evaluator(p)
    allowed = policy.guard_of(built)
    held = pl.held_out(ev)
    assert (drawn.weight, drawn.playoff) == (weight, playoff)
    # The three weeks' set as ``executes: three`` finds it.
    assert drawn.three == policy.exact(built, policy.QUEUE_SET, with_plan=False)
    # The week's swaps, set and streaming plan, as the live route builds them.
    swaps = mv.single_swaps(ev, "week")
    assert {c: list(g) for c, g in drawn.swaps.items()} == {c: list(g) for c, g in swaps.items()}
    ranked = sorted(
        (c for c, g in swaps.items() if g and g[0].gain > policy.DEFAULT_FIELDS.min_gain),
        key=lambda c: -swaps[c][0].gain,
    )[: policy.DEFAULT_FIELDS.pool]
    week = mv.recommend(
        ev, "week", ranked, min_gain=policy.DEFAULT_FIELDS.min_gain, allowed=allowed
    )
    assert drawn.week_set == tuple(pm.move for pm in week.moves)
    per_game = {k: wk.net_value(built.scorer, r) for k, r in p.rates.items()}
    stream = st.plan(ev, built.rule, drawn.week_set, per_game, guard=False, allowed=allowed)
    assert drawn.stream == stream
    # The engine's plans and its choice, on those inputs.
    three = drawn.three.moves
    every = pl.every_plan(ev, drawn.week_set, swaps, stream, allowed, held, three, weight)
    assert list(drawn.plans) == every
    chosen = pl.for_queue(ev, every, three, weight, playoff, allowed, held)
    assert drawn.chosen == chosen
    return drawn


def decision_of(built, drawn: policy.Drawn, monkeypatch) -> policy.Decision:
    """The seat's decision on what it drew, without solving the day again."""
    monkeypatch.setattr(policy, "draw_queue", lambda b, f=policy.DEFAULT_FIELDS: drawn)
    return policy.decide(built, "exact", policy.QUEUE)


def check_decision(built, drawn: policy.Drawn, decision: policy.Decision) -> None:
    """The decision made of the engine's answer: the plan's steps, dated, with its held-slot
    moves when a plan leads; else the three weeks' set as ``three`` gives it."""
    three = drawn.three
    assert decision.moves == three.moves and decision.source == "exact"
    assert decision.solves == three.solves + 2
    if drawn.chosen is None:
        assert not decision.plan_leads and decision.plan == ()
        assert decision == replace(three, solves=decision.solves)
        return
    assert decision.plan_leads
    assert [(m.add, m.drop, m.day) for m in decision.plan] == moves_of(drawn.chosen)
    assert decision.held == tuple(mv.held_used(built.problem, drawn.chosen.moves))


def held_case():
    setup, status, returns = returning()
    return built_on(setup, status=status, returns=returns)


#: The parity cases: a made-up problem, the weight and the playoff flag the seat must hand the
#: engine, and whether a plan leads there (found by ``~/sim-notes/vm/scratch/e/probe1.py`` and
#: ``probe2.py``; what leads is the engine's answer, checked against the engine's own call).
PARITY = {
    # One win per matchup: the engine's own floor, in the matchup's odds.
    "one win, a plan taken": (lambda: built_on(cats(), day=3, three_weight=0.0), 0.0, False, True),
    "one win, the set at a higher weight": (
        lambda: built_on(cats(), day=3, three_weight=0.9),
        0.9,
        False,
        False,
    ),
    "one win, the week's set is the three weeks'": (lambda: built_on(cats()), 0.33, False, False),
    "one win, the knob's floor is not the league's": (
        lambda: built_on(cats(), day=3, three_weight=0.0, plan_floor_cats=50.0),
        0.0,
        False,
        True,
    ),
    # Every category: the knob's floor.
    "every category, a plan taken": (
        lambda: built_on(every_category(cats()), day=3),
        0.33,
        False,
        True,
    ),
    "every category, its floor too high": (
        lambda: built_on(every_category(cats()), day=3, plan_floor_cats=50.0),
        0.33,
        False,
        False,
    ),
    "every category, a plan over several days": (
        lambda: built_on(every_category(weakened(cats())), three_weight=0.0),
        0.0,
        False,
        True,
    ),
    # A points league: its own floor.
    "points, a plan taken": (
        lambda: built_on(points_setup(), day=3, three_weight=0.0),
        0.0,
        False,
        True,
    ),
    "points, its own floor too high": (
        lambda: built_on(points_setup(), day=3, three_weight=0.0, plan_floor_points=50.0),
        0.0,
        False,
        False,
    ),
    "points, the categories' floor is not its": (
        lambda: built_on(points_setup(), day=3, three_weight=0.0, plan_floor_cats=50.0),
        0.0,
        False,
        True,
    ),
    # A bracket week: the weight 0 whatever the knob, the matchup's odds, the playoff floor.
    "a bracket week, a plan on the odds": (
        lambda: built_on(bracketed(cats()), day=14, three_weight=0.9),
        0.0,
        True,
        True,
    ),
    "a bracket week, every category: the playoff floor": (
        lambda: built_on(
            bracketed(every_category(cats())), day=14, three_weight=0.9, plan_floor_cats=50.0
        ),
        0.0,
        True,
        True,
    ),
    "a bracket week, points: the set stands": (
        lambda: built_on(bracketed(points_setup()), team=2, day=14, three_weight=0.9),
        0.0,
        True,
        False,
    ),
    "a bracket week of a season's own, no opponent read": (
        lambda: built_on(cats(), day=14, three_weight=0.9),
        0.0,
        True,
        False,
    ),
    # Held slots: a return inside the week.
    "held slots, a return inside the week": (held_case, 0.33, False, True),
}


@pytest.mark.parametrize("case", PARITY)
def test_the_seat_s_choice_is_the_library_s_for_queue_through_the_door(case):
    make, weight, playoff, leads = PARITY[case]
    built = make()
    p = built.problem
    drawn = check_parity(built, weight, playoff)
    assert (drawn.chosen is not None) == leads, case
    check_decision(built, drawn, policy.decide(built, "exact", policy.QUEUE))
    # What the choice was made on, by the engine's own names: the floor of the week's kind, and
    # a plan that leads clears it over the set on the gate.
    floor = pl.gate_floor(p, playoff)
    if playoff:
        assert floor == pl.PLAYOFF_FLOOR
    elif p.one_win:
        assert floor == st.PLAN_FLOOR_ODDS
    else:
        knob = "plan_floor_points" if p.points else "plan_floor_cats"
        assert floor == built.knobs[knob]
    ev = mv.Evaluator(p)
    against = pl.gate(ev, drawn.three.moves, weight, playoff)
    if drawn.chosen is not None:
        assert pl.gate(ev, drawn.chosen.moves, weight, playoff) > against + floor
        assert pl.valid(p, drawn.chosen.moves)
        assert mv.admitted(p, list(drawn.chosen.moves), policy.guard_of(built))
    if playoff and against is not None:
        # The gate is the matchup's odds, not the score.
        assert against == pl.matchup(ev, drawn.three.moves)


def test_the_parity_cases_are_what_their_names_say():
    """The cases' own power: the bracket week without a pairing reads no opponent (so the
    engine's gate is None and the set stands, the simulated season's case), the one with a
    pairing reads one; the held case's plans carry a return's worth, which only
    ``plans.held_out`` gives; the plan over several days has a step after tomorrow."""
    own = PARITY["a bracket week of a season's own, no opponent read"][0]()
    assert own.problem.horizons["week"][0].opponents == ()
    assert pl.gate(mv.Evaluator(own.problem), (), 0.0, True) is None
    named = PARITY["a bracket week, a plan on the odds"][0]()
    assert len(named.problem.horizons["week"][0].opponents) == 1
    assert policy.in_bracket(own) and policy.in_bracket(named)
    held = held_case()
    drawn = policy.draw_queue(held)
    backs = [b for plan in drawn.plans for b in plan.backs]
    assert backs and all(b.returning and b.gain is not None for b in backs)
    ev = mv.Evaluator(held.problem)
    allowed = policy.guard_of(held)
    three = drawn.three.moves
    without = pl.every_plan(
        ev, drawn.week_set, drawn.swaps, drawn.stream, allowed, None, three, drawn.weight
    )
    assert without != list(drawn.plans)
    assert all(b.gain is None for plan in without for b in plan.backs)
    several = PARITY["every category, a plan over several days"][0]()
    steps = policy.decide(several, "exact", policy.QUEUE).plan
    tomorrow = several.problem.first_day + DAY
    assert {m.day for m in steps} > {tomorrow} and min(m.day for m in steps) == tomorrow


def test_the_plan_switches_are_not_read_by_the_rule():
    """``with_plan`` reaches ``policy.decide`` from a seat built by hand; the rule draws its own
    plan either way."""
    built = PARITY["one win, a plan taken"][0]()
    drawn = policy.decide(built, "exact", policy.QUEUE, True)
    assert drawn.plan_leads and drawn == policy.decide(built, "exact", policy.QUEUE, False)
    assert drawn == policy.exact(built, policy.QUEUE) == policy.queue_rule(built)


# --------------------------------------------------------------------------- the season term
def adds(moves) -> set[int]:
    return {m.add for m in moves}


def test_the_season_term_is_on_the_set_and_the_gate_is_the_engine_s_own_score():
    """The term's place (the brief's second choice: the library does not take the wrapper).
    In the league where the three weeks and the season disagree, at a ``season_weight`` above 0
    the three weeks' set is the one the term chose, the week's inputs and the plans' values are
    the plain evaluator's, and the gate weighs that set on the engine's own score: the set the
    term chose is passed over for a plan, the guard holding. At weight 0 the same case is the
    library's choice on the plain set."""
    setup, _, strong, dead = flip_setup()
    plain = built_on(setup, day=3, three_weight=0.0)
    termed = built_on(setup, day=3, three_weight=0.0, season_weight=1.0)
    a = check_parity(plain, 0.0, False)
    b = check_parity(termed, 0.0, False)
    # The term reaches the three weeks' set: the season's player, whom the three weeks do not see.
    assert strong in adds(b.three.moves) and strong not in adds(a.three.moves)
    assert b.three == policy.exact(termed, policy.QUEUE_SET, with_plan=False)
    # It does not reach the week's inputs.
    assert (a.week_set, a.stream, dict(a.swaps)) == (b.week_set, b.stream, dict(b.swaps))
    # The gate: the term's set is worth nothing on the engine's score this week, a plan beats it
    # by the floor, and the queue takes the plan; the guard admits it.
    ev = mv.Evaluator(termed.problem)
    assert pl.score(ev, b.three.moves, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert a.chosen is None and b.chosen is not None
    assert strong not in adds(b.chosen.moves)
    assert mv.admitted(termed.problem, list(b.chosen.moves), policy.guard_of(termed))
    decision = policy.decide(termed, "exact", policy.QUEUE)
    assert decision.plan_leads and decision.moves == b.three.moves
    # The wrapper is not what the library takes: it has no odds for a bracket week's gate.
    wrapped = policy.seasoned(termed, ev, policy.QUEUE_SET)
    assert isinstance(wrapped, policy.Seasoned) and not hasattr(wrapped, "odds")
    assert dead in {m.drop for m in b.three.moves}


# --------------------------------------------------------------------------- the bids
def faab(setup):
    return replace(setup, waivers="faab", waiver_days=2)


def test_a_plan_s_step_bids_on_its_score_at_the_queue_s_weight():
    """In a FAAB league a step of the plan the queue took bids on its score, the week increment
    plus the arm's ``three_weight`` times its three weeks' increment (``plans.step_score``), as
    the live queue bids it; the set's gains stay the day's recommended moves' (the fortnight's
    typical gain). By priority no decision carries a basis."""
    setup = faab(every_category(cats()))
    bids = {}
    for weight in (0.0, 0.9):
        built = built_on(setup, day=3, three_weight=weight)
        assert built.bids
        drawn = policy.draw_queue(built)
        decision = policy.decide(built, "exact", policy.QUEUE)
        assert drawn.chosen is not None and decision.plan_leads and decision.basis is not None
        by_hand = [s.gain["week"] + weight * s.gain["three"] for s in drawn.chosen.steps]
        assert list(decision.basis.plan) == pytest.approx(by_hand)
        assert decision.basis.plan == policy.step_bids(drawn.chosen, weight)
        assert decision.basis == replace(drawn.three.basis, plan=decision.basis.plan)
        assert drawn.three.basis.plan == ()
        bids[weight] = (
            [(m.add, m.drop) for m in decision.plan],
            decision.basis.plan,
            [s.gain["three"] for s in drawn.chosen.steps],
        )
    # The same plan at both weights here, some step with a three weeks' increment: its bid
    # moves with the weight.
    assert bids[0.0][0] == bids[0.9][0] and any(abs(x) > 1e-6 for x in bids[0.9][2])
    assert bids[0.0][1] != bids[0.9][1]
    by_priority = built_on(replace(setup, waivers="priority"), day=3, three_weight=0.9)
    assert policy.decide(by_priority, "exact", policy.QUEUE).basis is None


def test_in_a_bracket_week_a_step_bids_on_its_week_increment_alone():
    built = built_on(faab(bracketed(cats())), day=14, three_weight=0.9)
    drawn = policy.draw_queue(built)
    decision = policy.decide(built, "exact", policy.QUEUE)
    assert drawn.chosen is not None and drawn.weight == 0.0
    assert decision.basis.plan == tuple(s.gain["week"] for s in drawn.chosen.steps)


def test_under_three_a_streaming_plan_s_step_bids_as_before_whatever_the_weight():
    """Rule 1 for the bids: an arm that executes ``three`` and draws its streaming plan bids a
    step on its week increment alone (``stream.step_gains``), at any ``three_weight``."""
    setup = faab(every_category(weakened(cats())))
    seen = []
    for weight in (0.0, 0.9):
        built = built_on(setup, three_weight=weight, plan_floor_cats=-1.0)
        decision = policy.exact(built, policy.QUEUE_SET, with_plan=True)
        assert decision.plan and not decision.plan_leads and decision.basis is not None
        assert len(decision.basis.plan) == len(decision.plan)
        seen.append(decision)
    assert seen[0] == seen[1]


def test_a_leading_plan_s_claim_carries_its_step_s_bid_and_the_fortnight_keeps_the_set_s():
    """The executor, under continuous waivers by FAAB (every add a claim): the claim of a
    leading plan's step bids the live rule on the step's score, and the fortnight's typical
    gain takes the day's recommended moves, the three weeks' set's, as the live queue's does on
    a day a plan leads."""
    setup = replace(make_setup(), waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)
    state, decision, in_set, first, _ = leading(setup)
    basis = policy.Basis(policy.LIVE, (2.0,), (6.0, 9.0), None, 1.0)
    queued = policy.queue(
        state, 1, replace(decision, basis=basis), 3, 4, False, setup.spots(), setup
    )
    (claim,) = queued.claims[1]
    assert (claim.move.add, claim.move.drop) == (first.add, first.drop)
    assert claim.bid == policy.live_bid(6.0, [2.0], 1.0, setup.budget, None) > 0
    assert queued.recent[1] == ((state.day, 2.0),)
    # The set's own claim, when no plan leads, bids on the set's gain.
    beside = policy.queue(
        state,
        1,
        replace(decision, basis=basis, plan_leads=False),
        3,
        4,
        False,
        setup.spots(),
        setup,
    )
    (own,) = beside.claims[1]
    assert own.move.add == in_set.add
    assert own.bid == policy.live_bid(2.0, [2.0], 1.0, setup.budget, None)


# --------------------------------------------------------------------------- seasons
TABLE = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0, "threes": 1.0}
SMALL = {"teams": 4, "pool": 12, "weeks": 3, "playoff_weeks": 1}


def in_points(setup):
    """``setup`` scored in points (``test_sim_knobs.points_setup``'s table)."""
    spec = replace(setup.spec, scoring="points", points=TABLE, cats=())
    return replace(setup, scoring="points", points=TABLE, cats=("fpts",), spec=spec)


def waiving(setup, waivers: str, rule: str = DROPPED):
    return replace(setup, waivers=waivers, waiver_days=2, waiver_rule=rule)


#: Every league kind once (the lesson of Fc's review): held slots, points, by priority and by
#: FAAB, both waiver rules, both head-to-head formats, and no waivers at all. Three weeks, four
#: seats, twelve free agents.
KINDS = {
    "every category, no waivers": lambda: every_category(make_setup(**SMALL)),
    "one win, priority, a dropped player waits, IL": lambda: waiving(
        make_setup(**SMALL, held_slots=("IL",)), "priority"
    ),
    "one win, FAAB, continuous": lambda: waiving(make_setup(**SMALL), "faab", CONTINUOUS),
    "every category, FAAB, continuous, IL": lambda: every_category(
        waiving(make_setup(**SMALL, held_slots=("IL",)), "faab", CONTINUOUS)
    ),
    "every category, priority, a dropped player waits": lambda: every_category(
        waiving(make_setup(**SMALL), "priority")
    ),
    "points, FAAB, a dropped player waits": lambda: waiving(in_points(make_setup(**SMALL)), "faab"),
    "points, priority, continuous, IL": lambda: waiving(
        in_points(make_setup(**SMALL, held_slots=("IL",))), "priority", CONTINUOUS
    ),
}
#: The world's seed and path every season below is played on: the first tried.
PATH = (1, 0)


def queue_arm(name: str = "Q", **knobs) -> rn.Arm:
    return rn.Arm(
        name, "exact", {**KNOBS, "daily_cap": 3, **knobs}, {"kind": "market"}, policy.QUEUE
    )


def season(setup, seat: rn.Arm):
    """A made-up season with ``seat`` in seat 1 among market rivals at 0.3 a day: the variant's
    result and its day records."""
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    days: list[rn.DayRecord] = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: seat.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=days.append)
    return result, days


def placed(r: rn.DayRecord, team: int = 1) -> list[tuple[int, int | None]]:
    """What ``team`` queued on the day: its free agents for the morning, then its claims."""
    return [(m.add, m.drop) for m in r.queued.get(team, ())] + [
        (c.move.add, c.move.drop) for c in r.claims.get(team, ())
    ]


@pytest.mark.parametrize("kind", KINDS)
def test_every_league_kind_plays_a_season_under_queue_and_the_audit_finds_nothing(kind):
    """The rule in every league kind, once: the queue takes a plan on some day, the seat lands
    adds, the audit finds nothing; on a day a plan leads the seat queues steps of that day's own
    plan and nothing of the set; and the counts say what the days show, in every seat's row."""
    setup = KINDS[kind]()
    result, days = season(setup, queue_arm())
    assert result.breaches == ()
    counts = result.counts
    assert counts[1]["landed"] >= 1, counts[1]
    led = [r for r in days if r.decisions[1].plan_leads]
    assert led, "the queue took no plan on any day"
    for r in led:
        d = r.decisions[1]
        steps = [(m.add, m.drop) for m in d.plan]
        assert set(placed(r)) <= set(steps), (r.day, placed(r), steps)
        # A free agent's add is queued for tomorrow: only a step dated tomorrow.
        tomorrow = {(m.add, m.drop) for m in d.plan if m.day == r.day + DAY}
        assert {(m.add, m.drop) for m in r.queued.get(1, ())} <= tomorrow
    for r in days:
        d = r.decisions[1]
        if not d.plan_leads:
            assert d.plan == () and set(placed(r)) <= {(m.add, m.drop) for m in d.moves}
    # The counts: the seat's are the days' own; a rival's row has the keys, at 0.
    assert counts[1]["plan_days"] == len(led)
    assert counts[1]["plan_steps"] == sum(len(placed(r)) for r in led)
    for t in setup.teams[1:]:
        assert counts[t]["plan_days"] == counts[t]["plan_steps"] == 0.0
    assert ct.metrics_in(list(counts.values()))[-2:] == ct.PLANS
    if "IL" in kind:
        assert counts[1]["held_stints"] >= 1, counts[1]


def test_a_later_step_waits_for_its_day_and_is_planned_again_the_next_day():
    """A season where the queue takes plans over several days (every category, no waivers). On
    a day a plan leads, a step dated after tomorrow is not queued; the state carries no plan
    (only tomorrow's moves), and the next day's queue is made of the next day's own decision:
    a step first planned for a later day is queued on the eve it is due, by the plan drawn
    that evening."""
    setup = KINDS["every category, no waivers"]()
    _, days = season(setup, queue_arm())
    waited = 0
    carried = 0
    seen_later: dict[int, object] = {}
    for r in days:
        d = r.decisions[1]
        queued = [(m.add, m.drop) for m in r.queued.get(1, ())]
        assert all(m.day is None for m in r.state.pending.get(1, ()))
        if not d.plan_leads:
            continue
        for m in d.plan:
            if m.day > r.day + DAY:
                assert (m.add, m.drop) not in queued, (r.day, m)
                waited += 1
                seen_later.setdefault(m.add, r.day)
            elif m.add in seen_later and seen_later[m.add] < r.day and (m.add, m.drop) in queued:
                carried += 1
    assert waited >= 1, "no plan of the season had a step after tomorrow"
    assert carried >= 1, "no step that waited was queued by a later day's plan"


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_plan_floor_decides_whether_the_queue_ever_takes_a_plan(h2h):
    """The lever does something, in the counts: where the league reads the knob (every
    category) a floor no plan clears leaves the set every day, and one below zero takes a plan
    on every day a valid one has a step. In a one-win league the floor is the engine's own and
    the knob moves nothing."""
    setup = make_setup(**SMALL)
    if h2h == EACH_CATEGORY:
        setup = every_category(setup)
    high, _ = season(setup, queue_arm(plan_floor_cats=50.0))
    low, low_days = season(setup, queue_arm(plan_floor_cats=-1.0))
    if h2h == EACH_CATEGORY:
        assert high.counts[1]["plan_days"] == 0.0 and low.counts[1]["plan_days"] >= 1
        assert high.counts != low.counts
    else:
        assert high.counts == low.counts and low.counts[1]["plan_days"] >= 1
    assert low.breaches == high.breaches == ()
    assert any(r.decisions[1].plan_leads for r in low_days)


def test_arms_that_share_a_room_each_take_the_rule_and_count_their_own_plans():
    """A room, where every seat is an arm's (a room has no rival seats, and is one season): an
    arm that executes ``queue`` and one that executes ``three``, in two seats each. The queue
    arm's seats take plans, counted in its row; the other arm's row has the keys at 0."""
    setup = every_category(make_setup(**SMALL))
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    out = rn.room(
        setup, w, {"Q": queue_arm(), "T": replace(queue_arm("T"), executes="three")}, ["Q", "T"], 0
    )
    assert out["breaches"] == []
    assert out["counts"]["Q"]["plan_days"] >= 1 and out["counts"]["T"]["plan_days"] == 0.0
    assert set(ct.PLANS) <= set(out["counts"]["T"])


def test_no_rival_takes_the_queue_s_rule(monkeypatch):
    """No rival takes ``queue`` (the lead, 2026-11-19; the brief's "a rival may take it" is
    withdrawn). The runner shares a decision between two variants whose seat and state key agree
    (``(team, repr(seat), state.key())``), and the key holds no week totals. A rival is the same
    seat in both arms' seasons, so one that read the week, as the queue's rule does, would share
    a decision between seasons whose totals differ. So a queue arm's rivals are what they were:
    static, the market, or its mirror, which decides on the surrogate tier and is handed nothing
    the arm executes. The arm's own seat is never shared between two arms: its name is in it."""
    setup = make_setup(**SMALL)
    for kind in op.KINDS[:3]:
        q = replace(queue_arm(), opponents={"kind": kind})
        rivals = rn.opponents_of(setup, q, 1)
        assert len(rivals) == len(setup.teams) - 1
        assert not any(isinstance(r, op.Seat) for r in rivals.values())
        assert not rn.queue_named([rivals])
    mirror = op.of({"kind": "mirror"}, queue_arm().knobs, 0.3)
    assert isinstance(mirror, op.Mirror) and not hasattr(mirror, "executes")
    asked = []
    real = policy.decide

    def spy(built, tier, *args, **kw):
        asked.append((tier, args, sorted(kw)))
        return real(built, tier, *args, **kw)

    monkeypatch.setattr(policy, "decide", spy)
    mirror.decide(setup, initial(setup), 2, setup.projection, {}, {}, None)
    assert asked == [("surrogate", (), ["fields"])]
    assert repr(queue_arm("A").seat()) != repr(queue_arm("B").seat())
    # The state's key holds no totals: two states apart only in the week's totals share it.
    first = initial(setup)
    scored = replace(first, totals={1: {1: {"pts": 9.0}}})
    assert scored.totals != first.totals and scored.key() == first.key()


def test_a_split_seat_executes_the_queue_s_rule_on_its_own_table():
    """The lesson of the draft PR's review: a rule the seat plays is played once by a seat whose
    table is split (``blend``: the first stand-in for every rostered player, the mix for the
    rest; ``test_sim_split.py``'s league and stand-ins, every category counted). The queue's
    rule reads the problem built on the seat's table, as every tier does: the table of each day
    is the split, the queue takes a plan on some day, the audit finds nothing, and the same arm
    on the first stand-in alone (``bbm``) queues something else on some day."""
    setup, lines = recorded()
    setup = every_category(setup)
    first = {k: {st_: v * 1.1 for st_, v in r.items()} for k, r in setup.projection.items()}
    second = split.second_of(first)
    blend = replace(
        arm("Y", "exact", "market", three_weight=0.0, system="blend", blend=0.25),
        executes=policy.QUEUE,
    )
    plain = replace(blend, name="B", knobs={**blend.knobs, "system": "bbm", "blend": None})
    arms = ss.believing({"Y": blend, "B": plain}, split.SOURCES)
    label = arms["Y"].forecaster
    assert label in ss.splits_of(split.SOURCES, arms) and arms["B"].forecaster == split.FIRST
    w = split.world_of(setup, lines, first, second, arms)
    queued = {}
    for name in ("Y", "B"):
        records, res = split.run(setup, w, split.variant_of(setup, {name: arms[name]}, {1: name}))
        assert res.breaches == ()
        assert any(r.decisions[1].plan_leads for r in records), name
        assert res.counts[1]["plan_days"] == sum(r.decisions[1].plan_leads for r in records)
        if name == "Y":
            for r in records:
                assert r.holds == {1: label}
                split.assert_split(w, r, label)
        queued[name] = [(r.day, placed(r)) for r in records]
    assert queued["Y"] != queued["B"]


# --------------------------------------------------------------------------- Rule 1
def rounded(x):
    if isinstance(x, float):
        return round(x, 9)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [rounded(v) for v in x]
    return x


def pair_digest(setup) -> str:
    """SHA-256 of a pair's whole task result (``run.paired``: both arms' outcomes, their
    difference, the solves, the moves, the counts of both arms and of the rivals, the breaches
    and the season scale, every key), each figure rounded to nine places: an exact arm that
    executes ``three`` with its streaming plan drawn and executed against one that executes
    ``weighted``, in seat 1 among market rivals through one world."""
    knobs = {**KNOBS, "daily_cap": 3}
    three = rn.Arm("A", "exact", knobs, {"kind": "market"}, policy.QUEUE_SET, True, True)
    weighted = rn.Arm("B", "exact", knobs, {"kind": "market"}, policy.WEIGHTED, False, False)
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    out = rounded(rn.paired(setup, w, three, weighted, 1))
    return hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()


#: Rule 1's pins: the pair of :func:`pair_digest` on two of :data:`KINDS` (one win by priority
#: with an IL slot; every category by FAAB under continuous waivers with an IL slot), as main
#: ``4b26577`` gave them (``~/sim-notes/vm/scratch/e/rule1_pins.py``, the same digest, run on a
#: copy of main's code and on this PR's tree).
RULE1_ONE_WIN = "c439af76da05a93a1a938fedfac6ecee69cc511c17b88bd3293ea28724f17dc4"
RULE1_EACH = "8bbd948eb04f1d5f9a7917400df4416c50d705258e765c8efe5b83cd59ede35a"


def test_rule_1_an_arm_that_does_not_name_queue_plays_as_main_s():
    """Arms that execute ``three`` and ``weighted`` give main's results, counts and keys, to the
    last key of the pair's record; and no row of such a run has the queue's counts."""
    assert pair_digest(KINDS["one win, priority, a dropped player waits, IL"]()) == RULE1_ONE_WIN
    assert pair_digest(KINDS["every category, FAAB, continuous, IL"]()) == RULE1_EACH


def test_a_pair_s_rows_carry_the_queue_s_counts_only_when_an_arm_names_queue():
    setup = KINDS["every category, no waivers"]()
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    three = replace(queue_arm("T"), executes=policy.QUEUE_SET)
    weighted = replace(queue_arm("W"), executes=policy.WEIGHTED, with_plan=False)
    plain = rn.paired(setup, w, three, weighted, 1)
    for row in plain["counts"].values():
        assert not set(ct.PLANS) & set(row)
    mixed = rn.paired(setup, w, three, queue_arm(), 1)
    assert mixed["breaches"] == []
    rows = mixed["counts"]
    assert all(set(ct.PLANS) <= set(rows[side]) for side in ("a", "b", "rivals"))
    assert rows["a"]["plan_days"] == rows["rivals"]["plan_days"] == 0.0
    assert rows["b"]["plan_days"] >= 1
    # The three arm's own figures are what they are beside a weighted arm: the queue arm's
    # presence adds its two keys to the row and moves nothing of it.
    assert {k: v for k, v in rows["a"].items() if k not in ct.PLANS} == plain["counts"]["a"]
    assert mixed["a"] == plain["a"]
    # Two leagues drafted apart: both seasons' rows carry the keys when either arm names queue.
    apart = rn.paired_apart(setup, w, setup, w, three, queue_arm(), 1)
    assert apart["counts"]["a"]["plan_days"] == 0.0 and apart["counts"]["b"] == rows["b"]
    assert set(ct.PLANS) <= set(apart["counts"]["rivals"])
