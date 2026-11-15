"""What gate 5 is fed (#172, PR 2b; on a replay since PR D3), pure: the surrogate's set against
the exact set on sampled league-days of a world. ``validate.surrogate_gate`` scores the list and
the command (``cli.gate_surrogate``) builds the replay it runs on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from . import policy
from .run import World
from .state import Setup, SimState, initial


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
    day's belief: gate 5's input. A day outside the calendar's weeks is left out."""
    out = []
    base = initial(setup)
    for day in days:
        if setup.calendar.week_of(day) is None:
            continue
        beliefs = w.beliefs_on(day)
        status, returns = w.status_on(day)
        state = SimState(day, base.rosters, base.pool, {})
        built = policy.problem_of(
            setup, state, team, knobs, beliefs, status, returns, fields.weeks_ahead
        )
        if built is None:
            continue
        exact = set(policy.exact(built, with_plan=False, fields=fields).moves)
        surrogate = set(policy.surrogate(built, fields).moves)
        out.append(exact == surrogate)
    return out


__all__ = [
    "surrogate_matches",
]
