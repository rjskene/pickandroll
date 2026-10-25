"""Yahoo's public sources for a public league (the prize leagues), read without a session.

Yahoo's Fantasy API still refuses the app (docs/ADD_DROP.md, "Inputs"), so a season is read from
what Yahoo serves to anyone for a public league:

* the v3 JSON endpoints ``settings`` and ``players`` (``pub-api.fantasysports.yahoo.com``);
* the league's pages on ``basketball.fantasysports.yahoo.com``, parsed in :mod:`.pages`, the
  settings page among them for the held slots and the lineup deadline v3 leaves out (#107).

For a private league both answer with nothing; that league's pages come from the extension.
Nothing here signs in, sends a cookie or acts on the league.
"""

from __future__ import annotations

import gzip
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from ...season.state import (
    PUBLIC,
    YAHOO_WEEK,
    Part,
    SeasonSettings,
    lineup_key,
    matchup_key,
    pairings_key,
    roster_key,
)
from . import pages

PUB_API = "https://pub-api.fantasysports.yahoo.com/fantasy/v3"
SITE = pages.SITE
#: Yahoo serves its full league pages to a browser.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0 Safari/537.36"
)
PAGE_ROWS = 25
#: Available players read per refresh, most rostered first (the players page's 25-row pages).
MAX_AVAILABLE = 300
#: The players page view whose columns carry percent rostered and started with the day's
#: change, adds and drops ("Research").
OWNERSHIP_VIEW = "R_O"


#: Yahoo's hosts, the ones its rate limit covers (#180): the pacer, the backoff and the cool-off
#: are for these alone.
YAHOO_HOSTS = ("yahoo.com",)
#: The statuses Yahoo answers when it rate limits: its own 999 and the standard 429.
RATE_LIMIT_STATUSES = (999, 429)
#: The seconds between two Yahoo reads in this process, from the end of one to the start of the
#: next (#180; 0.3 s each until 2026-10-25, which tripped the limit at about 95 pages a minute).
YAHOO_INTERVAL = 1.0
#: The waits before each retry of a rate-limited page: a minute, then doubled once.
BACKOFF = (60.0, 120.0)
#: How long every Yahoo read in this process is refused after a page gave up on the limit.
COOL_OFF = 15 * 60.0


class FetchError(RuntimeError):
    """A source that did not answer, or answered with an error status."""


class RateLimited(FetchError):
    """Yahoo's rate limit (#180): a page answered HTTP 999 or 429 through its retries, or this
    process is cooling off after one did and sent no request. ``retry_after`` is the seconds
    before Yahoo may be read again, as far as this process knows."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        cooling: bool = False,
    ) -> None:
        super().__init__(message)
        self.status, self.retry_after, self.cooling = status, retry_after, cooling


class PrivateLeague(RuntimeError):
    """Yahoo serves nothing public for the league: its pages come from the extension."""


class Fetch(Protocol):
    def __call__(self, url: str) -> str: ...


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """The real clock, each part's stamp by default. The season service passes its own, so a
    test that pins it stamps the parts at the pinned instant too (#121)."""
    return datetime.now(UTC)


#: The longest one address may take to accept a connection before the next is tried.
CONNECT_TIMEOUT = 5.0


def _connect_ipv4_first(address, timeout=None, source_address=None, *args, **kwargs):
    """``socket.create_connection`` that tries IPv4 addresses first, each for at most
    :data:`CONNECT_TIMEOUT`: Yahoo resolves to IPv6 addresses first, and on a network without an
    IPv6 route urllib otherwise waits out the whole timeout on each of them (curl falls back at
    once)."""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda info: info[0] != socket.AF_INET)
    error: OSError | None = None
    for family, kind, proto, _, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(min(timeout, CONNECT_TIMEOUT) if timeout else CONNECT_TIMEOUT)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            sock.settimeout(timeout)
            return sock
        except OSError as exc:
            error = exc
            sock.close()
    raise error or OSError(f"no address for {host}")


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # http.client sets this per connection (socket.create_connection) in __init__.
        self._create_connection = _connect_ipv4_first


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


def is_yahoo(url: str) -> bool:
    """Whether ``url`` is on one of :data:`YAHOO_HOSTS`."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in YAHOO_HOSTS)


def _minutes(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))} min"


class Pacer:
    """The pace of every Yahoo read in this process and the cool-off after its rate limit
    (#180). Yahoo answered HTTP 999 once about 380 pages had been read in four minutes
    (2026-10-24 and 10-25, 05:18 on the Mac's clock, twelve leagues back to back); an
    immediate retry failed the same way and a read three and a half hours later worked. So
    reads go one at a time, :data:`YAHOO_INTERVAL` apart, and once a page gives up on the limit
    every read is refused for :data:`COOL_OFF` without a request.

    One pacer serves the process (:data:`YAHOO`): the daily refreshes, the 15:00 pass and the
    Monday recorder all read through the API, so the pace holds across them. Its state is in
    memory only, never on disk: an API restart starts with no wait and no cool-off."""

    def __init__(
        self,
        interval: float = YAHOO_INTERVAL,
        cool_off: float = COOL_OFF,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval, self.cool_off, self.clock, self.sleep = interval, cool_off, clock, sleep
        self._lock = threading.Lock()
        self._last: float | None = None
        self._until: float | None = None

    def left(self) -> float | None:
        """The seconds of the cool-off left, None when there is none."""
        if self._until is None:
            return None
        left = self._until - self.clock()
        return left if left > 0 else None

    def read(self, url: str, get: Callable[[], str]) -> str:
        """``get()``, the read of ``url``, in its turn: one read at a time, the interval after
        the last one ended. Raises :class:`RateLimited` during the cool-off, sending nothing."""
        with self._lock:
            left = self.left()
            if left is not None:
                raise RateLimited(
                    f"{url}: rate limited by Yahoo, its reads paused for another {_minutes(left)}",
                    retry_after=left,
                    cooling=True,
                )
            if self._last is not None:
                wait = self._last + self.interval - self.clock()
                if wait > 0:
                    self.sleep(wait)
            try:
                return get()
            finally:
                self._last = self.clock()

    def give_up(self, exc: RateLimited, tries: int) -> RateLimited:
        """Start the cool-off after a page gave up on the limit (``exc``, its last answer, after
        ``tries`` reads): the error to raise."""
        with self._lock:
            wait = max(self.cool_off, exc.retry_after or 0.0)
            self._until = self.clock() + wait
        return RateLimited(
            f"{exc} after {tries} reads; Yahoo's reads paused for {_minutes(wait)}",
            status=exc.status,
            retry_after=wait,
        )


#: The process's Yahoo pacer.
YAHOO = Pacer()


class HttpFetch:
    """A plain GET with a browser User-Agent and no cookies (Yahoo's pages are a megabyte each).

    A Yahoo page goes through the process's :class:`Pacer` (``pacer``): one read at a time,
    :data:`YAHOO_INTERVAL` apart, and none during the cool-off. When Yahoo answers its rate
    limit (HTTP 999 or 429) the same page is read again after each of ``backoff``'s waits, then
    the cool-off starts and :class:`RateLimited` is raised. ``may_wait(seconds)`` may refuse a
    wait (a refresh job's deadline, #166): the read then gives up at once. Any other host, and
    a fetch made :meth:`unpaced`, keeps its own pace of one request per ``interval`` seconds and
    never waits on Yahoo's limit."""

    def __init__(
        self,
        interval: float = 0.3,
        timeout: float = 30.0,
        *,
        pacer: Pacer | None = YAHOO,
        backoff: tuple[float, ...] = BACKOFF,
        sleep: Callable[[float], None] = time.sleep,
        opener: Any = None,
    ) -> None:
        self.interval, self.timeout = interval, timeout
        self.pacer, self.backoff, self.sleep = pacer, backoff, sleep
        self.may_wait: Callable[[float], bool] = lambda seconds: True
        self._last = 0.0
        self._opener = opener or urllib.request.build_opener(_HTTPSHandler())

    def unpaced(self) -> HttpFetch:
        """This fetch outside the Yahoo pacer, its cool-off and its backoff: a rate limit is
        raised at once and starts no cool-off."""
        return HttpFetch(
            self.interval,
            self.timeout,
            pacer=None,
            backoff=(),
            sleep=self.sleep,
            opener=self._opener,
        )

    def __call__(self, url: str) -> str:
        if self.pacer is None or not is_yahoo(url):
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                self.sleep(wait)
            try:
                return self._get(url)
            finally:
                self._last = time.monotonic()
        for tries, wait in enumerate((*self.backoff, None), start=1):
            try:
                return self.pacer.read(url, lambda: self._get(url))
            except RateLimited as exc:
                if exc.cooling:
                    raise
                if wait is None or not self.may_wait(wait):
                    raise self.pacer.give_up(exc, tries) from exc
            self.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    def _get(self, url: str) -> str:
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
        except urllib.error.HTTPError as exc:
            if exc.code in RATE_LIMIT_STATUSES and is_yahoo(url):
                raise RateLimited(
                    f"{url}: rate limited by Yahoo (HTTP {exc.code})",
                    status=exc.code,
                    retry_after=_retry_after(exc.headers),
                ) from exc
            raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise FetchError(f"{url}: {exc}") from exc
        return body.decode("utf-8", errors="replace")


def _retry_after(headers: Any) -> float | None:
    """The seconds of a ``Retry-After`` header given in seconds; None otherwise."""
    value = headers.get("Retry-After") if headers is not None else None
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def bounded(fetch: Fetch, may_wait: Callable[[float], bool]) -> Fetch:
    """``fetch`` whose backoff waits only when ``may_wait`` allows (a refresh job's deadline)."""
    if isinstance(fetch, HttpFetch):
        fetch.may_wait = may_wait
    return fetch


def unpaced(fetch: Fetch) -> Fetch:
    """``fetch`` outside the Yahoo pacer and its cool-off (#180): the reads the extension's
    page posts start (a private league's extras) never wait on, nor are refused by, the daily
    refresh's limit."""
    return fetch.unpaced() if isinstance(fetch, HttpFetch) else fetch


# --------------------------------------------------------------------------- urls
def settings_url(league: str) -> str:
    return f"{PUB_API}/settings/nba/{league}?format=json"


def players_url(league: str) -> str:
    return f"{PUB_API}/players/nba/{league}?format=json&projected=1&average=1"


def league_url(league: str) -> str:
    return f"{SITE}/{league}"


def settings_page_url(league: str) -> str:
    """The league's settings page: the roster positions with the held slots and the lineup
    deadline (#107), which the v3 settings leave out."""
    return f"{SITE}/{league}/settings"


def team_url(league: str, team_id: int, day: date | None = None) -> str:
    return f"{SITE}/{league}/{team_id}" + (f"?date={day.isoformat()}" if day else "")


def available_url(league: str, offset: int, view: str = OWNERSHIP_VIEW) -> str:
    """The players page: available players (free agents and waivers), most rostered first."""
    return f"{SITE}/{league}/players?status=A&pos=P&stat1={view}&sort=R_PO&sdir=1&count={offset}"


def pairings_url(league: str, week: int) -> str:
    """The league page as shown for ``week``: that week's pairs (#116)."""
    return f"{SITE}/{league}?matchup_week={week}"


def matchup_url(league: str, week: int, teams: Iterable[int]) -> str:
    """A matchup page by its pair, or by one team (Yahoo names the opponent), in the week's
    totals view: while games are live the plain page names neither team (2026-10-22), the
    totals view both."""
    mids = "".join(f"&mid{i}={t}" for i, t in enumerate(teams, 1))
    return f"{SITE}/{league}/matchup?date=totals&week={week}{mids}"


def buzz_url(day: date) -> str:
    """Yahoo's buzz index for ``day`` (today or yesterday, US Eastern), most added first."""
    return (
        f"{SITE}/buzzindex?date={day.isoformat()}&pos=ALL&src=combined&bimtab=ALL"
        "&trendtab=O&sort=BI_A&sdir=1"
    )


def transactions_url(league: str) -> str:
    return f"{SITE}/{league}/transactions"


# --------------------------------------------------------------------------- v3 json
def settings_from_v3(body: Any) -> dict[str, Any] | None:
    """The season fields of Yahoo's public settings response, or None when Yahoo serves no
    public league under the id (private, dissolved or deleted)."""
    svc = body.get("service") if isinstance(body, dict) else None
    if not isinstance(svc, dict) or "league_id" not in svc:
        return None
    s = svc.get("settings") or {}
    return {
        "name": svc.get("name"),
        "current_week": svc.get("current_week"),
        "start_week": svc.get("start_week"),
        "end_week": svc.get("end_week"),
        "end_date": svc.get("end_date") or None,
        "weekly_deadline": svc.get("weekly_deadline") or None,
        "waiver_rule": s.get("waiver_rule"),
        "waiver_days": s.get("waiver_time"),
        "uses_faab": bool(s["uses_faab"]) if s.get("uses_faab") is not None else None,
        "max_weekly_adds": s.get("max_weekly_adds"),
        "trade_end_date": s.get("trade_end_date") or None,
        "trade_ratify": s.get("trade_ratify_type") or None,
        "trade_review_days": s.get("trade_reject_time"),
        "playoff_teams": s.get("num_playoff_teams"),
    }


def players_from_v3(body: Any) -> list[dict[str, Any]]:
    """Yahoo's player pool for the league: id, name, NBA team, positions, injury code, its words
    and the injury note."""
    svc = body.get("service") if isinstance(body, dict) else None
    rows = (svc or {}).get("player_list") or []
    out = []
    for p in rows:
        name = " ".join(x for x in (p.get("fname"), p.get("lname")) if x).strip() or p.get("name")
        if not name or p.get("id") is None:
            continue
        positions = [x for x in (p.get("display_pos") or "").split(",") if x]
        out.append(
            {
                "yahoo_id": int(p["id"]),
                "name": name,
                "nba_team": p.get("team_abbr") or None,
                "positions": positions,
                "status": p.get("inj") or None,
                "status_full": p.get("inj_full") or None,
                "note": p.get("inj_note") or None,
            }
        )
    return out


def _json(fetch: Fetch, url: str) -> Any:
    text = fetch(url)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FetchError(f"{url}: not JSON") from exc


# --------------------------------------------------------------------------- refresh
Progress = Callable[[str, int, int], None]


def refresh_parts(
    league: str,
    base: SeasonSettings,
    fetch: Fetch,
    today: date,
    *,
    max_available: int = MAX_AVAILABLE,
    progress: Progress | None = None,
    warn: Callable[[str, str], None] | None = None,
    clock: Clock = utc_now,
) -> list[Part]:
    """Every public source of a league, read once, as season parts.

    The order is settings, the player pool, the league page (standings and this week's pairs),
    every team's page, the available players most rostered first, Yahoo's projection of them
    for the next seven days, every matchup of the week (mine first) and the transactions.
    A matchup page that does not parse skips its pair (the last read stays) and is reported to
    ``warn``, never failing the rest. Raises :class:`PrivateLeague` when Yahoo serves nothing
    public for it. Each part and row is stamped with ``clock`` when it is read.
    """
    pages_needed = -(-max_available // PAGE_ROWS)
    total = 4 + base.num_teams + 2 * pages_needed + base.num_teams // 2 + 1
    done = 0

    def step(what: str) -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(what, done, total)

    def part(key: str, data: Any) -> Part:
        return Part(key, clock(), PUBLIC, data)

    out: list[Part] = []
    read = settings_from_v3(_json(fetch, settings_url(league)))
    if read is None:
        raise PrivateLeague(
            f"Yahoo serves no public league {league}: open its pages in Chrome with the extension"
        )
    out.append(part("settings", read))
    step("settings")
    # The held slots and the lineup deadline; a page that does not answer keeps the last read,
    # but the rate limit ends the read (#180).
    try:
        out.append(
            part("league_settings", pages.parse_settings_page(fetch(settings_page_url(league))))
        )
    except RateLimited:
        raise
    except (FetchError, pages.PageError):
        pass
    step("settings page")
    out.append(part("players", players_from_v3(_json(fetch, players_url(league)))))
    step("player pool")
    league_page = pages.parse_league_page(fetch(league_url(league)))
    out.append(part("league", {k: league_page[k] for k in ("name", "teams", "matchups")}))
    step("standings")
    team_ids = [t["team_id"] for t in league_page["teams"]] or list(range(1, base.num_teams + 1))
    for team_id in team_ids:
        out.append(
            part(
                roster_key(team_id),
                pages.parse_team_page(fetch(team_url(league, team_id)), team_id),
            )
        )
        step(f"team {team_id}")
    rows: list[dict[str, Any]] = []
    offsets = []
    for offset in range(0, max_available, PAGE_ROWS):
        page = pages.parse_players_page(fetch(available_url(league, offset)), today)
        rows.extend(page["rows"])
        offsets.append(offset)
        step(f"available {offset + 1}-{offset + PAGE_ROWS}")
        if len(page["rows"]) < PAGE_ROWS:
            break
    seen = clock().isoformat()
    unique = {r["player"]["yahoo_id"]: {**r, "seen_at": seen} for r in rows}
    out.append(part("available", {"rows": list(unique.values())}))
    # Yahoo's own projection of the same players for the next seven days.
    projected: dict[int, dict[str, Any]] = {}
    for offset in offsets:
        html = fetch(available_url(league, offset, pages.PROJECTION_VIEW))
        for r in pages.parse_projection_page(html)["rows"]:
            projected[r["player"]["yahoo_id"]] = {**r, "seen_at": clock().isoformat()}
        step(f"Yahoo projection {offset + 1}-{offset + PAGE_ROWS}")
    out.append(part(YAHOO_WEEK, {"rows": list(projected.values())}))
    week = read.get("current_week") or league_page.get("week")
    mine = base.my_team_id
    # Every pair of the week, mine first: the totals behind each live score.
    pairs = sorted(
        (m["teams"] for m in league_page["matchups"] if m["week"] == week),
        key=lambda t: mine not in t,
    )
    skipped: list[str] = []
    for pair in pairs if week is not None else []:
        try:
            data = pages.parse_matchup_page(fetch(matchup_url(league, int(week), pair)), int(week))
        except pages.PageError as exc:
            skipped.append(f"{pair[0]}-{pair[1]}: {exc}")
        else:
            out.append(part(matchup_key(int(week), data["teams"]), data))
        step("my matchup" if mine in pair else f"matchup {pair[0]}-{pair[1]}")
    if skipped and warn is not None:
        warn("matchups", f"{len(skipped)} of {len(pairs)} pairs skipped: {'; '.join(skipped)}")
    out.append(part("transactions", pages.parse_transactions_page(fetch(transactions_url(league)))))
    step("transactions")
    return out


def pairings_parts(
    league: str,
    weeks: Iterable[int],
    fetch: Fetch,
    step: Callable[[str], None] | None = None,
    clock: Clock = utc_now,
) -> list[Part]:
    """Each of ``weeks``' pairs from the league page shown for it, one ``pairings/<week>`` part
    a week: the season's schedule of opponents (#116). A page that cannot be read is left out;
    the next refresh asks for it again. The rate limit is raised (#180)."""
    out = []
    for week in weeks:
        try:
            data = pages.parse_pairings(fetch(pairings_url(league, week)), week)
        except RateLimited:
            raise
        except (FetchError, pages.PageError):
            continue
        out.append(Part(pairings_key(week), clock(), PUBLIC, data))
        if step is not None:
            step(f"week {week} pairs")
    return out


def lineup_parts(
    league: str,
    team_id: int,
    days: Iterable[date],
    fetch: Fetch,
    step: Callable[[str], None] | None = None,
    clock: Clock = utc_now,
) -> list[Part]:
    """``team_id``'s lineup on each of ``days``, from its team page shown for the day, one
    ``lineup/<team>/<day>`` part a day (#107). A page that cannot be read is left out; the
    rate limit is raised (#180)."""
    out = []
    for day in days:
        try:
            data = pages.parse_team_page(fetch(team_url(league, team_id, day)), team_id)
        except RateLimited:
            raise
        except (FetchError, pages.PageError):
            continue
        out.append(Part(lineup_key(team_id, day), clock(), PUBLIC, data))
        if step is not None:
            step(f"lineup {day:%a %b %d}")
    return out


def week_labels(league: str, team_id: int, days: Iterable[date], fetch: Fetch) -> dict[date, int]:
    """Yahoo's matchup week for each of ``days``, from the league's team page on that date
    (the calendar's source: no public endpoint lists the weeks' dates)."""
    out: dict[date, int] = {}
    for day in days:
        label = pages.week_label(fetch(team_url(league, team_id, day)))
        if label is not None:
            out[day] = label
    return out
