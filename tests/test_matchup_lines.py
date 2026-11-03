"""The Matchup view's players' week (#304): each player's line so far as Yahoo counts it, the
rest of the week and the two added, and each team's lines reconciling with the scoreboard: a
player dropped this week and the makes and attempts the box scores could not place are on no
player's row, and a finished day the matchup page was read before is listed, never filled in.

The league is the season tests' made-up one, its box scores made up here; nothing is from
Basketball Monster.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from pickandroll.api import season_matchup as sm
from pickandroll.api.season_scorecard import BOXSCORES_DIR
from pickandroll.api.seasons import STATE, season_dir
from pickandroll.season import so_far as sf
from pickandroll.season import weekly as wk
from tests.test_season import LEAGUE, fixture_names, projection_csv, season_client

KEY = "matchup/1/4-10"
DASHES = dict.fromkeys(["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"], "-")
COUNTED = {"pts": 12, "threes": 1, "reb": 4, "ast": 3, "stl": 1, "blk": 0, "tov": 2}
COUNTED |= {"fgm": 5, "fga": 9, "ftm": 1, "fta": 2}
BENCHED = {**COUNTED, "pts": 20, "reb": 9, "fgm": 8, "fga": 14}
UNBOXED = {"FG%": ".500", "FT%": "-", "3PTM": "0", "PTS": "8", "REB": "2"}
UNBOXED |= {"AST": "1", "ST": "0", "BLK": "1", "TO": "1"}


def printed(line: dict) -> dict:
    return {
        "FG%": f"{line['fgm'] / line['fga']:.3f}".lstrip("0"),
        "FT%": f"{line['ftm'] / line['fta']:.3f}".lstrip("0"),
        "3PTM": str(line["threes"]),
        "PTS": str(line["pts"]),
        "REB": str(line["reb"]),
        "AST": str(line["ast"]),
        "ST": str(line["stl"]),
        "BLK": str(line["blk"]),
        "TO": str(line["tov"]),
    }


def box_day(cache, day: str, espn: str, line: dict) -> None:
    game = {"id": day, "start": f"{day}T23:00:00Z", "teams": ["AAA", "BBB"]}
    game["players"] = {espn: {"name": "made up", "team": "AAA", "line": line}}
    (cache / f"{day}.json").write_text(json.dumps({"date": day, "games": [game]}))


@pytest.fixture
def week(tmp_path):
    """The fixture league's matchup, its page read on Tuesday morning (before that day's games)
    with a player table: my first player counted one of his two games, the box scores hold
    both; my second has no box scores; the rest of my count is a player dropped since; theirs
    all on no row."""
    with season_client(tmp_path) as client:
        projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
        client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
        v = client.get(f"/seasons/{LEAGUE}").json()
        mine = [s["player"]["yahoo_id"] for s in v["roster"]]
        path = season_dir(client.data_dir, LEAGUE) / STATE
        state = json.loads(path.read_text())
        part = state["parts"][KEY]
        part["data"]["players"] = {
            "4": [
                {"player": mine[0], "slot": "PG", "line": printed(COUNTED)},
                {"player": mine[1], "slot": "SG", "line": UNBOXED},
                *({"player": k, "slot": "BN", "line": DASHES} for k in mine[2:]),
            ],
            "10": [],
        }
        part["data"]["games"] = {
            "4": {"played": 3, "scheduled": 31},
            "10": {"played": 2, "scheduled": 32},
        }
        part["fetched_at"] = "2026-10-20T10:00:00+00:00"
        path.write_text(json.dumps(state))
        cache = client.data_dir / BOXSCORES_DIR
        cache.mkdir(exist_ok=True)
        box_day(cache, "2026-10-19", "e1", COUNTED)
        box_day(cache, "2026-10-20", "e1", BENCHED)
        (cache / "ids.json").write_text(json.dumps({str(mine[0]): "e1"}))
        r = client.get(f"/seasons/{LEAGUE}/matchup")
        assert r.status_code == 200, r.text
        yield r.json(), mine, part["data"]["totals"]


def test_a_players_counted_games_are_placed_from_his_box_scores(week):
    m, mine, _ = week
    rows = {r["player"]: r for r in m["players"]["mine"]}
    a = rows[mine[0]]
    so, rest, total = a["so_far"], a["rest"], a["total"]
    # One of his two games counted: the box scores' set that adds up to Yahoo's row.
    assert (so["games"], so["fgm"], so["fga"], so["why"]) == (1, 5, 9, None)
    assert so["fg_pct"] == pytest.approx(5 / 9, abs=1e-4)
    assert total["pts"] == pytest.approx(12 + rest["pts"], abs=1e-3)
    assert total["fg_pct"] == pytest.approx((5 + rest["fgm"]) / (9 + rest["fga"]), abs=1e-4)
    assert total["games"] == 1 + rest["games"]
    # No box scores: Yahoo's row as printed, its percentage without the attempts behind it.
    b = rows[mine[1]]["so_far"]
    assert (b["why"], b["games"], b["fgm"], b["fg_pct"], b["pts"]) == (
        sf.NO_BOX,
        None,
        None,
        0.5,
        8,
    )
    assert rows[mine[1]]["total"]["fg_pct"] is None and rows[mine[1]]["total"]["games"] is None
    # A row of dashes: no game counted.
    assert rows[mine[2]]["so_far"]["games"] == 0


def test_the_team_lines_reconcile_with_the_scoreboard_through_the_gap_row(week):
    m, _, totals = week
    team = m["team_lines"]["mine"]
    count, gap = team["so_far"], team["gap"]
    made, att = (float(x) for x in totals["4"]["FGM/A*"].split("/"))
    assert (count["pts"], count["fgm"], count["fga"], count["games"]) == (
        float(totals["4"]["PTS"]),
        made,
        att,
        3,
    )
    rows = m["players"]["mine"]
    # Every counting stat: the players' rows plus the gap row are Yahoo's count.
    for s in (*wk.COUNTING, "fgm", "fga", "ftm", "fta"):
        assert sum(r["so_far"][s] or 0 for r in rows) + gap[s] == pytest.approx(count[s], abs=1e-3)
    # The second player's makes are not placed: they are in the gap with the dropped player's.
    assert gap["fgm"] == pytest.approx(made - 5, abs=1e-3)
    assert gap["games"] == 3 - 1
    # The week's total is the scoreboard's projected final.
    cats = {c["cat"]: c for c in m["cats"]}
    assert team["total"]["pts"] == pytest.approx(cats["pts"]["mine"], abs=1e-2)
    assert team["total"]["fg_pct"] == pytest.approx(cats["fg_pct"]["mine"], abs=1e-3)
    assert team["total"]["pts"] == pytest.approx(count["pts"] + team["rest"]["pts"], abs=1e-2)
    # Theirs: no player's row read, so all of their count is in the gap.
    theirs = m["team_lines"]["theirs"]
    assert theirs["gap"]["pts"] == theirs["so_far"]["pts"] == float(totals["10"]["PTS"])


def test_a_finished_day_read_before_its_games_is_listed_in_neither_half(week):
    m, _, _ = week
    assert m["from"] == "2026-10-21"
    [day] = m["unread"]
    assert day["day"] == "2026-10-20" and all(isinstance(n, int) for n in day["games"])


def test_the_unread_days_run_from_the_read_to_the_first_day_projected():
    start, end = date(2026, 10, 19), date(2026, 10, 25)
    evening = datetime(2026, 10, 21, 1, 30, tzinfo=UTC)  # Oct 20, 21:30 Eastern: games began
    assert sm.unread_days(evening, date(2026, 10, 22), start, end) == [date(2026, 10, 21)]
    morning = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    assert sm.unread_days(morning, date(2026, 10, 21), start, end) == []
    assert sm.unread_days(None, date(2026, 10, 21), start, end) == [start, date(2026, 10, 20)]
    # The week over: every day from the read on.
    assert sm.unread_days(morning, None, start, end)[-1] == end


def test_a_points_leagues_team_lines_are_its_fantasy_points():
    week = wk.TeamWeek({1: wk.PlayerWeek(2, 2)}, {"fpts": 50.0, "pts": 40.0}, {})
    rows = [{"so_far": {"fpts": 30.0, "games": 2}}]
    lines = sm.team_lines({"fpts": 41.5}, 3, rows, week, points=True)
    assert lines["so_far"]["fpts"] == 41.5 and lines["gap"]["fpts"] == pytest.approx(11.5)
    assert lines["gap"]["games"] == 1
    assert lines["total"] == {"fpts": 91.5, "games": 5}
