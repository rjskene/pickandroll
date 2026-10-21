"""The strategy engine (#110, docs/ADD_DROP.md "The strategy engine"): which waiver moves serve
the rest of this week and the rest of the season together, on one weighted value

    λ · week + (1 − λ) · weeks_left · later

``week`` is the move model's expected categories won over the rest of this week against the
named opponent (#94) and ``later`` a typical later week's against the field: the move model's
three weeks ahead, averaged. So the rest of the season is read from the three weeks ahead, and
every number is the move model's evaluator, which keeps the engine in step with the Moves panel
and the Matchup card. λ = 1 is this week alone, 0 the rest of the season alone, and 0.5 the
natural weight, where every week counts once (:func:`weights`).

Two solvers answer each weight, and the set that is better on the weight's exact value is the
one recommended (:func:`choose`):

* the move model's exact search (``moves.search``) on the weighted value (:class:`Weighted`);
* the draft's roster MILP applied to the moves (:func:`solve_milp`), HiGHS through PuLP.
  Binaries ``a[p]`` add candidate ``p`` and ``g[q, t]`` drop my player ``q`` on date ``t``, one
  of the days an add arrives (the first day for a free agent, the clear date for a claim): at
  most once each, and on each date no more drops than adds. A drop keeps his games before his
  date. Each week's adds stay within its limit. Continuous starts fill the league's slots on
  each day of this week (a matching per day, integral for a fixed roster, so the program picks
  the lineup) and are capped by count at the number of starting slots on each later day. Each
  category's total goes through the draft's piecewise Φ (``objective.add_segments``): this week
  against the named opponent's final with the base roster's spread, a later week against the
  field (the other teams' projected weeks: the mean, and the spread between teams with two
  teams' weekly noise, :func:`curves`). Percentages are impacts (makes less a reference
  percentage times attempts), turnovers negated, a points league one curve on its points.

On the prize leagues' data of 2026-10-21 the program was exact and fast for this week, and on
the later weeks the exact search on the same weighted value found the better set more often:
the count cap and a single normal for the field are not the evaluator's lineups and
per-opponent odds. That is why both run. The program makes no held-slot moves (an add needs a
drop or an open spot); the search does. HiGHS starts from the search's set, which it completes
into its first incumbent, and its own model status says whether a solve finished or hit the time
limit (PuLP calls both "Optimal").
"""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import highspy
import numpy as np
import pulp

from ..optim.objective import add_segments, normal_segments, phi_density
from . import moves as mv
from . import weekly as wk
from .state import Player

#: The weighted horizon's key for ``moves.search`` and ``moves.recommend``.
WEIGHTED = "weighted"
#: The program's time limit per weight, in seconds.
TIME_LIMIT = 10.0
#: HiGHS's relative gap.
GAP = 1e-4
#: How far each curve's pieces reach past its mean, in spreads, beyond the totals' own range.
REACH = 8.0
#: The smallest spread a curve is given (a category nobody plays).
MIN_SIGMA = 1e-6
#: The program's status: solved to the gap, stopped at the time limit with a set, or no set.
OPTIMAL, TIME_LIMITED, FAILED = "optimal", "time_limited", "failed"
#: Which solver's set a point recommends.
SEARCH, MILP, BOTH = "search", "milp", "both"


# --------------------------------------------------------------------------- the weights
@dataclass(frozen=True)
class Weight:
    key: str
    label: str
    lam: float
    #: The natural weight: every week counts once.
    natural: bool = False


def weights(weeks_left: int) -> tuple[Weight, ...]:
    """The frontier's weights: this week alone, this week as much as all the later weeks
    together, every week alike (the natural weight) and the rest of the season alone. With no
    week after this one, only this week's."""
    week = Weight("week", "this week", 1.0)
    if weeks_left <= 0:
        return (week,)
    return (
        week,
        Weight("even", "this week as much as the rest", weeks_left / (1 + weeks_left)),
        Weight("natural", "every week alike", 0.5, natural=True),
        Weight("season", "rest of season", 0.0),
    )


WEIGHT_KEYS = ("week", "even", "natural", "season")


class Weighted:
    """The move model's values on one weighted horizon, ``WEIGHTED``, beside its own two (for
    ``moves.search`` and ``moves.recommend``): λ times this week's value plus 1 − λ times the
    weeks left times a later week's, the three weeks ahead averaged."""

    def __init__(self, ev: mv.Evaluator, lam: float, weeks_left: int) -> None:
        self.ev = ev
        self.problem = ev.problem
        self.lam = lam
        self.weeks_left = weeks_left
        self.later = len(ev.problem.horizons.get("three", ()))
        self.base = {**ev.base, WEIGHTED: self.value(WEIGHTED, ())}

    def combine(self, week: float, three: float) -> float:
        """The weighted value (or gain) of this week's and the three weeks' values (or gains)."""
        return self.lam * week + (1 - self.lam) * self.season(three)

    def season(self, three: float) -> float:
        """The rest of the season's value (or gain) from the three weeks': a later week's times
        the weeks left."""
        return self.weeks_left * three / self.later if self.later else 0.0

    def value(self, key: str, moves: Iterable[mv.Move]) -> float:
        if key != WEIGHTED:
            return self.ev.value(key, moves)
        moves = tuple(moves)
        three = self.ev.value("three", moves) if self.later else 0.0
        return self.combine(self.ev.value("week", moves), three)

    def gain(self, key: str, moves: Iterable[mv.Move]) -> float:
        return self.value(key, moves) - self.base[key]


def pool_of(gains: Mapping[str, Mapping[int, float]], size: int) -> list[int]:
    """The candidates both solvers search: the best by single-move gain on each horizon (the
    Moves panel's), taken in turn, ``size`` in all."""
    ranked = [sorted(g, key=lambda c: (-g[c], c)) for g in gains.values()]
    out: list[int] = []
    seen: set[int] = set()
    for row in itertools.zip_longest(*ranked):
        for cand in row:
            if cand is not None and cand not in seen:
                seen.add(cand)
                out.append(cand)
                if len(out) == size:
                    return out
    return out


# --------------------------------------------------------------------------- the curves
@dataclass(frozen=True)
class Curve:
    mu: float
    sigma: float


@dataclass(frozen=True)
class Curves:
    """What the program needs beyond the problem: each category's curve this week and in a
    later week, the percentages each percentage's impact is taken against, and my week so far
    (as impacts, turnovers negated)."""

    week: Mapping[str, Curve]
    week_ref: Mapping[str, float]
    so_far: Mapping[str, float]
    later: Mapping[str, Curve]
    later_ref: Mapping[str, float]


def contribution(
    rates: wk.Rates | None, cat: str, points: Mapping[str, float] | None, ref: float | None
) -> float:
    """A player's per-game contribution to a category's total as the program counts it: his
    impact on a percentage (makes less ``ref`` times attempts), negated turnovers, his fantasy
    points in a points league."""
    if not rates:
        return 0.0
    if cat == wk.FPTS:
        return sum(float(w) * float(rates.get(s, 0.0)) for s, w in (points or {}).items())
    if cat in wk.PCT:
        made, att = wk.PCT[cat]
        return float(rates.get(made, 0.0)) - (ref or 0.0) * float(rates.get(att, 0.0))
    v = float(rates.get(cat, 0.0))
    return -v if cat in wk.LOWER_WINS else v


def _total(totals: Mapping[str, float], cat: str, ref: float | None) -> float:
    """A week's total of ``cat`` as the program counts it (:func:`contribution`)."""
    if cat in wk.PCT:
        made, att = wk.PCT[cat]
        return totals.get(made, 0.0) - (ref or 0.0) * totals.get(att, 0.0)
    v = totals.get(cat, 0.0)
    return -v if cat in wk.LOWER_WINS else v


def curves(ev: mv.Evaluator) -> Curves:
    """The program's curves. This week: the named opponent's final as the mean (a percentage's
    impact against his percentage, so zero) and the spread of the base roster's odds. A later
    week: the field's teams on the three weeks ahead averaged, the mean of their totals and the
    spread between them with two teams' weekly noise (mine and an opponent's), each percentage
    against the field's own. The field's totals count every game its players play, not only
    the evaluator's starts: the count cap on my side ignores positions and so overstates my
    starts as much (on 2026-10-21's leagues the field's starts did as well or worse at every
    weight, by up to a third of a category-week)."""
    p = ev.problem
    week: dict[str, Curve] = {}
    week_ref: dict[str, float] = {}
    so_far: dict[str, float] = {}
    spans = p.horizons.get("week", ())
    if spans and spans[0].opponents:
        span = spans[0]
        odds = ev.odds("week", ())[0][0]
        theirs = wk.finals(
            span.opponents[0], span.so_far_theirs[0] if span.so_far_theirs else {}, p.cats
        )
        mine = ev.mine("week", ())[0]
        for o in odds:
            c, sd = o.cat, max(o.sd, MIN_SIGMA)
            if c in wk.PCT:
                made, att = wk.PCT[c]
                ref = theirs[c][0] or 0.0
                week_ref[c] = ref
                attempts = span.so_far.get(att, 0.0) + mine.totals.get(att, 0.0)
                so_far[c] = span.so_far.get(made, 0.0) - ref * span.so_far.get(att, 0.0)
                week[c] = Curve(0.0, max(o.sd * attempts, MIN_SIGMA))
            else:
                so_far[c] = _total(span.so_far, c, None)
                mean = theirs[c][0] or 0.0
                week[c] = Curve(-mean if c in wk.LOWER_WINS else mean, sd)
    later: dict[str, Curve] = {}
    later_ref: dict[str, float] = {}
    spans = p.horizons.get("three", ())
    teams = len(spans[0].opponents) if spans else 0
    if teams:
        rows: list[dict[str, float]] = []
        for t in range(teams):
            row = dict.fromkeys(wk.STATS, 0.0)
            for sp in spans:
                for key, pw in sp.opponents[t].players.items():
                    r = p.rates.get(key) or {}
                    for s in wk.STATS:
                        row[s] += pw.games * float(r.get(s, 0.0)) / len(spans)
            row[wk.FPTS] = sum(float(w) * row.get(s, 0.0) for s, w in (p.points or {}).items())
            rows.append(row)
        for c, (made, att) in wk.PCT.items():
            attempts = sum(r[att] for r in rows)
            later_ref[c] = sum(r[made] for r in rows) / attempts if attempts else 0.0
        for c in p.cats:
            xs = [_total(r, c, later_ref.get(c)) for r in rows]
            mu = sum(xs) / len(xs)
            between = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1) if len(xs) > 1 else 0.0
            noise = [
                float(sp.opponents[t].variance.get(c, 0.0)) for sp in spans for t in range(teams)
            ]
            spread = math.sqrt(between + 2 * sum(noise) / len(noise))
            later[c] = Curve(mu, max(spread, MIN_SIGMA))
    return Curves(week, week_ref, so_far, later, later_ref)


# --------------------------------------------------------------------------- the program
@dataclass(frozen=True)
class Milp:
    moves: tuple[mv.Move, ...]
    status: str
    seconds: float
    #: Variables, binaries and constraints.
    size: Mapping[str, int]
    #: The program's own value of its set on the horizons it modelled (``week``, ``later``).
    model: Mapping[str, float] = field(default_factory=dict)
    #: Each category's curve slope at the solution, by horizon (for :func:`first_order`).
    slopes: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    #: Each category's total at the solution as the program counts it (:func:`contribution`),
    #: by horizon: this week's from the week so far, a later week's.
    totals: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


def _days(
    problem: mv.MoveProblem, key: int, player: Player, span: mv.WeekSpan, avail: Mapping[int, date]
) -> list[date]:
    """The days of ``span`` ``player`` plays on, as ``weekly.project_week`` counts them."""
    played = wk.game_days(player.nba_team, span.days, problem.schedule)
    if span.games is not None and key in span.games:
        n = max(0, min(int(span.games[key]), len(played)))
        played = played[len(played) - n :]
    elif wk.is_out(player, span.this_week, key in problem.no_games):
        played = []
    if key in avail:
        played = [d for d in played if d >= avail[key]]
    return played


class _Started(pulp.HiGHS):
    """HiGHS from a starting point: the values of some variables, which it completes (a sub-MIP
    with them fixed) into its first incumbent."""

    def __init__(self, start: Mapping[Any, float], **kw: Any) -> None:
        super().__init__(**kw)
        self.start = start

    def callSolver(self, lp: pulp.LpProblem) -> None:
        if self.start:
            idx = np.array([v.index for v in self.start], dtype=np.int32)
            val = np.array(list(self.start.values()), dtype=np.float64)
            lp.solverModel.setSolution(len(idx), idx, val)
        lp.solverModel.run()


def _status(model: pulp.LpProblem) -> str:
    """HiGHS's own word on the solve: PuLP labels a time-limited solve "Optimal"."""
    status = model.solverModel.getModelStatus()
    if status == highspy.HighsModelStatus.kOptimal:
        return OPTIMAL
    if model.sol_status == pulp.LpSolutionIntegerFeasible:
        return TIME_LIMITED
    return FAILED


def solve_milp(
    problem: mv.MoveProblem,
    curves: Curves,
    pool: Sequence[int],
    lam: float,
    weeks_left: int,
    keep: Iterable[int] = (),
    start: Sequence[mv.Move] | None = None,
    time_limit: float = TIME_LIMIT,
    gap: float = GAP,
) -> Milp:
    """The program's set of moves among ``pool`` at weight ``lam``, ``keep`` never dropped,
    started from ``start`` (the search's set). A horizon without weight is left out of the
    model."""
    t0 = time.perf_counter()
    p = problem
    held, roster = dict(p.held), dict(p.roster)
    cands = {k: pl for k, pl in p.candidates if k in set(pool)}
    members: dict[int, Player] = {**held, **roster, **cands}
    eff = {k: p.effective[k] for k in cands}
    avail = {**p.effective, **p.returns}
    kept = set(keep)
    slots = tuple(p.slots)
    model = pulp.LpProblem("strategy", pulp.LpMaximize)
    a = {k: model.add_variable(f"a_{k}", cat=pulp.LpBinary) for k in cands}
    dates = sorted(set(eff.values()))
    g = {
        (q, t): model.add_variable(f"g_{q}_{t:%Y%m%d}", cat=pulp.LpBinary)
        for q in roster
        if q not in kept
        for t in dates
    }
    for q in roster:
        if q not in kept and dates:
            model += pulp.lpSum(g[q, t] for t in dates) <= 1, f"once_{q}"
    for t in dates:
        leaving = pulp.lpSum(g[q, t] for q in roster if (q, t) in g)
        model += leaving <= pulp.lpSum(a[k] for k in cands if eff[k] == t), f"arrive_{t:%Y%m%d}"
    model += pulp.lpSum(a.values()) <= pulp.lpSum(g.values()) + mv.open_spots(p), "spots"
    for i, lim in enumerate(p.limits):
        inside = [a[k] for k in cands if lim.start <= eff[k] <= lim.end]
        if lim.adds is not None and inside:
            model += pulp.lpSum(inside) <= lim.adds, f"limit_{i}"

    def on(k: int, day: date) -> Any:
        """1 when ``k`` is on my roster on ``day``."""
        if k in held:
            return 1
        if k in roster:
            return 1 - pulp.lpSum(g[k, t] for t in dates if t <= day and (k, t) in g)
        return a[k]

    def curve(name: str, cv: Curve, total: Any, lo: float, hi: float) -> Any:
        lo, hi = min(lo, cv.mu - REACH * cv.sigma), max(hi, cv.mu + REACH * cv.sigma)
        return add_segments(model, name, total, lo, *normal_segments(cv.mu, cv.sigma, lo, hi))

    totals: dict[str, dict[str, Any]] = {}
    value: dict[str, Any] = {}
    spans = p.horizons.get("week", ())
    if lam > 0 and spans and spans[0].opponents and curves.week:
        span = spans[0]
        days = {k: _days(p, k, pl, span, avail) for k, pl in members.items()}
        u: dict[tuple[int, date, int], Any] = {}
        for k, pl in members.items():
            fits = wk._fits(slots, tuple(pl.positions))
            for day in days[k]:
                for si in fits:
                    u[k, day, si] = model.add_variable(f"u_{k}_{day:%Y%m%d}_{si}", 0, 1)
        for day in span.days:
            for si in range(len(slots)):
                xs = [u[k, day, si] for k in members if (k, day, si) in u]
                if len(xs) > 1:
                    model += pulp.lpSum(xs) <= 1, f"slot_{day:%Y%m%d}_{si}"
            for k in members:
                xs = [u[k, day, si] for si in range(len(slots)) if (k, day, si) in u]
                if xs:
                    model += pulp.lpSum(xs) <= on(k, day), f"on_{k}_{day:%Y%m%d}"
        totals["week"], value["week"] = {}, 0
        for c in p.cats:
            per = {
                k: contribution(p.rates.get(k), c, p.points, curves.week_ref.get(c))
                for k in members
            }
            base = curves.so_far.get(c, 0.0)
            total = base + pulp.lpSum(per[k] * x for (k, _, _), x in u.items())
            lo = base + sum(min(0.0, per[k]) * len(days[k]) for k in members)
            hi = base + sum(max(0.0, per[k]) * len(days[k]) for k in members)
            totals["week"][c] = total
            value["week"] += curve(f"w_{c}", curves.week[c], total, lo, hi)
    later = p.horizons.get("three", ())
    if lam < 1 and weeks_left > 0 and later and curves.later:
        v: dict[tuple[int, date], Any] = {}
        played: dict[int, int] = {k: 0 for k in members}
        for span in later:
            for k, pl in members.items():
                for day in _days(p, k, pl, span, avail):
                    v[k, day] = model.add_variable(f"v_{k}_{day:%Y%m%d}", 0, 1)
                    played[k] += 1
                    if k not in held:
                        model += v[k, day] <= on(k, day), f"son_{k}_{day:%Y%m%d}"
        for day in sorted({d for _, d in v}):
            xs = [x for (_, d), x in v.items() if d == day]
            if len(xs) > len(slots):
                model += pulp.lpSum(xs) <= len(slots), f"starts_{day:%Y%m%d}"
        totals["later"], value["later"] = {}, 0
        for c in p.cats:
            per = {
                k: contribution(p.rates.get(k), c, p.points, curves.later_ref.get(c)) / len(later)
                for k in members
            }
            total = pulp.lpSum(per[k] * x for (k, _), x in v.items())
            lo = sum(min(0.0, per[k]) * played[k] for k in members)
            hi = sum(max(0.0, per[k]) * played[k] for k in members)
            totals["later"][c] = total
            value["later"] += curve(f"l_{c}", curves.later[c], total, lo, hi)
    model += lam * value.get("week", 0) + (1 - lam) * weeks_left * value.get("later", 0)
    size = {
        "variables": len(model.variables()),
        # PuLP keeps a binary as an integer in [0, 1].
        "binaries": sum(1 for x in model.variables() if x.cat == pulp.LpInteger),
        "constraints": model.numConstraints(),
    }
    seed: dict[Any, float] = {}
    if start is not None:
        seed = dict.fromkeys([*a.values(), *g.values()], 0.0)
        for m in start:
            if m.add in a:
                seed[a[m.add]] = 1.0
                if m.drop is not None and (m.drop, eff[m.add]) in g:
                    seed[g[m.drop, eff[m.add]]] = 1.0
    model.solve(_Started(seed, msg=False, timeLimit=time_limit, gapRel=gap))
    status = _status(model)
    if status == FAILED:
        return Milp((), status, time.perf_counter() - t0, size)
    adds = sorted((k for k in cands if (a[k].value() or 0.0) > 0.5), key=lambda k: (eff[k], k))
    leaving = {
        t: [q for q in roster if (q, t) in g and (g[q, t].value() or 0.0) > 0.5] for t in dates
    }
    moves = tuple(mv.Move(k, leaving[eff[k]].pop(0) if leaving[eff[k]] else None) for k in adds)
    slopes: dict[str, dict[str, float]] = {}
    for h, by_cat in totals.items():
        cvs = curves.week if h == "week" else curves.later
        slopes[h] = {
            c: phi_density((pulp.value(t) - cvs[c].mu) / cvs[c].sigma) / cvs[c].sigma
            for c, t in by_cat.items()
        }
    model_value = {h: float(pulp.value(x)) for h, x in value.items()}
    at = {h: {c: float(pulp.value(t)) for c, t in by_cat.items()} for h, by_cat in totals.items()}
    return Milp(moves, status, time.perf_counter() - t0, size, model_value, slopes, at)


def first_order(
    problem: mv.MoveProblem, curves: Curves, milp: Milp, lam: float, weeks_left: int
) -> dict[int, float]:
    """Each candidate's and each of my players' first-order value at the program's solution:
    the curves' slopes there times his line over every game he plays (as if he started them
    all), weighted as the program weighs the horizons. A ranking of whom to look at next, not a
    price: the exact prices are the re-solves'."""
    p = problem
    avail = {**p.effective, **p.returns}
    week, later = p.horizons.get("week", ()), p.horizons.get("three", ())
    out: dict[int, float] = {}
    for k, pl in (*p.roster, *p.candidates):
        r = p.rates.get(k)
        total = 0.0
        if "week" in milp.slopes and week:
            n = len(_days(p, k, pl, week[0], avail))
            s = milp.slopes["week"]
            total += (
                lam
                * n
                * sum(s[c] * contribution(r, c, p.points, curves.week_ref.get(c)) for c in s)
            )
        if "later" in milp.slopes and later:
            n = sum(len(_days(p, k, pl, sp, avail)) for sp in later) / len(later)
            s = milp.slopes["later"]
            total += (
                (1 - lam)
                * weeks_left
                * n
                * sum(s[c] * contribution(r, c, p.points, curves.later_ref.get(c)) for c in s)
            )
        out[k] = total
    return out


# --------------------------------------------------------------------------- the choice
def choose(
    w: Weighted, search: Sequence[mv.Move], milp: Milp | None, program_only: bool = False
) -> tuple[str, tuple[mv.Move, ...]]:
    """The set a weight recommends and its source: the program's when it is better on the
    weighted value by more than ``moves.EPS``, both when the two found the same adds with the
    same drops leaving on the same days, the search's otherwise (and whenever the program found
    no set). With ``program_only`` the program's set stands whenever it solved to the gap, and
    the search's is only the fallback for a solve that hit its time limit or failed."""
    search = tuple(search)
    if milp is None or milp.status == FAILED or not mv.feasible(w.problem, milp.moves):
        return SEARCH, search
    eff = w.problem.effective

    def picks(ms: Sequence[mv.Move]) -> tuple[frozenset[int], frozenset[tuple[int, date]]]:
        drops = frozenset((m.drop, eff[m.add]) for m in ms if m.drop is not None)
        return frozenset(m.add for m in ms), drops

    if picks(milp.moves) == picks(search):
        return BOTH, search
    if program_only:
        return (MILP, milp.moves) if milp.status == OPTIMAL else (SEARCH, search)
    if w.value(WEIGHTED, milp.moves) > w.value(WEIGHTED, search) + mv.EPS:
        return MILP, milp.moves
    return SEARCH, search
