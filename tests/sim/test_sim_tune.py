"""The tune's rules (#172, PR H2, ``sim/tune.py``): the order from a screen's record, a lever's
values and each nudge again, what a played value says over the run's cells, the step's choice, the
confirmation's finish, the verdict and its words, and the ledger's count; and the tune's folder
and the ledger's reader (``sim/readers.py``). No season is played here: the command is
``test_sim_tune_run.py``'s."""

from __future__ import annotations

from typing import Any

import pytest

from pickandroll.sim import policy
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim import tune as tn
from pickandroll.sim.engine import EACH_CATEGORY
from tests.sim.sim_league import KNOBS

BASE_KNOBS = {**KNOBS, "plan_floor_cats": 0.1, "plan_floor_points": 0.01, "daily_cap": 2}
#: A league that reads every lever: every category, by FAAB, the two sources' stand-ins named.
EVERY = policy.Shape(standins=True, waivers="faab", h2h=EACH_CATEGORY)
RICH = sc.Context("categories", "faab", 0.8, sc.NO_RATIO)
M = "matchup_wins"


def base(knobs: dict[str, Any] | None = None, **more: Any) -> dict[str, Any]:
    return {
        "name": "B",
        "tier": "surrogate",
        "knobs": {**BASE_KNOBS, **(knobs or {})},
        "opponents": {"kind": "static"},
        **more,
    }


def to(spec, lever, shape=EVERY, ctx=RICH) -> dict[str, Any]:
    """Each value's key with arm B's value where the pair is to play, else why it is not."""
    return {
        r.key: r.values["b"] if r.status == sc.PLAY else r.why
        for r in tn.values_of(lever, spec, [shape], ctx)
    }


# --------------------------------------------------------------------------- the order
def screened(lever: str, key: str, mean: float | None, se: float | None, survives=True) -> dict:
    """A screen's row: played with one cell's difference on the measure, or not played."""
    row: dict[str, Any] = {"lever": lever, "key": key, "status": sc.NOT_PLAYED}
    if mean is not None:
        row |= {
            "status": sc.PLAYED,
            "result": {
                "survives": survives,
                "cells": {"2024": {"prior": {"difference": {M: {"mean": mean, "se": se}}}}},
            },
        }
    return row


def screen_of(*rows: dict) -> dict:
    return {"name": "s", "measure": M, "rows": list(rows)}


def test_the_order_is_the_screen_s_survivors_strongest_first_by_difference_over_se():
    """A lever's place is its strongest surviving row's, either way round zero; a lever that did
    not survive is not tuned; a tie goes in the list's order; an SE of zero is the strongest."""
    screen = screen_of(
        screened("protection_floor", "protection_floor-up", 0.4, 0.2),
        screened("daily_cap", "daily_cap-minus", -0.9, 0.3),
        screened("daily_cap", "daily_cap-plus", 0.1, 0.3, survives=False),
        screened("pool", "pool-45", 0.1, 0.4, survives=False),
        screened("min_gain", "min_gain-double", 0.6, 0.3),
        screened("weeks_ahead", "weeks_ahead-6", 0.5, 0.0),
        screened("surrogate_days", "surrogate_days-monday", None, None),
    )
    order = tn.order_of(screen, None)
    assert [o["lever"] for o in order] == [
        "weeks_ahead",
        "daily_cap",
        "protection_floor",
        "min_gain",
    ]
    assert [o["from"] for o in order] == [
        "weeks_ahead-6",
        "daily_cap-minus",
        "protection_floor-up",
        "min_gain-double",
    ]
    assert order[0]["strength"] is None and "its SE is zero" in order[0]["place"]
    assert order[1]["strength"] == pytest.approx(3.0) and order[1]["place"] == tn.BY_SCREEN
    assert order[2]["strength"] == order[3]["strength"] == pytest.approx(2.0)
    assert tn.order_words(order) == (
        "weeks_ahead (weeks_ahead-6, its SE zero), daily_cap (daily_cap-minus, 3.00 SE), "
        "protection_floor (protection_floor-up, 2.00 SE), min_gain (min_gain-double, 2.00 SE)"
    )
    with pytest.raises(ValueError, match="the screen 's' has no survivor: nothing to tune"):
        tn.order_of(screen_of(screened("pool", "pool-45", 0.1, 0.4, survives=False)), None)


def test_levers_named_by_hand_take_the_screen_s_order_or_the_list_s():
    screen = screen_of(
        screened("pool", "pool-45", 0.1, 0.4, survives=False),
        screened("min_gain", "min_gain-double", 0.6, 0.3),
    )
    # With a screen: the levers it played first, strongest first, survivors or not; the others
    # after, in the list's order.
    named = tn.order_of(screen, ["weeks_ahead", "pool", "daily_cap", "min_gain", "pool"])
    assert [o["lever"] for o in named] == ["min_gain", "pool", "daily_cap", "weeks_ahead"]
    assert [o["place"] for o in named] == [tn.BY_SCREEN] * 2 + [tn.UNSCREENED] * 2
    # With none: the list's order, whatever the order named.
    by_hand = tn.order_of(None, ["weeks_ahead", "pool"])
    assert [o["lever"] for o in by_hand] == ["pool", "weeks_ahead"]
    assert all(o["place"] == tn.BY_HAND and o["strength"] is None for o in by_hand)
    assert tn.order_words(by_hand) == "pool, weeks_ahead"
    with pytest.raises(KeyError, match="lever 'pol' is not in the screen's list"):
        tn.order_of(None, ["pol"])
    with pytest.raises(ValueError, match="a tune names its levers"):
        tn.order_of(None, None)
    with pytest.raises(KeyError, match="lever 'gone' of the screen 's' is not in the code's list"):
        tn.order_of(screen_of(screened("gone", "gone-up", 0.6, 0.3)), None)


# --------------------------------------------------------------------------- a lever's values
def test_every_lever_of_the_list_has_its_nudge_and_its_nudge_again_or_none():
    """The second step of every row of the list as it is on main, derived from the row: a step
    written from the arm's own value is taken again by the lever itself; a step to a fixed
    number goes on by the same difference; a switch, a choice and a list have none; the knob's
    own bounds refuse a second step as they refuse a first. A row added to the list is added
    here, so its second step is written before any result."""
    pinned: set[str] = set()

    def at(spec: dict[str, Any], lever: str, *where: Any) -> dict[str, Any]:
        pinned.add(lever)
        return to(spec, lever, *where)

    spec = base({"protection_floor": 0.05, "season_weight": 0.1})
    assert at(spec, "protection_floor") == {
        "protection_floor-down": 0.0,
        "protection_floor-down-again": "protection_floor -0.05 is below its minimum 0.0",
        "protection_floor-up": 0.1,
        "protection_floor-up-again": 0.15,
    }
    assert at(spec, "daily_cap") == {
        "daily_cap-minus": 1,
        "daily_cap-minus-again": "daily_cap 0 is below its minimum 1",
        "daily_cap-plus": 3,
        "daily_cap-plus-again": "daily_cap 4 is above its maximum 3",
    }
    assert at(base({"daily_cap": 1}), "daily_cap") == {
        "daily_cap-minus": "daily_cap 0 is below its minimum 1",
        "daily_cap-plus": 2,
        "daily_cap-plus-again": 3,
    }
    assert at(spec, "plan_floor_cats") == {
        "plan_floor_cats-down": 0.0667,
        "plan_floor_cats-down-again": 0.0445,
        "plan_floor_cats-up": 0.15,
        "plan_floor_cats-up-again": 0.225,
    }
    assert at(spec, "season_weight") == {
        "season_weight-quarter": 0.3,
        "season_weight-quarter-again": "the same value as season_weight-half",
        "season_weight-half": 0.5,
        "season_weight-half-again": 0.9,
    }
    assert at(spec, "playoff_weight") == {
        "playoff_weight-1.5": 1.5,
        "playoff_weight-1.5-again": 2.0,
    }
    assert at(spec, "pool") == {"pool-45": 45, "pool-45-again": 60}
    assert at(spec, "min_gain") == {"min_gain-double": 0.02, "min_gain-double-again": 0.04}
    assert at(spec, "weeks_ahead") == {"weeks_ahead-6": 6, "weeks_ahead-6-again": 8}
    assert at(spec, "blend") == {
        "blend-0.25": 0.25,
        "blend-0.25-again": "blend 0.0 is below its minimum 0.25",
        "blend-0.75": 0.75,
        "blend-0.75-again": "blend 1.0 is above its maximum 0.75",
    }
    # No second step: a list, a switch, a choice.
    assert at(spec, "surrogate_days") == {"surrogate_days-monday": [0]}
    exact = base(tier="exact")
    assert at(exact, "executes") == {"executes-weighted": "weighted"}
    assert at(exact, "execute_plan") == {"execute_plan-flipped": True}
    assert at(spec, "system") == {"system-yahoo": "yahoo", "system-blend": "blend"}
    assert at(spec, "horizon_weight") == {
        "horizon_weight-even": "even",
        "horizon_weight-season": "season",
    }
    # Read only in a points league, and only where the plan is executed.
    points = policy.Shape(scoring="points"), sc.Context("points", "none", 0.8, sc.NO_RATIO)
    assert at(exact, "plan_floor_points", *points) == {
        "plan_floor_points-down": 0.0067,
        "plan_floor_points-down-again": 0.0045,
        "plan_floor_points-up": 0.015,
        "plan_floor_points-up-again": 0.0225,
    }
    assert at(base(tier="exact", execute_plan=True), "with_plan") == {"with_plan-flipped": False}
    # Every row of the list: here, or in the table's test below (the sizing's two).
    assert pinned | {"faab_sizing"} == set(sc.NAMES)


def test_a_quarter_of_the_scale_taken_again_is_the_half_whatever_the_rounding():
    """A measured figure is kept to four significant digits, so a quarter of the season scale
    taken twice and its half taken once can differ in the last digit. They are one value: over
    made-up scales the quarter again is never a second pair beside the half, and the half again,
    which is another value, always is one."""
    apart = 0
    for i in range(400):
        scale = 0.05 + 4.95 * i / 399
        ctx = sc.Context("categories", "faab", scale, sc.NO_RATIO)
        rows = {r.key: r for r in tn.values_of("season_weight", base(), [EVERY], ctx)}
        again, half = rows["season_weight-quarter-again"], rows["season_weight-half"]
        assert (again.status, again.why) == (
            sc.NOT_PLAYED,
            "the same value as season_weight-half",
        ), scale
        assert half.status == rows["season_weight-half-again"].status == sc.PLAY, scale
        quarter = rows["season_weight-quarter"].values["b"]
        apart += sc._figure(quarter + scale / 4) != half.values["b"]
    # The case is real: on some of these scales the two figures differ in the last digit.
    assert apart > 0
    # Whole numbers are never rounded, and a figure a whole step away is another value.
    assert tn._one_value(0.8264, 0.8265) and tn._one_value(45, 45)
    assert not tn._one_value(1000, 1001) and not tn._one_value(0.5, 0.25)
    assert not tn._one_value(None, 0.5) and tn._one_value([0], [0])


def test_a_step_along_the_frontier_goes_on_to_the_next_neighbour():
    """From ``even`` the nudge to ``natural`` taken again is ``season``: the one row the lever
    offers from the nudged arm and not from this one that does not go back."""
    got = to(base({"horizon_weight": "even"}), "horizon_weight")
    assert got["horizon_weight-natural"] == "natural"
    assert got["horizon_weight-natural-again"] == "season"
    assert "is not one of" in got["horizon_weight-week"]
    assert set(got) == {
        "horizon_weight-week",
        "horizon_weight-natural",
        "horizon_weight-natural-again",
    }


def test_a_step_from_none_takes_its_second_from_the_table():
    """The sizing is a multiplier and None is 1: half and double again are a quarter and four,
    written in ``tune.SECOND`` since a step from None has no size to repeat. A value the arm
    already holds is not played."""
    assert set(tn.SECOND) == {"faab_sizing-0.5", "faab_sizing-2"}
    assert to(base(), "faab_sizing") == {
        "faab_sizing-0.5": 0.5,
        "faab_sizing-0.5-again": 0.25,
        "faab_sizing-2": 2.0,
        "faab_sizing-2-again": 4.0,
    }
    assert to(base({"faab_sizing": 2.0}), "faab_sizing") == {
        "faab_sizing-0.5": 0.5,
        "faab_sizing-0.5-again": 0.25,
        "faab_sizing-2": tn.CURRENT,
    }
    assert to(base({"faab_sizing": 0.25}), "faab_sizing")["faab_sizing-0.5-again"] == tn.CURRENT


def test_a_second_step_is_a_pair_against_the_same_arm_a():
    """The nudge again is played against the arm the nudge is played against (the current arm
    on the lever's tier, set to what makes it read), names its pair by the nudge's key, and
    says both values."""
    spec = base()
    rows = {r.key: r for r in tn.values_of("playoff_weight", spec, [EVERY], RICH)}
    first, second = rows["playoff_weight-1.5"], rows["playoff_weight-1.5-again"]
    assert second.a == first.a and second.both == first.both == {"season_weight": 0.2}
    assert second.tier == first.tier == "surrogate" and second.status == sc.PLAY
    assert second.nudge == "to 1.5, again: 1 to 2"
    assert second.b == sc.applied(
        first.a, {"playoff_weight": 2.0, "name": "B:playoff_weight-1.5-again"}
    )
    assert rn.arm_of(second.b).knobs["season_weight"] == 0.2
    assert tn.change_of(second.a, second.b) == {"playoff_weight": 2.0}
    assert tn.pair_key(2, second.key) == "p2-playoff_weight-1.5-again"
    # A lever the league does not read is its one row, as in a screen.
    (row,) = tn.values_of("faab_sizing", spec, [policy.Shape()], sc.Context())
    assert row.status == sc.NOT_READ and row.key == "faab_sizing"


def test_a_nudge_that_is_the_current_value_is_not_played():
    """A screen refuses a nudge equal to its baseline's value; a tune has moved there, so the
    value is listed as the current one and its second step is tried from it."""
    got = to(base(pool=45), "pool")
    assert got == {"pool-45": tn.CURRENT}
    assert to(base(pool=60), "pool") == {"pool-45": 45, "pool-45-again": 30}


@pytest.mark.parametrize("tier", ["surrogate", "exact"])
def test_a_tune_that_took_any_nudge_of_the_list_goes_on_from_it_without_a_refusal(tier):
    """Every lever of the list as it stands, and every value a tune could take of it (a nudge or
    a nudge again): from the arm that took it the lever's values are listed again, and none is a
    refusal. A row whose nudge is a fixed target (``pool`` to 45, ``executes`` to ``weighted``,
    a share of the mix) is at its target there: a screen refuses that pair by name, and a tune
    lists it as the current value and plays the lever's other rows. A lever PR's rows are held
    to this by being in the list."""
    spec = base({"protection_floor": 0.05, "season_weight": 0.1}, tier=tier)
    taken = 0
    for name in sc.NAMES:
        for row in tn.values_of(name, spec, [EVERY], RICH):
            assert row.status in (sc.PLAY, sc.NOT_PLAYED, sc.NOT_READ), row
            if row.status != sc.PLAY:
                assert row.why and row.a is None and row.b is None, row
                continue
            change = tn.change_of(row.a, row.b)
            assert change and rn.arm_of(row.a) and rn.arm_of(row.b), row
            moved = sc.applied(spec, change)
            assert rn.arm_of(moved).tier == tier
            onward = tn.values_of(name, moved, [EVERY], RICH)
            assert onward and all(r.status != sc.REFUSED for r in onward), (row.key, onward)
            # Nothing offered from there is the value the arm now holds, and every key is one.
            assert all(tn.change_of(r.a, r.b) for r in onward if r.status == sc.PLAY)
            assert len({r.key for r in onward}) == len(onward)
            taken += 1
    assert taken >= 20


def test_a_made_up_switch_to_a_fixed_target_is_taken_once_and_then_left_out(monkeypatch):
    """A lever whose one nudge is a fixed target and no number (a made-up row: the week plan
    executed, to on): it has no second step, and from the arm that took it the row is the
    current value, not played, with no refusal of the lever or of the tune."""
    made = sc.Lever(
        "execute_plan",
        "exact",
        "to on",
        lambda arm, ctx: ({}, (sc.Step("on", "to on", {"execute_plan": True}),)),
    )
    monkeypatch.setattr(sc, "LEVERS", (made,))
    monkeypatch.setattr(sc, "NAMES", (made.name,))
    spec = base()
    (row,) = tn.values_of("execute_plan", spec, [EVERY], RICH)
    assert (row.key, row.status, row.values) == (
        "execute_plan-on",
        sc.PLAY,
        {"a": False, "b": True},
    )
    assert tn.second_of("execute_plan", spec, row, [row], [EVERY], RICH) is None
    moved = sc.applied(spec, tn.change_of(row.a, row.b))
    assert moved == {**spec, "execute_plan": True}
    (there,) = tn.values_of("execute_plan", moved, [EVERY], RICH)
    assert (there.key, there.status, there.why) == ("execute_plan-on", sc.NOT_PLAYED, tn.CURRENT)
    assert there.a is None and there.b is None
    assert [o["lever"] for o in tn.order_of(None, ["execute_plan"])] == ["execute_plan"]
    assert tn.tier_of(["execute_plan"]) == "exact"


def test_what_arm_b_holds_that_arm_a_does_not():
    a = base()
    b = sc.applied(a, {"pool": 45, "daily_cap": 3, "name": "B:x"})
    assert tn.change_of(a, b) == {"pool": 45, "daily_cap": 3}
    assert tn.change_of(a, a) == {} and sc.applied(a, tn.change_of(a, b)) == {**b, "name": "B"}


# --------------------------------------------------------------------------- a value's result
def played(
    deltas: dict[tuple[int, str], list[float]],
    marks: dict[str, Any] | None = None,
    breach: tuple[int, str, int] | None = None,
    moved: bool = True,
) -> tuple[dict, list[dict], list[dict]]:
    """A pair as ``replay`` records it, as far as a tune reads it, from each cell's paired
    differences on the measure by path: the record, every task's key and every task's result."""
    keys, results = [], []
    by_cell: dict[str, dict[str, Any]] = {}
    counts: dict[str, dict[str, Any]] = {}
    for (season, label), xs in deltas.items():
        rows = []
        for p, x in enumerate(xs):
            broke = breach == (season, label, p)
            keys.append({"season": season, "forecaster": label, "path": p})
            results.append(
                {
                    "delta": dict.fromkeys(rn.METRICS, x),
                    "counts": {"a": {"landed": 1.0}, "b": {"landed": 2.0 if moved else 1.0}},
                    "breaches": [{"rule": "planted"}] if broke else [],
                }
            )
            if not broke:
                rows.append(results[-1]["delta"])
        by_cell.setdefault(str(season), {})[label] = {
            "paths": len(rows),
            "difference": rn.aggregate(rows),
        }
        counts.setdefault(str(season), {})[label] = {"a": {}, "b": {}, "rivals": {}}
    payload = {
        "results": by_cell,
        "counts": {"by_season": counts},
        "audit": {"paths_voided": 0 if breach is None else 1},
        "verdict": {"rows": marks or {}},
    }
    return payload, keys, results


def result(deltas, **kw) -> dict:
    return tn.value_result(*played(deltas, **kw), M)


def test_a_value_s_difference_is_the_mean_over_the_cells_and_its_se_is_over_the_paths():
    """Two seasons, four paths: the mean over the cells of each cell's mean; the SE over the
    paths, a path's figure the mean over its cells (a path shares its seat and its draws across
    the cells, so the cells are not independent)."""
    got = result({(2023, "prior"): [1.0, 2.0, 1.0, 2.0], (2024, "prior"): [0.0, 1.0, 2.0, 1.0]})
    assert got["by_cell"] == {"2023 prior": 1.5, "2024 prior": 1.0}
    assert got["mean"] == pytest.approx(1.25) and got["whole_paths"] == 4
    by_path = [0.5, 1.5, 1.5, 1.5]
    assert got["se"] == pytest.approx(rn.aggregate([{M: x} for x in by_path], [M])[M]["se"])
    assert got["signs"] == tn.ABOVE and got["clears"] and "survives" not in got
    assert got["measure"] == M and not got["did_nothing"]
    assert all(c["read"] for d in got["cells"].values() for c in d.values())
    assert tn.value_words(got) == (
        "matchup wins +1.250 (SE 0.250) over 2 cells (2023 prior +1.500, 2024 prior +1.000)"
    )
    # One cell: the cell's own mean and SE.
    one = result({(2024, "prior"): [0.0, 1.0, 2.0, 1.0]})
    cell = one["cells"]["2024"]["prior"]["difference"][M]
    assert (one["mean"], one["se"]) == (cell["mean"], pytest.approx(cell["se"]))
    assert tn.value_words(one).endswith("over 1 cell")


def test_a_value_counts_only_when_every_cell_is_above_zero():
    """The sign rule: a value that helps in one made-up season and hurts in another does not
    clear, however large its mean; nor does one with a cell at zero; nor one below zero."""
    flips = result({(2023, "prior"): [3.0, 3.0, 4.0, 4.0], (2024, "prior"): [-1.0, -1.0, 0.0, 0.0]})
    assert flips["mean"] > 3 * flips["se"] > 0 and flips["signs"] == tn.FLIPS
    assert not flips["clears"] and tn.standing_of(flips) == tn.DEPENDS_SEASON
    by_forecaster = result({(2024, "prior"): [3.0, 3.0, 4.0], (2024, "espn"): [-1.0, 0.0, -1.0]})
    assert tn.standing_of(by_forecaster) == tn.DEPENDS_FORECASTER and not by_forecaster["clears"]
    # Two seasons whose forecasters disagree the same way in each: it is the forecaster's, not
    # the season's. Cells that disagree and share neither depend on both.
    up, down = [3.0, 3.0, 4.0], [-1.0, 0.0, -1.0]
    each = {(2023, "prior"): up, (2023, "espn"): down, (2024, "prior"): up, (2024, "espn"): down}
    assert tn.standing_of(result(each)) == tn.DEPENDS_FORECASTER
    across = result({(2023, "prior"): up, (2024, "espn"): down})
    assert tn.standing_of(across) == tn.DEPENDS_BOTH
    assert tn.DEPENDS == (tn.DEPENDS_SEASON, tn.DEPENDS_FORECASTER, tn.DEPENDS_BOTH)
    flat = result({(2023, "prior"): [3.0, 3.0, 4.0, 4.0], (2024, "prior"): [1.0, -1.0, 0.0, 0.0]})
    assert flat["signs"] == tn.NO_SIGN and not flat["clears"]
    assert tn.standing_of(flat) == tn.FLAT_CELL
    worse = result({(2023, "prior"): [-1.0, -2.0], (2024, "prior"): [-1.0, -1.0]})
    assert worse["signs"] == tn.BELOW and not worse["clears"] and tn.standing_of(worse) == tn.WORSE
    # Above zero in every cell and inside one SE; and with one path, no SE at all.
    inside = result(
        {(2023, "prior"): [3.0, -2.0, 0.0, 0.0], (2024, "prior"): [0.0, 0.0, 2.0, -1.0]}
    )
    assert inside["signs"] == tn.ABOVE and 0 < inside["mean"] <= inside["se"]
    assert not inside["clears"] and tn.standing_of(inside) == tn.WITHIN
    alone = result({(2024, "prior"): [1.0]})
    assert alone["se"] is None and not alone["clears"] and tn.standing_of(alone) == tn.NO_SE
    # A difference that never varies clears: its SE is zero.
    assert result({(2024, "prior"): [1.0, 1.0]})["clears"]
    idle = result({(2024, "prior"): [0.0, 0.0]}, moved=False)
    assert idle["did_nothing"] and not idle["clears"] and tn.standing_of(idle) == tn.NOTHING
    assert tn.signs_of([]) == tn.NO_SIGN and tn.signs_of([None, 1.0]) == tn.NO_SIGN


def test_an_oracle_s_cell_and_a_frozen_season_are_shown_and_not_read():
    """As the replay's own verdict: an oracle's row is a yardstick and a season that fails
    espn's freeze check is left out. Their cells stay in the record, marked, and the mean, the
    SE and the sign rule rest on the others."""
    marks = {
        "oracle:0.1": {"mark": rn.YARDSTICK, "cells": {"2024": {"mark": None}}},
        "espn": {"mark": None, "cells": {"2023": {"mark": rn.FREEZE}, "2024": {"mark": None}}},
    }
    got = result(
        {
            (2023, "espn"): [-5.0, -5.0],
            (2024, "espn"): [1.0, 2.0],
            (2024, "oracle:0.1"): [-9.0, -9.0],
        },
        marks=marks,
    )
    assert got["by_cell"] == {"2024 espn": 1.5} and got["signs"] == tn.ABOVE and got["clears"]
    assert got["cells"]["2023"]["espn"]["read"] is False
    assert got["cells"]["2024"]["oracle:0.1"]["read"] is False
    assert got["cells"]["2024"]["espn"]["read"] is True and got["whole_paths"] == 2
    none = result({(2024, "oracle:0.1"): [1.0, 1.0]}, marks=marks)
    assert none["mean"] is None and not none["clears"] and tn.standing_of(none) == tn.NO_CELL


def test_a_voided_path_is_left_out_of_the_mean_and_of_the_se():
    got = result(
        {(2023, "prior"): [1.0, 2.0, 3.0], (2024, "prior"): [1.0, 2.0, 9.0]},
        breach=(2024, "prior", 2),
    )
    assert got["voided"] == 1 and got["by_cell"] == {"2023 prior": 2.0, "2024 prior": 1.5}
    # The path that stands in one cell only is no whole path.
    assert got["whole_paths"] == 2 and got["mean"] == pytest.approx(1.75)
    assert tn.value_words(got).endswith("; 1 path(s) voided")


# --------------------------------------------------------------------------- the choice
def value(key: str, deltas, to_: Any = 1, **kw) -> dict:
    return {"key": key, "values": {"a": 0, "b": to_}, "result": result(deltas, **kw)}


def test_the_step_takes_the_best_value_that_counts_and_clears_one_se():
    cell = (2024, "prior")
    values = [
        value("pool-45", {cell: [1.0, 2.0, 1.0, 2.0]}, 45),
        value("pool-45-again", {cell: [2.0, 3.0, 2.0, 3.0]}, 60),
        value("pool-x", {cell: [3.0, -3.0, 0.0, 1.0]}),
    ]
    choice = tn.choose(values)
    assert choice["key"] == "pool-45-again" and choice["depends"] == choice["passed"] == []
    assert choice["standings"] == {
        "pool-45": tn.BEATEN,
        "pool-45-again": tn.TAKEN,
        "pool-x": tn.WITHIN,
    }
    step = {"lever": "pool", "from": 30, "values": values, "choice": choice}
    assert tn.step_words(step) == (
        "pool moves from 30 to 60 (pool-45-again): matchup wins +2.500 (SE 0.289) over 1 cell, "
        "every cell above zero and the mean above one SE, the best of the values that clear"
    )
    # A tie goes to the first in the lever's order.
    tie = tn.choose([values[0], {**values[0], "key": "pool-twin"}])
    assert tie["key"] == "pool-45"


def test_a_noisy_larger_mean_is_passed_over_for_the_surer_value_and_the_step_says_so():
    """A value is eligible when it counts and clears one SE, and the lever takes the eligible
    value with the largest mean. A value with a larger mean that does not clear does not block
    it: the surer value is taken, and the larger mean is named as passed over."""
    cell = (2024, "prior")
    values = [
        value("pool-45", {cell: [1.0, 2.0, 1.0, 2.0]}, 45),
        value("pool-45-again", {cell: [9.0, -5.0, 9.0, -5.0]}, 60),
    ]
    sure, noisy = (v["result"] for v in values)
    assert sure["clears"] and noisy["mean"] > sure["mean"] and noisy["signs"] == tn.ABOVE
    assert not noisy["clears"]
    choice = tn.choose(values)
    assert choice == {
        "key": "pool-45",
        "passed": ["pool-45-again"],
        "standings": {"pool-45": tn.TAKEN, "pool-45-again": tn.PASSED},
        "depends": [],
    }
    step = {"lever": "pool", "from": 30, "values": values, "choice": choice}
    assert tn.step_words(step) == (
        "pool moves from 30 to 45 (pool-45): matchup wins +1.500 (SE 0.289) over 1 cell, every "
        "cell above zero and the mean above one SE, the best of the values that clear; passed "
        "over, a larger mean that is not above one SE: pool-45-again (matchup wins +2.000 (SE "
        "4.041) over 1 cell)"
    )
    # With nothing eligible there is nothing to pass over: the noisy value alone is within one
    # SE, and one path has no SE at all.
    alone = tn.choose(values[1:])
    assert (alone["key"], alone["passed"], alone["standings"]) == (
        None,
        [],
        {"pool-45-again": tn.WITHIN},
    )
    assert tn.choose([value("pool-45", {cell: [1.0]}, 45)])["standings"] == {"pool-45": tn.NO_SE}
    # A smaller mean that does not clear is within one SE, not passed over.
    small = value("pool-x", {cell: [3.0, -3.0, 0.0, 1.0]})
    assert tn.choose([values[0], small])["standings"]["pool-x"] == tn.WITHIN
    # A larger mean with no SE (one path stands) is not "not above one SE": it has none. Its
    # standing says so, it is not passed over, and the step's words do not call it that.
    lone = value("pool-45-again", {cell: [9.0, 9.0]}, 60, breach=(2024, "prior", 1))
    assert lone["result"]["se"] is None and lone["result"]["mean"] > sure["mean"]
    unsure = tn.choose([values[0], lone])
    assert (unsure["key"], unsure["passed"]) == ("pool-45", [])
    assert unsure["standings"] == {"pool-45": tn.TAKEN, "pool-45-again": tn.NO_SE}
    words = tn.step_words(
        {"lever": "pool", "from": 30, "values": [values[0], lone], "choice": unsure}
    )
    assert "passed over" not in words and words.endswith("the best of the values that clear")


def test_a_lever_whose_values_do_not_count_or_clear_stays_and_says_why():
    flips = {(2023, "prior"): [3.0, 3.0, 4.0, 4.0], (2024, "prior"): [-1.0, -1.0, 0.0, 0.0]}
    values = [
        value("pool-45", flips, 45),
        value(
            "pool-45-again",
            {(2023, "prior"): [0.0, 0.0], (2024, "prior"): [0.0, 0.0]},
            60,
            moved=False,
        ),
    ]
    choice = tn.choose(values)
    assert choice["key"] is None and choice["depends"] == ["pool-45"]
    step = {"lever": "pool", "from": 30, "values": values, "choice": choice}
    assert choice["passed"] == []
    assert tn.step_words(step) == (
        "pool stays at 30: no value counts and clears one SE (pool-45: depends on the season; "
        f"pool-45-again: {tn.NOTHING})"
    )
    # A lever with no value to play stays too, each row with its reason.
    rows = [
        {"key": "faab_sizing", "status": sc.NOT_READ, "why": "no budget"},
        {"key": "pool-45", "status": sc.NOT_PLAYED, "why": tn.CURRENT},
    ]
    bare = {"lever": "pool", "from": 45, "values": rows, "choice": tn.choose([])}
    assert tn.choose([]) == {"key": None, "passed": [], "standings": {}, "depends": []}
    assert tn.step_words(bare) == (
        "pool stays at 45: no value to play (faab_sizing: not read here (no budget); pool-45: "
        "not played (the current value))"
    )


# --------------------------------------------------------------------------- the final set
def test_the_final_set_is_confirmed_on_the_cheapest_tier_that_reads_what_moved():
    assert tn.tier_of([]) == tn.tier_of(["pool", "daily_cap"]) == "surrogate"
    assert tn.tier_of(["pool", "executes"]) == "exact"
    spec = base(opponents={"kind": "market", "rate": 0.5})
    final = sc.applied(spec, {"pool": 45, "executes": "weighted"})
    a, b = tn.confirm_arms(spec, final, "exact", static=False)
    assert a == {**spec, "tier": "exact"} and tn.change_of(a, b) == {
        "pool": 45,
        "executes": "weighted",
    }
    assert b["name"] == "B:tuned" and b["opponents"] == spec["opponents"]
    sa, sb = tn.confirm_arms(spec, final, "exact", static=True)
    assert sa["opponents"] == sb["opponents"] == {"kind": "static"}
    assert tn.change_of(sa, sb) == tn.change_of(a, b)
    # A value the final arm does not read is named with the reads table's reason.
    surrogate = tn.confirm_arms(spec, final, "surrogate", static=False)[1]
    assert tn.unread_of(["pool", "executes"], b, [EVERY]) == {}
    assert tn.unread_of(["pool", "executes"], surrogate, [EVERY]) == {
        "executes": "only the exact tier reads executes"
    }


# --------------------------------------------------------------------------- the confirmation
def difference(odds=(0.0, 0.1), rank=(0.0, 0.1), wins=(0.0, 0.1)) -> dict:
    out = {m: {"mean": 0.0, "se": 0.1, "n": 4} for m in rn.METRICS}
    for m, (mean, se) in (("made_playoffs", odds), ("rank", rank), (M, wins)):
        out[m] = {"mean": mean, "se": se, "n": 4}
    return out


def test_a_cell_s_finish_is_read_on_playoff_odds_and_final_rank_each_against_its_se():
    """Above zero is better for playoff odds and below zero for the rank. The standings' measure
    decides nothing here."""
    assert tn.finish_of(difference(odds=(0.2, 0.1))) == tn.AHEAD
    assert tn.finish_of(difference(rank=(-0.5, 0.2))) == tn.AHEAD
    assert tn.finish_of(difference(odds=(-0.2, 0.1))) == tn.BEHIND
    assert tn.finish_of(difference(rank=(0.5, 0.2))) == tn.BEHIND
    assert tn.finish_of(difference(odds=(0.2, 0.1), rank=(0.5, 0.2))) == tn.MIXED
    assert tn.finish_of(difference(odds=(0.1, 0.1), rank=(-0.2, 0.2))) == tn.LEVEL
    assert tn.finish_of(difference(wins=(5.0, 0.1))) == tn.LEVEL
    assert tn.finish_of(difference(odds=(0.2, None))) == tn.UNSURE
    assert tn.finish_of(difference(odds=(0.0, 0.0), rank=(-1.0, 0.0))) == tn.AHEAD


def cells(**finishes: tuple[str, ...]) -> dict:
    """Confirmation cells by kind of rivals and forecaster, from each forecaster's finishes
    (against the run's rivals, then against static ones when given)."""
    made = {
        tn.AHEAD: difference(odds=(0.2, 0.1)),
        tn.BEHIND: difference(odds=(-0.2, 0.1)),
        tn.LEVEL: difference(),
        tn.MIXED: difference(odds=(0.2, 0.1), rank=(0.5, 0.2)),
        tn.UNSURE: difference(odds=(0.2, None)),
    }
    out: dict[str, dict] = {}
    for label, states in finishes.items():
        for kind, state in zip((tn.RUN, tn.STATIC), states, strict=False):
            out.setdefault(kind, {})[label] = {
                "difference": made[state],
                "paths": 4,
                "read": label != "oracle",
                "finish": tn.finish_of(made[state]),
            }
    return out


def test_the_verdict_rests_on_the_run_s_rivals_for_every_forecaster_the_rule_reads():
    holds = tn.verdict_of(cells(prior=(tn.AHEAD, tn.AHEAD), espn=(tn.AHEAD, tn.AHEAD)))
    assert holds["state"] == tn.HOLDS and holds["flags"] == [] and holds["why"] is None
    assert holds["words"] == tn.VERDICT_WORDS[tn.HOLDS] and holds["read"] == ["prior", "espn"]
    assert holds["rule"] == tn.VERDICT_RULE and holds["advisory"] == tn.ADVISORY
    assert holds["by_forecaster"]["prior"] == {tn.RUN: tn.AHEAD, tn.STATIC: tn.AHEAD}
    # One forecaster level: not shown. One behind: against, whatever the other shows.
    assert tn.verdict_of(cells(prior=(tn.AHEAD,), espn=(tn.LEVEL,)))["state"] == tn.NOT_SHOWN
    assert tn.verdict_of(cells(prior=(tn.MIXED,)))["state"] == tn.NOT_SHOWN
    assert tn.verdict_of(cells(prior=(tn.AHEAD,), espn=(tn.BEHIND,)))["state"] == tn.AGAINST
    # An oracle's row is shown and not read.
    yard = tn.verdict_of(cells(prior=(tn.AHEAD,), oracle=(tn.BEHIND,)))
    assert yard["state"] == tn.HOLDS and yard["read"] == ["prior"]
    assert yard["by_forecaster"]["oracle"] == {tn.RUN: tn.BEHIND}
    # No verdict, with the reason.
    for got, why in (
        (tn.verdict_of(cells(prior=(tn.AHEAD,)), voided=2), "the audit voided 2 path(s)"),
        (tn.verdict_of(cells(oracle=(tn.AHEAD,))), "no forecaster the rule may rest on"),
        (tn.verdict_of(cells(prior=(tn.UNSURE,))), "no SE in the cell(s) prior"),
    ):
        assert got["state"] is None and why in got["why"] and got["words"] == got["why"]


def test_an_edge_against_one_kind_of_rivals_only_is_flagged():
    """The static cells decide nothing; a forecaster ahead against one kind of rivals and not
    against the other is flagged, either way round."""
    got = tn.verdict_of(cells(prior=(tn.AHEAD, tn.LEVEL), espn=(tn.LEVEL, tn.AHEAD)))
    assert got["state"] == tn.NOT_SHOWN
    assert got["flags"] == [
        "prior: ahead against the run's rivals only",
        "espn: ahead against static rivals only",
    ]
    passive = tn.verdict_of(cells(prior=(tn.AHEAD, tn.BEHIND)))
    assert passive["state"] == tn.HOLDS
    assert passive["flags"] == ["prior: ahead against the run's rivals only"]
    # A run whose own rivals are static has one kind, and nothing to flag.
    assert tn.verdict_of(cells(prior=(tn.AHEAD,)))["flags"] == []


def test_a_forecaster_the_search_read_with_no_cell_on_the_season_is_no_verdict():
    """The verdict is stated for every forecaster the search read. One of them with no cell on
    the season confirmed on is no verdict, named with replay's reason, however the others
    finished; a forecaster the search never read is listed and decides nothing."""
    ahead = cells(prior=(tn.AHEAD, tn.AHEAD))
    got = tn.verdict_of(ahead, missing={"marcel": "one earlier season on file"})
    assert got["state"] is None and got["read"] == ["prior"]
    assert got["missing"] == {"marcel": "one earlier season on file"}
    assert got["why"] == got["words"]
    assert got["why"] == (
        "no verdict: the search read marcel (one earlier season on file), and the season "
        "confirmed on has no cell for it"
    )
    assert "recommended" not in got["words"]
    assert tn.verdict_of(ahead, missing={})["state"] == tn.HOLDS
    assert tn.verdict_of(ahead)["missing"] == {}
    # A voided path is said first: it is the audit's.
    assert "the audit voided" in tn.verdict_of(ahead, 1, {"marcel": "x"})["why"]
    # What a pair's record says of its cells, and what the search read.
    payload = {
        "cells": {
            "2023": {
                "prior": {"served": True, "reason": None},
                "marcel": {"served": False, "reason": "one earlier season on file"},
            }
        }
    }
    assert tn.skipped_of(payload, 2023) == {"marcel": "one earlier season on file"}
    assert tn.skipped_of(payload, 2024) == tn.skipped_of({}, 2023) == {}
    steps = [
        {"values": [{"key": "a", "status": sc.NOT_PLAYED}]},
        {"values": [{"result": {"by_cell": {"2024 prior": 1.0, "2024 marcel": 1.0}}}]},
        {"values": [{"result": {"by_cell": {"2023 prior": 1.0}}}]},
    ]
    assert tn.searched_of(steps) == ["prior", "marcel"] and tn.searched_of([]) == []
    # The printed table lists the forecaster with no cell.
    conf = {"cells": ahead, "skipped": {"marcel": "one earlier season on file"}, "verdict": got}
    lines = tn.confirmation_lines(conf, M)
    assert "  marcel: no cell on the season confirmed on (one earlier season on file)" in lines
    assert lines[-2] == f"verdict (advisory): {got['why']}"


def test_a_kind_of_rivals_that_is_one_seat_is_not_a_cell_and_the_edge_is_flagged():
    """Against static rivals the final arm can be the baseline's seat (what moved is read only
    through the run's rivals): that pair is not played, its finish says so, and a forecaster
    ahead against the run's rivals is ahead against one kind only."""
    run_only = {tn.RUN: cells(prior=(tn.AHEAD,), espn=(tn.LEVEL,))[tn.RUN]}
    got = tn.verdict_of(run_only, one_seat=[tn.STATIC])
    assert got["by_forecaster"] == {
        "prior": {tn.RUN: tn.AHEAD, tn.STATIC: tn.ONE_SEAT},
        "espn": {tn.RUN: tn.LEVEL, tn.STATIC: tn.ONE_SEAT},
    }
    assert got["flags"] == [
        (
            "prior: ahead against the run's rivals only (against static rivals the final arm is "
            "the baseline's seat)"
        )
    ]
    assert got["state"] == tn.NOT_SHOWN
    names = ["horizon_weight (not read)", "surrogate_days (not read)"]
    conf = {"cells": run_only, "one_seat": {tn.STATIC: names}, "verdict": got}
    assert (
        f"  against static rivals: not played, {tn.ONE_SEAT} (the two arms differ only in "
        "horizon_weight (not read); surrogate_days (not read))"
    ) in tn.confirmation_lines(conf, M)
    # With no such kind nothing changes: one kind played is one kind, and nothing to flag.
    assert tn.verdict_of(run_only)["flags"] == []


def test_a_confirmation_pair_is_read_by_forecaster_from_its_record():
    payload, _, _ = played({(2026, "prior"): [1.0, 1.0, 2.0], (2026, "oracle:0.1"): [0.0, 0.0]})
    payload["verdict"]["rows"] = {"oracle:0.1": {"mark": rn.YARDSTICK, "cells": {}}}
    got = tn.confirmation_of(payload, 2026)
    assert set(got) == {"prior", "oracle:0.1"} and got["prior"]["paths"] == 3
    assert got["prior"]["read"] and not got["oracle:0.1"]["read"]
    # The helper moves every outcome alike: more playoff odds and a worse (higher) final rank.
    assert got["prior"]["finish"] == tn.MIXED and got["oracle:0.1"]["finish"] == tn.LEVEL
    payload["results"]["2026"]["prior"]["difference"]["rank"]["mean"] *= -1
    assert tn.confirmation_of(payload, 2026)["prior"]["finish"] == tn.AHEAD
    assert set(got["prior"]["counts"]) == {"a", "b", "rivals"}
    assert set(got["prior"]["difference"]) == set(rn.METRICS)


def test_the_verdict_s_words_recommend_and_never_say_more():
    """Every sentence a tune can print about its verdict: "recommended" where it speaks of the
    final set, never "optimal", and a promotion only to say there is none."""
    conf = {"cells": cells(prior=(tn.AHEAD, tn.LEVEL)), "verdict": None}
    texts = [tn.SEARCH_RULE, tn.CARRY_NOTE, tn.VERDICT_RULE, tn.ADVISORY, tn.NO_CONFIRMATION]
    texts += [tn.NOTHING_TO_CONFIRM, tn.SAME_SEAT, tn.UNPLANNED, tn.ONE_SEAT]
    texts += list(tn.VERDICT_WORDS.values())
    for state in (tn.HOLDS, tn.NOT_SHOWN, tn.AGAINST):
        assert "recommended" in tn.VERDICT_WORDS[state]
    conf["verdict"] = tn.verdict_of(conf["cells"])
    lines = tn.confirmation_lines(conf, M)
    texts += lines
    assert all("optimal" not in t.lower() and "best set" not in t.lower() for t in texts)
    assert "promotes nothing" in tn.ADVISORY and "only on the user's word" in tn.ADVISORY
    assert "one withheld season is one realization" in tn.ADVISORY
    assert " ".join(lines[0].split()) == (
        "forecaster rivals playoff odds, points (SE) final rank (SE) matchup wins (SE) finish"
    )
    assert " ".join(lines[1].split()) == (
        "prior the run's rivals +20.0 (10.0) +0.000 (0.100) +0.000 (0.100) ahead"
    )
    assert "flag: prior: ahead against the run's rivals only" in lines
    assert lines[-2] == f"verdict (advisory): {tn.VERDICT_WORDS[tn.HOLDS]}"
    assert lines[-1] == tn.ADVISORY
    # A look at the confirmation season is named in the verdict's own line, by both its numbers.
    counted = tn.confirmation_lines({**conf, "look": {"look": 2, "line": 5}}, M)
    assert counted[-2] == (
        "verdict (advisory; look 2 for this league kind, line 5 of the ledger): "
        + tn.VERDICT_WORDS[tn.HOLDS]
    )
    assert counted[:-2] == lines[:-2] and "optimal" not in counted[-2]


# --------------------------------------------------------------------------- the ledger's looks
def test_a_look_is_counted_by_league_kind_and_a_tune_s_own_line_is_found_again():
    tune = {"design": "tune", "tune_started_at": "day one"}
    lines = [
        {"look": 1, "design": "paired", "name": "a-replay"},
        {"look": 2, **tune, "name": "t1", "spec_sha": "s1", "league_kind_sha": "k1"},
        {"look": 3, **tune, "name": "t2", "spec_sha": "s2", "league_kind_sha": "k2"},
    ]
    assert tn.look_of_kind([], "k1") == 1
    assert tn.look_of_kind(lines, "k1") == 2 and tn.look_of_kind(lines, "k3") == 1
    assert tn.own_look(lines, "t1", "s1", "day one") == lines[1]
    # Another spec under the same name, or the same spec under another, is another tune; and so
    # is the same tune started again in a new folder: it reads the season again.
    assert tn.own_look(lines, "t1", "s2", "day one") is None
    assert tn.own_look(lines, "t3", "s1", "day one") is None
    assert tn.own_look(lines, "t1", "s1", "day two") is None
    assert tn.own_look(lines, "a-replay", "s1", "day one") is None


# --------------------------------------------------------------------------- the folder, the ledger
def test_a_tune_s_folder_keeps_its_record_and_a_file_a_pair(tmp_path):
    assert reader.read_tune(tmp_path, "t") is None
    assert reader.read_tune_pair(tmp_path, "t", "p1-pool-45") is None
    rec = {"fit_sha": "f", "hold_out": 2025, "name": "t"}
    path = reader.write_tune(tmp_path, "t", rec)
    assert (
        path
        == tmp_path / reader.TUNES_DIR / "t" / reader.TUNE_FILE
        == tmp_path / "sim/tunes/t/tune.json"
    )
    assert reader.read_tune(tmp_path, "t") == rec
    pair = reader.write_tune_pair(tmp_path, "t", "p1-pool-45", {**rec, "name": "t-p1-pool-45"})
    assert (
        pair
        == reader.tune_pair_path(tmp_path, "t", "p1-pool-45")
        == path.parent / "p1-pool-45.json"
    )
    assert reader.read_tune_pair(tmp_path, "t", "p1-pool-45")["name"] == "t-p1-pool-45"
    # As every run's: the fit's hash and the hold-out are in what is written.
    with pytest.raises(ValueError, match="a tune's record names fit_sha"):
        reader.write_tune(tmp_path, "t", {"hold_out": 2025})
    with pytest.raises(ValueError, match="a run payload names hold_out"):
        reader.write_tune_pair(tmp_path, "t", "p1-pool-45", {"fit_sha": "f"})
    with pytest.raises(ValueError, match="a pair named 'tune' would be the tune's own record"):
        reader.tune_pair_path(tmp_path, "t", "tune")
    # A name is made safe as a run's is, and a tune's folder is not a screen's.
    assert reader.tune_dir(tmp_path, "a/b c").name == "a-b-c"
    assert reader.tune_dir(tmp_path, "t") != reader.screen_dir(tmp_path, "t")
    path.write_text("{")
    with pytest.raises(reader.SimReadError, match="is not JSON"):
        reader.read_tune(tmp_path, "t")


def test_the_ledger_is_read_line_by_line_and_a_broken_line_is_refused(tmp_path):
    assert reader.read_looks(tmp_path) == []
    reader.append_look(tmp_path, {"name": "a-replay", "design": "paired"})
    reader.append_look(tmp_path, {"name": "t", "design": "tune", "league_kind_sha": "k"})
    lines = reader.read_looks(tmp_path)
    assert lines == [
        {"look": 1, "name": "a-replay", "design": "paired"},
        {"look": 2, "name": "t", "design": "tune", "league_kind_sha": "k"},
    ]
    assert tn.look_of_kind(lines, "k") == 2
    path = tmp_path / reader.LEDGER
    path.write_text(path.read_text() + "\n[1]\n")
    with pytest.raises(reader.SimReadError, match="line 4, is not a record"):
        reader.read_looks(tmp_path)
    path.write_text("not json\n")
    with pytest.raises(reader.SimReadError, match="line 1, is not JSON"):
        reader.read_looks(tmp_path)
