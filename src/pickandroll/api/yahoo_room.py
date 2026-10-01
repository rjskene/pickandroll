"""A live Yahoo draft room mirrored into a session (YAHOO SYNC, ``docs/YAHOO_SYNC.md``).

The room's realtime channel carries every pick with the Yahoo player id the moment it happens;
the client in the user's draft page (the Chrome extension) forwards them here in batches. A
room keeps a ledger of what Yahoo reported per overall pick and reconciles the session with it:

* picks are applied in order; one that arrives before its predecessors waits for the gap;
* a batch is idempotent by overall, so a client can resend the whole history at any time;
* a Yahoo player with no projection (or one the session holds elsewhere) becomes a stand-in,
  the worst player left, so the board advances and the ledger keeps the real Yahoo id;
* the room is the truth for the board: a session pick that disagrees at the same overall is
  replaced by the room's pick and the conflict is logged with both players.

Everything the room sees goes to the fidelity log (:mod:`pickandroll.fidelity`), and so does
every solve, so the scorecard can be computed without the session and a room can be rebuilt
from its log after the API restarts.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from ..draft.settings import pick_owner, snake_picks
from ..draft.state import Pick
from ..fidelity import FidelityLog, now_iso, to_iso, to_ms
from ..sources.yahoo.players import YahooIdMap

if TYPE_CHECKING:
    from .app import Session

Mode = Literal["mirror", "autopilot"]
#: Board players appended to the plan's candidates, cheapest first.
BOARD_TAIL = 20
#: A heartbeat reaches the log at most this often; the latest is always kept in memory.
HEARTBEAT_EVERY_S = 60.0
#: Event types a room client may post (the server writes room_pick, session_pick, reco,
#: conflict, attach, detach and score itself).
CLIENT_EVENTS = frozenset(
    {"control", "turn_start", "draft_attempt", "pick_landed", "intervention", "heartbeat", "note"}
)
NEEDS_OVERALL = frozenset({"turn_start", "draft_attempt", "pick_landed"})
CONTROL_STATES = frozenset({"armed", "mirror", "absent"})


def control_for(mode: Mode) -> str:
    return "armed" if mode == "autopilot" else "mirror"


@dataclass(frozen=True)
class RoomPick:
    overall: int
    yid: str
    slot: int
    t: str
    src: str


@dataclass
class YahooRoom:
    draft_id: str
    slot: int
    mode: Mode
    num_teams: int
    rounds: int
    ids: YahooIdMap
    log: FidelityLog
    players_file: str
    ledger: dict[int, RoomPick] = field(default_factory=dict)
    #: The projection id the room put at each overall (mapped player or stand-in).
    assigned: dict[int, str] = field(default_factory=dict)
    standins: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: Overalls to re-place after an alias pin (a repair, not a conflict).
    repairs: set[int] = field(default_factory=set)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    control: str = "absent"
    heartbeat: dict[str, Any] | None = None
    heartbeat_logged: float = 0.0
    attached_at: str = field(default_factory=now_iso)
    resumed: bool = False
    scored: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def my_picks(self) -> list[int]:
        return snake_picks(self.num_teams, self.slot, self.rounds)

    @property
    def synced_through(self) -> int:
        k = 0
        while k + 1 in self.ledger:
            k += 1
        return k

    @property
    def waiting_for(self) -> int | None:
        """The first missing overall when later picks are parked behind it."""
        k = self.synced_through
        return k + 1 if any(o > k for o in self.ledger) else None


# --------------------------------------------------------------------------- attach
def attach_room(
    session: Session,
    *,
    draft_id: str,
    slot: int,
    mode: Mode,
    num_teams: int,
    ids: YahooIdMap,
    log: FidelityLog,
    players_file: str,
    prior: list[dict[str, Any]],
    attach_record: dict[str, Any],
) -> YahooRoom:
    """Bind a room to a session, write the attach record and replay any picks already in the
    log (a restart, or a second attach for the same draft)."""
    state = session.state
    if num_teams != state.settings.num_teams:
        raise ValueError(f"the room has {num_teams} teams, the session {state.settings.num_teams}")
    if not 1 <= slot <= num_teams:
        raise ValueError(f"slot must be between 1 and {num_teams}")
    with session.lock:
        if state.picks and slot != state.my_position:
            raise ValueError(
                f"the session already has picks for draft position {state.my_position}"
            )
        state.my_position = slot
    room = YahooRoom(
        draft_id=draft_id,
        slot=slot,
        mode=mode,
        num_teams=num_teams,
        rounds=state.settings.roster_size,
        ids=ids,
        log=log,
        players_file=players_file,
    )
    room_picks = [e for e in prior if e.get("type") == "room_pick"]
    controls = [e for e in prior if e.get("type") == "control"]
    room.resumed = bool(room_picks)
    room.scored = any(e.get("type") == "score" for e in prior)
    log.append(
        {
            "type": "attach",
            **attach_record,
            "draft_id": draft_id,
            "slot": slot,
            "mode": mode,
            "num_teams": num_teams,
            "rounds": room.rounds,
            "players_file": players_file,
            "session_id": session.id,
            "resumed": room.resumed,
            "mapped": len(ids.mapping),
            "players": len(ids.players),
        }
    )
    if controls and room.resumed:
        room.control = controls[-1].get("state", "absent")
    else:
        room.control = control_for(mode)
        log.append({"type": "control", "state": room.control, "slot": slot, "src": "api"})
    for e in room_picks:
        overall = int(e["overall"])
        if overall not in room.ledger:
            room.ledger[overall] = RoomPick(
                overall, str(e["yid"]), int(e["slot"]), e["t"], e.get("src", "log")
            )
    session.room = room
    with room.lock:
        changes = _reconcile(session, room)
    _publish_changes(session, room, changes, resume=True)
    session.publish(
        "room_attached",
        {"draft_id": draft_id, "slot": slot, "mode": mode, "resumed": room.resumed},
    )
    return room


# --------------------------------------------------------------------------- picks
def ingest(session: Session, room: YahooRoom, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Record a batch of room picks and bring the session level with the room."""
    unresolved = []
    new = 0
    with room.lock:
        for item in items:
            overall = int(item["overall"])
            yid = item.get("yahoo_player_id")
            if (yid is None or yid == "") and item.get("label"):
                yid = room.ids.resolve_label(str(item["label"]), item.get("team"))
            if yid is None or yid == "":
                miss = {"overall": overall, "label": item.get("label"), "team": item.get("team")}
                unresolved.append(miss)
                if miss not in room.unresolved:
                    room.unresolved.append(miss)
                continue
            yid = str(yid)
            seen = room.ledger.get(overall)
            if seen is not None:
                if seen.yid != yid:
                    note = {"overall": overall, "kept": seen.yid, "reported": yid, "kind": "room"}
                    if note not in room.conflicts:
                        room.conflicts.append(note)
                        room.log.append(
                            {"type": "note", "what": "room reported two players", **note}
                        )
                continue
            slot = int(item.get("slot") or pick_owner(room.num_teams, overall)[1])
            pick = RoomPick(
                overall, yid, slot, to_iso(item.get("t_room")), item.get("src") or "socket"
            )
            room.ledger[overall] = pick
            room.log.append(
                {
                    "type": "room_pick",
                    "t": pick.t,
                    "overall": overall,
                    "slot": slot,
                    "yid": yid,
                    "src": pick.src,
                    "name": room.ids.name(yid),
                }
            )
            new += 1
        changes = _reconcile(session, room)
    _publish_changes(session, room, changes)
    state = session.state
    return {
        "received": len(items),
        "new": new,
        "applied": sum(1 for c in changes if c["kind"] in ("new", "held")),
        "replaced": sum(1 for c in changes if c["kind"] in ("conflict", "repair")),
        "synced_through": room.synced_through,
        "waiting_for": room.waiting_for,
        "unresolved": unresolved,
        "version": session.version,
        "next_overall": state.next_overall,
        "my_next_pick": state.my_next_pick,
        "on_the_clock": state.on_the_clock,
        "complete": state.complete,
    }


def _reconcile(session: Session, room: YahooRoom) -> list[dict[str, Any]]:
    """Make the session agree with the ledger. A conflict or repair can free a player whose
    pick the room recorded earlier while the session still held him elsewhere; that pick got
    a stand-in, so walk again and put the player in his place. Caller holds the room lock; the
    session lock is taken here."""
    state = session.state
    changes: list[dict[str, Any]] = []
    with session.lock:
        for _ in range(len(room.ledger) + 1):
            changes += _walk(state, room)
            held = {p.player_id for p in state.picks}
            freed = {
                k
                for k, s in room.standins.items()
                if k not in room.repairs
                and (pid := room.ids.pid(s["yid"])) is not None
                and pid not in held
                and pid in state.z.index
            }
            if not freed:
                break
            room.repairs |= freed
    return changes


def _walk(state, room: YahooRoom) -> list[dict[str, Any]]:
    """One pass over the ledger from pick 1 (session lock held)."""
    changes: list[dict[str, Any]] = []
    k = 1
    while k in room.ledger:
        entry = room.ledger[k]
        have = state.picks[k - 1] if k <= len(state.picks) else None
        if have is None and k != len(state.picks) + 1:
            break
        target = room.assigned.get(k)
        if have is not None and target == have.player_id and k not in room.repairs:
            k += 1
            continue
        want = room.ids.pid(entry.yid)
        elsewhere = {p.player_id for p in state.picks if p.overall != k}
        if want is not None and want not in elsewhere and want in state.z.index:
            pid, standin = want, False
        else:
            pid, standin = _standin(state, elsewhere), True
        team = state.my_team if entry.slot == room.slot else f"Team {entry.slot}"
        t = now_iso()
        if have is not None and have.player_id == pid and k not in room.repairs:
            kind = "held"
        elif have is None:
            state.apply_pick(team, pid, k)
            kind = "new"
        else:
            state.picks[k - 1] = Pick(overall=k, team=team, player_id=pid)
            kind = "repair" if k in room.repairs else "conflict"
        room.repairs.discard(k)
        room.assigned[k] = pid
        if standin:
            room.standins[k] = {"yid": entry.yid, "name": room.ids.name(entry.yid), "as": pid}
        else:
            room.standins.pop(k, None)
        changes.append(
            {
                "overall": k,
                "kind": kind,
                "pid": pid,
                "yid": entry.yid,
                "standin": standin,
                "old": None if have is None else have.player_id,
                "t": t,
                "lag_ms": round(to_ms(t) - to_ms(entry.t)),
            }
        )
        k += 1
    return changes


def _standin(state, taken: set[str]) -> str:
    """The least useful player left: zero projected games first, then the lowest total z."""
    games = state.projections.df["games"]
    total = state.z["total"]
    left = [p for p in total.index if p not in taken]
    if not left:
        raise ValueError("no player left for a stand-in")
    return min(left, key=lambda p: (float(games.get(p, 0.0)) > 0.0, float(total[p]), p))


def _publish_changes(
    session: Session, room: YahooRoom, changes: list[dict[str, Any]], resume: bool = False
) -> None:
    from .app import _pick_row, _score

    state = session.state
    for c in changes:
        event = {
            "type": "session_pick",
            "t": c["t"],
            "overall": c["overall"],
            "pid": c["pid"],
            "yid": c["yid"],
            "lag_ms": c["lag_ms"],
            "standin": c["standin"],
            "kind": c["kind"],
        }
        if resume:
            event["resume"] = True
        room.log.append(event)
        if c["kind"] == "conflict":
            conflict = {
                "overall": c["overall"],
                "session_pid": c["old"],
                "session_yid": room.ids.yid(c["old"]),
                "room_yid": c["yid"],
                "room_pid": c["pid"],
            }
            room.conflicts.append({**conflict, "kind": "session"})
            room.log.append({"type": "conflict", **conflict})
        if c["kind"] == "held":
            continue
        row = _pick_row(state, next(p for p in state.picks if p.overall == c["overall"]))
        payload: dict[str, Any] = {"pick": row, "source": "yahoo_room"}
        if c["old"] is not None:
            payload["replaced"] = c["old"]
        session.publish("pick", payload)
    if not room.scored and state.my_picks and not state.my_remaining_picks:
        with session.lock:
            score = _score(session)
        room.scored = True
        final = score.get("final") or {}
        benchmark = score.get("benchmark") or {}
        best = score.get("best") or {}
        room.log.append(
            {
                "type": "score",
                "wins": final.get("wins", score.get("current_wins")),
                "benchmark": benchmark.get("wins"),
                "vs_benchmark": score.get("vs_benchmark"),
                "best": best.get("wins"),
                "matchups": final.get("matchups"),
            }
        )


def pin(session: Session, room: YahooRoom, yid: str, pid: str) -> dict[str, Any]:
    """Map a Yahoo id to a projection id for this room and re-place any stand-in for it."""
    if not room.ids.known(yid):
        raise KeyError(f"unknown Yahoo player {yid}")
    if pid not in session.state.z.index:
        raise KeyError(f"unknown player {pid!r}")
    with room.lock:
        room.ids.pin(yid, pid)
        room.repairs |= {k for k, s in room.standins.items() if s["yid"] == yid}
        changes = _reconcile(session, room)
    _publish_changes(session, room, changes)
    room.log.append({"type": "note", "what": "alias pinned", "yid": yid, "pid": pid})
    return {"yahoo_player_id": yid, "player_id": pid, "repaired": [c["overall"] for c in changes]}


# --------------------------------------------------------------------------- events
def record_events(room: YahooRoom, events: list[dict[str, Any]]) -> int:
    """Store client events with the server's receive time. Heartbeats are kept in memory and
    written at most once per ``HEARTBEAT_EVERY_S``."""
    clean = []
    for e in events:
        kind = e.get("type")
        if kind not in CLIENT_EVENTS:
            raise ValueError(f"unknown event type {kind!r}; allowed: {sorted(CLIENT_EVENTS)}")
        if kind in NEEDS_OVERALL and not isinstance(e.get("overall"), int):
            raise ValueError(f"{kind} needs an integer overall")
        if kind == "control" and e.get("state") not in CONTROL_STATES:
            raise ValueError(f"control state must be one of {sorted(CONTROL_STATES)}")
        clean.append({**e, "t": to_iso(e.get("t")), "src": e.get("src") or "client"})
    written = 0
    for e in clean:
        e["recv"] = now_iso()
        if e["type"] == "heartbeat":
            room.heartbeat = e
            if time.monotonic() - room.heartbeat_logged < HEARTBEAT_EVERY_S:
                continue
            room.heartbeat_logged = time.monotonic()
        if e["type"] == "control":
            room.control = e["state"]
        room.log.append(e)
        written += 1
    return written


# --------------------------------------------------------------------------- plan
def candidates(
    session: Session, room: YahooRoom, rec: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Who to draft, best first, by Yahoo id: the recommendation's priced candidates, the
    plan's next rows, then the board by cost (exact where priced, else first order). Drafted
    players, zero-game players and players without a Yahoo id are left out."""
    state = session.state
    with session.lock:
        taken = state.taken
        prices = session.prices
        exact = dict(session.exact_prices)
    games = state.projections.df["games"]
    total = state.z["total"]
    reverse = room.ids.reverse
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(pid: str, why: str, cost: float | None = None, tie: bool = False) -> bool:
        yid = reverse.get(pid)
        if yid is None or pid in seen or pid in taken or not float(games.get(pid, 0.0)) > 0.0:
            return False
        seen.add(pid)
        out.append(
            {
                "yahoo_player_id": yid,
                "player_id": pid,
                "name": room.ids.name(yid),
                **room.ids.row_name(yid),
                "why": why,
                "cost": None if cost is None or pd.isna(cost) else round(float(cost), 4),
                "tie": bool(tie),
            }
        )
        return True

    if rec:
        for c in rec.get("candidates", []):
            add(c["player"], "candidate", c.get("cost_vs_best"), c.get("tie", False))
        for row in rec.get("plan", [])[:3]:
            add(row["player"], "plan")

    def cost(pid: str) -> float | None:
        if pid in exact:
            return exact[pid]
        if prices is not None:
            value = prices.get(pid)
            if value is not None and not pd.isna(value):
                return float(value)
        return None

    left = [p for p in total.index if p not in taken and p not in seen]
    ranked = sorted(left, key=lambda p: (cost(p) is None, cost(p) or 0.0, -float(total[p])))
    added = 0
    for pid in ranked:
        if added >= BOARD_TAIL:
            break
        added += add(pid, "board", cost(pid))
    return out


def plan(session: Session, room: YahooRoom) -> dict[str, Any]:
    """What the drafter needs for my next turn, and for the one after it when my slot picks
    twice in a row."""
    from .app import _solver_status

    state = session.state
    rec = session.recommendation
    with session.lock:
        version = session.version
        picks_made = len(state.picks)
        next_overall = state.next_overall
        my_next = state.my_next_pick
        on_the_clock = state.on_the_clock
        my_picks = state.my_picks
    first = candidates(session, room, rec)
    second_pick = my_next + 1 if my_next is not None and my_next + 1 in my_picks else None
    second = None
    if second_pick is not None:
        planned = [r for r in (rec or {}).get("plan", []) if r["pick"] == second_pick]
        by_pid = {c["player_id"]: c for c in first}
        second = []
        for row in planned:
            if row["player"] in by_pid:
                second.append({**by_pid[row["player"]], "why": "plan"})
        second += [c for c in first if all(c["player_id"] != s["player_id"] for s in second)]
    return {
        "draft_id": room.draft_id,
        "version": version,
        "solved_version": rec["version"] if rec else None,
        "board": rec["next_overall"] - 1 if rec else None,
        "fresh": rec is not None and rec["version"] == version,
        "picks_applied": picks_made,
        "next_overall": next_overall,
        "my_next_pick": my_next,
        "on_the_clock": on_the_clock,
        "waiting_for": room.waiting_for,
        "candidates": first,
        "second_pick": second_pick,
        "second": second,
        "solver": _solver_status(session),
    }


def on_recommendation(session: Session, room: YahooRoom, payload: dict[str, Any]) -> None:
    """Log a solve: the board it was built on, its top candidate and the list the drafter is
    served, its time, and the recommended players the drafter cannot see because they have no
    Yahoo id (``top_pid`` is the solve's own first choice, mapped or not)."""
    cands = candidates(session, room, payload)
    timings = payload.get("timings") or {}
    names = session.state.projections.df["player"]
    reverse = room.ids.reverse
    raw = [c["player"] for c in payload.get("candidates", [])]
    pool = raw + [r["player"] for r in payload.get("plan", [])[:3]]
    unmapped = [
        {"pid": pid, "name": str(names.get(pid, pid))}
        for pid in dict.fromkeys(pool)
        if pid not in reverse
    ]
    room.log.append(
        {
            "type": "reco",
            "board": int(payload["next_overall"]) - 1,
            "version": payload["version"],
            "fresh": payload["version"] == session.version,
            "top_yid": cands[0]["yahoo_player_id"] if cands else None,
            "top_name": cands[0]["name"] if cands else None,
            "top_pid": raw[0] if raw else None,
            "cands": [c["yahoo_player_id"] for c in cands],
            "unmapped": unmapped,
            "solve_ms": timings.get("total_ms"),
            "mode": payload.get("mode"),
        }
    )


def unmatched_projection(session: Session, room: YahooRoom, limit: int = 25) -> list[dict]:
    """Projected players with no Yahoo id, best first: the ones to pin before a draft, since
    the drafter can never take them."""
    state = session.state
    reverse = room.ids.reverse
    total = state.z["total"].sort_values(ascending=False)
    df = state.projections.df
    rows = [pid for pid in total.index if pid not in reverse][:limit]
    return [
        {
            "player_id": pid,
            "name": str(df.at[pid, "player"]),
            "team": str(df.at[pid, "team"] or ""),
            "total": round(float(total[pid]), 3),
        }
        for pid in rows
    ]


def summary(session: Session, room: YahooRoom) -> dict[str, Any]:
    state = session.state
    rec = session.recommendation
    heartbeat = room.heartbeat
    return {
        "attached": True,
        "draft_id": room.draft_id,
        "session_id": session.id,
        "slot": room.slot,
        "mode": room.mode,
        "control": room.control,
        "num_teams": room.num_teams,
        "rounds": room.rounds,
        "players_file": room.players_file,
        "attached_at": room.attached_at,
        "resumed": room.resumed,
        "mapped": len(room.ids.mapping),
        "players": len(room.ids.players),
        "room_picks": len(room.ledger),
        "synced_through": room.synced_through,
        "waiting_for": room.waiting_for,
        "picks_applied": len(state.picks),
        "next_overall": state.next_overall,
        "my_next_pick": state.my_next_pick,
        "on_the_clock": state.on_the_clock,
        "version": session.version,
        "solved_version": rec["version"] if rec else None,
        "fresh": rec is not None and rec["version"] == session.version,
        "standins": [{"overall": k, **v} for k, v in sorted(room.standins.items())],
        "conflicts": room.conflicts,
        "unresolved": room.unresolved,
        "unmatched_yahoo": room.ids.unmatched(limit=25),
        "unmatched_projection": unmatched_projection(session, room, limit=25),
        "heartbeat": heartbeat,
        "heartbeat_age_s": None
        if heartbeat is None
        else round((to_ms(now_iso()) - to_ms(heartbeat["recv"])) / 1000.0, 1),
        "fidelity_log": str(room.log.path),
    }
