"""The past-days rankings (#95): import the user's Basketball Monster export of the last 7 or 14 days,
the breakout flag's minutes trend.

    python scripts/draft_day.py past-days --days 7                # newest BBM_PlayerRankings*.xls in ~/Downloads
    python scripts/draft_day.py past-days --days 14 --export FILE

The user exports by hand (basketballmonster.com: Rankings, All Players, Past 1 Week or Past 2
Weeks, Export to Excel), or a session does it from the user's signed-in Chrome; nothing here logs
in or handles credentials. The import validates the export with the session's own parser and
copies it to ``data/bbm_actual_<days>d_<totals|pergame>_<UTC stamp>.xls`` (the name
``scripts/bbm_fetch.py --actual`` saves under), keeping its file time, with the same sidecar. It
refuses a file that fails the schema, holds no player with a game, or has a player with more
games than the window allows (a season export saved as a past-days one).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from pickandroll.sources.bbm import PROJECTION_SUFFIXES
from pickandroll.sources.bbm.parse import is_per_game, normalize_bbm, read_bbm_export

HELP = "past-days: import a Basketball Monster past 7 or 14 days export into data/ (no league)"
LEAGUE = False

#: The export's name as the browser saves it (BBM_PlayerRankings.xls, BBM_PlayerRankings (1).xls).
EXPORT_GLOB = "BBM_PlayerRankings*"
#: The windows the flag reads, and the most games an NBA team plays in each.
MOST_GAMES = {7: 5, 14: 9}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--days",
        type=int,
        choices=sorted(MOST_GAMES),
        default=7,
        help="past-days: the window the export covers (default 7)",
    )


def downloads() -> Path:
    return Path(os.environ.get("PICKANDROLL_DOWNLOADS", Path.home() / "Downloads"))


def newest_export(runbook: Any) -> Path:
    found = [
        p
        for p in downloads().glob(EXPORT_GLOB)
        if p.is_file() and p.suffix.lower() in PROJECTION_SUFFIXES
    ]
    if not found:
        raise runbook.Stop(
            runbook.ERROR,
            f"no {EXPORT_GLOB} in {downloads()}: export one (basketballmonster.com: Rankings, "
            "All Players, Past 1 Week or Past 2 Weeks, Export to Excel), then run again",
        )
    return max(found, key=lambda p: p.stat().st_mtime)


def read(path: Path) -> tuple[pd.DataFrame, bool]:
    """The export's normalized frame (a sheet, or a CSV with the sheet's columns) and whether it
    was a per-game one."""
    raw = pd.read_csv(path) if path.suffix.lower() == ".csv" else read_bbm_export(path)
    return normalize_bbm(raw), is_per_game(raw)


def import_export(runbook: Any, source: Path, days: int) -> Path:
    """Validate ``source`` as a ``days``-day export and save it under data/; the saved file.
    Refusals stop (exit 1) with the reason."""
    data, say, stop = runbook.DATA, runbook.say, runbook.Stop
    if not source.is_file():
        raise stop(runbook.ERROR, f"no export at {source}")
    if source.suffix.lower() not in PROJECTION_SUFFIXES:
        raise stop(runbook.ERROR, f"{source.name} is not a .xls, .xlsx or .csv export")
    try:
        df, per_game = read(source)
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        raise stop(
            runbook.ERROR,
            f"{source} is not a Basketball Monster rankings export ({exc}); nothing saved",
        ) from exc
    played = df[df["games"] > 0]
    if played.empty:
        raise stop(runbook.ERROR, f"{source} holds no player with a game; nothing saved")
    most = float(played["games"].max())
    if most > MOST_GAMES[days]:
        raise stop(
            runbook.ERROR,
            f"{source} has a player with {most:g} games, more than a team plays in {days} days: "
            "a season or longer export? Nothing saved",
        )
    at = datetime.fromtimestamp(source.stat().st_mtime, UTC)
    kind = "pergame" if per_game else "totals"
    target = data / f"bbm_actual_{days}d_{kind}_{at:%Y%m%d-%H%M}{source.suffix.lower()}"
    if target.exists():
        raise stop(runbook.ERROR, f"{target.name} exists already; nothing saved")
    tmp = target.with_name(target.name + ".part")
    shutil.copy2(source, tmp)
    tmp.replace(target)
    meta = {
        "source": "bbm",
        "horizon": "custom",
        "as_of": at.isoformat(),
        "start": (at.date() - timedelta(days=days)).isoformat(),
        "end": at.date().isoformat(),
        "file": target.name,
    }
    target.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    say(
        f"saved data/{target.name} from {source}: {len(played)} players with games over "
        f"{days} days, at most {most:g}, exported {at.astimezone():%a %Y-%m-%d %H:%M}"
    )
    return target


def run(runbook: Any, args: argparse.Namespace) -> int:
    export = getattr(args, "export", None)
    source = Path(export).expanduser() if export else newest_export(runbook)
    import_export(runbook, source, args.days)
    return runbook.OK
