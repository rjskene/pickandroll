"""The decision log (#125): every solve of the moves and strategy routes kept as an entry under
``data/leagues/<id>/season/decisions/<date>.json``, and ``GET /seasons/{league}/decisions``,
the entries with my moves matched to them (``season.decisions``).

An entry is written when a solve finishes: the moves route's once per day and inputs (a cached
answer writes nothing), a strategy run's when it solved. It holds what the scorecard compares
against: the system and its export, the knobs in force, the adds left, the pool, and each
recommended set (the moves route's per horizon, the strategy's per weight) with its gains and
this week's categories and odds before and after it. A day's file is a list, appended to.
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
#: The AUTOPILOT knobs (docs/AUTOPILOT.md, section 6) an entry records as in force: the
#: projection system (the solve's own), then the blend weight, the strategy's horizon weight,
#: the keep rule's protection floor, the stash threshold, the FAAB sizing and the daily move
#: cap, None until the knob file (phase 3) sets them.
KNOBS = (
    "blend",
    "horizon_weight",
    "protection_floor",
    "stash_threshold",
    "faab_sizing",
    "daily_cap",
)

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


def knobs(system: str) -> dict[str, Any]:
    """The knobs in force for a solve on ``system``."""
    return {"system": system, **dict.fromkeys(KNOBS)}


def _logged(move: Mapping[str, Any]) -> dict[str, Any]:
    """A recommended move as logged: its add, drop and first day, and the bid to make (None
    until the FAAB sizing, phase 2, sets one)."""
    return {**{k: move[k] for k in ("add", "drop", "from")}, "bid": None}


def _moves_of(rows: Sequence[Mapping[str, Any]]) -> list[mv.Move]:
    return [mv.Move(int(r["add"]), None if r.get("drop") is None else int(r["drop"])) for r in rows]


def _common(built: Built, at: datetime, source: str) -> dict[str, Any]:
    p = built.problem
    return {
        "id": _id(at, source, built.system["key"]),
        "at": at.isoformat(),
        "source": source,
        "system": built.system,
        "knobs": knobs(built.system["key"]),
        "first_day": p.first_day.isoformat(),
        "adds": built.adds,
        "horizons": {k: built.horizons[k]["label"] for k in season_moves.HORIZONS},
    }


def moves_entry(built: Built, payload: Mapping[str, Any], at: datetime) -> dict[str, Any]:
    """The moves route's solve: each horizon's recommended set, with the held-slot moves and
    the comebacks it implies, its gains on both horizons and this week before and after."""
    ev = mv.Evaluator(built.problem)
    sets = []
    for key in season_moves.HORIZONS:
        rec = payload["recommended"][key]
        moves = [_logged(m) for m in rec["moves"]]
        sets.append(
            {
                "key": key,
                "weight": None,
                "moves": moves,
                "held": rec["held"],
                "comebacks": rec["comebacks"],
                "gain": rec["gain"],
                "week": _week(ev, _moves_of(moves)),
            }
        )
    search = payload.get("search") or {}
    return {
        **_common(built, at, "moves"),
        "pool": {
            "size": search.get("pool"),
            "candidates": len(payload.get("candidates") or {}),
            "min_gain": search.get("min_gain"),
        },
        "sets": sets,
    }


def strategy_entry(built: Built, payload: Mapping[str, Any], at: datetime) -> dict[str, Any]:
    """A strategy run that solved: each weight's chosen set and its source, its gains (this
    week, three weeks, the season) and this week before and after."""
    ev = mv.Evaluator(built.problem)
    sets = []
    for point in payload["points"]:
        if point.get("stage") != "done":
            continue
        moves = [_logged(m) for m in point.get("moves") or []]
        sets.append(
            {
                "key": point["key"],
                "weight": point["lambda"],
                "natural": point.get("natural", False),
                "source": point.get("source"),
                "moves": moves,
                "gain": point.get("gain"),
                "week": _week(ev, _moves_of(moves)),
            }
        )
    return {
        **_common(built, at, "strategy"),
        "pool": {"size": len(payload.get("pool") or []), "players": list(payload["pool"])},
        "settings": payload.get("settings"),
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
