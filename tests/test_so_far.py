"""A player's week so far as Yahoo counts it (#304): the matchup page's row, its makes, attempts
and games placed from his box scores when exactly one set of his games adds up to it.

Made-up lines throughout; nothing here is from Basketball Monster.
"""

from __future__ import annotations

import pytest

from pickandroll.season import so_far as sf


def game(pts=10, threes=1, reb=5, ast=3, stl=1, blk=0, tov=2, fgm=4, fga=9, ftm=1, fta=2):
    return {
        "pts": pts,
        "threes": threes,
        "reb": reb,
        "ast": ast,
        "stl": stl,
        "blk": blk,
        "tov": tov,
        "fgm": fgm,
        "fga": fga,
        "ftm": ftm,
        "fta": fta,
    }


def row(games, fg=None, ft=None):
    """The page's row for ``games``: summed counting columns, percentages to three places."""
    total = {k: sum(g[k] for g in games) for k in games[0]}
    out = {
        "3PTM": str(total["threes"]),
        "PTS": str(total["pts"]),
        "REB": str(total["reb"]),
        "AST": str(total["ast"]),
        "ST": str(total["stl"]),
        "BLK": str(total["blk"]),
        "TO": str(total["tov"]),
    }
    out["FG%"] = fg or (f"{total['fgm'] / total['fga']:.3f}".lstrip("0") if total["fga"] else "-")
    out["FT%"] = ft or (f"{total['ftm'] / total['fta']:.3f}".lstrip("0") if total["fta"] else "-")
    return out


A = game()
B = game(pts=22, threes=3, reb=7, ast=6, stl=2, blk=1, tov=4, fgm=8, fga=15, ftm=3, fta=4)
C = game(pts=6, threes=0, reb=2, ast=1, stl=0, blk=0, tov=1, fgm=3, fga=7, ftm=0, fta=0)


def test_the_one_set_of_games_that_adds_up_places_his_makes_attempts_and_games():
    # He played three games, and sat on the bench for the second.
    so = sf.so_far(row([A, C]), [A, B, C])
    assert so.matched and so.games == 2
    assert (so.line["fgm"], so.line["fga"], so.line["ftm"], so.line["fta"]) == (7, 16, 1, 2)
    assert so.line["fg_pct"] == pytest.approx(7 / 16)
    assert so.line["pts"] == 16
    assert so.to_dict()["why"] is None


def test_two_sets_that_add_up_leave_his_line_as_yahoo_printed_it():
    twin = dict(A)
    so = sf.so_far(row([A]), [A, twin, B])
    assert not so.matched and so.why == sf.ambiguous(2) and so.games is None
    assert so.line["pts"] == 10 and so.line["fg_pct"] == pytest.approx(0.444)
    assert so.line["fgm"] is None and so.line["fga"] is None


def test_no_set_that_adds_up_and_no_box_scores_say_why():
    # A game the box scores do not hold (a day not cached yet) was counted.
    so = sf.so_far(row([A, B]), [A, C])
    assert (so.why, so.games, so.line["fta"]) == (sf.NONE_ADDS_UP, None, None)
    assert so.line["reb"] == 12
    assert sf.so_far(row([A]), None).why == sf.NO_BOX


def test_the_percentages_must_round_to_yahoos_not_only_the_counting_stats():
    # The same counting stats, other makes: only the set whose makes round to Yahoo's fits.
    other = {**A, "fgm": 5, "fga": 9}
    so = sf.so_far(row([A]), [other, A])
    assert so.matched and (so.line["fgm"], so.line["fga"]) == (4, 9)
    # A percentage Yahoo prints as ``-`` means no attempts.
    none = {**C, "ftm": 0, "fta": 0}
    assert sf.so_far(row([none]), [none]).matched
    assert sf.so_far(row([none], ft=".500"), [none]).why == sf.NONE_ADDS_UP


def test_no_game_counted_is_certain_without_the_box_scores():
    dashes = dict.fromkeys(["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"], "-")
    so = sf.so_far(dashes, None)
    assert so.matched and so.games == 0 and so.line["pts"] == 0 and so.line["fg_pct"] is None


def test_a_points_league_keeps_yahoos_fantasy_points_and_matches_its_columns():
    page = {
        "Fan Pts": "41.50",
        "PTS": "32",
        "REB": "12",
        "AST": "9",
        "BLK": "1",
        "ST": "3",
        "TO": "6",
    }
    so = sf.so_far(page, [A, B], points={"pts": 1.0, "reb": 1.2})
    assert so.matched and so.games == 2 and so.line["fpts"] == 41.5
    assert so.line["threes"] == 4  # from the box scores: the page has no 3PTM column
    fallback = sf.so_far(page, None, points={"pts": 1.0})
    assert fallback.line["fpts"] == 41.5 and fallback.line["threes"] is None


def test_more_games_than_a_week_has_are_not_searched():
    assert sf.so_far(row([A]), [A] * 8).why == sf.TOO_MANY
