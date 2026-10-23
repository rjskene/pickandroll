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
    ``?wait=true`` returns once it is done. A private league answers ``409`` with what to do.
``POST /seasons/{league}/snapshot``
    The extension's reads of a private league: whole pages (``{url, html}``, parsed here by
    the same parsers) or parts already parsed (``{key, data}``).
``GET /seasons/{league}/moves``
    Every available player's best move this week and over the next three, and the recommended
    moves under the weekly add limit (#94, ``season_moves``); ``?system=yahoo`` for Yahoo's
    projection.
``GET /seasons/{league}/moves/{player}``
    The move drawer: adding ``player`` (for ``?drop=``) per category on both horizons, with
    every other drop and the best other adds.
``GET /seasons/{league}/lineup``
    The Lineup view (#107, ``season_lineup``): my recommended starters for each day of a week
    (``?week=``, this one by default) against Yahoo's lineup as read, the games it loses, the
    held slots with who is eligible for them, and first any held player whose status cleared.
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
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi import Path as FastPath
from pydantic import BaseModel, Field

from ..season import (
    EXTENSION,
    PUBLIC,
    YAHOO_WEEK,
    Calendar,
    Part,
    Season,
    SeasonSettings,
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
from ..season import moves as mv
from ..season import record as season_rec
from ..season.state import SLOTS_PAGE
from ..sources import schedule as nba_schedule
from ..sources.yahoo import pages, public
from . import (
    leagues,
    season_decisions,
    season_flags,
    season_lineup,
    season_matchup,
    season_moves,
    season_outlook,
    season_record,
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


#: A day's lineup is kept this long: this week's and last week's days.
LINEUP_KEPT = timedelta(days=14)


def save(
    data_dir: Path, league: str, parts: dict[str, Part], received: list[Part], source: str
) -> None:
    """The season's parts, less the matchup pages whose teams were misread
    (``unpaired_matchups``) and the lineup pages older than :data:`LINEUP_KEPT`, and a snapshot
    of what was received."""
    misread = unpaired_matchups(parts)
    parts = {k: p for k, p in parts.items() if k not in misread}
    folder = season_dir(data_dir, league)
    oldest = (datetime.now(UTC) - LINEUP_KEPT).date().isoformat()
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
        job = self.jobs.get(league)
        out = _summary(season, is_public, bool(parts), job)
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
            **_summary(season, is_public, bool(parts), self.jobs.get(league)),
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
        return {
            "date": today.isoformat(),
            "generated_at": now.isoformat(),
            "inputs": inputs,
            "notes": notes,
            "leagues": rows,
            "skipped": skipped,
            "lineups": lineups,
            "markdown": markdown + season_lineup.digest_section([*cleared_lines, *lineup_lines]),
        }

    def _lineup_line(self, league: str, today: date) -> dict[str, Any]:
        """A league's lineup for the digest: today's and tomorrow's games lost as set and the
        line saying so (None when nothing is lost or nothing was read), and the line naming a
        held player whose status cleared; the failure, if any, stays in the JSON."""
        try:
            out = self.lineup(league, "bbm", None)
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
        exports and the injury report (an O's return date)."""
        files = [
            season_dir(self.data_dir, league) / STATE,
            self.data_dir / "aliases.json",
            season_flags.injuries_path(self.data_dir),
        ]
        for pattern in (*BBM_ROS, BBM_THIS_WEEK, BBM_NEXT_WEEK):
            files += sorted(self.data_dir.glob(pattern))
        return tuple((f.name, f.stat().st_mtime_ns) for f in files if f.exists())

    def _built(self, league: str, system: str) -> season_moves.Built:
        base, _ = self._base(league)
        today = nba_today(self.clock())
        key = (league, system, "built", today, self._moves_stamp(league))

        def make() -> season_moves.Built | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_moves.build(season, today, self.data_dir, system)

        built = self.moves_cache.get(key, make)
        if built is None:
            raise HTTPException(409, f"league {league} has no season of my team to move in yet")
        return built

    def moves(self, league: str, system: str) -> dict[str, Any]:
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

    def best(self, league: str, system: str, solve: bool = False) -> dict[str, Any]:
        """The landing grid's best move (#108): from the moves already solved today, or, with
        ``solve``, solved now. Without it nothing is solved: a cold league says so."""
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
    def strategy(self, league: str, system: str) -> dict[str, Any]:
        """Today's strategy run on the league's current inputs; never solves."""
        self._base(league)
        today = nba_today(self.clock())
        run = self.strategy_runs.get(league, system, today, self._moves_stamp(league))
        if run is None:
            return {"league": league, "status": "not_solved", "system": system}
        return {"league": league, **run.payload()}

    def solve_strategy(
        self,
        league: str,
        system: str,
        settings: season_strategy.Settings,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Start the strategy run with ``settings`` (or find it), and its payload so far."""
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

    def matchup(self, league: str, system: str) -> dict[str, Any]:
        """The Matchup view (#116): my matchup's scoreboard and what each player adds to it."""
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

    def outlook(self, league: str, system: str) -> dict[str, Any]:
        """The Season view (#116): every week left of my season as win odds, each with its
        scoreboard and what my players add to it."""
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

    def lineup(self, league: str, system: str, week: int | None) -> dict[str, Any]:
        """The Lineup view (#107): my recommended starters for each day of ``week`` (this one
        by default) against Yahoo's lineup as read."""
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

    def move_detail(self, league: str, add: int, drop: int | None, system: str) -> dict[str, Any]:
        out = season_moves.detail_payload(self._built(league, system), add, drop)
        if out is None:
            raise HTTPException(404, f"no move adds {add} for {drop or 'nobody'} in {league}")
        return out

    # ------------------------------------------------------------------ trades
    def _trade_league(self, league: str, system: str) -> season_trades.TradeLeague:
        base, _ = self._base(league)
        today = nba_today(self.clock())
        key = (league, system, "trade", today, self._moves_stamp(league))

        def make() -> season_trades.TradeLeague | None:
            season = Season.from_parts(base, load_parts(self.data_dir, league))
            return season_trades.build(season, today, self.data_dir, system)

        built = self.moves_cache.get(key, make)
        if built is None:
            raise HTTPException(409, f"league {league} has no season of my team to trade in yet")
        return built

    def trade(self, league: str, body: TradeBody) -> dict[str, Any]:
        built = self._trade_league(league, body.system)
        try:
            return season_trades.evaluate(
                built, body.team, body.give, body.get, body.effective, nba_today(self.clock())
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
            # The private league's lineup pages (#107): its settings page until read, and my
            # team page shown for each day of this week from today.
            lineup_pages = [] if is_public else _lineup_pages(season, calendar, today)
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
            )
            folder = season_dir(self.data_dir, league)
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
            save(self.data_dir, league, parts, [part], part.source)

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

            received = public.refresh_parts(
                league, base, fetch, today, progress=progress, warn=job.warnings.__setitem__
            )
            settings = base.merged(next(p.data for p in received if p.key == "settings"))
            job.step = "calendar"
            calendar = self._calendar(league, settings, fetch, today)
            job.step = "pairs"
            weeks = self._unpaired(league, base, received, calendar, today)
            received += public.pairings_parts(
                league, weeks, fetch, step=lambda step: setattr(job, "step", step)
            )
            job.step = "lineups"
            received += (
                public.lineup_parts(
                    league,
                    base.my_team_id,
                    self._lineup_days(league, base.my_team_id, calendar, today),
                    fetch,
                    step=lambda step: setattr(job, "step", step),
                )
                if base.my_team_id is not None
                else []
            )
            job.step = "schedule"
            self._save_with_schedule(league, received, calendar, fetch, today)
            job.step = "flag inputs"
            self._record_adds(league, today)
            self._flag_inputs(job, fetch, today)
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

    def _lineup_days(
        self, league: str, team: int | None, calendar: Calendar | None, today: date
    ) -> list[date]:
        """The days of this week whose lineup a refresh reads: each day before today once, today
        and the days after it every time (#107)."""
        week = calendar.week_of(today) if calendar is not None else None
        if week is None or team is None:
            return []
        parts = load_parts(self.data_dir, league)
        return [d for d in week.days() if d >= today or lineup_key(team, d) not in parts]

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
            parts = merge_part(
                parts, Part("calendar", datetime.now(UTC), PUBLIC, calendar.to_dict())
            )
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
            received.append(Part("calendar", datetime.now(UTC), PUBLIC, calendar.to_dict()))
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
            received.append(Part("schedule", datetime.now(UTC), PUBLIC, {"days": {**old, **read}}))
            for part in received:
                parts = merge_part(parts, part)
            save(self.data_dir, league, parts, received, PUBLIC)

    # ------------------------------------------------------------------ a private league's extras
    def start_extras(self, league: str) -> RefreshJob | None:
        """A private league's public parts, in the background, when its season lacks them or
        its schedule is older than :data:`nba_schedule.MAX_AGE`: the week calendar (the shared
        cache a public league's refresh writes; no page of a private league answers the probe)
        and the NBA schedule. Its Yahoo pages come from the extension's snapshots."""
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
            self._save_with_schedule(job.league, [], self._cached_calendar(), fetch, today)
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
            at = page.fetched_at or datetime.now(UTC)
            try:
                received.extend(_page_parts(league, page.url, page.html, at, today))
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
        if any(p.key == "available" for p in received):
            self._record_adds(league, today)
        summary = self.summary(league)
        if received and not is_public:
            self.start_extras(league)
        return {"accepted": [p.key for p in received], "skipped": skipped, "season": summary}


#: The skip reasons the public digest prints as they are; any other reads as a failure.
NO_SEASON = "no season read yet"


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


def _lineup_pages(season: Season, calendar: Calendar | None, today: date) -> list[str]:
    """The pages a private league's lineups need from the user's Chrome: the settings page
    until it was read, and my team page shown for each day of this week from today."""
    s = season.settings
    out = [] if s.held_from == SLOTS_PAGE else [public.settings_page_url(s.league)]
    week = calendar.week_of(today) if calendar is not None else None
    if week is not None and s.my_team_id is not None:
        out += [public.team_url(s.league, s.my_team_id, d) for d in week.days(today)]
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
    system: str = Field("bbm", pattern="^(bbm|yahoo)$")
    #: The day the trade takes effect; by default when Yahoo would process it if accepted today.
    effective: date | None = None


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

    system_q = Query("bbm", pattern="^(bbm|yahoo)$", description="the projection system")
    from_q = Query(None, alias="from", description="the first day; a week before the last")
    to_q = Query(None, alias="to", description="the last day; today")

    @app.get("/seasons/{league}/moves")
    async def get_moves(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """Every available player's best move on both horizons and the recommended moves."""
        return await asyncio.to_thread(service.moves, league, system)

    @app.get("/seasons/{league}/best")
    async def get_best(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """The best recommended move when today's moves are solved; never solves them."""
        return await asyncio.to_thread(service.best, league, system)

    @app.post("/seasons/{league}/best")
    async def post_best(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """Solve today's moves and give the best recommended move."""
        return await asyncio.to_thread(service.best, league, system, True)

    @app.get("/seasons/{league}/moves/{player}")
    async def get_move(
        player: int,
        league: str = league_id,
        drop: int | None = Query(None, description="the player dropped for him; none: a free spot"),
        system: str = system_q,
    ) -> dict[str, Any]:
        """The move drawer for adding ``player``."""
        return await asyncio.to_thread(service.move_detail, league, player, drop, system)

    lock_q = Query([], description="my players no move may drop")

    @app.get("/seasons/{league}/matchup")
    async def get_matchup(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """My matchup this week: the projected finals and odds per category, the matchup odds,
        and what each player of both teams adds to them (#116)."""
        return await asyncio.to_thread(service.matchup, league, system)

    @app.get("/seasons/{league}/outlook")
    async def get_outlook(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """Every week left of my season: the win odds against its opponent (or the field), the
        summary of the regular weeks, and each week's scoreboard and my players (#116)."""
        return await asyncio.to_thread(service.outlook, league, system)

    @app.get("/seasons/{league}/lineup")
    async def get_lineup(
        league: str = league_id,
        system: str = system_q,
        week: int | None = Query(
            None, description="a week of the moves' four; this one by default"
        ),
    ) -> dict[str, Any]:
        """My recommended lineup for each day of the week against Yahoo's as read (#107)."""
        return await asyncio.to_thread(service.lineup, league, system, week)

    @app.get("/seasons/{league}/decisions")
    async def get_decisions(
        league: str = league_id,
        start: date | None = from_q,
        end: date | None = to_q,
    ) -> dict[str, Any]:
        """The decision log (#125): each solve's recommended sets and my moves matched to them."""
        return await asyncio.to_thread(service.decisions, league, start, end)

    @app.get("/seasons/{league}/strategy")
    async def get_strategy(league: str = league_id, system: str = system_q) -> dict[str, Any]:
        """Today's strategy run, as far as it got; never solves."""
        return await asyncio.to_thread(service.strategy, league, system)

    @app.post("/seasons/{league}/strategy")
    async def post_strategy(
        league: str = league_id,
        system: str = system_q,
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
