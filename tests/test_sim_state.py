"""The simulator's state (#172, PR 2b): a setup, an arm's position, the made-up league's
calendar, round robin and snake draft."""

from __future__ import annotations

from datetime import date

from pickandroll.season.sim import state as sst
from pickandroll.season.sim.state import SimState, add_totals, initial, round_robin, snake_draft
from tests.sim_league import make_setup


def test_the_setup_knows_its_days_weeks_and_spots():
    setup = make_setup(weeks=3, playoff_weeks=1)
    assert setup.start == date(2026, 10, 26) and setup.season_end == date(2026, 11, 15)
    assert len(setup.days) == 21
    assert setup.week_of(date(2026, 11, 3)).number == 2
    assert setup.starting_slots() == ("PG", "SG", "G", "C", "Util")
    assert setup.spots() == 6  # the bench counts, a held slot would not
    assert setup.spec is not None and setup.spec.regular_weeks == (1, 2)
    assert make_setup(bracket=False).spec is None


def test_day_one_and_the_key_two_arms_share_a_solve_on():
    setup = make_setup()
    state = initial(setup)
    assert state.day == setup.start
    assert set(state.pool) == set(setup.pool)
    taken = {k for r in state.rosters.values() for k, _ in r}
    assert not taken & state.pool
    same = SimState(state.day, dict(state.rosters), state.pool, {})
    assert same.key() == state.key()
    moved = SimState(state.day, state.rosters, state.pool - {setup.pool[0]}, {})
    assert moved.key() != state.key()
    assert state.active(1) == tuple(k for k, _ in setup.rosters[1])
    assert state.held(1) == ()
    assert state.owner_of(setup.rosters[2][0][0]) == 2
    assert state.owner_of(setup.pool[0]) is None


def test_totals_add_up_by_week_and_team():
    state = initial(make_setup())
    state = add_totals(state, 1, 3, {"pts": 10.0, "reb": 4.0})
    state = add_totals(state, 1, 3, {"pts": 5.0})
    state = add_totals(state, 2, 3, {"pts": 1.0})
    assert state.totals == {1: {3: {"pts": 15.0, "reb": 4.0}}, 2: {3: {"pts": 1.0}}}


def test_weeks_from_starts_on_the_monday_before_and_is_estimated():
    cal = sst.weeks_from(date(2026, 10, 21), 3)
    assert cal.estimated
    assert [(w.number, w.start, w.end) for w in cal.weeks] == [
        (1, date(2026, 10, 19), date(2026, 10, 25)),
        (2, date(2026, 10, 26), date(2026, 11, 1)),
        (3, date(2026, 11, 2), date(2026, 11, 8)),
    ]


def test_round_robin_pairs_everyone_once_a_round_then_repeats():
    pairs = round_robin((1, 2, 3, 4), range(1, 5))
    assert set(pairs) == {1, 2, 3, 4}
    for w in (1, 2, 3):
        assert sorted(t for p in pairs[w] for t in p) == [1, 2, 3, 4]
    seen = {p for w in (1, 2, 3) for p in pairs[w]}
    assert seen == {(1, 4), (2, 3), (1, 3), (2, 4), (1, 2), (3, 4)}
    assert pairs[4] == pairs[1]
    odd = round_robin((1, 2, 3), [1])
    assert len(odd[1]) == 1


def test_snake_draft_alternates_the_order_and_benches_everyone():
    value = {k: float(10 - k) for k in range(1, 9)}
    rosters = snake_draft(range(1, 9), value, (1, 2, 3), 2)
    assert rosters == {
        1: ((1, "BN"), (6, "BN")),
        2: ((2, "BN"), (5, "BN")),
        3: ((3, "BN"), (4, "BN")),
    }
