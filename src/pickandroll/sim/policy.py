"""The engine as a policy (#172, PR 2b): the move problem built from simulated state, the
tiers that solve it, and the executor that lands what they decide.

:func:`problem_of` mirrors ``api.season_moves.build`` step for step from in-memory inputs: the
spans from the setup's calendar, the opponents projected with ``weekly.project_week`` from the
shared beliefs, the candidates from the pool, the add limits from the league's rule and the adds
used, the keep rule's inputs from the same beliefs, then the knobs. **Every knob comes in as a
mapping of the twelve names of** :data:`KNOBS` **(the ten the live knob file takes,
``season.progress.LIVE_KNOBS``, each within the engine's own bounds, and the simulator's two); a
missing name raises; nothing here reads the knob file.** The season guard is
``moves.season_guard(ros)`` with ``ros`` the engine's own rest-of-season value of a move
(``season.decisions.move_projection``) under the simulated world's beliefs, passed explicitly into
every search.

Three tiers, each with the arm's :class:`Fields` (the live route's figures by default). **Exact**
is the live moves route: single swaps over every candidate, the best ``pool`` by gain, the
recommended set priced by re-solves on the horizon the autopilot queues (``three``), the week's
streaming plan beside it; or, when the arm says ``executes: weighted``, the strategy route's
weighted set under the horizon weight knob (its search, no program). **Surrogate** is the same
evaluator on the ``pool`` best candidates by value times games, the greedy search alone, solved
on the ``surrogate_days`` (Monday and Thursday). **Ranking** swaps the pool's best by value times
games for the roster's worst the keep rule does not keep, no evaluator.

**The season term** (:class:`SeasonFigure`, :func:`seasoned`): at a ``season_weight`` above 0,
the exact and the surrogate tiers rank and search on their odds value plus ``season_weight``
times ``ROS_w``, the moves' season value above a dead spot times the games left, a bracket game
counted ``playoff_weight`` times, on the key the arm executes and no other. At ``season_weight``
0 the wrapper is not built and every search runs on the engine's values, as before the term.
:func:`reads` says which knobs a seat reads in a league's :class:`Shape`.

Executions are the autopilot's (``season.autopilot``): a decided move lands the next day, at
most ``daily_cap`` a day and the league's adds a week, free agents only, never a kept player
dropped. The executor keeps the roster as Yahoo would: a held player whose status has cleared
comes back to the bench the next morning and, over the league's spots, the least valuable active
player leaves (the engine's rule for a cleared player); the held-slot moves a set needs are made
before its adds land, each only while its slot has room and accepts the player's status on the
morning it lands (``moves.eligible``: a move is carried out against the day it lands, as an add
another team took is); an add that needs an active spot (no drop, a churn's held drop, #221, or
a held move refused) takes a bench slot and is gone when none is open. Phase 1 models no waiver
clear dates and no bids: ``EXECUTIONS`` names that in every run's payload.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from statistics import median
from typing import Any, Protocol

from .engine import DEFAULTS, LIVE_KNOBS, Week, dl, mv, refused, sg, st, wk
from .state import BENCH, Setup, SimState, add_totals

#: The execution model every run's payload names (#172, the master's ruling on PR 2's plan).
EXECUTIONS = "free_agents_next_day"
#: A decided move lands this long after it is made: it takes effect then, and is charged to the
#: week of the day it is made, as Yahoo charges a free-agent add (never the week it lands in).
LANDS_AFTER = timedelta(1)
#: The live moves route's figures (``api.season_moves``): the candidates the recommended set is
#: searched among and the least gain a move must add. They, the weeks ahead and the surrogate's
#: days are the defaults of an arm's :class:`Fields` and are read nowhere else.
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


#: The simulator's own knobs (#172, PR C): the season term's weight, and the weight of a game in
#: the bracket's weeks inside it.
SIM_KNOBS = ("season_weight", "playoff_weight")
#: Every knob an arm names: the ten the live knob file takes, then the simulator's two.
KNOBS = (*LIVE_KNOBS, *SIM_KNOBS)
#: Each knob's default: the engine's own (``progress.DEFAULTS``), then no season term and a
#: bracket game counted once. The fallback of a league without a knob file.
KNOB_DEFAULTS: Mapping[str, Any] = {**DEFAULTS, "season_weight": 0.0, "playoff_weight": 1.0}
#: The live knobs the engine takes None for: those whose own default is None (the blend weight,
#: the stash threshold, the FAAB sizing).
TAKES_NONE = frozenset(k for k in LIVE_KNOBS if DEFAULTS[k] is None)


def knob(knobs: Mapping[str, Any], name: str) -> Any:
    """A knob by name; every one of ``KNOBS`` must be present (None is a value)."""
    if name not in KNOBS:
        raise KeyError(f"{name!r} is not a knob")
    if name not in knobs:
        raise KeyError(f"knob {name!r} missing: an arm names every knob explicitly")
    return knobs[name]


def knob_refused(name: str, value: Any) -> str | None:
    """Why knob ``name`` may not take ``value``; None when it may. A live knob by the engine's
    own check (``progress.refused``: its choices, a number, a whole one for a count, its minimum
    and its maximum), and None only where the engine's default is None (:data:`TAKES_NONE`); the
    simulator's two are numbers, 0 or more."""
    if name in SIM_KNOBS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f"{name} {value!r} is not a number"
        if not math.isfinite(value):
            return f"{name} {value!r} is not a finite number"
        if value < 0:
            return f"{name} {value} is below its minimum 0"
        return None
    if value is None:
        return None if name in TAKES_NONE else f"{name} is None: the engine takes a value for it"
    return refused(name, value)


def check_knobs(knobs: Mapping[str, Any]) -> dict[str, Any]:
    """The twelve knobs as given, in :data:`KNOBS` order: every name present (an arm names every
    knob explicitly; KeyError), no other name and every value allowed (:func:`knob_refused`;
    ValueError). Each error names the knob and the reason."""
    unknown = [k for k in knobs if k not in KNOBS]
    if unknown:
        raise ValueError(f"knob {unknown[0]!r} is not a knob: one of {', '.join(KNOBS)}")
    out = {name: knob(knobs, name) for name in KNOBS}
    for name, value in out.items():
        why = knob_refused(name, value)
        if why is not None:
            raise ValueError(f"knob {name!r} refused: {why}")
    return out


# --------------------------------------------------------------------------- the arm's fields
#: The arm's four fields beside its knobs, in the order the payload names them.
FIELDS = ("pool", "min_gain", "weeks_ahead", "surrogate_days")


@dataclass(frozen=True)
class Fields:
    """An arm's settings beside its knobs (#172, PR C), the live route's figures by default:
    ``pool``, the candidates a search ranks and searches among; ``min_gain``, the least gain a
    move must add on the key the arm executes (with the season term, on the combined figure);
    ``weeks_ahead``, the weeks a problem looks ahead, this one included (the ``three`` horizon is
    the ``weeks_ahead - 1`` after it, fewer near the season's end); ``surrogate_days``, the
    weekdays the surrogate solves on (Monday 0). Part of a seat's ``repr``, so two seats that
    differ in one never share a decision."""

    pool: int = POOL
    min_gain: float = MIN_GAIN
    weeks_ahead: int = WEEKS_AHEAD
    surrogate_days: tuple[int, ...] = SURROGATE_DAYS

    def payload(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "min_gain": self.min_gain,
            "weeks_ahead": self.weeks_ahead,
            "surrogate_days": list(self.surrogate_days),
        }


DEFAULT_FIELDS = Fields()


def _whole(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def fields_of(spec: Mapping[str, Any]) -> Fields:
    """An arm's fields from its spec, each at its default when the spec names none; a bad value is
    refused by name (ValueError): ``pool`` a whole number, 1 or more; ``min_gain`` a number, 0 or
    more; ``weeks_ahead`` a whole number, 2 or more (the three weeks' set needs a later week);
    ``surrogate_days`` a non-empty set of weekdays 0 to 6."""
    pool = spec.get("pool", POOL)
    if not _whole(pool) or pool < 1:
        raise ValueError(f"pool {pool!r}: a whole number, 1 or more")
    gain = spec.get("min_gain", MIN_GAIN)
    if (
        isinstance(gain, bool)
        or not isinstance(gain, int | float)
        or not math.isfinite(gain)
        or gain < 0
    ):
        raise ValueError(f"min_gain {gain!r}: a number, 0 or more")
    weeks = spec.get("weeks_ahead", WEEKS_AHEAD)
    if not _whole(weeks) or weeks < 2:
        raise ValueError(
            f"weeks_ahead {weeks!r}: a whole number, 2 or more (the three weeks' set needs a "
            "later week)"
        )
    days = spec.get("surrogate_days", SURROGATE_DAYS)
    if (
        isinstance(days, str | bytes)
        or not isinstance(days, Sequence)
        or not days
        or not all(_whole(d) and 0 <= d <= 6 for d in days)
    ):
        raise ValueError(f"surrogate_days {days!r}: a non-empty set of weekdays, 0 (Monday) to 6")
    return Fields(pool, float(gain), weeks, tuple(sorted(set(days))))


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
    #: The days of the bracket's weeks, whose games the season term counts ``playoff_weight``
    #: times (:func:`bracket_days`).
    bracket: frozenset[date] = frozenset()


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


def bracket_days(setup: Setup) -> frozenset[date]:
    """The days of the bracket's weeks (``spec.playoff_weeks`` on the calendar); none when the
    bracket is not read."""
    if setup.spec is None:
        return frozenset()
    weeks = set(setup.spec.playoff_weeks)
    return frozenset(d for w in setup.calendar.weeks if w.number in weeks for d in w.days())


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
    return Built(problem, rule, scorer, this, weeks_left, knobs, me, bracket_days(setup))


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


# --------------------------------------------------------------------------- the season term
class SeasonFigure:
    """``ROS_w``, the season term's figure (#172, PR C), on one problem at one ``playoff_weight``.

    ``worth_w(k)`` (:meth:`worth`) is a player's season value above a dead spot
    (``problem.season_value[k] - problem.dead``, the keep rule's per-game figure) times his
    team's games from the day he counts from to the season's last day, a game on a day of the
    bracket's weeks counted ``playoff_weight`` times. He counts from the move's day, or from his
    return when that is later, as the engine reads it (``moves.back_from``, as
    ``moves.net_of_return`` and ``decisions.move_projection`` apply it); one who does not return
    this season is worth 0, and one without a season value has none. The games are the
    schedule's: a day it has no entry for has no game (a setup's schedule reaches the season's
    last day), and nothing is extrapolated. So at ``playoff_weight`` 1 a healthy player's figure
    is ``moves.worth_from`` and an absent one's ``moves.net_of_return``: the unit of the stash
    threshold (#373), not a third one.

    A move's (:meth:`move`) is the add's less the drop's on the day it counts from
    (``moves.day_of``), the add's alone with no drop, and none when either has no season value;
    a set's (:meth:`of`) is the sum over its moves, a move with none counting zero
    (``moves.season_total``). The unit is a value times games, not expected category wins: the
    season scale (:func:`scale_of`) says what size of ``season_weight`` makes the two alike."""

    def __init__(self, built: Built, playoff_weight: float) -> None:
        p = built.problem
        self.problem = p
        self.playoff_weight = float(playoff_weight)
        self.bracket = built.bracket
        self._players = {**dict(p.candidates), **dict(p.held), **dict(p.roster)}
        self._games: dict[str, tuple[list[date], list[float]]] = {}
        self._worth: dict[tuple[int, date], float | None] = {}

    def games(self, nba_team: str | None, start: date) -> float:
        """``nba_team``'s games on the schedule from ``start`` to the season's last day, a bracket
        day's counted ``playoff_weight`` times."""
        end = self.problem.season_end
        if not nba_team or end is None or start > end:
            return 0.0
        if nba_team not in self._games:
            days = sorted(
                d for d, teams in self.problem.schedule.items() if d <= end and nba_team in teams
            )
            after = [0.0] * (len(days) + 1)
            for i in range(len(days) - 1, -1, -1):
                after[i] = after[i + 1] + (self.playoff_weight if days[i] in self.bracket else 1.0)
            self._games[nba_team] = (days, after)
        days, after = self._games[nba_team]
        return after[bisect_left(days, start)]

    def worth(self, key: int, day: date) -> float | None:
        """``worth_w``: what ``key`` is worth from ``day`` (or his return) to the season's end."""
        memo = (key, day)
        if memo not in self._worth:
            p = self.problem
            value = p.season_value.get(key)
            player = self._players.get(key)
            out: float | None = None
            if value is not None and player is not None:
                back = mv.back_from(p, key, player)
                out = (
                    0.0
                    if back is None
                    else (value - p.dead) * self.games(player.nba_team, max(day, back))
                )
            self._worth[memo] = out
        return self._worth[memo]

    def move(self, m: mv.Move) -> float | None:
        """``ROS_w`` of one move: the add's worth less the drop's, from the day it counts."""
        day = mv.day_of(self.problem, m)
        add = self.worth(m.add, day)
        if m.drop is None:
            return add
        drop = self.worth(m.drop, day)
        return None if add is None or drop is None else add - drop

    def of(self, moves: Iterable[mv.Move]) -> float:
        """``ROS_w`` of a set: its moves' summed, a move with none counting zero."""
        return mv.season_total(self.move, moves)[0]


class Seasoned:
    """A search's values with the season term on the key the arm executes (#172, PR C): the
    shape the engine's searches take (``moves.Valued``). On ``key`` a set's value is ``inner``'s
    plus ``weight`` times its ``ROS_w`` (:class:`SeasonFigure`); every other key is ``inner``'s.
    No moves have no term, so ``base`` is the inner's on every key (``moves.recommend`` reads a
    gain for each)."""

    def __init__(self, inner: mv.Valued, key: str, weight: float, figure: SeasonFigure) -> None:
        self.inner = inner
        self.problem = inner.problem
        self.key = key
        self.weight = float(weight)
        self.figure = figure
        self.base = dict(inner.base)

    def value(self, key: str, moves: Iterable[mv.Move]) -> float:
        moves = tuple(moves)
        v = self.inner.value(key, moves)
        return v + self.weight * self.figure.of(moves) if key == self.key else v

    def gain(self, key: str, moves: Iterable[mv.Move]) -> float:
        return self.value(key, moves) - self.base[key]


def seasoned(built: Built, inner: mv.Valued, key: str) -> mv.Valued:
    """``inner`` with the season term on ``key`` (:class:`Seasoned`) at the arm's
    ``season_weight``; ``inner`` itself at ``season_weight`` 0, where the wrapper is not built and
    the search is the engine's own."""
    weight = float(knob(built.knobs, "season_weight"))
    if weight == 0:
        return inner
    return Seasoned(inner, key, weight, SeasonFigure(built, knob(built.knobs, "playoff_weight")))


# --------------------------------------------------------------------------- the tiers
def _weight(knobs: Mapping[str, Any], weeks_left: int) -> float:
    """The arm's λ on the frontier (``strategy.weights``): its ``horizon_weight``'s; with no week
    after this one the frontier is this week's alone, and so is the weight, whatever the knob."""
    key = str(knob(knobs, "horizon_weight") or "natural")
    frontier = sg.weights(weeks_left)
    for w in frontier:
        if w.key == key:
            return w.lam
    if len(frontier) == 1:
        return frontier[0].lam
    raise KeyError(f"horizon weight {key!r} is not one of {sg.WEIGHT_KEYS}")


def _weighted_pool(ev: mv.Evaluator, fields: Fields) -> list[int]:
    """The weighted search's candidates: the best ``pool`` by single-swap gain on each of the
    week and the three weeks, taken in turn (``strategy.pool_of``)."""
    swaps = {key: mv.single_swaps(ev, key) for key in HORIZONS}
    gains = {key: {c: g[0].gain for c, g in swaps[key].items() if g} for key in HORIZONS}
    return sg.pool_of(gains, fields.pool)


def _three_pool(swaps: Mapping[int, Sequence[mv.SwapGain]], fields: Fields) -> list[int]:
    """The recommended set's candidates: the best ``pool`` by single-swap gain above
    ``min_gain``."""
    ranked = sorted(
        (c for c, g in swaps.items() if g and g[0].gain > fields.min_gain),
        key=lambda c: -swaps[c][0].gain,
    )
    return ranked[: fields.pool]


def exact(
    built: Built,
    executes: str = QUEUE_SET,
    with_plan: bool = True,
    fields: Fields = DEFAULT_FIELDS,
) -> Decision:
    """The live moves route's set on ``QUEUE_SET`` (or the strategy route's weighted set), the
    season guard on every search, the streaming plan beside. With a ``season_weight`` the single
    swaps, the pool's ranking and the recommended set (or the weighted search) all take the
    season term (:func:`seasoned`); the week's plan does not."""
    p = built.problem
    ev = mv.Evaluator(p)
    allowed = guard_of(built)
    solves = 0
    if executes == WEIGHTED:
        pool = _weighted_pool(ev, fields)
        w = seasoned(
            built,
            sg.Weighted(ev, _weight(built.knobs, built.weeks_left), built.weeks_left),
            sg.WEIGHTED,
        )
        moves = mv.search(
            w, sg.WEIGHTED, pool, keep=p.kept, min_gain=fields.min_gain, allowed=allowed
        )
        held = tuple(mv.held_used(p, moves))
        solves += 1
    else:
        scored = seasoned(built, ev, QUEUE_SET)
        swaps = mv.single_swaps(scored, QUEUE_SET)
        rec = mv.recommend(
            scored,
            QUEUE_SET,
            _three_pool(swaps, fields),
            min_gain=fields.min_gain,
            allowed=allowed,
        )
        moves = tuple(pm.move for pm in rec.moves)
        held = tuple(rec.held)
        solves += 1
    plan: tuple[mv.Move, ...] = ()
    if with_plan:
        week_set = mv.search(
            ev,
            "week",
            [c for c, _ in p.candidates][: fields.pool],
            keep=p.kept,
            min_gain=fields.min_gain,
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


def _surrogate_pool(built: Built, fields: Fields) -> list[int]:
    """The surrogate's candidates: the best ``pool`` by value times games this week."""
    p = built.problem
    start = p.first_day + timedelta(1)
    ranked = sorted(
        p.candidates,
        key=lambda m: (-p.value.get(m[0], 0.0) * max(1, _games(built, m, start)), m[0]),
    )
    return [k for k, _ in ranked[: fields.pool]]


def surrogate(built: Built, fields: Fields = DEFAULT_FIELDS) -> Decision:
    """The same evaluator on the ``pool`` best candidates by value times games this week, the
    greedy search alone on ``QUEUE_SET`` (with the season term at a ``season_weight``), the
    season guard kept."""
    p = built.problem
    ev = seasoned(built, mv.Evaluator(p), QUEUE_SET)
    allowed = guard_of(built)
    moves = mv.search(
        ev,
        QUEUE_SET,
        _surrogate_pool(built, fields),
        keep=p.kept,
        min_gain=fields.min_gain,
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


def decide(
    built: Built,
    tier: str,
    executes: str = QUEUE_SET,
    with_plan: bool = True,
    fields: Fields = DEFAULT_FIELDS,
) -> Decision:
    """The tier's decision on the day: the surrogate solves on its days only."""
    if tier == "exact":
        return exact(built, executes, with_plan, fields)
    if tier == "surrogate":
        if built.problem.first_day.weekday() not in fields.surrogate_days:
            return Decision(source="surrogate")
        return surrogate(built, fields)
    if tier == "ranking":
        return ranking(built)
    raise ValueError(f"unknown tier {tier!r}: one of {TIERS}")


# --------------------------------------------------------------------------- the season scale
@dataclass(frozen=True)
class Scale:
    """The season scale on one seat's day (:func:`scale_of`): the median best single swap's gain
    on the executed key without the term, the median of the same swaps' ``ROS_w``, and the first
    over the second (None when the second is 0 or there is none), over ``swaps`` swaps."""

    gain: float | None
    ros: float | None
    ratio: float | None
    swaps: int


def scale_of(
    built: Built,
    tier: str,
    executes: str = QUEUE_SET,
    fields: Fields = DEFAULT_FIELDS,
) -> Scale | None:
    """The season scale (#172, PR C): over the arm's pool on ``built``'s day (the exact tier's
    best ``pool`` by single-swap gain above ``min_gain``, the weighted search's, the surrogate's
    best by value times games), each candidate's best single swap on the key the arm executes,
    without the term. A ``season_weight`` equal to the ratio makes the term about as loud as the
    odds gain. None on the ranking tier and a static seat, which hold no odds. It decides nothing,
    draws nothing and is the same at any ``season_weight``."""
    if tier not in ("exact", "surrogate"):
        return None
    ev = mv.Evaluator(built.problem)
    if tier == "exact" and executes == WEIGHTED:
        pool = _weighted_pool(ev, fields)
        w = sg.Weighted(ev, _weight(built.knobs, built.weeks_left), built.weeks_left)
        best = mv.single_swaps(w, sg.WEIGHTED, pool)
    elif tier == "exact":
        swaps = mv.single_swaps(ev, QUEUE_SET)
        best = {c: swaps[c] for c in _three_pool(swaps, fields)}
    else:
        best = mv.single_swaps(ev, QUEUE_SET, _surrogate_pool(built, fields))
    figure = SeasonFigure(built, knob(built.knobs, "playoff_weight"))
    rows = [(g[0].gain, figure.move(mv.Move(c, g[0].drop))) for c, g in best.items() if g]
    gains = [x for x, _ in rows]
    ros = [r for _, r in rows if r is not None]
    gain = median(gains) if gains else None
    season = median(ros) if ros else None
    ratio = None if gain is None or season is None or abs(season) <= mv.EPS else gain / season
    return Scale(gain, season, ratio, len(rows))


# --------------------------------------------------------------------------- what each knob reads
#: A knob or field a seat reads: a different value can change what it queues.
READ = "read"


@dataclass(frozen=True)
class Shape:
    """What of a league decides which knobs a seat reads (#172, PR C): its scoring as the problem
    reads it, whether it has held slots, whether its bracket is read. Later PRs add to it (F: the
    waiver rule)."""

    scoring: str = "categories"
    held: bool = False
    bracket: bool = True

    def label(self) -> str:
        return ", ".join(
            (
                f"{self.scoring} league",
                "held slots" if self.held else "no held slots",
                "bracket read" if self.bracket else "no bracket read",
            )
        )


def shape_of(setup: Setup) -> Shape:
    points = setup.scoring == "points" and bool(setup.points)
    return Shape(
        "points" if points else "categories",
        any(s in mv.HELD for s in setup.roster_slots),
        setup.spec is not None,
    )


class Configured(Protocol):
    """What of an arm decides what it reads (``run.Arm`` has it)."""

    tier: str
    executes: str
    with_plan: bool
    execute_plan: bool
    knobs: Mapping[str, Any]


#: What makes each knob and field read, for the refusal's message.
WHEN_READ: Mapping[str, str] = {
    "system": "a forecaster per arm (PR D)",
    "blend": "a forecaster per arm and their mix (PR D)",
    "horizon_weight": "the exact tier executing weighted",
    "protection_floor": "a seat that moves: the exact, surrogate or ranking tier",
    "plan_floor_cats": "the exact tier drawing and executing the week plan in a categories league",
    "plan_floor_points": "the exact tier drawing and executing the week plan in a points league",
    "stash_threshold": "the simulator passing it to the engine (PR G)",
    "faab_sizing": "waivers and FAAB in the world (PR F)",
    "daily_cap": "the exact or the surrogate tier, which may queue more than one move a day",
    "three_weight": "the queue's rule (PR E)",
    "season_weight": "the exact or the surrogate tier",
    "playoff_weight": (
        "a season_weight above 0 on the exact or the surrogate tier, in a league whose bracket "
        "is read"
    ),
    "pool": "the exact or the surrogate tier",
    "min_gain": "the exact or the surrogate tier",
    "weeks_ahead": "the exact or the surrogate tier",
    "surrogate_days": "the surrogate tier",
}
STATIC = "a static seat makes no move"


def _odds(arm: Configured, mirrored: bool) -> bool:
    """Whether a search on odds reads the arm's knobs: its own tier's, or the mirror rivals'
    (the surrogate on the arm's knobs and fields)."""
    return arm.tier in ("exact", "surrogate") or mirrored


def reads(arm: Configured, shape: Shape, mirrored: bool = False) -> dict[str, str]:
    """For each of the twelve knobs, :data:`READ` when a different value can change what ``arm``'s
    seat queues in a league of ``shape``, else the reason it cannot. A value that only changes
    what is recorded (a plan drawn and not executed) is not read. ``mirrored``: the arm's rivals
    are its mirror (``opponents.Mirror``), the surrogate on its knobs, so what the surrogate reads
    is read too."""
    odds = _odds(arm, mirrored)
    moves = odds or arm.tier in TIERS
    out: dict[str, str] = {}
    out["protection_floor"] = READ if moves else STATIC
    if odds:
        out["daily_cap"] = READ
    elif arm.tier == "ranking":
        out["daily_cap"] = "the ranking tier queues one move a day, under any cap"
    else:
        out["daily_cap"] = STATIC
    if arm.tier == "exact":
        out["horizon_weight"] = (
            READ if arm.executes == WEIGHTED else "the arm does not execute weighted"
        )
    else:
        out["horizon_weight"] = "only the exact tier executing weighted reads it"
    for name, scoring in (("plan_floor_cats", "categories"), ("plan_floor_points", "points")):
        if arm.tier != "exact":
            why = "only the exact tier draws a week plan"
        elif not arm.with_plan:
            why = "the arm draws no week plan"
        elif not arm.execute_plan:
            why = "the plan is drawn and not executed"
        elif shape.scoring != scoring:
            why = f"a {shape.scoring} league"
        else:
            why = READ
        out[name] = why
    out["three_weight"] = "it weighs the three weeks in the queue's score: the queue's rule, PR E"
    out["system"] = "every seat shares the run's forecaster: a forecaster per arm, PR D"
    out["blend"] = "every seat shares the run's forecaster: a forecaster per arm, PR D"
    out["faab_sizing"] = "the world has no waivers and no budget: PR F"
    out["stash_threshold"] = "the engine reads it since #373; the simulator passes it in PR G"
    if odds:
        out["season_weight"] = READ
    elif arm.tier == "ranking":
        out["season_weight"] = "the ranking tier ranks by value times games and holds no odds"
    else:
        out["season_weight"] = STATIC
    if out["season_weight"] != READ:
        out["playoff_weight"] = out["season_weight"]
    elif not float(arm.knobs["season_weight"]) > 0:
        out["playoff_weight"] = "season_weight is 0: there is no season term"
    elif not shape.bracket:
        out["playoff_weight"] = "the league has no bracket read"
    else:
        out["playoff_weight"] = READ
    return {k: out[k] for k in KNOBS}


def field_reads(arm: Configured, mirrored: bool = False) -> dict[str, str]:
    """For each of the arm's four fields, :data:`READ` or the reason it is not, as
    :func:`reads` (no field depends on the league's shape)."""
    odds = _odds(arm, mirrored)
    if odds:
        out = dict.fromkeys(("pool", "min_gain", "weeks_ahead"), READ)
    elif arm.tier == "ranking":
        out = {
            "pool": "the ranking tier takes the wire's best whatever its size",
            "min_gain": "the ranking tier needs only a gain",
            "weeks_ahead": (
                "the ranking tier counts this week's games, and its keep rule is the same over "
                "any two weeks or more"
            ),
        }
    else:
        out = dict.fromkeys(("pool", "min_gain", "weeks_ahead"), STATIC)
    if arm.tier == "surrogate" or mirrored:
        out["surrogate_days"] = READ
    elif arm.tier in ("exact", "ranking"):
        out["surrogate_days"] = f"the {arm.tier} tier decides every day"
    else:
        out["surrogate_days"] = STATIC
    return {k: out[k] for k in FIELDS}


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
    to ``spots`` (:func:`_activate`; each player it sends counts in the team's ``forced_by``,
    never in ``executed_by`` or ``gone_by``). Then a churn's held drop goes to the pool on his
    own, as the engine times it (#221), freeing his slot; then the held-slot moves it queued,
    each player to his held slot while the slot has room (``slot_counts``, the league's slots by
    kind) and, given ``status``, only if the slot accepts the status he has that morning
    (``moves.eligible``, the engine's test): a move is carried out against the day it lands. One
    the slot does not accept is not made and counts in the team's ``held_refused_by``; he stays
    active and frees no spot. Then the adds: one with a drop of an active player takes his slot;
    one that needs an active spot (no drop, the churn's, or one whose held move was refused)
    takes a bench slot while the active roster is under ``spots`` and is otherwise gone, like an
    add another team took first (a churn's drop stands either way, made before the add; a plain
    swap's is never made). Without ``spots`` nothing is counted."""
    rosters = {t: list(r) for t, r in state.rosters.items()}
    pool = set(state.pool)
    adds_used = dict(state.adds_used)
    executed, gone, forced = dict(state.executed_by), dict(state.gone_by), dict(state.forced_by)
    refused = dict(state.held_refused_by)

    def count(by: dict[int, int], team: int, n: int = 1) -> None:
        if n:
            by[team] = by.get(team, 0) + n

    for team in order:
        roster = rosters.setdefault(team, [])
        if status is not None and value is not None:
            left = _activate(roster, spots, status, value)
            pool.update(left)
            count(forced, team, len(left))
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
            if idx is None:
                continue
            if status is not None and not mv.eligible(status.get(k), slot):
                count(refused, team)  # decided while out; the slot no longer takes him
            elif room:
                roster[idx] = (k, slot)
        for m in moves:
            if m.add not in pool:
                count(gone, team)
                continue
            idx = None
            if m.drop is not None and m.drop not in churned:
                idx = next((i for i, (pk, _) in enumerate(roster) if pk == m.drop), None)
                if idx is None:
                    count(gone, team)
                    continue
            if idx is None:
                if spots is not None and _active_count(roster) >= spots:
                    count(gone, team)
                    continue
                slot = BENCH
            else:
                slot = roster[idx][1]
                pool.add(roster[idx][0])
                del roster[idx]
            roster.append((m.add, slot))
            pool.discard(m.add)
            adds_used[team] = adds_used.get(team, 0) + 1
            count(executed, team)
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(pool),
        adds_used=adds_used,
        pending={},
        pending_held={},
        executed_by=executed,
        gone_by=gone,
        forced_by=forced,
        held_refused_by=refused,
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
    starters: Mapping[int, Mapping[int, str]] | None = None,
) -> SimState:
    """Every team's starters' lines added to the week's totals; a starter without a line (out at
    game time, unheard) adds nothing. ``starters`` is the day's lineup by team when it is already
    set (:func:`starters_of` of the same state, status and value); else it is set here."""
    week = setup.week_of(day)
    if week is None:
        return state
    for team in setup.teams:
        lineup = (
            starters[team]
            if starters is not None and team in starters
            else starters_of(setup, state, team, day, status, value)
        )
        for k in lineup:
            ln = line(k, day)
            if ln:
                state = add_totals(
                    state, week.number, team, {s: x for s, x in ln.items() if s != "minutes_factor"}
                )
    return state
