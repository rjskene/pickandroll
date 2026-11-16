"""A held player's return (#172, PR D4c): the engine's charge and the executor's drop agree.

The engine plans a cleared held player's return with ``moves.comebacks`` (since #406: he takes
an open active spot before anyone is sent); the simulator's executor lands it with
``policy._activate``. On one made-up league, through the names ``sim/engine.py`` gives, they
send the same player: nobody with a spot open, the weakest with none (the keep rule keeping
nobody, which the executor does not see), and on a tie in value the same one of the two.
"""

from __future__ import annotations

from dataclasses import replace

from pickandroll.sim import policy
from pickandroll.sim.engine import mv
from pickandroll.sim.state import BENCH, initial
from tests.sim.sim_league import KNOBS, make_setup

TEAM = 1


def held_return(open_spot: bool, tie: tuple[int, int] | None = None):
    """Seat 1 with one IL player whose status has cleared (IL takes ``O`` only, and his is
    none), its active roster one short of the spots (``open_spot``) or full, and a free agent
    far above everyone, so the keep rule keeps nobody: nobody's season value beats the best
    add's. ``tie``: two of the seat's active players given one line, the weakest two."""
    setup = make_setup(held_slots=("IL",))
    state = initial(setup)
    pool = sorted(state.pool)
    star, rest = pool[-1], pool[:-1]
    projection = dict(setup.projection)
    projection[star] = {s: v * 6 for s, v in projection[star].items()}
    active = [k for k, _ in state.rosters[TEAM]]
    if tie is not None:
        line = {s: v * 0.2 for s, v in projection[min(tie)].items()}
        for k in tie:
            projection[k] = dict(line)
        rosters = {t: tuple(x for x in r if x[0] not in tie) for t, r in state.rosters.items()}
        active = [*tie, *(k for k in active if k not in tie)]
        rest = [k for k in rest if k not in tie]
        state = replace(state, rosters=rosters)
    fill = rest[: setup.spots() - len(active)]
    active = (active + fill)[: setup.spots()]
    rest = [k for k in rest if k not in fill]
    if open_spot:
        held, active = active[-1], active[:-1]
    else:
        held, rest = rest[0], rest[1:]
    roster = (*((k, BENCH) for k in active), (held, "IL"))
    taken = {k for t, r in state.rosters.items() if t != TEAM for k, _ in r}
    setup = replace(setup, projection=projection)
    state = replace(
        state,
        rosters={**state.rosters, TEAM: roster},
        pool=frozenset(k for k in setup.players if k not in taken and k not in dict(roster)),
    )
    status = {held: None}
    problem = policy.problem_of(setup, state, TEAM, KNOBS, setup.projection, status, {}).problem
    assert mv.cleared(problem) == [(held, "IL")] and problem.kept == frozenset()
    assert dict(problem.activation) == {}  # the simulator never chooses an activation (#360)
    assert len(problem.roster) == setup.spots() - open_spot
    return setup, problem, list(roster), status, held


def sent(problem) -> list[int]:
    """Whom the engine charges for the cleared player, on both horizons (one answer)."""
    week, three = ([c.drop for c in mv.comebacks(problem, key, [])] for key in ("week", "three"))
    assert week == three
    return week


def test_with_an_active_spot_open_the_engine_sends_nobody_and_the_executor_drops_nobody():
    setup, problem, roster, status, held = held_return(open_spot=True)
    assert sent(problem) == []
    left = policy._activate(roster, setup.spots(), status, dict(problem.value))
    assert left == [] and (held, BENCH) in roster


def test_with_no_spot_open_the_engine_sends_the_one_player_the_executor_drops():
    setup, problem, roster, status, held = held_return(open_spot=False)
    (engine,) = sent(problem)
    weakest = min((k for k, _ in roster), key=lambda k: problem.value[k])
    assert engine == weakest
    left = policy._activate(roster, setup.spots(), status, dict(problem.value))
    assert left == [engine] and (held, BENCH) in roster


def test_on_a_tie_in_value_the_executor_drops_the_player_the_engine_sends():
    """Ids 9 and 10 order apart as numbers and as text: the engine breaks a tie by the id as
    text, and so does the executor (10 before 9)."""
    setup, problem, roster, status, _ = held_return(open_spot=False, tie=(9, 10))
    assert (
        problem.value[9]
        == problem.value[10]
        < min(v for k, v in problem.value.items() if k in dict(roster) and k not in (9, 10))
    )
    assert sent(problem) == [10]
    assert policy._activate(roster, setup.spots(), status, dict(problem.value)) == [10]
