"""The seat's bid policy (#172, PR F2, ``sim/bid_policy.py``): the family on the pure function.
The default member is the live rule (``autopilot.bid_of``, through the door); each lever alone;
the refusals by name. No season is played here: the queue, the walls and the record are
``test_sim_bid_seat.py``'s, the seasons ``test_sim_bid_seasons.py``'s."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from itertools import product

import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import engine, policy

DAY = timedelta(1)
#: A made-up season's calendar: twenty weeks of regular season from a Monday, two of bracket.
FIRST = date(2026, 10, 26)
BRACKET = FIRST + 140 * DAY
LAST = BRACKET + 13 * DAY


def seen(gain: float = 4.0, typical: float = 1.0, dollars: float = 100, **more) -> bp.Seen:
    return bp.Seen(gain, typical, dollars, **more)


def on(day: date) -> bp.When:
    return bp.When(day, FIRST, BRACKET, LAST)


# --------------------------------------------------------------------------- Rule 4: parity
GAINS = (-1.0, 0.0, 0.3, 0.4999, 0.5, 1.0, 1.4999, 1.5, 2.5, 3.2, 7.4999, 7.5, 12.0, 250.0)
TYPICALS = (-0.5, 0.0, 0.01, 0.1, 0.25, 1 / 3, 1.0, 2.0)
DOLLARS = (0, 1, 4, 37, 100)
SIZINGS = (None, 0, 0.5, 1.0, 1.25, 2.0)


def test_the_default_member_is_the_live_rule_through_the_door():
    """Rule 4: over a grid of gains, typicals, dollars and sizings the family's default returns
    ``autopilot.bid_of``'s amount for a claim with no flag, called through ``sim/engine.py``;
    and so does the route the queue takes for an arm that names no ``bid``
    (``policy.live_bid``). An empty block is the default member."""
    assert bp.of({}) == bp.DEFAULT == bp.BidPolicy()
    cells = 0
    for gain, typical, dollars, sizing in product(GAINS, TYPICALS, DOLLARS, SIZINGS):
        live = engine.bid_of(gain, (typical, "the grid's"), dollars, None, sizing, "W").amount
        got = bp.amount(bp.DEFAULT, seen(gain, typical, dollars, sizing=sizing))
        assert got == live, (gain, typical, dollars, sizing)
        # Until ten moves the typical is the plan floor: the queue's own call.
        assert policy.live_bid(gain, [], typical, dollars, sizing) == live
        cells += 1
    assert cells == len(GAINS) * len(TYPICALS) * len(DOLLARS) * len(SIZINGS)
    # A typical at or below 0: the live rule takes a base of 1 whatever the gain, the family
    # one of 1 for a gain above 0 and of 0 for a gain of 0 or less. Both are routine claims, so
    # the amount is one (the lead's working default, 2026-11-19): the grid holds every such cell.
    flat = [(g, t) for g, t in product(GAINS, TYPICALS) if t <= 0]
    assert {(g > 0) - (g < 0) for g, _ in flat} == {-1, 0, 1} and {t for _, t in flat} == {-0.5, 0}
    for (gain, typical), dollars, sizing in product(flat, DOLLARS, SIZINGS):
        s = seen(gain, typical, dollars, sizing=sizing)
        assert bp.value(bp.DEFAULT, s) == (1.0 if gain > 0 else 0.0)
        assert bp.amount(bp.DEFAULT, s) == 0
        assert engine.bid_of(gain, (typical, "flat"), dollars, None, sizing, "W").amount == 0
    # The grid holds routine claims, sized ones and clamped ones.
    amounts = {
        bp.amount(bp.DEFAULT, seen(g, t, d, sizing=s))
        for g, t, d, s in product(GAINS, TYPICALS, DOLLARS, SIZINGS)
    }
    assert {0, 1, 3, 37, 100} <= amounts


def test_the_default_member_on_the_fortnight_s_median_is_the_live_rule():
    """With ten moves the typical is the engine's own median (``autopilot.typical_gain``): the
    family is handed it and sizes on it as ``bid_of`` does."""
    fortnight = [0.2, 0.31, 0.5, 0.5, 0.77, 1.0, 1.3, 2.0, 2.2, 6.0]
    typical = engine.typical_gain(fortnight, 0.1)
    assert typical[1] == "the fortnight's median"
    for gain, sizing in product(GAINS, SIZINGS):
        live = engine.bid_of(gain, typical, 100, None, sizing, "W").amount
        assert bp.amount(bp.DEFAULT, seen(gain, typical[0], 100, sizing=sizing)) == live
        assert policy.live_bid(gain, fortnight, 0.1, 100, sizing) == live


# --------------------------------------------------------------------------- the value
def test_the_value_follows_the_named_horizon():
    s = seen(4.0, 1.0, week=6.0, typical_week=2.0, season=30.0, typical_season=3.0)
    assert bp.value(bp.DEFAULT, s) == 4.0
    assert bp.value(bp.of({"week": 1}), s) == 3.0
    assert bp.value(bp.of({"season": 1}), s) == 10.0
    # The three weeks take the rest of the weight.
    mixed = bp.of({"week": 0.25, "season": 0.25})
    assert mixed.three == 0.5
    assert bp.value(mixed, s) == pytest.approx(0.5 * 4.0 + 0.25 * 3.0 + 0.25 * 10.0)
    assert bp.amount(bp.of({"week": 1}), s) == 3 and bp.amount(bp.of({"season": 1}), s) == 10
    # A weight of 0 reads nothing: the horizon's figures may be absent.
    assert bp.value(bp.of({"week": 0.5}), replace(s, season=None, typical_season=None)) == 3.5


def test_a_gain_of_none_counts_zero_and_the_first_ten_moves_count_as_typical():
    season = bp.of({"season": 1})
    # No season figure for the move: 0 typicals, a routine claim.
    none = seen(4.0, 1.0, season=None, typical_season=3.0)
    assert bp.value(season, none) == 0.0 and bp.amount(season, none) == 0
    # Until ten moves the week and the season have no typical: a move that gains counts as
    # typical, one that gains nothing (or has no figure) as nothing.
    for rule, more, worth in (
        (bp.of({"week": 1}), {"week": 50.0, "typical_week": None}, 1.0),
        (season, {"season": 50.0, "typical_season": None}, 1.0),
        (bp.of({"week": 1}), {"week": 0.0, "typical_week": None}, 0.0),
        (season, {"season": -3.0, "typical_season": None}, 0.0),
        (season, {"season": None, "typical_season": None}, 0.0),
    ):
        early = seen(4.0, 1.0, **more)
        assert bp.value(rule, early) == worth and bp.amount(rule, early) == 0
    # A typical at or below 0 scales nothing: a gain above 0 is one typical, as bid_of takes
    # one on the three weeks, and a gain of 0 or less is nothing.
    assert bp.value(season, seen(4.0, 1.0, season=9.0, typical_season=-2.0)) == 1.0
    assert bp.value(season, seen(4.0, 1.0, season=0.0, typical_season=-2.0)) == 0.0
    assert bp.value(bp.DEFAULT, seen(4.0, 0.0)) == 1.0
    assert bp.value(bp.DEFAULT, seen(0.0, 0.0)) == bp.value(bp.DEFAULT, seen(-4.0, -1.0)) == 0.0
    # The three weeks' typical until ten moves is the plan floor, handed in as today.
    half = bp.of({"week": 0.5})
    assert bp.value(half, seen(4.0, 0.5, week=7.0, typical_week=None)) == 0.5 * 8.0 + 0.5


def test_a_plan_s_step_keeps_today_s_value_whatever_the_weights():
    """A step's gain is its week increment and its value that over the three weeks' typical:
    the horizon weights are not applied to it (PR E gives the steps their rule)."""
    step = seen(3.0, 1.0, step=True, week=50.0, typical_week=1.0, season=50.0, typical_season=1.0)
    for block in ({}, {"week": 1}, {"season": 1}, {"week": 0.3, "season": 0.3}):
        assert bp.value(bp.of(block), step) == 3.0
        assert bp.amount(bp.of(block), step) == bp.amount(bp.DEFAULT, seen(3.0, 1.0))


# --------------------------------------------------------------------------- the pace
PACE = {"k": 1, "shape": 1, "reserve": 0.2}
MID = FIRST + 70 * DAY  # half the regular season gone: the path holds 0.2 + 0.8 x 0.5


def paced(day: date, dollars: float, gain: float = 4.0, **pace) -> int:
    rule = bp.of({"pace": {**PACE, **pace}})
    return bp.amount(rule, seen(gain, 1.0, dollars, budget=100, when=on(day)))


def test_the_path_falls_over_the_regular_season_then_in_a_straight_line_to_nothing():
    line = bp.Pace(1.0, 1.0, 0.2)
    assert bp.path(line, on(FIRST)) == 1.0
    assert bp.path(line, on(MID)) == 0.6
    assert bp.path(line, on(BRACKET - DAY)) == pytest.approx(0.2 + 0.8 / 140)
    # The first day of the bracket holds the reserve, by either rule.
    assert bp.path(line, on(BRACKET)) == 0.2
    # A curve: shape 2 spends sooner, shape 0.5 later.
    assert bp.path(bp.Pace(1.0, 2.0, 0.2), on(MID)) == 0.4
    assert bp.path(bp.Pace(1.0, 0.5, 0.2), on(MID)) == pytest.approx(0.2 + 0.8 * math.sqrt(0.5))
    # The bracket's straight line, from the reserve to 0 on the last morning, and 0 after.
    assert bp.path(line, on(BRACKET + 6 * DAY)) == pytest.approx(0.2 * 7 / 13)
    assert bp.path(line, on(LAST - DAY)) == pytest.approx(0.2 / 13)
    assert bp.path(line, on(LAST)) == 0.0 == bp.path(line, on(LAST + DAY))
    # No bracket read: the caller names the day after the season's last, and the whole season
    # is regular.
    whole = bp.When(LAST, FIRST, LAST + DAY, LAST)
    assert bp.path(line, whole) == pytest.approx(0.2 + 0.8 / 154)
    # A day before the first counts as the first.
    assert bp.path(line, on(FIRST - DAY)) == 1.0


def test_on_the_path_the_bid_is_today_s_ahead_of_it_more_behind_it_less():
    today = bp.amount(bp.DEFAULT, seen(4.0, 1.0, 60))
    assert today == 4
    # On the path: 60 of 100 dollars left where the path holds 0.6.
    assert paced(MID, 60) == today
    # Ahead of it (more left than the path holds) the bid is more; behind it, less.
    assert paced(MID, 90) == 6  # 4 typicals x 1.5
    assert paced(MID, 30) == 2  # x 0.5
    assert paced(MID, 90, k=2) == 9  # x 1.5 squared
    assert paced(MID, 30, k=2) == 0  # x 0.25: one typical, a routine claim
    # k 0 is today's, wherever the seat stands; so is no pace.
    for dollars in (30, 60, 90):
        assert paced(MID, dollars, k=0) == bp.amount(bp.DEFAULT, seen(4.0, 1.0, dollars))
    # A pace lifts a claim under one typical above the routine when the seat is far ahead.
    assert paced(BRACKET, 100, gain=0.5) == 3  # 0.5 x (1.0 / 0.2), half up
    assert paced(FIRST, 100, gain=0.5) == 0
    # The first day: every dollar left, on the path.
    assert paced(FIRST, 100) == today
    # A seat with nothing left bids nothing.
    assert paced(MID, 0) == 0


def test_the_bracket_s_line_and_the_last_morning_spends_what_is_left():
    # Midway down the bracket's line the path holds 0.2 x 7 / 13: 20 dollars left are ahead.
    assert paced(BRACKET + 6 * DAY, 20) == bp._half_up(4.0 * round(0.2 / (0.2 * 7 / 13), 9))
    # On the last morning a claim can be decided the path is 0 and the pace has no bound: a
    # claim above the routine bids what is left, a routine one the routine.
    assert bp.pace(bp.of({"pace": PACE}), seen(budget=100, when=on(LAST))) == math.inf
    assert paced(LAST, 17) == 17
    assert paced(LAST, 17, gain=0.2) == 17
    assert paced(LAST, 17, gain=0.0) == 0 and paced(LAST, 17, gain=-1.0) == 0
    one = bp.of({"pace": PACE, "routine": 1})
    assert bp.amount(one, seen(0.0, 1.0, 17, budget=100, when=on(LAST))) == 1
    # A reserve of 0 has no bound from the first day of the bracket.
    assert paced(BRACKET, 3, reserve=0) == 3
    # A sizing is not applied to what is left.
    rule = bp.of({"pace": PACE})
    assert bp.amount(rule, seen(4.0, 1.0, 17, sizing=0.5, budget=100, when=on(LAST))) == 17


def test_a_claim_worth_nothing_never_rides_a_pace_in_the_bracket_s_last_week():
    """The lead's working default (q-5, 2026-11-19). In the bracket's last week a simulated
    seat reads no opponent, so a move its season term picks gains nothing on the three weeks,
    and a fortnight of such moves has a typical of 0. A paced arm whose ``bid.season`` is 0 bids the
    routine on such a claim on its path, ahead of it and where the path is 0; one whose
    ``bid.season`` is above 0 values the claim by the season, and its pace bids that up."""
    week = BRACKET + 6 * DAY
    on_path = 100 * bp.path(bp.Pace(1.0, 1.0, 0.2), on(week))
    cases = ((week, on_path), (week, 100), (LAST, 100))
    paces = [
        bp.pace(bp.of({"pace": PACE}), seen(0.0, 0.0, dollars, budget=100, when=on(day)))
        for day, dollars in cases
    ]
    assert paces[0] == 1.0 and 9 < paces[1] < 10 and paces[2] == math.inf
    for routine in bp.ROUTINES:
        rule = bp.of({"pace": PACE, "routine": routine})
        assert rule.season == 0
        for (day, dollars), (gain, typical) in product(
            cases, ((0.0, 0.0), (0.0, -0.2), (-0.3, 0.0), (0.0, 0.5))
        ):
            s = seen(gain, typical, dollars, budget=100, when=on(day))
            assert bp.value(rule, s) == 0.0, (day, dollars, gain, typical)
            assert bp.amount(rule, s) == routine, (day, dollars, gain, typical)
    # A gain above 0 on a typical of 0 is the live rule's one typical, and that does ride.
    rule = bp.of({"pace": PACE})
    ahead = seen(0.4, 0.0, 100, budget=100, when=on(week))
    assert bp.value(rule, ahead) == 1.0 and bp.amount(rule, ahead) == bp._half_up(paces[1]) == 9
    # The same claim under a weight on the season is worth its season figure in typicals: the
    # reserve is spent in the bracket's last week only by such an arm.
    weighs = bp.of({"pace": PACE, "season": 0.5})
    there = seen(0.0, 0.0, 100, budget=100, when=on(week), season=6.0, typical_season=2.0)
    assert bp.value(weighs, there) == 1.5
    assert bp.amount(weighs, there) == bp._half_up(1.5 * paces[1]) == 14
    assert bp.amount(weighs, replace(there, when=on(LAST))) == 100
    assert bp.amount(rule, there) == 0


def test_a_pace_reads_the_calendar_and_a_league_without_a_budget_has_none():
    rule = bp.of({"pace": PACE})
    with pytest.raises(ValueError, match="a pace reads the calendar"):
        bp.amount(rule, seen(budget=100))
    assert bp.pace(rule, seen(dollars=0, budget=0)) == 1.0
    # k 0 reads no calendar at all.
    assert bp.amount(bp.of({"pace": {**PACE, "k": 0}}), seen(budget=100)) == 4
    # A power too large for a float has no bound either.
    huge = bp.of({"pace": {"k": 1e6, "shape": 1, "reserve": 0.2}})
    assert bp.pace(huge, seen(dollars=100, budget=100, when=on(BRACKET))) == math.inf


def test_a_pace_whose_product_is_beyond_a_float_has_no_bound_either():
    """A ``k`` the block takes can give a pace that is a float while its product with the
    claim's value, or the base's with the sizing, is not one. That is no bound, as a power
    beyond a float is none: a claim worth more than nothing bids every dollar left, one worth
    less the routine, the caps and the clamp after it, and nothing is raised (found in review:
    it raised ``OverflowError`` inside the queue)."""
    steep = bp.of({"pace": {"k": 1023.5, "shape": 1, "reserve": 0.5}})
    at = {"budget": 100, "when": on(BRACKET)}
    p = bp.pace(steep, seen(**at))
    assert math.isfinite(p) and math.isinf(4.0 * p) and math.isfinite(1.0 * p)
    # The value times the pace is beyond a float.
    assert bp.amount(steep, seen(4.0, 1.0, 100, **at)) == 100
    assert bp.amount(steep, seen(4.0, 1.0, 100, sizing=0.5, **at)) == 100
    assert bp.amount(replace(steep, rival_cap=True), seen(4.0, 1.0, 100, others=(3,), **at)) == 4
    for routine in bp.ROUTINES:
        assert bp.amount(replace(steep, routine=routine), seen(-4.0, 1.0, 100, **at)) == routine
    # The base is a float and its product with the sizing is not.
    assert bp.amount(steep, seen(1.0, 1.0, 100, sizing=2.0, **at)) == 100
    assert bp.amount(steep, seen(1.0, 1.0, 100, sizing=0.5, **at)) == 100


# --------------------------------------------------------------------------- the routine
def test_a_routine_claim_bids_nothing_or_a_dollar_and_is_clamped_to_the_dollars_left():
    one = bp.of({"routine": 1})
    for gain in (-1.0, 0.0, 0.4, 1.0, 1.4999):
        assert bp.amount(bp.DEFAULT, seen(gain)) == 0
        assert bp.amount(one, seen(gain)) == 1
        assert bp.amount(one, seen(gain, dollars=0)) == 0
    # A claim above the routine is the same under either.
    assert bp.amount(one, seen(1.5)) == bp.amount(bp.DEFAULT, seen(1.5)) == 2
    # The routine dollar is not sized.
    assert bp.amount(one, seen(1.0, sizing=3.0)) == 1


# --------------------------------------------------------------------------- the rival cap
def test_the_rival_cap_binds_when_the_others_are_poor_and_never_when_one_is_rich():
    cap = bp.of({"rival_cap": True})
    big = seen(12.0, 1.0, 100)
    assert bp.amount(bp.DEFAULT, big) == 12
    # The richest other team holds 5: no bid above 6 can be needed to win.
    assert bp.amount(cap, replace(big, others=(0, 3, 5))) == 6
    assert bp.amount(cap, replace(big, others=(0, 0, 0))) == 1
    # One rich rival and it never binds.
    assert bp.amount(cap, replace(big, others=(0, 3, 500))) == 12
    assert bp.amount(cap, replace(big, others=(11, 0))) == 12
    # Off, the others are not read; with no other team there is no cap.
    assert bp.amount(bp.DEFAULT, replace(big, others=(0, 0, 0))) == 12
    assert bp.amount(cap, big) == 12
    # The clamp is last.
    assert bp.amount(cap, replace(big, dollars=4, others=(0, 3, 5))) == 4


# --------------------------------------------------------------------------- the shade
def test_the_shade_is_off_until_enough_wins_are_seen_then_the_quantile_plus_one():
    wins = (0, 0, 0, 1, 1, 2, 3, 5, 8, 30)
    big = seen(40.0, 1.0, 100, wins=wins)
    assert bp.amount(bp.DEFAULT, big) == 40
    # Ten seen and ten needed: nine in ten of the winning bids were 8 or less, so 9.
    assert bp.amount(bp.of({"shade": {"q": 0.9, "least": 10}}), big) == 9
    # Off until `least` are seen.
    assert bp.amount(bp.of({"shade": {"q": 0.9, "least": 11}}), big) == 40
    assert bp.amount(bp.of({"shade": {"q": 0.9, "least": 1}}), replace(big, wins=())) == 40
    # The quantile: the least bid at or below which that share of them falls; q 1 is the top.
    for q, at in ((0.1, 0), (0.3, 0), (0.4, 1), (0.5, 1), (0.6, 2), (0.75, 5), (1.0, 30)):
        assert bp.quantile(wins, q) == at, q
        assert bp.amount(bp.of({"shade": {"q": q, "least": 1}}), big) == at + 1
    assert bp.quantile((7,), 0.01) == 7 and bp.quantile((4, 2), 0.5) == 2
    # It never lifts a bid, and the clamp is last.
    small = seen(3.0, 1.0, 100, wins=wins)
    assert bp.amount(bp.of({"shade": {"q": 1, "least": 1}}), small) == 3
    assert bp.amount(bp.of({"shade": {"q": 1, "least": 1}}), replace(big, dollars=2)) == 2


def test_the_caps_come_after_the_sizing_and_before_the_clamp():
    rule = bp.of({"rival_cap": True, "shade": {"q": 0.5, "least": 2}, "routine": 1})
    s = seen(10.0, 1.0, 100, sizing=2.0, others=(9, 2), wins=(4, 6, 20))
    assert bp.amount(bp.DEFAULT, s) == 20
    assert bp.amount(bp.of({"rival_cap": True}), s) == 10
    assert bp.amount(rule, s) == 7
    assert bp.amount(rule, replace(s, dollars=5)) == 5
    # A routine dollar is under either cap.
    assert bp.amount(rule, replace(s, gain=0.5, others=(0, 0), wins=(0, 0, 0))) == 1


# --------------------------------------------------------------------------- the block
def test_the_block_s_keys_defaults_payload_and_label():
    assert bp.KEYS == ("week", "season", "pace", "routine", "rival_cap", "shade")
    assert bp.DEFAULT.payload() == {
        "week": 0.0,
        "season": 0.0,
        "pace": None,
        "routine": 0,
        "rival_cap": False,
        "shade": None,
    }
    full = bp.of(
        {
            "week": 0.25,
            "season": 0.5,
            "pace": {"k": 1, "shape": 2, "reserve": 0.2},
            "routine": 1,
            "rival_cap": True,
            "shade": {"q": 0.9, "least": 10},
        }
    )
    assert full == bp.BidPolicy(0.25, 0.5, bp.Pace(1.0, 2.0, 0.2), 1, True, bp.Shade(0.9, 10))
    assert full.payload() == {
        "week": 0.25,
        "season": 0.5,
        "pace": {"k": 1.0, "shape": 2.0, "reserve": 0.2},
        "routine": 1,
        "rival_cap": True,
        "shade": {"q": 0.9, "least": 10},
    }
    assert bp.of(full.payload()) == full and list(full.payload()) == list(bp.KEYS)
    assert full.label() == (
        "week 0.25, season 0.5, the three weeks 0.25, pace k 1 shape 2 reserve 0.2, a routine "
        "claim $1, the rival cap on, shade at the 0.9 quantile once 10 are seen"
    )
    assert bp.DEFAULT.label() == (
        "week 0, season 0, the three weeks 1, no pace, a routine claim $0, no rival cap, no shade"
    )
    # A null pace or shade is none; it is part of the repr, so two seats never share a decision.
    assert bp.of({"pace": None, "shade": None}) == bp.DEFAULT
    assert repr(full) != repr(bp.DEFAULT) and hash(full) != hash(bp.DEFAULT)


def test_weights_that_sum_to_one_leave_the_three_weeks_a_plain_nothing():
    """The three weeks take the rest of the weight, rounded: for some pairs that sum to 1 the
    rounded rest was a negative zero, and the line a run prints read "the three weeks -0"."""
    for week, season in ((0.9, 0.1), (0.8, 0.2), (0.7, 0.3), (0.25, 0.75), (1, 0), (0, 1)):
        rule = bp.of({"week": week, "season": season})
        assert rule.three == 0 and math.copysign(1.0, rule.three) == 1.0, (week, season)
        assert ", the three weeks 0, " in rule.label()
    assert bp.of({"week": 0.3, "season": 0.3}).three == 0.4


def test_a_pace_at_k_0_is_no_pace_in_the_block_as_it_bids():
    """``BidPolicy.bids``: the block with everything it never reads taken out. A pace at ``k`` 0
    follows no path, whatever its ``shape`` and ``reserve``, so it is no pace; every other key
    stands, and the block as named (the payload's) is not changed."""
    still = bp.of({"pace": {"k": 0, "shape": 3, "reserve": 0.9}, "routine": 1, "week": 0.5})
    assert still.pace == bp.Pace(0.0, 3.0, 0.9) and still.payload()["pace"]["shape"] == 3.0
    assert still.bids() == bp.of({"routine": 1, "week": 0.5}) != still
    assert bp.of({"pace": {"k": 0, "shape": 1, "reserve": 0.2}}).bids() == bp.DEFAULT
    paced = bp.of({"pace": PACE})
    assert paced.bids() is paced and bp.DEFAULT.bids() is bp.DEFAULT
    # It bids as the block without the pace, on any day and at any dollars.
    for day, dollars in product((FIRST, MID, BRACKET, LAST), (0, 20, 100)):
        s = seen(4.0, 1.0, dollars, budget=100, when=on(day), week=1.0)
        assert bp.amount(still, s) == bp.amount(still.bids(), s)


@pytest.mark.parametrize(
    ("block", "words"),
    [
        ([], "bid []: a mapping of week, season, pace, routine, rival_cap, shade, each optional"),
        ({"weak": 1}, "bid key 'weak' is not one the simulator reads: one of ('week', 'season',"),
        ({"week": -0.1}, "bid week -0.1: a number from 0 to 1"),
        ({"week": 1.5}, "bid week 1.5: a number from 0 to 1"),
        ({"week": "1"}, "bid week '1': a number from 0 to 1"),
        ({"week": True}, "bid week True: a number from 0 to 1"),
        ({"season": float("nan")}, "bid season nan: a number from 0 to 1"),
        ({"season": 2}, "bid season 2: a number from 0 to 1"),
        (
            {"week": 0.6, "season": 0.5},
            "bid week 0.6 and season 0.5: their sum is at most 1 (the three weeks take the rest)",
        ),
        ({"pace": 1}, "bid pace 1: a mapping of k, shape, reserve, or none"),
        ({"pace": {"k": 1, "shape": 1}}, "bid pace names k, shape, reserve: 'reserve' is missing"),
        (
            {"pace": {**PACE, "floor": 1}},
            "bid pace key 'floor' is not one of ('k', 'shape', 'reserve')",
        ),
        ({"pace": {**PACE, "k": -1}}, "bid pace k -1: a number, 0 or more"),
        ({"pace": {**PACE, "k": float("inf")}}, "bid pace k inf: a number, 0 or more"),
        ({"pace": {**PACE, "shape": 0}}, "bid pace shape 0: a number above 0"),
        (
            {"pace": {**PACE, "reserve": 1}},
            "bid pace reserve 1: a number, 0 or more and below 1",
        ),
        (
            {"pace": {**PACE, "reserve": -0.1}},
            "bid pace reserve -0.1: a number, 0 or more and below 1",
        ),
        ({"routine": 2}, "bid routine 2: 0 or 1 dollars"),
        ({"routine": 0.5}, "bid routine 0.5: 0 or 1 dollars"),
        ({"routine": True}, "bid routine True: 0 or 1 dollars"),
        ({"rival_cap": 1}, "bid rival_cap 1: true or false"),
        ({"rival_cap": "on"}, "bid rival_cap 'on': true or false"),
        ({"shade": 0.9}, "bid shade 0.9: a mapping of q, least, or none"),
        ({"shade": {"q": 0.9}}, "bid shade names q, least: 'least' is missing"),
        ({"shade": {"q": 0, "least": 1}}, "bid shade q 0: a number above 0 and at most 1"),
        ({"shade": {"q": 1.1, "least": 1}}, "bid shade q 1.1: a number above 0 and at most 1"),
        ({"shade": {"q": 0.9, "least": 0}}, "bid shade least 0: a whole number, 1 or more"),
        ({"shade": {"q": 0.9, "least": 2.5}}, "bid shade least 2.5: a whole number, 1 or more"),
    ],
)
def test_an_unknown_key_and_each_bad_value_are_refused_by_name(block, words):
    with pytest.raises(ValueError) as e:
        bp.of(block)
    assert words in str(e.value)
    # The weights at their bounds are taken.
    assert bp.of({"week": 0.5, "season": 0.5}).three == 0.0
    assert bp.of({"week": 0.7, "season": 0.3}).three == 0.0
