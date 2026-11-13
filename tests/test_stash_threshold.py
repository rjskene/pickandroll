"""The stash threshold's reader (#373): with no value the engine is main's exactly; with one, a
returning player leaves the roster only when the player who keeps his spot beats his value net
of return by the threshold's share, on each of the three ways he can leave (the plain drop, a
churn's held drop, the drop a comeback forces); the protection only grows with the threshold;
the Monday step never steps it (``test_hillclimb``, ``test_knobs``). Every league here is made up
(``test_moves``'s fixtures, ``stash_snapshot``'s cases); the outcomes are set by construction."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace

import pytest

from pickandroll.api import season_moves as sm
from pickandroll.season import Player
from pickandroll.season import moves as mv

from .stash_snapshot import SNAPSHOT, cases, payload
from .test_moves import WEEKS, il_full_league, keep_league, rates
from .test_season_guard import built_of

MONDAY = WEEKS[1][0]
GRID = (0.0, 0.1, 0.5, 1.0, 2.0, 5.0)


def at(problem: mv.MoveProblem, t: float | None) -> mv.MoveProblem:
    return replace(problem, stash_threshold=t)


# --------------------------------------------------------------------------- none is main
@pytest.mark.parametrize("name", sorted(cases()))
def test_with_no_threshold_every_payload_is_mains_snapshot(name):
    """Main's moves payloads (a908044, before the reader) for leagues with a returning player:
    the same sets in the same order, the same plans, comebacks, keep rule and activation."""
    snap = json.loads(SNAPSHOT.read_text())
    p = cases()[name]
    assert p.stash_threshold is None
    assert payload(p) == snap[name]
    assert payload(at(p, None)) == snap[name]


def test_the_knob_reaches_the_problem_as_a_number_or_none():
    assert sm.stash_threshold({"stash_threshold": None}) is None
    assert sm.stash_threshold({}) is None
    assert sm.stash_threshold({"stash_threshold": 0}) == 0.0
    assert sm.stash_threshold({"stash_threshold": 0.25}) == 0.25


# --------------------------------------------------------------------------- who is returning
def test_a_returning_player_is_one_of_mine_out_now_back_this_season_and_worth_something():
    p = keep_league()
    hurt = dict(p.roster)[5]
    assert mv.returning_net(p, 5) == pytest.approx(mv.net_of_return(p, 5, hurt))
    # Healthy, a candidate, out for the season, worth nothing back, or without a line: not.
    assert mv.returning_net(p, 1) is None and mv.returning_net(p, 10) is None
    ofs = replace(p, roster=(*p.roster[:3], (5, replace(hurt, status="OFS"))))
    assert mv.returning_net(ofs, 5) is None
    assert mv.returning_net(replace(p, season_value={**p.season_value, 5: 0.0}), 5) is None
    assert mv.returning_net(replace(p, season_value={1: 2.0}), 5) is None
    # A held player out (O) is; one whose status cleared is back, not returning.
    held = il_full_league([(7, "O")], {7: 0.5})
    assert mv.returning_net(held, 7) == pytest.approx(mv.net_of_return(held, 7, dict(held.held)[7]))
    assert mv.returning_net(il_full_league([(7, None)], {7: 0.5}), 7) is None


def test_the_alternatives_worth_is_the_returns_figure_from_its_day():
    p = keep_league(dead=0.1)
    assert mv.worth_from(p, 10, MONDAY) == pytest.approx(
        (0.8 - 0.1) * mv.games_left(p, "STR", MONDAY)
    )
    assert mv.worth_from(replace(p, season_value={}), 10, MONDAY) is None


# --------------------------------------------------------------------------- the bar at zero
def test_at_zero_the_alternative_must_beat_his_return_at_all():
    """t = 0: a returning player leaves only for an alternative worth more than his value net of
    return; level is not enough, and no line is never enough."""
    p = at(keep_league(), 0.0)
    net = mv.returning_net(p, 5)
    assert net is not None and net > 0
    assert mv.stash_clears(p, net * 1.01, net)
    assert not mv.stash_clears(p, net, net) and not mv.stash_clears(p, net * 0.99, net)
    assert not mv.stash_clears(p, None, net)
    # With no threshold there is no bar.
    assert mv.stash_clears(at(p, None), None, net)


# --------------------------------------------------------------------------- exit 1: the plain drop
def test_the_plain_drop_of_a_returning_player_needs_the_add_to_beat_his_return():
    # Player 5 out (O, back next Monday), no IL slot open: an add must drop someone.
    base = replace(keep_league(), held_open={})
    low = replace(base, season_value={**base.season_value, 5: 0.3})
    net = mv.returning_net(low, 5)
    worth = mv.worth_from(low, 10, WEEKS[0][0])
    assert net is not None and worth is not None and net < worth < 1.5 * net
    drop = mv.Move(10, 5)
    assert mv.feasible(at(low, None), [drop])
    # The add beats his return by under 50%: allowed at 0 and 0.4, refused at 0.5 and above.
    for t, ok in ((0.0, True), (0.4, True), (0.5, False), (2.0, False)):
        assert mv.stash_ok(at(low, t), drop) is ok
        assert mv.feasible(at(low, t), [drop]) is ok
        # Every gate the search passes through holds it: the single swaps never offer it.
        swaps = mv.single_swaps(mv.Evaluator(at(low, t)), "three", [10])
        assert (5 in [g.drop for g in swaps[10]]) is ok
    # Worth more back than any add: refused at 0, while a healthy drop still fits.
    assert not mv.feasible(at(base, 0.0), [drop])
    assert mv.feasible(at(base, 0.0), [mv.Move(10, 3)])


def test_the_search_never_recommends_a_drop_the_threshold_refuses():
    p = at(replace(keep_league(), held_open={}), 0.0)
    ev = mv.Evaluator(p)
    for key in ("week", "three"):
        rec = mv.recommend(ev, key, [10, 11], min_gain=0.0)
        assert all(pm.move.drop != 5 for pm in rec.moves)
    # And the route's payload with the threshold set holds to it on every horizon.
    _, out = sm.solve(built_of(p))
    for r in out["recommended"].values():
        assert all(m["drop"] != 5 for m in r["moves"])


# --------------------------------------------------------------------------- exit 2: the churn
def test_a_churns_held_drop_needs_the_add_to_beat_his_return():
    # Player 7 in the IL, out (O, back next Monday); 5 of mine out moves into the slot he frees.
    p = il_full_league([(7, "O")], {7: 0.5})
    net = mv.returning_net(p, 7)
    weak, strong = mv.worth_from(p, 10, WEEKS[0][0]), mv.worth_from(p, 11, WEEKS[0][0])
    assert net is not None and weak < net < strong
    for move, t, ok in (
        (mv.Move(10, 7), None, True),
        (mv.Move(10, 7), 0.0, False),
        (mv.Move(11, 7), 0.0, True),
        (mv.Move(11, 7), strong / net, False),
    ):
        assert mv.is_churn(p, move)
        assert mv.feasible(at(p, t), [move]) is ok
    # A claim's churn still needs him worth nothing net of return (#221), whatever the threshold.
    claim = replace(p, claims=frozenset({11}))
    assert not mv.churn_ok(claim, mv.Move(11, 7))
    assert not mv.feasible(at(claim, 0.0), [mv.Move(11, 7)])


# --------------------------------------------------------------------------- exit 3: the comeback
def comeback_league() -> mv.MoveProblem:
    """The keep league (5 out, an open IL slot) with 5 the least valuable per game: the IL move
    brings him back next Monday and, today, sends him himself."""
    p = keep_league()
    return replace(p, value={**p.value, 5: 0.05})


def test_a_comeback_keeps_a_returning_player_the_threshold_keeps_and_still_drops_someone():
    p = comeback_league()
    move = [mv.Move(11)]
    assert mv.comebacks(at(p, None), "three", move) == [mv.Comeback(5, "IL", MONDAY, 5)]
    # Player 3, the weakest of the others, is worth less than nothing over the season: 5 stays
    # and 3 goes, on every threshold.
    assert mv.worth_from(p, 3, MONDAY) < 0
    for t in GRID:
        assert mv.comebacks(at(p, t), "three", move) == [mv.Comeback(5, "IL", MONDAY, 3)]
    # With everyone else kept the drop is still made: 5 goes.
    kept = replace(p, kept=frozenset({1, 2, 3, 11}))
    assert mv.comebacks(at(kept, 5.0), "three", move) == [mv.Comeback(5, "IL", MONDAY, 5)]


def test_a_comeback_lets_a_returning_player_go_when_the_one_kept_instead_beats_his_return():
    p = comeback_league()
    # 5 worth little back, 3 worth something: 3's worth from Monday beats 5's return under 50%.
    q = replace(p, season_value={**p.season_value, 5: 0.15, 3: 0.2})
    net, worth = mv.returning_net(q, 5), mv.worth_from(q, 3, MONDAY)
    assert net is not None and worth is not None and net < worth < 1.5 * net
    move = [mv.Move(11)]
    assert mv.comebacks(at(q, 0.0), "three", move) == [mv.Comeback(5, "IL", MONDAY, 5)]
    assert mv.comebacks(at(q, 1.0), "three", move) == [mv.Comeback(5, "IL", MONDAY, 3)]


def test_a_held_players_return_and_a_cleared_activation_keep_to_it_too():
    # A held player back Monday with the roster full sends the weakest; an active player out
    # (5, back Monday too) is guarded among the others as he is.
    held = il_full_league([(7, "O")], {7: 0.5})
    held = replace(held, value={**held.value, 5: 0.01, 7: 0.02})
    base = mv.comebacks(at(held, None), "three", [])
    assert [(c.player, c.drop, c.returning) for c in base] == [(7, 5, True)]
    guarded = mv.comebacks(at(held, 0.0), "three", [])
    assert [(c.player, c.drop, c.returning) for c in guarded] == [(7, 3, True)]
    # A cleared player's activation: an active player out is left out of the choice.
    p = keep_league()
    back = (7, Player(7, "Back", "MIN", ("C",), status="Q"))
    p = replace(
        p,
        held=(back,),
        held_slots={7: "IL"},
        held_open={},
        rates={**p.rates, 7: rates(1.0)},
        value={**p.value, 7: 1.0},
        season_value={**p.season_value, 7: 1.0},
    )
    assert mv.cleared(p) == [(7, "IL")]

    def favours_five(ev: mv.Evaluator, steps) -> float:
        return 1.0 if ev.problem.activation.get(7) == 5 else 0.0

    assert mv.choose_activation(at(p, None), favours_five) == {7: 5}
    assert mv.choose_activation(at(p, 0.0), favours_five) != {7: 5}


# --------------------------------------------------------------------------- monotone
@pytest.mark.parametrize("name", sorted(cases()))
def test_the_protection_only_grows_with_the_threshold(name):
    """Per player (the guarantee the docs state): every move admitted at a higher threshold is
    admitted at a lower one, and every returning player left in a forced drop's pool at a higher
    threshold is left there at a lower one."""
    p = cases()[name]
    singles = [mv.Move(c, d) for c, _ in p.candidates for d in mv.drop_options(p) if d is not None]
    pool = [k for k, _ in p.roster] + [k for k, _ in p.held]
    admitted = {}
    left = {}
    for t in (None, *GRID):
        q = at(p, t)
        admitted[t] = {m for m in singles if mv.feasible(q, [m])}
        left[t] = {x for x in mv.guarded_pool(q, pool, MONDAY) if mv.returning_net(q, x)}
    order = [None, *GRID]
    for lo, hi in itertools.pairwise(order):
        assert admitted[hi] <= admitted[lo]
        assert left[hi] <= left[lo]
