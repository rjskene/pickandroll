from datetime import UTC, datetime

import pytest

from pickandroll.draft import DraftState, Keeper, KeeperInvalid, KeeperLogged, LeagueSettings
from pickandroll.projections import Cat, ProjectionSet


def make_state(pool, position=3, num_teams=4, keepers=()):
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    settings = LeagueSettings(num_teams=num_teams)
    return DraftState(
        settings=settings, projections=ps, my_team="me", my_position=position, keepers=keepers
    )


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


# --------------------------------------------------------------------------- keepers
# Four teams, my seat 3: my slots are 3, 6, 11, 14, 19, 22, 27, ... 51; team 4 picks 4 and 5.
def _best(pool, n):
    return make_state(pool).z["total"].nlargest(n).index.tolist()


def _team(state, overall):
    pos = state.owner_of(overall)[1]
    return state.my_team if pos == state.my_position else f"Team {pos}"


def _draft_to(state, overall):
    """Draft the best available player for every pick before ``overall``."""
    while state.next_overall < overall:
        state.apply_pick(_team(state, state.next_overall), state.available[0])


def test_keepers_are_taken_and_mine_are_on_my_roster_from_pick_one(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(None, 7, a), Keeper(None, 13, b), Keeper(1, 2, c)])
    assert {a, b, c} <= state.taken and not {a, b, c} & set(state.available)
    assert state.picks == [] and state.next_overall == 1
    assert state.my_roster == [a, b] and state.open_slots == 11
    assert len(state.my_slots) == 13 and len(state.my_picks) == 11
    assert {27, 51} <= set(state.my_slots) and not {27, 51} & set(state.my_picks)
    problem = state.horizon_problem()
    assert len(problem.picks) == 11 and {a, b} <= problem.locks
    assert c not in problem.z.index


def test_a_keeper_slot_is_logged_when_the_draft_reaches_it(pool):
    a, b, c = _best(pool, 3)
    # Pick 1 is team 1's keeper; picks 4 and 5, team 4's first two, are both keepers.
    state = make_state(pool, keepers=[Keeper(1, 1, a), Keeper(4, 1, b), Keeper(4, 2, c)])
    assert [(p.overall, p.team, p.player_id) for p in state.picks] == [(1, "Team 1", a)]
    _draft_to(state, 4)
    assert [(p.overall, p.team, p.player_id) for p in state.picks[3:]] == [
        (4, "Team 4", b),
        (5, "Team 4", c),
    ]
    assert state.next_overall == 6 and state.on_the_clock


def test_a_keeper_slot_takes_only_its_keeper(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(1, 1, a), Keeper(2, 2, b)])  # b: pick 7
    assert state.apply_pick("Team 1", a, 1) is state.picks[0]
    with pytest.raises(ValueError, match="pick 1 is a keeper slot"):
        state.apply_pick("Team 1", c, 1)
    with pytest.raises(ValueError, match="is kept with pick 7"):
        state.apply_pick("Team 2", b)
    assert len(state.picks) == 1


def test_sync_passes_a_keeper_slot_in_the_feed_and_refuses_another_player_there(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(2, 1, b)])
    feed = [(1, "Team 1", a), (2, "Team 2", b), (3, "me", c)]
    assert [p.overall for p in state.sync(feed)] == [1, 3]
    assert [p.player_id for p in state.picks] == [a, b, c]
    assert state.sync(feed) == []
    wrong = make_state(pool, keepers=[Keeper(2, 1, b)])
    with pytest.raises(ValueError, match="pick 2 is a keeper slot"):
        wrong.sync([(1, "Team 1", a), (2, "Team 2", c)])


def test_undo_takes_back_the_last_real_pick_with_the_keepers_after_it(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(1, 1, a), Keeper(4, 1, b), Keeper(4, 2, c)])
    _draft_to(state, 4)
    mine = state.picks[2].player_id
    assert [(p.overall, p.player_id) for p in state.undo()] == [(3, mine), (4, b), (5, c)]
    assert state.next_overall == 3 and {b, c} <= state.taken
    assert [p.overall for p in state.undo()] == [2]
    with pytest.raises(ValueError, match="no picks to undo"):
        state.undo()
    assert [p.player_id for p in state.picks] == [a]


def test_keepers_count_on_their_teams_and_in_the_replacement_window(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(None, 7, a), Keeper(1, 2, b), Keeper(2, 5, c)])
    totals = state.team_totals()
    assert totals["picks"].to_dict() == {"Team 1": 1, "Team 2": 1, "me": 1, "Team 4": 0}
    level = state.replacement_level()
    finals = state.projected_finals()
    assert finals.loc["Team 1", "pts"] == pytest.approx(state.z.loc[b, "pts"] + 12 * level["pts"])
    # The window is the one a board with the three keepers already drafted would have.
    drafted = make_state(pool)
    drafted.sync([(1, "Team 1", b), (2, "Team 2", c), (3, "me", a)])
    assert state.replacement_level().equals(drafted.replacement_level())


def test_team_names_are_not_taken_from_keeper_picks(pool):
    a, b = _best(pool, 2)
    state = make_state(pool, keepers=[Keeper(1, 2, a)])  # pick 8
    state.apply_pick("Sharks", b)
    _draft_to(state, 8)
    assert state.picks[7].player_id == a and state.picks[7].team == "Team 1"
    assert state.team_names()[1] == "Sharks"


@pytest.mark.parametrize(
    ("keepers", "message", "index"),
    [
        ([Keeper(None, 7, "nobody")], "unknown player", 0),
        ([Keeper(None, 14, "p1")], "round outside", 0),
        ([Keeper(5, 7, "p1")], "position outside", 0),
        ([Keeper(None, 7, "p1"), Keeper(1, 3, "p1")], "kept twice", 1),
        ([Keeper(None, 7, "p1"), Keeper(3, 7, "p2")], "pick 27 is already", 1),
    ],
)
def test_a_wrong_keeper_table_is_refused(pool, keepers, message, index):
    with pytest.raises(KeeperInvalid, match=message) as refused:
        make_state(pool, keepers=keepers)
    assert refused.value.index == index  # the API names the row with it


def test_my_keepers_follow_my_seat_until_the_first_real_pick(pool):
    a, b = _best(pool, 2)
    state = make_state(pool, keepers=[Keeper(None, 1, a), Keeper(1, 1, b)])
    assert [p.overall for p in state.picks] == [1]
    state.set_my_position(2)  # my round-1 keeper now takes pick 2, right after team 1's
    assert [(p.overall, p.team, p.player_id) for p in state.picks] == [
        (1, "Team 1", b),
        (2, "me", a),
    ]
    assert state.my_slots[0] == 2 and state.my_roster == [a]
    with pytest.raises(ValueError, match="pick 1 is already"):
        state.set_my_position(1)  # my keeper would share pick 1 with team 1's
    assert state.my_position == 2 and len(state.picks) == 2
    state.apply_pick("Team 3", state.available[0])
    with pytest.raises(ValueError, match="already has picks"):
        state.set_my_position(4)


def test_set_keepers_changes_only_the_slots_not_reached(pool):
    a, b, c, d = _best(pool, 4)
    state = make_state(pool, keepers=[Keeper(1, 1, a)])
    state.set_keepers([Keeper(2, 1, b)])  # before the first real pick: the whole table
    assert state.picks == [] and a in state.available and b in state.taken
    state.apply_pick("Team 1", c)
    assert state.picks[1].player_id == b
    state.set_keepers([Keeper(2, 1, b), Keeper(1, 2, d)])  # pick 8 is not reached yet
    assert d in state.taken
    with pytest.raises(KeeperLogged, match="pick 2 is in the log"):
        state.set_keepers([Keeper(1, 2, d)])
    # A new keeper at a slot already drafted is a change to the log too (the API's 409).
    with pytest.raises(KeeperLogged, match="pick 1 is in the log"):
        state.set_keepers([Keeper(2, 1, b), Keeper(1, 1, c)])
    # A player already drafted cannot be kept at a later slot (the API's 400, by row).
    with pytest.raises(KeeperInvalid, match="drafted with pick 1") as refused:
        state.set_keepers([Keeper(2, 1, b), Keeper(1, 2, c)])
    assert refused.value.index == 1
    assert state.keepers == (Keeper(2, 1, b), Keeper(1, 2, d))
    assert [p.player_id for p in state.picks] == [c, b]


def test_the_rooms_record_wins_over_a_wrong_keeper_entry(pool):
    a, b, c = _best(pool, 3)
    state = make_state(pool, keepers=[Keeper(1, 1, a), Keeper(2, 2, b)])  # b: pick 7
    # Yahoo's pick 1 is someone else: team 1's entry goes, an ordinary pick stays.
    assert state.replace_pick(1, "Team 1", c) == [Keeper(1, 1, a)]
    assert state.picks[0].player_id == c and not state.is_keeper_pick(state.picks[0])
    assert a in state.available and state.undo()[0].player_id == c
    # Yahoo's pick 1 is team 2's keeper, taken early: both entries it contradicts go.
    state = make_state(pool, keepers=[Keeper(1, 1, a), Keeper(2, 2, b)])
    assert state.replace_pick(1, "Team 1", b) == [Keeper(1, 1, a), Keeper(2, 2, b)]
    assert state.keepers == ()
    # A pending keeper the room drafts at another slot: his entry is dropped, then applied.
    state = make_state(pool, keepers=[Keeper(2, 2, b)])
    assert state.drop_keeper(b) == Keeper(2, 2, b) and state.drop_keeper(b) is None
    assert state.apply_pick("Team 1", b).overall == 1
