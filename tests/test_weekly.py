"""Weekly projections (#93): games from the schedule, the startable slots, the weekly totals and
spread, and the odds of each category. Every number here is made up and computed by hand."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from pickandroll.season import Player
from pickandroll.season import weekly as wk

MON = date(2026, 10, 26)
WEEK = [MON + timedelta(n) for n in range(7)]
SLOTS = wk.starting_slots(
    ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN", "IL"]
)
NINE = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")


def schedule(games: dict[str, list[int]]) -> dict[date, frozenset[str]]:
    """``{team: [weekday index, ...]}`` as the season's schedule, every day of the week present."""
    return {d: frozenset(t for t, days in games.items() if i in days) for i, d in enumerate(WEEK)}


def rates(
    pts=10.0,
    threes=1.0,
    reb=5.0,
    ast=3.0,
    stl=1.0,
    blk=1.0,
    tov=2.0,
    fgm=4.0,
    fga=8.0,
    ftm=2.0,
    fta=2.5,
):
    return {
        "pts": pts,
        "threes": threes,
        "reb": reb,
        "ast": ast,
        "stl": stl,
        "blk": blk,
        "tov": tov,
        "fgm": fgm,
        "fga": fga,
        "ftm": ftm,
        "fta": fta,
    }


def test_starting_slots_leave_out_the_bench_and_il():
    assert SLOTS == ("PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util")


def test_weekly_totals_are_rates_times_the_games_on_the_schedule():
    sched = schedule({"AAA": [0, 2, 4], "BBB": [1, 2, 5, 6]})
    roster = [(1, Player(1, "One", "AAA", ("PG",))), (2, Player(2, "Two", "BBB", ("C",)))]
    r = {
        1: rates(pts=20, fgm=8, fga=16, ftm=4, fta=5),
        2: rates(pts=10, fgm=5, fga=9, ftm=1, fta=2),
    }
    week = wk.project_week(roster, r, WEEK, sched, SLOTS, {1: 2.0, 2: 1.0}, this_week=False)
    assert week.players[1] == wk.PlayerWeek(3, 3)
    assert week.players[2] == wk.PlayerWeek(4, 4)
    assert week.totals["pts"] == 3 * 20 + 4 * 10
    assert week.totals["fgm"] == 3 * 8 + 4 * 5 and week.totals["fga"] == 3 * 16 + 4 * 9
    fg, _ = wk.final(week, {}, "fg_pct")
    assert fg == pytest.approx(44 / 84)
    # From today on (Friday): one game for AAA, two for BBB.
    rest = wk.project_week(roster, r, WEEK[4:], sched, SLOTS, {1: 2.0, 2: 1.0}, this_week=True)
    assert rest.totals["pts"] == 20 + 2 * 10


def test_a_day_with_more_players_than_slots_starts_the_best_that_fit():
    # Five centers (values 12..8) and seven point guards (7..1), all with a game on Monday.
    sched = schedule({"AAA": [0]})
    roster = [(i, Player(i, f"C{i}", "AAA", ("C",))) for i in range(5)]
    roster += [(10 + i, Player(10 + i, f"PG{i}", "AAA", ("PG",))) for i in range(7)]
    value = {i: 12.0 - i for i in range(5)} | {10 + i: 7.0 - i for i in range(7)}
    day = wk.starters([(k, p.positions) for k, p in roster], SLOTS, value)
    # Two C slots and two Util slots take the four best centers; PG and G the two best guards;
    # SG, SF, PF and F stay empty, and the fifth center sits though he outranks the guards.
    assert set(day) == {0, 1, 2, 3, 10, 11}
    assert sorted(day[k] for k in (0, 1, 2, 3)) == ["C", "C", "Util", "Util"]
    assert sorted(day[k] for k in (10, 11)) == ["G", "PG"]
    week = wk.project_week(
        roster, {k: rates() for k, _ in roster}, WEEK, sched, SLOTS, value, False
    )
    assert sum(p.started for p in week.players.values()) == 6
    assert week.players[4] == wk.PlayerWeek(1, 0)
    assert week.totals["pts"] == 6 * 10


def test_twelve_players_with_a_game_fill_the_ten_slots():
    pos = [
        ("PG",),
        ("SG",),
        ("PG", "SG"),
        ("SF",),
        ("PF",),
        ("SF", "PF"),
        ("C",),
        ("C",),
        ("PF", "C"),
        ("SG", "SF"),
        ("PG",),
        ("C",),
    ]
    roster = [(i, Player(i, f"P{i}", "AAA", p)) for i, p in enumerate(pos)]
    value = {i: 100.0 - i for i in range(12)}
    day = wk.starters([(k, p.positions) for k, p in roster], SLOTS, value)
    assert len(day) == 10 and set(day) == set(range(10))


def test_a_starter_moves_slots_to_make_room():
    # The guard takes Util first; the center, who fits only Util, moves him to PG.
    day = wk.starters([("g", ("PG",)), ("c", ("C",))], ("Util", "PG"), {"g": 2.0, "c": 1.0})
    assert day == {"g": "PG", "c": "Util"}


def test_the_out_rule():
    sched = schedule({"AAA": [0, 2, 4]})
    days = WEEK

    def games(status, this_week, zero=False):
        return wk.standalone_week(
            Player(1, "X", "AAA", ("PG",), status=status), days, sched, this_week, zero_games=zero
        ).games

    assert games("INJ", True) == 0 and games("INJ", False) == 0
    assert games("OFS", False) == 0 and games("SUSP", False) == 0 and games("NA", False) == 0
    assert games("O", True) == 0 and games("O", False) == 3
    assert games("GTD", True) == 3 and games("GTD", True, zero=True) == 0
    for status in ("D", "Q", "P", None):
        assert games(status, True) == 3
    # A weekly export's games count overrides the rule: an O with two games plays two.
    assert (
        wk.standalone_week(Player(1, "X", "AAA", status="O"), days, sched, True, games=2).games == 2
    )


def test_an_exports_games_are_the_last_game_days():
    sched = schedule({"AAA": [0, 2, 4], "BBB": [0]})
    roster = [
        (1, Player(1, "Back", "AAA", ("C",), status="INJ")),
        (2, Player(2, "Other", "BBB", ("C",))),
    ]
    # One slot: the injured player returns for his last two games; Monday goes to the other.
    week = wk.project_week(
        roster, {1: rates(), 2: rates()}, WEEK, sched, ("C",), {1: 9.0, 2: 1.0}, True, games={1: 2}
    )
    assert week.players[1] == wk.PlayerWeek(2, 2)
    assert week.players[2] == wk.PlayerWeek(1, 1)


def test_a_mirror_roster_is_a_coin_flip_in_every_category():
    sched = schedule({"AAA": [0, 1, 3, 5]})
    roster = [(i, Player(i, f"P{i}", "AAA", ("PG", "SG"))) for i in range(3)]
    r = {i: rates(pts=10 + i) for i in range(3)}
    a = wk.project_week(roster, r, WEEK, sched, SLOTS, {i: float(i) for i in range(3)}, False)
    odds = wk.category_odds(a, a, NINE)
    assert [o.p_win for o in odds] == [0.5] * 9
    assert wk.expected_won(odds) == 4.5


def test_the_spread_and_the_odds_of_a_counting_category():
    sched = schedule({"AAA": [0, 1, 2, 3]})
    mine = wk.project_week(
        [(1, Player(1, "A", "AAA", ("C",)))], {1: rates(pts=25)}, WEEK, sched, SLOTS, {}, False
    )
    theirs = wk.project_week(
        [(2, Player(2, "B", "AAA", ("C",)))], {2: rates(pts=20)}, WEEK, sched, SLOTS, {}, False
    )
    assert mine.variance["pts"] == pytest.approx(wk.PHI["pts"] * 100)
    (o,) = wk.category_odds(mine, theirs, ["pts"], {"pts": 30.0}, {"pts": 50.0})
    assert (o.mine, o.theirs) == (130.0, 130.0) and o.p_win == 0.5
    (o,) = wk.category_odds(mine, theirs, ["pts"])
    sd = math.sqrt(wk.PHI["pts"] * 100 + wk.PHI["pts"] * 80)
    assert o.sd == pytest.approx(sd)
    assert o.p_win == pytest.approx(0.5 * (1 + math.erf(20 / sd / math.sqrt(2))))
    # Fewer turnovers win.
    (t,) = wk.category_odds(mine, theirs, ["tov"], {"tov": 0.0}, {"tov": 5.0})
    assert t.p_win > 0.5


def test_a_percentage_counts_the_week_so_far_and_its_spread_is_binomial():
    sched = schedule({"AAA": [0, 1]})
    week = wk.project_week(
        [(1, Player(1, "A", "AAA", ("C",)))],
        {1: rates(fgm=5, fga=10)},
        WEEK,
        sched,
        SLOTS,
        {},
        False,
    )
    pct, sd = wk.final(week, {"fgm": 30.0, "fga": 50.0}, "fg_pct")
    assert pct == pytest.approx(40 / 70)
    # One shooter at .500 on 20 attempts: makes vary by binomial * 20 * .25, none from attempts.
    assert sd == pytest.approx(math.sqrt(wk.BINOMIAL["fgm"] * 20 * 0.25) / 70)


def test_a_points_league_projects_fantasy_points():
    sched = schedule({"AAA": [0, 1, 2]})
    pts = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}
    week = wk.project_week(
        [(1, Player(1, "A", "AAA", ("C",)))],
        {1: rates()},
        WEEK,
        sched,
        SLOTS,
        {},
        False,
        points=pts,
    )
    per_game = 10 + 1.2 * 5 + 1.5 * 3 + 3 * 1 + 3 * 1 - 2
    assert week.totals["fpts"] == pytest.approx(3 * per_game)
    (o,) = wk.category_odds(week, week, ["fpts"], {"fpts": 10.0}, {})
    assert o.mine == pytest.approx(10 + 3 * per_game) and o.p_win > 0.5
    values = wk.per_game_values({1: rates(), 2: rates(pts=30)}, ["fpts"], pts)
    assert values[2] - values[1] == pytest.approx(20)


def test_per_game_values_rank_the_better_player_first():
    r = {
        1: rates(pts=25, reb=10, fgm=9, fga=16),
        2: rates(),
        3: rates(pts=5, reb=2, tov=4, fgm=2, fga=7),
    }
    v = wk.per_game_values(r, NINE)
    assert v[1] > v[2] > v[3]


def test_player_totals_carry_the_percentages():
    t = wk.player_totals(wk.PlayerWeek(3, 2), rates(fgm=5, fga=10), None)
    assert t["fgm"] == 10 and t["fga"] == 20 and t["fg_pct"] == 0.5
    assert wk.player_totals(wk.PlayerWeek(3, 2), None) is None
