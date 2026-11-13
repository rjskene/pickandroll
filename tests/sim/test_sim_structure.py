"""The policy's inputs carry no world (#172, PR B2): a spy on a real run sees every ``decide``
receive a setup, a state, a seat, the beliefs, the statuses, the return dates and a generator,
and nothing else. (That ``policy.py`` and ``opponents.py`` import nothing from ``run.py`` is read
from the source in ``test_boundary.py``; the determinism of the commands is in
``test_season_sim_script.py``.)"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

import numpy as np
import pytest

from pickandroll.sim import run as rn
from pickandroll.sim.state import Setup, SimState
from tests.sim.sim_league import arm, inputs, make_setup, rates


class Spy:
    """A strategy that hands each call on to ``inner`` and keeps what it was handed. Its repr is
    the inner one's, so the runner's cache of shared decisions sees the same keys."""

    def __init__(self, inner: Any, calls: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> None:
        self.inner, self.calls = inner, calls

    @property
    def kind(self) -> str:
        return self.inner.kind

    @property
    def knobs(self) -> Any:
        return getattr(self.inner, "knobs", None)

    def __repr__(self) -> str:
        return repr(self.inner)

    def decide(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.inner.decide(*args, **kwargs)


def rates_of(m: Any) -> bool:
    return isinstance(m, Mapping) and all(
        isinstance(s, str) and isinstance(v, float) for s, v in m.items()
    )


def check_call(setup: Setup, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    assert kwargs == {} and len(args) == 7
    got_setup, state, team, beliefs, status, returns, g = args
    assert got_setup is setup
    assert type(state) is SimState and state.day in setup.days
    assert type(team) is int and team in setup.teams
    assert isinstance(beliefs, Mapping) and beliefs
    assert all(type(k) is int and rates_of(v) for k, v in beliefs.items())
    assert isinstance(status, Mapping)
    assert all(type(k) is int and (v is None or type(v) is str) for k, v in status.items())
    assert isinstance(returns, Mapping)
    assert all(type(k) is int and type(v) is date for k, v in returns.items())
    assert type(g) is np.random.Generator
    assert not any(isinstance(a, rn.World) for a in args)


def worlds(setup: Setup) -> dict[str, rn.World]:
    lines = {
        k: {
            d: rates(1.0 + 0.1 * (k % 3))
            for d in setup.days
            if setup.players[k].nba_team in setup.schedule[d]
        }
        for k in setup.players
    }
    return {
        "forward": rn.forward_world(setup, inputs(), 11, 0, 0.25),
        "replay": rn.replay_world(setup, lines, 1, 11, 0),
    }


@pytest.mark.parametrize("kind", ["forward", "replay"])
def test_every_decide_is_handed_the_problems_inputs_and_nothing_else(kind):
    setup = make_setup(statuses={1: "O"}, held_slots=("IL",))
    w = worlds(setup)[kind]
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    a, b = arm("A", "exact"), arm("B", "surrogate")
    variants = [
        {t: Spy(s, calls) for t, s in {**rn.opponents_of(setup, x, 1), 1: x.seat()}.items()}
        for x in (a, b)
    ]
    rn.simulate(setup, w, variants, [a.execute_plan, b.execute_plan])
    for args, kwargs in calls:
        check_call(setup, args, kwargs)
    # Every seat decided, on every simulated day, and the seats of both kinds were spied on.
    days = [d for d in setup.days if setup.week_of(d) is not None]
    assert {args[2] for args, _ in calls} == set(setup.teams)
    assert {args[1].day for args, _ in calls} == set(days)
    assert {type(v.inner).__name__ for v in variants[0].values()} >= {"Market"}
    assert any(args[2] == 1 for args, _ in calls) and any(args[2] != 1 for args, _ in calls)
