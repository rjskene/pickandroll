"""The season guard (#164): no recommended set, re-solve or streaming plan whose rest of the
season is below zero; the set it held back named beside the one recommended; the strategy's
program set taken only when allowed; the decision log's record. Every league here is made up
(``test_moves``'s and ``test_stream``'s fixtures); the outcomes are set by construction."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from pickandroll.api import season_decisions
from pickandroll.api import season_moves as sm
from pickandroll.season import moves as mv
from pickandroll.season import strategy as st
from pickandroll.season import stream as st_

from .test_moves import WEEKS, build, player, rates, schedule
from .test_stream import THU, per_game, stream_league

POINTS = {"points": {"pts": 1.0}}
HORIZONS = {
    "week": {"label": "rest of week 1", "weeks": [1]},
    "three": {"label": "weeks 2-4", "weeks": [2, 3, 4]},
}


def resting_league():
    """Player 3 rests this week and plays three games a week after; the streamer (10) plays four
    this week and none after; the holder (11) plays one this week and four a week after. The
    best week drops 3 for the streamer, which costs the season; the holder for 3 gains less on
    the week and pays over the season."""
    after = [7 + 7 * w + d for w in range(3) for d in (0, 2, 4)]
    sched = schedule(
        {
            "MIN": [0, 2, 4, 6] + [7 + 7 * w + d for w in range(3) for d in (0, 3)],
            "OFF": after,
            "STR": [0, 1, 3, 5],
            "HLD": [6] + [7 + 7 * w + d for w in range(3) for d in (0, 2, 4, 6)],
        }
    )
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "OFF")]
    cands = [player(10, "STR"), player(11, "HLD")]
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(1.5), 10: rates(1.0), 11: rates(1.2)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.1), 21: rates(1.0), 22: rates(0.9)}
    p = build(roster, cands, rate, sched, opponent, [opponent])
    return replace(p, season_end=WEEKS[3][6])


def built_of(problem: mv.MoveProblem, scorer=POINTS, **kw) -> sm.Built:
    return sm.Built(problem, {"key": "bbm"}, HORIZONS, {}, 0, scorer=scorer, **kw)


# --------------------------------------------------------------------------- the line
def test_a_set_is_allowed_at_zero_or_more_and_a_move_without_a_line_counts_none():
    ros = {mv.Move(10, 3): -2.0, mv.Move(11, 2): 2.0, mv.Move(12, 1): None}.get
    allowed = mv.season_guard(ros)
    assert allowed(()) and allowed([mv.Move(11, 2)])
    assert not allowed([mv.Move(10, 3)])
    # Exactly zero is on the line, and allowed.
    assert mv.season_total(ros, [mv.Move(10, 3), mv.Move(11, 2)]) == (0.0, False)
    assert allowed([mv.Move(10, 3), mv.Move(11, 2)])
    # A move without a line neither blocks the set nor pays for the rest; the total is partial.
    assert mv.season_total(ros, [mv.Move(12, 1)]) == (0.0, True)
    assert allowed([mv.Move(12, 1)]) and not allowed([mv.Move(12, 1), mv.Move(10, 3)])


def test_the_search_and_its_re_solves_never_offer_a_set_the_guard_refuses():
    p = resting_league()
    ros = sm.guard_ros(built_of(p))
    assert ros is not None
    assert ros(mv.Move(10, 3)) < 0 < ros(mv.Move(11, 3))
    allowed = mv.season_guard(ros)
    ev = mv.Evaluator(p)
    assert mv.search(ev, "week", [10, 11], min_gain=0.01) == (mv.Move(10, 3),)
    assert mv.search(ev, "week", [10, 11], min_gain=0.01, allowed=allowed) == (mv.Move(11, 3),)
    rec = mv.recommend(ev, "week", [10, 11], min_gain=0.01, allowed=allowed)
    assert [pm.move for pm in rec.moves] == [mv.Move(11, 3)]
    for pm in rec.moves:
        # Without the holder the guarded search finds nothing: the streamer for 3 is refused.
        assert pm.instead_without == ()
        for alt in (pm.instead_without, pm.instead_keep):
            assert alt is None or allowed(alt)


# --------------------------------------------------------------------------- the payload
def test_the_moves_payload_names_the_set_the_guard_held_back_and_what_it_forgoes():
    p = resting_league()
    out = sm.moves_payload(built_of(p))
    week = out["recommended"]["week"]
    assert [(x["add"], x["drop"]) for x in week["moves"]] == [(11, 3)]
    assert week["ros"]["value"] > 0
    # The week set re-solved without the holder offers nothing rather than the refused move.
    assert week["moves"][0]["instead_without"] == []
    guard = week["season_guard"]
    assert guard["held_back"] is True
    [held] = guard["moves"]
    assert (held["add"], held["drop"], held["season_costly"]) == (10, 3, True)
    assert held["ros"]["value"] < 0 and held["marginal"]["week"] > week["gain"]["week"]
    assert guard["ros"] == {"value": held["ros"]["value"], "partial": False}
    assert guard["gain"]["week"] == held["marginal"]["week"]
    assert guard["forgone"]["week"] == round(guard["gain"]["week"] - week["gain"]["week"], 3)
    assert guard["saved"] == {
        "value": round(week["ros"]["value"] - held["ros"]["value"], 4),
        "partial": False,
    }
    # The three weeks' set was the guard's to keep anyway: nothing held back.
    assert out["recommended"]["three"]["season_guard"] == {"held_back": False}
    # The landing grid reads the guarded set.
    assert sm.best_payload(built_of(p), out)["move"]["add"] == 11


def test_without_the_leagues_scorer_there_is_no_guard():
    p = resting_league()
    out = sm.moves_payload(built_of(p, scorer=None))
    week = out["recommended"]["week"]
    assert [(x["add"], x["drop"]) for x in week["moves"]] == [(10, 3)]
    assert week["season_guard"] is None
    assert sm.guard_ros(built_of(replace(p, season_end=None))) is None


# --------------------------------------------------------------------------- the plan
def blocking_league():
    """The stream league, with player 3 blocking shots the categories here leave out and the
    league's scorer counts heavily: the plan that streams his spot wins the week and the three
    weeks after, and costs the season."""
    problem, rule = stream_league()
    line = {**problem.rates[3], "blk": 5.0}
    problem = replace(problem, season_end=WEEKS[3][6], rates={**problem.rates, 3: line})
    built = sm.Built(
        problem, {"key": "bbm"}, {}, {}, 0, rule=rule, scorer={"points": {"pts": 1.0, "blk": 100.0}}
    )
    return problem, rule, built


def test_the_plan_keeps_to_the_season_guard_and_says_when_the_guard_refused_one():
    problem, rule, built = blocking_league()
    ev = mv.Evaluator(problem)
    allowed = mv.season_guard(sm.guard_ros(built))
    wild = st_.plan(ev, rule, (), per_game(problem))
    assert wild is not None and wild.steps[0] == mv.Move(10, 3, THU)
    assert not allowed(wild.moves)
    guarded = st_.plan(ev, rule, (), per_game(problem), allowed=allowed)
    assert guarded is not None and allowed(guarded.moves) and guarded.steps == ()
    out = sm.plan_payload(built, ev, [], [], sm.stream_of(built, ev, [], allowed), allowed)
    assert (out["recommended"], out["reason"], out["steps"]) == (False, "season", [])
    refused = out["guard"]
    assert [(x["add"], x["drop"], x["spot"]) for x in refused["steps"]] == [(10, 3, 3), (11, 10, 3)]
    assert refused["gain"]["week"] > st_.floor_of(problem) and refused["gain"]["three"] > 0
    assert refused["ros"]["value"] < 0
    # Without the guard the same plan is recommended.
    assert sm.plan_payload(built, ev, [], [], sm.stream_of(built, ev, []))["recommended"]


# --------------------------------------------------------------------------- the strategy
def test_the_strategy_takes_the_searchs_set_when_the_guard_refuses_the_programs():
    p = resting_league()
    ev = mv.Evaluator(p)
    w = st.Weighted(ev, 1.0, 10)
    allowed = mv.season_guard(sm.guard_ros(built_of(p)))
    search = mv.search(w, st.WEIGHTED, [10, 11], min_gain=0.01, allowed=allowed)
    program = st.Milp((mv.Move(10, 3),), st.OPTIMAL, 0.1, {})
    assert w.value(st.WEIGHTED, program.moves) > w.value(st.WEIGHTED, search)
    assert st.choose(w, search, program) == (st.MILP, program.moves)
    assert st.choose(w, search, program, allowed=allowed) == (st.SEARCH, search)
    # Option B too: a refused program set falls back to the search's.
    assert st.choose(w, search, program, True, allowed) == (st.SEARCH, search)


# --------------------------------------------------------------------------- the log
def test_the_decision_log_records_what_the_guard_held_back_on_each_set():
    p = resting_league()
    built = built_of(p)
    out = sm.moves_payload(built)
    entry = season_decisions.moves_entry(built, out, datetime(2026, 10, 26, 12, tzinfo=UTC))
    week, three = entry["sets"]
    held = out["recommended"]["week"]["season_guard"]
    assert week["season_guard"] == {
        "held_back": True,
        "moves": [
            {
                "add": 10,
                "drop": 3,
                "from": WEEKS[0][0].isoformat(),
                "gain": held["moves"][0]["marginal"],
                "ros": held["moves"][0]["ros"]["value"],
            }
        ],
        "gain": held["gain"],
        "ros": held["ros"],
    }
    assert three["season_guard"] == {"held_back": False}
    # The recommended set is the guarded one, flagged as the log flags it.
    assert [(m["add"], m["drop"], m["season_costly"]) for m in week["moves"]] == [(11, 3, False)]
    assert season_decisions.guard_record(None) is None
