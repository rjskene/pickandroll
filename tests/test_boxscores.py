"""#126, part 2: ESPN's final box scores by date, and Yahoo's players matched to them.

Every body here is made up in ESPN's shape: four teams, made-up players and lines.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from pickandroll.sources import boxscores as bx
from pickandroll.sources import schedule

NOW = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
KEYS = [
    "minutes",
    "points",
    "fieldGoalsMade-fieldGoalsAttempted",
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    "freeThrowsMade-freeThrowsAttempted",
    "rebounds",
    "assists",
    "turnovers",
    "steals",
    "blocks",
    "offensiveRebounds",
    "defensiveRebounds",
    "fouls",
    "plusMinus",
]


def event(
    eid: str,
    start: str,
    home: str,
    away: str,
    status: str = "STATUS_FINAL",
    season_type: int = 2,
) -> dict[str, Any]:
    return {
        "id": eid,
        "date": start,
        "season": {"year": 2027, "type": season_type},
        "status": {"type": {"name": status, "completed": status == "STATUS_FINAL"}},
        "competitions": [
            {"competitors": [{"team": {"abbreviation": home}}, {"team": {"abbreviation": away}}]}
        ],
    }


def row(espn: str, name: str, stats: list[str] | None = None) -> dict[str, Any]:
    return {
        "athlete": {"id": espn, "displayName": name},
        "stats": stats or [],
        "didNotPlay": stats is None,
    }


def summary(
    sides: dict[str, list[dict[str, Any]]], injured: dict[str, list[tuple[str, str]]] | None = None
) -> dict[str, Any]:
    return {
        "boxscore": {
            "players": [
                {"team": {"abbreviation": team}, "statistics": [{"keys": KEYS, "athletes": rows}]}
                for team, rows in sides.items()
            ]
        },
        "injuries": [
            {
                "team": {"abbreviation": team},
                "injuries": [{"athlete": {"id": e, "displayName": n}} for e, n in out],
            }
            for team, out in (injured or {}).items()
        ],
    }


#: 30 minutes, 20 points on 8-15 with 2-5 threes and 2-2 free throws, 6 boards (1 offensive),
#: 4 assists, 2 turnovers, 1 steal, no block.
LINE = ["30", "20", "8-15", "2-5", "2-2", "6", "4", "2", "1", "0", "1", "5", "3", "+4"]


class Fake:
    """ESPN's two endpoints from made-up bodies: scoreboards by date, summaries by event."""

    def __init__(self) -> None:
        self.boards: dict[str, dict[str, Any]] = {}
        self.games: dict[str, dict[str, Any]] = {}
        self.urls: list[str] = []
        self.down: set[str] = set()

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if url in self.down:
            raise RuntimeError(f"{url}: HTTP 503")
        if url.startswith(schedule.SCOREBOARD.split("?")[0]):
            day = url.rsplit("=", 1)[1]
            return json.dumps(self.boards.get(day, {"events": []}))
        eid = url.rsplit("=", 1)[1]
        return json.dumps(self.games[eid])


def test_a_scoreboard_gives_the_regular_seasons_games_in_yahoos_teams():
    body = {
        "events": [
            event("1", "2026-10-28T23:30Z", "GS", "NY"),
            event("2", "2026-10-29T00:00Z", "AAA", "BBB", status="STATUS_IN_PROGRESS"),
            event("3", "2026-10-29T00:00Z", "CCC", "DDD", status="STATUS_POSTPONED"),
            event("4", "2026-10-29T00:00Z", "EEE", "FFF", season_type=1),
        ]
    }
    games = bx.games_of(body)
    assert [(g["id"], g["teams"], g["final"], g["played"]) for g in games] == [
        ("1", ["GSW", "NYK"], True, True),
        ("2", ["AAA", "BBB"], False, True),
        ("3", ["CCC", "DDD"], False, False),
    ]
    assert games[0]["start"] == "2026-10-28T23:30Z"


def test_a_summary_gives_each_players_line_and_the_injured_with_none():
    body = summary(
        {
            "GS": [row("101", "Brooks Able", LINE), row("102", "Grant Baker")],
            "NY": [row("201", "Casey Cole", LINE)],
        },
        injured={"GS": [("103", "Drew Dunn"), ("101", "Brooks Able")]},
    )
    players = bx.players_of(body)
    assert players["101"]["team"] == "GSW" and players["201"]["team"] == "NYK"
    assert players["101"]["line"] == {
        "min": 30.0,
        "pts": 20.0,
        "fgm": 8.0,
        "fga": 15.0,
        "threes": 2.0,
        "ftm": 2.0,
        "fta": 2.0,
        "reb": 6.0,
        "ast": 4.0,
        "tov": 2.0,
        "stl": 1.0,
        "blk": 0.0,
        "oreb": 1.0,
        "dreb": 5.0,
    }
    # A coach's decision and the injury report: kept, with no line.
    assert players["102"]["line"] is None
    assert players["103"] == {"name": "Drew Dunn", "team": "GSW", "line": None}


def test_a_day_is_cached_once_every_game_on_it_is_over(tmp_path):
    fake = Fake()
    fake.boards["20261026"] = {
        "events": [
            event("1", "2026-10-26T23:30Z", "GS", "NY"),
            event("2", "2026-10-27T02:00Z", "AAA", "BBB", status="STATUS_IN_PROGRESS"),
        ]
    }
    fake.boards["20261027"] = {
        "events": [
            event("3", "2026-10-27T23:30Z", "GS", "AAA"),
            event("4", "2026-10-27T23:30Z", "NY", "BBB", status="STATUS_POSTPONED"),
        ]
    }
    fake.games["1"] = summary({"GS": [row("101", "Brooks Able", LINE)]})
    fake.games["3"] = summary({"GS": [row("101", "Brooks Able", LINE)]})
    days = [date(2026, 10, 26), date(2026, 10, 27)]
    out = bx.read_days(days, fake, tmp_path, NOW)
    # A game still on: the day waits; a postponed game: no summary asked, the day kept.
    assert out == {"read": ["2026-10-27"], "pending": ["2026-10-26"], "failed": [], "left": []}
    assert bx.summary_url("4") not in fake.urls and bx.summary_url("1") not in fake.urls
    kept = bx.load_days(days, tmp_path)
    assert list(kept) == [date(2026, 10, 27)]
    [game] = kept[date(2026, 10, 27)]
    assert game["id"] == "3" and game["teams"] == ["AAA", "GSW"]
    assert game["players"]["101"]["line"]["pts"] == 20.0
    # Once over, the day is read; a cached day is never read again.
    fake.boards["20261026"]["events"][1]["status"]["type"] = {
        "name": "STATUS_FINAL",
        "completed": True,
    }
    fake.games["2"] = summary({"AAA": [row("301", "Ellis Ford", LINE)]})
    fake.urls.clear()
    out = bx.read_days(days, fake, tmp_path, NOW)
    assert out["read"] == ["2026-10-26"]
    assert fake.urls == [
        schedule.scoreboard_url(date(2026, 10, 26)),
        bx.summary_url("1"),
        bx.summary_url("2"),
    ]


def test_a_day_a_request_fails_on_is_left_and_the_limit_holds(tmp_path):
    fake = Fake()
    fake.boards["20261026"] = {"events": [event("1", "2026-10-26T23:30Z", "GS", "NY")]}
    fake.down.add(bx.summary_url("1"))
    days = [date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]
    out = bx.read_days(days, fake, tmp_path, NOW, limit=2)
    assert out == {
        "read": ["2026-10-27"],
        "pending": [],
        "failed": ["2026-10-26"],
        "left": ["2026-10-28"],
    }
    assert bx.load_days(days, tmp_path) == {date(2026, 10, 27): []}


def test_yahoos_players_match_by_id_then_team_then_name_alone():
    games = [
        {
            "teams": ["GSW", "NYK"],
            "players": {
                "101": {"name": "Brooks Able", "team": "GSW", "line": {}},
                "201": {"name": "Casey Cole", "team": "NYK", "line": {}},
                "202": {"name": "Jordan Hale", "team": "NYK", "line": {}},
            },
        },
        {
            "teams": ["AAA", "BBB"],
            "players": {
                # Traded inside the span: seen on both teams.
                "301": {"name": "Ellis Ford", "team": "AAA", "line": {}},
                "401": {"name": "Jordan Hale", "team": "BBB", "line": None},
            },
        },
        {"teams": ["AAA"], "players": {"301": {"name": "Ellis Ford", "team": "BBB", "line": {}}}},
    ]
    players = {
        1: ("Brooks Able", "GSW"),
        2: ("Ellis Ford", "BBB"),
        3: ("Casey Cole", "GSW"),  # his team as Yahoo listed it before a trade
        4: ("Jordan Hale", "NYK"),
        5: ("Jordan Hale", None),  # two of the name and no team: not matched
        6: ("Nobody Here", "GSW"),
        7: ("Kept Before", "GSW"),
    }
    found = bx.match(players, games, {7: "999"})
    assert found == {
        1: ("101", "team"),
        2: ("301", "team"),
        3: ("201", "name"),
        4: ("202", "team"),
        7: ("999", "id"),
    }


def test_the_ids_matched_are_kept(tmp_path):
    assert bx.load_ids(tmp_path) == {}
    bx.save_ids(tmp_path, {12: "202", 3: "101"})
    assert bx.load_ids(tmp_path) == {3: "101", 12: "202"}
