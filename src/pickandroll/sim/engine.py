"""The door to the in-season engine (#172): the only module of the simulator that imports
``pickandroll.season``.

The simulator plays the engine's own library code as the seat's policy and scores its weeks with
the engine's rules, so this file is the whole list of engine code the simulator calls. The engine
is called as library code and never edited from here: its files are not the simulator's to edit,
and a change the simulator needs in them is asked for on the tracker (#172). Every other module of
the simulator imports these names from ``.engine``; ``tests/sim/test_boundary.py`` holds the
rule. The aliases are the ones the simulator's modules used before the move, so call sites and
the tests' patch targets read as they did.

From the moves executor's queue (``season.autopilot``) the simulator takes the claim's bid alone
(#172, PR Fb): ``bid_of``, ``typical_gain`` and the constants they need (the fortnight the typical
gain is over and the moves it needs), so a seat in a FAAB league bids by the live rule itself,
never a copy of it.

From the league's settings (``season.state``) the simulator takes the two names of a categories
league's head-to-head format (#172, the format PR): ``ONE_WIN``, a week one result in the
standings, and ``EACH_CATEGORY``, each category of a week a result, so a run's format is named by
the engine's own words.

From the Monday step (``season.hillclimb``) the simulator takes the grids its screen nudges a
floor by (#172, PR H1), and nothing of the step itself: ``FLOOR_STEP``, the protection floor's
step a game in each scoring; ``PLAN_DEFAULT`` and ``PLAN_CAP``, a plan floor's default and how
many times it the floor may rise to. The simulator never runs the step and writes no knob file.

From the week plans (``season.plans``, ``pl``) the simulator takes the queue's rule (#172, PR E):
``held_out``, ``every_plan`` and ``for_queue``, the plans the live queue weighs and the one it
takes instead of the three weeks' set, with ``step_score`` for a step's bid, ``gate`` and
``gate_floor`` for what the choice was made on. The search, the gate, the floor and the trim are
the engine's own: the simulator hands them the day's inputs and takes the answer.
"""

from __future__ import annotations

from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv
from pickandroll.season import plans as pl
from pickandroll.season import strategy as sg
from pickandroll.season import stream as st
from pickandroll.season import weekly as wk
from pickandroll.season.autopilot import TYPICAL_DAYS, TYPICAL_MIN, bid_of, typical_gain
from pickandroll.season.calendar import Calendar, Week, monday_of
from pickandroll.season.hillclimb import FLOOR_STEP, PLAN_CAP, PLAN_DEFAULT
from pickandroll.season.moves import HELD, Move
from pickandroll.season.progress import BLEND, DEFAULTS, LIVE_KNOBS, refused
from pickandroll.season.scorecard import FPTS, total, won
from pickandroll.season.state import EACH_CATEGORY, ONE_WIN, Player, SeasonSettings
from pickandroll.season.weekly import COUNTING, PCT, PHI, STATS, starting_slots

__all__ = [
    "BLEND",
    "COUNTING",
    "DEFAULTS",
    "EACH_CATEGORY",
    "FLOOR_STEP",
    "FPTS",
    "HELD",
    "LIVE_KNOBS",
    "ONE_WIN",
    "PCT",
    "PHI",
    "PLAN_CAP",
    "PLAN_DEFAULT",
    "STATS",
    "TYPICAL_DAYS",
    "TYPICAL_MIN",
    "Calendar",
    "Move",
    "Player",
    "SeasonSettings",
    "Week",
    "bid_of",
    "dl",
    "monday_of",
    "mv",
    "pl",
    "refused",
    "sg",
    "st",
    "starting_slots",
    "total",
    "typical_gain",
    "wk",
    "won",
]
