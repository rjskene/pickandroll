"""The Progress view (#129): the knob file and the Monday notes as read, the A/B halves of a
change, the sentences, and ``GET /progress`` on a fixture season. Every value is made up."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, season_moves
from pickandroll.season import moves as mv
from pickandroll.season import progress as pg
from pickandroll.season import realized as rz
from pickandroll.season import weekly as wk
from pickandroll.season.calendar import Calendar, Week
from tests.test_record import write_league
from tests.test_scorecard import (
    OTHER,
    PRIVATE,
    PUBLIC,
    SCORER,
    box_game,
    entry,
    logged,
    moved,
    put_box,
    put_entries,
    put_week,
    record,
    write,
)

WEEKS = [
    Week(1, date(2026, 10, 19), date(2026, 10, 25)),
    Week(2, date(2026, 10, 26), date(2026, 11, 1)),
    Week(3, date(2026, 11, 2), date(2026, 11, 8)),
]


# --------------------------------------------------------------------------- by category
def test_a_lines_value_by_category_sums_to_its_value():
    cats = {"cats": {"pts": {"p": 0.0, "sd": 4.0}, "fg_pct": {"p": 0.5, "sd": 2.0}}}
    line = {"pts": 20.0, "fgm": 8.0, "fga": 14.0, "reb": 9.0}
    by_cat = wk.net_values(cats, line)
    assert by_cat == {"pts": 5.0, "fg_pct": (8.0 - 7.0) / 2.0}
    assert sum(by_cat.values()) == wk.net_value(cats, line)
    points = {"points": {"pts": 1.0, "reb": 1.2}}
    assert wk.net_values(points, line) == {"pts": 20.0, "reb": pytest.approx(10.8)}
    assert wk.net_value(points, line) == pytest.approx(30.8)


def test_a_realized_span_splits_its_value_by_category():
    games = {
        date(2026, 10, 27): [
            {
                "start": "2026-10-27T23:00:00Z",
                "teams": ["AAA", "BBB"],
                "players": {
                    "e11": {"line": {"pts": 20.0, "reb": 4.0}},
                    "e12": {"line": {"pts": 8.0, "reb": 10.0}},
                },
            }
        ]
    }
    sides = {"add": rz.Side(11, "AAA", "e11", "id"), "drop": rz.Side(12, "BBB", "e12", "id")}
    at = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
    first = last = date(2026, 10, 27)
    out = rz.span(first, last, at, games, sides, SCORER, date(2026, 10, 28))
    assert out["value"] == 6.0 and out["cats"] == {"pts": 12.0, "reb": -6.0}
    # A side not matched: no value, so no split either.
    gone = {**sides, "drop": rz.Side(12, "BBB")}
    assert rz.span(first, last, at, games, gone, SCORER, date(2026, 10, 28))["cats"] is None


# --------------------------------------------------------------------------- the knob file
def test_the_knob_file_is_read_leniently_and_its_problems_named():
    raw = {
        "in_force": {"blend": 0.5, "horizon_weight": "natural", "colour": "red"},
        "leagues": {"100001": {"blend": 0.6}, "100004": "nope"},
        "frozen": {"100004": ["horizon_weight", "colour"]},
        "changes": [
            {
                "id": "K2",
                "monday": "2026-11-09",
                "knob": "stash_threshold",
                "from": 0.3,
                "to": 0.2,
                "leagues": [100004],
                "source": "master",
                "verdict": "maybe",
            },
            {
                "id": "K1",
                "monday": "2026-10-26",
                "knob": "horizon_weight",
                "from": "even",
                "to": "natural",
            },
            {"id": "K3", "monday": "next week", "knob": "blend"},
            {"id": "K4", "monday": "2026-11-16", "knob": "speed"},
            "not a change",
        ],
    }
    knobs, problems = pg.knob_file(raw)
    assert knobs["in_force"] == {"blend": 0.5, "horizon_weight": "natural"}
    assert knobs["leagues"] == {"100001": {"blend": 0.6}, "100004": {}}
    assert knobs["frozen"] == {"100004": ["horizon_weight"]}
    # Oldest first; the two unreadable changes left out, a bad verdict read as pending.
    assert [c["id"] for c in knobs["changes"]] == ["K1", "K2"]
    k2 = knobs["changes"][1]
    assert k2["leagues"] == ["100004"] and k2["source"] == "master" and k2["verdict"] is None
    assert knobs["changes"][0]["source"] is None and knobs["changes"][0]["leagues"] == []
    assert problems == [
        "in_force: colour is not a knob",
        "league 100004 is not an object",
        "frozen in league 100004: colour not knobs",
        "K2: verdict maybe is neither kept nor reverted",
        "K3: its monday is not a date",
        "K4: speed is not a knob",
        "change 5 is not an object",
    ]
    assert pg.knob_file(None) == ({"in_force": {}, "leagues": {}, "frozen": {}, "changes": []}, [])
    assert pg.knob_file([1, 2])[1] == ["the knob file is not an object"]


def test_a_knob_under_its_minimum_is_named_and_left_out_so_the_default_stays():
    raw = {
        "in_force": {"protection_floor": -0.1, "daily_cap": 2, "blend": 0.1},
        "leagues": {"100001": {"protection_floor": "low", "daily_cap": 0}},
        "changes": [
            {
                "id": "K1",
                "monday": "2026-10-26",
                "knob": "protection_floor",
                "from": 0.0,
                "to": -0.2,
            },
            {
                "id": "K2",
                "monday": "2026-11-02",
                "knob": "protection_floor",
                "from": 0.0,
                "to": 0.3,
            },
            {
                "id": "K3",
                "monday": "2026-11-09",
                "knob": "protection_floor",
                "from": 0.3,
                "to": 0.0,
            },
        ],
    }
    knobs, problems = pg.knob_file(raw)
    # The floor below its minimum is not in force: the default (0.0) stays.
    assert knobs["in_force"] == {"daily_cap": 2}
    assert knobs["leagues"] == {"100001": {}}
    # Raised and brought back down to the minimum, both pass; below it, left out.
    assert [c["id"] for c in knobs["changes"]] == ["K2", "K3"]
    assert problems == [
        "in_force: protection_floor -0.1 is below its minimum 0.0",
        "in_force: blend 0.1 is below its minimum 0.25",
        "league 100001: protection_floor 'low' is not a number",
        "league 100001: daily_cap 0 is below its minimum 1",
        "K1: protection_floor -0.2 is below its minimum 0.0",
    ]
    # At the minimum and above, and an unset value, pass; a knob without a minimum takes anything.
    assert pg.below_minimum("protection_floor", 0.0) is None
    assert pg.below_minimum("protection_floor", 0.25) is None
    assert pg.below_minimum("protection_floor", None) is None
    assert pg.below_minimum("protection_floor", True) == "protection_floor True is not a number"
    assert pg.below_minimum("horizon_weight", "natural") is None


def test_every_knob_with_a_lower_bound_has_its_minimum_and_the_floor_is_the_default():
    assert set(pg.KNOB_MINIMUMS) <= set(pg.KNOBS)
    # The bounds of docs/AUTOPILOT.md section 6 with a low end: the floor, the blend, the cap.
    assert pg.KNOB_MINIMUMS == {"protection_floor": 0.0, "blend": 0.25, "daily_cap": 1}
    assert pg.KNOB_MINIMUMS["protection_floor"] == season_moves.PROTECTION_FLOOR
    assert mv.MoveProblem.__dataclass_fields__["floor"].default == season_moves.PROTECTION_FLOOR


def test_a_monday_note_is_read_into_its_four_sections():
    lines = [
        "posted: 2026-11-09T06:04:00-06:00",
        "## What is working",
        "The moves track their projection.",
        "",
        "## What is not working",
        "Two leagues lose lineup days.",
        "## Decision",
        "One change: K1.",
        "## Action items",
        "1. Judge K1 on weeks 3 and 4",
        "   before any other change.",
        "2. Audit the returns.",
        "## Aside",
        "nothing",
    ]
    text = "\n".join(lines)
    note, problems = pg.note(text, "2026-11-09")
    assert note == {
        "monday": "2026-11-09",
        "posted": "2026-11-09T06:04:00-06:00",
        "working": "The moves track their projection.",
        "not_working": "Two leagues lose lineup days.",
        "decision": "One change: K1.",
        "actions": ["Judge K1 on weeks 3 and 4 before any other change.", "Audit the returns."],
    }
    assert problems == ["note 2026-11-09: Aside is not a section"]
    bare, problems = pg.note("## Decision\nNothing moves.\n## Action items\n- Wait\n- See", "x")
    assert bare["decision"] == "Nothing moves." and bare["actions"] == ["Wait", "See"]
    assert bare["working"] is None and bare["posted"] is None
    assert problems == ["note x: no section what is working, what is not"]


# --------------------------------------------------------------------------- A/B
def row(week: int, expected: float | None, won: float, rank: int, made: int = 0, **compared):
    return {
        "week": week,
        "scoring": "categories",
        "expected": expected,
        "won": won,
        "brier": None if expected is None else round((expected - won) ** 2, 4),
        "rank": rank,
        "moves": {"made": made, "compared": compared or None},
    }


def test_a_changes_halves_are_compared_over_the_weeks_it_is_judged_on():
    rows = {
        "1": [row(1, 0.5, 1.0, 5), row(2, 0.6, 1.0, 3, 2, moves=1, projected=2.0, realized=1.5)],
        "2": [row(1, 0.5, 0.0, 4), row(2, 0.5, 0.0, 6, 1)],
        "3": [row(1, None, 1.0, 2), row(2, 0.7, 1.0, 1)],
    }
    change = {"leagues": ["1"]}
    out = pg.ab(change, 2, rows, 2)
    assert out["window"] == [2, 2]
    a, b = out["a"], out["b"]
    assert a["leagues"] == ["1"] and b["leagues"] == ["2", "3"]
    assert a["wins_above"] == 0.4 and b["wins_above"] == pytest.approx((-0.5 + 0.3) / 2)
    assert a["standing_climbed"] == 2 and b["standing_climbed"] == -2 + 1
    assert a["moves_a_week"] == 2.0 and b["moves_a_week"] == 0.5
    assert a["moves"] == {
        "categories": {"moves": 1, "projected": 2.0, "realized": 1.5, "share": 0.75}
    }
    assert a["brier"] == 0.16 and b["brier"] == pytest.approx((0.25 + 0.09) / 2)
    # Each week's wins above expected a league, A against B, from two weeks before.
    assert out["series"] == [
        {"week": 1, "a": 0.5, "b": -0.5},
        {"week": 2, "a": 0.4, "b": pytest.approx(-0.1)},
    ]
    assert pg.ab(change, None, rows, 2) is None
    # A change starting after the last week recorded has no window yet.
    assert pg.ab(change, 3, rows, 2)["window"] is None


# --------------------------------------------------------------------------- the sentences
def test_the_sentences_follow_their_thresholds():
    pooled = {"weeks": 10, "won": 5.0, "expected": 5.6}
    leagues = [
        {"league": "1", "weeks": 5, "won": 4.0, "expected": 2.9},
        {"league": "2", "weeks": 5, "won": 1.0, "expected": 2.7},
        {"league": "3", "weeks": 5, "won": 2.0, "expected": 2.5},
    ]
    calibration = {
        "weeks": 10,
        "brier": 0.2,
        "buckets": [
            {"from": 0.6, "to": 0.8, "count": 40, "odds": 0.7, "won": 0.62},
            {"from": 0.0, "to": 0.2, "count": 31, "odds": 0.1, "won": 0.03},
            {"from": 0.8, "to": 1.0, "count": 12, "odds": 0.9, "won": 0.5},
            {"from": 0.4, "to": 0.6, "count": 90, "odds": 0.5, "won": 0.52},
        ],
    }
    moves = {
        "categories": {"moves": 8, "projected": 2.0, "realized": 1.7, "same_way": 6, "share": 0.85},
        "points": {"moves": 2, "projected": 20.0, "realized": 19.0, "same_way": 2, "share": 0.95},
    }
    kept = {
        "id": "K1",
        "knob": "horizon_weight",
        "from": "even",
        "to": "natural",
        "verdict": "kept",
        "week": 3,
        "ab": {"a": {"wins_above": 0.7}, "b": {"wins_above": -0.5}},
    }
    pending = {**kept, "id": "K2", "verdict": None, "week": 6, "ab": None}
    out = pg.sentences(pooled, leagues, calibration, moves, [kept, pending])
    texts = [(s["topic"], s["scope"], s["tone"], s["text"]) for s in out]
    assert texts == [
        (
            "wins",
            "pooled",
            "neutral",
            "5 won against 5.6 expected over 10 projected matchups: actual tracks expected within a game.",
        ),
        (
            "league",
            "1",
            "good",
            "League 1: 4 won against 2.9 expected over 5 projected weeks: 1.1 wins ahead of expectation.",
        ),
        (
            "league",
            "2",
            "bad",
            "League 2: 1 won against 2.7 expected over 5 projected weeks: 1.7 wins behind expectation.",
        ),
        (
            "moves",
            "pooled",
            "bad",
            "Judged on the horizon each was recommended for, the 8 scored moves whose horizon is over (category value) realized 85% of their projection: they trail it by 15%; 6 of 8 in the projected direction.",
        ),
        (
            "moves",
            "pooled",
            "neutral",
            "Judged on the horizon each was recommended for, the 2 scored moves whose horizon is over (fantasy points) realized 95% of their projection, tracking it; 2 of 2 in the projected direction.",
        ),
        (
            "odds",
            "pooled",
            "neutral",
            "The matchup odds' Brier score is 0.20 over 10 matchups (0.25 is a coin flip, lower is better).",
        ),
        (
            "odds",
            "pooled",
            "bad",
            "The category odds of 60% to 80% are over-confident: they said 70% and 62% came in, over 40 categories.",
        ),
        (
            "odds",
            "pooled",
            "bad",
            "The category odds of 0% to 20% are timid: they said 10% and 3% came in, over 31 categories.",
        ),
        (
            "knobs",
            "pooled",
            "good",
            "K1 (horizon_weight even → natural) was kept: the leagues that took it ran +1.2 wins a league against those that kept the setting over its weeks.",
        ),
        (
            "knobs",
            "pooled",
            "neutral",
            "K2 (horizon_weight even → natural) is pending: it is judged after week 7.",
        ),
    ]


# --------------------------------------------------------------------------- the route
def put_calendar(data_dir: Path) -> None:
    write(
        data_dir / "leagues" / "_shared" / "season" / "calendar.json",
        Calendar(WEEKS, False).to_dict(),
    )


@pytest.fixture
def client(tmp_path):
    """Two public leagues and the private one over two recorded weeks. In the first, a move of
    week 2 made as recommended by Tuesday's solve; the second only projected; the private one
    recorded with no solve. One knob change, taken by the first league from week 2, and one
    note on the Monday of week 2."""
    for league, extra in ((PUBLIC, {}), (OTHER, {}), (PRIVATE, {"public": False})):
        write_league(tmp_path, league, **extra)
    put_calendar(tmp_path)
    rows = [
        moved("add", 11, "AAA", "Oct 27, 9:00 am", 1),
        moved("drop", 12, "BBB", "Oct 27, 9:00 am", 1),
    ]
    put_week(tmp_path, PUBLIC, record(1, "L"))
    lineup = {"lost": 2, "days_read": 5, "days": 7, "unmatched": 0}
    put_week(tmp_path, PUBLIC, {**record(2), "transactions": rows, "lineup": lineup})
    monday = entry("2026-10-26T12:00:00+00:00", "2026-10-26", 0.7)
    move = logged(11, 12)
    tuesday = {
        **entry("2026-10-27T12:30:00+00:00", "2026-10-27", 0.8, moves=(move,)),
        "scorer": SCORER,
        "knobs": {"system": "bbm", "blend": 0.5},
    }
    tuesday["sets"][0]["week"]["after"] = {**tuesday["sets"][0]["week"]["before"], "matchup": 0.85}
    put_entries(tmp_path, PUBLIC, "2026-10-26", [monday])
    put_entries(tmp_path, PUBLIC, "2026-10-27", [tuesday])
    put_week(tmp_path, OTHER, record(1))
    put_week(tmp_path, OTHER, {**record(2, "L"), "lineup": {**lineup, "lost": 1, "days_read": 7}})
    put_entries(
        tmp_path, OTHER, "2026-10-26", [entry("2026-10-26T12:00:00+00:00", "2026-10-26", 0.4)]
    )
    put_week(tmp_path, PRIVATE, {**record(2, "T"), "lineup": {**lineup, "lost": 4, "days_read": 7}})
    games = [
        box_game("2026-10-27", 23, ["AAA", "BBB"], e11=20.0, e12=8.0),
        box_game("2026-10-29", 23, ["AAA", "CCC"], e11=10.0),
    ]
    put_box(tmp_path, games, date(2026, 10, 26), date(2026, 11, 1))
    knobs = {
        "in_force": {"system": "bbm", "blend": 0.5},
        "changes": [
            {
                "id": "K1",
                "monday": "2026-10-26",
                "knob": "blend",
                "from": 0.5,
                "to": 0.6,
                "leagues": [PUBLIC],
                "source": "master",
                "reason": "made up",
            }
        ],
    }
    write(tmp_path / "autopilot" / "knobs.json", knobs)
    note = "## What is working\nIt runs.\n## What is not\nNothing yet.\n## Decision\nK1.\n## Action items\n1. Judge K1.\n"
    (tmp_path / "autopilot" / "notes").mkdir(parents=True)
    (tmp_path / "autopilot" / "notes" / "2026-10-26.md").write_text(note)
    (tmp_path / "autopilot" / "notes" / "draft.md").write_text("## Decision\n")
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: None)
    app.state.seasons.clock = lambda: datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    with TestClient(app) as c:
        c.data_dir = tmp_path  # type: ignore[attr-defined]
        yield c


def test_the_season_check_says_how_many_were_flagged_and_how_many_went_below_zero():
    """#144: by unit, in the moves topic, after the moves' own sentence."""
    season = {
        "categories": {"checked": 12, "moves": 2, "below_so_far": 1},
        "points": {"checked": 3, "moves": 0, "below_so_far": 0},
        "none": {"checked": 0, "moves": 0, "below_so_far": 0},
    }
    moves = {"categories": {"moves": 1, "projected": 1.0, "realized": 1.0, "same_way": 1}}
    out = pg.sentences(
        None, [], None, {**moves, "categories": {**moves["categories"], "share": 1.0}}, [], season
    )
    texts = [(s["topic"], s["tone"], s["text"]) for s in out]
    assert texts[1:] == [
        (
            "moves",
            "bad",
            (
                "2 of the 12 moves checked against the season (category value) were flagged "
                "season-costly: projected positive on the horizon recommended, below zero over the "
                "season; 1 of them has realized below zero so far."
            ),
        ),
        (
            "moves",
            "good",
            (
                "None of the 3 moves checked against the season (fantasy points) was flagged "
                "season-costly."
            ),
        ),
    ]
    one = pg.season_sentence("pooled", "points", {"checked": 1, "moves": 1, "below_so_far": 0})
    assert one["tone"] == "neutral"
    assert one["text"].startswith(
        "1 of the 1 move checked against the season (fantasy points) was flagged"
    )
    assert one["text"].endswith("0 of them have realized below zero so far.")


def test_progress_gives_the_season_by_week_pooled_with_the_moves_knobs_and_notes(client):
    r = client.get("/progress")
    assert r.status_code == 200, r.text
    out = r.json()
    # The calendar's weeks to this one (week 3), the last recorded week 2.
    assert [w["week"] for w in out["weeks"]] == [1, 2, 3]
    assert (out["week"], out["last_recorded"]) == (3, 2)
    leagues = {lg["league"]: lg for lg in out["leagues"]}
    first = leagues[PUBLIC]["weeks"]
    assert first[0]["expected"] is None and first[0]["won"] == 0.0
    week2 = first[1]
    assert (week2["expected"], week2["won"], week2["brier"]) == (0.7, 1.0, 0.09)
    assert week2["moves"]["made"] == 1
    # The games lost to the lineup, with the days read (#149); none read before the count.
    assert (week2["lineup_lost"], week2["lineup_days_read"], week2["lineup_days"]) == (2, 5, 7)
    assert first[0]["lineup_lost"] is None and first[0]["lineup_days_read"] == 0
    assert week2["cum"]["lineup"] == {"lost": 2, "days_read": 5, "days": 7}
    assert week2["moves"]["compared"]["moves"] == 1
    assert week2["cum"]["weeks"] == 1 and week2["cum"]["won"] == 1.0
    assert week2["cum"]["won_all"] == 1.0 and week2["cum"]["expected"] == 0.7
    # The private league is shown, never pooled.
    assert leagues[PRIVATE]["public"] is False
    pooled = {p["week"]: p for p in out["pooled"]["weeks"]}
    assert pooled[2]["leagues"] == 2 and pooled[2]["record"] == "1-1-0"
    assert (pooled[2]["expected"], pooled[2]["won"]) == (1.1, 1.0)
    assert pooled[2]["brier"] == pytest.approx((0.09 + 0.16) / 2)
    assert pooled[2]["cum"]["moves"]["categories"]["compared"]["moves"] == 1
    # Pooled over the public leagues only: the private league's four are not in.
    assert pooled[2]["lineup"] == {"lost": 3, "days_read": 12, "days": 14}
    assert pooled[1]["lineup"] == {"lost": None, "days_read": 0, "days": 0}
    assert pooled[2]["cum"]["lineup"] == {"lost": 3, "days_read": 12, "days": 14}
    assert out["pooled"]["calibration"]["weeks"] == 2
    # The move, with its names, the knobs at its solve, its odds and its value by category.
    (move,) = out["moves"]
    assert (move["league"], move["week"], move["group"]) == (PUBLIC, 2, "scored")
    assert move["names"] == {"add": "Player 11", "drop": "Player 12"}
    assert move["knobs"] == {"system": "bbm", "blend": 0.5}
    # Made as the week's set recommended it: judged on its week (#143).
    assert move["judged"] == "week"
    assert move["projected"]["odds"]["before"]["matchup"] == 0.8
    assert move["projected"]["odds"]["after"]["matchup"] == 0.85
    week = move["realized"]["horizons"]["week"]
    assert week["value"] == 22.0 and week["cats"] == {"pts": 22.0, "reb": 0.0}
    # The change on its week, league 1 its A half and the other public league its B half.
    (change,) = out["knobs"]["changes"]
    assert (change["id"], change["week"], change["source"]) == ("K1", 2, "master")
    assert change["ab"]["window"] == [2, 2]
    assert change["ab"]["a"]["leagues"] == [PUBLIC] and change["ab"]["b"]["leagues"] == [OTHER]
    assert change["ab"]["a"]["wins_above"] == pytest.approx(0.3)
    assert change["ab"]["b"]["wins_above"] == pytest.approx(-0.4)
    # The note under its week, its action items on top; the draft not named for a date.
    (note,) = out["notes"]
    assert (note["monday"], note["week"], note["scored_week"]) == ("2026-10-26", 2, 1)
    assert out["action_items"] == {"monday": "2026-10-26", "items": ["Judge K1."]}
    assert out["problems"] == ["notes/draft.md is not named for a date"]
    topics = [s["topic"] for s in out["sentences"]]
    assert "wins" in topics and "knobs" in topics
    assert out["sources"]["moves"]["as_recommended"] == 1 and out["sources"]["notes"] == 1


def test_progress_reads_nothing_into_an_empty_season(tmp_path):
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: None)
    with TestClient(app) as c:
        out = c.get("/progress").json()
    assert out["leagues"] == [] and out["moves"] == [] and out["notes"] == []
    assert out["knobs"]["changes"] == [] and out["action_items"] is None
    assert out["pooled"]["to_date"] is None and out["sentences"] == []


def test_a_knob_file_that_is_not_json_is_a_problem_not_a_failure(client):
    (client.data_dir / "autopilot" / "knobs.json").write_text("{not json")
    out = client.get("/progress").json()
    assert out["knobs"]["changes"] == []
    assert any(p.startswith("knobs.json is not JSON") for p in out["problems"])


def test_progress_writes_nothing(client):
    before = sorted(p for p in Path(client.data_dir).rglob("*") if p.is_file())
    stamps = {p: p.stat().st_mtime_ns for p in before}
    client.get("/progress")
    after = sorted(p for p in Path(client.data_dir).rglob("*") if p.is_file())
    # The box scores' id map is the scorecard's own cache; nothing else is written.
    new = [p for p in after if p not in stamps and p.name != "ids.json"]
    changed = [p for p in before if p.stat().st_mtime_ns != stamps[p] and p.name != "ids.json"]
    assert new == [] and changed == []


def test_progress_carries_no_team_or_league_name(client):
    text = json.dumps(client.get("/progress").json())
    assert "Team " not in text and '"name"' not in text
