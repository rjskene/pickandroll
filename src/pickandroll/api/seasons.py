"""The in-season state of each league folder (docs/ADD_DROP.md, phase 1, issue #92).

Routes:

``GET /seasons``
    One row per league folder for the dashboard's Leagues section: name, week, my record,
    this week's opponent, when the snapshot was last read, and any refresh in progress.
``GET /seasons/{league}``
    The season view: settings, the week and the next ones, standings, every roster, my
    matchup, the available players and the league's transactions.
``POST /seasons/{league}/refresh``
    Reads the league's public sources (a public league: the prize leagues) in the background;
    ``?wait=true`` returns once it is done. A private league answers ``409`` with what to do.
``POST /seasons/{league}/snapshot``
    The extension's reads of a private league: whole pages (``{url, html}``, parsed here by
    the same parsers) or parts already parsed (``{key, data}``).

Storage, all under ``data/`` and never committed: ``data/leagues/<id>/season/state.json`` holds
the latest read of every part with its time and source, and every refresh or snapshot is kept
as ``season/snapshots/<UTC time>-<source>.json``. The matchup weeks are the same for every league
of the season, so their calendar is shared in ``data/leagues/_shared/season/calendar.json``; the
NBA schedule is cached by date in ``data/schedule/``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as FastPath
from pydantic import BaseModel, Field

from ..season import (
    EXTENSION,
    PUBLIC,
    Calendar,
    Part,
    Season,
    SeasonSettings,
    build_calendar,
    matchup_key,
    merge_part,
    monday_of,
    mondays,
    roster_key,
)
from ..sources import schedule as nba_schedule
from ..sources.yahoo import pages, public
from . import leagues

SEASON_DIR = "season"
STATE = "state.json"
SNAPSHOTS = "snapshots"
SCHEDULE_DIR = "schedule"
CALENDAR = "calendar.json"
#: The weeks a season view looks ahead: this one and the next three (the Moves card's horizon).
WEEKS_AHEAD = 4
#: The NBA's dates (and Yahoo's pages) run on US Eastern time.
NBA_TZ = ZoneInfo("America/New_York")
TRANSACTIONS_SHOWN = 30

FetchFactory = Callable[[], public.Fetch]


# --------------------------------------------------------------------------- storage
def season_dir(data_dir: Path, league: str) -> Path:
    return leagues.league_dir(data_dir, league) / SEASON_DIR


def calendar_path(data_dir: Path) -> Path:
    return data_dir / leagues.LEAGUES_DIR / leagues.SHARED / SEASON_DIR / CALENDAR


def base_settings(data_dir: Path, league: str) -> tuple[SeasonSettings, bool]:
    """The league folder's settings as a season's base, and whether Yahoo serves the league
    publicly (``"public": false`` in settings.json marks a private league)."""
    s = leagues.load_settings(data_dir, league)
    cats = leagues.league_cats(s)
    return (
        SeasonSettings(
            league=str(league),
            scoring=s["scoring"],
            cats=tuple(c.value for c in cats) if cats else ("fpts",),
            roster=tuple(str(x) for x in s.get("roster") or ()),
            num_teams=int(s.get("num_teams") or 12),
            my_team_id=s.get("my_team_id"),
            points=s.get("points"),
            name=s.get("name"),
        ),
        bool(s.get("public", True)),
    )


def load_parts(data_dir: Path, league: str) -> dict[str, Part]:
    path = season_dir(data_dir, league) / STATE
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except ValueError as exc:
        raise HTTPException(500, f"{path}: {exc}") from exc
    return {key: Part.from_dict(key, d) for key, d in (raw.get("parts") or {}).items()}


def _write_json(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, separators=(",", ":")))
    tmp.replace(path)


def save(
    data_dir: Path, league: str, parts: dict[str, Part], received: list[Part], source: str
) -> None:
    folder = season_dir(data_dir, league)
    _write_json(
        folder / STATE, {"league": league, "parts": {k: p.to_dict() for k, p in parts.items()}}
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    _write_json(
        folder / SNAPSHOTS / f"{stamp}-{source}.json",
        {
            "received_at": datetime.now(UTC).isoformat(),
            "source": source,
            "parts": {p.key: p.to_dict() for p in received},
        },
    )


def nba_today(now: datetime) -> date:
    return now.astimezone(NBA_TZ).date()


# --------------------------------------------------------------------------- refresh jobs
@dataclass
class RefreshJob:
    league: str
    status: str = "running"
    step: str = "starting"
    done: int = 0
    total: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
        }


class SeasonService:
    def __init__(
        self,
        data_dir: Path,
        fetch_factory: FetchFactory,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.data_dir = data_dir
        self.fetch_factory = fetch_factory
        #: Now, for the NBA date the views count games from (tests pin it).
        self.clock = clock
        self.jobs: dict[str, RefreshJob] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def lock(self, league: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(league, threading.Lock())

    # ------------------------------------------------------------------ reading
    def season(self, league: str) -> Season:
        base, _ = self._base(league)
        return Season.from_parts(base, load_parts(self.data_dir, league))

    def _base(self, league: str) -> tuple[SeasonSettings, bool]:
        try:
            return base_settings(self.data_dir, league)
        except leagues.LeagueError as exc:
            raise HTTPException(404, str(exc)) from exc

    def summary(self, league: str) -> dict[str, Any]:
        base, is_public = self._base(league)
        parts = load_parts(self.data_dir, league)
        season = Season.from_parts(base, parts)
        job = self.jobs.get(league)
        return _summary(season, is_public, bool(parts), job)

    def view(self, league: str) -> dict[str, Any]:
        base, is_public = self._base(league)
        parts = load_parts(self.data_dir, league)
        season = Season.from_parts(base, parts)
        return {
            **_summary(season, is_public, bool(parts), self.jobs.get(league)),
            **_view(season, nba_today(self.clock())),
        }

    # ------------------------------------------------------------------ refresh
    def start_refresh(self, league: str) -> RefreshJob:
        """The league's refresh: the one running, else a new one in the background."""
        self._base(league)
        with self._guard:
            job = self.jobs.get(league)
            if job is not None and job.status == "running":
                return job
            job = self.jobs[league] = RefreshJob(league)
        threading.Thread(
            target=self.run_refresh, args=(job,), daemon=True, name=f"season-{league}"
        ).start()
        return job

    def run_refresh(self, job: RefreshJob) -> RefreshJob:
        league = job.league
        try:
            base, is_public = self._base(league)
            if not is_public:
                raise public.PrivateLeague(
                    f"league {league} is private: open its pages in Chrome with the extension"
                )
            fetch = self.fetch_factory()
            today = nba_today(self.clock())

            def progress(step: str, done: int, total: int) -> None:
                job.step, job.done, job.total = step, done, total

            received = public.refresh_parts(league, base, fetch, today, progress=progress)
            settings = base.merged(next(p.data for p in received if p.key == "settings"))
            job.step = "calendar"
            calendar = self._calendar(league, settings, fetch, today)
            if calendar is not None:
                received.append(Part("calendar", datetime.now(UTC), PUBLIC, calendar.to_dict()))
            job.step = "schedule"
            with self.lock(league):
                parts = load_parts(self.data_dir, league)
                days = _schedule_days(calendar, today)
                read = nba_schedule.schedule_days(
                    days, fetch, self.data_dir / SCHEDULE_DIR, now=self.clock()
                )
                old = (parts.get("schedule").data if "schedule" in parts else {}).get("days", {})
                received.append(
                    Part("schedule", datetime.now(UTC), PUBLIC, {"days": {**old, **read}})
                )
                for part in received:
                    parts = merge_part(parts, part)
                save(self.data_dir, league, parts, received, PUBLIC)
            # The total counted every players page; the pool may have ended sooner.
            job.status, job.step, job.total = "done", "done", job.done
        except public.PrivateLeague as exc:
            job.status, job.error = "private", str(exc)
        except (public.FetchError, pages.PageError) as exc:
            job.status, job.error = "failed", str(exc)
        except HTTPException as exc:
            job.status, job.error = "failed", str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - the job reports what broke instead of dying silently
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = datetime.now(UTC)
        return job

    def _calendar(
        self, league: str, settings: SeasonSettings, fetch: public.Fetch, today: date
    ) -> Calendar | None:
        """The season's matchup weeks, from the shared cache when it reaches the season's end;
        else read once from the league's team page, one request per Monday."""
        end = settings.end_date
        if end is None:
            return None
        path = calendar_path(self.data_dir)
        try:
            cached = Calendar.from_dict(json.loads(path.read_text()))
            if cached.weeks and cached.weeks[-1].end >= end and not cached.estimated:
                return cached
        except (OSError, ValueError, KeyError):
            pass
        week = settings.current_week or 1
        first = monday_of(today) - timedelta(weeks=week - 1)
        team = settings.my_team_id or 1
        labels = public.week_labels(league, team, mondays(first, end), fetch)
        calendar = build_calendar(first, end, labels)
        _write_json(path, calendar.to_dict())
        return calendar

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, league: str, body: SnapshotBody) -> dict[str, Any]:
        base, _ = self._base(league)
        today = nba_today(self.clock())
        received: list[Part] = []
        skipped: list[dict[str, str]] = []
        for page in body.pages:
            at = page.fetched_at or datetime.now(UTC)
            try:
                received.append(_page_part(league, page.url, page.html, at, today))
            except pages.PageError as exc:
                skipped.append({"url": page.url, "reason": str(exc)})
        for given in body.parts:
            if not _known_key(given.key):
                skipped.append({"key": given.key, "reason": "unknown part"})
                continue
            received.append(
                Part(given.key, given.fetched_at or datetime.now(UTC), EXTENSION, given.data)
            )
        with self.lock(league):
            parts = load_parts(self.data_dir, league)
            for part in received:
                parts = merge_part(parts, part)
            try:
                Season.from_parts(base, parts)
            except (KeyError, TypeError, ValueError) as exc:
                raise HTTPException(400, f"the snapshot does not read: {exc}") from exc
            if received:
                save(self.data_dir, league, parts, received, EXTENSION)
        return {
            "accepted": [p.key for p in received],
            "skipped": skipped,
            "season": self.summary(league),
        }


def _known_key(key: str) -> bool:
    fixed = {"settings", "players", "league", "available", "transactions", "calendar", "schedule"}
    return key in fixed or key.startswith(("roster/", "matchup/"))


def _page_part(league: str, url: str, html: str, at: datetime, today: date) -> Part:
    kind, info = pages.page_kind(url)
    if info["league"] != str(league):
        raise pages.PageError(f"the page is league {info['league']}'s, not {league}'s")
    if kind == "league":
        d = pages.parse_league_page(html)
        return Part("league", at, EXTENSION, d)
    if kind == "team":
        d = pages.parse_team_page(html, info["team_id"])
        return Part(roster_key(info["team_id"]), at, EXTENSION, d)
    if kind == "players":
        d = pages.parse_players_page(html, today)
        return Part(
            "available",
            at,
            EXTENSION,
            {**d, "upsert": True, "rows": [{**r, "seen_at": at.isoformat()} for r in d["rows"]]},
        )
    if kind == "matchup":
        d = pages.parse_matchup_page(html, info.get("week"))
        return Part(matchup_key(d["week"], d["teams"]), at, EXTENSION, d)
    if kind == "transactions":
        return Part("transactions", at, EXTENSION, pages.parse_transactions_page(html))
    raise pages.PageError(f"no parser for a {kind} page")


def _schedule_days(calendar: Calendar | None, today: date) -> list[date]:
    """The dates the season view counts games on: the rest of this week and the next three
    (four weeks of days when the calendar is not known)."""
    if calendar is not None:
        weeks = calendar.ahead(today, WEEKS_AHEAD)
        if weeks:
            last = weeks[-1].end
            return [today + timedelta(n) for n in range((last - today).days + 1)]
    return [today + timedelta(n) for n in range(7 * WEEKS_AHEAD)]


# --------------------------------------------------------------------------- views
def _team(season: Season, team_id: int | None) -> dict[str, Any] | None:
    if team_id is None:
        return None
    t = season.team(team_id)
    if t is None:
        return {"team_id": team_id, "name": f"Team {team_id}", "record": None, "rank": None}
    return {
        "team_id": t.team_id,
        "name": t.name,
        "record": t.record,
        "rank": t.rank,
        "points_for": t.points_for,
    }


def _summary(
    season: Season, is_public: bool, has_snapshot: bool, job: RefreshJob | None
) -> dict[str, Any]:
    s = season.settings
    opponent = season.opponent
    sources = sorted({src for _, src in season.fetched.values()})
    updated = season.updated_at
    return {
        "league": s.league,
        "name": s.name,
        "scoring": s.scoring,
        "num_teams": s.num_teams,
        "public": is_public,
        "week": s.current_week,
        "end_week": s.end_week,
        "my_team": _team(season, s.my_team_id),
        "opponent": _team(season, opponent.team_id) if opponent else None,
        "has_snapshot": has_snapshot,
        "updated_at": updated.isoformat() if updated else None,
        "sources": sources,
        "refresh": job.to_dict() if job else None,
    }


def _view(season: Season, today: date) -> dict[str, Any]:
    week = season.current(today)
    days_left = week.days(since=today) if week else None
    weeks_ahead = season.calendar.ahead(today, WEEKS_AHEAD) if season.calendar else []

    def games(nba_team: str | None) -> int | None:
        return season.games(nba_team, days_left) if days_left is not None else None

    rosters = {
        str(team_id): [
            {**spot.to_dict(), "games_left": games(spot.player.nba_team)} for spot in spots
        ]
        for team_id, spots in season.rosters.items()
    }
    mine = season.settings.my_team_id
    matchup = season.matchup_of(mine)
    return {
        "settings": season.settings.to_dict(),
        "today": today.isoformat(),
        "current_week": week.to_dict() if week else None,
        "weeks_ahead": [w.to_dict() for w in weeks_ahead],
        "calendar_estimated": season.calendar.estimated if season.calendar else None,
        "teams": [{**t.to_dict(), "record": t.record} for t in season.teams],
        "roster": rosters.get(str(mine), []) if mine is not None else [],
        "rosters": rosters,
        "matchups": [m.to_dict() for m in season.matchups],
        "matchup": matchup.to_dict() if matchup else None,
        "available": [
            {**a.to_dict(), "games_left": games(a.player.nba_team)} for a in season.available
        ],
        "transactions": [t.to_dict() for t in season.transactions[:TRANSACTIONS_SHOWN]],
        "fetched": {
            k: {"at": at.isoformat(), "source": src}
            for k, (at, src) in sorted(season.fetched.items())
        },
        "schedule": {
            "days": len(season.schedule),
            "first": min(season.schedule).isoformat() if season.schedule else None,
            "last": max(season.schedule).isoformat() if season.schedule else None,
        },
    }


# --------------------------------------------------------------------------- routes
class SnapshotPage(BaseModel):
    url: str = Field(description="the page's address, which says what page it is")
    html: str = Field(description="the page's HTML as the user's Chrome rendered it")
    fetched_at: datetime | None = None


class SnapshotPart(BaseModel):
    key: str = Field(
        description="a season part: settings, players, league, roster/<team>, available, matchup/<week>/<a>-<b>, transactions"
    )
    data: Any
    fetched_at: datetime | None = None


class SnapshotBody(BaseModel):
    pages: list[SnapshotPage] = Field(default_factory=list)
    parts: list[SnapshotPart] = Field(default_factory=list)


def register(
    app: FastAPI, data_dir: Path, fetch_factory: FetchFactory | None = None
) -> SeasonService:
    service = SeasonService(data_dir, fetch_factory or public.HttpFetch)
    app.state.seasons = service
    league_id = FastPath(pattern=leagues.LEAGUE_ID)

    @app.get("/seasons")
    def list_seasons() -> list[dict[str, Any]]:
        """Every league folder's season, for the Leagues section of the landing page."""
        out = []
        for league in leagues.leagues(data_dir):
            try:
                out.append(service.summary(league))
            except HTTPException as exc:
                out.append({"league": league, "error": str(exc.detail)})
        return out

    @app.get("/seasons/{league}")
    def get_season(league: str = league_id) -> dict[str, Any]:
        return service.view(league)

    @app.post("/seasons/{league}/refresh", status_code=202)
    async def refresh_season(
        league: str = league_id,
        wait: bool = Query(False, description="return once the refresh is done"),
    ) -> dict[str, Any]:
        """Read the league's public sources again. A private league answers 409."""
        if wait:
            service._base(league)
            job = service.jobs.get(league)
            if job is None or job.status != "running":
                job = service.jobs[league] = RefreshJob(league)
                await asyncio.to_thread(service.run_refresh, job)
            else:
                while job.status == "running":
                    await asyncio.sleep(0.25)
        else:
            job = service.start_refresh(league)
        if job.status == "private":
            raise HTTPException(409, job.error)
        if job.status == "failed":
            raise HTTPException(502, job.error)
        return {"refresh": job.to_dict(), "season": service.summary(league)}

    @app.post("/seasons/{league}/snapshot")
    def post_snapshot(body: SnapshotBody, league: str = league_id) -> dict[str, Any]:
        """Pages or parsed parts of a league read in the user's own Chrome (the extension, for
        the private league)."""
        return service.snapshot(league, body)

    return service
