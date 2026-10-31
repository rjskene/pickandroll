"""A league's waiver, acquisition and trade rules from its settings page (#261): a private
league's page fills what Yahoo's v3 settings read (a public league's only) leaves None, so its
weekly cap and its re-add span are its own; a public league keeps the v3 values. And a standard-waivers league's claim (PR 2): no bid, the
odds by waiver priority at an assumed rival claim rate.

The private settings page fixture is made up: a made-up league name, Yahoo's row labels and its
standard roster. The public one is the season fixtures' (a public league's page, its id and
name replaced).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from pickandroll.api import season_knobs, season_moves, season_queue
from pickandroll.api import seasons as season_api
from pickandroll.season import Calendar, Season, Week
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season.state import Player, Transaction
from pickandroll.sources.yahoo import pages
from tests.test_moves_queue import PLAN, entry, league_day, move
from tests.test_season import (
    LEAGUE,
    TODAY,
    base,
    fixture,
    fixture_names,
    part,
    projection_csv,
    season_client,
)


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


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


# --------------------------------------------------------------------------- PR 2: claims
def test_a_standard_claims_odds_are_that_no_team_ahead_claims_first():
    # Priority 1: no team ahead, the claim is certain.
    c = mv.priority_claim(1, 12, 0.3)
    assert (c["ahead"], c["odds"], c["assumed"], c["after"]) == (0, 1.0, True, 12)
    assert mv.priority_claim(3, 12, 0.3)["odds"] == round(0.7**2, 4)
    assert mv.priority_claim(12, 12, 0.3)["odds"] == round(0.7**11, 4)
    # No rival claims: certain at any priority; every rival claims: lost unless first.
    assert mv.priority_claim(12, 12, 0.0)["odds"] == 1.0
    assert mv.priority_claim(5, 12, 1.0)["odds"] == 0.0
    assert mv.priority_claim(1, 12, 1.0)["odds"] == 1.0
    # A rate past its bounds is held to them; no priority read, no claim's terms.
    assert mv.priority_claim(2, 12, 1.5)["rate"] == 1.0
    assert mv.priority_claim(None, 12, 0.3) is None
    assert mv.RIVAL_CLAIM_RATE == 0.3


def put_settings(client, body) -> None:
    path = season_knobs.autopilot_dir(client.data_dir) / season_queue.SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))


@pytest.mark.parametrize(
    ("body", "rate"),
    [
        (None, 0.3),
        ({"rival_claim_rate": 0.45, "live_after": {"dry_run_days": 1}}, 0.45),
        ({"rival_claim_rate": 0}, 0.0),
        ({"rival_claim_rate": 1}, 1.0),
        ({"rival_claim_rate": 1.2}, 0.3),
        ({"rival_claim_rate": -0.1}, 0.3),
        ({"rival_claim_rate": "high"}, 0.3),
        ({"rival_claim_rate": True}, 0.3),
        ("{not json", 0.3),
    ],
)
def test_the_rival_claim_rate_is_the_settings_files_number_from_0_to_1_else_the_default(
    client, body, rate
):
    if body is not None:
        put_settings(client, body)
    assert season_queue.rival_claim_rate(client.data_dir) == rate


def claim_day(uses_faab):
    e = entry(move(101, 201, 0.9), move(102, 202, 0.8))
    availability = {101: ("W", date(2026, 10, 22)), 102: ("FA", None)}
    day = league_day(e, availability=availability, uses_faab=uses_faab)
    return qa.queue_of(day, date(2026, 10, 21), PLAN, (0.1, "the plan floor"), None)


def test_a_standard_leagues_queue_places_no_bid_and_claims_by_priority():
    standard = {x["add"]: x for x in claim_day(False)}
    assert standard[101]["bid"] is None and standard[101]["claim"] == "priority"
    # A free agent is added at once: no claim, and no bid either.
    assert standard[102]["bid"] is None and standard[102]["claim"] is None
    assert qa.effective_bid(standard[101]) == 0
    # A FAAB league, or one whose mode is not read, bids as before.
    for uses_faab in (True, None):
        faab = {x["add"]: x for x in claim_day(uses_faab)}
        assert faab[101]["bid"]["amount"] >= 1 and faab[101]["claim"] is None
        assert faab[102]["bid"]["amount"] == 0


def test_a_faab_leagues_moves_view_carries_no_claim(client):
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    # The public fixture league bids (v3's uses_faab): no claim block.
    r = client.get(f"/seasons/{LEAGUE}/moves", params={"source": "page"})
    assert r.status_code == 200, r.text
    assert r.json()["claim"] is None


def test_a_standard_leagues_moves_view_carries_the_claims_terms(client, monkeypatch):
    # The fixture league under standard waivers: my priority (2) and the assumed rate.
    build = season_moves.build

    def standard(season, *args, **kwargs):
        settings = replace(season.settings, uses_faab=False)
        return build(replace(season, settings=settings), *args, **kwargs)

    monkeypatch.setattr(season_moves, "build", standard)
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    built = client.app.state.seasons._built(LEAGUE, "bbm")
    assert built.priority == (2, 12)
    assert season_moves.moves_payload(built)["claim"] == mv.priority_claim(2, 12, 0.3)
    assert season_moves.claim_of(built, 0.4)["odds"] == 0.6
    url, page = f"/seasons/{LEAGUE}/moves", {"source": "page"}
    claim = client.get(url, params=page).json()["claim"]
    assert (claim["priority"], claim["ahead"], claim["odds"], claim["after"]) == (2, 1, 0.7, 12)
    # The route reads the rate at request time, past the kept solve: no restart to change it.
    put_settings(client, {"rival_claim_rate": 0.5})
    claim = client.get(url, params=page).json()["claim"]
    assert (claim["rate"], claim["odds"], claim["assumed"]) == (0.5, 0.5, True)
