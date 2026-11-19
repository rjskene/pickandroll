"""The screen's list and its rules (#172, PR H1, ``sim/screen.py``): the levers and their nudges,
which a league reads, the nudges that cannot be made, the nudge equal to the baseline, the measure
the standings count, the one-SE bar and "did nothing", the table and the spec's check. No season
is played here: the command is ``test_sim_screen_run.py``'s."""

from __future__ import annotations

from typing import Any

import pytest

from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from tests.sim.sim_league import KNOBS

#: The baseline's knobs: the tests' own, the plan floors and the cap at the engine's defaults.
BASE_KNOBS = {**KNOBS, "plan_floor_cats": 0.1, "plan_floor_points": 0.01, "daily_cap": 2}
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


def base(knobs: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    return {
        "name": "B",
        "tier": "surrogate",
        "knobs": {**BASE_KNOBS, **(knobs or {})},
        "opponents": {"kind": "static"},
        **more,
    }


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
        {k for k in policy.KNOBS if a.knobs[k] != b.knobs[k]}
        | {f for f in policy.FIELDS if getattr(a.fields, f) != getattr(b.fields, f)}
        | {k for k in ARM_KEYS if getattr(a, k) != getattr(b, k)}
    )


# --------------------------------------------------------------------------- the list
def test_the_list_is_written_in_the_code_and_is_the_brief_s():
    assert sc.SCREEN_VERSION == 1
    assert sc.NAMES == (
        "protection_floor",
        "daily_cap",
        "plan_floor_cats",
        "plan_floor_points",
        "horizon_weight",
        "faab_sizing",
        "season_weight",
        "playoff_weight",
        "pool",
        "min_gain",
        "weeks_ahead",
        "surrogate_days",
        "executes",
        "with_plan",
        "execute_plan",
        "system",
        "blend",
    )
    exact = {lever.name for lever in sc.LEVERS if lever.tier == "exact"}
    assert exact == {
        "plan_floor_cats",
        "plan_floor_points",
        "horizon_weight",
        "executes",
        "with_plan",
        "execute_plan",
    }
    assert all(lever.tier in ("exact", "surrogate") and lever.nudge for lever in sc.LEVERS)
    # Every name is a knob, a field or a key of an arm's spec: nothing the arm parser refuses.
    assert set(sc.NAMES) <= {*policy.KNOBS, *policy.FIELDS, *rn.SPEC_KEYS}


def test_every_nudge_of_the_list_builds_a_valid_arm_in_a_league_that_reads_it():
    """Every pair the list gives is two arms the arm parser accepts, on the lever's tier, that
    differ in the lever alone (a move to the mix names its share too), in a league that reads the
    lever, and that ``replay`` would not refuse as one seat; and every lever of the list is such
    a pair in some league here."""
    played: set[str] = set()
    for spec in (base(), base(execute_plan=True), base({"season_weight": 0.3})):
        for shape, ctx in ((EVERY, RICH), (POINTS, POINTS_CTX), (ONE, BARE)):
            for r in sc.rows_of(spec, sc.NAMES, [shape], ctx):
                assert r.status in (sc.PLAY, sc.NOT_READ, sc.NOT_PLAYED), r
                if r.status != sc.PLAY:
                    assert r.a is None and r.b is None and r.why
                    continue
                a, b = rn.arm_of(r.a), rn.arm_of(r.b)
                assert a.tier == b.tier == r.tier
                assert sc.read_why(r.lever, a, [shape]) is None
                assert rn.same_seat(a, b, [shape]) is None
                extra = {"blend"} if r.key == "system-blend" else set()
                assert differ(a, b) - extra == {r.lever}, r.key
                assert r.values == {"a": sc.value_of(a, r.lever), "b": sc.value_of(b, r.lever)}
                assert b.name == f"B:{r.key}" and a.name == "B"
                played.add(r.lever)
    assert played == set(sc.NAMES)


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
    }
    assert to(base({"plan_floor_cats": 0.3}), "plan_floor_cats")["plan_floor_cats-up"] == 0.4
    capped = rows(base({"plan_floor_cats": 0.4}), "plan_floor_cats")
    assert capped["plan_floor_cats-up"].why == "the floor is at its cap"
    assert capped["plan_floor_cats-down"].values == {"a": 0.4, "b": 0.2667}
    zero = rows(base({"plan_floor_cats": 0.0}), "plan_floor_cats")
    assert {r.status for r in zero.values()} == {sc.NOT_PLAYED}
    assert all("at or below zero has no step" in r.why for r in zero.values())
    assert to(base(), "plan_floor_points", POINTS, POINTS_CTX) == {
        "plan_floor_points-down": 0.0067,
        "plan_floor_points-up": 0.015,
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


def test_the_fields_and_the_spec_keys_take_the_list_s_values():
    assert to(base(), "faab_sizing") == {"faab_sizing-0.5": 0.5, "faab_sizing-2": 2.0}
    assert to(base(), "pool") == {"pool-45": 45}
    assert to(base(), "min_gain") == {"min_gain-double": 0.02}
    assert to(base(min_gain=0.05), "min_gain") == {"min_gain-double": 0.1}
    none = rows(base(min_gain=0), "min_gain")["min_gain-double"]
    assert (none.status, none.why) == (sc.NOT_PLAYED, "twice a min_gain of 0 is 0")
    assert to(base(), "weeks_ahead") == {"weeks_ahead-6": 6}
    assert to(base(), "surrogate_days") == {"surrogate_days-monday": [0]}
    assert to(base(), "executes") == {"executes-weighted": "weighted"}
    assert rows(base(), "executes")["executes-weighted"].both == {"tier": "exact"}
    assert to(base(), "execute_plan") == {"execute_plan-flipped": True}
    assert to(base(execute_plan=True), "with_plan") == {"with_plan-flipped": False}
    assert to(base(with_plan=False, execute_plan=True), "with_plan") == {"with_plan-flipped": True}


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
        ("with_plan", ONE, "the plan is drawn and not executed"),
    )
    for lever, shape, why in cases:
        (r,) = sc.rows_of(base(), [lever], [shape], BARE)
        assert (r.status, r.key, r.a, r.b, r.note) == (sc.NOT_READ, lever, None, None, None)
        assert r.why.startswith(why), (lever, r.why)
    # A baseline that draws no plan has none to execute.
    (r,) = sc.rows_of(base(with_plan=False), ["execute_plan"], [ONE], BARE)
    assert (r.status, r.why) == (sc.NOT_READ, "the arm draws no week plan")
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
        (base(executes="weighted"), "executes", "to weighted is the baseline's value (weighted)"),
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
        "did nothing (both arms' counts and outcomes are equal on every path): matchup wins "
        "+0.000 (SE 0.000) over 4 paths"
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
