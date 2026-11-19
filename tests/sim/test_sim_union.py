"""The union pool as an arm's choice (#172, PR pool): an arm's fifth field, ``guard_pool``, the
size of the guard's list (0, the default, is off). Above 0 the exact tier's searches take the
engine's own pool (``season.pool``, through the door as ``sp``): the best ``pool`` adds by single
swap, then the adds whose best single move the season guard admits. How the field is parsed and
refused, who reads it, the pool a search is handed against the door's own answer, a made-up day
on which it changes what the seat queues, the counts, the record, Rule 1, no peek and every
league kind once. ``test_sim_pool.py`` is the worker pool's and is not this.

Made-up leagues, fixed seeds. A test whose seat weighs runs in both head-to-head formats, or
says why it names one."""

from __future__ import annotations

import inspect
import re
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pickandroll.season import pool as season_pool
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import engine, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, sg, wk
from pickandroll.sim.state import Member, initial
from tests.sim.sim_league import KNOBS, NINE, make_setup, of_format, rates, replay_of

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
FORMATS = (ONE_WIN, EACH_CATEGORY)
#: The four fields an arm had before this one, in the payload's order.
FOUR = ("pool", "min_gain", "weeks_ahead", "surrogate_days")
#: The union's counts, in the payload's order.
UNION_KEYS = (
    "union_days",
    "union_admitted",
    "union_admitted_days",
    "union_taken_days",
    "union_head_refused_days",
)


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def spec(name="A", tier="exact", opponents="static", knobs=None, **more) -> dict:
    return {
        "name": name,
        "tier": tier,
        "knobs": {**KNOBS, **(knobs or {})},
        "opponents": {"kind": opponents},
        **more,
    }


def armed(name="A", tier="exact", opponents="static", knobs=None, **more) -> rn.Arm:
    return rn.arm_of(spec(name, tier, opponents, knobs, **more))


SOON, SOONER, STEADY, NOW = 101, 102, 103, 104
#: A head of two: the made-up leagues below have few free agents, and a head that holds them all
#: leaves the guard's list nothing to bring.
TWO = policy.Fields(pool=2)


def refusing(h2h: str = ONE_WIN, now: bool = False):
    """A two-seat league on whose first day the season guard refuses the whole head (after
    ``test_sim_knobs``'s flip league). Seat 1's six spots are full. ``SOON`` and ``SOONER`` are
    modest free agents whose team plays every day of weeks 2 to 4 (the three weeks' horizon on
    day one) and never after: each one's swaps gain the most over the three weeks and lose over
    the rest of the season, so the guard refuses every one. ``STEADY`` plays all season and is a
    little better than the seat's weakest: the smallest gain of the three, and the guard admits
    it. With ``now``, a fourth, ``NOW``, whose team plays every day of this week and never
    after: the week's best add (the weighted search's head takes each horizon's best in turn),
    refused the same way."""
    base = make_setup(teams=2, spots=6, pool=0, weeks=6, playoff_teams=2)
    weeks = base.calendar.weeks
    schedule = {d: set(t) for d, t in base.schedule.items()}
    for w in weeks[1:4]:
        for d in w.days():
            schedule[d].add("WWW")
    players = {
        **base.players,
        SOON: Member(SOON, "Soon", "WWW", ("PG",)),
        SOONER: Member(SOONER, "Sooner", "WWW", ("PG",)),
        STEADY: Member(STEADY, "Steady", "AAA", ("PG",)),
    }
    projection = {
        **base.projection,
        SOON: rates(0.55),
        SOONER: rates(0.5),
        STEADY: rates(0.8),
    }
    pool = [SOON, SOONER, STEADY]
    if now:
        for d in weeks[0].days():
            schedule[d].add("NNN")
        players[NOW] = Member(NOW, "Now", "NNN", ("PG",))
        projection[NOW] = rates(0.6)
        pool.append(NOW)
    setup = replace(
        base,
        players=players,
        projection=projection,
        schedule={d: frozenset(t) for d, t in schedule.items()},
        pool=tuple(pool),
        market=wk.per_game_values(projection, NINE, None),
    )
    return of_format(setup, h2h)


def built_of(setup, team: int = 1, **knobs) -> policy.Built:
    """``team``'s problem on day one, on the projection."""
    built = policy.problem_of(
        setup, initial(setup), team, {**KNOBS, **knobs}, setup.projection, {}, {}
    )
    assert built is not None
    return built


def held_day(h2h: str, full: bool) -> tuple[policy.Built, int]:
    """Seat 1's problem on day one of a league with one IL slot (after ``test_sim_policy``'s IL
    league): its five drafted players and one more active player, who is out for nine days;
    with ``full``, a seventh in the IL slot (``held``, out for the season). So an add can come
    with no drop while the slot is open (the player who is out goes to it), and with the held
    player's drop once it is full (a churn). The problem, and ``held``."""
    setup = of_format(make_setup(held_slots=("IL",)), h2h)
    free = sorted(initial(setup).pool)
    held, hurt = free[0], free[1]
    mine = (*setup.rosters[1], (hurt, "BN"), *(((held, "IL"),) if full else ()))
    setup = replace(setup, rosters={**setup.rosters, 1: mine})
    state = initial(setup)
    status = {hurt: "O", held: "O"}
    returns = {hurt: state.day + timedelta(9), held: state.day + timedelta(200)}
    built = policy.problem_of(setup, state, 1, KNOBS, setup.projection, status, returns)
    assert built is not None
    return built, held


def adds(decision: policy.Decision) -> list[int]:
    return [m.add for m in decision.moves]


def searches(monkeypatch) -> list[tuple[str, str, list[int], object]]:
    """Every search the policy asks of the engine from here on (``moves.search`` and
    ``moves.recommend`` as ``sim/policy.py`` calls them; the engine's own calls of one another
    are not kept): its name, its key, the pool it is handed and the allowed set."""
    seen: list[tuple[str, str, list[int], object]] = []
    for name in ("search", "recommend"):
        real = getattr(policy.mv, name)
        signature = inspect.signature(real)

        def spy(*a, _real=real, _sig=signature, _name=name, **k):
            if sys._getframe(1).f_code.co_filename.endswith("sim/policy.py"):
                args = _sig.bind(*a, **k).arguments
                seen.append((_name, args["key"], list(args["pool"]), args.get("allowed")))
            return _real(*a, **k)

        monkeypatch.setattr(policy.mv, name, spy)
    return seen


DOOR = ("pool_for", "admitted_swaps", "joined")


def door_calls(monkeypatch) -> list[tuple[str, tuple]]:
    """Every call ``sim/policy.py`` makes of the engine's pool rule from here on, with its
    arguments (the rule's own calls of its parts are not kept)."""
    seen: list[tuple[str, tuple]] = []
    for name in DOOR:
        real = getattr(season_pool, name)

        def spy(*a, _real=real, _name=name):
            if sys._getframe(1).f_code.co_filename.endswith("sim/policy.py"):
                seen.append((_name, a))
            return _real(*a)

        monkeypatch.setattr(season_pool, name, spy)
    return seen


def no_door(monkeypatch) -> None:
    """From here on a call of the engine's pool rule fails the test."""

    def never(*a, **k):
        raise AssertionError("the pool rule was called with the field off or unread")

    for name in DOOR:
        monkeypatch.setattr(season_pool, name, never)


# --------------------------------------------------------------------------- the door
def test_the_door_exports_the_engine_s_pool_rule():
    """Rule 2: the rule is the engine's, called through the door."""
    assert engine.sp is season_pool and "sp" in engine.__all__
    assert {"pool_for", "admitted_swaps", "joined"} <= set(dir(engine.sp))


# --------------------------------------------------------------------------- the field
def test_guard_pool_is_the_fifth_field_off_by_default_and_written_only_above_zero():
    assert policy.FIELDS == (*FOUR, "guard_pool")
    plain = policy.Fields()
    assert plain.guard_pool == 0 and plain == policy.DEFAULT_FIELDS == policy.fields_of({})
    # Appended last: the four before it are built by position as they were.
    assert policy.Fields(12, 0.0, 6, (0, 3)) == policy.Fields(12, 0.0, 6, (0, 3), 0)
    assert tuple(plain.payload()) == FOUR
    named = policy.fields_of({"guard_pool": 0})
    assert named == plain and tuple(named.payload()) == FOUR
    on = policy.fields_of({"pool": 12, "guard_pool": 30})
    assert on == policy.Fields(pool=12, guard_pool=30)
    assert tuple(on.payload()) == policy.FIELDS and on.payload()["guard_pool"] == 30
    assert {k: v for k, v in on.payload().items() if k != "guard_pool"} == (
        policy.Fields(pool=12).payload()
    )
    a = armed(guard_pool=7)
    assert a.fields.guard_pool == 7 and a.seat().fields == a.fields
    assert "guard_pool" in rn.SPEC_KEYS


@pytest.mark.parametrize(
    ("value", "shown"),
    [(-1, "-1"), (2.5, "2.5"), (True, "True"), ("30", "'30'"), (None, "None")],
)
def test_a_bad_guard_pool_is_refused_by_name(value, shown):
    words = f"guard_pool {shown}: a whole number, 0 or more (0 is off)"
    with pytest.raises(ValueError, match=re.escape(words)):
        policy.fields_of({"guard_pool": value})
    with pytest.raises(ValueError, match=re.escape(words)):
        rn.arm_of(spec(guard_pool=value))


def test_the_payload_carries_the_field_only_for_an_arm_above_zero(tmp_path):
    plain, zero, on = armed("A"), armed("Z", guard_pool=0), armed("B", guard_pool=30)
    p = ss.base_payload(
        "replay",
        "x",
        BUSINESS_HOURS,
        "sha",
        tmp_path / "fit.json",
        {},
        1,
        {"a": plain, "z": zero, "b": on},
    )
    assert tuple(p["fields"]["a"]) == tuple(p["fields"]["z"]) == FOUR
    assert p["fields"]["a"] == p["fields"]["z"]
    assert tuple(p["fields"]["b"]) == policy.FIELDS and p["fields"]["b"]["guard_pool"] == 30
    assert p["surrogate"]["a"] == p["surrogate"]["b"]
    gate = ss.base_payload("validate", "x", BUSINESS_HOURS, "sha", tmp_path / "fit.json", {}, 1)
    assert tuple(gate["fields"]["gate"]) == FOUR


# --------------------------------------------------------------------------- who reads it
#: Why each tier other than the exact one does not read the field.
UNREAD = {
    "surrogate": (
        "the surrogate tier ranks its pool by value times games: it has no single swap to ask "
        "the season guard about"
    ),
    "ranking": "the ranking tier searches no set, so it draws no guard's list",
    "static": policy.STATIC,
}


def test_the_reads_table_s_row_for_the_field():
    for mirror in (False, True):
        for executes in policy.EXECUTES:
            exact = rn.Arm("E", "exact", KNOBS, {}, executes)
            assert policy.field_reads(exact, mirror)["guard_pool"] == policy.READ
        # Not through a mirror either: a mirror rival is the surrogate.
        for tier, why in UNREAD.items():
            row = policy.field_reads(rn.Arm("X", tier, KNOBS, {}), mirror)
            assert list(row) == list(policy.FIELDS) and row["guard_pool"] == why
    assert policy.WHEN_READ["guard_pool"] == "the exact tier"


def test_the_record_s_reads_table_carries_the_row_only_for_an_arm_above_zero():
    """Rule 1 in the record: an arm that names nothing, or names 0, has the four rows it had."""
    one = policy.Shape()
    arms = {
        "a": armed("A"),
        "z": armed("Z", guard_pool=0),
        "b": armed("B", guard_pool=30),
        "s": armed("S", "surrogate", guard_pool=30),
    }
    table = ss.reads_of(arms, [one], rivals=True)
    assert list(table["a"][one.label()]["fields"]) == list(FOUR)
    assert table["a"] == table["z"]
    assert list(table["b"][one.label()]["fields"]) == list(policy.FIELDS)
    assert table["b"][one.label()]["fields"]["guard_pool"] == policy.READ
    assert table["s"][one.label()]["fields"]["guard_pool"] == UNREAD["surrogate"]
    assert {k: v for k, v in table["b"][one.label()]["fields"].items() if k in FOUR} == (
        table["a"][one.label()]["fields"]
    )


@pytest.mark.parametrize("opponents", ["static", "market", "mirror"])
def test_arms_that_differ_only_in_the_field_where_it_is_unread_are_the_same_seat(opponents):
    """On the surrogate and the ranking tier, a static seat, and through a mirror of an arm with
    the field on (the mirror is the surrogate): refused as for a knob. On the exact tier the two
    are two seats."""
    shapes = [policy.Shape(), policy.Shape("points", True, False, waivers="faab")]
    for tier, why in UNREAD.items():
        a = armed("A", tier, opponents)
        b = armed("B", tier, opponents, guard_pool=30)
        assert rn.same_seat(a, b, shapes) == [f"guard_pool ({why}; read by the exact tier)"]
        assert ss.same_seats({"a": a, "b": b}, shapes, rivals=True).startswith(
            "arms a and b are the same seat: they differ only in guard_pool ("
        )
    a, b = armed("A", "exact", opponents), armed("B", "exact", opponents, guard_pool=30)
    assert rn.same_seat(a, b, shapes) is None
    # Naming 0 is no difference at all: the same arm twice, which a run may play.
    assert rn.same_seat(a, armed("B", "exact", opponents, guard_pool=0), shapes) is None


# --------------------------------------------------------------------------- the searches' pool
def horizons_of(built: policy.Built) -> dict[str, dict[int, list[mv.SwapGain]]]:
    ev = mv.Evaluator(built.problem)
    return {key: mv.single_swaps(ev, key) for key in policy.HORIZONS}


def weighted_union(both, allowed, fields: policy.Fields):
    """The weighted search's pool in the live strategy run's form, from the door's functions:
    the head, then each horizon's guard's list taken in turn, joined."""
    gains = {key: {c: g[0].gain for c, g in both[key].items() if g} for key in policy.HORIZONS}
    listed = {
        key: {
            c: g.gain
            for c, g in engine.sp.admitted_swaps(
                both[key], allowed, fields.guard_pool, fields.min_gain
            )
        }
        for key in policy.HORIZONS
    }
    return engine.sp.joined(sg.pool_of(gains, fields.pool), sg.pool_of(listed, fields.guard_pool))


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("weight", [0.0, 0.5])
def test_the_three_weeks_set_is_searched_among_the_door_s_pool(h2h, weight, monkeypatch):
    """Parity through the door: with the field on, the pool ``moves.recommend`` is handed is
    ``engine.sp.pool_for`` on the single swaps the arm ranks (the season term on them at a
    ``season_weight``), the guard the search itself is handed and the arm's two sizes. Its
    first ``pool`` are today's (``_three_pool``), in that order."""
    built = built_of(of_format(make_setup(teams=4, pool=12), h2h), season_weight=weight)
    fields = policy.Fields(pool=3, guard_pool=4)
    asked, seen = door_calls(monkeypatch), searches(monkeypatch)
    decision = policy.exact(built, with_plan=False, fields=fields)
    assert [(name, key) for name, key, _, _ in seen] == [("recommend", policy.QUEUE_SET)]
    _, _, pool, allowed = seen[0]
    scored = policy.seasoned(built, mv.Evaluator(built.problem), policy.QUEUE_SET)
    swaps = mv.single_swaps(scored, policy.QUEUE_SET)
    want, _ = engine.sp.pool_for(swaps, allowed, 3, 4, fields.min_gain)
    assert pool == list(want.players)
    assert pool[: want.size] == policy._three_pool(swaps, fields) and want.size == 3
    assert want.admitted > 0, "the guard's list brought nothing: the test shows nothing"
    # One call of the rule, with the arm's sizes and the one guard the search is handed.
    assert [name for name, _ in asked] == ["pool_for"]
    assert asked[0][1][1] is allowed and asked[0][1][2:] == (3, 4, fields.min_gain)
    assert asked[0][1][0] == swaps
    assert decision.union is not None and decision.union.admitted == want.admitted


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("weight", [0.0, 0.5])
def test_the_weighted_search_is_handed_the_head_and_each_horizon_s_list_joined(
    h2h, weight, monkeypatch
):
    """The weighted search's pool with the field on: the head as at 0 (``_weighted_pool``),
    then each horizon's guard's list (``engine.sp.admitted_swaps``) taken in turn by
    ``strategy.pool_of``, joined by ``engine.sp.joined``. The form is the live strategy run's,
    put together here from the engine's functions (no test imports the API)."""
    built = built_of(of_format(make_setup(teams=4, pool=12), h2h), season_weight=weight)
    fields = policy.Fields(pool=3, guard_pool=4)
    asked, seen = door_calls(monkeypatch), searches(monkeypatch)
    decision = policy.exact(built, executes=policy.WEIGHTED, with_plan=False, fields=fields)
    assert [(name, key) for name, key, _, _ in seen] == [("search", sg.WEIGHTED)]
    _, _, pool, allowed = seen[0]
    both = horizons_of(built)
    want = weighted_union(both, allowed, fields)
    assert pool == list(want.players)
    head = policy._weighted_pool(mv.Evaluator(built.problem), fields)
    assert pool[: want.size] == head and want.size == 3
    assert want.admitted > 0, "the guard's lists brought nothing: the test shows nothing"
    assert [name for name, _ in asked] == ["admitted_swaps", "admitted_swaps", "joined"]
    for (_, args), key in zip(asked[:2], policy.HORIZONS, strict=True):
        assert args[0] == both[key] and args[1] is allowed and args[2:] == (4, fields.min_gain)
    assert decision.union is not None and decision.union.admitted == want.admitted


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
def test_the_week_plan_s_set_is_searched_among_the_same_candidates_on_and_off(
    h2h, executes, monkeypatch
):
    """``with_plan``'s week set is not part of the union: the first ``pool`` candidates in
    candidate order, whatever the field."""
    built = built_of(of_format(make_setup(teams=4, pool=12), h2h))
    seen = searches(monkeypatch)
    week = {}
    for size in (0, 4):
        seen.clear()
        policy.exact(built, executes=executes, fields=policy.Fields(pool=3, guard_pool=size))
        week[size] = [pool for name, key, pool, _ in seen if (name, key) == ("search", "week")]
    assert week[0] == week[4] == [[c for c, _ in built.problem.candidates][:3]]


# --------------------------------------------------------------------------- it bites
@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
def test_the_guard_refuses_the_whole_head_and_the_union_queues_the_add_it_admits(executes, h2h):
    """A made-up day: the head's two adds are refused by the season guard with every drop, and
    the one add the guard admits is not in the head. At 0 the search has nothing it may queue;
    with a list of one it queues that add."""
    built = built_of(refusing(h2h, now=True))
    guard = policy.guard_of(built)
    both = horizons_of(built)
    if executes == policy.WEIGHTED:
        head = policy._weighted_pool(mv.Evaluator(built.problem), TWO)
        assert head == [NOW, SOON]  # the week's best, then the three weeks'
    else:
        head = policy._three_pool(both[policy.QUEUE_SET], TWO)
        assert head == [SOON, SOONER]
    for key in policy.HORIZONS:
        assert not any(guard((mv.Move(c, g.drop),)) for c in head for g in both[key][c])
        assert all(guard((mv.Move(STEADY, g.drop),)) for g in both[key][STEADY])
    off = policy.exact(built, executes=executes, with_plan=False, fields=TWO)
    assert off.moves == () and off.union is None
    for size in (1, 30):
        fields = replace(TWO, guard_pool=size)
        on = policy.exact(built, executes=executes, with_plan=False, fields=fields)
        assert adds(on) == [STEADY]
        assert on.union == policy.PoolUnion(admitted=1, taken=1, refused=2)


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
def test_a_head_that_already_holds_the_admitted_add_takes_nothing_from_the_list(executes, h2h):
    """The same day with a head of four: the admitted add is in the head, so the list brings
    nothing new, the decision is the one at 0, and the union says so. The head's refused adds
    are counted all the same: the three weeks' two, and for the weighted search the week's
    best beside them."""
    built = built_of(refusing(h2h, now=True))
    four = policy.Fields(pool=4)
    off = policy.exact(built, executes=executes, with_plan=False, fields=four)
    on = policy.exact(
        built, executes=executes, with_plan=False, fields=replace(four, guard_pool=30)
    )
    assert adds(off) == adds(on) == [STEADY] and off.moves == on.moves
    refused = 3 if executes == policy.WEIGHTED else 2
    assert on.union == policy.PoolUnion(admitted=0, taken=0, refused=refused)


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
@pytest.mark.parametrize("full", [False, True], ids=["an open slot", "a full slot"])
def test_in_a_held_slot_league_a_move_with_no_drop_and_a_churn_reach_the_guard(
    full, executes, h2h, monkeypatch
):
    """Held slots: the guard's list is drawn from every drop an add can come with, so the
    guard is asked about an add with no drop (an open IL slot takes the player who is out) and
    about the drop of the held player (a full one), and the list holds an add with that move."""
    built, held = held_day(h2h, full)
    asked: list[mv.Move] = []
    lists: list[tuple[int, mv.SwapGain]] = []
    real = season_pool.admitted_swaps

    def spy(swaps, allowed, size, min_gain):
        def recording(moves):
            asked.extend(moves)
            return allowed(moves)

        out = real(swaps, recording, size, min_gain)
        lists.extend(out)
        return out

    monkeypatch.setattr(season_pool, "admitted_swaps", spy)
    fields = policy.Fields(pool=2, guard_pool=30)
    decision = policy.exact(built, executes=executes, with_plan=False, fields=fields)
    assert dict(built.problem.held_slots) == ({held: "IL"} if full else {})
    want = held if full else None
    assert want in {m.drop for m in asked}
    assert any(g.drop == want for _, g in lists)
    assert decision.union is not None and decision.union.admitted > 0


# --------------------------------------------------------------------------- off, and unread
@pytest.mark.parametrize("h2h", FORMATS)
def test_at_zero_the_rule_is_never_called_and_no_union_is_kept(h2h, monkeypatch):
    """Rule 1 where a seat decides: at 0 (unnamed, or named) the lines of today run as they
    are, and the pool rule is not called at all."""
    built = built_of(of_format(make_setup(teams=4, pool=12), h2h))
    on = {
        executes: policy.exact(built, executes=executes, fields=policy.Fields(guard_pool=30))
        for executes in policy.EXECUTES
    }
    no_door(monkeypatch)
    for executes in policy.EXECUTES:
        plain = policy.exact(built, executes=executes)
        named = policy.exact(built, executes=executes, fields=policy.fields_of({"guard_pool": 0}))
        assert plain == named and plain.union is None
        assert on[executes].union is not None


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_surrogate_the_ranking_tier_and_a_mirror_decide_the_same_with_the_field_on(
    h2h, monkeypatch
):
    """Unread: these tiers' decisions do not move with the field, and none of them calls the
    pool rule. A mirror of an arm with the field on is the surrogate with the arm's fields."""
    setup = of_format(make_setup(teams=4, pool=12), h2h)
    built = built_of(setup)
    no_door(monkeypatch)
    on = policy.Fields(guard_pool=30)
    for tier in ("surrogate", "ranking"):
        plain = policy.decide(built, tier)
        assert policy.decide(built, tier, fields=on) == plain
        assert plain.union is None and (plain.moves or tier == "ranking")
    state = initial(setup)
    decided = [
        op.of({"kind": "mirror"}, KNOBS, setup.market_rate, fields).decide(
            setup, state, 2, setup.projection, {}, {}, np.random.default_rng(1)
        )
        for fields in (policy.DEFAULT_FIELDS, on)
    ]
    assert decided[0] == decided[1] and decided[0].moves and decided[0].union is None


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
def test_the_season_scale_is_the_same_figure_with_the_field_on(executes, h2h, monkeypatch):
    """The season scale does not read the field: the same figure for the arm at 0 and above,
    on a day when the field changes what the seat queues, and with no call of the pool rule."""
    built = built_of(refusing(h2h, now=True))
    no_door(monkeypatch)
    off = policy.scale_of(built, "exact", executes, TWO)
    on = policy.scale_of(built, "exact", executes, replace(TWO, guard_pool=30))
    assert off is not None and off == on


# --------------------------------------------------------------------------- the counts
def test_the_counts_carry_the_union_s_keys_only_on_the_seats_a_run_counts():
    setup = make_setup()
    state = initial(setup)
    assert ct.SEASON == {"guard_pool": UNION_KEYS}
    assert not set(UNION_KEYS) & set(ct.Tally(setup).rows(state)[1])
    tally = ct.Tally(setup, {1: ("guard_pool",), 2: ("guard_pool",), 3: ()})
    days = (
        policy.Decision(union=policy.PoolUnion(admitted=3, taken=1, refused=2)),
        policy.Decision(union=policy.PoolUnion(admitted=0, taken=0, refused=1)),
        policy.Decision(union=policy.PoolUnion(admitted=2, taken=0, refused=0)),
        policy.NONE,  # a day with no union built (a day of an arm at 0)
    )
    before = ct.Tally(setup)
    for decision in days:
        for team in setup.teams:
            # Seat 2 is counted and builds none (its arm is at 0); seats 3 and 4 are not counted.
            tally.decided(team, policy.NONE if team == 2 else decision)
            before.decided(team, decision)
        tally.day(1, state)
        before.day(1, state)
    rows, plain = tally.rows(state), before.rows(state)
    assert {k: rows[1][k] for k in UNION_KEYS} == {
        "union_days": 3.0,
        "union_admitted": 5.0,
        "union_admitted_days": 2.0,
        "union_taken_days": 1.0,
        "union_head_refused_days": 2.0,
    }
    assert {k: rows[2][k] for k in UNION_KEYS} == dict.fromkeys(UNION_KEYS, 0.0)
    assert not set(UNION_KEYS) & (set(rows[3]) | set(rows[4]))
    assert ct.metrics_in([rows[1], rows[4]])[-5:] == UNION_KEYS
    assert ct.metrics_in([rows[4]]) == ct.metrics_in([plain[1]])
    # The counts a seat had are as they were: a tally that counts no field, on the same days.
    assert not set(UNION_KEYS) & set(plain[1])
    assert {k: v for k, v in rows[1].items() if k not in UNION_KEYS} == plain[1]
    assert rows[3] == plain[3] and rows[4] == plain[4]


def test_a_run_counts_the_union_when_an_arm_sets_the_field_on_its_arms_exact_seats():
    plain, zero, on = armed("P"), armed("Z", guard_pool=0), armed("B", guard_pool=30)
    surrogate = armed("S", "surrogate", guard_pool=30)
    assert rn.counted_of([plain, zero]) == ()
    assert rn.counted_of([plain, on]) == ("guard_pool",)
    assert rn._counted([plain, zero], {1: plain, 2: zero}) == {}
    # Both arms' seats on the tier that reads the field: the arm at 0 shows its zeros beside.
    assert rn._counted([plain, on, surrogate], {1: plain, 2: on, 3: surrogate}) == {
        1: ("guard_pool",),
        2: ("guard_pool",),
    }
    # A surrogate arm that names it is refused as the same seat where it matters; alone it
    # still names the field, and its own seat, which reads none, is not counted.
    assert rn.counted_of([surrogate]) == ("guard_pool",)
    assert rn._counted([surrogate], {1: surrogate}) == {}
    assert ss.counts_note("none") is ss.COUNTS_NOTE and ss.counts_note("none", ()) is ss.COUNTS_NOTE
    note = ss.counts_note("faab", ("guard_pool",))
    assert tuple(note)[-5:] == UNION_KEYS == tuple(ss.SEASON_NOTE["guard_pool"])
    assert {k: v for k, v in note.items() if k not in UNION_KEYS} == ss.counts_note("faab")


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("executes", policy.EXECUTES)
def test_a_season_with_the_field_on_differs_from_the_one_at_zero_and_the_counts_say_so(
    executes, h2h
):
    """The lever does something: in the league whose head the guard refuses, the arm at 0
    queues nothing on day one and the arm with the list queues the admitted add; their seasons
    part. The counts are the days' own (``Decision.union``), 0 for the arm at 0, and no
    rival's."""
    setup = refusing(h2h, now=True)
    off = armed("A", pool=2, executes=executes)
    on = armed("B", pool=2, executes=executes, guard_pool=30)
    seen: dict[int, list[rn.DayRecord]] = {0: [], 1: []}
    got = rn.paired(
        setup, replay_of(setup, 2, 0), off, on, 1, on_day=lambda r: seen[r.variant].append(r)
    )
    assert got["breaches"] == []
    first = [seen[v][0].decisions[1] for v in (0, 1)]
    assert first[0].moves == () and adds(first[1]) == [STEADY]
    assert first[0].union is None
    assert first[1].union == policy.PoolUnion(admitted=1, taken=1, refused=2)
    unions = [r.decisions[1].union for r in seen[1] if 1 in r.decisions]
    assert all(r.decisions[1].union is None for r in seen[0] if 1 in r.decisions)
    built = [u for u in unions if u is not None]
    assert {k: got["counts"]["b"][k] for k in UNION_KEYS} == {
        "union_days": float(len(built)),
        "union_admitted": float(sum(u.admitted for u in built)),
        "union_admitted_days": float(sum(1 for u in built if u.admitted)),
        "union_taken_days": float(sum(1 for u in built if u.taken)),
        "union_head_refused_days": float(sum(1 for u in built if u.refused)),
    }
    assert got["counts"]["b"]["union_days"] > 1 and got["counts"]["b"]["union_taken_days"] >= 1
    assert got["counts"]["b"]["union_head_refused_days"] >= 1
    assert {k: got["counts"]["a"][k] for k in UNION_KEYS} == dict.fromkeys(UNION_KEYS, 0.0)
    assert not set(UNION_KEYS) & set(got["counts"]["rivals"])
    # Another season: what the seat queued over it, and what landed.
    queued = [[r.queued.get(1, ()) for r in seen[v]] for v in (0, 1)]
    landed = [[r.landed.get(1, ()) for r in seen[v]] for v in (0, 1)]
    assert queued[0] != queued[1] and landed[0] != landed[1]
    # The season scale is each arm's own figure and does not read the field.
    assert got["scale"]["a"] == got["scale"]["b"]


@pytest.mark.parametrize("h2h", FORMATS)
def test_a_room_of_the_two_counts_both_arms_seats(h2h):
    """A room of the arm at 0 and the arm with the list (every seat an arm's, no rival): both
    arms' seats carry the counts, the arm at 0 its zeros."""
    setup = refusing(h2h, now=True)
    arms = {"A": armed("A", pool=2), "B": armed("B", pool=2, guard_pool=30)}
    room = rn.room(setup, replay_of(setup, 2, 0), arms, ["A", "B"], 1)
    assert room["seats"] == {"1": "B", "2": "A"} and room["breaches"] == []
    assert room["counts"]["B"]["union_days"] > 1 and room["counts"]["B"]["union_taken_days"] >= 1
    assert {k: room["counts"]["A"][k] for k in UNION_KEYS} == dict.fromkeys(UNION_KEYS, 0.0)


@pytest.mark.parametrize("h2h", FORMATS)
def test_rule_1_a_run_of_arms_at_zero_has_no_new_key_and_guard_pool_zero_named_is_unnamed(h2h):
    """Rule 1 in a season: two arms that leave the field off, one of them naming 0, play the
    same season with the same counts, and the run holds no key of the union's."""
    setup = of_format(make_setup(teams=4, pool=12), h2h)
    plain, named = armed("A", opponents="market"), armed("B", opponents="market", guard_pool=0)
    assert plain.fields == named.fields and repr(plain.seat().fields) == repr(named.seat().fields)
    got = rn.paired(setup, replay_of(setup, 2, 0), plain, named, 1)
    assert got["a"] == got["b"] and set(got["delta"].values()) == {0.0}
    assert got["counts"]["a"] == got["counts"]["b"] and got["counts"]["a"]["landed"] > 0
    assert not set(UNION_KEYS) & (set(got["counts"]["a"]) | set(got["counts"]["rivals"]))
