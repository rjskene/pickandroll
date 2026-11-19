"""The guard's clock is pinned for every test of the simulator (``tests/sim/conftest.py``).

This module pins nothing itself, on purpose: three files that ran a command without a pin of
their own had it refused whenever the suite ran inside the routines' window.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from pickandroll.sim import cli as ss


@pytest.fixture(scope="module")
def at_module_setup() -> datetime:
    """The hour a module's own fixture reads: where a module runs its ``fit``."""
    return ss.now_local()


def test_the_guard_s_clock_is_the_pinned_hour_in_a_module_with_no_pin_of_its_own(
    business_hours, at_module_setup
):
    assert not ss.in_quiet_window(business_hours)
    assert ss.now_local() == business_hours
    assert at_module_setup == business_hours
    assert ss.guard(rooms=0, nice=None) == (True, "ok")


def test_a_test_s_own_hour_still_wins_and_the_pin_comes_back(business_hours, monkeypatch):
    quiet = business_hours.replace(hour=5, minute=30)
    with monkeypatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: quiet)
        ok, why = ss.guard(rooms=0, nice=None)
        assert not ok and "window" in why
    assert ss.now_local() == business_hours
