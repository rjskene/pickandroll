"""The simulated world (#172, PR 1): seeded draws, the three layers' moments, the beliefs."""

from __future__ import annotations

import numpy as np
import pytest

from pickandroll.season.sim import world as w
from pickandroll.season.sim.fit import Component, Hazard

PHI = {
    "pts": 1.5,
    "reb": 1.5,
    "ast": 1.2,
    "fga": 1.4,
    "fta": 1.8,
    "threes": 1.1,
    "stl": 1.0,
    "blk": 1.0,
    "tov": 1.0,
}
RATES = {
    "pts": 20.0,
    "threes": 2.0,
    "reb": 8.0,
    "ast": 5.0,
    "stl": 1.0,
    "blk": 0.8,
    "tov": 2.5,
    "fgm": 7.0,
    "fga": 15.0,
    "ftm": 4.0,
    "fta": 5.0,
}
HAZARD = Hazard(
    0.10,
    (
        Component(1, 3, 0.7, {1: 0.5, 2: 0.3, 3: 0.2}),
        Component(4, 15, 0.25, {5: 0.5, 10: 0.5}),
        Component(16, None, 0.05, {20: 1.0}),
    ),
    runs=100,
    played=1000,
    players=20,
    censored=2,
    censored_share=0.1,
    leading=0,
)


def test_the_same_seed_and_path_draw_the_same_line():
    a = w.game_line(1, 3, 7, 11, RATES, PHI, 0.2)
    b = w.game_line(1, 3, 7, 11, RATES, PHI, 0.2)
    assert a == b
    assert w.game_line(1, 4, 7, 11, RATES, PHI, 0.2) != a
    assert w.game_line(1, 3, 7, 12, RATES, PHI, 0.2) != a


def test_streams_do_not_move_each_other():
    factor = w.minutes_factor(1, 3, 7, 11, 0.2)
    line = w.game_line(1, 3, 7, 11, RATES, {k: 3.0 for k in PHI}, 0.2)
    assert line["minutes_factor"] == factor
    eps = w.errors(1, 3, ["a", "b"], ["pts"], 0.0, {}, {"pts": 0.1})
    assert eps == w.errors(1, 3, ["a", "b"], ["pts"], 0.0, {}, {"pts": 0.1})


def test_errors_have_the_shrunk_mean_and_the_spread():
    players = [f"p{i}" for i in range(3000)]
    gap = {p: {"pts": 0.4} for p in players}
    eps = w.errors(5, 0, players, ["pts"], 0.5, gap, {"pts": 0.2})
    draws = np.array([eps[p]["pts"] for p in players])
    assert abs(draws.mean() + 0.2) < 0.02
    assert abs(draws.std() - 0.2) < 0.02
    truth = w.true_rates({"p0": {"pts": 10.0}}, {"p0": {"pts": np.log(1.1)}})
    assert truth["p0"]["pts"] == pytest.approx(11.0)


def test_game_line_moments_and_identities():
    lines = [w.game_line(2, 0, 0, g, RATES, PHI, 0.0) for g in range(3000)]
    reb = np.array([ln["reb"] for ln in lines])
    assert abs(reb.mean() - 8.0) < 0.3
    assert abs(reb.var() / reb.mean() - 1.5) < 0.3
    for ln in lines:
        assert ln["fgm"] <= ln["fga"] and ln["ftm"] <= ln["fta"]
        assert ln["pts"] == 2 * ln["fgm"] + ln["threes"] + ln["ftm"]
        assert ln["minutes_factor"] == 1.0
    fgm = np.array([ln["fgm"] for ln in lines])
    fga = np.array([ln["fga"] for ln in lines])
    assert abs(fgm.sum() / fga.sum() - 7 / 15) < 0.02


def test_the_minutes_factor_correlates_a_players_stats():
    wide = [w.game_line(3, 0, 0, g, RATES, {k: 1.0 for k in PHI}, 0.4) for g in range(2000)]
    flat = [w.game_line(3, 0, 0, g, RATES, {k: 1.0 for k in PHI}, 0.0) for g in range(2000)]

    def corr(lines):
        a = np.array([ln["reb"] for ln in lines])
        b = np.array([ln["ast"] for ln in lines])
        return float(np.corrcoef(a, b)[0, 1])

    assert corr(wide) > 0.3
    assert abs(corr(flat)) < 0.1
    factors = np.array([ln["minutes_factor"] for ln in wide])
    assert abs(factors.mean() - 1.0) < 0.03


def test_absences_follow_the_hazard_and_todays_status():
    available, out = w.absences(4, 0, 0, 20000, HAZARD)
    missed = 1 - available.mean()
    mean_len = 0.7 * 1.7 + 0.25 * 7.5 + 0.05 * 20
    expected = 0.10 * mean_len / (1 + 0.10 * mean_len)
    assert abs(missed - expected) < 0.03
    for a in out:
        assert not available[a.start : a.end + 1].any()
    assert all(available[a.end + 1] for a in out if a.end + 1 < len(available))
    today, out2 = w.absences(4, 0, 0, 30, HAZARD, out_through=4)
    assert not today[:5].any()
    assert out2[0] == w.Absence(0, 4)
    again, _ = w.absences(4, 0, 0, 30, HAZARD, out_through=4)
    assert (again == today).all()


def test_refresh_moves_beliefs_toward_the_truth():
    beliefs = {"a": {"pts": 10.0, "reb": 5.0}, "b": {"pts": 10.0}}
    truth = {"a": {"pts": 20.0, "reb": 5.0}}
    b = beliefs
    for week in range(20):
        b = w.refresh(b, truth, 0.25, 0.0, 1, 0, week)
    assert abs(b["a"]["pts"] - 20.0) < 0.2
    assert b["a"]["reb"] == pytest.approx(5.0)
    assert b["b"]["pts"] == 10.0
    frozen = w.refresh(beliefs, truth, 0.0, 0.0, 1, 0, 0)
    assert frozen["a"]["pts"] == 10.0
    noisy = w.refresh(beliefs, truth, 0.0, 0.1, 1, 0, 0)
    assert noisy == w.refresh(beliefs, truth, 0.0, 0.1, 1, 0, 0)
    assert noisy["a"]["pts"] != 10.0


def test_news_arrives_after_the_lag_with_a_noisy_return():
    absence = w.Absence(5, 9)
    assert w.news(1, 0, 0, absence, 6, 2) == w.Seen(False, None)
    seen = w.news(1, 0, 0, absence, 7, 2)
    assert seen.out and seen.returns is not None and seen.returns >= 7
    assert seen == w.news(1, 0, 0, absence, 7, 2)
    assert w.news(1, 0, 0, None, 7, 2) == w.Seen(False, None)
    late = w.news(1, 0, 0, absence, 30, 2)
    assert late.returns == 30


def test_player_season_and_team_week():
    days = [1, 2, 4, 5]
    lines_a, _ = w.player_season(7, 0, 0, RATES, PHI, 0.1, days, HAZARD)
    assert set(lines_a) <= set(days)
    lines = {
        "a": {1: {"pts": 10.0, "reb": 5.0}, 2: {"pts": 10.0, "reb": 5.0}},
        "b": {1: {"pts": 20.0, "reb": 2.0}},
        "c": {1: {"pts": 5.0, "reb": 9.0, "minutes_factor": 1.2}},
    }
    roster = [("a", ["PG"]), ("b", ["SF"]), ("c", ["C"])]
    value = {"a": 1.0, "b": 3.0, "c": 2.0}
    totals = w.team_week(lines, roster, [1, 2], ["Util", "Util"], value)
    # Day 1: two slots, b and c start, a sits; day 2: a alone.
    assert totals == {"pts": 35.0, "reb": 16.0}
