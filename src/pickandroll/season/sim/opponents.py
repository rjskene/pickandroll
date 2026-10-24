"""The other eleven seats (#172, PR 2b): what each opponent does on a day.

The ladder from the design note. **Static** makes no move. **Market** is the heuristic: each day
with probability ``rate`` (adds per team-day, from the league's recorded transactions) it adds
the pool's best by the market's view and drops its weakest by the same view, within the caps.
**Mirror** runs the surrogate on the shared beliefs. **Seat** is the equal room's: a named arm
in another seat, the same tiers the arm under test runs. Each strategy is pure given the world's
draws (``run.World`` passes the day's generator), so two arms of a comparison see the same
opponents while their states agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np

from .. import moves as mv
from . import policy
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
    """The surrogate on the shared beliefs, with the knobs given."""

    knobs: Mapping[str, Any]
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
        built = policy.problem_of(setup, state, team, self.knobs, beliefs, status, returns)
        if built is None:
            return policy.NONE
        return policy.decide(built, "surrogate")


@dataclass(frozen=True)
class Seat:
    """An arm in a seat: its tier, knobs and what it executes."""

    name: str
    tier: str
    knobs: Mapping[str, Any]
    executes: str = policy.QUEUE_SET
    with_plan: bool = True
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
        built = policy.problem_of(setup, state, team, self.knobs, beliefs, status, returns)
        if built is None:
            return policy.NONE
        return policy.decide(built, self.tier, self.executes, self.with_plan)


def of(spec: Mapping[str, Any], knobs: Mapping[str, Any], market_rate: float) -> Strategy:
    """An opponent from an arm's ``opponents`` block: ``{"kind": "static"}``,
    ``{"kind": "market", "rate": 0.1}`` (the recorded rate when none is given) or
    ``{"kind": "mirror"}`` (the arm's own knobs)."""
    kind = str(spec.get("kind", "static"))
    if kind == "static":
        return Static()
    if kind == "market":
        rate = spec.get("rate")
        return Market(float(market_rate if rate is None else rate))
    if kind == "mirror":
        return Mirror(dict(knobs))
    raise ValueError(f"unknown opponent kind {kind!r}: one of {KINDS[:3]}")
