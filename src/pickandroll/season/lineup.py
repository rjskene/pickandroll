"""Lineups (#107, docs/ADD_DROP.md, "Lineups"): the recommended starters for each day of a
week and Yahoo's lineup as read, compared.

A day's recommended lineup is the projection's own: the players who play that day
(:func:`weekly.playing_days`, the schedule and the out rule) placed by :func:`weekly.starters`,
the most valuable set the starting slots can hold. That set is also the largest: the sets the
slots can hold form a matroid, so no legal lineup counts more games. Yahoo's lineup counts the
players its starting slots hold who play that day; the games it loses are the difference. Two
lineups that start the same players in other slots count the same and are not a difference.

A league whose lineups change weekly sets one lineup for the week (:func:`weekly_lineup`): the
most valuable set over the week's games, each player worth his games times his per-game value.

Held slots (IL, IL+, NA) never start. A held player whose status cleared stays out of the
recommendation until he is activated, which the lineup says first (``season.moves.cleared``).

The games a lineup as read lost (#149, :func:`lost_games`) rest on the same matroid: the most
players who played that the starting slots could have held, less the starters who played.

The lineup executor's steps (#170, :func:`target_lineup`, :func:`lineup_steps`) turn Yahoo's
lineup as read into one that starts the recommended players: Yahoo's starters less the ones to
sit, plus the ones to start, placed so that the most players stay where they are (two lineups
that start the same players count the same, so nothing moves only to match the recommended slot
order). The changes are legal swaps and moves, each leaving every player in a slot he may take
(the bench takes anyone: Yahoo lets it run over its count while a starting slot is empty), in
groups that share no player and no slot: a group can be left out whole (a player's game began)
and the rest still applies. Held slots are never touched.
"""

from __future__ import annotations

from collections.abc import Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from typing import Any

from . import weekly as wk
from .state import Player, RosterSpot

#: The bench: a benched player who played can be a game lost; a held one (IL, IL+, NA) never is.
BENCH = "BN"


@dataclass(frozen=True)
class DayLineup[K: Hashable]:
    day: date
    #: The recommended starters by slot, in the league's slot order (None for a slot nobody
    #: who plays can fill); None for a day before the first a change counts.
    recommended: tuple[tuple[str, K | None], ...] | None
    #: Yahoo's lineup as read for the day (slot and player), None when not read.
    yahoo: tuple[tuple[str, K], ...] | None
    #: Of each, the players who start and play that day.
    started: tuple[K, ...]
    yahoo_started: tuple[K, ...] | None
    #: The players the recommendation starts that Yahoo's lineup does not, and the fewest of
    #: Yahoo's starters who must leave the starting slots to make room for them (no game, or a
    #: better player in his slot); a starter with no game whom the slots can still hold stays.
    start: tuple[K, ...] = ()
    sit: tuple[K, ...] = ()

    @property
    def lost(self) -> int | None:
        """The games Yahoo's lineup loses against the recommended one; None when either is
        missing."""
        if self.recommended is None or self.yahoo_started is None:
            return None
        return max(0, len(self.started) - len(self.yahoo_started))


def by_slot[K: Hashable](
    assignment: Mapping[K, str], slots: Sequence[str]
) -> tuple[tuple[str, K | None], ...]:
    """``starters``' players by slot as the league lists its slots (two ``C`` slots take the
    two centres in turn), an unfilled slot holding None."""
    left: dict[str, list[K]] = {}
    for key, slot in assignment.items():
        left.setdefault(slot, []).append(key)
    for keys in left.values():
        keys.sort(key=str)
    return tuple((slot, left[slot].pop(0) if left.get(slot) else None) for slot in slots)


def weekly_lineup[K: Hashable](
    roster: Sequence[tuple[K, Player]],
    playing: Mapping[K, Sequence[date]],
    days: Sequence[date],
    slots: Sequence[str],
    value: Mapping[K, float],
) -> dict[K, str]:
    """One lineup for the week (a league whose lineups change weekly): the most valuable set
    the slots hold, each player worth his games in ``days`` times his per-game value."""
    worth = {
        k: sum(1 for d in playing.get(k, ()) if d in days) * value.get(k, 0.0) for k, _ in roster
    }
    candidates = [(k, p.positions) for k, p in roster if worth[k] > 0]
    return wk.starters(candidates, slots, worth)


def compare(
    day: date,
    recommended: Mapping[int, str] | None,
    yahoo: Sequence[RosterSpot] | None,
    playing: Mapping[int, Sequence[date]],
    slots: Sequence[str],
    positions: Mapping[int, Sequence[str]] | None = None,
) -> DayLineup[int]:
    """One day: the recommended starters (``recommended``, a player's slot) against Yahoo's
    lineup as read (``yahoo``); a player starts when his slot starts and he plays that day.
    ``slots`` are the starting slots; ``positions`` the roster's (Yahoo's spots give their
    own), for the fewest starters to sit."""

    def plays(k: int) -> bool:
        return day in playing.get(k, ())

    started = tuple(k for k in (recommended or {}) if plays(k))
    read = None
    yahoo_started = None
    if yahoo is not None:
        read = tuple((sp.slot, sp.player.yahoo_id) for sp in yahoo)
        yahoo_started = tuple(
            k for slot, k in read if slot.upper() not in wk.NOT_STARTING and plays(k)
        )
    start: tuple[int, ...] = ()
    sit: tuple[int, ...] = ()
    if recommended is not None and yahoo is not None and yahoo_started is not None:
        on = set(yahoo_started)
        start = tuple(k for k in started if k not in on)
        rec = set(started)
        out = [
            sp.player.yahoo_id
            for sp in yahoo
            if sp.slot.upper() not in wk.NOT_STARTING and sp.player.yahoo_id not in rec
        ]
        if start and out:
            # The recommended starters first, then as many of the others as still fit: a
            # starter who plays never does (the recommended set is the largest that can).
            pos = {sp.player.yahoo_id: sp.player.positions for sp in yahoo}
            pos = {**pos, **(positions or {})}
            weight = {**dict.fromkeys(out, 1.0), **dict.fromkeys(started, 2.0)}
            held = wk.starters([(k, pos.get(k, ())) for k in weight], slots, weight)
            sit = tuple(k for k in out if k not in held)
    return DayLineup(
        day,
        by_slot(recommended, slots) if recommended is not None else None,
        read,
        started,
        yahoo_started,
        start,
        sit,
    )


def lost_games[K: Hashable](
    spots: Sequence[tuple[str, K, Sequence[str]]], played: Collection[K], slots: Sequence[str]
) -> int:
    """The games one day's lineup as read lost (#149): the most of its starters and benched
    players who played that the starting ``slots`` can hold, less as many of its starters who
    played. ``spots`` is the lineup (slot, player, positions), ``played`` the players who played
    that day. A benched player who played counts when a slot he fits was open or held a player
    without a game, or could be freed by moving its starter to one; two benched players who
    could take only one such slot count once. Held slots neither start nor count."""

    def most(rows: list[tuple[K, Sequence[str]]]) -> int:
        return len(wk.starters(rows, slots, dict.fromkeys((k for k, _ in rows), 1.0)))

    starting = [(k, pos) for slot, k, pos in spots if slot.upper() not in wk.NOT_STARTING]
    bench = [(k, pos) for slot, k, pos in spots if slot.upper() == BENCH]
    starting = [(k, pos) for k, pos in starting if k in played]
    bench = [(k, pos) for k, pos in bench if k in played]
    return most([*starting, *bench]) - most(starting)


def week_lost[K: Hashable](
    days: Sequence[date],
    lineups: Mapping[date, Sequence[tuple[str, K, Sequence[str]]]],
    played: Mapping[date, Collection[K]],
    slots: Sequence[str],
    matched: Collection[K],
) -> dict[str, Any]:
    """A week's games lost to the lineup: :func:`lost_games` summed over the ``days`` read, a
    day with both its lineup read after it (``lineups``) and its box scores (``played``); a day
    without either adds nothing and is not read. ``lost`` is None when no day was read.
    ``unmatched`` counts the players of a read day's starting slots or bench whom no box score
    of the week matched (``matched``): they count as not playing."""
    read = [d for d in days if d in lineups and d in played]
    unmatched = {
        k
        for d in read
        for slot, k, _ in lineups[d]
        if (slot.upper() not in wk.NOT_STARTING or slot.upper() == BENCH) and k not in matched
    }
    return {
        "lost": sum(lost_games(lineups[d], played[d], slots) for d in read) if read else None,
        "days_read": len(read),
        "days": len(days),
        "unmatched": len(unmatched),
    }


# --------------------------------------------------------------------------- the executor (#170)
#: The held slots: a player in one is never moved by the lineup executor, and none is a target
#: (an IL move is a roster move, phase 2).
HELD_SLOTS = frozenset({"IL", "IL+", "NA"})


@dataclass(frozen=True)
class Step[K: Hashable]:
    """One change on the team page: ``player`` from ``from_slot`` to ``to_slot``, and the player
    who was in ``to_slot`` (``swapped``, None for an empty slot) to ``from_slot``."""

    player: K
    from_slot: str
    to_slot: str
    swapped: K | None


def target_lineup[K: Hashable](
    spots: Sequence[tuple[str, K, Sequence[str]]],
    start: Collection[K],
    sit: Collection[K],
    slots: Sequence[str],
) -> dict[K, str] | None:
    """The lineup the steps lead to, every player's slot: Yahoo's starters (``spots``, slot,
    player and positions, as read) less ``sit``, plus ``start``, placed on the starting
    ``slots`` with the most players staying in the slot they hold (an exact search over the
    slots: at most a few thousand states); everyone else on the bench, a held player where he
    is. None when the players do not fit the slots, or a player to start is not on the roster
    or sits in a held slot."""
    current = {k: slot for slot, k, _ in spots}
    pos = {k: tuple(p) for _, k, p in spots}
    if any(k not in current or current[k].upper() in HELD_SLOTS for k in start):
        return None
    starting = [k for slot, k, _ in spots if slot.upper() not in wk.NOT_STARTING]
    chosen = [k for k in starting if k not in sit] + [k for k in start if k not in starting]
    if len(chosen) > len(slots):
        return None

    @cache
    def best(i: int, used: int) -> tuple[int, tuple[int, ...]] | None:
        if i == len(chosen):
            return 0, ()
        k = chosen[i]
        out = None
        for j, slot in enumerate(slots):
            if used >> j & 1 or not wk.accepts(slot, pos[k]):
                continue
            rest = best(i + 1, used | 1 << j)
            if rest is None:
                continue
            score = rest[0] + (slot.upper() == current[k].upper())
            if out is None or score > out[0]:
                out = score, (j, *rest[1])
        return out

    placed = best(0, 0)
    if placed is None:
        return None
    target = {k: (slot if slot.upper() in HELD_SLOTS else BENCH) for slot, k, _ in spots}
    target.update({k: slots[j] for k, j in zip(chosen, placed[1], strict=True)})
    return target


def lineup_steps[K: Hashable](
    spots: Sequence[tuple[str, K, Sequence[str]]],
    target: Mapping[K, str],
    slots: Sequence[str],
) -> list[list[Step[K]]] | None:
    """The legal changes from Yahoo's lineup as read (``spots``) to ``target``, in groups that
    share no player and no slot. ``slots`` are the starting slots; held players stay where they
    are. Each step moves a player into a free starting slot of his target; else a bench player
    into his target, its occupant to the bench (a swap); else a starter into his target, its
    occupant to the starter's slot when he may take it; else a player to the bench. A player
    once in his target never moves again. None when the lineup as read does not fit the slots (a
    starter in a slot the league does not have) or no legal order is found."""
    # The bench takes anyone, so it has a place for every player.
    tokens = [*slots, *[BENCH] * len(spots)]
    held: dict[int, K | None] = dict.fromkeys(range(len(tokens)))
    where: dict[K, int] = {}
    pos = {k: tuple(p) for _, k, p in spots}
    for slot, k, _ in spots:
        if slot.upper() in HELD_SLOTS:
            continue
        free = next(
            (i for i, t in enumerate(tokens) if t.upper() == slot.upper() and held[i] is None),
            None,
        )
        if free is None:
            return None
        held[free], where[k] = k, free

    def done(k: K) -> bool:
        return tokens[where[k]].upper() == target[k].upper()

    steps: list[tuple[Step[K], int, int]] = []

    def move(k: K, to: int) -> None:
        other = held[to]
        frm = where[k]
        steps.append((Step(k, tokens[frm], tokens[to], other), frm, to))
        held[to], held[frm] = k, other
        where[k] = to
        if other is not None:
            where[other] = frm

    def into(k: K) -> list[int]:
        return [i for i, t in enumerate(tokens) if t.upper() == target[k].upper()]

    def leaving(i: int) -> K | None:
        """The player in slot ``i`` when he is not in his target yet."""
        other = held[i]
        return other if other is not None and not done(other) else None

    while pending := [k for k in sorted(where, key=lambda k: where[k]) if not done(k)]:
        choice = next(
            (
                (k, i)
                for k in pending
                if target[k].upper() != BENCH
                for i in into(k)
                if held[i] is None
            ),
            None,
        )
        if choice is None:
            choice = next(
                (
                    (k, i)
                    for k in pending
                    if tokens[where[k]] == BENCH
                    for i in into(k)
                    if leaving(i) is not None
                ),
                None,
            )
        if choice is None:
            choice = next(
                (
                    (k, i)
                    for k in pending
                    for i in into(k)
                    if (other := leaving(i)) is not None
                    and wk.accepts(tokens[where[k]], pos[other])
                ),
                None,
            )
        if choice is None:
            choice = next(((k, i) for k in pending for i in into(k) if held[i] is None), None)
        if choice is None:
            return None
        move(*choice)

    # Group the steps by the slots they touch: a group shares no slot with another.
    root = list(range(len(tokens)))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for _, frm, to in steps:
        root[find(frm)] = find(to)
    groups: dict[int, list[Step[K]]] = {}
    for step, frm, _ in steps:
        groups.setdefault(find(frm), []).append(step)
    return list(groups.values())


def apply_steps[K: Hashable](
    spots: Sequence[tuple[str, K, Sequence[str]]], steps: Sequence[Step[K]]
) -> dict[K, str]:
    """Every player's slot after ``steps``, from the lineup as read."""
    out = {k: slot for slot, k, _ in spots}
    for step in steps:
        out[step.player] = step.to_slot
        if step.swapped is not None:
            out[step.swapped] = step.from_slot
    return out
