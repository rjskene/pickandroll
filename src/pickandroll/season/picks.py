"""Your picks (#434, the user's ruling of 2026-11-19): players the user names, which each league's
moves solve takes as forced moves and the queue carries like its own.

A pick holds a Yahoo player id, its leagues (all, or a list), an optional drop, an optional bid,
an expiry, and who set it and when. In a league where its player is available (on no team), the
solve makes it before it searches (:func:`forced`): it uses one of the week's adds, by its clear
day's week, and drops the player the user named, else the droppable player whose loss costs
least on the queue's own score. The keep rule, the protected players and the held-slot logic
apply as for any move; the season guard and the noise floor do not (the user's call). The
solver then fills the adds left around it (:func:`fold`).

A pick leaves a league once its player is on any team there (:func:`left_in`), and every league
at its expiry (:func:`active`). Pure: the API keeps the file and reads the leagues.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

from . import moves as mv

#: A pick's life when its expiry is not set: seven days from the day it was set.
DAYS = 7
#: What decides a pick's move in the payload and the decision log.
PICK = "pick"

#: Why a pick is not made in a league today.
NOT_AVAILABLE = "not available in this league: no projection for the player"
CLAIMED = "a claim on the player is already placed"
NO_ADDS = "no adds left that week: waits for the next week's adds"
DROP_KEPT = "the drop you named is kept: the keep rule, a held slot or a claim"
NO_DROP = "no drop: every rostered player is protected or held"


@dataclass(frozen=True)
class Pick:
    player: int
    #: The leagues it applies in; None for all.
    leagues: tuple[str, ...] | None
    #: The player to drop for him where he is mine; None for the cheapest drop.
    drop: int | None
    #: The user's bid in dollars; None for the bid policy's.
    bid: int | None
    #: The last day it applies on.
    expires: date
    by: str
    at: str
    name: str | None = None
    #: The leagues it has left, each with the day its player was first seen on a team there.
    left: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Pick:
        leagues = d.get("leagues")
        return cls(
            player=int(d["player"]),
            leagues=None if leagues is None else tuple(str(x) for x in leagues),
            drop=None if d.get("drop") is None else int(d["drop"]),
            bid=None if d.get("bid") is None else int(d["bid"]),
            expires=date.fromisoformat(d["expires"]),
            by=str(d.get("by") or ""),
            at=str(d.get("at") or ""),
            name=d.get("name"),
            left={str(k): str(v) for k, v in (d.get("left") or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "player": self.player,
            "name": self.name,
            "leagues": None if self.leagues is None else list(self.leagues),
            "drop": self.drop,
            "bid": self.bid,
            "expires": self.expires.isoformat(),
            "by": self.by,
            "at": self.at,
            "left": dict(self.left),
        }

    def applies(self, league: str) -> bool:
        return self.leagues is None or league in self.leagues


def expiry(today: date, days: int | None = None) -> date:
    """The last day a pick set ``today`` applies on: :data:`DAYS` days on unless ``days`` is set."""
    return today + timedelta(days=DAYS if days is None else days)


def active(picks: Iterable[Pick], league: str, today: date) -> list[Pick]:
    """The picks in force in ``league`` on ``today``: not expired, for the league, not left it."""
    return [p for p in picks if today <= p.expires and p.applies(league) and league not in p.left]


def left_in(picks: Iterable[Pick], league: str, rostered: Iterable[int], today: date) -> list[Pick]:
    """``picks`` with ``league`` marked left on ``today`` for each pick in force there whose
    player is on a team of the league (``rostered``, mine among them); the others unchanged."""
    on = set(rostered)
    out = []
    for p in picks:
        if p.player in on and p in active([p], league, today):
            p = replace(p, left={**p.left, league: today.isoformat()})
        out.append(p)
    return out


@dataclass(frozen=True)
class Forced:
    """A pick made in the solve: its move (its drop the named or the cheapest one)."""

    pick: Pick
    move: mv.Move


@dataclass(frozen=True)
class Skipped:
    pick: Pick
    reason: str


def _limit_used(problem: mv.MoveProblem, moves: Sequence[mv.Move], lim: mv.AddLimit) -> int:
    return sum(1 for m in moves if mv.limit_of(problem, mv.day_of(problem, m)) == lim)


def forced(
    problem: mv.MoveProblem, picks: Sequence[Pick], objective: mv.Objective
) -> tuple[list[Forced], list[Skipped]]:
    """The picks ``problem`` makes, in order, and those it cannot with why. Each takes its add's
    effective day (a claim's clear day) and one add of that day's week, the picks before it
    counted; its drop is the one named when he is one of mine whom a move may drop, else the
    option of :func:`moves.drop_options` (an open spot or a held-slot move among them) whose set
    with the picks before it scores best on ``objective``, the first such in that order on a tie.
    A named drop the keep rule keeps (or a claim's add, or a drop already taken) skips the pick."""
    ev = mv.Evaluator(problem)
    candidates = dict(problem.candidates)
    mine = {k for k, _ in problem.roster} | {k for k, _ in problem.held}
    taken: list[mv.Move] = []
    made: list[Forced] = []
    skipped: list[Skipped] = []
    for pk in picks:
        if pk.player in problem.pending:
            skipped.append(Skipped(pk, CLAIMED))
            continue
        if pk.player not in candidates or any(m.add == pk.player for m in taken):
            skipped.append(Skipped(pk, NOT_AVAILABLE))
            continue
        lim = mv.limit_of(problem, problem.effective[pk.player])
        if (
            lim is not None
            and lim.adds is not None
            and _limit_used(problem, taken, lim) >= lim.adds
        ):
            skipped.append(Skipped(pk, NO_ADDS))
            continue
        options = mv.drop_options(problem, taken)
        if pk.drop is not None and pk.drop in mine:
            if pk.drop not in options or pk.drop in problem.pending:
                skipped.append(Skipped(pk, DROP_KEPT))
                continue
            options = [pk.drop]
        best: tuple[float, int | None] | None = None
        for drop in options:
            trial = [*taken, mv.Move(pk.player, drop)]
            if drop in problem.pending or not mv.feasible(problem, trial):
                continue
            score = objective(ev, trial)
            if best is None or score > best[0] + mv.EPS:
                best = (score, drop)
        if best is None:
            skipped.append(Skipped(pk, NO_DROP))
            continue
        move = mv.Move(pk.player, best[1])
        taken.append(move)
        made.append(Forced(pk, move))
    return made, skipped


def fold(problem: mv.MoveProblem, made: Sequence[Forced]) -> mv.MoveProblem:
    """``problem`` with the picks ``made``: each add on my roster from its effective day and its
    drop off it (``moves.with_pending``: never a drop or a held-slot move of a later move), and
    one add fewer in its week's limit, so the solve fills the adds left around them. Whom the keep
    rule keeps is the caller's (it is read on this roster)."""
    if not made:
        return problem
    candidates = dict(problem.candidates)
    pending = [
        mv.Pending(f.move.add, candidates[f.move.add], f.move.drop, mv.day_of(problem, f.move))
        for f in made
    ]
    limits = []
    for lim in problem.limits:
        used = _limit_used(problem, [f.move for f in made], lim)
        limits.append(lim if lim.adds is None or not used else replace(lim, adds=lim.adds - used))
    return replace(mv.with_pending(problem, pending), limits=tuple(limits))
