"""SEASON SIM (#172): the season simulator's commands, for the terminal.

    python scripts/season_sim.py fetch-logs --seasons 2022-2026   # ESPN's per-game logs, cached
    python scripts/season_sim.py fit --hold-out 2025              # the world's fit, frozen with a hash
    python scripts/season_sim.py fit --dry-run                    # the fit printed, nothing written

ESPN's season id is the year the season ends in: 2025 is 2024-25, the hold-out. ``fetch-logs``
makes one request a season through the same player view the draft-edge audit read, caches each
under ``data/external/espn/gamelogs/`` (never committed) and never retries inside a run. ``fit``
refuses the hold-out, fits each cached season, pools the ones that agree and writes
``data/autopilot/sim/fit/<date>/fit.json`` with ``fit.sha256`` beside it; the frozen fit's
figures stay under ``data/`` and are described in words anywhere public.

Every command runs through :func:`guard`: at low priority (``nice``), never between 04:45 and
06:45 on the Mac's clock (the routines' window), never while a draft room is open on the API,
and a run expected over an hour is for the session to announce to fantasyMASTER first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pickandroll.season.sim import fit as fitmod
from pickandroll.sources import gamelogs

API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
DATA = ROOT / "data"
LOGS_DIR = Path("external") / "espn" / "gamelogs"
FIT_DIR = Path("autopilot") / "sim" / "fit"
#: The routines' window on the Mac's clock: no run starts inside it.
QUIET_FROM = time(4, 45)
QUIET_TO = time(6, 45)
#: Runs expected to take longer are announced to fantasyMASTER before they start.
ANNOUNCE_HOURS = 1.0
NICE = 10
TIMEOUT = 60
#: The hold-out season (#172): 2024-25, in no fit.
HOLD_OUT = 2025
#: The five seasons the fit may see, ESPN ids (2022 is 2021-22).
SEASONS = (2022, 2023, 2024, 2025, 2026)


# --------------------------------------------------------------------------- guard
def rooms_open(api: str = API, timeout: int = 5) -> int | None:
    """How many draft rooms the API holds; None when it cannot be asked (then none is assumed:
    a server that is down has no room on it)."""
    try:
        with urllib.request.urlopen(f"{api}/rooms", timeout=timeout) as r:
            return len(json.loads(r.read().decode()))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def in_quiet_window(now: datetime) -> bool:
    return QUIET_FROM <= now.time() < QUIET_TO


def guard(
    expected_hours: float = 0.0,
    now: datetime | None = None,
    rooms: int | None = None,
    announced: bool = False,
    nice: Callable[[int], Any] | None = os.nice,
) -> tuple[bool, str]:
    """Whether a run may start now, and why not: inside the quiet window, with a draft room
    open, or long and not yet announced. Lowers the process priority on the way."""
    now = now or datetime.now().astimezone()
    if in_quiet_window(now):
        return False, f"inside the routines' window ({QUIET_FROM:%H:%M}-{QUIET_TO:%H:%M} Mac clock)"
    open_rooms = rooms_open() if rooms is None else rooms
    if open_rooms:
        return False, f"{open_rooms} draft room(s) open on the API"
    if expected_hours > ANNOUNCE_HOURS and not announced:
        return False, f"a run of about {expected_hours:g} h is announced to fantasyMASTER first"
    if nice is not None:
        try:
            nice(NICE)
        except OSError:
            pass
    return True, "ok"


# --------------------------------------------------------------------------- fetch
def espn_fetch(url: str, timeout: int = TIMEOUT) -> str:
    """One request to ESPN's player view with the audit's filter header."""
    req = urllib.request.Request(url, headers={gamelogs.FILTER_HEADER: gamelogs.FILTER})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def parse_seasons(text: str) -> list[int]:
    """``2022-2026`` or ``2022,2024``."""
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def cmd_fetch(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    out = gamelogs.read_seasons(parse_seasons(args.seasons), espn_fetch, args.data / LOGS_DIR)
    for key in ("read", "cached", "failed"):
        if out[key]:
            print(f"{key}: {', '.join(str(s) for s in out[key])}")
    return 1 if out["failed"] else 0


# --------------------------------------------------------------------------- fit
def load_lines(seasons: Sequence[int], data: Path) -> dict[int, list[fitmod.GameLine]]:
    out: dict[int, list[fitmod.GameLine]] = {}
    for season in seasons:
        body = gamelogs.load_season(season, data / LOGS_DIR)
        if body is not None:
            out[season] = gamelogs.lines_of(body, season)
    return out


def run_fit(
    seasons: Sequence[int], hold_out: int | None, data: Path
) -> tuple[dict[str, Any], str, fitmod.Fit]:
    """Fit every cached season of ``seasons`` but the hold-out, pool, freeze."""
    fitmod.check_hold_out(seasons, hold_out)
    lines = load_lines(seasons, data)
    if not lines:
        raise FileNotFoundError(f"no cached season among {list(seasons)} under {data / LOGS_DIR}")
    fits = [fitmod.fit_season(rows, season) for season, rows in sorted(lines.items())]
    pooled = fitmod.pool(fits)
    payload, sha = fitmod.freeze(pooled, hold_out, seasons=fits)
    return payload, sha, pooled


def describe(payload: dict[str, Any]) -> str:
    """The fit in words and counts: no fitted figure (they stay under ``data/``)."""
    seasons = ", ".join(str(s) for s in payload["seasons"])
    separate = ", ".join(payload["separate"]) or "none"
    players = payload["dispersion"]["fitted_players"]
    return (
        f"seasons pooled: {seasons}; kept apart: {separate}; hold-out: {payload['hold_out']}; "
        f"players with a dispersion of their own: {players}; "
        f"games in the dispersion fit: {payload['dispersion']['games']}; "
        f"player-seasons in the hazard fit: {payload['hazard']['players']}"
    )


def cmd_fit(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    seasons = [s for s in parse_seasons(args.seasons) if s != args.hold_out]
    try:
        payload, sha, _ = run_fit(seasons, args.hold_out, args.data)
    except (fitmod.HoldOutError, FileNotFoundError) as e:
        print(f"refused: {e}")
        return 2
    print(describe(payload))
    if args.dry_run:
        print(f"sha256 {sha} (dry run, nothing written)")
        return 0
    out = args.data / FIT_DIR / datetime.now(UTC).date().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "fit.json").write_text(json.dumps(payload, indent=1, sort_keys=True))
    (out / "fit.sha256").write_text(sha + "\n")
    print(f"written: {out / 'fit.json'} sha256 {sha}")
    return 0


# --------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=DATA, help="the data folder (default data/)")
    ap.add_argument("--rooms", type=int, default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", required=True)
    fe = sub.add_parser("fetch-logs", help="ESPN's per-game logs for whole seasons, cached")
    fe.add_argument("--seasons", default="2022-2026", help="ESPN season ids, e.g. 2022-2026")
    fe.set_defaults(func=cmd_fetch)
    fi = sub.add_parser("fit", help="the world's fit over the cached seasons, frozen with a hash")
    fi.add_argument("--seasons", default="2022-2026")
    fi.add_argument("--hold-out", type=int, default=HOLD_OUT, help="the season no fit sees")
    fi.add_argument("--dry-run", action="store_true", help="print the fit, write nothing")
    fi.set_defaults(func=cmd_fit)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
