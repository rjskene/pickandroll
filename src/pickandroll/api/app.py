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
import json
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..availability.survival import SurvivalTable
from ..draft import STRATEGIES, DraftState, LeagueSettings, Strategy, simulate
from ..draft.league_sim import simulate_league
from ..optim.objective import CategoryCurve
from ..optim.roster import Slot, yahoo_default_slots
from ..projections.adp import adp_for_projections, load_adp
from ..projections.positions import apply_positions, load_positions
from ..projections.schema import Cat, ProjectionSet
from ..sources.bbm import PROJECTION_SUFFIXES, load_bbm
from ..sources.yahoo import YahooLeague
from .solver import BackgroundSolver, SolveParams, compute_recommendation, solver_executor
from .yahoo_feed import LeagueFactory, YahooFeed, attach_feed

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
KEEPALIVE_SECONDS = 15.0
# Streams end on their own after this long; EventSource reconnects and the UI refreshes on
# the next hello. Bounded streams let uvicorn finish a graceful shutdown or reload.
MAX_STREAM_SECONDS = 120.0
SURVIVAL_SUFFIXES = {".csv"}
CURVE_SUFFIXES = {".json"}
ADP_SUFFIXES = {".csv", ".xls", ".xlsx"}


# --------------------------------------------------------------------------- session store
@dataclass
class Session:
    id: str
    state: DraftState
    projection_label: str
    version: int = 0
    listeners: list[asyncio.Queue] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    yahoo: YahooFeed | None = None
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

    def record_score(
        self,
        snapshot: dict[str, Any],
        mode: str,
        wins: float,
        value: float,
        matchups: int,
        top: str | None,
    ) -> dict[str, Any]:
        """Remember a solve's expected categories won (and its value on the z scale). The
        benchmark is the latest solve made before my first pick; after that pick it never
        changes. ``snapshot`` is the board the solve was built on."""
        state = self.state
        entry = {
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
        self.history = [h for h in self.history if h["version"] != entry["version"]] + [entry]
        self.history.sort(key=lambda h: h["version"])
        first = state.my_picks[0] if state.my_picks else None
        if first is not None and snapshot["next_overall"] <= first:
            self.benchmark = entry
        return entry

    def set_recommendation(self, payload: dict[str, Any]) -> None:
        self.recommendation = payload
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

    def publish(self, event: str, data: dict[str, Any], bump: bool = True) -> None:
        """Send an event to every listener. Board changes bump the version and wake the
        background solver; transient solver progress (``bump=False``) does neither, so a
        solve never triggers itself."""
        if bump:
            self.version += 1
        payload = {"event": event, "version": self.version, "at": _now(), **data}
        if bump:
            self.log.append(payload)
        for queue in list(self.listeners):
            queue.put_nowait(payload)
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
        self.loop: asyncio.AbstractEventLoop | None = None

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
        description="multiplies the curve's spread; above one hedges for noisy weeks",
    )
    curve_file: str | None = Field(
        default=None, description="optional JSON inside data/ with per-category mu and sigma"
    )
    survival: Literal["none", "simulate", "file"] = Field(
        default="none",
        description="availability: ADP formula, a simulated table built now, or a saved table",
    )
    survival_sims: int = Field(default=300, ge=10, le=5000)
    survival_file: str | None = Field(default=None, description="survival CSV inside data/")
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


RecommendQuery = SolveParams


# --------------------------------------------------------------------------- app
def create_app(
    store: SessionStore | None = None,
    data_dir: Path | None = None,
    league_factory: LeagueFactory | None = None,
) -> FastAPI:
    store = store or SessionStore()
    data_dir = data_dir or DATA_DIR
    league_factory = league_factory or (lambda league_id: YahooLeague(league_id))
    shutdown = asyncio.Event()

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

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "time": _now()}

    @app.get("/projections")
    def list_projections() -> list[dict[str, Any]]:
        return _list_files(data_dir, PROJECTION_SUFFIXES)

    @app.get("/files")
    def list_files(
        kind: Literal["survival", "curve", "adp"] = "survival",
    ) -> list[dict[str, Any]]:
        """Saved survival tables (CSV with a ``.sims`` sidecar), curve files (JSON) or ADP
        files (a csv/xls whose name contains ``adp``) in data/."""
        if kind == "survival":
            files = _list_files(data_dir, SURVIVAL_SUFFIXES)
            return [f for f in files if (data_dir / (f["file"] + ".sims")).exists()]
        if kind == "adp":
            files = _list_files(data_dir, ADP_SUFFIXES)
            return [f for f in files if "adp" in f["file"].lower()]
        return _list_files(data_dir, CURVE_SUFFIXES)

    @app.post("/sessions", status_code=201)
    async def create_session(body: SessionCreate) -> dict[str, Any]:
        state, label, curve_source = await asyncio.to_thread(_build_state, body, data_dir)
        survival: dict[str, Any] = {"mode": body.survival, "status": "none"}
        if body.survival == "file":
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
        if body.survival == "simulate":
            asyncio.get_running_loop().create_task(
                _build_survival(session, body.survival_sims, drafters, body.fit_curve)
            )
        return _summary(session)

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
            adp = state.effective_adp()
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
            try:
                pick = session.state.apply_pick(body.team, body.player_id, body.overall)
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
        row = _pick_row(session.state, pick)
        session.publish("pick", {"pick": row})
        return row

    @app.post("/sessions/{session_id}/sync")
    def sync(session_id: str, body: SyncIn) -> dict[str, Any]:
        session = store.get(session_id)
        with session.lock:
            try:
                added = session.state.sync(body.picks)
            except (KeyError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
        rows = [_pick_row(session.state, p) for p in added]
        for row in rows:
            session.publish("pick", {"pick": row})
        return {"added": rows, "version": session.version}

    @app.delete("/sessions/{session_id}/picks/last")
    def undo_pick(session_id: str) -> dict[str, Any]:
        session = store.get(session_id)
        with session.lock:
            if not session.state.picks:
                raise HTTPException(400, "no picks to undo")
            pick = session.state.picks.pop()
        row = _pick_row(session.state, pick)
        session.publish("undo", {"pick": row})
        return row

    @app.post("/sessions/{session_id}/autopick")
    def autopick(session_id: str, body: AutoPickIn) -> dict[str, Any]:
        """Auto-pick for the other teams (draft simulation) until my pick or ``count`` picks."""
        session = store.get(session_id)
        if session.state.complete:
            raise HTTPException(400, "draft is complete")
        if body.until_my_pick and body.count is None and session.state.on_the_clock:
            raise HTTPException(400, "you are on the clock; make your pick first")
        with session.lock:
            made = simulate(
                session.state,
                count=body.count,
                until_my_pick=body.until_my_pick,
                noise=body.noise,
                seed=body.seed,
                strategy=body.strategy,
            )
        rows = [_pick_row(session.state, p) for p in made]
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
        / ``survival`` / ``solve`` / ``recommendation``.

        A comment line is sent every ``KEEPALIVE_SECONDS`` so proxies keep the connection open.
        """
        session = store.get(session_id)
        queue: asyncio.Queue = asyncio.Queue()
        session.listeners.append(queue)

        async def stream():
            stop = asyncio.ensure_future(shutdown.wait())
            started = asyncio.get_running_loop().time()
            try:
                yield _sse("hello", {"version": session.version})
                while not shutdown.is_set() and not await request.is_disconnected():
                    if asyncio.get_running_loop().time() - started > MAX_STREAM_SECONDS:
                        yield _sse("reconnect", {"version": session.version})
                        break
                    getter = asyncio.ensure_future(queue.get())
                    done, _pending = await asyncio.wait(
                        {getter, stop},
                        timeout=KEEPALIVE_SECONDS,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if getter in done:
                        payload = getter.result()
                        yield _sse(payload["event"], payload)
                    else:
                        getter.cancel()
                        if stop in done:
                            yield _sse("bye", {"reason": "server shutting down"})
                            break
                        yield ": keepalive\n\n"
            finally:
                stop.cancel()
                session.listeners.remove(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ yahoo feed
    @app.post("/sessions/{session_id}/yahoo", status_code=201)
    async def yahoo_attach(session_id: str, body: YahooAttach) -> dict[str, Any]:
        session = store.get(session_id)
        if session.yahoo and session.yahoo.running:
            session.yahoo.task.cancel()
        try:
            league = league_factory(body.league_id)
            feed = await asyncio.to_thread(
                attach_feed, session, league, body.interval, data_dir / "aliases.json"
            )
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

    return app


# --------------------------------------------------------------------------- session setup
def _build_state(body: SessionCreate, data_dir: Path) -> tuple[DraftState, str, str]:
    """Load projections, positions, ADP and the curve for a new session (blocking I/O)."""
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
    try:
        state = DraftState(
            settings=settings,
            projections=projections,
            my_team=body.my_team,
            my_position=body.my_position,
        )
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


async def _build_survival(
    session: Session, sims: int, drafters: tuple[Strategy, ...], fit_curve: bool
) -> None:
    """Simulate the league in a worker thread, then install the table (and the fitted curve)
    and wake the solver."""
    state = session.state

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


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


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
    }


app = create_app()
