"""ESPN's NBA injury report (public JSON, no sign-in), for the breakout flag's opportunity signal
(#95): every listed player with his team, position, status and estimated return date.

Ported from the draft-day news sweep (``scripts/draft_prep/news.py``, ``parse_espn``), which keeps
its own copy for the draft's block; this one keeps the position and the return date as data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from .schedule import ESPN_TO_YAHOO

#: The data behind https://www.espn.com/nba/injuries: every team's list.
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


@dataclass(frozen=True)
class Listed:
    """One player on the report. ``key`` is ESPN's id for him (``espn:1234``), the key an alias
    in ``data/aliases.json`` may pin."""

    key: str
    name: str
    #: His NBA team as Yahoo writes it (``GSW``, not ESPN's ``GS``).
    team: str
    #: ESPN's position: ``G``, ``F``, ``C`` or a finer one (``PG``, ``G-F``).
    position: str
    #: ``Out`` or ``Day-To-Day``.
    status: str
    returns: date | None
    injury: str | None
    #: When ESPN updated the item.
    when: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "team": self.team,
            "position": self.position,
            "status": self.status,
            "returns": self.returns.isoformat() if self.returns else None,
            "injury": self.injury,
            "when": self.when.isoformat() if self.when else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Listed:
        return cls(
            key=str(d["key"]),
            name=str(d["name"]),
            team=str(d.get("team") or ""),
            position=str(d.get("position") or ""),
            status=str(d.get("status") or ""),
            returns=date.fromisoformat(d["returns"]) if d.get("returns") else None,
            injury=d.get("injury"),
            when=datetime.fromisoformat(d["when"]) if d.get("when") else None,
        )


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)).astimezone(UTC)
    except ValueError:
        return None


def parse_injuries(text: str) -> list[Listed]:
    """Every player on ESPN's report, in its order."""
    out = []
    for team in json.loads(text).get("injuries") or []:
        for row in team.get("injuries") or []:
            athlete = row.get("athlete") or {}
            name = str(athlete.get("displayName") or "")
            if not name:
                continue
            links = " ".join(str(link.get("href", "")) for link in athlete.get("links") or [])
            found = re.search(r"/id/(\d+)", links)
            details = row.get("details") or {}
            back = details.get("returnDate")
            try:
                returns = date.fromisoformat(str(back)[:10]) if back else None
            except ValueError:
                returns = None
            team = str((athlete.get("team") or {}).get("abbreviation") or "")
            out.append(
                Listed(
                    key=f"espn:{found.group(1)}" if found else f"espn:{row.get('id', name)}",
                    name=name,
                    team=ESPN_TO_YAHOO.get(team, team),
                    position=str((athlete.get("position") or {}).get("abbreviation") or ""),
                    status=str(row.get("status") or ""),
                    returns=returns,
                    injury=str(details["type"]) if details.get("type") else None,
                    when=_when(row.get("date")),
                )
            )
    return out
