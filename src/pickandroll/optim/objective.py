"""Category-win objective: value each category total by the chance it beats the field.

The roster and horizon models normally maximize the sum of the category totals ``T_c`` (z-scores,
higher is better). Under a :class:`CategoryCurve` they maximize ``sum_c f_c(T_c)`` instead, with
``f_c(T) = Phi((T - mu_c) / sigma_c)``: the probability that a total of ``T`` beats an opponent
drawn from the league, so the objective reads as the expected number of categories won.
``mu_c`` and ``sigma_c`` are the mean and spread of team totals in the league
(:meth:`CategoryCurve.from_totals`); with nothing better to hand, :meth:`CategoryCurve.default`
uses zero and four, which is what simulated leagues on Basketball Monster projections show.

``Phi`` is S-shaped, so the models use a piecewise-linear version with breakpoints at a few
multiples of sigma (:attr:`CategoryCurve.breaks`). The total is split into one bounded piece
per segment and the pieces must fill in order. A maximizer fills a steeper segment before a
flatter one on its own, so a link needs a binary only where the next segment is steeper than
some segment before it; with the flat tails of ``Phi`` that is every link, one binary per
segment boundary and category. The payoff is that a category that cannot be won falls to near
zero marginal value (a soft punt) instead of earning a full z-point for every z-point, as the
plain sum does.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import pandas as pd
import pulp

from ..projections.schema import Cat

DEFAULT_BREAKS: tuple[float, ...] = (-2.5, -1.5, -0.5, 0.5, 1.5, 2.5)
DEFAULT_SIGMA = 4.0
_SQRT2 = math.sqrt(2.0)


def phi(x: float) -> float:
    """Standard normal cumulative distribution."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


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
    def from_totals(cls, totals: pd.DataFrame, cats: Iterable[Cat]) -> CategoryCurve:
        """Fit mu and sigma from a table of team totals, one row per team, one column per
        category (named by ``Cat.value``)."""
        cats = list(cats)
        missing = [c.value for c in cats if c.value not in totals.columns]
        if missing:
            raise ValueError(f"totals lack columns {missing}")
        mu = {c: float(totals[c.value].mean()) for c in cats}
        sigma = {c: float(totals[c.value].std(ddof=1)) for c in cats}
        return cls(mu=mu, sigma=sigma)

    def shift(self, offset: Mapping[Cat, float]) -> CategoryCurve:
        """The same curve on a scale where every total is moved by ``offset``: a total measured
        above replacement level is the raw total minus ``roster_size * level``, so the league's
        mean moves by the same amount."""
        mu = {c: m + float(offset.get(c, 0.0)) for c, m in self.mu.items()}
        return CategoryCurve(mu=mu, sigma=dict(self.sigma), breaks=self.breaks)

    def probability(self, cat: Cat, total: float) -> float:
        """Exact win probability for a total (the curve the segments approximate)."""
        return phi((total - self.mu[cat]) / self.sigma[cat])

    def segments(self, cat: Cat, lo: float, hi: float) -> tuple[float, list[Segment]]:
        """Piecewise-linear approximation on ``[lo, hi]``: the value at ``lo`` and the segments
        from there up. Breakpoints outside the range are dropped."""
        if hi <= lo:
            raise ValueError("hi must exceed lo")
        mu, sigma = self.mu[cat], self.sigma[cat]
        points = [lo] + [mu + b * sigma for b in self.breaks if lo < mu + b * sigma < hi] + [hi]
        values = [self.probability(cat, p) for p in points]
        segments = [
            Segment(start=p0, width=p1 - p0, slope=(v1 - v0) / (p1 - p0))
            for p0, p1, v0, v1 in zip(points[:-1], points[1:], values[:-1], values[1:], strict=True)
        ]
        return values[0], segments

    def evaluate(self, cat: Cat, total: float, lo: float, hi: float) -> float:
        """Value of a total under the piecewise-linear curve on ``[lo, hi]``."""
        base, segments = self.segments(cat, lo, hi)
        return base + sum(s.slope * min(max(total - s.start, 0.0), s.width) for s in segments)


def total_bounds(value: pd.DataFrame, roster_size: int) -> tuple[pd.Series, pd.Series]:
    """Safe bounds on any team total: the ``roster_size`` most negative values summed (positives
    clipped away) and the most positive summed, with a small margin."""
    lo = value.apply(lambda col: float(col.nsmallest(roster_size).clip(upper=0.0).sum()) - 1e-6)
    hi = value.apply(lambda col: float(col.nlargest(roster_size).clip(lower=0.0).sum()) + 1e-6)
    return lo, hi


def add_curve(
    model: pulp.LpProblem,
    name: str,
    total: pulp.LpAffineExpression,
    curve: CategoryCurve,
    cat: Cat,
    lo: float,
    hi: float,
) -> pulp.LpAffineExpression:
    """Add the piecewise-linear value of ``total`` to ``model`` and return it as an expression.

    ``total`` is split into one bounded piece per segment. A binary on a link forces the
    earlier segment to fill before the later one starts. The link needs one whenever the later
    segment is steeper than any segment before it: otherwise a maximizer could skip a flat
    stretch (the lower tail of the curve) and pour the total into a steeper segment further
    up. Where the later segment is the flattest so far, the maximizer fills in order by itself.
    """
    base, segments = curve.segments(cat, lo, hi)
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
