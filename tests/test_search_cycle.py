"""The search's improve loop never goes round (#364, item 3). On 2026-11-11 21:00 one search of
258901 went round two sets until the 90 s budget ran out: a round undid a move worth less than
``min_gain``, then took a swap that beat the undone set but not the set it started from, and the
next round swapped back. The loop now stops on the best set of the cycle, counts it on the budget,
and the answer, the decision log and the run report say so. Wherever the search ends today its
answer is the same. Nothing here opens a page.
"""

from __future__ import annotations

import random

from pickandroll.routine import run
from pickandroll.season import moves as mv
from tests.test_moves import build, player, rates, streaming_league
from tests.test_routine import PUBLIC, Clock, FakeAPI, base_answers, make_ctx

#: More value calls than a search over this pool needs a hundred times over.
CALLS = 20_000


class Loops(Exception):
    """The search went on past :data:`CALLS` value calls: it went round."""


def four_candidates():
    roster, cands, rate, sched, opponent, field = streaming_league()
    cands = [*cands, player(12, "HLD"), player(13, "HLD")]
    rate = {**rate, 12: rates(0.8), 13: rates(0.7)}
    return build(roster, cands, rate, sched, opponent, field)


class Seeded:
    """A value with interactions: each move worth up to 0.04, each pair of moves up to 0.015
    more or less. Seed 800 makes the improve loop go round two three-move sets: it is the first
    seed that does, the 258901 pattern on a small league."""

    def __init__(self, problem: mv.MoveProblem, seed: int) -> None:
        self.problem, self.seed, self.calls = problem, seed, 0
        self.base = {"week": 0.0}

    def _r(self, x) -> float:
        return random.Random(f"{self.seed}:{x}").random()

    def value(self, key, moves) -> float:
        self.calls += 1
        if self.calls > CALLS:
            raise Loops
        k = tuple(sorted((m.add, m.drop) for m in moves))
        one = sum(0.04 * self._r(m) for m in k)
        return one + sum(
            0.03 * (self._r((a, b)) - 0.5) for i, a in enumerate(k) for b in k[i + 1 :]
        )

    def gain(self, key, moves) -> float:
        return self.value(key, moves) - self.base[key]


def drops_only(trial) -> bool:
    """Every add with a drop, at most three: the sets of the fixture."""
    return all(m.drop is not None for m in trial) and len(trial) <= 3


def search(ev, budget=None):
    with mv.budgeted(budget):
        return mv.search(ev, "week", [10, 11, 12, 13], min_gain=0.01, allowed=drops_only)


def as_set(moves):
    return sorted((m.add, m.drop) for m in moves)


# --------------------------------------------------------------------------- the search
def test_a_search_that_goes_round_two_sets_stops_on_the_better_of_them():
    p = four_candidates()
    ev = Seeded(p, 800)
    budget = mv.Budget.start(None)
    found = search(ev, budget)
    # The loop went round (10 for 2, 11 for 3, 13 for 1) and (10 for 2, 12 for 3, 13 for 1):
    # it stops on the second, the better one, within a few hundred value calls.
    assert as_set(found) == [(10, 2), (12, 3), (13, 1)]
    other = [mv.Move(10, 2), mv.Move(11, 3), mv.Move(13, 1)]
    assert ev.value("week", found) > ev.value("week", other)
    assert ev.calls < 1_000
    assert (budget.cycles, budget.cut, budget.searches) == (1, 0, 1)


def test_a_search_that_never_goes_round_counts_no_cycle():
    p = four_candidates()
    for seed in (0, 1, 2):
        budget = mv.Budget.start(None)
        search(Seeded(p, seed), budget)
        assert budget.cycles == 0 and budget.searches == 1


def test_the_best_of_a_cycle_of_any_length_is_the_first_nothing_later_beats():
    a, b, c = ([mv.Move(10, 1)], [mv.Move(11, 1)], [mv.Move(12, 1)])
    by_value = lambda v, t, than, other: v > than
    assert mv.cycle_best([(a, 1.0), (b, 3.0), (c, 2.0)], by_value) == (b, 3.0)
    # Three sets equal on the horizon: the first is kept unless the season is better.
    season = {10: 0.0, 11: 5.0, 12: 1.0}
    tie = lambda v, t, than, other: (
        v > than or (v == than and season[t[0].add] > season[other[0].add])
    )
    assert mv.cycle_best([(a, 1.0), (b, 1.0), (c, 1.0)], tie) == (b, 1.0)
    assert mv.cycle_best([(a, 1.0), (b, 1.0), (c, 1.0)], by_value) == (a, 1.0)


# --------------------------------------------------------------------------- the run report
def test_the_solve_step_names_the_leagues_cut_by_the_budget_or_stopped_on_a_cycle(tmp_path):
    cut, cycled = PUBLIC[0], PUBLIC[1]
    answers = base_answers()
    answers[("GET", f"/seasons/{cut}/moves")] = (
        200,
        {"sets": [], "search": {"cut": True, "searches": 11, "finished": 1, "cycle": False}},
    )
    answers[("GET", f"/seasons/{cycled}/moves")] = (
        200,
        {"sets": [], "search": {"cut": False, "searches": 14, "finished": 14, "cycle": True}},
    )
    ctx = make_ctx(FakeAPI(answers), Clock("2026-10-29 05:01"), tmp_path)
    solve = run("daily", ctx, "http://api").find("solve")
    assert solve.status == "ok"
    assert solve.detail.endswith(
        f"; cut by the budget: {cut} (1 of 11); stopped on a cycle: {cycled}"
    )
    assert solve.data["cut"] == [f"{cut} (1 of 11)"] and solve.data["cycled"] == [cycled]
