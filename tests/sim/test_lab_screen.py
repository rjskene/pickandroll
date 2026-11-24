"""SEASON SIM (#172, PR live screen): the lab's Screen tab, a screen as it is played.

Made-up screen records only, on a clock the tests name: the view's model (``screen_view``) on a
screen in play, between pieces, stopped with a reason, finished, with nothing played, of an
earlier screen version and of no screen at all; the story's order and its marks for pieces and
pauses; the progress estimate at three clocks; the server's route, its last good read and its
refusals; ``lab --check``; the notes' line for the planned pieces; and the tab itself, drawn by
a stub DOM in node.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pickandroll.sim import capabilities as cap
from pickandroll.sim import cli
from pickandroll.sim import readers as reader
from pickandroll.sim import screen as sc
from pickandroll.sim.lab import model as md
from pickandroll.sim.lab import records as rd
from pickandroll.sim.lab import screen_view as scv
from pickandroll.sim.lab import server as sv

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
#: Each pair's estimate: 100 s a task, 12 tasks, on 3 workers: 400 s.
EST = {"seconds_one": 100.0, "tasks": 12}
PAIR_SECONDS = 400.0
KEYS = ("daily_cap-minus", "daily_cap-plus", "rate_cv-minus", "rate_cv-plus")
NOW_VERSION = cap.current().replay_version


def at(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def clock(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def result(mean: float, se: float = 0.2) -> dict:
    return {
        "measure": "matchup_wins",
        "cells": {
            "2023": {
                "prior": {
                    "paths": 12,
                    "clears": abs(mean) > se,
                    "counts": {},
                    "difference": {"matchup_wins": {"mean": mean, "se": se}},
                }
            }
        },
        "survives": abs(mean) > se,
        "did_nothing": False,
        "voided": 0,
        "outcomes_equal": False,
        "counts_equal": False,
        "paths": 12,
    }


def row(key: str, status: str, **more) -> dict:
    lever = key.split("-")[0]
    out = {
        "lever": lever,
        "key": key,
        "nudge": key.split("-")[1],
        "tier": "surrogate",
        "both": {"tier": "surrogate"},
        "values": {"a": 2, "b": 1 if key.endswith("minus") else 3},
        "status": status,
        "why": None,
        "note": None,
    }
    return out | more


def screen_record(
    played: dict[str, float],
    pieces: list[dict],
    *,
    version: int = sc.SCREEN_VERSION,
    replay: int = NOW_VERSION,
) -> dict:
    """A made-up screen of four pairs and one row it does not play: ``played`` maps each landed
    pair to its result's mean; the rest are left in the list's order."""
    rows = []
    for k in KEYS:
        if k in played:
            rows.append(row(k, sc.PLAYED, result=result(played[k]), file=reader.pair_file(k)))
        else:
            rows.append(row(k, sc.LEFT))
    rows.append(
        row(
            "guard-block",
            sc.NOT_PLAYED,
            values=None,
            why="the league's bracket is not read",
        )
    )
    rec = {
        "kind": "screen",
        "name": "s-live",
        "screen_version": version,
        "note": "a made-up screen",
        "spec": {
            "arm": {
                "name": "made-up baseline",
                "tier": "surrogate",
                "knobs": {"daily_cap": 2, "rate_cv": 0.25},
                "opponents": {"kind": "market"},
            },
            "world": {"seasons": [2023], "forecasters": ["prior"], "paths": 12, "seed": 1},
            "levers": ["daily_cap", "rate_cv", "guard"],
            "replay_version": replay,
            "screen_version": version,
            "fit_sha": "f",
        },
        "measure": "matchup_wins",
        "rule": sc.RULE,
        "league": {"label": "a made-up league", "rules": {"scoring": "categories"}},
        "scale": None,
        "rows": rows,
        "survivors": [k for k in played if abs(played[k]) > 0.2],
        "left": [k for k in KEYS if k not in played],
        "timing": {"estimates": dict.fromkeys(KEYS, EST), "pieces": pieces},
        "code_sha": "c",
        "fit_sha": "f",
        "hold_out": 2025,
    }
    if version >= 8:
        rec["resolved"] = {"knobs": {"daily_cap": 2, "rate_cv": 0.25, "miss_rate": 0.07}}
    return rec


def piece(start: float, end: float | None, played: list[str], stopped: str | None = None):
    return {
        "started_at": at(start),
        "finished_at": None if end is None else at(end),
        "played": played,
        "stopped": stopped,
        "workers": 3,
        "code_sha": "c",
    }


def landings(times: dict[str, float]) -> dict[str, dict]:
    return {k: {"started_at": None, "finished_at": at(t)} for k, t in times.items()}


#: A screen in play: two pairs landed at 400 s and 800 s in the open piece, the third in play.
IN_PLAY = screen_record(
    {"daily_cap-minus": 0.5, "daily_cap-plus": -0.1},
    [piece(0, None, ["daily_cap-minus", "daily_cap-plus"])],
)
IN_PLAY_LANDED = landings({"daily_cap-minus": 400, "daily_cap-plus": 800})
#: The same, stopped after the two by its piece's limit, and paused since.
STOPPED = screen_record(
    {"daily_cap-minus": 0.5, "daily_cap-plus": -0.1},
    [piece(0, 810, ["daily_cap-minus", "daily_cap-plus"], "--max-minutes 15: made-up words")],
)
#: Paused, then a second piece open since 3000 s with nothing landed in it yet.
SECOND = screen_record(
    {"daily_cap-minus": 0.5, "daily_cap-plus": -0.1},
    [
        piece(0, 810, ["daily_cap-minus", "daily_cap-plus"], "--max-minutes 15: made-up words"),
        piece(3000, None, []),
    ],
)
#: Finished: the second piece played the last two, landing at 3400 s and 3800 s.
FINISHED = screen_record(
    {"daily_cap-minus": 0.5, "daily_cap-plus": -0.1, "rate_cv-minus": 0.05, "rate_cv-plus": 0.3},
    [
        piece(0, 810, ["daily_cap-minus", "daily_cap-plus"], "--max-minutes 15: made-up words"),
        piece(3000, 3810, ["rate_cv-minus", "rate_cv-plus"]),
    ],
)
FINISHED_LANDED = landings(
    {"daily_cap-minus": 400, "daily_cap-plus": 800, "rate_cv-minus": 3400, "rate_cv-plus": 3800}
)


def marks(v: dict) -> dict[str, str]:
    return {r["key"]: r["mark"] for r in v["rows"]}


# --------------------------------------------------------------------------- the view's model
def test_a_screen_in_play_marks_each_row_and_names_the_pair_in_play():
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000))
    assert v["state"]["state"] == md.IN_PLAY and v["state"]["in_play"] == "rate_cv-minus"
    assert marks(v) == {
        "daily_cap-minus": "played",
        "daily_cap-plus": "played",
        "rate_cv-minus": "in play",
        "rate_cv-plus": "waiting",
        "guard-block": "not played",
    }
    assert v["counts"] == {"played": 2, "left": 2, "not_played": 1, "rows": 5}
    # Grouped by lever in the list's order; the refused row keeps its words.
    assert [g["lever"] for g in v["groups"]] == ["daily_cap", "rate_cv", "guard"]
    refused = next(r for r in v["rows"] if r["key"] == "guard-block")
    assert refused["why"] == "the league's bracket is not read" and refused["result"] is None
    # A played row: its difference, its SE and side, and the record's own "survives".
    better = next(r for r in v["rows"] if r["key"] == "daily_cap-minus")["result"]
    assert better["survives"] and better["cells"][0]["side"] == "better"
    assert better["cells"][0]["clears"] and better["cells"][0]["mean"] == 0.5
    inside = next(r for r in v["rows"] if r["key"] == "daily_cap-plus")["result"]
    assert not inside["survives"] and not inside["cells"][0]["clears"]
    # The pair in play as two arms: the lever at both values, the tier set in both, the rest same.
    arms = next(r for r in v["rows"] if r["key"] == "rate_cv-minus")["arms"]
    assert arms["differ"] == [{"label": "Line's error (spread)", "a": "2", "b": "1"}]
    assert arms["both"] == [{"label": "tier", "value": "surrogate"}]
    assert {x["label"] for x in arms["same"]} == {"Daily add cap", "Missed games (spread)"}
    assert [g["label"] for g in v["groups"]] == [
        "Daily add cap",
        "Line's error (spread)",
        "Season guard",
    ]
    assert v["shown"] == "rate_cv-minus" and v["baseline"]["knobs_from"] == "as played"
    assert v["kept"] is None and v["earlier_engine"] is False


@pytest.mark.parametrize(
    ("seconds", "share", "over", "words"),
    [
        (800, 0.0, False, "about 0% of its estimate"),  # the pair has just begun
        (1000, 0.5, False, "about 50% of its estimate"),  # inside its estimate
        (1300, 1.0, True, "longer than estimated"),  # past it: never over the whole
    ],
)
def test_the_pair_in_play_s_progress_is_an_estimate_at_the_clock_handed_in(
    seconds, share, over, words
):
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(seconds))
    p = v["in_play"]
    assert p["key"] == "rate_cv-minus" and p["since"] == 800
    assert p["estimate"] == PAIR_SECONDS
    assert p["share"] == share and p["over"] is over and p["words"] == words
    assert p["share"] <= 1.0
    # The work left: the two pairs' estimates less what the one in play has used.
    assert v["work_left"] == 2 * PAIR_SECONDS - min(seconds - 800, PAIR_SECONDS)
    assert v["unbroken_end"] == (clock(seconds) + timedelta(seconds=v["work_left"])).isoformat()
    assert scv.ESTIMATE_WORDS in v["cautions"]


def test_the_work_left_at_the_pace_so_far_beside_the_screen_s_own_estimate():
    # The two landed pairs took half again their estimates: 600 s and 600 s against 400 s each.
    slow = landings({"daily_cap-minus": 600, "daily_cap-plus": 1200})
    v = scv.view("s-live", IN_PLAY, slow, clock(1400))
    assert v["in_play"]["since"] == 1200 and v["in_play"]["elapsed"] == 200
    assert v["work_left"] == 2 * PAIR_SECONDS - 200  # the screen's own estimates
    pace = v["pace"]
    assert pace["ratio"] == 1.5 and pace["pairs"] == 2
    assert pace["work_left"] == 1.5 * 2 * PAIR_SECONDS - 200
    assert pace["unbroken_end"] == clock(1400 + pace["work_left"]).isoformat()
    assert pace["words"] == scv.PACE_WORDS and "An estimate too." in pace["words"]
    # Paused: the pace stands, nothing is in play.
    v = scv.view("s-live", STOPPED, slow, clock(2000))
    assert v["pace"]["work_left"] == 1.5 * 2 * PAIR_SECONDS
    # Nothing landed yet, or nothing left: no pace.
    first = screen_record({}, [piece(0, None, [])])
    assert scv.view("s-live", first, {}, clock(100))["pace"] is None
    assert scv.view("s-live", FINISHED, FINISHED_LANDED, clock(9000))["pace"] is None


def test_every_lever_of_the_list_and_an_override_have_the_lab_s_label():
    assert [n for n in sc.NAMES if n not in md.LEVERS] == []
    assert scv.label_of("rate_cv") == "Line's error (spread)"
    assert scv.label_of("rate_cv@standing.behind") == "Line's error (spread) · standing behind"
    assert scv.label_of("not_a_knob") == "not_a_knob"


def test_a_piece_stopped_with_a_reason_leaves_the_screen_paused_between_pieces():
    v = scv.view("s-live", STOPPED, IN_PLAY_LANDED, clock(2000))
    assert v["state"]["state"] == md.PAUSED and v["state"]["in_play"] is None
    assert v["in_play"] is None
    assert marks(v)["rate_cv-minus"] == "waiting"
    assert v["piece_words"] == [
        "piece 1 played 2 pair(s) and stopped: --max-minutes 15: made-up words"
    ]
    s = v["story"]
    # The pause runs from the piece's end to now; a stopped piece leaves no pair in play.
    assert s["pauses"] == [{"from": 810, "to": None}] and s["now"] == 2000 and s["length"] == 2000
    assert [x["key"] for x in s["spans"]] == ["daily_cap-minus", "daily_cap-plus"]
    assert v["work_left"] == 2 * PAIR_SECONDS and v["unbroken_end"] is not None


def test_the_story_orders_pieces_pauses_and_landings_and_the_board_follows_it():
    v = scv.view("s-live", SECOND, IN_PLAY_LANDED, clock(3100))
    assert v["state"]["state"] == md.IN_PLAY and v["in_play"]["since"] == 3000
    s = v["story"]
    assert [(p["from"], p["to"], p["open"]) for p in s["pieces"]] == [
        (0, 810, False),
        (3000, None, True),
    ]
    assert s["pauses"] == [{"from": 810, "to": 3000}]
    assert s["landings"] == [
        {"key": "daily_cap-minus", "t": 400},
        {"key": "daily_cap-plus", "t": 800},
    ]
    assert [(x["key"], x["from"], x["to"], x["landed"]) for x in s["spans"]] == [
        ("daily_cap-minus", 0, 400, True),
        ("daily_cap-plus", 400, 800, True),
        ("rate_cv-minus", 3000, None, False),
    ]
    # The board at moments of the story: in the first piece, in the pause, in the second.
    order = ["daily_cap-minus", "daily_cap-plus", "rate_cv-minus", "rate_cv-plus", "guard-block"]
    seen = {t: [scv.board_at(v, t)[k] for k in order] for t in (100, 600, 2000, 3050)}
    assert seen == {
        100: ["in play", "waiting", "waiting", "waiting", "not played"],
        600: ["played", "in play", "waiting", "waiting", "not played"],
        2000: ["played", "played", "waiting", "waiting", "not played"],
        3050: ["played", "played", "in play", "waiting", "not played"],
    }


def test_a_finished_screen_s_story_runs_to_its_last_end_and_plays_back():
    v = scv.view("s-live", FINISHED, FINISHED_LANDED, clock(9000))
    assert v["state"]["state"] == md.FINISHED and v["in_play"] is None
    assert set(marks(v).values()) == {"played", "not played"}
    s = v["story"]
    assert s["now"] is None and s["length"] == 3810 and s["pauses"] == [{"from": 810, "to": 3000}]
    assert [x["t"] for x in s["landings"]] == [400, 800, 3400, 3800]
    assert v["work_left"] is None and v["unbroken_end"] is None
    assert v["shown"] == "rate_cv-plus"  # the last pair played
    order = [r["key"] for r in v["rows"]]
    assert [scv.board_at(v, 0)[k] for k in order] == [
        "in play",
        "waiting",
        "waiting",
        "waiting",
        "not played",
    ]
    assert [scv.board_at(v, 3810)[k] for k in order] == ["played"] * 4 + ["not played"]


def test_a_screen_with_nothing_played_yet_is_its_list_alone():
    rec = screen_record({}, [])
    v = scv.view("s-live", rec, {}, clock(0))
    assert v["state"]["state"] == md.NOT_STARTED and v["in_play"] is None
    assert set(marks(v).values()) == {"waiting", "not played"}
    assert v["story"]["pieces"] == [] and v["story"]["length"] == 0.0
    assert v["shown"] == "daily_cap-minus"  # the first to play
    # Its first piece open, nothing landed yet: the first pair is in play from the piece's start.
    rec = screen_record({}, [piece(0, None, [])])
    v = scv.view("s-live", rec, {}, clock(100))
    assert marks(v)["daily_cap-minus"] == "in play" and v["in_play"]["since"] == 0


def test_a_piece_that_wrote_no_end_is_said_to_have_stopped_without_it():
    rec = screen_record(
        {"daily_cap-minus": 0.5},
        [piece(0, None, ["daily_cap-minus"]), piece(3000, None, [])],
    )
    v = scv.view("s-live", rec, landings({"daily_cap-minus": 400}), clock(3100))
    assert v["piece_words"][0].startswith("piece 1 stopped without writing its end")
    assert v["story"]["pieces"][0]["unwritten"] and v["story"]["pieces"][0]["to"] == 400
    assert v["state"]["state"] == md.IN_PLAY and v["in_play"]["key"] == "daily_cap-plus"
    assert scv.OUTSIDE_WORDS == v["outside_words"]


def test_an_earlier_screen_version_is_read_and_one_without_its_pieces_is_refused_by_name():
    old = screen_record({"daily_cap-minus": 0.5}, [piece(0, 500, ["daily_cap-minus"])], version=6)
    old["spec"]["replay_version"] = 21
    assert "resolved" not in old and scv.not_a_screen(old) is None
    assert scv.not_a_screen({**old, "timing": {"estimates": {}}}) == (
        "a screen record of version 6 with no pieces under its timing: the view needs when each "
        "piece ran"
    )
    v = scv.view("s-old", old, landings({"daily_cap-minus": 400}), clock(600))
    assert v["screen_version"] == 6 and v["baseline"]["knobs_from"] == "as given"
    assert v["earlier_engine"] is True
    assert any(
        "this screen is not set beside one of the current engine" in c for c in v["cautions"]
    )
    none = dict(old)
    del none["timing"]
    assert scv.not_a_screen(none) == (
        "a screen record of version 6 with no pieces under its timing: the view needs when each "
        "piece ran"
    )
    assert scv.not_a_screen({"kind": "replay"}).startswith("not a screen's record")
    assert scv.not_a_screen({**old, "rows": "x"}).startswith("a screen record of version 6 with")


def test_the_cautions_size_never_judge_and_name_the_world():
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000))
    assert v["cautions"][0] == scv.SIZES_WORDS
    assert v["cautions"][1] == "One season and one seed: 2022-23, seed 1, over 12 paths a pair."
    text = json.dumps(v)
    # The cautions say no lever is called a winner; nothing in the view says one is, or "optimal".
    assert not re.search(r"optimal|\bpunt", text, re.IGNORECASE)
    assert text.count("winner") == text.count("no lever here is called a winner")


def test_the_model_names_each_screen_s_folder_and_state():
    m = md.build(
        [{"folder": "s-live", "record": IN_PLAY, "pairs": {}}],
        [],
        [],
        [],
        None,
        hold_out=2025,
        confirmation=2026,
        generated={"at": "x", "read": {}, "refused": []},
    )
    assert m["lab_version"] == md.LAB_VERSION == 2
    (run,) = m["runs"]
    assert run["folder"] == "s-live"
    assert run["live"] == {
        "state": md.IN_PLAY,
        "in_play": "rate_cv-minus",
        "played": 2,
        "left": 2,
        "pieces": 1,
    }
    assert m["screen_view"]["title"] == "Screen"


# --------------------------------------------------------------------------- the progress file
def progress_file(
    key: str,
    came: list[tuple[float, float | None, bool]],
    *,
    tasks: int = 4,
    at_: float = 0.0,
    state: str = "playing",
    why: str | None = None,
) -> dict:
    """A made-up progress file of the pair ``key``: each path that came back as (its time, its
    difference, voided)."""
    return {
        "kind": "pair progress",
        "progress_version": 1,
        "run": "s-live",
        "key": key,
        "measure": "matchup_wins",
        "state": state,
        "why": why,
        "tasks": tasks,
        "done": len(came),
        "started_at": at(came[0][0]) if came else None,
        "updated_at": at(at_),
        "paths": [
            {
                "task": i,
                "season": 2023,
                "forecaster": "prior",
                "path": i,
                "at": at(t),
                "difference": d,
                "voided": v,
            }
            for i, (t, d, v) in enumerate(came)
        ],
    }


def test_the_pair_in_play_shows_its_paths_so_far_from_the_progress_file():
    prog = progress_file(
        "rate_cv-minus", [(800, 0.5, False), (900, -0.25, False), (950, 1.0, True)], at_=960
    )
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000), progress=prog)
    so = v["in_play"]["so_far"]
    assert (so["done"], so["total"], so["share"]) == (3, 4, 0.75)
    assert [m["side"] for m in so["marks"]] == ["ahead", "behind", "voided"]
    assert [m["t"] for m in so["marks"]] == [800, 900, 950]
    # The mean is of the paths that stand, so far; never set against the screen's rule.
    assert (so["n"], so["mean"]) == (2, 0.125)
    assert so["words"] == "so far, 3 of 4 paths" and so["note"] == scv.SO_FAR_WORDS
    assert "rule reads a whole pair" in so["note"] and so["updated_at"] == at(960)
    # The estimate is still in the view beside it, and the board's marks do not move.
    assert v["in_play"]["words"] == "about 50% of its estimate"
    assert marks(v)["rate_cv-minus"] == "in play" and v["cut"] is None
    span = next(s for s in v["story"]["spans"] if s["key"] == "rate_cv-minus")
    assert span["timed"] and span["total"] == 4 and span["marks"] == so["marks"]
    # Without the file, or with one that is not a progress file: the estimate alone.
    for other in (None, {"kind": "replay"}, {**prog, "tasks": "four"}):
        v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000), progress=other)
        assert v["in_play"]["so_far"] is None and v["cut"] is None


def test_another_pair_s_file_draws_nothing_on_the_pair_in_play_and_is_said_in_words():
    """A piece is open on one pair and the folder's file names another, neither in play nor
    landed (a piece before was stopped inside it): nothing of it is drawn on the pair in play."""
    other = progress_file("rate_cv-plus", [(700, 2.0, False), (750, -2.0, False)], at_=760)
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000), progress=other)
    assert v["state"]["state"] == md.IN_PLAY and v["in_play"]["key"] == "rate_cv-minus"
    open_span = next(s for s in v["story"]["spans"] if s["to"] is None)
    assert open_span["key"] == "rate_cv-minus" and open_span["marks"] is None
    assert all(s["marks"] is None for s in v["story"]["spans"])
    assert v["in_play"]["so_far"] is None
    assert v["in_play"]["words"] == "about 50% of its estimate"  # the estimate, as without a file
    assert v["cut"] == (
        f"rate_cv-plus: its progress file was last written at {at(760)} with 2 of 4 paths back, "
        "and it is not the pair in play now: a piece stopped inside that pair, and nothing of it "
        "is recorded"
    )


@pytest.mark.parametrize(
    ("seconds", "quiet"),
    [(1000, None), (1300, scv.QUIET_WORDS)],  # 40 s, then 340 s, since the last write
)
def test_a_progress_file_gone_quiet_is_said_after_three_paths_time(seconds, quiet):
    """The pair's own path takes ``seconds_one`` (100 s here): the file last written at 960 s is
    quiet past 960 + 3 x 100 s. With no estimate for the pair, nothing is said at any clock."""
    prog = progress_file("rate_cv-minus", [(800, 0.5, False), (960, -0.25, False)], at_=960)
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(seconds), progress=prog)
    assert v["in_play"]["so_far"]["quiet"] == quiet
    assert scv.QUIET_PATHS * EST["seconds_one"] == 300
    no_estimate = json.loads(json.dumps(IN_PLAY))
    del no_estimate["timing"]["estimates"]["rate_cv-minus"]
    v = scv.view("s-live", no_estimate, IN_PLAY_LANDED, clock(9000), progress=prog)
    assert v["in_play"]["so_far"]["done"] == 2 and v["in_play"]["so_far"]["quiet"] is None
    # A file that says the pair was cut is not "quiet": its own words say what happened.
    cut = {**prog, "state": "cut", "why": "made-up words"}
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1300), progress=cut)
    assert v["cut"] == "rate_cv-minus: made-up words" and v["in_play"]["so_far"]["quiet"] is None


def test_a_progress_file_whose_pair_has_landed_is_the_record_s_to_say():
    prog = progress_file("daily_cap-plus", [(500, 1.0, False)], at_=790)
    v = scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000), progress=prog)
    assert v["in_play"]["so_far"] is None and v["cut"] is None


def test_a_pair_stopped_inside_its_tasks_is_said_from_its_progress_file():
    cut = progress_file(
        "rate_cv-minus",
        [(800, 0.5, False)],
        at_=850,
        state="cut",
        why="the pair stopped inside its tasks (KeyboardInterrupt) after 1 of 4 came back",
    )
    v = scv.view("s-live", STOPPED, IN_PLAY_LANDED, clock(2000), progress=cut)
    assert v["cut"] == f"rate_cv-minus: {cut['why']}"
    # Killed outright: the file says playing, last written before its piece stopped.
    stale = progress_file("rate_cv-minus", [(800, 0.5, False)], at_=805)
    v = scv.view("s-live", STOPPED, IN_PLAY_LANDED, clock(2000), progress=stale)
    assert v["cut"] == (
        f"rate_cv-minus: its progress file was last written at {at(805)} with 1 of 4 paths back, "
        "and it is not the pair in play now: a piece stopped inside that pair, and nothing of it "
        "is recorded"
    )
    assert v["in_play"] is None


def test_a_landed_pair_s_paths_replay_evenly_over_its_time_from_its_record():
    both = {
        k: {**x, "paths": [1.0, -1.0, 0.0, None]} if k == "daily_cap-minus" else x
        for k, x in IN_PLAY_LANDED.items()
    }
    v = scv.view("s-live", IN_PLAY, both, clock(1000))
    first = next(s for s in v["story"]["spans"] if s["key"] == "daily_cap-minus")
    assert not first["timed"] and first["total"] == 4
    assert [m["t"] for m in first["marks"]] == [100, 200, 300, 400]
    assert [m["side"] for m in first["marks"]] == ["ahead", "behind", "level", None]
    assert [m["mean"] for m in first["marks"]] == [1.0, 0.0, 0.0, 0.0]
    assert v["spread_words"] == scv.SPREAD_WORDS
    second = next(s for s in v["story"]["spans"] if s["key"] == "daily_cap-plus")
    assert second["marks"] is None  # its record keeps no by_path
    assert scv.view("s-live", IN_PLAY, IN_PLAY_LANDED, clock(1000))["spread_words"] is None


def test_a_pair_s_paths_are_read_from_its_by_path_on_the_measure():
    pair = {
        "by_path": {
            "note": "made-up",
            "by_season": {
                "2023": {
                    "prior": [
                        {"path": 0, "a": {"matchup_wins": 10}, "b": {"matchup_wins": 12}},
                        {"path": 2, "a": {"matchup_wins": 11}, "b": {"matchup_wins": 9.5}},
                        {"path": 3, "a": {"matchup_wins": None}, "b": {"matchup_wins": 9}},
                    ]
                }
            },
        }
    }
    assert scv.paths_of(pair, "matchup_wins") == [2.0, -1.5, None]
    assert scv.paths_of({"by_path": None}, "matchup_wins") is None
    assert scv.paths_of({}, "matchup_wins") is None


def test_the_progress_file_is_read_from_the_folder_or_not_at_all(tmp_path):
    folder = write_screen(tmp_path, "s-live", IN_PLAY, IN_PLAY_LANDED)
    f = folder / reader.PROGRESS_FILE
    assert rd.read_progress(folder) is None
    prog = progress_file("rate_cv-minus", [(800, 0.5, False)], at_=805)
    f.write_text(json.dumps(prog))
    assert rd.read_progress(folder) == prog
    for bad in ('{"kind": "pair pro', json.dumps({"kind": "replay"})):
        f.write_text(bad)
        assert rd.read_progress(folder) is None
    f.unlink()
    elsewhere = tmp_path / "elsewhere.progress"
    elsewhere.write_text(json.dumps(prog))
    f.symlink_to(elsewhere)
    assert rd.read_progress(folder) is None
    # Not a record's name: the lab's model and a tune's resume never take it for one.
    assert not reader.PROGRESS_FILE.endswith(".json")
    f.unlink()
    f.write_text(json.dumps(prog))
    code, v = sv.Lab(tmp_path, now=lambda: clock(1000)).screen("s-live")
    assert code == 200 and v["in_play"]["so_far"]["done"] == 1


# --------------------------------------------------------------------------- the notes' plan line
def test_the_notes_may_name_the_planned_pieces_and_nothing_else_new():
    got = md.notes_of({"state": {"running": None, "text": "t", "pieces": "two pieces tonight"}})
    assert got["state"]["pieces"] == "two pieces tonight"
    with pytest.raises(md.NotesError, match="state.pieces: a non-empty text"):
        md.notes_of({"state": {"text": "t", "pieces": 3}})
    with pytest.raises(md.NotesError, match="an object of running, text and pieces"):
        md.notes_of({"state": {"text": "t", "plan": "x"}})
    with pytest.raises(md.NotesError, match="'screens' is not a section"):
        md.notes_of({"screens": {}})


# --------------------------------------------------------------------------- the reader and the route
def write_screen(data: Path, name: str, rec: dict, landed: dict[str, dict]) -> Path:
    folder = data / reader.SCREENS_DIR / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / reader.SCREEN_FILE).write_text(json.dumps(rec))
    for k, times in landed.items():
        (folder / reader.pair_file(k)).write_text(json.dumps({"kind": "replay", **times}))
    return folder


def test_the_landings_are_read_from_the_pairs_own_records_once_each(tmp_path):
    folder = write_screen(tmp_path, "s-live", IN_PLAY, IN_PLAY_LANDED)
    kept: dict = {}
    got = rd.screen_landings(folder, IN_PLAY, kept)
    # A pair record with no by_path (one written before PR trace) has no paths to replay.
    assert got == {k: {**v, "paths": None} for k, v in IN_PLAY_LANDED.items()} and len(kept) == 2
    # Read once a file: a kept read is used while the file is unchanged.
    f = folder / reader.pair_file("daily_cap-minus")
    path = str(f.resolve())
    kept[path] = (*kept[path][:2], {"started_at": None, "finished_at": "kept"})
    assert rd.screen_landings(folder, IN_PLAY, kept)["daily_cap-minus"]["finished_at"] == "kept"
    # A pair file whose time or size changed is read again (its kept read is not used for ever).
    f.write_text(json.dumps({"kind": "replay", "started_at": None, "finished_at": at(450)}))
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    again = rd.screen_landings(folder, IN_PLAY, kept)
    assert again["daily_cap-minus"]["finished_at"] == at(450)
    assert kept[path][2]["finished_at"] == at(450)
    # A pair file that is not JSON is left out; the rest are read.
    f.write_text("{")
    assert set(rd.screen_landings(folder, IN_PLAY, {})) == {"daily_cap-plus"}


def test_a_half_written_record_while_polling_keeps_the_last_good_read(tmp_path):
    folder = write_screen(tmp_path, "s-live", IN_PLAY, IN_PLAY_LANDED)
    now = [clock(1000)]
    lab = sv.Lab(tmp_path, now=lambda: now[0])
    code, v = lab.screen("s-live")
    assert code == 200 and v["kept"] is None and v["in_play"]["share"] == 0.5
    (folder / reader.SCREEN_FILE).write_text('{"kind": "scr')
    now[0] = clock(1100)
    code, v = lab.screen("s-live")
    assert code == 200 and v["kept"]["at"] == clock(1100).isoformat()
    assert v["kept"]["why"].startswith("its record is not JSON")
    assert v["in_play"]["share"] == 0.75  # the last good read, at the clock now
    # A lab that never read it well refuses it by name; a good write is read again.
    assert sv.Lab(tmp_path, now=lambda: now[0]).screen("s-live")[0] == 422
    (folder / reader.SCREEN_FILE).write_text(json.dumps(STOPPED))
    code, v = lab.screen("s-live")
    assert code == 200 and v["kept"] is None and v["state"]["state"] == md.PAUSED


def test_the_route_reads_only_a_screen_folder_inside_the_data_root(tmp_path):
    write_screen(tmp_path / "data", "s-live", IN_PLAY, IN_PLAY_LANDED)
    outside = tmp_path / "elsewhere"
    write_screen(outside, "s-out", IN_PLAY, {})
    (tmp_path / "data" / reader.SCREENS_DIR / "s-link").symlink_to(
        outside / reader.SCREENS_DIR / "s-out"
    )
    lab = sv.Lab(tmp_path / "data", now=lambda: clock(1000))
    for name in ("..", "../elsewhere", "s-link", "nope", "s live", "a" * 61, ""):
        assert lab.screen(name)[0] == 404, name
    assert lab.screen("s-live")[0] == 200


@contextmanager
def serving(lab: sv.Lab):
    srv = sv.server(lab, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()


def ask(port: int, path: str, method: str = "GET") -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_the_screen_route_answers_get_only_and_refuses_a_name_outside(tmp_path):
    write_screen(tmp_path, "s-live", IN_PLAY, IN_PLAY_LANDED)
    with serving(sv.Lab(tmp_path, now=lambda: clock(1000))) as port:
        code, body = ask(port, "/api/screen/s-live")
        assert code == 200 and json.loads(body)["in_play"]["key"] == "rate_cv-minus"
        for path in ("/api/screen/nope", "/api/screen/..%2F..%2Fx", "/api/screen/%2e%2e"):
            assert ask(port, path)[0] == 404, path
        for method in ("POST", "PUT", "DELETE"):
            assert ask(port, "/api/screen/s-live", method)[0] == 405
        assert ask(port, "/static/screen.js")[0] == 200


def test_lab_check_names_a_screen_in_play(tmp_path, capsys):
    write_screen(tmp_path, "s-live", IN_PLAY, IN_PLAY_LANDED)
    assert cli.main(["--data", str(tmp_path), "lab", "--check"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "live: s-live in play (2 played, 2 left)" in out
    write_screen(tmp_path, "s-live", FINISHED, FINISHED_LANDED)
    assert cli.main(["--data", str(tmp_path), "lab", "--check"]) == 0
    assert "live: no screen in play or paused" in capsys.readouterr().out.splitlines()


# --------------------------------------------------------------------------- the tab
STATIC = sv.STATIC
#: The numbers screen.js may hold: the speeds, the story's seconds at 1x and the pauses' rush, the
#: poll's fifteen seconds and a second's milliseconds, a minute's and an hour's seconds, percent
#: scaling, the clamp on a frame's step, a track mark's least width, and the digits shown.
SCREEN_NUMBERS = {"0", "0.1", "0.4", "1", "2", "3", "6", "10", "15", "40", "60", "100", "1000", "3600"}  # fmt: skip


def css_rule(css: str, selector: str) -> str:
    got = re.findall(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}", css)
    assert len(got) == 1, selector
    return got[0]


def test_every_tab_stays_reachable_and_the_status_text_yields():
    """The lead's look at 1440 wide (PR live screen): the status text squeezed the tabs out of
    sight. The tabs keep their width (a narrow page wraps them, never scrolls them away), and
    the status text yields: it wraps under the tabs, and a line longer than the page is cut with
    its full text on hover."""
    css = (STATIC / "app.css").read_text()
    nav = css_rule(css, "nav")
    assert "flex: 1 1 auto" in nav and "flex-wrap: wrap" in nav and "overflow" not in nav
    state = css_rule(css, ".state")
    assert "min-width: 0" in state and "flex: 0 1 auto" in state
    assert "text-overflow: ellipsis" in css_rule(css, ".state .st")
    assert "flex-wrap: wrap" in css_rule(css, ".top")
    js = (STATIC / "app.js").read_text()
    assert "el.title = text;" in js and '<span class="st">${esc(text)}</span>' in js
    assert 'window.addEventListener("resize", topHeight)' in js


def test_screen_js_holds_no_figure_and_asks_only_for_a_screen():
    js = (STATIC / "screen.js").read_text()
    assert not re.search(r"https?://", js)
    assert re.findall(r'fetch\("([^"]+)"', js) == ["/api/screen/"]
    assert '<script src="/static/screen.js"></script>' in (STATIC / "index.html").read_text()
    js = re.sub(r"^\s*//[^\n]*", "", js, flags=re.MULTILINE)
    js = re.sub(r"\d+px\b", "", js)
    js = re.sub(r"[A-Za-z_$][\w$]*", "x", js)
    found = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?", js))
    assert found <= SCREEN_NUMBERS, sorted(found - SCREEN_NUMBERS)
    assert '["Screen",' in (STATIC / "app.js").read_text()


MARK = "<x-mark>"
#: The view's keys whose values the script reads as names, states or times, never shows as text.
UNMARKED = {"key", "keys", "shown", "side", "updated_at", "name", "folder", "mark", "state", "start", "end", "started_at", "finished_at",
            "at", "now", "unbroken_end", "lever", "kind"}  # fmt: skip


def marked(x, key=""):
    if isinstance(x, dict):
        return {k: marked(v, k) for k, v in x.items()}
    if isinstance(x, list):
        return [marked(v, key) for v in x]
    if isinstance(x, str) and key not in UNMARKED:
        return MARK + x
    return x


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_screen_tab_draws_the_board_plays_the_story_and_polls(tmp_path):
    second = json.loads(json.dumps(SECOND))
    nothing = second["rows"][1]["result"]
    nothing.update(did_nothing=True, survives=False, outcomes_equal=True)
    nothing["cells"]["2023"]["prior"]["difference"]["matchup_wins"] = {"mean": 0.0, "se": 0.0}
    v = marked(json.loads(json.dumps(scv.view("s-live", second, IN_PLAY_LANDED, clock(3100)))))
    landed = {**IN_PLAY_LANDED, **landings({"rate_cv-minus": 3300})}
    nxt_rec = screen_record(
        {"daily_cap-minus": 0.5, "daily_cap-plus": -0.1, "rate_cv-minus": 0.05},
        [
            piece(0, 810, ["daily_cap-minus", "daily_cap-plus"], "made-up"),
            piece(3000, None, ["rate_cv-minus"]),
        ],
    )
    # The next read has the run's progress file: two of the pair in play's four paths back.
    prog = progress_file("rate_cv-plus", [(3350, 1.0, False), (3380, -1.0, False)], at_=3390)
    nxt = scv.view("s-live", nxt_rec, landed, clock(3400), progress=prog)
    nxt = marked(json.loads(json.dumps(nxt)))

    def model(screens):
        m = md.build(
            screens,
            [],
            [],
            [],
            None,
            hold_out=2025,
            confirmation=2026,
            generated={"at": "x", "read": {}, "refused": []},
        )
        return marked(json.loads(json.dumps(m, default=str)))

    files = {}
    for k, x in {
        "model": model([{"folder": "s-live", "record": SECOND, "pairs": {}}]),
        "view": v,
        "next": nxt,
        "empty": model([]),
    }.items():
        files[k] = tmp_path / f"{k}.json"
        files[k].write_text(json.dumps(x))
    harness = Path(__file__).with_name("lab_screen_harness.js")
    got = subprocess.run(
        ["node", str(harness), str(STATIC / "screen.js"), str(STATIC / "app.js"),
         *(str(files[k]) for k in ("model", "view", "next", "empty"))],
        capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    out = json.loads(got.stdout)
    assert out["problems"] == []
    assert out["draw_error"] == ""
    assert out["marks"] == []
    assert out["escaped"] >= 5
    assert out["runs_link"]
    # By itself: the screen in play, read, at now, polled every fifteen seconds.
    assert out["start"] == {
        "loaded": True,
        "live": True,
        "name": "s-live",
        "polling": True,
        "every": [60000, 15000],  # the model's minute, then the screen's fifteen seconds
    }
    assert out["board"] == {"played": 2, "in_play": 1, "waiting": 1, "not_played": 1}
    assert out["pair"] and "In play" in out["clock"] and "(an estimate)" in out["clock"]
    # A pair that did nothing says so alone; one that did something gives its difference.
    assert re.sub(r"<[^>]+>", "", out["rows"]["daily_cap-plus"]).endswith("did nothing")
    assert "±" not in out["rows"]["daily_cap-plus"] and "±" in out["rows"]["daily_cap-minus"]
    # The story from its start and at its end.
    assert out["at_start"] == {"played": 0, "in_play": 1, "waiting": 3, "not_played": 1}
    assert out["at_end"] == out["board"]
    assert out["play"]["after"] > out["play"]["before"] and out["play"]["live"] is False
    assert out["pick"]["drawn"]
    # A poll at now takes the next read: a pair landed, the reader stays at now.
    assert out["poll"]["asked"] == 2 and out["poll"]["live"] is True
    assert out["poll"]["board"] == {"played": 3, "in_play": 1, "waiting": 0, "not_played": 1}
    # The pair in play read from the progress file: its paths so far, one mark each, no estimate.
    row = out["poll"]["rows"]["rate_cv-plus"]
    assert "so far, 2 of 4 paths · mean 0.000 over 2" in row and row.count("<i class=") == 2
    assert 'class="ahead">▲' in row and 'class="behind">▼' in row and "an estimate" not in row
    # A failed poll keeps the last read and says so.
    assert out["failed"]["asked"] == 3 and "the view shows the last read" in out["failed"]["said"]
    assert out["failed"]["board"] == out["poll"]["board"]
    assert out["missing"] and "no screen named" in out["missing"]
    assert "No screen on the box yet" in out["empty"]
