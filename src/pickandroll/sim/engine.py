"""The door to the in-season engine (#172): the only module of the simulator that imports
``pickandroll.season``.

The simulator plays the engine's own library code as the seat's policy and scores its weeks with
the engine's rules, so this file is the whole list of engine code the simulator calls. The engine
is called as library code and never edited from here: its files are not the simulator's to edit,
and a change the simulator needs in them is asked for on the tracker (#172). Every other module of
the simulator imports these names from ``.engine``; ``tests/sim/test_boundary.py`` holds the
rule. The aliases are the ones the simulator's modules used before the move, so call sites and
the tests' patch targets read as they did.
"""

from __future__ import annotations

from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv
from pickandroll.season import strategy as sg
from pickandroll.season import stream as st
from pickandroll.season import weekly as wk
from pickandroll.season.calendar import Calendar, Week, monday_of
from pickandroll.season.moves import HELD, Move
from pickandroll.season.progress import BLEND, DEFAULTS, LIVE_KNOBS, refused
from pickandroll.season.scorecard import FPTS, total, won
from pickandroll.season.state import Player, SeasonSettings
from pickandroll.season.weekly import COUNTING, PCT, PHI, STATS, starting_slots

__all__ = [
    "BLEND",
    "COUNTING",
    "DEFAULTS",
    "FPTS",
    "HELD",
    "LIVE_KNOBS",
    "PCT",
    "PHI",
    "STATS",
    "Calendar",
    "Move",
    "Player",
    "SeasonSettings",
    "Week",
    "dl",
    "monday_of",
    "mv",
    "refused",
    "sg",
    "st",
    "starting_slots",
    "total",
    "wk",
    "won",
]
