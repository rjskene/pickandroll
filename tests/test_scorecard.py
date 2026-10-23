"""#126: the Monday scorecard, a recorded week against the decision log's projection of it.

Every record, entry and figure here is made up: four teams, nine categories, team 1 mine.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, season_scorecard
from pickandroll.season import scorecard as sc
from pickandroll.season.calendar import Week
from tests.test_record import SCRIPT, _moved, write_league

CATS = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"]
WEEK2 = Week(2, date(2026, 10, 26), date(2026, 11, 1))


def totals(**over: float) -> dict[str, float]:
    base = {"fgm": 160.0, "fga": 340.0, "ftm": 60.0, "fta": 80.0, "threes": 40.0, "pts": 420.0}
    base |= {"reb": 180.0, "ast": 100.0, "stl": 30.0, "blk": 20.0, "tov": 50.0}
    return base | over


def record(week: int = 2, outcome: str = "W", **mine: float) -> dict[str, Any]:
    """Week ``week``: team 1 (mine) against team 2, won 5-3-1 unless ``outcome`` says otherwise."""
    start = {1: "2026-10-19", 2: "2026-10-26", 3: "2026-11-02"}[week]
    end = {1: "2026-10-25", 2: "2026-11-01", 3: "2026-11-08"}[week]
    won, lost = (5, 3) if outcome == "W" else (3, 5) if outcome == "L" else (4, 4)
    return {
        "league": "100001",
        "week": week,
        "start": start,
        "end": end,
        "scoring": "categories",
        "cats": CATS,
        "teams": {
            "1": {
                "opponent": 2,
                "totals": totals(**mine),
                "result": {"won": won, "lost": lost, "tied": 1, "outcome": outcome},
            },
            "2": {
                "opponent": 1,
                "totals": totals(threes=45.0, reb=170.0, tov=40.0),
                "result": {"won": lost, "lost": won, "tied": 1, "outcome": "L"},
            },
        },
        "standings": {
            "teams": [
                {"team_id": 1, "rank": 2, "wins": 9, "losses": 7, "ties": 2},
                {"team_id": 2, "rank": 3, "wins": 7, "losses": 9, "ties": 2},
            ]
        },
    }


def block(matchup: float, p: dict[str, float]) -> dict[str, Any]:
    cats = {c: {"mine": 100.0, "theirs": 90.0, "p_win": p.get(c, 0.5)} for c in CATS}
    return {"cats": cats, "expected": sum(x["p_win"] for x in cats.values()), "matchup": matchup}


def entry(
    at: str,
    first_day: str,
    matchup: float = 0.6,
    system: str = "bbm",
    moves: tuple[dict[str, Any], ...] = (),
    **p: float,
):
    return {
        "id": f"{at}-moves-{system}",
        "at": at,
        "source": "moves",
        "system": {"key": system},
        "first_day": first_day,
        "sets": [
            {
                "key": "week",
                "moves": list(moves),
                "week": {"before": block(matchup, p), "after": None},
            }
        ],
    }


def logged(add: int, drop: int | None, value: float = 7.25) -> dict[str, Any]:
    """A recommended move as the log keeps it (#126): its gain and its value in scorer units."""
    horizon = {"from": "2026-10-27", "to": "2026-11-01", "add_games": 3, "drop_games": 2}
    return {
        "add": add,
        "drop": drop,
        "from": "2026-10-27",
        "bid": None,
        "gain": {"week": 0.21, "three": 0.4},
        "value": {"add": 2.5, "drop": 2.0, "horizons": {"week": {**horizon, "value": value}}},
    }


def test_the_projection_is_the_last_solve_that_saw_the_whole_week():
    entries = [
        # Sunday: its week is the one before.
        entry("2026-10-25T09:00:00+00:00", "2026-10-25", 0.9),
        entry("2026-10-26T09:00:00+00:00", "2026-10-26", 0.55),
        entry("2026-10-26T10:00:00+00:00", "2026-10-26", 0.61),
        # The other system, and a solve after Monday's games began (its first day is Tuesday).
        entry("2026-10-26T11:00:00+00:00", "2026-10-26", 0.2, system="yahoo"),
        entry("2026-10-27T02:00:00+00:00", "2026-10-27", 0.3),
    ]
    assert sc.projection(entries, WEEK2, "bbm")["sets"][0]["week"]["before"]["matchup"] == 0.61
    assert sc.projection(entries, WEEK2, "yahoo")["sets"][0]["week"]["before"]["matchup"] == 0.2
    assert sc.projection(entries[:1], WEEK2, "bbm") is None


def test_with_no_system_named_a_week_is_projected_on_its_entrys_system_in_force():
    # #152: each entry records the knob file's system for its league when it was logged.
    def on(e: dict[str, Any], file_system: str) -> dict[str, Any]:
        return {**e, "knobs": {"system": e["system"]["key"], "file_system": file_system}}

    def matchup(found: Mapping[str, Any] | None) -> float | None:
        return found["sets"][0]["week"]["before"]["matchup"] if found else None

    entries = [
        # Logged before entries kept it: Basketball Monster's, the file's default.
        entry("2026-10-26T04:00:00+00:00", "2026-10-26", 0.5),
        on(entry("2026-10-26T05:00:00+00:00", "2026-10-26", 0.61), "bbm"),
        # The dashboard named Yahoo's while the file had Basketball Monster's in force.
        on(entry("2026-10-26T06:00:00+00:00", "2026-10-26", 0.2, system="yahoo"), "bbm"),
    ]
    assert matchup(sc.projection(entries, WEEK2, None)) == 0.61
    assert matchup(sc.projection(entries[:1], WEEK2, None)) == 0.5
    assert matchup(sc.projection(entries, WEEK2, "yahoo")) == 0.2
    # The file then put the league on the blend: a solve on it before the week's games is the
    # last in force, and the entries before it keep the system they recorded.
    blend = on(entry("2026-10-26T07:00:00+00:00", "2026-10-26", 0.7, system="blend"), "blend")
    assert matchup(sc.projection([*entries, blend], WEEK2, None)) == 0.7
    assert matchup(sc.projection([*entries, blend], WEEK2, "bbm")) == 0.61
    assert sc.on_system(entries[0], None) and not sc.on_system(entries[2], None)


def test_a_category_is_won_on_its_total_a_percentage_on_its_makes_and_fewer_turnovers():
    assert sc.total({"fgm": 161.0, "fga": 342.0, "fg_pct": 0.5}, "fg_pct") == 0.471
    assert sc.total({"fg_pct": 0.5}, "fg_pct") == 0.5
    assert sc.won("tov", 40.0, 50.0) == 1.0 and sc.won("pts", 40.0, 50.0) == 0.0
    assert sc.won("reb", 1.0, 1.0) == 0.5 and sc.won("reb", None, 1.0) is None


def test_a_weeks_card_sets_the_projection_against_the_result():
    entries = [entry("2026-10-26T09:00:00+00:00", "2026-10-26", 0.6, threes=0.3, tov=0.7)]
    moves = [{"add": 11, "drop": 12, "day": "2026-10-27", "match": {"kind": "as_recommended"}}]
    card = sc.week_card(record(), entries, 1, "bbm", moves)
    assert card["week"] == 2 and card["projected"]["matchup"] == 0.6
    assert card["projected"]["expected"] == pytest.approx(0.3 + 0.7 + 7 * 0.5)
    assert card["actual"] == {
        "opponent": 2,
        "result": {"won": 5, "lost": 3, "tied": 1, "outcome": "W"},
        "won": 1.0,
        "categories": 5.5,
    }
    rows = {r["cat"]: r for r in card["cats"]}
    assert rows["threes"]["p_win"] == 0.3 and rows["threes"]["won"] == 0.0
    assert rows["reb"]["won"] == 1.0 and rows["tov"]["won"] == 0.0 and rows["pts"]["won"] == 0.5
    assert rows["threes"]["actual"] == {"mine": 40.0, "theirs": 45.0}
    assert card["standing"] == {"rank": 2, "record": "9-7-2", "teams": 2}
    assert card["moves"] == moves
    # Unprojected: shown, with no projection.
    bare = sc.week_card(record(), [], 1, "bbm")
    assert bare["projected"] is None and bare["actual"]["won"] == 1.0
    assert all(r["p_win"] is None for r in bare["cats"])
    # The games lost to the lineup as the record counted them (#149); none in an older record.
    count = {"lost": 2, "days_read": 6, "days": 7, "unmatched": 0}
    assert sc.week_card({**record(), "lineup": count}, [], 1, "bbm")["lineup"] == count
    assert bare["lineup"] is None


def test_a_points_leagues_week_is_its_points_and_its_matchup():
    rec = record()
    rec["scoring"] = "points"
    rec["teams"]["1"]["result"] = {"points": 810.5, "against": 790.25, "outcome": "W"}
    card = sc.week_card(rec, [], 1, "bbm")
    assert card["actual"]["categories"] is None and card["actual"]["won"] == 1.0
    assert card["cats"] == [
        {
            "cat": "fpts",
            "p_win": None,
            "projected": None,
            "actual": {"mine": 810.5, "theirs": 790.25},
            "won": 1.0,
        }
    ]


def test_calibration_pools_the_projected_weeks_brier_and_category_buckets():
    projected = [
        sc.week_card(record(), [entry("2026-10-26T09:00:00+00:00", "2026-10-26", 0.8)], 1, "bbm"),
        sc.week_card(
            record(outcome="L"),
            [entry("2026-10-26T09:00:00+00:00", "2026-10-26", 0.6, threes=0.9, tov=0.15)],
            1,
            "bbm",
        ),
    ]
    out = sc.calibration([*projected, sc.week_card(record(), [], 1, "bbm")])
    assert out["weeks"] == 2
    # (0.8 - 1)^2 and (0.6 - 0)^2.
    assert out["brier"] == pytest.approx((0.04 + 0.36) / 2)
    buckets = {b["from"]: b for b in out["buckets"]}
    # Every category at 0.5 but two: 0.9 (threes, lost) and 0.15 (tov, lost).
    assert buckets[0.4]["count"] == 9 + 7 and buckets[0.4]["odds"] == 0.5
    assert buckets[0.8] == {"from": 0.8, "to": 1.0, "count": 1, "odds": 0.9, "won": 0.0}
    assert buckets[0.0]["count"] == 1 and buckets[0.0]["won"] == 0.0
    assert buckets[0.2]["count"] == 0 and buckets[0.2]["odds"] is None


def test_the_season_to_date_sums_the_projected_weeks_and_keeps_the_record():
    cards = [
        sc.week_card(record(1, "T"), [], 1, "bbm"),
        sc.week_card(record(2), [entry("2026-10-26T09:00:00+00:00", "2026-10-26", 0.6)], 1, "bbm"),
        sc.week_card(
            record(3, "L"), [entry("2026-11-02T09:00:00+00:00", "2026-11-02", 0.3)], 1, "bbm"
        ),
    ]
    out = sc.to_date(cards)
    assert out["weeks"] == 3 and out["projected"] == 2 and out["record"] == "1-1-1"
    assert out["expected_wins"] == 0.9 and out["wins"] == 1.0
    assert out["expected_categories"] == 9.0 and out["categories"] == 5.5 + 3.5
    assert out["standing"]["rank"] == 2


# --------------------------------------------------------------------------- the routes
PUBLIC, OTHER, PRIVATE = "100001", "100004", "100002"


def write(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def season_folder(data_dir: Path, league: str) -> Path:
    return data_dir / "leagues" / league / "season"


def put_week(data_dir: Path, league: str, rec: dict[str, Any]) -> None:
    write(
        season_folder(data_dir, league) / "weeks" / f"{rec['week']}.json", {**rec, "league": league}
    )


def put_entries(data_dir: Path, league: str, day: str, entries: list[dict[str, Any]]) -> None:
    write(season_folder(data_dir, league) / "decisions" / f"{day}.json", entries)


#: My move of week 2, Tuesday 9:00 US Eastern: an add and its drop, and a lone add of team 2's.
WEEK2_MOVES = [
    _moved("add", 11, 1, "Oct 27, 9:00 am", 0),
    _moved("drop", 12, 1, "Oct 27, 9:00 am", 0),
    _moved("add", 13, 2, "Oct 27, 10:00 am", 1),
]


@pytest.fixture
def client(tmp_path):
    for league in (PUBLIC, OTHER):
        write_league(tmp_path, league)
    write_league(tmp_path, PRIVATE, public=False)
    # The public league: week 1 unprojected (the log began after it), week 2 projected on its
    # Monday morning, then my move on Tuesday as the solve before it recommended.
    put_week(tmp_path, PUBLIC, record(1, "T"))
    put_week(tmp_path, PUBLIC, {**record(2), "transactions": WEEK2_MOVES})
    monday = entry("2026-10-26T12:00:00+00:00", "2026-10-26", 0.7, threes=0.3)
    tuesday = entry("2026-10-27T12:30:00+00:00", "2026-10-27", 0.8, moves=(logged(11, 12),))
    put_entries(tmp_path, PUBLIC, "2026-10-26", [monday])
    put_entries(tmp_path, PUBLIC, "2026-10-27", [tuesday])
    # Another public league recorded but never projected; the private one projected.
    put_week(tmp_path, OTHER, record(2, "L"))
    put_week(tmp_path, PRIVATE, record(2))
    put_entries(
        tmp_path, PRIVATE, "2026-10-26", [entry("2026-10-26T12:00:00+00:00", "2026-10-26", 0.4)]
    )
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: None)
    with TestClient(app) as c:
        yield c


def test_a_leagues_scorecard_sets_each_recorded_week_against_its_projection(client):
    r = client.get(f"/seasons/{PUBLIC}/scorecard")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "recorded" and out["week"] == 2 and out["public"] is True
    card = out["card"]
    # The Monday solve, not Tuesday's (whose week had begun).
    assert card["projected"]["matchup"] == 0.7 and card["actual"]["won"] == 1.0
    # My move of the week (team 2's is not mine), matched to the solve before it, with the
    # log's projection of it; no entry here keeps a scorer, so it is not scored.
    [move] = card["moves"]
    assert (move["add"], move["drop"], move["day"]) == (11, 12, "2026-10-27")
    assert move["match"]["kind"] == "as_recommended" and move["match"]["near"] is True
    assert move["projected"]["set"] == "week" and move["projected"]["gain"]["week"] == 0.21
    assert move["projected"]["value"]["horizons"]["week"]["value"] == 7.25
    assert move["realized"]["valued"] is False and move["realized"]["reason"] == "no_scorer"
    assert move["group"] == "unscored"
    assert out["players"] == {"11": "Player 11", "12": "Player 12"}
    td = out["to_date"]
    assert td["weeks"] == 2 and td["projected"] == 1 and td["record"] == "1-0-1"
    assert td["moves"]["made"] == 1 and td["moves"]["as_recommended"] == 1
    assert td["moves"]["projected_value"] == {"week": 7.25} and td["moves"]["unscored"] == 1
    assert out["calibration"]["weeks"] == 1
    assert out["calibration"]["brier"] == pytest.approx(0.09)
    # A past week, and one not recorded.
    first = client.get(f"/seasons/{PUBLIC}/scorecard", params={"week": 1}).json()
    assert (
        first["week"] == 1 and first["card"]["projected"] is None and first["card"]["moves"] == []
    )
    assert (
        client.get(f"/seasons/{PUBLIC}/scorecard", params={"week": 3}).json()["status"]
        == "not_recorded"
    )
    assert client.get("/seasons/999999/scorecard").status_code == 404


def test_every_leagues_scorecard_pools_the_public_leagues_and_keeps_the_private_apart(client):
    r = client.get("/seasons/scorecard")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["week"] == 2 and out["skipped"] == []
    assert {p["league"]: p["status"] for p in out["leagues"]} == {
        PUBLIC: "recorded",
        OTHER: "recorded",
        PRIVATE: "recorded",
    }
    week = out["pooled"]["week"]
    # The public league that projected the week, not the one that did not, nor the private one.
    assert week["leagues"] == 1 and week["left_out"] == [OTHER] and week["not_recorded"] == []
    assert week["brier"] == pytest.approx(0.09)
    md = out["markdown"]
    assert md.startswith("## Scorecard, week 2 (Oct 26 - Nov 1)")
    assert "Pooled over 1 public league: matchup odds Brier 0.090" in md
    assert f"Left out, no projection of the week: {OTHER}." in md
    assert (
        f"| {PUBLIC} | 70% to win, 4.3 categories | W 5-3-1 | 5.5 | 2nd of 2, 9-7-2 | 1 (1 as recommended) |"
        in md
    )
    assert "Private league, suggestions only, never pooled:" in md
    assert (
        f"- League {PUBLIC}: added Player 11 and dropped Player 12 (as recommended, near a solve)"
        in md
    )
    unscored = "0 moves scored; 0 realized only; 1 unscored (1 with no scorer logged)"
    assert f"- Realized, the public leagues: this week {unscored}. Season to date {unscored}." in md
    # Public text: leagues by id, no team names, no per-move value.
    assert "Team" not in md and "7.25" not in md
    # A week only some leagues recorded: the others say so.
    one = client.get("/seasons/scorecard", params={"week": 1}).json()
    assert one["pooled"]["week"]["leagues"] == 0
    assert set(one["pooled"]["week"]["not_recorded"]) == {OTHER}


def test_the_markdown_sums_the_public_leagues_games_lost_to_the_lineup(tmp_path):
    for league in (PUBLIC, OTHER):
        write_league(tmp_path, league)
    write_league(tmp_path, PRIVATE, public=False)

    def put(lineups: dict[str, dict[str, Any]]) -> str:
        for league, count in lineups.items():
            put_week(tmp_path, league, {**record(2), "lineup": count})
        app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: None)
        with TestClient(app) as c:
            return c.get("/seasons/scorecard").json()["markdown"]

    count = {"lost": 2, "days_read": 5, "days": 7, "unmatched": 0}
    md = put(
        {
            PUBLIC: count,
            OTHER: {**count, "lost": 1, "days_read": 7},
            PRIVATE: {**count, "lost": 4},
        }
    )
    # The private league's games are never in the public sum.
    assert (
        "- Lineup: 3 player-games lost over the public leagues (12 of 14 league-days read)." in md
    )
    none = {"lost": None, "days_read": 0, "days": 7, "unmatched": 0}
    assert "Lineup:" not in put({PUBLIC: none, OTHER: none, PRIVATE: count})


def test_a_week_recorded_before_its_transactions_were_kept_reads_the_seasons_page():
    rec = record(2)
    season = SimpleNamespace(transactions=[])
    assert season_scorecard.week_moves(rec, 1, season) == []
    from pickandroll.season.state import Transaction

    season.transactions = [Transaction.from_dict(t) for t in WEEK2_MOVES]
    [made] = season_scorecard.week_moves(rec, 1, season)
    assert (made.add, made.drop, made.day) == (11, 12, date(2026, 10, 27))
    # A move after the week resolves to the year before: not this week's.
    season.transactions = [Transaction.from_dict(_moved("add", 14, 1, "Nov 3, 9:00 am", 0))]
    assert season_scorecard.week_moves(rec, 1, season) == []


def run_script(*argv: str, call) -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location("season_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.http = lambda api: call
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert mod.main(list(argv)) == 0
    return buf.getvalue()


def test_the_script_prints_the_weeks_markdown_or_a_line_per_league(client):
    def call(method: str, path: str):
        r = client.request(method, path)
        return r.status_code, r.json()

    md = run_script("scorecard", call=call)
    assert md.startswith("## Scorecard, week 2")
    line = run_script("scorecard", PUBLIC, OTHER, call=call).splitlines()
    assert line[0] == (
        f"{PUBLIC} week 2: projected 70% to win, 4.3 categories; W 5-3-1; rank 2 of 2, 9-7-2; "
        "moves 1 (1 as recommended); to date 1-0-1, wins 1 against 0.70 expected; 1 moves unscored"
    )
    assert line[1].startswith(f"{OTHER} week 2: not projected; L 3-5-1")


# --------------------------------------------------------------------------- realized (part 2)
#: The entries' scorer: points on points and rebounds (made up).
SCORER = {"points": {"pts": 1.0, "reb": 1.0}}


def moved(kind: str, pid: int, team: str, when: str, group: int) -> dict[str, Any]:
    """My transaction, its player on NBA team ``team``."""
    player = {"yahoo_id": pid, "name": f"Player {pid}", "nba_team": team}
    return {"kind": kind, "player": player, "team_id": 1, "when": when, "group": group}


def box_game(day: str, hour: int, teams: list[str], **lines: float) -> dict[str, Any]:
    """A final game on ``day`` at ``hour`` UTC; ``lines`` the points of ESPN players ``e<id>``,
    each on the team his Yahoo transaction names."""
    team_of = {"e11": "AAA", "e12": "BBB", "e15": "CCC"}
    return {
        "id": f"{day}-{hour}",
        "start": f"{day}T{hour:02d}:00Z",
        "teams": teams,
        "players": {
            e: {"name": f"Player {e[1:]}", "team": team_of[e], "line": {"pts": pts}}
            for e, pts in lines.items()
        },
    }


def put_box(data_dir: Path, games: list[dict[str, Any]], first: date, last: date) -> None:
    by_day: dict[str, list[dict[str, Any]]] = {}
    for g in games:
        by_day.setdefault(g["start"][:10], []).append(g)
    day = first
    while day <= last:
        write(
            data_dir / "boxscores" / f"{day.isoformat()}.json",
            {"date": day.isoformat(), "games": by_day.get(day.isoformat(), [])},
        )
        day = date.fromordinal(day.toordinal() + 1)


@pytest.fixture
def realized_client(tmp_path):
    write_league(tmp_path, PUBLIC)
    # Week 2: a lone add on Monday 10:00 Eastern after a solve that kept no scorer, then on
    # Tuesday the add and drop recommended by the solve before it, then a lone drop of a player
    # the box scores do not know.
    rows = [
        moved("add", 15, "CCC", "Oct 26, 10:00 am", 0),
        moved("add", 11, "AAA", "Oct 27, 9:00 am", 1),
        moved("drop", 12, "BBB", "Oct 27, 9:00 am", 1),
        moved("drop", 16, "DDD", "Oct 30, 9:00 am", 2),
    ]
    put_week(tmp_path, PUBLIC, {**record(2), "transactions": rows})
    monday = entry("2026-10-26T12:00:00+00:00", "2026-10-26", 0.7)
    tuesday = {
        **entry("2026-10-27T12:30:00+00:00", "2026-10-27", 0.8, moves=(logged(11, 12),)),
        "scorer": SCORER,
    }
    put_entries(tmp_path, PUBLIC, "2026-10-26", [monday])
    put_entries(tmp_path, PUBLIC, "2026-10-27", [tuesday])
    games = [
        # Monday 23:00 UTC: after the lone add, before Tuesday's move.
        box_game("2026-10-26", 23, ["CCC", "BBB"], e15=12.0, e12=30.0),
        box_game("2026-10-27", 23, ["AAA", "DDD"], e11=20.0),
        box_game("2026-10-28", 23, ["BBB", "EEE"], e12=8.0),
        box_game("2026-10-29", 23, ["AAA", "CCC"], e11=10.0, e15=6.0),
        # The unknown player's team, after his drop.
        box_game("2026-10-30", 23, ["DDD", "EEE"]),
    ]
    put_box(tmp_path, games, date(2026, 10, 26), date(2026, 11, 1))
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: None)
    app.state.seasons.clock = lambda: datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    with TestClient(app) as c:
        c.data_dir = tmp_path  # type: ignore[attr-defined]
        yield c


def test_a_moves_realized_value_comes_from_the_box_scores_of_its_players_games(realized_client):
    out = realized_client.get(f"/seasons/{PUBLIC}/scorecard").json()
    lone, pair, gone = out["card"]["moves"]
    # The lone add: valued with the nearest entry's scorer (the one it matched keeps none), so
    # realized only, never set against a projection.
    assert lone["match"]["kind"] == "not_recommended" and lone["group"] == "realized_only"
    assert lone["realized"]["scorer"] == {
        "entry": "2026-10-27T12:30:00+00:00-moves-bbm",
        "own": False,
    }
    assert lone["realized"]["lag_days"] == 0
    week = lone["realized"]["horizons"]["week"]
    assert (week["from"], week["through"], week["complete"]) == ("2026-10-26", "2026-11-01", True)
    assert (week["add_games"], week["value"]) == (2, 18.0)
    # The pair: his games from Tuesday less the dropped player's (Monday's was before it).
    real = pair["realized"]
    assert pair["group"] == "scored" and real["scorer"]["own"] is True and real["lag_days"] == 0
    assert real["add"] == {"yahoo": 11, "espn": "e11", "by": "team"}
    week = real["horizons"]["week"]
    assert (week["add_games"], week["drop_games"], week["value"]) == (2, 1, 22.0)
    # The three weeks after: none of their days is over.
    assert real["horizons"]["three"]["through"] is None
    # A player the box scores do not know: his team's game is a gap, the move unscored.
    assert gone["realized"]["reason"] == "unmatched" and gone["group"] == "unscored"
    assert gone["realized"]["horizons"]["week"]["gaps"] == 1
    # Made three days after the first day of the entry it matched.
    assert gone["realized"]["lag_days"] == 3
    moves = out["to_date"]["moves"]
    groups = (moves["made"], moves["scored"], moves["realized_only"], moves["unscored"])
    assert groups == (3, 1, 1, 1)
    # Every move realized is summed; only the scored one is set against its projection.
    assert moves["realized_value"] == {"week": 40.0} and moves["complete"] == {"week": 2}
    assert moves["compared"] == {
        "moves": 1,
        "projected": 7.25,
        "realized": 22.0,
        "same_way": 1,
        "horizons": {"week": 1},
        "share": 3.0345,
    }
    assert pair["judged"] == "week" and lone["judged"] == "week"
    assert moves["unscored_by"] == {"unmatched": 1} and moves["gaps"] == 1
    # The ESPN ids matched are kept.
    ids = json.loads((realized_client.data_dir / "boxscores" / "ids.json").read_text())
    assert ids == {"11": "e11", "12": "e12", "15": "e15"}
    md = realized_client.get("/seasons/scorecard").json()["markdown"]
    counts = (
        "1 move scored: realized 303% of projected, 1 of 1 in the projected direction; "
        "1 realized only; 1 unscored (1 with a player not matched to the box scores); "
        "1 game of players not matched"
    )
    assert f"- Realized, the public leagues: this week {counts}. Season to date {counts}." in md
    # Counts and ratios only: no value in scorer units, for a move or summed.
    assert not any(x in md for x in ("22.0", "7.25", "40.0", "18.0"))


def test_a_refresh_caches_the_seasons_box_scores_to_yesterday(tmp_path):
    from pickandroll.api.seasons import RefreshJob, SeasonService
    from pickandroll.season.calendar import Calendar
    from pickandroll.sources import boxscores, schedule

    urls: list[str] = []

    def fetch(url: str) -> str:
        urls.append(url)
        if url.startswith(schedule.SCOREBOARD.split("?")[0]):
            return json.dumps({"events": []})
        raise AssertionError(url)

    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    service = SeasonService(tmp_path, lambda: fetch, clock=lambda: now)
    calendar = Calendar((Week(1, date(2026, 10, 19), date(2026, 10, 25)), WEEK2))
    job = RefreshJob(PUBLIC)
    service._box_scores(job, fetch, date(2026, 10, 22), calendar)
    assert job.warnings == {}
    cached = boxscores.load_days(
        [date(2026, 10, 19) + timedelta(n) for n in range(4)], tmp_path / "boxscores"
    )
    assert sorted(cached) == [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]
    # Read once: the next refresh asks nothing.
    urls.clear()
    service._box_scores(job, fetch, date(2026, 10, 22), calendar)
    assert urls == []


def test_the_scored_moves_are_set_against_their_projection_in_share_and_direction():
    def row(projected: float, realized: float, own: bool = True) -> dict[str, Any]:
        span = {"value": realized, "complete": True, "gaps": 0}
        return {
            "match": {"kind": "as_recommended", "near": False},
            "projected": {"value": {"horizons": {"week": {"value": projected}}}},
            "realized": {"valued": True, "scorer": {"own": own}, "horizons": {"week": span}},
        }

    rows = [row(2.0, 3.0), row(1.0, -0.5), row(-1.0, -2.0), row(4.0, 9.0, own=False)]
    for r in rows:
        r["group"] = season_scorecard.group(r)
    s = season_scorecard.moves_summary(rows)
    # The borrowed scorer's move is realized only: summed, never compared.
    assert (s["scored"], s["realized_only"], s["unscored"]) == (3, 1, 0)
    assert s["realized_value"] == {"week": 9.5}
    assert s["compared"] == {
        "moves": 3,
        "projected": 2.0,
        "realized": 0.5,
        "same_way": 2,
        "horizons": {"week": 3},
        "share": 0.25,
    }
    # A projection summed to nothing or less has no share.
    s = season_scorecard.moves_summary([row(-1.0, 1.0)])
    assert s["compared"]["share"] is None
    line = season_scorecard._realized_counts([row(-1.0, 1.0)])
    assert line.startswith(
        "1 move scored: projected not positive, 0 of 1 in the projected direction"
    )


def test_each_move_is_judged_on_the_horizon_its_set_was_recommended_for():
    judged = season_scorecard.judged_horizon
    moves = {"source": "moves"}
    assert judged({"set": "week"}, moves) == "week"
    assert judged({"set": "plan"}, moves) == "week"
    assert judged({"set": "three"}, moves) == "three"
    # A strategy set on the three weeks after; a move with no projection of its own on its week.
    assert judged({"set": "w50"}, {"source": "strategy"}) == "three"
    assert judged(None, None) == "week"

    def row(judged: str, spans: dict[str, tuple[float, float, bool]]) -> dict[str, Any]:
        r = {
            "match": {"kind": "as_recommended", "near": False},
            "judged": judged,
            "projected": {
                "value": {"horizons": {h: {"value": p} for h, (p, _, _) in spans.items()}}
            },
            "realized": {
                "valued": True,
                "scorer": {"own": True},
                "horizons": {
                    h: {"value": x, "complete": done, "gaps": 0}
                    for h, (_, x, done) in spans.items()
                },
            },
        }
        return {**r, "group": season_scorecard.group(r)}

    rows = [
        # The week's set: its week over, set against its week.
        row("week", {"week": (1.0, 2.0, True), "three": (3.0, 1.0, False)}),
        # The three weeks' set: its three weeks over, set against them, never its week.
        row("three", {"week": (0.5, -1.0, True), "three": (2.0, 3.0, True)}),
        # The three weeks' set with them still running: not compared yet, its week over or not.
        row("three", {"week": (0.5, 0.5, True), "three": (2.0, 1.0, False)}),
    ]
    s = season_scorecard.moves_summary(rows)
    assert s["compared"] == {
        "moves": 2,
        "projected": 3.0,
        "realized": 5.0,
        "same_way": 2,
        "horizons": {"week": 1, "three": 1},
        "share": 1.6667,
    }
    # Every realized value is still summed on each horizon beside it.
    assert s["realized_value"] == {"week": 1.5, "three": 5.0}
    line = season_scorecard._realized_counts(rows)
    assert line.startswith(
        "3 moves scored: realized 167% of projected, 2 of 2 in the projected direction "
        "(the 2 with their recommended horizon over)"
    )


def test_the_season_is_summed_beside_the_others_and_the_flagged_counted():
    """#144: a strategy set solved under the season weight is judged on the season; the season
    is summed through the days read; the moves projected below zero over it and the flagged
    are counted, with how many realized below zero so far; its gaps are not counted twice."""
    assert (
        season_scorecard.judged_horizon(
            {"set": "season", "value": {"horizons": {"season": {"value": 1.0}}}},
            {"source": "strategy"},
        )
        == "season"
    )

    def row(flag: bool | None, projected: float, so_far: float, gaps: int = 0) -> dict:
        r = {
            "match": {"kind": "as_recommended", "near": False},
            "judged": "week",
            "season_costly": flag,
            "projected": {
                "value": {"horizons": {"week": {"value": 1.0}, "season": {"value": projected}}}
            },
            "realized": {
                "valued": True,
                "scorer": {"own": True},
                "horizons": {
                    "week": {"value": 0.5, "complete": True, "gaps": gaps},
                    "season": {"value": so_far, "complete": False, "gaps": gaps},
                },
            },
        }
        return {**r, "group": season_scorecard.group(r)}

    rows = [
        row(True, -3.0, -1.0, gaps=2),  # flagged, below zero so far
        row(True, -2.0, 0.5),  # flagged, above so far
        row(False, -0.5, -0.2),  # below zero over the season, not below the floor's margin
        row(False, 4.0, -0.1),
        row(None, 1.0, 0.3),  # logged before the flag
    ]
    s = season_scorecard.moves_summary(rows)
    assert s["projected_value"]["season"] == pytest.approx(-0.5)
    assert s["realized_value"]["season"] == pytest.approx(-0.5)
    assert s["complete"]["season"] == 0
    assert s["season_negative"] == {"moves": 3, "below_so_far": 2}
    assert s["season_costly"] == {"checked": 4, "moves": 2, "below_so_far": 1}
    assert s["gaps"] == 2
    line = season_scorecard._realized_counts(rows)
    assert line.endswith(
        "3 projected below zero over the season, 2 of them below zero so far; "
        "2 flagged season-costly, 1 of them below zero so far"
    )
    # A week with no season projection says nothing of it.
    assert "season" not in season_scorecard._realized_counts(
        [{**r, "projected": None, "season_costly": None} for r in rows[:1]]
    )
