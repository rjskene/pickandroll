"""The add reserve and the no-quick-re-cut rule (#436, the user's ruling of 2026-11-19).

Six of nine public leagues had used their week's adds by Thursday when a breakout came free.
Two rules keep adds and players from going cheaply:

- **The reserve.** Before the week's release day a set may use the week's last
  ``reserve_adds`` adds only through moves that clear one of three bars:
  - the move adds more than the price to the set on the queue's own score (the week plus
    ``three_weight`` times the three weeks; the matchup odds in a playoff week);
  - its add carries a breakout flag of ``add`` or ``must-add`` (a move lifted by a ``watch`` flag
    gets no exemption, the master's review);
  - it is one of the user's picks (#434). Those are folded before the search, never judged
    here, and count toward the week's adds.

  The moves that use the reserved adds are the set's lowest-scoring ones, so the rule reads the
  same whatever order the search built the set in. A move that counts in a later week does not
  touch this week's reserve. From the release day on the reserve is free.
- **No quick re-cut.** A move dropping a player I added within ``recut_days`` days is allowed
  only when it adds more than the price, or that player is out (an O, a status that keeps a
  player out of every week, or a held slot). A pick's drop is chosen before the search and never
  refused.

The price is ``reserve_price`` when set, else the fortnight's typical recommended gain the bid
policy scales by (``autopilot.typical_gain``). The rule composes with the season guard into the
``allowed`` every search, re-solve and plan already takes. The knobs (:data:`KNOBS`) are the
master's first guesses as the code's defaults (:data:`DEFAULTS`); ``reserve_adds`` and
``recut_days`` both 0 apply nothing. Pure: no I/O."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import moves as mv
from . import weekly as wk

RESERVE_ADDS = "reserve_adds"
RESERVE_RELEASE = "reserve_release"
RESERVE_PRICE = "reserve_price"
RECUT_DAYS = "recut_days"
KNOBS = (RESERVE_ADDS, RESERVE_RELEASE, RESERVE_PRICE, RECUT_DAYS)
#: The weekdays the release may fall on, Monday first (``date.weekday``).
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
#: The first guesses, ruled live as the code's defaults (the master's review on #436): one add
#: held, released by Friday's solves (their claims land on Saturday), the typical gain as the
#: price, no re-cut within three days.
DEFAULTS: Mapping[str, Any] = {
    RESERVE_ADDS: 1,
    RESERVE_RELEASE: "friday",
    RESERVE_PRICE: None,
    RECUT_DAYS: 3,
}
#: Both rules off: the moves as before #436.
OFF: Mapping[str, Any] = {**DEFAULTS, RESERVE_ADDS: 0, RECUT_DAYS: 0}
#: The flag levels whose add may use the reserve whatever it adds.
EXEMPT_LEVELS = frozenset({"add", "must-add"})
#: The rules' names in the record.
RESERVE, RECUT = "reserve", "recut"


def knobs_of(knobs: Mapping[str, Any] | None) -> dict[str, Any]:
    """The rules' knobs in force: :data:`DEFAULTS`, then those ``knobs`` set."""
    return {k: (knobs or {}).get(k, DEFAULTS[k]) for k in KNOBS}


def refused(knob: str, value: Any) -> str | None:
    """Why knob ``knob`` may not take ``value`` in the knob file; None when it may."""
    if value is None:
        return None if knob == RESERVE_PRICE else f"{knob} is None: the rule takes a value for it"
    if knob == RESERVE_RELEASE:
        if value not in WEEKDAYS:
            return f"{knob} {value!r} is not one of {', '.join(WEEKDAYS)}"
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return f"{knob} {value!r} is not a number"
    if knob in (RESERVE_ADDS, RECUT_DAYS) and not isinstance(value, int):
        return f"{knob} {value!r} is not a whole number"
    high = {RESERVE_ADDS: 3, RECUT_DAYS: 14}.get(knob)
    if value < 0:
        return f"{knob} {value} is below its minimum 0"
    if high is not None and value > high:
        return f"{knob} {value} is above its maximum {high}"
    return None


@dataclass(frozen=True)
class ReserveRule:
    """The two rules on one solve."""

    #: The week the reserve holds adds in, its adds left (None: no limit) and how many of them
    #: are held; None when the reserve does not apply (off, released or no limit).
    week: mv.AddLimit | None
    reserved: int
    #: What a move must add to the set to use a held add or re-cut a recent add.
    price: float
    #: The candidates whose flag lets them use the reserve whatever they add.
    exempt: frozenset[int]
    #: My players added within the re-cut days, each with the day added.
    recent: Mapping[int, date] = field(default_factory=dict)
    #: Of them, those out: a drop of one is never refused.
    out: frozenset[int] = frozenset()

    @property
    def applies(self) -> bool:
        return (self.week is not None and self.reserved > 0) or bool(self.recent)


def released(limit: mv.AddLimit, today: date, release: str) -> bool:
    """Whether the reserve of the week ``limit`` counts is free on a solve of ``today``: from that
    week's release day on (its start, a Monday, plus the weekday's offset)."""
    return today >= limit.start + timedelta(days=WEEKDAYS.index(release))


def rule_of(
    problem: mv.MoveProblem,
    today: date,
    knobs: Mapping[str, Any] | None,
    typical: float,
    flags: Mapping[int, str | None],
    recent: Mapping[int, date],
) -> ReserveRule | None:
    """The rules on ``problem``'s solve of ``today`` under ``knobs`` (``typical``, the price when
    ``reserve_price`` is unset; ``flags``, each candidate's flag level; ``recent``, my players by
    the day I added them); None when neither applies."""
    k = knobs_of(knobs)
    held, days = int(k[RESERVE_ADDS]), int(k[RECUT_DAYS])
    price = float(typical if k[RESERVE_PRICE] is None else k[RESERVE_PRICE])
    week = problem.limits[0] if problem.limits else None
    if (
        held <= 0
        or week is None
        or week.adds is None
        or released(week, today, str(k[RESERVE_RELEASE]))
    ):
        week = None
    mine = {key: pl for key, pl in (*problem.roster, *problem.held)}
    within = {
        key: day
        for key, day in recent.items()
        if key in mine and days > 0 and 0 <= (today - day).days < days
    }
    out = frozenset(key for key in within if is_out(problem, key, mine[key]))
    rule = ReserveRule(
        week,
        held if week is not None else 0,
        price,
        frozenset(c for c, level in flags.items() if level in EXEMPT_LEVELS),
        within,
        out,
    )
    return rule if rule.applies else None


def is_out(problem: mv.MoveProblem, key: int, player: Any) -> bool:
    """Whether my player ``key`` is out: in a held slot, or with a status that keeps a player out
    of this week or every week."""
    status = (getattr(player, "status", None) or "").upper()
    return key in problem.held_slots or status in wk.OUT_THIS_WEEK or status in wk.OUT_ALL


Objective = Callable[[mv.Evaluator, Sequence[mv.Move]], float]


@dataclass(frozen=True)
class Refusal:
    """Why the rules refuse a set: the rule and the move that failed it, with what it adds."""

    rule: str
    move: mv.Move
    adds: float


def marginal(ev: mv.Evaluator, objective: Objective, moves: Sequence[mv.Move], m: mv.Move) -> float:
    """What ``m`` adds to the set ``moves`` on ``objective``."""
    rest = [x for x in moves if x != m]
    return objective(ev, list(moves)) - objective(ev, rest)


def refusal(
    ev: mv.Evaluator, rule: ReserveRule, objective: Objective, moves: Sequence[mv.Move]
) -> Refusal | None:
    """The first move by which ``rule`` refuses the set ``moves``; None when it allows it."""
    p = ev.problem
    worth: dict[mv.Move, float] = {}

    def adds(m: mv.Move) -> float:
        if m not in worth:
            worth[m] = marginal(ev, objective, moves, m)
        return worth[m]

    for m in moves:
        recut = m.drop is not None and m.drop in rule.recent and m.drop not in rule.out
        if recut and adds(m) <= rule.price + mv.EPS:
            return Refusal(RECUT, m, adds(m))
    if rule.week is None or rule.week.adds is None:
        return None
    week = [m for m in moves if rule.week.start <= mv.day_of(p, m) <= rule.week.end]
    over = len(week) - max(0, rule.week.adds - rule.reserved)
    if over <= 0:
        return None
    # The reserved adds are the set's lowest-scoring moves of the week.
    for m in sorted(week, key=lambda x: (adds(x), x.add))[:over]:
        if m.add not in rule.exempt and adds(m) <= rule.price + mv.EPS:
            return Refusal(RESERVE, m, adds(m))
    return None


def guard(ev: mv.Evaluator, rule: ReserveRule | None, objective: Objective) -> mv.Allowed | None:
    """The rules as an ``allowed`` for the searches; None without a rule."""
    if rule is None:
        return None

    def allowed(moves: Sequence[mv.Move]) -> bool:
        return refusal(ev, rule, objective, moves) is None

    return allowed


def both(*guards: mv.Allowed | None) -> mv.Allowed | None:
    """The guards given, all of them; the one when only one is given, None with none."""
    given = [g for g in guards if g is not None]
    if not given:
        return None
    if len(given) == 1:
        return given[0]

    def allowed(moves: Sequence[mv.Move]) -> bool:
        return all(g(moves) for g in given)

    return allowed


def added_within(
    adds: Iterable[tuple[int, date | None]], today: date, days: int
) -> dict[int, date]:
    """``adds`` (a player and the day added) of the last ``days`` days, each player's latest."""
    out: dict[int, date] = {}
    for key, day in adds:
        if day is None or days <= 0 or not 0 <= (today - day).days < days:
            continue
        out[key] = max(day, out.get(key, day))
    return out
