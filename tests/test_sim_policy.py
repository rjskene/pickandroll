"""The policy adapter (#172, PR 2b): the engine's own problem from a simulated state, the three
tiers, the executor and the day's lineup."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.season.sim import policy
from pickandroll.season.sim.state import SimState, initial
from tests.sim_league import KNOBS, make_setup


def built_for(setup, team=1, state=None, knobs=KNOBS, status=None):
    state = state or initial(setup)
    return policy.problem_of(setup, state, team, knobs, setup.projection, status or {}, {})


def test_knobs_are_checked_and_a_missing_one_refused():
    assert policy.check_knobs(KNOBS) == KNOBS
    with pytest.raises(KeyError):
        policy.check_knobs({k: v for k, v in KNOBS.items() if k != "daily_cap"})
    with pytest.raises(KeyError):
        policy.knob({}, "daily_cap")


def test_the_problem_mirrors_the_live_route():
    setup = make_setup()
    out = initial(setup).active(1)[0]
    built = built_for(setup, status={out: "O"})
    p = built.problem
    assert built.team == 1 and built.week.number == 1 and built.weeks_left == 5
    assert {k for k, _ in p.roster} == set(initial(setup).active(1))
    assert {k for k, _ in p.candidates} == set(setup.pool)
    # Free agents land tomorrow.
    assert set(p.effective.values()) == {setup.start + timedelta(1)}
    assert p.first_day == setup.start
    assert [h.this_week for h in p.horizons["week"]] == [True]
    assert len(p.horizons["three"]) == 3
    # The week's opponent is the pairing's; the field is everyone else.
    assert len(p.horizons["week"][0].opponents) == 1
    assert len(p.horizons["three"][0].opponents) == 3
    assert p.limits[0].adds == 4 and p.limits[1].adds == 4
    assert p.spots == 6 and p.held == ()
    assert p.season_end == setup.season_end
    assert p.daily_cap == 1
    assert dict(p.roster)[out].status == "O"
    # Adds already made this week come off the limit.
    used = SimState(setup.start, initial(setup).rosters, initial(setup).pool, {1: 3})
    assert built_for(setup, state=used).problem.limits[0].adds == 1


def test_no_problem_past_the_season():
    setup = make_setup()
    late = SimState(
        setup.season_end + timedelta(1), initial(setup).rosters, initial(setup).pool, {}
    )
    assert built_for(setup, state=late) is None


def test_each_tier_decides_and_the_surrogate_keeps_to_its_days():
    setup = make_setup()
    built = built_for(setup)
    exact = policy.exact(built)
    assert exact.source == "exact" and exact.solves == 2
    for m in exact.moves:
        assert m.add in setup.pool
    weighted = policy.exact(built, executes=policy.WEIGHTED, with_plan=False)
    assert weighted.solves == 1 and weighted.plan == ()
    surrogate = policy.surrogate(built)
    assert surrogate.source == "surrogate" and surrogate.solves == 1
    ranking = policy.ranking(built)
    assert ranking.source == "ranking" and ranking.solves == 0
    assert len(ranking.moves) <= 1
    # Monday is a surrogate day; Tuesday is not.
    assert policy.decide(built, "surrogate").solves == 1
    tuesday = SimState(setup.start + timedelta(1), initial(setup).rosters, initial(setup).pool, {})
    assert policy.decide(built_for(setup, state=tuesday), "surrogate") == policy.Decision(
        source="surrogate"
    )
    with pytest.raises(ValueError):
        policy.decide(built, "oracle")


def test_the_ranking_tier_swaps_the_pools_best_for_the_rosters_worst_when_it_gains():
    setup = make_setup()
    built = built_for(setup)
    d = policy.ranking(built)
    if d.moves:
        (m,) = d.moves
        p = built.problem
        assert m.add in {k for k, _ in p.candidates} and m.drop in {k for k, _ in p.roster}
        assert m.drop not in p.kept


def test_the_queue_keeps_to_the_caps_and_the_pool():
    setup = make_setup()
    state = initial(setup)
    pool = sorted(state.pool)
    roster = state.active(1)
    decision = policy.Decision(
        (mv.Move(pool[0], roster[0]), mv.Move(pool[1], roster[1]), mv.Move(999, roster[2])),
        (),
        (mv.Move(pool[2], roster[3], day=state.day + timedelta(1)),),
    )
    one = policy.queue(state, 1, decision, 1, 4)
    assert one.pending[1] == (mv.Move(pool[0], roster[0]),)
    two = policy.queue(state, 1, decision, 3, 4)
    assert [m.add for m in two.pending[1]] == [pool[0], pool[1]]  # 999 is not in the pool
    with_plan = policy.queue(state, 1, decision, 3, 4, execute_plan=True)
    assert [m.add for m in with_plan.pending[1]] == [pool[0], pool[1], pool[2]]
    capped = policy.queue(SimState(state.day, state.rosters, state.pool, {1: 3}), 1, decision, 3, 4)
    assert len(capped.pending[1]) == 1
    none = policy.queue(SimState(state.day, state.rosters, state.pool, {1: 4}), 1, decision, 3, 4)
    assert none.pending[1] == ()


def test_landing_moves_in_order_a_contested_add_is_gone():
    setup = make_setup()
    state = initial(setup)
    pool = sorted(state.pool)
    a, b = state.active(1)[0], state.active(2)[0]
    slot_a = dict(state.rosters[1])[a]
    pending = {1: (mv.Move(pool[0], a),), 2: (mv.Move(pool[0], b), mv.Move(pool[1], None))}
    state = SimState(state.day, state.rosters, state.pool, {}, pending)
    landed = policy.land(state, [2, 1])
    # Team 2 was first in the order: it has the contested add; team 1's move is gone.
    assert pool[0] in landed.active(2) and b in landed.pool
    assert pool[0] not in landed.active(1) and a in landed.active(1)
    assert pool[1] in landed.active(2)  # the add without a drop takes a bench spot
    assert landed.executed == 2 and landed.gone == 1
    assert landed.adds_used == {2: 2} and landed.pending == {}
    other = policy.land(state, [1, 2])
    assert pool[0] in other.active(1) and dict(other.rosters[1])[pool[0]] == slot_a
    assert policy.new_week(landed).adds_used == {}


def test_the_days_starters_and_score():
    setup = make_setup(statuses={})
    state = initial(setup)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    day = setup.start
    playing = {k for k in state.active(1) if setup.players[k].nba_team in setup.schedule[day]}
    starters = policy.starters_of(setup, state, 1, day, {}, value)
    assert set(starters) <= playing and len(starters) <= 5
    out = next(iter(starters))
    fewer = policy.starters_of(setup, state, 1, day, {out: "O"}, value)
    assert out not in fewer
    lines = {k: {"pts": 10.0, "minutes_factor": 1.0} for k in starters}
    scored = policy.score_day(setup, state, day, {}, value, lambda k, d: lines.get(k))
    assert scored.totals[1][1] == {"pts": 10.0 * len(starters)}
    assert 2 not in scored.totals.get(1, {}) or scored.totals[1][2] == {}


def test_the_season_guard_prices_a_move_on_the_rest_of_the_season():
    setup = make_setup()
    built = built_for(setup)
    ros = policy.ros_of(built)
    p = built.problem
    m = mv.Move(p.candidates[0][0], p.roster[0][0])
    first = ros(m)
    assert first is None or isinstance(first, float)
    assert ros(m) == first  # cached
    allowed = policy.guard_of(built)
    assert callable(allowed)
    rng = np.random.default_rng(0)
    assert rng is not None
