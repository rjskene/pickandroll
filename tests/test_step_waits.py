"""A week plan's later step waits only on the earlier steps it does not stand without (#364,
item 4). On 2026-11-11 in 224319, step 2 (a claim on 10288 for 10443) waited for step 1 (a
no-drop claim on 6408) to land at 4 am, so it was placed at 09:15 and cleared a day late. A step
now stands without an earlier one when it keeps its room (it does not drop that step's add, and
the steps up to it still fit with that step left out) and its worth (it adds at least
``min_gain`` on the plan's score with that step not made): it goes in the night it is due. A
step that waits keeps the gate, and a claim behind a claim says it clears later than its day.
Nothing here opens a page.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pickandroll.api.season_moves import MIN_GAIN
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season import plans as pl
from tests.test_moves_queue import DAY, PLAN, TYPICAL, league_day, planned, step
from tests.test_pending import one_spot

WEIGHT = 0.33  # the queue's three weeks weight


class Worth:
    """A value by add: each add's own worth, and ``pair`` more for two adds made together."""

    def __init__(self, problem, own, pair=None):
        self.problem, self.own, self.pair = problem, own, pair or {}
        self.base = {h: 0.0 for h in problem.horizons}

    def value(self, key, moves):
        adds = {m.add for m in moves}
        v = sum(self.own.get(a, 0.0) for a in adds)
        return v + sum(b for (x, y), b in self.pair.items() if x in adds and y in adds)

    def gain(self, key, moves):
        return self.value(key, moves)


def steps_of(*moves):
    return [pl.Step(m, DAY, {}) for m in moves]


# --------------------------------------------------------------------------- what a step waits on
def test_the_224319_shape_a_claim_with_its_own_drop_never_waits_on_a_no_drop_claim():
    p, _ = one_spot()  # one active spot open: step 1 takes it
    ev = Worth(p, {10: 0.3, 11: 0.2})
    s = steps_of(mv.Move(10), mv.Move(11, 2))
    assert pl.waits_on(ev, s, 1, WEIGHT, MIN_GAIN) == []


def test_an_independent_step_with_its_own_room_and_worth_waits_on_nothing():
    p, _ = one_spot()
    ev = Worth(p, {10: 0.3, 11: 0.2})
    assert pl.waits_on(ev, steps_of(mv.Move(10, 3), mv.Move(11, 2)), 1, WEIGHT, MIN_GAIN) == []


def test_a_step_that_drops_an_earlier_steps_add_waits_on_it():
    p, _ = one_spot()
    ev = Worth(p, {10: 0.3, 11: 0.5})
    assert pl.waits_on(ev, steps_of(mv.Move(10, 3), mv.Move(11, 10)), 1, WEIGHT, MIN_GAIN) == [0]


def test_a_step_worth_less_than_min_gain_without_the_earlier_one_waits_on_it():
    p, _ = one_spot()
    # 11 is worth something only beside 10: alone it adds 0.005 on the plan's score.
    ev = Worth(p, {10: 0.3, 11: 0.005 / (1 + WEIGHT)}, pair={(10, 11): 0.2})
    assert pl.waits_on(ev, steps_of(mv.Move(10, 3), mv.Move(11, 2)), 1, WEIGHT, MIN_GAIN) == [0]


# --------------------------------------------------------------------------- the queue and the pass
def plan_of(*specs):
    """A logged week plan of claims: (add, drop, after) per step, all dated and clearing 10-23."""
    n = len(specs)
    steps = []
    for i, (add, drop, after) in enumerate(specs):
        s = step(add, drop, 0.5, "2026-10-23", 0, n)
        s["after"], s["plan"] = after, {**s["plan"], "step": i + 1}
        steps.append(s)
    return planned(*steps)


CLAIMS = {111: ("W", date(2026, 10, 23)), 112: ("W", date(2026, 10, 23))}
EVENING = datetime(2026, 10, 22, 3, 40, tzinfo=UTC)  # the 22:40 pass, 10-21 Central


def tonight(e):
    out = qa.queue_of(league_day(e, availability=CLAIMS), DAY, PLAN, TYPICAL, None)
    merged = qa.merge([], out, DAY, "09:00", EVENING - timedelta(hours=8))
    return merged, qa.due(merged, EVENING)


def test_a_step_that_waits_on_nothing_is_placed_the_same_night_as_the_step_before_it():
    merged, due = tonight(plan_of((111, None, []), (112, 212, [])))
    assert [e["reason"] for e in merged] == [None, None] and merged[1]["after"] == []
    assert [e["add"] for e in due] == [111, 112]


def test_a_step_that_waits_keeps_the_gate_and_says_it_clears_later_than_its_day():
    merged, due = tonight(plan_of((111, 211, []), (112, 111, [0])))
    assert [e["add"] for e in due] == [111]
    w = qa.waits(merged[1], {e["id"]: e for e in merged})
    assert w["slips"] is True and w["text"] == (
        "waits for step 1 to land: placed after its 4 am run, it clears later than 2026-10-23"
    )


def test_a_free_agent_step_behind_a_claim_waits_without_a_slip():
    e = plan_of((111, 211, []), (112, 111, [0]))
    out = qa.queue_of(
        league_day(e, availability={111: CLAIMS[111], 112: ("FA", None)}), DAY, PLAN, TYPICAL, None
    )
    merged = qa.merge([], out, DAY, "09:00", EVENING - timedelta(hours=8))
    w = qa.waits(merged[1], {x["id"]: x for x in merged})
    assert w["slips"] is False and w["text"] == "waits for step 1 to land"


def test_an_entry_logged_before_still_waits_on_every_earlier_step():
    merged, due = tonight(plan_of((111, None, []), (112, 212, [0])))
    assert [e["add"] for e in due] == [111]
    assert merged[1]["after"] == [merged[0]["id"]]
