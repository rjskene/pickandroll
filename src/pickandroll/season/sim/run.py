"""The runner (#172, PR 2b): one world a path, arms in lockstep, the paired difference.

A :class:`World` is one path of one league: the truth (the projection with its persistent error),
each player's game days, availability and lines, the shared beliefs refreshed weekly and what the
policy has heard of each absence. Every draw comes from ``world.rng(seed, path, player, game,
stream)`` and never from an arm, so a roster change in one arm reshuffles nothing for any player:
common random numbers. :func:`forward_world` builds it from a setup and the frozen fit's figures;
:func:`replay_world` from a season's recorded lines, which are then the truth (no game noise, no
hazard: the logs happened).

:func:`simulate` advances several variants of one league through the same world day by day: the
moves decided yesterday land, each seat decides, the day is played and scored. Variants whose
states agree share one solve (the lockstep of the design note); from the first divergence each
solves alone. :func:`paired` runs arm A and arm B for one seat and returns the paired difference
of the season's outcomes; :func:`room` runs twelve seats under named arms rotated across paths.
Pure but for the process pool: nothing here reads a file; the readers (``api.season_sim``) and the
script bring the inputs and write the payload.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

import numpy as np

from .. import moves as mv
from .. import weekly as wk
from ..progress import KNOBS
from . import league as lg
from . import opponents as op
from . import policy, world
from .fit import Component, Hazard
from .state import Member, Setup, initial, round_robin, snake_draft, weeks_from

Rates = Mapping[str, float]
#: The shrinks a comparison runs at (the design note's axis).
SHRINKS = (0.0, 0.25, 0.5)
#: The metrics a path reports for a seat.
METRICS = ("made_playoffs", "rank", "category_wins", "matchup_wins", "title")
#: The verdict line's rule, advisory until PR 3 (the master's ruling on PR 2's plan).
VERDICT_RULE = "one-SE"
VERDICT_LINE = (
    "advisory: a change passes when the paired change in playoff odds is not below zero by more "
    "than one standard error at any shrink; no block and no promotion before PR 3"
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
class World:
    """One path of one league: truth, lines, availability, beliefs and news."""

    def __init__(
        self,
        setup: Setup,
        seed: int,
        path: int,
        truth: Mapping[int, Rates],
        game_days: Mapping[int, Sequence[date]],
        available: Callable[[int], np.ndarray],
        line: Callable[[int, int], Mapping[str, float] | None],
        kappa: float,
        sigma_eta: float,
        lag: int,
        kind: str,
    ) -> None:
        self.setup = setup
        self.seed, self.path = seed, path
        self.truth = truth
        self.game_days = {k: list(v) for k, v in game_days.items()}
        self._index = {k: {d: i for i, d in enumerate(v)} for k, v in self.game_days.items()}
        self._available = available
        self._line = line
        self.kappa, self.sigma_eta, self.lag = kappa, sigma_eta, lag
        self.kind = kind
        self._avail: dict[int, np.ndarray] = {}
        self._absences: dict[int, list[world.Absence]] = {}
        self._lines: dict[tuple[int, date], Mapping[str, float] | None] = {}
        self._beliefs: dict[int, Mapping[int, Rates]] = {0: dict(setup.projection)}
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

    def beliefs(self, week: int) -> Mapping[int, Rates]:
        """The shared beliefs after ``week`` weekly refreshes (0: the projection)."""
        if week not in self._beliefs:
            prev = self.beliefs(week - 1)
            self._beliefs[week] = world.refresh(
                prev, self.truth, self.kappa, self.sigma_eta, self.seed, self.path, week
            )
        return self._beliefs[week]

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
                noise = round(float(g.standard_normal() * world.NEWS_SD_DAYS))
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


def consistent(rates: Rates) -> dict[str, float]:
    """A rate line whose makes do not exceed its attempts nor its threes its field goals: the
    errors are drawn a stat at a time, and a line that breaks the identities has no variance."""
    out = {k: float(v) for k, v in rates.items()}
    if "fgm" in out and "fga" in out:
        out["fgm"] = min(out["fgm"], out["fga"])
    if "ftm" in out and "fta" in out:
        out["ftm"] = min(out["ftm"], out["fta"])
    if "threes" in out and "fgm" in out:
        out["threes"] = min(out["threes"], out["fgm"])
    return out


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
        inputs.kappa,
        inputs.sigma_eta,
        inputs.lag,
        "forward",
    )


def replay_world(
    setup: Setup,
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    truth: Mapping[int, Rates],
    kappa: float,
    sigma_eta: float,
    lag: int,
    seed: int,
    path: int,
) -> World:
    """A replay's world: the recorded lines are the truth of every game, a game day without a
    line an absence; beliefs still refresh toward the season's realized rates."""
    game_days = game_days_of(setup)

    def available(player: int) -> np.ndarray:
        days = game_days.get(player, [])
        played = lines.get(player, {})
        return np.array([d in played for d in days], dtype=bool)

    def line(player: int, game: int) -> Mapping[str, float] | None:
        day = game_days[player][game]
        return lines.get(player, {}).get(day)

    return World(
        setup, seed, path, truth, game_days, available, line, kappa, sigma_eta, lag, "replay"
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


def _rotation(teams: Sequence[int], i: int) -> list[int]:
    n = len(teams)
    return [teams[(j + i) % n] for j in range(n)] if n else []


def _cap(strategy: Any) -> int:
    knobs = getattr(strategy, "knobs", None)
    if knobs is None:
        return 1
    return int(policy.knob(knobs, "daily_cap"))


def simulate(
    setup: Setup,
    w: World,
    variants: Sequence[Mapping[int, op.Strategy]],
    execute_plan: Sequence[bool] | None = None,
) -> list[VariantResult]:
    """Every variant (a strategy by seat) through one world in lockstep."""
    n = len(variants)
    states = [initial(setup) for _ in range(n)]
    solves = [0] * n
    shared = [0] * n
    plans = list(execute_plan or [False] * n)
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    week_index = 0
    for di, day in enumerate(setup.days):
        week = setup.week_of(day)
        if week is None:
            continue
        if day.weekday() == 0 and day != setup.start:
            week_index += 1
            states = [policy.new_week(s) for s in states]
        order = _rotation(setup.teams, di)
        states = [policy.land(s, order) for s in states]
        beliefs = w.beliefs(week_index)
        status, returns = w.status_on(day)
        value = wk.per_game_values(beliefs, setup.cats, points)
        cache: dict[tuple[Any, ...], policy.Decision] = {}
        for vi, state in enumerate(states):
            state = replace(state, day=day)
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
                state = policy.queue(
                    state, team, decision, _cap(strat), setup.max_weekly_adds, plans[vi]
                )
            states[vi] = state
        states = [policy.score_day(setup, s, day, status, value, w.line) for s in states]
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
    """Arm A and arm B in seat ``me`` through one world: each outcome and their difference."""
    va = {**opponents_of(setup, a, me), me: a.seat()}
    vb = {**opponents_of(setup, b, me), me: b.seat()}
    ra, rb = simulate(setup, w, [va, vb], [a.execute_plan, b.execute_plan])
    ma, mb = _metrics(ra.summaries.get(me)), _metrics(rb.summaries.get(me))
    return {
        "a": ma,
        "b": mb,
        "delta": {k: None if ma[k] is None or mb[k] is None else ma[k] - mb[k] for k in METRICS},
        "solves": ra.solves + rb.solves,
        "shared": rb.shared,
        "executed": [ra.executed, rb.executed],
        "gone": [ra.gone, rb.gone],
        "bracket_unread": setup.bracket_unread,
    }


def rotate(arms: Sequence[str], teams: Sequence[int], path: int) -> dict[int, str]:
    """Seat ``i`` gets arm ``(i + path) mod n``: across paths every arm sits in every seat."""
    n = len(arms)
    return {t: arms[(i + path) % n] for i, t in enumerate(teams)}


def room(
    setup: Setup, w: World, arms: Mapping[str, Arm], seats: Sequence[str], path: int
) -> dict[str, Any]:
    """Twelve seats under named arms, rotated by ``path``; each arm's outcomes pooled over its
    seats this path."""
    assigned = rotate(list(seats), setup.teams, path)
    variant = {t: arms[name].seat() for t, name in assigned.items()}
    (r,) = simulate(setup, w, [variant], [any(arms[n].execute_plan for n in seats)])
    by_arm: dict[str, list[dict[str, float | None]]] = {}
    for t, name in assigned.items():
        by_arm.setdefault(name, []).append(_metrics(r.summaries.get(t)))
    return {
        "seats": {str(t): name for t, name in assigned.items()},
        "by_arm": {
            name: {k: _mean([m[k] for m in rows]) for k in METRICS} for name, rows in by_arm.items()
        },
        "solves": r.solves,
        "shared": r.shared,
        "executed": r.executed,
        "gone": r.gone,
        "bracket_unread": setup.bracket_unread,
    }


def _mean(xs: Sequence[float | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return sum(vals) / len(vals) if vals else None


def aggregate(
    rows: Sequence[Mapping[str, float | None]],
) -> dict[str, dict[str, float | int | None]]:
    """Each metric's mean, standard error and count over ``rows`` (one a path)."""
    out: dict[str, dict[str, float | int | None]] = {}
    for k in METRICS:
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
    """The advisory line: passes when the paired change in playoff odds is not below zero by
    more than one SE at any shrink; None when a shrink has no SE."""
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
#: A player needs this many played games in the season to be in a replay's pool.
REPLAY_MIN_GAMES = 20


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
) -> Setup:
    """A made-up league on a recorded season: ``teams`` seats snake-drafting the pool on the
    stand-in projection, a round robin over the regular weeks, the bracket reseeded with the
    higher seed through a tie. Every player is his own team in the schedule (``p<id>``): his
    game days are his ``scheduled`` entries (played or not; the days he has a line for when
    none are given), so a trade or a team read later than the season moves nothing."""
    schedule: dict[date, set[str]] = {}
    members: dict[int, Member] = {}
    for k, m in players.items():
        own = f"p{k}"
        members[k] = Member(k, m.name, own, m.positions)
        days = (scheduled or {}).get(k) or list(lines.get(k, {}))
        for d in days:
            schedule.setdefault(d, set()).add(own)
    calendar = weeks_from(period_one, weeks)
    regular = tuple(range(1, weeks - playoff_weeks + 1))
    playoffs = tuple(range(weeks - playoff_weeks + 1, weeks + 1))
    ids = tuple(range(1, teams + 1))
    pairings = round_robin(ids, regular)
    pool = [k for k in standin if k in members and len(lines.get(k, {})) >= REPLAY_MIN_GAMES]
    points = None
    value = wk.per_game_values({k: standin[k] for k in pool}, tuple(cats), points)
    spots = sum(1 for s in slots if s not in mv.HELD)
    rosters = snake_draft(pool, value, ids, spots)
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
        players={k: members[k] for k in pool},
        rosters=rosters,
        pool=tuple(k for k in pool if k not in taken),
        projection={k: dict(standin[k]) for k in pool},
        schedule={d: frozenset(t) for d, t in schedule.items()},
        roster_slots=tuple(slots),
        cats=tuple(cats),
        max_weekly_adds=4,
        market={k: value.get(k, 0.0) for k in pool},
        spec=spec,
    )


def realized_rates(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
) -> dict[int, dict[str, float]]:
    """Each player's per-game rates over the games he played."""
    out: dict[int, dict[str, float]] = {}
    for k, by_day in lines.items():
        n = len(by_day)
        if not n:
            continue
        totals: dict[str, float] = {}
        for ln in by_day.values():
            for stat, x in ln.items():
                totals[stat] = totals.get(stat, 0.0) + float(x)
        out[k] = {stat: v / n for stat, v in totals.items() if stat in wk.STATS}
    return out


def oracle_standin(
    truth: Mapping[int, Rates], spread: float, seed: int, path: int
) -> dict[int, dict[str, float]]:
    """The realized rates noised on the log scale at ``spread`` per player and stat: a stand-in
    projection whose error is known."""
    keys = sorted(truth)
    eps = world.errors(seed, path, keys, list(wk.STATS), 0.0, {}, dict.fromkeys(wk.STATS, spread))
    return {k: consistent(v) for k, v in world.true_rates({k: truth[k] for k in keys}, eps).items()}


__all__ = [
    "KNOBS",
    "METRICS",
    "SHRINKS",
    "Arm",
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
