"""Later weeks on a legal roster, with return dates for every team (#485).

A week after this one plays each team on its active spots: each day the most valuable players
who can play that day hold them, a held player only from his return date (ESPN's), the least
valuable giving his spot up. This week is the out rule's, as before. Every league here is made
up; the outcomes are set by construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from pickandroll.season import Player
from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk

MON = date(2026, 11, 30)
THIS = tuple(MON - timedelta(7) + timedelta(n) for n in range(7))
NEXT = tuple(MON + timedelta(n) for n in range(7))
SLOTS = ("PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util")
SPOTS = 13
#: Every team plays every day of both weeks.
SCHEDULE = {d: frozenset({"AAA"}) for d in (*THIS, *NEXT)}


def line(level: float) -> dict[str, float]:
    return {
        "pts": 10 * level,
        "threes": level,
        "reb": 5 * level,
        "ast": 3 * level,
        "stl": level,
        "blk": level,
        "tov": 2.0,
        "fgm": 4.0,
        "fga": 8.0,
        "ftm": 2.0,
        "fta": 2.5,
    }


def roster(n: int, out: dict[int, str] | None = None) -> list[tuple[int, Player]]:
    """``n`` players worth ``n`` down to 1 (key 1 the best), each a Util; ``out`` their status."""
    out = out or {}
    return [
        (k, Player(k, f"P{k}", "AAA", ("PG", "SF", "C"), status=out.get(k)))
        for k in range(1, n + 1)
    ]


def value(members) -> dict[int, float]:
    return {k: float(100 - k) for k, _ in members}


def week(members, days, this_week, **kw) -> wk.TeamWeek:
    rates = {k: line(1.0) for k, _ in members}
    return wk.project_week(members, rates, days, SCHEDULE, SLOTS, value(members), this_week, **kw)


def playing(members, days, this_week, **kw) -> dict[int, list[date]]:
    return wk.playing_days(
        members, days, SCHEDULE, this_week, value=value(members), **{"spots": None, **kw}
    )


def per_day(days_of: dict[int, list[date]], days) -> list[int]:
    return [sum(1 for played in days_of.values() if d in played) for d in days]


def test_an_opponent_of_sixteen_with_three_o_stars_plays_at_most_its_active_spots():
    # Sixteen players, the three best listed O with no return date: back next Monday.
    members = roster(16, {1: "O", 2: "O", 3: "O"})
    capped = playing(members, NEXT, False, spots=SPOTS)
    assert per_day(capped, NEXT) == [SPOTS] * 7
    # The stars play; the three least valuable give up their spots.
    assert all(capped[k] == list(NEXT) for k in (1, 2, 3))
    assert all(capped[k] == [] for k in (14, 15, 16))
    # Without the cap all sixteen played every day: the field's extra games.
    assert per_day(playing(members, NEXT, False), NEXT) == [16] * 7
    tw = week(members, NEXT, False, spots=SPOTS)
    assert sum(pw.games for pw in tw.players.values()) == SPOTS * 7


def test_an_undated_o_opponent_is_back_on_monday_but_within_the_cap():
    # Thirteen healthy players fill the spots; an O with no date comes back on Monday.
    members = roster(14, {1: "O"})
    capped = playing(members, NEXT, False, spots=SPOTS)
    assert capped[1] == list(NEXT)
    assert per_day(capped, NEXT) == [SPOTS] * 7
    assert capped[14] == []


def test_a_held_opponent_counts_only_from_his_espn_return_day():
    members = roster(14, {1: "O"})
    back = NEXT[2]
    capped = playing(members, NEXT, False, spots=SPOTS, returns={1: back})
    assert capped[1] == [d for d in NEXT if d >= back]
    # The least valuable holds the spot until then, and gives it up on that day.
    assert capped[14] == [d for d in NEXT if d < back]
    assert per_day(capped, NEXT) == [SPOTS] * 7


def test_a_dated_inj_plays_from_his_date_and_an_undated_one_never():
    members = roster(13, {1: "INJ", 2: "INJ"})
    back = NEXT[4]
    days = playing(members, NEXT, False, spots=SPOTS, returns={1: back})
    assert days[1] == [d for d in NEXT if d >= back]
    assert days[2] == []
    # An INJ held is out of this week either way.
    this = playing(members, THIS, True, spots=SPOTS, returns={1: THIS[0]})
    assert this[1] == [] and this[2] == []


def test_this_week_is_unchanged_by_the_spots_and_the_dates():
    members = roster(16, {1: "O", 2: "INJ", 5: "GTD"})
    plain = week(members, THIS, True, no_games=frozenset({5}))
    legal = week(
        members, THIS, True, no_games=frozenset({5}), spots=SPOTS, returns={1: THIS[1], 2: THIS[1]}
    )
    assert legal == plain


def test_no_spots_and_no_dates_is_the_projection_as_before():
    members = roster(16, {1: "O", 2: "INJ"})
    assert week(members, NEXT, False, spots=None, returns=None) == week(members, NEXT, False)


def test_a_drop_and_a_late_add_hold_a_spot_only_inside_their_days():
    members = roster(14)
    gone, added = {2: NEXT[3]}, {1: NEXT[2]}
    capped = playing(members, NEXT, False, spots=SPOTS, available_from=added, gone_from=gone)
    # Before the add's day and from the drop's day the spot goes to the next player.
    assert capped[14] == [NEXT[0], NEXT[1], *NEXT[3:]]
    assert per_day(capped, NEXT) == [SPOTS] * 7


def test_my_returning_player_takes_a_spot_from_his_date_in_the_outlooks_projection():
    members = roster(14, {1: "O"})
    active, held = members[1:], members[:1]
    back = NEXT[3]
    rates = {k: line(1.0) for k, _ in members}
    span = mv.WeekSpan(NEXT, False, ())
    problem = mv.MoveProblem(
        roster=tuple(active),
        held=tuple(held),
        spots=SPOTS,
        held_open={},
        candidates=(),
        effective={},
        first_day=THIS[0],
        rates=rates,
        schedule=SCHEDULE,
        slots=SLOTS,
        value=value(members),
        cats=("pts", "reb", "ast"),
        points=None,
        no_games=frozenset(),
        horizons={"week": (), "three": (span,)},
        returns={1: back},
        held_slots={1: "IL"},
    )
    capped = mv.project_mine(problem, span, spots=SPOTS)
    assert capped.players[1].games == sum(1 for d in NEXT if d >= back)
    assert capped.players[14].games == sum(1 for d in NEXT if d < back)
    # The moves leave the cap off: their comebacks charge the drop.
    free = mv.project_mine(problem, span)
    assert free.players[14].games == 7 and free.players[1].games == capped.players[1].games


def test_my_dated_inj_comes_back_on_his_date_and_a_pending_add_is_not_dated():
    members = roster(13, {1: "INJ"})
    rates = {k: line(1.0) for k, _ in members}
    spans = (mv.WeekSpan(NEXT, False, ()),)
    problem = mv.MoveProblem(
        roster=tuple(members[1:]),
        held=tuple(members[:1]),
        spots=SPOTS,
        held_open={},
        candidates=(),
        effective={},
        first_day=THIS[0],
        rates=rates,
        schedule=SCHEDULE,
        slots=SLOTS,
        value=value(members),
        cats=("pts",),
        points=None,
        no_games=frozenset(),
        horizons={"week": (), "three": spans},
        returns={1: NEXT[2]},
        held_slots={1: "IL+"},
    )
    assert mv.dated(problem, 1)
    assert mv.comes_back(problem, 1, members[0][1], spans) == NEXT[2]
    # A pending claim's clear day is held in ``returns`` too, but it is no return date.
    pending = replace(problem, pending=frozenset({1}))
    assert not mv.dated(pending, 1)
    assert mv.comes_back(pending, 1, members[0][1], spans) is None
