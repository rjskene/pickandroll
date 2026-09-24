import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.projections import adp_for_projections, adp_from_table, load_adp

DATA = Path(__file__).resolve().parents[1] / "data"


def test_adp_from_fantasypros_like_table():
    table = pd.DataFrame(
        {"Player": ["Nikola Jokić", "Luka Doncic", "Nobody"], "AVG": ["1.4", "2.9", None]}
    )
    adp = adp_from_table(table)
    assert adp.to_dict() == {"nikola jokic": 1.4, "luka doncic": 2.9}


def test_adp_rank_fallback_and_projection_mapping(pool):
    table = pd.DataFrame({"Name": pool["player"].iloc[:5], "Rank": [1, 2, 3, 4, 5]})
    adp = adp_from_table(table)
    mapped = adp_for_projections(pool, adp)
    assert mapped.to_dict() == {pid: float(i + 1) for i, pid in enumerate(pool.index[:5])}


def test_load_adp_rejects_bad_file(tmp_path):
    bad = tmp_path / "adp.csv"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="need a name column"):
        load_adp(bad)


def test_session_uses_adp_file(tmp_path):
    sample = DATA / "bbm_sample_ros_totals.xls"
    if not sample.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    shutil.copy(sample, tmp_path / sample.name)
    (tmp_path / "adp.csv").write_text("player,adp\nJames Harden,1.5\nAnthony Davis,2.5\n")
    app = create_app(SessionStore(), data_dir=tmp_path)
    with TestClient(app) as client:
        r = client.post(
            "/sessions",
            json={
                "projection_file": sample.name,
                "num_teams": 4,
                "my_position": 1,
                "solve_ahead": False,
            },
        )
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["adp_source"] == "file:adp.csv" and s["adp_known"] == 2
        rec = client.post(f"/sessions/{s['id']}/recommend", json={"n": 3, "scenarios": 0}).json()
        assert rec["adp_source"] == "file:adp.csv"
        r = client.post(
            "/sessions",
            json={
                "projection_file": sample.name,
                "num_teams": 4,
                "my_position": 1,
                "adp_file": "missing.csv",
            },
        )
        assert r.status_code == 400
