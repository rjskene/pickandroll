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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.api import seasons as season_api
from pickandroll.season import (
    EXTENSION,
    PUBLIC,
    Calendar,
    Part,
    Player,
    Season,
    SeasonSettings,
    build_calendar,
    merge_part,
    mondays,
)
from pickandroll.sources import schedule
from pickandroll.sources.yahoo import pages, public

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


EMPTY_ROSTER = "<html><body><table><thead><tr><th>Pos</th><th>Players</th></tr></thead><tbody></tbody></table></body></html>"


class FakeYahoo:
    """Yahoo's and ESPN's public sources for league 100001, from the fixtures."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if url.startswith(public.PUB_API + "/settings/"):
            return fixture("settings.json")
        if url.startswith(public.PUB_API + "/players/"):
            return fixture("players.json")
        if url.startswith(schedule.SCOREBOARD.split("?")[0]):
            day = re.search(r"dates=(\d{8})", url).group(1)
            path = FIXTURES / f"espn_{day}.json"
            return path.read_text() if path.exists() else '{"events": []}'
        kind, info = pages.page_kind(url)
        if kind == "league":
            return fixture("league.html")
        if kind == "team":
            m = re.search(r"date=(\d{4}-\d{2}-\d{2})", url)
            if m:
                week = fake_week(date.fromisoformat(m.group(1)))
                return f"<html><body><p>Week {week} stats may change when Stat corrections are applied.</p></body></html>"
            path = FIXTURES / f"team{info['team_id']}.html"
            return path.read_text() if path.exists() else EMPTY_ROSTER
        if kind == "players":
            offset = int(re.search(r"count=(\d+)", url).group(1))
            return fixture("avail0.html" if offset == 0 else "avail25.html")
        if kind == "matchup":
            return fixture("matchup.html")
        if kind == "transactions":
            return fixture("transactions.html")
        raise AssertionError(url)


@pytest.fixture
def client(tmp_path):
    write_folder(tmp_path, LEAGUE)
    write_folder(tmp_path, "100002", public=False, my_team_id=7)
    fake = FakeYahoo()
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: fake)
    app.state.seasons.clock = lambda: NOW
    with TestClient(app) as c:
        c.fake = fake  # type: ignore[attr-defined]
        c.data_dir = tmp_path  # type: ignore[attr-defined]
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
    # Paging stopped at the short page; the calendar was read once, one request per Monday.
    fake = client.fake
    assert sum("/players?" in u for u in fake.urls) == 2
    assert sum("?date=" in u for u in fake.urls) == 24  # Mondays Oct 19 to Mar 29
    cal = json.loads((client.data_dir / "leagues/_shared/season/calendar.json").read_text())
    seventeen = next(w for w in cal["weeks"] if w["number"] == 17)
    assert (seventeen["start"], seventeen["end"]) == ("2027-02-08", "2027-02-21")
    # Stored with its time; a second refresh does not read the calendar again.
    folder = client.data_dir / "leagues" / LEAGUE / "season"
    assert (folder / "state.json").exists() and len(list((folder / "snapshots").iterdir())) == 1
    fake.urls.clear()
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    assert not any("?date=" in u for u in fake.urls)
    assert len(list((folder / "snapshots").iterdir())) == 2


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
