"""The week's adds from every stored read of the transactions page (#383).

The page lists a fixed number of rows, so a busy league's newest read stops reaching back to the
week's start and its count of my adds is only a floor. ``season.moves.adds_used`` joins the older
reads (``api.season_reads.older_reads``, the league's snapshots) to the newest, and a week the
joined reads still do not reach back past is held on the Queue (``ADDS_UNREAD``).

``tests/fixtures/season/adds_reads.json`` holds real reads of two public leagues in the week of
2026-11-09, with no league id and no team names (team ids and NBA player names only):

- ``wrapped``: my four adds, the first on Monday 04:17; by Friday night the newest read starts
  after it, so it counts 3 as a floor. Two older reads of the week join it and reach Sunday.
- ``short``: four adds, the newest read starting on Monday, so its count is a floor; with no
  older read the week is held, and the read of the night before (``covering``) completes it.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pickandroll.api import season_moves, season_queue, season_reads
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season.state import Player, Transaction
from tests.test_moves_queue import (
    LEAGUE,
    PLAN,
    TYPICAL,
    entry,
    league_day,
    move,
    queued,
    reasons,
)
from tests.test_season import season_client


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


FIXTURE = json.loads((Path(__file__).parent / "fixtures/season/adds_reads.json").read_text())
START, END, TODAY = (date.fromisoformat(FIXTURE[k]) for k in ("start", "end", "today"))
WEEK = (START, END)
NEXT = (date(2026, 11, 16), date(2026, 11, 22))


def read(rows) -> tuple[Transaction, ...]:
    return tuple(Transaction.from_dict(r) for r in rows)


def case(name: str):
    c = FIXTURE["cases"][name]
    return c["team"], read(c["newest"]), tuple(read(r) for r in c["older"])


def tx(kind, player, team, when, group=0) -> Transaction:
    return Transaction(
        kind, Player(player, f"P{player}", "X", ("PG",)), team, None, None, when, group
    )


def page(tag: int, when: str, *rows: Transaction) -> tuple[Transaction, ...]:
    """A full page: ``rows`` and another team's adds at ``when``, its own players, up to
    ``PAGE_TRANSACTIONS`` transactions (a shorter read is the league's whole list)."""
    n = len({t.group for t in rows})
    filler = tuple(
        tx("add", 9000 + 100 * tag + i, 99, when, n + i) for i in range(mv.PAGE_TRANSACTIONS - n)
    )
    return (*filler, *rows)


# --------------------------------------------------------------------------- the count
def test_an_older_read_covers_the_start_the_newest_no_longer_reaches():
    team, newest, older = case("wrapped")
    assert mv.adds_used(newest, team, START, END, TODAY) == mv.AddsUsed(3, False)
    assert mv.adds_used(newest, team, START, END, TODAY, older) == mv.AddsUsed(4, True)
    # Each add once, however many reads list it: the newest listed again changes nothing.
    assert mv.adds_used(newest, team, START, END, TODAY, (newest, *older)) == mv.AddsUsed(4, True)


def test_a_week_no_read_covers_stays_a_floor_until_one_does():
    team, newest, older = case("short")
    assert older == ()
    assert mv.adds_used(newest, team, START, END, TODAY) == mv.AddsUsed(4, False)
    covering = read(FIXTURE["cases"]["short"]["covering"])
    assert mv.adds_used(newest, team, START, END, TODAY, (covering,)) == mv.AddsUsed(4, True)


def test_a_read_with_a_gap_between_it_and_the_newer_ones_never_joins():
    # The newest read starts Wednesday; the older one ends Monday: what came between is unread.
    newest = page(
        1,
        "Nov 12, 4:00 am",
        tx("add", 103, 4, "Nov 12, 4:00 am", 0),
        tx("add", 102, 4, "Nov 11, 4:00 am", 1),
    )
    old = page(
        2,
        "Nov 9, 4:00 am",
        tx("add", 101, 4, "Nov 9, 4:00 am", 0),
        tx("add", 100, 4, "Nov 8, 4:00 am", 1),
    )
    assert mv.adds_used(newest, 4, START, END, TODAY, (old,)) == mv.AddsUsed(2, False)
    # A read between them that shares a transaction with each joins all three.
    middle = page(
        3,
        "Nov 11, 4:00 am",
        tx("add", 102, 4, "Nov 11, 4:00 am", 0),
        tx("add", 101, 4, "Nov 9, 4:00 am", 1),
    )
    assert mv.adds_used(newest, 4, START, END, TODAY, (middle, old)) == mv.AddsUsed(3, True)


def test_a_transaction_is_its_rows_not_its_place_on_the_page():
    # The same add and drop at another place on an older page is one transaction; another
    # team's add of the same player at the same time is another.
    newest = page(
        1,
        "Nov 10, 4:00 am",
        tx("add", 101, 4, "Nov 10, 4:00 am", 0),
        tx("drop", 201, 4, "Nov 10, 4:00 am", 0),
    )
    old = page(
        2,
        "Nov 9, 4:00 am",
        tx("add", 301, 9, "Nov 8, 4:00 am", 0),
        tx("add", 101, 4, "Nov 10, 4:00 am", 1),
        tx("drop", 201, 4, "Nov 10, 4:00 am", 1),
        tx("add", 102, 4, "Nov 9, 4:00 am", 2),
    )
    assert mv.adds_used(newest, 4, START, END, TODAY, (old,)) == mv.AddsUsed(2, True)
    assert mv.adds_used(newest, 9, START, END, TODAY, (old,)) == mv.AddsUsed(0, True)


def test_no_transactions_at_all_is_a_complete_zero():
    assert mv.adds_used((), 4, START, END, TODAY) == mv.AddsUsed(0, True)


def test_a_read_shorter_than_a_page_is_the_leagues_whole_list():
    # Fewer than 25 transactions, none before the week: the league has made no other.
    short = (tx("add", 101, 4, "Nov 10, 4:00 am", 0), tx("add", 102, 9, "Nov 11, 4:00 am", 1))
    assert mv.adds_used(short, 4, START, END, TODAY) == mv.AddsUsed(1, True)
    # A full page starting at the same time is a floor.
    full = page(1, "Nov 11, 4:00 am", *short)
    assert mv.adds_used(full, 4, START, END, TODAY) == mv.AddsUsed(1, False)


# --------------------------------------------------------------------------- the stored reads
def snapshot(folder: Path, stamp: str, at: datetime | None, rows=(), source="public") -> None:
    parts = (
        {}
        if at is None
        else {"transactions": {"fetched_at": at.isoformat(), "data": {"rows": rows}}}
    )
    (folder / f"{stamp}-{source}.json").write_text(json.dumps({"parts": parts}))


def test_the_stored_reads_are_the_weeks_newest_first(tmp_path):
    folder = season_reads.snapshots_dir(tmp_path, "900001")
    folder.mkdir(parents=True)
    row = tx("add", 101, 4, "Nov 10, 4:00 am").to_dict()
    snapshot(folder, "20261110T110000000000Z", datetime(2026, 11, 10, 11, tzinfo=UTC), [row])
    snapshot(folder, "20261112T110000000000Z", datetime(2026, 11, 12, 11, tzinfo=UTC), [row, row])
    # The Sunday evening read (Eastern) of the day before the week joins; Saturday's does not.
    snapshot(folder, "20261109T030000000000Z", datetime(2026, 11, 9, 3, tzinfo=UTC), [])
    snapshot(folder, "20261108T030000000000Z", datetime(2026, 11, 8, 3, tzinfo=UTC), [row])
    snapshot(folder, "20261111T110000000000Z", None, source="extension")  # no transactions
    (folder / "20261111T120000000000Z-public.json").write_text("{not json")
    reads = season_reads.older_reads(tmp_path, "900001", START)
    assert [len(r) for r in reads] == [2, 1, 0]
    assert reads[1][0].player.yahoo_id == 101
    assert season_reads.older_reads(tmp_path, "900002", START) == ()


def test_the_solves_limits_count_the_stored_reads(tmp_path):
    team, newest, older = case("wrapped")
    folder = season_reads.snapshots_dir(tmp_path, "900001")
    folder.mkdir(parents=True)
    for i, r in enumerate(reversed(older)):
        at = datetime(2026, 11, 11 + i, 11, tzinfo=UTC)
        snapshot(folder, at.strftime("%Y%m%dT%H%M%S000000Z"), at, [t.to_dict() for t in r])
    season = SimpleNamespace(
        settings=SimpleNamespace(league="900001", max_weekly_adds=4), transactions=newest
    )
    ahead = [SimpleNamespace(week=SimpleNamespace(start=START, end=END))]
    used, limits = season_moves.add_limits(season, team, ahead, TODAY)
    assert (used, limits[0].adds) == (mv.AddsUsed(3, False), 1)
    used, limits = season_moves.add_limits(season, team, ahead, TODAY, tmp_path)
    assert (used, limits[0].adds) == (mv.AddsUsed(4, True), 0)


def test_the_league_lists_adds_count_the_stored_reads():
    team, newest, older = case("wrapped")
    season = SimpleNamespace(
        settings=SimpleNamespace(my_team_id=team, max_weekly_adds=4, uses_faab=True, num_teams=12),
        teams=(),
        transactions=newest,
        current=lambda today: SimpleNamespace(start=START, end=END),
    )
    floor = season_queue.funds(season, [], TODAY)["adds"]
    assert (floor["used"], floor["complete"], floor["left"]) == (3, False, 1)
    full = season_queue.funds(season, [], TODAY, older)["adds"]
    assert (full["used"], full["complete"], full["left"]) == (4, True, 0)


# --------------------------------------------------------------------------- the hold
def adds(complete, limit=4):
    weeks = [
        {"start": str(WEEK[0]), "end": str(WEEK[1]), "adds": 1},
        {"start": str(NEXT[0]), "end": str(NEXT[1]), "adds": 4},
    ]
    return {"limit": limit, "used": 3, "complete": complete, "left": 1, "weeks": weeks}


def test_a_week_counted_only_as_a_floor_is_unread():
    assert season_queue.unread_weeks(adds(False)) == {WEEK}
    assert season_queue.unread_weeks(adds(True)) == frozenset()
    # No weekly limit, an entry logged before the count said, or none at all: nothing held.
    assert season_queue.unread_weeks(adds(False, limit=None)) == frozenset()
    assert season_queue.unread_weeks({**adds(True), "complete": None}) == frozenset()
    assert season_queue.unread_weeks(None) == frozenset()


def test_the_unread_weeks_adds_are_held_on_the_queue_and_the_next_weeks_are_not():
    e = entry(
        move(101, 201, 0.9, frm=str(START.replace(day=14))),
        move(102, 202, 0.8, frm=str(NEXT[0])),
    )
    left = {WEEK: 1, NEXT: 4}
    day = league_day(e, adds_left=left, unread=season_queue.unread_weeks(adds(False)))
    out = qa.queue_of(day, TODAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, qa.ADDS_UNREAD, None), (102, None, 1)]
    assert [x["queued"] for x in out] == [False, True]
    # Read in full, the same week's add is queued.
    day = league_day(e, adds_left=left, unread=season_queue.unread_weeks(adds(True)))
    assert reasons(qa.queue_of(day, TODAY, PLAN, TYPICAL, None)) == [(101, None, 1), (102, None, 2)]


def test_the_build_holds_the_adds_of_a_week_its_solve_counted_only_as_a_floor(client):
    q = queued(client)
    was = {e["id"] for e in q["entries"] if e["queued"]}
    assert was
    path = client.data_dir / "leagues" / LEAGUE / "season" / "decisions" / "2026-10-21.json"
    [logged] = json.loads(path.read_text())
    assert logged["adds"]["limit"] is not None and logged["adds"]["complete"] is True
    first = logged["adds"]["weeks"][0]
    path.write_text(json.dumps([{**logged, "adds": {**logged["adds"], "complete": False}}]))
    q = client.post("/autopilot/queue/build").json()
    week = [e for e in q["entries"] if e["id"] in was]
    assert all(first["start"] <= e["from"] <= first["end"] for e in week)
    assert all(e["reason"] == qa.ADDS_UNREAD and not e["queued"] for e in week)
