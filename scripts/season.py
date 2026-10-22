"""The season's scheduled commands (#97): the weekly recorder, run every Monday morning.

    python scripts/season.py record --all              # every league's latest finished week
    python scripts/season.py record 258901 --week 3     # one league, a past week
    python scripts/season.py record --all --json        # each league's answer whole, one per line

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
not wait on them. Nothing here signs in or reads Yahoo itself: the API does the reading.

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
from typing import Any

API = os.environ.get("PICKANDROLL_API", "http://127.0.0.1:8000").rstrip("/")
#: A league's record reads about twenty Yahoo pages; a slow Yahoo can take minutes.
TIMEOUT = 600

Call = Callable[[str, str], tuple[int, Any]]


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


def _ahead(ahead: list[str] | None) -> str:
    return f"; schedule pages ({len(ahead)}): {' '.join(ahead)}" if ahead else ""


def describe(league: str, status: int, body: Any) -> str:
    """One league's answer as one line."""
    detail = body.get("detail") if isinstance(body, dict) else body
    if status == 200:
        pages = body.get("pages") or {}
        read = ", ".join(f"{k} {v}" for k, v in pages.items())
        return (
            f"{league} week {body['week']}: {body['status']}"
            f"{f' (pages: {read})' if read and body['status'] != 'unchanged' else ''}"
            f"{_missing(body.get('missing') or {})}{_ahead(body.get('ahead'))}"
        )
    if status == 409 and isinstance(detail, dict) and detail.get("needs"):
        needs = detail["needs"]
        return (
            f"{league} week {detail.get('week')}: needs pages ({len(needs)}): {' '.join(needs)}"
            f"{_ahead(detail.get('ahead'))}"
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("record", help="record a finished week of each league")
    r.add_argument("leagues", nargs="*", help="league ids (or --all)")
    r.add_argument("--all", action="store_true", help="every league folder")
    r.add_argument("--week", type=int, help="a past week; by default the latest one over")
    r.add_argument("--api", default=API, help="the API's address")
    r.add_argument("--json", action="store_true", help="print each answer whole")
    args = ap.parse_args(argv)
    if not args.all and not args.leagues:
        ap.error("name the leagues or pass --all")
    leagues = None if args.all else args.leagues
    return record_all(http(args.api.rstrip("/")), args.week, leagues, args.json)


if __name__ == "__main__":
    sys.exit(main())
