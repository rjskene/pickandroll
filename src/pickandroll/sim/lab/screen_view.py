"""SEASON SIM (#172, PR live screen): a screen as it is played, for the lab's Screen tab.

Pure: a screen's record (``screen.json``, as the screen command writes it), the times its played
pairs landed and their paths (each pair's own record's ``started_at``, ``finished_at`` and
``by_path``, read by ``records.screen_landings``), the run's progress file when its folder holds
one, the notes' line for the planned pieces and a clock handed in; one dict out (:func:`view`).
Nothing here reads a file or the wall's clock.

What a screen in play leaves on disk: its record is written whole when a piece starts, each time
a pair ends and once more when the piece ends, each played pair's own record whole just before.
Since PR live screen the run also keeps a progress file for the pair in play
(``readers.PROGRESS_FILE``), rewritten whole each time one of its tasks comes back: with it the
pair in play shows its tasks done of the total and one mark a finished path, so far. Without it
(a screen played on code before it) the view has an **estimate** of how far the pair in play has
come: the time since the piece started or the last pair landed, against that pair's estimate
(``seconds_one`` x ``tasks`` / the piece's ``workers``, taken before the first pair), never a
count of paths. The record cannot tell a piece still playing from one stopped from outside before
it wrote its end: past its estimate the pair in play reads "longer than estimated", a piece that
is not the last and wrote no end is said to have stopped without writing it, and a progress file
says when it was last written.

The board, the clock and the pair in play are the record's at the clock handed in; the story
(:func:`story_of`) is the screen's history from its first piece to now (to its last piece's end
when it is finished), as offsets in seconds, so the page can replay it and show the board at any
moment of it. A tune's steps could take the same board; this module reads a screen only.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from .. import capabilities as cap
from .. import screen as sc
from . import model as md

#: A row's mark on the board.
PLAYED, IN_PLAY, WAITING, NOT_PLAYED = "played", "in play", "waiting", "not played"
#: The statuses of a row the screen plays (played, or left for a piece).
TO_PLAY = (sc.PLAYED, sc.LEFT)
#: The line beside the progress of the pair in play.
ESTIMATE_WORDS = (
    "Without the run's progress file (a screen played on code before it), how far the pair in "
    "play has come is an estimate from the screen's own timing (each pair's estimate, taken before "
    "the first pair, against the time since the piece started or the last pair landed), not a "
    "count of paths."
)
#: The line beside the work left.
PIECES_WORDS = (
    "The screen plays in pieces between the box's quiet hours, which its record does not know: "
    "the work left is the pairs' own estimates, not a time of day."
)
#: The cautions the lab gives beside any figure, the screen's first.
SIZES_WORDS = (
    "A screen sizes and never judges: a lever that survives is a candidate for the tune, not a "
    "finding, and no lever here is called a winner."
)
#: The line beside the work left at the pace so far.
PACE_WORDS = (
    "At the pace so far: the pairs landed in this screen took this share of their own estimates, "
    "and the pairs left are taken at the same share. An estimate too."
)
#: The line beside a pair's paths so far, from the run's progress file (PR live screen).
SO_FAR_WORDS = (
    "So far: each path is one mark as it came back (B ahead, behind or level on the measure), "
    "and the mean is of those paths alone. The screen's rule reads a whole pair, so a pair in "
    "play is never set against it."
)
#: The line beside a landed pair's paths in the story: its record keeps no times for them.
SPREAD_WORDS = (
    "A landed pair's paths are drawn evenly over its time: its record keeps each path's outcome "
    "(by_path), not when it came back."
)
#: A path's side by the sign of its difference, B less A.
SIDES = {1: "ahead", -1: "behind", 0: "level"}
OUTSIDE_WORDS = (
    "The record cannot tell a piece still playing from one stopped from outside before it wrote "
    "its end."
)


def when(x: Any) -> datetime | None:
    """A record's time; one written without an offset is read as UTC (the records write theirs
    with one)."""
    if x is None:
        return None
    try:
        t = datetime.fromisoformat(str(x))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.isoformat()


def label_of(name: str) -> str:
    """A lever's or an override's name as the page says it: the lab's label for the knob, and an
    override's situation after it (``rate_cv@standing.behind`` is "Line's error (spread) ·
    standing behind")."""
    knob, _, where = str(name).partition("@")
    label = md.lever_label(knob)
    return f"{label} · {where.replace('.', ' ')}" if where else label


def _int(x: Any, default: int) -> int:
    if isinstance(x, bool) or not isinstance(x, int) or x < 1:
        return default
    return x


def not_a_screen(record: Any) -> str | None:
    """Why a record is not a screen the Screen tab reads; None when it is one. Any screen version
    whose record holds its rows in play order, what is left and its pieces under ``timing`` is
    read (the box's are versions 6 and 8); one without them is refused by name."""
    if not isinstance(record, Mapping) or record.get("kind") != "screen":
        return "not a screen's record (its kind is not screen)"
    v = record.get("screen_version")
    if not isinstance(record.get("rows"), list):
        return f"a screen record of version {v!r} with no rows: the view needs the list in order"
    timing = record.get("timing")
    if not isinstance(timing, Mapping) or not isinstance(timing.get("pieces"), list):
        return (
            f"a screen record of version {v!r} with no pieces under its timing: the view needs "
            "when each piece ran"
        )
    if not isinstance(record.get("left", []), list):
        return f"a screen record of version {v!r} whose left is not a list"
    return None


def _num(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def paths_of(pair: Any, measure: str) -> list[float | None] | None:
    """A landed pair's paths' differences on ``measure``, B less A, from its record's
    ``by_path`` (PR trace; the paths that stand, a voided one left out), by season and
    forecaster in the record's order, then by path; None when the record keeps no ``by_path``
    (one written before it)."""
    block = pair.get("by_path") if isinstance(pair, Mapping) else None
    by = block.get("by_season") if isinstance(block, Mapping) else None
    if not isinstance(by, Mapping):
        return None
    out: list[float | None] = []
    for cells in by.values():
        for rows in (cells or {}).values() if isinstance(cells, Mapping) else ():
            for r in rows or []:
                a = ((r or {}).get("a") or {}).get(measure)
                b = ((r or {}).get("b") or {}).get(measure)
                out.append(float(b) - float(a) if _num(a) and _num(b) else None)
    return out


def progress_ok(x: Any) -> str | None:
    """Why a progress file is not one the view reads; None when it is."""
    if not isinstance(x, Mapping) or x.get("kind") != "pair progress":
        return "not a pair's progress file"
    if not isinstance(x.get("key"), str) or not isinstance(x.get("paths"), list):
        return "a progress file with no key or no paths"
    if isinstance(x.get("tasks"), bool) or not isinstance(x.get("tasks"), int):
        return "a progress file with no count of tasks"
    return None


def marks_of(diffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each path as one mark, in the order given (each ``{"t", "difference", "voided"}``): its
    side (B ahead, behind or level; None with no difference) and, over the paths so far that
    stand with a difference, their count and mean."""
    out, total, n = [], 0.0, 0
    for x in diffs:
        d = x.get("difference")
        voided = bool(x.get("voided"))
        side = None if voided or not _num(d) else SIDES[(d > 0) - (d < 0)]
        if side is not None:
            n += 1
            total += float(d)
        out.append(
            {
                "t": x["t"],
                "difference": float(d) if _num(d) else None,
                "side": "voided" if voided else side,
                "n": n,
                "mean": total / n if n else None,
            }
        )
    return out


def estimate_seconds(record: Mapping[str, Any], key: str, workers: int) -> float | None:
    """The screen's own estimate of pair ``key`` on ``workers`` workers, in seconds
    (``seconds_one`` x ``tasks`` / workers, as the screen sized its pieces); None when the record
    holds none for it."""
    e = ((record.get("timing") or {}).get("estimates") or {}).get(key)
    if not isinstance(e, Mapping):
        return None
    one, tasks = e.get("seconds_one"), e.get("tasks")
    if isinstance(one, bool) or not isinstance(one, int | float) or not math.isfinite(one):
        return None
    if isinstance(tasks, bool) or not isinstance(tasks, int):
        return None
    return float(one) * tasks / max(1, workers)


def pieces_of(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The screen's pieces in order: when each started and ended, its workers, the pairs it
    played and why it stopped. The last piece with no end is open; an earlier one with no end
    stopped from outside before it wrote its end (``unwritten``)."""
    raw = (record.get("timing") or {}).get("pieces") or []
    out = []
    for i, p in enumerate(raw):
        start, end = when(p.get("started_at")), when(p.get("finished_at"))
        out.append(
            {
                "index": i,
                "started": start,
                "finished": end,
                "open": end is None and i == len(raw) - 1,
                "unwritten": end is None and i < len(raw) - 1,
                "workers": _int(p.get("workers"), 1),
                "played": [str(k) for k in p.get("played") or []],
                "stopped": None if p.get("stopped") is None else str(p.get("stopped")),
            }
        )
    return out


def _order(record: Mapping[str, Any]) -> list[str]:
    """The pairs the screen plays, in the order it plays them (the list's)."""
    return [str(r.get("key")) for r in record.get("rows") or [] if r.get("status") in TO_PLAY]


def story_of(
    record: Mapping[str, Any],
    landed: Mapping[str, Mapping[str, Any]],
    now: datetime,
    progress: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The screen's history as offsets in seconds from its first piece's start: each piece (open
    to now while it is open), the pauses between pieces (and the pause now, when the screen is
    paused), each pair's landing, and the spans in which each pair was in play (from the piece's
    start or the last landing to its own, the last of an open piece to now), each with its
    estimate. ``length`` runs to now unless the screen is finished, then to its last end.

    Each span carries its paths as marks when they are known (PR live screen): a landed pair's
    from its record's ``by_path``, drawn evenly over its span (``timed`` false: the record keeps
    no times), and the pair in play's from ``progress``, the run's progress file, each at the
    time it came back (``timed`` true), with ``total`` the pair's tasks."""
    pieces = pieces_of(record)
    state = md.live_state(record)["state"]
    if not pieces or pieces[0]["started"] is None:
        return {
            "start": None,
            "end": None,
            "length": 0.0,
            "now": None,
            "pieces": [],
            "pauses": [],
            "spans": [],
            "landings": [],
        }
    start = pieces[0]["started"]

    def off(t: datetime) -> float:
        return max(0.0, (t - start).total_seconds())

    order = _order(record)
    land = {k: when((landed.get(k) or {}).get("finished_at")) for k in order}
    out_pieces, spans, pauses = [], [], []
    ends: list[datetime] = []
    for p in pieces:
        s = p["started"] or (ends[-1] if ends else start)
        mine = sorted(
            ((land.get(k), k) for k in p["played"] if land.get(k) is not None),
            key=lambda x: x[0],
        )
        cursor = s
        landed_here = {k for _, k in mine}
        for t, k in mine:
            span = {
                "key": k,
                "from": off(cursor),
                "to": off(t),
                "landed": True,
                "piece": p["index"],
                "estimate": estimate_seconds(record, k, p["workers"]),
                "marks": None,
                "total": None,
                "timed": False,
            }
            diffs = (landed.get(k) or {}).get("paths")
            if isinstance(diffs, list) and diffs:
                width = (span["to"] - span["from"]) / len(diffs)
                span["marks"] = marks_of(
                    [
                        {"t": span["from"] + (i + 1) * width, "difference": d}
                        for i, d in enumerate(diffs)
                    ]
                )
                span["total"] = len(diffs)
            spans.append(span)
            cursor = t
        if p["open"]:
            end = max(now, cursor)
        elif p["finished"] is not None:
            end = max(p["finished"], cursor)
        else:
            end = cursor
        # The pair after the last landing, in play until the piece's end (an open piece's until
        # now); a piece that ends between pairs, or stops before its next pair, leaves none.
        after = [
            k for k in order if k not in landed_here and (land.get(k) is None or land[k] > cursor)
        ]
        if after and (p["open"] or (end > cursor and not p["stopped"])):
            span = {
                "key": after[0],
                "from": off(cursor),
                "to": None if p["open"] else off(end),
                "landed": False,
                "piece": p["index"],
                "estimate": estimate_seconds(record, after[0], p["workers"]),
                "marks": None,
                "total": None,
                "timed": True,
            }
            if p["open"] and progress is not None and progress.get("key") == after[0]:
                came = sorted(
                    (
                        (when(x.get("at")) or s, x)
                        for x in progress.get("paths") or []
                        if isinstance(x, Mapping)
                    ),
                    key=lambda tx: tx[0],
                )
                span["marks"] = marks_of(
                    [
                        {
                            "t": max(span["from"], off(t)),
                            "difference": x.get("difference"),
                            "voided": x.get("voided"),
                        }
                        for t, x in came
                    ]
                )
                span["total"] = progress.get("tasks")
            spans.append(span)
        out_pieces.append(
            {
                "index": p["index"],
                "from": off(s),
                "to": None if p["open"] else off(end),
                "open": p["open"],
                "unwritten": p["unwritten"],
                "workers": p["workers"],
                "played": len(p["played"]),
                "stopped": p["stopped"],
                "started_at": _iso(p["started"]),
                "finished_at": _iso(p["finished"]),
            }
        )
        if ends and s > ends[-1]:
            pauses.append({"from": off(ends[-1]), "to": off(s)})
        ends.append(end)
    last = ends[-1]
    if state == md.PAUSED and now > last:
        pauses.append({"from": off(last), "to": None})
    finished = state == md.FINISHED
    stop = last if finished else max(now, last)
    landings = sorted(
        ({"key": k, "t": off(t)} for k, t in land.items() if t is not None), key=lambda x: x["t"]
    )
    return {
        "start": _iso(start),
        "end": _iso(stop),
        "length": off(stop),
        "now": None if finished else off(max(now, start)),
        "pieces": out_pieces,
        "pauses": pauses,
        "spans": spans,
        "landings": landings,
    }


def _result(row: Mapping[str, Any], measure: str) -> dict[str, Any] | None:
    """A played row's result as the board marks it: each cell's difference on the measure (B
    less A, its SE, its ratio and side), and the record's own "survives", "did nothing" and
    voided paths."""
    result = row.get("result")
    if not isinstance(result, Mapping):
        return None
    m = str(result.get("measure") or measure)
    cells = []
    for t, by_label in (result.get("cells") or {}).items():
        for label, c in (by_label or {}).items():
            d = md.diff_of((c or {}).get("difference"), m) if m in md.OUTCOMES else {}
            cells.append({"cell": f"{t} {label}", "paths": (c or {}).get("paths")} | d)
    try:
        words = sc.result_words(result)
    except (KeyError, TypeError, ValueError):
        words = None
    return {
        "cells": cells,
        "survives": bool(result.get("survives")),
        "did_nothing": bool(result.get("did_nothing")),
        "voided": int(result.get("voided") or 0),
        "words": words,
    }


def _arms(
    row: Mapping[str, Any], base: Mapping[str, Any], spec: Mapping[str, Any]
) -> dict[str, Any]:
    """A row's two arms: what differs (the lever, or its override, at the row's two values),
    what is set in both (``both``, its tier among them) and the baseline's other knobs, the same
    in both arms."""
    values = row.get("values") or None
    name = str(row.get("override") or row.get("lever") or "")
    both = {str(k): sc.shown(v) for k, v in (row.get("both") or {}).items()}
    differ = (
        [{"label": name, "a": sc.shown(values.get("a")), "b": sc.shown(values.get("b"))}]
        if isinstance(values, Mapping) and values
        else []
    )
    same = [
        {"label": label_of(str(k)), "a": sc.shown(v), "b": sc.shown(v)}
        for k, v in base.items()
        if k != name and k not in both
    ]
    arm = spec.get("arm") or {}
    return {
        "differ": [x | {"label": label_of(x["label"])} for x in differ],
        "both": [{"label": k, "value": v} for k, v in both.items()],
        "same": same,
        "tier": row.get("tier"),
        "names": {
            "a": "the baseline",
            "b": f"{label_of(name)} nudged" if differ else "the baseline",
        },
        "opponents": sc.shown((arm.get("opponents") or {}).get("kind")),
    }


def _mark(row: Mapping[str, Any], in_play: str | None) -> str:
    if row.get("result"):
        return PLAYED
    if str(row.get("key")) == in_play:
        return IN_PLAY
    if row.get("status") in TO_PLAY:
        return WAITING
    return NOT_PLAYED


def so_far_of(
    span: Mapping[str, Any] | None, progress: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """The pair in play's paths so far, from the run's progress file: tasks done of the total
    (the bar), each path's mark, and the count and mean of those that stand, worded "so far, n
    of N paths"; None without a progress file for it (the view falls back to the estimate)."""
    if span is None or progress is None or progress.get("key") != span.get("key"):
        return None
    marks = span.get("marks") or []
    total = int(progress.get("tasks") or 0)
    done = len(marks)
    last = marks[-1] if marks else {"n": 0, "mean": None}
    return {
        "done": done,
        "total": total,
        "share": min(1.0, done / total) if total else None,
        "n": last["n"],
        "mean": last["mean"],
        "marks": marks,
        "updated_at": progress.get("updated_at"),
        "words": f"so far, {done} of {total} paths",
        "note": SO_FAR_WORDS,
    }


def cut_words(progress: Mapping[str, Any] | None, in_play: str | None, state: str) -> str | None:
    """What a progress file says of a pair stopped inside its tasks: its own words when the run
    said so, or, when the file's pair is not the one in play now and not landed (its piece is no
    longer open), that it was stopped inside that pair; nothing of it is recorded."""
    if progress is None:
        return None
    done, total = len(progress.get("paths") or []), progress.get("tasks")
    if progress.get("state") == "cut":
        return f"{progress.get('key')}: {progress.get('why')}"
    if state != md.IN_PLAY or progress.get("key") != in_play:
        return (
            f"{progress.get('key')}: its progress file was last written at "
            f"{progress.get('updated_at')} with {done} of {total} paths back, and no piece is "
            "playing it now: the piece stopped inside that pair, and nothing of it is recorded"
        )
    return None


def progress_of(span: Mapping[str, Any] | None, story: Mapping[str, Any]) -> dict[str, Any] | None:
    """How far the pair in play has come at the story's now, by its open span: the seconds since
    the span began against its estimate, the share never above 1; past the estimate "longer than
    estimated". None when no pair is in play."""
    if span is None or story.get("now") is None:
        return None
    elapsed = max(0.0, story["now"] - span["from"])
    est = span.get("estimate")
    if est is None or est <= 0:
        return {
            "elapsed": elapsed,
            "estimate": None,
            "share": None,
            "over": False,
            "words": "no estimate in the record for this pair",
        }
    over = elapsed > est
    share = min(1.0, elapsed / est)
    return {
        "elapsed": elapsed,
        "estimate": est,
        "share": share,
        "over": over,
        "words": "longer than estimated"
        if over
        else f"about {math.floor(100 * share)}% of its estimate",
    }


def view(
    name: str,
    record: Mapping[str, Any],
    landed: Mapping[str, Mapping[str, Any]],
    now: datetime,
    plan: str | None = None,
    progress: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The Screen tab's view of the screen ``name`` at ``now``: its state and clock, the board
    (every row in play order, grouped by lever, each marked played, in play, waiting or not
    played), the pair in play as two arms (else the next to play, or the last played), the
    story, the work left by the screen's own estimates, the notes' ``plan`` for the pieces, and
    the cautions. ``landed``: each played pair's ``started_at`` and ``finished_at`` by key, as
    ``records.screen_landings`` reads them; ``progress``: the run's progress file, when its folder
    holds one (``records.read_progress``)."""
    spec = record.get("spec") or {}
    world = spec.get("world") or {}
    measure = str(record.get("measure") or "matchup_wins")
    live = md.live_state(record)
    in_play = live["in_play"]
    played_keys = {
        str(r.get("key"))
        for r in record.get("rows") or []
        if isinstance(r, Mapping) and r.get("result")
    }
    if progress is not None and (progress_ok(progress) or str(progress.get("key")) in played_keys):
        # Not a progress file, or one whose pair has landed (its record is written and the file
        # not yet removed): the record is the pair's word.
        progress = None
    story = story_of(record, landed, now, progress if live["state"] == md.IN_PLAY else None)
    pieces = pieces_of(record)
    open_span = next(
        (s for s in story["spans"] if s["to"] is None and not s["landed"]),
        None,
    )
    if open_span is not None and in_play is not None and open_span["key"] != in_play:
        # The record's left and the landings disagree (a pair landed after the record was read):
        # the record's left is the one the board shows.
        open_span = {**open_span, "key": in_play}
    resolved = (record.get("resolved") or {}).get("knobs")
    base = (
        dict(resolved)
        if isinstance(resolved, Mapping)
        else dict((spec.get("arm") or {}).get("knobs") or {})
    )
    groups: list[dict[str, Any]] = []
    by_lever: dict[str, dict[str, Any]] = {}
    rows = []
    landed_at = {x["key"]: x["t"] for x in story["landings"]}
    for row in record.get("rows") or []:
        key, lever = str(row.get("key")), str(row.get("lever"))
        values = row.get("values")
        out = {
            "key": key,
            "lever": lever,
            "label": label_of(lever),
            "override": row.get("override"),
            "override_label": None if not row.get("override") else label_of(row["override"]),
            "nudge": row.get("nudge"),
            "values": None
            if not values
            else {"a": sc.shown(values.get("a")), "b": sc.shown(values.get("b"))},
            "tier": row.get("tier"),
            "status": row.get("status"),
            "why": row.get("why"),
            "mark": _mark(row, in_play),
            "landed": landed_at.get(key),
            "result": _result(row, measure),
            "arms": _arms(row, base, spec),
        }
        rows.append(out)
        g = by_lever.get(lever)
        if g is None:
            g = by_lever[lever] = {"lever": lever, "label": out["label"], "keys": []}
            groups.append(g)
        g["keys"].append(key)
    order = _order(record)
    left = [str(k) for k in record.get("left") or []]
    shown = in_play or (left[0] if left else (order[-1] if order else None))
    workers = pieces[-1]["workers"] if pieces else 1
    prog = progress_of(open_span, story)
    so_far = so_far_of(open_span, progress)
    cut = cut_words(progress, in_play, live["state"])
    work = [estimate_seconds(record, k, workers) for k in left]
    known = [w for w in work if w is not None]
    work_left = None
    if known:
        work_left = sum(known)
        if prog is not None and prog["estimate"] is not None:
            work_left -= min(prog["elapsed"], prog["estimate"])
        work_left = max(0.0, work_left)
    unbroken = (
        None
        if work_left is None or live["state"] not in (md.IN_PLAY, md.PAUSED)
        else _iso(now + timedelta(seconds=work_left))
    )
    pace = pace_of(story, left, record, workers, prog, now, live["state"])
    capability = md.capability_of(spec.get("replay_version"))
    now_cap = cap.current()
    earlier = (
        capability is not None
        and now_cap is not None
        and capability["replay_version"] != now_cap.replay_version
    )
    seasons = [md.season_words(t) for t in md._seasons(world.get("seasons"))]
    cautions = [
        SIZES_WORDS,
        (
            f"One season and one seed: {', '.join(seasons) or 'no season recorded'}, seed "
            f"{world.get('seed')}, over {world.get('paths')} paths a pair."
        ),
        f"Played on {md.cap_words(capability)}"
        + (
            f"; the simulator is now on version {now_cap.replay_version} ({now_cap.title}), so "
            "this screen is not set beside one of the current engine without saying so."
            if earlier and now_cap is not None
            else "."
        ),
        ESTIMATE_WORDS,
    ]
    piece_words = []
    for p in story["pieces"]:
        if p["open"]:
            w = f"piece {p['index'] + 1} is open: {p['played']} pair(s) landed in it so far"
        elif p["unwritten"]:
            w = (
                f"piece {p['index'] + 1} stopped without writing its end, after {p['played']} "
                "pair(s): the record cannot say when or why"
            )
        else:
            w = f"piece {p['index'] + 1} played {p['played']} pair(s)" + (
                f" and stopped: {p['stopped']}" if p["stopped"] else ""
            )
        piece_words.append(w)
    state_words = {
        md.IN_PLAY: "in play: a piece is open",
        md.PAUSED: "paused between pieces: no piece is open and pairs are left",
        md.FINISHED: "finished: every pair is played",
        md.NOT_STARTED: "not started: no piece has run",
    }[live["state"]]
    return {
        "name": name,
        "screen_version": record.get("screen_version"),
        "replay_version": spec.get("replay_version"),
        "capability": capability,
        "earlier_engine": earlier,
        "measure": measure,
        "measure_label": md.OUTCOMES.get(measure, {}).get("label", measure),
        "rule": record.get("rule"),
        "league": (record.get("league") or {}).get("label"),
        "world": {
            "seasons": seasons,
            "forecasters": md._words(world.get("forecasters")),
            "paths": world.get("paths"),
            "seed": world.get("seed"),
        },
        "baseline": {
            "name": (spec.get("arm") or {}).get("name"),
            "tier": (spec.get("arm") or {}).get("tier"),
            "knobs_from": "as played" if isinstance(resolved, Mapping) else "as given",
        },
        "state": live | {"words": state_words},
        "counts": {
            "played": live["played"],
            "left": len(left),
            "not_played": sum(1 for r in rows if r["mark"] == NOT_PLAYED),
            "rows": len(rows),
        },
        "in_play": None
        if in_play is None
        else {"key": in_play, "since": None if open_span is None else open_span["from"]}
        | ({} if prog is None else prog)
        | {"so_far": so_far},
        "cut": cut,
        "spread_words": SPREAD_WORDS
        if any(s["marks"] and not s["timed"] for s in story["spans"])
        else None,
        "shown": shown,
        "work_left": work_left,
        "unbroken_end": unbroken,
        "unknown_estimates": len(work) - len(known),
        "pace": pace,
        "plan": plan,
        "pieces_words": PIECES_WORDS,
        "piece_words": piece_words,
        "outside_words": OUTSIDE_WORDS,
        "groups": groups,
        "rows": rows,
        "story": story,
        "cautions": cautions,
        "now": _iso(now),
        "kept": None,
    }


def pace_of(
    story: Mapping[str, Any],
    left: list[str],
    record: Mapping[str, Any],
    workers: int,
    prog: Mapping[str, Any] | None,
    now: datetime,
    state: str,
) -> dict[str, Any] | None:
    """The work left at the pace so far: the pairs landed in the screen took ``ratio`` of their
    own estimates (their spans' time over their estimates, each pair with an estimate), and the
    pairs left are taken at that ratio, less the time the pair in play has had. None until a pair
    has landed, or when no pair is left."""
    done = [
        s
        for s in story["spans"]
        if s["landed"] and s["to"] is not None and s.get("estimate") and s["estimate"] > 0
    ]
    if not done or not left or state not in (md.IN_PLAY, md.PAUSED):
        return None
    ratio = sum(s["to"] - s["from"] for s in done) / sum(s["estimate"] for s in done)
    ests = [estimate_seconds(record, k, workers) for k in left]
    known = [e * ratio for e in ests if e is not None]
    if not known:
        return None
    work = sum(known)
    if prog is not None and prog.get("estimate"):
        work -= min(prog["elapsed"], prog["estimate"] * ratio)
    work = max(0.0, work)
    return {
        "ratio": ratio,
        "pairs": len(done),
        "work_left": work,
        "unbroken_end": _iso(now + timedelta(seconds=work)),
        "words": PACE_WORDS,
    }


def board_at(v: Mapping[str, Any], t: float) -> dict[str, str]:
    """Each row's mark at offset ``t`` of the story (what the page draws while it replays it):
    played once its pair has landed, in play inside one of its spans, waiting while it is still to
    play, and not played throughout for a row the screen does not play."""
    marks = {}
    spans = v["story"]["spans"]
    length = v["story"]["length"]
    for r in v["rows"]:
        if r["mark"] == NOT_PLAYED:
            marks[r["key"]] = NOT_PLAYED
        elif r["landed"] is not None and r["landed"] <= t:
            marks[r["key"]] = PLAYED
        elif any(
            s["key"] == r["key"]
            and s["from"] <= t
            and (t <= length if s["to"] is None else t < s["to"])
            for s in spans
        ):
            marks[r["key"]] = IN_PLAY
        else:
            marks[r["key"]] = WAITING
    return marks


__all__ = [
    "ESTIMATE_WORDS",
    "IN_PLAY",
    "NOT_PLAYED",
    "OUTSIDE_WORDS",
    "PACE_WORDS",
    "PIECES_WORDS",
    "PLAYED",
    "SIZES_WORDS",
    "WAITING",
    "board_at",
    "cut_words",
    "estimate_seconds",
    "label_of",
    "marks_of",
    "not_a_screen",
    "pace_of",
    "paths_of",
    "pieces_of",
    "progress_of",
    "progress_ok",
    "so_far_of",
    "story_of",
    "view",
    "when",
]
