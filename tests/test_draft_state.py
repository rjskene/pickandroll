from datetime import UTC, datetime

import pytest

from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.projections import Cat, ProjectionSet


def make_state(pool, position=3, num_teams=4):
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    settings = LeagueSettings(num_teams=num_teams)
    return DraftState(settings=settings, projections=ps, my_team="me", my_position=position)


def test_initial_state(pool):
    state = make_state(pool)
    assert state.next_overall == 1
    assert not state.on_the_clock
    assert state.my_next_pick == 3
    assert len(state.available) == len(pool)


def test_apply_pick_updates_board(pool):
    state = make_state(pool)
    top = state.z["total"].idxmax()
    state.apply_pick("them", top)
    assert top in state.taken
    assert top not in state.available
    with pytest.raises(ValueError):
        state.apply_pick("them", top)
    with pytest.raises(KeyError):
        state.apply_pick("them", "nobody")


def test_sync_applies_only_new_picks(pool):
    state = make_state(pool)
    ids = state.z["total"].nlargest(3).index.tolist()
    feed = [(1, "a", ids[0]), (2, "b", ids[1])]
    assert len(state.sync(feed)) == 2
    feed.append((3, "me", ids[2]))
    added = state.sync(feed)
    assert [p.overall for p in added] == [3]
    assert state.my_roster == [ids[2]]


def test_recommend_locks_my_roster_and_blocks_others(pool):
    state = make_state(pool)
    ids = state.z["total"].nlargest(3).index.tolist()
    state.sync([(1, "a", ids[0]), (2, "b", ids[1])])
    assert state.on_the_clock
    table = state.recommend(n=4, punt=frozenset({Cat.FT_PCT}))
    assert not table.empty
    assert ids[0] not in table["player"].tolist()
    assert "name" in table.columns
    best = state.best_roster(punt=frozenset({Cat.FT_PCT}))
    assert ids[0] not in best.players and ids[1] not in best.players
    state.apply_pick("me", table.iloc[0]["player"])
    best = state.best_roster(punt=frozenset({Cat.FT_PCT}))
    assert table.iloc[0]["player"] in best.players


def test_draft_completes(pool):
    state = make_state(pool, num_teams=4)
    order = state.z["total"].sort_values(ascending=False).index.tolist()
    for k in range(state.settings.total_picks):
        _, position = state.owner_of(k + 1)
        team = "me" if position == state.my_position else f"t{position}"
        state.apply_pick(team, order[k])
    assert state.complete
    assert len(state.my_roster) == 13
    assert state.my_next_pick is None


def test_effective_adp_prefers_market_then_fallback(pool):
    state = make_state(pool)
    fallback = state.effective_adp()
    assert state.adp_source == "z_total"
    assert fallback[state.z["total"].idxmax()] == 1.0
    market = fallback.copy() * 0 + 50.0
    market.iloc[0] = 3.0
    state.set_adp(market.iloc[:10], "yahoo")
    eff = state.effective_adp()
    assert state.adp_source == "yahoo"
    assert eff.iloc[0] == 3.0
    assert eff.iloc[20] == fallback.iloc[20]


def test_plan_and_horizon_recommendation(pool):
    state = make_state(pool, position=2, num_teams=4)
    ids = state.z["total"].nlargest(2).index.tolist()
    state.apply_pick("a", ids[0])
    assert state.on_the_clock
    assert state.my_remaining_picks[0] == 2 and len(state.my_remaining_picks) == state.open_slots
    solution, punt = state.plan(punt=frozenset({Cat.TOV}))
    assert punt == frozenset({Cat.TOV})
    assert solution.plan["pick"].tolist() == state.my_remaining_picks
    assert solution.plan.iloc[0]["availability"] == 1.0
    table, solution2, _chosen = state.recommend_horizon(n=4, punt=frozenset({Cat.TOV}), workers=1)
    assert "p_available_next" in table.columns and "name" in table.columns
    assert table.iloc[0]["player"] == solution2.first_pick
    assert ids[0] not in table["player"].tolist()


def test_horizon_mismatch_raises(pool):
    state = make_state(pool, position=1, num_teams=4)
    top = state.z["total"].nlargest(3).index.tolist()
    state.apply_pick("me", top[0])
    state.apply_pick("me", top[1])  # I somehow own pick 2 as well: 11 open slots, 12 picks left
    with pytest.raises(ValueError, match="remaining picks"):
        state.horizon_problem(frozenset())


def test_solver_pool_is_trimmed_but_keeps_my_roster(pool):
    state = make_state(pool, num_teams=4)
    state.solver_margin = 5
    worst = state.z["total"].idxmin()
    state.apply_pick("them", state.z["total"].idxmax())
    state.apply_pick("me", worst)
    players = state.solver_players()
    assert worst in players
    assert len(players) == min(len(pool), 52 - 2 + 5 + 1)
    problem = state.problem(punt=frozenset())
    assert set(problem.z.index) == set(players)
    assert worst in problem.locks


def test_replacement_level_makes_late_plan_picks_likely(pool):
    state = make_state(pool, position=1, num_teams=4)
    level = state.replacement_level()
    assert set(level.index) == {c.value for c in state.settings.cats}
    solution, _ = state.plan(punt=frozenset())
    # The final pick should be a player who will plausibly still be there, not a lottery ticket.
    assert solution.plan.iloc[-1]["availability"] > 0.3
    values = state.horizon_problem(frozenset()).z["total"]
    assert values.loc[solution.plan["player"]].min() > -1.0


def test_roster_value_is_the_locked_part_of_the_plan(pool):
    state = make_state(pool, position=1, num_teams=4)
    assert state.roster_value() == 0.0
    top = state.z["total"].nlargest(2).index.tolist()
    state.apply_pick("me", top[0])
    one = state.roster_value(punt=frozenset({Cat.TOV}))
    assert one > 0
    for _ in range(6):  # the other teams' picks
        state.apply_pick("them", state.z.loc[state.available, "total"].idxmax())
    state.apply_pick("me", top[1]) if top[1] in state.available else None
    assert state.roster_value(punt=frozenset({Cat.TOV})) >= one - 1e-6
    active = [c.value for c in state.settings.cats if c is not Cat.TOV]
    expected = (
        (state.z.loc[state.my_roster, active] - state.replacement_level()[active]).sum().sum()
    )
    assert abs(state.roster_value(punt=frozenset({Cat.TOV})) - expected) < 1e-9


def test_curve_default_objective_and_category_report(pool):
    from pickandroll.optim import CategoryCurve

    state = make_state(pool, position=2, num_teams=4)
    assert state.objective == "sum"
    state.curve = CategoryCurve.default(state.settings.cats, sigma=3.0)
    assert state.objective == "win"
    ids = state.z["total"].nlargest(3).index.tolist()
    state.apply_pick("Sharks", ids[0])
    assert state.team_names() == {1: "Sharks", 2: "me", 3: "Team 3", 4: "Team 4"}
    problem = state.horizon_problem()
    assert problem.curve is not None and problem.max_candidates == 80
    assert state.horizon_problem(curve=None).curve is None
    table, solution, punt = state.recommend_horizon(n=3, workers=1)
    assert punt == frozenset() and state.last_punt_scan is None
    assert {"cost_first_order", "time_limited"} <= set(table.columns)
    assert solution.wins is not None and 0.0 < solution.wins < 9.0
    finals = state.raw_finals(solution)
    report = state.category_report(finals)
    assert [r["cat"] for r in report] == [c.value for c in state.settings.cats]
    assert all(r["label"] in {"conceded", "contested", "secured"} for r in report)
    assert all(r["expected"] == pytest.approx(float(finals[r["cat"]]), abs=1e-3) for r in report)
    assert state.expected_wins(finals) == pytest.approx(sum(r["odds"] for r in report), abs=1e-3)
    tally = state.matchups(finals)
    assert [o["team"] for o in tally["opponents"]] == ["Sharks", "Team 3", "Team 4"]
    assert tally["matchups_won"] == sum(o["won"] for o in tally["opponents"])
    assert all(o["won"] == (o["cats_beaten"] >= 5) for o in tally["opponents"])
    prices = state.board_prices(problem, solution)
    assert prices[solution.first_pick] == 0.0
    assert prices.dropna().min() >= 0.0 and ids[0] not in prices.index


def test_scenarios_when_someone_else_is_on_the_clock(pool):
    state = make_state(pool, position=3, num_teams=4)
    assert not state.on_the_clock
    problem = state.horizon_problem()
    table, solution, _ = state.recommend_horizon(n=4, workers=1, problem=problem)
    rows = state.scenarios(problem, table, count=2, workers=1)
    assert len(rows) <= 2
    for row in rows:
        assert row["gone"] != row["pick"] and row["pick"] in state.available
        assert row["objective"] <= solution.objective + 1e-6
        assert "gone_name" in row and "pick_name" in row
    state.apply_pick("a", state.available[0])
    state.apply_pick("b", state.available[0])
    assert state.on_the_clock
    problem = state.horizon_problem()
    table, _, _ = state.recommend_horizon(n=3, workers=1, problem=problem)
    assert state.scenarios(problem, table, workers=1) == []


def test_solve_plan_falls_back_to_sum_without_an_incumbent(pool, monkeypatch):
    from pickandroll.draft import state as state_module

    state = make_state(pool, position=1, num_teams=4)
    state.curve = state.wins_curve()
    calls = []
    real = state_module.solve_horizon

    def flaky(problem, **kwargs):
        calls.append(problem.curve is not None)
        if problem.curve is not None:
            raise RuntimeError("horizon solve failed with status Infeasible")
        return real(problem, **kwargs)

    monkeypatch.setattr(state_module, "solve_horizon", flaky)
    solution = state.solve_plan(state.horizon_problem())
    assert calls == [True, False] and state.last_fallback == "sum"
    assert solution.expected_wins is None and solution.slopes is not None
