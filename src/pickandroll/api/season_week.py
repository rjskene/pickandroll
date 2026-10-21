"""The season view's week projection (docs/ADD_DROP.md phase 2, #93).

Two projection systems give per-game rates by Yahoo player id: Basketball Monster's latest
rest-of-season export in ``data/`` (the one the draft uses, matched to Yahoo's players by name)
and Yahoo's own projection for the next seven days (the players page's ``S_PS7`` view, read by
the refresh or posted by the extension). The games come from the schedule, less the out rule; a
Basketball Monster weekly export (``bbm_week_this_*`` / ``bbm_week_next_*``) that covers a week
gives that week's games instead. The view sends each player's games per week and his per-game
rates per system (the web multiplies them out), and my matchup's projected finals and odds.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ..season import Matchup, Player, Season, matchup_key
from ..season import weekly as wk
from ..season.calendar import Week
from ..sources.bbm import PROJECTION_SUFFIXES, load_bbm
from ..sources.matching import load_aliases, match_players

#: Rest-of-season exports, newest first: the draft's Total Stats CSV or a per-game sheet.
BBM_ROS = ("bbm_projections_*", "bbm_ros_*")
#: Weekly exports (``sources.bbm.fetch.weekly``): the rest of this week and next week.
BBM_THIS_WEEK = "bbm_week_this_*"
BBM_NEXT_WEEK = "bbm_week_next_*"
NBA_TZ = ZoneInfo("America/New_York")
#: From this hour (Eastern) a matchup page read today holds some of today's games, so the
#: projection of the rest of the week starts tomorrow.
GAMES_BEGIN = time(19, 0)
SYSTEMS = ("bbm", "yahoo")


def _latest(data_dir: Path, patterns: Iterable[str]) -> Path | None:
    files = [
        f
        for pattern in patterns
        for f in data_dir.glob(pattern)
        if f.suffix.lower() in PROJECTION_SUFFIXES and "sample" not in f.name
    ]
    return max(files, key=lambda f: f.stat().st_mtime, default=None)


_frames: dict[tuple[str, float], pd.DataFrame] = {}
_matches: dict[tuple[str, float, int], dict[int, str]] = {}


def _frame(path: Path) -> pd.DataFrame:
    key = (str(path), path.stat().st_mtime)
    if key not in _frames:
        _frames.clear()
        _frames[key] = load_bbm(path).df
    return _frames[key]


def _per_game(row: pd.Series) -> dict[str, float] | None:
    games = float(row.get("games") or 0.0)
    if games <= 0:
        return None
    return {s: round(float(row.get(s) or 0.0) / games, 4) for s in wk.STATS}


def _yahoo_frame(players: Mapping[int, Player]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": [p.name for p in players.values()],
            "team": [p.nba_team or "" for p in players.values()],
        },
        index=[str(k) for k in players],
    )


def _match(
    path: Path, df: pd.DataFrame, players: Mapping[int, Player], data_dir: Path
) -> dict[int, str]:
    """Yahoo id -> the export's player id, cached per export and player set."""
    key = (str(path), path.stat().st_mtime, hash(tuple(sorted(players))))
    if key not in _matches:
        result = match_players(_yahoo_frame(players), df, load_aliases(data_dir / "aliases.json"))
        _matches.clear()
        _matches[key] = {int(k): v for k, v in result.mapping.items()}
    return _matches[key]


@dataclass(frozen=True)
class System:
    rates: Mapping[int, Mapping[str, float]]
    info: Mapping[str, Any]
    #: Players the system projects no games for.
    zero: frozenset[int] = frozenset()


def season_players(season: Season) -> dict[int, Player]:
    """Every player the season names: the pool, the rosters, the available and Yahoo's rows."""
    out: dict[int, Player] = dict(season.players)
    for spots in season.rosters.values():
        for s in spots:
            out[s.player.yahoo_id] = s.player
    for a in season.available:
        out[a.player.yahoo_id] = a.player
    for yid, r in season.yahoo_week.items():
        out.setdefault(yid, Player.from_dict(r["player"]))
    return out


def bbm_system(data_dir: Path, players: Mapping[int, Player]) -> System:
    path = _latest(data_dir, BBM_ROS)
    if path is None:
        return System({}, {"label": "Basketball Monster", "file": None})
    df = _frame(path)
    mapping = _match(path, df, players, data_dir)
    rates = {}
    for yid, pid in mapping.items():
        r = _per_game(df.loc[pid])
        if r is not None:
            rates[yid] = r
    as_of = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    info = {
        "label": "Basketball Monster",
        "file": path.name,
        "as_of": as_of.isoformat(),
        "players": len(rates),
    }
    return System(rates, info)


def yahoo_system(season: Season) -> System:
    rates: dict[int, dict[str, float]] = {}
    zero = set()
    seen = []
    for yid, r in season.yahoo_week.items():
        gp = float(r.get("gp") or 0.0)
        if r.get("seen_at"):
            seen.append(r["seen_at"])
        if gp <= 0:
            zero.add(yid)
            continue
        rates[yid] = {s: round(float(r.get(s) or 0.0) / gp, 4) for s in wk.STATS}
    info = {
        "label": "Yahoo, next 7 days",
        "as_of": max(seen) if seen else None,
        "players": len(rates),
    }
    return System(rates, info, frozenset(zero))


def _covers(path: Path, first: date, last: date, today: date) -> bool:
    """Whether a weekly export covers ``first``..``last``: its sidecar's dates when it has one
    (``sources.bbm.fetch`` writes them), else an export made today for the rest of this week."""
    meta = path.with_suffix(".json")
    try:
        d = json.loads(meta.read_text())
        return date.fromisoformat(d["start"]) == first and date.fromisoformat(d["end"]) == last
    except (OSError, ValueError, KeyError, TypeError):
        made = datetime.fromtimestamp(path.stat().st_mtime, UTC).astimezone(NBA_TZ).date()
        return first == today and made == today


def bbm_week_games(
    data_dir: Path,
    players: Mapping[int, Player],
    week: Week,
    first: date,
    today: date,
    this_week: bool,
) -> dict[int, int] | None:
    """The games a Basketball Monster weekly export gives each player for ``week`` from
    ``first``, when an export covers exactly that span; None otherwise."""
    path = _latest(data_dir, (BBM_THIS_WEEK if this_week else BBM_NEXT_WEEK,))
    if path is None or not _covers(path, first, week.end, today):
        return None
    df = _frame(path)
    mapping = _match(path, df, players, data_dir)
    return {yid: round(float(df.at[pid, "games"] or 0)) for yid, pid in mapping.items()}


# --------------------------------------------------------------------------- the week so far
_SO_FAR = {
    "3PTM": "threes",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "TO": "tov",
}
_SO_FAR_PAIRS = {"FGM/A": ("fgm", "fga"), "FTM/A": ("ftm", "fta")}


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        return None


def so_far(matchup: Matchup | None, team_id: int, points: bool) -> dict[str, float]:
    """A team's week so far in our stat names, from the matchup page: the category totals (the
    percentages from their makes and attempts), or a points league's score."""
    if matchup is None:
        return {}
    if points:
        if matchup.score is None or team_id not in matchup.teams:
            return {}
        return {wk.FPTS: matchup.score[matchup.teams.index(team_id)]}
    totals = matchup.totals.get(team_id) or {}
    out: dict[str, float] = {}
    for label, text in totals.items():
        key = re.sub(r"[\s*]", "", label).upper()
        if key in _SO_FAR and (v := _num(text)) is not None:
            out[_SO_FAR[key]] = v
        elif key in _SO_FAR_PAIRS and "/" in text:
            for name, value in zip(_SO_FAR_PAIRS[key], text.split("/"), strict=False):
                if (v := _num(value)) is not None:
                    out[name] = v
    return out


def first_day(read_at: datetime | None, today: date) -> date:
    """The first day the rest of this week projects: today, or tomorrow when the week so far
    was read today after the first games began."""
    if read_at is not None:
        local = read_at.astimezone(NBA_TZ)
        if local.date() == today and local.time() >= GAMES_BEGIN:
            return date.fromordinal(today.toordinal() + 1)
    return today


# --------------------------------------------------------------------------- the weeks
@dataclass(frozen=True)
class Span:
    """A week of the projection: its days from the first day on, and a weekly export's games
    when one covers them."""

    week: Week
    first: date
    days: list[date]
    games: Mapping[int, int] | None


def matchup_read(season: Season, team_id: int | None) -> tuple[Matchup | None, datetime | None]:
    """My matchup this week and when its page was read."""
    matchup = season.matchup_of(team_id) if team_id is not None else None
    if matchup is None:
        return None, None
    fetched = season.fetched.get(matchup_key(matchup.week, matchup.teams))
    return matchup, fetched[0] if fetched else None


def spans(
    season: Season,
    today: date,
    data_dir: Path,
    weeks_ahead: int,
    players: Mapping[int, Player],
    since: date,
) -> list[Span]:
    """The weeks ahead from ``since`` (this week's first day), each with its export's games."""
    weeks = season.calendar.ahead(today, weeks_ahead) if season.calendar else []
    out = []
    for i, week in enumerate(weeks):
        first = max(week.start, since) if i == 0 else week.start
        days = week.days(first) if first <= week.end else []
        override = bbm_week_games(data_dir, players, week, first, today, i == 0) if days else None
        out.append(Span(week, first, days, override))
    return out


# --------------------------------------------------------------------------- the view
def week_projection(
    season: Season, today: date, data_dir: Path, weeks_ahead: int
) -> dict[str, Any]:
    weeks = season.calendar.ahead(today, weeks_ahead) if season.calendar else []
    s = season.settings
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = list(s.cats)
    players = season_players(season)
    bbm = bbm_system(data_dir, players)
    yahoo = yahoo_system(season)
    out: dict[str, Any] = {
        "systems": {"bbm": dict(bbm.info), "yahoo": dict(yahoo.info)},
        "default": "bbm",
        "phi_source": wk.PHI_SOURCE,
        "weeks": [],
        "players": {},
        "matchup": None,
    }
    if not weeks:
        return out
    mine = s.my_team_id
    matchup, read_at = matchup_read(season, mine)
    since = first_day(read_at, today) if matchup is not None else today
    slots = wk.starting_slots(s.roster)
    value = wk.per_game_values(bbm.rates, cats, points)
    ahead = spans(season, today, data_dir, weeks_ahead, players, since)
    for sp in ahead:
        out["weeks"].append(
            {
                "number": sp.week.number,
                "start": sp.week.start.isoformat(),
                "end": sp.week.end.isoformat(),
                "from": sp.first.isoformat(),
                "days": len(sp.days),
                "games_from": "bbm" if sp.games is not None else "schedule",
            }
        )

    rows: dict[int, dict[str, Any]] = {}

    def row(yid: int) -> dict[str, Any]:
        if yid not in rows:
            rows[yid] = {
                "games": [],
                "started": None,
                "bbm": bbm.rates.get(yid),
                "yahoo": yahoo.rates.get(yid),
            }
        return rows[yid]

    for a in season.available:
        r = row(a.player.yahoo_id)
        for i, sp in enumerate(ahead):
            g = sp.games.get(a.player.yahoo_id) if sp.games is not None else None
            pw = wk.standalone_week(
                a.player,
                sp.days,
                season.schedule,
                i == 0,
                games=g,
                zero_games=a.player.yahoo_id in yahoo.zero,
            )
            r["games"].append(pw.games)
    if mine is None:
        out["players"] = {str(k): v for k, v in rows.items()}
        return out

    def project(roster: list[tuple[int, Player]], i: int) -> wk.TeamWeek:
        return wk.project_week(
            roster,
            bbm.rates,
            ahead[i].days,
            season.schedule,
            slots,
            value,
            i == 0,
            games=ahead[i].games,
            points=points,
            no_games=yahoo.zero,
        )

    roster = [(sp.player.yahoo_id, sp.player) for sp in season.rosters.get(mine, ())]
    weekly = [project(roster, i) for i in range(len(ahead))]
    for tw in weekly:
        for yid, pw in tw.players.items():
            r = row(yid)
            r["games"].append(pw.games)
            r["started"] = [*(r["started"] or []), pw.started]
    other = matchup.opponent_of(mine) if matchup is not None else None
    if matchup is not None and other is not None:
        theirs = [(sp.player.yahoo_id, sp.player) for sp in season.rosters.get(other, ())]
        tw = project(theirs, 0)
        for yid, pw in tw.players.items():
            r = row(yid)
            r["games"] = [pw.games]
            r["started"] = [pw.started]
        is_points = points is not None
        mine_so_far = so_far(matchup, mine, is_points)
        theirs_so_far = so_far(matchup, other, is_points)
        odds = wk.category_odds(weekly[0], tw, cats, mine_so_far, theirs_so_far)
        out["matchup"] = {
            "week": matchup.week,
            "teams": [mine, other],
            "system": "bbm",
            "so_far_at": read_at.isoformat() if read_at else None,
            "so_far": {str(mine): mine_so_far, str(other): theirs_so_far},
            "from": since.isoformat(),
            "odds": [o.to_dict() for o in odds],
            "expected": round(wk.expected_won(odds), 3),
            "rest": {str(mine): _totals(weekly[0]), str(other): _totals(tw)},
            "players_with_rates": {
                str(mine): sum(1 for k, _ in roster if k in bbm.rates),
                str(other): sum(1 for k, _ in theirs if k in bbm.rates),
            },
        }
    out["players"] = {str(k): v for k, v in rows.items()}
    return out


def _totals(tw: wk.TeamWeek) -> dict[str, float]:
    return {k: round(v, 2) for k, v in tw.totals.items()}
