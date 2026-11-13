"""The world's parameters from per-game logs (#172, PR 1).

Each layer of the world has a fit here: the over-dispersion of each counting stat beyond the
shared minutes factor (:func:`dispersion`), the spread of that factor (:func:`minutes_factor`),
the hazard of a new absence and the lengths of the runs that follow (:func:`hazard`), the spread
of the projection's error from two systems' disagreement (:func:`tau_from_systems`) or from
box-score residuals (:func:`tau_from_residuals`), and how fast the projection source's own
rest-of-season figures close the gap to the realized rate (:func:`refresh_rate`). Seasons are
fitted one at a time (:func:`fit_season`), compared (:func:`agree`) and pooled where they agree
(:func:`pool`); :func:`freeze` writes the result as a plain payload with its hash, naming the
hold-out season it never saw. Pure: the lines come in from ``sources.gamelogs``.

Games under :data:`MIN_MINUTES` are dropped from the dispersion and minutes fits; each player's
share of such games is kept in the payload so a gate failure can be read against it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from itertools import pairwise
from typing import Any

import numpy as np

from ..weekly import COUNTING, PHI, STATS

#: The stats a game line carries, in our names (``weekly.STATS``).
LINE_STATS = STATS
#: The counting stats and the attempts: the ones drawn negative-binomially, dispersion fitted.
DISPERSED = (*COUNTING, "fga", "fta")
#: Games under this many minutes are dropped from the dispersion and minutes fits.
MIN_MINUTES = 5.0
#: Played games a player needs for a dispersion of his own.
MIN_GAMES = 30
#: The shrinkage weight toward the pool for a per-player dispersion: ``(n·φ̂ + k·φ̄) / (n + k)``.
SHRINK_K = 30
#: Run lengths (games missed in a row) that end the first two components of the mixture.
RUN_CUTS = (3, 15)
#: A season disagrees with the others when its hazard or minutes spread is off the median by more.
AGREE_TOL = 0.20
#: Players projected under this many minutes a game are left out of ``tau_from_systems``.
TAU_FLOOR_MINUTES = 20.0
#: Players with fewer played games are left out of ``tau_from_residuals``.
TAU_FLOOR_GAMES = 10
#: The belief refresh until fitted from the exports: the weekly fraction of the gap closed, the
#: spread of the step not explained by it (log scale), and the news lag in days.
REFRESH_DEFAULTS: Mapping[str, float] = {"kappa": 0.10, "sigma_eta": 0.05, "lag": 1}
#: A run longer than this is a season-long absence for the mixture's lengths.
RUN_CAP = 60


class HoldOutError(ValueError):
    """The hold-out season was offered to a fit."""


@dataclass(frozen=True)
class GameLine:
    """One player's line in one of his team's scheduled games: ``played`` False (and the stats
    empty) when he did not play. ``period`` orders a team's games within a season."""

    player: str
    season: int
    period: int
    team: str | None
    played: bool
    minutes: float
    stats: Mapping[str, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- dispersion
@dataclass(frozen=True)
class Dispersion:
    """``pooled`` is the residual over-dispersion of each stat after the shared minutes factor
    (what the world draws with); ``raw`` the plain per-game variance over mean, the figure
    ``weekly.PHI`` carries, kept for comparison; ``players`` the shrunk per-player residual
    dispersion for players with :data:`MIN_GAMES` or more; ``short_share`` each player's share
    of played games under :data:`MIN_MINUTES`."""

    pooled: Mapping[str, float]
    raw: Mapping[str, float]
    players: Mapping[str, Mapping[str, float]]
    short_share: Mapping[str, float]
    games: int
    fitted_players: int


def _by_player(lines: Iterable[GameLine]) -> dict[str, list[GameLine]]:
    out: dict[str, list[GameLine]] = {}
    for ln in lines:
        out.setdefault(ln.player, []).append(ln)
    for v in out.values():
        v.sort(key=lambda ln: (ln.season, ln.period))
    return out


def _played(lines: Sequence[GameLine], min_minutes: float) -> list[GameLine]:
    return [ln for ln in lines if ln.played and ln.minutes >= min_minutes]


def _player_dispersion(
    played: Sequence[GameLine], stats: Sequence[str]
) -> tuple[dict[str, float], dict[str, float]]:
    """A player's residual and raw dispersion per stat over his played games: residual is the
    mean squared deviation from ``rate × minutes / mean minutes`` over that expectation; raw is
    the variance over the mean."""
    mins = np.array([ln.minutes for ln in played], dtype=float)
    share = mins / mins.mean()
    resid: dict[str, float] = {}
    raw: dict[str, float] = {}
    for stat in stats:
        x = np.array([float(ln.stats.get(stat, 0.0)) for ln in played])
        mean = x.mean()
        if mean <= 0:
            continue
        expected = mean * share
        resid[stat] = float(np.mean((x - expected) ** 2 / expected))
        raw[stat] = float(x.var(ddof=1) / mean) if len(x) > 1 else 1.0
    return resid, raw


def dispersion(
    lines: Iterable[GameLine],
    stats: Sequence[str] = DISPERSED,
    min_games: int = MIN_GAMES,
    k: int = SHRINK_K,
    min_minutes: float = MIN_MINUTES,
) -> Dispersion:
    """The dispersion of each stat, pooled over the players with ``min_games`` played games
    (games-weighted), floored at 1 (Poisson), and per player shrunk to the pool with weight
    ``k``."""
    players = _by_player(lines)
    per: dict[str, tuple[int, dict[str, float], dict[str, float]]] = {}
    short: dict[str, float] = {}
    games = 0
    for pid, pl in players.items():
        all_played = [ln for ln in pl if ln.played]
        kept = _played(pl, min_minutes)
        if all_played:
            short[pid] = round(1 - len(kept) / len(all_played), 4)
        games += len(kept)
        if len(kept) >= min_games:
            resid, raw = _player_dispersion(kept, stats)
            per[pid] = (len(kept), resid, raw)
    pooled: dict[str, float] = {}
    raw_pooled: dict[str, float] = {}
    for stat in stats:
        rows = [(n, r[stat], w[stat]) for n, r, w in per.values() if stat in r]
        if not rows:
            continue
        total = sum(n for n, _, _ in rows)
        pooled[stat] = max(1.0, sum(n * r for n, r, _ in rows) / total)
        raw_pooled[stat] = max(1.0, sum(n * w for n, _, w in rows) / total)
    shrunk: dict[str, dict[str, float]] = {}
    for pid, (n, resid, _) in per.items():
        shrunk[pid] = {
            stat: max(1.0, (n * resid[stat] + k * pooled[stat]) / (n + k))
            for stat in resid
            if stat in pooled
        }
    return Dispersion(pooled, raw_pooled, shrunk, short, games, len(per))


# --------------------------------------------------------------------------- minutes
@dataclass(frozen=True)
class MinutesFit:
    """``sigma`` is the spread of log minutes around each player's own season mean, pooled over
    players (games-weighted root mean square); ``players`` the same per player."""

    sigma: float
    players: Mapping[str, float]
    games: int


def minutes_factor(
    lines: Iterable[GameLine], min_minutes: float = MIN_MINUTES, min_games: int = 5
) -> MinutesFit:
    per: dict[str, float] = {}
    sq = 0.0
    games = 0
    for pid, pl in _by_player(lines).items():
        kept = _played(pl, min_minutes)
        if len(kept) < min_games:
            continue
        logs = np.log([ln.minutes for ln in kept])
        dev = logs - logs.mean()
        per[pid] = float(math.sqrt(np.mean(dev**2)))
        sq += float(np.sum(dev**2))
        games += len(kept)
    sigma = math.sqrt(sq / games) if games else 0.0
    return MinutesFit(sigma, per, games)


# --------------------------------------------------------------------------- hazard
@dataclass(frozen=True)
class Component:
    """Runs of ``lo`` to ``hi`` games missed in a row (``hi`` None: and longer): their share of
    all runs and the distribution of their lengths."""

    lo: int
    hi: int | None
    weight: float
    lengths: Mapping[int, float]


@dataclass(frozen=True)
class Hazard:
    """``rate`` is the chance a played game is followed by a new absence; ``components`` the
    run-length mixture; ``censored`` the runs still open at the season's last game (not in the
    mixture: a season-ending absence or a departure); ``leading`` the games before a player's
    first appearance (dropped: his roster status then is unknown)."""

    rate: float
    components: tuple[Component, ...]
    runs: int
    played: int
    players: int
    censored: int
    censored_share: float
    leading: int


def _runs(pl: Sequence[GameLine]) -> tuple[list[int], int, int, int]:
    """A player's interior runs of games missed (between his first and last played game), his
    played games, the length of the run open at the end, and the games before his first."""
    flags = [ln.played for ln in pl]
    if not any(flags):
        return [], 0, 0, len(flags)
    first = flags.index(True)
    last = len(flags) - 1 - flags[::-1].index(True)
    runs: list[int] = []
    run = 0
    for f in flags[first : last + 1]:
        if f:
            if run:
                runs.append(run)
            run = 0
        else:
            run += 1
    return runs, sum(flags), len(flags) - 1 - last, first


def hazard(lines: Iterable[GameLine], cuts: Sequence[int] = RUN_CUTS, cap: int = RUN_CAP) -> Hazard:
    """The absence hazard and its run-length mixture over every player-season in ``lines``."""
    runs: list[int] = []
    played = censored = leading = 0
    players = 0
    by_player_season: dict[tuple[str, int], list[GameLine]] = {}
    for ln in lines:
        by_player_season.setdefault((ln.player, ln.season), []).append(ln)
    for pl in by_player_season.values():
        pl.sort(key=lambda ln: ln.period)
        r, p, open_run, lead = _runs(pl)
        if p == 0:
            continue
        players += 1
        runs.extend(min(x, cap) for x in r)
        played += p
        censored += 1 if open_run else 0
        leading += lead
    bounds = [(1, cuts[0])] + [(cuts[i] + 1, cuts[i + 1]) for i in range(len(cuts) - 1)]
    bounds.append((cuts[-1] + 1, None))
    components = []
    for lo, hi in bounds:
        mine = [x for x in runs if x >= lo and (hi is None or x <= hi)]
        counts: dict[int, int] = {}
        for x in mine:
            counts[x] = counts.get(x, 0) + 1
        lengths = {n: c / len(mine) for n, c in sorted(counts.items())} if mine else {}
        components.append(Component(lo, hi, len(mine) / len(runs) if runs else 0.0, lengths))
    rate = len(runs) / played if played else 0.0
    return Hazard(
        rate,
        tuple(components),
        len(runs),
        played,
        players,
        censored,
        censored / players if players else 0.0,
        leading,
    )


# --------------------------------------------------------------------------- tau
def tau_from_systems(
    a: Mapping[str, Mapping[str, float]],
    b: Mapping[str, Mapping[str, float]],
    minutes: Mapping[str, float],
    floor: float = TAU_FLOOR_MINUTES,
    stats: Sequence[str] = LINE_STATS,
) -> dict[str, float]:
    """The spread of the log ratio of two systems' per-game rates over the players both project
    at ``floor`` minutes or more: the projection error's proxy until residuals exist."""
    out: dict[str, float] = {}
    keep = [p for p in a if p in b and minutes.get(p, 0.0) >= floor]
    for stat in stats:
        ratios = [
            math.log(a[p][stat] / b[p][stat])
            for p in keep
            if a[p].get(stat, 0) > 0 and b[p].get(stat, 0) > 0
        ]
        if len(ratios) >= 2:
            out[stat] = float(np.std(ratios, ddof=1))
    return out


def tau_from_residuals(
    projected: Mapping[str, Mapping[str, float]],
    realized: Mapping[str, Mapping[str, float]],
    games: Mapping[str, int],
    phi: Mapping[str, float] = PHI,
    floor: int = TAU_FLOOR_GAMES,
    stats: Sequence[str] = LINE_STATS,
) -> dict[str, float]:
    """The spread of the log ratio of realized to projected per-game rates over the players with
    ``floor`` played games or more, less the part that sampling noise alone explains
    (``phi / (rate × games)``), floored at zero."""
    out: dict[str, float] = {}
    for stat in stats:
        rows = [
            (math.log(realized[p][stat] / projected[p][stat]), projected[p][stat], games[p])
            for p in projected
            if p in realized
            and games.get(p, 0) >= floor
            and projected[p].get(stat, 0) > 0
            and realized[p].get(stat, 0) > 0
        ]
        if len(rows) < 2:
            continue
        var = float(np.var([r for r, _, _ in rows], ddof=1))
        noise = float(np.mean([phi.get(stat, 1.0) / (rate * n) for _, rate, n in rows]))
        out[stat] = math.sqrt(max(0.0, var - noise))
    return out


# --------------------------------------------------------------------------- refresh
@dataclass(frozen=True)
class Refresh:
    """The weekly fraction ``kappa`` of the gap between a projection and the realized rate that
    the source's next export closes, and ``sigma_eta``, the spread of the step it does not
    explain (log scale, a week); ``pairs`` the player-stat steps behind it. ``fitted`` False
    when the exports were too few and the defaults stand."""

    kappa: float
    sigma_eta: float
    pairs: int
    fitted: bool


def refresh_rate(
    exports: Sequence[tuple[date, Mapping[str, Mapping[str, float]]]],
    realized: Mapping[str, Mapping[str, float]],
    stats: Sequence[str] = COUNTING,
    defaults: Mapping[str, float] = REFRESH_DEFAULTS,
) -> Refresh:
    """For each pair of consecutive exports, the step ``log b' − log b`` regressed through the
    origin on the gap ``log θ − log b`` to the realized rate gives the share of the gap closed
    between them; converted to a week as ``1 − (1 − share)^(7 / days)`` and averaged over the
    pairs by their player-stat count. ``sigma_eta`` is the residual spread scaled to a week."""
    kappas: list[float] = []
    sigmas: list[float] = []
    counts: list[int] = []
    ordered = sorted(exports, key=lambda e: e[0])
    for (d0, b0), (d1, b1) in pairwise(ordered):
        days = (d1 - d0).days
        if days <= 0:
            continue
        xs: list[float] = []
        ys: list[float] = []
        for p, r in realized.items():
            if p not in b0 or p not in b1:
                continue
            for stat in stats:
                a, b, t = b0[p].get(stat, 0), b1[p].get(stat, 0), r.get(stat, 0)
                if a > 0 and b > 0 and t > 0:
                    xs.append(math.log(t / a))
                    ys.append(math.log(b / a))
        if len(xs) < 2:
            continue
        x, y = np.array(xs), np.array(ys)
        share = float(np.sum(x * y) / np.sum(x * x)) if np.any(x != 0) else 0.0
        share = max(0.0, min(0.999, share))
        kappas.append(1.0 - (1.0 - share) ** (7.0 / days))
        sigmas.append(float(math.sqrt(np.mean((y - share * x) ** 2) * 7.0 / days)))
        counts.append(len(xs))
    if not counts:
        return Refresh(defaults["kappa"], defaults["sigma_eta"], 0, False)
    w = np.array(counts, dtype=float)
    kappa = float(np.sum(w * np.array(kappas)) / w.sum())
    sigma = float(math.sqrt(np.sum(w * np.array(sigmas) ** 2) / w.sum()))
    return Refresh(kappa, sigma, int(w.sum()), True)


# --------------------------------------------------------------------------- seasons
@dataclass(frozen=True)
class SeasonFit:
    season: int
    dispersion: Dispersion
    minutes: MinutesFit
    hazard: Hazard
    players: int
    lines: int


def fit_season(
    lines: Iterable[GameLine],
    season: int,
    stats: Sequence[str] = DISPERSED,
    min_games: int = MIN_GAMES,
    k: int = SHRINK_K,
    min_minutes: float = MIN_MINUTES,
    cuts: Sequence[int] = RUN_CUTS,
) -> SeasonFit:
    rows = [ln for ln in lines if ln.season == season]
    return SeasonFit(
        season,
        dispersion(rows, stats, min_games, k, min_minutes),
        minutes_factor(rows, min_minutes),
        hazard(rows, cuts),
        len({ln.player for ln in rows}),
        len(rows),
    )


@dataclass(frozen=True)
class Agreement:
    """Which seasons agree: a season is an outlier when its hazard rate or its minutes spread is
    off the others' median by more than ``tol`` (relative)."""

    ok: bool
    outliers: tuple[int, ...]
    hazard: Mapping[int, float]
    sigma: Mapping[int, float]
    tol: float


def agree(fits: Sequence[SeasonFit], tol: float = AGREE_TOL) -> Agreement:
    rates = {f.season: f.hazard.rate for f in fits}
    sigmas = {f.season: f.minutes.sigma for f in fits}
    outliers: list[int] = []
    if len(fits) >= 3:
        for table in (rates, sigmas):
            med = float(np.median(list(table.values())))
            for s, v in table.items():
                if med > 0 and abs(v - med) / med > tol and s not in outliers:
                    outliers.append(s)
    return Agreement(not outliers, tuple(sorted(outliers)), rates, sigmas, tol)


@dataclass(frozen=True)
class Fit:
    """The pooled fit over the agreeing seasons, with each outlier's own fit kept apart."""

    seasons: tuple[int, ...]
    dispersion: Dispersion
    minutes: MinutesFit
    hazard: Hazard
    separate: Mapping[int, SeasonFit]
    agreement: Agreement


def _pool_dispersion(fits: Sequence[SeasonFit]) -> Dispersion:
    stats = sorted({s for f in fits for s in f.dispersion.pooled})
    pooled, raw = {}, {}
    for stat in stats:
        rows = [
            (f.dispersion.games, f.dispersion.pooled[stat], f.dispersion.raw[stat])
            for f in fits
            if stat in f.dispersion.pooled
        ]
        total = sum(n for n, _, _ in rows)
        pooled[stat] = sum(n * p for n, p, _ in rows) / total
        raw[stat] = sum(n * r for n, _, r in rows) / total
    players: dict[str, dict[str, float]] = {}
    short: dict[str, float] = {}
    for f in fits:
        # A player's latest season wins where he appears in several (fits in season order).
        players.update({p: dict(v) for p, v in f.dispersion.players.items()})
        short.update(f.dispersion.short_share)
    return Dispersion(
        pooled,
        raw,
        players,
        short,
        sum(f.dispersion.games for f in fits),
        len(players),
    )


def _pool_minutes(fits: Sequence[SeasonFit]) -> MinutesFit:
    games = sum(f.minutes.games for f in fits)
    sq = sum(f.minutes.sigma**2 * f.minutes.games for f in fits)
    players: dict[str, float] = {}
    for f in fits:
        players.update(f.minutes.players)
    return MinutesFit(math.sqrt(sq / games) if games else 0.0, players, games)


def _pool_hazard(fits: Sequence[SeasonFit]) -> Hazard:
    runs = sum(f.hazard.runs for f in fits)
    played = sum(f.hazard.played for f in fits)
    players = sum(f.hazard.players for f in fits)
    censored = sum(f.hazard.censored for f in fits)
    comps: list[Component] = []
    n_comp = len(fits[0].hazard.components)
    for i in range(n_comp):
        parts = [f.hazard.components[i] for f in fits]
        lo, hi = parts[0].lo, parts[0].hi
        mine = sum(c.weight * f.hazard.runs for c, f in zip(parts, fits))
        lengths: dict[int, float] = {}
        for c, f in zip(parts, fits):
            for n, p in c.lengths.items():
                lengths[n] = lengths.get(n, 0.0) + p * c.weight * f.hazard.runs
        if mine:
            lengths = {n: v / mine for n, v in sorted(lengths.items())}
        comps.append(Component(lo, hi, mine / runs if runs else 0.0, lengths))
    return Hazard(
        runs / played if played else 0.0,
        tuple(comps),
        runs,
        played,
        players,
        censored,
        censored / players if players else 0.0,
        sum(f.hazard.leading for f in fits),
    )


def pool(fits: Sequence[SeasonFit], agreement: Agreement | None = None) -> Fit:
    """The fit pooled over the seasons that agree (every one when they all do), the outliers
    kept apart under their season."""
    ordered = sorted(fits, key=lambda f: f.season)
    agreement = agreement or agree(ordered)
    kept = [f for f in ordered if f.season not in agreement.outliers] or ordered
    return Fit(
        tuple(f.season for f in kept),
        _pool_dispersion(kept),
        _pool_minutes(kept),
        _pool_hazard(kept),
        {f.season: f for f in ordered if f.season in agreement.outliers},
        agreement,
    )


# --------------------------------------------------------------------------- freeze
def check_hold_out(seasons: Iterable[int], hold_out: int | None) -> None:
    """Refuse a fit that would see the hold-out season."""
    if hold_out is not None and hold_out in set(seasons):
        raise HoldOutError(f"season {hold_out} is the hold-out and is in no fit")


def _hazard_dict(h: Hazard) -> dict[str, Any]:
    return {
        "rate": h.rate,
        "components": [
            {
                "lo": c.lo,
                "hi": c.hi,
                "weight": c.weight,
                "lengths": {str(k): v for k, v in c.lengths.items()},
            }
            for c in h.components
        ],
        "runs": h.runs,
        "played": h.played,
        "players": h.players,
        "censored": h.censored,
        "censored_share": h.censored_share,
        "leading": h.leading,
    }


def _season_dict(f: SeasonFit) -> dict[str, Any]:
    return {
        "season": f.season,
        "players": f.players,
        "lines": f.lines,
        "dispersion": {
            "pooled": dict(f.dispersion.pooled),
            "raw": dict(f.dispersion.raw),
            "games": f.dispersion.games,
            "fitted_players": f.dispersion.fitted_players,
        },
        "minutes": {"sigma": f.minutes.sigma, "games": f.minutes.games},
        "hazard": _hazard_dict(f.hazard),
    }


def freeze(
    fit: Fit,
    hold_out: int | None,
    parameters: Mapping[str, Any] | None = None,
    tau: Mapping[str, float] | None = None,
    refresh: Refresh | None = None,
    seasons: Sequence[SeasonFit] = (),
) -> tuple[dict[str, Any], str]:
    """The fit as a plain payload and the SHA-256 of its canonical JSON. The payload names the
    seasons fitted, the hold-out it excluded, every fit parameter, and each player's share of
    short games; a fit that saw the hold-out is refused."""
    check_hold_out(fit.seasons, hold_out)
    params = {
        "min_minutes": MIN_MINUTES,
        "min_games": MIN_GAMES,
        "shrink_k": SHRINK_K,
        "run_cuts": list(RUN_CUTS),
        "run_cap": RUN_CAP,
        "agree_tol": fit.agreement.tol,
        "tau_floor_minutes": TAU_FLOOR_MINUTES,
        "tau_floor_games": TAU_FLOOR_GAMES,
        "refresh_defaults": dict(REFRESH_DEFAULTS),
        **(parameters or {}),
    }
    payload: dict[str, Any] = {
        "kind": "season-sim fit",
        "seasons": list(fit.seasons),
        "hold_out": hold_out,
        "parameters": params,
        "dispersion": {
            "pooled": dict(fit.dispersion.pooled),
            "raw": dict(fit.dispersion.raw),
            "players": {p: dict(v) for p, v in sorted(fit.dispersion.players.items())},
            "games": fit.dispersion.games,
            "fitted_players": fit.dispersion.fitted_players,
        },
        "short_share": dict(sorted(fit.dispersion.short_share.items())),
        "minutes": {
            "sigma": fit.minutes.sigma,
            "games": fit.minutes.games,
            "players": dict(sorted(fit.minutes.players.items())),
        },
        "hazard": _hazard_dict(fit.hazard),
        "agreement": {
            "ok": fit.agreement.ok,
            "outliers": list(fit.agreement.outliers),
            "hazard": {str(k): v for k, v in fit.agreement.hazard.items()},
            "sigma": {str(k): v for k, v in fit.agreement.sigma.items()},
        },
        "separate": {str(s): _season_dict(f) for s, f in sorted(fit.separate.items())},
        "per_season": [_season_dict(f) for f in sorted(seasons, key=lambda f: f.season)],
        "tau": dict(tau) if tau else None,
        "refresh": None
        if refresh is None
        else {
            "kappa": refresh.kappa,
            "sigma_eta": refresh.sigma_eta,
            "pairs": refresh.pairs,
            "fitted": refresh.fitted,
            "lag": REFRESH_DEFAULTS["lag"],
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return payload, hashlib.sha256(canonical.encode()).hexdigest()
