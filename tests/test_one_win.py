"""A league whose standings count one win per matchup (#397, the user's ruling 2026-11-15): its
moves and its crowded-day lineups are judged on the odds of winning the matchup, with the same
horizon weights as before (the week plus ``three_weight`` times the next three). A league where
each category counts, or whose format is not known, is judged as before.

Every league here is made up (``test_moves``'s and ``test_lineup_win``'s fixtures); the outcomes
are set by construction.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import lineup as lu
from pickandroll.season import moves as mv
from pickandroll.season import plans as pl
from pickandroll.season import stream as st
from pickandroll.season import weekly as wk
from pickandroll.season.state import EACH_CATEGORY, ONE_WIN
from tests.test_lineup_win import MON, SO_FAR, p, win
from tests.test_lineup_win import line as day_line
from tests.test_moves import COUNTING, WEEKS, build, player, rates, schedule
from tests.test_season import LEAGUE, season_client, strategy_league

FIRST = WEEKS[0][0]


def line(pts: float, reb: float, ast: float) -> dict[str, float]:
    return rates(1.0) | {"pts": pts, "reb": reb, "ast": ast}


def league(**extra):
    """Three of mine level with the opponent's three in points, rebounds and assists, and two
    adds for my third player: a scorer (10) who wins points for sure and gives up rebounds and
    assists, and a slightly better all-round player (11). The scorer adds more expected
    categories; the all-round player adds more odds of winning the week."""
    sched = schedule({"MIN": list(range(28))})
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate = {k: line(10, 5, 3) for k in (1, 2, 3, 20, 21, 22)}
    rate |= {10: line(30, 3.5, 2.1), 11: line(10, 5.2, 3.12)}
    cands = [player(10, "MIN"), player(11, "MIN")]
    limit = [mv.AddLimit(w[0], w[6], 1) for w in WEEKS]
    return build(
        roster, cands, rate, sched, opponent, [opponent], cats=COUNTING, limits=limit, **extra
    )


SCORER, ALL_ROUND = mv.Move(10, 3), mv.Move(11, 3)


def evs(p):
    return mv.Evaluator(p), mv.Evaluator(replace(p, one_win=True))


def test_one_win_ranks_the_move_that_raises_the_odds_over_the_one_that_adds_categories():
    p = league()
    cats, one = evs(p)
    # The scorer adds more expected categories but lowers the odds; the all-round player raises
    # them.
    assert cats.gain("week", [SCORER]) > cats.gain("week", [ALL_ROUND]) > 0
    assert one.gain("week", [SCORER]) < 0 < one.gain("week", [ALL_ROUND])
    for key in ("week", "three"):
        swaps = {k: g[0].gain for k, g in mv.single_swaps(one, key).items() if g}
        assert max(swaps, key=swaps.get) == 11
        swaps = {k: g[0].gain for k, g in mv.single_swaps(cats, key).items() if g}
        assert max(swaps, key=swaps.get) == 10
        # The recommended set under one add a week: the odds' move, and the categories' as today.
        assert [pm.move.add for pm in mv.recommend(one, key, [10, 11]).moves] == [11]
        assert [pm.move.add for pm in mv.recommend(cats, key, [10, 11]).moves] == [10]


def test_a_one_win_weeks_value_is_its_matchup_odds_summed_over_the_weeks():
    p = league()
    cats, one = evs(p)
    for key in ("week", "three"):
        for moves in ([], [SCORER], [ALL_ROUND]):
            odds = cats.odds(key, moves)
            won = sum(sum(wk.matchup_won(o) for o in w) / len(w) for w in odds)
            each = sum(sum(wk.expected_won(o) for o in w) / len(w) for w in odds)
            assert one.value(key, moves) == pytest.approx(won)
            # Each category counting (or the format unknown): expected categories, as before.
            assert cats.value(key, moves) == pytest.approx(each)
    # The headline odds the Moves card shows are the value itself on this week.
    assert sm.matchup_odds(one, "week", [ALL_ROUND]) == pytest.approx(
        one.value("week", [ALL_ROUND])
    )
    # A playoff week scores on the odds in both kinds of league, and they agree.
    for weight in (0.0, pl.THREE_WEIGHT):
        both = [sm.plan_value(weight, True)(ev, [ALL_ROUND]) for ev in (cats, one)]
        assert both[0] == pytest.approx(both[1]) == pytest.approx(one.value("week", [ALL_ROUND]))


def test_the_measure_is_named_by_the_problem():
    p = league()
    assert mv.measure_of(p) == mv.CATEGORIES
    assert mv.measure_of(replace(p, one_win=True)) == mv.MATCHUP
    assert mv.measure_of(replace(p, points={"pts": 1.0})) == mv.POINTS


def test_a_one_win_plans_score_floor_and_queue_are_on_the_odds():
    p = replace(league(), plan_floor=st.PLAN_FLOOR_CATS)
    cats, one = evs(p)
    q = one.problem
    # The floor: 3 points of odds in a one-win league whatever the categories knob says.
    assert st.floor_of(q) == st.PLAN_FLOOR_ODDS == pl.PLAYOFF_FLOOR == 0.03
    assert pl.gate_floor(q) == pl.gate_floor(q, True) == 0.03
    assert st.floor_of(p) == st.PLAN_FLOOR_CATS
    # The score: the week's odds plus three_weight times the three weeks' odds.
    w = pl.THREE_WEIGHT
    for move in (SCORER, ALL_ROUND):
        assert pl.score(one, [move], w) == pytest.approx(
            one.gain("week", [move]) + w * one.gain("three", [move])
        )
    plans = [pl.WeekPlan(pl.SEARCH, (pl.Step(m, FIRST, {}),), (), {}) for m in (SCORER, ALL_ROUND)]
    # Against no moves: the one-win queue takes the all-round player's plan, the categories queue
    # the scorer's, each beating the empty set by its floor.
    assert pl.score(one, [ALL_ROUND], w) > pl.PLAYOFF_FLOOR
    assert pl.score(cats, [SCORER], w) > st.PLAN_FLOOR_CATS
    assert pl.for_queue(one, plans, [], w).moves == (ALL_ROUND,)
    assert pl.for_queue(cats, plans, [], w).moves == (SCORER,)


def test_a_cleared_players_drop_is_chosen_on_the_odds_in_a_one_win_league():
    """The cleared player (4) comes back in place of one of mine: on the categories the scorer (3)
    stays and a level player goes; on the odds the scorer goes."""
    sched = schedule({"MIN": list(range(28))})
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate = {k: line(10, 5, 3) for k in (1, 2, 10, 20, 21, 22)}
    rate |= {3: line(30, 3.5, 2.1), 4: line(10, 5.1, 3.06)}
    back = (4, Player(4, "Back", "MIN", ("C",)))
    q = build(
        roster,
        [player(10, "MIN")],
        rate,
        sched,
        opponent,
        [opponent],
        cats=COUNTING,
        held=[back],
        held_slots={4: "IL"},
    )
    assert mv.cleared(q) == [(4, "IL")]
    assert mv.choose_activation(q, sm.three_value) == {4: 1}
    assert mv.choose_activation(replace(q, one_win=True), sm.three_value) == {4: 3}


# --------------------------------------------------------------------------- the lineup (#314)
#: Points won for sure, assists a long way behind, rebounds a little ahead: a passer adds the
#: most expected categories, a rebounder the most odds of taking the second category the week
#: needs.
THEIRS = {"pts": (100.0, 5.0), "ast": (55.0, 3.0), "reb": (48.0, 3.0)}
PASSER = day_line(pts=6.0, ast=6.0)
REBOUNDER = day_line(pts=6.0, reb=4.0)


def scored(rates, key):
    week = wk.team_week({key: wk.PlayerWeek(1, 1)}, rates, None)
    odds = wk.odds_of(wk.finals(week, SO_FAR, ("pts", "ast", "reb")), THEIRS, ("pts", "ast", "reb"))
    return wk.expected_won(odds), wk.matchup_won(odds)


def test_a_one_win_crowded_day_starts_the_player_with_the_better_odds():
    rates = {2: PASSER, 3: REBOUNDER}
    (e2, o2), (e3, o3) = scored(rates, 2), scored(rates, 3)
    assert e2 > e3 and o3 - o2 > lu.TIE_ODDS
    roster = [p(2, "PG"), p(3, "PG")]
    value = {2: 5.0, 3: 4.0}
    kw = {"rates": rates, "value": value, "theirs": THEIRS}
    assert win(roster, ["Util"], **kw) == {MON: {2: "Util"}}
    assert win(roster, ["Util"], one_win=True, **kw) == {MON: {3: "Util"}}
    # Yahoo's starters as read do not hold against a real gain on the odds.
    assert win(roster, ["Util"], one_win=True, yahoo={MON: [2]}, **kw) == {MON: {3: "Util"}}


def test_a_one_win_near_tie_on_the_odds_keeps_yahoos_starters():
    rates = {3: REBOUNDER, 4: day_line(pts=6.0, reb=4.05)}
    (_, o3), (_, o4) = scored(rates, 3), scored(rates, 4)
    assert 0 < o4 - o3 < lu.TIE_ODDS
    roster = [p(3, "PG"), p(4, "PG")]
    kw = {"rates": rates, "value": {3: 5.0, 4: 4.0}, "theirs": THEIRS, "one_win": True}
    assert win(roster, ["Util"], yahoo={MON: [3]}, **kw) == {MON: {3: "Util"}}
    assert win(roster, ["Util"], yahoo={MON: [4]}, **kw) == {MON: {4: "Util"}}
    # TIE_ODDS is the categories' TIE converted at a third of a category's change.
    assert lu.TIE_ODDS == pytest.approx(lu.TIE / 3, abs=1e-12)


# --------------------------------------------------------------------------- the build
@pytest.mark.parametrize(
    ("h2h", "measure"), [(ONE_WIN, "matchup"), (EACH_CATEGORY, "categories"), (None, "categories")]
)
def test_the_build_reads_the_format_off_the_seasons_settings(tmp_path, monkeypatch, h2h, measure):
    real = sm.build
    seen = []

    def build_as(season, *args, **kw):
        built = real(replace(season, settings=replace(season.settings, h2h=h2h)), *args, **kw)
        seen.append(built.problem.one_win)
        return built

    monkeypatch.setattr(sm, "build", build_as)
    with season_client(tmp_path) as client:
        strategy_league(client)
        r = client.get(f"/seasons/{LEAGUE}/moves")
        assert r.status_code == 200, r.text
        assert r.json()["measure"] == measure
    assert seen and set(seen) == {h2h == ONE_WIN}


def test_the_strategy_panel_values_a_one_win_league_on_categories():
    from pickandroll.api import season_strategy as ss

    p = replace(league(), one_win=True)
    built = sm.Built(p, {"key": "bbm"}, {}, {}, 0)
    run = ss.Run(("k",), built, dict, ss.Settings(), 1)
    assert run.built.problem.one_win is False
    assert built.problem.one_win is True
