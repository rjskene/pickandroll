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

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pickandroll.season import pool as season_pool
from pickandroll.sim import cli as ss
from pickandroll.sim import engine, policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from tests.sim.sim_league import KNOBS

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
FORMATS = (ONE_WIN, EACH_CATEGORY)
#: The four fields an arm had before this one, in the payload's order.
FOUR = ("pool", "min_gain", "weeks_ahead", "surrogate_days")


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
