"""Waivers in a replay's league (#172, PR Fa): a dropped player waits his waiver days, a claim
on him is decided on his clear date by rolling waiver priority, the executor mirrors the
autopilot's claim rules, and the seat's problem is built as the live build builds it (each
candidate on waivers effective on his clear date and a claim, the seat's claims in flight folded
in). Made-up leagues, fixed seeds."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from pickandroll.season import moves as mv
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.state import (
    FAILED,
    LOST,
    WON,
    Claim,
    Resolved,
    SimState,
    Waiting,
    initial,
)
from tests.sim.sim_league import KNOBS, MONDAY, arm, make_setup, recorded_lines

DAY = timedelta(1)
#: The made-up league, its seed and path on which a surrogate seat among market rivals places a
#: claim and wins it (``test_a_surrogate_seat_places_a_claim_and_wins_one``, which says how it
#: was found).
CLAIM_PATH = (1, 1)


def league(**kw):
    """Four seats of five drafted players on six slots (one spot open each), waivers by
    priority after two days."""
    return replace(make_setup(teams=4, **kw), waivers="priority", waiver_days=2)


def spots_of(setup):
    return setup.spots(), Counter(setup.roster_slots)


def on_waivers(state: SimState, by: int, clears: date, *players: int) -> SimState:
    """``players`` (free agents of ``state``) on waivers until ``clears``, dropped by ``by``."""
    return replace(
        state,
        waivers={**state.waivers, **{k: Waiting(clears, by) for k in players}},
    )


def claim(add: int, drop: int | None, clears: date, week: int = 1, **kw) -> Claim:
    return Claim(mv.Move(add, drop), clears - 2 * DAY, clears, week, **kw)


def test_the_first_priority_is_the_draft_s_reverse_and_a_league_without_waivers_has_none():
    assert initial(league()).priority == (4, 3, 2, 1)
    plain = initial(make_setup(teams=4))
    assert (plain.priority, plain.waivers, plain.claims) == ((), {}, {})
    assert policy.executions_of("none") == policy.EXECUTIONS == "free_agents_next_day"
    assert policy.executions_of("priority") != policy.EXECUTIONS


def test_a_dropped_player_waits_his_days_and_is_a_free_agent_when_nobody_claims_him():
    setup = league()
    spots, counts = spots_of(setup)
    day = setup.start
    s = initial(setup)
    x, f = setup.rosters[1][0][0], min(s.pool)
    s = replace(s, pending={1: (mv.Move(f, x),)})
    s = policy.land(s, setup.teams, spots, counts, waiver=(day, 2))
    assert x in s.pool and s.waivers == {x: Waiting(day + 2 * DAY, 1)}
    # Team 2 adds him the day he left: a claim decided on his clear date, not tomorrow's add.
    two = policy.queue(replace(s, day=day), 2, policy.Decision((mv.Move(x),)), 1, 4, False, spots, setup)  # fmt: skip
    assert two.pending[2] == () and two.claims[2] == (Claim(mv.Move(x), day, day + 2 * DAY, 1),)
    tomorrow = policy.land(policy.clear_waivers(two, day + DAY, spots, counts, {}, 2), setup.teams, spots, counts, waiver=(day + DAY, 2))  # fmt: skip
    assert x not in tomorrow.active(2) and x in tomorrow.waivers
    cleared = policy.clear_waivers(tomorrow, day + 2 * DAY, spots, counts, {}, 2)
    assert x in cleared.active(2) and x not in cleared.pool and cleared.waivers == {}
    # Nobody claims him: on his clear date he is a free agent, whose add lands the next morning.
    free = policy.clear_waivers(s, day + 2 * DAY, spots, counts, {}, 2)
    assert x in free.pool and free.waivers == {} and free.resolved == ()
    three = policy.queue(replace(free, day=day + 2 * DAY), 3, policy.Decision((mv.Move(x),)), 1, 4, False, spots, setup)  # fmt: skip
    assert three.pending[3] == (mv.Move(x),) and three.claims.get(3, ()) == ()


def test_two_claims_on_one_player_go_to_the_better_priority_and_the_loser_s_drop_stays():
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    clears = setup.start + 3 * DAY
    a2, a3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x)
    s = replace(s, claims={2: (claim(x, a2, clears),), 3: (claim(x, a3, clears),)})
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2)
    # Team 3 stands ahead of team 2 (the order is 4, 3, 2, 1): it takes him and goes last.
    assert x in out.active(3) and a3 not in out.active(3) and a3 in out.pool
    assert out.waivers == {a3: Waiting(clears + 2 * DAY, 3)}
    assert x not in out.active(2) and a2 in out.active(2)
    assert out.priority == (4, 2, 1, 3)
    assert out.resolved == (Resolved(3, x, a3, WON, True), Resolved(2, x, a2, LOST, True))
    assert out.claim_counts == {
        3: {WON: 1, "behind": 1},
        2: {LOST: 1, "behind": 1, "behind_lost": 1},
    }
    assert out.claims == {} and out.executed_by == {3: 1} and out.adds_used == {3: 1}
    assert out.gone_by == {}


def test_a_team_with_two_claims_wins_its_first_then_waits_its_turn_again():
    """Team 4, first in the order, placed a claim on x and then one on y; team 3 placed one on z:
    team 4 takes x and goes last, team 3 takes z and goes last, then team 4 takes y."""
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x, y, z = sorted(s.pool)[:3]
    clears = setup.start + 3 * DAY
    d4, e4, d3 = setup.rosters[4][-1][0], setup.rosters[4][-2][0], setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x, y, z)
    s = replace(
        s,
        claims={4: (claim(x, d4, clears), claim(y, e4, clears)), 3: (claim(z, d3, clears),)},
    )
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2)
    assert [(r.team, r.add, r.outcome) for r in out.resolved] == [
        (4, x, WON),
        (3, z, WON),
        (4, y, WON),
    ]
    assert [r.behind for r in out.resolved] == [False, False, True]
    assert out.priority == (2, 1, 3, 4)
    assert {x, y} <= set(out.active(4)) and z in out.active(3)


def test_a_won_claim_the_roster_cannot_take_fails_and_the_player_goes_to_the_next():
    """Team 4 is first and claims x into an open spot it no longer has; it keeps its place, the
    claim fails (among the moves gone, not lost) and team 3's claim takes him."""
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x, extra = sorted(s.pool)[:2]
    s = replace(s, rosters={**s.rosters, 4: (*s.rosters[4], (extra, "BN"))}, pool=s.pool - {extra})
    assert len(s.active(4)) == spots
    clears = setup.start + 3 * DAY
    a3 = setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x)
    s = replace(s, claims={4: (claim(x, None, clears),), 3: (claim(x, a3, clears),)})
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2)
    assert out.resolved == (Resolved(4, x, None, FAILED, False), Resolved(3, x, a3, WON, True))
    assert out.priority == (4, 2, 1, 3) and x in out.active(3)
    assert out.claim_counts[4] == {FAILED: 1} and out.gone_by == {4: 1}


def test_a_claim_s_held_slot_move_is_made_only_if_it_is_won():
    """A full roster with an IL slot claims x with no drop: the decision's held-slot move goes on
    the claim, not on tomorrow's landing, and is made on the clear morning only if it wins."""
    setup = replace(make_setup(teams=4, held_slots=("IL",)), waivers="priority")
    spots, counts = spots_of(setup)
    s = initial(setup)
    x, hurt = sorted(s.pool)[:2]
    s = replace(s, rosters={**s.rosters, 3: (*s.rosters[3], (hurt, "BN"))}, pool=s.pool - {hurt})
    assert len(s.active(3)) == spots
    clears = setup.start + 3 * DAY
    s = replace(on_waivers(s, 1, clears, x), day=setup.start)
    decision = policy.Decision((mv.Move(x),), ((hurt, "IL"),))
    placed = policy.queue(s, 3, decision, 1, 4, False, spots, setup)
    assert placed.pending_held[3] == ()
    assert placed.claims[3] == (Claim(mv.Move(x), setup.start, clears, 1, ((hurt, "IL"),)),)
    won = policy.clear_waivers(placed, clears, spots, counts, {hurt: "O"}, 2)
    assert dict(won.rosters[3])[hurt] == "IL" and x in won.active(3)
    # Team 4 claims him too, ahead of team 3: team 3's claim is lost and the hurt player stays.
    a4 = setup.rosters[4][-1][0]
    rival = replace(placed, claims={**placed.claims, 4: (claim(x, a4, clears),)})
    lost = policy.clear_waivers(rival, clears, spots, counts, {hurt: "O"}, 2)
    assert dict(lost.rosters[3])[hurt] == "BN" and x in lost.active(4)


def test_a_claim_is_charged_to_the_week_of_the_day_before_it_lands():
    """Placed on a Friday: a claim that clears on Tuesday is charged to the new week, one that
    clears on Monday to the week before (Yahoo charges the week it clears in: the README's
    limit, pinned here so it cannot move unseen). The seat's plan charges them alike."""
    setup = league()
    spots, _ = spots_of(setup)
    friday = MONDAY + 4 * DAY
    s = initial(setup)
    tue, mon = sorted(s.pool)[:2]
    s = on_waivers(on_waivers(s, 1, friday + 4 * DAY, tue), 1, friday + 3 * DAY, mon)
    s = replace(s, day=friday)
    d1, e1 = setup.rosters[2][-1][0], setup.rosters[2][-2][0]
    decision = policy.Decision((mv.Move(tue, d1), mv.Move(mon, e1)))
    placed = policy.queue(s, 2, decision, 2, 4, False, spots, setup)
    assert [(c.move.add, c.week) for c in placed.claims[2]] == [(tue, 2), (mon, 1)]
    built = policy.problem_of(setup, s, 2, KNOBS, setup.projection, {}, {})
    p = built.problem
    assert (p.effective[tue], p.effective[mon]) == (friday + 4 * DAY, friday + 3 * DAY)
    week = {w.number: w for w in setup.calendar.weeks}
    assert mv.limit_of(p, p.effective[tue]).end == week[2].end + DAY
    assert mv.limit_of(p, p.effective[mon]).end == week[1].end + DAY


def test_the_week_s_adds_count_the_claims_charged_to_it():
    """Four adds made this week on a cap of four: a free agent and a claim charged to this week
    are not queued (the autopilot's NO_ADDS, the claims placed counted); a claim charged to next
    week is."""
    setup = league()
    spots, _ = spots_of(setup)
    friday = MONDAY + 4 * DAY
    s = initial(setup)
    tue, mon, f = sorted(s.pool)[:3]
    s = on_waivers(on_waivers(s, 1, friday + 4 * DAY, tue), 1, friday + 3 * DAY, mon)
    s = replace(s, day=friday, adds_used={2: 4})
    d, e, g = (k for k, _ in setup.rosters[2][-3:])
    decision = policy.Decision((mv.Move(f, g), mv.Move(mon, e), mv.Move(tue, d)))
    placed = policy.queue(s, 2, decision, 3, 4, False, spots, setup)
    assert placed.pending[2] == () and [c.move.add for c in placed.claims[2]] == [tue]
    # Three this week and a claim in flight charged to it: the week is full.
    s = replace(s, adds_used={2: 3}, claims={2: (claim(mon, e, friday + 3 * DAY, 1),)})
    full = policy.queue(s, 2, policy.Decision((mv.Move(f, g),)), 1, 4, False, spots, setup)
    assert full.pending[2] == ()


def test_the_executor_mirrors_the_autopilot_s_claim_rules():
    """READD: a team never claims back its own drop while he waits. DROP_CLAIMED: no move drops a
    player an open claim of the team takes. ALREADY_CLAIMED: no second claim on one add."""
    setup = league()
    spots, _ = spots_of(setup)
    s = initial(setup)
    mine, other, f = sorted(s.pool)[:3]
    clears = setup.start + 2 * DAY
    s = replace(on_waivers(on_waivers(s, 1, clears, mine), 2, clears, other), day=setup.start)
    d, e = setup.rosters[1][-1][0], setup.rosters[1][-2][0]
    readd = policy.queue(s, 1, policy.Decision((mv.Move(mine, d),)), 1, 4, False, spots, setup)
    assert readd.claims.get(1, ()) == () and readd.pending[1] == ()
    placed = policy.queue(s, 1, policy.Decision((mv.Move(other, d),)), 1, 4, False, spots, setup)
    assert [c.move for c in placed.claims[1]] == [mv.Move(other, d)]
    again = replace(placed, pending={})
    twice = policy.queue(again, 1, policy.Decision((mv.Move(other, e),)), 1, 4, False, spots, setup)  # fmt: skip
    assert len(twice.claims[1]) == 1 and twice.pending[1] == ()
    dropped = policy.queue(again, 1, policy.Decision((mv.Move(f, d),)), 1, 4, False, spots, setup)
    assert dropped.pending[1] == ()
    # Without waivers the same moves are free agents' adds, as before.
    plain = replace(setup, waivers="none")
    free = policy.queue(s, 1, policy.Decision((mv.Move(mine, d),)), 1, 4, False, spots, plain)
    assert free.pending[1] == (mv.Move(mine, d),) and free.claims == {}


def test_the_seat_s_problem_reads_the_wire_s_clear_dates_and_folds_its_claims_in():
    """As ``api.season_moves.build``: a candidate on waivers takes effect on his clear date and
    is a claim; a free agent takes effect tomorrow. My claim in flight is made in the problem:
    its add on my roster from his clear date and kept, its drop off it, the add out of the
    candidates (no second claim on him)."""
    setup = league()
    s = initial(setup)
    w, flight, f = sorted(s.pool)[:3]
    day = setup.start + DAY
    d = setup.rosters[1][-1][0]
    s = on_waivers(on_waivers(s, 2, day + 3 * DAY, w), 3, day + 2 * DAY, flight)
    s = replace(s, day=day, claims={1: (claim(flight, d, day + 2 * DAY),)})
    p = policy.problem_of(setup, s, 1, KNOBS, setup.projection, {}, {}).problem
    assert p.effective[w] == day + 3 * DAY and w in p.claims
    assert p.effective[f] == day + DAY and f not in p.claims
    assert flight not in dict(p.candidates) and flight not in p.effective
    assert flight in dict(p.roster) and d not in dict(p.roster)
    assert p.pending == {flight} and flight in p.kept and p.returns[flight] == day + 2 * DAY
    # Without the claim the roster is as it stands and the player is a candidate.
    bare = policy.problem_of(setup, replace(s, claims={}), 1, KNOBS, setup.projection, {}, {})
    assert flight in dict(bare.problem.candidates) and d in dict(bare.problem.roster)


def test_a_market_rival_s_pick_on_waivers_is_a_claim():
    """Its view and its rate are as they were; the pick it makes, the best on its view, is a
    claim when he is on waivers."""
    setup = league()
    spots, _ = spots_of(setup)
    best = min(initial(setup).pool)
    setup = replace(setup, market={**setup.market, best: 2 * max(setup.market.values())})
    s = replace(on_waivers(initial(setup), 1, setup.start + 2 * DAY, best), day=setup.start)
    decision = op.Market(1.0).decide(
        setup, s, 2, setup.projection, {}, {}, np.random.default_rng(0)
    )
    assert decision.moves[0].add == best
    out = policy.queue(s, 2, decision, 1, 4, False, spots, setup)
    assert [c.move.add for c in out.claims[2]] == [best] and out.pending[2] == ()


def test_a_surrogate_seat_places_a_claim_and_wins_one():
    """The test that catches a seat that never claims: a six-week made-up league of four seats
    and twelve free agents with waivers by priority, the surrogate in seat 1 among market rivals
    at a rate of 0.3 a day. Every seat drops players onto the wire; the surrogate claims one and
    wins it, and the audit finds nothing. CLAIM_PATH is the first of seeds 1 and 2 and paths 0
    and 1, tried in that order, on which the seat both places and wins a claim (on seed 1 path
    0 its one claim is lost)."""
    setup = league(pool=12)
    u = arm("U", "surrogate", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *CLAIM_PATH)
    seen: list = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: u.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda r: seen.append(r.state))
    assert result.breaches == ()
    counts = seen[-1].claim_counts[1]
    assert counts["placed"] >= 1 and counts[WON] >= 1, counts
