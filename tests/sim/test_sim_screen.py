"""The screen's list and its rules (#172, PR H1, ``sim/screen.py``): the levers and their nudges,
which a league reads, the nudges that cannot be made, the nudge equal to the baseline, the measure
the standings count, the one-SE bar and "did nothing", the table and the spec's check. No season
is played here: the command is ``test_sim_screen_run.py``'s."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from pickandroll.sim import bid_policy as bp
from pickandroll.sim import counts as ct
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from tests.sim.sim_league import KNOBS

#: The baseline's knobs: the tests' own, the plan floors and the cap at the engine's defaults,
#: and the take-in's five at live's (PR take-in), each of whose rows nudges away from them.
BASE_KNOBS = {
    **KNOBS,
    "plan_floor_cats": 0.1,
    "plan_floor_points": 0.01,
    "daily_cap": 2,
    **{k: policy.KNOB_DEFAULTS[k] for k in policy.TAKEIN_KNOBS},
}
#: A one-win categories league with nothing named; one that counts every category, by FAAB, with
#: the two sources' stand-ins named; a points league; a points league by FAAB.
ONE = policy.Shape()
EVERY = policy.Shape(standins=True, waivers="faab", h2h=EACH_CATEGORY)
POINTS = policy.Shape(scoring="points")
#: The contexts that go with them: no scale measured; a scale of 0.8.
BARE = sc.Context()
RICH = sc.Context("categories", "faab", 0.8, sc.NO_RATIO)
POINTS_CTX = sc.Context("points", "none", 0.8, sc.NO_RATIO)
ARM_KEYS = ("tier", "executes", "with_plan", "execute_plan")
#: The bid policy's levers (PR F2), each a key of an arm's ``bid`` block by its dotted name.
BID_NAMES = (
    "bid.week",
    "bid.season",
    "bid.pace.k",
    "bid.pace.reserve",
    "bid.routine",
    "bid.rival_cap",
    "bid.shade",
)


def base(knobs: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    return {
        "name": "B",
        "tier": "surrogate",
        "knobs": {**BASE_KNOBS, **(knobs or {})},
        "opponents": {"kind": "static"},
        **more,
    }


#: A baseline that executes the queue's rule (PR E): an exact arm, the plan switches not named.
QUEUE_BASE = base(tier="exact", executes="queue")


def rows(spec, lever, shape=EVERY, ctx=RICH) -> dict[str, sc.Row]:
    return {r.key: r for r in sc.rows_of(spec, [lever], [shape], ctx)}


def to(spec, lever, shape=EVERY, ctx=RICH) -> dict[str, Any]:
    """Each row's nudge by its key: arm B's value where the pair is to play, else the status."""
    return {
        k: r.values["b"] if r.status == sc.PLAY else r.status
        for k, r in rows(spec, lever, shape, ctx).items()
    }


def differ(a: rn.Arm, b: rn.Arm) -> set[str]:
    return (
        {k for k in policy.KNOBS if policy.knob(a.knobs, k) != policy.knob(b.knobs, k)}
        | {f for f in policy.FIELDS if getattr(a.fields, f) != getattr(b.fields, f)}
        | {k for k in (*ARM_KEYS, *policy.SEASON_FIELDS) if getattr(a, k) != getattr(b, k)}
        | {n for n in BID_NAMES if sc.value_of(a, n) != sc.value_of(b, n)}
    )


# --------------------------------------------------------------------------- the list
def test_the_list_is_written_in_the_code_and_is_the_brief_s():
    assert sc.SCREEN_VERSION == 7
    assert sc.NAMES == (
        "protection_floor",
        "daily_cap",
        "plan_floor_cats",
        "plan_floor_points",
        "horizon_weight",
        "three_weight",
        "stash_threshold",
        "faab_sizing",
        "season_weight",
        "playoff_weight",
        "pool",
        "min_gain",
        "weeks_ahead",
        "surrogate_days",
        "executes",
        "execute_plan",
        "system",
        "blend",
        "guard",
        "stake",
        *BID_NAMES,
        "guard_pool",
        "later_weeks",
        "rate_shrink",
        "rate_shrink_games",
        "rate_cv",
        "miss_rate",
    )
    exact = {lever.name for lever in sc.LEVERS if lever.tier == "exact"}
    assert exact == {
        "plan_floor_cats",
        "plan_floor_points",
        "horizon_weight",
        "three_weight",
        "executes",
        "execute_plan",
        "guard_pool",
    }
    assert all(lever.tier in ("exact", "surrogate") and lever.nudge for lever in sc.LEVERS)
    # Every name is a knob, a field or a key of an arm's spec, or a key of its ``bid`` block by
    # its dotted name: nothing the arm parser refuses.
    assert set(sc.NAMES) - set(BID_NAMES) <= {*policy.KNOBS, *policy.FIELDS, *rn.SPEC_KEYS}
    assert "bid" in rn.SPEC_KEYS and all(n.startswith(sc.BID) for n in BID_NAMES)
    for name in BID_NAMES:
        key, *sub = name.removeprefix(sc.BID).split(".")
        assert key in bp.KEYS and (not sub or sub[0] in (*bp.PACE_KEYS, *bp.SHADE_KEYS)), name
    # A plan floor is on the list twice (PR E): beside the set, and under queue with rows of
    # its own; so are rate_cv (PR take-in: the spread off, both its knobs) and later_weeks (all
    # of the take-in off); every other lever once. No two rows of the list start their keys
    # alike.
    twice = [lever.name for lever in sc.LEVERS if lever.key]
    assert twice == ["plan_floor_cats", "plan_floor_points", "rate_cv", "later_weeks"]
    assert [lever.key for lever in sc.LEVERS if lever.key] == [
        "plan_floor_cats-queue",
        "plan_floor_points-queue",
        "noise",
        "all",
    ]
    stems = [lever.key or lever.name for lever in sc.LEVERS]
    assert len(stems) == len(set(stems)) == len(sc.NAMES) + 4


def test_with_plan_is_a_spec_key_and_not_a_lever_of_a_season():
    """The plan is one lever (PR E, from H1's review): from a baseline that executes its plan,
    not drawing it and not executing it are one season, so ``with_plan`` is off the list and
    asked for by name it is refused with the reason."""
    assert "with_plan" in rn.SPEC_KEYS and "with_plan" not in sc.NAMES
    assert set(sc.NOT_LEVERS) == {"with_plan"}
    with pytest.raises(KeyError, match="lever 'with_plan' is not a lever of a season: a week plan"):
        sc.rows_of(base(), ["with_plan"], [ONE], BARE)
    assert "execute_plan plays" in sc.unlisted("with_plan")
    assert sc.unlisted("pol").startswith("lever 'pol' is not in the screen's list: one of (")


def test_every_nudge_of_the_list_builds_a_valid_arm_in_a_league_that_reads_it():
    """Every pair the list gives is two arms the arm parser accepts, on the lever's tier, that
    differ in the lever alone (a move to the mix names its share too), in a league that reads the
    lever, and that ``replay`` would not refuse as one seat; and every lever of the list is such
    a pair in some league here."""
    played: set[str] = set()
    keys: set[str] = set()
    specs = (base(), base(execute_plan=True), base({"season_weight": 0.3}), QUEUE_BASE)
    for spec in specs:
        for shape, ctx in ((EVERY, RICH), (POINTS, POINTS_CTX), (ONE, BARE)):
            got = sc.rows_of(spec, sc.NAMES, [shape], ctx)
            assert len({r.key for r in got}) == len(got)
            for r in got:
                assert r.status in (sc.PLAY, sc.NOT_READ, sc.NOT_PLAYED), r
                if r.status != sc.PLAY:
                    assert r.a is None and r.b is None and r.why
                    continue
                a, b = rn.arm_of(r.a), rn.arm_of(r.b)
                assert a.tier == b.tier == r.tier
                assert sc.read_why(r.lever, a, [shape]) is None
                assert rn.same_seat(a, b, [shape]) is None
                extra = {"blend"} if r.key == "system-blend" else set()
                # The spread off and all off move more than their lever (PR take-in).
                if r.key in ("noise-off", "all-off"):
                    extra = set(sc.NOISE_OFF if r.key == "noise-off" else sc.ALL_OFF) - {r.lever}
                # A move to or from queue leaves the plan switches to the rule: the spec that
                # executes queue names neither, whatever the other arm's are.
                if r.lever == "executes" and policy.QUEUE in (a.executes, b.executes):
                    extra = set(rn.PLAN_KEYS)
                assert differ(a, b) - extra == {r.lever}, r.key
                assert r.values == {"a": sc.value_of(a, r.lever), "b": sc.value_of(b, r.lever)}
                assert b.name == f"B:{r.key}" and a.name == "B"
                played.add(r.lever)
                keys.add(r.key)
    assert played == set(sc.NAMES)
    # The queue's rows (PR E) are among the pairs: the move to queue and from it, its weight
    # both ways, and each plan floor under it.
    assert {
        "executes-queue",
        "executes-three",
        "three_weight-0",
        "three_weight-0.67",
        "plan_floor_cats-queue-down",
        "plan_floor_cats-queue-up",
        "plan_floor_points-queue-down",
        "plan_floor_points-queue-up",
    } <= keys


def test_the_rows_come_in_the_list_s_order_and_an_unknown_lever_is_a_key_error():
    got = sc.rows_of(base(), ["pool", "daily_cap", "min_gain"], [ONE], BARE)
    assert [r.key for r in got] == [
        "daily_cap-minus",
        "daily_cap-plus",
        "pool-45",
        "min_gain-double",
    ]
    with pytest.raises(KeyError, match="lever 'pol' is not in the screen's list"):
        sc.rows_of(base(), ["pol"], [ONE], BARE)
    # A baseline the arm parser refuses is refused as it refuses it.
    with pytest.raises(ValueError, match="pool 0: a whole number, 1 or more"):
        sc.rows_of(base(pool=0), ["pool"], [ONE], BARE)


# --------------------------------------------------------------------------- the nudges
def test_a_floor_steps_by_the_monday_step_s_own_grid():
    # The protection floor: a step a game, by the league's scoring; never below its minimum.
    assert to(base({"protection_floor": 0.1}), "protection_floor") == {
        "protection_floor-down": 0.05,
        "protection_floor-up": 0.15,
    }
    assert to(base({"protection_floor": 0.1}), "protection_floor", POINTS, POINTS_CTX) == {
        "protection_floor-down": sc.NOT_PLAYED,
        "protection_floor-up": 0.6,
    }
    low = rows(base(), "protection_floor")["protection_floor-down"]
    assert low.why == "protection_floor -0.05 is below its minimum 0.0"
    # A plan floor: times 1.5 and divided by it, never above four times its default.
    assert to(base(), "plan_floor_cats") == {
        "plan_floor_cats-down": 0.0667,
        "plan_floor_cats-up": 0.15,
        "plan_floor_cats-queue-down": 0.0667,
        "plan_floor_cats-queue-up": 0.15,
    }
    assert to(base({"plan_floor_cats": 0.3}), "plan_floor_cats")["plan_floor_cats-up"] == 0.4
    capped = rows(base({"plan_floor_cats": 0.4}), "plan_floor_cats")
    assert capped["plan_floor_cats-up"].why == "the floor is at its cap"
    assert capped["plan_floor_cats-down"].values == {"a": 0.4, "b": 0.2667}
    zero = rows(base({"plan_floor_cats": 0.0}), "plan_floor_cats")
    assert {r.status for r in zero.values()} == {sc.NOT_PLAYED} and len(zero) == 4
    assert all("at or below zero has no step" in r.why for r in zero.values())
    assert to(base(), "plan_floor_points", POINTS, POINTS_CTX) == {
        "plan_floor_points-down": 0.0067,
        "plan_floor_points-up": 0.015,
        "plan_floor_points-queue-down": 0.0067,
        "plan_floor_points-queue-up": 0.015,
    }


def test_a_plan_floor_is_screened_on_the_exact_tier_executing_the_plan():
    r = rows(base(), "plan_floor_cats")["plan_floor_cats-up"]
    assert r.tier == "exact" and r.both == {"tier": "exact", "execute_plan": True}
    a = rn.arm_of(r.a)
    assert (a.tier, a.with_plan, a.execute_plan) == ("exact", True, True)
    # In a FAAB run the row says what else reads the floor; without waivers it says nothing.
    assert r.note == sc.PLAN_FAAB_NOTE and "typical gain until ten moves" in r.note
    plain = policy.Shape(h2h=EACH_CATEGORY)
    assert rows(base(), "plan_floor_cats", plain, BARE)["plan_floor_cats-up"].note is None
    # A baseline that draws no plan is set to draw one.
    drawn = rows(base(with_plan=False), "plan_floor_cats")["plan_floor_cats-up"]
    assert drawn.both == {"tier": "exact", "with_plan": True, "execute_plan": True}


def test_a_plan_floor_s_row_adds_no_note_where_the_bid_gives_the_three_weeks_no_weight():
    """The note a plan floor's row adds in a FAAB run says a seat that bids also reads the floor,
    as its typical gain until ten moves. Under a baseline whose ``bid`` gives the three weeks
    no weight no seat's set reads that typical (``policy.reads``, PR F2), so the row adds
    nothing; at any weight above 0 on the three weeks it adds the note."""
    for block, note in (
        ({"week": 1}, None),
        ({"week": 0.5, "season": 0.5}, None),
        ({"week": 0.75}, sc.PLAN_FAAB_NOTE),
        ({}, sc.PLAN_FAAB_NOTE),
    ):
        r = rows(base(bid=block), "plan_floor_cats")["plan_floor_cats-up"]
        assert r.status == sc.PLAY and r.note == note, block


def test_a_plan_floor_is_screened_under_queue_in_rows_of_its_own():
    """PR E: under the queue's rule the floor is the gate a week plan clears to take the queue.
    Both arms execute ``queue`` and name neither plan switch, whatever the baseline's are."""
    for spec in (base(), base(with_plan=False, execute_plan=True), base(executes="weighted")):
        got = rows(spec, "plan_floor_cats")
        r = got["plan_floor_cats-queue-up"]
        assert r.status == sc.PLAY and r.lever == "plan_floor_cats" and r.tier == "exact"
        assert r.both == {"tier": "exact", "executes": "queue"}
        for side in (r.a, r.b):
            assert side["executes"] == "queue" and not set(rn.PLAN_KEYS) & set(side)
            assert rn.arm_of(side).executes == policy.QUEUE
        assert r.values == {"a": 0.1, "b": 0.15} and r.note == sc.PLAN_FAAB_NOTE
    # From a baseline that executes queue the rows under queue set nothing but the tier's own,
    # and the rows beside a set are not played: the baseline plays no set with a plan beside it.
    own = rows(QUEUE_BASE, "plan_floor_cats")
    assert own["plan_floor_cats-queue-down"].both == {}
    assert own["plan_floor_cats-queue-down"].status == sc.PLAY
    for key in ("plan_floor_cats-down", "plan_floor_cats-up"):
        assert (own[key].status, own[key].why) == (sc.NOT_PLAYED, sc.QUEUE_BASELINE)
    # A one-win league reads its own floor under queue too; a points league the points floor.
    one = sc.rows_of(base(), ["plan_floor_cats"], [ONE], BARE)
    assert [(r.key, r.status) for r in one] == [
        ("plan_floor_cats", sc.NOT_READ),
        ("plan_floor_cats-queue", sc.NOT_READ),
    ]
    assert {r.why for r in one} == {policy.ONE_WIN_FLOOR}
    points = rows(base(), "plan_floor_points", POINTS, POINTS_CTX)
    assert points["plan_floor_points-queue-up"].both == {"tier": "exact", "executes": "queue"}


def test_three_weight_is_nudged_under_queue_and_executes_goes_to_each_other_choice():
    got = rows(base(), "three_weight", ONE, BARE)
    assert {k: r.values for k, r in got.items()} == {
        "three_weight-0": {"a": 0.33, "b": 0.0},
        "three_weight-0.67": {"a": 0.33, "b": 0.67},
    }
    assert all(r.both == {"tier": "exact", "executes": "queue"} for r in got.values())
    assert all(r.status == sc.PLAY and r.tier == "exact" for r in got.values())
    assert all(r.both == {} for r in rows(QUEUE_BASE, "three_weight", ONE, BARE).values())
    # Not read anywhere but under queue: the lever sets it, so the row is read in every league.
    three = rn.arm_of(base(tier="exact"))
    assert sc.read_why("three_weight", three, [ONE, EVERY, POINTS]) == policy.NOT_QUEUE
    assert sc.read_why("three_weight", rn.arm_of(QUEUE_BASE), [ONE]) is None
    # executes: each other choice, in the order of policy.EXECUTES.
    assert to(base(), "executes") == {"executes-weighted": "weighted", "executes-queue": "queue"}
    assert to(base(executes="weighted"), "executes") == {
        "executes-three": "three",
        "executes-queue": "queue",
    }
    assert to(QUEUE_BASE, "executes") == {
        "executes-three": "three",
        "executes-weighted": "weighted",
    }
    # A move to queue from a baseline that names its plan switches drops them in arm B alone.
    r = rows(base(execute_plan=True), "executes")["executes-queue"]
    assert r.a["execute_plan"] is True and not set(rn.PLAN_KEYS) & set(r.b)
    assert r.both == {"tier": "exact"}


def test_a_baseline_that_executes_queue_is_moved_to_the_surrogate_without_it():
    """Most levers are played on the surrogate tier, which reads nothing an arm executes and
    which the parser refuses ``queue`` on: the baseline goes there without the key."""
    r = rows(QUEUE_BASE, "pool")["pool-45"]
    assert r.status == sc.PLAY and r.both == {"tier": "surrogate"}
    assert "executes" not in r.a and "executes" not in r.b
    assert rn.arm_of(r.a).tier == "surrogate"
    # The row's words say so, in the record and under the row in the table.
    assert r.note == sc.QUEUE_OFF_TIER.format(tier="surrogate")
    assert "both arms leave executes out" in r.note and "surrogate tier" in r.note
    assert sc.table([r.payload()])[2].strip() == f"note: {r.note}"
    assert rows(base(tier="exact"), "pool")["pool-45"].note is None
    assert rows(QUEUE_BASE, "three_weight")["three_weight-0"].note is None
    # The exact levers keep it; the plan lever is not read under it.
    assert rows(QUEUE_BASE, "horizon_weight")["horizon_weight-even"].both == {
        "executes": "weighted"
    }
    (plan,) = sc.rows_of(QUEUE_BASE, ["execute_plan"], [ONE], BARE)
    assert (plan.status, plan.key, plan.why) == (sc.NOT_READ, "execute_plan", sc.QUEUE_PLANS)
    # applied: a spec the parser takes, whatever is changed.
    assert sc.applied(base(execute_plan=True, tier="exact"), {"executes": "queue"}) == {
        **base(tier="exact"),
        "executes": "queue",
    }
    assert sc.applied(QUEUE_BASE, {"tier": "surrogate"}) == base()
    assert sc.applied(QUEUE_BASE, {"pool": 45}) == {**QUEUE_BASE, "pool": 45}


def test_the_daily_cap_moves_by_one_inside_the_knob_s_bounds():
    assert to(base(), "daily_cap") == {"daily_cap-minus": 1, "daily_cap-plus": 3}
    low = rows(base({"daily_cap": 1}), "daily_cap")
    assert low["daily_cap-minus"].status == sc.NOT_PLAYED
    assert low["daily_cap-minus"].why == "daily_cap 0 is below its minimum 1"
    assert low["daily_cap-plus"].status == sc.PLAY
    high = rows(base({"daily_cap": 3}), "daily_cap")
    assert high["daily_cap-plus"].why == "daily_cap 4 is above its maximum 3"
    assert high["daily_cap-minus"].values == {"a": 3, "b": 2}


def test_the_horizon_weight_goes_to_each_neighbour_on_the_frontier():
    mid = rows(base(), "horizon_weight")
    assert {k: r.values["b"] for k, r in mid.items()} == {
        "horizon_weight-even": "even",
        "horizon_weight-season": "season",
    }
    assert all(r.both == {"tier": "exact", "executes": "weighted"} for r in mid.values())
    # The week weight is next to even on the frontier and the knob never takes it.
    even = rows(base({"horizon_weight": "even"}), "horizon_weight")
    assert even["horizon_weight-week"].status == sc.NOT_PLAYED
    assert even["horizon_weight-week"].why == (
        "horizon_weight 'week' is not one of even, natural, season"
    )
    assert even["horizon_weight-natural"].status == sc.PLAY
    # The frontier ends at the season's weight.
    assert list(rows(base({"horizon_weight": "season"}), "horizon_weight")) == [
        "horizon_weight-natural"
    ]


def test_the_season_weight_is_nudged_by_shares_of_the_run_s_season_scale():
    assert to(base(), "season_weight") == {"season_weight-quarter": 0.2, "season_weight-half": 0.4}
    assert to(base({"season_weight": 0.1}), "season_weight") == {
        "season_weight-quarter": 0.3,
        "season_weight-half": 0.5,
    }
    # A measured figure is taken at four significant digits.
    odd = sc.Context(scale=1 / 3, no_scale=sc.NO_RATIO)
    assert to(base(), "season_weight", ONE, odd) == {
        "season_weight-quarter": 0.08333,
        "season_weight-half": 0.1667,
    }
    # Before the scale is measured the rows wait on it; with no path that has one, or a scale of
    # zero, they are not played and say why.
    for ctx, why in (
        (BARE, sc.UNMEASURED),
        (sc.Context(no_scale=sc.NO_RATIO), sc.NO_RATIO),
        (sc.Context(scale=0.0), sc.ZERO_RATIO),
    ):
        got = rows(base(), "season_weight", ONE, ctx)
        assert {r.status for r in got.values()} == {sc.NOT_PLAYED}
        assert all(r.why == why and r.scale for r in got.values())


def test_the_playoff_weight_is_played_with_a_season_weight_in_both_arms():
    r = rows(base(), "playoff_weight")["playoff_weight-1.5"]
    assert r.status == sc.PLAY and r.both == {"season_weight": 0.2}
    assert r.values == {"a": 1.0, "b": 1.5}
    assert rn.arm_of(r.a).knobs["season_weight"] == rn.arm_of(r.b).knobs["season_weight"] == 0.2
    # The baseline's own season weight stands, and no scale is waited on.
    own = rows(base({"season_weight": 0.3}), "playoff_weight", ONE, BARE)["playoff_weight-1.5"]
    assert own.status == sc.PLAY and own.both == {} and not own.scale
    # With none and no scale the row waits, and its stand-in is no setting of the record's.
    wait = rows(base(), "playoff_weight", ONE, BARE)["playoff_weight-1.5"]
    assert (wait.status, wait.why, wait.scale, wait.both) == (
        sc.NOT_PLAYED,
        sc.UNMEASURED,
        True,
        {},
    )
    # A league whose bracket is not read does not read it, whatever the scale.
    flat = policy.Shape(bracket=False)
    (unread,) = rows(base(), "playoff_weight", flat, BARE).values()
    assert unread.status == sc.NOT_READ and unread.why == "the league has no bracket read"


def test_the_stash_threshold_goes_from_none_to_no_margin_and_to_a_quarter():
    """PR G's rows: the knob has no grid, so its two nudges are named. It is read with or
    without a held slot (an active player who is out is a returning player too), on the
    surrogate tier, and a nudge that is the baseline's value is refused by name."""
    assert BASE_KNOBS["stash_threshold"] is None
    both = {"stash_threshold-0": 0.0, "stash_threshold-0.25": 0.25}
    for shape, ctx in ((EVERY, RICH), (ONE, BARE), (POINTS, POINTS_CTX)):
        assert to(base(), "stash_threshold", shape, ctx) == both
    for held in (False, True):
        assert to(base(), "stash_threshold", policy.Shape(held=held), BARE) == both
    got = rows(base(), "stash_threshold")
    assert {r.tier for r in got.values()} == {"surrogate"}
    assert got["stash_threshold-0"].values == {"a": None, "b": 0.0}
    at_zero = rows(base({"stash_threshold": 0}), "stash_threshold")
    assert at_zero["stash_threshold-0"].status == sc.REFUSED
    assert "to 0 is the baseline's value" in at_zero["stash_threshold-0"].why
    assert at_zero["stash_threshold-0.25"].status == sc.PLAY


def test_the_fields_and_the_spec_keys_take_the_list_s_values():
    assert to(base(), "faab_sizing") == {"faab_sizing-0.5": 0.5, "faab_sizing-2": 2.0}
    assert to(base(), "pool") == {"pool-45": 45}
    assert to(base(), "min_gain") == {"min_gain-double": 0.02}
    assert to(base(min_gain=0.05), "min_gain") == {"min_gain-double": 0.1}
    none = rows(base(min_gain=0), "min_gain")["min_gain-double"]
    assert (none.status, none.why) == (sc.NOT_PLAYED, "twice a min_gain of 0 is 0")
    assert to(base(), "weeks_ahead") == {"weeks_ahead-6": 6}
    assert to(base(), "surrogate_days") == {"surrogate_days-monday": [0]}
    assert rows(base(), "executes")["executes-weighted"].both == {"tier": "exact"}
    # The plan is one lever: executed or not, drawn in both arms (PR E).
    assert to(base(), "execute_plan") == {"execute_plan-flipped": True}
    assert to(base(execute_plan=True), "execute_plan") == {"execute_plan-flipped": False}
    flip = rows(base(), "execute_plan")["execute_plan-flipped"]
    assert flip.both == {"tier": "exact"} and flip.a["with_plan"] is flip.b["with_plan"] is True
    undrawn = rows(base(with_plan=False), "execute_plan")["execute_plan-flipped"]
    assert undrawn.status == sc.PLAY and undrawn.both == {"tier": "exact", "with_plan": True}


def test_the_two_sources_levers_follow_the_reads_table_on_the_surrogate():
    got = rows(base(), "system")
    assert {k: r.values["b"] for k, r in got.items()} == {
        "system-yahoo": "yahoo",
        "system-blend": "blend",
    }
    assert all(r.tier == "surrogate" and r.both == {} for r in got.values())
    # A move to the mix names its share, the engine's default.
    assert rn.arm_of(got["system-blend"].b).knobs["blend"] == 0.5
    assert rn.arm_of(got["system-yahoo"].b).knobs["blend"] is None
    assert list(rows(base({"system": "blend", "blend": 0.4}), "system")) == [
        "system-bbm",
        "system-yahoo",
    ]
    # The mix is played with the blend system in both arms.
    mix = rows(base(), "blend")
    assert {k: r.values for k, r in mix.items()} == {
        "blend-0.25": {"a": 0.5, "b": 0.25},
        "blend-0.75": {"a": 0.5, "b": 0.75},
    }
    assert all(r.both == {"system": "blend", "blend": 0.5} for r in mix.values())
    own = rows(base({"system": "blend", "blend": 0.4}), "blend")
    assert all(r.both == {} and r.values["a"] == 0.4 for r in own.values())


# --------------------------------------------------------------------------- the bid policy's levers
def test_a_bid_weight_steps_once_each_way_and_a_step_the_block_refuses_is_not_played():
    assert sc.WEIGHT_STEP == 0.25
    for key in ("week", "season"):
        lever = f"bid.{key}"
        got = rows(base(), lever)
        down, up = got[f"{lever}-down"], got[f"{lever}-up"]
        assert (down.status, down.why) == (sc.NOT_PLAYED, f"bid {key} -0.25: a number from 0 to 1")
        assert up.status == sc.PLAY and up.values == {"a": 0.0, "b": 0.25} and up.both == {}
        assert up.nudge == "one step up: 0 to 0.25"
        # Arm A is the baseline as it is written, with no block; arm B names the one key.
        assert "bid" not in up.a and up.b["bid"] == {key: 0.25}
    assert to(base(bid={"week": 0.75}), "bid.week") == {"bid.week-down": 0.5, "bid.week-up": 1.0}
    top = rows(base(bid={"week": 1}), "bid.week")["bid.week-up"]
    assert (top.status, top.why) == (sc.NOT_PLAYED, "bid week 1.25: a number from 0 to 1")
    # The two weights sum to at most 1: a step past that is the block's own refusal.
    full = rows(base(bid={"week": 0.5, "season": 0.5}), "bid.season")
    assert full["bid.season-down"].values == {"a": 0.5, "b": 0.25}
    assert (full["bid.season-up"].status, full["bid.season-up"].why) == (
        sc.NOT_PLAYED,
        "bid week 0.5 and season 0.75: their sum is at most 1 (the three weeks take the rest)",
    )
    # The baseline's other keys stand in both arms.
    kept = rows(base(bid={"week": 0.75, "routine": 1}), "bid.season")["bid.season-up"]
    assert kept.a["bid"] == {"week": 0.75, "routine": 1}
    assert kept.b["bid"] == {"week": 0.75, "routine": 1, "season": 0.25}


def test_the_pace_s_levers_are_played_on_a_pace_in_both_arms():
    assert sc.PACE_PATH == {"k": 1.0, "shape": 1.0, "reserve": 0.2} and sc.RESERVE_STEP == 0.2
    # A baseline that names no pace holds the list's path at k 0 in both arms.
    at_zero = {"k": 0.0, "shape": 1.0, "reserve": 0.2}
    got = rows(base(), "bid.pace.k")
    assert {k: r.values for k, r in got.items()} == {
        "bid.pace.k-0.5": {"a": 0.0, "b": 0.5},
        "bid.pace.k-1": {"a": 0.0, "b": 1.0},
    }
    assert all(r.status == sc.PLAY and r.both == {"bid.pace": at_zero} for r in got.values())
    assert got["bid.pace.k-1"].a["bid"] == {"pace": at_zero}
    assert got["bid.pace.k-1"].b["bid"] == {"pace": {**at_zero, "k": 1.0}}
    # At k 0 no path is read, so arm A bids as the baseline: wherever it stands, on no calendar.
    a, plain = rn.arm_of(got["bid.pace.k-1"].a), rn.arm_of(base())
    assert plain.bid is None
    for dollars in (5, 50, 100):
        seen = bp.Seen(4.0, 1.0, dollars, budget=100)
        assert bp.amount(a.bid, seen) == bp.amount(bp.DEFAULT, seen)
    # The baseline's own pace stands, its k alone moved.
    own = rows(base(bid={"pace": {"k": 0, "shape": 2, "reserve": 0.3}}), "bid.pace.k")
    assert all(r.both == {} for r in own.values())
    assert own["bid.pace.k-0.5"].b["bid"] == {"pace": {"k": 0.5, "shape": 2, "reserve": 0.3}}
    # The reserve is nudged on a pace that follows its path in both arms: the list's ...
    (r,) = rows(base(), "bid.pace.reserve").values()
    assert (r.key, r.status, r.values) == ("bid.pace.reserve-up", sc.PLAY, {"a": 0.2, "b": 0.4})
    assert r.both == {"bid.pace": dict(sc.PACE_PATH)}
    # ... the baseline's shape and reserve at the list's k where the baseline holds k 0 ...
    still = base(bid={"pace": {"k": 0, "shape": 2, "reserve": 0.3}})
    (r,) = rows(still, "bid.pace.reserve").values()
    assert r.values == {"a": 0.3, "b": 0.5}
    assert r.both == {"bid.pace": {"k": 1.0, "shape": 2.0, "reserve": 0.3}}
    # ... and the baseline's own where it follows one.
    (r,) = rows(
        base(bid={"pace": {"k": 2, "shape": 2, "reserve": 0.3}}), "bid.pace.reserve"
    ).values()
    assert r.both == {} and r.values == {"a": 0.3, "b": 0.5}
    assert rn.arm_of(r.a).bid.pace.k == rn.arm_of(r.b).bid.pace.k == 2
    # A reserve of 1 or more is the block's refusal.
    (r,) = rows(
        base(bid={"pace": {"k": 1, "shape": 2, "reserve": 0.8}}), "bid.pace.reserve"
    ).values()
    assert (r.status, r.why) == (
        sc.NOT_PLAYED,
        "bid pace reserve 1.0: a number, 0 or more and below 1",
    )


def test_the_routine_the_cap_and_the_shade_take_the_list_s_values():
    assert to(base(), "bid.routine") == {"bid.routine-flipped": 1}
    assert to(base(bid={"routine": 1}), "bid.routine") == {"bid.routine-flipped": 0}
    assert to(base(), "bid.rival_cap") == {"bid.rival_cap-on": True}
    assert sc.SHADE_ON == {"q": 0.9, "least": 10}
    assert to(base(), "bid.shade") == {"bid.shade-on": {"q": 0.9, "least": 10}}
    # A baseline that shades at another quantile is moved to the list's.
    other = rows(base(bid={"shade": {"q": 0.5, "least": 3}}), "bid.shade")["bid.shade-on"]
    assert other.status == sc.PLAY
    assert other.nudge == "to on: {q 0.5, least 3} to {q 0.9, least 10}"
    assert rows(base(), "bid.shade")["bid.shade-on"].nudge == "to on: none to {q 0.9, least 10}"
    assert rows(base(), "bid.rival_cap")["bid.rival_cap-on"].nudge == "to on: false to true"
    # On already, at the list's value: the nudge is the baseline's and is refused by name.
    cases = (
        (base(bid={"rival_cap": True}), "bid.rival_cap", "to on is the baseline's value (true)"),
        (
            base(bid={"shade": dict(sc.SHADE_ON)}),
            "bid.shade",
            "to on is the baseline's value ({q 0.9, least 10})",
        ),
        (base(bid={"pace": dict(sc.PACE_PATH)}), "bid.pace.k", "to 1 is the baseline's value (1)"),
    )
    for spec, lever, why in cases:
        refused = [r for r in rows(spec, lever).values() if r.status == sc.REFUSED]
        assert len(refused) == 1, lever
        assert refused[0].why.startswith(f"lever {lever}: ") and why in refused[0].why


def test_a_bid_lever_is_read_only_in_a_faab_run_by_the_block_s_own_reason():
    unread = (
        (ONE, "the world has no waivers and no budget"),
        (policy.Shape(waivers="priority"), "waivers by priority carry no budget and no bid"),
    )
    arm = rn.arm_of(base())
    for lever in BID_NAMES:
        for shape, why in unread:
            (r,) = sc.rows_of(base(), [lever], [shape], BARE)
            assert (r.status, r.key, r.a, r.b, r.why) == (sc.NOT_READ, lever, None, None, why)
            assert sc.read_why(lever, arm, [shape]) == policy.bid_reads(arm, shape) == why
        # Read by FAAB in either format, and where one of the run's leagues is by FAAB.
        for shapes_ in ([policy.Shape(waivers="faab")], [EVERY], [ONE, EVERY]):
            got = sc.rows_of(base(), [lever], shapes_, BARE)
            assert any(r.status == sc.PLAY for r in got), lever
            assert sc.read_why(lever, arm, shapes_) is None
    # A baseline on another tier is screened on the surrogate, as every lever of that tier.
    r = rows({**base(), "tier": "ranking"}, "bid.routine")["bid.routine-flipped"]
    assert r.status == sc.PLAY and r.both == {"tier": "surrogate"}
    # A baseline whose block the arm parser refuses is refused as it refuses it.
    with pytest.raises(ValueError, match="bid week 2: a number from 0 to 1"):
        sc.rows_of(base(bid={"week": 2}), ["bid.week"], [EVERY], RICH)


def test_a_dotted_name_writes_into_the_bid_block_and_reads_the_policy_in_force():
    plain = base()
    change = {"bid.week": 0.25, "bid.pace": dict(sc.PACE_PATH), "bid.pace.k": 0.5}
    spec = sc.applied(plain, change)
    assert spec["bid"] == {"week": 0.25, "pace": {"k": 0.5, "shape": 1.0, "reserve": 0.2}}
    assert "bid" not in plain and change["bid.pace"] == sc.PACE_PATH
    # A key written into a block the baseline names leaves the baseline's own alone.
    named = base(bid={"pace": {"k": 1, "shape": 2, "reserve": 0.3}, "routine": 1})
    moved = sc.applied(named, {"bid.pace.reserve": 0.5})
    assert moved["bid"] == {"pace": {"k": 1, "shape": 2, "reserve": 0.5}, "routine": 1}
    assert named["bid"]["pace"]["reserve"] == 0.3
    # What an arm holds under a dotted name is its policy in force: the default member's where
    # it names no block, and None for a figure of a pace it does not name.
    assert [sc.value_of(rn.arm_of(spec), n) for n in BID_NAMES] == [0.25, 0.0, 0.5, 0.2, 0, False, None]  # fmt: skip
    assert [sc.value_of(rn.arm_of(plain), n) for n in BID_NAMES] == [0.0, 0.0, None, None, 0, False, None]  # fmt: skip
    assert sc.value_of(rn.arm_of(moved), "bid.pace") == {"k": 1.0, "shape": 2.0, "reserve": 0.5}
    assert sc.shown(dict(sc.PACE_PATH)) == "{k 1, shape 1, reserve 0.2}"


# --------------------------------------------------------------------------- what a league reads
def test_a_lever_the_league_does_not_read_is_one_row_with_the_reads_table_s_reason():
    cases = (
        ("faab_sizing", ONE, "the world has no waivers and no budget: PR F"),
        ("faab_sizing", policy.Shape(waivers="priority"), "waivers by priority carry no budget"),
        ("system", ONE, policy.NO_STANDINS),
        ("blend", ONE, policy.NO_STANDINS),
        ("plan_floor_cats", ONE, policy.ONE_WIN_FLOOR),
        ("plan_floor_cats", policy.Shape(waivers="faab"), policy.ONE_WIN_FLOOR),
        ("plan_floor_points", EVERY, "a categories league"),
        ("plan_floor_cats", POINTS, "a points league"),
    )
    for lever, shape, why in cases:
        # A plan floor is on the list twice (beside the set, under queue): a row each.
        r, *under = sc.rows_of(base(), [lever], [shape], BARE)
        assert (r.status, r.key, r.a, r.b, r.note) == (sc.NOT_READ, lever, None, None, None)
        assert r.why.startswith(why), (lever, r.why)
        floor = lever.startswith("plan_floor")
        assert [(u.status, u.key, u.why) for u in under] == (
            [(sc.NOT_READ, f"{lever}-queue", r.why)] if floor else []
        )
    # An arm that draws no plan has none to execute; the lever draws it in both arms, so this
    # reason is an arm's, never a row's.
    undrawn = rn.arm_of(base(tier="exact", with_plan=False))
    assert sc.read_why("execute_plan", undrawn, [ONE]) == "the arm draws no week plan"
    # Read in one of the run's leagues is read.
    assert rows(base(), "faab_sizing", ONE, BARE).keys() == {"faab_sizing"}
    both = sc.rows_of(base(), ["faab_sizing"], [ONE, EVERY], BARE)
    assert [r.status for r in both] == [sc.PLAY, sc.PLAY]


def test_a_mirror_s_rivals_read_what_the_surrogate_reads():
    """An arm among its mirror reads the surrogate's days on any tier, as the reads table says:
    the lever's own tier is the surrogate either way, so the row is played."""
    spec = {**base(), "opponents": {"kind": "mirror"}}
    assert rows(spec, "surrogate_days")["surrogate_days-monday"].status == sc.PLAY
    assert sc.read_why("surrogate_days", rn.arm_of({**spec, "tier": "exact"}), [ONE]) is None
    static = rn.arm_of({**base(), "tier": "exact"})
    assert sc.read_why("surrogate_days", static, [ONE]) == "the exact tier decides every day"
    assert sc.read_why("executes", rn.arm_of(base()), [ONE]) == "only the exact tier reads executes"


def test_a_nudge_equal_to_the_baseline_s_value_is_refused_by_name():
    cases = (
        (base(pool=45), "pool", "its nudge to 45 is the baseline's value (45)"),
        (base(weeks_ahead=6), "weeks_ahead", "its nudge to 6 is the baseline's value (6)"),
        (base(surrogate_days=[0]), "surrogate_days", "Monday only is the baseline's value ([0])"),
        (base({"three_weight": 0.67}), "three_weight", "to 0.67 is the baseline's value (0.67)"),
        (base({"faab_sizing": 0.5}), "faab_sizing", "to 0.5 is the baseline's value (0.5)"),
        (base({"playoff_weight": 1.5}), "playoff_weight", "to 1.5 is the baseline's value (1.5)"),
        (base({"system": "blend", "blend": 0.25}), "blend", "to 0.25 is the baseline's value"),
    )
    for spec, lever, why in cases:
        refused = [r for r in rows(spec, lever).values() if r.status == sc.REFUSED]
        assert len(refused) == 1, lever
        assert refused[0].why.startswith(f"lever {lever}: ") and why in refused[0].why
        assert "--levers" in refused[0].why and refused[0].a is None
    # The lever's other nudge is a pair all the same; the command refuses the screen.
    assert rows(base({"faab_sizing": 0.5}), "faab_sizing")["faab_sizing-2"].status == sc.PLAY
    # A lever the league does not read is listed, never refused: no pair of it would be played.
    (r,) = rows(base({"faab_sizing": 0.5}), "faab_sizing", ONE, BARE).values()
    assert r.status == sc.NOT_READ


def test_a_value_is_shown_in_the_table_s_words():
    assert [sc.shown(v) for v in (None, True, False, 0.05, 2.0, 45, [0, 3], "even")] == [
        "none",
        "true",
        "false",
        "0.05",
        "2",
        "45",
        "[0, 3]",
        "even",
    ]
    r = rows(base(), "faab_sizing")["faab_sizing-2"]
    assert r.nudge == "to 2: none to 2"
    assert rows(base(), "surrogate_days")["surrogate_days-monday"].nudge == (
        "Monday only: [0, 3] to [0]"
    )


# --------------------------------------------------------------------------- a pair's result
COUNTS = {"landed": 3.0, "gone": 0.0, "adds_per_week": 0.5}


def path(a: dict | None = None, b: dict | None = None, delta: float | None = 0.0) -> dict:
    return {
        "counts": {"a": {**COUNTS, **(a or {})}, "b": {**COUNTS, **(b or {})}},
        "delta": dict.fromkeys(rn.METRICS, delta),
    }


def pair(cells: dict[tuple[str, str], dict[str, tuple[float | None, float | None]]], voided=0):
    """A pair's record as far as the screen reads it: each cell's difference by metric, as
    ``(mean, SE)``; a metric not named is zero with no spread."""
    results: dict = {}
    counts: dict = {}
    for (t, label), by_metric in cells.items():
        diff = {m: {"mean": 0.0, "se": 0.0, "n": 4} for m in rn.METRICS}
        for m, (mean, se) in by_metric.items():
            diff[m] = {"mean": mean, "se": se, "n": 4}
        results.setdefault(t, {})[label] = {"paths": 4, "difference": diff}
        counts.setdefault(t, {})[label] = {"a": {"landed": 1}, "b": {"landed": 2}, "rivals": {}}
    return {
        "results": results,
        "counts": {"by_season": counts},
        "audit": {"paths_voided": voided},
    }


def test_the_measure_is_the_one_the_league_s_standings_count():
    assert sc.measure_of("categories", ONE_WIN) == "matchup_wins"
    assert sc.measure_of("categories", EACH_CATEGORY) == "category_wins"
    # A points league's week is one result, whatever format the rules hold.
    assert sc.measure_of("points", ONE_WIN) == "matchup_wins"
    assert set(sc.MEASURE_WORDS) == {"matchup_wins", "category_wins"} <= set(rn.METRICS)


def test_a_difference_clears_one_standard_error_either_way_or_it_does_not():
    assert sc.clears(0.31, 0.3) and sc.clears(-0.31, 0.3)
    assert not sc.clears(0.3, 0.3) and not sc.clears(-0.29, 0.3) and not sc.clears(0.0, 0.0)
    # A difference that never varies clears; one path has no SE and clears nothing.
    assert sc.clears(0.5, 0.0)
    assert not sc.clears(0.5, None) and not sc.clears(None, 0.1)


@pytest.mark.parametrize(
    ("scoring", "h2h", "measure"),
    [
        ("categories", ONE_WIN, "matchup_wins"),
        ("categories", EACH_CATEGORY, "category_wins"),
        ("points", ONE_WIN, "matchup_wins"),
    ],
)
def test_a_lever_survives_on_its_league_s_measure_alone(scoring, h2h, measure):
    """In each format and in a points league: a difference that clears one SE on the measure the
    standings count survives, either way; one that clears it on another outcome only does not."""
    other = "category_wins" if measure == "matchup_wins" else "matchup_wins"
    moved = [path(b={"landed": 4.0}, delta=1.0), path()]
    assert sc.measure_of(scoring, h2h) == measure
    for mean in (0.4, -0.4):
        got = sc.result_of(pair({("2024", "prior"): {measure: (mean, 0.3)}}), moved, measure)
        assert got["survives"] and not got["did_nothing"] and got["measure"] == measure
        assert got["cells"]["2024"]["prior"]["clears"]
    elsewhere = pair({("2024", "prior"): {other: (0.9, 0.1), "made_playoffs": (0.5, 0.1)}})
    got = sc.result_of(elsewhere, moved, measure)
    assert not got["survives"] and not got["cells"]["2024"]["prior"]["clears"]
    inside = sc.result_of(pair({("2024", "prior"): {measure: (0.2, 0.3)}}), moved, measure)
    assert not inside["survives"]


def test_a_lever_did_nothing_when_both_arms_played_one_season_on_every_path():
    flat = pair({("2024", "prior"): {}})
    same = [path(), path(a={"landed": 5.0}, b={"landed": 5.0})]
    got = sc.result_of(flat, same, "matchup_wins")
    assert got["counts_equal"] and got["outcomes_equal"] and got["did_nothing"]
    assert not got["survives"]
    assert sc.result_words(got) == (
        "did nothing (both arms' counts and outcomes are equal on every path, less the counts "
        "that part by construction between two arms): matchup wins +0.000 (SE 0.000) over 4 paths"
    )
    # The same counts with an outcome that differs on a path: the lever changed which moves were
    # made, not how many. It did something, and it survives when it clears the bar.
    cleared = pair({("2024", "prior"): {"matchup_wins": (0.9, 0.1)}})
    odd = sc.result_of(cleared, [path(), path(delta=1.0)], "matchup_wins")
    assert odd["counts_equal"] and not odd["outcomes_equal"]
    assert not odd["did_nothing"] and odd["survives"]
    # One path whose counts moved is enough, whatever the outcomes.
    one = sc.result_of(cleared, [path(), path(b={"gone": 1.0})], "matchup_wins")
    assert not one["counts_equal"] and one["outcomes_equal"]
    assert not one["did_nothing"] and one["survives"]
    assert sc.result_words(one) == "matchup wins +0.900 (SE 0.100) over 4 paths; survives"
    # An outcome a path does not have (no bracket read) is no difference.
    assert sc.result_of(flat, [path(delta=None)], "matchup_wins")["did_nothing"]


#: The rule's clause for the counts "did nothing" sets aside, wherever the rule is said.
LESS = "less the counts that part by construction between two arms"
#: The count keys of the groups the counts module defines today, in the payload's order.
COUNT_KEYS = (
    *ct.METRICS,
    *ct.CLAIMS,
    *ct.BIDS,
    *ct.STASH,
    *(m for group in ct.SEASON.values() for m in group),
)


def test_did_nothing_sets_aside_the_counts_that_part_by_construction_and_no_other():
    """The one declaration (``counts.APART_BY_CONSTRUCTION``, beside the keys' definition): a
    count that parts between two arms by construction and is no difference of the season. A
    pair apart only in a declared count did nothing. A pair apart in any other count did
    something, whatever its declared counts hold. A declared count sets no outcome aside.

    The guard's count of decided sets is declared (the guard PR): the arm on the block has
    none by construction, and a set the other arm decided past the guard and never queued is
    no difference in the season."""
    flat = pair({("2024", "prior"): {}})
    cleared = pair({("2024", "prior"): {"matchup_wins": (0.9, 0.1)}})
    guard = [path(a={"sets_past_guard": 0.0}, b={"sets_past_guard": 2.0}), path()]
    assert sc.result_of(flat, guard, "matchup_wins")["did_nothing"]
    declared = ct.APART_BY_CONSTRUCTION
    # Each declared key is one the payload's order knows (``counts.metrics_in``).
    assert declared and set(declared) <= set(ct.metrics_in([dict.fromkeys(declared, 0.0)]))
    for key in declared:
        apart = {"a": {key: 0.0}, "b": {key: 3.0}}
        only = sc.result_of(flat, [path(), path(**apart)], "matchup_wins")
        assert only["counts_equal"] and only["outcomes_equal"] and only["did_nothing"]
        assert not only["survives"] and LESS in sc.result_words(only)
        # It is set aside on a path where the other counts moved alike, too.
        alike = path(a={key: 0.0, "landed": 5.0}, b={key: 3.0, "landed": 5.0})
        assert sc.result_of(flat, [alike], "matchup_wins")["did_nothing"]
        # An outcome apart is something done, with the declared count apart or not.
        odd = sc.result_of(cleared, [path(**apart, delta=1.0)], "matchup_wins")
        assert odd["counts_equal"] and not odd["outcomes_equal"]
        assert not odd["did_nothing"] and odd["survives"]
        # Another count apart beside it is something done.
        more = path(a={key: 0.0}, b={key: 3.0, "gone": 1.0})
        got = sc.result_of(cleared, [path(**apart), more], "matchup_wins")
        assert not got["counts_equal"] and not got["did_nothing"] and got["survives"]
    others = [k for k in COUNT_KEYS if k not in declared]
    assert set(ct.METRICS) <= set(others) and len(others) > len(ct.METRICS)
    for key in others:
        got = sc.result_of(flat, [path(), path(a={key: 0.0}, b={key: 1.0})], "matchup_wins")
        assert not got["counts_equal"] and not got["did_nothing"], key
        # A count one arm's row has and the other's has not is a difference as well.
        lone = {"counts": {"a": {}, "b": {key: 0.0}}, "delta": dict.fromkeys(rn.METRICS, 0.0)}
        got = sc.result_of(flat, [lone], "matchup_wins")
        assert not got["counts_equal"] and not got["did_nothing"], key


def test_the_screen_reads_the_declaration_and_names_no_count(monkeypatch):
    """``screen.result_of`` reads the tuple where the keys are defined, at the time it is
    asked: a key a later PR appends is set aside by that one line, and with nothing declared
    every count is compared, as before the declaration. Rows that hold no declared count are
    judged the same whatever the tuple holds. Both arms' counts are recorded whole either way.
    No declared key is written in ``screen.py``, and the rule's clause names none: it is part
    of the rule whatever the tuple holds."""
    flat = pair({("2024", "prior"): {}})
    source = inspect.getsource(sc)
    assert "ct.APART_BY_CONSTRUCTION" in source
    assert not [k for k in ct.APART_BY_CONSTRUCTION if k in source]
    assert LESS in " ".join(sc.RULE.split()) and LESS in " ".join((sc.__doc__ or "").split())
    key = ct.APART_BY_CONSTRUCTION[0]
    declared = [path(a={key: 0.0}, b={key: 3.0})]
    plain = {
        "same": [path(), path(a={"landed": 5.0}, b={"landed": 5.0})],
        "moved": [path(), path(b={"gone": 1.0})],
        "outcome": [path(), path(delta=1.0)],
    }

    def read(paths) -> tuple[bool, bool, bool]:
        got = sc.result_of(flat, paths, "matchup_wins")
        return got["counts_equal"], got["outcomes_equal"], got["did_nothing"]

    before = {name: read(paths) for name, paths in plain.items()}
    assert before == {
        "same": (True, True, True),
        "moved": (False, True, False),
        "outcome": (True, False, False),
    }
    assert read(declared) == (True, True, True)
    words = sc.result_words(sc.result_of(flat, declared, "matchup_wins"))
    # The record keeps both arms' counts by cell as the pair's record holds them.
    kept = sc.result_of(flat, declared, "matchup_wins")["cells"]["2024"]["prior"]["counts"]
    assert kept == {side: flat["counts"]["by_season"]["2024"]["prior"][side] for side in "ab"}
    # One line more in the tuple, and the screen sets that count aside too.
    made_up = [path(b={"a_count_a_later_pr_brings": 1.0})]
    assert read(made_up) == (False, True, False)
    with monkeypatch.context() as mp:
        mp.setattr(
            ct, "APART_BY_CONSTRUCTION", (*ct.APART_BY_CONSTRUCTION, "a_count_a_later_pr_brings")
        )
        assert read(made_up) == (True, True, True) == read(declared)
        assert {name: read(paths) for name, paths in plain.items()} == before
    # Nothing declared: every count is compared, and the rule's words are the same.
    with monkeypatch.context() as mp:
        mp.setattr(ct, "APART_BY_CONSTRUCTION", ())
        assert read(declared) == (False, True, False)
        assert {name: read(paths) for name, paths in plain.items()} == before
        same = sc.result_of(flat, plain["same"], "matchup_wins")
        assert sc.result_words(same) == words and LESS in words


def test_a_pair_apart_only_in_the_value_its_claims_were_sized_on_did_nothing():
    """``value_won`` (PR F2) is what a seat's won claims were sized on, in typicals: for the
    bid's weight on the week or on the season it restates the lever's own setting, whatever the
    arm then bids. A pair whose two arms place the same claims at the same bids, win the same
    ones and finish alike played one season, and is marked "did nothing" (found in review: the
    count alone kept the mark off). Every other count of the bids still tells two seasons apart,
    and so does the value won beside one of them."""
    flat = pair({("2024", "prior"): {}})
    bids = {"claims_won": 3.0, "dollars_spent": 7.0, "dollars_at_bracket": 40.0}
    a, b = {**bids, "value_won": 2.5}, {**bids, "value_won": 3.25}
    got = sc.result_of(flat, [path(), path(a=a, b=b)], "matchup_wins")
    assert got["counts_equal"] and got["outcomes_equal"] and got["did_nothing"]
    assert not got["survives"] and sc.result_words(got).startswith("did nothing (")
    # It is declared with the counts that part by construction (the one declaration).
    assert "value_won" in ct.APART_BY_CONSTRUCTION and "value_won" in ct.BIDS
    # The record keeps the count in both arms' rows, as every other.
    assert set(got["cells"]["2024"]["prior"]["counts"]) == {"a", "b"}
    for key, count in bids.items():
        moved = sc.result_of(flat, [path(a=a, b={**b, key: count + 1})], "matchup_wins")
        assert not moved["counts_equal"] and not moved["did_nothing"], key
    # An outcome that differs is a lever that did something, whatever the counts.
    odd = sc.result_of(flat, [path(a=a, b=b, delta=1.0)], "matchup_wins")
    assert odd["counts_equal"] and not odd["outcomes_equal"] and not odd["did_nothing"]


def test_a_result_keeps_every_outcome_and_both_arms_counts_by_cell():
    cells = {
        ("2023", "prior"): {"matchup_wins": (0.1, 0.3)},
        ("2024", "prior"): {"matchup_wins": (-0.5, 0.2), "rank": (0.4, 0.2)},
    }
    got = sc.result_of(pair(cells, voided=1), [path(b={"landed": 9.0})], "matchup_wins")
    assert got["paths"] == 1 and got["voided"] == 1
    cell = got["cells"]["2024"]["prior"]
    assert set(cell["difference"]) == set(rn.METRICS)
    assert cell["difference"]["rank"] == {"mean": 0.4, "se": 0.2, "n": 4}
    assert cell["counts"] == {"a": {"landed": 1}, "b": {"landed": 2}}
    # With more than one cell, clearing the bar in one is enough.
    assert not got["cells"]["2023"]["prior"]["clears"] and cell["clears"] and got["survives"]
    assert sc.result_words(got) == (
        "2023 prior: matchup wins +0.100 (SE 0.300) over 4 paths; 2024 prior: matchup wins "
        "-0.500 (SE 0.200) over 4 paths; survives; 1 path(s) voided"
    )


# --------------------------------------------------------------------------- the table and the spec
def test_the_table_prints_every_row_in_the_list_s_order_and_the_survivors_last():
    spec = base({"daily_cap": 1})
    listed = [r.payload() for r in sc.rows_of(spec, ["daily_cap", "pool", "system"], [ONE], BARE)]
    assert [d["status"] for d in listed] == [sc.NOT_PLAYED, sc.PLAY, sc.PLAY, sc.NOT_READ]
    cleared = pair({("2024", "prior"): {"matchup_wins": (0.9, 0.1)}})
    listed[1] |= {
        "status": sc.PLAYED,
        "result": sc.result_of(cleared, [path(b={"landed": 9.0})], "matchup_wins"),
    }
    listed[2]["status"] = sc.LEFT
    lines = sc.table(listed)
    assert lines[0].split() == ["lever", "nudge", "tier", "result"]
    assert [x.split()[0] for x in lines[1:5]] == ["daily_cap", "daily_cap", "pool", "system"]
    assert lines[1].endswith("not played: daily_cap 0 is below its minimum 1")
    assert lines[2].endswith("matchup wins +0.900 (SE 0.100) over 4 paths; survives")
    assert lines[3].endswith(sc.LEFT)
    assert lines[4].endswith(f"not read here: {policy.NO_STANDINS}")
    assert lines[5] == "survivors: daily_cap (plus 1: 1 to 2)" and len(lines) == 6
    listed[1]["result"] = {**listed[1]["result"], "survives": False}
    assert sc.table(listed)[-1] == "survivors: none"
    # What both arms were set to, and a row's note, are said under a row that is read.
    floor = [r.payload() for r in sc.rows_of(base(), ["plan_floor_cats"], [EVERY], RICH)]
    lines = sc.table(floor)
    assert lines[1].endswith("to play [both arms: execute_plan true]")
    assert lines[2].strip() == f"note: {sc.PLAN_FAAB_NOTE}"
    assert sc.table([]) == ["no lever", "survivors: none"]


def test_a_row_s_record_names_what_was_set_and_leaves_the_specs_to_the_pair_s_file():
    r = rows(base(), "horizon_weight")["horizon_weight-even"]
    assert r.payload() == {
        "lever": "horizon_weight",
        "key": "horizon_weight-even",
        "nudge": "to its neighbour even: natural to even",
        "tier": "exact",
        "both": {"tier": "exact", "executes": "weighted"},
        "values": {"a": "natural", "b": "even"},
        "status": sc.PLAY,
        "why": None,
        "note": None,
    }


def test_two_specs_differ_by_name_or_are_one():
    world = {"seasons": [2024], "paths": 48, "waivers": "none"}
    was = {"screen_version": 1, "arm": base(), "levers": ["pool"], "world": world, "fit_sha": "x"}
    assert sc.spec_differs(was, {**was, "world": dict(world)}) is None
    assert sc.spec_differs(was, {**was, "world": {**world, "paths": 24}}) == (
        "paths: started with 48, now 24"
    )
    assert sc.spec_differs(was, {**was, "arm": base(pool=40)}) == "the baseline arm's spec"
    assert sc.spec_differs(was, {**was, "levers": ["pool", "min_gain"]}) == (
        "levers: started with ['pool'], now ['pool', 'min_gain']"
    )
    assert sc.spec_differs(was, {**was, "screen_version": 2}) == (
        "screen_version: started with 1, now 2"
    )
    assert sc.spec_differs(was, {**was, "fit_sha": "y"}) == "fit_sha: started with 'x', now 'y'"
