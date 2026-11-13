"""The engine as a policy (#172, PR 2b): the move problem built from simulated state, the
tiers that solve it, and the executor that lands what they decide.

:func:`problem_of` mirrors ``api.season_moves.build`` step for step from in-memory inputs: the
spans from the setup's calendar, the opponents projected with ``weekly.project_week`` from the
shared beliefs, the candidates from the pool, the add limits from the league's rule and the adds
used, the keep rule's inputs from the same beliefs, then the knobs. **Every knob comes in as a
mapping of the nine names ``season.progress.KNOBS`` lists; a missing name raises; nothing here
reads the knob file.** The season guard is ``moves.season_guard(ros)`` with ``ros`` the engine's
own rest-of-season value of a move (``season.decisions.move_projection``) under the simulated
world's beliefs, passed explicitly into every search.

Three tiers. **Exact** is the live moves route: single swaps over every candidate, the best
``POOL`` by gain, the recommended set priced by re-solves on the horizon the autopilot queues
(``three``), the week's streaming plan beside it; or, when the arm says ``executes: weighted``,
the strategy route's weighted set under the horizon weight knob (its search, no program).
**Surrogate** is the same evaluator on the ``POOL`` best candidates by value times games, the
greedy search alone, solved on Monday and Thursday. **Ranking** swaps the pool's best by value
times games for the roster's worst the keep rule does not keep, no evaluator.

Executions are the autopilot's (``season.autopilot``): a decided move lands the next day, at
most ``daily_cap`` a day and the league's adds a week, free agents only, never a kept player
dropped. The executor keeps the roster as Yahoo would: a held player whose status has cleared
comes back to the bench the next morning and, over the league's spots, the least valuable active
player leaves (the engine's rule for a cleared player); the held-slot moves a set needs are made
before its adds land; an add that needs an active spot (no drop, or a churn's held drop, #221)
takes a bench slot and is gone when none is open. Phase 1 models no waiver clear dates and no
bids: ``EXECUTIONS`` names that in every run's payload.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from .. import decisions as dl
from .. import moves as mv
from .. import strategy as sg
from .. import stream as st
from .. import weekly as wk
from ..calendar import Week
from ..progress import KNOBS
from .state import BENCH, Setup, SimState, add_totals

#: The execution model every run's payload names (#172, the master's ruling on PR 2's plan).
EXECUTIONS = "free_agents_next_day"
#: A decided move lands this long after it is made: it takes effect then, and is charged to the
#: week of the day it is made, as Yahoo charges a free-agent add (never the week it lands in).
LANDS_AFTER = timedelta(1)
#: The live moves route's figures (``api.season_moves``): the candidates the recommended set is
#: searched among and the least gain a move must add.
POOL = 30
MIN_GAIN = 0.01
WEEKS_AHEAD = 4
HORIZONS = ("week", "three")
#: The set the autopilot queues (``season.autopilot.QUEUE_SET``).
QUEUE_SET = "three"
WEIGHTED = "weighted"
EXECUTES = (QUEUE_SET, WEIGHTED)
TIERS = ("exact", "surrogate", "ranking")
#: The surrogate's solve days (Monday 0, Thursday 3).
SURROGATE_DAYS = (0, 3)
#: An absence read without a return date is taken to last this long (``moves.SHORT_ABSENCE_DAYS``).
DEFAULT_ABSENCE_DAYS = mv.SHORT_ABSENCE_DAYS


def knob(knobs: Mapping[str, Any], name: str) -> Any:
    """A knob by name; every one of ``KNOBS`` must be present (None is a value)."""
    if name not in KNOBS:
        raise KeyError(f"{name!r} is not a knob")
    if name not in knobs:
        raise KeyError(f"knob {name!r} missing: an arm names every knob explicitly")
    return knobs[name]


def check_knobs(knobs: Mapping[str, Any]) -> dict[str, Any]:
    """The knobs as given, every name present."""
    return {name: knob(knobs, name) for name in KNOBS}


@dataclass(frozen=True)
class Built:
    """The move problem for one team on one day, with what the tiers need beside it."""

    problem: mv.MoveProblem
    rule: mv.KeepRule
    scorer: Mapping[str, Any]
    week: Week
    weeks_left: int
    knobs: Mapping[str, Any]
    team: int


@dataclass(frozen=True)
class Decision:
    """What a tier decided for one team on one day."""

    moves: tuple[mv.Move, ...] = ()
    #: The held-slot moves the set needs (player, slot).
    held: tuple[tuple[int, str], ...] = ()
    #: The week's streaming plan's steps, recorded; executed only when the arm says so.
    plan: tuple[mv.Move, ...] = ()
    solves: int = 0
    source: str = "none"


NONE = Decision()


# --------------------------------------------------------------------------- the problem
def members_of(
    setup: Setup,
    keys: Sequence[int],
    status: Mapping[int, str | None],
) -> list[mv.Member]:
    """``(key, Player)`` for ``keys`` with the statuses the policy sees."""
    return [(k, setup.players[k].player(status.get(k))) for k in keys if k in setup.players]


def problem_of(
    setup: Setup,
    state: SimState,
    me: int,
    knobs: Mapping[str, Any],
    beliefs: Mapping[int, Mapping[str, float]],
    status: Mapping[int, str | None],
    returns: Mapping[int, date],
    weeks_ahead: int = WEEKS_AHEAD,
) -> Built | None:
    """The move problem for ``me`` on ``state.day``; None with no week left. Mirrors
    ``api.season_moves.build`` from in-memory inputs."""
    knobs = check_knobs(knobs)
    day = state.day
    weeks = setup.calendar.ahead(day, weeks_ahead)
    if not weeks:
        return None
    this = weeks[0]
    days0 = this.days(day)
    if not days0:
        return None
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    cats = tuple(setup.cats)
    slots = setup.starting_slots()
    value = wk.per_game_values(beliefs, cats, points)
    roster_of = {t: state.active(t) for t in setup.teams}

    def project(team: int, days: Sequence[date], this_week: bool) -> wk.TeamWeek:
        members = members_of(setup, roster_of.get(team, ()), status)
        return wk.project_week(members, beliefs, days, setup.schedule, slots, value, this_week)

    other = next(
        (b if a == me else a for a, b in setup.pairings.get(this.number, ()) if me in (a, b)), None
    )
    so_far = state.totals.get(this.number, {})
    week_span = mv.WeekSpan(
        tuple(days0),
        True,
        (project(other, days0, True),) if other is not None else (),
        dict(so_far.get(me, {})),
        (dict(so_far.get(other, {})),) if other is not None else (),
        None,
    )
    field_teams = [t for t in setup.teams if t != me]
    later = tuple(
        mv.WeekSpan(
            tuple(w.days()),
            False,
            tuple(project(t, w.days(), False) for t in field_teams),
            games=None,
        )
        for w in weeks[1:]
    )
    roster = tuple(members_of(setup, roster_of[me], status))
    held_pairs = state.held(me)
    held = tuple(members_of(setup, [k for k, _ in held_pairs], status))
    held_slots = {k: slot for k, slot in held_pairs}
    slot_count = Counter(setup.roster_slots)
    taken = Counter(slot for k, slot in held_pairs if not mv.is_cleared(status.get(k), slot))
    held_open = {k: slot_count.get(k, 0) - taken.get(k, 0) for k in mv.HELD}
    # Free agents land the next day: every candidate's move takes effect tomorrow.
    effective_day = day + LANDS_AFTER
    candidates = tuple(members_of(setup, sorted(k for k in state.pool if k in beliefs), status))
    effective = {k: effective_day for k, _ in candidates}
    limit = setup.max_weekly_adds
    used = int(state.adds_used.get(me, 0))
    # The engine charges a move to the week its day falls in, and a move's day here is the day
    # it lands, one after it is made. So each week's window is its days shifted by the lag: a
    # move made on Sunday lands Monday and spends the ending week's adds, as on Yahoo. This
    # week's window opens today, so a plan step dated today is charged here too.
    limits = tuple(
        mv.AddLimit(
            day if i == 0 else w.start + LANDS_AFTER,
            w.end + LANDS_AFTER,
            None if limit is None else (max(0, limit - used) if i == 0 else limit),
        )
        for i, w in enumerate(weeks)
    )
    spots = setup.spots()
    pool_n = max(1, len(setup.teams) * spots)
    # Two of ``build``'s fields stay at their defaults here, on purpose. ``cantcut`` (#222) is
    # Yahoo's can't-cut list as read off an add page: a simulated world has none. ``claims``
    # (#221) is the candidates on waivers, whose churns the engine offers only when the held
    # player is worth nothing: every add is a free agent under ``free_agents_next_day``, so none;
    # the waiver execution model sets it to every candidate, as the live route does for "W".
    problem = mv.MoveProblem(
        roster=roster,
        held=held,
        spots=spots,
        held_open={k: n for k, n in held_open.items() if n > 0},
        candidates=candidates,
        effective=effective,
        first_day=day,
        rates=beliefs,
        schedule=setup.schedule,
        slots=slots,
        value=value,
        cats=cats,
        points=points,
        no_games=frozenset(),
        horizons={"week": (week_span,), "three": later},
        limits=limits,
        returns={k: d for k, d in returns.items() if k in dict(roster) or k in held_slots},
        held_slots=held_slots,
    )
    season_value = wk.per_game_values(beliefs, cats, points, pool_n)
    dead = wk.line_value(beliefs, cats, points, pool_n)({})
    average = 0.0
    if points:
        best = sorted(season_value.values(), reverse=True)[:pool_n]
        average = sum(best) / len(best) if best else 0.0
    problem = replace(
        problem,
        season_value=season_value,
        dead=dead,
        average=average,
        season_end=setup.season_end,
        floor=float(knob(knobs, "protection_floor")),
        plan_floor=float(knob(knobs, "plan_floor_points" if points else "plan_floor_cats")),
        daily_cap=int(knob(knobs, "daily_cap")),
    )
    rule = mv.keep_rule(problem)
    problem = replace(problem, kept=rule.kept)
    scorer = wk.scorer_of(beliefs, cats, points, pool_n)
    weeks_left = sum(1 for w in setup.calendar.weeks if w.number > this.number)
    return Built(problem, rule, scorer, this, weeks_left, knobs, me)


def ros_of(built: Built) -> Callable[[mv.Move], float | None]:
    """Each move's rest of the season under the simulated beliefs, the engine's own figure
    (``decisions.move_projection``'s season horizon), cached; the season guard's input."""
    p = built.problem
    seen: dict[tuple[int, int | None, date], float | None] = {}

    def ros(m: mv.Move) -> float | None:
        k = (m.add, m.drop, mv.day_of(p, m))
        if k not in seen:
            proj = dl.move_projection(p, built.scorer, *k)
            s = ((proj or {}).get("horizons") or {}).get(dl.SEASON)
            seen[k] = None if s is None else s.get("value")
        return seen[k]

    return ros


def guard_of(built: Built) -> mv.Allowed:
    return mv.season_guard(ros_of(built))


# --------------------------------------------------------------------------- the tiers
def _weight(knobs: Mapping[str, Any], weeks_left: int) -> float:
    key = str(knob(knobs, "horizon_weight") or "natural")
    for w in sg.weights(weeks_left):
        if w.key == key:
            return w.lam
    raise KeyError(f"horizon weight {key!r} is not one of {sg.WEIGHT_KEYS}")


def exact(built: Built, executes: str = QUEUE_SET, with_plan: bool = True) -> Decision:
    """The live moves route's set on ``QUEUE_SET`` (or the strategy route's weighted set), the
    season guard on every search, the streaming plan beside."""
    p = built.problem
    ev = mv.Evaluator(p)
    allowed = guard_of(built)
    solves = 0
    if executes == WEIGHTED:
        swaps = {key: mv.single_swaps(ev, key) for key in HORIZONS}
        gains = {key: {c: g[0].gain for c, g in swaps[key].items() if g} for key in HORIZONS}
        pool = sg.pool_of(gains, POOL)
        w = sg.Weighted(ev, _weight(built.knobs, built.weeks_left), built.weeks_left)
        moves = mv.search(w, sg.WEIGHTED, pool, keep=p.kept, min_gain=MIN_GAIN, allowed=allowed)
        held = tuple(mv.held_used(p, moves))
        solves += 1
    else:
        swaps = mv.single_swaps(ev, QUEUE_SET)
        ranked = sorted(
            (c for c, g in swaps.items() if g and g[0].gain > MIN_GAIN),
            key=lambda c: -swaps[c][0].gain,
        )
        rec = mv.recommend(ev, QUEUE_SET, ranked[:POOL], min_gain=MIN_GAIN, allowed=allowed)
        moves = tuple(pm.move for pm in rec.moves)
        held = tuple(rec.held)
        solves += 1
    plan: tuple[mv.Move, ...] = ()
    if with_plan:
        week_set = mv.search(
            ev,
            "week",
            [c for c, _ in p.candidates][:POOL],
            keep=p.kept,
            min_gain=MIN_GAIN,
            allowed=allowed,
        )
        planned = st.plan(ev, built.rule, week_set, p.value, allowed=allowed)
        if planned is not None and st.recommended(ev, planned):
            plan = planned.steps
        solves += 1
    return Decision(tuple(moves), held, plan, solves, "exact")


def _games(built: Built, member: mv.Member, from_day: date) -> int:
    p = built.problem
    days = [d for d in p.horizons["week"][0].days if d >= from_day]
    return len(wk.game_days(member[1].nba_team, days, p.schedule))


def surrogate(built: Built, pool: int = POOL) -> Decision:
    """The same evaluator on the ``pool`` best candidates by value times games this week, the
    greedy search alone on ``QUEUE_SET``, the season guard kept."""
    p = built.problem
    start = p.first_day + timedelta(1)
    ranked = sorted(
        p.candidates,
        key=lambda m: (-p.value.get(m[0], 0.0) * max(1, _games(built, m, start)), m[0]),
    )
    ev = mv.Evaluator(p)
    allowed = guard_of(built)
    moves = mv.search(
        ev,
        QUEUE_SET,
        [k for k, _ in ranked[:pool]],
        keep=p.kept,
        min_gain=MIN_GAIN,
        allowed=allowed,
    )
    return Decision(tuple(moves), tuple(mv.held_used(p, moves)), (), 1, "surrogate")


def ranking(built: Built) -> Decision:
    """The pool's best by value times games this week for the roster's worst the keep rule does
    not keep, when it gains; no evaluator."""
    p = built.problem
    start = p.first_day + timedelta(1)

    def worth(m: mv.Member) -> float:
        return p.value.get(m[0], 0.0) * _games(built, m, start)

    adds = sorted(p.candidates, key=lambda m: (-worth(m), m[0]))
    drops = sorted((m for m in p.roster if m[0] not in p.kept), key=lambda m: (worth(m), m[0]))
    if not adds or not drops or p.limits and p.limits[0].adds is not None and p.limits[0].adds <= 0:
        return Decision(source="ranking")
    add, drop = adds[0], drops[0]
    if worth(add) <= worth(drop):
        return Decision(source="ranking")
    move = mv.Move(add[0], drop[0])
    if not mv.feasible(p, (move,)):
        return Decision(source="ranking")
    return Decision((move,), (), (), 0, "ranking")


def decide(built: Built, tier: str, executes: str = QUEUE_SET, with_plan: bool = True) -> Decision:
    """The tier's decision on the day: the surrogate solves on its days only."""
    if tier == "exact":
        return exact(built, executes, with_plan)
    if tier == "surrogate":
        if built.problem.first_day.weekday() not in SURROGATE_DAYS:
            return Decision(source="surrogate")
        return surrogate(built)
    if tier == "ranking":
        return ranking(built)
    raise ValueError(f"unknown tier {tier!r}: one of {TIERS}")


# --------------------------------------------------------------------------- the executor
def queue(
    state: SimState,
    team: int,
    decision: Decision,
    daily_cap: int,
    limit: int | None,
    execute_plan: bool = False,
    spots: int | None = None,
) -> SimState:
    """The moves of ``decision`` that may land tomorrow, within the day's cap and the week's
    adds: the set's in order, then the plan's steps due tomorrow when the arm executes plans.
    With them the held-slot moves those moves need: the decision's, in order, one for each kept
    add that needs an active spot (no drop, or a churn's held drop) beyond the spots open today
    (``spots`` less the active roster; none when ``spots`` is None), as the engine pairs them."""
    moves = list(decision.moves)
    if execute_plan:
        tomorrow = state.day + timedelta(1)
        moves += [m for m in decision.plan if m.day is None or m.day <= tomorrow]
    used = int(state.adds_used.get(team, 0))
    kept: list[mv.Move] = []
    seen_adds: set[int] = set()
    for m in moves:
        if len(kept) >= max(0, daily_cap):
            break
        if limit is not None and used + len(kept) >= limit:
            break
        if m.add in seen_adds or m.add not in state.pool:
            continue
        seen_adds.add(m.add)
        kept.append(mv.Move(m.add, m.drop))
    pending = dict(state.pending)
    pending[team] = tuple(kept)
    held_keys = {k for k, _ in state.held(team)}
    need = sum(1 for m in kept if m.drop is None or m.drop in held_keys)
    if spots is not None:
        need -= max(0, spots - len(state.active(team)))
    pending_held = dict(state.pending_held)
    pending_held[team] = tuple(decision.held[: max(0, need)])
    return replace(state, pending=pending, pending_held=pending_held)


def _active_count(roster: Sequence[tuple[int, str]]) -> int:
    return sum(1 for _, slot in roster if slot not in mv.HELD)


def _activate(
    roster: list[tuple[int, str]],
    spots: int | None,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
) -> list[int]:
    """A team's held players whose status no longer fits their slot (``moves.is_cleared``) come
    back to the bench; then, while the active roster is over ``spots``, its least valuable active
    player by ``value`` leaves, as the engine charges a cleared player (``moves.comebacks``), the
    keep rule apart (the executor does not see it). The players who left."""
    for i, (k, slot) in enumerate(roster):
        if slot in mv.HELD and mv.is_cleared(status.get(k), slot):
            roster[i] = (k, BENCH)
    out: list[int] = []
    # The keep rule stays out of the executor: the engine's ``comebacks`` never sends a kept
    # player while another can go, but the executor sees no problem and no rule, only the day's
    # values. The whole active roster is weighed, the returning player included.
    while spots is not None and _active_count(roster) > spots:
        weakest = min(
            (k for k, slot in roster if slot not in mv.HELD),
            key=lambda k: (value.get(k, 0.0), k),
        )
        roster.remove(next(x for x in roster if x[0] == weakest))
        out.append(weakest)
    return out


def land(
    state: SimState,
    order: Sequence[int],
    spots: int | None = None,
    slot_counts: Mapping[str, int] | None = None,
    status: Mapping[int, str | None] | None = None,
    value: Mapping[int, float] | None = None,
) -> SimState:
    """Yesterday's queued moves land, team by team in ``order``. First, given the day's ``status``
    and ``value``, each team's cleared held players come back and the active roster is trimmed
    to ``spots`` (:func:`_activate`; each player it sends counts in ``forced_drops``, never in
    ``executed`` or ``gone``). Then a churn's held drop goes to the pool on his own, as the
    engine times it (#221), freeing his slot; then the held-slot moves it queued, each player to
    his held slot while the slot has room (``slot_counts``, the league's slots by kind); then the
    adds: one with a drop of an active player takes his slot; one that needs an active spot (no
    drop, or the churn's) takes a bench slot while the active roster is under ``spots`` and is
    otherwise gone, like an add another team took first (a churn's drop stands either way, made
    before the add; a plain swap's is never made). Without ``spots`` nothing is counted."""
    rosters = {t: list(r) for t, r in state.rosters.items()}
    pool = set(state.pool)
    adds_used = dict(state.adds_used)
    executed, gone, forced = state.executed, state.gone, state.forced_drops
    for team in order:
        roster = rosters.setdefault(team, [])
        if status is not None and value is not None:
            left = _activate(roster, spots, status, value)
            pool.update(left)
            forced += len(left)
        moves = state.pending.get(team, ())
        churned: set[int] = set()
        for m in moves:
            if m.drop is None:
                continue
            idx = next(
                (i for i, (pk, s) in enumerate(roster) if pk == m.drop and s in mv.HELD), None
            )
            if idx is not None:
                del roster[idx]
                pool.add(m.drop)
                churned.add(m.drop)
        for k, slot in state.pending_held.get(team, ()):
            room = slot_counts is None or sum(1 for _, s in roster if s == slot) < slot_counts.get(
                slot, 0
            )
            idx = next(
                (i for i, (pk, s) in enumerate(roster) if pk == k and s not in mv.HELD), None
            )
            if idx is not None and room:
                roster[idx] = (k, slot)
        for m in moves:
            if m.add not in pool:
                gone += 1
                continue
            idx = None
            if m.drop is not None and m.drop not in churned:
                idx = next((i for i, (pk, _) in enumerate(roster) if pk == m.drop), None)
                if idx is None:
                    gone += 1
                    continue
            if idx is None:
                if spots is not None and _active_count(roster) >= spots:
                    gone += 1
                    continue
                slot = BENCH
            else:
                slot = roster[idx][1]
                pool.add(roster[idx][0])
                del roster[idx]
            roster.append((m.add, slot))
            pool.discard(m.add)
            adds_used[team] = adds_used.get(team, 0) + 1
            executed += 1
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(pool),
        adds_used=adds_used,
        pending={},
        pending_held={},
        executed=executed,
        gone=gone,
        forced_drops=forced,
    )


def new_week(state: SimState) -> SimState:
    """Monday: the adds used this week start over."""
    return replace(state, adds_used={})


# --------------------------------------------------------------------------- the day's lineup
def starters_of(
    setup: Setup,
    state: SimState,
    team: int,
    day: date,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
) -> dict[int, str]:
    """The day's starters as a lineup set before the games: the active players whose team plays
    today and whom the policy has not heard are out, the most valuable set the slots hold."""
    playing = [
        (k, setup.players[k].positions)
        for k in state.active(team)
        if k in setup.players
        and setup.players[k].nba_team in setup.schedule.get(day, frozenset())
        and status.get(k) not in wk.OUT_ALL
        and status.get(k) not in wk.OUT_THIS_WEEK
    ]
    return wk.starters(playing, setup.starting_slots(), value)


def score_day(
    setup: Setup,
    state: SimState,
    day: date,
    status: Mapping[int, str | None],
    value: Mapping[int, float],
    line: Callable[[int, date], Mapping[str, float] | None],
) -> SimState:
    """Every team's starters' lines added to the week's totals; a starter without a line (out at
    game time, unheard) adds nothing."""
    week = setup.week_of(day)
    if week is None:
        return state
    for team in setup.teams:
        for k in starters_of(setup, state, team, day, status, value):
            ln = line(k, day)
            if ln:
                state = add_totals(
                    state, week.number, team, {s: x for s, x in ln.items() if s != "minutes_factor"}
                )
    return state
