import numpy as np
import pandas as pd
import pytest

from pickandroll.availability import SurvivalTable

from .test_draft_state import make_state


def small_table() -> SurvivalTable:
    picks = pd.DataFrame(
        [
            {"sim": 1, "player": "a", "overall": 1},
            {"sim": 1, "player": "b", "overall": 2},
            {"sim": 2, "player": "b", "overall": 1},
            {"sim": 2, "player": "c", "overall": 2},
        ]
    )
    return SurvivalTable.from_pick_numbers(
        picks, total_picks=3, sims=2, players=["a", "b", "c", "d"]
    )


def test_survival_from_pick_numbers():
    table = small_table()
    assert list(table.table.columns) == [1, 2, 3, 4]
    assert table.total_picks == 3
    assert table.table.loc["a"].tolist() == [1.0, 0.5, 0.5, 0.5]
    assert table.table.loc["b"].tolist() == [1.0, 0.5, 0.0, 0.0]
    assert table.table.loc["c"].tolist() == [1.0, 1.0, 0.5, 0.5]
    assert table.table.loc["d"].tolist() == [1.0, 1.0, 1.0, 1.0]
    assert table.median_pick()["b"] == 2.0
    assert table.median_pick()["d"] == 4.0


def test_conditional_survival_and_unknown_players():
    table = small_table()
    cond = table.conditional(["a", "c", "zz"], now=2, picks=[2, 3, 4])
    assert cond.loc["a", 2] == 1.0
    assert cond.loc["a", 3] == pytest.approx(1.0)
    assert cond.loc["c", 3] == pytest.approx(0.5)
    assert np.isnan(cond.loc["zz", 3])
    # b never lasted to pick 3 in any simulation: no credit for lasting longer.
    late = table.conditional(["b"], now=3, picks=[3, 4])
    assert late.loc["b", 4] == 0.0


def test_survival_round_trip(tmp_path):
    table = small_table()
    path = tmp_path / "survival.csv"
    table.save(path)
    back = SurvivalTable.load(path)
    assert back.sims == 2
    pd.testing.assert_frame_equal(back.table, table.table)


def test_draft_state_uses_survival_where_known(pool):
    state = make_state(pool, position=1, num_teams=4)
    state.apply_pick("them", state.z["total"].idxmax())  # my pick 8 is next after 7 others
    for _ in range(6):
        state.apply_pick("them", state.available[0])
    assert state.on_the_clock
    players = state.available[:5]
    picks = state.my_remaining_picks
    rows = {players[0]: [1.0] * (state.settings.total_picks + 1)}  # always survives
    rows[players[1]] = [1.0] * picks[0] + [0.0] * (state.settings.total_picks + 1 - picks[0])
    table = pd.DataFrame(rows, index=range(1, state.settings.total_picks + 2)).T
    state.survival = SurvivalTable(table=table, sims=10)
    avail = state.availability(players)
    assert avail.loc[players[0], picks[1]] == 1.0
    assert avail.loc[players[1], picks[1]] == 0.0
    # Players the table lacks keep the ADP model.
    adp_only = make_state(pool, position=1, num_teams=4)
    for p in state.picks:
        adp_only.apply_pick(p.team, p.player_id)
    assert avail.loc[players[3], picks[1]] == pytest.approx(
        adp_only.availability(players).loc[players[3], picks[1]]
    )
