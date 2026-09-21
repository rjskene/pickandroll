from pathlib import Path

import pandas as pd
import pytest

from pickandroll.optim import Slot
from pickandroll.projections import (
    apply_positions,
    load_positions,
    positions_from_table,
    validate,
    zscores,
)
from pickandroll.sources.bbm import is_bbm_csv, load_bbm, load_bbm_csv, normalize_bbm_csv

DATA = Path(__file__).resolve().parents[1] / "data"


def synthetic_csv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2],
            "last_name": ["Jokic", "Doncic"],
            "first_name": ["Nikola", "Luka"],
            "games": [70, 65],
            "minutes": [2400, 2300],
            "field_goals_attempted": [1200, 1300],
            "field_goals": [700, 600],
            "free_throws_attempted": [500, 600],
            "free_throws": [410, 470],
            "threes": [80, 250],
            "threes_attempted": [200, 650],
            "offensive_rebounds": [200, 60],
            "defensive_rebounds": [650, 500],
            "assists": [700, 600],
            "blocks": [60, 30],
            "steals": [100, 90],
            "turnovers": [250, 280],
            "fouls": [180, 150],
            "technicals": [3, 8],
            "double_doubles": [55, 30],
            "triple_doubles": [25, 15],
            "comments": [None, "hamstring, day to day"],
        }
    )


def test_normalize_csv_rebuilds_points_and_rebounds():
    raw = synthetic_csv()
    assert is_bbm_csv(raw)
    df = normalize_bbm_csv(raw)
    validate(df)
    assert df.loc["nikola-jokic", "pts"] == 2 * 700 + 80 + 410
    assert df.loc["nikola-jokic", "reb"] == 850
    assert df.loc["luka-doncic", "injury"] == "hamstring, day to day"
    assert df.loc["nikola-jokic", "injury"] is None
    assert (df["positions"] == "").all() and (df["team"] == "").all()
    assert df["bbm_player_id"].tolist() == [1, 2]


def test_positions_attach_by_name_and_unknown_stay_util_only():
    df = normalize_bbm_csv(synthetic_csv())
    table = pd.DataFrame({"Name": ["Nikola Jokić", "Someone Else"], "Pos": ["C", "PG/SG"]})
    positions = positions_from_table(table)
    assert positions["nikola jokic"] == "C"
    out, missing = apply_positions(df, positions)
    assert out.loc["nikola-jokic", "positions"] == "C"
    assert missing == ["luka-doncic"]
    assert Slot("UTIL").accepts(()) and not Slot("PG", frozenset({"PG"})).accepts(())
    validate(out)


def test_load_positions_from_csv(tmp_path):
    path = tmp_path / "positions.csv"
    path.write_text("player,positions\nLuka Doncic,PG/SG\nBad Row,QB\n")
    positions = load_positions(path)
    assert positions.to_dict() == {"luka doncic": "PG/SG"}


def test_real_csv_export_if_present():
    files = sorted(DATA.glob("bbm_projections_*.csv"))
    if not files:
        pytest.skip("no Basketball Monster CSV in data/")
    ps = load_bbm(files[-1])
    assert ps.source == "bbm" and len(ps.df) > 300
    z = zscores(ps.df, pool_size=156)
    top = z["total"].nlargest(5).index.tolist()
    assert all(ps.df.loc[pid, "games"] > 0 for pid in top)
    # positions can be borrowed from the legacy Excel export for players who still exist
    xls = DATA / "bbm_sample_ros_totals.xls"
    if xls.exists():
        out, missing = apply_positions(ps.df, load_positions(xls))
        assert len(missing) < len(ps.df)
        validate(out)


def test_load_bbm_csv_metadata():
    files = sorted(DATA.glob("bbm_projections_*.csv"))
    if not files:
        pytest.skip("no Basketball Monster CSV in data/")
    ps = load_bbm_csv(files[-1], horizon="season", label="x")
    assert ps.label == "x" and ps.horizon == "season"
