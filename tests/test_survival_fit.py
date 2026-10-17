"""#77: the survival table fit from a format's earlier drafts (``fit_survival_table``): the
kernel-weighted share of players still on the board by ADP, rows answering only while enough
players lie within their bandwidth, the ADP formula past them. Synthetic drafts only."""

import numpy as np
import pandas as pd
import pytest

from pickandroll.availability import (
    LEAGUE_FROM_ADP,
    LeagueSurvivalTable,
    fit_survival_table,
    survival_counts,
    survival_frame,
)
from pickandroll.availability.league import bandwidth

PICKS = 156


def drafts(n: int, adps: np.ndarray, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """``n`` drafts of the players with ``adps``: each draft takes the first ``PICKS`` by ADP
    plus noise that widens late; the rest go undrafted (NaN)."""
    rng = np.random.default_rng(seed)
    a_all, y_all = [], []
    for _ in range(n):
        order = np.argsort(adps + rng.normal(0, 2 + 0.1 * adps), kind="stable")
        overall = np.full(len(adps), np.nan)
        # With fewer players than picks, the rest of the picks go to players with no ADP.
        taken = order[:PICKS]
        overall[taken] = np.arange(1, len(taken) + 1)
        a_all.append(adps)
        y_all.append(overall)
    return np.concatenate(a_all), np.concatenate(y_all)


def test_the_table_follows_the_drafts():
    adps = np.arange(1, 201, dtype=float)
    adp, overall = drafts(4, adps)
    table, counts = fit_survival_table(adp, overall, PICKS)
    assert isinstance(table, LeagueSurvivalTable) and table.picks == PICKS
    s = table.table.to_numpy()
    assert (np.diff(s, axis=1) <= 1e-12).all(), "S never rises with the pick"
    assert (s >= table.undrafted.to_numpy()[:, None] - 1e-12).all(), "nor falls below undrafted"
    assert 0.0 <= s.min() and s.max() <= 1.0
    # ADP 100 is on the board early, mostly gone by the end; ADP 150 goes undrafted more often.
    assert table.table.loc[100, 60] > 0.95 and table.table.loc[100, PICKS] < 0.3
    assert table.undrafted[150] > table.undrafted[100]
    # The counts are the players within each row's bandwidth, over every draft.
    for a in (90, 120, 150):
        assert counts[a] == int((np.abs(adp - a) <= bandwidth(a)).sum())
    assert counts[100] == 4 * len([x for x in adps if abs(x - 100) <= bandwidth(100)])


def test_rows_answer_only_while_their_counts_clear_the_minimum():
    adps = np.arange(1, 126, dtype=float)  # the market's ADP list stops at 125
    adp, overall = drafts(1, adps)
    table, counts = fit_survival_table(adp, overall, PICKS, min_count=20)
    last = table.max_adp
    assert counts[last] >= 20 and counts[last + 1] < 20
    assert all(counts[a] >= 20 for a in range(LEAGUE_FROM_ADP, last + 1))
    assert list(table.table.index) == list(range(1, last + 1))
    # Past the boundary, and before the table's first row, the ADP formula answers (NaN here).
    s = table.survival(pd.Series([60.0, 100.0, last + 1.0]), 120)
    assert np.isnan(s.iloc[0]) and not np.isnan(s.iloc[1]) and np.isnan(s.iloc[2])
    # More drafts carry the same rows further.
    more, _ = fit_survival_table(*drafts(3, adps), PICKS, min_count=20)
    assert more.max_adp > last
    # A first row that is already thin: no table, the session simulates.
    none, counts = fit_survival_table(adp, overall, PICKS, min_count=10_000)
    assert none is None and counts[LEAGUE_FROM_ADP] < 10_000


def test_the_counts_count_players_within_the_bandwidth():
    counts = survival_counts([90.0, 95.0, 101.0, 140.0], [90, 140])
    assert bandwidth(90) == pytest.approx(12.2)
    assert counts.to_dict() == {90: 3, 140: 1}


def test_the_written_table_reads_back():
    table, _ = fit_survival_table(*drafts(2, np.arange(1, 201, dtype=float)), PICKS)
    frame = survival_frame(table)
    assert list(frame.columns) == ["adp", *range(1, PICKS + 1), "undrafted"]
    back = LeagueSurvivalTable.from_frame(frame)
    pd.testing.assert_frame_equal(back.table, table.table, check_names=False)
    assert back.undrafted.to_numpy() == pytest.approx(table.undrafted.to_numpy())


def test_bad_observations_are_refused():
    with pytest.raises(ValueError, match="one ADP and one pick"):
        fit_survival_table([1.0, 2.0], [1.0], PICKS)
    with pytest.raises(ValueError, match="one ADP and one pick"):
        fit_survival_table([1.0, np.nan], [1.0, 2.0], PICKS)
    with pytest.raises(ValueError, match="picks must be"):
        fit_survival_table([1.0], [1.0], 0)
