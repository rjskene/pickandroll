"""The engine as a policy (#172, PR 2b): the move problem built from simulated state, the
tiers that solve it, and the executor that lands what they decide.

:func:`problem_of` mirrors ``api.season_moves.build`` step for step from in-memory inputs: the
spans from the setup's calendar, the opponents projected with ``weekly.project_week`` from the
shared beliefs, the candidates from the pool, the add limits from the league's rule and the adds
used, the keep rule's inputs from the same beliefs, then the knobs. This week's opponent and
both sides' totals so far come from one place, :func:`week_view`: the pairing's opponent, and in
a round of the bracket the round's (PR bracket: :func:`seed_round` seeds each round on its first
morning from the state's own totals, :func:`opponent_of` reads it), where a week had no opponent
before; the runner keys a strategy that reads the week (:func:`reads_week`) on the same view (PR
F2).
**Every knob comes in as a
mapping of the twelve names of** :data:`KNOBS` **(the ten the live knob file takes,
``season.progress.LIVE_KNOBS``, each within the engine's own bounds, and the simulator's two); a
missing name raises; nothing here reads the knob file.** The season guard is
``moves.season_guard(ros)`` with ``ros`` the engine's own rest-of-season value of a move
(``season.decisions.move_projection``) under the simulated world's beliefs, passed explicitly into
every search.

Three tiers, each with the arm's :class:`Fields` (the live route's figures by default). **Exact**
is the live moves route: single swaps over every candidate, the best ``pool`` by gain, the
recommended set priced by re-solves on the horizon the autopilot queues (``three``), the week's
streaming plan beside it; or, when the arm says ``executes: weighted``, the strategy route's
weighted set under the horizon weight knob (its search, no program). **Surrogate** is the same
evaluator on the ``pool`` best candidates by value times games, the greedy search alone, solved
on the ``surrogate_days`` (Monday and Thursday). **Ranking** swaps the pool's best by value times
games for the roster's worst the keep rule does not keep, no evaluator.

**The season term** (:class:`SeasonFigure`, :func:`seasoned`): at a ``season_weight`` above 0,
the exact and the surrogate tiers rank and search on their odds value plus ``season_weight``
times ``ROS_w``, the moves' season value above a dead spot times the games left, a bracket game
counted ``playoff_weight`` times, on the key the arm executes and no other. At ``season_weight``
0 the wrapper is not built and every search runs on the engine's values, as before the term.
:func:`reads` says which knobs a seat reads in a league's :class:`Shape`.

Executions are the autopilot's (``season.autopilot``): a decided move lands the next day, at most
``daily_cap`` a day and the league's adds a week, never a kept player dropped; in a league without
waivers every add is a free agent. The executor keeps the roster as Yahoo would: a held player whose
status has cleared comes back to the bench the next morning and, over the league's spots, a player
leaves: the one the team's seat named for him (PR G, below), else the least valuable active player
(the engine's rule for a cleared player with no choice made); the held-slot moves a set
needs are made before its adds land, each only while its slot has room and accepts the player's
status on the morning it lands (``moves.eligible``: a move is carried out against the day it lands,
as an add another team took is); an add that needs an active spot (no drop, a churn's held drop,
#221, or a held move refused) takes a bench slot and is gone when none is open.

**Waivers** (PR Fa, a league whose ``waivers`` is ``priority``): a player who leaves a roster on the
morning of day ``d`` waits until his clear date, ``d`` plus the league's waiver days; an add of him
before it is a **claim** (:class:`state.Claim`), decided on the morning of his clear date before
anything else lands (:func:`clear_waivers`): the team with the best priority that still has a claim
open that morning wins its first (in the order it placed them) and goes to the back of the order,
every other claim on that player is lost, and a won claim its roster cannot take fails and the
player goes to the next. A claim's drop and its held-slot moves are made only if it is won, but for
a churn on a claim: its held player leaves the next morning, won or not, as the autopilot drops him
on his own before the claim (which is why the engine offers a churn on a claim only when the held
player is worth nothing net of his return). A claim is charged to the week of the day before it
lands. The executor mirrors the autopilot's claim rules (:func:`queue`). The problem is built as the
live build builds it: each candidate on waivers effective on his clear date and among ``claims``,
and the seat's own claims in flight folded in (``moves.with_pending``).

**FAAB** (PR Fb, a league whose ``waivers`` is ``faab``): the waiting and the claims are as by
priority, but each claim carries a sealed bid from its team's budget, set when it is placed and
clamped to the dollars left that day (:func:`queue`), and the morning decides the claims highest
bid first, a tie by waiver priority, the winner paying exactly its bid; a claim its team can no
longer pay fails; the order rolls only when a win broke a tie (:func:`clear_waivers`). A seat on
the exact or the surrogate tier, and a mirror rival, bids by the live rule (``autopilot.bid_of``
through the door, :func:`live_bid`) on its move's own gain on the judging horizon and the typical
gain of the moves it recommended over the fortnight (:class:`Basis`); the ranking tier holds no
gain in the engine's units and bids $0; a market rival bids by an assumed form
(:func:`rival_bid`), or on the price book of the public leagues' winning bids (PR Fd,
``Setup.rival_bids`` ``book``: ``bids.book_bid``); a static seat never claims.
``EXECUTIONS`` names the model in every run's payload.

**Continuous waivers** (PR Fc, ``Setup.waiver_rule`` ``continuous``, by priority or by FAAB):
every unowned player is on waivers at all times, so every add is a claim, placed today and
decided on the morning its player clears: tomorrow for a player nobody dropped lately, a dropped
player's clear date otherwise. :func:`clear_waivers` decides both in one pass by the league's
waivers, :func:`queue` places every add as a claim under the claim rules, and the problem marks
every candidate among ``claims``. Nothing lands as a free agent and the day's rotation decides
nothing. With the rule not named nothing moves.

**The head-to-head format** (the format PR, ``Setup.h2h``). In a categories league that counts one
win per matchup (the default) the problem says so (``MoveProblem.one_win``, as the live build
passes ``SeasonSettings.one_win``), so every tier that weighs (exact, surrogate, a mirror rival)
values a week as the matchup's win odds (``weekly.matchup_won``) through the engine's own
``Evaluator``, the exact tier executing ``weighted`` too; the plan's floor is then the engine's
own (``stream.floor_of``: ``PLAN_FLOOR_ODDS``), so ``plan_floor_cats`` is read by nobody, and a
seat that bids scales by that floor until ten moves. A league that counts every category, and a
points league, are valued as before. The ranking tier, a market rival and a static seat read no
odds and do not change. :func:`measure_of` names the measure for the record.

**The stash threshold** (PR G, the engine's reader #373). The arm's ``stash_threshold`` is set on
the seat's problem (:func:`stash_of`: None stays None, no test) and read there by the engine
alone: its searches on the exact and the surrogate tier refuse a set whose drop is a returning
player the threshold keeps (``moves.stash_ok`` in ``moves.feasible``). The ranking tier does not
search with the engine and its one swap is not held to it; a mirror rival keeps None
(:func:`rival_knobs`). **The morning a held player comes back**, a seat that plans with the engine
names who leaves and the world checks it: its decision carries, for each held player its plan
brings back, the drop the plan charges (:func:`sends_of`, ``moves.comebacks`` on the seat's own
problem, so the keep rule and the threshold are the seat's), the state keeps the names one night
(``SimState.sends``), and :func:`arrive` takes a named player who is still active when the roster
is over its spots; with no name, or one who is not on the roster, the least valuable active player
leaves, as before. The world reads neither the knob nor the keep rule. The names are made with
what the seat queues that night made (PR E, :func:`named`): the set's moves, with the plan's
steps due for an arm that executes its plan, or a leading plan's steps due under the queue's
rule. What is queued is gathered in one place (:func:`gathered`), which the executor and the
names both read; the names are made with the part of it that can land together
(:func:`distinct`: a plan step that takes the add or the drop of a move of the set is left
out). So a named player is never the drop of a move queued for the same morning. The
day's choice of an activation's drop (``moves.choose_activation``, #360) is not made here: no
problem a seat decides on holds a cleared player.

**The queue's rule** (PR E, an exact arm that executes ``queue``). The live queue does not simply
take the three weeks' set: it also draws the week plans and takes a plan when it beats the set
by the plan floor on the queue's score, the week's gain plus ``three_weight`` times the three
weeks' (in a bracket week on the matchup's odds, the weight 0 and the floor the engine's own).
:func:`draw_queue` hands the engine the day's inputs in the live route's order
(``api.season_moves.week_plans_payload``, read and written again here): the three weeks' set as
``three`` finds it, the week's set, the week's single swaps and the streaming plan, the weight
(:func:`queue_weight`), the guard and the held returns; the plans, the gate, the floor and the
trim are the engine's (``season.plans`` through the door). :func:`queue_rule` makes the decision:
the plan's steps, dated, when a plan leads (:attr:`Decision.plan_leads`), else the set, and
:func:`queue` then places only the steps due today; the seat decides again tomorrow. The season
term is on the three weeks' set only; the plans and the gate are the engine's own score (the
library's functions do not take the term's wrapper: a bracket week's gate reads the matchup's
odds, which it has not), and the season guard, which does not read the term, admits or refuses
every plan all the same; under the arm's guard ``off`` (below) none of them is handed it.

**The guard and the stake** (the guard PR, an arm's two season fields, :data:`SEASON_FIELDS`).
``guard`` is ``block`` (the default: the engine's season guard on every search of the tier, as
live) or ``off`` (no search of the tier is handed an allowed set, :func:`allowed_of`; what holds
a set back is the season term alone). ``stake``, 0 to 1 (0 by default), moves the season term's
weight from the season after the running week to that week as the week's stake grows: the term
is ``season_weight x (this week's part + (1 - stake x L) x the rest)``, the season figure split
at the running week's last day (:func:`later_share`, :class:`StakedFigure`;
:func:`season_figure_of` is the one place every reader of the term takes its figure), ``L`` the
week's stake for the seat from the finished weeks' standings (``sim/stake.py``). Both are the
arm's own seat's (:func:`guarded`): a rival, a mirror too, stays on the block and reads no
stake. With neither named nothing moves.

**The union pool** (PR pool, an arm's fifth field, ``guard_pool``). The exact tier cuts its pool
before the season guard sees anything: the best ``pool`` by single-swap gain. Live has searched
a union since #424 (``season.pool``): that head, then the adds whose best single move the guard
admits. At a ``guard_pool`` above 0 the exact tier's searches take it: the three weeks' set by
``pool.pool_for``, the weighted search by its head and each horizon's admitted list joined
(:func:`exact`, :func:`_weighted_union`), and under the queue's rule the week's set by
``pool.pool_for`` on the week's single swaps (:func:`draw_queue`). The rule is the engine's,
called through the door (``sp``), with the one guard the day's searches share. At 0, the
default, the lines of before run and the rule is not called; so too under the arm's guard
``off``, where there is no guard to make a list, and the field is not read
(:func:`field_reads`). The week plan's set, :func:`scale_of`, the surrogate, the ranking tier
and the rivals do not read the field. A decision says what its union was
(:class:`PoolUnion`), for the counts: under the queue's rule the day's two sets' together.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import median
from typing import Any, NamedTuple, Protocol

from . import bid_policy as bp
from . import bids
from .engine import (
    DEFAULTS,
    LIVE_KNOBS,
    ONE_WIN,
    TYPICAL_DAYS,
    TYPICAL_MIN,
    Week,
    bid_of,
    dl,
    mv,
    pl,
    refused,
    sg,
    sp,
    st,
    typical_gain,
    wk,
)
from .league import fpts, round_pairs, round_weeks
from .shapes import BOOK, CONTINUOUS, DROPPED
from .stake import level as week_stake
from .state import (
    BENCH,
    FAILED,
    LOST,
    WON,
    Claim,
    Resolved,
    Setup,
    SimState,
    Waiting,
    add_totals,
)

#: The execution model every run's payload names (#172, the master's ruling on PR 2's plan).
EXECUTIONS = "free_agents_next_day"
#: A waiver league's (#172, PR Fa): a free agent's add the next morning, a dropped player's after
#: his waiver days by a claim, the claims decided by rolling waiver priority.
EXECUTIONS_PRIORITY = "free_agents_next_day_claims_by_priority"
#: A FAAB league's (#172, PR Fb): as by priority, but each claim carries a sealed bid from its
#: team's budget, and the claims are decided highest bid first, a tie by waiver priority.
EXECUTIONS_FAAB = "free_agents_next_day_claims_by_sealed_bids"
#: Under continuous waivers (#172, PR Fc): every add a claim, decided the next morning or on a
#: dropped player's clear date, by rolling priority or by sealed bids; no free agent.
EXECUTIONS_CONTINUOUS_PRIORITY = "claims_only_by_priority"
EXECUTIONS_CONTINUOUS_FAAB = "claims_only_by_sealed_bids"


def executions_of(waivers: str, rule: str = DROPPED) -> str:
    """The execution model a run's payload names under ``waivers`` (``shapes.WAIVERS``) and the
    waiver ``rule`` (``shapes.WAIVER_RULES``, PR Fc): the name it always had without waivers, a
    name of its own for each kind of waivers, and under continuous waivers for each again."""
    if waivers == "none":
        return EXECUTIONS
    if rule == CONTINUOUS:
        return EXECUTIONS_CONTINUOUS_FAAB if waivers == "faab" else EXECUTIONS_CONTINUOUS_PRIORITY
    return EXECUTIONS_FAAB if waivers == "faab" else EXECUTIONS_PRIORITY


#: A decided move lands this long after it is made: it takes effect then, and is charged to the
#: week of the day it is made, as Yahoo charges a free-agent add (never the week it lands in).
LANDS_AFTER = timedelta(1)
#: The live moves route's figures (``api.season_moves``): the candidates the recommended set is
#: searched among and the least gain a move must add. They, the weeks ahead and the surrogate's
#: days are the defaults of an arm's :class:`Fields` and are read nowhere else.
POOL = 30
MIN_GAIN = 0.01
WEEKS_AHEAD = 4
HORIZONS = ("week", "three")
#: The set the autopilot queues (``season.autopilot.QUEUE_SET``).
QUEUE_SET = "three"
WEIGHTED = "weighted"
#: The live queue's rule (#172, PR E): the three weeks' set, or the week plan that beats it by the
#: plan floor on the queue's score (:func:`queue_rule`). The exact tier's.
QUEUE = "queue"
EXECUTES = (QUEUE_SET, WEIGHTED, QUEUE)
TIERS = ("exact", "surrogate", "ranking")
#: The surrogate's solve days (Monday 0, Thursday 3).
SURROGATE_DAYS = (0, 3)
#: An absence read without a return date is taken to last this long (``moves.SHORT_ABSENCE_DAYS``).
DEFAULT_ABSENCE_DAYS = mv.SHORT_ABSENCE_DAYS
#: An arm's guard (#172, the guard PR): ``block``, the season guard on every search of its tier
#: (live's hard block, the default); ``off``, no block: a set that loses on the rest of the
#: season may be queued, and what holds it back is the season term at the arm's season weight.
BLOCK, OFF = "block", "off"
GUARDS = (BLOCK, OFF)
#: The tiers that search sets under the season guard and hold odds for a season term: the only
#: ones that read an arm's guard or its stake.
GUARDED_TIERS = ("exact", "surrogate")


#: The simulator's own knobs (#172, PR C): the season term's weight, and the weight of a game in
#: the bracket's weeks inside it.
SIM_KNOBS = ("season_weight", "playoff_weight")
#: Every knob an arm names: the ten the live knob file takes, then the simulator's two.
KNOBS = (*LIVE_KNOBS, *SIM_KNOBS)
#: Each knob's default: the engine's own (``progress.DEFAULTS``), then no season term and a
#: bracket game counted once. The fallback of a league without a knob file.
KNOB_DEFAULTS: Mapping[str, Any] = {**DEFAULTS, "season_weight": 0.0, "playoff_weight": 1.0}
#: The live knobs the engine takes None for: those whose own default is None (the blend weight,
#: the stash threshold, the FAAB sizing).
TAKES_NONE = frozenset(k for k in LIVE_KNOBS if DEFAULTS[k] is None)


def knob(knobs: Mapping[str, Any], name: str) -> Any:
    """A knob by name; every one of ``KNOBS`` must be present (None is a value)."""
    if name not in KNOBS:
        raise KeyError(f"{name!r} is not a knob")
    if name not in knobs:
        raise KeyError(f"knob {name!r} missing: an arm names every knob explicitly")
    return knobs[name]


def knob_refused(name: str, value: Any) -> str | None:
    """Why knob ``name`` may not take ``value``; None when it may. A live knob by the engine's
    own check (``progress.refused``: its choices, a number, a whole one for a count, its minimum
    and its maximum), and None only where the engine's default is None (:data:`TAKES_NONE`); the
    simulator's two are numbers, 0 or more. No knob takes a number that is not finite: the
    engine's check compares a number with its bounds, which a NaN passes, and the stash
    threshold, which has no maximum, is read since PR G (a NaN there keeps every returning
    player, and a record cannot hold it)."""
    if name in SIM_KNOBS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{name} {value!r} is not a number"
        if not math.isfinite(value):
            return f"{name} {value!r} is not a finite number"
        if value < 0:
            return f"{name} {value} is below its minimum 0"
        return None
    if value is None:
        return None if name in TAKES_NONE else f"{name} is None: the engine takes a value for it"
    if isinstance(value, float) and not math.isfinite(value):
        return f"{name} {value!r} is not a finite number"
    return refused(name, value)


def check_knobs(knobs: Mapping[str, Any]) -> dict[str, Any]:
    """The twelve knobs as given, in :data:`KNOBS` order: every name present (an arm names every
    knob explicitly; KeyError), no other name and every value allowed (:func:`knob_refused`;
    ValueError). Each error names the knob and the reason."""
    unknown = [k for k in knobs if k not in KNOBS]
    if unknown:
        raise ValueError(f"knob {unknown[0]!r} is not a knob: one of {', '.join(KNOBS)}")
    out = {name: knob(knobs, name) for name in KNOBS}
    for name, value in out.items():
        why = knob_refused(name, value)
        if why is not None:
            raise ValueError(f"knob {name!r} refused: {why}")
    return out


# --------------------------------------------------------------------------- the arm's fields
#: The arm's five fields beside its knobs, in the order the payload names them. The fifth,
#: ``guard_pool`` (#172, PR pool), is written in a payload only above 0.
FIELDS = ("pool", "min_gain", "weeks_ahead", "surrogate_days", "guard_pool")
#: ``guard_pool`` off: the default, and the exact tier's pools as they were before the field.
NO_GUARD_POOL = 0
#: The tiers whose searches take a union pool at a ``guard_pool`` above 0: the exact tier's.
UNION_TIERS = ("exact",)


@dataclass(frozen=True)
class Fields:
    """An arm's settings beside its knobs (#172, PR C), the live route's figures by default:
    ``pool``, the candidates a search ranks and searches among; ``min_gain``, the least gain a
    move must add on the key the arm executes (with the season term, on the combined figure);
    ``weeks_ahead``, the weeks a problem looks ahead, this one included (the ``three`` horizon is
    the ``weeks_ahead - 1`` after it, fewer near the season's end); ``surrogate_days``, the
    weekdays the surrogate solves on (Monday 0); ``guard_pool`` (PR pool), the size of the
    guard's list the exact tier's pools take beside their best ``pool`` (``season.pool``'s
    ``guard_size``), 0 for none: the pools as they were, and the default. Part of a seat's
    ``repr``, so two seats that differ in one never share a decision."""

    pool: int = POOL
    min_gain: float = MIN_GAIN
    weeks_ahead: int = WEEKS_AHEAD
    surrogate_days: tuple[int, ...] = SURROGATE_DAYS
    guard_pool: int = NO_GUARD_POOL

    def payload(self) -> dict[str, Any]:
        """The fields as a record names them: the four an arm always had, and ``guard_pool``
        only above 0, so an arm that leaves it off is recorded as before the field."""
        out: dict[str, Any] = {
            "pool": self.pool,
            "min_gain": self.min_gain,
            "weeks_ahead": self.weeks_ahead,
            "surrogate_days": list(self.surrogate_days),
        }
        if self.guard_pool > 0:
            out["guard_pool"] = self.guard_pool
        return out


DEFAULT_FIELDS = Fields()


def _whole(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def fields_of(spec: Mapping[str, Any]) -> Fields:
    """An arm's fields from its spec, each at its default when the spec names none; a bad value is
    refused by name (ValueError): ``pool`` a whole number, 1 or more; ``min_gain`` a number, 0 or
    more; ``weeks_ahead`` a whole number, 2 or more (the three weeks' set needs a later week);
    ``surrogate_days`` a non-empty set of weekdays 0 to 6; ``guard_pool`` a whole number, 0 or
    more (0 is off)."""
    pool = spec.get("pool", POOL)
    if not _whole(pool) or pool < 1:
        raise ValueError(f"pool {pool!r}: a whole number, 1 or more")
    gain = spec.get("min_gain", MIN_GAIN)
    if (
        isinstance(gain, bool)
        or not isinstance(gain, int | float)
        or not math.isfinite(gain)
        or gain < 0
    ):
        raise ValueError(f"min_gain {gain!r}: a number, 0 or more")
    weeks = spec.get("weeks_ahead", WEEKS_AHEAD)
    if not _whole(weeks) or weeks < 2:
        raise ValueError(
            f"weeks_ahead {weeks!r}: a whole number, 2 or more (the three weeks' set needs a "
            "later week)"
        )
    days = spec.get("surrogate_days", SURROGATE_DAYS)
    if (
        isinstance(days, str | bytes)
        or not isinstance(days, Sequence)
        or not days
        or not all(_whole(d) and 0 <= d <= 6 for d in days)
    ):
        raise ValueError(f"surrogate_days {days!r}: a non-empty set of weekdays, 0 (Monday) to 6")
    listed = spec.get("guard_pool", NO_GUARD_POOL)
    if not _whole(listed) or listed < 0:
        raise ValueError(f"guard_pool {listed!r}: a whole number, 0 or more (0 is off)")
    return Fields(pool, float(gain), weeks, tuple(sorted(set(days))), listed)


@dataclass(frozen=True)
class Built:
    """The move problem for one team on one day, with what the tiers need beside it."""

    problem: mv.MoveProblem
    rule: mv.KeepRule
    scorer: Mapping[str, Any]
    week: Week
    weeks_left: int
    knobs: Mapping[str, Any]
    team: int
    #: The days of the bracket's weeks, whose games the season term counts ``playoff_weight``
    #: times (:func:`bracket_days`).
    bracket: frozenset[date] = frozenset()
    #: Whether a claim carries a bid: a FAAB league (PR Fb). The tiers that bid then give their
    #: decision a :class:`Basis`.
    bids: bool = False
    #: The seat's guard, its stake and the week's stake ``L`` for it (the guard PR,
    #: :func:`guarded`): the block, no stake and no ``L`` unless the arm's seat says otherwise.
    #: E reads ``guard`` through :func:`allowed_of`; every reader of the season term reads
    #: ``stake`` and ``level`` through :func:`later_share` (:func:`season_figure_of`).
    guard: str = BLOCK
    stake: float = 0.0
    level: float = 0.0


#: How a decision's claims bid in a FAAB league (#172, PR Fb): by the live rule
#: (``autopilot.bid_of``: a seat on the exact or the surrogate tier, a mirror rival), or by the
#: market's assumed rule (:func:`rival_bid`). A decision without a basis bids $0.
LIVE, MARKET = "live", "market"
#: Yahoo's mark of a player on waivers: the availability ``bid_of`` is told for a claim.
WAIVER_MARK = "W"


@dataclass(frozen=True)
class Basis:
    """What a decision's claims bid on in a FAAB league (#172, PR Fb). ``rule`` is :data:`LIVE`
    or :data:`MARKET`. ``gains`` is each move's gain the bid scales on, in the order of the
    decision's moves: for the live rule the move's own gain on the judging horizon, the set's
    value less the set without it (the live queue's ``gain``, the logged ``marginal`` on
    ``three``); for the market the move's gain on its view. ``plan`` is each of the plan's steps'
    gain, in the order of its steps: under the queue's rule its score, as live bids
    (:func:`step_bids`, PR E); for a streaming plan beside the set its week increment
    (:func:`basis_of`).
    ``sizing`` is the seat's ``faab_sizing`` and ``floor`` its plan floor, the typical gain until
    ten moves (live); ``noise`` the market's draw by move, for each of its moves that is a claim
    (an empty tuple when none is).

    ``bid`` is the arm's bid policy when it names one (PR F2, :func:`with_bid`; None bids by the
    live rule itself), with ``week`` and ``season`` each move's gain on the other horizons the
    policy weighs, in the order of the decision's moves: its own gain to the set on the week, and
    the season term's figure for it (none counted 0); each empty at a weight of 0."""

    rule: str
    gains: tuple[float, ...]
    plan: tuple[float, ...] = ()
    sizing: float | None = None
    floor: float = 0.0
    noise: tuple[float, ...] = ()
    bid: bp.BidPolicy | None = None
    week: tuple[float, ...] = ()
    season: tuple[float, ...] = ()


@dataclass(frozen=True)
class PoolUnion:
    """What the exact tier's union pool was on one day (#172, PR pool), kept for the counts and
    read by no decision. ``admitted``: the adds the guard's list brought that the head did not
    hold (``season.pool.Pool.admitted``). ``took``: the ones of those the decided set adds, in
    the set's order (``taken``: how many); the day's cap and the week's adds may still cut
    them, so the count of the days one was taken is read on the set's moves the seat then
    queued or claimed (``counts.Tally.searched``). ``refused``: how many of the head's adds
    have a best single move that gains more than ``min_gain`` on a horizon the pool was ranked
    on and that the season guard refuses. Under the queue's rule (PR E) a day has two sets,
    each searched among a union of its own, and the record is the day's (:func:`_day_union`)."""

    admitted: int
    took: tuple[int, ...]
    refused: int

    @property
    def taken(self) -> int:
        return len(self.took)


@dataclass(frozen=True)
class Decision:
    """What a tier decided for one team on one day."""

    moves: tuple[mv.Move, ...] = ()
    #: The held-slot moves the set needs (player, slot).
    held: tuple[tuple[int, str], ...] = ()
    #: The week's streaming plan's steps, recorded; executed only when the arm says so.
    plan: tuple[mv.Move, ...] = ()
    solves: int = 0
    source: str = "none"
    #: What its claims bid on in a FAAB league (PR Fb); None elsewhere, and for a tier that
    #: holds no gain in the engine's units (ranking), whose claims bid $0.
    basis: Basis | None = None
    #: Whom each of the seat's held players sends when he comes back (PR G, :func:`sends_of`):
    #: (the held player, the drop the engine's plan charges him), by player, with what the seat
    #: queues tonight made (:func:`named`, PR E): the set's moves, or the steps due of a plan
    #: that leads. Only a seat that plans with the engine names any (the exact and the surrogate
    #: tiers, a mirror rival).
    sends: tuple[tuple[int, int], ...] = ()
    #: The seat's players the engine read as returning on the day (PR G, :func:`returning_of`),
    #: for the count of those it then drops; a tier's decision made by :func:`decide` has it.
    returning: frozenset[int] = frozenset()
    #: Whether its set is one the season guard would have refused (the guard PR): only a seat
    #: whose guard is ``off`` decides one (:func:`mark_past_guard`). A count, read by no decision.
    past_guard: bool = False
    #: Under the queue's rule (PR E): ``plan`` is the week plan the queue took instead of the
    #: set, its steps dated, and ``held`` the plan's. The executor then queues the plan's steps
    #: due today and none of ``moves``, whatever the arm's ``execute_plan``; ``moves`` stays the
    #: three weeks' set, the day's recommended moves (the record's, and the fortnight's typical
    #: gain's, as live's). False everywhere else.
    plan_leads: bool = False
    #: ``sends`` for an arm that executes its plan beside the set (PR E, :func:`named`): the
    #: names with the set's moves and the plan's steps due tonight that can land beside them
    #: (:func:`distinct`) made. None where no plan stands beside the set (none drawn, or the
    #: plan leads and ``sends`` is its own). The executor keeps the one that matches what it
    #: queues (:func:`queue`).
    plan_sends: tuple[tuple[int, int], ...] | None = None
    #: The day's union pool (PR pool): only on the exact tier at a ``guard_pool`` above 0, None
    #: everywhere else. A count, read by no decision.
    union: PoolUnion | None = None


NONE = Decision()


def returning_of(problem: mv.MoveProblem) -> frozenset[int]:
    """The seat's players, active and held, the engine reads as returning on the problem's day
    (#172, PR G): ``moves.returning_net`` not None, a player out now who is back this season and
    worth something then, the players the stash threshold weighs. The same at any threshold."""
    mine = (*problem.roster, *problem.held)
    return frozenset(k for k, _ in mine if mv.returning_net(problem, k) is not None)


def sends_of(problem: mv.MoveProblem, moves: Sequence[mv.Move] = ()) -> tuple[tuple[int, int], ...]:
    """Whom each of the seat's held players sends when he comes back (#172, PR G), as the
    engine's plan charges it on the seat's own problem: for each held player ``moves.comebacks``
    brings back inside a horizon with ``moves`` made (the three weeks' first, the horizon the
    queue's set is judged on, then the week's), the player it drops for him then. So the keep
    rule (never a kept player while another can go) and the stash threshold (a returning player
    it keeps goes only when no one else can, ``moves.guarded_pool``) are the seat's own, and
    nothing of either is written here. A held player the plan charges nobody for (the set leaves
    him an active spot, or he is out past the horizons) is not named. The engine dates a return
    by its own reading (an ``O`` is back next Monday, or on his return date when later); the
    morning he does come back is the world's (:func:`arrive`), which takes the drop named here
    whatever day the plan gave it.

    The three weeks' pass names every held player who is back inside the horizons while there
    is a later week. The week's pass adds to it in the season's last week alone, where there is
    none, and only a held player the engine reads as back inside the week (a ``GTD`` in an
    ``IL+`` slot): an ``O`` is out for the rest of the week to the engine, so in the last week
    its plan charges nobody for him and he is not named (the README's limits). ``moves`` is
    what the seat means to queue tonight that can land together (:func:`named`: the set's moves
    and the plan's steps due that go with them or instead of them, each add and each drop taken
    once, :func:`distinct`), not what the queue then keeps of it within the day's cap, the
    week's adds and the claim rules. A player those moves drop is never charged; one of their
    adds can be (the README's limits)."""
    held = {k for k, _ in problem.held}
    if not held:
        return ()
    out: dict[int, int] = {}
    for key in (QUEUE_SET, "week"):
        for c in mv.comebacks(problem, key, moves):
            if c.player in held:
                out.setdefault(c.player, c.drop)
    return tuple(sorted(out.items()))


def gathered(
    decision: Decision, execute_plan: bool, due: Callable[[int], date]
) -> tuple[list[mv.Move], list[tuple[mv.Move, int]]]:
    """What a seat means to queue tonight of ``decision`` (#172, PR E), before the day's cap,
    the week's adds and the claim rules cut it: the set's moves in order, none when a plan leads
    (the queue's rule queues the plan instead of the set); and the plan's steps due, each with
    its place in the plan, when the arm executes its plan (``execute_plan``) or the plan leads:
    a step dated at or before ``due`` of its add, the latest day a step of that add may be dated
    to be queued today (:func:`due_by`). The one place the queue's moves are gathered: the
    executor queues from it (:func:`queue`), and the names of who leaves when a held player
    comes back are made with it (:func:`named`), so both read one list.

    The list is not always one that can land whole. A streaming plan beside the set is drawn
    against the week's set, so a step due can take the add or the drop of a move of the three
    weeks' set. The executor queues one move an add and skips the step, and a second move of
    one drop finds its drop gone at the landing; the names are made with the part that can
    land together (:func:`distinct`)."""
    moves = [] if decision.plan_leads else list(decision.moves)
    steps: list[tuple[mv.Move, int]] = []
    if execute_plan or decision.plan_leads:
        steps = [
            (m, j) for j, m in enumerate(decision.plan) if m.day is None or m.day <= due(m.add)
        ]
    return moves, steps


def distinct(listed: Iterable[mv.Move]) -> list[mv.Move]:
    """The moves of ``listed`` that can land together (#172, PR E): each add and each drop
    taken once, by the first move of the list that takes it; a later move that takes either
    again is left out. What :func:`named` makes of the list gathered (:func:`gathered`) before
    the engine charges anyone on it: the engine's plan counts every add of the list as arriving
    and every drop as leaving once (``moves.comebacks``), and ``moves.feasible`` passes no set
    with one add or one drop twice. It is the executor's own reading of the same list, in the
    executor's order, where every add is a free agent's: it queues one move an add (the later
    one is skipped, :func:`queue`), and of two moves of one drop the second to land finds its
    drop gone (:func:`land`). So a move left out for its add takes nothing, and one left out
    for its drop still holds its add: it is queued, and a later move of that add is skipped all
    the same. Its add never arrives, though, so a later move that drops him finds nobody at the
    landing and is left out too, and so on down a chain (the lead's review of PR E; built in PR
    F2). A test holds the two readings together, list by list
    (``tests/sim/test_sim_queue.py``). Nothing is taken out of the queue here: the executor
    queues from the whole list, as it did before the names were made with it. In a waiver
    league a claim rule can cut a move of the list first (README, limits, item 7)."""
    adds: set[int] = set()
    drops: set[int] = set()
    gone: set[int] = set()
    out: list[mv.Move] = []
    for m in listed:
        if m.add in adds:
            continue  # the executor queues one move an add
        adds.add(m.add)
        if m.drop is not None and (m.drop in drops or m.drop in gone):
            # Queued, and gone at the landing: an earlier move took its drop, or its drop is
            # the add of a move that is itself gone. Either way its own add never arrives.
            gone.add(m.add)
            continue
        if m.drop is not None:
            drops.add(m.drop)
        out.append(m)
    return out


def due_on(problem: mv.MoveProblem) -> Callable[[int], date]:
    """:func:`due_by` as the seat's problem holds it: each candidate's effective day
    (``MoveProblem.effective``, which :func:`problem_of` sets by the same reading of the state
    the executor then queues on: tomorrow, or his clear date when he is on waivers and it is
    later). What :func:`named` hands :func:`gathered`, where the executor hands it the state's."""
    tomorrow = problem.first_day + LANDS_AFTER
    return lambda add: problem.effective.get(add, tomorrow)


def named(problem: mv.MoveProblem, decision: Decision) -> Decision:
    """``decision`` with the names of who leaves when one of the seat's held players comes back
    (PR G, :func:`sends_of`), made with what the seat queues tonight made (PR E, the refit of
    PR G's names): the one rule for every seat that plans with the engine, written here and
    read off :func:`gathered`, the list the executor queues from.

    - ``sends``: with the set's moves made, what an arm that does not execute a plan beside its
      set queues; or, under the queue's rule when a plan leads, with that plan's steps due made
      and none of the set's, since the plan is queued instead of the set.
    - ``plan_sends``: for an arm that executes its plan beside the set, with the set's moves
      and the plan's steps due made. None where no plan stands beside the set.

    Of the list gathered, the part that can land together is made (:func:`distinct`): a step
    that takes the add or the drop of an earlier move of the list is left out, since the
    executor does not queue a second move of one add and a second move of one drop finds its
    drop gone. A step dated later is queued on a later day and named with then. So a named
    player is never the drop of a move the seat queues for the same morning (the engine's
    charge leaves a dropped player out, and a step left out for its drop drops a player an
    earlier move already does). He can be one of those moves' own adds, who has not arrived
    when the held player comes back: the morning then falls to the rule before
    (:func:`_activate`), and no rule of the seat's own is written for it (the README's
    limits)."""
    if not problem.held:
        return decision
    due = due_on(problem)

    def of(execute_plan: bool) -> tuple[tuple[int, int], ...]:
        moves, steps = gathered(decision, execute_plan, due)
        return sends_of(problem, distinct([*moves, *(m for m, _ in steps)]))

    beside = bool(decision.plan) and not decision.plan_leads
    return replace(decision, sends=of(False), plan_sends=of(True) if beside else None)


def gains_of(ev: mv.Valued, key: str, moves: Sequence[mv.Move]) -> tuple[float, ...]:
    """Each move's own gain to ``moves`` on horizon ``key``: the set's value less the set
    without it (``moves.PricedMove.marginal``, which the live queue bids on)."""
    whole = ev.value(key, moves)
    return tuple(whole - ev.value(key, [x for x in moves if x != m]) for m in moves)


def basis_of(
    built: Built,
    ev: mv.Evaluator,
    moves: Sequence[mv.Move],
    planned: Any = None,
) -> Basis | None:
    """The live rule's basis for a decision of ``moves`` (and the week plan ``planned``, a
    ``stream.Plan``, when the decision carries one) in a FAAB league; None elsewhere. A move of
    the set bids on its own gain on the judging horizon (:func:`gains_of`, the live queue's
    ``marginal``); a plan step on its week increment (``stream.step_gains``), where live bids on
    its score, the week increment plus the queue's weight times its three weeks' increment
    (``plans.step_score``): a streaming plan beside the set is the simulator's own arm, not the
    queue's, and keeps the week increment; the queue's rule bids on the score
    (:func:`step_bids`, PR E). The gains
    are the engine's own, on its plain evaluator: the season term is the simulator's and live
    bids without it. The typical gain until ten moves is the problem's plan floor as the engine
    reads it (``stream.floor_of``): the knob, or in a one-win league the engine's own floor in
    the matchup's odds (the format PR; live has no rule here, its one-win league never queues)."""
    if not built.bids:
        return None
    steps = () if planned is None else tuple(g["week"] for g in st.step_gains(ev, planned))
    return Basis(
        LIVE,
        gains_of(ev, QUEUE_SET, moves),
        steps,
        knob(built.knobs, "faab_sizing"),
        float(st.floor_of(built.problem)),
    )


#: The market rivals' bid (#172, PR Fb): an assumption, not a fact, and nothing fitted (no league
#: is on the box). Its parameters are here alone, so a fit replaces them and not the world:
#: ``noise``, the range of the uniform draw a bid is multiplied by (its mean 1), and the fortnight
#: and the count of moves the typical gain needs, as the seat's (``autopilot.TYPICAL_DAYS``,
#: ``TYPICAL_MIN``).
@dataclass(frozen=True)
class RivalBids:
    noise: tuple[float, float] = (0.5, 1.5)
    days: int = TYPICAL_DAYS
    least: int = TYPICAL_MIN


RIVAL_BIDS = RivalBids()


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def market_noise(g: Any, params: RivalBids = RIVAL_BIDS) -> float:
    """A market rival's bid noise, from the path's draw for its team and day."""
    lo, hi = params.noise
    return lo + (hi - lo) * float(g.random())


def market_typical(
    recent: Sequence[tuple[date, float]], day: date, gain: float, params: RivalBids = RIVAL_BIDS
) -> float:
    """The typical gain a market rival's bid scales by: the median gain on the view of every
    market rival's moves of the fortnight before ``day`` (pooled: one rival moves too seldom to
    have ten), and the move's own ``gain`` until ``params.least`` such moves exist."""
    since = day - timedelta(params.days)
    gains = [x for d, x in recent if since < d < day]
    return float(median(gains)) if len(gains) >= params.least else gain


def rival_bid(gain: float, typical: float, dollars: int, scale: float, noise: float) -> int:
    """A market rival's bid: ``round(scale x gain / typical x noise)`` whole dollars (half up,
    as ``bid_of`` rounds), at least 0 and at most its ``dollars`` left."""
    ratio = gain / typical if typical > 0 else 1.0
    return max(0, min(int(dollars), _half_up(scale * ratio * noise)))


def live_bid(
    gain: float, gains: Sequence[float], floor: float, dollars: int, sizing: float | None
) -> int:
    """A seat's bid by the live rule: ``autopilot.bid_of`` on the move's ``gain``, the typical
    gain of the seat's fortnight (``autopilot.typical_gain`` of ``gains``, the plan ``floor``
    until ten), its ``dollars`` left, no breakout flag (flags are not modelled), its FAAB
    ``sizing`` and a claim's mark."""
    typical = typical_gain(list(gains), floor)
    return bid_of(gain, typical, dollars, None, sizing, WAIVER_MARK).amount


# --------------------------------------------------------------------------- the bid policy (PR F2)
#: Everything of the seat's bid policy that is not the pure family (``sim/bid_policy.py``) is in
#: this block and in :func:`queue`'s ``bid``: what a decision carries for it (:func:`with_bid`),
#: the seat's fortnight on the horizons it weighs (:func:`fortnight_by`), the calendar a pace
#: reads (:func:`bid_when`) and what a manager sees for one claim (:func:`bid_seen`).
def with_bid(built: Built, decision: Decision, bid: bp.BidPolicy | None) -> Decision:
    """``decision`` as an arm that names a ``bid`` block bids on it (#172, PR F2): its live
    basis names the policy and carries each move's gain on the other horizons the policy weighs,
    each only at a weight above 0: on the week the move's own gain to the set
    (:func:`gains_of`, on the engine's plain evaluator, as the basis reads the three weeks), on
    the season the season term's figure for it (:meth:`SeasonFigure.move` at the arm's
    ``playoff_weight``; none counts 0). A plan's steps carry nothing more: a step keeps today's
    value. The decision itself when the arm names no ``bid``, and for one without a live basis
    (no FAAB league, the ranking tier): the moves are never changed, only what their claims bid
    on."""
    basis = decision.basis
    if bid is None or basis is None or basis.rule != LIVE:
        return decision
    week: tuple[float, ...] = ()
    season: tuple[float, ...] = ()
    if decision.moves and bid.week > 0:
        week = gains_of(mv.Evaluator(built.problem), bp.WEEK, decision.moves)
    if decision.moves and bid.season > 0:
        figure = SeasonFigure(built, knob(built.knobs, "playoff_weight"))
        season = tuple(figure.move(m) or 0.0 for m in decision.moves)
    return replace(decision, basis=replace(basis, bid=bid, week=week, season=season))


def fortnight_by(
    state: SimState, team: int, basis: Basis
) -> tuple[Mapping[str, Mapping[int, tuple[tuple[date, float], ...]]], dict[str, float | None]]:
    """``team``'s moves on the other horizons its bid policy weighs (the week, the season; each
    only at a weight above 0), today's recommended moves counted, as ``SimState.recent_by``
    keeps them; and its typical gain on each (the lead's working default, 2026-11-19):

    - the fortnight's median by the engine's rule (``autopilot.typical_gain``) when the
      fortnight holds ``TYPICAL_MIN`` moves or more, as the live rule's;
    - else the median, by the same rule, of the seat's last ``TYPICAL_MIN`` moves on that
      horizon whatever their age, once it has made that many: a seat that decides twice a week
      seldom holds ten moves in a fortnight, and would read no size at all;
    - else None: before its tenth move a move that gains counts as typical
      (``bid_policy._ratio``).

    So the state keeps the fortnight's moves and, where they are fewer, the last
    ``TYPICAL_MIN``. With no ``bid`` named, or neither weight above 0, the state's own and no
    typical: the three weeks' fortnight (``SimState.recent``) is never changed."""
    rule = basis.bid
    kept = state.recent_by
    typicals: dict[str, float | None] = {}
    if rule is None:
        return kept, typicals
    since = state.day - timedelta(TYPICAL_DAYS)
    out = dict(kept)
    for key, weight, today in (
        (bp.WEEK, rule.week, basis.week),
        (bp.SEASON, rule.season, basis.season),
    ):
        if not weight > 0:
            continue
        every = (*kept.get(key, {}).get(team, ()), *((state.day, x) for x in today))
        last = len(every) - TYPICAL_MIN
        mine = tuple(e for i, e in enumerate(every) if e[0] > since or i >= last)
        out[key] = {**kept.get(key, {}), team: mine}
        fortnight = [x for d, x in mine if d > since]
        gains = fortnight if len(fortnight) >= TYPICAL_MIN else [x for _, x in mine]
        typicals[key] = typical_gain(gains, 0.0)[0] if len(gains) >= TYPICAL_MIN else None
    return out, typicals


def bid_when(setup: Setup, day: date) -> bp.When:
    """The calendar a pace reads for a claim decided on the morning of ``day``: the season's
    first simulated day, the first day of the bracket's first week (the day after the season's
    last where no bracket is read: the whole season is then regular) and the last morning a
    claim can be decided, the season's last day."""
    last = setup.season_end
    weeks = set(setup.spec.playoff_weeks) if setup.spec is not None else set()
    starts = [w.start for w in setup.calendar.weeks if w.number in weeks]
    first = max(setup.start, min(w.start for w in setup.calendar.weeks))
    return bp.When(day, first, min(starts) if starts else last + timedelta(1), last)


def bid_seen(
    setup: Setup,
    state: SimState,
    team: int,
    basis: Basis,
    typical: float,
    typicals: Mapping[str, float | None],
    i: int | None,
    gain: float,
    clears: date,
) -> bp.Seen:
    """What ``team``'s manager sees for the claim of its decision's move ``i``, or of a plan's
    step when ``i`` is None, decided on ``clears`` (``bid_policy.Seen``, the walls). The
    executor says which it is (:func:`queue`): under the queue's rule (PR E) a leading plan's
    steps are queued and none of the set's moves, so a claim's place in the queue is not its
    place among the decision's moves. Seen:
    the move's ``gain`` and the seat's ``typical`` on the three weeks, its own dollars and
    sizing, the league's budget, and only what its policy reads besides: the gains and typicals
    on the week and the season, every other team's dollars left (the rival cap), the other
    teams' winning bids of the season so far (the shade; never its own wins, never a bid that
    lost and never one still sealed) and the calendar (the pace)."""
    rule = basis.bid or bp.DEFAULT
    step = i is None
    more: dict[str, Any] = {}
    if i is not None and rule.week > 0:
        more |= {"week": basis.week[i], "typical_week": typicals.get(bp.WEEK)}
    if i is not None and rule.season > 0:
        more |= {"season": basis.season[i], "typical_season": typicals.get(bp.SEASON)}
    if rule.rival_cap:
        more["others"] = tuple(int(d) for t, d in sorted(state.dollars.items()) if t != team)
    if rule.shade is not None:
        more["wins"] = tuple(b for _, t, b in state.won_bids if t != team)
    if rule.pace is not None:
        more["when"] = bid_when(setup, clears)
    return bp.Seen(
        gain,
        typical,
        int(state.dollars.get(team, 0)),
        basis.sizing,
        step,
        budget=setup.budget,
        **more,
    )


# --------------------------------------------------------------------------- the problem
def members_of(
    setup: Setup,
    keys: Sequence[int],
    status: Mapping[int, str | None],
) -> list[mv.Member]:
    """``(key, Player)`` for ``keys`` with the statuses the policy sees."""
    return [(k, setup.players[k].player(status.get(k))) for k in keys if k in setup.players]


def stash_of(knobs: Mapping[str, Any]) -> float | None:
    """The stash threshold a seat's problem carries (#172, PR G): the arm's knob as a number,
    None when it names none. The engine reads it on the problem alone (``moves.stash_ok`` in
    ``moves.feasible``, ``moves.guarded_pool`` in ``moves.comebacks``); nothing else here does."""
    value = knob(knobs, "stash_threshold")
    return None if value is None else float(value)


def rival_knobs(knobs: Mapping[str, Any]) -> dict[str, Any]:
    """An arm's knobs as its mirror rivals hold them (PR G): the arm's whole, but for the stash
    threshold, which is the arm's own seat's and stays None for every rival. A knob the arm does
    not name stays missing, and is refused where the knobs are checked."""
    if knobs.get("stash_threshold") is None:
        return dict(knobs)
    return {**knobs, "stash_threshold": None}


def bracket_days(setup: Setup) -> frozenset[date]:
    """The days of the bracket's weeks (``spec.playoff_weeks`` on the calendar); none when the
    bracket is not read."""
    if setup.spec is None:
        return frozenset()
    weeks = set(setup.spec.playoff_weeks)
    return frozenset(d for w in setup.calendar.weeks if w.number in weeks for d in w.days())


def opponent_of(setup: Setup, state: SimState, me: int, week: int) -> int | None:
    """Whom ``me`` plays in ``week`` (#172, PR bracket): the other team of its pair in the
    setup's pairings, which hold the regular weeks; where they have no entry for the week, of
    its pair among the round's pairs the state holds for it (``SimState.seeded``, the bracket's
    round seeded that morning). None for a team in no pair: a week off, a team out of the
    field, on a bye or knocked out, and a bracket week on a state that holds no pairs."""
    pairs = setup.pairings[week] if week in setup.pairings else state.seeded.get(week, ())
    return next((b if a == me else a for a, b in pairs if me in (a, b)), None)


class WeekView(NamedTuple):
    """What a team's problem reads of this week beyond ``SimState.key()`` (:func:`week_view`):
    its opponent, and each side's totals so far this week as the week's span takes them (a
    points league's as its score). ``so_far_theirs`` is None with no opponent. It is hashable:
    the runner's decision cache keys a strategy that reads the week on it."""

    opponent: int | None
    so_far: tuple[tuple[str, float], ...]
    so_far_theirs: tuple[tuple[str, float], ...] | None


def week_view(setup: Setup, state: SimState, me: int, week: int) -> WeekView:
    """``me``'s view of ``week`` on ``state``: whom it plays (:func:`opponent_of`) and both
    sides' totals so far. The one source of the week's opponent and totals: :func:`problem_of`
    builds the week's span from it, and the runner's decision cache keys on it for a strategy
    that reads the week (:func:`reads_week`), so a decision is never shared across two views
    the problem tells apart, a round's pairs included."""
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None

    def so_far_of(team: int) -> tuple[tuple[str, float], ...]:
        totals = dict(state.totals.get(week, {}).get(team, {}))
        return tuple(({wk.FPTS: fpts(totals, points)} if points else totals).items())

    other = opponent_of(setup, state, me, week)
    return WeekView(other, so_far_of(me), so_far_of(other) if other is not None else None)


def reads_week(
    tier: str,
    executes: str = QUEUE_SET,
    with_plan: bool = True,
    bid: bp.BidPolicy | None = None,
) -> bool:
    """Whether a seat's decision reads the value of this week, so its opponent and the week's
    totals so far (:func:`week_view`):

    - the exact tier when it executes the weighted set or the queue's rule (PR E:
      :func:`draw_queue` searches the week's set and the week's plans), or draws the week's plan
      (:func:`exact`);
    - a tier that bids (the exact and the surrogate; a mirror rival is the surrogate) on an arm
      whose ``bid`` weighs the week (PR F2): its decision carries each move's gain on the week
      for its claims to be sized on (:func:`with_bid`), whatever set it searched.

    The surrogate, the ranking and the exact tier's recommended set on the three weeks search
    no week, and a ``bid`` that weighs the season reads the schedule and no matchup
    (:class:`SeasonFigure`): their decisions are the same whatever the view (held by behaviour,
    ``tests/sim/test_sim_bid_key.py``; in a round of the bracket,
    ``tests/sim/test_sim_bracket_run.py``). A seat that says it reads the week where no claim is
    ever sized (a league without FAAB) shares a little less and decides the same."""
    searches = tier == "exact" and (executes in (WEIGHTED, QUEUE) or with_plan)
    # The ranking tier holds no live basis, so its claims are sized on nothing (``with_bid``).
    bids = tier in ("exact", "surrogate") and bid is not None and bid.week > 0
    return searches or bids


def problem_of(
    setup: Setup,
    state: SimState,
    me: int,
    knobs: Mapping[str, Any],
    beliefs: Mapping[int, Mapping[str, float]],
    status: Mapping[int, str | None],
    returns: Mapping[int, date],
    weeks_ahead: int = WEEKS_AHEAD,
) -> Built | None:
    """The move problem for ``me`` on ``state.day``; None with no week left. Mirrors
    ``api.season_moves.build`` from in-memory inputs. This week is read through
    :func:`week_view`: against the pairing's opponent, or in a round of the bracket the round's
    (PR bracket), projected on the same beliefs from its active roster with both sides' totals
    so far, and against nobody for a team in no pair. Every later week is against the whole field,
    a bracket week too, as the live route builds them."""
    knobs = check_knobs(knobs)
    day = state.day
    weeks = setup.calendar.ahead(day, weeks_ahead)
    if not weeks:
        return None
    this = weeks[0]
    days0 = this.days(day)
    if not days0:
        return None
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    cats = tuple(setup.cats)
    slots = setup.starting_slots()
    value = wk.per_game_values(beliefs, cats, points)
    roster_of = {t: state.active(t) for t in setup.teams}

    # A points league's weeks are read as the live build reads them (``api.season_moves.build``):
    # each team's projected week carries its fantasy points (``points``), and the week so far is
    # each side's score, the sum the standings count (``league.fpts``), as the matchup page gives
    # it (``api.season_week.so_far``). Before PR D4c no points league reached this, and the
    # opponents' weeks carried no points: every week looked won and no move gained (#172).
    def project(team: int, days: Sequence[date], this_week: bool) -> wk.TeamWeek:
        members = members_of(setup, roster_of.get(team, ()), status)
        return wk.project_week(
            members, beliefs, days, setup.schedule, slots, value, this_week, points=points
        )

    view = week_view(setup, state, me, this.number)
    other = view.opponent
    week_span = mv.WeekSpan(
        tuple(days0),
        True,
        (project(other, days0, True),) if other is not None else (),
        dict(view.so_far),
        (dict(view.so_far_theirs),) if view.so_far_theirs is not None else (),
        None,
    )
    field_teams = [t for t in setup.teams if t != me]
    later = tuple(
        mv.WeekSpan(
            tuple(w.days()),
            False,
            tuple(project(t, w.days(), False) for t in field_teams),
            games=None,
        )
        for w in weeks[1:]
    )
    roster = tuple(members_of(setup, roster_of[me], status))
    held_pairs = state.held(me)
    held = tuple(members_of(setup, [k for k, _ in held_pairs], status))
    held_slots = {k: slot for k, slot in held_pairs}
    slot_count = Counter(setup.roster_slots)
    taken = Counter(slot for k, slot in held_pairs if not mv.is_cleared(status.get(k), slot))
    held_open = {k: slot_count.get(k, 0) - taken.get(k, 0) for k in mv.HELD}
    # Free agents land the next day: a candidate's move takes effect tomorrow, or on his clear
    # date when he is on waivers and it is later, as the live build sets ``effective`` from the
    # wire's clear dates (PR Fa). The candidates are the whole wire, waivers included, and
    # those on waivers are ``claims`` (#221: a churn on one is offered only when the held player
    # is worth nothing net of his return), as the live build marks the wire's "W". Under
    # continuous waivers (PR Fc) every candidate is a claim, as every entry of the live queue is
    # a waiver entry in such a league; one nobody dropped lately clears tomorrow.
    effective_day = day + LANDS_AFTER
    candidates = tuple(members_of(setup, sorted(k for k in state.pool if k in beliefs), status))
    effective = {
        k: max(effective_day, state.waivers[k].clears) if k in state.waivers else effective_day
        for k, _ in candidates
    }
    claims = frozenset(k for k, _ in candidates if setup.continuous or k in state.waivers)
    limit = setup.max_weekly_adds
    used = int(state.adds_used.get(me, 0))
    # The engine charges a move to the week its day falls in, and a move's day here is the day
    # it lands, one after it is made. So each week's window is its days shifted by the lag: a
    # move made on Sunday lands Monday and spends the ending week's adds, as on Yahoo. This
    # week's window opens today, so a plan step dated today is charged here too.
    limits = tuple(
        mv.AddLimit(
            day if i == 0 else w.start + LANDS_AFTER,
            w.end + LANDS_AFTER,
            None if limit is None else (max(0, limit - used) if i == 0 else limit),
        )
        for i, w in enumerate(weeks)
    )
    spots = setup.spots()
    pool_n = max(1, len(setup.teams) * spots)
    # One of ``build``'s fields stays at its default here, on purpose: ``cantcut`` (#222) is
    # Yahoo's can't-cut list as read off an add page, and a simulated world has none.
    problem = mv.MoveProblem(
        roster=roster,
        held=held,
        spots=spots,
        held_open={k: n for k, n in held_open.items() if n > 0},
        candidates=candidates,
        effective=effective,
        first_day=day,
        rates=beliefs,
        schedule=setup.schedule,
        slots=slots,
        value=value,
        cats=cats,
        points=points,
        no_games=frozenset(),
        horizons={"week": (week_span,), "three": later},
        limits=limits,
        returns={k: d for k, d in returns.items() if k in dict(roster) or k in held_slots},
        held_slots=held_slots,
        claims=claims,
        # A one-win league's moves rank on the matchup's odds (#397), as the live build passes
        # ``SeasonSettings.one_win`` (the format PR); a points league and one that counts every
        # category pass nothing.
        one_win=setup.one_win,
    )
    season_value = wk.per_game_values(beliefs, cats, points, pool_n)
    dead = wk.line_value(beliefs, cats, points, pool_n)({})
    average = 0.0
    if points:
        best = sorted(season_value.values(), reverse=True)[:pool_n]
        average = sum(best) / len(best) if best else 0.0
    problem = replace(
        problem,
        season_value=season_value,
        dead=dead,
        average=average,
        season_end=setup.season_end,
        floor=float(knob(knobs, "protection_floor")),
        plan_floor=float(knob(knobs, "plan_floor_points" if points else "plan_floor_cats")),
        daily_cap=int(knob(knobs, "daily_cap")),
        # The stash threshold (PR G), as the live build passes the knob file's
        # (``api.season_moves.stash_threshold``): None stays None, no test, as before the reader.
        stash_threshold=stash_of(knobs),
    )
    # My claims in flight are made in the problem before it is solved, as the live build folds
    # the queue's open claims (``api.season_moves.fold``, #360, #364): the solve is on the roster
    # they will leave, a claimed player is out of the candidates, and a claim's add is kept.
    problem = mv.with_pending(problem, pending_of(setup, state, me, status))
    rule = mv.keep_rule(problem)
    problem = replace(problem, kept=rule.kept | problem.pending)
    scorer = wk.scorer_of(beliefs, cats, points, pool_n)
    weeks_left = sum(1 for w in setup.calendar.weeks if w.number > this.number)
    return Built(
        problem, rule, scorer, this, weeks_left, knobs, me, bracket_days(setup), setup.bidding
    )


def pending_of(
    setup: Setup, state: SimState, me: int, status: Mapping[int, str | None]
) -> tuple[mv.Pending, ...]:
    """My claims placed and not yet decided (#172, PR Fa), as the live build reads the queue's
    open claims (``api.season_moves.pending_claims``, #360): each add with his clear date and his
    drop, in the order placed. A claim whose plain drop is no longer on my roster is left out, as
    there (Yahoo voids it; here it fails on its clear morning). A churn's claim is an open-spot
    claim once its held player has gone on his own (the autopilot's ``CHURN``): no drop."""
    mine = {k for k, _ in state.rosters.get(me, ())}
    out = []
    for c in state.claims.get(me, ()):
        add, drop = c.move.add, c.move.drop
        if add not in setup.players:
            continue
        if c.churn:
            drop = None if drop not in mine else drop
        elif drop is not None and drop not in mine:
            continue
        out.append(mv.Pending(add, setup.players[add].player(status.get(add)), drop, c.clears))
    return tuple(out)


def ros_of(built: Built) -> Callable[[mv.Move], float | None]:
    """Each move's rest of the season under the simulated beliefs, the engine's own figure
    (``decisions.move_projection``'s season horizon), cached; the season guard's input."""
    p = built.problem
    seen: dict[tuple[int, int | None, date], float | None] = {}

    def ros(m: mv.Move) -> float | None:
        k = (m.add, m.drop, mv.day_of(p, m))
        if k not in seen:
            proj = dl.move_projection(p, built.scorer, *k)
            s = ((proj or {}).get("horizons") or {}).get(dl.SEASON)
            seen[k] = None if s is None else s.get("value")
        return seen[k]

    return ros


def guard_of(built: Built) -> mv.Allowed:
    return mv.season_guard(ros_of(built))


def allowed_of(built: Built) -> mv.Allowed | None:
    """The allowed set every search of a tier is handed (the guard PR), the one place a tier
    takes it: the season guard (:func:`guard_of`) under ``block``, none under ``off`` (the
    engine's searches then test feasibility alone)."""
    return guard_of(built) if built.guard == BLOCK else None


def stake_unread(setup: Setup) -> str:
    """Why no seat reads a stake in ``setup``, a league whose bracket is not read."""
    return (
        "a stake reads the cut line and the bracket's weeks, and this league's bracket is not "
        f"read ({setup.bracket_unread or 'no spec'}): the bracket is not trusted"
    )


def stake_of(setup: Setup, state: SimState, team: int, week: int) -> float:
    """``L``, the stake of week ``week`` for ``team`` (``sim/stake.py``): the runner's figure for
    the week when the state holds one (``SimState.stakes``, set once a week), else the same
    function of the state's finished weeks. A league whose bracket is not read has no cut line
    and no bracket's weeks to trust: refused by name (ValueError)."""
    if setup.spec is None:
        raise ValueError(stake_unread(setup))
    held = state.stakes.get(team)
    return week_stake(setup.spec, state.totals, team, week) if held is None else held


def guarded(
    built: Built, setup: Setup, state: SimState, guard: str = BLOCK, stake: float = 0.0
) -> Built:
    """``built`` as an arm's seat with ``guard`` and ``stake`` decides on it (the guard PR): its
    guard, its stake and, at a stake above 0, the week's ``L`` for the seat (:func:`stake_of`).
    At the defaults ``built`` itself: a seat that names neither, a rival and a mirror decide as
    before."""
    if guard not in GUARDS:
        raise ValueError(f"guard {guard!r}: one of {', '.join(GUARDS)}")
    if guard == BLOCK and not stake > 0:
        return built
    level = stake_of(setup, state, built.team, built.week.number) if stake > 0 else 0.0
    return replace(built, guard=guard, stake=float(stake), level=level)


# --------------------------------------------------------------------------- the season term
class SeasonFigure:
    """``ROS_w``, the season term's figure (#172, PR C), on one problem at one ``playoff_weight``.

    ``worth_w(k)`` (:meth:`worth`) is a player's season value above a dead spot
    (``problem.season_value[k] - problem.dead``, the keep rule's per-game figure) times his
    team's games from the day he counts from to the season's last day, a game on a day of the
    bracket's weeks counted ``playoff_weight`` times. He counts from the move's day, or from his
    return when that is later, as the engine reads it (``moves.back_from``, as
    ``moves.net_of_return`` and ``decisions.move_projection`` apply it); one who does not return
    this season is worth 0, and one without a season value has none. The games are the
    schedule's: a day it has no entry for has no game (a setup's schedule reaches the season's
    last day), and nothing is extrapolated. So at ``playoff_weight`` 1 a healthy player's figure
    is ``moves.worth_from`` and an absent one's ``moves.net_of_return``: the unit of the stash
    threshold (#373), not a third one.

    A move's (:meth:`move`) is the add's less the drop's on the day it counts from
    (``moves.day_of``), the add's alone with no drop, and none when either has no season value;
    a set's (:meth:`of`) is the sum over its moves, a move with none counting zero
    (``moves.season_total``). The unit is a value times games, not expected category wins: the
    season scale (:func:`scale_of`) says what size of ``season_weight`` makes the two alike."""

    def __init__(self, built: Built, playoff_weight: float) -> None:
        p = built.problem
        self.problem = p
        self.playoff_weight = float(playoff_weight)
        self.bracket = built.bracket
        self._players = {**dict(p.candidates), **dict(p.held), **dict(p.roster)}
        self._games: dict[str, tuple[list[date], list[float]]] = {}
        self._worth: dict[tuple[int, date], float | None] = {}

    def games(self, nba_team: str | None, start: date) -> float:
        """``nba_team``'s games on the schedule from ``start`` to the season's last day, a bracket
        day's counted ``playoff_weight`` times."""
        end = self.problem.season_end
        if not nba_team or end is None or start > end:
            return 0.0
        if nba_team not in self._games:
            days = sorted(
                d for d, teams in self.problem.schedule.items() if d <= end and nba_team in teams
            )
            after = [0.0] * (len(days) + 1)
            for i in range(len(days) - 1, -1, -1):
                after[i] = after[i + 1] + (self.playoff_weight if days[i] in self.bracket else 1.0)
            self._games[nba_team] = (days, after)
        days, after = self._games[nba_team]
        return after[bisect_left(days, start)]

    def worth(self, key: int, day: date) -> float | None:
        """``worth_w``: what ``key`` is worth from ``day`` (or his return) to the season's end."""
        memo = (key, day)
        if memo not in self._worth:
            p = self.problem
            value = p.season_value.get(key)
            player = self._players.get(key)
            out: float | None = None
            if value is not None and player is not None:
                back = mv.back_from(p, key, player)
                out = (
                    0.0
                    if back is None
                    else (value - p.dead) * self.games(player.nba_team, max(day, back))
                )
            self._worth[memo] = out
        return self._worth[memo]

    def move(self, m: mv.Move) -> float | None:
        """``ROS_w`` of one move: the add's worth less the drop's, from the day it counts."""
        day = mv.day_of(self.problem, m)
        add = self.worth(m.add, day)
        if m.drop is None:
            return add
        drop = self.worth(m.drop, day)
        return None if add is None or drop is None else add - drop

    def of(self, moves: Iterable[mv.Move]) -> float:
        """``ROS_w`` of a set: its moves' summed, a move with none counting zero."""
        return mv.season_total(self.move, moves)[0]


class Seasoned:
    """A search's values with the season term on the key the arm executes (#172, PR C): the
    shape the engine's searches take (``moves.Valued``). On ``key`` a set's value is ``inner``'s
    plus ``weight`` times its ``ROS_w`` (:class:`SeasonFigure`); every other key is ``inner``'s.
    No moves have no term, so ``base`` is the inner's on every key (``moves.recommend`` reads a
    gain for each)."""

    def __init__(self, inner: mv.Valued, key: str, weight: float, figure: SeasonFigure) -> None:
        self.inner = inner
        self.problem = inner.problem
        self.key = key
        self.weight = float(weight)
        self.figure = figure
        self.base = dict(inner.base)

    def value(self, key: str, moves: Iterable[mv.Move]) -> float:
        moves = tuple(moves)
        v = self.inner.value(key, moves)
        return v + self.weight * self.figure.of(moves) if key == self.key else v

    def gain(self, key: str, moves: Iterable[mv.Move]) -> float:
        return self.value(key, moves) - self.base[key]


def later_share(built: Built) -> float:
    """``1 - stake x L``: how many times the season term counts a game after the running week
    on ``built``'s day (the guard PR), the one function every reader of the stake in force
    calls; ``L`` is the week's stake for the seat (``Built.level``, 0 to 1). 1 at ``stake`` 0
    and in a week whose stake is 0: the term is then the season figure itself
    (:func:`season_figure_of`). The season scale (:func:`scale_of`) is measured without the
    term and does not read it."""
    return 1.0 - built.stake * built.level


class StakedFigure(SeasonFigure):
    """The season figure a seat's term reads in a week that has a stake for it (the guard PR):
    :class:`SeasonFigure` with a game after the running week's last day counted ``share`` times
    (:func:`later_share`, ``1 - stake x L``) and a game of the running week counted in full, a
    bracket day's ``playoff_weight`` times in both parts as there. So a move's figure is

        its part over the days from its landing to the running week's last day
        + share x its part over the days after

    and a decisive week moves the term's weight from the later season to the week itself: at a
    share of 0 a player whose games are all after this week has no term, and one who plays
    this week keeps this week's. A move that lands after the running week (one decided on its
    last day, or a claim that clears later) has no part in it: its whole figure is scaled, by
    the stake of the week it was decided in (a limit, stated in the README)."""

    def __init__(self, built: Built, playoff_weight: float, share: float) -> None:
        super().__init__(built, playoff_weight)
        self.share = float(share)
        #: The first day after the running week: where the figure is split.
        self.later = built.week.end + timedelta(1)

    def games(self, nba_team: str | None, start: date) -> float:
        """``nba_team``'s games from ``start`` on, those after the running week counted
        ``share`` times."""
        whole = super().games(nba_team, start)
        rest = super().games(nba_team, max(start, self.later))
        return (whole - rest) + self.share * rest


def season_figure_of(built: Built) -> SeasonFigure:
    """The season term's figure in force on ``built``'s day (the guard PR), the one place every
    reader of the term takes it: :class:`SeasonFigure` at the arm's ``playoff_weight``, the
    figure as it was, whenever ``stake x L`` is 0 (no stake, or a week whose stake is 0: the
    same object on the same path, never a sum of two parts); :class:`StakedFigure` at
    :func:`later_share` otherwise."""
    playoff = knob(built.knobs, "playoff_weight")
    if built.stake * built.level == 0:
        return SeasonFigure(built, playoff)
    return StakedFigure(built, playoff, later_share(built))


def seasoned(built: Built, inner: mv.Valued, key: str) -> mv.Valued:
    """``inner`` with the season term on ``key`` (:class:`Seasoned`) at the arm's
    ``season_weight``, on the season figure in force (:func:`season_figure_of`: with a
    ``stake``, the games after the running week count ``1 - stake x L`` times); ``inner`` itself
    at ``season_weight`` 0, where the wrapper is not built and the search is the engine's own."""
    weight = float(knob(built.knobs, "season_weight"))
    if weight == 0:
        return inner
    return Seasoned(inner, key, weight, season_figure_of(built))


# --------------------------------------------------------------------------- the tiers
def _weight(knobs: Mapping[str, Any], weeks_left: int) -> float:
    """The arm's λ on the frontier (``strategy.weights``): its ``horizon_weight``'s; with no week
    after this one the frontier is this week's alone, and so is the weight, whatever the knob."""
    key = str(knob(knobs, "horizon_weight") or "natural")
    frontier = sg.weights(weeks_left)
    for w in frontier:
        if w.key == key:
            return w.lam
    if len(frontier) == 1:
        return frontier[0].lam
    raise KeyError(f"horizon weight {key!r} is not one of {sg.WEIGHT_KEYS}")


Swaps = Mapping[int, Sequence[mv.SwapGain]]


def _horizon_swaps(ev: mv.Evaluator) -> dict[str, dict[int, list[mv.SwapGain]]]:
    """Every candidate's single swaps on each of the week and the three weeks."""
    return {key: mv.single_swaps(ev, key) for key in HORIZONS}


def _weighted_head(swaps: Mapping[str, Swaps], fields: Fields) -> list[int]:
    """The best ``pool`` by single-swap gain on each horizon of ``swaps``, taken in turn
    (``strategy.pool_of``)."""
    gains = {key: {c: g[0].gain for c, g in swaps[key].items() if g} for key in HORIZONS}
    return sg.pool_of(gains, fields.pool)


def _weighted_pool(ev: mv.Evaluator, fields: Fields) -> list[int]:
    """The weighted search's candidates: the best ``pool`` by single-swap gain on each of the
    week and the three weeks, taken in turn (``strategy.pool_of``)."""
    return _weighted_head(_horizon_swaps(ev), fields)


def _weighted_union(swaps: Mapping[str, Swaps], allowed: mv.Allowed, fields: Fields) -> sp.Pool:
    """The weighted search's candidates at a ``guard_pool`` above 0 (#172, PR pool), in the live
    strategy run's form (``api.season_strategy``, read as the reference and put together again
    here from the engine's own functions): the head as at 0 (:func:`_weighted_head`), then each
    horizon's guard's list (``pool.admitted_swaps`` on that horizon's single swaps) taken in
    turn by ``strategy.pool_of``, ``guard_pool`` in all, joined without repeating an add
    (``pool.joined``)."""
    listed = {
        key: {
            c: g.gain
            for c, g in sp.admitted_swaps(swaps[key], allowed, fields.guard_pool, fields.min_gain)
        }
        for key in HORIZONS
    }
    return sp.joined(_weighted_head(swaps, fields), sg.pool_of(listed, fields.guard_pool))


def _union_of(
    pool: sp.Pool,
    tables: Sequence[Swaps],
    allowed: mv.Allowed,
    min_gain: float,
    moves: Iterable[mv.Move],
) -> PoolUnion:
    """What the day's union ``pool`` was, for the counts (:class:`PoolUnion`): the adds the
    guard's list brought, the ones of them the decided ``moves`` add, and how many of the head's
    adds have, on one of ``tables`` (a horizon's single swaps each: the ones the pool was ranked
    on), a best single move that gains more than ``min_gain`` and that ``allowed`` refuses. The
    guard is asked about single moves only, as the list itself asks it."""
    head, listed = pool.players[: pool.size], set(pool.players[pool.size :])

    def refused(c: int) -> bool:
        best = (t[c][0] for t in tables if t.get(c))
        return any(g.gain > min_gain and not allowed((mv.Move(c, g.drop),)) for g in best)

    took = tuple(m.add for m in moves if m.add in listed)
    return PoolUnion(pool.admitted, took, sum(1 for c in head if refused(c)))


def listed_of(fields: Fields, allowed: mv.Allowed | None) -> bool:
    """Whether a search of the exact tier takes the union pool (#172, PR pool): the arm's
    ``guard_pool`` is above 0 and there is a guard to make the list. Handed none (the arm's
    guard ``off``, :func:`allowed_of`) the rule gives the head alone, so the lines of 0 run."""
    return fields.guard_pool > 0 and allowed is not None


def _three_pool(swaps: Mapping[int, Sequence[mv.SwapGain]], fields: Fields) -> list[int]:
    """The recommended set's candidates: the best ``pool`` by single-swap gain above
    ``min_gain``."""
    ranked = sorted(
        (c for c, g in swaps.items() if g and g[0].gain > fields.min_gain),
        key=lambda c: -swaps[c][0].gain,
    )
    return ranked[: fields.pool]


def exact(
    built: Built,
    executes: str = QUEUE_SET,
    with_plan: bool = True,
    fields: Fields = DEFAULT_FIELDS,
) -> Decision:
    """The live moves route's set on ``QUEUE_SET`` (or the strategy route's weighted set), the
    season guard on every search (:func:`allowed_of`: none under the arm's guard ``off``), the
    streaming plan beside. With a ``season_weight`` the single
    swaps, the pool's ranking and the recommended set (or the weighted search) all take the
    season term (:func:`seasoned`); the week's plan does not. An arm that executes ``queue``
    takes the queue's rule (:func:`queue_rule`, PR E), which draws its own plans: ``with_plan``
    is not read there.

    The pool the set is searched among (#172, PR pool). At ``guard_pool`` 0, the default, it is
    cut before the guard sees anything: the best ``pool`` by single-swap gain
    (:func:`_three_pool`, :func:`_weighted_pool`), so when the guard refuses most of those the
    search has little left. Above 0 it is the engine's union, as live searches since #424: the
    same head, then the adds whose best single move the guard admits, ``guard_pool`` of them
    (``pool.pool_for`` through the door on the single swaps the arm ranks today, the season
    term on them; for the weighted search :func:`_weighted_union`). The guard is the one object
    every search of the day is handed, so what it has worked out for the list is not worked out
    again. The decision then says what the union was (:class:`PoolUnion`). A list needs a
    guard: handed none (the arm's guard ``off``, the guard PR), the rule gives the head alone,
    so the searches run as at 0 and no union is kept (:func:`listed_of`). The week plan's set
    below is not part of it: it searches the first ``pool`` candidates in candidate order,
    whatever the field."""
    if executes == QUEUE:
        return queue_rule(built, fields)
    p = built.problem
    ev = mv.Evaluator(p)
    allowed = allowed_of(built)
    listed = listed_of(fields, allowed)
    solves = 0
    union: sp.Pool | None = None
    tables: tuple[Swaps, ...] = ()
    if executes == WEIGHTED:
        if listed:
            both = _horizon_swaps(ev)
            union = _weighted_union(both, allowed, fields)
            pool, tables = list(union.players), tuple(both.values())
        else:
            pool = _weighted_pool(ev, fields)
        w = seasoned(
            built,
            sg.Weighted(ev, _weight(built.knobs, built.weeks_left), built.weeks_left),
            sg.WEIGHTED,
        )
        moves = mv.search(
            w, sg.WEIGHTED, pool, keep=p.kept, min_gain=fields.min_gain, allowed=allowed
        )
        held = tuple(mv.held_used(p, moves))
        solves += 1
    else:
        scored = seasoned(built, ev, QUEUE_SET)
        swaps = mv.single_swaps(scored, QUEUE_SET)
        if listed:
            union, _ = sp.pool_for(swaps, allowed, fields.pool, fields.guard_pool, fields.min_gain)
            pool, tables = list(union.players), (swaps,)
        else:
            pool = _three_pool(swaps, fields)
        rec = mv.recommend(scored, QUEUE_SET, pool, min_gain=fields.min_gain, allowed=allowed)
        moves = tuple(pm.move for pm in rec.moves)
        held = tuple(rec.held)
        solves += 1
    plan: tuple[mv.Move, ...] = ()
    taken = None
    if with_plan:
        week_set = mv.search(
            ev,
            "week",
            [c for c, _ in p.candidates][: fields.pool],
            keep=p.kept,
            min_gain=fields.min_gain,
            allowed=allowed,
        )
        planned = st.plan(ev, built.rule, week_set, p.value, allowed=allowed)
        if planned is not None and st.recommended(ev, planned):
            plan, taken = planned.steps, planned
        solves += 1
    basis = basis_of(built, ev, moves, taken)
    made = None if union is None else _union_of(union, tables, allowed, fields.min_gain, moves)
    return named(p, Decision(tuple(moves), held, plan, solves, "exact", basis, union=made))


# --------------------------------------------------------------------------- the queue's rule
def in_bracket(built: Built) -> bool:
    """Whether today's week is one of the bracket's (``Built.bracket``; never without a bracket
    read): the live build's ``playoff``, on which a week plan leads on the matchup's odds."""
    return built.problem.first_day in built.bracket


def queue_weight(built: Built) -> float:
    """The weight of the three weeks in the queue's score (#172, PR E): the arm's
    ``three_weight``, and 0 in a bracket week, where the matchup decides who advances (as the
    live route sets it, ``api.season_moves.week_plans_payload``). The one place the queue's rule
    and its steps' bids take the weight from."""
    return 0.0 if in_bracket(built) else float(knob(built.knobs, "three_weight"))


def step_bids(plan: pl.WeekPlan, weight: float) -> tuple[float, ...]:
    """What each step of the plan the queue took bids on in a FAAB league (#172, PR E), in the
    order of its steps: its score (``plans.step_score``), its week increment plus ``weight``
    (:func:`queue_weight`) times its three weeks' increment, as the live queue bids a step; so
    in a bracket week its week increment alone. The increments are the engine's own, on its
    plain evaluator."""
    return tuple(pl.step_score(s, weight) for s in plan.steps)


@dataclass(frozen=True)
class Drawn:
    """What the queue's rule drew on one day (#172, PR E): what :func:`draw_queue` handed the
    engine's week plans, and the engine's answer."""

    #: The three weeks' set as ``executes: three`` finds it (the season term on it, the guard on
    #: its search), with its held-slot moves and its basis.
    three: Decision
    #: The week's recommended set, the week's single swaps and the week's streaming plan without
    #: the three-week guard: what the plans' pool is made of.
    week_set: tuple[mv.Move, ...]
    swaps: Mapping[int, Sequence[mv.SwapGain]]
    stream: st.Plan | None
    #: The weight of the three weeks in the score, and whether today's week is the bracket's.
    weight: float
    playoff: bool
    #: Every plan the engine valued (``plans.every_plan``), and the one the queue takes instead
    #: of the set (``plans.for_queue``); None when the set stands.
    plans: tuple[pl.WeekPlan, ...]
    chosen: pl.WeekPlan | None
    #: What the week's set's union pool was (PR pool); None when none was built (the arm's
    #: ``guard_pool`` at 0, or its guard ``off``).
    week_union: PoolUnion | None = None


def draw_queue(built: Built, fields: Fields = DEFAULT_FIELDS) -> Drawn:
    """The day's week plans and the queue's choice among them and the three weeks' set (#172, PR
    E), by the engine's own functions in the live route's order
    (``api.season_moves._payload`` and ``week_plans_payload``, read as the reference and written
    again here; nothing of the plans, the gate, the floor or the trim is the simulator's):

    1. the three weeks' set as ``executes: three`` finds it (:func:`exact`: the season term on
       it, the guard on its search, and at a ``guard_pool`` above 0 its union pool, PR pool);
    2. the week's recommended set, among the arm's ``pool`` best candidates by single-swap gain
       on the week above ``min_gain``, as the three weeks' set is found on its own key, and at
       a ``guard_pool`` above 0 among the week's own union, that head and then the adds whose
       best single move on the week the guard admits (``pool.pool_for`` through the door, on
       the week's single swaps, as the live route builds it since #424; PR pool); the
       week's single swaps on every candidate; the week's streaming plan against that set
       without the three-week guard (the plans weigh the week first themselves), on the
       league's scorer's per-game values;
    3. the weight (:func:`queue_weight`) and whether the week is the bracket's
       (:func:`in_bracket`);
    4. ``plans.held_out``, ``plans.every_plan`` and ``plans.for_queue``, each given the guard.

    The allowed set is the arm's (:func:`allowed_of`: the season guard under ``block``, none
    under the arm's guard ``off``, the guard PR), taken once here for every call; the guard is
    the engine's own season figure and does not read the season term. The plans and the gate
    are valued on the engine's plain evaluator: the season term reaches the choice through the
    three weeks' set only (``plans.matchup`` reads the evaluator's odds and ``plans.held_out``
    builds evaluators of its own, so the library does not take :class:`Seasoned`). One thing
    the live route has that this does not: the searches' tie-break on the season, which the
    simulator's ``three`` has not either. The pool's adds from the guard's list (#424) are an
    arm's choice (``guard_pool``, PR pool), off by default: at 0 both sets are searched among
    the head alone, as before. What the week's union was is kept beside the three weeks' set's
    (``Drawn.week_union``, ``three.union``; :func:`queue_rule` makes the day's of the two)."""
    p = built.problem
    three = exact(built, QUEUE_SET, False, fields)
    ev = mv.Evaluator(p)
    allowed = allowed_of(built)
    swaps = mv.single_swaps(ev, "week")
    union: sp.Pool | None = None
    if listed_of(fields, allowed):
        union, _ = sp.pool_for(swaps, allowed, fields.pool, fields.guard_pool, fields.min_gain)
        pool = list(union.players)
    else:
        pool = _three_pool(swaps, fields)
    week = mv.recommend(ev, "week", pool, min_gain=fields.min_gain, allowed=allowed)
    week_set = tuple(pm.move for pm in week.moves)
    made = None if union is None else _union_of(union, (swaps,), allowed, fields.min_gain, week_set)
    per_game = {k: wk.net_value(built.scorer, r) for k, r in p.rates.items()}
    stream = st.plan(ev, built.rule, week_set, per_game, guard=False, allowed=allowed)
    weight, playoff = queue_weight(built), in_bracket(built)
    held = pl.held_out(ev)
    every = pl.every_plan(ev, week_set, swaps, stream, allowed, held, three.moves, weight)
    chosen = pl.for_queue(ev, every, three.moves, weight, playoff, allowed, held)
    return Drawn(three, week_set, swaps, stream, weight, playoff, tuple(every), chosen, made)


def queue_rule(built: Built, fields: Fields = DEFAULT_FIELDS) -> Decision:
    """The live queue's rule (#172, PR E), an exact arm that executes ``queue``: the week plan
    the engine takes instead of the three weeks' set (:func:`draw_queue`) when there is one,
    else the set. A plan that leads is the decision's ``plan``, each step a move dated its own
    day, with the plan's held-slot moves and ``plan_leads``; the executor queues the steps due
    today (:func:`queue`), and the rest are drawn again on their day, as the live queue is
    rebuilt on every run. ``moves`` is the three weeks' set either way. In a FAAB league a
    step bids on its score (:func:`step_bids`). Three solves: the three weeks' set, the week's
    set with its streaming plan, and the plans' search. The decision's union (PR pool) is the
    day's (:func:`_day_union`): the two sets' unions together, and the adds taken from a list
    the three weeks' set's while the set stands, none on a day a plan leads."""
    drawn = draw_queue(built, fields)
    three = drawn.three
    solves = three.solves + 2
    chosen = drawn.chosen
    union = _day_union(three.union, drawn.week_union, chosen is not None)
    if chosen is None:
        return replace(three, solves=solves, union=union)
    steps = tuple(mv.Move(s.move.add, s.move.drop, s.day) for s in chosen.steps)
    held = tuple(mv.held_used(built.problem, chosen.moves))
    basis = three.basis
    if basis is not None:
        basis = replace(basis, plan=step_bids(chosen, drawn.weight))
    led = Decision(three.moves, held, steps, solves, "exact", basis, plan_leads=True, union=union)
    return named(built.problem, led)


def _day_union(
    three: PoolUnion | None, week: PoolUnion | None, plan_leads: bool
) -> PoolUnion | None:
    """A day's union under the queue's rule (#172, PR pool on PR E): the three weeks' set's and
    the week's set's together. The adds the lists brought and the head's adds the guard refused
    are summed over the two sets (an add both lists brought is counted in each). The adds taken
    from a list are those of the set the seat means to queue: the three weeks' set's while the
    set stands. On a day a plan leads there is none: the plans are drawn by the engine from
    every candidate's single swaps on the week beside the two sets' moves, so no step can be
    said to have come from a list (the arm at 0 may draw the same step), and what the lists
    changed that day is in the plan itself. None when no union was built: the two sets take
    one together or not at all (:func:`listed_of`)."""
    if three is None or week is None:
        return None
    took = () if plan_leads else three.took
    return PoolUnion(three.admitted + week.admitted, took, three.refused + week.refused)


def _games(built: Built, member: mv.Member, from_day: date) -> int:
    p = built.problem
    days = [d for d in p.horizons["week"][0].days if d >= from_day]
    return len(wk.game_days(member[1].nba_team, days, p.schedule))


def _surrogate_pool(built: Built, fields: Fields) -> list[int]:
    """The surrogate's candidates: the best ``pool`` by value times games this week."""
    p = built.problem
    start = p.first_day + timedelta(1)
    ranked = sorted(
        p.candidates,
        key=lambda m: (-p.value.get(m[0], 0.0) * max(1, _games(built, m, start)), m[0]),
    )
    return [k for k, _ in ranked[: fields.pool]]


def surrogate(built: Built, fields: Fields = DEFAULT_FIELDS) -> Decision:
    """The same evaluator on the ``pool`` best candidates by value times games this week, the
    greedy search alone on ``QUEUE_SET`` (with the season term at a ``season_weight``), the
    season guard kept (:func:`allowed_of`: none under the arm's guard ``off``)."""
    p = built.problem
    plain = mv.Evaluator(p)
    ev = seasoned(built, plain, QUEUE_SET)
    allowed = allowed_of(built)
    moves = mv.search(
        ev,
        QUEUE_SET,
        _surrogate_pool(built, fields),
        keep=p.kept,
        min_gain=fields.min_gain,
        allowed=allowed,
    )
    basis = basis_of(built, plain, moves)
    held = tuple(mv.held_used(p, moves))
    return named(p, Decision(tuple(moves), held, (), 1, "surrogate", basis))


def ranking(built: Built) -> Decision:
    """The pool's best by value times games this week for the roster's worst the keep rule does
    not keep, when it gains; no evaluator. It does not search with the engine, so the stash
    threshold (PR G) is not its to read: its one swap is tested as before the reader."""
    p = built.problem
    if p.stash_threshold is not None:
        p = replace(p, stash_threshold=None)
    start = p.first_day + timedelta(1)

    def worth(m: mv.Member) -> float:
        return p.value.get(m[0], 0.0) * _games(built, m, start)

    adds = sorted(p.candidates, key=lambda m: (-worth(m), m[0]))
    drops = sorted((m for m in p.roster if m[0] not in p.kept), key=lambda m: (worth(m), m[0]))
    if not adds or not drops or p.limits and p.limits[0].adds is not None and p.limits[0].adds <= 0:
        return Decision(source="ranking")
    add, drop = adds[0], drops[0]
    if worth(add) <= worth(drop):
        return Decision(source="ranking")
    move = mv.Move(add[0], drop[0])
    if not mv.feasible(p, (move,)):
        return Decision(source="ranking")
    return Decision((move,), (), (), 0, "ranking")


def queue_refused(tier: str, executes: str) -> str | None:
    """Why ``tier`` may not execute ``executes``; None when it may. The queue's rule (#172, PR
    E) is the exact tier's: no other tier draws the week plans it chooses among."""
    if executes == QUEUE and tier != "exact":
        return (
            f"executes {QUEUE!r} is the exact tier's: the {tier} tier draws no week plan for "
            "the queue's rule to weigh"
        )
    return None


def mark_past_guard(built: Built, decision: Decision) -> Decision:
    """``decision`` marked when its set is one the season guard would have refused (the guard
    PR): its rest of the season is below 0 by the engine's own figure (:func:`guard_of`, the
    guard itself asked). Only a seat whose guard is ``off`` can decide such a set, so under
    ``block`` nothing is asked and the decision is returned as it is. The week plan's steps are
    not asked about, nor the exact tier's week set. A mark is a decision the block would have
    turned; an unmarked one may be too (the block tests every set a search tries, so its search
    can end on another set where this one passes as a whole): the count of marks is a lower
    bound on how often the block binds."""
    if built.guard == BLOCK or not decision.moves or guard_of(built)(decision.moves):
        return decision
    return replace(decision, past_guard=True)


def decide(
    built: Built,
    tier: str,
    executes: str = QUEUE_SET,
    with_plan: bool = True,
    fields: Fields = DEFAULT_FIELDS,
) -> Decision:
    """The tier's decision on the day (:func:`_decide`), with the players of the seat the engine
    reads as returning that day (:func:`returning_of`, PR G: what a run that names a stash
    threshold counts the seat's drops against)."""
    out = _decide(built, tier, executes, with_plan, fields)
    reading = returning_of(built.problem)
    return replace(out, returning=reading) if reading else out


def _decide(
    built: Built,
    tier: str,
    executes: str,
    with_plan: bool,
    fields: Fields,
) -> Decision:
    """The tier's decision on the day: the surrogate solves on its days only. On its other days
    it still names whom each of its held players sends when he comes back (:func:`sends_of`, PR
    G: no solve, the plan's charge with no move made), so a return on any morning finds the
    seat's own choice. ``queue`` is the exact tier's (:func:`queue_refused`, PR E). Under the
    arm's guard ``off`` (the guard PR) a set the season guard would have refused is marked so
    (:func:`mark_past_guard`)."""
    why = queue_refused(tier, executes)
    if why is not None:
        raise ValueError(why)
    if tier == "exact":
        return mark_past_guard(built, exact(built, executes, with_plan, fields))
    if tier == "surrogate":
        if built.problem.first_day.weekday() not in fields.surrogate_days:
            return named(built.problem, Decision(source="surrogate"))
        return mark_past_guard(built, surrogate(built, fields))
    if tier == "ranking":
        return ranking(built)
    raise ValueError(f"unknown tier {tier!r}: one of {TIERS}")


# --------------------------------------------------------------------------- the season scale
@dataclass(frozen=True)
class Scale:
    """The season scale on one seat's day (:func:`scale_of`), over ``swaps`` swaps (each
    candidate's best single swap on the executed key, without the term): ``gain``, their gains'
    median; ``ros``, the median of their ``ROS_w``; ``ratio``, the median ``|gain|`` over the
    median ``|ROS_w|`` of the swaps that have a ``ROS_w`` (0 or more: the ``season_weight`` at
    which the term is the week gain's size; None when none has one or the second is within
    ``moves.EPS`` of 0); ``against``, the share of those swaps whose ``ROS_w`` is below 0 (the
    week's best swap costs season value; None when none has one)."""

    gain: float | None
    ros: float | None
    ratio: float | None
    swaps: int
    against: float | None = None


def scale_of(
    built: Built,
    tier: str,
    executes: str = QUEUE_SET,
    fields: Fields = DEFAULT_FIELDS,
) -> Scale | None:
    """The season scale (#172, PR C): over the arm's pool on ``built``'s day (the exact tier's
    best ``pool`` by single-swap gain above ``min_gain``, the weighted search's, the surrogate's
    best by value times games), each candidate's best single swap on the key the arm executes,
    without the term (the ratio unsigned and the share against since PR C2). A
    ``season_weight`` equal to the ratio makes the term about as loud as the odds gain. None on
    the ranking tier and a static seat, which hold no odds. It decides nothing, draws nothing and
    is the same at any ``season_weight``."""
    if tier not in ("exact", "surrogate"):
        return None
    ev = mv.Evaluator(built.problem)
    if tier == "exact" and executes == WEIGHTED:
        pool = _weighted_pool(ev, fields)
        w = sg.Weighted(ev, _weight(built.knobs, built.weeks_left), built.weeks_left)
        best = mv.single_swaps(w, sg.WEIGHTED, pool)
    elif tier == "exact":
        swaps = mv.single_swaps(ev, QUEUE_SET)
        best = {c: swaps[c] for c in _three_pool(swaps, fields)}
    else:
        best = mv.single_swaps(ev, QUEUE_SET, _surrogate_pool(built, fields))
    figure = SeasonFigure(built, knob(built.knobs, "playoff_weight"))
    rows = [(g[0].gain, figure.move(mv.Move(c, g[0].drop))) for c, g in best.items() if g]
    gains = [x for x, _ in rows]
    valued = [(x, r) for x, r in rows if r is not None]
    gain = median(gains) if gains else None
    season = median(r for _, r in valued) if valued else None
    ratio = against = None
    if valued:
        size = median(abs(r) for _, r in valued)
        ratio = None if size <= mv.EPS else median(abs(x) for x, _ in valued) / size
        against = sum(1 for _, r in valued if r < 0) / len(valued)
    return Scale(gain, season, ratio, len(rows), against)


# --------------------------------------------------------------------------- what each knob reads
#: A knob or field a seat reads: a different value can change what it queues.
READ = "read"


@dataclass(frozen=True)
class Shape:
    """What of a league and its run decides which knobs a seat reads (#172, PR C): its scoring
    as the problem reads it, whether it has held slots, whether its bracket is read, whether
    the run names the two sources' stand-ins (PR D1: ``replay --bbm-as``, ``--yahoo-as``) and
    its waivers (PR Fa, ``shapes.WAIVERS``; in a FAAB league a seat that bids reads its FAAB
    sizing and its plan floor, PR Fb), and a categories league's head-to-head format (the format
    PR: in a one-win league the plan floor is the engine's own). The format is the run's, one a
    run, and the label leaves it out: the record names it in ``league.rules.h2h``."""

    scoring: str = "categories"
    held: bool = False
    bracket: bool = True
    standins: bool = False
    waivers: str = "none"
    h2h: str = ONE_WIN

    @property
    def one_win(self) -> bool:
        """Whether a week is one result and a seat that weighs weighs the matchup's odds."""
        return self.scoring == "categories" and self.h2h == ONE_WIN

    def label(self) -> str:
        parts = (
            f"{self.scoring} league",
            "held slots" if self.held else "no held slots",
            "bracket read" if self.bracket else "no bracket read",
        )
        if self.standins:
            parts = (*parts, "the two sources' stand-ins named")
        if self.waivers != "none":
            parts = (*parts, f"waivers by {self.waivers}")
        return ", ".join(parts)


def shape_of(setup: Setup) -> Shape:
    points = setup.scoring == "points" and bool(setup.points)
    return Shape(
        "points" if points else "categories",
        any(s in mv.HELD for s in setup.roster_slots),
        setup.spec is not None,
        waivers=setup.waivers,
        h2h=setup.h2h,
    )


def measure(points: bool, one_win: bool) -> str:
    """What a seat that weighs weighs a week in (``moves.measure_of`` of the problem
    :func:`problem_of` builds, the format PR): the matchup's odds in a one-win league, expected
    matchups won on the points in a points league, expected categories won in one that counts
    every category. The record names it once, even when no seat of the run weighs."""
    if one_win and not points:
        return mv.MATCHUP
    return mv.POINTS if points else mv.CATEGORIES


def measure_of(setup: Setup) -> str:
    """:func:`measure` of ``setup``'s league."""
    return measure(setup.scoring == "points" and bool(setup.points), setup.one_win)


class Configured(Protocol):
    """What of an arm decides what it reads (``run.Arm`` has it)."""

    tier: str
    executes: str
    with_plan: bool
    execute_plan: bool
    knobs: Mapping[str, Any]
    bid: bp.BidPolicy | None
    guard: str


#: What else reads a knob in a FAAB run (#172, PR Fb), said in the refusal's message after
#: :data:`WHEN_READ`'s words: a seat that bids reads its league's plan floor, its typical gain
#: until ten moves.
WHEN_READ_FAAB: Mapping[str, str] = {
    "plan_floor_cats": (
        "in a categories FAAB run by a seat that bids (the exact or the surrogate tier, a mirror "
        "rival), its typical gain until ten moves"
    ),
    "plan_floor_points": (
        "in a points FAAB run by a seat that bids (the exact or the surrogate tier, a mirror "
        "rival), its typical gain until ten moves"
    ),
    # PR F2: the season term's figure a bid weighs counts a bracket game playoff_weight times.
    "playoff_weight": (
        "in a FAAB run by a seat that bids (the exact or the surrogate tier, a mirror rival) on "
        "an arm whose bid weighs the season (bid.season above 0), in a league whose bracket is "
        "read"
    ),
}
#: What makes an arm's ``bid`` block read (PR F2), for the refusal's message.
BID_WHEN_READ = "a seat that bids in a FAAB league: the exact or the surrogate tier, a mirror rival"
#: Why two ``bid`` blocks apart only on a pace at ``k`` 0 are one seat where the block is read
#: (``bid_policy.BidPolicy.bids``), and what would read the difference.
PACE_AT_REST = (
    "the two blocks are apart only on a pace at k 0, which follows no path: its shape and its "
    "reserve move no bid, and it bids as no pace does"
)
PACE_WHEN_READ = "a pace whose k is above 0"
#: Why a plan floor is not read in a FAAB run by a seat that bids on an arm whose ``bid`` gives
#: the three weeks no weight (PR F2): the floor is that horizon's typical gain until ten moves,
#: and the block never reads it for a move of the set.
NO_THREE = (
    "the arm's bid gives the three weeks no weight (bid.week and bid.season sum to 1), and a "
    "seat that bids reads the floor only as its typical gain on the three weeks"
)

#: What else limits where a knob is read (the format PR), said in the refusal's message after
#: :data:`WHEN_READ`'s words and :data:`WHEN_READ_FAAB`'s: the categories plan floor is read only
#: where the league counts every category.
WHEN_READ_H2H: Mapping[str, str] = {
    "plan_floor_cats": "either only in a league that counts every category (--h2h each_category)",
}
#: Why ``plan_floor_cats`` is not read in a one-win league by a seat that would read it in one
#: that counts every category (the format PR).
ONE_WIN_FLOOR = (
    "a one-win league's plan floor is the engine's own, stream.PLAN_FLOOR_ODDS in the matchup's "
    "odds"
)

#: What makes each knob and field read, for the refusal's message.
WHEN_READ: Mapping[str, str] = {
    "system": "a run that names the two sources' stand-ins (replay --bbm-as, --yahoo-as)",
    "blend": "a run that names the two sources' stand-ins, on an arm whose system is blend",
    "horizon_weight": "the exact tier executing weighted",
    "protection_floor": "a seat that moves: the exact, surrogate or ranking tier",
    "plan_floor_cats": (
        "the exact tier drawing and executing the week plan, or executing queue, in a categories "
        "league"
    ),
    "plan_floor_points": (
        "the exact tier drawing and executing the week plan, or executing queue, in a points league"
    ),
    "stash_threshold": (
        "the arm's own seat on the exact or the surrogate tier, whose searches refuse a "
        "returning player's drop the threshold keeps"
    ),
    "faab_sizing": "a seat that bids in a FAAB league: the exact or the surrogate tier (PR Fb)",
    "daily_cap": "the exact or the surrogate tier, which may queue more than one move a day",
    "three_weight": "the exact tier executing queue",
    "season_weight": "the exact or the surrogate tier",
    "playoff_weight": (
        "a season_weight above 0 on the exact or the surrogate tier, in a league whose bracket "
        "is read"
    ),
    "pool": "the exact or the surrogate tier",
    "min_gain": "the exact or the surrogate tier",
    "weeks_ahead": "the exact or the surrogate tier",
    "surrogate_days": "the surrogate tier",
    "guard": "the exact or the surrogate tier, whose searches the season guard blocks",
    "stake": (
        "a season_weight above 0 on the exact or the surrogate tier, in a league whose bracket "
        "is read"
    ),
    "guard_pool": "the exact tier, while the arm's guard blocks",
}
STATIC = "a static seat makes no move"
#: Why ``guard_pool`` is not read off the exact tier (#172, PR pool): the union is of pools
#: ranked by single swaps, which only the exact tier draws; and on the exact tier under the
#: arm's guard ``off`` (the guard PR): the list is the guard's.
NO_SWAPS = (
    "the surrogate tier ranks its pool by value times games: it has no single swap to ask the "
    "season guard about"
)
NO_LIST = "the ranking tier searches no set, so it draws no guard's list"
GUARD_OFF = (
    "the arm's guard is off: with no season guard there is no guard's list, and the pool is "
    "its best `pool` adds alone, as at 0"
)
#: Why the ranking tier does not read the stash threshold (PR G).
RANKING_STASH = (
    "the ranking tier does not search with the engine: its one swap is not held to the threshold"
)
#: Why ``three_weight`` is not read: on the exact tier executing another choice, and on any
#: other tier (#172, PR E).
NOT_QUEUE = "the arm does not execute queue"
ONLY_QUEUE = "only the exact tier executing queue reads it"
#: What the reads table says beside its rows for an arm that executes ``queue`` (PR E), by knob:
#: where the season term stands in the queue's rule (:func:`read_notes`).
QUEUE_SEASON = (
    "under queue the season term is on the three weeks' set only; the week plans and the gate "
    "that weighs them against the set are the engine's own score, without the term; the season "
    "guard does not read the term and admits or refuses every plan all the same"
)
#: The same for a queue arm whose guard is ``off`` (the guard PR): the rule hands the engine no
#: allowed set (:func:`draw_queue`), so the note must not say the guard still judges a plan.
QUEUE_SEASON_OFF = (
    "under queue the season term is on the three weeks' set only; the week plans and the gate "
    "that weighs them against the set are the engine's own score, without the term; the arm's "
    "guard is off, so the season guard refuses no set and no plan"
)
#: Why ``system`` and ``blend`` are not read on a run without the two sources' stand-ins.
NO_STANDINS = "the run names no stand-ins for the two sources (--bbm-as, --yahoo-as)"


def _queue(arm: Configured) -> bool:
    """Whether the arm's seat takes the queue's rule: the exact tier executing ``queue``."""
    return arm.tier == "exact" and arm.executes == QUEUE


def read_notes(arm: Configured) -> dict[str, str]:
    """What the reads table says beside its rows for ``arm``, by knob (#172, PR E): for an arm
    that takes the queue's rule, where its season term stands (:data:`QUEUE_SEASON`, or
    :data:`QUEUE_SEASON_OFF` when the arm's guard is ``off``: the note never says the season
    guard judges a plan the rule did not hand it); nothing for any other arm, whose record is
    as it was."""
    if not _queue(arm):
        return {}
    return {"season_weight": QUEUE_SEASON_OFF if arm.guard == OFF else QUEUE_SEASON}


def _odds(arm: Configured, mirrored: bool) -> bool:
    """Whether a search on odds reads the arm's knobs: its own tier's, or the mirror rivals'
    (the surrogate on the arm's knobs and fields)."""
    return arm.tier in ("exact", "surrogate") or mirrored


def reads(arm: Configured, shape: Shape, mirrored: bool = False) -> dict[str, str]:
    """For each of the twelve knobs, :data:`READ` when a different value can change what ``arm``'s
    seat queues in a league of ``shape``, else the reason it cannot. A value that only changes
    what is recorded (a plan drawn and not executed) is not read. ``mirrored``: the arm's rivals
    are its mirror (``opponents.Mirror``), the surrogate on its knobs, so what the surrogate reads
    is read too."""
    odds = _odds(arm, mirrored)
    moves = odds or arm.tier in TIERS
    out: dict[str, str] = {}
    out["protection_floor"] = READ if moves else STATIC
    if odds:
        out["daily_cap"] = READ
    elif arm.tier == "ranking":
        out["daily_cap"] = "the ranking tier queues one move a day, under any cap"
    else:
        out["daily_cap"] = STATIC
    if arm.tier == "exact":
        out["horizon_weight"] = (
            READ if arm.executes == WEIGHTED else "the arm does not execute weighted"
        )
    else:
        out["horizon_weight"] = "only the exact tier executing weighted reads it"
    # A seat bids by the live rule in a FAAB league on the exact or the surrogate tier, and so
    # does a mirror rival on the arm's knobs (PR Fb): its bid scales by the typical gain, which is
    # the plan floor until ten moves. The ranking tier holds no gain in the engine's units, so its
    # claims bid $0 and it reads neither. That typical is the three weeks': an arm whose ``bid``
    # gives the three weeks no weight (PR F2) never reads it for a move of its set, and then
    # only a week plan's own route reads the floor: a streaming plan the arm executes, or the
    # queue's rule. Under the queue's rule (PR E) the floor is the gate a week plan must clear
    # to take the queue (``plans.gate_floor``): the rule draws and executes its own plan, so
    # the arm's two plan switches are not asked, and an arm that executes ``queue`` reads its
    # league's floor whatever its ``bid`` weighs.
    bids = shape.waivers == "faab" and odds
    rule = getattr(arm, "bid", None)
    three = rule is None or rule.three > 0
    queue = _queue(arm)
    for name, scoring in (("plan_floor_cats", "categories"), ("plan_floor_points", "points")):
        if arm.tier != "exact":
            why = "only the exact tier draws a week plan"
        elif not queue and not arm.with_plan:
            why = "the arm draws no week plan"
        elif not queue and not arm.execute_plan:
            why = "the plan is drawn and not executed"
        elif shape.scoring != scoring:
            why = f"a {shape.scoring} league"
        else:
            why = READ
        if bids and shape.scoring == scoring and why != READ:
            why = READ if three else NO_THREE
        # In a one-win league the engine's floor is its own and the knob reaches nothing (the
        # format PR); a seat that would not read it anyway keeps its reason.
        if why == READ and name == "plan_floor_cats" and shape.one_win:
            why = ONE_WIN_FLOOR
        out[name] = why
    # The weight of the three weeks in the queue's score (PR E): the queue's rule alone reads it.
    if queue:
        out["three_weight"] = READ
    else:
        out["three_weight"] = NOT_QUEUE if arm.tier == "exact" else ONLY_QUEUE
    # The arm's own seat believes by its system once the run names the stand-ins; a mirror
    # rival holds the run's forecaster, so nothing more is read through it.
    if shape.standins:
        out["system"] = READ
        out["blend"] = READ if arm.knobs["system"] == "blend" else "the arm's system is not blend"
    else:
        out["system"] = out["blend"] = NO_STANDINS
    if bids:
        out["faab_sizing"] = READ
    elif shape.waivers == "none":
        out["faab_sizing"] = "the world has no waivers and no budget: PR F"
    elif shape.waivers != "faab":
        out["faab_sizing"] = f"waivers by {shape.waivers} carry no budget and no bid: PR Fb"
    elif arm.tier == "ranking":
        out["faab_sizing"] = "the ranking tier holds no gain in the engine's units: it bids $0"
    else:
        out["faab_sizing"] = STATIC
    # The arm's own seat's searches read it on the problem (PR G: ``moves.stash_ok`` in every
    # set's feasibility, ``moves.guarded_pool`` on the drop a comeback forces). A mirror rival
    # keeps None (:func:`rival_knobs`), so nothing more is read through it.
    if arm.tier in ("exact", "surrogate"):
        out["stash_threshold"] = READ
    elif arm.tier == "ranking":
        out["stash_threshold"] = RANKING_STASH
    else:
        out["stash_threshold"] = STATIC
    if odds:
        out["season_weight"] = READ
    elif arm.tier == "ranking":
        out["season_weight"] = "the ranking tier ranks by value times games and holds no odds"
    else:
        out["season_weight"] = STATIC
    if out["season_weight"] != READ:
        out["playoff_weight"] = out["season_weight"]
    elif not float(arm.knobs["season_weight"]) > 0:
        out["playoff_weight"] = "season_weight is 0: there is no season term"
    elif not shape.bracket:
        out["playoff_weight"] = "the league has no bracket read"
    else:
        out["playoff_weight"] = READ
    # PR F2: a bid that weighs the season reads the season term's figure, which counts a bracket
    # game ``playoff_weight`` times, whatever the arm's ``season_weight``.
    if bids and rule is not None and rule.season > 0 and shape.bracket:
        out["playoff_weight"] = READ
    return {k: out[k] for k in KNOBS}


def bid_reads(arm: Configured, shape: Shape, mirrored: bool = False) -> str:
    """:data:`READ` when ``arm``'s ``bid`` block (PR F2) can change what its seat, or its mirror
    rivals, bid in a league of ``shape``, else the reason it cannot, as :func:`reads` says of
    ``faab_sizing``: it is read only in a FAAB league, by a seat that bids by the live rule (the
    exact or the surrogate tier, a mirror rival). Naming it elsewhere is allowed and moves
    nothing."""
    if shape.waivers == "faab" and _odds(arm, mirrored):
        return READ
    if shape.waivers == "none":
        return "the world has no waivers and no budget"
    if shape.waivers != "faab":
        return f"waivers by {shape.waivers} carry no budget and no bid"
    if arm.tier == "ranking":
        return "the ranking tier holds no gain in the engine's units: it bids $0"
    return STATIC


#: The arm's two season fields beside its knobs and its fields (#172, the guard PR), in the
#: order the payload names them: ``guard``, one of :data:`GUARDS`; ``stake``, 0 to 1. Both have
#: a default (the block, no stake), and an arm's payload carries one only when its spec names
#: it. They are the arm's own seat's: a rival, a mirror too, stays on the block with no stake.
SEASON_FIELDS = ("guard", "stake")
NO_GUARD = "the ranking tier searches no set, so no season guard blocks one"
NO_TERM = "season_weight is 0: there is no season term to scale"


def season_of(
    spec: Mapping[str, Any], tier: str, knobs: Mapping[str, Any]
) -> tuple[str, float, tuple[str, ...]]:
    """An arm's guard and stake from its spec (the guard PR), each at its default when the spec
    names none (None is not a name), and which of the two it names. Refused by name
    (ValueError): a guard out of :data:`GUARDS`; a guard named on the ranking tier or a static
    seat, which have none; a stake that is not a number from 0 to 1; a stake above 0 with
    ``season_weight`` 0, which scales nothing."""
    guard, stake = spec.get("guard"), spec.get("stake")
    named = tuple(k for k, v in zip(SEASON_FIELDS, (guard, stake), strict=True) if v is not None)
    if guard is None:
        guard = BLOCK
    elif guard not in GUARDS:
        raise ValueError(f"guard {guard!r}: one of {', '.join(GUARDS)}")
    elif tier not in GUARDED_TIERS:
        where = "the ranking tier has" if tier == "ranking" else "a static seat has"
        raise ValueError(
            f"guard {guard!r} named on tier {tier!r}: {where} no season guard; the exact and "
            "the surrogate tiers search under one"
        )
    if stake is None:
        stake = 0.0
    elif (
        isinstance(stake, bool)
        or not isinstance(stake, int | float)
        or not math.isfinite(stake)
        or not 0 <= stake <= 1
    ):
        raise ValueError(f"stake {stake!r}: a number from 0 to 1")
    if stake > 0 and not float(knob(knobs, "season_weight")) > 0:
        raise ValueError(
            f"stake {stake:g} with season_weight 0: the stake scales the season term, and "
            "there is none to scale"
        )
    return str(guard), float(stake), named


def season_reads(arm: Configured, shape: Shape) -> dict[str, str]:
    """For each of the arm's two season fields, :data:`READ` or the reason it is not, as
    :func:`reads`: the guard on the tiers that search under one; the stake where there is a
    season weight to scale, on those tiers, in a league whose bracket is read. Neither is read
    through a mirror: a rival stays on the block with no stake."""
    out: dict[str, str] = {}
    if arm.tier in GUARDED_TIERS:
        out["guard"] = READ
        if not float(arm.knobs["season_weight"]) > 0:
            out["stake"] = NO_TERM
        elif not shape.bracket:
            out["stake"] = "the league has no bracket read"
        else:
            out["stake"] = READ
    elif arm.tier == "ranking":
        out["guard"] = NO_GUARD
        out["stake"] = "the ranking tier ranks by value times games and holds no odds"
    else:
        out["guard"] = out["stake"] = STATIC
    return {k: out[k] for k in SEASON_FIELDS}


def field_reads(arm: Configured, mirrored: bool = False) -> dict[str, str]:
    """For each of the arm's five fields, :data:`READ` or the reason it is not, as
    :func:`reads` (no field depends on the league's shape). ``guard_pool`` (PR pool) is the
    exact tier's alone, whatever it executes, and only while the arm's guard blocks: under
    ``guard: off`` (the guard PR) there is no guard to make a list, so the arm is the seat at
    0. A mirror rival is the surrogate, whose pool is ranked by value times games with no
    single swaps, so nothing reads it through a mirror."""
    odds = _odds(arm, mirrored)
    if odds:
        out = dict.fromkeys(("pool", "min_gain", "weeks_ahead"), READ)
    elif arm.tier == "ranking":
        out = {
            "pool": "the ranking tier takes the wire's best whatever its size",
            "min_gain": "the ranking tier needs only a gain",
            "weeks_ahead": (
                "the ranking tier counts this week's games, and its keep rule is the same over "
                "any two weeks or more"
            ),
        }
    else:
        out = dict.fromkeys(("pool", "min_gain", "weeks_ahead"), STATIC)
    if arm.tier == "surrogate" or mirrored:
        out["surrogate_days"] = READ
    elif arm.tier in ("exact", "ranking"):
        out["surrogate_days"] = f"the {arm.tier} tier decides every day"
    else:
        out["surrogate_days"] = STATIC
    if arm.tier in UNION_TIERS:
        out["guard_pool"] = READ if arm.guard == BLOCK else GUARD_OFF
    elif arm.tier == "surrogate":
        out["guard_pool"] = NO_SWAPS
    elif arm.tier == "ranking":
        out["guard_pool"] = NO_LIST
    else:
        out["guard_pool"] = STATIC
    return {k: out[k] for k in FIELDS}


# --------------------------------------------------------------------------- the executor
#: The autopilot's claim rules the executor mirrors in a waiver league (#172, PR Fa), by the
#: autopilot's own names (``season.autopilot``): a move skipped for one is not queued.
READD = "READD"
DROP_CLAIMED = "DROP_CLAIMED"
ALREADY_CLAIMED = "ALREADY_CLAIMED"
NO_ADDS = "NO_ADDS"


def due_by(state: SimState, add: int, tomorrow: date) -> date:
    """The latest day a plan's step of ``add`` may be dated to be queued today: tomorrow, or a
    claim's clear date (the autopilot places a claim step dated at or before the day it would
    clear when placed today, ``autopilot._today``)."""
    wait = state.waivers.get(add)
    return tomorrow if wait is None else max(tomorrow, wait.clears)


def queue(
    state: SimState,
    team: int,
    decision: Decision,
    daily_cap: int,
    limit: int | None,
    execute_plan: bool = False,
    spots: int | None = None,
    setup: Setup | None = None,
) -> SimState:
    """The moves of ``decision`` that may land tomorrow, within the day's cap and the week's
    adds: the set's in order, then the plan's steps due tomorrow when the arm executes plans
    (:func:`gathered`, the one place they are gathered; the names of who leaves when a held
    player comes back were made with the part of the same list that can land together,
    :func:`named`, and the ones that match ``execute_plan`` are kept for the morning).
    Under the queue's rule (PR E) a plan that leads (``decision.plan_leads``) is queued instead
    of the set: its steps due tomorrow (:func:`due_by`), in the plan's order, and none of the
    set's moves, whatever ``execute_plan``; a later step is not queued early, and the seat draws
    its plan again tomorrow.
    With them the held-slot moves those moves need: the decision's, in order, one for each kept
    add that needs an active spot (no drop, or a churn's held drop) beyond the spots open today
    (``spots`` less the active roster; none when ``spots`` is None), as the engine pairs them.

    In a waiver league (``setup.waiting``, #172, PR Fa) a move whose add is on waivers is a claim
    (:class:`state.Claim`): placed today, decided on his clear date. The executor mirrors the
    autopilot's claim rules (``autopilot.queue_of``): a claim on a player this team dropped and
    who still waits (``READD``), a move whose drop an open claim of the team already takes
    (``DROP_CLAIMED``), a second claim on one add (``ALREADY_CLAIMED``) and a claim whose week has
    no add left, the claims in flight counted (``NO_ADDS``) are not queued. A claim is charged to
    the week of the day before it lands, and a free agent's add to this week, which counts the
    claims in flight charged to it. The spots open today are net of the claims in flight that
    will take one; a claim that needs a spot beyond them takes the next of the decision's
    held-slot moves, made only if it is won; a churn's claim's held drop leaves on his own
    tomorrow morning (``pending_drops``).

    In a FAAB league (``setup.bidding``, PR Fb) each claim placed carries its sealed bid, set now
    on the team's dollars left today (open bids are not taken out, as live clamps to the budget
    Yahoo reports): by the live rule for a decision whose :class:`Basis` says so (:func:`live_bid`
    on the typical gain of the moves the seat recommended over the fortnight, today's
    counted, as the live queue: the three weeks' set's, also on a day a plan leads), by the
    market's rule for a market rival (:func:`rival_bid` on
    the market rivals' typical gain over the fortnight before today, or with ``rival_bids``
    ``book``, PR Fd, ``bids.book_bid`` on the book at its move's rank among the market rivals'
    moves of that fortnight), and $0 for a decision without a basis. A free agent's add carries
    no bid. A seat whose arm names a ``bid`` block (PR F2, :func:`with_bid`) bids by the family
    (``bid_policy.amount``) on what its manager sees that day (:func:`bid_seen`), a pace read on
    the morning the claim is decided; every claim of a seat that bids by the live rule or the
    family carries its value in typicals (``Claim.value``), which no decision reads.

    Under continuous waivers (``setup.continuous``, PR Fc) every add is a claim: on a player
    nobody dropped lately it clears tomorrow, on a dropped player on his clear date, by the same
    rules; nothing is queued to land as a free agent."""
    tomorrow = state.day + timedelta(1)
    # What the seat means to queue (:func:`gathered`): under the queue's rule a leading plan's
    # steps and none of the set's moves. The set's gains stay the day's recommended moves' for
    # the fortnight's typical gain (below).
    moves, due = gathered(decision, execute_plan, lambda add: due_by(state, add, tomorrow))
    basis = decision.basis if setup is not None and setup.bidding else None
    if basis is None or decision.plan_leads:
        scaled = [0.0] * len(moves)
    else:
        scaled = list(basis.gains)
    # The set's moves gathered: ``moves[i]`` below it is the decision's move ``i``, and from it
    # on a plan's step (every one when a plan leads). What the bid policy is told (PR F2): a
    # step keeps today's value, and never reads the set's gains on the week or the season.
    of_set = len(moves)
    moves += [m for m, _ in due]
    scaled += [basis.plan[j] if basis is not None and basis.plan else 0.0 for _, j in due]
    waiting = setup is not None and setup.waiting
    continuous = setup is not None and setup.continuous
    used = int(state.adds_used.get(team, 0))
    mine = state.claims.get(team, ()) if waiting else ()
    this = setup.week_of(state.day) if waiting and setup is not None else None
    claimed_adds = {c.move.add for c in mine}
    claimed_drops = {c.move.drop for c in mine if c.move.drop is not None}
    held_keys = {k for k, _ in state.held(team)}
    kept: list[mv.Move] = []
    placed: list[Claim] = []
    seen_adds: set[int] = set()

    def charged(week: int | None) -> int:
        """The adds charged to ``week``: the claims in flight and placed today charged to it,
        and in this week the adds made and the free agents queued today."""
        n = sum(1 for c in (*mine, *placed) if c.week == week)
        if this is not None and week == this.number:
            n += used + len(kept)
        return n

    recent, market_recent = state.recent, state.market_recent
    dollars = int(state.dollars.get(team, 0))
    gains: list[float] = []
    # The bid policy's (PR F2): the seat's three weeks' typical, and its fortnight and typicals
    # on the other horizons its policy weighs.
    typical = 0.0
    recent_by, typicals = state.recent_by, {}
    if basis is not None and basis.rule == LIVE:
        # The seat's fortnight, today's recommended moves counted (the live queue's typical gain
        # is over the days ``today - TYPICAL_DAYS < day <= today``).
        since = state.day - timedelta(TYPICAL_DAYS)
        own = tuple((d, x) for d, x in state.recent.get(team, ()) if d > since)
        own += tuple((state.day, x) for x in basis.gains)
        recent = {**state.recent, team: own}
        gains = [x for _, x in own]
        typical = typical_gain(gains, basis.floor)[0]
        recent_by, typicals = fortnight_by(state, team, basis)
    elif basis is not None and basis.rule == MARKET:
        since = state.day - timedelta(RIVAL_BIDS.days)
        market_recent = tuple((d, x) for d, x in state.market_recent if d > since)
        market_recent += tuple((state.day, x) for x in basis.gains)

    def bid(i: int, clears: date) -> tuple[int, float]:
        """The sealed bid of the claim of ``moves[i]``, decided on ``clears``, and the claim's
        value in typicals (PR F2; 0 for a seat that holds none)."""
        assert setup is not None
        if basis is None:
            return 0, 0.0
        gain = scaled[i]
        if basis.rule == LIVE:
            # The bid policy (PR F2). An arm that names no ``bid`` bids by the live rule itself.
            at = i if i < of_set else None
            seen = bid_seen(setup, state, team, basis, typical, typicals, at, gain, clears)
            worth = bp.value(basis.bid or bp.DEFAULT, seen)
            if basis.bid is None:
                return live_bid(gain, gains, basis.floor, dollars, basis.sizing), worth
            return bp.amount(basis.bid, seen), worth
        if setup.rival_bids == BOOK:
            on_book = bids.book_bid(
                gain,
                state.market_recent,
                state.day,
                dollars,
                setup.rival_scale,
                setup.budget,
                basis.noise[i],
                setup.rival_prices,
                RIVAL_BIDS.days,
                RIVAL_BIDS.least,
            )
            return on_book, 0.0
        usual = market_typical(state.market_recent, state.day, gain)
        return rival_bid(gain, usual, dollars, setup.rival_scale, basis.noise[i]), 0.0

    for i, m in enumerate(moves):
        if len(kept) + len(placed) >= max(0, daily_cap):
            break
        wait = state.waivers.get(m.add) if waiting else None
        if wait is None and not continuous:
            full = used + len(kept) if this is None else charged(this.number)
            if limit is not None and full >= limit:
                continue
            if m.add in seen_adds or m.add not in state.pool:
                continue
            if m.drop is not None and m.drop in claimed_drops:
                continue  # DROP_CLAIMED
            seen_adds.add(m.add)
            kept.append(mv.Move(m.add, m.drop))
            continue
        if wait is None and m.add not in state.pool:
            continue  # under continuous waivers: an add not in the pool (a team holds him)
        if wait is not None and wait.by == team:
            continue  # READD: his own drop, still waiting
        if m.add in claimed_adds or m.add in seen_adds:
            continue  # ALREADY_CLAIMED
        if m.drop is not None and m.drop in claimed_drops:
            continue  # DROP_CLAIMED
        assert setup is not None
        # A dropped player's claim is decided on his clear date; under continuous waivers one on
        # a player nobody dropped lately the next morning.
        clears = tomorrow if wait is None else wait.clears
        week = setup.week_of(max(tomorrow, clears) - timedelta(1))
        number = None if week is None else week.number
        if limit is not None and number is not None and charged(number) >= limit:
            continue  # NO_ADDS
        seen_adds.add(m.add)
        claimed_adds.add(m.add)
        if m.drop is not None:
            claimed_drops.add(m.drop)
        churn = m.drop is not None and m.drop in held_keys
        placed.append(
            Claim(mv.Move(m.add, m.drop), state.day, clears, number, (), churn, *bid(i, clears))
        )
    pending = dict(state.pending)
    pending[team] = tuple(kept)
    # Whom the seat's returning held players send (PR G), for tomorrow morning alone: the
    # names made with what was gathered above made (:func:`named`, PR E), the plan's steps
    # beside the set when the arm executes its plan.
    names = decision.sends
    if execute_plan and decision.plan_sends is not None:
        names = decision.plan_sends
    sends = {t: x for t, x in state.sends.items() if t != team}
    if names:
        sends[team] = names
    need = sum(1 for m in kept if m.drop is None or m.drop in held_keys)
    free = 0
    if spots is not None:
        # The claims in flight that will take an open spot, carrying no held-slot move.
        taking = sum(1 for c in mine if c.needs_spot and not c.held)
        free = max(0, spots - len(state.active(team)) - taking)
        need -= free
    pending_held = dict(state.pending_held)
    pending_held[team] = tuple(decision.held[: max(0, need)])
    if not waiting:
        return replace(state, pending=pending, pending_held=pending_held, sends=sends)
    rest = list(decision.held[max(0, need) :])
    left = max(0, free - sum(1 for m in kept if m.drop is None or m.drop in held_keys))
    claims_out: list[Claim] = []
    for c in placed:
        if c.needs_spot:
            if left > 0:
                left -= 1
            elif rest:
                c = replace(c, held=(rest.pop(0),))
        claims_out.append(c)
    claims = dict(state.claims)
    claims[team] = (*mine, *claims_out)
    drops = dict(state.pending_drops)
    drops[team] = tuple(c.move.drop for c in claims_out if c.churn and c.move.drop is not None)
    counts = {t: dict(c) for t, c in state.claim_counts.items()}
    if claims_out:
        own = counts.setdefault(team, {})
        own["placed"] = own.get("placed", 0) + len(claims_out)
    return replace(
        state,
        pending=pending,
        pending_held=pending_held,
        claims=claims,
        pending_drops=drops,
        claim_counts=counts,
        recent=recent,
        market_recent=market_recent,
        recent_by=recent_by,
        sends=sends,
    )


def _active_count(roster: Sequence[tuple[int, str]]) -> int:
    return sum(1 for _, slot in roster if slot not in mv.HELD)


def _activate(
    roster: list[tuple[int, str]],
    spots: int | None,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
    named: Mapping[int, int] | None = None,
) -> list[int]:
    """A team's held players whose status no longer fits their slot (``moves.is_cleared``) come
    back to the bench; then, while the active roster is over ``spots``, a player leaves for
    each. A seat that plans with the engine names who (``named``, PR G: the returning player to
    the drop its plan charged him, :func:`sends_of`), and the world only checks it: the named
    player leaves when he is still one of the team's active players, the returning player
    himself when the plan named him. With no name, or one who is not on the roster (he has
    left, or he is an add of the seat's that lands after this), and for every seat that names
    none (a static, a market or a ranking seat), the rule before PR G: the least valuable active
    player by ``value`` leaves, the returning player included, a tie broken as the engine breaks
    it. The world reads no knob and no keep rule here: both reach the morning only through the
    seat's own choice. It does not read the team's queue either, and need not for a named
    player: the names are made with the queue made (:func:`named`, PR E), so none is the drop
    of a move queued for this morning. The rule before is blind to the queue as it always was:
    the player it sends can be a queued move's drop, and that move then finds its drop gone
    (:func:`land`). The players who left."""
    back: list[int] = []
    for i, (k, slot) in enumerate(roster):
        if slot in mv.HELD and mv.is_cleared(status.get(k), slot):
            roster[i] = (k, BENCH)
            back.append(k)
    out: list[int] = []
    for k in back:
        if spots is None or _active_count(roster) <= spots:
            break
        drop = (named or {}).get(k)
        at = next(
            (i for i, (pk, slot) in enumerate(roster) if pk == drop and slot not in mv.HELD), None
        )
        if drop is not None and at is not None:
            del roster[at]
            out.append(drop)
    # The whole active roster is weighed, the returning player included. A tie on value breaks
    # as the engine's does, by the id as text (#172, PR D4c: 10 before 9).
    while spots is not None and _active_count(roster) > spots:
        weakest = min(
            (k for k, slot in roster if slot not in mv.HELD),
            key=lambda k: (value.get(k, 0.0), str(k)),
        )
        roster.remove(next(x for x in roster if x[0] == weakest))
        out.append(weakest)
    return out


def _leaves(
    pool: set[int],
    waivers: dict[int, Waiting],
    waiver: tuple[date, int] | None,
    k: int,
    team: int,
) -> None:
    """``k`` leaves ``team``'s roster for the wire: on waivers in a waiver league."""
    pool.add(k)
    if waiver is not None:
        waivers[k] = Waiting(waiver[0] + timedelta(waiver[1]), team)


def arrive(
    state: SimState,
    order: Sequence[int],
    spots: int | None = None,
    status: Mapping[int, str | None] | None = None,
    value: Mapping[int, float] | None = None,
    values: Mapping[int, Mapping[int, float]] | None = None,
    waiver: tuple[date, int] | None = None,
) -> SimState:
    """The first half of the morning (:func:`land`'s first steps), team by team in ``order``:
    given the day's ``status`` and ``value`` (a team's own in ``values`` when it has one there:
    its seat's forecaster's), each team's cleared held players come back and the active roster
    is trimmed to ``spots`` (:func:`_activate`: the player its seat named for the returning one
    yesterday, ``state.sends``, PR G, when he is still active there, else the least valuable;
    each player it sends counts in the team's ``forced_by``, never in ``executed_by`` or
    ``gone_by``); then the held players the churns' claims drop (``pending_drops``) leave, on
    their own, as a churn's held drop does. Every player who leaves goes on waivers until
    ``waiver``'s day plus its days (None without waivers). The names are yesterday's and are
    spent here, used or not.

    In a waiver league the runner calls it before the morning's claims are decided
    (:func:`clear_waivers`, #172, Fc's review): a claim then meets the roster its team has that
    morning, so a cleared held player's trim cannot take the player just claimed, and a churn's
    claim finds the slot its held player leaves. Then :func:`land` makes the rest with
    ``arrived``. Without a held slot nothing here moves: no held player comes back and no
    roster is over its spots."""
    rosters = {t: list(r) for t, r in state.rosters.items()}
    pool = set(state.pool)
    forced = dict(state.forced_by)
    waivers = dict(state.waivers)
    for team in order:
        roster = rosters.setdefault(team, [])
        own = (values or {}).get(team, value)
        if status is not None and own is not None:
            left = _activate(roster, spots, status, own, dict(state.sends.get(team, ())))
            for k in left:
                _leaves(pool, waivers, waiver, k, team)
            if left:
                forced[team] = forced.get(team, 0) + len(left)
        for k in state.pending_drops.get(team, ()):
            idx = next((i for i, (pk, s) in enumerate(roster) if pk == k and s in mv.HELD), None)
            if idx is not None:
                del roster[idx]
                _leaves(pool, waivers, waiver, k, team)
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(pool),
        forced_by=forced,
        waivers=waivers,
        pending_drops={},
        sends={},
    )


def land(
    state: SimState,
    order: Sequence[int],
    spots: int | None = None,
    slot_counts: Mapping[str, int] | None = None,
    status: Mapping[int, str | None] | None = None,
    value: Mapping[int, float] | None = None,
    values: Mapping[int, Mapping[int, float]] | None = None,
    waiver: tuple[date, int] | None = None,
    arrived: bool = False,
) -> SimState:
    """Yesterday's queued moves land, team by team in ``order``. First (:func:`arrive`, unless
    ``arrived`` says the runner made it before the morning's claims), given the day's ``status``
    and ``value`` (a team's own in ``values`` when it has one there: its seat's forecaster's),
    each team's cleared held players come back and the active roster is trimmed to ``spots``
    (:func:`_activate`; each player it sends counts in the team's ``forced_by``, never in
    ``executed_by`` or ``gone_by``), and the held players the churns' claims drop leave. Then a
    churn's held drop goes to the pool on his
    own, as the engine times it (#221), freeing his slot; then the held-slot moves it queued,
    each player to his held slot while the slot has room (``slot_counts``, the league's slots by
    kind) and, given ``status``, only if the slot accepts the status he has that morning
    (``moves.eligible``, the engine's test): a move is carried out against the day it lands. One
    the slot does not accept is not made and counts in the team's ``held_refused_by``; he stays
    active and frees no spot. Then the adds: one with a drop of an active player takes his slot;
    one that needs an active spot (no drop, the churn's, or one whose held move was refused)
    takes a bench slot while the active roster is under ``spots`` and is otherwise gone, like an
    add another team took first (a churn's drop stands either way, made before the add; a plain
    swap's is never made). A swap whose drop is no longer an active player is gone too: he has
    left, or one of the morning's held-slot moves took him to a held slot (an arm that executes
    its plan beside its set can queue a step that drops the player its set moves there), and no
    add lands in a held slot; a claim meets the same test (:func:`clear_waivers`). Without
    ``spots`` nothing is counted.

    ``waiver`` (today and the league's waiver days, #172, PR Fa; None without waivers): every
    player who leaves a roster this morning (a forced drop, a churn's held drop, a swap's drop)
    goes on waivers until today plus the waiver days.

    Each team's first steps all come before any team's moves (they did team by team before
    Fc's review): no team's first steps read another's moves, so the order moves nothing."""
    if not arrived:
        state = arrive(state, order, spots, status, value, values, waiver)
    rosters = {t: list(r) for t, r in state.rosters.items()}
    pool = set(state.pool)
    adds_used = dict(state.adds_used)
    executed, gone = dict(state.executed_by), dict(state.gone_by)
    refused = dict(state.held_refused_by)
    waivers = dict(state.waivers)

    def count(by: dict[int, int], team: int, n: int = 1) -> None:
        if n:
            by[team] = by.get(team, 0) + n

    def leaves(k: int, team: int) -> None:
        _leaves(pool, waivers, waiver, k, team)

    for team in order:
        roster = rosters.setdefault(team, [])
        moves = state.pending.get(team, ())
        churned: set[int] = set()
        for m in moves:
            if m.drop is None:
                continue
            idx = next(
                (i for i, (pk, s) in enumerate(roster) if pk == m.drop and s in mv.HELD), None
            )
            if idx is not None:
                del roster[idx]
                leaves(m.drop, team)
                churned.add(m.drop)
        for k, slot in state.pending_held.get(team, ()):
            room = slot_counts is None or sum(1 for _, s in roster if s == slot) < slot_counts.get(
                slot, 0
            )
            idx = next(
                (i for i, (pk, s) in enumerate(roster) if pk == k and s not in mv.HELD), None
            )
            if idx is None:
                continue
            if status is not None and not mv.eligible(status.get(k), slot):
                count(refused, team)  # decided while out; the slot no longer takes him
            elif room:
                roster[idx] = (k, slot)
        for m in moves:
            if m.add not in pool:
                count(gone, team)
                continue
            idx = None
            if m.drop is not None and m.drop not in churned:
                # His drop must still be an active player. One who has left is not there to
                # swap, and neither is one a held-slot move above took to a held slot this
                # morning: the add would land in that slot (an arm that executes its plan
                # beside its set queues both, the set's held-slot move and the step).
                idx = next(
                    (i for i, (pk, s) in enumerate(roster) if pk == m.drop and s not in mv.HELD),
                    None,
                )
                if idx is None:
                    count(gone, team)
                    continue
            if idx is None:
                if spots is not None and _active_count(roster) >= spots:
                    count(gone, team)
                    continue
                slot = BENCH
            else:
                slot = roster[idx][1]
                leaves(roster[idx][0], team)
                del roster[idx]
            roster.append((m.add, slot))
            pool.discard(m.add)
            adds_used[team] = adds_used.get(team, 0) + 1
            count(executed, team)
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(pool),
        adds_used=adds_used,
        pending={},
        pending_held={},
        executed_by=executed,
        gone_by=gone,
        held_refused_by=refused,
        waivers=waivers,
    )


def clear_waivers(
    state: SimState,
    day: date,
    spots: int | None,
    slot_counts: Mapping[str, int] | None,
    status: Mapping[int, str | None],
    waiver_days: int,
    bidding: bool = False,
) -> SimState:
    """The morning of ``day`` in a waiver league (#172, PR Fa), once the cleared held players are
    back, the rosters trimmed and the churns' held players gone (:func:`arrive`, Fc's review) and
    before anything else lands: the claims on every player whose clear date has come are decided
    by rolling priority. The team
    with the best priority (``state.priority``, best first) that still has a claim open this
    morning takes its first open claim (in the order it placed them). Its roster takes the
    player when the claim's drop is still on its active roster, or, for an open-spot claim, when
    an active spot
    is open once the claim's held-slot moves are made (each while its slot has room and accepts
    the player's status this morning, ``moves.eligible``, else refused): the claim is won, the
    held-slot moves and the drop are made, the add lands (charged to the week of the day before,
    as a move made yesterday) and the team goes to the back of the order; every other claim on
    that player is lost, its drop and held-slot moves never made. A won claim the roster cannot
    take fails, counted apart from a lost one and among the moves gone, nothing of it made; the
    team keeps its place and the player goes to the next claim on him (Yahoo skips a claim it
    cannot process). Repeat until no claim is open. A player whose claims are all decided and
    who went to nobody is a free agent from this morning. A player who leaves a roster here goes
    on waivers until ``day`` plus ``waiver_days``. ``resolved`` is this morning's decisions in
    the order made, each with whether a team stood ahead of its team in the order when its
    player was decided; the claim counts (``state.CLAIM_COUNTS``) follow.

    In a FAAB league (``bidding``, PR Fb) the claims on the players clearing this morning go one
    at a time, the highest bid first, a tie by waiver priority (best first) and a team's own by
    the order it placed them: a claim whose player is gone is lost; one whose team's dollars left
    are below its bid, or whose roster cannot take the player, fails; else it is won, its team
    pays exactly its bid, and the claim is made as above. The order rolls only when the win broke
    a tie (another claim open on the player with the same bid): the winner goes to the back. A
    claim decided after another on its player failed counts as behind; a lost one always does.
    The bid counts (``state.BID_COUNTS``) follow.

    Under continuous waivers (PR Fc) a claim on a player nobody dropped lately is due the morning
    after it is placed (its ``clears``), and it is decided here, in the same pass and by the same
    rules as the claims on the players whose wait ends this morning: one morning, one way to
    decide. With the rule not named every claim is on a player on waivers whose clear date is
    its own, so the players due are those clearing, as before."""
    clearing = {k for k, w in state.waivers.items() if w.clears <= day}
    due = clearing | {c.move.add for cs in state.claims.values() for c in cs if c.clears <= day}
    if not due:
        return replace(state, resolved=()) if state.resolved else state
    rosters = {t: list(r) for t, r in state.rosters.items()}
    pool, waivers = set(state.pool), dict(state.waivers)
    adds_used = dict(state.adds_used)
    executed, gone = dict(state.executed_by), dict(state.gone_by)
    refused = dict(state.held_refused_by)
    counts = {t: dict(c) for t, c in state.claim_counts.items()}
    order = list(state.priority)
    open_: dict[int, list[Claim]] = {
        t: [c for c in cs if c.move.add in due] for t, cs in state.claims.items()
    }
    claims = {t: tuple(c for c in cs if c.move.add not in due) for t, cs in state.claims.items()}
    log: list[Resolved] = []

    def tally(team: int, outcome: str, behind: bool) -> None:
        own = counts.setdefault(team, {})
        own[outcome] = own.get(outcome, 0) + 1
        if behind:
            own["behind"] = own.get("behind", 0) + 1
            if outcome == LOST:
                own["behind_lost"] = own.get("behind_lost", 0) + 1

    def takes(team: int, c: Claim) -> list[tuple[int, str]] | None:
        """The held-slot moves to make if ``team``'s roster can take ``c``; None if it cannot."""
        roster = rosters.setdefault(team, [])
        if not c.needs_spot:
            here = any(pk == c.move.drop and s not in mv.HELD for pk, s in roster)
            return [] if here else None
        made: list[tuple[int, str]] = []
        for k, slot in c.held:
            active = any(pk == k and s not in mv.HELD for pk, s in roster)
            used = sum(1 for _, s in roster if s == slot) + sum(1 for _, s in made if s == slot)
            room = slot_counts is None or used < slot_counts.get(slot, 0)
            if active and room and mv.eligible(status.get(k), slot):
                made.append((k, slot))
        if spots is not None and _active_count(roster) - len(made) >= spots:
            return None
        return made

    def make(team: int, c: Claim, made: list[tuple[int, str]]) -> None:
        """``team`` wins ``c``: its held-slot moves that can be made, its drop, its add."""
        add, drop = c.move.add, c.move.drop
        roster = rosters[team]
        for k, slot in c.held:
            i = next((i for i, (pk, s) in enumerate(roster) if pk == k and s not in mv.HELD), None)
            if (k, slot) in made and i is not None:
                roster[i] = (k, slot)
            elif i is not None and not mv.eligible(status.get(k), slot):
                refused[team] = refused.get(team, 0) + 1  # placed while out; not taken now
        slot = BENCH
        if not c.needs_spot:
            i = next(i for i, (pk, _) in enumerate(roster) if pk == drop)
            slot = roster[i][1]
            del roster[i]
            pool.add(drop)
            waivers[drop] = Waiting(day + timedelta(waiver_days), team)
        roster.append((add, slot))
        pool.discard(add)
        waivers.pop(add, None)
        adds_used[team] = adds_used.get(team, 0) + 1
        executed[team] = executed.get(team, 0) + 1

    dollars = dict(state.dollars)
    # A FAAB league's (PR F2): the season's winning bids, which every manager sees, and each
    # team's value won.
    won_bids, value_won = list(state.won_bids), dict(state.value_won)
    while not bidding:
        team = next((t for t in order if open_.get(t)), None)
        if team is None:
            break
        c = open_[team].pop(0)
        add, drop = c.move.add, c.move.drop
        behind = order.index(team) > 0
        made = takes(team, c)
        if made is None:
            log.append(Resolved(team, add, drop, FAILED, behind))
            tally(team, FAILED, behind)
            gone[team] = gone.get(team, 0) + 1
            continue
        make(team, c, made)
        log.append(Resolved(team, add, drop, WON, behind))
        tally(team, WON, behind)
        # Every other claim on him is lost: a team ahead of each, the winner.
        for t, cs in open_.items():
            for lost in [x for x in cs if x.move.add == add]:
                cs.remove(lost)
                log.append(Resolved(t, add, lost.move.drop, LOST, True))
                tally(t, LOST, True)
        order.remove(team)
        order.append(team)

    def bump(team: int, key: str, n: int = 1) -> None:
        own = counts.setdefault(team, {})
        own[key] = own.get(key, 0) + n

    def rank(team: int, c: Claim) -> tuple[int, int, int]:
        """A claim's place in the morning's line: its bid, its team's priority, its order."""
        return (c.bid, -order.index(team), -open_[team].index(c))

    # Each player's claims this morning, before any is decided: a win with no other is alone.
    bidders = Counter(c.move.add for cs in open_.values() for c in cs)
    tried: set[int] = set()  # the players a claim on whom has failed this morning
    while bidding:
        line = [(t, c) for t, cs in open_.items() for c in cs]
        if not line:
            break
        team, c = max(line, key=lambda tc: rank(*tc))
        add, drop = c.move.add, c.move.drop
        behind = add in tried
        made = takes(team, c) if dollars.get(team, 0) >= c.bid else None
        if made is None:
            open_[team].remove(c)
            log.append(Resolved(team, add, drop, FAILED, behind, c.bid))
            tally(team, FAILED, behind)
            gone[team] = gone.get(team, 0) + 1
            tried.add(add)
            continue
        others = sorted(
            ((t, x) for t, cs in open_.items() for x in cs if x.move.add == add and x is not c),
            key=lambda tx: rank(*tx),
            reverse=True,
        )
        # The next bid on him that could have been taken: its team could pay it and take him.
        after = next(
            (x.bid for t, x in others if dollars.get(t, 0) >= x.bid and takes(t, x) is not None),
            None,
        )
        tie = any(x.bid == c.bid for _, x in others)
        open_[team].remove(c)
        make(team, c, made)
        dollars[team] = dollars.get(team, 0) - c.bid
        won_bids.append((day, team, c.bid))
        value_won[team] = value_won.get(team, 0.0) + c.value
        log.append(Resolved(team, add, drop, WON, behind, c.bid))
        tally(team, WON, behind)
        bump(team, "won_free", int(c.bid == 0))
        bump(team, "alone", int(bidders[add] == 1))
        bump(team, "over", c.bid - (after or 0))
        for t, lost in others:
            open_[t].remove(lost)
            log.append(Resolved(t, add, lost.move.drop, LOST, True, lost.bid))
            tally(t, LOST, True)
            bump(t, "lost_tie" if lost.bid == c.bid else "lost_bid")
            bump(t, "short", c.bid - lost.bid)
        if tie:
            order.remove(team)
            order.append(team)
    for k in clearing:
        waivers.pop(k, None)  # nobody took him: a free agent from this morning
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(pool),
        waivers=waivers,
        claims={t: cs for t, cs in claims.items() if cs},
        adds_used=adds_used,
        executed_by=executed,
        gone_by=gone,
        held_refused_by=refused,
        priority=tuple(order),
        resolved=tuple(log),
        claim_counts=counts,
        dollars=dollars,
        won_bids=tuple(won_bids),
        value_won=value_won,
    )


def new_week(state: SimState) -> SimState:
    """Monday: the adds used this week start over."""
    return replace(state, adds_used={})


def seed_round(setup: Setup, state: SimState, week: int) -> SimState:
    """The bracket's round of ``week`` seeded on the state (#172, PR bracket): its pairs as the
    league gives them from the state's own totals (``league.round_pairs``: the season's own
    bracket on the weeks finished before the round), kept under the week's number in
    ``SimState.seeded``. The runner calls it each morning before the day's decisions; it seeds a
    round once, on the first day the state does not hold it, and leaves the state as it is in a
    week that is no round's and in a league whose bracket is not read. So no pair reads a total
    of its own week (no peek), and two arms whose seasons differ seed their own."""
    spec = setup.spec
    if spec is None or week in state.seeded or week not in round_weeks(spec):
        return state
    return replace(state, seeded={**state.seeded, week: round_pairs(spec, state.totals, week)})


# --------------------------------------------------------------------------- the day's lineup
def starters_of(
    setup: Setup,
    state: SimState,
    team: int,
    day: date,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
) -> dict[int, str]:
    """The day's starters as a lineup set before the games: the active players whose team plays
    today and whom the policy has not heard are out, the most valuable set the slots hold."""
    playing = [
        (k, setup.players[k].positions)
        for k in state.active(team)
        if k in setup.players
        and setup.players[k].nba_team in setup.schedule.get(day, frozenset())
        and status.get(k) not in wk.OUT_ALL
        and status.get(k) not in wk.OUT_THIS_WEEK
    ]
    return wk.starters(playing, setup.starting_slots(), value)


def score_day(
    setup: Setup,
    state: SimState,
    day: date,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
    line: Callable[[int, date], Mapping[str, float] | None],
    starters: Mapping[int, Mapping[int, str]] | None = None,
    values: Mapping[int, Mapping[int, float]] | None = None,
) -> SimState:
    """Every team's starters' lines added to the week's totals; a starter without a line (out at
    game time, unheard) adds nothing. ``starters`` is the day's lineup by team when it is already
    set (:func:`starters_of` of the same state, status and value); else it is set here, on the
    team's own value in ``values`` when it has one there (its seat's forecaster's)."""
    week = setup.week_of(day)
    if week is None:
        return state
    for team in setup.teams:
        lineup = (
            starters[team]
            if starters is not None and team in starters
            else starters_of(setup, state, team, day, status, (values or {}).get(team, value))
        )
        for k in lineup:
            ln = line(k, day)
            if ln:
                state = add_totals(
                    state, week.number, team, {s: x for s, x in ln.items() if s != "minutes_factor"}
                )
    return state
