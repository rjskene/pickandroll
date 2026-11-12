"""The search's improve loop never goes round (#364, item 3). On 2026-11-11 21:00 one search of
258901 went round two sets until the 90 s budget ran out: a round undid a move worth less than
``min_gain``, then took a swap that beat the undone set but not the set it started from, and the
next round swapped back. Since the user's ruling of 2026-11-12 a swap must beat the set its round
started from, so that round takes the undo. The cycle guard stays as a backstop: a loop that comes
back to a set stops on the best of the cycle, counts it on the budget, and the answer, the decision
log and the run report say so. Nothing here opens a page.
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
def test_the_258901_shape_ends_on_the_undo_with_no_cycle():
    """Before the user's ruling of 2026-11-12 this went round (10 for 2, 11 for 3, 13 for 1) and
    (10 for 2, 12 for 3, 13 for 1): a round undid 10 for 2, then a swap beat the undone set but
    not the start. A swap now beats the start, so the round takes the undo and the loop ends."""
    p = four_candidates()
    ev = Seeded(p, 800)
    budget = mv.Budget.start(None)
    found = search(ev, budget)
    assert as_set(found) == [(12, 3), (13, 1)]
    full = [mv.Move(10, 2), mv.Move(12, 3), mv.Move(13, 1)]
    # The undone move was worth less than min_gain on the set it left.
    assert 0 < ev.value("week", full) - ev.value("week", found) < 0.01
    assert ev.calls < 1_000
    assert (budget.cycles, budget.cut, budget.searches) == (0, 0, 1)


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


def test_the_guard_keys_the_searchs_own_moves_with_an_owed_il_move_in_the_problem():
    """With a placed claim's IL move owed (#364, items 1 and 2), the move sits in the problem,
    the same for every trial, so the sets the loop stands on hold the search's own moves only:
    every search ends, on a set that fits, and never drops the player the IL slot holds."""
    from tests.test_il_room import OUT, il_league
    from tests.test_pending import claim, folded

    p, players = il_league()
    q = folded(p, [claim(players, 10)])
    assert q.il_owed == ((OUT, "IL"),)
    for seed in range(60):
        budget = mv.Budget.start(None)
        with mv.budgeted(budget):
            found = mv.search(Seeded(q, seed), "week", [11, 12], min_gain=0.01, allowed=drops_only)
        assert mv.feasible(q, found) and all(m.drop != OUT for m in found)
        assert budget.searches == 1 and budget.cut == 0


def test_under_the_ruling_no_seed_goes_round():
    """The guard is a backstop: with a swap judged on the round's start, each round either gains
    on the horizon or undoes a move, so no seeded search of the fixture comes back to a set."""
    p = four_candidates()
    for seed in range(1_000):
        budget = mv.Budget.start(None)
        search(Seeded(p, seed), budget)
        assert budget.cycles == 0, seed


# --------------------------------------------------------------------------- one move a round
P, R, Q, S = mv.Move(10, 1), mv.Move(11, 2), mv.Move(12, 3), mv.Move(13, 1)


class Table:
    """Values by the set of adds; the moves of ``TABLE`` alone are allowed."""

    def __init__(self, problem, table):
        self.problem, self.table, self.base = problem, table, {"week": 0.0}

    def value(self, key, moves):
        return self.table.get(frozenset(m.add for m in moves), 0.0)

    def gain(self, key, moves):
        return self.value(key, moves)


#: Greedy takes P, then R, then Q (each gaining more than min_gain): a start of 0.10. Undoing P
#: loses 0.008, undoing Q 0.015 and undoing R 0.03.
TABLE = {
    frozenset({10}): 0.05,
    frozenset({11}): 0.04,
    frozenset({12}): 0.03,
    frozenset({10, 11}): 0.085,
    frozenset({10, 12}): 0.07,
    frozenset({11, 12}): 0.092,
    frozenset({10, 11, 12}): 0.10,
}


def only(*moves):
    allowed = set(moves)
    return lambda trial: all(m in allowed for m in trial)


def test_a_round_takes_its_best_undo_never_one_a_worse_undo_chained_below():
    ev = Table(four_candidates(), TABLE)
    budget = mv.Budget.start(None)
    with mv.budgeted(budget):
        found = mv.search(ev, "week", [10, 11, 12], min_gain=0.01, allowed=only(P, R, Q))
    # Undoing P (0.092) is taken; undoing Q (0.085) loses more than min_gain and never replaces
    # it, though it clears min_gain below the undo already held.
    assert as_set(found) == [(11, 2), (12, 3)]
    assert budget.cycles == 0


def test_an_undo_within_min_gain_of_a_better_swap_wins():
    # Swapping P for S beats the start by 0.001; undoing P loses 0.009 to that swap: fewer moves
    # win within min_gain.
    ev = Table(four_candidates(), {**TABLE, frozenset({13, 11, 12}): 0.101})
    with mv.budgeted(mv.Budget.start(None)):
        found = mv.search(ev, "week", [10, 11, 12, 13], min_gain=0.01, allowed=only(P, R, Q, S))
    assert as_set(found) == [(11, 2), (12, 3)]
    # A swap more than min_gain better than the undo is taken instead.
    ev = Table(four_candidates(), {**TABLE, frozenset({13, 11, 12}): 0.105})
    with mv.budgeted(mv.Budget.start(None)):
        found = mv.search(ev, "week", [10, 11, 12, 13], min_gain=0.01, allowed=only(P, R, Q, S))
    assert as_set(found) == [(11, 2), (12, 3), (13, 1)]
