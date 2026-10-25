"""Yahoo's rate limit (#180): the reader paces every Yahoo read in the process, backs off and
retries a page that answers HTTP 999 or 429, then gives up and cools off; a refresh the limit
ends answers 503 with a Retry-After, keeps the pages it read, and the next refresh resumes at
the page it stopped on. The transport, the clock and the sleep are faked: nothing here reads
Yahoo."""

from __future__ import annotations

import json
import urllib.error
from datetime import timedelta
from email.message import Message

import pytest

from pickandroll.api import seasons as season_api
from pickandroll.api.season_status import REFRESHES
from pickandroll.api.seasons import RefreshJob, load_parts, season_dir
from pickandroll.season import status as st
from pickandroll.sources.yahoo import public
from tests.test_season import LEAGUE, NOW, season_client

PAGE = f"{public.SITE}/{LEAGUE}/players?count=0"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261021"


class Clock:
    """A monotonic clock its sleeps move, each sleep recorded."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class Page:
    def __init__(self, text: str) -> None:
        self.text, self.headers = text, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self.text.encode()


class Answers:
    """An opener answering each request with the next of ``codes`` (200: a page), the last
    one again once they run out; a rate limit carries ``retry_after`` when given."""

    def __init__(self, *codes: int, retry_after: int | None = None, pages=None) -> None:
        self.codes, self.retry_after, self.pages = list(codes), retry_after, pages
        self.urls: list[str] = []

    def open(self, req, timeout=None):
        url = req.full_url
        self.urls.append(url)
        code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
        if code == 200:
            return Page(self.pages(url) if self.pages else f"<html>{len(self.urls)}</html>")
        headers = Message()
        if self.retry_after is not None:
            headers["Retry-After"] = str(self.retry_after)
        raise urllib.error.HTTPError(url, code, "limited", headers, None)


def reader(*codes: int, **kw) -> tuple[public.HttpFetch, Answers, Clock, public.Pacer]:
    clock = Clock()
    pacer = public.Pacer(clock=clock, sleep=clock.sleep)
    answers = Answers(*codes, **kw)
    return public.HttpFetch(pacer=pacer, sleep=clock.sleep, opener=answers), answers, clock, pacer


# ---------------------------------------------------------------- the reader
def test_a_page_rate_limited_once_is_read_again_after_a_minute():
    fetch, answers, clock, pacer = reader(999, 200)
    assert fetch(PAGE) == "<html>2</html>"
    assert answers.urls == [PAGE, PAGE] and clock.slept == [60.0]
    assert pacer.left() is None


def test_a_page_rate_limited_every_time_gives_up_after_two_waits_and_the_process_cools_off():
    fetch, answers, clock, pacer = reader(999)
    with pytest.raises(public.RateLimited) as caught:
        fetch(PAGE)
    exc = caught.value
    assert clock.slept == [60.0, 120.0] and answers.urls == [PAGE] * 3
    assert (exc.status, exc.retry_after, exc.cooling) == (999, 900.0, False)
    assert str(exc) == (
        f"{PAGE}: rate limited by Yahoo (HTTP 999) after 3 reads; Yahoo's reads paused for 15 min"
    )
    # Every Yahoo read of the process is refused, without a request, until the cool-off ends.
    other = public.HttpFetch(pacer=pacer, sleep=clock.sleep, opener=answers)
    with pytest.raises(public.RateLimited) as caught:
        other(f"{public.PUB_API}/settings/nba/{LEAGUE}?format=json")
    assert caught.value.cooling and caught.value.retry_after == 900.0
    assert "its reads paused for another 15 min" in str(caught.value)
    assert len(answers.urls) == 3
    clock.t += 900.0
    answers.codes = [200]
    assert fetch(PAGE) == "<html>4</html>"


def test_429_is_the_limit_too_and_yahoos_retry_after_lengthens_the_cool_off():
    fetch, _, _, pacer = reader(429, retry_after=1800)
    with pytest.raises(public.RateLimited) as caught:
        fetch(PAGE)
    assert (caught.value.status, caught.value.retry_after) == (429, 1800.0)
    assert pacer.left() == 1800.0


def test_a_wait_the_caller_refuses_gives_up_at_once():
    fetch, answers, clock, pacer = reader(999, 200)
    fetch.may_wait = lambda seconds: False
    with pytest.raises(public.RateLimited, match="after 1 reads"):
        fetch(PAGE)
    assert clock.slept == [] and answers.urls == [PAGE] and pacer.left() == 900.0


def test_a_refresh_job_waits_only_inside_its_deadline():
    job = RefreshJob(LEAGUE, deadline=300.0)
    assert job.may_wait(60.0) and job.may_wait(120.0)
    assert not job.may_wait(300.0 - season_api.WAIT_MARGIN + 1)
    assert RefreshJob(LEAGUE).may_wait(10_000.0)
    fetch = public.HttpFetch()
    assert public.bounded(fetch, job.may_wait) is fetch and fetch.may_wait == job.may_wait


def test_yahoo_reads_are_one_at_a_time_a_second_apart_across_readers():
    fetch, answers, clock, pacer = reader(200)
    other = public.HttpFetch(pacer=pacer, sleep=clock.sleep, opener=answers)
    fetch(PAGE)
    other(PAGE)
    fetch(PAGE)
    assert clock.slept == [public.YAHOO_INTERVAL] * 2


def test_another_host_keeps_its_own_pace_and_never_waits_on_yahoos_limit():
    fetch, answers, clock, pacer = reader(429)
    with pytest.raises(public.FetchError) as caught:
        fetch(ESPN)
    assert not isinstance(caught.value, public.RateLimited) and str(caught.value) == (
        f"{ESPN}: HTTP 429"
    )
    assert pacer.left() is None and clock.slept == []
    # During Yahoo's cool-off, ESPN is read.
    pacer.give_up(public.RateLimited("x", status=999), 3)
    answers.codes = [200]
    assert fetch(ESPN).startswith("<html>")


def test_an_unpaced_fetch_is_never_refused_nor_waits_and_starts_no_cool_off():
    fetch, answers, clock, pacer = reader(999)
    loose = fetch.unpaced()
    assert (loose.pacer, loose.backoff) == (None, ())
    with pytest.raises(public.RateLimited):
        loose(PAGE)
    assert answers.urls == [PAGE] and clock.slept == [] and pacer.left() is None
    pacer.give_up(public.RateLimited("x", status=999), 3)
    answers.codes = [200]
    assert loose(PAGE).startswith("<html>")

    def plain(url: str) -> str:
        return url

    assert public.unpaced(plain) is plain


# ---------------------------------------------------------------- the refresh
@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        c.now = NOW  # type: ignore[attr-defined]
        c.app.state.seasons.clock = lambda: c.now
        yield c


class LimitedAt:
    """The fake Yahoo, whose ``at``-th Yahoo read answers the rate limit (``cooling``: the
    process's cool-off), the reads before it recorded."""

    def __init__(self, fake, at: int, cooling: bool = False) -> None:
        self.fake, self.at, self.cooling = fake, at, cooling
        self.yahoo: list[str] = []

    def __call__(self, url: str) -> str:
        if public.is_yahoo(url):
            self.yahoo.append(url)
            if len(self.yahoo) == self.at:
                if self.cooling:
                    raise public.RateLimited(
                        f"{url}: rate limited by Yahoo, its reads paused for another 9 min",
                        retry_after=540.0,
                        cooling=True,
                    )
                raise public.RateLimited(
                    f"{url}: rate limited by Yahoo (HTTP 999) after 3 reads",
                    status=999,
                    retry_after=900.0,
                )
        return self.fake(url)


def refresh(client):
    return client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})


def logged(client) -> list[dict]:
    log = season_dir(client.data_dir, LEAGUE) / REFRESHES
    return [json.loads(x) for x in log.read_text().splitlines()]


def test_a_refresh_the_limit_stops_answers_503_and_the_next_resumes_at_that_page(client):
    service = client.app.state.seasons
    limited = LimitedAt(client.fake, at=6)
    service.fetch_factory = lambda: limited
    r = refresh(client)
    assert r.status_code == 503 and r.headers["Retry-After"] == "900"
    error = r.json()["detail"]
    # Settings, the settings page, the pool, the league page and team 1 read; team 2 stopped.
    assert error.startswith("rate limited by Yahoo (HTTP 999) at team 1 5/")
    assert "; 5 pages held until " in error and error.endswith("; read again in 15 min")
    job = service.jobs[LEAGUE]
    assert (job.status, job.rate_limited, job.retry_after, job.held, job.resumed) == (
        "failed",
        True,
        900.0,
        5,
        0,
    )
    assert job.page == limited.yahoo[5] and "/2" in job.page
    end = logged(client)[-1]
    assert (end["rate_limited"], end["held"], end["page"], end["retry_after"]) == (
        True,
        5,
        job.page,
        900.0,
    )
    # Nothing saved from a half-read.
    assert not (season_dir(client.data_dir, LEAGUE) / "state.json").exists()
    row = client.get("/seasons/status").json()["leagues"][0]["yahoo"]["rows"][0]
    assert (row["state"], row["reason"], row["error"]) == (st.RED, "rate limited by Yahoo", error)

    # Twenty minutes on, the limit lifted: the five pages come from the hold, the rest is read.
    client.now = NOW + timedelta(minutes=20)
    client.fake.urls.clear()
    service.fetch_factory = lambda: client.fake
    r = refresh(client)
    assert r.status_code == 202, r.text
    done = r.json()["refresh"]
    assert (done["status"], done["resumed"], done["held"], done["rate_limited"]) == (
        "done",
        5,
        0,
        False,
    )
    assert not set(limited.yahoo[:5]) & set(client.fake.urls)
    assert limited.yahoo[5] in client.fake.urls
    assert LEAGUE not in service.held
    # Each part carries its own page's read time; the summary is the completing refresh's.
    parts = load_parts(client.data_dir, LEAGUE)
    for key in ("settings", "league_settings", "players", "league", "roster/1"):
        assert parts[key].fetched_at == NOW, key
    for key in ("roster/2", "available", "transactions"):
        assert parts[key].fetched_at == client.now, key
    assert r.json()["season"]["updated_at"] == client.now.isoformat()


def test_a_refresh_during_the_cool_off_keeps_the_hold(client):
    service = client.app.state.seasons
    service.fetch_factory = lambda: LimitedAt(client.fake, at=6)
    assert refresh(client).status_code == 503
    cooling = LimitedAt(client.fake, at=1, cooling=True)
    service.fetch_factory = lambda: cooling
    r = refresh(client)
    assert r.status_code == 503 and r.headers["Retry-After"] == "540"
    # The hold's pages are served, so the cool-off meets the first page not held.
    assert r.json()["detail"].startswith("rate limited by Yahoo (its reads paused) at team 1 5/")
    assert service.jobs[LEAGUE].held == 5 and service.jobs[LEAGUE].resumed == 5
    service.fetch_factory = lambda: client.fake
    assert refresh(client).json()["refresh"]["resumed"] == 5


def test_the_hold_is_dropped_after_an_hour_or_another_failure(client):
    service = client.app.state.seasons
    service.fetch_factory = lambda: LimitedAt(client.fake, at=6)
    assert refresh(client).status_code == 503
    client.now = NOW + timedelta(minutes=61)
    service.fetch_factory = lambda: client.fake
    assert refresh(client).json()["refresh"]["resumed"] == 0

    service.fetch_factory = lambda: LimitedAt(client.fake, at=6)
    assert refresh(client).status_code == 503
    fake = client.fake

    def broken(url: str) -> str:
        if "/transactions" in url:
            raise public.FetchError(f"{url}: HTTP 500")
        return fake(url)

    service.fetch_factory = lambda: broken
    r = refresh(client)
    assert r.status_code == 502 and r.json()["detail"].endswith("HTTP 500")
    assert service.jobs[LEAGUE].rate_limited is False and LEAGUE not in service.held
    service.fetch_factory = lambda: client.fake
    assert refresh(client).json()["refresh"]["resumed"] == 0


def test_a_refresh_never_limited_reports_nothing_held(client):
    r = refresh(client)
    assert r.status_code == 202
    out = r.json()["refresh"]
    assert (out["rate_limited"], out["retry_after"], out["held"], out["resumed"]) == (
        False,
        None,
        0,
        0,
    )
    assert client.app.state.seasons.held == {}


def test_the_extensions_page_posts_read_outside_the_pacer(client, monkeypatch):
    """A private league's extras (started by the extension's page posts) read Yahoo's buzz page
    even while the public refreshes' cool-off refuses every paced read."""
    clock = Clock()
    pacer = public.Pacer(clock=clock, sleep=clock.sleep)
    pacer.give_up(public.RateLimited("x", status=999), 3)
    answers = Answers(200, pages=client.fake)
    service = client.app.state.seasons
    service.fetch_factory = lambda: public.HttpFetch(
        pacer=pacer, sleep=lambda s: None, opener=answers
    )
    job = RefreshJob("100002", step="schedule")
    service.run_extras(job)
    assert job.status == "done", job.error
    assert any("/buzzindex?" in u for u in answers.urls)
    assert "flag inputs" not in job.warnings
