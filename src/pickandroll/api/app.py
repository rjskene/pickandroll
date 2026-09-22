"""FastAPI app: draft sessions over :class:`DraftState` with a server-sent event stream.

Sessions live in memory (a draft lasts an evening). Every mutation bumps the session version and
publishes an event, so the UI can subscribe to ``/sessions/{id}/events`` and re-fetch the board
and recommendation whenever a pick lands, whether it came from the Yahoo poller or manual entry.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..draft import DraftState, LeagueSettings, simulate
from ..optim.roster import Slot, yahoo_default_slots
from ..projections.adp import adp_for_projections, load_adp
from ..projections.positions import apply_positions, load_positions
from ..projections.schema import Cat, ProjectionSet
from ..sources.bbm import PROJECTION_SUFFIXES, load_bbm
from ..sources.yahoo import YahooLeague
from .yahoo_feed import LeagueFactory, YahooFeed, attach_feed

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
KEEPALIVE_SECONDS = 15.0
# Streams end on their own after this long; EventSource reconnects and the UI refreshes on
# the next hello. Bounded streams let uvicorn finish a graceful shutdown or reload.
MAX_STREAM_SECONDS = 120.0


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

    def publish(self, event: str, data: dict[str, Any], bump: bool = True) -> None:
        """Send an event to every listener. Board changes bump the version; transient solver
        progress (``bump=False``) does not, so the UI never re-solves because of it."""
        if bump:
            self.version += 1
        payload = {"event": event, "version": self.version, "at": _now(), **data}
        if bump:
            self.log.append(payload)
        for queue in list(self.listeners):
            queue.put_nowait(payload)


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, Session] = {}

    def create(self, state: DraftState, projection_label: str) -> Session:
        session = Session(id=uuid.uuid4().hex[:8], state=state, projection_label=projection_label)
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


class PickIn(BaseModel):
    team: str
    player_id: str
    overall: int | None = None


class SyncIn(BaseModel):
    picks: list[tuple[int, str, str]] = Field(description="(overall, team, player_id) triples")


class AutoPickIn(BaseModel):
    count: int | None = Field(default=None, ge=1, description="stop after this many picks")
    until_my_pick: bool = Field(default=True, description="stop when my team is on the clock")
    noise: float = Field(
        default=1.0, ge=0.0, le=3.0, description="0 = best ADP available, 1 = model spread"
    )
    seed: int | None = None


class YahooAttach(BaseModel):
    league_id: str
    interval: float = Field(default=8.0, ge=2.0, le=120.0)
    start: bool = True


class RecommendQuery(BaseModel):
    n: int = 8
    punt: list[Cat] | None = None
    max_punts: int = 2
    balance: float = 0.0
    horizon: bool = True


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
        app.state.loop = asyncio.get_running_loop()
        yield
        shutdown.set()  # wakes every open event stream so the server can exit
        for session in store.sessions.values():
            if session.yahoo and session.yahoo.task:
                session.yahoo.task.cancel()

    app = FastAPI(title="pickandroll", version="0.1.0", lifespan=lifespan)
    app.state.store = store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "time": _now()}

    @app.get("/projections")
    def list_projections() -> list[dict[str, Any]]:
        files = sorted(
            (f for f in data_dir.iterdir() if f.suffix.lower() in PROJECTION_SUFFIXES),
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

    @app.post("/sessions", status_code=201)
    def create_session(body: SessionCreate) -> dict[str, Any]:
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
                Slot(s.name, frozenset(s.eligible) if s.eligible else Slot.eligible)
                for s in body.slots
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
        session = store.create(state, projections.label)
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
        taken = state.taken
        adp = state.effective_adp()
        # Odds each player lasts to my next pick after the current one (the board's question
        # while I am on the clock is "can I wait on this player?").
        future = [k for k in state.my_remaining_picks if k > state.next_overall]
        next_pick = future[0] if future else None
        p_next = state.availability()[next_pick] if next_pick is not None else None
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
                    "z": {
                        c.value: round(float(z.at[pid, c.value]), 3) for c in state.settings.cats
                    },
                    "total": round(float(z.at[pid, "total"]), 3),
                    "taken": pid in taken,
                }
            )
        return {"version": session.version, "next_pick": next_pick, "players": rows}

    @app.get("/sessions/{session_id}/picks")
    def picks(session_id: str) -> list[dict[str, Any]]:
        session = store.get(session_id)
        return [_pick_row(session.state, p) for p in session.state.picks]

    @app.post("/sessions/{session_id}/picks", status_code=201)
    def add_pick(session_id: str, body: PickIn) -> dict[str, Any]:
        session = store.get(session_id)
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
        made = simulate(
            session.state,
            count=body.count,
            until_my_pick=body.until_my_pick,
            noise=body.noise,
            seed=body.seed,
        )
        rows = [_pick_row(session.state, p) for p in made]
        for row in rows:
            session.publish("pick", {"pick": row})
        return {"added": rows, "version": session.version}

    @app.post("/sessions/{session_id}/recommend")
    def recommend(session_id: str, body: RecommendQuery) -> dict[str, Any]:
        """Next-pick candidates and the best roster or plan from the current board.

        With ``horizon`` (default) the rolling-horizon model prices candidates including the
        risk of waiting and returns the plan for every remaining pick. It falls back to the
        single-roster model when my remaining picks and open slots disagree.
        """
        session = store.get(session_id)
        state = session.state
        punt = frozenset(body.punt) if body.punt is not None else None
        names = state.projections.df["player"]
        started = time.perf_counter()
        loop = getattr(app.state, "loop", None)

        def progress(update: dict[str, Any]) -> None:
            payload = {**update, "elapsed_ms": round((time.perf_counter() - started) * 1000)}
            if "candidate" in payload and "player" in payload["candidate"]:
                payload["candidate"] = {
                    **payload["candidate"],
                    "name": names.get(
                        payload["candidate"]["player"], payload["candidate"]["player"]
                    ),
                }
            if payload.get("first_pick"):
                payload["first_pick_name"] = names.get(payload["first_pick"], payload["first_pick"])
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(session.publish, "solve", payload, False)
            else:
                session.publish("solve", payload, bump=False)

        try:
            if body.horizon and not state.complete:
                try:
                    progress({"stage": "start", "done": 0, "total": 1, "auto_punt": punt is None})
                    table, plan, chosen = state.recommend_horizon(
                        n=body.n,
                        punt=punt,
                        max_punts=body.max_punts,
                        balance=body.balance,
                        progress=progress,
                    )
                    progress({"stage": "done", "done": 1, "total": 1})
                    return {
                        "version": session.version,
                        "mode": "horizon",
                        "timings": {k: round(v, 1) for k, v in state.last_timings.items()},
                        "punt_scan": _punt_scan_rows(state, names),
                        "on_the_clock": state.on_the_clock,
                        "next_overall": state.next_overall,
                        "my_next_pick": state.my_next_pick,
                        "adp_source": state.adp_source,
                        "candidates": _records(table),
                        "punted": [
                            c.value for c in sorted(chosen, key=list(state.settings.cats).index)
                        ],
                        "plan": [
                            {
                                "pick": int(r.pick),
                                "player": r.player,
                                "name": names.at[r.player],
                                "availability": round(float(r.availability), 3),
                            }
                            for r in plan.plan.itertuples()
                        ],
                        "best_roster": {
                            "objective": plan.objective,
                            "punted": [
                                c.value for c in sorted(chosen, key=list(state.settings.cats).index)
                            ],
                            "min_active_total": plan.min_active_total,
                            "cat_totals": {
                                c.value: round(float(v), 3) for c, v in plan.expected_totals.items()
                            },
                            "roster": [
                                {**r, "name": names.at[r["player"]]}
                                for r in plan.roster.to_dict(orient="records")
                            ],
                            "solve_seconds": plan.solve_seconds,
                        },
                    }
                except ValueError:
                    pass  # picks and open slots disagree: use the roster model below
            table = state.recommend(
                n=body.n, punt=punt, max_punts=body.max_punts, balance=body.balance
            )
            best = state.best_roster(punt=punt, max_punts=body.max_punts, balance=body.balance)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "version": session.version,
            "mode": "roster",
            "on_the_clock": state.on_the_clock,
            "next_overall": state.next_overall,
            "my_next_pick": state.my_next_pick,
            "adp_source": state.adp_source,
            "candidates": _records(table),
            "punted": [c.value for c in best.punted],
            "plan": [],
            "best_roster": {
                "objective": best.objective,
                "punted": [c.value for c in best.punted],
                "min_active_total": best.min_active_total,
                "cat_totals": {c.value: round(float(v), 3) for c, v in best.cat_totals.items()},
                "roster": [
                    {**r, "name": names.at[r["player"]]}
                    for r in best.roster.to_dict(orient="records")
                ],
                "solve_seconds": best.solve_seconds,
            },
        }

    @app.get("/sessions/{session_id}/events")
    async def events(session_id: str, request: Request) -> StreamingResponse:
        """Server-sent events: one ``hello`` on connect, then ``pick`` / ``undo`` / ``created``.

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


# --------------------------------------------------------------------------- helpers
def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return round(float(value), 3)


def _summary(session: Session) -> dict[str, Any]:
    state = session.state
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


def _punt_scan_rows(state: DraftState, names: pd.Series, top: int = 10) -> list[dict[str, Any]]:
    """The ranked punt strategies from the last automatic scan, best first."""
    table = state.last_punt_scan
    if table is None or table.empty:
        return []
    rows = []
    best = float(table["objective"].iloc[0])
    for r in table.head(top).itertuples():
        players = [p.strip() for p in str(r.players).split(",") if p.strip()]
        rows.append(
            {
                "punt": r.punt,
                "objective": round(float(r.objective), 3),
                "gap_to_best": round(best - float(r.objective), 3),
                "min_active_total": round(float(r.min_active_total), 3),
                "roster": [names.get(p, p) for p in players],
            }
        )
    return rows


def _records(table: pd.DataFrame) -> list[dict[str, Any]]:
    if table.empty:
        return []
    out = table.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].round(4)
    return out.to_dict(orient="records")


app = create_app()
