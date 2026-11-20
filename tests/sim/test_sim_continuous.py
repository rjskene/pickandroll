"""Continuous waivers (#172, PR Fc): every unowned player is on waivers at all times, so every add
is a claim, decided the next morning or on a dropped player's clear date by the league's waivers,
by priority or by sealed bids, in the same pass of the clear morning as a dropped player's claim.
The rule, the morning, the seats and their bids, the market rival's draw, the audit, the counts
and Rule 1's pins. Made-up leagues, fixed seeds. A test whose seat weighs runs in both
head-to-head formats, or says why it names one (the format PR's Rule 4)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.sim import audit, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import LOST, WON, Claim, Resolved, SimState, Waiting, initial
from tests.sim.sim_league import (
    KNOBS,
    MONDAY,
    arm,
    every_category,
    make_setup,
    of_format,
    recorded_lines,
)
from tests.sim.test_sim_seasons import rounded

DAY = timedelta(1)
FORMATS = (ONE_WIN, EACH_CATEGORY)
KINDS = ("priority", "faab")


def league(waivers: str = "priority", rule: str = CONTINUOUS, **kw):
    """Four seats of five drafted players on six slots (one spot open each), waivers after two
    days, under continuous waivers unless ``rule`` says otherwise."""
    return replace(make_setup(teams=4, **kw), waivers=waivers, waiver_days=2, waiver_rule=rule)


def spots_of(setup):
    return setup.spots(), Counter(setup.roster_slots)


def on_waivers(state: SimState, by: int, clears: date, *players: int) -> SimState:
    return replace(state, waivers={**state.waivers, **{k: Waiting(clears, by) for k in players}})


def morning(setup, s: SimState, day: date, status=None, value=None) -> SimState:
    """The morning of ``day`` as the runner plays it: the cleared held players back, the rosters
    trimmed and the churns' held players gone (``policy.arrive``, Fc's review; with ``status``
    and ``value`` given), then the claims due decided, then the rest of yesterday's queue
    landed, in the day's rotation."""
    spots, counts = spots_of(setup)
    order = rn._rotation(setup.teams, (day - setup.start).days)
    s = policy.arrive(s, order, spots, status, value, None, (day, 2))
    s = policy.clear_waivers(s, day, spots, counts, status or {}, setup.waiver_days, setup.bidding)
    return policy.land(s, order, spots, counts, status, value, None, (day, 2), arrived=True)


# --------------------------------------------------------------------------- the rule
def test_the_rule_is_dropped_by_default_and_named_only_with_waivers():
    assert shapes.WAIVER_RULES == (DROPPED, CONTINUOUS) == ("dropped", "continuous")
    for waivers in ("none", *KINDS):
        assert shapes.parse_waiver_rule(waivers, None) == DROPPED
    for waivers in KINDS:
        for rule in shapes.WAIVER_RULES:
            assert shapes.parse_waiver_rule(waivers, f" {rule.upper()}") == rule
    with pytest.raises(ValueError, match="--waiver-rule continuous: which adds are claims is a "):
        shapes.parse_waiver_rule("none", "continuous")
    with pytest.raises(ValueError, match="--waiver-rule fifo: one of dropped, continuous"):
        shapes.parse_waiver_rule("faab", "fifo")
    with pytest.raises(ValueError, match="waiver rule continuous with waivers none: which adds"):
        shapes.LeagueRules(waiver_rule=CONTINUOUS)
    with pytest.raises(ValueError, match="waiver rule 'fifo' is not one of dropped, continuous"):
        shapes.LeagueRules(waivers="priority", waiver_rule="fifo")
    plain = shapes.LeagueRules(waivers="priority")
    every = replace(plain, waiver_rule=CONTINUOUS)
    assert plain == shapes.LeagueRules(waivers="priority", waiver_rule=DROPPED) != every
    assert every.continuous and not plain.continuous and not shapes.PLAIN.continuous
    assert policy.executions_of("none", CONTINUOUS) == policy.EXECUTIONS
    assert policy.executions_of("priority") == policy.EXECUTIONS_PRIORITY
    assert policy.executions_of("faab", DROPPED) == policy.EXECUTIONS_FAAB
    assert policy.executions_of("priority", CONTINUOUS) == "claims_only_by_priority"
    assert policy.executions_of("faab", CONTINUOUS) == "claims_only_by_sealed_bids"
    setup = league()
    assert setup.continuous and not replace(setup, waiver_rule=DROPPED).continuous
    assert not replace(setup, waivers="none").continuous and not make_setup().continuous


def test_the_label_says_continuous_and_the_payload_records_the_rule_in_every_waiver_run():
    plain = shapes.LeagueRules(waivers="priority")
    assert plain.label() == "the nine categories, no held slot, waivers by priority after 2 days"
    every = replace(plain, waiver_rule=CONTINUOUS)
    assert every.label() == (
        "the nine categories, no held slot, continuous waivers by priority, a dropped player "
        "after 2 days"
    )
    faab = shapes.LeagueRules(waivers="faab", h2h=EACH_CATEGORY, waiver_rule=CONTINUOUS)
    assert faab.label() == (
        "the nine categories, every category counted, no held slot, continuous waivers by FAAB, "
        "a dropped player after 2 days, $100 a team, the rivals' bids x1"
    )
    assert "waiver_rule" not in shapes.PLAIN.payload()
    assert list(plain.payload())[-3:] == ["waivers", "waiver_days", "waiver_rule"]
    assert plain.payload()["waiver_rule"] == DROPPED
    assert every.payload() == {**plain.payload(), "waiver_rule": CONTINUOUS}
    assert faab.payload()["waiver_rule"] == CONTINUOUS and faab.payload()["budget"] == 100


# --------------------------------------------------------------------------- the morning
def two_add_x(waivers: str, rule: str, bids=(0, 0), dollars=None):
    """Teams 2 and 3 both add x, a free agent nobody dropped, on day one, each dropping its last
    drafted player. The day's rotation the next morning lands team 2 first; the first waiver
    order (the draft's reverse) has team 3 ahead of team 2. The state the morning after."""
    setup = league(waivers, rule)
    spots, _ = spots_of(setup)
    s = initial(setup)
    if dollars:
        s = replace(s, dollars={**s.dollars, **dollars})
    x = min(s.pool)
    a2, a3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    for team, drop in ((2, a2), (3, a3)):
        s = policy.queue(s, team, policy.Decision((mv.Move(x, drop),)), 1, 4, False, spots, setup)
    if rule == CONTINUOUS:
        # Every add is a claim: placed today, decided tomorrow morning, its bid set here.
        assert s.pending == {2: (), 3: ()}
        assert [c.clears for t in (2, 3) for c in s.claims[t]] == [setup.start + DAY] * 2
        s = replace(s, claims={t: (replace(s.claims[t][0], bid=b),) for t, b in zip((2, 3), bids)})
    else:
        assert s.claims == {2: (), 3: ()} and s.pending[2] == (mv.Move(x, a2),)
    assert rn._rotation(setup.teams, 1) == [2, 3, 4, 1] and s.priority == (4, 3, 2, 1)
    return setup, s, morning(setup, s, setup.start + DAY), x, a2, a3


@pytest.mark.parametrize("waivers", KINDS)
def test_two_adds_of_one_undropped_player_go_by_the_rotation_with_the_rule_not_named(waivers):
    _, s, out, x, a2, a3 = two_add_x(waivers, DROPPED)
    assert x in out.active(2) and a2 not in out.active(2) and a3 in out.active(3)
    assert out.gone_by == {3: 1} and out.resolved == () and out.priority == s.priority


def test_under_the_rule_by_priority_the_better_priority_takes_him_and_goes_to_the_back():
    _, s, out, x, a2, a3 = two_add_x("priority", CONTINUOUS)
    assert x in out.active(3) and a3 in out.pool and a2 in out.active(2) and x not in out.pool
    assert out.resolved == (Resolved(3, x, a3, WON, True), Resolved(2, x, a2, LOST, True))
    assert out.priority == (4, 2, 1, 3) and out.claims == {} and out.gone_by == {}
    # His drop waits his days, as any dropped player.
    assert out.waivers == {a3: Waiting(s.day + DAY + 2 * DAY, 3)}


def test_under_the_rule_by_faab_the_higher_bid_takes_him_and_pays_and_a_tie_goes_to_priority():
    _, s, out, x, _, _ = two_add_x("faab", CONTINUOUS, bids=(7, 5))
    assert x in out.active(2) and out.dollars == {1: 100, 2: 93, 3: 100, 4: 100}
    assert out.priority == s.priority  # no tie: the order stays
    _, _, tie, x, _, a3 = two_add_x("faab", CONTINUOUS, bids=(5, 5))
    assert x in tie.active(3) and a3 in tie.pool and tie.dollars[3] == 95
    assert tie.priority == (4, 2, 1, 3)
    # A team at $0 still wins a claim at $0.
    _, _, free, x, *_ = two_add_x("faab", CONTINUOUS, dollars={2: 0, 3: 0})
    assert x in free.active(3) and free.dollars[3] == 0
    assert free.claim_counts[3]["won_free"] == 1


def test_a_claim_lost_under_the_rule_makes_no_drop_and_no_held_slot_move():
    """Team 3, full with an IL slot, claims x with no drop and a held-slot move; team 2 claims him
    with a drop; team 4, first in the order, claims him too and takes him. Neither loser's drop
    nor its held-slot move is made."""
    setup = replace(league(held_slots=("IL",)))
    spots, _ = spots_of(setup)
    s = initial(setup)
    x, hurt = sorted(s.pool)[:2]
    s = replace(s, rosters={**s.rosters, 3: (*s.rosters[3], (hurt, "BN"))}, pool=s.pool - {hurt})
    a2, a4 = setup.rosters[2][-1][0], setup.rosters[4][-1][0]
    for team, decision in (
        (3, policy.Decision((mv.Move(x),), ((hurt, "IL"),))),
        (2, policy.Decision((mv.Move(x, a2),))),
        (4, policy.Decision((mv.Move(x, a4),))),
    ):
        s = policy.queue(s, team, decision, 1, 4, False, spots, setup)
    assert s.claims[3] == (Claim(mv.Move(x), setup.start, setup.start + DAY, 1, ((hurt, "IL"),)),)
    assert s.pending_held[3] == ()
    out = morning(setup, s, setup.start + DAY)
    assert x in out.active(4) and a4 in out.pool
    assert dict(out.rosters[3])[hurt] == "BN" and a2 in out.active(2)
    assert [r.outcome for r in out.resolved] == [WON, LOST, LOST]


def test_a_dropped_player_still_waits_his_days_and_an_undropped_one_clears_tomorrow():
    setup = league()
    spots, _ = spots_of(setup)
    s = initial(setup)
    x, y = sorted(s.pool)[:2]
    clears = setup.start + 3 * DAY
    s = on_waivers(s, 1, clears, x)
    d2, e2 = setup.rosters[2][-1][0], setup.rosters[2][-2][0]
    s = policy.queue(
        s, 2, policy.Decision((mv.Move(x, d2), mv.Move(y, e2))), 2, 4, False, spots, setup
    )
    assert [(c.move.add, c.clears) for c in s.claims[2]] == [(x, clears), (y, setup.start + DAY)]
    tomorrow = morning(setup, s, setup.start + DAY)
    assert y in tomorrow.active(2) and x in tomorrow.pool
    assert [c.move.add for c in tomorrow.claims[2]] == [x]
    later = morning(setup, replace(tomorrow, day=setup.start + DAY), setup.start + 2 * DAY)
    assert x in later.pool and later.resolved == ()
    last = morning(setup, replace(later, day=setup.start + 2 * DAY), clears)
    assert x in last.active(2) and last.claims == {}
    # The seat's problem reads the same dates, and every candidate is a claim.
    built = policy.problem_of(setup, s, 1, KNOBS, setup.projection, {}, {})
    assert built.problem.effective[x] == clears and built.problem.effective[y] == s.day + DAY
    assert built.problem.claims == frozenset(k for k, _ in built.problem.candidates)


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_draft_s_leftovers_are_claims_from_the_first_morning_in_the_seat_s_problem(h2h):
    """Nobody is on waivers on day one, and every leftover is a claim, effective tomorrow; with
    the rule not named only a player on waivers is (none on day one). The engine then offers a
    churn on any add only when the held player is worth nothing net of his return (#221)."""
    setup = of_format(league(), h2h)
    s = initial(setup)
    assert s.waivers == {} and s.pool == frozenset(setup.pool)
    p = policy.problem_of(setup, s, 1, KNOBS, setup.projection, {}, {}).problem
    keys = frozenset(k for k, _ in p.candidates)
    assert keys and p.claims == keys and set(p.effective.values()) == {setup.start + DAY}
    plain = of_format(league(rule=DROPPED), h2h)
    assert policy.problem_of(plain, s, 1, KNOBS, plain.projection, {}, {}).problem.claims == set()
    spots, _ = spots_of(setup)
    x = min(s.pool)
    out = policy.queue(s, 1, policy.Decision((mv.Move(x),)), 1, 4, False, spots, setup)
    assert out.claims[1][0].clears == setup.start + DAY and out.pending[1] == ()
    assert x in morning(setup, out, setup.start + DAY).active(1)


def test_a_claim_is_charged_to_the_week_of_the_day_before_it_lands_and_counts_in_its_week():
    """Placed on a Sunday, a claim on a player nobody dropped clears Monday and is charged to the
    week ending (a free agent's add, made that Sunday, was charged there too). Four adds this
    week on a cap of four: no claim charged to it is placed (``NO_ADDS``)."""
    setup = league()
    spots, _ = spots_of(setup)
    sunday = MONDAY + 6 * DAY
    s = replace(initial(setup), day=sunday)
    x, y = sorted(s.pool)[:2]
    out = policy.queue(s, 2, policy.Decision((mv.Move(x),)), 1, 4, False, spots, setup)
    assert [(c.clears, c.week) for c in out.claims[2]] == [(sunday + DAY, 1)]
    full = policy.queue(
        replace(s, adds_used={2: 4}), 2, policy.Decision((mv.Move(x),)), 1, 4, False, spots, setup
    )
    assert full.claims[2] == ()
    # The daily cap counts the claims: one a day places one.
    two = policy.queue(s, 2, policy.Decision((mv.Move(x), mv.Move(y))), 1, 4, False, spots, setup)
    assert [c.move.add for c in two.claims[2]] == [x]


# --------------------------------------------------------------------------- the bids
def test_every_add_of_a_seat_that_bids_carries_the_live_bid_and_the_ranking_tier_s_bids_nothing():
    """A seat's decision with a live basis on a player nobody dropped: under the rule a claim with
    the live rule's bid (``policy.live_bid``, the mark W); with it not named a free agent's add,
    which bids nothing. A decision without a basis (the ranking tier) bids $0."""
    setup = league("faab")
    spots, _ = spots_of(setup)
    s = initial(setup)
    x = min(s.pool)
    move = mv.Move(x, setup.rosters[2][-1][0])
    live = policy.Decision((move,), basis=policy.Basis(policy.LIVE, (9.0,), floor=3.0))
    out = policy.queue(s, 2, live, 1, 4, False, spots, setup)
    (c,) = out.claims[2]
    assert c.bid == policy.live_bid(9.0, [9.0], 3.0, 100, None) == 3
    assert out.recent[2] == ((s.day, 9.0),)
    dropped = policy.queue(s, 2, live, 1, 4, False, spots, replace(setup, waiver_rule=DROPPED))
    assert dropped.pending[2] == (move,) and dropped.claims[2] == ()
    ranking = policy.queue(s, 2, policy.Decision((move,)), 1, 4, False, spots, setup)
    assert ranking.claims[2][0].bid == 0


def test_a_market_rival_draws_its_noise_on_every_pick_under_the_rule_and_as_today_without():
    setup = replace(league("faab"), market_rate=1.0)
    spots, _ = spots_of(setup)
    x = min(initial(setup).pool)
    setup = replace(setup, market={**setup.market, x: 2 * max(setup.market.values())})
    s = initial(setup)

    def decide(setup_):
        return op.Market(1.0).decide(
            setup_, s, 2, setup_.projection, {}, {}, np.random.default_rng(5)
        )

    every = decide(setup)
    (move,) = every.moves
    assert move.add == x and x not in s.waivers and len(every.basis.noise) == 1
    out = policy.queue(s, 2, every, 1, 4, False, spots, setup)
    (noise,) = every.basis.noise
    gain = setup.market[x] - setup.market[move.drop]
    assert out.claims[2][0].bid == policy.rival_bid(gain, gain, 100, 1.0, noise)
    # The rule not named: the same draw and the same move, no noise on a free agent's pick.
    plain = decide(replace(setup, waiver_rule=DROPPED))
    assert plain.moves == every.moves and plain.basis.noise == ()
    # On a pick on waivers it draws under either rule, as in PR Fb.
    waiting = on_waivers(s, 1, s.day + 2 * DAY, x)
    for rule in (DROPPED, CONTINUOUS):
        d = op.Market(1.0).decide(
            replace(setup, waiver_rule=rule), waiting, 2, setup.projection, {}, {},
            np.random.default_rng(5),
        )  # fmt: skip
        assert d.basis.noise == (noise,)


# --------------------------------------------------------------------------- the audit
def day_of(state: SimState) -> audit.Day:
    return audit.Day(state.day, 0, state, {}, {})


def test_the_audit_holds_claims_only_under_the_rule_and_catches_an_add_outside_a_claim():
    names = [r.name for r in audit.rules_of("priority", CONTINUOUS)]
    assert names[-3:] == ["waiver_wait", "claim_priority", "claims_only"]
    names = [r.name for r in audit.rules_of("faab", CONTINUOUS)]
    assert names[-5:] == ["waiver_wait", "budget_floor", "bid_paid", "bid_order", "claims_only"]
    for waivers in ("none", *KINDS):
        assert "claims_only" not in [r.name for r in audit.rules_of(waivers)]
        assert audit.rules_of(waivers) == audit.rules_of(waivers, DROPPED)
    # The league's bracket has a round: its own audit reads the bracket's rule too (PR bracket).
    assert audit.Auditor(league()).rules == audit.rules_of("priority", CONTINUOUS, bracket=True)
    # An honest morning: the player who joined came by a claim won that morning.
    setup, before, after, x, _, _ = two_add_x("priority", CONTINUOUS)
    assert list(audit.claims_only(setup, day_of(after), day_of(before))) == []
    # A record in which he landed without one: caught.
    forged = replace(after, resolved=())
    assert list(audit.claims_only(setup, day_of(forged), day_of(before))) == [
        (3, f"player {x} joined without a claim won this morning")
    ]
    # The rule not named, a free agent's landing is no claim: the rule is a continuous run's.
    plain_setup, b, a, y, *_ = two_add_x("priority", DROPPED)
    assert [w for _, w in audit.claims_only(plain_setup, day_of(a), day_of(b))] == [
        f"player {y} joined without a claim won this morning"
    ]


# --------------------------------------------------------------------------- the seats move
def room_of(setup, seed: int = 1, path: int = 0):
    """A season of the made-up league: a surrogate seat in seat 1 and a ranking seat in seat 2,
    a market rival at 0.3 a day in seat 3 and a static seat in seat 4; the day states with it."""
    u, r = arm("U", "surrogate", opponents="market"), arm("R", "ranking", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, seed, path)
    seen: list[SimState] = []
    variant = {1: u.seat(), 2: r.seat(), 3: op.Market(0.3), 4: op.Static()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda d: seen.append(d.state))
    return result, seen


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("waivers", KINDS)
def test_a_surrogate_seat_and_a_ranking_seat_land_adds_under_the_rule(waivers, h2h):
    """The test that catches a rule under which nobody moves (the lesson of PR D4c): both seats
    land adds, every add is a claim won (the counts' ``landed`` is ``claims_won`` and ``gone``
    is ``claims_failed``), the static seat claims nothing, the audit finds nothing, and in a
    FAAB league every team's dollars are its budget less its won bids."""
    setup = of_format(league(waivers, pool=12), h2h)
    result, seen = room_of(setup)
    assert result.breaches == ()
    counts = result.counts
    assert counts[1]["landed"] >= 1 and counts[2]["landed"] >= 1, counts
    for t in setup.teams:
        assert counts[t]["landed"] == counts[t]["claims_won"], counts[t]
        assert counts[t]["gone"] == counts[t]["claims_failed"], counts[t]
    assert counts[4]["claims_placed"] == 0
    won = [r for s in seen for r in s.resolved if r.outcome == WON]
    assert len(won) == result.executed
    if waivers == "faab":
        for t in setup.teams:
            paid = sum(r.bid for r in won if r.team == t)
            assert seen[-1].dollars[t] == setup.budget - paid == setup.budget - counts[t]["dollars_spent"]  # fmt: skip


# --------------------------------------------------------------------------- Rule 1
def season_digest(setup, seed: int = 1, path: int = 0) -> str:
    """SHA-256 of a made-up season's outcome: a surrogate seat in seat 1 and a ranking seat in
    seat 2 among market rivals at 0.3 a day, every seat's counts and summary, every morning's
    decisions, the last day's rosters, order and dollars, and the solves, moves and breaches,
    each figure rounded to nine places.

    The three count keys PR F2 adds to a FAAB run (``counts.PACING``: the dollars at the
    bracket, the weeks at $0, the value won) are set aside, so the digests main pinned before
    them still compare every figure they covered; the new keys have their own tests
    (``test_sim_bid_seat.py``)."""
    u, r = arm("U", "surrogate", opponents="market"), arm("R", "ranking", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, seed, path)
    days: list[SimState] = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: u.seat(), 2: r.seat()}
    (res,) = rn.simulate(setup, w, [variant], on_day=lambda d: days.append(d.state))
    last = days[-1]
    figures = rounded(
        {
            "counts": {
                str(t): {m: x for m, x in row.items() if m not in ct.PACING}
                for t, row in res.counts.items()
            },
            "summaries": {str(t): s for t, s in res.summaries.items()},
            "decided": [
                [s.day.isoformat(), x.team, x.add, x.drop, x.outcome, x.behind, x.bid]
                for s in days
                for x in s.resolved
            ],
            "rosters": {str(t): sorted(k for k, _ in ro) for t, ro in last.rosters.items()},
            "priority": list(last.priority),
            "dollars": {str(t): d for t, d in last.dollars.items()},
            "moves": [res.solves, res.executed, res.gone, len(res.breaches)],
        }
    )
    return hashlib.sha256(json.dumps(figures, sort_keys=True, default=str).encode()).hexdigest()


#: Rule 1's pins: the made-up season (:func:`season_digest`, seed 1, path 0) with the rule not
#: named, by priority in one win and by FAAB under every category (the two league kinds, one in
#: each format), as main 2708829 (the format PR's) gave them
#: (``~/sim-notes/vm/scratch/fc/rule1_pins.py``, the same digest, run on main and on this PR).
BEFORE_PRIORITY = "aa3bb991587f0521b435326de3cae9e576964b9319ec1c8ae3c86e548e2810f8"
BEFORE_FAAB = "9ec1a88b9ec0eaffac5a4b68aaccb36141a9e8d4a7596cfe8f1bc9e0f5cc62e4"


def test_rule_1_with_the_rule_not_named_a_season_plays_as_the_format_pr_s():
    base = make_setup(teams=4, pool=12)
    priority = replace(base, waivers="priority", waiver_days=2)
    faab = every_category(replace(base, waivers="faab", waiver_days=2))
    assert priority.waiver_rule == faab.waiver_rule == DROPPED
    assert season_digest(priority) == BEFORE_PRIORITY
    assert season_digest(faab) == BEFORE_FAAB


#: The league block with the rule not named, every key byte for byte as main 2708829 gave it
#: (the rules' ``waiver_rule`` aside, the one key Rule 1 adds, and PR Fd's ``rival_bids`` in a
#: FAAB run, ``assumed`` when nothing is named), over the six rules of
#: :data:`BLOCK_RULES` (``~/sim-notes/vm/scratch/fc/block_pin.py``, on main and on this PR).
BLOCKS_BEFORE = "121dfc4cce6333c240b3cc590219d088b2570e9d3c4b3801121e5e488706b631"
FAAB_NOTE_BEFORE = "7fe817806c4fd4f7681d9dced83373d83293666f2eca6fc87cde486c026fa694"
BLOCK_RULES = (
    shapes.PLAIN,
    shapes.LeagueRules(waivers="priority"),
    shapes.LeagueRules(waivers="faab"),
    shapes.LeagueRules(waivers="priority", h2h=EACH_CATEGORY, waiver_days=3),
    shapes.LeagueRules(waivers="faab", h2h=EACH_CATEGORY, budget=50, rival_scale=2.0),
    shapes.LeagueRules("points", shapes.POINTS_DEFAULT, ("IL",), "faab"),
)


def block_of(rules: shapes.LeagueRules) -> dict:
    return ss.league_block(shapes.FIXED_GRID, [shapes.visit(0, shapes.FIXED_GRID)], [], rules)


def test_rule_1_with_the_rule_not_named_the_league_block_and_its_notes_are_today_s():
    blocks = []
    for rules in BLOCK_RULES:
        block = block_of(rules)
        assert block["rules"].pop("waiver_rule", DROPPED) == DROPPED
        assert block["rules"].pop("rival_bids", shapes.ASSUMED) == shapes.ASSUMED
        assert "waiver_rule_note" not in block
        blocks.append(block)
    assert hashlib.sha256(json.dumps(blocks, sort_keys=True).encode()).hexdigest() == BLOCKS_BEFORE
    assert hashlib.sha256(ss.FAAB_NOTE.encode()).hexdigest() == FAAB_NOTE_BEFORE


@pytest.mark.parametrize("waivers", KINDS)
def test_a_continuous_run_s_league_block_says_every_add_is_a_claim(waivers):
    rules = shapes.LeagueRules(waivers=waivers, waiver_rule=CONTINUOUS)
    block = block_of(rules)
    assert block["rules"]["waiver_rule"] == CONTINUOUS
    assert block["waiver_rule_note"] == ss.WAIVER_RULE_NOTE
    assert "every add is a claim" in ss.WAIVER_RULE_NOTE
    assert "landed equals claims_won" in ss.WAIVER_RULE_NOTE
    if waivers == "faab":
        note = block["faab_note"]
        assert note == ss.FAAB_NOTE_CONTINUOUS != ss.FAAB_NOTE
        assert ss.FAAB_FREE not in note and ss.FAAB_EVERY in note
        assert note.replace(ss.FAAB_EVERY, ss.FAAB_FREE) == ss.FAAB_NOTE
    else:
        assert "faab_note" not in block
