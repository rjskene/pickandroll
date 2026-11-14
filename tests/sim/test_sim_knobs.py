"""The knobs, the arm's fields, the season term and the reads table (#172, PR C): twelve knobs in
the engine's bounds, four fields on the arm and the seat, ``season_weight x ROS_w`` on the key the
arm executes (built only above 0), the season scale, and what each knob reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from itertools import product

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.sim import cli as ss
from pickandroll.sim import engine, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.state import Member, initial
from tests.sim.sim_league import KNOBS, arm, inputs, make_setup, rates


# --------------------------------------------------------------------------- the twelve knobs
def test_the_twelve_knobs_are_the_live_ten_and_the_simulators_two():
    assert policy.KNOBS == (*engine.LIVE_KNOBS, "season_weight", "playoff_weight")
    assert len(policy.KNOBS) == 12 and set(KNOBS) == set(policy.KNOBS)
    assert set(policy.KNOB_DEFAULTS) == set(policy.KNOBS)
    assert (
        policy.KNOB_DEFAULTS["season_weight"] == 0 and policy.KNOB_DEFAULTS["playoff_weight"] == 1
    )
    assert {k: policy.KNOB_DEFAULTS[k] for k in engine.LIVE_KNOBS} == dict(engine.DEFAULTS)
    assert policy.check_knobs(policy.KNOB_DEFAULTS) == dict(policy.KNOB_DEFAULTS)
    assert list(policy.check_knobs(KNOBS)) == list(policy.KNOBS)


@pytest.mark.parametrize(
    ("change", "error", "words"),
    [
        ({"system": "espn"}, ValueError, "'system' refused: system 'espn' is not one of"),
        ({"protection_floor": "high"}, ValueError, "protection_floor 'high' is not a number"),
        ({"daily_cap": 1.5}, ValueError, "daily_cap 1.5 is not a whole number"),
        ({"daily_cap": 0}, ValueError, "daily_cap 0 is below its minimum 1"),
        ({"daily_cap": 4}, ValueError, "daily_cap 4 is above its maximum 3"),
        ({"three_weight": 1.5}, ValueError, "three_weight 1.5 is above its maximum 1.0"),
        ({"blend": 0.1}, ValueError, "blend 0.1 is below its minimum 0.25"),
        ({"daily_cap": None}, ValueError, "daily_cap is None: the engine takes a value"),
        ({"season_weight": -0.5}, ValueError, "season_weight -0.5 is below its minimum 0"),
        ({"season_weight": None}, ValueError, "season_weight None is not a number"),
        ({"playoff_weight": "twice"}, ValueError, "playoff_weight 'twice' is not a number"),
        ({"playoff_weight": float("inf")}, ValueError, "playoff_weight inf is not a finite"),
        ({"rival_claim_rate": 0.3}, ValueError, "knob 'rival_claim_rate' is not a knob"),
    ],
)
def test_a_knob_out_of_bounds_or_unknown_is_refused_by_name(change, error, words):
    with pytest.raises(error, match=None) as e:
        policy.check_knobs({**KNOBS, **change})
    assert words in str(e.value)


def test_a_missing_knob_is_refused_by_name_and_none_stays_where_the_engine_takes_it():
    for name in policy.KNOBS:
        with pytest.raises(KeyError) as e:
            policy.check_knobs({k: v for k, v in KNOBS.items() if k != name})
        assert repr(name) in str(e.value) and "names every knob" in str(e.value)
    # The engine's own defaults of None: the blend weight, the stash threshold, the FAAB sizing.
    assert policy.TAKES_NONE == {"blend", "stash_threshold", "faab_sizing"}
    assert policy.check_knobs({**KNOBS, "blend": None, "faab_sizing": None})["blend"] is None
    assert policy.check_knobs({**KNOBS, "stash_threshold": 0.1})["stash_threshold"] == 0.1


def test_an_arm_spec_is_refused_on_a_bad_knob_and_policy_knobs_adds_the_two(tmp_path):
    spec = {"name": "A", "tier": "exact", "knobs": {**KNOBS, "daily_cap": 9}}
    with pytest.raises(ValueError, match="daily_cap 9 is above its maximum 3"):
        rn.arm_of(spec)
    # No knob file: the twelve defaults.
    assert ss.policy_knobs(tmp_path, "100001") == dict(policy.KNOB_DEFAULTS)


# --------------------------------------------------------------------------- the four fields
def test_the_fields_default_to_the_live_routes_figures_and_are_refused_by_name():
    f = policy.fields_of({})
    assert f == policy.Fields() == policy.DEFAULT_FIELDS
    assert (f.pool, f.min_gain, f.weeks_ahead, f.surrogate_days) == (30, 0.01, 4, (0, 3))
    assert f.payload() == {"pool": 30, "min_gain": 0.01, "weeks_ahead": 4, "surrogate_days": [0, 3]}
    g = policy.fields_of({"pool": 12, "min_gain": 0, "weeks_ahead": 6, "surrogate_days": [3, 0, 3]})
    assert g == policy.Fields(12, 0.0, 6, (0, 3))
    for bad, words in (
        ({"pool": 0}, "pool 0: a whole number, 1 or more"),
        ({"pool": 2.5}, "pool 2.5: a whole number"),
        ({"pool": True}, "pool True: a whole number"),
        ({"min_gain": -0.1}, "min_gain -0.1: a number, 0 or more"),
        ({"min_gain": "small"}, "min_gain 'small': a number"),
        ({"weeks_ahead": 1}, "weeks_ahead 1: a whole number, 2 or more"),
        ({"surrogate_days": []}, "surrogate_days []: a non-empty set of weekdays"),
        ({"surrogate_days": [7]}, "surrogate_days [7]: a non-empty set of weekdays"),
        ({"surrogate_days": "mon"}, "surrogate_days 'mon'"),
    ):
        with pytest.raises(ValueError) as e:
            policy.fields_of(bad)
        assert words in str(e.value)
        with pytest.raises(ValueError):
            rn.arm_of({"name": "A", "tier": "exact", "knobs": KNOBS, **bad})
    a = rn.arm_of({"name": "A", "tier": "surrogate", "knobs": KNOBS, "pool": 5})
    assert a.fields == policy.Fields(pool=5) and a.seat().fields == a.fields


def test_the_default_fields_reproduce_todays_decisions():
    setup = make_setup(seed=3)
    state = replace(initial(setup), day=setup.start + timedelta(3))
    built = policy.problem_of(setup, state, 1, KNOBS, setup.projection, {}, {})
    f = policy.Fields()
    assert policy.exact(built) == policy.exact(built, fields=f)
    assert policy.surrogate(built) == policy.surrogate(built, f)
    for tier in policy.TIERS:
        assert policy.decide(built, tier) == policy.decide(built, tier, fields=f)
    # weeks_ahead is the problem's: the three weeks' horizon is weeks_ahead - 1 later weeks.
    six = policy.problem_of(setup, state, 1, KNOBS, setup.projection, {}, {}, weeks_ahead=6)
    assert len(built.problem.horizons["three"]) == 3 and len(six.problem.horizons["three"]) == 5


def test_two_seats_that_differ_only_in_pool_decide_apart_inside_one_run():
    """Day one, two variants in one ``simulate`` call: the seat with a pool of one can only
    search the best candidate, the seat with thirty takes a set of two adds. The decision cache
    is keyed on the seat's ``repr``, which carries the fields, so the two share no solve."""
    setup = make_setup(seed=3)
    w = rn.forward_world(setup, inputs(), 1, 0, 0.0)
    knobs = {**KNOBS, "daily_cap": 3}
    wide = op.Seat("W", "exact", knobs, with_plan=False)
    narrow = op.Seat("W", "exact", knobs, with_plan=False, fields=policy.Fields(pool=1))
    assert repr(wide) != repr(narrow)
    first: dict[int, policy.Decision] = {}

    def keep(r: rn.DayRecord) -> None:
        if r.day == setup.start:
            first[r.variant] = r.decisions[1]

    static = {t: op.Static() for t in setup.teams if t != 1}
    out = rn.simulate(setup, w, [{**static, 1: wide}, {**static, 1: narrow}], on_day=keep)
    adds = [{m.add for m in first[v].moves} for v in (0, 1)]
    assert adds == [{17, 20}, {17}]
    assert out[1].shared == 0  # no decision of the narrow seat was the wide one's


def test_the_mirror_carries_the_arms_fields():
    f = policy.Fields(pool=7, weeks_ahead=3, surrogate_days=(1,))
    mirror = op.of({"kind": "mirror"}, KNOBS, 0.1, f)
    assert isinstance(mirror, op.Mirror) and mirror.fields == f and mirror.knobs == KNOBS
    a = replace(arm("A", "exact", "mirror"), fields=f)
    rivals = rn.opponents_of(make_setup(), a, 1)
    assert {r.fields for r in rivals.values()} == {f}
    # At the defaults the mirror is what it was.
    assert op.of({"kind": "mirror"}, KNOBS, 0.1) == op.Mirror(KNOBS)


# --------------------------------------------------------------------------- the season term
def _played(setup, team: str, start: date, bracket: frozenset[date], w: float = 1.0) -> float:
    """By hand: ``team``'s games from ``start`` to the season's end, bracket days ``w`` times."""
    days = [start + timedelta(i) for i in range((setup.season_end - start).days + 1)]
    return sum(
        (w if d in bracket else 1.0) for d in days if team in setup.schedule.get(d, frozenset())
    )


def test_the_season_figure_by_hand():
    setup = make_setup(seed=3, weeks=6, playoff_weeks=1)
    state = initial(setup)
    day = setup.start
    roster = state.active(1)
    out_until, gone_for_good, healthy = roster[0], roster[1], roster[2]
    back = day + timedelta(12)
    status = {out_until: "O", gone_for_good: "OFS"}
    built = policy.problem_of(setup, state, 1, KNOBS, setup.projection, status, {out_until: back})
    p = built.problem
    bracket = policy.bracket_days(setup)
    assert built.bracket == bracket and len(bracket) == 7
    assert bracket == frozenset(setup.calendar.weeks[-1].days())
    add = setup.pool[0]
    tomorrow = day + timedelta(1)  # a free agent lands the next day: the day the move counts
    team = {k: setup.players[k].nba_team for k in setup.players}

    def by_hand(k: int, start: date, w: float = 1.0) -> float:
        return (p.season_value[k] - p.dead) * _played(setup, team[k], start, bracket, w)

    fig = policy.SeasonFigure(built, 1.0)
    # An add with a drop, and an add alone (a held-slot move or an open spot).
    swap = mv.Move(add, healthy)
    assert fig.move(swap) == pytest.approx(by_hand(add, tomorrow) - by_hand(healthy, tomorrow))
    assert fig.move(mv.Move(add, None)) == pytest.approx(by_hand(add, tomorrow))
    # Out until a date: he counts from his return. Not back this season: worth nothing.
    assert fig.worth(out_until, tomorrow) == pytest.approx(by_hand(out_until, back))
    assert fig.worth(gone_for_good, tomorrow) == 0.0
    assert fig.move(mv.Move(add, gone_for_good)) == pytest.approx(by_hand(add, tomorrow))
    # Bracket games count playoff_weight times.
    twice = policy.SeasonFigure(built, 2.0)
    assert twice.worth(add, tomorrow) == pytest.approx(by_hand(add, tomorrow, 2.0))
    in_bracket = _played(setup, team[add], tomorrow, bracket, 2.0) - _played(
        setup, team[add], tomorrow, bracket
    )
    assert in_bracket == len([d for d in bracket if team[add] in setup.schedule[d]]) > 0
    # The two invariants at playoff_weight 1: the engine's units, not a third one.
    player = dict(p.roster)[out_until]
    assert fig.worth(add, tomorrow) == pytest.approx(mv.worth_from(p, add, tomorrow))
    assert fig.worth(healthy, tomorrow) == pytest.approx(mv.worth_from(p, healthy, tomorrow))
    assert fig.worth(out_until, tomorrow) == pytest.approx(mv.net_of_return(p, out_until, player))
    # A set's is the sum over its moves, and a move with no season value counts zero.
    other = mv.Move(setup.pool[1], roster[3])
    assert fig.of([swap, other]) == pytest.approx(fig.move(swap) + fig.move(other))
    unvalued = replace(p, season_value={k: v for k, v in p.season_value.items() if k != add})
    blank = policy.SeasonFigure(replace(built, problem=unvalued), 1.0)
    assert blank.move(swap) is None and blank.of([swap, other]) == pytest.approx(fig.move(other))


def test_at_season_weight_zero_the_wrapper_is_not_built_and_each_tier_decides_as_before(
    monkeypatch,
):
    """Each tier's decisions on three policy days, pinned from main ``7f180c7`` (before the
    term): at ``season_weight`` 0 they are the same, and no wrapper is ever made."""

    def never(*a, **k):
        raise AssertionError("the season term's wrapper was built at season_weight 0")

    monkeypatch.setattr(policy.Seasoned, "__init__", never)
    knobs = {**KNOBS, "daily_cap": 3}
    want = {
        ("held", 0): {
            "exact": [(17, None), (20, 6), (8, None)],
            "weighted": [(17, None), (20, 6), (8, None)],
            "surrogate": [(17, None), (20, 6), (8, None)],
        },
        ("held", 3): {
            "exact": [(17, None), (20, 6), (5, None)],
            "weighted": [(20, None), (17, 6), (8, None)],
            "surrogate": [(17, None), (20, 6), (5, None)],
        },
        ("plain", 8): {
            "exact": [(17, None), (8, 12)],
            "surrogate": [(17, None), (8, 12)],
            "ranking": [(20, 23)],
        },
    }
    for (kind, off), tiers in want.items():
        setup = make_setup(seed=3, held_slots=("IL",) if kind == "held" else ())
        day = setup.start + timedelta(off)
        state = replace(initial(setup), day=day)
        team = 1 if kind == "held" else 4
        status, returns = {}, {}
        if kind == "held":
            k = state.active(1)[0]
            status, returns = {k: "O"}, {k: day + timedelta(9)}
        built = policy.problem_of(setup, state, team, knobs, setup.projection, status, returns)
        got = {
            "exact": policy.exact(built),
            "weighted": policy.exact(built, executes=policy.WEIGHTED),
            "surrogate": policy.surrogate(built),
            "ranking": policy.ranking(built),
        }
        for tier, moves in tiers.items():
            assert [(m.add, m.drop) for m in got[tier].moves] == moves, (kind, off, tier)


def flip_setup() -> tuple:
    """A two-team league where the three weeks and the season disagree: free agent ``WEAK`` is a
    poor player whose team plays every day of weeks 2 to 4 (the three weeks' horizon on day one)
    and never after; ``STRONG`` is a far better one whose team plays only in weeks 5 and 6 (the
    last the bracket's). Team 1 holds ``DEAD``, a near-empty line whose team never plays."""
    base = make_setup(teams=2, spots=5, pool=0, weeks=6, playoff_weeks=1, playoff_teams=2)
    weak, strong, dead = 101, 102, 103
    weeks = base.calendar.weeks
    schedule = {d: set(t) for d, t in base.schedule.items()}
    for w in weeks[1:4]:
        for d in w.days():
            schedule[d].add("WWW")
    for w in weeks[4:6]:
        for d in w.days():
            schedule[d].add("SSS")
    players = {
        **base.players,
        weak: Member(weak, "Weak", "WWW", ("PG",)),
        strong: Member(strong, "Strong", "SSS", ("PG",)),
        dead: Member(dead, "Dead", "ZZZ", ("PG",)),
    }
    projection = {
        **base.projection,
        weak: rates(0.7),
        strong: rates(2.5),
        dead: {s: 0.05 * x for s, x in rates(0.1).items()},
    }
    mine = list(base.rosters[1])
    out = mine[-1][0]
    mine[-1] = (dead, mine[-1][1])
    setup = replace(
        base,
        players=players,
        projection=projection,
        schedule={d: frozenset(t) for d, t in schedule.items()},
        rosters={**base.rosters, 1: tuple(mine)},
        pool=(weak, strong, out),
    )
    return setup, weak, strong, dead


def _decisions(setup, weight: float) -> dict[str, policy.Decision]:
    knobs = {**KNOBS, "season_weight": weight}
    built = policy.problem_of(setup, initial(setup), 1, knobs, setup.projection, {}, {})
    return {tier: policy.decide(built, tier, with_plan=False) for tier in policy.TIERS}


def test_the_season_term_flips_the_choice_on_the_exact_and_surrogate_tiers_not_the_ranking():
    setup, weak, strong, dead = flip_setup()
    built = policy.problem_of(setup, initial(setup), 1, KNOBS, setup.projection, {}, {})
    fig = policy.SeasonFigure(built, 1.0)
    assert fig.move(mv.Move(strong, dead)) > fig.move(mv.Move(weak, dead)) > 0
    before, after = _decisions(setup, 0.0), _decisions(setup, 1.0)
    for tier in ("exact", "surrogate"):
        assert weak in {m.add for m in before[tier].moves}, tier
        assert strong not in {m.add for m in before[tier].moves}, tier
        assert strong in {m.add for m in after[tier].moves}, tier
    assert before["ranking"] == after["ranking"]
    # The term is on the executed key only: the week's value is untouched.
    ev = mv.Evaluator(built.problem)
    term = policy.Seasoned(ev, policy.QUEUE_SET, 2.0, fig)
    m = (mv.Move(strong, dead),)
    assert term.value("week", m) == ev.value("week", m)
    assert term.value("three", m) == pytest.approx(ev.value("three", m) + 2.0 * fig.of(m))
    assert term.base == ev.base and term.gain("three", ()) == 0


def test_the_weighted_strategy_takes_the_term_too():
    setup, _, strong, _ = flip_setup()
    picks = {}
    for weight in (0.0, 1.0):
        knobs = {**KNOBS, "season_weight": weight}
        built = policy.problem_of(setup, initial(setup), 1, knobs, setup.projection, {}, {})
        d = policy.exact(built, executes=policy.WEIGHTED, with_plan=False)
        picks[weight] = {m.add for m in d.moves}
    assert strong not in picks[0.0] and strong in picks[1.0]


def test_the_season_scale_by_hand_and_no_outcome_changes_with_it(monkeypatch):
    setup, weak, strong, _ = flip_setup()
    built = policy.problem_of(setup, initial(setup), 1, KNOBS, setup.projection, {}, {})
    ev = mv.Evaluator(built.problem)
    fig = policy.SeasonFigure(built, 1.0)
    # The exact tier's pool is the candidates whose best swap gains: the strong player's gains
    # nothing in the three weeks, so the scale is the weak one's swap alone.
    swaps = mv.single_swaps(ev, policy.QUEUE_SET)
    gainers = [c for c, g in swaps.items() if g and g[0].gain > policy.MIN_GAIN]
    assert weak in gainers and strong not in gainers
    s = policy.scale_of(built, "exact")
    rows = [(swaps[c][0].gain, fig.move(mv.Move(c, swaps[c][0].drop))) for c in gainers]
    assert s.swaps == len(rows)
    assert s.gain == pytest.approx(float(np.median([g for g, _ in rows])))
    assert s.ros == pytest.approx(float(np.median([r for _, r in rows])))
    assert s.ratio == pytest.approx(s.gain / s.ros)
    # The surrogate's pool is every candidate by value times games: a median over three.
    sur = policy.scale_of(built, "surrogate")
    every = mv.single_swaps(ev, policy.QUEUE_SET, policy._surrogate_pool(built, policy.Fields()))
    gains = [g[0].gain for g in every.values() if g]
    assert sur.swaps == len(gains) == 3 and sur.gain == pytest.approx(float(np.median(gains)))
    assert policy.scale_of(built, "ranking") is None and policy.scale_of(built, "static") is None
    # The same at any season_weight: it is taken without the term.
    heavy = replace(built, knobs={**built.knobs, "season_weight": 5.0})
    assert policy.scale_of(heavy, "exact") == s
    # A run's outcomes are the same with the scale and without it.
    setup = make_setup(seed=5)
    w = rn.forward_world(setup, inputs(), 2, 0, 0.0)
    a, b = arm("A", "exact"), arm("B", "surrogate")
    with_scale = rn.paired(setup, w, a, b, 1)
    assert with_scale["scale"]["a"]["swaps"] > 0 and with_scale["scale"]["b"] is not None
    monkeypatch.setattr(rn, "scale_on", lambda *args: None)
    without = rn.paired(setup, rn.forward_world(setup, inputs(), 2, 0, 0.0), a, b, 1)
    assert {k: v for k, v in with_scale.items() if k != "scale"} == {
        k: v for k, v in without.items() if k != "scale"
    }


# --------------------------------------------------------------------------- the reads table
SHAPES = [policy.Shape(s, h, b) for s, h, b in product(("categories", "points"), (0, 1), (0, 1))]
CONFIGS = [
    rn.Arm("X", t, {**KNOBS, "season_weight": sw}, {"kind": "market"}, e, wp, ep)
    for t, e, wp, ep, sw in product(
        (*policy.TIERS, "static"), policy.EXECUTES, (True, False), (True, False), (0.0, 0.5)
    )
]


def test_the_tripwire_every_live_knob_has_a_row_in_every_shape():
    """A knob added to the live file (``progress.LIVE_KNOBS``, read through the door) fails here
    until someone gives it a row."""
    for config, shape, mirror in product(CONFIGS, SHAPES, (False, True)):
        table = policy.reads(config, shape, mirror)
        assert set(engine.LIVE_KNOBS) <= set(table), set(engine.LIVE_KNOBS) - set(table)
        assert list(table) == list(policy.KNOBS)
        assert all(isinstance(v, str) and v for v in table.values())
        assert list(policy.field_reads(config, mirror)) == list(policy.FIELDS)
    assert set(policy.WHEN_READ) == {*policy.KNOBS, *policy.FIELDS}


def test_the_reads_table_as_built():
    cats = policy.Shape()
    exact = rn.Arm("E", "exact", KNOBS, {}, execute_plan=True)
    read = {k for k, v in policy.reads(exact, cats).items() if v == policy.READ}
    assert read == {"protection_floor", "daily_cap", "plan_floor_cats", "season_weight"}
    heavy = replace(exact, knobs={**KNOBS, "season_weight": 0.5}, executes=policy.WEIGHTED)
    read = {k for k, v in policy.reads(heavy, cats).items() if v == policy.READ}
    assert read == {
        "protection_floor",
        "daily_cap",
        "horizon_weight",
        "plan_floor_cats",
        "season_weight",
        "playoff_weight",
    }
    no_bracket = policy.reads(heavy, policy.Shape(bracket=False))
    assert no_bracket["playoff_weight"] == "the league has no bracket read"
    points = policy.reads(heavy, policy.Shape("points"))
    assert points["plan_floor_points"] == policy.READ and points["plan_floor_cats"] == (
        "a points league"
    )
    ranking = policy.reads(rn.Arm("R", "ranking", KNOBS, {}), cats)
    assert {k for k, v in ranking.items() if v == policy.READ} == {"protection_floor"}
    assert ranking["daily_cap"].startswith("the ranking tier queues one move a day")
    static = policy.reads(rn.Arm("S", "static", KNOBS, {}), cats)
    assert set(static.values()) - {policy.STATIC} == {
        static[k]
        for k in ("horizon_weight", "plan_floor_cats", "plan_floor_points", "three_weight")
    } | {static[k] for k in ("system", "blend", "faab_sizing", "stash_threshold")}
    # Rivals that mirror a static seat read what the surrogate reads.
    mirrored = policy.reads(rn.Arm("S", "static", KNOBS, {}), cats, mirrored=True)
    assert {k for k, v in mirrored.items() if v == policy.READ} == {
        "protection_floor",
        "daily_cap",
        "season_weight",
    }
    for never in ("three_weight", "system", "blend", "faab_sizing", "stash_threshold"):
        assert all(policy.reads(c, s)[never] != policy.READ for c in CONFIGS for s in SHAPES)
    f = policy.field_reads(rn.Arm("R", "surrogate", KNOBS, {}))
    assert set(f.values()) == {policy.READ}
    assert policy.field_reads(exact)["surrogate_days"] == "the exact tier decides every day"


def _day_records(setup, w, a: rn.Arm, b: rn.Arm, me: int) -> tuple[list, list]:
    """B1's day records of arm A and arm B in seat ``me`` (the other seats static) through one
    world, each day's digest by variant."""
    from pickandroll.sim import nopeek

    got: dict[int, list] = {0: [], 1: []}

    def keep(r: rn.DayRecord) -> None:
        # The decision holds what the seat drew, a plan it does not execute among it; the table
        # is about what the seat queues, so the comparison leaves the decision out.
        d = nopeek.digest(r)
        d.pop("decisions")
        got[r.variant].append((r.day, d))

    static = {t: op.Static() for t in setup.teams if t != me}
    rn.simulate(
        setup,
        w,
        [{**static, me: a.seat()}, {**static, me: b.seat()}],
        [a.execute_plan, b.execute_plan],
        on_day=keep,
    )
    return got[0], got[1]


def points_setup(seed: int = 3):
    """``make_setup``'s league scored in points: the problem then reads the points plan floor."""
    table = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0, "threes": 1.0}
    base = make_setup(seed=seed, weeks=3, playoff_weeks=1)
    return replace(
        base,
        scoring="points",
        points=table,
        cats=("fpts",),
        spec=replace(base.spec, scoring="points", points=table, cats=()),
    )


def weakened(setup, n: int = 2):
    """Seat 1's best ``n`` change places with the pool's worst ``n``: the pool then holds players
    better than some of the seat's, so the stream has spots and draws its plans."""
    pts = setup.points if setup.scoring == "points" else None
    value = wk.per_game_values(setup.projection, setup.cats, pts)
    mine = sorted(setup.rosters[1], key=lambda m: -value[m[0]])
    pool = sorted(setup.pool, key=lambda k: value[k])
    roster = [(k, slot) for k, (_, slot) in zip(pool[:n], mine[:n], strict=True)] + mine[n:]
    return replace(
        setup,
        rosters={**setup.rosters, 1: tuple(roster)},
        pool=(*(k for k, _ in mine[:n]), *pool[n:]),
    )


def strong(setup, me: int = 4):
    """Seat ``me``'s players all good alike and the pool's best a star: every one of the seat's
    is worth keeping on his own, none beats the star, so the protection floor decides who may go
    (a higher floor protects more)."""
    proj = dict(setup.projection)
    for k, _ in setup.rosters[me]:
        proj[k] = rates(1.2)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    proj[max(setup.pool, key=lambda k: value[k])] = rates(1.8)
    return replace(setup, projection=proj)


LEAGUES = {
    "cats": lambda: make_setup(seed=3, weeks=3, playoff_weeks=1),
    "points": points_setup,
    "weak cats": lambda: weakened(make_setup(seed=3, weeks=3, playoff_weeks=1)),
    "weak points": lambda: weakened(points_setup()),
    "strong": lambda: strong(make_setup(seed=3, weeks=3, playoff_weeks=1)),
}

#: For each knob, cases of two arms that differ only in it: the arm's tier, what it executes,
#: whether it draws and executes the plan, the knobs it starts from, the two values, the seat and
#: the league (:data:`LEAGUES`). The rows say ``read`` or not; the records must agree with them.
#: The plan floors' read cases go below zero: the synthetic leagues' plans gain nothing over
#: their sets (every team plays every other day), so a floor under zero takes each plan the stream
#: draws and one of 50 none. A floor of exactly zero would rest on the plan's gap being 0.0 or
#: 1e-16, which the engine's evaluator leaves to the order it sums in.
CASES = [
    # Never read yet: on the exact tier executing everything it can.
    ("three_weight", "exact", "three", True, True, {}, (0.0, 0.9), 1, "cats"),
    ("system", "exact", "three", True, True, {}, ("bbm", "yahoo"), 1, "cats"),
    ("blend", "exact", "three", True, True, {}, (None, 0.5), 1, "cats"),
    ("faab_sizing", "exact", "three", True, True, {}, (None, 2.0), 1, "cats"),
    ("stash_threshold", "exact", "three", True, True, {}, (None, 0.5), 1, "cats"),
    # Read only somewhere: a case where it is not, and one built where it is.
    ("horizon_weight", "exact", "three", True, False, {}, ("natural", "season"), 1, "cats"),
    ("horizon_weight", "exact", "weighted", False, False, {}, ("natural", "season"), 1, "cats"),
    ("plan_floor_cats", "exact", "three", True, False, {}, (-1.0, 50.0), 1, "weak cats"),
    ("plan_floor_cats", "exact", "three", True, True, {}, (-1.0, 50.0), 1, "weak cats"),
    ("plan_floor_cats", "exact", "three", True, True, {}, (-1.0, 50.0), 1, "weak points"),
    ("plan_floor_points", "exact", "three", True, True, {}, (-1.0, 50.0), 1, "weak cats"),
    ("plan_floor_points", "exact", "three", True, True, {}, (-1.0, 50.0), 1, "weak points"),
    ("daily_cap", "ranking", "three", True, False, {}, (1, 3), 4, "cats"),
    ("daily_cap", "exact", "three", False, False, {}, (1, 3), 1, "cats"),
    ("protection_floor", "static", "three", True, False, {}, (0.0, 100.0), 4, "cats"),
    ("protection_floor", "ranking", "three", True, False, {}, (0.0, 100.0), 4, "strong"),
    ("protection_floor", "exact", "three", True, False, {}, (0.0, 100.0), 4, "strong"),
    ("season_weight", "ranking", "three", True, False, {}, (0.0, 1.0), 4, "cats"),
    ("season_weight", "exact", "three", False, False, {}, (0.0, 1.0), 1, "cats"),
    ("season_weight", "surrogate", "three", False, False, {}, (0.0, 1.0), 1, "cats"),
    ("playoff_weight", "exact", "three", False, False, {}, (1.0, 5.0), 1, "cats"),
    (
        "playoff_weight",
        "exact",
        "three",
        False,
        False,
        {"season_weight": 0.05},
        (1.0, 5.0),
        1,
        "cats",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c[0]}-{c[1]}-{c[2]}-{c[8]}-{c[6]}")
def test_the_reads_table_against_behaviour(case):
    """A row that says a knob is not read gives identical day records; one that says ``read``
    gives different records on the case built for it."""
    name, tier, executes, with_plan, execute_plan, base, (va, vb), me, league = case
    setup = LEAGUES[league]()
    w = rn.forward_world(setup, inputs(), 7, 0, 0.0)
    knobs = {**KNOBS, "daily_cap": 3, **base}
    a = rn.Arm(
        "A", tier, {**knobs, name: va}, {"kind": "static"}, executes, with_plan, execute_plan
    )
    b = replace(a, name="B", knobs={**knobs, name: vb})
    shape = policy.shape_of(setup)
    rows = {policy.reads(a, shape)[name], policy.reads(b, shape)[name]}
    read = policy.READ in rows
    ra, rb = _day_records(setup, w, a, b, me)
    assert len(ra) == len(rb) > 0
    if read:
        assert ra != rb, f"{name} is read here and the records agree"
    else:
        assert ra == rb, f"{name} is not read here ({rows}) and the records part"


def test_a_comparison_of_the_same_seat_is_refused_by_name():
    shapes = [policy.Shape()]
    a = arm("A", "exact")
    same = rn.same_seat(a, replace(a, knobs={**a.knobs, "three_weight": 0.9}), shapes)
    assert same is not None and len(same) == 1
    assert same[0].startswith("three_weight (it weighs the three weeks in the queue's score")
    assert "read by the queue's rule (PR E)" in same[0]
    # Two unread, both named; one read among them and they are two seats.
    two = replace(a, knobs={**a.knobs, "three_weight": 0.9, "playoff_weight": 2.0})
    assert [x.split(" ")[0] for x in rn.same_seat(a, two, shapes)] == [
        "three_weight",
        "playoff_weight",
    ]
    assert rn.same_seat(a, replace(a, knobs={**a.knobs, "daily_cap": 2}), shapes) is None
    # A field: the exact tier never reads the surrogate's days.
    days = replace(a, fields=policy.Fields(surrogate_days=(0,)))
    assert rn.same_seat(a, days, shapes) == [
        "surrogate_days (the exact tier decides every day; read by the surrogate tier)"
    ]
    # The same arm twice is a check that the difference is zero, not a refusal; a mirror reads.
    assert rn.same_seat(a, a, shapes) is None
    r = arm("R", "ranking", "mirror")
    assert rn.same_seat(r, replace(r, knobs={**r.knobs, "daily_cap": 2}), shapes) is None
    assert rn.same_seat(r, replace(r, knobs={**r.knobs, "daily_cap": 2}), shapes, False) == [
        (
            "daily_cap (the ranking tier queues one move a day, under any cap; read by the exact "
            "or the surrogate tier, which may queue more than one move a day)"
        )
    ]
    # The commands' message.
    msg = ss.same_seats({"A": a, "B": two}, shapes, rivals=True)
    assert msg.startswith("arms A and B are the same seat: they differ only in three_weight (")


def test_a_weighted_arm_takes_this_weeks_weight_when_no_week_follows():
    """In the last week the engine's frontier is this week's alone (``strategy.weights``); the
    weighted arm then weighs this week alone, whatever its ``horizon_weight``, and runs on."""
    for key in ("even", "natural", "season"):
        assert policy._weight({"horizon_weight": key}, 0) == 1.0
        assert policy._weight({"horizon_weight": key}, 2) == next(
            w.lam for w in engine.sg.weights(2) if w.key == key
        )
    with pytest.raises(KeyError, match="'often' is not one of"):
        policy._weight({"horizon_weight": "often"}, 2)
