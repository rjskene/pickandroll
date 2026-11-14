"""SEASON SIM (#172): the season simulator's commands, for the terminal.

    python -m pickandroll.sim fetch-logs --seasons 2022-2026   # ESPN's per-game logs, cached
    python -m pickandroll.sim fit                              # the world's fit, frozen with a hash
    python -m pickandroll.sim fit --dry-run                    # the fit printed, nothing written
    python -m pickandroll.sim fit --refresh --tau residual --league <id>   # week six's re-freeze
    python -m pickandroll.sim compare A.json B.json --leagues all --paths 100
    python -m pickandroll.sim replay --season 2024 --standin prior --seats A.json B.json
    python -m pickandroll.sim replay --season 2024 --seats A.json B.json --no-peek 2023-12-04
    python -m pickandroll.sim room --leagues all --seats A.json B.json --draft rosters
    python -m pickandroll.sim validate --league all

ESPN's season id is the year the season ends in: 2025 is 2024-25, the hold-out. ``fetch-logs``
makes one request a season through the same player view the draft-edge audit read, caches each
under ``data/external/espn/gamelogs/`` (never committed) and never retries inside a run. ``fit``
refuses the hold-out whatever the flags say (``--hold-out`` may only add a second season no
fit sees), fits each cached season, pools the ones that agree and writes
``data/sim/fit/<date>/fit.json`` with ``fit.sha256`` beside it; the frozen fit's
figures stay under ``data/`` and are described in words anywhere public.

``compare`` plays each league's rest of the season from today many times over in the same
simulated worlds, once with arm A in my seat and once with arm B, at three shrinks of the
projection error toward the market, and reports the paired difference, B less A, with its
standard error: the verdict line is advisory (the design note's one-SE rule; no block and no
promotion before PR 3). ``replay`` plays a made-up league on a recorded season's game lines,
never the hold-out, its seats believing only the games already played; ``--no-peek`` checks one
path of it against a season changed after a date and writes nothing.
``room`` seats the arms given around one league's table, rotated across paths. ``validate`` runs
the six gates on this season's recorded weeks and on the hold-out, side by side, and writes what
each had to work with. Every run's payload goes under ``data/sim/runs/`` with the code's
commit, the fit's hash, the hold-out, the spec files verbatim and the execution model.

Every command runs through :func:`guard`: at low priority (``nice``), never when its span would
touch 04:45-06:45 on the Mac's clock (the routines' window), never while a draft room is open on
the API, and a run expected over an hour is for the session to announce to fantasyMASTER first.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import time as clock
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from ..api import seasons as season_api
from ..api.leagues import leagues as all_leagues
from . import audit, checks, gamelogs, nopeek, policy, world
from . import counts as ct
from . import fit as fitmod
from . import readers as reader
from . import run as rn
from . import validate as vg
from .engine import wk
from .state import snake_draft, weeks_from

#: The repository: this file is ``src/pickandroll/sim/cli.py``.
ROOT = Path(__file__).resolve().parents[3]
API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
#: How the commands are run (argparse would otherwise name ``__main__.py``).
PROG = "python -m pickandroll.sim"
DATA = ROOT / "data"
LOGS_DIR = reader.LOGS_DIR
FIT_DIR = reader.FIT_DIR
#: The routines' window on the Mac's clock: no run's span touches it.
QUIET_FROM = time(4, 45)
QUIET_TO = time(6, 45)
#: Runs expected to take longer are announced to fantasyMASTER before they start.
ANNOUNCE_HOURS = 1.0
NICE = 10
TIMEOUT = 60
#: The hold-out season (#172): 2024-25, in no fit, never a replay's or a comparison's target.
HOLD_OUT = 2025
#: The five seasons on disk, ESPN ids (2022 is 2021-22), and the ones a fit may see.
SEASONS = (2022, 2023, 2024, 2025, 2026)
FIT_SEASONS = ",".join(str(s) for s in SEASONS if s != HOLD_OUT)
THIS_SEASON = 2026
#: Paths a comparison runs by default (the design note: SE of the playoff-odds change about
#: 0.6 points at a hundred).
PATHS = 100
#: The paths a gate's samples are drawn over.
GATE_PATHS = 200
#: The league-days gate 5 samples: today and these offsets.
GATE_DAYS = (0, 3, 7, 10, 14)
EXECUTIONS = policy.EXECUTIONS


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


def touches_quiet_window(start: datetime, hours: float) -> bool:
    """Whether a run from ``start`` lasting ``hours`` would run into the routines' window: its
    start inside it, or the window's next opening before its end."""
    if in_quiet_window(start):
        return True
    end = start + timedelta(hours=max(0.0, hours))
    opening = datetime.combine(start.date(), QUIET_FROM, tzinfo=start.tzinfo)
    if opening <= start:
        opening += timedelta(days=1)
    return opening < end


def now_local() -> datetime:
    """The guard's clock, the Mac's local time. A seam the tests pin: a suite run inside the
    routines' window must not have every command refused for the hour it runs at."""
    return datetime.now().astimezone()


def guard(
    expected_hours: float = 0.0,
    now: datetime | None = None,
    rooms: int | None = None,
    announced: bool = False,
    nice: Callable[[int], Any] | None = os.nice,
) -> tuple[bool, str]:
    """Whether a run may start now, and why not: its span touching the quiet window, a draft
    room open, or long and not yet announced. Lowers the process priority on the way."""
    now = now or now_local()
    if touches_quiet_window(now, expected_hours):
        return False, (
            f"a run of about {expected_hours:g} h from now touches the routines' window "
            f"({QUIET_FROM:%H:%M}-{QUIET_TO:%H:%M} Mac clock)"
            if expected_hours
            else f"inside the routines' window ({QUIET_FROM:%H:%M}-{QUIET_TO:%H:%M} Mac clock)"
        )
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
    seasons: Sequence[int],
    data: Path,
    extra_hold_out: int | None = None,
    tau: Mapping[str, float] | None = None,
    refresh: fitmod.Refresh | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str, fitmod.Fit]:
    """Fit every cached season of ``seasons``, pool, freeze. The named hold-out
    (:data:`HOLD_OUT`) is refused whatever the flags say; ``extra_hold_out`` may add a second
    season no fit sees, never remove the named one. ``tau`` and ``refresh`` are week six's
    re-freeze (the residual tau and the fitted refresh together)."""
    fitmod.check_hold_out(seasons, HOLD_OUT)
    fitmod.check_hold_out(seasons, extra_hold_out)
    lines = load_lines(seasons, data)
    if not lines:
        raise FileNotFoundError(f"no cached season among {list(seasons)} under {data / LOGS_DIR}")
    fits = [fitmod.fit_season(rows, season) for season, rows in sorted(lines.items())]
    pooled = fitmod.pool(fits)
    extra = {"extra_hold_out": extra_hold_out} if extra_hold_out not in (None, HOLD_OUT) else {}
    extra |= dict(parameters or {})
    payload, sha = fitmod.freeze(
        pooled, HOLD_OUT, parameters=extra, tau=tau, refresh=refresh, seasons=fits
    )
    return payload, sha, pooled


def describe(payload: dict[str, Any]) -> str:
    """The fit in words and counts: no fitted figure (they stay under ``data/``)."""
    seasons = ", ".join(str(s) for s in payload["seasons"])
    separate = ", ".join(payload["separate"]) or "none"
    players = payload["dispersion"]["fitted_players"]
    text = (
        f"seasons pooled: {seasons}; kept apart: {separate}; hold-out: {payload['hold_out']}; "
        f"players with a dispersion of their own: {players}; "
        f"games in the dispersion fit: {payload['dispersion']['games']}; "
        f"player-seasons in the hazard fit: {payload['hazard']['players']}"
    )
    if payload.get("tau"):
        text += f"; tau: {len(payload['tau'])} stats ({payload['parameters'].get('tau_source', 'residual')})"
    refresh = payload.get("refresh")
    if refresh:
        text += f"; refresh: {'fitted' if refresh['fitted'] else 'defaults'} over {refresh['pairs']} pairs"
    return text


def residual_inputs(
    data: Path, league: str, season: int = THIS_SEASON
) -> tuple[
    list[tuple[date, dict[str, dict[str, float]]]], dict[str, dict[str, float]], dict[str, int]
]:
    """The exports as per-game rates by ESPN id, oldest first, and the season's realized rates
    and games by ESPN id: the refresh fit's and the residual tau's input."""
    from ..api.season_week import season_players
    from .engine import Season

    base, _ = season_api.base_settings(data, league)
    parts = season_api.load_parts(data, league)
    if not parts:
        raise reader.SimReadError(f"league {league}: no season state recorded")
    players = season_players(Season.from_parts(base, parts))
    ids = reader.espn_ids(data)
    exports = [(d, reader.by_espn(r, ids)) for d, r in reader.bbm_exports(data, players)]
    realized, games = reader.realized_by_espn(data, season)
    return exports, realized, games


def cmd_fit(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    tau = None
    refresh = None
    parameters: dict[str, Any] = {}
    try:
        if args.tau == "residual" or args.refresh:
            if not args.league:
                print("refused: --tau residual and --refresh need --league for the player set")
                return 2
            exports, realized, games = residual_inputs(args.data, args.league)
            if not exports:
                print("refused: no rest-of-season export on disk")
                return 2
            if args.tau == "residual":
                seasons0 = parse_seasons(args.seasons)
                lines = load_lines(seasons0, args.data)
                phi = (
                    fitmod.pool(
                        [fitmod.fit_season(r, s) for s, r in sorted(lines.items())]
                    ).dispersion.pooled
                    if lines
                    else {}
                )
                tau = fitmod.tau_from_residuals(
                    exports[0][1], realized, games, phi=phi or fitmod.PHI
                )
                parameters |= {
                    "tau_source": "residual",
                    "tau_export": exports[0][0].isoformat(),
                    "tau_players": len(games),
                }
            if args.refresh:
                refresh = fitmod.refresh_rate(exports, realized)
                parameters |= {"refresh_exports": [d.isoformat() for d, _ in exports]}
        payload, sha, _ = run_fit(
            parse_seasons(args.seasons), args.data, args.hold_out, tau, refresh, parameters
        )
    except (fitmod.HoldOutError, FileNotFoundError, reader.SimReadError) as e:
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


# --------------------------------------------------------------------------- the runs' common ground
def today_of(args: argparse.Namespace) -> date:
    if getattr(args, "today", None):
        return date.fromisoformat(args.today)
    return season_api.nba_today(datetime.now(UTC))


def read_specs(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text()) for p in paths]


def league_ids(text: str, data: Path) -> list[str]:
    return all_leagues(data) if text == "all" else [x.strip() for x in text.split(",") if x.strip()]


def world_inputs(
    data: Path, leagues: Sequence[str], need_tau: bool = True
) -> tuple[rn.WorldInputs, dict[str, Any], str, Path, dict[str, Any]]:
    """The frozen fit's inputs; tau from the fit, else the systems' spread over the first
    league's players (named in the payload); a replay, whose truth is the recorded lines, needs
    none and says so."""
    payload, sha, path = reader.newest_fit(data)
    tau_note: dict[str, Any] = {"source": "fit"}
    tau = None
    if not need_tau and not payload.get("tau"):
        tau = dict.fromkeys(wk.STATS, 0.0)
        tau_note = {"source": "not used: the replay's truth is the recorded lines"}
    elif not payload.get("tau"):
        tau = reader.systems_tau(data, leagues[0]) if leagues else {}
        tau_note = {
            "source": "systems",
            "systems": list(reader.GAP_SYSTEMS),
            "league": leagues[0] if leagues else None,
            "stats": len(tau),
            "floor": f"top {reader.TAU_POOL} by value",
        }
    if tau is not None and not tau:
        raise reader.SimReadError(
            "no tau: the fit has no residual tau and the first league has no Yahoo view on file "
            "to read the systems' spread from"
        )
    inputs = rn.inputs_of(payload, sha, tau)
    return inputs, payload, sha, path, tau_note


def base_payload(
    kind: str,
    name: str,
    started: datetime,
    sha: str,
    fit_path: Path,
    fit: Mapping[str, Any],
    workers: int,
    tau_note: Mapping[str, Any],
    inputs: rn.WorldInputs,
    arms: Mapping[str, rn.Arm] | None = None,
) -> dict[str, Any]:
    """The payload's common part. ``arms`` by their key in the payload (``a`` and ``b`` in a
    comparison, the names in a replay or a room): each arm's fields and its surrogate's pool and
    days; none (validate) for the live route's, the surrogate gate's."""
    fields = {k: arm.fields for k, arm in (arms or {}).items()} or {"gate": policy.Fields()}
    return {
        "kind": kind,
        "name": name,
        "started_at": started.isoformat(),
        "host": platform.node(),
        "workers": workers,
        "nice": NICE,
        "code_sha": reader.code_sha(ROOT),
        "fit_sha": sha,
        "fit_file": str(fit_path),
        "hold_out": fit.get("hold_out", HOLD_OUT),
        "executions": EXECUTIONS,
        "gap": {
            "systems": list(reader.GAP_SYSTEMS),
            "clip": reader.GAP_CLIP,
            "sign": "log(first) - log(second)",
        },
        "refresh": inputs.refresh_from,
        "tau": dict(tau_note),
        "fields": {k: f.payload() for k, f in fields.items()},
        "surrogate": {
            k: {"pool": f.pool, "days": list(f.surrogate_days), "plan": "daily"}
            for k, f in fields.items()
        },
        "period_calendar": {
            "source": reader.PERIOD_SOURCE,
            "period_one": {str(k): v.isoformat() for k, v in reader.PERIOD_ONE.items()},
        },
    }


def finish(payload: dict[str, Any], data: Path, dry_run: bool) -> Path | None:
    payload["finished_at"] = datetime.now(UTC).isoformat()
    if dry_run:
        return None
    return reader.write_run(data, payload)


def arms_of(specs: Sequence[Mapping[str, Any]], sha: str) -> list[rn.Arm]:
    out = []
    for spec in specs:
        rn.check_fit(spec, sha)
        out.append(rn.arm_of(spec))
    return out


def estimate_hours(seconds_one: float, tasks: int, workers: int) -> float:
    return seconds_one * tasks / max(1, workers) / 3600.0


def setups_of(
    data: Path, leagues: Sequence[str], today: date, system: str
) -> tuple[dict[str, Any], dict[str, str]]:
    setups: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    for league in leagues:
        try:
            setups[league] = reader.setup_of(data, league, today, system)
        except (reader.SimReadError, FileNotFoundError, KeyError, ValueError) as e:
            skipped[league] = str(e)
    return setups, skipped


def league_note(setup: Any) -> dict[str, Any]:
    return {
        "shape": policy.shape_of(setup).label(),
        "teams": len(setup.teams),
        "players": len(setup.players),
        "pool": len(setup.pool),
        "weeks": len(setup.calendar.weeks),
        "bracket": "read" if setup.spec is not None else setup.bracket_unread,
        "assumed_pairings": list(setup.assumed_pairings),
        "market_rate": round(setup.market_rate, 4),
    }


# --------------------------------------------------------------------------- the audit and the counts
#: A run whose audit found a breach exits with this, after writing its payload.
AUDIT_EXIT = 3
#: What each mechanism count is, for the payload.
COUNTS_NOTE = {
    "landed": "adds landed: a move's add on the roster the morning after (a swap's drop gone)",
    "gone": "moves lost: the add (or the drop) was gone, or no active spot was open",
    "adds_per_week": "adds charged to a week, its mean over the weeks played",
    "weeks_at_cap": "the share of weeks whose adds reached the league's cap",
    "forced_drops": "active players dropped when a held player came back over the spots",
    "held_refused": "held-slot moves refused: the slot no longer accepted the player that morning",
    "held_stints": "players placed in (or starting the run in) a held slot",
    "held_days": "days spent in a held slot",
    "starter_games": "games the day's starters played",
    "pooling": "a seat's season, the mean over the arm's seats a path, then over paths",
}


def audited(
    keys: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]]
) -> tuple[list[bool], dict[str, Any]]:
    """Which tasks stand and the payload's audit block. A task with a breach is a voided path: it
    is left out of every aggregate, and each breach is listed with the task it voids."""
    keep = [not r.get("breaches") for r in results]
    return keep, {
        "rules": audit.names(),
        "breaches": [
            {**key, **b}
            for key, r in zip(keys, results, strict=True)
            for b in r.get("breaches", ())
        ],
        "paths_voided": keep.count(False),
        "voided": [dict(key) for key, k in zip(keys, keep, strict=True) if not k],
    }


def audit_exit(note: Mapping[str, Any]) -> int:
    """The exit code after writing: :data:`AUDIT_EXIT` when the audit voided a path."""
    if not note["paths_voided"]:
        return 0
    print(
        f"AUDIT: {len(note['breaches'])} breach(es) voided {note['paths_voided']} path(s); "
        "they are listed in the payload and left out of its figures"
    )
    for b in note["breaches"][:10]:
        print(f"  {b['rule']} on {b['day']}, seat {b['seat']}: {b['found']}")
    return AUDIT_EXIT


def dry_run(key: Mapping[str, Any], first: Mapping[str, Any]) -> int:
    """A dry run's one task: its counts and season scale by arm and its audit printed, nothing
    written. A breach in it exits with :data:`AUDIT_EXIT` all the same: a dry run is a run the
    audit reads too."""
    for arm, row in (first.get("counts") or {}).items():
        if row:
            shown = ", ".join(f"{m} {row[m]:.4g}" for m in ct.METRICS if row.get(m) is not None)
            print(f"counts, {arm}, the first task: {shown}")
    for arm, row in (first.get("scale") or {}).items():
        if row:
            shown = ", ".join(
                f"{m} {row[m]:.4g}" for m in ("gain", "ros", "ratio") if row.get(m) is not None
            )
            print(f"season scale, {arm}, the first task: {shown} over {row['swaps']} swaps")
    _, note = audited([key], [first])
    print("dry run, nothing written")
    return audit_exit(note)


def verdict_of(by_shrink: Mapping[str, Any], note: Mapping[str, Any]) -> dict[str, Any]:
    """The advisory verdict over the paths that stand; none at all when the audit voided a path,
    since the paths left may not be the ones a clean run would have kept."""
    v = rn.verdict(by_shrink)
    if note["paths_voided"]:
        v = {
            **v,
            "passes": None,
            "why": f"no verdict: the audit voided {note['paths_voided']} path(s)",
        }
    return v


def counts_of(rows: Sequence[Any]) -> dict[str, Any] | None:
    """The counts of the paths that stand, pooled like the outcomes; None without a row."""
    have = [r for r in rows if r is not None]
    return rn.aggregate(have, ct.METRICS) if have else None


# --------------------------------------------------------------------------- the knobs (PR C)
#: What the payload's season scale is.
SCALE_NOTE = (
    "per arm: on the first simulated day of each path, for the arm's own seat (a replay's or a "
    "room's: its first seat in team order), over the arm's pool, each candidate's best single "
    "swap on the key the arm executes, without the season term; gain is the median of their "
    "gains (expected category wins), ros the median of their ROS_w (season value above a dead "
    "spot times the games left, a bracket game counted playoff_weight times), ratio gain over "
    "ros; each the mean over the paths that stand. A season_weight equal to ratio makes the "
    "term about as loud as the odds gain. Null on the ranking tier and a static seat."
)


def scale_of(rows: Sequence[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    """The season scale of the paths that stand: the mean of each figure over the paths that
    have it, and the paths; None when no path has one (the ranking tier, a static seat)."""
    have = [r for r in rows if r is not None]
    if not have:
        return None

    def mean(k: str) -> float | None:
        vals = [float(r[k]) for r in have if r.get(k) is not None]
        return sum(vals) / len(vals) if vals else None

    return {"gain": mean("gain"), "ros": mean("ros"), "ratio": mean("ratio"), "paths": len(have)}


def reads_of(
    arms: Mapping[str, rn.Arm], shapes: Sequence[policy.Shape], rivals: bool
) -> dict[str, Any]:
    """The reads table by arm and by each shape of the run: each knob and field ``read`` or the
    reason it is not (``policy.reads``, ``policy.field_reads``)."""
    out: dict[str, Any] = {}
    for key, arm in arms.items():
        mirror = rivals and rn.mirrored(arm)
        out[key] = {
            shape.label(): {
                "knobs": policy.reads(arm, shape, mirror),
                "fields": policy.field_reads(arm, mirror),
            }
            for shape in sorted(set(shapes), key=lambda s: s.label())
        }
    return out


def same_seats(
    arms: Mapping[str, rn.Arm], shapes: Sequence[policy.Shape], rivals: bool
) -> str | None:
    """Why the run is refused when two of ``arms`` are the same seat (``run.same_seat``), naming
    each knob or field they differ in, why it is not read and what would make it read; None
    when no two are."""
    named = list(arms.items())
    for i, (ka, a) in enumerate(named):
        for kb, b in named[i + 1 :]:
            same = rn.same_seat(a, b, shapes, rivals)
            if same:
                return (
                    f"arms {ka} and {kb} are the same seat: they differ only in {'; '.join(same)}"
                )
    return None


# --------------------------------------------------------------------------- compare
def task_compare(
    setup: Any,
    inputs: rn.WorldInputs,
    seed: int,
    path: int,
    s: float,
    a: rn.Arm,
    b: rn.Arm,
    me: int,
) -> dict[str, Any]:
    w = rn.forward_world(setup, inputs, seed, path, s)
    return rn.paired(setup, w, a, b, me)


def cmd_compare(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    started = datetime.now(UTC)
    today = today_of(args)
    leagues = league_ids(args.leagues, args.data)
    try:
        inputs, fit, sha, fit_path, tau_note = world_inputs(args.data, leagues)
        specs = read_specs([args.a, args.b])
        a, b = arms_of(specs, sha)
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    setups, skipped = setups_of(args.data, leagues, today, args.system)
    seats: dict[str, int] = {}
    for league, setup in list(setups.items()):
        me = reader.settings_of(args.data, league).my_team_id
        if me is None or me not in setup.teams:
            skipped[league] = "no team of mine in the recorded state"
            del setups[league]
        else:
            seats[league] = me
    if not setups:
        print(f"refused: no league to run ({skipped})")
        return 2
    shapes = [policy.shape_of(s_) for s_ in setups.values()]
    same = same_seats({a.name: a, b.name: b}, shapes, rivals=True)
    if same:
        print(f"refused: {same}")
        return 2
    shrinks = [float(x) for x in args.shrink.split(",")] if args.shrink else list(rn.SHRINKS)
    workers = args.workers or rn.workers_default()
    tasks = [
        (setups[league], inputs, args.seed, p, s, a, b, seats[league])
        for league in setups
        for s in shrinks
        for p in range(args.paths)
    ]
    t0 = clock.perf_counter()
    first = task_compare(*tasks[0])
    one = clock.perf_counter() - t0
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else estimate_hours(one, len(tasks), workers)
    )
    print(
        f"{len(tasks)} tasks ({len(setups)} leagues x {len(shrinks)} shrinks x {args.paths} paths), one took {one:.1f}s, about {hours:.2f} h on {workers} workers"
    )
    if args.dry_run:
        return dry_run(
            {"league": tasks[0][0].league, "shrink": tasks[0][4], "path": tasks[0][3]}, first
        )
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    results = [first, *rn.run_tasks(task_compare, tasks[1:], workers)]
    keep, note = audited(
        [{"league": t[0].league, "shrink": t[4], "path": t[3]} for t in tasks], results
    )
    tasks = [t for t, k in zip(tasks, keep, strict=True) if k]
    results = [r for r, k in zip(results, keep, strict=True) if k]
    rows_by_shrink: dict[str, list[dict[str, Any]]] = {}
    arms_by_shrink: dict[str, dict[str, list[dict[str, Any]]]] = {}
    by_league: dict[str, dict[str, list[dict[str, Any]]]] = {}
    counts_by_shrink: dict[str, dict[str, list[Any]]] = {}
    scales: dict[str, list[Any]] = {"a": [], "b": []}
    for task, r in zip(tasks, results, strict=True):
        league, s = task[0].league, str(task[4])
        for side in ("a", "b"):
            scales[side].append(r["scale"][side])
        for side in ("a", "b", "rivals"):
            counts_by_shrink.setdefault(s, {}).setdefault(side, []).append(r["counts"][side])
        rows_by_shrink.setdefault(s, []).append(r["delta"])
        arms_by_shrink.setdefault(s, {}).setdefault("a", []).append(r["a"])
        arms_by_shrink[s].setdefault("b", []).append(r["b"])
        by_league.setdefault(league, {}).setdefault(s, []).append(r["delta"])
    by_shrink = {s: rn.aggregate(rows) for s, rows in rows_by_shrink.items()}
    payload = base_payload(
        "compare",
        args.name or f"{a.name}-vs-{b.name}",
        started,
        sha,
        fit_path,
        fit,
        workers,
        tau_note,
        inputs,
        {"a": a, "b": b},
    )
    payload |= {
        "specs": {"a": specs[0], "b": specs[1]},
        "arms": {"a": a.name, "b": b.name},
        "leagues": {league: league_note(s_) for league, s_ in setups.items()},
        "seats": seats,
        "skipped": skipped,
        "paths": args.paths,
        "shrinks": shrinks,
        "seed": args.seed,
        "today": today.isoformat(),
        "system": args.system,
        "seconds_first_task": one,
        "results": {
            "difference": "b less a",
            "by_shrink": by_shrink,
            "arms_by_shrink": {
                s: {k: rn.aggregate(v) for k, v in d.items()} for s, d in arms_by_shrink.items()
            },
            "by_league": {
                league: {s: rn.aggregate(rows) for s, rows in d.items()}
                for league, d in by_league.items()
            },
            "solves": sum(r["solves"] for r in results),
            "shared": sum(r["shared"] for r in results),
            "executed": [
                sum(r["executed"][0] for r in results),
                sum(r["executed"][1] for r in results),
            ],
            "gone": [sum(r["gone"][0] for r in results), sum(r["gone"][1] for r in results)],
        },
        "verdict": verdict_of(by_shrink, note),
        "reads": reads_of({"a": a, "b": b}, shapes, rivals=True),
        "season_scale": {
            "note": SCALE_NOTE,
            "by_arm": {side: scale_of(rows) for side, rows in scales.items()},
        },
        "counts": {
            "note": COUNTS_NOTE,
            "rivals": "the seats other than mine, both arms' seasons, as one row",
            "by_shrink": {
                s: {side: counts_of(rows) for side, rows in d.items()}
                for s, d in counts_by_shrink.items()
            },
        },
        "audit": note,
    }
    path = finish(payload, args.data, False)
    for s, agg in by_shrink.items():
        d = agg["made_playoffs"]
        mean = "n/a" if d["mean"] is None else f"{100 * d['mean']:+.1f} pp"
        se = "n/a" if d["se"] is None else f"{100 * d['se']:.1f} pp"
        print(f"shrink {s}: playoff odds, B less A, {mean} (SE {se}) over {d['n']} paths")
    v = payload["verdict"]
    print(
        f"verdict ({v['rule']}, advisory): {'passes' if v['passes'] else 'does not pass' if v['passes'] is False else 'no verdict'}"
    )
    print(f"written: {path}")
    return audit_exit(note)


# --------------------------------------------------------------------------- replay
def parse_standin(text: str) -> list[tuple[str, float]]:
    """``prior`` or ``oracle:0.1,0.2,0.3``."""
    if text == "prior":
        return [("prior", 0.0)]
    if text.startswith("oracle:"):
        return [("oracle", float(x)) for x in text[len("oracle:") :].split(",") if x.strip()]
    raise ValueError(f"stand-in {text!r}: prior or oracle:<spread,...>")


def replay_setup_of(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    standin: tuple[str, float],
    prior: Any,
    seed: int,
    path: int,
) -> Any:
    """A replay's league in one path: drafted on the stand-in (the prior season's rates, or the
    replayed season's noised, per path)."""
    kind, spread = standin
    projection = prior if kind == "prior" else rn.oracle_standin(lines, spread, seed, path)
    return rn.replay_setup(season, lines, members, projection, reader.PERIOD_ONE[season], scheduled)


def task_replay(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    standin: tuple[str, float],
    prior: Any,
    lag: int,
    weights: Mapping[str, float],
    news_sd: float,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    seed: int,
    path: int,
) -> dict[str, Any]:
    setup = replay_setup_of(season, lines, members, scheduled, standin, prior, seed, path)
    w = rn.replay_world(setup, lines, lag, seed, path, weights, news_sd=news_sd)
    out = rn.room(setup, w, arms, seats, path)
    out["standin"] = {"kind": standin[0], "spread": standin[1]}
    return out


#: The replay's version in its payload: 2 since its seats believe only the games played
#: (#172, PR B1); a version 1 replay's figures came from seats that saw each season's rates.
REPLAY_VERSION = 2
BELIEF_RULE = (
    "per stat, (w * the forecaster's figure + the sum of his lines dated before the day) / "
    "(w + his games before the day), read every day"
)
NEWCOMER_RULE = (
    "a player nobody projected enters the belief the day after his first recorded game, from "
    "the mean projection over the projected players left undrafted"
)


def replay_notes(weights: fitmod.BeliefWeights, news_sd: float) -> dict[str, Any]:
    """What a replay's seats knew, for its payload."""
    return {
        "replay_version": REPLAY_VERSION,
        "belief": {
            "kind": "causal",
            "rule": BELIEF_RULE,
            "weights": weights.payload(),
            "weights_fitted_with": "the prior season's rates (the prior forecaster)",
            "oracle": "an oracle stand-in uses the prior forecaster's weights",
        },
        "newcomer": NEWCOMER_RULE,
        "pool": {
            "league": "everyone the season's log lists with a scheduled game",
            "draft": (
                f"the projected players with a scheduled game in the season's first "
                f"{rn.OPENING_DAYS} days"
            ),
            "projected": f"a stand-in projects the players with {rn.STANDIN_MIN_GAMES} games",
        },
        "news_sd_days": news_sd,
        "refresh": "not used: a replay's seats believe the games played, not a weekly refresh",
    }


def no_peek(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    standin: tuple[str, float],
    prior: Any,
    lag: int,
    weights: Mapping[str, float],
    news_sd: float,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    seed: int,
    day: date,
) -> tuple[Any, int, list[dict[str, Any]]]:
    """Path 0 of the replay on the recorded lines and on :func:`nopeek.perturb`'s, with one
    league built before either: the first difference between their day records (None when
    they never part), the records compared and the audit's breaches in either run."""
    setup = replay_setup_of(season, lines, members, scheduled, standin, prior, seed, 0)
    if day not in setup.days:
        raise ValueError(f"{day} is not a day of the replayed season")
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, seed)
    digests: list[dict[tuple[date, int], dict[str, str]]] = []
    breaches: list[dict[str, Any]] = []
    for run_, these in (("recorded", lines), ("changed", other)):
        got: dict[tuple[date, int], dict[str, str]] = {}

        def keep(r: rn.DayRecord, got: dict[tuple[date, int], dict[str, str]] = got) -> None:
            got[(r.day, r.variant)] = nopeek.digest(r)

        w = rn.replay_world(setup, these, lag, seed, 0, weights, news_sd=news_sd)
        out = rn.room(setup, w, arms, seats, 0, on_day=keep)
        breaches += [{"run": run_, **b} for b in out["breaches"]]
        digests.append(got)
    return nopeek.first_difference(digests[0], digests[1]), len(digests[0]), breaches


#: The span the guard gives ``replay --no-peek``: two paths of a real season take about three
#: minutes; a quarter of an hour leaves room.
NO_PEEK_HOURS = 0.25


def cmd_replay(args: argparse.Namespace) -> int:
    ok, why = guard(NO_PEEK_HOURS if args.no_peek else 0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    if args.season == HOLD_OUT:
        print(f"refused: {HOLD_OUT} is the hold-out; it is scored by validate only")
        return 2
    if args.news_sd < 0:
        print("refused: --news-sd is a spread in days, not below zero")
        return 2
    started = datetime.now(UTC)
    try:
        day = date.fromisoformat(args.no_peek) if args.no_peek else None
        inputs, fit, sha, fit_path, tau_note = world_inputs(args.data, [], need_tau=False)
        specs = read_specs(args.seats)
        arms = {arm.name: arm for arm in arms_of(specs, sha)}
        standins = parse_standin(args.standin)
        lines, members, scheduled = reader.replay_lines(args.data, args.season)
        prior = (
            reader.prior_rates(args.data, args.season)
            if any(k == "prior" for k, _ in standins)
            else {}
        )
        fitted = reader.belief_weights(args.data, args.season, HOLD_OUT)
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    if len(arms) < 2:
        print("refused: a replay seats at least two arms")
        return 2
    seats = list(arms)
    try:
        shape = policy.shape_of(
            replay_setup_of(
                args.season, lines, members, scheduled, standins[0], prior, args.seed, 0
            )
        )
    except ValueError as e:
        print(f"refused: {e}")
        return 2
    same = same_seats(arms, [shape], rivals=False)
    if same:
        print(f"refused: {same}")
        return 2
    weights = dict(fitted.weights)
    shown = ", ".join(f"{s} {weights[s]:g}" for s in wk.STATS if s in weights)
    source = (
        "the default" if fitted.default else "seasons " + ", ".join(str(t) for t in fitted.seasons)
    )
    print(f"belief weights ({source}): {shown}")
    if day is not None:
        t0 = clock.perf_counter()
        try:
            first, n, breaches = no_peek(
                args.season,
                lines,
                members,
                scheduled,
                standins[0],
                prior,
                inputs.lag,
                weights,
                args.news_sd,
                arms,
                seats,
                args.seed,
                day,
            )
        except ValueError as e:
            print(f"refused: {e}")
            return 2
        took = clock.perf_counter() - t0
        print(f"no-peek check on {day}: {n} day records a run, {took:.1f}s, nothing written")
        for b in breaches:
            print(
                f"AUDIT ({b['run']} season): {b['rule']} on {b['day']}, seat {b['seat']}: {b['found']}"
            )
        if breaches:
            print(f"AUDIT: {len(breaches)} breach(es); the check does not stand")
            return AUDIT_EXIT
        if first is not None and first[0] <= day:
            print(
                f"FAILED: the records part on {first[0]} (variant {first[1]}, "
                f"{', '.join(first[2])}), at or before {day}"
            )
            return 1
        if first is None:
            print(f"agree through {day}; the runs never part (the change after it reached no seat)")
        else:
            print(f"agree through {day}; first difference on {first[0]} ({', '.join(first[2])})")
        return 0
    workers = args.workers or rn.workers_default()
    tasks = [
        (
            args.season,
            lines,
            members,
            scheduled,
            standin,
            prior,
            inputs.lag,
            weights,
            args.news_sd,
            arms,
            seats,
            args.seed,
            p,
        )
        for standin in standins
        for p in range(args.paths)
    ]
    t0 = clock.perf_counter()
    first_run = task_replay(*tasks[0])
    one = clock.perf_counter() - t0
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else estimate_hours(one, len(tasks), workers)
    )
    print(
        f"{len(tasks)} tasks ({len(standins)} stand-ins x {args.paths} paths), one took {one:.1f}s, about {hours:.2f} h on {workers} workers"
    )
    if args.dry_run:
        return dry_run(
            {"standin": f"{tasks[0][4][0]}:{tasks[0][4][1]:g}", "path": tasks[0][12]}, first_run
        )
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    results = [first_run, *rn.run_tasks(task_replay, tasks[1:], workers)]
    keep, note = audited(
        [{"standin": f"{t[4][0]}:{t[4][1]:g}", "path": t[12]} for t in tasks], results
    )
    tasks = [t for t, k in zip(tasks, keep, strict=True) if k]
    results = [r for r, k in zip(results, keep, strict=True) if k]
    by_standin: dict[str, dict[str, list[dict[str, Any]]]] = {}
    counts_by_standin: dict[str, dict[str, list[Any]]] = {}
    scales: dict[str, list[Any]] = {arm: [] for arm in seats}
    for task, r in zip(tasks, results, strict=True):
        key = f"{task[4][0]}:{task[4][1]:g}"
        for arm, row in r["scale"].items():
            scales[arm].append(row)
        for arm, metrics in r["by_arm"].items():
            by_standin.setdefault(key, {}).setdefault(arm, []).append(metrics)
        for arm, row in r["counts"].items():
            counts_by_standin.setdefault(key, {}).setdefault(arm, []).append(row)
    payload = base_payload(
        "replay",
        args.name or f"replay-{args.season}",
        started,
        sha,
        fit_path,
        fit,
        workers,
        tau_note,
        inputs,
        arms,
    )
    payload |= replay_notes(fitted, args.news_sd)
    payload |= {
        "season": args.season,
        "specs": {arm: spec for arm, spec in zip(seats, specs, strict=True)},
        "seats": seats,
        "rotation": "seat i takes arm (i + path) mod n",
        "draft": f"snake on the stand-in projection, over {payload['pool']['draft']}",
        "standins": [{"kind": k, "spread": s} for k, s in standins],
        "players": sum(1 for k in members if scheduled.get(k) or lines.get(k)),
        "paths": args.paths,
        "seed": args.seed,
        "results": {
            key: {arm: rn.aggregate(rows) for arm, rows in d.items()}
            for key, d in by_standin.items()
        },
        "solves": sum(r["solves"] for r in results),
        "shape": shape.label(),
        "reads": reads_of(arms, [shape], rivals=False),
        "season_scale": {
            "note": SCALE_NOTE,
            "by_arm": {arm: scale_of(rows) for arm, rows in scales.items()},
        },
        "counts": {
            "note": COUNTS_NOTE,
            "rivals": None,
            "by_standin": {
                key: {arm: counts_of(rows) for arm, rows in d.items()}
                for key, d in counts_by_standin.items()
            },
        },
        "audit": note,
    }
    path = finish(payload, args.data, False)
    for key, d in payload["results"].items():
        for arm, agg in d.items():
            m = agg["made_playoffs"]
            print(
                f"{key} {arm}: playoff odds {m['mean']:.3f} (SE {m['se'] if m['se'] is None else round(m['se'], 3)}) over {m['n']} paths"
            )
    print(f"written: {path}")
    return audit_exit(note)


# --------------------------------------------------------------------------- room
def task_room(
    setup: Any,
    inputs: rn.WorldInputs,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    seed: int,
    path: int,
    s: float,
) -> dict[str, Any]:
    w = rn.forward_world(setup, inputs, seed, path, s)
    return rn.room(setup, w, arms, seats, path)


def snake_setup(setup: Any) -> Any:
    """The league redrafted: every player on a roster or in the pool, in a snake on the shared
    projection's value, everyone on the bench."""
    from dataclasses import replace

    keys = [k for k in setup.players if k in setup.projection]
    value = wk.per_game_values({k: setup.projection[k] for k in keys}, setup.cats, setup.points)
    rosters = snake_draft(keys, value, setup.teams, setup.spots())
    taken = {k for r in rosters.values() for k, _ in r}
    return replace(
        setup, rosters=rosters, pool=tuple(k for k in keys if k not in taken), adds_used={}
    )


def cmd_room(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    started = datetime.now(UTC)
    today = today_of(args)
    leagues = league_ids(args.leagues, args.data)
    try:
        inputs, fit, sha, fit_path, tau_note = world_inputs(args.data, leagues)
        specs = read_specs(args.seats)
        arms = {arm.name: arm for arm in arms_of(specs, sha)}
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    seats = list(arms)
    setups, skipped = setups_of(args.data, leagues, today, args.system)
    if args.draft == "snake":
        setups = {league: snake_setup(s_) for league, s_ in setups.items()}
    if not setups:
        print(f"refused: no league to run ({skipped})")
        return 2
    shapes = [policy.shape_of(s_) for s_ in setups.values()]
    same = same_seats(arms, shapes, rivals=False)
    if same:
        print(f"refused: {same}")
        return 2
    workers = args.workers or rn.workers_default()
    s = args.shrink
    tasks = [
        (setups[league], inputs, arms, seats, args.seed, p, s)
        for league in setups
        for p in range(args.paths)
    ]
    t0 = clock.perf_counter()
    first = task_room(*tasks[0])
    one = clock.perf_counter() - t0
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else estimate_hours(one, len(tasks), workers)
    )
    print(
        f"{len(tasks)} tasks ({len(setups)} leagues x {args.paths} paths), one took {one:.1f}s, about {hours:.2f} h on {workers} workers"
    )
    if args.dry_run:
        return dry_run({"league": tasks[0][0].league, "path": tasks[0][5]}, first)
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    results = [first, *rn.run_tasks(task_room, tasks[1:], workers)]
    keep, note = audited([{"league": t[0].league, "path": t[5]} for t in tasks], results)
    tasks = [t for t, k in zip(tasks, keep, strict=True) if k]
    results = [r for r, k in zip(results, keep, strict=True) if k]
    by_arm: dict[str, list[dict[str, Any]]] = {}
    by_league: dict[str, dict[str, list[dict[str, Any]]]] = {}
    counts_by_arm: dict[str, list[Any]] = {}
    scales: dict[str, list[Any]] = {arm: [] for arm in seats}
    for task, r in zip(tasks, results, strict=True):
        for arm, row in r["scale"].items():
            scales[arm].append(row)
        for arm, metrics in r["by_arm"].items():
            by_arm.setdefault(arm, []).append(metrics)
            by_league.setdefault(task[0].league, {}).setdefault(arm, []).append(metrics)
        for arm, row in r["counts"].items():
            counts_by_arm.setdefault(arm, []).append(row)
    payload = base_payload(
        "room", args.name or "room", started, sha, fit_path, fit, workers, tau_note, inputs, arms
    )
    payload |= {
        "specs": {arm: spec for arm, spec in zip(seats, specs, strict=True)},
        "seats": seats,
        "rotation": "seat i takes arm (i + path) mod n",
        "draft": args.draft,
        "leagues": {league: league_note(s_) for league, s_ in setups.items()},
        "skipped": skipped,
        "paths": args.paths,
        "shrink": s,
        "seed": args.seed,
        "today": today.isoformat(),
        "system": args.system,
        "results": {
            "by_arm": {arm: rn.aggregate(rows) for arm, rows in by_arm.items()},
            "by_league": {
                league: {arm: rn.aggregate(rows) for arm, rows in d.items()}
                for league, d in by_league.items()
            },
            "solves": sum(r["solves"] for r in results),
        },
        "reads": reads_of(arms, shapes, rivals=False),
        "season_scale": {
            "note": SCALE_NOTE,
            "by_arm": {arm: scale_of(rows) for arm, rows in scales.items()},
        },
        "counts": {
            "note": COUNTS_NOTE,
            "rivals": None,
            "by_arm": {arm: counts_of(rows) for arm, rows in counts_by_arm.items()},
        },
        "audit": note,
    }
    path = finish(payload, args.data, False)
    for arm, agg in payload["results"]["by_arm"].items():
        m = agg["made_playoffs"]
        odds = m["mean"] if m["mean"] is None else round(m["mean"], 3)
        print(f"{arm}: playoff odds {odds} over {m['n']} paths, its seats pooled")
    print(f"written: {path}")
    return audit_exit(note)


# --------------------------------------------------------------------------- validate
def gate_dict(g: vg.Gate) -> dict[str, Any]:
    return {"name": g.name, "passed": g.passed, "season": g.season, "detail": g.detail}


def not_run(name: str, season: Any, reason: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": None,
        "season": season,
        "detail": {"reason": reason, "run": False},
    }


def gate_absences(
    data: Path, season: int, inputs: rn.WorldInputs, seed: int, paths: int = GATE_PATHS
) -> dict[str, Any]:
    """Gate 4 on a cached season: player-games missed a player-week against the hazard."""
    try:
        lines, _, scheduled = reader.replay_lines(data, season)
    except reader.SimReadError as e:
        return not_run("absences", season, str(e))
    kept = {k: v for k, v in scheduled.items() if len(lines.get(k, {})) >= rn.GATE_MIN_GAMES}
    first = reader.PERIOD_ONE[season]
    last = max((d for days in kept.values() for d in days), default=first)
    weeks = [(w.start, w.end) for w in weeks_from(first, (last - first).days // 7 + 1).weeks]
    by_player = reader.missed_games(lines, kept, weeks)
    if not by_player:
        return not_run("absences", season, "no player-week with a scheduled game")
    players = sorted(by_player)
    missed = [m for k in players for m, _ in by_player[k]]
    sizes = [[n for _, n in by_player[k]] for k in players]
    samples = checks.missed_samples(inputs.hazard, sizes, paths, seed)
    g = vg.absence_gate(missed, samples, season=season, seed=seed)
    g.detail.update({"player_weeks": len(missed), "players": len(players), "paths": paths})
    return gate_dict(g)


def hold_out_setup(
    season: int, lines: Any, members: Any, scheduled: Any
) -> tuple[Any, dict[int, Any]]:
    """Gate 1's league: the players with :data:`run.GATE_MIN_GAMES` played games, every one of
    them projected at his own realized rates and drafted (no opening-week rule), and their
    lines. The gate's figures predate the replay's preseason pool and stay as they were."""
    kept = {k: v for k, v in lines.items() if len(v) >= rn.GATE_MIN_GAMES}
    truth = rn.realized_rates(kept)
    setup = rn.replay_setup(
        season,
        kept,
        {k: members[k] for k in kept if k in members},
        truth,
        reader.PERIOD_ONE[season],
        {k: v for k, v in scheduled.items() if k in kept},
        opening_days=None,
    )
    return setup, kept


def gate_hold_out_team_weeks(
    data: Path, season: int, inputs: rn.WorldInputs, seed: int, paths: int = GATE_PATHS // 2
) -> dict[str, Any]:
    """Gate 1 on the hold-out: made-up teams' realized weekly totals (their players' recorded
    lines) as transforms under the simulator's team-week distribution centred on the players'
    own realized rates (the game-noise and absence layers alone)."""
    try:
        lines, members, scheduled = reader.replay_lines(data, season)
    except reader.SimReadError as e:
        return not_run("team_weeks", season, str(e))
    setup, lines = hold_out_setup(season, lines, members, scheduled)
    exact = rn.WorldInputs(
        inputs.phi,
        inputs.phi_players,
        inputs.sigma,
        inputs.hazard,
        dict.fromkeys(wk.STATS, 0.0),
        0.0,
        0.0,
        inputs.lag,
        inputs.sha,
        inputs.refresh_from,
    )
    worlds = [rn.forward_world(setup, exact, seed, p, 0.0) for p in range(paths)]
    real = rn.replay_world(setup, lines, inputs.lag, seed, 0, belief="fixed")
    value = wk.per_game_values(setup.projection, setup.cats, setup.points)
    pits: list[float] = []
    team_weeks = 0
    for week in setup.spec.regular_weeks if setup.spec else ():
        days = setup.calendar.week(week).days()
        for team in setup.teams:
            roster = setup.rosters[team]
            realized = checks.team_week(setup, real, roster, days, value)
            if not realized:
                continue
            samples = checks.team_week_samples(setup, lambda p: worlds[p], roster, days, paths)
            pits += checks.transforms(realized, samples)
            team_weeks += 1
    g = vg.bucket_gate(pits, season=season, name="team_weeks")
    g.detail.update(
        {
            "team_weeks": team_weeks,
            "paths": paths,
            "teams": "snake-drafted on the realized rates",
            "layers": "game noise and absences",
        }
    )
    return gate_dict(g)


def gate_recorded_weeks(
    data: Path,
    league: str,
    setup: Any,
    inputs: rn.WorldInputs,
    seed: int,
    paths: int = GATE_PATHS // 2,
) -> list[dict[str, Any]]:
    """Gates 1 and 2 on a league's recorded weeks, the current rosters standing in for the
    week's (named in the detail)."""
    records = reader.recorded_weeks(data, league)
    if not records:
        return [
            not_run("team_weeks", league, "no recorded week"),
            not_run("matchup_odds", league, "no recorded week"),
        ]
    worlds = [rn.forward_world(setup, inputs, seed, p, 0.0) for p in range(paths)]
    pits: list[float] = []
    sim_odds: list[float] = []
    eng_odds: list[float] = []
    outcomes: list[float] = []
    for record in records:
        week = setup.calendar.week(int(record["week"]))
        if week is None:
            continue
        days = week.days()
        totals = reader.team_week_totals(record)
        samples = {
            t: checks.team_week_samples(setup, lambda p: worlds[p], setup.rosters[t], days, paths)
            for t in totals
            if t in setup.rosters
        }
        for t, realized in totals.items():
            if t in samples:
                pits += checks.transforms(realized, samples[t])
        if setup.spec is None:
            continue
        for a, b, share in reader.matchup_outcomes(record):
            if share is None or a not in samples or b not in samples:
                continue
            sim_odds.append(checks.simulated_odds(samples[a], samples[b], setup.spec))
            eng_odds.append(
                checks.engine_odds(
                    setup, setup.projection, setup.rosters[a], setup.rosters[b], days
                )
            )
            outcomes.append(share)
    g1 = vg.bucket_gate(pits, season=league, name="team_weeks")
    g1.detail.update({"weeks": len(records), "paths": paths, "rosters": "current"})
    out = [gate_dict(g1)]
    if outcomes:
        g2 = vg.brier_gate(
            vg.brier(sim_odds, outcomes), vg.brier(eng_odds, outcomes), season=league
        )
        g2.detail.update(
            {"matchups": len(outcomes), "rosters": "current", "rates": "current projection"}
        )
        out.append(gate_dict(g2))
    else:
        out.append(not_run("matchup_odds", league, "no scored matchup in the records"))
    return out


def gate_surrogate(
    setup: Any, inputs: rn.WorldInputs, me: int, knobs: Mapping[str, Any], seed: int
) -> dict[str, Any]:
    w = rn.forward_world(setup, inputs, seed, 0, 0.0)
    days = [
        setup.start + timedelta(d)
        for d in GATE_DAYS
        if setup.start + timedelta(d) <= setup.season_end
    ]
    matches = checks.surrogate_matches(setup, w, me, days, knobs)
    g = vg.surrogate_gate(matches, season=setup.league)
    g.detail.update({"days": [d.isoformat() for d in days]})
    return gate_dict(g)


def gate_refresh(
    data: Path, league: str, inputs: rn.WorldInputs, fit: Mapping[str, Any]
) -> dict[str, Any]:
    """Gate 6: the refresh in force against the week-to-week changes the exports on disk show."""
    import math

    try:
        exports, realized, games = residual_inputs(data, league)
    except reader.SimReadError as e:
        return not_run("refresh", league, str(e))
    if len(exports) < 2:
        return not_run("refresh", league, f"{len(exports)} export(s) on disk, two needed")
    gaps: list[float] = []
    steps: list[float] = []
    (d0, b0), (d1, b1) = exports[-2], exports[-1]
    days = max(1, (d1 - d0).days)
    for p, r in realized.items():
        if games.get(p, 0) < fitmod.TAU_FLOOR_GAMES:
            continue  # a realized rate over fewer games is noise, not the truth the gap needs
        if p in b0 and p in b1:
            for stat in fitmod.COUNTING:
                a, b, t = b0[p].get(stat, 0), b1[p].get(stat, 0), r.get(stat, 0)
                if a > 0 and b > 0 and t > 0:
                    gaps.append(math.log(t / a))
                    steps.append(math.log(b / a))
    kappa_interval = 1.0 - (1.0 - inputs.kappa) ** (days / 7.0)
    g = vg.refresh_gate(kappa_interval, gaps, steps, season=league)
    if g.detail.get("reason") == "too few pairs":
        return not_run(
            "belief_refresh",
            league,
            f"{len(gaps)} player-stat pairs with {fitmod.TAU_FLOOR_GAMES}+ games, too few",
        )
    g.detail.update(
        {
            "exports": [d0.isoformat(), d1.isoformat()],
            "days": days,
            "pairs": len(gaps),
            "refresh": inputs.refresh_from,
        }
    )
    return gate_dict(g)


def cmd_validate(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    started = datetime.now(UTC)
    today = today_of(args)
    leagues = league_ids(args.league, args.data)
    try:
        inputs, fit, sha, fit_path, tau_note = world_inputs(args.data, leagues)
    except (reader.SimReadError, ValueError, OSError) as e:
        print(f"refused: {e}")
        return 2
    gates: list[dict[str, Any]] = []
    gates.append(gate_hold_out_team_weeks(args.data, HOLD_OUT, inputs, args.seed))
    for season in (HOLD_OUT, THIS_SEASON):
        gates.append(gate_absences(args.data, season, inputs, args.seed))
    setups, skipped = setups_of(args.data, leagues, today, args.system)
    for league, setup in setups.items():
        gates += gate_recorded_weeks(args.data, league, setup, inputs, args.seed)
        gates.append(
            not_run("realized_share", league, "the scorecard's realized rows are read in PR 3")
        )
        me = reader.settings_of(args.data, league).my_team_id
        if me is not None and me in setup.teams:
            gates.append(
                gate_surrogate(setup, inputs, me, policy_knobs(args.data, league), args.seed)
            )
        else:
            gates.append(not_run("surrogate", league, "no team of mine"))
    if leagues:
        gates.append(gate_refresh(args.data, leagues[0], inputs, fit))
    payload = base_payload(
        "validate", args.name or "validate", started, sha, fit_path, fit, 1, tau_note, inputs
    )
    payload |= {
        "today": today.isoformat(),
        "leagues": {league: league_note(s_) for league, s_ in setups.items()},
        "skipped": skipped,
        "seed": args.seed,
        "gates": gates,
        "passed": all(g["passed"] for g in gates if g["passed"] is not None)
        and any(g["passed"] is not None for g in gates),
        "not_run": [g["name"] for g in gates if g["passed"] is None],
    }
    path = finish(payload, args.data, args.dry_run)
    for league, why in skipped.items():
        print(f"league {league} skipped: {why}")
    for g in gates:
        state = "not run" if g["passed"] is None else "passed" if g["passed"] else "FAILED"
        extra = (
            f" ({g['detail'].get('reason')})"
            if g["passed"] is None
            else f" {g['detail'].get('worst', '')}"
        )
        print(f"{g['name']:16} {g['season']!s:12} {state}{extra}")
    print(f"written: {path}" if path else "dry run, nothing written")
    return 0


def policy_knobs(data: Path, league: str) -> dict[str, Any]:
    """A league's live knobs as its solves run with them, and the simulator's two at their
    defaults; the twelve defaults (``policy.KNOB_DEFAULTS``) when the knob file cannot be read."""
    from ..api.season_knobs import for_league

    try:
        return policy.check_knobs({**policy.KNOB_DEFAULTS, **for_league(data, league)})
    except (OSError, ValueError, KeyError):
        return policy.check_knobs(dict(policy.KNOB_DEFAULTS))


# --------------------------------------------------------------------------- main
def _run_args(p: argparse.ArgumentParser, paths: int = PATHS) -> None:
    p.add_argument("--paths", type=int, default=paths, help=f"paths a league (default {paths})")
    p.add_argument("--seed", type=int, default=1, help="the run's seed (default 1)")
    p.add_argument("--workers", type=int, default=None, help="processes (default cores less two)")
    p.add_argument("--name", default=None, help="the run's name in its payload and file")
    p.add_argument("--expected-hours", type=float, default=None, help="override the estimate")
    p.add_argument("--announced", action="store_true", help="the run over an hour was announced")
    p.add_argument("--dry-run", action="store_true", help="estimate and write nothing")
    p.add_argument("--today", default=None, help="the first simulated day (default the NBA date)")
    p.add_argument("--system", default="bbm", help="the shared projection system (default bbm)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=DATA, help="the data folder (default data/)")
    ap.add_argument("--rooms", type=int, default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="command", required=True)
    fe = sub.add_parser("fetch-logs", help="ESPN's per-game logs for whole seasons, cached")
    fe.add_argument("--seasons", default="2022-2026", help="ESPN season ids, e.g. 2022-2026")
    fe.set_defaults(func=cmd_fetch)
    fi = sub.add_parser("fit", help="the world's fit over the cached seasons, frozen with a hash")
    fi.add_argument(
        "--seasons",
        default=FIT_SEASONS,
        help=f"the seasons to fit, never the hold-out {HOLD_OUT} (default {FIT_SEASONS})",
    )
    fi.add_argument(
        "--hold-out",
        type=int,
        default=None,
        help=f"a second season no fit sees, beside {HOLD_OUT} which is always refused",
    )
    fi.add_argument("--dry-run", action="store_true", help="print the fit, write nothing")
    fi.add_argument(
        "--tau",
        choices=("systems", "residual"),
        default="systems",
        help="residual: tau from this season's realized rates against the first export (week six)",
    )
    fi.add_argument(
        "--refresh", action="store_true", help="fit the beliefs' refresh from the exports on disk"
    )
    fi.add_argument(
        "--league", default=None, help="the league whose players the exports are matched on"
    )
    fi.set_defaults(func=cmd_fit)
    co = sub.add_parser("compare", help="arm A against arm B in my seat, paired, per league")
    co.add_argument("a", type=Path, help="arm A's spec file (the knobs in force)")
    co.add_argument("b", type=Path, help="arm B's spec file (the change)")
    co.add_argument("--leagues", default="all", help="league ids, comma separated, or all")
    co.add_argument("--shrink", default=None, help="shrinks, comma separated (default 0,0.25,0.5)")
    _run_args(co)
    co.set_defaults(func=cmd_compare)
    re_ = sub.add_parser("replay", help="a made-up league on a recorded season's lines")
    re_.add_argument("--season", type=int, required=True, help=f"ESPN season id, never {HOLD_OUT}")
    re_.add_argument("--standin", default="prior", help="prior, or oracle:0.1,0.2,0.3")
    re_.add_argument("--seats", type=Path, nargs="+", required=True, help="the arms' spec files")
    re_.add_argument(
        "--news-sd",
        type=float,
        default=world.NEWS_SD_DAYS,
        help=f"the told return date's spread in days (default {world.NEWS_SD_DAYS:g})",
    )
    re_.add_argument(
        "--no-peek",
        default=None,
        metavar="YYYY-MM-DD",
        help="check one path against a season changed after this date; writes nothing",
    )
    _run_args(re_, paths=20)
    re_.set_defaults(func=cmd_replay)
    ro = sub.add_parser("room", help="the arms around one league's table, rotated across paths")
    ro.add_argument("--leagues", default="all", help="league ids, comma separated, or all")
    ro.add_argument("--seats", type=Path, nargs="+", required=True, help="the arms' spec files")
    ro.add_argument(
        "--draft",
        choices=("rosters", "snake"),
        default="rosters",
        help="the recorded rosters, or a snake redraft",
    )
    ro.add_argument("--shrink", type=float, default=0.0, help="the shrink (default 0)")
    _run_args(ro, paths=20)
    ro.set_defaults(func=cmd_room)
    va = sub.add_parser("validate", help="the six gates on the recorded weeks and the hold-out")
    va.add_argument("--league", default="all", help="league ids, comma separated, or all")
    va.add_argument("--seed", type=int, default=1)
    va.add_argument("--name", default=None)
    va.add_argument("--dry-run", action="store_true", help="print the gates, write nothing")
    va.add_argument("--today", default=None)
    va.add_argument("--system", default="bbm")
    va.set_defaults(func=cmd_validate)
    args = ap.parse_args(argv)
    return args.func(args)
