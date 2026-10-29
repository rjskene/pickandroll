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
From #144 the projection also has a ``season`` horizon, to the season's last day, and each move
says whether it costs the season (:func:`season_costly`) on the horizon it is judged on
(:func:`judging_horizon`). From #187 each move also records its basis (:func:`basis_of`): an
open active spot, a held-slot move that makes room for the add, or a drop; an older entry has
none, which reads as unknown. Pure: the entries are read and written by the API.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from . import moves as mv
from . import weekly as wk
from .moves import MoveProblem, when_date
from .state import Transaction

AS_RECOMMENDED = "as_recommended"
DIFFERENTLY = "differently"
NOT_RECOMMENDED = "not_recommended"
NO_ENTRY = "no_entry"

#: How close to an entry a move is flagged ``near``: the error a wrong zone would make.
NEAR = timedelta(hours=1)
#: The horizons a move is judged on (#143, #144): the rest of its week, the three matchup weeks
#: after, and the rest of the season.
WEEK, THREE, SEASON = "week", "three", "season"
#: The moves route's sets recommended for the three weeks after.
THREE_SETS = ("three",)
#: The strategy's sets solved under the week weight (λ = 1, this week alone) and under the season
#: weight (λ = 0, the rest of the season alone).
WEEK_SET, SEASON_SET = "week", "season"
#: An add's basis (#187): an open active spot, a held-slot move that makes room, or a drop; a
#: drop of a held player is a churn (#221).
OPEN, HELD, DROP, CHURN = "open", "held", "drop", "churn"

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


def basis_of(drop: int | None, held: Mapping[str, Any] | None, churn: bool = False) -> str:
    """A recommended add's basis (#187): :data:`CHURN` when it drops a held player (``churn``,
    #221), :data:`DROP` when it drops an active one, :data:`HELD` when a held-slot move
    (``held``, who goes to which slot) makes room for him, else :data:`OPEN`."""
    if drop is not None:
        return CHURN if churn else DROP
    return HELD if held else OPEN


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


def _season_games(
    problem: MoveProblem, pid: int, player: Any, after: date, counted: int
) -> tuple[float, float]:
    """The games ``player`` was assumed to play to the season's last day, and how many of them
    were extrapolated: on the week's and the three weeks' days, those horizons' own count
    (``counted``); from ``after``, the day after them, from the day he is back as the keep rule
    reads it (``moves.back_from``; none when he does not return this season), his team's games
    on each day the schedule was read and, on the others, its rate over the read days
    (``moves.games_ahead``, the keep rule's count)."""
    back = mv.back_from(problem, pid, player)
    if back is None:
        return float(counted), 0.0
    read, extrapolated = mv.games_ahead(problem, player.nba_team, max(after, back))
    return counted + read + extrapolated, extrapolated


def season_games(
    problem: MoveProblem, pid: int, player: Any, start: date
) -> tuple[float, float] | None:
    """The games ``player`` plays from ``start`` to the season's last day as
    :func:`move_projection` counts an add's or a drop's (the horizons' days from ``start``, then
    :func:`_season_games`), and how many of them are extrapolated beyond the schedule read: a
    traded player's (#151). None without a season end, or from past it."""
    counted, through = 0, None
    for key in problem.horizons:
        games, first, last = _games(problem, key, pid, player, start)
        if first is None:
            continue
        counted += games
        through = max(through or last, last)
    end = problem.season_end
    if through is None or end is None or start > end:
        return None
    return _season_games(problem, pid, player, through + timedelta(1), counted)


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
    plan's. Each horizon also splits the value by category (``cats``, #129), the same way.
    The ``season`` horizon (#144) runs from the move's day to the season's last day on the
    games :func:`_season_games` counts, and says how many of them were extrapolated beyond the
    schedule read (``extrapolated_games``). None without a scorer or a candidate of the
    problem's."""
    added = dict(problem.candidates).get(add)
    if scorer is None or added is None:
        return None
    mine = dict(problem.roster) | dict(problem.held) | dict(problem.candidates)
    dropped = mine.get(drop) if drop is not None else None
    start = day if day is not None else problem.effective.get(add, problem.first_day)

    def per_game(pid: int) -> float | None:
        line = problem.rates.get(pid)
        return None if line is None else round(wk.net_value(scorer, line), 4)

    def by_cat(pid: int | None) -> dict[str, float]:
        line = problem.rates.get(pid) if pid is not None else None
        return wk.net_values(scorer, line or {})

    a, d = per_game(add), per_game(drop) if dropped is not None else None
    a_cats, d_cats = by_cat(add), by_cat(drop if dropped is not None else None)
    priced = a is not None and (dropped is None or d is not None)

    def valued(add_games: float, drop_games: float) -> tuple[float | None, dict[str, float] | None]:
        if not priced:
            return None, None
        value = round(add_games * a - drop_games * (d or 0.0), 4)
        cats = {c: round(add_games * x - drop_games * d_cats[c], 4) for c, x in a_cats.items()}
        return value, cats

    back = max(start, problem.returns.get(drop, start)) if dropped is not None else start
    horizons = {}
    counted = {"add": 0, "drop": 0}
    through: date | None = None
    for key in problem.horizons:
        add_games, first, last = _games(problem, key, add, added, start)
        if first is None:
            continue
        drop_games = _games(problem, key, drop, dropped, back)[0] if dropped is not None else 0
        counted["add"] += add_games
        counted["drop"] += drop_games
        through = max(through or last, last)
        value, cats = valued(add_games, drop_games)
        horizons[key] = {
            "from": first.isoformat(),
            "to": last.isoformat(),
            "add_games": add_games,
            "drop_games": drop_games if dropped is not None else None,
            "value": value,
            "cats": cats,
        }
    end = problem.season_end
    if through is not None and end is not None and start <= end:
        after = through + timedelta(1)
        add_games, add_x = _season_games(problem, add, added, after, counted["add"])
        drop_games, drop_x = 0.0, 0.0
        if dropped is not None:
            drop_games, drop_x = _season_games(problem, drop, dropped, after, counted["drop"])
        value, cats = valued(add_games, drop_games)
        horizons[SEASON] = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "add_games": round(add_games, 2),
            "drop_games": round(drop_games, 2) if dropped is not None else None,
            "extrapolated_games": {
                "add": round(add_x, 2),
                "drop": round(drop_x, 2) if dropped is not None else None,
            },
            "value": value,
            "cats": cats,
        }
    return {
        "add": a,
        "drop": d,
        "horizons": horizons,
    }


def judging_horizon(
    source: str | None, set_key: str | None, value: Mapping[str, Any] | None
) -> str:
    """The horizon a recommended move is judged on (#143, #144): the one its set was recommended
    for. The moves route's week set and streaming plan on the week, its three weeks' set on the
    three weeks after; the strategy's set under the week weight on the week, under the season
    weight on the season when its projection (``value``) has that horizon, and its others (the
    even and the natural weights) on the three weeks after."""
    if source == "strategy":
        if set_key == WEEK_SET:
            return WEEK
        season = set_key == SEASON_SET and SEASON in ((value or {}).get("horizons") or {})
        return SEASON if season else THREE
    return THREE if set_key in THREE_SETS else WEEK


def season_costly(value: Mapping[str, Any] | None, judged: str) -> bool | None:
    """Whether a move costs the season (#144): projected above zero on the horizon it is judged
    on and below zero over the season, whatever the protection floor (#164; the season guard
    draws the same line); None when either figure is missing. It measures the keep rule and
    changes nothing in the engine."""
    horizons = (value or {}).get("horizons") or {}
    on, season = horizons.get(judged), horizons.get(SEASON)
    if not on or not season or on.get("value") is None or season.get("value") is None:
        return None
    return on["value"] > 0 and season["value"] < 0
