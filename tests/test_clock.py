"""The pick clock (#66): the plan budget a room's reported clock gives, and the D1 gate read
against the clock each turn ran on, with the 30 s design point beside it. The last test reruns
the 2026-10-14 draft's ledger and skips without it."""

import pytest

from pickandroll.draft.clock import (
    DEFAULT_CLOCK_S,
    acts_at_s,
    d1_limit_s,
    plan_budget,
    price_budget,
)
from pickandroll.fidelity import analyze, markdown, read_events

from .conftest import DATA


def test_the_plan_budget_follows_the_clock_from_the_30_s_design_point():
    assert DEFAULT_CLOCK_S == 30.0
    # clock: plan budget, price limit, D1 limit (pending and misses), when the drafter acts
    table = {
        None: (5.0, 5.0, 11.0, 17.0),  # no clock reported: the design point
        30: (5.0, 5.0, 11.0, 17.0),
        40: (15.0, 10.0, 26.0, 27.0),
        60: (20.0, 10.0, 31.0, 47.0),
        90: (20.0, 10.0, 31.0, 77.0),
    }
    for clock, row in table.items():
        assert (plan_budget(clock), price_budget(clock), d1_limit_s(clock), acts_at_s(clock)) == row
    assert plan_budget(10) == 5.0  # never under the floor
    assert d1_limit_s(60, hit=True) == d1_limit_s(30, hit=True) == 1.0


def _ev(kind, t, **fields):
    return {"type": kind, "t": f"2026-10-01T00:{t // 60:02d}:{t % 60:02d}.000+00:00", **fields}


def ledger(clock=60, attach_clock=None):
    """Two teams, three rounds, slot 1: my picks are 1, 4 and 5. Each turn's reco is ready 9, 20
    and 25 s after its start; each turn reports ``clock`` (None: no clock on the turns)."""
    solve = {} if attach_clock is None else {"solve": {"clock_s": attach_clock}}
    events = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=3, draft_id="c", mode="autopilot", **solve),
        _ev("control", 0, state="armed"),
    ]
    clock_field = {} if clock is None else {"clock_s": clock}

    def turn(k, start, ready, landed):
        events.append(_ev("turn_start", start, overall=k, slot=1, **clock_field))
        events.append(_ev("reco", start + ready, board=k - 1, top_yid=f"y{k}", cands=[f"y{k}"]))
        events.append(_ev("pick_landed", landed, overall=k, yid=f"y{k}", how="row"))
        pick(k, f"y{k}", landed)

    def pick(k, yid, t):
        events.append(_ev("room_pick", t, overall=k, yid=yid, name=f"P{yid}"))
        events.append(_ev("session_pick", t, overall=k, yid=yid))

    turn(1, 10, 9, 20)
    pick(2, "o2", 22)
    pick(3, "o3", 25)
    turn(4, 30, 20, 52)
    turn(5, 53, 25, 79)
    pick(6, "o6", 80)
    return events


def test_d1_is_judged_on_the_clock_the_room_reported():
    card = analyze(ledger(clock=60))
    assert [r["clock_s"] for r in card["rows"]] == [60.0, 60.0, 60.0]
    assert [r["reco_ready_ms"] for r in card["rows"]] == [9000, 20000, 25000]
    gate = card["diagnostics"]["D1_gate"]
    assert gate["room"] == {
        "clocks": [60.0],
        "reported": True,
        "timed": 3,
        "untimed": [],
        "over": [],
        "missed": [],
        "pass": True,
    }
    # At the design point the 20 and 25 s recos are over 11 s and come after the drafter acts.
    assert gate["design"]["over"] == [4, 5] and gate["design"]["missed"] == [4, 5]
    assert gate["design"]["pass"] is False
    md = markdown(card)
    assert "| D1 gate, 3 timed turns | room's clock (60 s) | design point (30 s) |" in md
    assert "| limit: hits / pending and misses | 1 s / 31 s | 1 s / 11 s |" in md
    assert "| over the limit | none | 2: 4, 5 |" in md
    assert "| missed: ready after the drafter acts (47 s / 17 s) | none | 2: 4, 5 |" in md
    assert "| result | pass | **FAIL** |" in md


def test_a_turn_without_a_clock_takes_the_attachs_then_the_design_point():
    card = analyze(ledger(clock=None, attach_clock=60))
    assert [r["clock_s"] for r in card["rows"]] == [60.0, 60.0, 60.0]
    assert card["diagnostics"]["D1_gate"]["room"]["pass"] is True
    # Nothing reported anywhere: the room is judged at 30 s, and the card says no clock came.
    card = analyze(ledger(clock=None))
    room = card["diagnostics"]["D1_gate"]["room"]
    assert room["clocks"] == [30.0] and room["reported"] is False and room["missed"] == [4, 5]
    assert "| D1 gate, 3 timed turns | room's clock (30 s, none reported) |" in markdown(card)
    # A turn on a longer clock than the others widens the column to the range.
    events = ledger(clock=60)
    for e in events:
        if e["type"] == "turn_start" and e["overall"] == 1:
            e["clock_s"] = 30
    card = analyze(events)
    assert card["diagnostics"]["D1_gate"]["room"]["clocks"] == [30.0, 60.0]
    assert "| limit: hits / pending and misses | 1 s / 11-31 s | 1 s / 11 s |" in markdown(card)


def test_the_10_14_draft_misses_no_turn_on_its_own_clock():
    """The night's ledger: every turn reported a 60 s clock. On it no turn missed; at the 30 s
    design point the roster fallback's solves would have missed 4 of the 11 turns."""
    path = DATA / "fidelity" / "31822.jsonl"
    if not path.exists():
        pytest.skip("no 2026-10-14 ledger in data/fidelity")
    card = analyze(read_events(path))
    gate = card["diagnostics"]["D1_gate"]
    assert gate["room"]["clocks"] == [60.0] and gate["room"]["reported"] is True
    assert gate["room"]["over"] == [] and gate["room"]["missed"] == []
    assert gate["room"]["pass"] is True
    assert len(gate["room"]["untimed"]) + gate["room"]["timed"] == 11
    assert gate["design"]["missed"] == [52, 117, 124, 141]
