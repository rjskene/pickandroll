"""The round's pairs (#172, PR bracket): one pure function of the league gives a bracket round's
matchups as team ids from the weeks finished before it, by the same calls the season's end
makes; the state holds them, a problem reads its week's opponent from them, and the audit holds
them day by day. The seasons that play them are ``test_sim_bracket_run.py``'s."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from pickandroll.sim import audit, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import league as lg
from pickandroll.sim.engine import mv
from pickandroll.sim.shapes import CONTINUOUS, DROPPED, WAIVERS
from pickandroll.sim.state import initial, round_robin
from tests.sim.sim_league import KNOBS, every_category, make_setup
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


# --------------------------------------------------------------------------- the state's pairs
def final_league(**kw):
    """Four teams, every one against every other over three weeks, then a final between the top
    two in week four."""
    return make_setup(teams=4, weeks=4, playoff_weeks=1, playoff_teams=2, **kw)


def test_a_round_is_seeded_once_from_the_states_own_totals_and_stays_out_of_the_key():
    setup = final_league()
    spec = setup.spec
    state = replace(initial(setup), totals=ranked(spec, (3, 1, 2, 4)))
    assert state.seeded == {}
    # A regular week seeds nothing.
    assert policy.seed_round(setup, state, 3) is state
    seeded = policy.seed_round(setup, state, 4)
    assert seeded.seeded == {4: ((3, 1),)} == {4: lg.round_pairs(spec, state.totals, 4)}
    # Once a round: pairs the state holds are not seeded again, whatever its totals become.
    later = replace(seeded, totals=ranked(spec, (4, 2, 1, 3)))
    assert policy.seed_round(setup, later, 4) is later
    # Another arm's own totals seed its own pairs.
    other = policy.seed_round(setup, replace(state, totals=later.totals), 4)
    assert other.seeded == {4: ((4, 2),)}
    # The pairs are no part of what two arms share a solve on.
    assert seeded.key() == state.key() == other.key()
    # A league whose bracket is not read has no round to seed.
    unread = final_league(bracket=False)
    assert policy.seed_round(unread, initial(unread), 4).seeded == {}


def test_a_teams_opponent_is_the_pairings_in_a_regular_week_and_the_rounds_pair_in_the_bracket():
    setup = final_league()
    state = initial(setup)
    for week in setup.spec.regular_weeks:
        for a, b in setup.pairings[week]:
            assert policy.opponent_of(setup, state, a, week) == b
            assert policy.opponent_of(setup, state, b, week) == a
    # The final before it is seeded (and gate 5's hand-built states): nobody reads an opponent.
    assert all(policy.opponent_of(setup, state, t, 4) is None for t in setup.teams)
    seeded = replace(state, seeded={4: ((3, 1),)})
    assert policy.opponent_of(setup, seeded, 3, 4) == 1
    assert policy.opponent_of(setup, seeded, 1, 4) == 3
    # A team in no pair (out of the field, on a bye, knocked out) reads none.
    assert policy.opponent_of(setup, seeded, 2, 4) is None
    assert policy.opponent_of(setup, seeded, 4, 4) is None
    # The pairings come first: the state's pairs are read only where they have no entry.
    odd = replace(state, seeded={1: ((1, 2),)})
    a, b = next(pair for pair in setup.pairings[1] if 1 in pair)
    assert policy.opponent_of(setup, odd, 1, 1) == (b if a == 1 else a) != 2


@pytest.mark.parametrize("format_", ["one_win", "each_category"])
def test_a_problem_in_a_round_weighs_the_week_against_the_rounds_opponent(format_):
    """The final's Wednesday, in each head-to-head format. Without the pair the week has no
    opponent and is worth nothing (main's blind week); with it the week's span is the one a
    regular week against that team would have been, the opponent's week so far included, and it
    is worth something. The later weeks, the measure and a team out of the final do not change."""
    setup = final_league() if format_ == "one_win" else every_category(final_league())
    day = setup.calendar.weeks[-1].start + timedelta(2)
    so_far = {4: {1: totals(40.0), 3: totals(50.0)}}
    base = replace(initial(setup), day=day, totals=so_far)
    seeded = replace(base, seeded={4: ((3, 1),)})

    def problem(state, team=1, league=setup):
        return policy.problem_of(league, state, team, KNOBS, setup.projection, {}, {}).problem

    blind, mine = problem(base), problem(seeded)
    (none,) = blind.horizons["week"]
    assert none.opponents == () and none.so_far_theirs == ()
    assert mv.Evaluator(blind).base["week"] == 0.0
    (span,) = mine.horizons["week"]
    assert len(span.opponents) == 1
    assert span.so_far == totals(40.0) and span.so_far_theirs == (totals(50.0),)
    assert mv.Evaluator(mine).base["week"] > 0.0
    # The very span a regular week paired with team 3 gives: one rule for the week's opponent.
    paired = replace(setup, pairings={**setup.pairings, 4: ((1, 3), (2, 4))})
    assert span == problem(base, league=paired).horizons["week"][0]
    assert mine.horizons["three"] == blind.horizons["three"]
    assert mine.one_win == blind.one_win == setup.one_win
    assert mv.measure_of(mine) == policy.measure_of(setup)
    # The other finalist reads team 1; a team out of the final reads nobody and has its problem.
    (theirs,) = problem(seeded, 3).horizons["week"]
    assert theirs.so_far == totals(50.0) and theirs.so_far_theirs == (totals(40.0),)
    assert problem(seeded, 2).horizons["week"][0].opponents == ()
    assert problem(seeded, 2) == problem(base, 2)


# --------------------------------------------------------------------------- the audit
def found(setup, state, day) -> list:
    """What the rule finds on ``state`` read on ``day``."""
    return list(
        audit.bracket_pairs(setup, audit.Day(day, 0, replace(state, day=day), {}, {}), None)
    )


def test_the_audit_holds_a_rounds_pairs_to_the_leagues_on_every_day_of_the_round():
    setup = final_league()
    final = setup.calendar.weeks[-1]
    season = ranked(setup.spec, (3, 1, 2, 4))
    honest = policy.seed_round(setup, replace(initial(setup), totals=season), 4)
    assert honest.seeded == {4: ((3, 1),)}
    for day in final.days():
        assert found(setup, honest, day) == []
    # Later in the round, with the week's own totals in: the pairs do not read them.
    played = {**season, 4: {1: totals(10.0), 2: totals(500.0), 3: totals(99.0)}}
    assert found(setup, replace(honest, totals=played), final.end) == []
    # A round the state does not hold.
    assert found(setup, replace(honest, seeded={}), final.start) == [
        (None, "week 4 is a round of the bracket and the state holds no pairs for it")
    ]
    # Pairs that are not the league's: another team, or the same teams the lower seed first.
    assert found(setup, replace(honest, seeded={4: ((3, 2),)}), final.start) == [
        (None, "week 4's pairs ((3, 2),), the league gives ((3, 1),)")
    ]
    assert found(setup, replace(honest, seeded={4: ((1, 3),)}), final.start) == [
        (None, "week 4's pairs ((1, 3),), the league gives ((3, 1),)")
    ]
    # Totals of a finished week that changed after the round was seeded: the pairs are stale.
    moved = replace(honest, totals=ranked(setup.spec, (4, 2, 1, 3)))
    assert found(setup, moved, final.start) == [
        (None, "week 4's pairs ((3, 1),), the league gives ((4, 2),)")
    ]
    # A regular day reads nothing, whatever the state holds; nor does a league not read.
    assert found(setup, replace(honest, seeded={}), setup.start) == []
    assert found(final_league(bracket=False), replace(honest, seeded={}), final.start) == []


def test_the_audit_catches_a_team_in_two_pairs():
    setup = make_setup(teams=4, weeks=5, playoff_weeks=2, playoff_teams=4)
    one, _ = setup.spec.playoff_weeks
    day = setup.calendar.weeks[one - 1].start
    season = ranked(setup.spec, (1, 2, 3, 4))
    honest = policy.seed_round(setup, replace(initial(setup), totals=season), one)
    assert honest.seeded == {one: ((1, 4), (2, 3))} and found(setup, honest, day) == []
    twice = replace(honest, seeded={one: ((1, 4), (2, 1))})
    assert found(setup, twice, day) == [
        (None, f"week {one}'s pairs ((1, 4), (2, 1)), the league gives ((1, 4), (2, 3))"),
        (1, f"team 1 is in 2 pairs of week {one}"),
    ]


def test_the_rule_is_read_in_every_league_with_a_round_and_in_no_other():
    rule = audit.BRACKET_PAIRS
    assert rule.name == "bracket_pairs" and rule.check is audit.bracket_pairs
    assert rule not in audit.RULES
    for waivers in WAIVERS:
        for way in (DROPPED,) if waivers == "none" else (DROPPED, CONTINUOUS):
            plain = audit.rules_of(waivers, way)
            assert rule not in plain and plain == audit.rules_of(waivers, way, False)
            read = audit.rules_of(waivers, way, bracket=True)
            # After the six every run reads, before a waiver league's own: the rest as it was.
            assert read[len(audit.RULES)] is rule
            assert tuple(r for r in read if r is not rule) == plain
    setup = final_league()
    assert audit.has_round(setup)
    assert audit.Auditor(setup).rules == audit.rules_of(bracket=True) == (*audit.RULES, rule)
    faab = replace(setup, waivers="faab")
    assert audit.Auditor(faab).rules == audit.rules_of("faab", bracket=True)
    # No round: the bracket not read, one playoff team, or no playoff week.
    for none in (
        final_league(bracket=False),
        replace(setup, spec=replace(setup.spec, playoff_teams=1)),
        replace(setup, spec=replace(setup.spec, playoff_weeks=())),
    ):
        assert not audit.has_round(none) and audit.Auditor(none).rules == audit.RULES
    assert {"name": "bracket_pairs", "holds": rule.holds} in audit.names(audit.Auditor(setup).rules)


def test_a_replays_record_names_the_rule_under_every_kind_of_waivers():
    """The commands' audit block (``cli.audit_rules``): every league shape of the ruled grid has a
    round, so every replay's record names the rule, after the six and before its waivers'."""
    six = [r.name for r in audit.RULES]
    for grid in (shapes.FIXED_GRID, shapes.FULL):
        assert all(s.playoff_teams > 1 and s.playoff_weeks > 0 for s in grid.shapes)
        plain = ss.audit_rules(shapes.PLAIN, grid)
        assert [r.name for r in plain] == [*six, "bracket_pairs"]
        _, note = ss.audited([{"path": 0}], [{"breaches": []}], plain)
        assert [r["name"] for r in note["rules"]] == [*six, "bracket_pairs"]
        for waivers in ("priority", "faab"):
            for way in (DROPPED, CONTINUOUS):
                rules = shapes.LeagueRules(waivers=waivers, waiver_rule=way)
                assert ss.audit_rules(rules, grid) == audit.rules_of(waivers, way, bracket=True)
    # A grid whose one shape plays no round names none.
    bare = shapes.one("bare", replace(shapes.FIXED, playoff_teams=1, playoff_weeks=0))
    assert ss.audit_rules(shapes.PLAIN, bare) == audit.RULES


def test_the_replay_s_reason_says_the_bracket():
    """The version's reason names what a reader of an older record must know: a round's
    opponent is read, by whom it changes a season, that the view a decision is keyed on holds
    the round's pair, the audit's rule, and whose season is the version before's."""
    why = ss.REPLAY_VERSION_WHY
    assert ss.REPLAY_VERSION >= 19 and "19: the bracket's rounds: " in why
    mine = why.split("19: the bracket's rounds: ")[1].split("18: the bid policy: ")[0]
    for said in (
        "round's opponent",
        "the weighted set",
        "week's plan",
        "the queue's rule",
        "a bid that weighs the week",
        "holds the round's pair",
        "bracket_pairs",
    ):
        assert said in mine, said
    assert "names no bid on the week plays version 18's season" in mine
