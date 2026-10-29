"""The move model (#94): single moves and their prices, the recommended set under the weekly
add limit, waiver claims from their clear date, held-slot moves and the field. Every league here
is made up; the outcomes are set by construction (games, rates) rather than read off a solver."""

from __future__ import annotations

import itertools
from dataclasses import replace
from datetime import date, timedelta

import pytest

from pickandroll.season import Player, Transaction
from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk

MON = date(2026, 10, 26)
WEEKS = [tuple(MON + timedelta(7 * w + n) for n in range(7)) for w in range(4)]
NINE = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")
COUNTING = ("pts", "reb", "ast")


def rates(level: float = 1.0, tov: float = 2.0) -> dict[str, float]:
    """A line scaled by ``level``; shooting and turnovers fixed so the counting stats decide."""
    return {
        "pts": 10 * level,
        "threes": 1 * level,
        "reb": 5 * level,
        "ast": 3 * level,
        "stl": 1 * level,
        "blk": 1 * level,
        "tov": tov,
        "fgm": 4.0,
        "fga": 8.0,
        "ftm": 2.0,
        "fta": 2.5,
    }


def schedule(games: dict[str, list[int]]) -> dict[date, frozenset[str]]:
    """``{team: [day index over the four weeks, ...]}``, every day present."""
    days = [d for w in WEEKS for d in w]
    return {d: frozenset(t for t, idx in games.items() if i in idx) for i, d in enumerate(days)}


def player(key: int, team: str, status: str | None = None, pos: tuple[str, ...] = ("C",)):
    return (key, Player(key, f"P{key}", team, pos, status=status))


def team_week(members, rate, sched, days, this_week=False, slots=("C", "C", "Util")):
    value = {k: 1.0 for k, _ in members}
    return wk.project_week(members, rate, days, sched, slots, value, this_week)


def build(
    roster,
    candidates,
    rate,
    sched,
    opponent,
    field=(),
    *,
    cats=COUNTING,
    spots=None,
    held=(),
    held_open=None,
    effective=None,
    limits=None,
    first_day=None,
    slots=("C", "C", "Util"),
    so_far=None,
    so_far_theirs=None,
    value=None,
    returns=None,
    held_slots=None,
):
    """A problem with the ``week`` horizon (the first week against ``opponent``) and the
    ``three`` horizon (weeks 2-4 against ``field``, each a list of rosters)."""
    first = first_day or WEEKS[0][0]
    week_days = tuple(d for d in WEEKS[0] if d >= first)
    opp = team_week(opponent, rate, sched, week_days, True, slots)
    spans = {
        "week": (
            mv.WeekSpan(
                week_days,
                True,
                (opp,),
                so_far or {},
                (so_far_theirs,) if so_far_theirs is not None else (),
            ),
        ),
        "three": tuple(
            mv.WeekSpan(w, False, tuple(team_week(t, rate, sched, w, False, slots) for t in field))
            for w in WEEKS[1:]
        ),
    }
    return mv.MoveProblem(
        roster=tuple(roster),
        held=tuple(held),
        spots=len(roster) if spots is None else spots,
        held_open=held_open or {},
        candidates=tuple(candidates),
        effective=effective or {k: first for k, _ in candidates},
        first_day=first,
        rates=rate,
        schedule=sched,
        slots=slots,
        value=value or {k: 1.0 for k in rate},
        cats=cats,
        points=None,
        no_games=frozenset(),
        horizons=spans,
        limits=tuple(limits or ()),
        returns=returns or {},
        held_slots=held_slots or {},
    )


# --------------------------------------------------------------------------- one move
def streaming_league():
    """Three of mine (the third barely plays), a streamer with four games this week and none
    after, and a holder with one game this week and four a week after."""
    sched = schedule(
        {
            "MIN": [0, 2, 4, 6] + [7 + d for w in range(3) for d in (7 * w, 7 * w + 3)],
            "STR": [0, 1, 3, 5],
            "HLD": [6]
            + [7 + d for w in range(3) for d in (7 * w, 7 * w + 2, 7 * w + 4, 7 * w + 6)],
        }
    )
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    cands = [player(10, "STR"), player(11, "HLD")]
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(0.1), 10: rates(1.0), 11: rates(1.0)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.1), 21: rates(1.0), 22: rates(0.9)}
    field = [opponent, [player(30, "MIN"), player(31, "MIN"), player(32, "MIN")]]
    rate |= {30: rates(1.3), 31: rates(1.1), 32: rates(0.9)}
    return roster, cands, rate, sched, opponent, field


def test_the_best_single_move_differs_by_horizon_as_built():
    roster, cands, rate, sched, opponent, field = streaming_league()
    ev = mv.Evaluator(build(roster, cands, rate, sched, opponent, field))
    week = mv.single_swaps(ev, "week")
    three = mv.single_swaps(ev, "three")
    # Both replace the player who barely plays; the streamer wins the week, the holder the three.
    assert week[10][0].drop == 3 and week[11][0].drop == 3
    assert week[10][0].gain > week[11][0].gain > 0
    assert three[11][0].gain > 0 and three[10][0].gain < 0
    # With no open spot, an add without a drop is not a move.
    assert all(g.drop is not None for g in week[10])


def test_a_single_moves_prices_are_direct_re_solves():
    roster, cands, rate, sched, opponent, field = streaming_league()
    ev = mv.Evaluator(build(roster, cands, rate, sched, opponent, field))
    swaps = mv.single_swaps(ev, "week")[10]
    base = ev.value("week", ())
    for g in swaps:
        assert g.gain == pytest.approx(ev.value("week", [mv.Move(10, g.drop)]) - base)
    assert [g.gain for g in swaps] == sorted((g.gain for g in swaps), reverse=True)


def test_a_waiver_claim_counts_from_its_clear_date_and_its_drop_plays_until_then():
    # The claim clears on Thursday: the streamer's Monday and Tuesday games are lost, and the
    # player he replaces keeps his Monday and Wednesday games.
    roster, cands, rate, sched, opponent, field = streaming_league()
    thursday = WEEKS[0][3]
    p = build(
        roster, cands, rate, sched, opponent, field, effective={10: thursday, 11: WEEKS[0][0]}
    )
    ev = mv.Evaluator(p)
    members, _, gone = ev._after("week", frozenset({mv.Move(10, 3)}))
    week = wk.project_week(
        members,
        rate,
        WEEKS[0],
        sched,
        p.slots,
        p.value,
        True,
        available_from=p.effective,
        gone_from=gone,
    )
    assert week.players[10].games == 2  # Thursday and Saturday
    assert week.players[3].games == 2  # Monday and Wednesday, then dropped on Thursday
    # A free agent's drop stops on the first day.
    members, _, gone = ev._after("week", frozenset({mv.Move(11, 3)}))
    week = wk.project_week(
        members,
        rate,
        WEEKS[0],
        sched,
        p.slots,
        p.value,
        True,
        available_from=p.effective,
        gone_from=gone,
    )
    assert week.players[3].games == 0
    # The value is exactly that projection's.
    claimed = ev.gain("week", [mv.Move(10, 3)])
    assert claimed < mv.Evaluator(build(roster, cands, rate, sched, opponent, field)).gain(
        "week", [mv.Move(10, 3)]
    )


# --------------------------------------------------------------------------- the field
def test_the_field_averages_the_odds_against_each_team_not_against_an_average_team():
    roster, cands, rate, sched, opponent, _ = streaming_league()
    strong = [player(40, "MIN"), player(41, "MIN"), player(42, "MIN")]
    weak = [player(50, "MIN"), player(51, "MIN"), player(52, "MIN")]
    rate |= {k: rates(3.0) for k in (40, 41, 42)} | {k: rates(0.2) for k in (50, 51, 52)}
    p = build(roster, cands, rate, sched, opponent, [strong, weak])
    ev = mv.Evaluator(p)
    span = p.horizons["three"][0]
    mine = team_week(roster, rate, sched, span.days)
    each = [wk.expected_won(wk.category_odds(mine, t, COUNTING)) for t in span.opponents]
    assert ev._week(span, list(roster), {}, {}) == pytest.approx(sum(each) / 2)
    # Against a team with the average of the two lines the answer is different (Jensen).
    middle = [player(60 + i, "MIN") for i in range(3)]
    rate |= {k: rates(1.6) for k, _ in middle}
    avg = wk.expected_won(
        wk.category_odds(mine, team_week(middle, rate, sched, span.days), COUNTING)
    )
    assert abs(avg - sum(each) / 2) > 0.1


# --------------------------------------------------------------------------- the set
def deep_league():
    """Four of mine, three of them weak, and five candidates of different strength and games."""
    sched = schedule(
        {t: list(range(0, 28, n)) for t, n in (("A", 2), ("B", 3), ("C", 1), ("D", 4))}
    )
    roster = [player(1, "A"), player(2, "B"), player(3, "D"), player(4, "B")]
    cands = [player(10, "C"), player(11, "A"), player(12, "B"), player(13, "C"), player(14, "D")]
    rate = {1: rates(1.5), 2: rates(0.3), 3: rates(0.2), 4: rates(0.6)}
    rate |= {10: rates(0.9), 11: rates(1.1), 12: rates(0.8), 13: rates(0.5), 14: rates(1.4)}
    opponent = [player(20, "A"), player(21, "B"), player(22, "C"), player(23, "A")]
    rate |= {20: rates(1.2), 21: rates(1.0), 22: rates(0.7), 23: rates(0.9)}
    field = [opponent, [player(30, "C"), player(31, "B"), player(32, "A"), player(33, "D")]]
    rate |= {30: rates(1.0), 31: rates(1.1), 32: rates(0.8), 33: rates(1.2)}
    return roster, cands, rate, sched, opponent, field


@pytest.mark.parametrize("key", ["week", "three"])
def test_the_recommended_pair_matches_brute_force_over_every_pair_of_moves(key):
    roster, cands, rate, sched, opponent, field = deep_league()
    p = build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        field,
        limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][6], 2)],
    )
    ev = mv.Evaluator(p)
    pool = [c for c, _ in cands]
    found = mv.search(ev, key, pool)
    singles = [mv.Move(c, d) for c in pool for d in mv.drop_options(p)]
    sets = [()] + [(m,) for m in singles] + list(itertools.combinations(singles, 2))
    best = max(ev.value(key, s) for s in sets if mv.feasible(p, s))
    assert ev.value(key, found) == pytest.approx(best)


def test_the_weekly_limit_binds_and_a_claim_clearing_next_week_uses_next_weeks():
    roster, cands, rate, sched, opponent, field = deep_league()
    week1, week2 = WEEKS[0], WEEKS[1]
    limits = [mv.AddLimit(week1[0], week1[6], 1), mv.AddLimit(week2[0], week2[6], 4)]
    p = build(roster, cands, rate, sched, opponent, field, limits=limits)
    ev = mv.Evaluator(p)
    pool = [c for c, _ in cands]
    assert len(mv.search(ev, "three", pool)) == 1
    unlimited = mv.Evaluator(build(roster, cands, rate, sched, opponent, field))
    assert len(mv.search(unlimited, "three", pool)) > 1
    # Every claim clears next Monday: none uses this week's single add.
    later = {c: week2[0] for c in pool}
    p = build(roster, cands, rate, sched, opponent, field, limits=limits, effective=later)
    assert mv.feasible(p, [mv.Move(10, 2), mv.Move(14, 3)])
    assert not mv.feasible(
        build(roster, cands, rate, sched, opponent, field, limits=limits),
        [mv.Move(10, 2), mv.Move(14, 3)],
    )
    # No adds left this week: a free agent's move does not fit at all.
    p = build(
        roster, cands, rate, sched, opponent, field, limits=[mv.AddLimit(week1[0], week1[6], 0)]
    )
    assert mv.single_swaps(mv.Evaluator(p), "week")[10] == []


def test_every_recommended_move_is_priced_by_a_re_solve():
    roster, cands, rate, sched, opponent, field = deep_league()
    p = build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        field,
        limits=[mv.AddLimit(WEEKS[0][0], WEEKS[0][6], 2)],
    )
    ev = mv.Evaluator(p)
    pool = [c for c, _ in cands]
    rec = mv.recommend(ev, "three", pool)
    moves = tuple(pm.move for pm in rec.moves)
    assert rec.moves and rec.gain["three"] == pytest.approx(ev.gain("three", moves))
    value = ev.value("three", moves)
    for pm in rec.moves:
        without = mv.search(ev, "three", pool, exclude={pm.move.add})
        assert pm.price_without == pytest.approx(value - ev.value("three", without))
        assert pm.move.add not in {m.add for m in pm.instead_without}
        if pm.move.drop is not None:
            keep = mv.search(ev, "three", pool, keep={pm.move.drop})
            assert pm.price_keep == pytest.approx(value - ev.value("three", keep))
            assert pm.move.drop not in {m.drop for m in pm.instead_keep}
        # Both horizons' share of the set.
        rest = [m for m in moves if m != pm.move]
        assert pm.marginal["week"] == pytest.approx(
            ev.value("week", moves) - ev.value("week", rest)
        )
    assert all(pm.price_without >= -1e-9 for pm in rec.moves)


def test_min_gain_leaves_out_moves_worth_less():
    roster, cands, rate, sched, opponent, field = deep_league()
    ev = mv.Evaluator(build(roster, cands, rate, sched, opponent, field))
    pool = [c for c, _ in cands]
    every = mv.search(ev, "three", pool)
    some = mv.search(ev, "three", pool, min_gain=10.0)
    assert every and some == ()


# --------------------------------------------------------------------------- held slots
@pytest.mark.parametrize(
    ("status", "slots"),
    [
        # Yahoo's help page for basketball: IL takes O and OFS, never P, Q or D.
        ("O", ("IL", "IL+")),
        ("OFS", ("IL", "IL+")),
        ("P", ()),
        ("Q", ()),
        ("D", ()),
        # Unverified: IL+ from the 2021 announcement, NA from baseball and hockey.
        ("INJ", ("IL+",)),
        ("GTD", ("IL+",)),
        ("NA", ("NA",)),
        # A suspension, a healthy player and a status the table does not know go nowhere.
        ("SUSP", ()),
        (None, ()),
        ("DTD", ()),
    ],
)
def test_each_status_fits_the_held_slots_yahoo_allows(status, slots):
    assert mv.held_slots_for(status) == slots
    for slot in mv.HELD:
        assert mv.eligible(status, slot) == (slot in slots)
    assert status is None or status == "DTD" or status in mv.KNOWN_STATUSES
    assert mv.HELD_CONFIRMED == {"IL"}


def test_an_out_player_can_move_to_an_open_il_slot_instead_of_a_drop():
    roster, cands, rate, sched, opponent, field = streaming_league()
    hurt = (5, Player(5, "Hurt", "MIN", ("C",), status="O"))
    banned = (6, Player(6, "Banned", "MIN", ("C",), status="SUSP"))
    rate |= {5: rates(1.0), 6: rates(1.0)}
    full = [*roster, hurt]
    p = build(full, cands, rate, sched, opponent, field, held_open={"IL": 1})
    assert mv.held_moves(p) == [(5, "IL")]
    assert mv.feasible(p, [mv.Move(10)])
    assert mv.held_used(p, [mv.Move(10)]) == [(5, "IL")]
    # Dropping the hurt player and also asking for his IL move does not fit.
    assert not mv.feasible(p, [mv.Move(10, 5), mv.Move(11)])
    # No IL slot, or a suspension, or an IL+ slot an INJ player fills first: no free move.
    assert not mv.feasible(build(full, cands, rate, sched, opponent, field), [mv.Move(10)])
    p = build([*roster, banned], cands, rate, sched, opponent, field, held_open={"IL": 1, "IL+": 1})
    assert mv.held_moves(p) == []
    gtd = (7, Player(7, "Maybe", "MIN", ("C",), status="GTD"))
    p = build([*roster, gtd], cands, rate, sched, opponent, field, held_open={"IL": 1, "IL+": 1})
    assert mv.held_moves(p) == [(7, "IL+")]
    # A questionable player fits no held slot; an INJ only IL+ (Yahoo's IL takes O and OFS).
    q = (8, Player(8, "Doubt", "MIN", ("C",), status="Q"))
    p = build([*roster, q], cands, rate, sched, opponent, field, held_open={"IL": 1, "IL+": 1})
    assert mv.held_moves(p) == []
    inj = (9, Player(9, "Hurt Long", "MIN", ("C",), status="INJ"))
    p = build([*roster, inj], cands, rate, sched, opponent, field, held_open={"IL": 1})
    assert mv.held_moves(p) == []
    na = (8, Player(8, "Rookie", "MIN", ("C",), status="NA"))
    p = build([*roster, na], cands, rate, sched, opponent, field, held_open={"NA": 1})
    assert mv.held_moves(p) == [(8, "NA")]


def test_a_held_player_whose_status_cleared_is_activated_on_the_first_day():
    """Yahoo refuses every add while a player on IL is no longer eligible for it: the model
    activates him on the first day and drops the least valuable active player then, with no
    move made as with any."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    back = (5, Player(5, "Back", "MIN", ("C",), status="Q"))
    rate |= {5: rates(1.0)}
    value = {k: 1.0 for k in rate} | {1: 1.2, 3: 0.1}
    p = build(
        roster, cands, rate, sched, opponent, field, held=[back], held_slots={5: "IL"}, value=value
    )
    assert mv.cleared(p) == [(5, "IL")]
    first = WEEKS[0][0]
    for key in ("week", "three"):
        assert mv.comebacks(p, key, []) == [mv.Comeback(5, "IL", first, 3)]
        assert mv.comebacks(p, key, [mv.Move(10, 1)]) == [mv.Comeback(5, "IL", first, 3)]
    # The base already counts him in and the third player out.
    ev = mv.Evaluator(p)
    alone = build([roster[0], roster[1], back], cands, rate, sched, opponent, field, value=value)
    assert ev.base["three"] == pytest.approx(mv.Evaluator(alone).base["three"])
    # Still out (O), or a healthy player in a bench spot: nothing to activate.
    out = (5, Player(5, "Back", "MIN", ("C",), status="O"))
    p = build(
        roster, cands, rate, sched, opponent, field, held=[out], held_slots={5: "IL"}, value=value
    )
    assert mv.cleared(p) == [] and mv.comebacks(p, "three", []) == []


def il_league(status="O"):
    """The streaming league with a fourth player of mine, out (``status``), and an open IL slot;
    per-game values rank the third player last."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    hurt = (5, Player(5, "Hurt", "MIN", ("C",), status=status))
    rate |= {5: rates(1.0)}
    value = {k: 1.0 for k in rate} | {1: 1.2, 3: 0.1}
    return [*roster, hurt], cands, rate, sched, opponent, field, value


def test_an_il_move_defers_the_drop_to_the_day_he_returns():
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    ev = mv.Evaluator(p)
    # Out this week, so he comes back next Monday, inside the three weeks only, and sends the
    # least valuable active player then.
    assert mv.comebacks(p, "week", [mv.Move(11)]) == []
    assert mv.comebacks(p, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 3)]
    # Over the three weeks the free move is worth the drop it defers, no more.
    assert ev.value("three", [mv.Move(11)]) == pytest.approx(ev.value("three", [mv.Move(11, 3)]))
    # This week it opens a spot: the third player still plays.
    assert ev.value("week", [mv.Move(10)]) > ev.value("week", [mv.Move(10, 3)])


def test_a_later_return_date_holds_him_out_until_then():
    roster, cands, rate, sched, opponent, field, value = il_league()
    late = WEEKS[2][2]
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    q = build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        field,
        held_open={"IL": 1},
        value=value,
        returns={5: late},
    )
    assert mv.comebacks(q, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", late, 3)]
    # He misses the week before it: the roster is worth less without a move.
    assert mv.Evaluator(q).base["three"] < mv.Evaluator(p).base["three"]
    week = wk.project_week(
        [(5, roster[-1][1])],
        rate,
        WEEKS[1],
        sched,
        ("C",),
        value,
        False,
        available_from={5: late},
    )
    assert week.players[5].games == 0


def test_an_injured_player_costs_no_drop_inside_the_horizon():
    roster, cands, rate, sched, opponent, field, value = il_league("OFS")
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    ev = mv.Evaluator(p)
    assert mv.comebacks(p, "three", [mv.Move(11)]) == []
    assert ev.value("three", [mv.Move(11)]) > ev.value("three", [mv.Move(11, 3)])


def test_the_returning_player_goes_himself_when_he_is_worth_least():
    roster, cands, rate, sched, opponent, field, value = il_league()
    value |= {5: 0.05}
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    assert mv.comebacks(p, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 5)]
    # He never plays again, so the move is worth what the add brings with the third player kept.
    ev = mv.Evaluator(p)
    alone = build(roster[:3], cands, rate, sched, opponent, field, spots=4, value=value)
    assert ev.gain("three", [mv.Move(11)]) == pytest.approx(
        mv.Evaluator(alone).value("three", [mv.Move(11)]) - mv.Evaluator(alone).base["three"],
        abs=1e-9,
    )


def test_an_open_spot_takes_an_add_without_a_drop():
    roster, cands, rate, sched, opponent, field = streaming_league()
    p = build(roster, cands, rate, sched, opponent, field, spots=4)
    ev = mv.Evaluator(p)
    best = mv.single_swaps(ev, "week")[10][0]
    assert best.drop is None and best.gain > 0


# --------------------------------------------------------------------------- the weekly limit
def test_adds_this_week_are_counted_from_the_transactions_page():
    def p(k: int) -> Player:
        return Player(k, f"P{k}")

    rows = [
        Transaction("drop", p(1), 3, None, "To Waivers", "Oct 28, 8:53 am", 0),
        Transaction("add", p(2), 3, None, "Free Agent", "Oct 27, 3:57 am", 1),
        Transaction("drop", p(3), 3, None, "To Waivers", "Oct 27, 3:57 am", 1),
        Transaction("add", p(4), 5, None, "$0 Waiver", "Oct 27, 3:57 am", 2),
        Transaction("add", p(6), 3, None, "$1 Waiver", "Oct 26, 9:00 pm", 3),
        Transaction("add", p(7), 3, None, "Free Agent", "Oct 24, 1:00 pm", 4),
    ]
    today = date(2026, 10, 28)
    used = mv.adds_used(rows, 3, WEEKS[0][0], WEEKS[0][6], today)
    assert used == mv.AddsUsed(2, True)
    # The page does not reach back past Monday: the count is a floor.
    assert mv.adds_used(rows[:4], 3, WEEKS[0][0], WEEKS[0][6], today) == mv.AddsUsed(1, False)
    assert mv.adds_used([], 3, WEEKS[0][0], WEEKS[0][6], today) == mv.AddsUsed(0, True)
    # A December date read in January belongs to the year before.
    assert mv.when_date("Dec 30, 1:00 pm", date(2027, 1, 2)) == date(2026, 12, 30)
    assert mv.when_date("Sept 3, 1:00 pm", date(2026, 10, 2)) == date(2026, 9, 3)
    assert mv.when_date("yesterday", today) is None


# --------------------------------------------------------------------------- the keep rule (#124)
def keep_league(**extra):
    """The IL league (player 5 out, an open IL slot) with made-up rest-of-season values: player 1
    well above the best add (candidate 10), player 2 above the average but below the add, player
    3 below both; the season runs a fortnight past the four weeks read."""
    roster, cands, rate, sched, opponent, field, value = il_league()
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    season = {1: 2.0, 2: 0.3, 3: -0.5, 5: 1.5, 10: 0.8, 11: 0.4}
    return replace(
        p,
        season_value=season,
        season_end=WEEKS[3][6] + timedelta(days=14),
        **extra,
    )


def test_the_keep_rule_reads_a_return_from_the_status_and_the_return_date():
    p = keep_league()
    hurt = dict(p.roster)[5]
    first = WEEKS[0][0]
    assert mv.back_from(p, 1, dict(p.roster)[1]) == first
    # An O without a date is back next Monday, as the move model brings him back; with a
    # later date, on it.
    assert mv.back_from(p, 5, hurt) == WEEKS[1][0]
    assert mv.comes_back(p, 5, hurt, (*p.horizons["week"], *p.horizons["three"])) == WEEKS[1][0]
    q = replace(p, returns={5: WEEKS[2][3]})
    assert mv.back_from(q, 5, hurt) == WEEKS[2][3]
    # Out for the season, or INJ without a date, never comes back; INJ with one does.
    assert mv.back_from(p, 5, replace(hurt, status="OFS")) is None
    assert mv.back_from(p, 5, replace(hurt, status="INJ")) is None
    assert mv.back_from(q, 5, replace(hurt, status="INJ")) == WEEKS[2][3]
    # A doubt with a date is back on it; a candidate from his move's day.
    assert mv.back_from(
        replace(p, returns={5: first + timedelta(3)}), 5, replace(hurt, status="GTD")
    ) == first + timedelta(3)
    late = replace(p, effective={10: first + timedelta(2), 11: first})
    assert mv.back_from(late, 10, dict(p.candidates)[10]) == first + timedelta(2)


def test_games_to_the_seasons_end_count_the_schedule_read_and_the_teams_rate_after():
    p = keep_league()
    # MIN plays 10 of the 28 days read: 6 from the second Monday, and 14 unread days at 10/28.
    assert mv.games_left(p, "MIN", WEEKS[1][0]) == pytest.approx(6 + 14 * 10 / 28)
    # The two apart, as the season horizon (#144) reports the extrapolated games.
    read, extrapolated = mv.games_ahead(p, "MIN", WEEKS[1][0])
    assert read == 6 and extrapolated == pytest.approx(14 * 10 / 28)
    assert mv.games_left(p, "MIN", p.season_end + timedelta(1)) == 0.0
    assert mv.games_left(p, None, WEEKS[1][0]) == 0.0
    assert mv.games_left(replace(p, season_end=None), "MIN", WEEKS[1][0]) == 0.0
    # Nothing read: a season's rate a day.
    empty = replace(p, schedule={})
    days = (p.season_end - WEEKS[1][0]).days + 1
    assert mv.games_left(empty, "MIN", WEEKS[1][0]) == pytest.approx(days * mv.GAMES_PER_DAY)


def test_the_value_net_of_return_is_the_value_above_a_dead_spot_times_the_games_after_it():
    p = keep_league(dead=0.5)
    hurt = dict(p.roster)[5]
    games = mv.games_left(p, "MIN", WEEKS[1][0])
    assert mv.net_of_return(p, 5, hurt) == pytest.approx((1.5 - 0.5) * games)
    assert mv.net_of_return(p, 5, replace(hurt, status="OFS")) == 0.0
    assert mv.net_of_return(replace(p, season_value={}), 5, hurt) is None


def test_the_keep_rule_protects_a_net_positive_player_better_than_the_best_add_who_returns():
    p = keep_league()
    rule = mv.keep_rule(p)
    assert (rule.best, rule.best_value) == (10, 0.8)
    one, two, three, five = (rule.players[k] for k in (1, 2, 3, 5))
    assert (one.net_positive, one.beats_best, one.returns, one.protected) == (
        True,
        True,
        True,
        True,
    )
    assert (two.net_positive, two.beats_best, two.protected) == (True, False, False)
    assert (three.net_positive, three.beats_best, three.protected) == (False, False, False)
    # Out until next Monday, still protected: the absence never decides it.
    assert five.protected and five.back == WEEKS[1][0] and not five.bench
    assert rule.kept == {1, 5}
    # A raised floor protects more (#164): the best add must beat a player by the floor to take
    # him off the list. Player 2 at 0.77, 0.03 below the add's 0.8, is protected at 0.05, and
    # beaten by exactly the floor at 0.03 he is not.
    close = replace(p, season_value={**p.season_value, 2: 0.77})
    assert mv.keep_rule(close).kept == {1, 5}
    assert mv.keep_rule(replace(close, floor=0.05)).kept == {1, 2, 5}
    assert mv.keep_rule(replace(close, floor=0.03)).kept == {1, 5}
    # A floor of 1.0 protects player 2 at 0.3 as well; player 3, below the pool's average, never.
    assert mv.keep_rule(replace(p, floor=1.0)).kept == {1, 2, 5}
    assert 3 not in mv.keep_rule(replace(p, floor=10.0)).kept
    # Out for the season is never protected, however good.
    ofs = replace(p, roster=(*p.roster[:3], (5, replace(p.roster[3][1], status="OFS"))))
    assert not mv.keep_rule(ofs).players[5].protected
    # No add with a line: any valued net-positive player beats it.
    assert mv.keep_rule(replace(p, season_value={1: 2.0, 2: 0.3})).kept == {1, 2}


def test_yahoos_cant_cut_list_protects_a_player_whatever_the_three_tests_say():
    """#220: a player Yahoo refuses to drop is protected like the keep rule's players; out, he
    still goes to an open held slot (Yahoo blocks drops, not IL moves)."""
    p = keep_league()
    # Player 3, below the pool's average and the add, is the weakest: the rule leaves him.
    base = mv.keep_rule(p)
    assert 3 not in base.kept and 3 in mv.drop_options(replace(p, kept=base.kept))
    cut = replace(p, cantcut=frozenset({3}))
    rule = mv.keep_rule(cut)
    three = rule.players[3]
    assert (three.net_positive, three.beats_best, three.protected, three.cantcut) == (
        False,
        False,
        True,
        True,
    )
    assert not three.bench and rule.kept == {1, 3, 5}
    kept = replace(cut, kept=rule.kept)
    assert 3 not in mv.drop_options(kept)
    ev = mv.Evaluator(kept)
    for key in ("week", "three"):
        assert all(g.drop != 3 for gs in mv.single_swaps(ev, key).values() for g in gs)
        assert all(m.drop != 3 for m in mv.search(ev, key, [10, 11]))
    # Out and below the best add: droppable by the three tests, stashed when he is can't-cut.
    worse = replace(p, season_value=p.season_value | {5: 0.5})
    assert mv.stash_advice(worse, mv.keep_rule(worse))[0].advice == mv.DROPPABLE
    out = replace(worse, cantcut=frozenset({5}))
    (a,) = mv.stash_advice(out, mv.keep_rule(out))
    assert (a.player, a.advice, a.slot, a.protected) == (5, mv.STASH, "IL", True)
    # A can't-cut id not on my roster changes nothing.
    assert mv.keep_rule(replace(p, cantcut=frozenset({99}))).kept == mv.keep_rule(p).kept


def test_a_short_absence_keeps_a_player_better_than_the_best_add_on_the_bench():
    """Above the best add but not net positive (a points league's average above both), back in
    three days: kept for the solve and benched, not protected."""
    first = WEEKS[0][0]
    p = keep_league(average=1.8)
    doubt = (5, replace(dict(p.roster)[5], status="GTD"))
    p = replace(p, roster=(*p.roster[:3], doubt), returns={5: first + timedelta(3)})
    rule = mv.keep_rule(p)
    five = rule.players[5]
    assert (five.net_positive, five.beats_best, five.protected, five.bench) == (
        False,
        True,
        False,
        True,
    )
    # Player 1 is above the average and the add: protected; nobody else.
    assert rule.kept == {1, 5}
    # Back in a week or more: no bench, he may be dropped.
    later = replace(p, returns={5: first + timedelta(mv.SHORT_ABSENCE_DAYS)})
    assert mv.keep_rule(later).kept == {1}


def test_a_kept_player_is_never_a_drop_nor_the_one_a_return_sends():
    roster, cands, rate, sched, opponent, field, value = il_league()
    value |= {2: 0.5}
    p = build(roster, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    assert mv.comebacks(p, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 3)]
    kept = replace(p, kept=frozenset({3}))
    assert 3 not in mv.drop_options(kept) and 3 in mv.drop_options(p)
    ev = mv.Evaluator(kept)
    for key in ("week", "three"):
        assert all(g.drop != 3 for gs in mv.single_swaps(ev, key).values() for g in gs)
        assert all(m.drop != 3 for m in mv.search(ev, key, [10, 11]))
    # The return sends the weakest player the rule does not keep.
    assert mv.comebacks(kept, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 2)]
    # When it keeps everyone, the weakest of all goes.
    every = replace(p, kept=frozenset({1, 2, 3, 5, 11}))
    assert mv.comebacks(every, "three", [mv.Move(11)]) == [mv.Comeback(5, "IL", WEEKS[1][0], 3)]


def test_the_latest_to_return_takes_the_one_open_slot_roster_order_breaking_ties():
    roster, cands, rate, sched, opponent, field, value = il_league()
    soon = (6, Player(6, "Soon", "MIN", ("C",), status="O"))
    rate |= {6: rates(1.0)}
    full = [*roster, soon]
    returns = {5: WEEKS[1][3], 6: WEEKS[2][0]}
    p = build(
        full, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value, returns=returns
    )
    assert mv.held_moves(p) == [(6, "IL")]
    # The same return: the first on the roster.
    same = build(full, cands, rate, sched, opponent, field, held_open={"IL": 1}, value=value)
    assert mv.held_moves(same) == [(5, "IL")]
    # Out for the season before any return.
    ofs = (7, Player(7, "Gone", "MIN", ("C",), status="OFS"))
    rate |= {7: rates(1.0)}
    p = build(
        [*full, ofs],
        cands,
        rate,
        sched,
        opponent,
        field,
        held_open={"IL": 2},
        value=value,
        returns=returns,
    )
    assert mv.held_moves(p) == [(7, "IL"), (6, "IL")]


def il_full_league(occupants, season):
    """The keep league with the IL taken: ``occupants`` (key, status) sit in it."""
    roster, cands, rate, sched, opponent, field, value = il_league()
    held = [(k, Player(k, f"P{k}", "MIN", ("C",), status=st)) for k, st in occupants]
    rate |= {k: rates(1.0) for k, _ in occupants}
    p = build(
        roster,
        cands,
        rate,
        sched,
        opponent,
        field,
        held=held,
        held_slots={k: "IL" for k, _ in occupants},
        value=value | {k: 1.0 for k, _ in occupants},
    )
    base = {1: 2.0, 2: 0.3, 3: -0.5, 5: 1.5, 10: 0.8, 11: 0.4}
    return replace(p, season_value=base | season, season_end=WEEKS[3][6] + timedelta(days=14))


def test_the_il_advice_stashes_a_protected_player_into_an_open_slot_with_the_freed_spot():
    p = keep_league()
    rule = mv.keep_rule(p)
    (a,) = mv.stash_advice(p, rule)
    assert (a.player, a.advice, a.slot, a.slots, a.protected) == (5, mv.STASH, "IL", ("IL",), True)
    assert a.net == pytest.approx(mv.net_of_return(p, 5, dict(p.roster)[5]))
    # Not protected (the add is better): the moves may drop him.
    worse = replace(p, season_value=p.season_value | {5: 0.5})
    (a,) = mv.stash_advice(worse, mv.keep_rule(worse))
    assert a.advice == mv.DROPPABLE and a.leave is None
    # Healthy players and a doubt who may play today have no advice.
    assert all(x.player == 5 for x in mv.stash_advice(p, rule))


def test_a_full_il_names_its_occupant_with_the_least_value_net_of_return():
    # An INJ in IL would be cleared (Yahoo's IL takes O and OFS): both are O.
    p = il_full_league([(7, "O"), (8, "O")], {7: 3.0, 8: 0.2})
    p = replace(p, returns={8: WEEKS[2][0]})
    rule = mv.keep_rule(p)
    (a,) = mv.stash_advice(p, rule)
    # The league has no IL+: the only slot is IL.
    assert (a.advice, a.slot, a.slots) == (mv.IL_FULL, None, ("IL",))
    lv = a.leave
    assert (lv.player, lv.slot, lv.how, lv.drop, lv.protected) == (8, "IL", "drop", 8, False)
    assert lv.net == pytest.approx(mv.net_of_return(p, 8, dict(p.held)[8]))
    # The ranking governs even for a protected occupant, marked as such.
    both = replace(p, season_value=p.season_value | {8: 1.0})
    lv = mv.stash_advice(both, mv.keep_rule(both))[0].leave
    assert (lv.player, lv.protected) == (8, True)


def test_a_cleared_occupant_leaves_a_full_il_first_activated_with_the_weakest_dropped():
    p = il_full_league([(7, "O"), (8, None)], {7: 0.1, 8: 3.0})
    rule = mv.keep_rule(p)
    (a,) = mv.stash_advice(p, rule)
    sends = {c.player: c.drop for c in mv.comebacks(p, "week", ())}
    assert a.advice == mv.IL_FULL
    assert a.leave == mv.Leave(8, "IL", "activate", sends[8], None, False)
