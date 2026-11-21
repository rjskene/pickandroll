"""The floor's read-only routes (FLOOR PR 1, #458): the routines' run logs over a window of days,
a file that does not read listed with its reason, and the live progress files, stale after an
hour. Every folder here is a temporary one; nothing reads Yahoo."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

from pickandroll.api import routine_runs as rr
from pickandroll.api import season_knobs, season_pretip
from pickandroll.season import reserve as rs

from .test_moves_queue import PRIVATE, queued, row_of
from .test_season import LEAGUE, NOW, client  # noqa: F401 - the fixture

TODAY = NOW.astimezone(rr.CENTRAL).date()


def run_log(routine: str, day: date, **kw) -> dict:
    """A run log shaped as ``scripts/routine.py`` writes one."""
    at = f"{day.isoformat()}T05:00:00-06:00"
    step = {"name": "api", "status": "ok", "detail": "200", "started": at, "finished": at}
    return {"routine": routine, "started_at": at, "finished_at": at, "steps": [step], **kw}


def write_run(data_dir, day: date, routine: str, body) -> None:
    folder = rr.runs_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    text = body if isinstance(body, str) else json.dumps(body)
    (folder / f"{day.isoformat()}-{routine}.json").write_text(text)


def test_the_runs_of_a_window_of_days_are_served_as_written_keyed_by_day_and_routine(tmp_path):
    days = [TODAY - timedelta(days=n) for n in range(9)]
    for d in days:
        write_run(tmp_path, d, "daily", run_log("daily", d))
    write_run(tmp_path, TODAY, "evening-build", run_log("evening-build", TODAY, failed=["x"]))
    # Not a run log's name, and a writer's temporary file: neither is listed.
    (rr.runs_dir(tmp_path) / "notes.json").write_text("{}")
    (rr.runs_dir(tmp_path) / f"{TODAY.isoformat()}-daily.json.tmp").write_text("{")
    out = rr.runs(tmp_path, TODAY, 3)
    assert out["date"] == TODAY.isoformat() and out["days"] == 3
    assert [d["date"] for d in out["by_day"]] == [d.isoformat() for d in reversed(days[:3])]
    last = out["by_day"][-1]
    assert sorted(last["runs"]) == ["daily", "evening-build"]
    assert last["runs"]["evening-build"] == run_log("evening-build", TODAY, failed=["x"])
    assert all(d["unread"] == [] for d in out["by_day"])
    # One day by default; a day with no run is listed empty.
    [one] = rr.runs(tmp_path, TODAY + timedelta(days=1))["by_day"]
    assert one == {
        "date": (TODAY + timedelta(days=1)).isoformat(),
        "runs": {},
        "unread": [],
        "pretip": {"enabled": False, "lead_min": 60, "latest_start": "20:40", "slates": []},
    }


def test_a_file_that_does_not_read_is_listed_with_its_reason_never_dropped(tmp_path):
    write_run(tmp_path, TODAY, "daily", run_log("daily", TODAY))
    write_run(tmp_path, TODAY, "late", "{not json")
    write_run(tmp_path, TODAY, "morning", "[1, 2]")
    [day] = rr.runs(tmp_path, TODAY)["by_day"]
    assert list(day["runs"]) == ["daily"]
    reasons = {u["routine"]: (u["file"], u["reason"]) for u in day["unread"]}
    assert reasons["late"][0] == f"{TODAY.isoformat()}-late.json"
    assert reasons["late"][1].startswith("is not JSON")
    assert reasons["morning"][1] == "is not a run log (not a JSON object)"


def test_no_runs_folder_lists_every_day_empty_and_a_window_out_of_bounds_is_refused(tmp_path):
    out = rr.runs(tmp_path, TODAY, 7)
    assert len(out["by_day"]) == 7 and all(not d["runs"] for d in out["by_day"])
    for bad in (0, 8):
        try:
            rr.runs(tmp_path, TODAY, bad)
        except ValueError:
            continue
        raise AssertionError(f"days={bad} was not refused")  # pragma: no cover


def test_the_live_files_are_listed_with_when_written_and_stale_after_an_hour(tmp_path):
    assert rr.live(tmp_path, NOW)["live"] == []  # no folder
    folder = rr.live_dir(tmp_path)
    folder.mkdir(parents=True)
    assert rr.live(tmp_path, NOW)["live"] == []  # no file
    (folder / "daily.json").write_text(json.dumps({"step": "refresh", "done": 3}))
    (folder / "late.json").write_text(json.dumps({"step": "lineups"}))
    (folder / "morning.json").write_text("{half")
    for name, ago in (("daily", 10), ("late", 61), ("morning", 5)):
        t = (NOW - timedelta(minutes=ago)).timestamp()
        os.utime(folder / f"{name}.json", (t, t))
    rows = {r["routine"]: r for r in rr.live(tmp_path, NOW)["live"]}
    assert sorted(rows) == ["daily", "late", "morning"]
    assert rows["daily"]["progress"] == {"step": "refresh", "done": 3}
    assert not rows["daily"]["stale"] and rows["daily"]["reason"] is None
    assert rows["late"]["stale"]  # a run that died leaves its file behind
    assert rows["morning"]["progress"] is None and rows["morning"]["reason"].startswith("is not")
    written = (NOW - timedelta(minutes=10)).astimezone(rr.CENTRAL)
    assert rows["daily"]["written_at"] == written.isoformat(timespec="seconds")


def test_the_routes_serve_both_over_the_apps_data_folder(client):  # noqa: F811
    data = client.data_dir
    write_run(data, TODAY, "daily", run_log("daily", TODAY))
    write_run(data, TODAY - timedelta(days=1), "late", "{bad")
    r = client.get("/routine/runs")
    assert r.status_code == 200, r.text
    [day] = r.json()["by_day"]
    assert day["date"] == TODAY.isoformat() and list(day["runs"]) == ["daily"]
    two = client.get("/routine/runs", params={"date": TODAY.isoformat(), "days": 2}).json()
    assert [u["routine"] for u in two["by_day"][0]["unread"]] == ["late"]
    for bad in (0, 8):
        assert client.get("/routine/runs", params={"days": bad}).status_code == 422
    assert client.get("/routine/runs", params={"date": "yesterday"}).status_code == 422
    assert client.get("/routine/live").json()["live"] == []
    folder = rr.live_dir(data)
    folder.mkdir(parents=True)
    (folder / "daily.json").write_text(json.dumps({"step": "refresh"}))
    old = (NOW - timedelta(hours=2)).timestamp()
    os.utime(folder / "daily.json", (old, old))
    [row] = client.get("/routine/live").json()["live"]
    assert row["routine"] == "daily" and row["stale"] and row["progress"] == {"step": "refresh"}


# --------------------------------------------------------------------------- the pre-tip block
TIPS = {"BOS": "2026-11-20T00:00:00+00:00", "LAL": "2026-11-20T03:30:00+00:00"}


def pretip_on(data_dir) -> None:
    folder = season_knobs.autopilot_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "executor.json").write_text(json.dumps({"pretip": {"enabled": True}}))


def attempt(slate: str, at: str, **kw) -> season_pretip.PretipRun:
    return season_pretip.PretipRun(slate=slate, started_at=at, moves=[{"add": 1, "drop": 2}], **kw)


def test_each_day_carries_its_pretip_slates_planned_from_the_tips_with_their_attempts(tmp_path):
    day = date(2026, 11, 19)
    pretip_on(tmp_path)
    season_pretip.record(
        tmp_path,
        day,
        attempt(
            "first",
            "2026-11-19T17:00:10-06:00",
            outcome="failed",
            reason="push failed",
            solved_at="2026-11-19T17:05:00-06:00",
        ),
    )
    season_pretip.record(
        tmp_path,
        day,
        attempt(
            "first",
            "2026-11-19T17:10:10-06:00",
            outcome="done",
            solved_at="2026-11-19T17:12:00-06:00",
            pushed_at="2026-11-19T17:12:01-06:00",
            lineups_at="2026-11-19T17:18:00-06:00",
        ),
    )
    asked = []

    def tips_of(d):
        asked.append(d)
        return TIPS if d == day else None

    out = rr.runs(tmp_path, day, 2, tips_of)
    assert asked == [day - timedelta(days=1), day]
    before, block = (d["pretip"] for d in out["by_day"])
    assert before == {"enabled": True, "lead_min": 60, "latest_start": "20:40", "slates": []}
    assert block["enabled"] and block["lead_min"] == 60
    first, late = block["slates"]
    # Planned from the tip-offs as the pass plans them: start an hour before, until 15 minutes before.
    assert first["slate"] == "first" and first["tip"] == "2026-11-19T18:00:00-06:00"
    assert first["start_at"] == "2026-11-19T17:00:00-06:00"
    assert first["until"] == "2026-11-19T17:45:00-06:00"
    assert first["done"] and not first["missed"]
    assert [a["outcome"] for a in first["attempts"]] == ["failed", "done"]
    assert first["attempts"][0]["reason"] == "push failed"
    assert first["attempts"][1]["lineups_at"] == "2026-11-19T17:18:00-06:00"
    # The attempts carry their times and outcome only: never the moves or the pulls.
    assert set(first["attempts"][0]) == set(rr.ATTEMPT_FIELDS)
    assert late == {
        "slate": "late",
        "tip": "2026-11-19T21:30:00-06:00",
        "start_at": "2026-11-19T20:30:00-06:00",
        "until": "2026-11-19T21:15:00-06:00",
        "past_latest": False,
        "done": False,
        "missed": False,
        "attempts": [],
    }


def test_a_kept_slate_without_a_schedule_copy_or_missed_is_served_from_the_day_file(tmp_path):
    day = date(2026, 11, 19)
    season_pretip.record(
        tmp_path, day, attempt("late", "2026-11-19T20:46:00-06:00", outcome="missed")
    )
    block = rr.runs(tmp_path, day)["by_day"][0]["pretip"]
    assert block["enabled"] is False  # the knob is off by default
    [late] = block["slates"]
    assert late["slate"] == "late" and late["tip"] is None and late["start_at"] is None
    assert late["past_latest"] is False
    assert late["missed"] and not late["done"]
    assert [a["outcome"] for a in late["attempts"]] == ["missed"]
    # A day file that does not read is no slate.
    season_pretip.day_path(tmp_path, day).write_text("{oops")
    assert rr.runs(tmp_path, day)["by_day"][0]["pretip"]["slates"] == []


def test_a_slate_that_would_start_past_latest_start_is_marked_so_never_due(tmp_path):
    day = date(2026, 11, 19)
    pretip_on(tmp_path)
    # A 21:45 CT late tip-off: its start, 20:45, is past latest_start 20:40.
    tips = {"BOS": "2026-11-20T00:00:00+00:00", "LAL": "2026-11-20T03:45:00+00:00"}
    block = rr.runs(tmp_path, day, 1, lambda d: tips)["by_day"][0]["pretip"]
    assert block["latest_start"] == "20:40"
    first, late = block["slates"]
    assert late["start_at"] == "2026-11-19T20:45:00-06:00"
    assert late["past_latest"] is True and first["past_latest"] is False
    # And due() agrees: at 20:50 the late slate is not made due.
    now = datetime(2026, 11, 19, 20, 50, tzinfo=rr.CENTRAL)
    out = season_pretip.due(tmp_path, now, day, tips, stopped=False)
    assert not out["due"] and "would start past 20:40" in out["reason"]


def test_the_route_plans_the_slates_from_the_schedule_copy(client):  # noqa: F811
    data = client.data_dir
    pretip_on(data)
    folder = data / "schedule"
    folder.mkdir(parents=True, exist_ok=True)
    tips = {"BOS": f"{TODAY.isoformat()}T23:00:00+00:00"}
    (folder / f"{TODAY.isoformat()}.json").write_text(
        json.dumps({"fetched_at": NOW.isoformat(), "teams": ["BOS"], "tips": tips})
    )
    [day] = client.get("/routine/runs").json()["by_day"]
    [first] = day["pretip"]["slates"]
    assert first["slate"] == "first" and first["attempts"] == [] and not first["done"]
    assert first["tip"] == season_pretip.slates(tips, season_pretip.settings(data))[0]["tip"]


# --------------------------------------------------------------------------- the rule knobs
def test_the_queue_settings_carry_each_leagues_rules_from_its_row_and_the_solves_reader(client):  # noqa: F811
    # Before a build: no rows, no rules.
    assert client.get("/autopilot/queue").json()["settings"]["rules"] == {}
    own = {"daily_cap": 3, "reserve_adds": 2, "recut_days": 5, "reserve_price": 0.25}
    knobs = {"in_force": {"reserve_release": "thursday"}, "leagues": {LEAGUE: own}}
    path = client.data_dir / "autopilot" / "knobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(knobs))
    q = queued(client)
    rules, row = q["settings"]["rules"], row_of(q)
    # The floor and the cap are the league's own row's, so they cannot drift from it.
    assert rules[LEAGUE]["noise_floor"] == row["floor"]
    assert rules[LEAGUE]["daily_cap"] == {"value": row["cap"], "from": row["cap_from"]}
    assert rules[LEAGUE]["daily_cap"] == {"value": 3, "from": "the knob"}
    # The reserve's and the re-cut rule's knobs are the solve's own reader's, not the defaults.
    read = rs.knobs_of(season_knobs.for_league(client.data_dir, LEAGUE))
    assert read != dict(rs.DEFAULTS)
    assert (
        {k: rules[LEAGUE][k] for k in rs.KNOBS}
        == read
        == {
            "reserve_adds": 2,
            "reserve_release": "thursday",
            "reserve_price": 0.25,
            "recut_days": 5,
        }
    )
    assert rules[LEAGUE]["reserve_price_from"] == "the knob"
    # The private league's row is there too, with no floor and no cap of its own; its price
    # is the typical gain's.
    assert rules[PRIVATE]["noise_floor"] is None
    assert rules[PRIVATE]["daily_cap"] == {"value": None, "from": None}
    assert rules[PRIVATE]["reserve_price"] is None
    assert rules[PRIVATE]["reserve_price_from"] == "typical"
    # The stored queue's GET answers the same rules.
    assert client.get("/autopilot/queue").json()["settings"]["rules"] == rules
