"""Availability curves from average draft position.

P(player still available at overall pick k) is modelled as ``1 - Phi((k - adp) / sd)``: the
player is gone once the draft reaches their (noisy) draft position. ``sd`` widens with adp
because late picks are far less predictable than early ones.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def spread_for_adp(adp: float, base: float = 3.0, growth: float = 0.15) -> float:
    """Standard deviation of a player's draft slot as a function of their ADP."""
    return base + growth * adp


def availability(adp: pd.Series, pick: int, spread: pd.Series | None = None) -> pd.Series:
    """Probability each player is still on the board when overall ``pick`` comes up."""
    sd = spread if spread is not None else adp.map(spread_for_adp)
    zed = (pick - adp) / sd
    cdf = 0.5 * (1.0 + np.vectorize(math.erf)(zed / math.sqrt(2.0)))
    return pd.Series(1.0 - cdf, index=adp.index).clip(0.0, 1.0)


def availability_curve(adp: pd.Series, picks: list[int]) -> pd.DataFrame:
    """Availability at each of several picks; rows are players, columns are pick numbers."""
    return pd.DataFrame({k: availability(adp, k) for k in picks})
