"""Availability curves from simulated drafts.

The ADP model in :mod:`.adp` assumes a player's draft slot is normal around their ADP. A
:class:`SurvivalTable` replaces that assumption with the record of many simulated drafts: for
every player and every overall pick ``k``, the fraction of drafts in which the player was still
on the board when pick ``k`` came up (``S[p, k] = P(pick number of p >= k)``). A player never
drafted in a simulation is treated as taken at ``total_picks + 1``, so they survive every pick.

The planner needs the conditional form: given the player is still available *now*, the chance
they last until a later pick is ``S[p, k] / S[p, now]``. A player who has outlived every
simulation (``S[p, now]`` is zero) gets no credit for lasting any longer.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SurvivalTable:
    #: Rows are players, columns are overall pick numbers ``1 .. total_picks + 1``.
    table: pd.DataFrame
    sims: int

    def __post_init__(self) -> None:
        if self.sims <= 0:
            raise ValueError("sims must be positive")
        cols = list(self.table.columns)
        if cols != list(range(1, len(cols) + 1)):
            raise ValueError("survival columns must be the picks 1..total_picks + 1")

    @property
    def total_picks(self) -> int:
        return len(self.table.columns) - 1

    @classmethod
    def from_pick_numbers(
        cls,
        picks: pd.DataFrame,
        total_picks: int,
        sims: int,
        players: Iterable[str] | None = None,
    ) -> SurvivalTable:
        """Build the table from a long record of simulated picks with columns ``sim``,
        ``player`` and ``overall``. ``sims`` is the number of simulated drafts, which fixes
        the mass of the never-drafted outcome; ``players`` adds rows for players who were
        never drafted at all."""
        if not {"sim", "player", "overall"} <= set(picks.columns):
            raise ValueError("picks needs sim, player and overall columns")
        drafted = picks.groupby("player")["sim"].nunique()
        if (drafted > sims).any():
            raise ValueError("a player was drafted more often than there are simulations")
        counts = pd.crosstab(picks["player"], picks["overall"].astype(int))
        counts = counts.reindex(columns=range(1, total_picks + 1), fill_value=0)
        counts[total_picks + 1] = sims - drafted.reindex(counts.index).fillna(0).astype(int)
        if players is not None:
            index = counts.index.union(pd.Index(list(players)))
            counts = counts.reindex(index)
            missing = counts[total_picks + 1].isna()
            counts = counts.fillna(0)
            counts.loc[missing, total_picks + 1] = sims
        # S[p, k] = share of drafts where p went at pick k or later.
        survival = counts.iloc[:, ::-1].cumsum(axis=1).iloc[:, ::-1] / float(sims)
        survival.columns = [int(c) for c in survival.columns]
        survival.index.name = "player_id"
        return cls(table=survival.astype(float), sims=int(sims))

    def survival(self, players: Sequence[str], pick: int) -> pd.Series:
        """``S[p, pick]`` for each player; players not in the table are NaN."""
        col = min(max(int(pick), 1), self.total_picks + 1)
        return self.table[col].reindex(list(players))

    def conditional(
        self, players: Sequence[str], now: int, picks: Sequence[int], floor: float | None = None
    ) -> pd.DataFrame:
        """P(available at each of ``picks`` | available at ``now``), players by picks. Picks at
        or before ``now`` have probability one; players not in the table are NaN."""
        floor = 1.0 / self.sims if floor is None else floor
        s_now = self.survival(players, now).clip(lower=floor)
        out = {}
        for k in picks:
            if k <= now:
                out[k] = pd.Series(1.0, index=list(players))
            else:
                out[k] = (self.survival(players, k) / s_now).clip(0.0, 1.0)
        frame = pd.DataFrame(out)
        known = self.table.index.intersection(list(players))
        frame.loc[~frame.index.isin(known)] = np.nan
        return frame

    def median_pick(self) -> pd.Series:
        """The pick by which half the simulations had taken each player (ADP on the same
        scale as the market's): the first ``k`` with ``S[p, k + 1] < 0.5``."""
        below = self.table.lt(0.5)
        first = below.idxmax(axis=1).astype(float) - 1.0
        first[~below.any(axis=1)] = float(self.total_picks + 1)
        return first

    def save(self, path: Path) -> None:
        frame = self.table.copy()
        frame.index.name = "player_id"
        frame.to_csv(path)
        Path(str(path) + ".sims").write_text(str(self.sims))

    @classmethod
    def load(cls, path: Path) -> SurvivalTable:
        frame = pd.read_csv(path, index_col="player_id")
        frame.columns = [int(c) for c in frame.columns]
        sims = int(Path(str(path) + ".sims").read_text().strip())
        return cls(table=frame.astype(float), sims=sims)
