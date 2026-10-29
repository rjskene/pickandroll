"""The decision log (#125): every solve of the moves and strategy routes kept as an entry under
``data/leagues/<id>/season/decisions/<date>.json``, and ``GET /seasons/{league}/decisions``,
the entries with my moves matched to them (``season.decisions``).

An entry is written when a solve finishes: the moves route's once per day and inputs (a cached
answer writes nothing), a strategy run's when it solved. It holds what the scorecard compares
against: the system and its export, the knobs in force, the adds left, the pool, and each
recommended set (the moves route's per horizon, the strategy's per weight) with its gains and
this week's categories and odds before and after it, and (from #126) the scorer and each move's
own gain and value. A moves entry also says what the week's streaming plan (#136) was worth
against its set, whatever the verdict (``plan``), and a recommended plan is one more set,
``plan``, its steps dated by their ``from``. From #144 each move's value has a season horizon
and the move says whether it costs the season (``season_costly``) on the horizon its set is
judged on: below zero over the season, whatever the protection floor (#164). From #187 each
move records its basis (an open spot, a held-slot move, a drop) and the held move it takes. A
day's file is a list, appended to.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import Season
from ..season import decisions as dl
from ..season import moves as mv
from ..season import plans as pl
from ..season import progress as pg
from ..season import weekly as wk
from . import season_moves
from .season_moves import Built
from .season_week import NBA_TZ

DECISIONS = "decisions"
#: The days the route shows by default: the last week.
SHOWN_DAYS = 7
#: The zone the transactions page's times are read in. The page prints them without one, in
#: the zone of the Yahoo account that opened it (the user's Chrome for the private league; the
#: API's fetch, signed out, for a public one), and neither says which. US Eastern, the NBA's and
#: the league's clock, is the assumption; the user's Mac runs on US Central. A move within an
#: hour of a solve is flagged ``near`` (``decisions.NEAR``) so a wrong zone shows.
TRANSACTIONS_TZ = NBA_TZ
_lock = threading.Lock()


def decisions_dir(season_dir: Path) -> Path:
    return season_dir / DECISIONS


def append(season_dir: Path, entry: Mapping[str, Any]) -> None:
    """Add ``entry`` to its day's file (the day in US Eastern of its time)."""
    day = datetime.fromisoformat(entry["at"]).astimezone(NBA_TZ).date()
    path = decisions_dir(season_dir) / f"{day.isoformat()}.json"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = json.loads(path.read_text()) if path.exists() else []
        entries.append(dict(entry))
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, separators=(",", ":")))
        tmp.replace(path)


def load(season_dir: Path, to: date | None = None) -> list[dict[str, Any]]:
    """Every entry logged up to ``to`` (every one when None), oldest first."""
    folder = decisions_dir(season_dir)
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        if to is not None and path.stem > to.isoformat():
            continue
        out.extend(json.loads(path.read_text()))
    return sorted(out, key=lambda e: e["at"])


# --------------------------------------------------------------------------- the entries
def _id(at: datetime, source: str, system: str) -> str:
    return f"{at:%Y%m%dT%H%M%S%f}-{source}-{system}"


def week_block(ev: mv.Evaluator, moves: Sequence[mv.Move]) -> dict[str, Any] | None:
    """This week against the named opponent with ``moves`` made: each category's finals and
    odds, the expected categories won and the odds of winning the matchup; None in a week
    without a named opponent."""
    odds = ev.odds("week", list(moves))
    if not odds or len(odds[0]) != 1:
        return None
    cats = odds[0][0]
    return {
        "cats": {
            o.cat: {
                "mine": None if o.mine is None else round(float(o.mine), 4),
                "theirs": None if o.theirs is None else round(float(o.theirs), 4),
                "p_win": round(float(o.p_win), 4),
            }
            for o in cats
        },
        "expected": round(float(wk.expected_won(cats)), 4),
        "matchup": round(float(wk.matchup_won(cats)), 4),
    }


def _week(ev: mv.Evaluator, moves: Sequence[mv.Move]) -> dict[str, Any]:
    return {"before": week_block(ev, []), "after": week_block(ev, moves)}


def knobs(built: Built) -> dict[str, Any]:
    """The AUTOPILOT knobs (docs/AUTOPILOT.md, section 6) the solve ran with, every one of
    ``season.progress.KNOBS`` whether the solve uses it or not (#152): the projection system and
    its blend weight, the strategy's recommended weight, the keep rule's protection floor, the
    streaming plan's floors and moves a day, the stash threshold and the FAAB sizing; and beside
    them ``file_system``, the system the knob file had in force for the league, which a route
    naming another overrode (the scorecard projects each week on it)."""
    return {**{k: built.knobs.get(k) for k in pg.KNOBS}, "file_system": built.file_system}


def _logged(move: Mapping[str, Any], built: Built | None = None) -> dict[str, Any]:
    """A recommended move as logged: its add, drop and first day, and the bid to make (None
    until the FAAB sizing, phase 2, sets one); with the solve (``built``), its own gain on each
    horizon as the solve priced it (None for a strategy move left unpriced) and its projection
    in value units (``decisions.move_projection``), for the scorecard (#126)."""
    out = {**{k: move[k] for k in ("add", "drop", "from")}, "bid": None}
    if built is not None:
        drop = None if move.get("drop") is None else int(move["drop"])
        day = None if move.get("from") is None else date.fromisoformat(move["from"])
        out["gain"] = move.get("marginal")
        out["value"] = dl.move_projection(built.problem, built.scorer, int(move["add"]), drop, day)
    return out


def _based(moves: list[dict[str, Any]], built: Built) -> list[dict[str, Any]]:
    """``moves`` of one set, each with its basis (#187, ``decisions.basis_of``), the held-slot
    move that makes room for it (``held``, None but for a ``held`` or a ``churn`` basis) and a
    churn's held drop (``held_drop``, #221), read from the set as a whole as the payload reads
    it (``season_moves.held_by_add``): one rule for every set."""
    p = built.problem
    held = season_moves.held_by_add(p, _moves_of(moves))
    for m in moves:
        move = mv.Move(int(m["add"]), None if m.get("drop") is None else int(m["drop"]))
        m["held"] = held.get(move.add) if mv.needs_spot(p, move) else None
        m["held_drop"] = season_moves.held_drop(p, move)
        m["basis"] = season_moves.basis(p, move, m["held"])
    return moves


def _flagged(moves: list[dict[str, Any]], source: str, key: str) -> list[dict[str, Any]]:
    """``moves`` of one set, each with whether it costs the season (#144) on the horizon the set
    is judged on (``decisions.season_costly``); None for a move with no projection."""
    for m in moves:
        value = m.get("value")
        judged = dl.judging_horizon(source, key, value)
        m["season_costly"] = dl.season_costly(value, judged)
    return moves


def guard_record(guard: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The season guard on a logged set (#164): whether it held a set back and, when it did,
    that set's moves (add, drop, first day, what each adds to the set and its rest of the
    season), its gain and its rest of the season, so the scorecard can tell a move the guard
    held back from one the user chose; None where no guard ran."""
    if guard is None:
        return None
    if not guard.get("held_back"):
        return {"held_back": False}
    return {
        "held_back": True,
        "moves": [
            {
                **{k: m[k] for k in ("add", "drop", "from")},
                "gain": m.get("marginal"),
                "ros": (m.get("ros") or {}).get("value"),
            }
            for m in guard["moves"]
        ],
        "gain": guard["gain"],
        "ros": guard["ros"],
    }


def _moves_of(rows: Sequence[Mapping[str, Any]]) -> list[mv.Move]:
    """Logged moves as the model's, each counting from its ``from`` (a plan's step's day)."""
    return [
        mv.Move(
            int(r["add"]),
            None if r.get("drop") is None else int(r["drop"]),
            None if r.get("from") is None else date.fromisoformat(r["from"]),
        )
        for r in rows
    ]


def _common(built: Built, at: datetime, source: str) -> dict[str, Any]:
    p = built.problem
    return {
        "id": _id(at, source, built.system["key"]),
        "at": at.isoformat(),
        "source": source,
        "system": built.system,
        "knobs": knobs(built),
        "first_day": p.first_day.isoformat(),
        "adds": built.adds,
        "horizons": {k: built.horizons[k]["label"] for k in season_moves.HORIZONS},
        "scorer": built.scorer,
    }


def moves_entry(built: Built, payload: Mapping[str, Any], at: datetime) -> dict[str, Any]:
    """The moves route's solve: each horizon's recommended set, with the held-slot moves and
    the comebacks it implies, its gains on both horizons, this week before and after, and the
    season guard's record (:func:`guard_record`)."""
    ev = mv.Evaluator(built.problem)
    sets = []
    for key in season_moves.HORIZONS:
        rec = payload["recommended"][key]
        moves = _flagged(_based([_logged(m, built) for m in rec["moves"]], built), "moves", key)
        sets.append(
            {
                "key": key,
                "weight": None,
                "moves": moves,
                "held": rec["held"],
                "comebacks": rec["comebacks"],
                "gain": rec["gain"],
                "week": _week(ev, _moves_of(moves)),
                "season_guard": guard_record(rec.get("season_guard")),
            }
        )
    plan = payload.get("plan")
    if plan is not None and plan["recommended"]:
        # The streaming plan (#136) as one more set: the week set's moves it keeps, then its
        # steps by day, each counting from its day with its own gain.
        moves = [_logged(m, built) for m in (*plan["base"], *plan["steps"])]
        moves = _flagged(_based(moves, built), "moves", "plan")
        none = plan["value"]["none"]
        sets.append(
            {
                "key": "plan",
                "weight": None,
                "moves": moves,
                "held": plan["held"],
                "comebacks": plan["comebacks"],
                "gain": {h: round(v - none[h], 3) for h, v in plan["value"]["plan"].items()},
                "week": _week(ev, _moves_of(moves)),
            }
        )
    wp = payload.get("week_plans")
    if wp is not None and wp.get("queue") is not None:
        # The week plan the queue takes instead of the three weeks' set (#221 part 2): its steps
        # by day, each counting from its day with its own increment and the steps it waits on.
        w = wp["plans"][wp["queue"]]
        moves = [_logged({**s, "marginal": s["gain"]}, built) for s in w["steps"]]
        moves = _flagged(_based(moves, built), "moves", pl.QUEUE_PLAN)
        # The plan is one decision (the ruling's first condition): every step carries its id and
        # day, so the scorecard judges the plan whole and not its steps apart.
        unit = {
            "id": plan_id(_id(at, "moves", built.system["key"])),
            "day": built.problem.first_day.isoformat(),
        }
        for i, (m, s) in enumerate(zip(moves, w["steps"], strict=True)):
            m["after"] = s["after"]
            m["plan"] = {**unit, "step": i + 1, "steps": len(moves)}
        model = _moves_of(moves)
        sets.append(
            {
                "key": pl.QUEUE_PLAN,
                "weight": None,
                "moves": moves,
                "held": [
                    {"player": k, "slot": slot} for k, slot in mv.held_used(built.problem, model)
                ],
                "comebacks": {
                    h: season_moves.comebacks_rows(mv.comebacks(built.problem, h, model))
                    for h in built.problem.horizons
                },
                "gain": w["total"],
                "week": _week(ev, model),
            }
        )
    search = payload.get("search") or {}
    return {
        **_common(built, at, "moves"),
        "plan": plan_verdict(plan),
        "week_plans": week_plans_record(wp),
        "pool": {
            "size": search.get("pool"),
            "candidates": len(payload.get("candidates") or {}),
            "min_gain": search.get("min_gain"),
        },
        "sets": sets,
    }


def plan_id(entry: str) -> str:
    """The id of the week plan a moves entry queued (#221 part 2): the entry's own, with the set."""
    return f"{entry}:{pl.QUEUE_PLAN}"


def week_plans_record(wp: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The week plans as every moves entry logs them (#221 part 2): each plan's source, its moves
    (add, drop, day), its total on both horizons and its rest of the season, the plan the queue
    took (an index, None for none), the floor and the search's seconds; None with no day left."""
    if wp is None:
        return None
    return {
        "plans": [
            {
                "source": w["source"],
                "moves": [{k: s[k] for k in ("add", "drop", "from")} for s in w["steps"]],
                "total": w["total"],
                "ros": w["ros"],
            }
            for w in wp["plans"]
        ],
        "queue": wp["queue"],
        "floor": wp["floor"],
        "seconds": wp["seconds"],
    }


def plan_verdict(plan: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The week's best streaming plan against its set, as every moves entry logs it whether it
    was recommended or not (the scorecard counts the plans foregone and judges the floor): its
    expected value on both horizons, the set's, the shortfall, the floor in force and why it was
    not recommended (``short``, ``guard`` or ``season``, the latter two with the refused plan's
    gain on the set on both horizons and its rest of the season less the set's: the three-week
    guard refused it, or the season guard, #164); None without a stream spot. The steps are
    logged only as a recommended plan's set."""
    if plan is None:
        return None
    guard = plan.get("guard")
    return {
        "recommended": plan["recommended"],
        "reason": plan.get("reason"),
        "value": plan["value"]["plan"],
        "set": plan["value"]["set"],
        "short": plan["short"],
        "floor": plan["floor"],
        "guard": None if guard is None else {"gain": guard["gain"], "ros": guard.get("ros")},
    }


def strategy_entry(built: Built, payload: Mapping[str, Any], at: datetime) -> dict[str, Any]:
    """A strategy run that solved: each weight's chosen set and its source, its gains (this
    week, three weeks, the season), this week before and after and the season guard's record
    (:func:`guard_record`, #164), the weight the knob file recommends marked (#152)."""
    ev = mv.Evaluator(built.problem)
    sets = []
    for point in payload["points"]:
        if point.get("stage") != "done":
            continue
        moves = [_logged(m, built) for m in point.get("moves") or []]
        moves = _flagged(_based(moves, built), "strategy", point["key"])
        sets.append(
            {
                "key": point["key"],
                "weight": point["lambda"],
                "natural": point.get("natural", False),
                "recommended": point.get("recommended", False),
                "source": point.get("source"),
                "moves": moves,
                "gain": point.get("gain"),
                "week": _week(ev, _moves_of(moves)),
                "season_guard": guard_record(point.get("season_guard")),
            }
        )
    return {
        **_common(built, at, "strategy"),
        "pool": {"size": len(payload.get("pool") or []), "players": list(payload["pool"])},
        "settings": payload.get("settings"),
        "recommended": payload.get("recommended"),
        "sets": sets,
    }


# --------------------------------------------------------------------------- the route
def payload(
    entries: Sequence[Mapping[str, Any]],
    season: Season,
    today: date,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """The entries logged from ``start`` to ``end`` (the last week to today by default), and
    my moves made in those days, each matched to the latest entry before it (which may be
    older than ``start``). A private league's moves are its posted transactions page's."""
    end = end or today
    start = start or end - timedelta(days=SHOWN_DAYS - 1)
    mine = season.settings.my_team_id
    made = (
        dl.moves_made(season.transactions, mine, today, TRANSACTIONS_TZ) if mine is not None else []
    )

    def shown(day: date | None) -> bool:
        return day is not None and start <= day <= end

    def local(e: Mapping[str, Any]) -> date:
        return datetime.fromisoformat(e["at"]).astimezone(NBA_TZ).date()

    rows = [{**m.to_dict(), "match": dl.match(m, entries)} for m in made if shown(m.day)]
    kept = [e for e in entries if start <= local(e) <= end]
    ids = {
        k
        for e in kept
        for s in e["sets"]
        for m in s["moves"]
        for k in (m["add"], m["drop"])
        if k is not None
    } | {k for r in rows for k in (r["add"], r["drop"]) if k is not None}
    return {
        "league": season.settings.league,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "transactions_read": _read_at(season),
        "entries": kept,
        "made": rows,
        "summary": {
            **{
                kind: sum(1 for r in rows if r["match"]["kind"] == kind)
                for kind in (dl.AS_RECOMMENDED, dl.DIFFERENTLY, dl.NOT_RECOMMENDED, dl.NO_ENTRY)
            },
            "near": sum(1 for r in rows if r["match"]["near"]),
        },
        "players": {str(k): name for k, name in _names(season).items() if k in ids},
    }


def _read_at(season: Season) -> str | None:
    read = season.fetched.get("transactions")
    return read[0].isoformat() if read else None


def _names(season: Season) -> dict[int, str]:
    out = {p.yahoo_id: p.name for p in season.players.values()}
    for spots in season.rosters.values():
        out |= {sp.player.yahoo_id: sp.player.name for sp in spots}
    out |= {a.player.yahoo_id: a.player.name for a in season.available}
    out |= {t.player.yahoo_id: t.player.name for t in season.transactions}
    return out
