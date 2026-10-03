"""The YAHOO SYNC scorecard (``docs/YAHOO_SYNC.md`` §1-§4) computed from a fidelity log.

Pure functions over the event list. Every one of my seat's picks that has happened gets a
reference (``ref_k``: the #1 candidate of the recommendation for board ``k-1`` the drafter acted
on, the last one logged by its first draft attempt, else before the pick landed) and a label:
``compliant``, ``manual``, or the first failure that applies in the order ``absent``, ``stale``,
``unsolved``, ``expired``, ``fallback``, ``wrong``. ``final_k`` is the last recommendation for
board ``k-1`` before the pick landed; a turn whose ``final_k`` has another #1 than ``ref_k`` is
reco churn (D6).
"""

from __future__ import annotations

import math
from typing import Any

from ..draft.settings import pick_owner, snake_picks
from .recorder import to_ms

FAILURES = ("absent", "stale", "unsolved", "expired", "fallback", "wrong")
#: How a pick lands when the drafter made it (the queue counts: Yahoo took who it set).
DRAFTED = frozenset({"row", "queue", "search"})
LABELS = ("compliant", "manual", *FAILURES)
#: Lag targets in ms (G2) and the window a manual pick must be mirrored in (G4).
LAG_TARGETS = {"p50": 1000.0, "p95": 2000.0, "max": 5000.0}
ENTRY_LEAD_S = 45.0
#: How a turn's board was covered ahead (D1): a hit is a branch solved before the turn started,
#: pending one still solving then, a miss no branch (or a capped one, which the live solve prices).
PRESOLVE_CLASSES = ("hit", "pending", "miss")
#: For logs from before the API recorded ``branch_late``: a solved branch is installed when the API
#: applies pick k-1, within tens of ms of the turn start (20-90 ms in the gap-15 cells).
BRANCH_READY_MS = 250.0


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


def reco_kind(reco: dict[str, Any] | None) -> str | None:
    """``priced`` (exact prices), ``converged`` (a pre-solved branch plan) or ``plan`` (an early
    plan priced to first order), with ``capped`` when the log says a time limit stopped it."""
    if reco is None:
        return None
    if reco.get("priced", True):
        kind = "priced"
    elif reco.get("branch"):
        kind = "converged"
    else:
        kind = "plan"
    return f"{kind}, capped" if reco.get("capped") else kind


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
    probe = None  # the queue probe's note: what Yahoo did with a star on my turn
    mismatch = None  # the API's note when the room showed another team count (#17)
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
        elif kind == "note" and e.get("what") == "queue_probe":
            probe = e
        elif kind == "note" and e.get("what") == "team count mismatch":
            mismatch = mismatch or e

    # When armed turns acted (act_at_s, #10), as the API's control events set it, in order.
    acts: list[int | None] = []
    for c in controls:
        if c.get("src") == "api" and "act_at_s" in c and (not acts or acts[-1] != c["act_at_s"]):
            acts.append(c["act_at_s"])

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
    # A pick the room made before the first attach waited for a room that did not exist yet:
    # a process miss, not the build's lag. G2 judges the picks after it; G2 over all is kept.
    attached_at = to_ms(next(e for e in events if e.get("type") == "attach")["t"])
    pre_attach = {k for k in room if to_ms(room[k]["t"]) < attached_at}

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
        final = next((r for r in reversed(board) if to_ms(r["t"]) < t_land), None)
        # The reco the drafter acted on: the last one by its first attempt. An attempt logged
        # after the landing (the click settled late) is judged at the landing.
        tries = attempts.get(k, [])
        t_attempt = to_ms(tries[0]["t"]) if tries else None
        if t_attempt is not None and t_attempt < t_land:
            ref = next((r for r in reversed(board) if to_ms(r["t"]) <= t_attempt), None)
        else:
            ref = final
        acted = tries[0].get("board") if tries else None
        ready = (to_ms(board[0]["t"]) - t_turn) if board and t_turn is not None else None
        presolve = _presolve_class(board[0] if board else None, ready)
        how = land.get("how") if land else None
        ref_yid = str(ref["top_yid"]) if ref and ref.get("top_yid") is not None else None
        ref_name = ref.get("top_name") if ref else None
        # The solve's own first choice had no Yahoo id: the drafter could not take it, so the
        # best it can do is a fallback.
        hidden = {u["pid"]: u.get("name") for u in (ref or {}).get("unmapped") or []}
        top_hidden = bool(ref and ref.get("top_pid") in hidden)
        if top_hidden:
            ref_yid, ref_name = None, hidden[ref["top_pid"]]
        # The drafter made the pick: a click or the queue it set, not Yahoo's autopick at expiry
        # (which can happen to equal ref_k and is never compliant).
        drafted = how in DRAFTED or any(
            str(a.get("yid")) == actual and to_ms(a["t"]) < t_land for a in tries
        )
        if how == "manual":
            label = "manual"
        elif drafted and ref_yid is not None and actual == ref_yid:
            label = "compliant"
        elif control_at(t_turn if t_turn is not None else t_land) != "armed":
            label = "absent"
        elif synced_by.get(k - 1, math.inf) > t_land or (acted is not None and int(acted) < k - 1):
            # The session was behind, or the drafter read an older board's plan.
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
        churn = bool(ref and final and final.get("top_pid") != ref.get("top_pid"))
        # Where the actual pick stood in the acted reco's candidates (1 = its top), if at all.
        cands = [str(c) for c in (ref or {}).get("cands") or []]
        rank = cands.index(actual) + 1 if actual in cands else None
        cause = None
        if churn:
            a, b = (ref or {}).get("top_objective"), (final or {}).get("top_objective")
            if a is not None and b is not None and b > a + 1e-9:
                cause = "better plan after action"
        rows.append(
            {
                "overall": k,
                "round": pick_owner(num_teams, k)[0],
                "ref_yid": ref_yid,
                "ref_pid": ref.get("top_pid") if ref else None,
                "ref_name": ref_name,
                "ref_kind": reco_kind(ref),
                "acted_board": None if acted is None else int(acted),
                "final_yid": (
                    str(final["top_yid"]) if final and final.get("top_yid") is not None else None
                ),
                "final_pid": final.get("top_pid") if final else None,
                "final_name": final.get("top_name") if final else None,
                "final_kind": reco_kind(final),
                "churn": churn,
                "churn_cause": cause,
                "ref_objective": ref.get("top_objective") if ref else None,
                "final_objective": final.get("top_objective") if final else None,
                "actual_yid": actual,
                "actual_name": room[k].get("name"),
                "actual_rank": rank,
                "label": label,
                "how": how,
                "lag_ms": None if k not in lags else round(lags[k]),
                "turn_to_land_ms": None if to_land is None else round(to_land),
                "reco_ready_ms": None if ready is None else round(ready),
                "presolve": presolve,
                "attempts": len(attempts.get(k, [])),
            }
        )

    counts = {label: sum(1 for r in rows if r["label"] == label) for label in LABELS}
    decided = len(rows) - counts["manual"]
    # Diagnostic: compliance had the drafter been judged against the last reco before landing.
    against_final = sum(
        1
        for r in rows
        if r["label"] != "manual"
        and r["final_yid"] is not None
        and r["actual_yid"] == r["final_yid"]
    )
    priced = [r for r in recos if r.get("priced", True) and r.get("solve_ms") is not None]
    roster = [r for r in recos if (r.get("model") or r.get("mode")) == "roster"]

    # G1: the session's latest pick at each overall is the room's player, by Yahoo id. A
    # stand-in holds another player in his place, so it does not agree until it is repaired.
    agree = sum(
        1
        for k, e in room.items()
        if k in last_sync
        and str(last_sync[k].get("yid")) == str(e["yid"])
        and not last_sync[k].get("standin")
    )
    lag = stats([v for k, v in lags.items() if k not in pre_attach])
    lag_all = {**stats(list(lags.values())), "pre_attach": len(pre_attach)}
    manual_rows = [r for r in rows if r["label"] == "manual"]
    manual_ok = 0
    for r in manual_rows:
        t_manual = to_ms(landed[r["overall"]]["t"])
        late = [a for a in attempts.get(r["overall"], []) if to_ms(a["t"]) > t_manual]
        mirrored = r["lag_ms"] is not None and r["lag_ms"] <= LAG_TARGETS["max"]
        manual_ok += int(not late and mirrored)
    # G6 counts from the client's first sign of life in the draft room (its "entered" note, or
    # the earliest client event by time: events written before the attach arrive after it); the
    # control the API writes at attach is only a fallback (the attach can come minutes before
    # the room).
    entry = min(
        (
            e
            for e in events
            if (e.get("type") in ("control", "heartbeat") and e.get("src", "client") != "api")
            or (e.get("type") == "note" and e.get("src") == "client")
        ),
        key=lambda e: to_ms(e["t"]),
        default=None,
    )
    entry_from = "client" if entry else None
    if entry is None:
        entry = next((c for c in controls if c.get("state") in ("armed", "mirror")), None)
        entry_from = "attach" if entry else None
    lead = (to_ms(turns[1]["t"]) - to_ms(entry["t"])) / 1000.0 if entry and 1 in turns else None
    # G7: the content script's timers run on the page's Worker (a DOM timer in a hidden tab can
    # sleep through the pick clock).
    beats = [
        e
        for e in events
        if e.get("type") == "heartbeat"
        and e.get("src", "client") != "api"
        and to_ms(e["t"]) >= attached_at
    ]
    off = [e for e in beats if e.get("worker") is not True]
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
            "against_final": against_final,
        },
        "counts": counts,
        "guardrails": {
            "G1": {"agree": agree, "of": len(room), "total": total},
            "G2": lag,
            "G2_all": lag_all,
            "G3": {"interventions": len(interventions)},
            "G4": {"respected": manual_ok, "manual": len(manual_rows)},
            "G5": {"autopick_flips": sum(1 for c in controls if c.get("reason") == "autopick")},
            "G6": {
                "entry_lead_s": None if lead is None else round(lead, 1),
                "entry_from": entry_from,
            },
            "G7": {
                "heartbeats": len(beats),
                "worker_off": len(off),
                "first_off": min((e["t"] for e in off), key=to_ms, default=None),
            },
        },
        "diagnostics": {
            "D1": stats([r["reco_ready_ms"] for r in rows if r["reco_ready_ms"] is not None]),
            # Hits, pending branches and misses: three populations under one median.
            **{
                f"D1_{kind}": stats(
                    [
                        r["reco_ready_ms"]
                        for r in rows
                        if r["reco_ready_ms"] is not None and r["presolve"] == kind
                    ]
                )
                for kind in PRESOLVE_CLASSES
            },
            "D2": stats(
                [r["turn_to_land_ms"] for r in landed_rows if r["turn_to_land_ms"] is not None]
            ),
            "act_at_s": acts,
            # Exactly priced solves (all of them before #13), then the plan-only early ones
            # and the pre-solved plans installed with no solve at all.
            "D3": stats(
                [
                    float(r["solve_ms"])
                    for r in recos
                    if r.get("priced", True) and r.get("solve_ms") is not None
                ]
            ),
            "D3_plan": {
                **stats(
                    [
                        float(r["solve_ms"])
                        for r in recos
                        if not r.get("priced", True)
                        and not r.get("branch")
                        and r.get("solve_ms") is not None
                    ]
                ),
                "branch": sum(1 for r in recos if r.get("branch")),
            },
            # Priced solves while pre-solves ran in the background, and with none running (only
            # in logs that record it).
            "D3_busy": stats(
                [float(r["solve_ms"]) for r in priced if (r.get("branches_running") or 0) > 0]
            ),
            "D3_idle": stats(
                [float(r["solve_ms"]) for r in priced if r.get("branches_running") == 0]
            ),
            "D4": {
                "mean": round(sum(per_pick) / len(per_pick), 2) if per_pick else None,
                "max": max(per_pick) if per_pick else None,
            },
            "D5": None
            if score is None
            else {k: score.get(k) for k in ("wins", "benchmark", "vs_benchmark", "best")},
            "D6": {
                "churn": sum(1 for r in rows if r["churn"]),
                "picks": [r["overall"] for r in rows if r["churn"]],
            },
            # Recos of the single-roster fallback (the session's picks and open slots
            # disagree; in a room, the session and the room disagree on the draft). Goal 0.
            "roster": {
                "recos": len(roster),
                "boards": sorted({int(r["board"]) for r in roster if r.get("board") is not None}),
            },
        },
        "conflicts": len(conflicts),
        "standins": sum(1 for e in last_sync.values() if e.get("standin")),
        "queue_probe": None
        if probe is None
        else {
            k: probe.get(k)
            for k in (
                "overall",
                "yid",
                "name",
                "outcome",
                "control",
                "panel",
                "panel_found",
                "controls",
            )
        },
        "teams": _teams_seen(turns, num_teams, mismatch),
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
        "G7": None if not g["G7"]["heartbeats"] else g["G7"]["worker_off"] == 0,
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
        (
            f"| G2 over all picks, {g['G2_all']['pre_attach']} before the attach "
            f"| {ms(g['G2_all'])} | reported | - |"
        ),
        f"| G3 interventions | {g['G3']['interventions']} | 0 | {mark('G3')} |",
        f"| G4 manual respected | {g['G4']['respected']}/{g['G4']['manual']} | 1/1 | {mark('G4')} |",
        f"| G5 autopick flips | {g['G5']['autopick_flips']} | 0 | {mark('G5')} |",
        (
            f"| G6 entry lead | {_fmt(g['G6']['entry_lead_s'], ' s')}"
            f"{' (from attach)' if g['G6']['entry_from'] == 'attach' else ''} "
            f"| ≥ {ENTRY_LEAD_S:.0f} s | {mark('G6')} |"
        ),
        (
            f"| G7 client timers on the Worker | {g['G7']['worker_off']} of "
            f"{g['G7']['heartbeats']} heartbeats without"
            f"{', first at ' + str(g['G7']['first_off']) if g['G7']['first_off'] else ''} "
            f"| 0 | {mark('G7')} |"
        ),
        "",
        "| diagnostic | value |",
        "|---|---|",
        f"| D1 reco ready vs turn start | {ms(d['D1'])} |",
        f"| D1, hits (branch solved before the turn) | {ms(d['D1_hit'])} |",
        f"| D1, pending (branch still solving at the turn) | {ms(d['D1_pending'])} |",
        f"| D1, misses (no branch) | {ms(d['D1_miss'])} |",
        f"| D2 turn to land | {ms(d['D2'])}; armed turns act {_act(d['act_at_s'])} |",
        f"| D3 solve time, priced | {ms(d['D3'])} |",
        (
            f"| D3 plan only (early), and pre-solved plans installed | {ms(d['D3_plan'])}; "
            f"pre-solved {d['D3_plan']['branch']} |"
        ),
        f"| D3 priced, pre-solves running | {ms(d['D3_busy'])} |",
        f"| D3 priced, no pre-solve running | {ms(d['D3_idle'])} |",
        (
            f"| D4 attempts per landed pick | mean {_fmt(d['D4']['mean'])}, "
            f"max {_fmt(d['D4']['max'])} |"
        ),
        f"| D5 final expected categories won | {_score(d['D5'])} |",
        (
            f"| D6 reco churn (target 0) | {d['D6']['churn']}"
            f"{' at ' + ', '.join(str(k) for k in d['D6']['picks']) if d['D6']['picks'] else ''} |"
        ),
        f"| Recos from the roster fallback (goal 0 in a room) | {_roster(d['roster'])} |",
        "",
        (
            f"Compliance against the final reco (diagnostic): "
            f"{c['against_final']}/{c['denominator']}."
        ),
        "",
        f"Stand-ins {card['standins']}, conflicts {card['conflicts']}.",
        "",
        f"Queue probe (diagnostic): {_probe(card.get('queue_probe'))}.",
        "",
        f"Team count (diagnostic): {_teams(card.get('teams'))}.",
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
    churned = [r for r in card["rows"] if r["churn"]]
    if churned:
        lines += [
            "",
            "Reco churn (D6): the reco acted on, then the last one before the pick landed.",
            "",
            "| pick | acted on | kind | objective | final | kind | objective | cause |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in churned:
            lines.append(
                f"| {r['overall']} | {r['ref_name'] or r['ref_pid'] or '-'} | {r['ref_kind']} "
                f"| {_fmt(_round(r['ref_objective']))} "
                f"| {r['final_name'] or r['final_pid'] or '-'} | {r['final_kind']} "
                f"| {_fmt(_round(r['final_objective']))} | {r['churn_cause'] or 'to find'} |"
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


def _presolve_class(first: dict[str, Any] | None, ready_ms: float | None) -> str:
    """Hit, pending or miss for a turn whose board's first reco is ``first``."""
    if not (first and first.get("branch")):
        return "miss"
    late = first.get("branch_late")
    if late is None:
        late = ready_ms is None or ready_ms > BRANCH_READY_MS
    return "pending" if late else "hit"


def _probe(p: dict[str, Any] | None) -> str:
    """What Yahoo did with the probe's star: queued, drafted, dropped, no_control or failed;
    and, from #17, every control in the row ("cell 2.0": the third cell's first control)."""
    if p is None:
        return "not run"
    panel = p.get("panel")
    shown = "unreadable" if panel is None else (", ".join(panel) or "empty")
    out = (
        f"pick {p.get('overall')} ({p.get('name') or p.get('yid')}) {p.get('outcome')}; "
        f'control "{p.get("control") or "-"}"; queue panel {shown}'
    )
    controls = p.get("controls")
    if controls:
        listed = "; ".join(
            f'cell {c.get("cell")}.{c.get("pos", 0)} {c.get("tag", "?")} "{c.get("labels") or "-"}"'
            for c in controls
        )
        out += f"; row controls: {listed}"
    return out


def _teams_seen(turns: dict[int, dict], attached: int, mismatch: dict | None) -> dict[str, Any]:
    """The room's own team count, as the client first put it on a turn_start (#17)."""
    shown = next(
        (
            (k, e["teams"])
            for k, e in sorted(turns.items())
            if isinstance(e.get("teams"), int) and not isinstance(e.get("teams"), bool)
        ),
        None,
    )
    return {
        "attached": attached,
        "room": None if shown is None else shown[1],
        "from_pick": None if shown is None else shown[0],
        "mismatch": None if mismatch is None else mismatch.get("room_teams"),
    }


def _teams(t: dict[str, Any] | None) -> str:
    if t is None:
        return "not judged"
    if t["room"] is None:
        out = f"attached for {t['attached']}; the room's own count was not seen"
    else:
        out = (
            f"the room showed {t['room']} from pick {t['from_pick']}, attached for {t['attached']}"
        )
    if t["mismatch"] is not None:
        out += f"; MISMATCH ({t['mismatch']} teams): the API set the room to mirror"
    return out


def _roster(r: dict[str, Any]) -> str:
    if not r["recos"]:
        return "0"
    return f"{r['recos']} (boards {', '.join(str(b) for b in r['boards'])})"


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def _act(acts: list[int | None]) -> str:
    """act_at_s over the draft: "at once" (the default), or each setting in turn."""
    if all(a is None for a in acts):
        return "at once"
    return ", then ".join("at once" if a is None else f"at {a} s left" for a in acts)


def _fmt(value: Any, unit: str = "") -> str:
    return "-" if value is None else f"{value}{unit}"


def _score(score: dict[str, Any] | None) -> str:
    if not score:
        return "n/a"
    out = f"{score.get('wins')}"
    if score.get("benchmark") is not None:
        out += f" (benchmark {score['benchmark']}, {score.get('vs_benchmark'):+})"
    return out
