"""Roster MILP: choose the best legal roster from a pool of players.

Decision variables
    x[p, s]  binary   player p fills roster slot s (created only for eligible pairs)
    y[c]     binary   category c is *active* (not punted); constants when the punt is fixed
    u[c]     real     active contribution of category c, equal to T_c * y[c] where
                      T_c = sum_p z[p, c] * x_p is the team total (x_p = sum_s x[p, s])
    t        real     floor on the team total of every active category (max-min term)

Objective
    maximize (1 - balance) * sum_c u[c] + balance * t

Constraints
    each slot filled exactly once, each player at most once
    locks on, blocks off
    sum_c y[c] >= n_cats - max_punts
    u[c] = T_c * y[c] by big-M:  -M y <= u <= M y,  T - M (1 - y) <= u <= T + M (1 - y)
    t <= T_c + M_c (1 - y_c)
    optional: team percentage floors  sum_p x_p (makes_p - floor * attempts_p) >= -M (1 - y_c)
    optional: minimum projected games sum_p x_p games_p >= min_games

The product of a binary with a bounded team total is linearized per category (nine auxiliary
variables) rather than per player and category, which keeps the model small enough to solve in
well under a second during a draft.

``z`` must already be sign-adjusted so higher is better everywhere (see ``projections.zscores``).
Category weights scale the value columns. Availability weights, when given, scale a player's
value by the probability they are still on the board, which is how a planning solve for later
picks discounts players who will not last.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

import pandas as pd
import pulp

from ..projections.schema import NINE_CAT, PCT_CATS, PCT_COMPONENTS, POSITIONS, Cat

GUARDS = frozenset({"PG", "SG"})
FORWARDS = frozenset({"SF", "PF"})
ANY = frozenset(POSITIONS)


@dataclass(frozen=True)
class Slot:
    name: str
    eligible: frozenset[str] = ANY

    def accepts(self, positions: Iterable[str]) -> bool:
        return bool(self.eligible & set(positions))


def yahoo_default_slots(bench: int = 3) -> list[Slot]:
    """Yahoo's default NBA lineup: PG, SG, G, SF, PF, F, C, C, UTIL, UTIL plus bench."""
    slots = [
        Slot("PG", frozenset({"PG"})),
        Slot("SG", frozenset({"SG"})),
        Slot("G", GUARDS),
        Slot("SF", frozenset({"SF"})),
        Slot("PF", frozenset({"PF"})),
        Slot("F", FORWARDS),
        Slot("C1", frozenset({"C"})),
        Slot("C2", frozenset({"C"})),
        Slot("UTIL1", ANY),
        Slot("UTIL2", ANY),
    ]
    slots += [Slot(f"BN{i + 1}", ANY) for i in range(bench)]
    return slots


@dataclass
class RosterProblem:
    z: pd.DataFrame
    positions: Mapping[str, Sequence[str]]
    slots: Sequence[Slot] = field(default_factory=yahoo_default_slots)
    cats: Sequence[Cat] = NINE_CAT
    punt: frozenset[Cat] | None = None
    max_punts: int = 2
    balance: float = 0.0
    weights: Mapping[Cat, float] | None = None
    locks: frozenset[str] = frozenset()
    blocks: frozenset[str] = frozenset()
    raw: pd.DataFrame | None = None
    pct_floors: Mapping[Cat, float] | None = None
    min_games: float | None = None
    availability: pd.Series | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.balance <= 1.0:
            raise ValueError("balance must be between 0 and 1")
        if self.punt is not None and not set(self.punt) <= set(self.cats):
            raise ValueError("punt contains categories not in cats")
        unknown = [p for p in self.locks | self.blocks if p not in self.z.index]
        if unknown:
            raise ValueError(f"locked/blocked players not in pool: {unknown}")
        if self.locks & self.blocks:
            raise ValueError("a player cannot be both locked and blocked")
        if self.pct_floors and self.raw is None:
            raise ValueError("pct_floors requires raw makes/attempts in `raw`")
        if self.min_games is not None and self.raw is None:
            raise ValueError("min_games requires `raw` with a games column")

    @property
    def players(self) -> list[str]:
        return [p for p in self.z.index if p not in self.blocks]


@dataclass
class RosterSolution:
    status: str
    objective: float
    roster: pd.DataFrame
    active_cats: tuple[Cat, ...]
    punted: tuple[Cat, ...]
    cat_totals: pd.Series
    min_active_total: float
    solve_seconds: float

    @property
    def players(self) -> list[str]:
        return self.roster["player"].tolist()


def _value(problem: RosterProblem) -> pd.DataFrame:
    cols = [c.value for c in problem.cats]
    value = problem.z.loc[problem.players, cols].astype(float).copy()
    if problem.weights:
        for cat, wgt in problem.weights.items():
            if cat.value in value:
                value[cat.value] *= float(wgt)
    if problem.availability is not None:
        avail = problem.availability.reindex(value.index).fillna(1.0).clip(0.0, 1.0)
        value = value.mul(avail, axis=0)
    return value


def build(problem: RosterProblem) -> tuple[pulp.LpProblem, dict]:
    """Build the PuLP model. Returned dict holds the variables for inspection and tests."""
    players = problem.players
    value = _value(problem)
    cats = list(problem.cats)
    slots = list(problem.slots)
    pos = {p: set(problem.positions[p]) for p in players}

    model = pulp.LpProblem("roster", pulp.LpMaximize)

    x: dict[tuple[str, int], pulp.LpVariable] = {}
    for p in players:
        for i, slot in enumerate(slots):
            if slot.accepts(pos[p]):
                x[p, i] = model.add_variable(f"x_{_safe(p)}_{i}", cat=pulp.LpBinary)
    on = {p: pulp.lpSum(x[p, i] for i in range(len(slots)) if (p, i) in x) for p in players}

    for i, slot in enumerate(slots):
        model += pulp.lpSum(x[p, i] for p in players if (p, i) in x) == 1, f"fill_{slot.name}"
    for p in players:
        model += on[p] <= 1, f"once_{_safe(p)}"
    for p in problem.locks:
        model += on[p] == 1, f"lock_{_safe(p)}"

    auto_punt = problem.punt is None
    y: dict[Cat, pulp.LpVariable | int] = {}
    if auto_punt:
        for c in cats:
            y[c] = model.add_variable(f"y_{c.value}", cat=pulp.LpBinary)
        model += pulp.lpSum(y[c] for c in cats) >= len(cats) - problem.max_punts, "max_punts"
    else:
        for c in cats:
            y[c] = 0 if c in problem.punt else 1

    totals = {c: pulp.lpSum(value.at[p, c.value] * on[p] for p in players) for c in cats}
    big_m = {c: float(value[c.value].abs().sum()) + 1.0 for c in cats}

    # u[c] = totals[c] * y[c]
    u: dict[Cat, pulp.LpVariable | pulp.LpAffineExpression] = {}
    for c in cats:
        if auto_punt:
            u[c] = model.add_variable(f"u_{c.value}", lowBound=-big_m[c], upBound=big_m[c])
            model += u[c] <= big_m[c] * y[c], f"u_off_hi_{c.value}"
            model += u[c] >= -big_m[c] * y[c], f"u_off_lo_{c.value}"
            model += u[c] <= totals[c] + big_m[c] * (1 - y[c]), f"u_on_hi_{c.value}"
            model += u[c] >= totals[c] - big_m[c] * (1 - y[c]), f"u_on_lo_{c.value}"
        else:
            u[c] = totals[c] if y[c] else pulp.lpSum([])

    t = model.add_variable(
        "t_min_total", lowBound=-max(big_m.values()), upBound=max(big_m.values())
    )
    if problem.balance > 0.0:
        for c in cats:
            if auto_punt:
                model += t <= totals[c] + big_m[c] * (1 - y[c]), f"floor_{c.value}"
            elif y[c]:
                model += t <= totals[c], f"floor_{c.value}"
    else:
        model += t == 0, "t_unused"

    if problem.pct_floors:
        raw = problem.raw
        for c, floor in problem.pct_floors.items():
            if c not in PCT_CATS or c not in cats:
                raise ValueError(f"pct floor on non-percentage category {c}")
            makes, attempts = PCT_COMPONENTS[c]
            margin = pulp.lpSum(
                float(raw.at[p, makes] - floor * raw.at[p, attempts]) * on[p] for p in players
            )
            slack_m = float(raw.loc[players, attempts].abs().sum()) + 1.0
            model += margin >= -slack_m * (1 - y[c]), f"pct_floor_{c.value}"

    if problem.min_games is not None:
        raw = problem.raw
        model += (
            pulp.lpSum(float(raw.at[p, "games"]) * on[p] for p in players) >= problem.min_games,
            "min_games",
        )

    model += (1.0 - problem.balance) * pulp.lpSum(u[c] for c in cats) + problem.balance * t
    return model, {"x": x, "y": y, "u": u, "t": t, "on": on, "totals": totals, "value": value}


def solve_roster(
    problem: RosterProblem,
    time_limit: float = 10.0,
    gap: float = 0.0,
    threads: int | None = None,
) -> RosterSolution:
    model, parts = build(problem)
    solver = pulp.HiGHS(msg=False, timeLimit=time_limit, gapRel=gap, threads=threads)
    start = time.perf_counter()
    model.solve(solver)
    seconds = time.perf_counter() - start
    status = pulp.LpStatus[model.status]
    if status not in {"Optimal", "Not Solved"} or model.objective.value() is None:
        raise RuntimeError(f"roster solve failed with status {status}")

    slots = list(problem.slots)
    rows = []
    for (p, i), var in parts["x"].items():
        if var.value() is not None and var.value() > 0.5:
            rows.append({"player": p, "slot": slots[i].name, "slot_index": i})
    roster = pd.DataFrame(rows).sort_values("slot_index").reset_index(drop=True)

    active = tuple(c for c in problem.cats if _is_on(parts["y"][c]))
    punted = tuple(c for c in problem.cats if c not in active)
    chosen = roster["player"].tolist()
    cat_totals = parts["value"].loc[chosen].sum(axis=0)
    cat_totals.index = [Cat(c) for c in cat_totals.index]
    min_active = float(cat_totals[list(active)].min()) if active else float("nan")

    return RosterSolution(
        status=status,
        objective=float(pulp.value(model.objective)),
        roster=roster,
        active_cats=active,
        punted=punted,
        cat_totals=cat_totals,
        min_active_total=min_active,
        solve_seconds=seconds,
    )


def pick_pool(
    problem: RosterProblem,
    candidates: Sequence[str],
    time_limit: float = 5.0,
    gap: float = 0.0,
) -> pd.DataFrame:
    """Rank candidate players by the best roster objective when each is forced onto the roster.

    The difference from the unconstrained optimum is the price of taking that player now.
    """
    base = solve_roster(problem, time_limit=time_limit, gap=gap)
    rows = []
    for p in candidates:
        forced = replace(problem, locks=problem.locks | {p})
        try:
            sol = solve_roster(forced, time_limit=time_limit, gap=gap)
        except RuntimeError:
            continue
        rows.append(
            {
                "player": p,
                "objective": sol.objective,
                "cost_vs_best": max(0.0, base.objective - sol.objective),
                "punted": "/".join(c.value for c in sol.punted) or "-",
                "min_active_total": sol.min_active_total,
            }
        )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("objective", ascending=False).reset_index(drop=True)
    return out


def _is_on(flag: pulp.LpVariable | int) -> bool:
    if isinstance(flag, int):
        return bool(flag)
    return round(flag.value() or 0) == 1


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(name))
