"""The week's stake (#172, the guard PR, ``sim/stake.py``): ``L`` from the finished weeks'
standings, the gap to the cut line against the weeks left, and full in the bracket. The pure
rule, in both head-to-head formats and a points league. Made-up totals; no season is played
here (``test_sim_guard.py`` plays them)."""

from __future__ import annotations

import math

import pytest

from pickandroll.sim import league as lg
from pickandroll.sim import stake
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN

FORMATS = (ONE_WIN, EACH_CATEGORY)
#: Nine categories a higher total wins, so a week's margin is set by how many each side takes.
CATS = ("pts", "reb", "ast", "stl", "blk", "threes", "fgm", "ftm", "fta")
#: Four teams, five regular weeks, a final between the top two in week 6.
PAIRS = {
    1: ((1, 2), (3, 4)),
    2: ((1, 3), (2, 4)),
    3: ((1, 4), (2, 3)),
    4: ((1, 2), (3, 4)),
    5: ((1, 3), (2, 4)),
}
LAST = max(PAIRS)
FINAL = LAST + 1


def league(h2h: str = ONE_WIN, field: int = 2, tiebreak=None) -> lg.LeagueSpec:
    own = lg.TIEBREAK_EACH if h2h == EACH_CATEGORY else lg.TIEBREAK
    return lg.LeagueSpec((1, 2, 3, 4), PAIRS, (FINAL,), CATS, playoff_teams=field, byes=0,
                         tiebreak=tiebreak or own, h2h=h2h)  # fmt: skip


def points_league() -> lg.LeagueSpec:
    return lg.LeagueSpec((1, 2, 3, 4), PAIRS, (FINAL,), (), "points", {"pts": 1.0}, 2, 0,
                         lg.TIEBREAK_POINTS)  # fmt: skip


def week(a: int, b: int, won: int, tied: int = 0) -> dict[int, dict[str, float]]:
    """``a``'s and ``b``'s totals in a week ``a`` wins ``won`` categories of and ties ``tied``."""
    mine = {c: 2.0 if i < won else 1.0 if i < won + tied else 0.0 for i, c in enumerate(CATS)}
    return {a: mine, b: {c: 2.0 - x for c, x in mine.items()}}


def weeks(played: dict[int, list[tuple[int, ...]]]) -> dict[int, dict[int, dict[str, float]]]:
    """Week to each pair's ``(a, b, a's categories won[, tied])``, as totals."""
    return {w: {t: x for p in ps for t, x in week(*p).items()} for w, ps in played.items()}


#: After two weeks: team 1 is 2-0, teams 2 and 3 are 1-1, team 4 is 0-2; every win is 5-4 but
#: team 3's over team 4, which is 9-0. The field is the top two.
TWO_WEEKS = weeks({1: [(1, 2, 5), (3, 4, 9)], 2: [(1, 3, 5), (2, 4, 5)]})


# --------------------------------------------------------------------------- the formula
def test_a_seat_level_with_the_line_in_the_last_regular_week_has_a_stake_of_one():
    assert stake.swing(0.0, 0) == 1.0
    assert stake.WITHIN_ONE == pytest.approx(math.erf(1 / math.sqrt(2)))


def test_the_stake_falls_as_the_lead_grows_either_way():
    for after in (0, 3, 12):
        got = [stake.swing(d, after) for d in (0.0, 0.5, 1.0, 2.0, 4.0, 8.0)]
        assert got == sorted(got, reverse=True) and len(set(got)) == len(got), (after, got)
        assert all(stake.swing(-d, after) == stake.swing(d, after) for d in (0.5, 1.0, 4.0))
        assert all(0.0 <= x <= 1.0 for x in got)


def test_at_a_lead_of_zero_the_stake_rises_as_the_weeks_run_out():
    got = [stake.swing(0.0, after) for after in range(20, -1, -1)]
    assert got == sorted(got) and len(set(got)) == len(got)
    assert got[0] < 0.25 and got[-1] == 1.0
    # By hand, one week after this one: the spread is the root of three.
    by_hand = math.erf(1 / math.sqrt(6)) / math.erf(1 / math.sqrt(2))
    assert stake.swing(0.0, 1) == pytest.approx(by_hand, abs=1e-11)


def test_a_seat_far_out_or_far_in_has_next_to_no_stake():
    # Six weeks clear of the line with one to play, where a week is one result: twelve spreads.
    assert stake.swing(12.0, 1) < 1e-6 and stake.swing(-12.0, 1) < 1e-6
    assert stake.swing(12.0, 0) == 0.0


def test_the_stake_is_rounded_so_a_last_bit_of_erf_decides_nothing(monkeypatch):
    """The lesson of #387: ``erf`` may differ in its last bit between two machines; ``L`` is
    rounded to twelve places before anything reads it."""
    cases = [(d, n) for d in (0.0, 0.3, 1.0, 2.5) for n in (0, 1, 7)]
    before = [stake.swing(d, n) for d, n in cases]
    assert all(x == round(x, stake.DECIMALS) for x in before) and stake.DECIMALS == 12
    real = stake.phi
    monkeypatch.setattr(stake, "phi", lambda x: real(x) * (1 + 2e-16))
    assert [stake.swing(d, n) for d, n in cases] == before


# --------------------------------------------------------------------------- the lead
@pytest.mark.parametrize("h2h", FORMATS)
def test_the_lead_is_over_the_cut_line_in_weeks_by_the_format_s_measure(h2h):
    """Inside the field the line is the best team outside it; outside, the last team inside."""
    spec = league(h2h)
    table = stake.table_before(spec, TWO_WEEKS, 3)
    order = [row.team for row in table]
    if h2h == ONE_WIN:
        # 2-0, then the two 1-1 teams by category wins (team 3's 13 against team 2's 9), 0-2.
        assert order == [1, 3, 2, 4]
        want = {1: 1.0, 3: 0.0, 2: 0.0, 4: -1.0}
        assert stake.variance(spec) == 0.25
    else:
        # By the category percentage: team 3 has 13 of 18, team 1 has 10, team 2 has 9, team 4 4.
        assert order == [3, 1, 2, 4]
        want = {3: (13 - 9) / 9, 1: (10 - 9) / 9, 2: (9 - 10) / 9, 4: (4 - 10) / 9}
        assert stake.variance(spec) == pytest.approx(0.25 / 9)
    for team, lead in want.items():
        assert stake.lead(table, spec, team) == pytest.approx(lead), team
    # The stake is the formula on that lead in units of a week's spread, three weeks to play.
    for team, lead in want.items():
        delta = lead / math.sqrt(stake.variance(spec))
        assert stake.level(spec, TWO_WEEKS, team, 3) == stake.swing(delta, LAST - 3)


def test_a_points_league_s_week_is_one_result():
    spec = points_league()
    totals = {
        1: {1: {"pts": 10.0}, 2: {"pts": 9.0}, 3: {"pts": 31.0}, 4: {"pts": 1.0}},
        2: {1: {"pts": 10.0}, 3: {"pts": 9.0}, 2: {"pts": 30.0}, 4: {"pts": 1.0}},
    }
    table = stake.table_before(spec, totals, 3)
    # 2-0, then the two 1-1 teams by points for, then 0-2.
    assert [row.team for row in table] == [1, 3, 2, 4] and stake.variance(spec) == 0.25
    assert [stake.lead(table, spec, t) for t in (1, 3, 2, 4)] == [1.0, 0.0, 0.0, -1.0]
    assert stake.level(spec, totals, 1, 3) == stake.swing(2.0, 2)
    assert stake.level(spec, totals, 2, 3) == stake.level(spec, totals, 3, 3) == stake.swing(0, 2)


@pytest.mark.parametrize("h2h", FORMATS)
def test_with_no_week_finished_the_lead_is_zero(h2h):
    spec = league(h2h)
    for team in spec.teams:
        assert stake.lead(stake.table_before(spec, {}, 1), spec, team) == 0.0
        assert stake.level(spec, {}, team, 1) == stake.swing(0.0, LAST - 1)
    # A week's totals already running are not finished: week 1's are not read in week 1.
    assert stake.level(spec, TWO_WEEKS, 1, 1) == stake.swing(0.0, LAST - 1)


@pytest.mark.parametrize("h2h", FORMATS)
def test_only_the_weeks_finished_before_this_one_are_read(h2h):
    """The running week and every later one may hold anything: the stake does not move."""
    spec = league(h2h)
    later = weeks({3: [(4, 1, 9), (2, 3, 9)], 4: [(2, 1, 9), (4, 3, 9)], FINAL: [(4, 3, 9)]})
    for team in spec.teams:
        assert stake.level(spec, {**TWO_WEEKS, **later}, team, 3) == stake.level(
            spec, TWO_WEEKS, team, 3
        )
    # And a finished week is: team 2 a week on, with the week 3 it won in the table or not.
    assert stake.level(spec, {**TWO_WEEKS, **later}, 2, 4) != stake.level(spec, TWO_WEEKS, 2, 4)


def test_a_league_with_no_cut_line_has_no_stake_before_the_bracket():
    everyone = league(field=4)
    assert stake.lead(stake.table_before(everyone, TWO_WEEKS, 3), everyone, 1) is None
    assert [stake.level(everyone, TWO_WEEKS, t, 3) for t in everyone.teams] == [0.0] * 4
    assert [stake.level(everyone, TWO_WEEKS, t, FINAL) for t in everyone.teams] == [1.0] * 4
    # A team the league does not hold has none.
    assert stake.level(league(), TWO_WEEKS, 9, 3) == 0.0


# --------------------------------------------------------------------------- the bracket
#: The regular season whole, one win a matchup: team 1 wins all five, teams 2 and 3 end with two
#: wins and team 4 with one. Teams 2 and 3 tie on the record: team 3 has the more category wins
#: (its 9-0 over team 4 in week 1), and team 2 won their one meeting (week 3).
FULL = weeks(
    {
        1: [(1, 2, 5), (3, 4, 9)],
        2: [(1, 3, 5), (2, 4, 5)],
        3: [(1, 4, 5), (2, 3, 5)],
        4: [(1, 2, 5), (3, 4, 5)],
        5: [(1, 3, 5), (4, 2, 5)],
    }
)
#: A final's week of totals for every team, whoever is in it.
PLAYED = weeks({FINAL: [(1, 2, 5), (3, 4, 5)]})


def test_in_the_bracket_s_weeks_the_stake_is_one_inside_the_field_and_zero_outside():
    spec = league()
    final = stake.table_before(spec, FULL, None)
    assert [(r.team, r.wins) for r in final] == [(1, 5), (3, 2), (2, 2), (4, 1)]
    got = {t: stake.level(spec, FULL, t, FINAL) for t in spec.teams}
    assert got == {1: 1.0, 3: 1.0, 2: 0.0, 4: 0.0}
    # The bracket's own week is not read: whoever wins the final, the field is the field.
    after = {**FULL, **weeks({FINAL: [(3, 1, 9), (4, 2, 9)]})}
    assert {t: stake.level(spec, after, t, FINAL) for t in spec.teams} == got


def test_a_tie_at_the_line_is_broken_as_the_league_breaks_it():
    """Teams 2 and 3 end level on the record, at the line. The league's tiebreak (category
    wins, then head to head) puts team 3 in the field; a league that breaks on head to head
    alone puts team 2 in. The stake in the final's week follows the league's own table either
    way, which is the season's own."""
    spec = league()
    assert [r.team for r in stake.table_before(spec, FULL, None)] == [1, 3, 2, 4]
    assert (stake.level(spec, FULL, 3, FINAL), stake.level(spec, FULL, 2, FINAL)) == (1.0, 0.0)
    other = league(tiebreak=("head_to_head",))
    assert [r.team for r in stake.table_before(other, FULL, None)] == [1, 2, 3, 4]
    assert (stake.level(other, FULL, 3, FINAL), stake.level(other, FULL, 2, FINAL)) == (0.0, 1.0)
    for s in (spec, other):
        assert stake.table_before(s, FULL, None) == list(lg.season(s, {**FULL, **PLAYED}).standings)
    # In a regular week the two are level with the line either way: a tie in the table moves
    # who the line's team is, not the lead.
    for s in (spec, other):
        table = stake.table_before(s, FULL, LAST)
        assert stake.lead(table, s, 2) == stake.lead(table, s, 3) == 0.0


def test_a_head_to_head_tiebreak_reads_the_meetings_played_not_the_ones_to_come():
    """The table before a week is the league's standings on the pairings of the finished weeks:
    a meeting still to come has no result to read."""
    other = league(tiebreak=("head_to_head",))
    table = stake.table_before(other, TWO_WEEKS, 3)
    # Teams 2 and 3 are 1-1 and have not met: the team's number orders them.
    assert [r.team for r in table] == [1, 2, 3, 4]
    assert [(r.wins, r.losses) for r in table] == [(2, 0), (1, 1), (1, 1), (0, 2)]


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_last_regular_week_of_a_seat_level_with_the_line_is_a_full_stake(h2h):
    """Four weeks in, every team 2-2 with the same category wins: each is level with the line in
    the last regular week, and its stake is 1; a week earlier it was less."""
    spec = league(h2h)
    even = weeks(
        {
            1: [(1, 2, 5), (3, 4, 5)],
            2: [(3, 1, 5), (4, 2, 5)],
            3: [(1, 4, 5), (2, 3, 5)],
            4: [(2, 1, 5), (4, 3, 5)],
        }
    )
    table = stake.table_before(spec, even, LAST)
    assert {(r.wins, r.losses, r.category_wins) for r in table} == {(2, 2, 18.0)}
    for team in spec.teams:
        assert stake.level(spec, even, team, LAST) == 1.0
        assert stake.level(spec, even, team, LAST - 1) < 1.0
