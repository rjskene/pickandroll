"""The freshness light's states (#153): ``season.status``, pure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pickandroll.season import status as st

#: 14:00 ET on a game day, after the routine's due time; the morning before it.
NOW = datetime(2026, 10, 21, 18, 0, tzinfo=UTC)
MORNING = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)  # 05:00 ET
YESTERDAY = NOW - timedelta(hours=20)  # 18:00 ET the day before
OLD = NOW - timedelta(days=3)


def at(hours: float) -> datetime:
    """``hours`` before :data:`NOW`."""
    return NOW - timedelta(hours=hours)


def test_the_worst_state_wins_and_none_has_no_say():
    assert st.worst([st.GREEN, st.AMBER, None]) == st.AMBER
    assert st.worst([st.AMBER, st.RED, st.GREEN]) == st.RED
    assert st.worst([None, None]) == st.GREEN == st.worst([])


def test_an_export_is_green_today_amber_before_its_due_time_and_red_after():
    assert st.export_row("ros", "f.csv", at(1), NOW)["state"] == st.GREEN
    # Yesterday's file before today's is due: amber; after the due time: red.
    early = st.export_row("week_this", "f.xls", YESTERDAY - timedelta(hours=12), MORNING)
    assert (early["state"], early["reason"]) == (st.AMBER, "yesterday's, today's not due yet")
    late = st.export_row("week_this", "f.xls", YESTERDAY, NOW)
    assert (late["state"], late["reason"]) == (st.RED, "today's missing")
    # Older than yesterday is red even before the due time, and so is no file at all.
    assert st.export_row("actual_7d", "f.xls", OLD, MORNING)["state"] == st.RED
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


def test_a_public_refresh_is_judged_by_its_newest_read_and_its_job():
    assert st.refresh_row(None, at(3), None, NOW)["state"] == st.GREEN
    assert st.refresh_row(None, YESTERDAY, None, NOW)["reason"] == "not today"
    assert st.refresh_row(None, YESTERDAY, None, NOW)["state"] == st.AMBER
    assert st.refresh_row(None, OLD, None, NOW)["state"] == st.RED
    assert st.refresh_row(None, None, None, NOW)["reason"] == "never read"
    running = st.refresh_row({"status": "running"}, YESTERDAY, None, NOW)
    assert (running["state"], running["reason"]) == (st.AMBER, "refreshing")
    failed = st.refresh_row({"status": "failed", "error": "HTTP 999"}, at(3), at(3), NOW)
    assert (failed["state"], failed["error"]) == (st.RED, "HTTP 999")
    skipped = {"status": "done", "warnings": {"matchups": "1 of 6 pairs skipped"}}
    partial = st.refresh_row(skipped, at(3), at(3), NOW)
    assert (partial["state"], partial["reason"]) == (st.AMBER, "pages skipped")
    assert partial["snapshot_at"] == at(3).isoformat()


def test_the_private_leagues_pages_go_by_their_newest_read():
    fetched = {
        "matchup/1/4-10": at(2),
        "lineup/4/2026-10-20": OLD,
        "lineup/4/2026-10-21": at(5),
        "transactions": YESTERDAY,
        "league": at(1),
    }
    assert st.newest_by_kind(fetched)["lineup"] == at(5)
    rows = {r["kind"]: r for r in st.pages(fetched, NOW)}
    assert list(rows) == list(st.PAGES)
    assert rows["matchup"]["state"] == rows["lineup"]["state"] == st.GREEN
    assert rows["transactions"]["state"] == st.AMBER
    assert (rows["schedule"]["state"], rows["schedule"]["reason"]) == (st.RED, "never read")


def entry(source: str, hours: float, plan: object = None) -> dict:
    return {
        "source": source,
        "at": at(hours).isoformat(),
        "system": {"key": "bbm", "file": "bbm_projections.csv"},
        "plan": plan,
    }


def test_a_recommendation_is_red_when_an_input_is_newer_and_amber_when_not_built_today():
    moves = entry("moves", 1, plan={"steps": []})
    recs = st.recommendations([entry("moves", 6), moves], at(4), at(2), NOW)
    rows = {r["kind"]: r for r in recs["rows"]}
    assert (rows["moves"]["state"], rows["moves"]["built_at"]) == (st.GREEN, at(1).isoformat())
    assert rows["moves"]["projection_file"] == "bbm_projections.csv"
    assert rows["plan"]["state"] == st.GREEN and recs["state"] == st.GREEN
    # The strategy and the trades are made on request: no state of their own.
    assert (rows["strategy"]["state"], rows["strategy"]["reason"]) == (None, "run on request")
    assert rows["trades"]["state"] is None and rows["trades"]["built_at"] is None
    # A projection newer than the build; a Yahoo read newer than it.
    stale = st.recommendations([moves], at(0.5), at(2), NOW)
    assert (stale["state"], stale["rows"][0]["reason"]) == (st.RED, "projection newer")
    read = st.recommendations([moves], at(4), at(0.5), NOW)
    assert read["rows"][0]["reason"] == "Yahoo read newer"
    # Built yesterday on yesterday's inputs; never built.
    old = st.recommendations([entry("moves", 20)], at(30), at(30), NOW)
    assert (old["state"], old["rows"][0]["reason"]) == (st.AMBER, "not built today")
    assert st.recommendations([], at(4), at(2), NOW)["rows"][0]["state"] == st.AMBER


def test_a_league_without_a_plan_says_so_and_a_strategy_run_shows_its_inputs():
    recs = st.recommendations([entry("moves", 1), entry("strategy", 3)], at(2), at(2), NOW)
    rows = {r["kind"]: r for r in recs["rows"]}
    assert (rows["plan"]["state"], rows["plan"]["reason"]) == (None, "no plan for this league")
    assert (rows["strategy"]["state"], rows["strategy"]["reason"]) == (None, "projection newer")
    assert recs["inputs"] == {"projection": at(2).isoformat(), "Yahoo read": at(2).isoformat()}


def test_a_league_is_its_worst_section_and_the_whole_its_worst_league():
    recs = st.recommendations([entry("moves", 1, plan={"steps": []})], at(4), at(2), NOW)
    rows = [st.refresh_row(None, at(2), None, NOW)]
    green = st.league("100001", "League", True, rows, recs, st.GREEN)
    assert green["state"] == st.GREEN and green["yahoo"]["state"] == st.GREEN
    assert st.league("100001", "League", True, rows, recs, st.RED)["state"] == st.RED
    private = st.league(
        "100002", None, False, st.pages({"matchup/1/1-2": YESTERDAY}, NOW), recs, st.GREEN
    )
    assert private["state"] == st.RED  # its schedule never read
    exports = st.exports({k: (f"{k}.xls", at(2)) for k in st.EXPORTS}, NOW)
    out = st.payload(exports, [green], {"started_at": None, "finished_at": None}, NOW)
    assert (out["state"], out["today"]) == (st.GREEN, "2026-10-21")
    assert out["due_at"] == "2026-10-21T06:30:00-04:00"
    assert st.payload(exports, [green, private], None, NOW)["state"] == st.RED
