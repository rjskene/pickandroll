"""Final NBA box scores by date, from ESPN's public scoreboard and game summaries (#126, part 2).

A date's scoreboard (``schedule.SCOREBOARD``) lists its games, and each final game's summary
gives every player's line. A date is cached as ``<cache>/<YYYY-MM-DD>.json`` only once every
game on it is over or will not be played on it (``schedule.NOT_PLAYED``), and is never read
again; a date with a game not yet over is left for the next refresh. Only regular-season games
are kept. Teams are in Yahoo's abbreviations. A player on a game's injury report who did not
play is kept with no line, so that a player out for the whole span is matched and counts no
games, not a gap.

Yahoo players are matched to ESPN's by name and team, the name alone when the team fails (a
trade inside the span); each match is kept in ``<cache>/ids.json`` and used from then on.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .matching import match_players
from .schedule import ESPN_TO_YAHOO, NOT_PLAYED, scoreboard_url

SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event}"
IDS = "ids.json"
#: ESPN's regular season (its scoreboard's ``season.type``).
REGULAR = 2
#: ESPN's box-score columns and the keys of a line (``season.weekly``'s rates, and the stats a
#: points league may weigh) they fill: a made-attempted column fills two, None dropping one.
COLUMNS: Mapping[str, tuple[str | None, ...]] = {
    "minutes": ("min",),
    "points": ("pts",),
    "fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("threes", None),
    "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta"),
    "rebounds": ("reb",),
    "offensiveRebounds": ("oreb",),
    "defensiveRebounds": ("dreb",),
    "assists": ("ast",),
    "steals": ("stl",),
    "blocks": ("blk",),
    "turnovers": ("tov",),
}


def summary_url(event: str) -> str:
    return SUMMARY.format(event=event)


def _team(abbr: str | None) -> str | None:
    abbr = (abbr or "").upper()
    return ESPN_TO_YAHOO.get(abbr, abbr) or None


def games_of(body: Any) -> list[dict[str, Any]]:
    """The regular-season games of an ESPN scoreboard response: each one's event id, start (UTC),
    teams, whether it is over and whether it will be played on its date."""
    out = []
    for event in (body or {}).get("events") or []:
        if ((event.get("season") or {}).get("type") or REGULAR) != REGULAR:
            continue
        status = (event.get("status") or {}).get("type") or {}
        teams = [
            _team((side.get("team") or {}).get("abbreviation"))
            for comp in event.get("competitions") or []
            for side in comp.get("competitors") or []
        ]
        out.append(
            {
                "id": str(event.get("id") or ""),
                "start": event.get("date"),
                "teams": sorted(t for t in teams if t),
                "final": bool(status.get("completed")) or status.get("name") == "STATUS_FINAL",
                "played": status.get("name") not in NOT_PLAYED,
            }
        )
    return out


def _line(keys: list[str], stats: list[str]) -> dict[str, float] | None:
    """A player's line from his row of a box score; None for a row without stats."""
    if not stats:
        return None
    line: dict[str, float] = {}
    for key, raw in zip(keys, stats, strict=False):
        fills = COLUMNS.get(key)
        if fills is None:
            continue
        try:
            values = [float(x) for x in str(raw).split("-")] if "-" in key else [float(raw)]
        except ValueError:
            continue
        for name, value in zip(fills, values, strict=False):
            if name is not None:
                line[name] = value
    return line


def players_of(body: Any) -> dict[str, dict[str, Any]]:
    """Every player of an ESPN game summary by ESPN id: his name, his team and his line (None
    when he did not play), the injury report's players who did not play included."""
    out: dict[str, dict[str, Any]] = {}
    box = (body or {}).get("boxscore") or {}
    for side in box.get("players") or []:
        team = _team((side.get("team") or {}).get("abbreviation"))
        for block in (side.get("statistics") or [])[:1]:
            keys = block.get("keys") or []
            for row in block.get("athletes") or []:
                who = row.get("athlete") or {}
                if not who.get("id"):
                    continue
                played = not row.get("didNotPlay")
                out[str(who["id"])] = {
                    "name": who.get("displayName"),
                    "team": team,
                    "line": _line(keys, row.get("stats") or []) if played else None,
                }
    for side in (body or {}).get("injuries") or []:
        team = _team((side.get("team") or {}).get("abbreviation"))
        for row in side.get("injuries") or []:
            who = row.get("athlete") or {}
            if who.get("id") and str(who["id"]) not in out:
                out[str(who["id"])] = {"name": who.get("displayName"), "team": team, "line": None}
    return out


# --------------------------------------------------------------------------- the cache
def read_days(
    days: Iterable[date],
    fetch: Callable[[str], str],
    cache_dir: Path,
    now: datetime | None = None,
    limit: int | None = None,
) -> dict[str, list[str]]:
    """Read and cache each of ``days`` not cached yet whose games are all over, at most
    ``limit`` of them: ``{"read": [dates cached now], "pending": [dates with a game not over],
    "failed": [dates a request failed on], "left": [dates past the limit]}``."""
    now = now or datetime.now(UTC)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[str]] = {"read": [], "pending": [], "failed": [], "left": []}
    tried = 0
    for day in days:
        path = cache_dir / f"{day.isoformat()}.json"
        if path.exists():
            continue
        if limit is not None and tried >= limit:
            out["left"].append(day.isoformat())
            continue
        tried += 1
        try:
            games = games_of(json.loads(fetch(scoreboard_url(day))))
            if not all(g["final"] or not g["played"] for g in games):
                out["pending"].append(day.isoformat())
                continue
            kept = []
            for g in games:
                if g["played"]:
                    if not g["id"]:
                        raise ValueError(f"a game on {day} without an id")
                    body = json.loads(fetch(summary_url(g["id"])))
                    kept.append({**_kept(g), "players": players_of(body)})
        except Exception:  # noqa: BLE001 - a date the source cannot give is read again next time
            out["failed"].append(day.isoformat())
            continue
        _write(path, {"date": day.isoformat(), "fetched_at": now.isoformat(), "games": kept})
        out["read"].append(day.isoformat())
    return out


def _kept(game: Mapping[str, Any]) -> dict[str, Any]:
    return {k: game[k] for k in ("id", "start", "teams")}


def load_days(days: Iterable[date], cache_dir: Path) -> dict[date, list[dict[str, Any]]]:
    """The cached games of each of ``days`` that is cached (a date not cached is left out)."""
    out = {}
    for day in days:
        body = _read(cache_dir / f"{day.isoformat()}.json")
        if body is not None:
            out[day] = body.get("games") or []
    return out


def load_ids(cache_dir: Path) -> dict[int, str]:
    """The ESPN id of each Yahoo player matched so far."""
    body = _read(cache_dir / IDS) or {}
    return {int(k): str(v) for k, v in body.items()}


def save_ids(cache_dir: Path, ids: Mapping[int, str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    _write(cache_dir / IDS, {str(k): v for k, v in sorted(ids.items())})


# --------------------------------------------------------------------------- matching
def match(
    players: Mapping[int, tuple[str, str | None]],
    games: Iterable[Mapping[str, Any]],
    ids: Mapping[int, str],
) -> dict[int, tuple[str, str]]:
    """Each Yahoo player of ``players`` (yahoo id to name and NBA team) matched to an ESPN id of
    the ``games``' players, and how: ``id`` (matched before), ``team`` (by name on his own team)
    or ``name`` (by name alone, unique over every team). A player matched by none is left out."""
    out = {k: (ids[k], "id") for k in players if k in ids}
    # A player traded inside the span is seen on both teams.
    seen: dict[tuple[str, str | None], str] = {}
    for g in games:
        for espn, p in (g.get("players") or {}).items():
            seen[(espn, p.get("team"))] = p.get("name") or ""
    left = {k: v for k, v in players.items() if k not in out}
    for team in {t for _, t in left.values() if t}:
        mine = {k: name for k, (name, t) in left.items() if t == team}
        theirs = {e: name for (e, t), name in seen.items() if t == team}
        for k, espn in _by_name(mine, theirs).items():
            out[k] = (espn, "team")
    rest = {k: name for k, (name, _) in left.items() if k not in out}
    for k, espn in _by_name(rest, {e: name for (e, _), name in seen.items()}).items():
        out[k] = (espn, "name")
    return out


def _by_name(mine: Mapping[int, str], theirs: Mapping[str, str]) -> dict[int, str]:
    if not mine or not theirs:
        return {}
    yahoo = pd.DataFrame({"name": list(mine.values())}, index=[str(k) for k in mine])
    espn = pd.DataFrame({"player": list(theirs.values())}, index=list(theirs))
    return {int(k): v for k, v in match_players(yahoo, espn).mapping.items()}


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write(path: Path, body: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, separators=(",", ":")))
    tmp.replace(path)
