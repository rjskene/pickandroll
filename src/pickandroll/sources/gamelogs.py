"""ESPN's per-game logs for a whole season (#172, PR 1): the player view the draft-edge audit
read (``data/external/README.md``), one request a season, cached under ``data/external/espn/
gamelogs/<season>.json``, never committed.

The view returns up to 700 players, each with one entry per scheduled team game (``statSplitTypeId``
5: the stats empty when he did not play), the season's actual totals (split 0, source 0) and one
stored season projection (split 0, source 1; updated through the season, so not the preseason
figure). ESPN's season id is the year the season ends in: 2026 is 2025-26. The ``fetch`` is
injected exactly as ``boxscores.read_days`` takes it, with no retry loop here: a season whose
request fails is listed and read again next run.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..season.sim.fit import GameLine

#: The player view; ``{season}`` is ESPN's season id.
KONA_URL = (
    "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}"
    "/segments/0/leaguedefaults/1?view=kona_player_info"
)
#: The request header that asks for the 700 most rostered players (the audit's filter).
FILTER_HEADER = "X-Fantasy-Filter"
FILTER = '{"players":{"limit":700,"sortPercOwned":{"sortAsc":false,"sortPriority":1}}}'
#: ESPN's stat ids in our names; 40 is minutes (pinned by a test against a box-score line).
STAT_IDS: Mapping[str, str] = {
    "0": "pts",
    "1": "blk",
    "2": "stl",
    "3": "ast",
    "6": "reb",
    "11": "tov",
    "13": "fgm",
    "14": "fga",
    "15": "ftm",
    "16": "fta",
    "17": "threes",
    "40": "minutes",
}
GAMES_ID = "42"
PER_GAME = 5
SEASON_TOTAL = 0
ACTUAL = 0
PROJECTED = 1


def season_url(season: int) -> str:
    return KONA_URL.format(season=season)


def cache_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"{season}.json"


def read_seasons(
    seasons: Iterable[int],
    fetch: Callable[[str], str],
    cache_dir: Path,
    now: datetime | None = None,
) -> dict[str, list[int]]:
    """Fetch and cache each of ``seasons`` not cached yet, one request each: ``{"read": [seasons
    cached now], "cached": [seasons already there], "failed": [seasons a request failed on]}``."""
    now = now or datetime.now(UTC)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[int]] = {"read": [], "cached": [], "failed": []}
    for season in seasons:
        path = cache_path(season, cache_dir)
        if path.exists():
            out["cached"].append(season)
            continue
        try:
            body = json.loads(fetch(season_url(season)))
            if not isinstance(body, dict) or "players" not in body:
                raise ValueError(f"season {season}: no players in the response")
        except Exception:  # noqa: BLE001 - a season the source cannot give is read again next time
            out["failed"].append(season)
            continue
        path.write_text(json.dumps({"season": season, "fetched_at": now.isoformat(), "body": body}))
        out["read"].append(season)
    return out


def load_season(season: int, cache_dir: Path) -> dict[str, Any] | None:
    """The cached response of ``season``, None when not cached."""
    path = cache_path(season, cache_dir)
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("body")


def _stats(raw: Mapping[str, Any]) -> dict[str, float]:
    return {name: float(raw[k]) for k, name in STAT_IDS.items() if k in raw}


def lines_of(body: Mapping[str, Any], season: int) -> list[GameLine]:
    """Every player's per-game entries of ``season`` as lines, in period order: an entry with
    no stats is a game he did not play (minutes zero)."""
    out: list[GameLine] = []
    for row in body.get("players") or []:
        p = row.get("player") or {}
        pid = str(p.get("id"))
        for s in p.get("stats") or []:
            if s.get("statSplitTypeId") != PER_GAME or s.get("seasonId") != season:
                continue
            stats = _stats(s.get("stats") or {})
            minutes = stats.pop("minutes", 0.0)
            played = bool(s.get("stats")) and minutes > 0
            team = s.get("proTeamId")
            out.append(
                GameLine(
                    pid,
                    season,
                    int(s.get("scoringPeriodId") or 0),
                    None if team is None else str(team),
                    played,
                    minutes if played else 0.0,
                    stats if played else {},
                )
            )
    out.sort(key=lambda ln: (ln.player, ln.period))
    return out


def names_of(body: Mapping[str, Any]) -> dict[str, str]:
    """Each player's name by ESPN id."""
    return {
        str((row.get("player") or {}).get("id")): str(
            (row.get("player") or {}).get("fullName") or ""
        )
        for row in body.get("players") or []
    }


def totals_of(
    body: Mapping[str, Any], season: int, source: int = ACTUAL
) -> dict[str, dict[str, float]]:
    """Each player's season totals (``source`` ACTUAL) or stored projection (PROJECTED), with
    ``games``."""
    out: dict[str, dict[str, float]] = {}
    for row in body.get("players") or []:
        p = row.get("player") or {}
        for s in p.get("stats") or []:
            if (
                s.get("statSplitTypeId") == SEASON_TOTAL
                and s.get("seasonId") == season
                and s.get("statSourceId") == source
            ):
                raw = s.get("stats") or {}
                totals = _stats(raw)
                if GAMES_ID in raw:
                    totals["games"] = float(raw[GAMES_ID])
                out[str(p.get("id"))] = totals
    return out


def per_game(totals: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """Season totals to per-game rates, players without games left out."""
    out: dict[str, dict[str, float]] = {}
    for pid, t in totals.items():
        g = t.get("games", 0.0)
        if g > 0:
            out[pid] = {k: v / g for k, v in t.items() if k != "games"}
    return out
