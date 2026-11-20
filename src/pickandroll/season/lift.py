"""The breakout flag's lift (#435): a flagged player's line lifted toward the minutes played now.

The user ruled on 2026-11-19 that the moves take chances on players who may outplay their
projections. A flagged available player (``season.flags``) is valued, on a move that drops one of
my marginal players or nobody, on a line lifted by the flag:

- The player's minutes move toward the recent minutes by the level's weight:
  ``M' = projected + w[level] x (recent - projected)``, where ``recent`` is the 7-day window's
  minutes a game when it has at least :data:`RECENT_GAMES` games, else the 14-day window's (the
  master's review: the smaller of the two lags exactly the role changes the lift is for). The
  factor is ``M' / projected``, never below 1: a flag never lowers a line.
- When the surge signal spoke, the factor is at least ``1 + floor[level]``, so the market alone
  lifts even with no minutes gain.
- The lifted line is the line times the factor, stat by stat (a per-minute line at ``M'``):
  makes and attempts scale alike, so the percentages are unchanged.

Which moves the lift applies to is the move model's (``season.moves``, ``MoveProblem.lifted`` and
``MoveProblem.marginal``). The knobs (:data:`KNOBS`) are the code's first guesses
(:data:`DEFAULTS`), which the knob file may set per league; all of them 0 lift nothing. Pure: no
I/O."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import flags as fl

#: Each flag level's knob suffix.
LEVEL_KEYS: Mapping[str, str] = {"watch": "watch", "add": "add", "must-add": "must_add"}
#: The lift's knobs: each level's weight on the minutes gain, each level's floor on a surge, and
#: how many of my players are marginal (the lowest by the keep rule's value, the kept excluded).
WEIGHTS = tuple(f"lift_weight_{k}" for k in LEVEL_KEYS.values())
FLOORS = tuple(f"lift_floor_{k}" for k in LEVEL_KEYS.values())
MARGINAL = "lift_marginal"
KNOBS = (*WEIGHTS, *FLOORS, MARGINAL)
#: The first guesses, ruled live as the code's defaults (2026-11-19, the master's review on
#: #435): stronger than a plain move would take, since the lift applies only against a marginal
#: drop. The simulator tunes them (#172).
DEFAULTS: Mapping[str, Any] = {
    "lift_weight_watch": 0.5,
    "lift_weight_add": 0.75,
    "lift_weight_must_add": 1.0,
    "lift_floor_watch": 0.10,
    "lift_floor_add": 0.15,
    "lift_floor_must_add": 0.25,
    MARGINAL: 3,
}
#: The recent minutes are the first of these windows (days) with this many games.
RECENT_WINDOWS = (7, 14)
RECENT_GAMES = 2
#: Every knob at 0: no lift anywhere, the moves as before #435.
OFF: Mapping[str, Any] = {k: 0 for k in KNOBS}
#: The knobs' bounds, as the knob file checks them: a weight a share of the gap, a floor a share
#: of the line, the marginal players a count.
MINIMUMS: Mapping[str, float] = {k: 0.0 for k in KNOBS}
MAXIMUMS: Mapping[str, float] = {
    **{k: 1.0 for k in WEIGHTS},
    **{k: 0.5 for k in FLOORS},
    MARGINAL: 10,
}
WHOLE = frozenset({MARGINAL})
EPS = 1e-9


@dataclass(frozen=True)
class Lift:
    """A flagged player's lift: the factor on the player's line, the flag's level and each signal's score,
    and the lifted line itself."""

    factor: float
    level: str
    signals: Mapping[str, float]
    rates: Mapping[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor": round(self.factor, 3),
            "level": self.level,
            "signals": {k: round(v, 3) for k, v in self.signals.items() if v > 0},
        }


def knobs_of(knobs: Mapping[str, Any] | None) -> dict[str, Any]:
    """The lift's knobs in force: :data:`DEFAULTS`, then those ``knobs`` set."""
    return {k: (knobs or {}).get(k, DEFAULTS[k]) for k in KNOBS}


def is_off(knobs: Mapping[str, Any]) -> bool:
    """Whether ``knobs`` lift nothing: every weight and floor 0 (the marginal count alone lifts
    nothing), or no marginal player."""
    k = knobs_of(knobs)
    return int(k[MARGINAL]) <= 0 or all(float(k[x]) <= 0 for x in (*WEIGHTS, *FLOORS))


def factor_of(flag: fl.Flag, knobs: Mapping[str, Any]) -> float:
    """The factor ``flag`` lifts a line by under ``knobs`` (1 for none): the minutes moved toward
    the recent by the level's weight, at least the level's floor when the surge spoke."""
    if flag.level is None or flag.level not in LEVEL_KEYS:
        return 1.0
    k = knobs_of(knobs)
    suffix = LEVEL_KEYS[flag.level]
    weight = float(k[f"lift_weight_{suffix}"])
    floor = float(k[f"lift_floor_{suffix}"])
    factor = 1.0
    minutes = flag.signals.get("minutes")
    facts = minutes.facts if minutes is not None else {}
    projected = facts.get("projected_mpg")
    windows = facts.get("windows") or {}
    recent = recent_mpg(windows)
    if weight > 0 and projected and projected > 0 and recent is not None:
        lifted = projected + weight * (recent - projected)
        factor = max(factor, lifted / projected)
    surge = flag.signals.get("surge")
    if floor > 0 and surge is not None and surge.score > 0:
        factor = max(factor, 1.0 + floor)
    return factor


def recent_mpg(windows: Mapping[Any, Mapping[str, Any]]) -> float | None:
    """The recent minutes a game: the first of :data:`RECENT_WINDOWS` the minutes signal kept
    with at least :data:`RECENT_GAMES` games (its windows keyed by days, as an int or, read back
    from JSON, a string); None with neither."""
    for days in RECENT_WINDOWS:
        w = windows.get(days, windows.get(str(days)))
        if (
            w is not None
            and float(w.get("games") or 0) >= RECENT_GAMES
            and w.get("mpg") is not None
        ):
            return float(w["mpg"])
    return None


def lift_of(
    flag: fl.Flag, rates: Mapping[str, float] | None, knobs: Mapping[str, Any]
) -> Lift | None:
    """The lift of a player with ``flag`` and line ``rates`` under ``knobs``; None when it lifts
    nothing (no level, a factor of 1, or no line)."""
    if rates is None:
        return None
    factor = factor_of(flag, knobs)
    if factor <= 1.0 + EPS or flag.level is None:
        return None
    return Lift(
        factor,
        flag.level,
        {name: s.score for name, s in flag.signals.items()},
        {stat: v * factor for stat, v in rates.items()},
    )


def lifts(
    flags: Mapping[int, fl.Flag],
    rates: Mapping[int, Mapping[str, float]],
    candidates: Iterable[int],
    knobs: Mapping[str, Any],
) -> dict[int, Lift]:
    """Each candidate's lift (``candidates``, their keys) with a flag under ``knobs``; none when the
    knobs are off (:func:`is_off`)."""
    if is_off(knobs):
        return {}
    out = {}
    for key in candidates:
        f = flags.get(key)
        if f is None:
            continue
        lift = lift_of(f, rates.get(key), knobs)
        if lift is not None:
            out[key] = lift
    return out


def refused(knob: str, value: Any) -> str | None:
    """Why lift knob ``knob`` may not take ``value`` in the knob file: not a number (a whole one
    for the marginal count), under its minimum or over its maximum; None when it may."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"{knob} {value!r} is not a number"
    if knob in WHOLE and not isinstance(value, int):
        return f"{knob} {value!r} is not a whole number"
    if value < MINIMUMS[knob]:
        return f"{knob} {value} is below its minimum {MINIMUMS[knob]:g}"
    if value > MAXIMUMS[knob]:
        return f"{knob} {value} is above its maximum {MAXIMUMS[knob]:g}"
    return None
