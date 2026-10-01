"""Tier 1 replay: feed a recorded Yahoo room into the API (``docs/YAHOO_SYNC.md`` §5).

A fixture is the pick order of a real room (overall, Yahoo id, Board label, team) and the ms
time each pick's socket message reached the page that recorded it. Picks recorded before the
hook was installed have no time; they are spaced at the median recorded gap. The replay
attaches the room, posts each pick the moment the room would have sent it (``speed`` times
faster, or back to back with ``speed=None``), marks pick 1 and each of my turns with a
``turn_start`` and asks for the plan as the extension would, then reads back the status and
the scorecard.

``client`` is anything with httpx's ``get``/``post``: a FastAPI ``TestClient``, or an
``httpx.Client`` pointed at a running API.
"""

from __future__ import annotations

import csv
import statistics
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

from ..draft.settings import pick_owner, snake_picks

DEFAULT_GAP_MS = 5000.0


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
) -> dict[str, Any]:
    """Replay ``picks`` into the room ``draft_id``; returns the attach response, the plan
    served at each of my turns, the status and the scorecard."""
    rounds = len(picks) // num_teams
    mine = set(snake_picks(num_teams, slot, rounds))
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

    turn(1)
    for i, p in enumerate(picks):
        if speed:
            delay = started + offsets[i] / 1000.0 / speed - time.monotonic()
            if delay > 0:
                time.sleep(delay)
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
                            "src": "socket",
                        }
                    ]
                },
            )
        )
        if p.overall + 1 in mine:
            turn(p.overall + 1)
    status = _ok(client.get(f"/rooms/{draft_id}/status"))
    card = _ok(client.get(f"/rooms/{draft_id}/fidelity"))
    return {"attach": attach, "plans": plans, "status": status, "scorecard": card}


def _ok(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(
            f"{response.request.method} {response.request.url}: "
            f"{response.status_code} {response.text[:300]}"
        )
    return response.json()
