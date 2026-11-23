"""The recent-form blend (#486, ODDS CALIBRATION #489): each player's per-game line moved toward
the player's recent actual line, by ``rate_shrink x g / (g + rate_shrink_games)``, on the week and
three-week horizons; the keep rule, the season guard and every rest-of-season figure stay on the
line before the blend. Every league here is made up (``test_moves``'s, ``test_lift``'s and
``test_season``'s fixtures)."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from pickandroll.api import season_knobs
from pickandroll.api import season_moves as sm
from pickandroll.season import decisions as dl
from pickandroll.season import moves as mv
from pickandroll.season import progress as pg
from pickandroll.season import recent as rc
from pickandroll.season import reserve as rs

from .test_lift import bump, lifted, thin_league
from .test_moves import rates
from .test_season import (  # noqa: F401
    LEAGUE,
    NOW,
    client,
    fixture_names,
    past_days_csv,
    projection_csv,
)
from .test_season_guard import built_of, drop_clocks


# --------------------------------------------------------------------------- the blend
def test_a_full_window_moves_the_line_by_the_shrink_times_g_over_g_plus_k():
    line = {"pts": 10.0, "reb": 4.0}
    recent = {"pts": 20.0, "reb": 8.0}
    windows = {7: {1: (4.0, recent)}}
    out, used = rc.blend({1: line}, windows, 0.5, 4.0)
    # w = 0.5 x 4 / (4 + 4) = 0.25.
    assert rc.weight(4.0, 0.5, 4.0) == pytest.approx(0.25)
    assert out[1] == {"pts": pytest.approx(12.5), "reb": pytest.approx(5.0)}
    assert used == {1: 7}
    # More games, more weight, never past the shrink.
    assert rc.weight(12.0, 0.5, 4.0) == pytest.approx(0.375)
    assert rc.weight(1000.0, 0.5, 4.0) < 0.5
    # The line as read is untouched.
    assert line == {"pts": 10.0, "reb": 4.0}


def test_no_recent_games_keep_the_projection_and_a_shrink_of_zero_returns_the_rates_themselves():
    line = {"pts": 10.0}
    rates_in = {1: line, 2: {"pts": 5.0}}
    windows = {7: {1: (0.0, {"pts": 30.0})}, 14: {}}
    out, used = rc.blend(rates_in, windows, 0.5, 4.0)
    assert out == rates_in and used == {}
    assert out[1] is line
    windows = {7: {1: (3.0, {"pts": 30.0})}}
    off, used = rc.blend(rates_in, windows, 0.0, 4.0)
    assert off is rates_in and used == {}
    assert rc.knobs_of(None) == dict(rc.DEFAULTS)
    assert rc.knobs_of({rc.SHRINK: 0, rc.GAMES: None}) == {rc.SHRINK: 0.0, rc.GAMES: 4.0}


def test_a_percentage_moves_toward_the_recent_one_weighted_by_the_attempts():
    # Projected 5 of 10 a game (50%); lately 18 of 20 (90%).
    line = {"fgm": 5.0, "fga": 10.0}
    recent = {"fgm": 18.0, "fga": 20.0}
    out, _ = rc.blend({1: line}, {7: {1: (4.0, recent)}}, 1.0, 4.0)
    # w = 0.5: 11.5 of 15, the attempts-weighted mix of the two percentages.
    assert out[1]["fgm"] == pytest.approx(11.5) and out[1]["fga"] == pytest.approx(15.0)
    pct = out[1]["fgm"] / out[1]["fga"]
    assert pct == pytest.approx((0.5 * 10 * 0.5 + 0.5 * 20 * 0.9) / (0.5 * 10 + 0.5 * 20))
    assert pct != pytest.approx((0.5 + 0.9) / 2)


def test_the_seven_day_window_is_read_with_three_games_else_the_fourteen_day_one():
    fresh = (3.0, {"pts": 30.0})
    thin = (2.0, {"pts": 30.0})
    longer = (6.0, {"pts": 20.0})
    assert rc.window_of(1, {7: {1: fresh}, 14: {1: longer}}) == (7, fresh)
    assert rc.window_of(1, {7: {1: thin}, 14: {1: longer}}) == (14, longer)
    # No 14-day line: the thin 7-day one is all there is.
    assert rc.window_of(1, {7: {1: thin}, 14: {}}) == (7, thin)
    assert rc.window_of(1, {7: {}, 14: {1: (0.0, {})}}) is None
    assert rc.window_of(1, {}) is None


# --------------------------------------------------------------------------- the knob file
def test_the_knob_file_takes_the_blend_knobs_within_their_bounds_and_the_simulator_never_sees_them():
    raw = {
        "in_force": {"rate_shrink": 0.3, "rate_shrink_games": 6},
        "leagues": {
            "100": {"rate_shrink": 1.5, "rate_shrink_games": 0.5},
            "200": {"rate_shrink": 0},
        },
    }
    knobs, problems = pg.knob_file(raw)
    assert knobs["in_force"] == {"rate_shrink": 0.3, "rate_shrink_games": 6}
    assert knobs["leagues"].get("100", {}) == {}
    assert knobs["leagues"]["200"] == {"rate_shrink": 0}
    assert problems == [
        "league 100: rate_shrink 1.5 is above its maximum 1",
        "league 100: rate_shrink_games 0.5 is below its minimum 1",
    ]
    assert pg.refused("rate_shrink", "half") == "rate_shrink 'half' is not a number"
    assert pg.refused("rate_shrink", True) == "rate_shrink True is not a number"
    assert rc.knobs_of(pg.in_force_for(knobs, "200")) == {rc.SHRINK: 0.0, rc.GAMES: 6.0}
    # Outside the live knobs and their defaults: the simulator's arms name every live knob.
    assert not set(rc.KNOBS) & {*pg.LIVE_KNOBS, *pg.DEFAULTS}


# --------------------------------------------------------------------------- the season stays raw
def blended(p: mv.MoveProblem, factor: float = 1.6) -> mv.MoveProblem:
    """``p`` with the candidate's week line blended up (a hot week) and the line before the
    blend kept for the season, as ``season_moves.build`` makes it."""
    hot = {**p.rates, 10: {k: v * factor for k, v in p.rates[10].items()}}
    return replace(p, rates=hot, season_rates=p.rates)


def test_the_season_guard_and_the_rest_of_the_season_read_the_line_before_the_blend():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    hot = blended(p)
    raw, now = built_of(p), built_of(hot)
    # The hot week makes the move on the week horizon...
    assert mv.Evaluator(p).gain("week", [mv.Move(10, 3)]) < 0
    assert mv.Evaluator(hot).gain("week", [mv.Move(10, 3)]) > 0
    # ...but its rest of the season is the line before the blend, to the figure.
    assert sm.ros_of(now, 10, 3) == sm.ros_of(raw, 10, 3)
    assert sm.ros_of(raw, 10, 3)["value"] < 0
    guard_raw, guard_now = sm.guard_ros(raw), sm.guard_ros(now)
    assert guard_raw is not None and guard_now is not None
    assert guard_now(mv.Move(10, 3)) == guard_raw(mv.Move(10, 3))
    assert not mv.season_guard(guard_now)([mv.Move(10, 3)])
    # The decision log's season horizon (season_costly's) too; its week horizon plays the blend.
    a = dl.move_projection(raw.problem, raw.scorer, 10, 3)
    b = dl.move_projection(now.problem, now.scorer, 10, 3)
    assert b["horizons"][dl.SEASON] == a["horizons"][dl.SEASON]
    assert b["horizons"]["week"] != a["horizons"]["week"]
    # Without season_rates (the blend off), the rates are the season's.
    assert mv.season_line(p, 10, 3, 10) is p.rates[10]
    assert mv.season_line(hot, 10, 3, 10) is p.rates[10]


def test_a_lifted_add_keeps_his_lifted_line_over_the_season_under_the_blend():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    up = lifted(p)
    hot = replace(up, rates={**up.rates, 3: rates(0.3)}, season_rates=up.rates)
    assert mv.season_line(hot, 10, 3, 10) is up.lifted[10].rates
    # My drop's season line is the line before the blend.
    assert mv.season_line(hot, 10, 3, 3) is up.rates[3]
    assert sm.ros_of(built_of(hot), 10, 3) == sm.ros_of(built_of(up), 10, 3)


# --------------------------------------------------------------------------- the route
NAMES = ["Andre Drummond", "Keldon Johnson"]


def exports(client, day: date) -> None:  # noqa: F811
    """A 7-day export pulled on ``day``: Drummond's four games, Johnson's one, and four of mine
    (Durant's) well under the projection."""
    path = client.data_dir / f"bbm_actual_7d_totals_{day:%Y%m%d}-1500.csv"
    past_days_csv(
        path,
        [
            ("Andre Drummond", "NYK", "C", 4, 140, 22.0),
            ("Keldon Johnson", "SAS", "SF,PF", 1, 40, 20.0),
            ("Kevin Durant", "HOU", "SF,PF", 4, 120, 25.0),
        ],
    )
    t = datetime(day.year, day.month, day.day, 15, tzinfo=UTC).timestamp()
    os.utime(path, (t, t))


def knob_file(client, knobs: dict) -> None:  # noqa: F811
    path = season_knobs.autopilot_dir(client.data_dir) / season_knobs.KNOBS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"in_force": knobs}))
    bump(client)


def moves(client) -> dict:  # noqa: F811
    out = client.get(f"/seasons/{LEAGUE}/moves").json()
    drop_clocks(out)
    out.pop("stale", None)
    return out


def test_a_fresh_export_blends_and_the_payload_says_what_was_read(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", [*fixture_names(), *NAMES])
    exports(client, NOW.date())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    r = moves(client)["system"]["recent"]
    assert r["status"] == "blended" and r["players"] == 3
    assert (r[rc.SHRINK], r[rc.GAMES]) == (rc.DEFAULTS[rc.SHRINK], rc.DEFAULTS[rc.GAMES])
    assert r["windows"]["7d"]["file"] == "bbm_actual_7d_totals_20261021-1500.csv"
    assert "stale" not in r["windows"]["7d"] and r["windows"]["14d"] is None


def test_a_stale_export_blends_nothing_and_says_so(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", [*fixture_names(), *NAMES])
    exports(client, date(2026, 10, 14))
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    out = moves(client)
    r = out["system"]["recent"]
    assert r["status"] == (
        "no blend: export stale (bbm_actual_7d_totals_20261014-1500.csv (2026-10-14))"
    )
    assert r["players"] == 0 and r["windows"]["7d"]["stale"] is True
    # The moves are the ones with the blend off.
    knob_file(client, dict(rc.OFF))
    off = moves(client)
    assert "recent" not in off["system"]
    out["system"].pop("recent")
    assert json.dumps(out, sort_keys=True) == json.dumps(off, sort_keys=True)


def test_an_unreadable_export_blends_nothing_and_the_moves_still_solve(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    (client.data_dir / "bbm_actual_7d_totals_20261021-1400.xls").write_bytes(b"")
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    r = client.get(f"/seasons/{LEAGUE}/moves")
    assert r.status_code == 200
    recent = r.json()["system"]["recent"]
    assert recent["status"] == (
        "no blend: export unreadable (bbm_actual_7d_totals_20261021-1400.xls)"
    )
    assert recent["players"] == 0 and recent["windows"]["7d"]["unreadable"]


def test_no_export_blends_nothing_and_says_so(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    r = moves(client)["system"]["recent"]
    assert r["status"] == "no blend: no export" and r["players"] == 0


def test_a_shrink_of_zero_gives_todays_moves_byte_for_byte(client, monkeypatch):  # noqa: F811
    # The code before #486: no blend anywhere.
    monkeypatch.setattr(rc, "DEFAULTS", dict(rc.OFF))
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", [*fixture_names(), *NAMES])
    exports(client, NOW.date())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    before = moves(client)
    assert "recent" not in before["system"]
    monkeypatch.setattr(rc, "DEFAULTS", {rc.SHRINK: 0.5, rc.GAMES: 4.0})
    knob_file(client, {rc.SHRINK: 0})
    off = moves(client)
    assert json.dumps(off, sort_keys=True) == json.dumps(before, sort_keys=True)
    # At the first guesses, the blend is read.
    knob_file(client, {})
    on = moves(client)
    assert on["system"]["recent"]["status"] == "blended"
    # And it moves the figures: the week's odds on my lines.
    on.pop("system")
    before.pop("system")
    assert json.dumps(on, sort_keys=True) != json.dumps(before, sort_keys=True)


def test_the_week_projection_plays_the_blend_and_shows_the_line_as_read(client):  # noqa: F811
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    exports(client, NOW.date())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    on = client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    knob_file(client, {rc.SHRINK: 0})
    off = client.get(f"/seasons/{LEAGUE}").json()["week_projection"]
    assert json.dumps(on["matchup"], sort_keys=True) != json.dumps(off["matchup"], sort_keys=True)
    # The rows' Basketball Monster line is the one read, blend or none.
    assert on["players"] == off["players"]


def test_the_keep_rule_and_the_lift_read_the_line_before_the_blend(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rs, "DEFAULTS", dict(rs.OFF))
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", [*fixture_names(), *NAMES])
    exports(client, NOW.date())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    seen: dict[str, object] = {}
    real_keep, real_lifts = sm.keep_inputs, sm.lf.lifts

    def keep_inputs(rated, *args, **kw):
        seen.setdefault("keep", []).append(rated.bbm.rates)
        return real_keep(rated, *args, **kw)

    def lifts(flags, lines, *args, **kw):
        seen.setdefault("lift", []).append(lines)
        return real_lifts(flags, lines, *args, **kw)

    monkeypatch.setattr(sm, "keep_inputs", keep_inputs)
    monkeypatch.setattr(sm.lf, "lifts", lifts)
    on = moves(client)
    assert on["system"]["recent"]["status"] == "blended"
    knob_file(client, {rc.SHRINK: 0})
    moves(client)
    keep_on, keep_off = seen["keep"][0], seen["keep"][-1]
    lift_on, lift_off = seen["lift"][0], seen["lift"][-1]
    assert len(seen["keep"]) == 2 and len(seen["lift"]) == 2
    assert keep_on == keep_off and lift_on == lift_off
