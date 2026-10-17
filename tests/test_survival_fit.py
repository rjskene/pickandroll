"""#77: the survival table fit from a format's earlier drafts (``fit_survival_table``): the
kernel-weighted share of players still on the board by ADP, rows answering only while enough
players lie within their bandwidth, the ADP formula past them. Synthetic drafts only."""

import numpy as np
import pandas as pd
import pytest

from pickandroll.availability import (
    LEAGUE_FROM_ADP,
    LeagueSurvivalTable,
    availability,
    blend_with_formula,
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
    # Each at its draft's weight: another format's draft counts half.
    weighted = survival_counts([90.0, 95.0, 101.0, 140.0], [90, 140], [1.0, 0.5, 0.5, 0.5])
    assert weighted.to_dict() == {90: 2.0, 140: 0.5}


def test_a_draft_counts_at_its_weight():
    """Two drafts that disagree: a weight of a half pulls the share a third of the way, not half,
    toward the lighter draft; weights of zero drop it; the invariants hold either way."""
    adps = np.arange(1, 201, dtype=float)
    a1, y1 = drafts(1, adps, seed=1)
    # The second draft takes everyone about 15 picks after their ADP.
    _, y2 = drafts(1, adps + 15.0, seed=2)
    a2 = adps.copy()
    adp, overall = np.concatenate([a1, a2]), np.concatenate([y1, y2])
    w = np.concatenate([np.ones(len(a1)), np.full(len(a2), 0.5)])
    one, _ = fit_survival_table(a1, y1, PICKS)
    other, _ = fit_survival_table(a2, y2, PICKS)
    pooled, counts = fit_survival_table(adp, overall, PICKS, weights=w)
    zero = np.concatenate([np.ones(len(a1)), np.zeros(len(a2))])
    alone, _ = fit_survival_table(adp, overall, PICKS, weights=zero)
    cell = (110, 100)
    expected = (2 * one.table.loc[cell] + other.table.loc[cell]) / 3
    assert pooled.table.loc[cell] == pytest.approx(expected, abs=1e-9)
    assert alone.table.loc[cell] == pytest.approx(one.table.loc[cell], abs=1e-9)
    assert counts[100] == pytest.approx(1.5 * survival_counts(adps, [100])[100])
    s = pooled.table.to_numpy()
    assert (np.diff(s, axis=1) <= 1e-12).all()
    assert (s >= pooled.undrafted.to_numpy()[:, None] - 1e-12).all()
    with pytest.raises(ValueError, match="one weight"):
        fit_survival_table(adp, overall, PICKS, weights=w[:-1])


def test_the_written_table_reads_back():
    table, _ = fit_survival_table(*drafts(2, np.arange(1, 201, dtype=float)), PICKS)
    frame = survival_frame(table)
    assert list(frame.columns) == ["adp", *range(1, PICKS + 1), "undrafted"]
    back = LeagueSurvivalTable.from_frame(frame)
    pd.testing.assert_frame_equal(back.table, table.table, check_names=False)
    assert back.undrafted.to_numpy() == pytest.approx(table.undrafted.to_numpy())


def test_the_blend_shrinks_each_cell_toward_the_formula_by_one_draft():
    table, _ = fit_survival_table(*drafts(1, np.arange(1, 201, dtype=float)), PICKS)
    one, three = blend_with_formula(table, 1), blend_with_formula(table, 3)
    for a, k in ((95, 80), (110, 120), (130, PICKS)):
        formula = availability(pd.Series([float(a)]), k).iloc[0]
        # One draft is half the drafts' share, half the formula's; three drafts are 75/25.
        assert one.table.loc[a, k] == pytest.approx(0.5 * table.table.loc[a, k] + 0.5 * formula)
        assert three.table.loc[a, k] == pytest.approx(0.75 * table.table.loc[a, k] + 0.25 * formula)
    # The formula has no undrafted mass: the undrafted share shrinks by the same weight.
    assert one.undrafted.to_numpy() == pytest.approx(0.5 * table.undrafted.to_numpy())
    for blended in (one, three):
        s = blended.table.to_numpy()
        assert (np.diff(s, axis=1) <= 1e-12).all(), "S never rises with the pick"
        assert (s >= blended.undrafted.to_numpy()[:, None] - 1e-12).all()
        assert blended.picks == table.picks and blended.max_adp == table.max_adp
    # A fractional D (another format's draft at half weight): 1.5 drafts is 60/40.
    mixed = blend_with_formula(table, 1.5)
    formula = availability(pd.Series([110.0]), 120).iloc[0]
    assert mixed.table.loc[110, 120] == pytest.approx(
        0.6 * table.table.loc[110, 120] + 0.4 * formula
    )
    with pytest.raises(ValueError, match="drafts must be"):
        blend_with_formula(table, 0)


def test_bad_observations_are_refused():
    with pytest.raises(ValueError, match="one ADP and one pick"):
        fit_survival_table([1.0, 2.0], [1.0], PICKS)
    with pytest.raises(ValueError, match="one ADP and one pick"):
        fit_survival_table([1.0, np.nan], [1.0, 2.0], PICKS)
    with pytest.raises(ValueError, match="picks must be"):
        fit_survival_table([1.0], [1.0], 0)
