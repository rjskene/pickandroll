"""The pick clock and the solve budgets it allows (#13, #66).

The tuning point is a 30 s clock (user, 2026-10-02): the mocks' clock, and the one the drafter's
wait, the solve budgets and the gates are designed for. A room reports its own clock (the
client carries Yahoo's on every ``turn_start``, ``clock_s``), and the plan's budget follows it:

========  ===========  ==========  =====================  ==================
clock     plan budget  price limit  D1 limit (pending,     drafter acts at
                                    miss)
========  ===========  ==========  =====================  ==================
30 s      5 s          5 s          11 s                   17 s
40 s      15 s         10 s         26 s                   27 s
60 s      20 s         10 s         31 s                   47 s
90 s      20 s         10 s         31 s                   77 s
========  ===========  ==========  =====================  ==================

The drafter clicks with ``CLOCK_MARGIN_S`` of the clock left, and the exact prices that correct a
capped plan take up to ``PRICING_S`` after the plan (their 10 s budget and the solve's overhead):
the plan gets what is left, between ``PLAN_LIMIT_MIN`` and ``PLAN_LIMIT_MAX``. The D1 gate
(docs/YAHOO_SYNC.md §1) allows a turn whose board was solved ahead (a hit) ``HIT_LIMIT_S``, and
any other turn the plan budget plus the price limit plus one second: on a 30 s clock a capped
cold plan lands at budget plus pricing by construction.
"""

from __future__ import annotations

#: The design point: the mocks' clock, and the clock a room is taken to run until it reports one.
DEFAULT_CLOCK_S = 30.0
CLOCK_MARGIN_S = 13.0
PRICING_S = 12.0
PLAN_LIMIT_MIN = 5.0
PLAN_LIMIT_MAX = 20.0
PRICE_LIMIT_MAX = 10.0
#: D1: a turn whose board was solved before it started has its reco within this.
HIT_LIMIT_S = 1.0


def plan_budget(clock_s: float | None) -> float:
    """The plan's time limit in a room whose pick clock is ``clock_s`` seconds."""
    clock = DEFAULT_CLOCK_S if clock_s is None else clock_s
    return min(PLAN_LIMIT_MAX, max(PLAN_LIMIT_MIN, clock - CLOCK_MARGIN_S - PRICING_S))


def price_budget(clock_s: float | None) -> float:
    """The exact prices' time limit under the plan budget of ``clock_s``."""
    return min(PRICE_LIMIT_MAX, plan_budget(clock_s))


def d1_limit_s(clock_s: float | None, hit: bool = False) -> float:
    """The D1 gate on a turn: the latest its reco may be ready, in seconds from the turn's start."""
    if hit:
        return HIT_LIMIT_S
    return plan_budget(clock_s) + price_budget(clock_s) + 1.0


def acts_at_s(clock_s: float | None) -> float:
    """When the drafter acts, in seconds from the turn's start: ``CLOCK_MARGIN_S`` before the end.
    A reco ready later than this missed the turn."""
    clock = DEFAULT_CLOCK_S if clock_s is None else clock_s
    return clock - CLOCK_MARGIN_S
