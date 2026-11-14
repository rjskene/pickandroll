"""The other eleven seats (#172, PR 2b): what each opponent does on a day.

The ladder from the design note. **Static** makes no move. **Market** is the heuristic: each day
with probability ``rate`` (adds per team-day, from the league's recorded transactions) it adds
the pool's best by the market's view and drops its weakest by the same view, within the caps.
**Mirror** runs the surrogate on the shared beliefs with the arm's knobs and fields (the arm
whole: at the defaults nothing changes). **Seat** is the equal room's: a named arm in another
seat, the same tiers the arm under test runs, with its fields. Each strategy is pure given the world's
draws (``run.World`` passes the day's generator), so two arms of a comparison see the same
opponents while their states agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np

from . import policy
from .engine import mv
from .state import Setup, SimState

KINDS = ("static", "market", "mirror", "seat")


class Strategy(Protocol):
    """What a seat does on a day: a decision from the problem's inputs."""

    kind: str

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision: ...


@dataclass(frozen=True)
class Static:
    kind: str = "static"

    def decide(self, *args: Any, **kwargs: Any) -> policy.Decision:
        return policy.NONE


@dataclass(frozen=True)
class Market:
    """The market heuristic. ``rate`` is the chance of a move on a day; the view is the setup's
    ``market`` ranking (the shared projection's per-game value, percent rostered breaking
    ties)."""

    rate: float
    kind: str = "market"

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        if g.random() >= self.rate:
            return policy.NONE
        limit = setup.max_weekly_adds
        if limit is not None and state.adds_used.get(team, 0) >= limit:
            return policy.NONE
        view = setup.market
        pool = [k for k in state.pool if k in view]
        roster = [k for k in state.active(team) if k in view]
        if not pool or not roster:
            return policy.NONE
        add = max(pool, key=lambda k: (view[k], -k))
        drop = min(roster, key=lambda k: (view[k], k))
        if view[add] <= view[drop]:
            return policy.NONE
        return policy.Decision((mv.Move(add, drop),), (), (), 0, "market")


@dataclass(frozen=True)
class Mirror:
    """The surrogate on the shared beliefs, with the knobs and fields given (the arm's)."""

    knobs: Mapping[str, Any]
    fields: policy.Fields = policy.DEFAULT_FIELDS
    kind: str = "mirror"

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        built = policy.problem_of(
            setup, state, team, self.knobs, beliefs, status, returns, self.fields.weeks_ahead
        )
        if built is None:
            return policy.NONE
        return policy.decide(built, "surrogate", fields=self.fields)


@dataclass(frozen=True)
class Seat:
    """An arm in a seat: its tier, knobs, what it executes and its fields, and the forecaster it
    believes by (#172, PR D1): a label the world holds, None for the run's. Static, market and
    mirror seats hold the run's. The label is part of the seat, so of the runner's decision
    cache's key: two seats on different forecasters share no decision."""

    name: str
    tier: str
    knobs: Mapping[str, Any]
    executes: str = policy.QUEUE_SET
    with_plan: bool = True
    fields: policy.Fields = policy.DEFAULT_FIELDS
    forecaster: str | None = None
    kind: str = "seat"

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        if self.tier == "static":
            return policy.NONE
        built = policy.problem_of(
            setup, state, team, self.knobs, beliefs, status, returns, self.fields.weeks_ahead
        )
        if built is None:
            return policy.NONE
        return policy.decide(built, self.tier, self.executes, self.with_plan, self.fields)


#: The keys of an arm's ``opponents`` block the simulator reads (:func:`of`); any other is
#: refused by name (:func:`check_spec`).
SPEC_KEYS = ("kind", "rate")


def check_spec(spec: Mapping[str, Any]) -> None:
    """Refuse an ``opponents`` block's key the simulator does not read, by name."""
    unknown = [k for k in spec if k not in SPEC_KEYS]
    if unknown:
        raise ValueError(
            f"opponents key {unknown[0]!r} is not one the simulator reads: one of {SPEC_KEYS}"
        )


def of(
    spec: Mapping[str, Any],
    knobs: Mapping[str, Any],
    market_rate: float,
    fields: policy.Fields = policy.DEFAULT_FIELDS,
) -> Strategy:
    """An opponent from an arm's ``opponents`` block: ``{"kind": "static"}``,
    ``{"kind": "market", "rate": 0.1}`` (the recorded rate when none is given) or
    ``{"kind": "mirror"}`` (the arm's own knobs and fields)."""
    kind = str(spec.get("kind", "static"))
    if kind == "static":
        return Static()
    if kind == "market":
        rate = spec.get("rate")
        return Market(float(market_rate if rate is None else rate))
    if kind == "mirror":
        return Mirror(dict(knobs), fields)
    raise ValueError(f"unknown opponent kind {kind!r}: one of {KINDS[:3]}")
