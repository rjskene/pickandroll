"""The stash threshold (#172, PR G). The arm's knob reaches the seat's problem and the engine's
own searches read it there (``moves.stash_ok`` in every set's feasibility): a returning player
is the search's drop with no threshold and is kept at one, on the plain drop and on a churn's
held drop. A mirror rival keeps None and the ranking tier's one swap is not held to it.

And the morning a held player comes back: a seat that plans with the engine names whom he sends
(``policy.sends_of``: ``moves.comebacks`` on the seat's own problem, so the keep rule and the
threshold are the seat's), and the world only checks it (``policy.arrive``). The day's choice of
an activation's drop (``moves.choose_activation``) is not built: no problem a seat decides on
holds a cleared player (the README's limits, "What the executor sees since PR G").

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
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.state import BENCH, initial
from tests.sim.sim_league import KNOBS, make_setup, rates
from tests.sim.test_sim_held_morning import KINDS, WAYS, found, full_with_one_held, play

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


# --------------------------------------------------------------------------- the morning
def return_day(weekday: int):
    """Seat 1 with an IL slot on the first Monday (``weekday`` 0) or Tuesday (1) of a six-week
    league: its best drafted player ``back`` in the slot, out (``O``) and told back today, so
    his status clears tomorrow morning; its six active spots full with its other four, ``low``
    and ``nxt``, its two weakest and both below the league's average, ``low`` the weaker and out
    (``O``, no date: back next Monday). Every free agent is weaker still, so nobody is beaten by
    the best add. On the Monday ``low`` is a week from back and the keep rule lets him go; on the
    Tuesday he is back inside a week and it keeps him on the bench (``moves.kept_of``'s short
    absence). The setup, the state, the statuses, the return dates, ``back``, ``low``, ``nxt``."""
    setup = make_setup(weeks=6, held_slots=("IL",))
    state = initial(setup)
    pool = sorted(state.pool)
    low, nxt, wire = pool[0], pool[1], pool[2:]
    back, *rest = (k for k, _ in state.rosters[TEAM])
    projection = {
        **setup.projection,
        low: rates(0.3),
        nxt: rates(0.35),
        **{k: rates(0.1 + 0.01 * i) for i, k in enumerate(wire)},
    }
    setup = replace(setup, projection=projection)
    roster = (*((k, BENCH) for k in (*rest, low, nxt)), (back, "IL"))
    day = setup.start + timedelta(weekday)
    state = replace(state, day=day, rosters={**state.rosters, TEAM: roster}, pool=frozenset(wire))
    return setup, state, {back: "O", low: "O"}, {back: day}, back, low, nxt


def named_on(day, tier: str, threshold: float | None):
    """The seat's decision on the day, and the problem it was made on."""
    setup, state, status, returns, *_ = day
    built = policy.problem_of(
        setup, state, TEAM, knobs_at(threshold), setup.projection, status, returns
    )
    return built, policy.decide(built, tier, with_plan=False)


def next_morning(day, decision, names: bool = True):
    """The state the morning after ``decision`` is queued: ``back``'s status has cleared, the
    rest stands. ``names`` False: the seat's names are taken off, as for a seat that names none."""
    setup, state, status, _, back, *_ = day
    spots = setup.spots()
    placed = policy.queue(state, TEAM, decision, 1, setup.max_weekly_adds, False, spots, setup)
    if not names:
        placed = replace(placed, sends={})
    value = wk.per_game_values(setup.projection, setup.cats, None)
    cleared = {k: s for k, s in status.items() if k != back}
    out = policy.land(placed, setup.teams, spots, None, cleared, value)
    return placed, replace(out, day=state.day + timedelta(1)), cleared


@pytest.mark.parametrize("tier", SEARCH)
def test_the_keep_rule_moves_the_drop_a_returning_held_player_forces(tier):
    """On the Tuesday the keep rule keeps ``low`` on the bench, so the engine's plan charges
    ``nxt``, and ``nxt`` is who leaves; the rule before PR G, which a seat that names none still
    gets, sends ``low``, the least valuable by the day's values. On the Monday the keep rule
    keeps neither and both rules send ``low``. (The surrogate solves on neither Tuesday: it
    names on every day.)"""
    for weekday, charged in ((1, "nxt"), (0, "low")):
        day = return_day(weekday)
        setup, _, _, _, back, low, nxt = day
        who = {"low": low, "nxt": nxt}[charged]
        built, decision = named_on(day, tier, None)
        assert (low in built.problem.kept) is (weekday == 1) and nxt not in built.problem.kept
        assert (
            built.problem.value[low]
            < built.problem.value[nxt]
            == min(
                v
                for k, v in built.problem.value.items()
                if k in dict(built.problem.roster) and k != low
            )
        )
        assert decision.moves == () and decision.sends == ((back, who),)
        placed, out, status = next_morning(day, decision)
        assert placed.sends == {TEAM: ((back, who),)} and out.sends == {}
        assert back in out.active(TEAM) and who in out.pool and out.forced_by == {TEAM: 1}
        assert set(out.active(TEAM)) == set(placed.active(TEAM)) - {who} | {back}
        assert found(setup, placed, out, status) == []
        _, before, _ = next_morning(day, decision, names=False)
        assert low in before.pool and nxt in before.active(TEAM) and before.forced_by == {TEAM: 1}


@pytest.mark.parametrize("tier", SEARCH)
def test_the_threshold_moves_the_drop_a_returning_held_player_forces(tier):
    """On the Monday ``low`` is a returning player the keep rule does not keep. With no
    threshold the plan charges him; at a threshold ``nxt``, the one who would go instead, does
    not clear, the engine leaves him out of the choice (``moves.guarded_pool``) and ``nxt``
    leaves. The world reads no knob: the same morning without the seat's names sends ``low``."""
    day = return_day(0)
    setup, _, _, _, back, low, nxt = day
    built, at_none = named_on(day, tier, None)
    assert mv.returning_net(built.problem, low) is not None
    assert mv.returning_net(built.problem, nxt) is None
    assert at_none.sends == ((back, low),)
    _, kept = named_on(day, tier, NEVER)
    assert kept.sends == ((back, nxt),)
    placed, out, status = next_morning(day, kept)
    assert nxt in out.pool and low in out.active(TEAM) and back in out.active(TEAM)
    assert out.forced_by == {TEAM: 1} and found(setup, placed, out, status) == []
    _, unnamed, _ = next_morning(day, kept, names=False)
    assert low in unnamed.pool and nxt in unnamed.active(TEAM)


def test_a_named_drop_that_has_left_the_roster_falls_back_and_an_open_spot_sends_nobody():
    day = return_day(0)
    setup, state, _, _, back, low, nxt = day
    _, kept = named_on(day, "surrogate", NEVER)
    assert kept.sends == ((back, nxt),)
    # ``nxt`` left overnight (not by a move of the seat's): the rule before PR G sends ``low``.
    roster = tuple(x for x in state.rosters[TEAM] if x[0] != nxt)
    short = replace(state, rosters={**state.rosters, TEAM: roster}, pool=state.pool | {nxt})
    wire = wk.per_game_values(setup.projection, setup.cats, None)
    names = replace(short, sends={TEAM: kept.sends})
    cleared = {low: "O"}
    # One spot is open now: he takes it and nobody leaves, named or not.
    out = policy.land(names, setup.teams, setup.spots(), None, cleared, wire)
    assert back in out.active(TEAM) and low in out.active(TEAM) and out.forced_by == {}
    # Full again with another player, the named one still gone: the least valuable leaves.
    other = max(state.pool)
    full = replace(
        names,
        rosters={**names.rosters, TEAM: (*roster, (other, BENCH))},
        pool=names.pool - {other},
    )
    out = policy.land(full, setup.teams, setup.spots(), None, cleared, wire)
    weakest = min((k for k, s in full.rosters[TEAM] if s == BENCH), key=lambda k: wire[k])
    assert weakest in out.pool and back in out.active(TEAM) and out.forced_by == {TEAM: 1}
    # The plan named the returning player himself: he is active once back, and he leaves.
    own = replace(full, sends={TEAM: ((back, back),)})
    out = policy.land(own, setup.teams, setup.spots(), None, cleared, wire)
    assert back in out.pool and weakest in out.active(TEAM) and out.forced_by == {TEAM: 1}


@pytest.mark.parametrize("way", WAYS)
@pytest.mark.parametrize("waivers", KINDS)
def test_the_named_drop_leaves_before_the_claims_so_the_add_finds_its_drop(waivers, way):
    """The morning's order of Fc's review (``arrive``, ``clear_waivers``, ``land``) with a name:
    ``z`` clears the morning team 2's add of ``x`` for ``y`` comes in, and ``y`` is its least
    valuable by the day's values. The rule before PR G takes ``y`` and the add fails or is gone
    (``test_sim_held_morning``'s first case). The seat's plan charged ``extra``: he leaves, on
    waivers like anyone who leaves a roster, and the add lands for ``y``, every way it arrives,
    by priority and by FAAB, under both waiver rules. The seat's moves are scripted, so the case
    names no format."""
    setup, s, x, z, extra, y = full_with_one_held(waivers, way)
    decision = policy.Decision((mv.Move(x, y),), sends=((z, extra),))
    value = {k: 10.0 for k, _ in s.rosters[2]} | {x: 1.0, y: 5.0}
    placed, out = play(setup, s, 2, decision, {}, value)
    assert placed.sends == {2: ((z, extra),)} and out.sends == {}
    assert x in out.active(2) and z in out.active(2) and y in out.pool and extra in out.pool
    assert out.forced_by == {2: 1} and not out.gone_by.get(2)
    assert out.waivers[extra].by == 2 and out.waivers[extra].clears == out.day + timedelta(2)
    assert found(setup, placed, out) == []


def test_a_name_made_on_one_day_is_replaced_by_the_next_day_s():
    """The names are one night's. On the Monday the seat names ``low``; ``back`` is told a day
    later and does not clear, so the morning spends the name unused. On the Tuesday the keep
    rule keeps ``low`` and the seat names ``nxt``: he is who leaves the morning ``back`` does
    come back. A decision with no name takes the team's off, and another team's stand."""
    setup, state, status, _, back, low, nxt = return_day(0)
    spots = setup.spots()
    value = wk.per_game_values(setup.projection, setup.cats, None)
    tuesday = state.day + timedelta(1)

    def decide(s, told):
        built = policy.problem_of(
            setup, s, TEAM, knobs_at(None), setup.projection, status, {back: told}
        )
        return policy.decide(built, "surrogate")

    first = decide(state, tuesday)
    assert first.sends == ((back, low),)
    placed = policy.queue(state, TEAM, first, 1, None, False, spots, setup)
    morning = replace(policy.land(placed, setup.teams, spots, None, status, value), day=tuesday)
    assert morning.rosters == state.rosters and morning.sends == {} and morning.forced_by == {}
    second = decide(morning, tuesday)
    assert second.sends == ((back, nxt),)
    placed = policy.queue(
        replace(morning, sends={TEAM: first.sends, 2: ((1, 2),)}),
        TEAM,
        second,
        1,
        None,
        False,
        spots,
        setup,
    )
    assert placed.sends == {TEAM: ((back, nxt),), 2: ((1, 2),)}
    out = policy.land(placed, setup.teams, spots, None, {low: "O"}, value)
    assert nxt in out.pool and low in out.active(TEAM) and back in out.active(TEAM)
    none = policy.queue(placed, TEAM, policy.Decision(), 1, None, False, spots, setup)
    assert none.sends == {2: ((1, 2),)}


def test_an_add_with_no_drop_still_meets_the_morning_s_order():
    """A limit the README names: the seat adds into its open spot and its plan charges ``low``
    for ``back``'s return, with the add in. The morning brings ``back`` first: he takes the open
    spot, nobody leaves (the roster is not over its spots), and the add finds no spot."""
    setup, state, _, _, back, low, nxt = return_day(0)
    roster = tuple(x for x in state.rosters[TEAM] if x[0] != nxt)
    short = replace(state, rosters={**state.rosters, TEAM: roster}, pool=state.pool | {nxt})
    decision = policy.Decision((mv.Move(nxt),), sends=((back, low),))
    placed = policy.queue(short, TEAM, decision, 1, None, False, setup.spots(), setup)
    value = wk.per_game_values(setup.projection, setup.cats, None)
    out = policy.land(placed, setup.teams, setup.spots(), None, {low: "O"}, value)
    assert back in out.active(TEAM) and low in out.active(TEAM) and nxt in out.pool
    assert out.forced_by == {} and out.gone_by == {TEAM: 1}
