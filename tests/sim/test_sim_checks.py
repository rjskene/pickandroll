"""What gate 5 is fed (#172, PR 2b; PR D3): the surrogate against the exact set, on a replay of a
made-up recorded season."""

from __future__ import annotations

from datetime import timedelta

from pickandroll.sim import checks
from tests.sim.sim_league import KNOBS, make_setup, replay_of


def test_surrogate_matches_compare_the_two_tiers_sets():
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    days = [setup.start, setup.start + timedelta(3)]
    matches = checks.surrogate_matches(setup, w, 1, days, KNOBS)
    assert len(matches) == 2 and all(isinstance(m, bool) for m in matches)
    assert checks.surrogate_matches(setup, w, 1, [setup.season_end + timedelta(1)], KNOBS) == []


#: What ``surrogate_matches`` returned on main before PR D4a2, for every seat of the made-up setup
#: on its first eight days: equal every day.
MADE_UP_MATCHES = [True] * 8


def test_surrogate_matches_on_the_made_up_setup_are_what_they_were():
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    days = [setup.start + timedelta(d) for d in range(8)]
    for team in setup.teams:
        assert checks.surrogate_matches(setup, w, team, days, KNOBS) == MADE_UP_MATCHES


def test_a_record_says_what_gate_five_compared():
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    days = [setup.start, setup.start + timedelta(3)]
    records = checks.surrogate_records(setup, w, 1, days, KNOBS)
    assert [r["day"] for r in records] == [d.isoformat() for d in days]
    for r in records:
        assert r["left_out"] is None and r["equal"] is True
        assert r["exact"] == r["surrogate"]
        assert all(len(m) == 2 and isinstance(m[0], int) for m in r["exact"])
        # Two equal sets are worth the same by one evaluator.
        assert r["worth"]["exact"] == r["worth"]["surrogate"]
        assert isinstance(r["worth"]["standing"], float)
        assert (r["worth"]["exact"] == r["worth"]["standing"]) == (r["exact"] == [])
    assert [r["equal"] for r in records] == checks.surrogate_matches(setup, w, 1, days, KNOBS)


def test_a_day_left_out_of_gate_five_says_why(monkeypatch):
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    late = setup.season_end + timedelta(1)
    assert checks.surrogate_records(setup, w, 1, [late], KNOBS) == [
        {"day": late.isoformat(), "left_out": checks.OUTSIDE}
    ]
    # A day with no problem built (no week ahead or no day left in it): a stand-in builds none.
    monkeypatch.setattr(checks.policy, "problem_of", lambda *a, **k: None)
    assert checks.surrogate_records(setup, w, 1, [setup.start], KNOBS) == [
        {"day": setup.start.isoformat(), "left_out": checks.NO_PROBLEM}
    ]
    assert checks.surrogate_matches(setup, w, 1, [setup.start], KNOBS) == []
