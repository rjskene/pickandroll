"""What happened in a run, seat by seat (#172, PR B2): the mechanism counts.

An edge that comes from an artefact (four adds a week against rivals who never move) shows in
them. For each seat over one variant's season: the moves landed, the moves lost because the
player (or the drop) was gone, the adds charged to each week (their mean and the share of weeks
at the league's cap), the drops forced by a returning held player, the held-slot stints and the
days they lasted, the held-slot moves refused because the slot no longer accepted the player the
morning they landed, and the starters' games played. In a waiver league (PR Fa) also the claims
placed, won, lost to a better priority and failed (won and not taken), and of those decided, how
many had a team ahead of the seat's when their player was decided and how many of those were
lost: a waiver run's only, so a run without waivers counts as before. In a FAAB league (PR Fb)
also the dollars spent and left at the end, the claims won at $0, lost to a higher bid, lost on a
tie and won with no other claim on the player, and the dollars won claims paid above the next
bid that could have been taken and lost claims fell short of the winning bid by: a FAAB run's
only, the world's knowledge of every bid, which no decision reads. In a run where an arm takes
the queue's rule (PR E) also the days the queue took a week plan instead of the three weeks' set
and the steps of those plans the executor queued: that run's only, in every seat's row (0 for a
seat that does not take the rule), so a run that names no ``queue`` counts as before. The landing
and claim counters live on the state (``SimState.executed_by``, ``gone_by``, ``forced_by``,
``held_refused_by``, ``claim_counts``); the rest is tallied here from the days the audit reads
and the day's lines once they are scored. Pure.
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
#: The claim counts (PR Fa), a waiver run's only, after :data:`METRICS`, by metric: the key each
#: reads in ``SimState.claim_counts``. A run without waivers has none, so its counts are as before.
CLAIMS = {
    "claims_placed": "placed",
    "claims_won": "won",
    "claims_lost": "lost",
    "claims_failed": "failed",
    "claims_behind": "behind",
    "claims_behind_lost": "behind_lost",
}
#: The bid counts (PR Fb), a FAAB run's only, after :data:`CLAIMS`, by metric: the key each reads
#: in ``SimState.claim_counts`` (``state.BID_COUNTS``), or None for the dollars, read on
#: ``SimState.dollars``.
BIDS: dict[str, str | None] = {
    "dollars_spent": None,
    "dollars_left": None,
    "claims_won_free": "won_free",
    "claims_lost_bid": "lost_bid",
    "claims_lost_tie": "lost_tie",
    "claims_won_alone": "alone",
    "bid_over_next": "over",
    "bid_short": "short",
}


#: The queue's counts (PR E), only in a run where an arm executes ``queue``, after :data:`BIDS`:
#: the days the queue took a week plan instead of the three weeks' set, and the steps of those
#: plans queued (a free agent's add for the next morning, or a claim placed). Whether a queued
#: step then landed is in ``landed``, ``gone`` and the claim counts, with every other move.
PLANS = ("plan_days", "plan_steps")


class Tally:
    """One variant's counts as its season is played. ``plans``: the run has an arm that takes
    the queue's rule, so every seat's row carries :data:`PLANS`."""

    def __init__(self, setup: Setup, plans: bool = False) -> None:
        self.plans = plans
        self.plan_days: dict[int, int] = {}
        self.plan_steps: dict[int, int] = {}
        self.teams = tuple(setup.teams)
        self.limit = setup.max_weekly_adds
        self.waiting = setup.waiting
        self.bidding = setup.bidding
        self.budget = setup.budget
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

    def took(self, team: int, steps: int) -> None:
        """``team``'s queue took a week plan today (PR E), and ``steps`` of it were queued."""
        self.plan_days[team] = self.plan_days.get(team, 0) + 1
        self.plan_steps[team] = self.plan_steps.get(team, 0) + steps

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
            if self.waiting:
                claims = state.claim_counts.get(t, {})
                out[t] |= {m: float(claims.get(key, 0)) for m, key in CLAIMS.items()}
            if self.bidding:
                bids = state.claim_counts.get(t, {})
                left = int(state.dollars.get(t, self.budget))
                dollars = {"dollars_spent": self.budget - left, "dollars_left": left}
                out[t] |= {
                    m: float(dollars[m] if key is None else bids.get(key, 0))
                    for m, key in BIDS.items()
                }
            if self.plans:
                out[t] |= {
                    "plan_days": float(self.plan_days.get(t, 0)),
                    "plan_steps": float(self.plan_steps.get(t, 0)),
                }
        return out


def metrics_in(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The counts ``rows`` hold, in the payload's order: :data:`METRICS`, then the claim counts
    when a row has them (a waiver run's), then the bid counts (a FAAB run's), then the queue's
    (a run with an arm that executes ``queue``)."""
    extra = (*CLAIMS, *BIDS, *PLANS)
    return (*METRICS, *(m for m in extra if any(m in r for r in rows)))


def pooled(rows: Sequence[Mapping[str, float | None]]) -> dict[str, float | None]:
    """Seats' counts pooled: the mean of each over the seats that have it."""
    out: dict[str, float | None] = {}
    for m in metrics_in(rows):
        vals = [r[m] for r in rows if r.get(m) is not None]
        out[m] = sum(vals) / len(vals) if vals else None  # type: ignore[arg-type]
    return out


def row_of(counts: Mapping[Any, Mapping[str, float | None]], seats: Sequence[Any]) -> Any:
    """The pooled row of ``seats``; None when there are none."""
    rows = [counts[s] for s in seats if s in counts]
    return pooled(rows) if rows else None


__all__ = ["BIDS", "CLAIMS", "METRICS", "PLANS", "Tally", "metrics_in", "pooled", "row_of"]
