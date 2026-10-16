"""The ADP model's bias by keeper-adjusted ADP (#64): the table's lookup, the fit from the archive,
the held-out score, the shift in ``DraftState.availability`` and the session's flag. The last two
tests run on the league's own archive in data/ and skip without it."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, yahoo_room
from pickandroll.api.app import ADP_BIAS_FILE, SessionCreate, _adp_bias_path
from pickandroll.availability import LEAGUE_FROM_ADP, AdpBias, LeagueSurvivalTable
from pickandroll.availability import bias as adp_bias
from pickandroll.availability.adp import conditional_availability
from pickandroll.draft import Keeper

from .conftest import DATA, synthetic_pool
from .test_market_space import by_hand, league_frame, make_state, ranked

HISTORY = DATA / "yahoo_history"
SAMPLE = "bbm_sample_ros_totals.xls"

TABLE = AdpBias(centers=(10.0, 50.0, 90.0, 120.0), values=(0.0, 0.0, 8.0, 2.0), from_adp=60.0)


# --------------------------------------------------------------------------- the lookup
def test_the_shift_is_linear_between_centres_and_flat_past_the_ends():
    adp = pd.Series(
        {
            "first": 1.0,  # before the first centre: its value
            "zero": 50.0,  # a centre before from_adp: no shift
            "ramp": 70.0,  # halfway from the last zero centre to the first shifted one
            "centre": 90.0,
            "between": 105.0,
            "last": 120.0,
            "past": 400.0,  # past the last centre: its value
            "none": np.nan,
        }
    )
    shift = TABLE.shift(adp)
    assert list(shift.index) == list(adp.index)
    assert shift["first"] == 0.0 and shift["zero"] == 0.0
    assert shift["ramp"] == pytest.approx(4.0)
    assert shift["centre"] == 8.0 and shift["between"] == pytest.approx(5.0)
    assert shift["last"] == 2.0 and shift["past"] == 2.0
    assert shift["none"] == 0.0
    shifted = TABLE.apply(adp)
    assert shifted["centre"] == 98.0 and shifted["past"] == 402.0 and np.isnan(shifted["none"])
    # Below the first centre the shift is the first value, whatever it is.
    lead = AdpBias(centers=(30.0, 60.0), values=(3.0, 6.0))
    assert lead.shift(pd.Series([0.0, 30.0, 45.0, 99.0])).tolist() == [3.0, 3.0, 4.5, 6.0]


def test_a_table_round_trips_and_rejects_bad_shapes():
    table = AdpBias(
        centers=(6.2, 90.4),
        values=(0.0, 8.3),
        from_adp=72.0,
        half_life=1.0,
        seasons=(2025, 2026),
        target=2026,
        counts=(104, 122),
    )
    data = json.loads(json.dumps(table.to_dict()))
    assert data["from_adp"] == 72.0 and data["half_life"] == 1.0 and data["seasons"] == [2025, 2026]
    assert AdpBias.from_dict(data) == table
    # The script's record carries its held-out scores too; the table ignores them.
    assert AdpBias.from_dict({**data, "held_out": {"buckets": []}}) == table
    flat = AdpBias.from_dict({"centers": [10], "values": [2]})
    assert (
        flat.half_life is None
        and flat.from_adp == 0.0
        and flat.shift(pd.Series([0.0, 99.0])).tolist() == [2.0, 2.0]
    )
    with pytest.raises(ValueError, match="increase"):
        AdpBias(centers=(10.0, 10.0), values=(0.0, 1.0))
    with pytest.raises(ValueError, match="one value per bucket"):
        AdpBias(centers=(10.0, 20.0), values=(0.0,))
    with pytest.raises(ValueError, match="one value per bucket"):
        AdpBias(centers=(), values=())
    with pytest.raises(ValueError, match="finite"):
        AdpBias(centers=(10.0, 20.0), values=(0.0, np.nan))
    for bad in ({"centers": [1, 2]}, {"centers": "x", "values": [1]}, [1, 2], "table"):
        with pytest.raises(ValueError):
            AdpBias.from_dict(bad)


# --------------------------------------------------------------------------- the fit
def season_frames(season, picks, keepers, listed):
    """An archive season: ``picks`` maps overall -> (adp player name or None, ADP or None),
    ``keepers`` the overalls kept, ``listed`` every (name, ADP) in the season's ADP list."""
    rows = [
        {
            "draft_year": season,
            "overall": k,
            "adp_player": name,
            "avg_pick": value,
            "keeper_any": k in keepers,
        }
        for k, (name, value) in picks.items()
    ]
    adp = [{"draft_year": season, "player": n, "avg_pick": v} for n, v in listed]
    return pd.DataFrame(rows), pd.DataFrame(adp)


def test_observations_put_each_season_in_market_space():
    picks, adp = season_frames(
        2025,
        {
            1: ("A", 1.0),
            2: ("K", 2.0),  # a keeper with ADP 2: one ahead of everyone listed after him
            3: ("B", 4.0),
            4: ("Q", None),  # a keeper the ADP list lacks: a slot, no ADP
            5: (None, None),  # a drafted player the list lacks: no observation
            6: ("C", 3.0),
        },
        keepers={2, 4},
        listed=[("A", 1.0), ("K", 2.0), ("C", 3.0), ("B", 4.0), ("U", 9.0), ("V", None)],
    )
    obs = adp_bias.observations(picks, adp).set_index("player")
    assert list(obs.index) == ["A", "C", "B", "U"]  # keepers and unlisted ADPs left out
    assert obs["adp_eff"].to_dict() == {"A": 1.0, "C": 2.0, "B": 3.0, "U": 8.0}
    # Market pick: the overall pick minus the keeper slots before it; U was never drafted.
    assert obs.loc[["A", "B", "C"], "market_pick"].tolist() == [1.0, 2.0, 4.0]
    assert np.isnan(obs.loc["U", "market_pick"])
    assert set(obs["market_picks"]) == {4} and set(obs["season"]) == {2025}
    assert adp_bias.observations(picks, adp, seasons=[2024]).empty


def obs_frame(rows, market_picks=30):
    """Observations from (season, adp_eff, market_pick or None)."""
    return pd.DataFrame(
        [
            {
                "season": s,
                "player": f"{s}-{i}",
                "adp": a,
                "adp_eff": a,
                "market_pick": np.nan if m is None else float(m),
                "market_picks": market_picks,
            }
            for i, (s, a, m) in enumerate(rows)
        ]
    )


def test_fit_averages_residuals_by_bucket_weighs_seasons_and_zeroes_early_buckets():
    edges = (0, 10, 20, 30)
    rows = [(2025, 5.0, 5.0)] * 4 + [(2026, 5.0, 7.0)] * 4  # bucket 0-10: +0 and +2
    rows += [(2025, 15.0, 15.0)] * 4 + [(2026, 15.0, 25.0)] * 4  # 10-20: +0 and +10
    rows += [(2026, 25.0, None)] * 6 + [(2026, 25.0, 26.0)]  # 20-30: one drafted (too few)
    obs = obs_frame(rows)
    plain = adp_bias.fit(obs, 2026, edges=edges, min_drafted=3)
    assert plain.centers == (5.0, 15.0) and plain.values == (1.0, 5.0)
    assert plain.counts == (8, 8) and plain.seasons == (2025, 2026) and plain.target == 2026
    # A one-season half-life: 2025 counts half as much as 2026.
    recent = adp_bias.fit(obs, 2026, half_life=1.0, edges=edges, min_drafted=3)
    assert recent.values == pytest.approx((4 / 3, 20 / 3))
    # Buckets whose centre lies before from_adp carry no shift.
    late = adp_bias.fit(obs, 2026, half_life=1.0, from_adp=10.0, edges=edges, min_drafted=3)
    assert late.values == pytest.approx((0.0, 20 / 3)) and late.from_adp == 10.0
    with pytest.raises(ValueError, match="enough drafted"):
        adp_bias.fit(obs, 2026, edges=edges, min_drafted=9)


def test_held_out_scores_each_season_on_the_fit_without_it():
    """A league that takes every player from ADP 20 on ten picks after it, every season: held out,
    the shift beats the plain formula there and changes nothing in the buckets before."""
    rows = [
        (season, float(a), float(a if a < 20 else a + 10))
        for season in range(2020, 2026)
        for a in range(1, 41)
    ]
    obs = obs_frame(rows, market_picks=60)
    edges = (0, 10, 20, 40)
    scores = adp_bias.held_out(obs, from_adp=20.0, edges=edges, min_drafted=3)
    assert list(scores.index) == ["0-10", "10-20", "20-40"]
    assert scores["players"].tolist() == [60, 60, 120]
    assert (scores["terms"] == scores["players"] * 60).all()
    assert scores.loc["0-10", "biased"] == scores.loc["0-10", "plain"]
    assert scores.loc["20-40", "biased"] < scores.loc["20-40", "plain"] - 0.01

    choice = adp_bias.choose(
        obs, half_lives=(None,), from_adps=(0.0, 20.0), edges=edges, min_drafted=3
    )
    assert choice is not None and choice.half_life is None
    assert len(choice.grid) == 2 and (choice.scores["biased"] <= choice.scores["plain"]).all()
    assert choice.grid["biased"].min() == pytest.approx(
        (choice.scores["biased"] * choice.scores["terms"]).sum() / choice.scores["terms"].sum()
    )


def test_choose_takes_no_table_when_every_fit_is_worse_somewhere():
    """Residuals that flip sign from season to season: the fit on the others always points the
    wrong way, so no fit is no worse than the plain formula in every bucket."""
    rows = []
    for season in range(2020, 2026):
        sign = 1 if season % 2 else -1
        rows += [(season, float(a), float(a + sign * 6)) for a in range(8, 20)]
    obs = obs_frame(rows)
    assert (
        adp_bias.choose(obs, half_lives=(1.0,), from_adps=(0.0,), edges=(0, 10, 20), min_drafted=3)
        is None
    )


def test_market_picks_map_back_to_overall_picks():
    slots = [2, 5]  # keepers at overall 2 and 5 of 8: the market's picks are 1, 3, 4, 6, 7, 8
    assert [adp_bias.market_to_overall(m, slots, 8) for m in (1, 2, 3, 4, 6)] == [1, 3, 4, 6, 8]
    assert adp_bias.market_to_overall(2.5, slots, 8) == 3.5
    assert adp_bias.market_to_overall(0.5, slots, 8) == 0.5
    assert adp_bias.market_to_overall(9, slots, 8) == 11


# --------------------------------------------------------------------------- the session
def test_the_shift_moves_the_formula_and_leaves_the_league_table():
    """With a bias table the ADP model centres each player on his keeper-adjusted ADP plus the
    shift, its spread taken there; from ADP 90 the league table still answers by the ADP itself."""
    pool = synthetic_pool(140)
    p = ranked(make_state(pool))
    state = make_state(pool, [Keeper(1, 2, p[2])])
    plain = state.availability()
    state.adp_bias = TABLE
    state.adp_bias_source = "bias:test.json"
    assert state.availability_source == "adp"
    assert state.availability_bias == {
        "source": "bias:test.json",
        "from_adp": 60.0,
        "half_life": None,
        "seasons": [],
        "target": None,
    }
    frame = state.availability()
    market = state.market_adp()
    centre = TABLE.apply(market)
    expected = conditional_availability(
        centre,
        now=state.market_pick(state.next_overall),
        picks=[state.market_pick(k) for k in state.my_remaining_picks],
        spread=1.5 + 0.15 * centre,
    )
    expected.columns = state.my_remaining_picks
    pd.testing.assert_frame_equal(frame, expected)
    early = market[market <= 50].index
    late = market[(market >= 80) & (market <= 100)].index
    pd.testing.assert_frame_equal(frame.loc[early], plain.loc[early])
    last = state.my_remaining_picks[-1]
    assert (frame.loc[late, last] > plain.loc[late, last]).all()  # later, so likelier to last

    # The league table answers from ADP 90 by the unshifted ADP; before it the shifted formula.
    state.league_survival = LeagueSurvivalTable.from_frame(
        league_frame(rows=130, shape=lambda a, m: float(np.exp(-2.0 * m / a)))
    )
    with_table = state.availability()
    state.adp_bias = None
    no_bias = state.availability()
    known = market.reindex(with_table.index) >= LEAGUE_FROM_ADP
    pd.testing.assert_frame_equal(with_table.loc[known], no_bias.loc[known])
    pd.testing.assert_frame_equal(with_table.loc[~known], frame.loc[~known])
    pd.testing.assert_frame_equal(no_bias.loc[~known], by_hand(state).loc[~known])
    assert state.availability_bias is None


def test_the_bias_file_sits_beside_the_league_table():
    def path(**body):
        return _adp_bias_path(SessionCreate(projection_file="p.csv", **body), Path("/d"))

    assert path() == Path("/d/yahoo_history") / ADP_BIAS_FILE
    assert path(survival="none") == Path("/d/yahoo_history") / ADP_BIAS_FILE
    assert path(survival="simulate") == Path("/d/yahoo_history") / ADP_BIAS_FILE
    table = "yahoo_history/with_2026/survival_by_adp_adjusted.csv"
    assert (
        path(survival="league", survival_file=table)
        == Path("/d/yahoo_history/with_2026") / ADP_BIAS_FILE
    )
    assert path(survival="league", survival_file="mine.csv") == Path("/d") / ADP_BIAS_FILE
    # A league folder's session reads its own folder, never the home league's archive.
    assert path(league="238174", survival="simulate") == Path("/d/leagues/238174") / ADP_BIAS_FILE
    leagues_table = "leagues/238174/survival_by_adp.csv"
    assert path(league="238174", survival="league", survival_file=leagues_table) == (
        Path("/d/leagues/238174") / ADP_BIAS_FILE
    )


@pytest.fixture
def data_dir(tmp_path):
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    (tmp_path / SAMPLE).symlink_to(DATA / SAMPLE)
    (tmp_path / "yahoo_history").mkdir()
    return tmp_path


def test_a_session_loads_the_bias_with_its_table_and_the_flag_turns_it_off(data_dir):
    body = {
        "projection_file": SAMPLE,
        "num_teams": 4,
        "my_position": 2,
        "solve_ahead": False,
        "survival": "none",
    }
    store = SessionStore()
    with TestClient(create_app(store, data_dir=data_dir)) as c:
        s = c.post("/sessions", json=body).json()
        assert s["availability_bias"] is None and "note" not in s["survival"]

        record = {**TABLE.to_dict(), "held_out": {"buckets": []}}
        (data_dir / "yahoo_history" / ADP_BIAS_FILE).write_text(json.dumps(record))
        r = c.post("/sessions", json=body)
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["availability_source"] == "adp"
        assert s["availability_bias"]["source"] == "bias:yahoo_history/adp_bias.json"
        assert s["availability_bias"]["from_adp"] == 60.0
        state = store.get(s["id"]).state
        assert state.adp_bias == TABLE
        assert store.get(s["id"]).create_params["adp_bias"] is True
        rec = c.post(f"/sessions/{s['id']}/recommend", json={"time_limit": 4.0})
        assert rec.status_code == 200, rec.text
        assert rec.json()["availability_bias"] == s["availability_bias"]

        # The flag turns it off, and the session records it for a rebuild.
        s = c.post("/sessions", json={**body, "adp_bias": False}).json()
        assert s["availability_bias"] is None and store.get(s["id"]).state.adp_bias is None
        assert store.get(s["id"]).create_params["adp_bias"] is False

        # A league table elsewhere looks beside itself: none there, no shift.
        rows = ["adp," + ",".join(str(m) for m in range(1, 54)) + ",undrafted"]
        rows += [f"{a}," + ",".join("1.0" for _ in range(53)) + ",0.0" for a in range(1, 7)]
        (data_dir / "mine.csv").write_text("\n".join(rows) + "\n")
        s = c.post(
            "/sessions", json={**body, "survival": "league", "survival_file": "mine.csv"}
        ).json()
        assert s["availability_source"] == "league" and s["availability_bias"] is None

        # A table that cannot be read: the draft goes on without it, and the session says why.
        (data_dir / "yahoo_history" / ADP_BIAS_FILE).write_text(
            '{"centers": [1, 1], "values": [0, 1]}'
        )
        r = c.post("/sessions", json=body)
        assert r.status_code == 201, r.text
        s = r.json()
        assert s["availability_bias"] is None
        assert s["survival"]["note"] == (
            "could not read yahoo_history/adp_bias.json (bucket centres must increase): no ADP bias"
        )


def test_a_rebuild_keeps_the_bias_the_session_ran_on():
    """The attach record keeps the resolved flag; one from before #64 ran without the bias."""
    session = {"projection_file": SAMPLE, "survival": "league"}
    for logged, rebuilt in ((None, False), (True, True), (False, False)):
        record = {**session} if logged is None else {**session, "adp_bias": logged}
        prior = [{"type": "attach", "session": record}]
        assert yahoo_room.logged_session(prior)["adp_bias"] is rebuilt
    assert yahoo_room.logged_session([]) == {}


# --------------------------------------------------------------------------- the archive
@pytest.fixture(scope="module")
def archive():
    picks, adp = HISTORY / "picks_with_adp.csv", HISTORY / "adp.csv"
    if not (picks.exists() and adp.exists()):
        pytest.skip("no league history archive in data/yahoo_history")
    picks = pd.read_csv(picks)
    if 2026 not in set(picks["draft_year"]):
        pytest.skip("the archive has no 2026 draft")
    obs = adp_bias.observations(picks, pd.read_csv(adp), range(2017, 2027))
    return picks, obs, adp_bias.choose(obs)


def test_on_the_archive_each_season_held_out_the_shift_is_no_worse_in_any_bucket(archive):
    """Every archived season held out in turn, the chosen fit's Brier against the plain
    formula's, bucket by bucket: never worse, and better where the league runs late."""
    _, obs, choice = archive
    assert choice is not None
    scores = choice.scores
    assert len(scores) == len(adp_bias.EDGES) - 1
    assert (scores["biased"] <= scores["plain"] + 1e-12).all()
    for bucket in ("84-96", "96-108"):
        assert scores.loc[bucket, "biased"] < scores.loc[bucket, "plain"] - 0.005
    shipped = HISTORY / ADP_BIAS_FILE
    if shipped.exists():  # the written table is the chosen fit on every season
        table = AdpBias.from_dict(json.loads(shipped.read_text()))
        assert (table.half_life, table.from_adp) == (choice.half_life, choice.from_adp)
        fitted = adp_bias.fit(obs, 2026, choice.half_life, choice.from_adp)
        assert table.centers == pytest.approx(fitted.centers, abs=1e-3)
        assert table.values == pytest.approx(fitted.values, abs=1e-3)


def test_the_2026_draft_pick_error_with_the_shift_fit_on_the_other_seasons(archive):
    """The 2026-10-14 draft's 134 non-keeper picks with an ADP: keeper-adjusted ADP misses by 10.4
    picks on average (the analysis's number); shifted by the fit on 2017-2025, by about 9.5."""
    picks, obs, choice = archive
    season = picks[picks["draft_year"] == 2026]
    slots = sorted(season.loc[season["keeper_any"].astype(bool), "overall"].astype(int))
    drafted = obs[(obs["season"] == 2026) & obs["market_pick"].notna()]
    fitted = adp_bias.fit(obs[obs["season"] != 2026], 2026, choice.half_life, choice.from_adp)

    def overall(market):
        return market.map(lambda m: adp_bias.market_to_overall(float(m), slots, len(season)))

    real = overall(drafted["market_pick"])
    plain = (overall(drafted["adp_eff"]) - real).abs().mean()
    biased = (overall(fitted.apply(drafted["adp_eff"])) - real).abs().mean()
    assert len(drafted) == 134
    assert plain == pytest.approx(10.42, abs=0.01)
    assert biased == pytest.approx(9.5, abs=0.1)
