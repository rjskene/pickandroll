"""SEASON SIM (#172, PR dynamic knobs): a knob's value by the seat's situation.

An arm may name overrides in its knobs, ``knob@axis.situation``: the knob's value where the
seat's situation on that axis is the one named, its base elsewhere. The axes and their cut
points (``phase``: the thirds of the regular weeks and the bracket; ``standing``: the lead over
the cut line in swings), the names and their refusals, the knobs in force, the reads table's
rows, the decision key, a mirror rival's own situation and the seasons the overrides act in are
pinned here, on the made-up league. The no-override seasons against main's and the crossing
with every league rule are ``test_sim_dynamic_cross``'s."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from pickandroll.sim import counts as ct
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim import trace as tr
from pickandroll.sim import tune as tn
from pickandroll.sim.lab import trace_view
from pickandroll.sim.state import initial
from tests.sim import takein_matrix as tm
from tests.sim.sim_league import KNOBS, arm, make_setup, replay_of

#: The take-in's five at live's defaults (the arms of the seasons below, as live plays).
ON = {k: policy.KNOB_DEFAULTS[k] for k in policy.TAKEIN_KNOBS}


def checked(a: rn.Arm, **over: Any) -> rn.Arm:
    """``a`` with ``over`` in its knobs, checked as an arm's knobs are (``run.arm_of``)."""
    return replace(a, knobs=policy.check_arm_knobs({**a.knobs, **over}))


def ov(**over: Any) -> dict[str, Any]:
    """Overrides by name: ``knob__axis__where`` for ``knob@axis.where``."""
    out = {}
    for k, v in over.items():
        base, axis, where = k.split("__")
        out[policy.override_name(base, axis, where)] = v
    return out


# --------------------------------------------------------------------------- the axes
@pytest.mark.parametrize(
    ("weeks", "bracket", "phases"),
    [
        # R = 5, T = 2: two opening weeks, one between, two in the run-in.
        (6, 1, ["opening", "opening", "middle", "run_in", "run_in", "bracket"]),
        # R = 4, T = 1.
        (5, 1, ["opening", "middle", "middle", "run_in", "bracket"]),
        # R = 3, T = 1: one week each.
        (5, 2, ["opening", "middle", "run_in", "bracket", "bracket"]),
        # R = 19, T = 6, a long season's: six, seven, six and three.
        (22, 3, ["opening"] * 6 + ["middle"] * 7 + ["run_in"] * 6 + ["bracket"] * 3),
    ],
)
def test_phase_cuts_the_regular_weeks_in_thirds_and_names_the_bracket(weeks, bracket, phases):
    setup = make_setup(weeks=weeks, playoff_weeks=bracket)
    got = [policy.phase_of(setup.spec, w.number) for w in setup.calendar.weeks]
    assert got == phases
    assert policy.phase_of(None, 1) is None and policy.phase_of(setup.spec, None) is None
    assert policy.phase_of(setup.spec, weeks + 1) is None


def ranked_totals(setup, weeks: list[int]) -> dict[int, dict[int, dict[str, float]]]:
    """Each week's totals with team 1 best in every category, team 2 next and so on: team 1
    beats everyone, team 2 every team but 1, and the last team no one."""
    out = {}
    n = len(setup.teams)
    for w in weeks:
        out[w] = {}
        for t in setup.teams:
            v = float(n + 1 - t)
            row = dict.fromkeys(("pts", "reb", "ast", "stl", "blk", "threes"), v)
            row |= {"tov": float(t), "fgm": v, "fga": 10.0, "ftm": v, "fta": 10.0}
            out[w][t] = row
    return out


def test_standing_reads_the_finished_weeks_against_the_swing_left():
    """Four teams, two in the field, four regular weeks. Before any week is finished every team
    is on the line. After one week the winners lead the line by one week, which over the swing
    of the two weeks after the next (the root of five) is under one: still the line. After three
    the two above the line lead it by a week or two and the last week has the swing of one: safe,
    and the two below behind. The running week is never read."""
    setup = make_setup(teams=4, weeks=5)
    spec = setup.spec
    assert spec.regular_weeks == (1, 2, 3, 4) and spec.playoff_teams == 2
    assert {policy.standing_of(spec, {}, t, 1) for t in setup.teams} == {policy.LINE}
    one = ranked_totals(setup, [1])
    assert {policy.standing_of(spec, one, t, 2) for t in setup.teams} == {policy.LINE}
    three = ranked_totals(setup, [1, 2, 3])
    got = {t: policy.standing_of(spec, three, t, 4) for t in setup.teams}
    assert got == {1: "safe", 2: "safe", 3: "behind", 4: "behind"}
    # The running week's totals are not read: week 4's own, whatever they say, change nothing.
    four = ranked_totals(setup, [1, 2, 3, 4])
    four[4] = {t: four[4][5 - t] for t in setup.teams}
    assert {t: policy.standing_of(spec, four, t, 4) for t in setup.teams} == got
    # No standing in a bracket week, with no spec, or in a league whose field is every team.
    assert policy.standing_of(spec, three, 1, 5) is None
    assert policy.standing_of(None, three, 1, 4) is None
    everyone = replace(spec, playoff_teams=4, byes=0)
    assert policy.standing_of(everyone, three, 1, 4) is None
    assert not policy.shape_of(replace(setup, spec=everyone)).line
    assert policy.shape_of(setup).line
    # A league whose bracket is not read keeps the shape it had: its bracket says it all.
    unread = replace(setup, spec=None, bracket_unread="not read")
    assert policy.shape_of(unread) == policy.Shape(bracket=False)


def test_the_situation_reads_the_runner_s_standing_else_the_state_s_finished_weeks():
    setup = make_setup(teams=4, weeks=5)
    state = replace(initial(setup), totals=ranked_totals(setup, [1, 2, 3]))
    assert policy.situation_of(setup, state, 1, 4) == policy.Situation("run_in", "safe")
    held = replace(state, standing={1: "behind"})
    assert policy.situation_of(setup, held, 1, 4) == policy.Situation("run_in", "behind")
    assert policy.situation_of(setup, state, 1, 5) == policy.Situation("bracket", None)
    unread = replace(setup, spec=None, bracket_unread="not read")
    assert policy.situation_of(unread, state, 1, 4) == policy.NOWHERE


# --------------------------------------------------------------------------- names and refusals
def test_an_arm_s_overrides_are_checked_and_kept_after_its_knobs_in_order():
    knobs = {**KNOBS, **ov(rate_cv__standing__behind=0.2, daily_cap__phase__run_in=3)}
    got = policy.check_arm_knobs(knobs)
    assert list(got)[: len(policy.KNOBS)] == list(policy.KNOBS)
    assert list(got)[len(policy.KNOBS) :] == ["daily_cap@phase.run_in", "rate_cv@standing.behind"]
    a = rn.arm_of({"name": "A", "tier": "exact", "knobs": knobs})
    assert a.knobs == got
    # None named: the knobs as before, the very dict check_knobs gives.
    assert policy.check_arm_knobs(KNOBS) == policy.check_knobs(KNOBS)
    assert not policy.overrides_of(policy.check_arm_knobs(KNOBS))


@pytest.mark.parametrize(
    ("over", "says"),
    [
        ({"system@phase.opening": "yahoo"}, "system is fixed at setup"),
        ({"blend@standing.behind": 0.5}, "blend is fixed at setup"),
        ({"pool@phase.opening": 40}, "'pool' is not a knob"),
        ({"daily_cap@budget.low": 3}, "axis 'budget' is not one of phase, standing"),
        ({"daily_cap@phase.late": 3}, "'late' is not a situation of phase"),
        (
            {"playoff_weight@phase.bracket": 2.0},
            "season_weight x playoff_weight, one product: name season_weight@phase.bracket",
        ),
        (
            ov(daily_cap__phase__opening=2, daily_cap__standing__behind=3),
            "knob 'daily_cap' is overridden on two axes (phase, standing): one axis a knob",
        ),
        (
            ov(
                daily_cap__standing__safe=2,
                daily_cap__standing__line=3,
                daily_cap__standing__behind=3,
            ),
            "knob 'daily_cap' is overridden in every situation of standing",
        ),
        ({"daily_cap@phase.opening": 1}, "1 is the base value of daily_cap, so it says nothing"),
        ({"daily_cap@phase.opening": 4}, "override 'daily_cap@phase.opening' refused"),
        ({"rate_cv@standing.behind": 1.5}, "override 'rate_cv@standing.behind' refused"),
        (
            ov(
                daily_cap__phase__opening=2,
                rate_cv__phase__opening=0.1,
                miss_rate__phase__opening=0.1,
                season_weight__phase__opening=0.5,
            ),
            "4 overrides named: an arm names at most 3 (policy.MAX_OVERRIDES",
        ),
    ],
)
def test_an_override_is_refused_by_name(over, says):
    with pytest.raises(ValueError) as e:
        policy.check_arm_knobs({**KNOBS, **over})
    assert says in str(e.value)
    with pytest.raises(ValueError):
        rn.arm_of({"name": "A", "tier": "exact", "knobs": {**KNOBS, **over}})


def test_the_out_of_bounds_value_says_the_knob_s_own_reason():
    with pytest.raises(ValueError) as e:
        policy.check_arm_knobs({**KNOBS, "daily_cap@phase.opening": 4})
    assert policy.knob_refused("daily_cap", 4) in str(e.value)


def test_a_season_weight_on_standing_beside_a_stake_is_refused_and_on_phase_is_not():
    """The stake scales the season term by the standing: an override of ``season_weight`` on
    ``standing`` beside it would say it twice. On ``phase`` it is allowed, and a stake beside a
    ``season_weight`` above 0 only in an override has a term to scale."""
    spec = {"name": "A", "tier": "exact", "stake": 0.5}
    with pytest.raises(ValueError) as e:
        rn.arm_of(
            {
                **spec,
                "knobs": {**KNOBS, "season_weight": 0.5, **ov(season_weight__standing__behind=1.0)},
            }
        )
    assert "the stake already scales the season term by the standing" in str(e.value)
    a = rn.arm_of({**spec, "knobs": {**KNOBS, **ov(season_weight__phase__run_in=0.5)}})
    assert a.stake == 0.5 and policy.anywhere(a.knobs, "season_weight")
    with pytest.raises(ValueError, match="with season_weight 0"):
        rn.arm_of({**spec, "knobs": KNOBS})
    # With no stake the standing override is the arm's own choice.
    rn.arm_of(
        {
            "name": "A",
            "tier": "exact",
            "knobs": {**KNOBS, **ov(season_weight__standing__behind=1.0)},
        }
    )


def test_the_knobs_check_problem_of_reads_refuses_an_override_s_name():
    """Live has no reader for an override: the engine's knobs are the base seventeen, and the
    check every problem's knobs pass (``policy.check_knobs``) refuses an override's name, so a
    caller that forgets to resolve fails by name."""
    with pytest.raises(ValueError, match="daily_cap@phase.opening"):
        policy.check_knobs({**KNOBS, "daily_cap@phase.opening": 2})
    assert not any(policy.is_override(k) for k in policy.KNOBS)


# --------------------------------------------------------------------------- in force
def test_the_knobs_in_force_take_each_override_in_its_situation_alone():
    knobs = policy.check_arm_knobs(
        {**KNOBS, **ov(daily_cap__phase__run_in=3, rate_cv__standing__behind=0.2)}
    )
    here = policy.in_force(knobs, policy.Situation("run_in", "behind"))
    assert (here["daily_cap"], here["rate_cv"]) == (3, 0.2)
    assert not any(policy.is_override(k) for k in here)
    there = policy.in_force(knobs, policy.Situation("middle", "line"))
    assert (there["daily_cap"], there["rate_cv"]) == (1, 0.0)
    assert policy.in_force(knobs, policy.NOWHERE) == policy.base_of(knobs)
    assert policy.forced(knobs, policy.Situation("run_in", "line")) == ("daily_cap@phase.run_in",)
    # None named: the knobs themselves, read as before.
    assert policy.in_force(KNOBS, policy.Situation("run_in", "behind")) is KNOBS
    setup = make_setup()
    assert policy.knobs_on(KNOBS, setup, initial(setup), 1, 1) is KNOBS


def test_a_mirror_rival_decides_in_its_own_situation_never_the_seat_s():
    setup = make_setup(teams=4, weeks=5)
    a = checked(arm("A", "surrogate", "mirror"), **ov(daily_cap__standing__behind=3))
    state = replace(initial(setup), standing={1: "safe", 2: "behind"})
    rivals = rn.opponents_of(setup, a, 1)
    assert isinstance(rivals[2], op.Mirror) and "daily_cap@standing.behind" in rivals[2].knobs
    assert op.in_force(rivals[2].knobs, setup, state, 2)["daily_cap"] == 3
    assert op.in_force(a.seat().knobs, setup, state, 1)["daily_cap"] == 1
    # The executor's cap reads the same knobs in force.
    assert (
        rn._cap(rivals[2], setup, state, 2, 1) == 3 and rn._cap(a.seat(), setup, state, 1, 1) == 1
    )


def test_a_stash_override_stays_the_seat_s_own():
    knobs = policy.check_arm_knobs(
        {**KNOBS, **ov(stash_threshold__phase__run_in=0.5, daily_cap__phase__run_in=2)}
    )
    rival = policy.rival_knobs(knobs)
    assert rival["stash_threshold"] is None and "stash_threshold@phase.run_in" not in rival
    assert rival["daily_cap@phase.run_in"] == 2
    assert rn.stash_named([rn.Arm("A", "exact", knobs, {"kind": "mirror"})])
    # The base keeps its place: a rival's repr is its decisions' key.
    assert list(rival)[: len(policy.KNOBS)] == list(policy.KNOBS)


def test_the_decision_key_holds_the_overrides_in_force_only_for_an_arm_that_names_one():
    setup = make_setup(teams=4, weeks=5)
    state = replace(initial(setup), standing={1: "behind"})
    plain = arm("A", "surrogate", "static").seat()
    key = rn.decision_key(setup, state, 1, plain, 2)
    assert len(key) == 5
    named = checked(arm("A", "surrogate", "static"), **ov(daily_cap__standing__behind=3)).seat()
    got = rn.decision_key(setup, state, 1, named, 2)
    assert len(got) == 6 and got[-1] == ("daily_cap@standing.behind",)
    assert rn.decision_key(setup, replace(state, standing={1: "line"}), 1, named, 2)[-1] == ()


# --------------------------------------------------------------------------- the reads table
def test_the_reads_table_has_a_row_for_each_override_and_says_why_one_is_not_read():
    base = {**KNOBS, "season_weight": 0.5}
    over = ov(
        daily_cap__standing__behind=3,
        three_weight__phase__bracket=0.5,
        rate_cv__phase__opening=0.2,
    )
    exact = rn.Arm(
        "A",
        "exact",
        policy.check_arm_knobs({**base, **over}),
        {"kind": "market"},
        executes=policy.QUEUE,
    )
    one = policy.Shape()
    table = policy.reads(exact, one)
    assert list(table)[: len(policy.KNOBS)] == list(policy.KNOBS)
    assert table["daily_cap@standing.behind"] == policy.READ
    assert table["rate_cv@phase.opening"] == policy.READ
    assert table["three_weight@phase.bracket"] == policy.BRACKET_THREE
    assert (
        policy.reads(exact, policy.Shape(line=False))["daily_cap@standing.behind"] == policy.NO_LINE
    )
    unread = policy.reads(exact, policy.Shape(bracket=False))
    assert unread["daily_cap@standing.behind"] == policy.NO_LINE
    assert unread["rate_cv@phase.opening"] == policy.NO_PHASE
    # On a tier that does not read the knob, the knob's own reason.
    ranking = replace(exact, tier="ranking", executes=policy.QUEUE_SET)
    table = policy.reads(ranking, one)
    assert table["daily_cap@standing.behind"] == table["daily_cap"] != policy.READ
    assert table["three_weight@phase.bracket"] == table["three_weight"]
    # An arm that names none: the knobs' rows alone, as before.
    assert list(policy.reads(arm("B"), one)) == list(policy.KNOBS)


def test_a_knob_above_0_only_in_an_override_opens_what_it_opens():
    a = rn.Arm(
        "A",
        "exact",
        policy.check_arm_knobs(
            {**KNOBS, **ov(rate_shrink__phase__run_in=0.5, season_weight__phase__run_in=0.5)}
        ),
        {"kind": "market"},
    )
    table = policy.reads(a, policy.Shape())
    assert table["rate_shrink_games"] == policy.READ and table["playoff_weight"] == policy.READ
    plain = policy.reads(arm("B"), policy.Shape())
    assert plain["rate_shrink_games"] != policy.READ and plain["playoff_weight"] != policy.READ


def test_two_arms_that_differ_in_an_override_nobody_reads_are_one_seat_by_name():
    a = rn.Arm("A", "ranking", policy.check_arm_knobs(KNOBS), {"kind": "static"})
    b = replace(
        a, name="B", knobs=policy.check_arm_knobs({**KNOBS, **ov(three_weight__phase__opening=0.5)})
    )
    same = rn.same_seat(a, b, [policy.Shape()])
    assert same is not None and len(same) == 1
    assert same[0].startswith("three_weight@phase.opening (" + policy.ONLY_QUEUE)
    c = replace(b, tier="exact", executes=policy.QUEUE)
    assert (
        rn.same_seat(replace(a, tier="exact", executes=policy.QUEUE), c, [policy.Shape()]) is None
    )


def test_an_override_in_a_league_whose_bracket_is_not_read_is_refused_before_any_day():
    a = checked(arm("A", "surrogate", "static"), **ov(daily_cap__phase__middle=2))
    shapes = [policy.Shape(), policy.Shape(bracket=False)]
    assert "the league's bracket is not read" in rn.override_refused(a, shapes)
    assert rn.override_refused(a, shapes[:1]) is None
    assert rn.override_refused(arm("B"), shapes) is None
    setup = make_setup(weeks=4, bracket=False)
    w = replay_of(setup, 2, 0)
    with pytest.raises(ValueError, match="names override daily_cap@phase.middle"):
        rn.simulate(setup, w, [{**rn.opponents_of(setup, a, 1), 1: a.seat()}])


# --------------------------------------------------------------------------- seasons
def season_records(setup, a: rn.Arm, seed: int = 2) -> tuple[list[rn.DayRecord], rn.VariantResult]:
    w = replay_of(setup, seed, 0)
    got: list[rn.DayRecord] = []
    (res,) = rn.simulate(
        setup, w, [{**rn.opponents_of(setup, a, 1), 1: a.seat()}], on_day=got.append
    )
    return got, res


def first_day_of(setup, phase: str):
    return min(
        d
        for w in setup.calendar.weeks
        for d in w.days()
        if policy.phase_of(setup.spec, w.number) == phase
    )


def test_an_override_acts_in_its_situation_alone():
    """Every day before the run-in is the season with no override, record for record, and a
    day of the run-in parts them: the override is read in its situation and nowhere else. A
    mirror rival names it too, and reads it in its own run-in."""
    setup = make_setup(weeks=5)
    base = replace(arm("A", "exact", "mirror"), knobs={**KNOBS, **ON})
    named = checked(base, **ov(daily_cap__phase__run_in=3, rate_shrink__phase__run_in=0.0))
    plain, rp = season_records(setup, base)
    over, ro = season_records(setup, named)
    assert rp.breaches == () and ro.breaches == () and ro.result is not None
    start = first_day_of(setup, "run_in")
    before = [r for r in plain if r.day < start]
    assert before and tm.digest(before) == tm.digest([r for r in over if r.day < start])
    assert tm.digest(plain) != tm.digest(over)


def test_an_override_of_the_blend_moves_that_morning_s_blend_and_lineup():
    """``rate_shrink`` 0 at its base and live's in the middle weeks: the seat's blend is None in
    the opening and live's in the middle (``run.blend_of``), and the first day that parts the
    season from the one with no blend is a middle day, its lineup among what parts them. The
    blend over the whole season parts the opening already. Seven players a team, so a lineup
    has a bench to choose from; mirror rivals, which blend too."""
    setup = make_setup(weeks=5, spots=7)
    base = replace(arm("A", "exact", "mirror"), knobs={**KNOBS, **ON, "rate_shrink": 0.0})
    named = checked(base, **{"rate_shrink@phase.middle": ON["rate_shrink"]})
    state = initial(setup)
    assert rn.blend_of(named.seat(), setup, state, 1, 1) is None
    assert rn.blend_of(named.seat(), setup, state, 1, 2) == policy.blend_of(
        {**named.knobs, "rate_shrink": ON["rate_shrink"]}
    )
    assert rn.blend_of(base.seat(), setup, state, 1, 2) is None
    plain, _ = season_records(setup, base)
    over, _ = season_records(setup, named)
    middle = first_day_of(setup, "middle")
    by = {r.day: r for r in plain}
    parted = [r.day for r in over if nopeek.digest(r) != nopeek.digest(by[r.day])]
    assert parted and min(parted) >= middle
    lineup = [r.day for r in over if r.starters.get(1) != by[r.day].starters.get(1)]
    assert lineup and setup.week_of(min(lineup)).number in (2, 3)
    whole, _ = season_records(
        setup, replace(base, knobs={**base.knobs, "rate_shrink": ON["rate_shrink"]})
    )
    assert min(r.day for r in whole if nopeek.digest(r) != nopeek.digest(by[r.day])) < middle


def test_a_run_that_names_an_override_counts_every_arm_s_days_in_each_situation():
    setup = make_setup(weeks=5)
    a = replace(arm("A", "surrogate", "static"), knobs={**KNOBS, **ON})
    b = checked(replace(a, name="B"), **ov(daily_cap__standing__behind=3))
    got = rn.paired(setup, replay_of(setup, 3, 0), a, b, 1)
    days = {
        p: sum(
            1
            for w in setup.calendar.weeks
            for _ in w.days()
            if policy.phase_of(setup.spec, w.number) == p
        )
        for p in policy.SITUATIONS[policy.PHASE]
    }
    regular = sum(n for p, n in days.items() if p != policy.BRACKET)
    for side in ("a", "b"):
        row = got["counts"][side]
        assert {f"days_{p}": row[f"days_{p}"] for p in days} == {
            f"days_{p}": float(n) for p, n in days.items()
        }
        assert sum(row[f"days_{s}"] for s in policy.SITUATIONS[policy.STANDING]) == regular
        assert row["days_line"] >= 7  # every team is on the line until a week is finished
    assert not any(k in got["counts"]["rivals"] for k in ct.SITUATIONS)
    assert not any(
        k in rn.paired(setup, replay_of(setup, 3, 0), a, a, 1)["counts"]["a"] for k in ct.SITUATIONS
    )
    assert rn.counted_of([a, b]) == (ct.SITUATIONS_COUNTED,) and rn.counted_of([a]) == ()


# --------------------------------------------------------------------------- the trace
def test_a_trace_names_each_overridden_knob_s_value_in_force_and_the_day_s_situation():
    setup = make_setup(weeks=5)
    a = replace(arm("A", "surrogate", "market"), knobs={**KNOBS, **ON})
    b = checked(replace(a, name="B"), **ov(daily_cap__phase__middle=3))
    rec = tr.Recorder({"a": setup, "b": setup}, 1, {"a": a, "b": b})
    rn.paired(setup, replay_of(setup, 5, 0), a, b, 1, on_day=rec.on_day, on_end=rec.on_end)
    payload = rec.payload()
    json.dumps(payload, allow_nan=False)
    for x in payload["arms"]["a"]["days"]:
        assert "situation" not in x and "daily_cap" not in x["knobs"]
    seen = set()
    for x in payload["arms"]["b"]["days"]:
        phase = policy.phase_of(setup.spec, x["week"])
        assert x["situation"]["phase"] == phase
        cap = 3 if phase == "middle" else 1
        assert x["knobs"]["daily_cap"] == x["knobs"]["adds_today_cap"] == cap
        seen.add(cap)
    assert seen == {1, 3}
    # The lab charts the knob that moves, and the pair's panel names the override.
    charts, _, _ = trace_view.knob_charts(
        payload["arms"]["a"]["days"], payload["arms"]["b"]["days"]
    )
    assert any("daily_cap" in json.dumps(c) for c in charts)
    specs = {"a": {"knobs": dict(a.knobs)}, "b": {"knobs": dict(b.knobs)}}
    panel = trace_view.pair_of({"pair": {"specs": specs}})
    assert "daily_cap@phase.middle" in json.dumps(panel)


# --------------------------------------------------------------------------- split levers
def screen_base(**over: Any) -> dict[str, Any]:
    knobs = {**KNOBS, "plan_floor_cats": 0.1, "plan_floor_points": 0.01, "daily_cap": 2, **ON}
    return {
        "name": "B",
        "tier": "surrogate",
        "knobs": {**knobs, **over},
        "opponents": {"kind": "static"},
    }


def split_rows(spec, name, shape=None):
    return {r.key: r for r in sc.rows_of(spec, [name], [shape or policy.Shape()], sc.Context())}


#: The first set (README, "The first set"; the lead's decision of 2026-11-24): standing names
#: ``safe`` and ``line`` alone.
FIRST_SET = (
    "season_weight@phase",
    "daily_cap@phase",
    "daily_cap@standing.safe",
    "daily_cap@standing.line",
    "stash_threshold@phase",
)


def test_the_first_set_is_28_rows_with_no_behind_row():
    rows = sc.rows_of(screen_base(), list(FIRST_SET), [policy.Shape()], sc.Context())
    by = {}
    for r in rows:
        by.setdefault(r.lever, []).append(r)
    assert len(rows) == 28 and {k: len(v) for k, v in by.items()} == {
        "daily_cap@phase": 8,
        "daily_cap@standing": 4,
        "stash_threshold@phase": 8,
        "season_weight@phase": 8,
    }
    assert not any(".behind" in r.key for r in rows)
    # Every row but the season weight's is to play; those wait on the season scale.
    assert {r.status for r in by["season_weight@phase"]} == {sc.NOT_PLAYED}
    assert all(r.status == sc.PLAY for k, v in by.items() if k != "season_weight@phase" for r in v)
    assert {r.values["b"] for r in by["stash_threshold@phase"]} == {0.0, 0.25}


def test_a_split_lever_is_each_nudge_in_each_situation_alone():
    got = split_rows(screen_base(), "daily_cap@standing")
    keys = [
        f"daily_cap@standing.{w}-{t}" for w in ("safe", "line", "behind") for t in ("minus", "plus")
    ]
    assert list(got) == keys
    for key, row in got.items():
        where = key.split(".")[1].split("-")[0]
        over = f"daily_cap@standing.{where}"
        assert row.status == sc.PLAY and row.override == over and row.lever == "daily_cap@standing"
        b = rn.arm_of(row.b)
        assert policy.overrides_of(b.knobs) == {over: row.values["b"]} and row.values["a"] == 2
        assert rn.arm_of(row.a).knobs == rn.arm_of(screen_base()).knobs
        payload = row.payload()
        assert payload["override"] == over and "in the " + where + ":" in row.nudge
    # One situation by name.
    one = split_rows(screen_base(), "daily_cap@standing.behind")
    assert list(one) == ["daily_cap@standing.behind-minus", "daily_cap@standing.behind-plus"]
    # The list's rows carry no override, and a screen that names none plays the list as before.
    assert all(
        r.override is None
        for r in sc.rows_of(screen_base(), ["daily_cap"], [policy.Shape()], sc.Context())
    )
    assert (
        "override"
        not in sc.rows_of(screen_base(), ["daily_cap"], [policy.Shape()], sc.Context())[0].payload()
    )


def test_a_split_row_that_an_override_s_refusal_meets_is_listed_not_played():
    # A holds a cap of 3 when behind: from there the nudge up is out of bounds, and the nudge
    # down is the base.
    spec = screen_base(**{"daily_cap@standing.behind": 3})
    got = split_rows(spec, "daily_cap@standing.behind")
    down, up = got["daily_cap@standing.behind-minus"], got["daily_cap@standing.behind-plus"]
    assert down.status == up.status == sc.NOT_PLAYED
    assert down.why.startswith("refused: ") and "is the base value of daily_cap" in down.why
    assert up.why.startswith("refused: ") and policy.knob_refused("daily_cap", 4) in up.why
    assert down.values == {"a": 3, "b": 2} and up.values == {"a": 3, "b": 4}
    # The bracket's playoff weight is the season weight's to say.
    weighted = split_rows(screen_base(season_weight=0.5), "playoff_weight@phase")
    bracket = [r for k, r in weighted.items() if ".bracket-" in k]
    assert bracket and all(r.status == sc.NOT_PLAYED and "refused: " in r.why for r in bracket)
    assert any(r.status == sc.PLAY for k, r in weighted.items() if ".bracket-" not in k)
    # A league with no cut line reads no standing: the rows say so, and are not played.
    unread = split_rows(screen_base(), "daily_cap@standing", policy.Shape(line=False))
    assert {r.status for r in unread.values()} == {sc.NOT_READ}
    assert {r.why for r in unread.values()} == {policy.NO_LINE}


def test_the_split_levers_are_the_list_s_single_knob_levers_on_each_axis():
    assert len(sc.SPLIT_NAMES) == len(set(sc.SPLIT_NAMES))
    for name in sc.SPLIT_NAMES:
        knob, axis = name.split("@")
        assert knob in policy.OVERRIDABLE and axis in policy.AXES
    assert "system@phase" not in sc.SPLIT_NAMES and "blend@standing" not in sc.SPLIT_NAMES
    assert {"daily_cap@phase", "rate_cv@standing", "season_weight@phase"} <= set(sc.SPLIT_NAMES)
    assert sc.split_of("daily_cap@phase") == ("daily_cap", "phase", None)
    assert sc.split_of("daily_cap@phase.run_in") == ("daily_cap", "phase", "run_in")
    assert sc.split_of("daily_cap@phase.late") is None and sc.split_of("daily_cap") is None
    assert sc.known("daily_cap@standing") and not sc.known("system@phase")
    with pytest.raises(KeyError, match="is no split lever"):
        sc.rows_of(screen_base(), ["system@phase"], [policy.Shape()], sc.Context())


# --------------------------------------------------------------------------- the tune's stage
def test_the_second_stage_s_order_is_fixed_before_any_pair():
    names = ["rate_cv@standing.behind", "daily_cap@phase.run_in", "daily_cap@phase.opening"]
    got = tn.split_order_of(None, names)
    assert [o["lever"] for o in got] == [
        "daily_cap@phase.opening",
        "daily_cap@phase.run_in",
        "rate_cv@standing.behind",
    ]
    assert tn.split_order_of(None, None) == [] and tn.split_order_of(None, []) == []
    with pytest.raises(KeyError, match="names no situation"):
        tn.split_order_of(None, ["daily_cap@phase"])
    with pytest.raises(KeyError, match="is no split lever"):
        tn.split_order_of(None, ["system@phase.opening"])
    assert tn.pair_key(1, "x", tn.DYNAMIC_STAGE) == "d1-x" and tn.pair_key(1, "x") == "p1-x"


def test_the_second_stage_reads_a_screen_s_surviving_split_rows_and_the_first_stage_not():
    """A screen's split rows are the second stage's, its list's rows the first's."""
    rows = [
        {"lever": "pool", "key": "pool-45", "status": sc.PLAY},
        {
            "lever": "daily_cap@standing",
            "key": "daily_cap@standing.behind-plus",
            "status": sc.PLAY,
            "override": "daily_cap@standing.behind",
        },
    ]
    screen = {"measure": "matchup_wins", "rows": rows}
    with pytest.raises(ValueError):
        tn.order_of({**screen, "rows": rows[1:]}, None)
    assert tn.split_order_of({**screen, "rows": rows[:1]}, None) == []


# --------------------------------------------------------------------------- no peek
def peek_records(setup, lines) -> dict:
    """The no-peek check's season (``test_no_peek``) with an override on each axis: an exact seat
    among the market that blends in the run-in alone, and a surrogate seat among its mirror that
    takes a second add while on the line and blends while behind it."""
    from tests.sim.test_no_peek import SEED, WEIGHTS

    a = checked(arm("A", "exact", "market"), **ov(rate_shrink__phase__run_in=0.5))
    b = checked(
        arm("B", "surrogate", "mirror"),
        **ov(daily_cap__standing__line=2, rate_shrink__standing__behind=0.5),
    )
    got = {}

    def keep(r: rn.DayRecord) -> None:
        got[(r.day, r.variant)] = nopeek.digest(r)

    w = rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS)
    variants = [{**rn.opponents_of(setup, x, 1), 1: x.seat()} for x in (a, b)]
    rn.simulate(setup, w, variants, on_day=keep)
    return got


@pytest.mark.parametrize("which", [1, 2])
def test_a_seat_with_an_override_on_each_axis_does_not_see_past_the_day(which):
    """The standing reads the weeks finished before the running one and the phase the calendar,
    so a seat that follows either knows nothing dated after the day: its records through the day
    are the same in a world that differs after it, and some record after it differs."""
    from tests.sim.test_no_peek import DAYS, SEED, recorded

    setup, lines = recorded()
    day = DAYS[which]
    assert policy.phase_of(setup.spec, setup.week_of(day).number) == policy.RUN_IN
    base = peek_records(setup, lines)
    got = peek_records(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    assert set(got) == set(base)
    first = nopeek.first_difference(base, got)
    assert first is not None, "the change after the day reached no record: it tested nothing"
    assert first[0] > day, f"a record on {first[0]} saw past {day}: {first[2]}"
    same = [key for key in base if key[0] <= day]
    assert same and all(base[key] == got[key] for key in same)
