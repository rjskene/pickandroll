"""Rolling-horizon draft plan: who to take at each of my remaining picks.

Model 2 from the design doc. Given the players already on my roster (locked), the players gone
(blocked), my remaining overall pick numbers and, for every available player, the probability
they are still on the board at each of those picks, choose one player per pick to maximize the
availability-weighted value of the final roster subject to lineup slots.

Variables
    y[p, j]  binary   player p is the plan for my j-th remaining pick
    x[p, s]  binary   player p fills slot s in the final roster (locked players included)
    t        real     floor on expected active category totals (balance term)

Constraints
    sum_p y[p, j] = 1                       one player per pick
    sum_j y[p, j] = sum_s x[p, s] <= 1      a planned player gets a slot, once
    sum_s x[l, s] = 1                       locked players keep a slot
    sum_p x[p, s] = 1                       every slot filled
Objective
    max (1 - balance) * sum_c T_c + balance * t,
    T_c = sum_{p,j} z[p, c] A[p, j] y[p, j] + sum_l z[l, c]
    or, with a category curve, max sum_c Phi((T_c - mu_c) / sigma_c) in piecewise-linear form
    (see ``optim.objective``): the expected number of categories won by the expected totals.

Only the first pick of the plan is acted on. After the next real pick the state changes and the
plan is re-solved ("roll"). The punt is fixed here (and empty on the product's default path);
:func:`punt_scan_horizon` enumerates punt sets for studies that still want one.

Pricing an alternative first pick is a re-solve with that player forced first
(:func:`horizon_pick_pool`, in a process pool). :func:`first_order_prices` gives the same answer
to first order in microseconds from the objective's slopes, so every candidate has a price
before the exact solves land. :func:`scenarios_if_gone` answers "and if he is taken before my
turn?" for the players most likely to go, so the next answer is ready before it is needed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations

import pandas as pd
import pulp

from ..projections.schema import NINE_CAT, Cat
from .objective import CategoryCurve, curve_objective
from .pool import shared_pool
from .roster import Slot, _safe, yahoo_default_slots


@dataclass
class HorizonProblem:
    z: pd.DataFrame
    positions: Mapping[str, Sequence[str]]
    picks: Sequence[int]
    availability: pd.DataFrame
    slots: Sequence[Slot] = field(default_factory=yahoo_default_slots)
    cats: Sequence[Cat] = NINE_CAT
    punt: frozenset[Cat] = frozenset()
    balance: float = 0.0
    weights: Mapping[Cat, float] | None = None
    locks: frozenset[str] = frozenset()
    blocks: frozenset[str] = frozenset()
    force_first: str | None = None
    min_availability: float = 0.005
    min_candidates: int = 25
    #: Keep only this many candidates per pick, the best by availability-weighted total z.
    #: Shrinks the model a lot at early picks with hardly any change in the plan; the curve
    #: objective needs it to solve in reasonable time.
    max_candidates: int | None = None
    curve: CategoryCurve | None = None

    def __post_init__(self) -> None:
        open_slots = len(self.slots) - len(self.locks)
        if len(self.picks) != open_slots:
            raise ValueError(
                f"{len(self.picks)} remaining picks but {open_slots} open roster slots"
            )
        if not 0.0 <= self.balance <= 1.0:
            raise ValueError("balance must be between 0 and 1")
        if self.curve is not None and self.balance > 0.0:
            raise ValueError("a category curve and a balance term cannot be combined")
        if self.curve is not None and any(c not in self.curve.mu for c in self.cats):
            raise ValueError("curve lacks a category")
        if self.locks & self.blocks:
            raise ValueError("a player cannot be both locked and blocked")
        missing = [k for k in self.picks if k not in self.availability.columns]
        if missing:
            raise ValueError(f"availability lacks columns for picks {missing}")
        if self.force_first is not None and self.force_first not in self.z.index:
            raise ValueError(f"unknown player {self.force_first!r}")

    @property
    def available(self) -> list[str]:
        return [p for p in self.z.index if p not in self.blocks and p not in self.locks]

    @property
    def active_cats(self) -> list[Cat]:
        return [c for c in self.cats if c not in self.punt]


@dataclass
class HorizonSolution:
    status: str
    objective: float
    plan: pd.DataFrame
    roster: pd.DataFrame
    expected_totals: pd.Series
    min_active_total: float
    solve_seconds: float
    #: Win probability of each expected total under the problem's curve (punted ones zero).
    expected_wins: pd.Series | None = None
    #: Marginal value of one more z-point in each category at the expected totals: the curve's
    #: slope there, or one everywhere for the plain sum. Punted categories are zero.
    slopes: pd.Series | None = None
    #: The solver stopped at its time limit and this is the incumbent, not a proven optimum.
    time_limited: bool = False

    @property
    def first_pick(self) -> str | None:
        return None if self.plan.empty else str(self.plan.iloc[0]["player"])

    @property
    def wins(self) -> float | None:
        """Expected categories won, ``None`` without a curve."""
        return None if self.expected_wins is None else float(self.expected_wins.sum())


def _values(problem: HorizonProblem) -> pd.DataFrame:
    cols = [c.value for c in problem.active_cats]
    value = problem.z[cols].astype(float).copy()
    if problem.weights:
        for cat, wgt in problem.weights.items():
            if cat.value in value:
                value[cat.value] *= float(wgt)
    return value


def build(problem: HorizonProblem) -> tuple[pulp.LpProblem, dict]:
    avail = problem.available
    locked = sorted(problem.locks)
    everyone = avail + locked
    picks = list(problem.picks)
    slots = list(problem.slots)
    value = _values(problem)
    cats = problem.active_cats
    pos = {p: set(problem.positions[p]) for p in everyone}
    A = problem.availability.reindex(index=avail, columns=picks).fillna(0.0)

    model = pulp.LpProblem("horizon", pulp.LpMaximize)

    # Plan variables only where the player has a real chance of being there. Every pick keeps
    # at least ``min_candidates`` options so late picks in a thin pool stay feasible.
    y: dict[tuple[str, int], pulp.LpVariable] = {}
    total = problem.z["total"].astype(float).reindex(avail)
    for j, k in enumerate(picks):
        column = A[k]
        keep = set(column[column >= problem.min_availability].index)
        if len(keep) < problem.min_candidates:
            keep |= set(column.nlargest(problem.min_candidates).index)
        cap = problem.max_candidates
        if cap is not None and len(keep) > max(cap, problem.min_candidates):
            weighted = (total * column).reindex(list(keep))
            keep = set(weighted.nlargest(max(cap, problem.min_candidates)).index)
        if j == 0 and problem.force_first is not None:
            keep.add(problem.force_first)
        for p in avail:
            if p in keep:
                y[p, j] = model.add_variable(f"y_{_safe(p)}_{j}", cat=pulp.LpBinary)
    x: dict[tuple[str, int], pulp.LpVariable] = {}
    for p in everyone:
        for i, slot in enumerate(slots):
            if slot.accepts(pos[p]):
                x[p, i] = model.add_variable(f"x_{_safe(p)}_{i}", cat=pulp.LpBinary)

    on = {p: pulp.lpSum(x[p, i] for i in range(len(slots)) if (p, i) in x) for p in everyone}
    for j in range(len(picks)):
        model += pulp.lpSum(y[p, j] for p in avail if (p, j) in y) == 1, f"pick_{j}"
    for p in avail:
        planned = pulp.lpSum(y[p, j] for j in range(len(picks)) if (p, j) in y)
        model += planned == on[p], f"link_{_safe(p)}"
        model += on[p] <= 1, f"once_{_safe(p)}"
    for p in locked:
        model += on[p] == 1, f"lock_{_safe(p)}"
    for i, slot in enumerate(slots):
        model += pulp.lpSum(x[p, i] for p in everyone if (p, i) in x) == 1, f"fill_{slot.name}"
    if problem.force_first is not None:
        model += y[problem.force_first, 0] == 1, "force_first"

    totals: dict[Cat, pulp.LpAffineExpression] = {}
    for c in cats:
        terms = [
            float(value.at[p, c.value]) * float(A.at[p, picks[j]]) * var
            for (p, j), var in y.items()
        ]
        locked_total = float(value.loc[locked, c.value].sum()) if locked else 0.0
        totals[c] = pulp.lpSum(terms) + locked_total

    bound = max(float(value[c.value].abs().sum()) for c in cats) + 1.0 if cats else 1.0
    t = model.add_variable("t_min_total", lowBound=-bound, upBound=bound)
    if problem.balance > 0.0:
        for c in cats:
            model += t <= totals[c], f"floor_{c.value}"
    else:
        model += t == 0, "t_unused"

    if problem.curve is not None:
        model += curve_objective(model, totals, problem.curve, value, len(slots), cats)
    else:
        model += (1.0 - problem.balance) * pulp.lpSum(totals.values()) + problem.balance * t
    return model, {"y": y, "x": x, "totals": totals, "value": value, "A": A}


def solve_horizon(
    problem: HorizonProblem, time_limit: float = 10.0, gap: float = 0.0
) -> HorizonSolution:
    model, parts = build(problem)
    start = time.perf_counter()
    model.solve(pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=gap))
    seconds = time.perf_counter() - start
    status = pulp.LpStatus[model.status]
    if status not in {"Optimal", "Not Solved"} or model.objective.value() is None:
        raise RuntimeError(f"horizon solve failed with status {status}")

    picks = list(problem.picks)
    plan_rows = []
    for (p, j), var in parts["y"].items():
        if var.value() is not None and var.value() > 0.5:
            plan_rows.append(
                {"pick": picks[j], "player": p, "availability": float(parts["A"].at[p, picks[j]])}
            )
    plan = pd.DataFrame(plan_rows, columns=["pick", "player", "availability"]).sort_values("pick")
    plan = plan.reset_index(drop=True)

    slots = list(problem.slots)
    roster_rows = []
    for (p, i), var in parts["x"].items():
        if var.value() is not None and var.value() > 0.5:
            roster_rows.append(
                {"player": p, "slot": slots[i].name, "slot_index": i, "locked": p in problem.locks}
            )
    roster = pd.DataFrame(roster_rows).sort_values("slot_index").reset_index(drop=True)

    # Expected totals for every category, punted ones included, so callers can show the
    # whole profile; the objective and the balance floor only see the active ones.
    weights = dict(problem.weights or {})
    expected = {}
    for c in problem.cats:
        col = problem.z[c.value].astype(float) * float(weights.get(c, 1.0))
        planned = sum(float(col[r.player]) * float(r.availability) for r in plan.itertuples())
        locked_total = float(col[list(problem.locks)].sum()) if problem.locks else 0.0
        expected[c] = planned + locked_total
    expected = pd.Series(expected)
    active = [c for c in problem.cats if c not in problem.punt]
    min_active = float(expected[active].min()) if active else float("nan")
    wins = None
    if problem.curve is not None:
        wins = pd.Series(
            {
                c: (problem.curve.probability(c, float(expected[c])) if c in active else 0.0)
                for c in problem.cats
            }
        )
        slopes = pd.Series(
            {
                c: (problem.curve.slope(c, float(expected[c])) if c in active else 0.0)
                for c in problem.cats
            }
        )
    else:
        slopes = pd.Series({c: (1.0 if c in active else 0.0) for c in problem.cats})
    return HorizonSolution(
        status=status,
        objective=float(pulp.value(model.objective)),
        plan=plan,
        roster=roster,
        expected_totals=expected,
        min_active_total=min_active,
        solve_seconds=seconds,
        expected_wins=wins,
        slopes=slopes,
        time_limited=status == "Not Solved" or seconds >= 0.97 * time_limit,
    )


def first_order_prices(
    problem: HorizonProblem, solution: HorizonSolution, candidates: Sequence[str]
) -> pd.Series:
    """Objective lost, to first order, by taking each candidate with my next pick instead of
    the plan's first pick and keeping the rest of the plan.

    The change in each category total is the candidate's availability-weighted value minus the
    planned player's; the curve's slope at the expected totals converts it to categories won
    (or to plain z for the sum objective). The exact price re-solves the whole plan and
    differs a little: the later picks adjust, and a candidate the plan already had for a
    later pick leaves a hole there. This one is instant and covers the whole board.
    Candidates not in the model have no price (NaN).
    """
    first = solution.first_pick
    if first is None or solution.slopes is None:
        return pd.Series(float("nan"), index=list(candidates), dtype=float)
    pick = problem.picks[0]
    value = _values(problem)
    cols = [c.value for c in problem.active_cats]
    slopes = pd.Series({c.value: float(solution.slopes[c]) for c in problem.active_cats})
    avail = problem.availability[pick].reindex(value.index).fillna(0.0).clip(0.0, 1.0)
    weighted = value[cols].mul(avail, axis=0).mul(slopes, axis=1).sum(axis=1)
    base = float(weighted.get(first, float("nan")))
    prices = (base - weighted.reindex(list(candidates))).clip(lower=0.0)
    prices.name = "cost_first_order"
    return prices.astype(float)


def _solve_forced(
    args: tuple[HorizonProblem, str, float, float],
) -> tuple[str, HorizonSolution | None]:
    problem, candidate, time_limit, gap = args
    try:
        return candidate, solve_horizon(
            replace(problem, force_first=candidate), time_limit=time_limit, gap=gap
        )
    except (RuntimeError, ValueError):
        return candidate, None


def horizon_pick_pool(
    problem: HorizonProblem,
    candidates: Sequence[str],
    time_limit: float = 5.0,
    gap: float = 0.0,
    base: HorizonSolution | None = None,
    workers: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> pd.DataFrame:
    """Price candidates for the next pick by forcing each to be the plan's first pick.

    ``cost_vs_best`` includes the risk of waiting: a player the plan would take later at high
    probability costs little to skip now, a player likely to vanish costs a lot. Candidate
    solves are independent and run in a process pool unless ``workers=1``. ``progress`` is
    called with each priced candidate as it finishes.
    """
    if base is None:
        base = solve_horizon(problem, time_limit=time_limit, gap=gap)
    next_pick = problem.picks[1] if len(problem.picks) > 1 else None
    jobs = [(problem, c, time_limit, gap) for c in candidates]
    first_order = first_order_prices(problem, base, candidates)

    def row_for(c: str, sol: HorizonSolution) -> dict:
        objective = sol.objective
        if c == base.first_pick:
            # Same problem as the base plan: a time-limited re-solve never beats its incumbent.
            objective = max(objective, base.objective)
        return {
            "player": c,
            "objective": objective,
            "cost_vs_best": max(0.0, base.objective - objective),
            "cost_first_order": float(first_order.get(c, float("nan"))),
            "p_available_first": float(problem.availability.at[c, problem.picks[0]]),
            "p_available_next": (
                float(problem.availability.at[c, next_pick]) if next_pick is not None else 0.0
            ),
            "min_active_total": sol.min_active_total,
            "time_limited": sol.time_limited,
        }

    rows = []

    def collect(c: str, sol: HorizonSolution | None, done: int) -> None:
        if sol is not None:
            rows.append(row_for(c, sol))
        if progress is not None:
            progress(
                {
                    "stage": "candidates",
                    "done": done,
                    "total": len(jobs),
                    "candidate": rows[-1] if sol is not None else {"player": c, "failed": True},
                }
            )

    if workers == 1 or len(jobs) <= 1:
        for done, job in enumerate(jobs, start=1):
            c, sol = _solve_forced(job)
            collect(c, sol, done)
    else:
        from concurrent.futures import as_completed

        pool = shared_pool(workers)
        futures = [pool.submit(_solve_forced, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), start=1):
            c, sol = future.result()
            collect(c, sol, done)

    out = pd.DataFrame(
        rows,
        columns=[
            "player",
            "objective",
            "cost_vs_best",
            "cost_first_order",
            "p_available_first",
            "p_available_next",
            "min_active_total",
            "time_limited",
        ],
    )
    if not out.empty:
        # A forced re-solve can beat a time-limited base plan; the best solve seen is the
        # reference, so the top candidate always costs nothing.
        best = max(base.objective, float(out["objective"].max()))
        out["cost_vs_best"] = (best - out["objective"]).clip(lower=0.0)
    return out.sort_values("objective", ascending=False).reset_index(drop=True)


def _solve_blocked(
    args: tuple[HorizonProblem, str, float, float],
) -> tuple[str, HorizonSolution | None]:
    problem, gone, time_limit, gap = args
    try:
        return gone, solve_horizon(
            replace(problem, blocks=problem.blocks | {gone}), time_limit=time_limit, gap=gap
        )
    except (RuntimeError, ValueError):
        return gone, None


def scenarios_if_gone(
    problem: HorizonProblem,
    players: Sequence[str],
    time_limit: float = 5.0,
    gap: float = 0.0,
    workers: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> list[dict]:
    """For each player, the plan if that player is taken before my next pick: who to take
    instead and what the plan is then worth. Solved in the shared process pool."""
    jobs = [(problem, p, time_limit, gap) for p in players if p in problem.z.index]
    results: list[dict] = []

    def collect(gone: str, sol: HorizonSolution | None, done: int) -> None:
        if sol is not None:
            results.append(
                {
                    "gone": gone,
                    "pick": sol.first_pick,
                    "objective": sol.objective,
                    "wins": sol.wins,
                    "time_limited": sol.time_limited,
                }
            )
        if progress is not None:
            progress({"stage": "scenarios", "done": done, "total": len(jobs), "gone": gone})

    if workers == 1 or len(jobs) <= 1:
        for done, job in enumerate(jobs, start=1):
            gone, sol = _solve_blocked(job)
            collect(gone, sol, done)
    else:
        from concurrent.futures import as_completed

        pool = shared_pool(workers)
        futures = {pool.submit(_solve_blocked, job): job[1] for job in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            gone, sol = future.result()
            collect(gone, sol, done)
    order = {p: i for i, p in enumerate(players)}
    return sorted(results, key=lambda r: order.get(r["gone"], len(order)))


def punt_scan_horizon(
    problem: HorizonProblem, max_punts: int = 2, time_limit: float = 10.0, gap: float = 0.0
) -> list[tuple[frozenset[Cat], HorizonSolution]]:
    """Solve the plan under every punt set up to ``max_punts``, best first."""
    results = []
    for k in range(max_punts + 1):
        for combo in combinations(problem.cats, k):
            punt = frozenset(combo)
            sol = solve_horizon(replace(problem, punt=punt), time_limit=time_limit, gap=gap)
            results.append((punt, sol))
    return sorted(results, key=lambda item: item[1].objective, reverse=True)
