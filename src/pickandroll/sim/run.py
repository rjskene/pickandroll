"""The runner (#172, PR 2b): one world a path, arms in lockstep, the paired difference.

A :class:`World` is one path of one league on a recorded season: each player's game days, his
availability and lines (the recorded lines are the truth: no game noise, no hazard, the logs
happened), the beliefs and what the policy has heard of each absence. :func:`replay_world` builds
it from a season's recorded lines, its seats believing only the games already played
(``sim.belief``) in a league drawn from what was known before the season (:func:`replay_setup`).
Every draw comes from ``world.rng(seed, path, player, game, stream)`` and never from an arm, so a
roster change in one arm reshuffles nothing for any player: common random numbers.

:func:`simulate` advances several variants of one league through the same world day by day: the
moves decided yesterday land, each seat decides on the day's beliefs, the lineup is set, the day
is played and scored; a hook is handed each day's :class:`DayRecord`. Variants whose
states agree share one solve (the lockstep of the design note); from the first divergence each
solves alone. :func:`paired` runs arm A and arm B for one seat and returns the paired difference
of the season's outcomes, B less A; :func:`room` runs a league's seats under named arms rotated
across paths.
Pure but for the process pool: nothing here reads a file; the readers (``sim.readers``) and the
commands (``sim.cli``) bring the inputs and write the payload.
"""

from __future__ import annotations

import math
import multiprocessing
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import numpy as np

from . import adp, audit, policy, shapes, world
from . import counts as ct
from . import league as lg
from . import opponents as op
from .belief import CausalBelief, newcomer_prior
from .engine import EACH_CATEGORY, FPTS, ONE_WIN, Week, mv, wk
from .fit import W_DEFAULT
from .forecast import MIN_GAMES, realized_rates
from .state import (
    Claim,
    Member,
    Resolved,
    Setup,
    SimState,
    board_draft,
    initial,
    round_robin,
    snake_draft,
    weeks_from,
)

Rates = Mapping[str, float]
#: The knobs an arm names (``policy.KNOBS``: the ten live ones and the simulator's two).
KNOBS = policy.KNOBS
#: The metrics a path reports for a seat.
METRICS = ("made_playoffs", "rank", "category_wins", "matchup_wins", "title")
#: How workers are counted when not given: the machine's cores less two.
SPARE_CORES = 2
NICE = 10


# --------------------------------------------------------------------------- the inputs
@dataclass(frozen=True)
class WorldInputs:
    """What a run reads of the frozen fit: the days before an absence is heard (``lag``) and the
    fit's hash."""

    lag: int
    sha: str


def inputs_of(payload: Mapping[str, Any], sha: str) -> WorldInputs:
    """A run's inputs from a frozen fit: the lag of a fitted refresh when the fit has one, else the
    refresh's defaults' (one day), and the hash. Nothing else of the fit is read, so a fit with or
    without a ``tau`` loads alike."""
    refresh = payload.get("refresh") or {}
    defaults = (payload.get("parameters") or {}).get("refresh_defaults") or {}
    return WorldInputs(lag=int(refresh.get("lag", defaults.get("lag", 1))), sha=sha)


# --------------------------------------------------------------------------- the arms
@dataclass(frozen=True)
class Arm:
    """One arm of a comparison: a tier with its knobs, what it executes, its opponents and its
    fields (``policy.Fields``)."""

    name: str
    tier: str
    knobs: Mapping[str, Any]
    opponents: Mapping[str, Any]
    executes: str = policy.QUEUE_SET
    with_plan: bool = True
    execute_plan: bool = False
    fields: policy.Fields = policy.DEFAULT_FIELDS
    #: The forecaster the arm's seat believes by (#172, PR D1): a label the run's world holds,
    #: None for the run's own. A run sets it; a spec file does not name it.
    forecaster: str | None = None

    def seat(self) -> op.Seat:
        return op.Seat(
            self.name,
            self.tier,
            dict(self.knobs),
            self.executes,
            self.with_plan,
            self.fields,
            self.forecaster,
        )


#: The keys of an arm's spec file the simulator reads (:func:`arm_of`, :func:`check_fit`); any
#: other is refused by name, so a misspelled field never leaves an arm at its default.
SPEC_KEYS = (
    "name",
    "tier",
    "knobs",
    "opponents",
    "executes",
    "with_plan",
    "execute_plan",
    *policy.FIELDS,
    "fit_sha",
)


def arm_of(spec: Mapping[str, Any]) -> Arm:
    """An arm from its spec file's JSON: ``name``, ``tier``, every knob, ``opponents``, and the
    four fields when it names them (``pool``, ``min_gain``, ``weeks_ahead``,
    ``surrogate_days``; ``policy.fields_of``); a key the simulator does not read
    (:data:`SPEC_KEYS`, and ``opponents.SPEC_KEYS`` under ``opponents``), a knob missing,
    unknown or out of the engine's bounds, a field out of its own or a tier unknown is refused
    by name."""
    unknown = [k for k in spec if k not in SPEC_KEYS]
    if unknown:
        raise ValueError(
            f"spec key {unknown[0]!r} is not one the simulator reads: one of {SPEC_KEYS}"
        )
    opponents = dict(spec.get("opponents") or {"kind": "static"})
    op.check_spec(opponents)
    tier = str(spec.get("tier", ""))
    if tier not in (*policy.TIERS, "static"):
        raise ValueError(f"tier {tier!r}: one of {policy.TIERS} or static")
    knobs = policy.check_knobs(spec.get("knobs") or {})
    executes = str(spec.get("executes", policy.QUEUE_SET))
    if executes not in policy.EXECUTES:
        raise ValueError(f"executes {executes!r}: one of {policy.EXECUTES}")
    return Arm(
        str(spec.get("name") or "arm"),
        tier,
        knobs,
        opponents,
        executes,
        bool(spec.get("with_plan", True)),
        bool(spec.get("execute_plan", False)),
        policy.fields_of(spec),
    )


def mirrored(arm: Arm) -> bool:
    """Whether ``arm``'s rivals in a comparison are its mirror, the surrogate on its knobs and
    fields: what the surrogate reads, the arm's run reads too."""
    return str(arm.opponents.get("kind", "static")) == "mirror"


def same_seat(
    a: Arm, b: Arm, shapes: Sequence[policy.Shape], rivals: bool = True
) -> list[str] | None:
    """When arms ``a`` and ``b`` differ only in knobs and fields that neither reads in any of
    ``shapes`` (``policy.reads``, ``policy.field_reads``; ``rivals``: whether the arms' rivals
    play, as in a comparison, so a mirror reads), each such name with why it is not read and what
    would make it read: the two are then the same seat, and a run of them a no-op by
    construction. None when they differ in anything else, in a name one of them reads in some
    shape, or in nothing at all (the same arm twice, a check that the difference is zero)."""

    def identity(arm: Arm) -> tuple[Any, ...]:
        return (
            arm.tier,
            arm.executes,
            arm.with_plan,
            arm.execute_plan,
            sorted(arm.opponents.items()) if rivals else None,
            arm.forecaster,
        )

    if identity(a) != identity(b):
        return None
    names = [k for k in policy.KNOBS if a.knobs[k] != b.knobs[k]] + [
        f for f in policy.FIELDS if getattr(a.fields, f) != getattr(b.fields, f)
    ]
    if not names:
        return None
    out = []
    for name in names:
        rows = []
        for arm in (a, b):
            mirror = rivals and mirrored(arm)
            for shape in shapes:
                table = policy.reads(arm, shape, mirror) | policy.field_reads(arm, mirror)
                rows.append(table[name])
        if policy.READ in rows:
            return None
        also = policy.WHEN_READ_FAAB.get(name)
        only = policy.WHEN_READ_H2H.get(name)
        out.append(
            f"{name} ({rows[0]}; read by {policy.WHEN_READ[name]})"
            + (f", and {also}" if also else "")
            + (f"; {only}" if only else "")
        )
    return out


def check_fit(spec: Mapping[str, Any], sha: str) -> None:
    """A spec names the frozen fit it was written for; another fit on disk refuses the run."""
    named = spec.get("fit_sha")
    if named and named != sha:
        raise ValueError(
            f"spec {spec.get('name')!r} names fit {named[:12]}, the fit on disk is {sha[:12]}"
        )


# --------------------------------------------------------------------------- the world
class World:
    """One path of one league on a recorded season: lines, availability, beliefs and news.

    The seats believe ``causal`` (a :class:`belief.CausalBelief`), read on each day. The told
    return date's spread is ``news_sd`` days. ``label`` names the run's forecaster, whose belief
    that is; a world may hold a belief for other forecasters too (``others``, by label),
    which a seat names (``opponents.Seat.forecaster``; #172, PR D1). ``split`` maps a split
    label (a ``yahoo`` or ``blend`` seat's) to its rostered side's label: such a seat reads that
    label's belief for every rostered player and its own for the rest (:meth:`seat_beliefs`)."""

    def __init__(
        self,
        setup: Setup,
        seed: int,
        path: int,
        game_days: Mapping[int, Sequence[date]],
        available: Callable[[int], np.ndarray],
        line: Callable[[int, int], Mapping[str, float] | None],
        lag: int,
        causal: CausalBelief,
        news_sd: float = world.NEWS_SD_DAYS,
        label: str | None = None,
        others: Mapping[str, CausalBelief] | None = None,
        split: Mapping[str, str] | None = None,
    ) -> None:
        self.setup = setup
        self.seed, self.path = seed, path
        self.game_days = {k: list(v) for k, v in game_days.items()}
        self._index = {k: {d: i for i, d in enumerate(v)} for k, v in self.game_days.items()}
        self._available = available
        self._line = line
        self.lag = lag
        self.causal = causal
        self.label = label
        self.others = {k: v for k, v in (others or {}).items() if k != label}
        self.split = dict(split or {})
        for name, rostered in self.split.items():
            for held in (name, rostered):
                if held != label and held not in self.others:
                    raise ValueError(f"forecaster {held!r}: the world holds no belief for it")
        self.news_sd = float(news_sd)
        self._avail: dict[int, np.ndarray] = {}
        self._absences: dict[int, list[world.Absence]] = {}
        self._lines: dict[tuple[int, date], Mapping[str, float] | None] = {}
        self._status: dict[date, tuple[dict[int, str | None], dict[int, date]]] = {}

    def available(self, player: int) -> np.ndarray:
        if player not in self._avail:
            self._avail[player] = self._available(player)
        return self._avail[player]

    def absences(self, player: int) -> list[world.Absence]:
        if player not in self._absences:
            a = self.available(player)
            runs: list[world.Absence] = []
            start = None
            for i, ok in enumerate(a):
                if not ok and start is None:
                    start = i
                if ok and start is not None:
                    runs.append(world.Absence(start, i - 1))
                    start = None
            if start is not None:
                runs.append(world.Absence(start, len(a) - 1))
            self._absences[player] = runs
        return self._absences[player]

    def line(self, player: int, day: date) -> Mapping[str, float] | None:
        """The player's line on ``day``: None when his team does not play or he sits out."""
        key = (player, day)
        if key not in self._lines:
            i = self._index.get(player, {}).get(day)
            if i is None or not self.available(player)[i]:
                self._lines[key] = None
            else:
                self._lines[key] = self._line(player, i)
        return self._lines[key]

    def beliefs_on(self, day: date, label: str | None = None) -> Mapping[int, Rates]:
        """The beliefs a seat decides on, on ``day``: the run's forecaster's (``label`` None or
        the run's), or another forecaster's the world holds."""
        if label is not None and label != self.label:
            if label not in self.others:
                raise ValueError(f"forecaster {label!r}: the world holds no belief for it")
            return self.others[label].on(day)
        return self.causal.on(day)

    def seat_beliefs(
        self, day: date, label: str | None, rostered: frozenset[int]
    ) -> Mapping[int, Rates]:
        """What a seat holding ``label`` believes on ``day`` with ``rostered`` the players on any
        roster that morning: :meth:`beliefs_on` for a plain label; for a split one
        (:attr:`split`), its rostered side's belief of every rostered player and its own of
        every other (:func:`split_beliefs`)."""
        if label is None or label not in self.split:
            return self.beliefs_on(day, label)
        return split_beliefs(
            self.beliefs_on(day, label), self.beliefs_on(day, self.split[label]), rostered
        )

    def own(self, label: str | None) -> str | None:
        """``label`` as a seat holds it: None when it is the run's forecaster's."""
        return None if label is None or label == self.label else label

    def status_on(self, day: date) -> tuple[dict[int, str | None], dict[int, date]]:
        """What the policy has heard by ``day``: ``O`` with the return date it was told for an
        absence that began ``lag`` days ago or more and has not passed its told return; the
        statuses read on day one stand until their return."""
        if day in self._status:
            return self._status[day]
        status: dict[int, str | None] = {}
        returns: dict[int, date] = {}
        for k, s in self.setup.statuses.items():
            ret = self.setup.returns.get(k)
            if (
                s in wk.OUT_ALL
                or (ret is not None and day < ret)
                or (
                    ret is None and day <= self.setup.start + timedelta(policy.DEFAULT_ABSENCE_DAYS)
                )
            ):
                status[k] = s
                if ret is not None:
                    returns[k] = ret
        for k, days in self.game_days.items():
            if not days:
                continue
            for a in self.absences(k):
                if a.start == 0 and k in self.setup.statuses:
                    continue  # read on day one, above
                began = days[a.start]
                heard = began + timedelta(self.lag)
                if day < heard:
                    continue
                last = days[a.end] if a.end < len(days) else days[-1]
                g = world.rng(self.seed, self.path, k, a.start, world.STREAMS["news"])
                noise = round(float(g.standard_normal() * self.news_sd))
                told = max(heard, last + timedelta(1 + noise))
                if day <= told:
                    status[k] = "O"
                    returns[k] = told
        self._status[day] = (status, returns)
        return status, returns

    def market_rng(self, team: int, day_index: int) -> np.random.Generator:
        return world.rng(self.seed, self.path, team, day_index, world.STREAMS["market"])


def game_days_of(setup: Setup) -> dict[int, list[date]]:
    """Each player's team's game days from the start to the season's end."""
    days = setup.days
    by_team: dict[str, list[date]] = {}
    for d in days:
        for t in setup.schedule.get(d, frozenset()):
            by_team.setdefault(t, []).append(d)
    return {k: list(by_team.get(m.nba_team or "", [])) for k, m in setup.players.items()}


def replay_world(
    setup: Setup,
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    lag: int,
    seed: int,
    path: int,
    weights: Mapping[str, float] | None = None,
    news_sd: float = world.NEWS_SD_DAYS,
    label: str | None = None,
    forecasts: Mapping[str, Mapping[int, Rates]] | None = None,
    split: Mapping[str, str] | None = None,
    weights_of: Mapping[str, Mapping[str, float]] | None = None,
) -> World:
    """A replay's world: the recorded lines are the truth of every game, a game day without a
    line an absence. The seats' belief is causal: the setup's projection updated with the games
    played before each day, at ``weights``, :data:`fit.W_DEFAULT` for a stat without one; a
    player nobody projected on the newcomer's prior once he has played. ``label`` names the
    run's forecaster, whose projection the setup holds; ``forecasts`` are other forecasters'
    projections by label, each believed the same way with its own newcomer's prior (the mean of
    its own projected players left undrafted), for the seats that name them (#172, PR D1), at
    its own weights in ``weights_of`` (by label; ``weights`` for a label it does not name; PR
    D2). ``split`` maps each split label among them to its rostered side's label
    (:class:`World`)."""
    game_days = game_days_of(setup)
    w = {s: float((weights or {}).get(s, W_DEFAULT)) for s in wk.STATS}

    def own(name: str) -> dict[str, float]:
        given = (weights_of or {}).get(name)
        return w if given is None else {s: float(given.get(s, W_DEFAULT)) for s in wk.STATS}

    causal = causal_belief(setup, setup.projection, lines, w)
    others = {
        name: causal_belief(setup, rates, lines, own(name))
        for name, rates in (forecasts or {}).items()
        if name != label
    }

    def available(player: int) -> np.ndarray:
        days = game_days.get(player, [])
        played = lines.get(player, {})
        return np.array([d in played for d in days], dtype=bool)

    def line(player: int, game: int) -> Mapping[str, float] | None:
        day = game_days[player][game]
        return lines.get(player, {}).get(day)

    return World(
        setup,
        seed,
        path,
        game_days,
        available,
        line,
        lag,
        causal,
        news_sd=news_sd,
        label=label,
        others=others,
        split=split,
    )


def rostered_of(state: SimState) -> frozenset[int]:
    """The players on any roster of ``state``, held slots included."""
    return frozenset(k for roster in state.rosters.values() for k, _ in roster)


def split_beliefs(
    system: Mapping[int, Rates], rostered_side: Mapping[int, Rates], rostered: frozenset[int]
) -> dict[int, Rates]:
    """A split seat's table (#172, PR D1): a player in ``rostered`` reads ``rostered_side``'s
    belief of him, whatever it is (none when it has none); every other player ``system``'s.
    In ``system``'s order, then the rostered players only ``rostered_side`` believes."""
    out: dict[int, Rates] = {}
    for k, v in system.items():
        if k not in rostered:
            out[k] = v
        elif k in rostered_side:
            out[k] = rostered_side[k]
    for k, v in rostered_side.items():
        if k in rostered and k not in out:
            out[k] = v
    return out


def causal_belief(
    setup: Setup,
    projection: Mapping[int, Rates],
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    weights: Mapping[str, float],
) -> CausalBelief:
    """The league's players believed from ``projection`` (its players outside the league left
    out), a player it does not project on the newcomer's prior: the mean of its own projected
    players left undrafted."""
    projected = {k: v for k, v in projection.items() if k in setup.players}
    undrafted = [k for k in setup.pool if k in projected]
    return CausalBelief(
        setup.players, projected, lines, weights, newcomer_prior(projected, undrafted)
    )


def first_day(setup: Setup) -> date | None:
    """The first simulated day: the first of the setup's days inside a week."""
    return next((d for d in setup.days if setup.week_of(d) is not None), None)


def unprojected(
    setup: Setup, w: World, held: Mapping[int, str | None]
) -> dict[str, dict[str, int]]:
    """For each belief label a seat holds (``held``, by team; None for the run's forecaster's),
    the drafted players its table has no line for on the first simulated day (a split label's:
    its rostered side's, which every drafted player reads), counted on the rosters of the seats
    that hold it (``seats``) and on every roster (``all``): a seat values such a player at zero
    until he plays (#172, PR D2). Zero for the run's own label, whose projection the draft read.
    It reads the world's beliefs on that day and draws nothing."""
    day = first_day(setup)
    labels = {t: lb if lb is not None else w.label for t, lb in held.items()}
    out: dict[str, dict[str, int]] = {}
    if day is None:
        return out
    rostered = rostered_of(initial(setup))
    for label in dict.fromkeys(labels.values()):
        table = w.seat_beliefs(day, w.own(label), rostered)
        missing = {
            t: sum(1 for k, _ in setup.rosters.get(t, ()) if k not in table) for t in setup.teams
        }
        out[str(label)] = {
            "seats": sum(missing[t] for t, lb in labels.items() if lb == label),
            "all": sum(missing.values()),
        }
    return out


# --------------------------------------------------------------------------- the day loop
@dataclass(frozen=True)
class VariantResult:
    """One variant's season in one path."""

    result: lg.SeasonResult | None
    summaries: Mapping[int, dict[str, Any]]
    solves: int
    shared: int
    executed: int
    gone: int
    bracket_unread: str | None = None
    #: Active players the executor dropped when a cleared held player came back over the spots.
    forced_drops: int = 0
    #: Held-slot moves the executor refused: the slot no longer accepted the player that morning.
    held_refused: int = 0
    #: Each seat's mechanism counts over the season (``counts.METRICS``).
    counts: Mapping[int, Mapping[str, float | None]] = field(default_factory=dict)
    #: The audit's breaches in this variant: any one voids the path.
    breaches: tuple[audit.Breach, ...] = ()


def _record(
    setup: Setup,
    variant: int,
    state: SimState,
    due: Mapping[int, tuple[mv.Move, ...]],
    decided: Mapping[int, policy.Decision],
    beliefs: Mapping[int, Rates],
    status: Mapping[int, str | None],
    returns: Mapping[int, date],
    starters: Mapping[int, Mapping[int, str]],
    held: Mapping[str, Mapping[int, Rates]] | None = None,
    holds: Mapping[int, str] | None = None,
) -> DayRecord:
    on = {t: {k for k, _ in r} for t, r in state.rosters.items()}
    return DayRecord(
        state.day,
        variant,
        beliefs,
        status,
        returns,
        {t: tuple(m for m in moves if m.add in on.get(t, ())) for t, moves in due.items() if moves},
        dict(decided),
        {t: moves for t, moves in state.pending.items() if moves},
        dict(starters),
        state,
        dict(held or {}),
        dict(holds or {}),
        {
            t: placed
            for t, cs in state.claims.items()
            if (placed := tuple(c for c in cs if c.placed == state.day))
        },
        state.resolved,
    )


def _rotation(teams: Sequence[int], i: int) -> list[int]:
    n = len(teams)
    return [teams[(j + i) % n] for j in range(n)] if n else []


def _cap(strategy: Any) -> int:
    knobs = getattr(strategy, "knobs", None)
    if knobs is None:
        return 1
    return int(policy.knob(knobs, "daily_cap"))


@dataclass(frozen=True)
class DayRecord:
    """One variant's day as its seats lived it, taken after the day's lineup is set and before
    its lines are scored: what the no-peek check compares and the daily audit reads."""

    day: date
    variant: int
    #: The run's forecaster's beliefs and what the seats have heard (statuses, told return
    #: dates).
    beliefs: Mapping[int, Rates]
    status: Mapping[int, str | None]
    returns: Mapping[int, date]
    #: Yesterday's queued moves whose add is on the team's roster this morning, by team.
    landed: Mapping[int, tuple[mv.Move, ...]]
    #: Each moving seat's decision, and the moves it queued to land tomorrow, by team.
    decisions: Mapping[int, policy.Decision]
    queued: Mapping[int, tuple[mv.Move, ...]]
    #: Each team's starters for the day (player to slot).
    starters: Mapping[int, Mapping[int, str]]
    #: The variant's state, the day's totals not yet added.
    state: SimState
    #: The beliefs of every other forecaster a seat of the variant holds, by label (a split
    #: label's the table its seat read that day, after the landing), and the label each such
    #: team holds (#172, PR D1); both empty when every seat holds the run's.
    held: Mapping[str, Mapping[int, Rates]] = field(default_factory=dict)
    holds: Mapping[int, str] = field(default_factory=dict)
    #: A waiver league's (PR Fa): the claims each team placed today, and this morning's claims
    #: decided, in the order decided; both empty without waivers.
    claims: Mapping[int, tuple[Claim, ...]] = field(default_factory=dict)
    cleared: tuple[Resolved, ...] = ()


def holds_of(w: World, variant: Mapping[int, op.Strategy]) -> dict[int, str]:
    """The teams of ``variant`` whose seat names a forecaster other than the run's, with its
    label (``opponents.Seat.forecaster``; a rival holds the run's)."""
    out: dict[int, str] = {}
    for team, strat in variant.items():
        label = w.own(getattr(strat, "forecaster", None))
        if label is not None:
            out[team] = label
    return out


class _Tables:
    """One day's beliefs and per-game values for the labels the seats hold: a plain label's
    once for the day, a split label's (``World.split``) once for each set of rostered players
    it is read on."""

    def __init__(
        self,
        w: World,
        day: date,
        labels: Sequence[str],
        cats: Sequence[str],
        points: Mapping[str, float] | None,
    ) -> None:
        self.w, self.day, self.cats, self.points = w, day, cats, points
        self.held = {label: w.beliefs_on(day, label) for label in labels}
        self.value = {
            label: wk.per_game_values(b, cats, points)
            for label, b in self.held.items()
            if label not in w.split
        }
        self._mixed: dict[tuple[str, frozenset[int]], tuple[dict[int, Rates], Any]] = {}

    def of(self, label: str, state: SimState) -> tuple[Mapping[int, Rates], Mapping[int, float]]:
        """The beliefs and values a seat holding ``label`` reads on ``state``'s rosters."""
        if label not in self.w.split:
            return self.held[label], self.value[label]
        key = (label, rostered_of(state))
        if key not in self._mixed:
            first = self.w.beliefs_on(self.day, self.w.split[label])
            table = split_beliefs(self.held[label], first, key[1])
            self._mixed[key] = (table, wk.per_game_values(table, self.cats, self.points))
        return self._mixed[key]


def simulate(
    setup: Setup,
    w: World,
    variants: Sequence[Mapping[int, op.Strategy]],
    execute_plan: Sequence[bool] | None = None,
    on_day: Callable[[DayRecord], None] | None = None,
    rules: Sequence[audit.Rule] | None = None,
) -> list[VariantResult]:
    """Every variant (a strategy by seat) through one world in lockstep. Each day, after the lineup
    is set and before the day's lines are read, the audit (``sim.audit``: ``rules``, or the setup's,
    ``audit.rules_of``) reads every variant's day and its counts are tallied; ``on_day`` is handed a
    :class:`DayRecord` for each variant and day at the same point. A seat that names a forecaster
    (``opponents.Seat.forecaster``) decides, sets its lineup and is charged its forced drops on that
    forecaster's beliefs and values; every other seat on the run's. A split seat (``World.split``)
    reads its table on the rosters before the landing for the forced drops, and on the rosters after
    it for the rest of the day. The world's draws are common to all of them."""
    n = len(variants)
    states = [initial(setup) for _ in range(n)]
    solves = [0] * n
    shared = [0] * n
    plans = list(execute_plan or [False] * n)
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    spots, slot_counts = setup.spots(), Counter(setup.roster_slots)
    auditor = audit.Auditor(setup, rules, w.path)
    tallies = [ct.Tally(setup) for _ in range(n)]
    holds = [holds_of(w, v) for v in variants]
    labels = sorted({label for h in holds for label in h.values()})
    made: Week | None = None  # the week of the last simulated day, when yesterday's moves were made
    waiting = setup.waiting

    for di, day in enumerate(setup.days):
        week = setup.week_of(day)
        if week is None:
            continue
        monday = day.weekday() == 0 and day != setup.start
        beliefs = w.beliefs_on(day)
        status, returns = w.status_on(day)
        value = wk.per_game_values(beliefs, setup.cats, points)
        tables = _Tables(w, day, labels, setup.cats, points)
        # A split seat's forced drops are weighed on the rosters before anything lands.
        values = [
            {t: tables.of(label, s)[1] for t, label in h.items()}
            for h, s in zip(holds, states, strict=True)
        ]
        # Yesterday's moves land first, cleared held players back and the held-slot moves made
        # before them: on a Monday they were made on Sunday and spend the ending week's adds, so
        # the week's count starts over only once they are in. In a waiver league the claims on
        # the players clearing today are decided once the cleared held players are back, the
        # rosters trimmed and the churns' held players gone (``policy.arrive``, Fc's review), and
        # before the rest lands (PR Fa), each won one charged to the same week as yesterday's
        # moves: the week of the day before.
        order = _rotation(setup.teams, di)
        due = [s.pending for s in states]
        before = [s.executed_by for s in states]
        # Who leaves a roster this morning waits from today (a waiver league's only).
        waiver = {"waiver": (day, setup.waiver_days)} if waiting else {}
        if waiting:
            states = [
                policy.clear_waivers(
                    policy.arrive(s, order, spots, status, value, values[vi], **waiver),
                    day,
                    spots,
                    slot_counts,
                    status,
                    setup.waiver_days,
                    setup.bidding,
                )
                for vi, s in enumerate(states)
            ]
        arrived = {"arrived": True} if waiting else {}
        states = [
            policy.land(
                s, order, spots, slot_counts, status, value, values[vi], **waiver, **arrived
            )
            for vi, s in enumerate(states)
        ]
        for vi, s in enumerate(states):
            tallies[vi].charge((made or week).number, before[vi], s.executed_by)
        if monday:
            states = [policy.new_week(s) for s in states]
        # From here on, the day's rosters: yesterday's moves are in, today's land tomorrow.
        seats = [
            {t: tables.of(label, s) for t, label in h.items()}
            for h, s in zip(holds, states, strict=True)
        ]
        values = [{t: tv[1] for t, tv in seat.items()} for seat in seats]
        cache: dict[tuple[Any, ...], policy.Decision] = {}
        lineups: list[dict[int, dict[int, str]]] = []
        for vi, state in enumerate(states):
            state = replace(state, day=day)
            decided: dict[int, policy.Decision] = {}
            for team in setup.teams:
                strat = variants[vi].get(team)
                if strat is None or strat.kind == "static":
                    continue
                key = (team, repr(strat), state.key())
                if key in cache:
                    decision = cache[key]
                    shared[vi] += decision.solves
                else:
                    g = w.market_rng(team, di)
                    mine = seats[vi][team][0] if team in seats[vi] else beliefs
                    decision = strat.decide(setup, state, team, mine, status, returns, g)
                    cache[key] = decision
                    solves[vi] += decision.solves
                decided[team] = decision
                state = policy.queue(
                    state,
                    team,
                    decision,
                    _cap(strat),
                    setup.max_weekly_adds,
                    plans[vi],
                    spots,
                    setup,
                )
            states[vi] = state
            lineup = {
                t: policy.starters_of(setup, state, t, day, status, values[vi].get(t, value))
                for t in setup.teams
            }
            lineups.append(lineup)
            auditor.check(audit.Day(day, vi, state, status, lineup))
            tallies[vi].day(week.number, state)
            if on_day is not None:
                on_day(
                    _record(
                        setup,
                        vi,
                        state,
                        due[vi],
                        decided,
                        beliefs,
                        status,
                        returns,
                        lineup,
                        {
                            label: seats[vi][t][0]
                            for label, t in sorted({lb: t for t, lb in holds[vi].items()}.items())
                        },
                        holds[vi],
                    )
                )
        states = [
            policy.score_day(setup, s, day, status, value, w.line, lineups[vi], values[vi])
            for vi, s in enumerate(states)
        ]
        for vi in range(n):
            tallies[vi].played(lineups[vi], day, w.line)
        made = week
    out = []
    for vi, state in enumerate(states):
        result = None
        summaries: dict[int, dict[str, Any]] = {}
        if setup.spec is not None:
            totals = {
                wk_: {t: dict(x) for t, x in teams.items()} for wk_, teams in state.totals.items()
            }
            for wk_ in setup.spec.regular_weeks:
                totals.setdefault(wk_, {})
            result = lg.season(setup.spec, totals)
            summaries = {t: lg.summary(result, t) for t in setup.teams}
        out.append(
            VariantResult(
                result,
                summaries,
                solves[vi],
                shared[vi],
                state.executed,
                state.gone,
                setup.bracket_unread,
                forced_drops=state.forced_drops,
                held_refused=state.held_refused,
                counts=tallies[vi].rows(state),
                breaches=tuple(b for b in auditor.breaches if b.variant == vi),
            )
        )
    return out


# --------------------------------------------------------------------------- paired and room
def _metrics(summary: Mapping[str, Any] | None) -> dict[str, float | None]:
    if not summary:
        return dict.fromkeys(METRICS)
    return {
        "made_playoffs": float(summary["made_playoffs"]),
        "rank": float(summary["rank"]),
        "category_wins": float(summary["category_wins"]),
        "matchup_wins": float(summary["matchup_wins"]),
        "title": float(summary["title"]),
    }


def opponents_of(setup: Setup, arm: Arm, me: int) -> dict[int, op.Strategy]:
    other = op.of(arm.opponents, arm.knobs, setup.market_rate, arm.fields)
    return {t: other for t in setup.teams if t != me}


def scale_on(setup: Setup, w: World, arm: Arm, team: int) -> dict[str, Any] | None:
    """The season scale (``policy.scale_of``) for ``arm`` in seat ``team`` on the path's first
    simulated day, on the state, beliefs (the arm's forecaster's) and statuses the seat decides
    on there (yesterday's nothing landed, cleared held players back). None on the ranking tier
    and a static seat. It reads the world's cached figures, draws nothing from a generator and
    decides nothing, so no outcome and no solve count changes with it."""
    if arm.tier not in ("exact", "surrogate"):
        return None
    di, day = next(
        ((i, d) for i, d in enumerate(setup.days) if setup.week_of(d) is not None), (0, None)
    )
    if day is None:
        return None
    status, returns = w.status_on(day)
    first = initial(setup)
    # A split seat's table follows the rosters: before the landing for it, after for the scale.
    beliefs = w.seat_beliefs(day, w.own(arm.forecaster), rostered_of(first))
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    value = wk.per_game_values(beliefs, setup.cats, points)
    # Every other seat lands on the run's forecaster's values, as in the season.
    rivals = (
        value
        if w.own(arm.forecaster) is None
        else wk.per_game_values(w.beliefs_on(day), setup.cats, points)
    )
    state = policy.land(
        first,
        _rotation(setup.teams, di),
        setup.spots(),
        Counter(setup.roster_slots),
        status,
        rivals,
        {team: value},
    )
    if w.own(arm.forecaster) in w.split:
        beliefs = w.seat_beliefs(day, w.own(arm.forecaster), rostered_of(state))
    built = policy.problem_of(
        setup,
        replace(state, day=day),
        team,
        arm.knobs,
        beliefs,
        status,
        returns,
        arm.fields.weeks_ahead,
    )
    if built is None:
        return None
    s = policy.scale_of(built, arm.tier, arm.executes, arm.fields)
    if s is None:
        return None
    return {"gain": s.gain, "ros": s.ros, "ratio": s.ratio, "against": s.against, "swaps": s.swaps}


def paired(
    setup: Setup,
    w: World,
    a: Arm,
    b: Arm,
    me: int,
    on_day: Callable[[DayRecord], None] | None = None,
) -> dict[str, Any]:
    """Arm A and arm B in seat ``me`` through one world: each outcome and their difference, B less
    A (``b[k] - a[k]``, None where either is None). Positive is B ahead on every metric but
    ``rank``, where lower is better and a negative difference is B finishing higher. ``on_day`` is
    :func:`simulate`'s: A's season is variant 0, B's variant 1."""
    va = {**opponents_of(setup, a, me), me: a.seat()}
    vb = {**opponents_of(setup, b, me), me: b.seat()}
    scale = {"a": scale_on(setup, w, a, me), "b": scale_on(setup, w, b, me)}
    ra, rb = simulate(setup, w, [va, vb], [a.execute_plan, b.execute_plan], on_day=on_day)
    return _pair_result(setup, ra, rb, me, scale)


def paired_apart(
    setup_a: Setup,
    w_a: World,
    setup_b: Setup,
    w_b: World,
    a: Arm,
    b: Arm,
    me: int,
    on_day: Callable[[DayRecord], None] | None = None,
) -> dict[str, Any]:
    """Arm A and arm B in seat ``me``, each in a league of its own drafted apart (#172, PR D4a):
    A's season on ``setup_a`` through ``w_a``, B's on ``setup_b`` through ``w_b``, the two worlds
    on one ``(seed, path)`` so their draws stay common. The keys :func:`paired` returns, with
    nothing shared between the two (``shared`` is B's own). ``on_day`` gets A's days as variant 0
    and B's as variant 1."""
    va = {**opponents_of(setup_a, a, me), me: a.seat()}
    vb = {**opponents_of(setup_b, b, me), me: b.seat()}
    scale = {"a": scale_on(setup_a, w_a, a, me), "b": scale_on(setup_b, w_b, b, me)}
    (ra,) = simulate(setup_a, w_a, [va], [a.execute_plan], on_day=on_day)
    second = None if on_day is None else (lambda r: on_day(replace(r, variant=1)))
    (rb,) = simulate(setup_b, w_b, [vb], [b.execute_plan], on_day=second)
    rb = replace(rb, breaches=tuple(replace(x, variant=1) for x in rb.breaches))
    return _pair_result(setup_a, ra, rb, me, scale)


def _pair_result(
    setup: Setup, ra: VariantResult, rb: VariantResult, me: int, scale: dict[str, Any]
) -> dict[str, Any]:
    """A pair's task result from its two seasons (:func:`paired`, :func:`paired_apart`)."""
    ma, mb = _metrics(ra.summaries.get(me)), _metrics(rb.summaries.get(me))
    rivals = [t for t in setup.teams if t != me]
    return {
        "a": ma,
        "b": mb,
        "delta": {k: None if ma[k] is None or mb[k] is None else mb[k] - ma[k] for k in METRICS},
        "solves": ra.solves + rb.solves,
        "solves_by_arm": [ra.solves, rb.solves],
        "shared": rb.shared,
        "executed": [ra.executed, rb.executed],
        "gone": [ra.gone, rb.gone],
        "forced_drops": [ra.forced_drops, rb.forced_drops],
        "bracket_unread": setup.bracket_unread,
        "counts": {
            "a": ct.row_of(ra.counts, [me]),
            "b": ct.row_of(rb.counts, [me]),
            # The rival seats of both arms' seasons as one row.
            "rivals": ct.row_of(
                {(v, t): c for v, r in enumerate((ra, rb)) for t, c in r.counts.items()},
                [(v, t) for v in (0, 1) for t in rivals],
            ),
        },
        "breaches": [b.payload() for b in (*ra.breaches, *rb.breaches)],
        "scale": scale,
    }


def rotate(arms: Sequence[str], teams: Sequence[int], turn: int) -> dict[int, str]:
    """Seat ``i`` gets arm ``(i + turn) mod n``: across paths every arm sits in every seat (the
    path's turn, ``shapes.visit``; the path itself on one league shape)."""
    n = len(arms)
    return {t: arms[(i + turn) % n] for i, t in enumerate(teams)}


def room(
    setup: Setup,
    w: World,
    arms: Mapping[str, Arm],
    seats: Sequence[str],
    turn: int,
    on_day: Callable[[DayRecord], None] | None = None,
) -> dict[str, Any]:
    """The league's seats under named arms, rotated by ``turn`` (the path's turn,
    ``shapes.visit``; the path itself on one league shape); each arm's outcomes pooled over its
    seats this path. ``on_day`` is :func:`simulate`'s."""
    assigned = rotate(list(seats), setup.teams, turn)
    variant = {t: arms[name].seat() for t, name in assigned.items()}
    # The scale is each arm's in its first seat, in team order.
    first = {
        name: min(t for t, n in assigned.items() if n == name) for name in set(assigned.values())
    }
    scale = {name: scale_on(setup, w, arms[name], t) for name, t in sorted(first.items())}
    (r,) = simulate(setup, w, [variant], [any(arms[n].execute_plan for n in seats)], on_day=on_day)
    by_arm: dict[str, list[dict[str, float | None]]] = {}
    seats_of: dict[str, list[int]] = {}
    for t, name in assigned.items():
        by_arm.setdefault(name, []).append(_metrics(r.summaries.get(t)))
        seats_of.setdefault(name, []).append(t)
    return {
        "seats": {str(t): name for t, name in assigned.items()},
        "by_arm": {
            name: {k: _mean([m[k] for m in rows]) for k in METRICS} for name, rows in by_arm.items()
        },
        "solves": r.solves,
        "shared": r.shared,
        "executed": r.executed,
        "gone": r.gone,
        "forced_drops": r.forced_drops,
        "bracket_unread": setup.bracket_unread,
        # Every seat is an arm's: a room has no rival seats.
        "counts": {name: ct.row_of(r.counts, ts) for name, ts in seats_of.items()},
        "breaches": [b.payload() for b in r.breaches],
        "scale": scale,
    }


def _mean(xs: Sequence[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def aggregate(
    rows: Sequence[Mapping[str, float | None]],
    metrics: Sequence[str] = METRICS,
) -> dict[str, dict[str, float | int | None]]:
    """Each metric's mean, standard error and count over ``rows`` (one a path): the outcomes'
    :data:`METRICS`, or the mechanism counts' (``counts.METRICS``)."""
    out: dict[str, dict[str, float | int | None]] = {}
    for k in metrics:
        vals = [float(r[k]) for r in rows if r.get(k) is not None]
        n = len(vals)
        if n == 0:
            out[k] = {"mean": None, "se": None, "n": 0}
            continue
        mean = sum(vals) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
        out[k] = {"mean": mean, "se": sd / math.sqrt(n) if n > 1 else None, "n": n}
    return out


# --------------------------------------------------------------------------- a replay's verdict
#: The replay's advisory rule on the paired design (#172, PR D2; ruled 2026-11-07: there is no
#: grand figure across forecasters).
REPLAY_VERDICT_RULE = "one-SE in every cell, pooled above zero"
REPLAY_VERDICT_LINE = (
    "advisory: holds when the paired change in playoff odds (B less A) is not below zero by more "
    "than one SE in every cell the rule reads, and every forecaster's pooled change (the mean of "
    "its season means) is above zero; no grand figure across forecasters, no block and no "
    "promotion: the simulator never writes a live knob file"
)
#: The marks a replay's verdict table carries: a row the rule does not rest on, and a cell left
#: out of its forecaster's pooled figure and of the rule.
YARDSTICK = "yardstick"
FREEZE = "freeze"
SKIPPED = "skipped"
MARKS = {
    YARDSTICK: "an oracle is a labelled look-ahead, a yardstick: shown, not read by the rule",
    FREEZE: (
        "espn's stored projection of this season fails the freeze check: shown, left out of "
        "espn's pooled figure and of the rule"
    ),
    SKIPPED: "n/a: the forecaster cannot serve this season",
}


def pool_seasons(means: Sequence[float], of: int) -> dict[str, Any]:
    """One forecaster's pooled change over its seasons: the mean of the season means, with the SE
    taken from those means (the seasons are the clusters); with one season, that season's mean
    and no SE, and it says so. ``of``: the seasons the run names, so the figure says "over k of
    n" when a cell was skipped or left out."""
    k = len(means)
    if k == 0:
        return {"mean": None, "se": None, "seasons": 0, "of": of, "note": "no season"}
    mean = sum(means) / k
    se = math.sqrt(sum((x - mean) ** 2 for x in means) / (k - 1)) / math.sqrt(k) if k > 1 else None
    note = f"over {k} of {of} seasons" if k < of else f"over {k} seasons"
    if k == 1:
        note += ": that season's mean, no SE (it needs two seasons)"
    return {"mean": mean, "se": se, "seasons": k, "of": of, "note": note}


def replay_verdict(
    cells: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float | int | None]] | None]],
    seasons: Sequence[str],
    yardsticks: Sequence[str] = (),
    frozen: Mapping[str, Sequence[str]] | None = None,
    voided: int = 0,
    metrics: Sequence[str] = METRICS,
) -> dict[str, Any]:
    """The verdict of a replay's paired design, by forecaster and season (#172, PR D2): pure, on
    the figures alone. ``cells`` maps each forecaster's label to each season's paired change
    (:func:`aggregate` of the paths' ``delta``, B less A; None for a skipped cell);
    ``yardsticks`` are the labels the rule does not rest on (an oracle's); ``frozen`` maps a
    label to the seasons left out of its pooled figure and of the rule (an ``espn`` season that
    fails the freeze check). Each row carries its cells' playoff change with their marks and its
    pooled change in every metric (:func:`pool_seasons`). The rule (:data:`REPLAY_VERDICT_LINE`)
    holds when no cell it reads has its change in playoff odds below zero by more than one SE
    and every forecaster it reads has a pooled change above zero; ``passes`` is None, with the
    reason, when the audit voided a path, a cell the rule reads has no SE, or no forecaster is
    left for the rule to rest on."""
    frozen = frozen or {}
    rows: dict[str, Any] = {}
    read_cells: list[tuple[str, str, Mapping[str, float | int | None]]] = []
    read_rows: list[str] = []
    for label, by_season in cells.items():
        yardstick = label in yardsticks
        row_cells: dict[str, Any] = {}
        kept: dict[str, Mapping[str, Mapping[str, float | int | None]]] = {}
        for t in seasons:
            agg = by_season.get(t)
            if agg is None:
                row_cells[t] = {"mean": None, "se": None, "n": 0, "mark": SKIPPED}
                continue
            m = agg.get("made_playoffs") or {}
            mark = FREEZE if t in frozen.get(label, ()) else None
            row_cells[t] = {"mean": m.get("mean"), "se": m.get("se"), "n": m.get("n"), "mark": mark}
            if mark is None:
                kept[t] = agg
                if not yardstick:
                    read_cells.append((label, t, m))
        pooled = {
            k: pool_seasons(
                [
                    float(mean)
                    for agg in kept.values()
                    if (mean := (agg.get(k) or {}).get("mean")) is not None
                ],
                len(seasons),
            )
            for k in metrics
        }
        rows[label] = {
            "mark": YARDSTICK if yardstick else None,
            "cells": row_cells,
            "pooled": pooled,
        }
        if not yardstick and kept:
            read_rows.append(label)
    passes: bool | None
    why: str | None = None
    failed: list[str] = []
    no_se = [
        f"{t} {label}" for label, t, m in read_cells if m.get("se") is None or m.get("mean") is None
    ]
    if voided:
        passes, why = None, f"no verdict: the audit voided {voided} path(s)"
    elif not read_rows:
        passes, why = (
            None,
            (
                "no verdict: no forecaster the rule may rest on (an oracle is a yardstick, and a "
                "season that fails the freeze check is left out)"
            ),
        )
    elif no_se:
        passes, why = None, f"no verdict: no SE in the cell(s) {', '.join(no_se)} (one path?)"
    else:
        for label, t, m in read_cells:
            mean, se = float(m["mean"] or 0.0), float(m["se"] or 0.0)
            if mean < -se:
                failed.append(
                    f"{t} {label}: {mean:+.4f} is below zero by more than its SE {se:.4f}"
                )
        for label in read_rows:
            p = rows[label]["pooled"]["made_playoffs"]
            if p["mean"] is None or p["mean"] <= 0:
                shown = "no mean" if p["mean"] is None else f"{p['mean']:+.4f}"
                failed.append(f"{label} pooled: {shown} is not above zero")
        passes = not failed
    return {
        "rule": REPLAY_VERDICT_RULE,
        "line": REPLAY_VERDICT_LINE,
        "seasons": list(seasons),
        "rows": rows,
        "marks": dict(MARKS),
        "read": read_rows,
        "passes": passes,
        "why": why,
        "failed": failed,
    }


# --------------------------------------------------------------------------- the pool
def workers_default() -> int:
    return max(1, (os.cpu_count() or 2) - SPARE_CORES)


def _lower_priority() -> None:
    try:
        os.nice(NICE)
    except OSError:
        pass


def run_tasks(
    fn: Callable[..., Any], tasks: Sequence[tuple[Any, ...]], workers: int | None = None
) -> list[Any]:
    """``fn`` over ``tasks`` in a process pool of the simulator's own (never the engine's), each
    worker at low priority, the results in the tasks' order; one worker runs them in this process
    (tests, smoke runs).

    The workers start by ``spawn`` on every machine. Python's default is ``fork`` on Linux, and a
    forked worker inherits the solver's state from a parent that has already solved (the
    commands run their first task in the parent): a HiGHS solve in it can spin for ever. A
    spawned worker is a fresh process, as it is by default on macOS, so the two machines run
    alike."""
    n = workers or workers_default()
    if n <= 1 or len(tasks) <= 1:
        return [fn(*t) for t in tasks]
    with ProcessPoolExecutor(
        max_workers=n, initializer=_lower_priority, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        return list(pool.map(fn, *zip(*tasks, strict=True)))


# --------------------------------------------------------------------------- a replay's league
#: ESPN's eligible slot ids that are a position (the combinations, UTIL, bench and IR are not).
ESPN_POSITIONS: Mapping[int, str] = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F"}
#: The fixed league shape's parts (``shapes.FIXED``, #172, PR D4b), by their old names: the
#: roster a replay's seats fill (the private league's shape without held slots), its playoffs,
#: its team count and its weekly add limit. A path's league is its shape's (``shapes.visit``).
REPLAY_SLOTS = shapes.FIXED.slots
REPLAY_WEEKS = 22
REPLAY_PLAYOFF_WEEKS = shapes.FIXED.playoff_weeks
REPLAY_PLAYOFF_TEAMS = shapes.FIXED.playoff_teams
REPLAY_TEAMS = shapes.FIXED.teams
REPLAY_WEEKLY_ADDS = shapes.FIXED.weekly_adds
#: A forecaster built from lines projects a player with at least this many played games in the
#: season it reads: the prior season for ``prior``, the replayed one for the oracle
#: (``forecast.MIN_GAMES``).
STANDIN_MIN_GAMES = MIN_GAMES
#: A replay's draft takes the projected players with a scheduled game in the season's first this
#: many days: an opening-night roster is known before a draft.
OPENING_DAYS = 7


def replay_setup(
    season: int,
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    players: Mapping[int, Member],
    projection: Mapping[int, Rates],
    period_one: date,
    scheduled: Mapping[int, Sequence[date]] | None = None,
    teams: int = REPLAY_TEAMS,
    slots: Sequence[str] = REPLAY_SLOTS,
    weeks: int = REPLAY_WEEKS,
    playoff_weeks: int = REPLAY_PLAYOFF_WEEKS,
    playoff_teams: int = REPLAY_PLAYOFF_TEAMS,
    cats: Sequence[str] = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"),
    opening_days: int | None = OPENING_DAYS,
    draft: adp.Draft | None = None,
    weekly_adds: int | None = REPLAY_WEEKLY_ADDS,
    scoring: str = "categories",
    points: Mapping[str, float] | None = None,
    waivers: str = "none",
    waiver_days: int = shapes.WAIVER_DAYS,
    budget: int = shapes.BUDGET,
    rival_scale: float = shapes.RIVAL_SCALE,
    h2h: str = ONE_WIN,
    waiver_rule: str = shapes.DROPPED,
) -> Setup:
    """A made-up league on a recorded season, from what is known before it starts. Its players
    are everyone ``players`` lists with a scheduled game, projected or not; ``teams`` seats
    snake-draft the projected ones with a scheduled game in the season's first ``opening_days``
    days (from ``period_one``; None drafts every projected player) on ``projection``, the run's
    forecaster's, and everyone else is on the wire. A round robin over the regular weeks, the
    bracket reseeded with the higher seed through a tie. Every player is his own team in the
    schedule (``p<id>``): his game days are his ``scheduled`` entries (played or not; the days
    he has a line for when none are given), so a trade or a team read later than the season
    moves nothing. Every day of the calendar is a key of the schedule, an empty set when nobody
    plays: no day is unread, so the engine extrapolates no game (#172, PR C2).

    ``draft`` (#172, PR D4a): the league is drafted on a table of average draft positions
    instead (:func:`draft_boards`, ``state.board_draft``): every member with a game in the
    opening days who is projected or listed can be drafted, each seat takes the best player
    left on its own board, and the market's view is the table's (``adp.market_view``). None is
    the draft on ``projection`` alone, as before.

    A league shape (#172, PR D4b) is passed as its keywords (``shapes.LeagueShape.setup_args``):
    ``teams``, ``slots``, ``weekly_adds`` (None: no limit), ``playoff_teams`` and
    ``playoff_weeks``; the defaults are the fixed shape's. The season stays ``weeks`` long and the
    regular season is what the playoffs leave.

    The league rules (#172, PR D4c, ``shapes.LeagueRules``): ``scoring`` ``"points"`` scores on
    ``points`` (a stat's points per unit): the draft values by them, each seat's own board under
    a table too, the setup's categories are fantasy points alone and the standings break a tie
    on points for (``league.TIEBREAK_POINTS``); the default is the nine categories. The held
    slots arrive in ``slots`` after the bench: the draft takes the active spots only, so a held
    slot starts the season empty. The waivers (PR Fa, ``shapes.WAIVERS``): ``waivers`` and a
    dropped player's ``waiver_days``; the first priority order is the reverse of the draft's
    (``state.initial``). A FAAB league's (PR Fb): every team's ``budget`` and the
    ``rival_scale`` a market rival's bid is multiplied by. A categories league's head-to-head
    format (the format PR, ``shapes.H2H``): ``h2h`` ``each_category`` orders the standings by
    the category percentage, then head to head (``league.TIEBREAK_EACH``); the default counts
    one win per matchup, as before. A points league names none. A waiver league's
    ``waiver_rule`` (PR Fc, ``shapes.WAIVER_RULES``): ``continuous``, every add a claim, the
    draft's leftovers claimable from the first morning; the default, a claim only on a dropped
    player in his wait."""
    if (scoring == "points") != bool(points):
        raise ValueError(f"scoring {scoring!r} with points {points!r}: a points league has a table")
    if h2h not in shapes.H2H or (points and h2h != ONE_WIN):
        raise ValueError(f"head-to-head format {h2h!r} with scoring {scoring!r}")
    if waiver_rule not in shapes.WAIVER_RULES or (
        waivers == "none" and waiver_rule != shapes.DROPPED
    ):
        raise ValueError(f"waiver rule {waiver_rule!r} with waivers {waivers!r}")
    schedule: dict[date, set[str]] = {}
    members: dict[int, Member] = {}
    game_days = league_days(lines, players, scheduled)
    for k, days in game_days.items():
        m = players[k]
        own = f"p{k}"
        members[k] = Member(k, m.name, own, m.positions)
        for d in days:
            schedule.setdefault(d, set()).add(own)
    calendar = weeks_from(period_one, weeks)
    # Every day of the calendar has a key, an empty set when nobody plays, as a fully read live
    # schedule has: the engine counts a day without one as unread and extrapolates games over it
    # (moves.games_ahead), games no log holds.
    first, last = calendar.weeks[0].start, max(w.end for w in calendar.weeks)
    for i in range((last - first).days + 1):
        schedule.setdefault(first + timedelta(i), set())
    regular = tuple(range(1, weeks - playoff_weeks + 1))
    playoffs = tuple(range(weeks - playoff_weeks + 1, weeks + 1))
    ids = tuple(range(1, teams + 1))
    pairings = round_robin(ids, regular)
    projected = [k for k in projection if k in members]
    table = dict(points) if scoring == "points" and points else None
    value = wk.per_game_values({k: projection[k] for k in projected}, tuple(cats), table)
    spots = sum(1 for s in slots if s not in mv.HELD)
    draftable = draftable_of(
        members,
        game_days,
        projection,
        period_one,
        opening_days,
        None if draft is None else draft.picks,
    )
    if draft is None:
        rosters = snake_draft(draftable, value, ids, spots)
        market = {k: value.get(k, 0.0) for k in projected}
    else:
        boards = draft_boards(draft, draftable, value, ids, members, cats, table)
        rosters = board_draft(boards, ids, spots)
        market = adp.market_view(draft.picks, value, list(members))
    taken = {k for r in rosters.values() for k, _ in r}
    # A points league's spec names no category and its setup's one is fantasy points, the
    # category the engine takes its odds on (``moves.MoveProblem.cats``).
    spec = lg.LeagueSpec(
        ids,
        pairings,
        playoffs,
        () if table else tuple(cats),
        "points" if table else "categories",
        table,
        playoff_teams,
        2 ** math.ceil(math.log2(playoff_teams)) - playoff_teams,
        lg.TIEBREAK_POINTS if table else lg.TIEBREAK_EACH if h2h == EACH_CATEGORY else lg.TIEBREAK,
        h2h=h2h,
    )
    return Setup(
        start=calendar.weeks[0].start,
        calendar=calendar,
        pairings=pairings,
        teams=ids,
        players=members,
        rosters=rosters,
        pool=tuple(k for k in members if k not in taken),
        projection={k: dict(projection[k]) for k in projected},
        schedule={d: frozenset(t) for d, t in schedule.items()},
        roster_slots=tuple(slots),
        cats=(FPTS,) if table else tuple(cats),
        max_weekly_adds=weekly_adds,
        market=market,
        spec=spec,
        scoring="points" if table else "categories",
        points=table,
        waivers=waivers,
        waiver_days=waiver_days,
        budget=budget,
        rival_scale=rival_scale,
        h2h=h2h,
        waiver_rule=waiver_rule,
    )


def league_days(
    lines: Mapping[int, Mapping[date, Any]],
    players: Mapping[int, Any],
    scheduled: Mapping[int, Sequence[date]] | None = None,
) -> dict[int, list[date]]:
    """A replay's league's members and their game days (:func:`replay_setup`): everyone
    ``players`` lists with a scheduled game (the days he has a line for when none are given), in
    ``players``' order."""
    out: dict[int, list[date]] = {}
    for k in players:
        days = list((scheduled or {}).get(k) or list(lines.get(k, {})))
        if days:
            out[k] = days
    return out


def draftable_of(
    members: Mapping[int, Any],
    game_days: Mapping[int, Sequence[date]],
    projection: Mapping[int, Any],
    period_one: date,
    opening_days: int | None = OPENING_DAYS,
    picks: Mapping[int, float] | None = None,
) -> list[int]:
    """Who a replay's draft can take (:func:`replay_setup`): the league's members with a game in
    the season's first ``opening_days`` days (from ``period_one``; None: any game) who are
    projected, or, under a table (``picks``), projected or listed: in ``projection``'s order
    without a table and in ``members``' under one, as each draft has always read them."""
    opening = None if opening_days is None else period_one + timedelta(opening_days - 1)

    def opens(k: int) -> bool:
        return opening is None or any(period_one <= d <= opening for d in game_days.get(k, ()))

    if picks is None:
        return [k for k in projection if k in members and opens(k)]
    return [k for k in members if (k in projection or k in picks) and opens(k)]


def draft_boards(
    draft: adp.Draft,
    draftable: Sequence[int],
    value: Mapping[int, float],
    teams: Sequence[int],
    players: Mapping[int, Member],
    cats: Sequence[str],
    points: Mapping[str, float] | None = None,
) -> dict[int, list[int]]:
    """Each seat's board under ``draft`` (#172, PR D4a): a seat ``draft.seats`` names drafts on
    its own forecaster's per-game values on draft day (over the league's ``players`` it
    projects, as the run's ``value`` is over the run's; in a points league on ``points``, PR
    D4c), every other seat on a rival's board
    (``adp.rival_board``) drawn from its own generator on the path's ``(seed, path)`` and the
    ``draft`` stream, so two leagues on one path meet the same rivals' boards."""
    out: dict[int, list[int]] = {}
    for t in teams:
        own = draft.seats.get(t)
        if own is None:
            g = world.rng(draft.seed, draft.path, t, 0, world.STREAMS["draft"])
            out[t] = adp.rival_board(draft.picks, draftable, value, draft.spread, g)
        else:
            mine = wk.per_game_values({k: own[k] for k in own if k in players}, tuple(cats), points)
            out[t] = adp.seat_board(mine, draftable)
    return out


def drafted_unprojected(setup: Setup) -> int:
    """The drafted players the run's forecaster does not project (#172, PR D4a): a rival on a
    table can draft them; under the draft on the projection, none."""
    return sum(1 for r in setup.rosters.values() for k, _ in r if k not in setup.projection)


__all__ = [
    "KNOBS",
    "METRICS",
    "OPENING_DAYS",
    "SPEC_KEYS",
    "STANDIN_MIN_GAMES",
    "Arm",
    "DayRecord",
    "VariantResult",
    "World",
    "WorldInputs",
    "aggregate",
    "arm_of",
    "check_fit",
    "draft_boards",
    "draftable_of",
    "drafted_unprojected",
    "inputs_of",
    "league_days",
    "mirrored",
    "paired",
    "paired_apart",
    "pool_seasons",
    "realized_rates",
    "replay_setup",
    "replay_verdict",
    "replay_world",
    "room",
    "rostered_of",
    "rotate",
    "run_tasks",
    "same_seat",
    "scale_on",
    "simulate",
    "split_beliefs",
    "unprojected",
]
