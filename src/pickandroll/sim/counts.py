"""What happened in a run, seat by seat (#172, PR B2): the mechanism counts.

An edge that comes from an artefact (four adds a week against rivals who never move) shows in
them. For each seat over one variant's season: the moves landed, the moves lost because the
player (or the drop) was gone, the adds charged to each week (their mean and the share of weeks
at the league's cap), the drops forced by a returning held player, the held-slot stints and the
days they lasted, the held-slot moves refused because the slot no longer accepted the player the
morning they landed, and the starters' games played. The landing counters live on the state
(``SimState.executed_by``, ``gone_by``, ``forced_by``, ``held_refused_by``); the rest is tallied
here from the days the audit reads and the day's lines once they are scored. Pure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from .engine import HELD
from .state import Setup, SimState

#: A seat's counts over one season, in the payload's order.
METRICS = (
    "landed",
    "gone",
    "adds_per_week",
    "weeks_at_cap",
    "forced_drops",
    "held_refused",
    "held_stints",
    "held_days",
    "starter_games",
)


class Tally:
    """One variant's counts as its season is played."""

    def __init__(self, setup: Setup) -> None:
        self.teams = tuple(setup.teams)
        self.limit = setup.max_weekly_adds
        first = setup.week_of(setup.start)
        #: Adds charged to each week, by team; the adds made before day one count in its week.
        self.adds: dict[int, dict[int, int]] = {t: {} for t in self.teams}
        if first is not None:
            for t in self.teams:
                n = int(setup.adds_used.get(t, 0))
                if n:
                    self.adds[t][first.number] = n
        self.weeks: set[int] = set()
        self.stints = dict.fromkeys(self.teams, 0)
        self.held_days = dict.fromkeys(self.teams, 0)
        self.games = dict.fromkeys(self.teams, 0)
        self._held: dict[int, set[int]] = {t: set() for t in self.teams}

    def charge(self, week: int, before: Mapping[int, int], after: Mapping[int, int]) -> None:
        """The adds that landed this morning (``executed_by`` before and after the landing),
        charged to ``week``, the week of the day they were made."""
        for t in self.teams:
            n = int(after.get(t, 0)) - int(before.get(t, 0))
            if n:
                self.adds[t][week] = self.adds[t].get(week, 0) + n

    def day(self, week: int, state: SimState) -> None:
        """A simulated day of ``week``: each held player's stint goes on or begins."""
        self.weeks.add(week)
        for t in self.teams:
            now = {k for k, slot in state.rosters.get(t, ()) if slot in HELD}
            self.stints[t] += len(now - self._held[t])
            self.held_days[t] += len(now)
            self._held[t] = now

    def played(
        self,
        starters: Mapping[int, Mapping[int, str]],
        day: date,
        line: Callable[[int, date], Mapping[str, float] | None],
    ) -> None:
        """The day's starters who played (a line once the day is scored)."""
        for t, lineup in starters.items():
            self.games[t] = self.games.get(t, 0) + sum(1 for k in lineup if line(k, day))

    def rows(self, state: SimState) -> dict[int, dict[str, float | None]]:
        """Each seat's counts over the season, ``state`` the last day's."""
        weeks = sorted(self.weeks)
        out: dict[int, dict[str, float | None]] = {}
        for t in self.teams:
            per = [self.adds[t].get(w, 0) for w in weeks]
            out[t] = {
                "landed": float(state.executed_by.get(t, 0)),
                "gone": float(state.gone_by.get(t, 0)),
                "adds_per_week": sum(per) / len(per) if per else None,
                "weeks_at_cap": (
                    None
                    if self.limit is None or not per
                    else sum(1 for n in per if n >= self.limit) / len(per)
                ),
                "forced_drops": float(state.forced_by.get(t, 0)),
                "held_refused": float(state.held_refused_by.get(t, 0)),
                "held_stints": float(self.stints[t]),
                "held_days": float(self.held_days[t]),
                "starter_games": float(self.games[t]),
            }
        return out


def pooled(rows: Sequence[Mapping[str, float | None]]) -> dict[str, float | None]:
    """Seats' counts pooled: the mean of each over the seats that have it."""
    out: dict[str, float | None] = {}
    for m in METRICS:
        vals = [r[m] for r in rows if r.get(m) is not None]
        out[m] = sum(vals) / len(vals) if vals else None  # type: ignore[arg-type]
    return out


def row_of(counts: Mapping[Any, Mapping[str, float | None]], seats: Sequence[Any]) -> Any:
    """The pooled row of ``seats``; None when there are none."""
    rows = [counts[s] for s in seats if s in counts]
    return pooled(rows) if rows else None


__all__ = ["METRICS", "Tally", "pooled", "row_of"]
