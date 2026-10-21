"""The strategy engine (#110): the weighted value, the pool, the linear program's totals and
curves against the move model's evaluator, its constraints (locks, the weekly limits, a claim's
clear date) and status, the choice between the two solvers, and a points league. Every league
here is made up (``test_moves``'s fixtures); the outcomes are set by construction."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pulp
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import strategy as st
from pickandroll.season import weekly as wk

from .test_moves import WEEKS, build, deep_league, streaming_league

WEEKS_LEFT = 10


def limited(**kw):
    """The deep league with two adds this week."""
    roster, cands, rate, sched, opponent, field = deep_league()
    kw.setdefault("limits", [mv.AddLimit(WEEKS[0][0], WEEKS[0][6], 2)])
    return build(roster, cands, rate, sched, opponent, field, **kw), [c for c, _ in cands]


# --------------------------------------------------------------------------- the value
def test_the_weights_run_from_this_week_to_the_rest_of_the_season():
    ws = st.weights(21)
    assert [w.key for w in ws] == list(st.WEIGHT_KEYS)
    lam = {w.key: w.lam for w in ws}
    assert lam["week"] == 1.0 and lam["season"] == 0.0
    assert lam["natural"] == 0.5 and [w.key for w in ws if w.natural] == ["natural"]
    # This week weighs as much as the 21 weeks after it together.
    assert lam["even"] * 1 == pytest.approx((1 - lam["even"]) * 21)
    # The last week has nothing after it.
    assert [w.key for w in st.weights(0)] == ["week"]


def test_the_weighted_value_is_this_week_and_a_later_week_times_the_weeks_left():
    p, _ = limited()
    ev = mv.Evaluator(p)
    moves = [mv.Move(10, 2), mv.Move(14, 3)]
    for lam in (1.0, 0.7, 0.5, 0.0):
        w = st.Weighted(ev, lam, WEEKS_LEFT)
        later = ev.value("three", moves) / 3
        assert w.value(st.WEIGHTED, moves) == pytest.approx(
            lam * ev.value("week", moves) + (1 - lam) * WEEKS_LEFT * later
        )
        assert w.gain(st.WEIGHTED, moves) == pytest.approx(
            w.combine(ev.gain("week", moves), ev.gain("three", moves))
        )
        # The move model's own horizons pass through.
        assert w.value("week", moves) == ev.value("week", moves)
    assert st.Weighted(ev, 0.5, WEEKS_LEFT).season(3.0) == pytest.approx(WEEKS_LEFT)


def test_the_pool_takes_the_best_of_each_horizon_in_turn():
    gains = {"week": {1: 0.9, 2: 0.5, 3: 0.1, 4: -0.2}, "three": {3: 2.0, 1: 1.0, 5: 0.4}}
    assert st.pool_of(gains, 3) == [1, 3, 2]
    assert st.pool_of(gains, 10) == [1, 3, 2, 5, 4]


# --------------------------------------------------------------------------- the program
#: Categories where every start helps (no turnovers), with a percentage.
HELPED = ("fg_pct", "threes", "pts", "reb", "ast")


def fixed_roster(**kw):
    """The streaming league with no candidate: three of mine on three starting slots, so every
    game starts as the evaluator plays them, my shooters above the opponent's percentage, so the
    program starts every game too (it may bench a player whose start costs a category)."""
    roster, _, rate, sched, opponent, field = streaming_league()
    for k, _ in roster:
        rate[k] = {**rate[k], "fgm": 5.0}
    so_far = {"pts": 31.0, "threes": 2.0, "fgm": 12.0, "fga": 25.0}
    return build(roster, [], rate, sched, opponent, field, cats=HELPED, so_far=so_far, **kw)


def test_on_a_fixed_roster_the_programs_totals_are_the_season_views():
    p = fixed_roster()
    ev = mv.Evaluator(p)
    cv = st.curves(ev)
    m = st.solve_milp(p, cv, [], 0.5, WEEKS_LEFT)
    assert m.status == st.OPTIMAL and m.moves == ()
    so_far = p.horizons["week"][0].so_far
    week = ev.mine("week", ())[0].totals
    final = {s: so_far.get(s, 0.0) + week.get(s, 0.0) for s in wk.STATS}
    later = ev.mine("three", ())
    typical = {s: sum(t.totals[s] for t in later) / len(later) for s in wk.STATS}
    assert cv.week_ref["fg_pct"] == pytest.approx(0.5)
    for c in HELPED:
        assert m.totals["week"][c] == pytest.approx(st._total(final, c, cv.week_ref.get(c)))
        assert m.totals["later"][c] == pytest.approx(st._total(typical, c, cv.later_ref.get(c)))


def test_the_piecewise_objective_is_close_to_the_exact_odds_this_week():
    p = fixed_roster()
    ev = mv.Evaluator(p)
    m = st.solve_milp(p, st.curves(ev), [], 1.0, WEEKS_LEFT)
    # Six breaks over the normal: within 0.02 of each category's exact odds.
    assert m.model["week"] == pytest.approx(ev.base["week"], abs=0.02 * len(HELPED))


def test_this_weeks_program_beats_the_best_single_move():
    p, pool = limited()
    ev = mv.Evaluator(p)
    m = st.solve_milp(p, st.curves(ev), pool, 1.0, WEEKS_LEFT)
    best = max(g[0].gain for g in mv.single_swaps(ev, "week").values() if g)
    assert m.status == st.OPTIMAL and len(m.moves) == 2
    assert ev.gain("week", m.moves) > best


@pytest.mark.parametrize("weight", st.weights(WEEKS_LEFT), ids=lambda w: w.key)
def test_the_recommended_set_is_the_best_of_every_set_of_two_moves(weight):
    p, pool = limited()
    ev = mv.Evaluator(p)
    w = st.Weighted(ev, weight.lam, WEEKS_LEFT)
    search = mv.search(w, st.WEIGHTED, pool)
    m = st.solve_milp(p, st.curves(ev), pool, weight.lam, WEEKS_LEFT, start=search)
    _, shown = st.choose(w, search, m)
    singles = [mv.Move(c, d) for c in pool for d in mv.drop_options(p)]
    sets = [(), *((x,) for x in singles), *itertools.combinations(singles, 2)]
    best = max(w.value(st.WEIGHTED, s) for s in sets if mv.feasible(p, s))
    assert w.value(st.WEIGHTED, shown) == pytest.approx(best)
    assert w.value(st.WEIGHTED, shown) >= w.value(st.WEIGHTED, search) - 1e-12


def test_locks_and_each_weeks_add_limit_hold():
    p, pool = limited()
    cv = st.curves(mv.Evaluator(p))
    for lam in (1.0, 0.5, 0.0):
        free = st.solve_milp(p, cv, pool, lam, WEEKS_LEFT)
        assert free.status == st.OPTIMAL and mv.feasible(p, free.moves) and len(free.moves) <= 2
        locked = {m.drop for m in free.moves}
        kept = st.solve_milp(p, cv, pool, lam, WEEKS_LEFT, keep=locked)
        assert locked and not locked & {m.drop for m in kept.moves}
    # No adds left this week: nothing; every claim clearing next Monday uses next week's four.
    week1, week2 = WEEKS[0], WEEKS[1]
    shut = [mv.AddLimit(week1[0], week1[6], 0), mv.AddLimit(week2[0], week2[6], 4)]
    p, pool = limited(limits=shut)
    assert st.solve_milp(p, st.curves(mv.Evaluator(p)), pool, 0.0, WEEKS_LEFT).moves == ()
    p, pool = limited(limits=shut, effective={c: week2[0] for c in pool})
    later = st.solve_milp(p, st.curves(mv.Evaluator(p)), pool, 0.0, WEEKS_LEFT)
    assert len(later.moves) > 2 and mv.feasible(p, later.moves)


def test_a_drop_for_a_claim_keeps_his_games_until_it_clears():
    # The streamer's claim clears on Thursday: the player he replaces keeps Monday and Wednesday.
    roster, cands, rate, sched, opponent, field = streaming_league()
    thursday = WEEKS[0][3]
    p = build(
        roster, cands, rate, sched, opponent, field, effective={10: thursday, 11: WEEKS[0][0]}
    )
    ev = mv.Evaluator(p)
    m = st.solve_milp(p, st.curves(ev), [10], 1.0, WEEKS_LEFT, keep={1, 2})
    assert m.moves == (mv.Move(10, 3),)
    mine = ev.mine("week", m.moves)[0]
    assert mine.players[3].started == 2 and mine.players[10].started == 2
    for c in p.cats:
        assert m.totals["week"][c] == pytest.approx(mine.totals[c])


# --------------------------------------------------------------------------- status and choice
class _Model:
    """A solved model as ``_status`` reads it."""

    def __init__(self, status, sol_status):
        self.solverModel = type("H", (), {"getModelStatus": lambda _self: status})()
        self.sol_status = sol_status


def test_highs_says_whether_a_solve_finished_and_pulp_does_not():
    import highspy

    hs = highspy.HighsModelStatus
    assert st._status(_Model(hs.kOptimal, pulp.LpSolutionOptimal)) == st.OPTIMAL
    # PuLP calls this "Optimal": HiGHS stopped at the time limit with a set.
    assert st._status(_Model(hs.kTimeLimit, pulp.LpSolutionIntegerFeasible)) == st.TIME_LIMITED
    assert st._status(_Model(hs.kTimeLimit, pulp.LpSolutionNoSolutionFound)) == st.FAILED


def test_a_solve_cut_short_shows_the_searchs_set():
    p, pool = limited()
    ev = mv.Evaluator(p)
    w = st.Weighted(ev, 0.5, WEEKS_LEFT)
    search = mv.search(w, st.WEIGHTED, pool)
    m = st.solve_milp(p, st.curves(ev), pool, 0.5, WEEKS_LEFT, start=search, time_limit=1e-6)
    assert m.status in {st.TIME_LIMITED, st.FAILED}
    assert st.choose(w, search, m) == (st.SEARCH, search)
    assert st.choose(w, search, None) == (st.SEARCH, search)


def test_the_choice_takes_the_better_set_or_the_programs_alone():
    p, pool = limited()
    ev = mv.Evaluator(p)
    w = st.Weighted(ev, 1.0, WEEKS_LEFT)
    good = mv.search(w, st.WEIGHTED, pool)
    weak = (mv.Move(13, 2),)
    assert w.value(st.WEIGHTED, weak) < w.value(st.WEIGHTED, good)

    def milp(moves, status=st.OPTIMAL):
        return st.Milp(tuple(moves), status, 0.1, {})

    assert st.choose(w, weak, milp(good)) == (st.MILP, good)
    assert st.choose(w, good, milp(weak)) == (st.SEARCH, good)
    # The same adds and drops leaving on the same days, paired otherwise: both.
    swapped = tuple(mv.Move(a.add, b.drop) for a, b in zip(good, good[::-1], strict=True))
    assert st.choose(w, good, milp(swapped))[0] == st.BOTH
    # Option B: the program's set stands when it solved, even if worse; the search's is its
    # fallback for a solve that hit the limit.
    assert st.choose(w, good, milp(weak), program_only=True) == (st.MILP, weak)
    assert st.choose(w, good, milp(weak, st.TIME_LIMITED), program_only=True) == (st.SEARCH, good)


def test_first_order_values_rank_a_better_line_higher():
    p, pool = limited()
    ev = mv.Evaluator(p)
    m = st.solve_milp(p, st.curves(ev), pool, 0.5, WEEKS_LEFT)
    fo = st.first_order(p, st.curves(ev), m, 0.5, WEEKS_LEFT)
    # Same team, same games: candidates 10 and 13 differ only by their line.
    assert fo[10] > fo[13] > 0
    assert set(fo) == {k for k, _ in (*p.roster, *p.candidates)}


# --------------------------------------------------------------------------- a points league
POINTS = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}


def test_in_a_points_league_the_gains_are_in_matchups_won():
    roster, cands, rate, sched, opponent, field = streaming_league()
    p = build(roster, cands, rate, sched, opponent, field)
    slots, value = p.slots, p.value

    def project(team, days, this_week):
        return wk.project_week(team, rate, days, sched, slots, value, this_week, points=POINTS)

    week = p.horizons["week"][0]
    spans = {
        "week": (replace(week, opponents=(project(opponent, week.days, True),)),),
        "three": tuple(
            replace(sp, opponents=tuple(project(t, sp.days, False) for t in field))
            for sp in p.horizons["three"]
        ),
    }
    p = replace(p, cats=(wk.FPTS,), points=POINTS, horizons=spans)
    ev = mv.Evaluator(p)
    cv = st.curves(ev)
    assert set(cv.week) == set(cv.later) == {wk.FPTS}
    for lam in (1.0, 0.5):
        w = st.Weighted(ev, lam, WEEKS_LEFT)
        search = mv.search(w, st.WEIGHTED, [10, 11])
        m = st.solve_milp(p, cv, [10, 11], lam, WEEKS_LEFT, start=search)
        _, shown = st.choose(w, search, m)
        assert m.status == st.OPTIMAL and shown
        # One matchup a week: this week's value is a probability.
        assert 0.0 <= ev.value("week", shown) <= 1.0
        assert ev.value("three", shown) <= 3.0
    # The streamer adds this week's points.
    m = st.solve_milp(p, cv, [10, 11], 1.0, WEEKS_LEFT, keep={1, 2})
    assert (
        m.totals["week"][wk.FPTS]
        > st.solve_milp(p, cv, [], 1.0, WEEKS_LEFT).totals["week"][wk.FPTS]
    )
