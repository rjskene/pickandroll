"""Tier 1 replay: feed a recorded Yahoo room into the API (``docs/YAHOO_SYNC.md`` §5).

A fixture is the pick order of a real room (overall, Yahoo id, Board label, team) and the ms
time each pick's socket message reached the page that recorded it. Picks recorded before the
hook was installed have no time; they are spaced at the median recorded gap. The replay
attaches the room, waits ``lead`` seconds (the entry lead before pick 1, when the first plan
is solved), posts each pick the moment the room would have sent it (``speed`` times faster,
or back to back with ``speed=None``), marks pick 1 and each of my turns with a
``turn_start`` and asks for the plan as the extension would, then reads back the status and
the scorecard.

A session with keepers (``docs/KEEPERS.md``) names its keeper slots in the attach response;
my keeper slots are not turns. ``keepers`` says how the room sends the keepers' picks, since
that is only known on the night: ``"socket"`` as the slots pass, like any pick; ``"history"``
all at once on connect, as Yahoo's history frame would; ``"none"``, never.

``client`` is anything with httpx's ``get``/``post``: a FastAPI ``TestClient``, or an
``httpx.Client`` pointed at a running API.
"""

from __future__ import annotations

import csv
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

from ..draft.settings import pick_owner, snake_picks

DEFAULT_GAP_MS = 5000.0
KeeperFrames = Literal["socket", "history", "none"]


@dataclass(frozen=True)
class FixturePick:
    overall: int
    yahoo_player_id: str
    label: str
    team: str
    t_ms: int | None


def load_fixture(path: Path) -> list[FixturePick]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        rows = [
            FixturePick(
                overall=int(r["overall"]),
                yahoo_player_id=str(r["yahoo_player_id"]),
                label=r.get("label", ""),
                team=r.get("team", ""),
                t_ms=int(r["t_ms"]) if r.get("t_ms") else None,
            )
            for r in csv.DictReader(fh)
        ]
    rows.sort(key=lambda p: p.overall)
    if [p.overall for p in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"{path}: overall picks must run 1..{len(rows)}")
    return rows


def timeline(picks: list[FixturePick]) -> list[float]:
    """Milliseconds from pick 1 for every pick: recorded times where known, the median gap
    between consecutive recorded picks elsewhere."""
    known = [(i, float(p.t_ms)) for i, p in enumerate(picks) if p.t_ms is not None]
    gaps = [b - a for (i, a), (j, b) in pairwise(known) if j == i + 1]
    gap = statistics.median(gaps) if gaps else DEFAULT_GAP_MS
    if not known:
        return [i * gap for i in range(len(picks))]
    times: list[float] = [0.0] * len(picks)
    first_i, first_t = known[0]
    for i in range(first_i + 1):
        times[i] = first_t - (first_i - i) * gap
    for (i, a), (j, b) in pairwise(known):
        for k in range(i, j + 1):
            times[k] = a + (b - a) * (k - i) / (j - i)
    last_i, last_t = known[-1]
    for k in range(last_i, len(picks)):
        times[k] = last_t + (k - last_i) * gap
    return [t - times[0] for t in times]


def replay(
    client: Any,
    picks: list[FixturePick],
    *,
    draft_id: str,
    slot: int,
    num_teams: int = 12,
    session: dict[str, Any] | None = None,
    session_id: str | None = None,
    players_file: str | None = None,
    mode: str = "mirror",
    solve: dict[str, Any] | None = None,
    speed: float | None = None,
    plan_wait: float = 10.0,
    lead: float = 0.0,
    keepers: KeeperFrames = "socket",
) -> dict[str, Any]:
    """Replay ``picks`` into the room ``draft_id``; returns the attach response, the plan
    served at each of my turns, the status and the scorecard."""
    rounds = len(picks) // num_teams
    body: dict[str, Any] = {
        "draft_id": draft_id,
        "slot": slot,
        "num_teams": num_teams,
        "mode": mode,
        **(solve or {}),
    }
    if session_id is not None:
        body["session_id"] = session_id
    if session is not None:
        body["session"] = session
    if players_file is not None:
        body["players_file"] = players_file
    attach = _ok(client.post("/rooms", json=body))
    kept = {int(k["overall"]) for k in attach.get("keepers") or []}
    mine = set(snake_picks(num_teams, slot, rounds)) - kept
    # The client is in the draft room from here (G6 counts from this control).
    state = "armed" if mode == "autopilot" else "mirror"
    _ok(
        client.post(
            f"/rooms/{draft_id}/events",
            json={"events": [{"type": "control", "state": state, "slot": slot}]},
        )
    )

    def send(p: FixturePick, src: str) -> None:
        _ok(
            client.post(
                f"/rooms/{draft_id}/picks",
                json={
                    "picks": [
                        {
                            "overall": p.overall,
                            "yahoo_player_id": p.yahoo_player_id,
                            "slot": pick_owner(num_teams, p.overall)[1],
                            "t_room": round(time.time() * 1000.0),
                            "src": src,
                        }
                    ]
                },
            )
        )

    if keepers == "history":
        for p in picks:
            if p.overall in kept:
                send(p, "history")
    if lead > 0:
        time.sleep(lead)
    offsets = timeline(picks)
    started = time.monotonic()
    plans: list[dict[str, Any]] = []

    def turn(overall: int) -> None:
        owner = pick_owner(num_teams, overall)[1]
        _ok(
            client.post(
                f"/rooms/{draft_id}/events",
                json={
                    "events": [
                        {"type": "turn_start", "overall": overall, "slot": owner, "clock_s": 30}
                    ]
                },
            )
        )
        if overall in mine:
            plan = _ok(client.get(f"/rooms/{draft_id}/plan", params={"wait": plan_wait}))
            top = plan["candidates"][0] if plan["candidates"] else {}
            plans.append(
                {
                    "overall": overall,
                    "fresh": plan["fresh"],
                    "board": plan["board"],
                    "waited_ms": plan["waited_ms"],
                    "top": top.get("yahoo_player_id"),
                    "top_name": top.get("name"),
                    "candidates": len(plan["candidates"]),
                    "second": None if plan["second"] is None else len(plan["second"]),
                }
            )

    def on_clock(k: int) -> int:
        """The pick the room puts on the clock after pick k - 1: k, or past keeper slots whose
        picks it never sends as they pass."""
        if keepers != "socket":
            while k in kept:
                k += 1
        return k

    turn(on_clock(1))
    for i, p in enumerate(picks):
        if p.overall in kept and keepers != "socket":
            continue
        if speed:
            delay = started + offsets[i] / 1000.0 / speed - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        send(p, "socket")
        k = on_clock(p.overall + 1)
        if k in mine:
            turn(k)
    status = _ok(client.get(f"/rooms/{draft_id}/status"))
    card = _ok(client.get(f"/rooms/{draft_id}/fidelity"))
    return {"attach": attach, "plans": plans, "status": status, "scorecard": card}


def settled_replay(
    client: Any,
    picks: list[FixturePick],
    *,
    draft_id: str,
    slot: int,
    rank: Mapping[str, float],
    num_teams: int = 12,
    session: dict[str, Any] | None = None,
    players_file: str | None = None,
    solve: dict[str, Any] | None = None,
    plan_wait: float = 20.0,
    patience: int = 6,
) -> dict[str, Any]:
    """The value and compliance proxy for #13: the room's other picks in fixture order with no
    clock, and my picks drafted the way the armed drafter drafts them, each the top of the
    first fresh plan for its board (waiting as long as that takes). A fixture pick whose player
    is already gone (I took him) shifts to the best available by ``rank`` (Yahoo id -> o_rank,
    the order Yahoo's autodraft follows). Returns my picks, the scorecard and the final score."""
    rounds = len(picks) // num_teams
    mine = set(snake_picks(num_teams, slot, rounds))
    body: dict[str, Any] = {
        "draft_id": draft_id,
        "slot": slot,
        "num_teams": num_teams,
        "mode": "autopilot",
        **(solve or {}),
    }
    if session is not None:
        body["session"] = session
    if players_file is not None:
        body["players_file"] = players_file
    attach = _ok(client.post("/rooms", json=body))
    _ok(
        client.post(
            f"/rooms/{draft_id}/events",
            json={"events": [{"type": "control", "state": "armed", "slot": slot}]},
        )
    )
    ranked = sorted((r, yid) for yid, r in rank.items() if r and r > 0)
    taken: set[str] = set()
    drafted: list[dict[str, Any]] = []
    shifted = 0

    def post(overall: int, yid: str) -> None:
        _ok(
            client.post(
                f"/rooms/{draft_id}/picks",
                json={
                    "picks": [
                        {
                            "overall": overall,
                            "yahoo_player_id": yid,
                            "slot": pick_owner(num_teams, overall)[1],
                            "t_room": round(time.time() * 1000.0),
                            "src": "socket",
                        }
                    ]
                },
            )
        )
        taken.add(yid)

    for p in picks:
        k = p.overall
        if k in mine:
            _ok(
                client.post(
                    f"/rooms/{draft_id}/events",
                    json={
                        "events": [
                            {"type": "turn_start", "overall": k, "slot": slot, "clock_s": 30}
                        ]
                    },
                )
            )
            started = time.monotonic()
            plan: dict[str, Any] = {}
            for _ in range(patience):
                plan = _ok(client.get(f"/rooms/{draft_id}/plan", params={"wait": plan_wait}))
                if plan["fresh"]:
                    break
            top = next(
                (c for c in plan.get("candidates", []) if str(c["yahoo_player_id"]) not in taken),
                None,
            )
            if top is None:
                raise RuntimeError(f"no candidate to draft at pick {k}")
            yid = str(top["yahoo_player_id"])
            _ok(
                client.post(
                    f"/rooms/{draft_id}/events",
                    json={
                        "events": [{"type": "pick_landed", "overall": k, "yid": yid, "how": "row"}]
                    },
                )
            )
            post(k, yid)
            drafted.append(
                {
                    "overall": k,
                    "yid": yid,
                    "name": top.get("name"),
                    "fresh": plan["fresh"],
                    "waited_s": round(time.monotonic() - started, 1),
                }
            )
            continue
        yid = str(p.yahoo_player_id)
        if yid in taken:
            yid = next(y for _, y in ranked if y not in taken)
            shifted += 1
        post(k, yid)
    status = _ok(client.get(f"/rooms/{draft_id}/status"))
    card = _ok(client.get(f"/rooms/{draft_id}/fidelity"))
    score = _ok(client.get(f"/sessions/{attach['session_id']}/score"))
    return {
        "attach": attach,
        "mine": drafted,
        "shifted": shifted,
        "status": status,
        "scorecard": card,
        "score": score,
    }


def _ok(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{response.request.method} {response.request.url}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return response.json()
