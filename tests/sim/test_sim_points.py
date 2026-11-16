"""A points league and held slots in a replay's league (#172, PR D4c): the week, the standings'
tiebreak, and the league ``run.replay_setup`` builds under the league rules."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.sim import adp, shapes
from pickandroll.sim import league as lg
from pickandroll.sim import run as rn
from pickandroll.sim.engine import FPTS, STATS, wk
from pickandroll.sim.state import Member, snake_draft
from tests.sim.draws import between

POINTS = {"pts": 1.0}
TABLE = dict(shapes.POINTS_DEFAULT)
PERIOD_ONE = date(2026, 10, 26)


def spec(tiebreak=lg.TIEBREAK_POINTS) -> lg.LeagueSpec:
    """Four teams, three regular weeks (1v4, 2v3; 1v3, 4v2; 1v2, 3v4), scored on points alone."""
    pairings = {1: ((1, 4), (2, 3)), 2: ((1, 3), (4, 2)), 3: ((1, 2), (3, 4))}
    return lg.LeagueSpec(
        (1, 2, 3, 4), pairings, (4,), (), "points", POINTS, 2, 0, tiebreak=tiebreak
    )


def test_a_points_week_is_one_result_and_carries_the_team_s_points():
    s = spec()
    win = lg.week_result({"pts": 100.0, "reb": 9.0}, {"pts": 99.0}, s)
    assert (win.won, win.lost, win.tied, win.category_wins, win.points_for) == (1, 0, 0, 1, 100)
    tie = lg.week_result({"pts": 80.0}, {"pts": 80.0}, s)
    assert (tie.outcome, tie.category_wins, tie.points_for) == ("T", 0.5, 80.0)
    loss = lg.week_result({"pts": 70.0}, {"pts": 80.0}, s)
    assert (loss.outcome, loss.category_wins) == ("L", 0.0)
    # A categories league's week carries none.
    cats = lg.LeagueSpec((1, 2), {1: ((1, 2),)}, (2,), ("pts",), playoff_teams=2, byes=0)
    assert lg.week_result({"pts": 100.0}, {"pts": 99.0}, cats).points_for == 0.0


def test_a_points_league_breaks_a_tie_on_win_percentage_by_points_for_not_the_team_s_number():
    """Teams 1 and 2 both win twice and tie each other in week 3: one win percentage, one
    head to head and, in a points league, one category count. Team 2 scored more. Under the
    categories league's tiebreak the team's number decides it (team 1 first); under the points
    league's, points for does (team 2 first)."""
    pts = {
        1: {1: 100.0, 2: 100.0, 3: 100.0},
        2: {1: 150.0, 2: 150.0, 3: 100.0},
        3: {1: 50.0, 2: 50.0, 3: 60.0},
        4: {1: 50.0, 2: 50.0, 3: 50.0},
    }
    totals = {w: {t: {"pts": pts[t][w]} for t in pts} for w in (1, 2, 3)}
    old = lg.season(spec(lg.TIEBREAK), totals)
    new = lg.season(spec(), totals)
    for result in (old, new):
        rows = {s.team: s for s in result.standings}
        assert rows[1].pct == rows[2].pct and rows[1].category_wins == rows[2].category_wins
        assert (rows[1].points_for, rows[2].points_for) == (300.0, 400.0)
        # A points league's category wins are its matchup wins, team by team.
        assert all(o.category_wins == o.matchup_wins for o in result.outcomes.values())
    assert [s.team for s in old.standings][:2] == [1, 2]
    assert [s.team for s in new.standings][:2] == [2, 1]
    assert new.outcomes[2].rank == 1 and new.outcomes[1].rank == 2


def made_up_season(n: int = 34, seed: int = 5):
    """``n`` made-up players, each stat drawn on its own (so the two scorings rank them apart),
    every one playing every other day of the season; projected at his line."""
    rng = np.random.default_rng(seed)
    base = {"pts": 14, "threes": 1.5, "reb": 6, "ast": 4, "stl": 1, "blk": 0.8, "tov": 2}
    players, projection, lines = {}, {}, {}
    for k in range(1, n + 1):
        line = {s: base[s] * between(rng, 0.4, 1.6) for s in base}
        fga = 12 * between(rng, 0.5, 1.5)
        fta = 4 * between(rng, 0.5, 1.5)
        line |= {"fga": fga, "fgm": fga * between(rng, 0.38, 0.56)}
        line |= {"fta": fta, "ftm": fta * between(rng, 0.6, 0.9)}
        assert set(line) == set(STATS)
        players[k] = Member(k, f"P{k}", f"T{k % 6}", ("PG",))
        projection[k] = line
        lines[k] = {PERIOD_ONE + timedelta(2 * i): dict(line) for i in range(80)}
    return lines, players, projection


def setup_of(**kw):
    lines, players, projection = made_up_season()
    return projection, rn.replay_setup(2024, lines, players, projection, PERIOD_ONE, teams=2, **kw)


def test_a_points_league_drafts_on_fantasy_points_and_scores_and_breaks_ties_on_them():
    projection, cats = setup_of()
    _, points = setup_of(scoring="points", points=TABLE)
    assert (points.scoring, points.points, points.cats) == ("points", TABLE, (FPTS,))
    spec = points.spec
    assert (spec.scoring, spec.points, spec.cats, spec.tiebreak) == (
        "points",
        TABLE,
        (),
        lg.TIEBREAK_POINTS,
    )
    # The default is today's league: nine categories, their tiebreak.
    assert (cats.scoring, cats.points, cats.spec.tiebreak) == ("categories", None, lg.TIEBREAK)
    assert len(cats.cats) == 9 and FPTS not in cats.cats
    spots = points.spots()
    by_points = wk.per_game_values(projection, cats.cats, TABLE)
    by_cats = wk.per_game_values(projection, cats.cats, None)
    pool = sorted(projection)
    assert points.rosters == snake_draft(pool, by_points, points.teams, spots)
    assert cats.rosters == snake_draft(pool, by_cats, cats.teams, spots)
    # One player the two scorings rank apart: drafted by another seat, or not at all.
    seat = {k: t for t, r in points.rosters.items() for k, _ in r}
    other = {k: t for t, r in cats.rosters.items() for k, _ in r}
    assert any(seat.get(k) != other.get(k) for k in pool)
    first = max(pool, key=lambda k: (by_points[k], -k))
    assert points.rosters[1][0][0] == first != max(pool, key=lambda k: (by_cats[k], -k))


def test_a_seat_s_own_board_under_a_table_values_by_the_league_s_points():
    projection = made_up_season()[2]
    own = {k: projection[k] for k in projection}
    draft = adp.Draft({}, adp.Spread(0, 0.0), 1, 0, {1: own})
    cats = ("pts",)
    boards = rn.draft_boards(draft, sorted(own), {}, (1,), {k: None for k in own}, cats, TABLE)
    assert boards[1] == adp.seat_board(wk.per_game_values(own, cats, TABLE), sorted(own))
    plain = rn.draft_boards(draft, sorted(own), {}, (1,), {k: None for k in own}, cats)
    assert plain[1] == adp.seat_board(wk.per_game_values(own, cats, None), sorted(own))
    assert boards[1] != plain[1]


def test_held_slots_follow_the_bench_and_the_draft_fills_the_active_spots_only():
    rules = shapes.LeagueRules(held=shapes.parse_held("IL=2,IL+=1"))
    slots = rules.slots(shapes.SLOTS)
    _, setup = setup_of(slots=slots)
    assert setup.roster_slots == (*shapes.SLOTS, "IL", "IL", "IL+")
    assert setup.spots() == len(shapes.SLOTS)
    assert all(len(r) == setup.spots() for r in setup.rosters.values())
    assert all(slot not in ("IL", "IL+") for r in setup.rosters.values() for _, slot in r)
    _, plain = setup_of()
    assert setup.rosters == plain.rosters  # the same draft: a held slot starts the season empty


def test_a_points_league_without_a_table_is_refused():
    lines, players, projection = made_up_season(n=4)
    for kw in ({"scoring": "points"}, {"points": TABLE}):
        with pytest.raises(ValueError, match="a points league has a table"):
            rn.replay_setup(2024, lines, players, projection, PERIOD_ONE, teams=2, **kw)
