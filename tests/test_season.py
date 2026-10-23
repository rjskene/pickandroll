"""#92: a league's season from Yahoo's public sources (and, for a private league, the pages the
extension posts): the week calendar, the page parsers, the season state and the routes.

The fixtures in tests/fixtures/season are public pages of a prize league, cut to the tables
the parsers read and anonymised: the league id is 100001, every fantasy team is "Team <id>",
no manager names; the transactions page is another league's, renamed the same way. NBA
players' names and Yahoo's ownership numbers are Yahoo's public data. Nothing here is from
Basketball Monster.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import (
    SessionStore,
    create_app,
    season_flags,
    season_moves,
    season_strategy,
    season_week,
)
from pickandroll.api import seasons as season_api
from pickandroll.season import (
    EXTENSION,
    PUBLIC,
    Calendar,
    Matchup,
    Part,
    Player,
    Season,
    SeasonSettings,
    Week,
    build_calendar,
    merge_part,
    mondays,
    pairings_key,
    unpaired_matchups,
)
from pickandroll.season import flags as fl
from pickandroll.season import moves as mv
from pickandroll.season import strategy as st
from pickandroll.season import weekly as wk
from pickandroll.sources import schedule
from pickandroll.sources.injuries import ESPN_INJURIES_URL
from pickandroll.sources.yahoo import pages, public

from .test_moves import WEEKS, build, streaming_league

FIXTURES = Path(__file__).parent / "fixtures" / "season"
LEAGUE = "100001"
#: The day the fixture pages were read (US Eastern), mid-afternoon.
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
TODAY = date(2026, 10, 21)
ROSTER = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN"]
CATS = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


# --------------------------------------------------------------------------- calendar
def test_the_calendar_merges_mondays_yahoo_labels_as_one_week():
    first, end = date(2026, 10, 20), date(2026, 11, 22)
    days = mondays(first, end)
    assert days[0] == date(2026, 10, 19) and days[-1] == date(2026, 11, 16)
    # Week 3 runs two Mondays (a merged week), the last runs to the season's end.
    labels = dict(zip(days, [1, 2, 3, 3, 4], strict=True))
    cal = build_calendar(first, end, labels)
    assert not cal.estimated
    assert [(w.number, w.start, w.end) for w in cal.weeks] == [
        (1, date(2026, 10, 19), date(2026, 10, 25)),
        (2, date(2026, 10, 26), date(2026, 11, 1)),
        (3, date(2026, 11, 2), date(2026, 11, 15)),
        (4, date(2026, 11, 16), date(2026, 11, 22)),
    ]
    assert cal.week_of(date(2026, 11, 10)).number == 3
    assert [w.number for w in cal.ahead(date(2026, 10, 28), 3)] == [2, 3, 4]
    assert cal.week(3).days(since=date(2026, 11, 14)) == [date(2026, 11, 14), date(2026, 11, 15)]
    assert Calendar.from_dict(cal.to_dict()) == cal


def test_a_calendar_without_labels_is_the_monday_rule_and_says_so():
    cal = build_calendar(date(2026, 10, 20), date(2026, 11, 8))
    assert cal.estimated
    assert [(w.number, w.start, w.end) for w in cal.weeks] == [
        (1, date(2026, 10, 19), date(2026, 10, 25)),
        (2, date(2026, 10, 26), date(2026, 11, 1)),
        (3, date(2026, 11, 2), date(2026, 11, 8)),
    ]


# --------------------------------------------------------------------------- page parsers
def test_page_kinds_come_from_the_url():
    base = "https://basketball.fantasysports.yahoo.com/nba/100001"
    assert pages.page_kind(base) == ("league", {"league": LEAGUE})
    assert pages.page_kind(base + "/4") == ("team", {"league": LEAGUE, "team_id": 4})
    assert pages.page_kind(base + "/players?status=A&stat1=R_O")[0] == "players"
    assert pages.page_kind(base + "/matchup?week=3&mid1=4&mid2=10") == (
        "matchup",
        {"league": LEAGUE, "week": 3, "teams": [4, 10]},
    )
    assert pages.page_kind(base + "/transactions")[0] == "transactions"
    # The league page for another week (its week select) is that week's pairs.
    assert pages.page_kind(base + "?matchup_week=3") == (
        "league",
        {"league": LEAGUE, "matchup_week": 3},
    )
    with pytest.raises(pages.PageError):
        pages.page_kind("https://sports.yahoo.com/nba/players/6205")


def test_the_team_page_gives_the_roster_by_slot():
    d = pages.parse_team_page(fixture("team4.html"), 4)
    assert d["name"] == "Team 4" and d["week"] == 1
    assert [s["slot"] for s in d["spots"]] == ROSTER
    first = d["spots"][0]["player"]
    # The link text is abbreviated ("N. Alexander-Walker"); the title carries the full name.
    assert first == {
        "yahoo_id": 6205,
        "name": "Nickeil Alexander-Walker",
        "nba_team": "ATL",
        "positions": ["PG", "SG"],
        "status": None,
        "status_full": None,
        "note": None,
    }
    out = [s["player"] for s in d["spots"] if s["player"]["status"]]
    assert [(p["name"], p["status"], p["status_full"]) for p in out] == [
        ("Aaron Nesmith", "O", "Out")
    ]
    # Injury slots are read as slots.
    il = pages.parse_team_page(fixture("team2.html"), 2)["spots"]
    assert [s["slot"] for s in il].count("IL") == 3


def test_the_players_page_gives_the_available_pool_with_ownership():
    rows = pages.parse_players_page(fixture("avail0.html"), TODAY)["rows"]
    assert len(rows) == 25
    top = rows[0]
    assert top["player"]["name"] == "Dillon Brooks" and top["player"]["yahoo_id"] == 5858
    assert top["availability"] == "W" and top["clears"] == "2026-10-22"
    assert (top["pct_rostered"], top["pct_rostered_change"]) == (46.0, 0.0)
    assert (top["pct_started"], top["pct_started_change"]) == (15.0, 1.0)
    assert (top["adds"], top["drops"]) == (1115, 270)
    assert [r["pct_rostered"] for r in rows] == sorted(
        (r["pct_rostered"] for r in rows), reverse=True
    )
    assert {"O", "NA"} <= {r["player"]["status"] for r in rows}


@pytest.mark.parametrize(
    ("text", "value", "change"),
    [
        ("35% (–)", 35.0, 0.0),
        ("8% ( -1 )", 8.0, -1.0),
        ("12% (+4)", 12.0, 4.0),
        ("35%", 35.0, None),
        ("-", None, None),
    ],
)
def test_percent_cells_read_the_value_and_the_days_change(text, value, change):
    assert pages._pct(text) == (value, change)


def test_waiver_clear_dates_take_the_nearest_year():
    assert pages.clears_date("W (Oct 22)", date(2026, 10, 21)) == date(2026, 10, 22)
    assert pages.clears_date("W (Jan 2)", date(2026, 12, 31)) == date(2027, 1, 2)
    assert pages.clears_date("FA", date(2026, 12, 31)) is None


def test_the_league_page_gives_standings_and_this_weeks_pairs():
    d = pages.parse_league_page(fixture("league.html"))
    assert d["name"] == "Test League 100001" and d["week"] == 1
    assert [t["team_id"] for t in d["teams"]] == list(range(1, 13))
    mine = next(t for t in d["teams"] if t["team_id"] == 4)
    assert mine == {
        "team_id": 4,
        "name": "Team 4",
        "rank": None,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "points_for": None,
        "waiver_priority": 2,
        "faab": 100.0,
        "moves": None,
    }
    assert {tuple(m["teams"]) for m in d["matchups"]} == {
        (1, 2),
        (3, 11),
        (4, 10),
        (5, 9),
        (6, 8),
        (7, 12),
    }


def week_page(week: int, paired: bool = True) -> str:
    """The fixture league page as Yahoo shows another week (``?matchup_week=N``): the same
    pairs, no scores yet; or, not ``paired``, no pairs (a playoff week not seeded yet)."""
    html = re.sub(r"<div class='Fz-lg '>\d+</div>", "", fixture("league.html"))
    html = html.replace("week=1&", f"week={week}&").replace(
        "Week 1 Matchups", f"Week {week} Matchups"
    )
    return html if paired else html.replace("matchup?week=", "matchup?unseeded=")


def test_the_league_page_gives_each_pairs_live_score():
    d = pages.parse_league_page(fixture("league.html"))
    scores = {tuple(m["teams"]): m.get("score") for m in d["matchups"]}
    assert len(scores) == 6
    assert scores[(4, 10)] == [5.0, 3.0] and scores[(5, 9)] == [2.0, 2.0]
    # A week not played yet has the pairs and no score.
    later = pages.parse_league_page(week_page(2))["matchups"]
    assert {m["week"] for m in later} == {2} and all("score" not in m for m in later)


def test_the_matchup_page_gives_both_teams_totals_and_the_score():
    d = pages.parse_matchup_page(fixture("matchup.html"))
    assert d["week"] == 1 and d["teams"] == [4, 10] and d["score"] == [5.0, 3.0]
    assert d["totals"]["4"]["FG%"] == ".484" and d["totals"]["10"]["PTS"] == "31"
    points = pages.parse_matchup_page(fixture("matchup_points.html"))
    assert points["teams"] == [7, 12] and points["totals"] == {}
    assert points["lines"] == {
        "vs": [114.2, 92.7],
        "Orig Proj": [1061.41, 922.52],
        "Live Proj": [1065.53, 943.58],
    }


def test_the_transactions_page_pairs_each_add_with_its_drop():
    rows = pages.parse_transactions_page(fixture("transactions.html"))["rows"]
    assert len(rows) == 8
    claim = [r for r in rows if r["group"] == 1]
    assert [(r["kind"], r["player"]["name"], r["detail"]) for r in claim] == [
        ("add", "Jalen Smith", "$0 Waiver"),
        ("drop", "Kyshawn George", "To Waivers"),
    ]
    assert {r["team_id"] for r in claim} == {8} and claim[0]["team_name"] == "Team 8"
    assert rows[0]["player"]["status"] == "O" and rows[0]["when"].startswith("Oct 20")
    assert pages.parse_transactions_page("<html><body><p>none</p></body></html>") == {"rows": []}


def test_an_empty_page_is_refused_not_read_as_an_empty_roster():
    # A private league's page served without a session comes back empty.
    with pytest.raises(pages.PageError):
        pages.parse_team_page("", 4)
    with pytest.raises(pages.PageError):
        pages.parse_players_page("", TODAY)


# --------------------------------------------------------------------------- v3 and ESPN
def test_v3_settings_and_players():
    read = public.settings_from_v3(json.loads(fixture("settings.json")))
    assert read["name"] == "Test League 100001"
    assert (read["current_week"], read["end_week"], read["end_date"]) == (1, 22, "2027-04-04")
    assert (read["waiver_rule"], read["uses_faab"], read["max_weekly_adds"]) == (
        "continuous",
        True,
        4,
    )
    assert (read["trade_ratify"], read["trade_review_days"]) == ("yahoo", 2)
    assert read["playoff_teams"] == 6
    # Yahoo's answer for a league it does not serve publicly.
    assert public.settings_from_v3({"error": {"description": "league not found"}}) is None
    pool = public.players_from_v3(json.loads(fixture("players.json")))
    nesmith = next(p for p in pool if p["name"] == "Aaron Nesmith")
    assert nesmith["status"] == "O" and nesmith["nba_team"] == "IND"


def test_the_schedule_reads_espn_in_yahoos_team_names(tmp_path):
    day = json.loads(fixture("espn_20261021.json"))
    teams = schedule.teams_playing(day)
    assert len(teams) == 22 and "GSW" in teams and "GS" not in teams
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return fixture("espn_20261021.json")

    days = [date(2026, 10, 21)]
    first = schedule.schedule_days(days, fetch, tmp_path, now=NOW)
    assert first == {"2026-10-21": teams} and len(calls) == 1
    # Fresh in the cache: not read again; stale and not yet over: read again.
    schedule.schedule_days(days, fetch, tmp_path, now=NOW + timedelta(hours=1))
    assert len(calls) == 1
    schedule.schedule_days(days, fetch, tmp_path, now=NOW + timedelta(hours=13))
    assert len(calls) == 2
    # A copy read after the date was over is final.
    schedule.schedule_days(days, fetch, tmp_path, now=NOW + timedelta(days=3))
    schedule.schedule_days(days, fetch, tmp_path, now=NOW + timedelta(days=30))
    assert len(calls) == 3


def test_the_schedule_cache_serves_from_disk_offline(tmp_path):
    days = [date(2026, 10, 21), date(2026, 10, 22)]
    schedule.schedule_days(days, lambda url: fixture(f"espn_{url[-8:]}.json"), tmp_path, now=NOW)

    def offline(url: str) -> str:
        raise public.FetchError(f"{url}: no network")

    # Stale copies (a day later) are served when the source cannot be read.
    later = schedule.schedule_days(days, offline, tmp_path, now=NOW + timedelta(days=1))
    assert set(later) == {"2026-10-21", "2026-10-22"} and "GSW" in later["2026-10-21"]
    # A date never read is left out, so the season says its games are not known.
    assert schedule.schedule_days([date(2026, 10, 23)], offline, tmp_path, now=NOW) == {}


def test_a_far_date_of_the_schedule_is_read_again_only_weekly(tmp_path):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return fixture("espn_20261021.json")

    near, far, far_from = date(2026, 10, 23), date(2026, 12, 1), date(2026, 11, 16)
    schedule.schedule_days([near, far], fetch, tmp_path, now=NOW, far_from=far_from)
    assert len(calls) == 2
    # A day later the near date's copy is stale, the far date's is not.
    later = NOW + timedelta(days=1)
    schedule.schedule_days([near, far], fetch, tmp_path, now=later, far_from=far_from)
    assert calls[2:] == [schedule.scoreboard_url(near)]
    # Eight days on, the far date's is.
    later = NOW + timedelta(days=8)
    schedule.schedule_days([far], fetch, tmp_path, now=later, far_from=far_from)
    assert calls[3:] == [schedule.scoreboard_url(far)]


# --------------------------------------------------------------------------- the season state
def base(league: str = LEAGUE, my_team: int = 4) -> SeasonSettings:
    return SeasonSettings(league, "categories", tuple(CATS), tuple(ROSTER), 12, my_team)


def part(key: str, data, source: str = PUBLIC, at: datetime = NOW) -> Part:
    return Part(key, at, source, data)


def test_the_season_assembles_its_parts():
    league = pages.parse_league_page(fixture("league.html"))
    parts: dict[str, Part] = {}
    for p in (
        part("settings", public.settings_from_v3(json.loads(fixture("settings.json")))),
        part("players", public.players_from_v3(json.loads(fixture("players.json")))),
        part("league", league),
        part("roster/4", pages.parse_team_page(fixture("team4.html"), 4)),
        part("roster/10", pages.parse_team_page(fixture("team10.html"), 10)),
        part("available", pages.parse_players_page(fixture("avail0.html"), TODAY)),
        part("matchup/1/4-10", pages.parse_matchup_page(fixture("matchup.html"))),
        part("schedule", {"days": {"2026-10-21": ["ATL", "IND"], "2026-10-22": ["ATL"]}}),
    ):
        parts = merge_part(parts, p)
    s = Season.from_parts(base(), parts)
    assert s.settings.name == "Test League 100001" and s.settings.current_week == 1
    assert s.my_team.name == "Team 4" and s.opponent.team_id == 10
    assert len(s.my_roster) == 13 and len(s.rosters[10]) == 13
    assert s.matchup_of(4).score == (5.0, 3.0)
    # The pool fills in what a page leaves out (the injury's words).
    nesmith = next(x.player for x in s.my_roster if x.player.name == "Aaron Nesmith")
    assert nesmith.out and nesmith.status_full == "Out"
    assert s.games("ATL", [date(2026, 10, 21), date(2026, 10, 22)]) == 2
    assert s.games("IND", [date(2026, 10, 21), date(2026, 10, 23)]) is None  # not covered
    # A player who is now on a roster drops out of the available pool.
    taken = s.available[0].player
    claimed = parts["roster/4"].data | {
        "spots": [*parts["roster/4"].data["spots"], {"slot": "BN", "player": taken.to_dict()}]
    }
    s2 = Season.from_parts(base(), merge_part(parts, part("roster/4", claimed)))
    assert taken.yahoo_id not in {a.player.yahoo_id for a in s2.available}
    assert len(s2.available) == len(s.available) - 1


def test_the_first_playoff_week_is_a_week_a_round_ending_the_season():
    s = replace(base(), end_week=22, playoff_teams=6)
    # Six teams: three rounds (the top two seeds' byes in the first), weeks 20 to 22.
    assert s.first_playoff_week == 20
    assert replace(s, playoff_teams=4).first_playoff_week == 21
    assert replace(s, playoff_teams=8).first_playoff_week == 20
    assert replace(s, playoff_teams=10).first_playoff_week == 19
    assert replace(s, playoff_teams=None).first_playoff_week is None
    assert replace(s, end_week=None).first_playoff_week is None


def pairs_part(week: int, pairs: list[tuple[int, int]]) -> Part:
    data = {"week": week, "matchups": [{"week": week, "teams": list(t)} for t in pairs]}
    return part(pairings_key(week), data)


def test_the_season_knows_each_weeks_pairs_and_the_weeks_left_to_read():
    weeks = tuple(
        Week(n, SEASON_START + timedelta(weeks=n - 1), SEASON_START + timedelta(weeks=n, days=-1))
        for n in range(1, 23)
    )
    parts = {
        "league": part("league", pages.parse_league_page(fixture("league.html"))),
        "calendar": part("calendar", Calendar(weeks).to_dict()),
        "pairings/2": pairs_part(2, [(4, 7), (1, 10)]),
        "pairings/3": pairs_part(3, []),
    }
    season = Season.from_parts(replace(base(), end_week=22, playoff_teams=6), parts)
    # This week's pairs are the league page's; another week's, its own page's.
    assert season.opponent_in(4, 1) == 10 and season.opponent_in(4, 2) == 7
    assert season.opponent_in(10, 2) == 1 and season.opponent_in(4, 3) is None
    # Left to read: the regular weeks after this one never read, or read with no pairs.
    assert season.first_playoff_week == 20
    assert season.weeks_unpaired(TODAY) == list(range(3, 20))
    # A private league has no settings part: its playoffs start at the first week read with no
    # pairs and none after it.
    read = {f"pairings/{w}": pairs_part(w, [(4, 7)]) for w in range(4, 20)}
    read |= {f"pairings/{w}": pairs_part(w, []) for w in (20, 21, 22)}
    private = Season.from_parts(base(), {**parts, **read})
    assert private.first_playoff_week == 20 and private.weeks_unpaired(TODAY) == [3]
    # Read for no week ahead: every week is left, the playoffs with them.
    bare = Season.from_parts(base(), {k: parts[k] for k in ("league", "calendar")})
    assert bare.first_playoff_week is None and bare.weeks_unpaired(TODAY) == list(range(2, 23))
    # Without the calendar given, nothing is known to read.
    no_calendar = Season.from_parts(base(), {"league": parts["league"]})
    assert no_calendar.weeks_unpaired(TODAY) == []
    assert no_calendar.weeks_unpaired(TODAY, Calendar(weeks)) == list(range(2, 23))


def test_a_page_of_available_players_upserts_into_the_pool():
    first = pages.parse_players_page(fixture("avail0.html"), TODAY)
    second = pages.parse_players_page(fixture("avail25.html"), TODAY)
    parts = merge_part({}, part("available", {**first, "upsert": True}, EXTENSION))
    parts = merge_part(
        parts, part("available", {**second, "upsert": True}, EXTENSION, NOW + timedelta(minutes=1))
    )
    rows = parts["available"].data["rows"]
    assert len(rows) == 35 and "upsert" not in parts["available"].data
    assert parts["available"].fetched_at == NOW + timedelta(minutes=1)
    # A public refresh replaces the whole pool.
    parts = merge_part(parts, part("available", second))
    assert len(parts["available"].data["rows"]) == 10


def test_a_page_in_another_view_keeps_the_ownership_it_does_not_show():
    """The players page's stat views (the default, the projections) carry % Ros but not % Start,
    adds or drops: posting one keeps what the Research view read, and takes the rest."""
    research = pages.parse_players_page(fixture("avail25.html"), TODAY)
    parts = merge_part({}, part("available", research))
    before = parts["available"].data["rows"][0]
    stats_view = {
        **before,
        "pct_rostered": before["pct_rostered"] + 2,
        **dict.fromkeys(
            ("pct_rostered_change", "pct_started", "pct_started_change", "adds", "drops")
        ),
    }
    parts = merge_part(parts, part("available", {"rows": [stats_view], "upsert": True}, EXTENSION))
    after = next(
        r
        for r in parts["available"].data["rows"]
        if r["player"]["yahoo_id"] == before["player"]["yahoo_id"]
    )
    assert after["pct_rostered"] == before["pct_rostered"] + 2
    for key in ("pct_started", "adds", "drops"):
        assert after[key] == before[key] is not None


def test_a_private_league_takes_its_name_and_week_from_the_league_page():
    parts = merge_part(
        {}, part("league", pages.parse_league_page(fixture("league.html")), EXTENSION)
    )
    s = Season.from_parts(base("100002"), parts)
    assert s.settings.name == "Test League 100001" and s.settings.current_week == 1
    assert s.opponent.team_id == 10


def test_a_player_from_a_page_keeps_its_own_status_over_the_pools():
    page = Player(1, "A. Name", "ATL", ("PG",), "Q", None)
    pool = Player(1, "Alpha Name", "ATL", ("PG", "SG"), "O", "Out", "knee")
    merged = page.with_pool(pool)
    assert (merged.name, merged.positions, merged.status) == ("Alpha Name", ("PG",), "Q")
    # The pool's words and note describe another status, so they are not carried over.
    assert merged.status_full is None and merged.note is None


# --------------------------------------------------------------------------- the routes
def write_folder(data_dir: Path, league: str, **extra) -> None:
    folder = data_dir / "leagues" / league
    folder.mkdir(parents=True, exist_ok=True)
    body = {
        "league_id": int(league),
        "scoring": "categories",
        "num_teams": 12,
        "roster": ROSTER,
        "categories": CATS,
        "my_team_id": 4,
        **extra,
    }
    (folder / "settings.json").write_text(json.dumps(body))


SEASON_START = date(2026, 10, 19)


def fake_week(day: date) -> int:
    """The fake league's matchup week for a date: Monday weeks, the seventeenth two weeks long."""
    n = (day - SEASON_START).days // 7 + 1
    return n if n <= 17 else n - 1


def matchup_page(teams: list[int]) -> str:
    """The fixture matchup page (Team 4 vs Team 10) as another pair's: the same totals."""
    html = fixture("matchup.html")
    if teams in ([], [4], [4, 10]):
        return html
    a, b = teams
    for old, new in ((4, "A"), (10, "B"), ("A", a), ("B", b)):
        html = re.sub(rf"(/nba/100001/|Team ){old}\b", rf"\g<1>{new}", html)
    return html


EMPTY_ROSTER = "<html><body><table><thead><tr><th>Pos</th><th>Players</th></tr></thead><tbody></tbody></table></body></html>"


class FakeYahoo:
    """Yahoo's and ESPN's public sources for league 100001, from the fixtures."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.settings = fixture("settings.json")
        #: Games on every day of the horizon (the two fixture days in turn), not just those two.
        self.every_day = False
        #: The weeks whose league page lists no pairs (the playoffs, not seeded yet).
        self.unpaired = set(range(20, 24))
        #: The weeks whose league page does not answer.
        self.down: set[int] = set()
        #: The settings page: the roster positions with three IL slots, daily lineups.
        self.settings_page = fixture("settings_page.html")
        #: A team page shown for a day, by (team, day), instead of the team's own page.
        self.lineups: dict[tuple[int, date], str] = {}
        #: A team's page today instead of its fixture.
        self.team_pages: dict[int, str] = {}
        #: The pairs whose matchup page names no teams even in the totals view.
        self.live: set[tuple[int, ...]] = set()

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if url.startswith(public.PUB_API + "/settings/"):
            return self.settings
        if url.startswith(public.PUB_API + "/players/"):
            return fixture("players.json")
        if url.startswith(schedule.SCOREBOARD.split("?")[0]):
            day = re.search(r"dates=(\d{8})", url).group(1)
            path = FIXTURES / f"espn_{day}.json"
            if not path.exists() and self.every_day:
                path = FIXTURES / f"espn_2026102{1 + int(day) % 2}.json"
            return path.read_text() if path.exists() else '{"events": []}'
        if url == ESPN_INJURIES_URL:
            return fixture("espn_injuries.json")
        if "/buzzindex?" in url:
            return fixture("buzz.html")
        kind, info = pages.page_kind(url)
        if kind == "league":
            week = info.get("matchup_week")
            if week in self.down:
                raise public.FetchError(f"{url}: HTTP 503")
            if week is not None:
                return week_page(week, paired=week not in self.unpaired)
            return fixture("league.html")
        if kind == "team":
            path = FIXTURES / f"team{info['team_id']}.html"
            page = self.team_pages.get(info["team_id"]) or (
                path.read_text() if path.exists() else None
            )
            if "date" in info:
                # A day's page: that day's week label, and the team's roster as its lineup.
                if (info["team_id"], info["date"]) in self.lineups:
                    return self.lineups[info["team_id"], info["date"]]
                label = f"Week {fake_week(info['date'])} stats may change"
                if page is not None:
                    return page.replace("Week 1 stats may change", label)
                return (
                    f"<html><body><p>{label} when Stat corrections are applied.</p></body></html>"
                )
            return page if page is not None else EMPTY_ROSTER
        if kind == "players":
            if info["view"] == pages.PROJECTION_VIEW:
                return fixture("avail_ps7.html")
            offset = int(re.search(r"count=(\d+)", url).group(1))
            return fixture("avail0.html" if offset == 0 else "avail25.html")
        if kind == "matchup":
            # As on 2026-10-22: the plain page is the Live tab, the totals view the page read.
            if "date=totals" not in url or tuple(info["teams"]) in self.live:
                return fixture("matchup_live.html")
            return matchup_page(info["teams"])
        if kind == "transactions":
            return fixture("transactions.html")
        if kind == "settings":
            return self.settings_page
        raise AssertionError(url)


@contextmanager
def season_client(tmp_path: Path) -> Iterator[TestClient]:
    """The app on a data folder with the public fixture league and a private one (team 7),
    Yahoo faked (``c.fake``) and the clock at :data:`NOW`."""
    write_folder(tmp_path, LEAGUE)
    write_folder(tmp_path, "100002", public=False, my_team_id=7)
    fake = FakeYahoo()
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: fake)
    app.state.seasons.clock = lambda: NOW
    with TestClient(app) as c:
        c.fake = fake  # type: ignore[attr-defined]
        c.data_dir = tmp_path  # type: ignore[attr-defined]
        yield c


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def test_a_refresh_reads_the_public_sources_and_serves_the_season(client):
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202, r.text
    assert r.json()["refresh"]["status"] == "done"
    v = client.get(f"/seasons/{LEAGUE}").json()
    assert v["name"] == "Test League 100001" and v["week"] == 1
    assert v["my_team"] == {
        "team_id": 4,
        "name": "Team 4",
        "record": "0-0-0",
        "rank": None,
        "points_for": None,
    }
    assert v["opponent"]["team_id"] == 10
    assert v["current_week"] == {"number": 1, "start": "2026-10-19", "end": "2026-10-25"}
    assert [w["number"] for w in v["weeks_ahead"]] == [1, 2, 3, 4] and v[
        "calendar_estimated"
    ] is False
    assert len(v["roster"]) == 13
    atl = next(x for x in v["roster"] if x["player"]["nba_team"] == "ATL")
    # The rest of week 1 from Oct 21: the fixture schedule has ATL on the 21st only.
    assert atl["games_left"] == 1
    assert len(v["available"]) == 35 and v["available"][0]["player"]["name"] == "Dillon Brooks"
    assert v["matchup"]["score"] == [5.0, 3.0]
    assert len(v["transactions"]) == 8
    assert v["sources"] == ["public"] and v["fetched"]["league"]["source"] == "public"
    # Paging stopped at the short page, in both views; the calendar was read once, one request
    # per Monday.
    fake = client.fake
    assert sum("/players?" in u and "S_PS7" not in u for u in fake.urls) == 2
    assert sum("/players?" in u and "S_PS7" in u for u in fake.urls) == 2
    dated = [
        u for u in fake.urls if "?date=" in u and "/buzzindex" not in u and "/matchup" not in u
    ]
    # The calendar, one request per Monday from Oct 19 to Mar 29, and my team page shown for
    # each day of this week (#107).
    week = [date(2026, 10, 19) + timedelta(days=n) for n in range(7)]
    lineups = [public.team_url(LEAGUE, 4, d) for d in week]
    assert len(dated) == 24 + 7 and all(u in dated for u in lineups)
    cal = json.loads((client.data_dir / "leagues/_shared/season/calendar.json").read_text())
    seventeen = next(w for w in cal["weeks"] if w["number"] == 17)
    assert (seventeen["start"], seventeen["end"]) == ("2027-02-08", "2027-02-21")
    # Stored with its time; a second refresh does not read the calendar again.
    folder = client.data_dir / "leagues" / LEAGUE / "season"
    assert (folder / "state.json").exists() and len(list((folder / "snapshots").iterdir())) == 1
    fake.urls.clear()
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    # No calendar again; the days before today's lineup were read once, today's and later
    # days' are read every time.
    assert [u for u in fake.urls if "?date=" in u and "/matchup" not in u] == lineups[2:]
    assert len(list((folder / "snapshots").iterdir())) == 2


def test_a_refresh_reads_every_pairs_matchup_page_mine_first(client):
    steps: list[tuple[str, int, int]] = []
    parts = public.refresh_parts(
        LEAGUE, base(), client.fake, TODAY, progress=lambda *step: steps.append(step)
    )
    read = [u for u in client.fake.urls if "/matchup?" in u]
    assert len(read) == 6 and read[0].endswith("mid1=4&mid2=10")
    assert all("?date=totals&" in u for u in read)
    assert [k for k in (p.key for p in parts) if k.startswith("matchup/")][:2] == [
        "matchup/1/4-10",
        "matchup/1/1-2",
    ]
    assert [w for w, _, _ in steps if "matchup" in w] == [
        "my matchup",
        "matchup 1-2",
        "matchup 3-11",
        "matchup 5-9",
        "matchup 6-8",
        "matchup 7-12",
    ]
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    rows = {tuple(m["teams"]): m for m in client.get(f"/seasons/{LEAGUE}").json()["matchups"]}
    assert len(rows) == 6
    assert set(rows[(7, 12)]["totals"]) == {"7", "12"}


def test_a_matchup_page_without_its_teams_skips_that_pair_and_the_refresh_lands(client):
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    folder = client.data_dir / "leagues" / LEAGUE / "season"
    before = json.loads((folder / "state.json").read_text())["parts"]["matchup/1/7-12"]
    client.fake.live = {(7, 12), (3, 11)}
    later = NOW + timedelta(minutes=5)
    client.app.state.seasons.clock = lambda: later
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    job = r.json()["refresh"]
    assert job["status"] == "done", job
    assert job["warnings"]["matchups"] == (
        "2 of 6 pairs skipped: 3-11: the matchup page does not name two teams;"
        " 7-12: the matchup page does not name two teams"
    )
    # The pairs read are new; a skipped pair keeps its last read.
    parts = json.loads((folder / "state.json").read_text())["parts"]
    assert parts["matchup/1/7-12"] == before
    assert parts["matchup/1/4-10"]["fetched_at"] == later.isoformat() > before["fetched_at"]
    rows = {tuple(m["teams"]) for m in client.get(f"/seasons/{LEAGUE}").json()["matchups"]}
    assert len(rows) == 6


def weeks_read(client) -> list[int]:
    found = (re.search(r"matchup_week=(\d+)", u) for u in client.fake.urls)
    return sorted(int(m.group(1)) for m in found if m)


def test_a_refresh_reads_each_regular_week_ahead_once_and_an_empty_one_again(client):
    client.fake.unpaired |= {5}
    client.fake.down = {7}
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202, r.text
    # The regular weeks after this one; the playoffs (weeks 20 on, six teams) are the field's.
    assert weeks_read(client) == list(range(2, 20))
    season = client.app.state.seasons.season(LEAGUE)
    assert season.opponent_in(4, 2) == 10 and season.opponent_in(4, 5) is None
    # A page that did not answer is left out, not read as a week without pairs.
    assert 7 not in season.pairings
    client.fake.urls.clear()
    client.fake.unpaired -= {5}
    client.fake.down = set()
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert weeks_read(client) == [5, 7]
    season = client.app.state.seasons.season(LEAGUE)
    assert season.opponent_in(4, 5) == season.opponent_in(4, 7) == 10


def test_the_leagues_list_shows_each_folders_week_record_and_opponent(client):
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    rows = {r["league"]: r for r in client.get("/seasons").json()}
    assert set(rows) == {LEAGUE, "100002"}
    mine = rows[LEAGUE]
    assert (mine["name"], mine["week"], mine["my_team"]["record"], mine["opponent"]["name"]) == (
        "Test League 100001",
        1,
        "0-0-0",
        "Team 10",
    )
    assert mine["has_snapshot"] and mine["updated_at"] and mine["refresh"]["status"] == "done"
    private = rows["100002"]
    assert (
        private["public"] is False and private["has_snapshot"] is False and private["name"] is None
    )


def test_a_private_league_refresh_says_to_use_the_extension(client):
    r = client.post("/seasons/100002/refresh", params={"wait": True})
    assert r.status_code == 409 and "extension" in r.json()["detail"]
    assert client.fake.urls == []
    assert client.get("/seasons/9").status_code == 404


def test_a_private_leagues_pages_posted_by_the_extension_round_trip(client):
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    r = client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {"url": site, "html": fixture("league.html")},
                {"url": site + "/7", "html": fixture("team4.html")},
                {"url": site + "/players?status=A&pos=P&stat1=R_O", "html": fixture("avail0.html")},
                {
                    "url": site + "/matchup?week=1&mid1=7&mid2=12",
                    "html": fixture("matchup_points.html"),
                },
                {"url": site + "/transactions", "html": fixture("transactions.html")},
                # Another league's page is refused, not stored under this one.
                {
                    "url": "https://basketball.fantasysports.yahoo.com/nba/100001/4",
                    "html": fixture("team4.html"),
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == ["league", "roster/7", "available", "matchup/1/7-12", "transactions"]
    assert [s["url"].endswith("/100001/4") for s in body["skipped"]] == [True]
    assert body["season"]["opponent"]["team_id"] == 12 and body["season"]["sources"] == [
        "extension"
    ]
    v = client.get("/seasons/100002").json()
    assert (
        v["name"] == "Test League 100001" and len(v["roster"]) == 13 and len(v["available"]) == 25
    )
    assert v["matchup"]["lines"]["Live Proj"] == [1065.53, 943.58]
    # The next page of the players list adds to the pool; a parsed part goes in as it is.
    r = client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {"url": site + "/players?status=A&count=25", "html": fixture("avail25.html")}
            ],
            "parts": [
                {"key": "roster/12", "data": {"team_id": 12, "name": "Team 12", "spots": []}},
                {"key": "bogus", "data": {}},
            ],
        },
    )
    assert r.json()["accepted"] == ["available", "roster/12"] and r.json()["skipped"] == [
        {"key": "bogus", "reason": "unknown part"}
    ]
    assert len(client.get("/seasons/100002").json()["available"]) == 35
    # A new app on the same folder serves the same season (it is on disk, not in memory).
    again = create_app(SessionStore(), data_dir=client.data_dir, season_fetch=lambda: client.fake)
    again.state.seasons.clock = lambda: NOW
    with TestClient(again) as c2:
        assert len(c2.get("/seasons/100002").json()["available"]) == 35
    wait_for_job(client, "100002")


def wait_for_job(client, league: str) -> season_api.RefreshJob:
    """The league's background job, once it has finished."""
    job = client.app.state.seasons.jobs[league]
    deadline = time.monotonic() + 10
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    assert job.status == "done", job.error
    return job


def test_a_private_leagues_snapshot_brings_in_the_calendar_and_the_schedule(client):
    """No page of a private league answers without a sign-in, so its week calendar comes from
    the cache a public league's refresh writes, and the NBA schedule from ESPN, in the
    background after the extension's first post."""
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    assert client.post(f"/seasons/{LEAGUE}/refresh?wait=true").status_code == 202
    probes = len(client.fake.urls)
    r = client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {"url": site, "html": fixture("league.html")},
                {"url": site + "/7", "html": fixture("team4.html")},
            ]
        },
    )
    assert r.status_code == 200, r.text
    wait_for_job(client, "100002")
    v = client.get("/seasons/100002").json()
    assert v["current_week"] == {"number": 1, "start": "2026-10-19", "end": "2026-10-25"}
    assert v["calendar_estimated"] is False and v["sources"] == ["extension", "public"]
    assert all(row["games_left"] is not None for row in v["roster"])
    # Only ESPN was read for it: nothing of Yahoo's, and no calendar probe.
    assert all("espn" in url for url in client.fake.urls[probes:])
    # A second post while the schedule is fresh starts nothing.
    client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": site + "/7", "html": fixture("team4.html")}]},
    )
    assert client.app.state.seasons.start_extras("100002") is None


def test_a_signed_in_matchup_page_names_its_own_teams_not_the_navigations():
    """A signed-in page's navigation links to my team (7) before the matchup's two: the teams
    are the header's, else the totals table's, never the page's chrome."""
    html = fixture("matchup_signed_in.html")
    d = pages.parse_matchup_page(html)
    assert d["teams"] == [1, 2] and set(d["totals"]) == {"1", "2"} and d["score"] == [5.0, 3.0]
    # Without the header, the totals table's rows name them.
    bare = re.sub(r"<section id='matchup-header'.*?</section>", "", html, flags=re.DOTALL)
    assert pages.parse_matchup_page(bare)["teams"] == [1, 2]
    # The pair the URL asks for must be on the page (``mid1`` alone names one team).
    assert pages.parse_matchup_page(html, pair=[2, 1])["teams"] == [1, 2]
    assert pages.parse_matchup_page(html, pair=[1])["teams"] == [1, 2]
    with pytest.raises(pages.PageError, match="shows teams 1 and 2; its URL asks for 1 and 7"):
        pages.parse_matchup_page(html, pair=[1, 7])


def test_the_live_matchup_page_names_no_teams_and_the_totals_view_is_read():
    """While games are live the plain matchup page is Yahoo's Live tab, its teams and totals
    loaded by script: nothing to read. The URL the API builds asks for the totals view."""
    with pytest.raises(pages.PageError, match="does not name two teams"):
        pages.parse_matchup_page(fixture("matchup_live.html"), 1)
    assert public.matchup_url(LEAGUE, 1, [7, 12]) == (
        f"{public.SITE}/{LEAGUE}/matchup?date=totals&week=1&mid1=7&mid2=12"
    )
    assert public.matchup_url(LEAGUE, 1, [7]).endswith("matchup?date=totals&week=1&mid1=7")
    assert pages.page_kind(public.matchup_url(LEAGUE, 3, [4, 10])) == (
        "matchup",
        {"league": LEAGUE, "week": 3, "teams": [4, 10]},
    )


def test_a_matchup_page_is_stored_as_the_pair_its_url_asks_for_or_skipped(client):
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    client.post(
        "/seasons/100002/snapshot", json={"pages": [{"url": site, "html": fixture("league.html")}]}
    )
    html = fixture("matchup_signed_in.html")
    r = client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": f"{site}/matchup?week=1&mid1=1&mid2=2", "html": html}]},
    )
    assert r.json()["accepted"] == ["matchup/1/1-2"]
    r = client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": f"{site}/matchup?week=1&mid1=1&mid2=5", "html": html}]},
    )
    assert r.json()["accepted"] == []
    assert "its URL asks for 1 and 5" in r.json()["skipped"][0]["reason"]
    v = client.get("/seasons/100002").json()
    assert v["opponent"]["team_id"] == 12


def test_a_matchup_part_whose_teams_are_not_a_pair_of_its_week_is_not_read_and_is_dropped(client):
    """Pages read before the parser took its teams from the header were stored as my team
    against the matchup's first team. The league page's pairs expose them: the season reads none
    of them and the next save drops them; a week whose pairs were never read keeps its pages."""
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    client.post(
        "/seasons/100002/snapshot", json={"pages": [{"url": site, "html": fixture("league.html")}]}
    )
    state = client.data_dir / "leagues" / "100002" / "season" / "state.json"
    body = json.loads(state.read_text())
    page = pages.parse_matchup_page(fixture("matchup_signed_in.html"))
    for key, week, teams in (("matchup/1/1-7", 1, [7, 1]), ("matchup/2/3-7", 2, [7, 3])):
        data = page | {"week": week, "teams": teams}
        body["parts"][key] = Part(key, NOW, EXTENSION, data).to_dict()
    state.write_text(json.dumps(body))
    parts = season_api.load_parts(client.data_dir, "100002")
    assert unpaired_matchups(parts) == {"matchup/1/1-7"}
    # Read as it was, team 7's first matchup (7 vs 1) made team 1 this week's opponent.
    v = client.get("/seasons/100002").json()
    assert v["opponent"]["team_id"] == 12
    assert [7, 1] not in [m["teams"] for m in v["matchups"]]
    # The next save, any post, drops it; the snapshot files keep what was received.
    client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": site + "/7", "html": fixture("team4.html")}]},
    )
    kept = json.loads(state.read_text())["parts"]
    assert "matchup/1/1-7" not in kept and "matchup/2/3-7" in kept


def test_another_weeks_league_page_is_its_pairings_and_moves_nothing(client):
    """The league page shown for another week is that week's pairs, stored on its own: it
    never becomes the league part, so the standings and the current week stay this week's."""
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    client.post(
        "/seasons/100002/snapshot", json={"pages": [{"url": site, "html": fixture("league.html")}]}
    )
    r = client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": site + "?matchup_week=2", "html": week_page(2)}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == ["pairings/2"]
    v = client.get("/seasons/100002").json()
    assert v["week"] == 1 and v["opponent"]["team_id"] == 12
    assert {m["week"] for m in v["matchups"]} == {1}
    stored = season_api.load_parts(client.data_dir, "100002")
    assert stored["pairings/2"].data["week"] == 2
    assert {tuple(m["teams"]) for m in stored["pairings/2"].data["matchups"]} == {
        (1, 2),
        (3, 11),
        (4, 10),
        (5, 9),
        (6, 8),
        (7, 12),
    }
    assert stored["league"].data["week"] == 1
    wait_for_job(client, "100002")


def test_a_matchup_page_read_before_the_league_page_keeps_the_newer_score():
    league = pages.parse_league_page(fixture("league.html"))
    league["matchups"] = [
        m | {"score": [6.0, 3.0]} if m["teams"] == [4, 10] else m for m in league["matchups"]
    ]
    matchup = pages.parse_matchup_page(fixture("matchup.html"))
    early = NOW - timedelta(hours=2)
    parts = merge_part(
        merge_part({}, part("league", league)), part("matchup/1/4-10", matchup, at=early)
    )
    s = Season.from_parts(base(), parts)
    assert s.matchup_of(4).score == (6.0, 3.0) and s.matchup_of(4).totals[4]["FG%"] == ".484"
    # Read after it, the matchup page's own score stands.
    parts = merge_part(parts, part("matchup/1/4-10", matchup, at=NOW + timedelta(hours=1)))
    assert Season.from_parts(base(), parts).matchup_of(4).score == (5.0, 3.0)


def test_a_snapshot_that_does_not_read_is_refused(client):
    r = client.post(
        "/seasons/100002/snapshot", json={"parts": [{"key": "roster/3", "data": {"spots": []}}]}
    )
    assert r.status_code == 400
    assert not (client.data_dir / "leagues/100002/season/state.json").exists()


def test_season_service_reports_a_failed_refresh(tmp_path):
    write_folder(tmp_path, LEAGUE)

    def broken(url: str) -> str:
        raise public.FetchError(f"{url}: HTTP 503")

    service = season_api.SeasonService(tmp_path, lambda: broken, clock=lambda: NOW)
    job = service.run_refresh(season_api.RefreshJob(LEAGUE))
    assert job.status == "failed" and "503" in job.error and job.finished_at is not None
    assert not (tmp_path / "leagues" / LEAGUE / "season" / "state.json").exists()


# --------------------------------------------------------------------------- the week projection
CSV_HEAD = (
    "player_id,last_name,first_name,games,minutes,field_goals_attempted,field_goals,"
    "free_throws_attempted,free_throws,threes,threes_attempted,offensive_rebounds,"
    "defensive_rebounds,assists,blocks,steals,turnovers,fouls,technicals,double_doubles,"
    "triple_doubles,comments"
)


def projection_csv(
    path: Path,
    names: list[str],
    games: int = 70,
    star: str | None = None,
    scale: dict[str, float] | None = None,
) -> None:
    """A projection file in the export's CSV layout with made-up numbers: per game 5/10 from the
    field, 1.6/2 at the line, one three, five rebounds, three assists, half a block, a steal and
    two turnovers (12.6 points); ``star`` makes 10/18 (22.6 points); ``scale`` multiplies a
    player's whole line."""
    lines = [CSV_HEAD]
    for i, name in enumerate(names):
        first, _, last = name.partition(" ")
        fgm, fga = (10 * games, 18 * games) if name == star else (5 * games, 10 * games)
        g, x = games, (scale or {}).get(name, 1.0)
        lines.append(
            f"{i},{last},{first},{g},{30 * g},{fga * x:.1f},{fgm * x:.1f},{2 * g * x:.1f},"
            f"{1.6 * g * x:.1f},{g * x:.1f},{3 * g * x:.1f},{g * x:.1f},{4 * g * x:.1f},"
            f"{3 * g * x:.1f},{0.5 * g * x:.1f},{g * x:.1f},{2 * g * x:.1f},{2 * g},0,0,0,"
        )
    path.write_text("\n".join(lines) + "\n")


def fixture_names() -> list[str]:
    out = []
    for team in (4, 10):
        d = pages.parse_team_page(fixture(f"team{team}.html"), team)
        out += [s["player"]["name"] for s in d["spots"]]
    return out + ["Dillon Brooks"]


def test_the_week_projection_gives_games_rates_and_my_matchups_odds(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    w = v["week_projection"]
    assert w["systems"]["bbm"]["file"] == "bbm_projections_2026-10-21.csv"
    assert w["systems"]["bbm"]["players"] == 27
    assert w["systems"]["yahoo"]["players"] == 8  # ten rows, two with no games (O and NA)
    assert [x["number"] for x in w["weeks"]] == [1, 2, 3, 4]
    assert w["weeks"][0]["from"] == "2026-10-21" and w["weeks"][0]["games_from"] == "schedule"
    by_name = {s["player"]["name"]: s["player"] for s in v["roster"]}
    durant = w["players"][str(by_name["Kevin Durant"]["yahoo_id"])]
    assert durant["bbm"]["pts"] == 22.6 and durant["bbm"]["fga"] == 18
    assert len(durant["games"]) == 4 and len(durant["started"]) == 4
    days = [date(2026, 10, 21), date(2026, 10, 22)]
    playing = {
        d: set(schedule.teams_playing(json.loads(fixture(f"espn_{d:%Y%m%d}.json")))) for d in days
    }
    assert durant["games"][0] == sum("HOU" in playing[d] for d in days)
    # Nesmith is out (O): no games this week.
    assert w["players"][str(by_name["Aaron Nesmith"]["yahoo_id"])]["games"][0] == 0
    brooks = next(a for a in v["available"] if a["player"]["name"] == "Dillon Brooks")["player"]
    row = w["players"][str(brooks["yahoo_id"])]
    assert row["yahoo"]["pts"] == round(45.4 / 3, 4) and row["bbm"]["pts"] == 12.6
    assert row["started"] is None and len(row["games"]) == 4
    m = w["matchup"]
    assert m["teams"] == [4, 10] and m["system"] == "bbm" and m["from"] == "2026-10-21"
    assert (
        m["so_far"]["4"]["fgm"] == 15
        and m["so_far"]["4"]["fga"] == 31
        and m["so_far"]["4"]["pts"] == 42
    )
    odds = {o["cat"]: o for o in m["odds"]}
    assert list(odds) == CATS
    assert odds["pts"]["mine"] == pytest.approx(42 + m["rest"]["4"]["pts"])
    assert odds["fg_pct"]["mine"] == pytest.approx(
        (15 + m["rest"]["4"]["fgm"]) / (31 + m["rest"]["4"]["fga"])
    )
    assert all(0 <= o["p_win"] <= 1 for o in m["odds"])
    assert m["expected"] == pytest.approx(sum(o["p_win"] for o in m["odds"]), abs=1e-3)


def test_a_refresh_after_the_first_tip_off_projects_the_week_from_tomorrow(client):
    # 19:30 ET on a game day, whatever the real clock says (#121): every part is stamped with
    # the service's clock, so the week so far counts today's games and the rest starts tomorrow.
    evening = datetime(2026, 10, 21, 23, 30, tzinfo=UTC)
    client.app.state.seasons.clock = lambda: evening
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    folder = client.data_dir / "leagues" / LEAGUE / "season"
    parts = json.loads((folder / "state.json").read_text())["parts"]
    assert {"calendar", "schedule", "matchup/1/4-10"} <= set(parts)
    assert {p["fetched_at"] for p in parts.values()} == {evening.isoformat()}
    assert {r["seen_at"] for r in parts["available"]["data"]["rows"]} == {evening.isoformat()}
    w = client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    assert w["weeks"][0]["from"] == "2026-10-22" and w["matchup"]["from"] == "2026-10-22"


def test_a_weekly_export_gives_the_weeks_games(client):
    names = fixture_names()
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", names)
    week = client.data_dir / "bbm_week_this_20261021-1400.csv"
    projection_csv(week, names, games=1)
    week.with_suffix(".json").write_text(json.dumps({"start": "2026-10-21", "end": "2026-10-25"}))
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    w = v["week_projection"]
    assert w["weeks"][0]["games_from"] == "bbm" and w["weeks"][1]["games_from"] == "schedule"
    by_name = {s["player"]["name"]: s["player"] for s in v["roster"]}
    nesmith = by_name["Aaron Nesmith"]
    playing = schedule.teams_playing(
        json.loads(fixture("espn_20261021.json"))
    ) + schedule.teams_playing(json.loads(fixture("espn_20261022.json")))
    # The export's one game overrides the out rule, within the games his team has.
    assert w["players"][str(nesmith["yahoo_id"])]["games"][0] == min(1, playing.count("IND"))
    # An export for another span is not used.
    week.with_suffix(".json").write_text(json.dumps({"start": "2026-10-20", "end": "2026-10-25"}))
    w = client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    assert w["weeks"][0]["games_from"] == "schedule"


def test_the_week_so_far_and_where_the_rest_begins():
    m = Matchup.from_dict(pages.parse_matchup_page(fixture("matchup.html")))
    mine = season_week.so_far(m, 10, points=False)
    assert mine == {
        "fgm": 12,
        "fga": 23,
        "ftm": 7,
        "fta": 9,
        "threes": 0,
        "pts": 31,
        "reb": 13,
        "ast": 2,
        "stl": 2,
        "blk": 1,
        "tov": 2,
    }
    pts = Matchup.from_dict(pages.parse_matchup_page(fixture("matchup_points.html")))
    assert season_week.so_far(pts, 12, points=True) == {"fpts": 92.7}
    # Read at 2 pm Eastern: today's games are still to come; at 9 pm they have begun.
    assert season_week.first_day(datetime(2026, 10, 21, 18, 0, tzinfo=UTC), TODAY) == TODAY
    assert season_week.first_day(datetime(2026, 10, 22, 1, 0, tzinfo=UTC), TODAY) == date(
        2026, 10, 22
    )
    assert season_week.first_day(None, TODAY) == TODAY


def test_a_projection_page_posted_by_the_extension_feeds_yahoos_system(client):
    site = "https://basketball.fantasysports.yahoo.com/nba/100002"
    r = client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {
                    "url": site + "/players?status=A&pos=P&stat1=S_PS7&count=0",
                    "html": fixture("avail_ps7.html"),
                }
            ]
        },
    )
    assert r.json()["accepted"] == ["available", "yahoo_week"]
    parts = season_api.load_parts(client.data_dir, "100002")
    rows = parts["yahoo_week"].data["rows"]
    assert len(rows) == 10 and "upsert" not in parts["yahoo_week"].data
    # A second page upserts by player.
    client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {
                    "url": site + "/players?status=A&pos=P&stat1=S_PS7&count=25",
                    "html": fixture("avail_ps7.html"),
                }
            ]
        },
    )
    assert len(season_api.load_parts(client.data_dir, "100002")["yahoo_week"].data["rows"]) == 10


def test_the_projection_page_parser():
    rows = pages.parse_projection_page(fixture("avail_ps7.html"))["rows"]
    assert len(rows) == 10
    brooks = rows[0]
    assert brooks["player"]["name"] == "Dillon Brooks" and brooks["gp"] == 3.0
    assert (brooks["fgm"], brooks["fga"], brooks["ftm"], brooks["fta"]) == (16.6, 38.8, 5.7, 6.9)
    assert (brooks["threes"], brooks["pts"], brooks["reb"], brooks["ast"]) == (6.5, 45.4, 11.3, 5.0)
    assert (brooks["stl"], brooks["blk"], brooks["tov"]) == (2.9, 0.5, 4.3)
    # An out player's projection: no games.
    assert rows[1]["player"]["status"] == "O" and rows[1]["gp"] == 0.0
    # "-": no projection at all (a player not active) reads as no games.
    assert rows[4]["player"]["status"] == "NA" and rows[4]["gp"] == 0.0


# --------------------------------------------------------------------------- moves (#94)
def test_the_moves_route_values_every_candidate_and_recommends_a_set(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    r = client.get(f"/seasons/{LEAGUE}/moves")
    assert r.status_code == 200, r.text
    m = r.json()
    # The rest of the week starts where the matchup card's does, and from the same value.
    assert m["horizons"]["week"]["from"] == "2026-10-21"
    assert m["horizons"]["week"]["base"] == pytest.approx(
        v["week_projection"]["matchup"]["expected"], abs=1e-3
    )
    assert m["horizons"]["week"]["label"] == "rest of week 1 against Team 10"
    assert m["horizons"]["three"]["weeks"] == [2, 3, 4]
    assert m["system"]["key"] == "bbm"
    # The weekly limit, net of my adds this week; the page does not reach back past Monday.
    assert m["adds"]["limit"] == v["settings"]["max_weekly_adds"]
    assert m["adds"]["complete"] is False
    assert m["adds"]["left"] == m["adds"]["limit"] - m["adds"]["used"]
    brooks = next(a for a in v["available"] if a["player"]["name"] == "Dillon Brooks")
    row = m["candidates"][str(brooks["player"]["yahoo_id"])]
    assert row["from"] == brooks["clears"]
    best = row["week"]
    by_name = {s["player"]["name"]: s["player"]["yahoo_id"] for s in v["roster"]}
    # None: my out bench player can go to an open IL slot (the league's three, #124).
    assert best["drop"] is None or best["drop"] in by_name.values()
    # Only the candidates with a projection are valued.
    assert len(m["candidates"]) + m["unprojected"] == len(v["available"])
    # Yahoo's projection is a second system for the same table: it projects more of the
    # available players, and two of them are worth a move this week.
    y = client.get(f"/seasons/{LEAGUE}/moves", params={"system": "yahoo"}).json()
    assert y["system"]["key"] == "yahoo" and "fallback" in y["system"]
    assert len(y["candidates"]) > len(m["candidates"])
    assert len(y["recommended"]["week"]["moves"]) == 2
    for payload in (m, y):
        for key in ("week", "three"):
            rec = payload["recommended"][key]
            assert set(rec["gain"]) == {"week", "three"}
            assert len(rec["moves"]) <= payload["adds"]["left"]
            for move in rec["moves"]:
                assert move["marginal"][key] > payload["search"]["min_gain"]
                assert move["price_without"] >= 0
                assert move["add"] not in {x["add"] for x in move["instead_without"]}
    assert client.get(f"/seasons/{LEAGUE}/moves", params={"system": "espn"}).status_code == 422


def test_the_move_drawer_details_one_add_with_every_drop(client):
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    brooks = next(a for a in v["available"] if a["player"]["name"] == "Dillon Brooks")
    pid = brooks["player"]["yahoo_id"]
    row = m["candidates"][str(pid)]["three"]
    drop = row["drop"] or row["next_drop"]
    d = client.get(f"/seasons/{LEAGUE}/moves/{pid}", params={"drop": drop}).json()
    assert d["add"] == pid and d["drop"] == drop and d["from"] == brooks["clears"]
    week = d["horizons"]["week"]
    assert week["before"] == m["horizons"]["week"]["base"]
    assert week["gain"] == next(x["week"] for x in d["drops"] if x["drop"] == drop)
    assert week["after"] - week["before"] == pytest.approx(week["gain"], abs=2e-3)
    assert set(week["cats"]["before"]) == set(CATS)
    # This week's categories carry both finals; the three weeks' only the wins.
    assert {"wins", "mine", "theirs"} <= set(week["cats"]["after"]["pts"])
    assert set(d["horizons"]["three"]["cats"]["after"]["pts"]) == {"wins"}
    # Every active player is a drop, best three-week gain first.
    assert len(d["drops"]) >= len([s for s in v["roster"] if s["slot"] not in ("IL", "IL+", "NA")])
    assert [x["three"] for x in d["drops"]] == sorted(
        (x["three"] for x in d["drops"]), reverse=True
    )
    assert client.get(f"/seasons/{LEAGUE}/moves/1").status_code == 404


def test_an_out_player_of_mine_is_held_out_until_espns_later_return_date(tmp_path):
    path = season_flags.injuries_path(tmp_path)
    path.parent.mkdir(parents=True)

    def listed(key, name, team, status, returns):
        return {
            "key": key,
            "name": name,
            "team": team,
            "position": "C",
            "status": status,
            "returns": returns,
        }

    players = [
        listed("espn:1", "Hurt One", "MIN", "Out", "2026-11-04"),
        listed("espn:2", "Day Two", "SAS", "Day-To-Day", "2026-10-23"),
        listed("espn:3", "No Date", "NYK", "Out", None),
    ]
    path.write_text(json.dumps({"read_at": NOW.isoformat(), "players": players}))
    members = [
        (1, Player(1, "Hurt One", "MIN", ("C",), status="O")),
        (2, Player(2, "Day Two", "SAS", ("C",), status="GTD")),
        (3, Player(3, "No Date", "NYK", ("C",), status="O")),
        (4, Player(4, "Hurt One", "LAL", ("C",), status="O")),
    ]
    # O players only, by name and team; no date, no hold.
    assert season_moves.espn_returns(tmp_path, members) == {1: date(2026, 11, 4)}
    assert season_moves.espn_returns(tmp_path / "none", members) == {}


def test_moves_need_a_season_of_my_team(client):
    assert client.get("/seasons/100002/moves").status_code == 409
    assert client.get("/seasons/999999/moves").status_code == 404


# --------------------------------------------------------------------------- matchup view (#116)
def test_the_matchup_route_scores_my_week_and_what_each_player_adds(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    r = client.get(f"/seasons/{LEAGUE}/matchup")
    assert r.status_code == 200, r.text
    m = r.json()
    assert (m["week"], m["teams"], m["system"]["key"]) == (1, [4, 10], "bbm")
    assert (m["start"], m["end"], m["from"], m["days"]) == (
        "2026-10-19",
        "2026-10-25",
        "2026-10-21",
        5,
    )
    # Yahoo's count so far, mine first, and the one category level.
    assert m["score"] == [5.0, 3.0] and m["tied"] == 1 and m["rosters_read"] == [True, True]
    # The Matchup card's finals and odds: the same model.
    card = v["week_projection"]["matchup"]
    cats = {c["cat"]: c for c in m["cats"]}
    assert list(cats) == CATS
    for o in card["odds"]:
        assert cats[o["cat"]]["p_win"] == pytest.approx(o["p_win"], abs=1e-3)
        assert cats[o["cat"]]["mine"] == pytest.approx(o["mine"], abs=1e-3)
    assert cats["pts"]["so_far"] == [42.0, 31.0]
    assert cats["fg_pct"]["so_far"][0] == pytest.approx(15 / 31, abs=1e-4)
    assert m["expected"] == pytest.approx(sum(c["p_win"] for c in m["cats"]), abs=1e-3)
    assert m["expected"] == pytest.approx(card["expected"], abs=1e-3)
    odds = [wk.CategoryOdds(c["cat"], None, None, 1.0, c["p_win"]) for c in m["cats"]]
    assert m["win"] == pytest.approx(wk.matchup_won(odds), abs=1e-3) and 0 < m["win"] < 1
    # Both rosters, each player once; with games first, the larger Matchup first.
    mine, theirs = m["players"]["mine"], m["players"]["theirs"]
    assert {x["player"] for x in mine} == {s["player"]["yahoo_id"] for s in v["roster"]}
    team10 = pages.parse_team_page(fixture("team10.html"), 10)["spots"]
    assert {x["player"] for x in theirs} == {s["player"]["yahoo_id"] for s in team10}
    for rows in (mine, theirs):
        keys = [(x["games"] == 0, -x["matchup"]) for x in rows]
        assert keys == sorted(keys)
        # No start left adds nothing.
        assert all(x["cats"] == 0 and x["matchup"] == 0 for x in rows if not x["started"])
    by_name = {s["player"]["name"]: s["player"]["yahoo_id"] for s in v["roster"]}
    durant = next(x for x in mine if x["player"] == by_name["Kevin Durant"])
    assert durant == mine[0] and durant["per_game"]["pts"] == 22.6 and durant["slot"] == "SG"
    nesmith = next(x for x in mine if x["player"] == by_name["Aaron Nesmith"])
    assert nesmith["games"] == 0 and nesmith["matchup"] == 0 and mine[-1]["games"] == 0
    # His contribution is the week without him from the first day on (the drop path).
    built = client.app.state.seasons._built(LEAGUE, "bbm")
    span = built.problem.horizons["week"][0]
    week = mv.project_mine(built.problem, span, gone={durant["player"]: span.days[0]})
    without = wk.odds_of(
        wk.finals(week, span.so_far, CATS),
        wk.finals(span.opponents[0], span.so_far_theirs[0], CATS),
        CATS,
    )
    assert durant["cats"] == pytest.approx(m["expected"] - wk.expected_won(without), abs=1e-3)
    assert durant["matchup"] == pytest.approx(m["win"] - wk.matchup_won(without), abs=1e-3)
    assert durant["cats"] > mine[1]["cats"] > 0
    # Theirs are what each adds for them: my odds without him less with him.
    assert theirs[0]["cats"] > 0 and theirs[0]["matchup"] > 0
    y = client.get(f"/seasons/{LEAGUE}/matchup", params={"system": "yahoo"})
    assert y.status_code == 200 and y.json()["system"]["key"] == "yahoo"
    assert client.get(f"/seasons/{LEAGUE}/matchup", params={"system": "espn"}).status_code == 422


def test_the_matchup_route_needs_a_season_with_my_matchup(client):
    assert client.get("/seasons/100002/matchup").status_code == 409
    assert client.get("/seasons/999999/matchup").status_code == 404


# --------------------------------------------------------------------------- landing grid (#108)
def test_the_outlook_gives_every_week_left_against_its_opponent_or_the_field(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.fake.every_day = True
    client.fake.unpaired |= {5}
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    r = client.get(f"/seasons/{LEAGUE}/outlook")
    assert r.status_code == 200, r.text
    o = r.json()
    weeks = o["weeks"]
    # The fake calendar: 23 weeks, the seventeenth two weeks long.
    assert [w["week"] for w in weeks] == list(range(1, 24)) and weeks[16]["days"] == 14
    assert (o["team"], o["first_playoff_week"], o["system"]["key"]) == (4, 20, "bbm")
    # This week is the Matchup view's: its opponent, score, days and odds.
    m = client.get(f"/seasons/{LEAGUE}/matchup").json()
    this = weeks[0]
    assert (this["this_week"], this["opponent"], this["score"]) == (True, 10, [5.0, 3.0])
    assert this["tied"] == m["tied"] == 1
    assert (this["from"], this["days"]) == ("2026-10-21", 5)
    assert this["win"] == pytest.approx(m["win"], abs=1e-4)
    assert this["expected"] == pytest.approx(m["expected"], abs=1e-4)
    assert [c["p_win"] for c in this["cats"]] == pytest.approx(
        [c["p_win"] for c in m["cats"]], abs=1e-4
    )
    # A later regular week: the pairs its own page lists (the fixture's: team 10 every week).
    nxt = weeks[1]
    assert (nxt["opponent"], nxt["field"], nxt["from"], nxt["days"]) == (10, None, "2026-10-26", 7)
    assert not nxt["this_week"] and nxt["scheduled"] and nxt["games"] > 0
    assert nxt["score"] is None
    # A week whose page listed no pairs, and the playoffs: the field, every other roster read.
    others = [t for t in client.app.state.seasons.season(LEAGUE).rosters if t != 4]
    for w in [weeks[4], *weeks[19:]]:
        assert w["opponent"] is None and w["field"] == len(others) and w["win"] is not None
    assert [w["playoffs"] for w in weeks] == [False] * 19 + [True] * 4
    # The summary is the regular weeks': the wins expected, and the lean of each named week.
    s, regular = o["summary"], weeks[:19]
    assert (s["weeks"], s["field"], s["unread"]) == (19, 1, 0)
    assert s["expected_wins"] == pytest.approx(sum(w["win"] for w in regular), abs=0.01)
    named = [w["win"] for w in regular if w["opponent"] is not None]
    assert s["favoured"] == sum(1 for x in named if x >= 0.6)
    assert s["underdog"] == sum(1 for x in named if x <= 0.4)
    assert s["favoured"] + s["toss_up"] + s["underdog"] == 18
    # A week's players: what each adds is the week without him from its first day.
    p = client.app.state.seasons._built(LEAGUE, "bbm").problem
    season = client.app.state.seasons.season(LEAGUE)
    span = mv.WeekSpan(tuple(date(2026, 10, 26) + timedelta(n) for n in range(7)), False, ())
    members = [(sp.player.yahoo_id, sp.player) for sp in season.rosters[10]]
    theirs = wk.finals(
        wk.project_week(
            members, p.rates, span.days, p.schedule, p.slots, p.value, False,
            points=p.points, no_games=p.no_games,
        ),
        {},
        CATS,
    )  # fmt: skip
    full = wk.odds_of(wk.finals(mv.project_mine(p, span), {}, CATS), theirs, CATS)
    top = nxt["players"][0]
    gone = mv.project_mine(p, span, gone={top["player"]: span.days[0]})
    without = wk.odds_of(wk.finals(gone, {}, CATS), theirs, CATS)
    assert nxt["win"] == pytest.approx(wk.matchup_won(full), abs=1e-4)
    assert top["matchup"] == pytest.approx(wk.matchup_won(full) - wk.matchup_won(without), abs=1e-4)
    assert top["cats"] == pytest.approx(wk.expected_won(full) - wk.expected_won(without), abs=1e-4)
    assert top["matchup"] > 0 and nxt["started"] == sum(x["started"] for x in nxt["players"])
    assert all(x["cats"] == 0 and x["matchup"] == 0 for x in nxt["players"] if not x["started"])


def test_the_outlook_needs_a_season_of_my_team(client):
    assert client.get("/seasons/100002/outlook").status_code == 409


def test_the_leagues_list_gives_the_weeks_score_adds_left_and_flag_counts(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    rows = {r["league"]: r for r in client.get("/seasons").json()}
    v = client.get(f"/seasons/{LEAGUE}").json()
    mine = rows[LEAGUE]
    # The score is mine first, whichever side of the matchup Yahoo lists me on.
    a, b = v["matchup"]["score"]
    assert mine["score"] == ([a, b] if v["matchup"]["teams"][0] == 4 else [b, a])
    # The adds are the moves' own count, without solving a move.
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert mine["adds"] == {k: m["adds"][k] for k in ("limit", "used", "complete", "left")}
    levels = [f["level"] for f in v["flags"].values() if f["level"] is not None]
    assert sum(mine["flags"].values()) == len(levels)
    assert set(mine["flags"]) <= {"must-add", "add", "watch"}
    # A league with no season read has none of them.
    assert not {"score", "adds", "flags"} & set(rows["100002"])


def test_the_best_move_comes_from_the_solved_moves_and_never_solves_them(client):
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    # Games every day: the three weeks after this one have moves too.
    client.fake.every_day = True
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    service = client.app.state.seasons
    yahoo = {"system": "yahoo"}
    cold = client.get(f"/seasons/{LEAGUE}/best", params=yahoo).json()
    assert cold == {"league": LEAGUE, "status": "not_solved", "system": "yahoo"}
    # The look solved nothing.
    assert not service.moves_cache._payloads
    b = client.post(f"/seasons/{LEAGUE}/best", params=yahoo).json()
    m = client.get(f"/seasons/{LEAGUE}/moves", params=yahoo).json()
    rec = m["recommended"]["three"]
    assert (b["status"], b["horizon"], b["system"]) == ("solved", "three", "yahoo")
    assert b["label"] == m["horizons"]["three"]["label"]
    assert b["moves"] == len(rec["moves"]) > 0 and b["gain"] == rec["gain"]["three"]
    best = max(rec["moves"], key=lambda x: x["marginal"]["three"])
    assert (b["move"]["add"], b["move"]["drop"], b["move"]["gain"]) == (
        best["add"],
        best["drop"],
        best["marginal"]["three"],
    )
    v = client.get(f"/seasons/{LEAGUE}").json()
    names = {a["player"]["yahoo_id"]: a["player"]["name"] for a in v["available"]}
    names |= {s["player"]["yahoo_id"]: s["player"]["name"] for s in v["roster"]}
    assert b["move"]["add_name"] == names[best["add"]]
    assert b["move"]["drop_name"] == names.get(best["drop"])
    # Solved, the look answers the same; another system is still cold.
    assert client.get(f"/seasons/{LEAGUE}/best", params=yahoo).json() == b
    assert client.get(f"/seasons/{LEAGUE}/best").json()["status"] == "not_solved"
    assert client.post("/seasons/100002/best").status_code == 409
    assert client.get("/seasons/999999/best").status_code == 404


# --------------------------------------------------------------------------- strategy (#110)
def strategy_league(client, mine_scale: dict[str, float] | None = None) -> season_api.SeasonService:
    """The fixture league refreshed with games every day and twenty available players projected
    on lines from half to one and a half times the others' (mine scaled by ``mine_scale``), its
    programs solved in process."""
    client.fake.every_day = True
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    mine = set(fixture_names())
    pool = [a["player"]["name"] for a in v["available"] if a["player"]["name"] not in mine][:20]
    scale = {name: 0.5 + i / 19 for i, name in enumerate(pool)} | (mine_scale or {})
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv",
        [*mine, *pool],
        star="Kevin Durant",
        scale=scale,
    )
    service = client.app.state.seasons
    service.strategy_workers = 1
    return service


def test_every_move_carries_its_rest_of_the_season_as_the_log_values_it(client):
    """#151: every candidate's move on each horizon, the recommended sets, the plan, the drawer
    and the stash carry the decision log's own figure to the season's last day, so the moves
    table and the scorecard value a move alike."""
    from pickandroll.api import season_decisions
    from pickandroll.api.seasons import season_dir

    strategy_league(client)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    keys = {"value", "add_games", "drop_games", "extrapolated", "from", "to"}
    options = [(row[k], k) for row in m["candidates"].values() for k in ("week", "three") if row[k]]
    assert options
    ends = set()
    for opt, _ in options:
        ros = opt["ros"]
        assert set(ros) == keys and ros["value"] is not None
        assert ros["add_games"] >= ros["extrapolated"]["add"] >= 0
        # The move the row's For shows: its drop's games given up, none for an open spot.
        assert (ros["drop_games"] is None) == (opt["drop"] is None)
        ends.add(ros["to"])
    # One season's end, past the three weeks.
    (end,) = ends
    assert end > max(r["ros"]["from"] for r, _ in options)
    # The sets: each move's own figure, the set's their sum; the log has the same.
    entry = next(
        e
        for e in reversed(season_decisions.load(season_dir(client.data_dir, LEAGUE), None))
        if e["source"] == "moves"
    )
    logged = {
        (x["add"], x["drop"], x["from"]): x["value"]["horizons"]["season"]["value"]
        for st_ in entry["sets"]
        for x in st_["moves"]
    }
    seen = 0
    for key in ("week", "three"):
        rec = m["recommended"][key]
        assert rec["moves"]
        for x in rec["moves"]:
            assert x["ros"]["value"] == logged[(x["add"], x["drop"], x["from"])]
            seen += 1
        assert rec["ros"]["value"] == pytest.approx(sum(x["ros"]["value"] for x in rec["moves"]))
    assert seen
    # The drawer: the move's own figure, and each drop's and other add's.
    best = m["recommended"]["three"]["moves"][0]
    drop = {} if best["drop"] is None else {"drop": best["drop"]}
    r = client.get(f"/seasons/{LEAGUE}/moves/{best['add']}", params=drop)
    assert r.status_code == 200, (r.text, best)
    d = r.json()
    assert d["ros"] == best["ros"]
    assert next(x for x in d["drops"] if x["drop"] == best["drop"])["ros"] == best["ros"]
    assert all(x["ros"]["value"] is not None for x in (*d["drops"], *d["adds"]))
    # The candidate's own option on that drop is the same move.
    opt = m["candidates"][str(best["add"])]["three"]
    if opt["drop"] == best["drop"]:
        assert opt["ros"] == best["ros"]
    plan = m["plan"]
    if plan is not None:
        rows = [*plan["base"], *plan["steps"]]
        assert all("ros" in r and "dropped_by" in r for r in rows)
        if all(r["ros"] for r in rows):
            total = sum(r["ros"]["value"] for r in rows)
            assert plan["ros"]["plan"]["value"] == pytest.approx(total)
    for row in m["stash"]:
        for opt in (row["add"] or {}).values():
            assert opt is None or "ros" in opt


def test_the_strategy_route_never_solves_on_a_get_and_a_post_fills_it(client):
    service = strategy_league(client)
    url = f"/seasons/{LEAGUE}/strategy"
    cold = client.get(url).json()
    assert cold == {"league": LEAGUE, "status": "not_solved", "system": "bbm"}
    # The look solved nothing, not even the moves the pool is ranked by.
    assert not service.moves_cache._payloads
    r = client.post(url, params={"wait": True, "pool": 12, "weights": "week,natural"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["status"], s["error"], s["step"]) == ("solved", None, None)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    # The pool: the best single moves on each horizon in turn, from the Moves panel's gains.
    assert s["pool"] == st.pool_of(season_strategy.gains_of(m), 12)
    assert [pt["key"] for pt in s["points"]] == ["week", "natural"]
    week, natural = s["points"]
    assert (week["lambda"], natural["lambda"], natural["natural"]) == (1.0, 0.5, True)
    assert s["horizons"]["season"]["label"] == "season pace"
    assert s["weeks_left"] == s["horizons"]["season"]["weeks_left"] > 0
    for key in ("week", "three"):
        assert s["horizons"][key]["base"] == m["horizons"][key]["base"]
    for pt in s["points"]:
        assert pt["stage"] == "done" and pt["source"] in {"search", "milp", "both"}
        assert pt["milp"]["status"] in {"optimal", "time_limited", "failed"}
        assert set(pt["milp"]["size"]) == {"variables", "binaries", "constraints"}
        # Never worse than the search on the weight's own value.
        assert pt["gain"]["weighted"] >= pt["search"]["gain"]["weighted"] - 1e-9
        # The rest of the season is a later week times the weeks left (from rounded gains).
        assert pt["gain"]["season"] == pytest.approx(
            pt["gain"]["three"] * s["weeks_left"] / 3, abs=1e-3 * s["weeks_left"]
        )
        assert set(pt["cats"]) == {"week", "three"}
        assert all(x["priced"] and x["price_without"] >= -1e-9 for x in pt["moves"])
        # The schedule-based rest of the season beside the pace (#151): each move's, the set's
        # their sum.
        assert all(x["ros"]["value"] is not None for x in pt["moves"])
        assert pt["ros"]["value"] == pytest.approx(sum(x["ros"]["value"] for x in pt["moves"]))
    assert "ROS column" in s["horizons"]["season"]["title"]
    # This week's set is at least the best single move, which the pool always holds.
    best = max(r["week"]["gain"] for r in m["candidates"].values() if r["week"])
    assert week["gain"]["week"] >= best - 1e-3 > 0
    # The look finds the run as it ended; another system's is still cold.
    assert client.get(url).json() == s
    assert client.get(url, params={"system": "yahoo"}).json()["status"] == "not_solved"


def test_a_locked_player_is_never_dropped_and_option_b_is_one_switch(client):
    strategy_league(client)
    url = f"/seasons/{LEAGUE}/strategy"
    params = {"wait": True, "pool": 10, "weights": "week"}
    first = client.post(url, params=params).json()
    drops = {x["drop"] for x in first["points"][0]["moves"]} - {None}
    assert drops
    locked = client.post(url, params={**params, "lock": sorted(drops), "program_only": True}).json()
    assert locked["settings"]["keep"] == sorted(drops)
    assert locked["settings"]["program_only"] is True
    pt = locked["points"][0]
    for block in (pt["moves"], pt["search"]["moves"], pt["milp"]["moves"]):
        assert not drops & {x["drop"] for x in block}
    # Option B: the program's set wherever it solved.
    if pt["milp"]["status"] == "optimal":
        assert pt["source"] in {"milp", "both"}
    # A player not on my roster is no lock.
    other = client.post(url, params={**params, "lock": [999999999]}).json()
    assert other["settings"]["keep"] == []


def test_the_strategy_route_refuses_what_it_cannot_solve(client):
    strategy_league(client)
    url = f"/seasons/{LEAGUE}/strategy"
    assert client.post(url, params={"weights": "week,someday"}).status_code == 422
    assert client.post(url, params={"pool": 0}).status_code == 422
    assert client.post(url, params={"pool": 61}).status_code == 422
    assert client.post("/seasons/100002/strategy").status_code == 409
    assert client.get("/seasons/999999/strategy").status_code == 404


def test_a_solved_set_without_a_move_says_so():
    built = season_moves.Built(
        problem=type("P", (), {"roster": (), "held": (), "candidates": ()})(),
        system={"key": "bbm"},
        horizons={
            "week": {"label": "rest of week 25", "weeks": [25]},
            "three": {"label": "no later weeks", "weeks": []},
        },
        adds={},
        unprojected=0,
    )
    payload = {"recommended": {"week": {"moves": [], "gain": {"week": 0.0, "three": 0.0}}}}
    b = season_moves.best_payload(built, payload)
    # The last week has no three weeks after it: the rest of this week answers.
    assert (b["horizon"], b["move"], b["moves"], b["gain"]) == ("week", None, 0, 0.0)


def test_a_cache_peek_makes_nothing():
    cache = season_moves.MovesCache()
    assert cache.peek(("1", "bbm", "moves", 1)) is None
    assert cache.get(("1", "bbm", "moves", 1), lambda: "x") == "x"
    assert cache.peek(("1", "bbm", "moves", 1)) == "x"
    assert cache.peek(("1", "bbm", "moves", 2)) is None


# --------------------------------------------------------------------------- trades (#96)
def trade_league(client) -> dict[str, int]:
    """The fixture league refreshed with a projection where Cooper Flagg (team 10, my opponent
    this week) is the one star, and games on every day; every player of teams 4 and 10 by
    name."""
    client.fake.every_day = True
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Cooper Flagg"
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    return {
        s["player"]["name"]: s["player"]["yahoo_id"] for t in ("4", "10") for s in v["rosters"][t]
    }


def test_a_trade_with_this_weeks_opponent_scores_both_sides(client):
    ids = trade_league(client)
    body = {"team": 10, "give": [ids["Paul Reed"]], "get": [ids["Cooper Flagg"]]}
    r = client.post(f"/seasons/{LEAGUE}/trade", json=body)
    assert r.status_code == 200, r.text
    t = r.json()
    mine, theirs = t["sides"]["mine"], t["sides"]["theirs"]
    assert (mine["team"], theirs["team"]) == (4, 10)
    assert (mine["opponent"], theirs["opponent"]) == (10, 4)
    for key in ("week", "three"):
        assert mine["horizons"][key]["change"] > 0 > theirs["horizons"][key]["change"]
        cats = mine["horizons"][key]["cats"]
        assert [c["cat"] for c in cats] == CATS
        assert sum(c["change"] for c in cats) == pytest.approx(
            mine["horizons"][key]["change"], abs=5e-3
        )
    # The same horizons and odds as the moves: my side before the trade is the moves' base.
    moves = client.get(f"/seasons/{LEAGUE}/moves").json()
    for key in ("week", "three"):
        assert mine["horizons"][key]["before"] == pytest.approx(
            moves["horizons"][key]["base"], abs=2e-3
        )
    # Accepted today, processed after the league's two-day review.
    assert (t["first_day"], t["review_days"]) == ("2026-10-21", 2)
    assert (t["effective"], t["effective_rule"]) == ("2026-10-23", "review")
    assert mine["roster"]["valid"] and theirs["roster"]["valid"]
    flagg = next(p for p in t["players"] if p["name"] == "Cooper Flagg")
    assert (flagg["from"], flagg["to"]) == (10, 4)
    g = flagg["games"]["week"]
    assert g["old"]["games"] + g["new"]["games"] == g["before"]["games"]
    # The rest of the season (#151): each player's to the calendar's end from the trade's day,
    # each side's change what it receives less what it sends (no drop here).
    reed = next(p for p in t["players"] if p["name"] == "Paul Reed")
    assert flagg["ros"]["games"] > flagg["ros"]["extrapolated"] >= 0
    assert flagg["ros"]["value"] == pytest.approx(
        flagg["ros"]["per_game"] * flagg["ros"]["games"], abs=1e-3
    )
    assert not mine["roster"]["drops"] and not theirs["roster"]["drops"]
    change = flagg["ros"]["value"] - reed["ros"]["value"]
    assert change > 0
    assert mine["ros"]["change"] == pytest.approx(change, abs=2e-3)
    assert theirs["ros"]["change"] == pytest.approx(-change, abs=2e-3)
    for side in (mine, theirs):
        r = side["ros"]
        assert r["after"] - r["before"] == pytest.approx(r["change"], abs=2e-3)
        assert (r["from"], r["unvalued"]) == (t["effective"], 0)
    m = t["margin"]
    assert m["horizon"] == t["lead"] == "three"
    assert m["change"] == mine["horizons"]["three"]["change"]
    # Reed sits on my bench and Flagg leaves a team of my field (three teams with a roster
    # here): the trade is no worse for me even if Flagg produced nothing.
    assert m["reading"] == "wins_at_zero" and m["neutral"] is None


def test_a_trade_after_this_week_changes_nothing_this_week(client):
    ids = trade_league(client)
    body = {
        "team": 10,
        "give": [ids["Paul Reed"]],
        "get": [ids["Cooper Flagg"]],
        "effective": "2026-10-26",
    }
    t = client.post(f"/seasons/{LEAGUE}/trade", json=body).json()
    assert (t["effective"], t["effective_rule"]) == ("2026-10-26", "requested")
    for side in ("mine", "theirs"):
        assert t["sides"][side]["horizons"]["week"]["change"] == 0
    assert t["sides"]["mine"]["horizons"]["three"]["change"] > 0


def test_a_two_for_one_reports_the_full_roster_and_the_freed_spot(client):
    ids = trade_league(client)
    two = [ids["Cooper Flagg"], ids["Josh Hart"]]
    t = client.post(
        f"/seasons/{LEAGUE}/trade", json={"team": 10, "give": [ids["Paul Reed"]], "get": two}
    ).json()
    mine = t["sides"]["mine"]["roster"]
    # My out bench player takes one of the league's open IL slots (#124): no drop.
    assert mine["valid"] and mine["active"] == 13 and not mine["drops"]
    assert mine["held_moves"] == [{"player": ids["Aaron Nesmith"], "slot": "IL"}]
    theirs = t["sides"]["theirs"]["roster"]
    assert theirs["valid"] and theirs["open"] == 1
    # A third player in is one too many: a drop, never one of those received.
    three = [*two, ids["Austin Reaves"]]
    t = client.post(
        f"/seasons/{LEAGUE}/trade", json={"team": 10, "give": [ids["Paul Reed"]], "get": three}
    ).json()
    mine = t["sides"]["mine"]["roster"]
    assert not mine["valid"] and len(mine["drops"]) == 1 and mine["active"] == 14
    assert mine["drops"][0]["player"] not in three
    # The other way round my side frees a spot, and the best free agent for it is priced.
    back = client.post(
        f"/seasons/{LEAGUE}/trade",
        json={
            "team": 10,
            "give": [ids["Paul Reed"], ids["Mitchell Robinson"]],
            "get": [ids["Josh Hart"]],
        },
    ).json()
    assert back["sides"]["mine"]["roster"]["open"] == 1
    assert back["fill"]["name"] == "Dillon Brooks" and back["fill"]["gain"]["three"] > 0


def test_a_trade_that_cannot_be_evaluated_is_refused(client):
    ids = trade_league(client)
    reed, flagg = ids["Paul Reed"], ids["Cooper Flagg"]

    def post(body):
        return client.post(f"/seasons/{LEAGUE}/trade", json=body)

    assert post({"team": 10, "give": [reed], "get": [reed]}).status_code == 400
    assert post({"team": 10, "give": [flagg], "get": []}).status_code == 400
    assert post({"team": 10, "give": [reed], "get": [ids["Kevin Durant"]]}).status_code == 400
    assert post({"team": 4, "give": [reed], "get": []}).status_code == 400
    assert post({"team": 10}).status_code == 400
    assert post({"team": 10, "give": [reed], "system": "espn"}).status_code == 422
    assert client.post("/seasons/100002/trade", json={"team": 1}).status_code == 409


def test_a_trade_after_the_deadline_is_refused(client):
    settings = json.loads(fixture("settings.json"))
    settings["service"]["settings"]["trade_end_date"] = "2026-10-20"
    client.fake.settings = json.dumps(settings)
    ids = trade_league(client)
    body = {"team": 10, "give": [ids["Paul Reed"]], "get": [ids["Cooper Flagg"]]}
    r = client.post(f"/seasons/{LEAGUE}/trade", json=body)
    assert r.status_code == 409 and "2026-10-20" in r.json()["detail"]


# --------------------------------------------------------------------------- the breakout flag
PAST_HEAD = "Name,Team,Pos,g,m,p,3,r,a,s,b,fg%,fga,ft%,fta,to,USG"


def past_days_csv(path: Path, rows: list[tuple[str, str, str, int, float, float]]) -> None:
    """A past-days rankings export in the sheet's columns (Total Stats) with made-up numbers:
    ``(name, team, positions, games, minutes, usage)``."""
    lines = [PAST_HEAD]
    for name, team, pos, g, m, usg in rows:
        lines.append(
            f'{name},{team},"{pos}",{g},{m},{12 * g},{g},{5 * g},{3 * g},{g},0,0.5,{10 * g},0.8,{2 * g},{2 * g},{usg}'
        )
    path.write_text("\n".join(lines) + "\n")


def test_a_refresh_keeps_the_flags_inputs_and_the_view_flags_the_pool(client):
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    shared = client.data_dir / "leagues" / "_shared" / "season"
    today = json.loads((shared / "buzz" / "2026-10-21.json").read_text())
    assert today["day"] == "2026-10-21" and today["read_at"] == NOW.isoformat()
    assert len(today["rows"]) == 5 and today["adds"]["5015"] == 7206
    assert (shared / "buzz" / "2026-10-20.json").exists()
    assert len(json.loads((shared / "injuries.json").read_text())["players"]) == 4
    v = client.get(f"/seasons/{LEAGUE}").json()
    assert v["refresh"]["warnings"] == {}
    flags = v["flags"]
    # Drummond tops the buzz index: a full surge, a watch on its own.
    drummond = flags["5015"]
    assert drummond["level"] == "watch" and drummond["signals"]["surge"]["score"] == 1.0
    assert "#1 by adds on Yahoo's buzz index" in drummond["signals"]["surge"]["reason"]
    # Vassell (G-F, no projection) is out to Nov 20: the minutes at forward in San Antonio.
    keldon = flags["6217"]["signals"]["opportunity"]
    assert keldon["score"] == 0.5 and "Devin Vassell" in keldon["reason"]
    # Cunningham is out to Nov 12 at guard in Detroit; Duren is day to day.
    assert flags["6073"]["signals"]["opportunity"]["score"] == 0.5
    # Opportunity alone flags nobody: kept for the hover, scored 0.
    assert flags["6073"]["level"] is None and flags["6073"]["score"] == 0.0
    # Gilgeous-Alexander is back inside two weeks: nothing for Oklahoma City's guards.
    assert "10276" not in flags or flags["10276"]["signals"]["opportunity"]["score"] == 0.0
    assert v["flag_inputs"]["buzz"]["rows"] == 5 and v["flag_inputs"]["projection"] is None
    # Without a projection the minutes and the value gap cannot speak; opportunity still does.
    assert set(v["flag_inputs"]["silent"]) == {"minutes", "value"}
    assert "no rest-of-season export" in v["flag_inputs"]["silent"]["minutes"]
    # A second refresh within the hour reads neither again.
    reads = sum("/buzzindex?" in u or u == ESPN_INJURIES_URL for u in client.fake.urls)
    assert reads == 3
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert sum("/buzzindex?" in u or u == ESPN_INJURIES_URL for u in client.fake.urls) == reads


def test_the_projection_and_the_past_days_feed_the_value_and_minutes_signals(client):
    names = [*fixture_names(), "Andre Drummond", "Keldon Johnson"]
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", names)
    # 38 minutes a game over three games against the projection's 30.
    past_days_csv(
        client.data_dir / "bbm_actual_7d_totals_20261021-1500.csv",
        [
            ("Andre Drummond", "NYK", "C", 3, 114, 22.0),
            ("Keldon Johnson", "SAS", "SF,PF", 1, 40, 20.0),
        ],
    )
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    drummond = v["flags"]["5015"]
    assert drummond["signals"]["minutes"]["score"] == 1.0
    assert drummond["signals"]["value"]["score"] > 0
    assert drummond["level"] in ("add", "must-add")
    # One game is under the 7-day window's floor of two.
    assert v["flags"]["6217"]["signals"]["minutes"]["score"] == 0.0
    past = v["flag_inputs"]["past_days"]
    assert past["7d"]["file"] == "bbm_actual_7d_totals_20261021-1500.csv" and past["14d"] is None
    assert v["flag_inputs"]["silent"] == {}
    d = client.get("/flags/digest").json()
    md = d["markdown"]
    assert "Andre Drummond (NYK, C): adds surge" in md and "minutes up" in md and "value gap" in md
    # The projection's numbers stay local: the JSON has them, the markdown does not.
    assert "38.0" in d["leagues"][0]["flagged"][0]["signals"]["minutes"]["reason"]
    assert "38.0" not in md and "ranked" not in md and "projected min" not in md


def test_the_flag_digest_lists_every_league_with_a_season(client):
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    d = client.get("/flags/digest").json()
    assert d["date"] == "2026-10-21"
    assert [x["league"] for x in d["leagues"]] == [LEAGUE]
    assert d["leagues"][0]["name"] == "Test League 100001"
    assert {"league": "100002", "reason": "no season read yet"} in d["skipped"]
    top = d["leagues"][0]["flagged"]
    # Johnson's surge and his opportunity outrank Drummond's surge alone; the highest first.
    assert [x["name"] for x in top[:2]] == ["Keldon Johnson", "Andre Drummond"]
    assert [x["score"] for x in top] == sorted((x["score"] for x in top), reverse=True)
    assert all(x["level"] is not None for x in top)
    md = d["markdown"]
    assert md.startswith("## Breakout flags, Wed Oct 21") and "### League 100001" in md
    assert "Test League" not in md and "Team 4" not in md
    assert "no past-days export within 3 days" in md
    # The five most added are watch-level: one line of names, the evidence in the JSON.
    assert "- watch (5): Keldon Johnson (SAS), Andre Drummond (NYK), Zaccharie Risacher" in md
    assert top[0]["line"] not in md and top[0]["signals"]["opportunity"]["reason"]
    # The leagues not read close the markdown, by id.
    assert md.rstrip().endswith("Not read: League 100002 (no season read yet).")


def test_the_buzz_day_file_keeps_the_larger_adds_and_the_latest_read(tmp_path):
    season_flags.record_adds(tmp_path, TODAY, {1: 10, 2: 5})
    rows = [{"player": {"yahoo_id": 1}, "adds": 7}]
    season_flags.record_adds(tmp_path, TODAY, {1: 7, 3: 2}, buzz=rows, read_at=NOW)
    body = json.loads(season_flags.buzz_path(tmp_path, TODAY).read_text())
    assert body["adds"] == {"1": 10, "2": 5, "3": 2} and body["rows"] == rows
    # Today's is read again past the hour.
    assert not season_flags._buzz_due(tmp_path, TODAY, TODAY, NOW + timedelta(minutes=30))
    assert season_flags._buzz_due(tmp_path, TODAY, TODAY, NOW + timedelta(hours=2))
    # Yesterday's, read during the day, once more for its final count.
    yesterday = TODAY - timedelta(days=1)
    at = datetime(2026, 10, 20, 20, 0, tzinfo=UTC)  # 16:00 Eastern on the 20th
    season_flags.record_adds(tmp_path, yesterday, {}, buzz=[], read_at=at)
    assert season_flags._buzz_due(tmp_path, yesterday, TODAY, NOW)
    season_flags.record_adds(tmp_path, yesterday, {}, buzz=[], read_at=NOW)
    assert not season_flags._buzz_due(tmp_path, yesterday, TODAY, NOW)


def _et(day: date, hour: int, minute: int = 5) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=season_week.NBA_TZ)


def test_the_buzz_day_file_keeps_the_adds_by_the_hour_they_were_read(tmp_path):
    season_flags.record_adds(tmp_path, TODAY, {1: 40}, at=_et(TODAY, 9, 10))
    season_flags.record_adds(tmp_path, TODAY, {1: 35, 2: 3}, at=_et(TODAY, 9, 30))
    season_flags.record_adds(tmp_path, TODAY, {1: 90}, at=NOW)  # 14:00 Eastern
    body = json.loads(season_flags.buzz_path(tmp_path, TODAY).read_text())
    assert body["hours"] == {"09": {"1": 40, "2": 3}, "14": {"1": 90}}
    # A read after the day ended holds its final count.
    season_flags.record_adds(tmp_path, TODAY, {1: 120}, at=_et(TODAY + timedelta(days=1), 1))
    body = json.loads(season_flags.buzz_path(tmp_path, TODAY).read_text())
    assert body["hours"]["24"] == {"1": 120} and body["adds"] == {"1": 120, "2": 3}


def test_a_mornings_adds_compare_with_earlier_mornings(tmp_path):
    for i in (1, 2, 3):
        day = TODAY - timedelta(days=i)
        season_flags.record_adds(tmp_path, day, {1: 100}, at=_et(day, 9))
        season_flags.record_adds(tmp_path, day, {1: 1000}, at=_et(day, 20))
    season_flags.record_adds(tmp_path, TODAY, {1: 300}, at=_et(TODAY, 10))
    history, _, adds, info = season_flags._buzz(tmp_path, TODAY, _et(TODAY, 10, 20))
    # Each earlier day as of 09:05, an hour before today's read, not its final 1000.
    assert history[1] == [100.0, 100.0, 100.0] and adds[1] == 300
    assert info["same_hour"] == 3 and info["earlier_days"] == 3


def test_an_earlier_day_not_read_by_that_hour_scales_its_count(tmp_path):
    old = TODAY - timedelta(days=2)
    path = season_flags.buzz_path(tmp_path, old)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"day": old.isoformat(), "adds": {"1": 960}}))
    yesterday = TODAY - timedelta(days=1)
    season_flags.record_adds(tmp_path, yesterday, {1: 620}, at=_et(yesterday, 15))
    season_flags.record_adds(tmp_path, TODAY, {1: 50}, at=_et(TODAY, 9))
    history, *_, info = season_flags._buzz(tmp_path, TODAY, _et(TODAY, 9))
    # A file kept before the hours were holds final counts: the share of the day by 09:30.
    # Yesterday, read last at 15:05, scales from then.
    assert history[1] == pytest.approx([960 * 9.5 / 24, 620 * 9.5 / 15.5])
    assert info["same_hour"] == 0


def test_a_failed_flag_input_warns_and_the_refresh_still_lands(client):
    real = client.fake.__call__

    class Flaky(FakeYahoo):
        def __call__(self, url: str) -> str:
            if "/buzzindex?" in url:
                raise public.FetchError(f"{url}: HTTP 503")
            return real(url)

    client.app.state.seasons.fetch_factory = Flaky
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202 and r.json()["refresh"]["status"] == "done"
    warnings = r.json()["refresh"]["warnings"]
    assert set(warnings) == {"buzz index 2026-10-20", "buzz index 2026-10-21"}
    d = client.get("/flags/digest").json()
    assert "no buzz index read today" in d["notes"]


def test_a_past_days_export_is_never_offered_as_a_projection(client):
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", ["Andre Drummond"])
    past_days_csv(
        client.data_dir / "bbm_actual_7d_totals_20261021-1500.csv",
        [("Andre Drummond", "NYK", "C", 3, 90, 20.0)],
    )
    files = [f["file"] for f in client.get("/projections").json()]
    assert files == ["bbm_projections_2026-10-21.csv"]


def test_the_view_carries_the_flags_thresholds_from_the_flag_itself(client):
    """#113: the explainer's numbers are the flag's own, so a retune reaches the web."""
    v = client.get(f"/seasons/{LEAGUE}").json()
    cfg = v["flag_config"]
    assert [(x["level"], x["floor"]) for x in cfg["levels"]] == [(n, f) for n, f in fl.LEVELS]
    assert set(cfg["signals"]) == set(fl.SIGNALS) and cfg["max"] == len(fl.SIGNALS)
    assert cfg["signals"]["value"]["rank"] == fl.VALUE_RANK
    assert cfg["signals"]["minutes"]["min_games"] == {"7": 2, "14": 4}
    assert cfg["opportunity_needs_another"] is fl.OPPORTUNITY_NEEDS_ANOTHER
    assert cfg["past_days_max_days"] == 3
    # Before any read: no injury report either, so opportunity is silent too.
    assert set(v["flag_inputs"]["silent"]) == {"minutes", "value", "opportunity"}


def test_a_stale_past_days_export_leaves_only_the_minutes_silent():
    info = {
        "projection": "bbm_projections.csv",
        "injuries": {"read_at": "2026-10-21T15:00:00+00:00", "players": 4},
        "past_days": {"7d": {"file": "x.csv", "as_of": "2026-10-10", "stale": True}, "14d": None},
    }
    assert set(season_flags.silent(info)) == {"minutes"}
    assert "within 3 days" in season_flags.silent(info)["minutes"]
    assert season_flags.silent({"error": "boom"}) == {}


# --------------------------------------------------------------------------- the keep rule (#124)
def test_the_moves_say_whom_the_keep_rule_keeps_and_what_to_do_with_an_out_player(client):
    """Made-up lines: the star and my out bench player above the best add, the rest below."""
    strategy_league(client, {"Kevin Durant": 1.5, "Aaron Nesmith": 2.0})
    v = client.get(f"/seasons/{LEAGUE}").json()
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    ids = {s["player"]["name"]: s["player"]["yahoo_id"] for s in v["roster"]}
    star, out = ids["Kevin Durant"], ids["Aaron Nesmith"]
    rule = m["keep_rule"]
    assert rule["floor"] == 0.0 and rule["average"] == 0.0
    assert str(rule["best"]["player"]) in m["candidates"]
    by = {k["player"]: k for k in rule["players"]}
    assert set(by) == {
        s["player"]["yahoo_id"] for s in v["roster"] if s["slot"] not in ("IL", "IL+", "NA")
    }
    for k in by.values():
        assert k["protected"] == (k["net_positive"] and k["beats_best"] and k["returns"])
        assert k["value"] is None or k["protected"] == (k["value"] > rule["best"]["value"])
    kept = {k for k, x in by.items() if x["protected"] or x["bench"]}
    assert kept == {star, out}
    # He is out until next Monday and still protected; the open IL takes him.
    assert by[out]["back"] == "2026-10-26"
    [advice] = m["stash"]
    assert (advice["player"], advice["status"], advice["advice"], advice["slot"]) == (
        out,
        "O",
        "stash",
        "IL",
    )
    assert advice["slots"] == ["IL"] and advice["protected"] and advice["net"] > 0
    assert advice["add"]["three"]["player"] in {int(c) for c in m["candidates"]}
    # No move drops a kept player; an add with no drop names the held move that makes room.
    for row in m["candidates"].values():
        for key in ("week", "three"):
            best = row[key]
            if best is None:
                continue
            assert best["drop"] not in kept and best["next_drop"] not in kept
            assert (best["held"] is not None) == (best["drop"] is None)
    for key in ("week", "three"):
        rec = m["recommended"][key]
        assert not kept & {x["drop"] for x in rec["moves"]}
        free = [x for x in rec["moves"] if x["drop"] is None]
        assert [x["held"] for x in free] == rec["held"][: len(free)]
    # The drawer still lists a kept player as a drop, marked: what keeping him costs.
    pid = rule["best"]["player"]
    d = client.get(f"/seasons/{LEAGUE}/moves/{pid}", params={"drop": star}).json()
    marks = {x["drop"]: x["kept"] for x in d["drops"]}
    assert marks[star] is True and marks[None] is False
    # No drop: the out player's IL move makes the room, and the drawer names it.
    nobody = next(x for x in d["drops"] if x["drop"] is None)
    assert nobody["held"] == {"player": out, "slot": "IL"}
    assert all(x["held"] is None for x in d["drops"] if x["drop"] is not None)
    assert not any(marks[k] for k in marks if k not in kept and k is not None)


def test_the_strategy_names_the_held_moves_and_never_drops_a_kept_player(client):
    strategy_league(client, {"Kevin Durant": 1.5, "Aaron Nesmith": 2.0})
    s = client.post(
        f"/seasons/{LEAGUE}/strategy", params={"wait": True, "pool": 10, "weights": "week,natural"}
    ).json()
    kept = {k["player"] for k in s["keep_rule"]["players"] if k["protected"] or k["bench"]}
    assert len(kept) == 2
    for pt in s["points"]:
        for block in (pt["moves"], pt["search"]["moves"], pt["milp"]["moves"] or []):
            assert not kept & {x["drop"] for x in block}
        free = [x for x in pt["moves"] if x["drop"] is None]
        assert [x["held"] for x in free] == pt["held"][: len(free)]
        assert all(x["held"] is None for x in pt["moves"] if x["drop"] is not None)


def test_an_add_with_no_move_says_why():
    roster, cands, rate, sched, opponent, field = streaming_league()
    p = build(roster, cands, rate, sched, opponent, field)
    every = replace(p, kept=frozenset(k for k, _ in roster))
    ev = mv.Evaluator(every)
    assert all(not gs for gs in mv.single_swaps(ev, "week").values())
    assert season_moves.no_move(every, 10) == season_moves.NO_DROP
    shut = replace(p, limits=(mv.AddLimit(WEEKS[0][0], WEEKS[0][6], 0),))
    assert season_moves.no_move(shut, 10) == season_moves.NO_ADDS_LEFT


def test_a_points_leagues_average_is_over_the_players_the_league_rosters():
    """Made-up lines: four players worth 40, 30, 20 and 10 points a game."""
    rates = {k: {"pts": float(v)} for k, v in {1: 40, 2: 30, 3: 20, 4: 10}.items()}
    rated = SimpleNamespace(bbm=SimpleNamespace(rates=rates))
    got = season_moves.keep_inputs(rated, ("pts",), {"pts": 1.0}, 2)
    assert got["average"] == pytest.approx(35.0) and got["dead"] == 0.0
    assert season_moves.keep_inputs(rated, ("pts",), {"pts": 1.0}, 4)["average"] == pytest.approx(
        25.0
    )
    # A categories league's z-sums average zero over the same pool.
    cats = season_moves.keep_inputs(rated, ("pts",), None, 4)
    assert cats["average"] == 0.0 and sum(cats["season_value"].values()) == pytest.approx(0.0)
