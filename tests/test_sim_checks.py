"""What the gates are fed (#172, PR 2b): team weeks under a world, the odds beside the engine's,
missed games under the hazard, the surrogate against the exact set, the share's band."""

from __future__ import annotations

import numpy as np

from pickandroll.season import weekly as wk
from pickandroll.season.sim import checks
from pickandroll.season.sim import run as rn
from pickandroll.season.sim import validate as vg
from tests.sim_league import HAZARD, KNOBS, inputs, make_setup


def test_team_weeks_under_the_world_are_calibrated_against_the_world_itself():
    setup = make_setup(teams=4, spots=5, pool=4)
    worlds = [rn.forward_world(setup, inputs(tau=0.0), 21, p, 0.0) for p in range(40)]
    days = setup.calendar.week(1).days()
    value = wk.per_game_values(setup.projection, setup.cats, None)
    pits: list[float] = []
    for team in setup.teams:
        roster = setup.rosters[team]
        samples = checks.team_week_samples(setup, lambda p: worlds[p], roster, days, 40)
        assert len(samples) == 40 and all("pts" in s for s in samples)
        # A path of the same world as the realized side: its transforms are uniform.
        for p in range(40, 48):
            realized = checks.team_week(
                setup, rn.forward_world(setup, inputs(tau=0.0), 21, p, 0.0), roster, days, value
            )
            pits += checks.transforms(realized, samples)
    assert len(pits) == 4 * 8 * len(checks.COUNTING)
    assert 0.3 < float(np.mean(pits)) < 0.7


def test_simulated_odds_sit_beside_the_engines():
    setup = make_setup(teams=4, spots=5, pool=4)
    worlds = [rn.forward_world(setup, inputs(tau=0.0), 5, p, 0.0) for p in range(60)]
    days = setup.calendar.week(1).days()
    a, b = setup.rosters[1], setup.rosters[2]
    mine = checks.team_week_samples(setup, lambda p: worlds[p], a, days, 60)
    theirs = checks.team_week_samples(setup, lambda p: worlds[p], b, days, 60)
    sim = checks.simulated_odds(mine, theirs, setup.spec)
    eng = checks.engine_odds(setup, setup.projection, a, b, days)
    assert 0.0 <= sim <= 1.0 and 0.0 <= eng <= 1.0
    assert abs(sim - eng) < 0.35
    assert checks.simulated_odds([], [], setup.spec) == 0.5


def test_missed_samples_carry_an_absence_from_one_week_into_the_next():
    samples = checks.missed_samples(HAZARD, [[4, 3, 4], [2]], 50, 3)
    assert samples.shape == (4, 50)
    assert (samples[0] <= 4).all() and (samples[1] <= 3).all() and (samples[3] <= 2).all()
    # The same seed draws the same season; a season of one week never misses its first game.
    assert (samples == checks.missed_samples(HAZARD, [[4, 3, 4], [2]], 50, 3)).all()
    assert (checks.missed_samples(HAZARD, [[1]], 30, 1) == 0).all()
    gate = vg.absence_gate([0, 1, 0, 0], samples, season=2025, seed=1)
    assert gate.name == "absences"


def test_surrogate_matches_compare_the_two_tiers_sets():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 2, 0, 0.0)
    days = [setup.start, setup.start + __import__("datetime").timedelta(3)]
    matches = checks.surrogate_matches(setup, w, 1, days, KNOBS)
    assert len(matches) == 2 and all(isinstance(m, bool) for m in matches)
    assert (
        checks.surrogate_matches(
            setup, w, 1, [setup.season_end + __import__("datetime").timedelta(1)], KNOBS
        )
        == []
    )


def test_the_share_band():
    assert checks.share_band([2.0, 2.0], [[1.0, 3.0], [1.0, 1.0]]) == [0.5, 1.0]
    assert checks.share_band([0.0], [[1.0]]) == []
    assert checks.share_band([1.0], []) == []
