"""What gate 5 is fed (#172, PR 2b; on a replay since PR D3), pure: the surrogate's set against
the exact set on sampled league-days of a world, and since PR D4a2 what was compared: the two sets
and their worth by the exact tier's own objective. ``validate.surrogate_gate`` scores a seat's
records (since PR g5 by the worths: the gain the surrogate keeps) and the command
(``cli.gate_surrogate``) builds the replay it runs on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from . import policy
from .engine import mv
from .run import World
from .state import Setup, SimState, initial

#: Why a sampled day is left out of gate 5's input.
OUTSIDE = "outside the calendar's weeks"
NO_PROBLEM = "no problem built"


def _moves(moves: Iterable[mv.Move]) -> list[list[int | None]]:
    """A set of moves as ``[add, drop]`` pairs by id (``None``: no drop), in order."""
    return sorted(([m.add, m.drop] for m in moves), key=lambda x: (x[0], x[1] is not None, x[1]))


def surrogate_records(
    setup: Setup,
    w: World,
    team: int,
    days: Sequence[date],
    knobs: Mapping[str, object],
    fields: policy.Fields = policy.DEFAULT_FIELDS,
) -> list[dict[str, Any]]:
    """What gate 5 compared on each of ``days`` (#172, PR D4a2), from day one's rosters, both
    tiers with ``fields`` (an arm's; the live route's by default) on the day's belief: the exact
    tier's set and the surrogate's (``exact``, ``surrogate``: the add and the drop by id), whether
    they are equal as sets of moves (``equal``, which the gate counts), and each set's worth by
    the exact tier's own objective on that day's problem (``worth``, the gate's input since PR
    g5): the value one evaluator of the exact tier's gives it on the key the exact tier searches
    (``policy.QUEUE_SET``, with the season term when the knobs carry one, ``policy.seasoned``),
    beside the worth of standing still (``standing``, the empty set's). A day outside the
    calendar's weeks, or one with no problem built, is listed with ``left_out`` saying why; on
    every other ``left_out`` is None."""
    out: list[dict[str, Any]] = []
    base = initial(setup)
    for day in days:
        record: dict[str, Any] = {"day": day.isoformat()}
        if setup.calendar.week_of(day) is None:
            out.append({**record, "left_out": OUTSIDE})
            continue
        beliefs = w.beliefs_on(day)
        status, returns = w.status_on(day)
        state = SimState(day, base.rosters, base.pool, {})
        built = policy.problem_of(
            setup, state, team, knobs, beliefs, status, returns, fields.weeks_ahead
        )
        if built is None:
            out.append({**record, "left_out": NO_PROBLEM})
            continue
        exact = policy.exact(built, with_plan=False, fields=fields).moves
        surrogate = policy.surrogate(built, fields).moves
        scored = policy.seasoned(built, mv.Evaluator(built.problem), policy.QUEUE_SET)
        out.append(
            {
                **record,
                "left_out": None,
                "exact": _moves(exact),
                "surrogate": _moves(surrogate),
                "equal": set(exact) == set(surrogate),
                "worth": {
                    "exact": float(scored.value(policy.QUEUE_SET, exact)),
                    "surrogate": float(scored.value(policy.QUEUE_SET, surrogate)),
                    "standing": float(scored.value(policy.QUEUE_SET, ())),
                },
            }
        )
    return out


def surrogate_matches(
    setup: Setup,
    w: World,
    team: int,
    days: Sequence[date],
    knobs: Mapping[str, object],
    fields: policy.Fields = policy.DEFAULT_FIELDS,
) -> list[bool]:
    """On each of ``days``, from day one's rosters, whether the surrogate's set equals the exact
    set (as sets of moves), both with ``fields`` (an arm's; the live route's by default), on the
    day's belief: gate 5's input until PR g5 and since then what its ``matched`` counts, read
    from :func:`surrogate_records`. A day outside the calendar's weeks, or with no problem built,
    is left out."""
    records = surrogate_records(setup, w, team, days, knobs, fields)
    return [r["equal"] for r in records if r["left_out"] is None]


__all__ = [
    "NO_PROBLEM",
    "OUTSIDE",
    "surrogate_matches",
    "surrogate_records",
]
