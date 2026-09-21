from datetime import UTC, datetime

import pytest

from pickandroll.draft import DraftState, LeagueSettings
from pickandroll.projections import Cat, ProjectionSet


def make_state(pool, position=3, num_teams=4):
    ps = ProjectionSet(
        source="test", label="t", horizon="season", as_of=datetime(2026, 9, 21, tzinfo=UTC), df=pool
    )
    settings = LeagueSettings(num_teams=num_teams)
    return DraftState(settings=settings, projections=ps, my_team="me", my_position=position)


def test_initial_state(pool):
    state = make_state(pool)
    assert state.next_overall == 1
    assert not state.on_the_clock
    assert state.my_next_pick == 3
    assert len(state.available) == len(pool)


def test_apply_pick_updates_board(pool):
    state = make_state(pool)
    top = state.z["total"].idxmax()
    state.apply_pick("them", top)
    assert top in state.taken
    assert top not in state.available
    with pytest.raises(ValueError):
        state.apply_pick("them", top)
    with pytest.raises(KeyError):
        state.apply_pick("them", "nobody")


def test_sync_applies_only_new_picks(pool):
    state = make_state(pool)
    ids = state.z["total"].nlargest(3).index.tolist()
    feed = [(1, "a", ids[0]), (2, "b", ids[1])]
    assert len(state.sync(feed)) == 2
    feed.append((3, "me", ids[2]))
    added = state.sync(feed)
    assert [p.overall for p in added] == [3]
    assert state.my_roster == [ids[2]]


def test_recommend_locks_my_roster_and_blocks_others(pool):
    state = make_state(pool)
    ids = state.z["total"].nlargest(3).index.tolist()
    state.sync([(1, "a", ids[0]), (2, "b", ids[1])])
    assert state.on_the_clock
    table = state.recommend(n=4, punt=frozenset({Cat.FT_PCT}))
    assert not table.empty
    assert ids[0] not in table["player"].tolist()
    assert "name" in table.columns
    best = state.best_roster(punt=frozenset({Cat.FT_PCT}))
    assert ids[0] not in best.players and ids[1] not in best.players
    state.apply_pick("me", table.iloc[0]["player"])
    best = state.best_roster(punt=frozenset({Cat.FT_PCT}))
    assert table.iloc[0]["player"] in best.players


def test_draft_completes(pool):
    state = make_state(pool, num_teams=4)
    order = state.z["total"].sort_values(ascending=False).index.tolist()
    for k in range(state.settings.total_picks):
        _, position = state.owner_of(k + 1)
        team = "me" if position == state.my_position else f"t{position}"
        state.apply_pick(team, order[k])
    assert state.complete
    assert len(state.my_roster) == 13
    assert state.my_next_pick is None
