"""A league's waiver, acquisition and trade rules from its settings page (#261): a private
league's page fills what Yahoo's v3 settings read (a public league's only) leaves None, so its
weekly cap and its re-add span are its own; a public league keeps the v3 values.

The private settings page fixture is made up: a made-up league name, Yahoo's row labels and its
standard roster. The public one is the season fixtures' (a public league's page, its id and
name replaced).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from pickandroll.api import season_queue
from pickandroll.api import seasons as season_api
from pickandroll.season import Calendar, Season, Week
from pickandroll.season.state import Player, Transaction
from pickandroll.sources.yahoo import pages
from tests.test_season import TODAY, base, fixture, part

WEEKS = tuple(
    Week(
        n, date(2026, 10, 19) + timedelta(weeks=n - 1), date(2026, 10, 25) + timedelta(weeks=n - 1)
    )
    for n in range(1, 23)
)
#: What Yahoo's v3 settings say of a public league (tests/fixtures/season/settings.json).
V3 = {
    "waiver_rule": "continuous",
    "waiver_days": 2,
    "uses_faab": True,
    "max_weekly_adds": 4,
    "trade_ratify": "yahoo",
    "trade_review_days": 2,
}


def private_page() -> dict:
    return pages.parse_settings_page(fixture("settings_page_private.html"))


def season(*, v3: dict | None = None, page: dict | None = None) -> Season:
    parts = {
        "league": part("league", pages.parse_league_page(fixture("league.html"))),
        "calendar": part("calendar", Calendar(WEEKS).to_dict()),
    }
    if page is not None:
        parts["league_settings"] = part("league_settings", page)
    if v3 is not None:
        parts["settings"] = part("settings", v3)
    return Season.from_parts(base(), parts)


def test_the_settings_page_reads_the_waiver_acquisition_and_trade_rows():
    d = private_page()
    assert d["roster"][-2:] == ["IL", "IL"]
    assert (d["waiver_days"], d["waiver_rule"], d["uses_faab"]) == (
        1,
        "Continual rolling list",
        False,
    )
    assert (d["max_weekly_adds"], d["max_season_adds"]) == (5, None)
    assert d["post_draft_players"] == "free_agents"
    assert (d["trade_ratify"], d["trade_review_days"]) == ("vote", 1)
    # The public page prints fewer of them: what it does not print stays None.
    public = pages.parse_settings_page(fixture("settings_page.html"))
    assert (public["waiver_days"], public["max_weekly_adds"]) == (2, 4)
    assert (public["uses_faab"], public["post_draft_players"], public["trade_ratify"]) == (
        None,
        None,
        None,
    )


def test_the_rows_words_map_to_v3s():
    assert pages.waiver_rules({"waiver mode": "FAAB"})["uses_faab"] is True
    assert pages.waiver_rules({"post draft players": "Waivers"})["post_draft_players"] == "waivers"
    assert pages.waiver_rules({"max acquisitions for entire season": "40"})["max_season_adds"] == 40
    assert (
        pages.waiver_rules({"max acquisitions per week": "No maximum"})["max_weekly_adds"] is None
    )
    for printed, v3 in (
        ("Commissioner", "commish"),
        ("Yahoo", "yahoo"),
        ("None", "none"),
        ("Soon", None),
    ):
        assert pages.waiver_rules({"trade review": printed})["trade_ratify"] == v3
    assert all(v is None for v in pages.waiver_rules({}).values())


def test_a_private_league_takes_its_rules_from_its_settings_page():
    s = season(page=private_page()).settings
    assert (s.max_weekly_adds, s.waiver_days, s.uses_faab) == (5, 1, False)
    assert (s.max_season_adds, s.post_draft_players) == (None, "free_agents")
    assert (s.trade_ratify, s.trade_review_days, s.waiver_rule) == (
        "vote",
        1,
        "Continual rolling list",
    )
    # The new fields round-trip.
    again = type(s).from_dict(s.to_dict())
    assert (again.post_draft_players, again.max_season_adds) == ("free_agents", None)


def test_a_field_the_v3_read_set_wins_and_one_it_left_none_takes_the_pages():
    s = season(v3=V3, page=private_page()).settings
    assert (s.max_weekly_adds, s.waiver_days, s.uses_faab) == (4, 2, True)
    assert (s.trade_ratify, s.trade_review_days, s.waiver_rule) == ("yahoo", 2, "continuous")
    # v3 has no post-draft field: the page's fills it.
    assert s.post_draft_players == "free_agents"
    # A v3 read with a field None leaves the page's.
    s = season(v3={**V3, "max_weekly_adds": None}, page=private_page()).settings
    assert s.max_weekly_adds == 5


def test_the_weekly_cap_follows_the_league():
    adds = season_api._glance(season(page=private_page()), TODAY)["adds"]
    assert (adds["limit"], adds["left"]) == (5, 5 - adds["used"])
    public = season_api._glance(
        season(v3=V3, page=pages.parse_settings_page(fixture("settings_page.html"))), TODAY
    )
    assert public["adds"]["limit"] == 4
    # Neither read: no cap known.
    assert season_api._glance(season(), TODAY)["adds"]["limit"] is None


def drop(player: int, when: str) -> Transaction:
    return Transaction(
        "drop", Player(player, f"Player {player}", "X", ("PG",)), 4, None, None, when
    )


def test_the_re_add_span_is_the_leagues_waiver_days():
    drops = (drop(301, "Oct 20, 3:57 am"), drop(302, "Oct 19, 3:57 am"))
    private = replace(season(page=private_page()), transactions=drops)
    assert season_queue.dropped_recently(private, TODAY) == {301}
    public = replace(season(v3=V3), transactions=drops)
    assert season_queue.dropped_recently(public, TODAY) == {301, 302}
