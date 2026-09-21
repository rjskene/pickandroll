import numpy as np
import pytest

from pickandroll.availability import conditional_availability, pseudo_adp
from pickandroll.optim import HorizonProblem, horizon_pick_pool, punt_scan_horizon, solve_horizon
from pickandroll.projections import Cat, zscores
from pickandroll.projections.schema import split_positions

# Position 1 in a 4-team, 13-round snake draft: 60 synthetic players cover 52 picks.
FOUR_TEAM_PICKS = [1, 8, 9, 16, 17, 24, 25, 32, 33, 40, 41, 48, 49]


def make(pool, picks, locks=frozenset(), blocks=frozenset(), now=None, **kwargs):
    z = zscores(pool)
    positions = {pid: split_positions(v) for pid, v in pool["positions"].items()}
    adp = pseudo_adp(z["total"])
    now = now if now is not None else picks[0]
    avail = conditional_availability(adp, now=now, picks=picks)
    return HorizonProblem(
        z=z,
        positions=positions,
        picks=picks,
        availability=avail,
        locks=locks,
        blocks=blocks,
        **kwargs,
    )


def test_pseudo_adp_and_conditional_availability(pool):
    z = zscores(pool)
    adp = pseudo_adp(z["total"])
    assert adp[z["total"].idxmax()] == 1.0
    assert sorted(adp.values) == list(range(1, len(pool) + 1))
    avail = conditional_availability(adp, now=5, picks=[5, 20, 29])
    assert (avail[5] == 1.0).all()
    assert (avail[20] >= avail[29]).all()
    # A top player still on the board at pick 5 is very unlikely to last until pick 20.
    assert avail.at[z["total"].idxmax(), 20] < 0.05


def test_plan_covers_every_pick_and_fills_slots(pool):
    picks = FOUR_TEAM_PICKS
    problem = make(pool, picks)
    sol = solve_horizon(problem)
    assert sol.status == "Optimal"
    assert sol.plan["pick"].tolist() == picks
    assert sol.plan["player"].is_unique
    assert len(sol.roster) == 13
    assert set(sol.roster["player"]) == set(sol.plan["player"])
    # Availability at my first pick (now) is 1; later picks discount.
    assert sol.plan.iloc[0]["availability"] == 1.0
    assert sol.solve_seconds < 10


def test_plan_takes_scarce_star_now_not_later(pool):
    picks = FOUR_TEAM_PICKS
    problem = make(pool, picks)
    sol = solve_horizon(problem)
    z = problem.z["total"]
    assert sol.first_pick == z.idxmax()


def test_locks_blocks_and_open_slot_count(pool):
    z = zscores(pool)
    top = z["total"].nlargest(3).index.tolist()
    picks = FOUR_TEAM_PICKS[1:]  # 12 picks after one lock
    problem = make(
        pool, picks, locks=frozenset({top[0]}), blocks=frozenset({top[1]}), now=FOUR_TEAM_PICKS[1]
    )
    sol = solve_horizon(problem)
    assert top[0] in sol.roster["player"].tolist()
    assert top[1] not in sol.roster["player"].tolist()
    assert sol.roster.loc[sol.roster["player"] == top[0], "locked"].item()
    with pytest.raises(ValueError, match="remaining picks"):
        make(pool, picks[:-1], locks=frozenset({top[0]}), now=FOUR_TEAM_PICKS[1])


def test_pick_pool_prices_waiting_risk(pool):
    picks = FOUR_TEAM_PICKS
    problem = make(pool, picks)
    z = problem.z["total"]
    star = z.idxmax()
    mid = z.sort_values(ascending=False).index[30]
    table = horizon_pick_pool(problem, [star, mid], workers=1)
    assert list(table.columns) == [
        "player",
        "objective",
        "cost_vs_best",
        "p_available_first",
        "p_available_next",
        "min_active_total",
    ]
    assert table.iloc[0]["player"] == star
    assert table.loc[table["player"] == star, "cost_vs_best"].item() == 0.0
    assert table.loc[table["player"] == mid, "cost_vs_best"].item() > 0.0
    assert (
        table.loc[table["player"] == star, "p_available_next"].item()
        < table.loc[table["player"] == mid, "p_available_next"].item()
    )


def test_balance_and_punt_scan(pool):
    picks = FOUR_TEAM_PICKS
    greedy = solve_horizon(make(pool, picks))
    balanced = solve_horizon(make(pool, picks, balance=0.6))
    assert balanced.min_active_total >= greedy.min_active_total - 1e-6
    scan = punt_scan_horizon(make(pool, picks), max_punts=1)
    assert len(scan) == 10
    assert scan[0][1].objective >= scan[-1][1].objective
    assert all(isinstance(p, frozenset) for p, _ in scan)


def test_availability_can_be_zero_everywhere_for_gone_players(pool):
    picks = FOUR_TEAM_PICKS
    problem = make(pool, picks)
    avail = problem.availability.copy()
    star = problem.z["total"].idxmax()
    avail.loc[star] = 0.0
    avail.loc[star, picks[0]] = 0.0
    sol = solve_horizon(HorizonProblem(**{**problem.__dict__, "availability": avail}))
    assert star not in sol.plan["player"].tolist()
    assert np.isfinite(sol.objective)


def test_expected_totals_cover_punted_categories(pool):
    problem = make(pool, FOUR_TEAM_PICKS, punt=frozenset({Cat.TOV}))
    sol = solve_horizon(problem)
    assert set(sol.expected_totals.index) == set(Cat)
    assert sol.min_active_total == min(v for c, v in sol.expected_totals.items() if c != Cat.TOV)
