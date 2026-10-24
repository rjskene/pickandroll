"""Synthetic per-game logs for the season simulator's tests (#172): a few hundred player-games
drawn from known parameters, made-up names, fixed seeds, no real log anywhere."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from pickandroll.season.sim.fit import GameLine

#: Per-game rates the synthetic players are drawn around, by stat.
BASE_RATES: Mapping[str, tuple[float, float]] = {
    "pts": (8.0, 28.0),
    "threes": (0.5, 3.5),
    "reb": (2.0, 11.0),
    "ast": (1.0, 8.0),
    "stl": (0.4, 1.8),
    "blk": (0.2, 2.0),
    "tov": (0.8, 3.5),
    "fga": (6.0, 20.0),
    "fta": (1.0, 8.0),
}
TRUE_PHI: Mapping[str, float] = {
    "pts": 2.5,
    "threes": 1.2,
    "reb": 1.4,
    "ast": 1.3,
    "stl": 1.0,
    "blk": 1.1,
    "tov": 1.0,
    "fga": 1.5,
    "fta": 2.0,
}
#: The run-length mixture the synthetic absences follow: (lo, hi, weight).
TRUE_MIXTURE = ((1, 3, 0.70), (4, 15, 0.25), (16, 30, 0.05))


def negbin(rng: np.random.Generator, mean: float, phi: float) -> int:
    if mean <= 0:
        return 0
    if phi <= 1.0:
        return int(rng.poisson(mean))
    n = mean / (phi - 1.0)
    return int(rng.negative_binomial(n, 1.0 / phi))


def run_length(rng: np.random.Generator, mixture=TRUE_MIXTURE) -> int:
    weights = np.array([w for _, _, w in mixture])
    lo, hi, _ = mixture[int(rng.choice(len(mixture), p=weights / weights.sum()))]
    return int(rng.integers(lo, hi + 1))


def synthetic_lines(
    seed: int = 7,
    players: int = 40,
    games: int = 60,
    season: int = 2026,
    phi: Mapping[str, float] = TRUE_PHI,
    sigma_m: float = 0.2,
    hazard: float = 0.12,
    mixture=TRUE_MIXTURE,
    minutes: float = 30.0,
    prefix: str = "p",
    short_games: int = 0,
) -> list[GameLine]:
    """``players`` players over ``games`` scheduled games each: minutes lognormal around
    ``minutes`` with spread ``sigma_m``, each stat negative binomial around ``rate × minutes
    factor`` with its ``phi``, a new absence after a played game with probability ``hazard`` and
    a length from ``mixture``. ``short_games`` of each player's played games are cut to three
    minutes (a garbage-time line)."""
    rng = np.random.default_rng(seed)
    out: list[GameLine] = []
    for i in range(players):
        pid = f"{prefix}{i:03d}"
        rates = {s: float(rng.uniform(lo, hi)) for s, (lo, hi) in BASE_RATES.items()}
        out_until = -1
        shorts = 0
        for g in range(games):
            if g <= out_until:
                out.append(GameLine(pid, season, g + 1, "T1", False, 0.0, {}))
                continue
            factor = float(np.exp(-0.5 * sigma_m**2 + sigma_m * rng.standard_normal()))
            mins = minutes * factor
            stats = {s: float(negbin(rng, r * factor, phi[s])) for s, r in rates.items()}
            if shorts < short_games:
                shorts += 1
                mins = 3.0
            out.append(GameLine(pid, season, g + 1, "T1", True, mins, stats))
            if rng.random() < hazard:
                out_until = g + run_length(rng, mixture)
    return out


def rates_table(
    seed: int, players: Sequence[str], stats: Sequence[str] = tuple(BASE_RATES)
) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    return {
        p: {s: float(rng.uniform(*BASE_RATES[s])) for s in stats if s in BASE_RATES}
        for p in players
    }
