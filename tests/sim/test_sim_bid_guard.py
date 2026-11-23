"""The bid policy beside the season guard and the week's stake (#172, PR F2 built on the guard
PR). The two PRs edit the same things: an arm and its seat (a ``bid`` block; a guard and a
stake), the seat's decision (the guard and the stake decide its moves, the block what its claims
bid on), the same-seat check, the counts of a row and the one declaration of the counts that
part by construction, and the screen's list. This file holds what each must still do with the
other in force: an arm that names all three.

One thing is held here and nowhere else: **the bid policy reads the season figure with no
stake** (the lead's working default for the guard PR). A stake moves the season term's weight
inside the seat's decision; what a claim bids on at ``bid.season`` is the move's season figure
as it is, whatever the week's stake.

Made-up leagues, fixed seeds. No test here pins a literal outcome of a replay: each compares
arms of one world, or a decision with the engine asked directly."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from pickandroll.sim.shapes import CONTINUOUS
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, recorded_lines
from tests.sim.test_sim_bid_seasons import EVERY_KEY, PATH, RIVALS, in_force, public
from tests.sim.test_sim_guard import DEAD, SEASON_KEYS, disagreeing, spec
from tests.sim.test_sim_screen import BID_NAMES, base, differ

FORMATS = (ONE_WIN, EACH_CATEGORY)
#: A season weight at which the term is alive and small beside a week's gain.
A_WEIGHT = 0.0001
#: A block that weighs the season alone: what a claim bids on is its move's season figure.
ON_THE_SEASON = {"season": 1.0}


def named(name="A", tier="surrogate", opponents="static", knobs=None, **more) -> rn.Arm:
    """An arm from its spec, its categories plan floor at 0.1 as the bid policy's seasons have
    it; ``more`` names its ``bid`` block, its guard and its stake."""
    floors = {"plan_floor_cats": 0.1, **(knobs or {})}
    return rn.arm_of(spec(name, tier, opponents, floors, **more))


# --------------------------------------------------------------------------- the arm, the seat
def test_an_arm_names_a_bid_a_guard_and_a_stake_and_its_seat_carries_all_three():
    """One spec names the three. The arm holds each as its own PR parses it, the seat is made
    with all three, and a seat apart in any one of them is another seat (its repr is the
    runner's key for a shared decision)."""
    knobs = {"season_weight": A_WEIGHT}
    a = named(knobs=knobs, bid=EVERY_KEY, guard="off", stake=0.5)
    assert a.bid == bp.of(EVERY_KEY)
    assert (a.guard, a.stake, a.named) == (policy.OFF, 0.5, policy.SEASON_FIELDS)
    seat = a.seat()
    assert (seat.bid, seat.guard, seat.stake) == (a.bid, policy.OFF, 0.5)
    others = (
        named(knobs=knobs, guard="off", stake=0.5),
        named(knobs=knobs, bid=EVERY_KEY, stake=0.5),
        named(knobs=knobs, bid=EVERY_KEY, guard="off"),
    )
    assert len({repr(x.seat()) for x in (a, *others)}) == 4
    # The spec's keys: both PRs' are read, and a key of neither is still refused by name.
    assert {"bid", *policy.SEASON_FIELDS} <= set(rn.SPEC_KEYS)
    with pytest.raises((KeyError, ValueError), match="stakes"):
        named(knobs=knobs, bid=EVERY_KEY, stakes=0.5)


def test_the_same_seat_check_reads_the_block_and_the_two_fields_side_by_side():
    """``run.same_seat`` names what a pair differs in and neither arm reads. With both PRs:

    - on the ranking tier in a FAAB league a pair apart on its stake and on its block is one
      seat, and the refusal names the stake and then the block, each with its own reason;
    - on the surrogate tier in a FAAB league a pair apart on the block alone, both arms on the
      guard off with a stake, is two seats (the block is read), and so is a pair apart on the
      stake alone with a block in both arms;
    - with no waivers the surrogate pair apart on the block alone is one seat (nothing bids),
      and apart on the stake alone it is still two."""
    faab = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    none = policy.Shape(h2h=EACH_CATEGORY)
    knobs = {"season_weight": A_WEIGHT}

    def pair(tier, **b):
        fields = {"knobs": knobs, "stake": 0.5, "bid": ON_THE_SEASON}
        if tier != "ranking":
            fields["guard"] = "off"
        return named("A", tier, **fields), named("B", tier, **{**fields, **b})

    said = rn.same_seat(*pair("ranking", stake=1.0, bid={"season": 0.5}), [faab])
    assert said is not None and len(said) == 2
    assert said[0].startswith("stake (") and said[1].startswith("bid (")
    assert rn.same_seat(*pair("surrogate", bid={"season": 0.5}), [faab]) is None
    assert rn.same_seat(*pair("surrogate", stake=1.0), [faab]) is None
    quiet = rn.same_seat(*pair("surrogate", bid={"season": 0.5}), [none])
    assert quiet is not None and len(quiet) == 1 and quiet[0].startswith("bid (")
    assert rn.same_seat(*pair("surrogate", stake=1.0), [none]) is None


# --------------------------------------------------------------------------- the figure a bid reads
@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_a_bid_on_the_season_reads_the_figure_with_no_stake(tier, h2h):
    """The guard PR's league where the three weeks and the season disagree, by FAAB, on day one
    of a week whose stake is 1: a seat with a stake of 1 decides on the split figure (the
    season term counts nothing after the running week), and its claims at ``bid.season`` 1 are
    still sized on each move's season figure as it is (``policy.SeasonFigure``), the figure a
    seat with no stake would size them on. The two figures differ for the decided move, so the
    test would fail if the bid read the split one."""
    setup = replace(
        disagreeing(holds=DEAD, h2h=h2h), waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS
    )
    state = replace(initial(setup), stakes={1: 1.0})
    knobs = {**KNOBS, "season_weight": A_WEIGHT}
    built = policy.problem_of(setup, state, 1, knobs, setup.projection, {}, {})
    assert built is not None
    staked = policy.guarded(built, setup, state, policy.BLOCK, 1.0)
    assert (staked.stake, staked.level) == (1.0, 1.0)
    rule = bp.of(ON_THE_SEASON)
    decision = policy.decide(staked, tier, with_plan=False)
    assert decision.moves
    plain = policy.SeasonFigure(built, policy.knob(knobs, "playoff_weight"))
    split = policy.season_figure_of(staked)
    assert type(split) is policy.StakedFigure
    whole = tuple(plain.move(m) or 0.0 for m in decision.moves)
    assert whole != tuple(split.move(m) or 0.0 for m in decision.moves)
    sized = policy.with_bid(staked, decision, rule)
    assert sized.basis is not None and sized.basis.bid == rule
    assert sized.basis.season == whole
    assert sized.basis.season == policy.with_bid(built, decision, rule).basis.season
    assert replace(sized, basis=decision.basis) == decision


# --------------------------------------------------------------------------- a season
@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("tier", policy.GUARDED_TIERS)
def test_a_season_with_a_block_the_guard_off_and_a_stake_plays_clean(tier, h2h):
    """The two PRs in one run, under the public leagues' rules (FAAB, continuous waivers): a
    pair whose arms both name a block with every key, A with the guard off and B with a stake
    of 1, at a season weight. The audit is clean. Each arm's row holds the bid policy's three
    counts and ends with the guard's and the stake's, in the payload's order, and the block is
    in force in each arm's season (its bids part from the same arm's that names no block)."""
    setup = public(h2h)
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *PATH)
    knobs = {"season_weight": A_WEIGHT}
    rivals = {"kind": "market", "rate": RIVALS.rate}

    def arm_of(name, **more):
        made = spec(name, tier, knobs={"plan_floor_cats": 0.1, **knobs}, **more)
        return rn.arm_of({**made, "opponents": rivals})

    a, b = arm_of("A", bid=EVERY_KEY, guard="off"), arm_of("B", bid=EVERY_KEY, stake=1)
    days: dict[int, list[rn.DayRecord]] = {0: [], 1: []}
    got = rn.paired(setup, w, a, b, 1, on_day=lambda r: days[r.variant].append(r))
    assert got["breaches"] == []
    for side in "ab":
        row = got["counts"][side]
        assert tuple(row) == ct.metrics_in([row])
        assert tuple(row)[-len(SEASON_KEYS) :] == SEASON_KEYS
        assert set(ct.PACING) <= set(row) and row["claims_placed"] >= 1
    assert got["counts"]["b"]["sets_past_guard"] == 0.0
    assert 0 < got["counts"]["b"]["stake_mean"] <= 1
    assert not set(SEASON_KEYS) & set(got["counts"]["rivals"])
    # The block is in force beside each field: the same arm with no block bids other dollars.
    bare = {0: [], 1: []}
    rn.paired(
        setup,
        w,
        arm_of("A", guard="off"),
        arm_of("B", stake=1),
        1,
        on_day=lambda r: bare[r.variant].append(r),
    )
    assert in_force(days[0], bare[0]) and in_force(days[1], bare[1])
    # The command's blocks: the note names both PRs' counts, and the payload lists the blocks.
    key = {"season": 2024, "forecaster": "prior", "path": 0}  # a run's task key
    task = {"seat": 1, "unprojected": {"a": {}, "b": {}}}
    arms = {"a": a, "b": b}
    block = ss.paired_blocks([key], [{**got, **task}], arms, 1, waivers="faab")
    note = tuple(block["counts"]["note"])
    assert note[-len(SEASON_KEYS) :] == SEASON_KEYS and set(ct.PACING) <= set(note)
    assert set(ss.bid_block(arms)["bid"]) == {"a", "b"}


# --------------------------------------------------------------------------- the screen
def test_the_screen_s_rows_of_each_pr_keep_the_other_s_setting_in_both_arms():
    """Under a baseline that names a ``bid`` block, the guard off and a stake, in a FAAB league
    at a season weight: the guard's and the stake's rows keep the block in both arms, and the
    block's rows keep the guard and the stake, each pair apart in its own lever alone. The one
    declaration holds a count of each PR, and the screen's rule says them in one clause."""
    shape = policy.Shape(waivers="faab", h2h=EACH_CATEGORY)
    ctx = sc.Context("categories", "faab", 0.8, sc.NO_RATIO)
    block = {"week": 0.25, "season": 0.25, "routine": 1}
    spec_ = base({"season_weight": A_WEIGHT}, bid=block, guard="off", stake=0.25)
    levers = ["guard", "stake", *BID_NAMES]
    got = {r.key: r for r in sc.rows_of(spec_, levers, [shape], ctx)}
    played = {k: r for k, r in got.items() if r.status == sc.PLAY}
    assert {r.lever for r in played.values()} == {"stake", *BID_NAMES}
    # The baseline holds the guard off already: its row is the nudge equal to the baseline's.
    assert [r.status for r in got.values() if r.lever == "guard"] != [sc.PLAY]
    rule = bp.of(block)
    for r in played.values():
        a, b = rn.arm_of(r.a), rn.arm_of(r.b)
        assert differ(a, b) == {r.lever}, r.key
        assert rn.same_seat(a, b, [shape]) is None
        assert a.guard == b.guard == policy.OFF
        if r.lever == "stake":
            assert a.bid == b.bid == rule and (a.stake, b.stake) == (0.25, r.values["b"])
        else:
            assert a.stake == b.stake == 0.25 and a.bid != b.bid
    assert {"sets_past_guard", "value_won"} <= set(ct.APART_BY_CONSTRUCTION)
    assert "less the counts that part by construction between two arms" in sc.RULE
