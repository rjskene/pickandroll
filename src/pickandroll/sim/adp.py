"""The draft market (#172, PR D4a): a season's table of average draft positions.

ESPN's season logs (``sim.gamelogs``) carry each player's average draft position over ESPN's
drafts (``player.ownership.averageDraftPosition``). Three facts about it were settled on the logs
on file before anything was built on it, and ``docs/sim/README.md`` says them in words:

- a season's figure is that season's own: players in their first season on file carry figures
  off the ceiling, so it is no earlier season's draft; so do players in their last season on
  file, so it is no later season's (where a later log is on file: the hold-out's is never
  opened); and its order agrees with the season's own stored projection at least as well as
  with another season's;
- an undrafted player carries the ceiling, the figure the most players share at the top of the
  range: such a player is **not listed**, and every player that is sits ahead of him;
- the figure pools ESPN's drafts whatever their scoring: ``ownership.leagueType`` is one value
  for every player of every season.

A log whose players all carry one and the same figure holds no table (:class:`NoTable`). Pure:
the log is read by ``sim/readers.py``.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Where a run's table comes from: none (the draft on the run's forecaster, as before PR D4a) or
#: ESPN's figure in the season's own log.
SOURCES = ("none", "espn")
#: The figure read, in the log's player rows.
COLUMN = "ownership.averageDraftPosition"


class NoTable(ValueError):
    """The log carries no spread of figures: there is no table to draft on."""


@dataclass(frozen=True)
class Table:
    """A season's table: each listed player's average pick, by id. The undrafted (the players at
    :attr:`ceiling`) and the players with no figure are not listed."""

    source: str
    picks: Mapping[int, float]
    #: The figure the undrafted carry (the one the most players share), None when no figure is
    #: shared.
    ceiling: float | None
    at_ceiling: int
    no_figure: int
    players: int

    def payload(self) -> dict[str, Any]:
        """The table in counts: no figure (they stay under ``data/``)."""
        return {
            "source": self.source,
            "column": COLUMN,
            "players": self.players,
            "listed": len(self.picks),
            "at_ceiling": self.at_ceiling,
            "no_figure": self.no_figure,
        }


def _figure(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) and x > 0 else None


def espn_table(body: Mapping[str, Any]) -> Table:
    """The table in a season's log (``gamelogs.load_season``'s body). The ceiling is the figure
    the most players share (the larger at a tie), when more than one does. Refused
    (:class:`NoTable`) when fewer than two figures are carried: one figure for everyone is no
    order."""
    rows = body.get("players") or []
    figures: dict[int, float] = {}
    no_figure = 0
    for row in rows:
        p = row.get("player") or {}
        x = _figure((p.get("ownership") or {}).get("averageDraftPosition"))
        if x is None or p.get("id") is None:
            no_figure += 1
            continue
        figures[int(p["id"])] = x
    if len(set(figures.values())) < 2:
        raise NoTable(
            "its log carries one and the same draft position for every player"
            if figures
            else "its log carries no draft position"
        )
    shared, n = max(Counter(figures.values()).items(), key=lambda kv: (kv[1], kv[0]))
    ceiling = shared if n > 1 else None
    picks = {k: x for k, x in figures.items() if x != ceiling}
    return Table("espn", picks, ceiling, n if ceiling is not None else 0, no_figure, len(rows))


# --------------------------------------------------------------------------- the boards
@dataclass(frozen=True)
class Spread:
    """A rival's error about the table: a listed player's place on his board is his average pick
    plus a normal draw at ``base + growth * pick`` picks, with no bias. Given on the command
    line, never fitted here: both at least zero."""

    base: float
    growth: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.base) and math.isfinite(self.growth)):
            raise ValueError("the spread's base and growth are numbers")
        if self.base < 0 or self.growth < 0:
            raise ValueError("the spread's base and growth are at least zero")

    def at(self, pick: float) -> float:
        return self.base + self.growth * pick

    def payload(self) -> dict[str, Any]:
        return {"base": self.base, "growth": self.growth, "given": "on the command line"}


def parse_spread(text: str) -> Spread:
    """``<base>,<growth>``, both at least zero."""
    parts = [x.strip() for x in str(text).split(",")]
    if len(parts) != 2:
        raise ValueError(f"--adp-spread {text!r}: two figures, <base>,<growth>")
    try:
        base, growth = float(parts[0]), float(parts[1])
    except ValueError:
        raise ValueError(f"--adp-spread {text!r}: two figures, <base>,<growth>") from None
    return Spread(base, growth)


@dataclass(frozen=True)
class Draft:
    """How a replay's league is drafted on a table (#172, PR D4a): the listed players' average
    picks, the rivals' spread, the path's ``(seed, path)`` the rivals' draws are keyed on, and
    the seats that draft on a board of their own (an arm's), each with its forecaster's
    projection on draft day; every other seat is a rival."""

    picks: Mapping[int, float]
    spread: Spread
    seed: int
    path: int
    seats: Mapping[int, Mapping[int, Mapping[str, float]]] = field(default_factory=dict)


def rival_board(
    picks: Mapping[int, float],
    draftable: Sequence[int],
    value: Mapping[int, float],
    spread: Spread,
    g: np.random.Generator,
) -> list[int]:
    """A rival's board, best first. Every listed player of the table gets one standard normal
    draw from ``g``, in the order of his average pick (then id), whether he can be drafted or
    not, so the board's draws do not move with who can; his place is his pick plus the draw at
    :meth:`Spread.at` his pick. The draftable listed players by place (then id), then the
    draftable players the table does not list, by ``value`` (the run's forecaster's; higher
    first, then id): an unlisted player is never ahead of a listed one."""
    order = sorted(picks, key=lambda k: (picks[k], k))
    z = g.standard_normal(len(order))
    place = {k: picks[k] + float(z[i]) * spread.at(picks[k]) for i, k in enumerate(order)}
    can = list(dict.fromkeys(draftable))
    listed = sorted((k for k in can if k in place), key=lambda k: (place[k], k))
    rest = sorted((k for k in can if k not in place), key=lambda k: (-value.get(k, 0.0), k))
    return listed + rest


def seat_board(value: Mapping[int, float], draftable: Sequence[int]) -> list[int]:
    """An arm's seat's board, best first: the draftable players its own forecaster values, by
    that value (higher first, then id). A player it has no value for is not on it: the seat
    cannot value him and never drafts him."""
    return sorted((k for k in dict.fromkeys(draftable) if k in value), key=lambda k: (-value[k], k))


def market_view(
    picks: Mapping[int, float], value: Mapping[int, float], players: Sequence[int]
) -> dict[int, float]:
    """The market's view under a table, higher better: a listed player's is the negative of his
    average pick; a player the table does not list sits below every listed one, ordered by
    ``value`` (the run's forecaster's on draft day; higher first, then id). A player neither
    listed nor valued is in no view. The league's ``players`` only. It is the preseason's and
    does not refresh."""
    listed = {k: -float(picks[k]) for k in players if k in picks}
    floor = min(listed.values(), default=0.0) - 1.0
    rest = sorted(
        (k for k in players if k not in picks and k in value), key=lambda k: (-value[k], k)
    )
    return {**listed, **{k: floor - i for i, k in enumerate(rest)}}


__all__ = [
    "COLUMN",
    "SOURCES",
    "Draft",
    "NoTable",
    "Spread",
    "Table",
    "espn_table",
    "market_view",
    "parse_spread",
    "rival_board",
    "seat_board",
]
