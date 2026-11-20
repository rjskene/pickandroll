"""The bid policy in a seat (#172, PR F2): what a decision carries for it (``policy.with_bid``),
what the queue hands the family and what it never does (the walls), what the state keeps, the
three counts, the reads table, the same-seat refusal, the arm's spec and the record. Made-up
leagues and made-up mornings; no season is played here (``test_sim_bid_seasons.py``)."""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields, replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.sim import bid_policy as bp
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from pickandroll.sim.shapes import BOOK, CONTINUOUS
from pickandroll.sim.state import LOST, Resolved, initial
from tests.sim.sim_league import KNOBS, arm, every_category, rates
from tests.sim.test_sim_faab import DAY, built_on, claim, league, on_waivers, spots_of

#: A block naming every key.
EVERY_KEY = {
    "week": 0.25,
    "season": 0.25,
    "pace": {"k": 1, "shape": 1, "reserve": 0.2},
    "routine": 1,
    "rival_cap": True,
    "shade": {"q": 0.5, "least": 2},
}
PACE = {"k": 1, "shape": 1, "reserve": 0.2}


def morning(setup=None, ahead: int = 20, **more):
    """A FAAB league's day ``ahead`` of its first, a player on waivers who is decided two days
    on: the setup, the state, the player and team 2's drop."""
    setup = setup or league()
    s = initial(setup)
    x = min(s.pool)
    day = setup.start + ahead * DAY
    s = on_waivers(replace(s, day=day), 1, day + 2 * DAY, x)
    return setup, replace(s, **more), x, setup.rosters[2][-1][0]


def placed(block, setup, state, x, drop, gain=6.0, sizing=None, floor=1.0, week=(), season=()):
    """Team 2's claim on ``x`` and the state after the queue, its arm naming ``block`` (None:
    no ``bid`` at all)."""
    spots, _ = spots_of(setup)
    rule = None if block is None else bp.of(block)
    basis = policy.Basis(
        policy.LIVE, (gain,), sizing=sizing, floor=floor, bid=rule, week=week, season=season
    )
    decision = policy.Decision((mv.Move(x, drop),), basis=basis)
    out = policy.queue(state, 2, decision, 1, 4, False, spots, setup)
    (c,) = out.claims[2]
    return c, out


def nine(day, gain: float):
    """Nine moves, one on each of the nine days before ``day``, the oldest first, as the state
    keeps them."""
    return tuple((day - d * DAY, gain) for d in range(9, 0, -1))


# --------------------------------------------------------------------------- the queue
def test_an_arm_that_names_no_bid_bids_by_the_live_rule_and_an_empty_block_bids_the_same():
    setup, s, x, drop = morning()
    for gain, sizing, dollars in ((6.0, None, 100), (6.0, 0.5, 100), (1.2, None, 100), (9, 2.0, 4)):
        at = replace(s, dollars={**s.dollars, 2: dollars})
        none, out = placed(None, setup, at, x, drop, gain, sizing)
        live = policy.live_bid(gain, [gain], 1.0, dollars, sizing)
        assert none.bid == live
        # The claim's value in typicals is kept for the counts, whatever the arm names.
        assert none.value == gain
        empty, kept = placed({}, setup, at, x, drop, gain, sizing)
        assert (empty.bid, empty.value) == (none.bid, none.value)
        # Neither keeps a fortnight on another horizon.
        assert out.recent_by == kept.recent_by == {}
        assert out.recent == kept.recent


def test_a_seat_s_claim_bids_by_its_arm_s_policy_on_what_its_manager_sees():
    setup, s, x, drop = morning()
    day = s.day
    # The routine dollar.
    assert placed({"routine": 1}, setup, s, x, drop, 0.8)[0].bid == 1
    assert placed(None, setup, s, x, drop, 0.8)[0].bid == 0
    # The pace is read on the morning the claim is decided, two days on: 22 of the regular
    # season's 35 days gone, the path at 0.2 + 0.8 x 13 / 35, every dollar left.
    c, _ = placed({"pace": PACE}, setup, s, x, drop)
    when = policy.bid_when(setup, day + 2 * DAY)
    assert when == bp.When(day + 2 * DAY, setup.start, setup.start + 35 * DAY, setup.season_end)
    assert c.bid == bp.amount(bp.of({"pace": PACE}), bp.Seen(6.0, 1.0, 100, budget=100, when=when))
    assert c.bid == 12 and c.value == 6.0
    # On the day it is placed the path would hold more, and the bid be less.
    early = replace(when, day=day)
    assert bp.amount(bp.of({"pace": PACE}), bp.Seen(6.0, 1.0, 100, budget=100, when=early)) == 11
    # The league's budget is the start: a seat with half of it left is behind that path.
    half = replace(s, dollars={**s.dollars, 2: 50})
    assert placed({"pace": PACE}, setup, half, x, drop)[0].bid == 6
    # The rival cap reads the other teams' dollars left, never the seat's own.
    poor = replace(s, dollars={1: 3, 2: 100, 3: 5, 4: 0})
    assert placed({"rival_cap": True}, setup, poor, x, drop, 12.0)[0].bid == 6
    assert placed(None, setup, poor, x, drop, 12.0)[0].bid == 12
    rich = replace(s, dollars={1: 3, 2: 100, 3: 500, 4: 0})
    assert placed({"rival_cap": True}, setup, rich, x, drop, 12.0)[0].bid == 12


def test_the_shade_reads_the_other_teams_winning_bids_and_never_the_seat_s_own():
    setup, s, x, drop = morning()
    d = s.day - 3 * DAY
    won = ((d, 1, 2), (d, 3, 4), (d, 2, 50), (d, 4, 1))
    seen = replace(s, won_bids=won)
    top = {"shade": {"q": 1, "least": 3}}
    # Three wins of other teams (2, 4 and 1 dollars): the top of them plus one. The seat's own
    # win of 50 is not in the pool: with it the cap would be 51.
    assert placed(top, setup, seen, x, drop, 30.0)[0].bid == 5
    assert placed(None, setup, seen, x, drop, 30.0)[0].bid == 30
    # Nor does its own win count toward `least`.
    assert placed({"shade": {"q": 1, "least": 4}}, setup, seen, x, drop, 30.0)[0].bid == 30
    # Another team's later win moves it.
    more = replace(s, won_bids=(*won, (s.day, 3, 9)))
    assert placed(top, setup, more, x, drop, 30.0)[0].bid == 10


def test_the_week_and_the_season_weigh_the_seat_s_own_moves_on_that_horizon():
    setup, s, x, drop = morning()
    day = s.day
    week, season = {"week": 1}, {"season": 1}
    # Nine moves in the fortnight and today's: the week's median (1.5) is its typical.
    by = {bp.WEEK: {2: nine(day, 1.5), 3: nine(day, 99.0)}, bp.SEASON: {2: nine(day, 10.0)}}
    kept = replace(s, recent_by=by)
    c, out = placed(week, setup, kept, x, drop, week=(3.0,))
    assert (c.bid, c.value) == (2, 2.0)
    # The moves are kept with today's, the seat's own, on the horizon the policy weighs: the
    # other team's are as they were, and the season's, which this policy does not weigh,
    # untouched.
    assert out.recent_by[bp.WEEK][2] == (*nine(day, 1.5), (day, 3.0))
    assert out.recent_by[bp.WEEK][3] == nine(day, 99.0)
    assert out.recent_by[bp.SEASON] == by[bp.SEASON]
    # The three weeks' own fortnight is kept as it always was.
    assert out.recent == {2: ((day, 6.0),)}
    # The season's: 40 over a typical of 10.
    c, out = placed(season, setup, kept, x, drop, season=(40.0,))
    assert (c.bid, c.value) == (4, 4.0) and len(out.recent_by[bp.SEASON][2]) == 10
    # A season figure of none counts 0: no typicals, a routine claim.
    assert placed(season, setup, kept, x, drop, season=(0.0,))[0].bid == 0
    # The weights mix the horizons, the three weeks taking the rest.
    mixed = {"week": 0.25, "season": 0.25}
    c, _ = placed(mixed, setup, kept, x, drop, week=(3.0,), season=(40.0,))
    assert c.value == pytest.approx(0.5 * 6.0 + 0.25 * 2.0 + 0.25 * 4.0) and c.bid == 5


def test_the_week_and_the_season_read_a_size_from_the_seat_s_tenth_move():
    """The lead's working default (q-6, 2026-11-19): a seat that decides twice a week seldom
    holds ten moves in a fortnight, so on the week and the season its typical is the median of
    its last ten moves whatever their age, until its fortnight holds ten; before its tenth move
    a move that gains counts as typical. The three weeks' own typical is the live rule's."""
    setup, s, x, drop = morning(ahead=40)
    day = s.day
    # Before the tenth move: one typical, a routine claim.
    for key, block, more in (
        (bp.WEEK, {"week": 1}, {"week": (3.0,)}),
        (bp.SEASON, {"season": 1}, {"season": (3.0,)}),
    ):
        early = replace(s, recent_by={key: {2: nine(day, 1.5)[:8]}})
        c, out = placed(block, setup, early, x, drop, **more)
        assert (c.bid, c.value) == (0, 1.0) and len(out.recent_by[key][2]) == 9
        # The tenth move reads a size, on moves four days apart: three of the nine are in the
        # fortnight, and all ten are kept.
        apart = tuple((day - 4 * d * DAY, 1.5) for d in range(9, 0, -1))
        seldom = replace(s, recent_by={key: {2: apart}})
        c, out = placed(block, setup, seldom, x, drop, **more)
        assert (c.bid, c.value) == (2, 2.0)
        assert out.recent_by[key][2] == (*apart, (day, 3.0))
        assert sum(1 for d, _ in apart if d > day - 14 * DAY) == 3
        # An eleventh drops the oldest: out of the fortnight and not one of the last ten.
        c, out = placed(block, setup, replace(s, recent_by=out.recent_by), x, drop, **more)
        assert out.recent_by[key][2] == (*apart[1:], (day, 3.0), (day, 3.0))
        assert c.value == 2.0
    # The fortnight wins once it holds ten: eleven moves in it and today's, whose median (3) is
    # not the last ten's (2), and a move before the fortnight is dropped.
    gains = (9.0, 9.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 3.0, 3.0, 3.0)
    held = tuple((day - (11 - i) * DAY, g) for i, g in enumerate(gains))
    full = replace(s, recent_by={bp.WEEK: {2: ((day - 30 * DAY, 0.2), *held)}})
    c, out = placed({"week": 1}, setup, full, x, drop, week=(6.0,))
    assert (c.bid, c.value) == (2, 2.0)
    assert out.recent_by[bp.WEEK][2] == (*held, (day, 6.0))
    # The three weeks keep the live rule: nine moves spread over five weeks are no fortnight
    # of ten, so the typical is the plan floor (1), whatever the block.
    thin = replace(s, recent={2: tuple((day - 4 * d * DAY, 0.5) for d in range(9, 0, -1))})
    for block in (None, {}, {"week": 0.5}):
        c, out = placed(block, setup, thin, x, drop, week=(3.0,) if block else ())
        assert out.recent[2] == (*((day - 4 * d * DAY, 0.5) for d in range(3, 0, -1)), (day, 6.0))
    assert placed(None, setup, thin, x, drop)[0].bid == placed({}, setup, thin, x, drop)[0].bid == 6


def test_a_plan_s_step_bids_as_today_whatever_the_weights():
    """A step due tomorrow, executed: its claim bids on its week increment over the three
    weeks' typical, as the live rule, under a policy that weighs the week or the season; the
    pace, the routine and the caps apply to it as to any claim."""
    setup, s, x, drop = morning()
    spots, _ = spots_of(setup)

    def step(block, gain=3.0):
        rule = None if block is None else bp.of(block)
        basis = policy.Basis(policy.LIVE, (), plan=(gain,), floor=1.0, bid=rule)
        decision = policy.Decision((), plan=(mv.Move(x, drop),), basis=basis)
        out = policy.queue(s, 2, decision, 1, 4, True, spots, setup)
        (c,) = out.claims[2]
        return c

    live = step(None)
    assert (live.bid, live.value) == (3, 3.0)
    for block in ({"week": 1}, {"season": 1}, {"week": 0.5, "season": 0.5}):
        assert (step(block).bid, step(block).value) == (live.bid, live.value)
    assert step({"week": 1, "routine": 1}, 0.5).bid == 1
    assert step({"week": 1, "pace": PACE}).bid == 6


# --------------------------------------------------------------------------- the walls
def test_the_family_takes_one_frozen_value_and_the_module_reads_nothing_else():
    assert list(inspect.signature(bp.amount).parameters) == ["rule", "seen"]
    assert [f.name for f in fields(bp.Seen)] == [
        "gain",
        "typical",
        "dollars",
        "sizing",
        "step",
        "week",
        "typical_week",
        "season",
        "typical_season",
        "budget",
        "others",
        "wins",
        "when",
    ]
    assert [f.name for f in fields(bp.When)] == ["day", "first", "bracket", "last"]
    for frozen in (bp.Seen(1.0, 1.0, 1), bp.When(*[initial(league()).day] * 4), bp.DEFAULT):
        with pytest.raises(AttributeError):
            frozen.gain = 2.0  # type: ignore[misc]
    # The module imports nothing of the simulator, the engine or the price book.
    tree = ast.parse(Path(bp.__file__).read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a relative import"
            names.add(node.module)
    assert names == {"__future__", "collections.abc", "dataclasses", "datetime", "math", "typing"}


def test_a_sealed_bid_a_losing_bid_the_book_and_the_scale_never_move_the_seat_s_bid():
    """The walls: with a policy naming every key, the seat's bid of the day is the same whatever
    a rival's open claim bids, whatever a claim that lost bid, whatever the rivals' price book
    and scale are and whatever the market rivals' fortnight holds; and it moves with what a
    manager does see (another team's winning bid, another team's dollars left)."""
    setup, s, x, drop = morning()
    day = s.day
    y = sorted(s.pool)[1]
    a3 = setup.rosters[3][-1][0]
    s = on_waivers(s, 1, day + 2 * DAY, y)
    s = replace(
        s,
        dollars={1: 40, 2: 90, 3: 35, 4: 60},
        won_bids=((day - DAY, 1, 4), (day - DAY, 3, 7), (day - DAY, 4, 2), (day - DAY, 2, 30)),
        recent_by={bp.WEEK: {2: nine(day, 1.5)}, bp.SEASON: {2: nine(day, 10.0)}},
        market_recent=((day - DAY, 0.4), (day - DAY, 0.9)),
        claims={3: (claim(x, a3, day + 2 * DAY, 3),)},
        resolved=(Resolved(3, y, a3, LOST, True, 6),),
    )

    def bid(setup=setup, state=s) -> int:
        c, _ = placed(EVERY_KEY, setup, state, x, drop, 30.0, 1.5, week=(3.0,), season=(40.0,))
        return c.bid

    base = bid()
    assert base == 5  # the shade: the median of the other teams' wins (4), plus one
    # A sealed bid: another team's open claim, on the same player.
    for sealed in (0, 1, 50, 99):
        assert bid(state=replace(s, claims={3: (claim(x, a3, day + 2 * DAY, sealed),)})) == base
    assert bid(state=replace(s, claims={})) == base
    # A losing bid.
    for lost in (0, 29, 80):
        assert bid(state=replace(s, resolved=(Resolved(3, y, a3, LOST, True, lost),))) == base
    assert bid(state=replace(s, resolved=())) == base
    # The book and the scale: the world's bid model.
    prices = ((0.0, 5), (0.02, 3), (0.5, 1))
    for world in (
        replace(setup, rival_scale=0.25),
        replace(setup, rival_scale=4.0),
        replace(setup, rival_bids=BOOK, rival_prices=prices),
        replace(setup, rival_bids=BOOK, rival_prices=((0.9, 1),), rival_scale=3.0),
    ):
        assert bid(setup=world) == base
    # The market rivals' fortnight, which their bids scale by.
    assert bid(state=replace(s, market_recent=())) == base
    assert bid(state=replace(s, market_recent=tuple((day - DAY, 50.0) for _ in range(12)))) == base
    # What a manager sees does move it: another team's winning bid (the shade) ...
    seen = replace(s, won_bids=(*s.won_bids, (day, 4, 20), (day, 3, 22)))
    assert bid(state=seen) == 8
    # ... and, with no shade binding, the other teams' dollars left (the cap).
    unshaded = replace(s, won_bids=())
    assert bid(state=unshaded) == 45
    assert bid(state=replace(unshaded, dollars={1: 9, 2: 90, 3: 8, 4: 2})) == 10


# --------------------------------------------------------------------------- the state
def test_a_won_claim_joins_the_season_s_winning_bids_and_its_team_s_value_won():
    setup = league()
    spots, counts = spots_of(setup)
    s = initial(setup)
    x, y = sorted(s.pool)[:2]
    clears = setup.start + 3 * DAY
    a2, a3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    b3 = setup.rosters[3][-2][0]
    s = on_waivers(s, 1, clears, x, y)
    before = ((setup.start, 4, 1),)
    s = replace(
        s,
        won_bids=before,
        value_won={4: 0.5},
        claims={
            2: (replace(claim(x, a2, clears, 7), value=3.5),),
            3: (
                replace(claim(x, a3, clears, 5), value=9.0),
                replace(claim(y, b3, clears, 0), value=1.0),
            ),
        },
    )
    out = policy.clear_waivers(s, clears, spots, counts, {}, 2, bidding=True)
    # Team 2 wins x at 7 and team 3 the other player at $0, alone: both are winning bids, in
    # the order decided; the bid that lost is nowhere in them.
    assert set(out.won_bids) == {*before, (clears, 2, 7), (clears, 3, 0)}
    assert out.won_bids[0] == before[0] and len(out.won_bids) == 3
    assert out.value_won == {4: 0.5, 2: 3.5, 3: 1.0}
    # By priority nothing is kept.
    prio = policy.clear_waivers(replace(s, dollars={}), clears, spots, counts, {}, 2)
    assert prio.won_bids == before and prio.value_won == {4: 0.5}
    # A league without a budget starts with none of it.
    assert initial(setup).won_bids == () and initial(setup).value_won == {}
    assert initial(setup).recent_by == {}


def test_a_claim_s_value_is_no_part_of_the_key_two_seasons_share_a_decision_on():
    """``SimState.key`` is what a decision depends on: two seasons of a pair with one key share
    a rival's solve. A claim's value is what its bid was sized on, read by the counts alone, so
    two states apart on an open claim's value only (one move, one bid, one clear date) are one
    key, as on main, where a claim held no value: a pair that names no ``bid`` shares what it
    shared. Every other part of a claim still parts the keys."""
    _, state, x, drop = morning()
    c = replace(claim(x, drop, state.day + 2 * DAY, 3), value=0.4)
    one = replace(state, claims={2: (c,)})
    two = replace(state, claims={2: (replace(c, value=0.6),)})
    assert one != two and one.claims != two.claims
    assert one.key() == two.key()
    assert c.value == 0.4 and one.claims[2][0].value == 0.4  # the key changes no claim
    for other in (
        replace(c, bid=4),
        replace(c, clears=c.clears + DAY),
        replace(c, move=mv.Move(x, None)),
        replace(c, week=2),
        replace(c, churn=True),
    ):
        assert replace(state, claims={2: (other,)}).key() != one.key(), other
    assert replace(state, claims={3: (c,)}).key() != one.key()


@pytest.mark.parametrize("h2h", [ONE_WIN, EACH_CATEGORY])
def test_no_decision_reads_an_open_claim_s_value(h2h):
    """Why the key may leave a claim's value out (the lead's a-8): no decision reads it. Two
    states of one key, apart only on the values of their open claims (the deciding team's own
    and two other teams'), give one decision, and one queue after it: the same claims placed,
    at the same bids and values, and the same state beside them. Held for the seat on each tier
    with a block naming every key and with none, a mirror rival of each such arm, and a market
    rival bidding by the assumed form and on the price book. Every add is a claim here (FAAB
    under continuous waivers) and the day's beliefs make two free agents the best of all, so
    each of them places one."""
    base = league(pool=12) if h2h == ONE_WIN else every_category(league(pool=12))
    setup = replace(base, waiver_rule=CONTINUOUS)
    spots, _ = spots_of(setup)
    s = replace(initial(setup), day=setup.start)
    riser, second, *_, x, y, z = sorted(s.pool)
    beliefs = {**setup.projection, riser: rates(3.0), second: rates(2.5)}
    waiting = (x, y, z)

    def at(value: float):
        claims = {}
        for team, k in zip((1, 2, 3), waiting, strict=True):
            c = claim(k, setup.rosters[team][-1][0], s.day + DAY, 3)
            claims[team] = (replace(c, value=value * team),)
        return replace(s, claims=claims)

    one, two = at(0.4), at(7.0)
    assert one != two and one.key() == two.key()
    rule = bp.of(EVERY_KEY)
    knobs = {**KNOBS, "plan_floor_cats": 0.25}
    # The surrogate decides on every day here, so this one is a day of its own.
    daily = replace(policy.DEFAULT_FIELDS, surrogate_days=tuple(range(7)))
    cases = []
    for tier in ("exact", "surrogate", "ranking"):
        u = replace(arm("U", tier, plan_floor_cats=0.25), fields=daily)
        cases += [(setup, 1, u.seat()), (setup, 1, replace(u, bid=rule).seat())]
    cases += [(setup, 2, op.Mirror(knobs, daily, bid=block)) for block in (None, rule)]
    market = op.Market(1.0, op.SEASON, 3)
    book = replace(setup, rival_bids=BOOK, rival_prices=((0.0, 1), (0.5, 7)))
    cases += [(setup, 3, market), (book, 3, market)]
    bids = []
    for room, team, strategy in cases:
        got = []
        for state in (one, two):
            g = np.random.default_rng(7)
            decision = strategy.decide(room, state, team, beliefs, {}, {}, g)
            # The day's cap as a run reads it: the arm's knob, and one move for a market rival.
            cap = int(policy.knob(strategy.knobs, "daily_cap")) if team != 3 else 1
            out = policy.queue(state, team, decision, cap, room.max_weekly_adds, False, spots, room)
            held = len(state.claims[team])
            # The claims that stood are as they stood, their values with them.
            assert out.claims[team][:held] == state.claims[team]
            assert all(out.claims[t] == state.claims[t] for t in (1, 2, 3) if t != team)
            got.append((decision, out.claims[team][held:], replace(out, claims={}), g.random()))
        assert got[0] == got[1], strategy
        assert got[0][0].moves and got[0][1], strategy
        bids.append(max(c.bid for c in got[0][1]))
    # The comparison is of bids that are there: every seat that bids placed one above $0.
    exact, exact_named, sur, sur_named, ranked, ranked_named, mirror, mirror_named, *rivals = bids
    assert min(exact, exact_named, sur, sur_named, mirror, mirror_named, *rivals) > 0
    assert ranked == ranked_named == 0


# --------------------------------------------------------------------------- the decision
@pytest.mark.parametrize("h2h", [ONE_WIN, EACH_CATEGORY])
def test_a_decision_carries_the_gains_on_the_horizons_its_arm_s_bid_weighs(h2h):
    setup = league(pool=12) if h2h == ONE_WIN else every_category(league(pool=12))
    b = built_on(setup, plan_floor_cats=0.25, playoff_weight=2.0)
    plain = policy.surrogate(b)
    assert plain.moves and plain.basis is not None and plain.basis.bid is None
    # No bid named: the decision itself. Nor has a decision without a live basis one to carry.
    assert policy.with_bid(b, plain, None) is plain
    ranked = policy.ranking(b)
    assert policy.with_bid(b, ranked, bp.of(EVERY_KEY)) is ranked
    # An empty block: the policy is named, no other horizon is read.
    empty = policy.with_bid(b, plain, bp.DEFAULT)
    assert empty.basis == replace(plain.basis, bid=bp.DEFAULT)
    ev = mv.Evaluator(b.problem)
    figure = policy.SeasonFigure(b, 2.0)
    want_week = policy.gains_of(ev, "week", plain.moves)
    want_season = tuple(figure.move(m) or 0.0 for m in plain.moves)
    for block, week, season in (
        ({"week": 0.5}, want_week, ()),
        ({"season": 0.5}, (), want_season),
        (EVERY_KEY, want_week, want_season),
    ):
        got = policy.with_bid(b, plain, bp.of(block))
        # The moves and everything else of the decision are as they were.
        assert replace(got, basis=plain.basis) == plain
        assert got.basis == replace(plain.basis, bid=bp.of(block), week=week, season=season)
    # The season's figure counts a bracket game playoff_weight times: the arm's knob is read.
    once = policy.SeasonFigure(b, 1.0)
    assert any(figure.move(m) != once.move(m) for m in plain.moves)
    # A seat and a mirror rival of the arm carry it, and the arm's bid is part of their repr.
    s = replace(initial(setup), day=setup.start)
    u = replace(
        arm("U", "surrogate", plan_floor_cats=0.25, playoff_weight=2.0), bid=bp.of(EVERY_KEY)
    )
    rng = np.random.default_rng(5)
    seated = u.seat().decide(setup, s, 1, setup.projection, {}, {}, rng)
    assert seated.moves == plain.moves and seated.basis.bid == bp.of(EVERY_KEY)
    assert (seated.basis.week, seated.basis.season) == (want_week, want_season)
    mirror = op.of({"kind": "mirror"}, u.knobs, 0.1, u.fields, u.bid)
    assert mirror.decide(setup, s, 1, setup.projection, {}, {}, rng) == seated
    bare = replace(u, bid=None)
    assert bare.seat().decide(setup, s, 1, setup.projection, {}, {}, rng).basis == plain.basis
    assert repr(u.seat()) != repr(bare.seat())
    assert repr(mirror) != repr(op.of({"kind": "mirror"}, u.knobs, 0.1, u.fields))
    # A ranking seat bids $0 whatever its arm names.
    r = replace(arm("R", "ranking"), bid=bp.of(EVERY_KEY))
    assert r.seat().decide(setup, s, 1, setup.projection, {}, {}, rng).basis is None


# --------------------------------------------------------------------------- the counts
def test_a_faab_run_counts_the_dollars_at_the_bracket_the_weeks_at_zero_and_the_value_won():
    setup = league()  # five weeks of regular season, the sixth the bracket's
    s = initial(setup)
    assert ct.PACING == ("dollars_at_bracket", "weeks_at_zero", "value_won")
    assert tuple(ct.BIDS)[-3:] == ct.PACING and set(ct.PACING) <= set(ss.BIDS_NOTE)

    def at(**dollars: int):
        return replace(s, dollars={**s.dollars, **{int(k[1:]): v for k, v in dollars.items()}})

    tally = ct.Tally(setup)
    tally.day(5, at(t1=40, t2=0))
    tally.day(5, at(t1=40, t2=0))
    # The first simulated day of the bracket's first week, then a later one.
    tally.day(6, at(t1=30, t2=0))
    tally.day(6, at(t1=10, t2=0, t3=0))
    rows = tally.rows(replace(at(t1=10, t2=0, t3=0), value_won={1: 7.5}))
    assert [rows[t]["dollars_at_bracket"] for t in setup.teams] == [30.0, 0.0, 100.0, 100.0]
    assert [rows[t]["weeks_at_zero"] for t in setup.teams] == [0.0, 4 / 7, 1 / 7, 0.0]
    assert [rows[t]["value_won"] for t in setup.teams] == [7.5, 0.0, 0.0, 0.0]
    assert list(rows[1])[-len(ct.BIDS) :] == list(ct.BIDS)
    # A league whose bracket is not read has no first day of it; the others stand.
    flat = ct.Tally(league(bracket=False))
    flat.day(6, at(t1=30, t2=0))
    rows = flat.rows(at(t1=30, t2=0))
    assert rows[1]["dollars_at_bracket"] is None and rows[2]["weeks_at_zero"] == 1 / 7
    assert ct.pooled(list(rows.values()))["dollars_at_bracket"] is None
    # A season that ends before the bracket's first day has none either.
    short = ct.Tally(setup)
    short.day(5, at(t1=40))
    assert short.rows(at(t1=40))[1]["dollars_at_bracket"] is None
    # By priority no bid count at all.
    prio = ct.Tally(replace(setup, waivers="priority"))
    prio.day(6, replace(s, dollars={}))
    assert not set(ct.BIDS) & set(prio.rows(replace(s, dollars={}))[1])


# --------------------------------------------------------------------------- the reads
def test_the_bid_block_is_read_only_in_a_faab_league_by_a_seat_that_bids():
    faab = policy.Shape(waivers="faab")
    named = bp.of({"routine": 1})
    for tier in ("exact", "surrogate"):
        for shape in (faab, policy.Shape(waivers="faab", h2h=EACH_CATEGORY)):
            assert policy.bid_reads(rn.Arm("X", tier, KNOBS, {}, bid=named), shape) == policy.READ
        assert policy.bid_reads(rn.Arm("X", tier, KNOBS, {}, bid=named), policy.Shape()) == (
            "the world has no waivers and no budget"
        )
        assert policy.bid_reads(
            rn.Arm("X", tier, KNOBS, {}, bid=named), policy.Shape(waivers="priority")
        ) == ("waivers by priority carry no budget and no bid")
    assert policy.bid_reads(rn.Arm("X", "ranking", KNOBS, {}, bid=named), faab) == (
        "the ranking tier holds no gain in the engine's units: it bids $0"
    )
    static = rn.Arm("X", "static", KNOBS, {}, bid=named)
    assert policy.bid_reads(static, faab) == policy.STATIC
    # A mirror rival takes the arm's bid as it takes its other settings.
    assert policy.bid_reads(static, faab, mirrored=True) == policy.READ
    assert policy.bid_reads(rn.Arm("X", "ranking", KNOBS, {}, bid=named), faab, True) == policy.READ
    # The words that say what reads it are the block's own, beside the knobs' and the fields'.
    assert set(policy.WHEN_READ) == {*policy.KNOBS, *policy.FIELDS}
    assert "FAAB" in policy.BID_WHEN_READ


def test_a_bid_that_weighs_the_season_reads_the_playoff_weight():
    """The one knob that gains a reader: the season term's figure counts a bracket game
    ``playoff_weight`` times, so an arm whose bid weighs the season reads the knob in a FAAB
    league whose bracket is read, whatever its ``season_weight``. No other knob's row moves."""
    faab = policy.Shape(waivers="faab")
    weighs = bp.of({"season": 0.5})
    for tier in ("exact", "surrogate"):
        bare = rn.Arm("X", tier, KNOBS, {})
        named = replace(bare, bid=weighs)
        before, after = policy.reads(bare, faab), policy.reads(named, faab)
        assert before["playoff_weight"] == "season_weight is 0: there is no season term"
        assert after["playoff_weight"] == policy.READ
        assert {k for k in policy.KNOBS if before[k] != after[k]} == {"playoff_weight"}
        # Not without a bracket read, not outside a FAAB league, not at a weight of 0.
        flat = policy.Shape(waivers="faab", bracket=False)
        assert policy.reads(named, flat) == policy.reads(bare, flat)
        for shape in (policy.Shape(), policy.Shape(waivers="priority")):
            assert policy.reads(named, shape) == policy.reads(bare, shape)
        # (A block that leaves the three weeks a weight: one that leaves them none moves the
        # plan floor's row, the next test.)
        other = replace(bare, bid=bp.of({"week": 0.75, "routine": 1}))
        assert policy.reads(other, faab) == before
    ranking = replace(rn.Arm("X", "ranking", KNOBS, {}), bid=weighs)
    assert policy.reads(ranking, faab)["playoff_weight"] != policy.READ
    # Two arms apart only on the knob are two seats there, and one seat elsewhere, by name.
    a = replace(rn.Arm("A", "surrogate", KNOBS, {}), bid=weighs)
    b = replace(a, name="B", knobs={**KNOBS, "playoff_weight": 2.0})
    assert rn.same_seat(a, b, [faab], rivals=False) is None
    (why,) = rn.same_seat(a, b, [policy.Shape(waivers="priority")], rivals=False)
    assert why == (
        "playoff_weight (season_weight is 0: there is no season term; read by a season_weight "
        "above 0 on the exact or the surrogate tier, in a league whose bracket is read), and in "
        "a FAAB run by a seat that bids (the exact or the surrogate tier, a mirror rival) on an "
        "arm whose bid weighs the season (bid.season above 0), in a league whose bracket is read"
    )


def test_a_bid_that_gives_the_three_weeks_no_weight_reads_no_plan_floor():
    """The one row that loses a reader (found in review). In a FAAB league a seat that bids
    reads its league's plan floor for one thing: its typical gain on the three weeks until ten
    moves. An arm whose ``bid`` gives the week and the season the whole weight never reads that
    typical for a move of its set, so no value of the floor can move a bid of a surrogate seat
    or of a mirror rival: the row says so, and two arms apart only on the floor are one seat,
    refused by name. An exact arm that draws and executes its week plan still reads the floor
    (the plan's own, and a step's bid). No other row moves, and none at a weight above 0."""
    every = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    points = policy.Shape(scoring="points", waivers="faab")
    whole = bp.of({"week": 1})
    assert whole.three == 0 and bp.of({"week": 0.5, "season": 0.5}).three == 0
    for shape, name in ((every, "plan_floor_cats"), (points, "plan_floor_points")):
        bare = rn.Arm("X", "surrogate", KNOBS, {})
        named = replace(bare, bid=whole)
        before, after = policy.reads(bare, shape), policy.reads(named, shape)
        assert before[name] == policy.READ and after[name] == policy.NO_THREE
        assert {k for k in policy.KNOBS if before[k] != after[k]} == {name}
        halves = replace(bare, bid=bp.of({"week": 0.5, "season": 0.5}))
        assert policy.reads(halves, shape)[name] == policy.NO_THREE
        # A weight above 0 on the three weeks reads it, however small; so does an empty block.
        for block in ({"week": 0.75}, {"week": 0.5, "season": 0.25}, {}):
            assert policy.reads(replace(bare, bid=bp.of(block)), shape)[name] == policy.READ
        # A mirror rival takes the arm's block, and reads no more than the arm's seat.
        still = rn.Arm("X", "static", KNOBS, {})
        assert policy.reads(still, shape, mirrored=True)[name] == policy.READ
        assert policy.reads(replace(still, bid=whole), shape, True)[name] == policy.NO_THREE
        # The exact tier: through its week plan when it draws and executes it, else not at all.
        exact = rn.Arm("X", "exact", KNOBS, {}, bid=whole)
        assert policy.reads(exact, shape)[name] == policy.NO_THREE
        assert policy.reads(replace(exact, execute_plan=True), shape)[name] == policy.READ
        assert policy.reads(replace(exact, bid=None), shape)[name] == policy.READ
        # Outside a FAAB league the row is what it was, whatever the block.
        flat = replace(shape, waivers="priority")
        assert policy.reads(named, flat) == policy.reads(bare, flat)
    # In a one-win league the floor is the engine's own for an arm that would read it; one that
    # would not keeps its reason.
    one = policy.Shape(waivers="faab")
    surrogate = rn.Arm("X", "surrogate", KNOBS, {})
    assert policy.reads(surrogate, one)["plan_floor_cats"] == policy.ONE_WIN_FLOOR
    assert policy.reads(replace(surrogate, bid=whole), one)["plan_floor_cats"] == policy.NO_THREE
    # Two arms apart only on the floor: two seats with no bid named, one seat under the block.
    a = rn.Arm("A", "surrogate", KNOBS, {})
    b = replace(a, name="B", knobs={**KNOBS, "plan_floor_cats": 0.5})
    assert rn.same_seat(a, b, [every], rivals=False) is None
    (why,) = rn.same_seat(replace(a, bid=whole), replace(b, bid=whole), [every], rivals=False)
    assert why.startswith(f"plan_floor_cats ({policy.NO_THREE}; read by ")
    assert "bid.week and bid.season sum to 1" in policy.NO_THREE
    # One of the two at a weight above 0 reads it: two seats.
    part = replace(b, bid=bp.of({"week": 0.75}))
    assert rn.same_seat(replace(a, bid=bp.of({"week": 0.75})), part, [every], False) is None


def test_two_arms_apart_only_on_a_pace_at_k_0_are_the_same_seat_by_name():
    """A pace at ``k`` 0 follows no path, whatever its ``shape`` and ``reserve``: such a block
    bids as the block without the pace (found in review). Two arms apart only on that are one
    seat in a FAAB league too, refused by name: two paces at ``k`` 0 on two paths, and one
    against no ``bid`` at all. A pace that follows its path is read."""
    faab = policy.Shape(waivers="faab")
    a = rn.Arm("A", "surrogate", KNOBS, {})
    still = replace(a, name="B", bid=bp.of({"pace": {"k": 0, "shape": 3, "reserve": 0.9}}))
    other = replace(a, name="C", bid=bp.of({"pace": {"k": 0, "shape": 1, "reserve": 0.2}}))
    words = [f"bid ({policy.PACE_AT_REST}; read by {policy.PACE_WHEN_READ})"]
    for one, two in ((a, still), (still, other), (replace(a, bid=bp.DEFAULT), still)):
        assert rn.same_seat(one, two, [faab], rivals=False) == words
        assert rn.same_seat(two, one, [faab, policy.Shape()], rivals=False) == words
    assert "k 0" in policy.PACE_AT_REST and "above 0" in policy.PACE_WHEN_READ
    # With another key apart beside it the block is read, and so is a pace above k 0.
    dollar = bp.of({"pace": {"k": 0, "shape": 3, "reserve": 0.9}, "routine": 1})
    assert rn.same_seat(a, replace(a, name="D", bid=dollar), [faab], rivals=False) is None
    paced = replace(a, name="E", bid=bp.of({"pace": {"k": 0.5, "shape": 3, "reserve": 0.9}}))
    assert rn.same_seat(still, paced, [faab], rivals=False) is None
    # Where nobody reads a bid at all, the league's reason is the one given, as for any block.
    (why,) = rn.same_seat(a, still, [policy.Shape(waivers="priority")], rivals=False)
    assert why == (
        f"bid (waivers by priority carry no budget and no bid; read by {policy.BID_WHEN_READ})"
    )
    # Alike in the block as named: one arm twice, a check that the difference is zero.
    assert rn.same_seat(still, replace(still, name="F"), [faab], rivals=False) is None


def test_two_arms_apart_only_on_a_bid_nobody_reads_are_the_same_seat_by_name():
    a = rn.Arm("A", "surrogate", KNOBS, {})
    b = replace(a, name="B", bid=bp.of({"routine": 1}))
    faab = policy.Shape(waivers="faab")
    assert rn.same_seat(a, b, [faab], rivals=False) is None
    assert rn.same_seat(a, b, [policy.Shape(), faab], rivals=False) is None
    for shape, why in (
        (policy.Shape(), "the world has no waivers and no budget"),
        (policy.Shape(waivers="priority"), "waivers by priority carry no budget and no bid"),
    ):
        assert rn.same_seat(a, b, [shape], rivals=False) == [
            (
                f"bid ({why}; read by a seat that bids in a FAAB league: the exact or the "
                "surrogate tier, a mirror rival)"
            )
        ]
    ra, rb = replace(a, tier="ranking"), replace(b, tier="ranking")
    assert rn.same_seat(ra, rb, [faab], rivals=False) == [
        (
            "bid (the ranking tier holds no gain in the engine's units: it bids $0; read by a "
            "seat that bids in a FAAB league: the exact or the surrogate tier, a mirror rival)"
        )
    ]
    # Mirror rivals of a ranking arm bid by it in a pair.
    mirrors = {"kind": "mirror"}
    ma, mb = replace(ra, opponents=mirrors), replace(rb, opponents=mirrors)
    assert rn.same_seat(ma, mb, [faab], rivals=True) is None
    assert rn.same_seat(ma, mb, [faab], rivals=False) is not None
    # The policy in force is what is compared: an empty block is the default member, so the two
    # differ in nothing, as one arm named twice.
    assert rn.same_seat(a, replace(a, name="B", bid=bp.DEFAULT), [policy.Shape()], False) is None
    # Apart on a knob nobody reads and on the bid: both are named.
    c = replace(b, knobs={**KNOBS, "faab_sizing": 2.0})
    both = rn.same_seat(a, c, [policy.Shape(waivers="priority")], rivals=False)
    assert [w.split(" ")[0] for w in both] == ["faab_sizing", "bid"]


# --------------------------------------------------------------------------- the spec
def test_an_arm_s_spec_names_its_bid_and_a_bad_block_is_refused_by_name():
    spec = {"name": "A", "tier": "surrogate", "knobs": KNOBS}
    assert "bid" in rn.SPEC_KEYS and rn.arm_of(spec).bid is None
    named = rn.arm_of({**spec, "bid": EVERY_KEY})
    assert named.bid == bp.of(EVERY_KEY) and named.seat().bid == named.bid
    assert rn.arm_of({**spec, "bid": {}}).bid == bp.DEFAULT
    for block, words in (
        ({"paces": 1}, "bid key 'paces' is not one the simulator reads"),
        ({"week": 0.7, "season": 0.7}, "their sum is at most 1"),
        (None, "bid None: a mapping of week, season, pace, routine, rival_cap, shade"),
    ):
        with pytest.raises(ValueError, match=words):
            rn.arm_of({**spec, "bid": block})
    # The rivals of the arm: a mirror takes its bid, a market rival and a static seat none.
    setup = league()
    mirrored = rn.arm_of({**spec, "bid": EVERY_KEY, "opponents": {"kind": "mirror"}})
    others = rn.opponents_of(setup, mirrored, 1)
    assert set(others) == {2, 3, 4} and all(o.bid == named.bid for o in others.values())
    market = rn.opponents_of(setup, replace(named, opponents={"kind": "market"}), 1)
    assert not hasattr(market[2], "bid")


# --------------------------------------------------------------------------- the record
def test_a_run_s_record_names_an_arm_s_bid_and_one_without_has_no_key():
    """The payload's common part, the reads table and the line a run prints before any path
    (the dry run and the no-peek check print it), from the functions the command calls: a
    command's run is the look's."""
    a = rn.Arm("A", "surrogate", KNOBS, {})
    b = replace(a, name="B", bid=bp.of({"pace": PACE, "routine": 1}))

    def payload(arms):
        return ss.base_payload("replay", "x", datetime.now(UTC), "0" * 64, Path("f"), {}, 1, arms)

    none = payload({"a": a, "b": replace(a, name="B")})
    assert "bid" not in none and "bid_note" not in none
    assert payload(None).keys() == none.keys()
    named = payload({"a": a, "b": b})
    assert set(named) - set(none) == {"bid", "bid_note"}
    # Every key with its value in force, for the arm that names one only.
    assert named["bid"] == {
        "b": {
            "week": 0.0,
            "season": 0.0,
            "pace": {"k": 1.0, "shape": 1.0, "reserve": 0.2},
            "routine": 1,
            "rival_cap": False,
            "shade": None,
        }
    }
    assert named["bid_note"] == ss.BID_NOTE and "recommended" not in ss.BID_NOTE
    assert {k: v for k, v in named.items() if k in none} | {"started_at": 0} == none | {
        "started_at": 0
    }
    # The reads table: a row for the block under the arm that names one.
    faab, prio = policy.Shape(waivers="faab"), policy.Shape(waivers="priority")
    table = ss.reads_of({"a": a, "b": b}, [faab, prio], rivals=True)
    assert all(set(by) == {"knobs", "fields"} for by in table["a"].values())
    assert table["b"][faab.label()]["bid"] == policy.READ
    assert table["b"][prio.label()]["bid"] == "waivers by priority carry no budget and no bid"
    # The line: the block in words, and why the league does not read it when it does not.
    assert ss.bid_lines({"a": a, "b": replace(a, name="B")}, [faab], True) == []
    assert ss.bid_lines({"a": a, "b": b}, [faab], True) == [
        (
            "bid policy, arm B (B): week 0, season 0, the three weeks 1, pace k 1 shape 1 "
            "reserve 0.2, a routine claim $1, no rival cap, no shade"
        )
    ]
    (line,) = ss.bid_lines({"B": b}, [prio], False)
    assert line.startswith("bid policy, arm B: week 0, ") and line.endswith(
        "; not read in this run: waivers by priority carry no budget and no bid"
    )
    # The counts' notes say each of the three.
    assert all(ss.BIDS_NOTE[m] for m in ct.PACING)
