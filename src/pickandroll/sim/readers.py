"""The season simulator's readers and writers (#172, PR 2b).

The simulator's core (the other modules of ``pickandroll.sim``) is pure; everything here reads what
it needs from ``data/`` and writes what it leaves. The **fit** is the newest frozen one under
``data/sim/fit/``, its hash checked against the file. A **replay** is a made-up league on a recorded
season's game lines (``sim.gamelogs``), each scoring period dated from the season's first
(:data:`PERIOD_ONE`); the forecasters' figures and each belief label's weights are read from the
same logs. Every run's payload goes under ``data/sim/runs/`` with the fit's hash and the hold-out
named (the master's conditions on #172). Nothing here reads a live league (#172, PR D3). The
**book** (PR Fd) is the newest under ``data/sim/bids/``, its hash checked as the fit's; the
winning-bids table it is fitted on is read under ``data/external/bids/``, its ``.sha256`` checked
first, and only the columns ``bids.READ`` names.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import adp, bids, gamelogs
from . import fit as fitmod
from . import forecast as fc
from . import run as rn
from .engine import wk
from .state import Member

SIM_DIR = Path("sim")
FIT_DIR = SIM_DIR / "fit"
RUNS_DIR = SIM_DIR / "runs"
#: The confirmation season's ledger (#172, PR D2): one JSON line a written run that names it.
LEDGER = SIM_DIR / "confirmation-looks.jsonl"
LOGS_DIR = Path("external") / "espn" / "gamelogs"
#: The rivals' price book (#172, PR Fd), and the table it is fitted on.
BIDS_DIR = SIM_DIR / "bids"
TABLE_DIR = Path("external") / "bids"
#: The first scoring period's date, by ESPN season id (the year the season ends in): period
#: ``p`` is this date plus ``p − 1`` days. Verified against ESPN's scoreboard event ids on
#: 2026-10-24, three games a season; 2023's period 1 is the day before opening night.
PERIOD_ONE: Mapping[int, date] = {
    2022: date(2021, 10, 19),
    2023: date(2022, 10, 17),
    2024: date(2023, 10, 24),
    2025: date(2024, 10, 22),
    2026: date(2025, 10, 21),
}
PERIOD_SOURCE = "ESPN scoreboard event ids, 2026-10-24"
#: ESPN's position ids (``defaultPositionId``) and the eligible slots that are a position.
ESPN_POSITIONS: Mapping[int, str] = {1: "PG", 2: "SG", 3: "SF", 4: "PF", 5: "C"}
ESPN_SLOTS: Mapping[int, str] = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F"}


class SimReadError(ValueError):
    """What a run needs is not on disk, or not trusted."""


# --------------------------------------------------------------------------- the fit
def fit_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def newest_fit(data_dir: Path) -> tuple[dict[str, Any], str, Path]:
    """The newest frozen fit, its hash and its file; refused when the hash beside it does not
    match the file (a fit edited after it was frozen)."""
    files = sorted((data_dir / FIT_DIR).glob("*/fit.json"))
    if not files:
        raise SimReadError(f"no frozen fit under {data_dir / FIT_DIR}")
    path = files[-1]
    payload = json.loads(path.read_text())
    sha = fit_hash(payload)
    beside = path.with_name("fit.sha256")
    if beside.exists() and beside.read_text().strip() != sha:
        raise SimReadError(f"{path}: the hash beside it does not match the file")
    return payload, sha, path


# --------------------------------------------------------------------------- the book (PR Fd)
def bids_rows(data_dir: Path) -> tuple[list[dict[str, str]], str, Path]:
    """The winning-bids table's rows, each restricted to the columns ``bids.READ`` names, its
    hash and its file; refused when the table or its ``.sha256`` is missing, when the hash
    beside it does not match the file, or when a column the fit reads is not in it."""
    path = data_dir / TABLE_DIR / bids.TABLE
    beside = path.with_name(f"{bids.TABLE}.sha256")
    if not path.exists():
        raise SimReadError(f"no winning-bids table at {path}")
    if not beside.exists():
        raise SimReadError(f"{path}: no {beside.name} beside it")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    told = beside.read_text().split()
    if not told or told[0] != sha:
        raise SimReadError(f"{path}: the hash beside it does not match the file")
    reader = csv.DictReader(io.StringIO(data.decode()))
    missing = [c for c in bids.READ if c not in (reader.fieldnames or ())]
    if missing:
        raise SimReadError(f"{path}: no column {missing[0]!r}")
    return [{c: row[c] for c in bids.READ} for row in reader], sha, path


def newest_book(data_dir: Path) -> tuple[dict[str, Any], str, Path]:
    """The newest price book, its hash and its file; refused when there is none, or when the hash
    beside it does not match the file (a book edited after it was written)."""
    files = sorted((data_dir / BIDS_DIR).glob("*/book.json"))
    if not files:
        raise SimReadError(f"no price book under {data_dir / BIDS_DIR} (fit-bids writes one)")
    path = files[-1]
    payload = json.loads(path.read_text())
    sha = fit_hash(payload)
    beside = path.with_name("book.sha256")
    if beside.exists() and beside.read_text().strip() != sha:
        raise SimReadError(f"{path}: the hash beside it does not match the file")
    return payload, sha, path


def code_sha(root: Path) -> str | None:
    """The checkout's commit, for the payload (the commands read it, the core stays pure)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


# --------------------------------------------------------------------------- a replay
def period_date(season: int, period: int) -> date:
    if season not in PERIOD_ONE:
        raise SimReadError(f"season {season}: no first period on file")
    return PERIOD_ONE[season] + timedelta(period - 1)


def replay_lines(
    data_dir: Path, season: int
) -> tuple[dict[int, dict[date, dict[str, float]]], dict[int, Member], dict[int, list[date]]]:
    """A recorded season's lines by player and date (the games he played), its players as
    members (name, NBA team as ESPN numbers it, positions from the eligible slots), and each
    player's scheduled games (every entry, played or not: his team's games while he was on it)."""
    body = gamelogs.load_season(season, data_dir / LOGS_DIR)
    if body is None:
        raise SimReadError(f"season {season}: no cached log under {data_dir / LOGS_DIR}")
    lines: dict[int, dict[date, dict[str, float]]] = {}
    scheduled: dict[int, list[date]] = {}
    for ln in gamelogs.lines_of(body, season):
        day = period_date(season, ln.period)
        scheduled.setdefault(int(ln.player), []).append(day)
        if not ln.played:
            continue
        stats = {k: float(v) for k, v in ln.stats.items() if k in wk.STATS}
        lines.setdefault(int(ln.player), {})[day] = stats
    members: dict[int, Member] = {}
    for row in body.get("players") or []:
        p = row.get("player") or {}
        pid = int(p.get("id"))
        positions = tuple(
            ESPN_SLOTS[s] for s in (p.get("eligibleSlots") or []) if s in ESPN_SLOTS
        ) or (
            (ESPN_POSITIONS[p["defaultPositionId"]],)
            if p.get("defaultPositionId") in ESPN_POSITIONS
            else ()
        )
        team = p.get("proTeamId")
        members[pid] = Member(
            pid, str(p.get("fullName") or pid), None if team is None else str(team), positions
        )
    return lines, members, {k: sorted(v) for k, v in scheduled.items()}


def adp_table(data_dir: Path, season: int, hold_out: int | None) -> tuple[adp.Table, str]:
    """The table of average draft positions in ``season``'s own log (``adp.espn_table``) and the
    log file's hash (#172, PR D4a). The hold-out is refused before its log is opened; a season
    with no log, or a log whose players all carry one figure, is refused by name."""
    if season == hold_out:
        raise SimReadError(f"{hold_out} is the hold-out; no run plays it")
    path = data_dir / LOGS_DIR / f"{season}.json"
    if not path.is_file():
        raise SimReadError(f"season {season}: no cached log under {data_dir / LOGS_DIR}")
    raw = path.read_bytes()
    try:
        table = adp.espn_table(json.loads(raw).get("body") or {})
    except adp.NoTable as e:
        raise SimReadError(f"season {season} has no draft table: {e}") from None
    return table, hashlib.sha256(raw).hexdigest()


def prior_rates(
    data_dir: Path, season: int, min_games: int = rn.STANDIN_MIN_GAMES
) -> dict[int, dict[str, float]]:
    """The ``prior`` forecaster (``forecast.prior``): the prior season's per-game rates, for the
    players with ``min_games`` played games in the prior season: a player new to the league that
    season, or who missed most of the last, has none and arrives by the newcomer's rule."""
    lines, _, _ = replay_lines(data_dir, season - 1)
    return fc.prior(lines, min_games)


def espn_rates(data_dir: Path, season: int) -> tuple[dict[int, dict[str, float]], dict[int, float]]:
    """The ``espn`` forecaster (``forecast.espn``): ESPN's stored projection for ``season`` from
    its cached log, per game, for every player whose block has games above zero, and those
    games (the freeze check's, ``forecast.freeze_of``). Refused when the log or the blocks are
    not on file."""
    body = gamelogs.load_season(season, data_dir / LOGS_DIR)
    if body is None:
        raise SimReadError(f"espn: season {season} has no cached log under {data_dir / LOGS_DIR}")
    totals = gamelogs.totals_of(body, season, gamelogs.PROJECTED)
    rates = fc.espn(gamelogs.per_game(totals))
    if not rates:
        raise SimReadError(f"espn: season {season}'s log holds no projection block with games")
    games = {int(pid): float(t["games"]) for pid, t in totals.items() if t.get("games", 0.0) > 0}
    return rates, games


def marcel_seasons(data_dir: Path, season: int) -> list[int]:
    """The seasons ``marcel`` reads for ``season``: the one before it and back, while each is on
    file (:func:`seasons_on_file`), up to ``len(forecast.MARCEL_WEIGHTS)``, most recent first."""
    on_file = set(seasons_on_file(data_dir, season))
    out: list[int] = []
    for t in range(season - 1, season - 1 - len(fc.MARCEL_WEIGHTS), -1):
        if t not in on_file:
            break
        out.append(t)
    return out


def marcel_rates(data_dir: Path, season: int) -> tuple[dict[int, dict[str, float]], list[int]]:
    """The ``marcel`` forecaster (``forecast.marcel``) for ``season`` and the seasons it read;
    refused when fewer than ``forecast.MARCEL_SEASONS`` earlier seasons are on file."""
    read = marcel_seasons(data_dir, season)
    try:
        return fc.marcel([replay_lines(data_dir, t)[0] for t in read]), read
    except fc.CannotServe as e:
        raise SimReadError(f"season {season}: {e}") from None


def seasons_on_file(data_dir: Path, before: int) -> list[int]:
    """The seasons whose log is cached and dated (:data:`PERIOD_ONE`), earlier than ``before``:
    read from the file names, so no later season's file is opened."""
    folder = data_dir / LOGS_DIR
    out = []
    for path in folder.glob("*.json") if folder.is_dir() else ():
        if path.stem.isdigit() and int(path.stem) < before and int(path.stem) in PERIOD_ONE:
            out.append(int(path.stem))
    return sorted(out)


def belief_weights(data_dir: Path, season: int, hold_out: int | None) -> fitmod.BeliefWeights:
    """The causal belief's weights for a replay of ``season`` under the prior-season forecaster:
    fitted on every season on file earlier than it whose prior season is on file too, neither of
    them the hold-out; the default when none qualifies. Since #172's PR D2 these are the prior
    label's own weights and every other label's fallback (:func:`label_weights`)."""
    on_file = set(seasons_on_file(data_dir, season))
    samples = []
    for t in sorted(on_file):
        if t - 1 not in on_file or hold_out in (t, t - 1):
            continue
        lines, _, _ = replay_lines(data_dir, t)
        samples.append(fitmod.BeliefSample(t, t - 1, prior_rates(data_dir, t), lines))
    return fitmod.belief_weights(samples, hold_out)


# --------------------------------------------------------------------------- each label's weights
#: A belief a replay's seats may hold, as its weights' fit reads it (#172, PR D2): a forecaster,
#: or an arm's system on the two stand-ins.
BeliefLabel = fc.Forecaster | fc.SystemBelief


class _Seasons:
    """The recorded seasons a fit of the belief's weights reads, each read once: its lines, and
    each forecaster's projection of it with the seasons that projection read, or why there is
    none. A season's file is opened only once the hold-out is ruled out of what it would read."""

    def __init__(self, data_dir: Path, before: int, hold_out: int | None, seed: int, shape: str):
        self.data_dir, self.hold_out, self.seed, self.shape = data_dir, hold_out, seed, shape
        self.on_file = seasons_on_file(data_dir, before)
        self._lines: dict[int, dict[int, dict[date, dict[str, float]]]] = {}
        self._made: dict[tuple[int, str], tuple[Mapping[int, Any], tuple[int, ...]] | str] = {}

    def lines(self, t: int) -> dict[int, dict[date, dict[str, float]]]:
        if t not in self._lines:
            self._lines[t] = replay_lines(self.data_dir, t)[0]
        return self._lines[t]

    def reads(self, t: int, f: fc.Forecaster) -> tuple[int, ...] | str:
        """The seasons ``f``'s projection of ``t`` reads, from the file names alone; why it
        cannot serve ``t`` when it cannot."""
        if f.name == "prior":
            return (t - 1,) if t - 1 in self.on_file else f"prior: season {t - 1} is not on file"
        if f.name == "marcel":
            read = tuple(marcel_seasons(self.data_dir, t))
            if len(read) < fc.MARCEL_SEASONS:
                return (
                    f"marcel needs {fc.MARCEL_SEASONS} earlier seasons on file, it has {len(read)}"
                )
            return read
        return (t,)

    def projection(
        self, t: int, f: fc.Forecaster
    ) -> tuple[Mapping[int, Any], tuple[int, ...]] | str:
        """``f``'s projection of season ``t`` and the seasons it read, or why it gives no sample:
        it cannot serve ``t``, it would read the hold-out, or (``espn``) the projection fails the
        freeze check, having seen part of its own season."""
        key = (t, f.label)
        if key in self._made:
            return self._made[key]
        reads = self.reads(t, f)
        made: tuple[Mapping[int, Any], tuple[int, ...]] | str
        if isinstance(reads, str):
            made = reads
        elif self.hold_out is not None and self.hold_out in (t, *reads):
            made = f"{f.label}: its projection of {t} would read the hold-out {self.hold_out}"
        else:
            try:
                if f.name == "prior":
                    made = (prior_rates(self.data_dir, t), reads)
                elif f.name == "espn":
                    rates, games = espn_rates(self.data_dir, t)
                    played = {k: len(v) for k, v in self.lines(t).items()}
                    freeze = fc.freeze_of(games, played)
                    made = (
                        f"espn: the projection of {t} fails the freeze check (median projected "
                        f"games {freeze['median_projected_games']:g} below {fc.FREEZE_LINE:g})"
                        if freeze["flagged"]
                        else (rates, reads)
                    )
                elif f.name == "marcel":
                    rates, read = marcel_rates(self.data_dir, t)
                    made = (rates, tuple(read))
                else:
                    assert f.spread is not None
                    rates = fc.oracle(
                        self.lines(t), f.spread, self.seed, 0, self.shape, role=f.role, fit_season=t
                    )
                    made = (rates, reads)
            except (SimReadError, fc.CannotServe) as e:
                made = str(e) if f.name in str(e) else f"{f.name}: {e}"
        self._made[key] = made
        return made

    def sample(self, t: int, label: BeliefLabel) -> fitmod.BeliefSample | str:
        """The label's sample of season ``t``, or why there is none."""
        if t == self.hold_out:
            return f"{t} is the hold-out"
        if isinstance(label, fc.SystemBelief):
            first = self.projection(t, label.first)
            if isinstance(first, str):
                return f"the first stand-in cannot serve it ({first})"
            second = self.projection(t, label.second)
            if isinstance(second, str):
                return f"the second stand-in cannot serve it ({second})"
            rates = fc.system_rates(label.system, label.blend, first[0], second[0])
            read = tuple(sorted({*first[1], *second[1]}))
            return fitmod.BeliefSample(t, None, rates, self.lines(t), read)
        made = self.projection(t, label)
        if isinstance(made, str):
            return made
        rates, read = made
        prior_season = t - 1 if label.name == "prior" else None
        return fitmod.BeliefSample(t, prior_season, rates, self.lines(t), read)


def label_weights(
    data_dir: Path,
    season: int,
    hold_out: int | None,
    labels: Sequence[BeliefLabel],
    seed: int,
    shape: str,
    prior: fitmod.BeliefWeights | None = None,
) -> dict[str, fitmod.LabelWeights]:
    """Each belief label's weights for a replay of ``season`` (#172, PR D2), by label: fitted on
    the label's own projection of every season on file earlier than it that the label can serve
    (``prior`` as :func:`belief_weights`; ``espn`` the season's stored projection, none where it
    fails the freeze check; ``marcel`` where two earlier seasons are on file; an oracle a draw of
    the season at its spread and ``shape`` on its fit keys, ``seed`` the run's; a system label
    ``forecast.system_rates`` on the two stand-ins' projections, where both serve the season).
    No sample's season, nor any season its projection read, is the hold-out. A label with no
    sample takes ``prior`` (the prior forecaster's, :func:`belief_weights` when not given) when
    those were fitted, else the default (``fit.label_weights``)."""
    seasons = _Seasons(data_dir, season, hold_out, seed, shape)
    if prior is None:
        prior = belief_weights(data_dir, season, hold_out)
    out: dict[str, fitmod.LabelWeights] = {}
    for label in labels:
        if label.label in out:
            continue
        samples: list[fitmod.BeliefSample] = []
        left_out: dict[int, str] = {}
        for t in seasons.on_file:
            got = seasons.sample(t, label)
            if isinstance(got, str):
                left_out[t] = got
            else:
                samples.append(got)
        out[label.label] = fitmod.label_weights(label.label, samples, hold_out, prior, left_out)
    return out


# --------------------------------------------------------------------------- the run's record
def run_path(data_dir: Path, kind: str, name: str, started: datetime) -> Path:
    stamp = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "run"
    return data_dir / RUNS_DIR / f"{stamp}-{kind}-{safe}.json"


def write_run(data_dir: Path, payload: Mapping[str, Any]) -> Path:
    """The payload under ``data/sim/runs/``; the fit's hash and the hold-out must be
    in it (the master's conditions)."""
    for key in ("fit_sha", "hold_out"):
        if key not in payload:
            raise ValueError(f"a run payload names {key}")
    path = run_path(
        data_dir,
        str(payload["kind"]),
        str(payload.get("name") or "run"),
        datetime.fromisoformat(str(payload["started_at"])),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str))
    return path


def append_look(data_dir: Path, record: Mapping[str, Any]) -> tuple[int, Path]:
    """One line for a written run that names the confirmation season, appended to the ledger
    (:data:`LEDGER`) as ``{"look": n, **record}``: ``n`` the line's number, and the ledger's
    path. Lines are only ever appended."""
    path = data_dir / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.read_text().splitlines() if path.exists() else []
    n = 1 + sum(1 for line in before if line.strip())
    with path.open("a") as f:
        f.write(json.dumps({"look": n, **record}, sort_keys=True, default=str) + "\n")
    return n, path


__all__ = [
    "ESPN_POSITIONS",
    "ESPN_SLOTS",
    "FIT_DIR",
    "PERIOD_ONE",
    "PERIOD_SOURCE",
    "RUNS_DIR",
    "SimReadError",
    "belief_weights",
    "code_sha",
    "espn_rates",
    "fit_hash",
    "marcel_rates",
    "marcel_seasons",
    "newest_fit",
    "period_date",
    "prior_rates",
    "replay_lines",
    "run_path",
    "seasons_on_file",
    "write_run",
]
