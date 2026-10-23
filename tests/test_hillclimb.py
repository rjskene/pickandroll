"""The Monday hill-climb step (#152): the rule table on made-up Progress payloads, the A/B halves,
the verdicts two Mondays on, the knob file written (the private league's values kept), the note,
and ``POST /autopilot/monday`` with the script on the Progress view's fixture. Every value is made
up; leagues are numbered, no names."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from pickandroll.season import hillclimb as hc
from pickandroll.season import progress as pg
from tests.test_progress import client  # noqa: F401 - the Progress view's fixture
from tests.test_scorecard import OTHER, PRIVATE, PUBLIC, run_script

MONDAYS = [date(2026, 10, 19) + timedelta(weeks=i) for i in range(8)]
WEEKS = [
    {"week": i + 1, "start": d.isoformat(), "end": (d + timedelta(days=6)).isoformat()}
    for i, d in enumerate(MONDAYS)
]
#: Four categories leagues and three points leagues armed; league 9 the private one.
ARMED = {
    "1": "categories",
    "2": "categories",
    "3": "categories",
    "4": "categories",
    "5": "points",
    "6": "points",
    "7": "points",
}
EVERY = [*ARMED, "9"]
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def row(week: int, expected: float | None, won: float | None, **kw) -> dict[str, Any]:
    return {
        "week": week,
        "expected": expected,
        "won": won,
        "expected_categories": kw.get("exp_cats"),
        "categories": kw.get("cats"),
        "scoring": kw.get("scoring", "categories"),
    }


def move(league: str, week: int, projected: float, realized: float, **kw) -> dict[str, Any]:
    """A scored move whose judging horizon is over (unless ``complete`` is false)."""
    judged = kw.get("judged", "week")
    return {
        "league": league,
        "week": week,
        "scoring": ARMED.get(league, "categories"),
        "group": kw.get("group", "scored"),
        "judged": judged,
        "projected": {
            "set": kw.get("set", "week"),
            "value": {"horizons": {judged: {"value": projected}}},
        },
        "realized": {
            "valued": True,
            "horizons": {
                judged: {"value": realized, "complete": kw.get("complete", True)},
                "season": {"value": kw.get("season")},
            },
        },
        "season_costly": kw.get("costly"),
        "knobs": {"system": kw.get("system", "bbm")},
    }


def payload(
    moves: list[dict[str, Any]] | None = None,
    rows: dict[str, list[dict[str, Any]]] | None = None,
    last: int = 2,
) -> dict[str, Any]:
    rows = rows or {}
    return {
        "weeks": WEEKS,
        "last_recorded": last,
        "leagues": [
            {"league": lg, "public": True, "scoring": s, "weeks": rows.get(lg, [])}
            for lg, s in ARMED.items()
        ]
        + [{"league": "9", "public": False, "scoring": "categories", "weeks": []}],
        "moves": moves or [],
        "sentences": [
            {"topic": "wins", "scope": "pooled", "tone": "good", "text": "Ahead of expectation."},
            {"topic": "moves", "scope": "pooled", "tone": "bad", "text": "The moves trail."},
            {"topic": "league", "scope": "1", "tone": "bad", "text": "League 1: behind."},
        ],
    }


def step(raw: Any, p: dict[str, Any], monday: date = MONDAYS[2], **kw) -> dict[str, Any]:
    return hc.step(p, raw, monday, NOW, ARMED, EVERY, **kw)


def costly_moves(spec: dict[str, tuple[int, int]]) -> list[dict[str, Any]]:
    """Per league: (season-costly moves, how many of them below zero over the season)."""
    out = []
    for lg, (n, below) in spec.items():
        for i in range(n):
            out.append(move(lg, 1, 1.0, 0.5, costly=True, season=-1.0 if i < below else 1.0))
    return out


# --------------------------------------------------------------------------- the rule table
def test_no_rule_clears_on_a_quiet_season_and_nothing_is_changed():
    out = step(None, payload([move("1", 1, 1.0, 0.9)]))
    assert out["change"] is None and out["verdicts"] == []
    assert [(r["rule"], r["scoring"], r["clears"]) for r in out["rules"]] == [
        ("season_check", "categories", False),
        ("season_check", "points", False),
        ("plan_floor", "categories", False),
        ("plan_floor", "points", False),
        ("system", None, False),
    ]
    assert out["knobs"] == {}
    assert "No change: no rule's numbers cleared its threshold." in out["note"]


def test_the_season_check_raises_its_scorings_floor_in_the_half_that_lagged():
    # Four flagged, three below zero: more than half. Leagues 1 and 3 hold all three.
    p = payload(costly_moves({"1": (2, 2), "3": (1, 1), "2": (1, 0)}))
    out = step(None, p)
    c = out["change"]
    assert (c["id"], c["knob"], c["scoring"], c["from"], c["to"]) == (
        "K1",
        "protection_floor",
        "categories",
        0.0,
        0.05,
    )
    assert (c["leagues"], c["b_leagues"]) == (["1", "3"], ["2", "4"])
    assert c["set"] == {"protection_floor": 0.05}
    assert c["was"] == {"protection_floor": {"1": 0.0, "3": 0.0}}
    assert c["source"] == "master" and c["verdict"] is None and c["monday"] == "2026-11-02"
    assert c["reason"].startswith(
        "The season check (categories): 3 of the 4 season-costly moves whose horizon is over "
        "realized below zero over the season so far (75%)"
    )
    # The floor in the two leagues that took it; in force in none, since they differ.
    assert out["knobs"]["leagues"] == {
        "1": {"protection_floor": 0.05},
        "3": {"protection_floor": 0.05},
    }
    assert "protection_floor" not in out["knobs"]["in_force"]
    assert out["knobs"]["changes"] == [c]
    knobs, problems = pg.knob_file(out["knobs"])
    assert problems == [] and knobs["changes"][0]["scoring"] == "categories"


def test_a_moves_sample_counts_only_scored_moves_whose_horizon_is_over():
    moves = costly_moves({"1": (2, 2), "3": (1, 1)})
    moves += [
        move("2", 1, 1.0, 0.5, costly=True, season=-1.0, complete=False),
        move("2", 1, 1.0, 0.5, costly=True, season=-1.0, group="realized_only"),
    ]
    out = step(None, payload(moves))
    assert out["rules"][0]["numbers"] == {"season_costly": 3, "below_zero": 3}
    assert out["change"]["knob"] == "protection_floor"


def test_a_points_floor_steps_half_a_point_a_game():
    out = step(None, payload(costly_moves({"5": (2, 2), "6": (1, 1)})))
    c = out["change"]
    assert (c["scoring"], c["from"], c["to"]) == ("points", 0.0, 0.5)
    # Halves by id, alternately: 5 and 7 against 6; the first lagged more.
    assert (c["leagues"], c["b_leagues"]) == (["5", "7"], ["6"])


def test_the_season_check_comes_before_the_plans_and_the_plans_before_the_system():
    plans = [move("1", 1, 1.0, 0.2, set="plan") for _ in range(5)]
    system = [move("2", 1, 1.0, 0.1) for _ in range(20)]
    floor = costly_moves({"1": (3, 2)})
    out = step(None, payload([*floor, *plans, *system]))
    assert [r["clears"] for r in out["rules"]] == [True, False, True, False, True]
    assert out["change"]["rule"] == "season_check"
    out = step(None, payload([*plans, *system]))
    assert out["change"]["rule"] == "plan_floor"


def test_the_plan_floor_rises_by_half_its_value_never_above_four_times_its_default():
    plans = [move("1", 1, 1.0, 0.4, set="plan") for _ in range(5)]
    out = step(None, payload(plans))
    c = out["change"]
    assert (c["knob"], c["from"], c["to"]) == ("plan_floor_cats", 0.1, 0.15)
    assert out["rules"][2]["numbers"] == {"plan_moves": 5, "share": 0.4}
    # Near the cap it stops at it; at the cap the rule is blocked and the next one has its say.
    near = step({"in_force": {"plan_floor_cats": 0.3}}, payload(plans))["change"]
    assert (near["from"], near["to"]) == (0.3, 0.4)
    capped = step({"in_force": {"plan_floor_cats": 0.4}}, payload(plans))
    assert capped["change"] is None and capped["rules"][2]["blocked"] == "the floor is at its cap"
    assert "the streaming plans (categories) cleared but the floor is at its cap" in capped["note"]
    # Four plan moves are too few.
    assert step(None, payload(plans[:4]))["change"] is None


def test_the_system_steps_to_the_blend_at_half_never_straight_to_yahoo():
    moves = [move(lg, 1, 1.0, 0.3) for lg in ARMED for _ in range(3)]
    out = step({"in_force": {"system": "bbm"}}, payload(moves))
    c = out["change"]
    assert (c["knob"], c["from"], c["to"]) == ("system", "bbm", "blend")
    assert c["set"] == {"system": "blend", "blend": 0.5}
    assert len(c["leagues"]) + len(c["b_leagues"]) == len(ARMED)
    knobs, _ = pg.knob_file(out["knobs"])
    for lg in c["leagues"]:
        assert pg.in_force_for(knobs, lg)["system"] == "blend"
        assert pg.in_force_for(knobs, lg)["blend"] == 0.5
    for lg in [*c["b_leagues"], "9"]:
        assert pg.in_force_for(knobs, lg)["system"] == "bbm"
    # Nineteen moves are too few, and moves under another system do not count.
    assert step(None, payload(moves[:19]))["change"] is None
    other = [move(lg, 1, 1.0, 0.3, system="yahoo") for lg in ARMED for _ in range(3)]
    assert step(None, payload(other))["rules"][4]["numbers"]["moves"] == 0


def test_a_kept_blend_steps_a_quarter_toward_yahoo_within_its_bounds():
    moves = [move(lg, 1, 1.0, 0.3, system="blend") for lg in ARMED for _ in range(3)]
    out = step({"in_force": {"system": "blend"}}, payload(moves))
    c = out["change"]
    assert (c["knob"], c["from"], c["to"]) == ("blend", 0.5, 0.75)
    # At the bound the step is refused; a blend still waiting for its verdict blocks it.
    top = step({"in_force": {"system": "blend", "blend": 0.75}}, payload(moves))
    assert top["change"] is None and "above its maximum 0.75" in top["rules"][4]["blocked"]
    pending = {
        "in_force": {"system": "blend"},
        "changes": [
            {
                "id": "K1",
                "monday": "2026-09-28",
                "knob": "system",
                "from": "bbm",
                "to": "blend",
                "leagues": ["1"],
                "source": "master",
            }
        ],
    }
    assert step(pending, payload(moves))["rules"][4]["blocked"] == (
        "the blend in force has not been kept yet"
    )
    # The step moves the weight most leagues share; a league on another weight keeps it.
    mixed = step(
        {"in_force": {"system": "blend"}, "leagues": {"1": {"blend": 0.75}}}, payload(moves)
    )
    c = mixed["change"]
    assert (c["from"], c["to"]) == (0.5, 0.75)
    assert "1" not in [*c["leagues"], *c["b_leagues"]]


def test_a_knob_changed_in_the_last_four_weeks_or_frozen_is_not_changed_again():
    floor = costly_moves({"1": (2, 2), "3": (1, 1)})
    recent = {
        "changes": [
            {
                "id": "K1",
                "monday": "2026-10-12",
                "knob": "protection_floor",
                "from": 0.0,
                "to": 0.05,
                "leagues": ["2"],
                "source": "master",
                "verdict": "reverted",
            }
        ]
    }
    out = step(recent, payload(floor))
    assert out["change"] is None
    assert out["rules"][0]["blocked"] == "K1 changed protection_floor on 2026-10-12"
    # Four weeks on, it may change again.
    assert step(recent, payload(floor), MONDAYS[3])["change"]["id"] == "K2"
    # A revert writes the knob again: the four weeks run from it.
    undone = {
        "changes": [{**recent["changes"][0], "monday": "2026-09-28", "judged_on": "2026-10-12"}]
    }
    assert step(undone, payload(floor))["rules"][0]["blocked"] == (
        "K1 (protection_floor) was reverted on 2026-10-12"
    )
    assert step(undone, payload(floor), MONDAYS[3])["change"]["id"] == "K2"
    # Frozen in three of the four leagues: one left to split.
    frozen = {"frozen": {lg: ["protection_floor"] for lg in ("1", "2", "3")}}
    out = step(frozen, payload(floor))
    assert out["change"] is None
    assert out["rules"][0]["blocked"] == "1 league to split, fewer than 2"
    # A blocked rule passes to the next, and the note names it.
    both = floor + costly_moves({"5": (2, 2), "6": (1, 1)})
    out = step(frozen, payload(both))
    assert (out["change"]["rule"], out["change"]["scoring"]) == ("season_check", "points")
    assert (
        "Passed over before it: the season check (categories) cleared but 1 league to split, "
        "fewer than 2."
    ) in out["note"]


def test_the_step_never_changes_a_knob_without_a_hook():
    knobs, _ = pg.knob_file(None)
    for knob in ("stash_threshold", "faab_sizing"):
        assert knob not in pg.HOOKED
        assert hc.refused_change(knobs, knob, 0.2, "2026-11-02", ["1", "2"]) == (
            f"{knob} has no hook, so the step never changes it"
        )
    # Every knob a rule can change is hooked; a bound is refused like a minimum.
    assert {"protection_floor", "plan_floor_cats", "plan_floor_points", "system", "blend"} <= (
        pg.HOOKED
    )
    assert hc.refused_change(knobs, "protection_floor", -0.05, "2026-11-02", ["1", "2"]) == (
        "protection_floor -0.05 is below its minimum 0.0"
    )
    assert hc.refused_change(knobs, "protection_floor", 0.05, "2026-11-02", ["1", "2"]) is None


# --------------------------------------------------------------------------- the verdicts
def judged_file(**over) -> dict[str, Any]:
    """K1 on the Monday of week 2: the categories floor in leagues 1 and 3."""
    return {
        "leagues": {"1": {"protection_floor": 0.05}, "3": {"protection_floor": 0.05}},
        "changes": [
            {
                "id": "K1",
                "monday": "2026-10-26",
                "knob": "protection_floor",
                "from": 0.0,
                "to": 0.05,
                "leagues": ["1", "3"],
                "source": "master",
                "verdict": None,
                "scoring": "categories",
                "set": {"protection_floor": 0.05},
                "was": {"protection_floor": {"1": 0.0, "3": 0.0}},
                **over,
            }
        ],
    }


def two_weeks(a: float, b: float, **kw) -> dict[str, list[dict[str, Any]]]:
    """Weeks 2 and 3 of the categories leagues: A (1, 3) and B (2, 4) each week ``a`` and ``b``
    wins above an expected 0.5, ``kw`` their categories above 4."""
    out = {}
    for lg in ("1", "2", "3", "4"):
        up = a if lg in ("1", "3") else b
        cats = kw.get("a_cats" if lg in ("1", "3") else "b_cats", 0.0)
        out[lg] = [row(w, 0.5, 0.5 + up, exp_cats=4.0, cats=4.0 + cats) for w in (2, 3)]
    return out


def test_a_change_is_judged_two_mondays_on_and_a_kept_one_rolls_out_to_its_scoring():
    out = step(judged_file(), payload(rows=two_weeks(0.5, -0.5), last=3), MONDAYS[3])
    (v,) = out["verdicts"]
    assert (v["id"], v["verdict"], v["decided_by"]) == ("K1", "kept", "wins_above")
    assert (v["leagues"], v["b_leagues"], v["window"]) == (["1", "3"], ["2", "4"], [2, 3])
    assert (v["a"]["wins_above"], v["b"]["wins_above"]) == (1.0, -1.0)
    k1 = out["knobs"]["changes"][0]
    assert (k1["verdict"], k1["judged_on"], k1["rolled_out"]) == (
        "kept",
        "2026-11-09",
        "2026-11-09",
    )
    assert k1["judged"]["decided_by"] == "wins_above" and k1["judged"]["reached"] == [
        "1",
        "2",
        "3",
        "4",
    ]
    # Every categories league on the floor; the points and the private league keep theirs.
    knobs, _ = pg.knob_file(out["knobs"])
    assert [pg.in_force_for(knobs, lg)["protection_floor"] for lg in EVERY] == [
        0.05,
        0.05,
        0.05,
        0.05,
        0.0,
        0.0,
        0.0,
        0.0,
    ]
    assert "K1 (protection_floor) is kept: on wins above expected a league" in out["note"]


def test_a_kept_system_change_rolls_out_its_weight_against_the_half_it_recorded():
    # K1 put leagues 1 and 3 on the blend at half, the file's weight elsewhere 0.75; it
    # recorded leagues 2 and 4 as its B half, so the points leagues are not compared.
    raw = {
        "in_force": {"blend": 0.75},
        "leagues": {"1": {"system": "blend", "blend": 0.5}, "3": {"system": "blend", "blend": 0.5}},
        "changes": [
            {
                "id": "K1",
                "monday": "2026-10-26",
                "knob": "system",
                "from": "bbm",
                "to": "blend",
                "leagues": ["1", "3"],
                "b_leagues": ["2", "4"],
                "source": "master",
                "verdict": None,
                "set": {"system": "blend", "blend": 0.5},
                "was": {"system": {"1": "bbm", "3": "bbm"}, "blend": {"1": 0.75, "3": 0.75}},
            }
        ],
    }
    out = step(raw, payload(rows=two_weeks(0.5, -0.5), last=3), MONDAYS[3])
    (v,) = out["verdicts"]
    assert (v["verdict"], v["leagues"], v["b_leagues"]) == ("kept", ["1", "3"], ["2", "4"])
    knobs, _ = pg.knob_file(out["knobs"])
    assert {lg: pg.in_force_for(knobs, lg)["system"] for lg in EVERY} == {
        **dict.fromkeys(ARMED, "blend"),
        "9": "bbm",
    }
    assert {lg: pg.in_force_for(knobs, lg)["blend"] for lg in EVERY} == {
        **dict.fromkeys(ARMED, 0.5),
        "9": 0.75,
    }
    # The Progress view's A/B draws the same B half.
    rows = {
        lg: [{**r, "brier": None, "moves": {"made": 0}} for r in rs]
        for lg, rs in two_weeks(0.5, -0.5).items()
    }
    half = pg.ab(knobs["changes"][0], 2, rows, 3)
    assert (half["a"]["leagues"], half["b"]["leagues"]) == (["1", "3"], ["2", "4"])


def test_force_on_a_monday_that_judged_keeps_its_verdict_and_judges_nothing_twice():
    p = payload(rows=two_weeks(0.5, -0.5), last=3)
    first = step(judged_file(), p, MONDAYS[3])
    again = step(first["knobs"], p, MONDAYS[3], force=True)
    assert [(v["id"], v["verdict"], v["decided_by"]) for v in again["verdicts"]] == [
        ("K1", "kept", "wins_above")
    ]
    assert again["knobs"] == first["knobs"]
    assert again["note"] == first["note"]


def test_a_change_that_did_worse_is_reverted_to_its_old_values():
    out = step(judged_file(), payload(rows=two_weeks(-0.5, 0.5), last=3), MONDAYS[3])
    (v,) = out["verdicts"]
    assert (v["verdict"], v["decided_by"]) == ("reverted", "wins_above")
    k1 = out["knobs"]["changes"][0]
    assert (k1["verdict"], k1["rolled_out"]) == ("reverted", None)
    knobs, _ = pg.knob_file(out["knobs"])
    assert all(pg.in_force_for(knobs, lg)["protection_floor"] == 0.0 for lg in EVERY)
    assert "1" not in out["knobs"]["leagues"] and "3" not in out["knobs"]["leagues"]


def test_the_first_measure_that_tells_the_halves_apart_decides():
    # The wins differ by less than half a win a league; the categories by two a league.
    rows = two_weeks(0.1, 0.0, a_cats=-1.0, b_cats=0.0)
    (v,) = step(judged_file(), payload(rows=rows, last=3), MONDAYS[3])["verdicts"]
    assert (v["verdict"], v["decided_by"]) == ("reverted", "categories_above")
    # Nothing tells them apart: kept, A having done no worse.
    (v,) = step(judged_file(), payload(rows=two_weeks(0.0, 0.0), last=3), MONDAYS[3])["verdicts"]
    assert (v["verdict"], v["decided_by"]) == ("kept", None)


def test_the_year_to_date_is_read_as_the_change_in_the_gap_and_never_decides():
    # A lagged by three wins a league before the change, then ran a win ahead of B a league
    # over the window: the raw year to date has A behind, the gap moved two wins its way.
    rows = two_weeks(0.5, -0.5)
    for lg in ("1", "2", "3", "4"):
        rows[lg].insert(0, row(1, 0.5, 0.5 - (3.0 if lg in ("1", "3") else 0.0)))
    out = step(judged_file(), payload(rows=rows, last=3), MONDAYS[3])
    (v,) = out["verdicts"]
    assert (v["verdict"], v["decided_by"]) == ("kept", "wins_above")
    assert (v["a_ytd"]["wins_above"], v["b_ytd"]["wins_above"]) == (-2.0, -1.0)
    assert v["since"]["wins_above"] == 2.0
    assert out["knobs"]["changes"][0]["judged"]["since"]["wins_above"] == 2.0
    assert (
        "Year to date, the gap on wins above expected a league moved +2 since its Monday "
        "(-2 against -1)."
    ) in out["note"]
    # With nothing before the change, the year to date is the window.
    (v,) = step(judged_file(), payload(rows=two_weeks(0.5, -0.5), last=3), MONDAYS[3])["verdicts"]
    assert v["since"]["wins_above"] == 2.0


def test_a_change_waits_for_its_two_weeks_and_a_users_change_is_never_judged():
    rows = two_weeks(0.5, -0.5)
    assert step(judged_file(), payload(rows=rows, last=2), MONDAYS[3])["verdicts"] == []
    users = judged_file(source="user")
    assert step(users, payload(rows=rows, last=3), MONDAYS[3])["verdicts"] == []


# --------------------------------------------------------------------------- the writes
def test_the_private_league_keeps_its_values_when_a_shared_value_splits():
    floor = costly_moves({"1": (2, 2), "3": (1, 1)})
    out = step({"in_force": {"protection_floor": 0.1}}, payload(floor))
    knobs, _ = pg.knob_file(out["knobs"])
    assert out["change"]["from"] == 0.1 and out["change"]["to"] == 0.15
    assert "protection_floor" not in out["knobs"]["in_force"]
    assert {lg: pg.in_force_for(knobs, lg)["protection_floor"] for lg in EVERY} == {
        "1": 0.15,
        "2": 0.1,
        "3": 0.15,
        "4": 0.1,
        "5": 0.1,
        "6": 0.1,
        "7": 0.1,
        "9": 0.1,
    }


def test_force_undoes_the_mondays_own_change_but_never_a_judged_one():
    floor = costly_moves({"1": (2, 2), "3": (1, 1)})
    first = step(None, payload(floor))
    assert first["change"]["id"] == "K1"
    # Run again on the same Monday with force, the moves now quiet: K1 undone and gone.
    again = step(first["knobs"], payload([]), force=True)
    assert again["change"] is None and again["knobs"]["changes"] == []
    knobs, _ = pg.knob_file(again["knobs"])
    assert all(pg.in_force_for(knobs, lg)["protection_floor"] == 0.0 for lg in EVERY)
    judged = {**first["knobs"], "changes": [{**first["change"], "verdict": "kept"}]}
    with pytest.raises(ValueError, match="K1 of 2026-11-02 is already judged"):
        step(judged, payload([]), force=True)
    assert hc.ran(first["knobs"], "2026-11-02") == ["K1"] and hc.ran(None, "2026-11-02") == []


def test_a_knob_file_of_the_wrong_shape_is_not_written():
    assert hc.writable(None) == [] and hc.writable({"in_force": {}}) == []
    assert hc.writable([1]) == ["the knob file is not an object"]
    assert hc.writable({"leagues": {"1": "x"}, "changes": {}}) == [
        "changes is not a list",
        "league 1 is not an object",
    ]


def test_the_note_has_the_four_sections_and_names_no_league():
    out = step(None, payload(costly_moves({"1": (2, 2), "3": (1, 1)})))
    note, problems = pg.note(out["note"], "2026-11-02")
    assert problems == []
    assert note["working"] == "Ahead of expectation."
    assert note["not_working"] == "The moves trail."
    assert note["decision"].startswith("K1: The season check (categories)")
    assert note["actions"] == [
        "Judge K1 (protection_floor) two Mondays on, once its two weeks are recorded."
    ]
    assert "League 1" not in out["note"]


# --------------------------------------------------------------------------- the route
def test_the_monday_route_writes_the_note_once_and_says_so_after(client):  # noqa: F811
    url = "/autopilot/monday"
    knobs_path = client.data_dir / "autopilot" / "knobs.json"
    before = knobs_path.read_text()
    note = client.data_dir / "autopilot" / "notes" / "2026-11-02.md"
    dry = client.post(url, params={"dry_run": True})
    assert dry.status_code == 200, dry.text
    assert (dry.json()["status"], dry.json()["written"]) == ("dry_run", [])
    assert not note.exists()
    out = client.post(url).json()
    assert (out["monday"], out["status"]) == ("2026-11-02", "written")
    # K1 (week 2) is not due: week 3 is not recorded. Nothing changes, so only the note is new.
    assert out["verdicts"] == [] and out["change"] is None
    assert out["written"] == ["autopilot/notes/2026-11-02.md"]
    assert knobs_path.read_text() == before and note.read_text() == out["note"]
    again = client.post(url).json()
    assert (again["status"], again["written"], again["note"]) == ("already", [], out["note"])
    forced = client.post(url, params={"force": True}).json()
    assert forced["status"] == "written"
    assert client.post(url, params={"monday": "2026-11-03"}).status_code == 422


def test_the_route_blocks_the_system_on_a_recent_blend_change_and_writes_a_new_one(
    client,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(hc, "SYSTEM_MOVES", 1)
    monkeypatch.setattr(hc, "SYSTEM_SHARE", 100.0)
    out = client.post("/autopilot/monday", params={"dry_run": True}).json()
    assert out["rules"][-1]["blocked"] == "K1 changed blend on 2026-10-26"
    assert "the projection system cleared but K1 changed blend on 2026-10-26" in out["note"]
    # Without K1 the system steps to the blend in one of the two public leagues.
    path = client.data_dir / "autopilot" / "knobs.json"
    path.write_text(json.dumps({"in_force": {"system": "bbm", "blend": 0.5}}))
    out = client.post("/autopilot/monday").json()
    c = out["change"]
    assert (c["id"], c["knob"], c["to"]) == ("K1", "system", "blend")
    assert sorted([*c["leagues"], *c["b_leagues"]]) == sorted([PUBLIC, OTHER])
    written = json.loads(path.read_text())
    assert written["in_force"] == {"blend": 0.5}
    assert written["leagues"] == {c["leagues"][0]: {"system": "blend"}}
    assert out["written"] == ["autopilot/knobs.json", "autopilot/notes/2026-11-02.md"]
    # The solves of the league that took it now run on the blend; the private league's do not.
    from pickandroll.api import season_knobs

    assert season_knobs.for_league(client.data_dir, c["leagues"][0])["system"] == "blend"
    assert season_knobs.for_league(client.data_dir, PRIVATE)["system"] == "bbm"


def test_a_knob_file_that_is_not_json_is_refused_not_overwritten(client):  # noqa: F811
    path = client.data_dir / "autopilot" / "knobs.json"
    path.write_text("{not json")
    r = client.post("/autopilot/monday")
    assert r.status_code == 409 and "not JSON" in r.json()["detail"]
    assert path.read_text() == "{not json"


def test_the_scorecard_projects_each_week_on_the_system_its_entry_had_in_force(client):  # noqa: F811
    url = f"/seasons/{PUBLIC}/scorecard"
    before = client.get(url).json()
    assert before["system"] is None
    shown = [w["projected"] for w in before["weeks"]]
    assert any(shown)
    # The file now puts the league on Yahoo's: the weeks its entries projected on Basketball
    # Monster's, in force when they were logged, keep their projections.
    path = client.data_dir / "autopilot" / "knobs.json"
    path.write_text(json.dumps({"leagues": {PUBLIC: {"system": "yahoo"}}}))
    assert [w["projected"] for w in client.get(url).json()["weeks"]] == shown
    # A named system still wins: no entry was solved on Yahoo's.
    named = client.get(url, params={"system": "yahoo"}).json()
    assert named["system"] == "yahoo" and not any(w["projected"] for w in named["weeks"])


def test_the_script_prints_the_steps_line_and_its_note(client):  # noqa: F811
    def call(method: str, path: str):
        r = client.request(method, path)
        return r.status_code, r.json()

    out = run_script("monday", "--dry-run", call=call)
    assert out.startswith("2026-11-02: dry run, nothing written; no change\n## What is working")
    out = run_script("monday", call=call).splitlines()
    assert out[0] == "2026-11-02: written autopilot/notes/2026-11-02.md; no change"
    # Once a Monday: the second run says so and shows the note the first one wrote.
    out = run_script("monday", call=call).splitlines()
    assert out[:2] == ["2026-11-02: already run (no change); nothing written", "## What is working"]
