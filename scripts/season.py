"""The season's commands: the weekly recorder (#97), run every Monday morning, the lineup
check (#107) and the decision log (#125), for the terminal.

    python scripts/season.py record --all              # every league's latest finished week
    python scripts/season.py record 258901 --week 3     # one league, a past week
    python scripts/season.py record --all --json        # each league's answer whole, one per line
    python scripts/season.py lineup --all               # today's and tomorrow's lineups as set
    python scripts/season.py lineup 258901 --days 7     # one league, the rest of the week
    python scripts/season.py decisions 258901           # the last week's solves and my moves

It asks the API (``PICKANDROLL_API``, by default http://127.0.0.1:8000) to record each league and
prints one line per league:

    258901 week 3: recorded (pages: taken 7, available 2, searches 0)
    251146 week 3: unchanged
    31822 week 3: needs pages (8): https://basketball.fantasysports.yahoo.com/nba/31822 ...; schedule pages (15): https://...?matchup_week=5 ...
    15953: skipped: no week is over yet
    238174: failed (502): https://...: HTTP 503

``needs pages`` is the private league: the pages listed are for the user's signed-in Chrome to
open (read only; the extension posts them), after which the league is recorded again.
``schedule pages`` are the private league's weeks ahead whose pairs the Season view has not read
(#116): the league page shown for each week, for the same Chrome to open once; the record does
not wait on them. ``lineup pages`` are its settings page until read and my team page shown for
each day of the week from today (#107), for the lineup comparison. Nothing here signs in or
reads Yahoo itself: the API does the reading.

``lineup`` prints one line per league: the days whose lineup as set in Yahoo loses games against
the recommended one, with the players to start and to sit, first any IL player whose status
cleared (Yahoo refuses every add until he is activated); the days not read are named:

    258901 week 1: Thu start Paul Reed for Myles Turner (1 game lost)
    251146 week 1: nothing lost Wed-Thu
    31822 week 1: IL: Jusuf Nurkic is Q, activate him (drops Paul Reed); not read: Thu

``decisions`` prints a league's decision log (#125): each solve of the moves and strategy routes
with its recommended sets, then each of my moves from the transactions page and how it matched
the solve before it (as recommended, differently, not recommended, or no entry; "near a solve"
when one lies within an hour of it, where a wrong time zone could change the match):

    258901 2026-10-22 13:05 moves bbm: week +0.42: add Paul Reed for Myles Turner; three +0.31: no move
    258901 2026-10-22 18:40 made: add Paul Reed for Myles Turner (Free Agent): as recommended (moves 2026-10-22 13:05)

Exit codes: 0 every league was asked, whatever it answered; 2 the API is unreachable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
#: A league's record reads about twenty Yahoo pages; a slow Yahoo can take minutes.
TIMEOUT = 600

Call = Callable[[str, str], tuple[int, Any]]
#: The league's clock: the decision log's times are printed in it.
ET = ZoneInfo("America/New_York")


class Unreachable(RuntimeError):
    """The API did not answer."""


def http(api: str = API, timeout: float = TIMEOUT) -> Call:
    def call(method: str, path: str) -> tuple[int, Any]:
        data = b"" if method == "POST" else None
        req = urllib.request.Request(api + path, method=method, data=data)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            try:
                return exc.code, json.loads(body)
            except ValueError:
                return exc.code, {"detail": body.decode("utf-8", errors="replace")}
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            raise Unreachable(f"{api}: {exc}") from exc

    return call


def _missing(missing: dict[str, Any]) -> str:
    parts = []
    for key, value in missing.items():
        parts.append(f"{len(value)} {key}" if isinstance(value, list) else f"{key} ({value})")
    return "; missing: " + ", ".join(parts) if parts else ""


def _ahead(
    ahead: list[str] | None, lineup: list[str] | None = None, moves: str | None = None
) -> str:
    out = f"; schedule pages ({len(ahead)}): {' '.join(ahead)}" if ahead else ""
    out += f"; lineup pages ({len(lineup)}): {' '.join(lineup)}" if lineup else ""
    return out + (f"; transactions page: {moves}" if moves else "")


def _pages_ahead(body: dict[str, Any]) -> str:
    return _ahead(body.get("ahead"), body.get("lineup_pages"), body.get("transactions_page"))


def describe(league: str, status: int, body: Any) -> str:
    """One league's answer as one line."""
    detail = body.get("detail") if isinstance(body, dict) else body
    if status == 200:
        pages = body.get("pages") or {}
        read = ", ".join(f"{k} {v}" for k, v in pages.items())
        return (
            f"{league} week {body['week']}: {body['status']}"
            f"{f' (pages: {read})' if read and body['status'] != 'unchanged' else ''}"
            f"{_missing(body.get('missing') or {})}"
            f"{_pages_ahead(body)}"
        )
    if status == 409 and isinstance(detail, dict) and detail.get("needs"):
        needs = detail["needs"]
        return (
            f"{league} week {detail.get('week')}: needs pages ({len(needs)}): {' '.join(needs)}"
            f"{_pages_ahead(detail)}"
        )
    if status in (404, 409):
        return f"{league}: skipped: {detail}"
    return f"{league}: failed ({status}): {detail}"


def record_all(
    call: Call, week: int | None, leagues: list[str] | None = None, as_json: bool = False
) -> int:
    try:
        if leagues is None:
            status, rows = call("GET", "/seasons")
            if status != 200:
                print(f"the league list failed ({status}): {rows}")
                return 0
            leagues = [str(r["league"]) for r in rows]
        for league in leagues:
            path = f"/seasons/{league}/record" + (f"?week={week}" if week is not None else "")
            status, body = call("POST", path)
            if as_json:
                print(json.dumps({"league": league, "status": status, "body": body}), flush=True)
            else:
                print(describe(league, status, body), flush=True)
    except Unreachable as exc:
        print(f"the API is unreachable: {exc}", flush=True)
        return 2
    return 0


def _day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%a")


def lineup_line(league: str, body: Any, days: int) -> str:
    """One league's lineups for the first ``days`` days a change counts, as one line."""
    names = {int(k): v["name"] for k, v in (body.get("players") or {}).items()}
    name = lambda k: names.get(k, str(k))
    ahead = [d for d in body["days"] if not d["past"]][:days]
    parts = []
    for a in body.get("alerts") or []:
        if a["kind"] == "cleared":
            drop = f" (drops {name(a['drop'])})" if a.get("drop") is not None else ""
            parts.append(
                f"{a['slot']}: {name(a['player'])} is {a['status'] or 'healthy'}, "
                f"activate him{drop}"
            )
    for d in ahead:
        if d["lost"]:
            sit = f" for {', '.join(map(name, d['sit']))}" if d["sit"] else ""
            games = f"{d['lost']} game{'s' if d['lost'] != 1 else ''} lost"
            parts.append(
                f"{_day(d['date'])} start {', '.join(map(name, d['start']))}{sit} ({games})"
            )
    unread = [_day(d["date"]) for d in ahead if d["yahoo"] is None]
    if not parts and ahead and len(unread) < len(ahead):
        span = _day(ahead[0]["date"]) + (f"-{_day(ahead[-1]['date'])}" if len(ahead) > 1 else "")
        parts.append(f"nothing lost {span}")
    if unread:
        parts.append(f"not read: {', '.join(unread)}")
    return f"{league} week {body['week']}: " + "; ".join(parts or ["no day left this week"])


def lineup_all(
    call: Call, days: int, leagues: list[str] | None = None, as_json: bool = False
) -> int:
    try:
        if leagues is None:
            status, rows = call("GET", "/seasons")
            if status != 200:
                print(f"the league list failed ({status}): {rows}")
                return 0
            leagues = [str(r["league"]) for r in rows]
        for league in leagues:
            status, body = call("GET", f"/seasons/{league}/lineup")
            if as_json:
                print(json.dumps({"league": league, "status": status, "body": body}), flush=True)
            elif status == 200:
                print(lineup_line(league, body, days), flush=True)
            else:
                detail = body.get("detail") if isinstance(body, dict) else body
                print(f"{league}: skipped ({status}): {detail}", flush=True)
    except Unreachable as exc:
        print(f"the API is unreachable: {exc}", flush=True)
        return 2
    return 0


def _local(iso: str) -> str:
    """A time in US Eastern: ``2026-10-22 13:05``."""
    return f"{datetime.fromisoformat(iso).astimezone(ET):%Y-%m-%d %H:%M}"


def _moves_text(moves: list[dict[str, Any]], name: Callable[[Any], str]) -> str:
    return ", ".join(
        f"add {name(m['add'])}" + (f" for {name(m['drop'])}" if m.get("drop") is not None else "")
        for m in moves
    )


def decision_lines(body: Any) -> list[str]:
    """A decision log (#125) as lines: each solve with its sets, then each of my moves with how
    it matched the solve before it."""
    names = {int(k): v for k, v in (body.get("players") or {}).items()}
    name = lambda k: names.get(int(k), str(k))
    by_id = {e["id"]: e for e in body["entries"]}
    out = []
    for e in body["entries"]:
        sets = []
        for st in e["sets"]:
            gain = st["gain"] or {}
            value = gain.get("weighted", gain.get(st["key"]))
            what = _moves_text(st["moves"], name) or "no move"
            label = st["key"] if st["weight"] is None else f"{st['key']} ({st.get('source')})"
            sets.append(
                f"{label} {value:+.2f}: {what}" if value is not None else f"{label}: {what}"
            )
        out.append(f"{_local(e['at'])} {e['source']} {e['system']['key']}: " + "; ".join(sets))
    for m in body["made"]:
        when = _local(m["at"]) if m["at"] else (m["day"] or "?")
        what = _moves_text([m], name) if m["add"] is not None else f"drop {name(m['drop'])}"
        detail = f" ({m['detail']})" if m.get("detail") else ""
        match = m["match"]
        entry = by_id.get(match["entry"]) if match["entry"] else None
        against = f" ({entry['source']} {_local(entry['at'])})" if entry else ""
        # Within an hour of a solve: a wrong time zone could have changed the match.
        near = " [near a solve]" if match.get("near") else ""
        out.append(f"{when} made: {what}{detail}: {match['kind'].replace('_', ' ')}{against}{near}")
    return out or ["nothing logged"]


def decisions_all(
    call: Call,
    leagues: list[str],
    start: str | None = None,
    end: str | None = None,
    as_json: bool = False,
) -> int:
    query = "&".join(f"{k}={v}" for k, v in (("from", start), ("to", end)) if v)
    try:
        for league in leagues:
            status, body = call(
                "GET", f"/seasons/{league}/decisions" + (f"?{query}" if query else "")
            )
            if as_json:
                print(json.dumps({"league": league, "status": status, "body": body}), flush=True)
            elif status == 200:
                for line in decision_lines(body):
                    print(f"{league} {line}", flush=True)
            else:
                detail = body.get("detail") if isinstance(body, dict) else body
                print(f"{league}: skipped ({status}): {detail}", flush=True)
    except Unreachable as exc:
        print(f"the API is unreachable: {exc}", flush=True)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("record", help="record a finished week of each league")
    r.add_argument("leagues", nargs="*", help="league ids (or --all)")
    r.add_argument("--all", action="store_true", help="every league folder")
    r.add_argument("--week", type=int, help="a past week; by default the latest one over")
    r.add_argument("--api", default=API, help="the API's address")
    r.add_argument("--json", action="store_true", help="print each answer whole")
    lu = sub.add_parser("lineup", help="each league's lineups as set against the recommended")
    lu.add_argument("leagues", nargs="*", help="league ids (or --all)")
    lu.add_argument("--all", action="store_true", help="every league folder")
    lu.add_argument("--days", type=int, default=2, help="the days from today (default 2)")
    lu.add_argument("--api", default=API, help="the API's address")
    lu.add_argument("--json", action="store_true", help="print each answer whole")
    dc = sub.add_parser("decisions", help="a league's decision log and its moves matched")
    dc.add_argument("leagues", nargs="+", help="league ids")
    dc.add_argument("--from", dest="start", help="the first day (YYYY-MM-DD); a week ago")
    dc.add_argument("--to", dest="end", help="the last day (YYYY-MM-DD); today")
    dc.add_argument("--api", default=API, help="the API's address")
    dc.add_argument("--json", action="store_true", help="print each answer whole")
    args = ap.parse_args(argv)
    if args.command == "decisions":
        return decisions_all(
            http(args.api.rstrip("/")), args.leagues, args.start, args.end, args.json
        )
    if not args.all and not args.leagues:
        ap.error("name the leagues or pass --all")
    leagues = None if args.all else args.leagues
    if args.command == "lineup":
        return lineup_all(http(args.api.rstrip("/")), args.days, leagues, args.json)
    return record_all(http(args.api.rstrip("/")), args.week, leagues, args.json)


if __name__ == "__main__":
    sys.exit(main())
