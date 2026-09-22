"""Automatic picks for the other teams, for draft simulations.

Each simulated pick draws a latent draft slot for every available player,
``adp + noise * sd(adp) * eps`` with ``eps ~ N(0, 1)``, and takes the player with the earliest
slot. With ``noise=0`` this is the naive "best ADP available" drafter; with ``noise=1`` the
picks follow the same spread the availability model assumes, so simulated drafts and the
planner's survival odds agree. Positions are ignored, as they are in a Yahoo draft where the
bench absorbs any surplus.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..availability.adp import spread_for_adp
from .state import DraftState, Pick


def team_label(state: DraftState, position: int) -> str:
    """The team name used for a draft position: my team's name, else ``Team N``."""
    return state.my_team if position == state.my_position else f"Team {position}"


def latent_slots(state: DraftState, rng: np.random.Generator, noise: float = 1.0) -> pd.Series:
    """One noisy draft slot per available player."""
    adp = state.effective_adp().reindex(state.available).astype(float)
    sd = adp.map(spread_for_adp)
    eps = rng.standard_normal(len(adp))
    return adp + noise * sd * eps


def auto_pick(
    state: DraftState,
    rng: np.random.Generator | None = None,
    noise: float = 1.0,
    slots: pd.Series | None = None,
) -> Pick:
    """Make the next pick for whichever team is on the clock.

    ``slots`` lets a caller reuse one draw across several picks so that a run of simulated
    picks is internally consistent (a player judged "gone early" stays gone early).
    """
    if state.complete:
        raise ValueError("draft is complete")
    if slots is None:
        slots = latent_slots(state, rng or np.random.default_rng(), noise)
    slots = slots.reindex(state.available).dropna()
    if slots.empty:
        raise ValueError("no available players")
    _, position = state.owner_of(state.next_overall)
    return state.apply_pick(team_label(state, position), str(slots.idxmin()))


def simulate(
    state: DraftState,
    count: int | None = None,
    until_my_pick: bool = True,
    noise: float = 1.0,
    seed: int | None = None,
) -> list[Pick]:
    """Auto-pick for the other teams until my pick comes up, or for ``count`` picks.

    With ``until_my_pick`` false the simulation also picks for my team (by ADP, not the
    solver), which is only useful to fast-forward a mock draft.
    """
    rng = np.random.default_rng(seed)
    slots = latent_slots(state, rng, noise)
    made: list[Pick] = []
    while not state.complete:
        if until_my_pick and state.on_the_clock:
            break
        if count is not None and len(made) >= count:
            break
        made.append(auto_pick(state, rng, noise, slots))
    return made
