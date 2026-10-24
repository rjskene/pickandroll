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
    log under ``moves`` and the entries due for the extension; ``PUT /leagues/{league}/moves``
    sets the mode and the user's cap.
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
import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

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
    season_decisions,
    season_flags,
    season_hillclimb,
    season_knobs,
    season_lineup,
    season_matchup,
    season_moves,
    season_outlook,
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


def nba_today(now: datetime) -> date:
    return now.astimezone(NBA_TZ).date()


# --------------------------------------------------------------------------- refresh jobs
#: How long a public refresh may run, in seconds (#166): checked before every read and between
#: the steps, and by everything that reads the job. Past it the job ends failed, naming the step,
#: the page and the time it ran, and the league's next refresh can start. A read in flight
#: finishes or times out on its own socket timeout (``public.HttpFetch``); the step it cut is not
#: retried in the same job.
REFRESH_DEADLINE = 300.0


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
        }


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
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()
        #: One reader of ESPN's box scores at a time: two refreshes read a date once (#126).
        self._box_lock = threading.Lock()
        #: One writer of the ESPN ids the scorecards match.
        self._ids_lock = threading.Lock()
        self.moves_cache = season_moves.MovesCache()
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
        exports, the injury report (an O's return date) and the knob file (#152)."""
        files = [
            season_dir(self.data_dir, league) / STATE,
            self.data_dir / "aliases.json",
            season_flags.injuries_path(self.data_dir),
            season_knobs.autopilot_dir(self.data_dir) / season_knobs.KNOBS_FILE,
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

    def moves(self, league: str, system: str | None) -> dict[str, Any]:
        system = self._system(league, system)
        built = self._built(league, system)
        today = nba_today(self.clock())
        key = (league, system, "moves", today, self._moves_stamp(league))

        def make() -> dict[str, Any]:
            out = season_moves.moves_payload(built)
            self._log(league, lambda at: season_decisions.moves_entry(built, out, at))
            return out

        return self.moves_cache.get(key, make)

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
        day of its week, never solved again."""
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
        return season_autopilot.steps_payload(
            league, base.my_team_id, day, today, now, lineup, tips, mode, stop
        )

    def autopilot(self, league: str) -> dict[str, Any]:
        """The Lineup view's executor panel (#170)."""
        self._base(league)
        mode = leagues.lineup_mode(self.data_dir, league)
        return season_autopilot.view(self.data_dir, league, mode, nba_today(self.clock()))

    def log_lineup_run(self, league: str, run: season_autopilot.LineupRun) -> dict[str, Any]:
        """Append a run of the lineup executor to the league's log (#170), refused (409) when
        the mode, STOP or the run's own outcome says it should not have run."""
        self._base(league)
        mode = leagues.lineup_mode(self.data_dir, league)
        why = season_autopilot.check_run(run, mode, season_autopilot.stopped(self.data_dir))
        if why is not None:
            raise HTTPException(409, why)
        record = {
            "at": self.clock().isoformat(timespec="seconds"),
            **run.model_dump(mode="json", by_alias=True),
        }
        try:
            return season_autopilot.append_run(
                self.data_dir, league, record, nba_today(self.clock())
            )
        except season_autopilot.LogError as exc:
            raise HTTPException(409, str(exc)) from exc

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
        return {
            "date": day.isoformat(),
            "built": [],
            "execute_time": None,
            "leagues": [],
            "entries": [],
            **(body or {}),
            "settings": season_queue.settings(self.data_dir),
            "stop": season_autopilot.stopped(self.data_dir),
            "now": self.clock().isoformat(),
        }

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
        execute_time = season_queue.settings(self.data_dir)["execute_time"]
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
                    "pending": [c["id"] for c in claims],
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

        for day, q in earlier.items():
            ids = {e["id"] for e in q.get("entries") or []} & set(resolved)
            if ids:
                season_queue.update(self.data_dir, day, _resolver(resolved, now))
        try:
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

    def set_execute_time(self, value: str) -> dict[str, Any]:
        """The execute time, the dashboard's own click (#171): today's entries not executed are
        timed again, never sooner than a full window after they were queued."""
        try:
            season_queue.set_execute_time(self.data_dir, value, by="dashboard")
        except season_queue.QueueError as exc:
            raise HTTPException(422, str(exc)) from exc
        today = nba_today(self.clock())
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
        entries = [e for e in body.get("entries") or [] if e.get("league") == league]
        row = next((r for r in body.get("leagues") or [] if r["league"] == league), None)
        return {
            **season_autopilot.moves_view(self.data_dir, league, mode, today, entries),
            "row": row,
            "settings": season_queue.settings(self.data_dir),
        }

    def moves_due(self, league: str, day: date | None) -> dict[str, Any]:
        """The entries of the league due now (#171), for the extension's execute pass: queued,
        not struck, not executed, their window over, each with the bid to place; with the
        players protected and why (the stored keep rule's and the engine's now: the page check
        refuses a protected drop whatever the queue says), the day's cap, the adds left as read
        and the budget. None when the mode is off, STOP is on or the day is not today."""
        self._base(league)
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
            "entries": [],
            "next": None,
            "protected": {},
            "cap": None,
            "adds_left": [],
            "budget": None,
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
        due = [{**e, "bid_placed": qa.effective_bid(e)} for e in qa.due(mine, now)]
        later = sorted(
            at
            for e in mine
            if e.get("queued")
            and not e.get("struck")
            and not e.get("outcome")
            and e.get("executes_at")
            and (at := datetime.fromisoformat(e["executes_at"])) > now
        )
        return {
            **out,
            "reason": None if due else "nothing due now",
            "entries": due,
            "next": later[0].isoformat() if later else None,
            "protected": protected,
            "cap": row.get("cap"),
            "adds_left": row.get("adds_left") or [],
            "budget": row.get("budget"),
        }

    def log_moves_run(self, league: str, run: season_autopilot.MovesRun) -> dict[str, Any]:
        """Append an execute pass to the league's log under ``moves`` (#171) and set its outcomes
        on the queue's entries; refused (409) when the mode, STOP, the queue or the pass's own
        outcome says it should not have run."""
        self._base(league)
        mode = leagues.executor_mode(self.data_dir, league, leagues.MOVES)
        body = self._read_queue(run.day) or {}
        mine = {e["id"]: e for e in body.get("entries") or [] if e.get("league") == league}
        why = season_autopilot.check_moves_run(
            run, mode, season_autopilot.stopped(self.data_dir), mine
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
        checks = {c.id: c for c in run.entries}
        if checks:

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
        return record

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
        try:
            base, is_public = self._base(league)
            if not is_public:
                raise public.PrivateLeague(
                    f"league {league} is private: open its pages in Chrome with the extension"
                )
            # Every read checks the deadline, and so does every step (#166).
            fetch = deadlined(self.fetch_factory(), job)
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
                clock=self.clock,
            )
            settings = base.merged(next(p.data for p in received if p.key == "settings"))
            job.at("calendar")
            calendar = self._calendar(league, settings, fetch, today)
            job.at("pairs")
            weeks = self._unpaired(league, base, received, calendar, today)
            received += public.pairings_parts(league, weeks, fetch, step=job.at, clock=self.clock)
            job.at("lineups")
            received += (
                public.lineup_parts(
                    league,
                    base.my_team_id,
                    self._lineup_days(league, base.my_team_id, calendar, today),
                    fetch,
                    step=job.at,
                    clock=self.clock,
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
        except (public.FetchError, pages.PageError) as exc:
            status, error = "failed", str(exc)
        except HTTPException as exc:
            status, error = "failed", str(exc.detail)
        except Exception as exc:  # noqa: BLE001 - the job reports what broke instead of dying silently
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            # The total counted every players page; the pool may have ended sooner. A job the
            # deadline already ended keeps that end (#166).
            done = {"step": "done", "total": job.done} if status == "done" else {}
            if job.end(status, error, **done):
                log_refresh(self.data_dir, job)
        return job

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
            fetch = self.fetch_factory()
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
    #: The day's execute time on the Pacific clock.
    execute_time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


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
        """The day's execute time, the dashboard's own click (#171)."""
        return service.set_execute_time(body.execute_time)

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
    async def get_moves(league: str = league_id, system: str | None = system_q) -> dict[str, Any]:
        """Every available player's best move on both horizons and the recommended moves."""
        return await asyncio.to_thread(service.moves, league, system)

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

    @app.put("/leagues/{league}/moves")
    def put_moves_mode(body: MovesMode, league: str = league_id) -> dict[str, Any]:
        """The Queue card's mode switch and cap, the user's own click (#171). No session, script
        or routine sets ``live``."""
        try:
            return service.set_moves_mode(league, body.mode, body.cap)
        except leagues.LeagueError as exc:
            raise HTTPException(404, str(exc)) from exc

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
