"""The bracket's opponent through the runner (#172, PR bracket): the decision cache's key holds
a team's view of its week for a strategy that reads the week, and for no other; the seasons that
play a round. The pure pairs, the state's and the audit's rule are ``test_sim_bracket.py``'s.

Every league is made up and every seed fixed. Each season's test names its time below."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from functools import cache
from itertools import product

import numpy as np
import pytest

from pickandroll.sim import audit, nopeek, policy
from pickandroll.sim import league as lg
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_no_peek import SEED, WEIGHTS, recorded
from tests.sim.test_sim_knobs import weakened
from tests.sim.test_sim_league import totals
from tests.sim.test_sim_points import TABLE
from tests.sim.test_sim_split import armed, second_of, variant_of, world_of

FORMATS = ("one_win", "each_category")


def final_league(format_: str = "one_win", **kw):
    """Four teams, every one against every other over three weeks, then a final between the top
    two in week four; in either head-to-head format."""
    setup = make_setup(teams=4, weeks=4, playoff_weeks=1, playoff_teams=2, **kw)
    return setup if format_ == "one_win" else every_category(setup)


# --------------------------------------------------------------------------- who reads the week
def seats():
    """A seat of every tier, executed set and plan choice."""
    return [
        op.Seat("S", tier, dict(KNOBS), executes, with_plan)
        for tier, executes, with_plan in product(policy.TIERS, policy.EXECUTES, (False, True))
    ]


def rivals():
    return [
        op.Static(),
        op.of({"kind": "market", "rate": 1.0}, KNOBS, 0.1),
        op.of({"kind": "market", "rate": 1.0, "view": "season", "among": 2}, KNOBS, 0.1),
        op.Mirror(dict(KNOBS)),
    ]


def rounds_league(format_: str = "one_win", **kw):
    """Four teams over three weeks, then all four in a bracket of two rounds (weeks four and
    five): on a day of the first round a seat still has a later week to weigh."""
    setup = make_setup(teams=4, weeks=5, playoff_weeks=2, playoff_teams=4, **kw)
    return setup if format_ == "one_win" else every_category(setup)


ME = 4


def three_views(setup, number: int = 4):
    """Three states of :func:`rounds_league` equal in ``key()`` on the Thursday of week
    ``number`` (a day the surrogate solves; week four is the first round, with a later week to
    weigh, week five the final, the season's last week), whose views of the week are apart in
    everything the week's span reads: team 4 plays team 1 and trails, plays team 2 and leads,
    or plays nobody and no total is in (the blind week a bracket's was before PR bracket)."""
    day = setup.calendar.weeks[number - 1].start + timedelta(3)
    base = replace(initial(setup), day=day)
    first, second = (((4, 1), (2, 3)), ((4, 2), (1, 3))) if number == 4 else (((4, 1),), ((4, 2),))
    one = replace(base, totals={number: {4: totals(40.0), 1: totals(50.0)}}, seeded={number: first})
    two = replace(
        base, totals={number: {4: totals(55.0), 2: totals(35.0)}}, seeded={number: second}
    )
    assert one.key() == two.key() == base.key()
    views = [policy.week_view(setup, s, ME, number) for s in (one, two, base)]
    assert len(set(views)) == 3 and [v.opponent for v in views] == [1, 2, None]
    return one, two, base


def decided(strat, setup, state, team: int = ME) -> policy.Decision:
    g = np.random.default_rng(7)
    return strat.decide(setup, state, team, setup.projection, {}, {}, g)


#: The cases of the test below: the league's waivers and the week the states are in. A league
#: without waivers gives no decision a basis to bid on, so the first round is asked again under
#: FAAB with continuous waivers, where every decision of a tier that bids carries one; and the
#: final is the season's last week, in which the three weeks hold nothing and a rule may branch.
VIEWS = {"round one": ("none", 4), "round one, FAAB": ("faab", 4), "the final, FAAB": ("faab", 5)}


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("case", sorted(VIEWS))
def test_only_a_strategy_that_says_it_reads_the_week_decides_on_the_weeks_view(case, format_):
    """Held by behaviour, not by a list: every strategy the simulator seats decides on three
    states that share a ``key()`` and differ in the week's opponent and totals (two pairs, and
    the blind week). One that does not say it reads the week gives the same decision on all
    three, its bid's basis included, so the cache may share it. A kind added later that reads
    the week and does not say so fails here: in the first round of two, in a FAAB league, or in
    the season's last week. Of those that say it, the weighted set differs on the two pairs in
    the first round, and in the final moves against either opponent and not at all in the blind
    week (only decisions the test asserts on are made); the week's plan is searched on the week
    too (``policy.exact``), and no plan is drawn on these states. About 1.5 s each."""
    waivers, number = VIEWS[case]
    setup = rounds_league(format_)
    if waivers == "faab":
        setup = replace(setup, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)
    one, two, blind = three_views(setup, number)
    # The pool's first player is the market's darling, so a market rival has a move to make.
    setup = replace(setup, market={**setup.market, min(one.pool): 99.0})
    kinds = {
        c
        for c in vars(op).values()
        if isinstance(c, type) and c.__module__ == op.__name__ and "decide" in vars(c)
    } - {op.Strategy}
    made = [*rivals(), *seats()]
    assert {type(s) for s in made} == kinds, "a strategy kind this test does not seat"
    moved, based = set(), 0
    for strat, team in product(made, setup.teams):
        if not rn._reads_week(strat):
            a, b, c = (decided(strat, setup, state, team) for state in (one, two, blind))
            assert a == b == c, (strat, team)
            based += a.basis is not None
            if a.moves:
                moved.add((strat.kind, getattr(strat, "tier", None)))
        elif strat.executes == policy.WEIGHTED and team == ME:
            a, b = decided(strat, setup, one, team), decided(strat, setup, two, team)
            assert a.moves and b.moves, strat
            if number == 4:
                assert a != b, strat
            else:
                # The last week is all the weighted set weighs: with nobody to play it is
                # worth nothing and the set is empty, where against either opponent it is not.
                assert not decided(strat, setup, blind, team).moves, strat
    # Not an empty promise: of those that do not read the week, a market rival and the ranking
    # move on these states in either week; with a later week to weigh, the mirror and a seat of
    # the other two tiers too (in the season's last week the three weeks hold nothing to gain).
    assert moved >= {("market", None), ("seat", "ranking")}
    if number == 4:
        assert moved >= {("mirror", None), ("seat", "exact"), ("seat", "surrogate")}
    assert (based > 0) == (waivers == "faab")
    # Who says it reads the week: the exact tier's weighted set, and the exact tier with a plan.
    assert [(s.tier, s.executes, s.with_plan) for s in seats() if s.reads_week] == [
        ("exact", "three", True),
        ("exact", "weighted", False),
        ("exact", "weighted", True),
    ]
    assert not any(rn._reads_week(r) for r in rivals())


def test_the_decision_key_holds_the_weeks_view_for_a_seat_that_reads_the_week_and_no_other():
    setup = rounds_league()
    one, two, _ = three_views(setup)
    for strat in [*rivals(), *seats()]:
        k1, k2 = (rn.decision_key(setup, s, ME, strat, 4) for s in (one, two))
        assert k1[:3] == k2[:3] == (ME, repr(strat), one.key())
        if rn._reads_week(strat):
            assert k1[3] == policy.week_view(setup, one, ME, 4) != k2[3]
            assert k2[3] == policy.week_view(setup, two, ME, 4)
        else:
            assert k1 == k2 and k1[3] is None
    # Two arms of one name, apart only in their rivals or in ``execute_plan``, are one seat to
    # the cache; on one view they share (as the same arm twice does), on two they do not.
    a = rn.Arm("S", "exact", dict(KNOBS), {"kind": "static"}, policy.WEIGHTED)
    for b in (replace(a, opponents={"kind": "market"}), replace(a, execute_plan=True)):
        assert a != b and repr(a.seat()) == repr(b.seat())
        ka, kb = (rn.decision_key(setup, one, ME, arm.seat(), 4) for arm in (a, b))
        assert ka == kb
        assert ka != rn.decision_key(setup, two, ME, b.seat(), 4)
    # A team's view is its own: another pair's totals this week are no part of it.
    other = replace(one, totals={4: {**one.totals[4], 2: totals(33.0)}})
    assert policy.week_view(setup, other, ME, 4) == policy.week_view(setup, one, ME, 4)
    assert policy.week_view(setup, one, ME, 4) == policy.WeekView(
        1, tuple(totals(40.0).items()), tuple(totals(50.0).items())
    )
    # A team in no pair has no opponent's totals; a points league's view is each side's score.
    assert policy.week_view(setup, replace(one, seeded={}), ME, 4).so_far_theirs is None


# --------------------------------------------------------------------------- two arms, one name
@dataclass(frozen=True)
class Script:
    """A rival that makes the one swap it is told, on the day it is told."""

    day: object
    add: int
    drop: int
    kind: str = "script"

    def decide(self, setup, state, team, beliefs, status, returns, g):
        if state.day != self.day:
            return policy.NONE
        return policy.Decision((mv.Move(self.add, self.drop),), (), (), 0, self.kind)


def lockstep(setup, w, variants, plans, me, monkeypatch):
    """The variants through ``w`` in lockstep: the results, each day's record by variant, and
    the keys ``me``'s decision was looked up under, by day, in the variants' order."""
    keys: dict = {}
    real = rn.decision_key

    def spy(setup_, state, team, strat, week):
        key = real(setup_, state, team, strat, week)
        if team == me:
            keys.setdefault(state.day, []).append(key)
        return key

    recs: dict = {}
    with monkeypatch.context() as mp:
        mp.setattr(rn, "decision_key", spy)
        results = rn.simulate(
            setup, w, variants, plans, on_day=lambda r: recs.__setitem__((r.day, r.variant), r)
        )
    return results, recs, keys


def apart_on_one_state(keys) -> list:
    """The days the two variants' states agreed in what the cache keyed on before (the team, the
    seat, ``SimState.key()``) while their views of the week differed."""
    return [d for d, (a, b) in sorted(keys.items()) if a[:3] == b[:3] and a[3] != b[3]]


def own_decisions(setup, w, variants, plans, me, monkeypatch):
    """Each variant's season in lockstep is its season alone, day by day and at the end; the days
    of :func:`apart_on_one_state`, and those of them on which the two variants' seats decided
    differently (before the key held the view, the second was handed the first's)."""
    results, recs, keys = lockstep(setup, w, variants, plans, me, monkeypatch)
    for vi, (variant, plan) in enumerate(zip(variants, plans, strict=True)):
        (alone,), solo, _ = lockstep(setup, w, [variant], [plan], me, monkeypatch)
        for day in setup.days:
            if (day, vi) in recs:
                mine, theirs = recs[(day, vi)], solo[(day, 0)]
                assert mine.decisions == theirs.decisions, (vi, day)
                assert mine.state == theirs.state, (vi, day)
        assert results[vi].summaries == alone.summaries
        assert results[vi].result == alone.result
        assert results[vi].solves + results[vi].shared == alone.solves
    days = apart_on_one_state(keys)
    differ = [d for d in days if recs[(d, 0)].decisions[me] != recs[(d, 1)].decisions[me]]
    return results, recs, days, differ


#: The found paths of the test below (seed 5), each named for what the days the old key met are
#: apart in: the format, the league, the seat's team, the rival that swaps and the two days of
#: its swap (as days of the season).
ONE_NAME = {
    "totals": ("one_win", final_league, 3, 4, 0, 2),
    "in or out": ("each_category", final_league, 1, 4, 0, 4),
    "opponent": ("one_win", rounds_league, 2, 4, 0, 4),
}


@pytest.mark.parametrize("apart", sorted(ONE_NAME))
def test_two_arms_of_one_name_apart_in_their_rivals_each_decide_on_their_own_week(
    apart, monkeypatch
):
    """Two arms of one name whose seats are one ``repr``, apart only in their rivals: here one
    rival makes the same swap in both variants, on two different days. The variants' states
    part, then agree again in ``SimState.key()`` while a week's totals (and, by the standings,
    a round's pairs) differ. Before the key held the week's view the second variant was handed
    the first's decision on those days. Three found paths. ``totals``: the two seats meet one
    opponent in the final with different totals so far. ``in or out`` (every category): the two
    seasons seed different finals, one seat plays its final and the other is out of its own, and
    the states agree on the final's first morning. ``opponent`` (two rounds, all four teams in
    the first): on the first round's first morning both seats are in the round against two
    different teams with no total in yet, so the opponent alone tells the two views apart, and
    the two seats decide differently (one win; under every category the same grid found such
    mornings and none on which the two decisions differ). About 3 s each."""
    format_, league, me, rival, first, second = ONE_NAME[apart]
    setup = league(format_)
    base = initial(setup)
    add, drop = min(base.pool), base.active(rival)[0]
    a = rn.Arm("S", "exact", dict(KNOBS), {"kind": "static"}, policy.WEIGHTED, with_plan=False)
    b = replace(a, opponents={"kind": "script"})
    assert a != b and repr(a.seat()) == repr(b.seat()) and a.seat().reads_week
    static = {t: op.Static() for t in setup.teams}
    variants = [
        {**static, rival: Script(setup.days[day], add, drop), me: arm.seat()}
        for arm, day in ((a, first), (b, second))
    ]
    w = replay_of(setup, 5, 0)
    results, recs, days, differ = own_decisions(setup, w, variants, [False, False], me, monkeypatch)
    assert days, "on no day did the two states agree in key() on two views of the week"
    assert differ, "on no such day did the two seats decide differently"
    (ra, rb) = results
    assert not ra.breaches and not rb.breaches
    # What the two views are apart in on a day the two seats decided differently: the first
    # such day, or for ``opponent`` the first round's first morning (in that season the old key
    # also met days of a regular week, apart in their totals).
    weeks = lg.round_weeks(setup.spec)
    monday = setup.calendar.weeks[weeks[0] - 1].start
    day = monday if apart == "opponent" else differ[0]
    assert day in differ
    one, two = (
        policy.week_view(setup, recs[(day, vi)].state, me, setup.week_of(day).number)
        for vi in (0, 1)
    )
    if apart == "totals":
        assert all(setup.week_of(d).number in weeks for d in days)
        assert one.opponent == two.opponent is not None and one != two
    elif apart == "in or out":
        # The two seasons seeded different finals: one seat is in its own, the other is not.
        assert all(setup.week_of(d).number in weeks for d in days)
        assert ra.result.playoffs.seeds != rb.result.playoffs.seeds
        assert (one.opponent is None) != (two.opponent is None)
    else:
        assert None not in (one.opponent, two.opponent) and one.opponent != two.opponent
        assert one._replace(opponent=None) == two._replace(opponent=None)


def test_two_arms_of_one_name_apart_in_execute_plan_each_decide_on_their_own_week(monkeypatch):
    """The other pair of one ``repr``: two arms of one name apart only in ``execute_plan``. Both
    draw the week's plan, one executes it, so their seasons part by the seat's own moves, with
    no rival moving; by the final's first morning the two states agree again in
    ``SimState.key()`` while the standings, and so the final's pairs, differ: the arm that
    executes its plan plays its season's final, the other is out of its own. Before the key
    held the week's view the arm in the final was handed the other's decision there, made with
    no opponent at all. A pair of arms whose seasons seed different pairs: each arm's seat
    reads its own (its opponent, or nobody). A found path (seed 9, seat 4). One format, every
    category, with the plan floor under zero: under one win a plan must beat its set by the
    engine's own floor in the matchup's odds, and in these made-up leagues none does
    (``test_sim_knobs.py``'s note on its cases), so the two arms never part. About 2 s."""
    me = 4
    setup = weakened(final_league("each_category"))
    knobs = {**KNOBS, "plan_floor_cats": -1.0}
    a = rn.Arm("S", "exact", knobs, {"kind": "static"}, with_plan=True)
    b = replace(a, execute_plan=True)
    assert a != b and repr(a.seat()) == repr(b.seat()) and a.seat().reads_week
    assert rn.same_seat(a, b, [policy.shape_of(setup)]) is None  # the pair is not refused
    static = {t: op.Static() for t in setup.teams}
    variants = [{**static, me: arm.seat()} for arm in (a, b)]
    plans = [a.execute_plan, b.execute_plan]
    w = replay_of(setup, 9, 0)
    results, recs, days, differ = own_decisions(setup, w, variants, plans, me, monkeypatch)
    final = setup.calendar.weeks[-1]
    assert days and all(final.contains(d) for d in days)
    assert differ, "on no such day did the two seats decide differently"
    (ra, rb) = results
    assert not ra.breaches and not rb.breaches
    # They parted by the plan alone: only the second arm queued a step of one.
    assert ra.executed != rb.executed
    # Each season seeded its own final, and on the days the old key met, each seat read its own
    # opponent: the other team of its own season's final, or nobody when it is not in it.
    met = []
    for vi, res in enumerate(results):
        ((pair,),) = end_pairs(res.result)
        mine = next(iter(set(pair) - {me})) if me in pair else None
        for day in days:
            assert policy.opponent_of(setup, recs[(day, vi)].state, me, final.number) == mine
        met.append(mine)
    assert met[0] is None and met[1] is not None


# --------------------------------------------------------------------------- Rule 1 and the bite
def played(setup, w, variants, plans=None, blind=False):
    """The variants through ``w``: the results and each day's record by variant. ``blind`` plays
    main's bracket week: no round is seeded (the runner's one line does nothing), so a week of
    the bracket has no opponent, and the audit reads the rules without the bracket's."""
    recs: dict = {}
    rules = audit.rules_of(setup.waivers, setup.waiver_rule) if blind else None
    with pytest.MonkeyPatch.context() as mp:
        if blind:
            mp.setattr(policy, "seed_round", lambda setup_, state, week: state)
        results = rn.simulate(
            setup,
            w,
            variants,
            plans,
            on_day=lambda r: recs.__setitem__((r.day, r.variant), r),
            rules=rules,
        )
    return results, recs


def unseeded(rec):
    """A day record less the round's pairs its state holds."""
    return replace(rec, state=replace(rec.state, seeded={}))


def no_week_readers(setup, me: int = 1):
    """Three variants whose every seat searches no week: the exact tier's recommended set with
    no plan among mirrors, the surrogate among market rivals, the ranking among static ones."""
    mirror = op.Mirror(dict(KNOBS))
    market = op.of({"kind": "market", "rate": 0.3}, KNOBS, 0.1)
    static = op.Static()
    seats_ = (
        (op.Seat("E", "exact", dict(KNOBS), with_plan=False), mirror),
        (op.Seat("U", "surrogate", dict(KNOBS)), market),
        (op.Seat("R", "ranking", dict(KNOBS)), static),
    )
    return [{**{t: rival for t in setup.teams}, me: seat} for seat, rival in seats_]


@pytest.mark.parametrize("format_", FORMATS)
def test_rule_1_a_season_whose_seats_search_no_week_is_the_blind_seasons(format_):
    """Rule 1 by construction: where no seat's decision reads the value of the week, a season
    with every round seeded is the season with none, key for key: the same decisions, queues,
    lineups and states every day (the pairs a state holds apart), the same solves and shared
    solves, summaries, counts and final. The audit, with its rule read, finds nothing.
    Two rounds, so a later round is seeded on standings a round has changed. About 3 s each."""
    setup = rounds_league(format_)
    w = replay_of(setup, 5, 0)
    variants = no_week_readers(setup)
    seeded, recs = played(setup, w, variants)
    blind, before = played(setup, w, variants, blind=True)
    assert recs.keys() == before.keys()
    for at, rec in recs.items():
        assert unseeded(rec) == before[at], at
    for mine, theirs in zip(seeded, blind, strict=True):
        assert mine == theirs and not mine.breaches
        assert mine.result is not None and len(mine.result.playoffs.rounds) == 2
    # Not an empty promise: the weighing seats' variants moved, in a round too (the ranking
    # among static rivals finds nothing to gain in this league), and the rounds were seeded.
    executed = [r.executed for r in seeded]
    assert executed[0] > 0 and executed[1] > 0, executed
    assert any(
        moves
        for (day, _), rec in recs.items()
        if setup.week_of(day).number in lg.round_weeks(setup.spec)
        for moves in rec.queued.values()
    )
    last = max(day for day, _ in recs)
    assert all(len(recs[(last, vi)].state.seeded) == 2 for vi in range(3))
    assert all(before[(last, vi)].state.seeded == {} for vi in range(3))


#: The found paths of the test below (seed 5), a format each: the league, the seat's team, the
#: rival that swaps (on the season's first day in one variant, on its fifth in the other) and
#: the mirror's chair. Under every category the league has two rounds, and the two variants
#: share the mirror's solve in both.
SHARED = {
    "one_win": (final_league, 1, 3, 4),
    "each_category": (rounds_league, 1, 2, 3),
}


@pytest.mark.parametrize("format_", FORMATS)
def test_rule_1_two_arms_share_a_rivals_solve_in_a_round_they_seed_differently(
    format_, monkeypatch
):
    """Why the round's pairs stay out of ``SimState.key()``. A pair of arms of two names on the
    three weeks' set (two surrogate seats) over one mirror, in two variants whose seasons part
    and agree again (one rival makes the same swap on two different days) with the standings,
    and so a round's pairs, apart. On a day of a round on which the mirror solves, the two
    states agree in ``key()`` and hold different pairs; the mirror reads neither the pairs nor
    the week, so the second variant takes the first's solve. ``solves`` and ``shared`` are the
    blind season's, variant by variant (a double with the pairs emptied, not a number), and so
    is every day's record. With the pairs in the key the second variant solves alone on those
    days and ``shared`` falls: this test then fails. A found path a format. About 2 s each."""
    league, me, rival, chair = SHARED[format_]
    setup = league(format_)
    base = initial(setup)
    add, drop = min(base.pool), base.active(rival)[0]
    rest = {**{t: op.Static() for t in setup.teams}, chair: op.Mirror(dict(KNOBS))}
    arms = [rn.Arm(name, "surrogate", dict(KNOBS), {"kind": "mirror"}) for name in "AB"]
    variants = [
        {**rest, rival: Script(setup.days[day], add, drop), me: arm.seat()}
        for arm, day in zip(arms, (0, 4), strict=True)
    ]
    assert not any(rn._reads_week(strat) for variant in variants for strat in variant.values())
    w = replay_of(setup, 5, 0)
    seeded, recs, keys = lockstep(setup, w, variants, [False, False], chair, monkeypatch)
    blind, before = played(setup, w, variants, blind=True)
    # The days of a round on which the mirror was looked up under one key in both variants,
    # solved, and the two states held different pairs for the round.
    weeks = lg.round_weeks(setup.spec)
    met = [
        day
        for day, (first, second) in sorted(keys.items())
        if setup.week_of(day).number in weeks
        and first == second
        and recs[(day, 0)].decisions[chair].solves
        and recs[(day, 0)].state.seeded != recs[(day, 1)].state.seeded
    ]
    counts = [(r.solves, r.shared) for r in seeded]
    assert counts == [(r.solves, r.shared) for r in blind]
    assert met, "on no day of a round was the mirror's solve shared across two sets of pairs"
    assert {setup.week_of(day).number for day in met} == set(weeks)
    assert counts[0][1] == 0 and counts[1][1] >= len(met)
    assert recs.keys() == before.keys()
    for at, rec in recs.items():
        assert unseeded(rec) == before[at], at
    for mine, theirs in zip(seeded, blind, strict=True):
        assert mine == theirs and not mine.breaches
    # Not an empty promise: the seats and the mirror moved, and the two seasons ended apart.
    assert all(r.executed > 1 for r in seeded)
    assert end_pairs(seeded[0].result) != end_pairs(seeded[1].result)


def planless(rec):
    """A day record less the round's pairs its state holds and less the plan each seat drew."""
    decisions = {t: replace(d, plan=()) for t, d in rec.decisions.items()}
    return replace(unseeded(rec), decisions=decisions)


def test_rule_1_the_default_arm_draws_a_plan_in_a_round_and_plays_the_blind_season():
    """Rule 1 for the one seat of its list whose day record does change: an arm's default, the
    exact tier on the three weeks' set that draws the week's plan and does not execute it. It
    reads the week, for the plan alone: in a round it plays, a plan is drawn where the blind
    week drew none (a found path, seed 5: the weakened seat reaches the final and draws one
    there). No step of it is queued, so the season is the blind one's: every day's record but
    for the plan drawn (and the pairs the state holds), the same solves and shared solves,
    summaries, counts and final. One format, every category, the plan floor under zero: under
    one win no plan of a made-up league clears the engine's floor in the matchup's odds
    (``test_sim_knobs.py``'s note on its cases), so there the record does not change at all.
    About 2 s."""
    me = 1
    setup = weakened(final_league("each_category"))
    arm = rn.Arm("D", "exact", {**KNOBS, "plan_floor_cats": -1.0}, {"kind": "static"})
    assert arm.with_plan and not arm.execute_plan and arm.seat().reads_week
    variant = {**{t: op.Static() for t in setup.teams}, me: arm.seat()}
    w = replay_of(setup, 5, 0)
    (seeded,), recs = played(setup, w, [variant], [arm.execute_plan])
    (blind,), before = played(setup, w, [variant], [arm.execute_plan], blind=True)
    assert seeded == blind and not seeded.breaches and seeded.executed > 0
    final = setup.calendar.weeks[-1]
    ((pair,),) = end_pairs(seeded.result)
    assert me in pair
    assert recs.keys() == before.keys()
    for (day, vi), rec in recs.items():
        if day < final.start:
            assert rec == before[(day, vi)], day
        assert planless(rec) == planless(before[(day, vi)]), day
    days = sorted(day for day, _ in recs if final.contains(day))
    assert any(recs[(day, 0)].decisions[me].plan for day in days)
    assert not any(before[(day, 0)].decisions[me].plan for day in days)


def test_what_a_run_shares_and_solves_is_the_same_but_for_two_arms_of_one_name(monkeypatch):
    """The key's view moves no count where no two variants hold one seat on two views: a room,
    and a pair of two names over one mirror (the second arm draws no plan; both read the week),
    share and solve as they did under the old key, and the pair does share its mirrors' solves;
    the same arm twice shares every decision, in the final too. One format: no decision is
    compared, only who is asked to decide. About 7 s."""
    setup = final_league()
    w = replay_of(setup, 5, 0)
    a = rn.Arm("A", "exact", dict(KNOBS), {"kind": "mirror"}, policy.WEIGHTED)
    b = replace(a, name="B", with_plan=False)
    assert a.seat().reads_week and b.seat().reads_week
    assert repr(rn.opponents_of(setup, a, 1)) == repr(rn.opponents_of(setup, b, 1))

    def counts(variants):
        return [
            (r.solves, r.shared, r.summaries, r.result) for r in rn.simulate(setup, w, variants)
        ]

    room = [{1: a.seat(), 2: b.seat(), 3: op.Mirror(dict(KNOBS)), 4: op.Static()}]
    pair = [{**rn.opponents_of(setup, arm, 1), 1: arm.seat()} for arm in (a, b)]
    twice = [pair[0], pair[0]]
    now = [counts(v) for v in (room, pair, twice)]
    monkeypatch.setattr(rn, "_reads_week", lambda strat: False)
    assert [counts(v) for v in (room, pair, twice)] == now
    # The pair of two names: the second variant took solves of the first (the mirrors').
    assert now[1][0][1] == 0 and now[1][1][1] > 0
    (first, second) = now[2]
    assert second[0] == 0 and second[1] == first[0] > 0 and second[2:] == first[2:]


@pytest.mark.parametrize("format_", FORMATS)
def test_it_bites_a_finalist_that_weighs_the_week_queues_on_its_opponent_in_the_final(format_):
    """The weighted set among static rivals, a team at a time, against the blind season. Before
    the final the two are one season (no bracket week has been met). A team out of the final
    reads no opponent either way, and its whole season is the blind one's. A finalist reads the
    other finalist: in the final its problem's week has an opponent on every day, where the
    blind one has none, and (a found path, seed 5) at least one finalist queues differently
    there. About 5 s each."""
    setup = final_league(format_)
    w = replay_of(setup, 5, 0)
    final = setup.calendar.weeks[-1]
    static = {t: op.Static() for t in setup.teams}
    bit = []
    for me in setup.teams:
        seat = op.Seat("W", "exact", dict(KNOBS), policy.WEIGHTED, with_plan=False)
        (seeded,), recs = played(setup, w, [{**static, me: seat}])
        (blind,), before = played(setup, w, [{**static, me: seat}], blind=True)
        assert not seeded.breaches
        for (day, vi), rec in recs.items():
            if day < final.start:
                assert rec == before[(day, vi)], (me, day)
        (((hi, lo, _),),) = seeded.result.playoffs.rounds
        finalists = {seeded.result.playoffs.seeds[hi], seeded.result.playoffs.seeds[lo]}
        days = [day for day, _ in recs if final.contains(day)]
        assert len(days) == 7
        if me not in finalists:
            assert all(unseeded(recs[(d, 0)]) == before[(d, 0)] for d in days)
            assert seeded == blind
            continue
        (other,) = finalists - {me}
        for day in days:
            assert policy.opponent_of(setup, recs[(day, 0)].state, me, final.number) == other
            assert policy.opponent_of(setup, before[(day, 0)].state, me, final.number) is None
        if any(recs[(d, 0)].queued != before[(d, 0)].queued for d in days):
            bit.append(me)
    assert bit, "no finalist queued differently in the final than with the pairs emptied"


def decided_on(strat, setup, state, me: int, rec) -> policy.Decision:
    """``strat``'s decision for ``me`` on ``state`` with the beliefs and news of the day record
    ``rec``. On the record's own state it is the decision the record holds: no league without
    waivers has a problem that reads what the seat queued that day."""
    g = np.random.default_rng(7)
    return strat.decide(setup, state, me, rec.beliefs, rec.status, rec.returns, g)


def week_value(setup, rec, me: int, knobs) -> float:
    """What this week is worth in ``me``'s problem on the record's day, with no move made."""
    built = policy.problem_of(setup, rec.state, me, knobs, rec.beliefs, rec.status, rec.returns)
    return mv.Evaluator(built.problem).base["week"]


@pytest.mark.parametrize("waivers", ["none", "faab"])
def test_it_bites_a_plan_is_drawn_and_executed_in_the_final_and_its_step_bids_on_the_week(
    waivers,
):
    """An arm that draws and executes the week's plan, in the seat whose roster is weakened (it
    reaches the final), against the blind season. A blind week is worth nothing whatever is
    done, so no path of the stream beats its set and no plan is drawn there; against the
    final's opponent the week has a value, a plan is drawn and its step is executed (a found
    path, seed 5). Without waivers the step is queued; in a FAAB league under continuous
    waivers it is a claim, whose sealed bid is the live rule's on the step's week gain, which is
    not 0, and (the found path) the bid is above $0. One format, every category, the plan floor
    under zero: under one win no plan of a made-up league clears the engine's floor in the
    matchup's odds (``test_sim_knobs.py``'s note on its cases). About 2 s each."""
    me = 1
    setup = weakened(final_league("each_category"))
    if waivers == "faab":
        setup = replace(setup, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)
    knobs = {**KNOBS, "plan_floor_cats": -1.0}
    seat = op.Seat("P", "exact", knobs, with_plan=True)
    variant = {**{t: op.Static() for t in setup.teams}, me: seat}
    w = replay_of(setup, 5, 0)
    (seeded,), recs = played(setup, w, [variant], [True])
    (blind,), before = played(setup, w, [variant], [True], blind=True)
    assert not seeded.breaches
    final = setup.calendar.weeks[-1]
    ((pair,),) = end_pairs(seeded.result)
    assert me in pair
    for (day, vi), rec in recs.items():
        if day < final.start:
            assert rec == before[(day, vi)], day
    days = sorted(day for day, _ in recs if final.contains(day))
    for day in days:
        assert not before[(day, 0)].decisions[me].plan
        assert week_value(setup, before[(day, 0)], me, knobs) == 0.0
        assert week_value(setup, recs[(day, 0)], me, knobs) > 0.0
    bids = []
    for day in days:
        rec, decision = recs[(day, 0)], recs[(day, 0)].decisions[me]
        claims = {(c.move.add, c.move.drop): c for c in rec.claims.get(me, ())}
        placed = {(m.add, m.drop) for m in rec.queued.get(me, ())} | set(claims)
        own = {(m.add, m.drop) for m in decision.moves}
        for j, step in enumerate(decision.plan):
            at = (step.add, step.drop)
            if at not in placed or at in own:
                continue
            # A step of the plan, executed: the blind season's seat placed nothing like it.
            mine = before[(day, 0)]
            assert at not in {(m.add, m.drop) for m in mine.queued.get(me, ())}
            assert at not in {(c.move.add, c.move.drop) for c in mine.claims.get(me, ())}
            if waivers == "faab":
                basis = decision.basis
                gain = basis.plan[j]
                assert gain != 0.0
                fortnight = [x for _, x in rec.state.recent[me]]
                assert claims[at].bid == policy.live_bid(
                    gain, fortnight, basis.floor, rec.state.dollars[me], basis.sizing
                )
            bids.append(claims[at].bid if at in claims else None)
    assert bids, "no step of a plan was executed in the final"
    if waivers == "faab":
        assert max(bids) > 0
    else:
        assert bids == [None] * len(bids)
    # A step landed: the seat made a move in the final that the blind season's seat did not.
    assert not blind.breaches and seeded.executed > blind.executed


# --------------------------------------------------------------------------- the pairs, played
def end_pairs(result) -> tuple:
    """The rounds the season's end played, as the state holds a round: team ids, higher seed
    first."""
    post = result.playoffs
    return tuple(tuple((post.seeds[hi], post.seeds[lo]) for hi, lo, _ in r) for r in post.rounds)


SHAPES = {"4/2": (6, 4, 2), "6/3": (8, 6, 3), "8/3": (10, 8, 3)}


@pytest.mark.parametrize("reseed", [True, False])
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_the_pairs_a_season_seeds_are_the_rounds_its_end_plays(shape, reseed):
    """Through the runner, on each bracket shape, reseeded and fixed, two variants whose seasons
    differ: the pairs each state holds at the season's end are the rounds its own season's end
    played, a round a week; and on every day of a round every team's opponent is its pair's
    other team, and none for a team on a bye, out of the field or knocked out. On a round's
    Wednesday the week of the problem built for each team, in both variants, is the week of a
    league whose pairings held the round's pairs as they hold a regular week's: that one
    opponent's projected week with both sides' totals so far, or nobody's. The seats are the
    ranking's and a market's (no solve): the pairs are the league's, whoever decides. One
    format: the bracket is played alike in both. About 1 s each."""
    teams, playoff_teams, rounds = SHAPES[shape]
    setup = make_setup(
        teams=teams, weeks=3 + rounds, playoff_weeks=rounds, playoff_teams=playoff_teams
    )
    setup = replace(setup, spec=replace(setup.spec, reseed=reseed))
    w = replay_of(setup, 5, 0)
    market = op.of({"kind": "market", "rate": 0.5}, KNOBS, 0.1)
    variants = [
        {t: op.Static() for t in setup.teams},
        {**{t: market for t in setup.teams}, 1: op.Seat("R", "ranking", dict(KNOBS))},
    ]
    results, recs = played(setup, w, variants)
    last = max(day for day, _ in recs)
    weeks = lg.round_weeks(setup.spec)
    assert len(weeks) == rounds
    for vi, res in enumerate(results):
        assert not res.breaches
        due = end_pairs(res.result)
        assert len(due) == rounds
        assert recs[(last, vi)].state.seeded == dict(zip(weeks, due, strict=True))
        for (day, v), rec in recs.items():
            number = setup.week_of(day).number
            if v != vi or number not in weeks:
                continue
            pairs = due[weeks.index(number)]
            other = {a: b for a, b in pairs} | {b: a for a, b in pairs}
            # The same league with this round's pairs among its pairings, and no pairs seeded.
            paired = replace(setup, pairings={**setup.pairings, number: pairs})
            for t in setup.teams:
                assert policy.opponent_of(setup, rec.state, t, number) == other.get(t), (day, t)
                if day != setup.calendar.weeks[number - 1].start + timedelta(2):
                    continue
                span, regular = (
                    policy.problem_of(
                        league, state, t, KNOBS, rec.beliefs, rec.status, rec.returns
                    ).problem.horizons["week"]
                    for league, state in ((setup, rec.state), (paired, unseeded(rec).state))
                )
                assert span == regular, (day, t)
                assert len(span[0].opponents) == (t in other), (day, t)
                assert span[0].so_far and len(span[0].so_far_theirs) == (t in other)
        # Somebody sat out each round that has a bye or a team knocked out.
        assert all(len(pairs) * 2 < teams for pairs in due)
    assert results[0].result != results[1].result


# --------------------------------------------------------------------------- every league kind
def weighing(setup, me: int = 1):
    """A seat that reads the week (the weighted set) among market rivals."""
    market = op.of({"kind": "market", "rate": 0.3}, KNOBS, 0.1)
    seat = op.Seat("W", "exact", dict(KNOBS), policy.WEIGHTED, with_plan=False)
    return {**{t: market for t in setup.teams}, me: seat}


def kinds():
    """The league rules a round is crossed with, on the four-team league with a final: held
    slots, waivers by priority and by FAAB, each as dropped and continuous."""
    plain = {"teams": 4, "weeks": 4, "playoff_weeks": 1, "playoff_teams": 2}
    out = {"held": make_setup(**plain, held_slots=("IL", "IL+"))}
    for waivers in ("priority", "faab"):
        for way in (DROPPED, CONTINUOUS):
            out[f"{waivers}-{way}"] = replace(
                make_setup(**plain), waivers=waivers, waiver_days=2, waiver_rule=way
            )
    return out


@cache
def kind_season(kind: str, format_: str, me: int):
    """One season of :func:`kinds`' league ``kind`` in ``format_``, team ``me`` weighing the week
    among market rivals (seed 5): the setup, the result and the day records. Played once for
    the tests below."""
    setup = kinds()[kind]
    setup = setup if format_ == "one_win" else every_category(setup)
    (res,), recs = played(setup, replay_of(setup, 5, 0), [weighing(setup, me)])
    return setup, res, recs


def final_claims(setup, recs, me: int) -> list:
    """The claims ``me`` placed in the final: each with the gain its bid was sized on (the
    decision's basis for the claim's move; None in a league without bids)."""
    final = setup.calendar.weeks[-1]
    out = []
    for (day, _), rec in sorted(recs.items()):
        if not final.contains(day):
            continue
        decision = rec.decisions[me]
        at = [(m.add, m.drop) for m in decision.moves]
        for claim in rec.claims.get(me, ()):
            i = at.index((claim.move.add, claim.move.drop))
            out.append((claim, decision.basis.gains[i] if decision.basis else None))
    return out


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("kind", sorted(kinds()))
def test_a_round_under_every_league_rule_with_a_seat_that_reads_the_week(kind, format_):
    """A seat that weighs the week through a final, under each league rule and in each format:
    the audit, the bracket's rule read with the league's own, finds nothing; the final's pair is
    the season's end's, and the seat met its opponent there if it reached the final. Every seat
    in turn (who reaches the final moves with who holds the seat). Under continuous waivers,
    where every add is a claim, a seat places claims in the final (by priority, or with a sealed
    bid); under the default rule only a dropped player waits, and on this path no seat claims
    one in the final. About 3 s each."""
    met = claimed = 0
    for me in (1, 2, 3, 4):
        setup, res, recs = kind_season(kind, format_, me)
        final = setup.calendar.weeks[-1]
        assert audit.BRACKET_PAIRS in audit.Auditor(setup).rules
        assert not res.breaches, (me, res.breaches[:2])
        last = max(day for day, _ in recs)
        ((pair,),) = end_pairs(res.result)
        assert recs[(last, 0)].state.seeded == {final.number: (pair,)}
        claimed += len(final_claims(setup, recs, me))
        if me in pair:
            (other,) = set(pair) - {me}
            state = recs[(final.start, 0)].state
            assert policy.week_view(setup, state, me, final.number).opponent == other
            met += 1
    assert met, "no seat reached the final"
    assert (claimed > 0) == kind.endswith(CONTINUOUS), claimed


@pytest.mark.parametrize("format_", FORMATS)
def test_a_weighted_sets_claims_in_the_seasons_last_week_bid_nothing(format_):
    """A limit this PR brings into reach, pinned as it is (the README's sixth of a bracket
    week): a set's claim bids on its move's own gain on the three weeks, whatever set the seat
    executes (``policy.basis_of``), and in the season's last week the three weeks hold nothing.
    So every claim of a weighted set there is sized on a gain of exactly 0.0 and bids $0,
    whatever the week is worth against the round's opponent and whatever the seat has left; a
    plan's step in the same week bids on its week gain (the plan's test above). Before this PR
    the case was not met: the blind final gave the weighted set nothing to gain, and the seat
    placed no claim there. FAAB under continuous waivers, each seat in turn (the seasons of the
    test above); the blind double for the first seat that claims. About 1 s each."""
    kind = f"faab-{CONTINUOUS}"
    seen, earlier = [], []
    for me in (1, 2, 3, 4):
        setup, _, recs = kind_season(kind, format_, me)
        final = setup.calendar.weeks[-1]
        placed = final_claims(setup, recs, me)
        for claim, gain in placed:
            assert gain == 0.0 and claim.bid == 0, (me, claim)
        if placed:
            assert recs[(final.start, 0)].state.dollars[me] > 0
            seen.append(me)
            earlier += [
                claim.bid
                for (day, _), rec in recs.items()
                if day < final.start
                for claim in rec.claims.get(me, ())
            ]
    assert seen, "no weighted seat placed a claim in the final"
    # The same seats bid above $0 before the final, on gains that were not 0.
    assert max(earlier) > 0
    me = seen[0]
    setup, _, _ = kind_season(kind, format_, me)
    _, before = played(setup, replay_of(setup, 5, 0), [weighing(setup, me)], blind=True)
    final = setup.calendar.weeks[-1]
    assert not any(rec.claims.get(me) for (day, _), rec in before.items() if final.contains(day))


def points_league():
    """:func:`final_league` scored in points as a replay builds such a league
    (``run.replay_setup``): one category, the fantasy points, and standings that break a tie on
    points for."""
    base = final_league()
    spec = replace(base.spec, scoring="points", points=TABLE, cats=(), tiebreak=lg.TIEBREAK_POINTS)
    return replace(base, scoring="points", points=TABLE, cats=(wk.FPTS,), spec=spec)


def test_a_points_league_reads_its_rounds_opponent_and_both_scores():
    """A points league names no format. A seat that weighs the week among market rivals, against
    the blind season: the audit finds nothing; before the final the two are one season; in the
    final the seat's week is against the other finalist with each side's score so far, the
    week has a value on every day where the blind one is worth nothing, and (a found path,
    seed 5, seat 1) the seat queues differently there. About 1 s."""
    me = 1
    setup = points_league()
    w = replay_of(setup, 5, 0)
    (res,), recs = played(setup, w, [weighing(setup, me)])
    (blind,), before = played(setup, w, [weighing(setup, me)], blind=True)
    assert not res.breaches and not blind.breaches
    final = setup.calendar.weeks[-1]
    assert final.number not in setup.pairings
    ((pair,),) = end_pairs(res.result)
    assert me in pair
    (other,) = set(pair) - {me}
    for (day, vi), rec in recs.items():
        if day < final.start:
            assert rec == before[(day, vi)], day
    days = sorted(day for day, _ in recs if final.contains(day))
    for day in days:
        rec = recs[(day, 0)]
        view = policy.week_view(setup, rec.state, me, final.number)
        assert view.opponent == other and rec.state.seeded == {final.number: (pair,)}
        assert [k for k, _ in view.so_far] == [k for k, _ in view.so_far_theirs] == [wk.FPTS]
        assert week_value(setup, rec, me, KNOBS) > 0.0
        assert week_value(setup, before[(day, 0)], me, KNOBS) == 0.0
    # Both scores are the week's so far: none on its first morning, some by its third day.
    scores = [policy.week_view(setup, recs[(day, 0)].state, me, final.number) for day in days]
    assert scores[0].so_far == scores[0].so_far_theirs == ((wk.FPTS, 0.0),)
    assert scores[2].so_far[0][1] > 0.0 and scores[2].so_far_theirs[0][1] > 0.0
    assert any(recs[(day, 0)].queued != before[(day, 0)].queued for day in days)
    assert res != blind


# --------------------------------------------------------------------------- a split seat
def two_rounds():
    """The no-peek check's recorded league (four teams, six weeks) with its last two weeks a
    bracket of two rounds for all four."""
    setup, lines = recorded()
    spec = setup.spec
    pairings = {week: pairs for week, pairs in spec.pairings.items() if week <= 4}
    spec = replace(spec, pairings=pairings, playoff_weeks=(5, 6), playoff_teams=4, byes=0)
    return replace(setup, spec=spec, pairings=pairings), lines


def test_a_pair_with_a_split_seat_plays_its_rounds_on_its_own_table():
    """A rule that reads a seat's own forecaster, on a pair with a split seat: a ``blend`` arm
    and a ``bbm`` arm, both weighing the week, in one seat through two rounds. Each variant
    seeds its own rounds, the audit finds nothing, and in a round the split seat's opponent is
    projected on the table the seat itself reads. One format (one win): the split is the
    forecaster's, not the measure's. About 4 s."""
    setup, lines = two_rounds()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    arms = {
        name: replace(a, tier="exact", executes=policy.WEIGHTED, with_plan=False)
        for name, a in armed(("B", "bbm", None), ("Y", "blend", 0.25)).items()
    }
    assert all(a.seat().reads_week for a in arms.values())
    w = world_of(setup, lines, first, second_of(first), arms)
    variants = [variant_of(setup, arms, {1: name}) for name in ("Y", "B")]
    results, recs = played(setup, w, variants)
    last = max(day for day, _ in recs)
    for vi, res in enumerate(results):
        assert not res.breaches, res.breaches[:2]
        assert recs[(last, vi)].state.seeded == dict(
            zip((5, 6), end_pairs(res.result), strict=True)
        )
    # The split seat's problem in the first round: its opponent's week is projected on the
    # table the seat read that day, not on the run's.
    day = setup.calendar.weeks[4].start
    rec = recs[(day, 0)]
    other = policy.opponent_of(setup, rec.state, 1, 5)
    assert other is not None and rec.holds == {1: arms["Y"].forecaster}
    table = rec.held[arms["Y"].forecaster]
    state = replace(rec.state, day=day)

    def theirs(beliefs):
        built = policy.problem_of(setup, state, 1, arms["Y"].knobs, beliefs, rec.status, {})
        return built.problem.horizons["week"][0].opponents

    assert len(theirs(table)) == 1 and theirs(table) != theirs(rec.beliefs)


# --------------------------------------------------------------------------- no peek in a round
def test_no_peek_in_a_round_with_a_seat_that_reads_the_week():
    """The no-peek check on a day inside the second round, a seat that weighs the week in seat
    4, which plays both rounds: with every line from that day on redrawn, no record changes up
    to and on that day (the round's pairs, the opponent's week so far and the decision read
    nothing ahead), and the records do change after it. Not a check of empty decisions (a found
    path): on that day the seat queues a move, and the decision it made is the one its state
    gives with the round's pairs and another with the pairs emptied, so what is compared did
    read the round's opponent. One format: the check reads what is known, not the measure.
    About 7 s."""
    me = 4
    setup, lines = two_rounds()
    day = setup.calendar.weeks[5].start + timedelta(2)
    variant = weighing(setup, me)

    def records_of(these):
        w = rn.replay_world(setup, these, 1, SEED, 0, WEIGHTS)
        _, recs = played(setup, w, [variant])
        return {at: nopeek.digest(r) for at, r in recs.items()}, recs

    base, recs = records_of(lines)
    rec = recs[(day, 0)]
    assert rec.state.seeded.keys() == {5, 6}
    assert policy.opponent_of(setup, rec.state, me, 6) is not None
    assert rec.queued.get(me), "the seat queued nothing on the day"
    again, emptied = (
        decided_on(variant[me], setup, state, me, rec)
        for state in (rec.state, replace(rec.state, seeded={}))
    )
    assert again == rec.decisions[me] != emptied
    got, _ = records_of(nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    first_diff = nopeek.first_difference(base, got)
    assert first_diff is not None and first_diff[0] > day
    assert records_of(lines)[0] == base
