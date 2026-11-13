"""A held move lands only if the slot still accepts the player (#172): a queued move is carried
out against the day it lands. The held-slot move is made only while the slot has room and accepts
the player's status that morning (``moves.eligible``); one it does not accept is refused
(``held_refused``), frees no spot, and the add that needed the spot meets the usual check."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.state import initial
from tests.sim.sim_league import arm, inputs, make_setup


def queued_for(kind: str = "IL"):
    """A league with one ``kind`` slot. Team 1 is at its spots (its five drafted players and
    ``hurt``, out), the held slot empty. On the day the seat is told ``hurt`` returns it still
    hears him out, queues him for the held slot and a no-drop add (the pool's best) into the
    bench spot that frees. Returns the setup, the queued state, ``hurt``, ``add`` and the
    league's spots and slot counts."""
    setup = make_setup(held_slots=(kind,))
    free = sorted(initial(setup).pool)
    hurt, add = free[1], free[2]
    projection = dict(setup.projection)
    projection[add] = {s: v * 2 for s, v in projection[add].items()}
    rosters = {**setup.rosters, 1: (*setup.rosters[1], (hurt, "BN"))}
    setup = replace(setup, rosters=rosters, projection=projection)
    state = initial(setup)
    spots, counts = setup.spots(), Counter(setup.roster_slots)
    assert len(state.active(1)) == spots and state.held(1) == ()
    decision = policy.Decision((mv.Move(add),), ((hurt, kind),), (), 1, "x")
    queued = policy.queue(state, 1, decision, 2, 4, spots=spots)
    assert queued.pending_held[1] == ((hurt, kind),) and queued.pending[1] == (mv.Move(add),)
    return setup, queued, hurt, add, spots, counts


def values(setup):
    return wk.per_game_values(setup.projection, setup.cats, None)


def test_a_player_cleared_overnight_stays_active_and_the_add_is_gone():
    """The case the audit found: heard out on the told day, queued for IL with a no-drop add,
    his status cleared by the morning the move lands. He stays active, the IL slot stays empty,
    the add has no spot and is gone, and the day after nobody is forced out."""
    setup, queued, hurt, add, spots, counts = queued_for("IL")
    value = values(setup)
    landed = policy.land(queued, [1], spots, counts, {}, value)
    slots = dict(landed.rosters[1])
    assert slots[hurt] == "BN" and hurt in landed.active(1)
    assert landed.held(1) == () and add not in slots and add in landed.pool
    assert landed.held_refused == 1 and landed.gone == 1 and landed.executed == 0
    assert landed.forced_drops == 0 and len(landed.active(1)) == spots
    after = policy.land(replace(landed, day=landed.day), [1], spots, counts, {}, value)
    assert after.forced_drops == 0 and after.rosters == landed.rosters


def test_a_held_move_the_slot_still_accepts_lands_as_before():
    setup, queued, hurt, add, spots, counts = queued_for("IL")
    landed = policy.land(queued, [1], spots, counts, {hurt: "O"}, values(setup))
    assert dict(landed.rosters[1])[hurt] == "IL" and dict(landed.rosters[1])[add] == "BN"
    assert landed.executed == 1 and landed.gone == 0 and landed.held_refused == 0
    # The same as the executor without statuses, which makes the move on room alone.
    assert landed.rosters == policy.land(queued, [1], spots, counts).rosters


@pytest.mark.parametrize(("kind", "made"), [("IL", False), ("IL+", True)])
def test_out_turning_to_day_to_day_overnight(kind, made):
    """Heard out when queued, GTD by the morning: IL no longer takes him, IL+ does."""
    setup, queued, hurt, add, spots, counts = queued_for(kind)
    landed = policy.land(queued, [1], spots, counts, {hurt: "GTD"}, values(setup))
    slot = dict(landed.rosters[1])[hurt]
    assert (slot == kind) is made and (slot == "BN") is not made
    assert (add in landed.active(1)) is made
    assert landed.held_refused == (0 if made else 1)
    assert (landed.executed, landed.gone) == ((1, 0) if made else (0, 1))


def test_without_statuses_the_executor_is_unchanged():
    """``status=None`` (no statuses given): the held move is made on room alone, as before."""
    _, queued, hurt, add, spots, counts = queued_for("IL")
    landed = policy.land(queued, [1], spots, counts)
    assert dict(landed.rosters[1])[hurt] == "IL" and add in landed.active(1)
    assert landed.held_refused == 0 and landed.executed == 1 and landed.gone == 0


def test_no_held_slot_ever_holds_a_player_it_does_not_accept():
    """Every day record of 18 paths of a league with IL and IL+, my seat exact against
    surrogate (the paths the audit found the breach on): each held player fits his slot under
    the status heard that day. On main two of these paths had a player in IL with no status."""
    found, refused = [], 0
    for seed in (3, 5, 8):
        setup = make_setup(held_slots=("IL", "IL+"), seed=seed, weeks=8)
        a, b = arm("A", "exact"), arm("B", "surrogate")
        variants = [{**rn.opponents_of(setup, x, 1), 1: x.seat()} for x in (a, b)]
        for path in range(6):

            def check(r: rn.DayRecord, seed: int = seed, path: int = path) -> None:
                for team, roster in r.state.rosters.items():
                    for k, slot in roster:
                        if slot in mv.HELD and not mv.eligible(r.status.get(k), slot):
                            found.append((seed, path, r.day, r.variant, team, k, slot))

            w = rn.forward_world(setup, inputs(), 11, path, 0.25)
            results = rn.simulate(setup, w, variants, [a.execute_plan, b.execute_plan], check)
            refused += sum(r.held_refused for r in results)
    assert found == []
    assert refused > 0  # not vacuous: the executor refused the moves that broke the rule
