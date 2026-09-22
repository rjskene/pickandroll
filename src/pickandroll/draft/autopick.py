"""Automatic picks for the other teams, for draft simulations.

Three drafters:

``z``
    Take one of the best available players by total z. With ``noise`` the choice is a softmax
    over the top of the board with temperature ``0.5 * noise`` z-points, so the players closest
    to the top get most of the weight and ``noise=0`` is the pure best-z drafter.
``adp``
    Draw a latent draft slot for every available player, ``adp + noise * sd(adp) * eps`` with
    ``eps ~ N(0, 1)``, and take the earliest. With ``noise=1`` the picks follow the spread the
    availability model assumes, so simulated drafts and the planner's survival odds agree.
``lp``
    Each team solves its own roster problem (its picks locked, a punt of its own drawn once per
    simulation) and takes one of the new players from that roster, again softmax-weighted by z.

Positions are ignored by the first two, as they are in a Yahoo draft where the bench absorbs
any surplus; the roster model respects them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

from ..availability.adp import spread_for_adp
from ..optim.roster import RosterProblem, solve_roster
from ..projections.schema import Cat
from .state import DraftState, Pick

Strategy = Literal["z", "adp", "lp"]
STRATEGIES: tuple[Strategy, ...] = ("z", "adp", "lp")

#: Punts a simulated team may commit to, with weights; ``None`` is "no punt".
TEAM_PUNTS: Sequence[tuple[frozenset[Cat], float]] = (
    (frozenset(), 4.0),
    (frozenset({Cat.TOV}), 2.0),
    (frozenset({Cat.FT_PCT}), 1.5),
    (frozenset({Cat.FG_PCT}), 1.0),
    (frozenset({Cat.BLK}), 1.0),
    (frozenset({Cat.AST}), 1.0),
    (frozenset({Cat.THREES}), 0.5),
    (frozenset({Cat.TOV, Cat.FT_PCT}), 0.5),
    (frozenset({Cat.TOV, Cat.BLK}), 0.5),
)
TOP_K = 15
Z_TEMPERATURE = 0.5


def team_label(state: DraftState, position: int) -> str:
    """The team name used for a draft position: my team's name, else ``Team N``."""
    return state.my_team if position == state.my_position else f"Team {position}"


def team_roster(state: DraftState, team: str) -> list[str]:
    return [p.player_id for p in state.picks if p.team == team]


def latent_slots(state: DraftState, rng: np.random.Generator, noise: float = 1.0) -> pd.Series:
    """One noisy draft slot per available player (the ``adp`` drafter)."""
    adp = state.effective_adp().reindex(state.available).astype(float)
    sd = adp.map(spread_for_adp)
    eps = rng.standard_normal(len(adp))
    return adp + noise * sd * eps


def softmax_choice(scores: pd.Series, rng: np.random.Generator, noise: float) -> str:
    """Pick an index from ``scores`` (higher is better): the best with no noise, else a
    softmax over the top with temperature ``Z_TEMPERATURE * noise``."""
    scores = scores.dropna()
    if scores.empty:
        raise ValueError("no players to choose from")
    if noise <= 0:
        return str(scores.idxmax())
    top = scores.nlargest(TOP_K)
    logits = (top.to_numpy(dtype=float) - float(top.max())) / (Z_TEMPERATURE * noise)
    weights = np.exp(logits)
    weights /= weights.sum()
    return str(rng.choice(top.index.to_numpy(), p=weights))


def draw_team_punts(state: DraftState, rng: np.random.Generator) -> dict[str, frozenset[Cat]]:
    """A punt set for every other team, drawn once so a simulated team stays consistent."""
    options = [p for p, _ in TEAM_PUNTS if p <= set(state.settings.cats)]
    weights = np.array([w for p, w in TEAM_PUNTS if p <= set(state.settings.cats)], dtype=float)
    weights /= weights.sum()
    punts = {}
    for position in range(1, state.settings.num_teams + 1):
        if position == state.my_position:
            continue
        punts[team_label(state, position)] = options[rng.choice(len(options), p=weights)]
    return punts


def lp_choices(state: DraftState, team: str, punt: frozenset[Cat]) -> pd.Series:
    """Total z of the players a team's own roster model would add from here."""
    roster = team_roster(state, team)
    remaining = state.settings.roster_size - len(roster)
    if remaining <= 0:
        raise ValueError(f"{team} has a full roster")
    best = state.z.loc[state.available, "total"].nlargest(remaining + state.solver_margin)
    players = list(dict.fromkeys(roster + best.index.tolist()))
    problem = RosterProblem(
        z=state.z.loc[players],
        positions={p: state.positions[p] for p in players},
        slots=state.settings.slots,
        cats=state.settings.cats,
        punt=punt,
        locks=frozenset(roster),
        raw=state.projections.df.loc[players],
    )
    solution = solve_roster(problem, method="milp")
    new = [p for p in solution.players if p not in roster]
    if not new:  # infeasible or degenerate: fall back to the best available
        return best
    return state.z.loc[new, "total"]


def auto_pick(
    state: DraftState,
    rng: np.random.Generator | None = None,
    noise: float = 1.0,
    slots: pd.Series | None = None,
    strategy: Strategy = "z",
    team_punts: dict[str, frozenset[Cat]] | None = None,
) -> Pick:
    """Make the next pick for whichever team is on the clock.

    ``slots`` lets a caller reuse one ADP draw across several picks so that a run of simulated
    picks is internally consistent (a player judged "gone early" stays gone early), and
    ``team_punts`` does the same for the roster model's punts.
    """
    if state.complete:
        raise ValueError("draft is complete")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy!r}")
    rng = rng or np.random.default_rng()
    _, position = state.owner_of(state.next_overall)
    team = team_label(state, position)
    if strategy == "adp":
        if slots is None:
            slots = latent_slots(state, rng, noise)
        slots = slots.reindex(state.available).dropna()
        if slots.empty:
            raise ValueError("no available players")
        chosen = str(slots.idxmin())
    elif strategy == "lp":
        punt = (team_punts or {}).get(team, frozenset())
        chosen = softmax_choice(lp_choices(state, team, punt), rng, noise)
    else:
        chosen = softmax_choice(state.z.loc[state.available, "total"], rng, noise)
    return state.apply_pick(team, chosen)


def simulate(
    state: DraftState,
    count: int | None = None,
    until_my_pick: bool = True,
    noise: float = 1.0,
    seed: int | None = None,
    strategy: Strategy = "z",
) -> list[Pick]:
    """Auto-pick for the other teams until my pick comes up, or for ``count`` picks.

    With ``until_my_pick`` false the simulation also picks for my team with the same drafter,
    which is only useful to fast-forward a mock draft.
    """
    rng = np.random.default_rng(seed)
    slots = latent_slots(state, rng, noise) if strategy == "adp" else None
    team_punts = draw_team_punts(state, rng) if strategy == "lp" else None
    made: list[Pick] = []
    while not state.complete:
        if until_my_pick and state.on_the_clock:
            break
        if count is not None and len(made) >= count:
            break
        made.append(auto_pick(state, rng, noise, slots, strategy, team_punts))
    return made
