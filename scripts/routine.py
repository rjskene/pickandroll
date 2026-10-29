"""The routines, from the terminal or a timer (#225, docs/AUTOPILOT.md §3):

    python scripts/routine.py daily                # 05:00: refresh, solve, queue, digest on #99
    python scripts/routine.py morning              # 07:45: the due entries' pages (the extension acts)
    python scripts/routine.py late                 # 15:00: lineups late, moves late, re-solve
    python scripts/routine.py evening-build        # 21:00: refresh, re-solve, rebuild the queue
    python scripts/routine.py evening-pass         # 22:40: the evening's pages, hard stop 22:58
    python scripts/routine.py monday               # Mon 06:00: record, scorecard, hill-climb, queue
    python scripts/routine.py daily --dry-run      # the plan from the live API; writes nothing
    python scripts/routine.py daily --force        # outside the window (a test, a re-run)

The API is ``PICKANDROLL_API`` (http://127.0.0.1:8000). ``--no-post`` keeps the GitHub comments
off (the soak); ``--no-marker`` keeps the daily from writing data/routine/daily.json; ``--json``
prints the report as JSON after the summary. Every run writes data/routine/runs/<day>-<name>.json
unless it was a dry run.

Exit codes: 0 every step ok or skipped by its rule; 1 a step failed; 2 the API is unreachable;
3 outside the routine's window (nothing ran); 4 STOP is set (nothing ran).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.routine import CENTRAL, Context, Report, Unreachable, http, now, run
from pickandroll.routine.report import marker, write_json
from pickandroll.routine.routines import ROUTINES
from pickandroll.routine.steps import gh_comment, script_runner

API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
DATA = Path(os.environ.get("PICKANDROLL_DATA", ROOT / "data"))
OK, FAILED, UNREACHABLE, REFUSED, STOPPED = 0, 1, 2, 3, 4


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("routine", choices=sorted(ROUTINES))
    p.add_argument("--api", default=API)
    p.add_argument("--data", type=Path, default=DATA, help="the API's data folder (the marker, STOP)")
    p.add_argument("--dry-run", action="store_true", help="reads only; the plan from the live answers")
    p.add_argument("--no-post", action="store_true", help="no GitHub comments")
    p.add_argument("--no-marker", action="store_true", help="the daily writes no data/routine/daily.json")
    p.add_argument("--force", action="store_true", help="run outside the routine's window")
    p.add_argument("--json", action="store_true", help="print the report as JSON too")
    p.add_argument("--now", help="pretend it is this time (ISO, Central if naive); for tests")
    args = p.parse_args(argv)

    if args.now:
        fixed = datetime.fromisoformat(args.now)
        fixed = fixed.replace(tzinfo=CENTRAL) if fixed.tzinfo is None else fixed.astimezone(CENTRAL)
        started = time.monotonic()
        clock = lambda: fixed.fromtimestamp(fixed.timestamp() + time.monotonic() - started, CENTRAL)
    else:
        clock = now

    report = Report(args.routine, clock(), clock=clock)
    ctx = Context(
        call=http(args.api),
        now=clock,
        sleep=time.sleep,
        report=report,
        data_dir=args.data,
        run_script=script_runner(ROOT, sys.executable),
        post=gh_comment,
        browser=None,
        dry_run=args.dry_run,
        posting=not args.no_post,
    )
    try:
        run(args.routine, ctx, args.api, force=args.force)
    except Unreachable as exc:
        report.failed("api", f"unreachable: {exc}")
        report.finished = clock()
        print(report.summary())
        return UNREACHABLE

    print(report.summary())
    if args.json:
        print(json.dumps(report.to_dict(), indent=1))
    if report.refused:
        return REFUSED  # nothing ran, nothing written
    if report.unreachable:
        return UNREACHABLE  # likewise: a run log of a silent API would hide the real one
    if not args.dry_run:
        day = report.started.date().isoformat()
        write_json(args.data / "routine" / "runs" / f"{day}-{args.routine}.json", report.to_dict())
        if args.routine == "daily" and not args.no_marker:
            write_json(args.data / "routine" / "daily.json", marker(report))
    if report.stopped:
        return STOPPED
    return FAILED if report.any_failed else OK


if __name__ == "__main__":
    sys.exit(main())
