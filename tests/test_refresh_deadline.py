"""A public refresh's deadline (#166): a refresh past it ends failed with the step, the page and
the time it ran, logged, and the next one starts; a stalled read cannot keep the job running;
one job runs at a time per league, waiting callers sharing it. The league is the season tests'
fixture, Yahoo faked."""

from __future__ import annotations

import json
import threading
import time

import pytest

from pickandroll.api import seasons as season_api
from pickandroll.api.season_status import REFRESHES
from pickandroll.api.seasons import season_dir
from pickandroll.season import status as st
from tests.test_season import LEAGUE, season_client


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def logged(client) -> list[dict]:
    log = season_dir(client.data_dir, LEAGUE) / REFRESHES
    return [json.loads(x) for x in log.read_text().splitlines()]


def slow_players(client, seconds: float) -> None:
    """Yahoo's players pages answer after ``seconds``; everything else as the fake has it."""
    fake = client.fake

    def fetch(url: str) -> str:
        if "/players" in url:
            time.sleep(seconds)
        return fake(url)

    client.app.state.seasons.fetch_factory = lambda: fetch


def test_a_refresh_past_its_deadline_ends_failed_with_where_it_was_and_the_next_one_starts(
    client, monkeypatch
):
    monkeypatch.setattr(season_api, "REFRESH_DEADLINE", 0.2)
    slow_players(client, 0.3)
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 502
    error = r.json()["detail"]
    assert error.startswith("past the 0.2-second deadline after ")
    # The step it was on and the last page it read: a slow players page, then the next read.
    assert ": at " in error and ", reading " in error and "/players" in error
    job = client.app.state.seasons.jobs[LEAGUE]
    assert (job.status, job.error, job.deadline) == ("failed", error, 0.2)
    assert job.finished_at is not None
    # Logged: its start, then its end with the reason; nothing saved from the job.
    assert [(x["status"], x["error"]) for x in logged(client)] == [
        ("running", None),
        ("failed", error),
    ]
    assert not (season_dir(client.data_dir, LEAGUE) / "state.json").exists()
    # The freshness light reads it failed, with the reason.
    row = client.get("/seasons/status").json()["leagues"][0]["yahoo"]["rows"][0]
    assert (row["status"], row["state"], row["reason"]) == ("failed", st.RED, "refresh failed")
    assert row["error"] == error
    # The next refresh starts, a new job, and lands within the deadline.
    monkeypatch.setattr(season_api, "REFRESH_DEADLINE", 300.0)
    client.app.state.seasons.fetch_factory = lambda: client.fake
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202 and r.json()["refresh"]["status"] == "done"
    assert client.app.state.seasons.jobs[LEAGUE] is not job


def test_a_read_that_stalls_past_the_deadline_cannot_keep_the_job_running(client, monkeypatch):
    """The worker is stuck in a read: the waiting caller ends the job at the deadline and the
    next refresh can start; the read, once it returns, ends nothing more."""
    monkeypatch.setattr(season_api, "REFRESH_DEADLINE", 0.2)
    release, entered = threading.Event(), threading.Event()
    fake = client.fake

    def stuck(url: str) -> str:
        if "/players" in url and not release.is_set():
            entered.set()
            release.wait(10)
        return fake(url)

    service = client.app.state.seasons
    service.fetch_factory = lambda: stuck
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert entered.is_set() and r.status_code == 502
    job = service.jobs[LEAGUE]
    assert job.status == "failed" and "reading" in job.error and "/players" in job.error
    ended, error = job.finished_at, job.error
    # A new refresh does not wait for the stuck one: it starts its own job.
    monkeypatch.setattr(season_api, "REFRESH_DEADLINE", 300.0)
    service.fetch_factory = lambda: fake
    started = service.start_refresh(LEAGUE)
    assert started is not job
    assert started.wait(30) and started.status == "done"
    # The stuck read returns: the old job's worker stops at its next check and logs nothing.
    release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and any(
        t.name == f"season-{LEAGUE}" for t in threading.enumerate()
    ):
        time.sleep(0.05)
    assert (job.status, job.error, job.finished_at) == ("failed", error, ended)
    assert [x["status"] for x in logged(client)] == ["running", "failed", "running", "done"]


def test_a_refresh_under_its_deadline_is_unchanged(client):
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202
    refresh = r.json()["refresh"]
    assert (refresh["status"], refresh["step"], refresh["error"]) == ("done", "done", None)
    job = client.app.state.seasons.jobs[LEAGUE]
    assert job.deadline == season_api.REFRESH_DEADLINE == 300.0 and not job.overdue()
    assert job.page is not None
    assert [x["status"] for x in logged(client)] == ["running", "done"]


def test_two_waiting_callers_share_one_job(client):
    """The wait path goes through the service's guard: a second caller while the first's job
    runs waits on that job instead of running another refresh beside it."""
    release, entered = threading.Event(), threading.Event()
    fake = client.fake
    factories = []

    def held(url: str) -> str:
        if "/players" in url and not release.is_set():
            entered.set()
            release.wait(10)
        return fake(url)

    def factory():
        factories.append(1)
        return held

    service = client.app.state.seasons
    service.fetch_factory = factory
    answers: dict[str, object] = {}

    def post(name: str) -> None:
        answers[name] = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})

    first = threading.Thread(target=post, args=("first",))
    first.start()
    assert entered.wait(10)
    job = service.jobs[LEAGUE]
    second = threading.Thread(target=post, args=("second",))
    second.start()
    time.sleep(0.3)
    # Still one job, the first's, and the second caller waiting on it.
    assert service.jobs[LEAGUE] is job and job.status == "running"
    release.set()
    first.join(30)
    second.join(30)
    assert answers["first"].status_code == answers["second"].status_code == 202
    a, b = (answers[k].json()["refresh"] for k in ("first", "second"))
    assert a == b and a["status"] == "done"
    # One refresh read the league: one fetch made, one start and one end logged.
    assert len(factories) == 1
    assert [x["status"] for x in logged(client)] == ["running", "done"]


def test_the_status_light_reads_a_job_past_its_deadline_failed(client, monkeypatch):
    """A job still running past its deadline, its worker gone quiet: the light's read ends it."""
    service = client.app.state.seasons
    job = season_api.RefreshJob(LEAGUE, deadline=0.0)
    service.jobs[LEAGUE] = job
    time.sleep(0.01)
    row = client.get("/seasons/status").json()["leagues"][0]["yahoo"]["rows"][0]
    assert (row["status"], row["state"], row["reason"]) == ("failed", st.RED, "refresh failed")
    assert row["error"].startswith("past the 0-second deadline after 0 s: at starting")
    assert job.status == "failed" and job.finished_at is not None
    assert [x["status"] for x in logged(client)] == ["failed"]
    # A job without a deadline (a private league's extras) is never ended by it.
    quiet = season_api.RefreshJob(LEAGUE)
    service.jobs[LEAGUE] = quiet
    service.expire(quiet)
    assert quiet.status == "running" and not quiet.overdue()
