"""The NBA schedule by date, from ESPN's public scoreboard (NBA's own schedule file answers 403).

One request per date; each date is cached as ``<cache>/<YYYY-MM-DD>.json`` and read again only
once its copy is older than ``max_age`` (a game can be postponed), or ``far_max_age`` for a date
weeks away (the rest of the season, which the Season view counts games on, #116). Team names
are returned in Yahoo's abbreviations, the ones the league pages and the player pool use.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day}"
#: ESPN's abbreviations that differ from Yahoo's.
ESPN_TO_YAHOO = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}
#: Games that will not be played on their date.
NOT_PLAYED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_SUSPENDED"}
MAX_AGE = timedelta(hours=12)
#: How old a far date's copy may be: its games move rarely, and the season holds many dates.
FAR_MAX_AGE = timedelta(days=7)


def scoreboard_url(day: date) -> str:
    return SCOREBOARD.format(day=day.strftime("%Y%m%d"))


def teams_playing(body: Any) -> list[str]:
    """The teams with a game in an ESPN scoreboard response, in Yahoo's abbreviations."""
    teams: set[str] = set()
    for event in (body or {}).get("events") or []:
        status = ((event.get("status") or {}).get("type") or {}).get("name")
        if status in NOT_PLAYED:
            continue
        for comp in event.get("competitions") or []:
            for side in comp.get("competitors") or []:
                abbr = ((side.get("team") or {}).get("abbreviation") or "").upper()
                if abbr:
                    teams.add(ESPN_TO_YAHOO.get(abbr, abbr))
    return sorted(teams)


def schedule_days(
    days: Iterable[date],
    fetch: Callable[[str], str],
    cache_dir: Path,
    now: datetime | None = None,
    max_age: timedelta = MAX_AGE,
    far_from: date | None = None,
    far_max_age: timedelta = FAR_MAX_AGE,
) -> dict[str, list[str]]:
    """``{"YYYY-MM-DD": [teams playing]}`` for ``days``, from the cache where it is fresh: within
    ``max_age``, or ``far_max_age`` for a date from ``far_from`` on.

    A date already over when its copy was read is final. A date that cannot be read is left
    out (the season's games count then says the schedule does not cover it)."""
    now = now or datetime.now(UTC)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[str]] = {}
    for day in days:
        path = cache_dir / f"{day.isoformat()}.json"
        cached = _read(path)
        if cached is not None:
            fetched = datetime.fromisoformat(cached["fetched_at"])
            final = fetched.date() > day + timedelta(days=1)
            age = far_max_age if far_from is not None and day >= far_from else max_age
            if final or now - fetched < age:
                out[day.isoformat()] = cached["teams"]
                continue
        try:
            teams = teams_playing(json.loads(fetch(scoreboard_url(day))))
        except Exception:  # noqa: BLE001 - a date the source cannot give is reported missing
            if cached is not None:
                out[day.isoformat()] = cached["teams"]
            continue
        path.write_text(json.dumps({"fetched_at": now.isoformat(), "teams": teams}))
        out[day.isoformat()] = teams
    return out


def _read(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None
