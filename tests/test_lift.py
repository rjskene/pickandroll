"""The breakout flag's lift (#435, the user's ruling of 2026-11-19): a flagged available player's
line lifted toward the recent minutes, and by a floor on an adds surge, on a move that drops one
of my marginal players or nobody. Every league here is made up (``test_moves``'s,
``test_season_guard``'s and ``test_season``'s fixtures)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from pickandroll.api import season_decisions as sd
from pickandroll.api import season_flags, season_knobs
from pickandroll.api import season_moves as sm
from pickandroll.api.seasons import STATE, season_dir
from pickandroll.season import flags as fl
from pickandroll.season import lift as lf
from pickandroll.season import moves as mv
from pickandroll.season import progress as pg
from pickandroll.season import reserve as rs

from .test_moves import build, player, rates, schedule
from .test_season import LEAGUE, client, fixture_names, projection_csv  # noqa: F401
from .test_season_guard import built_of


def minutes(projected: float, *recent: float, games: tuple[int, int] = (4, 4)) -> fl.Signal:
    windows = {
        d: {"games": g, "mpg": m, "usage": None}
        for d, m, g in zip((7, 14), recent, games, strict=False)
    }
    return fl.Signal(
        0.5, "minutes up", "minutes up", {"projected_mpg": projected, "windows": windows}
    )


def flag(level: str | None, **signals: fl.Signal) -> fl.Flag:
    return fl.Flag(level, 1.6, signals)


SURGE = fl.Signal(0.7, "adds", "adds", {"adds": 900})


# --------------------------------------------------------------------------- the factor
def test_the_minutes_move_toward_the_seven_day_window_by_the_levels_weight():
    # Projected 20, the last 7 days 30 over 2 games: an add's weight 0.75 gives 27.5 minutes.
    f = flag("add", minutes=minutes(20.0, 30.0, 18.0, games=(2, 4)))
    assert lf.factor_of(f, lf.DEFAULTS) == pytest.approx(1.375)
    assert lf.factor_of(replace(f, level="watch"), lf.DEFAULTS) == pytest.approx(1.25)
    assert lf.factor_of(replace(f, level="must-add"), lf.DEFAULTS) == pytest.approx(1.5)
    # The 14-day window lags the role change; with one game in 7 days it is the one read.
    lagging = flag("add", minutes=minutes(20.0, 30.0, 24.0, games=(1, 4)))
    assert lf.factor_of(lagging, lf.DEFAULTS) == pytest.approx(1.15)
    assert lf.recent_mpg({"14": {"games": 4, "mpg": 24.0}}) == 24.0
    assert lf.recent_mpg({7: {"games": 1, "mpg": 30.0}}) is None
    # Fewer minutes now than projected never lowers the line.
    assert lf.factor_of(flag("add", minutes=minutes(30.0, 20.0)), lf.DEFAULTS) == 1.0


def test_a_surge_lifts_by_the_levels_floor_even_with_no_minutes_gain():
    assert lf.factor_of(flag("watch", surge=SURGE), lf.DEFAULTS) == pytest.approx(1.10)
    assert lf.factor_of(flag("add", surge=SURGE), lf.DEFAULTS) == pytest.approx(1.15)
    assert lf.factor_of(flag("must-add", surge=SURGE), lf.DEFAULTS) == pytest.approx(1.25)
    # The larger of the two.
    both = flag("add", surge=SURGE, minutes=minutes(20.0, 30.0))
    assert lf.factor_of(both, lf.DEFAULTS) == pytest.approx(1.375)
    small = flag("add", surge=SURGE, minutes=minutes(20.0, 21.0))
    assert lf.factor_of(small, lf.DEFAULTS) == pytest.approx(1.15)


def test_no_level_or_every_knob_at_zero_lifts_nothing():
    line = rates(1.0)
    assert lf.lift_of(flag(None, surge=SURGE), line, lf.DEFAULTS) is None
    assert lf.lift_of(flag("add", surge=SURGE), line, lf.OFF) is None
    assert lf.lift_of(flag("add", surge=SURGE), None, lf.DEFAULTS) is None
    assert lf.is_off(lf.OFF) and not lf.is_off({}) and lf.is_off({lf.MARGINAL: 0})
    lifted = lf.lift_of(flag("add", minutes=minutes(20.0, 24.0)), line, lf.DEFAULTS)
    assert lifted is not None and lifted.level == "add"
    # Stat by stat, makes and attempts alike: the percentages are unchanged.
    assert lifted.rates == {k: pytest.approx(v * 1.15) for k, v in line.items()}
    assert lifted.to_dict() == {"factor": 1.15, "level": "add", "signals": {"minutes": 0.5}}
    assert lf.lifts({10: flag("add", surge=SURGE)}, {10: line}, [10, 11], lf.OFF) == {}
    assert set(lf.lifts({10: flag("add", surge=SURGE)}, {10: line}, [10, 11], {})) == {10}


# --------------------------------------------------------------------------- the moves
def thin_league() -> mv.MoveProblem:
    """Three of mine every day; a candidate (10) with the same games, a little below my weakest
    (3) on the projection and above 3 on a line lifted by half."""
    sched = schedule({"MIN": list(range(28))})
    roster = [player(1, "MIN"), player(2, "MIN"), player(3, "MIN")]
    cands = [player(10, "MIN")]
    rate = {1: rates(1.2), 2: rates(1.0), 3: rates(0.6), 10: rates(0.5)}
    opponent = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.0), 21: rates(0.9), 22: rates(0.8)}
    p = build(roster, cands, rate, sched, opponent, [opponent])
    return replace(p, season_value={1: 3.0, 2: 2.0, 3: 0.5, 10: 0.4})


def lifted(p: mv.MoveProblem, factor: float = 1.5, n: int = 1) -> mv.MoveProblem:
    lift = lf.Lift(factor, "add", {"minutes": 0.6}, {k: v * factor for k, v in p.rates[10].items()})
    return replace(p, lifted={10: lift}, marginal=mv.marginal_of(p, n))


def test_a_flagged_add_is_recommended_for_a_marginal_drop_where_the_plain_line_was_not():
    p = thin_league()
    plain = mv.Evaluator(p)
    assert plain.gain("week", [mv.Move(10, 3)]) < 0
    assert mv.recommend(plain, "week", [10], min_gain=0.01).moves == ()
    up = lifted(p)
    assert up.marginal == frozenset({3})
    ev = mv.Evaluator(up)
    assert ev.gain("week", [mv.Move(10, 3)]) > 0 and ev.gain("three", [mv.Move(10, 3)]) > 0
    rec = mv.recommend(ev, "week", [10], min_gain=0.01)
    assert [pm.move for pm in rec.moves] == [mv.Move(10, 3)]
    # The base is the plain roster's: no move, no lift.
    assert ev.base == plain.base


def test_the_same_add_for_a_drop_not_marginal_is_scored_on_his_plain_line():
    up = lifted(thin_league())
    plain = mv.Evaluator(thin_league())
    ev = mv.Evaluator(up)
    assert not mv.is_lifted(up, 10, 2) and mv.is_lifted(up, 10, 3) and mv.is_lifted(up, 10, None)
    assert ev.gain("week", [mv.Move(10, 2)]) == pytest.approx(plain.gain("week", [mv.Move(10, 2)]))
    # My marginal players: the lowest by the keep rule's value, the kept left out.
    assert mv.marginal_of(replace(up, kept=frozenset({3})), 1) == frozenset({2})
    assert mv.marginal_of(up, 0) == frozenset()


def test_the_guards_rest_of_the_season_and_the_logs_take_the_lift():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    up = lifted(p)
    plain_ros, up_ros = sm.ros_of(built_of(p), 10, 3), sm.ros_of(built_of(up), 10, 3)
    assert plain_ros is not None and up_ros is not None
    assert plain_ros["value"] < 0 < up_ros["value"]
    # Not marginal: the plain figure.
    assert sm.ros_of(built_of(up), 10, 2) == sm.ros_of(built_of(p), 10, 2)


def test_the_payload_and_the_log_record_the_lift_on_a_lifted_move_only():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    built = built_of(lifted(p))
    out = sm._payload(built)
    (row,) = out["recommended"]["week"]["moves"]
    assert (row["add"], row["drop"]) == (10, 3)
    assert row["lift"] == {"factor": 1.5, "level": "add", "signals": {"minutes": 0.6}}
    assert out["candidates"]["10"]["week"]["lift"]["factor"] == 1.5
    assert out["lift"] == {
        "knobs": lf.knobs_of(built.knobs),
        "marginal": [3],
        "lifted": {"10": row["lift"]},
    }
    e = sd.moves_entry(built, out, datetime(2026, 10, 26, 12, tzinfo=UTC))
    assert e["sets"][0]["moves"][0]["lift"] == row["lift"] and e["lift"] == out["lift"]
    plain = sm._payload(built_of(p))
    assert "lift" not in plain and plain["recommended"]["week"]["moves"] == []
    e = sd.moves_entry(built_of(p), plain, datetime(2026, 10, 26, 12, tzinfo=UTC))
    assert "lift" not in e


def test_no_lift_gives_todays_payload_byte_for_byte():
    p = replace(thin_league(), season_end=thin_league().horizons["three"][-1].days[-1])
    empty = replace(p, lifted={}, marginal=frozenset({3}))
    a, b = sm._payload(built_of(p)), sm._payload(built_of(empty))
    for out in (a, b):
        out["search"].pop("seconds")
    assert json.dumps(a) == json.dumps(b)


# --------------------------------------------------------------------------- the knobs
def test_the_knob_file_takes_the_lift_knobs_within_their_bounds_and_the_simulator_never_sees_them():
    raw = {
        "in_force": {"lift_weight_add": 0.3, "lift_marginal": 2},
        "leagues": {"100": {"lift_floor_watch": 0.9, "lift_marginal": 1.5, "lift_weight_watch": 0}},
    }
    knobs, problems = pg.knob_file(raw)
    assert knobs["in_force"] == {"lift_weight_add": 0.3, "lift_marginal": 2}
    assert knobs["leagues"]["100"] == {"lift_weight_watch": 0}
    assert problems == [
        "league 100: lift_floor_watch 0.9 is above its maximum 0.5",
        "league 100: lift_marginal 1.5 is not a whole number",
    ]
    force = pg.in_force_for(knobs, "100")
    assert lf.knobs_of(force) == {
        **lf.DEFAULTS,
        "lift_weight_add": 0.3,
        "lift_marginal": 2,
        "lift_weight_watch": 0,
    }
    # Outside the live knobs and their defaults: the simulator's arms name every live knob.
    assert not set(lf.KNOBS) & {*pg.LIVE_KNOBS, *pg.DEFAULTS}


# --------------------------------------------------------------------------- the route
def bump(client) -> None:  # noqa: F811
    state = season_dir(client.data_dir, LEAGUE) / STATE
    t = state.stat().st_mtime_ns + 10**9
    os.utime(state, ns=(t, t))


def test_every_lift_knob_at_zero_gives_todays_moves_byte_for_byte(client, monkeypatch):  # noqa: F811
    # The add reserve (#436) exempts a must-add's add, so flagging every candidate changes its
    # record: off here, the lift alone on test (its own zero test is in test_reserve).
    monkeypatch.setattr(rs, "DEFAULTS", dict(rs.OFF))
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    flagged: dict[int, fl.Flag] = {}
    seen: list[int] = []
    real = season_flags.league_flags

    def league_flags(*args, **kw):
        players, _, inputs = real(*args, **kw)
        seen.append(len(flagged))
        return players, dict(flagged), inputs

    monkeypatch.setattr(season_flags, "league_flags", league_flags)
    before = client.get(f"/seasons/{LEAGUE}/moves").json()
    cands = [int(k) for k in before["candidates"]]
    assert cands and "lift" not in before
    # Every candidate flagged must-add on a surge.
    flagged.update({c: flag("must-add", surge=SURGE) for c in cands})
    knob_file = season_knobs.autopilot_dir(client.data_dir) / season_knobs.KNOBS_FILE
    knob_file.parent.mkdir(parents=True, exist_ok=True)
    knob_file.write_text(json.dumps({"in_force": dict(lf.OFF)}))
    bump(client)
    off = client.get(f"/seasons/{LEAGUE}/moves").json()
    # The solve read the flags, every candidate flagged.
    assert seen and seen[-1] == len(cands)
    for out in (before, off):
        out["search"].pop("seconds")
        out.pop("stale", None)
    assert json.dumps(off, sort_keys=True) == json.dumps(before, sort_keys=True)
    # The code's first guesses: every candidate lifted by the must-add floor.
    knob_file.unlink()
    bump(client)
    on = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert on["lift"]["knobs"] == dict(lf.DEFAULTS)
    assert {int(k) for k in on["lift"]["lifted"]} == set(cands)
    assert all(
        x["factor"] == 1.25 and x["level"] == "must-add" for x in on["lift"]["lifted"].values()
    )
    assert len(on["lift"]["marginal"]) <= lf.DEFAULTS[lf.MARGINAL]


def test_a_flag_read_that_fails_logs_a_line_and_the_moves_solve_without_the_lift(
    client,  # noqa: F811
    monkeypatch,
    caplog,
):
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})

    calls = []

    def broken(*args, **kw):
        calls.append(1)
        raise RuntimeError("no buzz")

    monkeypatch.setattr(season_flags, "league_flags", broken)
    bump(client)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        r = client.get(f"/seasons/{LEAGUE}/moves")
    assert r.status_code == 200 and "lift" not in r.json() and calls
    assert any(
        f"moves of league {LEAGUE} solve without the lift: its flags failed: no buzz" in m
        for m in caplog.messages
    )
