"""The round's pairs (#172, PR bracket): one pure function of the league gives a bracket round's
matchups as team ids from the weeks finished before it, by the same calls the season's end
makes; the state holds them, a problem reads its week's opponent from them, and the audit holds
them day by day. The seasons that play them are ``test_sim_bracket_run.py``'s."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pickandroll.sim import league as lg
from pickandroll.sim.state import round_robin
from tests.sim.test_sim_league import CATS, totals

#: The playoff formats of the ruled grid (``shapes.FULL.playoffs``), each with a league's teams:
#: four of six over two weeks, six of eight over three (two byes), eight of ten over three.
FORMATS = {"4/2": (6, 4, 2), "6/3": (8, 6, 3), "8/3": (10, 8, 3)}


def league(fmt: str = "4/2", **kw) -> lg.LeagueSpec:
    """A league of the playoff format ``fmt``: every team against every other once (so a team
    that outscores another every week finishes above it), then the bracket's weeks, the byes the
    rounds need."""
    n, playoff_teams, rounds = FORMATS[fmt]
    ids = tuple(range(1, n + 1))
    weeks = tuple(range(n, n + rounds))
    byes = 2**rounds - playoff_teams
    pairings = round_robin(ids, range(1, n))
    return lg.LeagueSpec(ids, pairings, weeks, CATS, playoff_teams=playoff_teams, byes=byes, **kw)


def ranked(spec: lg.LeagueSpec, best_first: tuple[int, ...]) -> dict[int, dict[int, dict]]:
    """Regular weeks after which the teams stand in the order ``best_first``: each outscores
    everyone after it in points every week, every other category level."""
    pts = {t: 200.0 - 10.0 * i for i, t in enumerate(best_first)}
    return {w: {t: totals(pts[t]) for t in spec.teams} for w in spec.regular_weeks}


def won_by(spec: lg.LeagueSpec, winners: tuple[int, ...]) -> dict[int, dict]:
    """A bracket week's totals in which each team of ``winners`` outscores every other team."""
    return {t: totals(150.0 if t in winners else 50.0) for t in spec.teams}


def drawn(spec: lg.LeagueSpec, seed: int) -> dict[int, dict[int, dict[str, float]]]:
    """Every week's totals of a season, regular and bracket, drawn in whole numbers (no two
    machines round a whole number apart)."""
    g = np.random.default_rng([41, seed])
    out: dict[int, dict[int, dict[str, float]]] = {}
    for week in (*spec.regular_weeks, *spec.playoff_weeks):
        out[week] = {}
        for t in spec.teams:
            fga, fta = float(g.integers(150, 250)), float(g.integers(60, 120))
            out[week][t] = {
                "pts": float(g.integers(300, 500)),
                "reb": float(g.integers(100, 200)),
                "ast": float(g.integers(60, 140)),
                "stl": float(g.integers(15, 40)),
                "blk": float(g.integers(10, 30)),
                "tov": float(g.integers(30, 70)),
                "threes": float(g.integers(20, 60)),
                "fgm": float(g.integers(60, 140)),
                "fga": fga,
                "ftm": float(g.integers(30, 60)),
                "fta": fta,
            }
    return out


def end_pairs(spec: lg.LeagueSpec, season: dict) -> list[tuple[tuple[int, int], ...]]:
    """Each round's pairs as the season's end played them, as team ids."""
    post = lg.season(spec, season).playoffs
    return [tuple((post.seeds[hi], post.seeds[lo]) for hi, lo, _ in rnd) for rnd in post.rounds]


# --------------------------------------------------------------------------- the pure function
def test_the_rounds_weeks_are_the_first_playoff_weeks_one_a_round():
    assert lg.round_weeks(league("4/2")) == (6, 7)
    assert lg.round_weeks(league("6/3")) == (8, 9, 10)
    assert lg.round_weeks(league("8/3")) == (10, 11, 12)
    # More playoff weeks than rounds: the weeks past the last round are no round's.
    final = replace(league("4/2"), playoff_teams=2, byes=0)
    assert final.rounds == 1 and lg.round_weeks(final) == (6,)
    # No bracket: no playoff team, one (no round to play), or no playoff week.
    for none in (
        replace(league(), playoff_teams=0),
        replace(league(), playoff_teams=1),
        replace(league(), playoff_weeks=()),
    ):
        assert lg.round_weeks(none) == ()


def test_four_teams_over_two_weeks_seeded_from_the_standings_as_team_ids():
    s = league("4/2")
    one, two = s.playoff_weeks
    # The seeds are not the team ids: team 6 finishes first, then 5, 4, 3; 2 and 1 are out.
    season = ranked(s, (6, 5, 4, 3, 2, 1))
    assert lg.round_pairs(s, season, one) == ((6, 3), (5, 4))
    # Round two on its first morning: seed 4 upset seed 1, seed 2 beat seed 3.
    season[one] = won_by(s, (3, 5))
    assert lg.round_pairs(s, season, two) == ((5, 3),)
    # The favourites through: the final is seed 1 against seed 2, the higher seed first.
    season[one] = won_by(s, (6, 5))
    assert lg.round_pairs(s, season, two) == ((6, 5),)


def test_six_teams_over_three_weeks_the_byes_sit_out_and_the_rounds_reseed_or_not():
    s = league("6/3")
    fixed = replace(s, reseed=False)
    one, two, three = s.playoff_weeks
    season = ranked(s, (1, 2, 3, 4, 5, 6, 7, 8))
    first = lg.round_pairs(s, season, one)
    assert first == ((3, 6), (4, 5)) == lg.round_pairs(fixed, season, one)
    assert not {1, 2, 7, 8} & {t for pair in first for t in pair}  # on a bye, or out
    # Seeds 6 and 5 upset 3 and 4. Reseeded, the best left meets the worst left; the fixed
    # bracket keeps its slots: 1 meets the winner of 4-5, 2 the winner of 3-6.
    season[one] = won_by(s, (6, 5))
    assert lg.round_pairs(s, season, two) == ((1, 6), (2, 5))
    assert lg.round_pairs(fixed, season, two) == ((1, 5), (2, 6))
    # Seed 6 goes on past seed 1, seed 2 holds: the final either way.
    season[two] = won_by(s, (6, 2))
    assert lg.round_pairs(s, season, three) == ((2, 6),)
    season[two] = won_by(s, (5, 2))
    assert lg.round_pairs(fixed, season, three) == ((2, 5),)


def test_eight_teams_over_three_weeks_in_the_order_the_bracket_lists_them():
    s = league("8/3")
    one, two, _ = s.playoff_weeks
    season = ranked(s, (10, 9, 8, 7, 6, 5, 4, 3, 2, 1))
    assert lg.round_pairs(s, season, one) == ((10, 3), (9, 4), (8, 5), (7, 6))
    season[one] = won_by(s, (3, 9, 8, 6))
    assert lg.round_pairs(s, season, two) == ((9, 3), (8, 6))
    assert lg.round_pairs(replace(s, reseed=False), season, two) == ((9, 8), (6, 3))


def test_a_tie_in_a_round_sends_the_higher_seed_to_the_next_rounds_pairs():
    s = league("4/2")
    one, two = s.playoff_weeks
    season = ranked(s, (1, 2, 3, 4, 5, 6))
    # Round one level on every category in both matchups: seeds 1 and 2 go through.
    season[one] = {t: totals(100.0) for t in s.teams}
    assert lg.round_pairs(s, season, two) == ((1, 2),)
    # A round whose week has no totals is read the same way (level, the higher seed through).
    del season[one]
    assert lg.round_pairs(s, season, two) == ((1, 2),)


def test_no_pairs_in_a_week_that_is_no_rounds_and_in_a_league_with_no_bracket():
    s = league("4/2")
    one, two = s.playoff_weeks
    season = ranked(s, (1, 2, 3, 4, 5, 6))
    for week in (0, *s.regular_weeks, two + 1, 99):
        assert lg.round_pairs(s, season, week) == ()
    # Two playoff teams over two playoff weeks: the final is the first, the second no round's.
    final = replace(s, playoff_teams=2, byes=0)
    assert lg.round_pairs(final, season, one) == ((1, 2),)
    assert lg.round_pairs(final, season, two) == ()
    for none in (
        replace(s, playoff_teams=0),
        replace(s, playoff_teams=1),
        replace(s, playoff_weeks=()),
    ):
        for week in (one - 1, one, two):
            assert lg.round_pairs(none, season, week) == ()


def test_a_spec_the_bracket_cannot_play_raises_on_a_rounds_morning_as_the_seasons_end_does():
    s = league("6/3")
    one, two, _ = s.playoff_weeks
    season = ranked(s, (1, 2, 3, 4, 5, 6, 7, 8))
    odd = replace(s, byes=1)
    short = replace(s, playoff_weeks=(one, two))
    coin = replace(s, playoff_tiebreak="coin")
    for bad, words in ((odd, "is not a bracket"), (short, "need 3 weeks"), (coin, "not played")):
        with pytest.raises(ValueError, match=words):
            lg.season(bad, season)
        with pytest.raises(ValueError, match=words):
            lg.round_pairs(bad, season, one)
        # A regular week asks the bracket nothing.
        assert lg.round_pairs(bad, season, one - 1) == ()


CASES = [(fmt, reseed) for fmt in FORMATS for reseed in (True, False)]


@pytest.mark.parametrize(("fmt", "reseed"), CASES)
def test_each_round_on_its_first_morning_is_the_round_the_seasons_end_plays(fmt, reseed):
    """Random totals over several seasons: a round's pairs from the weeks finished before it
    (its own week and the later ones not yet in the totals) are the pairs the bracket plays at
    the season's end, by team; and the seasons between them seed more than one bracket."""
    s = replace(league(fmt), reseed=reseed)
    seen = set()
    for seed in range(12):
        season = drawn(s, seed)
        end = end_pairs(s, season)
        assert len(end) == s.rounds == len(lg.round_weeks(s))
        for i, week in enumerate(lg.round_weeks(s)):
            morning = {w: t for w, t in season.items() if w < week}
            assert lg.round_pairs(s, morning, week) == end[i], (seed, week)
        seen.add(tuple(end))
    assert len(seen) > 1


@pytest.mark.parametrize(("fmt", "reseed"), CASES)
def test_no_peek_a_rounds_pairs_do_not_read_its_own_week_or_a_later_one(fmt, reseed):
    """Changing the totals of round ``r``'s week and of every later week leaves round ``r``'s
    pairs as they were; changing an earlier week can move them (or the test shows nothing)."""
    s = replace(league(fmt), reseed=reseed)
    moved = 0
    for seed in range(12):
        season, other = drawn(s, seed), drawn(s, 100 + seed)
        for week in lg.round_weeks(s):
            pairs = lg.round_pairs(s, season, week)
            after = {w: (season[w] if w < week else other[w]) for w in season}
            assert lg.round_pairs(s, after, week) == pairs, (seed, week)
            before = {w: (other[w] if w < week else season[w]) for w in season}
            moved += lg.round_pairs(s, before, week) != pairs
    assert moved > 0


def test_the_pairs_name_no_winner_and_no_team_twice():
    s = league("8/3")
    for seed in range(6):
        season = drawn(s, seed)
        for week in lg.round_weeks(s):
            pairs = lg.round_pairs(s, season, week)
            assert all(len(pair) == 2 for pair in pairs)
            teams = [t for pair in pairs for t in pair]
            assert len(teams) == len(set(teams)) and set(teams) <= set(s.teams)
