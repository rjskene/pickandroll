"""SEASON SIM (#172, PR H2): the tune's rules.

A tune answers: among the levers that survived a screen, which values does the simulator
recommend, and does that hold on a season it never searched? It recommends; it promotes nothing,
writes no knob file and reads no live league.

This module is the rules, and touches no file. Every choice is fixed before a result: the levers'
order, their values and the measure.

- :func:`order_of`, the levers and their order: a screen's survivors, strongest first by the
  size of the difference over its SE, or the levers named.
- :func:`values_of`, a lever's values from the current arm: the screen's own rows (``screen.LEVERS``,
  ``screen.rows_of``: the list's nudge, on the cheapest tier that reads the lever) and each
  nudge again (:func:`second_of`, derived from the row as it is).
- :func:`value_result`, what a played value says: the mean over the run's cells of the paired
  difference on the measure the league's standings count, its SE, and whether every cell is on
  one side.
- :func:`choose`, the step's choice: the best value that counts and clears one SE, or none.
- :func:`confirmation_of` and :func:`verdict_of`, the final set against the baseline on the
  season the search never played: stated on playoff odds and final rank, by forecaster, against
  the run's rivals and against static ones.

The command that plays each pair, by the code ``replay`` plays a pair with, is ``cli.cmd_tune``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from . import policy
from . import run as rn
from . import screen as sc

#: The tune's version in its record: 1, the search and the confirmation of PR H2. A change to a
#: rule below is a new version, and a folder started under another is refused.
TUNE_VERSION = 1
#: The passes over the levers when ``--passes`` names none.
PASSES = 1
#: What a second step's key adds to its nudge's.
AGAIN = "again"

#: Where a lever's order comes from, for the record.
BY_SCREEN = "the screen's order: strongest first by the size of the difference over its SE"
BY_HAND = "named by hand, in the list's order"
UNSCREENED = (
    "named by hand and not played in the screen: after the screened ones, in the list's order"
)

#: Why a value is not played: the nudge leaves the lever where the current arm holds it.
CURRENT = "the current value"
#: How near two figures of one lever are one value: one unit of the fourth significant digit,
#: the rounding a measured figure is kept to (the screen's season scale). A quarter of the scale
#: taken twice and its half taken once are each rounded, so they can differ by that much.
ROUNDING = 1.1e-3
#: The second steps the rules of :func:`second_of` cannot derive, by the nudge's key: what arm B
#: takes at the nudge again. A step from None has no size to repeat, so the sizing's two (a
#: multiplier, None being 1) are written here: the same factor again.
SECOND: Mapping[str, Mapping[str, Any]] = {
    "faab_sizing-0.5": {"faab_sizing": 0.25},
    "faab_sizing-2": {"faab_sizing": 4.0},
}

#: A played value's cells: every one above zero, every one below, both sides, or one with no
#: difference (or no figure).
ABOVE, BELOW, FLIPS, NO_SIGN = "above", "below", "flips", "none"
#: What a played value is, in its step's record.
TAKEN = "taken"
BEATEN = "clears one SE with every cell above zero, and another value that clears is ahead of it"
PASSED = "a larger mean than the value taken, passed over: it is not above one SE"
WITHIN = "within one SE"
NO_SE = "no SE (fewer than two paths stand in every cell)"
NOTHING = "did nothing (both arms' counts and outcomes are equal on every path)"
WORSE = "below zero in every cell"
FLAT_CELL = "no difference in a cell: its sign does not agree in every cell"
DEPENDS_SEASON = "depends on the season"
DEPENDS_FORECASTER = "depends on the forecaster"
DEPENDS_BOTH = "depends on the season and on the forecaster"
DEPENDS = (DEPENDS_SEASON, DEPENDS_FORECASTER, DEPENDS_BOTH)
NO_CELL = "no cell the rule reads"

#: The search's rule, for the record and the plan.
SEARCH_RULE = (
    "one lever at a time, in an order fixed before any pair; a lever's values are the current "
    "one, each of the list's nudges and each nudge again; every value is a pair against the "
    "current arm on the same paths, on every season and forecaster the search names; a value's "
    "difference (B less A) is the mean over those cells on the measure the league's standings "
    "count, its SE over the paths (a path's figure the mean over its cells), and it counts only "
    "when every cell is above zero; a value is eligible when it counts and its difference is "
    "above one SE; the lever takes the eligible value with the largest difference (a tie to the "
    "first in the lever's order) and stays when none is eligible; a value with a larger "
    "difference that is not above one SE is passed over, and the step says so; an oracle's "
    "cells and a season that fails espn's freeze check are shown and not read"
)
#: What the current arm takes from a chosen value.
CARRY_NOTE = (
    "the current arm takes the lever's own value and nothing else: a value found on another "
    "tier, or with something else set in both arms, is recorded with what it was found under, "
    "and the final set says which of its values the final arm does not read"
)

#: A confirmation cell's finish, on playoff odds and final rank.
AHEAD = "ahead"
BEHIND = "behind"
MIXED = "ahead on one and behind on the other"
LEVEL = "no difference beyond one SE"
UNSURE = "no SE"
#: The verdict's states.
HOLDS = "holds"
NOT_SHOWN = "not shown"
AGAINST = "against"
#: The two kinds of rivals the confirmation is played against.
RUN, STATIC = "run", "static"
RIVALS_WORDS = {RUN: "the run's rivals", STATIC: "static rivals"}
#: A kind of rivals against which the final arm is the baseline's seat (the two arms differ only
#: in what neither reads there): its pair is not played, and its finish is this.
ONE_SEAT = "the baseline's seat: no difference by construction"
#: The confirmation's statuses in the record.
CONFIRMED = "played"
NO_CONFIRMATION = "no confirmation, not a verdict"
NOTHING_TO_CONFIRM = (
    "nothing to confirm: no lever moved, so the final set is the baseline and the season the "
    "search never played is not read"
)
SAME_SEAT = (
    "nothing to confirm: the final arm reads none of the values that moved, so it is the "
    "baseline's seat and the season the search never played is not read"
)
NOT_YET = "left for the next piece"
UNPLANNED = (
    "not played: the confirmation's pair cannot be planned on the season confirmed on; no path "
    "of the season was played and no look is counted"
)
#: The verdict's rule, for the record.
VERDICT_RULE = (
    "on the season the search never played, the final set (B) against the baseline (A), by "
    "forecaster, against the run's rivals: a cell is ahead when its paired change in playoff "
    "odds is above zero or its change in final rank below zero (a better finish) by more than "
    "one SE and neither is the other way by more than one SE; behind the other way round; the "
    "final set holds when every forecaster the rule reads is ahead, is against when one is "
    "behind, and is not shown otherwise; a forecaster the search read that has no cell on that "
    "season is no verdict; one whose cell is there and not read (espn's, on a season that fails "
    "its freeze check) leaves a verdict on the others, and the verdict's line names it as not "
    "confirmed, with why; the standings' measure is shown beside and decides nothing here; "
    "the same pair against static rivals is shown, and an edge against one kind of rivals only "
    "is flagged (against static rivals the final arm can be the baseline's seat: that pair is "
    "not played, and an edge against the run's rivals is then against one kind only)"
)
#: What a verdict is and is not, printed with every one.
ADVISORY = (
    "advisory: one withheld season is one realization of the world, and its SE is over the "
    "paths (the seats and the draws), not over the season's own chance; the simulator "
    "recommends, promotes nothing and writes no knob file, and live changes only on the user's "
    "word"
)
#: The verdict's line by state.
VERDICT_WORDS = {
    HOLDS: "the final set is recommended: it finished ahead of the baseline on the withheld season",
    NOT_SHOWN: (
        "the final set is not recommended over the baseline: the withheld season does not show "
        "it ahead beyond one SE for every forecaster"
    ),
    AGAINST: "the final set is not recommended: it finished behind the baseline on the withheld season",
}
#: Why a cell that is there is not read, by replay's mark, as a verdict's line says it. (An
#: oracle's row is a yardstick in the search too, so it is never one the search read.)
UNREAD_WHY = {rn.FREEZE: "its stored projection of that season fails the freeze check"}
#: The same of a mark this list does not hold.
UNREAD = "its cell on that season is not read"
#: What a verdict's line says of the forecasters it rests on when a forecaster the search read
#: went unconfirmed (its cell on the season confirmed on is there and not read), by state: the
#: word never stands alone.
RESTS_ON = {
    HOLDS: "confirmed on {read} alone, ",
    NOT_SHOWN: "stated on {read} alone, ",
    AGAINST: "stated on {read} alone, ",
}
#: And what it says of each forecaster that went unconfirmed, whatever the state.
UNCONFIRMED = "not confirmed on {others}, which the search read"


# --------------------------------------------------------------------------- the order
def strength_of(row: Mapping[str, Any], measure: str) -> float | None:
    """A screen's played row's strength: the largest, over its cells, of the size of its
    difference on ``measure`` over its SE (infinite where the SE is zero and the difference is
    not); None for a row that was not played or whose cells have no SE."""
    result = row.get("result")
    if not result:
        return None
    best: float | None = None
    for by_label in result["cells"].values():
        for cell in by_label.values():
            d = cell["difference"][measure]
            if d["mean"] is None or d["se"] is None:
                continue
            if d["se"] > 0:
                x = abs(d["mean"]) / d["se"]
            else:
                x = math.inf if d["mean"] else 0.0
            best = x if best is None else max(best, x)
    return best


def order_of(screen: Mapping[str, Any] | None, names: Sequence[str] | None) -> list[dict[str, Any]]:
    """The tune's levers in the order they are searched, fixed before any pair: with a
    ``screen``'s record and no ``names``, its survivors, the strongest first (a lever's strength
    its strongest surviving row's, :func:`strength_of`; a tie in the list's order); with both,
    the levers named, those the screen played first by their strongest played row, then the
    others in the list's order; with ``names`` alone, the list's order. Each with where its
    place comes from. A lever not in the code's list is a KeyError; no screen and no name, or a
    screen with no survivor, a ValueError."""
    if names is not None:
        names = list(dict.fromkeys(names))
        unknown = [n for n in names if n not in sc.NAMES]
        if unknown:
            raise KeyError(f"lever {unknown[0]!r} is not in the screen's list: one of {sc.NAMES}")
    index = sc.NAMES.index
    if screen is None:
        if not names:
            raise ValueError(
                "a tune names its levers: a screen's survivors (--screen) or --levers by name"
            )
        return [
            {"lever": n, "from": None, "strength": None, "place": BY_HAND}
            for n in sorted(names, key=index)
        ]
    measure = screen["measure"]
    best: dict[str, tuple[float, Mapping[str, Any]]] = {}
    for row in screen["rows"]:
        x = strength_of(row, measure)
        if x is None or (names is None and not row["result"]["survives"]):
            continue
        lever = row["lever"]
        if lever not in sc.NAMES:
            raise KeyError(
                f"lever {lever!r} of the screen {screen.get('name')!r} is not in the code's "
                f"list: one of {sc.NAMES}"
            )
        if lever not in best or x > best[lever][0]:
            best[lever] = (x, row)
    wanted = list(best) if names is None else names
    if not wanted:
        raise ValueError(f"the screen {screen.get('name')!r} has no survivor: nothing to tune")
    ranked = sorted((n for n in wanted if n in best), key=lambda n: (-best[n][0], index(n)))
    rest = sorted((n for n in wanted if n not in best), key=index)
    out = []
    for n in ranked:
        x, row = best[n]
        out.append(
            {
                "lever": n,
                "from": row["key"],
                # An SE of zero has no finite ratio: the record keeps none and the words say so.
                "strength": x if math.isfinite(x) else None,
                "place": BY_SCREEN if math.isfinite(x) else BY_SCREEN + " (its SE is zero)",
            }
        )
    out += [{"lever": n, "from": None, "strength": None, "place": UNSCREENED} for n in rest]
    return out


def order_words(order: Sequence[Mapping[str, Any]]) -> str:
    """The order as the plan prints it."""
    parts = []
    for o in order:
        if o["from"] is None:
            parts.append(o["lever"])
        elif o["strength"] is None:
            parts.append(f"{o['lever']} ({o['from']}, its SE zero)")
        else:
            parts.append(f"{o['lever']} ({o['from']}, {o['strength']:.2f} SE)")
    return ", ".join(parts)


# --------------------------------------------------------------------------- a lever's values
_MISSING = object()


def change_of(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """What arm B's spec holds that arm A's does not, by name (a knob's value, a spec key's),
    the arm's own name aside: what ``screen.applied`` would take to make B of A."""
    knobs_a = a.get("knobs") or {}
    out = {k: v for k, v in (b.get("knobs") or {}).items() if knobs_a.get(k, _MISSING) != v}
    out |= {k: v for k, v in b.items() if k not in ("knobs", "name") and a.get(k, _MISSING) != v}
    return out


def _number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _continued(a: Any, b: Any) -> Any:
    """The step from ``a`` to ``b`` taken again from ``b``: a whole number stays whole."""
    if isinstance(a, int) and isinstance(b, int):
        return b + (b - a)
    return round(float(b) + (float(b) - float(a)), 10)


def _words(row: sc.Row) -> str:
    """A playable row's nudge without its two values (``<words>: <a> to <b>``)."""
    return row.nudge.rsplit(": ", 1)[0]


def second_of(
    name: str,
    spec: Mapping[str, Any],
    first: sc.Row,
    firsts: Sequence[sc.Row],
    shapes: Sequence[policy.Shape],
    ctx: sc.Context,
) -> sc.Row | None:
    """The nudge of ``first`` (a pair to play, one of lever ``name``'s rows ``firsts`` from the
    arm ``spec``) taken again, as a row against the same arm A; None when the nudge has no
    second step. Derived from the row as it is, by the first of these that applies:

    0. the nudge's key is in :data:`SECOND`: the value written there;
    1. the lever is asked for its rows from the nudged arm (``screen.rows_of``): the row of the
       same key, when it moves on (a step written from the arm's own value: a floor's step, the
       cap's, twice the ``min_gain``, a share of the season scale); when that row cannot be made
       (the knob's bounds, a floor at its cap) the second step is listed with that reason;
    2. a row the lever offers from the nudged arm and not from this one, when there is exactly
       one and it does not go back (a step along a frontier: the next neighbour);
    3. the lever's own value is a number in both arms and the nudge changes nothing else: the
       same difference again (``pool`` 30 to 45, then 60).

    A switch, a choice, a list and a step from None have none. The second step's row is refused
    by the knob's own bounds and the arm's parser as a first step's is (not played, with the
    reason), and one equal to the current value is not played."""
    assert first.status == sc.PLAY and first.a is not None and first.b is not None
    assert first.values is not None
    at, to = first.values["a"], first.values["b"]
    step = change_of(first.a, first.b)
    key = f"{first.key}-{AGAIN}"
    words = f"{_words(first)}, {AGAIN}"

    def unmade(why: str) -> sc.Row:
        return replace(
            first, key=key, nudge=words, status=sc.NOT_PLAYED, why=why, a=None, b=None, values=None
        )

    change: Mapping[str, Any] | None = SECOND.get(first.key)
    if change is None:
        try:
            onward = sc.rows_of(sc.applied(spec, step), [name], shapes, ctx)
        except (ValueError, KeyError):
            onward = []
        same = next((r for r in onward if r.key == first.key), None)
        known = {r.key for r in firsts}
        fresh = [
            r
            for r in onward
            if r.key not in known and r.status == sc.PLAY and r.values["b"] not in (at, to)
        ]
        if same is not None and same.status == sc.NOT_PLAYED:
            return unmade(str(same.why))
        if same is not None and same.status == sc.PLAY and same.values["b"] not in (at, to):
            change = change_of(same.a or {}, same.b or {})
        elif len(fresh) == 1:
            change = change_of(fresh[0].a or {}, fresh[0].b or {})
        elif _number(at) and _number(to) and set(step) == {name}:
            change = {name: _continued(at, to)}
    if change is None:
        return None
    bounds = [policy.knob_refused(k, v) for k, v in change.items() if k in policy.KNOBS]
    refused = next((w for w in bounds if w is not None), None)
    a = rn.arm_of(first.a)
    b_spec = sc.applied(first.a, {**change, "name": f"{a.name}:{key}"})
    b = None
    if refused is None:
        try:
            b = rn.arm_of(b_spec)
        except ValueError as e:
            refused = str(e)
    if refused is not None or b is None:
        return unmade(str(refused))
    if all(sc.value_of(b, k) == sc.value_of(a, k) for k in change):
        return unmade(CURRENT)
    values = {"a": at, "b": sc.value_of(b, name)}
    return replace(
        first,
        key=key,
        nudge=f"{words}: {sc.shown(values['a'])} to {sc.shown(values['b'])}",
        b=b_spec,
        values=values,
    )


def _one_value(x: Any, y: Any) -> bool:
    """Whether two values of a lever are one: equal, or two figures within the rounding a
    measured figure is kept to (:data:`ROUNDING`; whole numbers are never rounded)."""
    if x == y:
        return True
    if not (_number(x) and _number(y)) or (isinstance(x, int) and isinstance(y, int)):
        return False
    return math.isclose(float(x), float(y), rel_tol=ROUNDING, abs_tol=0.0)


def _same_arm(name: str, x: sc.Row, y: sc.Row) -> bool:
    """Whether two rows of lever ``name`` to play have one arm B: the specs equal apart from
    their names and the lever's own value, and the lever's two values one value
    (:func:`_one_value`)."""
    if x.b is None or y.b is None or x.values is None or y.values is None:
        return False
    blank = {name: None, "name": None}
    return sc.applied(x.b, blank) == sc.applied(y.b, blank) and _one_value(
        x.values["b"], y.values["b"]
    )


def values_of(
    name: str,
    spec: Mapping[str, Any],
    shapes: Sequence[policy.Shape],
    ctx: sc.Context,
) -> list[sc.Row]:
    """Lever ``name``'s values from the current arm ``spec``, as the screen's rows
    (``screen.rows_of``: arm A is the current arm on the cheapest tier that reads the lever, set
    to whatever else makes it read): each of the list's nudges, and after each the nudge again
    (:func:`second_of`). A lever the league does not read is its one row saying why; a nudge
    that cannot be made says why; a nudge that is the current value is not played (a screen
    refuses it; a tune has moved there); a second step that lands on a value already listed is
    not played twice (two figures within a measured figure's rounding are one value: a quarter
    of the season scale taken twice is the half)."""
    firsts = [
        replace(r, status=sc.NOT_PLAYED, why=CURRENT, a=None, b=None)
        if r.status == sc.REFUSED
        else r
        for r in sc.rows_of(spec, [name], shapes, ctx)
    ]
    out: list[sc.Row] = []
    for r in firsts:
        out.append(r)
        if r.status != sc.PLAY:
            continue
        second = second_of(name, spec, r, firsts, shapes, ctx)
        if second is None:
            continue
        if second.status == sc.PLAY:
            twin = next(
                (
                    x
                    for x in (*firsts, *out)
                    if x.status == sc.PLAY and x.key != second.key and _same_arm(name, x, second)
                ),
                None,
            )
            if twin is not None:
                second = replace(
                    second,
                    status=sc.NOT_PLAYED,
                    why=f"the same value as {twin.key}",
                    a=None,
                    b=None,
                )
        out.append(second)
    return out


def pair_key(turn: int, row_key: str) -> str:
    """A played value's name in the tune's folder: its pass and its row's key."""
    return f"p{turn}-{row_key}"


# --------------------------------------------------------------------------- a value's result
def _mark(payload: Mapping[str, Any], season: str, label: str) -> str | None:
    """The mark the replay's own verdict puts on the cell, None when the rule reads it: its
    row's (an oracle's, a yardstick), else its own (a season that fails espn's freeze check, a
    skipped cell)."""
    row = ((payload.get("verdict") or {}).get("rows") or {}).get(label) or {}
    cell = (row.get("cells") or {}).get(season) or {}
    return row.get("mark") if row.get("mark") is not None else cell.get("mark")


def _read(payload: Mapping[str, Any], season: str, label: str) -> bool:
    """Whether the rule reads the cell: not an oracle's row (a yardstick) and not a cell the
    replay's own verdict marks (a season that fails espn's freeze check, a skipped cell)."""
    return _mark(payload, season, label) is None


def _se(xs: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) / math.sqrt(n)


def signs_of(means: Sequence[float | None]) -> str:
    """Where a value's cells stand: every one above zero, every one below, both sides, or
    neither (a cell at zero or without a figure, and no two on opposite sides)."""
    if any(m is not None and m > 0 for m in means) and any(m is not None and m < 0 for m in means):
        return FLIPS
    if means and all(m is not None and m > 0 for m in means):
        return ABOVE
    if means and all(m is not None and m < 0 for m in means):
        return BELOW
    return NO_SIGN


def value_result(
    payload: Mapping[str, Any],
    keys: Sequence[Mapping[str, Any]],
    results: Sequence[Mapping[str, Any]],
    measure: str,
) -> dict[str, Any]:
    """What a played value says, from its pair's record (``payload``, as ``replay`` writes a
    pair) and every task's key and result: the screen's reading of the pair
    (``screen.result_of``: by cell the difference B less A with its SE on every outcome, both
    arms' counts, "did nothing"), each cell marked read or not, and the search's own figures
    (:data:`SEARCH_RULE`): ``mean``, the mean over the cells read of the difference on
    ``measure``; ``se``, over the paths that stand in every cell read, a path's figure the mean
    over those cells; ``signs`` (:func:`signs_of`); and ``clears``, every cell above zero and
    the mean above one SE."""
    standing = [(k, r) for k, r in zip(keys, results, strict=True) if not r.get("breaches")]
    out = sc.result_of(payload, [r for _, r in standing], measure)
    del out["survives"]  # a screen's word: a tune's is ``clears``
    by_cell: dict[str, float | None] = {}
    for t, by_label in out["cells"].items():
        for label, cell in by_label.items():
            cell["read"] = _read(payload, t, label)
            if cell["read"]:
                by_cell[f"{t} {label}"] = cell["difference"][measure]["mean"]
    means = list(by_cell.values())
    mean = sum(means) / len(means) if means and all(m is not None for m in means) else None
    by_path: dict[Any, list[float]] = {}
    for k, r in standing:
        d = r["delta"].get(measure)
        if d is not None and f"{k['season']} {k['forecaster']}" in by_cell:
            by_path.setdefault(k["path"], []).append(float(d))
    whole = [sum(v) / len(v) for v in by_path.values() if len(v) == len(by_cell)]
    se = _se(whole)
    signs = signs_of(means)
    return out | {
        "mean": mean,
        "se": se,
        "whole_paths": len(whole),
        "by_cell": by_cell,
        "signs": signs,
        "clears": signs == ABOVE and mean is not None and se is not None and mean > se,
    }


def _depends(by_cell: Mapping[str, float | None]) -> str:
    """What a value whose cells flip depends on: the season, when one forecaster's cells are on
    both sides of zero between two seasons; the forecaster, when one season's cells are between
    two forecasters; both, when both are so or the cells that disagree share neither."""
    signed = [(*k.split(" ", 1), m > 0) for k, m in by_cell.items() if m]
    pairs = [(x, y) for x in signed for y in signed if x[2] and not y[2]]
    season = any(x[1] == y[1] and x[0] != y[0] for x, y in pairs)
    forecaster = any(x[0] == y[0] and x[1] != y[1] for x, y in pairs)
    if season and not forecaster:
        return DEPENDS_SEASON
    if forecaster and not season:
        return DEPENDS_FORECASTER
    return DEPENDS_BOTH


def standing_of(result: Mapping[str, Any]) -> str:
    """What a played value is, before the step chooses: one of the words above."""
    if result["did_nothing"]:
        return NOTHING
    if not result["by_cell"]:
        return NO_CELL
    if result["signs"] == FLIPS:
        return _depends(result["by_cell"])
    if result["signs"] == BELOW:
        return WORSE
    if result["signs"] == NO_SIGN:
        return FLAT_CELL
    if result["se"] is None:
        return NO_SE
    return BEATEN if result["clears"] else WITHIN


def choose(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A step's choice among a lever's played ``values`` (each its row's record with its
    ``result``, in the lever's order; :data:`SEARCH_RULE`): a value is eligible when it counts
    (every cell above zero) and its mean is above one SE; the eligible value with the largest
    mean is taken (a tie to the first in the lever's order), and none when none is eligible. A
    noisy value does not block a sure one: a value that counts with a larger mean than the one
    taken, and an SE it is not above, is ``passed`` over and named (a value with no SE is not
    passed over for want of one: its standing says it has none). With each value's standing by
    its key, and ``depends`` naming the values whose cells flip when the lever stays."""
    eligible = [v for v in values if v["result"]["clears"] and not v["result"]["did_nothing"]]
    taken = max(eligible, key=lambda v: v["result"]["mean"]) if eligible else None
    passed = [
        v["key"]
        for v in values
        if taken is not None
        and v["result"]["signs"] == ABOVE
        and not v["result"]["clears"]
        and v["result"]["se"] is not None
        and v["result"]["mean"] > taken["result"]["mean"]
    ]
    standings = {}
    for v in values:
        if taken is not None and v["key"] == taken["key"]:
            standings[v["key"]] = TAKEN
        elif v["key"] in passed:
            standings[v["key"]] = PASSED
        else:
            standings[v["key"]] = standing_of(v["result"])
    return {
        "key": None if taken is None else taken["key"],
        "passed": passed,
        "standings": standings,
        "depends": [k for k, s in standings.items() if s in DEPENDS and taken is None],
    }


def measure_words(measure: str) -> str:
    return sc.MEASURE_WORDS.get(measure, measure)


def value_words(result: Mapping[str, Any]) -> str:
    """A played value's figures as the run prints them."""
    words = measure_words(result["measure"])
    cells = len(result["by_cell"])
    mean = "n/a" if result["mean"] is None else f"{result['mean']:+.3f}"
    se = "n/a" if result["se"] is None else f"{result['se']:.3f}"
    out = f"{words} {mean} (SE {se}) over {cells} cell{'s' if cells != 1 else ''}"
    if cells > 1:
        out += (
            " ("
            + ", ".join(
                f"{k} {'n/a' if m is None else f'{m:+.3f}'}" for k, m in result["by_cell"].items()
            )
            + ")"
        )
    if result["voided"]:
        out += f"; {result['voided']} path(s) voided"
    return out


def step_words(step: Mapping[str, Any]) -> str:
    """A step's choice and why, as the run prints it and the record keeps it."""
    played = [v for v in step["values"] if v.get("result") is not None]
    lever, at = step["lever"], sc.shown(step["from"])
    if not played:
        whys = "; ".join(
            f"{v['key']}: {v['status']}" + (f" ({v['why']})" if v.get("why") else "")
            for v in step["values"]
        )
        return f"{lever} stays at {at}: no value to play ({whys})"
    standings = step["choice"]["standings"]
    if step["choice"]["key"] is not None:
        taken = next(v for v in played if v["key"] == step["choice"]["key"])
        out = (
            f"{lever} moves from {at} to {sc.shown(taken['values']['b'])} ({taken['key']}): "
            f"{value_words(taken['result'])}, every cell above zero and the mean above one SE, "
            "the best of the values that clear"
        )
        over = [v for v in played if v["key"] in step["choice"]["passed"]]
        if over:
            out += "; passed over, a larger mean that is not above one SE: " + ", ".join(
                f"{v['key']} ({value_words(v['result'])})" for v in over
            )
        return out
    whys = "; ".join(f"{v['key']}: {standings[v['key']]}" for v in played)
    return f"{lever} stays at {at}: no value counts and clears one SE ({whys})"


# --------------------------------------------------------------------------- the final set
def tier_of(moved: Sequence[str]) -> str:
    """The tier the final set is confirmed on: the cheapest that reads every lever that moved
    (the exact tier when one of them is the exact tier's, else the surrogate)."""
    tiers = {lever.name: lever.tier for lever in sc.LEVERS}
    return "exact" if any(tiers[n] == "exact" for n in moved) else "surrogate"


def unread_of(
    moved: Sequence[str], spec: Mapping[str, Any], shapes: Sequence[policy.Shape]
) -> dict[str, str]:
    """Each lever of ``moved`` that the arm ``spec`` does not read in the run's league
    (``screen.read_why``), with the reason: a value found with something else set in both arms
    that the final arm does not hold, or on another tier."""
    arm = rn.arm_of(spec)
    out = {}
    for name in moved:
        why = sc.read_why(name, arm, shapes)
        if why is not None:
            out[name] = why
    return out


def confirm_arms(
    base: Mapping[str, Any], final: Mapping[str, Any], tier: str, static: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The confirmation's pair: arm A the baseline and arm B the final arm, both on ``tier``;
    with ``static``, both against static rivals instead of the arms' own."""
    more = {"tier": tier, **({"opponents": {"kind": "static"}} if static else {})}
    a = sc.applied(base, more)
    name = rn.arm_of(a).name
    return a, sc.applied(final, {**more, "name": f"{name}:tuned"})


# --------------------------------------------------------------------------- the confirmation
def finish_of(difference: Mapping[str, Mapping[str, Any]]) -> str:
    """A cell's finish on the two outcomes the verdict is stated on, playoff odds (above zero is
    better) and final rank (below zero is better), each against its own SE (:data:`VERDICT_RULE`)."""
    odds, rank = difference["made_playoffs"], difference["rank"]
    if any(d["mean"] is None or d["se"] is None for d in (odds, rank)):
        return UNSURE
    up = odds["mean"] > odds["se"] or -rank["mean"] > rank["se"]
    down = -odds["mean"] > odds["se"] or rank["mean"] > rank["se"]
    if up and down:
        return MIXED
    return AHEAD if up else BEHIND if down else LEVEL


def confirmation_of(payload: Mapping[str, Any], season: int) -> dict[str, Any]:
    """One confirmation pair's cells, by forecaster, from its record: the paired difference on
    every outcome, the paths, both arms' and the rivals' mechanism counts, whether the rule
    reads the cell (``read``; when it does not, ``mark`` is replay's mark on it), and its
    finish."""
    t = str(season)
    out = {}
    for label, cell in (payload["results"].get(t) or {}).items():
        mark = _mark(payload, t, label)
        out[label] = {
            "difference": cell["difference"],
            "paths": cell["paths"],
            "counts": payload["counts"]["by_season"][t][label],
            "read": mark is None,
            "mark": mark,
            "finish": finish_of(cell["difference"]),
        }
    return out


def skipped_of(payload: Mapping[str, Any], season: int) -> dict[str, str]:
    """The forecasters a confirmation pair names that have no cell on ``season``, each with the
    reason ``replay`` gives (its record's ``cells``: a forecaster that cannot serve the season)."""
    by_label = (payload.get("cells") or {}).get(str(season)) or {}
    return {
        label: str(c.get("reason") or "the forecaster cannot serve this season")
        for label, c in by_label.items()
        if not c.get("served")
    }


def searched_of(steps: Sequence[Mapping[str, Any]]) -> list[str]:
    """The forecasters the search read: those with a cell some played value's figures rest on,
    in the order met."""
    out: dict[str, None] = {}
    for step in steps:
        for value in step["values"]:
            for cell in (value.get("result") or {}).get("by_cell") or ():
                out[cell.split(" ", 1)[1]] = None
    return list(out)


def verdict_of(
    cells: Mapping[str, Mapping[str, Mapping[str, Any]]],
    voided: int = 0,
    missing: Mapping[str, str] | None = None,
    one_seat: Sequence[str] = (),
    searched: Sequence[str] = (),
) -> dict[str, Any]:
    """The confirmation's verdict (:data:`VERDICT_RULE`) from its cells by kind of rivals
    (:data:`RUN`, and :data:`STATIC` when the run's rivals are not static) and forecaster:
    ``state`` (:data:`HOLDS`, :data:`NOT_SHOWN`, :data:`AGAINST`; None with ``why`` when the
    audit voided a path, a forecaster the search read has no cell (``missing``, each with the
    reason), a cell the rule reads has no SE or no forecaster is left to read), the finish by
    forecaster and kind, and a flag for each forecaster ahead against one kind of rivals only.
    ``one_seat``: the kinds of rivals against which the final arm is the baseline's seat, whose
    pair was not played (:data:`ONE_SEAT`): ahead against the other kind is ahead against one
    kind only. ``searched``: the forecasters the search read (:func:`searched_of`). One of them
    whose cell here is there and not read (``espn``'s, on a season that fails its freeze check)
    is ``unconfirmed``, with why: the verdict is stated on the forecasters read, and its
    ``words`` say which those are and name each one that went unconfirmed, so "recommended"
    never stands alone. (No cell at all is ``missing``, and no verdict.)"""
    run = cells[RUN]
    missing = dict(missing or {})
    read = [label for label, c in run.items() if c["read"]]
    unconfirmed = {
        label: UNREAD_WHY.get(run[label].get("mark"), UNREAD)
        for label in searched
        if label in run and not run[label]["read"]
    }
    by_forecaster = {
        label: {
            **{kind: cells[kind][label]["finish"] for kind in cells if label in cells[kind]},
            **{kind: ONE_SEAT for kind in one_seat if kind not in cells},
        }
        for label in run
    }
    flags = []
    for label, by_kind in by_forecaster.items():
        if STATIC not in by_kind:
            continue
        ahead = [kind for kind in (RUN, STATIC) if by_kind[kind] == AHEAD]
        if len(ahead) == 1:
            flag = f"{label}: ahead against {RIVALS_WORDS[ahead[0]]} only"
            if ONE_SEAT in by_kind.values():
                other = RUN if ahead[0] == STATIC else STATIC
                flag += f" (against {RIVALS_WORDS[other]} the final arm is the baseline's seat)"
            flags.append(flag)
    state: str | None = None
    why: str | None = None
    unsure = [label for label in read if run[label]["finish"] == UNSURE]
    if voided:
        why = f"no verdict: the audit voided {voided} path(s)"
    elif missing:
        why = (
            "no verdict: the search read "
            + ", ".join(f"{label} ({w})" for label, w in missing.items())
            + ", and the season confirmed on has no cell for it"
        )
    elif not read:
        why = (
            "no verdict: no forecaster the rule may rest on (an oracle is a yardstick, and a "
            "season that fails the freeze check is left out)"
        )
    elif unsure:
        why = f"no verdict: no SE in the cell(s) {', '.join(unsure)} (one path?)"
    elif all(run[label]["finish"] == AHEAD for label in read):
        state = HOLDS
    elif any(run[label]["finish"] == BEHIND for label in read):
        state = AGAINST
    else:
        state = NOT_SHOWN
    words = why if state is None else VERDICT_WORDS[state]
    if unconfirmed:
        others = ", ".join(f"{label} ({w})" for label, w in unconfirmed.items())
        rests = RESTS_ON.get(state, "").format(read=" and ".join(read))
        words = f"{words}; {rests}{UNCONFIRMED.format(others=others)}"
    return {
        "rule": VERDICT_RULE,
        "advisory": ADVISORY,
        "read": read,
        "missing": missing,
        "unconfirmed": unconfirmed,
        "by_forecaster": by_forecaster,
        "flags": flags,
        "state": state,
        "why": why,
        "words": words,
    }


def _figure(d: Mapping[str, Any], scale: float = 1.0, digits: int = 3) -> str:
    if d["mean"] is None:
        return "n/a"
    se = "n/a" if d["se"] is None else f"{scale * d['se']:.{digits}f}"
    return f"{scale * d['mean']:+.{digits}f} ({se})"


def confirmation_lines(conf: Mapping[str, Any], measure: str) -> list[str]:
    """A played confirmation as the run prints it: a row a forecaster and kind of rivals (the
    change in playoff odds in points, in final rank and on the standings' measure, each with its
    SE, and the finish), each named forecaster with no cell and why, a kind of rivals whose pair
    is one seat, the flags, the verdict's line and what a verdict is. The verdict's line
    says which look at the confirmation season it is, when it is one (``conf["look"]``): its
    number for the league kind and its line in the ledger, where every run's look is counted."""
    rows = [
        (
            label + ("" if c["read"] else " [not read]"),
            RIVALS_WORDS[kind],
            _figure(c["difference"]["made_playoffs"], 100.0, 1),
            _figure(c["difference"]["rank"]),
            _figure(c["difference"][measure]),
            c["finish"],
        )
        for kind, by_label in conf["cells"].items()
        for label, c in by_label.items()
    ]
    head = (
        "forecaster",
        "rivals",
        "playoff odds, points (SE)",
        "final rank (SE)",
        f"{measure_words(measure)} (SE)",
        "finish",
    )
    widths = [max(len(head[i]), *(len(r[i]) for r in rows)) for i in range(len(head))]
    out = [
        "  " + "  ".join(f"{x:<{w}}" for x, w in zip(row, widths, strict=True)).rstrip()
        for row in (head, *rows)
    ]
    out.append(
        "  (B less A: the final set less the baseline; a rank below zero is a better finish)"
    )
    out += [
        f"  {label}: no cell on the season confirmed on ({why})"
        for label, why in (conf.get("skipped") or {}).items()
    ]
    out += [
        f"  against {RIVALS_WORDS[kind]}: not played, {ONE_SEAT} (the two arms differ only in "
        f"{'; '.join(names)})"
        for kind, names in (conf.get("one_seat") or {}).items()
    ]
    out += [f"flag: {f}" for f in conf["verdict"]["flags"]]
    look = conf.get("look")
    which = (
        f"; look {look['look']} for this league kind, line {look['line']} of the ledger"
        if look
        else ""
    )
    out.append(f"verdict (advisory{which}): {conf['verdict']['words']}")
    out.append(conf["verdict"]["advisory"])
    return out


# --------------------------------------------------------------------------- the ledger's looks
def own_look(
    lines: Sequence[Mapping[str, Any]], name: str, spec_sha: str, started_at: str
) -> Mapping[str, Any] | None:
    """The ledger's line this tune already wrote, so a tune taken up again after its look is
    counted once; None when it has none. A tune is its name, its spec's hash and when its folder
    was started (its first piece's start): the same command run in a new folder, after the old
    one was removed, reads the season again and is another look."""
    for line in lines:
        if (
            line.get("design") == "tune"
            and line.get("name") == name
            and line.get("spec_sha") == spec_sha
            and line.get("tune_started_at") == started_at
        ):
            return line
    return None


def look_of_kind(lines: Sequence[Mapping[str, Any]], kind_sha: str) -> int:
    """The number a tune's look takes for its league kind: one more than the tunes' lines of
    that kind already in the ledger."""
    return 1 + sum(
        1
        for line in lines
        if line.get("design") == "tune" and line.get("league_kind_sha") == kind_sha
    )


__all__ = [
    "ABOVE",
    "ADVISORY",
    "AGAIN",
    "AGAINST",
    "AHEAD",
    "BEATEN",
    "BEHIND",
    "BELOW",
    "BY_HAND",
    "BY_SCREEN",
    "CARRY_NOTE",
    "CONFIRMED",
    "CURRENT",
    "DEPENDS",
    "DEPENDS_BOTH",
    "DEPENDS_FORECASTER",
    "DEPENDS_SEASON",
    "FLAT_CELL",
    "FLIPS",
    "HOLDS",
    "LEVEL",
    "MIXED",
    "NOTHING",
    "NOTHING_TO_CONFIRM",
    "NOT_SHOWN",
    "NOT_YET",
    "NO_CELL",
    "NO_CONFIRMATION",
    "NO_SE",
    "NO_SIGN",
    "ONE_SEAT",
    "PASSED",
    "PASSES",
    "RESTS_ON",
    "RIVALS_WORDS",
    "ROUNDING",
    "RUN",
    "SAME_SEAT",
    "SEARCH_RULE",
    "SECOND",
    "STATIC",
    "TAKEN",
    "TUNE_VERSION",
    "UNCONFIRMED",
    "UNPLANNED",
    "UNREAD",
    "UNREAD_WHY",
    "UNSCREENED",
    "UNSURE",
    "VERDICT_RULE",
    "VERDICT_WORDS",
    "WITHIN",
    "WORSE",
    "change_of",
    "choose",
    "confirm_arms",
    "confirmation_lines",
    "confirmation_of",
    "finish_of",
    "look_of_kind",
    "measure_words",
    "order_of",
    "order_words",
    "own_look",
    "pair_key",
    "searched_of",
    "second_of",
    "signs_of",
    "skipped_of",
    "standing_of",
    "step_words",
    "strength_of",
    "tier_of",
    "unread_of",
    "value_result",
    "value_words",
    "values_of",
    "verdict_of",
]
