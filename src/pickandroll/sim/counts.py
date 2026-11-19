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
only, the world's knowledge of every bid, which no decision reads; and (PR F2) the dollars left
on the first day of the bracket, the weeks the seat stood at $0 and the value its won claims
were sized on, for every seat of a FAAB run whatever its bid policy. The landing and claim
counters live on the state (``SimState.executed_by``, ``gone_by``, ``forced_by``,
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
#: ``SimState.dollars``, and for the bid policy's three (PR F2, :data:`PACING`).
BIDS: dict[str, str | None] = {
    "dollars_spent": None,
    "dollars_left": None,
    "claims_won_free": "won_free",
    "claims_lost_bid": "lost_bid",
    "claims_lost_tie": "lost_tie",
    "claims_won_alone": "alone",
    "bid_over_next": "over",
    "bid_short": "short",
    "dollars_at_bracket": None,
    "weeks_at_zero": None,
    "value_won": None,
}
#: The bid policy's three counts (PR F2), the last of :data:`BIDS`, for every seat of a FAAB run
#: whatever its ``bid`` (so a pair compares): did it pace (the dollars left on the first
#: simulated day of the bracket's first week, after that morning's claims; None where no bracket
#: is read), did it run dry (the days it stood at $0, in weeks; 0 when it never did), and what a
#: dollar bought (the summed value in typicals of the claims it won, ``Claim.value``, to divide
#: by ``dollars_spent``; 0 for a seat that holds no such value: the ranking tier, a market rival).
PACING = ("dollars_at_bracket", "weeks_at_zero", "value_won")


class Tally:
    """One variant's counts as its season is played."""

    def __init__(self, setup: Setup) -> None:
        self.teams = tuple(setup.teams)
        self.limit = setup.max_weekly_adds
        self.waiting = setup.waiting
        self.bidding = setup.bidding
        self.budget = setup.budget
        #: The bid policy's counts (PR F2): the first week of the bracket (None when it is not
        #: read), each team's dollars on its first simulated day, and its days at $0.
        self.bracket = min(setup.spec.playoff_weeks, default=None) if setup.spec else None
        self.at_bracket: dict[int, int] = {}
        self.dry = dict.fromkeys(self.teams, 0)
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
        """A simulated day of ``week``: each held player's stint goes on or begins; in a FAAB
        league each team's dollars are read, once the morning's claims are decided."""
        self.weeks.add(week)
        for t in self.teams:
            now = {k for k, slot in state.rosters.get(t, ()) if slot in HELD}
            self.stints[t] += len(now - self._held[t])
            self.held_days[t] += len(now)
            self._held[t] = now
            if self.bidding:
                left = int(state.dollars.get(t, self.budget))
                if week == self.bracket:
                    self.at_bracket.setdefault(t, left)
                if left <= 0:
                    self.dry[t] += 1

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
                own: dict[str, float | None] = {
                    "dollars_spent": self.budget - left,
                    "dollars_left": left,
                    "dollars_at_bracket": self.at_bracket.get(t),
                    "weeks_at_zero": self.dry[t] / 7,
                    "value_won": state.value_won.get(t, 0.0),
                }
                for m, key in BIDS.items():
                    x = own[m] if key is None else bids.get(key, 0)
                    out[t][m] = None if x is None else float(x)
        return out


def metrics_in(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The counts ``rows`` hold, in the payload's order: :data:`METRICS`, then the claim counts
    when a row has them (a waiver run's), then the bid counts (a FAAB run's)."""
    extra = (*CLAIMS, *BIDS)
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


__all__ = ["BIDS", "CLAIMS", "METRICS", "PACING", "Tally", "metrics_in", "pooled", "row_of"]
