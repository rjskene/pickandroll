"""A categories league's head-to-head format (#397, the user's ruling 2026-11-15): every category
counts in the standings (a 5-4 week adds five wins and four losses), or a week is one win. The
format is read from Yahoo's settings (v3's ``scoring_type``, the settings page's "Scoring Type")
and, where neither says it, from the standings: one win a week leaves every team's wins, losses
and ties summing to the weeks played. The league page and the landing label it.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pickandroll.api import seasons as season_api
from pickandroll.season import Season
from pickandroll.season.state import (
    EACH_CATEGORY,
    H2H_SETTINGS,
    H2H_STANDINGS,
    ONE_WIN,
    PAGE_FIELDS,
    SeasonSettings,
    h2h_from_standings,
)
from pickandroll.sources.yahoo import pages, public
from tests.test_season import base, fixture, part
from tests.test_waiver_rules import listed, private_page, season


def league_after(week: int, records: list[tuple[int, int, int]]) -> dict:
    """The league page's read in ``week``, the twelve teams' records as given (the rest 0-0-0)."""
    d = pages.parse_league_page(fixture("league.html"))
    teams = [
        {**t, "wins": w, "losses": lo, "ties": ti}
        for t, (w, lo, ti) in zip(d["teams"], records + [(0, 0, 0)] * 12, strict=False)
    ]
    return {**d, "week": week, "teams": teams}


def read(league: dict, *, page: dict | None = None, v3: dict | None = None, scoring="categories"):
    parts = {"league": part("league", league)}
    if page is not None:
        parts["league_settings"] = part("league_settings", page)
    if v3 is not None:
        parts["settings"] = part("settings", v3)
    return Season.from_parts(replace(base(), scoring=scoring), parts).settings


# 31822 after three weeks: every record sums to 3. A public league after three weeks: 5-4 weeks.
ONE_WIN_WEEKS = [(2, 1, 0), (1, 2, 0), (3, 0, 0), (0, 3, 0), (1, 1, 1)] + [(2, 1, 0)] * 7
EACH_WEEKS = [(10, 17, 0), (15, 11, 1), (14, 13, 0)] + [(13, 14, 0)] * 9


@pytest.mark.parametrize(
    ("printed", "h2h"),
    [
        ("Head-to-Head - Categories", EACH_CATEGORY),
        ("Head-to-Head - One Win", ONE_WIN),
        ("Head-to-Head - Most Categories", ONE_WIN),
        ("Head-to-Head  -  one win", ONE_WIN),
        ("Head-to-Head - Points", None),
        ("Rotisserie", None),
        (None, None),
    ],
)
def test_the_scoring_type_names_the_format(printed, h2h):
    assert pages.h2h_format(printed) == h2h


def test_the_settings_page_gives_the_scoring_type_as_printed_and_its_format():
    d = pages.parse_settings_page(fixture("settings_page.html"))
    assert (d["scoring_type"], d["h2h"]) == ("Head-to-Head - Categories", EACH_CATEGORY)
    html = fixture("settings_page_private.html").replace(
        "Head-to-Head - Categories", "Head-to-Head - One Win"
    )
    d = pages.parse_settings_page(html)
    assert (d["scoring_type"], d["h2h"]) == ("Head-to-Head - One Win", ONE_WIN)


def test_v3_names_the_format_by_its_scoring_type():
    body = json.loads(fixture("settings.json"))
    assert public.settings_from_v3(body)["h2h"] == EACH_CATEGORY  # "head"
    body["service"]["scoring_type"] = "headone"
    assert public.settings_from_v3(body)["h2h"] == ONE_WIN
    body["service"]["scoring_type"] = "headpoint"
    assert public.settings_from_v3(body)["h2h"] is None
    del body["service"]["scoring_type"]
    assert public.settings_from_v3(body)["h2h"] is None


def test_the_standings_say_the_format_when_the_records_do():
    assert h2h_from_standings(ONE_WIN_WEEKS, 3) == ONE_WIN
    assert h2h_from_standings(EACH_WEEKS, 3) == EACH_CATEGORY
    # Before a week is played, or with no record, nothing is said.
    assert h2h_from_standings([(0, 0, 0)] * 12, 0) is None
    assert h2h_from_standings([], 3) is None
    # A record short of the weeks (a read between weeks) says neither.
    assert h2h_from_standings([(2, 1, 0), (1, 1, 0)], 3) is None


def test_a_one_win_league_is_read_from_its_settings_page_and_one_where_each_counts_from_v3():
    one = read(league_after(4, ONE_WIN_WEEKS), page={**private_page(), "h2h": ONE_WIN})
    assert (one.h2h, one.h2h_from, one.one_win) == (ONE_WIN, H2H_SETTINGS, True)
    v3 = public.settings_from_v3(json.loads(fixture("settings.json")))
    each = read(league_after(4, EACH_WEEKS), v3=v3)
    assert (each.h2h, each.h2h_from, each.one_win) == (EACH_CATEGORY, H2H_SETTINGS, False)
    # v3's format wins over the page's, as for every rule v3 gives.
    both = read(league_after(4, EACH_WEEKS), v3=v3, page={**private_page(), "h2h": ONE_WIN})
    assert both.h2h == EACH_CATEGORY


def test_without_a_settings_read_the_standings_give_the_format_of_both_kinds():
    page = {**private_page(), "h2h": None}
    one = read(league_after(4, ONE_WIN_WEEKS), page=page)
    assert (one.h2h, one.h2h_from) == (ONE_WIN, H2H_STANDINGS)
    each = read(league_after(4, EACH_WEEKS), page=page)
    assert (each.h2h, each.h2h_from) == (EACH_CATEGORY, H2H_STANDINGS)
    # Week 1: nothing played, nothing known. A points league is never read as either.
    assert read(league_after(1, []), page=page).h2h is None
    assert read(league_after(4, EACH_WEEKS), page=page, scoring="points").h2h is None


def test_the_format_survives_the_stored_settings():
    s = read(league_after(4, ONE_WIN_WEEKS), page=private_page())
    again = SeasonSettings.from_dict(s.to_dict())
    assert (again.h2h, again.h2h_from, again.scoring_type) == (
        s.h2h,
        s.h2h_from,
        "Head-to-Head - Categories",
    )


def test_a_stored_settings_page_without_the_scoring_type_is_read_again():
    assert "scoring_type" in PAGE_FIELDS
    old = {k: v for k, v in private_page().items() if k not in ("scoring_type", "h2h")}
    assert listed(season(page=old)) == [True, True]
    assert listed(season(page=private_page())) == [False, False]


def test_the_summary_carries_the_format_the_labels_read():
    one = Season.from_parts(base(), {"league": part("league", league_after(4, ONE_WIN_WEEKS))})
    summary = season_api._summary(one, False, True, None)
    assert (summary["h2h"], summary["h2h_from"]) == (ONE_WIN, H2H_STANDINGS)
    each = season(v3=public.settings_from_v3(json.loads(fixture("settings.json"))))
    assert season_api._summary(each, True, True, None)["h2h"] == EACH_CATEGORY
