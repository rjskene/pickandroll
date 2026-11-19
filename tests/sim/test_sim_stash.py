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
never the week's measure); the seasons that ask what the seat does run in both, and a season
that names one says why."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from dataclasses import replace
from datetime import datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import forecast as fc
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN, mv, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED
from pickandroll.sim.state import BENCH, Claim, Waiting, initial
from tests.sim.sim_league import (
    KNOBS,
    arm,
    make_data_dir,
    make_setup,
    of_format,
    rates,
    recorded_lines,
)
from tests.sim.test_no_peek import WEIGHTS
from tests.sim.test_sim_continuous import morning
from tests.sim.test_sim_held_morning import KINDS, WAYS, found, full_with_one_held, play
from tests.sim.test_sim_seasons import rounded
from tests.sim.test_sim_split import second_of

TEAM = 1
DAY = timedelta(1)
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
    assert at_none.moves == (move,) and gone in at_none.returning
    edge = edge_of(built.problem, move)
    assert decided(day, tier, edge / 2)[1].moves == at_none.moves
    above = decided(day, tier, 2 * edge + 1)[1]
    assert [m.add for m in above.moves] == [star] and above.moves[0].drop != gone
    assert above.returning == at_none.returning


@pytest.mark.parametrize("tier", SEARCH)
def test_a_churn_s_held_drop_is_the_search_s_at_none_and_is_kept_at_a_threshold(tier):
    """The same on a churn: the star for the held player, the hurt one to the slot he leaves."""
    day = a_day(churn=True)
    *_, star, gone, hurt = day
    built, at_none = decided(day, tier, None)
    move = mv.Move(star, gone)
    assert at_none.moves == (move,) and at_none.held == ((hurt, "IL"),)
    assert mv.is_churn(built.problem, move) and at_none.returning == {gone, hurt}
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


def test_two_arms_apart_only_in_the_threshold_are_two_seats_where_it_is_read():
    """A replay refuses a pair that differs only in what neither arm reads. On the tiers that
    search with the engine the threshold is read, with or without a held slot, so the pair runs;
    on the ranking tier and for a static seat it is refused by name, with why and what reads it."""
    shapes = [policy.Shape(), policy.Shape(held=True)]
    for tier in SEARCH:
        a = arm("A", tier)
        assert rn.same_seat(a, replace(a, name="B", knobs=knobs_at(0.25)), shapes) is None
    read_by = policy.WHEN_READ["stash_threshold"]
    for tier, why in (("ranking", policy.RANKING_STASH), ("static", policy.STATIC)):
        a = arm("A", tier)
        refused = rn.same_seat(a, replace(a, name="B", knobs=knobs_at(0.25)), shapes)
        assert refused == [f"stash_threshold ({why}; read by {read_by})"]
    # Mirror rivals read nothing more of it: they keep None, so the two arms face one rival.
    r = arm("A", "ranking", "mirror")
    refused = rn.same_seat(r, replace(r, name="B", knobs=knobs_at(0.25)), shapes)
    assert refused == [f"stash_threshold ({policy.RANKING_STASH}; read by {read_by})"]


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
def return_day(weekday: int, week: int = 0, slot: str = "IL", heard: str = "O"):
    """Seat 1 with an IL slot on the first Monday (``weekday`` 0) or Tuesday (1) of a six-week
    league: its best drafted player ``back`` in the slot, out (``O``) and told back today, so
    his status clears tomorrow morning; its six active spots full with its other four, ``low``
    and ``nxt``, its two weakest and both below the league's average, ``low`` the weaker and out
    (``O``, no date: back next Monday). Every free agent is weaker still, so nobody is beaten by
    the best add. On the Monday ``low`` is a week from back and the keep rule lets him go; on the
    Tuesday he is back inside a week and it keeps him on the bench (``moves.kept_of``'s short
    absence). ``week``: the same day that many weeks on (5: the season's last week); ``slot``
    and ``heard``: the held slot and ``back``'s status in it. The setup, the state, the
    statuses, the return dates, ``back``, ``low``, ``nxt``."""
    setup = make_setup(weeks=6, held_slots=(slot,))
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
    roster = (*((k, BENCH) for k in (*rest, low, nxt)), (back, slot))
    day = setup.start + week * WEEK + timedelta(weekday)
    state = replace(state, day=day, rosters={**state.rosters, TEAM: roster}, pool=frozenset(wire))
    return setup, state, {back: heard, low: "O"}, {back: day}, back, low, nxt


def named_on(day, tier: str, threshold: float | None):
    """The seat's decision on the day, and the problem it was made on."""
    setup, state, status, returns, *_ = day
    built = policy.problem_of(
        setup, state, TEAM, knobs_at(threshold), setup.projection, status, returns
    )
    return built, policy.decide(built, tier, with_plan=False)


def next_morning(day, decision, names: bool = True, execute_plan: bool = False):
    """The state the morning after ``decision`` is queued: ``back``'s status has cleared, the
    rest stands. ``names`` False: the seat's names are taken off, as for a seat that names none.
    ``execute_plan``: the arm executes its week plan, so the plan's steps due are queued too."""
    setup, state, status, _, back, *_ = day
    spots = setup.spots()
    placed = policy.queue(
        state, TEAM, decision, 1, setup.max_weekly_adds, execute_plan, spots, setup
    )
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


def test_a_ranking_seat_names_none_and_its_morning_is_the_rule_before():
    """A seat that does not plan with the engine, by its own decision and not by a name taken
    off: on the Tuesday the ranking tier's decision carries no name, at any threshold, though
    its problem holds ``back`` and its keep rule keeps ``low``. So the morning ``back`` comes
    back sends ``low``, the least valuable active player by the day's values, as before PR G;
    the seat's own swap (the wire's best by value times games for ``nxt``) then lands."""
    day = return_day(1)
    setup, _, _, _, back, low, nxt = day
    for threshold in (None, NEVER):
        built, decision = named_on(day, "ranking", threshold)
        assert low in built.problem.kept and dict(built.problem.held_slots) == {back: "IL"}
        assert decision.source == "ranking" and decision.sends == ()
        assert [m.drop for m in decision.moves] == [nxt]
        placed, out, status = next_morning(day, decision)
        assert placed.sends == {} and out.forced_by == {TEAM: 1} == out.executed_by
        assert low in out.pool and nxt in out.pool and back in out.active(TEAM)
        assert found(setup, placed, out, status) == []


@pytest.mark.parametrize("tier", SEARCH)
def test_in_the_last_week_the_plan_charges_nobody_for_an_o_and_the_rule_before_applies(tier):
    """A limit the README names ("Whose date"), pinned. The engine reads an ``O`` as out for the
    rest of this week, and the season's last week has no later one: its plan brings ``back``
    back inside no horizon and charges nobody, so the seat names none and the morning the world
    brings him back is the rule before, ``low`` leaving though the seat's keep rule keeps him.
    A held player the engine does read as back inside the week is named there, by the week's
    pass of ``sends_of``: a ``GTD`` in an ``IL+`` slot (a day-one status; a replay hears every
    absence as ``O``). In any earlier week the three weeks' pass names both."""
    day = return_day(1, week=5)
    setup, state, _, _, back, low, nxt = day
    assert setup.week_of(state.day).number == max(w.number for w in setup.calendar.weeks)
    built, decision = named_on(day, tier, None)
    assert built.problem.horizons[policy.QUEUE_SET] == () and low in built.problem.kept
    assert decision.moves == () == decision.sends
    placed, out, status = next_morning(day, decision)
    assert low in out.pool and nxt in out.active(TEAM) and back in out.active(TEAM)
    assert out.forced_by == {TEAM: 1} and found(setup, placed, out, status) == []
    day = return_day(1, week=5, slot="IL+", heard="GTD")
    setup = day[0]
    built, decision = named_on(day, tier, None)
    assert mv.comebacks(built.problem, policy.QUEUE_SET, ()) == []
    assert [(c.player, c.drop) for c in mv.comebacks(built.problem, "week", ())] == [(back, nxt)]
    assert decision.sends == ((back, nxt),)
    placed, out, status = next_morning(day, decision)
    assert nxt in out.pool and low in out.active(TEAM) and back in out.active(TEAM)
    assert out.forced_by == {TEAM: 1} and found(setup, placed, out, status) == []
    # The week before, the three weeks' pass names an ``O`` and the week's adds nothing to it.
    earlier, named = named_on(return_day(1, week=4), tier, None)
    assert mv.comebacks(earlier.problem, "week", ()) == [] and named.sends == ((back, nxt),)


def test_a_name_made_on_the_set_alone_can_take_the_drop_of_a_plan_step_queued_beside_it():
    """A limit the README names (limits, 7), pinned. The names are made with the decided set
    made, not with the week plan's steps an arm that executes its plan queues beside the set.
    On the Tuesday the seat's plan charges ``nxt`` for ``back``'s return, and a plan step due
    tomorrow drops ``nxt`` for a free agent. The morning brings ``back`` first: ``nxt`` leaves
    as the forced drop and the step finds its drop gone (counted in ``gone``), where the rule
    before PR G sent ``low``, whom the seat's keep rule keeps, and landed the step. With the
    step made the engine's plan charges the step's own add, who would come and go: the roster
    the morning leaves is the one that plan charges, by a move that is not made."""
    day = return_day(1)
    setup, state, _, _, back, low, nxt = day
    built, decision = named_on(day, "exact", None)
    assert decision.moves == () and decision.sends == ((back, nxt),)
    free = max(state.pool)
    step = mv.Move(free, nxt, state.day + DAY)
    assert mv.feasible(built.problem, (step,))
    assert policy.sends_of(built.problem, (step,)) == ((back, free),)
    planned = replace(decision, plan=(step,))
    placed, out, status = next_morning(day, planned, execute_plan=True)
    assert placed.pending[TEAM] == (mv.Move(free, nxt),) and placed.sends == {TEAM: decision.sends}
    assert nxt in out.pool and free in out.pool and out.gone_by == {TEAM: 1}
    assert set(out.active(TEAM)) == set(placed.active(TEAM)) - {nxt} | {back}
    assert out.forced_by == {TEAM: 1} and not out.executed_by
    assert found(setup, placed, out, status) == []
    _, before, _ = next_morning(day, planned, names=False, execute_plan=True)
    assert low in before.pool and nxt in before.pool and free in before.active(TEAM)
    assert before.forced_by == {TEAM: 1} == before.executed_by and not before.gone_by


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


# --------------------------------------------------------------------------- the count
def test_the_count_is_a_named_run_s_only():
    """Fa's lesson: a run that names no threshold counts as before, key for key; one that names
    one carries the returning players each seat dropped, last, and None for a seat whose
    players nothing read."""
    setup = make_setup()
    s = initial(setup)
    (out, _), (stays, _), (other, _) = s.rosters[1][:3]
    plain = ct.Tally(setup).rows(s)
    assert set(plain[1]) == set(ct.METRICS) and ct.metrics_in([plain[1]]) == ct.METRICS
    tally = ct.Tally(setup, stash=True)
    tally.reading(1, frozenset({out, stays}), s)
    tally.reading(2, frozenset(), s)
    after = replace(s, rosters={**s.rosters, 1: s.rosters[1][1:2] + s.rosters[1][3:]})
    assert {k for k, _ in s.rosters[1]} - {k for k, _ in after.rosters[1]} == {out, other}
    tally.left(s, after)
    tally.left(after, after)
    rows = tally.rows(after)
    assert [rows[t]["returning_dropped"] for t in setup.teams] == [1.0, 0.0, None, None]
    assert (
        ct.metrics_in([rows[1]]) == (*ct.METRICS, *ct.STASH) == (*ct.METRICS, "returning_dropped")
    )
    assert ct.pooled([rows[3], rows[4]])["returning_dropped"] is None
    assert ss.counts_note() is ss.COUNTS_NOTE and "returning_dropped" not in ss.counts_note("faab")
    assert set(ss.counts_note("faab", True)) - set(ss.counts_note("faab")) == set(ct.STASH)
    none, share = arm("A", "surrogate"), arm("B", "surrogate", stash_threshold=0.0)
    assert not rn.stash_named((none, none)) and rn.stash_named((none, share))
    # A claim in flight is folded into the seat's problem, its drop off it: he stays in the
    # reading as he was read the day the claim was placed, while the claim is open and no longer.
    claim = Claim(mv.Move(min(s.pool), stays), s.day, s.day + 2 * DAY, 1)
    waiting = replace(s, claims={1: (claim,)})
    won = replace(waiting, rosters={**s.rosters, 1: s.rosters[1][:1] + s.rosters[1][2:]}, claims={})
    for decided, counted in ((False, 1.0), (True, 0.0)):
        tally = ct.Tally(setup, stash=True)
        tally.reading(1, frozenset({stays}), s)
        tally.reading(1, frozenset(), waiting)
        if decided:  # lost or failed: the next day's reading is that day's alone
            tally.reading(1, frozenset(), s)
        tally.left(waiting, won)
        assert tally.rows(won)[1]["returning_dropped"] == counted


@pytest.mark.parametrize("rule", (DROPPED, CONTINUOUS))
@pytest.mark.parametrize("waivers", KINDS)
def test_a_returning_player_a_claim_drops_is_counted_however_long_the_claim_waits(waivers, rule):
    """The review's finding. The star is on waivers, so the seat's add of him for ``gone``, a
    returning player, is a claim, by priority and by FAAB under either waiver rule. While the
    claim is open the seat's problem is the roster the claim will leave (``moves.with_pending``):
    ``gone`` is on the team's roster and off the problem, so the next day's reading does not
    hold him. The morning the claim is won he leaves, and he is counted once, whether the claim
    waited one morning or two. The runner's own steps (``run.simulate``): the decision, the
    reading, the queue, the morning, the count. Made on one made-up day: no format is named."""
    for wait in (1, 2):
        setup, state, status, returns, star, gone, _ = a_day(churn=False)
        setup = replace(setup, waivers=waivers, waiver_days=2, waiver_rule=rule)
        s = replace(
            initial(setup),
            rosters=state.rosters,
            pool=state.pool,
            waivers={star: Waiting(state.day + wait * DAY, 2)},
        )
        value = wk.per_game_values(setup.projection, setup.cats, None)
        tally = ct.Tally(setup, stash=True)
        for n in range(wait):
            built = policy.problem_of(
                setup, s, TEAM, knobs_at(None), setup.projection, status, returns
            )
            decision = policy.decide(built, "surrogate", with_plan=False)
            tally.reading(TEAM, decision.returning, s)
            on_problem = gone in dict(built.problem.roster)
            if n == 0:
                assert decision.moves == (mv.Move(star, gone),) and gone in decision.returning
            else:
                assert not on_problem and gone not in decision.returning and not decision.moves
            assert gone in dict(s.rosters[TEAM])
            placed = policy.queue(
                s, TEAM, decision, 1, setup.max_weekly_adds, False, setup.spots(), setup
            )
            assert [c.move for c in placed.claims[TEAM]] == [mv.Move(star, gone)]
            s = replace(morning(setup, placed, s.day + DAY, status, value), day=s.day + DAY)
            tally.left(placed, s)
        row = tally.rows(s)[TEAM]
        assert star in s.active(TEAM) and gone in s.pool and not s.claims.get(TEAM)
        assert row["claims_won"] == 1.0 and row["returning_dropped"] == 1.0, wait


# --------------------------------------------------------------------------- the seasons
POINTS_TABLE = {
    "pts": 1.0,
    "reb": 1.2,
    "ast": 1.5,
    "stl": 3.0,
    "blk": 3.0,
    "tov": -1.0,
    "threes": 1.0,
}
#: The seed and the path of the made-up seasons below (``~/sim-notes/vm/scratch/g/probe_season.py``).
SEASON = (1, 1)
#: The threshold the seasons name.
SHARE = 0.25


def held_league(scoring: str = "categories", waivers: str = "none", rule: str = DROPPED):
    """Four seats of five drafted players on six active slots and an IL slot, twelve free agents,
    six weeks; in points, with waivers after two days, under the waiver rule, as asked."""
    setup = make_setup(teams=4, pool=12, held_slots=("IL",))
    if scoring == "points":
        spec = replace(setup.spec, scoring="points", points=POINTS_TABLE, cats=())
        setup = replace(setup, scoring="points", points=POINTS_TABLE, cats=("fpts",), spec=spec)
    if waivers != "none":
        setup = replace(setup, waivers=waivers, waiver_days=2, waiver_rule=rule)
    return setup


def season(setup, thresholds, tier: str = "surrogate", lines=None, stash: bool = True):
    """Seat 1 on ``tier`` at each of ``thresholds`` (a variant each, one world) among market
    rivals at 0.3 a day: the results and each variant's day records."""
    w = rn.replay_world(setup, lines or recorded_lines(setup, 11), 1, *SEASON)
    days: dict[int, list] = {i: [] for i in range(len(thresholds))}
    variants = [
        {
            **{t: op.Market(0.3) for t in setup.teams},
            1: arm("U", tier, opponents="market", stash_threshold=t).seat(),
        }
        for t in thresholds
    ]
    results = rn.simulate(
        setup, w, variants, on_day=lambda r: days[r.variant].append(r), stash=stash
    )
    return results, days


#: The ways an add reaches a roster: a free agent; a claim by priority or by FAAB under either
#: waiver rule.
ADDS = (
    ("none", DROPPED),
    ("priority", DROPPED),
    ("priority", CONTINUOUS),
    ("faab", DROPPED),
    ("faab", CONTINUOUS),
)
#: Every league kind (the plan's section 6), each with the IL slot: categories in both
#: head-to-head formats and points, each way an add arrives.
LEAGUE_KINDS = tuple(
    (scoring, waivers, rule, h2h)
    for scoring, formats in (("categories", (ONE_WIN, EACH_CATEGORY)), ("points", (ONE_WIN,)))
    for waivers, rule in ADDS
    for h2h in formats
)
#: The kinds the exact tier plays too (a season of it is some four times the surrogate's).
EXACT_KINDS = (
    ("categories", "none", DROPPED, ONE_WIN),
    ("categories", "faab", CONTINUOUS, EACH_CATEGORY),
    ("points", "priority", DROPPED, ONE_WIN),
)
SEASONS = [("surrogate", k) for k in LEAGUE_KINDS] + [("exact", k) for k in EXACT_KINDS]
#: The seasons of :data:`SEASONS` in which a morning takes a name the rule before PR G would
#: not have sent (:func:`mornings_moved`; seed and path :data:`SEASON`). In the others the one
#: morning that takes a name sends the player who is also the least valuable that day.
NAME_MOVES = (("exact", EXACT_KINDS[1]), ("exact", EXACT_KINDS[2]))


def mornings_named(days, team: int = TEAM) -> list[tuple[int, int, int]]:
    """The mornings that took ``team``'s name: (the day's index, the held player, the drop) it
    named on a day whose next morning has the held player off his slot and the named player off
    the roster."""
    out = []
    for i, (before, after) in enumerate(pairwise(days)):
        was = {k for k, _ in before.state.held(team)}
        now = {k for k, _ in after.state.held(team)}
        roster = {k for k, _ in after.state.rosters[team]}
        out += [
            (i, back, drop)
            for back, drop in before.state.sends.get(team, ())
            if back in was and back not in now and drop not in roster
        ]
    return out


def mornings_moved(setup, days) -> list[tuple[int, int, int]]:
    """Of the mornings that took seat 1's name, those the name moved: the named player is not
    the one the rule before PR G sends, the least valuable of the active players and the one
    coming back by that morning's values (the run's, which the seat holds here), a tie by the
    id as text. A morning that ignored the names could not show one: no move of the seat's own
    drops a player it named (the names are made with the set made)."""
    points = dict(setup.points) if setup.scoring == "points" and setup.points else None
    out = []
    for i, back, drop in mornings_named(days):
        value = wk.per_game_values(days[i + 1].beliefs, setup.cats, points)
        active = (*days[i].state.active(TEAM), back)
        if drop != min(active, key=lambda k: (value.get(k, 0.0), str(k))):
            out.append((i, back, drop))
    return out


@pytest.mark.parametrize(
    ("tier", "kind"), SEASONS, ids=lambda x: x if isinstance(x, str) else "-".join(x)
)
def test_a_season_with_a_threshold_named_plays_clean_in_every_league_kind(tier, kind):
    """Fc's lesson: the new morning is played once in every league kind with the IL slot, the
    audit clean. In each the seat holds a player, names a drop for him, and the morning that
    brings him back sends the named player; only the seat that builds a problem has the count.
    A named player is often also the one the rule before would send, so that alone would pass
    with the names ignored: in the kinds of :data:`NAME_MOVES` a morning sends a named player
    who is not the least valuable that day (the mornings on made-up days above hold the rule
    itself, under every way an add arrives)."""
    scoring, waivers, rule, h2h = kind
    setup = of_format(held_league(scoring, waivers, rule), h2h)
    (result,), days = season(setup, (SHARE,), tier)
    assert result.breaches == ()
    row = result.counts[TEAM]
    assert row["held_stints"] >= 1 and row["forced_drops"] >= 1
    assert row["returning_dropped"] is not None
    assert all(result.counts[t]["returning_dropped"] is None for t in setup.teams if t != TEAM)
    assert mornings_named(days[0])
    if (tier, kind) in NAME_MOVES:
        assert mornings_moved(setup, days[0])
    if rule == CONTINUOUS:
        assert row["landed"] == row["claims_won"] >= 1


@pytest.mark.parametrize("h2h", (ONE_WIN, EACH_CATEGORY))
def test_the_lever_does_something_the_threshold_changes_the_roster_at_the_end(h2h):
    """D4c's lesson, in both formats. One made-up season with the IL slot, the surrogate at None
    and at a threshold through one world: the audit is clean in both, both count the returning
    players dropped, and the seat ends the season on another roster."""
    setup = of_format(held_league(), h2h)
    (none, share), days = season(setup, (None, SHARE))
    assert none.breaches == share.breaches == ()
    last = [{k for k, _ in days[i][-1].state.rosters[1]} for i in (0, 1)]
    assert last[0] != last[1]
    assert none.counts[1]["returning_dropped"] >= 1
    assert none.counts[1]["returning_dropped"] != share.counts[1]["returning_dropped"]
    # A run that names none carries no such key (Fa's lesson), and is the same season.
    (plain,), _ = season(setup, (None,), stash=False)
    assert set(plain.counts[1]) == set(ct.METRICS)
    assert plain.counts[1] == {m: none.counts[1][m] for m in ct.METRICS}


def test_a_pair_and_a_room_carry_the_count_when_an_arm_names_a_threshold_and_only_then():
    """The count through the runner's pair and room (``run.paired``, ``run.room``): a row of
    every arm, and the rivals' (market rivals build no problem, so theirs is None), when one arm
    names a threshold; no such key when none does. The command's blocks pool it and say what it
    is in their note (``cli.paired_blocks``, ``cli.room_blocks``), in such a run only. One
    format (the league's own, one win): what is held is where the key goes, which reads no
    format; what the seat does with a threshold is the lever test's, in both."""
    setup = held_league()

    def world():
        return rn.replay_world(setup, recorded_lines(setup, 11), 1, *SEASON)

    none, share = arm("A", "surrogate"), arm("B", "surrogate", stash_threshold=SHARE)
    pair = rn.paired(setup, world(), none, share, me=1)
    assert pair["breaches"] == [] and set(pair["counts"]) == {"a", "b", "rivals"}
    assert all("returning_dropped" in row for row in pair["counts"].values())
    assert pair["counts"]["a"]["returning_dropped"] is not None
    assert pair["counts"]["rivals"]["returning_dropped"] is None
    plain = rn.paired(setup, world(), none, replace(none, name="B"), me=1)
    assert all(set(row) == set(ct.METRICS) for row in plain["counts"].values())
    assert plain["counts"]["a"] == {m: pair["counts"]["a"][m] for m in ct.METRICS}
    seats = ["A", "B", "A", "B"]
    room = rn.room(setup, world(), {"A": none, "B": share}, seats, 0)
    assert room["breaches"] == []
    assert all(room["counts"][n]["returning_dropped"] is not None for n in "AB")
    # The command's blocks, on the runner's results with what a task adds to one.
    key = {"season": 2024, "forecaster": "prior"}
    task = {"seat": 1, "unprojected": {"a": {}, "b": {}}}
    named = ss.paired_blocks([key], [{**pair, **task}], {"a": none, "b": share}, 1)["counts"]
    assert set(named["note"]) - set(ss.COUNTS_NOTE) == set(ct.STASH)
    cell = named["by_season"]["2024"]["prior"]
    assert (
        cell["a"]["returning_dropped"]["n"] == 1 and cell["rivals"]["returning_dropped"]["n"] == 0
    )
    unnamed = ss.paired_blocks([key], [{**plain, **task}], {"a": none, "b": none}, 1)["counts"]
    assert unnamed["note"] == ss.COUNTS_NOTE
    assert set(unnamed["by_season"]["2024"]["prior"]["a"]) == set(ct.METRICS)
    in_room = ss.room_blocks([key], [{**room, "unprojected": {}}], seats)["counts"]
    assert set(in_room["note"]) - set(ss.COUNTS_NOTE) == set(ct.STASH)
    assert "returning_dropped" in in_room["by_season"]["2024"]["prior"]["A"]


def test_no_peek_with_a_threshold_named():
    """The seat's names and its count read nothing ahead: a second season that agrees with the
    first through a Thursday and differs after gives the same day records through that day, the
    state's names and the decisions' among them. One format (one win): the names and the
    reading are made from the seat's problem by the same calls in both (``moves.comebacks``,
    ``moves.returning_net``, neither of which reads the week's measure), and the no-peek check
    of every other field in both formats is ``test_no_peek``'s."""
    setup = held_league()
    lines = recorded_lines(setup, 11)
    day = setup.start + timedelta(17)
    assert day.weekday() == 3

    def records(lines):
        _, days = season(setup, (SHARE,), lines=lines)
        return {(r.day, r.variant): nopeek.digest(r) for r in days[0]}, days[0]

    base, seen = records(lines)
    assert any(r.state.sends for r in seen if r.day <= day)
    got, _ = records(nopeek.perturb(lines, rn.game_days_of(setup), day, 5))
    first = nopeek.first_difference(base, got)
    assert first is not None and first[0] > day
    assert all(base[key] == got[key] for key in base if key[0] <= day)


SOURCES = (fc.Forecaster("espn"), fc.Forecaster("marcel"))


@pytest.mark.parametrize(
    ("system", "blend", "h2h"), [("yahoo", None, ONE_WIN), ("blend", 0.25, EACH_CATEGORY)]
)
def test_a_split_seat_names_on_its_own_table_and_plays_clean(system, blend, h2h):
    """#432's lesson: a rule that reads the seat's own forecaster is played with a split seat,
    which reads a free agent on one table and its roster on another. A ``yahoo`` and a
    ``blend`` seat with the IL slot and a threshold: the audit is clean, each name is the one
    ``sends_of`` gives on the seat's own table of that day (the table its record holds), a
    morning takes one and the seat has the count. For the ``yahoo`` seat the run's table names
    another player on at least one of those days, so the names are read off the seat's own.
    Each system once and each format once: the name is made the same way in both formats."""
    setup = of_format(held_league(), h2h)
    lines = recorded_lines(setup, 11)
    first = {k: {st: v * 1.1 for st, v in r.items()} for k, r in setup.projection.items()}
    a = arm("Y", "surrogate", "market", system=system, blend=blend, stash_threshold=SHARE)
    arms = ss.believing({"Y": a}, SOURCES)
    seat = arms["Y"].seat()
    fixed = ss.Fixed({"espn": first, "marcel": second_of(first)}, {})
    w = rn.replay_world(
        setup,
        lines,
        1,
        *SEASON,
        WEIGHTS,
        label="run",
        forecasts=ss.forecasts_of(SOURCES, fixed, lines, 1, SEASON[1], "stat", arms),
        split=ss.splits_of(SOURCES, arms),
    )
    assert seat.forecaster in w.split
    days: list = []
    variant = {**{t: op.Market(0.3) for t in setup.teams}, TEAM: seat}
    (result,) = rn.simulate(setup, w, [variant], on_day=days.append, stash=True)
    assert result.breaches == ()
    named = [r for r in days if r.state.sends.get(TEAM)]
    assert named and mornings_named(days)
    apart = 0
    for r in named:
        moves = r.decisions[TEAM].moves

        def names(table, r=r, moves=moves):
            built = policy.problem_of(setup, r.state, TEAM, a.knobs, table, r.status, r.returns)
            return policy.sends_of(built.problem, moves)

        assert names(r.held[seat.forecaster]) == r.state.sends[TEAM]
        apart += names(r.beliefs) != r.state.sends[TEAM]
    assert apart or system != "yahoo"
    assert result.counts[TEAM]["held_stints"] >= 1
    assert result.counts[TEAM]["returning_dropped"] is not None


@pytest.mark.parametrize("h2h", (ONE_WIN, EACH_CATEGORY))
def test_a_mirror_rival_names_too_keeps_none_and_has_the_count(h2h):
    """A mirror rival plans with the engine: it is made without the arm's threshold, names whom
    its own held players send, a morning takes a rival's name, and, building a problem, it has
    the count the market rivals of the other seasons do not. The audit is clean."""
    setup = of_format(held_league(), h2h)
    a = arm("U", "surrogate", "mirror", stash_threshold=SHARE)
    variant = {**rn.opponents_of(setup, a, TEAM), TEAM: a.seat()}
    rivals = [t for t in setup.teams if t != TEAM]
    assert all(variant[t].knobs["stash_threshold"] is None for t in rivals)
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, *SEASON)
    days: list = []
    (result,) = rn.simulate(setup, w, [variant], on_day=days.append, stash=True)
    assert result.breaches == ()
    assert all(result.counts[t]["returning_dropped"] is not None for t in setup.teams)
    assert any(mornings_named(days, t) for t in rivals)


# --------------------------------------------------------------------------- the command
BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))


@pytest.fixture(scope="module")
def pinned_clock():
    """The guard's clock, for the one test here that runs the command."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def test_the_command_takes_a_threshold_from_a_seat_s_file_and_counts_it(tmp_path, pinned_clock):
    """End to end, once: a seat's file names the threshold, the arm parser takes it, the room
    plays with an IL slot and the dry run prints the count for the seat that builds a problem
    and not for the static seat beside it. One format (the command's own, no ``--h2h`` named):
    what is held is the knob's way from the file to the arm and the count's way to the print,
    neither of which reads a format."""
    folder = make_data_dir(tmp_path)
    assert ss.main(["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    specs = {
        "T": {"tier": "surrogate", "knobs": {**KNOBS, "stash_threshold": SHARE}},
        "S": {"tier": "static", "knobs": KNOBS},
    }
    for name, spec in specs.items():
        seat = {"name": name, "opponents": {"kind": "static"}, **spec}
        (folder / f"{name}.json").write_text(json.dumps(seat))
    seats = [str(folder / f"{n}.json") for n in specs]
    argv = ["--data", str(folder), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        room = ("--seats", *seats, "--paths", "1", "--held", "IL=1")
        code = ss.main([*argv, "--seed", "5", *room, "--dry-run"])
    out = buf.getvalue()
    assert code == 0, out
    counts = {x.split(",")[1].strip(): x for x in out.splitlines() if x.startswith("counts, ")}
    assert set(counts) == {"T", "S"}
    assert "returning_dropped" in counts["T"] and "returning_dropped" not in counts["S"]


def test_the_replay_s_version_is_the_stash_threshold_s():
    """The record's version and the first words of its reason (PR G): a payload read later says
    which rule the morning of a comeback was played by."""
    assert ss.REPLAY_VERSION == 15
    assert ss.REPLAY_VERSION_WHY.startswith("15: the stash threshold: ")
    assert "14: the arm's seat's draft under a table" in ss.REPLAY_VERSION_WHY


# --------------------------------------------------------------------------- Rule 1
def outcome_digest(setup, tier: str, opponents: str) -> str:
    """SHA-256 of a made-up season's outcome (seed 1, path 0): seat 1 on ``tier`` at the tests'
    knobs, the threshold None, among ``opponents``; every seat's counts and summary, the last
    day's rosters, and the solves, moves and breaches, each figure rounded to nine places."""
    a = arm("U", tier, opponents=opponents)
    assert a.knobs["stash_threshold"] is None
    w = rn.replay_world(setup, recorded_lines(setup, 11), 1, 1, 0)
    last: list = []
    variant = {**rn.opponents_of(setup, a, 1), 1: a.seat()}
    (res,) = rn.simulate(setup, w, [variant], on_day=lambda d: last.append(d.state))
    figures = rounded(
        {
            "counts": {str(t): row for t, row in res.counts.items()},
            "summaries": {str(t): x for t, x in res.summaries.items()},
            "rosters": {str(t): sorted(k for k, _ in ro) for t, ro in last[-1].rosters.items()},
            "moves": [res.solves, res.executed, res.gone, len(res.breaches)],
        }
    )
    return hashlib.sha256(json.dumps(figures, sort_keys=True, default=str).encode()).hexdigest()


#: Rule 1's pins: a made-up season without held slots (:func:`outcome_digest`) at None on each
#: tier, in each head-to-head format and against each kind of rival that decides, as main
#: ``88af1de`` gives them (``~/sim-notes/vm/scratch/g/rule1_pins.py``: the same function on
#: main's code and on this PR, whose tree is cut from ``4b26577``). A mirror rival is a
#: surrogate, so the two mirror rows hold the rival's side of the rule too.
RULE_1 = {
    ("exact", "mirror", ONE_WIN): (
        "0e1824ee73f1ed0eb18c3236e4439066041fa4d57b97ee03f0d4deeb3dfd94d6"
    ),
    ("exact", "market", EACH_CATEGORY): (
        "8b6fda8857f18f72b6551e732a8d3fa2aa11d52bcf5ccf296f72f7df674693e8"
    ),
    ("surrogate", "mirror", EACH_CATEGORY): (
        "1b1d3bea0dd9f0ef67435da4651fb20cece0095a98bf894774d0d7f4efe3be16"
    ),
    ("surrogate", "market", ONE_WIN): (
        "3f27822b7bc39bb9073e3ae1b7dec2da0f5710b30fed236f3ec2992bbffad53f"
    ),
    ("ranking", "market", ONE_WIN): (
        "9c72dbf300e4808419f6d61538c3294556edeb697355dafbcd6e4af36d106c35"
    ),
}


@pytest.mark.parametrize("case", RULE_1, ids="-".join)
def test_rule_1_a_league_without_held_slots_is_main_s_at_none_on_each_tier(case):
    tier, opponents, h2h = case
    setup = of_format(make_setup(teams=4, pool=12), h2h)
    assert not set(setup.roster_slots) & set(mv.HELD)
    assert outcome_digest(setup, tier, opponents) == RULE_1[case]
