"""The head-to-head format (#172, the format PR): one win per matchup, or every category.

The rule (``shapes.LeagueRules.h2h``, ``replay --h2h``), the standings that read it
(``league.standings``), the playoffs that do not, and the league ``run.replay_setup`` builds.
Every test of the format runs in both formats. Made-up leagues only."""

from __future__ import annotations

from pathlib import Path

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import league as lg
from pickandroll.sim import shapes
from pickandroll.sim.engine import EACH_CATEGORY, ONE_WIN
from tests.sim.test_sim_points import TABLE, setup_of
from tests.sim.test_sim_rules_run import pinned_clock, replay, spec, wire, written  # noqa: F401

FORMATS = (ONE_WIN, EACH_CATEGORY)
#: Nine categories a higher total wins, so a week's margin is set by how many each side takes.
CATS = ("pts", "reb", "ast", "stl", "blk", "threes", "fgm", "ftm", "fta")
#: Four teams, three regular weeks, a final between the top two in week 4.
PAIRS = {1: ((1, 2), (3, 4)), 2: ((1, 3), (2, 4)), 3: ((1, 4), (2, 3))}


def league(h2h: str, pairs=PAIRS) -> lg.LeagueSpec:
    tiebreak = lg.TIEBREAK_EACH if h2h == EACH_CATEGORY else lg.TIEBREAK
    return lg.LeagueSpec((1, 2, 3, 4), pairs, (4,), CATS, playoff_teams=2, byes=0,
                         tiebreak=tiebreak, h2h=h2h)  # fmt: skip


def week(a: int, b: int, won: int, tied: int = 0) -> dict[int, dict[str, float]]:
    """``a``'s and ``b``'s totals in a week ``a`` wins ``won`` categories of and ties ``tied``."""
    mine = {c: 2.0 if i < won else 1.0 if i < won + tied else 0.0 for i, c in enumerate(CATS)}
    return {a: mine, b: {c: 2.0 - x for c, x in mine.items()}}


def season(weeks: dict[int, list[tuple[int, ...]]], final: tuple[int, ...] = (1, 2, 5)):
    """Week to each pair's ``(a, b, a's categories won[, tied])``, and the final's, as totals."""
    totals = {w: {t: x for p in ps for t, x in week(*p).items()} for w, ps in weeks.items()}
    totals[4] = week(*final)
    return totals


#: Team 1 wins every week narrowly (5-4), team 2 loses to it narrowly and wins its other two weeks
#: 9-0: one win per matchup ranks team 1 first (3-0 against 2-1), every category team 2 (22 of 27
#: categories against 15).
NARROW_AND_WIDE = season(
    {1: [(1, 2, 5), (3, 4, 5)], 2: [(1, 3, 5), (2, 4, 9)], 3: [(1, 4, 5), (2, 3, 9)]}
)


# --------------------------------------------------------------------------- the rule
def test_the_format_is_one_win_per_matchup_by_default_and_every_category_when_named():
    assert shapes.H2H == (ONE_WIN, EACH_CATEGORY) == ("one_win", "each_category")
    assert shapes.PLAIN.h2h == ONE_WIN and shapes.PLAIN.one_win
    assert shapes.parse_h2h("categories", None) == ONE_WIN
    for h2h in FORMATS:
        assert shapes.parse_h2h("categories", h2h) == h2h
        assert shapes.parse_h2h("categories", h2h.upper()) == h2h
    each = shapes.LeagueRules(h2h=EACH_CATEGORY)
    assert not each.one_win and each != shapes.PLAIN
    # Hashable and told apart by the format alone.
    assert len({shapes.PLAIN, each, shapes.LeagueRules(h2h=ONE_WIN)}) == 2


def test_a_format_named_with_points_or_out_of_the_two_is_refused_by_name():
    for h2h in FORMATS:
        with pytest.raises(ValueError, match=f"--h2h {h2h}: a points league's week is one result"):
            shapes.parse_h2h("points", h2h)
    with pytest.raises(ValueError, match="--h2h each: one of one_win, each_category"):
        shapes.parse_h2h("categories", "each")
    with pytest.raises(ValueError, match="with scoring points: a points league's week is one"):
        shapes.LeagueRules("points", shapes.POINTS_DEFAULT, h2h=EACH_CATEGORY)
    with pytest.raises(ValueError, match="'roto' is not one of one_win, each_category"):
        shapes.LeagueRules(h2h="roto")
    # A points league holds the default: its measure is its own, not the matchup's odds.
    points = shapes.LeagueRules("points", shapes.POINTS_DEFAULT)
    assert points.h2h == ONE_WIN and not points.one_win


def test_the_label_says_every_category_and_leaves_the_default_unsaid():
    each = shapes.LeagueRules(held=("IL",), waivers="priority", h2h=EACH_CATEGORY)
    assert each.label() == (
        "the nine categories, every category counted, one IL slot, waivers by priority after 2 days"
    )
    assert shapes.LeagueRules(held=("IL",), waivers="priority").label() == (
        "the nine categories, one IL slot, waivers by priority after 2 days"
    )


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_payload_names_the_format_in_a_categories_league_and_none_in_points(h2h):
    rules = shapes.LeagueRules(h2h=h2h)
    assert rules.payload() == {"scoring": "categories", "points": None, "held": [], "h2h": h2h}
    assert "h2h" not in shapes.LeagueRules("points", shapes.POINTS_DEFAULT).payload()


def test_replay_refuses_a_format_with_points_or_unknown_before_any_path(wire: Path):  # noqa: F811
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--scoring", "points", "--h2h", "one_win"), "--h2h one_win: a points league's week"),
        (("--scoring", "points", "--h2h", "each_category"), "--h2h each_category: a points"),
        (("--h2h", "roto"), "--h2h roto: one of one_win, each_category"),
    ):
        code, out = replay(wire, *room, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out


# --------------------------------------------------------------------------- the standings
@pytest.mark.parametrize("h2h", FORMATS)
def test_the_two_formats_order_a_narrow_winner_and_a_wide_one_apart(h2h):
    result = lg.season(league(h2h), NARROW_AND_WIDE)
    order = [s.team for s in result.standings]
    assert order == ([1, 2, 3, 4] if h2h == ONE_WIN else [2, 1, 3, 4])
    rows = {s.team: (s.wins, s.losses, s.ties, s.category_wins) for s in result.standings}
    # The weeks' results and the category wins are kept in either format.
    assert rows[1] == (3, 0, 0, 15.0) and rows[2] == (2, 1, 0, 22.0)


def test_the_format_moves_the_rank_and_what_rests_on_it_and_nothing_else():
    one = lg.season(league(ONE_WIN), NARROW_AND_WIDE)
    each = lg.season(league(EACH_CATEGORY), NARROW_AND_WIDE)
    assert one.results == each.results
    strip = lambda s: (s.team, s.wins, s.losses, s.ties, s.category_wins, s.points_for)
    assert sorted(map(strip, one.standings)) == sorted(map(strip, each.standings))
    for team in (1, 2, 3, 4):
        a, b = lg.summary(one, team), lg.summary(each, team)
        assert set(a) == set(b)
        same = ("category_wins", "matchup_wins", "record")
        assert {k: a[k] for k in same} == {k: b[k] for k in same}
    assert (lg.summary(one, 1)["rank"], lg.summary(each, 1)["rank"]) == (1, 2)
    assert (lg.summary(one, 2)["rank"], lg.summary(each, 2)["rank"]) == (2, 1)


def test_every_category_breaks_a_tie_on_head_to_head_then_on_the_team_s_number():
    """Teams 1 and 2 take 14 of 27 categories each; team 2 won their meeting, so it ranks first
    though its number is the higher. When they tied the meeting (14.5 each), the number decides."""
    beat = season({1: [(1, 2, 4), (3, 4, 9)], 2: [(1, 3, 5), (2, 4, 5)], 3: [(1, 4, 5), (2, 3, 4)]})
    table = lg.standings(lg.season(league(EACH_CATEGORY), beat).results, league(EACH_CATEGORY))
    assert [s.team for s in table] == [3, 2, 1, 4]
    assert table[1].category_wins == table[2].category_wins == 14.0
    # A tied meeting (4 won, 4 lost, 1 tied each), the rest the same totals: the number decides.
    tied = season(
        {1: [(1, 2, 4, 1), (3, 4, 9)], 2: [(1, 3, 5), (2, 4, 5)], 3: [(1, 4, 5), (2, 3, 5)]}
    )
    table = lg.standings(lg.season(league(EACH_CATEGORY), tied).results, league(EACH_CATEGORY))
    assert table[1].category_wins == table[2].category_wins
    assert [s.team for s in table][1:3] == [1, 2]


def test_a_points_league_ignores_the_format_field():
    """A points league's week is one result: its standings read the win percentage whatever its
    spec's ``h2h`` holds."""
    pairs = {1: ((1, 2), (3, 4))}
    points = {"pts": 1.0}
    totals = {1: {1: {"pts": 10.0}, 2: {"pts": 9.0}, 3: {"pts": 30.0}, 4: {"pts": 1.0}}}
    for h2h in FORMATS:
        s = lg.LeagueSpec((1, 2, 3, 4), pairs, (2,), (), "points", points, 2, 0,
                          lg.TIEBREAK_POINTS, h2h=h2h)  # fmt: skip
        assert [x.team for x in lg.season(s, totals).standings] == [3, 1, 2, 4]


# --------------------------------------------------------------------------- the playoffs
@pytest.mark.parametrize("final", [(1, 2, 5), (1, 2, 4), (1, 2, 4, 1)])
def test_the_playoffs_are_the_same_bracket_play_in_both_formats(final):
    """One seeding and one week's totals give one bracket in either format: the side with more
    categories through, the higher seed through a tie (4 won, 4 lost, 1 tied)."""
    totals = season({1: [(1, 2, 5), (3, 4, 5)]}, final)
    seeds = {1: 1, 2: 2}
    one = lg.playoffs(seeds, totals, league(ONE_WIN))
    each = lg.playoffs(seeds, totals, league(EACH_CATEGORY))
    assert one == each
    assert one.champion == (2 if final == (1, 2, 4) else 1)


# --------------------------------------------------------------------------- the replay's league
@pytest.mark.parametrize("h2h", FORMATS)
def test_a_replay_s_league_carries_the_format_into_its_standings(h2h):
    _, setup = setup_of(h2h=h2h)
    assert setup.h2h == setup.spec.h2h == h2h
    assert setup.one_win == (h2h == ONE_WIN)
    assert setup.spec.tiebreak == (lg.TIEBREAK if h2h == ONE_WIN else lg.TIEBREAK_EACH)


def test_a_replay_s_points_league_names_no_format_and_refuses_one():
    _, points = setup_of(scoring="points", points=TABLE)
    assert points.h2h == ONE_WIN and not points.one_win
    assert points.spec.tiebreak == lg.TIEBREAK_POINTS
    with pytest.raises(ValueError, match="head-to-head format 'each_category' with scoring"):
        setup_of(scoring="points", points=TABLE, h2h=EACH_CATEGORY)


@pytest.mark.parametrize("h2h", FORMATS)
def test_the_league_block_names_the_format_and_every_category_says_how_it_ranks(h2h):
    rules = shapes.LeagueRules(h2h=h2h)
    block = ss.league_block(shapes.FIXED_GRID, [shapes.visit(0, shapes.FIXED_GRID)], [], rules)
    assert block["rules"]["h2h"] == h2h
    assert ("h2h_note" in block) == (h2h == EACH_CATEGORY)
    if h2h == EACH_CATEGORY:
        assert "category percentage" in block["h2h_note"] and "working default" in block["h2h_note"]
