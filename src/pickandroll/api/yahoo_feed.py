"""Live Yahoo draft feed for a session.

Yahoo has no push API, so a feed polls the league's draft results on an interval, maps each
Yahoo ``player_key`` to a projection id with the name matcher, and hands new picks to
``DraftState.sync``. Every applied pick is published on the session's event stream, which
triggers the UI to re-solve.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..sources.matching import MatchResult, load_aliases, match_players
from ..sources.yahoo import YahooLeague

if TYPE_CHECKING:
    from .app import Session

LeagueFactory = Callable[[str], YahooLeague]


@dataclass
class YahooFeed:
    league: YahooLeague
    league_name: str
    draft_status: str
    teams: dict[str, str]
    mapping: dict[str, str]
    match: MatchResult
    yahoo_names: dict[str, str]
    interval: float = 8.0
    polls: int = 0
    last_poll: str | None = None
    last_error: str | None = None
    unmapped_picks: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    def status(self) -> dict[str, Any]:
        return {
            "attached": True,
            "running": self.running,
            "league": self.league_name,
            "draft_status": self.draft_status,
            "interval": self.interval,
            "polls": self.polls,
            "last_poll": self.last_poll,
            "last_error": self.last_error,
            "matched": len(self.mapping),
            "unmatched_yahoo": [
                {"player_key": k, "name": self.yahoo_names.get(k, k)}
                for k in self.match.unmatched_yahoo
            ],
            "unmatched_projection": self.match.unmatched_projection,
            "unmapped_picks": self.unmapped_picks,
        }

    def poll_once(self, session: Session) -> list[dict[str, Any]]:
        """Fetch draft results and apply new picks. Returns the picks applied."""
        results = self.league.draft_results()
        self.draft_status = self.league.draft_status()
        feed = []
        self.unmapped_picks = []
        for overall, team_key, player_key in results:
            pid = self.mapping.get(player_key)
            if pid is None:
                self.unmapped_picks.append(
                    {
                        "overall": overall,
                        "team": self.teams.get(team_key, team_key),
                        "player_key": player_key,
                        "name": self.yahoo_names.get(player_key, player_key),
                    }
                )
                continue
            feed.append((overall, self.teams.get(team_key, team_key), pid))
        # Picks must be contiguous from 1 for DraftState; stop at the first gap.
        applied = []
        expected = session.state.next_overall
        known = {p.overall for p in session.state.picks}
        for overall, team, pid in sorted(feed):
            if overall in known:
                continue
            if overall != expected:
                break
            try:
                pick = session.state.apply_pick(team, pid, overall)
            except (KeyError, ValueError) as exc:
                self.last_error = f"pick {overall}: {exc}"
                break
            expected += 1
            row = _row(session, pick)
            applied.append(row)
            session.publish("pick", {"pick": row, "source": "yahoo"})
        self.polls += 1
        self.last_poll = datetime.now(tz=UTC).isoformat()
        return applied

    async def run(self, session: Session) -> None:
        while True:
            try:
                await asyncio.to_thread(self.poll_once, session)
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - any transport error must not kill the loop
                self.last_error = str(exc)
            if session.state.complete or self.draft_status == "postdraft":
                session.publish("yahoo_done", {"draft_status": self.draft_status})
                return
            await asyncio.sleep(self.interval)


def attach_feed(
    session: Session,
    league: YahooLeague,
    interval: float = 8.0,
    aliases_path: Path | None = None,
) -> YahooFeed:
    """Pull league metadata, match players to the session's projections, build the feed."""
    info = league.info()
    teams = league.teams()
    players = league.players()
    aliases = load_aliases(aliases_path) if aliases_path else {}
    match = match_players(players, session.state.projections.df, aliases=aliases)
    team_labels = {t.team_key: t.name for t in teams}
    mine = next((t for t in teams if t.is_mine), None)
    if mine is not None:
        session.state.my_team = mine.name
        if mine.draft_position:
            session.state.my_position = int(mine.draft_position)
    feed = YahooFeed(
        league=league,
        league_name=info.name,
        draft_status=info.draft_status,
        teams=team_labels,
        mapping=match.mapping,
        match=match,
        yahoo_names=players["name"].to_dict() if not players.empty else {},
        interval=interval,
    )
    session.publish(
        "yahoo_attached",
        {
            "league": info.name,
            "matched": len(match.mapping),
            "unmatched": len(match.unmatched_yahoo),
        },
    )
    return feed


def _row(session: Session, pick) -> dict[str, Any]:
    from .app import _pick_row

    return _pick_row(session.state, pick)
