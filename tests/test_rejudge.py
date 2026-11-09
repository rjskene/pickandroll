"""A placed claim judged again when a held player clears (#345): as the build judges a new entry,
with his comeback's drop charged, and cancelled when it no longer pays or the comeback would drop
the claim's own add (31153, 2026-11-09: a $2 claim won at 04:17 and dropped at 05:31 by the
comeback). Nothing here opens a page.
"""

from __future__ import annotations

import pytest

from pickandroll.api import season_moves
from pickandroll.season import Player
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from tests.test_moves import build, rates, streaming_league

BACK = 5


def league(add_value: float, status: str = "O"):
    """The streaming league with player 5 on IL as ``status`` in this league's read, and the
    streamer 10 (the claim's add) worth ``add_value`` a game."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    rate |= {BACK: rates(1.0)}
    value = {k: 1.0 for k in rate} | {1: 1.2, 3: 0.4, 10: add_value}
    held = [(BACK, Player(BACK, "Back", "MIN", ("C",), status=status))]
    p = build(
        roster, cands, rate, sched, opponent, field, held=held, held_slots={BACK: "IL"}, value=value
    )
    return season_moves.Built(problem=p, system={}, horizons={}, adds={}, unprojected=0)


CLAIM = {"id": "2026-11-07:1:10:1", "add": 10, "drop": 1, "judged": "three"}
OPEN = qa.Floor(plan=-100.0, scored=None, moves=0)


def test_his_newest_status_clears_him_where_this_leagues_read_still_shows_him_out():
    built = league(0.1)
    assert mv.cleared(built.problem) == []
    p = season_moves.with_statuses(built.problem, {BACK: "P"})
    assert mv.cleared(p) == [(BACK, "IL")]
    # The built problem itself is never changed, and no statuses leave it as it is.
    assert mv.cleared(built.problem) == []
    assert season_moves.with_statuses(built.problem, {}) is built.problem


def test_a_claim_whose_add_his_comeback_would_drop_is_cancelled():
    # The add is the weakest active player once he is back: the comeback sends him.
    [j] = season_moves.rejudge_claims(league(0.1), [CLAIM], {BACK: "P"}).values()
    assert j["judged"] == "three" and j["comeback_drops"] == {BACK: 10}
    verdict, reason = qa.rejudge_verdict(
        10, [BACK], j["gain"], j["value"], OPEN, j["season_costly"], j["comeback_drops"]
    )
    assert verdict == qa.CANCEL
    assert reason == "with 5 back his comeback would drop 10, the claim's own add"


def test_a_claim_that_still_pays_with_him_back_is_kept():
    # A strong add: the comeback sends the weakest of the rest (3), and the gain clears the floor.
    [j] = season_moves.rejudge_claims(league(2.0), [CLAIM], {BACK: "P"}).values()
    assert j["comeback_drops"] == {BACK: 3}
    assert qa.rejudge_verdict(
        10, [BACK], j["gain"], j["value"], OPEN, j["season_costly"], j["comeback_drops"]
    ) == (qa.KEEP, "with 5 back it still clears the noise floor")
    # The gain is the evaluator's with his comeback charged in the base and in the set.
    p = season_moves.with_statuses(league(2.0).problem, {BACK: "P"})
    assert j["gain"] == pytest.approx(mv.Evaluator(p).gain("three", [mv.Move(10, 1)]))


def test_the_verdict_takes_the_season_guard_and_the_floor_as_the_build_does():
    floor = qa.Floor(plan=0.05, scored=None, moves=0)
    assert qa.rejudge_verdict(10, [BACK], 0.5, None, floor, True, {BACK: 3}) == (
        qa.CANCEL,
        "with 5 back it costs the season (season-costly)",
    )
    assert qa.rejudge_verdict(10, [BACK], 0.01, None, floor, False, {BACK: 3}) == (
        qa.CANCEL,
        "with 5 back it is below the noise floor (plan)",
    )
    scored = qa.Floor(plan=0.05, scored=1.0, moves=30)
    assert qa.rejudge_verdict(10, [5, 6], 0.5, 0.5, scored, None, {5: 3, 6: 2}) == (
        qa.CANCEL,
        "with 5 and 6 back it is below the noise floor (scored)",
    )
    assert qa.rejudge_verdict(10, [BACK], 0.5, None, floor, None, {BACK: 3})[0] == qa.KEEP


def test_a_claim_out_of_the_pool_or_off_the_roster_is_not_judged():
    built = league(0.1)
    gone = {**CLAIM, "id": "x", "add": 99}
    no_drop = {**CLAIM, "id": "y", "drop": 77}
    out = season_moves.rejudge_claims(built, [gone, no_drop], {BACK: "P"})
    assert out == {"x": None, "y": None}
