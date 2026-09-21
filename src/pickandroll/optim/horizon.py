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

Only the first pick of the plan is acted on. After the next real pick the state changes and the
plan is re-solved ("roll"). The punt is fixed here; automatic punt selection enumerates punt
sets with :func:`punt_scan_horizon`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations

import pandas as pd
import pulp

from ..projections.schema import NINE_CAT, Cat
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

    def __post_init__(self) -> None:
        open_slots = len(self.slots) - len(self.locks)
        if len(self.picks) != open_slots:
            raise ValueError(
                f"{len(self.picks)} remaining picks but {open_slots} open roster slots"
            )
        if not 0.0 <= self.balance <= 1.0:
            raise ValueError("balance must be between 0 and 1")
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

    @property
    def first_pick(self) -> str | None:
        return None if self.plan.empty else str(self.plan.iloc[0]["player"])


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
    for j, k in enumerate(picks):
        column = A[k]
        keep = set(column[column >= problem.min_availability].index)
        if len(keep) < problem.min_candidates:
            keep |= set(column.nlargest(problem.min_candidates).index)
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

    expected = pd.Series({c: float(pulp.value(expr)) for c, expr in parts["totals"].items()})
    min_active = float(expected.min()) if len(expected) else float("nan")
    return HorizonSolution(
        status=status,
        objective=float(pulp.value(model.objective)),
        plan=plan,
        roster=roster,
        expected_totals=expected,
        min_active_total=min_active,
        solve_seconds=seconds,
    )


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
) -> pd.DataFrame:
    """Price candidates for the next pick by forcing each to be the plan's first pick.

    ``cost_vs_best`` includes the risk of waiting: a player the plan would take later at high
    probability costs little to skip now, a player likely to vanish costs a lot. Candidate
    solves are independent and run in a process pool unless ``workers=1``.
    """
    if base is None:
        base = solve_horizon(problem, time_limit=time_limit, gap=gap)
    next_pick = problem.picks[1] if len(problem.picks) > 1 else None
    jobs = [(problem, c, time_limit, gap) for c in candidates]
    if workers == 1 or len(jobs) <= 1:
        results = [_solve_forced(job) for job in jobs]
    else:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_solve_forced, jobs))
    rows = []
    for c, sol in results:
        if sol is None:
            continue
        rows.append(
            {
                "player": c,
                "objective": sol.objective,
                "cost_vs_best": max(0.0, base.objective - sol.objective),
                "p_available_first": float(problem.availability.at[c, problem.picks[0]]),
                "p_available_next": (
                    float(problem.availability.at[c, next_pick]) if next_pick is not None else 0.0
                ),
                "min_active_total": sol.min_active_total,
            }
        )
    out = pd.DataFrame(
        rows,
        columns=[
            "player",
            "objective",
            "cost_vs_best",
            "p_available_first",
            "p_available_next",
            "min_active_total",
        ],
    )
    return out.sort_values("objective", ascending=False).reset_index(drop=True)


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
