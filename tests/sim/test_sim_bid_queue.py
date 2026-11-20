"""The bid policy beside the queue's rule (#172, PR F2 built on PR E). The two PRs meet in the
executor: under the queue's rule a leading plan's steps are queued and none of the set's moves,
while the decision's basis still carries the set's gains (the day's recommended moves, the
fortnight's typical gain). So a claim's place in the queue is not its place among the
decision's moves, and the executor tells the bid policy which claim is a plan's step: a step
keeps today's value, its own score over the three weeks' typical, and never reads the set's
gains on the week or the season.

And in the reads table: an arm whose ``bid`` gives the three weeks no weight reads no plan
floor as its typical gain, but one that executes ``queue`` still reads its league's floor, the
gate a week plan clears (the lead's a-8 to PR F2).

Made-up leagues, fixed seeds. No test here pins a literal outcome of a replay."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import counts as ct
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY
from pickandroll.sim.shapes import CONTINUOUS
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, make_setup
from tests.sim.test_sim_bid_seasons import EVERY_KEY
from tests.sim.test_sim_queue import DAY, KINDS, built_on, cats, faab, leading, queue_arm, season
from tests.sim.test_sim_screen import EVERY, base, rows

#: Blocks that give the three weeks no weight, and one that gives them some.
NO_THREE_BLOCKS = ({"week": 1}, {"week": 0.5, "season": 0.5})
ON_THE_WEEK = bp.of({"week": 1.0})


def claims_by_faab(setup):
    """``setup`` by FAAB with every add a claim (continuous waivers)."""
    return replace(setup, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)


# --------------------------------------------------------------------------- the executor
def test_a_leading_plan_s_claim_is_a_step_s_to_the_bid_policy_whatever_the_set_holds():
    """By hand, on PR E's decision whose plan leads beside a set of one move: the block weighs
    the week alone, and the set's one move loses on the week. The claim placed is the plan's
    first step, valued and sized as a step: its own score over the three weeks' typical. Read
    as the set's move in the same place of the queue it would be worth nothing (the set's
    move's week gain), and bid the routine. The fortnight keeps the set's gains, on the three
    weeks and on the week."""
    setup = claims_by_faab(make_setup())
    state, decision, in_set, first, _ = leading(setup)
    basis = policy.Basis(policy.LIVE, (2.0,), (6.0, 9.0), None, 1.0, bid=ON_THE_WEEK, week=(-5.0,))
    led = replace(decision, basis=basis)
    queued = policy.queue(state, 1, led, 3, 4, False, setup.spots(), setup)
    (claim,) = queued.claims[1]
    assert (claim.move.add, claim.move.drop) == (first.add, first.drop)
    dollars = state.dollars[1]
    typical = policy.typical_gain([2.0], 1.0)[0]
    as_step = bp.Seen(6.0, typical, dollars, None, True, budget=setup.budget)
    assert (claim.bid, claim.value) == (bp.amount(ON_THE_WEEK, as_step), 6.0 / typical)
    as_set = bp.Seen(6.0, typical, dollars, None, False, week=-5.0, budget=setup.budget)
    assert bp.value(ON_THE_WEEK, as_set) == 0.0
    assert claim.bid > ON_THE_WEEK.routine == bp.amount(ON_THE_WEEK, as_set)
    assert queued.recent[1] == ((state.day, 2.0),)
    assert queued.recent_by[bp.WEEK][1] == ((state.day, -5.0),)
    # With no plan leading and the arm executing its plan, the set's move comes first and reads
    # its own week gain; the step after it is still a step.
    beside = policy.queue(
        state, 1, replace(led, plan_leads=False), 3, 4, True, setup.spots(), setup
    )
    own, step = beside.claims[1]
    assert (own.move.add, step.move.add) == (in_set.add, first.add)
    assert (own.bid, own.value) == (ON_THE_WEEK.routine, 0.0)
    assert (step.bid, step.value) == (claim.bid, claim.value)
    # An arm that names no block bids the live rule on the step's score, as PR E has it, and
    # its claim's value is the same step's.
    bare = policy.queue(
        state, 1, replace(led, basis=replace(basis, bid=None, week=())), 3, 4, False,
        setup.spots(), setup,
    )  # fmt: skip
    (plain,) = bare.claims[1]
    assert plain.bid == policy.live_bid(6.0, [2.0], 1.0, setup.budget, None)
    assert plain.value == claim.value


@pytest.mark.parametrize("weight", [0.0, 0.33])
def test_on_a_day_the_queue_takes_a_plan_each_claim_is_sized_on_its_step_s_score(weight):
    """The same through the tier's own decision, on PR E's league of three weeks by FAAB with
    every add a claim: on its fourth day the queue takes a plan of two steps while the three
    weeks' set holds two moves. An arm whose block weighs the week alone places the plan's two
    claims, each worth its step's score over the plan floor (the seat's typical until ten
    moves), which moves with the queue's weight; neither is worth the set's move's week gain in
    the same place of the queue, which before a tenth move counts one typical at most."""
    setup = replace(faab(cats()), waiver_rule=CONTINUOUS)
    built = built_on(setup, day=3, three_weight=weight)
    decision = policy.with_bid(built, policy.decide(built, "exact", policy.QUEUE), ON_THE_WEEK)
    basis = decision.basis
    assert decision.plan_leads and len(decision.moves) == 2 and basis is not None
    assert len(basis.week) == 2 and len(basis.plan) == len(decision.plan) == 2
    state = replace(initial(setup), day=setup.start + 3 * DAY)
    queued = policy.queue(state, 1, decision, 3, 4, False, setup.spots(), setup)
    claims = queued.claims[1]
    assert [(c.move.add, c.move.drop) for c in claims] == [(m.add, m.drop) for m in decision.plan]
    assert basis.floor > 0
    worth = [score / basis.floor for score in basis.plan]
    assert [c.value for c in claims] == pytest.approx(worth)
    assert all(v > 1.5 for v in worth)
    for c, score in zip(claims, basis.plan, strict=True):
        seen = bp.Seen(score, basis.floor, state.dollars[1], None, True, budget=setup.budget)
        assert c.bid == bp.amount(ON_THE_WEEK, seen) > ON_THE_WEEK.routine


# --------------------------------------------------------------------------- the reads table
def test_an_arm_that_executes_queue_reads_its_plan_floor_whatever_its_bid_weighs():
    """The lead's a-8 to PR F2, at the refit on PR E. In a FAAB league that counts every
    category, an arm whose ``bid`` gives the three weeks no weight reads no plan floor for a
    move of its set (``policy.NO_THREE``): true of an exact arm that executes a set and no week
    plan. An arm that executes ``queue`` reads the floor all the same, as the gate a week plan
    clears, and so does one that executes its streaming plan. Two ``queue`` arms apart only on
    the floor are two seats; two arms that execute the set are one, refused by name."""
    every = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    points = policy.Shape(scoring="points", waivers="faab")
    for block in NO_THREE_BLOCKS:
        rule = bp.of(block)
        assert rule.three == 0
        for shape, name in ((every, "plan_floor_cats"), (points, "plan_floor_points")):
            on_set = rn.Arm("T", "exact", KNOBS, {}, bid=rule)
            queue = replace(on_set, name="Q", executes=policy.QUEUE)
            planned = replace(on_set, name="P", execute_plan=True)
            assert policy.reads(on_set, shape)[name] == policy.NO_THREE
            assert policy.reads(replace(on_set, with_plan=False), shape)[name] == policy.NO_THREE
            assert policy.reads(queue, shape)[name] == policy.READ
            assert policy.reads(planned, shape)[name] == policy.READ
            # The queue arm's row is what it is with no block at all.
            assert policy.reads(queue, shape) == {
                **policy.reads(replace(queue, bid=None), shape),
                "playoff_weight": policy.reads(queue, shape)["playoff_weight"],
            }
            apart = {**KNOBS, name: float(KNOBS[name]) + 0.05}
            assert rn.same_seat(queue, replace(queue, name="B", knobs=apart), [shape]) is None
            (why,) = rn.same_seat(on_set, replace(on_set, name="B", knobs=apart), [shape])
            assert why.startswith(f"{name} ({policy.NO_THREE}; read by ")


def test_the_screen_s_floor_rows_under_queue_are_played_from_a_baseline_whose_bid_weighs_no_three():
    """The screen, by FAAB where every category counts, from a baseline whose ``bid`` gives
    the three weeks no weight: the floor's rows under ``queue`` are played (both arms execute
    ``queue`` and keep the block), with no note about a seat's typical gain, which such a block
    never reads; from a baseline with no block the same rows carry the note."""
    for block, note in (({"week": 1}, None), (None, sc.PLAN_FAAB_NOTE)):
        spec = base() if block is None else base(bid=block)
        got = rows(spec, "plan_floor_cats")
        for key in ("plan_floor_cats-queue-down", "plan_floor_cats-queue-up"):
            r = got[key]
            assert (r.status, r.note) == (sc.PLAY, note), (key, block)
            a, b = rn.arm_of(r.a), rn.arm_of(r.b)
            assert a.executes == b.executes == policy.QUEUE
            assert a.bid == b.bid == (None if block is None else bp.of(block))
            assert rn.same_seat(a, b, [EVERY]) is None


# --------------------------------------------------------------------------- seasons
@pytest.mark.parametrize("kind", [k for k in KINDS if "FAAB" in k])
def test_a_queue_arm_that_names_a_block_plays_a_season_by_faab_and_the_audit_finds_nothing(kind):
    """PR E's FAAB league kinds, once each, with the queue arm naming a block with every key:
    the audit finds nothing, the queue takes a plan on some day, and the seat's row holds both
    PRs' counts. On a day a plan leads every claim placed is a step of that day's plan, and its
    value is the step's own: its score over the seat's typical gain on the three weeks that
    day, whatever the set's moves gain on the week or the season. Under continuous waivers,
    where every add is a claim, some step of a leading plan is a claim."""
    setup = KINDS[kind]()
    arm = replace(queue_arm(), bid=bp.of(EVERY_KEY))
    result, days = season(setup, arm)
    assert result.breaches == ()
    row = result.counts[1]
    assert set(ct.PLANS) <= set(row) and set(ct.PACING) <= set(row)
    led = [r for r in days if r.decisions[1].plan_leads]
    assert led and row["plan_days"] == len(led)
    seen = 0
    for r in led:
        d = r.decisions[1]
        assert d.basis is not None and d.basis.bid == arm.bid
        assert len(d.basis.week) == len(d.basis.season) == len(d.moves)
        steps = [(m.add, m.drop) for m in d.plan]
        # The state of the record is the day's after the queue: its fortnight counts today's.
        typical = policy.typical_gain([x for _, x in r.state.recent[1]], d.basis.floor)[0]
        for c in r.claims.get(1, ()):
            j = steps.index((c.move.add, c.move.drop))
            as_step = bp.Seen(d.basis.plan[j], typical, 0.0, None, True)
            assert c.value == pytest.approx(bp.value(arm.bid, as_step)), (r.day, j)
            seen += 1
    if "continuous" in kind:
        assert seen >= 1, "no step of a leading plan was a claim on any day"
        assert row["claims_placed"] >= 1, row
