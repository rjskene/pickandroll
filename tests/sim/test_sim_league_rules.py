"""The league rules (#172, PR D4c): how a run's league scores and what it holds."""

from __future__ import annotations

import pytest

from pickandroll.sim import shapes
from pickandroll.sim.engine import HELD, STATS


def test_the_default_rules_are_today_s_league():
    plain = shapes.PLAIN
    assert plain == shapes.LeagueRules()
    assert (plain.scoring, plain.points, plain.held, plain.table) == ("categories", None, (), None)
    assert plain.slots(shapes.SLOTS) == shapes.SLOTS
    assert plain.payload() == {"scoring": "categories", "points": None, "held": []}
    assert plain.label() == "the nine categories, no held slot"


def test_the_default_points_table_scores_every_stat_of_a_line_once():
    """ESPN's published default for head-to-head points leagues, in the engine's order."""
    assert [s for s, _ in shapes.POINTS_DEFAULT] == list(STATS)
    assert dict(shapes.POINTS_DEFAULT) == {
        "pts": 1,
        "threes": 1,
        "fgm": 2,
        "fga": -1,
        "ftm": 1,
        "fta": -1,
        "reb": 1,
        "ast": 2,
        "stl": 4,
        "blk": 4,
        "tov": -2,
    }


def test_the_held_slots_are_two_of_the_engine_s_and_not_na():
    assert set(shapes.HELD_MOST) < HELD and "NA" not in shapes.HELD_MOST
    assert dict(shapes.HELD_MOST) == {"IL": 2, "IL+": 1}


def test_held_slots_are_parsed_in_the_roster_s_order():
    assert shapes.parse_held("IL+=1,IL=2") == ("IL", "IL", "IL+")
    assert shapes.parse_held("il=1") == ("IL",)
    assert shapes.parse_held("IL=0,IL+=1") == ("IL+",)
    assert shapes.parse_held("IL=0") == ()


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("NA=1", "the plan names these two"),
        ("BN=1", "the held slots a league may hold here are IL, IL+"),
        ("IL=3", "IL is 0 to 2"),
        ("IL+=2", "IL+ is 0 to 1"),
        ("IL=-1", "IL is 0 to 2"),
        ("IL=x", "a count is a whole number"),
        ("IL=1.5", "a count is a whole number"),
        ("", "names nothing"),
        ("IL=1,IL=2", "IL is named twice"),
        ("IL", "is not KEY=VALUE"),
    ],
)
def test_a_held_slot_the_plan_does_not_name_is_refused_in_words(text, says):
    with pytest.raises(ValueError) as e:
        shapes.parse_held(text)
    assert says in str(e.value)


def test_a_points_table_is_what_it_names_in_the_engine_s_order():
    assert shapes.parse_points("reb=1.2,pts=1") == (("pts", 1.0), ("reb", 1.2))
    table = shapes.parse_points(",".join(f"{s}={w:g}" for s, w in shapes.POINTS_DEFAULT))
    assert table == shapes.POINTS_DEFAULT


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("fpts=1", "the stats of a line are pts, threes"),
        ("fg_pct=1", "the stats of a line are"),
        ("pts=x", "points per unit are a number"),
        ("pts=inf", "a finite number"),
        ("pts=nan", "a finite number"),
        ("", "names nothing"),
        ("pts=1,pts=2", "pts is named twice"),
        ("pts", "is not KEY=VALUE"),
        ("pts=0,reb=0", "every weight is zero, so every week would tie"),
    ],
)
def test_a_points_table_with_a_key_or_a_value_it_cannot_read_is_refused_in_words(text, says):
    with pytest.raises(ValueError) as e:
        shapes.parse_points(text)
    assert says in str(e.value)


@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
        ({"scoring": "roto"}, "is not one of categories, points"),
        (
            {"scoring": "categories", "points": shapes.POINTS_DEFAULT},
            "a categories league has none",
        ),
        ({"scoring": "points"}, "a points league scores on a table"),
        ({"scoring": "points", "points": ()}, "each stat once"),
        ({"scoring": "points", "points": (("reb", 1.0), ("pts", 1.0))}, "in STATS order"),
        ({"scoring": "points", "points": (("fpts", 1.0),)}, "fpts is no stat of a line"),
        ({"scoring": "points", "points": (("pts", 0.0),)}, "a points table that scores nothing"),
        ({"held": ("IL+", "IL")}, "IL first, then IL+"),
        ({"held": ("IL", "IL", "IL")}, "at most 2 IL"),
        ({"held": ("NA",)}, "is not one of IL, IL+"),
    ],
)
def test_league_rules_out_of_the_plan_are_refused_in_words(kwargs, says):
    with pytest.raises(ValueError) as e:
        shapes.LeagueRules(**kwargs)
    assert says in str(e.value)


def test_the_rules_label_and_payload_say_the_scoring_the_table_and_the_held_slots():
    full = shapes.LeagueRules("points", shapes.POINTS_DEFAULT, ("IL", "IL", "IL+"))
    assert full.label() == "points on ESPN's default table, two IL slots and one IL+ slot"
    assert full.payload() == {
        "scoring": "points",
        "points": dict(shapes.POINTS_DEFAULT),
        "held": ["IL", "IL", "IL+"],
    }
    own = shapes.LeagueRules("points", shapes.parse_points("pts=1,reb=1.2"), ("IL",))
    assert own.label() == "points on the table pts 1, reb 1.2, one IL slot"
    assert own.table == {"pts": 1.0, "reb": 1.2}
    held = shapes.LeagueRules(held=("IL+",))
    assert held.label() == "the nine categories, one IL+ slot"
    # The held slots follow the roster, after its bench: the draft fills the active spots only.
    assert held.slots(shapes.SLOTS) == (*shapes.SLOTS, "IL+")
    # Hashable: one set of rules for a whole run, a key like a league shape.
    assert len({full, own, held, shapes.PLAIN, shapes.LeagueRules()}) == 4


# --------------------------------------------------------------------------- the waivers (PR Fa)
def test_the_default_rules_have_no_waivers_and_record_as_before():
    plain = shapes.PLAIN
    assert (plain.waivers, plain.waiver_days, plain.waiting) == ("none", 2, False)
    # A league without waivers records the three keys of PR D4c and labels as it did.
    assert set(plain.payload()) == {"scoring", "points", "held"}
    assert shapes.LeagueRules(held=("IL",)) == shapes.LeagueRules(
        "categories", None, ("IL",), "none", 2
    )


def test_a_waiver_league_says_its_wait_in_the_label_and_the_payload():
    priority = shapes.LeagueRules(waivers="priority")
    assert priority.waiting and priority.waiver_days == shapes.WAIVER_DAYS == 2
    assert priority.label() == "the nine categories, no held slot, waivers by priority after 2 days"
    assert priority.payload() == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "waivers": "priority",
        "waiver_days": 2,
    }
    one = shapes.LeagueRules("points", shapes.POINTS_DEFAULT, ("IL",), "priority", 1)
    assert one.label() == (
        "points on ESPN's default table, one IL slot, waivers by priority after 1 day"
    )
    assert one.payload()["waiver_days"] == 1
    # Hashable and told apart by the wait.
    assert len({priority, one, shapes.LeagueRules(waivers="priority", waiver_days=3)}) == 3


def test_the_waivers_flags_parse_to_the_kind_and_the_wait():
    assert shapes.parse_waivers("none") == ("none", 2)
    assert shapes.parse_waivers("priority") == ("priority", 2)
    assert shapes.parse_waivers("Priority", "3") == ("priority", 3)
    assert shapes.parse_waivers("priority", "7") == ("priority", 7)
    assert shapes.parse_waivers("priority", "1") == ("priority", 1)


@pytest.mark.parametrize(
    ("waivers", "days", "says"),
    [
        ("faab", None, "--waivers faab: a budget and sealed bids are PR Fb's"),
        ("bids", None, "--waivers bids: one of none, priority"),
        ("priority", "0", "--waiver-days 0: a dropped player waits 1 to 7 days"),
        ("priority", "8", "--waiver-days 8: a dropped player waits 1 to 7 days"),
        ("priority", "two", "--waiver-days two: a whole number of days"),
        ("none", "2", "--waiver-days 2: a dropped player's wait is a waiver league's"),
        ("none", "3", "it is read only with --waivers priority"),
    ],
)
def test_a_waiver_flag_out_of_the_plan_is_refused_in_words(waivers, days, says):
    with pytest.raises(ValueError) as e:
        shapes.parse_waivers(waivers, days)
    assert says in str(e.value)


@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
        ({"waivers": "faab"}, "waivers faab: a budget and sealed bids are PR Fb's"),
        ({"waivers": "rolling"}, "waivers 'rolling' is not one of none, priority"),
        ({"waivers": "priority", "waiver_days": 0}, "a dropped player waits 1 to 7 days"),
        ({"waivers": "priority", "waiver_days": 8}, "a dropped player waits 1 to 7 days"),
        ({"waivers": "priority", "waiver_days": 2.0}, "a whole number of days"),
        ({"waivers": "priority", "waiver_days": True}, "a whole number of days"),
        ({"waiver_days": 3}, "waiver days 3 with waivers none: a wait is a waiver league's"),
    ],
)
def test_waiver_rules_out_of_the_plan_are_refused_in_words(kwargs, says):
    with pytest.raises(ValueError) as e:
        shapes.LeagueRules(**kwargs)
    assert says in str(e.value)
