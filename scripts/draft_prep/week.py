"""The weekly projections (#117): import the user's Basketball Monster export of the rest of this
week or of next week, the week projection's games.

    python scripts/draft_day.py week --this                # newest WeeklyProjections*.xls in ~/Downloads
    python scripts/draft_day.py week --next --export FILE
    python scripts/draft_day.py week --this --end 2026-11-01

The user exports by hand (basketballmonster.com: Weekly Projections, Remaining Week or Next Week,
All Players, Refresh, Export to Excel), or a session does it from the user's signed-in Chrome;
nothing here logs in or handles credentials. The span is today in the NBA's zone through the
coming Sunday for ``--this`` (the page's Remaining Week button) and next Monday through the Sunday
after for ``--next`` (Next Week); ``--start`` and ``--end`` set either end instead.

The import validates the export with the reader the week projection uses and copies it to
``data/bbm_week_<this|next>_<UTC stamp>.xls`` (the name ``sources.bbm.fetch.weekly`` saves
under), keeping its file time, with the sidecar ``api/season_week.py`` matches to the week
(``start``, ``end``). It refuses a file that fails the schema, has a player with more games than
the span has days (a season export saved as a weekly one), holds fewer players than
``min_players`` asks (a filtered page: ``MIN_PLAYERS`` for next week, that share of seven days
for the rest of this week), was made on the wrong day for its span (a this-week export must be
today's, a next-week one from the week before; the check is off with ``--start``), or is the
other kind's saved export (a download that did not land). An export identical to the newest
saved one of its kind, for the same span, saves nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from pickandroll.sources.bbm import PROJECTION_SUFFIXES, load_bbm

HELP = "week: import a Basketball Monster weekly export, this week or next, into data/ (no league)"
LEAGUE = False

#: The export's name as the browser saves it (WeeklyProjections.xls, WeeklyProjections (1).xls).
EXPORT_GLOB = "WeeklyProjections*"
#: The saved files by kind, data/<prefix><UTC stamp>.xls, as ``api/season_week.py`` reads them.
SAVED = {"this": "bbm_week_this_", "next": "bbm_week_next_"}
#: The page's button for each kind, and the span's words in the output.
BUTTON = {"this": "Remaining Week", "next": "Next Week"}
WORDS = {"this": "the rest of this week", "next": "next week"}
#: An export of a full week with fewer players is a partial one (Only Top Players, a cut-off
#: download). On All Players the page lists every player then, those without a game in the
#: span too; over a shorter span it lists only the players with a game in it (#181).
MIN_PLAYERS = 300
NBA_TZ = ZoneInfo("America/New_York")


def min_players(which: str, days: int) -> int:
    """The fewest players a ``which`` export over ``days`` days may hold (#181): next week's the
    full :data:`MIN_PLAYERS`; the rest of this week's that share of a seven-day span, since a
    short span's page lists only the players with a game in it (139 on Sunday 2026-10-25, one
    day, about a third of the teams playing)."""
    if which == "next":
        return MIN_PLAYERS
    return math.ceil(MIN_PLAYERS * min(1.0, days / 7))


def day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD): {text!r}") from None


def add_arguments(parser: argparse.ArgumentParser) -> None:
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument(
        "--this",
        dest="week",
        action="store_const",
        const="this",
        help="week: the rest of this week, today through Sunday (Remaining Week)",
    )
    kind.add_argument(
        "--next",
        dest="week",
        action="store_const",
        const="next",
        help="week: next week, Monday through Sunday (Next Week)",
    )
    # --start is the script's own (servers --start); as week --start D it is the span's first day.
    parser.add_argument(
        "--end",
        type=day,
        metavar="D",
        help="week: the span's last day (YYYY-MM-DD) instead of the Sunday",
    )


def now() -> datetime:
    """The clock, read once per run."""
    return datetime.now(UTC)


def downloads() -> Path:
    return Path(os.environ.get("PICKANDROLL_DOWNLOADS", Path.home() / "Downloads"))


def newest_export(runbook: Any, which: str) -> Path:
    found = [
        p
        for p in downloads().glob(EXPORT_GLOB)
        if p.is_file() and p.suffix.lower() in PROJECTION_SUFFIXES
    ]
    if not found:
        raise runbook.Stop(
            runbook.ERROR,
            f"no {EXPORT_GLOB} in {downloads()}: export one (basketballmonster.com: Weekly "
            f"Projections, {BUTTON[which]}, All Players, Refresh, Export to Excel), then run again",
        )
    return max(found, key=lambda p: p.stat().st_mtime)


def span(which: str, today: date, start: date | None, end: date | None) -> tuple[date, date]:
    """The days the export covers: ``start`` (or today, or next Monday) through ``end`` (or the
    Sunday on or after the first day)."""
    first = start or (today if which == "this" else today + timedelta(days=7 - today.weekday()))
    return first, end or first + timedelta(days=6 - first.weekday())


def saved(data: Path, which: str) -> Path | None:
    """The newest saved export of a kind, by file time (the week projection's pick)."""
    files = [
        p
        for p in data.glob(f"{SAVED[which]}*")
        if p.is_file() and p.suffix.lower() in PROJECTION_SUFFIXES
    ]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def covered(path: Path) -> tuple[date, date] | None:
    """A saved export's span from its sidecar, None without one."""
    try:
        meta = json.loads(path.with_suffix(".json").read_text())
        return date.fromisoformat(meta["start"]), date.fromisoformat(meta["end"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> pd.DataFrame:
    """The export's normalized frame, read as the week projection reads it (``load_bbm``: the
    sheet through ``read_bbm_export`` and ``normalize_bbm``, a CSV in the draft's layout)."""
    return load_bbm(path, horizon="week").df


def dates(first: date, last: date) -> str:
    return f"{first:%a %Y-%m-%d} to {last:%a %Y-%m-%d}"


def import_export(
    runbook: Any, source: Path, which: str, start: date | None = None, end: date | None = None
) -> Path:
    """Validate ``source`` as a ``which``-week export and save it under data/; the saved file, or
    the newest one of its kind when ``source`` is identical to it. Refusals stop (exit 1) with
    the reason."""
    data, say, stop = runbook.DATA, runbook.say, runbook.Stop
    today = now().astimezone(NBA_TZ).date()
    first, last = span(which, today, start, end)
    if last < first:
        raise stop(runbook.ERROR, f"the span ends before it starts ({dates(first, last)})")
    days = (last - first).days + 1
    if not source.is_file():
        raise stop(runbook.ERROR, f"no export at {source}")
    if source.suffix.lower() not in PROJECTION_SUFFIXES:
        raise stop(runbook.ERROR, f"{source.name} is not a .xls, .xlsx or .csv export")
    try:
        df = read(source)
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        raise stop(
            runbook.ERROR,
            f"{source} is not a Basketball Monster weekly export ({exc}); nothing saved",
        ) from exc
    most = float(df["games"].max()) if len(df) else 0.0
    if most > days:
        raise stop(
            runbook.ERROR,
            f"{source} has a player with {most:g} games in a {days}-day span "
            f"({dates(first, last)}): a season or longer export? Nothing saved",
        )
    floor = min_players(which, days)
    if len(df) < floor:
        scaled = f" for a {days}-day span ({MIN_PLAYERS} × {days}/7)" if floor < MIN_PLAYERS else ""
        raise stop(
            runbook.ERROR,
            f"{source} holds {len(df)} players, under {floor}{scaled}: a partial export (Only "
            "Top Players, or a cut-off download?); nothing saved",
        )
    at = datetime.fromtimestamp(source.stat().st_mtime, UTC)
    made = at.astimezone(NBA_TZ).date()
    if start is None:
        if which == "this" and made != first:
            raise stop(
                runbook.ERROR,
                f"{source} was exported {made:%a %Y-%m-%d}, not today ({first:%a %Y-%m-%d}): an "
                f"older download? Export {BUTTON[which]} again; nothing saved",
            )
        if which == "next" and not first - timedelta(days=7) <= made < first:
            raise stop(
                runbook.ERROR,
                f"{source} was exported {made:%a %Y-%m-%d}, not in the week before "
                f"{first:%a %Y-%m-%d}: an older download? Export {BUTTON[which]} again; "
                "nothing saved",
            )
    mine = digest(source)
    for kind in (which, *(k for k in SAVED if k != which)):
        previous = saved(data, kind)
        if previous is None or digest(previous) != mine:
            continue
        theirs = covered(previous)
        if kind == which and theirs == (first, last):
            say(
                f"not saved: {source.name} is identical to {previous.name}, saved for "
                f"{dates(first, last)}; it stands"
            )
            return previous
        held = dates(*theirs) if theirs else "no span"
        raise stop(
            runbook.ERROR,
            f"{source} is identical to {previous.name} ({WORDS[kind]}, {held}): an older "
            f"download? Check that the {BUTTON[which]} export landed; nothing saved",
        )
    target = data / f"{SAVED[which]}{at:%Y%m%d-%H%M}{source.suffix.lower()}"
    if target.exists():
        raise stop(runbook.ERROR, f"{target.name} exists already; nothing saved")
    meta = {
        "source": "bbm",
        "horizon": "week",
        "as_of": at.isoformat(),
        "start": first.isoformat(),
        "end": last.isoformat(),
        "file": target.name,
    }
    target.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    tmp = target.with_name(target.name + ".part")
    shutil.copy2(source, tmp)
    tmp.replace(target)
    playing = int((df["games"] > 0).sum())
    say(
        f"saved data/{target.name} from {source}: {WORDS[which]}, {dates(first, last)} "
        f"({days} day{'s' if days != 1 else ''}), {len(df)} players, {playing} with games, at most {most:g}, exported "
        f"{at.astimezone():%a %Y-%m-%d %H:%M}"
    )
    return target


def run(runbook: Any, args: argparse.Namespace) -> int:
    which = getattr(args, "week", None)
    if which is None:
        raise runbook.Stop(runbook.ERROR, "week needs --this or --next")
    start = getattr(args, "start", None)
    if start is True:
        raise runbook.Stop(runbook.ERROR, "week --start needs a date (YYYY-MM-DD)")
    try:
        first = date.fromisoformat(start) if start else None
    except ValueError:
        raise runbook.Stop(
            runbook.ERROR, f"week --start: not a date (YYYY-MM-DD): {start!r}"
        ) from None
    export = getattr(args, "export", None)
    source = Path(export).expanduser() if export else newest_export(runbook, which)
    import_export(runbook, source, which, first, getattr(args, "end", None))
    return runbook.OK
