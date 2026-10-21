"""Yahoo's public sources for a public league (the prize leagues), read without a session.

Yahoo's Fantasy API still refuses the app (docs/ADD_DROP.md, "Inputs"), so a season is read from
what Yahoo serves to anyone for a public league:

* the v3 JSON endpoints ``settings`` and ``players`` (``pub-api.fantasysports.yahoo.com``);
* the league's pages on ``basketball.fantasysports.yahoo.com``, parsed in :mod:`.pages`.

For a private league both answer with nothing; that league's pages come from the extension.
Nothing here signs in, sends a cookie or acts on the league.
"""

from __future__ import annotations

import gzip
import http.client
import json
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from ...season.state import PUBLIC, YAHOO_WEEK, Part, SeasonSettings, matchup_key, roster_key
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


class FetchError(RuntimeError):
    """A source that did not answer, or answered with an error status."""


class PrivateLeague(RuntimeError):
    """Yahoo serves nothing public for the league: its pages come from the extension."""


class Fetch(Protocol):
    def __call__(self, url: str) -> str: ...


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


class HttpFetch:
    """A plain GET with a browser User-Agent and no cookies, at most one request per
    ``interval`` seconds (Yahoo's pages are a megabyte each)."""

    def __init__(self, interval: float = 0.3, timeout: float = 30.0) -> None:
        self.interval, self.timeout = interval, timeout
        self._last = 0.0
        self._opener = urllib.request.build_opener(_HTTPSHandler())

    def __call__(self, url: str) -> str:
        wait = self._last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
        except urllib.error.HTTPError as exc:
            raise FetchError(f"{url}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise FetchError(f"{url}: {exc}") from exc
        finally:
            self._last = time.monotonic()
        return body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- urls
def settings_url(league: str) -> str:
    return f"{PUB_API}/settings/nba/{league}?format=json"


def players_url(league: str) -> str:
    return f"{PUB_API}/players/nba/{league}?format=json&projected=1&average=1"


def league_url(league: str) -> str:
    return f"{SITE}/{league}"


def team_url(league: str, team_id: int, day: date | None = None) -> str:
    return f"{SITE}/{league}/{team_id}" + (f"?date={day.isoformat()}" if day else "")


def available_url(league: str, offset: int, view: str = OWNERSHIP_VIEW) -> str:
    """The players page: available players (free agents and waivers), most rostered first."""
    return f"{SITE}/{league}/players?status=A&pos=P&stat1={view}&sort=R_PO&sdir=1&count={offset}"


def matchup_url(league: str, week: int, teams: Iterable[int]) -> str:
    a, b = list(teams)
    return f"{SITE}/{league}/matchup?week={week}&mid1={a}&mid2={b}"


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
) -> list[Part]:
    """Every public source of a league, read once, as season parts.

    The order is settings, the player pool, the league page (standings and this week's pairs),
    every team's page, the available players most rostered first, Yahoo's projection of them
    for the next seven days, my matchup and the transactions. Raises :class:`PrivateLeague` when Yahoo serves nothing public for it.
    """
    pages_needed = -(-max_available // PAGE_ROWS)
    total = 3 + base.num_teams + 2 * pages_needed + 2
    done = 0

    def step(what: str) -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(what, done, total)

    def part(key: str, data: Any) -> Part:
        return Part(key, datetime.now(UTC), PUBLIC, data)

    out: list[Part] = []
    read = settings_from_v3(_json(fetch, settings_url(league)))
    if read is None:
        raise PrivateLeague(
            f"Yahoo serves no public league {league}: open its pages in Chrome with the extension"
        )
    out.append(part("settings", read))
    step("settings")
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
    seen = datetime.now(UTC).isoformat()
    unique = {r["player"]["yahoo_id"]: {**r, "seen_at": seen} for r in rows}
    out.append(part("available", {"rows": list(unique.values())}))
    # Yahoo's own projection of the same players for the next seven days.
    projected: dict[int, dict[str, Any]] = {}
    for offset in offsets:
        html = fetch(available_url(league, offset, pages.PROJECTION_VIEW))
        for r in pages.parse_projection_page(html)["rows"]:
            projected[r["player"]["yahoo_id"]] = {**r, "seen_at": datetime.now(UTC).isoformat()}
        step(f"Yahoo projection {offset + 1}-{offset + PAGE_ROWS}")
    out.append(part(YAHOO_WEEK, {"rows": list(projected.values())}))
    week = read.get("current_week") or league_page.get("week")
    mine = base.my_team_id
    pair = next(
        (m["teams"] for m in league_page["matchups"] if mine in m["teams"] and m["week"] == week),
        None,
    )
    if pair is not None and week is not None:
        data = pages.parse_matchup_page(fetch(matchup_url(league, int(week), pair)), int(week))
        out.append(part(matchup_key(int(week), data["teams"]), data))
    step("my matchup")
    out.append(part("transactions", pages.parse_transactions_page(fetch(transactions_url(league)))))
    step("transactions")
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
