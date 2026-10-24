"""SEASON SIM (#172): a forward Monte Carlo season simulator for the in-season engine.

The world (``world``) samples the rest of a season on the real schedule in three layers: a
persistent projection error drawn once a path, per-game noise around a shared minutes factor,
and availability from a fitted hazard; the policy's beliefs refresh weekly and learn of an
absence after a lag. The fit (``fit``) estimates those layers from per-game logs, per season and
pooled where the seasons agree, and freezes the result with a hash. The league (``league``)
scores weeks, standings and the bracket on the simulated totals. The gates (``validate``) are
the checks a verdict waits on. Pure: no file reads, no network, no clock; the readers live in
``sources.gamelogs`` and ``scripts/season_sim.py``.
"""

from .fit import Fit, GameLine, HoldOutError, SeasonFit, fit_season, freeze, pool
from .league import LeagueSpec, Outcome, season
from .world import STREAMS, rng

__all__ = [
    "STREAMS",
    "Fit",
    "GameLine",
    "HoldOutError",
    "LeagueSpec",
    "Outcome",
    "SeasonFit",
    "fit_season",
    "freeze",
    "pool",
    "rng",
    "season",
]
