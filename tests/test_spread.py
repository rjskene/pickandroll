"""The week's spread for the line's error and missed games (#487, ODDS CALIBRATION #489): each
started game discounted by its chance of being missed (the healthy rate by days ahead, or a Q, D
or P listing's this week), and the spread widened by those misses and by ``rate_cv`` of the
line. Every knob at 0 is the week before. Every league here is made up (``test_moves``'s,
``test_lift``'s and ``test_season``'s fixtures)."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pickandroll.api import season_moves as sm
from pickandroll.season import lineup as lu
from pickandroll.season import moves as mv
from pickandroll.season import progress as pg
from pickandroll.season import spread as spr
from pickandroll.season import weekly as wk

from .test_lift import bump, thin_league
from .test_moves import WEEKS, build, player, rates, schedule
from .test_recent_blend import knob_file, moves
from .test_season import LEAGUE, client, fixture_names, projection_csv  # noqa: F401
from .test_season_guard import built_of

NOISE = spr.noise_of(spr.DEFAULTS)
MON = WEEKS[0][0]
SLOTS = ("C", "C", "Util")
NINE = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")


def week(members, days, noise=None, this_week=True, today=None):
    sched = schedule({"MIN": list(range(28)), "STR": [0, 2, 4, 6]})
    rate = {k: rates(1.0) for k, _ in members}
    value = {k: 1.0 for k, _ in members}
    return wk.project_week(
        members, rate, days, sched, SLOTS, value, this_week, noise=noise, today=today
    )


ROSTER = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]


# --------------------------------------------------------------------------- the knobs at zero
def test_every_knob_at_zero_is_the_week_before_exactly():
    assert spr.noise_of(spr.OFF) is None
    zero = wk.Noise(0.0, 0.0, spr.STATUS_MISS, spr.SHAPE)
    plain = week(ROSTER, WEEKS[0])
    for off in (None, zero):
        tw = week(ROSTER, WEEKS[0], off)
        assert tw == plain
        assert json.dumps(tw.to_dict()) == json.dumps(plain.to_dict())
    # The status rates go with the missed games: off with miss_rate 0.
    assert spr.noise_of({spr.CV: 0.25, spr.MISS: 0}).status_miss == {}
    assert spr.noise_of({spr.CV: 0, spr.MISS: 0.07}).rate_cv == 0.0


# --------------------------------------------------------------------------- the games
def test_each_started_game_is_discounted_by_its_chance_of_being_missed():
    tw = week(ROSTER, WEEKS[0], NOISE, today=MON)
    # Seven days, three of mine every day: lags 0 to 6, the shape's.
    expected = 7 - sum(0.07 * s for s in spr.SHAPE)
    for k in (1, 2, 3):
        pw = tw.players[k]
        assert (pw.games, pw.started) == (7, 7)  # whole games as before
        assert pw.miss == pytest.approx(tuple(0.07 * s for s in spr.SHAPE))
        assert pw.expected == pytest.approx(expected)
    assert tw.totals["pts"] == pytest.approx(3 * 10 * expected)
    assert wk.player_totals(tw.players[1], rates(1.0))["pts"] == pytest.approx(10 * expected)
    # A later week: every game past six days takes the last shape's rate.
    later = week(ROSTER, WEEKS[2], NOISE, this_week=False, today=MON)
    assert later.players[1].miss == pytest.approx((0.07 * spr.SHAPE[-1],) * 7)
    # With no today, the days ahead count from the week's first day.
    assert week(ROSTER, WEEKS[0], NOISE).players[1].miss == pw.miss


def test_a_q_d_or_p_listing_takes_its_status_rate_this_week_only():
    listed = [player(1, "MIN", "Q"), player(2, "MIN", "D"), player(3, "MIN", "P")]
    tw = week(listed, WEEKS[0], NOISE, today=MON)
    assert tw.players[1].miss == spr.STATUS_MISS["Q"]
    assert tw.players[2].miss == (0.698,) * 7
    assert tw.players[3].miss == (0.126,) * 7
    # Q's rate falls with the days ahead, as measured.
    q = spr.STATUS_MISS["Q"]
    assert q[0] > q[2] > q[4]
    # A later week reads a listing as healthy: the status is this week's news.
    later = week(listed, WEEKS[1], NOISE, this_week=False, today=MON)
    healthy = week(ROSTER, WEEKS[1], NOISE, this_week=False, today=MON)
    assert later.totals == healthy.totals
    # O and INJ keep the out rule; a GTD the zero-games rule.
    assert week([player(1, "MIN", "O")], WEEKS[0], NOISE).players[1].started == 0


# --------------------------------------------------------------------------- the spread
def test_the_spread_widens_more_on_monday_than_on_friday():
    def ratio(days):
        a = week(ROSTER, days, NOISE, today=days[0])
        b = week(ROSTER, days)
        return {s: a.variance[s] / b.variance[s] for s in ("pts", "reb", "ast")}

    monday, friday = ratio(WEEKS[0]), ratio(WEEKS[0][4:])
    for s in monday:
        assert monday[s] > friday[s] > 1.0
    # The line's error alone: (cv x E[n] x r)^2 on top of phi x the total.
    cv_only = wk.Noise(0.25)
    tw = week(ROSTER, WEEKS[0], cv_only)
    assert tw.variance["pts"] == pytest.approx(wk.PHI["pts"] * 3 * 70 + 3 * (0.25 * 7 * 10) ** 2)
    # The missed games alone: m (1 - m) per game times the line squared.
    miss_only = wk.Noise(0.0, 0.1)
    tw = week([player(1, "MIN")], WEEKS[0][:1], miss_only)
    m = 0.1
    assert tw.variance["pts"] == pytest.approx(wk.PHI["pts"] * 10 * (1 - m) + m * (1 - m) * 100)


# --------------------------------------------------------------------------- the moves
def streamers() -> mv.MoveProblem:
    """Three of mine every day; three candidates with the same line: four games this week (10),
    three (11), and four but listed Q (12)."""
    sched = schedule({"MIN": list(range(28)), "FOUR": [0, 2, 4, 6], "THREE": [1, 3, 5]})
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    cands = [player(10, "FOUR"), player(11, "THREE"), player(12, "FOUR", "Q")]
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(0.2)} | {k: rates(1.0) for k in (10, 11, 12)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.0), 21: rates(0.9), 22: rates(0.8)}
    return build(roster, cands, rate, sched, opponent, [opponent])


def test_streamers_with_equal_lines_still_rank_by_games_and_then_by_status():
    plain = streamers()
    noisy = replace(plain, noise=NOISE)

    def gains(p):
        ev = mv.Evaluator(p)
        return {k: ev.gain("week", [mv.Move(k, 3)]) for k in (10, 11, 12)}

    before, after = gains(plain), gains(noisy)
    assert before[10] > before[11] and before[10] == pytest.approx(before[12])
    # The miss discount keeps the order by games, and a Q listing ranks below a healthy one.
    assert after[10] > after[11]
    assert after[10] > after[12]


def test_the_season_horizon_and_the_guard_count_whole_games():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    noisy = replace(p, noise=NOISE)
    assert sm_ros(noisy) == sm_ros(p)
    # The week's gain does take the discount.
    assert mv.Evaluator(noisy).gain("week", [mv.Move(10, 3)]) != pytest.approx(
        mv.Evaluator(p).gain("week", [mv.Move(10, 3)])
    )


def sm_ros(p: mv.MoveProblem):
    built = built_of(p)
    guard = sm.guard_ros(built)
    return sm.ros_of(built, 10, 3), guard(mv.Move(10, 3)) if guard else None


# --------------------------------------------------------------------------- the knob file
def test_the_knob_file_takes_the_spread_knobs_within_their_bounds():
    raw = {
        "in_force": {"rate_cv": 0.2, "miss_rate": 0.05},
        "leagues": {"100": {"rate_cv": 1.5, "miss_rate": -0.1}, "200": {"miss_rate": 0}},
    }
    knobs, problems = pg.knob_file(raw)
    assert knobs["in_force"] == {"rate_cv": 0.2, "miss_rate": 0.05}
    assert knobs["leagues"]["200"] == {"miss_rate": 0}
    assert problems == [
        "league 100: rate_cv 1.5 is above its maximum 1",
        "league 100: miss_rate -0.1 is below its minimum 0",
    ]
    assert spr.knobs_of(pg.in_force_for(knobs, "200")) == {spr.CV: 0.2, spr.MISS: 0.0}
    # Outside the live knobs and their defaults: the simulator's arms name every live knob.
    assert not set(spr.KNOBS) & {*pg.LIVE_KNOBS, *pg.DEFAULTS}


# --------------------------------------------------------------------------- the route
def test_every_knob_at_zero_gives_todays_moves_and_week_view_byte_for_byte(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(spr, "DEFAULTS", dict(spr.OFF))
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    before, view = moves(client), client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    assert "spread" not in before["system"] and "spread" not in view
    monkeypatch.setattr(spr, "DEFAULTS", {spr.CV: 0.25, spr.MISS: 0.07})
    knob_file(client, dict(spr.OFF))
    off = moves(client)
    assert json.dumps(off, sort_keys=True) == json.dumps(before, sort_keys=True)
    view_off = client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    assert json.dumps(view_off, sort_keys=True) == json.dumps(view, sort_keys=True)
    # At the ruled defaults the payload, the log and the week view say what was applied.
    knob_file(client, {})
    on = moves(client)
    s = on["system"]["spread"]
    assert (s["rate_cv"], s["miss_rate"]) == (0.25, 0.07)
    assert s["source"] == spr.SOURCE and s["status_miss"]["Q"] == list(spr.STATUS_MISS["Q"])
    assert client.get(f"/seasons/{LEAGUE}").json()["week_projection"]["spread"] == s
    on.pop("system"), before.pop("system")
    assert json.dumps(on, sort_keys=True) != json.dumps(before, sort_keys=True)
    bump(client)


def test_a_lineup_day_reads_the_same_spread_as_the_opponents_finals():
    """``win_lineup`` with the miss and cv: my starts take what the opponent's finals carry."""
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    sched = schedule({"MIN": list(range(28))})
    days = WEEKS[0]
    playing = wk.playing_days(roster, days, sched, True)
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(0.8)}
    value = {k: 1.0 for k in rate}
    theirs = wk.finals(week(roster, days, NOISE, today=MON), {}, NINE)
    plain = lu.win_lineup(roster, playing, days, SLOTS, value, rate, NINE, {}, theirs)
    same = lu.win_lineup(
        roster, playing, days, SLOTS, value, rate, NINE, {}, theirs, miss=None, cv=0.0
    )
    assert plain == same
    noisy = lu.win_lineup(
        roster, playing, days, SLOTS, value, rate, NINE, {}, theirs, miss={1: 0.07}, cv=0.25
    )
    assert set(noisy.days) == set(plain.days)
