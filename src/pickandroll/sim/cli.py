"""SEASON SIM (#172): the season simulator's commands, for the terminal.

    python -m pickandroll.sim fetch-logs --seasons 2022-2026   # ESPN's per-game logs, cached
    python -m pickandroll.sim fit                              # the world's fit, frozen with a hash
    python -m pickandroll.sim fit --dry-run                    # the fit printed, nothing written
    python -m pickandroll.sim fit-bids                         # the rivals' price book, with a hash
    python -m pickandroll.sim replay --seasons 2022-2024 --forecasters prior,espn --seats A.json B.json
    python -m pickandroll.sim replay --seasons 2022-2024 --forecasters prior,espn --arms A.json B.json
    python -m pickandroll.sim replay --seasons 2024 --forecasters oracle:0.1 --shape minutes ...
    python -m pickandroll.sim replay --seasons 2024 --bbm-as espn --yahoo-as marcel --seats ...
    python -m pickandroll.sim replay --seasons 2024 --seats A.json B.json --no-peek 2023-12-04
    python -m pickandroll.sim validate --season 2024 --forecaster prior
    python -m pickandroll.sim screen --arm BASE.json --seasons 2024 [--levers pool min_gain]

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
the hold-out, the spec files verbatim and the execution model. ``screen`` nudges each lever of a
fixed list once against a baseline arm (``sim/screen.py``), plays every pair as ``replay --arms``
plays one, never on the hold-out or the confirmation season, and writes a folder under
``data/sim/screens/``: a record a pair and the screen's own, so a screen stopped between two
pairs is taken up again by the same command.

Every command runs through :func:`guard`: at low priority (``nice``), never when its span would
touch 04:45-06:45 in the machine's local time (the routines' window), never while a draft room is
open on the API, and a run expected over an hour is announced on the tracker and starts on the
user's word (``--announced`` says that has happened).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
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

from . import adp, audit, bids, checks, gamelogs, nopeek, policy, shapes, world
from . import counts as ct
from . import fit as fitmod
from . import forecast as fc
from . import readers as reader
from . import run as rn
from . import screen as sc
from . import validate as vg
from .engine import EACH_CATEGORY, ONE_WIN, mv, wk

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


# --------------------------------------------------------------------------- the price book (PR Fd)
def describe_book(book: Mapping[str, Any]) -> str:
    """A price book in a few lines, for the terminal (its figures stay under ``data/``)."""
    prices = bids.prices_of(book)
    total = sum(n for _, n in prices)
    zero = sum(n for s, n in prices if s == 0)
    adds = book["adds"]

    def x(v: Any) -> str:
        return "none" if v is None else f"{v:.3g}"

    head = (
        f"book: {book['rows_kept']} rivals' winning bids of {book['rows_read']} rows, "
        f"{len(book['leagues'])} leagues, claims {book['first_claim']} to {book['last_claim']}, "
        f"table sha256 {book['table_sha256']}"
    )
    shares = (
        f"prices (shares of the budget): {len(prices)} distinct, {zero} of {total} at $0, the "
        f"median {x(bids.quantile(prices, 0.5))}, the top {x(prices[-1][0])}"
    )
    weeks = (
        f"adds ({adds['unit']}): {adds['weeks']} whole league-weeks, the median "
        f"{x(adds['median'])}, the quartiles {x(adds['q1'])} and {x(adds['q3'])}"
    )
    ours = f"ours: {book['ours']['won']} won, {book['ours']['lost']} lost"
    return f"{head}\n{shares}\n{weeks}\n{ours}"


def cmd_fit_bids(args: argparse.Namespace) -> int:
    """The price book from the winning-bids table (``bids.book_of``), written as the fit is:
    ``data/sim/bids/<date>/book.json`` with ``book.sha256`` beside it. It reads no game log, so no
    season is involved; the table's hash is checked first and only ``bids.READ`` is read."""
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    try:
        rows, table_sha, _ = reader.bids_rows(args.data)
        book = bids.book_of(rows, table_sha)
    except (reader.SimReadError, bids.BookError) as e:
        print(f"refused: {e}")
        return 2
    sha = reader.fit_hash(book)
    print(describe_book(book))
    if args.dry_run:
        print(f"sha256 {sha} (dry run, nothing written)")
        return 0
    out = args.data / reader.BIDS_DIR / datetime.now(UTC).date().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "book.json").write_text(json.dumps(book, indent=1, sort_keys=True))
    (out / "book.sha256").write_text(sha + "\n")
    print(f"written: {out / 'book.json'} sha256 {sha}")
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
SIMULATING = ("replay", "validate", "screen")
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
    executions: str = EXECUTIONS,
    measure: str | None = None,
    book: tuple[Mapping[str, Any], str, Path] | None = None,
) -> dict[str, Any]:
    """The payload's common part. ``arms`` by their key in the payload (``a`` and ``b`` in a
    pair, the names in a room): each arm's fields and its surrogate's pool and days; none
    (validate) for the live route's, the surrogate gate's. ``executions``, the run's execution
    model (``policy.executions_of`` its waivers, PR Fa, and its waiver rule, PR Fc); ``measure``, what the run's format gives
    a seat that weighs (``policy.measure``, the format PR; a replay's, beside it); ``book``, the
    price book its rivals bid on (``readers.newest_book``, PR Fd): its hash, its file and its
    table's hash beside the fit's, in a run that names it only. An arm's ``fields`` carry its
    guard and its stake (the guard PR) when its spec names them, and only then."""
    fields = {k: arm.fields for k, arm in (arms or {}).items()} or {"gate": policy.Fields()}
    season = {k: arm.season_payload() for k, arm in (arms or {}).items()}
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
        **(
            {
                "book_sha": book[1],
                "book_file": str(book[2]),
                "book_table_sha256": book[0].get("table_sha256"),
            }
            if book is not None
            else {}
        ),
        "hold_out": fit.get("hold_out", HOLD_OUT),
        "executions": executions,
        **({"measure": measure} if measure is not None else {}),
        "fields": {k: f.payload() | season.get(k, {}) for k, f in fields.items()},
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
#: What each claim count is (PR Fa): a waiver run's only, beside :data:`COUNTS_NOTE`.
CLAIMS_NOTE = {
    "claims_placed": "waiver claims placed",
    "claims_won": "claims won: the seat had the best priority among the claims open that morning",
    "claims_lost": "claims lost: a team with better priority took the player",
    "claims_failed": "claims won the roster could not take (the drop gone, no spot open)",
    "claims_behind": "claims decided with a team ahead of the seat in the order",
    "claims_behind_lost": "of those, the claims lost",
}


#: What the claim counts are in a FAAB run (PR Fb), where a bid decides first: the notes of
#: :data:`CLAIMS_NOTE` it says otherwise.
FAAB_CLAIMS_NOTE = {
    "claims_won": "claims won: the highest bid that could be taken, a tie to the better priority",
    "claims_lost": "claims lost: another claim took the player, on a higher or an equal bid",
    "claims_behind": "claims decided with a claim on the player ahead of it (the winner's, or one "
    "that failed)",
}
#: What each bid count is (PR Fb): a FAAB run's only, after the claims'. The world knows every
#: bid, so these are exact; no decision reads them.
BIDS_NOTE = {
    "dollars_spent": "dollars paid for won claims over the season",
    "dollars_left": "dollars left at the season's end",
    "claims_won_free": "claims won at $0",
    "claims_lost_bid": "claims lost to a higher bid",
    "claims_lost_tie": "claims lost on a tie, to a better priority",
    "claims_won_alone": "claims won with no other claim on the player that morning",
    "bid_over_next": "dollars won claims paid above the next bid that could have been taken (the "
    "whole bid when there was none): the world's knowledge, not the seat's",
    "bid_short": "dollars lost claims fell short of the winning bid by: the world's knowledge",
}


#: What the guard's and the stake's counts are (the guard PR), by the arm field whose naming
#: brings them (``counts.SEASON``): a run's in which an arm names that field, on its arms' seats.
SEASON_NOTE = {
    "guard": {
        "sets_past_guard": "sets the seat decided that the season guard would have refused (the "
        "rest of the season below 0 by the engine's own figure), before the day's cap and the "
        "week's adds cut them: 0 for an arm on the block, by construction; an arm with the "
        "guard off shows how often the block would bind",
    },
    "stake": {
        "stake_mean": "the week's stake L for the seat, its mean over the weeks played (the "
        "standings it reads are the arm's own season's; an arm's stake field does not change "
        "what L is, only whether its weight reads it)",
        "stake_weeks_above_half": "the weeks whose stake L was above a half",
    },
}


def counts_note(waivers: str = "none", counted: Sequence[str] = ()) -> dict[str, str]:
    """The counts' note for a run under ``waivers``: :data:`COUNTS_NOTE`, the claims' too in a
    waiver run, and in a FAAB run the bids' with the claims' said for bids; then the notes of
    the season fields the run's arms name (``counted``, ``run.counted_of``; :data:`SEASON_NOTE`),
    none for a run that names neither."""
    if waivers == "none":
        note = COUNTS_NOTE
    elif waivers == "faab":
        note = {**COUNTS_NOTE, **CLAIMS_NOTE, **FAAB_CLAIMS_NOTE, **BIDS_NOTE}
    else:
        note = {**COUNTS_NOTE, **CLAIMS_NOTE}
    if not counted:
        return note
    return {**note, **{k: v for f in counted for k, v in SEASON_NOTE[f].items()}}


def audited(
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    rules: Sequence[audit.Rule] | None = None,
) -> tuple[list[bool], dict[str, Any]]:
    """Which tasks stand and the payload's audit block. A task with a breach is a voided path: it
    is left out of every aggregate, and each breach is listed with the task it voids. ``rules``,
    the rules the run was held to (``audit.rules_of`` its waivers and its waiver rule; :data:`audit.RULES` by
    default)."""
    keep = [not r.get("breaches") for r in results]
    return keep, {
        "rules": audit.names(rules),
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


def dry_run(
    key: Mapping[str, Any],
    first: Mapping[str, Any],
    rules: Sequence[audit.Rule] | None = None,
) -> int:
    """A dry run's one task: its counts and season scale by arm and its audit printed, nothing
    written. A breach in it exits with :data:`AUDIT_EXIT` all the same: a dry run is a run the
    audit reads too (``rules``, as :func:`audited`)."""
    for arm, row in (first.get("counts") or {}).items():
        if row:
            shown = ", ".join(
                f"{m} {row[m]:.4g}" for m in ct.metrics_in([row]) if row.get(m) is not None
            )
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
    if "drafted_unprojected" in first:
        print(
            f"draft market, the first task: {first['drafts']} draft(s), "
            f"{', '.join(str(n) for n in first['drafted_unprojected'])} drafted player(s) the "
            "run's forecaster does not project"
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
    _, note = audited([key], [first], rules)
    print("dry run, nothing written")
    return audit_exit(note)


def counts_of(rows: Sequence[Any]) -> dict[str, Any] | None:
    """The counts of the paths that stand, pooled like the outcomes; None without a row."""
    have = [r for r in rows if r is not None]
    return rn.aggregate(have, ct.metrics_in(have)) if have else None


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


#: What the season scale's gain is in a points league (#172, PR Fa: D4c's points runs).
SCALE_NOTE_POINTS = (
    " In this points league the gain is in expected matchups won on the week's fantasy points: "
    "each week's chance of outscoring the opponent (a later week's the mean over the field), "
    "summed over the key's weeks."
)


#: What the season scale's gain is in a one-win league (#172, the format PR), whatever the seats.
SCALE_NOTE_ONE_WIN = (
    " In this league, which counts one win per matchup, the gain is in the matchup's win odds: "
    "each week's chance of winning the matchup (a later week's the mean over the field), summed "
    "over the key's weeks, not its expected categories; so the ratio is in odds, and a "
    "season_weight set in one format is not the other's."
)


def scale_note(scoring: str = "categories", h2h: str = ONE_WIN) -> str:
    """The season scale's note for a run that scores by ``scoring`` in the head-to-head format
    ``h2h``: a points run's and a one-win run's say what the gain is there; a run that counts
    every category has :data:`SCALE_NOTE` as it was."""
    if scoring == "points":
        return SCALE_NOTE + SCALE_NOTE_POINTS
    return SCALE_NOTE + SCALE_NOTE_ONE_WIN if h2h == ONE_WIN else SCALE_NOTE


def scale_of(rows: Sequence[Mapping[str, Any] | None]) -> dict[str, Any] | None:
    """The season scale of the paths that stand: the mean of each figure over the paths that
    have it, the paths that have a row (``paths``) and, of those, the paths whose row holds a
    ratio (``paths_with_ratio``: what the ratio's mean rests on; a seat with no feasible swap
    on its first day, or none that has a ``ROS_w``, or whose ``ROS_w`` have a median size of 0,
    has a row and no ratio); None when no path has a row (the ranking tier, a static seat)."""
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
        "paths_with_ratio": sum(1 for r in have if r.get("ratio") is not None),
    }


def reads_of(
    arms: Mapping[str, rn.Arm], shapes: Sequence[policy.Shape], rivals: bool
) -> dict[str, Any]:
    """The reads table by arm and by each shape of the run: each knob and field ``read`` or the
    reason it is not (``policy.reads``, ``policy.field_reads``), an arm's guard and stake among
    its fields when its spec names them (``policy.season_reads``, the guard PR)."""
    out: dict[str, Any] = {}
    for key, arm in arms.items():
        mirror = rivals and rn.mirrored(arm)
        out[key] = {
            shape.label(): {
                "knobs": policy.reads(arm, shape, mirror),
                "fields": policy.field_reads(arm, mirror)
                | {k: v for k, v in policy.season_reads(arm, shape).items() if k in arm.named},
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


def replay_setup_of(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    projection: Any,
    draft: adp.Draft | None = None,
    league: shapes.LeagueShape = shapes.FIXED,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> Any:
    """A replay's league in one path, drafted on the run's forecaster's ``projection``, or on a
    table of average draft positions (``draft``, #172, PR D4a), in the path's league shape
    (``league``, #172, PR D4b; the fixed shape by default) under the run's league rules
    (``league_rules``, PR D4c: the scoring, a points table and the held slots after the
    shape's bench; PR Fa: the waivers; PR Fb: a FAAB league's budget and the rivals' bid
    scale; the format PR: a categories league's head-to-head format; PR Fc: the waiver rule;
    PR Fd: how the rivals bid, and the book's prices; today's by default)."""
    args = league.setup_args()
    return rn.replay_setup(
        season,
        lines,
        members,
        projection,
        reader.PERIOD_ONE[season],
        scheduled,
        draft=draft,
        **{**args, "slots": league_rules.slots(args["slots"])},
        scoring=league_rules.scoring,
        points=league_rules.table,
        waivers=league_rules.waivers,
        waiver_days=league_rules.waiver_days,
        budget=league_rules.budget,
        rival_scale=league_rules.rival_scale,
        h2h=league_rules.h2h,
        waiver_rule=league_rules.waiver_rule,
        rival_bids=league_rules.rival_bids,
        rival_prices=league_rules.rival_prices,
    )


def spots_of(league: shapes.LeagueShape) -> int:
    """The roster spots a league shape's draft fills: its slots that are not held."""
    return sum(1 for s in league.slots if s not in mv.HELD)


def short_drafts(
    reads: Sequence[Any],
    grid: shapes.Grid,
    seed: int,
    oracle_shape: str,
    sources: Sources | None,
    arms: Mapping[str, rn.Arm],
    picks: Mapping[int, Mapping[int, float]],
) -> list[dict[str, Any]]:
    """Every draft of ``grid``'s league shapes that may not fill (#172, PR D4b), one record a
    season, forecaster, team count with roster size, and board: the draft takes teams times the
    slots that are not held (``need``), and a board holds fewer (``holds``). The board is the
    pool, the season's draftable players on the cell's forecaster (``run.draftable_of``),
    which every seat drafts from without a table and every rival's board is under one; or,
    under a table (``picks``, by season), an arm's seat's own board, its forecaster's draftable
    players. Rivals could take every player on that board, so it is held to the whole draft's
    need, and a draft refused on it might have filled. Read on path 0: a forecaster projects
    the same players on every path. Empty when every draft fills. A run that names a league
    shape is refused on any record; under the fixed shape they are noted (:func:`short_line`)."""
    out: list[dict[str, Any]] = []
    sizes = sorted({(x.teams, spots_of(x)) for x in grid.shapes})
    for r in reads:
        days = rn.league_days(r.lines, r.members, r.scheduled)
        table = picks.get(r.season)
        if table is not None:
            forecasts = forecasts_of(sources, r.fixed, r.lines, seed, 0, oracle_shape, arms)
        for f in r.served:
            projection = projection_of(f, r.fixed, r.lines, seed, 0, oracle_shape)
            pool = rn.draftable_of(
                days, days, projection, reader.PERIOD_ONE[r.season], rn.OPENING_DAYS, table
            )
            boards: dict[str | None, int] = {None: len(pool)}
            if table is not None:
                for key, arm in arms.items():
                    own = own_projection(arm.forecaster, f.label, projection, forecasts)
                    boards[key] = sum(1 for k in pool if k in own)
            for teams, spots in sizes:
                for board, n in boards.items():
                    if n < teams * spots:
                        out.append(
                            {
                                "season": r.season,
                                "forecaster": f.label,
                                "teams": teams,
                                "spots": spots,
                                "need": teams * spots,
                                "board": "pool" if board is None else board,
                                "holds": n,
                            }
                        )
    return out


def short_line(x: Mapping[str, Any]) -> str:
    """One of :func:`short_drafts`' records in words."""
    head = (
        f"{x['season']} on {x['forecaster']}: the draft of {x['teams']} teams of {x['spots']} "
        f"spots takes {x['need']} players"
    )
    if x["board"] == "pool":
        return f"{head} and the season has {x['holds']} draftable"
    arm = x["board"].upper() if x["board"] in PAIR else x["board"]
    return (
        f"{head} and arm {arm}'s seat's own board holds {x['holds']} (rivals could take them "
        "all, so the board is held to the whole draft; the draft might have filled)"
    )


#: A season's market under ``--adp espn`` (#172, PR D4a): its table's listed players' average
#: picks and the rivals' spread; None under ``--adp none``.
Market = tuple[Mapping[int, float], adp.Spread] | None
#: The fixed shape's seats as ``run.replay_setup`` numbers them (a league shape's are its
#: ``ids``).
REPLAY_IDS = shapes.FIXED.ids
#: The grids ``replay --grid`` names (#172, PR D4b).
GRIDS: dict[str, shapes.Grid] = {"fixed": shapes.FIXED_GRID, "full": shapes.FULL}


def own_projection(
    label: str | None, run_label: str | None, projection: Any, forecasts: Mapping[str, Any]
) -> Any:
    """The projection a seat holding ``label`` drafts on: the run's forecaster's (``run_label``)
    for None or its label, else that label's (``forecasts_of``'s, for a ``system`` or ``blend``
    seat its stand-in belief on day one)."""
    return projection if label is None or label == run_label else forecasts[label]


def room_draft(
    market: Market,
    arms: Mapping[str, rn.Arm],
    seats: Sequence[str],
    run_label: str | None,
    projection: Any,
    forecasts: Mapping[str, Any],
    seed: int,
    path: int,
    league: shapes.LeagueShape = shapes.FIXED,
    turn: int | None = None,
) -> adp.Draft | None:
    """A room's draft under a ``market`` on one path (#172, PR D4a): every seat holds an arm, so
    every seat drafts on its arm's own board. None without a market. The seats are the path's
    league shape's and the arms are rotated by its ``turn`` (#172, PR D4b; the path's on one
    shape); the rivals' draws stay on the path."""
    if market is None:
        return None
    rotation = path if turn is None else turn
    own = {
        t: own_projection(arms[name].forecaster, run_label, projection, forecasts)
        for t, name in rn.rotate(seats, league.ids, rotation).items()
    }
    return adp.Draft(market[0], market[1], seed, path, own)


def pair_setups(
    season: int,
    lines: Any,
    members: Any,
    scheduled: Any,
    projection: Any,
    market: Market,
    arms: Mapping[str, rn.Arm],
    pair: Sequence[str],
    run_label: str | None,
    forecasts: Mapping[str, Any],
    seed: int,
    path: int,
    league: shapes.LeagueShape = shapes.FIXED,
    turn: int | None = None,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> dict[str, Any]:
    """The pair's league on one path, by arm (#172, PR D4a), in the path's league shape (#172,
    PR D4b) under the run's league rules (PR D4c): one league drafted on the run's forecaster
    without a ``market``. Under one, the
    arm's seat drafts on the arm's own board and every other seat on a rival's board: arms whose
    draft-day beliefs are one label share one league (the same object), arms on two labels get
    one each. The arm's seat is the shape's ``teams[turn mod n]`` (the path's turn; the path
    itself on one shape)."""
    if market is None:
        setup = replay_setup_of(
            season, lines, members, scheduled, projection, None, league, league_rules
        )
        return dict.fromkeys(pair, setup)
    me = league.ids[(path if turn is None else turn) % league.teams]
    labels = {k: arms[k].forecaster or run_label for k in pair}
    setups: dict[str, Any] = {}
    for k in pair:
        same = next((setups[j] for j in setups if labels[j] == labels[k]), None)
        if same is not None:
            setups[k] = same
            continue
        own = own_projection(labels[k], run_label, projection, forecasts)
        draft = adp.Draft(market[0], market[1], seed, path, {me: own})
        setups[k] = replay_setup_of(
            season, lines, members, scheduled, projection, draft, league, league_rules
        )
    return setups


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
    market: Market = None,
    grid: shapes.Grid = shapes.FIXED_GRID,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> dict[str, Any]:
    """One task of the room on a replay. Under a ``market`` (#172, PR D4a) every seat holds an
    arm, so every seat drafts on its arm's own board and no board is a rival's. The path plays
    its league shape on ``grid`` with the arms rotated by its turn (``shapes.visit``, #172, PR
    D4b), under the run's ``league_rules`` (PR D4c); the world's draws stay on ``(seed,
    path)``."""
    v = shapes.visit(path, grid)
    projection = projection_of(forecaster, fixed, lines, seed, path, shape)
    forecasts = forecasts_of(sources, fixed, lines, seed, path, shape, arms)
    draft = room_draft(
        market, arms, seats, forecaster.label, projection, forecasts, seed, path, v.shape, v.turn
    )
    setup = replay_setup_of(
        season, lines, members, scheduled, projection, draft, v.shape, league_rules
    )
    w = rn.replay_world(
        setup,
        lines,
        lag,
        seed,
        path,
        weights[forecaster.label],
        news_sd=news_sd,
        label=forecaster.label,
        forecasts=forecasts,
        split=splits_of(sources, arms),
        weights_of=weights,
    )
    held = {t: arms[name].forecaster for t, name in rn.rotate(seats, setup.teams, v.turn).items()}
    unprojected = rn.unprojected(setup, w, held)
    out = rn.room(setup, w, arms, seats, v.turn)
    out["forecaster"] = forecaster.label
    out["unprojected"] = unprojected
    out["league"] = {"shape": v.index, "turn": v.turn}
    if market is not None:
        out["drafts"] = 1
        out["drafted_unprojected"] = [rn.drafted_unprojected(setup)]
    return out


def seat_of(setup: Any, path: int) -> int:
    """The paired design's seat on ``path``: ``setup.teams[path mod len(teams)]``, so over a
    multiple of the seats every seat is taken equally often (#172, PR D2)."""
    return setup.teams[path % len(setup.teams)]


def paths_for_pair(paths: int, teams: int = rn.REPLAY_TEAMS) -> int:
    """``paths`` rounded up to a multiple of the league's ``teams``."""
    return -(-max(1, paths) // teams) * teams


def pair_league(
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
    market: Market = None,
    grid: shapes.Grid = shapes.FIXED_GRID,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> tuple[shapes.Visit, dict[str, Any], dict[int, rn.World], int]:
    """A pair's path before any day of it (:func:`task_paired`'s, which plays it, and
    :func:`task_scale`'s, which reads the season scale on it): the path's visit, each arm's
    league by its key in ``pair`` (one object when the two share a draft), each league's world
    by the league's ``id``, and the pair's seat."""
    v = shapes.visit(path, grid)
    projection = projection_of(forecaster, fixed, lines, seed, path, shape)
    forecasts = forecasts_of(sources, fixed, lines, seed, path, shape, arms)

    def world_of(setup: Any) -> rn.World:
        return rn.replay_world(
            setup,
            lines,
            lag,
            seed,
            path,
            weights[forecaster.label],
            news_sd=news_sd,
            label=forecaster.label,
            forecasts=forecasts,
            split=splits_of(sources, arms),
            weights_of=weights,
        )

    setups = pair_setups(
        season,
        lines,
        members,
        scheduled,
        projection,
        market,
        arms,
        pair,
        forecaster.label,
        forecasts,
        seed,
        path,
        v.shape,
        v.turn,
        league_rules,
    )
    sa, sb = (setups[k] for k in pair)
    worlds = {id(sa): world_of(sa)} if sa is sb else {id(sa): world_of(sa), id(sb): world_of(sb)}
    me = seat_of(sa, v.turn)
    return v, setups, worlds, me


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
    market: Market = None,
    grid: shapes.Grid = shapes.FIXED_GRID,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> dict[str, Any]:
    """One task of the paired design on a replay (#172, PR D2): the league drafted on the cell's
    forecaster, arm A in seat :func:`seat_of` in one season and arm B in the same seat in a
    second, through one world (``run.paired``); every other seat is each arm's rivals, on the
    run's forecaster. ``pair`` names the two arms' keys in ``arms`` (``a`` and ``b``).

    Under a ``market`` (#172, PR D4a) the arm's seat drafts on the arm's own board and the other
    seats on rivals' boards. When the two arms' draft-day beliefs are one label there is one
    draft and one league, as before; when they differ each arm's season is its own league from
    the draft on (``run.paired_apart``): two setups and two worlds on the same ``(seed, path)``,
    so the world's draws and the rivals' boards stay common.

    The path plays its league shape on ``grid``, and the seat is the shape's ``teams[turn mod
    n]`` (``shapes.visit``, #172, PR D4b): both arms hold one shape and one seat. Every path
    plays the run's ``league_rules`` (PR D4c)."""
    v, setups, worlds, me = pair_league(
        season,
        lines,
        members,
        scheduled,
        forecaster,
        fixed,
        shape,
        sources,
        lag,
        weights,
        news_sd,
        arms,
        pair,
        seed,
        path,
        market,
        grid,
        league_rules,
    )
    a, b = (arms[k] for k in pair)
    sa, sb = (setups[k] for k in pair)
    unprojected = {
        k: rn.unprojected(
            setups[k],
            worlds[id(setups[k])],
            {t: arms[k].forecaster if t == me else None for t in setups[k].teams},
        )
        for k in pair
    }
    if sa is sb:
        out = rn.paired(sa, worlds[id(sa)], a, b, me)
    else:
        out = rn.paired_apart(sa, worlds[id(sa)], sb, worlds[id(sb)], a, b, me)
    out["seat"] = me
    out["forecaster"] = forecaster.label
    out["unprojected"] = unprojected
    out["league"] = {"shape": v.index, "turn": v.turn}
    if market is not None:
        out["drafts"] = 1 if sa is sb else 2
        out["drafted_unprojected"] = [
            rn.drafted_unprojected(x) for x in ([sa] if sa is sb else [sa, sb])
        ]
    return out


def task_scale(
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
    market: Market = None,
    grid: shapes.Grid = shapes.FIXED_GRID,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> dict[str, Any] | None:
    """The season scale of the pair's arm A on one path (#172, PR H1: the screen's nudge of
    ``season_weight`` is a share of it): ``run.scale_on`` on the league, the world and the
    seat :func:`task_paired` would play, on the path's first simulated day. No day is played,
    nothing is drawn and nothing decided; None where the arm holds no odds."""
    _, setups, worlds, me = pair_league(
        season,
        lines,
        members,
        scheduled,
        forecaster,
        fixed,
        shape,
        sources,
        lag,
        weights,
        news_sd,
        arms,
        pair,
        seed,
        path,
        market,
        grid,
        league_rules,
    )
    sa = setups[pair[0]]
    return rn.scale_on(sa, worlds[id(sa)], arms[pair[0]], me)


#: The replay's version in its payload: 12 since continuous waivers (#172, PR Fc), 11 since the
#: head-to-head format (the format PR),
#: 10 since FAAB (PR Fb), 9 since the waivers (PR Fa), 8 since the league rules (PR D4c), 7 since the
#: league generator (PR D4b), 6 since the draft market (PR D4a), each as its reason says; 5
#: since the standalone cut (PR D3): the payload
#: names nothing of a live league or a drawn world (its ``gap``, ``refresh`` and ``tau`` are
#: gone), its figures as they were; 4 since
#: a run names several seasons (PR D2): what
#: is one season's (results, counts, the season scale, the forecasters, the sources, the
#: weights, the players, the shape, the unprojected count) is keyed by season, and each label's
#: weights are its own; 3 since a run names its forecasters (PR D1): its results and counts are
#: keyed by the forecaster's label (``prior``, ``oracle:0.1``), where version 2 keyed them by kind
#: and spread (``prior:0``); 2 since its seats believe only the games played (PR B1), a version 1
#: replay's seats having seen each season's rates.
REPLAY_VERSION = 13
REPLAY_VERSION_WHY = (
    "13: the rivals' adds and bids: a market rival's opponents block may name view (draft, the "
    "draft-day ranking all season, the default; or season, the run's forecaster's per-game value "
    "that morning, a player heard out never picked) and among (one of its best few worth more "
    "than its weakest, each as likely; 1 by default); --rival-bids book, with --waivers faab, "
    "draws a market rival's bid on the price book fit-bids writes from the public leagues' "
    "winning bids, at its move's rank among the market's moves of the fortnight; the league "
    "block's rules name rival_bids in every FAAB run, and a run on the book records the book's "
    "file and hashes and says so in its FAAB note; with nothing new named the figures are "
    "version 12's. "
    "12: continuous waivers (--waiver-rule continuous, with --waivers priority or faab): every "
    "unowned player is on waivers at all times, so every add is a claim, decided the next "
    "morning (a dropped player's on his clear date) by the league's waivers, and nothing lands as "
    "a free agent; the league block's rules name the waiver rule in every waiver run, and a "
    "continuous run names its execution model (claims_only_by_priority, "
    "claims_only_by_sealed_bids), says the rule in its league block's notes and is held to one "
    "audit rule more (claims_only); with the rule not named the figures are version 11's, but in "
    "a waiver run with held slots: every waiver league's morning now brings the cleared held "
    "players back, trims the rosters and lets the churns' held players go before the claims due "
    "are decided, where it decided them first (PR Fa's order, in which a cleared player's trim "
    "could take a player just claimed and a churn's claim found no room in the slot its held "
    "player was leaving), so such a run moves where a claim is decided on a morning a held "
    "player comes back or a churn's held player leaves"
)
#: What a replay under a table drafts on (#172, PR D4a), for its payload.
ADP_RIVAL = (
    "a rival seat's board: each listed player's average pick plus a normal draw at base + "
    "growth x pick picks, no bias, one draw a listed player; the players the table does not list "
    "below every listed one, by the run's forecaster's draft-day value"
)
ADP_SEAT = (
    "an arm's seat's board: its own forecaster's per-game value on draft day (a system or blend "
    "seat's stand-in belief); a player it does not project is not on it"
)
ADP_MARKET = (
    "the market's view: the negative of a listed player's average pick, the unlisted below by "
    "the run's forecaster's draft-day value; the preseason's, never refreshed"
)
ADP_POOL = (
    "the players with a scheduled game in the season's first {days} days that the run's "
    "forecaster projects or the table lists"
)
ADP_LIMIT = (
    "the arm's seat drafts on per-game value alone, with no regard for the games a player is "
    "expected to miss or for where the room would take him, so it can finish near the top or "
    "near the bottom of the room on every path, the paired change in playoff odds then zero with "
    "no spread; how it should draft is open with the user"
)
ADP_APART = (
    "the two arms' draft-day beliefs differ, so each arm's season is a league of its own from "
    "the draft on, on the same (seed, path) and the same rivals' boards: the pair shares no draft"
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


def unprojected_note(grid: shapes.Grid) -> str:
    """:data:`UNPROJECTED_NOTE`, word for word on the fixed shape; on a grid the whole room is
    the path's league's seats, not twelve (#172, PR D4b)."""
    if grid is shapes.FIXED_GRID:
        return UNPROJECTED_NOTE
    return UNPROJECTED_NOTE.replace("on all twelve (all)", "on all the path's league's seats (all)")


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
    market: Market = None,
    league: shapes.LeagueShape = shapes.FIXED,
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> tuple[Any, int, list[dict[str, Any]]]:
    """Path 0 of the replay on the recorded lines and on :func:`nopeek.perturb`'s, with one
    league built before either (on ``projection``, the run's forecaster's on path 0, ``label``,
    believed at ``weights``; ``forecasts`` the arms' other beliefs' projections, at their own
    ``weights_of``; ``split`` their split labels): the first difference between their day records
    (None when they never part), the records compared and the audit's breaches in either run.
    ``paired``: the design the run names is the pair (``arms`` ``a`` and ``b``), path 0's seat
    taken by each arm in its own season, and both seasons' day records are compared.

    Under a ``market`` (#172, PR D4a2) the league is drafted as the run's path 0 drafts it
    (:func:`room_draft`, :func:`pair_setups`); a pair whose two arms draft apart has two leagues,
    both built before either world, and both leagues' seasons are compared (``run.paired_apart``,
    B's days as variant 1). The leagues are built once, before either world, so the check is
    about the season's decisions; that the draft reads nothing of the season rests on what it is
    built from (the table, the forecasters' draft-day figures, the opening days' schedule).

    The league is path 0's shape (``league``, #172, PR D4b): the grid's first under ``--grid
    full``, the shape named under ``--league``; path 0's turn is 0 on any grid), under the
    run's league rules (``league_rules``, PR D4c)."""
    pinned = forecasts or {}
    if paired:
        setups = pair_setups(
            season,
            lines,
            members,
            scheduled,
            projection,
            market,
            arms,
            PAIR,
            label,
            pinned,
            seed,
            0,
            league,
            None,
            league_rules,
        )
        setup, second = setups["a"], setups["b"]
    else:
        draft = room_draft(market, arms, seats, label, projection, pinned, seed, 0, league)
        setup = second = replay_setup_of(
            season, lines, members, scheduled, projection, draft, league, league_rules
        )
    if day not in setup.days:
        raise ValueError(f"{day} is not a day of the replayed season")
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, seed)
    digests: list[dict[tuple[date, int], dict[str, str]]] = []
    breaches: list[dict[str, Any]] = []
    for run_, these in (("recorded", lines), ("changed", other)):
        got: dict[tuple[date, int], dict[str, str]] = {}

        def keep(r: rn.DayRecord, got: dict[tuple[date, int], dict[str, str]] = got) -> None:
            got[(r.day, r.variant)] = nopeek.digest(r)

        def world_of(s: Any, these: Any = these) -> rn.World:
            return rn.replay_world(
                s,
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

        w = world_of(setup)
        if paired and second is not setup:
            out = rn.paired_apart(
                setup, w, second, world_of(second), arms["a"], arms["b"], seat_of(setup, 0), keep
            )
        elif paired:
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
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> SeasonRead:
    """Everything a replay reads for ``season`` before any path. A forecaster that cannot serve
    it leaves its cell skipped; a stand-in that cannot refuses the run by name
    (``readers.SimReadError``): a system label cannot be built there. The run's policy shape
    (what its seats read) is read on a league under the run's ``league_rules`` (PR D4c): its
    scoring and its held slots, which no league shape moves."""
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
            policy.shape_of(
                replay_setup_of(
                    season, lines, members, scheduled, first, None, shapes.FIXED, league_rules
                )
            ),
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


@dataclass(frozen=True)
class ReplayPlan:
    """A replay as :func:`replay_plan` leaves it, its inputs read and nothing played: the seasons,
    the league shapes and rules, the table's spread, when it started, the no-peek day, the
    forecasters, the stand-ins, the fit, the specs and their arms, the seats, whether it is a
    pair, the tables, each season's read, the short drafts and the shapes read, and the price
    book its rivals bid on when the run names it (PR Fd)."""

    seasons: list[int]
    grid: shapes.Grid
    league_rules: shapes.LeagueRules
    spread: Any
    started: datetime
    day: date | None
    named: Sequence[fc.Forecaster]
    sources: Sources | None
    inputs: rn.WorldInputs
    fit: dict[str, Any]
    sha: str
    fit_path: Path
    specs: list[dict[str, Any]]
    arms: dict[str, rn.Arm]
    seats: list[str]
    paired: bool
    tables: dict[int, tuple[adp.Table, str]]
    reads: list[SeasonRead]
    short: list[dict[str, Any]]
    shapes_read: list[policy.Shape]
    book: tuple[Mapping[str, Any], str, Path] | None = None


def replay_plan(
    args: argparse.Namespace,
    specs: list[dict[str, Any]] | None = None,
    read: Callable[..., SeasonRead] | None = None,
) -> ReplayPlan | int:
    """A replay's flags read, checked and refused by name as ``replay`` refuses them (the exit
    code then), its fit, logs and arms read and its cells and weights printed: everything before
    a task is made. ``specs``: the arms' specs when the caller holds them (``screen``, whose arm
    B is arm A with one nudge); None reads ``args.arms`` or ``args.seats``, as ``replay`` does.
    ``read``: what reads a season, :func:`read_season` by default (``screen`` hands one that
    remembers, so its pairs share one read of a season)."""
    read = read or read_season
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
    if args.league is not None and args.grid != "fixed":
        print(
            f"refused: --league names one league shape for the whole run; --grid {args.grid} "
            "visits a grid of them: name one or the other"
        )
        return 2
    try:
        grid = (
            shapes.one("league", shapes.parse_league(args.league))
            if args.league is not None
            else GRIDS[args.grid]
        )
    except ValueError as e:
        print(f"refused: {e}")
        return 2
    named_shape = args.league is not None or args.grid != "fixed"
    if args.points is not None and args.scoring != "points":
        print("refused: --points is a points league's table; it is read only with --scoring points")
        return 2
    try:
        table = None
        if args.scoring == "points":
            table = (
                shapes.parse_points(args.points)
                if args.points is not None
                else shapes.POINTS_DEFAULT
            )
        held = shapes.parse_held(args.held) if args.held is not None else ()
        waivers, waiver_days = shapes.parse_waivers(args.waivers, args.waiver_days)
        budget, scale = shapes.parse_budget(waivers, args.budget, args.rival_scale)
        h2h = shapes.parse_h2h(args.scoring, args.h2h)
        waiver_rule = shapes.parse_waiver_rule(waivers, args.waiver_rule)
        rival_bids = shapes.parse_rival_bids(waivers, args.rival_bids)
        league_rules = shapes.LeagueRules(
            args.scoring,
            table,
            held,
            waivers,
            waiver_days,
            budget,
            scale,
            h2h,
            waiver_rule,
            rival_bids,
        )
    except ValueError as e:
        print(f"refused: {e}")
        return 2
    spread = None
    if args.adp == "none" and args.adp_spread is not None:
        print(
            "refused: --adp-spread is the spread of a table's rivals; --adp none drafts on the "
            "run's forecaster and reads none"
        )
        return 2
    if args.adp != "none":
        if args.adp_spread is None:
            print(
                f"refused: --adp {args.adp} names its rivals' spread, --adp-spread "
                "<base>,<growth>: it is given, never fitted here"
            )
            return 2
        try:
            spread = adp.parse_spread(args.adp_spread)
        except ValueError as e:
            print(f"refused: {e}")
            return 2
    started = datetime.now(UTC)
    try:
        day = date.fromisoformat(args.no_peek) if args.no_peek else None
        named = fc.parse(args.forecasters)
        sources = sources_of(args.bbm_as, args.yahoo_as)
        inputs, fit, sha, fit_path = world_inputs(args.data)
        book = None
        if league_rules.rival_bids == shapes.BOOK:
            book = reader.newest_book(args.data)
            league_rules = replace(league_rules, rival_prices=bids.prices_of(book[0]))
        if specs is None:
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
    tables: dict[int, tuple[adp.Table, str]] = {}
    if spread is not None:
        try:
            tables = {t: reader.adp_table(args.data, t, HOLD_OUT) for t in seasons}
        except reader.SimReadError as e:
            print(f"refused: --adp {args.adp}: {e}")
            return 2
    try:
        reads = [
            read(args.data, t, named, sources, arms, args.seed, args.shape, league_rules)
            for t in seasons
        ]
    except (reader.SimReadError, ValueError, OSError, KeyError) as e:
        print(f"refused: {e}")
        return 2
    for line_ in cells_lines(reads, named):
        print(line_)
    for t, (table, sha) in tables.items():
        print(
            f"draft market, {t}: {args.adp} table, {len(table.picks)} listed, "
            f"{table.at_ceiling} at the ceiling, log {sha[:12]}; spread {spread.base:g},"
            f"{spread.growth:g} given"
        )
    if not any(r.served for r in reads):
        print("refused: no cell is left: no forecaster named serves any season named")
        return 2
    if league_rules != shapes.PLAIN:
        print(f"league rules, on every path: {league_rules.label()}")
    short = short_drafts(
        reads,
        grid,
        args.seed,
        args.shape,
        sources,
        arms,
        {t: table.picks for t, (table, _) in tables.items()},
    )
    if short and named_shape:
        for x in short:
            print(f"refused: {short_line(x)}")
        print(
            f"refused: {len(short)} draft(s) of the league shapes named cannot be filled; no "
            "short roster is played"
        )
        return 2
    for x in short:
        print(
            "short draft, played on the fixed shape with the rosters it cannot fill left short "
            f"(a named league shape refuses it): {short_line(x)}"
        )
    shapes_read = [r.shape for r in reads if r.shape is not None]
    # A stake reads the cut line and the bracket's weeks: no path of a league whose bracket is
    # not read is played with one (the guard PR), said before any path.
    for arm in arms.values():
        why = rn.stake_refused(arm, shapes_read)
        if why:
            print(f"refused: {why}")
            return 2
    same = same_seats(arms, shapes_read, rivals=paired)
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
    return ReplayPlan(
        seasons,
        grid,
        league_rules,
        spread,
        started,
        day,
        named,
        sources,
        inputs,
        fit,
        sha,
        fit_path,
        specs,
        arms,
        seats,
        paired,
        tables,
        reads,
        short,
        shapes_read,
        book,
    )


@dataclass(frozen=True)
class ReplayTasks:
    """A replay's tasks as :func:`replay_tasks` makes them: the paths a cell (rounded up), each
    path's visit, the task function, every task's arguments and key, the cells, and the task
    timed first (the slowest by its league)."""

    paths: int
    visits: list[Any]
    task: Any
    tasks: list[tuple[Any, ...]]
    keys: list[dict[str, Any]]
    cells: int
    slow: int


def replay_tasks(plan: ReplayPlan, args: argparse.Namespace) -> ReplayTasks:
    """The tasks of ``plan``'s run, a cell's paths rounded up as ``replay`` rounds them (said
    when it does)."""
    grid, league_rules, spread, sources, inputs, arms, seats, paired, tables, reads = (
        plan.grid,
        plan.league_rules,
        plan.spread,
        plan.sources,
        plan.inputs,
        plan.arms,
        plan.seats,
        plan.paired,
        plan.tables,
        plan.reads,
    )
    paths = args.paths
    if len(grid.shapes) > 1:
        paths = shapes.round_up(args.paths, grid, paired)
        if paths != args.paths:
            print(
                f"--paths {args.paths} rounded up to {paths}, a multiple of the grid's "
                f"{len(grid.shapes)} league shapes, so every shape is played once a round and a "
                "team count's seats are taken as evenly as the paths allow"
            )
    elif paired:
        teams = grid.shapes[0].teams
        paths = paths_for_pair(args.paths, teams)
        if paths != args.paths:
            print(
                f"--paths {args.paths} rounded up to {paths}, a multiple of the league's "
                f"{teams} seats, so every seat is taken equally often in every cell"
            )
    visits = [shapes.visit(p, grid) for p in range(paths)]
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
            None if spread is None else (tables[r.season][0].picks, spread),
            grid,
            league_rules,
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
    # The timed task is the first cell's path on the run's largest draft and, among those, the
    # loosest add limit (no limit first: a seat that may add keeps solving), so on a grid the
    # estimate errs long; on one shape it is path 0.
    slow = max(
        range(min(paths, len(grid.shapes))),
        key=lambda p: (
            visits[p].shape.teams * spots_of(visits[p].shape),
            math.inf if visits[p].shape.weekly_adds is None else visits[p].shape.weekly_adds,
            -p,
        ),
    )
    return ReplayTasks(paths, visits, task, tasks, keys, cells, slow)


def replay_payload(
    plan: ReplayPlan,
    args: argparse.Namespace,
    made: ReplayTasks,
    results: Sequence[Mapping[str, Any]],
    workers: int,
    run_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The record of ``plan``'s run from every task's result, and its audit block: the paths the
    audit voided left out of every figure. Nothing is written and no look is counted here."""
    (
        seasons,
        grid,
        league_rules,
        spread,
        started,
        named,
        sources,
        fit,
        sha,
        fit_path,
        specs,
        arms,
        seats,
        paired,
        tables,
        reads,
        short,
        shapes_read,
    ) = (
        plan.seasons,
        plan.grid,
        plan.league_rules,
        plan.spread,
        plan.started,
        plan.named,
        plan.sources,
        plan.fit,
        plan.sha,
        plan.fit_path,
        plan.specs,
        plan.arms,
        plan.seats,
        plan.paired,
        plan.tables,
        plan.reads,
        plan.short,
        plan.shapes_read,
    )
    keys, paths, visits = made.keys, made.paths, made.visits
    rules = audit.rules_of(league_rules.waivers, league_rules.waiver_rule)
    keep, note = audited(keys, results, rules)
    keys = [k for k, ok_ in zip(keys, keep, strict=True) if ok_]
    results = [r for r, ok_ in zip(results, keep, strict=True) if ok_]
    payload = base_payload(
        "replay",
        run_name,
        started,
        sha,
        fit_path,
        fit,
        workers,
        arms,
        policy.executions_of(league_rules.waivers, league_rules.waiver_rule),
        policy.measure(league_rules.points is not None, league_rules.one_win),
        plan.book,
    )
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
        )
        if spread is None
        else (
            "snake in which each seat takes the best player left on its own board (adp): the "
            "rivals' on the season's table, an arm's seat's on its own forecaster"
        ),
        "adp": adp_block(args.adp, spread, tables, keys, results, paired),
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
        "reads": reads_of(arms, shapes_read, rivals=paired),
        "audit": note,
        "confirmation": None,
        "league": league_block(grid, visits, short, league_rules),
    }
    if spread is not None:
        payload["pool"]["draft"] = ADP_POOL.format(days=rn.OPENING_DAYS)
    if paired:
        payload |= paired_blocks(
            keys,
            results,
            arms,
            paths,
            grid,
            league_rules.scoring,
            league_rules.waivers,
            league_rules.h2h,
        )
        payload["verdict"] = verdict_block(payload, named, seasons, sources, note)
    else:
        payload |= room_blocks(
            keys,
            results,
            seats,
            grid,
            league_rules.scoring,
            league_rules.waivers,
            league_rules.h2h,
            rn.counted_of(list(arms.values())),
        )
        if sources is not None:
            payload["result_is"] = ROOM_RESULT
    return payload, note


def cmd_replay(args: argparse.Namespace) -> int:
    ok, why = guard(NO_PEEK_HOURS if args.no_peek else 0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    plan = replay_plan(args)
    if isinstance(plan, int):
        return plan
    (
        seasons,
        grid,
        league_rules,
        spread,
        day,
        named,
        sources,
        inputs,
        sha,
        specs,
        arms,
        seats,
        paired,
        tables,
        reads,
    ) = (
        plan.seasons,
        plan.grid,
        plan.league_rules,
        plan.spread,
        plan.day,
        plan.named,
        plan.sources,
        plan.inputs,
        plan.sha,
        plan.specs,
        plan.arms,
        plan.seats,
        plan.paired,
        plan.tables,
        plan.reads,
    )
    if day is not None:
        (r,) = reads
        if not r.served:
            print(f"refused: no forecaster named serves {r.season}")
            return 2
        f0 = r.served[0]
        first = shapes.visit(0, grid).shape
        rules_ = "" if league_rules == shapes.PLAIN else f"; {league_rules.label()}"
        print(f"no-peek check's league: path 0's, {first.label()}{rules_}")
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
                None if spread is None else (tables[r.season][0].picks, spread),
                first,
                league_rules,
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
    made = replay_tasks(plan, args)
    paths, visits, task, tasks, keys, cells, slow = (
        made.paths,
        made.visits,
        made.task,
        made.tasks,
        made.keys,
        made.cells,
        made.slow,
    )
    t0 = clock.perf_counter()
    first_run = task(*tasks[slow])
    one = clock.perf_counter() - t0
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else estimate_hours(one, len(tasks), workers)
    )
    print(
        f"{len(tasks)} tasks ({cells} cells x {paths} paths), one took {one:.1f}s, about {hours:.2f} h on {workers} workers"
    )
    if len(grid.shapes) > 1:
        print(
            f"the task timed is path {slow}, on the grid's largest draft with its loosest add "
            f"limit ({visits[slow].shape.label()}): the estimate errs long"
        )
    rules = audit.rules_of(league_rules.waivers, league_rules.waiver_rule)
    if args.dry_run:
        return dry_run(keys[slow], first_run, rules)
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    rest = rn.run_tasks(task, tasks[:slow] + tasks[slow + 1 :], workers)
    results = [*rest[:slow], first_run, *rest[slow:]]
    run_name = args.name or "replay-" + "-".join(str(t) for t in seasons)
    payload, note = replay_payload(plan, args, made, results, workers, run_name)
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


def adp_block(
    source: str,
    spread: adp.Spread | None,
    tables: Mapping[int, tuple[adp.Table, str]],
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    paired: bool,
) -> dict[str, Any]:
    """What a replay's league was drafted on (#172, PR D4a): the source and, under a table, the
    given spread, the rules, and per season the table in counts (no figure: they stay in the
    log), the log's hash, and the drafted players the run's forecaster does not project, over
    the drafts of the paths that stand."""
    if spread is None:
        return {"source": source}
    drafted: dict[str, list[int]] = {}
    drafts: dict[str, set[int]] = {}
    for key, res in zip(keys, results, strict=True):
        t = str(key["season"])
        drafted.setdefault(t, []).extend(res["drafted_unprojected"])
        drafts.setdefault(t, set()).add(res["drafts"])
    seasons = {}
    for season, (table, sha) in tables.items():
        t = str(season)
        got = drafted.get(t, [])
        seasons[t] = {
            **table.payload(),
            "log_sha256": sha,
            "drafted_unprojected": {
                "drafts": len(got),
                "total": sum(got),
                "mean": sum(got) / len(got) if got else None,
                "max": max(got, default=None),
            },
        }
        if paired:
            seasons[t]["drafts_per_path"] = sorted(drafts.get(t, set()))
    out: dict[str, Any] = {
        "source": source,
        "spread": spread.payload(),
        "rival": ADP_RIVAL,
        "seat": ADP_SEAT,
        "market": ADP_MARKET,
        "pool": ADP_POOL.format(days=rn.OPENING_DAYS),
        "limit": ADP_LIMIT,
        "seasons": seasons,
    }
    if paired:
        apart = any(2 in v for v in drafts.values())
        out["pair"] = ADP_APART if apart else "one draft and one league, shared by both arms"
    return out


def room_blocks(
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    seats: Sequence[str],
    grid: shapes.Grid = shapes.FIXED_GRID,
    scoring: str = "categories",
    waivers: str = "none",
    h2h: str = ONE_WIN,
    counted: Sequence[str] = (),
) -> dict[str, Any]:
    """A room's figures, keyed by season and then by forecaster: each arm's outcomes and counts
    pooled over its seats and the paths that stand (the counts' note the run's ``waivers``' and
    the season fields its arms name, ``counted``, :func:`counts_note`), each arm's season scale
    by season (its note the run's ``scoring``'s and format's, :func:`scale_note`), the
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
            "note": scale_note(scoring, h2h),
            "by_season": {
                t: {arm: scale_of(rows) for arm, rows in d.items()} for t, d in scales.items()
            },
        },
        "counts": {
            "note": counts_note(waivers, counted),
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
            "note": unprojected_note(grid),
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
#: The seat rule and the rivals on a league shape other than the fixed one (#172, PR D4b).
SEAT_RULE_SHAPES = (
    "path p plays its league shape and turn (league.rule) and puts arm A in that shape's seat "
    "teams[turn mod n] in one season and arm B in the same seat in a second, through one world; "
    "on a grid the paths are a multiple of its shapes, on one shape a multiple of its seats, so "
    "a team count's seats are taken as evenly as the paths allow"
)
RIVALS_NOTE_SHAPES = (
    "the other seats of the path's league (its teams less one) are each arm's opponents block "
    "and believe the run's forecaster, whatever the arm believes"
)
#: The by-axis table's note (#172, PR D4b).
BY_AXIS_NOTE = (
    "advisory, a description and not a test: for each axis of the grid and each of its values, "
    "the paired change (b less a) over the paths whose league shape has that value; a shape is "
    "played once a round, so the paths behind a value are few, and an axis's values sit on "
    "nearly but not exactly even seats (league.rule); no verdict reads it"
)
#: The league block's note (#172, PR D4b).
LEAGUE_NOTE = (
    "each path plays one league shape at one turn, a pure function of the path (league.rule), "
    "and both arms of a pair share them; the verdict pools every path of a cell, so on a grid "
    "its paths vary the league as well as the seat and the draft. short_draft: each draft that "
    "may not fill (the season's draftable players, or under a table an arm's seat's own board, "
    "fewer than teams x the slots that are not held); a run that names a league shape refuses "
    "it, and on the fixed shape it is noted and played, the rosters it cannot fill left short"
)


#: What a points league's metrics are (#172, PR D4c), in a points run's league block.
POINTS_NOTE = (
    "a points league's week is one result, a win, a tie or a loss on the week's fantasy points, "
    "so category_wins is its matchup wins again (a tie half) and equals matchup_wins; a tie on "
    "win percentage in the standings goes to points for, then head to head; the bracket's tied "
    "week to the higher seed"
)


#: How a league that counts every category ranks its teams (#172, the format PR), in such a run's
#: league block; a run of the default format, one win per matchup, has none, as before.
H2H_NOTE = (
    "each category of each regular week is a win, a loss or a tie, and the standings order the "
    "teams by the category percentage (category wins, a tie half, over the categories played), "
    "then head to head (the weeks' results between the tied teams), then the team's number, a "
    "working default (a league may break a tie otherwise); matchup_wins, category_wins and the "
    "record are the weeks' results as in the default format, only the rank and what rests on it "
    "read the format; a playoff matchup goes to the side with more categories, the higher seed "
    "through a tie, as in the default"
)


#: How a FAAB league's bids are made (#172, PR Fb), in a FAAB run's league block.
FAAB_NOTE = (
    "a claim's sealed bid is set when it is placed, clamped to its team's dollars left that day "
    "(open bids not taken out); the clear morning decides the claims highest bid first, a tie "
    "by waiver priority, the winner paying exactly its bid, a claim its team can no longer pay "
    "failing; the order rolls only when a win broke a tie, a working default (a league may set "
    "it otherwise); only a dropped player waiting his days is bid on, a free agent costs $0. "
    "The seat on the exact or the surrogate tier, and a mirror rival, bid by the live rule "
    "(autopilot.bid_of) on the move's own gain on the judging horizon over the typical gain of "
    "the moves it recommended in the fortnight (the plan floor until ten), its faab_sizing, and "
    "no flag: the live rule's flags are not modelled. The ranking tier bids $0. A market rival "
    "bids round(rival_scale x gain / typical x noise) on its own view, the typical over every "
    f"market rival's moves of the {policy.RIVAL_BIDS.days} days before (its own gain until "
    f"{policy.RIVAL_BIDS.least}), the noise uniform on [{policy.RIVAL_BIDS.noise[0]:g}, "
    f"{policy.RIVAL_BIDS.noise[1]:g}): an assumed form, not a fit, so a result that flips sign "
    "across rival_scale 0.5, 1 and 2 depends on the league. A static seat never claims. The bid "
    "counts are the world's knowledge of every bid; no seat reads them"
)
#: The clause of :data:`FAAB_NOTE` that says which adds are bid on, and what a FAAB run under
#: continuous waivers (#172, PR Fc) says in its place: the note is otherwise the same, and a run
#: with the rule not named records :data:`FAAB_NOTE` as before.
FAAB_FREE = "only a dropped player waiting his days is bid on, a free agent costs $0"
FAAB_EVERY = (
    "under continuous waivers every add is a claim and is bid on, one on a player nobody dropped "
    "lately decided the next morning; no add is a free agent's"
)
FAAB_NOTE_CONTINUOUS = FAAB_NOTE.replace(FAAB_FREE, FAAB_EVERY)
#: The clause of :data:`FAAB_NOTE` on the market rivals' bids, and what a run on the price book
#: (#172, PR Fd, ``--rival-bids book``) says in its place; a run that names none says
#: :data:`FAAB_ASSUMED` as before.
FAAB_ASSUMED = (
    "A market rival bids round(rival_scale x gain / typical x noise) on its own view, the typical "
    f"over every market rival's moves of the {policy.RIVAL_BIDS.days} days before (its own gain "
    f"until {policy.RIVAL_BIDS.least}), the noise uniform on [{policy.RIVAL_BIDS.noise[0]:g}, "
    f"{policy.RIVAL_BIDS.noise[1]:g}): an assumed form, not a fit, so a result that flips sign "
    "across rival_scale 0.5, 1 and 2 depends on the league."
)
FAAB_BOOK = (
    "A market rival bids round(rival_scale x budget x Q(u)) on the price book (fit-bids: the "
    "public leagues' rivals' winning bids as shares of their budget; its hash, its file and its "
    "table's hash recorded with the fit's), Q the book's quantile and u = (below + U) / (n + 1), below the market rivals' "
    f"moves of the {policy.RIVAL_BIDS.days} days before that gained less on the view than its "
    f"move, n how many there are and U uniform on [0, 1) (U alone until {policy.RIVAL_BIDS.least}): "
    "a book of winning bids, so where several claims meet the simulated winning prices sit above "
    "it, and a result that flips sign across rival_scale 0.5, 1 and 2 depends on the league."
)
#: How a league under continuous waivers adds (#172, PR Fc), in such a run's league block, by
#: priority or by FAAB; a run with the rule not named has none.
WAIVER_RULE_NOTE = (
    "continuous waivers: every unowned player is on waivers at all times, the draft's leftovers "
    "from the first morning, so every add is a claim: one on a player nobody dropped lately is "
    "decided the next morning (a working default: no league's clear time is read), one on a "
    "dropped player on his clear date, the drop's morning plus the waiver days; no add lands as "
    "a free agent and the day's rotation decides nothing. The clear morning decides every claim "
    "due in one pass, by the league's waivers (rolling priority, or sealed bids), a claim's drop "
    "and held-slot moves made only if it is won and a churn's held player leaving the next "
    "morning, won or not. The claim counts then cover every add: landed equals claims_won and "
    "gone equals claims_failed"
)


def league_block(
    grid: shapes.Grid,
    visits: Sequence[shapes.Visit],
    short: Sequence[Mapping[str, Any]],
    league_rules: shapes.LeagueRules = shapes.PLAIN,
) -> dict[str, Any]:
    """A replay's league (#172, PR D4b): the grid named, its shapes in order, the visit rule,
    each path's shape index and turn, and the drafts that may not fill; and the run's league
    rules (PR D4c: the scoring, the points table or null, the held slots), with what a points
    league's metrics are in a points run, in a FAAB run how the bids are made (PR Fb), in a
    run that counts every category how its standings rank (the format PR), and under continuous
    waivers how the league adds (PR Fc)."""
    return {
        "grid": grid.name,
        "axes": {k: list(v) for k, v in grid.axes().items()},
        "shapes": [x.payload() for x in grid.shapes],
        "rule": shapes.VISIT_RULE,
        "by_path": [{"shape": v.index, "turn": v.turn} for v in visits],
        "short_draft": list(short),
        "note": LEAGUE_NOTE,
        "rules": league_rules.payload(),
        **({"points_note": POINTS_NOTE} if league_rules.scoring == "points" else {}),
        **({"faab_note": faab_note(league_rules)} if league_rules.bidding else {}),
        **({"h2h_note": H2H_NOTE} if league_rules.h2h == EACH_CATEGORY else {}),
        **({"waiver_rule_note": WAIVER_RULE_NOTE} if league_rules.continuous else {}),
    }


def faab_note(league_rules: shapes.LeagueRules) -> str:
    """A FAAB run's note on its bids: :data:`FAAB_NOTE`, under continuous waivers (PR Fc) with
    :data:`FAAB_EVERY` for :data:`FAAB_FREE` (:data:`FAAB_NOTE_CONTINUOUS`), and on the price book
    (PR Fd) with :data:`FAAB_BOOK` for :data:`FAAB_ASSUMED`."""
    note = FAAB_NOTE_CONTINUOUS if league_rules.continuous else FAAB_NOTE
    if league_rules.rival_bids == shapes.BOOK:
        note = note.replace(FAAB_ASSUMED, FAAB_BOOK)
    return note


def axis_key(value: Any) -> str:
    return "none" if value is None else str(value)


def by_axis(
    keys: Sequence[Mapping[str, Any]], results: Sequence[Mapping[str, Any]], grid: shapes.Grid
) -> dict[str, Any]:
    """The paired change by each axis's value, by season and forecaster (:data:`BY_AXIS_NOTE`):
    the paths that stand, grouped by their league shape's value on the axis."""
    rows: dict[str, dict[str, dict[str, dict[str, list[Any]]]]] = {}
    axes = grid.axes()
    for key, res in zip(keys, results, strict=True):
        t, label = str(key["season"]), key["forecaster"]
        cell = rows.setdefault(t, {}).setdefault(
            label, {a: {axis_key(v): [] for v in vals} for a, vals in axes.items()}
        )
        for axis, v in shapes.axis_values(shapes.visit(key["path"], grid).shape).items():
            cell[axis][axis_key(v)].append(res["delta"])
    return {
        "note": BY_AXIS_NOTE,
        "by_season": {
            t: {
                label: {
                    axis: {
                        v: {"paths": len(rs), "difference": rn.aggregate(rs)}
                        for v, rs in values.items()
                    }
                    for axis, values in cell.items()
                }
                for label, cell in d.items()
            }
            for t, d in rows.items()
        },
    }


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
    grid: shapes.Grid = shapes.FIXED_GRID,
    scoring: str = "categories",
    waivers: str = "none",
    h2h: str = ONE_WIN,
) -> dict[str, Any]:
    """The pair's figures, keyed by season and then by forecaster: each arm's outcomes, the
    difference (B less A) over the paths that stand with how many are distinct, the counts by arm
    and for the rivals (their note the run's ``waivers``', :func:`counts_note`), each arm's season
    scale by season (its note the run's ``scoring``'s and format's, :func:`scale_note`), the
    unprojected count by cell and arm, the seat rule and each path's seat, and the rivals each arm faced. On a grid of
    more than one league shape, the by-axis table (:func:`by_axis`, #172, PR D4b)."""
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
            "rule": SEAT_RULE if grid is shapes.FIXED_GRID else SEAT_RULE_SHAPES,
            "by_path": [
                v.shape.ids[v.turn % v.shape.teams]
                for v in (shapes.visit(p, grid) for p in range(paths))
            ],
        },
        "rivals": {
            **{side: dict(arms[side].opponents) for side in PAIR},
            "note": RIVALS_NOTE if grid is shapes.FIXED_GRID else RIVALS_NOTE_SHAPES,
        },
        **({"by_axis": by_axis(keys, results, grid)} if len(grid.shapes) > 1 else {}),
        "distinct_note": DISTINCT_NOTE,
        "difference": "b less a",
        "results": {t: {label: cell(rs) for label, rs in d.items()} for t, d in rows.items()},
        "season_scale": {
            "note": scale_note(scoring, h2h),
            "by_season": {
                t: {side: scale_of(rs) for side, rs in d.items()} for t, d in scales.items()
            },
        },
        "counts": {
            "note": counts_note(waivers, rn.counted_of(list(arms.values()))),
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
            "note": unprojected_note(grid),
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


# --------------------------------------------------------------------------- screen
#: A screen's paths a cell when ``--paths`` names none (the plan's figure).
SCREEN_PATHS = 48
#: The world's flags a screen's spec keeps (#172, PR H1): a folder started under one value of any
#: is refused under another. The workers, the name, the data folder, the cap in minutes, the
#: announcement and the estimate's override are not the world's.
SCREEN_WORLD = (
    "seasons",
    "forecasters",
    "shape",
    "bbm_as",
    "yahoo_as",
    "adp",
    "adp_spread",
    "grid",
    "league",
    "scoring",
    "points",
    "held",
    "waivers",
    "waiver_days",
    "waiver_rule",
    "budget",
    "rival_scale",
    "rival_bids",
    "h2h",
    "news_sd",
    "paths",
    "seed",
)
#: What a screen is, in its record.
SCREEN_NOTE = (
    "a screen nudges each lever of its list once against the baseline arm, on the same paths, "
    "each pair played by the code replay plays a pair with; it chooses no value, writes no knob "
    "file and reads no live league"
)


def timed_task(task: Callable[..., Any], *args: Any) -> tuple[float, Any]:
    """One task and the seconds it took, where it ran (a worker, or this process on one)."""
    t0 = clock.perf_counter()
    out = task(*args)
    return clock.perf_counter() - t0, out


def pair_args(args: argparse.Namespace, seasons: str) -> argparse.Namespace:
    """``screen``'s flags as ``replay`` reads a pair's: the seasons named, two arms (their specs
    are handed to :func:`replay_plan`, so no file is read), no room and no no-peek check."""
    return argparse.Namespace(
        **{
            **vars(args),
            "seasons": seasons,
            "arms": [Path("a"), Path("b")],
            "seats": None,
            "no_peek": None,
        }
    )


def remembering(read: Callable[..., SeasonRead] = read_season) -> Callable[..., SeasonRead]:
    """:func:`read_season` that remembers: a screen's pairs name one world, so a season is read
    once for each pair of beliefs its arms hold (what the read takes of the arms: nothing without
    stand-ins, each arm's ``system`` and ``blend`` with them, in the arms' order, which is the
    order the labels are kept in)."""
    kept: dict[Any, SeasonRead] = {}

    def again(
        data: Path,
        season: int,
        named: Sequence[fc.Forecaster],
        sources: Sources | None,
        arms: Mapping[str, rn.Arm],
        seed: int,
        shape: str,
        league_rules: shapes.LeagueRules = shapes.PLAIN,
    ) -> SeasonRead:
        systems = (
            None
            if sources is None
            else tuple((str(a.knobs["system"]), repr(a.knobs["blend"])) for a in arms.values())
        )
        key = (
            str(data),
            season,
            tuple(f.label for f in named),
            systems,
            seed,
            shape,
            repr(league_rules),
        )
        if key not in kept:
            kept[key] = read(data, season, named, sources, arms, seed, shape, league_rules)
        return kept[key]

    return again


def screen_pair(
    args: argparse.Namespace,
    specs: Sequence[Mapping[str, Any]],
    read: Callable[..., SeasonRead],
    said: set[str],
    whose: str,
) -> tuple[ReplayPlan, ReplayTasks] | int:
    """One pair of a screen as ``replay`` plans it (:func:`replay_plan`, :func:`replay_tasks`),
    or the exit code when ``replay`` refuses it. What the plan prints is printed once a screen:
    a line said for an earlier pair is not said again (``said``)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        plan = replay_plan(args, [dict(s) for s in specs], read)
        made = None if isinstance(plan, int) else replay_tasks(plan, args)
    if isinstance(plan, int) or made is None:
        print(buf.getvalue(), end="")
        print(f"refused: {whose} cannot be planned (the line above)")
        return plan if isinstance(plan, int) else 2
    for line in buf.getvalue().splitlines():
        if line not in said:
            said.add(line)
            print(line)
    return plan, made


def screen_scale(
    args: argparse.Namespace,
    base: Mapping[str, Any],
    read: Callable[..., SeasonRead],
    said: set[str],
    workers: int,
) -> dict[str, Any] | int:
    """The run's season scale (``screen.SCALE_NOTE``): the baseline on the surrogate tier, its
    scale's ratio on each path of the first cell (:func:`task_scale`: no day is played), the
    mean over the paths that have one. The exit code when the pair cannot be planned."""
    spec = sc.applied(base, {"tier": "surrogate"})
    got = screen_pair(args, [spec, spec], read, said, "the season scale's arm")
    if isinstance(got, int):
        return got
    _, made = got
    t0 = clock.perf_counter()
    rows = rn.run_tasks(task_scale, made.tasks[: made.paths], workers)
    ratios = [float(r["ratio"]) for r in rows if r is not None and r.get("ratio") is not None]
    first = made.keys[0]
    ratio = sum(ratios) / len(ratios) if ratios else None
    print(
        f"season scale: measured on {len(ratios)} of {made.paths} paths of the first cell "
        f"({first['season']} {first['forecaster']}) in {clock.perf_counter() - t0:.0f}s: "
        + ("none" if ratio is None else f"{ratio:.4g}")
    )
    return {
        "ratio": ratio,
        "paths": len(ratios),
        "of": made.paths,
        "cell": {"season": first["season"], "forecaster": first["forecaster"]},
        "note": sc.SCALE_NOTE,
    }


def screen_spec(
    args: argparse.Namespace, base: Mapping[str, Any], names: Sequence[str], plan: ReplayPlan
) -> dict[str, Any]:
    """What a screen's folder is started with and every later piece is held to: the code's
    ``screen_version`` and ``replay_version`` (a pair played under another is another pair), the
    baseline arm's spec verbatim, the levers named (in the list's order), the world's flags
    (:data:`SCREEN_WORLD`; the seasons as read), the fit's hash and, in a run whose rivals bid on
    the price book (PR Fd), the book's: a newer book is another world."""
    return {
        "screen_version": sc.SCREEN_VERSION,
        "replay_version": REPLAY_VERSION,
        "arm": dict(base),
        "levers": list(names),
        "world": {
            k: list(plan.seasons) if k == "seasons" else getattr(args, k) for k in SCREEN_WORLD
        },
        "fit_sha": plan.sha,
        **({} if plan.book is None else {"book_sha": plan.book[1]}),
    }


def screen_record(
    name: str,
    spec: Mapping[str, Any],
    plan: ReplayPlan,
    scale: Mapping[str, Any] | None,
    measure: str,
    rows: Sequence[sc.Row],
    results: Mapping[str, Mapping[str, Any]],
    timing: Mapping[str, Any],
) -> dict[str, Any]:
    """A screen's record: its spec, the code's commit and the fit's hash, the season scale used,
    the measure and the rule, every row of the list in its order (a played pair's with its
    result and its file, one still to play as left for the next piece), the survivors, what is
    left, and under ``timing`` everything that is a time: each pair's estimate and the pieces'
    start and end. Apart from ``timing`` a screen played in pieces records what one played
    unbroken does."""
    out = []
    for r in rows:
        d = r.payload()
        if r.key in results:
            d |= {"status": sc.PLAYED, "result": dict(results[r.key]), "file": f"{r.key}.json"}
        elif r.status == sc.PLAY:
            d["status"] = sc.LEFT
        out.append(d)
    rules = plan.league_rules
    return {
        "kind": "screen",
        "name": name,
        "screen_version": sc.SCREEN_VERSION,
        "note": SCREEN_NOTE,
        "spec": dict(spec),
        "code_sha": reader.code_sha(ROOT),
        "fit_sha": plan.sha,
        "fit_file": str(plan.fit_path),
        **({} if plan.book is None else {"book_sha": plan.book[1], "book_file": str(plan.book[2])}),
        "hold_out": plan.fit.get("hold_out", HOLD_OUT),
        "league": {"rules": rules.payload(), "label": rules.label()},
        "measure": measure,
        "rule": sc.RULE,
        "scale": None if scale is None else dict(scale),
        "rows": out,
        "survivors": [d["key"] for d in out if (d.get("result") or {}).get("survives")],
        "left": [d["key"] for d in out if d["status"] == sc.LEFT],
        "timing": dict(timing),
    }


def cmd_screen(args: argparse.Namespace) -> int:
    began = clock.perf_counter()
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    if args.max_minutes is not None and not args.max_minutes > 0:
        print("refused: --max-minutes is a span in minutes, above 0")
        return 2
    unknown = [n for n in args.levers or () if n not in sc.NAMES]
    if unknown:
        print(
            f"refused: lever {unknown[0]!r} is not in the screen's list: one of "
            f"{', '.join(sc.NAMES)}"
        )
        return 2
    names = [n for n in sc.NAMES if not args.levers or n in args.levers]
    seasons_text = args.seasons
    if seasons_text is None:
        latest = gate_season(args.data)
        if latest is None:
            print(
                "refused: no season a screen may play has a log on file under "
                f"{args.data / LOGS_DIR}"
            )
            return 2
        seasons_text = str(latest)
    try:
        looked = parse_seasons(seasons_text)
    except ValueError:
        looked = []  # refused by name below, as replay refuses it
    if CONFIRMATION in looked:
        print(
            f"refused: {CONFIRMATION} is the confirmation season; a screen is a search and never "
            "plays it"
        )
        return 2
    try:
        base = json.loads(Path(args.arm).read_text())
    except (OSError, ValueError) as e:
        print(f"refused: --arm: {e}")
        return 2
    if not isinstance(base, dict):
        print(f"refused: --arm: {args.arm} is not an arm's spec")
        return 2
    try:
        rn.arm_of(base)
    except (ValueError, KeyError) as e:
        print(f"refused: --arm: {e.args[0] if e.args else e}")
        return 2
    wa = pair_args(args, seasons_text)
    said: set[str] = set()
    read = remembering()
    got = screen_pair(wa, [base, base], read, said, "the baseline arm's world")
    if isinstance(got, int):
        return got
    plan, _ = got
    rules = plan.league_rules
    measure = sc.measure_of(rules.scoring, rules.h2h)
    ctx = sc.Context(rules.scoring, rules.waivers)
    rows = sc.rows_of(base, names, plan.shapes_read, ctx)
    workers = args.workers or rn.workers_default()
    name = args.name or "screen-" + "-".join(str(t) for t in plan.seasons)
    spec = screen_spec(args, base, names, plan)
    try:
        state = reader.read_screen(args.data, name)
    except reader.SimReadError as e:
        print(f"refused: {e}")
        return 2
    if state is not None:
        differs = sc.spec_differs(state.get("spec") or {}, spec)
        if differs is not None:
            print(
                f"refused: the screen {name!r} was started with another spec ({differs}); a "
                "screen is resumed on the spec it was started with: name this one another "
                "(--name)"
            )
            return 2
    scale = (state or {}).get("scale")
    if any(r.scale for r in rows):
        if scale is None:
            measured = screen_scale(wa, base, read, said, workers)
            if isinstance(measured, int):
                return measured
            scale = measured
        else:
            kept = "none" if scale["ratio"] is None else f"{scale['ratio']:.4g}"
            print(
                f"season scale: {kept}, on {scale['paths']} of {scale['of']} paths of the first "
                "cell, as the screen measured it when it was started"
            )
        ctx = replace(ctx, scale=scale["ratio"], no_scale=sc.NO_RATIO)
        rows = sc.rows_of(base, names, plan.shapes_read, ctx)
    refused = [r for r in rows if r.status == sc.REFUSED]
    for r in refused:
        print(f"refused: {r.why}")
    if refused:
        return 2
    results: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.status != sc.PLAY:
            continue
        try:
            pair = reader.read_screen_pair(args.data, name, r.key)
        except reader.SimReadError as e:
            print(f"refused: {e}")
            return 2
        if pair is None:
            continue
        if pair.get("specs") != {"a": dict(r.a or {}), "b": dict(r.b or {})}:
            print(
                f"refused: the screen {name!r} holds a pair {r.key} of other arms than this "
                "screen's: name this one another (--name)"
            )
            return 2
        results[r.key] = pair["screen"]["result"]
    todo = [r for r in rows if r.status == sc.PLAY and r.key not in results]
    before = dict((state or {}).get("timing") or {})
    estimates: dict[str, dict[str, Any]] = dict(before.get("estimates") or {})
    plans: dict[str, tuple[ReplayPlan, ReplayTasks]] = {}
    for r in todo:
        got = screen_pair(wa, [r.a or {}, r.b or {}], read, said, f"the pair of {r.key}")
        if isinstance(got, int):
            return got
        plans[r.key] = got
    firsts: dict[str, Any] = {}
    untimed = [r for r in todo if r.key not in estimates]
    if untimed:
        t0 = clock.perf_counter()
        timed = rn.run_tasks(
            timed_task,
            [(plans[r.key][1].task, *plans[r.key][1].tasks[plans[r.key][1].slow]) for r in untimed],
            workers,
        )
        for r, (seconds, first) in zip(untimed, timed, strict=True):
            estimates[r.key] = {"seconds_one": seconds, "tasks": len(plans[r.key][1].tasks)}
            firsts[r.key] = first
        print(
            f"one task of each of {len(untimed)} pair(s) timed in "
            f"{clock.perf_counter() - t0:.0f}s on {workers} workers"
        )

    def hours_of(key: str) -> float:
        e = estimates[key]
        return estimate_hours(float(e["seconds_one"]), int(e["tasks"]), workers)

    left_hours = sum(hours_of(r.key) for r in todo)
    whole_hours = (
        args.expected_hours
        if args.expected_hours is not None
        else sum(hours_of(r.key) for r in rows if r.status == sc.PLAY and r.key in estimates)
    )
    listed = [r.payload() for r in rows]
    texts = []
    for r, d in zip(rows, listed, strict=True):
        if r.key in results:
            texts.append("played before")
        elif r.status == sc.PLAY:
            e = estimates[r.key]
            texts.append(
                f"to play: {e['tasks']} tasks, one took {e['seconds_one']:.1f}s, about "
                f"{hours_of(r.key):.2f} h"
            )
        else:
            texts.append(sc.status_words(d))
    print(f"the screen {name}, its list as it would be played:")
    for line_ in sc.listing(listed, texts):
        print(line_)
    print(
        f"{len(todo)} pair(s) to play, about {left_hours:.2f} h on {workers} workers; the whole "
        f"screen ({len(todo) + len(results)} pairs) about {whole_hours:.2f} h"
    )
    audit_rules = audit.rules_of(rules.waivers, rules.waiver_rule)
    if args.dry_run:
        code = 0
        for r in untimed:
            made = plans[r.key][1]
            _, note = audited([made.keys[made.slow]], [firsts[r.key]], audit_rules)
            if note["paths_voided"]:
                print(f"the pair of {r.key}, its timed task:")
                code = max(code, audit_exit(note))
        print("dry run, nothing written")
        return code
    if todo:
        if whole_hours > ANNOUNCE_HOURS and not args.announced:
            print(
                f"refused: a screen of about {whole_hours:g} h is announced on the tracker and "
                "starts on the user's word, whatever a piece of it takes; --announced says that "
                "has happened"
            )
            return 2
        piece_hours = (
            left_hours if args.max_minutes is None else min(left_hours, args.max_minutes / 60.0)
        )
        ok, why = guard(piece_hours, rooms=args.rooms, announced=True)
        if not ok:
            print(f"refused: {why}")
            return 2
    piece: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "host": platform.node(),
        "workers": workers,
        "nice": NICE,
        "hash_seed": hash_seed(),
        "code_sha": reader.code_sha(ROOT),
        "played": [],
        "stopped": None,
    }
    # A run with nothing left to play of a screen on file is no piece: it writes the record
    # again from the pairs' files (the same record, unless a piece died between a pair's file and
    # the record) and prints the table.
    pieces = list(before.get("pieces") or [])
    if pieces and pieces[0].get("code_sha") != piece["code_sha"]:
        print(
            f"note: the screen was started on commit {pieces[0].get('code_sha')} and this run is "
            f"on {piece['code_sha']}; each piece records its own"
        )
    if todo or state is None:
        pieces.append(piece)
    timing = {"estimates": estimates, "pieces": pieces}

    def save() -> Path:
        return reader.write_screen(
            args.data,
            name,
            screen_record(name, spec, plan, scale, measure, rows, results, timing),
        )

    save()
    code = 0
    for r in todo:
        minutes = 60.0 * hours_of(r.key)
        spent = (clock.perf_counter() - began) / 60.0
        if args.max_minutes is not None and spent + minutes > args.max_minutes:
            piece["stopped"] = (
                f"--max-minutes {args.max_minutes:g}: the pair of {r.key}, about {minutes:.1f} "
                f"min, would pass it {spent:.1f} min from the start"
            )
            print(f"stopped: {piece['stopped']}")
            break
        pair_plan, made = plans[r.key]
        pair_plan = replace(pair_plan, started=datetime.now(UTC))
        t0 = clock.perf_counter()
        if r.key in firsts:
            rest = rn.run_tasks(
                made.task, made.tasks[: made.slow] + made.tasks[made.slow + 1 :], workers
            )
            ran = [*rest[: made.slow], firsts.pop(r.key), *rest[made.slow :]]
        else:
            ran = rn.run_tasks(made.task, made.tasks, workers)
        payload, note = replay_payload(pair_plan, wa, made, ran, workers, f"{name}-{r.key}")
        standing = [x for x in ran if not x.get("breaches")]
        result = sc.result_of(payload, standing, measure)
        payload["screen"] = {
            "name": name,
            "screen_version": sc.SCREEN_VERSION,
            **r.payload(),
            "status": sc.PLAYED,
            "result": result,
        }
        payload["finished_at"] = datetime.now(UTC).isoformat()
        path = reader.write_screen_pair(args.data, name, r.key, payload)
        results[r.key] = result
        piece["played"].append(r.key)
        save()
        print(
            f"{r.key}: {sc.result_words(result)} ({clock.perf_counter() - t0:.0f}s); written: "
            f"{path}"
        )
        code = max(code, audit_exit(note))
    piece["finished_at"] = datetime.now(UTC).isoformat()
    record = screen_record(name, spec, plan, scale, measure, rows, results, timing)
    path = reader.write_screen(args.data, name, record)
    print(
        f"the screen {name}: {sc.MEASURE_WORDS.get(measure, measure)}, B less A, one SE either "
        "way (advisory: a survivor is a candidate for the tune, not a finding)"
    )
    for line_ in sc.table(record["rows"]):
        print(line_)
    if record["left"]:
        print(
            f"left for the next piece: {', '.join(record['left'])}; the same command plays "
            "them and nothing played before"
        )
    print(f"written: {path}")
    # A pair of an earlier piece whose audit voided a path keeps the screen's exit code.
    return AUDIT_EXIT if any(x.get("voided") for x in results.values()) else code


# --------------------------------------------------------------------------- validate
def gate_dict(g: vg.Gate) -> dict[str, Any]:
    return {"name": g.name, "passed": g.passed, "season": g.season, "detail": g.detail}


#: What each seat's row of gate 5 records beside its count (#172, PR D4a2).
GATE_RECORDS = (
    "per seat and sampled day (detail.records): the exact tier's set and the surrogate's, the add "
    "and the drop by id; whether they are equal (the gate's input); and each set's worth by the "
    "exact tier's own objective on that day's problem, the value one evaluator of the exact "
    "tier's gives it on the key it searches (three weeks, with the season term at a "
    "season_weight), beside standing still's; a day left out says why. The worths do not enter "
    "the gate's rule"
)
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
    data: Path, season: int, f: fc.Forecaster, lag: int, seed: int, h2h: str = ONE_WIN
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Gate 5 on a replay (#172, PR D3): the league, the belief's weights and the world built as
    ``replay`` builds them for ``season`` and forecaster ``f`` (:func:`read_season`,
    :func:`replay_setup_of`, ``run.replay_world`` at the label's own weights), path 0; on each of
    the :data:`GATE_DAYS` after the first simulated day, for each of :func:`gate_seats`, whether
    the surrogate's set equals the exact set from day one's rosters (``checks.surrogate_matches``),
    at the knobs' defaults (``policy.KNOB_DEFAULTS``) and the fields' (``policy.DEFAULT_FIELDS``),
    in the head-to-head format ``h2h`` (the format PR: one win per matchup by default, so the two
    tiers are compared in the measure the seats play). One gate row a seat, and the block that
    names what the gate ran on. Refused (``readers.SimReadError``) when ``f`` cannot serve the
    season."""
    rules = shapes.LeagueRules(h2h=h2h)
    r = read_season(data, season, [f], None, {}, seed, GATE_SHAPE, rules)
    if not r.served:
        raise reader.SimReadError(f"{f.label} cannot serve {season}: {r.skipped[f.label]}")
    projection = projection_of(f, r.fixed, r.lines, seed, 0, GATE_SHAPE)
    setup = replay_setup_of(season, r.lines, r.members, r.scheduled, projection, league_rules=rules)
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
        records = checks.surrogate_records(setup, w, seat, days, knobs, fields)
        matches = [r["equal"] for r in records if r["left_out"] is None]
        g = vg.surrogate_gate(matches, season=season)
        g.detail.update({"seat": seat, "days": [d.isoformat() for d in days], "records": records})
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
        "records": GATE_RECORDS,
        "league": f"the fixed league shape ({shapes.FIXED.label()}); gate 5 is not run on a grid",
        "rules": rules.payload(),
    }
    return rows, block


def record_line(seat: int, r: Mapping[str, Any]) -> str:
    """One printed line of gate 5's record, a seat and a day: equal or not and the two sets'
    worths to four decimals, or why the day is left out. No player is named."""
    if r["left_out"] is not None:
        return f"seat {seat}, {r['day']}: left out, {r['left_out']}"
    worth = r["worth"]
    return (
        f"seat {seat}, {r['day']}: {'equal' if r['equal'] else 'differ'}; worth, exact "
        f"{worth['exact']:.4f}, surrogate {worth['surrogate']:.4f}"
    )


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
        h2h = shapes.parse_h2h("categories", args.h2h)
        inputs, fit, sha, fit_path = world_inputs(args.data)
    except (reader.SimReadError, ValueError, OSError) as e:
        print(f"refused: {e}")
        return 2
    rules = shapes.LeagueRules(h2h=h2h)
    t0 = clock.perf_counter()
    try:
        surrogate, block = gate_surrogate(args.data, season, forecaster, inputs.lag, args.seed, h2h)
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
        for r in d.get("records", ()):
            print("  " + record_line(d["seat"], r))
    days = len(block["days"]) * len(block["seats"])
    print(
        f"gate 5 on a replay of {block['season']} drafted on {block['forecaster']}: {days} "
        "league-days "
        f"({len(block['seats'])} seats x {len(block['days'])} days) in {took:.1f}s"
    )
    # The label leaves the default format unsaid; gate 5's line says it in either.
    under = rules.label() if h2h != ONE_WIN else f"{rules.label()}, {shapes.H2H_WORDS[h2h]}"
    print(
        f"gate 5 plays the fixed league shape: {shapes.FIXED.label()}, under {under} (validate "
        "takes no --scoring, --points or --held; --h2h names the format)"
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


def _cell_args(p: argparse.ArgumentParser, seasons: str | None) -> None:
    """The flags that name a run's cells (``replay``'s and ``screen``'s): its seasons, required
    when ``seasons`` (the help's words for the default) is None, its forecasters and an
    oracle's error."""
    p.add_argument(
        "--seasons",
        required=seasons is None,
        default=None,
        help=f"ESPN season ids, e.g. 2024 or 2022,2023,2024 or 2022-2024; never {HOLD_OUT}"
        + (f" (default {seasons})" if seasons else ""),
    )
    p.add_argument(
        "--forecasters",
        default="prior",
        help="the run's forecasters, comma separated: prior, espn, marcel, oracle:<spread> "
        "(default prior)",
    )
    p.add_argument(
        "--shape",
        choices=fc.SHAPES,
        default="stat",
        help="an oracle's error: stat, a draw a player and stat; minutes, a share of it common to "
        "the player's stats (default stat)",
    )


def _world_args(p: argparse.ArgumentParser) -> None:
    """The flags that name a run's world (``replay``'s and ``screen``'s): the two sources'
    stand-ins, the draft market, the league's shape and rules, its waivers and its format, and
    the told return date's spread."""
    p.add_argument(
        "--bbm-as",
        default=None,
        metavar="FORECASTER",
        help="the forecaster standing in for the first live source (system bbm); with --yahoo-as",
    )
    p.add_argument(
        "--yahoo-as",
        default=None,
        metavar="FORECASTER",
        help="the forecaster standing in for the second live source (system yahoo); with --bbm-as",
    )
    p.add_argument(
        "--adp",
        choices=adp.SOURCES,
        default="none",
        help="what the rivals draft on: none, the run's forecaster as before; espn, the average "
        "draft position in the season's own log (default none)",
    )
    p.add_argument(
        "--adp-spread",
        default=None,
        metavar="BASE,GROWTH",
        help="with --adp espn: a rival's error about the table, a normal draw at base + growth x "
        "pick picks; given, never fitted here",
    )
    p.add_argument(
        "--grid",
        choices=tuple(GRIDS),
        default="fixed",
        help="the league shapes the paths visit: fixed, the one league of twelve teams, thirteen "
        "slots, four adds a week and six playoff teams over three weeks; full, the ruled grid of "
        "72, a run's paths rounded up to a multiple of 72 (default fixed)",
    )
    p.add_argument(
        "--league",
        default=None,
        metavar="KEY=VALUE,...",
        help="one league shape for the whole run, as teams=10,slots=15,adds=none,playoffs=4/2: "
        "each a value of the grid's, a key left out the fixed shape's; not with --grid full",
    )
    p.add_argument(
        "--scoring",
        choices=shapes.SCORINGS,
        default="categories",
        help="how the run's league scores, on every path: categories, the nine; points, on "
        "--points or ESPN's default table (default categories)",
    )
    p.add_argument(
        "--points",
        default=None,
        metavar="STAT=W,...",
        help="with --scoring points: the table, a stat's points per unit, as pts=1,reb=1.2; a "
        "stat left out scores nothing (default ESPN's default table)",
    )
    p.add_argument(
        "--held",
        default=None,
        metavar="IL=N,IL+=N",
        help="the held slots after the bench, on every path, as IL=2,IL+=1: IL 0 to 2, IL+ 0 or 1 "
        "(default none)",
    )
    p.add_argument(
        "--waivers",
        default="none",
        metavar="KIND",
        help="how a dropped player is added back, on every path: none, a free agent the next "
        "morning; priority, he waits --waiver-days and a claim on him goes by rolling waiver "
        "priority; faab, he waits and a claim carries a sealed bid from the team's budget, the "
        "highest bid first, a tie by priority (default none)",
    )
    p.add_argument(
        "--waiver-days",
        default=None,
        metavar="N",
        help=f"with --waivers priority or faab: the days a dropped player waits, 1 to 7 (default "
        f"{shapes.WAIVER_DAYS})",
    )
    p.add_argument(
        "--waiver-rule",
        default=None,
        metavar="RULE",
        help="with --waivers priority or faab, which adds are claims: dropped, a dropped player's "
        "in his wait, every other add a free agent's the next morning; continuous, every add, "
        "one on a player nobody dropped lately decided the next morning (default dropped)",
    )
    p.add_argument(
        "--budget",
        default=None,
        metavar="DOLLARS",
        help=f"with --waivers faab: the whole dollars each team starts with, 1 to 1000 (default "
        f"{shapes.BUDGET})",
    )
    p.add_argument(
        "--rival-scale",
        default=None,
        metavar="X",
        help="with --waivers faab: what a market rival's bid is multiplied by, above 0, an "
        "assumption to sweep (default 1)",
    )
    p.add_argument(
        "--rival-bids",
        default=None,
        metavar="HOW",
        help="with --waivers faab, how a market rival bids: assumed, the assumed form; book, a "
        "draw on the newest price book under data/sim/bids/ (fit-bids writes it) (default "
        "assumed)",
    )
    p.add_argument(
        "--h2h",
        default=None,
        metavar="FORMAT",
        help="a categories league's head-to-head format, on every path: one_win, a week is one "
        "result, won by the side with more categories; each_category, each category of a week "
        "is a result and the standings rank by the category percentage; not with --scoring "
        "points (default one_win)",
    )
    p.add_argument(
        "--news-sd",
        type=float,
        default=world.NEWS_SD_DAYS,
        help=f"the told return date's spread in days (default {world.NEWS_SD_DAYS:g})",
    )


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
    fb = sub.add_parser(
        "fit-bids",
        help="the rivals' price book from the public leagues' winning bids, written with a hash",
    )
    fb.add_argument("--dry-run", action="store_true", help="print the book, write nothing")
    fb.set_defaults(func=cmd_fit_bids)
    re_ = sub.add_parser("replay", help="a made-up league on a recorded season's lines")
    _cell_args(re_, None)
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
    _world_args(re_)
    re_.add_argument(
        "--no-peek",
        default=None,
        metavar="YYYY-MM-DD",
        help="check one path of one season against it changed after this date; writes nothing",
    )
    _run_args(re_, paths=20)
    re_.set_defaults(func=cmd_replay)
    sn = sub.add_parser(
        "screen", help="each lever nudged once against a baseline arm, and what moved"
    )
    sn.add_argument(
        "--arm",
        type=Path,
        required=True,
        metavar="SPEC",
        help="the baseline arm's spec file: arm A of every pair, arm B is A with one nudge",
    )
    sn.add_argument(
        "--levers",
        nargs="+",
        default=None,
        metavar="NAME",
        help="the levers to screen, by name, in the list's order whatever the order named "
        f"(default every lever of the list: {', '.join(sc.NAMES)})",
    )
    _cell_args(
        sn, "the latest season on file that is neither the hold-out nor the confirmation season"
    )
    _world_args(sn)
    sn.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="N",
        help="start no pair whose estimate would pass N minutes from the start: stop cleanly and "
        "say what is left, which the same command plays later",
    )
    _run_args(sn, paths=SCREEN_PATHS)
    sn.set_defaults(func=cmd_screen)
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
    va.add_argument(
        "--h2h",
        default=None,
        metavar="FORMAT",
        help="gate 5's league's head-to-head format, the measure its seats weigh in: one_win, the "
        "matchup's odds; each_category, expected categories (default one_win)",
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
