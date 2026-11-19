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

from pickandroll.sim import audit, nopeek, policy
from pickandroll.sim import league as lg
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_no_peek import SEED, WEIGHTS, recorded
from tests.sim.test_sim_league import totals
from tests.sim.test_sim_points import TABLE, made_up_season, setup_of
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
    Two rounds, so a later round is seeded on standings a round has changed. About 10 s each."""
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


def test_what_a_run_shares_and_solves_is_the_same_but_for_two_arms_of_one_name(monkeypatch):
    """The key's view moves no count where no two variants hold one seat on two views: a room,
    and a pair of two names, share and solve as they did under the old key; the same arm twice
    shares every decision, in the final too. One format: no decision is compared, only who is
    asked to decide. About 10 s."""
    setup = final_league()
    w = replay_of(setup, 5, 0)
    a = rn.Arm("A", "exact", dict(KNOBS), {"kind": "mirror"}, policy.WEIGHTED)
    b = replace(a, name="B", knobs={**KNOBS, "three_weight": 0.5})
    assert a.seat().reads_week and b.seat().reads_week

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
    (first, second) = now[2]
    assert second[0] == 0 and second[1] == first[0] > 0 and second[2:] == first[2:]


@pytest.mark.parametrize("format_", FORMATS)
def test_it_bites_a_finalist_that_weighs_the_week_queues_on_its_opponent_in_the_final(format_):
    """The weighted set among static rivals, a team at a time, against the blind season. Before
    the final the two are one season (no bracket week has been met). A team out of the final
    reads no opponent either way, and its whole season is the blind one's. A finalist reads the
    other finalist: in the final its problem's week has an opponent on every day, where the
    blind one has none, and (a found path, seed 5) at least one finalist queues differently
    there. About 6 s each."""
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
    other team, and none for a team on a bye, out of the field or knocked out. The seats are the
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
            for t in setup.teams:
                assert policy.opponent_of(setup, rec.state, t, number) == other.get(t), (day, t)
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


@pytest.mark.parametrize("format_", FORMATS)
@pytest.mark.parametrize("kind", sorted(kinds()))
def test_a_round_under_every_league_rule_with_a_seat_that_reads_the_week(kind, format_):
    """A seat that weighs the week through a final, under each league rule and in each format:
    the audit, the bracket's rule read with the league's own, finds nothing; the final's pair is
    the season's end's, and the seat met its opponent there if it reached the final. Every seat
    in turn (who reaches the final moves with who holds the seat). About 3 s each."""
    setup = kinds()[kind]
    setup = setup if format_ == "one_win" else every_category(setup)
    w = replay_of(setup, 5, 0)
    final = setup.calendar.weeks[-1]
    assert audit.BRACKET_PAIRS in audit.Auditor(setup).rules
    met = 0
    for me in setup.teams:
        (res,), recs = played(setup, w, [weighing(setup, me)])
        assert not res.breaches, (me, res.breaches[:2])
        last = max(day for day, _ in recs)
        ((pair,),) = end_pairs(res.result)
        assert recs[(last, 0)].state.seeded == {final.number: (pair,)}
        if me in pair:
            (other,) = set(pair) - {me}
            state = recs[(final.start, 0)].state
            assert policy.week_view(setup, state, me, final.number).opponent == other
            met += 1
    assert met, "no seat reached the final"


def test_a_points_league_reads_its_rounds_opponent_and_both_scores():
    """A points league names no format. Two teams, so the final is the whole league: on its
    Wednesday the seat's week is against the other team with each side's score so far, and the
    season's audit finds nothing (nobody finds a move to make in this league: the test reads
    the problem, not a queue). The bracket is named: the replay's default, six teams, is one a
    league of two cannot play, and such a spec raises on the first bracket morning now, where
    it raised at the season's end before. About 11 s."""
    _, setup = setup_of(scoring="points", points=TABLE, playoff_teams=2, playoff_weeks=1)
    assert setup.spec is not None and len(lg.round_weeks(setup.spec)) == 1
    lines, _, _ = made_up_season()
    w = rn.replay_world(setup, lines, 1, 5, 0)
    (res,), recs = played(setup, w, [weighing(setup)])
    assert not res.breaches
    number = lg.round_weeks(setup.spec)[0]
    week = setup.calendar.weeks[number - 1]
    assert number not in setup.pairings
    state = recs[(week.start + timedelta(2), 0)].state
    view = policy.week_view(setup, state, 1, number)
    assert view.opponent == 2 and state.seeded[number] in (((1, 2),), ((2, 1),))
    assert [k for k, _ in view.so_far] == [k for k, _ in view.so_far_theirs] == [wk.FPTS]
    span = policy.problem_of(setup, state, 1, KNOBS, setup.projection, {}, {}).problem
    assert len(span.horizons["week"][0].opponents) == 1


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
    forecaster's, not the measure's. About 20 s."""
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
    1: with every line from that day on redrawn, no record changes up to and on that day (the
    round's pairs, the opponent's week so far and the decision read nothing ahead), and the
    records do change after it. One format: the check reads what is known, not the measure.
    About 15 s."""
    setup, lines = two_rounds()
    day = setup.calendar.weeks[5].start + timedelta(2)

    def records_of(these):
        w = rn.replay_world(setup, these, 1, SEED, 0, WEIGHTS)
        _, recs = played(setup, w, [weighing(setup)])
        return {at: nopeek.digest(r) for at, r in recs.items()}, recs

    base, recs = records_of(lines)
    assert recs[(day, 0)].state.seeded.keys() == {5, 6}
    got, _ = records_of(nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    first_diff = nopeek.first_difference(base, got)
    assert first_diff is not None and first_diff[0] > day
    assert records_of(lines)[0] == base
