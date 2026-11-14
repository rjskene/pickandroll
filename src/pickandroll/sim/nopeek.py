"""The no-peek check (#172, PR B1): a seat's day must not depend on anything after it.

Two replay worlds that agree on the preseason inputs, the schedule, every line dated before day
``d`` and every absence that begins on or before ``d`` (its start and its end: the return date
told is news already issued) must hand the seats identical days through ``d``, whatever happens
after. :func:`perturb` builds the second world's lines from the first's by a seeded change with
exactly that agreement: every line dated ``d`` or later is redrawn around itself, and past the
games an earlier absence holds fixed some played games are dropped and some missed ones played.
:func:`digest` reduces a :class:`run.DayRecord` to a hash per field, so a whole season's records
compare without being kept, and :func:`first_difference` finds where two runs part. Pure.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import numpy as np

#: The chance a game past the protected ones flips: a played game dropped, a missed one played.
FLIP = 0.15
#: Every stat of a line dated ``d`` or later is scaled by a factor drawn in this range.
SCALE = (0.5, 1.5)
#: The record's fields a digest hashes, in order.
FIELDS = ("beliefs", "status", "returns", "landed", "decisions", "queued", "starters", "state")
#: The record's fields a digest hashes when they are not empty: the other forecasters' beliefs a
#: variant's seats hold and which team holds which (#172, PR D1). A run whose seats all hold the
#: run's forecaster digests as it did before them.
HELD = ("held", "holds")


def _rng(seed: int, player: int, day: date) -> np.random.Generator:
    return np.random.default_rng([int(seed), int(player), day.toordinal()])


def _redrawn(line: Mapping[str, float], g: np.random.Generator) -> dict[str, float]:
    """``line`` with every stat scaled and rounded, makes within attempts, threes within field
    goals, points from the makes when the line has them."""
    out = {s: float(round(float(x) * g.uniform(*SCALE))) for s, x in sorted(line.items())}
    if "fgm" in out and "fga" in out:
        out["fgm"] = min(out["fgm"], out["fga"])
    if "ftm" in out and "fta" in out:
        out["ftm"] = min(out["ftm"], out["fta"])
    if "threes" in out and "fgm" in out:
        out["threes"] = min(out["threes"], out["fgm"])
    if {"pts", "fgm", "ftm"} <= set(out):
        out["pts"] = 2.0 * out["fgm"] + out.get("threes", 0.0) + out["ftm"]
    return out


def protected_through(days: Sequence[date], played: Sequence[bool], day: date) -> int:
    """The number of a player's first game days whose being played or missed is fixed by the
    agreement: those dated ``day`` or earlier, every game of an absence that begins by then and
    the game that ends it."""
    n = sum(1 for d in days if d <= day)
    i = 0
    while i < len(days):
        if played[i]:
            i += 1
            continue
        start = i
        while i < len(days) and not played[i]:
            i += 1
        if start < n:
            n = max(n, min(len(days), i + 1))
    return n


def perturb(
    lines: Mapping[int, Mapping[date, Mapping[str, float]]],
    game_days: Mapping[int, Sequence[date]],
    day: date,
    seed: int,
    flip: float = FLIP,
) -> dict[int, dict[date, dict[str, float]]]:
    """A second season's lines that agree with ``lines`` before ``day`` and on every absence that
    begins by it, and differ after: each line dated ``day`` or later redrawn, and past the
    protected games (:func:`protected_through`) each played game dropped, or missed game played
    (on one of his own lines, redrawn), with chance ``flip``."""
    out: dict[int, dict[date, dict[str, float]]] = {}
    for k, by_day in lines.items():
        days = sorted(game_days.get(k) or by_day)
        played = [d in by_day for d in days]
        keep = protected_through(days, played, day)
        mine = [by_day[d] for d in sorted(by_day)]
        new: dict[date, dict[str, float]] = {}
        for i, d in enumerate(days):
            g = _rng(seed, k, d)
            here = played[i]
            if i >= keep and g.random() < flip and mine:
                here = not here
            if not here:
                continue
            base = by_day[d] if d in by_day else mine[int(g.integers(len(mine)))]
            new[d] = dict(base) if d < day else _redrawn(base, g)
        for d, ln in by_day.items():  # a line off his game days stays as it is
            if d not in new and d not in days:
                new[d] = dict(ln)
        out[k] = new
    return out


def canonical(x: Any) -> Any:
    """A form of ``x`` that compares and hashes alike whatever the order its maps and sets were
    built in."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return (
            type(x).__name__,
            tuple((f.name, canonical(getattr(x, f.name))) for f in dataclasses.fields(x)),
        )
    if isinstance(x, Mapping):
        return (
            "map",
            tuple(sorted(((canonical(k), canonical(v)) for k, v in x.items()), key=repr)),
        )
    if isinstance(x, set | frozenset):
        return ("set", tuple(sorted((canonical(v) for v in x), key=repr)))
    if isinstance(x, list | tuple):
        return tuple(canonical(v) for v in x)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, np.generic):
        return x.item()
    return x


def _hash(x: Any) -> str:
    return hashlib.sha256(repr(canonical(x)).encode()).hexdigest()[:16]


def digest(record: Any) -> dict[str, str]:
    """A hash of each of the record's :data:`FIELDS`, and of each of :data:`HELD` it has and is
    not empty."""
    out = {f: _hash(getattr(record, f)) for f in FIELDS}
    for f in HELD:
        x = getattr(record, f, None)
        if x:
            out[f] = _hash(x)
    return out


def first_difference(
    a: Mapping[tuple[date, int], Mapping[str, str]],
    b: Mapping[tuple[date, int], Mapping[str, str]],
) -> tuple[date, int, tuple[str, ...]] | None:
    """The first (day, variant) whose digests differ, with the fields that differ; a record one
    run has and the other lacks differs in every field."""
    for key in sorted(set(a) | set(b)):
        da, db = a.get(key), b.get(key)
        if da is None or db is None:
            return (key[0], key[1], FIELDS)
        fields = tuple(f for f in (*FIELDS, *HELD) if da.get(f) != db.get(f))
        if fields:
            return (key[0], key[1], fields)
    return None


__all__ = [
    "FIELDS",
    "FLIP",
    "HELD",
    "SCALE",
    "canonical",
    "digest",
    "first_difference",
    "perturb",
    "protected_through",
]
