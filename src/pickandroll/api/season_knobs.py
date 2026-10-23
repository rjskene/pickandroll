"""The knob file at solve time (#152, docs/AUTOPILOT.md section 6): the knobs a league's solves
run with, from ``data/autopilot/knobs.json``.

The file holds the knobs in force and each league's own values; ``season.progress`` reads it
leniently (a key it does not know, or a value a knob may not take, is left out and named in the
Progress view's problems). A solve takes the defaults, then the values in force, then its
league's own. A missing file or one that is not JSON means the defaults. Every solve reads the
file again, and the solves kept for the day are keyed to its version (the service's moves
stamp), so a Monday change is in force from the next solve.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..season import progress as pg

AUTOPILOT_DIR = "autopilot"
KNOBS_FILE = "knobs.json"


def autopilot_dir(data_dir: Path) -> Path:
    return data_dir / AUTOPILOT_DIR


def load_knobs(data_dir: Path) -> tuple[Any, list[str]]:
    """The knob file's JSON, None when there is none; a file that is not JSON is a problem."""
    path = autopilot_dir(data_dir) / KNOBS_FILE
    try:
        return json.loads(path.read_text()), []
    except FileNotFoundError:
        return None, []
    except ValueError as exc:
        return None, [f"{KNOBS_FILE} is not JSON: {exc}"]


def for_league(data_dir: Path, league: str) -> dict[str, Any]:
    """The knobs ``league``'s solves run with (``season.progress.in_force_for``)."""
    raw, _ = load_knobs(data_dir)
    knobs, _ = pg.knob_file(raw)
    return pg.in_force_for(knobs, league)
