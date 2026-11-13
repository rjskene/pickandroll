"""The replay's causal belief and its weights (#172, PR B1): the forecaster's figure updated with
the games played before the day, nothing later; the weights fitted on earlier seasons only."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from pickandroll.sim import fit as fitmod
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.belief import CausalBelief, consistent, newcomer_prior, shrunk
from pickandroll.sim.engine import STATS
from tests.sim.sim_league import inputs, make_data_dir, make_setup

D1 = date(2024, 10, 22)
D2 = D1 + timedelta(2)
D3 = D1 + timedelta(3)
PRIOR = {
    "pts": 10.0,
    "threes": 1.0,
    "reb": 5.0,
    "ast": 3.0,
    "stl": 1.0,
    "blk": 1.0,
    "tov": 2.0,
    "fgm": 4.0,
    "fga": 8.0,
    "ftm": 2.0,
    "fta": 2.0,
}
LINES = {
    D1: {"pts": 16.0, "threes": 1.0, "fgm": 7.0, "fga": 10.0, "ftm": 1.0, "fta": 2.0},
    D2: {"pts": 4.0, "threes": 0.0, "fgm": 2.0, "fga": 9.0, "ftm": 0.0, "fta": 0.0},
    D3: {"pts": 22.0, "threes": 2.0, "fgm": 8.0, "fga": 14.0, "ftm": 4.0, "fta": 4.0},
}
W2 = dict.fromkeys(STATS, 2.0)


def belief(lines=LINES, weights=W2, newcomer=None, projection=None, players=(1,)):
    return CausalBelief(
        players,
        {1: PRIOR} if projection is None else projection,
        {1: lines},
        weights,
        newcomer or {},
    )


# --------------------------------------------------------------------------- the belief by hand
def test_the_belief_is_the_prior_weighed_against_the_games_before_the_day():
    b = belief()
    # Before his first game: the projection itself.
    assert b.of(1, D1) == consistent(PRIOR)
    # The line dated D1 is in no belief of D1, and in the one of the day after.
    one = b.of(1, D1 + timedelta(1))
    assert one["pts"] == pytest.approx((2 * 10 + 16) / 3)
    assert one["fgm"] == pytest.approx((2 * 4 + 7) / 3)
    assert one["fga"] == pytest.approx((2 * 8 + 10) / 3)
    assert one["reb"] == pytest.approx(2 * 5 / 3)  # a stat the line lacks counts as zero
    # D2's line is not in D2's belief: the same as the day before.
    assert b.of(1, D2) == one
    two = b.of(1, D2 + timedelta(1))
    assert two["pts"] == pytest.approx((20 + 16 + 4) / 4)
    # The percentages follow from the makes and attempts, each shrunk on its own.
    assert two["fgm"] / two["fga"] == pytest.approx((8 + 7 + 2) / (16 + 10 + 9))
    assert two["ftm"] / two["fta"] == pytest.approx((4 + 1 + 0) / (4 + 2 + 0))
    three = b.of(1, D3 + timedelta(30))
    assert three["pts"] == pytest.approx((20 + 16 + 4 + 22) / 5)
    assert three["threes"] == pytest.approx((2 + 1 + 0 + 2) / 5)
    assert b.games_before(1, D1) == 0 and b.games_before(1, D3) == 2
    assert b.games_before(1, D3 + timedelta(1)) == 3
    # The weights are per stat.
    heavy = belief(weights={**W2, "pts": 98.0}).of(1, D1 + timedelta(1))
    assert heavy["pts"] == pytest.approx((98 * 10 + 16) / 99)
    assert heavy["fgm"] == pytest.approx(one["fgm"])


def test_the_belief_on_a_day_reads_every_player_and_passes_through_consistent():
    odd = {D1: {"threes": 3.0, "fgm": 2.0, "fga": 4.0}}  # a line with more threes than makes
    b = belief(lines=odd, projection={1: {**PRIOR, "threes": 1.0, "fgm": 1.0}})
    after = b.of(1, D1 + timedelta(1))
    # Shrunk alone, threes would be (2 + 3) / 3 against makes of (2 + 2) / 3: held to the makes.
    assert after["threes"] == pytest.approx(after["fgm"]) == pytest.approx((2 * 1 + 2) / 3)
    assert shrunk({"threes": 1.0, "fgm": 1.0}, {"threes": 3.0, "fgm": 2.0}, 1, W2)["threes"] == (
        pytest.approx(4 / 3)
    )
    on = b.on(D1 + timedelta(1))
    assert set(on) == {1} and on[1] == after
    assert b.on(D1 + timedelta(1)) is on  # the last day read is kept


def test_a_player_nobody_projected_is_believed_from_the_day_after_his_first_game():
    projection = {1: PRIOR, 2: {**PRIOR, "pts": 20.0}, 3: {**PRIOR, "pts": 30.0}}
    newcomer = newcomer_prior(projection, [2, 3, 9])  # 9 is not projected: not in the mean
    assert newcomer["pts"] == pytest.approx(25.0) and newcomer["reb"] == pytest.approx(5.0)
    b = CausalBelief(
        [1, 2, 3, 9],
        projection,
        {9: {D2: {"pts": 13.0, "fgm": 5.0, "fga": 9.0}}},
        W2,
        newcomer,
    )
    assert b.of(9, D1) is None and b.of(9, D2) is None and 9 not in b.on(D2)
    after = b.of(9, D2 + timedelta(1))
    assert after["pts"] == pytest.approx((2 * 25 + 13) / 3)
    assert after["fgm"] == pytest.approx((2 * 4 + 5) / 3)
    assert 9 in b.on(D2 + timedelta(1))
    # A stat is averaged over the undrafted players that have it.
    partial = newcomer_prior({2: {"pts": 20.0}, 3: {"pts": 30.0, "reb": 7.0}}, [2, 3])
    assert partial == {"pts": 25.0, "reb": 7.0}
    assert newcomer_prior(projection, []) == {}
    # Without a newcomer's prior an unprojected player stays out of the belief.
    alone = CausalBelief([9], {}, {9: {D1: {"pts": 1.0}}}, W2, {})
    assert alone.of(9, D3) is None


def test_the_replay_world_reads_the_causal_belief_by_day_and_the_gate_a_fixed_one():
    setup = make_setup(teams=2, spots=3, pool=2, weeks=2, playoff_weeks=1)
    k = setup.pool[0]
    days = [d for d in setup.days if setup.players[k].nba_team in setup.schedule[d]]
    lines = {k: {days[0]: {"pts": 40.0}}}
    w = rn.replay_world(setup, lines, 1, 1, 0, {"pts": 4.0})
    assert w.belief == "causal"
    before, after = w.beliefs_on(days[0]), w.beliefs_on(days[0] + timedelta(1))
    assert before[k] == consistent(setup.projection[k])
    p = setup.projection[k]["pts"]
    assert after[k]["pts"] == pytest.approx((4 * p + 40) / 5)
    # A stat without a weight takes the default.
    assert after[k]["reb"] == pytest.approx(
        fitmod.W_DEFAULT * setup.projection[k]["reb"] / (fitmod.W_DEFAULT + 1)
    )
    with pytest.raises(ValueError, match="by day"):
        w.beliefs(0)
    fixed = rn.replay_world(setup, lines, 1, 1, 0, belief="fixed")
    assert fixed.causal is None
    assert all(fixed.beliefs_on(d) == setup.projection for d in setup.days)
    with pytest.raises(ValueError, match="belief"):
        rn.replay_world(setup, lines, 1, 1, 0, belief="refreshed")


def test_a_forward_world_counts_its_refreshes_by_monday_as_the_day_loop_did():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 1, 0, 0.0)
    count, seen = 0, {}
    for d in setup.days:
        if setup.week_of(d) is None:
            continue
        if d.weekday() == 0 and d != setup.start:
            count += 1
        seen[d] = count
    assert {d: w.week_index(d) for d in seen} == seen
    assert w.beliefs_on(setup.days[-1]) is w.beliefs(seen[setup.days[-1]])


# --------------------------------------------------------------------------- the weights
def season_of(rng: np.random.Generator, players: int = 60, games: int = 40):
    """Players' true points rates and their lines: Poisson games around each rate."""
    rate = {k: float(rng.uniform(5.0, 25.0)) for k in range(players)}
    lines = {
        k: {D1 + timedelta(2 * g): {"pts": float(rng.poisson(r))} for g in range(games)}
        for k, r in rate.items()
    }
    return rate, lines


def test_a_noisy_forecaster_gets_a_smaller_weight_than_an_accurate_one():
    rng = np.random.default_rng(5)
    rate, lines = season_of(rng)
    accurate = {k: {"pts": r} for k, r in rate.items()}
    noisy = {k: {"pts": r * float(np.exp(0.6 * rng.standard_normal()))} for k, r in rate.items()}
    good = fitmod.belief_weights([fitmod.BeliefSample(2023, 2022, accurate, lines)], 2025)
    bad = fitmod.belief_weights([fitmod.BeliefSample(2023, 2022, noisy, lines)], 2025)
    assert bad.weights["pts"] < good.weights["pts"]
    assert good.weights["pts"] in fitmod.W_GRID and bad.weights["pts"] in fitmod.W_GRID
    assert good.seasons == (2023,) and good.default is False
    # Stats nobody was projected on keep the default and are named.
    assert good.weights["reb"] == fitmod.W_DEFAULT and "reb" in good.unobserved
    assert good.payload()["grid"] == list(fitmod.W_GRID)


def test_a_tie_takes_the_larger_weight_and_no_sample_takes_the_default():
    exact = {k: {D1 + timedelta(g): {"pts": 12.0} for g in range(5)} for k in range(3)}
    prior = {k: {"pts": 12.0} for k in range(3)}  # every weight predicts every game exactly
    tied = fitmod.belief_weights([fitmod.BeliefSample(2023, 2022, prior, exact)], 2025)
    assert tied.weights["pts"] == max(fitmod.W_GRID)
    small = fitmod.belief_weights(
        [fitmod.BeliefSample(2023, 2022, prior, exact)], 2025, grid=(5, 3)
    )
    assert small.weights["pts"] == 5
    none = fitmod.belief_weights([], 2025)
    assert none.default is True and none.seasons == ()
    assert none.weights == dict.fromkeys(STATS, fitmod.W_DEFAULT)
    assert fitmod.W_DEFAULT == 10.0 and fitmod.W_GRID == (2, 4, 6, 10, 16, 25, 40, 65, 100)


def test_the_weights_refuse_the_hold_out_as_a_season_or_as_its_forecaster():
    _, lines = season_of(np.random.default_rng(1), players=3, games=3)
    prior = {k: {"pts": 10.0} for k in lines}
    with pytest.raises(fitmod.HoldOutError):
        fitmod.belief_weights([fitmod.BeliefSample(2025, 2024, prior, lines)], 2025)
    with pytest.raises(fitmod.HoldOutError):
        fitmod.belief_weights([fitmod.BeliefSample(2026, 2025, prior, lines)], 2025)


def test_the_weights_read_only_seasons_earlier_than_the_replayed_one(tmp_path: Path):
    data = make_data_dir(tmp_path, seasons=(2022, 2023, 2024, 2025, 2026))
    folder = data / reader.LOGS_DIR
    for later in (2025, 2026):  # the hold-out and a season after: never opened
        (folder / f"{later}.json").write_text("not a log")
    fitted = reader.belief_weights(data, 2024, 2025)
    assert fitted.seasons == (2023,) and fitted.default is False
    assert set(fitted.weights) == set(STATS)
    assert all(w in fitmod.W_GRID for w in fitted.weights.values())
    assert reader.seasons_on_file(data, 2024) == [2022, 2023]
    # 2022's prior season is not on file: nothing qualifies, the default stands.
    assert reader.belief_weights(data, 2023, 2025).default is True
    # A season after the hold-out skips it and never opens its file.
    assert reader.belief_weights(data, 2026, 2025).seasons == (2023, 2024)
    # The weights are a pure function of what was read: the same twice.
    assert reader.belief_weights(data, 2024, 2025) == fitted
