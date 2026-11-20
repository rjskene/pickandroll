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
were sized on, for every seat of a FAAB run whatever its bid policy. In a run where an arm names a
stash threshold (PR G) also the returning players the seat dropped: such a run's only, so a run
that names none counts as before. In a run where an arm takes the queue's rule (PR E) also the
days the queue took a week plan instead of the three weeks' set and the steps of those plans the
executor queued: that run's only, in every seat's row (0 for a seat that does not take the rule),
so a run that names no ``queue`` counts as before. The landing and claim
counters live on the state (``SimState.executed_by``, ``gone_by``, ``forced_by``,
``held_refused_by``, ``claim_counts``); the rest is tallied here from the days the audit reads
and the day's lines once they are scored. In a run where an arm names its guard or its stake (the
guard PR) also, on the seats of the run's arms on the exact or the surrogate tier, the sets
decided that the season guard would have refused, and the season's mean week's stake with the
weeks it was above a half: such a run's only, so a run that names neither counts as before. Pure.
In a run where an arm sets ``guard_pool`` above 0 (PR pool) also, on the run's arms' seats on
the exact tier, the days a union pool was built, the adds the guard's list brought beyond the
head and the days it brought any, the days the seat queued or claimed one of them, and the
days the guard refused the best single move of an add of the head: such a run's only.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import date
from typing import Any

from .engine import HELD
from .state import Setup, SimState

#: The week's stake above which a week is counted in ``stake_weeks_above_half``.
HALF = 0.5

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


#: The stash count (PR G), after :data:`BIDS`, only in a run where an arm names a stash
#: threshold: the players who left the seat's roster (a move's drop, a churn's held drop, a drop
#: a returning held player forced) whom the engine read as returning on the seat's problem the
#: day before (``moves.returning_net`` not None, ``policy.returning_of``); a claim's drop, who
#: is off the seat's problem while the claim is open, as he was read the day the claim was
#: placed (:meth:`Tally.reading`). None for a seat that builds no problem (a market or a static
#: rival): nothing reads its players.
STASH = ("returning_dropped",)

#: The guard's and the stake's counts (the guard PR), after :data:`STASH`, by the season field
#: (``policy.SEASON_FIELDS``) whose naming brings them: in a run where an arm names ``guard``,
#: the sets its arms' seats decided that the season guard would have refused (none under the
#: block, by construction; under ``off`` a lower bound on how often the block would have turned
#: the decision); in one where an arm names ``stake``, the mean of the week's stake
#: ``L`` over the weeks the seat played and the weeks ``L`` was above :data:`HALF`. On the
#: run's arms' seats whose tier reads the fields, never a rival's; a run that names neither has
#: none, so its counts are as before.
#:
#: The union pool's counts (PR pool), by the arm field whose setting brings them: in a run
#: where an arm sets ``guard_pool`` above 0, over the decision days of each of the run's arms'
#: seats on the exact tier, the days a union pool was built (``union_days``: every such day of
#: an arm with the field on whose guard blocks), the adds the guard's list brought that the
#: head did not hold, summed (``union_admitted``: over ``union_days`` it is their mean) and the
#: days it brought any (``union_admitted_days``), the days the seat queued or claimed a move
#: of its set whose add the set took from the list and not from the head
#: (``union_taken_days``: a listed add went out, the day's cap and the week's adds applied;
#: never a day a plan leads under the queue's rule, ``policy.queue_rule``), and the days the
#: season guard refused the best single move of an add of the head
#: (``union_head_refused_days``: how often the cut before the guard costs the search an add).
#: 0 for an arm at 0, by construction; never a rival's. A run that leaves the field off has
#: none, so its counts are as before. Under the queue's rule a day's figures are its two sets'
#: together (``policy.queue_rule``).
SEASON: dict[str, tuple[str, ...]] = {
    "guard": ("sets_past_guard",),
    "stake": ("stake_mean", "stake_weeks_above_half"),
    "guard_pool": (
        "union_days",
        "union_admitted",
        "union_admitted_days",
        "union_taken_days",
        "union_head_refused_days",
    ),
}

#: The queue's counts (PR E), only in a run where an arm executes ``queue``, after the guard's
#: and the stake's (:data:`SEASON`): the days the queue took a week plan instead of the three
#: weeks' set, and the steps of those plans queued (a free agent's add for the next morning, or
#: a claim placed). Whether a queued step then landed is in ``landed``, ``gone`` and the claim
#: counts, with every other move.
PLANS = ("plan_days", "plan_steps")

#: The counts that part by construction between two arms and are no difference of the season:
#: what a pair's two rows may differ in while the two arms played one season. The screen's
#: "did nothing" sets them aside when it says whether the two arms' counts are equal
#: (``screen.result_of`` reads this tuple and names no count itself); both rows are still
#: recorded whole. The one declaration: a PR whose count is of this kind appends its key here,
#: a line a key with its reason, and declares nothing of its own elsewhere.
APART_BY_CONSTRUCTION: tuple[str, ...] = (
    # The guard PR: an arm on the block has none, by construction. A set an ``off`` arm
    # decided past the guard and never queued is no difference in the season, and one that is
    # queued shows in the other counts.
    "sets_past_guard",
    # PR F2: the summed value in typicals of the claims a seat won is measured in the arm's own
    # weights, so a weight of the bid block moves it by itself, whatever the arm then bids. Two
    # arms apart in it alone placed the same claims at the same bids and played one season.
    "value_won",
    # PR pool: four of the union's, which describe an arm's own search: an arm with
    # ``guard_pool`` on counts them and an arm at 0 never does, whatever either plays (it
    # builds a union every decision day). ``union_taken_days`` is not one of them: an add
    # from the list that the seat queued or claimed is a real difference.
    "union_days",
    "union_admitted",
    "union_admitted_days",
    "union_head_refused_days",
)


class Tally:
    """One variant's counts as its season is played. ``stash``: the run names a stash threshold,
    and the returning players each seat drops are counted (:data:`STASH`). ``counted``, by team,
    names the season fields (:data:`SEASON`'s keys) the run counts on that seat; none by
    default. ``plans``: the run has an arm that takes the queue's rule, so every seat's row
    carries :data:`PLANS`."""

    def __init__(
        self,
        setup: Setup,
        stash: bool = False,
        counted: Mapping[int, Sequence[str]] | None = None,
        plans: bool = False,
    ) -> None:
        self.stash = stash
        #: Each seat's players its last decision read as returning (with the drops of its open
        #: claims as read the day each was placed), and those of them it dropped.
        self._returning: dict[int, frozenset[int]] = {}
        self.returning_dropped: dict[int, int] = {}
        self.plans = plans
        self.plan_days: dict[int, int] = {}
        self.plan_steps: dict[int, int] = {}
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
        self.counted = {t: tuple(names) for t, names in (counted or {}).items() if names}
        #: The sets a counted seat decided past the guard, and its stake by week.
        self.past = dict.fromkeys(self.counted, 0)
        self.stakes: dict[int, dict[int, float]] = {t: {} for t in self.counted}
        #: A counted seat's union pools, summed over its decision days.
        self.unions: dict[int, dict[str, int]] = {
            t: dict.fromkeys(SEASON["guard_pool"], 0)
            for t, names in self.counted.items()
            if "guard_pool" in names
        }

    def charge(self, week: int, before: Mapping[int, int], after: Mapping[int, int]) -> None:
        """The adds that landed this morning (``executed_by`` before and after the landing),
        charged to ``week``, the week of the day they were made."""
        for t in self.teams:
            n = int(after.get(t, 0)) - int(before.get(t, 0))
            if n:
                self.adds[t][week] = self.adds[t].get(week, 0) + n

    def reading(self, team: int, returning: frozenset[int], state: SimState) -> None:
        """``team``'s seat decided today, on ``state``, on a problem whose returning players are
        ``returning``. The problem is the roster as the seat's open claims will leave it
        (``moves.with_pending``): a claim's drop is off it from the day after the claim is
        placed, though he is on the team's roster until the claim is won. So the drop of a claim
        still open today stays in the reading as he was read the day it was placed, until the
        claim is decided: a claim that waits two mornings or more counts like any other move."""
        claimed = {c.move.drop for c in state.claims.get(team, ())}
        waiting = self._returning.get(team, frozenset()) & claimed
        self._returning[team] = returning | waiting
        self.returning_dropped.setdefault(team, 0)

    def left(self, before: SimState, after: SimState) -> None:
        """A morning, from the state before anything landed to the one after: each player who
        left a seat's roster and whom its last reading (:meth:`reading`) holds as returning is
        counted."""
        for t, returning in self._returning.items():
            if not returning:
                continue
            still = {k for k, _ in after.rosters.get(t, ())}
            gone = {k for k, _ in before.rosters.get(t, ())} - still
            self.returning_dropped[t] += len(gone & returning)

    def decided(self, team: int, decision: Any) -> None:
        """``team``'s decision of the day (a ``policy.Decision``): a set decided past the guard
        is counted on a counted seat."""
        if team in self.past and decision.past_guard:
            self.past[team] += 1

    def searched(self, team: int, union: Any, queued: Collection[int]) -> None:
        """The union pool ``team``'s search took today (PR pool: a ``policy.PoolUnion``, the
        decision's; None when none was built) and the adds of its set's moves the seat then
        ``queued`` or claimed, the day's cap and the week's adds applied: counted on a seat
        that counts the union. A day is one of ``union_taken_days`` when one of those adds is
        one the set took from the list (``union.took``); a set the cap or the week's adds cut
        back to what the seat at 0 queues is not one."""
        row = self.unions.get(team)
        if row is None or union is None:
            return
        row["union_days"] += 1
        row["union_admitted"] += union.admitted
        row["union_admitted_days"] += union.admitted > 0
        row["union_taken_days"] += any(c in queued for c in union.took)
        row["union_head_refused_days"] += union.refused > 0

    def took(self, team: int, steps: int) -> None:
        """``team``'s queue took a week plan today (PR E), and ``steps`` of it were queued."""
        self.plan_days[team] = self.plan_days.get(team, 0) + 1
        self.plan_steps[team] = self.plan_steps.get(team, 0) + steps

    def day(self, week: int, state: SimState) -> None:
        """A simulated day of ``week``: each held player's stint goes on or begins; on the
        week's first, a counted seat's stake for the week is kept (``SimState.stakes``); in a
        FAAB league each team's dollars are read, once the morning's claims are decided."""
        if week not in self.weeks:
            for t, by_week in self.stakes.items():
                if t in state.stakes:
                    by_week[week] = float(state.stakes[t])
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
            if self.stash:
                n = self.returning_dropped.get(t)
                out[t]["returning_dropped"] = None if n is None else float(n)
            names = self.counted.get(t, ())
            if "guard" in names:
                out[t]["sets_past_guard"] = float(self.past[t])
            if "stake" in names:
                levels = list(self.stakes[t].values())
                out[t]["stake_mean"] = sum(levels) / len(levels) if levels else None
                out[t]["stake_weeks_above_half"] = (
                    float(sum(1 for x in levels if x > HALF)) if levels else None
                )
            if t in self.unions:
                out[t] |= {m: float(n) for m, n in self.unions[t].items()}
            if self.plans:
                out[t] |= {
                    "plan_days": float(self.plan_days.get(t, 0)),
                    "plan_steps": float(self.plan_steps.get(t, 0)),
                }
        return out


def metrics_in(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The counts ``rows`` hold, in the payload's order: :data:`METRICS`, then the claim counts
    when a row has them (a waiver run's), then the bid counts (a FAAB run's), then the stash
    count (a run's that names a stash threshold, PR G), then the guard's, the stake's and the
    union pool's (a run that names them, :data:`SEASON`), then the queue's (a run with an arm that executes ``queue``, PR E)."""
    season = (m for group in SEASON.values() for m in group)
    extra = (*CLAIMS, *BIDS, *STASH, *season, *PLANS)
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


__all__ = [
    "APART_BY_CONSTRUCTION",
    "BIDS",
    "CLAIMS",
    "HALF",
    "METRICS",
    "PACING",
    "PLANS",
    "SEASON",
    "STASH",
    "Tally",
    "metrics_in",
    "pooled",
    "row_of",
]
