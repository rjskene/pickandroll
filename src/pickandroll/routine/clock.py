"""The routines' clock: Central, whatever the host's zone (the queue's execute time and the
trigger times are Central, ``docs/AUTOPILOT.md`` §2 and §3)."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")


def now() -> datetime:
    return datetime.now(CENTRAL)


def parse_hm(hm: str) -> time:
    hh, mm = hm.split(":")
    return time(int(hh), int(mm))


def at(when: datetime, hm: str) -> datetime:
    """``hm`` ("HH:MM") on ``when``'s day, in its zone."""
    return datetime.combine(when.date(), parse_hm(hm), tzinfo=when.tzinfo)


def before(when: datetime, hm: str) -> bool:
    return when < at(when, hm)


def seconds_until(when: datetime, hm: str) -> float:
    return max(0.0, (at(when, hm) - when).total_seconds())
