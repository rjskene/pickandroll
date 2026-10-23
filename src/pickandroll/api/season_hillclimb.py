"""``POST /autopilot/monday`` (#152; docs/AUTOPILOT.md section 6): the Monday hill-climb step on
the API's own data. It reads the Progress payload, the knob file and the leagues' settings, runs
``season.hillclimb.step`` and writes the knob file (``data/autopilot/knobs.json``) and the Monday
note (``data/autopilot/notes/<monday>.md``), under one lock.

Once a Monday: a second run answers the note and the changes the first one wrote and writes
nothing. ``force`` undoes that Monday's own change, never one already judged, and runs again,
rewriting the note. ``dry_run`` answers the same and writes nothing. A knob file the step cannot
write without losing what is in it (not JSON, or the wrong shape) is refused (409), never
overwritten.

The armed leagues are the public ones: every public league counts as armed unless the user
disarms it (docs/AUTOPILOT.md section 1), and no in-season disarm exists yet. The private league
takes no change; the file is written so that its values stay as they were.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..season import hillclimb as hc
from ..season import progress as pg
from . import leagues as league_files
from .season_knobs import KNOBS_FILE, autopilot_dir, load_knobs
from .season_progress import NOTES_DIR

_lock = threading.Lock()


def note_path(data_dir: Path, monday: date) -> Path:
    return autopilot_dir(data_dir) / NOTES_DIR / f"{monday.isoformat()}.md"


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def run(
    data_dir: Path,
    monday: date,
    now: datetime,
    progress: Callable[[], dict[str, Any]],
    scorings: dict[str, tuple[str, bool]],
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """The step for ``monday``: ``progress`` gives the Progress payload, ``scorings`` each
    league's scoring and whether it is public. Answers the step's verdicts, rules, change and
    note, ``status`` (``written``, ``dry_run`` or ``already``) and the files written."""
    if monday.weekday() != 0:
        raise HTTPException(422, f"{monday.isoformat()} is not a Monday")
    m = monday.isoformat()
    with _lock:
        raw, problems = load_knobs(data_dir)
        if problems or (why := hc.writable(raw)):
            raise HTTPException(
                409, f"the knob file cannot be written: {'; '.join(problems or why)}"
            )
        note = note_path(data_dir, monday)
        made = hc.ran(raw, m)
        if not force and (made or note.exists()):
            knobs, _ = pg.knob_file(raw)
            return {
                "monday": m,
                "status": "already",
                "changes": [c for c in knobs["changes"] if c["id"] in made],
                "note": note.read_text() if note.exists() else None,
                "written": [],
            }
        armed = {lg: s for lg, (s, public) in scorings.items() if public}
        try:
            out = hc.step(progress(), raw, monday, now, armed, scorings, force)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        written = []
        if not dry_run:
            if out["knobs"] != (raw or {}):
                path = autopilot_dir(data_dir) / KNOBS_FILE
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(out["knobs"], indent=2) + "\n")
                written.append(f"autopilot/{KNOBS_FILE}")
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(out["note"])
            written.append(f"autopilot/{NOTES_DIR}/{note.name}")
        return {**out, "status": "dry_run" if dry_run else "written", "written": written}


def scorings(
    data_dir: Path, base: Callable[[str], tuple[Any, bool]]
) -> dict[str, tuple[str, bool]]:
    """Every league folder's scoring and whether it is public, from its settings (``base``, the
    service's); a league whose settings cannot be read is left out."""
    out = {}
    for league in league_files.leagues(data_dir):
        try:
            settings, public = base(league)
        except HTTPException:
            continue
        out[league] = (settings.scoring or "categories", public)
    return out
