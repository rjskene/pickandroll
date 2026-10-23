"""The Monday hill-climb step (#152; docs/AUTOPILOT.md section 6): the verdicts on the changes
judged this Monday, at most one new change from the rule table, the knob file they leave and the
Monday note, from the Progress payload (``api.season_progress``) and the knob file.

The rule table, in order (master's rulings on #152, 2026-10-23); the first rule that clears and
is not blocked decides, one change a Monday:

1. **The season check**, per scoring: three or more season-costly moves (#144), more than half of
   them realized below zero over the season so far: that scoring's protection floor rises a step
   (:data:`FLOOR_STEP`: 0.05 z a game in a categories league, 0.5 fantasy points a game in a
   points league).
2. **The streaming plans**, per scoring: five or more plan moves (#136), realized under half their
   projection: that scoring's plan floor rises by half its value, never above four times its
   default.
3. **The projection system**: twenty or more moves under the system in force, pooled over the
   scorings by realized share, under half their projection season to date: Basketball Monster's
   (or Yahoo's) steps to the blend at 0.5, never straight to Yahoo's; a kept blend steps 0.25
   toward Yahoo's, within its bounds.

A sample counts only scored moves whose judging horizon is over (#143), as the scorecard compares
them. A rule that clears is blocked when its knob is unhooked (``progress.HOOKED``), changed in
the last four weeks or still judged, frozen in all but one league it would reach, or when the step
would leave its bounds; the next rule then has its say. The leagues a change reaches are the armed
leagues of its scoring (of both for the system), split in two by league id: the half that lagged
on the rule's measure takes it (A), the other keeps the setting (B). The private league takes no
change, and the knob file is written so that its values stay as they were.

A change is judged two Mondays on, once its two weeks are recorded: on each measure in turn (the
wins above expected a league, the categories above expected a league, the moves' realized share,
the season-costly moves gone below zero a league), the first on which the halves differ by its
threshold over the two weeks decides; kept when A did better, reverted when worse, kept when no
measure tells them apart. A kept change rolls out to the leagues of its scope; a reverted one
writes the old values back for the A leagues. A user's change is never judged, and a frozen knob
is never written.

Pure: ``api.season_hillclimb`` reads the payload and the files and writes what this returns.
"""

from __future__ import annotations

import copy
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from . import progress as pg
from .stream import PLAN_FLOOR_CATS, PLAN_FLOOR_POINTS

SCORINGS = ("categories", "points")
#: The protection floor's step, a per-game margin in the league's units.
FLOOR_STEP = {"categories": 0.05, "points": 0.5}
FLOOR_MOVES = 3
PLAN_KNOB = {"categories": "plan_floor_cats", "points": "plan_floor_points"}
PLAN_DEFAULT = {"categories": PLAN_FLOOR_CATS, "points": PLAN_FLOOR_POINTS}
PLAN_MOVES = 5
PLAN_SHARE = 0.5
#: A plan floor never rises above this many times its default.
PLAN_CAP = 4.0
SYSTEM_MOVES = 20
SYSTEM_SHARE = 0.5
BLEND_START = 0.5
BLEND_STEP = 0.25
#: Never two changes to the same knob within four weeks.
QUIET_DAYS = 28
#: A change needs leagues for both halves.
MIN_LEAGUES = 2
#: The knobs changed together: the projection system and its blend weight are one row of the
#: bounds table.
FAMILY = {"system": ("system", "blend"), "blend": ("system", "blend")}
#: The measures a change is judged on, in order: the name, the threshold the halves must differ
#: by over its two weeks, and whether more is better.
MEASURES: tuple[tuple[str, float, bool], ...] = (
    ("wins_above", 0.5, True),
    ("categories_above", 1.0, True),
    ("share", 0.10, True),
    ("season_below", 1.0, False),
)
MEASURE_WORDS = {
    "wins_above": "wins above expected a league",
    "categories_above": "categories above expected a league",
    "share": "the moves' realized share of their projection",
    "season_below": "season-costly moves gone below zero a league",
}
RULE_WORDS = {
    "season_check": "the season check",
    "plan_floor": "the streaming plans",
    "system": "the projection system",
}


# --------------------------------------------------------------------------- the moves
def over(move: Mapping[str, Any]) -> tuple[float, float] | None:
    """A scored move's projected and realized value on its judging horizon once that horizon is
    over, as the scorecard compares it (``season_scorecard.moves_summary``); None otherwise."""
    if move.get("group") != "scored":
        return None
    judged = move.get("judged") or "week"
    real = ((move.get("realized") or {}).get("horizons") or {}).get(judged)
    proj = (((move.get("projected") or {}).get("value") or {}).get("horizons") or {}).get(judged)
    if not real or not real.get("complete") or real.get("value") is None:
        return None
    if not proj or proj.get("value") is None:
        return None
    return float(proj["value"]), float(real["value"])


def season_so_far(move: Mapping[str, Any]) -> float | None:
    """A move's realized value over the season so far (#144)."""
    season = ((move.get("realized") or {}).get("horizons") or {}).get("season") or {}
    return season.get("value")


def share(moves: Iterable[Mapping[str, Any]]) -> tuple[int, float | None]:
    """The moves whose horizon is over and their realized share of their projection, pooled over
    the scorings by share (each scoring's own units), weighted by its moves; None when no
    scoring's projection is above zero."""
    by: dict[str, list[tuple[float, float]]] = {}
    for m in moves:
        if (x := over(m)) is not None:
            by.setdefault(m.get("scoring") or "categories", []).append(x)
    n = sum(len(xs) for xs in by.values())
    shares = [
        (len(xs), sum(r for _, r in xs) / sum(p for p, _ in xs))
        for xs in by.values()
        if sum(p for p, _ in xs) > 0
    ]
    if not shares:
        return n, None
    weight = sum(k for k, _ in shares)
    return n, round(sum(k * s for k, s in shares) / weight, 4)


def costly(moves: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """The season-costly moves whose horizon is over, and how many of them realized below zero
    over the season so far."""
    flagged = [m for m in moves if m.get("season_costly") and over(m) is not None]
    below = sum(1 for m in flagged if (s := season_so_far(m)) is not None and s < 0)
    return len(flagged), below


def _plan(m: Mapping[str, Any]) -> bool:
    return (m.get("projected") or {}).get("set") == "plan"


def _system(m: Mapping[str, Any]) -> str | None:
    return (m.get("knobs") or {}).get("system")


# --------------------------------------------------------------------------- the knobs
def value(knobs: Mapping[str, Any], league: str, knob: str) -> Any:
    """A knob's value in ``league`` as the file sets it (``knobs`` as ``progress.knob_file``
    reads it): the default, then ``in_force``, then the league's own."""
    return {
        **pg.DEFAULTS,
        **knobs.get("in_force", {}),
        **knobs.get("leagues", {}).get(league, {}),
    }[knob]


def frozen(knobs: Mapping[str, Any], league: str, knob: str) -> bool:
    names = knobs.get("frozen", {}).get(league, [])
    return any(k in names for k in FAMILY.get(knob, (knob,)))


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def written(change: Mapping[str, Any]) -> str:
    """The last day a change wrote its knob: its verdict's (a revert or a rollout writes it
    again), else its Monday."""
    return change.get("judged_on") or change["monday"]


def recent(knobs: Mapping[str, Any], knob: str, monday: str) -> dict[str, Any] | None:
    """The change that keeps ``knob`` from changing this Monday: one that wrote its family
    within :data:`QUIET_DAYS` (its Monday, or its revert or rollout), or one still waiting for
    its verdict."""
    family = FAMILY.get(knob, (knob,))
    for c in reversed(knobs.get("changes", [])):
        if c["knob"] not in family or c["monday"] > monday:
            continue
        if _days(monday, written(c)) < QUIET_DAYS or (
            c["verdict"] is None and c.get("source") != "user"
        ):
            return c
    return None


def refused_change(
    knobs: Mapping[str, Any], knob: str, to: Any, monday: str, scope: Sequence[str]
) -> str | None:
    """Why the step may not set ``knob`` to ``to`` in ``scope`` this Monday; None when it may.
    Every change the step makes passes here first."""
    if knob not in pg.HOOKED:
        return f"{knob} has no hook, so the step never changes it"
    if why := pg.refused(knob, to):
        return why
    if c := recent(knobs, knob, monday):
        if c.get("judged_on") and c["verdict"] is not None:
            return f"{c['id']} ({c['knob']}) was {c['verdict']} on {c['judged_on']}"
        return f"{c['id']} changed {c['knob']} on {c['monday']}"
    if len(scope) < MIN_LEAGUES:
        return f"{len(scope)} league{'s' * (len(scope) != 1)} to split, fewer than {MIN_LEAGUES}"
    return None


def _ids(leagues: Iterable[str]) -> list[str]:
    return sorted(leagues, key=lambda x: (0, int(x)) if x.isdigit() else (1, x))


def scope(
    knobs: Mapping[str, Any], armed: Mapping[str, str], knob: str, scoring: str | None
) -> tuple[list[str], Any]:
    """The leagues a change of ``knob`` reaches: the armed leagues of ``scoring`` (of both when
    None) where the knob is not frozen and holds the value most of them share (the lower on a
    tie), and that value."""
    leagues = [
        lg
        for lg, s in armed.items()
        if (scoring is None or s == scoring) and not frozen(knobs, lg, knob)
    ]
    if not leagues:
        return [], None
    at = _modal([value(knobs, lg, knob) for lg in leagues])
    return _ids(lg for lg in leagues if value(knobs, lg, knob) == at), at


def _modal(values: Sequence[Any]) -> Any:
    """The value most of ``values`` share, the lower on a tie."""
    counts = Counter(repr(v) for v in values)
    by = {repr(v): v for v in values}
    top = max(counts.values())
    common = sorted(
        (by[r] for r, n in counts.items() if n == top), key=lambda v: (v is None, str(v))
    )
    if all(isinstance(v, int | float) for v in common):
        common = sorted(common)
    return common[0]


def halves(
    leagues: Sequence[str], lag: Callable[[Sequence[str]], float | None]
) -> tuple[list[str], list[str]]:
    """``leagues`` split in two by league id, alternately; the half that lagged (``lag`` the
    greater) first, the first half on a tie or when neither can say."""
    ids = _ids(leagues)
    one, two = ids[0::2], ids[1::2]
    l1, l2 = lag(one), lag(two)
    if l2 is not None and (l1 is None or l2 > l1):
        return two, one
    return one, two


# --------------------------------------------------------------------------- the rules
def _in(moves: Sequence[Mapping[str, Any]], leagues: Iterable[str]) -> list[Mapping[str, Any]]:
    keep = set(leagues)
    return [m for m in moves if str(m.get("league")) in keep]


def _floor_rule(
    knobs: Mapping[str, Any],
    armed: Mapping[str, str],
    moves: Sequence[Mapping[str, Any]],
    scoring: str,
) -> dict[str, Any]:
    leagues = [lg for lg, s in armed.items() if s == scoring]
    flagged, below = costly(_in(moves, leagues))
    out = {
        "rule": "season_check",
        "scoring": scoring,
        "knob": "protection_floor",
        "numbers": {"season_costly": flagged, "below_zero": below},
        "clears": flagged >= FLOOR_MOVES and below > flagged / 2,
    }
    if not out["clears"]:
        return out
    reach, at = scope(knobs, armed, "protection_floor", scoring)
    to = round(float(at) + FLOOR_STEP[scoring], 4)

    def lag(half: Sequence[str]) -> float | None:
        return costly(_in(moves, half))[1] / len(half) if half else None

    a, b = halves(reach, lag)
    reason = (
        f"The season check ({scoring}): {below} of the {flagged} season-costly moves whose "
        f"horizon is over realized below zero over the season so far ({below / flagged:.0%}); "
        f"the protection floor rises {at:g} → {to:g} a game in {len(a)} of the "
        f"{len(reach)} {scoring} leagues, the half with more of them."
    )
    return {
        **out,
        "from": at,
        "to": to,
        "set": {"protection_floor": to},
        "leagues": a,
        "b_leagues": b,
        "reach": reach,
        "reason": reason,
    }


def _plan_rule(
    knobs: Mapping[str, Any],
    armed: Mapping[str, str],
    moves: Sequence[Mapping[str, Any]],
    scoring: str,
) -> dict[str, Any]:
    knob = PLAN_KNOB[scoring]
    leagues = [lg for lg, s in armed.items() if s == scoring]
    n, got = share(m for m in _in(moves, leagues) if _plan(m))
    out = {
        "rule": "plan_floor",
        "scoring": scoring,
        "knob": knob,
        "numbers": {"plan_moves": n, "share": got},
        "clears": n >= PLAN_MOVES and got is not None and got < PLAN_SHARE,
    }
    if not out["clears"]:
        return out
    reach, at = scope(knobs, armed, knob, scoring)
    cap = round(PLAN_CAP * PLAN_DEFAULT[scoring], 4)
    at = float(at)
    to = min(round(at * 1.5, 4), cap)
    if to <= at:
        why = "the floor is at its cap" if at >= cap else "a floor at or below zero has no half"
        return {**out, "from": at, "to": at, "blocked": why}

    def lag(half: Sequence[str]) -> float | None:
        s = share(m for m in _in(moves, half) if _plan(m))[1]
        return None if s is None else -s

    a, b = halves(reach, lag)
    reason = (
        f"The streaming plans ({scoring}): the {n} plan moves whose horizon is over realized "
        f"{got:.0%} of their projection, under {PLAN_SHARE:.0%}; the plan floor rises "
        f"{at:g} → {to:g} in {len(a)} of the {len(reach)} {scoring} leagues, the half whose "
        "plans realized less."
    )
    return {
        **out,
        "from": at,
        "to": to,
        "set": {knob: to},
        "leagues": a,
        "b_leagues": b,
        "reach": reach,
        "reason": reason,
    }


def _kept_blend(knobs: Mapping[str, Any], leagues: Sequence[str]) -> bool:
    """Whether the blend in force in ``leagues`` was kept: the last change of the system that
    reached them was, or none did (the master or the user set it)."""
    for c in reversed(knobs.get("changes", [])):
        if c["knob"] == "system" and set(c["leagues"]) & set(leagues):
            return c["verdict"] == "kept" or c.get("source") == "user"
    return True


def _system_rule(
    knobs: Mapping[str, Any], armed: Mapping[str, str], moves: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    reach, system = scope(knobs, armed, "system", None)
    n, got = share(m for m in _in(moves, reach) if _system(m) == system)
    out = {
        "rule": "system",
        "scoring": None,
        "knob": "system",
        "numbers": {"system": system, "moves": n, "share": got},
        "clears": n >= SYSTEM_MOVES and got is not None and got < SYSTEM_SHARE,
    }
    if not out["clears"]:
        return out

    def lag(half: Sequence[str]) -> float | None:
        s = share(m for m in _in(moves, half) if _system(m) == system)[1]
        return None if s is None else -s

    head = (
        f"The projection system: the {n} moves under {system} whose horizon is over realized "
        f"{got:.0%} of their projection season to date, under {SYSTEM_SHARE:.0%}"
    )
    if system == "blend":
        if not _kept_blend(knobs, reach):
            return {**out, "blocked": "the blend in force has not been kept yet"}
        weights = {
            lg: pg.BLEND if (w := value(knobs, lg, "blend")) is None else float(w) for lg in reach
        }
        at = _modal(list(weights.values()))
        reach = [lg for lg in reach if weights[lg] == at]
        to = round(at + BLEND_STEP, 4)
        a, b = halves(reach, lag)
        return {
            **out,
            "knob": "blend",
            "from": at,
            "to": to,
            "set": {"blend": to},
            "leagues": a,
            "b_leagues": b,
            "reach": reach,
            "reason": f"{head}; the blend moves {at:g} → {to:g} toward Yahoo's in {len(a)} of "
            f"the {len(reach)} leagues, the half whose moves realized less.",
        }
    a, b = halves(reach, lag)
    return {
        **out,
        "from": system,
        "to": "blend",
        "set": {"system": "blend", "blend": BLEND_START},
        "leagues": a,
        "b_leagues": b,
        "reach": reach,
        "reason": f"{head}; {len(a)} of the {len(reach)} leagues, the half whose moves realized "
        f"less, try the blend at {BLEND_START:g}.",
    }


def rules(
    knobs: Mapping[str, Any],
    armed: Mapping[str, str],
    moves: Sequence[Mapping[str, Any]],
    monday: str,
) -> list[dict[str, Any]]:
    """Every rule in the table's order with its numbers, whether it clears, and for one that
    does the change it would make or why it is blocked."""
    out = [_floor_rule(knobs, armed, moves, s) for s in SCORINGS]
    out += [_plan_rule(knobs, armed, moves, s) for s in SCORINGS]
    out.append(_system_rule(knobs, armed, moves))
    for r in out:
        if r["clears"] and "blocked" not in r:
            reach = [*r["leagues"], *r["b_leagues"]]
            for knob, to in r["set"].items():
                if why := refused_change(knobs, knob, to, monday, reach):
                    r["blocked"] = why
                    break
    return out


# --------------------------------------------------------------------------- the verdicts
def _mean(xs: Sequence[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def measures(
    leagues: Sequence[str],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    moves: Sequence[Mapping[str, Any]],
    first: int,
    last: int,
) -> dict[str, float | None]:
    """A half's measures over weeks ``first`` to ``last``: the wins and the categories above
    expected a league (over its projected weeks), its moves' realized share, and its season-costly
    moves gone below zero a league."""
    above, cats = [], []
    for lg in leagues:
        shown = [r for r in rows.get(lg, ()) if first <= r["week"] <= last]
        won = [r for r in shown if r.get("expected") is not None and r.get("won") is not None]
        if won:
            above.append(sum(r["won"] - r["expected"] for r in won))
        both = [
            r
            for r in shown
            if r.get("expected_categories") is not None and r.get("categories") is not None
        ]
        if both:
            cats.append(sum(r["categories"] - r["expected_categories"] for r in both))
    picked = [m for m in _in(moves, leagues) if first <= int(m["week"]) <= last]
    return {
        "wins_above": _mean(above),
        "categories_above": _mean(cats),
        "share": share(picked)[1],
        "season_below": round(costly(picked)[1] / len(leagues), 4) if leagues else None,
    }


def due(change: Mapping[str, Any], last: int | None) -> bool:
    """Whether a change is judged this Monday: the master's, without a verdict, its weeks known
    and both of them recorded."""
    week = change.get("week")
    return (
        change.get("source") != "user"
        and change["verdict"] is None
        and week is not None
        and last is not None
        and last >= week + pg.JUDGED_WEEKS - 1
    )


def verdict(
    change: Mapping[str, Any],
    armed: Mapping[str, str],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    moves: Sequence[Mapping[str, Any]],
    knobs: Mapping[str, Any],
) -> dict[str, Any]:
    """A change's verdict over its two weeks: the halves (A the leagues that took it, B the
    armed leagues of its scope that kept the setting: those the change recorded, when it did),
    each measure for both, and the measure that decided, kept when none tells them apart.
    Beside it, never deciding, the year to date read as a difference in differences (``since``,
    each measure's A − B gap to the last week recorded less its gap before the change; a sum
    over no weeks is nothing, a share over no moves unknown) and the raw figures it is read
    from (``a_ytd``, ``b_ytd``, ``a_before``, ``b_before``)."""
    week = int(change["week"])
    end = week + pg.JUDGED_WEEKS - 1
    scoring = change.get("scoring")
    named = change.get("b_leagues")
    a = _ids(lg for lg in change["leagues"] if lg in armed)
    b = _ids(
        lg
        for lg, s in armed.items()
        if lg not in a
        and (named is None or lg in named)
        and (scoring is None or s == scoring)
        and not frozen(knobs, lg, change["knob"])
    )
    last = max((r["week"] for rs in rows.values() for r in rs), default=end)
    figures = {
        "window": [week, end],
        "a": measures(a, rows, moves, week, end),
        "b": measures(b, rows, moves, week, end),
        "a_ytd": measures(a, rows, moves, 1, last),
        "b_ytd": measures(b, rows, moves, 1, last),
        "a_before": measures(a, rows, moves, 1, week - 1),
        "b_before": measures(b, rows, moves, 1, week - 1),
    }
    figures["since"] = {
        name: _since(figures, name, summed=name != "share") for name, _, _ in MEASURES
    }
    decided, outcome = None, "kept"
    for name, threshold, more in MEASURES:
        x, y = figures["a"][name], figures["b"][name]
        if x is None or y is None:
            continue
        gap = (x - y) if more else (y - x)
        if abs(gap) < threshold:
            continue
        decided, outcome = name, ("kept" if gap > 0 else "reverted")
        break
    return {
        "id": change["id"],
        "knob": change["knob"],
        "verdict": outcome,
        "decided_by": decided,
        "leagues": a,
        "b_leagues": b,
        **figures,
    }


def _since(figures: Mapping[str, Any], name: str, summed: bool) -> float | None:
    """The change in a measure's A − B gap since the change's Monday: the gap to the last week
    less the gap before. For a sum, a half with nothing before counts nothing."""

    def gap(a: float | None, b: float | None, empty: float | None) -> float | None:
        a, b = (empty if a is None else a), (empty if b is None else b)
        return None if a is None or b is None else a - b

    now = gap(figures["a_ytd"][name], figures["b_ytd"][name], None)
    before = gap(figures["a_before"][name], figures["b_before"][name], 0.0 if summed else None)
    return None if now is None or before is None else round(now - before, 4)


def _judged(change: Mapping[str, Any], raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """The verdict the step wrote on ``raw`` (``change`` as the knob file reads it), as
    :func:`verdict` gave it; None when it wrote none."""
    j = raw.get("judged")
    if not isinstance(j, dict) or change["verdict"] is None:
        return None
    return {
        "id": change["id"],
        "knob": change["knob"],
        "verdict": change["verdict"],
        "decided_by": j.get("decided_by"),
        "leagues": j.get("leagues") or [],
        "b_leagues": j.get("b_leagues") or [],
        "window": j.get("window"),
        "a": j.get("a") or {},
        "b": j.get("b") or {},
        "since": j.get("since") or {},
        "a_ytd": j.get("a_ytd") or {},
        "b_ytd": j.get("b_ytd") or {},
    }


def _verdict_reason(v: Mapping[str, Any]) -> str:
    what = f"{v['id']} ({v['knob']})"
    weeks = f"weeks {v['window'][0]}-{v['window'][1]}"
    name = v["decided_by"]
    if name is None:
        said = f"{what} is kept: no measure told the halves apart over {weeks}."
    else:
        x, y = v["a"][name], v["b"][name]
        said = (
            f"{what} is {v['verdict']}: on {MEASURE_WORDS[name]}, the {len(v['leagues'])} "
            f"leagues that took it ran {x:g} against {y:g} for the {len(v['b_leagues'])} that "
            f"kept the setting over {weeks}."
        )
    shown = name or "wins_above"
    d = (v.get("since") or {}).get(shown)
    if d is None:
        return said
    x, y = (v.get("a_ytd") or {}).get(shown), (v.get("b_ytd") or {}).get(shown)
    raw = f" ({x:g} against {y:g})" if x is not None and y is not None else ""
    return (
        f"{said} Year to date, the gap on {MEASURE_WORDS[shown]} moved {d:+g} since its "
        f"Monday{raw}."
    )


# --------------------------------------------------------------------------- the writes
def _object(raw: Any, key: str) -> dict[str, Any]:
    got = raw.get(key)
    if not isinstance(got, dict):
        got = raw[key] = {}
    return got


def write(
    raw: dict[str, Any], knob: str, targets: Mapping[str, Any], leagues: Iterable[str]
) -> None:
    """Set ``knob`` to each of ``targets`` (league → value) in the raw knob file, every other
    league of ``leagues`` (and of the file) keeping its value: ``in_force`` holds the knob only
    while every league shares one value, and a league's own value is kept only where it differs
    from that."""
    knobs, _ = pg.knob_file(raw)
    every = _ids(set(leagues) | set(targets) | set(knobs["leagues"]))
    want = {lg: targets[lg] if lg in targets else value(knobs, lg, knob) for lg in every}
    in_force = _object(raw, "in_force")
    values = list(want.values())
    if values and all(v == values[0] for v in values):
        in_force[knob] = values[0]
    else:
        in_force.pop(knob, None)
    base = value(pg.knob_file(raw)[0], "", knob)
    own = _object(raw, "leagues")
    for lg in every:
        mine = own.get(lg)
        if not isinstance(mine, dict):
            mine = own[lg] = {}
        if want[lg] == base:
            mine.pop(knob, None)
        else:
            mine[knob] = want[lg]
        if not mine:
            del own[lg]


def _raw_change(raw: Mapping[str, Any], cid: str) -> dict[str, Any] | None:
    return next(
        (c for c in raw.get("changes") or [] if isinstance(c, dict) and c.get("id") == cid), None
    )


def _undo(raw: dict[str, Any], change: Mapping[str, Any], leagues: Iterable[str]) -> None:
    """Write back the values a change replaced for the leagues that took it."""
    knobs, _ = pg.knob_file(raw)
    was = change.get("was")
    if not isinstance(was, dict):
        was = {change["knob"]: dict.fromkeys(change.get("leagues") or [], change.get("from"))}
    for knob, before in was.items():
        if knob not in pg.KNOBS or not isinstance(before, dict):
            continue
        keep = {lg: v for lg, v in before.items() if not frozen(knobs, str(lg), knob)}
        write(raw, knob, {str(k): v for k, v in keep.items()}, leagues)


def _roll_out(
    raw: dict[str, Any],
    change: Mapping[str, Any],
    armed: Mapping[str, str],
    leagues: Iterable[str],
) -> list[str]:
    """Write a kept change's values to every armed league of its scope; the leagues reached."""
    knobs, _ = pg.knob_file(raw)
    values = change.get("set")
    if not isinstance(values, dict):
        values = {change["knob"]: change.get("to")}
    scoring = change.get("scoring")
    reach = _ids(
        lg
        for lg, s in armed.items()
        if (scoring is None or s == scoring) and not frozen(knobs, lg, change["knob"])
    )
    for knob, to in values.items():
        if knob in pg.KNOBS:
            write(raw, knob, dict.fromkeys(reach, to), leagues)
    return reach


def _next_id(raw: Mapping[str, Any]) -> str:
    seen = [
        int(c["id"][1:])
        for c in raw.get("changes") or []
        if isinstance(c, dict) and str(c.get("id", ""))[:1] == "K" and str(c["id"])[1:].isdigit()
    ]
    return f"K{max(seen, default=0) + 1}"


def writable(raw: Any) -> list[str]:
    """What keeps the step from writing the raw knob file: anything but an object with objects
    for ``in_force``, ``leagues`` and its leagues, and ``frozen``, and a list for ``changes``."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        return ["the knob file is not an object"]
    out = [
        f"{key} is not an object"
        for key in ("in_force", "leagues", "frozen")
        if raw.get(key) is not None and not isinstance(raw[key], dict)
    ]
    if raw.get("changes") is not None and not isinstance(raw["changes"], list):
        out.append("changes is not a list")
    for lg, v in (raw.get("leagues") or {}).items() if isinstance(raw.get("leagues"), dict) else ():
        if not isinstance(v, dict):
            out.append(f"league {lg} is not an object")
    return out


def ran(raw: Any, monday: str) -> list[str]:
    """The ids of the changes the step made or judged on ``monday``."""
    if not isinstance(raw, dict) or not isinstance(raw.get("changes"), list):
        return []
    return [
        str(c.get("id"))
        for c in raw["changes"]
        if isinstance(c, dict) and monday in (c.get("monday"), c.get("judged_on"))
    ]


# --------------------------------------------------------------------------- the note
def note(
    monday: str,
    sentences: Sequence[Mapping[str, str]],
    verdicts: Sequence[Mapping[str, Any]],
    change: Mapping[str, Any] | None,
    outcomes: Sequence[Mapping[str, Any]],
    pending: Sequence[Mapping[str, Any]],
) -> str:
    """The Monday note (``progress.note`` reads it): what is working and what is not, the pooled
    sentences by tone; the decision, the verdicts and the change or why none was made; and the
    action items. Counts and ratios only, no league named."""
    pooled = [s for s in sentences if s.get("scope") == "pooled" and s.get("topic") != "knobs"]
    working = [s["text"] for s in pooled if s.get("tone") != "bad"]
    not_working = [s["text"] for s in pooled if s.get("tone") == "bad"]
    decision = [_verdict_reason(v) for v in verdicts]
    passed = []
    for r in outcomes:
        if r["clears"] and not r.get("blocked"):
            break  # the rule that made the change
        if r["clears"]:
            where = f" ({r['scoring']})" if r["scoring"] else ""
            passed.append(f"{RULE_WORDS[r['rule']]}{where} cleared but {r['blocked']}")
    blocked = "; ".join(passed)
    if change is not None:
        decision.append(f"{change['id']}: {change['reason']}")
        if blocked:
            decision.append(f"Passed over before it: {blocked}.")
    elif blocked:
        decision.append(f"No change: {blocked}.")
    else:
        decision.append("No change: no rule's numbers cleared its threshold.")
    actions = [
        f"Judge {c['id']} ({c['knob']}) once week {c['week'] + pg.JUDGED_WEEKS - 1} is recorded."
        for c in pending
        if c.get("week") is not None
    ]
    if change is not None:
        actions.append(
            f"Judge {change['id']} ({change['knob']}) two Mondays on, once its two weeks are recorded."
        )
    lines = ["## What is working", *(working or ["Nothing yet to say."])]
    lines += ["", "## What is not", *(not_working or ["Nothing yet to say."])]
    lines += ["", "## Decision", *decision]
    lines += ["", "## Action items"]
    lines += [f"{i}. {a}" for i, a in enumerate(actions, 1)] or ["1. None."]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- the step
def step(
    progress: Mapping[str, Any],
    raw: Any,
    monday: date,
    now: datetime,
    armed: Mapping[str, str],
    leagues: Iterable[str],
    force: bool = False,
) -> dict[str, Any]:
    """The Monday step on ``progress`` (``GET /progress``'s payload) and the raw knob file:
    with ``force``, this Monday's own change undone first (never one already judged); then the
    verdicts due, each written; then at most one change. ``armed`` maps the armed leagues to
    their scoring, ``leagues`` every league the file may name. Returns the verdicts, the rules
    with their numbers, the change, the knob file after it and the note."""
    m = monday.isoformat()
    out_raw: dict[str, Any] = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    leagues = _ids(set(leagues) | set(armed))
    if force:
        for c in [c for c in out_raw.get("changes") or [] if isinstance(c, dict)]:
            if c.get("monday") == m:
                if c.get("verdict") is not None:
                    raise ValueError(f"{c.get('id')} of {m} is already judged")
                _undo(out_raw, c, leagues)
                out_raw["changes"].remove(c)

    rows = {
        str(lg["league"]): lg.get("weeks") or []
        for lg in progress.get("leagues") or []
        if str(lg["league"]) in armed
    }
    moves = [m_ for m_ in progress.get("moves") or [] if str(m_.get("league")) in armed]
    last = progress.get("last_recorded")
    weeks = progress.get("weeks") or []

    knobs, _ = pg.knob_file(out_raw)
    for c in knobs["changes"]:
        c["week"] = pg.week_at(weeks, c["monday"]) if weeks else None
    verdicts = []
    for c in knobs["changes"]:
        target = _raw_change(out_raw, c["id"])
        if c["judged_on"] == m and target is not None and (earlier := _judged(c, target)):
            # Judged by this Monday's first run (``force`` runs it again): the note keeps it.
            verdicts.append(earlier)
            continue
        if not due(c, last):
            continue
        v = verdict(c, armed, rows, moves, knobs)
        verdicts.append(v)
        if v["verdict"] == "kept":
            reach = _roll_out(out_raw, target or c, armed, leagues)
        else:
            _undo(out_raw, target or c, leagues)
            reach = v["leagues"]
        if target is not None:
            target |= {
                "verdict": v["verdict"],
                "judged_on": m,
                "rolled_out": m if v["verdict"] == "kept" else None,
                "judged": {
                    "decided_by": v["decided_by"],
                    "window": v["window"],
                    "leagues": v["leagues"],
                    "b_leagues": v["b_leagues"],
                    "a": v["a"],
                    "b": v["b"],
                    "since": v["since"],
                    "a_ytd": v["a_ytd"],
                    "b_ytd": v["b_ytd"],
                    "reached": reach,
                },
            }

    knobs, _ = pg.knob_file(out_raw)
    outcomes = rules(knobs, armed, moves, m)
    chosen = next((r for r in outcomes if r["clears"] and "blocked" not in r), None)
    change = None
    if chosen is not None:
        was = {
            knob: {lg: value(knobs, lg, knob) for lg in chosen["leagues"]} for knob in chosen["set"]
        }
        change = {
            "id": _next_id(out_raw),
            "monday": m,
            "knob": chosen["knob"],
            "from": chosen["from"],
            "to": chosen["to"],
            "leagues": chosen["leagues"],
            "source": "master",
            "reason": chosen["reason"],
            "decided_at": now.isoformat(timespec="seconds"),
            "verdict": None,
            "judged_on": None,
            "rolled_out": None,
            "scoring": chosen["scoring"],
            "rule": chosen["rule"],
            "b_leagues": chosen["b_leagues"],
            "set": chosen["set"],
            "was": was,
        }
        for knob, to in chosen["set"].items():
            write(out_raw, knob, dict.fromkeys(chosen["leagues"], to), leagues)
        changes = out_raw.get("changes")
        if not isinstance(changes, list):
            changes = out_raw["changes"] = []
        changes.append(change)

    after, _ = pg.knob_file(out_raw)
    for c in after["changes"]:
        c["week"] = pg.week_at(weeks, c["monday"]) if weeks else None
    pending = [
        c
        for c in after["changes"]
        if c["verdict"] is None and c.get("source") != "user" and c["monday"] != m
    ]
    text = note(m, progress.get("sentences") or [], verdicts, change, outcomes, pending)
    return {
        "monday": m,
        "verdicts": verdicts,
        "rules": outcomes,
        "change": change,
        "knobs": out_raw,
        "note": text,
    }
