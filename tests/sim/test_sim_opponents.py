"""The other seats (#172, PR 2b): static, the market heuristic, the mirror and a named arm."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pickandroll.season.sim import opponents as op
from pickandroll.season.sim import policy
from pickandroll.season.sim.state import SimState, initial
from tests.sim_league import KNOBS, make_setup


def decide(strategy, setup, state, team=2, g=None):
    return strategy.decide(
        setup, state, team, setup.projection, {}, {}, g or np.random.default_rng(0)
    )


def test_static_never_moves():
    setup = make_setup()
    assert decide(op.Static(), setup, initial(setup)) == policy.NONE
    assert op.Static().kind == "static"


def test_the_market_moves_at_its_rate_best_in_for_worst_out():
    base = make_setup()
    state = initial(base)
    # The pool's first player is the market's darling: worth more than anyone rostered.
    setup = replace(base, market={**base.market, min(state.pool): 99.0})
    always = op.Market(1.0)
    d = decide(always, setup, state)
    (m,) = d.moves
    view = setup.market
    assert m.add == max(state.pool, key=lambda k: (view[k], -k))
    assert m.drop == min(state.active(2), key=lambda k: (view[k], k))
    assert d.source == "market" and d.solves == 0
    never = op.Market(0.0)
    assert decide(never, setup, state) == policy.NONE
    # The weekly cap holds it too, and a pool no better than the roster moves nothing.
    capped = SimState(state.day, state.rosters, state.pool, {2: 4})
    assert decide(always, setup, capped) == policy.NONE
    assert decide(always, base, state) == policy.NONE
    # The same generator state gives the same call; the rate is read from it.
    half = op.Market(0.5)
    draws = [
        decide(half, setup, state, g=np.random.default_rng(s)) != policy.NONE for s in range(40)
    ]
    assert 5 < sum(draws) < 35


def test_the_mirror_is_the_surrogate_on_the_shared_beliefs():
    setup = make_setup()
    state = initial(setup)
    mirror = decide(op.Mirror(KNOBS), setup, state)
    built = policy.problem_of(setup, state, 2, KNOBS, setup.projection, {}, {})
    assert mirror == policy.decide(built, "surrogate")


def test_a_seat_runs_its_tier():
    setup = make_setup()
    state = initial(setup)
    seat = op.Seat("A", "ranking", KNOBS)
    built = policy.problem_of(setup, state, 2, KNOBS, setup.projection, {}, {})
    assert decide(seat, setup, state) == policy.ranking(built)
    assert decide(op.Seat("S", "static", KNOBS), setup, state) == policy.NONE
    assert op.Seat("E", "exact", KNOBS).kind == "seat"


def test_opponents_are_built_from_the_arms_block():
    assert isinstance(op.of({"kind": "static"}, KNOBS, 0.1), op.Static)
    market = op.of({"kind": "market"}, KNOBS, 0.1)
    assert isinstance(market, op.Market) and market.rate == 0.1
    assert op.of({"kind": "market", "rate": 0.3}, KNOBS, 0.1).rate == 0.3
    assert isinstance(op.of({"kind": "mirror"}, KNOBS, 0.1), op.Mirror)
    with pytest.raises(ValueError):
        op.of({"kind": "seat"}, KNOBS, 0.1)
