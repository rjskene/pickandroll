"""SEASON SIM (#172, PR H1): the screen's list of levers and the rules that read a pair.

A screen answers one question: which levers move a season at all? It nudges each lever once
against a baseline arm, on the same paths, and lists what moved. It chooses no value, writes no
knob file and reads no live league.

This module is the list and the rules, and touches no file:

- :data:`LEVERS`, the levers and their nudges, written before any result. A lever is added by
  the PR that builds it; no flag invents a nudge.
- :func:`rows_of`, the pairs a baseline arm gives: for each lever, arm A is the baseline on the
  cheapest tier that reads the lever, set to whatever else makes it read, and arm B is A with the
  one nudge. A lever the run's league does not read (``policy.reads``, ``policy.field_reads``) is
  listed with the reason and not played; a nudge the knob's own bounds refuse, or the grid has no
  step for, is listed and not played; a nudge equal to the baseline's value is refused by name.
- :func:`result_of`, what a played pair's figures say: the paired difference on the measure the
  league's standings count against one standard error, and "did nothing" when the two arms'
  counts and outcomes are equal on every path (less the counts that part by construction
  between two arms, ``counts.APART_BY_CONSTRUCTION``).

The command that plays each pair, by the code ``replay`` plays a pair with, is ``cli.cmd_screen``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import counts as ct
from . import forecast as fc
from . import policy
from . import run as rn
from .engine import BLEND, EACH_CATEGORY, FLOOR_STEP, PLAN_CAP, PLAN_DEFAULT, sg

#: The screen's version in its record: 1, the list of PR H1. A change to the list, to a nudge or
#: to a rule below is a new version, and a folder started under another is refused.
SCREEN_VERSION = 1
#: What the Monday step multiplies a plan floor by (``season.hillclimb``'s plan rule, where the
#: figure is written in the rule itself): the step up of the knob's own grid; the step down
#: divides by it.
PLAN_STEP = 1.5

#: A row's status: a pair to play, a lever the run's league does not read, a nudge that cannot be
#: made, and a nudge equal to the baseline's value (the screen is refused by name).
PLAY = "to play"
NOT_READ = "not read here"
NOT_PLAYED = "not played"
REFUSED = "refused"
#: A played pair's status in the record, and a pair left for the next piece.
PLAYED = "played"
LEFT = "left for the next piece"

#: Why a nudge that needs the season scale is not made: before the scale is measured, and when
#: no path of the first cell has one.
UNMEASURED = "the run's season scale is not measured yet"
NO_RATIO = "no path of the first cell has a season scale (no swap there has a season value)"
ZERO_RATIO = "the run's season scale is 0: a share of it is no nudge"
#: How the season scale is measured, for the record.
SCALE_NOTE = (
    "the mean, over the first cell's paths that have one, of the baseline's season scale on the "
    "surrogate tier on the path's first simulated day (the ratio: the season_weight at which the "
    "season term is the week gain's size); measured once, before any pair, and kept with the "
    "screen so a later piece uses the same figure"
)
#: The one sentence a plan floor's row adds in a FAAB run.
PLAN_FAAB_NOTE = (
    "in a FAAB run a seat that bids also reads this floor as its typical gain until ten moves, "
    "on the surrogate tier too; that is not what this row screens, which is the plan's floor on "
    "the exact tier executing the plan (whose own bids read it as well)"
)
#: The bar a lever survives at, for the record and the table.
RULE = (
    "a lever survives when its paired difference (B less A) clears one standard error, either "
    "way, on the measure the league's standings count, in a cell of the run; a lever whose two "
    "arms' counts and outcomes are equal on every path did nothing (its difference is zero by "
    "construction) and does not survive; advisory: a survivor is a candidate for the tune, not "
    "a finding"
)
#: The measures by name, for the table.
MEASURE_WORDS = {"matchup_wins": "matchup wins", "category_wins": "category wins"}


@dataclass(frozen=True)
class Context:
    """What of the run a nudge reads: the league's scoring and its waivers, and the run's season
    scale (:data:`SCALE_NOTE`); with no scale, ``no_scale`` says why."""

    scoring: str = "categories"
    waivers: str = "none"
    scale: float | None = None
    no_scale: str = UNMEASURED


@dataclass(frozen=True)
class Step:
    """One nudge of a lever: its short name (the pair's file is ``<lever>-<tag>``), its words,
    what arm B takes (a knob's or a spec key's value by name), why the grid has no such step
    when it has none, and whether it waits on the season scale."""

    tag: str
    words: str
    change: Mapping[str, Any] = field(default_factory=dict)
    unmade: str | None = None
    scale: bool = False


#: What a lever makes of the baseline at its tier: what else is set in both arms, and its steps.
Make = Callable[[rn.Arm, Context], tuple[Mapping[str, Any], Sequence[Step]]]


@dataclass(frozen=True)
class Lever:
    """One row of the list: the lever's name (the knob, field or spec key it nudges), the
    cheapest tier that reads it, its nudges in words, what both arms are set to so that it
    reads, in words, and how its pair is made."""

    name: str
    tier: str
    nudge: str
    make: Make
    both: str = ""


def _figure(x: float) -> float:
    """A measured figure as the arm takes it: four significant digits."""
    return float(f"{x:.4g}")


def _plain(steps: Callable[[rn.Arm, Context], Sequence[Step]]) -> Make:
    return lambda base, ctx: ({}, steps(base, ctx))


def _floor(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    at, step = float(base.knobs["protection_floor"]), FLOOR_STEP[ctx.scoring]
    return (
        Step("down", "one step down", {"protection_floor": round(at - step, 4)}),
        Step("up", "one step up", {"protection_floor": round(at + step, 4)}),
    )


def _cap(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    at = int(base.knobs["daily_cap"])
    return (
        Step("minus", "minus 1", {"daily_cap": at - 1}),
        Step("plus", "plus 1", {"daily_cap": at + 1}),
    )


def _plan(name: str, scoring: str) -> Make:
    def make(base: rn.Arm, ctx: Context) -> tuple[Mapping[str, Any], Sequence[Step]]:
        both = {"with_plan": True, "execute_plan": True}
        at = float(base.knobs[name])
        if at <= 0:
            why = "a floor at or below zero has no step: the grid multiplies"
            return both, (
                Step("down", "one step down", unmade=why),
                Step("up", "one step up", unmade=why),
            )
        cap = round(PLAN_CAP * PLAN_DEFAULT[scoring], 4)
        up = min(round(at * PLAN_STEP, 4), cap)
        return both, (
            Step("down", "one step down", {name: round(at / PLAN_STEP, 4)}),
            Step(
                "up",
                "one step up",
                {name: up},
                None if up > at else "the floor is at its cap",
            ),
        )

    return make


def _horizon(base: rn.Arm, ctx: Context) -> tuple[Mapping[str, Any], Sequence[Step]]:
    keys = sg.WEIGHT_KEYS
    i = keys.index(str(base.knobs["horizon_weight"]))
    return {"executes": policy.WEIGHTED}, tuple(
        Step(keys[j], f"to its neighbour {keys[j]}", {"horizon_weight": keys[j]})
        for j in (i - 1, i + 1)
        if 0 <= j < len(keys)
    )


def _sizing(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    return (
        Step("0.5", "to 0.5", {"faab_sizing": 0.5}),
        Step("2", "to 2", {"faab_sizing": 2.0}),
    )


def _no_scale(ctx: Context) -> str | None:
    """Why a nudge by the season scale cannot be made; None when it can."""
    if ctx.scale is None:
        return ctx.no_scale
    return None if ctx.scale > 0 else ZERO_RATIO


def _season(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    at, why = float(base.knobs["season_weight"]), _no_scale(ctx)
    shares = (("quarter", "plus a quarter of the season scale", 4), ("half", "plus a half", 2))
    if why is not None:
        return tuple(Step(tag, words, unmade=why, scale=True) for tag, words, _ in shares)
    return tuple(
        Step(tag, words, {"season_weight": _figure(at + ctx.scale / part)})
        for tag, words, part in shares
    )


def _playoff(base: rn.Arm, ctx: Context) -> tuple[Mapping[str, Any], Sequence[Step]]:
    step = Step("1.5", "to 1.5", {"playoff_weight": 1.5})
    if float(base.knobs["season_weight"]) > 0:
        return {}, (step,)
    why = _no_scale(ctx)
    if why is not None:
        # A stand-in above zero, so the reads table answers for the pair as it would be played.
        return {"season_weight": 1.0}, (Step("1.5", "to 1.5", unmade=why, scale=True),)
    return {"season_weight": _figure(ctx.scale / 4)}, (step,)


def _gain(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    at = float(base.fields.min_gain)
    if at <= 0:
        return (Step("double", "twice the baseline's", unmade="twice a min_gain of 0 is 0"),)
    return (Step("double", "twice the baseline's", {"min_gain": 2 * at}),)


def _system(base: rn.Arm, ctx: Context) -> Sequence[Step]:
    at = str(base.knobs["system"])
    return tuple(
        Step(
            s,
            f"to {s}" + (f", the mix at {BLEND:g}" if s == "blend" else ""),
            {"system": s, **({"blend": BLEND} if s == "blend" else {})},
        )
        for s in fc.SYSTEMS
        if s != at
    )


def _blend(base: rn.Arm, ctx: Context) -> tuple[Mapping[str, Any], Sequence[Step]]:
    both: dict[str, Any] = {}
    if base.knobs["system"] != "blend":
        both["system"] = "blend"
    if base.knobs["blend"] is None:
        both["blend"] = BLEND
    return both, (
        Step("0.25", "to 0.25", {"blend": 0.25}),
        Step("0.75", "to 0.75", {"blend": 0.75}),
    )


#: The list (Rule 2: written before any result), one row a lever, in the order the table prints.
#: A floor's step is the Monday step's own grid: the protection floor's a game by scoring
#: (``FLOOR_STEP``), a plan floor's times and divided by :data:`PLAN_STEP`, never above
#: ``PLAN_CAP`` times its default.
LEVERS: tuple[Lever, ...] = (
    Lever(
        "protection_floor",
        "surrogate",
        "one step down and one step up",
        _plain(_floor),
    ),
    Lever("daily_cap", "surrogate", "minus 1 and plus 1", _plain(_cap)),
    Lever(
        "plan_floor_cats",
        "exact",
        "one step each way",
        _plan("plan_floor_cats", "categories"),
        "the week plan drawn and executed",
    ),
    Lever(
        "plan_floor_points",
        "exact",
        "one step each way",
        _plan("plan_floor_points", "points"),
        "the week plan drawn and executed",
    ),
    Lever(
        "horizon_weight",
        "exact",
        "to each neighbour on the frontier",
        _horizon,
        "executes weighted",
    ),
    Lever("faab_sizing", "surrogate", "to 0.5 and to 2", _plain(_sizing)),
    Lever(
        "season_weight",
        "surrogate",
        "plus a quarter of the run's season scale, and plus a half",
        _plain(_season),
    ),
    Lever(
        "playoff_weight",
        "surrogate",
        "to 1.5",
        _playoff,
        "a season weight: the baseline's, or with none a quarter of the run's season scale",
    ),
    Lever("pool", "surrogate", "to 45", _plain(lambda b, c: (Step("45", "to 45", {"pool": 45}),))),
    Lever("min_gain", "surrogate", "twice the baseline's", _plain(_gain)),
    Lever(
        "weeks_ahead",
        "surrogate",
        "to 6",
        _plain(lambda b, c: (Step("6", "to 6", {"weeks_ahead": 6}),)),
    ),
    Lever(
        "surrogate_days",
        "surrogate",
        "Monday only",
        _plain(lambda b, c: (Step("monday", "Monday only", {"surrogate_days": [0]}),)),
    ),
    Lever(
        "executes",
        "exact",
        "to weighted",
        _plain(lambda b, c: (Step("weighted", "to weighted", {"executes": policy.WEIGHTED}),)),
    ),
    Lever(
        "with_plan",
        "exact",
        "flipped",
        _plain(lambda b, c: (Step("flipped", "flipped", {"with_plan": not b.with_plan}),)),
    ),
    Lever(
        "execute_plan",
        "exact",
        "flipped",
        _plain(lambda b, c: (Step("flipped", "flipped", {"execute_plan": not b.execute_plan}),)),
    ),
    Lever(
        "system",
        "surrogate",
        f"to each other source, and to the mix at {BLEND:g}",
        _plain(_system),
    ),
    Lever("blend", "surrogate", "to 0.25 and to 0.75", _blend, "system blend"),
    # The union pool (PR pool): to the size of the list the live search takes beside its pool.
    Lever(
        "guard_pool",
        "exact",
        "to 30",
        _plain(lambda b, c: (Step("30", "to 30", {"guard_pool": 30}),)),
    ),
)
#: The levers' names, in the list's order.
NAMES: tuple[str, ...] = tuple(lever.name for lever in LEVERS)


# --------------------------------------------------------------------------- a lever's pair
def applied(spec: Mapping[str, Any], change: Mapping[str, Any]) -> dict[str, Any]:
    """``spec`` with ``change``: a knob's value under ``knobs``, any other name a spec key's."""
    out = dict(spec)
    knobs = dict(spec.get("knobs") or {})
    for name, value in change.items():
        if name in policy.KNOBS:
            knobs[name] = value
        else:
            out[name] = value
    out["knobs"] = knobs
    return out


def value_of(arm: rn.Arm, name: str) -> Any:
    """What ``arm`` holds under ``name``: a knob's value, a field's, or a spec key's."""
    if name in policy.KNOBS:
        return arm.knobs[name]
    if name in policy.FIELDS:
        value = getattr(arm.fields, name)
        return list(value) if isinstance(value, tuple) else value
    return getattr(arm, name)


def shown(value: Any) -> str:
    """A value as the table prints it."""
    if isinstance(value, bool) or value is None:
        return str(value).lower() if isinstance(value, bool) else "none"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(shown(v) for v in value) + "]"
    return str(value)


def read_why(name: str, arm: rn.Arm, shapes: Sequence[policy.Shape]) -> str | None:
    """Why the run's league does not read lever ``name`` on ``arm`` in any of ``shapes``; None
    when it does in one. A knob and a field by the reads table (``policy.reads``,
    ``policy.field_reads``; a mirror's rivals read what the surrogate reads). The three spec
    keys by what they are: ``executes`` is read on the exact tier; a week plan only recorded
    changes no season, so ``with_plan`` is read only by an arm that executes the plan and
    ``execute_plan`` only by one that draws it."""
    mirror = rn.mirrored(arm)
    if name in policy.KNOBS:
        whys = [policy.reads(arm, shape, mirror)[name] for shape in shapes]
    elif name in policy.FIELDS:
        whys = [policy.field_reads(arm, mirror)[name]]
    elif arm.tier != "exact":
        whys = [f"only the exact tier reads {name}"]
    elif name == "with_plan" and not arm.execute_plan:
        whys = ["the plan is drawn and not executed"]
    elif name == "execute_plan" and not arm.with_plan:
        whys = ["the arm draws no week plan"]
    else:
        whys = [policy.READ]
    return None if policy.READ in whys else whys[0]


@dataclass(frozen=True)
class Row:
    """One row of a screen: the lever, its pair's name in the folder (``key``), the nudge in
    words, the tier the pair is played on and what else both arms were set to (by name, each a
    change from the baseline), its status and the reason when it is not played, a note, the two
    arms' specs when it is a pair, the lever's value in each arm, and whether it waits on the
    season scale."""

    lever: str
    key: str
    nudge: str
    tier: str
    status: str
    why: str | None = None
    both: Mapping[str, Any] = field(default_factory=dict)
    note: str | None = None
    a: Mapping[str, Any] | None = None
    b: Mapping[str, Any] | None = None
    values: Mapping[str, Any] | None = None
    scale: bool = False

    def payload(self) -> dict[str, Any]:
        """The row as the record keeps it (the arms' specs are in the pair's own record)."""
        return {
            "lever": self.lever,
            "key": self.key,
            "nudge": self.nudge,
            "tier": self.tier,
            "both": dict(self.both),
            "values": None if self.values is None else dict(self.values),
            "status": self.status,
            "why": self.why,
            "note": self.note,
        }


def _lever_rows(
    lever: Lever, spec: Mapping[str, Any], shapes: Sequence[policy.Shape], ctx: Context
) -> list[Row]:
    plain = rn.arm_of(spec)
    tiered = applied(spec, {"tier": lever.tier})
    sets, steps = lever.make(rn.arm_of(tiered), ctx)
    a_spec = applied(tiered, sets)
    a = rn.arm_of(a_spec)
    both = {k: value_of(a, k) for k in ("tier", *sets) if value_of(a, k) != value_of(plain, k)}
    floor = lever.name in ("plan_floor_cats", "plan_floor_points")
    note = PLAN_FAAB_NOTE if floor and ctx.waivers == "faab" else None

    def row(key: str, nudge: str, status: str, **more: Any) -> Row:
        return Row(
            lever.name, key, nudge, lever.tier, status, **{"both": both, "note": note, **more}
        )

    why = read_why(lever.name, a, shapes)
    if why is not None:
        return [row(lever.name, lever.nudge, NOT_READ, why=why, note=None)]
    out = []
    for step in steps:
        key = f"{lever.name}-{step.tag}"
        if step.unmade is not None:
            # A pair that waits on the scale holds a stand-in for it, which is no setting.
            kept = {k: v for k, v in both.items() if k == "tier"} if step.scale else both
            out.append(
                row(key, step.words, NOT_PLAYED, why=step.unmade, scale=step.scale, both=kept)
            )
            continue
        bounds = [policy.knob_refused(k, v) for k, v in step.change.items() if k in policy.KNOBS]
        refused = next((w for w in bounds if w is not None), None)
        b_spec = applied(a_spec, {**step.change, "name": f"{a.name}:{key}"})
        if refused is None:
            try:
                b = rn.arm_of(b_spec)
            except ValueError as e:
                refused = str(e)
        if refused is not None:
            out.append(row(key, step.words, NOT_PLAYED, why=refused))
            continue
        values = {"a": value_of(a, lever.name), "b": value_of(b, lever.name)}
        nudge = f"{step.words}: {shown(values['a'])} to {shown(values['b'])}"
        if all(value_of(b, k) == value_of(a, k) for k in step.change):
            out.append(
                row(
                    key,
                    nudge,
                    REFUSED,
                    why=(
                        f"lever {lever.name}: its nudge {step.words} is the baseline's value "
                        f"({shown(values['a'])}): the pair would be one seat twice; leave the "
                        "lever out with --levers, or screen another baseline"
                    ),
                    values=values,
                )
            )
            continue
        out.append(row(key, nudge, PLAY, a=a_spec, b=b_spec, values=values))
    return out


def rows_of(
    spec: Mapping[str, Any],
    names: Sequence[str],
    shapes: Sequence[policy.Shape],
    ctx: Context,
) -> list[Row]:
    """The screen's rows for the baseline arm ``spec`` and the levers ``names``, in the list's
    order (whatever order they are named in), on a run whose league shapes are ``shapes``. The
    baseline is parsed as every arm is (``run.arm_of``: ValueError, KeyError by name); a name
    not in the list is a KeyError."""
    unknown = [n for n in names if n not in NAMES]
    if unknown:
        raise KeyError(f"lever {unknown[0]!r} is not in the screen's list: one of {NAMES}")
    return [
        r for lever in LEVERS if lever.name in names for r in _lever_rows(lever, spec, shapes, ctx)
    ]


# --------------------------------------------------------------------------- a pair's result
def measure_of(scoring: str, h2h: str) -> str:
    """The measure a league's standings count, by the outcome's name: category wins where every
    category of a week is a result, matchup wins where a week is one result (a one-win league,
    and a points league, whose week is one result on the points)."""
    return "category_wins" if scoring == "categories" and h2h == EACH_CATEGORY else "matchup_wins"


def clears(mean: float | None, se: float | None) -> bool:
    """Whether a difference clears one standard error, either way; never without an SE (fewer
    than two paths)."""
    return mean is not None and se is not None and abs(mean) > se


def _played(counts: Mapping[str, Any]) -> dict[str, Any]:
    """A seat's counts less the ones that part by construction between two arms and are no
    difference of the season it played (``counts.APART_BY_CONSTRUCTION``, declared beside each
    key's definition)."""
    return {k: v for k, v in counts.items() if k not in ct.APART_BY_CONSTRUCTION}


def result_of(
    payload: Mapping[str, Any], standing: Sequence[Mapping[str, Any]], measure: str
) -> dict[str, Any]:
    """What a played pair says, from its record (``payload``, as ``replay`` writes a pair) and
    its standing paths' task results (``standing``: those the audit did not void): by cell, the
    paired difference B less A with its SE on every outcome and whether it clears one SE on
    ``measure``, and both arms' counts; whether every standing path's counts are equal between
    the two arms and whether its outcomes are; whether the lever did nothing (both: the two arms
    played one season on every path, as far as a record tells); and whether it survives
    (:data:`RULE`). Both arms play one world, so equal counts with an outcome that differs is a
    lever that changed which moves were made, not how many: it did something.

    The counts compared are every one but those declared to part by construction between two
    arms (``counts.APART_BY_CONSTRUCTION``, PR pool): an arm with such a lever on counts them
    and an arm with it off never does, whatever either plays, so they say nothing of whether
    the two played one season. Both arms' counts are still recorded whole. A row whose counts
    declare none is read on all of them."""
    cells = {
        t: {
            label: {
                "paths": c["paths"],
                "difference": c["difference"],
                "clears": clears(c["difference"][measure]["mean"], c["difference"][measure]["se"]),
                "counts": {
                    side: payload["counts"]["by_season"][t][label][side] for side in ("a", "b")
                },
            }
            for label, c in by_label.items()
        }
        for t, by_label in payload["results"].items()
    }
    counts = all(_played(r["counts"]["a"]) == _played(r["counts"]["b"]) for r in standing)
    outcomes = all(all(not v for v in r["delta"].values()) for r in standing)
    nothing = counts and outcomes
    return {
        "measure": measure,
        "paths": len(standing),
        "voided": int(payload["audit"]["paths_voided"]),
        "cells": cells,
        "counts_equal": counts,
        "outcomes_equal": outcomes,
        "did_nothing": nothing,
        "survives": not nothing and any(c["clears"] for d in cells.values() for c in d.values()),
    }


# --------------------------------------------------------------------------- the table
def result_words(result: Mapping[str, Any]) -> str:
    """A played row's result as the table prints it."""
    words = MEASURE_WORDS.get(result["measure"], result["measure"])
    many = sum(len(d) for d in result["cells"].values()) > 1
    parts = []
    for t, by_label in result["cells"].items():
        for label, c in by_label.items():
            d = c["difference"][result["measure"]]
            se = "n/a" if d["se"] is None else f"{d['se']:.3f}"
            mean = "n/a" if d["mean"] is None else f"{d['mean']:+.3f}"
            where = f"{t} {label}: " if many else ""
            parts.append(f"{where}{words} {mean} (SE {se}) over {c['paths']} paths")
    out = "; ".join(parts)
    if result["did_nothing"]:
        out = "did nothing (both arms' counts and outcomes are equal on every path): " + out
    elif result["survives"]:
        out += "; survives"
    if result["voided"]:
        out += f"; {result['voided']} path(s) voided"
    return out


def listing(rows: Sequence[Mapping[str, Any]], texts: Sequence[str]) -> list[str]:
    """The rows as a table in the list's order: the lever, the nudge, the tier and ``texts``'
    words for each, with what both arms were set to and the row's note under a row that is read."""
    if not rows:
        return ["no lever"]
    w1 = max(len("lever"), *(len(r["lever"]) for r in rows))
    w2 = max(len("nudge"), *(len(r["nudge"]) for r in rows))
    w3 = max(len("tier"), *(len(r["tier"]) for r in rows))
    out = [f"  {'lever':<{w1}}  {'nudge':<{w2}}  {'tier':<{w3}}  result"]
    for r, text in zip(rows, texts, strict=True):
        both = {k: v for k, v in r["both"].items() if k != "tier"}
        if both and r["status"] != NOT_READ:
            text += " [both arms: " + ", ".join(f"{k} {shown(v)}" for k, v in both.items()) + "]"
        out.append(f"  {r['lever']:<{w1}}  {r['nudge']:<{w2}}  {r['tier']:<{w3}}  {text}")
        if r.get("note") and r["status"] != NOT_READ:
            out.append(f"  {'':<{w1}}  note: {r['note']}")
    return out


def status_words(row: Mapping[str, Any]) -> str:
    """A row that is not a played pair, as the table prints it."""
    if row["status"] in (NOT_READ, NOT_PLAYED):
        return f"{row['status']}: {row['why']}"
    return row["status"]


def table(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """The screen's table from its record's rows (``Row.payload`` with a played pair's
    ``result``): every row in the list's order, then the survivors."""
    texts = [
        result_words(r["result"]) if r.get("result") is not None else status_words(r) for r in rows
    ]
    kept = [r for r in rows if (r.get("result") or {}).get("survives")]
    return [
        *listing(rows, texts),
        "survivors: " + ("; ".join(f"{r['lever']} ({r['nudge']})" for r in kept) or "none"),
    ]


def spec_differs(was: Mapping[str, Any], now: Mapping[str, Any]) -> str | None:
    """The first name the two specs differ in (a world flag by its own name), with both values;
    None when they are one spec."""
    for key in sorted({*was, *now}):
        a, b = was.get(key), now.get(key)
        if a == b:
            continue
        if isinstance(a, Mapping) and isinstance(b, Mapping) and key == "world":
            inner = next(k for k in sorted({*a, *b}) if a.get(k) != b.get(k))
            return f"{inner}: started with {a.get(inner)!r}, now {b.get(inner)!r}"
        if key == "arm":
            return "the baseline arm's spec"
        return f"{key}: started with {a!r}, now {b!r}"
    return None


__all__ = [
    "LEFT",
    "LEVERS",
    "NAMES",
    "NOT_PLAYED",
    "NOT_READ",
    "NO_RATIO",
    "PLAN_FAAB_NOTE",
    "PLAN_STEP",
    "PLAY",
    "PLAYED",
    "REFUSED",
    "RULE",
    "SCALE_NOTE",
    "SCREEN_VERSION",
    "Context",
    "Lever",
    "Row",
    "Step",
    "applied",
    "clears",
    "listing",
    "measure_of",
    "read_why",
    "result_of",
    "result_words",
    "rows_of",
    "shown",
    "spec_differs",
    "status_words",
    "table",
    "value_of",
]
