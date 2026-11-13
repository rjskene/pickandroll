"""The policy adapter (#172, PR 2b): the engine's own problem from a simulated state, the three
tiers, the executor and the day's lineup."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.season.sim import policy
from pickandroll.season.sim.state import SimState, initial
from tests.sim_league import KNOBS, make_setup


def built_for(setup, team=1, state=None, knobs=KNOBS, status=None):
    state = state or initial(setup)
    return policy.problem_of(setup, state, team, knobs, setup.projection, status or {}, {})


def test_knobs_are_checked_and_a_missing_one_refused():
    assert policy.check_knobs(KNOBS) == KNOBS
    with pytest.raises(KeyError):
        policy.check_knobs({k: v for k, v in KNOBS.items() if k != "daily_cap"})
    with pytest.raises(KeyError):
        policy.knob({}, "daily_cap")


def test_the_problem_mirrors_the_live_route():
    setup = make_setup()
    out = initial(setup).active(1)[0]
    built = built_for(setup, status={out: "O"})
    p = built.problem
    assert built.team == 1 and built.week.number == 1 and built.weeks_left == 5
    assert {k for k, _ in p.roster} == set(initial(setup).active(1))
    assert {k for k, _ in p.candidates} == set(setup.pool)
    # Free agents land tomorrow.
    assert set(p.effective.values()) == {setup.start + timedelta(1)}
    assert p.first_day == setup.start
    assert [h.this_week for h in p.horizons["week"]] == [True]
    assert len(p.horizons["three"]) == 3
    # The week's opponent is the pairing's; the field is everyone else.
    assert len(p.horizons["week"][0].opponents) == 1
    assert len(p.horizons["three"][0].opponents) == 3
    assert p.limits[0].adds == 4 and p.limits[1].adds == 4
    assert p.spots == 6 and p.held == ()
    assert p.season_end == setup.season_end
    assert p.daily_cap == 1
    assert dict(p.roster)[out].status == "O"
    # Adds already made this week come off the limit.
    used = SimState(setup.start, initial(setup).rosters, initial(setup).pool, {1: 3})
    assert built_for(setup, state=used).problem.limits[0].adds == 1


def test_an_add_is_charged_to_the_week_it_is_made_in_and_plays_the_next_day():
    """Yahoo charges a free-agent add to the week it is made in, whenever it lands: a move on
    Sunday spends the ending week's adds and plays from Monday; a midweek one spends this week's
    and plays tomorrow."""
    setup = make_setup()
    base = initial(setup)
    sunday = setup.calendar.weeks[0].end
    assert sunday.weekday() == 6
    move = mv.Move(min(base.pool), base.active(1)[0])
    for today in (sunday, setup.start + timedelta(2)):
        tomorrow = today + timedelta(1)
        p = built_for(setup, state=SimState(today, base.rosters, base.pool, {1: 3})).problem
        assert mv.day_of(p, move) == tomorrow
        # The week's last add pays for him, even when he lands in the next week.
        assert mv.limit_of(p, tomorrow) == p.limits[0] and p.limits[0].adds == 1
        assert mv.feasible(p, (move,))
        spent = SimState(today, base.rosters, base.pool, {1: 4})
        assert not mv.feasible(built_for(setup, state=spent).problem, (move,))
    # The windows: this week's opens today and runs a day past its end; the next starts after.
    p = built_for(setup, state=SimState(sunday, base.rosters, base.pool, {})).problem
    assert (p.limits[0].start, p.limits[0].end) == (sunday, sunday + timedelta(1))
    assert p.limits[1].start == sunday + timedelta(2) and p.limits[1].adds == 4


def test_no_problem_past_the_season():
    setup = make_setup()
    late = SimState(
        setup.season_end + timedelta(1), initial(setup).rosters, initial(setup).pool, {}
    )
    assert built_for(setup, state=late) is None


def test_each_tier_decides_and_the_surrogate_keeps_to_its_days():
    setup = make_setup()
    built = built_for(setup)
    exact = policy.exact(built)
    assert exact.source == "exact" and exact.solves == 2
    for m in exact.moves:
        assert m.add in setup.pool
    weighted = policy.exact(built, executes=policy.WEIGHTED, with_plan=False)
    assert weighted.solves == 1 and weighted.plan == ()
    surrogate = policy.surrogate(built)
    assert surrogate.source == "surrogate" and surrogate.solves == 1
    ranking = policy.ranking(built)
    assert ranking.source == "ranking" and ranking.solves == 0
    assert len(ranking.moves) <= 1
    # Monday is a surrogate day; Tuesday is not.
    assert policy.decide(built, "surrogate").solves == 1
    tuesday = SimState(setup.start + timedelta(1), initial(setup).rosters, initial(setup).pool, {})
    assert policy.decide(built_for(setup, state=tuesday), "surrogate") == policy.Decision(
        source="surrogate"
    )
    with pytest.raises(ValueError):
        policy.decide(built, "oracle")


def test_the_ranking_tier_swaps_the_pools_best_for_the_rosters_worst_when_it_gains():
    setup = make_setup()
    built = built_for(setup)
    d = policy.ranking(built)
    if d.moves:
        (m,) = d.moves
        p = built.problem
        assert m.add in {k for k, _ in p.candidates} and m.drop in {k for k, _ in p.roster}
        assert m.drop not in p.kept


def test_the_queue_keeps_to_the_caps_and_the_pool():
    setup = make_setup()
    state = initial(setup)
    pool = sorted(state.pool)
    roster = state.active(1)
    decision = policy.Decision(
        (mv.Move(pool[0], roster[0]), mv.Move(pool[1], roster[1]), mv.Move(999, roster[2])),
        (),
        (mv.Move(pool[2], roster[3], day=state.day + timedelta(1)),),
    )
    one = policy.queue(state, 1, decision, 1, 4)
    assert one.pending[1] == (mv.Move(pool[0], roster[0]),)
    two = policy.queue(state, 1, decision, 3, 4)
    assert [m.add for m in two.pending[1]] == [pool[0], pool[1]]  # 999 is not in the pool
    with_plan = policy.queue(state, 1, decision, 3, 4, execute_plan=True)
    assert [m.add for m in with_plan.pending[1]] == [pool[0], pool[1], pool[2]]
    capped = policy.queue(SimState(state.day, state.rosters, state.pool, {1: 3}), 1, decision, 3, 4)
    assert len(capped.pending[1]) == 1
    none = policy.queue(SimState(state.day, state.rosters, state.pool, {1: 4}), 1, decision, 3, 4)
    assert none.pending[1] == ()


def test_landing_moves_in_order_a_contested_add_is_gone():
    setup = make_setup()
    state = initial(setup)
    pool = sorted(state.pool)
    a, b = state.active(1)[0], state.active(2)[0]
    slot_a = dict(state.rosters[1])[a]
    pending = {1: (mv.Move(pool[0], a),), 2: (mv.Move(pool[0], b), mv.Move(pool[1], None))}
    state = SimState(state.day, state.rosters, state.pool, {}, pending)
    landed = policy.land(state, [2, 1])
    # Team 2 was first in the order: it has the contested add; team 1's move is gone.
    assert pool[0] in landed.active(2) and b in landed.pool
    assert pool[0] not in landed.active(1) and a in landed.active(1)
    assert pool[1] in landed.active(2)  # the add without a drop takes a bench spot
    assert landed.executed == 2 and landed.gone == 1
    assert landed.adds_used == {2: 2} and landed.pending == {}
    other = policy.land(state, [1, 2])
    assert pool[0] in other.active(1) and dict(other.rosters[1])[pool[0]] == slot_a
    assert policy.new_week(landed).adds_used == {}


def il_league():
    """A league with one IL slot. Team 1 has its five drafted players, one more active player
    (``hurt``, out) and one in IL (``held``, out long); ``add`` is the pool's best."""
    setup = make_setup(held_slots=("IL",))
    pool = sorted(initial(setup).pool)
    held, hurt, add = pool[0], pool[1], pool[2]
    rosters = dict(setup.rosters)
    rosters[1] = (*setup.rosters[1], (hurt, "BN"), (held, "IL"))
    projection = dict(setup.projection)
    projection[add] = {s: v * 2 for s, v in projection[add].items()}
    setup = replace(setup, rosters=rosters, projection=projection)
    return setup, initial(setup), held, hurt, add


def test_a_held_slot_move_lands_first_and_the_active_roster_never_exceeds_the_spots():
    """An add through a held-slot move (an injured active player to an open IL slot): the queue
    carries the move with the add, the landing makes it first and the add takes the bench spot
    it frees. Without the held-slot move the add has no spot and is gone, nothing made."""
    setup, state, held, hurt, add = il_league()
    rosters = {**state.rosters, 1: tuple(x for x in state.rosters[1] if x[0] != held)}
    state = replace(state, rosters=rosters, pool=state.pool | {held})
    spots, counts = setup.spots(), Counter(setup.roster_slots)
    assert len(state.active(1)) == spots and state.held(1) == ()
    swap = mv.Move(max(state.pool), state.active(1)[0])
    decision = policy.Decision((swap, mv.Move(add)), ((hurt, "IL"),), (), 1, "x")
    queued = policy.queue(state, 1, decision, 2, 4, spots=spots)
    # One held-slot move for the one add that needs a spot; the plain swap needs none.
    assert queued.pending_held[1] == ((hurt, "IL"),)
    landed = policy.land(queued, [1], spots, counts)
    assert dict(landed.rosters[1])[hurt] == "IL" and dict(landed.rosters[1])[add] == "BN"
    assert add in landed.active(1) and len(landed.active(1)) == spots
    assert landed.executed == 2 and landed.gone == 0 and landed.pending_held == {}
    # The held-slot move trimmed away (or none decided): the add is gone, the roster untouched.
    alone = replace(queued, pending_held={})
    gone = policy.land(alone, [1], spots, counts)
    assert add not in gone.active(1) and len(gone.active(1)) == spots
    assert gone.executed == 1 and gone.gone == 1 and hurt in gone.active(1)
    # A full IL slot has no room: the player stays active and the add is gone the same way.
    full = replace(queued, rosters={**queued.rosters, 1: (*queued.rosters[1], (held, "IL"))})
    full = replace(full, pool=full.pool - {held})
    blocked = policy.land(full, [1], spots, counts)
    assert dict(blocked.rosters[1])[hurt] == "BN" and add not in blocked.active(1)
    assert len(blocked.active(1)) == spots and blocked.gone == 1


def test_a_churns_add_takes_a_bench_slot_and_starts():
    """A churn (#221) drops the held player, moves the injured active player into his slot and
    adds into the freed spot: the add is active and starts when his team plays, never parked in
    the vacated IL slot. The sim's problem offers it: every add is a free agent (no claims)."""
    setup, state, held, hurt, add = il_league()
    status = {held: "O", hurt: "O"}
    returns = {held: setup.start + timedelta(40), hurt: setup.start + timedelta(4)}
    built = policy.problem_of(setup, state, 1, KNOBS, setup.projection, status, returns)
    p = built.problem
    churn = mv.Move(add, held)
    assert p.claims == frozenset() and p.cantcut == frozenset()
    assert mv.is_churn(p, churn) and mv.feasible(p, (churn,))
    assert mv.held_used(p, (churn,)) == [(hurt, "IL")]
    spots, counts = setup.spots(), Counter(setup.roster_slots)
    decision = policy.Decision((churn,), tuple(mv.held_used(p, (churn,))), (), 1, "x")
    queued = policy.queue(state, 1, decision, 2, 4, spots=spots)
    assert queued.pending_held[1] == ((hurt, "IL"),)
    landed = policy.land(queued, [1], spots, counts)
    slots = dict(landed.rosters[1])
    assert held not in slots and held in landed.pool
    assert slots[hurt] == "IL" and slots[add] == "BN" and add in landed.active(1)
    assert len(landed.active(1)) == spots and landed.executed == 1
    value = wk.per_game_values(setup.projection, setup.cats, None)
    day = next(d for d in setup.days if setup.players[add].nba_team in setup.schedule[d])
    assert add in policy.starters_of(setup, landed, 1, day, {hurt: "O"}, value)


def test_a_cleared_held_player_comes_back_and_the_roster_is_trimmed_to_the_spots():
    """The morning a held player's status no longer fits his slot he is back on the bench, and
    the active roster over the spots loses its least valuable active player, as the engine
    charges a cleared player; given the day's statuses and values, before anything lands."""
    setup, state, held, hurt, _add = il_league()
    spots, counts = setup.spots(), Counter(setup.roster_slots)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    # Still out: nothing moves.
    same = policy.land(state, [1], spots, counts, {held: "O", hurt: "O"}, value)
    assert same.rosters == state.rosters and same.pool == state.pool
    # Back (no status): to the bench, and the weakest of the seven active players goes; the
    # returned player, the best here, starts the same day his team plays.
    value = {**value, held: max(value.values()) + 1.0}
    back = policy.land(state, [1], spots, counts, {hurt: "O"}, value)
    slots = dict(back.rosters[1])
    weakest = min(state.active(1), key=lambda k: (value.get(k, 0.0), k))
    assert slots[held] == "BN" and held in back.active(1)
    assert weakest not in slots and weakest in back.pool
    assert len(back.active(1)) == spots
    assert back.forced_drops == 1 and back.executed == 0 and back.gone == 0
    assert back.adds_used == state.adds_used
    day = next(d for d in setup.days if setup.players[held].nba_team in setup.schedule[d])
    assert held in policy.starters_of(setup, back, 1, day, {hurt: "O"}, value)
    # The returning player is weighed with the rest: the weakest himself, he is the one who goes.
    lowest = min(value.values()) - 1.0
    himself = policy.land(state, [1], spots, counts, {hurt: "O"}, {**value, held: lowest})
    assert held not in dict(himself.rosters[1]) and held in himself.pool
    assert himself.forced_drops == 1 and len(himself.active(1)) == spots


def test_the_days_starters_and_score():
    setup = make_setup(statuses={})
    state = initial(setup)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    day = setup.start
    playing = {k for k in state.active(1) if setup.players[k].nba_team in setup.schedule[day]}
    starters = policy.starters_of(setup, state, 1, day, {}, value)
    assert set(starters) <= playing and len(starters) <= 5
    out = next(iter(starters))
    fewer = policy.starters_of(setup, state, 1, day, {out: "O"}, value)
    assert out not in fewer
    lines = {k: {"pts": 10.0, "minutes_factor": 1.0} for k in starters}
    scored = policy.score_day(setup, state, day, {}, value, lambda k, d: lines.get(k))
    assert scored.totals[1][1] == {"pts": 10.0 * len(starters)}
    assert 2 not in scored.totals.get(1, {}) or scored.totals[1][2] == {}


def test_the_season_guard_prices_a_move_on_the_rest_of_the_season():
    setup = make_setup()
    built = built_for(setup)
    ros = policy.ros_of(built)
    p = built.problem
    m = mv.Move(p.candidates[0][0], p.roster[0][0])
    first = ros(m)
    assert first is None or isinstance(first, float)
    assert ros(m) == first  # cached
    allowed = policy.guard_of(built)
    assert callable(allowed)
    rng = np.random.default_rng(0)
    assert rng is not None
