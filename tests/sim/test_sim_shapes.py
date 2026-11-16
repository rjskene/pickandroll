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
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import shapes
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


def test_the_fixed_shape_s_league_is_the_league_before(wire_read):
    """Rule 1: the fixed shape's league is what ``replay_setup`` built before it took a shape."""
    _, r, _ = wire_read
    projection = ss.projection_of(r.served[0], r.fixed, r.lines, 1, 0, "stat")
    period_one = reader.PERIOD_ONE[2024]
    before = rn.replay_setup(2024, r.lines, r.members, projection, period_one, r.scheduled)
    assert _setup(r, shapes.FIXED) == before
    assert before.max_weekly_adds == 4
