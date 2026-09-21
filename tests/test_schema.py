import pandas as pd
import pytest

from pickandroll.projections import ProjectionSet, per_game_to_totals, split_positions, validate


def test_split_positions_handles_separators():
    assert split_positions("PG/SG") == ("PG", "SG")
    assert split_positions("PF, C") == ("PF", "C")
    assert split_positions("c") == ("C",)
    with pytest.raises(ValueError):
        split_positions("PG/QB")


def test_validate_accepts_synthetic_pool(pool):
    validate(pool)


def test_validate_rejects_missing_and_duplicates(pool):
    with pytest.raises(ValueError, match="missing"):
        validate(pool.drop(columns=["fga"]))
    dup = pd.concat([pool, pool.iloc[:1]])
    with pytest.raises(ValueError, match="duplicate"):
        validate(dup)


def test_validate_rejects_makes_over_attempts(pool):
    bad = pool.copy()
    bad.loc[bad.index[0], "fgm"] = bad.loc[bad.index[0], "fga"] + 5
    with pytest.raises(ValueError, match="fgm exceeds fga"):
        validate(bad)


def test_per_game_to_totals_scales_by_games(pool):
    per_game = pool.copy()
    per_game["pts"] = 20.0
    totals = per_game_to_totals(per_game)
    assert (totals["pts"] == 20.0 * pool["games"]).all()


def test_projection_set_positions(pool):
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=pd.Timestamp("2026-09-21"), df=pool
    )
    positions = ps.positions()
    assert set(positions) == set(pool.index)
    assert all(isinstance(v, tuple) and v for v in positions.values())
