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
    # The format PR: a categories league records its head-to-head format, one win by default.
    assert plain.payload() == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": "one_win",
    }
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
    # A league without waivers records the three keys of PR D4c (and the format's since the
    # format PR) and labels as it did.
    assert set(plain.payload()) == {"scoring", "points", "held", "h2h"}
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
        "h2h": "one_win",
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
        ("bids", None, "--waivers bids: one of none, priority"),
        ("priority", "0", "--waiver-days 0: a dropped player waits 1 to 7 days"),
        ("priority", "8", "--waiver-days 8: a dropped player waits 1 to 7 days"),
        ("priority", "two", "--waiver-days two: a whole number of days"),
        ("none", "2", "--waiver-days 2: a dropped player's wait is a waiver league's"),
        ("none", "3", "it is read only with --waivers priority or faab"),
    ],
)
def test_a_waiver_flag_out_of_the_plan_is_refused_in_words(waivers, days, says):
    with pytest.raises(ValueError) as e:
        shapes.parse_waivers(waivers, days)
    assert says in str(e.value)


@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
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


# --------------------------------------------------------------------------- PR Fb: the budget
def test_a_faab_league_says_its_budget_and_the_rivals_scale_in_the_label_and_the_payload():
    faab = shapes.LeagueRules(waivers="faab")
    assert faab.waiting and faab.bidding and not shapes.LeagueRules(waivers="priority").bidding
    assert (faab.budget, faab.rival_scale) == (shapes.BUDGET, shapes.RIVAL_SCALE) == (100, 1.0)
    assert faab.label() == (
        "the nine categories, no held slot, waivers by FAAB after 2 days, $100 a team, the "
        "rivals' bids x1"
    )
    assert faab.payload() == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": "one_win",
        "waivers": "faab",
        "waiver_days": 2,
        "budget": 100,
        "rival_scale": 1.0,
    }
    named = shapes.LeagueRules("points", shapes.POINTS_DEFAULT, ("IL",), "faab", 3, 250, 0.5)
    assert named.label() == (
        "points on ESPN's default table, one IL slot, waivers by FAAB after 3 days, $250 a team, "
        "the rivals' bids x0.5"
    )
    assert (named.payload()["budget"], named.payload()["rival_scale"]) == (250, 0.5)
    # A priority league records the five keys it did before the budget.
    assert "budget" not in shapes.LeagueRules(waivers="priority").payload()
    # Hashable and told apart by the budget and the scale.
    assert len({faab, named, shapes.LeagueRules(waivers="faab", budget=99)}) == 3
    assert shapes.LeagueRules(waivers="faab", rival_scale=2) != faab


def test_the_budget_flags_parse_to_whole_dollars_and_a_scale():
    assert shapes.parse_waivers("faab") == ("faab", 2)
    assert shapes.parse_waivers("FAAB", "4") == ("faab", 4)
    assert shapes.parse_budget("faab", None, None) == (100, 1.0)
    assert shapes.parse_budget("faab", "1", "0.5") == (1, 0.5)
    assert shapes.parse_budget("faab", "1000", "2") == (1000, 2.0)
    assert shapes.parse_budget("none", None, None) == (100, 1.0)
    assert shapes.parse_budget("priority", None, None) == (100, 1.0)


@pytest.mark.parametrize(
    ("waivers", "budget", "scale", "says"),
    [
        ("priority", "100", None, "--budget 100: a budget and the rivals' bids are"),
        ("none", None, "1", "--rival-scale 1: a budget and the rivals' bids are a FAAB league's"),
        ("priority", None, "2", "it is read only with --waivers faab"),
        ("faab", "0", None, "--budget 0: a team starts with 1 to 1000 dollars"),
        ("faab", "1001", None, "--budget 1001: a team starts with 1 to 1000 dollars"),
        ("faab", "99.5", None, "--budget 99.5: whole dollars"),
        ("faab", None, "0", "--rival-scale 0: a number above 0"),
        ("faab", None, "-1", "--rival-scale -1: a number above 0"),
        ("faab", None, "inf", "--rival-scale inf: a number above 0"),
        ("faab", None, "nan", "--rival-scale nan: a number above 0"),
        ("faab", None, "lots", "--rival-scale lots: a number above 0"),
    ],
)
def test_a_budget_flag_out_of_the_plan_is_refused_in_words(waivers, budget, scale, says):
    with pytest.raises(ValueError) as e:
        shapes.parse_budget(waivers, budget, scale)
    assert says in str(e.value)


@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
        ({"waivers": "faab", "budget": 0}, "budget 0: a team starts with 1 to 1000 dollars"),
        ({"waivers": "faab", "budget": 1001}, "a team starts with 1 to 1000 dollars"),
        ({"waivers": "faab", "budget": 100.0}, "budget 100.0: whole dollars"),
        ({"waivers": "faab", "budget": True}, "budget True: whole dollars"),
        ({"waivers": "faab", "rival_scale": 0.0}, "rival scale 0.0: a number above 0"),
        ({"waivers": "faab", "rival_scale": float("inf")}, "a number above 0"),
        ({"waivers": "faab", "rival_scale": True}, "rival scale True: a number above 0"),
        ({"waivers": "priority", "budget": 50}, "the rivals' bids are a FAAB league's"),
        ({"rival_scale": 2.0}, "budget 100 and rival scale 2 with waivers none"),
    ],
)
def test_budget_rules_out_of_the_plan_are_refused_in_words(kwargs, says):
    with pytest.raises(ValueError) as e:
        shapes.LeagueRules(**kwargs)
    assert says in str(e.value)
