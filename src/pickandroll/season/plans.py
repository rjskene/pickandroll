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
(:func:`valued`). A plan is kept only when the season guard holds on it (``allowed``). The pool
also takes the three weeks' set's moves, so a plan can carry a lasting pickup with the week's
streamers, and the beam's cheap score then weighs the three weeks as the plan's score does.

The roster's own changes inside the week are listed on their day as zero-choice steps
(:class:`Back`): a cleared player's activation, a held-slot move's comeback and a held player's
return, each with the drop it forces (``moves.comebacks``). A held return's increment is the plan
with him back less the plan with him held past the horizons; it is shown, never summed in the
total. A heuristic: the plans are recommended, never optimal. Plan 1 is the recommended week set
unless a searched plan beats its week by the plan floor (``stream.floor_of``).

The queue (:func:`for_queue`, the user's ruling of 2026-11-06) weighs this week first: a plan's
score is its week gain plus ``three_weight`` times its three-week gain, and the plan with the
highest score leads when it keeps the rules and beats the three weeks' set by the plan floor on
that score. Standings count each category as a win, so expected categories (points in a points
league) are the measure and the matchup odds a headline beside them. In a playoff week a matchup
decides who advances: the score is the matchup odds, the floor :data:`PLAYOFF_FLOOR`, and the
three weeks do not count.

A weekly add and a claim are not spent on a step that gives the plan nothing (:func:`trimmed`, the
master's ruling of 2026-11-06): the plan that leads loses, lowest first, each step whose removal
keeps it valid and costs its score less than :data:`TRIM_SHARE` of the floor, leave-one-out rather
than by increment, and what remains faces the set again. A chain step a later step drops stays,
since the plan without it is not valid. The Moves card keeps the plan as searched; the queue, the
log and what executes are the trimmed plan. Pure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from . import moves as mv
from . import stream as st
from . import weekly as wk

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
#: The weight of the three weeks in a plan's score: the default of the knob ``three_weight``
#: (docs/AUTOPILOT.md section 6). The Monday step never moves it.
THREE_WEIGHT = 0.33
#: What a plan must beat the three weeks' set by on the matchup odds in a playoff week: 3
#: percentage points.
PLAYOFF_FLOOR = 0.03
#: A step of the plan the queue takes comes out when it costs less than this share of the floor.
TRIM_SHARE = 0.5


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
    three_set: Sequence[mv.Move] = (),
) -> list[tuple[mv.Move, ...]]:
    """The pool a plan's steps come from: the week's best single moves (``swaps``, the week's
    ``single_swaps``), each a block of one, each stream spot's chain, whole, and each of the three
    weeks' set's moves, a block of one, whatever it gains this week."""
    ranked = sorted(
        (c for c, g in swaps.items() if g and g[0].gain > mv.EPS),
        key=lambda c: (-swaps[c][0].gain, c),
    )
    out: list[tuple[mv.Move, ...]] = []
    for cand in ranked[:SINGLES]:
        out += [(mv.Move(cand, g.drop),) for g in swaps[cand][:DROPS] if g.gain > mv.EPS]
    if stream_plan is not None:
        out += [tuple(sp.steps) for sp in stream_plan.spots if sp.steps]
    out += [(m,) for m in three_set]
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
    weight: float = 0.0,
) -> list[tuple[mv.Move, ...]]:
    """The best :data:`EXACT` plans by cheap score: a beam over the blocks of ``pool``, each
    block's cheap score its own :func:`score` at ``weight``, every plan kept to :func:`valid` and
    ``allowed``."""
    p = ev.problem
    cheap = [score(ev, b, weight) for b in pool]
    beam: list[tuple[tuple[mv.Move, ...], float, int]] = [((), 0.0, -1)]
    seen: dict[frozenset[mv.Move], tuple[tuple[mv.Move, ...], float]] = {}
    for _ in range(PLAN_STEPS):
        nxt = []
        for moves, worth, last in beam:
            for i in range(last + 1, len(pool)):
                trial = (*moves, *pool[i])
                if valid(p, trial) and (allowed is None or allowed(trial)):
                    nxt.append((trial, worth + cheap[i], i))
        if not nxt:
            break
        nxt.sort(key=lambda x: -x[1])
        beam = nxt[:BEAM]
        for moves, worth, _ in beam:
            seen.setdefault(frozenset(moves), (moves, worth))
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


def every_plan(
    ev: mv.Evaluator,
    week_set: Sequence[mv.Move],
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    stream_plan: st.Plan | None = None,
    allowed: mv.Allowed | None = None,
    out: HeldOut | None = None,
    three_set: Sequence[mv.Move] = (),
    weight: float = 0.0,
) -> list[WeekPlan]:
    """Every plan the search valued, distinct by adds and days (:func:`key_of`; of the searched
    plans with the same adds and days only the one with the best score at ``weight`` is kept, and
    none with the set's: the set is plan 1's idea): plan 1 the recommended ``week_set`` unless a
    searched plan beats its week by the plan floor, the others by their week gain, best first;
    none without a day left in the week."""
    p = ev.problem
    if not p.horizons["week"][0].days:
        return []
    base = valued(ev, week_set, SET, out)
    ranked = [
        valued(ev, moves, SEARCH, out)
        for moves in search(ev, blocks(p, swaps, stream_plan, three_set), allowed, weight)
    ]

    def three(w: WeekPlan) -> float:
        return w.total.get("three", 0.0)

    ranked.sort(key=lambda w: (-(w.total["week"] + weight * three(w)), -three(w), len(w.steps)))
    seen = {key_of(p, week_set)}
    found = []
    for w in ranked:
        if (k := key_of(p, w.moves)) not in seen:
            seen.add(k)
            found.append(w)
    found.sort(key=lambda w: (-w.total["week"], -three(w), len(w.steps)))
    floor = st.floor_of(p)
    if found and found[0].total["week"] > base.total["week"] + floor:
        plans = [found[0], *sorted([base, *found[1:]], key=lambda w: -w.total["week"])]
    else:
        plans = [base, *found]
    return plans


def week_plans(
    ev: mv.Evaluator,
    week_set: Sequence[mv.Move],
    swaps: Mapping[int, Sequence[mv.SwapGain]],
    stream_plan: st.Plan | None = None,
    allowed: mv.Allowed | None = None,
    out: HeldOut | None = None,
) -> list[WeekPlan]:
    """The week's plans the Moves card shows, at most :data:`WEEK_PLANS`, of :func:`every_plan`."""
    return every_plan(ev, week_set, swaps, stream_plan, allowed, out)[:WEEK_PLANS]


def shown(plans: Sequence[WeekPlan], chosen: WeekPlan | None) -> list[WeekPlan]:
    """The plans the card shows of ``plans``: the first :data:`WEEK_PLANS`, the plan the queue
    took in the last place when no plan among them has its moves."""
    top = list(plans[:WEEK_PLANS])
    if chosen is None or place(top, chosen) is not None:
        return top
    return [*top[: WEEK_PLANS - 1], chosen]


def place(plans: Sequence[WeekPlan], chosen: WeekPlan) -> int | None:
    """Where the plan with ``chosen``'s moves stands in ``plans``, None when none has them."""
    moves = set(chosen.moves)
    return next((i for i, w in enumerate(plans) if set(w.moves) == moves), None)


def score(ev: mv.Evaluator, moves: Sequence[mv.Move], weight: float) -> float:
    """A set's or plan's score in the regular season: its week gain plus ``weight`` times its
    three-week gain. In a playoff week the weight is 0 for everything but the gate (:func:`gate`)."""
    return ev.gain("week", moves) + weight * ev.gain("three", moves)


def matchup(ev: mv.Evaluator, moves: Sequence[mv.Move]) -> float | None:
    """The odds of winning this week's matchup with ``moves`` made, over the opponents the week
    reads (``weekly.matchup_won``); None with no opponent read."""
    weeks = ev.odds("week", moves)
    if not weeks or not weeks[0]:
        return None
    return sum(wk.matchup_won(o) for o in weeks[0]) / len(weeks[0])


def step_score(step: Step, weight: float) -> float:
    """What a step adds to its plan's score: its increments, weighted as :func:`score`."""
    return step.gain["week"] + weight * step.gain.get("three", 0.0)


def waits_on(
    ev: mv.Evaluator, steps: Sequence[Step], j: int, weight: float, min_gain: float
) -> list[int]:
    """The earlier steps of a plan step ``j`` waits on before it is placed (#364, item 4): each
    step ``i`` before it that ``j`` does not stand without. ``j`` stands without ``i`` when it
    keeps its room and its worth with ``i`` not made: it does not drop ``i``'s add, the steps up
    to ``j`` less ``i`` still fit (:func:`moves.feasible`), and ``j`` adds at least ``min_gain``
    to the steps before it less ``i``, on the plan's score (:func:`step_score`'s weights). The
    plan chose ``j`` given ``i``: a step that waits on nothing goes in the night it is due even
    if ``i`` is lost at 4 am."""
    p = ev.problem
    move = steps[j].move
    out = []
    for i in range(j):
        earlier = steps[i].move
        if move.drop is not None and move.drop == earlier.add:
            out.append(i)
            continue
        before = [s.move for k, s in enumerate(steps[:j]) if k != i]
        if not mv.feasible(p, [*before, move]):
            out.append(i)
            continue
        gain = {h: ev.value(h, [*before, move]) - ev.value(h, before) for h in p.horizons}
        if step_score(Step(move, steps[j].day, gain), weight) < min_gain:
            out.append(i)
    return out


def gate(
    ev: mv.Evaluator, moves: Sequence[mv.Move], weight: float, playoff: bool = False
) -> float | None:
    """What :func:`for_queue` chooses on: the :func:`score`, or in a playoff week the
    :func:`matchup` odds, None with no opponent read."""
    return matchup(ev, moves) if playoff else score(ev, moves, weight)


def gate_floor(problem: mv.MoveProblem, playoff: bool = False) -> float:
    """What a plan must beat the three weeks' set by on :func:`gate`."""
    return PLAYOFF_FLOOR if playoff else st.floor_of(problem)


def trimmed(
    ev: mv.Evaluator,
    plan: WeekPlan,
    weight: float = THREE_WEIGHT,
    playoff: bool = False,
    allowed: mv.Allowed | None = None,
    out: HeldOut | None = None,
) -> WeekPlan:
    """``plan`` without the steps that give it nothing: while some step's removal leaves a plan
    that keeps the rules and the season guard and costs less than :data:`TRIM_SHARE` of
    :func:`gate_floor` on :func:`gate`, leave-one-out, the one that costs least comes out. A plan
    is left at least one step. ``plan`` itself when no step comes out."""
    p = ev.problem
    margin = TRIM_SHARE * gate_floor(p, playoff)
    moves = list(plan.moves)
    while len(moves) > 1:
        now = gate(ev, moves, weight, playoff)
        costs = []
        for m in moves:
            rest = [o for o in moves if o is not m]
            then = gate(ev, rest, weight, playoff)
            if (
                now is not None
                and then is not None
                and now - then < margin
                and valid(p, rest)
                and mv.admitted(p, rest, allowed)
            ):
                costs.append((now - then, m))
        if not costs:
            break
        gone = min(costs, key=lambda c: c[0])[1]
        moves = [o for o in moves if o is not gone]
    return plan if len(moves) == len(plan.moves) else valued(ev, moves, plan.source, out)


def for_queue(
    ev: mv.Evaluator,
    plans: Sequence[WeekPlan],
    three_set: Sequence[mv.Move],
    weight: float = THREE_WEIGHT,
    playoff: bool = False,
    allowed: mv.Allowed | None = None,
    out: HeldOut | None = None,
) -> WeekPlan | None:
    """The plan the queue takes instead of the three weeks' set: the one with the highest
    :func:`gate` among those that beat the set's by :func:`gate_floor`, :func:`trimmed`, while it
    still beats the set; None when none does, when no plan has a step, or in a playoff week with no
    opponent read, and the queue then takes the set. Only a plan that keeps the rules
    (:func:`valid`) and the season guard (``allowed``) is weighed: plan 1, the week's recommended
    set, may take more steps than :data:`PLAN_STEPS` or more moves a day than the cap, and then
    never takes the queue (the master's ruling of 2026-10-29)."""
    p = ev.problem
    against = gate(ev, three_set, weight, playoff)
    if against is None:
        return None
    line = against + gate_floor(p, playoff)
    top = line
    best = None
    for w in plans:
        if not w.steps or not valid(p, w.moves) or not mv.admitted(p, list(w.moves), allowed):
            continue
        value = gate(ev, w.moves, weight, playoff)
        if value is not None and value > top:
            best, top = w, value
    if best is None:
        return None
    best = trimmed(ev, best, weight, playoff, allowed, out)
    value = gate(ev, best.moves, weight, playoff)
    return best if value is not None and value > line else None
