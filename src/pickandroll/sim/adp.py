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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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


__all__ = ["COLUMN", "SOURCES", "NoTable", "Table", "espn_table"]
