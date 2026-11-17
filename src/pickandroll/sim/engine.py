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
(#172, PR Fb): ``bid_of``, ``typical_gain`` and the constants they need (a free agent's mark and
the fortnight the typical gain is over), so a seat in a FAAB league bids by the live rule itself,
never a copy of it.
"""

from __future__ import annotations

from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv
from pickandroll.season import strategy as sg
from pickandroll.season import stream as st
from pickandroll.season import weekly as wk
from pickandroll.season.autopilot import FREE_AGENT, TYPICAL_DAYS, TYPICAL_MIN, bid_of, typical_gain
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
    "FREE_AGENT",
    "HELD",
    "LIVE_KNOBS",
    "PCT",
    "PHI",
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
    "refused",
    "sg",
    "st",
    "starting_slots",
    "total",
    "typical_gain",
    "wk",
    "won",
]
