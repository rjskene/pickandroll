"""Streaming plans (#136): dated moves on the move model, the stream spots, the planner's
search against a brute force over every path, and its rules (claims from their clear date, one
stint per player, the adds left, the daily cap, a start slot). Every league here is made up."""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from pickandroll.season import moves as mv
from pickandroll.season import stream as st
from pickandroll.season import weekly as wk
from tests.test_moves import WEEKS, build, player, rates, schedule

THU = WEEKS[0][3]
DAYS = WEEKS[0][3:]


def stream_league(later: tuple[str, ...] = ("LAT",), **kw):
    """Thursday to Sunday: two of mine who play every day and a third who plays Sunday alone;
    three free agents, one with Thursday and Friday, one with Saturday and Sunday, a weaker one
    with Friday to Sunday. Rest-of-season values put the third below the best add. In the weeks
    after, mine play every day and so do the free agents of the teams in ``later``."""
    every = [7 + d for d in range(21)]
    week = {"MIN": list(range(7)), "SUN": [6], "EAR": [3, 4], "LAT": [5, 6], "WIDE": [4, 5, 6]}
    sched = schedule(
        {t: days + (every if t in ("MIN", "SUN", *later) else []) for t, days in week.items()}
    )
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "SUN")]
    cands = [player(10, "EAR"), player(11, "LAT"), player(12, "WIDE")]
    rate = {1: rates(1.5), 2: rates(1.4), 3: rates(0.6), 10: rates(1.0), 11: rates(1.1)}
    rate |= {12: rates(0.7)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.3), 21: rates(1.2), 22: rates(1.1)}
    field = [opponent]
    problem = build(roster, cands, rate, sched, opponent, field, first_day=THU, **kw)
    season = {1: 2.0, 2: 1.8, 3: 0.2, 10: 0.5, 11: 0.6, 12: 0.4}
    problem = replace(problem, season_value=season)
    rule = mv.keep_rule(problem)
    return replace(problem, kept=rule.kept), rule


def per_game(problem: mv.MoveProblem) -> dict[int, float]:
    """The cheap score's per-game values: the line's points, as a scorer would rank them."""
    return {k: r["pts"] for k, r in problem.rates.items()}


def every_path(problem: mv.MoveProblem, occupant: int, adds: int) -> list[tuple[mv.Move, ...]]:
    """Every path for the spot: distinct candidates on strictly later days, each dropping the
    holder before, at most ``adds`` of them, none before his effective day."""
    out: list[tuple[mv.Move, ...]] = [()]
    cands = [k for k, _ in problem.candidates]
    days = problem.horizons["week"][0].days
    for n in range(1, adds + 1):
        for who in itertools.permutations(cands, n):
            for when in itertools.combinations(days, n):
                if any(problem.effective[k] > d for k, d in zip(who, when, strict=True)):
                    continue
                holders = [occupant, *who]
                out.append(tuple(mv.Move(who[i], holders[i], when[i]) for i in range(n)))
    return out


# --------------------------------------------------------------------------- dated moves
def test_a_dated_set_values_as_its_timeline():
    """A step that drops an earlier add: the week is project_week's with each add available
    from his step's day and each dropped player gone from it."""
    problem, _ = stream_league()
    sat = DAYS[2]
    moves = [mv.Move(10, 3, THU), mv.Move(11, 10, sat)]
    span = problem.horizons["week"][0]
    members = [*problem.roster, *((k, p) for k, p in problem.candidates if k in (10, 11))]
    expected = wk.project_week(
        members,
        problem.rates,
        span.days,
        problem.schedule,
        problem.slots,
        problem.value,
        True,
        points=None,
        no_games=problem.no_games,
        available_from={**problem.effective, 10: THU, 11: sat},
        gone_from={3: THU, 10: sat},
    )
    ev = mv.Evaluator(problem)
    assert ev.mine("week", moves)[0] == expected
    # 10 plays Thursday and Friday for the spot, 11 Saturday and Sunday; 3 never.
    assert expected.players[10].games == 2 and expected.players[11].games == 2
    assert expected.players[3].games == 0


def test_a_move_on_its_effective_day_is_the_undated_move():
    problem, _ = stream_league()
    ev = mv.Evaluator(problem)
    for key in ("week", "three"):
        assert ev.value(key, [mv.Move(11, 3, THU)]) == pytest.approx(
            ev.value(key, [mv.Move(11, 3)])
        )


def test_a_later_day_counts_from_that_day():
    problem, _ = stream_league()
    ev = mv.Evaluator(problem)
    sat = DAYS[2]
    week = ev.mine("week", [mv.Move(12, 3, sat)])[0]
    # 12 plays Friday to Sunday; from Saturday he plays two, and 3 is gone from Saturday.
    assert week.players[12].games == 2
    assert week.players[3].games == 0


def test_feasible_counts_each_step_against_its_week():
    problem, _ = stream_league(limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][-1], 1)])
    assert mv.feasible(problem, [mv.Move(10, 3, THU)])
    assert not mv.feasible(problem, [mv.Move(10, 3, THU), mv.Move(11, 10, DAYS[2])])


# --------------------------------------------------------------------------- stream spots
def test_stream_spots_are_below_the_best_add_and_kept_by_nothing():
    problem, rule = stream_league()
    assert rule.best_value == 0.6
    assert st.stream_spots(problem, rule) == [3]
    # A third player above the best add is not a stream spot; nor is one the rule keeps.
    lifted = replace(problem, season_value={**problem.season_value, 3: 0.9})
    assert st.stream_spots(lifted, mv.keep_rule(lifted)) == []
    kept = replace(rule, players={**rule.players, 3: replace(rule.players[3], bench=True)})
    assert st.stream_spots(problem, kept) == []


def test_stream_spots_take_the_weakest_two():
    problem, _ = stream_league()
    low = replace(problem, season_value={**problem.season_value, 1: 0.1, 2: 0.3})
    low_rule = mv.keep_rule(low)
    low = replace(low, kept=low_rule.kept)
    assert st.stream_spots(low, low_rule) == [1, 3]


# --------------------------------------------------------------------------- the search
def best_by_brute_force(ev: mv.Evaluator, adds: int) -> tuple[mv.Move, ...]:
    """Of every path for the spot, the best week among those no worse on the weeks after than
    keeping the occupant."""
    problem = ev.problem
    later = ev.value("three", ())
    allowed = [
        path
        for path in every_path(problem, 3, adds)
        if mv.feasible(problem, list(path)) and ev.value("three", path) >= later - mv.EPS
    ]
    return max(allowed, key=lambda path: ev.value("week", path))


def test_the_plan_is_the_best_path_by_brute_force():
    """Every path of up to two adds valued exactly: the planner's spot plan is the best."""
    problem, rule = stream_league(limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][-1], 2)])
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None and len(found.spots) == 1
    best = best_by_brute_force(ev, 2)
    assert ev.value("week", found.moves) == pytest.approx(ev.value("week", best))
    # Thursday-Friday's free agent, then Saturday-Sunday's: two adds, four games for the spot.
    assert found.steps == (mv.Move(10, 3, THU), mv.Move(11, 10, DAYS[2]))
    assert st.recommended(ev, found)


def test_one_add_left_buys_one_step():
    problem, rule = stream_league(limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][-1], 1)])
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None and len(found.steps) == 1
    best = best_by_brute_force(ev, 1)
    assert ev.value("week", found.moves) == pytest.approx(ev.value("week", best))


def test_a_plan_never_costs_the_weeks_after():
    """With no free agent playing after this week, any path leaves the spot worse there than
    the occupant, who plays every day: no step, though streaming would win the week."""
    problem, rule = stream_league(later=())
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None and found.steps == ()
    assert ev.value("week", (mv.Move(10, 3, THU), mv.Move(11, 10, DAYS[2]))) > ev.value("week", ())


def test_without_the_guard_the_plan_takes_the_best_week_whatever_it_costs_after():
    problem, rule = stream_league(later=())
    ev = mv.Evaluator(problem)
    free = st.plan(ev, rule, (), per_game(problem), guard=False)
    assert free is not None
    assert free.steps == (mv.Move(10, 3, THU), mv.Move(11, 10, DAYS[2]))
    assert ev.value("three", free.moves) < ev.value("three", ())


def test_the_payload_says_the_guard_refused_a_plan_and_what_it_would_buy():
    """The best week streams the spot but leaves it empty after: the plan is not recommended,
    and the payload gives the refused plan's steps, games and gain for the user to weigh."""
    from pickandroll.api.season_moves import Built, plan_payload

    problem, rule = stream_league(later=())
    ev = mv.Evaluator(problem)
    built = Built(problem, {"key": "bbm"}, {}, {}, 0, rule=rule, scorer={"points": {"pts": 1.0}})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(st, "PLAN_FLOOR_CATS", 0.0)
        out = plan_payload(built, ev, [], [])
    assert out is not None
    assert (out["recommended"], out["reason"], out["steps"]) == (False, "guard", [])
    guard = out["guard"]
    assert [(x["add"], x["drop"], x["from"], x["spot"]) for x in guard["steps"]] == [
        (10, 3, THU.isoformat(), 3),
        (11, 10, DAYS[2].isoformat(), 3),
    ]
    assert guard["spots"] == [3] and guard["games"] > out["games"]["set"]
    assert guard["gain"]["week"] > 0 > guard["gain"]["three"]
    # With the weeks after the occupant's to lose, a plan the guard keeps carries no reason.
    problem, rule = stream_league()
    ev = mv.Evaluator(problem)
    built = Built(problem, {"key": "bbm"}, {}, {}, 0, rule=rule, scorer={"points": {"pts": 1.0}})
    out = plan_payload(built, ev, [], [])
    assert out["recommended"] and (out["reason"], out["guard"]) == (None, None)


def test_the_set_keeps_the_adds_for_its_other_spots():
    """Two stream spots and two adds: the set spends one on each; planning the first spot
    cannot take the second's add, so the plan is never behind the set."""
    problem, _ = stream_league(limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][-1], 2)])
    low = replace(problem, season_value={**problem.season_value, 2: 0.1})
    rule = mv.keep_rule(low)
    low = replace(low, kept=rule.kept)
    assert st.stream_spots(low, rule) == [2, 3]
    ev = mv.Evaluator(low)
    against = (mv.Move(10, 2), mv.Move(11, 3))
    found = st.plan(ev, rule, against, per_game(low))
    assert found is not None and len(found.moves) <= 2
    for key in ("week", "three"):
        assert ev.value(key, found.moves) >= ev.value(key, against) - mv.EPS


def test_no_add_left_no_plan():
    problem, rule = stream_league(limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][-1], 0)])
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None and found.steps == ()
    assert not st.recommended(ev, found)


def test_a_claim_steps_in_from_its_clear_date():
    """The Thursday-Friday player is a claim clearing Friday: he holds the spot from Friday."""
    problem, rule = stream_league(effective={10: DAYS[1], 11: THU, 12: THU})
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None
    for step in found.steps:
        assert step.day >= problem.effective[step.add]
    assert all(s.add != 10 or s.day == DAYS[1] for s in found.steps)


def test_no_player_holds_the_spot_twice():
    """A scores Thursday and Saturday, B Friday: the best path by score would be A, B, A."""
    days = DAYS[:3]
    scores = {
        0: {d: 0.0 for d in days},
        1: {days[0]: 5.0, days[1]: 0.0, days[2]: 5.0},
        2: {days[0]: 0.0, days[1]: 4.0, days[2]: 0.0},
    }
    found = st.paths(days, 0, scores, {1: days[0], 2: days[0]}, 3, dict.fromkeys(days, 2))
    for p in found:
        adds = [m.add for m in p.steps]
        assert len(adds) == len(set(adds)) and 0 not in adds
        for prev, step in itertools.pairwise((mv.Move(0), *p.steps)):
            assert step.drop == prev.add
    # A alone for all three days beats switching to B and losing him.
    assert found[0].steps == (mv.Move(1, 0, days[0]),)


def test_paths_keep_to_the_adds_and_the_daily_room():
    days = DAYS
    scores = {0: {d: 0.0 for d in days}} | {
        k: {d: (1.0 if i == k - 1 else 0.0) for i, d in enumerate(days)} for k in range(1, 5)
    }
    earliest = dict.fromkeys(range(1, 5), days[0])
    room = dict.fromkeys(days, 2)
    best = st.paths(days, 0, scores, earliest, 4, room)[0]
    assert len(best.steps) == 4 and best.score == 4.0
    assert all(len(p.steps) <= 2 for p in st.paths(days, 0, scores, earliest, 2, room))
    # No room on Friday: whoever scores Friday can never start the spot that day.
    full = {**room, days[1]: 0}
    for p in st.paths(days, 0, scores, earliest, 4, full):
        assert all(m.day != days[1] for m in p.steps)


def test_the_daily_room_counts_the_base_moves():
    problem, _ = stream_league()
    base = [mv.Move(10, 1), mv.Move(11, 2)]
    room = st._room(problem, base, DAYS)
    assert room[THU] == 0 and all(room[d] == st.DAILY_CAP for d in DAYS[1:])


def test_a_holder_without_a_start_slot_scores_nothing():
    """A guard where my better guard plays scores nothing that day; the next day he starts."""
    sched = schedule({"MIN": list(range(28)), "PG": [3], "GRD": [3, 4], "SUN": [6]})
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "SUN", pos=("PG",))]
    roster.append(player(4, "PG", pos=("PG",)))
    cands = [player(13, "GRD", pos=("PG",))]
    rate = {k: rates(1.0) for k in (1, 2, 3, 4, 13, 20, 21, 22)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    value = {1: 3.0, 2: 3.0, 3: 0.5, 4: 2.0, 13: 1.0, 20: 1.0, 21: 1.0, 22: 1.0}
    problem = build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        [opponent],
        first_day=THU,
        slots=("C", "C", "PG"),
        value=value,
    )
    span = problem.horizons["week"][0]
    scores = st.day_scores(problem, span, (), 3, [13], {13: 1.0})
    assert scores[13][THU] == 0.0
    assert scores[13][DAYS[1]] == 1.0
    assert scores[13][DAYS[2]] == 0.0


# --------------------------------------------------------------------------- the plan
def test_the_base_leaves_the_stream_spot_to_the_plan():
    problem, rule = stream_league()
    ev = mv.Evaluator(problem)
    against = (mv.Move(11, 3),)
    found = st.plan(ev, rule, against, per_game(problem))
    assert found is not None
    assert found.base == () and found.against == against
    assert ev.value("week", found.moves) > ev.value("week", against)


def test_the_steps_gains_telescope_to_the_plan():
    problem, rule = stream_league()
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None and found.steps
    gains = st.step_gains(ev, found)
    for key in ("week", "three"):
        total = sum(g[key] for g in gains)
        assert total == pytest.approx(ev.value(key, found.moves) - ev.value(key, found.base))


def test_a_plan_inside_the_floor_is_not_recommended():
    problem, rule = stream_league()
    ev = mv.Evaluator(problem)
    found = st.plan(ev, rule, (), per_game(problem))
    assert found is not None
    gap = ev.value("week", found.moves) - ev.value("week", found.against)
    assert gap > 0
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(st, "PLAN_FLOOR_CATS", gap + 0.01)
        assert not st.recommended(ev, found)


def test_a_points_leagues_floor_is_on_the_win_odds_scale():
    """A points league's week is the matchup's win odds: the floor is the same share of it."""
    problem, _ = stream_league()
    assert st.floor_of(problem) == st.PLAN_FLOOR_CATS == 0.10
    points = replace(problem, points={"pts": 1.0}, cats=("fpts",))
    assert st.floor_of(points) == st.PLAN_FLOOR_POINTS == 0.01
