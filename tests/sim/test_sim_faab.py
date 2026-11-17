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
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.state import FAILED, LOST, WON, Claim, Resolved, SimState, Waiting, initial
from tests.sim.sim_league import KNOBS, make_setup

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
    # A win at $0, with no other claim on the player: free and alone.
    _, _, free, *_ = two_on_x(0, 0, dollars={2: 0, 3: 0})
    assert free.claim_counts[3]["won_free"] == 1 and free.dollars[3] == 0


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


def test_the_exact_and_the_surrogate_tier_bid_on_their_moves_own_gains_and_ranking_bids_nothing():
    setup = league(pool=12)
    b = built_on(setup, faab_sizing=0.5, plan_floor_cats=0.25)
    assert b.bids
    exact = policy.exact(b, with_plan=False)
    assert exact.moves and exact.basis is not None and exact.basis.rule == policy.LIVE
    ev = mv.Evaluator(b.problem)
    assert exact.basis.gains == policy.gains_of(ev, "three", exact.moves)
    rec = mv.recommend(ev, "three", [c for c, _ in b.problem.candidates])
    if tuple(pm.move for pm in rec.moves) == exact.moves:
        assert exact.basis.gains == pytest.approx([pm.marginal["three"] for pm in rec.moves])
    assert (exact.basis.sizing, exact.basis.floor) == (0.5, 0.25)
    sur = policy.surrogate(b)
    assert sur.basis is not None and sur.basis.gains == policy.gains_of(ev, "three", sur.moves)
    assert policy.ranking(b).basis is None
    # By priority no tier carries a basis, and the decision is the same.
    p = built_on(replace(setup, waivers="priority"), faab_sizing=0.5, plan_floor_cats=0.25)
    assert not p.bids
    assert policy.exact(p, with_plan=False) == replace(exact, basis=None)


def test_a_seat_that_bids_reads_faab_sizing_and_its_plan_floor_in_a_faab_league():
    faab = policy.Shape(waivers="faab")
    points = policy.Shape("points", waivers="faab")
    for tier in ("exact", "surrogate"):
        reads = policy.reads(rn.Arm("X", tier, KNOBS, {}), faab)
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
