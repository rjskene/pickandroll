"""Per-game rates blended toward recent form (#486, ODDS CALIBRATION #489).

A calibration of the public leagues' week odds (weeks 2-5, 36 league-weeks) found the week-start
odds too high on average: the projection overrates the players we hold by more than the players
our opponents hold. That is a selection effect. We draft and add by that projection's value, so
its overestimates collect on our rosters. The fix is the same for every player: each one's
per-game line moves toward the player's recent actual per-game line, and the move grows with
the games played in the window:

    line = (1 - w) projected + w recent,    w = rate_shrink x g / (g + rate_shrink_games)

``g`` is the games in the recent window. The window is the 7-day one when it holds at least
:data:`FRESH_GAMES` of the player's games (fresher), else the 14-day one (:func:`window_of`).
Every stat blends alike, makes and attempts too, so a percentage moves toward the recent one
weighted by the attempts. No rule names my players: the larger correction on them comes out of
the data.

Which projections play the blended line is the caller's (``api.season_moves.system_rates``): the
week and three-week horizons, the field and the views built on them. The keep rule, the season
guard and every rest-of-season figure stay on the line before the blend. A 7- or 14-day window
is no signal for a season, and the breakout lift (#435) already moves its own line toward the
recent minutes.

The knobs (:data:`KNOBS`) are first guesses (:data:`DEFAULTS`). The master ruled 0.5 and 4 games
on 2026-11-23, from the calibration's fit. The simulator tunes them (#172). ``rate_shrink`` at 0
blends nothing, and the rates come back as they went in. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from typing import Any

#: The knobs: the most weight recent form may take, and the games at which it takes half of it.
SHRINK = "rate_shrink"
GAMES = "rate_shrink_games"
KNOBS = (SHRINK, GAMES)
#: The first guesses (#486, the master's ruling of 2026-11-23 on the calibration's fit).
DEFAULTS: Mapping[str, float] = {SHRINK: 0.5, GAMES: 4.0}
#: Every knob at 0 weight: no blend anywhere, the rates as before #486.
OFF: Mapping[str, float] = {SHRINK: 0.0, GAMES: DEFAULTS[GAMES]}
#: The knobs' bounds, as the knob file checks them: a share of the gap, and a count of games.
MINIMUMS: Mapping[str, float] = {SHRINK: 0.0, GAMES: 1.0}
MAXIMUMS: Mapping[str, float] = {SHRINK: 1.0, GAMES: 30.0}
#: The recent windows (days), freshest first; the first with this many of a player's games is read.
WINDOWS = (7, 14)
FRESH_GAMES = 3

#: A player's recent line: the games played in the window and the per-game line over them.
Recent = tuple[float, Mapping[str, float]]


def knobs_of(knobs: Mapping[str, Any] | None) -> dict[str, float]:
    """The blend's knobs from a league's knobs (the knob file's), each else its default."""
    knobs = knobs or {}
    return {k: float(knobs[k]) if knobs.get(k) is not None else DEFAULTS[k] for k in KNOBS}


def window_of[K: Hashable](
    key: K, windows: Mapping[int, Mapping[K, Recent]]
) -> tuple[int, Recent] | None:
    """The window ``key``'s recent line is read from: the first of :data:`WINDOWS` holding at
    least :data:`FRESH_GAMES` of the player's games, else the last one that has the player; None
    when none does."""
    found = None
    for days in WINDOWS:
        line = windows.get(days, {}).get(key)
        if line is None or line[0] <= 0:
            continue
        found = (days, line)
        if line[0] >= FRESH_GAMES:
            return found
    return found


def weight(games: float, shrink: float, half: float) -> float:
    """Recent form's weight on a line from ``games`` games: ``shrink x g / (g + half)``."""
    if shrink <= 0 or games <= 0:
        return 0.0
    return shrink * games / (games + half)


def blend[K: Hashable](
    rates: Mapping[K, Mapping[str, float]],
    windows: Mapping[int, Mapping[K, Recent]],
    shrink: float,
    half: float,
) -> tuple[Mapping[K, Mapping[str, float]], dict[K, int]]:
    """``rates`` with each player's line moved toward the player's recent line (:func:`window_of`) by
    :func:`weight`, stat by stat, and the window each blended player was read from. A player
    with no recent games keeps the line. ``shrink`` at 0 returns ``rates`` itself."""
    if shrink <= 0:
        return rates, {}
    out: dict[K, Mapping[str, float]] = dict(rates)
    used: dict[K, int] = {}
    for key, line in rates.items():
        found = window_of(key, windows)
        if found is None:
            continue
        days, (games, recent) = found
        w = weight(games, shrink, half)
        if w <= 0:
            continue
        stats = set(line) | set(recent)
        out[key] = {
            s: (1 - w) * float(line.get(s, 0.0)) + w * float(recent.get(s, 0.0)) for s in stats
        }
        used[key] = days
    return out, used


def refused(knob: str, value: Any) -> str | None:
    """Why blend knob ``knob`` may not take ``value`` in the knob file: not a number, under its
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
