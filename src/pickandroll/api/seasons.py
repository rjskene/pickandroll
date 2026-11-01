"""The in-season state of each league folder (docs/ADD_DROP.md, phase 1, issue #92).

Routes:

``GET /seasons``
    One row per league folder for the dashboard's Leagues section: name, week, my record,
    this week's opponent, when the snapshot was last read, and any refresh in progress.
``GET /seasons/{league}``
    The season view: settings, the week and the next ones, standings, every roster, my
    matchup, the available players and the league's transactions, and the breakout flag of
    the available players (#95, ``season_flags``) with the signals today's inputs leave silent
    and the flag's thresholds for the explainer (#113).
``POST /seasons/{league}/refresh``
    Reads the league's public sources (a public league: the prize leagues) in the background;
    ``?wait=true`` returns once it is done. One refresh runs at a time per league, and each
    within :data:`REFRESH_DEADLINE` (#166). A private league answers ``409`` with what to do.
    Yahoo's rate limit answers ``503`` with a ``Retry-After`` header, any other failure ``502``;
    the next refresh resumes at the page the limit stopped (#180).
``POST /seasons/{league}/snapshot``
    The extension's reads of a private league: whole pages (``{url, html}``, parsed here by
    the same parsers) or parts already parsed (``{key, data}``).
``GET /seasons/{league}/moves``
    Every available player's best move this week and over the next three, and the recommended
    moves under the weekly add limit (#94, ``season_moves``); ``?system=yahoo`` for Yahoo's
    projection, ``?system=blend`` for the blend of the two (#152), the knob file's system
    (``api.season_knobs``) when the route names none.
``GET /seasons/{league}/moves/{player}``
    The move drawer: adding ``player`` (for ``?drop=``) per category on both horizons, with
    every other drop and the best other adds.
``GET /seasons/{league}/lineup``
    The Lineup view (#107, ``season_lineup``): my recommended starters for each day of a week
    (``?week=``, this one by default) against Yahoo's lineup as read, the games it loses, the
    held slots with who is eligible for them, and first any held player whose status cleared.
``GET /seasons/{league}/lineup/steps``
    The lineup executor's steps for ``?date=`` (today by default; #170, ``season_autopilot``):
    the legal changes from Yahoo's lineup as read to one that starts the recommended players,
    with each player's tip-off; none when the mode is off, STOP is on or the day is closed.
``GET /seasons/{league}/autopilot``, ``POST /seasons/{league}/autopilot/lineup``
    The executor's mode, STOP, the live check and its runs; a run appended to the league's log
    (``data/leagues/<id>/autopilot/<date>.json``). ``PUT /leagues/{league}/lineups`` sets the
    mode, the dashboard's own click; ``live`` waits for the dry run.
``GET /autopilot/queue``, ``POST /autopilot/queue/build``, ``POST /autopilot/queue/{id}/strike``,
``PUT /autopilot/queue/settings``
    The moves executor's queue (#171, ``season_queue``): built from the day's moves solves in the
    decision log, never solved; the user's veto and execute time. ``GET`` and ``POST
    /seasons/{league}/autopilot/moves``, ``GET …/moves/due``: the league's Queue card, its pass
    log under ``moves`` and the entries due for the extension, with the IL moves their open-spot
    claims need first (``il_first``, #214) and the held drops its churns need first
    (``drop_first``, #221 part 3); ``POST /seasons/{league}/autopilot/il`` and ``…/drop`` log
    those under ``il`` and ``drop``; ``PUT /leagues/{league}/moves`` sets the mode and the user's cap. ``GET
    /autopilot/start-active/due`` and ``POST /seasons/{league}/autopilot/start-active``: the
    leagues that want Yahoo's Start Active Players for the rest of the week and the runs' log
    under ``start_active`` (#215).
``GET /seasons/{league}/decisions``
    The decision log (#125, ``season_decisions``): every moves and strategy solve of the days
    ``?from=``..``?to=`` (the last week by default) and my moves of those days from the
    transactions page, each matched to the latest solve before it.
``GET /seasons/{league}/strategy``
    The Strategy panel (#110, ``season_strategy``): today's run of the strategy engine, the
    recommended set at each weight of this week against the rest of the season, from the exact
    search and the linear program; never solves (``not_solved`` until a POST).
``POST /seasons/{league}/strategy``
    Start that run (``?pool=`` 30 by default, up to 60, ``?weights=``, ``?lock=`` players never
    dropped, ``?program_only=true`` for the linear program with the search as its fallback only,
    ``?wait=true`` to answer once it is done).
``POST /seasons/{league}/trade``
    The Trade card (#96, ``season_trades``): a proposal between my roster and one other team's
    (``{team, give, get}``, players by Yahoo id), both sides before and after on the moves'
    horizons, each resulting roster's slots, the traded players' games and the margin that
    leaves the trade neutral on my side. Nothing is proposed or sent to Yahoo.
``POST /seasons/{league}/record``
    The weekly recorder (#97, ``season_record``): a finished week's standings, each team's
    totals, games and result, the matchups and the drafted players' season lines, written to
    ``season/weeks/<week>.json``; ``?week=`` for a past week, by default the latest one over.
    Recording a week again writes only what changed. A private league answers ``409`` with the
    pages still to open in the user's Chrome.
``GET /seasons/{league}/weeks``
    The recorded weeks: my opponent, result and place after each (``/weeks/{week}``: a record).
``GET /seasons/{league}/scorecard``
    The Monday scorecard (#126, ``season_scorecard``): the league's recorded weeks to ``?week=``
    (the last recorded by default), each against the decision log's projection of it, my moves
    of each matched to the solve before them, the season to date and the odds' calibration.
``GET /seasons/scorecard``
    Every league's scorecard of ``?week=`` (the last any league recorded), the odds pooled over
    the public leagues that projected it (the private league apart), and the week as markdown
    for the AUTOPILOT tracker (#127). Unless ``?system=`` names one, both score each week on the
    system in force when it began (#152): the knob file's for the league, as the decision log
    recorded it, so a change of system scores its first week on the old one for both halves.
``POST /autopilot/monday``
    The Monday hill-climb step (#152, ``season_hillclimb``): the verdicts due, at most one knob
    change from the rule table, written to the knob file with the Monday note and the Monday's
    comment for #127 (``comment``: counts and ratios, leagues by id, no team or league name, no
    projection number); once a Monday (``?force=true`` undoes that Monday's change and runs
    again), ``?dry_run=true`` writes nothing.
``GET /flags/digest``
    The day's breakout flags across every league with a season: each league's flagged players
    with their evidence, and the digest as markdown for a public issue (leagues by id, no team
    or league names, no number derived from Basketball Monster).

Storage, all under ``data/`` and never committed: ``data/leagues/<id>/season/state.json`` holds
the latest read of every part with its time and source, and every refresh or snapshot is kept
as ``season/snapshots/<UTC time>-<source>.json``. The matchup weeks are the same for every league
of the season, so their calendar is shared in ``data/leagues/_shared/season/calendar.json``; the
NBA schedule is cached by date in ``data/schedule/``.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import math
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as FastPath
from pydantic import BaseModel, Field, ValidationError

from ..season import (
    EXTENSION,
    PUBLIC,
    YAHOO_WEEK,
    Calendar,
    Part,
    Season,
    SeasonSettings,
    Week,
    build_calendar,
    lineup_key,
    matchup_key,
    merge_part,
    monday_of,
    mondays,
    pairings_key,
    roster_key,
    unpaired_matchups,
)
from ..season import autopilot as qa
from ..season import moves as mv
from ..season import record as season_rec
from ..season import status as st
from ..season.state import SLOTS_PAGE
from ..sources import boxscores
from ..sources import schedule as nba_schedule
from ..sources.yahoo import pages, public
from . import (
    leagues,
    season_autopilot,
    season_cantcut,
    season_decisions,
    season_flags,
    season_hillclimb,
    season_knobs,
    season_lineup,
    season_matchup,
    season_moves,
    season_outlook,
    season_passes,
    season_progress,
    season_queue,
    season_record,
    season_scorecard,
    season_status,
    season_strategy,
    season_trades,
)
from .season_week import BBM_NEXT_WEEK, BBM_ROS, BBM_THIS_WEEK, NBA_TZ, week_projection

SEASON_DIR = "season"
STATE = "state.json"
SNAPSHOTS = "snapshots"
SCHEDULE_DIR = "schedule"
CALENDAR = "calendar.json"
#: The weeks a season view looks ahead: this one and the next three (the Moves card's horizon).
WEEKS_AHEAD = 4
#: The NBA's dates (and Yahoo's pages) run on US Eastern time.
TRANSACTIONS_SHOWN = 30
#: The most days of box scores a refresh reads (each a scoreboard and a summary per game): a
#: daily refresh reads one, and a cache begun late catches up over a few refreshes.
BOX_DAYS = 14

FetchFactory = Callable[[], public.Fetch]
#: The server's own log, where uvicorn writes beside its access lines (which carry no times
#: and no app lines): each refresh's start and end, with its time (#153).
LOG = logging.getLogger("uvicorn.error")


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


#: A day's lineup is kept this long: this week's and last week's days.
LINEUP_KEPT = timedelta(days=14)


def save(
    data_dir: Path,
    league: str,
    parts: dict[str, Part],
    received: list[Part],
    source: str,
    now: datetime,
) -> None:
    """The season's parts, less the matchup pages whose teams were misread
    (``unpaired_matchups``) and the lineup pages older than :data:`LINEUP_KEPT` at ``now`` (the
    service's clock), and a snapshot of what was received, named for when it was written."""
    misread = unpaired_matchups(parts)
    parts = {k: p for k, p in parts.items() if k not in misread}
    folder = season_dir(data_dir, league)
    oldest = (now - LINEUP_KEPT).date().isoformat()
    parts = {k: p for k, p in parts.items() if not (k.startswith("lineup/") and k[-10:] < oldest)}
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


#: A page's look at the moves (#240): ``source=page`` on the route, the web's flag only.
PAGE = "page"
#: Why a page's answer is an older one while the moves of newer inputs are solved (#240).
STALE_REASON = "inputs newer than this answer; solving"
#: The page's solves run here, one at a time, never on the process pool from the route (#240).
_PAGE_SOLVES = ThreadPoolExecutor(max_workers=1, thread_name_prefix="moves-page")


def nba_today(now: datetime) -> date:
    return now.astimezone(NBA_TZ).date()


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat(timespec="seconds")


# --------------------------------------------------------------------------- refresh jobs
#: How long a public refresh may run, in seconds (#166): checked before every read and between
#: the steps, and by everything that reads the job. Past it the job ends failed, naming the step,
#: the page and the time it ran, and the league's next refresh can start. A read in flight
#: finishes or times out on its own socket timeout (``public.HttpFetch``); the step it cut is not
#: retried in the same job.
REFRESH_DEADLINE = 300.0
#: The seconds a refresh keeps for its reads after a backoff on Yahoo's rate limit: a wait that
#: would leave less before the deadline is not slept and the read gives up (#180).
WAIT_MARGIN = 30.0
#: How long the Yahoo pages of a refresh the rate limit ended are kept for the league's next one
#: (#180): a page read longer ago is read again.
HOLD = timedelta(minutes=60)
#: Who ``armed.json`` says set a moves mode from the Queue screen's one switch (#205); the
#: Queue card's single switch records ``dashboard``.
EVERY_LEAGUE = "dashboard: every league"
#: The evening routine's pass is a moves pass (#209): the evening sets no lineup.
EVENING_MOVES_ONLY = "the evening pass is a moves pass"


class RefreshDeadline(BaseException):
    """A refresh past its deadline. Like ``asyncio.CancelledError``, a ``BaseException``: the
    refresh's broad handlers (a flag input, a box score day, a schedule date) let it through,
    since the deadline ends the job and is never one more warning."""


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
    #: What failed without failing the job: the breakout flag's inputs, by input, and the
    #: matchup pages skipped.
    warnings: dict[str, str] = field(default_factory=dict)
    #: The seconds the job may run (a public refresh's :data:`REFRESH_DEADLINE`, #166); None
    #: for none.
    deadline: float | None = None
    #: The last page the job read, for the deadline's reason.
    page: str | None = None
    #: Yahoo's rate limit ended the job (#180), and the seconds before Yahoo may be read again.
    rate_limited: bool = False
    retry_after: float | None = None
    #: The Yahoo pages kept for the league's next refresh when the limit ended the job, and the
    #: pages this job took from an earlier one's instead of reading them (#180).
    held: int = 0
    resumed: int = 0
    _began: float = field(default_factory=time.monotonic, repr=False, compare=False)
    _ending: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _ended: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def elapsed(self) -> float:
        """The seconds since the job began."""
        return time.monotonic() - self._began

    def overdue(self) -> bool:
        return self.deadline is not None and self.elapsed() > self.deadline

    def late(self) -> str:
        """The deadline's reason: the step and the page the job was on, and the time it ran."""
        page = f", reading {self.page}" if self.page else ""
        return (
            f"past the {self.deadline:g}-second deadline after {self.elapsed():.0f} s: at "
            f"{self.step}{page}"
        )

    def check(self) -> None:
        """Raise :class:`RefreshDeadline` once the job is past its deadline."""
        if self.overdue():
            raise RefreshDeadline(self.late())

    def at(self, step: str) -> None:
        """Go on to ``step``, the deadline allowing."""
        self.check()
        self.step = step

    def may_wait(self, seconds: float) -> bool:
        """Whether a backoff of ``seconds`` on Yahoo's rate limit still leaves
        :data:`WAIT_MARGIN` before the deadline (#180)."""
        return self.deadline is None or self.elapsed() + seconds + WAIT_MARGIN <= self.deadline

    def end(self, status: str, error: str | None = None, **fields: Any) -> bool:
        """End the job once: the first end sets ``status``, ``error``, ``fields`` and the time
        and says so; a later one (a stalled worker's, after the deadline ended its job) changes
        nothing."""
        with self._ending:
            if self.finished_at is not None:
                return False
            for name, value in fields.items():
                setattr(self, name, value)
            self.status, self.error, self.finished_at = status, error, datetime.now(UTC)
            self._ended.set()
            return True

    def wait(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for the job to end; whether it has."""
        return self._ended.wait(timeout)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "step": self.step,
            "done": self.done,
            "total": self.total,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error": self.error,
            "warnings": self.warnings,
            "page": self.page,
            "rate_limited": self.rate_limited,
            "retry_after": self.retry_after,
            "held": self.held,
            "resumed": self.resumed,
        }


class Hold:
    """The Yahoo pages a refresh reads, kept for the league's next refresh when the rate limit
    ends it (#180): by URL, gzipped, each with the time it was read. The next refresh takes a
    page an earlier one read within :data:`HOLD` from here and reads the rest, from the page the
    limit stopped on; its parts carry their own page's read time (:meth:`stamp`). A page read
    twice in one refresh is read twice, as before. Nothing reaches the season until a refresh
    completes, so the state never mixes a half-read. In memory only, never on disk: an API
    restart starts clean, at the first page."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self.clock = clock
        #: The pages earlier refreshes read, and the ones this one read.
        self.earlier: dict[str, tuple[datetime, bytes]] = {}
        self.pages: dict[str, tuple[datetime, bytes]] = {}
        #: The earlier pages taken instead of read.
        self.taken: set[str] = set()
        self._read_at: datetime | None = None

    def wrap(self, fetch: public.Fetch) -> public.Fetch:
        """``fetch`` through the hold: an earlier page still fresh comes from here, any other
        is read and, a Yahoo page, kept."""

        def read(url: str) -> str:
            kept = self.earlier.get(url)
            if kept is not None and self.clock() - kept[0] <= HOLD:
                self._read_at = kept[0]
                self.taken.add(url)
                return gzip.decompress(kept[1]).decode("utf-8")
            text = fetch(url)
            self._read_at = self.clock()
            if public.is_yahoo(url):
                self.pages[url] = (self._read_at, gzip.compress(text.encode("utf-8")))
            return text

        return read

    def stamp(self) -> datetime:
        """When the page last returned was read: the stamp of the part built from it."""
        return self._read_at or self.clock()

    def kept(self) -> Hold:
        """The pages still fresh, earlier ones and this refresh's, for the next refresh."""
        out = Hold(self.clock)
        now = self.clock()
        pages = {**self.earlier, **self.pages}
        out.earlier = {u: v for u, v in pages.items() if now - v[0] <= HOLD}
        return out

    def until(self) -> datetime | None:
        """When the oldest page kept is too old to take."""
        times = [t for t, _ in self.earlier.values()]
        return min(times) + HOLD if times else None


def log_refresh(data_dir: Path, job: RefreshJob) -> None:
    """A refresh job's start or end, with when it was written, appended to the league's refresh
    log (``season_status.REFRESHES``) and a line in the server's log. The light reads the last
    one after a restart, and a start with no end is a refresh that never finished (#153)."""
    line = {"at": datetime.now(UTC).isoformat(), "league": job.league, **job.to_dict()}
    path = season_dir(data_dir, job.league) / season_status.REFRESHES
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(line, separators=(",", ":")) + "\n")
    except OSError as exc:
        LOG.warning("refresh %s: the job was not logged: %s", job.league, exc)
    LOG.info(
        "%s refresh %s %s at %s %d/%d%s",
        line["at"],
        job.league,
        job.status,
        job.step,
        job.done,
        job.total,
        f": {job.error}" if job.error else "",
    )


def retry_after(seconds: float | None) -> dict[str, str]:
    """The ``Retry-After`` header of a 503 on Yahoo's rate limit (#180), the cool-off's length
    when Yahoo named none."""
    return {"Retry-After": str(math.ceil(seconds if seconds is not None else public.COOL_OFF))}


def deadlined(fetch: public.Fetch, job: RefreshJob) -> public.Fetch:
    """``fetch`` for ``job``: each read first checks the job's deadline and then notes its
    page (#166)."""

    def read(url: str) -> str:
        job.check()
        job.page = url
        return fetch(url)

    return read


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
        #: The Mac's clock, the daily routine's day and due time (#153); None: the system's.
        self.local_tz: tzinfo | None = None
        self.jobs: dict[str, RefreshJob] = {}
        #: Each league's Yahoo pages kept from a refresh the rate limit ended (#180).
        self.held: dict[str, Hold] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        #: One reader of ESPN's box scores at a time: two refreshes read a date once (#126).
        self._box_lock = threading.Lock()
        #: One writer of the ESPN ids the scorecards match.
        self._ids_lock = threading.Lock()
        self.moves_cache = season_moves.MovesCache()
        #: When each kept moves answer was made, by its cache key (#240).
        self._moves_at: dict[tuple[Any, ...], datetime] = {}
        #: The page solves started and not done, by key: at most one a key (#240).
        self._page_solving: set[tuple[Any, ...]] = set()
        self._page_lock = threading.Lock()
        #: Where a page's solve runs (tests run it at once).
        self.page_solves: Executor = _PAGE_SOLVES
        self.flags_cache = season_moves.MovesCache()
        self.strategy_runs = season_strategy.Runs()
        #: The strategy engine's programs run in the background process pool; 1: in process.
        self.strategy_workers: int | None = None

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
        out = _summary(season, is_public, bool(parts), self.job(league))
        if not parts:
            return out
        # The landing grid's card (#108): the week's score, the adds left and the flags.
        out |= _glance(season, nba_today(self.clock()))
        try:
            players, flags, _ = self._flags(league)
            out["flags"] = dict(Counter(f.level for _, f in season_flags.flagged(players, flags)))
        except Exception as exc:  # noqa: BLE001 - the card reads without its flags
            out["flags"] = None
            out["flags_error"] = f"{type(exc).__name__}: {exc}"
        return out

    def view(self, league: str) -> dict[str, Any]:
        base, is_public = self._base(league)
        parts = load_parts(self.data_dir, league)
        season = Season.from_parts(base, parts)
        today = nba_today(self.clock())
        try:
            _, flags, inputs = self._flags(league)
            flag_view = {
                "flags": season_flags.payload(flags),
                "flag_inputs": {**inputs, "silent": season_flags.silent(inputs)},
            }
        except Exception as exc:  # noqa: BLE001 - the season reads without its flags
            flag_view = {"flags": {}, "flag_inputs": {"error": f"{type(exc).__name__}: {exc}"}}
        # The explainer's thresholds come from the flag itself, never from copies in the web.
        flag_view["flag_config"] = season_flags.config()
        return {
            **_summary(season, is_public, bool(parts), self.job(league)),
            **_view(season, today),
            "week_projection": week_projection(season, today, self.data_dir, WEEKS_AHEAD),
            **flag_view,
        }

    # ------------------------------------------------------------------ breakout flags
    def _flags(
        self, league: str
    ) -> tuple[list[season_flags.fl.Pickup], dict[int, season_flags.fl.Flag], dict[str, Any]]:
        """The league's flags, made again when its state or a flag input changes, or the day."""
        base, _ = self._base(league)
        now = self.clock()
        today = nba_today(now)
        state = season_dir(self.data_dir, league) / STATE
        stamp = (
            state.stat().st_mtime_ns if state.exists() else None,
            season_flags.stamp(self.data_dir, today),
        )

        def make() -> Any:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_flags.league_flags(season, today, self.data_dir, now)

        return self.flags_cache.get((league, "flags", "flags", today, stamp), make)

    def digest(self) -> dict[str, Any]:
        """Every league's flagged players with their evidence, and the digest as markdown."""
        now = self.clock()
        today = nba_today(now)
        rows: list[dict[str, Any]] = []
        lineups: list[dict[str, Any]] = []
        lineup_lines: list[str] = []
        cleared_lines: list[str] = []
        shown: list[tuple[str, list[tuple[season_flags.fl.Pickup, season_flags.fl.Flag]]]] = []
        skipped: list[dict[str, str]] = []
        inputs: dict[str, Any] | None = None
        for league in leagues.leagues(self.data_dir):
            try:
                base, _ = base_settings(self.data_dir, league)
            except leagues.LeagueError as exc:
                skipped.append({"league": league, "reason": str(exc)})
                continue
            parts = load_parts(self.data_dir, league)
            if not parts:
                skipped.append({"league": league, "reason": NO_SEASON})
                continue
            try:
                name = Season.from_parts(base, parts).settings.name
                players, flags, inputs = self._flags(league)
            except Exception as exc:  # noqa: BLE001 - one league's failure leaves the others
                skipped.append({"league": league, "reason": f"{type(exc).__name__}: {exc}"})
                continue
            top = season_flags.flagged(players, flags)
            rows.append(season_flags.digest_league(league, name, top))
            shown.append((league, top))
            line = self._lineup_line(league, today)
            if line.get("line"):
                lineup_lines.append(line["line"])
            if line.get("cleared_line"):
                cleared_lines.append(line["cleared_line"])
            lineups.append({"league": league, **line})
        notes = season_flags.stale(inputs, now) if inputs is not None else []
        # The markdown is public: a league's own failure text stays in the JSON.
        unread = [(x["league"], _public_reason(x["reason"])) for x in skipped]
        markdown = season_flags.fl.digest_markdown(today, shown, notes, unread)
        executor = season_autopilot.digest_lines(self.data_dir, self._lineup_modes(), now)
        moves_executor = season_autopilot.moves_digest_lines(
            self.data_dir,
            self._modes(leagues.MOVES),
            season_queue.latest(self.data_dir, today),
            now,
        )
        return {
            "date": today.isoformat(),
            "generated_at": now.isoformat(),
            "inputs": inputs,
            "notes": notes,
            "leagues": rows,
            "skipped": skipped,
            "lineups": lineups,
            "executor": executor,
            "moves_executor": moves_executor,
            "markdown": markdown
            + season_lineup.digest_section([*cleared_lines, *executor, *lineup_lines])
            + season_autopilot.moves_digest_section(moves_executor),
        }

    def _lineup_modes(self) -> dict[str, dict[str, Any]]:
        """Every league's lineup executor mode (#170)."""
        return self._modes(leagues.LINEUPS)

    def _lineup_line(self, league: str, today: date) -> dict[str, Any]:
        """A league's lineup for the digest: today's and tomorrow's games lost as set and the
        line saying so (None when nothing is lost or nothing was read), and the line naming a
        held player whose status cleared; the failure, if any, stays in the JSON."""
        try:
            out = self.lineup(league, None, None)
        except HTTPException as exc:
            return {"line": None, "error": str(exc.detail)}
        except Exception as exc:  # noqa: BLE001 - a lineup's failure leaves the digest
            return {"line": None, "error": f"{type(exc).__name__}: {exc}"}
        last = today + timedelta(days=season_lineup.DIGEST_DAYS - 1)
        days = [d for d in out["days"] if not d["past"] and d["date"] <= last.isoformat()]
        return {
            "line": season_lineup.digest_line(league, out, today),
            "lost": sum(d["lost"] or 0 for d in days),
            "unread": [d["date"] for d in days if d["yahoo"] is None],
            "cleared": [a for a in out["alerts"] if a["kind"] == "cleared"],
            "cleared_line": season_lineup.cleared_line(league, out),
        }

    def _flag_inputs(self, job: RefreshJob, fetch: public.Fetch, today: date) -> None:
        """Read the flag's network inputs; a failure is a warning on the job, never its end."""
        try:
            job.warnings |= season_flags.read_inputs(self.data_dir, fetch, today, self.clock())
        except Exception as exc:  # noqa: BLE001 - a flag input is not worth a failed refresh
            job.warnings["flag inputs"] = f"{type(exc).__name__}: {exc}"

    def _box_scores(
        self, job: RefreshJob, fetch: public.Fetch, today: date, calendar: Calendar | None
    ) -> None:
        """Cache the final box scores the scorecard's realized values read (#126): each day of
        the season to yesterday not cached yet, oldest first, at most :data:`BOX_DAYS` a
        refresh. What is not read is a warning on the job, never its end."""
        if calendar is not None and calendar.weeks:
            first, end = calendar.weeks[0].start, calendar.weeks[-1].end
        else:
            first, end = today - timedelta(BOX_DAYS), today
        last = min(end, today - timedelta(1))
        days = [first + timedelta(n) for n in range((last - first).days + 1)]
        try:
            with self._box_lock:
                read = boxscores.read_days(
                    days,
                    fetch,
                    self.data_dir / season_scorecard.BOXSCORES_DIR,
                    self.clock(),
                    BOX_DAYS,
                )
        except Exception as exc:  # noqa: BLE001 - the box scores are not worth a failed refresh
            job.warnings["box scores"] = f"{type(exc).__name__}: {exc}"
            return
        left = [
            f"{len(read[k])} {words}"
            for k, words in (("failed", "failed"), ("left", "left for the next refresh"))
            if read[k]
        ]
        if left:
            job.warnings["box scores"] = "days " + ", ".join(left)

    def _record_adds(self, league: str, today: date) -> None:
        """Keep the pool's Yahoo-wide adds read today, the adds history every league shares."""
        try:
            season = self.season(league)
            adds = season_flags.pool_adds(season, today)
            if adds:
                season_flags.record_adds(self.data_dir, today, adds, at=self.clock())
        except Exception:  # noqa: BLE001, S110 - the history misses a day's adds, nothing more
            pass

    # ------------------------------------------------------------------ moves
    def _moves_stamp(self, league: str) -> tuple[Any, ...]:
        """What the moves of a league depend on beyond the day: the state file, the projection
        exports, the injury report (an O's return date), the knob file (#152) and Yahoo's
        can't-cut list (#220)."""
        files = [
            season_dir(self.data_dir, league) / STATE,
            self.data_dir / "aliases.json",
            season_flags.injuries_path(self.data_dir),
            season_knobs.autopilot_dir(self.data_dir) / season_knobs.KNOBS_FILE,
            season_cantcut.path_of(self.data_dir, league),
        ]
        for pattern in (*BBM_ROS, BBM_THIS_WEEK, BBM_NEXT_WEEK):
            files += sorted(self.data_dir.glob(pattern))
        return tuple((f.name, f.stat().st_mtime_ns) for f in files if f.exists())

    def _system(self, league: str, system: str | None) -> str:
        """``system``, or when the route names none the one the knob file has in force for
        ``league`` (#152; Basketball Monster's without one)."""
        return system or season_knobs.for_league(self.data_dir, league)["system"]

    def _built(self, league: str, system: str | None) -> season_moves.Built:
        base, _ = self._base(league)
        system = self._system(league, system)
        today = nba_today(self.clock())
        key = (league, system, "built", today, self._moves_stamp(league))

        def make() -> season_moves.Built | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            knobs = season_knobs.for_league(self.data_dir, league)
            return season_moves.build(season, today, self.data_dir, system, knobs)

        built = self.moves_cache.get(key, make)
        if built is None:
            raise HTTPException(409, f"league {league} has no season of my team to move in yet")
        return built

    def moves(
        self, league: str, system: str | None, source: str | None = None, entry: bool = False
    ) -> dict[str, Any]:
        """``_moves``, with a standard-waivers league's claim at the rival claim rate the settings
        file holds now (#261): read at request time, past the kept solve."""
        out = self._moves(league, system, source, entry)
        claim = out.get("claim")
        if claim is None:
            return out
        rate = season_queue.rival_claim_rate(self.data_dir)
        return {**out, "claim": mv.priority_claim(claim["priority"], claim["teams"], rate)}

    def _moves(
        self, league: str, system: str | None, source: str | None = None, entry: bool = False
    ) -> dict[str, Any]:
        """Today's moves on the league's current inputs, solved once a key. A solve without
        ``source`` writes its decision entry; ``entry`` (the route's call without a source, the
        routine's) writes one every call, from the answer kept when there was no solve to write
        it, with that answer's build time (#240 (i)). ``source="page"`` (#240): never logged and
        never waits on a solve when an answer of today is kept: that one comes back at once with
        ``stale`` while the solve of the newer inputs runs on the page's thread."""
        system = self._system(league, system)
        today = nba_today(self.clock())
        stamp = self._moves_stamp(league)
        key = (league, system, "moves", today, stamp)
        if source == PAGE:
            kept = self.moves_cache.peek(key)
            if kept is not None:
                return kept
            older = self.moves_cache.latest(key[:3])
            if older is None or older[0][3] != today:
                return self._solve_moves(league, system, key, log=False)
            self._solve_later(league, system, key)
            inputs = max((ns for _, ns in stamp), default=None)
            stale = {
                "built_at": _iso(self._moves_at.get(older[0])),
                "inputs_at": None
                if inputs is None
                else _iso(datetime.fromtimestamp(inputs / 1e9, UTC)),
                "reason": STALE_REASON,
            }
            return {**older[1], "stale": stale}
        made: list[bool] = []
        out = self._solve_moves(league, system, key, log=True, made=made)
        if entry and not made:
            built = self._built(league, system)
            built_at = _iso(self._moves_at.get(key))
            self._log(
                league,
                lambda at: {**season_decisions.moves_entry(built, out, at), "built_at": built_at},
            )
        return out

    def _solve_moves(
        self,
        league: str,
        system: str,
        key: tuple[Any, ...],
        log: bool,
        made: list[bool] | None = None,
    ) -> dict[str, Any]:
        """The moves of ``key``, solved once under the cache's gate for it; ``made`` gets True
        when this call solved them, and ``log`` writes the decision entry of that solve."""
        built = self._built(league, system)

        def make() -> dict[str, Any]:
            out = season_moves.moves_payload(built)
            at = self.clock()
            with self._page_lock:
                for old in [k for k in self._moves_at if k[:3] == key[:3]]:
                    del self._moves_at[old]
                self._moves_at[key] = at
            if made is not None:
                made.append(True)
            if log:
                self._log(league, lambda at: season_decisions.moves_entry(built, out, at))
            return out

        return self.moves_cache.get(key, make)

    def _solve_later(self, league: str, system: str, key: tuple[Any, ...]) -> None:
        """Solve ``key``'s moves on the page's thread, unless a page solve of it is on already;
        a failure leaves the next look to try again."""
        with self._page_lock:
            if key in self._page_solving:
                return
            self._page_solving.add(key)

        def run() -> None:
            try:
                self._solve_moves(league, system, key, log=False)
            except Exception:  # noqa: BLE001, S110 - the next look solves again
                pass
            finally:
                with self._page_lock:
                    self._page_solving.discard(key)

        self.page_solves.submit(run)

    def _log(self, league: str, entry: Callable[[datetime], dict[str, Any]]) -> None:
        """Keep a finished solve in the decision log (#125); a failure to log loses the entry,
        never the answer."""
        try:
            season_decisions.append(season_dir(self.data_dir, league), entry(self.clock()))
        except Exception:  # noqa: BLE001, S110 - the log misses one solve, nothing more
            pass

    def decisions(self, league: str, start: date | None, end: date | None) -> dict[str, Any]:
        """The decision log (#125): the entries of ``start``..``end`` and my moves in those days,
        each matched to the latest entry before it."""
        base, _ = self._base(league)
        today = nba_today(self.clock())
        season = Season.from_parts(base, load_parts(self.data_dir, league))
        entries = season_decisions.load(season_dir(self.data_dir, league), end)
        return season_decisions.payload(entries, season, today, start, end)

    def best(self, league: str, system: str | None, solve: bool = False) -> dict[str, Any]:
        """The landing grid's best move (#108): from the moves already solved today, or, with
        ``solve``, solved now. Without it nothing is solved: a cold league says so."""
        system = self._system(league, system)
        if solve:
            self.moves(league, system)
        else:
            self._base(league)
        today = nba_today(self.clock())
        stamp = self._moves_stamp(league)
        payload = self.moves_cache.peek((league, system, "moves", today, stamp))
        built = self.moves_cache.peek((league, system, "built", today, stamp))
        if payload is None or built is None:
            return {"league": league, "status": "not_solved", "system": system}
        return {"league": league, **season_moves.best_payload(built, payload)}

    # ------------------------------------------------------------------ strategy
    def strategy(self, league: str, system: str | None) -> dict[str, Any]:
        """Today's strategy run on the league's current inputs; never solves."""
        self._base(league)
        system = self._system(league, system)
        today = nba_today(self.clock())
        run = self.strategy_runs.get(league, system, today, self._moves_stamp(league))
        if run is None:
            return {"league": league, "status": "not_solved", "system": system}
        return {"league": league, **run.payload()}

    def solve_strategy(
        self,
        league: str,
        system: str | None,
        settings: season_strategy.Settings,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Start the strategy run with ``settings`` (or find it), and its payload so far."""
        system = self._system(league, system)
        built = self._built(league, system)
        today = nba_today(self.clock())
        stamp = self._moves_stamp(league)
        mine = {k for k, _ in built.problem.roster}
        settings = season_strategy.Settings(
            settings.pool,
            settings.weights,
            tuple(sorted(k for k in set(settings.keep) if k in mine)),
            settings.program_only,
        )
        run = self.strategy_runs.start(
            league,
            system,
            (today, stamp, settings),
            lambda: season_strategy.Run(
                (today, stamp, settings),
                built,
                lambda: self.moves(league, system),
                settings,
                self.strategy_workers,
                on_solved=lambda run: self._log(
                    league, lambda at: season_decisions.strategy_entry(built, run.payload(), at)
                ),
            ),
        )
        if wait:
            run.done.wait()
        return {"league": league, **run.payload()}

    def matchup(self, league: str, system: str | None) -> dict[str, Any]:
        """The Matchup view (#116): my matchup's scoreboard and what each player adds to it."""
        system = self._system(league, system)
        built = self._built(league, system)
        base, _ = self._base(league)
        today = nba_today(self.clock())
        key = (league, system, "matchup", today, self._moves_stamp(league))

        def make() -> dict[str, Any] | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_matchup.payload(built, season)

        out = self.moves_cache.get(key, make)
        if out is None:
            raise HTTPException(409, f"league {league} has no matchup of my team this week")
        return {"league": league, **out}

    def outlook(self, league: str, system: str | None) -> dict[str, Any]:
        """The Season view (#116): every week left of my season as win odds, each with its
        scoreboard and what my players add to it."""
        system = self._system(league, system)
        built = self._built(league, system)
        base, _ = self._base(league)
        today = nba_today(self.clock())
        key = (league, system, "outlook", today, self._moves_stamp(league))

        def make() -> dict[str, Any] | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_outlook.payload(built, season, today, self.data_dir)

        out = self.moves_cache.get(key, make)
        if out is None:
            raise HTTPException(409, f"league {league} has no season of my team to look ahead in")
        return {"league": league, **out}

    # ------------------------------------------------------------------ the lineup executor
    def lineup_steps(self, league: str, day: date | None) -> dict[str, Any]:
        """The lineup executor's steps for ``day``, today by default (#170): the Lineup view's
        day of its week, never solved again; in a live league with the live guard now
        (``live``, #170 PR 3)."""
        base, _ = self._base(league)
        now = self.clock()
        today = nba_today(now)
        day = day or today
        mode = leagues.lineup_mode(self.data_dir, league)
        season = Season.from_parts(base, load_parts(self.data_dir, league))
        weeks = season.calendar.weeks if season.calendar is not None else []
        week = next((w.number for w in weeks if w.start <= day <= w.end), None)
        lineup = None
        if week is not None and base.my_team_id is not None:
            try:
                lineup = self.lineup(league, None, week)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        tips = nba_schedule.load_tips(day, self.data_dir / SCHEDULE_DIR)
        stop = season_autopilot.stopped(self.data_dir)
        live = (
            season_autopilot.live_check(self.data_dir, league, mode)
            if mode["mode"] == "live"
            else None
        )
        return season_autopilot.steps_payload(
            league, base.my_team_id, day, today, now, lineup, tips, mode, stop, live
        )

    def autopilot(self, league: str) -> dict[str, Any]:
        """The Lineup view's executor panel (#170)."""
        self._base(league)
        mode = leagues.lineup_mode(self.data_dir, league)
        return season_autopilot.view(self.data_dir, league, mode, nba_today(self.clock()))

    def log_lineup_run(self, league: str, run: season_autopilot.LineupRun) -> dict[str, Any]:
        """Append a run of the lineup executor to the league's log (#170), refused (409) when
        the mode, STOP, the live guard (a live run, #170 PR 3) or the run's own outcome says it
        should not have run."""
        self._base(league)
        mode = leagues.lineup_mode(self.data_dir, league)
        live = (
            season_autopilot.live_check(self.data_dir, league, mode) if run.mode == "live" else None
        )
        why = season_autopilot.check_run(run, mode, season_autopilot.stopped(self.data_dir), live)
        if why is not None:
            raise HTTPException(409, why)
        record = {
            "at": self.clock().isoformat(timespec="seconds"),
            **run.model_dump(mode="json", by_alias=True),
        }
        try:
            out = season_autopilot.append_run(
                self.data_dir, league, record, nba_today(self.clock())
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc
        self._attribute("lineup", league, run.trigger, {league: run.outcome})
        return out

    def set_lineup_mode(self, league: str, mode: str) -> dict[str, Any]:
        """The dashboard's mode switch (#170): the private league is refused, and ``live``
        until the dry run passes (``season_autopilot.live_check``)."""
        self._base(league)
        current = leagues.lineup_mode(self.data_dir, league)
        if current.get("private"):
            raise HTTPException(409, "the private league is never touched")
        if mode == "live":
            check = season_autopilot.live_check(self.data_dir, league, current)
            if not check["ok"]:
                raise HTTPException(409, check["reason"])
        leagues.set_lineups(self.data_dir, league, mode, by="dashboard")
        return self.autopilot(league)

    # ------------------------------------------------------------------ the moves executor
    def _modes(self, kind: str) -> dict[str, dict[str, Any]]:
        """Every league's mode of an executor (``leagues.LINEUPS``, ``leagues.MOVES``); a folder
        that does not read is left out."""
        out = {}
        for league in leagues.leagues(self.data_dir):
            try:
                out[league] = leagues.executor_mode(self.data_dir, league, kind)
            except leagues.LeagueError:
                continue
        return out

    def _read_queue(self, day: date) -> dict[str, Any] | None:
        try:
            return season_queue.read(self.data_dir, day)
        except season_queue.QueueError as exc:
            raise HTTPException(409, str(exc)) from exc

    def _queue_payload(self, day: date, body: dict[str, Any] | None) -> dict[str, Any]:
        out = {
            "date": day.isoformat(),
            "built": [],
            "execute_time": None,
            "leagues": [],
            "entries": [],
            **(body or {}),
            "settings": season_queue.settings(self.data_dir, day),
            "stop": season_autopilot.stopped(self.data_dir),
            "now": self.clock().isoformat(),
        }
        lines = {
            league: season_autopilot.day_lines(self.data_dir, league, day)
            for league in sorted({str(e["league"]) for e in out["entries"]})
        }
        latest = {
            k: v for x in lines.values() for k, v in season_autopilot.latest_passes(x).items()
        }
        il = {
            k: v
            for league in lines
            for k, v in season_autopilot.latest_il(
                season_autopilot.il_lines(self.data_dir, league, day)
            ).items()
        }
        dropped = {
            k: v
            for league in lines
            for k, v in season_autopilot.latest_drop(
                season_autopilot.drop_lines(self.data_dir, league, day)
            ).items()
        }
        passes = self._passes(day)
        by_id = {e["id"]: e for e in out["entries"]}
        return {
            **out,
            # The routine's pass while it runs, and the day's last one closed (#201).
            "active": season_passes.active(passes),
            "last_pass": season_passes.last_closed(passes),
            # The modes now (#205): a switch after the build shows on the next read.
            "leagues": [self._row_now(r) for r in out["leagues"]],
            # The day's pass results (#200), read from the leagues' logs: never stored on the queue.
            # A week plan's step (#221 part 2) with what it waits for, None for nothing.
            "entries": [
                {
                    **e,
                    "pass": latest.get(str(e["id"])),
                    "il_pass": il.get(str(e["id"])),
                    "drop_pass": dropped.get(str(e["id"])),
                    "waits": qa.waits(e, by_id),
                }
                for e in out["entries"]
            ],
            "passes": season_autopilot.pass_tally(lines),
            # Each league's latest Start Active run of the day (#215), read from its log.
            "start_active": {
                str(r["league"]): runs[-1]
                for r in out["leagues"]
                if (
                    runs := season_autopilot.start_active_lines(
                        self.data_dir, str(r["league"]), day
                    )
                )
            },
            "names": self._queue_names(out["entries"]),
        }

    def _queue_names(self, entries: Iterable[Mapping[str, Any]]) -> dict[str, str]:
        """Every player the day's entries mention (the add, the drop, the held move's player), by
        id (#194): each league's read from its own snapshot at request time; a league whose
        snapshot does not read names none, and the web says "player N"."""
        wanted: dict[str, set[int]] = {}
        for e in entries:
            held = e.get("held_move") or {}
            for k in (e.get("add"), e.get("drop"), held.get("player")):
                if k is not None:
                    wanted.setdefault(str(e["league"]), set()).add(int(k))
        out: dict[str, str] = {}
        for league, ids in wanted.items():
            try:
                base, _ = base_settings(self.data_dir, league)
                players = Season.from_parts(base, load_parts(self.data_dir, league)).players
            except Exception:  # noqa: BLE001, S112 - one league's snapshot leaves the others
                continue
            out |= {str(k): players[k].name for k in sorted(ids) if k in players}
        return out

    def queue(self, day: date | None = None) -> dict[str, Any]:
        """A day's queue of the moves executor (#171), today's by default; reads only."""
        day = day or nba_today(self.clock())
        return self._queue_payload(day, self._read_queue(day))

    def build_queue(self) -> dict[str, Any]:
        """Build today's queue (#171) from each armed league's last moves solve of the day in the
        decision log: never a solve. A rebuild keeps the entries struck or executed by id and
        gives an entry new to the queue its full window; a league the build cannot read keeps
        its entries as they were. Claims placed on earlier days are resolved from the leagues'
        transactions on the way."""
        now = self.clock()
        today = nba_today(now)
        execute_time = season_queue.settings(self.data_dir, today)["in_force"]
        modes = self._modes(leagues.MOVES)
        since = today - timedelta(days=season_queue.PENDING_DAYS)
        try:
            earlier = {
                d: q
                for d in season_queue.days(self.data_dir)
                if since <= d < today and (q := season_queue.read(self.data_dir, d)) is not None
            }
            old = season_queue.read(self.data_dir, today) or {}
        except season_queue.QueueError as exc:
            raise HTTPException(409, str(exc)) from exc
        rows: list[dict[str, Any]] = []
        reads: dict[str, tuple[Season, list[dict[str, Any]]]] = {}
        scoring: dict[str, str] = {}
        for league in leagues.leagues(self.data_dir):
            try:
                base, _ = base_settings(self.data_dir, league)
            except leagues.LeagueError:
                continue
            scoring[league] = base.scoring
            mode = modes.get(league)
            if mode is None:
                continue
            row = {"league": league, "scoring": base.scoring, "mode": mode["mode"]}
            if mode.get("private"):
                rows.append({**row, "status": season_queue.PRIVATE, "reason": qa.PRIVATE})
                continue
            if mode["mode"] == "off":
                rows.append({**row, "status": season_queue.OFF, "reason": qa.OFF})
                continue
            try:
                season = Season.from_parts(base, load_parts(self.data_dir, league))
                entries = season_decisions.load(season_dir(self.data_dir, league), today)
            except Exception as exc:  # noqa: BLE001 - one league's failure leaves the others
                rows.append({**row, "status": season_queue.FAILED, "reason": _failure(exc)})
                continue
            reads[league] = (season, entries)
        try:
            payloads, _ = self._all_scorecards(None)
        except Exception:  # noqa: BLE001 - without the scorecards the plan floor applies
            payloads = []
        differences = season_queue.scored_differences(payloads, scoring)
        gains: dict[str, list[float]] = {}
        for league, (_, entries) in reads.items():
            gains.setdefault(scoring[league], []).extend(season_queue.recent_gains(entries, today))
        resolved: dict[str, str] = {}
        builds: dict[str, list[dict[str, Any]]] = {}
        for league, (season, entries) in sorted(reads.items()):
            mode, kind = modes[league], scoring[league]
            row = {"league": league, "scoring": kind, "mode": mode["mode"]}
            claims = season_queue.pending(earlier.values(), league)
            settled = season_queue.resolutions(season, claims, today)
            resolved |= settled
            claims = [c for c in claims if c["id"] not in settled]
            entry = season_queue.day_entry(entries, today)
            if entry is None:
                reason = season_queue.NOT_SOLVED_REASON
                rows.append({**row, "status": season_queue.NOT_SOLVED, "reason": reason})
                continue
            system = (entry.get("system") or {}).get("key")
            try:
                built = self._built(league, system)
                _, flags, _ = self._flags(league)
            except Exception as exc:  # noqa: BLE001 - one league's failure leaves the others
                rows.append({**row, "status": season_queue.FAILED, "reason": _failure(exc)})
                continue
            knobs = entry.get("knobs") or {}
            plan = season_queue.plan_floor(knobs, kind)
            floor = qa.noise_floor(differences.get(kind, []), plan)
            typical = qa.typical_gain(gains.get(kind, []), plan)
            cap, cap_from = season_queue.daily_cap(mode, knobs)
            todays = [e for e in old.get("entries") or [] if e.get("league") == league]
            keep = [e for e in todays if qa.kept(e)]
            holding = [e for e in keep if qa.holds_place(e)]
            protected = season_queue.protected_of(built.rule)
            left = season_queue.adds_left(entry.get("adds"), [*claims, *holding])
            budget = season_queue.budget_of(season)
            day = qa.LeagueDay(
                league=league,
                scoring=kind,
                entry=entry,
                mode=mode["mode"],
                private=False,
                protected=protected,
                availability={
                    a.player.yahoo_id: (a.availability, a.clears) for a in season.available
                },
                flags={k: f.level for k, f in flags.items()},
                dropped=season_queue.dropped_recently(season, today),
                budget=budget,
                cap=cap,
                adds_left=left,
                uses_faab=season.settings.uses_faab,
                kept=frozenset(e["id"] for e in keep),
                done=len(holding),
            )
            builds[league] = qa.queue_of(day, today, floor, typical, knobs.get("faab_sizing"))
            rows.append(
                {
                    **row,
                    "status": season_queue.QUEUED,
                    "reason": None,
                    "decision": entry.get("id"),
                    "system": system,
                    "cap": cap,
                    "cap_from": cap_from,
                    "budget": budget,
                    "adds": entry.get("adds"),
                    "adds_left": [
                        {"start": s.isoformat(), "end": e.isoformat(), "adds": n}
                        for (s, e), n in left.items()
                    ],
                    "pending": [
                        {k: c.get(k) for k in ("id", "add", "drop", "from")} for c in claims
                    ],
                    "protected": {str(k): why for k, why in protected.items()},
                    "floor": floor.to_dict(),
                    "typical": {"value": typical[0], "from": typical[1]},
                    "queued": sum(1 for e in builds[league] if e["queued"]) + len(holding),
                    "built_at": now.isoformat(),
                }
            )

        def change(body: dict[str, Any] | None) -> dict[str, Any]:
            body = body or {}
            # Merged with the queue as read under the store's lock: a strike made while the
            # leagues were read is kept.
            out = []
            for e in body.get("entries") or []:
                if e.get("league") not in builds:
                    out.append(e)
            for league, new in builds.items():
                todays = [e for e in body.get("entries") or [] if e.get("league") == league]
                out += qa.merge(todays, new, today, execute_time, now)
            return {
                "date": today.isoformat(),
                "built": [*(body.get("built") or []), now.isoformat()],
                "execute_time": execute_time,
                "leagues": sorted(rows, key=lambda r: r["league"]),
                "entries": sorted(out, key=season_queue.sort_key),
            }

        try:
            for day, q in earlier.items():
                if {e["id"] for e in q.get("entries") or []} & set(resolved):
                    season_queue.update(self.data_dir, day, _resolver(resolved, now))
            body = season_queue.update(self.data_dir, today, change)
        except season_queue.QueueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return self._queue_payload(today, body)

    def strike(self, entry_id: str, bid_only: bool, undo: bool) -> dict[str, Any]:
        """The user's veto on a queue entry (#171): strike it, or its bid alone (a $0 claim), or
        undo either; refused once it executed, and an undone strike refused while the league's
        cap is full."""
        day = season_queue.day_of(entry_id)
        if day is None:
            raise HTTPException(404, f"no queue entry {entry_id}")
        now = self.clock()

        def change(body: dict[str, Any] | None) -> dict[str, Any]:
            entries = (body or {}).get("entries") or []
            e = next((x for x in entries if x.get("id") == entry_id), None)
            if body is None or e is None:
                raise HTTPException(404, f"no queue entry {entry_id}")
            if e.get("outcome"):
                raise HTTPException(409, "executed already: a strike comes before the pass")
            if not e.get("queued"):
                raise HTTPException(409, "not queued: there is nothing to strike")
            if bid_only:
                e["bid_struck"] = not undo
            else:
                if undo and e.get("struck"):
                    row = next(
                        (r for r in body.get("leagues") or [] if r["league"] == e["league"]), {}
                    )
                    holding = sum(
                        1
                        for x in entries
                        if x["league"] == e["league"] and x["id"] != entry_id and qa.holds_place(x)
                    )
                    if row.get("cap") is not None and holding >= row["cap"]:
                        raise HTTPException(
                            409, "the day's cap is full: strike another entry first"
                        )
                e["struck"] = not undo
            e["struck_at"] = now.isoformat()
            e["struck_by"] = "dashboard"
            return body

        try:
            body = season_queue.update(self.data_dir, day, change)
        except season_queue.QueueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return self._queue_payload(day, body)

    def set_execute_time(self, body: QueueSettings) -> dict[str, Any]:
        """The execute times, the dashboard's own click (#171): the day's and Sunday's (#209),
        each when sent; today's entries not executed are timed again by the one in force today,
        never sooner than a full window after they were queued."""
        sent = body.model_fields_set
        if body.execute_time is None and "sunday_execute_time" not in sent:
            raise HTTPException(422, "send an execute time, Sunday's, or both")
        try:
            if body.execute_time is not None:
                season_queue.set_execute_time(self.data_dir, body.execute_time, by="dashboard")
            if "sunday_execute_time" in sent:
                season_queue.set_sunday_execute_time(
                    self.data_dir, body.sunday_execute_time, by="dashboard"
                )
        except season_queue.QueueError as exc:
            raise HTTPException(422, str(exc)) from exc
        today = nba_today(self.clock())
        value = season_queue.settings(self.data_dir, today)["in_force"]
        if self._read_queue(today) is not None:

            def change(body: dict[str, Any] | None) -> dict[str, Any]:
                body = body or {}
                entries = qa.retime(body.get("entries") or [], today, value)
                return {**body, "execute_time": value, "entries": entries}

            season_queue.update(self.data_dir, today, change)
        return self.queue(today)

    def moves_view(self, league: str) -> dict[str, Any]:
        """The league's Queue card (#171): the mode, STOP, the live check, the passes, and its
        row and entries of today's queue."""
        self._base(league)
        today = nba_today(self.clock())
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        try:
            body = season_queue.read(self.data_dir, today) or {}
        except season_queue.QueueError:
            body = {}
        mine = [e for e in body.get("entries") or [] if e.get("league") == league]
        # A week plan's step with what it waits for (#221 part 2), as the Queue route reads it.
        by_id = {e["id"]: e for e in mine}
        entries = [{**e, "waits": qa.waits(e, by_id)} for e in mine]
        row = next((r for r in body.get("leagues") or [] if r["league"] == league), None)
        return {
            **season_autopilot.moves_view(self.data_dir, league, mode, today, entries),
            "row": self._row_now(row) if row else None,
            "settings": season_queue.settings(self.data_dir, today),
        }

    def moves_due(self, league: str, day: date | None) -> dict[str, Any]:
        """The entries of the league due now (#171), for the extension's execute pass: queued,
        not struck, not executed, their window over, each with the bid to place and its add page;
        with my team, the players protected and why (the stored keep rule's and the engine's now:
        the page check refuses a protected drop whatever the queue says), the claims still open
        (earlier days' placed and unresolved, and today's placed), the day's cap and how many of
        today's entries took their place, the adds left as read less every claim since, and the
        budget. None when the mode is off, STOP is on or the day is not today. Every answer
        carries ``live``, the live guard now (``season_autopilot.moves_live_check``): a pass
        places its claims only in a live league where it holds (#171 PR 3)."""
        base, _ = self._base(league)
        now = self.clock()
        today = nba_today(now)
        day = day or today
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        stop = season_autopilot.stopped(self.data_dir)
        out: dict[str, Any] = {
            "league": league,
            "date": day.isoformat(),
            "mode": mode["mode"],
            "stop": stop,
            "reason": None,
            "team": base.my_team_id,
            "entries": [],
            "next": None,
            "protected": {},
            "pending": [],
            "cap": None,
            "done": 0,
            "adds_left": [],
            "budget": None,
            "il_first": [],
            "drop_first": [],
            "held": [],
            "live": season_autopilot.moves_live_check(self.data_dir, league, mode),
            "at": now.isoformat(),
        }

        def closed(reason: str) -> dict[str, Any]:
            return {**out, "reason": reason}

        if mode.get("private"):
            return closed(qa.PRIVATE)
        if mode["mode"] == "off":
            return closed(qa.OFF)
        if stop:
            return closed("STOP is on (data/autopilot/STOP)")
        if day != today:
            return closed("only today's queue executes")
        body = self._read_queue(day)
        if body is None:
            return closed("no queue today: the build runs at the end of the morning routine")
        row = next((r for r in body.get("leagues") or [] if r["league"] == league), None)
        if row is None or row.get("status") != season_queue.QUEUED:
            return closed((row or {}).get("reason") or "the league is not in the day's queue")
        protected = dict(row.get("protected") or {})
        try:
            rule = self._built(league, row.get("system")).rule
            protected |= {str(k): why for k, why in season_queue.protected_of(rule).items()}
        except Exception:  # noqa: BLE001, S110 - the build's keep rule still holds
            pass
        mine = [e for e in body.get("entries") or [] if e.get("league") == league]
        # A churn is due on its add page only once its held drop landed, and its claim then goes
        # in with no drop (#221 part 3).
        due = [
            {
                **e,
                "bid_placed": qa.effective_bid(e),
                "page": qa.add_page(league, e["add"]),
                **({"drop": None} if qa.churn_drop(e) is not None else {}),
            }
            for e in qa.due(mine, now)
        ]
        done = [e for e in mine if e.get("outcome") in qa.EXECUTED]
        earlier = [p for p in row.get("pending") or [] if isinstance(p, Mapping)]
        placed = [e for e in done if e.get("outcome") in qa.PLACED]
        left = season_queue.adds_left(row.get("adds"), [*earlier, *done])
        later = sorted(
            at
            for e in mine
            if e.get("queued")
            and not e.get("struck")
            and not e.get("outcome")
            and e.get("executes_at")
            and (at := datetime.fromisoformat(e["executes_at"])) > now
        )
        pending = [
            {k: c.get(k) for k in ("id", "add", "drop", "from")} for c in [*earlier, *placed]
        ]
        adds_left = (
            [
                {"start": s.isoformat(), "end": e.isoformat(), "adds": n}
                for (s, e), n in left.items()
            ]
            if row.get("adds")
            else row.get("adds_left") or []
        )
        blocked = row.get("cap") is not None and len(done) >= row["cap"]
        held = qa.held(mine, now)
        return {
            **out,
            "reason": None if due else (held[0]["waits"]["text"] if held else "nothing due now"),
            "entries": due,
            # A week plan's steps whose window is over, held on an earlier step (#221 part 2).
            "held": held,
            "next": later[0].isoformat() if later else None,
            "protected": protected,
            "pending": pending,
            "cap": row.get("cap"),
            "done": len(done),
            "adds_left": adds_left,
            "budget": row.get("budget"),
            "il_first": []
            if blocked
            else self._il_first(league, base, mine, due, pending, adds_left),
            "drop_first": []
            if blocked
            else self._drop_first(league, base, mine, now, pending, adds_left, protected),
        }

    def _drop_first(
        self,
        league: str,
        base: Any,
        mine: list[dict[str, Any]],
        now: datetime,
        pending: list[dict[str, Any]],
        adds_left: list[dict[str, Any]],
        protected: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """The held drops the due churns need first (#221 part 3), for the routine to open the
        drop page before anything else of the league: each churn whose window is over, queued,
        not struck, its drop not on record today, its earlier plan steps landed, whose claim
        nothing else stops (no claim on the add open, an add left in its week) and whose H the
        keep rule does not protect; each H once, in the queue's order. After a logged drop the
        extension reads the due answer again and goes on to the IL move or the add page."""
        if base.my_team_id is None:
            return []
        by_id = {e["id"]: e for e in mine}
        claimed = {c.get("add") for c in pending}
        out: list[dict[str, Any]] = []
        for e in mine:
            h = qa.churn_drop(e)
            if h is None or not e.get("queued") or e.get("struck") or e.get("outcome"):
                continue
            if not e.get("executes_at") or datetime.fromisoformat(e["executes_at"]) > now:
                continue
            if qa.drop_outcome(e) is not None or str(h) in protected:
                continue
            if any(not qa.landed(by_id.get(k) or {}) for k in e.get("after") or ()):
                continue
            if e.get("add") in claimed or any(x["player"] == h for x in out):
                continue
            week = next(
                (w for w in adds_left if e.get("from") and w["start"] <= e["from"] <= w["end"]),
                None,
            )
            if week is not None and week.get("adds") is not None and week["adds"] < 1:
                continue
            out.append(
                {
                    "entry": e["id"],
                    "player": h,
                    "slot": (e.get("held_drop") or {}).get("slot"),
                    "add": e["add"],
                    "page": public.drop_url(league, base.my_team_id),
                }
            )
        return out

    def _il_first(
        self,
        league: str,
        base: Any,
        mine: list[dict[str, Any]],
        due: list[dict[str, Any]],
        pending: list[dict[str, Any]],
        adds_left: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """The IL moves the due open-spot claims need first (#214), for the routine to open the
        team page before the league's add pages: each due entry whose basis is ``held`` and whose
        claim nothing else stops (no claim on the add open, an add left in its week), its held
        player once, in the queue's order, unless he was moved to the IL today or the entry's
        move failed today. ``date`` is the first day he can still be moved: today, or tomorrow
        once his team's game has tipped off (null tip: today's page says)."""
        moved = {
            (e.get("held_move") or {}).get("player")
            for e in mine
            if (e.get("il") or {}).get("outcome") == "moved"
        }
        claimed = {c.get("add") for c in pending}
        out: list[dict[str, Any]] = []
        for e in due:
            held = e.get("held_move") or {}
            player, slot = held.get("player"), held.get("slot")
            # A churn is due only once its held drop landed, its drop then None (#221 part 3).
            if e.get("basis") not in ("held", qa.CHURN) or e.get("drop") is not None:
                continue
            if player is None or slot not in season_autopilot.IL_SLOTS:
                continue
            if player in moved or (e.get("il") or {}).get("outcome") in season_autopilot.IL_STICKS:
                continue
            if e.get("add") in claimed or any(x["player"] == player for x in out):
                continue
            week = next(
                (w for w in adds_left if e.get("from") and w["start"] <= e["from"] <= w["end"]),
                None,
            )
            if week is not None and week.get("adds") is not None and week["adds"] < 1:
                continue
            out.append({"entry": e["id"], "player": player, "slot": slot})
        if not out:
            return out
        now = self.clock()
        today = nba_today(now)
        tips = nba_schedule.load_tips(today, self.data_dir / SCHEDULE_DIR) or {}
        try:
            players = Season.from_parts(base, load_parts(self.data_dir, league)).players
        except Exception:  # noqa: BLE001 - no team read: today's page says whether he is locked
            players = {}
        for x in out:
            team = players[x["player"]].nba_team if x["player"] in players else None
            tip = season_autopilot.tip_at(tips, team)
            day = today + timedelta(days=1) if tip is not None and tip <= now else today
            x |= {
                "date": day.isoformat(),
                "tip": tip.isoformat() if tip is not None else None,
                "page": public.team_url(league, base.my_team_id, day)
                if base.my_team_id is not None
                else None,
            }
        return out

    def log_moves_run(self, league: str, run: season_autopilot.MovesRun) -> dict[str, Any]:
        """Append an execute pass to the league's log under ``moves`` (#171) and, for a live pass,
        set its placed, failed and gone outcomes on the queue's entries: a dry run moves none (the
        ruling on #171) and a live skip none (#171 PR 3), so the late pass reads those entries
        again; refused (409) when the mode, STOP, the live guard, the queue or the pass's own
        outcome says it should not have run."""
        self._base(league)
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        body = self._read_queue(run.day) or {}
        mine = {e["id"]: e for e in body.get("entries") or [] if e.get("league") == league}
        live = (
            season_autopilot.moves_live_check(self.data_dir, league, mode)
            if run.mode == "live"
            else None
        )
        why = season_autopilot.check_moves_run(
            run, mode, season_autopilot.stopped(self.data_dir), mine, live
        )
        if why is not None:
            raise HTTPException(409, why)
        now = self.clock()
        record = {"at": now.isoformat(timespec="seconds"), **run.model_dump(mode="json")}
        try:
            season_autopilot.append_run(
                self.data_dir, league, record, nba_today(now), season_autopilot.MOVES
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc
        # The page's can't-cut ids, for the next solve (#220): the newest read wins.
        season_cantcut.record(self.data_dir, league, record.get("entries") or [])
        checks = {c.id: c for c in run.entries if c.outcome in season_autopilot.STICKS}
        if checks and run.mode == "live":

            def change(q: dict[str, Any] | None) -> dict[str, Any]:
                q = q or {}
                for e in q.get("entries") or []:
                    c = checks.get(e.get("id"))
                    if c is not None and e.get("league") == league:
                        e.update(
                            outcome=c.outcome,
                            outcome_reason=c.reason,
                            outcome_at=now.isoformat(),
                            bid_placed=c.bid,
                        )
                return q

            season_queue.update(self.data_dir, run.day, change)
        self._attribute("moves", league, run.trigger, {c.id: c.outcome for c in run.entries})
        return record

    def log_il_run(self, league: str, run: season_autopilot.ILRun) -> dict[str, Any]:
        """Log an IL move the extension made (or would make) on the team page for an open-spot
        claim (#214), under ``il`` in the league's day file. A live ``moved`` or ``failed`` goes
        on the queue's entry as its ``il`` (never its outcome or place): the player is not moved
        again that day, and a failed move is never retried that day. Refused (409) when the mode,
        STOP, the live guard or the queue says it should not have run, or names another move than
        the entry's ``held_move``. The run goes to the open moves pass, apart from its claims."""
        self._base(league)
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        body = self._read_queue(run.day) or {}
        mine = {e["id"]: e for e in body.get("entries") or [] if e.get("league") == league}
        live = (
            season_autopilot.moves_live_check(self.data_dir, league, mode)
            if run.mode == "live"
            else None
        )
        why = season_autopilot.check_il_run(
            run, mode, season_autopilot.stopped(self.data_dir), mine, live
        )
        if why is not None:
            raise HTTPException(409, why)
        now = self.clock()
        record = {"at": now.isoformat(timespec="seconds"), **run.model_dump(mode="json")}
        try:
            season_autopilot.append_run(
                self.data_dir, league, record, nba_today(now), season_autopilot.IL
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc
        if run.mode == "live" and run.outcome in season_autopilot.IL_STICKS:

            def change(q: dict[str, Any] | None) -> dict[str, Any]:
                q = q or {}
                for e in q.get("entries") or []:
                    if e.get("id") == run.entry and e.get("league") == league:
                        e["il"] = {
                            "outcome": run.outcome,
                            "at": now.isoformat(),
                            "reason": run.reason,
                            "message": run.message,
                        }
                return q

            season_queue.update(self.data_dir, run.day, change)
        if run.entry is not None:
            self._attribute("moves", league, run.trigger, {run.entry: run.outcome}, key="il")
        return record

    def log_drop_run(self, league: str, run: season_autopilot.DropRun) -> dict[str, Any]:
        """Log a churn's held drop the extension made (or would make) on the drop page (#221 part
        3), under ``drop`` in the league's day file. A live ``dropped``, ``failed`` or
        ``unconfirmed`` goes on the queue's entry as its ``drop_run`` (never its outcome or
        place): H is not dropped again that day, and the churn's add goes on only after
        ``dropped``. Refused (409) when the mode, STOP, the live guard, the keep rule or the queue
        says it should not have run, or names another drop than the churn's. The run goes to the
        open moves pass, apart from its claims."""
        self._base(league)
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        body = self._read_queue(run.day) or {}
        mine = {e["id"]: e for e in body.get("entries") or [] if e.get("league") == league}
        row = next((r for r in body.get("leagues") or [] if r.get("league") == league), None)
        protected = {int(k) for k in ((row or {}).get("protected") or {})}
        try:
            built = self._built(league, (row or {}).get("system"))
            protected |= {int(k) for k in season_queue.protected_of(built.rule)}
        except Exception:  # noqa: BLE001, S110 - the build's keep rule still holds
            pass
        live = (
            season_autopilot.moves_live_check(self.data_dir, league, mode)
            if run.mode == "live"
            else None
        )
        why = season_autopilot.check_drop_run(
            run, mode, season_autopilot.stopped(self.data_dir), mine, live, protected
        )
        if why is not None:
            raise HTTPException(409, why)
        now = self.clock()
        record = {"at": now.isoformat(timespec="seconds"), **run.model_dump(mode="json")}
        try:
            season_autopilot.append_run(
                self.data_dir, league, record, nba_today(now), season_autopilot.DROP
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc
        if run.mode == "live" and run.outcome in season_autopilot.DROP_STICKS:

            def change(q: dict[str, Any] | None) -> dict[str, Any]:
                q = q or {}
                for e in q.get("entries") or []:
                    if e.get("id") == run.entry and e.get("league") == league:
                        e["drop_run"] = {
                            "outcome": run.outcome,
                            "at": now.isoformat(),
                            "reason": run.reason,
                            "message": run.message,
                        }
                return q

            season_queue.update(self.data_dir, run.day, change)
        if run.entry is not None:
            self._attribute("moves", league, run.trigger, {run.entry: run.outcome}, key="drop")
        return record

    # ------------------------------------------------------------------ Start Active (#215)
    def _my_roster(self, league: str) -> tuple[Any, Season | None, dict[str, list[int]] | None]:
        """The league's base, season and my roster as the need rule keeps it; the season and
        roster None when the snapshot does not read or has no team of mine."""
        base, _ = self._base(league)
        try:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
        except Exception:  # noqa: BLE001 - no read: the need rule goes on the runs alone
            return base, None, None
        spots = season.rosters.get(base.my_team_id) if base.my_team_id is not None else None
        return base, season, season_autopilot.roster_record(spots) if spots else None

    def start_active_due(self) -> dict[str, Any]:
        """The armed public leagues and whether each wants Yahoo's Start Active Players for the
        rest of the week (#215): ``season_autopilot.start_active_need`` on the moves mode, the
        week's first day from the league's calendar (else the Monday) and my roster as last read,
        with the team page of today to open and the live guard. On a Monday every armed league's
        last run is last week's, so it says ``week_start`` before any run of the week. Under STOP
        none needs a run. Nothing here opens a page."""
        now = self.clock()
        today = nba_today(now)
        stop = season_autopilot.stopped(self.data_dir)
        rows = []
        for league, mode in self._modes(leagues.MOVES).items():
            if mode.get("private") or mode["mode"] == "off":
                continue
            row: dict[str, Any] = {"league": league, "mode": mode["mode"]}
            try:
                base, season, roster = self._my_roster(league)
            except HTTPException as exc:
                rows.append({**row, "need": False, "reasons": [], "error": str(exc.detail)})
                continue
            week = season.calendar.week_of(today) if season and season.calendar else None
            start = week.start if week is not None else today - timedelta(days=today.weekday())
            need = season_autopilot.start_active_need(self.data_dir, league, mode, start, roster)
            if stop:
                need = {**need, "need": False}
            team = base.my_team_id
            rows.append(
                {
                    **row,
                    **need,
                    "team": team,
                    "week": {"start": start.isoformat(), "end": week.end.isoformat()}
                    if week is not None
                    else {"start": start.isoformat(), "end": None},
                    "roster": roster,
                    "page": public.team_url(league, team, today) if team is not None else None,
                    "live": season_autopilot.moves_live_check(self.data_dir, league, mode),
                }
            )
        return {
            "date": today.isoformat(),
            "stop": stop,
            "reason": "STOP is on (data/autopilot/STOP)" if stop else None,
            "leagues": rows,
            "at": now.isoformat(),
        }

    def log_start_active_run(
        self, league: str, run: season_autopilot.StartActiveRun
    ) -> dict[str, Any]:
        """Log a Start Active run the extension made (or would make) on the team page (#215),
        under ``start_active`` in the league's day file, with the roster it ran on: the page's
        when the run carries it, else my roster as last read. Refused (409) when the mode, STOP or
        the live guard says it should not have run. A routine's moves-pass run goes to the open moves
        pass, by league."""
        _, _, roster = self._my_roster(league)
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        live = (
            season_autopilot.moves_live_check(self.data_dir, league, mode)
            if run.mode == "live"
            else None
        )
        why = season_autopilot.check_start_active_run(
            run, mode, season_autopilot.stopped(self.data_dir), live
        )
        if why is not None:
            raise HTTPException(409, why)
        now = self.clock()
        record = {
            "at": now.isoformat(timespec="seconds"),
            **run.model_dump(mode="json"),
            "roster": run.roster if run.roster is not None else roster,
        }
        try:
            season_autopilot.append_run(
                self.data_dir, league, record, nba_today(now), season_autopilot.START_ACTIVE
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc
        # The 05:00 daily opens no moves pass: its runs are logged and go to none. Nor does a
        # press that follows a lineup run or an add (#289): it is that run's, not the pass's.
        if run.trigger not in ("routine_daily", "after_lineup", "after_add"):
            self._attribute("moves", league, run.trigger, {league: run.outcome}, key="start_active")
        return record

    # ------------------------------------------------------------------ the pass record (#201)
    def _attribute(
        self,
        kind: str,
        league: str,
        trigger: str,
        outcomes: Mapping[str, str],
        key: str = "outcomes",
    ) -> None:
        """Give a post the log took to the open pass of its kind (#201); a panel's never. The
        record changes nothing in what the post logged or answers: a record that does not take
        it is logged here and left. ``key`` ``il`` is an IL run's (#214)."""
        if trigger == "panel":
            return
        now = self.clock()
        try:
            season_passes.attribute(
                self.data_dir, nba_today(now), now, kind, league, outcomes, key=key
            )
        except Exception:  # the record never fails the log's post
            LOG.warning("the pass record did not take %s's %s post", league, kind, exc_info=True)

    def open_pass(self, body: PassOpen) -> dict[str, Any]:
        """Open a routine's pass (#201): the leagues it will open, in order, and the entries a
        moves pass will check; the private league is refused, as everywhere."""
        if body.kind == "lineup" and body.trigger == "routine_evening":
            raise HTTPException(409, EVENING_MOVES_ONLY)
        for league in body.leagues:
            _, is_public = self._base(league)
            if not is_public:
                raise HTTPException(409, qa.PRIVATE)
        now = self.clock()
        try:
            p = season_passes.open_pass(
                self.data_dir,
                nba_today(now),
                now,
                body.kind,
                body.trigger,
                body.leagues,
                body.entries,
            )
        except season_passes.PassError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return season_passes.view(p)

    def pass_opening(self, pass_id: str, body: PassOpening) -> dict[str, Any]:
        """The league (and entry) the routine opens now."""
        try:
            p = season_passes.opening(self.data_dir, pass_id, self.clock(), body.league, body.entry)
        except season_passes.PassError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return season_passes.view(p)

    def pass_done(self, pass_id: str, body: PassDone) -> dict[str, Any]:
        """The routine's end of its pass, with the week plan's steps of its leagues it leaves
        held on an earlier step (#221 part 2), read from the day's queue."""
        now = self.clock()
        try:
            held = self._held_of(pass_id, now)
            p = season_passes.done(self.data_dir, pass_id, now, body.summary, held)
        except season_passes.PassError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return season_passes.view(p)

    def _held_of(self, pass_id: str, now: datetime) -> dict[str, dict[str, Any]]:
        """The day's queued entries of the pass's leagues (those it named, if any) that
        ``autopilot.held`` holds now, by id; none when the queue does not read."""
        day = season_passes.day_of(pass_id)
        p = next((x for x in self._passes(day) if x["id"] == pass_id), None)
        if p is None or p["kind"] != "moves":
            return {}
        try:
            body = season_queue.read(self.data_dir, day)
        except season_queue.QueueError:
            LOG.warning("the queue of %s does not read: the pass records no holds", day)
            return {}
        if body is None:
            return {}
        named = p.get("entries")
        mine = [e for e in body.get("entries") or [] if str(e.get("league")) in p["leagues"]]
        return {
            h["id"]: {"add": h["add"], **h["waits"]}
            for h in qa.held(mine, now)
            if named is None or h["id"] in named
        }

    def _passes(self, day: date) -> list[dict[str, Any]]:
        """The day's passes as they read now; none when the record does not read (the queue
        still answers)."""
        try:
            return season_passes.read(self.data_dir, day, self.clock())
        except season_passes.PassError:
            LOG.warning("the pass record of %s does not read", day, exc_info=True)
            return []

    def set_moves_mode(self, league: str, mode: str, cap: int | None) -> dict[str, Any]:
        """The Queue card's mode switch and cap, the user's own click (#171): the private league
        is refused, and ``live`` until the dry run passes
        (``season_autopilot.moves_live_check``)."""
        self._base(league)
        current = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        if current.get("private"):
            raise HTTPException(409, qa.PRIVATE)
        if mode == "live":
            check = season_autopilot.moves_live_check(self.data_dir, league, current)
            if not check["ok"]:
                raise HTTPException(409, check["reason"])
        leagues.set_executor(self.data_dir, league, leagues.MOVES, mode, by="dashboard", cap=cap)
        return self.moves_view(league)

    def set_all_moves_modes(self, mode: str) -> dict[str, Any]:
        """The Queue screen's one switch (#205), the user's own click: ``mode`` for every public
        league of the queue build's set, the points leagues the landing hides among them, under
        the single switch's rules. ``live`` is checked per league (``moves_live_check``, STOP
        included) and a league it refuses keeps its mode; a league already in the mode is left
        as it is; each keeps the user's own cap. The private league's file and the lineup
        executor's keys are never written."""
        out: list[dict[str, Any]] = []
        for league in leagues.leagues(self.data_dir):
            try:
                base_settings(self.data_dir, league)
                current = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
            except leagues.LeagueError:
                continue
            if current.get("private"):
                continue
            row = {"league": league, "mode": current["mode"], "ok": True, "reason": None}
            if current["mode"] != mode and mode == "live":
                check = season_autopilot.moves_live_check(self.data_dir, league, current)
                if not check["ok"]:
                    row |= {"ok": False, "reason": check["reason"]}
            if current["mode"] != mode and row["ok"]:
                try:
                    done = leagues.set_executor(
                        self.data_dir, league, leagues.MOVES, mode, EVERY_LEAGUE, current["cap"]
                    )
                    row["mode"] = done["mode"]
                except (OSError, leagues.LeagueError) as exc:
                    row |= {"ok": False, "reason": _failure(exc)}
            out.append(row)
        return {"mode": mode, "leagues": out}

    def _row_now(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """A league's row of the day's queue with what has moved since the build (#205): the
        moves executor's mode and the user's own cap now, and the live guard now; a row the build
        left off whose league was switched on since says so. The private row is as built."""
        if row.get("status") == season_queue.PRIVATE:
            return dict(row)
        try:
            mode = leagues.executor_mode(self.data_dir, str(row["league"]), leagues.MOVES)
        except leagues.LeagueError:
            return dict(row)
        live = season_autopilot.moves_live_check(self.data_dir, str(row["league"]), mode)
        out = {**row, "mode": mode["mode"], "user_cap": mode["cap"], "live": live}
        if row.get("status") == season_queue.OFF and mode["mode"] != "off":
            out["reason"] = qa.SWITCHED_ON
        return out

    def lineup(self, league: str, system: str | None, week: int | None) -> dict[str, Any]:
        """The Lineup view (#107): my recommended starters for each day of ``week`` (this one
        by default) against Yahoo's lineup as read."""
        system = self._system(league, system)
        built = self._built(league, system)
        base, is_public = self._base(league)
        today = nba_today(self.clock())
        key = (league, system, "lineup", week, today, self._moves_stamp(league))

        def make() -> dict[str, Any] | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_lineup.payload(built, season, today, week, is_public)

        out = self.moves_cache.get(key, make)
        if out is None:
            raise HTTPException(404, f"week {week} of league {league} has no lineup to show")
        return {"league": league, **out}

    def move_detail(
        self, league: str, add: int, drop: int | None, system: str | None
    ) -> dict[str, Any]:
        out = season_moves.detail_payload(self._built(league, system), add, drop)
        if out is None:
            raise HTTPException(404, f"no move adds {add} for {drop or 'nobody'} in {league}")
        return out

    # ------------------------------------------------------------------ trades
    def _trade_league(self, league: str, system: str | None) -> season_trades.TradeLeague:
        base, _ = self._base(league)
        system = self._system(league, system)
        today = nba_today(self.clock())
        key = (league, system, "trade", today, self._moves_stamp(league))

        def make() -> season_trades.TradeLeague | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            blend = season_knobs.for_league(self.data_dir, league)["blend"]
            return season_trades.build(season, today, self.data_dir, system, blend)

        built = self.moves_cache.get(key, make)
        if built is None:
            raise HTTPException(409, f"league {league} has no season of my team to trade in yet")
        return built

    def trade(self, league: str, body: TradeBody) -> dict[str, Any]:
        system = self._system(league, body.system)
        built = self._trade_league(league, system)
        # The moves' problem and scorer, for the rest of the season (#151); a trade is valued
        # on its horizons without them.
        try:
            moves = self._built(league, system)
        except HTTPException:
            moves = None
        try:
            return season_trades.evaluate(
                built,
                body.team,
                body.give,
                body.get,
                body.effective,
                nba_today(self.clock()),
                moves,
            )
        except season_trades.Refused as exc:
            raise HTTPException(exc.status, exc.detail) from exc

    # ------------------------------------------------------------------ the weekly recorder
    def _reference_league(self) -> str | None:
        """A public league whose players pages give the season's lines (NBA statistics, the same
        in every league) for a private one."""
        for league in leagues.leagues(self.data_dir):
            try:
                _, is_public = base_settings(self.data_dir, league)
            except leagues.LeagueError:
                continue
            if is_public:
                return league
        return None

    def record(self, league: str, number: int | None) -> dict[str, Any]:
        """Record a finished week of ``league`` (#97): read it, and write its record when it is
        new or its content changed."""
        base, is_public = self._base(league)
        now = self.clock()
        today = nba_today(now)
        with self.lock(f"record/{league}"):
            parts = load_parts(self.data_dir, league)
            season = Season.from_parts(base, parts)
            calendar = season.calendar or self._cached_calendar()
            if calendar is None:
                raise HTTPException(409, f"league {league} has no week calendar yet: refresh it")
            try:
                week = season_record.week_to_record(calendar.weeks, today, number)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            # The weeks ahead whose pairs the Season view lacks: a public league's refresh reads
            # them; a private league's are for the user's Chrome to open with the record's pages.
            ahead = (
                []
                if is_public
                else [
                    public.pairings_url(league, w) for w in season.weeks_unpaired(today, calendar)
                ]
            )
            # The private league's lineup pages (#107): its settings page until read, my team
            # page shown for each day of this week from today, and for each day of the week
            # recorded not read after it (#149).
            lineup_pages = [] if is_public else _lineup_pages(season, calendar, today, week)
            # And its transactions page until read today, for the decision log's match (#125).
            read = season.fetched.get("transactions")
            moves_page = (
                public.transactions_url(league)
                if not is_public and (read is None or nba_today(read[0]) < today)
                else None
            )
            fetch = self.fetch_factory()
            try:
                if is_public:
                    draft = parts.get(season_record.DRAFT)
                    inputs = season_record.public_inputs(
                        league, week, fetch, now, draft.data["picks"] if draft else None
                    )
                    if inputs.picks_read:
                        self._save_part(
                            league, Part(season_record.DRAFT, now, PUBLIC, {"picks": inputs.picks})
                        )
                    source, owners, owners_at = league, None, None
                else:
                    inputs = season_record.private_inputs(league, week, parts, season.settings)
                    source = self._reference_league()
                    owners = {
                        sp.player.yahoo_id: team
                        for team, spots in season.rosters.items()
                        for sp in spots
                    }
                    times = [at for k, (at, _) in season.fetched.items() if k.startswith("roster/")]
                    owners_at = min(times) if times else None
                lines = lines_at = None
                count: dict[str, int] = {}
                if inputs.picks is not None and source is not None:
                    wanted = {
                        int(p["player"]["yahoo_id"]): p["player"]["name"] for p in inputs.picks
                    }
                    lines, count = season_record.read_lines(
                        source, wanted, fetch, season_record.season_year(week)
                    )
                    lines_at = self.clock()
            except season_record.NeedsPages as exc:
                raise HTTPException(
                    409,
                    {
                        "message": f"league {league} is private: open these pages in Chrome "
                        "with the extension, then record again",
                        "week": week.number,
                        "needs": exc.urls,
                        "ahead": ahead,
                        "lineup_pages": lineup_pages,
                        "transactions_page": moves_page,
                    },
                ) from exc
            except public.RateLimited as exc:
                raise HTTPException(503, str(exc), headers=retry_after(exc.retry_after)) from exc
            except (public.FetchError, pages.PageError) as exc:
                raise HTTPException(502, str(exc)) from exc
            folder = season_dir(self.data_dir, league)
            read_pages = season_record.transaction_pages(
                folder / SNAPSHOTS, week, parts.get("transactions")
            )
            box = season_scorecard.BoxScores.at(self.data_dir, today)
            lineup = season_lineup.week_lost(season, week, box)
            self._save_ids(box)
            new = season_record.assemble(
                league,
                week,
                season.settings,
                inputs,
                lines,
                lines_at,
                source if lines is not None else None,
                owners,
                owners_at,
                season_rec.week_transactions(read_pages, week),
                lineup,
            )
            out, status = season_rec.settle(
                season_record.load_record(folder, week.number), new, self.clock()
            )
            if out is not None:
                season_record.write_record(folder, out)
            written = out or season_record.load_record(folder, week.number) or new
        return {
            "league": league,
            "week": week.number,
            "status": status,
            "pages": count,
            "missing": written.get("missing") or {},
            "summary": season_rec.summary(written, season.settings.my_team_id),
            "ahead": ahead,
            "lineup_pages": lineup_pages,
            "transactions_page": moves_page,
        }

    def _save_part(self, league: str, part: Part) -> None:
        with self.lock(league):
            parts = merge_part(load_parts(self.data_dir, league), part)
            save(self.data_dir, league, parts, [part], part.source, self.clock())

    def weeks(self, league: str) -> dict[str, Any]:
        base, _ = self._base(league)
        mine = Season.from_parts(base, load_parts(self.data_dir, league)).settings.my_team_id
        rows = season_record.records(season_dir(self.data_dir, league))
        return {
            "league": league,
            "my_team_id": mine,
            "weeks": [season_rec.summary(r, mine) for r in rows],
        }

    def week(self, league: str, number: int) -> dict[str, Any]:
        self._base(league)
        out = season_record.load_record(season_dir(self.data_dir, league), number)
        if out is None:
            raise HTTPException(404, f"week {number} of league {league} is not recorded")
        return out

    # ------------------------------------------------------------------ the scorecard (#126)
    def scorecard(
        self,
        league: str,
        week: int | None = None,
        system: str | None = None,
        box: season_scorecard.BoxScores | None = None,
    ) -> dict[str, Any]:
        """A league's recorded weeks against the decision log (#126): ``week`` (the last
        recorded by default) and every week to it, its moves realized from the cached box
        scores, the season to date and the calibration; on ``system``, by default each week on
        the one in force when it began (#152, ``season.scorecard.projection``)."""
        base, is_public = self._base(league)
        season = Season.from_parts(base, load_parts(self.data_dir, league))
        folder = season_dir(self.data_dir, league)
        own = box is None
        box = box or season_scorecard.BoxScores.at(self.data_dir, nba_today(self.clock()))
        out = season_scorecard.league_payload(
            league,
            season,
            is_public,
            season_record.records(folder),
            season_decisions.load(folder),
            system,
            week,
            box,
        )
        if own:
            self._save_ids(box)
        return out

    def _save_ids(self, box: season_scorecard.BoxScores) -> None:
        with self._ids_lock:
            box.save()

    def scorecards(self, week: int | None = None, system: str | None = None) -> dict[str, Any]:
        """Every league's scorecard of ``week`` (the last any league recorded by default), the
        public leagues' odds pooled, and the week as markdown for the AUTOPILOT tracker."""
        payloads, skipped = self._all_scorecards(system)
        # The markdown is public: a league's own failure text stays in the JSON.
        out = season_scorecard.all_payload(
            payloads, week, [{**x, "reason": "its scorecard failed"} for x in skipped]
        )
        return {**out, "skipped": skipped, "generated_at": self.clock().isoformat()}

    def _all_scorecards(
        self, system: str | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Every league's scorecard of all its recorded weeks, read with one box-score cache,
        and the leagues whose scorecard failed with the reason."""
        payloads, skipped = [], []
        box = season_scorecard.BoxScores.at(self.data_dir, nba_today(self.clock()))
        for league in leagues.leagues(self.data_dir):
            try:
                payloads.append(self.scorecard(league, None, system, box))
            except Exception as exc:  # noqa: BLE001 - one league's failure leaves the others
                reason = exc.detail if isinstance(exc, HTTPException) else type(exc).__name__
                skipped.append({"league": league, "reason": str(reason)})
        self._save_ids(box)
        return payloads, skipped

    def progress(self, system: str | None = None) -> dict[str, Any]:
        """The Progress view (#129): every league's scorecard over the season as series by week,
        pooled over the public leagues, with the knob file and the Monday notes; reads only."""
        payloads, skipped = self._all_scorecards(system)
        knobs, problems = season_knobs.load_knobs(self.data_dir)
        notes, found = season_progress.load_notes(self.data_dir)
        calendar = self._cached_calendar()
        out = season_progress.payload(
            payloads,
            knobs,
            notes,
            nba_today(self.clock()),
            calendar.weeks if calendar is not None else (),
            [*problems, *found],
            skipped,
            system,
        )
        return {**out, "generated_at": self.clock().isoformat()}

    def monday(
        self, monday: date | None = None, dry_run: bool = False, force: bool = False
    ) -> dict[str, Any]:
        """The Monday hill-climb step (#152) for ``monday``, this week's by default: the
        verdicts due, at most one knob change, the knob file and the Monday note written."""
        day = monday or season_hillclimb.monday_of(nba_today(self.clock()))
        return season_hillclimb.run(
            self.data_dir,
            day,
            self.clock(),
            self.progress,
            season_hillclimb.scorings(self.data_dir, self._base),
            dry_run,
            force,
        )

    # ------------------------------------------------------------------ freshness
    def status(self) -> dict[str, Any]:
        """The freshness light (#153): the daily exports, each league's Yahoo reads and its
        recommendations against the inputs they rest on; reads only."""
        # The Mac's clock, where the routine runs: its day and its due time.
        now = self.clock().astimezone(self.local_tz)
        found = season_status.exports_found(self.data_dir)
        exports = st.exports(found, now)
        projection_at = max((found[k][1] for k in st.RESTS_ON if found.get(k)), default=None)
        out = []
        for league in leagues.leagues(self.data_dir):
            try:
                base, is_public = self._base(league)
            except HTTPException as exc:
                out.append({"league": league, "state": st.RED, "error": str(exc.detail)})
                continue
            parts = load_parts(self.data_dir, league)
            fetched = {k: p.fetched_at for k, p in parts.items()}
            read_at = max(fetched.values(), default=None)
            folder = season_dir(self.data_dir, league)
            if is_public:
                # The service's own job; after a restart, the last one its log has.
                job = self.job(league)
                last = job.to_dict() if job else season_status.last_refresh(folder)
                snapshot = season_status.snapshot_at(folder / SNAPSHOTS, PUBLIC)
                rows = [st.refresh_row(last, read_at, snapshot, now, live=job is not None)]
                kind = "Yahoo"
            else:
                rows = st.pages(fetched, now)
                newest = max(fetched, key=fetched.__getitem__, default=None)
                kind = newest.split("/", 1)[0] if newest else "Yahoo"
            entries = season_status.latest_entries(folder, nba_today(now))
            recs = st.recommendations(entries, projection_at, read_at, now, yahoo=kind)
            name = Season.from_parts(base, parts).settings.name
            out.append(st.league(league, name, is_public, rows, recs, exports["state"]))
        routine = st.routine_row(season_status.routine_marker(self.data_dir), now)
        return st.payload(routine, exports, out, now)

    # ------------------------------------------------------------------ refresh
    def start_refresh(self, league: str) -> RefreshJob:
        """The league's refresh: the one running, else a new one in the background, within
        :data:`REFRESH_DEADLINE` (a running job past it is ended first, #166)."""
        self._base(league)
        with self._guard:
            job = self.jobs.get(league)
            self.expire(job)
            if job is not None and job.status == "running":
                return job
            job = self.jobs[league] = RefreshJob(league, deadline=REFRESH_DEADLINE)
        threading.Thread(
            target=self.run_refresh, args=(job,), daemon=True, name=f"season-{league}"
        ).start()
        return job

    def job(self, league: str) -> RefreshJob | None:
        """The league's last refresh job, ended first when it ran past its deadline (#166)."""
        job = self.jobs.get(league)
        self.expire(job)
        return job

    def expire(self, job: RefreshJob | None) -> None:
        """End ``job`` failed when it is running past its deadline (#166), its worker perhaps
        still in a read: logged, and the light and the next refresh see it ended."""
        running = job is not None and job.status == "running"
        if running and job.overdue() and job.end("failed", job.late()):
            log_refresh(self.data_dir, job)

    def run_refresh(self, job: RefreshJob) -> RefreshJob:
        league = job.league
        log_refresh(self.data_dir, job)
        status, error = "failed", "the refresh stopped before it ended"
        # The pages an earlier refresh read before the rate limit stopped it (#180).
        hold = self.held.pop(league, None) or Hold(self.clock)
        hold.clock = self.clock
        limited: public.RateLimited | None = None
        try:
            base, is_public = self._base(league)
            if not is_public:
                raise public.PrivateLeague(
                    f"league {league} is private: open its pages in Chrome with the extension"
                )
            # Every read checks the deadline, and so does every step (#166); a backoff on the
            # rate limit waits only inside it, and the pages read are held for a resume (#180).
            fetch = deadlined(hold.wrap(public.bounded(self.fetch_factory(), job.may_wait)), job)
            today = nba_today(self.clock())

            def progress(step: str, done: int, total: int) -> None:
                job.check()
                job.step, job.done, job.total = step, done, total

            received = public.refresh_parts(
                league,
                base,
                fetch,
                today,
                progress=progress,
                warn=job.warnings.__setitem__,
                clock=hold.stamp,
            )
            settings = base.merged(next(p.data for p in received if p.key == "settings"))
            job.at("calendar")
            calendar = self._calendar(league, settings, fetch, today)
            job.at("pairs")
            weeks = self._unpaired(league, base, received, calendar, today)
            received += public.pairings_parts(league, weeks, fetch, step=job.at, clock=hold.stamp)
            job.at("lineups")
            received += (
                public.lineup_parts(
                    league,
                    base.my_team_id,
                    self._lineup_days(league, base.my_team_id, calendar, today),
                    fetch,
                    step=job.at,
                    clock=hold.stamp,
                )
                if base.my_team_id is not None
                else []
            )
            job.at("schedule")
            self._save_with_schedule(league, received, calendar, fetch, today)
            job.at("box scores")
            self._box_scores(job, fetch, today, calendar)
            job.at("flag inputs")
            self._record_adds(league, today)
            self._flag_inputs(job, fetch, today)
            job.check()
            status, error = "done", None
        except RefreshDeadline as exc:
            status, error = "failed", str(exc)
        except public.PrivateLeague as exc:
            status, error = "private", str(exc)
        except public.RateLimited as exc:
            limited = exc
            status, error = "failed", self._limited(job, hold, exc)
        except (public.FetchError, pages.PageError) as exc:
            status, error = "failed", str(exc)
        except HTTPException as exc:
            status, error = "failed", str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - the job reports what broke instead of dying silently
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            # The total counted every players page; the pool may have ended sooner. A job the
            # deadline already ended keeps that end (#166). Only the rate limit keeps the pages
            # read for the next refresh (#180).
            done = {"step": "done", "total": job.done} if status == "done" else {}
            if limited is not None:
                kept = self.held[league] = hold.kept()
                done |= {
                    "rate_limited": True,
                    "retry_after": limited.retry_after,
                    "held": len(kept.earlier),
                }
            if job.end(status, error, resumed=len(hold.taken), **done):
                log_refresh(self.data_dir, job)
        return job

    def _limited(self, job: RefreshJob, hold: Hold, exc: public.RateLimited) -> str:
        """The error of a refresh Yahoo's rate limit ended: the answer, where the job got to and
        the pages held for the next one, until when on the Mac's clock (#180)."""
        why = f"HTTP {exc.status}" if exc.status else "its reads paused"
        kept = hold.kept()
        until = kept.until()
        held = (
            f"{len(kept.earlier)} pages held until {until.astimezone(self.local_tz):%H:%M}"
            if until is not None
            else "no pages held"
        )
        wait = f"; read again in {math.ceil((exc.retry_after or 0) / 60)} min"
        return f"rate limited by Yahoo ({why}) at {job.step} {job.done}/{job.total}; {held}{wait}"

    def _lineup_days(
        self, league: str, team: int | None, calendar: Calendar | None, today: date
    ) -> list[date]:
        """The days whose lineup a refresh reads: today and the days after it in this week every
        time (#107), and each day before today of this week or the last until it was read after
        the day (#149), since a lineup read on its own day may change later that day."""
        week = calendar.week_of(today) if calendar is not None else None
        if calendar is None or week is None or team is None:
            return []
        last = calendar.week_of(week.start - timedelta(days=1))
        parts = load_parts(self.data_dir, league)
        past = [d for w in (last, week) if w is not None for d in w.days() if d < today]
        again = [d for d in past if not _read_after(parts.get(lineup_key(team, d)), d)]
        return again + week.days(today)

    def _unpaired(
        self,
        league: str,
        base: SeasonSettings,
        received: list[Part],
        calendar: Calendar | None,
        today: date,
    ) -> list[int]:
        """The regular weeks ahead whose pairs the season lacks once ``received`` is merged:
        each is read once, and again only while its page lists no pairs."""
        parts = load_parts(self.data_dir, league)
        for part in received:
            parts = merge_part(parts, part)
        if calendar is not None:
            parts = merge_part(parts, Part("calendar", self.clock(), PUBLIC, calendar.to_dict()))
        return Season.from_parts(base, parts).weeks_unpaired(today)

    def _save_with_schedule(
        self,
        league: str,
        received: list[Part],
        calendar: Calendar | None,
        fetch: public.Fetch,
        today: date,
    ) -> None:
        """Merge ``received`` with the calendar and the NBA schedule for the days the view counts
        games on into the league's season, and save it."""
        if calendar is not None:
            received.append(Part("calendar", self.clock(), PUBLIC, calendar.to_dict()))
        # Read before the league's lock: a snapshot posted meanwhile does not wait on ESPN.
        days = _schedule_days(calendar, today)
        read = nba_schedule.schedule_days(
            days,
            fetch,
            self.data_dir / SCHEDULE_DIR,
            now=self.clock(),
            far_from=today + timedelta(weeks=WEEKS_AHEAD),
        )
        with self.lock(league):
            parts = load_parts(self.data_dir, league)
            old = (parts.get("schedule").data if "schedule" in parts else {}).get("days", {})
            received.append(Part("schedule", self.clock(), PUBLIC, {"days": {**old, **read}}))
            for part in received:
                parts = merge_part(parts, part)
            save(self.data_dir, league, parts, received, PUBLIC, self.clock())

    # ------------------------------------------------------------------ a private league's extras
    def start_extras(self, league: str) -> RefreshJob | None:
        """A private league's public parts, in the background, when its season lacks them or
        its schedule is older than :data:`nba_schedule.MAX_AGE`: the week calendar (the shared
        cache a public league's refresh writes; no page of a private league answers the probe),
        the NBA schedule and the box scores. Its Yahoo pages come from the extension's
        snapshots."""
        parts = load_parts(self.data_dir, league)
        schedule = parts.get("schedule")
        fresh = schedule is not None and self.clock() - schedule.fetched_at < nba_schedule.MAX_AGE
        if fresh and ("calendar" in parts or self._cached_calendar() is None):
            return None
        with self._guard:
            job = self.jobs.get(league)
            if job is not None and job.status == "running":
                return job
            job = self.jobs[league] = RefreshJob(league, step="schedule")
        threading.Thread(
            target=self.run_extras, args=(job,), daemon=True, name=f"season-extras-{league}"
        ).start()
        return job

    def run_extras(self, job: RefreshJob) -> RefreshJob:
        try:
            today = nba_today(self.clock())
            # The extension's page posts start these reads: never paced with, nor refused by,
            # the public refreshes' Yahoo limit (#180).
            fetch = public.unpaced(self.fetch_factory())
            calendar = self._cached_calendar()
            self._save_with_schedule(job.league, [], calendar, fetch, today)
            job.step = "box scores"
            self._box_scores(job, fetch, today, calendar)
            job.step = "flag inputs"
            self._flag_inputs(job, fetch, today)
            job.status, job.step = "done", "done"
        except Exception as exc:  # noqa: BLE001 - the job reports what broke instead of dying silently
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            job.finished_at = datetime.now(UTC)
        return job

    def _cached_calendar(self) -> Calendar | None:
        try:
            return Calendar.from_dict(json.loads(calendar_path(self.data_dir).read_text()))
        except (OSError, ValueError, KeyError):
            return None

    def _calendar(
        self, league: str, settings: SeasonSettings, fetch: public.Fetch, today: date
    ) -> Calendar | None:
        """The season's matchup weeks, from the shared cache when it reaches the season's end;
        else read once from the league's team page, one request per Monday."""
        end = settings.end_date
        if end is None:
            return None
        cached = self._cached_calendar()
        if (
            cached is not None
            and cached.weeks
            and cached.weeks[-1].end >= end
            and not cached.estimated
        ):
            return cached
        week = settings.current_week or 1
        first = monday_of(today) - timedelta(weeks=week - 1)
        team = settings.my_team_id or 1
        labels = public.week_labels(league, team, mondays(first, end), fetch)
        calendar = build_calendar(first, end, labels)
        _write_json(calendar_path(self.data_dir), calendar.to_dict())
        return calendar

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, league: str, body: SnapshotBody) -> dict[str, Any]:
        base, is_public = self._base(league)
        today = nba_today(self.clock())
        received: list[Part] = []
        skipped: list[dict[str, str]] = []
        for page in body.pages:
            at = page.fetched_at or self.clock()
            try:
                received.extend(_page_parts(league, page.url, page.html, at, today))
            except pages.PageError as exc:
                skipped.append({"url": page.url, "reason": str(exc)})
        for given in body.parts:
            if not _known_key(given.key):
                skipped.append({"key": given.key, "reason": "unknown part"})
                continue
            received.append(
                Part(given.key, given.fetched_at or self.clock(), EXTENSION, given.data)
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
                save(self.data_dir, league, parts, received, EXTENSION, self.clock())
        if any(p.key == "available" for p in received):
            self._record_adds(league, today)
        summary = self.summary(league)
        if received and not is_public:
            self.start_extras(league)
        return {"accepted": [p.key for p in received], "skipped": skipped, "season": summary}


#: The skip reasons the public digest prints as they are; any other reads as a failure.
NO_SEASON = "no season read yet"


def _failure(exc: Exception) -> str:
    """A league's failure for the queue's row: an HTTP refusal's own words, else the type."""
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return f"{type(exc).__name__}: {exc}"


def _resolver(
    resolved: dict[str, str], now: datetime
) -> Callable[[dict[str, Any] | None], dict[str, Any]]:
    """An earlier queue's change that sets the claims the transactions settled (#171)."""

    def change(body: dict[str, Any] | None) -> dict[str, Any]:
        body = body or {}
        for e in body.get("entries") or []:
            if e.get("id") in resolved and not e.get("resolved"):
                e["resolved"] = resolved[e["id"]]
                e["resolved_at"] = now.isoformat()
        return body

    return change


def _public_reason(reason: str) -> str:
    return reason if reason == NO_SEASON else "its flags failed"


def _known_key(key: str) -> bool:
    fixed = {
        "settings",
        "players",
        "league",
        "available",
        "transactions",
        "calendar",
        "schedule",
        "draft",
        "league_settings",
        YAHOO_WEEK,
    }
    return key in fixed or key.startswith(("roster/", "matchup/", "pairings/", "lineup/"))


def _read_after(part: Part | None, day: date) -> bool:
    """Whether a day's lineup was read after the day, so that it is final (#149)."""
    return part is not None and nba_today(part.fetched_at) > day


def _lineup_pages(
    season: Season, calendar: Calendar | None, today: date, recorded: Week | None = None
) -> list[str]:
    """The pages a private league's lineups need from the user's Chrome: the settings page
    until it was read, my team page shown for each day of this week from today, and for each
    day of the ``recorded`` week not read after it (#149)."""
    s = season.settings
    out = [] if s.held_from == SLOTS_PAGE else [public.settings_page_url(s.league)]
    week = calendar.week_of(today) if calendar is not None else None
    if week is not None and s.my_team_id is not None:
        out += [public.team_url(s.league, s.my_team_id, d) for d in week.days(today)]
    if recorded is not None and s.my_team_id is not None:
        final = season_lineup.final_reads(season, s.my_team_id, recorded.days())
        out += [
            public.team_url(s.league, s.my_team_id, d)
            for d in recorded.days()
            if d < today and d not in final
        ]
    return out


def _page_parts(league: str, url: str, html: str, at: datetime, today: date) -> list[Part]:
    """The season parts one league page gives: one, except that the players page in Yahoo's
    projection view also gives the projection rows."""
    kind, info = pages.page_kind(url)
    part = _page_part(league, kind, info, html, at, today)
    if kind == "players" and info.get("view") == pages.PROJECTION_VIEW:
        rows = pages.parse_projection_page(html)["rows"]
        seen = at.isoformat()
        data = {"upsert": True, "rows": [{**r, "seen_at": seen} for r in rows]}
        return [part, Part(YAHOO_WEEK, at, EXTENSION, data)]
    return [part]


def _page_part(
    league: str, kind: str, info: dict[str, Any], html: str, at: datetime, today: date
) -> Part:
    if info["league"] != str(league):
        raise pages.PageError(f"the page is league {info['league']}'s, not {league}'s")
    if kind == "league":
        if "matchup_week" in info:
            # Another week's pairs (the week select): its own part, never this week's league
            # part, so it moves neither the standings nor the current week.
            week = int(info["matchup_week"])
            return Part(pairings_key(week), at, EXTENSION, pages.parse_pairings(html, week))
        return Part("league", at, EXTENSION, pages.parse_league_page(html))
    if kind == "team":
        d = pages.parse_team_page(html, info["team_id"])
        if "date" in info:
            # Another day's lineup (#107): its own part, never the roster today's page holds.
            return Part(lineup_key(info["team_id"], info["date"]), at, EXTENSION, d)
        return Part(roster_key(info["team_id"]), at, EXTENSION, d)
    if kind == "settings":
        return Part("league_settings", at, EXTENSION, pages.parse_settings_page(html))
    if kind == "players":
        d = pages.parse_players_page(html, today)
        return Part(
            "available",
            at,
            EXTENSION,
            {**d, "upsert": True, "rows": [{**r, "seen_at": at.isoformat()} for r in d["rows"]]},
        )
    if kind == "matchup":
        # The pair the URL asked for: a page showing another is skipped, never stored as it.
        d = pages.parse_matchup_page(html, info.get("week"), info.get("teams"))
        return Part(matchup_key(d["week"], d["teams"]), at, EXTENSION, d)
    if kind == "transactions":
        return Part("transactions", at, EXTENSION, pages.parse_transactions_page(html))
    if kind == "draftresults":
        return Part("draft", at, EXTENSION, pages.parse_draft_results(html))
    raise pages.PageError(f"no parser for a {kind} page")


def _schedule_days(calendar: Calendar | None, today: date) -> list[date]:
    """The dates the season view counts games on: the rest of the season, for the Season view
    (#116; four weeks of days when the calendar is not known). The dates past the Moves card's
    four weeks are read again only weekly (``nba_schedule.schedule_days``' ``far_from``)."""
    if calendar is not None:
        weeks = [w for w in calendar.weeks if w.end >= today]
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


def _glance(season: Season, today: date) -> dict[str, Any]:
    """My week at a glance: the score so far, mine first, and the adds left this week."""
    mine = season.settings.my_team_id
    matchup = season.matchup_of(mine)
    score = None
    if matchup is not None and matchup.score is not None:
        a, b = matchup.score
        score = [a, b] if matchup.teams[0] == mine else [b, a]
    week = season.current(today)
    adds = None
    if mine is not None and week is not None:
        limit = season.settings.max_weekly_adds
        used = mv.adds_used(season.transactions, mine, week.start, week.end, today)
        adds = {
            "limit": limit,
            "used": used.count,
            "complete": used.complete,
            "left": None if limit is None else max(0, limit - used.count),
        }
    return {"score": score, "adds": adds}


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


class TradeBody(BaseModel):
    #: The counterparty's team id.
    team: int
    #: My players who go to them, and theirs who come to me, by Yahoo id.
    give: list[int] = Field(default_factory=list)
    get: list[int] = Field(default_factory=list)
    #: The projection system; the knob file's when None (#152).
    system: str | None = Field(None, pattern="^(bbm|yahoo|blend)$")
    #: The day the trade takes effect; by default when Yahoo would process it if accepted today.
    effective: date | None = None


class LineupMode(BaseModel):
    #: The lineup executor's mode (#170): ``off``, ``dry_run`` or ``live``.
    mode: str = Field(pattern="^(off|dry_run|live)$")


class PassOpen(BaseModel):
    #: A routine's pass (#201): its kind and trigger, the leagues in the order it opens them and,
    #: for a moves pass, the entries it will check.
    kind: Literal["moves", "lineup"]
    #: ``routine_evening`` opens a moves pass only (#209): the evening has no lineup pass.
    trigger: Literal["routine", "routine_late", "routine_evening"]
    leagues: list[str] = Field(min_length=1)
    entries: list[str] | None = None


class PassOpening(BaseModel):
    league: str
    entry: str | None = None


class PassDone(BaseModel):
    summary: str | None = Field(None, max_length=500)


class AllMovesMode(BaseModel):
    #: The Queue screen's one switch (#205): the moves executor's mode for every public league.
    #: No cap: each league keeps the user's own.
    mode: str = Field(pattern="^(off|dry_run|live)$")


class MovesMode(BaseModel):
    #: The moves executor's mode (#171), and the user's own cap on the day's moves (None: the
    #: knob's). The body is the whole setting: a mode sent without a cap clears the user's.
    mode: str = Field(pattern="^(off|dry_run|live)$")
    cap: int | None = Field(None, ge=0, le=10)


class StrikeBody(BaseModel):
    #: Strike the bid alone (the claim placed for $0), and undo a strike.
    bid_only: bool = False
    undo: bool = False


class QueueSettings(BaseModel):
    #: The day's execute time on the Central clock, and Sunday's own (#209): either may be sent
    #: alone; Sunday's sent null clears it.
    execute_time: str | None = Field(None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    sunday_execute_time: str | None = Field(None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


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

    week_q = Query(None, ge=1, description="the week; by default the last recorded")
    scorecard_system_q = Query(
        None,
        pattern="^(bbm|yahoo|blend)$",
        description="the system scored; by default each week's in force when it began (#152)",
    )

    # Before ``/seasons/{league}``, whose pattern would refuse the word.
    @app.get("/seasons/scorecard")
    async def get_scorecards(
        week: int | None = week_q, system: str | None = scorecard_system_q
    ) -> dict[str, Any]:
        """Every league's scorecard of a week (#126), pooled, with the markdown for #127."""
        return await asyncio.to_thread(service.scorecards, week, system)

    @app.get("/seasons/status")
    async def get_status() -> dict[str, Any]:
        """The freshness light (#153): the daily exports, every league's Yahoo reads and when
        its recommendations were built against their inputs; reads only."""
        return await asyncio.to_thread(service.status)

    @app.get("/progress")
    async def get_progress(system: str | None = scorecard_system_q) -> dict[str, Any]:
        """The hill-climb over the season (#129): every league's weeks against their
        projection, pooled, the moves, the knob changes and the Monday notes; reads only."""
        return await asyncio.to_thread(service.progress, system)

    monday_q = Query(None, description="the Monday; this week's by default")

    @app.post("/autopilot/monday")
    async def post_monday(
        monday: date | None = monday_q,
        dry_run: bool = Query(False, description="answer the step, write nothing"),
        force: bool = Query(
            False, description="undo the Monday's own change (never one judged) and run again"
        ),
    ) -> dict[str, Any]:
        """The Monday hill-climb step (#152): the verdicts due, at most one knob change from
        the rule table, the knob file and the Monday note; once a Monday."""
        return await asyncio.to_thread(service.monday, monday, dry_run, force)

    queue_day_q = Query(None, alias="date", description="the day; today by default")

    @app.get("/autopilot/queue")
    def get_queue(day: date | None = queue_day_q) -> dict[str, Any]:
        """A day's queue of the moves executor (#171); reads only."""
        return service.queue(day)

    @app.post("/autopilot/queue/build")
    async def post_queue_build() -> dict[str, Any]:
        """Build today's queue from the day's moves solves in the decision log (#171); never a
        solve. Again the same day, it keeps what was struck or executed."""
        return await asyncio.to_thread(service.build_queue)

    @app.put("/autopilot/queue/settings")
    def put_queue_settings(body: QueueSettings) -> dict[str, Any]:
        """The execute times, the dashboard's own click (#171, Sunday's #209)."""
        return service.set_execute_time(body)

    @app.post("/autopilot/queue/{entry}/strike")
    def post_strike(entry: str, body: StrikeBody | None = None) -> dict[str, Any]:
        """The user's veto on a queue entry (#171): strike it or its bid, or undo either."""
        body = body or StrikeBody()
        return service.strike(entry, body.bid_only, body.undo)

    @app.get("/seasons/{league}")
    def get_season(league: str = league_id) -> dict[str, Any]:
        return service.view(league)

    @app.get("/seasons/{league}/scorecard")
    async def get_scorecard(
        league: str = league_id, week: int | None = week_q, system: str | None = scorecard_system_q
    ) -> dict[str, Any]:
        """A league's recorded weeks against the decision log (#126)."""
        return await asyncio.to_thread(service.scorecard, league, week, system)

    @app.post("/seasons/{league}/refresh", status_code=202)
    async def refresh_season(
        league: str = league_id,
        wait: bool = Query(False, description="return once the refresh is done"),
    ) -> dict[str, Any]:
        """Read the league's public sources again. A private league answers 409."""
        # One job per league, the running one or a new one, under the service's guard (#166).
        job = service.start_refresh(league)
        while wait and job.status == "running":
            await asyncio.to_thread(job.wait, 1.0)
            service.expire(job)
        if job.status == "private":
            raise HTTPException(409, job.error)
        if job.status == "failed" and job.rate_limited:
            raise HTTPException(503, job.error, headers=retry_after(job.retry_after))
        if job.status == "failed":
            raise HTTPException(502, job.error)
        return {"refresh": job.to_dict(), "season": service.summary(league)}

    system_q = Query(
        None,
        pattern="^(bbm|yahoo|blend)$",
        description="the projection system; the knob file's (#152) by default",
    )
    from_q = Query(None, alias="from", description="the first day; a week before the last")
    to_q = Query(None, alias="to", description="the last day; today")

    @app.get("/seasons/{league}/moves")
    async def get_moves(
        league: str = league_id,
        system: str | None = system_q,
        source: str | None = Query(
            None,
            pattern="^page$",
            description="page: the web's look, answered at once and never logged (#240)",
        ),
    ) -> dict[str, Any]:
        """Every available player's best move on both horizons and the recommended moves. A call
        without ``source`` (the routine's) waits for the solve and writes one decision entry."""
        return await asyncio.to_thread(service.moves, league, system, source, source is None)

    @app.get("/seasons/{league}/best")
    async def get_best(league: str = league_id, system: str | None = system_q) -> dict[str, Any]:
        """The best recommended move when today's moves are solved; never solves them."""
        return await asyncio.to_thread(service.best, league, system)

    @app.post("/seasons/{league}/best")
    async def post_best(league: str = league_id, system: str | None = system_q) -> dict[str, Any]:
        """Solve today's moves and give the best recommended move."""
        return await asyncio.to_thread(service.best, league, system, True)

    @app.get("/seasons/{league}/moves/{player}")
    async def get_move(
        player: int,
        league: str = league_id,
        drop: int | None = Query(None, description="the player dropped for him; none: a free spot"),
        system: str | None = system_q,
    ) -> dict[str, Any]:
        """The move drawer for adding ``player``."""
        return await asyncio.to_thread(service.move_detail, league, player, drop, system)

    lock_q = Query([], description="my players no move may drop")

    @app.get("/seasons/{league}/matchup")
    async def get_matchup(league: str = league_id, system: str | None = system_q) -> dict[str, Any]:
        """My matchup this week: the projected finals and odds per category, the matchup odds,
        and what each player of both teams adds to them (#116)."""
        return await asyncio.to_thread(service.matchup, league, system)

    @app.get("/seasons/{league}/outlook")
    async def get_outlook(league: str = league_id, system: str | None = system_q) -> dict[str, Any]:
        """Every week left of my season: the win odds against its opponent (or the field), the
        summary of the regular weeks, and each week's scoreboard and my players (#116)."""
        return await asyncio.to_thread(service.outlook, league, system)

    @app.get("/seasons/{league}/lineup")
    async def get_lineup(
        league: str = league_id,
        system: str | None = system_q,
        week: int | None = Query(
            None, description="a week of the moves' four; this one by default"
        ),
    ) -> dict[str, Any]:
        """My recommended lineup for each day of the week against Yahoo's as read (#107)."""
        return await asyncio.to_thread(service.lineup, league, system, week)

    steps_day_q = Query(None, alias="date", description="the day; today by default")

    @app.get("/seasons/{league}/lineup/steps")
    async def get_lineup_steps(
        league: str = league_id, day: date | None = steps_day_q
    ) -> dict[str, Any]:
        """The lineup executor's steps for a day (#170); nothing here sets a lineup."""
        return await asyncio.to_thread(service.lineup_steps, league, day)

    @app.get("/seasons/{league}/autopilot")
    def get_autopilot(league: str = league_id) -> dict[str, Any]:
        """The lineup executor's mode, STOP, the live check and its runs (#170)."""
        return service.autopilot(league)

    @app.post("/seasons/{league}/autopilot/lineup")
    def post_lineup_run(body: dict[str, Any], league: str = league_id) -> dict[str, Any]:
        """A run of the lineup executor, for the league's log (#170). The page's crumb is never
        posted here: a run carrying one is refused."""
        if season_autopilot.has_crumb(body):
            raise HTTPException(422, "a run never carries the page's crumb")
        try:
            run = season_autopilot.LineupRun.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return service.log_lineup_run(league, run)

    @app.put("/leagues/{league}/lineups")
    def put_lineup_mode(body: LineupMode, league: str = league_id) -> dict[str, Any]:
        """The Lineup view's mode switch, the user's own click (#170). No session, script or
        routine sets ``live``."""
        try:
            return service.set_lineup_mode(league, body.mode)
        except leagues.LeagueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/seasons/{league}/autopilot/moves")
    def get_moves_autopilot(league: str = league_id) -> dict[str, Any]:
        """The moves executor's mode, STOP, the live check, its passes and the league's entries
        of today's queue (#171)."""
        return service.moves_view(league)

    @app.get("/seasons/{league}/autopilot/moves/due")
    def get_moves_due(league: str = league_id, day: date | None = steps_day_q) -> dict[str, Any]:
        """The league's queue entries due now, for the extension's execute pass (#171); nothing
        here claims or drops anyone."""
        return service.moves_due(league, day)

    @app.post("/seasons/{league}/autopilot/moves")
    def post_moves_run(body: dict[str, Any], league: str = league_id) -> dict[str, Any]:
        """An execute pass of the moves executor, for the league's log (#171). The page's crumb
        is never posted here: a pass carrying one is refused."""
        if season_autopilot.has_crumb(body):
            raise HTTPException(422, "a pass never carries the page's crumb")
        try:
            run = season_autopilot.MovesRun.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return service.log_moves_run(league, run)

    @app.post("/seasons/{league}/autopilot/drop")
    def post_drop_run(body: dict[str, Any], league: str = league_id) -> dict[str, Any]:
        """A churn's held drop on the drop page (#221 part 3), for the league's log. The page's
        crumb is never posted here: a run carrying one is refused."""
        if season_autopilot.has_crumb(body):
            raise HTTPException(422, "a run never carries the page's crumb")
        try:
            run = season_autopilot.DropRun.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return service.log_drop_run(league, run)

    @app.post("/seasons/{league}/autopilot/il")
    def post_il_run(body: dict[str, Any], league: str = league_id) -> dict[str, Any]:
        """An IL move on the team page for an open-spot claim, for the league's log (#214). The
        page's crumb is never posted here: a run carrying one is refused."""
        if season_autopilot.has_crumb(body):
            raise HTTPException(422, "a run never carries the page's crumb")
        try:
            run = season_autopilot.ILRun.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return service.log_il_run(league, run)

    @app.get("/autopilot/start-active/due")
    def get_start_active_due() -> dict[str, Any]:
        """The armed public leagues that want Yahoo's Start Active Players for the rest of the
        week, and why (#215); nothing here presses anything."""
        return service.start_active_due()

    @app.post("/seasons/{league}/autopilot/start-active")
    def post_start_active_run(body: dict[str, Any], league: str = league_id) -> dict[str, Any]:
        """A Start Active run on the team page, for the league's log (#215). The page's crumb is
        never posted here: a run carrying one is refused."""
        if season_autopilot.has_crumb(body):
            raise HTTPException(422, "a run never carries the page's crumb")
        try:
            run = season_autopilot.StartActiveRun.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
        return service.log_start_active_run(league, run)

    @app.put("/leagues/{league}/moves")
    def put_moves_mode(body: MovesMode, league: str = league_id) -> dict[str, Any]:
        """The Queue card's mode switch and cap, the user's own click (#171). No session, script
        or routine sets ``live``."""
        try:
            return service.set_moves_mode(league, body.mode, body.cap)
        except leagues.LeagueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post("/autopilot/passes")
    def post_pass(body: PassOpen) -> dict[str, Any]:
        """Open a routine's execute pass (#201), for the Queue screen to show it live; refused
        while a pass of its kind is open."""
        return service.open_pass(body)

    @app.post("/autopilot/passes/{pass_id}/opening")
    def post_pass_opening(pass_id: str, body: PassOpening) -> dict[str, Any]:
        """The league (and entry) the routine's pass opens now (#201)."""
        return service.pass_opening(pass_id, body)

    @app.post("/autopilot/passes/{pass_id}/done")
    def post_pass_done(pass_id: str, body: PassDone | None = None) -> dict[str, Any]:
        """The routine's end of its pass (#201); refused once it is done or stale."""
        return service.pass_done(pass_id, body or PassDone())

    @app.put("/autopilot/moves/mode")
    def put_all_moves_modes(body: AllMovesMode) -> dict[str, Any]:
        """The Queue screen's one switch for every public league's moves executor, the user's
        own click (#205): each league's live guard is checked on its own and a league it refuses
        keeps its mode. No session, script or routine sets ``live``."""
        return service.set_all_moves_modes(body.mode)

    @app.get("/seasons/{league}/decisions")
    async def get_decisions(
        league: str = league_id,
        start: date | None = from_q,
        end: date | None = to_q,
    ) -> dict[str, Any]:
        """The decision log (#125): each solve's recommended sets and my moves matched to them."""
        return await asyncio.to_thread(service.decisions, league, start, end)

    @app.get("/seasons/{league}/strategy")
    async def get_strategy(
        league: str = league_id, system: str | None = system_q
    ) -> dict[str, Any]:
        """Today's strategy run, as far as it got; never solves."""
        return await asyncio.to_thread(service.strategy, league, system)

    @app.post("/seasons/{league}/strategy")
    async def post_strategy(
        league: str = league_id,
        system: str | None = system_q,
        pool: int = Query(
            season_strategy.POOL,
            ge=1,
            le=season_strategy.MAX_POOL,
            description="the candidates both solvers search, by single-move gain",
        ),
        weights: str = Query(
            ",".join(season_strategy.st.WEIGHT_KEYS),
            pattern=r"^(week|even|natural|season)(,(week|even|natural|season))*$",
            description="the frontier's weights, by key",
        ),
        lock: list[int] = lock_q,
        program_only: bool = Query(
            False, description="the linear program's set, the search only its fallback"
        ),
        wait: bool = Query(False, description="answer once the run is done"),
    ) -> dict[str, Any]:
        """Start the strategy run (or find the one with these settings)."""
        keys = [k for k in season_strategy.st.WEIGHT_KEYS if k in weights.split(",")]
        settings = season_strategy.Settings(pool, tuple(keys), tuple(lock), program_only)
        return await asyncio.to_thread(service.solve_strategy, league, system, settings, wait)

    @app.post("/seasons/{league}/trade")
    async def post_trade(body: TradeBody, league: str = league_id) -> dict[str, Any]:
        """Both sides of a proposed trade before and after. Nothing is sent to Yahoo."""
        return await asyncio.to_thread(service.trade, league, body)

    @app.post("/seasons/{league}/record")
    async def post_record(
        league: str = league_id,
        week: int | None = Query(None, description="a past week; by default the latest one over"),
    ) -> dict[str, Any]:
        """Record a finished week (#97). A private league answers 409 with the pages to open."""
        return await asyncio.to_thread(service.record, league, week)

    @app.get("/seasons/{league}/weeks")
    def get_weeks(league: str = league_id) -> dict[str, Any]:
        """The recorded weeks, for the season's history."""
        return service.weeks(league)

    @app.get("/seasons/{league}/weeks/{week}")
    def get_week(week: int, league: str = league_id) -> dict[str, Any]:
        """One recorded week."""
        return service.week(league, week)

    @app.get("/flags/digest")
    async def get_flag_digest() -> dict[str, Any]:
        """The day's breakout flags across leagues, for the daily alert on #99."""
        return await asyncio.to_thread(service.digest)

    @app.post("/seasons/{league}/snapshot")
    def post_snapshot(body: SnapshotBody, league: str = league_id) -> dict[str, Any]:
        """Pages or parsed parts of a league read in the user's own Chrome (the extension, for
        the private league)."""
        return service.snapshot(league, body)

    return service
