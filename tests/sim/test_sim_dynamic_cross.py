"""SEASON SIM (#172, PR dynamic knobs): an arm that names no override plays main's season, and
an override on each axis crossed with the league's rules.

The equality: each league of ``takein_matrix`` (a one-win league, a held slot with two players
out on day one, points, waivers by priority, by FAAB and continuous, every category counted,
same-day adds) on the exact tier, the surrogate, the queue's rule and an arm that executes its
plan on plan floors of -1, all with mirror rivals, and a ``yahoo`` and a ``blend`` split seat,
each with the take-in's five at live's defaults, must give the digests main gave before dynamic
knobs (main ``26e67fd``, taken with the same code on that tree): outcome for outcome. Two
made-up traces with no override are byte for byte main's (no trace version step).

The crossing: an arm with two overrides on one axis, ``phase`` or ``standing``, plays every
league on the exact tier with mirror rivals, and the arm that executes its plan on floors of -1
too; each season plays to its end with no breach, each axis moves some season, and a split seat
plays each axis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim import trace as tr
from tests.sim import takein_matrix as tm
from tests.sim.sim_league import arm, make_setup, replay_of

#: The take-in's five at live's defaults.
ON = {k: policy.KNOB_DEFAULTS[k] for k in policy.TAKEIN_KNOBS}
#: Each season's digest on main ``26e67fd``, before dynamic knobs, with :data:`ON`, by league
#: and arm (``takein_matrix``) and by split seat; and two made-up traces' payloads, hashed.
MAIN = {
    "plain/exact": "c865d892bfc662fb",
    "plain/surrogate": "8366f4d63249306b",
    "plain/queue": "c865d892bfc662fb",
    "plain/plan": "c865d892bfc662fb",
    "held/exact": "59899efd1bc414d6",
    "held/surrogate": "c12b7650d4cb9fa1",
    "held/queue": "59899efd1bc414d6",
    "held/plan": "59899efd1bc414d6",
    "points/exact": "099836662c971374",
    "points/surrogate": "611013662c746cde",
    "points/queue": "099836662c971374",
    "points/plan": "099836662c971374",
    "priority/exact": "fdd970e9e1eeee2e",
    "priority/surrogate": "8366f4d63249306b",
    "priority/queue": "fdd970e9e1eeee2e",
    "priority/plan": "fdd970e9e1eeee2e",
    "faab/exact": "fdd970e9e1eeee2e",
    "faab/surrogate": "8366f4d63249306b",
    "faab/queue": "fdd970e9e1eeee2e",
    "faab/plan": "fdd970e9e1eeee2e",
    "continuous/exact": "2d13cdbb6c16dbe6",
    "continuous/surrogate": "f42135c51e308366",
    "continuous/queue": "2d13cdbb6c16dbe6",
    "continuous/plan": "2d13cdbb6c16dbe6",
    "each/exact": "4a427f8112bd6224",
    "each/surrogate": "45ec3658236aad00",
    "each/queue": "4a427f8112bd6224",
    "each/plan": "4a427f8112bd6224",
    "same_day/exact": "4f502bc8d895bf1b",
    "same_day/surrogate": "18cd53293a0a8b42",
    "same_day/queue": "771628bf86d3639d",
    "same_day/plan": "4f502bc8d895bf1b",
    "split_yahoo": "4c4b318de43180e1",
    "split_blend": "e8aeeac1feebb0ac",
    "trace/surrogate/market": "71dc4786f64b0800",
    "trace/exact/mirror": "be8177b37391ba97",
}
#: Two overrides on each axis: a knob of the queue's size and one of the week's odds. The base
#: daily cap is the tests' 1, and the take-in's rates are live's.
AXIS = {
    policy.PHASE: {"daily_cap@phase.middle": 2, "rate_shrink@phase.run_in": 0.0},
    policy.STANDING: {"daily_cap@standing.line": 2, "rate_cv@standing.behind": 0.0},
}


def on(a: rn.Arm, **over: Any) -> rn.Arm:
    """``a`` with the take-in's five at live's defaults and ``over``, checked."""
    return replace(a, knobs=policy.check_arm_knobs({**a.knobs, **ON, **over}))


def split_season(name: str, over: dict[str, Any]) -> tuple[str, rn.VariantResult]:
    """A split seat's season (``takein_matrix.split_season``) with :data:`ON` and ``over``."""
    from pickandroll.sim import cli as ss
    from tests.sim.test_no_peek import recorded
    from tests.sim.test_sim_split import SOURCES, second_of, world_of

    system, blend = tm.SPLITS[name]
    setup, lines = recorded()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    second = second_of(first)
    a = arm("Y", "exact", "mirror")
    a = on(replace(a, knobs={**a.knobs, "system": system, "blend": blend}), **over)
    arms_ = ss.believing({"Y": a}, SOURCES)
    w = world_of(setup, lines, first, second, arms_)
    variant = {**rn.opponents_of(setup, arms_["Y"], tm.ME), tm.ME: arms_["Y"].seat()}
    got: list[rn.DayRecord] = []
    (res,) = rn.simulate(setup, w, [variant], on_day=got.append)
    return tm.digest(got), res


def trace_sha(tier: str, rivals: str) -> str:
    """A made-up trace's payload hashed: two arms with :data:`ON` that differ in name alone."""
    setup = make_setup(weeks=4)
    a = on(arm("A", tier, rivals))
    b = on(arm("B", tier, rivals, daily_cap=1))
    rec = tr.Recorder({"a": setup, "b": setup}, 1, {"a": a, "b": b})
    rn.paired(setup, replay_of(setup, 5, 0), a, b, 1, on_day=rec.on_day, on_end=rec.on_end)
    text = json.dumps(rec.payload(), sort_keys=False, allow_nan=False)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- none named
@pytest.mark.parametrize("league", list(tm.LEAGUES))
def test_an_arm_that_names_no_override_plays_main_s_season_in_each_league(league):
    got = {f"{league}/{name}": tm.season(league, on(a)) for name, a in tm.arms().items()}
    assert got == {k: v for k, v in MAIN.items() if k.startswith(f"{league}/")}


@pytest.mark.parametrize("name", list(tm.SPLITS))
def test_a_split_seat_that_names_no_override_plays_main_s_season(name):
    assert split_season(name, {})[0] == MAIN[name]


@pytest.mark.parametrize(("tier", "rivals"), [("surrogate", "market"), ("exact", "mirror")])
def test_a_trace_with_no_override_is_main_s_byte_for_byte(tier, rivals):
    assert trace_sha(tier, rivals) == MAIN[f"trace/{tier}/{rivals}"]


# --------------------------------------------------------------------------- each axis crossed
@pytest.fixture(scope="module")
def crossed() -> dict[tuple[str, str], bool]:
    """Whether an override on each axis moved each league's season on the exact tier with
    mirror rivals (its digest against main's with none), each played to its end, no breach."""
    out = {}
    a = tm.arms()["exact"]
    for axis, over in AXIS.items():
        for league in tm.LEAGUES:
            got, res = tm.played(league, on(a, **over))
            assert res.result is not None and res.breaches == (), (axis, league, res.breaches)
            out[(axis, league)] = got != MAIN[f"{league}/exact"]
    return out


def test_each_axis_moves_some_league_s_season(crossed):
    for axis in AXIS:
        assert any(crossed[(axis, league)] for league in tm.LEAGUES), axis


@pytest.mark.parametrize("axis", list(AXIS))
@pytest.mark.parametrize("league", list(tm.LEAGUES))
def test_an_arm_that_executes_its_plan_on_floors_of_minus_one_plays_each_axis(league, axis):
    a = tm.arms()["plan"]
    _, res = tm.played(league, on(a, **AXIS[axis]))
    assert a.execute_plan and policy.knob(a.knobs, "plan_floor_cats") == -1.0
    assert res.result is not None and res.breaches == ()


@pytest.mark.parametrize("axis", list(AXIS))
@pytest.mark.parametrize("name", list(tm.SPLITS))
def test_a_split_seat_plays_each_axis(name, axis):
    _, res = split_season(name, AXIS[axis])
    assert res.result is not None and res.breaches == ()
