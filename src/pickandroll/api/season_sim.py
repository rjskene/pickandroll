"""The season simulator's readers and writers (#172, PR 2b).

The simulator's core (``season.sim``) is pure; everything here reads what it needs from
``data/`` and writes what it leaves. A **setup** is one league as a run starts it, from the
season view's recorded state (``api.seasons``) and the projection systems the moves route uses
(``api.season_moves.system_rates``): rosters, pool, the shared projection, the schedule, the
statuses and return dates read, the market view and rate, and the bracket as the settings page
gave it (``BracketUnread``'s words when it did not). The **fit** is the newest frozen one under
``data/autopilot/sim/fit/``, its hash checked against the file. A **replay** is a made-up league
on a recorded season's game lines (``sources.gamelogs``), each scoring period dated from the
season's first (:data:`PERIOD_ONE`). The **gates'** inputs come from the week records
(``api.season_record``), the decision log (``api.season_decisions``) and the box-score cache.
Every run's payload goes under ``data/autopilot/sim/runs/`` with the fit's hash and the hold-out
named (the master's conditions on #172).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ..season import Season, SeasonSettings
from ..season import moves as mv
from ..season import weekly as wk
from ..season.sim import league as lg
from ..season.sim import run as rn
from ..season.sim.state import Member, Setup, round_robin
from ..sources import boxscores, gamelogs
from . import season_decisions, season_moves, season_record, seasons
from .season_scorecard import BOXSCORES_DIR

SIM_DIR = Path("autopilot") / "sim"
FIT_DIR = SIM_DIR / "fit"
RUNS_DIR = SIM_DIR / "runs"
LOGS_DIR = Path("external") / "espn" / "gamelogs"
#: The two systems the gap is read between, in order: ``log(first) − log(second)``.
GAP_SYSTEMS = ("bbm", "yahoo")
GAP_CLIP = 1.0
#: Percent rostered breaks ties in the market view at this weight (a point of it is a ten
#: thousandth of value: never more than the value itself).
PCT_WEIGHT = 1e-4
#: The players the systems' tau is read over: the rostered population, as the top of the pool
#: by the shared value stands in for the minutes floor until per-game minutes are on file.
TAU_POOL = 156
#: The first scoring period's date, by ESPN season id (the year the season ends in): period
#: ``p`` is this date plus ``p − 1`` days. Verified against ESPN's scoreboard event ids on
#: 2026-10-24, three games a season; 2023's period 1 is the day before opening night.
PERIOD_ONE: Mapping[int, date] = {
    2022: date(2021, 10, 19),
    2023: date(2022, 10, 17),
    2024: date(2023, 10, 24),
    2025: date(2024, 10, 22),
    2026: date(2025, 10, 21),
}
PERIOD_SOURCE = "ESPN scoreboard event ids, 2026-10-24"
#: ESPN's position ids (``defaultPositionId``) and the eligible slots that are a position.
ESPN_POSITIONS: Mapping[int, str] = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}
ESPN_SLOTS: Mapping[int, str] = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F"}


class SimReadError(ValueError):
    """What a run needs is not on disk, or not trusted."""


# --------------------------------------------------------------------------- the setup
def gap_of(
    first: Mapping[int, wk.Rates], second: Mapping[int, wk.Rates], clip: float = GAP_CLIP
) -> dict[int, dict[str, float]]:
    """``log(first) − log(second)`` per player and stat, zero where either is missing or not
    positive, clipped to ``±clip``."""
    out: dict[int, dict[str, float]] = {}
    for k, a in first.items():
        b = second.get(k)
        if b is None:
            continue
        row = {}
        for stat in wk.STATS:
            x, y = float(a.get(stat, 0.0)), float(b.get(stat, 0.0))
            row[stat] = max(-clip, min(clip, math.log(x / y))) if x > 0 and y > 0 else 0.0
        out[k] = row
    return out


def market_view(season: Season, value: Mapping[int, float]) -> dict[int, float]:
    """The market's ranking: the shared projection's per-game value, percent rostered breaking
    ties (Yahoo's own rank is not in the recorded state; the deviation is named in the docs)."""
    pct = {a.player.yahoo_id: float(a.pct_rostered or 0.0) for a in season.available}
    return {k: float(v) + PCT_WEIGHT * pct.get(k, 0.0) for k, v in value.items()}


def market_rate(season: Season, today: date) -> float:
    """Adds per team-day over the days the transactions page reaches."""
    adds = [t for t in season.transactions if t.kind == "add"]
    days = [mv.when_date(t.when, today) for t in adds]
    known = [d for d in days if d is not None]
    if not known:
        return 0.0
    span = (max(known) - min(known)).days + 1
    teams = max(1, len(season.rosters) or season.settings.num_teams)
    groups = {t.group for t, d in zip(adds, days, strict=True) if d is not None}
    return len(groups) / (span * teams)


def _members(players: Mapping[int, Any]) -> dict[int, Member]:
    return {k: Member(k, p.name, p.nba_team, tuple(p.positions)) for k, p in players.items()}


def setup_of(
    data_dir: Path,
    league: str,
    today: date,
    system: str = "bbm",
    blend: float | None = None,
    tiebreak: tuple[str, ...] = lg.TIEBREAK,
) -> Setup:
    """``league`` as a run starts it on ``today``, from the recorded season state."""
    base, _ = seasons.base_settings(data_dir, league)
    parts = seasons.load_parts(data_dir, league)
    if not parts:
        raise SimReadError(f"league {league}: no season state recorded")
    season = Season.from_parts(base, parts)
    s = season.settings
    if season.calendar is None:
        raise SimReadError(f"league {league}: no calendar on file")
    if not season.rosters:
        raise SimReadError(f"league {league}: no rosters read")
    rated = season_moves.system_rates(season, data_dir, system, blend)
    players = _members(rated.players)
    rosters = {
        t: tuple((sp.player.yahoo_id, sp.slot) for sp in spots)
        for t, spots in season.rosters.items()
    }
    teams = tuple(sorted(rosters))
    on_roster = {k for r in rosters.values() for k, _ in r}
    pool = tuple(
        a.player.yahoo_id
        for a in season.available
        if a.player.yahoo_id not in on_roster and a.player.yahoo_id in rated.rates
    )
    statuses = {k: p.status for k, p in rated.players.items() if p.status}
    out_members = [(k, p) for k, p in rated.players.items() if p.status in wk.OUT_THIS_WEEK]
    returns = season_moves.espn_returns(data_dir, out_members)
    this = season.calendar.week_of(today)
    adds_used = {}
    if this is not None:
        for t in teams:
            adds_used[t] = mv.adds_used(season.transactions, t, this.start, this.end, today).count
    regular = [w.number for w in season.calendar.weeks if w.number not in set(s.playoff_weeks)]
    pairings = {w: tuple(ps) for w, ps in season.pairings.items() if ps}
    assumed = tuple(w for w in regular if w not in pairings)
    if assumed:
        pairings |= round_robin(teams, assumed)
    spec: lg.LeagueSpec | None = None
    unread: str | None = None
    try:
        spec = lg.LeagueSpec.from_settings(s, teams, pairings, tiebreak)
    except lg.BracketUnread as e:
        unread = str(e)
    espn_ids = {
        k: v for k, v in boxscores.load_ids(data_dir / BOXSCORES_DIR).items() if k in players
    }
    return Setup(
        league=str(league),
        start=today,
        calendar=season.calendar,
        pairings=pairings,
        teams=teams,
        players=players,
        rosters=rosters,
        pool=pool,
        projection={k: dict(v) for k, v in rated.rates.items() if k in players},
        schedule=season.schedule,
        roster_slots=tuple(s.roster),
        cats=tuple(s.cats),
        scoring=s.scoring,
        points=dict(s.points) if s.points else None,
        max_weekly_adds=s.max_weekly_adds,
        statuses=statuses,
        returns=returns,
        gap=gap_of(rated.bbm.rates, rated.yahoo.rates),
        market=market_view(season, rated.value),
        market_rate=market_rate(season, today),
        adds_used=adds_used,
        espn_ids=espn_ids,
        spec=spec,
        bracket_unread=unread,
        assumed_pairings=assumed,
    )


def systems_tau(data_dir: Path, league: str, pool: int = TAU_POOL) -> dict[str, float]:
    """The spread of the two systems' disagreement over the league's top ``pool`` players by the
    shared value: the projection error's proxy until the residual fit of week six."""
    from ..season.sim.fit import tau_from_systems

    base, _ = seasons.base_settings(data_dir, league)
    parts = seasons.load_parts(data_dir, league)
    if not parts:
        return {}
    season = Season.from_parts(base, parts)
    rated = season_moves.system_rates(season, data_dir, "bbm")
    both = [k for k in rated.bbm.rates if k in rated.yahoo.rates]
    top = sorted(both, key=lambda k: -rated.value.get(k, 0.0))[:pool]
    a = {str(k): rated.bbm.rates[k] for k in top}
    b = {str(k): rated.yahoo.rates[k] for k in top}
    return tau_from_systems(a, b, dict.fromkeys(a, 30.0))


# --------------------------------------------------------------------------- the fit
def fit_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def newest_fit(data_dir: Path) -> tuple[dict[str, Any], str, Path]:
    """The newest frozen fit, its hash and its file; refused when the hash beside it does not
    match the file (a fit edited after it was frozen)."""
    files = sorted((data_dir / FIT_DIR).glob("*/fit.json"))
    if not files:
        raise SimReadError(f"no frozen fit under {data_dir / FIT_DIR}")
    path = files[-1]
    payload = json.loads(path.read_text())
    sha = fit_hash(payload)
    beside = path.with_name("fit.sha256")
    if beside.exists() and beside.read_text().strip() != sha:
        raise SimReadError(f"{path}: the hash beside it does not match the file")
    return payload, sha, path


def code_sha(root: Path) -> str | None:
    """The checkout's commit, for the payload (the script reads it, the core stays pure)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


# --------------------------------------------------------------------------- a replay
def period_date(season: int, period: int) -> date:
    if season not in PERIOD_ONE:
        raise SimReadError(f"season {season}: no first period on file")
    return PERIOD_ONE[season] + timedelta(period - 1)


def replay_lines(
    data_dir: Path, season: int
) -> tuple[dict[int, dict[date, dict[str, float]]], dict[int, Member], dict[int, list[date]]]:
    """A recorded season's lines by player and date (the games he played), its players as
    members (name, NBA team as ESPN numbers it, positions from the eligible slots), and each
    player's scheduled games (every entry, played or not: his team's games while he was on it)."""
    body = gamelogs.load_season(season, data_dir / LOGS_DIR)
    if body is None:
        raise SimReadError(f"season {season}: no cached log under {data_dir / LOGS_DIR}")
    lines: dict[int, dict[date, dict[str, float]]] = {}
    scheduled: dict[int, list[date]] = {}
    for ln in gamelogs.lines_of(body, season):
        day = period_date(season, ln.period)
        scheduled.setdefault(int(ln.player), []).append(day)
        if not ln.played:
            continue
        stats = {k: float(v) for k, v in ln.stats.items() if k in wk.STATS}
        lines.setdefault(int(ln.player), {})[day] = stats
    members: dict[int, Member] = {}
    for row in body.get("players") or []:
        p = row.get("player") or {}
        pid = int(p.get("id"))
        positions = tuple(
            ESPN_SLOTS[s] for s in (p.get("eligibleSlots") or []) if s in ESPN_SLOTS
        ) or (
            (ESPN_POSITIONS[p["defaultPositionId"]],)
            if p.get("defaultPositionId") in ESPN_POSITIONS
            else ()
        )
        team = p.get("proTeamId")
        members[pid] = Member(
            pid, str(p.get("fullName") or pid), None if team is None else str(team), positions
        )
    return lines, members, {k: sorted(v) for k, v in scheduled.items()}


def prior_rates(
    data_dir: Path, season: int, min_games: int = rn.REPLAY_MIN_GAMES
) -> dict[int, dict[str, float]]:
    """The prior season's per-game rates, the replay's first stand-in projection: a player new
    to the league that season has none and sits out the pool."""
    lines, _, _ = replay_lines(data_dir, season - 1)
    return {k: v for k, v in rn.realized_rates(lines).items() if len(lines[k]) >= min_games}


# --------------------------------------------------------------------------- the gates' inputs
def recorded_weeks(data_dir: Path, league: str) -> list[dict[str, Any]]:
    """The league's week records with a scored week in them."""
    folder = seasons.season_dir(data_dir, league)
    return [r for r in season_record.records(folder) if (r.get("teams") or {})]


def team_week_totals(record: Mapping[str, Any]) -> dict[int, dict[str, float]]:
    return {
        int(t): {k: float(v) for k, v in (row.get("totals") or {}).items()}
        for t, row in (record.get("teams") or {}).items()
        if row.get("totals")
    }


def matchup_outcomes(record: Mapping[str, Any]) -> list[tuple[int, int, float | None]]:
    """``(a, b, a's share)`` of each matchup: 1 won, 0 lost, 0.5 tied, None unscored."""
    out = []
    for m in record.get("matchups") or []:
        a, b = (int(t) for t in m["teams"])
        winner = m.get("winner")
        share = None if m.get("score") is None else 0.5 if winner is None else float(winner == a)
        out.append((a, b, share))
    return out


def decisions(data_dir: Path, league: str, to: date | None = None) -> list[dict[str, Any]]:
    return season_decisions.load(seasons.season_dir(data_dir, league), to)


def missed_games(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    schedule: Mapping[int, Sequence[date]],
    weeks: Sequence[tuple[date, date]],
) -> dict[int, list[tuple[int, int]]]:
    """Each player's weeks in order, ``(missed, scheduled)`` a week: of his scheduled games in
    the week, those without a line (gate 4's observations; a week he has no game in is left
    out)."""
    out: dict[int, list[tuple[int, int]]] = {}
    for k, days in schedule.items():
        played = lines.get(k, {})
        rows = []
        for start, end in weeks:
            scheduled = [d for d in days if start <= d <= end]
            if scheduled:
                rows.append((sum(1 for d in scheduled if d not in played), len(scheduled)))
        if rows:
            out[k] = rows
    return out


def team_days(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]], members: Mapping[int, Member]
) -> dict[int, list[date]]:
    """Each player's team's game days in a recorded season: a team played on a day any of its
    players has a line."""
    by_team: dict[str, set[date]] = {}
    for k, by_day in lines.items():
        team = members[k].nba_team if k in members else None
        if team:
            by_team.setdefault(team, set()).update(by_day)
    return {
        k: sorted(by_team.get(m.nba_team or "", ()))
        for k, m in members.items()
        if m.nba_team in by_team
    }


# --------------------------------------------------------------------------- the exports
#: Basketball Monster's rest-of-season exports by date in the file name, oldest first; several
#: a day keep the last.
EXPORTS = "bbm_projections_*.csv"
_EXPORT_DATE = re.compile(r"bbm_projections_(\d{4}-\d{2}-\d{2})(?:T(\d{6}))?\.csv$")


def export_date(path: Path) -> tuple[date, str] | None:
    m = _EXPORT_DATE.match(path.name)
    if m is None:
        return None
    return date.fromisoformat(m.group(1)), m.group(2) or ""


def _per_game(row: Mapping[str, Any]) -> dict[str, float] | None:
    games = float(row.get("games") or 0.0)
    if games <= 0:
        return None
    return {s: float(row.get(s) or 0.0) / games for s in wk.STATS}


def bbm_exports(
    data_dir: Path, players: Mapping[int, Any]
) -> list[tuple[date, dict[int, dict[str, float]]]]:
    """Every rest-of-season export as per-game rates by Yahoo id, by date, oldest first: the
    refresh fit's and the residual tau's input."""
    from ..sources.bbm import load_bbm
    from ..sources.matching import load_aliases, match_players

    dated: dict[date, Path] = {}
    for path in data_dir.glob(EXPORTS):
        d = export_date(path)
        if d is not None and (
            d[0] not in dated or d[1] >= (export_date(dated[d[0]]) or (d[0], ""))[1]
        ):
            dated[d[0]] = path
    if not dated:
        return []
    yahoo = pd.DataFrame(
        {
            "name": [p.name for p in players.values()],
            "team": [p.nba_team or "" for p in players.values()],
        },
        index=[str(k) for k in players],
    )
    aliases = load_aliases(data_dir / "aliases.json")
    out = []
    for d, path in sorted(dated.items()):
        df = load_bbm(path).df
        mapping = match_players(yahoo, df, aliases).mapping
        rates = {}
        for yid, pid in mapping.items():
            r = _per_game(df.loc[pid])
            if r is not None:
                rates[int(yid)] = r
        out.append((d, rates))
    return out


def realized_by_espn(
    data_dir: Path, season: int
) -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """A season's realized per-game rates and played games by ESPN id, from the cached log."""
    lines, _, _ = replay_lines(data_dir, season)
    return (
        {str(k): v for k, v in rn.realized_rates(lines).items()},
        {str(k): len(v) for k, v in lines.items()},
    )


def by_espn(table: Mapping[int, Any], ids: Mapping[int, str]) -> dict[str, Any]:
    """A table by Yahoo id re-keyed by ESPN id where the player is matched."""
    return {ids[k]: v for k, v in table.items() if k in ids}


def espn_ids(data_dir: Path) -> dict[int, str]:
    return boxscores.load_ids(data_dir / BOXSCORES_DIR)


# --------------------------------------------------------------------------- the run's record
def run_path(data_dir: Path, kind: str, name: str, started: datetime) -> Path:
    stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "run"
    return data_dir / RUNS_DIR / f"{stamp}-{kind}-{safe}.json"


def write_run(data_dir: Path, payload: Mapping[str, Any]) -> Path:
    """The payload under ``data/autopilot/sim/runs/``; the fit's hash and the hold-out must be
    in it (the master's conditions)."""
    for key in ("fit_sha", "hold_out"):
        if key not in payload:
            raise ValueError(f"a run payload names {key}")
    path = run_path(
        data_dir,
        str(payload["kind"]),
        str(payload.get("name") or "run"),
        datetime.fromisoformat(str(payload["started_at"])),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str))
    return path


def settings_of(data_dir: Path, league: str) -> SeasonSettings:
    base, _ = seasons.base_settings(data_dir, league)
    parts = seasons.load_parts(data_dir, league)
    return Season.from_parts(base, parts).settings if parts else base


__all__ = [
    "ESPN_POSITIONS",
    "ESPN_SLOTS",
    "FIT_DIR",
    "GAP_CLIP",
    "GAP_SYSTEMS",
    "PERIOD_ONE",
    "PERIOD_SOURCE",
    "RUNS_DIR",
    "SimReadError",
    "bbm_exports",
    "by_espn",
    "code_sha",
    "decisions",
    "espn_ids",
    "export_date",
    "fit_hash",
    "gap_of",
    "market_rate",
    "market_view",
    "matchup_outcomes",
    "missed_games",
    "newest_fit",
    "period_date",
    "prior_rates",
    "realized_by_espn",
    "recorded_weeks",
    "replay_lines",
    "run_path",
    "settings_of",
    "setup_of",
    "systems_tau",
    "team_days",
    "team_week_totals",
    "write_run",
]
