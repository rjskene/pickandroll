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
from collections import deque
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
#: The plan's budget follows the room's pick clock: the drafter clicks with CLOCK_MARGIN_S of
#: the clock left (at 17 s of 30), and the exact prices that correct a capped plan take up to
#: PRICING_S after it (their 10 s budget and the solve's overhead). A 30 s clock (the mocks)
#: gives the 5 s floor; a longer one lets the plan converge (6-16 s in rounds 1-6), up to the
#: plan's own 20 s budget.
DEFAULT_CLOCK_S = 30.0
CLOCK_MARGIN_S = 13.0
PRICING_S = 12.0
PLAN_LIMIT_MIN = 5.0
PLAN_LIMIT_MAX = 20.0
PRICE_LIMIT_MAX = 10.0


def plan_budget(clock_s: float | None) -> float:
    """The plan's time limit in a room whose pick clock is ``clock_s`` seconds."""
    clock = DEFAULT_CLOCK_S if clock_s is None else clock_s
    return min(PLAN_LIMIT_MAX, max(PLAN_LIMIT_MIN, clock - CLOCK_MARGIN_S - PRICING_S))


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
    #: The pick clock the plan budget follows (``None``: the attach fixed a time_limit).
    clock_s: float | None = None
    #: The room's own team count when its client reported one that disagrees with the
    #: attach's (the room was then put in mirror mode, once).
    teams_mismatch: int | None = None
    #: The first recommendation from the single-roster model has been noted in the log.
    roster_noted: bool = False
    #: (overall, ms from the room's pick to the session's) for the latest picks: the web
    #: app's sync panel, without reading the log.
    recent_lags: deque = field(default_factory=lambda: deque(maxlen=24), repr=False)
    #: The user's "Draft in Yahoo" from the web app (#10), for the draft tab to click while
    #: that pick is on the clock; see :func:`request_pick`.
    request: dict[str, Any] | None = None
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
    """Record a batch of room picks and bring the session level with the room. A pick outside
    the draft (overall below 1 or past num_teams x rounds) is no room's: it is dropped and
    counted in ``ignored``, never the batch with it, and the log gets one note per batch that
    had any."""
    unresolved = []
    new = 0
    last = room.num_teams * room.rounds
    outside = sorted({int(i["overall"]) for i in items if not 1 <= int(i["overall"]) <= last})
    with room.lock:
        if outside:
            room.log.append(
                {
                    "type": "note",
                    "what": "room picks outside the draft ignored",
                    "overalls": outside,
                }
            )
        for item in items:
            overall = int(item["overall"])
            if not 1 <= overall <= last:
                continue
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
        "ignored": sum(1 for i in items if not 1 <= int(i["overall"]) <= last),
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
        elif c["kind"] != "repair":  # a pinned stand-in is the same room pick, not a late one
            room.recent_lags.append((c["overall"], c["lag_ms"]))
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
        payload: dict[str, Any] = {"pick": row, "source": "yahoo_room", "lag_ms": c["lag_ms"]}
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


# --------------------------------------------------------------------------- draft request
def request_pick(
    session: Session, room: YahooRoom, overall: int, board: int, yid: str
) -> dict[str, Any]:
    """The user's "Draft in Yahoo" (#10): ask the draft tab to click ``yid`` for my pick
    ``overall``. Taken only while that pick is mine on the clock and ``board`` is the session's
    (picks 1..overall-1); a newer request replaces it. The tab clicks only while the room has
    the pick on the clock, and in autopilot the drafter stands aside while it is pending.
    ValueError for anything else."""
    state = session.state
    with session.lock:
        next_overall, on_clock, made = state.next_overall, state.on_the_clock, len(state.picks)
    if not on_clock or overall != next_overall:
        raise ValueError(
            f"pick {overall} is not mine on the clock (the next pick is {next_overall})"
        )
    if board != made:
        raise ValueError(f"board {board} is not the session's: it has {made} picks")
    yid = str(yid)
    if not room.ids.known(yid):
        raise ValueError(f"unknown Yahoo player {yid}")
    with room.lock:
        if overall in room.ledger:
            raise ValueError(f"pick {overall} has been made in the room")
        if any(p.yid == yid for p in room.ledger.values()):
            raise ValueError(f"{room.ids.name(yid)} has been drafted")
        room.request = {
            "overall": overall,
            "board": board,
            "yahoo_player_id": yid,
            "player_id": room.ids.pid(yid),
            "name": room.ids.name(yid),
            **room.ids.row_name(yid),
            "t": now_iso(),
        }
    room.log.append(
        {"type": "note", "what": "draft request", "overall": overall, "board": board, "yid": yid}
    )
    return room.request


def live_request(session: Session, room: YahooRoom) -> dict[str, Any] | None:
    """The pending request, or None once its turn has ended: the pick is in the room, or the
    session has moved past it (a hand pick entered here)."""
    q = room.request
    if q is not None and (
        q["overall"] in room.ledger or session.state.next_overall != q["overall"]
    ):
        room.request = q = None
    return q


# --------------------------------------------------------------------------- events
def _event_problem(e: dict[str, Any]) -> str | None:
    """Why the API does not take a client event, or None."""
    kind = e.get("type")
    if kind not in CLIENT_EVENTS:
        return f"type {kind!r}"
    if kind in NEEDS_OVERALL and not isinstance(e.get("overall"), int):
        return f"{kind} without an integer overall"
    if kind == "control" and e.get("state") not in CONTROL_STATES:
        return f"control state {e.get('state')!r}"
    try:
        to_iso(e.get("t"))
    except (ValueError, TypeError, OverflowError, OSError):
        return "bad t"
    return None


def record_events(
    room: YahooRoom, events: list[dict[str, Any]]
) -> tuple[int, int, list[dict[str, Any]]]:
    """Store client events with the server's receive time; returns (written, ignored, shown):
    ``shown`` are the events taken, heartbeats aside, for the web app's sync panel.
    Heartbeats are kept in memory and written at most once per ``HEARTBEAT_EVERY_S``.

    An event the API does not take (a type it does not know, a server type, or one missing
    what its type needs) is dropped and counted, never the batch with it: an extension one
    event type ahead of the API must not lose the draft_attempt and pick_landed events posted
    alongside. The log gets one note per batch that dropped any."""
    clean = []
    dropped: dict[str, int] = {}
    for e in events:
        problem = _event_problem(e)
        if problem is not None:
            dropped[problem] = dropped.get(problem, 0) + 1
            continue
        clean.append({**e, "t": to_iso(e.get("t")), "src": e.get("src") or "client"})
    if dropped:
        room.log.append({"type": "note", "what": "client events ignored", "ignored": dropped})
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
        q = room.request
        failed = e["type"] == "note" and e.get("what") == "request failed"
        if failed and q is not None and e.get("overall") == q["overall"]:
            room.request = None  # the tab gave up; in autopilot the drafter takes the turn
        room.log.append(e)
        written += 1
    shown = [e for e in clean if e["type"] != "heartbeat"]
    return written, sum(dropped.values()), shown


def follow_clock(session: Session, room: YahooRoom, events: list[dict[str, Any]]) -> float | None:
    """Adopt the longest pick clock the room has shown when the attach left the plan budget
    to the clock. The attach comes from the waiting room, before Yahoo's first ``D|`` frame;
    the client carries that frame's clock on every turn_start. Returns the new budget when it
    changed."""
    if room.clock_s is None:
        return None
    seen = [
        float(e["clock_s"])
        for e in events
        if e.get("type") == "turn_start"
        and isinstance(e.get("clock_s"), int | float)
        and e["clock_s"] > room.clock_s
    ]
    if not seen:
        return None
    room.clock_s = max(seen)
    budget = plan_budget(room.clock_s)
    with session.lock:
        session.state.plan_time_limit = budget
        session.state.price_time_limit = min(PRICE_LIMIT_MAX, budget)
    room.log.append(
        {
            "type": "note",
            "t": now_iso(),
            "what": "plan_budget",
            "clock_s": room.clock_s,
            "time_limit": budget,
            "src": "api",
        }
    )
    return budget


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
            "mode": payload.get("mode"),  # before #17 the only record of the model
            # "horizon", or "roster": the single-roster fallback (picks and open slots
            # disagree; in a room that means the session and the room disagree on the draft).
            "model": payload.get("mode"),
            "priced": payload.get("priced", True),
            "branch": payload.get("branch", False),
            # A branch plan still solving when its board arrived (installed when it landed).
            "branch_late": payload.get("branch_late"),
            # The objective behind the #1 and whether a time limit stopped that solve (what a
            # later reco for the board must beat), and the pre-solves in flight while it ran.
            "top_objective": payload.get("top_objective"),
            "capped": payload.get("capped"),
            "branches_running": payload.get("branches_running"),
        }
    )
    if payload.get("mode") == "roster" and not room.roster_noted:
        room.roster_noted = True
        room.log.append(
            {
                "type": "note",
                "t": now_iso(),
                "what": "roster fallback",
                "board": int(payload["next_overall"]) - 1,
                "reason": payload.get("roster_reason"),
                "src": "api",
            }
        )


def check_teams(session: Session, room: YahooRoom, events: list[dict[str, Any]]) -> int | None:
    """Compare the team count the room's client derived from the room (``teams`` on
    turn_start) with the attach's. On the first disagreement the room goes to mirror mode and
    the log gets a loud note: every pick the session credits from then on would be wrong
    (mock 2: a 10-team room attached as 12). Returns the room's count when it disagreed."""
    if room.teams_mismatch is not None:
        return None
    said = {room.num_teams, session.state.settings.num_teams}
    seen = [
        int(e["teams"])
        for e in events
        if e.get("type") == "turn_start"
        and isinstance(e.get("teams"), int)
        and not isinstance(e.get("teams"), bool)
    ]
    wrong = next((t for t in seen if {t} != said), None)
    if wrong is None:
        return None
    room.teams_mismatch = wrong
    was = room.mode
    room.mode = "mirror"
    room.control = control_for("mirror")
    room.log.append({"type": "control", "state": room.control, "slot": room.slot, "src": "api"})
    room.log.append(
        {
            "type": "note",
            "t": now_iso(),
            "what": "team count mismatch",
            "room_teams": wrong,
            "num_teams": room.num_teams,
            "session_teams": session.state.settings.num_teams,
            "mode_was": was,
            "src": "api",
        }
    )
    session.publish("room_mode", {"draft_id": room.draft_id, "mode": "mirror"}, bump=False)
    return wrong


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
        "teams_mismatch": room.teams_mismatch,
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
        "complete": state.complete,
        "recent_lags": [{"overall": k, "lag_ms": v} for k, v in room.recent_lags],
        "request": live_request(session, room),
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
