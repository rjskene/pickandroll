"""Phase 3 of KEEPERS (docs/KEEPERS.md §1.1): availability in market space. Keepers are not in the
market, so a player's ADP counts only the non-keepers ahead of him and a pick counts only the
market's picks; the league's own survival table is read on those two axes."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from pickandroll.availability import (
    LEAGUE_FROM_ADP,
    LeagueSurvivalTable,
    conditional_availability,
)
from pickandroll.availability.adp import SPREAD_BASE, SPREAD_GROWTH
from pickandroll.draft import DraftState, Keeper, LeagueSettings, latent_slots
from pickandroll.draft.league_sim import _fresh_state
from pickandroll.projections import ProjectionSet

from .conftest import synthetic_pool


def make_state(pool, keepers=(), position=3):
    """Four teams (52 picks) with the ADP set to the z ranking: p's ADP is its rank."""
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    state = DraftState(
        settings=LeagueSettings(num_teams=4),
        projections=ps,
        my_team="me",
        my_position=position,
        keepers=tuple(keepers),
    )
    order = state.z["total"].sort_values(ascending=False).index
    state.set_adp(pd.Series(np.arange(1.0, len(order) + 1), index=order), "test")
    return state


def ranked(state):
    """Player ids by ADP: ``ranked(state)[a - 1]`` has ADP ``a``."""
    return list(state.effective_adp().sort_values().index)


def by_hand(state, players=None):
    """The ADP model read in market space, written out."""
    adp = state.effective_adp()
    if players is not None:
        adp = adp.reindex(players)
    market = state.market_adp(adp)
    picks = state.my_remaining_picks
    frame = conditional_availability(
        market,
        now=state.market_pick(state.next_overall),
        picks=[state.market_pick(k) for k in picks],
        spread=SPREAD_BASE + SPREAD_GROWTH * market,
    )
    frame.columns = picks
    return frame


def test_without_keepers_market_space_is_the_plain_model(pool):
    state = make_state(pool)
    assert state.spread_base == 1.5 and state.spread_growth == 0.15
    assert all(state.market_pick(k) == k for k in range(1, 53))
    pd.testing.assert_series_equal(state.market_adp(), state.effective_adp())
    adp = state.effective_adp()
    plain = conditional_availability(
        adp, now=1, picks=state.my_remaining_picks, spread=1.5 + 0.15 * adp
    )
    pd.testing.assert_frame_equal(state.availability(), plain)


def test_keepers_leave_the_market_on_both_axes(pool):
    probe = make_state(pool)
    p = ranked(probe)
    # ADP 3 kept by team 1 in round 2 (pick 8), ADP 10 by team 2 in round 5 (pick 18), ADP 30
    # by me in round 7 (pick 27).
    keepers = [Keeper(1, 2, p[2]), Keeper(2, 5, p[9]), Keeper(None, 7, p[29])]
    state = make_state(pool, keepers)
    assert sorted(state.keeper_slots) == [8, 18, 27]
    ahead = state.keepers_ahead()
    assert ahead[p[1]] == 0 and ahead[p[19]] == 2 and ahead[p[39]] == 3
    market = state.market_adp()
    assert market[p[19]] == 18.0 and market[p[39]] == 37.0
    assert [state.market_pick(k) for k in (1, 8, 9, 18, 19, 28)] == [1, 8, 8, 17, 17, 25]
    pd.testing.assert_frame_equal(state.availability(), by_hand(state))
    # By my pick 30 three keeper slots have passed, but only two keepers were ahead of ADP 20:
    # the market has spent one pick fewer on his rivals than the overall-pick model counts.
    assert 27 not in state.my_remaining_picks and 30 in state.my_remaining_picks
    overall = conditional_availability(
        state.effective_adp(), now=1, picks=[30], spread=1.5 + 0.15 * market
    )
    assert state.availability().loc[p[19], 30] > 1.5 * overall.loc[p[19], 30]
    # Three keepers ahead of ADP 40 and three slots passed: the two models agree.
    assert state.availability().loc[p[39], 30] == pytest.approx(overall.loc[p[39], 30])


def test_a_keeper_slot_reached_moves_nothing(pool):
    """Every keeper in the table counts, logged or not: reaching his slot changes neither a
    later player's adjusted ADP nor the market pick count."""
    p = ranked(make_state(pool))
    state = make_state(pool, [Keeper(1, 2, p[2])])
    before = state.market_adp()
    while state.next_overall <= 8:
        pos = state.owner_of(state.next_overall)[1]
        team = state.my_team if pos == state.my_position else f"Team {pos}"
        state.apply_pick(team, state.available[0])
    assert state.picks[7].player_id == p[2]  # the keeper's pick is logged
    pd.testing.assert_series_equal(state.market_adp(), before)
    assert state.market_pick(state.next_overall) == state.next_overall - 1
    pd.testing.assert_frame_equal(state.availability(), by_hand(state))


def test_a_dropped_keeper_leaves_both_axes(pool):
    p = ranked(make_state(pool))
    state = make_state(pool, [Keeper(1, 2, p[2]), Keeper(2, 5, p[9])])
    assert state.keepers_ahead()[p[19]] == 2 and state.market_pick(19) == 17
    state.drop_keeper(p[9])
    assert state.keepers_ahead()[p[19]] == 1 and state.market_pick(19) == 18


def test_the_sim_drafter_draws_in_market_space_with_the_session_spread(pool):
    p = ranked(make_state(pool))
    state = make_state(pool, [Keeper(1, 2, p[2])])
    state.spread_base, state.spread_growth = 2.0, 0.1
    slots = latent_slots(state, np.random.default_rng(5), noise=1.0)
    market = state.market_adp().reindex(state.available)
    eps = np.random.default_rng(5).standard_normal(len(market))
    expected = market + (2.0 + 0.1 * market) * eps
    pd.testing.assert_series_equal(slots, expected, check_names=False)
    # The survival build's drafters get the session's spread too.
    built = _fresh_state(state.settings, state.projections, None, (), (2.0, 0.1))
    assert (built.spread_base, built.spread_growth) == (2.0, 0.1)


# ---------------------------------------------------------------------- the league table
def drop_at(a, m):
    """The archive's shape, moved onto the rows the table answers for: S(m | a) is one up to
    pick a - 90, then falls over five picks."""
    return max(0.0, min(1.0, 1.0 - (m - (a - LEAGUE_FROM_ADP)) / 5.0))


def league_frame(rows=100, picks=53, undrafted=None, shape=drop_at):
    """A table in the archive's shape (adp, 1..picks, undrafted); the undrafted share floors
    each row."""
    data = {"adp": list(range(1, rows + 1))}
    for m in range(1, picks + 1):
        data[str(m)] = [shape(a, m) for a in range(1, rows + 1)]
    data["undrafted"] = undrafted if undrafted is not None else [0.0] * rows
    return pd.DataFrame(data)


def test_league_table_reads_its_shape_and_rejects_others():
    table = LeagueSurvivalTable.from_frame(league_frame())
    assert table.picks == 53 and table.max_adp == 100
    with pytest.raises(ValueError, match="undrafted"):
        LeagueSurvivalTable.from_frame(league_frame().drop(columns=["undrafted"]))
    with pytest.raises(ValueError, match="whole numbers"):
        LeagueSurvivalTable.from_frame(league_frame().rename(columns={"7": "seven"}))
    with pytest.raises(ValueError, match="pick columns"):
        LeagueSurvivalTable.from_frame(league_frame().drop(columns=["7"]))
    with pytest.raises(ValueError, match="ADPs 1..n"):
        LeagueSurvivalTable.from_frame(league_frame().iloc[1:])
    bad = league_frame()
    bad.loc[0, "3"] = 1.5
    with pytest.raises(ValueError, match="0..1"):
        LeagueSurvivalTable.from_frame(bad)


def test_league_table_answers_from_adp_90_interpolates_and_floors():
    assert LEAGUE_FROM_ADP == 90
    undrafted = [0.0] * 100
    undrafted[95] = 0.3  # ADP 96
    table = LeagueSurvivalTable.from_frame(league_frame(undrafted=undrafted))
    adp = pd.Series(
        {"a": 92.0, "b": 92.5, "c": 96.0, "edge": 90.0, "early": 50.0, "just": 89.5, "past": 101.0}
    )
    s = table.survival(adp, 5)
    assert s["a"] == pytest.approx(0.4) and s["b"] == pytest.approx(0.5)
    assert s["c"] == 1.0 and s["edge"] == 0.0
    # Before ADP 90 the table holds rows but does not answer; past its last row it has none.
    assert s[["early", "just", "past"]].isna().all()
    assert table.survival(adp, 20)["c"] == pytest.approx(0.3)  # never below the undrafted share
    cond = table.conditional(adp, now=3, picks=[3, 5])
    assert list(cond.columns) == [3, 5]
    assert cond.loc["a", 3] == 1.0 and cond.loc["a", 5] == pytest.approx(0.4 / 0.8)
    assert cond.loc[["early", "just", "past"]].isna().all().all()


def test_the_league_table_answers_late_and_the_normal_model_early():
    """Under survival: league a player at adjusted ADP 50 gets the normal model and one at 120
    the table, conditioned on the table's own S(now)."""
    pool = synthetic_pool(140)
    p = ranked(make_state(pool))
    state = make_state(pool, [Keeper(1, 2, p[2])])
    state.league_survival = LeagueSurvivalTable.from_frame(
        league_frame(rows=130, shape=lambda a, m: float(np.exp(-2.0 * m / a)))
    )
    assert state.availability_source == "league"
    while state.next_overall <= 10:  # past the keeper slot, so S(now) < 1
        pos = state.owner_of(state.next_overall)[1]
        team = state.my_team if pos == state.my_position else f"Team {pos}"
        state.apply_pick(team, state.available[0])
    market = state.market_adp()
    early, late = market[market == 50].index[0], market[market == 120].index[0]
    assert early in state.available and late in state.available
    frame = state.availability()
    model = by_hand(state)
    pd.testing.assert_series_equal(frame.loc[early], model.loc[early])

    now = state.market_pick(state.next_overall)
    assert now == state.next_overall - 1
    s_now = np.exp(-2.0 * now / 120)
    for k in state.my_remaining_picks:
        m = state.market_pick(k)
        expected = 1.0 if m <= now else np.exp(-2.0 * m / 120) / s_now
        assert frame.loc[late, k] == pytest.approx(expected)
    last = state.my_remaining_picks[-1]
    assert frame.loc[late, last] < model.loc[late, last] - 0.2  # not the normal model's answer
    # Every player before ADP 90 is the model's, every one from 90 the table's.
    known = market.reindex(frame.index) >= LEAGUE_FROM_ADP
    pd.testing.assert_frame_equal(frame.loc[~known], model.loc[~known])
    assert not np.allclose(frame.loc[known].to_numpy(), model.loc[known].to_numpy())
