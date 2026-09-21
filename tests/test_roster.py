import pytest

from pickandroll.optim import RosterProblem, Slot, pick_pool, solve_roster, yahoo_default_slots
from pickandroll.projections import Cat, ProjectionSet, zscores
from pickandroll.projections.schema import split_positions


def make_problem(pool, **kwargs):
    z = zscores(pool)
    positions = {pid: split_positions(v) for pid, v in pool["positions"].items()}
    return RosterProblem(z=z, positions=positions, raw=pool, **kwargs)


def test_default_slots_count():
    assert len(yahoo_default_slots()) == 13
    assert len(yahoo_default_slots(bench=0)) == 10


def test_fixed_punt_fills_every_slot_legally(pool):
    problem = make_problem(pool, punt=frozenset({Cat.FT_PCT}))
    sol = solve_roster(problem)
    assert sol.status == "Optimal"
    assert len(sol.roster) == 13
    assert sol.roster["player"].is_unique
    for _, row in sol.roster.iterrows():
        slot = next(s for s in problem.slots if s.name == row["slot"])
        assert slot.accepts(problem.positions[row["player"]])
    assert sol.punted == (Cat.FT_PCT,)
    assert sol.solve_seconds < 5


def test_fixed_punt_matches_greedy_when_no_position_pressure(pool):
    # With every slot UTIL, the optimum is simply the top-13 by punt-adjusted total.
    slots = [Slot(f"U{i}") for i in range(13)]
    problem = make_problem(pool, punt=frozenset(), slots=slots)
    sol = solve_roster(problem)
    expected = set(problem.z["total"].nlargest(13).index)
    assert set(sol.players) == expected


def test_locks_and_blocks_are_respected(pool):
    z = zscores(pool)
    worst = z["total"].idxmin()
    best = z["total"].idxmax()
    problem = make_problem(
        pool, punt=frozenset(), locks=frozenset({worst}), blocks=frozenset({best})
    )
    sol = solve_roster(problem)
    assert worst in sol.players
    assert best not in sol.players


def test_auto_punt_respects_max_punts_and_beats_no_punt(pool):
    no_punt = solve_roster(make_problem(pool, punt=frozenset()))
    auto = solve_roster(make_problem(pool, punt=None, max_punts=2))
    assert len(auto.punted) <= 2
    # Punting can only add value: the no-punt roster is feasible for the auto model.
    assert auto.objective >= no_punt.objective - 1e-6


def test_balance_raises_weakest_category(pool):
    greedy = solve_roster(make_problem(pool, punt=frozenset(), balance=0.0))
    balanced = solve_roster(make_problem(pool, punt=frozenset(), balance=0.7))
    assert balanced.min_active_total >= greedy.min_active_total - 1e-6


def test_pct_floor_constrains_team_percentage(pool):
    floor = 0.54
    problem = make_problem(pool, punt=frozenset(), pct_floors={Cat.FG_PCT: floor})
    sol = solve_roster(problem)
    chosen = pool.loc[sol.players]
    assert chosen["fgm"].sum() / chosen["fga"].sum() >= floor - 1e-9


def test_min_games_constraint(pool):
    problem = make_problem(pool, punt=frozenset(), min_games=13 * 75)
    sol = solve_roster(problem)
    assert pool.loc[sol.players, "games"].sum() >= 13 * 75 - 1e-9


def test_availability_discounts_unlikely_players(pool):
    z = zscores(pool)
    best = z["total"].idxmax()
    avail = z["total"].map(lambda _: 1.0)
    avail[best] = 0.0
    problem = make_problem(pool, punt=frozenset(), availability=avail)
    sol = solve_roster(problem)
    assert best not in sol.players


def test_pick_pool_ranks_candidates(pool):
    z = zscores(pool)
    candidates = z["total"].nlargest(4).index.tolist() + [z["total"].idxmin()]
    problem = make_problem(pool, punt=frozenset())
    table = pick_pool(problem, candidates)
    assert list(table.columns)[:3] == ["player", "objective", "cost_vs_best"]
    assert table["cost_vs_best"].min() >= -1e-6
    assert table.iloc[-1]["player"] == z["total"].idxmin()


def test_invalid_problem_configuration(pool):
    with pytest.raises(ValueError):
        make_problem(pool, balance=2.0)
    with pytest.raises(ValueError):
        make_problem(pool, locks=frozenset({"nobody"}))


def test_projection_set_round_trip(pool):
    ps = ProjectionSet(
        source="test",
        label="t",
        horizon="season",
        as_of=__import__("datetime").datetime(2026, 9, 21),
        df=pool,
    )
    problem = RosterProblem(z=zscores(ps.df), positions=ps.positions())
    assert solve_roster(problem).status == "Optimal"


def test_punt_sets_count():
    from pickandroll.optim import punt_sets

    assert len(punt_sets(list(Cat), 2)) == 1 + 9 + 36
    assert len(punt_sets(list(Cat), 0)) == 1


def test_punt_scan_matches_single_model_auto_punt(pool):
    from pickandroll.optim import punt_scan

    problem = make_problem(pool, punt=None, max_punts=2)
    scan = punt_scan(problem, workers=1)
    assert len(scan.solutions) == 46
    assert list(scan.table.columns)[:2] == ["punt", "objective"]
    assert scan.table["objective"].is_monotonic_decreasing
    milp = solve_roster(problem, method="milp")
    assert abs(scan.solutions[0].objective - milp.objective) < 1e-6
    assert set(scan.solutions[0].punted) == set(milp.punted)


def test_balanced_auto_punt_routes_through_enumeration_and_agrees_with_milp(pool):
    problem = make_problem(pool, punt=None, max_punts=1, balance=0.5)
    via_enum = solve_roster(problem, method="enumerate")
    via_milp = solve_roster(problem, method="milp")
    assert abs(via_enum.objective - via_milp.objective) < 1e-6
    assert via_enum.status == "Optimal"


def test_invalid_method_rejected(pool):
    with pytest.raises(ValueError):
        solve_roster(make_problem(pool, punt=frozenset()), method="magic")
