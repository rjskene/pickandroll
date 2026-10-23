"""The freshness light's states (#153): ``season.status``, pure, and its route."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pickandroll.api import season_status
from pickandroll.api.seasons import RefreshJob, season_dir
from pickandroll.season import status as st
from tests.test_season import LEAGUE, fixture_names, projection_csv, season_client

#: The Mac's clock: 13:00 on a game day, past the routine's due time; 05:00 before it.
LOCAL = ZoneInfo("America/Chicago")
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC).astimezone(LOCAL)
MORNING = datetime(2026, 10, 21, 5, 0, tzinfo=LOCAL)
YESTERDAY = datetime(2026, 10, 20, 18, 0, tzinfo=LOCAL)


def at(hours: float, now: datetime = NOW) -> datetime:
    """``hours`` before ``now``."""
    return now - timedelta(hours=hours)


def test_the_worst_state_wins_and_none_has_no_say():
    assert st.worst([st.GREEN, st.AMBER, None]) == st.AMBER
    assert st.worst([st.AMBER, st.RED, st.GREEN]) == st.RED
    assert st.worst([None, None]) == st.GREEN == st.worst([])


def test_the_day_and_the_due_time_are_the_macs_clock():
    assert st.due_at(NOW).isoformat() == "2026-10-21T06:30:00-05:00"
    # 23:30 on the Mac is already the next day in New York: the Mac's day counts.
    late = datetime(2026, 10, 21, 23, 30, tzinfo=LOCAL)
    assert st.day_of(late.astimezone(UTC), NOW).isoformat() == "2026-10-21"


def test_an_export_is_green_today_amber_before_its_due_time_and_red_after():
    assert st.export_row("ros", "f.csv", at(1), NOW)["state"] == st.GREEN
    early = st.export_row("week_this", "f.xls", YESTERDAY, MORNING)
    assert (early["state"], early["reason"]) == (st.AMBER, "expected by 06:30")
    # Not due yet: even an older file, or none, is only amber.
    assert st.export_row("actual_7d", None, None, MORNING)["state"] == st.AMBER
    late = st.export_row("week_this", "f.xls", YESTERDAY, NOW)
    assert (late["state"], late["reason"]) == (st.RED, "today's missing")
    missing = st.export_row("actual_14d", None, None, NOW)
    assert (missing["state"], missing["reason"], missing["label"]) == (
        st.RED,
        "missing",
        "last 14 days",
    )


def test_the_exports_section_lists_the_five_kinds_and_takes_the_worst():
    found = {k: (f"{k}.xls", at(2)) for k in st.EXPORTS}
    section = st.exports(found, NOW)
    assert [r["kind"] for r in section["rows"]] == list(st.EXPORTS)
    assert section["state"] == st.GREEN
    found["week_next"] = None
    assert st.exports(found, NOW)["state"] == st.RED


def marker(**over) -> dict:
    steps = {
        "exports": {"status": "ok", "detail": "five exports"},
        "refresh": {"status": "ok", "detail": "13 leagues"},
    }
    return {
        "started_at": at(8).isoformat(),
        "finished_at": at(7).isoformat(),
        "steps": steps,
        **over,
    }


def test_the_routines_run_is_read_from_its_marker():
    ran = st.routine_row(marker(), NOW)
    assert (ran["state"], ran["reason"]) == (st.GREEN, "ran today")
    assert ran["steps"]["refresh"] == {"status": "ok", "detail": "13 leagues"}
    failed = marker(steps={"refresh": {"status": "failed", "detail": "Yahoo 503"}})
    assert st.routine_row(failed, NOW)["reason"] == "refresh failed"
    assert st.routine_row(failed, NOW)["state"] == st.RED
    skipped = marker(steps={"exports": {"status": "skipped", "detail": "no Chrome"}})
    assert st.routine_row(skipped, NOW)["state"] == st.AMBER
    running = marker(started_at=at(0.5, MORNING).isoformat(), finished_at=None)
    assert st.routine_row(running, MORNING)["reason"] == "running"
    assert st.routine_row(marker(finished_at=None), NOW)["reason"] == "not finished"
    # No marker, an unreadable one or yesterday's: no run recorded today.
    for none in (None, {"started_at": "soon"}, marker(started_at=YESTERDAY.isoformat())):
        assert st.routine_row(none, MORNING)["state"] == st.AMBER
        assert st.routine_row(none, MORNING)["reason"] == "no run recorded today, expected by 06:30"
        assert st.routine_row(none, NOW)["state"] == st.RED


def test_a_public_refresh_is_judged_by_its_newest_read_and_its_job():
    assert st.refresh_row(None, at(3), None, NOW)["state"] == st.GREEN
    assert st.refresh_row(None, YESTERDAY, None, MORNING)["state"] == st.AMBER
    late = st.refresh_row(None, YESTERDAY, None, NOW)
    assert (late["state"], late["reason"]) == (st.RED, "not refreshed today")
    running = st.refresh_row({"status": "running"}, YESTERDAY, None, NOW)
    assert (running["state"], running["reason"]) == (st.AMBER, "refreshing")
    failed = st.refresh_row({"status": "failed", "error": "HTTP 999"}, at(3), at(3), NOW)
    assert (failed["state"], failed["error"]) == (st.RED, "HTTP 999")
    skipped = {"status": "done", "warnings": {"matchups": "1 of 6 pairs skipped"}}
    partial = st.refresh_row(skipped, at(3), at(3), NOW)
    assert (partial["state"], partial["reason"]) == (st.AMBER, "pages skipped")
    assert partial["snapshot_at"] == at(3).isoformat()


def test_a_refresh_logged_as_started_and_never_ended_is_red():
    """After a restart the service has no job: the last one its log has stands in, and a start
    with no end is a refresh the service stopped during (#153)."""
    started = {"status": "running", "step": "players", "done": 12, "total": 47}
    lost = st.refresh_row(started, YESTERDAY, None, NOW, live=False)
    assert (lost["state"], lost["reason"]) == (st.RED, "refresh never finished")
    assert (lost["step"], lost["done"], lost["total"], lost["logged"]) == ("players", 12, 47, True)
    # The service's own running job is only amber.
    assert st.refresh_row(started, YESTERDAY, None, NOW)["state"] == st.AMBER
    failed = {"status": "failed", "error": "HTTP 502", "finished_at": at(8).isoformat()}
    logged = st.refresh_row(failed, YESTERDAY, None, NOW, live=False)
    assert (logged["state"], logged["error"], logged["finished_at"]) == (
        st.RED,
        "HTTP 502",
        at(8).isoformat(),
    )
    assert st.refresh_row(None, at(3), None, NOW, live=False)["logged"] is False


def test_the_last_logged_refresh_skips_a_torn_line(tmp_path):
    assert season_status.last_refresh(tmp_path) is None
    log = tmp_path / season_status.REFRESHES
    log.write_text('{"status":"running"}\n{"status":"done","done":47}\n{"status":"fa')
    assert season_status.last_refresh(tmp_path) == {"status": "done", "done": 47}


def test_the_private_leagues_pages_go_by_their_newest_read():
    fetched = {
        "matchup/1/4-10": at(2),
        "lineup/4/2026-10-20": at(30),
        "lineup/4/2026-10-21": at(5),
        "transactions": YESTERDAY,
        "league": at(1),
    }
    assert st.newest_by_kind(fetched)["lineup"] == at(5)
    rows = {r["kind"]: r for r in st.pages(fetched, NOW)}
    assert list(rows) == list(st.PAGES)
    assert rows["matchup"]["state"] == rows["lineup"]["state"] == st.GREEN
    assert (rows["transactions"]["state"], rows["transactions"]["reason"]) == (
        st.RED,
        "not read today",
    )
    assert (rows["schedule"]["state"], rows["schedule"]["reason"]) == (st.RED, "never read")
    # Before the run is due, what was not read today is only amber.
    early = {r["kind"]: r["state"] for r in st.pages(fetched, MORNING)}
    assert early == {
        "matchup": st.GREEN,
        "lineup": st.GREEN,
        "transactions": st.AMBER,
        "schedule": st.AMBER,
    }


def entry(source: str, hours: float, plan: object = None) -> dict:
    return {
        "source": source,
        "at": at(hours).isoformat(),
        "system": {"key": "bbm", "file": "bbm_projections.csv"},
        "plan": plan,
    }


def test_a_solve_older_than_its_inputs_is_amber_and_none_today_is_red_once_due():
    moves = entry("moves", 1, plan={"steps": []})
    recs = st.recommendations([entry("moves", 6), moves], at(4), at(2), NOW)
    rows = {r["kind"]: r for r in recs["rows"]}
    assert (rows["moves"]["state"], rows["moves"]["built_at"]) == (st.GREEN, at(1).isoformat())
    assert rows["moves"]["projection_file"] == "bbm_projections.csv"
    assert rows["plan"]["state"] == st.GREEN and recs["state"] == st.GREEN
    # The strategy and the trades are made on request: no state of their own.
    assert (rows["strategy"]["state"], rows["strategy"]["reason"]) == (None, "run on request")
    assert rows["trades"]["state"] is None and rows["trades"]["built_at"] is None
    assert rows["trades"]["inputs"] == {
        "projection": at(4).isoformat(),
        "Yahoo read": at(2).isoformat(),
    }
    # An input newer than the solve: the view solves again on open.
    stale = st.recommendations([moves], at(0.5), at(2), NOW)
    assert (stale["state"], stale["rows"][0]["reason"]) == (
        st.AMBER,
        "projection newer; re-solved on open",
    )
    read = st.recommendations([moves], at(4), at(0.5), NOW)
    assert read["rows"][0]["reason"] == "Yahoo read newer; re-solved on open"
    # The private league names its newest page.
    page = st.recommendations([moves], at(4), at(0.5), NOW, yahoo="lineup")
    assert page["rows"][0]["reason"] == "lineup read newer; re-solved on open"
    assert list(page["inputs"]) == ["projection", "lineup read"]
    # No solve today: amber before the run is due, red after.
    old = [entry("moves", 20)]
    assert st.recommendations(old, at(30), at(30), MORNING)["state"] == st.AMBER
    late = st.recommendations(old, at(30), at(30), NOW)
    assert (late["state"], late["rows"][0]["reason"]) == (st.RED, "not solved today")
    assert st.recommendations([], at(4), at(2), NOW)["rows"][0]["state"] == st.RED


def test_a_league_without_a_plan_says_so_and_a_strategy_run_shows_its_inputs():
    recs = st.recommendations([entry("moves", 1), entry("strategy", 3)], at(2), at(2), NOW)
    rows = {r["kind"]: r for r in recs["rows"]}
    assert (rows["plan"]["state"], rows["plan"]["reason"]) == (None, "no plan for this league")
    assert rows["strategy"]["state"] is None
    assert rows["strategy"]["reason"] == "projection newer; re-solved on open"
    assert recs["inputs"] == {"projection": at(2).isoformat(), "Yahoo read": at(2).isoformat()}


def test_a_league_is_its_worst_section_and_the_whole_adds_the_run_and_the_exports():
    recs = st.recommendations([entry("moves", 1, plan={"steps": []})], at(4), at(2), NOW)
    rows = [st.refresh_row(None, at(2), None, NOW)]
    green = st.league("100001", "League", True, rows, recs, st.GREEN)
    assert green["state"] == st.GREEN and green["yahoo"]["state"] == st.GREEN
    assert st.league("100001", "League", True, rows, recs, st.RED)["state"] == st.RED
    unread = st.pages({"matchup/1/1-2": at(2)}, NOW)
    private = st.league("100002", None, False, unread, recs, st.GREEN)
    assert private["state"] == st.RED  # its other pages never read
    exports = st.exports({k: (f"{k}.xls", at(2)) for k in st.EXPORTS}, NOW)
    ran = st.routine_row(marker(), NOW)
    out = st.payload(ran, exports, [green], NOW)
    assert (out["state"], out["today"]) == (st.GREEN, "2026-10-21")
    assert out["due_at"] == "2026-10-21T06:30:00-05:00"
    assert st.payload(ran, exports, [green, private], NOW)["state"] == st.RED
    assert st.payload(st.routine_row(None, NOW), exports, [green], NOW)["state"] == st.RED


def test_the_status_route_lights_every_league_and_names_what_is_late(tmp_path):
    """The route on the fixture leagues, the clock at :data:`NOW` on the Mac's clock: nothing
    read and no export first; then the run, the exports, a refresh and the moves solved; then
    a projection newer than the moves, a missing export and a failed refresh."""
    with season_client(tmp_path) as client:
        client.app.state.seasons.local_tz = LOCAL
        before = client.get("/seasons/status").json()
        assert before["state"] == st.RED and before["today"] == "2026-10-21"
        assert before["routine"]["reason"] == "no run recorded today"
        assert {r["reason"] for r in before["exports"]["rows"]} == {"missing"}
        assert [lg["league"] for lg in before["leagues"]] == ["100001", "100002"]

        (tmp_path / "routine").mkdir()
        (tmp_path / "routine" / "daily.json").write_text(json.dumps(marker()))
        ros = tmp_path / "bbm_projections_2026-10-21.csv"
        projection_csv(ros, fixture_names())
        os.utime(ros, (at(4).timestamp(), at(4).timestamp()))
        for name in ("week_this", "week_next", "actual_7d_totals", "actual_14d_totals"):
            export = tmp_path / f"bbm_{name}_20261021-1400.xls"
            export.write_bytes(b"")
            sidecar = {"as_of": at(4).isoformat(), "file": export.name}
            export.with_suffix(".json").write_text(json.dumps(sidecar))
        client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
        assert client.get(f"/seasons/{LEAGUE}/moves").status_code == 200
        p = client.get("/seasons/status").json()
        assert p["routine"]["state"] == p["exports"]["state"] == st.GREEN
        public, private = p["leagues"]
        assert public["yahoo"]["rows"][0]["read_at"] == NOW.astimezone(UTC).isoformat()
        assert public["recommendations"]["rows"][0]["state"] == st.GREEN
        assert public["state"] == st.GREEN
        # The private league reads no page of its own here: red, and so over all.
        assert (private["public"], private["state"], p["state"]) == (False, st.RED, st.RED)

        later = (NOW + timedelta(minutes=1)).timestamp()
        os.utime(ros, (later, later))
        (tmp_path / "bbm_week_next_20261021-1400.xls").unlink()
        failed = RefreshJob(LEAGUE, status="failed", error="Yahoo answered 503")
        client.app.state.seasons.jobs[LEAGUE] = failed
        p = client.get("/seasons/status").json()
        public = p["leagues"][0]
        moves = public["recommendations"]["rows"][0]
        assert (moves["state"], moves["reason"]) == (
            st.AMBER,
            "projection newer; re-solved on open",
        )
        assert public["yahoo"]["rows"][0]["error"] == "Yahoo answered 503"
        assert public["yahoo"]["state"] == st.RED
        rows = {r["kind"]: r for r in p["exports"]["rows"]}
        assert rows["week_next"]["reason"] == "missing"

        # The refresh logged its start and its end, each with its time; after a restart (no
        # job in the service) the light reads the log's last line.
        log = season_dir(tmp_path, LEAGUE) / season_status.REFRESHES
        lines = [json.loads(x) for x in log.read_text().splitlines()]
        assert [x["status"] for x in lines] == ["running", "done"]
        assert all(x["at"] and x["league"] == LEAGUE for x in lines)
        assert lines[1]["finished_at"] and lines[1]["step"] == "done"
        client.app.state.seasons.jobs.clear()
        refresh = client.get("/seasons/status").json()["leagues"][0]["yahoo"]["rows"][0]
        assert (refresh["status"], refresh["logged"], refresh["state"]) == ("done", True, st.GREEN)
        # A start the log never saw end: the service stopped during it.
        with log.open("a") as f:
            f.write(json.dumps({**lines[0], "at": NOW.isoformat()}) + "\n")
        refresh = client.get("/seasons/status").json()["leagues"][0]["yahoo"]["rows"][0]
        assert (refresh["state"], refresh["reason"]) == (st.RED, "refresh never finished")
