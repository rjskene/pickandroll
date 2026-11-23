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
    python -m pickandroll.sim tune --arm BASE.json --screen NAME --seasons 2023,2024

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
pairs is taken up again by the same command. ``tune`` searches the levers a screen left standing,
one lever at a time (``sim/tune.py``), each value a pair against the current arm on every season
and forecaster named, never the hold-out and never the confirmation season, then plays the final
set against the baseline once on the season the search never played, counts that look on the
confirmation season's ledger, and writes a folder under ``data/sim/tunes/``; it recommends and
promotes nothing.

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
from collections.abc import Callable, Iterable, Mapping, Sequence
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
from . import trace as tr
from . import tune as tn
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
SIMULATING = ("replay", "validate", "screen", "tune", "trace")
HASH_SEED_NOTE = (
    "PYTHONHASHSEED is unset: at an exact tie the outcome may differ between processes (an "
    "order-dependent sum in the engine's evaluator); a run to be reproduced sets PYTHONHASHSEED=0"
)


def hash_seed() -> str:
    """The process's ``PYTHONHASHSEED`` as the run record keeps it: its value, or ``"random"``
    when it is unset (or empty, which Python reads as unset)."""
    return os.environ.get("PYTHONHASHSEED") or "random"


#: What an arm's ``bid`` block is (#172, PR F2), beside the block in the payload of a run whose
#: arm names one.
BID_NOTE = (
    "an arm listed under bid names a bid block, every key here with its value in force: in a "
    "FAAB run its seat on the exact or the surrogate tier, and its mirror rivals, bid by the "
    "bid policy family (sim/bid_policy.py) in place of the live rule the league's FAAB note "
    "describes: the move's value in typicals weighed over the week, the three weeks (the rest "
    "of the weight) and the season; times a pace, the seat's share of the budget left over a "
    "spending path, to the power k, read on the morning the claim is decided; a base of one "
    "typical or less bids the routine dollars, a larger one the base times faab_sizing; then "
    "at most the richest other team's dollars left plus one (rival_cap), at most a quantile of "
    "the other teams' winning bids of the season so far plus one (shade), and the clamp to the "
    "dollars left. It reads only what a manager sees: no sealed bid, no losing bid, nothing of "
    "the rivals' bid model. A plan's step keeps the live rule's value. With every key at its "
    "default it is the live rule; an arm not listed names none and bids by the live rule "
    "itself; outside a FAAB run the block is read by nobody (reads)"
)


def bid_block(arms: Mapping[str, rn.Arm] | None) -> dict[str, Any]:
    """The arms' bid policies for the payload (#172, PR F2): under ``bid``, by the arm's key,
    every key of the block with its value in force (``bid_policy.BidPolicy.payload``) for each
    arm that names one, and :data:`BID_NOTE` beside it; nothing at all in a run whose arms name
    none (Rule 1)."""
    named = {k: arm.bid.payload() for k, arm in (arms or {}).items() if arm.bid is not None}
    return {"bid": named, "bid_note": BID_NOTE} if named else {}


def bid_lines(
    arms: Mapping[str, rn.Arm], shapes: Sequence[policy.Shape], rivals: bool
) -> list[str]:
    """What a run says of each arm that names a ``bid`` block (#172, PR F2), before any path, in
    a dry run and in the no-peek check alike: the block in words, and why the run's league does
    not read it when it does not (``policy.bid_reads``)."""
    out = []
    for key, arm in arms.items():
        if arm.bid is None:
            continue
        mirror = rivals and rn.mirrored(arm)
        whys = [policy.bid_reads(arm, shape, mirror) for shape in shapes]
        unread = "" if policy.READ in whys or not whys else f"; not read in this run: {whys[0]}"
        whose = f"arm {key.upper()} ({arm.name})" if rivals else f"arm {key}"
        out.append(f"bid policy, {whose}: {arm.bid.label()}{unread}")
    return out


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
    table's hash beside the fit's, in a run that names it only. An arm that names a ``bid``
    block (PR F2) is listed under ``bid`` (:func:`bid_block`). An arm's ``fields`` carry its
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
        **bid_block(arms),
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
    "dollars_at_bracket": "dollars left on the first day of the bracket, after that morning's "
    "claims (none where no bracket is read)",
    "weeks_at_zero": "weeks the seat stood at $0: its days with nothing left, over seven (0 "
    "when it never ran dry)",
    "value_won": "the value of the claims won, in typicals: what each bid was sized on when it "
    "was placed (the bid policy's value; the three weeks' gain over the seat's typical gain by "
    "default), summed, to divide by dollars_spent; a claim whose gain is 0 or less on a typical "
    "at or below 0 counts 0 and one whose gain is above 0 there counts 1; 0 for a seat that "
    "holds no gain in the engine's units (the ranking tier, a market rival)",
}


#: What the stash count is (PR G): only in a run where an arm names a stash threshold.
STASH_NOTE = {
    "returning_dropped": "players who left the seat's roster (a move's drop, a churn's held "
    "drop, a drop a returning held player forced) whom the engine read as returning on the "
    "seat's problem the day before (moves.returning_net: out, back this season and worth "
    "something then; a claim's drop as read the day the claim was placed); null for a seat "
    "that builds no problem (a market or a static rival)",
}
#: What each of the queue's counts is (PR E): only in a run where an arm executes ``queue``,
#: after every other count, in every seat's row (0 for a seat that does not take the rule).
PLANS_NOTE = {
    "plan_days": "days the queue took a week plan instead of the three weeks' set (the queue's "
    "rule; a streaming plan executed beside a set is not counted here)",
    "plan_steps": "steps of those plans queued: a free agent's add for the next morning, or a "
    "claim placed; whether each landed is in landed, gone and the claim counts",
}

#: What the guard's and the stake's counts are (the guard PR), by the arm field whose naming
#: brings them (``counts.SEASON``): a run's in which an arm names that field, on the seats of
#: its arms on the exact or the surrogate tier. ``sets_past_guard`` is a lower bound on how
#: often the block would have turned an ``off`` seat's decision, and the note says so: the
#: count asks the guard about the decided set alone (``policy.mark_past_guard``).
SEASON_NOTE = {
    "guard": {
        "sets_past_guard": "sets the seat decided that the season guard would have refused (the "
        "rest of the season below 0 by the engine's own figure), before the day's cap and the "
        "week's adds cut them: 0 for an arm on the block, by construction; for an arm with the "
        "guard off a lower bound on how often the block would have turned its decision, not "
        "that number (the block tests every set a search tries, so it can end on another set "
        "where the set decided here passes as a whole and is not counted; the exact tier's "
        "week set and week plan are not asked about)",
    },
    "stake": {
        "stake_mean": "the week's stake L for the seat, its mean over the weeks played (the "
        "standings it reads are the arm's own season's; an arm's stake field does not change "
        "what L is, only whether its season term reads it)",
        "stake_weeks_above_half": "the weeks whose stake L was above a half",
    },
    # The union pool's (PR pool): a run's in which an arm on the exact tier sets guard_pool
    # above 0, on its arms' seats on the exact tier.
    "guard_pool": {
        "union_days": "decision days on which the seat's search took a union pool (its best "
        "`pool` adds by single move, then the guard's list of `guard_pool`): every decision day "
        "of an arm with guard_pool above 0, and 0 for an arm at 0, by construction, as are the "
        "four below",
        "union_admitted": "adds the guard's list brought that the head did not hold, summed over "
        "those days (over union_days it is their mean a day)",
        "union_admitted_days": "days the guard's list brought at least one such add",
        "union_taken_days": "days the seat queued or claimed a move of its set whose add the set "
        "took from the guard's list and not from the head, the day's cap and the week's adds "
        "applied: a listed add went out (never a day a plan leads under the queue's rule)",
        "union_head_refused_days": "days the season guard refused the best single move of at "
        "least one add of the head (a move that gains more than min_gain): how often the cut "
        "before the guard costs the search an add",
    },
}


def queue_run(arms: Iterable[rn.Arm]) -> bool:
    """Whether one of the run's arms takes the queue's rule (``executes: queue``, PR E)."""
    return any(arm.executes == policy.QUEUE for arm in arms)


def counts_note(
    waivers: str = "none",
    stash: bool = False,
    counted: Sequence[str] = (),
    queue: bool = False,
) -> dict[str, str]:
    """The counts' note for a run under ``waivers``: :data:`COUNTS_NOTE`, the claims' too in a
    waiver run, and in a FAAB run the bids' with the claims' said for bids; ``stash``: the run
    names a stash threshold (``run.stash_named``, PR G), and the note says its count; then the
    notes of the season fields the run's arms name and of the union pool's counts when an
    arm sets ``guard_pool`` (``counted``, ``run.counted_of``; :data:`SEASON_NOTE`), none for
    a run that names none; ``queue``: the run has an arm that
    executes ``queue`` (:func:`queue_run`, PR E), and the queue's counts' follow."""
    if waivers == "none":
        note = COUNTS_NOTE
    elif waivers == "faab":
        note = {**COUNTS_NOTE, **CLAIMS_NOTE, **FAAB_CLAIMS_NOTE, **BIDS_NOTE}
    else:
        note = {**COUNTS_NOTE, **CLAIMS_NOTE}
    if stash:
        note = {**note, **STASH_NOTE}
    if counted:
        note = {**note, **{k: v for f in counted for k, v in SEASON_NOTE[f].items()}}
    return {**note, **PLANS_NOTE} if queue else note


def audit_rules(league_rules: shapes.LeagueRules, grid: shapes.Grid) -> tuple[audit.Rule, ...]:
    """The rules a replay on ``grid`` under ``league_rules`` is held to, for its record
    (``audit.rules_of``): its waivers' and its waiver rule's, and the bracket's (PR bracket) when
    a league shape of the grid has a round to play, as each path's own audit reads it
    (``audit.has_round``). Every shape of the ruled grid has one: a replay's league is drafted
    with its bracket (``run.replay_setup``)."""
    bracket = any(s.playoff_teams > 1 and s.playoff_weeks > 0 for s in grid.shapes)
    return audit.rules_of(
        league_rules.waivers, league_rules.waiver_rule, bracket, league_rules.same_day
    )


def audited(
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    rules: Sequence[audit.Rule] | None = None,
) -> tuple[list[bool], dict[str, Any]]:
    """Which tasks stand and the payload's audit block. A task with a breach is a voided path: it
    is left out of every aggregate, and each breach is listed with the task it voids. ``rules``,
    the rules the run was held to (:func:`audit_rules`: its waivers, its waiver rule and its
    bracket; :data:`audit.RULES` by default)."""
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
    its fields when its spec names them (``policy.season_reads``, the guard PR); for an arm
    that names a ``bid`` block (PR F2) the block's row (``policy.bid_reads``); and for an arm
    that executes ``queue`` only (PR E), ``notes``: what the table says beside a row
    (``policy.read_notes``: where the season term stands in the queue's rule). An arm's fields
    are the ones its record names (``policy.Fields.payload``): ``guard_pool`` has a row only
    for an arm that sets it above 0 (PR pool), so an arm that leaves it off has the four rows
    it had."""
    out: dict[str, Any] = {}
    for key, arm in arms.items():
        mirror = rivals and rn.mirrored(arm)
        notes = policy.read_notes(arm)
        named = arm.fields.payload()
        fields = {k: v for k, v in policy.field_reads(arm, mirror).items() if k in named}
        out[key] = {
            shape.label(): {
                "knobs": policy.reads(arm, shape, mirror),
                "fields": fields
                | {k: v for k, v in policy.season_reads(arm, shape).items() if k in arm.named},
                **({} if arm.bid is None else {"bid": policy.bid_reads(arm, shape, mirror)}),
                **({"notes": notes} if notes else {}),
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
        lineup_from=league_rules.lineup_from,
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
    seat_draft: str | None = None,
) -> list[dict[str, Any]]:
    """Every draft of ``grid``'s league shapes that may not fill (#172, PR D4b), one record a
    season, forecaster, team count with roster size, and board: the draft takes teams times the
    slots that are not held (``need``), and a board holds fewer (``holds``). The board is the
    pool, the season's draftable players on the cell's forecaster (``run.draftable_of``),
    which every seat drafts from without a table and every rival's board is under one; or,
    under a table (``picks``, by season), an arm's seat's own board, its forecaster's draftable
    players (under ``seat_draft`` ``adp.MARKET_DRAFT`` the players it does not pass on, a split
    seat's by its rostered side: :func:`passing_label`). Rivals could take every player on that
    board, so it is held to the whole draft's
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
                split = splits_of(sources, arms)
                for key, arm in arms.items():
                    label = passing_label(seat_draft, arm.forecaster, split)
                    own = own_projection(label, f.label, projection, forecasts)
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
#: picks, the rivals' spread and how an arm's seat drafts (``adp.SEAT_DRAFTS``, the draft PR);
#: None under ``--adp none``.
Market = tuple[Mapping[int, float], adp.Spread, str] | None
#: A trace's hook into a pair's task (PR trace, :func:`task_paired`): handed each arm's league by
#: its key and the seat, it returns the season's ``on_day`` and ``on_end``.
Watch = Callable[
    [Mapping[str, Any], int],
    tuple[
        Callable[[rn.DayRecord], None] | None,
        Callable[[rn.VariantResult, rn.VariantResult], None] | None,
    ],
]


def seat_draft_of(args: argparse.Namespace) -> str | None:
    """How a run's arms' seats draft (``adp.SEAT_DRAFTS``): the rule ``--seat-draft`` names, the
    market's when it names none; None without a table, where nobody drafts from a market."""
    if args.adp == "none":
        return None
    return args.seat_draft or adp.MARKET_DRAFT


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


def passing_label(
    rule: str | None, label: str | None, split: Mapping[str, str] | None
) -> str | None:
    """The label whose table a seat holding ``label`` is named with in a draft under ``rule``
    (``adp.SEAT_DRAFTS``). Under ``adp.OWN_DRAFT`` its own: the board it ranks, a split label's
    available side as the run builds it for day one. Under ``adp.MARKET_DRAFT`` the table it
    passes by, which is what it will believe of a player once he is on its roster: a split
    label's rostered side (``split``, :func:`splits_of`: the first stand-in's), any other
    label's own. A ``yahoo`` or ``blend`` seat that passed by its available side would draft a
    player only the second stand-in projects and read him at nothing from the first day."""
    if rule == adp.MARKET_DRAFT and label is not None:
        return (split or {}).get(label, label)
    return label


def draft_of(market: Market, seed: int, path: int, own: Mapping[int, Any]) -> adp.Draft:
    """A path's draft on a ``market`` with the arms' seats ``own`` (by team, each arm's
    forecaster's projection), under the market's rule. ``adp.OWN_DRAFT`` is ``adp.Draft``'s own
    default and names nothing more, as before the draft PR."""
    assert market is not None
    if market[2] == adp.OWN_DRAFT:
        return adp.Draft(market[0], market[1], seed, path, own)
    return adp.Draft(market[0], market[1], seed, path, own, rule=market[2])


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
    split: Mapping[str, str] | None = None,
) -> adp.Draft | None:
    """A room's draft under a ``market`` on one path (#172, PR D4a). Every seat holds an arm
    and is named with its arm's forecaster's projection: under ``adp.MARKET_DRAFT`` (the draft
    PR, the default) each drafts as the rival in its seat would, less the players its own arm
    cannot value (a split seat by its rostered side, ``split``: :func:`passing_label`); under
    ``adp.OWN_DRAFT`` every seat drafts on its arm's own board. None without a market. The
    seats are the path's league shape's and the arms are rotated by its ``turn`` (#172, PR
    D4b; the path's on one shape); the rivals' draws stay on the path."""
    if market is None:
        return None
    rotation = path if turn is None else turn
    own = {
        t: own_projection(
            passing_label(market[2], arms[name].forecaster, split),
            run_label,
            projection,
            forecasts,
        )
        for t, name in rn.rotate(seats, league.ids, rotation).items()
    }
    return draft_of(market, seed, path, own)


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
    split: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The pair's league on one path, by arm (#172, PR D4a), in the path's league shape (#172,
    PR D4b) under the run's league rules (PR D4c): one league drafted on the run's forecaster
    without a ``market``. Under one, the arm's seat drafts by the market's rule (the draft PR)
    and every other seat on a rival's board: under ``adp.MARKET_DRAFT``, the default, as the
    rival in its seat would, less the players the arm cannot value; under ``adp.OWN_DRAFT`` on
    the arm's own board. Arms whose seats are named with one label's table share one league
    (the same object), arms on two get one each. That label is the arm's draft-day belief's,
    but under ``adp.MARKET_DRAFT`` a split seat's is its rostered side's (``split``,
    :func:`passing_label`): a ``yahoo`` or ``blend`` arm passes on the players its ``bbm``
    baseline passes on, and the two are one league on every path. Under ``adp.MARKET_DRAFT``
    two arms on two tables share one league all the same when their two drafts come out the
    same league (every roster equal: the two tables lack the same players, or differ only on
    players the seat never reached): nothing else of a setup reads the arm. The arm's seat is
    the shape's ``teams[turn mod n]`` (the path's turn; the path itself on one shape)."""
    if market is None:
        setup = replay_setup_of(
            season, lines, members, scheduled, projection, None, league, league_rules
        )
        return dict.fromkeys(pair, setup)
    me = league.ids[(path if turn is None else turn) % league.teams]
    labels = {k: passing_label(market[2], arms[k].forecaster, split) or run_label for k in pair}
    setups: dict[str, Any] = {}
    for k in pair:
        same = next((setups[j] for j in setups if labels[j] == labels[k]), None)
        if same is not None:
            setups[k] = same
            continue
        own = own_projection(labels[k], run_label, projection, forecasts)
        setup = replay_setup_of(
            season,
            lines,
            members,
            scheduled,
            projection,
            draft_of(market, seed, path, {me: own}),
            league,
            league_rules,
        )
        if market[2] == adp.MARKET_DRAFT:
            setup = next((x for x in setups.values() if x.rosters == setup.rosters), setup)
        setups[k] = setup
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
    arm: each drafts as the rival in its seat would less the players its arm cannot value, or
    under ``adp.OWN_DRAFT`` on its arm's own board (:func:`room_draft`). The path plays
    its league shape on ``grid`` with the arms rotated by its turn (``shapes.visit``, #172, PR
    D4b), under the run's ``league_rules`` (PR D4c); the world's draws stay on ``(seed,
    path)``."""
    v = shapes.visit(path, grid)
    projection = projection_of(forecaster, fixed, lines, seed, path, shape)
    forecasts = forecasts_of(sources, fixed, lines, seed, path, shape, arms)
    draft = room_draft(
        market,
        arms,
        seats,
        forecaster.label,
        projection,
        forecasts,
        seed,
        path,
        v.shape,
        v.turn,
        splits_of(sources, arms),
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
        splits_of(sources, arms),
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
    watch: Watch | None = None,
) -> dict[str, Any]:
    """One task of the paired design on a replay (#172, PR D2): the league drafted on the cell's
    forecaster, arm A in seat :func:`seat_of` in one season and arm B in the same seat in a
    second, through one world (``run.paired``); every other seat is each arm's rivals, on the
    run's forecaster. ``pair`` names the two arms' keys in ``arms`` (``a`` and ``b``).

    Under a ``market`` (#172, PR D4a) the arm's seat drafts by the market's rule (the draft PR:
    as the rival in its seat less the players the arm cannot value, or on the arm's own board)
    and the other seats on rivals' boards. When the two arms' draft-day beliefs are one label
    there is one draft and one league, as before; when they differ, and the two drafts are not
    the same league (:func:`pair_setups`), each arm's season is its own league from the draft
    on (``run.paired_apart``): two setups and two worlds on the same ``(seed, path)``, so the
    world's draws and the rivals' boards stay common.

    The path plays its league shape on ``grid``, and the seat is the shape's ``teams[turn mod
    n]`` (``shapes.visit``, #172, PR D4b): both arms hold one shape and one seat. Every path
    plays the run's ``league_rules`` (PR D4c).

    ``watch`` (PR trace): handed each arm's league by its key and the seat once the path's
    leagues are built, it returns the season's ``on_day`` and ``on_end`` (``run.paired``'s); a
    trace's recorder. Without one the task is as it was, and with one its result is too."""
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
    on_day, on_end = (None, None) if watch is None else watch({k: setups[k] for k in pair}, me)
    if sa is sb:
        out = rn.paired(sa, worlds[id(sa)], a, b, me, on_day=on_day, on_end=on_end)
    else:
        out = rn.paired_apart(
            sa, worlds[id(sa)], sb, worlds[id(sb)], a, b, me, on_day=on_day, on_end=on_end
        )
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


#: The replay's version in its payload: 20 since the union pool as an arm's choice (#172, PR
#: pool), 19 since the bracket's rounds (#172, PR bracket), 18
#: since the bid policy (#172, PR F2), 17 since the
#: queue's rule (#172, PR E), 16 since the season guard as an arm's choice and the
#: week's stake (the guard PR), 15 since the stash threshold (#172, PR G), 14 since the
#: arm's seat drafts from the market's board (the draft PR), 13 since the rivals' adds and bids
#: (PR Fd),
#: 12 since continuous waivers (PR Fc), 11 since the
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
REPLAY_VERSION = 21
REPLAY_VERSION_WHY = (
    "21: a league whose free-agent adds play the same day: a league rule of the run, "
    "lineup_from (--lineup-from, tomorrow by default, today); under today a free agent's add "
    "decided on a day lands that day, once every seat has decided on the morning's wire and "
    "before the day's lineups, in the day's rotation, with its drop and its held-slot moves, "
    "and his line of the day is his new team's; a claim is decided as before and charged to "
    "the week it clears in (on a Monday the week starts over before the morning); the seat's "
    "problem is the live build's (a free agent effective today, the weeks' own add windows); "
    "the audit holds such a league to lands_same_day in the place of lands_next_day, and its "
    "claim rules read each winner's roster after the morning, before the day's landing; the "
    "record names the rule in the league's rules, the label, the execution model "
    "(free_agents_same_day, with a name of its own for each kind of waivers) and lineup_note; a "
    "screen's or a tune's world names the flag only when named, and the rule is part of the "
    "league kind; under continuous waivers every add is a claim and the rule moves nothing; "
    "with the rule left off the figures are version 20's. Beside it, --league adds takes any "
    "positive whole count (the private league allows five), the grid's own axis unchanged. "
    "20: the union pool as an arm's choice: an arm may set a fifth field, guard_pool, the size "
    "of the guard's list (0, the default, is off); above 0, while the arm's guard blocks, the "
    "exact tier's three weeks' set, its weighted search and under the queue's rule its week's "
    "set are searched among the engine's union pool (season.pool: the best pool adds by single "
    "move, then the adds whose best single move the season guard admits), as live searches "
    "since #424; an arm's fields and its reads table carry guard_pool only above 0, and a run "
    "in which an arm on the exact tier sets it adds five counts on its arms' seats on the "
    "exact tier (union_days, union_admitted, union_admitted_days, union_taken_days, "
    "union_head_refused_days); with the field left off the figures are version 19's. "
    "19: the bracket's rounds: in a week of the bracket a seat's problem reads its round's "
    "opponent, seeded that morning from the variant's own totals as the season's end seeds it "
    "(before, the week had no opponent and was worth nothing): the weighted set weighs the "
    "matchup, a week's plan can be drawn there, the queue's rule takes a plan on the matchup's "
    "odds in a round the seat plays, and a bid that weighs the week sizes a claim against the "
    "round's opponent; the view of the week a decision is keyed on (version 18) holds the "
    "round's pair; the audit holds the round's pairs (bracket_pairs); a seat that executes the "
    "three weeks' set alone and names no bid on the week plays version 18's season. "
    "18: the bid policy: an arm's spec may name a bid block; its seat on the exact or the "
    "surrogate tier, and its mirror rivals, then bid in a FAAB league by a family of rules whose "
    "default member is the live rule (the gain weighed over the week, the three weeks and the "
    "season; a pace against a spending path; the routine dollar; a cap at the richest other "
    "team's dollars left plus one; a shade at a quantile of the other teams' winning bids plus "
    "one); a week plan's step keeps the live value, under the queue's rule too, where the "
    "executor says which claim is a step; the bid reads the season figure with no stake; the "
    "reads table has the block's row, playoff_weight is read by a seat that bids on an arm whose "
    "bid weighs the season, and a plan floor is not read as a seat's typical gain where the bid "
    "gives the three weeks no weight; a run whose arm names a block records it under bid; a "
    "decision is shared between two variants only on one view of the week (its team's opponent "
    "and both sides' totals so far) for a strategy that reads the week: the exact tier on the "
    "weighted set, the queue's rule or a week's plan, and a seat or a mirror rival whose bid "
    "weighs the week; with no bid named the figures are version 17's, but for two arms of one "
    "name whose seat reads the week (apart only in their rivals or in execute_plan), which "
    "could be handed each other's decision before, and a FAAB run's counts gain three keys "
    "(dollars_at_bracket, weeks_at_zero, value_won). "
    "17: the queue's rule: an exact arm's executes may name queue, the live queue's rule (the "
    "three weeks' set as three finds it, then the week plan the engine's plans.for_queue takes "
    "instead of it: the plan with the highest score that beats the set by the plan floor, the "
    "score the week's gain plus the arm's three_weight times the three weeks' gain, the weight 0 "
    "in a week of the bracket), its steps queued on the days they are due and the plan drawn "
    "again every day; queue is refused off the exact tier, and with_plan or execute_plan beside "
    "it; no rival takes it; under FAAB a step of the plan the queue took bids on its score at the "
    "queue's weight; three_weight is read by the exact tier executing queue and a plan floor "
    "there too; a run with a queue arm counts plan_days and plan_steps in every seat's row and "
    "its reads table carries a note on the season term (on the three weeks' set only: not in the "
    "plans' gate, and the season guard does not read it); under an arm's guard off every call of "
    "the rule is handed no allowed set, the plans and the queue's choice too, and the note says "
    "that; the names of who leaves when a held player comes back are made with what the seat "
    "queues that night made (the set's moves and the plan's steps due that can land together, or "
    "a leading plan's steps due), so in a league with held slots an arm that executes its plan "
    "may play another season than version 16's; with no arm naming queue and none executing a "
    "plan in a league with held slots, the figures and the counts are version 16's, and the reads "
    "table's reason for three_weight changes in words. "
    "16: the season guard as an arm's choice and a season term that reads the week's stake: an "
    "arm's spec may name guard (block, the season guard on every search of its tier, live's and "
    "the default; or off, no search of the tier is handed an allowed set) and stake (0 to 1, 0 by"
    " default: the season term that week is season_weight x (this week's part + (1 - stake x L) x"
    " the rest), a move's season figure split at the running week's last day, L the week's stake "
    "for the seat from the finished weeks' standings, in the bracket's weeks 1 inside the field "
    "and 0 for a top seed in the week of its bye; the figure as it was when stake x L is 0); an "
    "arm's fields and its reads table carry the two only when its spec names them; a run in which"
    " an arm names guard counts sets_past_guard (the sets decided that the guard would have "
    "refused, a lower bound on how often the block would have turned a decision), and one in "
    "which an arm names stake counts stake_mean and stake_weeks_above_half, on the seats of its "
    "arms on the exact or the surrogate tier; season_scale's rows gain paths_with_ratio (the "
    "paths whose row holds a ratio) in every run that has a scale; with neither field named every"
    " other figure and key is version 15's. "
    "15: the stash threshold: an arm's stash_threshold is set on its seat's problem and read "
    "there by the engine's searches on the exact and the surrogate tier (a set that drops a "
    "returning player the threshold keeps is refused; the ranking tier's one swap is not held to "
    "it, a mirror rival keeps none); a seat that plans with the engine names who leaves the "
    "morning one of its held players comes back, the drop the engine's plan charges on the seat's "
    "own problem, and the morning takes him when he is still one of the team's active players "
    "(else, and for a seat that names none, the least valuable active player, as before); a run "
    "where an arm names a threshold counts the returning players each seat dropped "
    "(returning_dropped); a league without held slots with no threshold named has the figures of "
    "the version before (its record differs in one word, the reads table's row for the knob), "
    "and a league with held slots may differ from them at any threshold, none included, on the "
    "mornings a returning held player forces a drop; and no add lands in a held slot: a swap "
    "whose drop one of the morning's held-slot moves took to a held slot is gone, as a claim "
    "whose drop is no longer an active player fails (before, an arm that executes its plan beside "
    "its set could land a step's add in the slot its drop sat in, a season the audit refused). "
    "14: the arm's seat's draft under a table (--adp espn): it drafts as a rival does, from the "
    "market's board (the listed players by average pick plus a draw at the spread, the unlisted "
    "below by the run's forecaster's draft-day value) on the draw the rival in that seat on that "
    "path would take, less the players its own forecaster has no value for (a yahoo or blend "
    "seat by its rostered side, the first stand-in's), where it drafted on its own forecaster's "
    "per-game value alone (the user's ruling of 2026-11-18); two arms of a pair on two beliefs "
    "share one draft wherever their drafts come out the same, a bbm arm with a yahoo or blend "
    "arm on every path; --seat-draft "
    "own names the earlier rule and gives version 13's figures under a table, and the draft "
    "block names the rule (seat_draft); a run without a table is version 13's. "
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
#: An arm's seat's board, by the run's rule (``adp.SEAT_DRAFTS``; the draft PR).
ADP_SEAT = {
    adp.MARKET_DRAFT: (
        "an arm's seat's board: a rival's (each listed player's average pick plus a normal draw "
        "at the spread, the unlisted below by the run's forecaster's draft-day value), on the "
        "draw the rival in that seat on that path would take, less the players the arm's own "
        "forecaster has no value for on draft day (a system or blend seat's stand-in belief; a "
        "yahoo or blend seat's rostered side, the first stand-in's, which is what it reads of "
        "a player it drafts): it drafts as a rival does and passes on a player it cannot value "
        "(the user's ruling of 2026-11-18; --seat-draft market, the default)"
    ),
    adp.OWN_DRAFT: (
        "an arm's seat's board: its own forecaster's per-game value on draft day (a system or "
        "blend seat's stand-in belief); a player it does not project is not on it"
    ),
}
ADP_MARKET = (
    "the market's view: the negative of a listed player's average pick, the unlisted below by "
    "the run's forecaster's draft-day value; the preseason's, never refreshed"
)
ADP_POOL = (
    "the players with a scheduled game in the season's first {days} days that the run's "
    "forecaster projects or the table lists"
)
#: The limit of the arm's seat's draft rule, by rule. ``own``'s is the limit the ruling of
#: 2026-11-18 answered.
ADP_LIMIT = {
    adp.MARKET_DRAFT: (
        "the arm's seat drafts as a rival does, so its roster is an average manager's on the "
        "table and not what its own forecaster likes: nothing a seat could gain at the draft is "
        "in a result; it never drafts a player its forecaster has no line for (a rookie under a "
        "forecaster built on earlier seasons), where a rival does, so the season's best "
        "newcomers always start on rivals' rosters; a starting belief taken from the market for "
        "such a player is not built; and an average roster is no average finish: a surrogate "
        "seat that plays the season harder than its rivals finishes above the middle of the room, "
        "and how far above is not settled (looks of twelve paths: near the top on every path at one "
        "seed, out of the playoffs on a share of the paths at two more), so a verdict on "
        "playoff odds needs more paths than a look plays"
    ),
    adp.OWN_DRAFT: (
        "the arm's seat drafts on per-game value alone, with no regard for the games a player "
        "is expected to miss or for where the room would take him, so it can finish near the top "
        "or near the bottom of the room on every path, the paired change in playoff odds then "
        "zero with no spread; the user's ruling of 2026-11-18 replaced this rule (--seat-draft "
        "market, the default)"
    ),
}
#: What a pair's draft is, when the two arms share it.
ADP_SHARED = {
    adp.MARKET_DRAFT: (
        "one draft and one league, shared by both arms: the arms' seat drafts as a rival does on "
        "the same draw for either arm, and the two arms' drafts came out the same league, every "
        "roster equal (they pass by one table, a yahoo or blend arm by the first stand-in's as "
        "a bbm arm does; or by two that lack the same players, or differ only on players the "
        "seat never reached)"
    ),
    adp.OWN_DRAFT: "one draft and one league, shared by both arms",
}
#: The payload's ``draft`` under a table, by rule.
ADP_DRAFT = {
    adp.MARKET_DRAFT: (
        "snake in which each seat takes the best player left on its own board (adp): every "
        "seat's on the season's table with a draw of its own, an arm's seat's the rival's in "
        "its seat less the players its own forecaster cannot value"
    ),
    adp.OWN_DRAFT: (
        "snake in which each seat takes the best player left on its own board (adp): the "
        "rivals' on the season's table, an arm's seat's on its own forecaster"
    ),
}
ADP_APART = (
    "the two arms' draft-day beliefs differ, so each arm's season is a league of its own from "
    "the draft on, on the same (seed, path) and the same rivals' boards: the pair shares no draft"
)
#: The same under ``adp.MARKET_DRAFT``, where two beliefs part a pair only on the paths where
#: they pass on different players. No record made from the command carries it today: every arm
#: the command names passes by one table (:func:`passing_label`), so its pairs are one league
#: on every path; a pair built on two labels that are not a split of one another can part.
ADP_APART_MARKET = (
    "on some path the two arms' forecasters pass on different players the seat reached, so "
    "there each arm's season is a league of its own from the draft on, on the same (seed, path) "
    "and the same rivals' boards; where the two drafts come out the same league, every roster "
    "equal, the pair shares it (drafts_per_path)"
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
            split,
        )
        setup, second = setups["a"], setups["b"]
    else:
        draft = room_draft(
            market, arms, seats, label, projection, pinned, seed, 0, league, None, split
        )
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
    #: How an arm's seat drafts under a table (``adp.SEAT_DRAFTS``; the draft PR), None without one.
    seat_draft: str | None = None


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
        lineup_from = shapes.parse_lineup_from(getattr(args, "lineup_from", None))
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
            lineup_from=lineup_from,
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
    if args.adp == "none" and args.seat_draft is not None:
        print(
            f"refused: --seat-draft {args.seat_draft} is how an arm's seat drafts under a "
            "table; --adp none drafts every seat on the run's forecaster and nobody from a market"
        )
        return 2
    seat_draft = seat_draft_of(args)
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
            f"{spread.growth:g} given; the arms' seats draft "
            + (
                "as rivals do, less the players they cannot value (--seat-draft market)"
                if seat_draft == adp.MARKET_DRAFT
                else "on their own forecasters (--seat-draft own)"
            )
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
        seat_draft,
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
    for line_ in bid_lines(arms, shapes_read, paired):
        print(line_)
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
        seat_draft,
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
            None if spread is None else (tables[r.season][0].picks, spread, plan.seat_draft),
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
    rules = audit_rules(league_rules, grid)
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
        policy.executions_of(league_rules.waivers, league_rules.waiver_rule, league_rules.same_day),
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
        else ADP_DRAFT[plan.seat_draft],
        "adp": adp_block(args.adp, spread, tables, keys, results, paired, plan.seat_draft),
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
            queue_run(arms.values()),
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
                None if spread is None else (tables[r.season][0].picks, spread, plan.seat_draft),
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
    rules = audit_rules(league_rules, grid)
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
    seat_draft: str | None = None,
) -> dict[str, Any]:
    """What a replay's league was drafted on (#172, PR D4a): the source and, under a table, the
    given spread, the rules (the arm's seat's by ``seat_draft``, ``adp.SEAT_DRAFTS``; the draft
    PR), and per season the table in counts (no figure: they stay in the
    log), the log's hash, and the drafted players the run's forecaster does not project, over
    the drafts of the paths that stand."""
    if spread is None:
        return {"source": source}
    rule = seat_draft or adp.MARKET_DRAFT
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
        "seat_draft": rule,
        "seat": ADP_SEAT[rule],
        "market": ADP_MARKET,
        "pool": ADP_POOL.format(days=rn.OPENING_DAYS),
        "limit": ADP_LIMIT[rule],
        "seasons": seasons,
    }
    if paired:
        apart = any(2 in v for v in drafts.values())
        parted = ADP_APART if rule == adp.OWN_DRAFT else ADP_APART_MARKET
        out["pair"] = parted if apart else ADP_SHARED[rule]
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
    queue: bool = False,
) -> dict[str, Any]:
    """A room's figures, keyed by season and then by forecaster: each arm's outcomes and counts
    pooled over its seats and the paths that stand (the counts' note the run's ``waivers``',
    the season fields its arms name, ``counted``, and the queue's counts' when ``queue`` says an
    arm executes it, :func:`counts_note`), each arm's season scale by season (its note the
    run's ``scoring``'s and format's, :func:`scale_note`), the unprojected count by cell."""
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
            # A run that names a stash threshold carries its count in every row (PR G).
            "note": counts_note(
                waivers,
                any(
                    m in (row or {})
                    for r in results
                    for row in r["counts"].values()
                    for m in ct.STASH
                ),
                counted,
                queue,
            ),
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
#: A same-day run's note on its lineup rule (PR today).
LINEUP_NOTE = (
    "a free agent's add plays the day it is made: every seat decides on the morning's wire, then "
    "the day's free-agent adds land in the day's rotation (an add an earlier team took is lost, "
    "its drop kept), with their drops and held-slot moves, before the day's lineups, so an added "
    "player may start that day and his line of the day is his new team's, a dropped one's "
    "nobody's; a move is charged to the week of its day, with no shift. A claim is decided as "
    "before, on a dropped player's clear date. Not modelled: a game's tip-off (every add of the "
    "day plays that day), the hour a manager acts, news between the morning and the tip"
)
#: The same rule under continuous waivers, where it moves nothing.
LINEUP_NOTE_CONTINUOUS = (
    "a free agent's add would play the day it is made, but under continuous waivers every add is "
    "a claim, decided the next morning or on a dropped player's clear date, so the rule moves "
    "nothing: the season is the season of the default rule"
)
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
        **(
            {"lineup_note": lineup_note(league_rules)}
            if league_rules.lineup_from == shapes.TODAY
            else {}
        ),
    }


def lineup_note(league_rules: shapes.LeagueRules) -> str:
    """A same-day run's note on its lineup rule (PR today): :data:`LINEUP_NOTE`, and under
    continuous waivers :data:`LINEUP_NOTE_CONTINUOUS`, since there every add is a claim and the
    rule moves nothing."""
    return LINEUP_NOTE_CONTINUOUS if league_rules.continuous else LINEUP_NOTE


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


#: What a pair record's ``by_path`` is (PR trace).
BY_PATH_NOTE = (
    "each path that stands, with arm A's and arm B's outcomes on it, by season and forecaster: "
    "what a trace of one path of this pair checks itself on (a voided path is left out, as from "
    "every figure); a record written before it has none"
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
    and for the rivals (their note the run's ``waivers``' and the fields its arms set,
    :func:`counts_note`, ``run.counted_of``), each arm's season
    scale by season (its note the run's ``scoring``'s and format's, :func:`scale_note`), the
    unprojected count by cell and arm, the seat rule and each path's seat, and the rivals each arm faced. On a grid of
    more than one league shape, the by-axis table (:func:`by_axis`, #172, PR D4b). Each path
    that stands with each arm's outcomes, by season and forecaster (``by_path``, PR trace: what
    a trace of one path checks itself on; it adds a key and moves no outcome)."""
    rows: dict[str, dict[str, list[Mapping[str, Any]]]] = {}
    by_path: dict[str, dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]]] = {}
    scales: dict[str, dict[str, list[Any]]] = {}
    for key, res in zip(keys, results, strict=True):
        t, label = str(key["season"]), key["forecaster"]
        rows.setdefault(t, {}).setdefault(label, []).append(res)
        by_path.setdefault(t, {}).setdefault(label, []).append((key, res))
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
        "by_path": {
            "note": BY_PATH_NOTE,
            "by_season": {
                t: {
                    label: [
                        {"path": int(key["path"]), "a": res["a"], "b": res["b"]} for key, res in d
                    ]
                    for label, d in cells.items()
                }
                for t, cells in by_path.items()
            },
        },
        "season_scale": {
            "note": scale_note(scoring, h2h),
            "by_season": {
                t: {side: scale_of(rs) for side, rs in d.items()} for t, d in scales.items()
            },
        },
        "counts": {
            "note": counts_note(
                waivers,
                rn.stash_named(arms.values()),
                rn.counted_of(list(arms.values())),
                queue_run(arms.values()),
            ),
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
    "seat_draft",
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
    "lineup_from",
    "news_sd",
    "paths",
    "seed",
)
#: World flags added after a screen's record was fixed (PR today's ``lineup_from``): recorded only
#: when named, so a screen or a tune that names none records the world it did before.
WORLD_IF_NAMED = ("lineup_from",)
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


def baseline_arm(path: Path) -> dict[str, Any] | None:
    """The baseline arm's spec from ``--arm``'s file (a screen's and a tune's), parsed as every
    arm is; None, the refusal printed by name, when the file cannot be read or is no arm's."""
    try:
        base = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        print(f"refused: --arm: {e}")
        return None
    if not isinstance(base, dict):
        print(f"refused: --arm: {path} is not an arm's spec")
        return None
    try:
        rn.arm_of(base)
    except (ValueError, KeyError) as e:
        print(f"refused: --arm: {e.args[0] if e.args else e}")
        return None
    return base


def scale_in_force(
    args: argparse.Namespace,
    base: Mapping[str, Any],
    kept: Mapping[str, Any] | None,
    read: Callable[..., SeasonRead],
    said: set[str],
    workers: int,
    whose: str,
) -> dict[str, Any] | int:
    """The season scale a screen or a tune sizes its nudges on: the one its folder was started
    with (``kept``), said again, else measured now (:func:`screen_scale`; the exit code when
    that cannot be planned). ``whose``: "screen" or "tune", for the line."""
    if kept is None:
        return screen_scale(args, base, read, said, workers)
    figure = "none" if kept["ratio"] is None else f"{kept['ratio']:.4g}"
    print(
        f"season scale: {figure}, on {kept['paths']} of {kept['of']} paths of the first "
        f"cell, as the {whose} measured it when it was started"
    )
    return dict(kept)


def new_piece(workers: int) -> dict[str, Any]:
    """One run of a screen or a tune that plays a pair, as its record's ``timing`` keeps it:
    when and where it ran, on what commit, the pairs it played and why it stopped."""
    return {
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


def play_pair(
    plan: ReplayPlan,
    made: ReplayTasks,
    args: argparse.Namespace,
    workers: int,
    run_name: str,
    first: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    """One planned pair played to its record, as ``replay`` plays it: every task, then
    :func:`replay_payload`. ``first``: the result of the pair's timed task when this run timed
    it, so it is not played twice. The record, its audit block and every task's result."""
    plan = replace(plan, started=datetime.now(UTC))
    if first is not None:
        rest = rn.run_tasks(
            made.task, made.tasks[: made.slow] + made.tasks[made.slow + 1 :], workers
        )
        ran = [*rest[: made.slow], first, *rest[made.slow :]]
    else:
        ran = rn.run_tasks(made.task, made.tasks, workers)
    payload, note = replay_payload(plan, args, made, ran, workers, run_name)
    return payload, note, ran


def screen_spec(
    args: argparse.Namespace, base: Mapping[str, Any], names: Sequence[str], plan: ReplayPlan
) -> dict[str, Any]:
    """What a screen's folder is started with and every later piece is held to: the code's
    ``screen_version`` and ``replay_version`` (a pair played under another is another pair), the
    baseline arm's spec verbatim, the levers named (in the list's order), the world's flags
    (:data:`SCREEN_WORLD`; the seasons as read, and the seat's draft rule in force and not the
    flag as typed, ``plan.seat_draft``: a run that names no rule under a table and one that
    names the default are one world), the fit's hash and, in a run whose rivals bid on the
    price book (PR Fd), the book's: a newer book is another world."""
    read = {"seasons": list(plan.seasons), "seat_draft": plan.seat_draft}
    return {
        "screen_version": sc.SCREEN_VERSION,
        "replay_version": REPLAY_VERSION,
        "arm": dict(base),
        "levers": list(names),
        "world": {
            k: read[k] if k in read else getattr(args, k)
            for k in SCREEN_WORLD
            if k not in WORLD_IF_NAMED or getattr(args, k, None) is not None
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
    if unknown and unknown[0] in sc.NOT_LEVERS:
        print(f"refused: {sc.unlisted(unknown[0])}")
        return 2
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
    base = baseline_arm(args.arm)
    if base is None:
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
        scale = scale_in_force(wa, base, scale, read, said, workers, "screen")
        if isinstance(scale, int):
            return scale
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
    held_to = audit_rules(rules, plan.grid)
    if args.dry_run:
        code = 0
        for r in untimed:
            made = plans[r.key][1]
            _, note = audited([made.keys[made.slow]], [firsts[r.key]], held_to)
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
    piece = new_piece(workers)
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
        t0 = clock.perf_counter()
        payload, note, ran = play_pair(
            pair_plan, made, wa, workers, f"{name}-{r.key}", firsts.pop(r.key, None)
        )
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


# --------------------------------------------------------------------------- tune
#: What a tune is, in its record.
TUNE_NOTE = (
    "a tune searches the levers named one at a time, each value a pair against the current arm "
    "on the same paths, played by the code replay plays a pair with, then plays the final set "
    "against the baseline once on a season the search never played; it recommends, promotes "
    "nothing, writes no knob file and reads no live league"
)
#: The league's rules that are the rivals' and not the league's kind: how its market rivals bid.
TUNE_RIVALS = ("rival_scale", "rival_bids")
#: What a tune's look at the confirmation season is, in its record.
TUNE_LOOK_NOTE = (
    "a tune reads the confirmation season once, at the end: one line in the ledger (the tune's "
    "name, its spec's hash, the code's commit, the date, the league kind), appended before its "
    "first confirmation pair is played and never again for the same tune's folder; the same "
    "tune started again in a new folder reads the season again and is another look; look n "
    "counts the tunes of this league kind in the ledger, and the line's own number every run "
    "that named the season; a dry run and a tune with --confirm none add none"
)
#: Why a tune confirmed on another season counts no look.
TUNE_OTHER_SEASON = (
    "the final set was played on a season the search withheld that is not the confirmation "
    "season ({season}): no look is counted, since other runs play that season freely"
)
#: What a finished tune says when the ledger no longer holds the line it wrote.
TUNE_LOOK_LOST = (
    "the ledger no longer holds this tune's line (the ledger was removed, or the folder copied "
    "without it): the look is the one the confirmation's pair recorded when it was played"
)
#: What a confirmed tune says when neither the ledger nor its pairs name a look.
TUNE_NO_LOOK = "no look is on record for this tune, in the ledger or in its confirmation's pairs"
#: The world's flags that name the league kind (its shapes and its rules): a screen's and a
#: tune's are held equal by the kind in force, not by the flag as typed.
KIND_FLAGS = (
    "grid",
    "league",
    "scoring",
    "points",
    "held",
    "waivers",
    "waiver_days",
    "waiver_rule",
    "budget",
    "h2h",
    "lineup_from",
)
#: What a tune says of a screen played under another code, fit or world than its own.
SCREEN_DIFFERS_NOTE = (
    "the screen was played under what is listed here and this tune is not; its survivors and "
    "their order are taken as they stand, and the tune's own pairs are what its steps rest on"
)


def league_kind(plan: ReplayPlan) -> dict[str, Any]:
    """The league kind a tune searches and confirms in, and counts its looks by: the league
    shapes as they are played (each shape's teams, slots, adds and playoff format, in the
    grid's order; not the grid's name, so one shape named two ways is one kind) and the league's
    rules, less what is the rivals' (how they bid and the scale of their bids,
    :data:`TUNE_RIVALS`). Nothing is pooled across kinds."""
    return {
        "shapes": [s.payload() for s in plan.grid.shapes],
        "rules": {k: v for k, v in plan.league_rules.payload().items() if k not in TUNE_RIVALS},
    }


def shapes_in_force(world: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """The league shapes a screen's or a tune's world names (``--league``, else ``--grid``), as
    :func:`league_kind` keeps them; None when the flags cannot be read as shapes."""
    try:
        grid = (
            shapes.one("league", shapes.parse_league(str(world["league"])))
            if world.get("league") is not None
            else GRIDS[str(world.get("grid"))]
        )
    except (ValueError, KeyError):
        return None
    return [s.payload() for s in grid.shapes]


def screen_unfit(
    screen: Mapping[str, Any],
    base: Mapping[str, Any],
    kind: Mapping[str, Any],
    confirm: int | None,
) -> str | None:
    """Why a tune may not take its levers from ``screen``'s record; None when it may: the screen
    has pairs left to play (its survivors are not all known), it screened another baseline arm,
    it played the season this tune confirms on (``confirm``: the levers and their order would be
    chosen on the season called withheld), or it was played in another league kind (the
    league's rules, less the rivals', and the league shapes in force, read from the screen's
    world as the flags name them, whatever order they were typed in)."""
    if screen.get("left"):
        return (
            f"it has pairs left to play ({', '.join(screen['left'])}), so its survivors are "
            "not all known: finish the screen first"
        )
    spec = screen.get("spec") or {}
    if spec.get("arm") != dict(base):
        return (
            "it screened another baseline arm than --arm, and its survivors are that arm's; "
            "to tune levers from this arm name them with --levers and no --screen"
        )
    theirs_world = spec.get("world") or {}
    if confirm is not None and confirm in (theirs_world.get("seasons") or ()):
        return (
            f"it was played on season {confirm}, the season this tune confirms on (--confirm): "
            "its survivors and their order were chosen there, so the season would not be "
            "withheld from what chose the levers; confirm on a season the screen did not play, "
            "or name the levers with --levers and no --screen"
        )
    theirs = {
        k: v
        for k, v in ((screen.get("league") or {}).get("rules") or {}).items()
        if k not in TUNE_RIVALS
    }
    differs = next(
        (
            f"{k}: the screen's {theirs.get(k)!r}, this tune's {kind['rules'].get(k)!r}"
            for k in sorted({*theirs, *kind["rules"]})
            if theirs.get(k) != kind["rules"].get(k)
        ),
        None,
    )
    if differs is None and shapes_in_force(theirs_world) != kind["shapes"]:
        differs = (
            f"the league shapes: the screen's --grid {theirs_world.get('grid')!r} --league "
            f"{theirs_world.get('league')!r} name other shapes than this tune's"
        )
    if differs is not None:
        return (
            f"it was played in another league kind ({differs}), and a tune is one league "
            "kind's; to tune levers here name them with --levers and no --screen"
        )
    return None


def screen_differs(screen: Mapping[str, Any], spec: Mapping[str, Any]) -> dict[str, Any]:
    """What a screen a tune takes its order from was played under that this tune is not, by
    name, each with the screen's value and the tune's: the code's two versions, the fit's and
    the book's hashes, and every flag of the world that is not the league kind's (the kind is
    held equal by :func:`screen_unfit`). A screen of an earlier simulator is not refused: it is
    said."""
    theirs = screen.get("spec") or {}
    out: dict[str, Any] = {}
    for key in ("screen_version", "replay_version", "fit_sha", "book_sha"):
        if theirs.get(key) != spec.get(key):
            out[key] = {"screen": theirs.get(key), "tune": spec.get(key)}
    a, b = theirs.get("world") or {}, spec.get("world") or {}
    for key in sorted({*a, *b}):
        if key not in KIND_FLAGS and a.get(key) != b.get(key):
            out[key] = {"screen": a.get(key), "tune": b.get(key)}
    return out


def confirm_unfit(args: argparse.Namespace, confirm: int, plan: ReplayPlan) -> str | None:
    """Why the season a tune confirms on cannot be played in the tune's world, found before the
    first pair of the search and in the dry run; None when nothing stands in the way. It reads
    what is on file of the season before it begins and plays no path, so no outcome of the
    season is read and no look is counted: the ledger's own lines (on the confirmation season),
    the season's draft table under ``--adp``, the stand-ins' figures and each forecaster's. A
    forecaster the search reads (one that serves a season of the search) must serve the season
    confirmed on, since the verdict is stated for every forecaster the search read. What only a
    whole plan finds (a draft a named league shape cannot fill) is still met at the end, and is
    then recorded with the final set."""
    if confirm == CONFIRMATION:
        try:
            reader.read_looks(args.data)
        except reader.SimReadError as e:
            return f"the ledger its look is counted on cannot be read: {e}"
    if plan.spread is not None:
        try:
            reader.adp_table(args.data, confirm, HOLD_OUT)
        except reader.SimReadError as e:
            return (
                f"--adp {args.adp}: {e}; a tune under a draft table confirms on a season that "
                "has one"
            )
    if plan.sources is not None:
        try:
            fixed_of(args.data, confirm, list(plan.sources))
        except reader.SimReadError as e:
            why = str(e).removeprefix(f"season {confirm}: ")
            return f"a stand-in cannot serve season {confirm}: {why}"
    _, served, skipped = cells_of(args.data, confirm, plan.named)
    if not served:
        return (
            f"no forecaster named serves season {confirm} ("
            + "; ".join(f"{label}: {why}" for label, why in skipped.items())
            + ")"
        )
    searched = {f.label for r in plan.reads for f in r.served}
    missing = {label: why for label, why in skipped.items() if label in searched}
    if missing:
        return (
            "the search reads "
            + ", ".join(
                f"{label}, which cannot serve season {confirm} ({why})"
                for label, why in missing.items()
            )
            + ": the verdict is stated for every forecaster the search read; name the "
            "forecasters that serve it (--forecasters)"
        )
    return None


def pair_one_seat(plan: ReplayPlan, a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str] | None:
    """Whether a pair of specs is one seat in the run's league, as ``replay`` would refuse it
    (:func:`same_seats` on the arms as the run believes them): each name the two differ in with
    why neither reads it; None when they are two seats."""
    arms = believing(dict(zip(PAIR, (rn.arm_of(a), rn.arm_of(b)), strict=True)), plan.sources)
    return rn.same_seat(arms["a"], arms["b"], plan.shapes_read, True)


def tune_spec(
    args: argparse.Namespace,
    base: Mapping[str, Any],
    order: Sequence[Mapping[str, Any]],
    plan: ReplayPlan,
    confirm: int | None,
    screen: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """What a tune's folder is started with and every later piece is held to: a screen's spec
    for the same arm and world (:func:`screen_spec`: the two versions, the baseline arm's spec
    verbatim, the world's flags, the fit's hash and the book's), its ``levers`` the tune's in the
    order they are searched, and the tune's own: ``tune_version``, the passes, the season it
    confirms on (None for none) and the screen its order came from (its name and its spec's
    hash). Every choice is here before the first pair."""
    return {
        "tune_version": tn.TUNE_VERSION,
        **screen_spec(args, base, [o["lever"] for o in order], plan),
        "passes": args.passes,
        "confirm": confirm,
        "screen": None
        if screen is None
        else {"name": screen.get("name"), "spec_sha": spec_hash(screen.get("spec") or {})},
    }


def tune_record(
    name: str,
    spec: Mapping[str, Any],
    plan: ReplayPlan,
    scale: Mapping[str, Any] | None,
    measure: str,
    order: Sequence[Mapping[str, Any]],
    steps: Sequence[Mapping[str, Any]],
    final: Mapping[str, Any] | None,
    confirmation: Mapping[str, Any] | None,
    left: Mapping[str, Any] | None,
    timing: Mapping[str, Any],
    screen: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A tune's record: its spec, the code's commit and the fit's hash, the league and its kind,
    the measure and the search's rule, the order with where each place comes from and what the
    screen it came from was played under that this tune is not (``screen``), the season scale
    used, every finished step (each value's pair with its result and its file, the choice and
    why), the final set, the confirmation (its cells with the final pair's mechanism counts,
    the ledger's look, the verdict), what is left, and under ``timing`` everything that is a
    time. Apart from ``timing`` a tune played in pieces records what one played unbroken does."""
    rules = plan.league_rules
    return {
        "kind": "tune",
        "name": name,
        "tune_version": tn.TUNE_VERSION,
        "note": TUNE_NOTE,
        "spec": dict(spec),
        "code_sha": reader.code_sha(ROOT),
        "fit_sha": plan.sha,
        "fit_file": str(plan.fit_path),
        **({} if plan.book is None else {"book_sha": plan.book[1], "book_file": str(plan.book[2])}),
        "hold_out": plan.fit.get("hold_out", HOLD_OUT),
        "league": {"rules": rules.payload(), "label": rules.label(), "kind": league_kind(plan)},
        "measure": measure,
        "rule": tn.SEARCH_RULE,
        "carry": tn.CARRY_NOTE,
        "order": [dict(o) for o in order],
        "screen": None if screen is None else dict(screen),
        "scale": None if scale is None else dict(scale),
        "steps": [dict(s) for s in steps],
        "final": None if final is None else dict(final),
        "confirmation": None if confirmation is None else dict(confirmation),
        "left": None if left is None else dict(left),
        "timing": dict(timing),
    }


def look_block(
    line: Mapping[str, Any], lines: Sequence[Mapping[str, Any]], ledger: Path
) -> dict[str, Any]:
    """A tune's look in its record, from its own ledger ``line`` and the ledger's ``lines``: the
    look's number for its league kind, the line's number among every run's, how many earlier
    lines are other runs' (a replay's, another kind's tune), and the ledger's file."""
    earlier = [x for x in lines if int(x.get("look", 0)) < int(line["look"])]
    mine = [
        x
        for x in earlier
        if x.get("design") == "tune" and x.get("league_kind_sha") == line["league_kind_sha"]
    ]
    return {
        "season": CONFIRMATION,
        "look": int(line["look_of_kind"]),
        "line": int(line["look"]),
        "others": len(earlier) - len(mine),
        "ledger": str(ledger),
        "note": TUNE_LOOK_NOTE,
    }


def look_words(look: Mapping[str, Any]) -> str:
    """A tune's look as it is printed: "look n" for the league kind, and where it stands in the
    ledger."""
    return (
        f"confirmation season {look['season']}: look {look['look']} for this league kind (line "
        f"{look['line']} of {look['ledger']}; {look['others']} earlier line(s) are other runs')"
    )


def cmd_tune(args: argparse.Namespace) -> int:
    began = clock.perf_counter()
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    if args.max_minutes is not None and not args.max_minutes > 0:
        print("refused: --max-minutes is a span in minutes, above 0")
        return 2
    if args.passes < 1:
        print("refused: --passes is a count of passes over the levers, 1 or more")
        return 2
    unknown = [n for n in args.levers or () if n not in sc.NAMES]
    if unknown:
        print(
            f"refused: lever {unknown[0]!r} is not in the screen's list: one of "
            f"{', '.join(sc.NAMES)}"
        )
        return 2
    if args.screen is None and not args.levers:
        print(
            "refused: a tune names its levers: --screen NAME (that screen's survivors) or "
            "--levers by name"
        )
        return 2
    # The season the final set is confirmed on: never the hold-out, never one of the search's.
    confirm: int | None = None
    if args.confirm != "none":
        try:
            confirm = int(args.confirm)
        except ValueError:
            print(f"refused: --confirm {args.confirm!r}: an ESPN season id, or none")
            return 2
    if confirm == HOLD_OUT:
        print(f"refused: --confirm {HOLD_OUT}: {HOLD_OUT} is the hold-out; no run plays it")
        return 2
    seasons_text = args.seasons
    if seasons_text is None:
        on_file = reader.seasons_on_file(args.data, max(reader.PERIOD_ONE) + 1)
        free = [t for t in on_file if t not in (HOLD_OUT, CONFIRMATION, confirm)]
        if not free:
            print(
                "refused: no season a tune's search may play has a log on file under "
                f"{args.data / LOGS_DIR}"
            )
            return 2
        seasons_text = ",".join(str(t) for t in free)
    try:
        looked = parse_seasons(seasons_text)
    except ValueError:
        looked = []  # refused by name below, as replay refuses it
    if HOLD_OUT in looked:
        print(f"refused: {HOLD_OUT} is the hold-out; no run plays it")
        return 2
    if CONFIRMATION in looked:
        print(
            f"refused: {CONFIRMATION} is the confirmation season; a tune's search never plays "
            "it: it is read once, at the end (--confirm)"
        )
        return 2
    if confirm is not None and confirm in looked:
        print(
            f"refused: --confirm {confirm} is one of the search's seasons (--seasons): the "
            "season a tune confirms on is withheld from its search"
        )
        return 2
    if confirm is not None and (
        confirm not in reader.PERIOD_ONE or not (args.data / LOGS_DIR / f"{confirm}.json").is_file()
    ):
        print(
            f"refused: --confirm {confirm}: season {confirm} has no log on file under "
            f"{args.data / LOGS_DIR}"
        )
        return 2
    base = baseline_arm(args.arm)
    if base is None:
        return 2
    screen = None
    if args.screen is not None:
        try:
            screen = reader.read_screen(args.data, args.screen)
        except reader.SimReadError as e:
            print(f"refused: {e}")
            return 2
        if screen is None:
            print(
                f"refused: --screen {args.screen}: no screen of that name has a record under "
                f"{args.data / reader.SCREENS_DIR}"
            )
            return 2
    wa = pair_args(args, seasons_text)
    said: set[str] = set()
    read = remembering()
    got = screen_pair(wa, [base, base], read, said, "the baseline arm's world")
    if isinstance(got, int):
        return got
    plan, world = got
    rules = plan.league_rules
    measure = sc.measure_of(rules.scoring, rules.h2h)
    kind = league_kind(plan)
    if screen is not None:
        unfit = screen_unfit(screen, base, kind, confirm)
        if unfit is not None:
            print(f"refused: --screen {args.screen}: {unfit}")
            return 2
    if confirm is not None:
        # Whether the season confirmed on can be played at all in this world is asked now, not
        # after the search: no path of it is planned, and none of its outcomes is read.
        unfit = confirm_unfit(args, confirm, plan)
        if unfit is not None:
            print(
                f"refused: --confirm {confirm}: {unfit}; nothing of the search is played for a "
                "confirmation that cannot be: name another season with --confirm, or --confirm "
                "none (no confirmation, not a verdict)"
            )
            return 2
    try:
        order = tn.order_of(screen, args.levers)
    except (ValueError, KeyError) as e:
        print(f"refused: {e.args[0] if e.args else e}")
        return 2
    names = [o["lever"] for o in order]
    workers = args.workers or rn.workers_default()
    name = args.name or "tune-" + "-".join(str(t) for t in plan.seasons)
    spec = tune_spec(args, base, order, plan, confirm, screen)
    try:
        state = reader.read_tune(args.data, name)
    except reader.SimReadError as e:
        print(f"refused: {e}")
        return 2
    if state is not None:
        differs = sc.spec_differs(state.get("spec") or {}, spec)
        if differs is not None:
            print(
                f"refused: the tune {name!r} was started with another spec ({differs}); a tune "
                "is resumed on the spec it was started with: name this one another (--name)"
            )
            return 2
    else:
        folder = reader.tune_dir(args.data, name)
        if folder.is_dir() and any(folder.glob("*.json")):
            print(
                f"refused: the tune {name!r} has pairs on file under {folder} and no record "
                f"({reader.TUNE_FILE}): the record says when the tune was started, which is how "
                "its look at the confirmation season is found again; remove the folder to start "
                "the tune again (its confirmation is then another look), or name this one "
                "another (--name)"
            )
            return 2
    screened = None
    if screen is not None:
        screened = {
            "name": screen.get("name"),
            "differs": screen_differs(screen, spec),
            "note": SCREEN_DIFFERS_NOTE,
        }
        if screened["differs"]:
            print(
                f"note: the screen {args.screen} was played under another "
                + "; ".join(
                    f"{k} ({d['screen']!r} there, {d['tune']!r} here)"
                    for k, d in screened["differs"].items()
                )
                + ": its survivors and their order are taken as they stand"
            )
    # The season scale is the baseline's, measured once before any pair, whatever moves later.
    ctx = sc.Context(rules.scoring, rules.waivers)
    scale = (state or {}).get("scale")
    if any(r.scale for r in sc.rows_of(base, names, plan.shapes_read, ctx)):
        scale = scale_in_force(wa, base, scale, read, said, workers, "tune")
        if isinstance(scale, int):
            return scale
        ctx = replace(ctx, scale=scale["ratio"], no_scale=sc.NO_RATIO)
    plans: dict[str, tuple[ReplayPlan, ReplayTasks]] = {}

    def ident(wargs: argparse.Namespace, a: Mapping[str, Any], b: Mapping[str, Any]) -> str:
        return json.dumps([wargs.seasons, a, b], sort_keys=True, default=str)

    def planned(
        wargs: argparse.Namespace, a: Mapping[str, Any], b: Mapping[str, Any], whose: str
    ) -> tuple[ReplayPlan, ReplayTasks] | int:
        key = ident(wargs, a, b)
        if key not in plans:
            got = screen_pair(wargs, [a, b], read, said, whose)
            if isinstance(got, int):
                return got
            plans[key] = got
        return plans[key]

    # The plan: each lever's values as the baseline gives them, one task of each lever's first
    # pair timed (a lever timed by an earlier piece is not timed again).
    listed = {n: tn.values_of(n, base, plan.shapes_read, ctx) for n in names}
    before = dict((state or {}).get("timing") or {})
    estimates: dict[str, dict[str, Any]] = dict(before.get("estimates") or {})
    firsts: dict[str, Any] = {}
    timed_keys: dict[str, Mapping[str, Any]] = {}
    untimed = []
    for n in names:
        row = next((r for r in listed[n] if r.status == sc.PLAY), None)
        if row is None or n in estimates:
            continue
        got = planned(wa, row.a or {}, row.b or {}, f"the pair of {row.key}")
        if isinstance(got, int):
            return got
        untimed.append((n, row, got[1]))
    if untimed:
        t0 = clock.perf_counter()
        timed = rn.run_tasks(
            timed_task, [(made.task, *made.tasks[made.slow]) for _, _, made in untimed], workers
        )
        for (n, row, made), (seconds, first) in zip(untimed, timed, strict=True):
            estimates[n] = {"seconds_one": seconds, "tasks": len(made.tasks)}
            firsts[ident(wa, row.a or {}, row.b or {})] = first
            timed_keys[row.key] = made.keys[made.slow]
        print(
            f"one task of each of {len(untimed)} lever(s) timed in "
            f"{clock.perf_counter() - t0:.0f}s on {workers} workers"
        )

    def pair_hours(lever: str) -> float:
        e = estimates.get(lever)
        if e is None:
            return 0.0
        return estimate_hours(float(e["seconds_one"]), int(e["tasks"]), workers)

    static_rivals = str(rn.arm_of(base).opponents.get("kind", "static")) == "static"
    kinds = [tn.RUN] if static_rivals else [tn.RUN, tn.STATIC]
    confirm_tasks = len(plan.named) * world.paths

    def confirm_hours() -> float:
        """One confirmation pair's estimate: its tasks at the slowest lever's timed task (a
        lever timed inside the search counts from then on)."""
        slowest = max((float(e["seconds_one"]) for e in estimates.values()), default=0.0)
        return estimate_hours(slowest, confirm_tasks, workers)

    pairs = sum(1 for n in names for r in listed[n] if r.status == sc.PLAY)
    search_hours = args.passes * sum(
        pair_hours(n) for n in names for r in listed[n] if r.status == sc.PLAY
    )
    confirm_all = 0.0 if confirm is None else len(kinds) * confirm_hours()
    whole_hours = (
        args.expected_hours if args.expected_hours is not None else search_hours + confirm_all
    )
    rows = [r for n in names for r in listed[n]]
    texts = []
    for r in rows:
        if r.status != sc.PLAY:
            texts.append(sc.status_words(r.payload()))
            continue
        e = estimates[r.lever]
        texts.append(
            f"a pair of {e['tasks']} tasks, one of the lever's took {e['seconds_one']:.1f}s, "
            f"about {pair_hours(r.lever):.2f} h"
        )
    print(
        f"the tune {name}, its plan: {args.passes} pass(es) over {len(names)} lever(s) in this "
        f"order, fixed before any pair: {tn.order_words(order)}"
    )
    print(
        f"the search's cells: season(s) {', '.join(str(t) for t in plan.seasons)} by "
        f"{', '.join(f.label for f in plan.named)}, {world.paths} paths a cell; never the "
        f"hold-out ({HOLD_OUT}), never the confirmation season ({CONFIRMATION})"
    )
    print(f"each lever's values from the baseline, on {tn.measure_words(measure)}:")
    for line_ in sc.listing([r.payload() for r in rows], texts):
        print(line_)
    if confirm is None:
        print(f"the confirmation: none ({tn.NO_CONFIRMATION})")
    else:
        print(
            f"the confirmation: the final set against the baseline on {confirm}, once, against "
            + " and against ".join(tn.RIVALS_WORDS[k] for k in kinds)
            + f": up to {len(kinds)} pair(s) of {confirm_tasks} tasks, about {confirm_all:.2f} h, "
            "both arms on the cheapest tier that reads every value that moved"
        )
    print(
        f"the whole tune: about {args.passes * pairs} pair(s) of the search, as the baseline "
        f"lists them, and the confirmation, about {whole_hours:.2f} h on {workers} workers (a "
        "pass that moves no lever ends the search; a lever that moved is tried from its new "
        "value in a later pass, and a lever first read after another moved is timed then: the "
        "search may play pairs this plan does not list, and the hour's rule is read again "
        "before each pair)"
    )
    held_to = audit_rules(rules, plan.grid)
    if args.dry_run:
        code = 0
        for _, row, made in untimed:
            key = ident(wa, row.a or {}, row.b or {})
            _, note = audited([timed_keys[row.key]], [firsts[key]], held_to)
            if note["paths_voided"]:
                print(f"the pair of {row.key}, its timed task:")
                code = max(code, audit_exit(note))
        print("dry run, nothing written")
        return code
    piece = new_piece(workers)
    pieces = list(before.get("pieces") or [])
    if pieces and pieces[0].get("code_sha") != piece["code_sha"]:
        print(
            f"note: the tune was started on commit {pieces[0].get('code_sha')} and this run is "
            f"on {piece['code_sha']}; each piece records its own"
        )
    timing = {"estimates": estimates, "pieces": pieces}
    steps: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    conf: dict[str, Any] | None = None
    left: dict[str, Any] | None = None
    started = False
    met_hours = 0.0

    def save() -> Path:
        return reader.write_tune(
            args.data,
            name,
            tune_record(
                name, spec, plan, scale, measure, order, steps, final, conf, left, timing, screened
            ),
        )

    def start() -> str | None:
        """Before the first pair this run would play: the hour's rule on the whole tune's
        estimate, the routines' window against what is left of it (under ``--max-minutes``, the
        piece); then the piece is opened and the record written. Why the run may not start,
        else None."""
        nonlocal started
        if started:
            return None
        if whole_hours > ANNOUNCE_HOURS and not args.announced:
            return (
                f"a tune of about {whole_hours:g} h is announced on the tracker and starts on "
                "the user's word, whatever a piece of it takes; --announced says that has "
                "happened"
            )
        left_hours = max(0.0, whole_hours - met_hours)
        piece_hours = (
            left_hours if args.max_minutes is None else min(left_hours, args.max_minutes / 60.0)
        )
        ok, why = guard(piece_hours, rooms=args.rooms, announced=True)
        if not ok:
            return why
        started = True
        pieces.append(piece)
        save()
        return None

    def past_the_hour(hours: float, ahead: float, key: str) -> str | None:
        """The hour's rule read again before the pair ``key``: the plan's estimate lists the
        search as the baseline gives it, and a search can come to more (a later pass from a
        moved value, a lever timed late). ``hours``: the pair's own; ``ahead``: the
        confirmation's still to play. Why the pair is not started, else None. A tune that was
        announced, or whose estimate the caller gave (``--expected-hours``), is not asked again."""
        if args.announced or args.expected_hours is not None:
            return None
        so_far = met_hours + hours + ahead
        if so_far <= ANNOUNCE_HOURS + 1e-9:
            return None
        return (
            f"with the pair of {key} the tune comes to about {so_far:g} h, more than its plan "
            f"listed (about {whole_hours:g} h) and past the hour: a tune of over an hour is "
            "announced on the tracker and starts on the user's word; --announced says that has "
            "happened"
        )

    def over(minutes: float, key: str) -> str | None:
        """Why the pair ``key`` is not started under ``--max-minutes``; None when it fits."""
        spent = (clock.perf_counter() - began) / 60.0
        if args.max_minutes is None or spent + minutes <= args.max_minutes:
            return None
        return (
            f"--max-minutes {args.max_minutes:g}: the pair of {key}, about {minutes:.1f} min, "
            f"would pass it {spent:.1f} min from the start"
        )

    def on_file(
        key: str, a: Mapping[str, Any], b: Mapping[str, Any]
    ) -> dict[str, Any] | str | None:
        """The pair ``key`` as the folder holds it; None when it has none; the refusal's words
        when the file cannot be read or holds other arms than this tune's."""
        try:
            pair = reader.read_tune_pair(args.data, name, key)
        except reader.SimReadError as e:
            return str(e)
        if pair is not None and pair.get("specs") != {"a": dict(a), "b": dict(b)}:
            return (
                f"the tune {name!r} holds a pair {key} of other arms than this tune's: name "
                "this one another (--name)"
            )
        return pair

    code = 0
    voided = 0
    stopped: str | None = None
    # A stop that is a refusal: the hour's rule met inside the tune, or a confirmation's pair
    # that cannot be planned. The record is written with what stands, and the exit code says so.
    halted = False
    current: dict[str, Any] = dict(base)
    moved: list[str] = []
    # The pairs met so far, by their two arms: a later pass that comes to the same two arms (a
    # lever whose current arm no step has changed since) takes that result and plays nothing.
    met: dict[str, tuple[str, dict[str, Any]]] = {}
    for turn in range(1, args.passes + 1):
        moved_now = False
        for lever in names:
            values_ = tn.values_of(lever, current, plan.shapes_read, ctx)
            values: list[dict[str, Any]] = []
            for r in values_:
                d = r.payload()
                if r.status != sc.PLAY:
                    values.append(d)
                    continue
                key = tn.pair_key(turn, r.key)
                a, b = r.a or {}, r.b or {}
                pair = on_file(key, a, b)
                if isinstance(pair, str):
                    print(f"refused: {pair}")
                    return 2
                two = ident(wa, a, b)
                earlier = met.get(two)
                file = key
                if pair is not None:
                    result = pair["tune"]["result"]
                    met_hours += pair_hours(lever)
                    print(f"pass {turn}, {r.key}: played before: {tn.value_words(result)}")
                elif earlier is not None:
                    file, result = earlier
                    d["same_as"] = file
                    print(
                        f"pass {turn}, {r.key}: the same two arms as {file} on the same paths, "
                        f"not played again: {tn.value_words(result)}"
                    )
                else:
                    got = planned(wa, a, b, f"the pair of {key}")
                    if isinstance(got, int):
                        return got
                    pair_plan, made = got
                    if lever not in estimates:
                        # A lever with no pair from the baseline: timed when it first has one.
                        seconds, first = timed_task(made.task, *made.tasks[made.slow])
                        estimates[lever] = {"seconds_one": seconds, "tasks": len(made.tasks)}
                        firsts[two] = first
                        print(
                            f"pass {turn}, {r.key}: lever {lever} has its first pair here, none "
                            f"from the baseline: one task timed, {seconds:.1f}s, about "
                            f"{pair_hours(lever):.2f} h a pair"
                        )
                    refusal = start()
                    if refusal is not None:
                        print(f"refused: {refusal}")
                        return 2
                    ahead = 0.0 if confirm is None else len(kinds) * confirm_hours()
                    stopped = past_the_hour(pair_hours(lever), ahead, key)
                    if stopped is not None:
                        halted = True
                        left = {"stopped": stopped, "next": key}
                        break
                    stopped = over(60.0 * pair_hours(lever), key)
                    if stopped is not None:
                        left = {"stopped": stopped, "next": key}
                        break
                    t0 = clock.perf_counter()
                    payload, note, ran = play_pair(
                        pair_plan, made, wa, workers, f"{name}-{key}", firsts.pop(two, None)
                    )
                    result = tn.value_result(payload, made.keys, ran, measure)
                    payload["tune"] = {
                        "name": name,
                        "tune_version": tn.TUNE_VERSION,
                        "pass": turn,
                        **d,
                        "status": sc.PLAYED,
                        "result": result,
                    }
                    payload["finished_at"] = datetime.now(UTC).isoformat()
                    path = reader.write_tune_pair(args.data, name, key, payload)
                    piece["played"].append(key)
                    met_hours += pair_hours(lever)
                    print(
                        f"pass {turn}, {r.key}: {tn.value_words(result)} "
                        f"({clock.perf_counter() - t0:.0f}s); written: {path}"
                    )
                    code = max(code, audit_exit(note))
                if earlier is None:
                    voided += int(result["voided"])
                    met[two] = (key, result)
                values.append(d | {"status": sc.PLAYED, "result": result, "file": f"{file}.json"})
            if stopped is not None:
                break
            step: dict[str, Any] = {
                "pass": turn,
                "lever": lever,
                "from": sc.value_of(rn.arm_of(current), lever),
                "values": values,
                "choice": tn.choose([v for v in values if v.get("result") is not None]),
                "change": None,
            }
            taken = step["choice"]["key"]
            if taken is not None:
                row = next(r for r in values_ if r.key == taken)
                step["change"] = tn.change_of(row.a or {}, row.b or {})
                current = sc.applied(current, step["change"])
                moved_now = True
                if lever not in moved:
                    moved.append(lever)
            step["why"] = tn.step_words(step)
            steps.append(step)
            print(f"pass {turn}: {step['why']}")
            if started:
                save()
        if stopped is not None or not moved_now:
            break
    if stopped is None:
        # The final set: what the current arm holds that the baseline does not.
        first_arm, last_arm = rn.arm_of(base), rn.arm_of(current)
        levers = [n for n in moved if sc.value_of(last_arm, n) != sc.value_of(first_arm, n)]
        tier = tn.tier_of(levers)
        arms = {k: tn.confirm_arms(base, current, tier, k == tn.STATIC) for k in kinds}
        final = {
            "set": tn.change_of(base, current),
            "arm": dict(current),
            "levers": levers,
            "tier": tier,
            "unread": tn.unread_of(levers, arms[tn.RUN][1], plan.shapes_read),
        }
        # A kind of rivals against which the final arm is the baseline's seat (the two differ
        # only in what neither reads there) is known before the season is read: replay would
        # refuse that pair, so it is not planned.
        one_seat: dict[str, list[str]] = {}
        for k in kinds:
            same = pair_one_seat(plan, *arms[k])
            if same:
                one_seat[k] = same
        conf = {"season": confirm, "status": tn.NOT_YET, "look": None}
        if confirm is None:
            conf["status"] = tn.NO_CONFIRMATION
        elif not final["set"]:
            conf["status"] = tn.NOTHING_TO_CONFIRM
        elif len(final["unread"]) == len(levers) or tn.RUN in one_seat:
            conf["status"] = tn.SAME_SEAT
        else:
            ca = pair_args(args, str(confirm))
            playing = [k for k in kinds if k not in one_seat]
            conf |= {
                "tier": tier,
                "arms": {k: {"a": arms[k][0], "b": arms[k][1]} for k in kinds},
                "files": {k: f"confirm-{k}.json" for k in playing},
                "one_seat": one_seat,
            }
            ledger = args.data / reader.LEDGER
            spec_sha = spec_hash(spec)
            # A tune is its folder: the look it has is the one its first piece's start names.
            first_start = (pieces[0] if pieces else piece)["started_at"]
            if confirm == CONFIRMATION:
                try:
                    lines = reader.read_looks(args.data)
                except reader.SimReadError as e:
                    print(f"refused: {e}")
                    return 2
                own = tn.own_look(lines, name, spec_sha, first_start)
                if own is not None:
                    conf["look"] = look_block(own, lines, ledger)
            else:
                conf["look_note"] = TUNE_OTHER_SEASON.format(season=CONFIRMATION)
            payloads: dict[str, Mapping[str, Any]] = {}
            for i, k in enumerate(playing):
                key = f"confirm-{k}"
                a, b = arms[k]
                pair = on_file(key, a, b)
                if isinstance(pair, str):
                    print(f"refused: {pair}")
                    return 2
                if pair is not None:
                    payloads[k] = pair
                    met_hours += confirm_hours()
                    kept = (pair.get("tune") or {}).get("look")
                    if confirm == CONFIRMATION and conf["look"] is None and kept:
                        # The pair was played on a look the ledger no longer holds.
                        conf |= {"look": dict(kept), "look_lost": TUNE_LOOK_LOST}
                    continue
                # Whether this piece may play the pair is settled before the season is read:
                # the hour's rule and the window, the hour's rule again, the cap in minutes.
                refusal = start()
                if refusal is not None:
                    print(f"refused: {refusal}")
                    return 2
                ahead = (len(playing) - i - 1) * confirm_hours()
                stopped = past_the_hour(confirm_hours(), ahead, key)
                if stopped is not None:
                    halted = True
                    left = {"stopped": stopped, "next": key}
                    break
                stopped = over(60.0 * confirm_hours(), key)
                if stopped is not None:
                    left = {"stopped": stopped, "next": key}
                    break
                # The season the search never played is read here, for the first time.
                said_now = io.StringIO()
                with contextlib.redirect_stdout(said_now):
                    got = planned(ca, a, b, f"the confirmation's pair against {tn.RIVALS_WORDS[k]}")
                print(said_now.getvalue(), end="")
                if isinstance(got, int):
                    # What only a whole plan finds (the early check asks the rest): the final
                    # set stands in the record with why its confirmation was not played.
                    whys = [
                        x.removeprefix("refused: ")
                        for x in said_now.getvalue().splitlines()
                        if x.startswith("refused: ")
                    ]
                    conf |= {"status": tn.UNPLANNED, "why": whys[0] if whys else None}
                    halted = True
                    break
                pair_plan, made = got
                if confirm == CONFIRMATION and conf["look"] is None:
                    # The look is counted before the season is played, so a tune that dies in its
                    # confirmation is on the ledger all the same.
                    lines = reader.read_looks(args.data)
                    n, ledger = reader.append_look(
                        args.data,
                        {
                            "started_at": datetime.now(UTC).isoformat(),
                            "name": name,
                            "design": "tune",
                            "tune_started_at": first_start,
                            "seasons": [confirm],
                            "search_seasons": list(plan.seasons),
                            "forecasters": [f.label for f in plan.named],
                            "spec_sha": spec_sha,
                            "specs": {
                                side: spec_hash(x)
                                for side, x in zip(PAIR, arms[tn.RUN], strict=True)
                            },
                            "fit_sha": plan.sha,
                            "code_sha": piece["code_sha"],
                            "league_kind": kind,
                            "league_kind_sha": spec_hash(kind),
                            "look_of_kind": tn.look_of_kind(lines, spec_hash(kind)),
                        },
                    )
                    lines = reader.read_looks(args.data)
                    conf["look"] = look_block(lines[n - 1], lines, ledger)
                    print(look_words(conf["look"]) + ": appended")
                    save()
                t0 = clock.perf_counter()
                payload, note, _ = play_pair(pair_plan, made, ca, workers, f"{name}-{key}")
                if confirm == CONFIRMATION:
                    payload["confirmation"] = {
                        "season": CONFIRMATION,
                        "look": conf["look"]["line"],
                        "ledger": conf["look"]["ledger"],
                        "note": TUNE_LOOK_NOTE,
                    }
                payload["tune"] = {
                    "name": name,
                    "tune_version": tn.TUNE_VERSION,
                    "confirmation": k,
                    "tier": tier,
                    "look": conf["look"],
                }
                payload["finished_at"] = datetime.now(UTC).isoformat()
                path = reader.write_tune_pair(args.data, name, key, payload)
                piece["played"].append(key)
                met_hours += confirm_hours()
                payloads[k] = payload
                print(
                    f"the confirmation against {tn.RIVALS_WORDS[k]}: played "
                    f"({clock.perf_counter() - t0:.0f}s); written: {path}"
                )
                code = max(code, audit_exit(note))
                save()
            if stopped is None and conf["status"] == tn.NOT_YET:
                cells = {k: tn.confirmation_of(payloads[k], confirm) for k in playing}
                lost = sum(int(payloads[k]["audit"]["paths_voided"]) for k in playing)
                voided += lost
                # Each named forecaster with no cell on the season, by replay's reason; one the
                # search read is no verdict. One the search read whose cell is there and not
                # read leaves a verdict on the others, and the verdict's line names it.
                skipped = tn.skipped_of(payloads[tn.RUN], confirm)
                searched = tn.searched_of(steps)
                missing = {label: why_ for label, why_ in skipped.items() if label in searched}
                conf |= {
                    "status": tn.CONFIRMED,
                    "cells": cells,
                    "skipped": skipped,
                    "verdict": tn.verdict_of(cells, lost, missing, list(one_seat), searched),
                }
    if stopped is not None:
        piece["stopped"] = stopped
        print(("refused: " if halted else "stopped: ") + stopped)
    piece["finished_at"] = datetime.now(UTC).isoformat()
    if final is not None:
        chosen = ", ".join(f"{k} {sc.shown(v)}" for k, v in final["set"].items()) or "none"
        print(f"the tune {name}, the final set (what the search changed in the baseline): {chosen}")
        for lever, why_ in final["unread"].items():
            print(f"  not read by the final arm on the {final['tier']} tier: {lever} ({why_})")
    if conf is not None and conf["status"] == tn.CONFIRMED:
        if conf["look"] is not None:
            where = look_words(conf["look"])
            where += f"; {conf['look_lost']}" if "look_lost" in conf else ""
        else:
            where = f"season {confirm}: " + conf.get("look_note", TUNE_NO_LOOK)
        own_tier = rn.arm_of(base).tier
        on = f"both arms on the {conf['tier']} tier"
        if own_tier != conf["tier"]:
            on += (
                f" (the cheapest that reads every value that moved; the baseline's own is the "
                f"{own_tier} tier)"
            )
        print(f"the confirmation, the final set against the baseline, {on}: {where}")
        for line_ in tn.confirmation_lines(conf, measure):
            print(line_)
    elif conf is not None:
        print(
            f"the confirmation: {conf['status']}" + (f" ({conf['why']})" if conf.get("why") else "")
        )
        if final is not None and final["set"] and confirm is None:
            print(
                "the search's set is no recommendation by itself: it was chosen on the seasons "
                "it was searched on"
            )
    # A run with nothing left to play of a tune on file is no piece: it writes the record again
    # from the pairs' files and prints the choices.
    if not started and state is None:
        pieces.append(piece)
    path = save()
    if left is not None and halted:
        print(f"left, from {left['next']} on; the same command with --announced plays it")
    elif left is not None:
        print(f"left for the next piece, from {left['next']} on; the same command plays it")
    print(f"written: {path}")
    if halted:
        return 2
    return AUDIT_EXIT if voided else code


# --------------------------------------------------------------------------- validate
def gate_dict(g: vg.Gate) -> dict[str, Any]:
    return {"name": g.name, "passed": g.passed, "season": g.season, "detail": g.detail}


#: What each seat's row of gate 5 records beside its verdict (#172, PR D4a2; the worths are the
#: rule's input since PR g5).
GATE_RECORDS = (
    "per seat and sampled day (detail.records): the exact tier's set and the surrogate's, the add "
    "and the drop by id; whether they are equal (counted in detail.matched; it does not decide); "
    "and each set's worth by the exact tier's own objective on that day's problem, the value one "
    "evaluator of the exact tier's gives it on the key it searches (three weeks, with the season "
    "term at a season_weight), beside standing still's; a day left out says why. The worths are "
    "what the gate's rule reads: a tier's gain on a day is its set's worth less standing still's"
)
#: Gate 5's rule, as each record says it (#172, PR g5; ``validate.surrogate_gate``).
GATE_RULE = (
    f"a seat passes when its surrogate keeps at least {vg.SURROGATE_KEEPS:.0%} of the exact "
    f"search's gain over its {vg.SURROGATE_OF} league-days, every one of them compared. A day's "
    "gain is a set's worth by the exact tier's own objective less standing still's "
    "(detail.records); each tier's is summed over the days (detail.gain), then the two sums are "
    "compared, surrogate >= share x exact, with no division and less a tolerance "
    f"({vg.EPS:g} of gain), so a float's last bits never decide: an exact tier that stood still "
    "asks only that the surrogate lose nothing, and a surrogate that found more passes. An exact "
    "gain below 0, which the exact search does not give, is held to itself and not to a share of "
    "it, so the same sets never fail. detail.kept is the surrogate's gain over the exact "
    "search's (null when the exact gain is not above 0). The days on which the two sets are "
    "equal are counted (detail.matched) and do not decide. The gate passes when every seat does"
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
    the :data:`GATE_DAYS` after the first simulated day, for each of :func:`gate_seats`, the
    surrogate's set against the exact set from day one's rosters (``checks.surrogate_records``),
    at the knobs' defaults (``policy.KNOB_DEFAULTS``) and the fields' (``policy.DEFAULT_FIELDS``),
    in the head-to-head format ``h2h`` (the format PR: one win per matchup by default, so the two
    tiers are compared in the measure the seats play). A seat passes on the gain its surrogate
    keeps over its days (``validate.surrogate_gate``, PR g5). One gate row a seat, and the block
    that names what the gate ran on. Refused (``readers.SimReadError``) when ``f`` cannot serve
    the season."""
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
        g = vg.surrogate_gate(records, season=season)
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
        "rule": GATE_RULE,
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


def share_tenths(x: float) -> int:
    """A share in tenths of a percent, cut, not rounded: 0.9499 is 949. (A last bit under a whole
    tenth, as a product of floats can leave, does not cut it to the tenth below.)"""
    return math.floor(x * 1000 + 1e-6)


def kept_words(d: Mapping[str, Any]) -> str:
    """The share a seat's surrogate kept as gate 5's line says it, from the row's detail: cut to
    a tenth of a percent (:func:`share_tenths`), then held to the rule's verdict on the two gains
    (``validate.keeps``). The rule's tolerance is on the gain (``validate.EPS``) and the cut's is
    on the share, so within that tolerance of the bar the cut alone can read as the share needed
    for a seat the rule fails, or under it for one the rule passes. Held, a seat that fails by
    the gain never reads as at the share needed and one that keeps it never reads under it. A
    seat that fails only for a day left out is not held under the bar: its share is what it kept
    on the days compared."""
    tenths, bar = share_tenths(d["kept"]), d["needs"] * 1000
    if vg.keeps(d["gain"]["exact"], d["gain"]["surrogate"], d["needs"]):
        tenths = max(tenths, math.floor(bar + 1e-6))
    else:
        tenths = min(tenths, math.ceil(bar - 1e-6) - 1)
    return f"{tenths / 10:.1f}%"


def seat_line(d: Mapping[str, Any]) -> str:
    """What gate 5 prints for a seat after its verdict, from the row's detail: the share of the
    exact search's gain its surrogate kept (:func:`kept_words`), with the two gains to four
    decimals and the share needed (the two gains alone when the exact gain is not above 0, where
    there is no share); then the days on which the two sets are equal, which do not decide; and,
    for a seat with a day left out, that a seat needs every day. No player is named."""
    gain = d["gain"]
    if d["kept"] is None:
        kept = (
            f"the exact search made no gain ({gain['exact']:.4f}), so the surrogate need only "
            f"not fall below it: its gain {gain['surrogate']:.4f}"
        )
    else:
        kept = (
            f"the surrogate kept {kept_words(d)} of the exact search's gain "
            f"({gain['surrogate']:.4f} of {gain['exact']:.4f}; needs {d['needs']:.0%})"
        )
    line_ = f"{kept}; equal sets on {d['matched']} of {d['of']} league-days"
    if d["of"] < vg.SURROGATE_OF:
        line_ += f"; {d['of']} of {vg.SURROGATE_OF} days compared, and a seat needs every one"
    return line_


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
        print(f"{g['name']:16} {g['season']!s:12} {state} seat {d['seat']}: {seat_line(d)}")
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
# --------------------------------------------------------------------------- trace
#: The span the guard gives a trace whose estimate no record holds (the arms form): one task of
#: the pair, the exact tier's included.
TRACE_HOURS = 0.5
#: What a record's own estimate of one task is multiplied by for the guard: the recorder's work
#: and a slower hour.
TRACE_MARGIN = 1.5
#: What a trace is, in its record.
TRACE_NOTE = (
    "one path of one pair played again with a recorder watching: arm A's and arm B's seasons on "
    "the same draws, day by day; a look at one path of its season, which proves nothing (a pair "
    "is judged on its record's figures over every path)"
)
#: How a trace was checked (``check.status``): a trace of a record that keeps its paths'
#: outcomes is checked on them; of one that keeps none, on its world, fit, versions, hash seed,
#: seat and league shape only; one that differed and was written on ``--drifted`` is marked so;
#: the arms form has no record to check on.
CHECKED = "checked"
WORLD_ONLY = "world and seat only: the record keeps no path's outcome"
DRIFTED = "drifted"
UNCHECKED = "not from a record"
#: The trace's record forms, and the folder record each reads.
TRACE_FORMS = ("screen", "tune")


@dataclass(frozen=True)
class TraceFrom:
    """A trace's record: the screen's or tune's (``kind``) folder record, the pair's own record
    of row ``key``, and what is read off them."""

    kind: str
    name: str
    key: str
    folder: Mapping[str, Any]
    pair: Mapping[str, Any]

    @property
    def spec(self) -> Mapping[str, Any]:
        return self.folder.get("spec") or {}

    @property
    def row(self) -> Mapping[str, Any]:
        """The row's own block in the pair's record: its lever, nudge and ``values``."""
        return self.pair.get(self.kind) or {}

    def seasons(self) -> list[int]:
        """The seasons the record searched: its world's, less a tune's confirmation season."""
        world = self.spec.get("world") or {}
        confirm = self.spec.get("confirm")
        return [int(t) for t in world.get("seasons") or () if t != confirm]

    def seconds(self) -> float | None:
        """The record's own estimate of one task of the pair (a screen's by row, a tune's by
        lever); None when it holds none."""
        estimates = (self.folder.get("timing") or {}).get("estimates") or {}
        e = estimates.get(self.key) or estimates.get(self.row.get("lever"))
        return None if not e else float(e["seconds_one"])


def world_defaults() -> argparse.Namespace:
    """Every cell and world flag at its default, as ``replay`` would read it with none named."""
    p = argparse.ArgumentParser(add_help=False)
    _cell_args(p, "the record's")
    _world_args(p)
    _run_args(p, paths=1)
    return p.parse_args([])


def trace_world_args(world: Mapping[str, Any], data: Path, rooms: int | None) -> argparse.Namespace:
    """``replay``'s flags for a screen's or a tune's world (its spec's ``world``,
    :data:`SCREEN_WORLD`): every flag at its default, then the world's own values (its seasons
    as ``--seasons`` names them); the pair's two arms are handed to the plan, so no file is
    read (:func:`pair_args`)."""
    ns = world_defaults()
    for k in SCREEN_WORLD:
        if k in world:
            v = world[k]
            setattr(ns, k, ",".join(str(t) for t in v) if k == "seasons" else v)
    ns.data, ns.rooms, ns.workers = data, rooms, 1
    return pair_args(ns, ns.seasons)


def trace_from(args: argparse.Namespace) -> TraceFrom | int:
    """The record a trace is made from, read and refused by name: a screen's or a tune's that
    exists, a row of it that was played, never a tune's confirmation pair."""
    kind = "screen" if args.screen is not None else "tune"
    name = args.screen if kind == "screen" else args.tune
    if args.row is None:
        print(f"refused: a trace from a {kind} names its row (--row KEY)")
        return 2
    try:
        if kind == "screen":
            folder = reader.read_screen(args.data, name)
            pair = None if folder is None else reader.read_screen_pair(args.data, name, args.row)
        else:
            folder = reader.read_tune(args.data, name)
            pair = None if folder is None else reader.read_tune_pair(args.data, name, args.row)
    except (reader.SimReadError, ValueError) as e:
        print(f"refused: {e}")
        return 2
    if folder is None:
        print(f"refused: no {kind} named {name!r} under {args.data / reader.SIM_DIR}")
        return 2
    if pair is None:
        print(f"refused: the {kind} {name!r} has no played pair {args.row!r}")
        return 2
    if kind == "tune" and "confirmation" in (pair.get("tune") or {}):
        print(
            f"refused: {args.row!r} is the tune's confirmation pair: a trace never plays a "
            "tune's confirmation season"
        )
        return 2
    if pair.get("design") != "paired":
        print(f"refused: {args.row!r} is not a pair's record")
        return 2
    return TraceFrom(kind, name, args.row, folder, pair)


def trace_drift(
    got: TraceFrom,
    wa: argparse.Namespace,
    plan: ReplayPlan,
    made: ReplayTasks,
    path: int,
) -> list[str]:
    """What of the record the code and the world on file no longer give, before any day is
    played: the world's spec (the screen's own test, ``screen.spec_differs``), the replay's
    version, the fit's and the book's hashes, and path ``path``'s seat and league shape."""
    out: list[str] = []
    spec = got.spec
    rebuilt = screen_spec(wa, spec.get("arm") or {}, list(spec.get("levers") or ()), plan)
    differs = sc.spec_differs({k: spec.get(k) for k in rebuilt}, rebuilt)
    if differs is not None:
        out.append(f"the {got.kind}'s spec: {differs}")
    pair = got.pair
    if pair.get("replay_version") != REPLAY_VERSION:
        out.append(
            f"replay_version: the pair was played under {pair.get('replay_version')}, the code "
            f"is {REPLAY_VERSION}"
        )
    if pair.get("fit_sha") != plan.sha:
        out.append("the fit's hash: the pair's is not the fit on file")
    book = None if plan.book is None else plan.book[1]
    if pair.get("book_sha") != book:
        out.append("the price book's hash: the pair's is not the book on file")
    v = made.visits[path]
    seats = (pair.get("seat") or {}).get("by_path") or []
    shapes_ = (pair.get("league") or {}).get("by_path") or []
    seat = v.shape.ids[v.turn % v.shape.teams]
    if path >= len(seats) or seats[path] != seat:
        out.append(f"path {path}'s seat: the record's is not {seat}")
    if path >= len(shapes_) or shapes_[path] != {"shape": v.index, "turn": v.turn}:
        out.append(f"path {path}'s league shape and turn differ from the record's")
    return out


def recorded_outcomes(
    pair: Mapping[str, Any], season: int, label: str, path: int
) -> tuple[str, dict[str, Any] | None]:
    """The pair's recorded outcomes on path ``path`` of the cell (``by_path``): (``CHECKED``,
    them), or (:data:`WORLD_ONLY`, None) for a record that keeps none; a path the record voided
    is said so."""
    block = pair.get("by_path")
    if not isinstance(block, Mapping):
        return WORLD_ONLY, None
    cell = ((block.get("by_season") or {}).get(str(season)) or {}).get(label) or []
    got = next((x for x in cell if x.get("path") == path), None)
    if got is None:
        return "world and seat only: the record voided this path", None
    return CHECKED, {"a": got.get("a"), "b": got.get("b")}


def trace_task(made: ReplayTasks, season: int, label: str, path: int) -> int | None:
    """The index of the task of ``season``'s cell of ``label`` on ``path``."""
    want = {"season": season, "forecaster": label, "path": path}
    return next((i for i, k in enumerate(made.keys) if dict(k) == want), None)


def play_trace(
    plan: ReplayPlan, made: ReplayTasks, i: int
) -> tuple[dict[str, Any], tr.Recorder, float]:
    """Task ``i`` of the pair played with a :class:`trace.Recorder` watching (``task_paired``'s
    ``watch``): its result, the recorder and the seconds it took."""
    held: dict[str, tr.Recorder] = {}

    def watch(setups: Mapping[str, Any], me: int) -> tuple[Any, Any]:
        held["rec"] = tr.Recorder(setups, me, plan.arms)
        return held["rec"].hooks()

    t0 = clock.perf_counter()
    out = made.task(*made.tasks[i], watch=watch)
    return out, held["rec"], clock.perf_counter() - t0


def cmd_trace(args: argparse.Namespace) -> int:
    ok, why = guard(0.0, rooms=args.rooms)
    if not ok:
        print(f"refused: {why}")
        return 2
    if args.path < 0:
        print("refused: --path is a path's number, 0 or more")
        return 2
    got: TraceFrom | None = None
    defaults = world_defaults()
    if args.arms is None:
        named = [
            k
            for k in SCREEN_WORLD
            if k not in ("paths", "seed") and getattr(args, k, None) != getattr(defaults, k, None)
        ]
        named += [] if args.seed is None else ["seed"]
        if named:
            print(
                f"refused: a trace from a record plays the record's world; it names no world "
                f"flag (--{named[0].replace('_', '-')})"
            )
            return 2
        read = trace_from(args)
        if isinstance(read, int):
            return read
        got = read
        searched = got.seasons()
        played = [int(t) for t in got.pair.get("seasons") or ()]
        if args.season is None and len(played) != 1:
            print(f"refused: the pair played {len(played)} seasons: name one (--season)")
            return 2
        season = played[0] if args.season is None else args.season
        if season not in searched or season not in played:
            print(
                f"refused: a trace from a {got.kind} plays only a season it searched "
                f"({', '.join(str(t) for t in searched) or 'none'}), never a tune's confirmation "
                "season"
            )
            return 2
        recorded = got.pair.get("hash_seed")
        if recorded not in (None, "random") and hash_seed() != recorded:
            print(
                f"refused: the pair was played under PYTHONHASHSEED={recorded}; this process "
                f"runs under {hash_seed()}: set it to the record's"
            )
            return 2
        wa = trace_world_args(got.spec.get("world") or {}, args.data, args.rooms)
        specs = [dict(got.pair["specs"]["a"]), dict(got.pair["specs"]["b"])]
        planned = screen_pair(wa, specs, read_season, set(), f"the pair of {got.key}")
        if isinstance(planned, int):
            return planned
        plan, made = planned
    else:
        if args.row is not None or args.season is not None:
            print("refused: the arms form names its season with --seasons, and no --row")
            return 2
        if args.seasons is None:
            print("refused: the arms form names its one season (--seasons)")
            return 2
        try:
            seasons = parse_seasons(args.seasons)
        except ValueError:
            seasons = []
        if len(seasons) != 1:
            print("refused: a trace plays one season: --seasons names one")
            return 2
        season = seasons[0]
        wa = argparse.Namespace(
            **{
                **vars(args),
                "seats": None,
                "no_peek": None,
                "paths": args.path + 1,
                "workers": 1,
                "seed": 1 if args.seed is None else args.seed,
            }
        )
        plan_ = replay_plan(wa)
        if isinstance(plan_, int):
            return plan_
        plan = plan_
        made = replay_tasks(plan, wa)
    labels = sorted({str(k["forecaster"]) for k in made.keys if k["season"] == season})
    if args.forecaster is not None and args.forecaster not in labels:
        print(f"refused: --forecaster {args.forecaster!r}: one of {', '.join(labels)}")
        return 2
    if args.forecaster is None and len(labels) != 1:
        print(f"refused: the season has {len(labels)} forecasters' cells: name one (--forecaster)")
        return 2
    label = args.forecaster or labels[0]
    i = trace_task(made, season, label, args.path)
    if i is None:
        print(f"refused: path {args.path} is not one of the pair's {made.paths} paths")
        return 2
    v = made.visits[args.path]
    drift: list[str] = []
    status, expected = UNCHECKED, None
    seconds = None
    if got is not None:
        drift = trace_drift(got, wa, plan, made, args.path)
        status, expected = recorded_outcomes(got.pair, season, label, args.path)
        seconds = got.seconds()
    whose = f"{got.kind} {got.name!r}, row {got.key}" if got is not None else "the arms named"
    print(
        f"trace: {whose}, season {season}, forecaster {label}, path {args.path} "
        f"({v.shape.label()}, turn {v.turn})"
    )
    for d in drift:
        print(f"differs from the record: {d}")
    if drift and not args.drifted:
        print(
            "STOPPED: the code or the world has moved since the pair was played; nothing played "
            "(--drifted writes the trace marked as drifted)"
        )
        return 1
    hours = (
        args.expected_hours
        if args.expected_hours is not None
        else TRACE_HOURS
        if seconds is None
        else seconds * TRACE_MARGIN / 3600
    )
    print(
        "one task of the pair: "
        + (
            "no record holds its estimate"
            if seconds is None
            else f"about {seconds:.0f}s on the record's own estimate"
        )
        + f"; the guard is given {hours:.2f} h"
    )
    print(f"to check: {status}" + ("" if expected is None else " (the path's outcomes)"))
    name = args.name or (
        f"{got.kind}-{got.name}-{got.key}-path{args.path}"
        if got is not None
        else f"arms-{season}-path{args.path}"
    )
    target = reader.trace_path(args.data, name)
    if target.exists():
        print(
            f"refused: a trace named {name!r} is on file ({target}): name this one another (--name)"
        )
        return 2
    if args.dry_run:
        print(f"dry run: nothing played, nothing written (would write {target})")
        return 0
    ok, why = guard(hours, rooms=args.rooms, announced=args.announced)
    if not ok:
        print(f"refused: {why}")
        return 2
    started = datetime.now(UTC)
    out, rec, took = play_trace(plan, made, i)
    outcomes = {"a": out["a"], "b": out["b"]}
    if expected is not None and outcomes != expected:
        drift.append("the path's outcomes: the trace's are not the record's")
        print("differs from the record: the path's outcomes")
        if not args.drifted:
            print(
                "STOPPED: the code has moved since the pair was played; nothing written "
                "(--drifted writes the trace marked as drifted)"
            )
            return 1
    rules = plan.league_rules
    payload = base_payload(
        "trace",
        name,
        started,
        plan.sha,
        plan.fit_path,
        plan.fit,
        1,
        plan.arms,
        policy.executions_of(rules.waivers, rules.waiver_rule, rules.same_day),
        policy.measure(rules.points is not None, rules.one_win),
        plan.book,
    )
    row = {} if got is None else got.row
    payload |= {
        "note": TRACE_NOTE,
        "source": {"form": "arms"}
        if got is None
        else {
            "form": got.kind,
            "name": got.name,
            "row": got.key,
            "pair_name": got.pair.get("name"),
        },
        "check": {
            "status": DRIFTED if drift else status,
            "drift": drift,
            **({} if got is None else {"record_hash_seed": got.pair.get("hash_seed")}),
        },
        "season": season,
        "forecaster": label,
        "seed": wa.seed,
        "path": args.path,
        "league": {
            "rules": rules.payload(),
            "label": rules.label(),
            "shape": v.index,
            "turn": v.turn,
            "shape_label": v.shape.label(),
        },
        "pair": {
            "lever": row.get("lever"),
            "nudge": row.get("nudge"),
            "values": row.get("values"),
            "arms": {k: arm.name for k, arm in plan.arms.items()},
            "specs": dict(zip(PAIR, plan.specs, strict=True)),
            "knobs": {k: dict(arm.knobs) for k, arm in plan.arms.items()},
        },
        "outcomes": {**outcomes, "difference": out["delta"]},
        "scale": out.get("scale"),
        "timing": {"seconds": round(took, 1)},
        "confirmation": None,
        **rec.payload(),
    }
    if season == CONFIRMATION:
        look, ledger = reader.append_look(
            args.data,
            {
                "started_at": payload["started_at"],
                "name": name,
                "design": "trace",
                "seasons": [season],
                "forecasters": [label],
                "specs": {k: spec_hash(s) for k, s in zip(PAIR, plan.specs, strict=True)},
                "fit_sha": plan.sha,
                "code_sha": payload["code_sha"],
            },
        )
        payload["confirmation"] = {
            "season": CONFIRMATION,
            "look": look,
            "ledger": str(ledger),
            "note": CONFIRMATION_NOTE,
        }
        print(f"confirmation season {CONFIRMATION}: look {look}, appended to {ledger}")
    payload["finished_at"] = datetime.now(UTC).isoformat()
    path = reader.write_trace(args.data, name, payload)
    first = payload["differ"]["first"]
    print(
        f"played in {took:.1f}s: {sum(len(a['days']) for a in payload['arms'].values())} arm-days; "
        + ("the arms decide alike every day" if first is None else f"they first differ on {first}")
    )
    breaches = [b for a in payload["arms"].values() for b in (a["end"] or {}).get("breaches", [])]
    print(f"the check: {payload['check']['status']}")
    print(f"written: {path}")
    if breaches:
        print(f"AUDIT: {len(breaches)} breach(es) in the traced path; the trace holds them")
        return AUDIT_EXIT
    return 0


def _run_args(p: argparse.ArgumentParser, paths: int) -> None:
    p.add_argument("--paths", type=int, default=paths, help=f"paths a cell (default {paths})")
    p.add_argument("--seed", type=int, default=1, help="the run's seed (default 1)")
    p.add_argument("--workers", type=int, default=None, help="processes (default cores less two)")
    p.add_argument("--name", default=None, help="the run's name in its payload and file")
    p.add_argument("--expected-hours", type=float, default=None, help="override the estimate")
    p.add_argument(
        "--announced",
        action="store_true",
        help="the run over an hour was announced on the tracker and the user said to start it: "
        "passed only on the user's word",
    )
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
        "--seat-draft",
        choices=adp.SEAT_DRAFTS,
        default=None,
        help="with --adp espn: how an arm's seat drafts: market, as the rival in its seat does, "
        "less the players its own forecaster cannot value (the default); own, on its own "
        "forecaster's per-game value alone, the rule before 2026-11-18",
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
        "teams, slots and playoffs each a value of the grid's, adds any positive whole count or "
        "none, a key left out the fixed shape's; not with --grid full",
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
        "--lineup-from",
        default=None,
        metavar="DAY",
        help="when a free agent's add plays, in every seat's league: tomorrow, it lands the "
        "morning after it is made; today, the day it is made, before that day's lineups (a claim "
        "is decided as before, so under continuous waivers today moves nothing) (default "
        "tomorrow)",
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
    tu = sub.add_parser(
        "tune",
        help="the levers' values searched one lever at a time, then the final set played once "
        "on a season the search never played",
    )
    tu.add_argument(
        "--arm",
        type=Path,
        required=True,
        metavar="SPEC",
        help="the baseline arm's spec file: the search starts from it and the final set is "
        "played against it",
    )
    tu.add_argument(
        "--screen",
        default=None,
        metavar="NAME",
        help="the screen whose survivors are tuned, strongest first by difference over SE; "
        "its baseline arm and league kind must be this tune's, and it must not have played "
        "the season --confirm names",
    )
    tu.add_argument(
        "--levers",
        nargs="+",
        default=None,
        metavar="NAME",
        help="the levers to tune, by name: in the screen's order with --screen, else the "
        "list's (default the screen's survivors)",
    )
    tu.add_argument(
        "--passes",
        type=int,
        default=tn.PASSES,
        metavar="N",
        help=f"the passes over the levers; a pass that moves none ends the search (default "
        f"{tn.PASSES})",
    )
    tu.add_argument(
        "--confirm",
        default=str(CONFIRMATION),
        metavar="SEASON",
        help="the season the final set is played on against the baseline, once, withheld from "
        f"the search and from the screen named; never {HOLD_OUT}; it must be one the tune's "
        "world can play (its draft table under --adp, a forecaster the search reads); none "
        "plays no confirmation, a look at the machinery and not a verdict (default "
        f"{CONFIRMATION})",
    )
    _cell_args(
        tu,
        "every season on file that is neither the hold-out, the confirmation season nor "
        "--confirm's",
    )
    _world_args(tu)
    tu.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        metavar="N",
        help="start no pair whose estimate would pass N minutes from the start: stop cleanly, "
        "and the same command takes the tune up again",
    )
    _run_args(tu, paths=SCREEN_PATHS)
    tu.set_defaults(func=cmd_tune)
    tc = sub.add_parser(
        "trace",
        help="one path of one pair played again with a recorder watching: both arms' seasons day "
        "by day, written under data/sim/traces/",
    )
    whence = tc.add_mutually_exclusive_group(required=True)
    whence.add_argument(
        "--screen",
        default=None,
        metavar="NAME",
        help="a screen's pair: its arms and its world are the screen's record's",
    )
    whence.add_argument(
        "--tune",
        default=None,
        metavar="NAME",
        help="a tune's pair of its search (never its confirmation): its arms and world the tune's",
    )
    whence.add_argument(
        "--arms",
        type=Path,
        nargs=2,
        default=None,
        metavar="SPEC",
        help="arm A's and arm B's spec files, on the world the flags name, as replay takes them",
    )
    tc.add_argument("--row", default=None, metavar="KEY", help="with --screen or --tune: the pair")
    tc.add_argument("--path", type=int, required=True, metavar="N", help="the pair's path played")
    tc.add_argument(
        "--season",
        type=int,
        default=None,
        help="with --screen or --tune: the season, one the record searched (default the pair's "
        "only one)",
    )
    tc.add_argument(
        "--forecaster",
        default=None,
        help="the cell's forecaster (default the season's only one)",
    )
    tc.add_argument(
        "--drifted",
        action="store_true",
        help="write a trace whose record the code or the world no longer gives, marked drifted "
        "(default: stop and write nothing)",
    )
    _cell_args(tc, "none: with --arms one season, named")
    _world_args(tc)
    tc.add_argument(
        "--seed", type=int, default=None, help="with --arms: the run's seed (default 1)"
    )
    tc.add_argument("--name", default=None, help="the trace's name and file")
    tc.add_argument("--expected-hours", type=float, default=None, help="override the estimate")
    tc.add_argument(
        "--announced",
        action="store_true",
        help="a trace over an hour was announced on the tracker and the user said to start it",
    )
    tc.add_argument("--dry-run", action="store_true", help="plan and check, play and write nothing")
    tc.set_defaults(func=cmd_trace)
    va = sub.add_parser(
        "validate", help="gate 5: the gain the surrogate keeps of the exact search's, on a replay"
    )
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
