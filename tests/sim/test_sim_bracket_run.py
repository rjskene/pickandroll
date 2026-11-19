"""The bracket's opponent through the runner (#172, PR bracket): the decision cache's key holds
a team's view of its week for a strategy that reads the week, and for no other; the seasons that
play a round. The pure pairs, the state's and the audit's rule are ``test_sim_bracket.py``'s.

Every league is made up and every seed fixed. Each season's test names its time below."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from itertools import product

import numpy as np
import pytest

from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_sim_league import totals

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


def two_views(setup):
    """Two states equal in ``key()`` on the first round's Thursday (a day the surrogate solves)
    whose views of the week are apart in everything the week's span reads: team 4 plays team 1
    and trails, or plays team 2 and leads."""
    day = setup.calendar.weeks[3].start + timedelta(3)
    base = replace(initial(setup), day=day)
    one = replace(
        base, totals={4: {4: totals(40.0), 1: totals(50.0)}}, seeded={4: ((4, 1), (2, 3))}
    )
    two = replace(
        base, totals={4: {4: totals(55.0), 2: totals(35.0)}}, seeded={4: ((4, 2), (1, 3))}
    )
    assert one.key() == two.key()
    assert policy.week_view(setup, one, ME, 4) != policy.week_view(setup, two, ME, 4)
    return one, two


def decided(strat, setup, state, team: int = ME) -> policy.Decision:
    g = np.random.default_rng(7)
    return strat.decide(setup, state, team, setup.projection, {}, {}, g)


@pytest.mark.parametrize("format_", FORMATS)
def test_only_a_strategy_that_says_it_reads_the_week_decides_on_the_weeks_view(format_):
    """Held by behaviour, not by a list: every strategy the simulator seats decides on two states
    that share a ``key()`` and differ in the week's opponent and totals. One that does not say
    it reads the week gives the same decision on both, so the cache may share it. A kind added
    later that reads the week and does not say so fails here. Of those that say it, the weighted
    set differs on these two; the week's plan is searched on the week too (``policy.exact``),
    and no plan is drawn on either of these states."""
    setup = rounds_league(format_)
    one, two = two_views(setup)
    # The pool's first player is the market's darling, so a market rival has a move to make.
    setup = replace(setup, market={**setup.market, min(one.pool): 99.0})
    kinds = {
        c
        for c in vars(op).values()
        if isinstance(c, type) and c.__module__ == op.__name__ and "decide" in vars(c)
    } - {op.Strategy}
    made = [*rivals(), *seats()]
    assert {type(s) for s in made} == kinds, "a strategy kind this test does not seat"
    moved = set()
    for strat, team in product(made, setup.teams):
        a, b = decided(strat, setup, one, team), decided(strat, setup, two, team)
        if not rn._reads_week(strat):
            assert a == b, (strat, team)
            if a.moves:
                moved.add((strat.kind, getattr(strat, "tier", None)))
        elif strat.executes == policy.WEIGHTED and team == ME:
            assert a != b and a.moves and b.moves, strat
    # Not an empty promise: of those that do not read the week, a market rival, the mirror and a
    # seat of each tier move on these states.
    assert moved >= {
        ("market", None),
        ("mirror", None),
        ("seat", "exact"),
        ("seat", "surrogate"),
        ("seat", "ranking"),
    }
    # Who says it reads the week: the exact tier's weighted set, and the exact tier with a plan.
    assert [(s.tier, s.executes, s.with_plan) for s in seats() if s.reads_week] == [
        ("exact", "three", True),
        ("exact", "weighted", False),
        ("exact", "weighted", True),
    ]
    assert not any(rn._reads_week(r) for r in rivals())


def test_the_decision_key_holds_the_weeks_view_for_a_seat_that_reads_the_week_and_no_other():
    setup = rounds_league()
    one, two = two_views(setup)
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
    return results, days, differ


#: The found paths of the test below, a format each: the seat's team, the rival that swaps, the
#: two days of its swap (as days of the season) and what the days the cache met are apart in.
ONE_NAME = {
    "one_win": (3, 4, 0, 2, "totals"),
    "each_category": (1, 4, 0, 4, "opponent"),
}


@pytest.mark.parametrize("format_", FORMATS)
def test_two_arms_of_one_name_apart_in_their_rivals_each_decide_on_their_own_week(
    format_, monkeypatch
):
    """Two arms of one name whose seats are one ``repr``, apart only in their rivals: here one
    rival makes the same swap in both variants, on two different days. The variants' states
    part, then agree again in ``SimState.key()`` while a week's totals (and, by the standings,
    the final's pairs) differ. Before the key held the week's view the second variant was handed
    the first's decision on those days. A found path a format (seed 5): under one win a
    matchup the two variants meet again in the final with different totals so far; under every
    category they meet on the final's first morning with different opponents. About 8 s each."""
    me, rival, first, second, apart = ONE_NAME[format_]
    setup = final_league(format_)
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
    results, days, differ = own_decisions(setup, w, variants, [False, False], me, monkeypatch)
    final = setup.calendar.weeks[-1]
    assert days and all(final.contains(d) for d in days)
    assert differ, "on no such day did the two seats decide differently"
    (ra, rb) = results
    assert not ra.breaches and not rb.breaches
    if apart == "opponent":
        # The two seasons seeded different finals, and each seat met its own.
        assert ra.result.playoffs.seeds != rb.result.playoffs.seeds
