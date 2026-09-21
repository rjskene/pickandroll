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


def spread_for_adp(adp: float, base: float = 3.0, growth: float = 0.15) -> float:
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
