"""#126, part 2: a move's realized value, from the box scores of the games its two players played.

Every game, line and scorer here is made up: a points scorer for plain arithmetic, and a
categories scorer checked against its own sum of games.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from pickandroll.season import realized as rz
from pickandroll.season import weekly as wk
from pickandroll.season.calendar import Calendar, Week

WEEKS = tuple(
    Week(
        n, date(2026, 10, 19) + timedelta(7 * (n - 1)), date(2026, 10, 25) + timedelta(7 * (n - 1))
    )
    for n in range(1, 7)
)
CALENDAR = Calendar(WEEKS)
WEEK2 = WEEKS[1]
#: Tuesday of week 2, 13:00 UTC (9:00 US Eastern).
AT = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
POINTS = {"points": {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}}
TODAY = date(2026, 11, 2)


def line(pts: float, reb: float = 0.0, **more: float) -> dict[str, float]:
    return {"pts": pts, "reb": reb, **more}


def game(day: date, hour: int, teams: tuple[str, ...], **players: Any) -> dict[str, Any]:
    """A game on ``day`` starting at ``hour`` UTC; ``players`` by ESPN id: (team, line)."""
    start = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
    return {
        "id": f"{day:%m%d}{hour}",
        "start": start.isoformat().replace("+00:00", "Z"),
        "teams": list(teams),
        "players": {e: {"name": e, "team": t, "line": ln} for e, (t, ln) in players.items()},
    }


def days(*games: dict[str, Any], also: tuple[date, ...] = ()) -> dict[date, list[dict[str, Any]]]:
    out: dict[date, list[dict[str, Any]]] = {d: [] for d in also}
    for g in games:
        out.setdefault(datetime.fromisoformat(g["start"]).date(), []).append(g)
    return out


ADD = rz.Side(11, "AAA", "e11", "team")
DROP = rz.Side(12, "BBB", "e12", "team")


def week_days(first: date, last: date) -> tuple[date, ...]:
    return tuple(first + timedelta(n) for n in range((last - first).days + 1))


def test_a_moves_spans_are_its_week_from_its_day_and_the_three_weeks_after():
    assert rz.spans(WEEK2, date(2026, 10, 27), CALENDAR) == {
        "week": (date(2026, 10, 27), date(2026, 11, 1)),
        "three": (date(2026, 11, 2), date(2026, 11, 22)),
    }
    # Fewer at the season's end, none after it; seven-day weeks without a calendar.
    assert rz.spans(WEEKS[4], date(2026, 11, 20), CALENDAR)["three"] == (
        date(2026, 11, 23),
        date(2026, 11, 29),
    )
    assert "three" not in rz.spans(WEEKS[5], date(2026, 11, 27), CALENDAR)
    assert rz.spans(WEEK2, date(2026, 10, 27))["three"] == (date(2026, 11, 2), date(2026, 11, 22))


def test_the_add_s_games_from_the_move_less_the_drop_s_valued_with_the_scorer():
    mon, tue, thu, sat = (date(2026, 10, 26) + timedelta(n) for n in (0, 1, 3, 5))
    played = days(
        # Monday's game is before the move: neither side's.
        game(mon, 23, ("AAA", "CCC"), e11=("AAA", line(30.0)), e12=("BBB", line(40.0))),
        # Tuesday's after it: both count, the drop's game as the add's.
        game(tue, 23, ("AAA", "CCC"), e11=("AAA", line(10.0, 5.0))),
        game(tue, 23, ("BBB", "DDD"), e12=("BBB", line(8.0))),
        # A game he sat: no game for him.
        game(thu, 23, ("AAA", "DDD"), e11=("AAA", None)),
        game(sat, 23, ("AAA", "BBB"), e11=("AAA", line(20.0)), e12=("BBB", line(4.0, 1.0))),
        also=week_days(mon, date(2026, 11, 1)),
    )
    out = rz.realized(AT, AT.date(), WEEK2, ADD, DROP, POINTS, played, TODAY, CALENDAR)
    assert out["valued"] is True and out["reason"] is None
    week = out["horizons"]["week"]
    assert (week["from"], week["to"], week["through"]) == ("2026-10-27", "2026-11-01", "2026-11-01")
    assert week["complete"] is True and week["missing"] == []
    assert (week["add_games"], week["drop_games"]) == (2, 2)
    # 10 + 5 x 1.2 + 20 for the add, 8 + 4 + 1.2 for the drop.
    assert week["add"] == pytest.approx(36.0) and week["drop"] == pytest.approx(13.2)
    assert week["value"] == pytest.approx(22.8) and week["gaps"] == 0
    # The three weeks after: nothing read yet (today is their first day).
    three = out["horizons"]["three"]
    assert three["through"] is None and three["value"] is None and three["missing"] == []
    assert out["add"] == {"yahoo": 11, "espn": "e11", "by": "team"}


def test_a_categories_scorer_values_the_games_as_their_sum():
    scorer = {
        "cats": {
            "fg_pct": {"p": 0.47, "sd": 2.1},
            "pts": {"p": 0.0, "sd": 6.5},
            "tov": {"p": 0.0, "sd": 1.3},
        }
    }
    a = line(12.0, fgm=5.0, fga=9.0, tov=2.0)
    b = line(18.0, fgm=7.0, fga=16.0, tov=1.0)
    tue, wed = date(2026, 10, 27), date(2026, 10, 28)
    played = days(
        game(tue, 23, ("AAA",), e11=("AAA", a)),
        game(wed, 23, ("AAA",), e11=("AAA", b)),
        also=week_days(tue, date(2026, 11, 1)),
    )
    out = rz.realized(AT, tue, WEEK2, ADD, None, scorer, played, TODAY, CALENDAR)
    week = out["horizons"]["week"]
    assert week["add_games"] == 2 and week["drop_games"] is None and week["drop"] is None
    # To the four decimals a value is kept to.
    sum_of_games = wk.net_value(scorer, a) + wk.net_value(scorer, b)
    assert week["value"] == pytest.approx(sum_of_games, abs=1e-4)


def test_a_span_counts_through_its_last_day_read_without_a_gap():
    tue, thu = date(2026, 10, 27), date(2026, 10, 29)
    played = days(
        game(tue, 23, ("AAA",), e11=("AAA", line(10.0))),
        game(thu, 23, ("AAA",), e11=("AAA", line(50.0))),
    )
    out = rz.realized(AT, tue, WEEK2, ADD, None, POINTS, played, date(2026, 10, 30), CALENDAR)
    week = out["horizons"]["week"]
    # Wednesday is not read: Thursday's game waits for it, and the span is not complete.
    assert week["through"] == "2026-10-27" and week["value"] == pytest.approx(10.0)
    assert week["missing"] == ["2026-10-28"] and week["complete"] is False
    assert out["valued"] is True


def test_a_player_not_matched_is_a_gap_of_his_teams_games_never_a_zero():
    tue, wed = date(2026, 10, 27), date(2026, 10, 28)
    played = days(
        game(tue, 23, ("BBB", "CCC"), e11=("AAA", line(10.0))),
        game(wed, 23, ("BBB", "DDD")),
        game(wed, 23, ("AAA", "CCC")),
        also=(date(2026, 10, 29),),
    )
    lost = rz.Side(12, "BBB")
    out = rz.realized(AT, tue, WEEK2, ADD, lost, POINTS, played, date(2026, 10, 30), CALENDAR)
    week = out["horizons"]["week"]
    assert out["valued"] is False and out["reason"] == rz.UNMATCHED
    assert week["gaps"] == 2 and week["value"] is None and week["drop_games"] is None
    assert week["add"] == pytest.approx(10.0)
    assert out["drop"] == {"yahoo": 12, "espn": None, "by": None}


def test_a_player_whose_team_has_not_played_has_no_game_not_a_gap():
    tue = date(2026, 10, 27)
    played = days(
        game(tue, 23, ("AAA", "CCC"), e11=("AAA", line(10.0))), also=(tue + timedelta(1),)
    )
    idle = rz.Side(12, "BBB")
    out = rz.realized(AT, tue, WEEK2, ADD, idle, POINTS, played, date(2026, 10, 29), CALENDAR)
    week = out["horizons"]["week"]
    assert out["valued"] is True and week["gaps"] == 0
    assert (week["drop_games"], week["drop"], week["value"]) == (0, 0.0, 10.0)


def test_a_move_has_no_realized_value_without_a_time_a_scorer_or_a_day_read():
    tue = date(2026, 10, 27)
    assert rz.realized(None, None, WEEK2, ADD, DROP, POINTS, {}, TODAY)["reason"] == rz.NO_TIME
    assert rz.realized(AT, tue, WEEK2, ADD, DROP, None, {}, TODAY)["reason"] == rz.NO_SCORER
    out = rz.realized(AT, tue, WEEK2, ADD, DROP, POINTS, {}, tue)
    assert out["reason"] == rz.NOT_READ and out["horizons"]["week"]["missing"] == []


def test_a_stream_s_moves_add_up_to_what_the_spot_made():
    """Add A for B on Tuesday, then C for A on Thursday: the two moves' values sum to C's games
    and A's before Thursday, less B's from Tuesday."""
    tue, wed, thu, fri = (date(2026, 10, 27) + timedelta(n) for n in range(4))
    a, b, c = rz.Side(1, "AAA", "a"), rz.Side(2, "BBB", "b"), rz.Side(3, "CCC", "c")
    played = days(
        *(
            game(d, 23, ("AAA", "BBB", "CCC"), a=("AAA", line(10.0)), b=("BBB", line(7.0)))
            for d in (tue, wed, thu, fri)
        ),
        game(thu, 23, ("CCC",), c=("CCC", line(15.0))),
        game(fri, 23, ("CCC",), c=("CCC", line(15.0))),
        also=week_days(tue, date(2026, 11, 1)),
    )
    later = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    first = rz.realized(AT, tue, WEEK2, a, b, POINTS, played, TODAY, CALENDAR)
    second = rz.realized(later, thu, WEEK2, c, a, POINTS, played, TODAY, CALENDAR)
    total = first["horizons"]["week"]["value"] + second["horizons"]["week"]["value"]
    assert total == pytest.approx(10.0 * 2 + 15.0 * 2 - 7.0 * 4)
