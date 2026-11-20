"""The decision cache's key and the week (#172, PR F2). A ``bid`` block that weighs the week makes
a strategy read the week's opponent and totals for its claims' size, on a ``repr`` two arms'
seasons share by design (a mirror rival), and ``SimState.key()`` holds no totals. So the runner
keys every strategy that reads the week on its team's view of the week as well
(``run.decision_key``, ``policy.week_view``, ``policy.reads_week``): the exact tier that
searches the week (main's own case, two arms of one name) and whoever bids by a block that
weighs it. Found by reading this PR beside the bracket PR, which adds the round's pairs to the
view.

Who reads the week is held by behaviour, not by a list. Every league is made up and every seed
fixed. No test here pins a literal outcome of a replay: the found paths (the queue's rule on a
view, the two seasons with a shared mirror) each assert their premise."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from itertools import product

import numpy as np
import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv
from pickandroll.sim.shapes import CONTINUOUS
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_sim_league import totals

FORMATS = ("one_win", "each_category")
ME = 4
#: The week the views are in: a regular week with a later one to weigh.
WEEK = 2


def league(format_: str = "one_win", **kw):
    """Four teams, every one against every other over three weeks, then a final between the top
    two in week four; in either head-to-head format."""
    setup = make_setup(teams=4, weeks=4, playoff_weeks=1, playoff_teams=2, **kw)
    return setup if format_ == "one_win" else every_category(setup)


def by_faab(setup):
    """``setup`` by FAAB with every add a claim (continuous waivers)."""
    return replace(setup, waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS)


# --------------------------------------------------------------------------- who reads the week
def seats():
    """A seat of every tier, executed set and plan choice. The queue's rule is the exact tier's
    (PR E: any other tier refuses it where it decides); it draws its own plan whatever the
    seat's plan switch says."""
    return [
        op.Seat("S", tier, dict(KNOBS), executes, with_plan)
        for tier, executes, with_plan in product(policy.TIERS, policy.EXECUTES, (False, True))
        if executes != policy.QUEUE or tier == "exact"
    ]


#: Blocks of the bid policy: one that weighs the week, one that weighs the season, one that
#: weighs neither and paces.
ON_WEEK = bp.of({"week": 0.5})
ON_SEASON = bp.of({"season": 0.5})
PACED = bp.of({"pace": {"k": 1, "shape": 1, "reserve": 0.2}, "routine": 1})
#: Knobs with a season term, for the seats that take a guard or a stake (the guard PR), and
#: with a stash threshold (PR G).
TERM = {**KNOBS, "season_weight": 0.0005}
STASH = {**KNOBS, "stash_threshold": 0.0}


def settings():
    """Seats that name what an arm can name beside its knobs, on the tiers that plan with the
    engine and on a set that searches no week (the three weeks', no plan drawn): a ``bid``
    block, a season term with the guard off and with a stake (the guard PR), a stash threshold
    (PR G). Whether each reads the week is asked by behaviour, as of every seat."""
    out = []
    for tier in ("exact", "surrogate"):
        out += [
            op.Seat("S", tier, dict(KNOBS), with_plan=False, bid=ON_WEEK),
            op.Seat("S", tier, dict(KNOBS), with_plan=False, bid=ON_SEASON),
            op.Seat("S", tier, dict(KNOBS), with_plan=False, bid=PACED),
            op.Seat("S", tier, dict(TERM), with_plan=False),
            op.Seat("S", tier, dict(TERM), with_plan=False, guard=policy.OFF),
            op.Seat("S", tier, dict(TERM), with_plan=False, stake=1.0),
            op.Seat("S", tier, dict(TERM), with_plan=False, bid=ON_SEASON),
            op.Seat("S", tier, dict(STASH), with_plan=False),
        ]
    return out


def rivals():
    return [
        op.Static(),
        op.of({"kind": "market", "rate": 1.0}, KNOBS, 0.1),
        op.of({"kind": "market", "rate": 1.0, "view": "season", "among": 2}, KNOBS, 0.1),
        op.Mirror(dict(KNOBS)),
        op.Mirror(dict(KNOBS), bid=ON_SEASON),
        op.Mirror(dict(KNOBS), bid=PACED),
        op.Mirror(dict(TERM)),
    ]


def week_bidders():
    """The rival that reads the week: a mirror whose arm's ``bid`` weighs it."""
    return [op.Mirror(dict(KNOBS), bid=ON_WEEK)]


def rival_of(setup, me: int = ME, week: int = WEEK) -> int:
    return next(b if a == me else a for a, b in setup.pairings[week] if me in (a, b))


#: A week's totals so far of a side far behind in every category, and of one far ahead.
LOW = totals(20.0, reb=4.0, tov=9.0, fgm=6.0, ftm=2.0, threes=1.0)
HIGH = totals(90.0, reb=30.0, tov=2.0, fgm=16.0, ftm=9.0, threes=9.0)


def three_views(setup, week: int = WEEK):
    """Three states of :func:`league` equal in ``key()`` on the Thursday of ``week`` (a day the
    surrogate solves, with a later week to weigh), whose views of the week are apart in the
    totals so far: team 4 is far behind its opponent in every category, far ahead, or no total
    is in."""
    day = setup.calendar.weeks[week - 1].start + timedelta(3)
    base = replace(initial(setup), day=day)
    other = rival_of(setup, ME, week)
    one = replace(base, totals={week: {ME: LOW, other: HIGH}})
    two = replace(base, totals={week: {ME: HIGH, other: LOW}})
    assert one.key() == two.key() == base.key()
    for team, against in ((ME, other), (other, ME)):
        views = [policy.week_view(setup, s, team, week) for s in (one, two, base)]
        assert len(set(views)) == 3 and {v.opponent for v in views} == {against}
    return one, two, base


def decided(strat, setup, state, team: int = ME) -> policy.Decision:
    g = np.random.default_rng(7)
    return strat.decide(setup, state, team, setup.projection, {}, {}, g)


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("waivers", ["none", "faab"])
def test_only_a_strategy_that_says_it_reads_the_week_decides_on_the_weeks_view(waivers, format_):
    """Held by behaviour, not by a list: every strategy the simulator seats decides on three
    states that share a ``key()`` and differ in the week's totals so far. One that does not say
    it reads the week gives the same decision on all three, its bid's basis included, so the
    cache may share it. A kind or a setting added later that reads the week and does not say so
    fails here, in a league without waivers or by FAAB. So a seat with each setting an arm can
    name is asked too (``settings``): a ``bid`` block, the guard off, a stake, a stash threshold.

    Of those that say it: the weighted set searches the week, and its decision is another on
    another view; the week's plan is searched on the week too (``policy.exact``), and so are
    the queue's rule's set and plans (``policy.draw_queue``; no plan leads on these states, and
    the test below finds a view on which the rule's choice moves). A seat or a mirror whose
    ``bid`` weighs the week searches no week and says it reads it all the same: by FAAB its
    moves are the same on the three views and the gains its claims are sized on are not. Both
    teams of the pair are asked, each on its own view. About 5 s each."""
    setup = league(format_)
    if waivers == "faab":
        setup = by_faab(setup)
    one, two, none = three_views(setup)
    # The pool's first player is the market's darling, so a market rival has a move to make.
    setup = replace(setup, market={**setup.market, min(one.pool): 99.0})
    kinds = {
        c
        for c in vars(op).values()
        if isinstance(c, type) and c.__module__ == op.__name__ and "decide" in vars(c)
    } - {op.Strategy}
    made = [*rivals(), *week_bidders(), *seats(), *settings()]
    assert {type(s) for s in made} == kinds, "a strategy kind this test does not seat"
    moved, based, sized, parted = set(), 0, 0, 0
    pair = (ME, rival_of(setup))
    for strat, team in product(made, setup.teams):
        if not rn._reads_week(strat):
            a, b, c = (decided(strat, setup, state, team) for state in (one, two, none))
            assert a == b == c, (strat, team)
            based += a.basis is not None
            if a.moves:
                moved.add((strat.kind, getattr(strat, "tier", None)))
        elif team not in pair:
            continue
        elif getattr(strat, "bid", None) is ON_WEEK:
            # It reads the week for its claims' size alone: the same moves on every view, and
            # where a claim is sized (FAAB) each move's gain on the week, which the view moves.
            a, b, c = (decided(strat, setup, state, team) for state in (one, two, none))
            assert a.moves == b.moves == c.moves, strat
            if a.basis is not None and a.moves:
                assert len({a.basis.week, b.basis.week, c.basis.week}) > 1, strat
                sized += 1
        elif strat.executes == policy.WEIGHTED:
            a, b, c = (decided(strat, setup, state, team) for state in (one, two, none))
            parted += not a == b == c
    # Not an empty promise: of those that do not read the week, each kind that can move does.
    assert moved >= {
        ("market", None),
        ("mirror", None),
        ("seat", "exact"),
        ("seat", "surrogate"),
        ("seat", "ranking"),
    }
    assert (based > 0) == (waivers == "faab")
    # A bid on the week parted on the views wherever a claim was sized on a day with a move.
    assert (sized > 0) == (waivers == "faab"), sized
    # The search of the week does read it: the weighted set parted on the views.
    assert parted > 0
    # Who says it reads the week: the exact tier's weighted set, the exact tier with a plan and
    # the exact tier under the queue's rule; and whoever bids by a block that weighs the week.
    assert [(s.tier, s.executes, s.with_plan) for s in seats() if s.reads_week] == [
        ("exact", "three", True),
        ("exact", "weighted", False),
        ("exact", "weighted", True),
        ("exact", "queue", False),
        ("exact", "queue", True),
    ]
    assert [s.tier for s in settings() if s.reads_week] == ["exact", "surrogate"]
    assert all(s.bid is ON_WEEK for s in settings() if s.reads_week)
    assert not any(rn._reads_week(r) for r in rivals())
    assert all(rn._reads_week(r) for r in week_bidders())


def test_the_queues_rule_decides_on_the_weeks_view_in_a_regular_week():
    """The queue's rule (PR E) reads the week as the weighted set does: on a found path (a
    one-win league, the Thursday of week three, the seat far ahead of its opponent or level
    with no total in) its choice is another on another view of one state, so two arms of one
    name must not share it across views. Under a second."""
    setup = league()
    one, _, none = three_views(setup, 3)
    team = rival_of(setup, ME, 3)
    seat = op.Seat("S", "exact", dict(KNOBS), policy.QUEUE)
    ahead, level = (decided(seat, setup, state, team) for state in (one, none))
    assert (ahead.moves, ahead.plan) != (level.moves, level.plan)
    k1, k2 = (rn.decision_key(setup, state, team, seat, 3) for state in (one, none))
    assert k1[:4] == k2[:4] and k1[4] != k2[4]


def test_the_decision_key_holds_the_weeks_view_for_a_strategy_that_reads_the_week_and_no_other():
    setup = league()
    one, two, _ = three_views(setup)
    other = rival_of(setup)
    for strat in [*rivals(), *week_bidders(), *seats(), *settings()]:
        k1, k2 = (rn.decision_key(setup, s, ME, strat, WEEK) for s in (one, two))
        assert k1[:3] == k2[:3] == (ME, repr(strat), one.key())
        # The fourth place is the guard PR's: the week's stake of a seat that reads one, which
        # the runner sets on the state; these states hold none.
        assert k1[3] is None and k2[3] is None and len(k1) == 5
        if rn._reads_week(strat):
            assert k1[4] == policy.week_view(setup, one, ME, WEEK) != k2[4]
            assert k2[4] == policy.week_view(setup, two, ME, WEEK)
        else:
            assert k1 == k2 and k1[4] is None
    # A seat with a stake is keyed on its own week's figure, whatever its view; no other is.
    staked = op.Seat("S", "surrogate", dict(TERM), with_plan=False, stake=1.0)
    plain = op.Seat("S", "surrogate", dict(TERM), with_plan=False)
    low, high = (replace(one, stakes={ME: level, 1: 0.5}) for level in (0.0, 1.0))
    assert low.key() == high.key() == one.key()
    assert [rn.decision_key(setup, s, ME, staked, WEEK)[3] for s in (low, high)] == [0.0, 1.0]
    assert rn.decision_key(setup, low, ME, plain, WEEK) == rn.decision_key(
        setup, high, ME, plain, WEEK
    )
    # Two arms of one name, apart only in their rivals or in ``execute_plan``, are one seat to
    # the cache; on one view they share (as the same arm twice does), on two they do not.
    a = rn.Arm("S", "exact", dict(KNOBS), {"kind": "static"}, policy.WEIGHTED)
    for b in (replace(a, opponents={"kind": "market"}), replace(a, execute_plan=True)):
        assert a != b and repr(a.seat()) == repr(b.seat())
        ka, kb = (rn.decision_key(setup, one, ME, arm.seat(), WEEK) for arm in (a, b))
        assert ka == kb
        assert ka != rn.decision_key(setup, two, ME, b.seat(), WEEK)
    # Two arms of two names apart only in the seat's own things face one mirror, and a mirror
    # whose block weighs the week is keyed on its own team's view.
    c = rn.Arm("C", "surrogate", dict(KNOBS), {"kind": "mirror"}, bid=ON_WEEK)
    d = replace(c, name="D", knobs={**KNOBS, "stash_threshold": 0.0})
    mirrors = [rn.opponents_of(setup, arm, 1)[ME] for arm in (c, d)]
    assert repr(mirrors[0]) == repr(mirrors[1]) and repr(c.seat()) != repr(d.seat())
    kc, kd = (rn.decision_key(setup, one, ME, m, WEEK) for m in mirrors)
    assert kc == kd != rn.decision_key(setup, two, ME, mirrors[1], WEEK)
    # A team's view is its own: another pair's totals this week are no part of it.
    third = next(t for t in setup.teams if t not in (ME, other))
    elsewhere = replace(one, totals={WEEK: {**one.totals[WEEK], third: totals(33.0)}})
    assert policy.week_view(setup, elsewhere, ME, WEEK) == policy.week_view(setup, one, ME, WEEK)
    assert policy.week_view(setup, one, ME, WEEK) == policy.WeekView(
        other, tuple(LOW.items()), tuple(HIGH.items())
    )
    # A week the pairings do not hold (the bracket's), on a state that holds no round's pairs
    # (PR bracket seeds them), has no opponent and nobody else's totals.
    last = setup.calendar.weeks[-1].number
    assert last not in setup.pairings
    assert policy.week_view(setup, one, ME, last) == policy.WeekView(None, (), None)


def test_what_a_run_shares_and_solves_is_the_same_but_for_one_seat_on_two_views(monkeypatch):
    """The key's view moves no count where no two variants hold one strategy on two views: a
    room, and a pair of two names over one mirror (the second arm draws no plan; both read the
    week), share and solve as they did under the old key, and the pair does share its mirrors'
    solves; the same arm twice shares every decision. One format: no decision is compared,
    only who is asked to decide. About 7 s."""
    setup = league()
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


# --------------------------------------------------------------------------- seasons
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


def lockstep(setup, w, variants, plans, who, monkeypatch):
    """The variants through ``w`` in lockstep: the results, each day's record by variant, and
    the keys ``who``'s decision was looked up under, by day, in the variants' order."""
    keys: dict = {}
    real = rn.decision_key

    def spy(setup_, state, team, strat, week):
        key = real(setup_, state, team, strat, week)
        if team == who:
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
    strategy, ``SimState.key()``, a stake's level) while their views of the week, the key's
    last place, differed."""
    return [d for d, (a, b) in sorted(keys.items()) if a[:-1] == b[:-1] and a[-1] != b[-1]]


def own_decisions(setup, w, variants, plans, who, monkeypatch):
    """Each variant's season in lockstep is its season alone, day by day and at the end; the days
    of :func:`apart_on_one_state`, and those of them on which ``who`` decided differently in the
    two variants (before the key held the view, the second was handed the first's)."""
    results, recs, keys = lockstep(setup, w, variants, plans, who, monkeypatch)
    for vi, (variant, plan) in enumerate(zip(variants, plans, strict=True)):
        (alone,), solo, _ = lockstep(setup, w, [variant], [plan], who, monkeypatch)
        for day in setup.days:
            if (day, vi) in recs:
                mine, theirs = recs[(day, vi)], solo[(day, 0)]
                assert mine.decisions == theirs.decisions, (vi, day)
                assert mine.state == theirs.state, (vi, day)
        assert results[vi].summaries == alone.summaries
        assert results[vi].result == alone.result
        assert results[vi].solves + results[vi].shared == alone.solves
    days = apart_on_one_state(keys)
    differ = [d for d in days if recs[(d, 0)].decisions[who] != recs[(d, 1)].decisions[who]]
    return results, recs, days, differ


#: Found paths, by format: the replay's seed, the scripted rival's team and the mirror's. In
#: week one the two meet, so the mirror's view holds the rival's totals.
SHARED = {"one_win": (5, 2, 3), "each_category": (2, 3, 2)}


@pytest.mark.parametrize("format_", FORMATS)
def test_two_arms_that_share_a_week_bidding_mirror_each_get_its_own_weeks_decision(
    format_, monkeypatch
):
    """The season that holds the crossing: two arms of two names whose ``bid`` weighs the week
    face one mirror rival (one ``repr``, by design), in a FAAB league with continuous waivers
    and a one-day wait. Their seasons are parted by a scripted rival, which makes one swap on
    the first Monday in one and a day later in the other, standing in for whatever parts two
    arms' seasons: by Thursday, a day the mirror solves, the two states agree in ``key()`` and
    the mirror's views of its week do not (its opponent's totals differ by a day of one
    player). It makes the same moves in both and the gains its claims are sized on differ; each
    season in lockstep is that season alone, every day. Under the old key the second season
    was handed the first's decision. With a two-day wait the seasons cannot meet again by a
    Thursday (the dropped player is still waiting), which is why the wait is one day here.
    About 5 s each."""
    seed, rival, chair = SHARED[format_]
    setup = replace(by_faab(league(format_)), waiver_days=1)
    assert rival_of(setup, chair, 1) == rival
    base = initial(setup)
    add, drop = min(base.pool), base.active(rival)[0]
    block = bp.of({"week": 1.0})
    arms = [rn.Arm(name, "surrogate", dict(KNOBS), {"kind": "mirror"}, bid=block) for name in "AB"]
    mirrors = [rn.opponents_of(setup, arm, 1)[chair] for arm in arms]
    assert repr(mirrors[0]) == repr(mirrors[1]) and mirrors[0].reads_week
    assert repr(arms[0].seat()) != repr(arms[1].seat())
    variants = [
        {
            **{t: op.Static() for t in setup.teams},
            chair: mirror,
            rival: Script(setup.days[day], add, drop),
            1: arm.seat(),
        }
        for arm, mirror, day in zip(arms, mirrors, (0, 1), strict=True)
    ]
    w = replay_of(setup, seed, 0)
    plans = [False, False]
    _, recs, _, differ = own_decisions(setup, w, variants, plans, chair, monkeypatch)
    assert differ, "on no day did the mirror decide on two views of one state"
    day = differ[0]
    assert day.weekday() == 3 and setup.week_of(day).number == 1
    first, second = (recs[(day, v)].decisions[chair] for v in (0, 1))
    assert first.moves == second.moves != ()
    assert first.basis.week != second.basis.week
    # Under the old key the second season is handed the first's decision that day.
    with monkeypatch.context() as mp:
        mp.setattr(rn, "_reads_week", lambda strat: False)
        _, old, _ = lockstep(setup, w, variants, plans, chair, monkeypatch)
    assert old[(day, 1)].decisions[chair] == first != second
