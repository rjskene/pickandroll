"""Week plans (#221 part 2, docs/ADD_DROP.md "Week plans"): a few dated sequences of moves over
the rest of this week, each step priced by what it adds to the plan before it.

A plan is at most :data:`PLAN_STEPS` dated moves (``moves.Move`` with its day) inside this week,
the current week only (the ruling of 2026-10-23). Its steps come from a pool of blocks
(:func:`blocks`): each of the week's best single moves (``moves.single_swaps`` on the ``week``
horizon, the top :data:`SINGLES` candidates with their :data:`DROPS` best drops, churns among
them), a block of one dated at its add's effective day; and each stream spot's chain from the
streaming plan (``stream.plan``), kept whole so a step that drops an earlier step's add never
comes without it.

A plan keeps to the rules every dated set keeps (:func:`valid`): ``moves.feasible`` (distinct adds
and drops, the room, the churn rule and the weekly adds), each step inside the week, each drop on
the roster, held, or an earlier step's add, and at most the daily cap a day (``stream.DAILY_CAP``
or the problem's own, a knob). The search is a beam over the blocks, :data:`BEAM` wide, by a cheap
score (each block's own week gain); the best :data:`EXACT` plans are valued exactly with the
Moves card's evaluator. A step's increment is the plan up to it less the plan before it, on
``week`` and on ``three``, so the increments telescope to the plan's gain over the base
(:func:`valued`). A plan is kept only when the season guard holds on it (``allowed``).

The roster's own changes inside the week are listed on their day as zero-choice steps
(:class:`Back`): a cleared player's activation, a held-slot move's comeback and a held player's
return, each with the drop it forces (``moves.comebacks``). A held return's increment is the plan
with him back less the plan with him held past the horizons; it is shown, never summed in the
total. A heuristic: the plans are recommended, never optimal. Plan 1 is the recommended week set
unless a searched plan beats its week by the plan floor (``stream.floor_of``). Pure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from . import moves as mv
from . import stream as st

#: The plans shown at most, and the steps a plan takes at most.
WEEK_PLANS = 5
PLAN_STEPS = 4
#: The beam's width and the plans valued exactly (the ruling: 8, as the stream's).
BEAM = 8
EXACT = 8
#: The week's best candidates whose single moves join the pool, and the drops each comes with.
SINGLES = 12
DROPS = 2
#: Where a plan comes from: the recommended week set, or the search.
SET, SEARCH = "set", "search"
#: The decision log's set for the plan the queue takes instead of the three weeks' set.
QUEUE_PLAN = "week_plan"


@dataclass(frozen=True)
class Step:
    move: mv.Move
    day: date
    #: What the step adds to the plan before it, on each horizon.
    gain: Mapping[str, float]


@dataclass(frozen=True)
class Back:
    """A zero-choice step: a player of mine back inside the week and the drop he forces."""

    player: int
    slot: str
    day: date
    drop: int
    #: A held player's return (#221 part 1), else a cleared activation or a held move's comeback.
    returning: bool
    #: A held return's increment (the plan with him back less with him held), else None.
    gain: Mapping[str, float] | None


@dataclass(frozen=True)
class WeekPlan:
    source: str
    steps: tuple[Step, ...]
    backs: tuple[Back, ...]
    #: The plan's gain over the base on each horizon: its steps' increments summed.
    total: Mapping[str, float]

    @property
    def moves(self) -> tuple[mv.Move, ...]:
        return tuple(s.move for s in self.steps)


def blocks(
    problem: mv.MoveProblem,
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    stream_plan: st.Plan | None = None,
) -> list[tuple[mv.Move, ...]]:
    """The pool a plan's steps come from: the week's best single moves (``swaps``, the week's
    ``single_swaps``), each a block of one, and each stream spot's chain, whole."""
    ranked = sorted(
        (c for c, g in swaps.items() if g and g[0].gain > mv.EPS),
        key=lambda c: (-swaps[c][0].gain, c),
    )
    out: list[tuple[mv.Move, ...]] = []
    for cand in ranked[:SINGLES]:
        out += [(mv.Move(cand, g.drop),) for g in swaps[cand][:DROPS] if g.gain > mv.EPS]
    if stream_plan is not None:
        out += [tuple(sp.steps) for sp in stream_plan.spots if sp.steps]
    return list(dict.fromkeys(out))


def cap_of(problem: mv.MoveProblem) -> int:
    return st.DAILY_CAP if problem.daily_cap is None else problem.daily_cap


def valid(problem: mv.MoveProblem, moves: Sequence[mv.Move]) -> bool:
    """Whether a plan keeps the rules: at most :data:`PLAN_STEPS` steps, each inside the week, at
    most the daily cap a day, each drop on the roster, held, or an earlier step's add, and
    ``moves.feasible``."""
    if len(moves) > PLAN_STEPS:
        return False
    week = set(problem.horizons["week"][0].days)
    days = [mv.day_of(problem, m) for m in moves]
    if any(d not in week for d in days):
        return False
    cap = cap_of(problem)
    if any(days.count(d) > cap for d in set(days)):
        return False
    mine = {k for k, _ in problem.roster} | {k for k, _ in problem.held}
    for m, d in zip(moves, days, strict=True):
        if m.drop is None or m.drop in mine:
            continue
        earlier = any(
            o.add == m.drop and od <= d and o is not m for o, od in zip(moves, days, strict=True)
        )
        if not earlier:
            return False
    return mv.feasible(problem, moves)


def search(
    ev: mv.Evaluator,
    pool: Sequence[tuple[mv.Move, ...]],
    allowed: mv.Allowed | None = None,
) -> list[tuple[mv.Move, ...]]:
    """The best :data:`EXACT` plans by cheap score: a beam over the blocks of ``pool``, each
    block's cheap score its own week gain, every plan kept to :func:`valid` and ``allowed``."""
    p = ev.problem
    cheap = [ev.gain("week", b) for b in pool]
    beam: list[tuple[tuple[mv.Move, ...], float, int]] = [((), 0.0, -1)]
    seen: dict[frozenset[mv.Move], tuple[tuple[mv.Move, ...], float]] = {}
    for _ in range(PLAN_STEPS):
        nxt = []
        for moves, score, last in beam:
            for i in range(last + 1, len(pool)):
                trial = (*moves, *pool[i])
                if valid(p, trial) and (allowed is None or allowed(trial)):
                    nxt.append((trial, score + cheap[i], i))
        if not nxt:
            break
        nxt.sort(key=lambda x: -x[1])
        beam = nxt[:BEAM]
        for moves, score, _ in beam:
            seen.setdefault(frozenset(moves), (moves, score))
    ranked = sorted(seen.values(), key=lambda x: -x[1])
    return [moves for moves, _ in ranked[:EXACT]]


def ordered(problem: mv.MoveProblem, moves: Sequence[mv.Move]) -> list[mv.Move]:
    """A plan's moves by day, the plan's own order breaking ties."""
    index = {m: i for i, m in enumerate(moves)}
    return sorted(moves, key=lambda m: (mv.day_of(problem, m), index[m]))


#: The value of a set of moves with one held player kept out past the horizons: a held return's
#: increment's other side (the API caches one evaluator a returner).
HeldOut = Callable[[int, str, Sequence[mv.Move]], float]


def held_out(ev: mv.Evaluator) -> HeldOut:
    """:data:`HeldOut` on ``ev``'s problem: each returner's problem with his return moved past the
    horizons, its evaluator made once."""
    p = ev.problem
    last = max(d for spans in p.horizons.values() for span in spans for d in span.days)
    evs: dict[int, mv.Evaluator] = {}

    def value(player: int, key: str, moves: Sequence[mv.Move]) -> float:
        if player not in evs:
            later = {**p.returns, player: last + timedelta(days=1)}
            evs[player] = mv.Evaluator(replace(p, returns=later))
        return evs[player].value(key, moves)

    return value


def valued(
    ev: mv.Evaluator, moves: Sequence[mv.Move], source: str, out: HeldOut | None = None
) -> WeekPlan:
    """A plan valued exactly: its steps by day, each with its increment on every horizon, and the
    zero-choice steps of the week with a held return's increment when ``out`` is given."""
    p = ev.problem
    steps: list[Step] = []
    done: list[mv.Move] = []
    before = {h: ev.value(h, ()) for h in p.horizons}
    for m in ordered(p, moves):
        done.append(m)
        now = {h: ev.value(h, done) for h in p.horizons}
        steps.append(Step(m, mv.day_of(p, m), {h: now[h] - before[h] for h in p.horizons}))
        before = now
    backs = []
    for c in mv.comebacks(p, "week", done):
        gain = None
        if c.returning and out is not None:
            gain = {h: ev.value(h, done) - out(c.player, h, done) for h in p.horizons}
        backs.append(Back(c.player, c.slot, c.day, c.drop, c.returning, gain))
    total = {h: sum(s.gain[h] for s in steps) for h in p.horizons}
    return WeekPlan(source, tuple(steps), tuple(backs), total)


def key_of(problem: mv.MoveProblem, moves: Sequence[mv.Move]) -> frozenset[tuple]:
    """A plan's identity: its adds with their days, never its drops (the master's ruling of
    2026-10-29): two plans that add the same players on the same days are one idea with another
    drop, and the candidates table already shows the drops."""
    return frozenset((m.add, mv.day_of(problem, m)) for m in moves)


def week_plans(
    ev: mv.Evaluator,
    week_set: Sequence[mv.Move],
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    stream_plan: st.Plan | None = None,
    allowed: mv.Allowed | None = None,
    out: HeldOut | None = None,
) -> list[WeekPlan]:
    """The week's plans, at most :data:`WEEK_PLANS`, distinct by adds and days (:func:`key_of`;
    of the searched plans with the same adds and days only the one worth most on the week is kept,
    and none with the set's: the set is plan 1's idea): plan 1 the recommended ``week_set`` unless
    a searched plan beats its week by the plan floor, the others by their week gain, best first;
    none without a day left in the week."""
    p = ev.problem
    if not p.horizons["week"][0].days:
        return []
    base = valued(ev, week_set, SET, out)
    ranked = [
        valued(ev, moves, SEARCH, out)
        for moves in search(ev, blocks(p, swaps, stream_plan), allowed)
    ]
    ranked.sort(key=lambda w: (-w.total["week"], -w.total.get("three", 0.0), len(w.steps)))
    seen = {key_of(p, week_set)}
    found = []
    for w in ranked:
        if (k := key_of(p, w.moves)) not in seen:
            seen.add(k)
            found.append(w)
    floor = st.floor_of(p)
    if found and found[0].total["week"] > base.total["week"] + floor:
        plans = [found[0], *sorted([base, *found[1:]], key=lambda w: -w.total["week"])]
    else:
        plans = [base, *found]
    return plans[:WEEK_PLANS]


def for_queue(
    ev: mv.Evaluator, plans: Sequence[WeekPlan], three_set: Sequence[mv.Move], key: str = "three"
) -> WeekPlan | None:
    """The plan the queue takes instead of the three weeks' set (the ruling's second answer): the
    one worth most on ``key`` (the queue's judging horizon) among those that beat the set there
    by the plan floor; None when none does or a plan has no step. Only a plan that keeps the
    rules (:func:`valid`) is weighed: plan 1, the week's recommended set, may take more steps than
    :data:`PLAN_STEPS` or more moves a day than the cap, and then never takes the queue (the
    master's ruling of 2026-10-29)."""
    p = ev.problem
    floor = st.floor_of(p)
    against = ev.value(key, three_set)
    better = [
        w
        for w in plans
        if w.steps and valid(p, w.moves) and ev.value(key, w.moves) > against + floor
    ]
    return max(better, key=lambda w: ev.value(key, w.moves), default=None)
