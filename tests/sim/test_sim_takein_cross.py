"""SEASON SIM (#172, PR take-in): each change of the take-in crossed with the league's rules.

Each of the three changes alone (the field's later weeks on a legal roster, the blend toward
recent form, the week's spread), and all three, played on the exact tier with mirror rivals in
every league of ``takein_matrix``: a one-win league, a held slot with two players out on day
one, points, waivers by priority, by FAAB and continuous, every category counted, and same-day
adds. Every season plays to its end with no breach of the audit; each change moves some
season, and all three move every one. An arm that executes its plan on plan floors of -1 plays
every league with all three on. The seasons with every change off are
``test_sim_takein_equality``'s."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.sim import policy
from tests.sim import takein_matrix as tm
from tests.sim.test_sim_takein_equality import BEFORE

#: Each change alone, and all of them: the knobs it turns to live's.
ON = {k: policy.KNOB_DEFAULTS[k] for k in policy.TAKEIN_KNOBS}
CHANGES = {
    "legal": {"later_weeks": policy.LEGAL},
    "blend": {k: ON[k] for k in ("rate_shrink", "rate_shrink_games")},
    "spread": {k: ON[k] for k in ("rate_cv", "miss_rate")},
    "all": ON,
}


@pytest.fixture(scope="module")
def crossed() -> dict[tuple[str, str], bool]:
    """Whether each change moved each league's season on the exact tier (its digest against
    the one with every change off), each season played to its end with no breach."""
    out = {}
    a = tm.arms()["exact"]
    for change, knobs in CHANGES.items():
        for league in tm.LEAGUES:
            got, res = tm.played(league, replace(a, knobs={**a.knobs, **knobs}))
            assert res.result is not None and res.breaches == (), (change, league, res.breaches)
            out[(change, league)] = got != BEFORE[f"{league}/exact"]
    return out


def test_each_change_moves_some_season_and_all_three_move_every_league(crossed):
    for change in ("legal", "blend", "spread"):
        assert any(crossed[(change, league)] for league in tm.LEAGUES), change
    assert all(crossed[("all", league)] for league in tm.LEAGUES)
    # The blend and the spread reach most leagues: each moves more than half of them.
    for change in ("blend", "spread"):
        assert sum(crossed[(change, league)] for league in tm.LEAGUES) > len(tm.LEAGUES) / 2


@pytest.mark.parametrize("league", list(tm.LEAGUES))
def test_an_arm_that_executes_its_plan_on_floors_of_minus_one_plays_every_league(league):
    a = tm.arms()["plan"]
    got, res = tm.played(league, replace(a, knobs={**a.knobs, **ON}))
    assert a.execute_plan and policy.knob(a.knobs, "plan_floor_cats") == -1.0
    assert res.result is not None and res.breaches == ()
    assert got != BEFORE[f"{league}/plan"]
