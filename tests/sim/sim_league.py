"""Made-up leagues for the simulator's tests (#172, PR 2b): a small in-memory setup the policy,
runner and checks run on, and a fixture data folder the readers and the script read. Every
player and team here is synthetic or from the anonymised season fixtures; the projection files
are made up in Basketball Monster's CSV layout and carry no figure of theirs."""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from pickandroll.season import build_calendar
from pickandroll.season import weekly as wk
from pickandroll.season.sim import league as lg
from pickandroll.season.sim import run as rn
from pickandroll.season.sim import state as sst
from pickandroll.season.sim.fit import Component, Hazard
from pickandroll.sources.yahoo import pages, public
from tests.sim_fixtures import synthetic_lines
from tests.test_gamelogs import entry

FIXTURES = Path(__file__).parent / "fixtures" / "season"
NINE = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")
PHI = {
    "pts": 1.5,
    "reb": 1.5,
    "ast": 1.2,
    "fga": 1.4,
    "fta": 1.8,
    "threes": 1.1,
    "stl": 1.0,
    "blk": 1.0,
    "tov": 1.0,
}
HAZARD = Hazard(
    0.05,
    (
        Component(1, 3, 0.7, {1: 0.5, 2: 0.3, 3: 0.2}),
        Component(4, 15, 0.25, {5: 0.5, 10: 0.5}),
        Component(16, None, 0.05, {20: 1.0}),
    ),
    runs=100,
    played=1000,
    players=20,
    censored=2,
    censored_share=0.1,
    leading=0,
)
KNOBS: dict[str, Any] = {
    "system": "bbm",
    "blend": None,
    "horizon_weight": "natural",
    "protection_floor": 0.0,
    "plan_floor_cats": 0.0,
    "plan_floor_points": 0.0,
    "stash_threshold": None,
    "faab_sizing": None,
    "daily_cap": 1,
}
NBA = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
POSITIONS = (("PG",), ("SG",), ("SF",), ("PF",), ("C",), ("PG", "SG"), ("SF", "PF"), ("PF", "C"))
MONDAY = date(2026, 10, 26)


def rates(level: float) -> dict[str, float]:
    return {
        "pts": 10 * level,
        "threes": 1 * level,
        "reb": 5 * level,
        "ast": 3 * level,
        "stl": 1 * level,
        "blk": 1 * level,
        "tov": 2.0,
        "fgm": 4.0 * level,
        "fga": 8.0 * level,
        "ftm": 2.0,
        "fta": 2.5,
    }


def alternating_schedule(first: date, days: int, teams=NBA) -> dict[date, frozenset[str]]:
    """Each team plays every other day, the teams staggered."""
    return {
        first + timedelta(i): frozenset(t for j, t in enumerate(teams) if (i + j) % 2 == 0)
        for i in range(days)
    }


def make_setup(
    teams: int = 4,
    spots: int = 5,
    pool: int = 8,
    weeks: int = 6,
    playoff_weeks: int = 1,
    playoff_teams: int = 2,
    seed: int = 3,
    statuses: dict[int, str] | None = None,
    max_weekly_adds: int | None = 4,
    bracket: bool = True,
    held_slots: tuple[str, ...] = (),
) -> sst.Setup:
    """``teams`` seats, ``spots`` players each (snake-drafted on the projection), ``pool`` free
    agents, a Monday-to-Sunday calendar of ``weeks`` weeks with the last ``playoff_weeks`` the
    bracket's, every team playing every other day; ``held_slots`` (IL, IL+, NA) after the bench."""
    rng = np.random.default_rng(seed)
    n = teams * spots + pool
    players = {}
    projection = {}
    for k in range(1, n + 1):
        players[k] = sst.Member(k, f"P{k}", NBA[k % len(NBA)], POSITIONS[k % len(POSITIONS)])
        projection[k] = rates(float(rng.uniform(0.6, 1.4)))
    cal = sst.weeks_from(MONDAY, weeks)
    regular = tuple(range(1, weeks - playoff_weeks + 1))
    ids = tuple(range(1, teams + 1))
    pairings = sst.round_robin(ids, regular)
    schedule = alternating_schedule(cal.weeks[0].start, 7 * weeks)
    value = wk.per_game_values(projection, NINE, None)
    keys = list(players)
    rosters = sst.snake_draft(keys, value, ids, spots)
    taken = {k for r in rosters.values() for k, _ in r}
    rounds = max(1, int(np.ceil(np.log2(playoff_teams))))
    spec = lg.LeagueSpec(
        ids,
        pairings,
        tuple(range(weeks - playoff_weeks + 1, weeks + 1)),
        NINE,
        "categories",
        None,
        playoff_teams,
        2**rounds - playoff_teams,
    )
    return sst.Setup(
        league="made-up",
        start=cal.weeks[0].start,
        calendar=cal,
        pairings=pairings,
        teams=ids,
        players=players,
        rosters=rosters,
        pool=tuple(k for k in keys if k not in taken),
        projection=projection,
        schedule=schedule,
        roster_slots=("PG", "SG", "G", "C", "Util", "BN", *held_slots),
        cats=NINE,
        max_weekly_adds=max_weekly_adds,
        statuses=statuses or {},
        market=value,
        market_rate=0.2,
        spec=spec if bracket else None,
        bracket_unread=None if bracket else "the settings page has not been read",
    )


def inputs(tau: float = 0.1, kappa: float = 0.1, sigma_eta: float = 0.05, lag: int = 1):
    return rn.WorldInputs(
        PHI, {}, 0.2, HAZARD, dict.fromkeys(wk.STATS, tau), kappa, sigma_eta, lag, "fit-sha"
    )


def arm(name: str = "A", tier: str = "exact", opponents: str = "market", **knobs: Any) -> rn.Arm:
    return rn.Arm(name, tier, {**KNOBS, **knobs}, {"kind": opponents})


# --------------------------------------------------------------------------- a data folder
LEAGUE = "100001"
MY_TEAM = 4
ROSTER = ["PG", "SG", "G", "C", "Util", "BN"]
YAHOO_CATS = ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
TODAY = date(2026, 10, 21)
#: The fixture league's calendar: six weeks from the Monday before opening night.
SEASON_FIRST = date(2026, 10, 20)
SEASON_END = date(2026, 11, 29)
PLAYOFF_WEEKS = [5, 6]
EXPORT_DATES = ("2026-10-19", "2026-10-22")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def fixture_players() -> list[dict[str, Any]]:
    return public.players_from_v3(json.loads(fixture("players.json")))


def _part(key: str, data: Any, at: str = "2026-10-21T18:00:00+00:00") -> dict[str, Any]:
    return {key: {"fetched_at": at, "source": "public", "data": data}}


def write_bbm_csv(path: Path, players: list[dict[str, Any]], seed: int) -> None:
    """A made-up rest-of-season export in the CSV layout: season totals over 70 games."""
    rng = np.random.default_rng(seed)
    cols = [
        "player_id",
        "last_name",
        "first_name",
        "games",
        "minutes",
        "field_goals_attempted",
        "field_goals",
        "free_throws_attempted",
        "free_throws",
        "threes",
        "threes_attempted",
        "offensive_rebounds",
        "defensive_rebounds",
        "assists",
        "blocks",
        "steals",
        "turnovers",
        "fouls",
        "technicals",
        "double_doubles",
        "triple_doubles",
        "comments",
    ]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i, p in enumerate(players):
            first, _, last = p["name"].partition(" ")
            level = float(rng.uniform(0.6, 1.4))
            g = 70
            fga = round(8 * level * g)
            fgm = round(0.47 * fga)
            fta = round(2.5 * level * g)
            ftm = round(0.78 * fta)
            w.writerow(
                [
                    1000 + i,
                    last,
                    first,
                    g,
                    round(28 * level * g),
                    fga,
                    fgm,
                    fta,
                    ftm,
                    round(1.2 * level * g),
                    round(3.2 * level * g),
                    round(1.0 * level * g),
                    round(4.0 * level * g),
                    round(3.0 * level * g),
                    round(0.8 * level * g),
                    round(1.0 * level * g),
                    round(2.0 * level * g),
                    0,
                    0,
                    0,
                    0,
                    "",
                ]
            )


def write_logs(data: Path, seasons: tuple[int, ...], players: list[dict[str, Any]]) -> None:
    """ESPN-shaped logs for ``seasons``: the fixture players under numeric ids (1000 + i), on six
    pro teams, with their positions as eligible slots."""
    folder = data / "external" / "espn" / "gamelogs"
    folder.mkdir(parents=True, exist_ok=True)
    slots = {"PG": 0, "SG": 1, "SF": 2, "PF": 3, "C": 4}
    for si, season in enumerate(seasons):
        rows = synthetic_lines(seed=200 + si, players=len(players), games=45, season=season)
        by_pid: dict[str, list] = {}
        for ln in rows:
            raw = (
                {
                    "0": ln.stats.get("pts"),
                    "1": ln.stats.get("blk"),
                    "2": ln.stats.get("stl"),
                    "3": ln.stats.get("ast"),
                    "6": ln.stats.get("reb"),
                    "11": ln.stats.get("tov"),
                    "13": round(0.47 * ln.stats.get("fga", 0.0)),
                    "14": ln.stats.get("fga"),
                    "15": round(0.78 * ln.stats.get("fta", 0.0)),
                    "16": ln.stats.get("fta"),
                    "17": ln.stats.get("threes"),
                    "40": ln.minutes,
                }
                if ln.played
                else {}
            )
            raw = {k: v for k, v in raw.items() if v is not None}
            i = int(ln.player[1:])
            by_pid.setdefault(str(1000 + i), []).append(
                entry(season, ln.period, raw, team=1 + i % 6)
            )
        body = {
            "players": [
                {
                    "player": {
                        "id": int(pid),
                        "fullName": players[int(pid) - 1000]["name"],
                        "proTeamId": 1 + (int(pid) - 1000) % 6,
                        "defaultPositionId": slots.get(players[int(pid) - 1000]["positions"][0], 0)
                        + 1,
                        "eligibleSlots": [
                            slots[p] for p in players[int(pid) - 1000]["positions"] if p in slots
                        ]
                        + [11, 12],
                        "stats": stats,
                    }
                }
                for pid, stats in by_pid.items()
            ]
        }
        (folder / f"{season}.json").write_text(json.dumps({"season": season, "body": body}))


def make_data_dir(tmp: Path, seasons: tuple[int, ...] = (2023, 2024, 2025, 2026)) -> Path:
    """A data folder with one public league's recorded season (twelve six-man teams drawn from
    the anonymised fixtures), two made-up exports, ESPN ids, synthetic logs and no fit yet."""
    data = tmp / "data"
    league_dir = data / "leagues" / LEAGUE
    season_dir = league_dir / "season"
    season_dir.mkdir(parents=True)
    (league_dir / "settings.json").write_text(
        json.dumps(
            {
                "league_id": LEAGUE,
                "scoring": "categories",
                "num_teams": 12,
                "roster": ROSTER,
                "my_team_id": MY_TEAM,
                "categories": YAHOO_CATS,
                "public": True,
            }
        )
    )
    players = fixture_players()
    league = pages.parse_league_page(fixture("league.html"))
    teams = [int(t["team_id"]) for t in league["teams"]]
    parts: dict[str, Any] = {}
    parts |= _part(
        "settings",
        {
            "name": "Test League 100001",
            "current_week": 1,
            "max_weekly_adds": 4,
            "playoff_teams": 4,
            "playoff_weeks": PLAYOFF_WEEKS,
            "playoff_tiebreak": "Higher seed wins",
            "playoff_reseeding": True,
            "divisions": False,
        },
    )
    parts |= _part("players", players)
    parts |= _part("league", league)
    rng = np.random.default_rng(11)
    order = list(range(len(players)))
    rng.shuffle(order)
    spots = len(ROSTER)
    used = 0
    for t in teams:
        mine = [players[order[used + j]] for j in range(spots)]
        used += spots
        mine[0] = {**mine[0], "status": "O", "status_full": "Out"} if t == MY_TEAM else mine[0]
        parts |= _part(
            f"roster/{t}",
            {
                "team_id": t,
                "name": f"Team {t}",
                "week": 1,
                "spots": [{"slot": s, "player": p} for s, p in zip(ROSTER, mine, strict=True)],
            },
        )
    left = [players[i] for i in order[used:]]
    parts |= _part(
        "available",
        {
            "rows": [
                {
                    "player": p,
                    "availability": "FA",
                    "clears": None,
                    "pct_rostered": 40.0 - i,
                    "pct_rostered_change": 0.0,
                    "pct_started": 10.0,
                    "pct_started_change": 0.0,
                    "adds": 10,
                    "drops": 5,
                }
                for i, p in enumerate(left)
            ]
        },
    )
    cal = build_calendar(SEASON_FIRST, SEASON_END)
    parts |= _part("calendar", cal.to_dict())
    nba = sorted({p["nba_team"] for p in players if p["nba_team"]})
    days = [
        cal.weeks[0].start + timedelta(i) for i in range((SEASON_END - cal.weeks[0].start).days + 1)
    ]
    parts |= _part(
        "schedule",
        {
            "days": {
                d.isoformat(): [t for j, t in enumerate(nba) if (i + j) % 2 == 0]
                for i, d in enumerate(days)
            }
        },
    )
    regular = [w.number for w in cal.weeks if w.number not in PLAYOFF_WEEKS]
    rr = sst.round_robin(tuple(teams), regular)
    for w in regular:
        if w in (1, 3):
            continue  # week 1 is the league page's; week 3 is left unread (assumed)
        parts |= _part(
            f"pairings/{w}", {"week": w, "matchups": [{"teams": list(p)} for p in rr[w]]}
        )
    parts |= _part("matchup/1/4-10", pages.parse_matchup_page(fixture("matchup.html")))
    parts |= _part(
        "transactions",
        {
            "rows": [
                {
                    "kind": "add",
                    "player": left[0],
                    "team_id": 4,
                    "team_name": "Team 4",
                    "detail": "Free Agent",
                    "when": "Oct 20, 3:57 am",
                    "group": 1,
                },
                {
                    "kind": "drop",
                    "player": left[1],
                    "team_id": 4,
                    "team_name": "Team 4",
                    "detail": "To Waivers",
                    "when": "Oct 20, 3:57 am",
                    "group": 1,
                },
                {
                    "kind": "add",
                    "player": left[2],
                    "team_id": 7,
                    "team_name": "Team 7",
                    "detail": "Free Agent",
                    "when": "Oct 19, 1:10 pm",
                    "group": 2,
                },
            ]
        },
    )
    # Yahoo's seven-day view of the available players: made-up totals over three games.
    parts |= _part(
        "yahoo_week",
        {
            "rows": [
                {
                    "player": p,
                    "gp": 3,
                    "seen_at": "2026-10-21T18:00:00+00:00",
                    **{s: round(3 * x * (1.1 - 0.01 * i), 1) for s, x in rates(1.0).items()},
                }
                for i, p in enumerate(left)
            ]
        },
    )
    (season_dir / "state.json").write_text(json.dumps({"league": LEAGUE, "parts": parts}))
    for i, d in enumerate(EXPORT_DATES):
        write_bbm_csv(data / f"bbm_projections_{d}.csv", players, seed=30 + i)
    (data / "aliases.json").write_text("{}")
    box = data / "boxscores"
    box.mkdir()
    (box / "ids.json").write_text(
        json.dumps({str(p["yahoo_id"]): str(1000 + i) for i, p in enumerate(players)})
    )
    write_logs(data, seasons, players)
    return data


__all__ = [
    "HAZARD",
    "KNOBS",
    "LEAGUE",
    "MY_TEAM",
    "NINE",
    "PHI",
    "TODAY",
    "arm",
    "inputs",
    "make_data_dir",
    "make_setup",
    "rates",
]
