"""The league shapes (#172, PR D4b): the ruled grid and its order, the fixed shape, each shape's
league on the made-up season, and a draft that cannot be filled, found by name."""

from __future__ import annotations

import contextlib
import hashlib
import io
import itertools
import json
from types import SimpleNamespace

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import policy, shapes
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from tests.sim.sim_league import make_data_dir

#: The grid's seventy-two shapes in their order, as a digest of their payloads: the order is part
#: of every run's record and is never changed.
GRID_ORDER = "c0d7932334b69f9fba05872a3962bc2850124ca410d4cc286e6f45afec392368"


def order_digest(grid: shapes.Grid) -> str:
    return hashlib.sha256(json.dumps([s.payload() for s in grid.shapes]).encode()).hexdigest()


def test_the_grid_is_seventy_two_shapes_in_the_ruled_order():
    g = shapes.FULL.shapes
    assert len(g) == 72 and len(set(g)) == 72
    # The team count turns fastest, then the slots, the adds and the playoffs.
    head = [(s.teams, len(s.slots), s.weekly_adds, s.playoff_teams, s.playoff_weeks) for s in g[:7]]
    assert head == [
        (10, 13, 2, 4, 2),
        (12, 13, 2, 4, 2),
        (14, 13, 2, 4, 2),
        (10, 15, 2, 4, 2),
        (12, 15, 2, 4, 2),
        (14, 15, 2, 4, 2),
        (10, 13, 3, 4, 2),
    ]
    last = g[-1]
    assert (last.teams, len(last.slots), last.weekly_adds, last.playoff_teams) == (14, 15, None, 8)
    playoffs, adds = ((4, 2), (6, 3), (8, 3)), (2, 3, 4, None)
    rosters, teams = (shapes.SLOTS, shapes.WIDE_SLOTS), (10, 12, 14)
    assert g == tuple(
        shapes.LeagueShape(t, s, a, p, w)
        for (p, w), a, s, t in itertools.product(playoffs, adds, rosters, teams)
    )
    assert shapes.WIDE_SLOTS == (*shapes.SLOTS, "BN", "BN")
    assert order_digest(shapes.FULL) == GRID_ORDER
    assert shapes.FULL.axes() == {
        "playoffs": ("4/2", "6/3", "8/3"),
        "weekly_adds": (2, 3, 4, None),
        "slots": (13, 15),
        "teams": (10, 12, 14),
    }


def test_the_fixed_shape_is_the_league_before_and_one_of_the_grid():
    f = shapes.FIXED
    assert f == shapes.LeagueShape(12, rn.REPLAY_SLOTS, 4, 6, 3)
    assert (rn.REPLAY_TEAMS, rn.REPLAY_PLAYOFF_TEAMS, rn.REPLAY_PLAYOFF_WEEKS) == (12, 6, 3)
    assert rn.REPLAY_WEEKLY_ADDS == 4 and ss.REPLAY_IDS == f.ids == tuple(range(1, 13))
    assert shapes.FULL.shapes.index(f) == 37
    assert shapes.FIXED_GRID.shapes == (f,) and shapes.FIXED_GRID.name == "fixed"
    assert f.label() == "12 teams, 13 slots, 4 adds a week, 6 playoff teams over 3 weeks"
    no_limit = shapes.LeagueShape(10, shapes.WIDE_SLOTS, None, 4, 2)
    assert no_limit.label() == "10 teams, 15 slots, no add limit, 4 playoff teams over 2 weeks"
    assert no_limit.payload()["weekly_adds"] is None and len(no_limit.payload()["slots"]) == 15


@pytest.fixture(scope="module")
def wire_read(tmp_path_factory):
    """The made-up season 2024 with a wire of 120, fitted and read on ``prior``: 191 draftable
    players, 206 under its table of draft positions."""
    data = make_data_dir(tmp_path_factory.mktemp("shapes"), wire=120)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    r = ss.read_season(data, 2024, [fc.parse_one("prior")], None, {}, 1, "stat")
    table, _ = reader.adp_table(data, 2024, ss.HOLD_OUT)
    return data, r, table


def _setup(r, league):
    projection = ss.projection_of(r.served[0], r.fixed, r.lines, 1, 0, "stat")
    return ss.replay_setup_of(2024, r.lines, r.members, r.scheduled, projection, None, league)


def test_each_shape_s_league_has_its_teams_roster_limit_and_bracket(wire_read):
    _, r, _ = wire_read
    full = {(t, s): False for t in (10, 12, 14) for s in (13, 15)}
    for x in shapes.FULL.shapes:
        setup = _setup(r, x)
        assert setup.teams == x.ids and setup.roster_slots == x.slots
        assert setup.max_weekly_adds == x.weekly_adds
        spec = setup.spec
        assert spec.teams == x.ids and spec.playoff_teams == x.playoff_teams
        # The season stays 22 weeks; the playoffs are its last weeks and the regular season is
        # what they leave.
        assert len(setup.calendar.weeks) == rn.REPLAY_WEEKS
        assert spec.playoff_weeks == tuple(range(23 - x.playoff_weeks, 23))
        assert sorted(spec.pairings) == list(range(1, 23 - x.playoff_weeks))
        assert spec.byes == {4: 0, 6: 2, 8: 0}[x.playoff_teams]
        full[(x.teams, len(x.slots))] = all(len(v) == len(x.slots) for v in setup.rosters.values())
    # Every draft fills but fourteen teams of fifteen, whose 210 the season's 191 cannot.
    assert [k for k, ok in full.items() if not ok] == [(14, 15)]


def test_a_draft_that_cannot_be_filled_is_found_by_name(wire_read):
    _, r, table = wire_read
    found = ss.short_drafts([r], shapes.FULL, 1, "stat", None, {}, {})
    assert found == [
        {
            "season": 2024,
            "forecaster": "prior",
            "teams": 14,
            "spots": 15,
            "need": 210,
            "board": "pool",
            "holds": 191,
        }
    ]
    assert sum(len(v) for v in _setup(r, shapes.FULL.shapes[-1]).rosters.values()) == 191
    assert ss.short_line(found[0]) == (
        "2024 on prior: the draft of 14 teams of 15 spots takes 210 players and the season has "
        "191 draftable"
    )
    # The fixed shape fills here.
    assert ss.short_drafts([r], shapes.FIXED_GRID, 1, "stat", None, {}, {}) == []
    # Under a table the pool holds the listed players too (206), and an arm's seat's own board
    # only the players its forecaster projects (191): both are held to the whole draft.
    arms = {"a": SimpleNamespace(forecaster=None), "b": SimpleNamespace(forecaster=None)}
    under = ss.short_drafts([r], shapes.FULL, 1, "stat", None, arms, {2024: table.picks})
    assert [(x["teams"], x["spots"], x["board"], x["holds"]) for x in under] == [
        (14, 15, "pool", 206),
        (14, 15, "a", 191),
        (14, 15, "b", 191),
    ]
    line = ss.short_line(under[1])
    assert "arm A's seat's own board holds 191" in line and "might have filled" in line


def test_the_made_up_folder_without_a_wire_is_short_under_the_fixed_shape(tmp_path):
    """The default made-up folder's 85 projected players are fewer than the fixed shape's 156:
    its draft leaves every roster short, as it always has (the pins rest on it); the check says
    so, and a run on the fixed shape notes it rather than refusing it."""
    data = make_data_dir(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    r = ss.read_season(data, 2024, [fc.parse_one("prior")], None, {}, 1, "stat")
    (x,) = ss.short_drafts([r], shapes.FIXED_GRID, 1, "stat", None, {}, {})
    assert (x["need"], x["holds"], x["board"]) == (156, 85, "pool")
    assert sum(len(v) for v in _setup(r, shapes.FIXED).rosters.values()) == 85


def test_no_axis_of_the_grid_changes_what_a_seat_reads(wire_read):
    """What decides which knobs a seat reads (``policy.Shape``: the scoring, held slots, the
    bracket) is one for every shape of the grid, so a run on it has one reads table."""
    _, r, _ = wire_read
    want = policy.shape_of(_setup(r, shapes.FIXED))
    assert {policy.shape_of(_setup(r, x)) for x in shapes.FULL.shapes} == {want}


def test_the_fixed_shape_s_league_is_the_league_before(wire_read):
    """Rule 1: the fixed shape's league is what ``replay_setup`` built before it took a shape."""
    _, r, _ = wire_read
    projection = ss.projection_of(r.served[0], r.fixed, r.lines, 1, 0, "stat")
    period_one = reader.PERIOD_ONE[2024]
    before = rn.replay_setup(2024, r.lines, r.members, projection, period_one, r.scheduled)
    assert _setup(r, shapes.FIXED) == before
    assert before.max_weekly_adds == 4


# --------------------------------------------------------------------------- the visit rule
ROUNDS = (1, 2, 3, 5, 7)


def _turns(rule, rounds: int) -> list[tuple[int, int]]:
    """(shape index, turn) for every path of ``rounds`` rounds of the full grid."""
    return [rule(p) for p in range(72 * rounds)]


def _rule(p: int) -> tuple[int, int]:
    v = shapes.visit(p, shapes.FULL)
    return v.index, v.turn


def _grid_order(p: int) -> tuple[int, int]:
    """The rule with the grid's own order where the place stands (the brief's first rule)."""
    c, j = p % 72, p // 72
    return c, 24 * j + (c // 3 + shapes.STRIDE * j) % 24


def test_on_one_shape_the_turn_is_the_path():
    assert [shapes.visit(p, shapes.FIXED_GRID).turn for p in range(500)] == list(range(500))
    assert {shapes.visit(p, shapes.FIXED_GRID).shape for p in range(500)} == {shapes.FIXED}
    league = shapes.one("league", shapes.FULL.shapes[5])
    assert [shapes.visit(p, league).turn for p in range(50)] == list(range(50))


def test_a_shape_s_place_is_one_to_one_with_its_playoffs_every_third_turn():
    g = shapes.FULL
    places = {}
    for p in range(3):
        for a in range(4):
            for s in range(2):
                x = shapes.place(g, p, a, s)
                assert x % 3 == p and x % 8 == 2 * a + s
                assert x == (16 * p + 9 * (2 * a + s)) % 24
                places[(p, a, s)] = x
    assert sorted(places.values()) == list(range(24))


@pytest.mark.parametrize("rounds", ROUNDS)
def test_every_shape_once_a_round_and_a_team_count_s_seats_within_one(rounds):
    got = _turns(_rule, rounds)
    assert sorted(c for c, _ in got) == sorted(list(range(72)) * rounds)
    for n in (10, 12, 14):
        seats = [t % n for c, t in got if shapes.FULL.shapes[c].teams == n]
        counts = [seats.count(i) for i in range(n)]
        assert max(counts) - min(counts) <= 1
        # A room of 2, 3, 4, 5 or 12 arms: every seat and arm within one visit of even.
        for arms in (2, 3, 4, 5, 12):
            cells = {}
            for c, t in got:
                if shapes.FULL.shapes[c].teams == n:
                    for i in range(n):
                        cells[(i, (i + t) % arms)] = cells.get((i, (i + t) % arms), 0) + 1
            filled = [cells.get((i, a), 0) for i in range(n) for a in range(arms)]
            assert max(filled) - min(filled) <= 1


def test_a_shape_sees_a_new_seat_each_round_for_five_rounds():
    for c, x in enumerate(shapes.FULL.shapes):
        seats = [shapes.visit(72 * j + c, shapes.FULL).turn % x.teams for j in range(5)]
        assert shapes.visit(72 * 4 + c, shapes.FULL).shape == x
        assert len(set(seats)) == 5, (c, seats)


def _largest_gap(rule, rounds: int) -> float:
    """The largest gap, between two values of one axis, in mean draft position (0 the first
    pick, 1 the last) over ``rounds`` rounds."""
    worst = 0.0
    for axis in ("playoffs", "weekly_adds", "slots", "teams"):
        pos: dict[object, list[float]] = {}
        for c, t in _turns(rule, rounds):
            x = shapes.FULL.shapes[c]
            pos.setdefault(shapes.axis_values(x)[axis], []).append((t % x.teams) / (x.teams - 1))
        means = [sum(v) / len(v) for v in pos.values()]
        worst = max(worst, max(means) - min(means))
    return worst


def test_no_axis_s_value_drafts_from_one_end_of_the_order():
    """The places keep each axis's values near even draft positions: the largest gap is under a
    tenth at one round and under a twentieth at two and three. The grid's own order in their
    place fails at one round (one playoff format would draft from the first picks and another
    from the last): that is why the rule has places."""
    assert _largest_gap(_rule, 1) < 0.1
    assert _largest_gap(_rule, 2) < 0.05 and _largest_gap(_rule, 3) < 0.05
    assert _largest_gap(_grid_order, 1) > 0.2
    early = sorted(
        t % 12
        for c, t in _turns(_grid_order, 1)
        if shapes.FULL.shapes[c].teams == 12 and shapes.FULL.shapes[c].playoff_teams == 4
    )
    assert early == list(range(8))


def test_the_paths_round_up_to_the_grid():
    assert shapes.round_up(100, shapes.FULL, True) == 144
    assert shapes.round_up(100, shapes.FULL, False) == 144
    assert shapes.round_up(144, shapes.FULL, True) == 144
    assert [shapes.round_up(n, shapes.FIXED_GRID, True) for n in (1, 12, 20)] == [12, 12, 24]
    assert shapes.round_up(5, shapes.FIXED_GRID, False) == 5
    league = shapes.one("league", shapes.FULL.shapes[0])
    assert shapes.round_up(12, league, True) == 20


def test_a_small_grid_is_visited_by_the_same_rule():
    """A test's grid of few shapes: every shape once a round, its team count's seats within one."""
    small = shapes.Grid("small", (4, 6), (shapes.SLOTS,), (2, None), ((2, 1),))
    assert len(small.shapes) == 4 and small.per_round == 2
    got = [shapes.visit(p, small) for p in range(12)]
    assert [v.index for v in got] == [0, 1, 2, 3] * 3
    for n in (4, 6):
        seats = [v.turn % n for v in got if v.shape.teams == n]
        counts = [seats.count(i) for i in range(n)]
        assert max(counts) - min(counts) <= 1
    with pytest.raises(ValueError, match="share a factor"):
        shapes.Grid("bad", (4,), (shapes.SLOTS, shapes.WIDE_SLOTS), (2, None), ((2, 1), (4, 2)))
