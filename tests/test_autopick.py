import numpy as np
import pytest

from pickandroll.draft import auto_pick, simulate

from .test_draft_state import make_state


def test_naive_autopick_takes_best_adp(pool):
    state = make_state(pool, position=3, num_teams=4)
    best = state.effective_adp().idxmin()
    pick = auto_pick(state, noise=0.0)
    assert pick.player_id == best
    assert pick.team == "Team 1"
    assert pick.overall == 1


def test_simulate_stops_at_my_pick_and_is_reproducible(pool):
    a = make_state(pool, position=3, num_teams=4)
    b = make_state(pool, position=3, num_teams=4)
    made_a = simulate(a, seed=7)
    made_b = simulate(b, seed=7)
    assert [p.overall for p in made_a] == [1, 2]
    assert a.on_the_clock
    assert [p.player_id for p in made_a] == [p.player_id for p in made_b]
    assert {p.team for p in made_a} == {"Team 1", "Team 2"}


def test_noise_keeps_picks_near_adp(pool):
    state = make_state(pool, position=4, num_teams=4)
    adp = state.effective_adp()
    made = simulate(state, noise=1.0, seed=1)
    ranks = [adp.rank().loc[p.player_id] for p in made]
    assert all(r <= 12 for r in ranks)


def test_simulate_count_and_completion(pool):
    state = make_state(pool, position=1, num_teams=4)
    state.settings = state.settings.__class__(num_teams=4, slots=state.settings.slots[:3])
    made = simulate(state, count=2, until_my_pick=False, seed=3)
    assert len(made) == 2
    simulate(state, until_my_pick=False, seed=3)
    assert state.complete
    with pytest.raises(ValueError):
        auto_pick(state, np.random.default_rng(0))
