"""The moves search's pool takes the adds the season guard admits (#424): the best ``POOL`` by
single-move gain, then the best ``GUARD_POOL`` by their best single move the guard admits,
without repeating one. Without a guard the pool is the ``POOL`` alone. The strategy run takes the
same list after its own pool, and the decision log counts what each list gave. Every league here
is made up (``test_moves``'s and ``test_season_guard``'s fixtures)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.api import season_moves as sm
from pickandroll.api import season_strategy as ss
from pickandroll.season import moves as mv

from .test_moves import WEEKS, build, player, rates, schedule
from .test_season_guard import blocking_league, built_of, resting_league

#: The streamers who crowd the holder out of the pool: all of them gain more on the week than the
#: holder (11), and every move of theirs costs the season.
STREAMERS = (10, *range(12, 12 + sm.POOL - 1))


def crowded_league() -> mv.MoveProblem:
    """``resting_league`` with ``POOL`` streamers: each plays four games this week and none after
    (the guard refuses every move of theirs), so the holder (11), the one add the guard admits,
    ranks below the pool on the week."""
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
    cands = [*(player(k, "STR") for k in STREAMERS), player(11, "HLD")]
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(1.5), 11: rates(1.2)}
    rate |= {k: rates(1.0) for k in STREAMERS}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.1), 21: rates(1.0), 22: rates(0.9)}
    p = build(roster, cands, rate, sched, opponent, [opponent])
    return replace(p, season_end=WEEKS[3][6])


def _swaps(gains: dict[int, list[tuple[int | None, float]]]) -> dict[int, list[mv.SwapGain]]:
    return {c: [mv.SwapGain(d, g) for d, g in rows] for c, rows in gains.items()}


# --------------------------------------------------------------------------- the helper
def test_the_pool_is_the_best_by_single_move_then_the_adds_the_guard_admits():
    # Forty adds; the guard refuses every one of the top 30's best moves (drop 100), admits their
    # second (drop 101) and every move of the ten below them.
    swaps = _swaps(
        {c: [(100, 1.0 - 0.01 * c), (101, 0.5 - 0.01 * c)] for c in range(1, 41)}
        | {41: [(100, 0.005)]}
    )

    def allowed(moves):
        return all(not (m.add <= 30 and m.drop == 100) for m in moves)

    pool, guarded = sm.pool_for(swaps, allowed)
    # Today's 30 first, in their order; then the ten below them the guard admits.
    assert pool.players == tuple(range(1, 41))
    assert (pool.size, pool.admitted) == (30, 10)
    assert pool.counts() == {"size": 30, "admitted": 10}
    # The guard's list: the ten below on their best move, then the top adds on their admitted
    # second drop, best first, 30 in all; an admitted move under MIN_GAIN (41) never joins.
    assert [c for c, _ in guarded] == [*range(31, 41), *range(1, 21)]
    assert guarded[0] == (31, mv.SwapGain(100, pytest.approx(0.69)))
    assert guarded[10] == (1, mv.SwapGain(101, pytest.approx(0.49)))
    assert 41 not in pool.players


def test_without_a_guard_the_pool_is_todays_thirty_exactly():
    swaps = _swaps({c: [(100, 1.0 - 0.01 * c)] for c in range(1, 41)})
    pool, guarded = sm.pool_for(swaps, None)
    assert pool.players == tuple(sm.ranked_of(swaps)[: sm.POOL]) == tuple(range(1, 31))
    assert (pool.size, pool.admitted, guarded) == (30, 0, [])


def test_the_guards_list_never_repeats_an_add_already_in_the_pool():
    swaps = _swaps({c: [(100, 1.0 - 0.01 * c)] for c in range(1, 41)})
    pool, guarded = sm.pool_for(swaps, lambda moves: True)
    # The guard admits every move: its list is the pool's own top 30, and nothing is added.
    assert [c for c, _ in guarded] == list(range(1, 31))
    assert (pool.players, pool.admitted) == (tuple(range(1, 31)), 0)


# --------------------------------------------------------------------------- the payload
def test_an_add_below_the_pool_the_guard_admits_is_recommended_when_it_refuses_the_top_30():
    p = crowded_league()
    built = built_of(p)
    ev = mv.Evaluator(p)
    swaps = mv.single_swaps(ev, "week")
    ranked = sm.ranked_of(swaps)
    # The holder ranks below the pool, and the guard refuses every move of the 30 above him.
    assert ranked.index(11) >= sm.POOL and set(ranked[: sm.POOL]) == set(STREAMERS)
    allowed = mv.season_guard(sm.guard_ros(built))
    assert not any(allowed((mv.Move(c, g.drop),)) for c in STREAMERS for g in swaps[c])
    # Today's pool alone offers nothing.
    before = mv.recommend(ev, "week", ranked[: sm.POOL], min_gain=sm.MIN_GAIN, allowed=allowed)
    assert before.moves == ()

    out = sm.moves_payload(built)
    week = out["recommended"]["week"]
    assert [(x["add"], x["drop"]) for x in week["moves"]] == [(11, 3)]
    assert out["search"]["pools"]["week"] == {"size": sm.POOL, "admitted": 1}
    assert out["search"]["guard_pool"] == sm.GUARD_POOL
    [listed] = out["search"]["guarded"]["week"]
    assert (listed["player"], listed["drop"]) == (11, 3)
    # The unguarded solve behind held_back searched the same pool: a streamer for 3, held back.
    guard = week["season_guard"]
    assert guard["held_back"] is True
    [held] = guard["moves"]
    assert held["add"] in STREAMERS and held["drop"] == 3


def test_without_the_guard_the_payloads_pool_is_todays_and_nothing_is_listed():
    p = crowded_league()
    out = sm.moves_payload(built_of(p, scorer=None))
    assert out["search"]["pools"] == {
        "week": {"size": sm.POOL, "admitted": 0},
        "three": {"size": out["search"]["pools"]["three"]["size"], "admitted": 0},
    }
    assert out["search"]["guarded"] == {"week": [], "three": []}
    # The unguarded set: a streamer for 3.
    [move] = out["recommended"]["week"]["moves"]
    assert move["add"] in STREAMERS and move["drop"] == 3


@pytest.mark.parametrize("size", [1, 2, sm.POOL])
@pytest.mark.parametrize("fixture", ["crowded", "resting", "blocking"])
def test_the_union_is_never_worse_than_todays_pool_under_the_guard(monkeypatch, size, fixture):
    monkeypatch.setattr(sm, "POOL", size)
    if fixture == "blocking":
        p, _, built = blocking_league()
    else:
        p = crowded_league() if fixture == "crowded" else resting_league()
        built = built_of(p)
    ev = mv.Evaluator(p)
    allowed = mv.season_guard(sm.guard_ros(built))
    for key in sm.HORIZONS:
        swaps = mv.single_swaps(ev, key)
        today = sm.ranked_of(swaps)[:size]
        pool, _ = sm.pool_for(swaps, allowed)
        assert pool.players[: pool.size] == tuple(today)
        old = mv.recommend(ev, key, today, min_gain=sm.MIN_GAIN, allowed=allowed)
        new = mv.recommend(ev, key, list(pool.players), min_gain=sm.MIN_GAIN, allowed=allowed)
        old_v = ev.value(key, [pm.move for pm in old.moves])
        new_v = ev.value(key, [pm.move for pm in new.moves])
        assert new_v >= old_v - mv.EPS
        assert allowed([pm.move for pm in new.moves])


def test_the_decision_log_counts_the_adds_each_list_gave():
    from datetime import UTC, datetime

    from pickandroll.api import season_decisions

    built = built_of(replace(crowded_league(), plan_floor=99.0))
    out = sm.moves_payload(built)
    entry = season_decisions.moves_entry(built, out, datetime(2026, 11, 18, 12, tzinfo=UTC))
    assert entry["pool"]["size"] == sm.POOL
    assert entry["pool"]["pools"] == out["search"]["pools"]
    assert entry["pool"]["pools"]["week"]["admitted"] == 1


# --------------------------------------------------------------------------- the strategy
def test_the_strategy_pool_appends_the_adds_the_guard_admits():
    p = crowded_league()
    built = built_of(p)
    answer = sm.moves_payload(built)
    assert ss.guarded_of(answer)["week"] == {11: answer["search"]["guarded"]["week"][0]["gain"]}
    # A pool of one: the week's best by single move, a streamer (the three weeks' best is the
    # holder, so a larger pool would take him on its own).
    run = ss.Run(("k",), built, lambda: answer, ss.Settings(pool=1, weights=("week",)), 1)
    run.run()
    out = run.payload()
    assert out["status"] == "solved", out["error"]
    # The pool setting's candidate first, then the holder from the guard's list.
    [first, added] = out["pool"]
    assert first in STREAMERS and added == 11
    assert out["pool_counts"] == {"size": 1, "admitted": 1}
    [point] = out["points"]
    assert [(m["add"], m["drop"]) for m in point["moves"]] == [(11, 3)]


def test_without_a_guard_the_strategy_pool_is_the_pool_setting_alone():
    p = crowded_league()
    built = built_of(p, scorer=None)
    answer = sm.moves_payload(built)
    run = ss.Run(("k",), built, lambda: answer, ss.Settings(pool=1, weights=("week",)), 1)
    run.run()
    out = run.payload()
    assert out["status"] == "solved", out["error"]
    [first] = out["pool"]
    assert first in STREAMERS
    assert out["pool_counts"] == {"size": 1, "admitted": 0}


def test_an_answer_made_before_the_guards_list_gives_the_strategy_nothing_to_append():
    assert ss.guarded_of({"search": {"pool": 30}}) == {"week": {}, "three": {}}
    assert ss.guarded_of({}) == {"week": {}, "three": {}}
