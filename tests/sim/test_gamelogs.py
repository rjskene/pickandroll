"""ESPN's season logs reader (#172, PR 1) on a hand-written response: made-up players, ESPN's
ids only."""

from __future__ import annotations

import json
from pathlib import Path

from pickandroll.sources import gamelogs as gl


def entry(season, period, stats, team=7, split=gl.PER_GAME, source=0):
    return {
        "seasonId": season,
        "statSplitTypeId": split,
        "statSourceId": source,
        "scoringPeriodId": period,
        "proTeamId": team,
        "externalId": f"40{season}{period:03d}",
        "stats": stats,
    }


def line(pts, min_, fgm=5, fga=10, ftm=2, fta=2, threes=1, reb=5, ast=3, stl=1, blk=1, tov=2):
    return {
        "0": pts,
        "1": blk,
        "2": stl,
        "3": ast,
        "6": reb,
        "11": tov,
        "13": fgm,
        "14": fga,
        "15": ftm,
        "16": fta,
        "17": threes,
        "40": min_,
        "42": 1,
    }


def body(season=2026):
    return {
        "players": [
            {
                "player": {
                    "id": 1001,
                    "fullName": "Alpha Made-Up",
                    "stats": [
                        entry(season, 2, line(20, 34.0)),
                        entry(season, 3, {}),
                        entry(season, 5, line(12, 28.5)),
                        entry(
                            season, 0, {**line(1600, 2400.0), "42": 70}, split=0, source=gl.ACTUAL
                        ),
                        entry(
                            season,
                            0,
                            {**line(1700, 2500.0), "42": 75},
                            split=0,
                            source=gl.PROJECTED,
                        ),
                        entry(season + 1, 0, line(1, 1.0), split=0, source=gl.PROJECTED),
                    ],
                }
            },
            {
                "player": {
                    "id": 1002,
                    "fullName": "Beta Made-Up",
                    "stats": [
                        entry(season, 1, line(8, 15.0), team=9),
                        entry(season, 2, line(9, 16.0), team=9),
                    ],
                }
            },
        ]
    }


def test_lines_of_reads_every_scheduled_game_in_order():
    lines = gl.lines_of(body(), 2026)
    assert [(ln.player, ln.period) for ln in lines] == [
        ("1001", 2),
        ("1001", 3),
        ("1001", 5),
        ("1002", 1),
        ("1002", 2),
    ]
    first = lines[0]
    assert first.played and first.minutes == 34.0 and first.team == "7"
    assert (
        first.stats["pts"] == 20.0 and first.stats["threes"] == 1.0 and "minutes" not in first.stats
    )
    assert set(first.stats) == {
        "pts",
        "blk",
        "stl",
        "ast",
        "reb",
        "tov",
        "fgm",
        "fga",
        "ftm",
        "fta",
        "threes",
    }
    sat = lines[1]
    assert not sat.played and sat.minutes == 0.0 and sat.stats == {}
    assert gl.lines_of(body(), 2025) == []


def test_minutes_is_espn_id_40_as_a_box_score_line_counts_them():
    # The box-score cache writes a line's minutes under ``min``; the player view's id 40 is the
    # same figure, pinned here on a made-up line.
    boxscore_line = {"min": 34.0, "pts": 20.0, "reb": 5.0}
    ln = gl.lines_of(body(), 2026)[0]
    assert ln.minutes == boxscore_line["min"]
    assert ln.stats["pts"] == boxscore_line["pts"] and ln.stats["reb"] == boxscore_line["reb"]
    assert gl.STAT_IDS["40"] == "minutes"


def test_totals_and_per_game():
    actual = gl.totals_of(body(), 2026)
    projected = gl.totals_of(body(), 2026, gl.PROJECTED)
    assert actual["1001"]["pts"] == 1600.0 and actual["1001"]["games"] == 70.0
    assert projected["1001"]["pts"] == 1700.0 and projected["1001"]["games"] == 75.0
    assert "1002" not in actual
    rates = gl.per_game(actual)
    assert rates["1001"]["pts"] == 1600.0 / 70
    assert "games" not in rates["1001"]
    assert gl.names_of(body()) == {"1001": "Alpha Made-Up", "1002": "Beta Made-Up"}


def test_read_seasons_requests_each_season_once_and_lists_a_failure(tmp_path: Path):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        if "/seasons/2024/" in url:
            raise OSError("no")
        return json.dumps(body(2025))

    out = gl.read_seasons([2025, 2024], fetch, tmp_path)
    assert out == {"read": [2025], "cached": [], "failed": [2024]}
    assert len(calls) == 2 and gl.season_url(2025) in calls
    assert (tmp_path / "2025.json").exists() and not (tmp_path / "2024.json").exists()
    saved = json.loads((tmp_path / "2025.json").read_text())
    assert saved["season"] == 2025 and "fetched_at" in saved
    assert gl.load_season(2025, tmp_path) == body(2025)
    assert gl.load_season(2024, tmp_path) is None
    again = gl.read_seasons([2025, 2024], fetch, tmp_path)
    assert again == {"read": [], "cached": [2025], "failed": [2024]}
    assert len(calls) == 3  # the cached season is not requested again; the failed one once more
    assert gl.FILTER_HEADER == "X-Fantasy-Filter" and "700" in gl.FILTER
