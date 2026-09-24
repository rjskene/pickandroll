import numpy as np
import pandas as pd
import pulp
import pytest

from pickandroll.optim import (
    CategoryCurve,
    HorizonProblem,
    RosterProblem,
    phi,
    punt_scan,
    solve_horizon,
    solve_roster,
)
from pickandroll.optim.horizon import build as build_horizon
from pickandroll.optim.objective import add_curve, total_bounds
from pickandroll.optim.roster import build as build_roster
from pickandroll.projections import NINE_CAT, Cat, zscores
from pickandroll.projections.schema import split_positions

from .test_horizon import FOUR_TEAM_PICKS
from .test_horizon import make as make_horizon
from .test_roster import make_problem


def test_phi_is_the_normal_cdf():
    assert phi(0.0) == pytest.approx(0.5)
    assert phi(1.96) == pytest.approx(0.975, abs=1e-3)
    assert phi(-3.0) < 0.002


def test_curve_construction_fit_and_shift():
    curve = CategoryCurve.default(NINE_CAT, sigma=4.0)
    assert curve.probability(Cat.PTS, 0.0) == pytest.approx(0.5)
    assert curve.probability(Cat.PTS, 4.0) == pytest.approx(phi(1.0))
    rng = np.random.default_rng(0)
    totals = pd.DataFrame({c.value: rng.normal(1.0, 3.0, 400) for c in NINE_CAT})
    fitted = CategoryCurve.from_totals(totals, NINE_CAT)
    assert fitted.mu[Cat.REB] == pytest.approx(1.0, abs=0.5)
    assert fitted.sigma[Cat.REB] == pytest.approx(3.0, abs=0.5)
    shifted = fitted.shift({Cat.REB: -13.0})
    assert shifted.mu[Cat.REB] == pytest.approx(fitted.mu[Cat.REB] - 13.0)
    assert shifted.mu[Cat.PTS] == fitted.mu[Cat.PTS]
    assert shifted.probability(Cat.REB, fitted.mu[Cat.REB] - 13.0) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        CategoryCurve(mu={Cat.PTS: 0.0}, sigma={Cat.PTS: 0.0})
    with pytest.raises(ValueError):
        CategoryCurve.from_totals(totals[["pts"]], NINE_CAT)


def test_piecewise_curve_tracks_phi():
    curve = CategoryCurve.default([Cat.PTS], sigma=4.0)
    lo, hi = -30.0, 30.0
    for total in np.linspace(lo, hi, 61):
        exact = curve.probability(Cat.PTS, float(total))
        approx = curve.evaluate(Cat.PTS, float(total), lo, hi)
        assert abs(exact - approx) < 0.03
    for b in curve.breaks:  # exact at the breakpoints
        total = b * 4.0
        assert curve.evaluate(Cat.PTS, total, lo, hi) == pytest.approx(
            curve.probability(Cat.PTS, total)
        )


@pytest.mark.parametrize("total", [-29.0, -12.0, -7.0, -2.0, 0.0, 3.0, 8.0, 14.0, 29.0])
def test_model_curve_equals_piecewise_value_at_any_total(total):
    """The MILP form must not skip the flat lower tail and fill a steeper segment instead."""
    curve = CategoryCurve.default([Cat.PTS], sigma=4.0)
    lo, hi = -30.0, 30.0
    model = pulp.LpProblem("curve", pulp.LpMaximize)
    t = model.add_variable("T", lowBound=lo, upBound=hi)
    model += t == total, "fix"
    model += add_curve(model, "pts", t, curve, Cat.PTS, lo, hi)
    model.solve(pulp.HiGHS(msg=False))
    assert pulp.LpStatus[model.status] == "Optimal"
    assert pulp.value(model.objective) == pytest.approx(
        curve.evaluate(Cat.PTS, total, lo, hi), abs=1e-6
    )


def test_total_bounds_contain_any_roster_total(pool):
    z = zscores(pool)
    value = z[[c.value for c in NINE_CAT]]
    lo, hi = total_bounds(value, 13)
    rng = np.random.default_rng(1)
    for _ in range(20):
        roster = rng.choice(value.index, 13, replace=False)
        totals = value.loc[roster].sum()
        assert (totals >= lo).all() and (totals <= hi).all()


def _roster_curve_value(problem: RosterProblem, sol, curve: CategoryCurve) -> float:
    _, parts = build_roster(problem)
    lo, hi = total_bounds(parts["value"], len(problem.slots))
    return sum(
        curve.evaluate(c, float(sol.cat_totals[c]), float(lo[c.value]), float(hi[c.value]))
        for c in sol.active_cats
    )


def test_roster_curve_objective_matches_solution_totals(pool):
    curve = CategoryCurve.default(NINE_CAT, sigma=3.0)
    problem = make_problem(pool, punt=frozenset({Cat.TOV}), curve=curve)
    sol = solve_roster(problem)
    assert sol.status == "Optimal"
    assert len(sol.roster) == 13
    assert sol.punted == (Cat.TOV,)
    assert sol.objective == pytest.approx(_roster_curve_value(problem, sol, curve), abs=1e-5)
    assert 0.0 <= sol.objective <= 8.0


def test_roster_curve_prefers_no_explicit_punt(pool):
    curve = CategoryCurve.default(NINE_CAT, sigma=3.0)
    problem = make_problem(pool, punt=None, max_punts=1, curve=curve)
    with pytest.raises(ValueError):
        solve_roster(problem, method="milp")
    sol = solve_roster(problem)  # auto routes through the scan
    assert sol.punted == ()
    scan = punt_scan(problem, workers=1)
    assert scan.solutions[0].objective == pytest.approx(sol.objective, abs=1e-6)
    assert all(s.objective <= sol.objective + 1e-6 for s in scan.solutions)


def test_curve_rejects_balance_and_missing_categories(pool):
    curve = CategoryCurve.default(NINE_CAT)
    with pytest.raises(ValueError):
        make_problem(pool, punt=frozenset(), curve=curve, balance=0.5)
    with pytest.raises(ValueError):
        make_problem(pool, punt=frozenset(), curve=CategoryCurve.default([Cat.PTS]))


def test_horizon_curve_objective_matches_expected_totals(pool):
    curve = CategoryCurve.default(NINE_CAT, sigma=3.0)
    problem = make_horizon(pool, FOUR_TEAM_PICKS, punt=frozenset({Cat.FT_PCT}), curve=curve)
    sol = solve_horizon(problem)
    assert sol.status == "Optimal"
    assert sol.plan["pick"].tolist() == FOUR_TEAM_PICKS
    _, parts = build_horizon(problem)
    lo, hi = total_bounds(parts["value"], len(problem.slots))
    expected = sum(
        curve.evaluate(c, float(sol.expected_totals[c]), float(lo[c.value]), float(hi[c.value]))
        for c in problem.active_cats
    )
    assert sol.objective == pytest.approx(expected, abs=1e-5)
    assert sol.expected_wins is not None
    assert sol.expected_wins[Cat.FT_PCT] == 0.0
    assert 0.0 < sol.expected_wins[Cat.PTS] < 1.0
    with pytest.raises(ValueError):
        make_horizon(pool, FOUR_TEAM_PICKS, curve=curve, balance=0.3)


def test_horizon_curve_soft_punts_a_lost_category(pool):
    """A category the league always wins by a mile is worth almost nothing at the margin, so
    the plan stops paying for it: its expected total drops against the plain-sum plan."""
    z = zscores(pool)
    positions = {pid: split_positions(v) for pid, v in pool["positions"].items()}
    base = make_horizon(pool, FOUR_TEAM_PICKS)
    plain = solve_horizon(base)
    mu = dict.fromkeys(NINE_CAT, 0.0)
    mu[Cat.BLK] = 60.0  # unreachable: every team in the league blocks far more than we can
    curve = CategoryCurve(mu=mu, sigma=dict.fromkeys(NINE_CAT, 3.0))
    curved = solve_horizon(
        HorizonProblem(
            z=z,
            positions=positions,
            picks=FOUR_TEAM_PICKS,
            availability=base.availability,
            curve=curve,
        )
    )
    assert curved.expected_totals[Cat.BLK] <= plain.expected_totals[Cat.BLK] + 1e-6
    others = [c for c in NINE_CAT if c != Cat.BLK]
    assert curved.expected_totals[others].sum() >= plain.expected_totals[others].sum() - 1e-6


def test_simulated_curve_scaling_slope_and_labels():
    from pickandroll.optim.objective import SIMULATED_SIGMA, win_label

    curve = CategoryCurve.simulated(NINE_CAT)
    assert curve.source.startswith("simulated league")
    assert curve.sigma[Cat.TOV] == SIMULATED_SIGMA[Cat.TOV]
    flat = curve.scaled(2.0)
    assert flat.sigma[Cat.PTS] == pytest.approx(2.0 * curve.sigma[Cat.PTS])
    assert flat.mu == curve.mu and "sigma x2" in flat.source
    assert curve.scaled(1.0) is curve
    with pytest.raises(ValueError):
        curve.scaled(0.0)
    # The slope is the density over sigma: highest at the mean, tiny in the tails.
    mu = curve.mu[Cat.REB]
    assert curve.slope(Cat.REB, mu) == pytest.approx(0.3989 / curve.sigma[Cat.REB], abs=1e-3)
    assert curve.slope(Cat.REB, mu + 20.0) < 1e-4
    assert curve.wins({Cat.REB: mu, Cat.AST: curve.mu[Cat.AST]}) == pytest.approx(1.0)
    assert win_label(0.05) == "conceded"
    assert win_label(0.5) == "contested"
    assert win_label(0.95) == "secured"
    back = CategoryCurve.from_dict(flat.to_dict(), NINE_CAT)
    assert back.sigma[Cat.PTS] == pytest.approx(flat.sigma[Cat.PTS], abs=1e-3)
    assert back.source == flat.source
    with pytest.raises(ValueError):
        CategoryCurve.from_dict({"mu": {"pts": 0.0}, "sigma": {"pts": 1.0}}, NINE_CAT)
