"""The gates a verdict waits on (#172, PR 1), as pure functions on arrays; the script reads the
recorded weeks, the box scores and the hold-out season and calls them with the season each is
scored on, so the gates on the hold-out and on this season's recorded weeks stand side by side.

1. Team weeks: every team's weekly totals as probability integral transforms under the
   simulator's team-week distribution; no bucket of 20 points off by more than 5.
2. Matchup odds: the simulator's odds from the week's first day scored by Brier beside the
   engine's analytic odds; not worse by more than 0.01.
3. Realized share: the scorecard's share over the scored moves inside the simulator's central
   80% band for the same moves.
4. Absences: player-games missed a team-week against the hazard, as transforms in buckets.
5. Surrogate: its set equals the exact set on four of five sampled league-days.
6. Belief refresh: the fitted ``kappa`` against this season's recorded week-to-week projection
   changes, once the recorder has enough weeks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

BUCKETS = 5
BUCKET_TOL = 0.05
BRIER_TOL = 0.01
CENTRAL = 0.80
SURROGATE_NEEDED = 4
SURROGATE_OF = 5
REFRESH_BOOTSTRAPS = 500


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


def brier(odds: Sequence[float], outcomes: Sequence[float]) -> float:
    o, y = np.asarray(odds, dtype=float), np.asarray(outcomes, dtype=float)
    return float(np.mean((o - y) ** 2)) if o.size else float("nan")


def brier_gate(
    sim: float, engine: float, season: int | str | None = None, tol: float = BRIER_TOL
) -> Gate:
    """Gate 2: the simulator's Brier not worse than the engine's by more than ``tol``."""
    return Gate(
        "matchup_odds", sim <= engine + tol, season, {"sim": sim, "engine": engine, "tol": tol}
    )


def band(samples: Sequence[float], central: float = CENTRAL) -> tuple[float, float]:
    s = np.asarray(samples, dtype=float)
    lo, hi = (1 - central) / 2, 1 - (1 - central) / 2
    return float(np.quantile(s, lo)), float(np.quantile(s, hi))


def band_gate(
    realized: float,
    samples: Sequence[float],
    season: int | str | None = None,
    central: float = CENTRAL,
    name: str = "realized_share",
) -> Gate:
    """Gate 3: the realized figure inside the simulator's central band for the same moves."""
    lo, hi = band(samples, central)
    return Gate(
        name,
        lo <= realized <= hi,
        season,
        {"realized": realized, "low": lo, "high": hi, "central": central, "n": len(samples)},
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


def implied_kappa(gaps: Sequence[float], steps: Sequence[float]) -> float:
    """The weekly refresh the recorded steps imply: the step regressed through the origin on
    the gap to the realized rate (both log scale, a week apart)."""
    x, y = np.asarray(gaps, dtype=float), np.asarray(steps, dtype=float)
    return float(np.sum(x * y) / np.sum(x * x)) if np.any(x != 0) else 0.0


def refresh_gate(
    kappa: float,
    gaps: Sequence[float],
    steps: Sequence[float],
    season: int | str | None = None,
    central: float = CENTRAL,
    bootstraps: int = REFRESH_BOOTSTRAPS,
    seed: int = 0,
    min_pairs: int = 20,
) -> Gate:
    """Gate 6: the fitted ``kappa`` inside the central band of the refresh the recorded
    week-to-week projection changes imply, bootstrapped over the pairs; not run (failed, with
    the reason) under ``min_pairs`` pairs."""
    x, y = np.asarray(gaps, dtype=float), np.asarray(steps, dtype=float)
    if x.size < min_pairs:
        return Gate(
            "belief_refresh",
            False,
            season,
            {"reason": "too few pairs", "n": int(x.size), "min_pairs": min_pairs},
        )
    g = np.random.default_rng(seed)
    draws = []
    for _ in range(bootstraps):
        idx = g.integers(0, x.size, x.size)
        draws.append(implied_kappa(x[idx], y[idx]))
    lo, hi = band(draws, central)
    return Gate(
        "belief_refresh",
        lo <= kappa <= hi,
        season,
        {"kappa": kappa, "implied": implied_kappa(x, y), "low": lo, "high": hi, "n": int(x.size)},
    )
