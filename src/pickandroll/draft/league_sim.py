"""All-auto league simulation: survival curves and the league's category curve for a draft.

Every team in the simulated draft is one of the drafters in :mod:`.autopick` (``z``, ``adp`` or
``lp`` with a punt of its own), drawn per team from the requested mix. Many such drafts give two
things a session needs before its first pick:

``survival``
    For every player and overall pick, the share of drafts in which the player was still on the
    board (:class:`~pickandroll.availability.survival.SurvivalTable`), the planner's
    replacement for the ADP availability formula.
``curve``
    The mean and spread of each category's team total across every simulated team, the
    ``mu`` and ``sigma`` of the category-win objective
    (:class:`~pickandroll.optim.objective.CategoryCurve`).

Every random draw is keyed by (seed, overall pick) so a simulation is reproducible. Drafts are
independent and run in the shared process pool; ``workers=1`` keeps everything in-process.
``scripts/survival_sim.py`` is the command-line front for the same function.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..availability.survival import SurvivalTable
from ..optim.objective import CategoryCurve
from ..optim.pool import shared_pool
from ..projections.schema import ProjectionSet
from .autopick import (
    STRATEGIES,
    TEAM_PUNTS,
    Strategy,
    latent_slots,
    lp_choices,
    softmax_choice,
    team_label,
)
from .settings import LeagueSettings
from .state import DraftState

NOISE = 1.0
FIRST_SEED = 100_000


@dataclass(frozen=True)
class LeagueSimulation:
    survival: SurvivalTable
    curve: CategoryCurve
    #: One row per simulated team: ``sim``, ``position``, ``strategy``, ``punt`` and the
    #: category totals in z.
    team_totals: pd.DataFrame
    sims: int
    strategies: tuple[Strategy, ...]
    seconds: float


def _rng(seed: int, *keys: int) -> np.random.Generator:
    return np.random.default_rng([seed, *keys])


def draft_once(
    state: DraftState, seed: int, strategies: Sequence[Strategy] = STRATEGIES, noise: float = NOISE
) -> tuple[list[tuple[str, int]], list[dict]]:
    """Run one draft on a fresh state in which every team is a simulated drafter. Returns the
    ``(player, overall)`` record and each team's category totals."""
    if state.picks:
        raise ValueError("draft_once needs a state with no picks")
    if not strategies:
        raise ValueError("at least one drafter strategy is needed")
    n = state.settings.num_teams
    draw = _rng(seed, 7)
    team_strategy = {
        pos: strategies[int(draw.integers(len(strategies)))] for pos in range(1, n + 1)
    }
    cats = set(state.settings.cats)
    options = [p for p, _ in TEAM_PUNTS if p <= cats]
    weights = np.array([w for p, w in TEAM_PUNTS if p <= cats], dtype=float)
    weights /= weights.sum()
    draw = _rng(seed, 999)
    punts = {
        team_label(state, pos): options[int(draw.choice(len(options), p=weights))]
        for pos in range(1, n + 1)
    }
    boards = {
        pos: latent_slots(state, _rng(seed, 100 + pos), noise)
        for pos, strategy in team_strategy.items()
        if strategy == "adp"
    }
    picks: list[tuple[str, int]] = []
    while not state.complete:
        overall = state.next_overall
        _, position = state.owner_of(overall)
        team = team_label(state, position)
        strategy = team_strategy[position]
        d = _rng(seed, overall)
        if strategy == "adp":
            slots = boards[position].reindex(state.available).dropna()
            chosen = str(slots.idxmin())
        elif strategy == "lp":
            chosen = softmax_choice(lp_choices(state, team, punts[team]), d, noise)
        else:
            chosen = softmax_choice(state.z.loc[state.available, "total"], d, noise)
        state.apply_pick(team, chosen)
        picks.append((chosen, overall))
    cols = [c.value for c in state.settings.cats]
    totals = []
    for position in range(1, n + 1):
        team = team_label(state, position)
        roster = [p.player_id for p in state.picks if p.team == team]
        totals.append(
            {
                "sim": seed,
                "position": position,
                "strategy": team_strategy[position],
                "punt": "/".join(
                    c.value for c in sorted(punts[team], key=list(state.settings.cats).index)
                )
                or "-",
                **{c: float(state.z.loc[roster, c].sum()) for c in cols},
            }
        )
    return picks, totals


def _fresh_state(
    settings: LeagueSettings, projections: ProjectionSet, adp: pd.Series | None
) -> DraftState:
    state = DraftState(settings=settings, projections=projections, my_team="me", my_position=1)
    if adp is not None:
        state.set_adp(adp, "given")
    return state


def _job(
    args: tuple[LeagueSettings, ProjectionSet, pd.Series | None, int, tuple[Strategy, ...]],
) -> tuple[int, list[tuple[str, int]], list[dict]]:
    settings, projections, adp, seed, strategies = args
    state = _fresh_state(settings, projections, adp)
    picks, totals = draft_once(state, seed, strategies)
    return seed, picks, totals


def simulate_league(
    settings: LeagueSettings,
    projections: ProjectionSet,
    sims: int,
    adp: pd.Series | None = None,
    strategies: Sequence[Strategy] = STRATEGIES,
    first_seed: int = FIRST_SEED,
    workers: int | None = None,
    progress: Callable[[dict], None] | None = None,
) -> LeagueSimulation:
    """Run ``sims`` all-auto drafts and fit the survival table and the category curve.

    ``adp`` is the market ADP the ``adp`` drafters follow (the projection ranking when
    ``None``). ``progress`` is called after every finished draft with ``done`` and ``total``.
    """
    if sims < 1:
        raise ValueError("sims must be positive")
    strategies = tuple(strategies)
    if not strategies or any(s not in STRATEGIES for s in strategies):
        raise ValueError(f"strategies must be drawn from {STRATEGIES}")
    started = time.perf_counter()
    base = _fresh_state(settings, projections, adp)
    jobs = [(settings, projections, adp, first_seed + i, strategies) for i in range(sims)]
    rows: list[dict] = []
    totals: list[dict] = []

    def collect(
        seed: int, picks: list[tuple[str, int]], team_totals: list[dict], done: int
    ) -> None:
        rows.extend({"sim": seed, "player": p, "overall": k} for p, k in picks)
        totals.extend(team_totals)
        if progress is not None:
            progress({"stage": "survival", "done": done, "total": sims})

    if workers == 1 or sims == 1:
        for done, job in enumerate(jobs, start=1):
            seed, picks, team_totals = _job(job)
            collect(seed, picks, team_totals, done)
    else:
        from concurrent.futures import as_completed

        pool = shared_pool(workers)
        futures = [pool.submit(_job, job) for job in jobs]
        for done, future in enumerate(as_completed(futures), start=1):
            seed, picks, team_totals = future.result()
            collect(seed, picks, team_totals, done)

    picks_df = pd.DataFrame(rows, columns=["sim", "player", "overall"])
    table = SurvivalTable.from_pick_numbers(
        picks_df, total_picks=settings.total_picks, sims=sims, players=base.z.index
    )
    team_totals = pd.DataFrame(totals)
    mix = "/".join(strategies)
    curve = CategoryCurve.from_totals(
        team_totals,
        settings.cats,
        source=f"simulated league ({sims} drafts, {settings.num_teams} teams, {mix} drafters)",
    )
    return LeagueSimulation(
        survival=table,
        curve=curve,
        team_totals=team_totals,
        sims=sims,
        strategies=strategies,
        seconds=time.perf_counter() - started,
    )
