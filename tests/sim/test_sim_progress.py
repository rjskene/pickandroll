"""SEASON SIM (#172, PR live screen): the progress file of the pair in play.

While a screen or a tune plays a pair, its folder keeps a progress file (``readers.PROGRESS_FILE``)
rewritten whole each time one of the pair's tasks comes back, removed once the pair's record is
written, so the lab's Screen tab can show a pair move as its paths are played. It changes nothing
played or recorded: ``run_tasks`` returns its results in the tasks' order with its watch or
without, a pair's record is byte for byte the same with the file written and with the writing
off (on the surrogate tier and the exact), a failed write warns once and the run plays on, and a
pair stopped inside its tasks leaves the file saying so. One small screen is read between its
tasks through the commands: the file is there, its count is right and the lab's view reads it.
"""

from __future__ import annotations

import contextlib
import io
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.lab import records as rd
from pickandroll.sim.lab import server as sv
from tests.sim.sim_league import make_data_dir
from tests.sim.test_sim_screen_run import BASE, small  # noqa: F401 - the league made small

#: The clock every run here is pinned to, so two runs' records can be held byte for byte.
PINNED = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
MEASURE = "matchup_wins"


class Pinned(datetime):
    """``datetime`` with its clock pinned to :data:`PINNED`."""

    @classmethod
    def now(cls, tz=None):
        return PINNED if tz is not None else PINNED.replace(tzinfo=None)


def nap_square(i: int, nap: float) -> int:
    """In a worker: ``i`` squared after a nap, so the results come back out of the tasks' order."""
    time.sleep(nap)
    return i * i


def fails_at_two(i: int) -> int:
    if i == 2:
        raise ValueError("made-up failure")
    return i


def pair_task_fails_at_two(i: int) -> dict[str, Any]:
    """A made-up pair's task: its path's result, and a failure on the third."""
    if i == 2:
        raise ValueError("made-up failure")
    return {"delta": {MEASURE: float(i)}, "breaches": []}


# --------------------------------------------------------------------------- run_tasks' watch
def test_the_watch_sees_each_result_once_and_moves_no_result_or_its_order():
    tasks = [(0, 0.6), (1, 0.0), (2, 0.0), (3, 0.2)]
    seen: list[tuple[int, int]] = []
    got = rn.run_tasks(nap_square, tasks, workers=2, on_done=lambda i, r: seen.append((i, r)))
    assert got == [0, 1, 4, 9] == rn.run_tasks(nap_square, tasks, workers=2)
    assert sorted(seen) == [(0, 0), (1, 1), (2, 4), (3, 9)]
    # One worker: in this process, the watch told after each task in turn.
    seen.clear()
    assert rn.run_tasks(nap_square, tasks, workers=1, on_done=lambda i, r: seen.append((i, r))) == [
        0,
        1,
        4,
        9,
    ]
    assert seen == [(0, 0), (1, 1), (2, 4), (3, 9)]


def test_a_failing_task_still_fails_the_run_and_the_watch_saw_what_came_back():
    seen: list[int] = []
    with pytest.raises(ValueError, match="made-up failure"):
        rn.run_tasks(fails_at_two, [(i,) for i in range(4)], 1, lambda i, r: seen.append(i))
    assert seen == [0, 1]


# --------------------------------------------------------------------------- the watch
@dataclass
class Made:
    """The part of a pair's tasks (``cli.ReplayTasks``) a watch reads."""

    keys: list[dict[str, Any]]
    tasks: list[tuple[Any, ...]]
    slow: int
    task: Any = None


def made(n: int, slow: int = 1) -> Made:
    keys = [{"season": 2024, "forecaster": "prior", "path": p} for p in range(n)]
    return Made(keys, [(p,) for p in range(n)], slow)


def result(d: float | None, voided: bool = False) -> dict[str, Any]:
    return {"delta": {MEASURE: d, "rank": 0}, "breaches": [{"rule": "x"}] if voided else []}


def read(folder: Path) -> dict[str, Any]:
    return json.loads((folder / reader.PROGRESS_FILE).read_text())


def test_the_watch_writes_the_pair_in_play_whole_as_each_task_comes_back(tmp_path):
    w = ss.PairWatch(tmp_path, "k-up", "s", MEASURE)
    w.start(made(4, slow=1), result(1.0))
    got = read(tmp_path)
    assert (got["kind"], got["key"], got["run"], got["measure"]) == (
        "pair progress",
        "k-up",
        "s",
        MEASURE,
    )
    # The timed task is done at the pair's start.
    assert (got["state"], got["tasks"], got["done"]) == ("playing", 4, 1)
    assert got["paths"][0] | {"at": None} == {
        "task": 1,
        "season": 2024,
        "forecaster": "prior",
        "path": 1,
        "at": None,
        "difference": 1.0,
        "voided": False,
    }
    w.done(3, result(-0.5, voided=True))
    w.done(0, result(None))
    got = read(tmp_path)
    assert got["done"] == 3 and [p["task"] for p in got["paths"]] == [1, 3, 0]
    assert [(p["difference"], p["voided"]) for p in got["paths"]] == [
        (1.0, False),
        (-0.5, True),
        (None, False),
    ]
    assert not list(tmp_path.glob("*.partial"))
    w.cut(KeyboardInterrupt())
    got = read(tmp_path)
    assert got["state"] == "cut" and got["why"] == (
        "the pair stopped inside its tasks (KeyboardInterrupt) after 3 of 4 came back; nothing "
        "of it is recorded"
    )
    w.close()
    assert not (tmp_path / reader.PROGRESS_FILE).exists()
    w.close()  # removing it twice is no error


def test_a_failed_write_warns_once_and_the_run_plays_on(tmp_path, capsys):
    blocked = tmp_path / "a-file"
    blocked.write_text("not a folder")
    w = ss.PairWatch(blocked, "k-up", "s", MEASURE)
    w.start(made(3), result(1.0))
    w.done(0, result(0.0))
    w.done(2, {"delta": "not a mapping"})
    w.close()
    out = capsys.readouterr().out
    assert out.count("warning: the progress file in") == 1 and "the run plays on" in out


@dataclass
class Plan:
    started: Any = None


def test_a_pair_stopped_inside_its_tasks_leaves_its_file_saying_so(tmp_path, monkeypatch):
    m = made(4, slow=0)
    m.task = pair_task_fails_at_two
    w = ss.PairWatch(tmp_path, "k-up", "s", MEASURE)
    monkeypatch.setattr(ss, "replay_payload", lambda *a, **k: pytest.fail("no record is made"))
    with pytest.raises(ValueError, match="made-up failure"):
        ss.play_pair(Plan(), m, None, 1, "s-k-up", None, w)
    got = read(tmp_path)
    assert got["state"] == "cut" and got["done"] == 2
    assert got["why"].startswith("the pair stopped inside its tasks (ValueError) after 2 of 4")


# --------------------------------------------------------------------------- through the commands
@pytest.fixture(scope="module")
def roots(tmp_path_factory) -> tuple[Path, Path]:
    """Two data roots alike: the made-up seasons, a made-up frozen fit and the baseline arms."""
    out = []
    for tag in ("watched", "unwatched"):
        folder = make_data_dir(tmp_path_factory.mktemp(tag), wire=120)
        fit = folder / "sim" / "fit" / "2026-01-01"
        fit.mkdir(parents=True)
        made_up = {"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}}
        (fit / "fit.json").write_text(json.dumps(made_up))
        (folder / "B.json").write_text(json.dumps(BASE))
        out.append(folder)
    return out[0], out[1]


def screen(data: Path, lever: str, name: str, paths: str) -> str:
    argv = ["--data", str(data), "--rooms", "0", "screen", "--arm", str(data / "B.json")]
    argv += ["--workers", "1", "--seed", "5", "--paths", paths, "--seasons", "2024"]
    argv += ["--levers", lever, "--name", name]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(argv)
    assert code == 0, buf.getvalue()
    return buf.getvalue()


def pair_bytes(data: Path, name: str) -> dict[str, bytes]:
    """The screen's files, each with its data root's path (a record names its fit's file) said as
    one token, so two roots' records can be held byte for byte."""
    folder = reader.screen_dir(data, name)
    return {
        f.name: f.read_bytes().replace(str(data).encode(), b"<root>")
        for f in sorted(folder.glob("*.json"))
    }


@pytest.mark.parametrize(
    ("lever", "name", "paths"),
    [("weeks_ahead", "surrogate", "4"), ("execute_plan", "exact", "2")],
)
def test_a_screen_keeps_its_pair_in_play_s_progress_and_records_it_as_without(
    roots, monkeypatch, lever, name, paths
):
    watched, unwatched = roots
    monkeypatch.setattr(ss, "datetime", Pinned)
    seen: list[dict[str, Any]] = []
    start, done = ss.PairWatch.start, ss.PairWatch.done

    def look(w: ss.PairWatch) -> None:
        """Between two tasks: the file as it is, and the lab's view of the screen."""
        got = rd.read_progress(w.folder)
        code, v = sv.Lab(watched, now=lambda: PINNED).screen(name)
        so_far = (v.get("in_play") or {}).get("so_far") if code == 200 else None
        seen.append({"file": got, "code": code, "so_far": so_far, "state": v["state"]["state"]})

    def watched_start(self, made, first):
        start(self, made, first)
        look(self)

    def watched_done(self, index, result):
        done(self, index, result)
        look(self)

    monkeypatch.setattr(ss.PairWatch, "start", watched_start)
    monkeypatch.setattr(ss.PairWatch, "done", watched_done)
    screen(watched, lever, name, paths)
    tasks = seen[0]["file"]["tasks"]
    assert tasks >= 2 and len(seen) == tasks
    for k, x in enumerate(seen, start=1):
        assert x["file"]["key"] == seen[0]["file"]["key"] and x["file"]["done"] == k
        assert x["code"] == 200 and x["state"] == "in play"
        assert (x["so_far"]["done"], x["so_far"]["total"]) == (k, tasks)
        assert x["so_far"]["words"] == f"so far, {k} of {tasks} paths"
    # At the end the file is gone, and the screen's records are byte for byte a run's without it.
    folder = reader.screen_dir(watched, name)
    assert not (folder / reader.PROGRESS_FILE).exists()
    # The last look against the pair's own record: every task named once, each with its season,
    # forecaster and path as the record keeps them (the tasks' order: by season, forecaster,
    # then path), and each path's difference that path's B less A on the measure (``by_path``).
    last = seen[-1]["file"]
    pair = json.loads((folder / reader.pair_file(last["key"])).read_text())
    assert pair["audit"]["paths_voided"] == 0
    stood = [
        (int(t), label, row)
        for t, cells in pair["by_path"]["by_season"].items()
        for label, rows in cells.items()
        for row in sorted(rows, key=lambda r: r["path"])
    ]
    assert len(stood) == tasks
    assert sorted(x["task"] for x in last["paths"]) == list(range(tasks))
    for x in last["paths"]:
        t, label, row = stood[x["task"]]
        assert (x["season"], x["forecaster"], x["path"]) == (t, label, row["path"])
        assert x["difference"] == row["b"][MEASURE] - row["a"][MEASURE] and not x["voided"]
    # The timed task is the one named first, at the pair's start.
    assert seen[0]["file"]["paths"][0]["task"] == last["paths"][0]["task"]
    assert not list(folder.glob("*.partial"))
    monkeypatch.setattr(ss, "PROGRESS", False)
    monkeypatch.setattr(ss.PairWatch, "start", lambda *a: pytest.fail("no watch when it is off"))
    screen(unwatched, lever, name, paths)
    mine, theirs = pair_bytes(watched, name), pair_bytes(unwatched, name)
    assert set(mine) == set(theirs) and len(mine) == 2  # the pair's record and the screen's
    (pair,) = set(mine) - {reader.SCREEN_FILE}
    if mine[pair] != theirs[pair]:
        a, b = json.loads(mine[pair]), json.loads(theirs[pair])
        differs = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        pytest.fail(f"the pair's record differs with the progress file written: {differs}")
    # The screen's record: the same but for the timed task's measured seconds in its timing.
    a, b = (json.loads(x[reader.SCREEN_FILE]) for x in (mine, theirs))
    assert {k: v for k, v in a.items() if k != "timing"} == {
        k: v for k, v in b.items() if k != "timing"
    }
    assert a["timing"]["pieces"] == b["timing"]["pieces"]
