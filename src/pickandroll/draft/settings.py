"""League and draft settings, and snake-draft pick arithmetic."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..optim.roster import Slot, yahoo_default_slots
from ..projections.schema import NINE_CAT, Cat


@dataclass(frozen=True)
class LeagueSettings:
    num_teams: int = 12
    slots: tuple[Slot, ...] = field(default_factory=lambda: tuple(yahoo_default_slots()))
    cats: tuple[Cat, ...] = NINE_CAT
    draft_type: str = "snake"

    @property
    def roster_size(self) -> int:
        return len(self.slots)

    @property
    def total_picks(self) -> int:
        return self.num_teams * self.roster_size


def snake_picks(num_teams: int, position: int, rounds: int) -> list[int]:
    """Overall pick numbers owned by ``position`` (1-based) in a snake draft."""
    if not 1 <= position <= num_teams:
        raise ValueError("position must be between 1 and num_teams")
    picks = []
    for rnd in range(1, rounds + 1):
        slot = position if rnd % 2 == 1 else num_teams - position + 1
        picks.append((rnd - 1) * num_teams + slot)
    return picks


def pick_owner(num_teams: int, overall_pick: int) -> tuple[int, int]:
    """Return ``(round, draft_position)`` that owns an overall pick number in a snake draft."""
    if overall_pick < 1:
        raise ValueError("overall_pick must be positive")
    rnd, idx = divmod(overall_pick - 1, num_teams)
    position = idx + 1 if rnd % 2 == 0 else num_teams - idx
    return rnd + 1, position
