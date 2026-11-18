"""FAAB in a replay's league (#172, PR Fb): a claim carries a sealed bid from its team's budget,
the highest bid takes the player and pays it, a tie goes to the better priority, and the seat
bids by the live rule (``autopilot.bid_of``, through the door). Made-up leagues, fixed seeds."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.sim import audit, nopeek, policy
from pickandroll.sim import counts as ct
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, st
from pickandroll.sim.state import FAILED, LOST, WON, Claim, Resolved, SimState, Waiting, initial
from tests.sim.sim_league import KNOBS, arm, every_category, make_setup, recorded_lines

DAY = timedelta(1)


def league(**kw):
    """Four seats of five drafted players on six slots (one spot open each), waivers by FAAB
    after two days, $100 a team."""
    return replace(make_setup(teams=4, **kw), waivers="faab", waiver_days=2)


def spots_of(setup):
    return setup.spots(), Counter(setup.roster_slots)


def on_waivers(state: SimState, by: int, clears: date, *players: int) -> SimState:
    return replace(state, waivers={**state.waivers, **{k: Waiting(clears, by) for k in players}})


def claim(add: int, drop: int | None, clears: date, bid: int, week: int = 1) -> Claim:
    return Claim(mv.Move(add, drop), clears - 2 * DAY, clears, week, bid=bid)


def two_on_x(bid2: int, bid3: int, dollars: dict[int, int] | None = None):
    """Teams 2 and 3 claim x with drops on their rosters; team 3 stands ahead in the order."""
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    clears = setup.start + 3 * DAY
    a2, a3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x)
    s = replace(s, claims={2: (claim(x, a2, clears, bid2),), 3: (claim(x, a3, clears, bid3),)})
    if dollars:
        s = replace(s, dollars={**s.dollars, **dollars})
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2, bidding=True)
    return setup, s, out, x, a2, a3, clears


# --------------------------------------------------------------------------- the clear morning
def test_a_faab_league_starts_every_team_on_its_budget_and_names_its_model():
    setup = league()
    assert setup.bidding and initial(setup).dollars == {1: 100, 2: 100, 3: 100, 4: 100}
    assert initial(replace(setup, budget=7)).dollars == dict.fromkeys(setup.teams, 7)
    assert initial(replace(setup, waivers="priority")).dollars == {}
    assert policy.executions_of("faab") == policy.EXECUTIONS_FAAB
    assert policy.EXECUTIONS_FAAB not in (policy.EXECUTIONS, policy.EXECUTIONS_PRIORITY)


def test_two_bids_on_one_player_go_to_the_higher_which_pays_it_and_the_loser_pays_nothing():
    _, s, out, x, a2, a3, clears = two_on_x(7, 5)
    # Team 2 stands behind team 3 in the order and bids more: it takes him and pays its bid.
    assert (
        x in out.active(2) and a2 in out.pool and out.waivers == {a2: Waiting(clears + 2 * DAY, 2)}
    )
    assert x not in out.active(3) and a3 in out.active(3)
    assert out.dollars == {1: 100, 2: 93, 3: 100, 4: 100}
    # No tie, so the order stays as it was.
    assert out.priority == s.priority == (4, 3, 2, 1)
    assert out.resolved == (Resolved(2, x, a2, WON, False, 7), Resolved(3, x, a3, LOST, True, 5))
    assert out.claim_counts[2] == {WON: 1, "won_free": 0, "alone": 0, "over": 2}
    assert out.claim_counts[3] == {
        LOST: 1,
        "behind": 1,
        "behind_lost": 1,
        "lost_bid": 1,
        "short": 2,
    }
    assert out.claims == {} and out.executed_by == {2: 1} and out.gone_by == {}


def test_a_tie_goes_to_the_better_priority_which_goes_last():
    _, _, out, x, a2, _, _ = two_on_x(5, 5)
    assert x in out.active(3) and a2 in out.active(2)
    assert out.dollars[3] == 95 and out.dollars[2] == 100
    assert out.priority == (4, 2, 1, 3)
    assert out.claim_counts[3]["over"] == 0
    assert out.claim_counts[2]["lost_tie"] == 1 and "lost_bid" not in out.claim_counts[2]
    assert out.claim_counts[2]["short"] == 0


def test_a_bid_above_the_dollars_left_fails_and_the_player_goes_to_the_next():
    _, _, out, x, a2, a3, _ = two_on_x(7, 5, dollars={2: 4})
    assert out.resolved == (
        Resolved(2, x, a2, FAILED, False, 7),
        Resolved(3, x, a3, WON, True, 5),
    )
    assert x in out.active(3) and out.dollars[2] == 4 and out.dollars[3] == 95
    assert out.gone_by == {2: 1}
    # Nobody else could have been taken: the whole bid is paid above the next.
    assert out.claim_counts[3]["over"] == 5 and out.claim_counts[3]["behind"] == 1
    # A tie at $0 with no dollars left: the better priority wins him free, not alone (team 2
    # claimed him too), and team 2 loses on the tie.
    _, _, free, *_ = two_on_x(0, 0, dollars={2: 0, 3: 0})
    assert free.claim_counts[3]["won_free"] == 1 and free.claim_counts[3]["alone"] == 0
    assert free.claim_counts[2]["lost_tie"] == 1
    assert free.dollars == {1: 100, 2: 0, 3: 0, 4: 100}


def test_a_lone_claim_is_won_alone_and_a_team_s_second_win_needs_the_dollars_left():
    """Team 4 claims x at $60 and y at $50 with $100: it wins x, and its claim on y then fails
    (its $40 left are below the bid), so y goes to team 3's $1."""
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x, y = sorted(s.pool)[:2]
    clears = setup.start + 3 * DAY
    d4, e4, d3 = setup.rosters[4][-1][0], setup.rosters[4][-2][0], setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x, y)
    s = replace(
        s,
        claims={
            4: (claim(x, d4, clears, 60), claim(y, e4, clears, 50)),
            3: (claim(y, d3, clears, 1),),
        },
    )
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2, bidding=True)
    assert [(r.team, r.add, r.outcome) for r in out.resolved] == [
        (4, x, WON),
        (4, y, FAILED),
        (3, y, WON),
    ]
    assert out.dollars[4] == 40 and out.dollars[3] == 99
    assert out.claim_counts[4]["alone"] == 1 and out.claim_counts[3]["alone"] == 0
    assert out.priority == s.priority


def test_a_priority_morning_is_fa_s_whatever_the_claims_bid():
    """The bid is read only in a FAAB league: by priority the order decides, as before."""
    setup = replace(league(), waivers="priority")
    spots, counts = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    clears = setup.start + 3 * DAY
    a2, a3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    s = on_waivers(s, 1, clears, x)
    s = replace(s, claims={2: (claim(x, a2, clears, 9),), 3: (claim(x, a3, clears, 0),)})
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2)
    assert x in out.active(3) and out.priority == (4, 2, 1, 3) and out.dollars == {}
    assert out.resolved == (Resolved(3, x, a3, WON, True), Resolved(2, x, a2, LOST, True))


# --------------------------------------------------------------------------- the seat's bid
@pytest.mark.parametrize(
    ("gain", "typical", "dollars", "sizing", "amount"),
    [
        (1.4, 1.0, 100, None, 0),  # a routine claim: one typical or less bids $0
        (3.2, 1.0, 100, None, 3),  # a larger one, in typicals
        (6.0, 2.0, 100, 0.5, 2),  # faab_sizing 0.5: three typicals, halved, half up
        (6.0, 2.0, 100, 2.0, 6),  # faab_sizing 2
        (9.0, 1.0, 4, None, 4),  # clamped to the dollars left
        (9.0, 1.0, 0, 2.0, 0),  # nothing left
    ],
)
def test_the_seat_s_bid_is_the_autopilot_s(gain, typical, dollars, sizing, amount):
    floor = typical
    live = qa.bid_of(gain, qa.typical_gain([], floor), dollars, None, sizing, "W").amount
    assert policy.live_bid(gain, [], floor, dollars, sizing) == live == amount


def basis(gains, sizing=None, floor=1.0):
    return policy.Basis(policy.LIVE, tuple(gains), sizing=sizing, floor=floor)


def seat_claim(gain: float, recent=(), dollars: int = 100, sizing=None, floor: float = 1.0):
    """Team 2 claims a player on waivers on a day with ``recent`` (day offset, gain) behind it:
    the state after the queue."""
    setup = league()
    spots, _ = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    day = setup.start + 20 * DAY
    s = on_waivers(replace(s, day=day), 1, day + 2 * DAY, x)
    s = replace(
        s,
        dollars={**s.dollars, 2: dollars},
        recent={2: tuple((day - d * DAY, g) for d, g in recent)},
    )
    drop = setup.rosters[2][-1][0]
    decision = policy.Decision((mv.Move(x, drop),), basis=basis([gain], sizing, floor))
    return policy.queue(s, 2, decision, 1, 4, False, spots, setup), day


def test_a_seat_s_claim_carries_the_live_bid_on_its_fortnight_s_typical_gain():
    # Nine moves in the fortnight and today's: ten, so the median (2.0) is the typical.
    nine = [(d, 2.0) for d in range(1, 10)]
    out, day = seat_claim(6.0, nine, sizing=0.5)
    (c,) = out.claims[2]
    gains = [2.0] * 9 + [6.0]
    assert c.bid == qa.bid_of(6.0, qa.typical_gain(gains, 1.0), 100, None, 0.5, "W").amount
    assert c.bid == 2  # three typicals, x0.5, half up
    # The fortnight is kept with today's moves; a day fourteen back is out of it.
    assert out.recent[2][-1] == (day, 6.0) and len(out.recent[2]) == 10
    old, _ = seat_claim(6.0, [(14, 2.0), *nine[:8]])
    assert len(old.recent[2]) == 9 and min(d for d, _ in old.recent[2]) == day - 8 * DAY


def test_the_typical_gain_is_the_plan_floor_until_ten_moves():
    # Eight before and today's: nine, so the plan floor (3.0) is the typical: 9 / 3 = 3 typicals.
    out, _ = seat_claim(9.0, [(d, 0.5) for d in range(1, 9)], floor=3.0)
    assert out.claims[2][0].bid == 3
    # With ten the median of the fortnight: 9 / 0.5 = 18 typicals.
    ten, _ = seat_claim(9.0, [(d, 0.5) for d in range(1, 10)], floor=3.0)
    assert ten.claims[2][0].bid == 18


def test_a_bid_is_clamped_to_the_dollars_left_when_placed_and_a_free_agent_bids_nothing():
    out, _ = seat_claim(50.0, dollars=7)
    assert out.claims[2][0].bid == 7
    setup = league()
    spots, _ = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    decision = policy.Decision((mv.Move(x, setup.rosters[2][-1][0]),), basis=basis([50.0]))
    free = policy.queue(s, 2, decision, 1, 4, False, spots, setup)
    assert free.pending[2] == (mv.Move(x, setup.rosters[2][-1][0]),) and free.claims[2] == ()
    assert free.dollars == s.dollars


def test_a_decision_without_a_basis_bids_nothing_and_a_priority_claim_carries_no_bid():
    setup = league()
    spots, _ = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    s = on_waivers(s, 1, s.day + 2 * DAY, x)
    move = mv.Move(x, setup.rosters[2][-1][0])
    out = policy.queue(s, 2, policy.Decision((move,)), 1, 4, False, spots, setup)
    assert out.claims[2][0].bid == 0 and out.recent == {}
    prio = replace(setup, waivers="priority")
    by_priority = policy.queue(
        replace(s, dollars={}),
        2,
        policy.Decision((move,), basis=basis([9.0])),
        1,
        4,
        False,
        spots,
        prio,
    )
    assert by_priority.claims[2][0].bid == 0 and by_priority.recent == {}


# --------------------------------------------------------------------------- the rivals' bids
def test_a_market_rival_s_bid_is_the_assumed_form_on_its_view():
    assert policy.rival_bid(3.0, 1.0, 100, 1.0, 1.0) == 3
    assert policy.rival_bid(3.0, 1.0, 100, 2.0, 1.25) == 8  # 7.5, half up
    assert policy.rival_bid(3.0, 1.0, 100, 0.5, 0.5) == 1  # 0.75
    assert policy.rival_bid(3.0, 1.0, 2, 1.0, 1.0) == 2  # clamped to the dollars left
    assert policy.rival_bid(3.0, 0.0, 100, 1.0, 1.0) == 1  # no typical: the gain is one
    lo, hi = policy.RIVAL_BIDS.noise
    draws = [policy.market_noise(np.random.default_rng(i)) for i in range(50)]
    assert all(lo <= d < hi for d in draws) and lo < 1 < hi
    # The typical: the move's own gain until ten moves of the fortnight before today, pooled.
    day = date(2026, 11, 30)
    nine = [(day - i * DAY, 2.0) for i in range(1, 10)]
    assert policy.market_typical(nine, day, 5.0) == 5.0
    ten = [*nine, (day - 13 * DAY, 4.0)]
    assert policy.market_typical(ten, day, 5.0) == 2.0
    # Today's and the fifteenth day back do not count.
    out = [*nine, (day, 4.0), (day - 14 * DAY, 4.0)]
    assert policy.market_typical(out, day, 5.0) == 5.0


def test_a_market_rival_s_claim_in_a_faab_league_carries_its_bid():
    setup = replace(league(), market_rate=1.0)
    spots, _ = spots_of(setup)
    s = initial(setup)
    top = max(setup.market.values())
    x = min(s.pool)
    setup = replace(setup, market={**setup.market, x: 2 * top})
    s = on_waivers(initial(setup), 1, setup.start + 2 * DAY, x)
    decision = op.Market(1.0).decide(
        setup, s, 2, setup.projection, {}, {}, np.random.default_rng(5)
    )
    (move,) = decision.moves
    assert move.add == x and decision.basis is not None and decision.basis.rule == policy.MARKET
    gain = setup.market[x] - setup.market[move.drop]
    assert decision.basis.gains == (gain,) and len(decision.basis.noise) == 1
    out = policy.queue(s, 2, decision, 1, 4, False, spots, replace(setup, rival_scale=2.0))
    (noise,) = decision.basis.noise
    assert out.claims[2][0].bid == policy.rival_bid(gain, gain, 100, 2.0, noise)
    assert out.market_recent == ((s.day, gain),) and out.recent == {}
    # The same draw in a priority league: no basis, the same move.
    prio = replace(setup, waivers="priority")
    plain = op.Market(1.0).decide(prio, s, 2, setup.projection, {}, {}, np.random.default_rng(5))
    assert plain.moves == decision.moves and plain.basis is None


# --------------------------------------------------------------------------- the tiers
def built_on(setup, team: int = 1, **knobs):
    s = replace(initial(setup), day=setup.start)
    return policy.problem_of(setup, s, team, {**KNOBS, **knobs}, setup.projection, {}, {})


#: A bid's typical gain until ten moves, by format (the format PR): the engine's plan floor, which
#: in a one-win league is its own in the matchup's odds, and where every category counts the knob.
FLOOR_BY_FORMAT = [(ONE_WIN, st.PLAN_FLOOR_ODDS), (EACH_CATEGORY, 0.25)]


@pytest.mark.parametrize(("h2h", "floor"), FLOOR_BY_FORMAT)
def test_the_exact_and_the_surrogate_tier_bid_on_their_moves_own_gains_and_ranking_bids_nothing(
    h2h, floor
):
    setup = league(pool=12) if h2h == ONE_WIN else every_category(league(pool=12))
    b = built_on(setup, faab_sizing=0.5, plan_floor_cats=0.25)
    assert b.bids
    exact = policy.exact(b, with_plan=False)
    assert exact.moves and exact.basis is not None and exact.basis.rule == policy.LIVE
    ev = mv.Evaluator(b.problem)
    assert exact.basis.gains == policy.gains_of(ev, "three", exact.moves)
    rec = mv.recommend(ev, "three", [c for c, _ in b.problem.candidates])
    if tuple(pm.move for pm in rec.moves) == exact.moves:
        assert exact.basis.gains == pytest.approx([pm.marginal["three"] for pm in rec.moves])
    assert (exact.basis.sizing, exact.basis.floor) == (0.5, floor)
    sur = policy.surrogate(b)
    assert sur.basis is not None and sur.basis.gains == policy.gains_of(ev, "three", sur.moves)
    assert policy.ranking(b).basis is None
    # A plan's steps each carry a gain, in the plan's order.
    planned = policy.exact(b, with_plan=True)
    assert planned.basis is not None and len(planned.basis.plan) == len(planned.plan)
    # By priority no tier carries a basis, and the decision is the same.
    p = built_on(replace(setup, waivers="priority"), faab_sizing=0.5, plan_floor_cats=0.25)
    assert not p.bids
    assert policy.exact(p, with_plan=False) == replace(exact, basis=None)


def test_a_seat_that_bids_reads_faab_sizing_and_its_plan_floor_in_a_faab_league():
    faab = policy.Shape(waivers="faab")
    each = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    points = policy.Shape("points", waivers="faab")
    for tier in ("exact", "surrogate"):
        reads = policy.reads(rn.Arm("X", tier, KNOBS, {}), faab)
        # In a one-win league the plan floor is the engine's own (the format PR); where every
        # category counts, a seat that bids reads the knob.
        assert reads["faab_sizing"] == policy.READ
        assert reads["plan_floor_cats"] == policy.ONE_WIN_FLOOR
        reads = policy.reads(rn.Arm("X", tier, KNOBS, {}), each)
        assert reads["faab_sizing"] == reads["plan_floor_cats"] == policy.READ
        assert reads["plan_floor_points"] != policy.READ
        assert (
            policy.reads(rn.Arm("X", tier, KNOBS, {}), points)["plan_floor_points"] == policy.READ
        )
    ranking = policy.reads(rn.Arm("X", "ranking", KNOBS, {}), faab)
    assert (
        ranking["faab_sizing"] == "the ranking tier holds no gain in the engine's units: it bids $0"
    )
    mirrored = policy.reads(rn.Arm("X", "static", KNOBS, {}), faab, mirrored=True)
    assert mirrored["faab_sizing"] == policy.READ
    assert policy.reads(rn.Arm("X", "static", KNOBS, {}), faab)["faab_sizing"] == policy.STATIC
    for waivers in ("none", "priority"):
        shape = policy.Shape(waivers=waivers)
        assert policy.reads(rn.Arm("X", "exact", KNOBS, {}), shape)["faab_sizing"] != policy.READ


# --------------------------------------------------------------------------- the audit and the counts
def day_of(state: SimState) -> audit.Day:
    return audit.Day(state.day, 0, state, {}, {})


def found(rule, setup, today: SimState, before: SimState | None) -> list:
    return list(rule(setup, day_of(today), None if before is None else day_of(before)))


def morning(bid2: int = 7, bid3: int = 5):
    """``two_on_x``'s morning as the audit reads it: the day before with the claims open, the
    clear morning after."""
    setup, s, out, x, a2, a3, clears = two_on_x(bid2, bid3)
    return setup, replace(s, day=clears - DAY), replace(out, day=clears), x, a2, a3


def test_a_faab_run_is_held_to_the_wait_and_the_bid_rules_in_place_of_claim_priority():
    assert [r.name for r in audit.rules_of("faab")] == [
        *(r.name for r in audit.RULES),
        "waiver_wait",
        "budget_floor",
        "bid_paid",
        "bid_order",
    ]
    assert audit.Auditor(league()).rules == audit.rules_of("faab")
    for bids in ((7, 5), (5, 5), (0, 0)):
        setup, before, after, *_ = morning(*bids)
        for rule in audit.rules_of("faab"):
            assert found(rule.check, setup, after, before) == [], (bids, rule.name)


def test_budget_floor_catches_dollars_below_zero():
    setup, before, after, *_ = morning()
    assert found(
        audit.budget_floor, setup, replace(after, dollars={**after.dollars, 4: -1}), before
    ) == [(4, "dollars left -1, below zero")]


def test_bid_paid_catches_a_win_that_paid_other_than_its_bid_and_dollars_that_moved_alone():
    setup, before, after, x, *_ = morning()
    cheap = tuple(replace(r, bid=3) if r.outcome == WON else r for r in after.resolved)
    assert (2, f"won claim on player {x} paid 3, placed at 7") in found(
        audit.bid_paid, setup, replace(after, resolved=cheap), before
    )
    # The loser charged as well; a team that made no claim charged.
    for team in (3, 1):
        moved = replace(after, dollars={**after.dollars, team: after.dollars[team] - 2})
        assert found(audit.bid_paid, setup, moved, before) == [
            (team, f"dollars left {after.dollars[team] - 2}, expected {after.dollars[team]}")
        ]
    # On day one the budget stands for the day before.
    assert found(audit.bid_paid, setup, before, None) == []
    assert found(audit.bid_paid, setup, replace(before, dollars={**before.dollars, 1: 90}), None)


def test_bid_order_catches_a_lower_bid_that_won_an_order_rolled_without_a_tie_and_one_left():
    setup, before, after, x, a2, a3 = morning()
    # Team 3's $5 took x though team 2's $7 stood ahead of it and did not fail.
    low = (Resolved(3, x, a3, WON, False, 5), Resolved(2, x, a2, LOST, True, 7))
    breaches = found(audit.bid_order, setup, replace(after, resolved=low), before)
    assert (3, f"claim on player {x} won by team 3 at 5 with team 2 ahead at 7") in breaches
    assert (2, f"claim on player {x} lost to no higher or equal bid") in breaches
    # A win without a tie rolled the order.
    rolled = replace(after, priority=(4, 3, 1, 2))
    assert found(audit.bid_order, setup, rolled, before) == [
        (None, "priority after the morning (4, 3, 1, 2), expected (4, 3, 2, 1)")
    ]
    # A tie's winner left in its place.
    setup, before, tied, *_ = morning(5, 5)
    assert found(audit.bid_order, setup, replace(tied, priority=before.priority), before) == [
        (None, "priority after the morning (4, 3, 2, 1), expected (4, 2, 1, 3)")
    ]


def test_a_faab_run_s_counts_carry_the_dollars_and_the_bids_after_the_claims():
    setup, _, out, *_ = two_on_x(7, 5)
    rows = ct.Tally(setup).rows(out)
    assert list(rows[2])[-len(ct.BIDS) :] == list(ct.BIDS)
    assert {m: rows[2][m] for m in ct.BIDS} == {
        "dollars_spent": 7.0,
        "dollars_left": 93.0,
        "claims_won_free": 0.0,
        "claims_lost_bid": 0.0,
        "claims_lost_tie": 0.0,
        "claims_won_alone": 0.0,
        "bid_over_next": 2.0,
        "bid_short": 0.0,
    }
    assert (rows[3]["claims_lost_bid"], rows[3]["bid_short"], rows[3]["dollars_left"]) == (
        1,
        2,
        100,
    )
    assert ct.metrics_in(list(rows.values())) == (*ct.METRICS, *ct.CLAIMS, *ct.BIDS)
    # By priority: the claims' counts and no bid count.
    prio = ct.Tally(replace(setup, waivers="priority")).rows(replace(out, dollars={}))
    assert ct.metrics_in(list(prio.values())) == (*ct.METRICS, *ct.CLAIMS)


#: The made-up league's seed and path on which a surrogate seat among market rivals wins a claim
#: it paid for (``test_a_surrogate_seat_wins_a_claim_it_paid_for``, which says how it was found).
PAID_PATH = (1, 0)


def test_a_surrogate_seat_wins_a_claim_it_paid_for():
    """The test that catches a seat that never bids above $0: a six-week made-up league of four
    seats and twelve free agents, waivers by FAAB, the surrogate in seat 1 among market rivals
    at a rate of 0.3 a day (its arm names the engine's categories plan floor, 0.1, its typical
    gain until ten moves where every category counts; in this one-win league, since the format
    PR, the typical is the engine's own floor in the matchup's odds). The seat wins a claim and pays for it, every team's dollars are its budget
    less what its won claims bid, and the audit finds nothing. PAID_PATH is the first of seeds 1
    and 2 and paths 0 and 1, tried in that order, on which the seat wins a claim above $0."""
    setup = league(pool=12)
    u = arm("U", "surrogate", opponents="market", plan_floor_cats=0.1)
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PAID_PATH)
    seen: list = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: u.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda r: seen.append(r.state))
    assert result.breaches == ()
    won = [r for s in seen for r in s.resolved if r.outcome == WON]
    assert any(r.bid for r in won if r.team == 1), won
    for t in setup.teams:
        paid = sum(r.bid for r in won if r.team == t)
        assert seen[-1].dollars[t] == setup.budget - paid
        assert result.counts[t]["dollars_spent"] == paid


def test_a_claim_s_bid_is_part_of_the_day_s_digest():
    """The no-peek record: two day records alike but for one claim's bid digest apart in that
    claim's field alone, and two alike but for a decided claim's bid in the morning's."""
    _, _, out, x, a2, _, clears = two_on_x(7, 5)

    def record(bid: int) -> rn.DayRecord:
        placed = {2: (claim(x, a2, clears, bid),)}
        return rn.DayRecord(clears, 0, {}, {}, {}, {}, {}, {}, {}, out, claims=placed, cleared=out.resolved)  # fmt: skip

    one, two = nopeek.digest(record(7)), nopeek.digest(record(8))
    assert set(one) == set(two) and [f for f in one if one[f] != two[f]] == ["claims"]
    paid = record(7)
    more = replace(paid, cleared=tuple(replace(r, bid=r.bid + 1) for r in paid.cleared))
    three = nopeek.digest(more)
    assert [f for f in one if one[f] != three[f]] == ["cleared"]


def test_the_refusal_of_a_pair_apart_only_on_a_plan_floor_names_a_seat_that_bids():
    """Two surrogate arms apart only on ``plan_floor_cats``: the same seat outside a FAAB run,
    and the refusal says a seat that bids reads it there, in a league that counts every category
    (the format PR); two seats in a FAAB run that counts every category, one in a one-win FAAB
    run, where the plan floor is the engine's own."""
    a = rn.Arm("A", "surrogate", KNOBS, {})
    b = rn.Arm("B", "surrogate", {**KNOBS, "plan_floor_cats": 0.5}, {})
    for h2h in (ONE_WIN, EACH_CATEGORY):
        (why,) = rn.same_seat(a, b, [policy.Shape(waivers="priority", h2h=h2h)], rivals=False)
        assert why == (
            "plan_floor_cats (only the exact tier draws a week plan; read by the exact tier "
            "drawing and executing the week plan in a categories league), and in a categories "
            "FAAB run by a seat that bids (the exact or the surrogate tier, a mirror rival), its "
            "typical gain until ten moves; either only in a league that counts every category "
            "(--h2h each_category)"
        )
    (why,) = rn.same_seat(a, b, [policy.Shape(waivers="faab")], rivals=False)
    assert why.startswith(f"plan_floor_cats ({policy.ONE_WIN_FLOOR}; read by the exact tier")
    each = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    assert rn.same_seat(a, b, [each], rivals=False) is None
