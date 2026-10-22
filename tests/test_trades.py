"""The trade evaluator (#96): both sides before and after on the move optimiser's horizons, the
counterparty as this week's opponent, an over-full roster's drop, a freed spot's add, the held
slots, the effective date and the neutral margin. Every league here is made up; the outcomes are
set by construction (games, rates) rather than read off a solver."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from pickandroll.season import Player
from pickandroll.season import moves as mv
from pickandroll.season import trades as tr

MON = date(2026, 10, 26)
WEEKS = [tuple(MON + timedelta(7 * w + n) for n in range(7)) for w in range(4)]
COUNTING = ("pts", "reb", "ast")
SLOTS = ("C", "C", "Util")


def rates(level: float = 1.0) -> dict[str, float]:
    """A line scaled by ``level``; shooting and turnovers fixed so the counting stats decide."""
    return {
        "pts": 10 * level,
        "threes": 1 * level,
        "reb": 5 * level,
        "ast": 3 * level,
        "stl": 1 * level,
        "blk": 1 * level,
        "tov": 2.0,
        "fgm": 4.0,
        "fga": 8.0,
        "ftm": 2.0,
        "fta": 2.5,
    }


def every_other_day(team: str = "MIN") -> dict[date, frozenset[str]]:
    days = [d for w in WEEKS for d in w]
    return {d: frozenset({team} if i % 2 == 0 else ()) for i, d in enumerate(days)}


def player(key: int, team: str = "MIN", status: str | None = None) -> tr.Member:
    return (key, Player(key, f"P{key}", team, ("C",), status=status))


def league(
    levels: dict[int, dict[int, float]],
    pairs: dict[int, int] | None = None,
    *,
    spots: int = 3,
    held_slots: dict[str, int] | None = None,
    statuses: dict[int, str] | None = None,
    teams_of: dict[int, str] | None = None,
    extra_rates: dict[int, float] | None = None,
) -> tr.League:
    """A league from ``{team: {player: level}}``: everyone on one NBA team playing every other
    day, this week against ``pairs`` and the three weeks after against the field."""
    statuses, teams_of = statuses or {}, teams_of or {}
    rate = {k: rates(v) for t in levels.values() for k, v in t.items()}
    rate |= {k: rates(v) for k, v in (extra_rates or {}).items()}
    teams = {
        t: tr.TeamRoster(tuple(player(k, teams_of.get(k, "MIN"), statuses.get(k)) for k in members))
        for t, members in levels.items()
    }
    return tr.League(
        teams=teams,
        spots=spots,
        held_slots=held_slots or {},
        rates=rate,
        schedule=every_other_day(),
        slots=SLOTS,
        value={k: r["pts"] for k, r in rate.items()},
        cats=COUNTING,
        points=None,
        no_games=frozenset(),
        value_of=lambda r: r["pts"],
        horizons={
            "week": (tr.Span(WEEKS[0], True, pairs or {1: 2, 2: 1, 3: 4, 4: 3}),),
            "three": tuple(tr.Span(w, False) for w in WEEKS[1:]),
        },
    )


LEVELS = {
    1: {11: 1.0, 12: 0.8, 13: 0.6},
    2: {21: 1.4, 22: 1.0, 23: 1.0},
    3: {31: 1.4, 32: 1.0, 33: 1.0},
    4: {41: 1.2, 42: 1.0, 43: 0.8},
}


def trade(give, get, theirs=2, effective=MON) -> tr.Trade:
    return tr.Trade(1, theirs, tuple(give), tuple(get), effective)


def test_a_one_for_one_up_the_scale_helps_me_and_costs_them_on_both_horizons():
    rep = tr.evaluate(league(LEVELS), trade([13], [21]))
    for key in ("week", "three"):
        assert rep.mine.change(key) > 0
        assert rep.theirs.change(key) < 0
    assert rep.mine.roster.valid and rep.theirs.roster.valid
    assert (rep.mine.roster.open, rep.theirs.roster.open) == (0, 0)
    # The per-category change carries the total: no category is set aside.
    week = rep.mine
    per_cat = {c: week.after["three"][c] - week.before["three"][c] for c in COUNTING}
    assert set(per_cat) == set(COUNTING)
    assert sum(per_cat.values()) == pytest.approx(week.change("three"))
    assert all(v > 0 for v in per_cat.values())


def test_trading_with_this_weeks_opponent_moves_both_sides_of_the_matchup():
    lg = league(LEVELS)
    with_opponent = tr.evaluate(lg, trade([13], [21], theirs=2))
    with_other = tr.evaluate(lg, trade([13], [31], theirs=3))
    # Teams 2 and 3 are the same rosters; only team 2 plays me this week, and it gets weaker.
    assert with_opponent.mine.change("week") > with_other.mine.change("week") > 0
    # Over the field the two trades are the same trade.
    assert with_opponent.mine.change("three") == pytest.approx(with_other.mine.change("three"))


def test_an_over_full_roster_drops_the_player_it_misses_least_and_is_not_valid_as_entered():
    rep = tr.evaluate(league(LEVELS), trade([13], [21, 22]))
    mine = rep.mine.roster
    assert not mine.valid
    assert mine.active == 4 and mine.drops == (12,)
    # Their side gave two for one: a spot opens, nothing to drop.
    assert rep.theirs.roster.valid and rep.theirs.roster.open == 1
    # The drop is the player the new roster benches every day: it costs my side nothing.
    ev = tr.Evaluator(league(LEVELS))
    undropped = ev.won("three", 1, tr.changes_of(trade([13], [21, 22])))
    assert rep.mine.after["three"] == pytest.approx(undropped)


def test_a_two_for_one_frees_a_spot_and_prices_its_best_add_beside_the_trade():
    lg = league(LEVELS, extra_rates={51: 0.9, 52: 0.5})
    pool = [(player(51), MON), (player(52), MON)]
    rep = tr.evaluate(lg, trade([12, 13], [21]), pool=pool)
    assert rep.mine.roster.valid and rep.mine.roster.open == 1
    assert rep.theirs.roster.drops and not rep.theirs.roster.valid
    assert rep.fill is not None and rep.fill.add == 51
    assert rep.fill.gain["three"] > 0
    # The add is valued beside the trade, never inside it.
    plain = tr.evaluate(lg, trade([12, 13], [21]))
    assert rep.mine.after == plain.mine.after
    # A week without adds left takes none.
    spent = [mv.AddLimit(WEEKS[0][0], WEEKS[-1][-1], 0)]
    assert tr.evaluate(lg, trade([12, 13], [21]), pool=pool, limits=spent).fill is None


def test_a_received_injured_player_takes_an_open_held_slot_instead_of_a_drop():
    lg = league(LEVELS, held_slots={"IL": 1}, statuses={23: "OFS"})
    rep = tr.evaluate(lg, trade([13], [21, 23]))
    assert rep.mine.roster.valid
    assert rep.mine.roster.held_moves == ((23, "IL"),)
    assert rep.mine.roster.active == 3


def test_a_trade_effective_after_this_week_changes_nothing_this_week():
    late = WEEKS[1][2]
    rep = tr.evaluate(league(LEVELS), trade([13], [21], effective=late))
    assert rep.mine.change("week") == pytest.approx(0.0, abs=1e-12)
    assert rep.theirs.change("week") == pytest.approx(0.0, abs=1e-12)
    assert rep.mine.change("three") > 0
    # Each traded player plays for his old team until the date and his new one from it.
    m = next(x for x in rep.moved if x.player == 21)
    assert (m.old, m.new) == (2, 1)
    assert m.before["week"].games == m.on_old["week"].games == 4
    assert m.on_new["week"].games == 0
    assert m.on_old["three"].games + m.on_new["three"].games == m.before["three"].games
    assert m.on_old["three"].games == 1


def test_the_margin_is_the_share_of_what_i_receive_that_leaves_me_neutral():
    lg = league(LEVELS)
    even = tr.evaluate(lg, trade([12], [22])).margin
    assert even is not None and even.reading == "crosses"
    # 22 at 80% of his line is 12 on my side; team 2 holds the weaker player in my field, so
    # the trade is neutral a little below that.
    assert 0.7 < even.neutral < 0.8
    up = tr.evaluate(lg, trade([13], [21])).margin
    assert up.reading == "crosses" and up.change > 0 and 0 < up.neutral < even.neutral


def test_the_margin_names_the_ends_it_falls_past():
    # 99 never plays: receiving him loses at any scale; giving him away wins at none.
    lg = league(
        {**LEVELS, 2: {**LEVELS[2], 99: 1.0}, 1: {**LEVELS[1], 98: 1.0}},
        spots=4,
        teams_of={99: "OFF", 98: "OFF"},
    )
    loses = tr.evaluate(lg, trade([11], [99])).margin
    assert loses.reading == "loses_at_max" and loses.neutral is None
    wins = tr.evaluate(lg, trade([98], [23])).margin
    assert wins.reading == "wins_at_zero" and wins.neutral is None
    assert tr.evaluate(lg, trade([98], [])).margin is None
