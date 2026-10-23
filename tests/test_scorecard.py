"""#126: the Monday scorecard, a recorded week against the decision log's projection of it.

Every record, entry and figure here is made up: four teams, nine categories, team 1 mine.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import date
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
    # log's projection of it and no realized value yet.
    [move] = card["moves"]
    assert (move["add"], move["drop"], move["day"]) == (11, 12, "2026-10-27")
    assert move["match"]["kind"] == "as_recommended" and move["match"]["near"] is True
    assert move["projected"]["set"] == "week" and move["projected"]["gain"]["week"] == 0.21
    assert move["projected"]["value"]["horizons"]["week"]["value"] == 7.25
    assert move["realized"] is None
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
    assert season_scorecard.UNSCORED in md
    # Public text: leagues by id, no team names, no per-move value.
    assert "Team" not in md and "7.25" not in md
    # A week only some leagues recorded: the others say so.
    one = client.get("/seasons/scorecard", params={"week": 1}).json()
    assert one["pooled"]["week"]["leagues"] == 0
    assert set(one["pooled"]["week"]["not_recorded"]) == {OTHER}


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
