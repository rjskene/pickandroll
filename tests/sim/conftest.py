"""What every test of the simulator shares: the guard's clock.

The commands refuse to start inside the routines' window (``cli.guard``), and they read the hour
through one seam, ``cli.now_local``. A suite that runs inside the window must not have a command
refused for the hour it runs at, so the seam is pinned here for every test under ``tests/sim``,
before any module's own fixtures run a command. A file's own pin, and a test's own ``monkeypatch``
of another hour, still win: each sets the seam after this one and puts it back when it ends.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss

#: A weekday morning outside the routines' window (``test_season_sim_script.BUSINESS_HOURS``).
BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))


@pytest.fixture(scope="session", autouse=True)
def business_hours() -> Iterator[datetime]:
    """The guard's clock reads ``BUSINESS_HOURS`` for the whole session, module fixtures included."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield BUSINESS_HOURS
