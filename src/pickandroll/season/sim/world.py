"""The simulated world (#172, PR 1): what is true in one path of one season, and what the policy
gets to see of it.

Three layers on the real schedule. A persistent projection error per player and stat, drawn
once a path (:func:`errors`): the true rate is the projection times ``e^ε`` with
``ε ~ N(−s·gap, τ²)``, ``s`` the shrink toward the market view. Per-game noise
(:func:`game_line`): one minutes factor shared across the player's stats, each counting stat
and attempt negative binomial around ``rate × factor`` with its dispersion, makes binomial on
attempts, points from the makes. Availability (:func:`absences`): today's status as read, then
a hazard of a new absence after each played game with a run length from the fitted mixture.

Beliefs are what the policy decides on, never the truth: the projection with its error,
refreshed once a week toward the truth at ``kappa`` with noise ``sigma_eta`` (:func:`refresh`),
and an absence seen only ``lag`` days after it began, with a noisy return date (:func:`news`).

Every draw is seeded by ``(seed, path, player, game, stream)`` through :func:`rng`, as the draft
simulator keys by seed and pick, so two arms of a comparison see one world and a stream added
later moves no other draw. Pure: rates, schedule and rosters come in; the fit's figures are
passed, never read.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..weekly import BINOMIAL, COUNTING, PCT, starters
from .fit import DISPERSED, Hazard

#: The stream id of each use of the generator; append, never reorder.
STREAMS: Mapping[str, int] = {
    "error": 0,
    "minutes": 1,
    "line": 2,
    "absence": 3,
    "duration": 4,
    "refresh": 5,
    "news": 6,
}
#: The spread of the return date the policy sees around the true one, in days.
NEWS_SD_DAYS = 2.0
#: Rates and beliefs are per-game stats in ``weekly.STATS`` names.
Rates = Mapping[str, float]


def rng(seed: int, path: int, *keys: int) -> np.random.Generator:
    """One generator per (seed, path, keys): the keys are the player's index, the game's index
    and the stream."""
    return np.random.default_rng([int(seed), int(path), *(int(k) for k in keys)])


# --------------------------------------------------------------------------- layer 1
def errors(
    seed: int,
    path: int,
    players: Sequence[str],
    stats: Sequence[str],
    s: float,
    gap: Mapping[str, Mapping[str, float]],
    tau: Mapping[str, float],
) -> dict[str, dict[str, float]]:
    """The persistent error ``ε`` of every player and stat in this path: normal with mean
    ``−s·gap`` (the gap between the policy's system and the market view, zero when unknown) and
    spread ``tau[stat]``."""
    out: dict[str, dict[str, float]] = {}
    for i, p in enumerate(players):
        g = rng(seed, path, i, 0, STREAMS["error"])
        draws = g.standard_normal(len(stats))
        out[p] = {
            stat: float(-s * gap.get(p, {}).get(stat, 0.0) + tau.get(stat, 0.0) * z)
            for stat, z in zip(stats, draws)
        }
    return out


def true_rates(
    projection: Mapping[str, Rates], eps: Mapping[str, Mapping[str, float]]
) -> dict[str, dict[str, float]]:
    """Each player's true per-game rates: the projection times ``e^ε`` stat by stat."""
    return {
        p: {stat: float(r) * math.exp(eps.get(p, {}).get(stat, 0.0)) for stat, r in rates.items()}
        for p, rates in projection.items()
    }


# --------------------------------------------------------------------------- layer 2
def _negbin(g: np.random.Generator, mean: float, phi: float) -> int:
    """A count with the given mean and variance ``phi × mean`` (Poisson at ``phi <= 1``)."""
    if mean <= 0:
        return 0
    if phi <= 1.0:
        return int(g.poisson(mean))
    n = mean / (phi - 1.0)
    return int(g.negative_binomial(n, 1.0 / phi))


def minutes_factor(seed: int, path: int, player: int, game: int, sigma: float) -> float:
    """The game's minutes factor: lognormal with mean one."""
    if sigma <= 0:
        return 1.0
    z = rng(seed, path, player, game, STREAMS["minutes"]).standard_normal()
    return float(math.exp(-0.5 * sigma * sigma + sigma * z))


def game_line(
    seed: int,
    path: int,
    player: int,
    game: int,
    rates: Rates,
    phi: Mapping[str, float],
    sigma: float,
    binomial: Mapping[str, float] = BINOMIAL,
) -> dict[str, float]:
    """One player's line in one game he plays. Counting stats and attempts are negative binomial
    around ``rate × minutes factor`` with ``phi[stat]``; makes are binomial on the attempts at
    the projected percentage; points are two a field goal, one more a three, one a free throw
    when the makes are projected, else drawn like the other counts."""
    factor = minutes_factor(seed, path, player, game, sigma)
    g = rng(seed, path, player, game, STREAMS["line"])
    line: dict[str, float] = {}
    for stat in DISPERSED:
        if stat == "pts":
            continue
        if stat in rates:
            line[stat] = float(_negbin(g, rates[stat] * factor, phi.get(stat, 1.0)))
    for made, (num, den) in ((k, v) for k, v in PCT.items()):
        if num in rates and den in rates and den in line:
            p = min(1.0, max(0.0, rates[num] / rates[den])) if rates[den] > 0 else 0.0
            attempts = int(line[den])
            line[num] = float(g.binomial(attempts, p)) if attempts else 0.0
        elif num in rates:
            line[num] = float(_negbin(g, rates[num] * factor, phi.get(num, 1.0)))
    if "pts" in rates:
        if "fgm" in line and "ftm" in line:
            threes = line.get("threes", 0.0)
            line["pts"] = 2.0 * line["fgm"] + threes + line["ftm"]
        else:
            line["pts"] = float(_negbin(g, rates["pts"] * factor, phi.get("pts", 1.0)))
    line["minutes_factor"] = factor
    return line


# --------------------------------------------------------------------------- layer 3
def _run_length(g: np.random.Generator, hazard: Hazard) -> int:
    weights = np.array([c.weight for c in hazard.components], dtype=float)
    if weights.sum() <= 0:
        return 1
    comp = hazard.components[int(g.choice(len(weights), p=weights / weights.sum()))]
    if not comp.lengths:
        return comp.lo
    lengths = list(comp.lengths)
    probs = np.array([comp.lengths[n] for n in lengths], dtype=float)
    return int(lengths[int(g.choice(len(lengths), p=probs / probs.sum()))])


@dataclass(frozen=True)
class Absence:
    """Games ``start`` to ``end`` (indexes, inclusive) the player misses."""

    start: int
    end: int


def absences(
    seed: int,
    path: int,
    player: int,
    games: int,
    hazard: Hazard,
    out_through: int = -1,
) -> tuple[np.ndarray, list[Absence]]:
    """Which of the player's next ``games`` he plays, and the absences: game indexes through
    ``out_through`` missed from today's status as read, then after every played game a new
    absence with probability ``hazard.rate`` and a length from the mixture. One generator per
    player and path, consumed in game order."""
    g = rng(seed, path, player, 0, STREAMS["absence"])
    available = np.ones(games, dtype=bool)
    out: list[Absence] = []
    i = 0
    if out_through >= 0:
        end = min(out_through, games - 1)
        available[: end + 1] = False
        out.append(Absence(0, end))
        i = end + 1
    while i < games:
        if g.random() < hazard.rate and i + 1 < games:
            length = _run_length(g, hazard)
            end = min(i + length, games - 1)
            available[i + 1 : end + 1] = False
            out.append(Absence(i + 1, end))
            i = end + 1
        else:
            i += 1
    return available, out


# --------------------------------------------------------------------------- beliefs
def refresh(
    beliefs: Mapping[str, Rates],
    truth: Mapping[str, Rates],
    kappa: float,
    sigma_eta: float,
    seed: int,
    path: int,
    week: int,
    stats: Sequence[str] = COUNTING,
) -> dict[str, dict[str, float]]:
    """The policy's rates after one weekly refresh: on the log scale each stat moves ``kappa``
    of the way to the truth plus noise ``N(0, sigma_eta²)``; stats outside ``stats`` and
    players without a truth stay put."""
    g = rng(seed, path, week, 0, STREAMS["refresh"])
    out: dict[str, dict[str, float]] = {}
    for p in sorted(beliefs):
        rates = dict(beliefs[p])
        t = truth.get(p)
        for stat in stats:
            b = rates.get(stat)
            if t is None or b is None or b <= 0 or t.get(stat, 0.0) <= 0:
                continue
            step = kappa * (math.log(t[stat]) - math.log(b)) + sigma_eta * g.standard_normal()
            rates[stat] = float(b * math.exp(step))
        out[p] = rates
    return out


@dataclass(frozen=True)
class Seen:
    """What the policy knows of a player's absence on a day: ``out`` whether it has heard, and
    the return day it believes (None while it has not)."""

    out: bool
    returns: int | None


def news(
    seed: int,
    path: int,
    player: int,
    absence: Absence | None,
    day: int,
    lag: int,
    sd_days: float = NEWS_SD_DAYS,
) -> Seen:
    """On ``day`` (an index), whether the policy has heard of ``absence`` (``lag`` days after it
    began) and the return day it is told: the true one plus normal noise, never before the day
    it hears."""
    if absence is None or day < absence.start + lag:
        return Seen(False, None)
    g = rng(seed, path, player, absence.start, STREAMS["news"])
    noise = round(float(g.standard_normal() * sd_days))
    return Seen(True, max(day, absence.end + 1 + noise))


# --------------------------------------------------------------------------- a season
def player_season(
    seed: int,
    path: int,
    player: int,
    rates: Rates,
    phi: Mapping[str, float],
    sigma: float,
    game_days: Sequence[int],
    hazard: Hazard,
    out_through: int = -1,
) -> tuple[dict[int, dict[str, float]], list[Absence]]:
    """A player's lines by day index for the games he plays of ``game_days`` (his team's days),
    and his absences (in game indexes)."""
    available, out = absences(seed, path, player, len(game_days), hazard, out_through)
    lines = {
        day: game_line(seed, path, player, i, rates, phi, sigma)
        for i, day in enumerate(game_days)
        if available[i]
    }
    return lines, out


def team_week(
    lines: Mapping[Any, Mapping[int, Mapping[str, float]]],
    roster: Sequence[tuple[Any, Sequence[str]]],
    days: Sequence[int],
    slots: Sequence[str],
    value: Mapping[Any, float],
) -> dict[str, float]:
    """A roster's weekly totals: on each of ``days`` the rostered players with a line fill the
    starting ``slots`` most valuable first (``weekly.starters``), and the starters' lines add
    up. The percentages are left to the league, which has the makes and attempts."""
    totals: dict[str, float] = {}
    for day in days:
        candidates = [(k, pos) for k, pos in roster if day in lines.get(k, {})]
        for k in starters(candidates, slots, value):
            for stat, x in lines[k][day].items():
                if stat == "minutes_factor":
                    continue
                totals[stat] = totals.get(stat, 0.0) + float(x)
    return totals
