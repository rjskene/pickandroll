"""Z-scores over a draft pool.

Counting categories use the usual ``(x - mean) / std`` over the pool. Percentage categories use
*impact*: ``makes - pool_pct * attempts``, which is the number of makes a player adds above what a
pool-average shooter would produce on the same attempts. Summing impact across a roster and
dividing by summed attempts recovers the team percentage exactly, which is why the optimizer can
treat FG% and FT% linearly. Turnovers are negated so that higher is better in every column.

The pool is chosen iteratively: score everybody, keep the top ``pool_size`` by total z, recompute
the pool statistics from those players only, repeat. Two or three passes is enough to converge.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from .schema import NEGATIVE_CATS, NINE_CAT, PCT_CATS, PCT_COMPONENTS, Cat


def _safe_std(values: pd.Series) -> float:
    std = float(values.std(ddof=0))
    return std if std > 0 else 1.0


def category_values(df: pd.DataFrame, cats: Sequence[Cat] = NINE_CAT) -> pd.DataFrame:
    """Raw per-player values used for z-scoring: counting totals and percentage impact.

    Impact for percentage categories is computed against the pool average of ``df`` itself, so
    call this with the pool, or use :func:`zscores` which handles pool selection.
    """
    out = pd.DataFrame(index=df.index)
    for cat in cats:
        if cat in PCT_CATS:
            makes, attempts = PCT_COMPONENTS[cat]
            total_att = float(df[attempts].sum())
            pool_pct = float(df[makes].sum()) / total_att if total_att > 0 else 0.0
            out[cat.value] = df[makes] - pool_pct * df[attempts]
        else:
            out[cat.value] = df[cat.value].astype(float)
    return out


def zscores(
    df: pd.DataFrame,
    cats: Sequence[Cat] = NINE_CAT,
    pool_size: int | None = None,
    iterations: int = 3,
    weights: Mapping[Cat, float] | None = None,
) -> pd.DataFrame:
    """Z-score every player in ``df`` against a draft pool.

    Returns a DataFrame indexed like ``df`` with one column per category (higher is better) plus
    ``total``. Players with zero games get zero in every category.
    """
    if pool_size is not None and pool_size < 2:
        raise ValueError("pool_size must be at least 2")
    weights = dict(weights or {})

    eligible = df[df["games"] > 0]
    pool_index = eligible.index
    z = pd.DataFrame(0.0, index=df.index, columns=[c.value for c in cats] + ["total"])

    passes = iterations if pool_size is not None else 1
    for _ in range(passes):
        pool = eligible.loc[pool_index]
        # Percentage impact must be measured against the pool's shooting, then applied to
        # everyone eligible.
        pool_stats: dict[Cat, tuple[float, float, float]] = {}
        for cat in cats:
            if cat in PCT_CATS:
                makes, attempts = PCT_COMPONENTS[cat]
                total_att = float(pool[attempts].sum())
                pool_pct = float(pool[makes].sum()) / total_att if total_att > 0 else 0.0
                impact = pool[makes] - pool_pct * pool[attempts]
                pool_stats[cat] = (pool_pct, float(impact.mean()), _safe_std(impact))
            else:
                values = pool[cat.value].astype(float)
                pool_stats[cat] = (0.0, float(values.mean()), _safe_std(values))

        for cat in cats:
            pct, mean, std = pool_stats[cat]
            if cat in PCT_CATS:
                makes, attempts = PCT_COMPONENTS[cat]
                raw = eligible[makes] - pct * eligible[attempts]
            else:
                raw = eligible[cat.value].astype(float)
            score = (raw - mean) / std
            if cat in NEGATIVE_CATS:
                score = -score
            z.loc[eligible.index, cat.value] = score * weights.get(cat, 1.0)

        z["total"] = z[[c.value for c in cats]].sum(axis=1)
        if pool_size is not None:
            pool_index = z.loc[eligible.index, "total"].nlargest(pool_size).index

    return z


def rank(z: pd.DataFrame, cats: Sequence[Cat] | None = None) -> pd.Series:
    """Total z (higher is better) sorted descending, restricted to ``cats`` when given."""
    cols = [c.value for c in cats] if cats else [c for c in z.columns if c != "total"]
    return z[cols].sum(axis=1).sort_values(ascending=False)


def punt_total(z: pd.DataFrame, punt: Sequence[Cat]) -> pd.Series:
    """Total z with the punted categories removed."""
    cols = [c for c in z.columns if c != "total" and c not in {p.value for p in punt}]
    return z[cols].sum(axis=1)


def as_matrix(z: pd.DataFrame, cats: Sequence[Cat] = NINE_CAT) -> np.ndarray:
    return z[[c.value for c in cats]].to_numpy(dtype=float)
