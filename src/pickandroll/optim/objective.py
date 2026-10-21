"""Category-win objective: value each category total by the chance it beats the field.

The roster and horizon models normally maximize the sum of the category totals ``T_c`` (z-scores,
higher is better). Under a :class:`CategoryCurve` they maximize ``sum_c f_c(T_c)`` instead, with
``f_c(T) = Phi((T - mu_c) / sigma_c)``: the probability that a total of ``T`` beats an opponent
drawn from the league, so the objective reads as the expected number of categories won.
``mu_c`` and ``sigma_c`` are the mean and spread of team totals in the league
(:meth:`CategoryCurve.from_totals`). :meth:`CategoryCurve.simulated` carries the fit from 3000
simulated twelve-team drafts on Basketball Monster projections (the 2026-09-23 study), which is
the default curve for a session; :meth:`CategoryCurve.from_rosters` fits it from a league's
own drafted rosters instead (#65); :meth:`CategoryCurve.default` is the flat zero-mean fallback.

``Phi`` is S-shaped, so the models use a piecewise-linear version with breakpoints at a few
multiples of sigma (:attr:`CategoryCurve.breaks`). The total is split into one bounded piece
per segment and the pieces must fill in order. A maximizer fills a steeper segment before a
flatter one on its own, so a link needs a binary only where the next segment is steeper than
some segment before it; with the flat tails of ``Phi`` that is every link, one binary per
segment boundary and category. The payoff is that a category that cannot be won falls to near
zero marginal value (a soft punt) instead of earning a full z-point for every z-point, as the
plain sum does.

The derivative of the curve, :meth:`CategoryCurve.slope`, is the marginal value of one more
z-point in a category: the number of categories won per z. It prices a change to the plan to
first order and tells a drafter where the next pick should invest.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pulp

from ..projections.schema import Cat

DEFAULT_BREAKS: tuple[float, ...] = (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)
DEFAULT_SIGMA = 4.0
_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)

#: League fit from ``scripts/survival_sim.py``: 3000 simulated twelve-team, thirteen-round
#: drafts (36,000 teams) on Basketball Monster rest-of-season projections of 2026-09-21, every
#: team a z, ADP or LP drafter. Mean and spread of each category's team total in z.
SIMULATED_MU: dict[Cat, float] = {
    Cat.PTS: -0.407,
    Cat.THREES: -0.688,
    Cat.REB: -0.279,
    Cat.AST: 0.067,
    Cat.STL: -0.204,
    Cat.BLK: -0.040,
    Cat.TOV: 0.165,
    Cat.FG_PCT: 0.417,
    Cat.FT_PCT: -0.097,
}
SIMULATED_SIGMA: dict[Cat, float] = {
    Cat.PTS: 3.538,
    Cat.THREES: 4.167,
    Cat.REB: 3.992,
    Cat.AST: 4.012,
    Cat.STL: 3.565,
    Cat.BLK: 3.926,
    Cat.TOV: 4.664,
    Cat.FG_PCT: 4.190,
    Cat.FT_PCT: 4.149,
}
SIMULATED_SOURCE = "simulated league (3000 all-auto drafts, BBM 2026-09-21)"

#: Win odds below ``CONCEDED`` mean the category is lost on the board as it stands; above
#: ``SECURED`` it is won barring surprises; between the two it is in play.
CONCEDED = 0.15
SECURED = 0.85


def phi(x: float) -> float:
    """Standard normal cumulative distribution."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def phi_density(x: float) -> float:
    """Standard normal density."""
    return math.exp(-0.5 * x * x) / _SQRT2PI


def win_label(probability: float) -> str:
    """``conceded``, ``contested`` or ``secured`` for a win probability."""
    if probability < CONCEDED:
        return "conceded"
    if probability > SECURED:
        return "secured"
    return "contested"


@dataclass(frozen=True)
class Segment:
    start: float
    width: float
    slope: float


@dataclass(frozen=True)
class CategoryCurve:
    mu: Mapping[Cat, float]
    sigma: Mapping[Cat, float]
    breaks: tuple[float, ...] = DEFAULT_BREAKS
    #: Where the fit came from, for display.
    source: str = "default"

    def __post_init__(self) -> None:
        if any(s <= 0 for s in self.sigma.values()):
            raise ValueError("sigma must be positive")
        if list(self.breaks) != sorted(self.breaks):
            raise ValueError("breaks must be increasing")

    @classmethod
    def default(
        cls, cats: Iterable[Cat], mu: float = 0.0, sigma: float = DEFAULT_SIGMA
    ) -> CategoryCurve:
        cats = list(cats)
        return cls(mu=dict.fromkeys(cats, mu), sigma=dict.fromkeys(cats, sigma))

    @classmethod
    def simulated(cls, cats: Iterable[Cat], sigma_scale: float = 1.0) -> CategoryCurve:
        """The study's league fit over ``cats`` (a category the fit lacks gets the flat
        default), with every sigma multiplied by ``sigma_scale``."""
        cats = list(cats)
        mu = {c: SIMULATED_MU.get(c, 0.0) for c in cats}
        sigma = {c: SIMULATED_SIGMA.get(c, DEFAULT_SIGMA) for c in cats}
        flat = [c.value for c in cats if c not in SIMULATED_MU]
        if not flat:
            source = SIMULATED_SOURCE
        elif len(flat) == len(cats):
            source = f"flat default (mu 0, sigma {DEFAULT_SIGMA:g}) for {', '.join(flat)}"
        else:
            source = f"{SIMULATED_SOURCE}; flat default for {', '.join(flat)}"
        return cls(mu=mu, sigma=sigma, source=source).scaled(sigma_scale)

    @classmethod
    def from_totals(
        cls,
        totals: pd.DataFrame,
        cats: Iterable[Cat],
        source: str = "fitted",
        weights: Sequence[float] | None = None,
    ) -> CategoryCurve:
        """Fit mu and sigma from a table of team totals, one row per team, one column per
        category (named by ``Cat.value``). ``weights``, one per team (its draft's weight), make
        the mean and the spread weighted ones; equal weights give the plain fit."""
        cats = list(cats)
        missing = [c.value for c in cats if c.value not in totals.columns]
        if missing:
            raise ValueError(f"totals lack columns {missing}")
        if len(totals) < 2:
            raise ValueError("at least two teams are needed to fit a curve")
        if weights is None:
            mu = {c: float(totals[c.value].mean()) for c in cats}
            sigma = {c: float(totals[c.value].std(ddof=1)) for c in cats}
            return cls(mu=mu, sigma=sigma, source=source)
        w = np.asarray(weights, dtype=float)
        if w.shape != (len(totals),) or (w < 0).any() or w.sum() <= 0:
            raise ValueError("needs one weight of zero or more per team, not all zero")
        # Reliability weights: the plain ddof=1 spread when the weights are equal.
        v1, v2 = float(w.sum()), float((w**2).sum())
        mu, sigma = {}, {}
        for c in cats:
            x = totals[c.value].to_numpy(float)
            mu[c] = float(w @ x / v1)
            sigma[c] = float(np.sqrt(w @ (x - mu[c]) ** 2 / (v1 - v2 / v1)))
        return cls(mu=mu, sigma=sigma, source=source)

    def blend(self, prior: CategoryCurve, weight: float, source: str) -> CategoryCurve:
        """``weight`` of this curve and ``1 - weight`` of ``prior`` in every category's mu and
        sigma: the league's rosters shrunk toward the simulated league by ``D/(D+1)``."""
        if not 0.0 <= weight <= 1.0:
            raise ValueError("weight must lie in 0..1")
        missing = [c.value for c in self.mu if c not in prior.mu]
        if missing:
            raise ValueError(f"the prior lacks {missing}")
        mu = {c: weight * float(m) + (1 - weight) * float(prior.mu[c]) for c, m in self.mu.items()}
        sigma = {
            c: weight * float(s) + (1 - weight) * float(prior.sigma[c])
            for c, s in self.sigma.items()
        }
        return CategoryCurve(mu=mu, sigma=sigma, breaks=self.breaks, source=source)

    @classmethod
    def from_rosters(
        cls,
        z: pd.DataFrame,
        rosters: Mapping[Any, Sequence[str]],
        cats: Iterable[Cat],
        source: str = "rosters",
    ) -> CategoryCurve:
        """Fit mu and sigma from drafted rosters: each roster's total is the sum of its players'
        z (``z`` indexed by player id, one column per category), as :func:`roster_totals`."""
        cats = list(cats)
        return cls.from_totals(roster_totals(z, rosters, cats), cats, source=source)

    @classmethod
    def from_dict(cls, spec: Mapping[str, Any], cats: Iterable[Cat] | None = None) -> CategoryCurve:
        """Inverse of :meth:`to_dict`; ``cats`` restricts and orders the categories."""
        mu = {Cat(c): float(v) for c, v in spec["mu"].items()}
        sigma = {Cat(c): float(v) for c, v in spec["sigma"].items()}
        if cats is not None:
            cats = list(cats)
            missing = [c.value for c in cats if c not in mu or c not in sigma]
            if missing:
                raise ValueError(f"curve lacks categories {missing}")
            mu = {c: mu[c] for c in cats}
            sigma = {c: sigma[c] for c in cats}
        breaks = tuple(float(b) for b in spec.get("breaks", DEFAULT_BREAKS))
        return cls(mu=mu, sigma=sigma, breaks=breaks, source=str(spec.get("source", "file")))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mu": {c.value: round(float(v), 4) for c, v in self.mu.items()},
            "sigma": {c.value: round(float(v), 4) for c, v in self.sigma.items()},
            "breaks": list(self.breaks),
            "source": self.source,
        }

    def scaled(self, sigma_scale: float) -> CategoryCurve:
        """The same means with every sigma multiplied by ``sigma_scale``: above one the curve is
        flatter, so a lead in a category is trusted less and the objective moves toward the sum
        of z; below one it is steeper and leads count as nearly won."""
        if sigma_scale <= 0:
            raise ValueError("sigma_scale must be positive")
        if sigma_scale == 1.0:
            return self
        sigma = {c: float(s) * sigma_scale for c, s in self.sigma.items()}
        source = f"{self.source}, sigma x{sigma_scale:g}"
        return CategoryCurve(mu=dict(self.mu), sigma=sigma, breaks=self.breaks, source=source)

    def shift(self, offset: Mapping[Cat, float]) -> CategoryCurve:
        """The same curve on a scale where every total is moved by ``offset``: a total measured
        above replacement level is the raw total minus ``roster_size * level``, so the league's
        mean moves by the same amount."""
        mu = {c: m + float(offset.get(c, 0.0)) for c, m in self.mu.items()}
        return CategoryCurve(mu=mu, sigma=dict(self.sigma), breaks=self.breaks, source=self.source)

    def probability(self, cat: Cat, total: float) -> float:
        """Exact win probability for a total (the curve the segments approximate)."""
        return phi((total - self.mu[cat]) / self.sigma[cat])

    def slope(self, cat: Cat, total: float) -> float:
        """Marginal value of one more z-point at ``total``: categories won per z."""
        sigma = self.sigma[cat]
        return phi_density((total - self.mu[cat]) / sigma) / sigma

    def wins(self, totals: Mapping[Cat, float]) -> float:
        """Expected categories won by a set of totals, summed over the curve's categories
        present in ``totals``."""
        return float(sum(self.probability(c, float(t)) for c, t in totals.items() if c in self.mu))

    def segments(self, cat: Cat, lo: float, hi: float) -> tuple[float, list[Segment]]:
        """Piecewise-linear approximation on ``[lo, hi]``: the value at ``lo`` and the segments
        from there up. Breakpoints outside the range are dropped."""
        return normal_segments(self.mu[cat], self.sigma[cat], lo, hi, self.breaks)

    def evaluate(self, cat: Cat, total: float, lo: float, hi: float) -> float:
        """Value of a total under the piecewise-linear curve on ``[lo, hi]``."""
        base, segments = self.segments(cat, lo, hi)
        return base + sum(s.slope * min(max(total - s.start, 0.0), s.width) for s in segments)


def roster_totals(
    z: pd.DataFrame, rosters: Mapping[Any, Sequence[str]], cats: Iterable[Cat]
) -> pd.DataFrame:
    """One row per roster (indexed by its key), one column per category: the sum of the z of
    its players. A player ``z`` lacks raises: the caller decides what an unscored pick means."""
    cols = [c.value for c in cats]
    missing = sorted({p for players in rosters.values() for p in players if p not in z.index})
    if missing:
        raise KeyError(f"no z for {missing}")
    rows = {key: z.loc[list(players), cols].sum() for key, players in rosters.items()}
    return pd.DataFrame.from_dict(rows, orient="index", columns=cols)


def total_bounds(value: pd.DataFrame, roster_size: int) -> tuple[pd.Series, pd.Series]:
    """Safe bounds on any team total: the ``roster_size`` most negative values summed (positives
    clipped away) and the most positive summed, with a small margin."""
    lo = value.apply(lambda col: float(col.nsmallest(roster_size).clip(upper=0.0).sum()) - 1e-6)
    hi = value.apply(lambda col: float(col.nlargest(roster_size).clip(lower=0.0).sum()) + 1e-6)
    return lo, hi


def normal_segments(
    mu: float, sigma: float, lo: float, hi: float, breaks: Sequence[float] = DEFAULT_BREAKS
) -> tuple[float, list[Segment]]:
    """:meth:`CategoryCurve.segments` for one normal curve given by its mean and spread (the
    season's strategy engine, #110, has a curve per category and horizon)."""
    if hi <= lo:
        raise ValueError("hi must exceed lo")
    points = [lo] + [mu + b * sigma for b in breaks if lo < mu + b * sigma < hi] + [hi]
    values = [phi((p - mu) / sigma) for p in points]
    segments = [
        Segment(start=p0, width=p1 - p0, slope=(v1 - v0) / (p1 - p0))
        for p0, p1, v0, v1 in zip(points[:-1], points[1:], values[:-1], values[1:], strict=True)
    ]
    return values[0], segments


def add_curve(
    model: pulp.LpProblem,
    name: str,
    total: pulp.LpAffineExpression,
    curve: CategoryCurve,
    cat: Cat,
    lo: float,
    hi: float,
) -> pulp.LpAffineExpression:
    """Add the piecewise-linear value of ``total`` to ``model`` and return it as an expression
    (:func:`add_segments` on the curve's segments)."""
    base, segments = curve.segments(cat, lo, hi)
    return add_segments(model, name, total, lo, base, segments)


def add_segments(
    model: pulp.LpProblem,
    name: str,
    total: pulp.LpAffineExpression,
    lo: float,
    base: float,
    segments: Sequence[Segment],
) -> pulp.LpAffineExpression:
    """Add the piecewise-linear value of ``total`` to ``model``, ``base`` at ``lo`` and
    ``segments`` from there up, and return it as an expression.

    ``total`` is split into one bounded piece per segment. A binary on a link forces the
    earlier segment to fill before the later one starts. The link needs one whenever the later
    segment is steeper than any segment before it: otherwise a maximizer could skip a flat
    stretch (the lower tail of the curve) and pour the total into a steeper segment further
    up. Where the later segment is the flattest so far, the maximizer fills in order by itself.
    """
    pieces = [
        model.add_variable(f"seg_{name}_{k}", lowBound=0.0, upBound=s.width)
        for k, s in enumerate(segments)
    ]
    model += total == lo + pulp.lpSum(pieces), f"curve_{name}"
    flattest = float("inf")
    for k in range(len(segments) - 1):
        flattest = min(flattest, segments[k].slope)
        if segments[k + 1].slope > flattest:
            full = model.add_variable(f"full_{name}_{k}", cat=pulp.LpBinary)
            model += pieces[k] >= segments[k].width * full, f"fill_{name}_{k}"
            model += pieces[k + 1] <= segments[k + 1].width * full, f"next_{name}_{k}"
    return base + pulp.lpSum(s.slope * piece for s, piece in zip(segments, pieces, strict=True))


def curve_objective(
    model: pulp.LpProblem,
    totals: Mapping[Cat, pulp.LpAffineExpression],
    curve: CategoryCurve,
    value: pd.DataFrame,
    roster_size: int,
    cats: Sequence[Cat],
) -> pulp.LpAffineExpression:
    """Expected categories won over ``cats``, given each category's total expression."""
    lo, hi = total_bounds(value, roster_size)
    return pulp.lpSum(
        add_curve(model, c.value, totals[c], curve, c, float(lo[c.value]), float(hi[c.value]))
        for c in cats
    )
