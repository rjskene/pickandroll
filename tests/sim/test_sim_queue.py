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
from pickandroll.sim.state import BENCH, WON, Waiting, initial
from tests.sim import test_sim_split as split
from tests.sim import test_sim_stash as stash
from tests.sim.sim_league import KNOBS, arm, every_category, make_setup, rates, recorded_lines
from tests.sim.test_no_peek import recorded
from tests.sim.test_sim_continuous import morning, spots_of
from tests.sim.test_sim_held_morning import found
from tests.sim.test_sim_knobs import flip_setup, points_setup, weakened

DAY = timedelta(1)
FORMATS = (ONE_WIN, EACH_CATEGORY)
#: The plan floors every problem and season of this file reads, away from 0. At a floor of 0 a
#: plan that only ties its set (the set's own moves, a step that adds nothing) is taken or not,
#: and trimmed or not, on a float's last bit, which moves with the process's hash seed
#: (``sim_league.KNOBS``' note: a test that reads a plan floor sets it away from 0). Under the
#: queue's rule a league that counts every category and a points league read the knob as the
#: gate a week plan clears; a one-win league reads neither (its floor is the engine's own).
#: Small, so the made-up leagues' plans clear it.
FLOORS = {"plan_floor_cats": 0.01, "plan_floor_points": 0.01}


def built_on(setup, team: int = 1, day: int = 0, status=None, returns=None, **knobs):
    """``team``'s problem ``day`` days into the made-up season, on the day-one rosters. The
    cap is three a day unless the case says otherwise, so a plan may take several steps a day;
    the plan floors are :data:`FLOORS` unless the case names one."""
    today = replace(initial(setup), day=setup.start + day * DAY)
    knobs = {**KNOBS, "daily_cap": 3, **FLOORS, **knobs}
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
    # The arm's own seat (a pair's, or each of its seats in a room) takes the rule; no rival
    # does (``test_no_rival_takes_the_queue_s_rule``).
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
    decision = policy.Decision((in_set,), (), (first, later), 3, "exact", None, plan_leads=True)
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
    tally = ct.Tally(setup, plans=True)
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
        assert ss.counts_note(waivers, queue=False) == before and not set(ct.PLANS) & set(before)
        with_queue = ss.counts_note(waivers, queue=True)
        assert list(with_queue) == [*before, *ct.PLANS]
        assert {k: with_queue[k] for k in before} == dict(before)
        # Beside the stash count (PR G), the queue's counts come last.
        assert list(ss.counts_note(waivers, True, True)) == [*before, *ct.STASH, *ct.PLANS]
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


@pytest.mark.parametrize("case", ["one win, a plan taken", "every category, a plan taken"])
def test_the_plan_switches_are_not_read_by_the_rule(case):
    """``with_plan`` reaches ``policy.decide`` from a seat built by hand; the rule draws its own
    plan either way, in both head-to-head formats."""
    built = PARITY[case][0]()
    drawn = policy.decide(built, "exact", policy.QUEUE, True)
    assert drawn.plan_leads and drawn == policy.decide(built, "exact", policy.QUEUE, False)
    assert drawn == policy.exact(built, policy.QUEUE) == policy.queue_rule(built)


# --------------------------------------------------------------------------- the season term
def adds(moves) -> set[int]:
    return {m.add for m in moves}


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_season_term_is_on_the_set_and_the_gate_is_the_engine_s_own_score(h2h):
    """The term's place (the brief's second choice: the library does not take the wrapper).
    In the league where the three weeks and the season disagree, at a ``season_weight`` above 0
    the three weeks' set is the one the term chose, the week's inputs and the plans' values are
    the plain evaluator's, and the gate weighs that set on the engine's own score: the set the
    term chose is passed over for a plan, the guard holding. At weight 0 the same case is the
    library's choice on the plain set. In both formats: with one win a matchup the gate's floor
    is the engine's own, and where every category counts it is the knob's (:data:`FLOORS`)."""
    setup, _, strong, dead = flip_setup()
    if h2h == EACH_CATEGORY:
        setup = every_category(setup)
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
    # The guard does not read the term: its figure for every single swap of the day and its
    # verdict on each set and on the plan are the same at both weights. So the term stands in
    # one place, the three weeks' set, and the record's note says that and no more.
    ros_plain, ros_termed = policy.ros_of(plain), policy.ros_of(termed)
    singles = [
        mv.Move(add, g.drop)
        for swaps in (a.swaps, b.swaps, mv.single_swaps(ev, policy.QUEUE_SET))
        for add, gains in swaps.items()
        for g in gains
    ]
    assert singles and [ros_plain(m) for m in singles] == [ros_termed(m) for m in singles]
    assert any(ros_plain(m) is not None and ros_plain(m) < 0 for m in singles)
    for moves in (a.three.moves, b.three.moves, b.chosen.moves, *([m] for m in singles)):
        assert mv.admitted(plain.problem, list(moves), policy.guard_of(plain)) == mv.admitted(
            termed.problem, list(moves), policy.guard_of(termed)
        )
    assert "on the three weeks' set only" in policy.QUEUE_SEASON
    assert "does not read the term" in policy.QUEUE_SEASON
    assert "in the guard" not in policy.QUEUE_SEASON
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
    typical gain). By priority no decision carries a basis. Every category counts here: the
    point is one plan bid at two weights, and in the one-win form of this problem the weight
    changes which of the plan and the set the queue takes (the parity cases); the bracket
    week's bid, below, is a one-win league's."""
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
    """An exact arm that executes ``queue`` among market rivals, three moves a day, its plan
    floors :data:`FLOORS` unless the test names one."""
    return rn.Arm(
        name,
        "exact",
        {**KNOBS, "daily_cap": 3, **FLOORS, **knobs},
        {"kind": "market"},
        policy.QUEUE,
    )


def season(setup, seat: rn.Arm, path: tuple[int, int] = PATH):
    """A made-up season with ``seat`` in seat 1 among market rivals at 0.3 a day, on ``path``:
    the variant's result and its day records. A seat that names a stash threshold has the
    run's count of it (``run.stash_named``), and an arm that executes its plan beside its set
    has the run execute it (``Arm.execute_plan``)."""
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *path)
    days: list[rn.DayRecord] = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: seat.seat()}
    (result,) = rn.simulate(
        setup,
        w,
        [variant],
        [seat.execute_plan],
        on_day=days.append,
        stash=rn.stash_named([seat]),
    )
    return result, days


def placed(r: rn.DayRecord, team: int = 1) -> list[tuple[int, int | None]]:
    """What ``team`` queued on the day: its free agents for the morning, then its claims."""
    return [(m.add, m.drop) for m in r.queued.get(team, ())] + [
        (c.move.add, c.move.drop) for c in r.claims.get(team, ())
    ]


def names_on_a_queued_drop(days, team: int = 1) -> list:
    """The days ``team`` named, for a held player's return, the drop of a move it queued that
    same day (the refit of PR G's names: none, since the names are made with the queue made)."""
    return [
        (r.day, r.state.sends[team], placed(r, team))
        for r in days
        if {x for _, x in r.state.sends.get(team, ())} & {drop for _, drop in placed(r, team)}
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
        # The seat names whom its held player sends, and never the drop of a move it queued
        # that day (the refit of PR G's names; in the points kind the name made on the set
        # alone was a queued step's drop on one day).
        assert any(r.state.sends.get(1) for r in days)
    assert names_on_a_queued_drop(days) == []


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_later_step_waits_for_its_day_and_is_planned_again_the_next_day(h2h):
    """A season where the queue takes plans over several days (no waivers, both formats). On
    a day a plan leads, a step dated after tomorrow is not queued; the state carries no plan
    (only tomorrow's moves), and the next day's queue is made of the next day's own decision:
    a step first planned for a later day is queued on the eve it is due, by the plan drawn
    that evening."""
    setup = make_setup(**SMALL)
    if h2h == EACH_CATEGORY:
        setup = every_category(setup)
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
    arm's seats take plans, counted in its row; the other arm's row has the keys at 0. The
    league counts every category: with one win a matchup the arm's two seats take no plan on
    this league and path (``~/sim-notes/vm/scratch/e/probe10.py``), and the test would count
    nothing."""
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
    rest; ``test_sim_split.py``'s league and stand-ins, every category counted: in its one-win
    form the queue takes no plan on that season, ``test_no_peek.py``). The queue's
    rule reads the problem built on the seat's table, as every tier does: the table of each day
    is the split, the queue takes a plan on some day, the audit finds nothing, and the same arm
    on the first stand-in alone (``bbm``) queues something else on some day."""
    setup, lines = recorded()
    setup = every_category(setup)
    first = {k: {st_: v * 1.1 for st_, v in r.items()} for k, r in setup.projection.items()}
    second = split.second_of(first)
    blend = replace(
        arm("Y", "exact", "market", three_weight=0.0, system="blend", blend=0.25, **FLOORS),
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


# --------------------------------------------------------------------------- the names
#: The ways an add reaches a roster (``test_sim_held_morning.WAYS``): a free agent's add, with
#: no waivers and with them; a claim under continuous waivers; and a claim on a dropped player
#: who clears the next morning, the rule not named. By priority and by FAAB.
ARRIVALS = (
    ("none", "free_agent"),
    *((w, way) for w in ("priority", "faab") for way in ("free_agent", "claim", "dropped_claim")),
)
#: And a claim on a dropped player who clears the morning after next: the step is dated then.
LATE = (("priority", "late_claim"), ("faab", "late_claim"))


def arriving(setup, waivers: str, way: str):
    """``setup`` with the waivers and the waiver rule ``way`` asks for."""
    if waivers == "none":
        return setup
    return waiving(setup, waivers, CONTINUOUS if way == "claim" else DROPPED)


def held_back(setup, day: int = 1):
    """Seat 1 ``day`` days into ``setup``'s season, a league with an IL slot: its best drafted
    player ``back`` in the slot, out and told back today, so his status clears tomorrow
    morning; its six active spots full with its other four and the wire's two weakest. The
    state, the statuses, the return dates, ``back``, and the per-game values a morning weighs."""
    value = wk.per_game_values(setup.projection, setup.cats, None)
    state = initial(setup)
    back, *rest = sorted((k for k, _ in state.rosters[1]), key=lambda k: -value[k])
    two = sorted(state.pool, key=lambda k: value[k])[:2]
    roster = (*((k, BENCH) for k in (*rest, *two)), (back, "IL"))
    today = setup.start + day * DAY
    state = replace(
        state, day=today, rosters={**state.rosters, 1: roster}, pool=state.pool - set(two)
    )
    return state, {back: "O"}, {back: today}, back, value


def next_morning(setup, state, decision, cap: int, execute_plan: bool, status, value):
    """``decision`` queued tonight and tomorrow morning played as the runner plays it (the
    returns and the trims, then the claims due, then the rest of the queue): the state the
    night leaves and the one the morning does."""
    spots, _ = spots_of(setup)
    night = policy.queue(state, 1, decision, cap, setup.max_weekly_adds, execute_plan, spots, setup)
    tomorrow = state.day + DAY
    return night, replace(morning(setup, night, tomorrow, status, value), day=tomorrow)


def placed_on(night) -> list[tuple[int, int | None]]:
    """What seat 1 has queued on the state ``night``: free agents, then claims."""
    return [(m.add, m.drop) for m in night.pending.get(1, ())] + [
        (c.move.add, c.move.drop) for c in night.claims.get(1, ())
    ]


#: The path of the season of an arm that names a stash threshold and executes ``queue``: on
#: the file's own (:data:`PATH`) that league's season counts the same with the threshold as without.
THRESHOLD_PATH = (1, 1)


def test_the_queue_is_gathered_in_one_place_for_the_executor_and_for_the_names():
    """``policy.gathered``: what a seat means to queue tonight. A plan that leads is gathered
    instead of the set, whatever the arm's plan switch; a plan beside the set only for an arm
    that executes its plan; a step by the day its add is due. The executor queues that list."""
    setup = cats()
    state, decision, in_set, first, later = leading(setup)
    tomorrow = state.day + DAY

    def due(add: int):
        return tomorrow

    for execute_plan in (False, True):
        assert policy.gathered(decision, execute_plan, due) == ([], [(first, 0)])
    beside = replace(decision, plan_leads=False)
    assert policy.gathered(beside, False, due) == ([in_set], [])
    assert policy.gathered(beside, True, due) == ([in_set], [(first, 0)])
    # A step dated later is due today when its add waits until then (a claim placed today),
    # and a step with no date is due.
    assert policy.gathered(beside, True, lambda add: later.day) == (
        [in_set],
        [(first, 0), (later, 1)],
    )
    undated = replace(beside, plan=(replace(later, day=None),))
    assert policy.gathered(undated, True, due) == ([in_set], [(undated.plan[0], 0)])
    assert policy.gathered(policy.NONE, True, due) == ([], [])
    # The executor queues what is gathered, on the state's reading of the day a step is due.
    for d, execute_plan in ((decision, False), (beside, False), (beside, True)):
        moves, steps = policy.gathered(d, execute_plan, due)
        want = tuple(mv.Move(m.add, m.drop) for m in (*moves, *(s for s, _ in steps)))
        assert policy.queue(state, 1, d, 3, None, execute_plan).pending[1] == want


def test_the_part_of_a_list_that_can_land_together_takes_each_add_and_each_drop_once():
    """``policy.distinct``, what the names are made with of the list gathered: the first move
    of the list that takes an add or a drop keeps it, and a later move that takes either again
    is left out. A move left out takes nothing; an add with no drop shares none; a step that
    drops an earlier move's add (a streaming plan's chain) stays."""
    a, b, c, x, y = 1, 2, 3, 11, 12
    first = mv.Move(a, x)
    assert policy.distinct([]) == []
    assert policy.distinct([first, mv.Move(a, y)]) == [first]
    assert policy.distinct([first, mv.Move(b, x)]) == [first]
    assert policy.distinct([first, first, mv.Move(b, y)]) == [first, mv.Move(b, y)]
    assert policy.distinct([first, mv.Move(a, y), mv.Move(b, y)]) == [first, mv.Move(b, y)]
    assert policy.distinct([mv.Move(a), mv.Move(b), mv.Move(a)]) == [mv.Move(a), mv.Move(b)]
    chain = [first, mv.Move(b, a), mv.Move(c, y)]
    assert policy.distinct(chain) == chain
    # A date is not read: a step is the move it makes.
    assert policy.distinct([first, mv.Move(a, x, cats().start)]) == [first]


def test_a_seat_that_holds_no_player_names_nobody_and_its_decision_is_untouched():
    """Rule 1's mechanism: ``policy.named`` is the identity on a problem that holds no player,
    in a league with an IL slot as in one without, whatever the decision carries. So no
    decision of such a seat moves with the refit, on any tier."""
    for setup in (cats(), make_setup(seed=3, weeks=3, playoff_weeks=1, held_slots=("IL",))):
        built = built_on(setup)
        assert built.problem.held == ()
        leads = leading(setup)[1]
        for decision in (leads, replace(leads, plan_leads=False), policy.NONE):
            assert policy.named(built.problem, decision) is decision
        for tier, executes in (
            ("exact", policy.QUEUE),
            ("exact", policy.QUEUE_SET),
            ("surrogate", policy.QUEUE_SET),
        ):
            decided = policy.decide(built, tier, executes)
            assert decided.sends == () and decided.plan_sends is None


@pytest.mark.parametrize("rule", (DROPPED, CONTINUOUS))
def test_the_day_a_step_is_due_reads_the_same_on_the_problem_as_on_the_state(rule):
    """The names are made when the seat decides, on its problem (``policy.due_on``), and the
    queue is built at night, on the state (``policy.due_by``): for every candidate the two say
    the same day, a free agent's tomorrow and a waiting player's clear date, so the names are
    made with the list the executor then queues."""
    setup = waiving(make_setup(**SMALL), "priority", rule)
    state = replace(initial(setup), day=setup.start + 2 * DAY)
    soon, late = sorted(state.pool)[:2]
    tomorrow = state.day + DAY
    waits = {soon: Waiting(tomorrow, 2), late: Waiting(tomorrow + 2 * DAY, 3)}
    state = replace(state, waivers=waits)
    built = policy.problem_of(setup, state, 1, dict(KNOBS), setup.projection, {}, {})
    due = policy.due_on(built.problem)
    candidates = [k for k, _ in built.problem.candidates]
    assert {soon, late} < set(candidates)
    for k in candidates:
        assert due(k) == policy.due_by(state, k, tomorrow), k
    assert due(soon) == tomorrow and due(late) == tomorrow + 2 * DAY
    assert due(max(state.pool)) == tomorrow


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize(("waivers", "way"), ARRIVALS)
def test_under_queue_a_returning_held_player_sends_whom_the_plan_s_step_made_charges(
    waivers, way, h2h
):
    """The refit of PR G's names, for the queue's rule: the names are made with what the seat
    queues that night made. A Tuesday on which the seat's held player is told back, in both
    formats and every way an add arrives: the queue takes a week plan, whose one step due
    tomorrow drops ``step.drop``. With the three weeks' set made, which is not queued, the
    engine's plan charges that very player for the return, and that was the name as PR G made
    it. With the step made it charges another player on the roster: the morning sends him, the
    step lands (a free agent's add, or a claim won after the return and the trim, the morning's
    order), the roster is the plan's and the audit finds nothing. With PR G's name the step's
    drop left for the return and the step was gone (a claim: failed)."""
    setup = make_setup(seed=2, weeks=3, playoff_weeks=1, held_slots=("IL",))
    setup = arriving(setup if h2h == ONE_WIN else every_category(setup), waivers, way)
    state, status, returns, back, value = held_back(setup)
    tomorrow = state.day + DAY

    def decided():
        built = policy.problem_of(
            setup, state, 1, {**KNOBS, "daily_cap": 3, **FLOORS}, setup.projection, status, returns
        )
        return built.problem, policy.decide(built, "exact", policy.QUEUE)

    p, decision = decided()
    if way == "dropped_claim":
        # The step's add was dropped by another team and clears tomorrow: the step is a claim.
        state = replace(state, waivers={decision.plan[0].add: Waiting(tomorrow, 3)})
        p, decision = decided()
    assert decision.plan_leads and decision.plan_sends is None and decision.moves
    moves, steps = policy.gathered(decision, False, policy.due_on(p))
    ((step, _),) = steps
    assert moves == [] and step.day == tomorrow and len(decision.plan) > 1
    # The names: with the step made, and not with the set made.
    ((held, named),) = decision.sends
    assert held == back and decision.sends == policy.sends_of(p, [step])
    as_g = policy.sends_of(p, decision.moves)
    assert as_g == ((back, step.drop),)
    assert named != step.drop and named in dict(p.roster) and named not in p.kept
    night, out = next_morning(setup, state, decision, 3, False, {}, value)
    assert night.sends == {1: decision.sends} and placed_on(night) == [(step.add, step.drop)]
    assert bool(night.claims.get(1)) == (way != "free_agent")
    assert set(out.active(1)) == set(state.active(1)) - {named, step.drop} | {back, step.add}
    assert out.held(1) == () and len(out.active(1)) == setup.spots()
    assert out.forced_by == {1: 1} == out.executed_by and not out.gone_by
    if way != "free_agent":
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(1, step.add, WON)]
    assert found(setup, night, out, {}) == []
    # As PR G made the name: the step's drop leaves for the return, and the step is gone.
    night, lost = next_morning(setup, state, replace(decision, sends=as_g), 3, False, {}, value)
    assert step.add not in lost.active(1) and named in lost.active(1)
    assert lost.forced_by == {1: 1} == lost.gone_by and not lost.executed_by


@pytest.mark.parametrize(("waivers", "way"), (*ARRIVALS, *LATE))
def test_an_arm_that_executes_its_plan_names_with_the_set_and_the_step_due_made(waivers, way):
    """The same refit for the arm that executes its plan beside its set (``execute_plan``),
    every way an add arrives. PR G's Monday (``test_sim_stash.return_day``), the decision by
    hand, so the seat weighs nothing and no format is named: no move in the set and a plan step
    that drops ``low`` for ``free``. With the set alone made the engine's plan charges ``low``
    for ``back``'s return; with the step made, ``nxt``. The executor keeps the names made with
    what it queues (``Decision.plan_sends``): ``nxt`` leaves for the return and the step lands
    on the roster it was planned on. A step that is a claim clearing the morning after next is
    dated then and is placed tonight (``policy.due_by``), so the names are made with it too:
    its drop is still on the roster when the claim is decided. With the set's own name ``low``
    left for the return and the step was gone."""
    setup, state, status, returns, back, low, nxt = stash.return_day(0)
    free = max(state.pool)
    setup = arriving(
        replace(setup, projection={**setup.projection, free: rates(0.5)}), waivers, way
    )
    # The day's state was made for a league without waivers: the priority order and the
    # dollars are day one's of the league as it now is.
    first = initial(setup)
    state = replace(state, priority=first.priority, dollars=first.dollars)
    tomorrow = state.day + DAY
    lands = tomorrow + DAY if way == "late_claim" else tomorrow
    if way in ("dropped_claim", "late_claim"):
        state = replace(state, waivers={free: Waiting(lands, 3)})
    built = policy.problem_of(setup, state, 1, dict(KNOBS), setup.projection, status, returns)
    p = built.problem
    step = mv.Move(free, low, lands)
    assert mv.feasible(p, (step,)) and not {low, nxt} & p.kept
    decision = policy.named(p, policy.Decision(plan=(step,), source="exact"))
    assert decision.sends == ((back, low),) and decision.plan_sends == ((back, nxt),)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    cleared = {low: "O"}
    night, out = next_morning(setup, state, decision, 1, True, cleared, value)
    assert night.sends == {1: ((back, nxt),)} and placed_on(night) == [(free, low)]
    assert bool(night.claims.get(1)) == (way != "free_agent")
    assert back in out.active(1) and nxt in out.pool and out.forced_by == {1: 1}
    assert found(setup, night, out, cleared) == []
    if way == "late_claim":
        # The claim is still open: its drop stayed for it, and it is won the morning after.
        assert low in out.active(1) and [c.move.add for c in out.claims[1]] == [free]
        before, out = out, replace(morning(setup, out, lands, cleared, value), day=lands)
        assert found(setup, before, out, cleared) == []
    assert set(out.active(1)) == set(state.active(1)) - {nxt, low} | {back, free}
    assert out.executed_by == {1: 1} and not out.gone_by and out.forced_by == {1: 1}
    if way != "free_agent":
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(1, free, WON)]
    # With the set's own name (an arm that queues no step keeps it): ``low`` leaves for the
    # return, and the step finds its drop gone.
    plain = replace(decision, plan_sends=None)
    night, lost = next_morning(setup, state, plain, 1, True, cleared, value)
    assert night.sends == {1: ((back, low),)} and low in lost.pool
    if way == "late_claim":
        lost = replace(morning(setup, lost, lands, cleared, value), day=lands)
    assert free not in lost.active(1) and nxt in lost.active(1)
    assert lost.gone_by == {1: 1} and not lost.executed_by


def monday(lines, waivers: str = "none", way: str = "free_agent"):
    """PR G's Monday (``test_sim_stash.return_day``: ``back`` in the IL slot and told back, the
    six active spots full, ``low`` and ``nxt`` the two weakest; neither is kept), the wire's last
    free agents given the rates ``lines`` in order, in a league where an add arrives ``way``
    (a ``dropped_claim``: each of those free agents was dropped by another team and clears
    tomorrow). The setup, the state, the seat's problem, ``back``, ``low``, ``nxt``, ``third``
    (the least valuable of the other four) and those free agents."""
    setup, state, status, returns, back, low, nxt = stash.return_day(0)
    wire = sorted(state.pool, reverse=True)[: len(lines)]
    projection = {**setup.projection, **{k: rates(x) for k, x in zip(wire, lines, strict=True)}}
    setup = arriving(replace(setup, projection=projection), waivers, way)
    # The day's state was made for a league without waivers: the priority order and the
    # dollars are day one's of the league as it now is.
    first = initial(setup)
    state = replace(state, priority=first.priority, dollars=first.dollars)
    if way == "dropped_claim":
        state = replace(state, waivers={k: Waiting(state.day + DAY, 3) for k in wire})
    built = policy.problem_of(setup, state, 1, dict(KNOBS), setup.projection, status, returns)
    p = built.problem
    third = min((k for k, _ in p.roster if k not in (low, nxt)), key=lambda k: (p.value[k], str(k)))
    assert not {low, nxt, third} & p.kept and p.value[low] < p.value[nxt] < p.value[third]
    return setup, state, p, back, low, nxt, third, wire


def test_the_names_of_an_arm_that_executes_its_plan_take_the_set_s_move_and_no_later_step():
    """The rule as it is written, each part held by a name that moves with it (the decision by
    hand on PR G's Monday, so the seat weighs nothing and no format is named). The three weeks'
    set swaps ``low`` for a free agent, a plan step due tomorrow swaps ``nxt`` for another, and
    a step dated the day after swaps ``third`` for one more; each add is worth more than the
    roster's bottom four. For ``back``'s return the engine's plan charges ``nxt`` with the set
    alone made (``Decision.sends``, PR G's name), ``low`` with the step alone made, ``third``
    with both made, and the next player up with the later step made too. The names an arm that
    executes its plan keeps are the third: the set's move is in the list and the later step is
    not. The morning sends ``third`` and both queued moves land; the later step was not queued.
    With the set's own name, or the step's alone, the named player is a queued move's drop: he
    leaves for the return and that move is gone."""
    setup, state, p, back, low, nxt, third, (a, b, c) = monday((1.5, 2.0, 2.5))
    tomorrow = state.day + DAY
    in_set, step = mv.Move(a, low), mv.Move(b, nxt, tomorrow)
    later = mv.Move(c, third, tomorrow + DAY)
    assert mv.feasible(p, (in_set, step, later))
    assert p.value[third] < min(p.value[k] for k in (a, b, c))
    decision = policy.named(p, policy.Decision(moves=(in_set,), plan=(step, later), source="exact"))
    alone, of_step = policy.sends_of(p, [in_set]), policy.sends_of(p, [step])
    assert decision.sends == alone == ((back, nxt),) and of_step == ((back, low),)
    assert decision.plan_sends == policy.sends_of(p, [in_set, step]) == ((back, third),)
    with_later = policy.sends_of(p, [in_set, step, later])
    assert with_later not in (decision.plan_sends, alone, of_step)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    cleared = {low: "O"}
    night, out = next_morning(setup, state, decision, 3, True, cleared, value)
    assert night.sends == {1: ((back, third),)} and placed_on(night) == [(a, low), (b, nxt)]
    assert set(out.active(1)) == set(state.active(1)) - {low, nxt, third} | {back, a, b}
    assert out.forced_by == {1: 1} and out.executed_by == {1: 2} and not out.gone_by
    assert found(setup, night, out, cleared) == []
    # With the set's own name, or the step's alone: a queued move's drop leaves for the return.
    for wrong in (alone, of_step):
        wrongly = replace(decision, plan_sends=wrong)
        _, lost = next_morning(setup, state, wrongly, 3, True, cleared, value)
        assert lost.forced_by == {1: 1} == lost.executed_by == lost.gone_by


#: A plan step due that cannot land beside a move of the set: it takes that move's add (the
#: executor queues one move an add), or its drop (the second to land finds the drop gone).
TWICE = ("one add twice", "one drop twice")


@pytest.mark.parametrize(("waivers", "way"), ARRIVALS)
@pytest.mark.parametrize("shape", TWICE)
def test_a_step_that_takes_an_earlier_move_s_add_or_drop_is_left_out_of_the_names(
    shape, waivers, way
):
    """The streaming plan is drawn against the week's set, so a step due can take the add or the
    drop of a move of the three weeks' set. Both cannot land: the names are made with the
    first move of the list that takes each add and each drop (``policy.distinct``), a list
    ``moves.feasible`` can pass, and the step is left out. PR G's Monday, the decision by hand
    (no format is named), every way an add arrives.

    One add twice: the set swaps ``low`` for the star, the step ``nxt`` for the star. The
    executor queues the set's move alone. With that move made the engine's plan charges
    ``nxt``; with both made it counts the star twice and charged ``third``, who then left
    while ``nxt`` stayed.

    One drop twice: the set swaps ``low`` for ``strong``, the step ``low`` for ``weak``, who is
    worth less than ``nxt``. With the set's move made the plan charges ``nxt``; with both made
    it charged ``weak``, the add of a step that cannot land, so the name was of nobody on the
    roster, the rule before sent ``low``, and the set's own move was lost with the step."""
    if shape == "one add twice":
        setup, state, p, back, low, nxt, third, (star,) = monday((3.0,), waivers, way)
        tomorrow = state.day + DAY
        in_set, step = mv.Move(star, low), mv.Move(star, nxt, tomorrow)
    else:
        setup, state, p, back, low, nxt, third, (strong, weak) = monday((0.5, 0.32), waivers, way)
        tomorrow = state.day + DAY
        in_set, step = mv.Move(strong, low), mv.Move(weak, low, tomorrow)
        assert p.value[low] < p.value[weak] < p.value[nxt] < p.value[strong]
    assert mv.feasible(p, (in_set,)) and mv.feasible(p, (step,))
    assert not mv.feasible(p, (in_set, step))
    decision = policy.named(p, policy.Decision(moves=(in_set,), plan=(step,), source="exact"))
    assert policy.gathered(decision, True, policy.due_on(p)) == ([in_set], [(step, 0)])
    whole = policy.sends_of(p, [in_set, step])
    assert decision.plan_sends == decision.sends == ((back, nxt),) != whole
    value = wk.per_game_values(setup.projection, setup.cats, None)
    cleared = {low: "O"}
    night, out = next_morning(setup, state, decision, 2, True, cleared, value)
    both = shape == "one drop twice" and way == "free_agent"
    queued = [(in_set.add, low), (step.add, low)] if both else [(in_set.add, in_set.drop)]
    assert night.sends == {1: ((back, nxt),)} and placed_on(night) == queued
    assert bool(night.claims.get(1)) == (way != "free_agent")
    # ``nxt`` leaves for the return and the set's move lands; a step queued beside it is gone.
    assert set(out.active(1)) == set(state.active(1)) - {low, nxt} | {back, in_set.add}
    assert out.forced_by == {1: 1} == out.executed_by
    assert out.gone_by == ({1: 1} if both else {})
    if way != "free_agent":
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(1, in_set.add, WON)]
    assert found(setup, night, out, cleared) == []
    # With the names made on the whole list, the step that cannot land counted in.
    _, lost = next_morning(
        setup, state, replace(decision, plan_sends=whole), 2, True, cleared, value
    )
    assert nxt in lost.active(1) and lost.forced_by == {1: 1}
    if shape == "one add twice":
        assert whole == ((back, third),) and third in lost.pool
    else:
        assert whole == ((back, step.add),) and low in lost.pool
        assert in_set.add not in lost.active(1) and not lost.executed_by


def plan_arm(executes: str = policy.QUEUE_SET, **knobs) -> rn.Arm:
    """An exact arm that executes ``executes`` with its streaming plan drawn and executed
    beside the set, among market rivals, three moves a day. Its plan floors are below zero, so
    it takes each plan the stream draws, as Rule 1's pair does (:func:`pair_digest`)."""
    knobs = {**KNOBS, "daily_cap": 3, "plan_floor_cats": -1.0, "plan_floor_points": -1.0, **knobs}
    return rn.Arm("P", "exact", knobs, {"kind": "market"}, executes, True, True)


#: The exact tier's own decisions of an arm that executes its plan beside its set, on a day of
#: :func:`held_back` in a three-week league that counts every category: the league's seed, the
#: day, and what the arm executes (found by ``~/sim-notes/vm/scratch/e/fix2/b1_own_decisions.py``).
OWN = {
    "a step that can land": (2, 1, policy.QUEUE_SET),
    "steps that repeat the set's adds": (3, 1, policy.QUEUE_SET),
    "weighted, steps that repeat the set's adds": (3, 11, policy.WEIGHTED),
}


@pytest.mark.parametrize("case", OWN)
def test_the_exact_tier_s_own_decision_carries_the_names_with_its_plan_s_steps_due(case):
    """The seat's own decision, not one made by hand: an exact arm that executes its streaming
    plan beside its set, on a day its held player is told back. ``policy.exact`` names with
    its plan: ``Decision.plan_sends`` is the engine's charge with the set's moves and the
    plan's steps due that can land together made, and the executor keeps it. One format, every
    category: a one-win league's plan floor is the engine's own, and in the made-up one-win
    seasons the stream draws no plan for the arm to execute.

    A step that can land: the set swaps one player and the step due another. Three names:
    with the set alone made, with the step alone made, and with both made, which charges the
    step's own add (the limit that stays: he has not arrived, the morning falls to the rule
    before, and a queued move finds its drop gone).

    Steps that repeat the set's adds, under ``three`` and under ``weighted``: the plan was
    drawn against the week's set and each of its steps due adds a player the three weeks' set
    adds. The executor queues the set's two moves and no step; the names are the set's own, a
    player on the roster; the morning sends him and both moves land. With the whole list made
    the engine charged an add of the set, and a queued move was lost."""
    seed, day, executes = OWN[case]
    setup = every_category(make_setup(seed=seed, weeks=3, playoff_weeks=1, held_slots=("IL",)))
    state, status, returns, back, value = held_back(setup, day)
    seat = plan_arm(executes)
    built = policy.problem_of(setup, state, 1, seat.knobs, setup.projection, status, returns)
    p = built.problem
    decision = policy.decide(built, "exact", executes, True)
    moves, steps = policy.gathered(decision, True, policy.due_on(p))
    assert moves and steps and decision.plan_sends is not None
    listed = [*moves, *(m for m, _ in steps)]
    together = policy.distinct(listed)
    assert decision.sends == policy.sends_of(p, moves)
    assert decision.plan_sends == policy.sends_of(p, together)
    ((held, named),) = decision.plan_sends
    assert held == back
    night, out = next_morning(setup, state, decision, 3, True, {}, value)
    assert night.sends == {1: decision.plan_sends}
    assert named not in {drop for _, drop in placed_on(night)}
    assert out.forced_by == {1: 1} and found(setup, night, out, {}) == []
    if case == "a step that can land":
        ((step, _),) = steps
        assert together == listed and placed_on(night) == [(m.add, m.drop) for m in listed]
        assert len({decision.sends, policy.sends_of(p, [step]), decision.plan_sends}) == 3
        assert named == step.add and out.executed_by == {1: 1} == out.gone_by
        return
    assert together == moves and placed_on(night) == [(m.add, m.drop) for m in moves]
    whole = policy.sends_of(p, listed)
    assert decision.plan_sends == decision.sends != whole and named in dict(p.roster)
    assert out.executed_by == {1: len(moves)} and len(moves) == 2 and not out.gone_by
    left, came = {named, *(m.drop for m in moves)}, {back, *(m.add for m in moves)}
    assert set(out.active(1)) == set(state.active(1)) - left | came
    # With the names made on the whole list: an add of the set is charged, and a move is lost.
    _, lost = next_morning(setup, state, replace(decision, plan_sends=whole), 3, True, {}, value)
    assert lost.executed_by == {1: 1} == lost.gone_by


def first_takers(listed) -> list:
    """The test's own reading of the part of a list that can land together: a move stays when
    no move kept before it takes its add or its drop."""
    out: list = []
    for m in listed:
        if all(m.add != x.add and (m.drop is None or m.drop != x.drop) for x in out):
            out.append(m)
    return out


#: The seasons of an arm that executes its plan beside its set, by what each is played for:
#: the world's seed and path (found by ``~/sim-notes/vm/scratch/e/fix2/c1_seasons.py``).
PLAN_PATHS = {
    "a step due moves the name to another player of the roster": (1, 1),
    "a step due repeats the set's drop": (1, 2),
}


@pytest.mark.parametrize("what", PLAN_PATHS)
def test_an_arm_that_executes_its_plan_beside_its_set_plays_a_season_with_an_il_slot(what):
    """The arm's own decisions over a season: ``three`` with its streaming plan drawn and
    executed, six weeks with an IL slot and no waivers, every category (the one format in
    which the made-up seasons' stream draws a plan for the arm to execute: a one-win league's
    plan floor is the engine's own). The audit finds nothing. On every night the seat holds a
    player, the names the executor kept are the engine's charge on the seat's problem of that
    day with what it queues made: the set's moves and the plan's steps due, each add and each
    drop taken once. No name is the drop of a move queued that day, and a morning takes a name.

    On one path a night's step due moves the name off the set's own to another player of the
    roster. On the other a night's step due takes the drop of a move of the set: both are
    queued, the names are made with the set's move, and with the whole list made the engine
    would have charged the add of the step that cannot land."""
    setup = every_category(
        make_setup(teams=4, pool=12, weeks=6, playoff_weeks=1, held_slots=("IL",))
    )
    seat = plan_arm()
    result, days = season(setup, seat, PLAN_PATHS[what])
    assert result.breaches == () and any(r.decisions[1].plan for r in days)
    moved = repeated = 0
    for r in days:
        decision = r.decisions[1]
        names = r.state.sends.get(1, ())
        built = policy.problem_of(setup, r.state, 1, seat.knobs, r.beliefs, r.status, r.returns)
        p = built.problem
        if not p.held:
            assert names == (), r.day
            continue
        tomorrow = r.day + DAY
        moves, steps = policy.gathered(decision, True, lambda add, tomorrow=tomorrow: tomorrow)
        listed = [*moves, *(m for m, _ in steps)]
        together = first_takers(listed)
        assert names == policy.sends_of(p, together), r.day
        if steps and names != decision.sends and all(x in dict(p.roster) for _, x in names):
            moved += 1
        if len(together) < len(listed) and names != policy.sends_of(p, listed):
            repeated += 1
    assert names_on_a_queued_drop(days) == [] and stash.mornings_named(days)
    assert (moved if "moves the name" in what else repeated) >= 1, (moved, repeated)


def test_a_stash_threshold_and_a_leading_plan_s_step_both_reach_the_name():
    """An arm that names a stash threshold and executes ``queue``, on PR G's Monday with a free
    agent above everyone, the leading plan by hand: its step due tomorrow drops ``nxt`` for the
    star. With no threshold the plan with the step made charges ``low``, the least valuable,
    for ``back``'s return. At a threshold nobody clears ``low``, a returning player, is left out
    of the choice (the engine's ``guarded_pool``): made on the set alone the name is ``nxt``,
    the step's own drop (PR G's name); made with the step made it is ``third``, the weakest of
    the others. The morning sends him, the step lands, ``low`` stays, the audit finds nothing."""
    setup, state, status, returns, back, low, nxt = stash.return_day(0)
    star = max(state.pool)
    setup = replace(setup, projection={**setup.projection, star: rates(3.0)})
    step = mv.Move(star, nxt, state.day + DAY)
    names = {}
    for threshold in (None, stash.NEVER):
        knobs = {**KNOBS, "stash_threshold": threshold}
        built = policy.problem_of(setup, state, 1, knobs, setup.projection, status, returns)
        p = built.problem
        assert mv.feasible(p, (step,)) and mv.returning_net(p, low) is not None
        led = policy.Decision(plan=(step,), source="exact", plan_leads=True)
        names[threshold] = policy.named(p, led)
        assert names[threshold].plan_sends is None
    others = [k for k, _ in p.roster if k not in (low, nxt)]
    third = min(others, key=lambda k: (p.value[k], str(k)))
    assert third not in p.kept and p.value[third] < p.value[star]
    assert names[None].sends == ((back, low),)
    assert policy.sends_of(p) == ((back, nxt),) and names[stash.NEVER].sends == ((back, third),)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    cleared = {low: "O"}
    night, out = next_morning(setup, state, names[stash.NEVER], 1, False, cleared, value)
    assert night.sends == {1: ((back, third),)} and placed_on(night) == [(star, nxt)]
    assert set(out.active(1)) == set(state.active(1)) - {third, nxt} | {back, star}
    assert out.forced_by == {1: 1} == out.executed_by and not out.gone_by
    assert found(setup, night, out, cleared) == []


@pytest.mark.parametrize("h2h", FORMATS)
def test_an_arm_that_names_a_stash_threshold_and_executes_queue_plays_a_season(h2h):
    """The two together, the arm's own decisions over a season with an IL slot and waivers by
    priority, in both formats: the audit finds nothing, the queue takes plans, the seat names
    whom its held players send and a morning takes a name, the run's rows carry the stash count
    and the queue's, and no name is ever the drop of a move the seat queued that day (in the
    one-win season the name as PR G made it was, on one night; the other format's season has
    no such night). The threshold is read: the season at None is another one."""
    setup = waiving(make_setup(**SMALL, held_slots=("IL",)), "priority")
    setup = setup if h2h == ONE_WIN else every_category(setup)
    at_none, plain_days = season(setup, queue_arm(), THRESHOLD_PATH)
    at_share, days = season(setup, queue_arm(stash_threshold=stash.SHARE), THRESHOLD_PATH)
    assert at_none.breaches == at_share.breaches == ()
    row = at_share.counts[1]
    assert row["plan_days"] >= 1 and row["held_stints"] >= 1 and row["landed"] >= 1
    assert row["returning_dropped"] is not None and "returning_dropped" not in at_none.counts[1]
    assert list(row)[-3:] == [*ct.STASH, *ct.PLANS]
    assert stash.mornings_named(days)
    assert names_on_a_queued_drop(days) == [] == names_on_a_queued_drop(plain_days)
    assert [placed(r) for r in days] != [placed(r) for r in plain_days]


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_split_seat_names_on_its_own_table_with_its_queue_made(h2h):
    """The lesson of the draft PR's review again, for the names: a ``yahoo`` seat, which reads a
    free agent on one table and its roster on another, executes ``queue`` over a season with an
    IL slot, in both formats. The audit finds nothing; each night's names are the ones
    ``policy.named`` gives on the seat's own table of that day with what it queues made; on
    some night they are not the names made on the set alone (PR G's), and on some night the
    run's table would name another player; no name is the drop of a move queued that day, and a
    morning takes one."""
    setup = make_setup(teams=4, pool=12, weeks=6, playoff_weeks=1, held_slots=("IL",))
    setup = setup if h2h == ONE_WIN else every_category(setup)
    lines = recorded_lines(setup, 11)
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    seat = replace(
        arm("Y", "exact", "market", system="yahoo", daily_cap=3, **FLOORS), executes=policy.QUEUE
    )
    arms = ss.believing({"Y": seat}, split.SOURCES)
    label = arms["Y"].forecaster
    assert label in ss.splits_of(split.SOURCES, arms)
    w = split.world_of(setup, lines, first, split.second_of(first), arms)
    days, result = split.run(setup, w, split.variant_of(setup, arms, {1: "Y"}))
    assert result.breaches == () and any(r.decisions[1].plan_leads for r in days)
    named = [r for r in days if r.state.sends.get(1)]
    moved = apart = 0
    for r in named:
        decision = r.decisions[1]

        def names(table, r=r, decision=decision):
            built = policy.problem_of(setup, r.state, 1, seat.knobs, table, r.status, r.returns)
            fresh = policy.named(built.problem, replace(decision, sends=()))
            return fresh.sends, policy.sends_of(built.problem, decision.moves)

        own, on_the_set = names(r.held[label])
        assert own == r.state.sends[1] == decision.sends, r.day
        moved += own != on_the_set
        apart += names(r.beliefs)[0] != own
    assert named and moved and apart
    assert names_on_a_queued_drop(days) == [] and stash.mornings_named(days)


# --------------------------------------------------------------------------- Rule 1
def rounded(x):
    if isinstance(x, float):
        return round(x, 9)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [rounded(v) for v in x]
    return x


def pair_digest(setup) -> tuple[str, int]:
    """SHA-256 of a pair's whole task result (``run.paired``: both arms' outcomes, their
    difference, the solves, the moves, the counts of both arms and of the rivals, the breaches
    and the season scale, every key), each figure rounded to nine places: an exact arm that
    executes ``three`` with its streaming plan drawn and executed against one that executes
    ``weighted``, in seat 1 among market rivals through one world. With it, the days the first
    arm held a streaming plan.

    The pair's plan floors are below zero, so the first arm takes each plan the stream draws
    (as ``test_sim_knobs.py``'s read cases do) and the digest holds the executor's plan path. At
    ``KNOBS``' floor of 0 the every-category digest moved with the process's hash seed: a plan
    that ties its set was taken or not on a float's last bit."""
    knobs = {**KNOBS, "daily_cap": 3, "plan_floor_cats": -1.0, "plan_floor_points": -1.0}
    three = rn.Arm("A", "exact", knobs, {"kind": "market"}, policy.QUEUE_SET, True, True)
    weighted = rn.Arm("B", "exact", knobs, {"kind": "market"}, policy.WEIGHTED, False, False)
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    days: list[rn.DayRecord] = []
    out = rounded(rn.paired(setup, w, three, weighted, 1, on_day=days.append))
    planned = sum(1 for r in days if r.variant == 0 and r.decisions[1].plan)
    digest = hashlib.sha256(json.dumps(out, sort_keys=True, default=str).encode()).hexdigest()
    return digest, planned


#: Rule 1's pins: the pair of :func:`pair_digest` on two of :data:`KINDS` (one win by priority
#: with an IL slot; every category by FAAB under continuous waivers with an IL slot), as main
#: ``4b26577`` gave them (``~/sim-notes/vm/scratch/e/rule1_pins.py``, the same digest, run on a
#: copy of main's code and on this PR's tree, each under hash seeds 0 to 9: one value a league).
RULE1_ONE_WIN = "c439af76da05a93a1a938fedfac6ecee69cc511c17b88bd3293ea28724f17dc4"
RULE1_EACH = "e27288e2530c4b08ad248b7b3d1d04701551b7fb6f3e398dc564fa61f1373e75"


def test_rule_1_an_arm_that_does_not_name_queue_plays_as_main_s():
    """Arms that execute ``three`` and ``weighted`` give main's results, counts and keys, to the
    last key of the pair's record; and no row of such a run has the queue's counts. Where every
    category counts the first arm holds a streaming plan on some days and queues its steps, so
    the pin holds the executor's plan path as main's; a one-win league's plan floor is the
    engine's own, and no plan of that season clears it."""
    one, _ = pair_digest(KINDS["one win, priority, a dropped player waits, IL"]())
    each, planned = pair_digest(KINDS["every category, FAAB, continuous, IL"]())
    assert one == RULE1_ONE_WIN
    assert each == RULE1_EACH
    assert planned >= 1, "the pair's first arm held no streaming plan: the pin holds less"


def test_a_pair_s_rows_carry_the_queue_s_counts_only_when_an_arm_names_queue():
    """Which rows of a pair carry the queue's two keys: none when neither arm names ``queue``,
    every row (both arms' and the rivals') when one does, in one league or in two drafted apart,
    and the other arm's own figures do not move. One format is played, every category: which
    rows carry a key is the runner's bookkeeping and reads no format (the counts themselves are
    held in both formats by the league kinds' test above), and each pair here is two exact
    seasons, the file's dearest."""
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
