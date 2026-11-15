"""The gates (#172, PR 1), as pure functions on arrays; the commands (``cli``) read the cached
logs and the hold-out season and call them with the season each is scored on. Gates 2, 3 and 6
read a live league's recorded weeks, scorecard and exports and went with the standalone cut (PR
D3); the numbers below are the ones the gates have always had.

1. Team weeks: every team's weekly totals as probability integral transforms under the
   simulator's team-week distribution; no bucket of 20 points off by more than 5.
4. Absences: player-games missed a team-week against the hazard, as transforms in buckets.
5. Surrogate: its set equals the exact set on four of five sampled league-days.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

BUCKETS = 5
BUCKET_TOL = 0.05
SURROGATE_NEEDED = 4
SURROGATE_OF = 5


@dataclass(frozen=True)
class Gate:
    """One gate's verdict on one season (or ``None`` for pooled data) with its evidence."""

    name: str
    passed: bool
    season: int | str | None
    detail: dict[str, Any] = field(default_factory=dict)


def pit(observed: float, samples: Sequence[float]) -> float:
    """Where ``observed`` falls in ``samples``: the share below plus half the share equal."""
    s = np.asarray(samples, dtype=float)
    if s.size == 0:
        return 0.5
    return float((np.sum(s < observed) + 0.5 * np.sum(s == observed)) / s.size)


def pits(
    observed: Sequence[float],
    samples: Sequence[Sequence[float]],
    randomize: bool = False,
    seed: int = 0,
) -> np.ndarray:
    """One transform per observation against its own row of samples. ``randomize`` spreads a
    tie uniformly over the samples equal to the observation instead of halving it: the form
    for counts, whose ties are many and would otherwise pile the transforms on a few values."""
    g = np.random.default_rng(seed)
    out = []
    for o, row in zip(observed, samples):
        s = np.asarray(row, dtype=float)
        if s.size == 0:
            out.append(0.5)
            continue
        below = float(np.sum(s < o)) / s.size
        equal = float(np.sum(s == o)) / s.size
        u = float(g.random()) if randomize else 0.5
        out.append(below + u * equal)
    return np.array(out, dtype=float)


def bucket_gate(
    transforms: Sequence[float],
    season: int | str | None = None,
    buckets: int = BUCKETS,
    tol: float = BUCKET_TOL,
    name: str = "team_weeks",
) -> Gate:
    """Gate 1 (and 4 on absences): the transforms' share in each of ``buckets`` equal buckets
    against the ``1 / buckets`` expected, the worst off within ``tol``."""
    t = np.asarray(transforms, dtype=float)
    expected = 1.0 / buckets
    rows = []
    worst = 0.0
    for i in range(buckets):
        lo, hi = i / buckets, (i + 1) / buckets
        inside = (t >= lo) & ((t < hi) if i < buckets - 1 else (t <= hi))
        share = float(inside.mean()) if t.size else 0.0
        worst = max(worst, abs(share - expected))
        rows.append({"from": lo, "to": hi, "share": share, "count": int(inside.sum())})
    return Gate(
        name,
        t.size > 0 and worst <= tol,
        season,
        {"buckets": rows, "worst": worst, "n": int(t.size), "tol": tol},
    )


def absence_gate(
    missed: Sequence[float],
    samples: Sequence[Sequence[float]],
    season: int | str | None = None,
    buckets: int = BUCKETS,
    tol: float = BUCKET_TOL,
    seed: int = 0,
) -> Gate:
    """Gate 4: each team-week's player-games missed against the hazard's samples for it, as
    randomized transforms (counts) in buckets."""
    return bucket_gate(
        pits(missed, samples, randomize=True, seed=seed), season, buckets, tol, name="absences"
    )


def surrogate_gate(
    matches: Sequence[bool],
    season: int | str | None = None,
    needed: int = SURROGATE_NEEDED,
    of: int = SURROGATE_OF,
) -> Gate:
    """Gate 5: the surrogate's set equal to the exact set on ``needed`` of the ``of`` sampled
    league-days."""
    m = [bool(x) for x in matches][:of]
    return Gate(
        "surrogate",
        len(m) == of and sum(m) >= needed,
        season,
        {"matched": sum(m), "of": len(m), "needed": needed},
    )
