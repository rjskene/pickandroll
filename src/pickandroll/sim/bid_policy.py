"""The seat's bid policy (#172, PR F2): a family of FAAB bid rules whose default member is the
live rule.

An arm's spec may name ``bid``, a mapping (:func:`of`); every key is optional and defaults to
today's rule (``autopilot.bid_of`` with no flag, which ``tests/sim/test_sim_bid_policy.py`` holds
the default member to, through the door). The family, in order (:func:`amount`):

1. **The value**, in typicals (:func:`value`): the move's gain over the seat's typical gain on
   each horizon, weighed ``week``, ``season`` and the rest on the three weeks. A horizon with no
   typical yet (the week and the season, before the seat's tenth move), or whose typical is at
   or below 0, counts a move that gains as typical (ratio 1, ``bid_of``'s base of 1 on the three
   weeks) and one that gains nothing or less as nothing (ratio 0): a claim worth nothing never
   rides the pace. A plan's step keeps today's value, its week increment over the three weeks'
   typical: no weight applies.
2. **The pace** (:func:`pace`): ``((left / start) / path) ** k``, the seat's share of the budget
   left over a spending path (:func:`path`), so a seat ahead of the path bids up and one behind
   it bids down. Where the path is 0 the pace has no bound (``math.inf``), and neither has one
   whose power, or whose product with the value, is beyond a float.
3. **The base** is the value times the pace, rounded half up. At 1 or less the claim is routine
   and bids ``routine`` dollars.
4. Otherwise the amount is the base times ``faab_sizing``, rounded half up; with no bound on the
   pace, what is left for a claim worth more than nothing, and the routine for any other.
5. **The rival cap**, when on: at most the richest other team's dollars left, plus one.
6. **The shade**, when named: at most the ``q`` quantile of the other teams' winning bids of the
   season so far, plus one, once ``least`` of them are seen.
7. The clamp to the dollars left, last.

Items 5 and 6 refuse only dollars that cannot be needed to win; they are no ceiling on value.

**The walls.** The function takes the arm's block and one frozen value, :class:`Seen`: what a
manager sees when a claim is placed (the seat's own dollars, every other team's dollars left, the
other teams' winning bids to date, the calendar, the move's gains and the seat's own typicals),
and nothing else. No sealed bid, no losing bid, nothing of the rivals' bid model, nothing of a
later day. Pure: no I/O, no generator, no import from the engine or from ``sim.bids``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

#: The keys of an arm's ``bid`` block, in the order the payload names them; any other is refused
#: by name (:func:`of`).
KEYS = ("week", "season", "pace", "routine", "rival_cap", "shade")
PACE_KEYS = ("k", "shape", "reserve")
SHADE_KEYS = ("q", "least")
#: The horizons a move's value is weighed over beside the three weeks: the keys of
#: ``SimState.recent_by`` and the names of the block's two weights.
WEEK, SEASON = "week", "season"
#: What a routine claim may bid, in dollars.
ROUTINES = (0, 1)
#: The places a figure made with a power is rounded to before it decides anything: the last bit
#: of a power differs between machines.
PLACES = 9


@dataclass(frozen=True)
class Pace:
    """The pace's three figures: ``k``, how hard the bid follows the path (0: not at all);
    ``shape``, the path's curve over the regular season (1: a straight line); ``reserve``, the
    share of the budget the path still holds on the first day of the bracket."""

    k: float
    shape: float
    reserve: float

    def payload(self) -> dict[str, Any]:
        return {"k": self.k, "shape": self.shape, "reserve": self.reserve}


@dataclass(frozen=True)
class Shade:
    """The shade's two figures: ``q``, the quantile of the other teams' winning bids, and
    ``least``, how many of them must be seen before it binds."""

    q: float
    least: int

    def payload(self) -> dict[str, Any]:
        return {"q": self.q, "least": self.least}


@dataclass(frozen=True)
class BidPolicy:
    """An arm's ``bid`` block, every key at today's rule by default. Part of a seat's ``repr``,
    so two seats that differ in it never share a decision."""

    week: float = 0.0
    season: float = 0.0
    pace: Pace | None = None
    routine: int = 0
    rival_cap: bool = False
    shade: Shade | None = None

    @property
    def three(self) -> float:
        """The three weeks' weight: the rest, and never a rounded negative zero (a run prints
        it)."""
        return max(0.0, round(1.0 - self.week - self.season, PLACES))

    def bids(self) -> BidPolicy:
        """The block as it bids: itself with what it never reads taken out. A pace at ``k`` 0
        follows no path whatever its ``shape`` and ``reserve`` (:func:`pace`), so it is no
        pace. Two blocks with one such form bid alike on every claim (``run.same_seat``); the
        payload keeps the block as named."""
        if self.pace is not None and self.pace.k == 0:
            return replace(self, pace=None)
        return self

    def payload(self) -> dict[str, Any]:
        """Every key with its value in force."""
        return {
            "week": self.week,
            "season": self.season,
            "pace": None if self.pace is None else self.pace.payload(),
            "routine": self.routine,
            "rival_cap": self.rival_cap,
            "shade": None if self.shade is None else self.shade.payload(),
        }

    def label(self) -> str:
        """The block in words, for a run's output."""
        pace, shade = self.pace, self.shade
        return ", ".join(
            (
                f"week {self.week:g}",
                f"season {self.season:g}",
                f"the three weeks {self.three:g}",
                "no pace"
                if pace is None
                else f"pace k {pace.k:g} shape {pace.shape:g} reserve {pace.reserve:g}",
                f"a routine claim ${self.routine}",
                "the rival cap on" if self.rival_cap else "no rival cap",
                "no shade"
                if shade is None
                else f"shade at the {shade.q:g} quantile once {shade.least} are seen",
            )
        )


#: Today's rule: the default member.
DEFAULT = BidPolicy()


def _number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def _whole(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _mapping(x: Any) -> bool:
    return isinstance(x, Mapping)


def _block(name: str, spec: Any, keys: tuple[str, ...]) -> Mapping[str, Any]:
    """``bid``'s sub-block ``name`` as given: a mapping that names every one of ``keys`` and no
    other (ValueError by name)."""
    if not _mapping(spec):
        raise ValueError(f"bid {name} {spec!r}: a mapping of {', '.join(keys)}, or none")
    unknown = [k for k in spec if k not in keys]
    if unknown:
        raise ValueError(f"bid {name} key {unknown[0]!r} is not one of {keys}")
    missing = [k for k in keys if k not in spec]
    if missing:
        raise ValueError(f"bid {name} names {', '.join(keys)}: {missing[0]!r} is missing")
    return spec


def of(spec: Any) -> BidPolicy:
    """An arm's bid policy from its spec's ``bid`` block, each key at its default when the block
    names none. An unknown key or a bad value is refused by name (ValueError): ``week`` and
    ``season`` numbers from 0 to 1 whose sum is at most 1; ``pace`` none or ``k`` (0 or more),
    ``shape`` (above 0) and ``reserve`` (0 or more, below 1), all three; ``routine`` 0 or 1;
    ``rival_cap`` true or false; ``shade`` none or ``q`` (above 0, at most 1) and ``least`` (a
    whole number, 1 or more), both."""
    if not _mapping(spec):
        raise ValueError(f"bid {spec!r}: a mapping of {', '.join(KEYS)}, each optional")
    unknown = [k for k in spec if k not in KEYS]
    if unknown:
        raise ValueError(f"bid key {unknown[0]!r} is not one the simulator reads: one of {KEYS}")
    week, season = spec.get("week", 0.0), spec.get("season", 0.0)
    for name, x in (("week", week), ("season", season)):
        if not _number(x) or not 0 <= x <= 1:
            raise ValueError(f"bid {name} {x!r}: a number from 0 to 1")
    if round(week + season, PLACES) > 1:
        raise ValueError(
            f"bid week {week:g} and season {season:g}: their sum is at most 1 (the three weeks "
            "take the rest)"
        )
    pace = None
    if spec.get("pace") is not None:
        p = _block("pace", spec["pace"], PACE_KEYS)
        k, shape, reserve = p["k"], p["shape"], p["reserve"]
        if not _number(k) or k < 0:
            raise ValueError(f"bid pace k {k!r}: a number, 0 or more")
        if not _number(shape) or not shape > 0:
            raise ValueError(f"bid pace shape {shape!r}: a number above 0")
        if not _number(reserve) or not 0 <= reserve < 1:
            raise ValueError(f"bid pace reserve {reserve!r}: a number, 0 or more and below 1")
        pace = Pace(float(k), float(shape), float(reserve))
    routine = spec.get("routine", 0)
    if not _whole(routine) or routine not in ROUTINES:
        raise ValueError(f"bid routine {routine!r}: 0 or 1 dollars")
    cap = spec.get("rival_cap", False)
    if cap is not True and cap is not False:
        raise ValueError(f"bid rival_cap {cap!r}: true or false")
    shade = None
    if spec.get("shade") is not None:
        s = _block("shade", spec["shade"], SHADE_KEYS)
        q, least = s["q"], s["least"]
        if not _number(q) or not 0 < q <= 1:
            raise ValueError(f"bid shade q {q!r}: a number above 0 and at most 1")
        if not _whole(least) or least < 1:
            raise ValueError(f"bid shade least {least!r}: a whole number, 1 or more")
        shade = Shade(float(q), least)
    return BidPolicy(float(week), float(season), pace, routine, cap, shade)


# --------------------------------------------------------------------------- what a manager sees
@dataclass(frozen=True)
class When:
    """The calendar a pace reads: ``day``, the morning the claim is decided; ``first``, the
    season's first day; ``bracket``, the first day of the bracket's first week (the day after
    the season's last where no bracket is read: the whole season is regular); ``last``, the last
    morning a claim can be decided."""

    day: date
    first: date
    bracket: date
    last: date


@dataclass(frozen=True)
class Seen:
    """Everything the policy reads for one claim, and nothing else (the walls).

    ``gain`` and ``typical`` are the three weeks': the move's own gain to its set and the seat's
    typical gain of the fortnight, the plan floor until ten moves (for a plan's ``step``, the
    gain its claim bids on over the same typical: its week increment beside a set, its score
    under the queue's rule, PR E). ``week`` and ``season`` are the move's gain on the
    week and the season term's figure for it (None counts 0), with ``typical_week`` and
    ``typical_season`` the seat's typicals on them (``policy.fortnight_by``: the fortnight's
    median once it holds ten moves, else the median of the seat's last ten), None before its
    tenth move. ``dollars`` is the seat's own left and ``sizing`` its ``faab_sizing``;
    ``budget`` what every team started with; ``others`` every other team's dollars left;
    ``wins`` the other teams' winning bids of the season so far; ``when`` the calendar, read
    only by a pace."""

    gain: float
    typical: float
    dollars: float
    sizing: Any = None
    step: bool = False
    week: float | None = None
    typical_week: float | None = None
    season: float | None = None
    typical_season: float | None = None
    budget: int = 0
    others: tuple[int, ...] = ()
    wins: tuple[int, ...] = ()
    when: When | None = None


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _ratio(gain: float | None, typical: float | None) -> float:
    """A gain in typicals, a gain of None counting 0: the gain over the typical where the
    typical is above 0. With no typical yet, or one at or below 0, a gain above 0 counts as one
    typical (``bid_of``'s base of 1) and a gain of 0 or less as nothing: a claim worth nothing
    is worth nothing in every member, so it never rides a pace (the lead's working default,
    2026-11-19). The default member bids the routine on a base of 0 as on a base of 1."""
    g = 0.0 if gain is None else float(gain)
    if typical is not None and typical > 0:
        return g / typical
    return 1.0 if g > 0 else 0.0


def value(rule: BidPolicy, seen: Seen) -> float:
    """The claim's value in typicals: the three weeks' ratio at the default weights and for a
    plan's step; else each horizon's ratio by its weight, a weight of 0 reading nothing."""
    three = _ratio(seen.gain, seen.typical)
    if seen.step or (rule.week == 0 and rule.season == 0):
        return three
    out = rule.three * three if rule.three > 0 else 0.0
    if rule.week > 0:
        out += rule.week * _ratio(seen.week, seen.typical_week)
    if rule.season > 0:
        out += rule.season * _ratio(seen.season, seen.typical_season)
    return out


def path(pace_: Pace, when: When) -> float:
    """The share of the budget the spending path holds on ``when.day``: over the regular season
    ``reserve + (1 - reserve) x (1 - t) ** shape``, ``t`` the share of the regular season gone
    (0 on the first day, 1 on the first day of the bracket); from there a straight line from
    ``reserve`` to 0 on the last morning a claim can be decided, and 0 after it."""
    if when.day < when.bracket:
        span = (when.bracket - when.first).days
        t = min(1.0, max(0.0, (when.day - when.first).days / span)) if span > 0 else 1.0
        return round(pace_.reserve + (1.0 - pace_.reserve) * (1.0 - t) ** pace_.shape, PLACES)
    span, left = (when.last - when.bracket).days, (when.last - when.day).days
    if span <= 0 or left <= 0:
        return 0.0
    return round(pace_.reserve * min(left, span) / span, PLACES)


def pace(rule: BidPolicy, seen: Seen) -> float:
    """What the value is multiplied by: 1 with no pace named, at ``k`` 0 and in a league without
    a budget; else ``((left / start) / path) ** k``, rounded (:data:`PLACES`); ``math.inf``
    where the path is 0 (the pace has no bound)."""
    named = rule.pace
    if named is None or named.k == 0 or seen.budget <= 0:
        return 1.0
    if seen.when is None:
        raise ValueError("a pace reads the calendar: the claim's Seen names no When")
    on = path(named, seen.when)
    if on <= 0:
        return math.inf
    try:
        return round((max(0.0, float(seen.dollars)) / seen.budget / on) ** named.k, PLACES)
    except OverflowError:
        return math.inf


def quantile(wins: Sequence[int], q: float) -> int:
    """The least of ``wins`` at or below which a fraction ``q`` of them falls (no
    interpolation: a bid is whole dollars)."""
    ranked = sorted(wins)
    n = len(ranked)
    return ranked[min(n, max(1, math.ceil(round(q * n, PLACES)))) - 1]


def amount(rule: BidPolicy, seen: Seen) -> int:
    """The claim's bid in whole dollars under ``rule`` on what a manager sees (the module's
    list, in its order)."""
    v, p = value(rule, seen), pace(rule, seen)
    left = max(0, math.floor(seen.dollars))
    paced = v * p if math.isfinite(p) else math.inf
    if not math.isfinite(paced):
        # No bound: a claim worth more than nothing bids what is left, one worth nothing or
        # less the routine (on the same value as everywhere else). So too where the pace is a
        # float and its product with the value is beyond one.
        out = left if v > 0 else rule.routine
    else:
        base = _half_up(paced)
        sized = base * (1.0 if seen.sizing is None else float(seen.sizing))
        # A base whose product with the sizing is beyond a float is above any dollars left.
        out = rule.routine if base <= 1 else _half_up(sized) if math.isfinite(sized) else left
    if rule.rival_cap and seen.others:
        out = min(out, max(seen.others) + 1)
    if rule.shade is not None and len(seen.wins) >= rule.shade.least:
        out = min(out, quantile(seen.wins, rule.shade.q) + 1)
    return min(out, left)


__all__ = [
    "DEFAULT",
    "KEYS",
    "PACE_KEYS",
    "PLACES",
    "ROUTINES",
    "SEASON",
    "SHADE_KEYS",
    "WEEK",
    "BidPolicy",
    "Pace",
    "Seen",
    "Shade",
    "When",
    "amount",
    "of",
    "pace",
    "path",
    "quantile",
    "value",
]
