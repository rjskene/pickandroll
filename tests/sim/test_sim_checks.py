"""What gate 5 is fed (#172, PR 2b; PR D3): the surrogate against the exact set, on a replay of a
made-up recorded season."""

from __future__ import annotations

from datetime import timedelta

from pickandroll.sim import checks
from tests.sim.sim_league import KNOBS, make_setup, replay_of


def test_surrogate_matches_compare_the_two_tiers_sets():
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    days = [setup.start, setup.start + timedelta(3)]
    matches = checks.surrogate_matches(setup, w, 1, days, KNOBS)
    assert len(matches) == 2 and all(isinstance(m, bool) for m in matches)
    assert checks.surrogate_matches(setup, w, 1, [setup.season_end + timedelta(1)], KNOBS) == []
