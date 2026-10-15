"""League and draft settings, and the pick arithmetic of a snake draft, with or without
traded picks.

A pure snake is arithmetic: :func:`snake_picks` and :func:`pick_owner`. A league with traded
picks is a snake plus a map, the draft position that owns each overall pick
(:func:`check_pick_owners`, :func:`position_picks`, :func:`position_pick`). Everything that
needs an owner takes the map first and falls back to the snake."""

from __future__ import annotations

from collections.abc import Sequence
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


def round_of(num_teams: int, overall_pick: int) -> int:
    """The round an overall pick falls in (the same with or without traded picks)."""
    if overall_pick < 1:
        raise ValueError("overall_pick must be positive")
    return (overall_pick - 1) // num_teams + 1


def snake_owners(num_teams: int, rounds: int) -> tuple[int, ...]:
    """The draft position on every overall pick of a pure snake, pick 1 first."""
    return tuple(pick_owner(num_teams, k)[1] for k in range(1, num_teams * rounds + 1))


def check_pick_owners(
    owners: Sequence[int] | None, num_teams: int, rounds: int
) -> tuple[int, ...] | None:
    """A pick-owner map as the state keeps it: the draft position (1..``num_teams``) on each
    overall pick, pick 1 first, ``num_teams x rounds`` of them; ``None`` stays ``None`` (a
    pure snake). ``ValueError`` names what is wrong with anything else."""
    if owners is None:
        return None
    total = num_teams * rounds
    if len(owners) != total:
        raise ValueError(f"pick_owners needs {total} entries (one per pick), got {len(owners)}")
    out = []
    for k, o in enumerate(owners, start=1):
        if isinstance(o, bool) or not isinstance(o, int) or not 1 <= o <= num_teams:
            raise ValueError(f"pick_owners[{k - 1}] (pick {k}) must be a position 1-{num_teams}")
        out.append(int(o))
    return tuple(out)


def traded_picks(owners: Sequence[int] | None, num_teams: int) -> list[int]:
    """The overall picks a map gives to another position than the snake would."""
    if owners is None:
        return []
    return [k for k, o in enumerate(owners, start=1) if pick_owner(num_teams, k)[1] != o]


def position_picks(
    owners: Sequence[int] | None, num_teams: int, position: int, rounds: int
) -> list[int]:
    """Every overall pick ``position`` owns: by the map when there is one, else the snake."""
    if owners is None:
        return snake_picks(num_teams, position, rounds)
    if not 1 <= position <= num_teams:
        raise ValueError("position must be between 1 and num_teams")
    return [k for k, o in enumerate(owners, start=1) if o == position]


def position_pick(
    owners: Sequence[int] | None, num_teams: int, position: int, rnd: int, rounds: int
) -> int | None:
    """The pick ``position`` has in round ``rnd``: the snake's, or with a map the first of its
    picks in that round (a team may hold two there, or none: then ``None``)."""
    if owners is None:
        return snake_picks(num_teams, position, rounds)[rnd - 1]
    picks = [
        k
        for k in position_picks(owners, num_teams, position, rounds)
        if round_of(num_teams, k) == rnd
    ]
    return picks[0] if picks else None
