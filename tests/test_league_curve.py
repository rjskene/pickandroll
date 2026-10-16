"""The category curve from the league's drafted rosters (#65): the fit recovers a known mu and
sigma, the archive's picks become rosters by the team that made each pick, seasons that cannot
be scored are skipped with the reason, the standings check is in z units, and ``curve: league``
runs through ``/sessions``."""

import json
import shutil
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.api.league_curve import (
    draft_year,
    fit_league_curve,
    pool_spread,
    season_rosters,
)
from pickandroll.optim.objective import CategoryCurve, roster_totals
from pickandroll.projections.schema import NINE_CAT, Cat
from pickandroll.projections.zscores import zscores
from pickandroll.sources.bbm import load_bbm

from .conftest import DATA

CATS = [Cat.PTS, Cat.REB, Cat.FG_PCT]


def test_the_roster_fit_recovers_a_known_mu_and_sigma():
    """Rosters of 13 whose players' z are drawn so that a roster's total is N(mu, sigma): the
    fit over 2000 rosters lands within about three standard errors of both."""
    rng = np.random.default_rng(65)
    mu = {Cat.PTS: 0.6, Cat.REB: -0.9, Cat.FG_PCT: 0.2}
    sigma = {Cat.PTS: 2.2, Cat.REB: 3.4, Cat.FG_PCT: 2.8}
    size, teams = 13, 2000
    ids = [f"p{i}" for i in range(size * teams)]
    z = pd.DataFrame(
        {c.value: rng.normal(mu[c] / size, sigma[c] / np.sqrt(size), len(ids)) for c in CATS},
        index=ids,
    )
    rosters = {t: ids[t * size : (t + 1) * size] for t in range(teams)}
    curve = CategoryCurve.from_rosters(z, rosters, CATS, source="synthetic")
    for c in CATS:
        assert curve.mu[c] == pytest.approx(mu[c], abs=0.25)
        assert curve.sigma[c] == pytest.approx(sigma[c], rel=0.05)
    assert curve.source == "synthetic"
    # A roster total is the plain sum of its players' z; an unscored player is the caller's call.
    totals = roster_totals(z, {"a": ids[:2]}, CATS)
    assert totals.loc["a", "pts"] == pytest.approx(z.loc[ids[:2], "pts"].sum())
    with pytest.raises(KeyError, match="nobody"):
        roster_totals(z, {"a": ["nobody"]}, CATS)


def test_a_projection_date_names_its_draft_year():
    assert draft_year(datetime(2026, 10, 14, tzinfo=UTC)) == 2026
    assert draft_year(datetime(2026, 7, 1, tzinfo=UTC)) == 2026
    assert draft_year(datetime(2027, 2, 1, tzinfo=UTC)) == 2026


def projections(n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A season's projection rows (names, games, raw points 100 + 25 z) and their z."""
    rng = np.random.default_rng(seed)
    ids = [f"s{seed}-{i}" for i in range(n)]
    z = pd.DataFrame({c.value: rng.normal(0, 1, n) for c in CATS}, index=ids)
    df = pd.DataFrame(
        {
            "player": [f"Player {i}" for i in range(n)],
            "games": 70.0,
            "pts": 100 + 25 * z["pts"],
            "reb": 50 + 10 * z["reb"],
        },
        index=ids,
    )
    return df, z


def picks(year: int, teams: int, rounds: int, names: list[str]) -> pd.DataFrame:
    """A snake draft of ``names`` in order; team "T1" also uses team "T2"'s first-round pick."""
    rows = []
    for k, name in enumerate(names[: teams * rounds], start=1):
        rnd, at = divmod(k - 1, teams)
        slot = at + 1 if rnd % 2 == 0 else teams - at
        team = "T1" if (rnd, slot) == (0, 2) else f"T{slot}"
        rows.append(
            {"draft_year": year, "n_teams": teams, "round": rnd + 1, "overall": k}
            | {"player": name, "team": team}
        )
    return pd.DataFrame(rows)


def test_the_archive_becomes_rosters_by_the_team_that_made_each_pick(tmp_path):
    df24, z24 = projections(20, 24)
    df26, z26 = projections(20, 26)
    names = [f"Player {i}" for i in range(20)]
    archive = pd.concat(
        [
            picks(2016, 4, 2, names),  # twelve rounds that year: not on the session's scale
            picks(2022, 4, 3, names),  # no projection file
            picks(2024, 4, 3, names),
            picks(2026, 4, 3, names[:11] + ["Somebody Unknown"]),
        ]
    )
    archive.to_csv(tmp_path / "picks.csv", index=False)
    standings = pd.DataFrame(
        [
            {"season": "2023-24", "teams": 4, "pts_sd_pg": 50.0, "reb_sd_pg": 30.0},
            {"season": "2024-25", "teams": 4, "pts_sd_pg": 100.0, "reb_sd_pg": 10.0},
            {"season": "2015-16", "teams": 10, "pts_sd_pg": 999.0, "reb_sd_pg": 999.0},
        ]
    )
    standings.to_csv(tmp_path / "category_totals.csv", index=False)
    seasons = {2024: (df24, z24), 2026: (df26, z26)}
    fit = fit_league_curve(tmp_path, seasons.get, CATS, num_teams=4, roster_size=3, season=2026)

    # T1 made its own first pick and T2's: four picks, and T2 two. T4's last pick is a name
    # the projections lack, left off its total.
    rosters, unmatched = season_rosters(archive[archive.draft_year == 2026], df26)
    assert {t: len(r) for t, r in rosters.items()} == {"T1": 4, "T2": 2, "T3": 3, "T4": 2}
    assert unmatched == ["Somebody Unknown"]
    assert [s["year"] for s in fit.seasons] == [2024, 2026]
    assert fit.seasons[1] == {
        "year": 2026,
        "rosters": 4,
        "picks": 12,
        "scored": 11,
        "unmatched": ["Somebody Unknown"],
    }
    assert fit.skipped == [
        {"year": 2016, "reason": "4 teams x 2 rounds, the session drafts 4 x 3"},
        {"year": 2022, "reason": "no projection file (projections_2022.csv)"},
    ]
    # Pooled over both seasons, each roster on its own season's z.
    expected = pd.concat(
        [
            roster_totals(z24, season_rosters(archive[archive.draft_year == 2024], df24)[0], CATS),
            roster_totals(z26, rosters, CATS),
        ]
    )
    for c in CATS:
        assert fit.curve.mu[c] == pytest.approx(expected[c.value].mean())
        assert fit.curve.sigma[c] == pytest.approx(expected[c.value].std(ddof=1))
    assert fit.curve.source == "league rosters 2024, 2026 (8 rosters, 23 of 24 picks scored)"
    # The check: the standings' per-game spread over the pool's per-player spread (25 and 10
    # here), averaged over the four-team seasons; no z units for a percentage.
    assert pool_spread(df26, z26, CATS) == pytest.approx({Cat.PTS: 25.0, Cat.REB: 10.0})
    assert fit.check["pts"] == pytest.approx((2.0 + 4.0) / 2)
    assert fit.check["reb"] == pytest.approx((3.0 + 1.0) / 2)
    assert fit.check["fg_pct"] is None
    assert fit.check_seasons == ["2023-24", "2024-25"]
    assert fit.to_dict()["check"] == {"pts": 3.0, "reb": 2.0, "fg_pct": None}


def test_an_archive_with_nothing_to_fit_says_why(tmp_path):
    with pytest.raises(ValueError, match="no drafted rosters: picks.csv"):
        fit_league_curve(tmp_path, lambda y: None, CATS, 4, 3, 2026)
    picks(2025, 4, 3, [f"Player {i}" for i in range(12)]).to_csv(tmp_path / "picks.csv")
    with pytest.raises(ValueError, match=r"2025: no projection file \(projections_2025.csv\)"):
        fit_league_curve(tmp_path, lambda y: None, CATS, 4, 3, 2026)


@pytest.fixture
def sample(tmp_path):
    path = DATA / "bbm_sample_ros_totals.xls"
    if not path.exists():
        pytest.skip("no Basketball Monster sample export in data/")
    shutil.copy(path, tmp_path / path.name)
    return path.name


def test_curve_league_runs_through_sessions(tmp_path, sample):
    """Four teams, thirteen rounds: the sample's top 52 by z drafted in a snake into the default
    archive folder, the session's own season."""
    proj = load_bbm(tmp_path / sample, horizon="season")
    z = zscores(proj.df, cats=NINE_CAT, pool_size=52)
    order = z["total"].sort_values(ascending=False).index[:52]
    names = proj.df.loc[order, "player"].tolist()
    archive = tmp_path / "yahoo_history"
    archive.mkdir()
    year = draft_year(proj.as_of)
    picks(year, 4, 13, names).to_csv(archive / "picks.csv", index=False)
    store = SessionStore()
    with TestClient(create_app(store, data_dir=tmp_path)) as client:
        base = {
            "projection_file": sample,
            "num_teams": 4,
            "solve_ahead": False,
            "survival": "none",
        }
        r = client.post("/sessions", json={**base, "curve": "league"})
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["curve"]["source"] == f"league rosters {year} (4 rosters, 52 of 52 picks scored)"
        assert s["curve_fit"]["seasons"][0]["scored"] == 52 and s["curve_fit"]["check"] == {}
        rosters, _ = season_rosters(pd.read_csv(archive / "picks.csv"), proj.df)
        totals = roster_totals(z, rosters, NINE_CAT)
        assert s["curve"]["sigma"]["pts"] == pytest.approx(totals["pts"].std(ddof=1), abs=1e-4)
        assert s["curve"]["mu"]["ast"] == pytest.approx(totals["ast"].mean(), abs=1e-4)
        assert store.sessions[s["id"]].create_params["curve"] == "league"
        # The default stays the simulated league, with no fit to report.
        plain = client.post("/sessions", json=base).json()
        assert plain["curve"]["source"].startswith("simulated league")
        assert plain["curve_fit"] is None
        # A simulation measures survival only: the league's curve stands.
        sim = client.post(
            "/sessions",
            json={**base, "curve": "league", "survival": "simulate", "survival_sims": 10},
        ).json()
        assert store.sessions[sim["id"]].create_params["fit_curve"] is False
        # One curve at a time, and a league folder without an archive says so.
        (tmp_path / "curve.json").write_text(
            json.dumps({"mu": {"pts": 0.0}, "sigma": {"pts": 1.0}})
        )
        r = client.post("/sessions", json={**base, "curve": "league", "curve_file": "curve.json"})
        assert r.status_code == 400 and "pass one or the other" in r.json()["detail"]
        r = client.post(
            "/sessions",
            json={**base, "curve": "league", "survival": "simulate", "fit_curve": True},
        )
        assert r.status_code == 400 and "leave fit_curve out" in r.json()["detail"]
        (archive / "picks.csv").unlink()
        r = client.post("/sessions", json={**base, "curve": "league"})
        assert r.status_code == 400
        assert r.json()["detail"] == (
            "curve=league: no drafted rosters: picks.csv is not in yahoo_history/"
        )
