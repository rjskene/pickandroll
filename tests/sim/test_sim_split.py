"""The roster split of a ``yahoo`` or ``blend`` seat (#172, PR D1): every player on a roster
that morning reads the first stand-in's belief, every other player the system's table. The table
follows the rosters: before the landing for the forced drops, after it for the decision, the
lineup, the day record and the score. A ``bbm`` seat and a seat on a plain forecaster read what
they read before the split.

The league is the no-peek test's small replay season; the second stand-in misses every player's
level by a factor of its own."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.belief import consistent
from pickandroll.sim.engine import wk
from tests.sim.sim_league import arm
from tests.sim.test_no_peek import DAYS, SEED, WEIGHTS, recorded

RUN = "run"
FIRST, SECOND = "espn", "marcel"
SOURCES = (fc.Forecaster(FIRST), fc.Forecaster(SECOND))


def second_of(projection) -> dict[int, dict[str, float]]:
    """The first's rates, every player's scaled by a factor of his own from 0.5 to 1.6, a fifth
    of them left unprojected: the second ranks the players differently and covers fewer."""
    g = np.random.default_rng(11)
    out = {}
    for k, rates in sorted(projection.items()):
        scale = float(g.uniform(0.5, 1.6))
        if g.random() < 0.2:
            continue
        out[k] = {s: v * scale for s, v in rates.items()}
    return out


@pytest.fixture(scope="module")
def season():
    setup, lines = recorded()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    return setup, lines, first, second_of(first)


def fixed_of(first, second) -> ss.Fixed:
    return ss.Fixed({FIRST: first, SECOND: second}, {})


def armed(*specs: tuple[str, str, float | None]) -> dict[str, rn.Arm]:
    """Surrogate arms by name, system and blend, each believing by its system."""
    arms = {}
    for name, system, blend in specs:
        a = arm(name, "surrogate", "market")
        arms[name] = replace(a, knobs={**a.knobs, "system": system, "blend": blend})
    return ss.believing(arms, SOURCES)


def world_of(setup, lines, first, second, arms, label=RUN, run_lines=None):
    forecasts = ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", arms)
    return rn.replay_world(
        setup,
        run_lines or lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label=label,
        forecasts=forecasts,
        split=ss.splits_of(SOURCES, arms),
    )


def variant_of(setup, arms, seats):
    """The arms in their seats, the market in every other."""
    rivals = rn.opponents_of(setup, next(iter(arms.values())), 0)
    return {**rivals, **{t: arms[name].seat() for t, name in seats.items()}}


def run(setup, w, variant, on_day=None):
    got: list[rn.DayRecord] = []

    def keep(r: rn.DayRecord) -> None:
        got.append(r)
        if on_day is not None:
            on_day(r)

    (res,) = rn.simulate(setup, w, [variant], on_day=keep)
    return got, res


def assert_split(w, r, label):
    """The seat's table on day ``r.day``: the first's belief of every rostered player, the
    system's of every other, absent where the side it reads has none."""
    table = r.held[label]
    on = rn.rostered_of(r.state)
    first, system = w.beliefs_on(r.day, FIRST), w.beliefs_on(r.day, label)
    for k in set(table) | set(first) | set(system):
        want = (first if k in on else system).get(k)
        assert table.get(k) == want, (r.day, k, k in on)
    return on


# --------------------------------------------------------------------------- the split
@pytest.mark.parametrize(("system", "blend"), [("yahoo", None), ("blend", 0.25)])
def test_a_split_seat_reads_the_first_for_rostered_players_and_its_system_for_the_rest(
    season, system, blend, monkeypatch
):
    setup, lines, first, second = season
    arms = armed(("Y", system, blend))
    label = arms["Y"].forecaster
    assert label in ss.splits_of(SOURCES, arms)
    w = world_of(setup, lines, first, second, arms)
    seen: dict[date, dict] = {}
    real = op.Seat.decide

    def decide(self, setup_, state, team, beliefs, status, returns, g):
        if team == 1:
            seen[state.day] = dict(beliefs)
        return real(self, setup_, state, team, beliefs, status, returns, g)

    monkeypatch.setattr(op.Seat, "decide", decide)
    records, res = run(setup, w, variant_of(setup, arms, {1: "Y"}))
    parts = [0, 0]
    for r in records:
        assert r.holds == {1: label}
        on = assert_split(w, r, label)
        # The seat decided on the table its record holds: one table a day.
        assert seen[r.day] == r.held[label]
        # Both sides are read: a rostered player the system projects reads the first's line.
        parts[0] += sum(1 for k in on if w.beliefs_on(r.day, label).get(k) != r.held[label].get(k))
        parts[1] += sum(1 for k in r.held[label] if k not in on)
    assert parts[0] > 0 and parts[1] > 0
    assert res.breaches == ()
    if system == "blend":
        # The available side is the mix at the share: neither source's line alone.
        table = ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", arms)
        assert table[label] == fc.system_rates("blend", 0.25, first, second)
        both = [k for k in second if k in first]
        assert all(
            table[label][k] not in (consistent(first[k]), consistent(second[k])) for k in both
        )


def test_the_table_follows_the_rosters_yesterdays_moves_in(season):
    """A player a team added yesterday reads the first's line today; the player it dropped, on
    no roster now, reads the system's."""
    setup, lines, first, second = season
    arms = armed(("Y", "yahoo", None))
    label = arms["Y"].forecaster
    w = world_of(setup, lines, first, second, arms)
    records, _ = run(setup, w, variant_of(setup, arms, {1: "Y"}))
    checked = 0
    for r in records:
        on = rn.rostered_of(r.state)
        firsts, system = w.beliefs_on(r.day, FIRST), w.beliefs_on(r.day, label)
        for moves in r.landed.values():
            for m in moves:
                assert m.add in on
                assert r.held[label].get(m.add) == firsts.get(m.add)
                if m.drop is not None and m.drop not in on:
                    assert r.held[label].get(m.drop) == system.get(m.drop)
                    checked += 1
    assert checked > 0


def test_the_forced_drops_are_weighed_on_the_rosters_before_the_landing(season, monkeypatch):
    """At the landing the seat's values are its table on the rosters as they stood before
    anything landed; from there on, on the rosters after it. The two differ on a day a move
    lands."""
    setup, lines, first, second = season
    arms = armed(("Y", "yahoo", None))
    label = arms["Y"].forecaster
    w = world_of(setup, lines, first, second, arms)
    points = None
    landed: dict[date, tuple] = {}
    real = policy.land
    day = [None]

    def land(state, order, spots=None, slot_counts=None, status=None, value=None, values=None):
        d = day[0]
        if values and 1 in values:
            table = rn.split_beliefs(
                w.beliefs_on(d, label), w.beliefs_on(d, FIRST), rn.rostered_of(state)
            )
            assert values[1] == wk.per_game_values(table, setup.cats, points)
            landed[d] = (values[1], rn.rostered_of(state))
        return real(state, order, spots, slot_counts, status, value, values)

    def status_on(d, _real=w.status_on):
        day[0] = d
        return _real(d)

    monkeypatch.setattr(policy, "land", land)
    monkeypatch.setattr(w, "status_on", status_on)
    records, _ = run(setup, w, variant_of(setup, arms, {1: "Y"}))
    apart = 0
    for r in records:
        before, rostered = landed[r.day]
        after = wk.per_game_values(r.held[label], setup.cats, points)
        if rostered != rn.rostered_of(r.state):
            apart += before != after
        else:
            assert before == after
    assert apart > 0


def test_a_forced_drop_is_weighed_on_the_first_line():
    """``land`` trims a split seat's active roster on the values it is handed: the rostered
    players' first-side values, here the reverse of the system's."""
    from pickandroll.sim.state import initial
    from tests.sim.sim_league import make_setup

    setup = make_setup()
    state = initial(setup)
    team = setup.teams[0]
    roster = list(state.rosters[team])
    held, rest = roster[:1], roster[1:]
    state = replace(state, rosters={**state.rosters, team: ((held[0][0], "IL"), *rest)})
    spots = sum(1 for _, s in rest if s not in ("IL", "IL+"))
    ids = [k for k, _ in rest]
    on = rn.rostered_of(state)
    system = {k: {"pts": float(i)} for i, k in enumerate(ids)}  # the first is the weakest
    firsts = {k: {"pts": float(-i)} for i, k in enumerate(ids)}  # the last is the weakest
    table = rn.split_beliefs(system, firsts, on)
    assert table == firsts  # every one of them is on a roster
    value = {k: r["pts"] for k, r in table.items()}
    out = policy.land(state, [team], spots, None, {held[0][0]: None}, None, {team: value})
    assert {k for k, _ in state.rosters[team]} - {k for k, _ in out.rosters[team]} == {ids[-1]}


# --------------------------------------------------------------------------- bbm and plain
def test_a_bbm_seat_and_a_yahoo_seat_in_one_room_each_read_their_own(season, monkeypatch):
    setup, lines, first, second = season
    arms = armed(("B", "bbm", None), ("Y", "yahoo", None))
    yahoo = arms["Y"].forecaster
    assert arms["B"].forecaster == FIRST and ss.splits_of(SOURCES, arms) == {yahoo: FIRST}
    w = world_of(setup, lines, first, second, arms)
    seen: dict[tuple[int, date], object] = {}
    real = op.Seat.decide

    def decide(self, setup_, state, team, beliefs, status, returns, g):
        seen[(team, state.day)] = beliefs
        return real(self, setup_, state, team, beliefs, status, returns, g)

    monkeypatch.setattr(op.Seat, "decide", decide)
    records, res = run(setup, w, variant_of(setup, arms, {1: "B", 2: "Y"}))
    for r in records:
        assert r.holds == {1: FIRST, 2: yahoo}
        # The bbm seat reads the first's belief whole, as before the split.
        assert r.held[FIRST] == w.beliefs_on(r.day, FIRST) == seen[(1, r.day)]
        assert_split(w, r, yahoo)
        assert seen[(2, r.day)] == r.held[yahoo]
    assert res.breaches == ()


def test_a_plain_seat_reads_what_it_read_before_the_split(season):
    """A world that holds a split label changes nothing for a seat on a plain label: its
    records equal those of a world without the split."""
    setup, lines, first, second = season
    arms = armed(("B", "bbm", None))
    digests = []
    for split in (False, True):
        w = rn.replay_world(
            setup,
            lines,
            1,
            SEED,
            0,
            WEIGHTS,
            label=RUN,
            forecasts={FIRST: first, "yahoo(x)": second},
            split={"yahoo(x)": FIRST} if split else None,
        )
        records, _ = run(setup, w, variant_of(setup, arms, {1: "B"}))
        digests.append([nopeek.digest(r) for r in records])
    assert digests[0] == digests[1]


# --------------------------------------------------------------------------- the world
def test_the_first_is_held_with_no_bbm_arm_and_off_the_runs_forecaster(season):
    setup, lines, first, second = season
    arms = armed(("Y", "yahoo", None))
    forecasts = ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", arms)
    assert set(forecasts) == {arms["Y"].forecaster, FIRST} and forecasts[FIRST] is first
    w = world_of(setup, lines, first, second, arms)
    assert FIRST in w.others and w.split == {arms["Y"].forecaster: FIRST}
    # Without a split label the first is not held for its own sake.
    plain = ss.believing({"P": arm("P", "surrogate", "market")}, SOURCES)
    assert set(
        ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", plain)
    ) == {FIRST}
    assert ss.splits_of(SOURCES, plain) == {} and ss.splits_of(None, arms) == {}
    with pytest.raises(ValueError, match="holds no belief"):
        rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS, label=RUN, split={"y": FIRST})


def test_the_first_on_the_runs_forecaster_is_the_runs_belief(season):
    """When the first stand-in is the run's forecaster, a split seat's rostered side is the
    run's belief."""
    setup, lines, _, _ = season
    first = dict(setup.projection)
    second = second_of(first)
    arms = armed(("Y", "yahoo", None))
    label = arms["Y"].forecaster
    w = world_of(setup, lines, first, second, arms, label=FIRST)
    assert FIRST not in w.others
    records, res = run(setup, w, variant_of(setup, arms, {1: "Y"}))
    for r in records[::7]:
        on = rn.rostered_of(r.state)
        run_belief = w.beliefs_on(r.day)
        assert all(r.held[label].get(k) == run_belief.get(k) for k in on)
    assert res.breaches == ()


# --------------------------------------------------------------------------- the checks
def test_the_no_peek_check_holds_with_a_split_seat(season):
    setup, lines, first, second = season
    arms = armed(("B", "bbm", None), ("Y", "blend", 0.25))

    def records_of(these):
        w = world_of(setup, lines, first, second, arms, run_lines=these)
        records, _ = run(setup, w, variant_of(setup, arms, {1: "Y", 2: "B"}))
        return {(r.day, r.variant): nopeek.digest(r) for r in records}

    base = records_of(lines)
    assert all({"held", "holds"} <= set(d) for d in base.values())
    day = DAYS[1]
    got = records_of(nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    first_diff = nopeek.first_difference(base, got)
    assert first_diff is not None and first_diff[0] > day
    # The same seed twice: the same records.
    assert records_of(lines) == base


def test_a_split_seats_scale_reads_its_table(season):
    """The season scale lands on the table of the first state and scales on the table after."""
    setup, lines, first, second = season
    arms = armed(("Y", "yahoo", None), ("B", "bbm", None))
    w = world_of(setup, lines, first, second, arms)
    y, b = rn.scale_on(setup, w, arms["Y"], 1), rn.scale_on(setup, w, arms["B"], 1)
    assert y is not None and b is not None and y != b
    assert rn.scale_on(setup, w, arms["Y"], 1) == y
