"""The runner (#172, PR 2b): one world a path, arms in lockstep, the paired difference.

A :class:`World` is one path of one league: the truth (the projection with its persistent error),
each player's game days, availability and lines, the shared beliefs and what the policy has heard
of each absence. Every draw comes from ``world.rng(seed, path, player, game, stream)`` and never
from an arm, so a roster change in one arm reshuffles nothing for any player: common random
numbers. :func:`forward_world` builds it from a setup and the frozen fit's figures, its beliefs
refreshed weekly toward the drawn truth; :func:`replay_world` from a season's recorded lines,
which are then the truth (no game noise, no hazard: the logs happened), its seats believing only
the games already played (``sim.belief``) in a league drawn from what was known before the
season (:func:`replay_setup`).

:func:`simulate` advances several variants of one league through the same world day by day: the
moves decided yesterday land, each seat decides on the day's beliefs, the lineup is set, the day
is played and scored; a hook is handed each day's :class:`DayRecord`. Variants whose
states agree share one solve (the lockstep of the design note); from the first divergence each
solves alone. :func:`paired` runs arm A and arm B for one seat and returns the paired difference
of the season's outcomes, B less A; :func:`room` runs twelve seats under named arms rotated across
paths.
Pure but for the process pool: nothing here reads a file; the readers (``sim.readers``) and the
commands (``sim.cli``) bring the inputs and write the payload.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import numpy as np

from . import audit, policy, world
from . import counts as ct
from . import league as lg
from . import opponents as op
from .belief import CausalBelief, consistent, newcomer_prior
from .engine import KNOBS, Week, mv, wk
from .fit import W_DEFAULT, Component, Hazard
from .state import Member, Setup, SimState, initial, round_robin, snake_draft, weeks_from

Rates = Mapping[str, float]
#: The shrinks a comparison runs at (the design note's axis).
SHRINKS = (0.0, 0.25, 0.5)
#: The metrics a path reports for a seat.
METRICS = ("made_playoffs", "rank", "category_wins", "matchup_wins", "title")
#: The verdict line's rule, advisory until PR 3 (the master's ruling on PR 2's plan).
VERDICT_RULE = "one-SE"
VERDICT_LINE = (
    "advisory: a change (arm B) passes when the paired change in playoff odds, B less A, is not "
    "below zero by more than one standard error at any shrink; no block and no promotion before "
    "PR 3"
)
#: How workers are counted when not given: the machine's cores less two.
SPARE_CORES = 2
NICE = 10


# --------------------------------------------------------------------------- the inputs
@dataclass(frozen=True)
class WorldInputs:
    """The frozen fit's figures the world draws with, and the beliefs' refresh."""

    phi: Mapping[str, float]
    phi_players: Mapping[str, Mapping[str, float]]
    sigma: float
    hazard: Hazard
    tau: Mapping[str, float]
    kappa: float
    sigma_eta: float
    lag: int
    sha: str
    refresh_from: str = "defaults"


def hazard_of(d: Mapping[str, Any]) -> Hazard:
    """The hazard back from the frozen payload's dict."""
    return Hazard(
        float(d["rate"]),
        tuple(
            Component(
                int(c["lo"]),
                None if c.get("hi") is None else int(c["hi"]),
                float(c["weight"]),
                {int(k): float(v) for k, v in (c.get("lengths") or {}).items()},
            )
            for c in d.get("components") or []
        ),
        int(d.get("runs", 0)),
        int(d.get("played", 0)),
        int(d.get("players", 0)),
        int(d.get("censored", 0)),
        float(d.get("censored_share", 0.0)),
        int(d.get("leading", 0)),
    )


def inputs_of(payload: Mapping[str, Any], sha: str, tau: Mapping[str, float] | None) -> WorldInputs:
    """The world's inputs from a frozen fit; ``tau`` from the payload when it has one (the
    residual fit of week six), else the one given (the systems' spread); none at all is refused:
    at ``tau = 0`` the simulator restates the engine's beliefs."""
    t = payload.get("tau") or tau
    if not t:
        raise ValueError("no tau: the fit has no residual tau and none was given")
    refresh = payload.get("refresh") or {}
    defaults = (payload.get("parameters") or {}).get("refresh_defaults") or {}
    fitted = bool(refresh.get("fitted"))
    return WorldInputs(
        phi={k: float(v) for k, v in (payload["dispersion"]["pooled"] or {}).items()},
        phi_players={
            str(p): {k: float(v) for k, v in d.items()}
            for p, d in (payload["dispersion"].get("players") or {}).items()
        },
        sigma=float(payload["minutes"]["sigma"]),
        hazard=hazard_of(payload["hazard"]),
        tau={k: float(v) for k, v in t.items()},
        kappa=float(refresh["kappa"] if fitted else defaults.get("kappa", 0.10)),
        sigma_eta=float(refresh["sigma_eta"] if fitted else defaults.get("sigma_eta", 0.05)),
        lag=int(refresh.get("lag", defaults.get("lag", 1))),
        sha=sha,
        refresh_from="fitted" if fitted else "defaults",
    )


# --------------------------------------------------------------------------- the arms
@dataclass(frozen=True)
class Arm:
    """One arm of a comparison: a tier with its knobs, what it executes and its opponents."""

    name: str
    tier: str
    knobs: Mapping[str, Any]
    opponents: Mapping[str, Any]
    executes: str = policy.QUEUE_SET
    with_plan: bool = True
    execute_plan: bool = False

    def seat(self) -> op.Seat:
        return op.Seat(self.name, self.tier, dict(self.knobs), self.executes, self.with_plan)


def arm_of(spec: Mapping[str, Any]) -> Arm:
    """An arm from its spec file's JSON: ``name``, ``tier``, every knob, ``opponents``; a knob
    missing or a tier unknown is refused."""
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
        dict(spec.get("opponents") or {"kind": "static"}),
        executes,
        bool(spec.get("with_plan", True)),
        bool(spec.get("execute_plan", False)),
    )


def check_fit(spec: Mapping[str, Any], sha: str) -> None:
    """A spec names the frozen fit it was written for; another fit on disk refuses the run."""
    named = spec.get("fit_sha")
    if named and named != sha:
        raise ValueError(
            f"spec {spec.get('name')!r} names fit {named[:12]}, the fit on disk is {sha[:12]}"
        )


# --------------------------------------------------------------------------- the world
#: How a world's seats believe: the drawn world's weekly refresh toward its truth, a replay's
#: causal belief from the games already played (``sim.belief``), or the projection all season.
BELIEFS = ("refresh", "causal", "fixed")


class World:
    """One path of one league: truth, lines, availability, beliefs and news.

    ``belief`` is one of :data:`BELIEFS`: ``refresh`` moves the projection toward ``truth`` each
    week at ``kappa`` with noise ``sigma_eta``; ``causal`` reads ``causal`` (a
    :class:`belief.CausalBelief`) on each day; ``fixed`` is the projection all season. The told
    return date's spread is ``news_sd`` days."""

    def __init__(
        self,
        setup: Setup,
        seed: int,
        path: int,
        truth: Mapping[int, Rates],
        game_days: Mapping[int, Sequence[date]],
        available: Callable[[int], np.ndarray],
        line: Callable[[int, int], Mapping[str, float] | None],
        lag: int,
        kind: str,
        belief: str = "refresh",
        kappa: float = 0.0,
        sigma_eta: float = 0.0,
        causal: CausalBelief | None = None,
        news_sd: float = world.NEWS_SD_DAYS,
    ) -> None:
        if belief not in BELIEFS:
            raise ValueError(f"belief {belief!r}: one of {BELIEFS}")
        if belief == "causal" and causal is None:
            raise ValueError("a causal belief needs its CausalBelief")
        self.setup = setup
        self.seed, self.path = seed, path
        self.truth = truth
        self.game_days = {k: list(v) for k, v in game_days.items()}
        self._index = {k: {d: i for i, d in enumerate(v)} for k, v in self.game_days.items()}
        self._available = available
        self._line = line
        self.kappa, self.sigma_eta, self.lag = kappa, sigma_eta, lag
        self.kind = kind
        self.belief = belief
        self.causal = causal
        self.news_sd = float(news_sd)
        self._avail: dict[int, np.ndarray] = {}
        self._absences: dict[int, list[world.Absence]] = {}
        self._lines: dict[tuple[int, date], Mapping[str, float] | None] = {}
        self._beliefs: dict[int, Mapping[int, Rates]] = {0: dict(setup.projection)}
        self._status: dict[date, tuple[dict[int, str | None], dict[int, date]]] = {}
        self._weeks: dict[date, int] | None = None

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

    def beliefs(self, week: int) -> Mapping[int, Rates]:
        """The shared beliefs after ``week`` weekly refreshes (0: the projection); the projection
        itself for a ``fixed`` world. A ``causal`` belief is read by day (:meth:`beliefs_on`)."""
        if self.belief == "causal":
            raise ValueError("a causal belief is read by day: beliefs_on")
        if self.belief == "fixed":
            return self._beliefs[0]
        if week not in self._beliefs:
            prev = self.beliefs(week - 1)
            self._beliefs[week] = world.refresh(
                prev, self.truth, self.kappa, self.sigma_eta, self.seed, self.path, week
            )
        return self._beliefs[week]

    def week_index(self, day: date) -> int:
        """The weekly refreshes behind ``day``: one for every Monday after the first simulated
        day, counted over the days a week holds, as the day loop counts them."""
        if self._weeks is None:
            index, out = 0, {}
            for d in self.setup.days:
                if self.setup.week_of(d) is None:
                    continue
                if d.weekday() == 0 and d != self.setup.start:
                    index += 1
                out[d] = index
            self._weeks = out
        return self._weeks.get(day, 0)

    def beliefs_on(self, day: date) -> Mapping[int, Rates]:
        """The shared beliefs the seats decide on, on ``day``."""
        if self.belief == "causal":
            assert self.causal is not None
            return self.causal.on(day)
        return self.beliefs(self.week_index(day))

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


def _out_through(setup: Setup, player: int, days: Sequence[date]) -> int:
    """The game index the player is out through from the status read on day one; -1 when in."""
    s = setup.statuses.get(player)
    if s is None or not days:
        return -1
    if s in wk.OUT_ALL:
        return len(days) - 1
    if s in wk.OUT_THIS_WEEK:
        ret = setup.returns.get(player) or setup.start + timedelta(policy.DEFAULT_ABSENCE_DAYS)
        return max(-1, sum(1 for d in days if d < ret) - 1)
    return -1


def forward_world(setup: Setup, inputs: WorldInputs, seed: int, path: int, s: float) -> World:
    """The forward Monte Carlo's world: the projection with its error as the truth, lines and
    availability from the fit."""
    keys = sorted(setup.projection)
    stats = list(wk.STATS)
    eps = world.errors(seed, path, keys, stats, s, setup.gap, inputs.tau)
    truth = {
        k: consistent(v)
        for k, v in world.true_rates({k: setup.projection[k] for k in keys}, eps).items()
    }
    game_days = game_days_of(setup)

    def available(player: int) -> np.ndarray:
        days = game_days.get(player, [])
        ok, _ = world.absences(
            seed, path, player, len(days), inputs.hazard, _out_through(setup, player, days)
        )
        return ok

    def line(player: int, game: int) -> Mapping[str, float] | None:
        rates = truth.get(player)
        if rates is None:
            return None
        espn = setup.espn_ids.get(player)
        phi = {**inputs.phi, **inputs.phi_players.get(espn or "", {})}
        return world.game_line(seed, path, player, game, rates, phi, inputs.sigma)

    return World(
        setup,
        seed,
        path,
        truth,
        game_days,
        available,
        line,
        inputs.lag,
        "forward",
        belief="refresh",
        kappa=inputs.kappa,
        sigma_eta=inputs.sigma_eta,
    )


def replay_world(
    setup: Setup,
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    lag: int,
    seed: int,
    path: int,
    weights: Mapping[str, float] | None = None,
    belief: str = "causal",
    news_sd: float = world.NEWS_SD_DAYS,
) -> World:
    """A replay's world: the recorded lines are the truth of every game, a game day without a
    line an absence. The seats' belief is ``causal`` (the setup's projection updated with the
    games played before each day, at ``weights``, :data:`fit.W_DEFAULT` for a stat without one;
    a player nobody projected on the newcomer's prior once he has played) or ``fixed`` (the
    projection all season, the hold-out gate's)."""
    game_days = game_days_of(setup)
    causal = None
    if belief == "causal":
        w = {s: float((weights or {}).get(s, W_DEFAULT)) for s in wk.STATS}
        undrafted = [k for k in setup.pool if k in setup.projection]
        causal = CausalBelief(
            setup.players,
            setup.projection,
            lines,
            w,
            newcomer_prior(setup.projection, undrafted),
        )

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
        {},
        game_days,
        available,
        line,
        lag,
        "replay",
        belief=belief,
        causal=causal,
        news_sd=news_sd,
    )


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
    #: The shared beliefs and what the seats have heard (statuses, told return dates).
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


def simulate(
    setup: Setup,
    w: World,
    variants: Sequence[Mapping[int, op.Strategy]],
    execute_plan: Sequence[bool] | None = None,
    on_day: Callable[[DayRecord], None] | None = None,
    rules: Sequence[audit.Rule] | None = None,
) -> list[VariantResult]:
    """Every variant (a strategy by seat) through one world in lockstep. Each day, after the
    lineup is set and before the day's lines are read, the audit (``sim.audit``: ``rules``, or
    :data:`audit.RULES`) reads every variant's day and its counts are tallied; ``on_day`` is
    handed a :class:`DayRecord` for each variant and day at the same point."""
    n = len(variants)
    states = [initial(setup) for _ in range(n)]
    solves = [0] * n
    shared = [0] * n
    plans = list(execute_plan or [False] * n)
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    spots, slot_counts = setup.spots(), Counter(setup.roster_slots)
    auditor = audit.Auditor(setup, rules, w.path)
    tallies = [ct.Tally(setup) for _ in range(n)]
    made: Week | None = None  # the week of the last simulated day, when yesterday's moves were made
    for di, day in enumerate(setup.days):
        week = setup.week_of(day)
        if week is None:
            continue
        monday = day.weekday() == 0 and day != setup.start
        beliefs = w.beliefs_on(day)
        status, returns = w.status_on(day)
        value = wk.per_game_values(beliefs, setup.cats, points)
        # Yesterday's moves land first, cleared held players back and the held-slot moves made
        # before them: on a Monday they were made on Sunday and spend the ending week's adds, so
        # the week's count starts over only once they are in.
        order = _rotation(setup.teams, di)
        due = [s.pending for s in states]
        before = [s.executed_by for s in states]
        states = [policy.land(s, order, spots, slot_counts, status, value) for s in states]
        for vi, s in enumerate(states):
            tallies[vi].charge((made or week).number, before[vi], s.executed_by)
        if monday:
            states = [policy.new_week(s) for s in states]
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
                    decision = strat.decide(setup, state, team, beliefs, status, returns, g)
                    cache[key] = decision
                    solves[vi] += decision.solves
                decided[team] = decision
                state = policy.queue(
                    state, team, decision, _cap(strat), setup.max_weekly_adds, plans[vi], spots
                )
            states[vi] = state
            lineup = {
                t: policy.starters_of(setup, state, t, day, status, value) for t in setup.teams
            }
            lineups.append(lineup)
            auditor.check(audit.Day(day, vi, state, status, lineup))
            tallies[vi].day(week.number, state)
            if on_day is not None:
                on_day(
                    _record(setup, vi, state, due[vi], decided, beliefs, status, returns, lineup)
                )
        states = [
            policy.score_day(setup, s, day, status, value, w.line, lineups[vi])
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
    other = op.of(arm.opponents, arm.knobs, setup.market_rate)
    return {t: other for t in setup.teams if t != me}


def paired(setup: Setup, w: World, a: Arm, b: Arm, me: int) -> dict[str, Any]:
    """Arm A and arm B in seat ``me`` through one world: each outcome and their difference, B less
    A (``b[k] - a[k]``, None where either is None). Positive is B ahead on every metric but
    ``rank``, where lower is better and a negative difference is B finishing higher."""
    va = {**opponents_of(setup, a, me), me: a.seat()}
    vb = {**opponents_of(setup, b, me), me: b.seat()}
    ra, rb = simulate(setup, w, [va, vb], [a.execute_plan, b.execute_plan])
    ma, mb = _metrics(ra.summaries.get(me)), _metrics(rb.summaries.get(me))
    rivals = [t for t in setup.teams if t != me]
    return {
        "a": ma,
        "b": mb,
        "delta": {k: None if ma[k] is None or mb[k] is None else mb[k] - ma[k] for k in METRICS},
        "solves": ra.solves + rb.solves,
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
    }


def rotate(arms: Sequence[str], teams: Sequence[int], path: int) -> dict[int, str]:
    """Seat ``i`` gets arm ``(i + path) mod n``: across paths every arm sits in every seat."""
    n = len(arms)
    return {t: arms[(i + path) % n] for i, t in enumerate(teams)}


def room(
    setup: Setup,
    w: World,
    arms: Mapping[str, Arm],
    seats: Sequence[str],
    path: int,
    on_day: Callable[[DayRecord], None] | None = None,
) -> dict[str, Any]:
    """Twelve seats under named arms, rotated by ``path``; each arm's outcomes pooled over its
    seats this path. ``on_day`` is :func:`simulate`'s."""
    assigned = rotate(list(seats), setup.teams, path)
    variant = {t: arms[name].seat() for t, name in assigned.items()}
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


def verdict(by_shrink: Mapping[str, Mapping[str, Mapping[str, float | None]]]) -> dict[str, Any]:
    """The advisory line: passes when the paired change in playoff odds (B less A, as
    :func:`paired` gives it) is not below zero by more than one SE at any shrink; None when a
    shrink has no SE."""
    passes: bool | None = True
    for agg in by_shrink.values():
        d = agg.get("made_playoffs") or {}
        mean, se = d.get("mean"), d.get("se")
        if mean is None or se is None:
            passes = None
            break
        if mean < -se:
            passes = False
    return {"rule": VERDICT_RULE, "line": VERDICT_LINE, "passes": passes}


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
    worker at low priority; one worker runs them in this process (tests, smoke runs)."""
    n = workers or workers_default()
    if n <= 1 or len(tasks) <= 1:
        return [fn(*t) for t in tasks]
    with ProcessPoolExecutor(max_workers=n, initializer=_lower_priority) as pool:
        return list(pool.map(fn, *zip(*tasks, strict=True)))


# --------------------------------------------------------------------------- a replay's league
#: ESPN's eligible slot ids that are a position (the combinations, UTIL, bench and IR are not).
ESPN_POSITIONS: Mapping[int, str] = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F"}
#: The roster a replay's seats fill: the private league's shape without held slots.
REPLAY_SLOTS = ("PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util", "BN", "BN", "BN")
REPLAY_WEEKS = 22
REPLAY_PLAYOFF_WEEKS = 3
REPLAY_PLAYOFF_TEAMS = 6
REPLAY_TEAMS = 12
#: A stand-in forecaster projects a player with at least this many played games in the season
#: it reads: the prior season for the prior-season forecaster, the replayed one for the oracle.
STANDIN_MIN_GAMES = 20
#: The gates read the players with at least this many played games in the season.
GATE_MIN_GAMES = 20
#: A replay's draft takes the projected players with a scheduled game in the season's first this
#: many days: an opening-night roster is known before a draft.
OPENING_DAYS = 7


def replay_setup(
    season: int,
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    players: Mapping[int, Member],
    standin: Mapping[int, Rates],
    period_one: date,
    scheduled: Mapping[int, Sequence[date]] | None = None,
    teams: int = REPLAY_TEAMS,
    slots: Sequence[str] = REPLAY_SLOTS,
    weeks: int = REPLAY_WEEKS,
    playoff_weeks: int = REPLAY_PLAYOFF_WEEKS,
    playoff_teams: int = REPLAY_PLAYOFF_TEAMS,
    cats: Sequence[str] = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"),
    opening_days: int | None = OPENING_DAYS,
) -> Setup:
    """A made-up league on a recorded season, from what is known before it starts. Its players
    are everyone ``players`` lists with a scheduled game, projected or not; ``teams`` seats
    snake-draft the projected ones with a scheduled game in the season's first ``opening_days``
    days (from ``period_one``; None drafts every projected player) on the stand-in projection,
    and everyone else is on the wire. A round robin over the regular weeks, the bracket reseeded
    with the higher seed through a tie. Every player is his own team in the schedule
    (``p<id>``): his game days are his ``scheduled`` entries (played or not; the days he has a
    line for when none are given), so a trade or a team read later than the season moves
    nothing."""
    schedule: dict[date, set[str]] = {}
    members: dict[int, Member] = {}
    game_days: dict[int, list[date]] = {}
    for k, m in players.items():
        days = list((scheduled or {}).get(k) or list(lines.get(k, {})))
        if not days:
            continue
        own = f"p{k}"
        members[k] = Member(k, m.name, own, m.positions)
        game_days[k] = days
        for d in days:
            schedule.setdefault(d, set()).add(own)
    calendar = weeks_from(period_one, weeks)
    regular = tuple(range(1, weeks - playoff_weeks + 1))
    playoffs = tuple(range(weeks - playoff_weeks + 1, weeks + 1))
    ids = tuple(range(1, teams + 1))
    pairings = round_robin(ids, regular)
    projected = [k for k in standin if k in members]
    opening = None if opening_days is None else period_one + timedelta(opening_days - 1)
    draftable = [
        k
        for k in projected
        if opening is None or any(period_one <= d <= opening for d in game_days[k])
    ]
    points = None
    value = wk.per_game_values({k: standin[k] for k in projected}, tuple(cats), points)
    spots = sum(1 for s in slots if s not in mv.HELD)
    rosters = snake_draft(draftable, value, ids, spots)
    taken = {k for r in rosters.values() for k, _ in r}
    spec = lg.LeagueSpec(
        ids,
        pairings,
        playoffs,
        tuple(cats),
        "categories",
        None,
        playoff_teams,
        2 ** math.ceil(math.log2(playoff_teams)) - playoff_teams,
    )
    return Setup(
        league=f"replay-{season}",
        start=calendar.weeks[0].start,
        calendar=calendar,
        pairings=pairings,
        teams=ids,
        players=members,
        rosters=rosters,
        pool=tuple(k for k in members if k not in taken),
        projection={k: dict(standin[k]) for k in projected},
        schedule={d: frozenset(t) for d, t in schedule.items()},
        roster_slots=tuple(slots),
        cats=tuple(cats),
        max_weekly_adds=4,
        market={k: value.get(k, 0.0) for k in projected},
        spec=spec,
    )


def realized_rates(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]], min_games: int = 1
) -> dict[int, dict[str, float]]:
    """Each player's per-game rates over the games he played, for those with ``min_games``."""
    out: dict[int, dict[str, float]] = {}
    for k, by_day in lines.items():
        n = len(by_day)
        if not n or n < min_games:
            continue
        totals: dict[str, float] = {}
        for ln in by_day.values():
            for stat, x in ln.items():
                totals[stat] = totals.get(stat, 0.0) + float(x)
        out[k] = {stat: v / n for stat, v in totals.items() if stat in wk.STATS}
    return out


def oracle_standin(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    spread: float,
    seed: int,
    path: int,
    min_games: int = STANDIN_MIN_GAMES,
) -> dict[int, dict[str, float]]:
    """The replayed season's realized rates noised on the log scale at ``spread`` per player and
    stat: a stand-in projection whose error is known, a labelled look-ahead. It projects only the
    players with ``min_games`` played games in the replayed season, a stated part of that
    look-ahead; the others arrive by the newcomer's rule."""
    truth = realized_rates(lines, min_games)
    keys = sorted(truth)
    eps = world.errors(seed, path, keys, list(wk.STATS), 0.0, {}, dict.fromkeys(wk.STATS, spread))
    return {k: consistent(v) for k, v in world.true_rates({k: truth[k] for k in keys}, eps).items()}


__all__ = [
    "BELIEFS",
    "GATE_MIN_GAMES",
    "KNOBS",
    "METRICS",
    "OPENING_DAYS",
    "SHRINKS",
    "STANDIN_MIN_GAMES",
    "Arm",
    "DayRecord",
    "VariantResult",
    "World",
    "WorldInputs",
    "aggregate",
    "arm_of",
    "check_fit",
    "consistent",
    "forward_world",
    "inputs_of",
    "oracle_standin",
    "paired",
    "realized_rates",
    "replay_setup",
    "replay_world",
    "room",
    "rotate",
    "run_tasks",
    "simulate",
    "verdict",
]
