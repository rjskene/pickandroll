"""Games haircuts: a player's projected totals scaled to the games he is now expected to play.

Projections are per game times games (``schema``: totals over the horizon), so news that a
player will miss games is a scale on his whole line: every counting stat, the makes and attempts
behind the percentages, his minutes and his games. His per-game numbers and his percentages
stay as projected. The z-scores are then recomputed over the scaled table (the pool's means move
with him), and the plan is solved again on them.

A haircut is a fraction of the projected games kept, in ``[0, 1]``: ``games_fraction`` given
outright, or ``1 - games_out / games`` from a number of games out. A fraction of one is no
haircut at all.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from .schema import STAT_COLS, Cat

#: The columns a haircut scales: the totals, the minutes and games behind them, and a points
#: league's fantasy points (a weighted sum of the totals, so it scales the same way).
SCALED_COLS: tuple[str, ...] = (*STAT_COLS, "minutes", "games", Cat.FPTS.value)


def games_fraction(games: float, games_out: float) -> float:
    """The share of ``games`` a player keeps when he misses ``games_out`` of them (0 when he
    misses them all, or has none projected)."""
    if games_out < 0:
        raise ValueError(f"games out must be zero or more, not {games_out}")
    if games <= 0:
        return 0.0
    return max(0.0, 1.0 - float(games_out) / float(games))


def scale_games(df: pd.DataFrame, fractions: Mapping[str, float]) -> pd.DataFrame:
    """A copy of the projection table ``df`` with each listed player's totals scaled by his
    fraction of games kept. Raises ``KeyError`` for a player ``df`` does not hold and
    ``ValueError`` for a fraction outside ``[0, 1]``."""
    unknown = [pid for pid in fractions if pid not in df.index]
    if unknown:
        raise KeyError(f"no projected player {', '.join(map(str, unknown))}")
    bad = {pid: f for pid, f in fractions.items() if not 0.0 <= float(f) <= 1.0}
    if bad:
        raise ValueError(f"a games fraction is between 0 and 1: {bad}")
    out = df.copy()
    if not fractions:
        return out
    scale = pd.Series(1.0, index=df.index)
    scale[list(fractions)] = [float(f) for f in fractions.values()]
    for col in SCALED_COLS:
        if col in out.columns:
            out[col] = out[col].astype(float) * scale
    return out
