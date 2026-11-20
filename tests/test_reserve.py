"""The add reserve and the no-quick-re-cut rule (#436, the user's ruling of 2026-11-19): before the
week's release day the week's last adds go only to a move that clears the price, carries an
``add`` or ``must-add`` flag, or is one of the user's picks; a player added within the re-cut days
is dropped only for more than the price, or when out. Every league here is made up
(``test_moves``'s, ``test_season_guard``'s, ``test_moves_queue``'s and ``test_season``'s
fixtures)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from pickandroll.api import season_decisions as sd
from pickandroll.api import season_knobs
from pickandroll.api import season_moves as sm
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season import picks as pk
from pickandroll.season import progress as pg
from pickandroll.season import reserve as rs

from .test_lift import bump
from .test_moves import WEEKS, build, player, rates, schedule
from .test_moves_queue import DAY, PLAN, TYPICAL, WEEK, entry, league_day, move, reasons
from .test_season import LEAGUE, client, fixture_names, projection_csv  # noqa: F401
from .test_season_guard import built_of, drop_clocks

MON, FRI = WEEKS[0][0], WEEKS[0][4]
#: Between the two moves' worth on the queue's score (4.4 and 0.35).
PRICE = 1.0
OBJECTIVE = sm.plan_value(0.33, False)


def two_adds(limit: int | None = 2, status: str | None = None) -> mv.MoveProblem:
    """Two moves worth making: 10 for 3, a large gain, and 11 for 2, a small one; ``limit`` adds
    in the first week."""
    sched = schedule({"MIN": list(range(28))})
    roster = [player(1, "MIN"), player(2, "MIN", status), player(3, "MIN")]
    cands = [player(10, "MIN"), player(11, "MIN")]
    rate = {1: rates(1.0), 2: rates(0.5), 3: rates(0.4), 10: rates(1.5), 11: rates(0.62)}
    opp = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.0), 21: rates(0.9), 22: rates(0.7)}
    limits = [] if limit is None else [mv.AddLimit(WEEKS[0][0], WEEKS[0][6], limit)]
    return build(roster, cands, rate, sched, opp, [opp], limits=limits)


BIG, SMALL = mv.Move(10, 3), mv.Move(11, 2)


def solved(p: mv.MoveProblem, rule: rs.ReserveRule | None) -> list[mv.Move]:
    ev = mv.Evaluator(p)
    allowed = rs.guard(ev, rule, OBJECTIVE)
    rec = mv.recommend(ev, "three", [10, 11], min_gain=0.01, allowed=allowed)
    return sorted((pm.move for pm in rec.moves), key=lambda m: m.add)


def rule(p, today=MON, knobs=None, price=PRICE, flags=None, recent=None):
    return rs.rule_of(p, today, knobs, price, flags or {}, recent or {})


# --------------------------------------------------------------------------- the reserve
def test_the_reserve_holds_the_weeks_last_add_for_a_small_gain_before_the_release_day():
    p = two_adds()
    assert solved(p, None) == [BIG, SMALL]
    r = rule(p)
    assert r is not None and (r.week, r.reserved, r.price) == (p.limits[0], 1, PRICE)
    assert solved(p, r) == [BIG]
    why = rs.refusal(mv.Evaluator(p), r, OBJECTIVE, [BIG, SMALL])
    assert why is not None and (why.rule, why.move) == (rs.RESERVE, SMALL)
    assert 0 < why.adds < PRICE
    # Within the adds the reserve leaves free, a small gain is never refused.
    assert rs.refusal(mv.Evaluator(p), r, OBJECTIVE, [SMALL]) is None
    # With three adds left, both fit beside the one held.
    assert solved(two_adds(3), rule(two_adds(3))) == [BIG, SMALL]


def test_a_large_gain_a_strong_flag_or_the_release_day_frees_the_held_add():
    p = two_adds()
    # A price below the small move's worth.
    assert solved(p, rule(p, price=0.1)) == [BIG, SMALL]
    # An add flagged add or must-add uses the reserve whatever it gains.
    for level in ("add", "must-add"):
        assert solved(p, rule(p, flags={11: level})) == [BIG, SMALL]
    # From the release day on the reserve is free: the re-cut days alone stay.
    assert rule(p, today=FRI).week is None and rule(p, today=FRI - timedelta(days=1)).week
    assert rule(p, today=MON, knobs={rs.RESERVE_RELEASE: "monday"}).week is None
    assert solved(p, rule(p, today=FRI)) == [BIG, SMALL]
    # No limit: nothing to hold. Both rules off: no rule at all.
    assert rule(two_adds(None)).week is None
    assert rule(p, knobs=rs.OFF) is None
    assert rule(p, knobs={**rs.OFF, rs.RECUT_DAYS: 1}).days == 1
    # The knob's price stands in for the typical gain.
    assert rule(p, knobs={rs.RESERVE_PRICE: 0.25}).price == 0.25


def test_a_move_lifted_by_a_watch_flag_gets_no_exemption():
    p = two_adds()
    r = rule(p, flags={11: "watch"})
    assert r is not None and r.exempt == frozenset()
    assert solved(p, r) == [BIG]


# --------------------------------------------------------------------------- the re-cut
def test_a_player_added_within_the_recut_days_is_kept_against_a_small_gain():
    p = two_adds(None)
    r = rule(p, recent={2: MON - timedelta(days=1)})
    assert r is not None and r.week is None and r.recent == {2: MON - timedelta(days=1)}
    assert solved(p, r) == [BIG]
    why = rs.refusal(mv.Evaluator(p), r, OBJECTIVE, [BIG, SMALL])
    assert why is not None and (why.rule, why.move) == (rs.RECUT, SMALL)
    # A large gain re-cuts the player.
    assert solved(p, rule(p, price=0.1, recent={2: MON})) == [BIG, SMALL]
    # Added three days ago or more: out of the window.
    assert rule(p, recent={2: MON - timedelta(days=3)}).recent == {}
    assert rule(p, knobs={rs.RECUT_DAYS: 5}, recent={2: MON - timedelta(days=3)}).recent
    # A player who is not mine any more is no re-cut.
    assert rule(p, recent={99: MON}).recent == {}


def test_a_chain_that_re_cuts_its_own_add_pays_the_price():
    """The master's review: a set's earlier add counts as added on its move's day, so a two-step
    stream dropping it within the re-cut days is refused at a small gain, allowed above."""
    p = two_adds(None)
    step1, step2 = mv.Move(11, 2, MON), mv.Move(10, 11, MON + timedelta(days=2))
    chain = [step1, step2]
    assert mv.feasible(p, chain)
    ev = mv.Evaluator(p)
    worth = rs.worths(ev, OBJECTIVE, chain)
    # Step 1 is needed by step 2: its worth is what it adds before its day.
    assert worth[0] == pytest.approx(OBJECTIVE(ev, [step1]) - OBJECTIVE(ev, []))
    high = rule(p, price=worth[1] + 0.5)
    why = rs.refusal(ev, high, OBJECTIVE, chain)
    assert why is not None and (why.rule, why.move) == (rs.RECUT, step2)
    assert rs.refusal(ev, rule(p, price=worth[1] - 0.5), OBJECTIVE, chain) is None
    # Three days apart: out of the window. A streamer who is out: never refused.
    later = [step1, mv.Move(10, 11, MON + timedelta(days=3))]
    assert rs.refusal(ev, high, OBJECTIVE, later) is None
    out = replace(p, candidates=(player(10, "MIN"), player(11, "MIN", "O")))
    assert rs.refusal(mv.Evaluator(out), high, OBJECTIVE, chain) is None
    # The re-cut days at 0: no chain check.
    assert rs.refusal(ev, replace(high, days=0), OBJECTIVE, chain) is None


def test_a_recent_add_who_is_out_may_be_dropped_for_any_gain():
    p = two_adds(None, status="O")
    r = rule(p, recent={2: MON})
    assert r is not None and r.out == frozenset({2})
    assert SMALL in solved(p, r)
    assert rs.refusal(mv.Evaluator(p), r, OBJECTIVE, [BIG, SMALL]) is None


def test_added_within_keeps_each_players_latest_add_of_the_window():
    adds = [(2, MON - timedelta(days=5)), (2, MON - timedelta(days=1)), (3, None), (4, MON)]
    assert rs.added_within(adds, MON, 3) == {2: MON - timedelta(days=1), 4: MON}
    assert rs.added_within(adds, MON, 0) == {}


# --------------------------------------------------------------------------- the moves card
def test_the_payload_logs_the_rule_and_the_set_it_held_back():
    p = replace(two_adds(), season_end=WEEKS[-1][-1])
    built = built_of(p, reserve=rule(p))
    out = sm._payload(built)
    three = out["recommended"]["three"]
    assert [(m["add"], m["drop"]) for m in three["moves"]] == [(10, 3)]
    held = three["reserve"]
    assert held["held_back"] and held["rule"] == rs.RESERVE
    assert [(m["add"], m["drop"]) for m in held["moves"]] == [(10, 3), (11, 2)]
    assert held["refused"]["add"] == 11 and held["price"] == PRICE
    assert held["forgone"]["three"] > 0
    assert out["reserve"] == {
        "knobs": rs.knobs_of(built.knobs),
        "week": {"start": MON.isoformat(), "end": WEEKS[0][6].isoformat(), "adds": 2},
        "reserved": 1,
        "price": PRICE,
        "exempt": [],
        "recent": {},
        "out": [],
    }
    # The log carries each move's worth on the queue's score, the queue's number.
    e = sd.moves_entry(built, out, datetime(2026, 10, 26, 12, tzinfo=UTC))
    logged = {s["key"]: s for s in e["sets"]}
    assert logged["three"]["reserve"]["adds"] == sm.reserve_adds(built, mv.Evaluator(p), [BIG])
    assert logged["three"]["reserve"]["held_back"] and e["reserve"] == out["reserve"]
    assert [r["add"] for r in logged["week"]["reserve"]["adds"]] == [
        m["add"] for m in out["recommended"]["week"]["moves"]
    ]
    # The week plans keep the rule: no plan takes both adds (the small one on the held add).
    plans = (out.get("week_plans") or {}).get("plans") or []
    assert plans
    for plan in plans:
        assert not {10, 11} <= {s["add"] for s in plan["steps"]}, plan


def test_no_rule_gives_todays_payload_byte_for_byte():
    p = replace(two_adds(), season_end=WEEKS[-1][-1])
    a, b = sm._payload(built_of(p)), sm._payload(built_of(p, reserve=None))
    for out in (a, b):
        drop_clocks(out)
    assert json.dumps(a) == json.dumps(b) and "reserve" not in a
    assert "reserve" not in a["recommended"]["three"]


# --------------------------------------------------------------------------- the queue
def reserve_record(**over):
    return {
        "knobs": {**rs.DEFAULTS},
        "week": {"start": WEEK[0].isoformat(), "end": WEEK[1].isoformat(), "adds": 2},
        "reserved": 1,
        "price": 0.3,
        "exempt": [],
        "recent": {},
        "out": [],
        **over,
    }


def test_the_queue_holds_the_weeks_last_add_and_a_quick_recut_for_a_small_gain():
    e = {**entry(move(101, 201, 0.9), move(102, 202, 0.2)), "reserve": reserve_record()}
    day = league_day(e, adds_left={WEEK: 2}, cap=3)
    out = qa.queue_of(day, DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, None, 1), (102, qa.RESERVE_HELD, None)]
    assert out[1]["reserve"] == {"worth": 0.2, "price": 0.3, "days": 3}
    assert "reserve" not in out[0]
    # The solve's own number when logged (the master's review): 101's worth on the queue's
    # score was 0.1, so 101 is the one held, whatever its three-week gain.
    e["sets"][1]["reserve"] = {
        "adds": [{"add": 101, "drop": 201, "adds": 0.1}, {"add": 102, "drop": 202, "adds": 0.5}]
    }
    out = qa.queue_of(day, DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, None, 1), (102, None, 2)]
    e["sets"][1]["reserve"]["adds"][1]["adds"] = 0.25
    out = qa.queue_of(day, DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, None, 1), (102, qa.RESERVE_HELD, None)]
    assert out[1]["reserve"]["worth"] == 0.25
    # An add flagged add may use it; a larger gain clears it; three adds left leave it free.
    flagged = {**e, "reserve": reserve_record(exempt=[102])}
    assert (
        reasons(
            qa.queue_of(league_day(flagged, adds_left={WEEK: 2}, cap=3), DAY, PLAN, TYPICAL, None)
        )[1][1]
        is None
    )
    assert (
        reasons(qa.queue_of(league_day(e, adds_left={WEEK: 3}, cap=3), DAY, PLAN, TYPICAL, None))[
            1
        ][1]
        is None
    )
    # The re-cut: 202 added two days ago and not out.
    recut = {
        **entry(move(101, 201, 0.9), move(102, 202, 0.2)),
        "reserve": reserve_record(week=None, reserved=0, recent={"202": "2026-10-19"}),
    }
    out = qa.queue_of(league_day(recut, cap=3), DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, None, 1), (102, qa.RECUT_HELD, None)]
    out_now = {**recut, "reserve": {**recut["reserve"], "out": [202]}}
    assert [
        x["queued"] for x in qa.queue_of(league_day(out_now, cap=3), DAY, PLAN, TYPICAL, None)
    ] == [True, True]


def test_a_pick_is_never_held_by_the_reserve():
    pick = {**move(103, 203, 0.01), "score": 0.01}
    e = {
        **entry(move(101, 201, 0.2)),
        "reserve": reserve_record(recent={"203": "2026-10-20"}),
    }
    e["sets"].append({"key": pk.PICK, "moves": [pick]})
    out = qa.queue_of(league_day(e, adds_left={WEEK: 2}, cap=3), DAY, PLAN, TYPICAL, None)
    by_add = {x["add"]: x for x in out}
    assert by_add[103]["queued"] and "reserve" not in by_add[103]
    # The pick took one of the two adds: the set's move would use the held one.
    assert by_add[101]["reason"] == qa.RESERVE_HELD


# --------------------------------------------------------------------------- the knobs
def test_the_knob_file_takes_the_rules_knobs_within_their_bounds_and_the_simulator_never_sees_them():
    raw = {
        "in_force": {"reserve_adds": 2, "reserve_release": "thursday", "reserve_price": None},
        "leagues": {"100": {"recut_days": 15, "reserve_adds": 1.5, "reserve_release": "fri"}},
    }
    knobs, problems = pg.knob_file(raw)
    assert knobs["in_force"] == raw["in_force"]
    assert "recut_days" not in knobs["leagues"].get("100", {})
    assert "league 100: recut_days 15 is above its maximum 14" in problems
    assert "league 100: reserve_adds 1.5 is not a whole number" in problems
    assert any("reserve_release 'fri' is not one of" in x for x in problems)
    assert not set(rs.KNOBS) & {*pg.LIVE_KNOBS, *pg.DEFAULTS}
    assert (
        rs.refused(rs.RECUT_DAYS, None) is not None and rs.refused(rs.RESERVE_PRICE, None) is None
    )


# --------------------------------------------------------------------------- the route
def test_both_rules_at_zero_give_todays_moves_byte_for_byte(client, monkeypatch):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    # Before #436: no rule on any solve.
    monkeypatch.setattr(rs, "rule_of", lambda *a, **kw: None)
    before = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert "reserve" not in before
    monkeypatch.undo()
    knob_file = season_knobs.autopilot_dir(client.data_dir) / season_knobs.KNOBS_FILE
    knob_file.parent.mkdir(parents=True, exist_ok=True)
    knob_file.write_text(json.dumps({"in_force": dict(rs.OFF)}))
    bump(client)
    off = client.get(f"/seasons/{LEAGUE}/moves").json()
    for out in (before, off):
        drop_clocks(out)
        out.pop("stale", None)
    assert json.dumps(off, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_the_service_prices_the_rule_on_yesterdays_typical_gain(client):  # noqa: F811
    svc = client.app.state.seasons
    today = DAY
    # No armed league logged a move: the plan floor of the knobs.
    assert svc._typical("categories", today, {"plan_floor_cats": 0.2}) == 0.2
    assert (today, "categories") in svc._typicals
