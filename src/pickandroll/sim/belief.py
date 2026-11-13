"""What a replay's seat believes (#172, PR B1): the forecaster's figure updated with only the
games already played.

On day ``d`` the belief about a player is, stat by stat,
``(w[s] · prior[s] + the sum of his lines' s dated before d) / (w[s] + his games before d)``:
the forecaster's preseason figure weighed as ``w[s]`` games against his own games so far.
"Before d" is strict, so the belief read on day ``d`` counts no line dated ``d`` or later and the
seat never hears a game before it is played. Makes and attempts are stats of their own, so the
percentages follow from them; the result passes through :func:`consistent`. A player nobody
projected is in no belief until the day after his first recorded game; from then his prior is
the **newcomer's prior** (:func:`newcomer_prior`): the mean projection over the projected players
left undrafted, so an unknown is an average wire player until his games say otherwise.

The projection is an argument: each forecaster gets its own belief. The weights ``w`` are fitted
in ``fit.belief_weights``. Pure: lines, projection and weights come in.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Mapping
from datetime import date

from .engine import STATS

Rates = Mapping[str, float]


def consistent(rates: Rates) -> dict[str, float]:
    """A rate line whose makes do not exceed its attempts nor its threes its field goals: the
    errors are drawn a stat at a time, and a line that breaks the identities has no variance."""
    out = {k: float(v) for k, v in rates.items()}
    if "fgm" in out and "fga" in out:
        out["fgm"] = min(out["fgm"], out["fga"])
    if "ftm" in out and "fta" in out:
        out["ftm"] = min(out["ftm"], out["fta"])
    if "threes" in out and "fgm" in out:
        out["threes"] = min(out["threes"], out["fgm"])
    return out


def shrunk(prior: Rates, sums: Mapping[str, float], games: int, w: Mapping[str, float]) -> dict:
    """``(w · prior + sums) / (w + games)`` for every stat of the prior, through
    :func:`consistent`."""
    return consistent(
        {
            s: (w[s] * float(p) + float(sums.get(s, 0.0))) / (w[s] + games)
            for s, p in prior.items()
            if s in w
        }
    )


def newcomer_prior(projection: Mapping[int, Rates], undrafted: Iterable[int]) -> dict[str, float]:
    """The mean projection, per stat, over the projected players left undrafted (a stat averaged
    over the players that have it), through :func:`consistent`; empty when there are none."""
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for k in undrafted:
        rates = projection.get(k)
        if rates is None:
            continue
        for s, v in rates.items():
            if s in STATS:
                totals[s] = totals.get(s, 0.0) + float(v)
                counts[s] = counts.get(s, 0) + 1
    return consistent({s: totals[s] / counts[s] for s in totals})


class CausalBelief:
    """Every player's belief on any day, from the lines dated before it.

    ``players`` are the league's; a projected one starts from his projection, any other from
    ``newcomer`` once he has played. The running sums are taken in date order once, so the belief
    on day ``d`` depends on the lines before ``d`` alone, bit for bit."""

    def __init__(
        self,
        players: Iterable[int],
        projection: Mapping[int, Rates],
        lines: Mapping[int, Mapping[date, Mapping[str, float]]],
        weights: Mapping[str, float],
        newcomer: Rates,
    ) -> None:
        self.weights = {s: float(weights[s]) for s in STATS if s in weights}
        self.newcomer = dict(newcomer)
        self._order = list(dict.fromkeys(players))
        self._prior = {k: dict(projection[k]) for k in self._order if k in projection}
        self._dates: dict[int, list[date]] = {}
        self._sums: dict[int, list[dict[str, float]]] = {}
        for k in self._order:
            by_day = lines.get(k) or {}
            days = sorted(by_day)
            running = dict.fromkeys(STATS, 0.0)
            sums = [dict(running)]
            for d in days:
                ln = by_day[d]
                for s in STATS:
                    running[s] += float(ln.get(s, 0.0))
                sums.append(dict(running))
            self._dates[k] = days
            self._sums[k] = sums
        self._day: date | None = None
        self._cached: dict[int, dict[str, float]] = {}

    def games_before(self, player: int, day: date) -> int:
        return bisect_left(self._dates.get(player, []), day)

    def of(self, player: int, day: date) -> dict[str, float] | None:
        """One player's belief on ``day``; None for a player nobody projected who has not played
        before it."""
        n = self.games_before(player, day)
        prior = self._prior.get(player)
        if prior is None:
            if n == 0 or not self.newcomer:
                return None
            prior = self.newcomer
        return shrunk(prior, self._sums[player][n], n, self.weights)

    def on(self, day: date) -> dict[int, dict[str, float]]:
        """Every believed player's rates on ``day`` (the last day read is kept)."""
        if day != self._day:
            out: dict[int, dict[str, float]] = {}
            for k in self._order:
                b = self.of(k, day)
                if b is not None:
                    out[k] = b
            self._day, self._cached = day, out
        return self._cached


__all__ = ["CausalBelief", "consistent", "newcomer_prior", "shrunk"]
