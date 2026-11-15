"""The world's draws (#172, PR 1): the generator every draw of a path comes from, and the error
an oracle forecaster's projection is drawn with (#172, PR D1).

Every draw is seeded by ``(seed, path, player, game, stream)`` through :func:`rng`, as the draft
simulator keys by seed and pick, so two arms of a pair see one world and a stream added later
moves no other draw. A replay's truth is the recorded lines (``run.replay_world``); what is drawn
on a path is the told return date of an absence (the ``news`` stream, :data:`NEWS_SD_DAYS`), a
market rival's moves (``market``) and an oracle's error (:func:`errors` and :func:`true_rates`
on the ``error`` and ``forecast`` streams). The drawn world of game noise, a hazard and a weekly
refresh went with the standalone cut (PR D3); its streams keep their numbers. Pure.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

#: The stream id of each use of the generator; append, never reorder.
STREAMS: Mapping[str, int] = {
    "error": 0,
    "minutes": 1,
    "line": 2,
    "absence": 3,
    "duration": 4,
    "refresh": 5,
    "news": 6,
    "market": 7,
    "forecast": 8,
}
#: The spread of the return date the policy sees around the true one, in days.
NEWS_SD_DAYS = 2.0
#: Rates and beliefs are per-game stats in ``weekly.STATS`` names.
Rates = Mapping[str, float]


def rng(seed: int, path: int, *keys: int) -> np.random.Generator:
    """One generator per (seed, path, keys): the keys are the player's index, the game's index
    and the stream."""
    return np.random.default_rng([int(seed), int(path), *(int(k) for k in keys)])


# --------------------------------------------------------------------------- an oracle's error
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


# --------------------------------------------------------------------------- an absence
@dataclass(frozen=True)
class Absence:
    """Games ``start`` to ``end`` (indexes, inclusive) the player misses."""

    start: int
    end: int
