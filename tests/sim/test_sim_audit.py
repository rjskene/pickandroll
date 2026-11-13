"""The daily audit (#172, PR B2): each rule against a day built by hand to break exactly it, a
clean run with seats that move, and the lineup fixed before the day's lines."""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import timedelta

import pytest

from pickandroll.sim import audit, policy
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.state import initial
from tests.sim.sim_league import arm, inputs, make_setup, rates


def league():
    """Two teams of five on the bench, six free agents, one IL slot, a cap of four adds."""
    return make_setup(teams=2, spots=5, pool=6, weeks=2, playoff_weeks=1, held_slots=("IL",))


def plays(setup, k, day):
    return setup.players[k].nba_team in setup.schedule.get(day, frozenset())


def game_day(setup):
    """A day after the first on which two of team 1's players and one of team 2's play."""
    return next(
        d
        for d in setup.days[1:]
        if sum(plays(setup, k, d) for k, _ in setup.rosters[1]) >= 2
        and any(plays(setup, k, d) for k, _ in setup.rosters[2])
    )


def day_of(setup, state, day, status=None, starters=None, variant=0):
    """The audit's view of ``state`` on ``day``, its lineup set as the policy sets it."""
    status = status or {}
    state = replace(state, day=day)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    if starters is None:
        starters = {t: policy.starters_of(setup, state, t, day, status, value) for t in setup.teams}
    return audit.Day(day, variant, state, status, starters)


def broken(setup, today, before=None) -> dict[str, list]:
    """Every rule's findings on ``today``, by rule, the rules that found nothing left out."""
    out: dict[str, list] = {}
    for rule in audit.RULES:
        got = list(rule.check(setup, today, before))
        if got:
            out[rule.name] = got
    return out


def with_rosters(state, rosters, pool=None):
    return replace(
        state,
        rosters={t: tuple(r) for t, r in rosters.items()},
        pool=frozenset(state.pool if pool is None else pool),
    )


@pytest.fixture
def base():
    setup = league()
    day = game_day(setup)
    state = initial(setup)
    today = day_of(setup, state, day)
    before = day_of(setup, state, day - timedelta(1))
    return setup, state, day, today, before


def test_a_day_as_the_policy_leaves_it_breaks_nothing(base):
    setup, _, _, today, before = base
    assert broken(setup, today, before) == {} and broken(setup, today, None) == {}
    assert [r.name for r in audit.RULES] == [
        "roster_slots",
        "one_place",
        "weekly_adds",
        "lands_next_day",
        "held_kind",
        "lineup",
    ]


def test_roster_slots_finds_too_many_actives_and_an_overfull_held_kind(base):
    setup, state, day, _, _ = base
    extra = sorted(state.pool)[:2]
    rosters = dict(state.rosters)
    rosters[1] = (*rosters[1], *((k, "BN") for k in extra))  # seven active on six spots
    s = with_rosters(state, rosters, state.pool - set(extra))
    today, before = day_of(setup, s, day), day_of(setup, s, day - timedelta(1))
    got = broken(setup, today, before)
    assert set(got) == {"roster_slots"} and got["roster_slots"] == [
        (1, "7 active players on 6 active spots")
    ]
    two = list(state.rosters[2])
    rosters = dict(state.rosters)
    rosters[2] = (*((k, "IL") for k, _ in two[:2]), *two[2:])  # two in the one IL slot
    s = with_rosters(state, rosters)
    status = {k: "O" for k, _ in two[:2]}
    today = day_of(setup, s, day, status)
    got = broken(setup, today, day_of(setup, s, day - timedelta(1), status))
    assert set(got) == {"roster_slots"} and got["roster_slots"] == [
        (2, "2 in IL, the league has 1")
    ]


def test_one_place_finds_a_player_on_two_rosters_and_one_also_on_the_wire(base):
    setup, state, day, _, _ = base
    k = state.rosters[2][0][0]
    rosters = dict(state.rosters)
    rosters[1] = (*rosters[1], (k, "BN"))
    s = with_rosters(state, rosters)
    got = broken(setup, day_of(setup, s, day), day_of(setup, s, day - timedelta(1)))
    assert set(got) == {"one_place"} and got["one_place"] == [(1, f"player {k} on rosters [1, 2]")]
    s = with_rosters(state, state.rosters, state.pool | {k})
    got = broken(setup, day_of(setup, s, day), day_of(setup, s, day - timedelta(1)))
    assert got == {"one_place": [(2, f"player {k} on roster 2 and on the wire")]}


def test_weekly_adds_counts_the_landed_and_the_queued_against_the_cap(base):
    setup, state, day, _, before = base
    free = sorted(state.pool)
    drop = state.rosters[1][0][0]
    at_cap = replace(state, adds_used={1: 3}, pending={1: (mv.Move(free[0], drop),)})
    assert broken(setup, day_of(setup, at_cap, day), before) == {}
    over = replace(state, adds_used={1: 4}, pending={1: (mv.Move(free[0], drop),)})
    got = broken(setup, day_of(setup, over, day), before)
    assert got == {"weekly_adds": [(1, "5 adds this week on a cap of 4")]}
    assert broken(replace(setup, max_weekly_adds=None), day_of(setup, over, day), before) == {}


def test_lands_next_day_wants_every_arrival_queued_the_day_before(base):
    setup, state, day, _, _ = base
    new = min(state.pool)
    out = state.rosters[1][0][0]
    rosters = dict(state.rosters)
    rosters[1] = ((new, "BN"), *rosters[1][1:])
    s = with_rosters(state, rosters, (state.pool - {new}) | {out})
    yesterday = day - timedelta(1)
    got = broken(setup, day_of(setup, s, day), day_of(setup, state, yesterday))
    assert got == {
        "lands_next_day": [(1, f"player {new} joined without a move queued the day before")]
    }
    queued = replace(state, pending={1: (mv.Move(new, out),)})
    assert broken(setup, day_of(setup, s, day), day_of(setup, queued, yesterday)) == {}
    # On the first day the setup's rosters stand for the day before, with nothing queued.
    assert set(broken(setup, day_of(setup, s, day), None)) == {"lands_next_day"}


def test_held_kind_checks_the_status_heard_on_the_day_of_the_placing(base):
    setup, state, day, _, _ = base
    k = state.rosters[1][0][0]
    rosters = dict(state.rosters)
    rosters[1] = ((k, "IL"), *rosters[1][1:])
    s = with_rosters(state, rosters)
    yesterday = day_of(setup, state, day - timedelta(1), {k: "O"})
    got = broken(setup, day_of(setup, s, day, {}), yesterday)
    assert got == {"held_kind": [(1, f"player {k} placed in IL with status None")]}
    assert broken(setup, day_of(setup, s, day, {k: "O"}), yesterday) == {}
    # A player already in the slot the day before was placed then, not today.
    stayed = day_of(setup, s, day - timedelta(1), {k: "O"})
    assert broken(setup, day_of(setup, s, day, {k: "O"}), stayed) == {}


def test_lineup_finds_each_kind_of_bad_start(base):
    setup, state, day, today, before = base
    team = 1
    active = [p for p in state.active(team) if plays(setup, p, day)]
    lineup = dict(today.starters[team])
    k, slot = next(iter(lineup.items()))

    def only_lineup(starters, status=None, on=day):
        t = day_of(setup, state, on, status, {team: starters})
        got = broken(setup, t, before)
        assert set(got) <= {"lineup"}
        return [what for _, what in got.get("lineup", [])]

    assert only_lineup(lineup) == []
    wrong, where = next(
        (p, s)
        for p in active
        for s in setup.starting_slots()
        if not wk.accepts(s, setup.players[p].positions)
    )
    assert only_lineup({wrong: where}) == [f"starter {wrong} is not eligible for {where}"]
    a, b = active[0], active[1]  # every position fits Util, the league starts one
    assert only_lineup({a: "Util", b: "Util"}) == ["2 starters in Util, the league starts 1"]
    assert only_lineup({k: slot}, {k: "O"}) == [f"starter {k} started though heard O"]
    off = next(d for d in setup.days if setup.players[k].nba_team not in setup.schedule.get(d, ()))
    assert only_lineup({k: slot}, on=off) == [f"starter {k}'s team does not play on {off}"]
    other = next(p for p, _ in state.rosters[2] if plays(setup, p, day))
    pos = setup.players[other].positions
    util = "Util" if wk.accepts("Util", pos) else slot
    assert only_lineup({other: util}) == [f"starter {other} is not on the active roster"]


# --------------------------------------------------------------------------- whole runs
def test_a_clean_forward_run_with_seats_that_move_breaks_no_rule():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 11, 0, 0.25)
    out = rn.paired(setup, w, arm("A", "exact"), arm("B", "ranking"), me=1)
    assert out["breaches"] == []
    assert out["counts"]["a"]["landed"] + out["counts"]["b"]["landed"] > 0  # the seats moved


def test_a_clean_replay_with_seats_that_move_breaks_no_rule():
    """A replay world (the causal belief, the recorded lines) and an equal room whose seats move,
    a player out on day one: every day of both arms passes."""
    setup = make_setup(statuses={1: "O"})
    lines = {
        k: {
            d: rates(1.0 + 0.1 * (k % 3))
            for d in setup.days
            if setup.players[k].nba_team in setup.schedule[d]
        }
        for k in setup.players
    }
    w = rn.replay_world(setup, lines, 1, 11, 0)
    arms = {"A": arm("A", "exact"), "B": arm("B", "surrogate")}
    out = rn.room(setup, w, arms, ["A", "B", "A", "B"], 0)
    assert out["breaches"] == []
    assert out["counts"]["A"]["landed"] + out["counts"]["B"]["landed"] > 0  # the seats moved


def test_the_audit_runs_without_a_hook_and_its_rules_can_be_added_to():
    setup = make_setup(teams=2, spots=3, pool=4, weeks=2, playoff_weeks=1)
    w = rn.forward_world(setup, inputs(), 2, 0, 0.0)
    seen = []

    def every(setup_, today, before):
        seen.append((today.day, today.variant))
        if today.day == setup_.start + timedelta(3):
            yield 1, "a rule a later PR adds"

    rules = (*audit.RULES, audit.Rule("extra", every, "a test's rule"))
    variant = {t: arm("A", "ranking").seat() for t in setup.teams}
    (r,) = rn.simulate(setup, w, [variant], rules=rules)
    assert len(seen) == sum(1 for d in setup.days if setup.week_of(d) is not None)
    assert [(b.rule, b.day, b.seat, b.path) for b in r.breaches] == [
        ("extra", setup.start + timedelta(3), 1, 0)
    ]
    # The default rules read every day too: no hook is passed and nothing is found.
    (clean,) = rn.simulate(setup, w, [variant])
    assert clean.breaches == ()


def test_the_lineup_is_set_before_the_days_lines_are_read():
    # No line reaches the lineup: its inputs are the setup, the state, the team, the day, what
    # the seat has heard and the values.
    assert list(inspect.signature(policy.starters_of).parameters) == [
        "setup",
        "state",
        "team",
        "day",
        "status",
        "value",
    ]
    # And changing a day's lines changes nobody's starters that day.
    setup = make_setup(teams=2, spots=5, pool=4, weeks=2, playoff_weeks=1)
    k = setup.rosters[1][0][0]
    days = [d for d in setup.days if setup.players[k].nba_team in setup.schedule[d]]
    lines = {
        p: {d: {"pts": 10.0} for d in setup.days if setup.players[p].nba_team in setup.schedule[d]}
        for p in setup.players
    }
    target = days[3]
    changed = {p: dict(v) for p, v in lines.items()}
    for days_lines in changed.values():
        if target in days_lines:
            days_lines[target] = {"pts": 40.0}
    del changed[k][target]  # he does not play that day either

    def starters_on(these):
        got = {}

        def keep(r):
            if r.day == target:
                got[r.variant] = r.starters

        w = rn.replay_world(setup, these, 1, 1, 0)
        variant = {t: arm("A", "ranking").seat() for t in setup.teams}
        rn.simulate(setup, w, [variant], on_day=keep)
        return got

    assert starters_on(lines) == starters_on(changed)
