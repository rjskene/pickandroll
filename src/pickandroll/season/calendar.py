"""The league's matchup weeks.

Yahoo's NBA weeks run Monday to Sunday, but some are longer: the week of the All-Star break is
merged with the next, and the last week can run to the season's end date. No public endpoint
lists the weeks' dates; the league's team page names the matchup week of any date it is asked
for, so the calendar is built from that label for each Monday (``labels``). Without labels every
Monday starts a week and the calendar says it is an estimate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class Week:
    number: int
    start: date
    #: The last day of the week, inclusive.
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def days(self, since: date | None = None) -> list[date]:
        """The week's days, from ``since`` on when it falls inside the week."""
        first = max(self.start, since) if since else self.start
        return [first + timedelta(n) for n in range((self.end - first).days + 1)]

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "start": self.start.isoformat(), "end": self.end.isoformat()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Week:
        return cls(int(d["number"]), date.fromisoformat(d["start"]), date.fromisoformat(d["end"]))


@dataclass(frozen=True)
class Calendar:
    weeks: tuple[Week, ...]
    #: True when some week's dates come from the Monday rule rather than Yahoo's labels.
    estimated: bool = False

    def week(self, number: int) -> Week | None:
        return next((w for w in self.weeks if w.number == number), None)

    def week_of(self, day: date) -> Week | None:
        return next((w for w in self.weeks if w.contains(day)), None)

    def ahead(self, day: date, count: int) -> list[Week]:
        """The week holding ``day`` and the ``count - 1`` after it (fewer at the season's end)."""
        out = [w for w in self.weeks if w.end >= day]
        return out[:count]

    def to_dict(self) -> dict[str, Any]:
        return {"weeks": [w.to_dict() for w in self.weeks], "estimated": self.estimated}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Calendar:
        return cls(tuple(Week.from_dict(w) for w in d["weeks"]), bool(d.get("estimated")))


def monday_of(day: date) -> date:
    return day - timedelta(day.weekday())


def mondays(first: date, end: date) -> list[date]:
    """Every Monday from the one on or before ``first`` to ``end``: the dates whose week label
    builds the calendar."""
    out, day = [], monday_of(first)
    while day <= end:
        out.append(day)
        day += timedelta(7)
    return out


def build_calendar(first: date, end: date, labels: Mapping[date, int] | None = None) -> Calendar:
    """The weeks from the Monday on or before ``first`` (the season's first day) to ``end``.

    ``labels`` maps a Monday to the matchup week Yahoo names for it. Consecutive Mondays with one
    label are one long week. A Monday without a label starts the week after the previous one,
    and the calendar is then an estimate.
    """
    labels = dict(labels or {})
    starts = mondays(first, end)
    if not starts:
        return Calendar((), estimated=True)
    numbered: list[tuple[date, int]] = []
    estimated = False
    for day in starts:
        if day in labels:
            number = int(labels[day])
        else:
            number = numbered[-1][1] + 1 if numbered else 1
            estimated = True
        numbered.append((day, number))
    return Calendar(tuple(_weeks(numbered, end)), estimated=estimated)


def _weeks(numbered: Iterable[tuple[date, int]], end: date) -> list[Week]:
    weeks: list[Week] = []
    for day, number in numbered:
        if weeks and weeks[-1].number == number:
            continue
        if weeks:
            prev = weeks[-1]
            weeks[-1] = Week(prev.number, prev.start, day - timedelta(1))
        weeks.append(Week(number, day, end))
    return weeks
