"""A belief for each seat (#172, PR D1): a seat that names a forecaster decides, sets its lineup and
is charged its forced drops on that forecaster's beliefs; every other seat on the run's. The
world's draws stay common, two seats on different forecasters share no decision, the no-peek
check covers the beliefs each seat holds, and a run whose seats all hold the run's forecaster is
the run it was.

The league is the no-peek test's small replay season; the second forecaster misses every
player's level by a factor of its own."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from pickandroll.sim import belief as bf
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import wk
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, arm, make_setup
from tests.sim.test_no_peek import DAYS, SEED, WEIGHTS, recorded

RUN = "run"
OTHER = "other"


def other_forecast(setup) -> dict[int, dict[str, float]]:
    """Every projected player's rates scaled by a factor of his own, from 0.5 to 1.6: the other
    forecaster ranks the players differently."""
    g = np.random.default_rng(11)
    return {
        k: {s: v * float(g.uniform(0.5, 1.6)) for s, v in rates.items()}
        for k, rates in sorted(setup.projection.items())
    }


@pytest.fixture(scope="module")
def season():
    setup, lines = recorded()
    return setup, lines, other_forecast(setup)


def world(setup, lines, other, forecasts=True):
    return rn.replay_world(
        setup,
        lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label=RUN,
        forecasts={OTHER: other} if forecasts else None,
    )


def values(w, day, label=None):
    return wk.per_game_values(w.beliefs_on(day, label), w.setup.cats, None)


def mixed(setup):
    """Seat 1 on the other forecaster, seat 2 on the run's, a market rival and a mirror."""
    return {
        1: op.Seat("B", "surrogate", dict(KNOBS), forecaster=OTHER),
        2: op.Seat("A", "exact", dict(KNOBS)),
        3: op.Market(0.4),
        4: op.Mirror(dict(KNOBS)),
    }


# --------------------------------------------------------------------------- the world
def test_the_world_holds_a_belief_for_each_forecaster(season):
    setup, lines, other = season
    w = world(setup, lines, other)
    day = DAYS[1]
    run, theirs = w.beliefs_on(day), w.beliefs_on(day, OTHER)
    assert w.beliefs_on(day, RUN) is run and w.beliefs_on(day, None) is run
    assert set(run) == set(theirs) and run != theirs
    # Each has its own newcomer's prior: the mean of its own projected players left undrafted.
    undrafted = [k for k in setup.pool if k in other]
    assert w.others[OTHER].newcomer == pytest.approx(
        rn.newcomer_prior({k: other[k] for k in undrafted}, undrafted)
    )
    assert w.others[OTHER].newcomer != w.causal.newcomer
    with pytest.raises(ValueError, match="holds no belief"):
        w.beliefs_on(day, "elsewhere")
    with pytest.raises(ValueError, match="only a causal world"):
        rn.replay_world(setup, lines, 1, SEED, 0, belief="fixed", forecasts={OTHER: other})


def test_a_drawn_world_answers_every_label_with_its_one_belief():
    from tests.sim.sim_league import inputs

    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 1, 0, 0.0)
    day = setup.days[3]
    assert w.beliefs_on(day, OTHER) is w.beliefs_on(day)


# --------------------------------------------------------------------------- the seats
def test_each_seat_decides_and_sets_its_lineup_on_its_own_forecaster(season, monkeypatch):
    setup, lines, other = season
    w = world(setup, lines, other)
    label = {1: OTHER, 2: None, 3: None, 4: None}
    seen: list[tuple[int, date, bool]] = []
    for kind in (op.Seat, op.Mirror):
        real = kind.decide

        def decide(self, setup_, state, team, beliefs, status, returns, g, real=real):
            seen.append((team, state.day, beliefs is w.beliefs_on(state.day, label[team])))
            # The decision is the one ``decide`` gives on the seat's own belief.
            got = real(self, setup_, state, team, beliefs, status, returns, g)
            return got

        monkeypatch.setattr(kind, "decide", decide)
    differs = [0]

    def check(r: rn.DayRecord) -> None:
        assert r.holds == {1: OTHER} and set(r.held) == {OTHER}
        assert r.held[OTHER] is w.beliefs_on(r.day, OTHER)
        for t in setup.teams:
            own = values(w, r.day, label[t])
            want = policy.starters_of(setup, r.state, t, r.day, r.status, own)
            assert r.starters[t] == want
        run_lineup = policy.starters_of(setup, r.state, 1, r.day, r.status, values(w, r.day))
        differs[0] += run_lineup != r.starters[1]

    (res,) = rn.simulate(setup, w, [mixed(setup)], on_day=check)
    assert seen and all(ok for _, _, ok in seen)
    assert {t for t, _, _ in seen} == {1, 2, 4}  # the market rival decides on no belief
    assert differs[0] > 0  # seat 1's lineup is not the one the run's forecaster would set
    assert res.breaches == ()


def test_a_seats_forced_drops_weigh_its_own_forecasters_values():
    """``land`` trims a team's active roster on its own values when ``values`` has them."""
    setup = make_setup()
    state = initial(setup)
    team = setup.teams[0]
    roster = list(state.rosters[team])
    held = [(k, "IL") for k, _ in roster[:1]]
    rest = roster[1:]
    state = replace(state, rosters={**state.rosters, team: tuple(held + rest)})
    spots = sum(1 for _, s in rest if s not in ("IL", "IL+"))
    ids = [k for k, _ in rest]
    run = {k: float(i) for i, k in enumerate(ids)}  # the run's: the first is the weakest
    own = {k: float(-i) for i, k in enumerate(ids)}  # the seat's: the last is the weakest
    status = {held[0][0]: None}
    a = policy.land(state, [team], spots, None, status, run)
    b = policy.land(state, [team], spots, None, status, run, {team: own})
    gone_a = {k for k, _ in state.rosters[team]} - {k for k, _ in a.rosters[team]}
    gone_b = {k for k, _ in state.rosters[team]} - {k for k, _ in b.rosters[team]}
    assert gone_a == {ids[0]} and gone_b == {ids[-1]}
    assert a.forced_by[team] == b.forced_by[team] == 1


def test_two_arms_on_different_forecasters_share_no_decision(season):
    setup, lines, other = season
    a = arm("A", "surrogate", "static")
    b = replace(a, name="B", forecaster=OTHER)
    w = world(setup, lines, other)
    got: dict[tuple[int, date], int] = {}
    real = w.line

    def line(player, day):
        x = real(player, day)
        assert got.setdefault((player, day), id(x)) == id(x)  # one object for both seasons
        return x

    w.line = line  # type: ignore[method-assign]
    out = rn.paired(setup, w, a, b, 1)
    assert out["solves"] > 0 and out["shared"] == 0
    assert out["breaches"] == []
    # The same arm twice in the same world shares every decision: the cache would have shared.
    again = rn.paired(setup, world(setup, lines, other), a, replace(a, name="A"), 1)
    assert again["shared"] == again["solves"] > 0  # B solved nothing of its own
    # The scale reads each arm's own forecaster.
    assert out["scale"]["a"] == again["scale"]["a"]
    assert out["scale"]["b"] != out["scale"]["a"]


def test_a_run_whose_seats_hold_the_runs_forecaster_is_the_run_it_was(season):
    """The world's other beliefs change nothing while no seat names them: the same records and
    results as a world without them."""
    setup, lines, other = season
    variants = [{**rn.opponents_of(setup, x, 1), 1: x.seat()} for x in (arm("A"), arm("B"))]
    runs = []
    for forecasts in (False, True):
        got: dict = {}

        def keep(r: rn.DayRecord, got: dict = got) -> None:
            got[(r.day, r.variant)] = nopeek.digest(r)

        w = world(setup, lines, other, forecasts)
        res = rn.simulate(setup, w, variants, on_day=keep)
        runs.append((got, [(r.summaries, r.solves, r.shared, r.counts) for r in res]))
    assert runs[0] == runs[1]
    assert all(set(d) == set(nopeek.FIELDS) for d in runs[0][0].values())


# --------------------------------------------------------------------------- the checks
def records_of(setup, lines, other, lag: int = 1):
    got: dict[tuple[date, int], dict[str, str]] = {}

    def keep(r: rn.DayRecord) -> None:
        got[(r.day, r.variant)] = nopeek.digest(r)

    w = rn.replay_world(setup, lines, lag, SEED, 0, WEIGHTS, label=RUN, forecasts={OTHER: other})
    res = rn.simulate(setup, w, [mixed(setup)], on_day=keep)
    return got, res


def test_the_no_peek_check_holds_with_two_forecasters(season):
    setup, lines, other = season
    base, _ = records_of(setup, lines, other)
    assert all({"held", "holds"} <= set(d) for d in base.values())
    day = DAYS[1]
    changed = nopeek.perturb(lines, rn.game_days_of(setup), day, SEED)
    got, _ = records_of(setup, changed, other)
    first = nopeek.first_difference(base, got)
    assert first is not None and first[0] > day
    assert all(base[k] == got[k] for k in base if k[0] <= day)


def test_a_peek_in_the_other_forecasters_belief_alone_is_caught(season, monkeypatch):
    """The check's power on the held beliefs: only the other forecaster's belief counts the
    line dated on the day it is read, and the records part on that very day, in ``held``."""
    setup, lines, other = season
    day = DAYS[1]

    class Peeking(bf.CausalBelief):
        def games_before(self, player, d):
            return sum(1 for x in self._dates.get(player, []) if x <= d)

    real = rn.causal_belief

    def causal_belief(setup_, projection, lines_, weights):
        b = real(setup_, projection, lines_, weights)
        if projection is other:
            b.__class__ = Peeking
        return b

    monkeypatch.setattr(rn, "causal_belief", causal_belief)
    base, _ = records_of(setup, lines, other)
    got, _ = records_of(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED), other)
    first = nopeek.first_difference(base, got)
    assert first is not None and first[0] == day
    assert "held" in first[2] and "beliefs" not in first[2]


def test_the_audit_and_the_counts_on_a_two_forecaster_run(season):
    setup, lines, other = season
    _, (res,) = records_of(setup, lines, other)
    assert res.breaches == ()
    assert set(res.counts) == set(setup.teams)
    assert all(row["starter_games"] > 0 for row in res.counts.values())


def test_a_two_forecaster_run_is_deterministic(season):
    setup, lines, other = season
    first, (a,) = records_of(setup, lines, other)
    again, (b,) = records_of(setup, lines, other)
    assert first == again
    assert (a.summaries, a.solves, a.counts) == (b.summaries, b.solves, b.counts)
