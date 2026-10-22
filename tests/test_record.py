"""#97: the weekly recorder. A finished week's standings, every team's totals, games and result,
the matchups and the drafted players' season lines, written once per week.

The parser fixtures in tests/fixtures/season/record are cut from public pages of two prize
leagues to the elements the parsers read and anonymised: the league id is 100001, every fantasy
team is "Team <id>", no manager names. NBA players' names and stats are Yahoo's public data.
The route tests serve pages built here in the same markup, for a made-up four-team league.
Nothing here is from Basketball Monster.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
from collections.abc import Mapping
from contextlib import redirect_stdout
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app, season_record
from pickandroll.season import Week
from pickandroll.season import record as rec
from pickandroll.sources.yahoo import pages

FIXTURES = Path(__file__).parent / "fixtures" / "season" / "record"
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "season.py"
CATS = ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"]
ROSTER = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN"]
LEAGUE, PRIVATE, POINTS = "100001", "100002", "100003"
#: Monday after week 1, and after week 2, mid-morning US Eastern.
AFTER_1 = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)
AFTER_2 = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
WEEKS = [
    Week(1, date(2026, 10, 19), date(2026, 10, 25)),
    Week(2, date(2026, 10, 26), date(2026, 11, 1)),
    Week(3, date(2026, 11, 2), date(2026, 11, 8)),
]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


# --------------------------------------------------------------------------- parsers
def test_the_matchup_page_gives_each_teams_games_played():
    d = pages.parse_matchup_page(fixture("matchup_week.html"), 1)
    assert d["teams"] == [4, 10] and d["score"] == [5.0, 3.0]
    assert d["games"] == {"4": {"played": 3, "scheduled": 31}, "10": {"played": 2, "scheduled": 32}}
    assert d["totals"]["4"]["FGM/A*"] == "15/31" and "roster_totals" not in d


def test_a_points_matchup_sums_its_player_table_to_the_score():
    d = pages.parse_matchup_page(fixture("matchup_week_points.html"), 1)
    assert d["totals"] == {} and d["score"] == [30.9, 120.2]
    assert d["games"]["8"] == {"played": 2, "scheduled": 27}
    sums = d["roster_totals"]
    assert [sums["8"]["Fan Pts"], sums["6"]["Fan Pts"]] == d["score"]
    assert sums["6"]["PTS"] == 54.0


def test_the_draft_results_give_every_pick_by_round_and_overall():
    picks = pages.parse_draft_results(fixture("draftresults.html"))["picks"]
    assert len(picks) == 24
    first, last = picks[0], picks[-1]
    assert (first["round"], first["in_round"], first["pick"]) == (1, 1, 1)
    assert first["player"]["yahoo_id"] == 10094 and first["player"]["nba_team"] == "SAS"
    assert first["team_name"] == "Team 9"
    # The snake: the first pick of round 2 is the team that made the last of round 1.
    assert picks[12]["team_name"] == picks[11]["team_name"] and picks[12]["pick"] == 13
    assert (last["round"], last["pick"], last["team_name"]) == (2, 24, "Team 9")


def test_season_lines_name_who_has_each_player():
    rows = pages.parse_stat_lines(fixture("lines_season.html"))["rows"]
    george = rows[0]
    assert george["player"]["name"] == "Paul George" and george["team_id"] == 7
    assert (george["gp"], george["pts"], george["fgm"], george["fga"], george["mpg"]) == (
        1.0,
        38.0,
        12.0,
        21.0,
        31.0,
    )
    waiver = rows[-1]
    assert (waiver["team_id"], waiver["availability"], waiver["gp"]) == (None, "W", 0.0)
    # The search page prints no games column.
    found = pages.parse_stat_lines(fixture("search.html"))["rows"]
    assert len(found) == 1 and found[0]["gp"] is None and found[0]["pts"] == 12.0


def test_page_kinds_know_the_draft_results_and_the_search():
    base = f"https://basketball.fantasysports.yahoo.com/nba/{LEAGUE}"
    assert pages.page_kind(base + "/draftresults") == ("draftresults", {"league": LEAGUE})
    assert pages.page_kind(base + "/playersearch?search=x&stat1=S_S_2026")[0] == "playersearch"
    assert pages.page_kind(base + "/players?status=T&stat1=S_S_2026")[1]["status"] == "T"


# --------------------------------------------------------------------------- the core
def test_team_totals_split_makes_and_attempts_and_name_the_stats():
    t = rec.team_totals({"FGM/A*": "15/31", "FG%": ".484", "3PTM": "5", "ST": "2", "TO": "6"})
    assert t == {"fgm": 15.0, "fga": 31.0, "fg_pct": 0.484, "threes": 5.0, "stl": 2.0, "tov": 6.0}
    assert rec.team_totals({"Fan Pts": 30.9, "DD": "2"}) == {"fpts": 30.9, "DD": 2.0}


def test_week_teams_read_each_result():
    m = {"week": 1, "teams": [1, 2], "score": [5.0, 3.0], "totals": {}, "games": {}}
    teams, pairs = rec.week_teams([m], CATS, points=False)
    assert teams["1"]["result"] == {"won": 5, "lost": 3, "tied": 1, "outcome": "W"}
    assert teams["2"]["result"] == {"won": 3, "lost": 5, "tied": 1, "outcome": "L"}
    assert pairs == [{"teams": [1, 2], "score": [5.0, 3.0], "winner": 1}]
    tie = {**m, "score": [4.0, 4.0]}
    assert rec.week_teams([tie], CATS, False)[0]["1"]["result"]["outcome"] == "T"
    pts = {**m, "score": [810.5, 902.0]}
    assert rec.week_teams([pts], ["fpts"], True)[0]["1"]["result"] == {
        "points": 810.5,
        "against": 902.0,
        "outcome": "L",
    }


def test_draft_teams_match_by_name_and_say_which_did_not():
    picks = [
        {"team_name": "Team  1", "round": 1, "pick": 1},
        {"team_name": "Renamed", "round": 1, "pick": 2},
    ]
    out, unmatched = rec.draft_teams(picks, [{"team_id": 1, "name": "team 1"}])
    assert [p["team_id"] for p in out] == [1, None] and unmatched == ["Renamed"]


def _record(**over) -> dict:
    base = {
        "league": LEAGUE,
        "week": 1,
        "start": "2026-10-19",
        "end": "2026-10-25",
        "standings": {"read_at": "a", "through": "2026-10-25", "teams": [{"team_id": 1}]},
        "players": {"read_at": "a", "through": "2026-10-25", "rows": [{"player": 1, "line": 1}]},
        "teams": {"1": {"totals": {"pts": 40.0}}},
        "missing": {},
        "sources": {"pages": "public"},
    }
    return {**base, **over}


def test_settle_records_once_and_revises_only_a_change():
    t0, t1 = datetime(2026, 10, 26, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    first, status = rec.settle(None, _record(), t0)
    assert status == "recorded" and first["recorded_at"] == t0.isoformat()
    # Read again later the same day: only the read times differ.
    again = _record(standings={**first["standings"], "read_at": "b"})
    assert rec.settle(first, again, t1) == (None, "unchanged")
    corrected = _record(teams={"1": {"totals": {"pts": 42.0}}})
    out, status = rec.settle(first, corrected, t1)
    assert status == "revised" and out["recorded_at"] == t0.isoformat()
    assert out["revised_at"] == t1.isoformat()


def test_a_late_read_never_replaces_the_one_at_the_weeks_end():
    t0 = datetime(2026, 10, 26, tzinfo=UTC)
    first, _ = rec.settle(None, _record(), t0)
    late = _record(
        players={"read_at": "c", "through": "2026-10-28", "rows": [{"player": 1, "line": 2}]},
        missing={"players": [7]},
    )
    assert rec.settle(first, late, t0) == (None, "unchanged")
    # A first record read late keeps that read until one at the week's end arrives.
    lone, _ = rec.settle(None, late, t0)
    out, status = rec.settle(lone, _record(), t0)
    assert status == "revised" and out["players"]["through"] == "2026-10-25"
    assert "players" not in out["missing"]


def test_games_come_from_the_totals_over_the_averages():
    totals = {"fga": 87.0, "pts": 101.0, "reb": 30.0}
    assert season_record._games(totals, {"fga": 9.7, "pts": 11.2, "reb": 3.3}) == 9.0
    assert season_record._games({"fga": 0.0, "pts": 0.0, "reb": 0.0}, {}) == 0.0


def test_the_week_to_record_is_the_latest_over():
    assert season_record.week_to_record(WEEKS, date(2026, 10, 26), None).number == 1
    assert season_record.week_to_record(WEEKS, date(2026, 11, 4), None).number == 2
    assert season_record.week_to_record(WEEKS, date(2026, 11, 4), 1).number == 1
    with pytest.raises(ValueError, match="no week is over"):
        season_record.week_to_record(WEEKS, date(2026, 10, 25), None)
    with pytest.raises(ValueError, match="once over"):
        season_record.week_to_record(WEEKS, date(2026, 10, 30), 2)
    with pytest.raises(LookupError):
        season_record.week_to_record(WEEKS, date(2026, 10, 30), 9)


# --------------------------------------------------------------------------- pages for the routes
SITE = "https://basketball.fantasysports.yahoo.com/nba"
TEAMS = (1, 2, 3, 4)
#: Each week's pairs and score (categories won), with each team's games played and scheduled.
SCORES = {
    1: {(1, 2): (5, 3), (3, 4): (4, 4)},
    2: {(1, 3): (6, 2), (2, 4): (3, 5)},
}
POINT_SCORES = {1: {(1, 2): (810.5, 790.25), (3, 4): (700.0, 700.0)}}
GAMES = {1: 28, 2: 31, 3: 30, 4: 29}


def standings_after(week: int, points: bool = False) -> dict[int, tuple[int, int, int, float]]:
    """The standings page after ``week``: written out by hand, not summed from the scores."""
    if points:
        return {1: (1, 0, 0, 810.5), 2: (0, 1, 0, 790.25), 3: (0, 0, 1, 700.0), 4: (0, 0, 1, 700.0)}
    return {
        0: {t: (0, 0, 0, 0.0) for t in TEAMS},
        1: {1: (5, 3, 1, 0.0), 2: (3, 5, 1, 0.0), 3: (4, 4, 1, 0.0), 4: (4, 4, 1, 0.0)},
        2: {1: (11, 5, 2, 0.0), 2: (6, 10, 2, 0.0), 3: (6, 10, 2, 0.0), 4: (9, 7, 2, 0.0)},
    }[week]


def league_html(league: str, week: int, points: bool) -> str:
    rows = sorted(standings_after(week, points).items(), key=lambda kv: (-kv[1][0], kv[0]))
    body = "".join(
        f'<tr><td>{rank}</td><td><a href="/nba/{league}/{t}">Team {t}</a></td>'
        f"<td>{w}-{lo}-{ti}</td><td>{pf}</td></tr>"
        for rank, (t, (w, lo, ti, pf)) in enumerate(rows, 1)
    )
    return (
        f"<html><head><title>Test League {league} | Yahoo</title></head><body>"
        "<table><thead><tr><th>Rank</th><th>Team</th><th>W-L-T</th><th>Pts</th></tr></thead>"
        f"<tbody>{body}</tbody></table></body></html>"
    )


def team_stats(week: int, team: int) -> dict[str, float]:
    k = week * 10 + team
    return {
        "fgm": 150 + k,
        "fga": 320 + 2 * k,
        "ftm": 60 + k % 7,
        "fta": 80 + k % 5,
        "threes": 40 + k % 9,
        "pts": 400 + 3 * k,
        "reb": 180 + k,
        "ast": 100 + k % 11,
        "stl": 30 + k % 4,
        "blk": 20 + k % 6,
        "tov": 50 + k % 8,
    }


def matchup_html(league: str, week: int, a: int, b: int, points: bool, bump: int = 0) -> str:
    score = (POINT_SCORES if points else SCORES)[week][(a, b)]
    games = (
        f'<div id="remaining-games"><div><span>0</span><span>Remaining</span></div>'
        f"<div><span>{GAMES[a]}/{GAMES[a]}</span><span>Games Played</span>"
        f"<span>{GAMES[b]}/{GAMES[b]}</span></div></div>"
    )
    head = (
        f'<p><a href="/nba/{league}/{a}">Team {a}</a> <a href="/nba/{league}/{b}">Team {b}</a></p>'
        f"<table class='M-a'><tr><td>{score[0]}</td><th>vs</th><td>{score[1]}</td></tr></table>"
    )
    if points:
        cols = ["Fan Pts", "PTS", "REB", "AST", "BLK", "ST", "TO"]
        half = "<th>Pos</th><th>Player</th>" + "".join(f"<th>{c}</th>" for c in cols)
        cells = "".join(f"<td>{v}</td>" for v in (score[0], 100, 40, 20, 5, 6, 9))
        cells_b = "".join(f"<td>{v}</td>" for v in (score[1], 90, 41, 21, 4, 7, 8))
        table = (
            f'<table id="statTable0"><thead><tr>{half}<th></th><th>Pos</th>{half}</tr></thead>'
            f"<tbody><tr><td>PG</td><td>A</td>{cells}<td></td><td>PG</td><td>PG</td><td>B</td>{cells_b}</tr></tbody></table>"
        )
        return f"<html><body>{head}{games}{table}</body></html>"

    def row(t: int) -> str:
        s = team_stats(week, t)
        s["pts"] += bump if t == a else 0
        return (
            f'<tr><td><a href="/nba/{league}/{t}">Team {t}</a></td>'
            f"<td>{s['fgm']}/{s['fga']}</td><td>{s['fgm'] / s['fga']:.3f}</td>"
            f"<td>{s['ftm']}/{s['fta']}</td><td>{s['ftm'] / s['fta']:.3f}</td>"
            f"<td>{s['threes']}</td><td>{s['pts']}</td><td>{s['reb']}</td><td>{s['ast']}</td>"
            f"<td>{s['stl']}</td><td>{s['blk']}</td><td>{s['tov']}</td></tr>"
        )

    labels = [
        "Team",
        "FGM/A*",
        "FG%",
        "FTM/A*",
        "FT%",
        "3PTM",
        "PTS",
        "REB",
        "AST",
        "ST",
        "BLK",
        "TO",
    ]
    table = (
        "<table><thead><tr>"
        + "".join(f"<th>{x}</th>" for x in labels)
        + f"</tr></thead><tbody>{row(a)}{row(b)}</tbody></table>"
    )
    return f"<html><body>{head}{games}{table}</body></html>"


#: The draft: three rounds of the four teams, snake order; player 1000 + pick.
def picks() -> list[tuple[int, int, int, int]]:
    out = []
    for r in (1, 2, 3):
        order = TEAMS if r % 2 else tuple(reversed(TEAMS))
        for n, team in enumerate(order, 1):
            overall = (r - 1) * 4 + n
            out.append((r, n, 1000 + overall, team))
    return out


def draft_html() -> str:
    tables = []
    for r in (1, 2, 3):
        rows = "".join(
            f'<tr><td class="first">{n}.</td><td class="player">'
            f'<a href="https://sports.yahoo.com/nba/players/{pid}" class="name">Player {pid}</a> '
            f'<span>(BOS - SF)</span></td><td class="last" title="Team {t}">Team {t}</td></tr>'
            for rr, n, pid, t in picks()
            if rr == r
        )
        tables.append(
            f'<table><thead><tr><th colspan="3">Round {r}</th></tr></thead><tbody>{rows}</tbody></table>'
        )
    return "<html><body>" + "".join(tables) + "</body></html>"


def line(pid: int) -> dict[str, float]:
    k = pid % 100
    return {"gp": 3 + k % 2, "fgm": 20 + k, "fga": 45 + k, "ftm": 9, "fta": 11, "threes": 6,
            "pts": 55 + k, "reb": 18, "ast": 12, "stl": 3, "blk": 2, "tov": 7}  # fmt: skip


#: The taken players by preseason rank: drafted 1001-1009 (1005 traded to team 2) and two others;
#: the available ones: 1011 (dropped), four others. 1010 and 1012 were dropped and are on
#: neither list; the search finds 1012 and not 1010.
TAKEN = [1001, 1002, 1003, 3001, 1004, 1005, 1006, 3002, 1007, 1008, 1009]
AVAILABLE = [3003, 3004, 1011, 3005, 3006, 3007]
OWNER = {pid: team for _, _, pid, team in picks()} | {1005: 2, 3001: 3, 3002: 4}


def lines_html(league: str, ids: list[int], averages: bool = False, games: bool = True) -> str:
    labels = ["", "Players", "Roster Status"] + (["GP*"] if games else []) + [
        "MPG", "FGM /A*", "FG%", "FTM /A*", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO",
    ]  # fmt: skip
    rows = []
    for pid in ids:
        s = line(pid)
        if averages:
            s = {k: round(v / s["gp"], 1) if k != "gp" else v for k, v in s.items()}
        status = (
            f'<a href="/nba/{league}/{OWNER[pid]}">Team {OWNER[pid]}</a>' if pid in TAKEN else "FA"
        )
        cells = [
            "",
            (
                f'<div class="ysf-player-name"><a data-ys-playerid="{pid}" title="Player {pid}" '
                f'href="https://sports.yahoo.com/nba/players/{pid}">Player {pid}</a>'
                "<span>BOS - SF</span></div>"
            ),
            status,
            *([str(s["gp"])] if games else []),
            "30:00",
            f"{s['fgm']}/{s['fga']}",
            f"{s['fgm'] / s['fga']:.3f}",
            f"{s['ftm']}/{s['fta']}",
            f"{s['ftm'] / s['fta']:.3f}",
            *(str(s[k]) for k in ("threes", "pts", "reb", "ast", "stl", "blk", "tov")),
        ]
        rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    head = "".join(f"<th>{x}</th>" for x in labels)
    return (
        f"<html><body><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}"
        "</tbody></table></body></html>"
    )


class FakeYahoo:
    """The made-up league's public pages after ``week``."""

    def __init__(self) -> None:
        self.week = 1
        self.urls: list[str] = []
        #: Points added to team 1's PTS in week 1's matchup page: a stat correction.
        self.bump = 0

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if "fantasysports.yahoo.com/nba/" not in url:
            return '{"events": []}'  # ESPN: a private snapshot's schedule read, in the background
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        league, rest = parts[1], parts[2:]
        points = league == POINTS
        if league == PRIVATE:
            raise AssertionError(f"the private league is never fetched: {url}")
        if not rest:
            return league_html(league, self.week, points)
        if rest[0] == "matchup":
            week, team = int(q["week"]), int(q["mid1"])
            pair = next(p for p in (POINT_SCORES if points else SCORES)[week] if team in p)
            return matchup_html(league, week, *pair, points, self.bump if week == 1 else 0)
        if rest[0] == "draftresults":
            return draft_html()
        if rest[0] == "players":
            ids = TAKEN if q["status"] == "T" else AVAILABLE
            offset, size = int(q["count"]), season_record.PAGE_ROWS
            return lines_html(league, ids[offset : offset + size])
        if rest[0] == "playersearch":
            pid = int(re.search(r"(\d+)$", unquote(q["search"])).group(1))
            found = [pid] if pid == 1012 else []
            return lines_html(league, found, averages=q["stat1"].startswith("S_AS"), games=False)
        raise AssertionError(url)


def write_league(data_dir: Path, league: str, **extra) -> None:
    folder = data_dir / "leagues" / league
    folder.mkdir(parents=True, exist_ok=True)
    body = {
        "league_id": int(league),
        "scoring": "categories",
        "num_teams": 4,
        "roster": ROSTER,
        "categories": CATS,
        "my_team_id": 1,
        **extra,
    }
    (folder / "settings.json").write_text(json.dumps(body))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(season_record, "PAGE_ROWS", 4)
    write_league(tmp_path, LEAGUE)
    write_league(tmp_path, PRIVATE, public=False, my_team_id=2)
    write_league(tmp_path, POINTS, scoring="points", points={"pts": 1.0})
    shared = tmp_path / "leagues" / "_shared" / "season"
    shared.mkdir(parents=True)
    (shared / "calendar.json").write_text(
        json.dumps({"weeks": [w.to_dict() for w in WEEKS], "estimated": False})
    )
    fake = FakeYahoo()
    app = create_app(SessionStore(), data_dir=tmp_path, season_fetch=lambda: fake)
    clock = {"now": AFTER_1}
    app.state.seasons.clock = lambda: clock["now"]
    with TestClient(app) as c:
        c.fake = fake  # type: ignore[attr-defined]
        c.data_dir = tmp_path  # type: ignore[attr-defined]
        c.clock = clock  # type: ignore[attr-defined]
        yield c


def week_file(client, league: str, week: int) -> Path:
    return client.data_dir / "leagues" / league / "season" / "weeks" / f"{week}.json"


def by_team(rows: list[Mapping]) -> dict[int, Mapping]:
    return {int(r["team_id"]): r for r in rows}


# --------------------------------------------------------------------------- the routes
def test_a_recorded_week_from_the_league_pages(client):
    r = client.post(f"/seasons/{LEAGUE}/record")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["week"] == 1 and out["status"] == "recorded"
    # Two matchup pages cover the four teams; the taken players' pages run to a short page; the
    # available ones and one search (totals and averages) find the drops.
    assert out["pages"] == {"taken": 3, "available": 2, "searches": 2}
    rec_ = json.loads(week_file(client, LEAGUE, 1).read_text())
    assert rec_["start"] == "2026-10-19" and rec_["end"] == "2026-10-25"
    t1 = rec_["teams"]["1"]
    assert t1["opponent"] == 2 and t1["result"] == {"won": 5, "lost": 3, "tied": 1, "outcome": "W"}
    assert t1["totals"]["fgm"] == 161.0 and t1["totals"]["fga"] == 342.0
    assert t1["games"] == {"played": 28, "scheduled": 28}
    assert rec_["matchups"] == [
        {"teams": [1, 2], "score": [5.0, 3.0], "winner": 1},
        {"teams": [3, 4], "score": [4.0, 4.0], "winner": None},
    ]
    assert rec_["standings"]["through"] == "2026-10-25"
    assert by_team(rec_["standings"]["teams"])[1]["wins"] == 5
    players = {p["player"]: p for p in rec_["players"]["rows"]}
    assert len(players) == 12 and rec_["players"]["from"] == LEAGUE
    assert players[1005]["drafted_by"] == 4 and players[1005]["team"] == 2  # traded
    assert players[1011]["team"] == "FA" and players[1011]["line"]["pts"] == line(1011)["pts"]
    # Found by the search: his games from his totals over his averages.
    assert players[1012]["line"]["gp"] == line(1012)["gp"]
    assert players[1010]["line"] is None and rec_["missing"] == {"players": [1010]}
    assert out["summary"]["opponent"] == 2 and out["summary"]["rank"] == 1


def test_recording_the_same_week_again_changes_nothing(client):
    assert client.post(f"/seasons/{LEAGUE}/record").json()["status"] == "recorded"
    path = week_file(client, LEAGUE, 1)
    before = path.read_bytes()
    # Later the same Monday: the pages read again, the draft not.
    client.clock["now"] = datetime(2026, 10, 26, 16, 30, tzinfo=UTC)
    client.fake.urls.clear()
    r = client.post(f"/seasons/{LEAGUE}/record")
    assert r.json()["status"] == "unchanged"
    assert path.read_bytes() == before
    assert not any("draftresults" in u for u in client.fake.urls)


def test_a_stat_correction_revises_the_week(client):
    first = client.post(f"/seasons/{LEAGUE}/record").json()["summary"]
    client.fake.bump = 3
    client.clock["now"] = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)
    r = client.post(f"/seasons/{LEAGUE}/record", params={"week": 1})
    assert r.json()["status"] == "revised"
    rec_ = json.loads(week_file(client, LEAGUE, 1).read_text())
    assert rec_["teams"]["1"]["totals"]["pts"] == team_stats(1, 1)["pts"] + 3
    assert rec_["recorded_at"] == first["recorded_at"]
    assert rec_["revised_at"] == "2026-10-27T14:00:00+00:00"
    # Read a day late, the standings and the lines stay those of the week's end.
    assert rec_["standings"]["through"] == "2026-10-25"
    assert rec_["players"]["through"] == "2026-10-25"


def test_the_recorded_results_sum_to_the_standings(client):
    client.post(f"/seasons/{LEAGUE}/record")
    client.fake.week, client.clock["now"] = 2, AFTER_2
    assert client.post(f"/seasons/{LEAGUE}/record").json()["week"] == 2
    weeks = [json.loads(week_file(client, LEAGUE, w).read_text()) for w in (1, 2)]
    for upto, rec_ in enumerate(weeks, 1):
        table = by_team(rec_["standings"]["teams"])
        for team in TEAMS:
            results = [w["teams"][str(team)]["result"] for w in weeks[:upto]]
            summed = tuple(sum(r[k] for r in results) for k in ("won", "lost", "tied"))
            assert summed == (table[team]["wins"], table[team]["losses"], table[team]["ties"])
    history = client.get(f"/seasons/{LEAGUE}/weeks").json()
    assert [(w["week"], w["opponent"], w["record"]) for w in history["weeks"]] == [
        (1, 2, "5-3-1"),
        (2, 3, "11-5-2"),
    ]
    assert client.get(f"/seasons/{LEAGUE}/weeks/2").json()["week"] == 2
    assert client.get(f"/seasons/{LEAGUE}/weeks/3").status_code == 404


def test_a_points_leagues_week_sums_to_its_points_for(client):
    out = client.post(f"/seasons/{POINTS}/record").json()
    rec_ = json.loads(week_file(client, POINTS, 1).read_text())
    table = by_team(rec_["standings"]["teams"])
    for team in TEAMS:
        result = rec_["teams"][str(team)]["result"]
        assert result["points"] == table[team]["points_for"]
        outcome = {"W": (1, 0, 0), "L": (0, 1, 0), "T": (0, 0, 1)}[result["outcome"]]
        assert outcome == (table[team]["wins"], table[team]["losses"], table[team]["ties"])
    assert rec_["teams"]["1"]["totals"]["fpts"] == 810.5
    assert rec_["teams"]["1"]["totals_from"] == "players"
    assert out["summary"]["result"] == {"points": 810.5, "against": 790.25, "outcome": "W"}


def test_a_week_not_over_or_unknown_is_refused(client):
    assert client.post(f"/seasons/{LEAGUE}/record", params={"week": 2}).status_code == 409
    assert client.post(f"/seasons/{LEAGUE}/record", params={"week": 9}).status_code == 404
    client.clock["now"] = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    r = client.post(f"/seasons/{LEAGUE}/record")
    assert r.status_code == 409 and "no week is over" in r.json()["detail"]
    assert client.get(f"/seasons/{LEAGUE}/weeks").json()["weeks"] == []


def snapshot(client, league: str, url: str, html: str, at: datetime):
    body = {"pages": [{"url": url, "html": html, "fetched_at": at.isoformat()}]}
    r = client.post(f"/seasons/{league}/snapshot", json=body)
    assert r.status_code == 200 and not r.json()["skipped"], r.text
    return r


def test_a_private_league_names_the_pages_it_needs_then_records(client):
    during = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)
    # My matchup read during the week: its pair is known, its totals are not final.
    snapshot(
        client,
        PRIVATE,
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=1&mid2=2",
        matchup_html(PRIVATE, 1, 1, 2, False),
        during,
    )
    r = client.post(f"/seasons/{PRIVATE}/record")
    assert r.status_code == 409
    needs = r.json()["detail"]["needs"]
    # The weeks ahead whose pairs the Season view lacks: the league page shown for each.
    assert r.json()["detail"]["ahead"] == [f"{SITE}/{PRIVATE}?matchup_week=3"]
    assert needs == [
        f"{SITE}/{PRIVATE}",
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=1&mid2=2",
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=3",
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=4",
        f"{SITE}/{PRIVATE}/draftresults",
    ]
    # The extension posts what the user's Chrome opened: the league page, a matchup page by one
    # team (its opponent named by the page), the draft results, and the rosters.
    snapshot(client, PRIVATE, needs[0], league_html(PRIVATE, 1, False), AFTER_1)
    snapshot(client, PRIVATE, needs[1], matchup_html(PRIVATE, 1, 1, 2, False), AFTER_1)
    still = client.post(f"/seasons/{PRIVATE}/record").json()["detail"]["needs"]
    # Team 3's opponent is not known until its page is read: the page by team 3 covers team 4.
    assert still == [
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=3",
        f"{SITE}/{PRIVATE}/matchup?week=1&mid1=4",
        f"{SITE}/{PRIVATE}/draftresults",
    ]
    still = [still[0], still[2]]
    snapshot(client, PRIVATE, still[0], matchup_html(PRIVATE, 1, 3, 4, False), AFTER_1)
    snapshot(client, PRIVATE, still[1], draft_html(), AFTER_1)
    rosters = [
        {"key": f"roster/{t}", "data": {"team_id": t, "name": f"Team {t}", "spots": [
            {"slot": "BN", "player": {"yahoo_id": pid, "name": f"Player {pid}"}}
            for pid, owner in OWNER.items() if owner == t and pid < 1010
        ]}}
        for t in TEAMS
    ]  # fmt: skip
    client.post(f"/seasons/{PRIVATE}/snapshot", json={"parts": rosters})
    client.fake.urls.clear()
    out = client.post(f"/seasons/{PRIVATE}/record")
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "recorded"
    assert out.json()["ahead"] == [f"{SITE}/{PRIVATE}?matchup_week=3"]
    rec_ = json.loads(week_file(client, PRIVATE, 1).read_text())
    assert rec_["sources"] == {"pages": "extension", "players": LEAGUE}
    assert rec_["teams"]["3"]["result"]["outcome"] == "T"
    players = {p["player"]: p for p in rec_["players"]["rows"]}
    # The lines from the public league's pages, who has them from the private league's rosters.
    assert rec_["players"]["owners"] == "rosters"
    assert players[1005]["team"] == 2 and players[1011]["team"] is None
    assert players[1011]["line"]["pts"] == line(1011)["pts"]
    assert all(f"/nba/{LEAGUE}/" in u for u in client.fake.urls if "fantasysports" in u)
    # Once the week's page is posted, nothing is left ahead.
    week3 = league_html(PRIVATE, 1, False).replace(
        "</body>",
        f'<a href="/nba/{PRIVATE}/matchup?week=3&mid1=1&mid2=4">1 v 4</a>'
        f'<a href="/nba/{PRIVATE}/matchup?week=3&mid1=2&mid2=3">2 v 3</a></body>',
    )
    snapshot(client, PRIVATE, f"{SITE}/{PRIVATE}?matchup_week=3", week3, AFTER_1)
    assert client.post(f"/seasons/{PRIVATE}/record").json()["ahead"] == []


def test_the_draft_is_read_once_per_league(client):
    client.post(f"/seasons/{LEAGUE}/record")
    state = json.loads((client.data_dir / "leagues" / LEAGUE / "season" / "state.json").read_text())
    assert len(state["parts"]["draft"]["data"]["picks"]) == 12
    client.fake.week, client.clock["now"] = 2, AFTER_2
    client.fake.urls.clear()
    client.post(f"/seasons/{LEAGUE}/record")
    assert not any("draftresults" in u for u in client.fake.urls)


# --------------------------------------------------------------------------- the script
def load_script():
    spec = importlib.util.spec_from_file_location("season_script_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_script_prints_one_line_per_league(client):
    script = load_script()

    def call(method: str, path: str) -> tuple[int, object]:
        r = client.request(method, path)
        return r.status_code, r.json()

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = script.record_all(call, week=None)
    lines = buf.getvalue().strip().splitlines()
    assert code == 0 and len(lines) == 3
    assert lines[0].startswith(f"{LEAGUE} week 1: recorded")
    assert lines[1].startswith(f"{PRIVATE} week 1: needs pages (")
    assert f"{SITE}/{PRIVATE}/draftresults" in lines[1]
    assert f"; schedule pages (1): {SITE}/{PRIVATE}?matchup_week=3; lineup pages (" in lines[1]
    # The lineup pages (#107): the settings page until read, then my team page by day.
    assert (
        f"lineup pages (8): {SITE}/{PRIVATE}/settings {SITE}/{PRIVATE}/2?date=2026-10-26 "
        in lines[1]
    )
    assert lines[2].startswith(f"{POINTS} week 1: recorded")


def test_the_script_fails_only_when_the_api_is_unreachable():
    script = load_script()

    def down(method: str, path: str):
        raise script.Unreachable("connection refused")

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert script.record_all(down, week=None) == 2
    assert "unreachable" in buf.getvalue()
