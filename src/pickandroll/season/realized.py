"""A move's realized value (#126, part 2; docs/ADD_DROP.md "Scorecard"): the added player's games
in the move's span less the dropped player's, both from the move on, each game's actual line
valued with the decision log entry's scorer (``weekly.net_value``, in the units the entry priced
the move in). Every game the two played counts, whoever started; a game that began before the
move is not his.

The spans are the projection's horizons: ``week``, from the move to the end of its matchup
week, ``three``, the three matchup weeks after it, and ``season`` (#144), from the move to the
season's last day, complete only once the season is over and "so far" until then. A span is
counted through its last day read without a gap from its first (``through``): a day not read
yet stops it, and is listed in ``missing`` once it is over. A player not matched to the box
scores is a gap: his team's games in the span are counted in ``gaps`` and the span has no
value, never a zero (until his team plays there is nothing to miss: no games, no value). A
later move that drops the added player counts his games from then on against itself, so a
stream's moves add up to what the spot made.

Pure: the games are ``sources.boxscores``' cached days, read by ``api.season_scorecard``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from . import weekly as wk
from .calendar import Calendar, Week

#: The weeks after the move's own that ``three`` spans (the Moves card's horizon).
AFTER = 3
#: Why a move has no realized value.
NO_TIME, NO_SCORER, UNMATCHED, NOT_READ = "no_time", "no_scorer", "unmatched", "not_read"

Game = Mapping[str, Any]


@dataclass(frozen=True)
class Side:
    """One player of a move: his Yahoo id, his NBA team as Yahoo listed it, and his ESPN id
    with how it was matched (``id``, ``team`` or ``name``), None when unmatched."""

    yahoo: int
    team: str | None
    espn: str | None = None
    by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"yahoo": self.yahoo, "espn": self.espn, "by": self.by}


def spans(week: Week, day: date, calendar: Calendar | None = None) -> dict[str, tuple[date, date]]:
    """A move's spans: ``week`` from its day to its week's end, ``three`` over the
    :data:`AFTER` matchup weeks after (fewer at the season's end, none after it; seven-day
    weeks when the calendar is not known), and ``season`` from its day to the calendar's last
    day (#144; none without a calendar)."""
    out = {"week": (day, week.end)}
    if calendar is None:
        out["three"] = (week.end + timedelta(1), week.end + timedelta(7 * AFTER))
        return out
    later = [w for w in calendar.weeks if w.start > week.end][:AFTER]
    if later:
        out["three"] = (later[0].start, later[-1].end)
    end = max((w.end for w in calendar.weeks), default=None)
    if end is not None and day <= end:
        out["season"] = (day, end)
    return out


def _start(game: Game) -> datetime | None:
    try:
        return datetime.fromisoformat(str(game["start"]))
    except (KeyError, ValueError):
        return None


def _after(game: Game, at: datetime) -> bool:
    start = _start(game)
    return start is not None and start >= at


def span(
    first: date,
    last: date,
    at: datetime,
    games: Mapping[date, Sequence[Game]],
    sides: Mapping[str, Side],
    scorer: Mapping[str, Any],
    today: date,
) -> dict[str, Any]:
    """One span of a move: the days read, each side's games and their value, and the move's
    value (the add's less the drop's) with its share by category (``cats``, #129); None while a
    side is unmatched or no day is read."""
    through = None
    day = first
    while day <= last and day in games:
        through, day = day, day + timedelta(1)
    missing = [
        (first + timedelta(n)).isoformat()
        for n in range((min(last, today - timedelta(1)) - first).days + 1)
        if first + timedelta(n) not in games
    ]
    played = [
        g
        for n in range(((through - first).days + 1) if through else 0)
        for g in games[first + timedelta(n)]
        if _after(g, at)
    ]
    out: dict[str, Any] = {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "through": through.isoformat() if through else None,
        "complete": through == last,
        "missing": missing,
    }
    gaps, values, by_cat = 0, {}, {}
    for key in ("add", "drop"):
        side = sides.get(key)
        if side is None:
            out[f"{key}_games"] = None
            continue
        if side.espn is None:
            team = [g for g in played if side.team and side.team in (g.get("teams") or ())]
            if side.team and not team:
                # His team has not played: no game to miss, nothing to match him on yet.
                out[f"{key}_games"], values[key], by_cat[key] = 0, 0.0, {}
                continue
            gaps += len(team)
            out[f"{key}_games"] = None
            values[key] = None
            continue
        lines = [
            p["line"]
            for g in played
            if (p := (g.get("players") or {}).get(side.espn)) and p.get("line") is not None
        ]
        total: dict[str, float] = {}
        for line in lines:
            for stat, x in line.items():
                total[stat] = total.get(stat, 0.0) + float(x)
        out[f"{key}_games"] = len(lines)
        values[key] = round(wk.net_value(scorer, total), 4)
        by_cat[key] = wk.net_values(scorer, total)
    out["add"], out["drop"] = values.get("add"), values.get("drop")
    out["gaps"] = gaps
    known = through is not None and all(v is not None for v in values.values())
    out["value"] = (
        round((values.get("add") or 0.0) - (values.get("drop") or 0.0), 4) if known else None
    )
    add, drop = by_cat.get("add") or {}, by_cat.get("drop") or {}
    out["cats"] = (
        {c: round(add.get(c, 0.0) - drop.get(c, 0.0), 4) for c in wk.net_values(scorer, {})}
        if known
        else None
    )
    return out


def realized(
    at: datetime | None,
    day: date | None,
    week: Week,
    add: Side | None,
    drop: Side | None,
    scorer: Mapping[str, Any] | None,
    games: Mapping[date, Sequence[Game]],
    today: date,
    calendar: Calendar | None = None,
) -> dict[str, Any]:
    """A move's realized value on each span, and whether it has one (``valued``): when its time
    is known, a scorer values it, its week's span has a day read and has a value, its players
    matched; else ``reason`` says why not (``no_time``, ``no_scorer``, ``not_read``,
    ``unmatched``). A later span with a gap keeps its gaps and no value, the move valued on its
    week."""
    sides = {k: s for k, s in (("add", add), ("drop", drop)) if s is not None}
    out: dict[str, Any] = {
        "valued": False,
        "reason": None,
        **{k: s.to_dict() if s else None for k, s in (("add", add), ("drop", drop))},
        "horizons": {},
    }
    if at is None or day is None:
        return {**out, "reason": NO_TIME}
    if scorer is None:
        return {**out, "reason": NO_SCORER}
    out["horizons"] = {
        key: span(first, last, at, games, sides, scorer, today)
        for key, (first, last) in spans(week, day, calendar).items()
    }
    if out["horizons"]["week"]["through"] is None:
        return {**out, "reason": NOT_READ}
    if out["horizons"]["week"]["value"] is None:
        return {**out, "reason": UNMATCHED}
    return {**out, "valued": True}
