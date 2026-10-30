"""The knob file at solve time (#152, docs/AUTOPILOT.md section 6): every hooked knob in force
and per league reaching the moves solve, the strategy and the decision log; the refusals; a
missing or broken file meaning the defaults; a named system winning; and the blend of the two
systems. Every value is made up; the projection is the season tests' made-up one."""

from __future__ import annotations

import json
import os

import pytest

from pickandroll.api import season_knobs, season_moves
from pickandroll.api import seasons as season_api
from pickandroll.season import Season
from pickandroll.season import progress as pg
from tests.test_decisions import logged
from tests.test_season import LEAGUE, season_client, strategy_league


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def put_knobs(client, body) -> None:
    """The knob file, its modification time moved on so the solves kept for the day see it."""
    path = season_knobs.autopilot_dir(client.data_dir) / season_knobs.KNOBS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.stat().st_mtime_ns if path.exists() else 0
    path.write_text(body if isinstance(body, str) else json.dumps(body))
    os.utime(path, ns=(before + 10**9, before + 10**9))


# --------------------------------------------------------------------------- the knobs
def test_the_hooked_knobs_are_every_knob_but_the_stash_threshold_and_the_faab_sizing():
    assert set(pg.DEFAULTS) == set(pg.KNOBS)
    assert pg.HOOKED <= set(pg.KNOBS)
    # Recorded, never read: the Monday step never changes one.
    assert set(pg.KNOBS) - pg.HOOKED == {"stash_threshold", "faab_sizing"}
    assert pg.DEFAULTS["system"] == "bbm" and pg.DEFAULTS["horizon_weight"] == "natural"
    assert (pg.DEFAULTS["protection_floor"], pg.DEFAULTS["daily_cap"]) == (0.0, 2)
    assert (pg.DEFAULTS["plan_floor_cats"], pg.DEFAULTS["plan_floor_points"]) == (0.10, 0.01)


def test_a_league_takes_the_defaults_then_the_values_in_force_then_its_own():
    knobs, problems = pg.knob_file(
        {
            "in_force": {"protection_floor": 0.2, "daily_cap": 3, "system": "yahoo"},
            "leagues": {"100001": {"system": "blend", "daily_cap": 1}, "100004": {"blend": 0.3}},
        }
    )
    assert problems == []
    one = pg.in_force_for(knobs, "100001")
    assert {k: one[k] for k in ("system", "protection_floor", "daily_cap")} == {
        "system": "blend",
        "protection_floor": 0.2,
        "daily_cap": 1,
    }
    # The blend system with no weight set is half Yahoo's.
    assert one["blend"] == pg.BLEND == 0.5
    # A weight set without the blend system is recorded, not used.
    four = pg.in_force_for(knobs, "100004")
    assert (four["system"], four["blend"], four["daily_cap"]) == ("yahoo", 0.3, 3)
    assert pg.in_force_for(knobs, "100009") == {
        **pg.DEFAULTS,
        "protection_floor": 0.2,
        "daily_cap": 3,
        "system": "yahoo",
    }
    assert pg.in_force_for(pg.knob_file(None)[0], "100001") == dict(pg.DEFAULTS)


def test_a_value_out_of_its_bounds_is_refused_and_the_default_stays():
    knobs, problems = pg.knob_file(
        {
            "in_force": {
                "system": "espn",
                "horizon_weight": "week",
                "daily_cap": 1.5,
                "plan_floor_cats": "high",
                "blend": 0.8,
            },
            "leagues": {"100001": {"daily_cap": 4, "plan_floor_points": 0.02}},
        }
    )
    assert knobs["in_force"] == {} and knobs["leagues"] == {"100001": {"plan_floor_points": 0.02}}
    assert problems == [
        "in_force: system 'espn' is not one of bbm, yahoo, blend",
        "in_force: horizon_weight 'week' is not one of even, natural, season",
        "in_force: daily_cap 1.5 is not a whole number",
        "in_force: plan_floor_cats 'high' is not a number",
        "in_force: blend 0.8 is above its maximum 0.75",
        "league 100001: daily_cap 4 is above its maximum 3",
    ]
    assert pg.refused("blend", 0.75) is None and pg.refused("daily_cap", 3) is None
    assert pg.refused("daily_cap", True) == "daily_cap True is not a number"
    assert pg.refused("stash_threshold", 0.3) is None


# --------------------------------------------------------------------------- the blend
def test_the_blend_mixes_each_rate_of_a_player_yahoo_projects_and_keeps_the_rest():
    bbm = {1: {"pts": 20.0, "reb": 4.0}, 2: {"pts": 10.0}}
    yahoo = {1: {"pts": 30.0, "reb": 8.0}, 3: {"pts": 5.0}}
    out = season_moves.blend_rates(bbm, yahoo, 0.25)
    assert out == {1: {"pts": 22.5, "reb": 5.0}, 3: {"pts": 5.0}}


def test_the_blend_system_rates_and_values_are_the_two_systems_mixed(client):
    strategy_league(client)
    service = client.app.state.seasons
    base, _ = service._base(LEAGUE)
    season = Season.from_parts(base, season_api.load_parts(client.data_dir, LEAGUE))
    bbm = season_moves.system_rates(season, client.data_dir, "bbm")
    yahoo = season_moves.system_rates(season, client.data_dir, "yahoo")
    blend = season_moves.system_rates(season, client.data_dir, "blend", 0.25)
    both = set(bbm.bbm.rates) & set(bbm.yahoo.rates)
    assert both, "the fixture's available players have both systems' lines"
    for k in both:
        for stat, b in bbm.rates[k].items():
            y = yahoo.rates[k].get(stat, 0.0)
            assert blend.rates[k][stat] == pytest.approx(0.75 * b + 0.25 * y)
        assert blend.value[k] == pytest.approx(0.75 * bbm.value[k] + 0.25 * yahoo.value[k])
    for k in set(bbm.rates) - set(bbm.yahoo.rates):
        assert blend.rates[k] == bbm.rates[k] and blend.value[k] == bbm.value[k]
    assert blend.info["blend"] == 0.25 and "Blend" in blend.info["label"]
    # No weight: half and half.
    assert season_moves.system_rates(season, client.data_dir, "blend").info["blend"] == 0.5


# --------------------------------------------------------------------------- at solve time
def test_every_hooked_knob_reaches_the_solve_and_the_log(client):
    strategy_league(client)
    put_knobs(
        client,
        {
            "in_force": {"protection_floor": 0.3, "daily_cap": 1, "stash_threshold": 0.2},
            "leagues": {
                LEAGUE: {
                    "system": "blend",
                    "blend": 0.25,
                    "plan_floor_cats": 0.2,
                    "horizon_weight": "season",
                }
            },
        },
    )
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert m["system"]["key"] == "blend" and m["system"]["blend"] == 0.25
    assert m["keep_rule"]["floor"] == 0.3 and m["plan"]["floor"] == 0.2
    built = client.app.state.seasons._built(LEAGUE, None)
    assert (built.problem.floor, built.problem.plan_floor, built.problem.daily_cap) == (0.3, 0.2, 1)
    [entry] = logged(client)
    assert entry["system"]["key"] == "blend"
    assert entry["knobs"] == {
        "system": "blend",
        "blend": 0.25,
        "horizon_weight": "season",
        "protection_floor": 0.3,
        "plan_floor_cats": 0.2,
        "plan_floor_points": 0.01,
        # Recorded as the file has it, though nothing reads it.
        "stash_threshold": 0.2,
        "faab_sizing": None,
        "daily_cap": 1,
        # The system the file had in force, beside the one the solve ran on.
        "file_system": "blend",
    }
    # The strategy marks the recommended weight; nothing executes it.
    s = client.post(
        f"/seasons/{LEAGUE}/strategy",
        params={"wait": True, "pool": 10, "weights": "natural,season"},
    ).json()
    assert s["status"] == "solved" and s["recommended"] == "season"
    assert [(p["key"], p["recommended"]) for p in s["points"]] == [
        ("natural", False),
        ("season", True),
    ]
    run = logged(client)[-1]
    assert run["source"] == "strategy" and run["recommended"] == "season"
    assert [(x["key"], x["recommended"]) for x in run["sets"]] == [
        ("natural", False),
        ("season", True),
    ]
    assert run["knobs"] == entry["knobs"]


def test_a_named_system_wins_over_the_knob_files(client):
    strategy_league(client)
    put_knobs(client, {"in_force": {"system": "yahoo", "protection_floor": 0.3}})
    assert client.get(f"/seasons/{LEAGUE}/moves").json()["system"]["key"] == "yahoo"
    named = client.get(f"/seasons/{LEAGUE}/moves", params={"system": "bbm"}).json()
    assert named["system"]["key"] == "bbm" and named["keep_rule"]["floor"] == 0.3
    assert [e["knobs"]["system"] for e in logged(client)] == ["yahoo", "bbm"]
    assert [e["knobs"]["file_system"] for e in logged(client)] == ["yahoo", "yahoo"]
    b = client.get(f"/seasons/{LEAGUE}/moves", params={"system": "blend"}).json()
    assert b["system"]["key"] == "blend" and b["system"]["blend"] == 0.5
    assert client.get(f"/seasons/{LEAGUE}/best").json()["system"] == "yahoo"


def test_a_change_to_the_file_solves_again(client):
    strategy_league(client)
    put_knobs(client, {"in_force": {"protection_floor": 0.0}})
    client.get(f"/seasons/{LEAGUE}/moves")
    client.get(f"/seasons/{LEAGUE}/moves")
    # The same file: no new solve; the second call's entry is the kept answer's (#240 (i)).
    assert ["built_at" in e for e in logged(client)] == [False, True]
    put_knobs(client, {"in_force": {"protection_floor": 0.4}})
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert m["keep_rule"]["floor"] == 0.4
    entries = logged(client)
    assert [e["knobs"]["protection_floor"] for e in entries] == [0.0, 0.0, 0.4]
    assert "built_at" not in entries[2]


@pytest.mark.parametrize("body", [None, "{not json", json.dumps([1, 2])])
def test_a_missing_or_broken_file_means_the_defaults(client, body):
    strategy_league(client)
    if body is not None:
        put_knobs(client, body)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert m["system"]["key"] == "bbm"
    [entry] = logged(client)
    assert entry["knobs"] == {**pg.DEFAULTS, "file_system": "bbm"}
    assert season_knobs.for_league(client.data_dir, LEAGUE) == dict(pg.DEFAULTS)


def test_a_value_the_file_may_not_hold_leaves_the_default_in_the_solve(client):
    strategy_league(client)
    put_knobs(client, {"in_force": {"protection_floor": -0.5, "daily_cap": 9, "system": "x"}})
    client.get(f"/seasons/{LEAGUE}/moves")
    [entry] = logged(client)
    assert entry["knobs"] == {**pg.DEFAULTS, "file_system": "bbm"}


def test_the_routes_and_the_trade_body_take_the_blend_and_refuse_another_system(client):
    strategy_league(client)
    url = f"/seasons/{LEAGUE}"
    assert client.get(f"{url}/moves", params={"system": "espn"}).status_code == 422
    assert client.get(f"{url}/matchup", params={"system": "blend"}).json()["system"]["key"] == (
        "blend"
    )
    assert client.get("/seasons/scorecard", params={"system": "blend"}).status_code == 200
    assert season_api.TradeBody(team=1).system is None
    assert season_api.TradeBody(team=1, system="blend").system == "blend"
