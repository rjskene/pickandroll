"""SEASON SIM (#172): a forward Monte Carlo season simulator for the in-season engine.

The world (``world``) samples the rest of a season on the real schedule in three layers: a
persistent projection error drawn once a path, per-game noise around a shared minutes factor,
and availability from a fitted hazard; the policy's beliefs refresh weekly and learn of an
absence after a lag. The fit (``fit``) estimates those layers from per-game logs, per season and
pooled where the seasons agree, and freezes the result with a hash. The league (``league``)
scores weeks, standings and the bracket on the simulated totals. The state (``state``) is a
league as a run starts it and one arm's position on a day; the policy (``policy``) is the
engine's own solve on that state, in three tiers, with the executor that lands its moves; the
opponents (``opponents``) are the other seats' strategies; the runner (``run``) plays arms in
lockstep through one world and pairs their outcomes; the checks (``checks``) draw what the gates
(``validate``) score. Pure: no file reads, no network, no clock; the readers live in
``sources.gamelogs``, ``api.season_sim`` and ``scripts/season_sim.py``.
"""

from .fit import Fit, GameLine, HoldOutError, SeasonFit, fit_season, freeze, pool
from .league import BracketUnread, LeagueSpec, Outcome, season
from .opponents import Market, Mirror, Seat, Static
from .policy import EXECUTIONS, TIERS, Decision
from .run import Arm, World, WorldInputs, forward_world, paired, replay_world, room, simulate
from .state import Member, Setup, SimState
from .world import STREAMS, rng

__all__ = [
    "EXECUTIONS",
    "STREAMS",
    "TIERS",
    "Arm",
    "BracketUnread",
    "Decision",
    "Fit",
    "GameLine",
    "HoldOutError",
    "LeagueSpec",
    "Market",
    "Member",
    "Mirror",
    "Outcome",
    "SeasonFit",
    "Seat",
    "Setup",
    "SimState",
    "Static",
    "World",
    "WorldInputs",
    "fit_season",
    "forward_world",
    "freeze",
    "paired",
    "pool",
    "replay_world",
    "rng",
    "room",
    "season",
    "simulate",
]
