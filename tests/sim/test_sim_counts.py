"""The mechanism counts (#172, PR B2), by hand on a short scripted run, and per seat summing to
the whole-state counters the runner gave before."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import pytest

from pickandroll.sim import counts as ct
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv
from pickandroll.sim.opponents import Static
from tests.sim.sim_league import KNOBS, arm, inputs, make_setup, rates

MON = date(2026, 10, 26)  # the fixture's first day, a Monday


@dataclass(frozen=True)
class Script:
    """A seat that decides the moves it is given on the days it is given them, each day's with
    the held-slot moves they need (player, slot) when a third item names them."""

    plan: tuple[tuple[Any, ...], ...]
    knobs: Mapping[str, Any] = field(default_factory=lambda: {**KNOBS, "daily_cap": 4})
    kind: str = "seat"

    def decide(self, setup, state, team, beliefs, status, returns, g) -> policy.Decision:
        for day, moves, *held in self.plan:
            if day == state.day:
                return policy.Decision(moves, tuple(held[0]) if held else (), (), 0, "script")
        return policy.NONE


def scripted():
    """Two teams of six on six active spots and one IL slot, a cap of two adds a week. Team 1
    holds a free agent in IL, heard out until Thursday of week one."""
    setup = make_setup(
        teams=2, spots=6, pool=6, weeks=2, playoff_weeks=1, max_weekly_adds=2, held_slots=("IL",)
    )
    free = sorted(setup.pool)
    hurt = free[-1]
    rosters = dict(setup.rosters)
    rosters[1] = (*rosters[1], (hurt, "IL"))
    setup = replace(
        setup,
        rosters=rosters,
        pool=tuple(free[:-1]),
        statuses={hurt: "O"},
        returns={hurt: MON + timedelta(3)},
    )
    one = [k for k, _ in setup.rosters[1] if k != hurt]
    two = [k for k, _ in setup.rosters[2]]
    f1, f2, f3 = free[:3]
    plans = {
        1: Script(
            (
                (MON, (mv.Move(f1, one[0]),)),  # lands Tuesday
                (MON + timedelta(1), (mv.Move(f2, one[1]),)),  # lands Wednesday: the cap
                # Week two: team 2 wants the same player and lands first on Wednesday.
                (MON + timedelta(8), (mv.Move(f3, one[2]),)),
            )
        ),
        2: Script(((MON + timedelta(8), (mv.Move(f3, two[0]),)),)),
    }
    lines = {
        k: {d: rates(1.0) for d in setup.days if setup.players[k].nba_team in setup.schedule[d]}
        for k in setup.players
    }
    return setup, lines, plans, hurt, (f1, f2, f3)


def test_the_counts_by_hand_on_a_short_run():
    setup, lines, plans, hurt, (_, _, f3) = scripted()
    w = rn.replay_world(setup, lines, 1, 1, 0)
    records = []
    (r,) = rn.simulate(setup, w, [plans], on_day=records.append)
    one, two = r.counts[1], r.counts[2]
    # Team 1: two moves landed in week one, at the cap; the third lost to team 2, who landed
    # first; his held player back on Thursday over the spots, the weakest active dropped.
    assert one["landed"] == 2 and one["gone"] == 1 and one["forced_drops"] == 1
    assert one["adds_per_week"] == pytest.approx(1.0) and one["weeks_at_cap"] == pytest.approx(0.5)
    assert one["held_stints"] == 1 and one["held_days"] == 3  # Monday to Wednesday in IL
    assert one["held_refused"] == 0 and two["held_refused"] == 0
    assert two["landed"] == 1 and two["gone"] == 0 and two["forced_drops"] == 0
    assert two["adds_per_week"] == pytest.approx(0.5) and two["weeks_at_cap"] == 0.0
    assert two["held_stints"] == 0 and two["held_days"] == 0
    final = records[-1].state
    assert f3 in {k for k, _ in final.rosters[2]} and f3 not in {k for k, _ in final.rosters[1]}
    assert hurt in {k for k, _ in final.rosters[1]}  # back from IL on the bench
    # The starters' games: every starter has a line on every day his team plays.
    for t in (1, 2):
        played = sum(1 for rec in records for k in rec.starters[t] if lines.get(k, {}).get(rec.day))
        assert r.counts[t]["starter_games"] == played > 0
    # Per seat, the counts sum to the whole-state counters.
    assert (r.executed, r.gone, r.forced_drops) == (3, 1, 1)
    assert sum(c["landed"] for c in r.counts.values()) == r.executed
    assert sum(c["gone"] for c in r.counts.values()) == r.gone
    assert sum(c["forced_drops"] for c in r.counts.values()) == r.forced_drops
    assert r.breaches == ()


def test_a_refused_held_move_is_counted_for_its_seat():
    """Team 1 at its six spots, its IL slot empty, one active player heard out until Thursday.
    On Wednesday, the last day the seat hears him out, it queues him for IL with a no-drop add;
    by Thursday morning his status has cleared, so the move is refused and the add has no spot:
    one refusal and one move lost, both team 1's, and nobody placed or forced out."""
    setup = make_setup(
        teams=2, spots=6, pool=6, weeks=2, playoff_weeks=1, max_weekly_adds=2, held_slots=("IL",)
    )
    hurt = setup.rosters[1][0][0]
    told = MON + timedelta(3)
    setup = replace(setup, statuses={hurt: "O"}, returns={hurt: told})
    free = min(setup.pool)
    wednesday = told - timedelta(1)
    plans = {1: Script(((wednesday, (mv.Move(free),), ((hurt, "IL"),)),)), 2: Static()}
    lines = {
        k: {d: rates(1.0) for d in setup.days if setup.players[k].nba_team in setup.schedule[d]}
        for k in setup.players
    }
    records = []
    (r,) = rn.simulate(
        setup, rn.replay_world(setup, lines, 1, 1, 0), [plans], on_day=records.append
    )
    heard = {rec.day: rec.status.get(hurt) for rec in records}
    assert heard[wednesday] == "O" and heard[told] is None
    one = r.counts[1]
    assert one["held_refused"] == 1 and one["gone"] == 1 and one["landed"] == 0
    assert one["held_stints"] == 0 and one["forced_drops"] == 0
    assert r.counts[2]["held_refused"] == 0 and r.held_refused == 1
    final = records[-1].state
    assert dict(final.rosters[1])[hurt] != "IL" and free in final.pool
    assert r.breaches == ()


def test_the_counts_per_seat_sum_to_what_the_runner_counted_before():
    """A forward run with held slots: the whole-state counters are the ones main gave at d6fee43
    (executed, gone and forced drops of each variant), and the seats sum to them."""
    setup = make_setup(held_slots=("IL", "IL+"), seed=3, weeks=8)
    w = rn.forward_world(setup, inputs(), 11, 0, 0.25)
    a, b = arm("A", "exact"), arm("B", "surrogate")
    variants = [{**rn.opponents_of(setup, x, 1), 1: x.seat()} for x in (a, b)]
    results = rn.simulate(setup, w, variants, [a.execute_plan, b.execute_plan])
    assert [(r.executed, r.gone, r.forced_drops) for r in results] == BEFORE
    for r in results:
        assert sum(c["landed"] for c in r.counts.values()) == r.executed
        assert sum(c["gone"] for c in r.counts.values()) == r.gone
        assert sum(c["forced_drops"] for c in r.counts.values()) == r.forced_drops
        assert set(r.counts) == set(setup.teams) and set(r.counts[1]) == set(ct.METRICS)


def test_pooled_rows_are_the_mean_over_the_seats_that_have_each():
    rows = [
        {**dict.fromkeys(ct.METRICS, 1.0), "weeks_at_cap": None},
        {**dict.fromkeys(ct.METRICS, 3.0), "weeks_at_cap": 0.5},
    ]
    got = ct.pooled(rows)
    assert got["landed"] == 2.0 and got["weeks_at_cap"] == 0.5
    assert ct.row_of({1: rows[0], 2: rows[1]}, [1]) == rows[0]
    assert ct.row_of({1: rows[0]}, []) is None


#: The whole-state counters of the run above under main at d6fee43, before they were per seat.
BEFORE = [(5, 1, 2), (4, 1, 2)]
