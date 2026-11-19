"""The stash threshold (#172, PR G). The arm's knob reaches the seat's problem and the engine's
own searches read it there (``moves.stash_ok`` in every set's feasibility): a returning player
is the search's drop with no threshold and is kept at one, on the plain drop and on a churn's
held drop. A mirror rival keeps None and the ranking tier's one swap is not held to it.

Made-up leagues, fixed seeds. The days' seats weigh on one made-up day and compare two decisions
made in the same run, so they name no format (the engine's threshold test reads season values,
never the week's measure)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim.engine import mv
from pickandroll.sim.state import BENCH, initial
from tests.sim.sim_league import KNOBS, make_setup, rates

TEAM = 1
WEEK = timedelta(7)
#: A threshold no add clears: every returning player is kept while another can go.
NEVER = 1e6
#: The tiers that search with the engine.
SEARCH = ("surrogate", "exact")
#: Positions that fit every lineup slot of ``make_setup``'s league (PG, SG, G, C, Util).
ANYWHERE = ("PG", "SG", "C")


def knobs_at(threshold: float | None) -> dict:
    return {**KNOBS, "stash_threshold": threshold}


# --------------------------------------------------------------------------- a made-up day
def a_day(churn: bool):
    """Seat 1 on the first Monday of a six-week league, its six active spots full (its five
    drafted players and ``fill`` from the wire), with ``star``, a free agent far above everyone,
    so the keep rule keeps nobody, and every other free agent far below everyone, so the star is
    the one add worth making. The seat's players and the star fit every lineup slot, so each
    starts whenever he plays and a healthy player's drop costs his games. Without ``churn`` the
    league has no held slot and ``fill`` is
    ``gone``: out (``O``) until the Monday of week five, past the three weeks a set is judged on,
    so dropping him for the star costs the horizon nothing. With ``churn`` the league has an IL
    slot holding ``gone`` (out as long), and the seat's best player ``hurt`` is out until the
    Monday of week three: the star for ``gone`` with ``hurt`` to the slot he leaves keeps every
    game. The setup, the state, the statuses, the return dates, the star, ``gone``, ``hurt``."""
    setup = make_setup(weeks=6, held_slots=("IL",) if churn else ())
    state = initial(setup)
    pool = sorted(state.pool)
    fill, extra, star = pool[0], pool[1], pool[-1]
    mine = [k for k, _ in state.rosters[TEAM]]
    hurt = mine[0]
    gone = extra if churn else fill
    roster = [(k, BENCH) for k in (*mine, fill)] + ([(gone, "IL")] if churn else [])
    wire = [k for k in pool if k != star and k not in dict(roster)]
    low = {k: rates(0.1 + 0.01 * i) for i, k in enumerate(wire)}
    anywhere = {k: replace(setup.players[k], positions=ANYWHERE) for k in (*dict(roster), star)}
    setup = replace(
        setup,
        players={**setup.players, **anywhere},
        projection={**setup.projection, **low, star: rates(3.0)},
    )
    taken = {k for t, r in state.rosters.items() if t != TEAM for k, _ in r} | dict(roster).keys()
    state = replace(
        state,
        rosters={**state.rosters, TEAM: tuple(roster)},
        pool=frozenset(k for k in setup.players if k not in taken),
    )
    status = {gone: "O", **({hurt: "O"} if churn else {})}
    returns = {gone: setup.start + 4 * WEEK, **({hurt: setup.start + 2 * WEEK} if churn else {})}
    return setup, state, status, returns, star, gone, hurt


def decided(day, tier: str, threshold: float | None):
    """The seat's decision on the day and the problem it was made on."""
    setup, state, status, returns, *_ = day
    built = policy.problem_of(
        setup, state, TEAM, knobs_at(threshold), setup.projection, status, returns
    )
    return built, policy.decide(built, tier, with_plan=False)


def edge_of(problem, move: mv.Move) -> float:
    """The share at which the engine's test turns for ``move``'s drop, a returning player: the
    add's worth from the day the move counts over his value net of return, less one."""
    net = mv.returning_net(problem, move.drop)
    worth = mv.worth_from(problem, move.add, mv.day_of(problem, move))
    assert net is not None and worth is not None and worth > net > 0
    return worth / net - 1.0


def test_the_knob_reaches_the_problem_and_none_is_the_problem_before():
    setup, state, status, returns, *_ = a_day(churn=True)

    def problem(threshold):
        return policy.problem_of(
            setup, state, TEAM, knobs_at(threshold), setup.projection, status, returns
        ).problem

    none, share, whole = problem(None), problem(0.25), problem(1)
    assert (
        none.stash_threshold
        is None
        is mv.MoveProblem.__dataclass_fields__["stash_threshold"].default
    )
    assert share.stash_threshold == 0.25
    assert isinstance(whole.stash_threshold, float) and whole.stash_threshold == 1.0
    # Nothing else on the problem moves with the knob: at None it is the problem before PR G.
    assert replace(share, stash_threshold=None) == none == replace(whole, stash_threshold=None)
    assert none.kept == share.kept


@pytest.mark.parametrize("tier", SEARCH)
def test_a_returning_player_is_the_search_s_drop_at_none_and_is_kept_at_a_threshold(tier):
    """The plain drop of an active player who is out. Below the share at which the engine's own
    test turns the decision is the one at None; above it no move drops him."""
    day = a_day(churn=False)
    *_, star, gone, _ = day
    built, at_none = decided(day, tier, None)
    move = mv.Move(star, gone)
    assert at_none.moves == (move,)
    edge = edge_of(built.problem, move)
    assert decided(day, tier, edge / 2)[1].moves == at_none.moves
    above = decided(day, tier, 2 * edge + 1)[1]
    assert [m.add for m in above.moves] == [star] and above.moves[0].drop != gone


@pytest.mark.parametrize("tier", SEARCH)
def test_a_churn_s_held_drop_is_the_search_s_at_none_and_is_kept_at_a_threshold(tier):
    """The same on a churn: the star for the held player, the hurt one to the slot he leaves."""
    day = a_day(churn=True)
    *_, star, gone, hurt = day
    built, at_none = decided(day, tier, None)
    move = mv.Move(star, gone)
    assert at_none.moves == (move,) and at_none.held == ((hurt, "IL"),)
    assert mv.is_churn(built.problem, move)
    edge = edge_of(built.problem, move)
    assert decided(day, tier, edge / 2)[1] == at_none
    above = decided(day, tier, 2 * edge + 1)[1]
    assert above.moves and all(m.drop != gone for m in above.moves)


def test_the_ranking_tier_s_one_swap_is_not_held_to_the_threshold():
    """The ranking tier does not search with the engine: its swap drops the returning player at
    any threshold, as before the reader, though the engine's test on its problem refuses it."""
    day = a_day(churn=False)
    *_, star, gone, _ = day
    built, at_none = decided(day, "ranking", None)
    assert at_none.moves == (mv.Move(star, gone),)
    held_to, kept = decided(day, "ranking", NEVER)
    assert kept == at_none
    assert held_to.problem.stash_threshold == NEVER
    assert not mv.feasible(held_to.problem, at_none.moves) and mv.feasible(
        built.problem, kept.moves
    )


def test_a_mirror_rival_keeps_none():
    """The knob is the arm's own seat's: its mirror rivals are made without it, so two arms that
    differ only in it face one rival, and the rival decides as at None."""
    named = knobs_at(NEVER)
    mirror = op.of({"kind": "mirror"}, named, 0.0)
    assert mirror.knobs == KNOBS and mirror == op.Mirror(KNOBS) == op.Mirror(named)
    assert policy.rival_knobs(named) == KNOBS and policy.rival_knobs({}) == {}
    setup, state, status, returns, _, gone, _ = a_day(churn=False)
    g = np.random.default_rng(0)
    rival = mirror.decide(setup, state, TEAM, setup.projection, status, returns, g)
    assert gone in {m.drop for m in rival.moves}
    own = policy.problem_of(setup, state, TEAM, named, setup.projection, status, returns)
    kept = policy.decide(own, "surrogate", with_plan=False)
    assert kept.moves and gone not in {m.drop for m in kept.moves}
