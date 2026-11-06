"""The record of every move and trade made in a league, and why (#334). Pure: the API reads the
league's week records, its snapshot, the queue's day files, the run logs and the decision log, and
nothing new is written.

Progress's Moves view scores moves against projections; this is what happened. My transactions
come from the week records and the latest snapshot, one group once however many pages listed it
(:func:`merged`). Each then finds its reason, in this order:

1. a queue entry placed on it (:func:`rows_of`): the set it came from, its gains and its bid. A
   claim that never landed has no transaction, and is a row of its own: lost, lapsed or still
   pending;
2. a comeback's chain (#318): the player's return and the drop that made room;
3. a churn's held drop on the drop log, under its entry;
4. otherwise a move by hand, against the latest recommendation before it (``decisions.match``).

A trade is never a move here (``decisions.moves_made`` skips them on purpose): it is its own row,
and a trade the page does not place on a team is an unread trade rather than nothing. No trade has
been seen live and none logs why it was made, so the row says so. A lineup run is not a move.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from typing import Any

from . import autopilot as qa
from . import decisions as dl
from . import moves as mv
from .state import Transaction

#: A row's kind; a comeback's is the prefix of its entry on the drop log too.
CLAIM, FREE_AGENT, DROP, TRADE, COMEBACK, IL = (
    "claim",
    "free_agent",
    "drop",
    "trade",
    "comeback",
    "il",
)
KINDS = (CLAIM, FREE_AGENT, DROP, TRADE, COMEBACK, IL)
#: A row's result: a claim's, a move made straight away, a move by hand, a claim not yet processed,
#: and a comeback stopped partway.
WON, LOST, LAPSED, LANDED, BY_HAND, PENDING, PARTIAL = (
    "won",
    "lost",
    "lapsed",
    "landed",
    "by hand",
    "pending",
    "partial",
)
RESULTS = (WON, LOST, LAPSED, LANDED, BY_HAND, PENDING, PARTIAL)
#: Who made a move.
THE_QUEUE, THE_COMEBACK, THE_USER = "the queue", "the comeback", "you"
#: The day the queue began: a move before it has no queue record.
FIRST_RECORD = date(2026, 10, 24)
NO_RECORD = "no record: moves before 2026-10-24 have no queue record"
NO_ENTRY = "no record: no recommendation was logged before this move"
TRADE_WHY = "a trade's reason is not logged"
UNREAD_TRADE = "the page does not say which team this trade belongs to"
COMEBACK_NEED = "cleared to come back with a full roster: he needs a drop first"
#: A comeback's stage that means a player really moved.
_MOVED = ("dropped", "unconfirmed", "set")


@dataclass(frozen=True)
class Runs:
    """A league's live runs from its day logs: the comebacks' and churns' drops, the IL moves and
    the comebacks' returns (a lineup run's steps of kind ``return`` with a drop)."""

    drops: Sequence[Mapping[str, Any]] = ()
    il: Sequence[Mapping[str, Any]] = ()
    returns: Sequence[Mapping[str, Any]] = ()


def merged(
    records: Iterable[Iterable[Mapping[str, Any]]],
    latest: Iterable[Transaction],
) -> list[Transaction]:
    """Every transaction of the week records (``records``, each one's rows) and the latest
    snapshot's (``latest``), a group once however many listed it, numbered anew. A group is its
    team, its time as the page prints it and its players, as ``record.week_transactions`` counts
    it."""
    seen: dict[tuple[Any, ...], int] = {}
    out: list[Transaction] = []

    def take(rows: Sequence[Transaction]) -> None:
        groups: dict[int, list[Transaction]] = {}
        for t in rows:
            groups.setdefault(t.group, []).append(t)
        for group in groups.values():
            players = tuple(sorted((t.kind, t.player.yahoo_id) for t in group))
            key = (group[0].team_id, group[0].when, players)
            if key in seen:
                continue
            seen[key] = len(seen)
            out.extend(
                Transaction(t.kind, t.player, t.team_id, t.team_name, t.detail, t.when, seen[key])
                for t in group
            )

    for rows in records:
        take([Transaction.from_dict(r) for r in rows])
    take(list(latest))
    return out


def _trades(transactions: Sequence[Transaction]) -> list[list[Transaction]]:
    groups: dict[int, list[Transaction]] = {}
    for t in transactions:
        groups.setdefault(t.group, []).append(t)
    return [rows for rows in groups.values() if any(t.kind == "trade" for t in rows)]


def _says(t: Transaction) -> bool:
    """Whether Yahoo's words for ``t`` name where he went."""
    return " to " in f" {(t.detail or '').lower()} "


def _names(t: Transaction, my_name: str | None) -> bool:
    return bool(my_name) and str(my_name).lower() in (t.detail or "").lower()


def _side(t: Transaction, my_name: str | None) -> str | None:
    """Which way ``t`` went on Yahoo's words: ``got`` when they name my team, ``gave`` when they
    name another, None when they name none. The page's team link is no side: the parser reads one
    link to the row, however many teams it holds."""
    if not _says(t):
        return None
    return "got" if _names(t, my_name) else "gave"


def trade_row(
    league: str,
    rows: Sequence[Transaction],
    me: int | None,
    my_name: str | None,
    today: date,
    zone: tzinfo,
) -> dict[str, Any] | None:
    """A trade group as a row: mine when the page's link is my team or Yahoo's words name it, and
    None when the words send every player to other teams. The rest cannot be placed, since the
    page's one link may be my partner's: an unread trade, never nothing."""
    mine = any(t.team_id == me or _names(t, my_name) for t in rows)
    if not mine and any(_says(t) for t in rows):
        return None
    unread = not mine
    when = rows[0].when
    day = mv.when_date(when, today)
    at = dl.when_at(when, today, zone)
    sides = [
        {
            "player": t.player.yahoo_id,
            "name": t.player.name,
            "side": _side(t, my_name),
            "detail": t.detail,
        }
        for t in rows
    ]
    return {
        "id": f"{league}:trade:{day}:{':'.join(str(t.player.yahoo_id) for t in rows)}",
        "league": league,
        "date": day.isoformat() if day else None,
        "at": at.isoformat() if at else None,
        "kind": TRADE,
        "player": None,
        "add": None,
        "drop": None,
        "sides": sides,
        "bid": None,
        "result": LANDED,
        "who": None if unread else THE_USER,
        "unread": unread,
        "why": {"note": UNREAD_TRADE if unread else TRADE_WHY},
    }


def _logged(
    entries: Sequence[Mapping[str, Any]],
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
    entry: str | None,
    move: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if entry is None or move is None:
        return None
    return logged(entries, {"kind": dl.AS_RECOMMENDED, "entry": entry, "move": move})


def _odds(record: Mapping[str, Any] | None) -> float | None:
    after = ((record or {}).get("odds") or {}).get("after") or {}
    return after.get("matchup")


def queue_why(
    e: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    """A queued move's reason: the set it came from, its step and the plan's size, its gain on
    this week and on the three weeks with the season beside it, the matchup odds when logged, and
    the bid with how it was sized. An entry whose decision no longer reads keeps what the queue
    held."""
    record = _logged(
        entries, logged, e.get("decision"), {"add": e.get("add"), "drop": e.get("drop")}
    )
    gain = (record or {}).get("gain") or {}
    judged = e.get("judged") or qa.JUDGED
    plan = e.get("plan") or {}
    bid = e.get("bid") or {}
    return {
        "set": e.get("set"),
        "step": plan.get("step"),
        "steps_of": plan.get("steps"),
        "week": gain.get("week", e.get("gain") if judged == "week" else None),
        "three": gain.get("three", e.get("three") if judged == "week" else e.get("gain")),
        "season": e.get("season"),
        "matchup": plan["matchup"] if plan.get("matchup") is not None else _odds(record),
        "against": plan.get("against"),
        "bid_reason": bid.get("reason"),
    }


def hand_why(
    made: dl.Made,
    entries: Sequence[Mapping[str, Any]],
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
) -> dict[str, Any]:
    """A move by hand against the latest recommendation before it (``decisions.match``), with
    that recommendation's gains. No entry says so: before the queue's first day, that no record
    exists."""
    m = dl.match(made, entries)
    if m["kind"] == dl.NO_ENTRY:
        early = made.day is not None and made.day < FIRST_RECORD
        return {"match": m["kind"], "note": NO_RECORD if early else NO_ENTRY}
    record = _logged(entries, logged, m["entry"], m["move"])
    gain = (record or {}).get("gain") or {}
    return {
        "match": m["kind"],
        "entry": m["entry"],
        "move": m["move"],
        "set": (record or {}).get("set"),
        "week": gain.get("week"),
        "three": gain.get("three"),
    }


def _day_of(raw: Any) -> date | None:
    return date.fromisoformat(raw[:10]) if isinstance(raw, str) else None


def _take(made: list[dl.Made], found: Iterable[dl.Made]) -> dl.Made | None:
    """The oldest of ``found``, taken out of ``made``."""
    oldest = min(found, key=lambda m: (m.day or date.min, m.group), default=None)
    if oldest is not None:
        made.remove(oldest)
    return oldest


def _take_add(made: list[dl.Made], add: int, since: date | None) -> dl.Made | None:
    """The oldest add of ``add`` on or after ``since``, taken out of ``made``."""
    return _take(
        made,
        [m for m in made if m.add == add and (since is None or (m.day or since) >= since)],
    )


def _take_drop(made: list[dl.Made], drop: Any) -> dl.Made | None:
    """The oldest lone drop of ``drop``, taken out of ``made``."""
    return _take(made, [m for m in made if m.drop == drop and m.add is None])


def _kind(made: dl.Made | None, e: Mapping[str, Any] | None = None) -> str:
    """A move's kind, on Yahoo's words for it, or the queue's while it has none."""
    if made is not None and made.add is None:
        return DROP
    words = ((made.detail if made is not None else None) or "").lower()
    if words:
        return FREE_AGENT if "free agent" in words else CLAIM
    return FREE_AGENT if (e or {}).get("availability") == qa.FREE_AGENT else CLAIM


def _claim_result(
    e: Mapping[str, Any], hit: dl.Made | None, kind: str, settled_by: date | None
) -> str:
    """How a placed claim came out: the queue's settling, the page's add, or still pending. A claim
    placed before ``settled_by`` that nothing settled never will be: the queue stops looking at it,
    so it lapsed (a claim of before #324, which added the word, has no ``resolved`` to say so)."""
    resolved = e.get("resolved")
    if resolved in (LOST, LAPSED):
        return str(resolved)
    if resolved == WON or hit is not None:
        return LANDED if kind == FREE_AGENT else WON
    if e.get("outcome") == "added":
        return LANDED
    day = _day_of(e.get("date"))
    return LAPSED if day is not None and settled_by is not None and day < settled_by else PENDING


def _row(
    league: str,
    day: date | None,
    at: datetime | str | None,
    kind: str,
    add: int | None,
    drop: int | None,
    bid: float | None,
    result: str,
    who: str,
    why: Mapping[str, Any],
    key: str,
) -> dict[str, Any]:
    return {
        "id": f"{league}:{key}",
        "league": league,
        "date": day.isoformat() if day else None,
        "at": at.isoformat() if isinstance(at, datetime) else at,
        "kind": kind,
        "player": None,
        "add": add,
        "drop": drop,
        "sides": None,
        "bid": bid,
        "result": result,
        "who": who,
        "unread": False,
        "why": dict(why),
    }


def _bid(e: Mapping[str, Any], hit: dl.Made | None, kind: str) -> float | None:
    """The bid Yahoo printed, or the one the queue placed; a free agent's add has none."""
    if hit is not None and hit.bid is not None:
        return hit.bid
    return None if kind == FREE_AGENT else qa.effective_bid(e)


def _queue_rows(
    league: str,
    placed: Sequence[Mapping[str, Any]],
    made: list[dl.Made],
    entries: Sequence[Mapping[str, Any]],
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
    settled_by: date | None,
) -> list[dict[str, Any]]:
    out = []
    for e in sorted(placed, key=lambda x: (str(x.get("date")), str(x.get("id")))):
        day = _day_of(e.get("date"))
        add = int(e["add"])
        hit = None if e.get("resolved") in (LOST, LAPSED) else _take_add(made, add, day)
        kind = _kind(hit, e)
        out.append(
            _row(
                league,
                hit.day if hit is not None and hit.day else day,
                hit.at if hit is not None else e.get("outcome_at"),
                kind,
                add,
                hit.drop if hit is not None else e.get("drop"),
                _bid(e, hit, kind),
                _claim_result(e, hit, kind, settled_by),
                THE_QUEUE,
                queue_why(e, entries, logged),
                str(e.get("id")),
            )
        )
    return out


def _comeback_rows(league: str, runs: Runs, made: list[dl.Made]) -> list[dict[str, Any]]:
    """Each comeback that moved somebody, its drop and his return in order: one chain to a player
    and his drop, a player who comes back twice having two."""
    chains: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for r in runs.drops:
        entry = str(r.get("entry") or "")
        if not entry.startswith(f"{COMEBACK}:"):
            continue
        key = (int(entry.split(":")[1]), int(r["player"]))
        chains.setdefault(key, []).append(
            {
                "stage": "drop",
                "player": r.get("player"),
                "outcome": r.get("outcome"),
                "at": r.get("at"),
                "words": r.get("message") or r.get("reason"),
            }
        )
    for s in runs.returns:
        key = (int(s["player"]), int(s["drop"]))
        chains.setdefault(key, []).append(
            {
                "stage": "move",
                "player": s["player"],
                "outcome": s.get("outcome"),
                "at": s.get("at"),
                "words": s.get("message") or s.get("reason"),
            }
        )
    out = []
    for (player, drop), raw in sorted(chains.items()):
        steps = sorted(raw, key=lambda s: str(s.get("at")))
        if not any(s.get("outcome") in _MOVED for s in steps):
            continue
        day = _day_of(steps[0].get("at"))
        hit = _take_drop(made, drop)
        whole = any(s["stage"] == "move" and s.get("outcome") == "set" for s in steps)
        out.append(
            _row(
                league,
                hit.day if hit is not None and hit.day else day,
                steps[0].get("at"),
                COMEBACK,
                None,
                drop,
                None,
                LANDED if whole else PARTIAL,
                THE_COMEBACK,
                {"need": COMEBACK_NEED, "steps": steps},
                f"comeback:{player}:{drop}",
            )
            | {"player": player}
        )
    return out


def _il_rows(
    league: str, runs: Runs, queue: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    out = []
    for r in runs.il:
        if r.get("outcome") != "moved":
            continue
        e = queue.get(str(r.get("entry"))) or {}
        steps = [
            {
                "stage": "IL move",
                "player": r.get("player"),
                "outcome": r.get("outcome"),
                "at": r.get("at"),
                "words": r.get("message") or r.get("reason"),
            }
        ]
        if e:
            steps.append(
                {
                    "stage": "claim",
                    "player": e.get("add"),
                    "outcome": e.get("resolved") or e.get("outcome"),
                    "at": e.get("outcome_at"),
                    "words": e.get("outcome_reason"),
                }
            )
        out.append(
            _row(
                league,
                _day_of(r.get("day")) or _day_of(r.get("at")),
                r.get("at"),
                IL,
                None,
                None,
                None,
                LANDED,
                THE_QUEUE,
                {
                    "need": {"for": e.get("add"), "slot": r.get("to_slot")},
                    "from": r.get("from_slot"),
                    "steps": steps,
                },
                f"il:{r.get('player')}:{r.get('at')}",
            )
            | {"player": r.get("player")}
        )
    return out


def _churn_rows(
    league: str,
    runs: Runs,
    made: list[dl.Made],
    queue: Mapping[str, Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    out = []
    for r in runs.drops:
        e = queue.get(str(r.get("entry")))
        if e is None or r.get("outcome") != "dropped":
            continue
        player = r.get("player")
        hit = _take_drop(made, player)
        out.append(
            _row(
                league,
                hit.day if hit is not None and hit.day else _day_of(r.get("day")),
                r.get("at"),
                DROP,
                None,
                player,
                None,
                LANDED,
                THE_QUEUE,
                queue_why(e, entries, logged),
                f"churn:{r.get('entry')}",
            )
        )
    return out


def _moment(row: Mapping[str, Any]) -> float:
    at = row.get("at")
    return datetime.fromisoformat(at).timestamp() if at else 0.0


def newest_first(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """``rows`` by date and then moment, the page's clock and the queue's being in other zones."""
    return sorted(rows, key=lambda r: (r["date"] or "", _moment(r), r["id"]), reverse=True)


def rows_of(
    league: str,
    me: int | None,
    my_name: str | None,
    transactions: Sequence[Transaction],
    queue: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    runs: Runs,
    logged: Callable[[Sequence[Mapping[str, Any]], Mapping[str, Any]], dict[str, Any] | None],
    today: date,
    zone: tzinfo,
    settled_by: date | None = None,
) -> list[dict[str, Any]]:
    """The league's rows, newest first: each of my transaction groups once, with the queue's
    placed claims that never landed, the comebacks and the IL moves. ``queue`` is the league's
    entries of every day; ``entries`` its decision log; ``logged`` reads a move's record from it
    (``season_scorecard.logged_move``, so the two screens never disagree on a figure);
    ``settled_by`` is the day the queue stops looking at a claim before."""
    made = list(dl.moves_made(transactions, me, today, zone)) if me is not None else []
    by_id = {str(e.get("id")): e for e in queue}
    placed = [e for e in queue if e.get("outcome") in qa.PLACED]
    out = _queue_rows(league, placed, made, entries, logged, settled_by)
    out += _comeback_rows(league, runs, made)
    out += _churn_rows(league, runs, made, by_id, entries, logged)
    out += _il_rows(league, runs, by_id)
    for m in made:
        out.append(
            _row(
                league,
                m.day,
                m.at,
                _kind(m),
                m.add,
                m.drop,
                m.bid,
                BY_HAND,
                THE_USER,
                hand_why(m, entries, logged),
                f"made:{m.group}",
            )
        )
    for rows in _trades(transactions):
        row = trade_row(league, rows, me, my_name, today, zone)
        if row is not None:
            out.append(row)
    return newest_first(out)
