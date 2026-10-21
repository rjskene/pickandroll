"""The move model (#94): single moves and their prices, the recommended set under the weekly
add limit, waiver claims from their clear date, held-slot moves and the field. Every league here
is made up; the outcomes are set by construction (games, rates) rather than read off a solver."""

from __future__ import annotations

import itertools
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
        value={k: 1.0 for k in rate},
        cats=cats,
        points=None,
        no_games=frozenset(),
        horizons=spans,
        limits=tuple(limits or ()),
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
    members, gone = ev._after(frozenset({mv.Move(10, 3)}))
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
    members, gone = ev._after(frozenset({mv.Move(11, 3)}))
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
    assert ev._week(span, list(roster), {}) == pytest.approx(sum(each) / 2)
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
def test_an_out_player_can_move_to_an_open_il_slot_instead_of_a_drop():
    roster, cands, rate, sched, opponent, field = streaming_league()
    hurt = (5, Player(5, "Hurt", "MIN", ("C",), status="INJ"))
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
    na = (8, Player(8, "Rookie", "MIN", ("C",), status="NA"))
    p = build([*roster, na], cands, rate, sched, opponent, field, held_open={"NA": 1})
    assert mv.held_moves(p) == [(8, "NA")]


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
