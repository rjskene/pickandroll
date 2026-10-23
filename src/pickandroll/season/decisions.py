"""The decision log (#125, docs/ADD_DROP.md, "Decision log"): the moves my team made in Yahoo,
each matched to what the engine recommended before it.

An entry is one solve of the moves or the strategy route, as ``api.season_decisions`` keeps it:
its sets, each a list of moves (an add and the player dropped for him, or nobody). A move made
is one of my transactions on the league's transactions page: an add with the drop that came
with it (the page groups them), or a lone drop. It is matched against the latest entry logged
before it, over every set of that entry:

- ``as_recommended``: a set holds the same add with the same drop (nobody being an open spot or
  a move to a held slot);
- ``differently``: a set adds the same player for another drop, or drops the same player for
  another add;
- ``not_recommended``: no set of the entry names either player;
- ``no_entry``: nothing was logged before the move.

The page prints a move's time without its zone (``Oct 20, 3:57 am``); it is read in the zone
given (``api.season_decisions.TRANSACTIONS_TZ``). A move within :data:`NEAR` of any entry is
flagged ``near``: a zone off by an hour could change the entry it is matched to, so its kind is
not to be trusted blindly.

From #126 on, an entry also keeps what the Monday scorecard scores a move by: its scorer (the
league's, as data: ``weekly.scorer_of``) and, for each recommended move, its own gain on each
horizon as the solve priced it and its projection in value units (:func:`move_projection`).
Pure: the entries are read and written by the API.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from . import weekly as wk
from .moves import MoveProblem, when_date
from .state import Transaction

AS_RECOMMENDED = "as_recommended"
DIFFERENTLY = "differently"
NOT_RECOMMENDED = "not_recommended"
NO_ENTRY = "no_entry"

#: How close to an entry a move is flagged ``near``: the error a wrong zone would make.
NEAR = timedelta(hours=1)

_CLOCK = re.compile(r",\s*(\d{1,2}):(\d{2})\s*([ap])\.?m", re.IGNORECASE)
_BID = re.compile(r"\$\s*(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Made:
    """One of my moves: the player added and the player dropped with him (either may be None,
    a lone add or a lone drop), as the transactions page lists it."""

    group: int
    day: date | None
    at: datetime | None
    add: int | None
    drop: int | None
    #: Yahoo's words for the add (``$5 Waiver``, ``Free Agent``) and the bid in it in dollars
    #: as read, None for a free agent's add and a lone drop.
    detail: str | None = None
    bid: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "day": self.day.isoformat() if self.day else None,
            "at": self.at.isoformat() if self.at else None,
            "add": self.add,
            "drop": self.drop,
            "detail": self.detail,
            "bid": self.bid,
        }


def when_at(when: str | None, today: date, zone: tzinfo) -> datetime | None:
    """When a transaction was made, as the page prints it (``Oct 20, 3:57 am``), in ``zone``;
    None when the page gives no date. A date without a time is taken at its midnight."""
    day = when_date(when, today)
    if day is None:
        return None
    m = _CLOCK.search(when or "")
    if m is None:
        return datetime.combine(day, time(), zone)
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return datetime.combine(day, time(hour, int(m.group(2))), zone)


def bid_of(detail: str | None) -> float | None:
    """The bid in Yahoo's words for a claim (``$5 Waiver``), None when it names none."""
    m = _BID.search(detail or "")
    return float(m.group(1)) if m else None


def moves_made(
    transactions: Sequence[Transaction], team_id: int, today: date, zone: tzinfo
) -> list[Made]:
    """My moves on the transactions page, newest first: each group's add and drop (a trade is
    not a move here)."""
    groups: dict[int, list[Transaction]] = {}
    for t in transactions:
        if t.team_id == team_id:
            groups.setdefault(t.group, []).append(t)
    out = []
    for group, rows in groups.items():
        if any(t.kind not in ("add", "drop") for t in rows):
            continue
        add = next((t for t in rows if t.kind == "add"), None)
        drop = next((t for t in rows if t.kind == "drop"), None)
        when = rows[0].when
        out.append(
            Made(
                group,
                when_date(when, today),
                when_at(when, today, zone),
                add.player.yahoo_id if add else None,
                drop.player.yahoo_id if drop else None,
                add.detail if add else None,
                bid_of(add.detail) if add else None,
            )
        )
    return out


def recommended(entry: Mapping[str, Any]) -> list[tuple[int, int | None]]:
    """Every move an entry recommends, over all its sets: (add, drop)."""
    return [
        (int(m["add"]), None if m.get("drop") is None else int(m["drop"]))
        for s in entry.get("sets") or []
        for m in s.get("moves") or []
    ]


def before(made: Made, entries: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The latest entry logged before ``made``; None when the page gives no date for it."""
    if made.at is None:
        return None
    return max(
        (e for e in entries if datetime.fromisoformat(e["at"]) <= made.at),
        key=lambda e: datetime.fromisoformat(e["at"]),
        default=None,
    )


def match(made: Made, entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """How ``made`` compares with the latest entry before it: its kind, the entry, the
    recommended move it matched or overlapped, and whether any entry lies within :data:`NEAR`
    of it, before or after."""
    entries = list(entries)
    near = made.at is not None and any(
        abs(datetime.fromisoformat(e["at"]) - made.at) <= NEAR for e in entries
    )
    entry = before(made, entries)
    if entry is None:
        return {"kind": NO_ENTRY, "entry": None, "move": None, "near": near}
    moves = recommended(entry)
    if made.add is not None and (made.add, made.drop) in moves:
        kind, move = AS_RECOMMENDED, _move((made.add, made.drop))
    else:
        overlap = next(
            (
                m
                for m in moves
                if (made.add is not None and m[0] == made.add)
                or (made.drop is not None and m[1] == made.drop)
            ),
            None,
        )
        kind = DIFFERENTLY if overlap is not None else NOT_RECOMMENDED
        move = _move(overlap) if overlap is not None else None
    return {"kind": kind, "entry": entry["id"], "move": move, "near": near}


def _move(m: tuple[int, int | None]) -> dict[str, Any]:
    return {"add": m[0], "drop": m[1]}


# --------------------------------------------------------------------------- value units (#126)
def _games(
    problem: MoveProblem, key: str, pid: int, player: Any, start: date
) -> tuple[int, date | None, date | None]:
    """The games ``player`` was assumed to play over horizon ``key`` from ``start`` on, as the
    projection counts them, and the horizon's first and last days."""
    games, days = 0, []
    for span in problem.horizons[key]:
        days += span.days
        playing = wk.playing_days(
            [(pid, player)],
            span.days,
            problem.schedule,
            span.this_week,
            span.games,
            problem.no_games,
            available_from={pid: start},
        )
        games += len(playing[pid])
    return games, min(days, default=None), max(days, default=None)


def move_projection(
    problem: MoveProblem,
    scorer: Mapping[str, Any] | None,
    add: int,
    drop: int | None,
    day: date | None = None,
) -> dict[str, Any] | None:
    """A recommended move in value units: the add's and the drop's per-game value under
    ``scorer`` net of an empty line, and on each horizon its days and the games each was
    assumed to play there, the add's from the day the move takes effect (``day``, a streaming
    plan's step's, else the add's effective day) and the drop's given up from that day (or from
    his return, when later); the move's value is the add's games' less the drop's. A plan's
    step may drop an earlier step's add, a candidate, so its steps' values telescope to the
    plan's. None without a scorer or a candidate of the problem's."""
    added = dict(problem.candidates).get(add)
    if scorer is None or added is None:
        return None
    mine = dict(problem.roster) | dict(problem.held) | dict(problem.candidates)
    dropped = mine.get(drop) if drop is not None else None
    start = day if day is not None else problem.effective.get(add, problem.first_day)

    def per_game(pid: int) -> float | None:
        line = problem.rates.get(pid)
        return None if line is None else round(wk.net_value(scorer, line), 4)

    a, d = per_game(add), per_game(drop) if dropped is not None else None
    horizons = {}
    for key in problem.horizons:
        add_games, first, last = _games(problem, key, add, added, start)
        if first is None:
            continue
        drop_games = 0
        if dropped is not None:
            back = max(start, problem.returns.get(drop, start))
            drop_games = _games(problem, key, drop, dropped, back)[0]
        value = None
        if a is not None and (dropped is None or d is not None):
            value = round(add_games * a - drop_games * (d or 0.0), 4)
        horizons[key] = {
            "from": first.isoformat(),
            "to": last.isoformat(),
            "add_games": add_games,
            "drop_games": drop_games if dropped is not None else None,
            "value": value,
        }
    return {
        "add": a,
        "drop": d,
        "horizons": horizons,
    }
