"""FastAPI app: draft sessions over :class:`DraftState` with a server-sent event stream.

Sessions live in memory (a draft lasts an evening). Every mutation bumps the session version and
publishes an event, so the UI can subscribe to ``/sessions/{id}/events`` and refresh the board
whenever a pick lands, whether it came from the Yahoo poller or manual entry. Each change also
wakes the session's background solver (:mod:`.solver`), which re-plans ahead of the clock and
publishes a ``recommendation`` event when the new answer is ready.

A session's objective is the category-win curve by default (``objective: win``), with the
curve's mean and spread taken from the simulated league of the 2026-09-23 study, from a JSON
file, or fitted from the session's own survival simulation. Availability comes from the ADP
formula unless a survival table is simulated at setup or loaded from a file.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..availability.adp import SPREAD_BASE, SPREAD_GROWTH
from ..availability.league import LEAGUE_FROM_ADP, LeagueSurvivalTable
from ..availability.survival import SurvivalTable
from ..draft import (
    STRATEGIES,
    DraftState,
    KeeperInvalid,
    KeeperLogged,
    LeagueSettings,
    Strategy,
    simulate,
)
from ..draft.league_sim import simulate_league
from ..fidelity import FidelityLog, analyze, last_attach, markdown, read_events
from ..fidelity import status as fidelity_status
from ..optim.objective import CategoryCurve
from ..optim.roster import Slot, yahoo_default_slots
from ..projections.adp import adp_for_projections, load_adp
from ..projections.positions import apply_positions, load_positions
from ..projections.schema import Cat, ProjectionSet
from ..sources.bbm import PROJECTION_SUFFIXES, load_bbm
from ..sources.matching import load_aliases
from ..sources.yahoo import YahooLeague, build_id_map, load_players_file
from . import yahoo_room
from .keepers import (
    KeeperIn,
    Labelled,
    keeper_error,
    keeper_params,
    keeper_rows,
    listed,
    read_keepers_file,
    resolve_keepers,
)
from .solver import BackgroundSolver, SolveParams, compute_recommendation, solver_executor
from .yahoo_feed import LeagueFactory, SeatRefused, YahooFeed, attach_feed
from .yahoo_room import YahooRoom

LOG = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
KEEPALIVE_SECONDS = 15.0
# Streams end on their own after this long; EventSource reconnects, the stream replays the
# board changes it missed and the UI refreshes on the next hello. Bounded streams let uvicorn
# finish a graceful shutdown or reload.
MAX_STREAM_SECONDS = 120.0
SURVIVAL_SUFFIXES = {".csv"}
CURVE_SUFFIXES = {".json"}
ADP_SUFFIXES = {".csv", ".xls", ".xlsx"}
KEEPER_SUFFIXES = {".csv"}
#: Browsers that may call the API: the dev UI, other localhost tools and the Chrome extension.
CORS_ORIGINS = r"^(chrome-extension://[a-p]{32}|https?://(localhost|127\.0\.0\.1)(:\d+)?)$"
#: The longest a room client may hold ``/plan`` for a fresh solve (the pick clock is 30 s).
PLAN_WAIT_MAX = 20.0
#: How long a room the extension reports as open and unattached stays listed (#10): it reports
#: every 3 s, so a room drops off soon after its tab closes or attaches.
SEEN_TTL_S = 30.0
#: Solver settings a room attaches with unless told otherwise: they kept solves inside a 30 s
#: clock in the 2026-09-27 mocks. The plan's time limit follows the room's pick clock
#: (:func:`yahoo_room.plan_budget`, 5 s on a 30 s clock) unless the attach gives one.
ROOM_SOLVE = {
    "n": 3,
    "scenarios": 0,
    # #13: the clock decides. Publish the plan before its prices and plan the boards my turn
    # can start on ahead of it. A shorter plan budget at my own turn stays off (0): in rounds
    # 1-6 a plan needs 6-16 s to converge, and a 3 s incumbent cost 0.72 expected category
    # wins over a settled replay (slot 6 of room 2515267).
    "early": True,
    "turn_time_limit": 0.0,
    "turn_n": 2,
    "presolve": True,
}


# --------------------------------------------------------------------------- session store
@dataclass
class Session:
    id: str
    state: DraftState
    projection_label: str
    version: int = 0
    #: One (queue, its event loop) per open event stream.
    listeners: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    yahoo: YahooFeed | None = None
    room: YahooRoom | None = None
    #: The ``POST /sessions`` body, kept so a room's log can rebuild the session.
    create_params: dict[str, Any] | None = None
    #: Guards the pick log: picks are applied and problems are built under it.
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    #: Which objective the session drafts on; the curve itself lives on the state.
    objective: str = "win"
    sigma_scale: float = 1.0
    curve_source: str = "none"
    #: Survival availability: ``mode`` none/simulate/file, ``status`` none/building/ready/failed.
    survival: dict[str, Any] = field(default_factory=lambda: {"mode": "none", "status": "none"})
    solver: BackgroundSolver | None = None
    solve_params: SolveParams = field(default_factory=SolveParams)
    recommendation: dict[str, Any] | None = None
    #: First-order deviation cost per available player from the latest plan, and the exact
    #: re-solve cost for the candidates that were priced.
    prices: pd.Series | None = field(default=None, repr=False)
    exact_prices: dict[str, float] = field(default_factory=dict, repr=False)
    prices_version: int | None = None
    #: Expected wins frozen before my first pick, and one entry per solve.
    benchmark: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def survival_building(self) -> bool:
        return self.survival.get("status") == "building"

    def score_entry(
        self,
        snapshot: dict[str, Any],
        mode: str,
        wins: float,
        value: float,
        matchups: int,
        top: str | None,
    ) -> dict[str, Any]:
        """A solve's expected categories won (and its value on the z scale), for the
        payload. ``snapshot`` is the board the solve was built on. Nothing is kept until the
        payload becomes the recommendation (:meth:`record_score`)."""
        return {
            "version": snapshot["version"],
            "next_overall": snapshot["next_overall"],
            "my_pick": snapshot["my_next_pick"],
            "on_the_clock": snapshot["on_the_clock"],
            "mode": mode,
            "wins": round(float(wins), 4),
            "value": round(float(value), 3),
            "matchups": int(matchups),
            "top": top,
            "drafted": snapshot["drafted"],
            "at": _now(),
        }

    def record_score(self, entry: dict[str, Any]) -> None:
        """Remember the score of the recommendation shown for a board, so the Team card
        agrees with the Plan and Pick cards: a later solve of the same board that does not
        displace it leaves the history alone. The benchmark is the latest one recorded before
        my first pick; after that pick it never changes."""
        state = self.state
        self.history = [h for h in self.history if h["version"] != entry["version"]] + [entry]
        self.history.sort(key=lambda h: h["version"])
        first = state.my_picks[0] if state.my_picks else None
        if first is not None and entry["next_overall"] <= first:
            self.benchmark = entry

    def set_recommendation(self, payload: dict[str, Any]) -> None:
        self.recommendation = payload
        if payload.get("score") is not None:
            self.record_score(payload["score"])
        top = payload["candidates"][0] if payload.get("candidates") else None
        self.publish(
            "recommendation",
            {
                "solved_version": payload["version"],
                "stale": payload["version"] != self.version,
                "wins": payload.get("wins"),
                "top": top["name"] if top else None,
                "top_player": top["player"] if top else None,
            },
            bump=False,
        )
        if self.room is not None:
            try:
                yahoo_room.on_recommendation(self, self.room, payload)
            except Exception:  # the log must never break a solve
                LOG.exception("could not log the solve for room %s", self.room.draft_id)

    def publish(self, event: str, data: dict[str, Any], bump: bool = True) -> None:
        """Send an event to every listener. Board changes bump the version and wake the
        background solver; transient solver progress (``bump=False``) does neither, so a
        solve never triggers itself."""
        if bump:
            self.version += 1
        payload = {"event": event, "version": self.version, "at": _now(), **data}
        if bump:
            self.log.append(payload)
        # Room picks and notes are published from worker threads (asyncio.to_thread). A queue
        # is not thread-safe there: its put would not wake the stream until the next keepalive
        # (15 s), so a pick reached the browser late. Hand it to the stream's own loop instead.
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        for queue, loop in list(self.listeners):
            if loop is here:
                queue.put_nowait(payload)
            elif not loop.is_closed():
                loop.call_soon_threadsafe(queue.put_nowait, payload)
        if bump and self.solver is not None:
            self.solver.kick(event)

    def publish_threadsafe_solve(self, update: dict[str, Any]) -> None:
        """Publish a ``solve`` progress event from a worker thread."""
        loop = self.solver.loop if self.solver is not None else None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self.publish, "solve", update, False)
        else:
            self.publish("solve", update, bump=False)


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}
        #: Yahoo draft id -> the session its room is attached to.
        self.rooms: dict[str, str] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def room(self, draft_id: str) -> tuple[YahooRoom, Session] | None:
        session = self.sessions.get(self.rooms.get(draft_id, ""))
        if session is None or session.room is None or session.room.draft_id != draft_id:
            return None
        return session.room, session

    def create(
        self,
        state: DraftState,
        projection_label: str,
        objective: str = "win",
        sigma_scale: float = 1.0,
        curve_source: str = "none",
        survival: dict[str, Any] | None = None,
        solve_ahead: bool = True,
    ) -> Session:
        session = Session(
            id=uuid.uuid4().hex[:8],
            state=state,
            projection_label=projection_label,
            objective=objective,
            sigma_scale=sigma_scale,
            curve_source=curve_source,
            survival=survival or {"mode": "none", "status": "none"},
        )
        session.solver = BackgroundSolver(session)
        session.solver.enabled = solve_ahead
        if self.loop is not None:
            session.solver.bind(self.loop)
        self.sessions[session.id] = session
        session.publish("created", {})
        return session

    def get(self, session_id: str) -> Session:
        try:
            return self.sessions[session_id]
        except KeyError:
            raise HTTPException(404, f"no session {session_id}") from None


# --------------------------------------------------------------------------- schemas
class SlotIn(BaseModel):
    name: str
    eligible: list[str] = Field(default_factory=list, description="empty means any position")


class SessionCreate(BaseModel):
    projection_file: str = Field(
        description="file name inside data/ (Basketball Monster .xls or .csv)"
    )
    positions_file: str | None = Field(
        default=None,
        description="optional file inside data/ with player names and positions (csv or xls)",
    )
    adp_file: str | None = Field(
        default=None,
        description="optional file inside data/ with player names and ADP (csv or xls)",
    )
    horizon: str = "season"
    num_teams: int = 12
    my_position: int = 1
    my_team: str = "me"
    slots: list[SlotIn] | None = None
    bench: int = 3
    cats: list[Cat] | None = None
    objective: Literal["win", "sum"] = Field(
        default="win",
        description="win = expected categories won (the curve), sum = plain sum of z",
    )
    sigma_scale: float = Field(
        default=1.0,
        gt=0.0,
        le=5.0,
        description="multiplies the curve's spread; above one flattens it toward sum of z, below one steepens it",
    )
    curve_file: str | None = Field(
        default=None, description="optional JSON inside data/ with per-category mu and sigma"
    )
    survival: Literal["none", "simulate", "file", "league"] = Field(
        default="none",
        description="availability: ADP formula, a simulated table built now, a saved table, or "
        "the league's own survival by ADP (survival_file: adp,1..N,undrafted)",
    )
    survival_sims: int = Field(default=300, ge=10, le=5000)
    survival_file: str | None = Field(default=None, description="survival CSV inside data/")
    spread_base: float = Field(
        default=SPREAD_BASE,
        gt=0.0,
        le=20.0,
        description="the ADP model's spread of a draft slot is spread_base + spread_growth * ADP "
        "picks; it also drives the simulated drafters",
    )
    spread_growth: float = Field(default=SPREAD_GROWTH, ge=0.0, le=1.0)
    drafters: list[Strategy] | None = Field(
        default=None, description="drafter mix for the simulation (default z, adp and lp)"
    )
    fit_curve: bool = Field(
        default=True, description="with survival=simulate, take mu and sigma from the run"
    )
    solve_ahead: bool = Field(
        default=True, description="re-solve in the background after every change"
    )
    time_limit: float = Field(
        default=20.0,
        ge=1.0,
        le=600.0,
        description="seconds per plan solve; the incumbent is kept when it is hit",
    )
    keepers: list[KeeperIn] = Field(
        default_factory=list, description="keepers: team position (none: mine), round, player"
    )
    keepers_file: str | None = Field(
        default=None,
        description="CSV inside data/ with position,round,player rows (position me: mine), "
        "taken before the keepers list",
    )


class KeepersIn(BaseModel):
    keepers: list[KeeperIn]


class PickIn(BaseModel):
    team: str
    player_id: str
    overall: int | None = None


class SyncIn(BaseModel):
    picks: list[tuple[int, str, str]] = Field(description="(overall, team, player_id) triples")


class AutoPickIn(BaseModel):
    count: int | None = Field(default=None, ge=1, description="stop after this many picks")
    until_my_pick: bool = Field(default=True, description="stop when my team is on the clock")
    noise: float = Field(default=1.0, ge=0.0, le=3.0, description="0 = no randomness")
    seed: int | None = None
    strategy: Strategy = Field(
        default="z",
        description="z = best total z, adp = noisy ADP slot, lp = each team's own roster model",
    )


class YahooAttach(BaseModel):
    league_id: str
    interval: float = Field(default=8.0, ge=2.0, le=120.0)
    start: bool = True


class RoomAttach(BaseModel):
    """Attach a Yahoo draft room, or resume one from its fidelity log. Fields left out on a
    resume come from the log's attach record."""

    draft_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$", description="Yahoo draft id")
    slot: int | None = Field(default=None, ge=1, le=20, description="my draft slot in the room")
    mode: Literal["mirror", "autopilot"] | None = Field(
        default=None,
        description="mirror the room (default) or let pickandroll draft when armed; left out on a "
        "rebuild, the mode last set since the last detach; ignored when the room is live (PATCH "
        "sets it)",
    )
    num_teams: int | None = Field(default=None, ge=2, le=20)
    room_teams: int | None = Field(
        default=None,
        ge=2,
        le=20,
        description="the room's own team count, as its client or the waiting room shows it: an "
        "attach whose team count disagrees is refused (422) before anything is built",
    )
    players_file: str | None = Field(
        default=None, description="Yahoo players JSON in data/ (default: newest yahoo_players_*)"
    )
    session_id: str | None = Field(default=None, description="attach to this session")
    session: SessionCreate | None = Field(
        default=None, description="or create a session with these settings"
    )
    ext_version: str | None = Field(
        default=None,
        max_length=32,
        description="the extension's version, when it attaches: written to the attach record",
    )
    n: int | None = Field(default=None, ge=1, le=30, description="candidates priced per solve")
    scenarios: int | None = Field(default=None, ge=0, le=8)
    time_limit: float | None = Field(
        default=None, ge=1.0, le=600.0, description="plan budget (default: from clock_s)"
    )
    clock_s: float | None = Field(
        default=None, ge=10.0, le=600.0, description="the room's seconds per pick (default 30)"
    )
    early: bool | None = Field(default=None, description="publish the plan before its prices")
    turn_time_limit: float | None = Field(
        default=None, ge=0.0, le=600.0, description="plan budget at my own turn (0: time_limit)"
    )
    turn_n: int | None = Field(default=None, ge=1, le=30)
    presolve: bool | None = Field(
        default=None, description="plan the boards my turn can start on before it starts"
    )


class RoomPickIn(BaseModel):
    overall: int = Field(
        description="outside 1..num_teams x rounds: dropped and counted, not refused"
    )
    yahoo_player_id: str | int | None = None
    label: str | None = Field(default=None, description='Board label, "F. Last", with team')
    team: str | None = None
    slot: int | None = Field(default=None, ge=1, le=20)
    t_room: float | str | None = Field(
        default=None, description="when the room message arrived: epoch ms or ISO-8601"
    )
    src: str | None = Field(default=None, description="socket, history or board")


class RoomPicks(BaseModel):
    picks: list[RoomPickIn]


class RoomEvents(BaseModel):
    events: list[dict[str, Any]]


class RoomPatch(BaseModel):
    """What the user sets for a room; a field left out keeps its value (at least one)."""

    mode: Literal["mirror", "autopilot"] | None = Field(
        default=None, description="left out, the room keeps its mode; null is refused (422)"
    )
    act_at_s: int | None = Field(
        default=None,
        ge=yahoo_room.ACT_AT_MIN_S,
        le=yahoo_room.ACT_AT_MAX_S,
        description="armed: act when the clock is down to this many seconds, unless I pick "
        "first; null: at once. Left out, the room keeps its setting",
    )


class RoomSeen(BaseModel):
    """A draft room open in the user's Chrome that no session follows yet, as the extension's
    draft tab sees it."""

    draft_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    slot: int | None = Field(default=None, ge=1, le=20, description="my slot, once the room says")
    room_teams: int | None = Field(
        default=None, ge=2, le=20, description="the room's team count, once its picks show it"
    )


class DraftRequest(BaseModel):
    """The user's "Draft in Yahoo" from the web app: this player for my pick on the clock."""

    overall: int = Field(ge=1)
    board: int = Field(ge=0, description="the session's picks the request was made on")
    yahoo_player_id: str


class AliasPin(BaseModel):
    yahoo_player_id: str
    player_id: str


RecommendQuery = SolveParams


# --------------------------------------------------------------------------- app
def create_app(
    store: SessionStore | None = None,
    data_dir: Path | None = None,
    league_factory: LeagueFactory | None = None,
    fidelity_dir: Path | None = None,
) -> FastAPI:
    store = store or SessionStore()
    data_dir = data_dir or DATA_DIR
    fidelity_dir = fidelity_dir or data_dir / "fidelity"
    league_factory = league_factory or (lambda league_id: YahooLeague(league_id))
    shutdown = asyncio.Event()
    rooms_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        shutdown.clear()
        loop = asyncio.get_running_loop()
        app.state.loop = loop
        store.loop = loop
        for session in store.sessions.values():
            if session.solver is not None:
                session.solver.bind(loop)
        yield
        shutdown.set()  # wakes every open event stream so the server can exit
        for session in store.sessions.values():
            if session.yahoo and session.yahoo.task:
                session.yahoo.task.cancel()
            if session.solver is not None:
                session.solver.enabled = False

    app = FastAPI(title="pickandroll", version="0.2.0", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "time": _now()}

    @app.get("/projections")
    def list_projections() -> list[dict[str, Any]]:
        # A keepers CSV is never a projection: left out, it cannot become the default.
        files = _list_files(data_dir, PROJECTION_SUFFIXES)
        return [f for f in files if "keeper" not in f["file"].lower()]

    names_cache: dict[tuple[str, float], list[dict[str, str]]] = {}

    @app.get("/projections/players")
    def projection_players(file: str) -> list[dict[str, str]]:
        """A projection file's players (id, name, team) by name, for the setup screen's keeper
        typeahead before a session exists. Cached per file version."""
        path = data_dir / file
        if (
            not _in_data_dir(file)
            or not path.is_file()
            or path.suffix.lower() not in PROJECTION_SUFFIXES
        ):
            raise HTTPException(400, f"projection file not found: {file}")
        key = (file, path.stat().st_mtime)
        if key not in names_cache:
            try:
                df = load_bbm(path).df
            except ValueError as exc:
                raise HTTPException(400, f"could not parse {file}: {exc}") from exc
            names_cache.clear()
            names_cache[key] = sorted(
                (
                    {"player_id": str(pid), "name": str(row["player"]), "team": str(row["team"])}
                    for pid, row in df[["player", "team"]].iterrows()
                ),
                key=lambda r: r["name"],
            )
        return names_cache[key]

    @app.get("/files")
    def list_files(
        kind: Literal["survival", "league", "curve", "adp", "keepers"] = "survival",
    ) -> list[dict[str, Any]]:
        """Saved survival tables (CSV with a ``.sims`` sidecar), league survival tables (a CSV
        headed ``adp,1..N,undrafted``, in data/ or one folder down), curve files (JSON), ADP
        files (a csv/xls whose name contains ``adp``) or keeper tables (a csv whose name
        contains ``keeper``) in data/."""
        if kind == "league":
            return _league_tables(data_dir)
        if kind == "survival":
            files = _list_files(data_dir, SURVIVAL_SUFFIXES)
            return [f for f in files if (data_dir / (f["file"] + ".sims")).exists()]
        if kind == "adp":
            files = _list_files(data_dir, ADP_SUFFIXES)
            return [f for f in files if "adp" in f["file"].lower()]
        if kind == "keepers":
            files = _list_files(data_dir, KEEPER_SUFFIXES)
            return [f for f in files if "keeper" in f["file"].lower()]
        return _list_files(data_dir, CURVE_SUFFIXES)

    @app.get("/keepers-file")
    def keepers_file(file: str) -> dict[str, Any]:
        """A keepers CSV's rows as written (players by name, position null for mine), for the
        setup screen to offer before a session exists."""
        return {
            "file": file,
            "rows": [
                {"label": label, **row.model_dump()}
                for label, row in _keepers_file_rows(data_dir, file)
            ],
        }

    @app.post("/sessions", status_code=201)
    async def create_session(body: SessionCreate) -> dict[str, Any]:
        return _summary(await make_session(body))

    async def make_session(body: SessionCreate) -> Session:
        state, label, curve_source = await asyncio.to_thread(_build_state, body, data_dir)
        survival: dict[str, Any] = {"mode": body.survival, "status": "none"}
        if body.survival == "league":
            if not body.survival_file:
                raise HTTPException(400, "survival=league needs survival_file")
            path = data_dir / body.survival_file
            if not path.exists():
                raise HTTPException(400, f"survival file not found: {body.survival_file}")
            try:
                league = await asyncio.to_thread(_load_league_survival, path)
            except (OSError, ValueError) as exc:
                raise HTTPException(400, f"could not read {path.name}: {exc}") from exc
            if league.picks < state.settings.total_picks:
                raise HTTPException(
                    400,
                    f"{path.name} covers {league.picks} picks, the draft has "
                    f"{state.settings.total_picks}",
                )
            state.league_survival = league
            survival = {
                "mode": "league",
                "status": "ready",
                "source": f"league:{path.name}",
                "from_adp": LEAGUE_FROM_ADP,
                "max_adp": league.max_adp,
            }
        elif body.survival == "file":
            if not body.survival_file:
                raise HTTPException(400, "survival=file needs survival_file")
            path = data_dir / body.survival_file
            if not path.exists():
                raise HTTPException(400, f"survival file not found: {body.survival_file}")
            try:
                table = await asyncio.to_thread(SurvivalTable.load, path)
            except (OSError, ValueError) as exc:
                raise HTTPException(400, f"could not read {path.name}: {exc}") from exc
            if table.total_picks != state.settings.total_picks:
                raise HTTPException(
                    400,
                    f"{path.name} covers {table.total_picks} picks, the draft has "
                    f"{state.settings.total_picks}",
                )
            state.survival = table
            survival = {
                "mode": "file",
                "status": "ready",
                "sims": table.sims,
                "source": f"file:{path.name}",
            }
        elif body.survival == "simulate":
            drafters = tuple(body.drafters) if body.drafters else STRATEGIES
            if any(d not in STRATEGIES for d in drafters):
                raise HTTPException(400, f"drafters must be drawn from {STRATEGIES}")
            survival = {
                "mode": "simulate",
                "status": "building",
                "sims": body.survival_sims,
                "done": 0,
                "drafters": list(drafters),
                "source": None,
            }
        session = store.create(
            state,
            label,
            objective=body.objective,
            sigma_scale=body.sigma_scale,
            curve_source=curve_source,
            survival=survival,
            solve_ahead=body.solve_ahead,
        )
        # The keeper table as resolved, by id: a rebuild after a restart does not re-read the file.
        session.create_params = {
            **body.model_dump(mode="json"),
            "keepers": keeper_params(state.keepers),
            "keepers_file": None,
        }
        if body.survival == "simulate":
            asyncio.get_running_loop().create_task(
                _build_survival(session, body.survival_sims, drafters, body.fit_curve)
            )
        return session

    @app.get("/sessions")
    def list_sessions() -> list[dict[str, Any]]:
        return [_summary(s) for s in store.sessions.values()]

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        return _summary(store.get(session_id))

    @app.get("/sessions/{session_id}/board")
    def board(session_id: str, limit: int = 300) -> dict[str, Any]:
        session = store.get(session_id)
        state = session.state
        z = state.z
        df = state.projections.df
        with session.lock:
            taken = state.taken
            kept = {k["player_id"]: k["team"] for k in keeper_rows(state)}
            adp = state.effective_adp()
            ahead = state.keepers_ahead(adp)
            adp_eff = adp - ahead
            # Odds each player lasts to my next pick after the current one (the board's
            # question while I am on the clock is "can I wait on this player?").
            future = [k for k in state.my_remaining_picks if k > state.next_overall]
            next_pick = future[0] if future else None
            p_next = state.availability()[next_pick] if next_pick is not None else None
            priced = session.prices_version == session.version
            prices = session.prices if priced else None
            exact = session.exact_prices if priced else {}
        rows = []
        for pid in z["total"].sort_values(ascending=False).index[:limit]:
            rows.append(
                {
                    "player_id": pid,
                    "name": df.at[pid, "player"],
                    "team": df.at[pid, "team"],
                    "positions": df.at[pid, "positions"],
                    "games": float(df.at[pid, "games"]),
                    "adp": _float_or_none(adp.get(pid)),
                    # Keeper-adjusted: the market reaches him this many picks sooner.
                    "adp_eff": _float_or_none(adp_eff.get(pid)),
                    "keepers_ahead": int(ahead.get(pid, 0)),
                    "p_next": _float_or_none(p_next.get(pid)) if p_next is not None else None,
                    # The exact re-solve cost where a candidate was priced, else the
                    # first-order estimate from the plan's slopes.
                    "cost": (
                        _float_or_none(exact[pid])
                        if pid in exact
                        else _float_or_none(prices.get(pid))
                        if prices is not None
                        else None
                    ),
                    "cost_exact": pid in exact,
                    "z": {
                        c.value: round(float(z.at[pid, c.value]), 3) for c in state.settings.cats
                    },
                    "total": round(float(z.at[pid, "total"]), 3),
                    "taken": pid in taken,
                    "keeper": kept.get(pid),
                }
            )
        return {
            "version": session.version,
            "next_pick": next_pick,
            "prices_version": session.prices_version if prices is not None else None,
            "scale": (session.recommendation or {}).get("scale") if prices is not None else None,
            "players": rows,
        }

    @app.get("/sessions/{session_id}/picks")
    def picks(session_id: str) -> list[dict[str, Any]]:
        session = store.get(session_id)
        return [_pick_row(session.state, p) for p in session.state.picks]

    @app.post("/sessions/{session_id}/picks", status_code=201)
    def add_pick(session_id: str, body: PickIn) -> dict[str, Any]:
        session = store.get(session_id)
        with session.lock:
            before = len(session.state.picks)
            try:
                pick = session.state.apply_pick(body.team, body.player_id, body.overall)
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
            row = _pick_row(session.state, pick)
            # The pick and the keeper picks logged after it.
            rows = [_pick_row(session.state, p) for p in session.state.picks[before:]]
        for logged in rows:
            session.publish("pick", {"pick": logged})
        return row

    @app.post("/sessions/{session_id}/sync")
    def sync(session_id: str, body: SyncIn) -> dict[str, Any]:
        session = store.get(session_id)
        with session.lock:
            before = len(session.state.picks)
            try:
                session.state.sync(body.picks)
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
            # The feed's new picks and the keeper picks logged on the way.
            rows = [_pick_row(session.state, p) for p in session.state.picks[before:]]
        for row in rows:
            session.publish("pick", {"pick": row})
        return {"added": rows, "version": session.version}

    @app.delete("/sessions/{session_id}/picks/last")
    def undo_pick(session_id: str) -> dict[str, Any]:
        """Take back the last real pick and the keeper picks logged after it (they come back
        when the draft reaches their slots again)."""
        session = store.get(session_id)
        with session.lock:
            try:
                undone = session.state.undo()
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            row, *kept = [_pick_row(session.state, p) for p in undone]
        session.publish("undo", {"pick": row, "keepers": kept})
        return {**row, "keepers_undone": kept}

    @app.patch("/sessions/{session_id}/keepers")
    def set_keepers(session_id: str, body: KeepersIn) -> dict[str, Any]:
        """Replace the keeper table: all of it before the first pick, then the slots the draft
        has not reached (409 for a change to a keeper already in the log). In a room, a keeper
        may also name the player at a gap, a pick the room never sent: he replaces the
        stand-in there (docs/KEEPERS.md §2)."""
        session = store.get(session_id)
        room = session.room
        with room.lock if room is not None else contextlib.nullcontext():
            with session.lock:
                state = session.state
                rows = listed(body.keepers)
                gaps = yahoo_room.gap_standins(room) if room is not None else {}
                try:
                    state.set_keepers(
                        resolve_keepers(rows, state.projections.df), fixable=frozenset(gaps)
                    )
                except KeeperLogged as exc:
                    raise HTTPException(409, str(exc)) from exc
                except KeeperInvalid as exc:
                    raise HTTPException(400, keeper_error(rows, exc)) from exc
                except ValueError as exc:
                    raise HTTPException(400, str(exc)) from exc
                if session.create_params is not None:
                    session.create_params = {
                        **session.create_params,
                        "keepers": keeper_params(state.keepers),
                        "keepers_file": None,
                    }
                table = keeper_rows(state)
            changes = yahoo_room.keepers_fixed(session, room, gaps) if room is not None else []
        if room is not None:
            yahoo_room.publish_changes(session, room, changes)
        session.publish("keepers", {"keepers": table})
        return {"keepers": table, "version": session.version}

    @app.post("/sessions/{session_id}/autopick")
    def autopick(session_id: str, body: AutoPickIn) -> dict[str, Any]:
        """Auto-pick for the other teams (draft simulation) until my pick or ``count`` picks."""
        session = store.get(session_id)
        if session.state.complete:
            raise HTTPException(400, "draft is complete")
        if body.until_my_pick and body.count is None and session.state.on_the_clock:
            raise HTTPException(400, "you are on the clock; make your pick first")
        with session.lock:
            before = len(session.state.picks)
            simulate(
                session.state,
                count=body.count,
                until_my_pick=body.until_my_pick,
                noise=body.noise,
                seed=body.seed,
                strategy=body.strategy,
            )
            # The simulated picks and the keeper picks logged on the way.
            rows = [_pick_row(session.state, p) for p in session.state.picks[before:]]
        for row in rows:
            session.publish("pick", {"pick": row})
        return {"added": rows, "version": session.version}

    @app.post("/sessions/{session_id}/recommend")
    def recommend(session_id: str, body: RecommendQuery) -> dict[str, Any]:
        """Solve now and wait for the answer: next-pick candidates priced with the risk of
        waiting, the plan for every remaining pick, the category report and the league tally.

        The background solver produces the same payload after every change; this endpoint is
        for clients that want a synchronous answer. It falls back to the single-roster model
        when my remaining picks and open slots disagree.
        """
        session = store.get(session_id)
        session.solve_params = body
        try:
            payload = compute_recommendation(session, body, session.publish_threadsafe_solve)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.set_recommendation(payload)
        return payload

    @app.post("/sessions/{session_id}/solve", status_code=202)
    def solve(session_id: str, body: RecommendQuery) -> dict[str, Any]:
        """Queue a background solve with these settings; the result arrives as a
        ``recommendation`` event and at ``/recommendation``."""
        session = store.get(session_id)
        session.solve_params = body
        if not session.state.my_remaining_picks:
            raise HTTPException(400, "you have no picks left; the final score is at /score")
        queued = session.solver.kick("manual", force=True) if session.solver else False
        return {"queued": queued, "version": session.version, "solver": _solver_status(session)}

    @app.get("/sessions/{session_id}/recommendation")
    def recommendation(session_id: str) -> dict[str, Any]:
        """The latest solve (possibly for an earlier board: compare ``solved_version``)."""
        session = store.get(session_id)
        payload = session.recommendation
        return {
            "version": session.version,
            "solved_version": payload["version"] if payload else None,
            "stale": payload is not None and payload["version"] != session.version,
            "solver": _solver_status(session),
            "recommendation": payload,
        }

    @app.get("/sessions/{session_id}/teams")
    def teams(session_id: str) -> dict[str, Any]:
        """Every team's drafted category totals and projected finals, and the head-to-head
        tally of my expected finals against each of them."""
        session = store.get(session_id)
        state = session.state
        rec = session.recommendation
        with session.lock:
            my_final = None
            if rec is not None and rec["version"] == session.version:
                my_final = rec["best_roster"]["cat_totals"]
            totals = state.team_totals()
            projected = state.projected_finals(my_final)
            tally = state.matchups(my_final)
        by_team = {o["team"]: o for o in tally["opponents"]}
        cats = [c.value for c in state.settings.cats]
        rows = []
        for team, row in totals.iterrows():
            opp = by_team.get(team)
            rows.append(
                {
                    "team": team,
                    "position": int(row["position"]),
                    "picks": int(row["picks"]),
                    "mine": team == state.my_team,
                    "totals": {c: round(float(row[c]), 3) for c in cats},
                    "projected": {c: round(float(projected.at[team, c]), 3) for c in cats},
                    "cats_beaten": opp["cats_beaten"] if opp else None,
                    "won": opp["won"] if opp else None,
                    "leads": opp["leads"] if opp else [],
                }
            )
        rows.sort(key=lambda r: r["position"])
        return {
            "version": session.version,
            "cats": cats,
            "my_final_from": "plan" if my_final is not None else "replacement fill",
            "teams": rows,
            "matchups_won": tally["matchups_won"],
            "cats_beaten": round(float(tally["cats_beaten"]), 3),
            "teams_beaten": tally["teams_beaten"],
        }

    @app.get("/sessions/{session_id}/solver")
    def solver_status(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        return {**_solver_status(session), "survival": session.survival}

    @app.get("/sessions/{session_id}/score")
    def score(session_id: str) -> dict[str, Any]:
        """Expected categories won before my first pick (the benchmark), the best plan seen
        during the draft, the latest, and the final roster's realized odds and league tally."""
        session = store.get(session_id)
        with session.lock:
            return _score(session)

    @app.get("/sessions/{session_id}/events")
    async def events(session_id: str, request: Request) -> StreamingResponse:
        """Server-sent events: one ``hello`` on connect, then ``pick`` / ``undo`` / ``created``
        / ``survival`` / ``solve`` / ``recommendation``, and for a Yahoo room ``room_attached``
        / ``room_mode`` / ``room_detached`` / ``room_event`` (a client event, heartbeats aside).

        A comment line is sent every ``KEEPALIVE_SECONDS`` so proxies keep the connection open.

        Every event carries the session version as its id. A stream ends after
        ``MAX_STREAM_SECONDS`` and EventSource reconnects with ``Last-Event-ID``: the board
        changes logged since that version are sent again after the ``hello``, so the picks of a
        simulation that lands while the browser reconnects are still announced.
        """
        session = store.get(session_id)
        queue: asyncio.Queue = asyncio.Queue()
        listener = (queue, asyncio.get_running_loop())
        session.listeners.append(listener)
        # Listening before reading the log: a change published in between is in both, and the
        # queue's copy is skipped.
        missed = _missed(session, request.headers.get("last-event-id"))
        replayed = {id(p) for p in missed}

        def send(payload: dict[str, Any]) -> str | None:
            if id(payload) in replayed:
                return None
            return _sse(payload["event"], payload, event_id=payload["version"])

        async def stream():
            stop = asyncio.ensure_future(shutdown.wait())
            started = asyncio.get_running_loop().time()
            try:
                yield _sse("hello", {"version": session.version})
                for payload in missed:
                    yield _sse(payload["event"], payload, event_id=payload["version"])
                while not shutdown.is_set() and not await request.is_disconnected():
                    if asyncio.get_running_loop().time() - started > MAX_STREAM_SECONDS:
                        # Hand over what is queued first: a burst of picks used to lose all
                        # but its first here.
                        while not queue.empty():
                            if (line := send(queue.get_nowait())) is not None:
                                yield line
                        yield _sse("reconnect", {"version": session.version})
                        break
                    getter = asyncio.ensure_future(queue.get())
                    done, _pending = await asyncio.wait(
                        {getter, stop},
                        timeout=KEEPALIVE_SECONDS,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if getter in done:
                        if (line := send(getter.result())) is not None:
                            yield line
                    else:
                        getter.cancel()
                        if stop in done:
                            yield _sse("bye", {"reason": "server shutting down"})
                            break
                        yield ": keepalive\n\n"
            finally:
                stop.cancel()
                session.listeners.remove(listener)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ yahoo feed
    @app.post("/sessions/{session_id}/yahoo", status_code=201)
    async def yahoo_attach(session_id: str, body: YahooAttach) -> dict[str, Any]:
        session = store.get(session_id)
        if session.room is not None:
            raise HTTPException(409, f"session follows Yahoo room {session.room.draft_id}")
        if session.yahoo and session.yahoo.running:
            session.yahoo.task.cancel()
        try:
            league = league_factory(body.league_id)
            feed = await asyncio.to_thread(
                attach_feed, session, league, body.interval, data_dir / "aliases.json"
            )
        except SeatRefused as exc:
            raise HTTPException(400, f"yahoo: {exc}") from exc
        except Exception as exc:
            raise HTTPException(502, f"yahoo: {exc}") from exc
        session.yahoo = feed
        if body.start:
            feed.task = asyncio.create_task(feed.run(session))
        return {**feed.status(), "session": _summary(session)}

    @app.get("/sessions/{session_id}/yahoo")
    def yahoo_status(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        if session.yahoo is None:
            return {"attached": False}
        return session.yahoo.status()

    @app.post("/sessions/{session_id}/yahoo/poll")
    async def yahoo_poll(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        if session.yahoo is None:
            raise HTTPException(400, "no yahoo feed attached")
        try:
            applied = await asyncio.to_thread(session.yahoo.poll_once, session)
        except Exception as exc:
            raise HTTPException(502, f"yahoo: {exc}") from exc
        return {"applied": applied, **session.yahoo.status()}

    @app.delete("/sessions/{session_id}/yahoo")
    def yahoo_detach(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        if session.yahoo and session.yahoo.task:
            session.yahoo.task.cancel()
        session.yahoo = None
        return {"attached": False}

    # ------------------------------------------------------------------ yahoo draft room
    def room_log(draft_id: str) -> FidelityLog:
        try:
            return FidelityLog(fidelity_dir, draft_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def players_path(name: str | None) -> Path:
        if name:
            if name != Path(name).name or name in {".", ".."} or "\\" in name:
                raise HTTPException(400, f"players_file must be a file name in data/: {name!r}")
            path = data_dir / name
            if not path.exists():
                raise HTTPException(400, f"players file not found: {name}")
            return path
        files = sorted(data_dir.glob("yahoo_players_*.json"), key=lambda f: f.stat().st_mtime)
        if not files:
            raise HTTPException(400, "no yahoo_players_*.json in data/; pass players_file")
        return files[-1]

    async def open_room(body: RoomAttach) -> tuple[YahooRoom, Session]:
        """Attach a room, or return the live one, or rebuild one from its log."""
        async with rooms_lock:
            live = store.room(body.draft_id)
            if live is not None:
                room, session = live
                if body.slot is not None and body.slot != room.slot:
                    raise HTTPException(
                        409, f"room {room.draft_id} is attached for slot {room.slot}"
                    )
                if body.session_id is not None and body.session_id != session.id:
                    raise HTTPException(
                        409, f"room {room.draft_id} is attached to session {session.id}"
                    )
                if body.room_teams is not None and body.room_teams != room.num_teams:
                    raise HTTPException(
                        422,
                        f"room {room.draft_id} has {body.room_teams} teams but is attached "
                        f"for {room.num_teams}",
                    )
                return room, session
            log = room_log(body.draft_id)
            prior = await asyncio.to_thread(log.read)
            record = last_attach(prior) or {}
            if body.room_teams is not None:
                # Before any session is made or solve started: a session for the wrong number
                # of teams credits the room's picks to the wrong teams (mock 2).
                said = {
                    t
                    for t in (
                        body.num_teams,
                        body.session.num_teams if body.session is not None else None,
                        store.get(body.session_id).state.settings.num_teams
                        if body.session_id is not None
                        else None,
                        (record.get("session") or {}).get("num_teams")
                        if body.session is None and body.session_id is None
                        else None,
                    )
                    if t is not None
                }
                if said and said != {body.room_teams}:
                    raise HTTPException(
                        422,
                        f"the room has {body.room_teams} teams but the attach says "
                        f"{', '.join(str(t) for t in sorted(said))}",
                    )
            if body.session_id is not None:
                session = store.get(body.session_id)
            elif body.session is not None:
                session = await make_session(body.session)
            elif record.get("session"):
                session = await make_session(SessionCreate(**record["session"]))
            else:
                raise HTTPException(
                    400, "no session: pass session_id or session settings (no log to resume from)"
                )
            if session.yahoo is not None:
                raise HTTPException(409, "session follows the Yahoo Fantasy API feed; detach it")
            if session.room is not None:
                raise HTTPException(409, f"session follows Yahoo room {session.room.draft_id}")
            solve = record.get("solve") or {}

            def option(name: str, default: Any) -> Any:
                value = getattr(body, name)
                if value is not None:
                    return value
                return record.get(name, solve.get(name, default))

            slot = option("slot", None)
            if slot is None:
                raise HTTPException(400, "slot is required")
            turn_limit = float(option("turn_time_limit", ROOM_SOLVE["turn_time_limit"]))
            params = SolveParams(
                n=option("n", ROOM_SOLVE["n"]),
                scenarios=option("scenarios", 0),
                early=bool(option("early", ROOM_SOLVE["early"])),
                turn_time_limit=turn_limit or None,
                turn_n=option("turn_n", ROOM_SOLVE["turn_n"]),
                presolve=bool(option("presolve", ROOM_SOLVE["presolve"])),
            )
            # The plan budget follows the room's clock unless a time_limit was given (now, or
            # by the attach a resume reads; logs from before #13 always gave one).
            clock_s = option("clock_s", None)
            follow = body.time_limit is None and (
                body.clock_s is not None
                or bool(solve.get("follow_clock", "time_limit" not in solve))
            )
            if follow:
                time_limit = yahoo_room.plan_budget(clock_s)
            else:
                time_limit = float(option("time_limit", yahoo_room.plan_budget(clock_s)))
            path = players_path(option("players_file", None))
            state = session.state

            def build() -> YahooRoom:
                ids = build_id_map(
                    load_players_file(path),
                    state.projections.df,
                    load_aliases(data_dir / "aliases.json"),
                )
                session.solve_params = params
                state.plan_time_limit = time_limit
                state.price_time_limit = min(state.price_time_limit, time_limit)
                room = yahoo_room.attach_room(
                    session,
                    draft_id=body.draft_id,
                    slot=int(slot),
                    # None (a rebuild): the mode last set since the room's last detach.
                    mode=body.mode,
                    num_teams=int(option("num_teams", state.settings.num_teams)),
                    ids=ids,
                    log=log,
                    players_file=path.name,
                    prior=prior,
                    attach_record={
                        **({"ext_version": body.ext_version} if body.ext_version else {}),
                        "session": session.create_params,
                        "solve": {
                            "n": params.n,
                            "scenarios": params.scenarios,
                            "time_limit": time_limit,
                            "clock_s": clock_s,
                            "follow_clock": follow,
                            "early": params.early,
                            "turn_time_limit": params.turn_time_limit or 0.0,
                            "turn_n": params.turn_n,
                            "presolve": params.presolve,
                        },
                    },
                )
                if follow:
                    room.clock_s = float(clock_s or yahoo_room.DEFAULT_CLOCK_S)
                return room

            try:
                room = await asyncio.to_thread(build)
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
            room.loop = asyncio.get_running_loop()  # the gap checks run on it
            store.rooms[body.draft_id] = session.id
            if session.solver is not None:
                # The room's solve settings replace the session's: solve again with them (and
                # plan the boards ahead when the first turn is near).
                session.solver.kick("room")
            return room, session

    async def get_room(draft_id: str) -> tuple[YahooRoom, Session]:
        """The live room; after an API restart, the room rebuilt from its log."""
        live = store.room(draft_id)
        if live is not None:
            return live
        log = room_log(draft_id)
        if last_attach(await asyncio.to_thread(log.read)) is None:
            raise HTTPException(404, f"no room {draft_id}")
        return await open_room(RoomAttach(draft_id=draft_id))

    def room_view(room: YahooRoom, session: Session) -> dict[str, Any]:
        return {**yahoo_room.summary(session, room), "session": _summary(session)}

    @app.post("/rooms", status_code=201)
    async def attach_room(body: RoomAttach) -> dict[str, Any]:
        """Attach a Yahoo draft room to a session (``session_id``, or a new one from
        ``session``). For a draft id with a log and no live room, rebuild the room from the
        log: same session settings, the logged picks re-applied, a fresh solve."""
        room, session = await open_room(body)
        return room_view(room, session)

    @app.get("/rooms")
    def list_rooms() -> list[dict[str, Any]]:
        return [
            yahoo_room.summary(live[1], live[0])
            for draft_id in list(store.rooms)
            if (live := store.room(draft_id)) is not None
        ]

    # A room open in Chrome and not attached, for the web app to offer (#10). Registered before
    # /rooms/{draft_id} so "seen" is never read as a draft id. Never attaches anything itself.
    seen: dict[str, dict[str, Any]] = {}

    @app.post("/rooms/seen")
    def room_seen(body: RoomSeen) -> dict[str, Any]:
        seen[body.draft_id] = {**body.model_dump(), "at": time.monotonic()}
        return {"seen": body.draft_id}

    @app.get("/rooms/seen")
    def rooms_seen() -> list[dict[str, Any]]:
        """Rooms the extension reported open and unattached in the last ``SEEN_TTL_S``."""
        now = time.monotonic()
        for draft_id in [d for d, e in seen.items() if now - e["at"] >= SEEN_TTL_S]:
            del seen[draft_id]
        return [
            {**{k: v for k, v in e.items() if k != "at"}, "age_s": round(now - e["at"], 1)}
            for e in sorted(seen.values(), key=lambda e: -e["at"])
            if store.room(e["draft_id"]) is None
        ]

    @app.get("/rooms/{draft_id}")
    async def room_status(draft_id: str) -> dict[str, Any]:
        room, session = await get_room(draft_id)
        return room_view(room, session)

    @app.patch("/rooms/{draft_id}")
    async def room_mode(draft_id: str, body: RoomPatch) -> dict[str, Any]:
        if not {"mode", "act_at_s"} & body.model_fields_set:
            raise HTTPException(422, "nothing to set: give mode, act_at_s or both")
        if "mode" in body.model_fields_set and body.mode is None:
            # Most likely a client's stale or empty value; leaving the field out keeps the mode.
            raise HTTPException(422, "mode cannot be null: leave it out to keep the room's mode")
        room, session = await get_room(draft_id)
        if body.mode == "autopilot" and room.teams_mismatch is not None:
            # The session's draft is not the room's (#17): every plan would be for the wrong picks.
            raise HTTPException(
                409,
                f"room {draft_id} has {room.teams_mismatch} teams but is attached for "
                f"{room.num_teams}: attach a session with the room's team count before arming",
            )
        if body.mode is not None:
            room.mode = body.mode
            room.control = yahoo_room.control_for(body.mode)
        if "act_at_s" in body.model_fields_set:
            room.act_at_s = body.act_at_s
        yahoo_room.log_control(room)
        session.publish(
            "room_mode",
            {"draft_id": draft_id, "mode": room.mode, "act_at_s": room.act_at_s},
            bump=False,
        )
        return room_view(room, session)

    @app.delete("/rooms/{draft_id}")
    def room_detach(draft_id: str) -> dict[str, Any]:
        live = store.room(draft_id)
        if live is None:
            raise HTTPException(404, f"no live room {draft_id}")
        room, session = live
        room.log.append({"type": "detach", "session_id": session.id})
        session.room = None
        store.rooms.pop(draft_id, None)
        session.publish("room_detached", {"draft_id": draft_id}, bump=False)
        return {"attached": False, "draft_id": draft_id}

    @app.post("/rooms/{draft_id}/picks")
    async def room_picks(draft_id: str, body: RoomPicks) -> dict[str, Any]:
        """A batch of room picks by Yahoo id (or Board label and team). Idempotent by overall;
        resend the whole history whenever in doubt."""
        room, session = await get_room(draft_id)
        items = [p.model_dump() for p in body.picks]
        try:
            return await asyncio.to_thread(yahoo_room.ingest, session, room, items)
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/rooms/{draft_id}/plan")
    async def room_plan(
        draft_id: str,
        wait: float = Query(default=0.0, ge=0.0, le=PLAN_WAIT_MAX),
        board: int | None = Query(
            default=None,
            ge=0,
            description="Hold for the solve built on this many picks: a turn's client knows "
            "its board before the API may have applied the last pick.",
        ),
    ) -> dict[str, Any]:
        """Candidates for my next turn by Yahoo id. ``wait`` holds up to that many seconds
        (at most 20) for a solve of the current board, or of ``board`` once the session has
        applied that many picks, and starts one if none is running."""
        room, session = await get_room(draft_id)
        loop = asyncio.get_running_loop()
        started = loop.time()
        deadline = started + wait
        kicked = False
        while True:
            rec = session.recommendation
            state = session.state
            fresh = (
                rec is not None
                and rec["version"] == session.version
                and (board is None or rec["next_overall"] - 1 >= board)
            )
            if fresh or loop.time() >= deadline or not state.my_remaining_picks:
                break
            synced = board is None or state.next_overall - 1 >= board
            solver = session.solver
            if synced and solver is not None and not kicked and not solver.running:
                kicked = solver.kick("room", force=True)
            await asyncio.sleep(0.1)
        payload = await asyncio.to_thread(yahoo_room.plan, session, room)
        if board is not None and (payload["board"] is None or payload["board"] < board):
            payload["fresh"] = False  # current for the API, but older than the client's board
        return {**payload, "waited_ms": round((loop.time() - started) * 1000)}

    @app.post("/rooms/{draft_id}/events")
    async def room_events(draft_id: str, body: RoomEvents) -> dict[str, Any]:
        """Client events for the fidelity log: control, turn_start, draft_attempt,
        pick_landed, intervention, heartbeat, note. An event of another type, or one missing
        what its type needs, is dropped and counted in ``ignored``; the rest are kept."""
        room, session = await get_room(draft_id)
        written, ignored, shown = await asyncio.to_thread(
            yahoo_room.record_events, room, body.events
        )
        for event in shown:  # the web app's sync panel: the extension's latest doings
            session.publish("room_event", {"draft_id": draft_id, "entry": event}, bump=False)
        await asyncio.to_thread(yahoo_room.follow_clock, session, room, body.events)
        await asyncio.to_thread(yahoo_room.check_teams, session, room, body.events)
        await asyncio.to_thread(yahoo_room.check_gaps, session, room)
        return {
            "received": len(body.events),
            "written": written,
            "ignored": ignored,
            "control": room.control,
        }

    @app.post("/rooms/{draft_id}/request")
    async def room_request(draft_id: str, body: DraftRequest) -> dict[str, Any]:
        """Ask the draft tab to draft ``yahoo_player_id`` for my pick ``overall`` (#10), in
        mirror and autopilot alike. Refused (409) unless that pick is mine on the clock and
        ``board`` is the session's; dropped when the turn ends or the tab's click fails."""
        room, session = await get_room(draft_id)
        try:
            q = yahoo_room.request_pick(
                session, room, body.overall, body.board, body.yahoo_player_id
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"request": q}

    @app.post("/rooms/{draft_id}/aliases")
    async def room_alias(draft_id: str, body: AliasPin) -> dict[str, Any]:
        """Pin a Yahoo player to a projection id for this room and for later ones
        (``data/aliases.json``, which stays on this machine)."""
        room, session = await get_room(draft_id)
        try:
            result = await asyncio.to_thread(
                yahoo_room.pin, session, room, body.yahoo_player_id, body.player_id
            )
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
        key = str(room.ids.players.at[body.yahoo_player_id, "player_key"])
        path = data_dir / "aliases.json"
        aliases = load_aliases(path)
        aliases[key] = body.player_id
        path.write_text(json.dumps(aliases, indent=1, sort_keys=True) + "\n")
        return result

    @app.get("/rooms/{draft_id}/status")
    def room_fidelity_status(draft_id: str) -> dict[str, Any]:
        """One call for a mid-draft check: the log's view (picks seen, lag so far, labels of my
        picks so far) and, when the room is live, the session's."""
        events = read_events(room_log(draft_id).path)
        if not events:
            raise HTTPException(404, f"no log for room {draft_id}")
        try:
            view = fidelity_status(analyze(events))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        live = store.room(draft_id)
        return {**view, "live": None if live is None else yahoo_room.summary(live[1], live[0])}

    @app.get("/rooms/{draft_id}/fidelity", response_model=None)
    def room_fidelity(
        draft_id: str, format: Literal["json", "md"] = "json"
    ) -> dict[str, Any] | PlainTextResponse:
        """The scorecard from the log: compliance, labels, G1-G6, D1-D5 and every pick."""
        events = read_events(room_log(draft_id).path)
        if not events:
            raise HTTPException(404, f"no log for room {draft_id}")
        try:
            card = analyze(events)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        if format == "md":
            return PlainTextResponse(markdown(card), media_type="text/markdown")
        return {**card, "markdown": markdown(card)}

    @app.get("/sessions/{session_id}/yahoo/room")
    def session_room(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        if session.room is None:
            return {"attached": False}
        return yahoo_room.summary(session, session.room)

    @app.post("/sessions/{session_id}/yahoo/room", status_code=201)
    async def session_room_attach(session_id: str, body: RoomAttach) -> dict[str, Any]:
        store.get(session_id)
        room, session = await open_room(body.model_copy(update={"session_id": session_id}))
        return room_view(room, session)

    return app


# --------------------------------------------------------------------------- session setup
def _in_data_dir(file: str) -> bool:
    """A relative name that stays inside data/ (symlinks in data/ are the user's own)."""
    name = Path(file)
    return not name.is_absolute() and ".." not in name.parts


def _keepers_file_rows(data_dir: Path, file: str) -> list[Labelled]:
    """A keepers CSV inside ``data_dir``, labelled by line (400 if missing or unreadable)."""
    path = data_dir / file
    if not _in_data_dir(file) or not path.is_file() or path.suffix.lower() not in KEEPER_SUFFIXES:
        raise HTTPException(400, f"keepers file not found: {file}")
    try:
        return read_keepers_file(path)
    except (OSError, ValueError) as exc:  # a bad encoding is a ValueError too
        raise HTTPException(400, str(exc)) from exc


#: The session's files, each a path inside data/ (the keepers file is checked where it is read).
DATA_FILE_FIELDS = ("projection_file", "positions_file", "adp_file", "curve_file", "survival_file")


def _build_state(body: SessionCreate, data_dir: Path) -> tuple[DraftState, str, str]:
    """Load projections, positions, ADP and the curve for a new session (blocking I/O)."""
    for name in DATA_FILE_FIELDS:
        file = getattr(body, name)
        if file and not _in_data_dir(file):
            raise HTTPException(400, f"{name} must be a path inside data/: {file}")
    path = data_dir / body.projection_file
    if not path.exists() or path.suffix.lower() not in PROJECTION_SUFFIXES:
        raise HTTPException(400, f"projection file not found: {body.projection_file}")
    try:
        projections: ProjectionSet = load_bbm(path, horizon=body.horizon)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(400, f"could not parse {body.projection_file}: {exc}") from exc
    positions_path = (
        data_dir / body.positions_file if body.positions_file else data_dir / "positions.csv"
    )
    if positions_path.exists() and positions_path != path:
        try:
            df, _missing = apply_positions(projections.df, load_positions(positions_path))
        except ValueError as exc:
            raise HTTPException(
                400, f"could not read positions from {positions_path.name}: {exc}"
            ) from exc
        projections = ProjectionSet(
            source=projections.source,
            label=projections.label,
            horizon=projections.horizon,
            as_of=projections.as_of,
            df=df,
            start=projections.start,
            end=projections.end,
        )
    elif body.positions_file:
        raise HTTPException(400, f"positions file not found: {body.positions_file}")
    slots = (
        tuple(
            Slot(s.name, frozenset(s.eligible) if s.eligible else Slot.eligible) for s in body.slots
        )
        if body.slots
        else tuple(yahoo_default_slots(bench=body.bench))
    )
    settings = LeagueSettings(
        num_teams=body.num_teams,
        slots=slots,
        cats=tuple(body.cats) if body.cats else LeagueSettings.cats,
    )
    # The file's rows first, then the request's list; errors name the line or the index.
    rows = _keepers_file_rows(data_dir, body.keepers_file) if body.keepers_file else []
    rows += listed(body.keepers)
    try:
        state = DraftState(
            settings=settings,
            projections=projections,
            my_team=body.my_team,
            my_position=body.my_position,
            keepers=tuple(resolve_keepers(rows, projections.df)),
        )
    except KeeperInvalid as exc:
        raise HTTPException(400, keeper_error(rows, exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    adp_path = data_dir / body.adp_file if body.adp_file else data_dir / "adp.csv"
    if adp_path.exists() and adp_path != path:
        try:
            adp = adp_for_projections(state.projections.df, load_adp(adp_path))
        except ValueError as exc:
            raise HTTPException(400, f"could not read ADP from {adp_path.name}: {exc}") from exc
        if not adp.empty:
            state.set_adp(adp, f"file:{adp_path.name}")
    elif body.adp_file:
        raise HTTPException(400, f"ADP file not found: {body.adp_file}")
    state.plan_time_limit = body.time_limit
    state.price_time_limit = min(state.price_time_limit, body.time_limit)
    state.spread_base = body.spread_base
    state.spread_growth = body.spread_growth
    curve_source = "none"
    if body.objective == "win":
        if body.curve_file:
            curve_path = data_dir / body.curve_file
            if not curve_path.exists():
                raise HTTPException(400, f"curve file not found: {body.curve_file}")
            try:
                spec = json.loads(curve_path.read_text())
                curve = CategoryCurve.from_dict(
                    {**spec, "source": f"file:{curve_path.name}"}, settings.cats
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(400, f"could not read {curve_path.name}: {exc}") from exc
        else:
            curve = CategoryCurve.simulated(settings.cats)
        state.curve = curve.scaled(body.sigma_scale)
        curve_source = state.curve.source
    return state, projections.label, curve_source


def _load_league_survival(path: Path) -> LeagueSurvivalTable:
    """The league's survival by ADP from a CSV in data/ (``adp,1..N,undrafted``)."""
    return LeagueSurvivalTable.from_frame(pd.read_csv(path))


async def _build_survival(
    session: Session, sims: int, drafters: tuple[Strategy, ...], fit_curve: bool
) -> None:
    """Simulate the league in a worker thread, then install the table (and the fitted curve)
    and wake the solver."""
    state = session.state
    # The simulated league has no "me": my keepers go in at my seat.
    keepers = [
        replace(k, position=state.my_position) if k.position is None else k for k in state.keepers
    ]

    def progress(update: dict[str, Any]) -> None:
        session.survival["done"] = update["done"]
        loop = session.solver.loop if session.solver else None
        payload = {"status": "building", **update}
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(session.publish, "survival", payload, False)

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            solver_executor(),
            lambda: simulate_league(
                state.settings,
                state.projections,
                sims,
                state.adp,
                drafters,
                progress=progress,
                keepers=keepers,
                spread=(state.spread_base, state.spread_growth),
            ),
        )
    except Exception as exc:  # noqa: BLE001 - report, keep the session usable
        session.survival = {**session.survival, "status": "failed", "error": str(exc)}
        session.publish("survival", {"status": "failed", "error": str(exc)})
        return
    with session.lock:
        state.survival = result.survival
        if fit_curve and session.objective == "win":
            state.curve = result.curve.scaled(session.sigma_scale)
            session.curve_source = state.curve.source
    session.survival = {
        **session.survival,
        "status": "ready",
        "done": sims,
        "source": result.curve.source,
        "seconds": round(result.seconds, 1),
    }
    session.publish(
        "survival",
        {"status": "ready", "sims": sims, "seconds": round(result.seconds, 1)},
    )


# --------------------------------------------------------------------------- helpers
def _league_tables(data_dir: Path) -> list[dict[str, Any]]:
    """League survival tables in data/ or one folder down, by their header: ``file`` is the
    path inside data/."""
    if not data_dir.exists():
        return []
    folders = [data_dir] + sorted(
        p for p in data_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
    )
    out = []
    for folder in folders:
        for f in _list_files(folder, SURVIVAL_SUFFIXES):
            path = folder / f["file"]
            try:
                with path.open() as fh:
                    head = fh.readline().strip().split(",")
            except (OSError, UnicodeDecodeError):
                continue
            if head[0] == "adp" and head[-1] == "undrafted":
                out.append({**f, "file": str(path.relative_to(data_dir))})
    return out


def _list_files(data_dir: Path, suffixes: set[str]) -> list[dict[str, Any]]:
    if not data_dir.exists():
        return []
    files = sorted(
        (f for f in data_dir.iterdir() if f.is_file() and f.suffix.lower() in suffixes),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "file": f.name,
            "kind": f.suffix.lower().lstrip("."),
            "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat(),
        }
        for f in files
    ]


def _sse(event: str, data: dict[str, Any], event_id: int | None = None) -> str:
    head = "" if event_id is None else f"id: {event_id}\n"
    return f"{head}event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _missed(session: Session, last_event_id: str | None) -> list[dict[str, Any]]:
    """The board changes logged after the version a reconnecting stream saw last."""
    try:
        seen = int(last_event_id) if last_event_id else None
    except ValueError:
        seen = None
    if seen is None:
        return []
    return [p for p in list(session.log) if p["version"] > seen]


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 3)


def _solver_status(session: Session) -> dict[str, Any]:
    status = session.solver.status() if session.solver is not None else {"enabled": False}
    return {**status, "recommendation_version": (session.recommendation or {}).get("version")}


def _summary(session: Session) -> dict[str, Any]:
    state = session.state
    curve = state.curve
    return {
        "id": session.id,
        "version": session.version,
        "projection": session.projection_label,
        "num_teams": state.settings.num_teams,
        "roster_size": state.settings.roster_size,
        "cats": [c.value for c in state.settings.cats],
        "slots": [s.name for s in state.settings.slots],
        "my_team": state.my_team,
        "my_position": state.my_position,
        "my_picks": state.my_picks,
        "my_slots": state.my_slots,
        "keepers": keeper_rows(state),
        "picks_made": len(state.picks),
        "next_overall": state.next_overall,
        "my_next_pick": state.my_next_pick,
        "on_the_clock": state.on_the_clock,
        "complete": state.complete,
        "my_roster": state.my_roster,
        "unknown_positions": int(
            (state.projections.df["positions"].fillna("").str.strip() == "").sum()
        ),
        "adp_source": state.adp_source,
        "adp_known": int(state.adp.notna().sum()) if state.adp is not None else 0,
        # Keepers out of the market: each moves every player ranked behind him up a pick.
        "adp_keepers_ahead": len(state.keepers),
        "spread_base": state.spread_base,
        "spread_growth": state.spread_growth,
        "objective": state.objective,
        "curve": None if curve is None else curve.to_dict(),
        "sigma_scale": session.sigma_scale,
        "availability_source": state.availability_source,
        "survival": session.survival,
        "solver": _solver_status(session),
    }


def _score(session: Session) -> dict[str, Any]:
    """Every number is expected categories won on the session's curve: the benchmark before my
    first pick, the best plan seen during the draft, the latest solve, what my drafted players
    are worth alone, and once the roster is full the final roster's odds and its head-to-head
    tally against the league's projected finals. Values on the z scale ride along."""
    state = session.state
    history = list(session.history)
    latest = history[-1] if history else None
    benchmark = session.benchmark
    best = max(history, key=lambda h: h["wins"]) if history else None
    drafted_wins = state.roster_wins() if state.my_roster else 0.0
    drafted_value = state.roster_value()
    full = not state.my_remaining_picks
    final: dict[str, Any] | None = None
    if full and state.my_roster:
        finals = state.roster_totals()
        tally = state.matchups(finals)
        final = {
            "wins": round(drafted_wins, 4),
            "value": round(drafted_value, 3),
            "matchups": tally["matchups_won"],
            "cats_beaten": round(float(tally["cats_beaten"]), 3),
            "opponents": tally["opponents"],
            "categories": state.category_report(finals),
        }
    current = final["wins"] if final is not None else (latest["wins"] if latest else None)
    return {
        "version": session.version,
        "objective": state.objective,
        "benchmark": benchmark,
        "best": best,
        "latest": latest,
        "final": final,
        "drafted": len(state.my_roster),
        "roster_size": state.settings.roster_size,
        "drafted_wins": round(drafted_wins, 4),
        "drafted_value": round(drafted_value, 3),
        "current_wins": None if current is None else round(current, 4),
        "vs_benchmark": (
            None if benchmark is None or current is None else round(current - benchmark["wins"], 4)
        ),
        "vs_best": None if best is None or current is None else round(current - best["wins"], 4),
        "history": history,
    }


def _pick_row(state: DraftState, pick) -> dict[str, Any]:
    rnd, position = state.owner_of(pick.overall)
    return {
        "overall": pick.overall,
        "round": rnd,
        "position": position,
        "team": pick.team,
        "player_id": pick.player_id,
        "name": state.projections.df.at[pick.player_id, "player"],
        "keeper": state.is_keeper_pick(pick),
    }


app = create_app()
