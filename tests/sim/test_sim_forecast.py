"""The forecasters (#172, PR D1): ``parse``, the four sources on made-up lines and stub bodies,
the oracle's two shapes and the two diagnostics, each figure by hand. No file under ``data/`` is
read and nothing is fetched."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from pickandroll.sim import forecast as fc
from pickandroll.sim import gamelogs as gl
from pickandroll.sim import readers as reader
from pickandroll.sim import world
from pickandroll.sim.engine import STATS
from tests.sim.test_gamelogs import entry
from tests.sim.test_gamelogs import line as raw_line

FIRST = date(2024, 10, 22)


# --------------------------------------------------------------------------- parse
def test_parse_names_the_four_and_keeps_their_order():
    got = fc.parse("prior,espn,marcel,oracle:0.1")
    assert [f.label for f in got] == ["prior", "espn", "marcel", "oracle:0.1"]
    assert got[3] == fc.Forecaster("oracle", 0.1) and got[0].spread is None
    assert [f.label for f in fc.parse(" oracle:0.25 , prior")] == ["oracle:0.25", "prior"]
    assert fc.parse("oracle:0.10")[0].label == "oracle:0.1"


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("gospel", "one of prior, espn, marcel or oracle:<spread>"),
        ("prior,prior", "prior is named twice"),
        ("oracle:0.1,oracle:0.10", "oracle:0.1 is named twice"),
        ("oracle", "an oracle names its spread"),
        ("oracle:", "is not a number"),
        ("oracle:wide", "is not a number"),
        ("oracle:0", "a number above zero"),
        ("oracle:-0.1", "a number above zero"),
        ("oracle:nan", "a number above zero"),
        ("oracle:inf", "a number above zero"),
        ("prior:0.1", "prior takes no spread"),
        ("prior,", "an empty name"),
        ("oracle:0.1,0.2", "'0.2'"),
    ],
)
def test_parse_refuses_by_name(text, why):
    with pytest.raises(ValueError) as e:
        fc.parse(text)
    assert why in str(e.value)


# --------------------------------------------------------------------------- espn
def write_body(data: Path, season: int, body: dict) -> None:
    folder = data / reader.LOGS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{season}.json").write_text(json.dumps({"season": season, "body": body}))


def projected(season: int, stats: dict, games: int | None) -> dict:
    raw = dict(stats) if games is None else {**stats, gl.GAMES_ID: games}
    return entry(season, 0, raw, split=gl.SEASON_TOTAL, source=gl.PROJECTED)


def test_espn_reads_the_stored_projection_per_game(tmp_path: Path):
    season = 2024
    full = raw_line(1600, 2400.0, fgm=600, fga=1300, ftm=300, fta=380, threes=150)
    full = {k: v for k, v in full.items() if k != gl.GAMES_ID}
    body = {
        "players": [
            {"player": {"id": 11, "stats": [projected(season, full, 80)]}},
            {"player": {"id": 12, "stats": [projected(season, full, None)]}},  # no games count
            {"player": {"id": 13, "stats": [projected(season, full, 0)]}},  # games zero
            # Only the actual totals and another season's block: not a projection of this one.
            {
                "player": {
                    "id": 14,
                    "stats": [
                        entry(season, 0, {**full, "42": 70}, split=0, source=gl.ACTUAL),
                        projected(season + 1, full, 70),
                    ],
                }
            },
        ]
    }
    write_body(tmp_path, season, body)
    rates, games = reader.espn_rates(tmp_path, season)
    assert set(rates) == {11} and games == {11: 80.0}
    assert all(isinstance(k, int) for k in rates)
    r = rates[11]
    assert set(r) == set(STATS)  # minutes (id 40) is not a stat
    assert r["pts"] == 1600 / 80 and r["fgm"] == 600 / 80 and r["fga"] == 1300 / 80
    assert r["threes"] == 150 / 80 and r["reb"] == 5 / 80
    with pytest.raises(reader.SimReadError, match="no cached log"):
        reader.espn_rates(tmp_path, 2023)
    write_body(tmp_path, 2022, {"players": body["players"][3:]})
    with pytest.raises(reader.SimReadError, match="no projection block"):
        reader.espn_rates(tmp_path, 2022)


def test_espn_passes_its_rates_through_consistent():
    got = fc.espn({"7": {"fgm": 9.0, "fga": 8.0, "threes": 10.0, "minutes": 30.0}})
    assert got == {7: {"fgm": 8.0, "fga": 8.0, "threes": 8.0}}


# --------------------------------------------------------------------------- marcel
def season_lines(rows: dict[int, tuple[int, dict[str, float]]], start: date = FIRST) -> dict:
    """``{player: (games, one line)}`` as that many identical games."""
    return {k: {start + timedelta(i): dict(ln) for i in range(n)} for k, (n, ln) in rows.items()}


def by_hand(seasons_rows, player, stat, mean):
    """Marcel's figure for one player and stat, from ``(games, line)`` rows most recent first."""
    num = den = 0.0
    for w, rows in zip(fc.MARCEL_WEIGHTS, seasons_rows, strict=False):
        if player in rows:
            n, ln = rows[player]
            num += w * n * ln.get(stat, 0.0)
            den += w * n
    return (num + fc.MARCEL_REGRESS_GAMES * mean) / (den + fc.MARCEL_REGRESS_GAMES)


def test_marcel_by_hand_on_three_seasons():
    latest = {
        1: (60, {"pts": 20.0, "reb": 4.0}),
        2: (30, {"pts": 10.0, "reb": 8.0}),
        3: (5, {"pts": 40.0}),
    }
    middle = {
        1: (70, {"pts": 18.0, "reb": 5.0}),
        2: (50, {"pts": 12.0, "reb": 6.0}),
        4: (25, {"pts": 9.0}),
    }
    oldest = {1: (80, {"pts": 16.0, "reb": 6.0}), 5: (10, {"pts": 30.0})}
    rows = [latest, middle, oldest]
    got = fc.marcel([season_lines(r) for r in rows])
    # The mean is over the latest season's players with 20 games: 1 and 2 (3 has five).
    mean = {"pts": (20.0 + 10.0) / 2, "reb": (4.0 + 8.0) / 2}
    # 1, 2 have 20 games in the latest season; 4 has 25 in the middle one and none in the
    # latest (missing it); 3 and 5 never reach 20 in any season read.
    assert sorted(got) == [1, 2, 4]
    for k in (1, 2, 4):
        for stat in ("pts", "reb"):
            assert got[k][stat] == pytest.approx(by_hand(rows, k, stat, mean[stat]))
    # By the formula's numbers for player 1's points: (5·60·20 + 4·70·18 + 3·80·16 + 100·15) /
    # (5·60 + 4·70 + 3·80 + 100).
    assert got[1]["pts"] == pytest.approx((6000 + 5040 + 3840 + 1500) / (300 + 280 + 240 + 100))
    # Player 4 missed the latest season: only the middle one counts for him, at weight four.
    assert got[4]["pts"] == pytest.approx((4 * 25 * 9.0 + 100 * 15.0) / (4 * 25 + 100))
    # A stat no line has is projected at the mean's share.
    assert got[4]["reb"] == pytest.approx(100 * 6.0 / (4 * 25 + 100))
    assert set(got[1]) == set(STATS)


def test_marcel_on_two_seasons_takes_the_first_two_weights_unrenormalized():
    latest = {1: (40, {"pts": 20.0}), 2: (20, {"pts": 10.0})}
    middle = {1: (50, {"pts": 30.0}), 2: (19, {"pts": 50.0})}
    got = fc.marcel([season_lines(latest), season_lines(middle)])
    assert got[1]["pts"] == pytest.approx(
        (5 * 40 * 20 + 4 * 50 * 30 + 100 * 15) / (200 + 200 + 100)
    )
    assert got[2]["pts"] == pytest.approx((5 * 20 * 10 + 4 * 19 * 50 + 100 * 15) / (100 + 76 + 100))


def test_marcel_has_a_20_game_floor_and_needs_two_seasons():
    latest = {1: (19, {"pts": 20.0}), 2: (20, {"pts": 10.0})}
    middle = {1: (19, {"pts": 30.0})}
    got = fc.marcel([season_lines(latest), season_lines(middle)])
    assert sorted(got) == [2]  # 19 games twice is not 20 in one season
    with pytest.raises(fc.CannotServe, match="needs 2 earlier seasons on file, it has 1"):
        fc.marcel([season_lines(latest)])
    with pytest.raises(fc.CannotServe, match="needs 2"):
        fc.marcel([])


def test_marcel_passes_its_rates_through_consistent():
    rows = {1: (30, {"fgm": 5.0, "fga": 4.0, "threes": 1.0})}
    got = fc.marcel([season_lines(rows), season_lines(rows)])
    assert got[1]["fgm"] == got[1]["fga"]


def test_marcels_reader_reads_back_from_the_season_before(tmp_path: Path):
    folder = tmp_path / reader.LOGS_DIR
    folder.mkdir(parents=True)
    for t in (2022, 2023, 2024, 2026):
        (folder / f"{t}.json").write_text(json.dumps({"season": t, "body": {"players": []}}))
    assert reader.marcel_seasons(tmp_path, 2026) == []  # 2025 is not on file: none read
    assert reader.marcel_seasons(tmp_path, 2025) == [2024, 2023, 2022]
    assert reader.marcel_seasons(tmp_path, 2024) == [2023, 2022]
    assert reader.marcel_seasons(tmp_path, 2023) == [2022]
    with pytest.raises(reader.SimReadError, match="season 2023: marcel needs 2 earlier"):
        reader.marcel_rates(tmp_path, 2023)


# --------------------------------------------------------------------------- the oracle
def oracle_lines() -> dict:
    """Eight players over twenty-odd games with varied stats, and one with a single game."""
    out = {}
    for k in range(1, 9):
        out[k] = {
            FIRST + timedelta(i): {
                "pts": 8.0 + k + (i % 3),
                "reb": 3.0 + k % 4,
                "ast": 2.0 + (k * i) % 5,
                "fgm": 3.0 + k % 2,
                "fga": 7.0 + k % 3,
                "ftm": 1.0 + i % 2,
                "fta": 2.0 + i % 2,
                "threes": 1.0 + k % 3,
                "stl": 1.0,
                "blk": 0.5 * (k % 3),
                "tov": 1.5,
            }
            for i in range(20 + k % 3)
        }
    out[9] = {FIRST: {"pts": 4.0}}
    return out


#: ``run.oracle_standin(oracle_lines(), 0.2, 7, 3)`` on main before the move (5348cd6), to 12
#: places.
PINNED_1 = {
    "ast": 4.605536986454,
    "blk": 0.471499007771,
    "fga": 7.939166071343,
    "fgm": 3.347067607651,
    "fta": 2.538856967243,
    "ftm": 1.234361361182,
    "pts": 11.452795524183,
    "reb": 3.411228578996,
    "stl": 0.723608037693,
    "threes": 2.303156161326,
    "tov": 1.752131303224,
}
PINNED_PTS = {4: 14.369675829617, 8: 14.660644819403}


def test_the_oracles_stat_shape_is_the_first_replays_draw():
    got = fc.oracle(oracle_lines(), 0.2, 7, 3)
    assert sorted(got) == list(range(1, 9))  # 9 has one game
    assert {s: round(v, 12) for s, v in got[1].items()} == PINNED_1
    assert {k: round(got[k]["pts"], 12) for k in (4, 8)} == PINNED_PTS
    assert fc.oracle(oracle_lines(), 0.2, 7, 3, shape="stat") == got
    assert fc.oracle(oracle_lines(), 0.2, 7, 4) != got  # another path, another draw
    with pytest.raises(ValueError, match="shape"):
        fc.oracle(oracle_lines(), 0.2, 7, 3, shape="weekly")


def many_lines(n: int = 600) -> dict:
    line = {s: 2.0 for s in STATS} | {"fga": 10.0, "fgm": 4.0, "fta": 5.0, "ftm": 4.0}
    return {k: {FIRST + timedelta(i): dict(line) for i in range(fc.MIN_GAMES)} for k in range(n)}


def test_the_minutes_shape_splits_the_variance_and_keeps_the_percentages():
    lines = many_lines()
    sigma = 0.3
    stat = fc.oracle(lines, sigma, 5, 0, shape="stat")
    mins = fc.oracle(lines, sigma, 5, 0, shape="minutes")
    truth = fc.realized_rates(lines)
    eps = {k: {s: math.log(mins[k][s] / truth[k][s]) for s in ("pts", "reb", "ast")} for k in mins}
    # The whole error has the spread sigma; the part two stats share is MINUTES_SHARE of it.
    xs = np.array([[e["pts"], e["reb"], e["ast"]] for e in eps.values()])
    assert xs.std(axis=0, ddof=1) == pytest.approx([sigma] * 3, rel=0.08)
    cov = np.cov(xs[:, 0], xs[:, 1])[0, 1]
    assert cov / sigma**2 == pytest.approx(fc.MINUTES_SHARE, abs=0.08)
    stat_xs = np.array([[math.log(stat[k][s] / truth[k][s]) for s in ("pts", "reb")] for k in stat])
    assert abs(np.cov(stat_xs[:, 0], stat_xs[:, 1])[0, 1]) / sigma**2 < 0.1
    # The per-stat part is the stat shape's own draw: what is left after the shared part.
    k = 17
    shared = world.rng(5, 0, k, 0, world.STREAMS["forecast"]).standard_normal()
    z_pts = math.log(stat[k]["pts"] / truth[k]["pts"]) / sigma
    want = sigma * (math.sqrt(0.7) * shared + math.sqrt(0.3) * z_pts)
    assert math.log(mins[k]["pts"] / truth[k]["pts"]) == pytest.approx(want)
    # The shared draw moves makes and attempts alike: a percentage moves only by the stat
    # parts (a player whose makes were held to his attempts by ``consistent`` is left out).
    checked = 0
    for k in list(mins)[:60]:
        if stat[k]["fgm"] == stat[k]["fga"] or mins[k]["fgm"] == mins[k]["fga"]:
            continue
        z_made = math.log(stat[k]["fgm"] / truth[k]["fgm"]) / sigma
        z_tried = math.log(stat[k]["fga"] / truth[k]["fga"]) / sigma
        want = 0.4 * math.exp(sigma * math.sqrt(1 - fc.MINUTES_SHARE) * (z_made - z_tried))
        assert mins[k]["fgm"] / mins[k]["fga"] == pytest.approx(want)
        checked += 1
    assert checked > 50


# --------------------------------------------------------------------------- the diagnostics
def test_error_of_by_hand():
    realized = {
        1: (25, {"pts": 20.0, "reb": 5.0}),
        2: (30, {"pts": 10.0, "reb": 0.0}),
        3: (10, {"pts": 8.0}),
    }
    lines = season_lines(realized)
    rates = {
        1: {"pts": 10.0, "reb": 5.0},
        2: {"pts": 10.0, "reb": 4.0},
        3: {"pts": 8.0},
        4: {"pts": 1.0},
    }
    got = fc.error_of(rates, lines)
    assert got["projected"] == 4 and got["played"] == 2 and got["min_games"] == 20
    pts = [math.log(20 / 10), math.log(10 / 10)]
    mean = sum(pts) / 2
    assert got["by_stat"]["pts"]["mean"] == pytest.approx(mean)
    assert got["by_stat"]["pts"]["spread"] == pytest.approx(
        math.sqrt(sum((x - mean) ** 2 for x in pts))
    )
    assert got["by_stat"]["pts"]["n"] == 2
    # 2's realized rebounds are zero: left out, and one value has no spread.
    assert got["by_stat"]["reb"] == {"mean": 0.0, "spread": None, "n": 1}
    assert got["by_stat"]["ast"] == {"mean": None, "spread": None, "n": 0}
    assert got["median_spread"] == pytest.approx(got["by_stat"]["pts"]["spread"])
    assert fc.error_of(rates, lines, min_games=5)["played"] == 3


def test_freeze_of_by_hand_and_its_flag_on_both_sides_of_the_line():
    actual = {1: 70, 2: 10, 3: 30, 4: 31}
    low = {1: 70.0, 2: 12.0, 3: 30.0, 4: 60.0, 5: 40.0}  # 5 never played: 0 games
    got = fc.freeze_of(low, actual)
    assert got["projected"] == 5 and got["short"] == 3  # 2, 3 and 5 played 30 or fewer
    assert got["median_projected_games"] == 30.0 and got["equal"] == 2  # 1 and 3
    assert got["flagged"] is True and "never a refusal" in got["note"]
    high = {1: 75.0, 2: 70.0, 3: 50.0, 5: 66.0}
    got = fc.freeze_of(high, actual)
    assert got["median_projected_games"] == 66.0 and got["flagged"] is False and got["equal"] == 0
    at = fc.freeze_of({2: 50.0}, actual)
    assert at["median_projected_games"] == fc.FREEZE_LINE and at["flagged"] is False
    assert fc.freeze_of({1: 70.0}, actual)["median_projected_games"] is None
