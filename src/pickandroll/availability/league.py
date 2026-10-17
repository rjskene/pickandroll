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


#: A table row answers only when at least this many observed players have an ADP within its
#: kernel's bandwidth (``fit_survival_table``); a thin row is left to the ADP formula.
MIN_COUNT = 20


def bandwidth(adp: float) -> float:
    """The Gaussian kernel's bandwidth at an ADP: the archive's (5 + 0.08 ADP), wider late,
    where the market's ADPs spread out."""
    return 5.0 + 0.08 * float(adp)


def survival_counts(adp: Sequence[float], rows: Sequence[int]) -> pd.Series:
    """For each ADP row, the observed players whose ADP lies within the row's bandwidth."""
    x = np.asarray(adp, dtype=float)
    return pd.Series(
        [int((np.abs(x - a) <= bandwidth(a)).sum()) for a in rows],
        index=pd.Index(list(rows), name="adp"),
        dtype=int,
    )


def fit_survival_table(
    adp: Sequence[float],
    overall: Sequence[float],
    picks: int,
    min_count: int = MIN_COUNT,
) -> tuple[LeagueSurvivalTable | None, pd.Series]:
    """``S(m | a)`` from observed drafts, one observation per player with an ADP per draft:
    his ADP and the overall pick that took him (NaN when he went undrafted, so he survives
    every pick). Each row is the kernel-weighted share of players still on the board, the
    archive's smoothing (``bandwidth``). The table keeps the rows from ADP 1 up to the last of
    an unbroken run, from :data:`LEAGUE_FROM_ADP` on, whose counts clear ``min_count``
    (``survival_counts``); past it, and before :data:`LEAGUE_FROM_ADP`, the ADP formula answers.
    Returns the table (``None`` when the first row it would answer is already thin) and the
    counts of every row looked at."""
    a_obs = np.asarray(adp, dtype=float)
    y = np.asarray(overall, dtype=float)
    if a_obs.shape != y.shape or not len(a_obs) or np.isnan(a_obs).any():
        raise ValueError("needs one ADP and one pick (NaN if undrafted) per observation")
    if picks < 1:
        raise ValueError("picks must be at least 1")
    top = max(int(np.ceil(a_obs.max() + bandwidth(a_obs.max()))), LEAGUE_FROM_ADP)
    counts = survival_counts(a_obs, range(1, top + 1))
    last = None
    for a in range(LEAGUE_FROM_ADP, top + 1):
        if counts[a] < min_count:
            break
        last = a
    if last is None:
        return None, counts
    undrafted = np.isnan(y)
    ks = np.arange(1, picks + 1)
    alive = ((y[:, None] >= ks[None, :]) | undrafted[:, None]).astype(float)
    rows, und = {}, {}
    for a in range(1, last + 1):
        w = np.exp(-0.5 * ((a_obs - a) / bandwidth(a)) ** 2)
        total = float(w.sum())
        if total <= 0.0:
            raise ValueError(f"no observation weighs on ADP {a}")
        # Clipped: a weighted share of ones can round a hair past 1.
        rows[a] = np.clip((w @ alive) / total, 0.0, 1.0)
        und[a] = min(max(float(w @ undrafted.astype(float)) / total, 0.0), 1.0)
    table = pd.DataFrame.from_dict(rows, orient="index", columns=[int(k) for k in ks])
    table.index = pd.Index(list(rows), name="adp")
    return LeagueSurvivalTable(table=table, undrafted=pd.Series(und)), counts


def survival_frame(table: LeagueSurvivalTable) -> pd.DataFrame:
    """The table as written: ``adp, 1..N, undrafted`` (what :meth:`LeagueSurvivalTable.from_frame`
    reads back)."""
    frame = table.table.copy()
    frame["undrafted"] = table.undrafted.to_numpy(float)
    return frame.reset_index()
