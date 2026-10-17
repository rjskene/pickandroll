"""The draft-day runbook's stale-log guard (scripts/draft_day.py, #67): a room log under the league's
id that an earlier run first attached is not rebuilt. The attach and the run stop with exit 8 and
name the file to move aside; this run's own log (an API restart mid-draft) still rebuilds."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draft_day.py"
LEAGUE = "238174"
DRAFT = "2026-10-17T11:00:00-07:00"


@pytest.fixture
def runbook(tmp_path, monkeypatch):
    """The script as a module, its root moved to a scratch folder holding one league."""
    spec = importlib.util.spec_from_file_location("draft_day_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "data"
    (data / "leagues" / LEAGUE).mkdir(parents=True)
    (data / "fidelity").mkdir()
    settings = {"scoring": "points", "num_teams": 12, "draft": {"time": DRAFT, "pick_seconds": 60}}
    (data / "leagues" / LEAGUE / "settings.json").write_text(json.dumps(settings))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    return module


def write_log(runbook, *attached_at):
    path = runbook.DATA / "fidelity" / f"{LEAGUE}.jsonl"
    events = [{"type": "note", "t": "2026-10-14T01:00:00Z", "what": "entered"}]
    events += [{"type": "attach", "t": t, "draft_id": LEAGUE} for t in attached_at]
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


def no_api(*args, **kwargs):
    raise AssertionError(f"the API was called: {args}")


def test_an_earlier_runs_log_stops_the_attach_before_the_api(runbook, monkeypatch):
    # A rehearsal under the league's id two days before, then this run's attach.
    write_log(runbook, "2026-10-15T16:00:00Z", "2026-10-17T17:30:00Z")
    monkeypatch.setattr(runbook, "api", no_api)
    with pytest.raises(runbook.Stop) as stop:
        runbook.attach(LEAGUE, None)
    assert stop.value.code == runbook.STALE == 8
    message = str(stop.value)
    assert message.startswith(f"data/fidelity/{LEAGUE}.jsonl is an earlier run's log")
    assert "first attached Thu 2026-10-15 09:00 PDT, 50 h before this draft (Sat 11:00 PDT)" in (
        message
    )
    assert (
        f"mv data/fidelity/{LEAGUE}.jsonl data/fidelity/{LEAGUE}_2026-10-15_earlier.jsonl"
        in message
    )
    assert f"DELETE /rooms/{LEAGUE} first" in message


@pytest.mark.parametrize("command", ["attach", "run"])
def test_the_run_and_the_attach_command_exit_8(runbook, monkeypatch, command, capsys):
    write_log(runbook, "2026-10-15T16:00:00Z")
    for step in ("keep_awake", "servers", "refresh", "monitor", "finish"):
        monkeypatch.setattr(runbook, step, lambda *a, **k: runbook.OK)
    monkeypatch.setattr(runbook, "status", lambda *a, **k: "predraft")
    monkeypatch.setattr(runbook, "api", no_api)
    monkeypatch.setattr(sys, "argv", ["draft_day.py", command, LEAGUE])
    assert runbook.main() == 8
    out = capsys.readouterr().out
    assert "STOP data/fidelity/238174.jsonl is an earlier run's log" in out and "(exit 8)" in out
    log = (runbook.DATA / "fidelity" / f"draft_day_{LEAGUE}.log").read_text()
    assert "(exit 8)" in log


def test_this_runs_log_rebuilds_the_room(runbook, monkeypatch):
    """An API restart mid-draft: the log's first attach is this run's (T-30), so the attach
    rebuilds the room from it."""
    write_log(runbook, "2026-10-17T17:30:00Z")
    calls = []

    def api(method, path, body=None, timeout=60.0):
        calls.append((method, path, body))
        return [] if method == "GET" else {"mode": "autopilot", "picks_applied": 40}

    def call(method, url, body=None, timeout=30.0):
        calls.append((method, url.removeprefix(runbook.API), body))
        return 201, {"mode": "autopilot", "picks_applied": 40}

    monkeypatch.setattr(runbook, "api", api)
    monkeypatch.setattr(runbook, "call", call)
    assert runbook.attach(LEAGUE, None) == runbook.OK
    assert calls == [("GET", "/rooms", None), ("POST", "/rooms", {"draft_id": LEAGUE})]


def test_the_guard_reads_the_first_attach_against_the_draft_time(runbook):
    mine = runbook.settings(LEAGUE)
    runbook.check_log(LEAGUE, mine)  # no log: nothing to judge
    path = runbook.DATA / "fidelity" / f"{LEAGUE}.jsonl"
    path.write_text(json.dumps({"type": "note", "t": "2026-10-10T00:00:00Z"}) + "\n")
    runbook.check_log(LEAGUE, mine)  # no attach in it: nothing to judge
    write_log(runbook, "2026-10-17T12:06:00Z")  # 5.9 h before the 18:00 UTC start
    runbook.check_log(LEAGUE, mine)
    write_log(runbook, "2026-10-17T12:00:00Z")  # 6 h before: an earlier run
    with pytest.raises(runbook.Stop, match="6 h before this draft"):
        runbook.check_log(LEAGUE, mine)
    runbook.check_log(LEAGUE, {**mine, "draft": {}})  # no draft time: nothing to judge


# --------------------------------------------------------------------------- a finished room
def test_servers_does_not_count_a_complete_room_as_live(runbook, monkeypatch, capsys):
    monkeypatch.setattr(runbook, "call", lambda *a, **k: (200, {}))
    rooms = [{"draft_id": LEAGUE, "complete": True}, {"draft_id": "15953", "complete": False}]
    monkeypatch.setattr(runbook, "api", lambda *a, **k: rooms)
    assert runbook.servers() == runbook.OK
    out = capsys.readouterr().out
    assert "live rooms on the API: 15953\n" in out
    assert f"complete rooms on the API (not live): {LEAGUE}" in out
    monkeypatch.setattr(runbook, "api", lambda *a, **k: rooms[:1])
    runbook.servers()
    assert "live rooms" not in capsys.readouterr().out


def test_the_attach_says_a_complete_room_is_complete(runbook, monkeypatch, capsys):
    write_log(runbook, "2026-10-17T17:30:00Z")
    monkeypatch.setattr(runbook, "api", lambda *a, **k: [])
    detail = {"detail": f"draft complete: room {LEAGUE}'s log holds all 156 picks; not resumed"}
    monkeypatch.setattr(runbook, "call", lambda *a, **k: (409, detail))
    assert runbook.attach(LEAGUE, None) == runbook.OK
    assert f"room {LEAGUE} complete: its log holds every pick" in capsys.readouterr().out
    monkeypatch.setattr(runbook, "call", lambda *a, **k: (500, {"detail": "boom"}))
    with pytest.raises(runbook.Stop, match="POST /rooms: 500 boom"):
        runbook.attach(LEAGUE, None)


def test_the_monitor_ends_on_a_room_complete_before_a_restart(runbook, monkeypatch):
    detail = {"detail": f"no room {LEAGUE}: its draft is complete (156 picks in its log)"}
    monkeypatch.setattr(runbook, "keep_awake", lambda: None)
    monkeypatch.setattr(runbook, "call", lambda *a, **k: (404, detail))
    assert runbook.monitor(LEAGUE, 180, 1200, 3600) == runbook.OK


def test_finish_replays_a_complete_room_after_a_restart(runbook, monkeypatch):
    write_log(runbook, "2026-10-17T17:30:00Z")
    room = {"session_id": "s1", "mode": "autopilot", "picks_applied": 156, "num_teams": 12}
    room |= {"rounds": 13, "complete": True}
    calls = []

    def call(method, url, body=None, timeout=30.0):
        calls.append((method, url.removeprefix(runbook.API), body))
        if (method, url) == ("GET", f"{runbook.API}/rooms/{LEAGUE}") and len(calls) == 1:
            return 404, {"detail": f"no room {LEAGUE}: its draft is complete (156 picks)"}
        if method == "POST":
            return 201, room
        return 200, room

    monkeypatch.setattr(runbook, "call", call)
    monkeypatch.setattr(runbook, "hooks", lambda name: [])
    assert runbook.finish(LEAGUE) == runbook.OK
    assert calls[:2] == [
        ("GET", f"/rooms/{LEAGUE}", None),
        ("POST", "/rooms", {"draft_id": LEAGUE, "replay": True}),
    ]
    saved = list((runbook.DATA / "fidelity").glob(f"{LEAGUE}_*_session_s1"))
    assert len(saved) == 1 and (saved[0] / "ledger.jsonl").exists()
