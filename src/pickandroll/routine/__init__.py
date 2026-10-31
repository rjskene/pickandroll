"""The routines (#225): the AUTOPILOT chain as a deterministic runner, so that it runs on a
schedule anywhere, with no language model in the path.

Six routines, the ones the Desktop scheduled tasks ran from the Mac (``docs/AUTOPILOT.md`` §3):
``daily`` (05:00), ``morning`` (09:15), ``late`` (15:00), ``evening-build`` (21:00),
``evening-pass`` (22:40) and ``monday`` (06:00 Mondays), on the Central clock. Each is a fixed
sequence of steps over the API, the browser (PR 2) and two scripts; every step reports ``ok``,
``failed`` or ``skipped`` with one line of detail, and the run ends in a written summary, a JSON
run log and, for the daily, the freshness light's marker (``season/status.py``).

The effects are injected (``Context``): the API call, the clock, the sleep, the script runner and
the GitHub poster, so the sequences are tested without a network. ``scripts/routine.py`` wires
the real ones.
"""

from .api import Call, Unreachable, http
from .clock import CENTRAL, now
from .report import Report, Step
from .routines import ROUTINES, WINDOWS, Refused, run
from .steps import Context, Stopped

__all__ = [
    "CENTRAL",
    "ROUTINES",
    "WINDOWS",
    "Call",
    "Context",
    "Refused",
    "Report",
    "Step",
    "Stopped",
    "Unreachable",
    "http",
    "now",
    "run",
]
