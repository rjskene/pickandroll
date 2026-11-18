"""The morning's order with a held slot (#172, Fc's review, finding 1). In every waiver league the
cleared held players come back, the rosters are trimmed and the held players the churns' claims
drop leave (``policy.arrive``) before the claims due are decided (``policy.clear_waivers``), and
then the rest lands (``policy.land``). A claim so meets the roster its team has that morning.

The cases: the reviewer's two, each played three ways an add arrives (a free agent's add with the
rule not named, a claim under continuous waivers, and a claim with the rule not named on a dropped
player clearing the next morning), by priority and by FAAB; and a season under continuous waivers
with a held slot, by priority and by FAAB, in both formats. Made-up leagues, fixed seeds. The
cases' seats weigh nothing (their moves are scripted), so they name no format; the season's seat
weighs and runs in both."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.season import moves as mv
from pickandroll.sim import audit, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import FAILED, WON, Waiting, initial
from tests.sim.sim_league import arm, of_format, recorded_lines
from tests.sim.test_sim_continuous import DAY, league, morning, spots_of

FORMATS = (ONE_WIN, EACH_CATEGORY)
KINDS = ("priority", "faab")
#: How the add arrives: a free agent's add (the rule not named, a player nobody dropped), a
#: claim under the rule, and a claim with the rule not named on a dropped player who clears the
#: morning after it is placed (Fa's case of the same order).
WAYS = ("free_agent", "claim", "dropped_claim")


def full_with_one_held(waivers: str, way: str):
    """Team 2 of a four-team league with an IL slot: its five drafted players, one more on the
    bench (its six active spots full), and ``z`` in the IL slot; ``x`` a free agent, on waivers
    clearing tomorrow for ``dropped_claim``. The setup, the state, x, z, and team 2's
    last-drafted player."""
    rule = CONTINUOUS if way == "claim" else DROPPED
    setup = league(waivers, rule, held_slots=("IL",))
    s = initial(setup)
    x, extra, z = sorted(s.pool)[:3]
    roster = (*s.rosters[2], (extra, "BN"), (z, "IL"))
    s = replace(s, rosters={**s.rosters, 2: roster}, pool=s.pool - {extra, z})
    if way == "dropped_claim":
        s = replace(s, waivers={x: Waiting(setup.start + DAY, 1)})
    return setup, s, x, z, extra, setup.rosters[2][-1][0]


def found(setup, before, after, status=None) -> list[str]:
    """What the audit's rules for the league find between the two states, given the morning's
    ``status`` (a held slot's rule reads it)."""
    days = [audit.Day(x.day, 0, x, status or {}, {}) for x in (before, after)]
    out = []
    for rule in audit.rules_of(setup.waivers, setup.waiver_rule):
        out += [f"{rule.name}: {what}" for _, what in rule.check(setup, days[1], days[0])]
    return out


def play(setup, s, team, decision, status, value):
    spots, _ = spots_of(setup)
    placed = policy.queue(s, team, decision, 1, 4, False, spots, setup)
    out = replace(morning(setup, placed, setup.start + DAY, status, value), day=setup.start + DAY)
    return placed, out


@pytest.mark.parametrize("way", WAYS)
@pytest.mark.parametrize("waivers", KINDS)
def test_a_cleared_held_player_s_trim_comes_before_the_add_so_its_player_stays(waivers, way):
    """``z`` clears the morning team 2's add of ``x`` for ``y`` comes in. The trim takes team 2's
    weakest before x comes. When that is y, the add fails (a claim) or is gone (a free agent's),
    and x stays free. When it is another, x lands for y and stays. Every way the add arrives
    agrees, and the audit finds nothing. Before Fc's review a claim came first and the trim
    could take x himself: by priority ``claim_priority`` found "won claim on player ... not on
    its roster", and by FAAB ``bid_order`` did, the team having paid."""
    setup, s, x, z, extra, y = full_with_one_held(waivers, way)
    decision = policy.Decision((mv.Move(x, y),))
    base = {k: 10.0 for k, _ in s.rosters[2]} | {x: 1.0}
    # The trim takes y, the add's drop.
    placed, out = play(setup, s, 2, decision, {}, {**base, y: 5.0})
    on = {k for k, _ in out.rosters[2]}
    assert x not in on and y not in on and x in out.pool and z in out.active(2)
    assert out.forced_by.get(2) == 1
    if way == "free_agent":
        assert out.resolved == () and out.gone_by.get(2) == 1
    else:
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(2, x, FAILED)]
    assert found(setup, placed, out) == []
    # The trim takes another: x lands for y, and stays.
    placed, out = play(setup, s, 2, decision, {}, {**base, extra: 2.0})
    assert x in out.active(2) and y in out.pool and extra in out.pool and z in out.active(2)
    assert out.forced_by.get(2) == 1
    if way == "free_agent":
        assert out.executed_by.get(2) == 1
    else:
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(2, x, WON)]
    assert found(setup, placed, out) == []


@pytest.mark.parametrize("way", WAYS)
@pytest.mark.parametrize("waivers", KINDS)
def test_a_churn_s_held_player_leaves_before_its_claim_so_the_claim_is_won(waivers, way):
    """A churn: team 2 adds ``x`` dropping its held ``z`` (out), and moves its injured active
    ``w`` to the slot z leaves. z leaves first, so the held-slot move finds its room and x lands,
    every way the add arrives. Before Fc's review the claim was decided while z still held the
    slot: no room, the claim failed, and z left anyway, which no audit rule saw."""
    setup, s, x, z, _, w = full_with_one_held(waivers, way)
    decision = policy.Decision((mv.Move(x, z),), ((w, "IL"),))
    value = {k: 10.0 for k, _ in s.rosters[2]} | {x: 20.0}
    placed, out = play(setup, s, 2, decision, {z: "O", w: "O"}, value)
    slots = dict(out.rosters[2])
    assert slots.get(x) is not None and z not in slots and slots[w] == "IL"
    assert z in out.pool and z in out.waivers
    if way == "free_agent":
        assert out.resolved == () and out.executed_by.get(2) == 1
    else:
        assert [(r.team, r.add, r.outcome) for r in out.resolved] == [(2, x, WON)]
    assert not out.gone_by.get(2) and found(setup, placed, out, {z: "O", w: "O"}) == []


def test_without_a_held_slot_the_first_half_of_the_morning_moves_nothing():
    """No held player comes back and no roster is over its spots, so ``arrive`` leaves a state
    without a held slot as it found it, a churn's drop list aside (empty without a held slot)."""
    setup = league("priority", CONTINUOUS)
    spots, _ = spots_of(setup)
    s = initial(setup)
    order = rn._rotation(setup.teams, 1)
    value = {k: 1.0 for k in setup.players}
    after = policy.arrive(s, order, spots, {}, value, None, (setup.start + DAY, 2))
    assert after == s


# --------------------------------------------------------------------------- a season
#: The first of seeds 1 to 3 and paths 0 to 2, tried in that order, on which the surrogate seat
#: in seat 1 makes a held stint that ends and wins a claim in every kind and format below
#: (``~/sim-notes/vm/scratch/fc/held_path.py``; all nine do).
HELD_PATH = (1, 0)


@pytest.mark.parametrize("h2h", FORMATS)
@pytest.mark.parametrize("waivers", KINDS)
def test_a_season_under_the_rule_with_a_held_slot_plays_clean(waivers, h2h):
    """The rule met a league kind no test played (the lesson of D4c): a six-week made-up league
    of four seats with an IL slot and twelve free agents under continuous waivers, the surrogate
    in seat 1 among market rivals at 0.3 a day. The audit finds nothing, the seat makes a held
    stint that ends (a player in the slot comes back to its active roster), and it wins a
    claim. The season plays alike on Fc's head before the review's fix: on these paths no claim
    meets a comeback, so the cases above test the order and this one the league kind."""
    setup = of_format(league(waivers, CONTINUOUS, held_slots=("IL",), pool=12), h2h)
    u = arm("U", "surrogate", opponents="market")
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *HELD_PATH)
    seen: list = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, 1: u.seat()}
    (result,) = rn.simulate(setup, w, [variant], on_day=lambda r: seen.append(r.state))
    assert result.breaches == ()
    assert result.counts[1]["held_stints"] >= 1
    held = [{k for k, slot in s.rosters[1] if slot in mv.HELD} for s in seen]
    active = [set(s.active(1)) for s in seen]
    ended = {k for i, h in enumerate(held) for k in h if any(k in a for a in active[i + 1 :])}
    assert ended, "no held stint of the seat ended"
    assert any(r.team == 1 and r.outcome == WON for s in seen for r in s.resolved)
