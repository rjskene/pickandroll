"""Yahoo Fantasy Sports access through ``yfpy``.

Everything the draft needs from Yahoo lives behind :class:`YahooLeague`:

* league settings (teams, roster slots, stat categories, draft type and status),
* the team list with draft positions and which team is mine,
* the player pool with eligible positions and average draft position,
* the draft results, which during a live draft contain the picks made so far.

The ``query`` object is injectable so the mapping code can be tested without the network. First
use requires a one-time browser OAuth handshake; see ``scripts/yahoo_auth.py``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ...optim.roster import ANY, Slot

REPO_ROOT = Path(__file__).resolve().parents[4]
GAME_CODE = "nba"
PAGE_SIZE = 25

# Yahoo roster position abbreviations to solver slot eligibility. IL and IL+ are not draft slots.
SLOT_ELIGIBILITY: dict[str, frozenset[str]] = {
    "PG": frozenset({"PG"}),
    "SG": frozenset({"SG"}),
    "G": frozenset({"G"}),
    "SF": frozenset({"SF"}),
    "PF": frozenset({"PF"}),
    "F": frozenset({"F"}),
    "C": frozenset({"C"}),
    "Util": ANY,
    "UTIL": ANY,
    "BN": ANY,
}
SKIP_POSITIONS = {"IL", "IL+", "NA", "IR"}

# Yahoo NBA stat display names to our categories.
STAT_NAMES: dict[str, str] = {
    "FG%": "fg_pct",
    "FT%": "ft_pct",
    "3PTM": "threes",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "TO": "tov",
}


@dataclass(frozen=True)
class LeagueInfo:
    league_key: str
    name: str
    num_teams: int
    draft_type: str
    is_auction: bool
    draft_status: str
    draft_time: int | None
    scoring_type: str
    roster_positions: tuple[tuple[str, int], ...]
    stat_categories: tuple[str, ...]

    @property
    def slots(self) -> list[Slot]:
        return slots_from_positions(self.roster_positions)

    @property
    def cats(self) -> list[str]:
        return [STAT_NAMES[s] for s in self.stat_categories if s in STAT_NAMES]


@dataclass(frozen=True)
class TeamInfo:
    team_key: str
    team_id: int
    name: str
    draft_position: int | None
    is_mine: bool


def slots_from_positions(positions: Iterable[tuple[str, int]]) -> list[Slot]:
    """Expand Yahoo ``(abbreviation, count)`` roster positions into solver slots."""
    slots: list[Slot] = []
    for abbr, count in positions:
        if abbr in SKIP_POSITIONS:
            continue
        eligible = SLOT_ELIGIBILITY.get(abbr, ANY)
        for i in range(int(count)):
            name = abbr if count == 1 else f"{abbr}{i + 1}"
            slots.append(Slot(name, eligible))
    return slots


def make_query(league_id: str, env_file: Path | None = None, **kwargs: Any):
    """Build a ``YahooFantasySportsQuery`` with credentials from ``.env`` at the repo root."""
    from yfpy.query import YahooFantasySportsQuery

    env_file = env_file or REPO_ROOT / ".env"
    return YahooFantasySportsQuery(
        league_id=str(league_id),
        game_code=GAME_CODE,
        env_file_location=env_file.parent,
        save_token_data_to_env_file=True,
        **kwargs,
    )


class YahooLeague:
    def __init__(self, league_id: str | None = None, query: Any | None = None) -> None:
        self.league_id = str(league_id or os.environ.get("YAHOO_LEAGUE_ID", ""))
        self._query = query
        self._league_key: str | None = None

    @property
    def query(self):
        if self._query is None:
            if not self.league_id:
                raise ValueError("league_id is required (or set YAHOO_LEAGUE_ID)")
            self._query = make_query(self.league_id)
        return self._query

    @property
    def league_key(self) -> str:
        if self._league_key is None:
            self._league_key = self.query.get_league_key()
        return self._league_key

    # ------------------------------------------------------------------ settings
    def info(self) -> LeagueInfo:
        league = self.query.get_league_metadata()
        settings = self.query.get_league_settings()
        positions = tuple((rp.position, int(rp.count)) for rp in settings.roster_positions)
        stats = tuple(
            s.display_name
            for s in settings.stat_categories.stats
            if not getattr(s, "is_only_display_stat", 0)
        )
        return LeagueInfo(
            league_key=league.league_key,
            name=_text(league.name),
            num_teams=int(league.num_teams),
            draft_type=settings.draft_type,
            is_auction=bool(int(settings.is_auction_draft or 0)),
            draft_status=league.draft_status,
            draft_time=settings.draft_time,
            scoring_type=settings.scoring_type,
            roster_positions=positions,
            stat_categories=stats,
        )

    def teams(self) -> list[TeamInfo]:
        return [
            TeamInfo(
                team_key=t.team_key,
                team_id=int(t.team_id),
                name=_text(t.name),
                draft_position=t.draft_position,
                is_mine=bool(int(t.is_owned_by_current_login or 0)),
            )
            for t in self.query.get_league_teams()
        ]

    # ------------------------------------------------------------------ players
    def players(self, max_players: int | None = None) -> pd.DataFrame:
        """Player pool with positions and ADP, sorted by Yahoo's actual-rank ordering."""
        rows = []
        start = 0
        while True:
            url = (
                f"https://fantasysports.yahooapis.com/fantasy/v2/league/{self.league_key}/players"
                f";sort=AR;start={start};count={PAGE_SIZE}/draft_analysis"
            )
            page = self.query.query(url, ["league", "players"])
            page = _as_list(page)
            for player in page:
                rows.append(player_row(player))
            start += PAGE_SIZE
            if len(page) < PAGE_SIZE or (max_players and len(rows) >= max_players):
                break
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index("player_key")
            if max_players:
                df = df.head(max_players)
        return df

    # ------------------------------------------------------------------ draft
    def draft_status(self) -> str:
        return self.query.get_league_metadata().draft_status

    def draft_results(self) -> list[tuple[int, str, str]]:
        """``(overall_pick, team_key, player_key)`` for every pick made so far."""
        results = self.query.get_league_draft_results()
        return sorted((int(r.pick), r.team_key, r.player_key) for r in _as_list(results) if r.pick)


def player_row(player: Any) -> dict[str, Any]:
    analysis = getattr(player, "draft_analysis", None)
    positions = getattr(player, "eligible_positions", None) or []
    if isinstance(positions, str):
        positions = [positions]
    positions = [p for p in positions if p not in {"Util", "UTIL", "BN", "IL", "IL+", "NA"}]
    return {
        "player_key": player.player_key,
        "player_id": getattr(player, "player_id", None),
        "name": player.full_name if hasattr(player, "full_name") else _text(player.name.full),
        "team": getattr(player, "editorial_team_abbr", None),
        "positions": "/".join(positions),
        "status": getattr(player, "status", None) or "",
        "adp": _float(getattr(analysis, "average_pick", None)),
        "adp_round": _float(getattr(analysis, "average_round", None)),
        "percent_drafted": _float(getattr(analysis, "percent_drafted", None)),
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _float(value: Any) -> float | None:
    try:
        return None if value in (None, "", "-") else float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
