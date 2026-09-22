import numpy as np
import pytest

from pickandroll.draft import auto_pick, simulate
from pickandroll.draft.autopick import draw_team_punts, softmax_choice, team_roster

from .test_draft_state import make_state


def test_naive_adp_autopick_takes_best_adp(pool):
    state = make_state(pool, position=3, num_teams=4)
    best = state.effective_adp().idxmin()
    pick = auto_pick(state, noise=0.0, strategy="adp")
    assert pick.player_id == best
    assert pick.team == "Team 1"
    assert pick.overall == 1


def test_z_autopick_takes_best_z_without_noise(pool):
    state = make_state(pool, position=3, num_teams=4)
    best = state.z["total"].idxmax()
    assert auto_pick(state, noise=0.0, strategy="z").player_id == best


def test_softmax_favours_the_closest_scores(pool):
    state = make_state(pool, position=3, num_teams=4)
    scores = state.z["total"]
    rng = np.random.default_rng(0)
    picks = [softmax_choice(scores, rng, noise=1.0) for _ in range(300)]
    ranks = scores.rank(ascending=False)
    assert ranks.loc[picks].max() <= 15
    assert (ranks.loc[picks] <= 3).mean() > 0.5


def test_simulate_stops_at_my_pick_and_is_reproducible(pool):
    a = make_state(pool, position=3, num_teams=4)
    b = make_state(pool, position=3, num_teams=4)
    made_a = simulate(a, seed=7)
    made_b = simulate(b, seed=7)
    assert [p.overall for p in made_a] == [1, 2]
    assert a.on_the_clock
    assert [p.player_id for p in made_a] == [p.player_id for p in made_b]
    assert {p.team for p in made_a} == {"Team 1", "Team 2"}


def test_adp_noise_keeps_picks_near_adp(pool):
    state = make_state(pool, position=4, num_teams=4)
    adp = state.effective_adp()
    made = simulate(state, noise=1.0, seed=1, strategy="adp")
    ranks = [adp.rank().loc[p.player_id] for p in made]
    assert all(r <= 12 for r in ranks)


def test_lp_autopick_respects_each_teams_roster(pool):
    state = make_state(pool, position=4, num_teams=4)
    punts = draw_team_punts(state, np.random.default_rng(3))
    assert set(punts) == {"Team 1", "Team 2", "Team 3"}
    # Snake order for 4 teams: 1 2 3 me | me 3 2 1, so eight picks give every team two.
    made = simulate(state, count=8, until_my_pick=False, noise=0.0, seed=3, strategy="lp")
    assert len(made) == 8
    assert all(len(team_roster(state, f"Team {n}")) == 2 for n in (1, 2, 3))
    assert len({p.player_id for p in made}) == 8


def test_simulate_count_and_completion(pool):
    state = make_state(pool, position=1, num_teams=4)
    state.settings = state.settings.__class__(num_teams=4, slots=state.settings.slots[:3])
    made = simulate(state, count=2, until_my_pick=False, seed=3)
    assert len(made) == 2
    simulate(state, until_my_pick=False, seed=3)
    assert state.complete
    with pytest.raises(ValueError):
        auto_pick(state, np.random.default_rng(0))
    with pytest.raises(ValueError):
        auto_pick(make_state(pool), strategy="nope")  # type: ignore[arg-type]
