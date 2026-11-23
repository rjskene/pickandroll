"""The week's spread and games for the projection's own error and missed games (#487, ODDS
CALIBRATION #489).

``weekly.team_week``'s spread counted only game-to-game noise around a known per-game line. A
calibration of the week odds (weeks 2-5, the public leagues' Monday and Tuesday solves) found it
too narrow early in the week: the standardized gap's spread was 1.23 on Monday. Two terms widen
it, and the games are discounted for the games players miss:

- **The line's own error.** Each player's per-game line is off by a share ``rate_cv`` of itself,
  the same share over all of the player's games of the week:
  variance ``(rate_cv x E[n] x r)^2`` per player and stat.
- **Missed games.** Each started game is missed with a probability ``m``: the healthy
  ``miss_rate`` times :data:`SHAPE` at the game's days ahead, or a measured rate for a player
  listed Q, D or P this week (:data:`STATUS_MISS`). The expected games are
  ``E[n] = sum (1 - m)`` and their variance ``sum m (1 - m)``, times the line squared.

Both apply only to the games left, so the spread narrows as the week is played. ``miss_rate`` at
0 turns off the missed games, the status rates with them, and ``rate_cv`` at 0 the line's error:
both at 0 give the numbers before #487 exactly.

The knobs (:data:`KNOBS`) are the master's ruling of 2026-11-23 from the calibration's fit
(:data:`DEFAULTS`). The simulator tunes them (#172). Pure: no I/O."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .weekly import Noise

#: The knobs: the per-game line's error as a share of it, and the healthy player's missed games.
CV = "rate_cv"
MISS = "miss_rate"
KNOBS = (CV, MISS)
#: The master's ruling of 2026-11-23 on the calibration's fit (rate_cv) and the box scores
#: (miss_rate, :data:`SOURCE`).
DEFAULTS: Mapping[str, float] = {CV: 0.25, MISS: 0.07}
#: Every knob at 0: the spread and the games before #487.
OFF: Mapping[str, float] = {CV: 0.0, MISS: 0.0}
MINIMUMS: Mapping[str, float] = {CV: 0.0, MISS: 0.0}
MAXIMUMS: Mapping[str, float] = {CV: 1.0, MISS: 0.3}

#: Where :data:`SHAPE` and :data:`STATUS_MISS` come from.
SOURCE = (
    "ESPN box scores (data/boxscores), 2026-10-19 to 2026-11-22, 274 rostered players of the ten "
    "leagues, each player's Yahoo status read at 16:00 UTC on a day and the team's games from "
    "that day to six days on; a game with no line or no minutes is missed; measured 2026-11-23 "
    "(pickandroll-scratch/emissary/odds487/miss.py)"
)
#: A healthy player's missed games by days ahead (0 to 6, the last for any later day), over
#: their mean: 0.031, 0.053, 0.067, 0.079, 0.089, 0.098, 0.102 measured (17,994 games, 0.072
#: pooled). A status read today says more about today's game than Sunday's.
SHAPE: tuple[float, ...] = (0.418, 0.715, 0.904, 1.066, 1.200, 1.322, 1.376)
#: A player listed Q, D or P this week: the missed games by days ahead (0 to 6). Q's fall with
#: the days (0.497 over days 0-1, 304 games; 0.333 over 2-3, 258; 0.226 over 4-6, 350); D (53
#: games) and P (143) are too few to split and take their pooled rate. O and INJ keep the out
#: rule (``weekly.is_out``), and a GTD the zero-games rule.
STATUS_MISS: Mapping[str, tuple[float, ...]] = {
    "Q": (0.497, 0.497, 0.333, 0.333, 0.226, 0.226, 0.226),
    "D": (0.698,),
    "P": (0.126,),
}


def knobs_of(knobs: Mapping[str, Any] | None) -> dict[str, float]:
    """The spread's knobs from a league's knobs (the knob file's), each else its default."""
    knobs = knobs or {}
    return {k: float(knobs[k]) if knobs.get(k) is not None else DEFAULTS[k] for k in KNOBS}


def noise_of(knobs: Mapping[str, Any] | None) -> Noise | None:
    """The league's :class:`weekly.Noise` under its ``knobs``; None when every knob is 0 (the
    week as before #487)."""
    k = knobs_of(knobs)
    if k[CV] <= 0 and k[MISS] <= 0:
        return None
    return Noise(k[CV], k[MISS], STATUS_MISS if k[MISS] > 0 else {}, SHAPE)


def record(noise: Noise | None) -> dict[str, Any] | None:
    """What the payload and the decision log say of the spread: the knobs, the status rates and
    their source; None when it is off."""
    if noise is None:
        return None
    return {
        CV: noise.rate_cv,
        MISS: noise.miss_rate,
        "shape": list(noise.shape),
        "status_miss": {s: list(v) for s, v in noise.status_miss.items()},
        "source": SOURCE,
    }


def refused(knob: str, value: Any) -> str | None:
    """Why spread knob ``knob`` may not take ``value`` in the knob file: not a number, under its
    minimum or over its maximum; None when it may."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"{knob} {value!r} is not a number"
    if value < MINIMUMS[knob]:
        return f"{knob} {value} is below its minimum {MINIMUMS[knob]:g}"
    if value > MAXIMUMS[knob]:
        return f"{knob} {value} is above its maximum {MAXIMUMS[knob]:g}"
    return None
