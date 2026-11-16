"""SEASON SIM (#172): the season simulator's commands, for the terminal.

    python -m pickandroll.sim fetch-logs --seasons 2022-2026   # ESPN's per-game logs, cached
    python -m pickandroll.sim fit                              # the world's fit, frozen with a hash
    python -m pickandroll.sim fit --dry-run                    # the fit printed, nothing written
    python -m pickandroll.sim replay --seasons 2022-2024 --forecasters prior,espn --seats A.json B.json
    python -m pickandroll.sim replay --seasons 2022-2024 --forecasters prior,espn --arms A.json B.json
    python -m pickandroll.sim replay --seasons 2024 --forecasters oracle:0.1 --shape minutes ...
    python -m pickandroll.sim replay --seasons 2024 --bbm-as espn --yahoo-as marcel --seats ...
    python -m pickandroll.sim replay --seasons 2024 --seats A.json B.json --no-peek 2023-12-04
    python -m pickandroll.sim validate --season 2024 --forecaster prior

ESPN's season id is the year the season ends in: 2025 is 2024-25, the hold-out. ``fetch-logs``
makes one request a season through the same player view the draft-edge audit read, caches each
under ``data/external/espn/gamelogs/`` (never committed) and never retries inside a run. ``fit``
refuses the hold-out whatever the flags say (``--hold-out`` may only add a second season no
fit sees), fits each cached season, pools the ones that agree and writes
``data/sim/fit/<date>/fit.json`` with ``fit.sha256`` beside it; the frozen fit's
figures stay under ``data/`` and are described in words anywhere public.

``replay`` plays a made-up league on one or several recorded seasons' game lines, never the
hold-out, its seats believing only the games already played, once for each season and
forecaster that serves it (a cell): the arms rotated around the table (``--seats``) or two arms
paired in one seat (``--arms``, B less A, with a verdict by forecaster and season); a written
replay that names the confirmation season adds a line to its ledger; ``--no-peek`` checks one
path of one season against it changed after a date and writes nothing. ``validate`` runs gate 5
on a replay of a recorded season (``--season``, ``--forecaster``) and writes what it had to work
with. Every run's payload goes under ``data/sim/runs/`` with the code's commit, the fit's hash,
the hold-out, the spec files verbatim and the execution model.

Every command runs through :func:`guard`: at low priority (``nice``), never when its span would
touch 04:45-06:45 in the machine's local time (the routines' window), never while a draft room is
open on the API, and a run expected over an hour is announced on the tracker and starts on the
user's word (``--announced`` says that has happened).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time as clock
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from . import audit, checks, gamelogs, nopeek, policy, world
from . import counts as ct
from . import fit as fitmod
from . import forecast as fc
from . import readers as reader
from . import run as rn
from . import validate as vg
from .engine import wk

#: The repository: this file is ``src/pickandroll/sim/cli.py``.
ROOT = Path(__file__).resolve().parents[3]
API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
#: How the commands are run (argparse would otherwise name ``__main__.py``).
PROG = "python -m pickandroll.sim"
DATA = ROOT / "data"
LOGS_DIR = reader.LOGS_DIR
FIT_DIR = reader.FIT_DIR
#: The routines' window, in the machine's local time: no run's span touches it.
QUIET_FROM = time(4, 45)
QUIET_TO = time(6, 45)
#: A run expected to take longer is announced on the tracker and starts on the user's word;
#: ``--announced`` says that has happened.
ANNOUNCE_HOURS = 1.0
NICE = 10
TIMEOUT = 60
#: The hold-out season (#172): 2024-25, in no fit, never a replay's or a comparison's target.
HOLD_OUT = 2025
#: The confirmation season (2025-26, ESPN id 2026): a written replay that names it is a look, one
#: line in the ledger (``readers.append_look``; #172, PR D2). Refusing it inside a search set is
#: PR H's.
CONFIRMATION = 2026
CONFIRMATION_NOTE = (
    "the confirmation season is looked at sparingly: every written replay that names it appends "
    "one line to the ledger (when, the run's name, the design, the seasons, the forecasters, a "
    "hash of each spec, the fit's hash, the code's commit), and this run is the look its number "
    "names; a dry run and a no-peek check add none"
)
#: The five seasons on disk, ESPN ids (2022 is 2021-22), and the ones a fit may see.
SEASONS = (2022, 2023, 2024, 2025, 2026)
FIT_SEASONS = ",".join(str(s) for s in SEASONS if s != HOLD_OUT)
#: The league-days gate 5 samples: the replay's first simulated day and these days after it,
#: for each of :func:`gate_seats`.
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
    """The guard's clock, the machine's local time. A seam the tests pin: a suite run inside the
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
            f"({QUIET_FROM:%H:%M}-{QUIET_TO:%H:%M} local time)"
            if expected_hours
            else f"inside the routines' window ({QUIET_FROM:%H:%M}-{QUIET_TO:%H:%M} local time)"
        )
    open_rooms = rooms_open() if rooms is None else rooms
    if open_rooms:
        return False, f"{open_rooms} draft room(s) open on the API"
    if expected_hours > ANNOUNCE_HOURS and not announced:
        return False, (
            f"a run of about {expected_hours:g} h is announced on the tracker and starts on the "
            "user's word; --announced says that has happened"
        )
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
) -> tuple[dict[str, Any], str, fitmod.Fit]:
    """Fit every cached season of ``seasons``, pool, freeze. The named hold-out
    (:data:`HOLD_OUT`) is refused whatever the flags say; ``extra_hold_out`` may add a second
    season no fit sees, never remove the named one."""
    fitmod.check_hold_out(seasons, HOLD_OUT)
    fitmod.check_hold_out(seasons, extra_hold_out)
    lines = load_lines(seasons, data)
    if not lines:
        raise FileNotFoundError(f"no cached season among {list(seasons)} under {data / LOGS_DIR}")
    fits = [fitmod.fit_season(rows, season) for season, rows in sorted(lines.items())]
    pooled = fitmod.pool(fits)
    extra = {"extra_hold_out": extra_hold_out} if extra_hold_out not in (None, HOLD_OUT) else {}
    payload, sha = fitmod.freeze(pooled, HOLD_OUT, parameters=extra, seasons=fits)
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
    return text


def cmd_fit(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    try:
        payload, sha, _ = run_fit(parse_seasons(args.seasons), args.data, args.hold_out)
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
def read_specs(paths: Sequence[Path]) -> list[dict[str, Any]]:
    return [json.loads(Path(p).read_text()) for p in paths]


def world_inputs(data: Path) -> tuple[rn.WorldInputs, dict[str, Any], str, Path]:
    """The newest frozen fit, read for the lag and its hash (``run.inputs_of``), with its
    payload, hash and file."""
    payload, sha, path = reader.newest_fit(data)
    return rn.inputs_of(payload, sha), payload, sha, path


#: The commands whose outcome runs through the engine's evaluator (an exact tie there can fall
#: either way with the process's hash seed).
SIMULATING = ("replay", "validate")
HASH_SEED_NOTE = (
    "PYTHONHASHSEED is unset: at an exact tie the outcome may differ between processes (an "
    "order-dependent sum in the engine's evaluator); a run to be reproduced sets PYTHONHASHSEED=0"
)


def hash_seed() -> str:
    """The process's ``PYTHONHASHSEED`` as the run record keeps it: its value, or ``"random"``
    when it is unset (or empty, which Python reads as unset)."""
    return os.environ.get("PYTHONHASHSEED") or "random"


def base_payload(
    kind: str,
    name: str,
    started: datetime,
    sha: str,
    fit_path: Path,
    fit: Mapping[str, Any],
    workers: int,
    arms: Mapping[str, rn.Arm] | None = None,
) -> dict[str, Any]:
    """The payload's common part. ``arms`` by their key in the payload (``a`` and ``b`` in a
    pair, the names in a room): each arm's fields and its surrogate's pool and days; none
    (validate) for the live route's, the surrogate gate's."""
    fields = {k: arm.fields for k, arm in (arms or {}).items()} or {"gate": policy.Fields()}
    return {
        "kind": kind,
        "name": name,
        "started_at": started.isoformat(),
        "host": platform.node(),
        "workers": workers,
        "nice": NICE,
        "hash_seed": hash_seed(),
        "code_sha": reader.code_sha(ROOT),
        "fit_sha": sha,
        "fit_file": str(fit_path),
        "hold_out": fit.get("hold_out", HOLD_OUT),
        "executions": EXECUTIONS,
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
                f"{m} {row[m]:.4g}"
                for m in ("gain", "ros", "ratio", "against")
                if row.get(m) is not None
            )
            print(f"season scale, {arm}, the first task: {shown} over {row['swaps']} swaps")
    unprojected = first.get("unprojected") or {}
    by_side = unprojected if "delta" in first else {"": unprojected}
    for side, rows in by_side.items():
        for label, row in rows.items():
            whose = f"arm {side.upper()}'s " if side else ""
            print(
                f"unprojected, {whose}{label}, the first task: {row['seats']} on its seats' "
                f"rosters, {row['all']} on all"
            )
    if "delta" in first and "seat" in first:
        shown = {
            side: ", ".join(f"{m} {v:g}" for m, v in first[side].items() if v is not None)
            for side in ("a", "b", "delta")
        }
        print(
            f"pair, the first task: seat {first['seat']}; A {shown['a']}; B {shown['b']}; "
            f"B less A {shown['delta']}"
        )
    _, note = audited([key], [first])
    print("dry run, nothing written")
    return audit_exit(note)


def counts_of(rows: Sequence[Any]) -> dict[str, Any] | None:
    """The counts of the paths that stand, pooled like the outcomes; None without a row."""
    have = [r for r in rows if r is not None]
    return rn.aggregate(have, ct.METRICS) if have else None


# --------------------------------------------------------------------------- the knobs (PR C)
#: What the payload's season scale is.
SCALE_NOTE = (
    "per arm: on the first simulated day of each path, for the arm's own seat (a replay's or a "
    "room's: its first seat in team order), over the arm's pool, each candidate's best single "
    "swap on the key the arm executes, without the season term. gain: the median of their gains "
    "on that key (expected category wins in a categories league). ros: the median of their "
    "ROS_w (season value above a dead spot times the games left, a bracket game counted "
    "playoff_weight times). ratio: the median size of the gain over the median size of ROS_w, "
    "over the swaps that have a ROS_w, 0 or more: the season_weight at which the term is the "
    "gain's size. against: the share of those swaps whose ROS_w is below 0, the week's best swap "
    "costing season value. Each the mean over the paths that stand; null on the ranking tier and "
    "a static seat."
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

    return {
        "gain": mean("gain"),
        "ros": mean("ros"),
        "ratio": mean("ratio"),
        "against": mean("against"),
        "paths": len(have),
    }


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


# --------------------------------------------------------------------------- replay
@dataclass(frozen=True)
class Fixed:
    """What of a run's forecasters is the same on every path, read once before any path:
    ``rates`` by name (``prior``, ``espn``, ``marcel``), ESPN's projected games (the freeze
    check's) and the seasons ``marcel`` read. An oracle is drawn per path."""

    rates: Mapping[str, Mapping[int, Mapping[str, float]]]
    espn_games: Mapping[int, float]
    marcel_seasons: tuple[int, ...] = ()


def fixed_of(data: Path, season: int, named: Sequence[fc.Forecaster]) -> Fixed:
    """The named forecasters' figures for a replay of ``season``; one that cannot serve the
    season (no prior log, one earlier season for ``marcel``, no projection block) is refused by
    name, before any path."""
    names = {f.name for f in named}
    rates: dict[str, Mapping[int, Mapping[str, float]]] = {}
    games: Mapping[int, float] = {}
    read: list[int] = []
    for name in ("prior", "espn", "marcel"):
        if name not in names:
            continue
        try:
            if name == "prior":
                rates[name] = reader.prior_rates(data, season)
            elif name == "espn":
                rates[name], games = reader.espn_rates(data, season)
            else:
                rates[name], read = reader.marcel_rates(data, season)
        except reader.SimReadError as e:
            message = str(e)
            raise reader.SimReadError(
                message if name in message else f"{name}: {message}"
            ) from None
    return Fixed(rates, games, tuple(read))


def projection_of(
    f: fc.Forecaster, fixed: Fixed, lines: Any, seed: int, path: int, shape: str
) -> Mapping[int, Mapping[str, float]]:
    """A forecaster's projection on one path: an oracle's draw (a stand-in's on its role's
    stream), any other's figures."""
    if f.name == "oracle":
        assert f.spread is not None
        return fc.oracle(lines, f.spread, seed, path, shape, role=f.role)
    return fixed.rates[f.name]


#: The two sources' stand-ins a run names: the first's (``bbm``) and the second's (``yahoo``).
Sources = tuple[fc.Forecaster, fc.Forecaster]


def sources_of(bbm: str | None, yahoo: str | None) -> Sources | None:
    """The stand-ins ``--bbm-as`` and ``--yahoo-as`` name, None when neither is given. One
    without the other, or the same forecaster for both, is refused by name."""
    if bbm is None and yahoo is None:
        return None
    if bbm is None or yahoo is None:
        given = "--bbm-as" if yahoo is None else "--yahoo-as"
        raise ValueError(f"{given} without the other: a run names both sources' stand-ins or none")
    first = fc.standin(fc.parse_one(bbm), "bbm")
    second = fc.standin(fc.parse_one(yahoo), "yahoo")
    if first.label == second.label:
        raise ValueError(f"--bbm-as and --yahoo-as both name {first.label}: the two sources differ")
    return first, second


def believing(arms: Mapping[str, rn.Arm], sources: Sources | None) -> dict[str, rn.Arm]:
    """The arms, each believing by its ``system`` when the run names the stand-ins: its
    forecaster the label ``forecast.system_label`` gives; as they are otherwise."""
    if sources is None:
        return dict(arms)
    first, second = sources
    return {
        name: replace(
            arm,
            forecaster=fc.system_label(
                str(arm.knobs["system"]), arm.knobs["blend"], first.label, second.label
            ),
        )
        for name, arm in arms.items()
    }


def forecasts_of(
    sources: Sources | None,
    fixed: Fixed,
    lines: Any,
    seed: int,
    path: int,
    shape: str,
    arms: Mapping[str, rn.Arm],
) -> dict[str, Mapping[int, Mapping[str, float]]]:
    """The beliefs' projections the arms name on one path, by label: each arm's system on the
    two stand-ins (``forecast.system_rates``, a split label's available side), and the first
    stand-in's own whenever an arm's label is split (:func:`splits_of`: its rostered side);
    none without stand-ins."""
    if sources is None:
        return {}
    first = projection_of(sources[0], fixed, lines, seed, path, shape)
    second = projection_of(sources[1], fixed, lines, seed, path, shape)
    out: dict[str, Mapping[int, Mapping[str, float]]] = {}
    for arm in arms.values():
        if arm.forecaster is not None and arm.forecaster not in out:
            system, blend = str(arm.knobs["system"]), arm.knobs["blend"]
            out[arm.forecaster] = fc.system_rates(system, blend, first, second)
    if splits_of(sources, arms) and sources[0].label not in out:
        out[sources[0].label] = first
    return out


def splits_of(sources: Sources | None, arms: Mapping[str, rn.Arm]) -> dict[str, str]:
    """Each split label the arms hold (``forecast.SPLIT``: a ``yahoo`` or ``blend`` seat's) and
    its rostered side's label, the first stand-in's: a player on any roster that morning reads
    the first's belief (``run.World.split``)."""
    if sources is None:
        return {}
    return {
        arm.forecaster: sources[0].label
        for arm in arms.values()
        if arm.forecaster is not None and str(arm.knobs["system"]) in fc.SPLIT
    }


def replay_setup_of(season: int, lines: Any, members: Any, scheduled: Any, projection: Any) -> Any:
    """A replay's league in one path, drafted on the run's forecaster's ``projection``."""
    return rn.replay_setup(season, lines, members, projection, reader.PERIOD_ONE[season], scheduled)


def task_replay(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    forecaster: fc.Forecaster,
    fixed: Fixed,
    shape: str,
    sources: Sources | None,
    lag: int,
    weights: Mapping[str, Mapping[str, float]],
    news_sd: float,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    seed: int,
    path: int,
) -> dict[str, Any]:
    projection = projection_of(forecaster, fixed, lines, seed, path, shape)
    setup = replay_setup_of(season, lines, members, scheduled, projection)
    w = rn.replay_world(
        setup,
        lines,
        lag,
        seed,
        path,
        weights[forecaster.label],
        news_sd=news_sd,
        label=forecaster.label,
        forecasts=forecasts_of(sources, fixed, lines, seed, path, shape, arms),
        split=splits_of(sources, arms),
        weights_of=weights,
    )
    held = {t: arms[name].forecaster for t, name in rn.rotate(seats, setup.teams, path).items()}
    unprojected = rn.unprojected(setup, w, held)
    out = rn.room(setup, w, arms, seats, path)
    out["forecaster"] = forecaster.label
    out["unprojected"] = unprojected
    return out


def seat_of(setup: Any, path: int) -> int:
    """The paired design's seat on ``path``: ``setup.teams[path mod len(teams)]``, so over a
    multiple of the seats every seat is taken equally often (#172, PR D2)."""
    return setup.teams[path % len(setup.teams)]


def paths_for_pair(paths: int, teams: int = rn.REPLAY_TEAMS) -> int:
    """``paths`` rounded up to a multiple of the league's ``teams``."""
    return -(-max(1, paths) // teams) * teams


def task_paired(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    forecaster: fc.Forecaster,
    fixed: Fixed,
    shape: str,
    sources: Sources | None,
    lag: int,
    weights: Mapping[str, Mapping[str, float]],
    news_sd: float,
    arms: Mapping[str, rn.Arm],
    pair: Sequence[str],
    seed: int,
    path: int,
) -> dict[str, Any]:
    """One task of the paired design on a replay (#172, PR D2): the league drafted on the cell's
    forecaster, arm A in seat :func:`seat_of` in one season and arm B in the same seat in a
    second, through one world (``run.paired``); every other seat is each arm's rivals, on the
    run's forecaster. ``pair`` names the two arms' keys in ``arms`` (``a`` and ``b``)."""
    projection = projection_of(forecaster, fixed, lines, seed, path, shape)
    setup = replay_setup_of(season, lines, members, scheduled, projection)
    w = rn.replay_world(
        setup,
        lines,
        lag,
        seed,
        path,
        weights[forecaster.label],
        news_sd=news_sd,
        label=forecaster.label,
        forecasts=forecasts_of(sources, fixed, lines, seed, path, shape, arms),
        split=splits_of(sources, arms),
        weights_of=weights,
    )
    me = seat_of(setup, path)
    a, b = (arms[k] for k in pair)
    unprojected = {
        k: rn.unprojected(
            setup, w, {t: arms[k].forecaster if t == me else None for t in setup.teams}
        )
        for k in pair
    }
    out = rn.paired(setup, w, a, b, me)
    out["seat"] = me
    out["forecaster"] = forecaster.label
    out["unprojected"] = unprojected
    return out


#: The replay's version in its payload: 5 since the standalone cut (#172, PR D3): the payload
#: names nothing of a live league or a drawn world (its ``gap``, ``refresh`` and ``tau`` are
#: gone), its figures as they were; 4 since
#: a run names several seasons (PR D2): what
#: is one season's (results, counts, the season scale, the forecasters, the sources, the
#: weights, the players, the shape, the unprojected count) is keyed by season, and each label's
#: weights are its own; 3 since a run names its forecasters (PR D1): its results and counts are
#: keyed by the forecaster's label (``prior``, ``oracle:0.1``), where version 2 keyed them by kind
#: and spread (``prior:0``); 2 since its seats believe only the games played (PR B1), a version 1
#: replay's seats having seen each season's rates.
REPLAY_VERSION = 5
REPLAY_VERSION_WHY = (
    "5: the standalone cut: the payload names nothing of a live league or a drawn world (no gap, "
    "refresh or tau); the figures are version 4's"
)
BELIEF_RULE = (
    "per stat, (w * the forecaster's figure + the sum of his lines dated before the day) / "
    "(w + his games before the day), read every day"
)
NEWCOMER_RULE = (
    "a player nobody projected enters the belief the day after his first recorded game, from "
    "the mean projection over the projected players left undrafted"
)
#: Whose weights each belief takes (#172, PR D2: each label's own).
WEIGHTS_RULE = (
    "each belief label's weights are fitted on that label's own projection of the seasons on "
    "file earlier than the replayed one (readers.label_weights): prior the season before's "
    "rates; espn the season's stored projection, none where it fails the freeze check; marcel "
    "where two earlier seasons are on file; an oracle a draw of the season at its spread and "
    "shape, on keys of its own; a system label the system's table on the two stand-ins' "
    "projections, where both serve the season. No sample's season, nor any season its "
    "projection read, is the hold-out. A label with no sample takes the prior forecaster's "
    "weights when those were fitted, else the default; each label's record says which"
)
#: What the unprojected count is (#172, PR D2).
UNPROJECTED_NOTE = (
    "per belief label an arm holds: the drafted players its table has no line for on the first "
    "day (a split label: its rostered side's table), on the rosters of the seats that hold it "
    "(seats) and on all twelve (all); a seat values such a player at zero until he plays. The "
    "mean and the largest over the paths that stand. Zero by construction for the run's own "
    "label, whose projection the draft read"
)
#: The printed line when a seat can hold drafted players its belief does not project.
UNPROJECTED_WARNING = (
    "note: no forecaster of the run is the first stand-in, so a seat can hold drafted players "
    "its belief does not project (it values them at zero until they play); the payload counts "
    "them under unprojected"
)


def source_of(f: fc.Forecaster, fixed: Fixed, shape: str) -> str:
    """One sentence on where a forecaster's projection comes from."""
    if f.name == "prior":
        return (
            f"the prior season's per-game rates of the players with {fc.MIN_GAMES} played games "
            "in it"
        )
    if f.name == "espn":
        return (
            "ESPN's stored season projection for the replayed season, per game, for every "
            "player whose block has games; ESPN updates it through the season (see freeze)"
        )
    if f.name == "marcel":
        read = ", ".join(str(t) for t in fixed.marcel_seasons)
        weights = ", ".join(f"{w:g}" for w in fc.MARCEL_WEIGHTS[: len(fixed.marcel_seasons)])
        return (
            f"the per-game lines of seasons {read} weighted {weights} by recency, regressed "
            f"toward the mean of the players with {fc.MARCEL_MIN_GAMES} games in the latest by "
            f"{fc.MARCEL_REGRESS_GAMES:g} games; a player with {fc.MARCEL_MIN_GAMES} games in "
            "one of them is projected"
        )
    return (
        f"the replayed season's realized rates of the players with {fc.MIN_GAMES} played games, "
        f"noised on the log scale at {f.spread:g} per player and stat ({shape} shape): a "
        "labelled look-ahead whose error is known"
    )


def forecasters_block(
    named: Sequence[fc.Forecaster],
    fixed: Fixed,
    lines: Any,
    seed: int,
    shape: str,
    sources: Sources | None = None,
    weights: Mapping[str, fitmod.LabelWeights] | None = None,
) -> dict[str, Any]:
    """The payload's ``forecasters``: per label where its projection comes from, how many players
    it projects and how many of them played ``forecast.ERROR_MIN_GAMES`` games, its error
    against the replayed season (``forecast.error_of``; an oracle's on path 0, where it should
    sit at its spread), ``espn``'s freeze check and its belief's weights (``weights``, by label);
    the two sources' stand-ins among them, with the role each stands for. Never shown to a
    seat."""
    out: dict[str, Any] = {}
    played = {k: len(v) for k, v in lines.items()}
    roles: dict[str, list[str]] = {}
    for f in sources or ():
        roles.setdefault(f.label, []).append(fc.ROLES[list(sources or ()).index(f)])
    every = list(dict.fromkeys([*named, *(sources or ())]))
    for f in every:
        rates = projection_of(f, fixed, lines, seed, 0, shape)
        e = fc.error_of(rates, lines)
        block: dict[str, Any] = {
            "name": f.name,
            "source": source_of(f, fixed, shape),
            "projected": e["projected"],
            "played": e["played"],
            "error": {k: e[k] for k in ("min_games", "by_stat", "median_spread")},
            "weights": weights[f.label].payload() if weights and f.label in weights else None,
        }
        if f.name == "oracle":
            block["error"]["measured_on"] = "path 0: an oracle's error should sit at its spread"
        if f.name == "espn":
            block["freeze"] = fc.freeze_of(fixed.espn_games, played)
        if f.label in roles:
            block["stands_for"] = roles[f.label]
        out[f.label] = block
    return out


SOURCES_NOTE = "the result is about two sources with these errors, not about the two real sources"
ORACLE_SOURCES_NOTE = (
    "an oracle stand-in draws from its role's own stream: two oracle stand-ins have independent "
    "errors and neither shares the run's draws; two real sources' errors are correlated, so with "
    "oracle stand-ins the mix's benefit is an upper bound"
)


def sources_block(
    sources: Sources | None,
    arms: Mapping[str, rn.Arm],
    fixed: Fixed,
    lines: Any,
    seed: int,
    shape: str,
) -> dict[str, Any] | None:
    """The payload's ``sources``: the two stand-ins' labels, what the result is about, the rule
    as modelled and what still differs from the live route, and each system belief an arm holds
    with its rostered side and the error of its table (a split label's: the available side's)
    on path 0; None without stand-ins."""
    if sources is None:
        return None
    first, second = sources
    forecasts = forecasts_of(sources, fixed, lines, seed, 0, shape, arms)
    split = splits_of(sources, arms)
    systems = {}
    for arm in arms.values():
        label = arm.forecaster
        if label is None or label in systems:
            continue
        system = str(arm.knobs["system"])
        e = fc.error_of(forecasts[label], lines)
        systems[label] = {
            "system": system,
            "share": fc.share_of(system, arm.knobs["blend"]),
            "rostered": split.get(label),
            "projected": e["projected"],
            "played": e["played"],
            "error": {k: e[k] for k in ("min_games", "by_stat", "median_spread")},
        }
    return {
        "bbm": first.label,
        "yahoo": second.label,
        "note": SOURCES_NOTE,
        "oracle": ORACLE_SOURCES_NOTE if "oracle" in (first.name, second.name) else None,
        "rule": fc.SYSTEMS_RULE,
        "differs": list(fc.LIVE_DIFFERENCES),
        "systems": systems,
    }


def replay_notes(
    weights: Mapping[str, Mapping[str, fitmod.LabelWeights]], news_sd: float
) -> dict[str, Any]:
    """What a replay's seats knew, for its payload: ``weights`` by season, then by belief label."""
    return {
        "replay_version": REPLAY_VERSION,
        "replay_version_why": REPLAY_VERSION_WHY,
        "belief": {
            "kind": "causal",
            "rule": BELIEF_RULE,
            "weights": {
                t: {label: lw.payload() for label, lw in by_label.items()}
                for t, by_label in weights.items()
            },
            "weights_rule": WEIGHTS_RULE,
        },
        "newcomer": NEWCOMER_RULE,
        "pool": {
            "league": "everyone the season's log lists with a scheduled game",
            "draft": (
                f"the projected players with a scheduled game in the season's first "
                f"{rn.OPENING_DAYS} days"
            ),
            "projected": (
                f"prior and an oracle project the players with {fc.MIN_GAMES} played games in "
                "the season they read, espn every player whose block has games, marcel the "
                f"players with {fc.MARCEL_MIN_GAMES} games in one of the seasons it reads"
            ),
        },
        "news_sd_days": news_sd,
    }


def belief_labels(
    named: Sequence[fc.Forecaster], sources: Sources | None, arms: Mapping[str, rn.Arm]
) -> dict[str, reader.BeliefLabel]:
    """Every belief label a replay holds, by label, as its weights' fit reads it: each of the
    run's forecasters, each system label the arms hold (a ``bbm`` seat's is the first stand-in's
    own) and the first stand-in's whenever a label is split (#172, PR D2)."""
    out: dict[str, reader.BeliefLabel] = {f.label: f for f in named}
    if sources is None:
        return out
    first, second = sources
    for arm in arms.values():
        system = str(arm.knobs["system"])
        label: reader.BeliefLabel = (
            first if system == "bbm" else fc.SystemBelief(system, arm.knobs["blend"], first, second)
        )
        out.setdefault(label.label, label)
    if splits_of(sources, arms):
        out.setdefault(first.label, first)
    return out


def weights_lines(weights: Mapping[str, fitmod.LabelWeights]) -> list[str]:
    """One printed line a belief label: its weights and where they come from."""
    out = []
    for label, lw in weights.items():
        shown = ", ".join(
            f"{s} {lw.weights.weights[s]:g}" for s in wk.STATS if s in lw.weights.weights
        )
        seasons = ", ".join(str(t) for t in lw.weights.seasons)
        source = lw.source if not seasons else f"{lw.source}, seasons {seasons}"
        out.append(f"belief weights, {label} ({source}): {shown}")
    return out


def unprojected_of(rows: Sequence[Mapping[str, Mapping[str, int]]]) -> dict[str, Any]:
    """The unprojected count of the paths that stand, by label: the mean and the largest over
    paths of each count (:func:`run.unprojected`)."""
    labels = list(dict.fromkeys(label for r in rows for label in r))
    out: dict[str, Any] = {}
    for label in labels:
        have = [r[label] for r in rows if label in r]
        out[label] = {
            k: {"mean": sum(x[k] for x in have) / len(have), "max": max(x[k] for x in have)}
            for k in ("seats", "all")
        }
    return out


def no_peek(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    projection: Any,
    lag: int,
    weights: Mapping[str, float],
    news_sd: float,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    seed: int,
    day: date,
    label: str | None = None,
    forecasts: Mapping[str, Any] | None = None,
    split: Mapping[str, str] | None = None,
    weights_of: Mapping[str, Mapping[str, float]] | None = None,
    paired: bool = False,
) -> tuple[Any, int, list[dict[str, Any]]]:
    """Path 0 of the replay on the recorded lines and on :func:`nopeek.perturb`'s, with one
    league built before either (on ``projection``, the run's forecaster's on path 0, ``label``,
    believed at ``weights``; ``forecasts`` the arms' other beliefs' projections, at their own
    ``weights_of``; ``split`` their split labels): the first difference between their day records
    (None when they never part), the records compared and the audit's breaches in either run.
    ``paired``: the design the run names is the pair (``arms`` ``a`` and ``b``), path 0's seat
    taken by each arm in its own season, and both seasons' day records are compared."""
    setup = replay_setup_of(season, lines, members, scheduled, projection)
    if day not in setup.days:
        raise ValueError(f"{day} is not a day of the replayed season")
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, seed)
    digests: list[dict[tuple[date, int], dict[str, str]]] = []
    breaches: list[dict[str, Any]] = []
    for run_, these in (("recorded", lines), ("changed", other)):
        got: dict[tuple[date, int], dict[str, str]] = {}

        def keep(r: rn.DayRecord, got: dict[tuple[date, int], dict[str, str]] = got) -> None:
            got[(r.day, r.variant)] = nopeek.digest(r)

        w = rn.replay_world(
            setup,
            these,
            lag,
            seed,
            0,
            weights,
            news_sd=news_sd,
            label=label,
            forecasts=forecasts,
            split=split,
            weights_of=weights_of,
        )
        if paired:
            out = rn.paired(setup, w, arms["a"], arms["b"], seat_of(setup, 0), on_day=keep)
        else:
            out = rn.room(setup, w, arms, seats, 0, on_day=keep)
        breaches += [{"run": run_, **b} for b in out["breaches"]]
        digests.append(got)
    return nopeek.first_difference(digests[0], digests[1]), len(digests[0]), breaches


#: The span the guard gives ``replay --no-peek``: two paths of a real season take about three
#: minutes; a quarter of an hour leaves room.
NO_PEEK_HOURS = 0.25


@dataclass(frozen=True)
class SeasonRead:
    """What a replay reads for one of its seasons before any path (#172, PR D2): the season's
    lines, members and schedule, the figures of the forecasters that serve it and of the
    stand-ins (:class:`Fixed`), the run's forecasters that serve it (its cells) and why each
    other cannot, each belief label's weights, the league's shape, and the seconds the weights'
    fits took."""

    season: int
    lines: Any
    members: Any
    scheduled: Any
    fixed: Fixed
    served: tuple[fc.Forecaster, ...]
    skipped: Mapping[str, str]
    fits: Mapping[str, fitmod.LabelWeights]
    shape: policy.Shape | None
    fit_seconds: float

    @property
    def weights(self) -> dict[str, dict[str, float]]:
        return {label: dict(lw.weights.weights) for label, lw in self.fits.items()}


def cells_of(
    data: Path, season: int, named: Sequence[fc.Forecaster]
) -> tuple[Fixed, list[fc.Forecaster], dict[str, str]]:
    """The run's forecasters for one season: the figures of those that serve it, those that do
    (in order), and the reader's reason for each that does not (#172, PR D2)."""
    rates: dict[str, Mapping[int, Mapping[str, float]]] = {}
    games: Mapping[int, float] = {}
    read: tuple[int, ...] = ()
    served: list[fc.Forecaster] = []
    skipped: dict[str, str] = {}
    for f in named:
        try:
            one = fixed_of(data, season, [f])
        except reader.SimReadError as e:
            skipped[f.label] = str(e).removeprefix(f"season {season}: ")
            continue
        served.append(f)
        rates.update(one.rates)
        games = one.espn_games or games
        read = one.marcel_seasons or read
    return Fixed(rates, games, read), served, skipped


def read_season(
    data: Path,
    season: int,
    named: Sequence[fc.Forecaster],
    sources: Sources | None,
    arms: Mapping[str, rn.Arm],
    seed: int,
    shape: str,
) -> SeasonRead:
    """Everything a replay reads for ``season`` before any path. A forecaster that cannot serve
    it leaves its cell skipped; a stand-in that cannot refuses the run by name
    (``readers.SimReadError``): a system label cannot be built there."""
    lines, members, scheduled = reader.replay_lines(data, season)
    fixed, served, skipped = cells_of(data, season, named)
    if sources is not None:
        try:
            standins = fixed_of(data, season, list(sources))
        except reader.SimReadError as e:
            why = str(e).removeprefix(f"season {season}: ")
            raise reader.SimReadError(f"a stand-in cannot serve season {season}: {why}") from None
        fixed = Fixed(
            {**fixed.rates, **standins.rates},
            fixed.espn_games or standins.espn_games,
            fixed.marcel_seasons or standins.marcel_seasons,
        )
    fits: dict[str, fitmod.LabelWeights] = {}
    league = None
    took = 0.0
    if served:
        t0 = clock.perf_counter()
        fits = reader.label_weights(
            data,
            season,
            HOLD_OUT,
            list(belief_labels(served, sources, arms).values()),
            seed,
            shape,
            prior=reader.belief_weights(data, season, HOLD_OUT),
        )
        took = clock.perf_counter() - t0
        first = projection_of(served[0], fixed, lines, seed, 0, shape)
        league = replace(
            policy.shape_of(replay_setup_of(season, lines, members, scheduled, first)),
            standins=sources is not None,
        )
    return SeasonRead(
        season, lines, members, scheduled, fixed, tuple(served), skipped, fits, league, took
    )


def cells_lines(reads: Sequence[SeasonRead], named: Sequence[fc.Forecaster]) -> list[str]:
    """The cells as a small table, seasons across and forecasters down, and the reason for each
    skipped cell under it."""
    width = max(len(f.label) for f in named)
    out = ["cells (seasons across, forecasters down):"]
    out.append("  " + " " * width + "".join(f"  {r.season:>7}" for r in reads))
    for f in named:
        row = "".join(f"  {'skipped' if f.label in r.skipped else 'served':>7}" for r in reads)
        out.append(f"  {f.label:<{width}}{row}")
    for r in reads:
        for label, why in r.skipped.items():
            out.append(f"skipped: {label} in {r.season}: {why}")
    return out


def spec_hash(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def cmd_replay(args: argparse.Namespace) -> int:
    ok, why = guard(NO_PEEK_HOURS if args.no_peek else 0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    try:
        seasons = parse_seasons(args.seasons)
    except ValueError:
        print(f"refused: --seasons {args.seasons!r}: ESPN season ids, e.g. 2022,2024 or 2022-2024")
        return 2
    if not seasons:
        print("refused: --seasons names no season")
        return 2
    if HOLD_OUT in seasons:
        print(f"refused: {HOLD_OUT} is the hold-out; no run plays it")
        return 2
    twice = [t for t in dict.fromkeys(seasons) if seasons.count(t) > 1]
    if twice:
        print(f"refused: --seasons names {twice[0]} twice")
        return 2
    missing = [
        t
        for t in seasons
        if t not in reader.PERIOD_ONE or not (args.data / LOGS_DIR / f"{t}.json").is_file()
    ]
    if missing:
        print(f"refused: season {missing[0]} has no log on file under {args.data / LOGS_DIR}")
        return 2
    if args.no_peek and len(seasons) > 1:
        print(f"refused: --no-peek checks one season; --seasons names {len(seasons)}")
        return 2
    if args.news_sd < 0:
        print("refused: --news-sd is a spread in days, not below zero")
        return 2
    if (args.seats is None) == (args.arms is None):
        print(
            "refused: a replay names --seats (a room) or --arms (a pair), never both and never "
            "neither"
        )
        return 2
    if args.arms is not None and len(args.arms) != 2:
        print(f"refused: --arms names exactly two spec files, A and B, not {len(args.arms)}")
        return 2
    paired = args.arms is not None
    started = datetime.now(UTC)
    try:
        day = date.fromisoformat(args.no_peek) if args.no_peek else None
        named = fc.parse(args.forecasters)
        sources = sources_of(args.bbm_as, args.yahoo_as)
        inputs, fit, sha, fit_path = world_inputs(args.data)
        specs = read_specs(args.arms if paired else args.seats)
        made = arms_of(specs, sha)
        arms = believing(
            dict(zip(PAIR, made, strict=True)) if paired else {arm.name: arm for arm in made},
            sources,
        )
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    if len(arms) < 2:
        print("refused: a replay seats at least two arms")
        return 2
    seats = list(arms)
    if paired:
        for key, arm in arms.items():
            if str(arm.opponents.get("kind", "static")) == "market" and "rate" not in arm.opponents:
                print(
                    f"refused: arm {key.upper()} ({arm.name}) has market rivals without a rate: a "
                    "replay records no market rate, so they would never move; name "
                    "opponents.rate"
                )
                return 2
    try:
        reads = [
            read_season(args.data, t, named, sources, arms, args.seed, args.shape) for t in seasons
        ]
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    for line_ in cells_lines(reads, named):
        print(line_)
    if not any(r.served for r in reads):
        print("refused: no cell is left: no forecaster named serves any season named")
        return 2
    shapes = [r.shape for r in reads if r.shape is not None]
    same = same_seats(arms, shapes, rivals=paired)
    if same:
        print(f"refused: {same}")
        return 2
    for r in reads:
        for line_ in weights_lines(r.fits):
            print(line_.replace("belief weights, ", f"belief weights, {r.season}, ", 1))
    print(
        "belief weights fitted in "
        + ", ".join(f"{r.fit_seconds:.1f}s for {r.season}" for r in reads)
    )
    if sources is not None and all(f.label != sources[0].label for f in named):
        print(UNPROJECTED_WARNING)
    if day is not None:
        (r,) = reads
        if not r.served:
            print(f"refused: no forecaster named serves {r.season}")
            return 2
        f0 = r.served[0]
        t0 = clock.perf_counter()
        try:
            found, n, breaches = no_peek(
                r.season,
                r.lines,
                r.members,
                r.scheduled,
                projection_of(f0, r.fixed, r.lines, args.seed, 0, args.shape),
                inputs.lag,
                r.weights[f0.label],
                args.news_sd,
                arms,
                seats,
                args.seed,
                day,
                f0.label,
                forecasts_of(sources, r.fixed, r.lines, args.seed, 0, args.shape, arms),
                splits_of(sources, arms),
                r.weights,
                paired,
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
        if found is not None and found[0] <= day:
            print(
                f"FAILED: the records part on {found[0]} (variant {found[1]}, "
                f"{', '.join(found[2])}), at or before {day}"
            )
            return 1
        if found is None:
            print(f"agree through {day}; the runs never part (the change after it reached no seat)")
        else:
            print(f"agree through {day}; first difference on {found[0]} ({', '.join(found[2])})")
        return 0
    workers = args.workers or rn.workers_default()
    paths = args.paths
    if paired:
        paths = paths_for_pair(args.paths)
        if paths != args.paths:
            print(
                f"--paths {args.paths} rounded up to {paths}, a multiple of the league's "
                f"{rn.REPLAY_TEAMS} seats, so every seat is taken equally often in every cell"
            )
    task = task_paired if paired else task_replay
    tasks = [
        (
            r.season,
            r.lines,
            r.members,
            r.scheduled,
            f,
            r.fixed,
            args.shape,
            sources,
            inputs.lag,
            r.weights,
            args.news_sd,
            arms,
            PAIR if paired else seats,
            args.seed,
            p,
        )
        for r in reads
        for f in r.served
        for p in range(paths)
    ]
    keys = [
        {"season": r.season, "forecaster": f.label, "path": p}
        for r in reads
        for f in r.served
        for p in range(paths)
    ]
    cells = sum(len(r.served) for r in reads)
    t0 = clock.perf_counter()
    first_run = task(*tasks[0])
    one = clock.perf_counter() - t0
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else estimate_hours(one, len(tasks), workers)
    )
    print(
        f"{len(tasks)} tasks ({cells} cells x {paths} paths), one took {one:.1f}s, about {hours:.2f} h on {workers} workers"
    )
    if args.dry_run:
        return dry_run(keys[0], first_run)
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    results = [first_run, *rn.run_tasks(task, tasks[1:], workers)]
    keep, note = audited(keys, results)
    keys = [k for k, ok_ in zip(keys, keep, strict=True) if ok_]
    results = [r for r, ok_ in zip(results, keep, strict=True) if ok_]
    run_name = args.name or "replay-" + "-".join(str(t) for t in seasons)
    payload = base_payload("replay", run_name, started, sha, fit_path, fit, workers, arms)
    payload |= replay_notes({str(r.season): r.fits for r in reads}, args.news_sd)
    payload |= {
        "seasons": seasons,
        "cells": {
            str(r.season): {
                f.label: {"served": f.label not in r.skipped, "reason": r.skipped.get(f.label)}
                for f in named
            }
            for r in reads
        },
        "design": "paired" if paired else "room",
        "specs": dict(zip(seats, specs, strict=True)),
        "draft": (
            f"snake on the run's forecaster's projection, over {payload['pool']['draft']}; an "
            "arm on a forecaster of its own reads it from the season's first day, not at the "
            "draft"
        ),
        "forecasters": {
            str(r.season): forecasters_block(
                r.served, r.fixed, r.lines, args.seed, args.shape, sources, r.fits
            )
            for r in reads
        },
        "oracle_shape": args.shape,
        "sources": None
        if sources is None
        else {
            str(r.season): sources_block(sources, arms, r.fixed, r.lines, args.seed, args.shape)
            for r in reads
        },
        "beliefs": {name: arm.forecaster or "the run's forecaster" for name, arm in arms.items()},
        "players": {
            str(r.season): sum(1 for k in r.members if r.scheduled.get(k) or r.lines.get(k))
            for r in reads
        },
        "paths": paths,
        "seed": args.seed,
        "solves": sum(res["solves"] for res in results),
        "shape": {str(r.season): r.shape.label() for r in reads if r.shape is not None},
        "reads": reads_of(arms, shapes, rivals=paired),
        "audit": note,
        "confirmation": None,
    }
    if paired:
        payload |= paired_blocks(keys, results, arms, paths)
        payload["verdict"] = verdict_block(payload, named, seasons, sources, note)
    else:
        payload |= room_blocks(keys, results, seats)
        if sources is not None:
            payload["result_is"] = ROOM_RESULT
    look = None
    if CONFIRMATION in seasons:
        look, ledger = reader.append_look(
            args.data,
            {
                "started_at": payload["started_at"],
                "name": run_name,
                "design": payload["design"],
                "seasons": seasons,
                "forecasters": [f.label for f in named],
                "specs": {arm: spec_hash(spec) for arm, spec in zip(seats, specs, strict=True)},
                "fit_sha": sha,
                "code_sha": payload["code_sha"],
            },
        )
        payload["confirmation"] = {
            "season": CONFIRMATION,
            "look": look,
            "ledger": str(ledger),
            "note": CONFIRMATION_NOTE,
        }
    path = finish(payload, args.data, False)
    if paired:
        for line_ in verdict_lines(payload["verdict"]):
            print(line_)
    room_results = {} if paired else payload["results"]
    for t, by_label in room_results.items():
        for label, d in by_label.items():
            for arm, agg in d.items():
                m = agg["made_playoffs"]
                print(
                    f"{t} {label} {arm}: playoff odds {m['mean']:.3f} (SE {m['se'] if m['se'] is None else round(m['se'], 3)}) over {m['n']} paths"
                )
    if look is not None:
        print(f"confirmation season {CONFIRMATION}: look {look}, appended to {ledger}")
    print(f"written: {path}")
    return audit_exit(note)


#: Whose result a ``system`` difference is, by design (#172, PR D2).
PAIR_RESULT = (
    "under --arms a system difference is the one seat's, against rivals on the run's forecaster"
)
ROOM_RESULT = (
    "under --seats a system difference is a room's result: an arm's outcome moves with the seats "
    "it shares the room with"
)
SE_NOTE = (
    "the SE in a cell is over its paths (the seat and the draws: told return dates, market "
    "rivals' draws, an oracle's draw), not over the season's own chance: one recorded season is "
    "one draw of the world; the SE in the pooled column is over the season means, the seasons "
    "the clusters"
)
FADES_NOTE = (
    "both stand-ins learn from the same played games, so a system difference fades through the "
    "season, where the live sources stay apart all year"
)


def verdict_block(
    payload: Mapping[str, Any],
    named: Sequence[fc.Forecaster],
    seasons: Sequence[int],
    sources: Sources | None,
    note: Mapping[str, Any],
) -> dict[str, Any]:
    """The pair's verdict by forecaster and season (``run.replay_verdict``) from its payload's
    figures, with the sentences its text says every time: what each SE is over, how many paths
    of each cell are distinct when fewer than all, the rivals and whom they believe, and with
    stand-ins named that a system difference fades and whose result it is."""
    ts = [str(t) for t in seasons]
    results = payload["results"]
    cells = {
        f.label: {t: (results.get(t) or {}).get(f.label, {}).get("difference") for t in ts}
        for f in named
    }
    frozen = {
        label: [
            t
            for t in ts
            if ((payload["forecasters"].get(t) or {}).get(label) or {})
            .get("freeze", {})
            .get("flagged")
        ]
        for label in cells
    }
    v = rn.replay_verdict(
        cells,
        ts,
        yardsticks=[f.label for f in named if f.name == "oracle"],
        frozen=frozen,
        voided=int(note["paths_voided"]),
    )
    repeats = [
        f"{t} {label}: {c['distinct']} of {c['paths']} paths distinct"
        for t, by_label in results.items()
        for label, c in by_label.items()
        if c["distinct"] < c["paths"]
    ]
    rivals = payload["rivals"]
    notes = [
        SE_NOTE,
        *(["distinct paths: " + "; ".join(repeats)] if repeats else []),
        (
            f"rivals: arm A's {json.dumps(rivals['a'], sort_keys=True)}, arm B's "
            f"{json.dumps(rivals['b'], sort_keys=True)}; they believe the run's forecaster"
        ),
    ]
    if sources is not None:
        notes += [FADES_NOTE, PAIR_RESULT]
    return v | {"notes": notes}


def verdict_lines(v: Mapping[str, Any]) -> list[str]:
    """The verdict as printed: the table (one row a forecaster, one column a season and the
    pooled column, each figure in points of playoff odds with its SE, "n/a" for a skipped cell),
    the marks under it, the notes, then the verdict's line."""

    def pp(mean: Any, se: Any) -> str:
        if mean is None:
            return "n/a"
        return f"{100 * mean:+.1f} ({'n/a' if se is None else f'{100 * se:.1f}'})"

    seasons = list(v["seasons"])
    width = max([len("forecaster"), *(len(x) + 4 for x in v["rows"])])
    out = ["playoff odds, B less A, in points (SE):"]
    out.append(
        f"  {'forecaster':<{width}}"
        + "".join(f"  {t:>14}" for t in seasons)
        + "  "
        + f"{'pooled':>14}"
    )
    used: set[str] = set()
    for label, row in v["rows"].items():
        name = label + (" [y]" if row["mark"] else "")
        if row["mark"]:
            used.add(row["mark"])
        figures = []
        for t in seasons:
            c = row["cells"][t]
            text = pp(c["mean"], c["se"]) if c["mark"] != rn.SKIPPED else "n/a"
            if c["mark"] == rn.FREEZE:
                text += " [f]"
            if c["mark"]:
                used.add(c["mark"])
            figures.append(f"  {text:>14}")
        p = row["pooled"]["made_playoffs"]
        out.append(f"  {name:<{width}}" + "".join(figures) + f"  {pp(p['mean'], p['se']):>14}")
    for label, row in v["rows"].items():
        p = row["pooled"]["made_playoffs"]
        if p["seasons"] < p["of"] or p["seasons"] == 1:
            out.append(f"  {label} pooled: {p['note']}")
    tags = {rn.YARDSTICK: "[y]", rn.FREEZE: "[f]", rn.SKIPPED: "n/a"}
    for mark in (rn.YARDSTICK, rn.FREEZE, rn.SKIPPED):
        if mark in used:
            out.append(f"  {tags[mark]} {v['marks'][mark]}")
    out += [f"note: {n}" for n in v["notes"]]
    if v["passes"] is None:
        verdict = v["why"]
    else:
        verdict = "holds" if v["passes"] else "does not hold: " + "; ".join(v["failed"])
    out.append(f"verdict ({v['rule']}, advisory): {verdict}")
    return out


def room_blocks(
    keys: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]], seats: Sequence[str]
) -> dict[str, Any]:
    """A room's figures, keyed by season and then by forecaster: each arm's outcomes and counts
    pooled over its seats and the paths that stand, each arm's season scale by season, the
    unprojected count by cell."""
    by_cell: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
    counts_by_cell: dict[str, dict[str, dict[str, list[Any]]]] = {}
    unprojected: dict[str, dict[str, list[Any]]] = {}
    scales: dict[str, dict[str, list[Any]]] = {}
    for key, res in zip(keys, results, strict=True):
        t, label = str(key["season"]), key["forecaster"]
        for arm, row in res["scale"].items():
            scales.setdefault(t, {}).setdefault(arm, []).append(row)
        for arm, metrics in res["by_arm"].items():
            by_cell.setdefault(t, {}).setdefault(label, {}).setdefault(arm, []).append(metrics)
        for arm, row in res["counts"].items():
            counts_by_cell.setdefault(t, {}).setdefault(label, {}).setdefault(arm, []).append(row)
        unprojected.setdefault(t, {}).setdefault(label, []).append(res["unprojected"])
    return {
        "seats": list(seats),
        "rotation": "seat i takes arm (i + path) mod n",
        "results": {
            t: {
                label: {arm: rn.aggregate(rows) for arm, rows in d.items()}
                for label, d in by_label.items()
            }
            for t, by_label in by_cell.items()
        },
        "season_scale": {
            "note": SCALE_NOTE,
            "by_season": {
                t: {arm: scale_of(rows) for arm, rows in d.items()} for t, d in scales.items()
            },
        },
        "counts": {
            "note": COUNTS_NOTE,
            "rivals": None,
            "by_season": {
                t: {
                    label: {arm: counts_of(rows) for arm, rows in d.items()}
                    for label, d in by_label.items()
                }
                for t, by_label in counts_by_cell.items()
            },
        },
        "unprojected": {
            "note": UNPROJECTED_NOTE,
            "by_season": {
                t: {label: unprojected_of(rows) for label, rows in d.items()}
                for t, d in unprojected.items()
            },
        },
    }


#: The paired design's two arms, A and B, as the payload keys them.
PAIR = ("a", "b")
SEAT_RULE = (
    "path p puts arm A in seat teams[p mod 12] in one season and arm B in the same seat in a "
    "second, through one world; the paths are a multiple of the twelve seats, so every seat is "
    "taken equally often in every cell"
)
RIVALS_NOTE = (
    "the eleven other seats are each arm's opponents block and believe the run's forecaster, "
    "whatever the arm believes; until PR D4 a market rival's view is the run's forecaster's "
    "draft-day ranking, the same all season"
)
DISTINCT_NOTE = (
    "paths repeat when nothing is drawn (the season's games are the same on every path): two "
    "paths are one when their seat, both arms' metrics and both arms' mechanism counts (the "
    "moves landed among them) agree; an SE over repeated paths is over copies"
)


def distinct(rows: Sequence[Mapping[str, Any]]) -> int:
    """How many of a cell's paired paths are distinct, by the seat, both arms' metrics and both
    arms' mechanism counts (:data:`DISTINCT_NOTE`)."""
    return len(
        {
            json.dumps(
                [r["seat"], r["a"], r["b"], r["counts"]["a"], r["counts"]["b"]],
                sort_keys=True,
                default=str,
            )
            for r in rows
        }
    )


def paired_blocks(
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    arms: Mapping[str, rn.Arm],
    paths: int,
) -> dict[str, Any]:
    """The pair's figures, keyed by season and then by forecaster: each arm's outcomes, the
    difference (B less A) over the paths that stand with how many are distinct, the counts by
    arm and for the rivals, each arm's season scale by season, the unprojected count by cell and
    arm, the seat rule and each path's seat, and the rivals each arm faced."""
    rows: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    scales: dict[str, dict[str, list[Any]]] = {}
    for key, res in zip(keys, results, strict=True):
        t, label = str(key["season"]), key["forecaster"]
        rows.setdefault(t, {}).setdefault(label, []).append(res)
        for side in PAIR:
            scales.setdefault(t, {}).setdefault(side, []).append(res["scale"][side])

    def cell(rs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "a": rn.aggregate([r["a"] for r in rs]),
            "b": rn.aggregate([r["b"] for r in rs]),
            "difference": rn.aggregate([r["delta"] for r in rs]),
            "paths": len(rs),
            "distinct": distinct(rs),
        }

    return {
        "arms": {side: arms[side].name for side in PAIR},
        "seat": {
            "rule": SEAT_RULE,
            "by_path": [p % rn.REPLAY_TEAMS + 1 for p in range(paths)],
        },
        "rivals": {
            **{side: dict(arms[side].opponents) for side in PAIR},
            "note": RIVALS_NOTE,
        },
        "distinct_note": DISTINCT_NOTE,
        "difference": "b less a",
        "results": {t: {label: cell(rs) for label, rs in d.items()} for t, d in rows.items()},
        "season_scale": {
            "note": SCALE_NOTE,
            "by_season": {
                t: {side: scale_of(rs) for side, rs in d.items()} for t, d in scales.items()
            },
        },
        "counts": {
            "note": COUNTS_NOTE,
            "rivals": "the seats other than the pair's, both arms' seasons, as one row",
            "by_season": {
                t: {
                    label: {
                        side: counts_of([r["counts"][side] for r in rs])
                        for side in (*PAIR, "rivals")
                    }
                    for label, rs in d.items()
                }
                for t, d in rows.items()
            },
        },
        "unprojected": {
            "note": UNPROJECTED_NOTE,
            "by_season": {
                t: {
                    label: {
                        side: unprojected_of([r["unprojected"][side] for r in rs]) for side in PAIR
                    }
                    for label, rs in d.items()
                }
                for t, d in rows.items()
            },
        },
    }


# --------------------------------------------------------------------------- validate
def gate_dict(g: vg.Gate) -> dict[str, Any]:
    return {"name": g.name, "passed": g.passed, "season": g.season, "detail": g.detail}


#: The forecaster gate 5's replay is drafted on and believes by, when ``--forecaster`` names none.
GATE_FORECASTER = "prior"
#: An oracle's error shape in gate 5's replay (a run of ``replay`` sets it with ``--shape``).
GATE_SHAPE = "stat"


def gate_seats(teams: Sequence[int]) -> tuple[int, ...]:
    """Gate 5's seats: the first, the middle (the lower of two) and the last of the draft order."""
    return tuple(dict.fromkeys((teams[0], teams[(len(teams) - 1) // 2], teams[-1])))


def gate_season(data: Path) -> int | None:
    """The latest season a replay can play that a gate may look at: a cached, dated log, neither
    the hold-out nor the confirmation season. None when there is none."""
    on_file = reader.seasons_on_file(data, max(reader.PERIOD_ONE) + 1)
    return max((t for t in on_file if t not in (HOLD_OUT, CONFIRMATION)), default=None)


def season_refused(data: Path, season: int) -> str | None:
    """Why gate 5 may not replay ``season``: the hold-out (refused as the replay refuses it), the
    confirmation season (a gate needs no look at it), or a season with no dated log on file."""
    if season == HOLD_OUT:
        return f"{HOLD_OUT} is the hold-out; no run plays it"
    if season == CONFIRMATION:
        return f"{CONFIRMATION} is the confirmation season; a gate needs no look at it"
    if season not in reader.PERIOD_ONE or not (data / LOGS_DIR / f"{season}.json").is_file():
        return f"season {season} has no log on file under {data / LOGS_DIR}"
    return None


def gate_surrogate(
    data: Path, season: int, f: fc.Forecaster, lag: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Gate 5 on a replay (#172, PR D3): the league, the belief's weights and the world built as
    ``replay`` builds them for ``season`` and forecaster ``f`` (:func:`read_season`,
    :func:`replay_setup_of`, ``run.replay_world`` at the label's own weights), path 0; on each of
    the :data:`GATE_DAYS` after the first simulated day, for each of :func:`gate_seats`, whether
    the surrogate's set equals the exact set from day one's rosters (``checks.surrogate_matches``),
    at the knobs' defaults (``policy.KNOB_DEFAULTS``) and the fields' (``policy.DEFAULT_FIELDS``).
    One gate row a seat, and the block that names what the gate ran on. Refused
    (``readers.SimReadError``) when ``f`` cannot serve the season."""
    r = read_season(data, season, [f], None, {}, seed, GATE_SHAPE)
    if not r.served:
        raise reader.SimReadError(f"{f.label} cannot serve {season}: {r.skipped[f.label]}")
    projection = projection_of(f, r.fixed, r.lines, seed, 0, GATE_SHAPE)
    setup = replay_setup_of(season, r.lines, r.members, r.scheduled, projection)
    w = rn.replay_world(
        setup, r.lines, lag, seed, 0, r.weights[f.label], label=f.label, weights_of=r.weights
    )
    first = rn.first_day(setup)
    days = (
        []
        if first is None
        else [first + timedelta(d) for d in GATE_DAYS if first + timedelta(d) <= setup.season_end]
    )
    knobs = policy.check_knobs(dict(policy.KNOB_DEFAULTS))
    fields = policy.DEFAULT_FIELDS
    seats = gate_seats(setup.teams)
    rows = []
    for seat in seats:
        matches = checks.surrogate_matches(setup, w, seat, days, knobs, fields)
        g = vg.surrogate_gate(matches, season=season)
        g.detail.update({"seat": seat, "days": [d.isoformat() for d in days]})
        rows.append(gate_dict(g))
    block = {
        "season": season,
        "forecaster": f.label,
        "shape": GATE_SHAPE,
        "seats": list(seats),
        "seats_rule": "the first, the middle and the last of the draft order",
        "days": [d.isoformat() for d in days],
        "path": 0,
        "knobs": knobs,
        "fields": fields.payload(),
        "weights": r.fits[f.label].payload(),
        "rule": (
            f"a seat passes when the surrogate's set equals the exact set on "
            f"{vg.SURROGATE_NEEDED} of its {vg.SURROGATE_OF} league-days; the gate passes when "
            "every seat does"
        ),
    }
    return rows, block


def cmd_validate(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    started = datetime.now(UTC)
    season = args.season if args.season is not None else gate_season(args.data)
    if season is None:
        print(f"refused: no replayable season on file under {args.data / LOGS_DIR}")
        return 2
    why = season_refused(args.data, season)
    if why:
        print(f"refused: {why}")
        return 2
    try:
        forecaster = fc.parse_one(args.forecaster)
        inputs, fit, sha, fit_path = world_inputs(args.data)
    except (reader.SimReadError, ValueError, OSError) as e:
        print(f"refused: {e}")
        return 2
    t0 = clock.perf_counter()
    try:
        surrogate, block = gate_surrogate(args.data, season, forecaster, inputs.lag, args.seed)
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    took = clock.perf_counter() - t0
    gates = surrogate
    payload = base_payload("validate", args.name or "validate", started, sha, fit_path, fit, 1)
    payload |= {
        "seed": args.seed,
        "surrogate_gate": block,
        "gates": gates,
        "passed": all(g["passed"] for g in gates) and bool(gates),
    }
    path = finish(payload, args.data, args.dry_run)
    for g in gates:
        d = g["detail"]
        state = "passed" if g["passed"] else "FAILED"
        print(
            f"{g['name']:16} {g['season']!s:12} {state} seat {d['seat']}: "
            f"{d['matched']} of {d['of']} league-days"
        )
    days = len(block["days"]) * len(block["seats"])
    print(
        f"gate 5 on a replay of {block['season']} drafted on {block['forecaster']}: {days} "
        "league-days "
        f"({len(block['seats'])} seats x {len(block['days'])} days) in {took:.1f}s"
    )
    print(f"written: {path}" if path else "dry run, nothing written")
    return 0


# --------------------------------------------------------------------------- main
def _run_args(p: argparse.ArgumentParser, paths: int) -> None:
    p.add_argument("--paths", type=int, default=paths, help=f"paths a cell (default {paths})")
    p.add_argument("--seed", type=int, default=1, help="the run's seed (default 1)")
    p.add_argument("--workers", type=int, default=None, help="processes (default cores less two)")
    p.add_argument("--name", default=None, help="the run's name in its payload and file")
    p.add_argument("--expected-hours", type=float, default=None, help="override the estimate")
    p.add_argument("--announced", action="store_true", help="the run over an hour was announced")
    p.add_argument("--dry-run", action="store_true", help="estimate and write nothing")


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
    fi.set_defaults(func=cmd_fit)
    re_ = sub.add_parser("replay", help="a made-up league on a recorded season's lines")
    re_.add_argument(
        "--seasons",
        required=True,
        help=f"ESPN season ids, e.g. 2024 or 2022,2023,2024 or 2022-2024; never {HOLD_OUT}",
    )
    re_.add_argument(
        "--forecasters",
        default="prior",
        help="the run's forecasters, comma separated: prior, espn, marcel, oracle:<spread> "
        "(default prior)",
    )
    re_.add_argument(
        "--shape",
        choices=fc.SHAPES,
        default="stat",
        help="an oracle's error: stat, a draw a player and stat; minutes, a share of it common to "
        "the player's stats (default stat)",
    )
    re_.add_argument(
        "--seats", type=Path, nargs="+", default=None, help="a room: the arms' spec files"
    )
    re_.add_argument(
        "--arms",
        type=Path,
        nargs="+",
        default=None,
        metavar="SPEC",
        help="the paired design: arm A's and arm B's spec files, B less A",
    )
    re_.add_argument(
        "--bbm-as",
        default=None,
        metavar="FORECASTER",
        help="the forecaster standing in for the first live source (system bbm); with --yahoo-as",
    )
    re_.add_argument(
        "--yahoo-as",
        default=None,
        metavar="FORECASTER",
        help="the forecaster standing in for the second live source (system yahoo); with --bbm-as",
    )
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
        help="check one path of one season against it changed after this date; writes nothing",
    )
    _run_args(re_, paths=20)
    re_.set_defaults(func=cmd_replay)
    va = sub.add_parser("validate", help="gate 5: the surrogate against the exact set on a replay")
    va.add_argument(
        "--season",
        type=int,
        default=None,
        help="gate 5's replayed season, an ESPN season id (default the latest replayable on file; "
        f"never {HOLD_OUT} or {CONFIRMATION})",
    )
    va.add_argument(
        "--forecaster",
        default=GATE_FORECASTER,
        help=f"gate 5's replay's forecaster (default {GATE_FORECASTER})",
    )
    va.add_argument("--seed", type=int, default=1)
    va.add_argument("--name", default=None)
    va.add_argument("--dry-run", action="store_true", help="run the gate, write nothing")
    va.set_defaults(func=cmd_validate)
    args = ap.parse_args(argv)
    dry = getattr(args, "dry_run", False)
    if args.command in SIMULATING and not dry and hash_seed() == "random":
        print(HASH_SEED_NOTE, file=sys.stderr)
    return args.func(args)
