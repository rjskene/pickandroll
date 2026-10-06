"""Availability from a league's own drafts, by ADP.

A :class:`LeagueSurvivalTable` holds ``S(m | a)``: the share of the league's past drafts in which a
player with (keeper-adjusted) ADP ``a`` was still on the board at market pick ``m``, with the share
never drafted at all alongside. Unlike :class:`~.survival.SurvivalTable` it is keyed by ADP, not by
player, so one table serves every season: a player is looked up by his ADP, interpolated between the
table's whole-number rows.

In a keeper draft both axes live in market space: the ADP is the market's minus the keepers ranked
ahead, and the pick is the overall pick minus the keeper slots before it (``DraftState.market_pick``).
A player who was never drafted is on the board at every pick, so ``S`` never falls below the
undrafted share (a table built with each season's own censoring point can dip below it late).

The table answers only for ADP :data:`LEAGUE_FROM_ADP` and later. Earlier players keep the normal
model, the better read of their sharp survival, which the table's smoothing blurs; later ones get the
table, which carries the undrafted mass the normal model has none of (docs/KEEPERS.md §1.1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

#: The first (keeper-adjusted) ADP the table answers for; earlier players are left to the normal model.
LEAGUE_FROM_ADP = 90


@dataclass(frozen=True)
class LeagueSurvivalTable:
    #: Rows are ADP ``1 .. n``, columns are market picks ``1 .. picks``.
    table: pd.DataFrame
    #: P(never drafted | ADP), on the same rows.
    undrafted: pd.Series

    def __post_init__(self) -> None:
        rows = list(self.table.index)
        if not rows or rows != list(range(1, len(rows) + 1)):
            raise ValueError("rows must be the ADPs 1..n")
        cols = list(self.table.columns)
        if not cols or cols != list(range(1, len(cols) + 1)):
            raise ValueError("pick columns must be 1..n")
        if list(self.undrafted.index) != rows:
            raise ValueError("undrafted must have one value per ADP row")
        values = np.concatenate(
            [self.table.to_numpy(float).ravel(), self.undrafted.to_numpy(float)]
        )
        if np.isnan(values).any() or (values < 0).any() or (values > 1).any():
            raise ValueError("shares must lie in 0..1")

    @property
    def picks(self) -> int:
        return len(self.table.columns)

    @property
    def max_adp(self) -> int:
        return len(self.table.index)

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> LeagueSurvivalTable:
        """A table as written: an ``adp`` column of whole numbers, the pick columns ``1 .. n``
        and an ``undrafted`` column."""
        if "adp" not in frame.columns or "undrafted" not in frame.columns:
            raise ValueError("needs an adp column and an undrafted column")
        body = frame.drop(columns=["adp", "undrafted"])
        try:
            body.columns = [int(c) for c in body.columns]
            index = [int(a) for a in frame["adp"]]
        except (TypeError, ValueError) as exc:
            raise ValueError("adp rows and pick columns must be whole numbers") from exc
        if any(float(a) != float(b) for a, b in zip(frame["adp"], index, strict=True)):
            raise ValueError("adp rows must be whole numbers")
        body.index = pd.Index(index, name="adp")
        undrafted = pd.Series(frame["undrafted"].to_numpy(float), index=body.index)
        return cls(table=body.astype(float).copy(), undrafted=undrafted)

    def survival(self, adp: pd.Series, pick: int) -> pd.Series:
        """``S(pick | adp)`` for each player, never below the undrafted share; NaN for an ADP
        before :data:`LEAGUE_FROM_ADP` or past the table (the caller keeps its own model there)."""
        col = min(max(int(pick), 1), self.picks)
        floor = np.maximum(self.table[col].to_numpy(float), self.undrafted.to_numpy(float))
        rows = self.table.index.to_numpy(float)
        x = adp.to_numpy(float)
        values = np.interp(x, rows, floor, left=np.nan, right=np.nan)
        values[x < LEAGUE_FROM_ADP] = np.nan
        return pd.Series(values, index=adp.index)

    def conditional(
        self, adp: pd.Series, now: int, picks: Sequence[int], floor: float = 1e-6
    ) -> pd.DataFrame:
        """P(available at each of ``picks`` | available at ``now``), players by picks, all in
        market picks. Picks at or before ``now`` have probability one; a player the table does not
        answer for (see :meth:`survival`) is NaN throughout."""
        s_now = self.survival(adp, now)
        known = s_now.notna()
        s_now = s_now.clip(lower=floor)
        out = {}
        for k in picks:
            if k <= now:
                out[k] = pd.Series(1.0, index=adp.index)
            else:
                out[k] = (self.survival(adp, k) / s_now).clip(0.0, 1.0)
        frame = pd.DataFrame(out, index=adp.index)
        frame.loc[~known] = np.nan
        return frame
