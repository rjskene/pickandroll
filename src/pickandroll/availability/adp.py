"""Availability curves from average draft position.

P(player still available at overall pick k) is modelled as ``1 - Phi((k - adp) / sd)``: the
player is gone once the draft reaches their (noisy) draft position. ``sd`` widens with adp
because late picks are far less predictable than early ones.

During a draft the question is conditional: given the player is still on the board *now*, what
is the chance they last until my pick? That is ``S(k) / S(now)`` with ``S`` the survival curve.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

_SQRT2 = math.sqrt(2.0)

#: The spread of a player's draft slot around his ADP, ``base + growth * adp`` picks. Fitted on
#: league 31822's drafts 2017-2025 in keeper-adjusted space (docs/KEEPERS.md §1.1): the base was
#: 3.0, which made the first rounds about twice as uncertain as they are.
SPREAD_BASE = 1.5
SPREAD_GROWTH = 0.15


def spread_for_adp(adp: float, base: float = SPREAD_BASE, growth: float = SPREAD_GROWTH) -> float:
    """Standard deviation of a player's draft slot as a function of their ADP."""
    return base + growth * adp


def _survival(adp: pd.Series, sd: pd.Series, pick: float) -> pd.Series:
    zed = (pick - adp.astype(float)) / sd.astype(float)
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(zed / _SQRT2))
    return pd.Series(1.0 - cdf, index=adp.index).clip(0.0, 1.0)


def availability(adp: pd.Series, pick: int, spread: pd.Series | None = None) -> pd.Series:
    """Probability each player is still on the board when overall ``pick`` comes up."""
    sd = spread if spread is not None else adp.map(spread_for_adp)
    return _survival(adp, sd, pick)


def availability_curve(adp: pd.Series, picks: Sequence[int]) -> pd.DataFrame:
    """Availability at each of several picks; rows are players, columns are pick numbers."""
    return pd.DataFrame({k: availability(adp, k) for k in picks})


def conditional_availability(
    adp: pd.Series,
    now: int,
    picks: Sequence[int],
    spread: pd.Series | None = None,
    floor: float = 1e-6,
) -> pd.DataFrame:
    """P(available at each of ``picks`` | available at pick ``now``), players by picks.

    A pick at or before ``now`` (my pick is right now) has probability one.
    """
    sd = spread if spread is not None else adp.map(spread_for_adp)
    s_now = _survival(adp, sd, now).clip(lower=floor)
    out = {}
    for k in picks:
        if k <= now:
            out[k] = pd.Series(1.0, index=adp.index)
        else:
            out[k] = (_survival(adp, sd, k) / s_now).clip(0.0, 1.0)
    return pd.DataFrame(out)


def pseudo_adp(order: pd.Series) -> pd.Series:
    """Fallback ADP when no market data exists: rank players by a value column.

    ``order`` is any series where higher means better (for example total z); the best player
    gets ADP 1, the next 2, and so on.
    """
    ranked = order.sort_values(ascending=False)
    return pd.Series(np.arange(1, len(ranked) + 1, dtype=float), index=ranked.index).reindex(
        order.index
    )


def _increasing_fit(y: np.ndarray) -> np.ndarray:
    """The non-decreasing sequence closest to ``y`` in least squares (pool adjacent
    violators): each run that breaks the order is replaced by its mean."""
    means: list[float] = []
    sizes: list[int] = []
    for value in y.astype(float):
        means.append(value)
        sizes.append(1)
        while len(means) > 1 and means[-2] > means[-1]:
            size = sizes[-2] + sizes[-1]
            means[-2] = (means[-2] * sizes[-2] + means[-1] * sizes[-1]) / size
            sizes[-2] = size
            means.pop()
            sizes.pop()
    return np.repeat(means, sizes)


def rank_to_adp(rank: pd.Series, adp: pd.Series) -> pd.Series:
    """ADP on the market's scale for ranked players the ADP list lacks.

    ``rank`` and ``adp`` are keyed by player (lower is earlier in both). The players both know
    give the map: the best non-decreasing fit of ADP on rank over them, read between their ranks
    by linear interpolation and, past the last of them, one pick per rank. A listed player ranked
    past the list's length (the market took him far ahead of the rank) is left out of the fit:
    pooled with the list's last picks, he would flatten the map for every player ranked between.
    Returns the players with a rank and no ADP; empty when fewer than two players are in both."""
    rank = rank.dropna().astype(float)
    adp = adp.dropna().astype(float)
    both = rank.index.intersection(adp.index)
    missing = rank.index.difference(adp.index)
    if len(both) < 2 or missing.empty:
        return pd.Series(dtype=float)
    pairs = pd.DataFrame({"rank": rank[both], "adp": adp[both]}).sort_values(["rank", "adp"])
    inside = pairs[pairs["rank"] <= len(pairs)]
    if len(inside) >= 2:
        pairs = inside
    # One point per rank: tied ranks share their mean ADP before the fit.
    pairs = pairs.groupby("rank", sort=True)["adp"].mean()
    xs = pairs.index.to_numpy(float)
    ys = _increasing_fit(pairs.to_numpy(float))
    wanted = rank[missing].to_numpy(float)
    mapped = np.interp(wanted, xs, ys)
    past = wanted > xs[-1]
    mapped[past] = ys[-1] + (wanted[past] - xs[-1])
    before = wanted < xs[0]
    mapped[before] = np.maximum(1.0, ys[0] - (xs[0] - wanted[before]))
    return pd.Series(mapped, index=missing, dtype=float)
