"""The simulated league (#172, PR 1): weeks scored as the record scores them, standings with
the tiebreak, the bracket with byes, a season's outcomes."""

from __future__ import annotations

import pytest

from pickandroll.season.sim import league as lg
from pickandroll.season.state import SeasonSettings

CATS = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")


def spec(teams=4, weeks=3, playoff_teams=2, byes=0, playoff_weeks=(4,), **kw):
    ids = tuple(range(1, teams + 1))
    rounds = {
        1: ((1, 4), (2, 3)),
        2: ((1, 3), (4, 2)),
        3: ((1, 2), (3, 4)),
    }
    if teams == 4:
        pairings = {wk: rounds[(wk - 1) % 3 + 1] for wk in range(1, weeks + 1)}
    else:
        pairings = {
            wk: tuple((ids[i], ids[-1 - i]) for i in range(len(ids) // 2))
            for wk in range(1, weeks + 1)
        }
    return lg.LeagueSpec(
        ids, pairings, playoff_weeks, CATS, playoff_teams=playoff_teams, byes=byes, **kw
    )


def totals(pts, reb=10.0, tov=5.0, fgm=10.0, fga=20.0, ftm=5.0, fta=10.0, threes=3.0):
    return {
        "pts": pts,
        "reb": reb,
        "ast": 10.0,
        "stl": 3.0,
        "blk": 2.0,
        "tov": tov,
        "threes": threes,
        "fgm": fgm,
        "fga": fga,
        "ftm": ftm,
        "fta": fta,
    }


def test_a_week_is_scored_as_the_record_scores_it():
    s = spec()
    mine = totals(100.0, tov=4.0, fgm=10.0, fga=20.0)
    theirs = totals(90.0, tov=5.0, fgm=5.0, fga=10.0)
    r = lg.week_result(mine, theirs, s)
    assert r.cats["fg_pct"] == 0.5  # 0.500 against 0.500
    assert r.cats["tov"] == 1.0  # lower turnovers win
    assert r.cats["pts"] == 1.0
    assert r.cats["ast"] == 0.5
    assert r.outcome == "W"
    assert r.category_wins == r.won + 0.5 * r.tied
    # A three-decimal percentage difference counts.
    close = lg.week_result(
        totals(90.0, fgm=100.0, fga=199.0), totals(90.0, fgm=100.0, fga=200.0), s
    )
    assert close.cats["fg_pct"] == 1.0


def test_a_points_league_scores_on_the_points():
    s = spec(scoring="points", points={"pts": 1.0, "reb": 1.2, "tov": -1.0})
    r = lg.week_result(totals(100.0), totals(99.0), s)
    assert (r.won, r.lost, r.tied) == (1.0, 0.0, 0.0)
    assert r.cats == {"fpts": 1.0}
    t = lg.week_result(totals(100.0), totals(100.0), s)
    assert t.outcome == "T"


def test_standings_break_ties_by_category_wins_then_head_to_head():
    s = spec(teams=4, weeks=3)
    # Week 1: 1v4, 2v3; week 2: 1v3, 4v2; week 3: 1v2, 3v4 (the rotation).
    assert s.pairings[1] == ((1, 4), (2, 3))
    assert s.pairings[3] == ((1, 2), (3, 4))
    t = {
        1: {1: totals(100.0), 2: totals(100.0), 3: totals(60.0)},
        2: {1: totals(100.0), 2: totals(100.0), 3: totals(100.0)},
        3: {1: totals(60.0), 2: totals(100.0), 3: totals(60.0)},
        4: {1: totals(60.0), 2: totals(60.0), 3: totals(60.0)},
    }
    result = lg.season(s, {wk: {team: t[team][wk] for team in t} for wk in (1, 2, 3)})
    ranks = {st.team: st.rank for st in result.standings}
    # Team 2 beats 1 head to head in week 3 with the same record otherwise.
    assert ranks[2] == 1 and ranks[1] == 2
    assert ranks[4] == 4
    assert result.outcomes[2].made_playoffs and result.outcomes[1].made_playoffs
    assert not result.outcomes[3].made_playoffs


def test_bracket_pairs_best_against_worst_after_the_byes():
    assert lg.bracket(list(range(1, 7)), 6, 2) == [(3, 6), (4, 5)]
    assert lg.bracket(list(range(1, 5)), 4, 0) == [(1, 4), (2, 3)]
    with pytest.raises(ValueError):
        lg.bracket(list(range(1, 7)), 6, 1)


def test_playoffs_reseed_and_a_tie_sends_the_higher_seed_through():
    s = spec(teams=6, weeks=1, playoff_teams=6, byes=2, playoff_weeks=(20, 21, 22))
    seeds = {i: i * 10 for i in range(1, 7)}  # seed -> team id
    week = {
        20: {30: totals(60.0), 60: totals(100.0), 40: totals(100.0), 50: totals(60.0)},
        21: {10: totals(60.0), 60: totals(100.0), 20: totals(100.0), 40: totals(60.0)},
        22: {60: totals(100.0), 20: totals(100.0)},
    }
    p = lg.playoffs(seeds, week, s)
    assert p.rounds[0] == ((3, 6, 6), (4, 5, 4))
    assert p.rounds[1] == ((1, 6, 6), (2, 4, 2))
    # The final is a tie on every category: the higher seed, 2, takes the title.
    assert p.rounds[2] == ((2, 6, 2),)
    assert p.champion == 20
    with pytest.raises(ValueError):
        lg.playoffs(
            seeds, week, spec(teams=6, weeks=1, playoff_teams=6, byes=2, playoff_weeks=(20,))
        )


def test_a_season_end_to_end_with_a_summary():
    s = spec(teams=4, weeks=3, playoff_teams=2, byes=0, playoff_weeks=(4,))
    t = {
        wk: {1: totals(100.0), 2: totals(90.0), 3: totals(80.0), 4: totals(70.0)}
        for wk in (1, 2, 3, 4)
    }
    result = lg.season(s, t)
    o = result.outcomes[1]
    assert o.rank == 1 and o.made_playoffs and o.title
    assert o.record == (3, 0, 0)
    assert o.matchup_wins == 3.0
    assert result.playoffs.champion == 1
    assert lg.summary(result, 4) == {
        "rank": 4,
        "made_playoffs": False,
        "title": False,
        "category_wins": result.outcomes[4].category_wins,
        "matchup_wins": 0.0,
        "record": [0, 3, 0],
    }


# --------------------------------------------------------------------------- from the settings
def settings(**kw):
    """A league's settings as read, the bracket's rows included unless ``kw`` unsets them."""
    base = {
        "league": "1",
        "scoring": "categories",
        "cats": tuple(CATS),
        "roster": ("PG", "SG", "C", "Util", "BN"),
        "num_teams": 6,
        "my_team_id": 1,
        "playoff_teams": 6,
        "playoff_weeks": (20, 21, 22),
        "playoff_tiebreak": "Higher seed wins",
        "playoff_reseeding": True,
        "divisions": False,
    }
    return SeasonSettings(**{**base, **kw})


def test_the_spec_is_built_from_the_settings_page_once_the_bracket_rows_are_read():
    pairings = {1: ((1, 2), (3, 4), (5, 6))}
    s = lg.LeagueSpec.from_settings(settings(), [1, 2, 3, 4, 5, 6], pairings)
    assert s.teams == (1, 2, 3, 4, 5, 6) and s.pairings == {1: ((1, 2), (3, 4), (5, 6))}
    assert (s.playoff_teams, s.byes, s.playoff_weeks) == (6, 2, (20, 21, 22))
    assert s.reseed is True and s.playoff_tiebreak == "higher_seed"
    assert s.cats == tuple(CATS) and s.scoring == "categories" and s.points is None
    # Four teams in two weeks: no byes; no reseeding plays the fixed bracket.
    four = lg.LeagueSpec.from_settings(
        settings(playoff_teams=4, playoff_weeks=(21, 22), playoff_reseeding=False), [1, 2, 3, 4], {}
    )
    assert (four.byes, four.reseed) == (0, False)


def test_no_spec_before_the_settings_page_is_read_for_the_bracket():
    teams, pairings = [1, 2, 3, 4, 5, 6], {}
    with pytest.raises(lg.BracketUnread, match="playoff_tiebreak, playoff_reseeding, divisions"):
        lg.LeagueSpec.from_settings(
            settings(playoff_tiebreak=None, playoff_reseeding=None, divisions=None), teams, pairings
        )
    with pytest.raises(lg.BracketUnread, match="playoff_reseeding"):
        lg.LeagueSpec.from_settings(settings(playoff_reseeding=None), teams, pairings)
    with pytest.raises(lg.BracketUnread, match="divisions"):
        lg.LeagueSpec.from_settings(settings(divisions=True), teams, pairings)
    with pytest.raises(lg.BracketUnread, match="not played"):
        lg.LeagueSpec.from_settings(settings(playoff_tiebreak="Bench points"), teams, pairings)
    with pytest.raises(lg.BracketUnread, match="need 3 weeks"):
        lg.LeagueSpec.from_settings(settings(playoff_weeks=(21, 22)), teams, pairings)
    with pytest.raises(lg.BracketUnread, match="playoff teams"):
        lg.LeagueSpec.from_settings(settings(playoff_teams=None), teams, pairings)


def test_the_fixed_bracket_keeps_its_slots_when_the_league_does_not_reseed():
    assert lg.bracket_order(3) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert lg.bracket_order(2) == [1, 4, 2, 3]
    seeds = {i: 10 + i for i in range(1, 7)}
    # Seeds 6 and 5 upset 3 and 4 in the first round.
    week = {
        20: {13: totals(90.0), 16: totals(100.0), 14: totals(90.0), 15: totals(100.0)},
        # Fixed bracket: 1 meets the winner of 4-5 (seed 5), 2 meets the winner of 3-6 (seed 6).
        # Seed 5 beats seed 1; seed 2 beats seed 6.
        21: {11: totals(90.0), 15: totals(100.0), 12: totals(100.0), 16: totals(90.0)},
        22: {12: totals(100.0), 15: totals(90.0)},
    }
    fixed = spec(
        teams=6, weeks=1, playoff_teams=6, byes=2, playoff_weeks=(20, 21, 22), reseed=False
    )
    p = lg.playoffs(seeds, week, fixed)
    assert p.rounds[0] == ((3, 6, 6), (4, 5, 5))
    assert p.rounds[1] == ((1, 5, 5), (2, 6, 2))
    assert p.rounds[2] == ((2, 5, 2),) and p.champion == 12
    # Reseeded, the same upsets send 1 against 6 (the worst left) and 2 against 5; both ties
    # go to the higher seed.
    reseeded = spec(teams=6, weeks=1, playoff_teams=6, byes=2, playoff_weeks=(20, 21, 22))
    assert lg.playoffs(seeds, week, reseeded).rounds[1] == ((1, 6, 1), (2, 5, 2))


def test_a_spec_with_a_tie_breaker_the_bracket_does_not_play_is_refused():
    s = spec(
        teams=4, weeks=1, playoff_teams=4, byes=0, playoff_weeks=(4, 5), playoff_tiebreak="coin"
    )
    with pytest.raises(ValueError, match="not played"):
        lg.playoffs({1: 1, 2: 2, 3: 3, 4: 4}, {}, s)
