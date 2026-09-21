import numpy as np

from pickandroll.projections import NINE_CAT, Cat, rank, zscores
from pickandroll.projections.zscores import category_values


def test_shape_and_columns(pool):
    z = zscores(pool)
    assert list(z.columns) == [c.value for c in NINE_CAT] + ["total"]
    assert len(z) == len(pool)
    assert np.isfinite(z.to_numpy()).all()


def test_pool_mean_zero_and_unit_std_for_counting_cats(pool):
    z = zscores(pool)
    for cat in (Cat.PTS, Cat.REB, Cat.AST):
        assert abs(z[cat.value].mean()) < 1e-9
        assert abs(z[cat.value].std(ddof=0) - 1.0) < 1e-9


def test_turnovers_are_flipped(pool):
    z = zscores(pool)
    worst = pool["tov"].idxmax()
    best = pool["tov"].idxmin()
    assert z.loc[worst, "tov"] < z.loc[best, "tov"]


def test_percentage_impact_rewards_volume(pool):
    df = pool.copy()
    a, b = df.index[:2]
    # Same FG% above the pool, but player a shoots ten times more often.
    pct = 0.60
    df.loc[a, ["fga", "fgm"]] = [1000.0, 1000.0 * pct]
    df.loc[b, ["fga", "fgm"]] = [100.0, 100.0 * pct]
    z = zscores(df)
    assert z.loc[a, "fg_pct"] > z.loc[b, "fg_pct"] > 0


def test_pool_size_iteration_changes_reference(pool):
    full = zscores(pool)
    top = zscores(pool, pool_size=20)
    # A tighter pool has a higher mean, so an average player scores lower against it.
    median_player = full["total"].sort_values().index[len(pool) // 2]
    assert top.loc[median_player, "total"] < full.loc[median_player, "total"]


def test_zero_games_players_score_zero(pool):
    df = pool.copy()
    df.loc[df.index[0], "games"] = 0
    z = zscores(df)
    assert (z.loc[df.index[0]] == 0).all()


def test_rank_orders_descending(pool):
    r = rank(zscores(pool))
    assert list(r) == sorted(r, reverse=True)


def test_category_values_impact_sums_to_zero(pool):
    cv = category_values(pool)
    assert abs(cv["fg_pct"].sum()) < 1e-6
    assert abs(cv["ft_pct"].sum()) < 1e-6
