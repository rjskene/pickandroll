"""The YAHOO SYNC scorecard (``docs/YAHOO_SYNC.md`` §1-§4) computed from a fidelity log.

Pure functions over the event list. Every one of my seat's picks that has happened gets a
reference (``ref_k``: the #1 candidate of the last recommendation solved for board ``k-1``
before the pick landed) and a label: ``compliant``, ``manual``, or the first failure that
applies in the order ``absent``, ``stale``, ``unsolved``, ``expired``, ``fallback``, ``wrong``.
"""

from __future__ import annotations

import math
from typing import Any

from ..draft.settings import pick_owner, snake_picks
from .recorder import to_ms

FAILURES = ("absent", "stale", "unsolved", "expired", "fallback", "wrong")
LABELS = ("compliant", "manual", *FAILURES)
#: Lag targets in ms (G2) and the window a manual pick must be mirrored in (G4).
LAG_TARGETS = {"p50": 1000.0, "p95": 2000.0, "max": 5000.0}
ENTRY_LEAD_S = 60.0


def stats(values: list[float]) -> dict[str, Any]:
    """Count, nearest-rank p50 and p95, and max, rounded to ms."""
    if not values:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)

    def rank(q: float) -> float:
        return ordered[max(0, math.ceil(q * len(ordered)) - 1)]

    return {
        "n": len(ordered),
        "p50": round(rank(0.5)),
        "p95": round(rank(0.95)),
        "max": round(ordered[-1]),
    }


def analyze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Everything the scorecard prints, as data."""
    attach = next((e for e in reversed(events) if e.get("type") == "attach"), None)
    if attach is None:
        raise ValueError("no attach record in the log")
    slot = int(attach["slot"])
    num_teams = int(attach.get("num_teams", 12))
    rounds = int(attach.get("rounds", 13))
    mine = snake_picks(num_teams, slot, rounds)

    room: dict[int, dict] = {}
    first_sync: dict[int, dict] = {}
    last_sync: dict[int, dict] = {}
    turns: dict[int, dict] = {}
    landed: dict[int, dict] = {}
    attempts: dict[int, list[dict]] = {}
    recos: list[dict] = []
    controls: list[dict] = []
    interventions: list[dict] = []
    conflicts: list[dict] = []
    score = None
    for e in events:
        kind = e.get("type")
        if kind == "room_pick":
            room.setdefault(int(e["overall"]), e)
        elif kind == "session_pick":
            first_sync.setdefault(int(e["overall"]), e)
            last_sync[int(e["overall"])] = e
        elif kind == "turn_start":
            turns.setdefault(int(e["overall"]), e)
        elif kind == "pick_landed":
            landed[int(e["overall"])] = e
        elif kind == "draft_attempt":
            attempts.setdefault(int(e["overall"]), []).append(e)
        elif kind == "reco":
            recos.append(e)
        elif kind == "control":
            controls.append(e)
        elif kind == "intervention":
            interventions.append(e)
        elif kind == "conflict":
            conflicts.append(e)
        elif kind == "score":
            score = e

    def control_at(t: float) -> str:
        state = "absent"
        for c in controls:
            if to_ms(c["t"]) <= t:
                state = c.get("state", state)
        return state

    # When every pick before k had reached the session: the running max of first-sync times.
    synced_by: dict[int, float] = {0: -math.inf}
    running = -math.inf
    for k in range(1, (max(room) if room else 0) + 1):
        t = to_ms(first_sync[k]["t"]) if k in first_sync else math.inf
        running = max(running, t)
        synced_by[k] = running

    lags = {k: to_ms(first_sync[k]["t"]) - to_ms(room[k]["t"]) for k in room if k in first_sync}

    rows = []
    for k in mine:
        if k not in room:
            continue
        actual = str(room[k]["yid"])
        land = landed.get(k)
        t_land = to_ms(land["t"]) if land else to_ms(room[k]["t"])
        if k in turns:
            t_turn = to_ms(turns[k]["t"])
        elif k - 1 in room:
            t_turn = to_ms(room[k - 1]["t"])
        else:
            t_turn = None
        board = [r for r in recos if int(r.get("board", -1)) == k - 1]
        ref = next((r for r in reversed(board) if to_ms(r["t"]) < t_land), None)
        ready = (to_ms(board[0]["t"]) - t_turn) if board and t_turn is not None else None
        how = land.get("how") if land else None
        ref_yid = str(ref["top_yid"]) if ref and ref.get("top_yid") is not None else None
        ref_name = ref.get("top_name") if ref else None
        # The solve's own first choice had no Yahoo id: the drafter could not take it, so the
        # best it can do is a fallback.
        hidden = {u["pid"]: u.get("name") for u in (ref or {}).get("unmapped") or []}
        top_hidden = bool(ref and ref.get("top_pid") in hidden)
        if top_hidden:
            ref_yid, ref_name = None, hidden[ref["top_pid"]]
        if how == "manual":
            label = "manual"
        elif ref_yid is not None and actual == ref_yid:
            label = "compliant"
        elif control_at(t_turn if t_turn is not None else t_land) != "armed":
            label = "absent"
        elif synced_by.get(k - 1, math.inf) > t_land:
            label = "stale"
        elif ref is None:
            label = "unsolved"
        elif how in ("expiry", "autopick"):
            label = "expired"
        elif top_hidden or actual in {str(c) for c in ref.get("cands") or []}:
            label = "fallback"
        else:
            label = "wrong"
        if land and land.get("ms_from_turn") is not None:
            to_land = float(land["ms_from_turn"])
        elif land and t_turn is not None:
            to_land = t_land - t_turn
        else:
            to_land = None
        rows.append(
            {
                "overall": k,
                "round": pick_owner(num_teams, k)[0],
                "ref_yid": ref_yid,
                "ref_pid": ref.get("top_pid") if ref else None,
                "ref_name": ref_name,
                "actual_yid": actual,
                "actual_name": room[k].get("name"),
                "label": label,
                "how": how,
                "lag_ms": None if k not in lags else round(lags[k]),
                "turn_to_land_ms": None if to_land is None else round(to_land),
                "reco_ready_ms": None if ready is None else round(ready),
                "attempts": len(attempts.get(k, [])),
            }
        )

    counts = {label: sum(1 for r in rows if r["label"] == label) for label in LABELS}
    decided = len(rows) - counts["manual"]

    # G1: the session's latest pick at each overall is the room's player, by Yahoo id. A
    # stand-in holds another player in his place, so it does not agree until it is repaired.
    agree = sum(
        1
        for k, e in room.items()
        if k in last_sync
        and str(last_sync[k].get("yid")) == str(e["yid"])
        and not last_sync[k].get("standin")
    )
    lag = stats(list(lags.values()))
    manual_rows = [r for r in rows if r["label"] == "manual"]
    manual_ok = 0
    for r in manual_rows:
        t_manual = to_ms(landed[r["overall"]]["t"])
        late = [a for a in attempts.get(r["overall"], []) if to_ms(a["t"]) > t_manual]
        mirrored = r["lag_ms"] is not None and r["lag_ms"] <= LAG_TARGETS["max"]
        manual_ok += int(not late and mirrored)
    # G6 counts from the client's first sign of life in the draft room; the control the API
    # writes at attach is only a fallback (the attach can come minutes before the room).
    entry = next(
        (
            e
            for e in events
            if e.get("type") in ("control", "heartbeat") and e.get("src", "client") != "api"
        ),
        None,
    )
    entry_from = "client" if entry else None
    if entry is None:
        entry = next((c for c in controls if c.get("state") in ("armed", "mirror")), None)
        entry_from = "attach" if entry else None
    lead = (to_ms(turns[1]["t"]) - to_ms(entry["t"])) / 1000.0 if entry and 1 in turns else None
    landed_rows = [r for r in rows if r["label"] != "manual" and r["overall"] in landed]
    per_pick = [r["attempts"] for r in landed_rows]
    total = num_teams * rounds
    return {
        "draft_id": attach.get("draft_id"),
        "slot": slot,
        "num_teams": num_teams,
        "rounds": rounds,
        "mode": attach.get("mode"),
        "control": control_at(math.inf),
        "picks_seen": len(room),
        "total_picks": total,
        "compliance": {
            "compliant": counts["compliant"],
            "denominator": decided,
            "manual": counts["manual"],
            "my_picks_seen": len(rows),
        },
        "counts": counts,
        "guardrails": {
            "G1": {"agree": agree, "of": len(room), "total": total},
            "G2": lag,
            "G3": {"interventions": len(interventions)},
            "G4": {"respected": manual_ok, "manual": len(manual_rows)},
            "G5": {"autopick_flips": sum(1 for c in controls if c.get("reason") == "autopick")},
            "G6": {
                "entry_lead_s": None if lead is None else round(lead, 1),
                "entry_from": entry_from,
            },
        },
        "diagnostics": {
            "D1": stats([r["reco_ready_ms"] for r in rows if r["reco_ready_ms"] is not None]),
            "D2": stats(
                [r["turn_to_land_ms"] for r in landed_rows if r["turn_to_land_ms"] is not None]
            ),
            "D3": stats([float(r["solve_ms"]) for r in recos if r.get("solve_ms") is not None]),
            "D4": {
                "mean": round(sum(per_pick) / len(per_pick), 2) if per_pick else None,
                "max": max(per_pick) if per_pick else None,
            },
            "D5": None
            if score is None
            else {k: score.get(k) for k in ("wins", "benchmark", "vs_benchmark", "best")},
        },
        "conflicts": len(conflicts),
        "standins": sum(1 for e in last_sync.values() if e.get("standin")),
        "rows": rows,
        "last_room_pick": room[max(room)] if room else None,
        "last_reco": recos[-1] if recos else None,
    }


def guardrail_pass(card: dict[str, Any]) -> dict[str, bool | None]:
    """Pass/fail per guardrail; ``None`` when there is nothing to judge yet."""
    g = card["guardrails"]
    complete = card["picks_seen"] >= card["total_picks"]
    lag = g["G2"]
    return {
        "G1": (g["G1"]["agree"] == card["total_picks"]) if complete else None,
        "G2": None
        if not lag["n"]
        else all(lag[k] <= LAG_TARGETS[k] for k in ("p50", "p95", "max")),
        "G3": g["G3"]["interventions"] == 0,
        "G4": None if not g["G4"]["manual"] else g["G4"]["respected"] == g["G4"]["manual"],
        "G5": g["G5"]["autopick_flips"] == 0,
        "G6": None if g["G6"]["entry_lead_s"] is None else g["G6"]["entry_lead_s"] >= ENTRY_LEAD_S,
    }


def markdown(card: dict[str, Any]) -> str:
    """The §4 scorecard, ready to paste into the tracker."""
    c = card["compliance"]
    g = card["guardrails"]
    d = card["diagnostics"]
    ok = guardrail_pass(card)

    def mark(key: str) -> str:
        return {True: "pass", False: "**FAIL**", None: "n/a"}[ok[key]]

    def ms(s: dict[str, Any]) -> str:
        if not s.get("n"):
            return "n/a"
        return f"p50 {s['p50']} / p95 {s['p95']} / max {s['max']} ms (n {s['n']})"

    lines = [
        f"## Room {card['draft_id']}: fidelity scorecard",
        "",
        (
            f"Slot {card['slot']} of {card['num_teams']}, {card['rounds']} rounds, mode "
            f"{card['mode']}, control now {card['control']}; picks seen "
            f"{card['picks_seen']}/{card['total_picks']}."
        ),
        "",
        (
            f"**Compliance {c['compliant']}/{c['denominator']}** (manual {c['manual']}, "
            f"my picks seen {c['my_picks_seen']} of {card['rounds']})"
        ),
        "",
        "| label | " + " | ".join(LABELS) + " |",
        "|---|" + "---|" * len(LABELS),
        "| picks | " + " | ".join(str(card["counts"][k]) for k in LABELS) + " |",
        "",
        "| guardrail | value | target | result |",
        "|---|---|---|---|",
        (
            f"| G1 board agreement | {g['G1']['agree']}/{g['G1']['of']} "
            f"(of {g['G1']['total']}) | {g['G1']['total']}/{g['G1']['total']} | {mark('G1')} |"
        ),
        f"| G2 sync lag | {ms(g['G2'])} | p50 ≤ 1000, p95 ≤ 2000, max ≤ 5000 | {mark('G2')} |",
        f"| G3 interventions | {g['G3']['interventions']} | 0 | {mark('G3')} |",
        f"| G4 manual respected | {g['G4']['respected']}/{g['G4']['manual']} | 1/1 | {mark('G4')} |",
        f"| G5 autopick flips | {g['G5']['autopick_flips']} | 0 | {mark('G5')} |",
        (
            f"| G6 entry lead | {_fmt(g['G6']['entry_lead_s'], ' s')}"
            f"{' (from attach)' if g['G6']['entry_from'] == 'attach' else ''} | ≥ 60 s "
            f"| {mark('G6')} |"
        ),
        "",
        "| diagnostic | value |",
        "|---|---|",
        f"| D1 reco ready vs turn start | {ms(d['D1'])} |",
        f"| D2 turn to land | {ms(d['D2'])} |",
        f"| D3 solve time | {ms(d['D3'])} |",
        (
            f"| D4 attempts per landed pick | mean {_fmt(d['D4']['mean'])}, "
            f"max {_fmt(d['D4']['max'])} |"
        ),
        f"| D5 final expected categories won | {_score(d['D5'])} |",
        "",
        f"Stand-ins {card['standins']}, conflicts {card['conflicts']}.",
        "",
        "| pick | rd | ref | actual | label | lag ms | turn→land ms | reco ready ms | tries |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in card["rows"]:
        lines.append(
            f"| {r['overall']} | {r['round']} | {r['ref_name'] or r['ref_yid'] or '-'} "
            f"| {r['actual_name'] or r['actual_yid']} | {r['label']} | {_fmt(r['lag_ms'])} "
            f"| {_fmt(r['turn_to_land_ms'])} | {_fmt(r['reco_ready_ms'])} | {r['attempts']} |"
        )
    return "\n".join(lines) + "\n"


def status(card: dict[str, Any]) -> dict[str, Any]:
    """The mid-draft summary the drone checks once a round."""
    last = card["last_room_pick"]
    reco = card["last_reco"]
    return {
        "draft_id": card["draft_id"],
        "slot": card["slot"],
        "control": card["control"],
        "picks_seen": card["picks_seen"],
        "lag_ms": card["guardrails"]["G2"],
        "last_room_pick": None
        if last is None
        else {k: last.get(k) for k in ("overall", "yid", "name", "slot", "t")},
        "last_reco": None
        if reco is None
        else {k: reco.get(k) for k in ("board", "fresh", "top_yid", "top_name", "solve_ms", "t")},
        "compliance": card["compliance"],
        "counts": card["counts"],
        "my_picks": [
            {k: r[k] for k in ("overall", "label", "ref_name", "actual_name", "lag_ms")}
            for r in card["rows"]
        ],
        "conflicts": card["conflicts"],
        "standins": card["standins"],
    }


def _fmt(value: Any, unit: str = "") -> str:
    return "-" if value is None else f"{value}{unit}"


def _score(score: dict[str, Any] | None) -> str:
    if not score:
        return "n/a"
    out = f"{score.get('wins')}"
    if score.get("benchmark") is not None:
        out += f" (benchmark {score['benchmark']}, {score.get('vs_benchmark'):+})"
    return out
