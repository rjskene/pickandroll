"""SEASON SIM (#172, PR take-in): the leagues the take-in's equality test plays, and what it
compares of them.

Each case is a made-up season played with every take-in knob off (the tests' arms,
``sim_league.KNOBS``): ``later_weeks`` uncapped and the four rates at 0. Its digest is every
day's rosters, moves queued, claims placed and decided, and starters, by variant, all whole
numbers, so it does not rest on a float's last bit. The digests in ``test_sim_takein`` were
taken from the simulator before the take-in (main ``faf143c``, with #490); the test plays the
same cases on the code of now and asks for the same digests: outcome for outcome."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from pickandroll.sim import run as rn
from pickandroll.sim.shapes import CONTINUOUS, TODAY
from tests.sim.sim_league import arm, every_category, make_setup, replay_of

#: A points league's table (the bid seasons' test's).
POINTS = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0, "threes": 1.0}
#: The seat the arms sit in.
ME = 1


def digest(records: list[rn.DayRecord]) -> str:
    """Every day's whole-number facts of a season, by variant, hashed."""
    rows = []
    for r in records:
        rows.append(
            [
                r.day.isoformat(),
                r.variant,
                {
                    str(t): sorted([k, s] for k, s in ros)
                    for t, ros in sorted(r.state.rosters.items())
                },
                {str(t): [[m.add, m.drop] for m in ms] for t, ms in sorted(r.queued.items())},
                {
                    str(t): [[c.move.add, c.move.drop, c.bid] for c in cs]
                    for t, cs in sorted(r.claims.items())
                },
                [[c.team, c.add, c.drop, c.outcome, c.bid] for c in r.cleared],
                {
                    str(t): sorted([k, s] for k, s in st.items())
                    for t, st in sorted(r.starters.items())
                },
            ]
        )
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]


def _base(**kw: Any):
    return make_setup(weeks=5, **kw)


def _points(setup):
    return replace(
        setup,
        scoring="points",
        points=POINTS,
        cats=("fpts",),
        spec=replace(setup.spec, scoring="points", points=POINTS, cats=()),
    )


#: Each league by name: its setup.
LEAGUES: dict[str, Callable[[], Any]] = {
    "plain": lambda: _base(),
    "held": lambda: _base(held_slots=("IL",), statuses={2: "O", 7: "O"}),
    "points": lambda: _points(_base()),
    "priority": lambda: replace(_base(), waivers="priority", waiver_days=2),
    "faab": lambda: replace(_base(), waivers="faab", waiver_days=2),
    "continuous": lambda: replace(_base(), waivers="faab", waiver_days=2, waiver_rule=CONTINUOUS),
    "each": lambda: every_category(_base()),
    "same_day": lambda: replace(_base(), lineup_from=TODAY),
}


def arms() -> dict[str, rn.Arm]:
    """The seats played in every league: both tiers on mirror rivals, the queue's rule, and an
    arm that executes its streaming plan on plan floors of -1."""
    return {
        "exact": arm("exact", "exact", "mirror"),
        "surrogate": arm("surrogate", "surrogate", "mirror"),
        "queue": replace(arm("queue", "exact", "mirror"), executes="queue"),
        "plan": replace(
            arm("plan", "exact", "mirror", plan_floor_cats=-1.0, plan_floor_points=-1.0),
            execute_plan=True,
        ),
    }


def played(league: str, a: rn.Arm) -> tuple[str, rn.VariantResult]:
    """``a``'s season in seat :data:`ME` of ``league`` on path 0 of seed 2: its digest and its
    result."""
    setup = LEAGUES[league]()
    w = replay_of(setup, 2, 0)
    variant = {**rn.opponents_of(setup, a, ME), ME: a.seat()}
    got: list[rn.DayRecord] = []
    (res,) = rn.simulate(setup, w, [variant], [a.execute_plan], on_day=got.append)
    return digest(got), res


def season(league: str, a: rn.Arm) -> str:
    """The digest of ``a``'s season in seat :data:`ME` of ``league`` on path 0 of seed 2."""
    return played(league, a)[0]


#: The split seats (PR D1): a ``yahoo`` and a ``blend`` seat on the split test's season.
SPLITS = {"split_yahoo": ("yahoo", None), "split_blend": ("blend", 0.25)}


def split_season(name: str) -> str:
    """The digest of a split seat's season, on the exact tier with mirror rivals, in seat
    :data:`ME` of the split test's made-up season (its two stand-ins)."""
    from pickandroll.sim import cli as ss
    from tests.sim.test_no_peek import recorded
    from tests.sim.test_sim_split import SOURCES, second_of, world_of

    system, blend = SPLITS[name]
    setup, lines = recorded()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    second = second_of(first)
    a = arm("Y", "exact", "mirror")
    a = replace(a, knobs={**a.knobs, "system": system, "blend": blend})
    arms_ = ss.believing({"Y": a}, SOURCES)
    w = world_of(setup, lines, first, second, arms_)
    variant = {**rn.opponents_of(setup, arms_["Y"], ME), ME: arms_["Y"].seat()}
    got: list[rn.DayRecord] = []
    rn.simulate(setup, w, [variant], on_day=got.append)
    return digest(got)
