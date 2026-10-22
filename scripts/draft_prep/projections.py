"""This morning's projections (#75): import the user's Basketball Monster export, flag a stale one.

    python scripts/draft_day.py projections                  # newest Projections*.csv: ~/Downloads, repo root
    python scripts/draft_day.py projections --export FILE    # this export
    python scripts/draft_day.py run <league> --bbm-fetch     # follow-on: the headless refresh first

The user exports by hand (basketballmonster.com: Member, Projections 26-27, Export CSV). Nothing
here logs in or handles credentials. The import validates the export with the session's own loader
and copies it to ``data/bbm_projections_<date>.csv``, the date being the export's (its file time,
which the copy keeps and the loader reads as ``as_of``). It refuses a file that fails the schema,
holds too few players, or is older than the newest saved file. An export identical to the newest
saved file saves nothing: that file stands and is dated at the new export's time, since Basketball
Monster has not changed it since. It then prints the players whose games or value moved most against
the previous file, names and directions only.

``status`` prints the newest file and its export time, with an ALERT when it is older than
``STALE_DAYS``; ``run`` repeats the ALERT before the attach. ``--bbm-fetch`` (off by default) makes
``run`` refresh first through the Basketball Monster profile the user logged into once, headed
(``scripts/bbm_fetch.py``). A missing or logged-out profile, or any failure, leaves the newest file
on disk in place.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from pickandroll.projections.names import normalize_name
from pickandroll.projections.schema import NINE_CAT
from pickandroll.projections.zscores import zscores
from pickandroll.sources.bbm import PROJECTION_SUFFIXES, load_bbm

HELP = "projections: import this morning's Basketball Monster export into data/ (no league)"
LEAGUE = False

#: The export's name as the browser saves it (Projections.csv, Projections (1).csv, ...).
EXPORT_GLOB = "Projections*.csv"
#: The saved files, data/bbm_projections_<date>[T<time>].<csv|xls|xlsx>.
SAVED_PREFIX = "bbm_projections_"
#: Older than this, status and run raise an ALERT.
STALE_DAYS = 2.0
#: An export with fewer players is a partial one (a filtered page, a cut-off download).
MIN_PLAYERS = 300
#: Movers are looked for among the top this many by value, in either file.
TOP = 200
#: The value: nine-category total z over a 12-team, 13-round pool.
POOL = 156
#: A move worth listing: this many games, or this much total z.
GAMES_MOVE = 3.0
VALUE_MOVE = 0.5
#: Names per list.
LIST = 8


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--export",
        metavar="FILE",
        help="projections, past-days, week: import this export instead of the newest download",
    )
    parser.add_argument(
        "--bbm-fetch",
        action="store_true",
        help="projections, run: refresh headless through data/bbm-profile first (follow-on; "
        "needs the user's one headed login, scripts/bbm_fetch.py)",
    )


# --------------------------------------------------------------------------- files
def downloads() -> Path:
    return Path(os.environ.get("PICKANDROLL_DOWNLOADS", Path.home() / "Downloads"))


def exported_at(path: Path) -> datetime:
    """The export's time: the file's modification time, which the import's copy keeps."""
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).astimezone()


def saved(data: Path) -> list[Path]:
    """The saved projection files, oldest first: by the date in the name, then the file time."""
    files = [
        p
        for p in data.glob(f"{SAVED_PREFIX}*")
        if p.is_file() and p.suffix.lower() in PROJECTION_SUFFIXES
    ]
    return sorted(files, key=lambda p: (p.stem, p.stat().st_mtime))


def newest(data: Path) -> Path | None:
    files = saved(data)
    return files[-1] if files else None


def newest_export(runbook: Any) -> Path:
    places = (downloads(), runbook.ROOT)
    found = [p for place in places for p in place.glob(EXPORT_GLOB) if p.is_file()]
    if not found:
        raise runbook.Stop(
            runbook.ERROR,
            f"no {EXPORT_GLOB} in {downloads()} or the repo root: export one "
            "(basketballmonster.com: Member, Projections 26-27, Export CSV), then run again",
        )
    return max(found, key=lambda p: p.stat().st_mtime)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> pd.DataFrame:
    return load_bbm(path).df


# --------------------------------------------------------------------------- movers
def values(df: pd.DataFrame) -> pd.DataFrame:
    """Name, games and value (nine-category total z) per player, keyed by the normalized name."""
    z = zscores(df, NINE_CAT, pool_size=POOL)
    out = pd.DataFrame(
        {"player": df["player"], "games": df["games"].astype(float), "value": z["total"]}
    )
    out.index = pd.Index([normalize_name(p) for p in df["player"]])
    return out[~out.index.duplicated()]


def movers(old: pd.DataFrame, new: pd.DataFrame) -> dict[str, list[str]]:
    """The players whose games or value moved most from ``old`` to ``new``, among the top ``TOP``
    by value in either: names only, the largest move first. A player listed for games is not
    listed again for value."""
    a, b = values(old), values(new)
    top = list(dict.fromkeys([*b.nlargest(TOP, "value").index, *a.nlargest(TOP, "value").index]))
    both = [k for k in top if k in a.index and k in b.index]
    games = b.loc[both, "games"] - a.loc[both, "games"]
    value = b.loc[both, "value"] - a.loc[both, "value"]

    def largest(moves: pd.Series, skip: frozenset[str] = frozenset()) -> list[str]:
        order = moves.abs().sort_values(ascending=False, kind="stable").index
        return [k for k in order if k not in skip][:LIST]

    games_down = largest(games[games <= -GAMES_MOVE])
    games_up = largest(games[games >= GAMES_MOVE])
    listed = frozenset([*games_down, *games_up])
    lists = {
        "games down": games_down,
        "games up": games_up,
        "value down": largest(value[value <= -VALUE_MOVE], listed),
        "value up": largest(value[value >= VALUE_MOVE], listed),
        "new to the export": [k for k in top if k not in a.index][:LIST],
    }
    out = {label: [str(b.loc[k, "player"]) for k in keys] for label, keys in lists.items()}
    out["gone from the export"] = [str(a.loc[k, "player"]) for k in top if k not in b.index][:LIST]
    return out


# --------------------------------------------------------------------------- the import
def import_export(runbook: Any, source: Path) -> Path:
    """Validate ``source`` and save it as data/bbm_projections_<date>; the saved file, or the
    newest one when ``source`` is identical to it. Refusals stop (exit 1) with the reason."""
    data, say, stop = runbook.DATA, runbook.say, runbook.Stop
    if not source.is_file():
        raise stop(runbook.ERROR, f"no export at {source}")
    if source.suffix.lower() not in PROJECTION_SUFFIXES:
        raise stop(runbook.ERROR, f"{source.name} is not a .csv, .xls or .xlsx export")
    try:
        df = load(source)
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        raise stop(
            runbook.ERROR,
            f"{source} is not a Basketball Monster projection export ({exc}); nothing saved",
        ) from exc
    players = int((df["games"] > 0).sum())
    if players < MIN_PLAYERS:
        raise stop(
            runbook.ERROR,
            f"{source} holds {players} players with games, under {MIN_PLAYERS}: a partial export "
            "(a filtered page or a cut-off download?); nothing saved",
        )
    at = exported_at(source)
    previous = newest(data)
    if previous is not None:
        before = exported_at(previous)
        same = digest(previous) == digest(source)
        if not same and previous.suffix.lower() == source.suffix.lower():
            try:
                same = load(previous).equals(df)
            except (ValueError, KeyError, OSError, pd.errors.ParserError):
                same = False
        if same:
            if at > before:
                os.utime(previous, (at.timestamp(), at.timestamp()))
            say(
                f"not saved: {source.name} is identical to {previous.name}, so Basketball "
                f"Monster has not changed it; {previous.name} stands, dated "
                f"{max(at, before):%a %Y-%m-%d %H:%M}"
            )
            return previous
        if at < before:
            raise stop(
                runbook.ERROR,
                f"{source} (exported {at:%a %Y-%m-%d %H:%M}) is older than {previous.name} "
                f"(exported {before:%a %Y-%m-%d %H:%M}): export a fresh one; nothing saved",
            )
    suffix = source.suffix.lower()
    target = data / f"{SAVED_PREFIX}{at:%Y-%m-%d}{suffix}"
    if target.exists():
        target = data / f"{SAVED_PREFIX}{at:%Y-%m-%dT%H%M%S}{suffix}"
    if target.exists():
        raise stop(runbook.ERROR, f"{target.name} exists already; nothing saved")
    tmp = target.with_name(target.name + ".part")
    shutil.copy2(source, tmp)
    tmp.replace(target)
    say(
        f"saved data/{target.name} from {source}: {players} players, exported "
        f"{at:%a %Y-%m-%d %H:%M}"
    )
    if previous is not None:
        report_movers(runbook, previous, df)
    return target


def report_movers(runbook: Any, previous: Path, df: pd.DataFrame) -> None:
    try:
        moved = movers(load(previous), df)
    except (ValueError, KeyError, OSError, pd.errors.ParserError) as exc:
        runbook.say(f"movers: {previous.name} does not load ({exc}); none listed")
        return
    runbook.say(f"movers against {previous.name}, top {TOP} by value:")
    for label, names in moved.items():
        if names:
            runbook.say(f"  {label}: {', '.join(names)}")
    if not any(moved.values()):
        runbook.say("  none")


# --------------------------------------------------------------------------- the fetch
def open_fetcher(profile: Path, out: Path) -> Any:
    from pickandroll.sources.bbm.fetch import BBMFetcher

    return BBMFetcher(headless=True, profile_dir=profile, data_dir=out)


def fetch(runbook: Any) -> Path | None:
    """The headless refresh (``--bbm-fetch``): the projections page's export through the profile
    the user logged into once, headed. ``None`` when there is no profile, it is logged out (this
    never signs in), or anything else fails; the newest file on disk then stands."""
    say = runbook.say
    profile = runbook.DATA / "bbm-profile"
    keep = "; the newest file on disk stands"
    if not profile.is_dir():
        say(
            "ALERT --bbm-fetch: no Basketball Monster profile at data/bbm-profile (the user logs "
            f"in once, headed: python scripts/bbm_fetch.py --ros){keep}"
        )
        return None
    try:
        with open_fetcher(profile, runbook.DATA / "draft_day" / "bbm_fetch") as bbm:
            bbm.ensure_login()
            path = bbm.rest_of_season("totals")
    except RuntimeError as exc:
        say(f"ALERT --bbm-fetch: {exc}{keep}")
        return None
    except Exception as exc:  # noqa: BLE001 - the refresh is best effort
        say(f"ALERT --bbm-fetch failed ({type(exc).__name__}: {exc}){keep}")
        return None
    say(f"--bbm-fetch: downloaded {Path(path).name}")
    return Path(path)


# --------------------------------------------------------------------------- staleness
def freshness(runbook: Any, now: datetime | None = None) -> tuple[str, bool]:
    """The newest saved file and its export time, and whether it is older than ``STALE_DAYS``."""
    path = newest(runbook.DATA)
    if path is None:
        return (
            f"ALERT no data/{SAVED_PREFIX}* file: export one and run `draft_day.py projections`",
            True,
        )
    at = exported_at(path)
    age = (now or datetime.now(UTC)) - at
    line = f"projections {path.name}, exported {at:%a %Y-%m-%d %H:%M}"
    if age <= timedelta(days=STALE_DAYS):
        return line, False
    alert = (
        f"ALERT {line}, {age.total_seconds() / 86400:.1f} days ago: export this morning's "
        "(Member, Projections 26-27, Export CSV) and run `draft_day.py projections`"
    )
    return alert, True


def on_status(runbook: Any, league: str) -> None:
    runbook.say("  " + freshness(runbook)[0])


def before_attach(runbook: Any, league: str, args: argparse.Namespace) -> None:
    if getattr(args, "bbm_fetch", False):
        path = fetch(runbook)
        if path is not None:
            try:
                import_export(runbook, path)
            except runbook.Stop as exc:
                runbook.say(f"ALERT --bbm-fetch: {exc}; the newest file on disk stands")
    line, stale = freshness(runbook)
    if stale:
        runbook.say(line)


# --------------------------------------------------------------------------- the command
def run(runbook: Any, args: argparse.Namespace) -> int:
    source = None
    if args.bbm_fetch:
        source = fetch(runbook)
    if source is None:
        source = Path(args.export).expanduser() if args.export else newest_export(runbook)
    import_export(runbook, source)
    return runbook.OK
