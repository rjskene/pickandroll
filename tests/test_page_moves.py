"""A page's look at the moves (#240): ``source=page`` answers at once, never logged, with the
league's kept answer of today marked ``stale`` while the solve of the newer inputs runs on the
page's thread, at most one a key; the routine's call (no source) waits for its solve and writes
one decision entry every call, from the kept answer with its build time when it did not solve.

The league is the season tests' made-up one; nothing here is from Basketball Monster.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest

from pickandroll.api import season_moves, seasons
from tests.test_decisions import SITE, logged, snapshot
from tests.test_season import LEAGUE, NOW, fixture, season_client, strategy_league

MOVES = f"/seasons/{LEAGUE}/moves"
PAGE = {"source": "page"}


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        strategy_league(c)
        yield c


class Later:
    """The page's thread, held: each solve submitted waits until ``run``."""

    def __init__(self) -> None:
        self.jobs: list = []

    def submit(self, fn):
        self.jobs.append(fn)

    def run(self) -> None:
        jobs, self.jobs = self.jobs, []
        for fn in jobs:
            fn()


def solves(monkeypatch) -> list[int]:
    """Count the moves solves (``season_moves.moves_payload``)."""
    made: list[int] = []
    real = season_moves.moves_payload

    def counted(built):
        made.append(1)
        return real(built)

    monkeypatch.setattr(season_moves, "moves_payload", counted)
    return made


def new_inputs(client, at: datetime) -> None:
    client.app.state.seasons.clock = lambda: at
    snapshot(client, LEAGUE, f"{SITE}/{LEAGUE}/transactions", fixture("transactions.html"))


def test_a_page_look_is_never_logged_and_the_routines_call_logs_from_its_answer(
    client, monkeypatch
):
    made = solves(monkeypatch)
    page = client.get(MOVES, params=PAGE)
    assert page.status_code == 200, page.text
    # Nothing kept yet: the page waits for the solve, and logs nothing.
    assert "stale" not in page.json() and len(made) == 1 and logged(client) == []
    # The routine's call after it: no new solve, one entry from that answer, with its build time.
    later = NOW + timedelta(minutes=2)
    client.app.state.seasons.clock = lambda: later
    routine = client.get(MOVES).json()
    assert routine == page.json() and len(made) == 1
    [e] = logged(client)
    assert (e["at"], e["built_at"], e["source"]) == (later.isoformat(), NOW.isoformat(), "moves")
    # One entry every routine call, never two.
    client.get(MOVES)
    assert len(logged(client)) == 2 and len(made) == 1
    # A page look still logs nothing.
    client.get(MOVES, params=PAGE)
    assert len(logged(client)) == 2
    assert client.get(MOVES, params={"source": "routine"}).status_code == 422


def test_a_page_look_on_newer_inputs_answers_the_kept_one_stale_while_one_solve_runs(
    client, monkeypatch
):
    made = solves(monkeypatch)
    later = Later()
    client.app.state.seasons.page_solves = later
    first = client.get(MOVES, params=PAGE).json()
    assert len(made) == 1
    at = NOW + timedelta(minutes=5)
    new_inputs(client, at)
    look = client.get(MOVES, params=PAGE).json()
    stale = look.pop("stale")
    assert look == first and len(made) == 1
    assert (stale["built_at"], stale["reason"]) == (NOW.isoformat(), seasons.STALE_REASON)
    assert stale["inputs_at"] is not None and len(later.jobs) == 1
    # A second look while it runs gets the same stale answer, not a second solve.
    again = client.get(MOVES, params=PAGE).json()
    assert again["stale"] == stale and len(later.jobs) == 1
    later.run()
    assert len(made) == 2
    fresh = client.get(MOVES, params=PAGE).json()
    assert "stale" not in fresh and len(made) == 2 and later.jobs == []
    # The page's solves logged nothing; the routine's call logs the fresh answer, built at ``at``.
    assert logged(client) == []
    client.get(MOVES)
    [e] = logged(client)
    assert e["built_at"] == at.isoformat() and len(made) == 2


def test_a_routine_call_on_newer_inputs_waits_for_its_solve_and_logs_it(client, monkeypatch):
    made = solves(monkeypatch)
    client.app.state.seasons.page_solves = Later()
    client.get(MOVES, params=PAGE)
    new_inputs(client, NOW + timedelta(minutes=5))
    # Behaves as before #240: solves the new inputs and writes that solve's entry.
    client.get(MOVES)
    [e] = logged(client)
    assert len(made) == 2 and "built_at" not in e


def test_a_page_look_with_no_answer_of_today_waits_for_the_solve(client, monkeypatch):
    made = solves(monkeypatch)
    later = Later()
    client.app.state.seasons.page_solves = later
    client.get(MOVES, params=PAGE)
    # The next day: yesterday's answer is never shown for today's.
    tomorrow = NOW + timedelta(days=1)
    client.app.state.seasons.clock = lambda: tomorrow
    look = client.get(MOVES, params=PAGE).json()
    assert "stale" not in look and len(made) == 2 and later.jobs == []


def test_a_page_solve_that_fails_leaves_the_next_look_to_try_again(client, monkeypatch):
    later = Later()
    client.app.state.seasons.page_solves = later
    client.get(MOVES, params=PAGE)
    new_inputs(client, NOW + timedelta(minutes=5))
    real = season_moves.moves_payload

    def broken(built):
        raise RuntimeError("no")

    monkeypatch.setattr(season_moves, "moves_payload", broken)
    assert "stale" in client.get(MOVES, params=PAGE).json()
    later.run()
    monkeypatch.setattr(season_moves, "moves_payload", real)
    assert "stale" in client.get(MOVES, params=PAGE).json() and len(later.jobs) == 1
    later.run()
    assert "stale" not in client.get(MOVES, params=PAGE).json()


def test_two_callers_of_one_key_wait_on_one_solve_and_log_one_entry(client, monkeypatch):
    service = client.app.state.seasons
    started, go = threading.Event(), threading.Event()
    made: list[int] = []
    real = season_moves.moves_payload

    def slow(built):
        made.append(1)
        started.set()
        assert go.wait(10)
        return real(built)

    monkeypatch.setattr(season_moves, "moves_payload", slow)
    out: list[dict] = []
    threads = [
        threading.Thread(target=lambda: out.append(service.moves(LEAGUE, None))) for _ in range(2)
    ]
    threads[0].start()
    assert started.wait(10)
    threads[1].start()
    go.set()
    for t in threads:
        t.join(10)
    assert len(made) == 1 and len(out) == 2 and out[0] is out[1]
    assert len(logged(client)) == 1
