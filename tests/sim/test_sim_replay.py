"""A replay's league and what its seats hear (#172, PR B1): everyone the log lists is in the
league, the draft takes the projected players an opening-week roster shows, a player nobody
projected is believed once he has played, the told return date's spread is a parameter, and the
hold-out gate's inputs are the ones it had before."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from pickandroll.sim import cli, policy, world
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.belief import newcomer_prior, shrunk
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.state import Member, initial, snake_draft
from tests.sim.sim_league import KNOBS, inputs, make_data_dir

FIRST = date(2024, 10, 22)
SLOTS = ("PG", "C", "Util", "BN")


def line(level: float) -> dict[str, float]:
    return {
        "pts": 10 * level,
        "reb": 5 * level,
        "ast": 3 * level,
        "fgm": 4.0,
        "fga": 8.0,
        "ftm": 2.0,
        "fta": 2.5,
        "threes": 1.0,
        "stl": 1.0,
        "blk": 1.0,
        "tov": 2.0,
    }


def season():
    """Thirty regulars from opening night, the first ten missing three games in mid-season; 31,
    projected best of all, whose first game is on day eleven; 32, projected, who plays once; 33,
    whom nobody projected, first seen on day six; 34, listed with no game."""
    players = {k: Member(k, f"P{k}", "x", ("PG",) if k % 2 else ("C",)) for k in range(1, 35)}
    scheduled = {k: [FIRST + timedelta(2 * i + k % 2) for i in range(25)] for k in range(1, 31)}
    lines = {
        k: {d: line(0.5 + k / 30) for i, d in enumerate(days) if k > 10 or i not in (5, 6, 7)}
        for k, days in scheduled.items()
    }
    lines[31] = {FIRST + timedelta(10 + 2 * i): line(3.0) for i in range(20)}
    lines[32] = {FIRST + timedelta(1): line(2.5)}
    lines[33] = {FIRST + timedelta(5 + 2 * i): line(2.0) for i in range(20)}
    scheduled |= {k: sorted(lines[k]) for k in (31, 33)}
    scheduled[32] = [FIRST + timedelta(1 + 2 * i) for i in range(25)]  # scheduled, played once
    standin = {k: line(0.5 + k / 30) for k in range(1, 31)} | {31: line(3.0), 32: line(2.5)}
    return lines, players, standin, scheduled


def league(opening_days: int | None = rn.OPENING_DAYS):
    lines, players, standin, scheduled = season()
    setup = rn.replay_setup(
        2024,
        lines,
        players,
        standin,
        FIRST,
        scheduled,
        teams=4,
        slots=SLOTS,
        weeks=6,
        playoff_weeks=1,
        playoff_teams=2,
        opening_days=opening_days,
    )
    return setup, lines


# --------------------------------------------------------------------------- the pool
def test_the_league_is_everyone_with_a_scheduled_game_and_the_draft_an_opening_week_roster():
    setup, _ = league()
    drafted = {k for r in setup.rosters.values() for k, _ in r}
    # Everyone listed with a scheduled game is in the league, projected or not; 34 has none.
    assert set(setup.players) == set(range(1, 34))
    # 32 is projected and played once: in the league and drafted (his team plays in week one).
    assert 32 in drafted
    # 31 is projected above everyone but has no game in the first seven days: on the wire.
    assert 31 in setup.projection and 31 not in drafted and 31 in setup.pool
    # 33 is nobody's projection: never drafted, on the wire, out of the market's view.
    assert 33 not in setup.projection and 33 in setup.pool and 33 not in setup.market
    assert set(setup.market) == set(setup.projection) == set(range(1, 33))
    assert len(drafted) == 16 and set(setup.pool) == set(setup.players) - drafted
    # None for the opening days drafts every projected player, as the hold-out gate does.
    every, _ = league(opening_days=None)
    assert 31 in {k for r in every.rosters.values() for k, _ in r}


def test_a_player_nobody_projected_is_a_candidate_only_from_the_day_after_his_first_game():
    setup, lines = league()
    weights = dict.fromkeys(wk.STATS, 6.0)
    w = rn.replay_world(setup, lines, 1, 1, 0, weights)
    seen = FIRST + timedelta(5)  # his first recorded game
    undrafted = [k for k in setup.pool if k in setup.projection]
    newcomer = newcomer_prior(setup.projection, undrafted)
    assert newcomer["pts"] == pytest.approx(
        sum(setup.projection[k]["pts"] for k in undrafted) / len(undrafted)
    )

    def candidates(day: date) -> set[int]:
        state = replace(initial(setup), day=day)
        status, returns = w.status_on(day)
        built = policy.problem_of(setup, state, 1, KNOBS, w.beliefs_on(day), status, returns)
        assert built is not None
        return {k for k, _ in built.problem.candidates}

    for day in (FIRST, seen):
        assert 33 not in w.beliefs_on(day) and 33 not in candidates(day)
    after = seen + timedelta(1)
    assert 33 in candidates(after) and 31 in candidates(FIRST)
    assert w.beliefs_on(after)[33] == pytest.approx(shrunk(newcomer, lines[33][seen], 1, weights))


# --------------------------------------------------------------------------- the news
def test_the_told_return_date_spread_is_a_parameter_and_zero_tells_the_true_day():
    setup, lines = league()
    exact = rn.replay_world(setup, lines, 1, 1, 0, news_sd=0.0)
    default = rn.replay_world(setup, lines, 1, 1, 0)
    assert default.news_sd == world.NEWS_SD_DAYS == 2.0
    told_any = 0
    for k, days in exact.game_days.items():
        for a in exact.absences(k):
            if a.end >= len(days) - 1:
                continue
            heard = days[a.start] + timedelta(1)  # the lag is one day
            status, returns = exact.status_on(heard)
            # At no spread the date told is the day after his last missed game.
            assert status.get(k) == "O" and returns[k] == max(heard, days[a.end] + timedelta(1))
            # The default reproduces the formula the replay used before the spread was a knob.
            g = world.rng(1, 0, k, a.start, world.STREAMS["news"])
            noise = round(float(g.standard_normal() * world.NEWS_SD_DAYS))
            s2, r2 = default.status_on(heard)
            assert s2.get(k) == "O"
            assert r2[k] == max(heard, days[a.end] + timedelta(1 + noise))
            told_any += 1
    assert told_any == 10


# --------------------------------------------------------------------------- the hold-out gate
def test_the_hold_out_gate_keeps_its_league_and_its_figures(tmp_path: Path):
    """Gate 1 still reads the players with 20 played games, every one drafted on his own realized
    rates and believed at them all season; its figures on the synthetic data are the ones the
    code before the causal belief gave (checked against main at cde02bd)."""
    data = make_data_dir(tmp_path)
    lines, members, scheduled = reader.replay_lines(data, 2025)
    setup, kept = cli.hold_out_setup(2025, lines, members, scheduled)
    full = {k for k, v in lines.items() if len(v) >= rn.GATE_MIN_GAMES}
    assert set(setup.players) == set(kept) == full and len(full) == 82
    truth = rn.realized_rates({k: lines[k] for k in full})
    assert setup.projection == {k: dict(v) for k, v in truth.items()}
    value = wk.per_game_values(truth, setup.cats, None)
    want = snake_draft(list(truth), value, setup.teams, setup.spots())
    assert setup.rosters == want and setup.pool == ()
    w = rn.replay_world(setup, kept, 1, 3, 0, belief="fixed")
    assert all(w.beliefs_on(d) == setup.projection for d in setup.days[::9])
    g = cli.gate_hold_out_team_weeks(data, 2025, inputs(), 3, paths=4)
    assert g["detail"]["n"] == 588 and g["detail"]["team_weeks"] == 84
    assert [b["count"] for b in g["detail"]["buckets"]] == [286, 160, 64, 50, 28]
    a = cli.gate_absences(data, 2025, inputs(), 3)
    assert a["detail"]["n"] == 574
    assert [b["count"] for b in a["detail"]["buckets"]] == [76, 65, 76, 144, 213]


# --------------------------------------------------------------------------- the schedule (PR C2)
@pytest.fixture(scope="module")
def wire_league(tmp_path_factory):
    """The wire fixture's replay of 2024 on the prior season's stand-in, path 0."""
    data = make_data_dir(tmp_path_factory.mktemp("wire"), wire=120)
    lines, members, scheduled = reader.replay_lines(data, 2024)
    prior = reader.prior_rates(data, 2024)
    return cli.replay_setup_of(2024, lines, members, scheduled, ("prior", 0.0), prior, 5, 0)


def test_a_replays_schedule_keys_every_day_of_its_calendar(wire_league):
    """Every day of the calendar is a key, an empty set when nobody plays, so the engine reads
    every day and extrapolates no game (``moves.games_ahead``'s unread days are none)."""
    setup = wire_league
    days = setup.days
    assert days[0] == setup.calendar.weeks[0].start and all(d in setup.schedule for d in days)
    # The synthetic logs end weeks before the replay's calendar: those days are keyed, empty.
    last_game = max(d for d, teams in setup.schedule.items() if teams)
    assert last_game < setup.season_end and setup.schedule[setup.season_end] == frozenset()
    built = policy.problem_of(setup, initial(setup), 1, KNOBS, setup.projection, {}, {})
    teams = sorted({m.nba_team for m in setup.players.values()})
    assert len(teams) == len(setup.players)  # every player is his own team
    for day in days:
        for team in teams:
            assert mv.games_ahead(built.problem, team, day)[1] == 0.0


def test_on_a_replay_the_season_figure_is_the_engines_at_playoff_weight_one(wire_league):
    """PR C's two invariants on a replay setup: a healthy player's ``worth_w`` is
    ``moves.worth_from`` and an absent one's ``moves.net_of_return``."""
    setup = wire_league
    state = initial(setup)
    day = setup.start
    out = state.active(1)[0]
    back = day + timedelta(12)
    built = policy.problem_of(setup, state, 1, KNOBS, setup.projection, {out: "O"}, {out: back})
    p = built.problem
    fig = policy.SeasonFigure(built, 1.0)
    tomorrow = day + timedelta(1)
    healthy = [k for k, _ in p.roster if k != out] + [k for k, _ in p.candidates][:5]
    assert len(healthy) > 5
    for k in healthy:
        assert fig.worth(k, tomorrow) == pytest.approx(mv.worth_from(p, k, tomorrow))
    player = dict(p.roster)[out]
    assert fig.worth(out, tomorrow) == pytest.approx(mv.net_of_return(p, out, player))
    assert fig.worth(out, tomorrow) != 0.0
