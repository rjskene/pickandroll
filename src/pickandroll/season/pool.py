"""The moves search's pool (#424; moved here from ``api.season_moves`` by #430): the
candidates a horizon's search, its re-solves and the solve without the season guard all search,
and the strategy run's appended list. Pure: no I/O, and every size and the gain floor are
arguments (the API passes its ``POOL``, ``GUARD_POOL`` and ``MIN_GAIN``).

A horizon's pool is the best ``size`` candidates by single-move gain, in that order, then the
best ``guard_size`` adds by their best single move the guard admits, each not already in. The
best by single move stay though the guard may refuse each one's best move: one may come with
another drop, or join a set the guard admits as a whole. An add below them whose move the guard
admits would otherwise never be searched. Without a guard the pool is the first list alone."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from . import moves as mv


@dataclass(frozen=True)
class Pool:
    """A horizon's search pool: ``players`` in order, the first ``size`` the best by single-move
    gain (the pool before #424), then ``admitted`` more from the guard's list
    (:func:`admitted_swaps`)."""

    players: tuple[int, ...]
    size: int
    admitted: int

    def counts(self) -> dict[str, int]:
        return {"size": self.size, "admitted": self.admitted}


def ranked_of(swaps: Mapping[int, Sequence[mv.SwapGain]], min_gain: float) -> list[int]:
    """The candidates whose best single move gains more than ``min_gain``, best first."""
    return sorted(
        (c for c, g in swaps.items() if g and g[0].gain > min_gain),
        key=lambda c: -swaps[c][0].gain,
    )


def admitted_swaps(
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    allowed: mv.Allowed | None,
    size: int,
    min_gain: float,
) -> list[tuple[int, mv.SwapGain]]:
    """The guard's list: the best ``size`` adds by their best single move that ``allowed``
    admits and that gains more than ``min_gain``, each with that move's drop and gain, best
    first; empty without a guard. ``swaps`` is a horizon's ``moves.single_swaps``: every drop
    each add can come with, best first."""
    if allowed is None:
        return []
    pairs = sorted(
        ((c, g) for c, gains in swaps.items() for g in gains if g.gain > min_gain),
        key=lambda cg: (-cg[1].gain, cg[0]),
    )
    out: list[tuple[int, mv.SwapGain]] = []
    seen: set[int] = set()
    for c, g in pairs:
        if len(out) >= size:
            break
        if c in seen or not allowed((mv.Move(c, g.drop),)):
            continue
        seen.add(c)
        out.append((c, g))
    return out


def joined(head: Sequence[int], extra: Iterable[int]) -> Pool:
    """``head`` and then each of ``extra`` not already in it."""
    seen = set(head)
    more = [c for c in extra if not (c in seen or seen.add(c))]
    return Pool((*head, *more), len(head), len(more))


def pool_for(
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    allowed: mv.Allowed | None,
    size: int,
    guard_size: int,
    min_gain: float,
) -> tuple[Pool, list[tuple[int, mv.SwapGain]]]:
    """A horizon's search pool and the guard's list it took from: the best ``size`` by
    single-move gain (:func:`ranked_of`, in that order), then the guard's list of
    ``guard_size`` (:func:`admitted_swaps`) without repeating an add. Without a guard, the
    first ``size`` alone."""
    guarded = admitted_swaps(swaps, allowed, guard_size, min_gain)
    return joined(ranked_of(swaps, min_gain)[:size], (c for c, _ in guarded)), guarded
