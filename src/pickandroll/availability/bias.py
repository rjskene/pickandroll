"""A mean shift for the ADP model by keeper-adjusted ADP, from the league's own drafts (#64).

The normal model centres a player's draft slot on his ADP. League 31822 runs behind the market from
about the eighth round: in the 2026 draft players with an effective ADP past 85 went 10-12 picks
after it, and 40-50 percent of them went undrafted. An :class:`AdpBias` holds the league's mean
residual, market pick minus effective ADP, at the centre of each effective-ADP bucket. The model
then centres each player on ``adp + bias(adp)`` (``DraftState.availability``): linear between the
centres, flat past the first and the last.

The fit reads the history archive in keeper-adjusted space (docs/KEEPERS.md §1.1).
:func:`observations` turns each season into its players with their effective ADP and the market
pick each went at (none for a player never drafted). :func:`fit` weights each season by its
distance from the target season and averages the drafted players' residuals by bucket.
:func:`held_out` fits on all seasons but one and scores the fit's availability on the one left
out, for each season in turn: the Brier score of ``S(m)`` over every market pick, bucket by bucket.
:func:`choose` picks the half-life and the first ADP with a shift by that score. It takes the
lowest total among the fits no worse than the plain formula in any bucket. A bucket whose centre
lies before that ADP gets no shift: out of sample its residual cost more than it gave.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .adp import SPREAD_BASE, SPREAD_GROWTH

#: Effective-ADP bucket edges, the analysis's buckets for the 2026-10-14 draft.
EDGES: tuple[float, ...] = (0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120, 135, 160)
#: A bucket with fewer drafted players than this is left out of a fit.
MIN_DRAFTED = 10
#: The fits :func:`choose` compares: season half-lives (``None`` weighs every season alike) and
#: the first effective ADP with a shift.
HALF_LIVES: tuple[float | None, ...] = (1.0, 2.0, 3.0, None)
FROM_ADPS: tuple[float, ...] = (0.0, 48.0, 60.0, 72.0, 84.0, 96.0)

_SQRT2 = math.sqrt(2.0)
_erf = np.vectorize(math.erf, otypes=[float])


@dataclass(frozen=True)
class AdpBias:
    """The league's mean residual (market pick minus effective ADP) at each bucket centre."""

    centers: tuple[float, ...]
    values: tuple[float, ...]
    #: Buckets whose centre lies before this ADP carry no shift.
    from_adp: float = 0.0
    #: The fit's season weighting: a season ``half_life`` years from the target counts half;
    #: ``None`` weighs every season alike.
    half_life: float | None = None
    seasons: tuple[int, ...] = ()
    target: int | None = None
    #: Drafted players behind each centre.
    counts: tuple[int, ...] = field(default=())

    def __post_init__(self) -> None:
        centers = np.asarray(self.centers, float)
        values = np.asarray(self.values, float)
        if centers.size == 0 or centers.shape != values.shape:
            raise ValueError("needs one value per bucket centre, and at least one centre")
        if not (np.isfinite(centers).all() and np.isfinite(values).all()):
            raise ValueError("centres and values must be finite")
        if (np.diff(centers) <= 0).any():
            raise ValueError("bucket centres must increase")
        if self.counts and len(self.counts) != centers.size:
            raise ValueError("needs one count per bucket centre")

    def shift(self, adp: pd.Series) -> pd.Series:
        """The shift for each effective ADP: linear between the centres, flat past the ends,
        zero for a missing ADP."""
        x = adp.to_numpy(float)
        out = np.interp(x, np.asarray(self.centers, float), np.asarray(self.values, float))
        out[np.isnan(x)] = 0.0
        return pd.Series(out, index=adp.index)

    def apply(self, adp: pd.Series) -> pd.Series:
        """The effective ADP the normal model centres on: ``adp + shift(adp)``."""
        return adp.astype(float) + self.shift(adp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "centers": [round(float(c), 4) for c in self.centers],
            "values": [round(float(v), 4) for v in self.values],
            "counts": [int(n) for n in self.counts],
            "from_adp": float(self.from_adp),
            "half_life": None if self.half_life is None else float(self.half_life),
            "seasons": [int(s) for s in self.seasons],
            "target": self.target,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdpBias:
        try:
            centers = tuple(float(c) for c in data["centers"])
            values = tuple(float(v) for v in data["values"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("needs centers and values, lists of numbers") from exc
        half_life = data.get("half_life")
        target = data.get("target")
        return cls(
            centers=centers,
            values=values,
            from_adp=float(data.get("from_adp") or 0.0),
            half_life=None if half_life is None else float(half_life),
            seasons=tuple(int(s) for s in data.get("seasons") or ()),
            target=None if target is None else int(target),
            counts=tuple(int(n) for n in data.get("counts") or ()),
        )


# --------------------------------------------------------------------------- fitting
def observations(
    picks: pd.DataFrame, adp: pd.DataFrame, seasons: Iterable[int] | None = None
) -> pd.DataFrame:
    """The archive's players by season, keepers left out, in market space.

    ``picks`` is the archive's ``picks_with_adp`` (``draft_year``, ``overall``, ``avg_pick``,
    ``adp_player``, ``keeper_any``) and ``adp`` its ``adp`` list (``draft_year``, ``player``,
    ``avg_pick``). A player's effective ADP is his ADP minus the keepers with a lower ADP, and his
    market pick is his overall pick minus the keeper slots before it; a listed player nobody
    drafted has none. Columns: ``season``, ``player``, ``adp``, ``adp_eff``, ``market_pick``
    (NaN: never drafted) and ``market_picks``, the season's picks that were not keepers."""
    wanted = None if seasons is None else {int(s) for s in seasons}
    rows: list[dict[str, Any]] = []
    for season, p in picks.groupby("draft_year", sort=True):
        if wanted is not None and int(season) not in wanted:
            continue
        kept = p[p["keeper_any"].astype(bool)]
        kept_adp = np.sort(kept["avg_pick"].dropna().to_numpy(float))
        kept_slots = np.sort(kept["overall"].to_numpy(int))
        market_picks = len(p) - len(kept_slots)
        drafted = p[~p["keeper_any"].astype(bool) & p["adp_player"].notna()]
        went = dict(zip(drafted["adp_player"], drafted["overall"], strict=True))
        kept_names = set(kept["adp_player"].dropna())
        listed = adp[(adp["draft_year"] == season) & adp["avg_pick"].notna()]
        for name, value in zip(listed["player"], listed["avg_pick"].astype(float), strict=True):
            if name in kept_names:
                continue
            overall = went.get(name)
            rows.append(
                {
                    "season": int(season),
                    "player": name,
                    "adp": value,
                    "adp_eff": value - float(np.searchsorted(kept_adp, value, side="left")),
                    "market_pick": (
                        np.nan
                        if overall is None
                        else float(overall - np.searchsorted(kept_slots, overall, side="left"))
                    ),
                    "market_picks": market_picks,
                }
            )
    columns = ["season", "player", "adp", "adp_eff", "market_pick", "market_picks"]
    return pd.DataFrame(rows, columns=columns)


def _weights(seasons: pd.Series, target: int, half_life: float | None) -> np.ndarray:
    if half_life is None:
        return np.ones(len(seasons))
    return 0.5 ** (np.abs(seasons.to_numpy(float) - target) / half_life)


def fit(
    obs: pd.DataFrame,
    target: int,
    half_life: float | None = None,
    from_adp: float = 0.0,
    edges: Sequence[float] = EDGES,
    min_drafted: int = MIN_DRAFTED,
) -> AdpBias:
    """The weighted mean residual of the drafted players, bucket by bucket: each bucket's centre
    is its players' weighted mean effective ADP. A bucket with fewer than ``min_drafted`` drafted
    players is left out, and one whose centre lies before ``from_adp`` carries no shift."""
    drafted = obs[obs["market_pick"].notna()]
    seasons = tuple(sorted(int(s) for s in drafted["season"].unique()))
    w = _weights(drafted["season"], target, half_life)
    eff = drafted["adp_eff"].to_numpy(float)
    resid = drafted["market_pick"].to_numpy(float) - eff
    bucket = np.digitize(eff, edges[1:-1], right=True)
    inside = (eff >= edges[0]) & (eff <= edges[-1])
    centers, values, counts = [], [], []
    for b in range(len(edges) - 1):
        mask = inside & (bucket == b)
        if mask.sum() < min_drafted:
            continue
        weight = w[mask].sum()
        center = float((w[mask] * eff[mask]).sum() / weight)
        value = float((w[mask] * resid[mask]).sum() / weight)
        centers.append(center)
        values.append(0.0 if center < from_adp else value)
        counts.append(int(mask.sum()))
    if not centers:
        raise ValueError("no bucket has enough drafted players to fit")
    return AdpBias(
        centers=tuple(centers),
        values=tuple(values),
        from_adp=from_adp,
        half_life=half_life,
        seasons=seasons,
        target=target,
        counts=tuple(counts),
    )


def survival_curve(
    mu: np.ndarray, picks: np.ndarray, base: float = SPREAD_BASE, growth: float = SPREAD_GROWTH
) -> np.ndarray:
    """``S(m) = 1 - Phi((m - mu) / (base + growth * mu))``, players by picks."""
    mu = np.asarray(mu, float)[:, None]
    zed = (np.asarray(picks, float)[None, :] - mu) / (base + growth * mu)
    return 1.0 - 0.5 * (1.0 + _erf(zed / _SQRT2))


def held_out(
    obs: pd.DataFrame,
    half_life: float | None = None,
    from_adp: float = 0.0,
    base: float = SPREAD_BASE,
    growth: float = SPREAD_GROWTH,
    edges: Sequence[float] = EDGES,
    min_drafted: int = MIN_DRAFTED,
) -> pd.DataFrame:
    """Each season held out in turn: the fit on the others (weighted toward it) against the plain
    formula, on its players over market picks ``1 .. market_picks``. A player is on the board at
    pick ``m`` when his market pick is ``m`` or later, or he was never drafted. One row per
    bucket: ``players``, ``terms`` (player-picks), the mean squared error of the plain formula
    (``plain``) and of the shifted one (``biased``)."""
    labels = [f"{edges[i]:g}-{edges[i + 1]:g}" for i in range(len(edges) - 1)]
    sums = {label: [0, 0, 0.0, 0.0] for label in labels}
    for season in sorted(obs["season"].unique()):
        rest = obs[obs["season"] != season]
        if rest["market_pick"].notna().sum() == 0:
            continue
        bias = fit(rest, int(season), half_life, from_adp, edges, min_drafted)
        mine = obs[(obs["season"] == season) & obs["adp_eff"].between(edges[0], edges[-1])]
        if mine.empty:
            continue
        picks = np.arange(1, int(mine["market_picks"].iloc[0]) + 1)
        eff = mine["adp_eff"].to_numpy(float)
        went = mine["market_pick"].fillna(np.inf).to_numpy(float)
        on_board = (went[:, None] >= picks[None, :]).astype(float)
        plain = ((survival_curve(eff, picks, base, growth) - on_board) ** 2).sum(axis=1)
        shifted = bias.apply(mine["adp_eff"]).to_numpy(float)
        biased = ((survival_curve(shifted, picks, base, growth) - on_board) ** 2).sum(axis=1)
        bucket = np.digitize(eff, edges[1:-1], right=True)
        for b, p0, p1 in zip(bucket, plain, biased, strict=True):
            row = sums[labels[b]]
            row[0] += 1
            row[1] += len(picks)
            row[2] += p0
            row[3] += p1
    out = pd.DataFrame(
        [
            {
                "bucket": label,
                "players": n,
                "terms": terms,
                "plain": p0 / terms if terms else np.nan,
                "biased": p1 / terms if terms else np.nan,
            }
            for label, (n, terms, p0, p1) in sums.items()
        ]
    )
    return out[out["players"] > 0].set_index("bucket")


@dataclass(frozen=True)
class Choice:
    half_life: float | None
    from_adp: float
    #: The held-out score of the choice (:func:`held_out`).
    scores: pd.DataFrame
    #: Every fit compared: half_life, from_adp, total plain and biased, worst bucket change.
    grid: pd.DataFrame


def choose(
    obs: pd.DataFrame,
    half_lives: Sequence[float | None] = HALF_LIVES,
    from_adps: Sequence[float] = FROM_ADPS,
    base: float = SPREAD_BASE,
    growth: float = SPREAD_GROWTH,
    edges: Sequence[float] = EDGES,
    min_drafted: int = MIN_DRAFTED,
) -> Choice | None:
    """The fit with the lowest held-out Brier over all buckets among those no worse than the plain
    formula in any bucket; ``None`` when every fit is worse somewhere."""
    rows, best = [], None
    for half_life in half_lives:
        for from_adp in from_adps:
            scores = held_out(obs, half_life, from_adp, base, growth, edges, min_drafted)
            terms = scores["terms"].sum()
            plain = float((scores["plain"] * scores["terms"]).sum() / terms)
            biased = float((scores["biased"] * scores["terms"]).sum() / terms)
            worst = float((scores["biased"] - scores["plain"]).max())
            rows.append(
                {
                    "half_life": half_life,
                    "from_adp": from_adp,
                    "plain": plain,
                    "biased": biased,
                    "worst_bucket": worst,
                }
            )
            if worst <= 1e-12 and (best is None or biased < best[0]):
                best = (biased, half_life, from_adp, scores)
    grid = pd.DataFrame(rows)
    grid["half_life"] = pd.Series([r["half_life"] for r in rows], dtype=object)  # None, not NaN
    if best is None:
        return None
    return Choice(half_life=best[1], from_adp=best[2], scores=best[3], grid=grid)


def market_to_overall(market: float, keeper_slots: Sequence[int], total: int) -> float:
    """Market pick ``market`` as an overall pick: the market-th slot that is not a keeper's,
    linear between slots, one pick per market pick before the first and past the last."""
    slots = [k for k in range(1, total + 1) if k not in set(keeper_slots)]
    if market <= 1:
        return float(slots[0]) + (market - 1)
    if market >= len(slots):
        return float(slots[-1]) + (market - len(slots))
    lo = math.floor(market)
    return slots[lo - 1] + (market - lo) * (slots[lo] - slots[lo - 1])
