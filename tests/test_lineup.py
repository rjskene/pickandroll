"""Lineups and held slots (#107, #124): the settings page's held slots and lineup rule, the day's
lineup pages, the recommended lineup against Yahoo's, the cleared IL occupant and the digest's
lineup line.

The settings page fixture is cut from a public prize league's page with the league's id and name
replaced; the team pages are the season fixtures with their slots moved. Nothing here is from
Basketball Monster: the projection is the season tests' made-up one.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from datetime import date, timedelta

import pytest

from pickandroll.api import season_lineup
from pickandroll.season import Player, RosterSpot, Season, SeasonSettings, Week
from pickandroll.season import lineup as lu
from pickandroll.season import weekly as wk
from pickandroll.season.state import SLOTS_PAGE, SLOTS_ROSTERS
from pickandroll.sources.yahoo import pages, public
from tests.test_season import (
    CATS,
    LEAGUE,
    NOW,
    ROSTER,
    TODAY,
    base,
    fixture,
    fixture_names,
    part,
    projection_csv,
    season_client,
    wait_for_job,
)

SITE = "https://basketball.fantasysports.yahoo.com/nba"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


WEEK = [date(2026, 10, 19) + timedelta(days=n) for n in range(7)]
STARTING = [s for s in ROSTER if s != "BN"]


def moved(html: str, slots: dict[str, str] | None = None, bench_all: bool = False) -> str:
    """A team page with players moved: ``slots`` by player name, or everyone to the bench."""
    rows = html.split("<tr")
    out = []
    for row in rows:
        new = row
        if bench_all:
            new = re.sub(r'data-pos="[^"]*">[^<]*<', 'data-pos="BN">BN<', new, count=1)
        for name, slot in (slots or {}).items():
            if f'title="{name}"' in new:
                new = re.sub(r'data-pos="[^"]*">[^<]*<', f'data-pos="{slot}">{slot}<', new, count=1)
        out.append(new)
    return "<tr".join(out)


# --------------------------------------------------------------------------- the pages
def test_the_settings_page_gives_the_held_slots_the_lineup_rule_and_the_playoffs():
    d = pages.parse_settings_page(fixture("settings_page.html"))
    assert d["roster"] == [*ROSTER, "IL", "IL", "IL"]
    assert (d["lineup_deadline"], d["lineup_changes"], d["lineup_from"]) == (
        "Daily - Today",
        "daily",
        "today",
    )
    assert d["playoff_weeks"] == [20, 21, 22]
    assert d["injured_add_to_slot"] is False
    # The bracket's rules (#172): the tie-breaker as printed, reseeding and divisions.
    assert d["playoff_tiebreak"] == "Higher seed wins"
    assert d["playoff_reseeding"] is True and d["divisions"] is False
    with pytest.raises(pages.PageError):
        pages.parse_settings_page("<html><body><table></table></body></html>")


def test_a_settings_page_without_the_bracket_rows_leaves_them_unread():
    html = fixture("settings_page.html")
    for label in ("Playoff Tie-Breaker", "Playoff Reseeding", "Divisions"):
        html = re.sub(rf"<tr[^>]*>\s*<td[^>]*>{label}:</td>.*?</tr>", "", html, flags=re.DOTALL)
    d = pages.parse_settings_page(html)
    assert d["playoff_weeks"] == [20, 21, 22]
    assert (d["playoff_tiebreak"], d["playoff_reseeding"], d["divisions"]) == (None, None, None)


@pytest.mark.parametrize(
    ("deadline", "rule"),
    [
        ("Daily - Today", ("daily", "today")),
        ("Daily - Tomorrow", ("daily", "tomorrow")),
        ("Weekly - Monday", ("weekly", None)),
        ("Something new", (None, None)),
        (None, (None, None)),
    ],
)
def test_the_lineup_deadline_says_daily_or_weekly(deadline, rule):
    assert pages.lineup_rule(deadline) == rule


def test_a_dated_team_page_and_the_settings_page_are_their_own_kinds():
    assert pages.page_kind(f"{SITE}/{LEAGUE}/4?date=2026-10-22") == (
        "team",
        {"league": LEAGUE, "team_id": 4, "date": date(2026, 10, 22)},
    )
    assert pages.page_kind(f"{SITE}/{LEAGUE}/settings") == ("settings", {"league": LEAGUE})
    with pytest.raises(pages.PageError):
        pages.page_kind(f"{SITE}/{LEAGUE}/4?date=soon")
    assert public.settings_page_url(LEAGUE) == f"{SITE}/{LEAGUE}/settings"


# --------------------------------------------------------------------------- the season state
def rosters(il: dict[int, int]) -> list:
    """Team pages with ``il[team]`` players in IL slots."""
    out = []
    for team, n in il.items():
        spots = [
            {"slot": "IL", "player": {"yahoo_id": 100 * team + i, "name": f"P{team}{i}"}}
            for i in range(n)
        ]
        out.append(
            part(f"roster/{team}", {"team_id": team, "name": f"Team {team}", "spots": spots})
        )
    return out


def test_the_settings_page_is_the_source_of_the_held_slots():
    page = pages.parse_settings_page(fixture("settings_page.html"))
    parts = {p.key: p for p in [part("league_settings", page), *rosters({1: 1})]}
    s = Season.from_parts(base(), parts).settings
    assert s.roster == (*ROSTER, "IL", "IL", "IL") and s.held_slots == {"IL": 3}
    assert s.held_from == SLOTS_PAGE
    assert (s.lineup_changes, s.lineup_from, s.lineup_deadline) == (
        "daily",
        "today",
        "Daily - Today",
    )
    # The page names the playoff weeks: no estimate from the bracket.
    assert s.first_playoff_week == 20 and s.injured_add_to_slot is False
    # And the bracket's rules, carried through the settings' round trip (#172).
    assert (s.playoff_tiebreak, s.playoff_reseeding, s.divisions) == (
        "Higher seed wins",
        True,
        False,
    )
    again = SeasonSettings.from_dict(s.to_dict())
    assert (again.playoff_tiebreak, again.playoff_reseeding, again.divisions) == (
        "Higher seed wins",
        True,
        False,
    )
    assert SeasonSettings.from_dict(base().to_dict()).playoff_tiebreak is None


def test_without_the_settings_page_the_held_slots_are_the_most_any_roster_fills():
    # The folder's own roster (the draft's) lists IL slots; it is never used for them.
    folder = SeasonSettings(LEAGUE, "categories", tuple(CATS), (*ROSTER, "IL", "IL", "IL"), 12, 4)
    parts = {p.key: p for p in rosters({1: 1, 2: 2, 3: 0})}
    parts["settings"] = part("settings", {"weekly_deadline": "intraday"})
    s = Season.from_parts(folder, parts).settings
    assert s.roster == (*ROSTER, "IL", "IL") and s.held_slots == {"IL": 2}
    assert s.held_from == SLOTS_ROSTERS
    # v3's ``intraday`` is a daily lineup, counting today.
    assert (s.lineup_changes, s.lineup_from) == ("daily", "today")
    # Nothing read: no held slot and nothing to say where one came from.
    s = Season.from_parts(folder, {}).settings
    assert s.held_slots == {} and s.held_from is None and s.lineup_changes is None


def test_a_days_lineup_page_is_kept_by_team_and_day():
    spots = [{"slot": "BN", "player": {"yahoo_id": 5, "name": "Five"}}]
    data = {"team_id": 4, "name": "Team 4", "spots": spots}
    season = Season.from_parts(base(), {"lineup/4/2026-10-22": part("lineup/4/2026-10-22", data)})
    assert season.lineups == {4: {date(2026, 10, 22): (RosterSpot("BN", Player(5, "Five")),)}}
    assert season.rosters == {}


# --------------------------------------------------------------------------- the comparison
def p(key: int, *positions: str, team: str = "AAA") -> tuple[int, Player]:
    return key, Player(key, f"P{key}", team, positions)


def test_yahoos_lineup_loses_the_games_its_bench_plays():
    day = WEEK[2]
    playing = {1: [day], 2: [day], 3: []}
    rec = {1: "C", 2: "Util"}
    benched = [
        RosterSpot("C", Player(3, "P3")),
        RosterSpot("BN", Player(1, "P1")),
        RosterSpot("Util", Player(2, "P2")),
    ]
    line = lu.compare(day, rec, benched, playing, ("C", "Util"))
    assert line.lost == 1 and line.start == (1,) and line.sit == (3,)
    assert line.recommended == (("C", 1), ("Util", 2))
    # The same players in other slots lose nothing and are no difference.
    swapped = [RosterSpot("Util", Player(1, "P1")), RosterSpot("C", Player(2, "P2"))]
    line = lu.compare(day, rec, swapped, playing, ("C", "Util"))
    assert line.lost == 0 and line.start == () and line.sit == ()
    # Not read: nothing to compare.
    line = lu.compare(day, rec, None, playing, ("C", "Util"))
    assert line.lost is None and line.yahoo is None


def test_a_starter_with_no_game_sits_only_when_his_slot_is_needed():
    day = WEEK[6]
    slots = ("C", "Util", "Util")
    playing = {1: [day], 2: [day]}
    rec = {1: "C", 2: "Util"}
    idle = [
        RosterSpot("C", Player(3, "P3", positions=("C",))),
        RosterSpot("Util", Player(4, "P4", positions=("PG",))),
        RosterSpot("Util", Player(5, "P5", positions=("SG",))),
        RosterSpot("BN", Player(1, "P1", positions=("C",))),
        RosterSpot("BN", Player(2, "P2", positions=("PF",))),
    ]
    line = lu.compare(day, rec, idle, playing, slots)
    # Two starts need two slots: one of the three idle starters stays where he is.
    assert line.lost == 2 and line.start == (1, 2) and len(line.sit) == 2
    assert set(line.sit) < {3, 4, 5}
    # A starter who plays sits when a better player needs his slot: the positions decide.
    playing = {1: [day], 2: [day], 6: [day]}
    crowded = [
        RosterSpot("C", Player(6, "P6")),
        RosterSpot("PG", Player(2, "P2")),
        RosterSpot("BN", Player(1, "P1")),
    ]
    roster = {1: ("C",), 2: ("PG",), 6: ("C",)}
    line = lu.compare(day, {1: "C", 2: "PG"}, crowded, playing, ("C", "PG"), roster)
    assert line.lost == 0 and line.start == (1,) and line.sit == (6,)


def test_two_slots_of_a_kind_take_their_players_in_turn():
    assert lu.by_slot({7: "C", 3: "C", 5: "PG"}, ("PG", "C", "C", "Util")) == (
        ("PG", 5),
        ("C", 3),
        ("C", 7),
        ("Util", None),
    )


def test_a_weekly_lineup_starts_the_most_games_times_value():
    roster = [p(1, "C"), p(2, "C"), p(3, "C")]
    playing = {1: WEEK[:4], 2: WEEK[:2], 3: WEEK[:1]}
    value = {1: 1.0, 2: 1.5, 3: 5.0}
    # Four games at 1.0 lose to two at 1.5 and one at 5.0: the slot goes to the 5.0 player.
    assert lu.weekly_lineup(roster, playing, WEEK, ("C",), value) == {3: "C"}
    assert lu.weekly_lineup(roster, playing, WEEK, ("C", "C"), value) == {3: "C", 1: "C"}


# --------------------------------------------------------------------------- games lost (#149)
def test_a_benched_player_who_played_is_lost_when_a_slot_he_fits_was_open_or_idle():
    slots = ("PG", "C", "Util")
    spots = [
        ("PG", 1, ("PG",)),
        ("C", 2, ("C",)),  # no game: his slot is idle
        ("BN", 3, ("C",)),  # played: the idle C was his
        ("BN", 4, ("SG",)),  # played: Util was open
        ("BN", 5, ("PF",)),  # no game: nothing lost
        ("IL", 6, ("PG",)),  # held: never a game lost
    ]
    assert lu.lost_games(spots, {1, 3, 4, 6}, slots) == 2
    # Everyone who played started: nothing lost.
    assert lu.lost_games(spots, {1, 2}, slots) == 0


def test_two_benched_players_who_could_take_one_slot_count_once():
    slots = ("C", "PG")
    spots = [("C", 1, ("C",)), ("PG", 2, ("PG",)), ("BN", 3, ("C",)), ("BN", 4, ("C",))]
    # The C slot's starter had no game: one of the two benched centres could have started.
    assert lu.lost_games(spots, {2, 3, 4}, slots) == 1


def test_a_benched_player_counts_when_a_starter_could_move_to_free_his_slot():
    slots = ("C", "F")
    # 3 fits only C, whose starter played; that starter also fits F, where 2 had no game.
    spots = [("C", 1, ("PF", "C")), ("F", 2, ("SF",)), ("BN", 3, ("C",))]
    assert lu.lost_games(spots, {1, 3}, slots) == 1
    # A starter who fits nowhere else holds his slot: nothing lost.
    spots = [("C", 1, ("C",)), ("F", 2, ("SF",)), ("BN", 3, ("C",))]
    assert lu.lost_games(spots, {1, 3}, slots) == 0


def test_a_weeks_games_lost_sum_the_days_read_and_count_the_unmatched_once():
    slots = ("C", "PG")
    lineup = [("C", 1, ("C",)), ("BN", 2, ("PG",)), ("BN", 9, ("SG",)), ("NA", 8, ("C",))]
    lineups = {WEEK[0]: lineup, WEEK[1]: lineup, WEEK[3]: lineup}
    # Day 3 has no box scores and day 2 no lineup read after it: neither is read.
    played = {WEEK[0]: {1, 2}, WEEK[1]: {2}, WEEK[2]: {1, 2}}
    out = lu.week_lost(WEEK, lineups, played, slots, matched={1, 2})
    # 9 matched no box score: once, though on two days; 8 is held and never counted.
    assert out == {"lost": 2, "days_read": 2, "days": 7, "unmatched": 1}
    assert lu.week_lost(WEEK, {}, played, slots, matched={1, 2}) == {
        "lost": None,
        "days_read": 0,
        "days": 7,
        "unmatched": 0,
    }


class Box:
    """The box-score cache as ``week_lost`` reads it: games by day and the ESPN ids known."""

    def __init__(self, games: dict[date, list[dict]], ids: dict[int, str]):
        self.games, self.ids = games, ids

    def days(self, first: date, last: date) -> dict[date, list[dict]]:
        return {d: g for d, g in self.games.items() if first <= d <= last}

    def match(self, players, games) -> dict[int, tuple[str, str]]:
        return {k: (self.ids[k], "id") for k in players if k in self.ids}


def game(**lines: dict | None) -> list[dict]:
    return [{"id": "1", "players": {e: {"line": line} for e, line in lines.items()}}]


def test_only_a_lineup_read_after_its_day_counts_and_the_box_scores_say_who_played():
    def spot(slot: str, key: int, *positions: str) -> dict:
        return {
            "slot": slot,
            "player": {"yahoo_id": key, "name": f"P{key}", "positions": positions},
        }

    lineup = {"team_id": 4, "spots": [spot("C", 1, "C"), spot("BN", 2, "PG"), spot("IL", 3, "PG")]}
    after = NOW.replace(day=20)  # Oct 20, 14:00 Eastern
    parts = {
        # Oct 19 read the next day: final. Oct 20 read that afternoon: not final.
        "lineup/4/2026-10-19": part("lineup/4/2026-10-19", lineup, at=after),
        "lineup/4/2026-10-20": part("lineup/4/2026-10-20", lineup, at=after),
        # Oct 21 read after it, but its box scores are not cached.
        "lineup/4/2026-10-21": part("lineup/4/2026-10-21", lineup, at=NOW.replace(day=23)),
    }
    season = Season.from_parts(base(), parts)
    week = Week(1, WEEK[0], WEEK[-1])
    assert set(season_lineup.final_reads(season, 4, WEEK)) == {WEEK[0], WEEK[2]}
    played = {"pts": 10.0}
    box = Box(
        {WEEK[0]: game(e1=played, e2=played, e3=played), WEEK[1]: game(e2=played)},
        {1: "e1", 2: "e2", 3: "e3"},
    )
    # Oct 19: the benched PG played with PG open; the held player's game is no loss.
    assert season_lineup.week_lost(season, week, box) == {
        "lost": 1,
        "days_read": 1,
        "days": 7,
        "unmatched": 0,
    }
    # A line of None is a player on the report who did not play.
    box.games[WEEK[0]] = game(e1=played, e2=None)
    assert season_lineup.week_lost(season, week, box)["lost"] == 0
    # A league without a team of mine has no count.
    assert season_lineup.week_lost(Season.from_parts(base(my_team=None), parts), week, box) is None


# --------------------------------------------------------------------------- the route
def lineup_league(client, **pages_by_day) -> None:
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    client.fake.every_day = True
    for day, html in pages_by_day.items():
        client.fake.lineups[4, date.fromisoformat(day)] = html
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202, r.text


def test_the_lineup_route_recommends_each_day_and_counts_what_yahoo_loses(client):
    lineup_league(client, **{"2026-10-22": moved(fixture("team4.html"), bench_all=True)})
    r = client.get(f"/seasons/{LEAGUE}/lineup")
    assert r.status_code == 200, r.text
    lu_ = r.json()
    assert (lu_["week"], lu_["start"], lu_["end"], lu_["first"]) == (
        1,
        "2026-10-19",
        "2026-10-25",
        "2026-10-21",
    )
    # The weeks the view can show: this one and the moves' three after it.
    assert lu_["weeks"] == [1, 2, 3, 4]
    assert lu_["rule"] == {
        "changes": "daily",
        "from": "today",
        "deadline": "Daily - Today",
        "source": "settings page",
    }
    days = {d["date"]: d for d in lu_["days"]}
    assert [d["past"] for d in lu_["days"]] == [True, True, False, False, False, False, False]
    # A day before the first shows Yahoo's lineup alone.
    assert days["2026-10-19"]["recommended"] is None and days["2026-10-19"]["yahoo"] is not None
    v = client.get(f"/seasons/{LEAGUE}").json()
    positions = {s["player"]["yahoo_id"]: s["player"]["positions"] for s in v["roster"]}
    for d in lu_["days"][2:]:
        # Slot by slot in the league's order, every player legal where he stands.
        assert [x["slot"] for x in d["recommended"]] == STARTING
        for x in d["recommended"]:
            if x["player"] is not None:
                assert wk.accepts(x["slot"], positions[x["player"]])
        assert d["games"]["recommended"] >= d["games"]["yahoo"]
        assert d["lost"] == d["games"]["recommended"] - d["games"]["yahoo"]
    # Everyone benched on Thursday: every game the recommendation starts is lost.
    thu = days["2026-10-22"]
    assert thu["games"]["yahoo"] == 0 and thu["lost"] == thu["games"]["recommended"] > 0
    assert sorted(thu["start"]) == sorted(x["player"] for x in thu["recommended"] if x["player"])
    assert {x["slot"] for x in thu["yahoo"]["slots"]} == {"BN"} and thu["sit"] == []
    # Each day names whoever of mine plays: every recommended starter, and no one else starts.
    for d in lu_["days"][2:]:
        starters = {x["player"] for x in d["recommended"] if x["player"]}
        assert starters <= set(d["playing"]) and len(starters) == d["games"]["recommended"]
    assert lu_["summary"]["lost"] >= thu["lost"] and "2026-10-22" in lu_["summary"]["differ"]
    # The league's three IL slots, all open; my out bench player could go to one.
    held = lu_["held"]
    assert [x["slot"] for x in held["slots"]] == ["IL", "IL", "IL"]
    assert held["open"] == {"IL": 3} and held["source"] == SLOTS_PAGE and not held["lower_bound"]
    by_name = {x["name"]: int(k) for k, x in lu_["players"].items()}
    assert held["eligible"] == [{"player": by_name["Aaron Nesmith"], "slots": ["IL"]}]
    assert lu_["alerts"] == [] and lu_["needs"] == []
    # A later week of the moves' four: every day recommended, none read; outside them, none.
    later = client.get(f"/seasons/{LEAGUE}/lineup", params={"week": 2}).json()
    assert not any(d["past"] for d in later["days"]) and len(later["summary"]["unread"]) == 7
    assert client.get(f"/seasons/{LEAGUE}/lineup", params={"week": 9}).status_code == 404


def test_a_player_held_now_but_benched_on_an_earlier_days_page_leaves_the_lineup_alone(client):
    """#196: Jakob Poeltl (healthy, his team plays Wednesday) sits in IL in the snapshot and on
    the bench of Tuesday's page: his games ahead are in the payload's playing days, and the
    recommendation is the active roster's alone."""
    client.fake.team_pages[4] = moved(fixture("team4.html"), {"Jakob Poeltl": "IL"})
    lineup_league(client, **{"2026-10-20": moved(fixture("team4.html"), {"Jakob Poeltl": "BN"})})
    v = client.get(f"/seasons/{LEAGUE}").json()
    held = next(s["player"]["yahoo_id"] for s in v["roster"] if s["slot"] == "IL")
    r = client.get(f"/seasons/{LEAGUE}/lineup")
    assert r.status_code == 200, r.text
    days = {d["date"]: d for d in r.json()["days"]}
    assert {"slot": "BN", "player": held} in days["2026-10-20"]["yahoo"]["slots"]
    ahead = [d for d in days.values() if not d["past"]]
    # He plays the days ahead, as the compare counts him, and is never recommended nor benched.
    assert held in days["2026-10-21"]["playing"]
    for d in ahead:
        assert held not in {x["player"] for x in d["recommended"]} and held not in d["bench"]
    r = client.get(f"/seasons/{LEAGUE}/lineup/steps")
    assert r.status_code == 200, r.text


def test_a_held_player_whose_status_cleared_is_the_first_thing_said(client):
    """Paul Reed (healthy) sits in an IL slot: Yahoo refuses every add until he is activated."""
    client.fake.team_pages[4] = moved(fixture("team4.html"), {"Paul Reed": "IL"})
    lineup_league(client)
    v = client.get(f"/seasons/{LEAGUE}").json()
    reed = next(s["player"]["yahoo_id"] for s in v["roster"] if s["player"]["name"] == "Paul Reed")
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    [cleared] = m["cleared"]
    assert (cleared["player"], cleared["slot"], cleared["status"]) == (reed, "IL", None)
    assert cleared["from"] == "2026-10-21" and cleared["drop"] is not None
    alerts = client.get(f"/seasons/{LEAGUE}/lineup").json()["alerts"]
    assert alerts[0]["kind"] == "cleared" and alerts[0]["player"] == reed
    held = client.get(f"/seasons/{LEAGUE}/lineup").json()["held"]
    assert held["slots"][0] == {"slot": "IL", "player": reed, "cleared": True}
    # The digest says so first, names only.
    d = client.get("/flags/digest").json()
    [row] = [x for x in d["lineups"] if x["league"] == LEAGUE]
    drop = next(
        s["player"]["name"] for s in v["roster"] if s["player"]["yahoo_id"] == cleared["drop"]
    )
    assert row["cleared_line"] == (
        f"- League {LEAGUE}: Paul Reed sits in IL with no status and blocks every add until"
        f" activated; the activation would drop {drop}"
    )
    section = d["markdown"][d["markdown"].index("### Lineups") :]
    assert section.splitlines()[2] == row["cleared_line"]


def test_the_cleared_line_names_the_player_his_slot_status_and_the_drop():
    players = {"1": {"name": "One"}, "2": {"name": "Two"}}
    alerts = [
        {"kind": "held_lower_bound", "slots": {"IL": 1}},
        {"kind": "cleared", "player": 1, "slot": "IL", "status": "Q", "from": "x", "drop": 2},
    ]
    assert season_lineup.cleared_line("9", {"players": players, "alerts": alerts}) == (
        "- League 9: One sits in IL as Q and blocks every add until activated;"
        " the activation would drop Two"
    )
    alerts[1] = {**alerts[1], "drop": None}
    assert season_lineup.cleared_line("9", {"players": players, "alerts": alerts}).endswith(
        "until activated; an active spot is open for him"
    )
    assert season_lineup.cleared_line("9", {"players": players, "alerts": alerts[:1]}) is None


def test_the_digest_names_the_leagues_that_lose_games_as_set(client):
    lineup_league(client, **{"2026-10-22": moved(fixture("team4.html"), bench_all=True)})
    d = client.get("/flags/digest").json()
    [row] = [x for x in d["lineups"] if x["league"] == LEAGUE]
    assert row["lost"] > 0 and row["line"].startswith(f"- League {LEAGUE}: ")
    assert "Thu start " in row["line"] and " lost)" in row["line"]
    assert "### Lineups" in d["markdown"] and row["line"] in d["markdown"]


def test_the_digest_line_names_players_and_games_only_and_nothing_when_nothing_is_lost():
    players = {"1": {"name": "One"}, "2": {"name": "Two"}, "3": {"name": "Three"}}

    def day(iso, lost, start=(), sit=(), past=False):
        return {"date": iso, "past": past, "lost": lost, "start": list(start), "sit": list(sit)}

    lineup = {
        "players": players,
        "days": [
            day("2026-10-20", 3, [1], [2], past=True),
            day("2026-10-21", 1, [1], [2]),
            day("2026-10-22", 2, [1, 3]),
            day("2026-10-23", 4, [3], [2]),
        ],
    }
    line = season_lineup.digest_line("9", lineup, TODAY)
    # Today and tomorrow only; the day before and the day after are not in it.
    assert (
        line
        == "- League 9: Wed start One for Two (1 game lost); Thu start One, Three (2 games lost)"
    )
    quiet = {"players": players, "days": [day("2026-10-21", 0), day("2026-10-22", None)]}
    assert season_lineup.digest_line("9", quiet, TODAY) is None
    assert season_lineup.digest_section([]) == ""
    assert season_lineup.digest_section([line]) == f"\n### Lineups\n\n{line}\n"


def test_a_private_leagues_lineup_and_settings_pages_round_trip(client):
    # The shared calendar from a public league's refresh, as for any private league.
    lineup_league(client)
    site = f"{SITE}/100002"
    at = NOW.isoformat()
    r = client.post(
        "/seasons/100002/snapshot",
        json={
            "pages": [
                {"url": site, "html": fixture("league.html"), "fetched_at": at},
                {"url": site + "/7", "html": fixture("team4.html"), "fetched_at": at},
                {
                    "url": site + "/7?date=2026-10-22",
                    "html": fixture("team4.html"),
                    "fetched_at": at,
                },
                {
                    "url": site + "/settings",
                    "html": fixture("settings_page.html"),
                    "fetched_at": at,
                },
            ]
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == ["league", "roster/7", "lineup/7/2026-10-22", "league_settings"]
    wait_for_job(client, "100002")
    s = client.get("/seasons/100002").json()["settings"]
    assert s["held_from"] == SLOTS_PAGE and s["roster"].count("IL") == 3
    out = client.get("/seasons/100002/lineup").json()
    days = {d["date"]: d for d in out["days"]}
    assert days["2026-10-22"]["yahoo"]["page"] == "dated page"
    # Today's lineup is the team page read today; the days ahead not read today are to open.
    assert days["2026-10-21"]["yahoo"]["page"] == "team page"
    assert out["needs"] == [public.team_url("100002", 7, d) for d in WEEK[4:]]


def test_a_private_leagues_record_lists_its_lineup_pages(client):
    lineup_league(client)
    site = f"{SITE}/100002"
    client.post(
        "/seasons/100002/snapshot",
        json={"pages": [{"url": site, "html": fixture("league.html")}]},
    )
    wait_for_job(client, "100002")
    # A week later: week 1 is over, week 2 runs from Monday Oct 26.
    later = NOW + timedelta(days=7)
    client.app.state.seasons.clock = lambda: later
    r = client.post("/seasons/100002/record")
    body = r.json()
    detail = body["detail"] if r.status_code == 409 else body
    # The settings page until read, my team page for each day of this week from today, and for
    # each day of the week recorded not read after it (#149): none of week 1's was.
    days = [date(2026, 10, 28) + timedelta(days=n) for n in range(5)]
    assert detail["lineup_pages"] == [
        public.settings_page_url("100002"),
        *(public.team_url("100002", 7, d) for d in days),
        *(public.team_url("100002", 7, d) for d in WEEK),
    ]
    # A day read after it is no longer asked for.
    at = (later - timedelta(days=1)).isoformat()
    url = public.team_url("100002", 7, WEEK[0])
    page = {"url": url, "html": fixture("team4.html"), "fetched_at": at}
    assert client.post("/seasons/100002/snapshot", json={"pages": [page]}).status_code == 200
    wait_for_job(client, "100002")
    r = client.post("/seasons/100002/record")
    detail = r.json()["detail"] if r.status_code == 409 else r.json()
    assert url not in detail["lineup_pages"]
    assert public.team_url("100002", 7, WEEK[1]) in detail["lineup_pages"]


def dated(urls: list[str]) -> list[str]:
    return [u for u in urls if "?date=" in u and "/matchup" not in u and "/buzzindex" not in u]


def test_a_refresh_reads_a_past_day_again_until_it_was_read_after_the_day(client):
    # Read on Wednesday Oct 21: every day of week 1, the past two after their day.
    lineup_league(client)
    fake = client.fake
    service = client.app.state.seasons
    fake.urls.clear()
    service.clock = lambda: NOW + timedelta(days=1)
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    # Thursday: Wednesday was read on its own day, so once more; Monday and Tuesday were not.
    assert dated(fake.urls) == [public.team_url(LEAGUE, 4, d) for d in WEEK[2:]]
    # The next Monday: last week's days read on or before their day, then this week's.
    fake.urls.clear()
    service.clock = lambda: NOW + timedelta(days=5)
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    this = [date(2026, 10, 26) + timedelta(days=n) for n in range(7)]
    assert dated(fake.urls) == [public.team_url(LEAGUE, 4, d) for d in [*WEEK[3:], *this]]


def test_the_lineup_command_prints_one_line_per_league(client):
    from tests.test_record import load_script

    script = load_script()
    lineup_league(client, **{"2026-10-22": moved(fixture("team4.html"), bench_all=True)})

    def call(method: str, path: str) -> tuple[int, object]:
        r = client.request(method, path)
        return r.status_code, r.json()

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert script.lineup_all(call, days=2) == 0
    lines = dict(line.split(" ", 1) for line in buf.getvalue().strip().splitlines())
    assert lines[LEAGUE].startswith("week 1: ") and "Thu start " in lines[LEAGUE]
    assert " lost)" in lines[LEAGUE]
    # The private league has no season of its own yet: skipped, with why.
    assert lines["100002:"].startswith("skipped (409)")
