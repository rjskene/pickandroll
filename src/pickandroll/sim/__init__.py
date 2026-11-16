"""SEASON SIM (#172): a standalone whole-season simulator.

A replay drafts a made-up league (twelve teams, or a grid of league shapes: ``shapes``) on a
forecaster's projection (``forecast``) and plays it through a recorded season's game lines
(``gamelogs``), from the draft to the final; the recorded lines are the truth and each seat
believes only the games already played (``belief``).
The league (``league``) scores weeks, standings and the bracket. The state (``state``) is a league
as a run starts it and one arm's position on a day; the policy (``policy``) is the engine's own
solve on that state, in three tiers, with the executor that lands its moves; the opponents
(``opponents``) are the other seats' strategies; the runner (``run``) plays arms in lockstep
through one world, in a room or a pair; the audit (``audit``), the counts (``counts``) and the
no-peek check (``nopeek``) read what happened; gate 5 (``checks``, ``validate``) checks the
surrogate against the exact tier. The fit (``fit``) is frozen with a hash; a run reads its lag.
Those modules are pure: no file reads, no network, no clock. The readers are ``gamelogs`` (ESPN's
game logs) and ``readers`` (the fit, the logs, the run records), the commands are ``cli``
(``python -m pickandroll.sim <command>``), and the in-season engine is reached through ``engine``
only. Nothing outside this package imports it, and it imports nothing from the live API
(``tests/sim/test_boundary.py``).
"""

from .fit import Fit, GameLine, HoldOutError, SeasonFit, fit_season, freeze, pool
from .league import BracketUnread, LeagueSpec, Outcome, season
from .opponents import Market, Mirror, Seat, Static
from .policy import EXECUTIONS, TIERS, Decision
from .run import Arm, World, WorldInputs, paired, replay_world, room, simulate
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
    "freeze",
    "paired",
    "pool",
    "replay_world",
    "rng",
    "room",
    "season",
    "simulate",
]
