"""Streaming plans (#136, docs/ADD_DROP.md "Streaming plans"): a dated sequence of adds and drops
that turns a marginal spot over inside the week for more games than any single move buys.

A stream spot is an active spot whose occupant is below the waiver replacement level (the keep
rule's best available add by rest-of-season per-game value) and kept by nothing (protected or
on the bench, #124); the weakest :data:`STREAM_SPOTS` are planned one after the other. The base
is the recommended week set less the moves that drop a stream spot's occupant: those spots are
the plan's to fill. A spot is planned with the earlier spots' plans made and the later spots'
own moves from the set, so it never takes the adds the set gives them.

A spot's path says who holds it each day from the first day to the week's last. Each change of
holder is one dated move (``moves.Move`` with its ``day``) whose drop is the holder before, so a
later step drops an earlier step's add. The path keeps to the week's adds left, at most
:data:`DAILY_CAP` moves a day (the base's included, docs/AUTOPILOT.md section 2), each candidate
from his effective day on (a claim's clear date), and nobody holds the spot twice.

The search is a dynamic programme over the days with a cheap score: a holder's day is worth his
per-game value (the league scorer's, net of an empty line) when he has a game that day and would
start it beside the rest of the roster, and a whole path also counts its last holder's games in
the weeks after. It keeps the best :data:`KEEP` partial paths per holder and adds used. The best
:data:`EXACT` whole paths are valued with the Moves card's evaluator against the spot as the set
leaves it (its own move for the spot, else its occupant kept): the spot's plan is the path with
the best week among those that cost nothing on the three weeks after, since the last holder
stays. A heuristic: the plan is recommended, never optimal, and only when its week beats the
recommended set's by more than :data:`PLAN_FLOOR`. Pure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import islice

from . import moves as mv
from . import weekly as wk

#: The stream spots planned at most.
STREAM_SPOTS = 2
#: The moves a league may execute in a day (docs/AUTOPILOT.md, section 2).
DAILY_CAP = 2
#: The partial paths kept per holder and adds used, and the whole paths valued exactly.
KEEP = 5
EXACT = 8
#: How far a plan's week must beat the recommended set's, in expected categories: the week's
#: noise floor until the scorecard (#126) sets one.
PLAN_FLOOR = 0.10


@dataclass(frozen=True)
class SpotPlan:
    """A stream spot's plan: its occupant and the dated steps that turn it over (none when no
    path beats keeping him)."""

    occupant: int
    steps: tuple[mv.Move, ...]


@dataclass(frozen=True)
class Plan:
    #: The recommended set's moves kept, and each stream spot's plan in order.
    base: tuple[mv.Move, ...]
    spots: tuple[SpotPlan, ...]
    #: The set the plan is measured against (the recommended week set).
    against: tuple[mv.Move, ...]

    @property
    def steps(self) -> tuple[mv.Move, ...]:
        """Every step, by day (the first spot's first on a day both turn over)."""
        order = [(s.day, i, j) for i, sp in enumerate(self.spots) for j, s in enumerate(sp.steps)]
        return tuple(self.spots[i].steps[j] for _, i, j in sorted(order))

    @property
    def moves(self) -> tuple[mv.Move, ...]:
        """The plan as a set of moves: the base, then its steps."""
        return (*self.base, *self.steps)


def stream_spots(problem: mv.MoveProblem, rule: mv.KeepRule) -> list[int]:
    """My active players whose spot may be streamed, weakest first: below the best available
    add by rest-of-season per-game value and kept by nothing; a player without a line is
    weakest. At most :data:`STREAM_SPOTS`."""
    if rule.best_value is None:
        return []
    kept = rule.kept | problem.kept
    below = []
    for key, _ in problem.roster:
        value = problem.season_value.get(key)
        if key in kept or (value is not None and value >= rule.best_value):
            continue
        below.append((value if value is not None else float("-inf"), key))
    return [k for _, k in sorted(below)][:STREAM_SPOTS]


def _others(
    problem: mv.MoveProblem, span: mv.WeekSpan, fixed: Sequence[mv.Move], occupant: int
) -> dict[date, list[tuple[int, tuple[str, ...]]]]:
    """Who else plays each day of ``span`` with ``fixed`` made, the occupant left out: the
    players a holder of the spot competes with for a start."""
    by_id = dict(problem.candidates)
    members = [*problem.held, *problem.roster, *((m.add, by_id[m.add]) for m in fixed)]
    members = [(k, pl) for k, pl in members if k != occupant]
    available, gone = mv.timeline(problem, fixed)
    playing = wk.playing_days(
        members,
        span.days,
        problem.schedule,
        span.this_week,
        span.games,
        problem.no_games,
        available_from={**problem.effective, **problem.returns, **available},
        gone_from=gone,
    )
    positions = {k: pl.positions for k, pl in members}
    return {d: [(k, positions[k]) for k, ds in playing.items() if d in ds] for d in span.days}


def day_scores(
    problem: mv.MoveProblem,
    span: mv.WeekSpan,
    fixed: Sequence[mv.Move],
    occupant: int,
    holders: Sequence[int],
    per_game: Mapping[int, float],
) -> dict[int, dict[date, float]]:
    """Each holder's cheap score on each day of ``span``: his per-game value when he plays that
    day and would start beside the others playing with ``fixed`` made, else 0."""
    others = _others(problem, span, fixed, occupant)
    players = dict(problem.roster) | dict(problem.candidates)
    out: dict[int, dict[date, float]] = {}
    for key in holders:
        player = players[key]
        start = problem.returns.get(key, problem.effective.get(key, problem.first_day))
        played = wk.playing_days(
            [(key, player)],
            span.days,
            problem.schedule,
            span.this_week,
            span.games,
            problem.no_games,
            available_from={key: start},
        )[key]
        out[key] = {
            d: per_game.get(key, 0.0)
            if d in played
            and key
            in wk.starters([*others[d], (key, player.positions)], problem.slots, problem.value)
            else 0.0
            for d in span.days
        }
    return out


@dataclass(frozen=True)
class _Partial:
    score: float
    steps: tuple[mv.Move, ...]
    held: frozenset[int]


def paths(
    days: Sequence[date],
    occupant: int,
    scores: Mapping[int, Mapping[date, float]],
    earliest: Mapping[int, date],
    adds: int,
    room: Mapping[date, int],
    after: Mapping[int, float] | None = None,
) -> list[_Partial]:
    """The best paths for a spot over ``days`` by cheap score, best first: who holds it each
    day, starting with ``occupant``. A change of holder is one add (``adds`` at most) on a day
    with ``room`` left under the daily cap, to a candidate from his ``earliest`` day on who has
    not held it. At most :data:`KEEP` paths per holder and adds used; a whole path's score adds
    its last holder's ``after`` (his worth in the weeks after, where he stays)."""
    # (holder, adds used) -> the best partial paths through the day before.
    states = {(occupant, 0): [_Partial(0.0, (), frozenset({occupant}))]}
    candidates = [k for k in scores if k != occupant]
    for d in days:
        nxt: dict[tuple[int, int], list[_Partial]] = {}
        for (holder, used), parts in states.items():
            nxt.setdefault((holder, used), []).extend(
                _Partial(p.score + scores[holder][d], p.steps, p.held) for p in parts
            )
        if room.get(d, 0) > 0:
            # A change to a candidate comes from the best paths with as many adds used,
            # whoever holds the spot.
            by_used: dict[int, list[tuple[int, _Partial]]] = {}
            for (holder, used), parts in states.items():
                if used < adds:
                    by_used.setdefault(used, []).extend((holder, p) for p in parts)
            for used, rows in by_used.items():
                rows.sort(key=lambda r: -r[1].score)
                for cand in candidates:
                    if earliest[cand] > d:
                        continue
                    changed = (
                        _Partial(
                            p.score + scores[cand][d],
                            (*p.steps, mv.Move(cand, holder, d)),
                            p.held | {cand},
                        )
                        for holder, p in rows
                        if cand not in p.held
                    )
                    nxt.setdefault((cand, used + 1), []).extend(islice(changed, KEEP))
        states = {k: sorted(v, key=lambda p: -p.score)[:KEEP] for k, v in nxt.items() if v}
    after = after or {}
    whole = [
        _Partial(p.score + after.get(holder, 0.0), p.steps, p.held)
        for (holder, _), parts in states.items()
        for p in parts
    ]
    return sorted(whole, key=lambda p: (-p.score, len(p.steps)))


def after_scores(
    problem: mv.MoveProblem, holders: Sequence[int], per_game: Mapping[int, float]
) -> dict[int, float]:
    """Each holder's cheap worth in the weeks after this one (the ``three`` horizon): his
    per-game value times the games he plays there."""
    players = dict(problem.roster) | dict(problem.candidates)
    out = dict.fromkeys(holders, 0.0)
    for span in problem.horizons.get("three", ()):
        playing = wk.playing_days(
            [(k, players[k]) for k in holders],
            span.days,
            problem.schedule,
            span.this_week,
            span.games,
            problem.no_games,
            available_from={**problem.effective, **problem.returns},
        )
        for k in holders:
            out[k] += per_game.get(k, 0.0) * len(playing[k])
    return out


def _room(
    problem: mv.MoveProblem, moves: Sequence[mv.Move], days: Sequence[date]
) -> dict[date, int]:
    used: dict[date, int] = {}
    for m in moves:
        day = mv.day_of(problem, m)
        used[day] = used.get(day, 0) + 1
    return {d: DAILY_CAP - used.get(d, 0) for d in days}


def _adds_left(problem: mv.MoveProblem, moves: Sequence[mv.Move], week: date) -> int:
    """The adds this week allows beyond ``moves`` (a large number when unlimited)."""
    lim = mv.limit_of(problem, week)
    if lim is None or lim.adds is None:
        return len(problem.candidates)
    spent = sum(1 for m in moves if mv.limit_of(problem, mv.day_of(problem, m)) == lim)
    return max(0, lim.adds - spent)


def plan_spot(
    ev: mv.Evaluator,
    fixed: Sequence[mv.Move],
    occupant: int,
    per_game: Mapping[int, float],
    own: Sequence[mv.Move] = (),
) -> SpotPlan:
    """The plan for ``occupant``'s spot with ``fixed`` made, against the spot as the set leaves
    it (``own``, the set's move for it, else the occupant kept): of the best :data:`EXACT` paths
    by cheap score, the one with the best week among those no worse on the weeks after; the
    set's own move (or no step) when none beats it."""
    p = ev.problem
    span = p.horizons["week"][0]
    used = {m.add for m in fixed}
    holders = [c for c, _ in p.candidates if c not in used]
    scores = day_scores(p, span, fixed, occupant, [occupant, *holders], per_game)
    # A candidate who never scores cannot pay for an add.
    scores = {k: v for k, v in scores.items() if k == occupant or any(x > 0 for x in v.values())}
    earliest = {k: p.effective[k] for k in scores if k != occupant}
    adds = _adds_left(p, fixed, span.days[0])
    room = _room(p, fixed, span.days)
    after = after_scores(p, list(scores), per_game)
    found = [
        part.steps
        for part in paths(span.days, occupant, scores, earliest, adds, room, after)
        if part.steps
    ]
    own = tuple(own) if own and mv.feasible(p, [*fixed, *own]) else ()
    best = SpotPlan(occupant, own)
    best_v = ev.value("week", [*fixed, *own])
    later = ev.value("three", [*fixed, *own])
    for steps in found[:EXACT]:
        trial = [*fixed, *steps]
        if steps == own or not mv.feasible(p, trial):
            continue
        v = ev.value("week", trial)
        if v > best_v + mv.EPS and ev.value("three", trial) >= later - mv.EPS:
            best, best_v = SpotPlan(occupant, steps), v
    return best


def plan(
    ev: mv.Evaluator,
    rule: mv.KeepRule,
    recommended: Sequence[mv.Move],
    per_game: Mapping[int, float],
) -> Plan | None:
    """The week's streaming plan against the ``recommended`` set, None without a stream spot."""
    p = ev.problem
    spots = stream_spots(p, rule)
    if not spots:
        return None
    own = {
        o: [mv.Move(m.add, m.drop, mv.day_of(p, m)) for m in recommended if m.drop == o]
        for o in spots
    }
    base = tuple(m for m in recommended if m.drop not in spots)
    planned: list[SpotPlan] = []
    for i, occupant in enumerate(spots):
        done = [m for sp in planned for m in sp.steps]
        rest = [m for o in spots[i + 1 :] for m in own[o]]
        planned.append(plan_spot(ev, [*base, *done, *rest], occupant, per_game, own[occupant]))
    return Plan(base, tuple(planned), tuple(recommended))


def recommended(ev: mv.Evaluator, plan_: Plan) -> bool:
    """Whether the plan's week beats its set's by more than :data:`PLAN_FLOOR`."""
    if not plan_.steps:
        return False
    return ev.value("week", plan_.moves) - ev.value("week", plan_.against) > PLAN_FLOOR


def step_gains(ev: mv.Evaluator, plan_: Plan) -> list[dict[str, float]]:
    """Each step's own gain on each horizon: the plan up to it less the plan before it (the base
    and the earlier steps), so the steps' gains sum to the plan's over its base."""
    out = []
    done = list(plan_.base)
    for step in plan_.steps:
        before = {h: ev.value(h, done) for h in ev.base}
        done.append(step)
        out.append({h: ev.value(h, done) - before[h] for h in ev.base})
    return out
