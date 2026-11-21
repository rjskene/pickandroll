"""A run's live progress file (FLOOR PR 2, #459): written when the run starts and after each step,
removed on every exit path, never on a dry run, a failed write never stopping the run, and the
run log and the daily marker as before, byte for byte. Nothing here opens a page."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from pickandroll.routine import Report, run
from pickandroll.routine.report import Live, live_path, marker, progress

from .test_routine import SCRIPT, Clock, FakeAPI, base_answers, make_ctx

#: The names the seven hooked steps announce (the master's ruling on #459, option B): their
#: own, and a browser pass's by its pass.
HOOKED = {
    "exports",
    "refresh",
    "solve",
    "browser_pass",
    "queue_build",
    "post",
    "resolve_comebacks",
    "start_active",
    "lineup",
    "moves",
    "comebacks",
    "il",
}


class Recording(Live):
    """A live file that keeps a copy of each write's content, to look at the run mid-way."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.seen: list[dict] = []

    def write(self, report) -> None:
        super().write(report)
        self.seen.append(json.loads(self.path.read_text()))


def daily(tmp_path, live: Live | None):
    ctx = make_ctx(FakeAPI(base_answers()), Clock("2026-10-29 05:01"), tmp_path)
    ctx.report.live = live
    return run("daily", ctx, "http://api")


def test_the_file_mid_run_names_the_routine_its_start_and_the_steps_so_far(tmp_path):
    live = Recording(live_path(tmp_path, "daily"))
    report = daily(tmp_path, live)
    first, *rest = live.seen
    # The first write, past the window check: no step yet, under way since the run's start.
    assert first["routine"] == "daily" and first["steps"] == []
    assert first["started_at"] == report.started.isoformat()
    assert first["current"] == {"name": None, "after": None, "started": first["started_at"]}
    # One write after each step, its steps the run log's own so far, and none named between.
    after = [x for x in rest if x["current"]["name"] is None]
    assert len(after) == len(report.steps)
    for n, seen in enumerate(after, 1):
        assert seen["steps"] == [s.to_dict() for s in report.steps[:n]]
        last = report.steps[n - 1]
        assert seen["current"] == {"name": None, "after": last.name, "started": last.finished}
    # A long step names itself while under way, and only the seven hooked ones do.
    named = [x["current"]["name"] for x in rest if x["current"]["name"] is not None]
    assert set(named) <= HOOKED
    assert {"exports", "refresh", "solve", "queue_build", "post"} <= set(named)
    # Named while under way: that run of the step is not yet among the steps written.
    for x in rest:
        if (step := x["current"]["name"]) is not None:
            done = sum(1 for s in x["steps"] if s["name"] == step)
            assert done < sum(1 for s in report.steps if s.name == step)


def test_a_step_that_says_it_began_is_named_until_it_finishes(tmp_path):
    clock = Clock("2026-10-29 05:01")
    ctx = make_ctx(FakeAPI(base_answers()), clock, tmp_path)
    report = ctx.report
    report.live = Live(live_path(tmp_path, "daily"))
    report.start_live()
    report.ok("api", "200")
    clock.advance(30)
    report.begin("refresh")
    body = json.loads(report.live.path.read_text())
    assert body["current"] == {
        "name": "refresh",
        "after": "api",
        "started": clock().isoformat(),
    }
    clock.advance(30)
    report.ok("refresh", "done")
    assert json.loads(report.live.path.read_text())["current"]["name"] is None
    assert progress(report)["written_at"] == clock().isoformat()


def test_a_begin_with_no_finish_is_cleared_by_the_next_finish(tmp_path):
    clock = Clock("2026-10-29 05:01")
    report = make_ctx(FakeAPI(base_answers()), clock, tmp_path).report
    report.live = Live(live_path(tmp_path, "daily"))
    report.begin("exports")  # a step that began and reported under another name, or not at all
    clock.advance(5)
    report.skipped("private_pages", "signed out")
    body = json.loads(report.live.path.read_text())
    assert body["current"] == {
        "name": None,
        "after": "private_pages",
        "started": clock().isoformat(),
    }
    assert report.current is None and report.current_started is None


def test_the_hooks_leave_the_run_log_and_the_marker_byte_for_byte(tmp_path, monkeypatch):
    hooked = daily(tmp_path / "a", Live(live_path(tmp_path / "a", "daily")))
    # As on main: no step announces itself.
    monkeypatch.setattr(Report, "begin", lambda self, name: None)
    bare = daily(tmp_path / "b", None)
    assert json.dumps(hooked.to_dict()) == json.dumps(bare.to_dict())
    assert json.dumps(marker(hooked)) == json.dumps(marker(bare))


def test_the_run_log_and_the_marker_are_byte_for_byte_as_without_the_file(tmp_path):
    plain = daily(tmp_path / "a", None)
    with_live = daily(tmp_path / "b", Live(live_path(tmp_path / "b", "daily")))
    assert json.dumps(with_live.to_dict()) == json.dumps(plain.to_dict())
    assert json.dumps(marker(with_live)) == json.dumps(marker(plain))
    assert "live" not in with_live.to_dict() and "current" not in with_live.to_dict()


def test_a_write_that_fails_is_logged_and_the_run_goes_on(tmp_path):
    blocked = tmp_path / "routine" / "live"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("a file where the folder goes")
    warned: list[str] = []
    live = Live(live_path(tmp_path, "daily"), warn=warned.append)
    report = daily(tmp_path, live)
    plain = daily(tmp_path / "plain", None)
    assert warned and all(w.startswith("live progress not written") for w in warned)
    assert json.dumps(report.to_dict()) == json.dumps(plain.to_dict())
    # A removal that fails is logged too, never raised.
    live.remove()
    assert warned[-1].startswith("live progress not removed")
    # A file that is not there is removed silently.
    quiet: list[str] = []
    Live(live_path(tmp_path / "none", "daily"), warn=quiet.append).remove()
    assert quiet == []


# --------------------------------------------------------------------------- the script
def script(monkeypatch, fake_run=None):
    spec = importlib.util.spec_from_file_location("routine_script_live", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if fake_run is not None:
        monkeypatch.setattr(module, "run", fake_run)
    return module


def args(tmp_path, routine="evening-build", at="2026-10-29 21:05"):
    return [routine, "--api", "http://127.0.0.1:9", "--data", str(tmp_path), "--now", at]


def ending(how):
    """A run that writes its first progress and a step, checks the file is there, then ends
    ``how``: done, failed, stopped or an exception."""
    seen: dict = {}

    def fake_run(name, ctx, api, force=False):
        report = ctx.report
        report.start_live()
        report.ok("api", "200")
        path = live_path(ctx.data_dir, name)
        seen["mid"] = json.loads(path.read_text()) if path.exists() else None
        if how == "failed":
            report.failed("solve", "boom")
        elif how == "stopped":
            report.stopped = True
        elif how == "exception":
            raise RuntimeError("the runner broke")
        report.finished = ctx.now()
        return report

    return fake_run, seen


@pytest.mark.parametrize(
    "how, code", [("done", "OK"), ("failed", "FAILED"), ("stopped", "STOPPED"), ("exception", None)]
)
def test_the_file_is_removed_however_the_run_ends(tmp_path, monkeypatch, capsys, how, code):
    fake_run, seen = ending(how)
    module = script(monkeypatch, fake_run)
    argv = [*args(tmp_path), "--no-browser", "--no-post"]
    if how == "exception":
        with pytest.raises(RuntimeError):
            module.main(argv)
    else:
        assert module.main(argv) == getattr(module, code)
    assert seen["mid"]["routine"] == "evening-build"
    assert [s["name"] for s in seen["mid"]["steps"]] == ["api"]
    assert not live_path(tmp_path, "evening-build").exists()
    runs = tmp_path / "routine" / "runs" / "2026-10-29-evening-build.json"
    assert runs.exists() == (how != "exception")  # the run log as today


def test_an_unreachable_api_and_a_refused_run_leave_no_file(tmp_path, monkeypatch, capsys):
    module = script(monkeypatch)
    code = module.main([*args(tmp_path / "u"), "--no-browser", "--no-post"])
    assert code == module.UNREACHABLE
    assert not live_path(tmp_path / "u", "evening-build").exists()
    # Refused at the window: nothing written at all, the live folder included.
    code = module.main([*args(tmp_path / "r", routine="morning", at="2026-10-29 03:00")])
    assert code == module.REFUSED and not (tmp_path / "r" / "routine").exists()


def test_a_dry_run_writes_no_progress_file(tmp_path, monkeypatch, capsys):
    fake_run, seen = ending("done")
    module = script(monkeypatch, fake_run)
    argv = [*args(tmp_path), "--no-browser", "--no-post", "--dry-run"]
    assert module.main(argv) == module.OK
    assert seen["mid"] is None and not (tmp_path / "routine").exists()
