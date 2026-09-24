from pickandroll.draft.league_sim import draft_once, simulate_league

from .test_draft_state import make_state


def test_draft_once_fills_every_team(pool):
    state = make_state(pool, position=1, num_teams=4)
    picks, totals = draft_once(state, seed=3, strategies=("z", "adp"))
    assert state.complete and len(picks) == state.settings.total_picks
    assert [k for _, k in picks] == list(range(1, state.settings.total_picks + 1))
    assert len({p for p, _ in picks}) == len(picks)
    assert [t["position"] for t in totals] == [1, 2, 3, 4]
    assert all(t["strategy"] in {"z", "adp"} for t in totals)
    again = make_state(pool, position=1, num_teams=4)
    assert draft_once(again, seed=3, strategies=("z", "adp"))[0] == picks


def test_simulate_league_fits_table_and_curve(pool):
    state = make_state(pool, position=1, num_teams=4)
    sim = simulate_league(
        state.settings, state.projections, sims=4, strategies=("z", "adp"), workers=1
    )
    assert sim.sims == 4 and sim.survival.sims == 4
    assert sim.survival.total_picks == state.settings.total_picks
    assert set(sim.survival.table.index) == set(state.z.index)
    assert (sim.survival.table[1] == 1.0).all()
    assert sim.survival.table.iloc[:, -1].between(0.0, 1.0).all()
    assert len(sim.team_totals) == 16
    assert sim.curve.source.startswith("simulated league (4 drafts, 4 teams, z/adp drafters)")
    assert all(s > 0 for s in sim.curve.sigma.values())
    updates = []
    simulate_league(
        state.settings,
        state.projections,
        sims=2,
        strategies=("z",),
        workers=1,
        progress=updates.append,
    )
    assert [u["done"] for u in updates] == [1, 2] and updates[0]["stage"] == "survival"
