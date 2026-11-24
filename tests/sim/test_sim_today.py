"""A league whose free-agent adds play the day they are made (#172, PR today): the league rule
``lineup_from`` (``tomorrow`` by default, ``today``), the seat's problem built as the live build
builds one (a free agent effective today, the weeks' own add windows), the day's adds landed
once every seat has decided and before the lineups, a claim decided as before, and the audit's
rule in the place of ``lands_next_day``. Made-up leagues, fixed seeds. Each season's test names
its time below."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from pickandroll.sim import audit, nopeek, policy, shapes
from pickandroll.sim import bid_policy as bp
from pickandroll.sim import cli as ss
from pickandroll.sim import opponents as op
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv, wk
from pickandroll.sim.shapes import CONTINUOUS, DROPPED, TODAY, TOMORROW
from pickandroll.sim.state import WON, Claim, Waiting, initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_no_peek import SEED, WEIGHTS, recorded
from tests.sim.test_sim_bracket_run import points_league, two_rounds
from tests.sim.test_sim_counts import MON as MONDAY_ONE
from tests.sim.test_sim_counts import Script
from tests.sim.test_sim_faab import morning as faab_morning
from tests.sim.test_sim_rules_run import (  # noqa: F401
    WHEN,
    pinned_clock,
    replay,
    spec,
    wire,
    written,
)
from tests.sim.test_sim_split import armed, second_of, variant_of, world_of
from tests.sim.test_sim_waivers import contested

DAY = timedelta(1)
FORMATS = ("one_win", "each_category")


def same_day(setup):
    return replace(setup, lineup_from=TODAY)


def spots_of(setup):
    return setup.spots(), Counter(setup.roster_slots)


def played(setup, w, variants, plans=None):
    """The variants through ``w``: the results and each day's record by (day, variant)."""
    recs: dict = {}
    results = rn.simulate(
        setup, w, variants, plans, on_day=lambda r: recs.__setitem__((r.day, r.variant), r)
    )
    return results, recs


# --------------------------------------------------------------------------- the rule's words
def test_the_rule_is_tomorrow_by_default_and_today_is_named_and_said():
    plain = shapes.LeagueRules()
    assert plain.lineup_from == TOMORROW and not plain.same_day
    assert "lineup_from" not in plain.payload()
    assert "same day" not in plain.label() and "next day" not in plain.label()
    today = shapes.LeagueRules(lineup_from=TODAY)
    assert today.same_day and today.payload()["lineup_from"] == TODAY
    assert today.label().endswith(shapes.LINEUP_WORDS[TODAY])
    waivers = shapes.LeagueRules(waivers="priority", lineup_from=TODAY)
    assert waivers.same_day and shapes.LINEUP_WORDS[TODAY] in waivers.label()
    # Under continuous waivers every add is a claim: the rule is named and moves nothing.
    claims = shapes.LeagueRules(waivers="faab", waiver_rule=CONTINUOUS, lineup_from=TODAY)
    assert not claims.same_day and claims.payload()["lineup_from"] == TODAY
    with pytest.raises(ValueError, match="lineup rule 'noon'"):
        shapes.LeagueRules(lineup_from="noon")


def test_the_flag_is_parsed_by_its_own_words():
    assert shapes.parse_lineup_from(None) == TOMORROW
    assert shapes.parse_lineup_from(" Today ") == TODAY
    assert shapes.parse_lineup_from("tomorrow") == TOMORROW
    with pytest.raises(ValueError, match="--lineup-from noon: one of tomorrow, today"):
        shapes.parse_lineup_from("noon")


def test_the_setup_lands_a_free_agents_add_the_same_day_and_a_claim_as_before():
    setup = make_setup(teams=4)
    assert setup.lineup_from == TOMORROW and setup.lands_after == DAY and not setup.same_day
    today = same_day(setup)
    assert today.same_day and today.lands_after == timedelta(0)
    for waivers in ("priority", "faab"):
        dropped = replace(today, waivers=waivers, waiver_rule=DROPPED)
        assert dropped.same_day and dropped.lands_after == timedelta(0)
        claims = replace(dropped, waiver_rule=CONTINUOUS)
        assert not claims.same_day and claims.lands_after == DAY
    with pytest.raises(ValueError, match="lineup rule 'noon'"):
        rn.replay_setup(2024, {}, {}, {}, (setup.start, setup.season_end), {}, lineup_from="noon")


def test_the_payload_names_each_waiver_kind_under_the_rule():
    assert policy.executions_of("none") == "free_agents_next_day"
    assert policy.executions_of("none", same_day=True) == "free_agents_same_day"
    assert policy.executions_of("priority", DROPPED, True) == (
        "free_agents_same_day_claims_by_priority"
    )
    assert policy.executions_of("faab", DROPPED, True) == (
        "free_agents_same_day_claims_by_sealed_bids"
    )
    # Under continuous waivers there is no free agent: the claims' own names.
    for waivers in ("priority", "faab"):
        assert policy.executions_of(waivers, CONTINUOUS, True) == policy.executions_of(
            waivers, CONTINUOUS
        )
    names = {
        policy.executions_of(w, r, d)
        for w in ("none", "priority", "faab")
        for r in (DROPPED, CONTINUOUS)
        for d in (False, True)
        if w != "none" or r == DROPPED
    }
    assert len(names) == 8


# --------------------------------------------------------------------------- the seat's problem
def built_on(setup, day, team: int = 1, state=None):
    state = replace(state or initial(setup), day=day)
    return policy.problem_of(setup, state, team, dict(KNOBS), setup.projection, {}, {})


def test_a_free_agent_is_effective_today_and_a_dropped_player_on_his_clear_date():
    """The live build sets a free agent's ``effective`` to its first day and a waiver player's
    to the later of it and his clear date (``api.season_moves.build``): in a same-day league the
    seat's problem is that build. Under the default rule every day is a day later; a claim's day
    is the same under both."""
    base = replace(make_setup(teams=4), waivers="priority", waiver_days=2)
    day = base.start + 2 * DAY
    s = initial(base)
    x, f = sorted(s.pool)[:2]
    s = replace(s, waivers={x: Waiting(day + 2 * DAY, 2)})
    later = built_on(base, day, state=s).problem
    today = built_on(same_day(base), day, state=s).problem
    assert later.first_day == today.first_day == day
    assert later.effective[f] == day + DAY and today.effective[f] == day
    assert later.effective[x] == today.effective[x] == day + 2 * DAY
    assert {k for k, d in today.effective.items() if d != later.effective[k]} == set(
        today.effective
    ) - {x}
    assert built_on(base, day).lands == DAY and built_on(same_day(base), day).lands == timedelta(0)


def test_under_continuous_waivers_the_problem_is_the_default_rules():
    for waivers in ("priority", "faab"):
        base = replace(make_setup(teams=4), waivers=waivers, waiver_rule=CONTINUOUS)
        day = base.start + 3 * DAY
        a, b = built_on(base, day), built_on(same_day(base), day)
        assert a.problem == b.problem and a.lands == b.lands == DAY


def test_the_weeks_add_windows_are_the_weeks_own_days_under_the_rule():
    """On a week's last day: under the default rule a move made today lands tomorrow and spends
    this week's adds (the window is this week's days shifted by one); under the rule it plays
    today and spends this week's adds (the window is the week's own days), and next week's
    window opens on its Monday."""
    base = make_setup(teams=4)
    week = base.calendar.weeks[1]
    sunday = week.end
    later = built_on(base, sunday).problem.limits
    today = built_on(same_day(base), sunday).problem.limits
    assert (later[0].start, later[0].end) == (sunday, sunday + DAY)
    assert (today[0].start, today[0].end) == (sunday, sunday)
    nxt = base.calendar.weeks[2]
    assert (later[1].start, later[1].end) == (nxt.start + DAY, nxt.end + DAY)
    assert (today[1].start, today[1].end) == (nxt.start, nxt.end)
    assert later[0].adds == today[0].adds == base.max_weekly_adds


def sunday_claim(waivers: str, rule: str, used: int = 2, in_flight: int = 0):
    """A Sunday of week two in a league of two adds a week: team 1 has ``used`` adds charged to
    the week and ``in_flight`` claims in flight charged to week three, and queues a claim on a
    player who clears on Monday. The setup, the state after the queue, the Monday and the weeks."""
    base = replace(make_setup(teams=4, max_weekly_adds=2), waivers=waivers, waiver_days=2)
    setup = replace(base, lineup_from=rule)
    spots, _ = spots_of(setup)
    week, nxt = setup.calendar.weeks[1], setup.calendar.weeks[2]
    sunday, monday = week.end, nxt.start
    s = initial(setup)
    x, *others = sorted(s.pool)
    roster = [k for k, _ in setup.rosters[1]]
    flight = tuple(
        Claim(mv.Move(others[i], roster[-2 - i]), sunday - DAY, monday, nxt.number)
        for i in range(in_flight)
    )
    s = replace(
        s,
        day=sunday,
        adds_used={1: used},
        waivers={x: Waiting(monday, 2), **{k: Waiting(monday, 3) for k in others[:in_flight]}},
        claims={1: flight} if flight else {},
    )
    claim = policy.Decision((mv.Move(x, roster[-1]),))
    return setup, policy.queue(s, 1, claim, 1, 2, False, spots, setup), monday, week, nxt, x


@pytest.mark.parametrize("waivers", ["priority", "faab"])
def test_a_claim_that_clears_on_a_monday_is_the_new_weeks_under_the_rule(waivers):
    """The lead's decision (PR today): in a same-day league a claim is charged to the week it
    clears in, as the seat's problem weighs it (his effective day falls in the next week's
    window, the weeks' own days). A seat at its week's limit on a Sunday places a claim that
    clears on Monday, charged to the new week; the problem built that Sunday puts the claim's
    day in the new week's window. Under the default rule the same claim is the ending week's and
    the queue refuses it (``NO_ADDS``), as before."""
    setup, after, monday, week, nxt, x = sunday_claim(waivers, TODAY)
    (placed,) = after.claims[1]
    assert placed.move.add == x and placed.clears == monday and placed.week == nxt.number
    p = built_on(setup, week.end, state=replace(after, claims={})).problem
    assert p.effective[x] == monday and p.limits[1].start == monday
    _, before, *_ = sunday_claim(waivers, TOMORROW)
    assert before.claims.get(1, ()) == ()


@pytest.mark.parametrize("waivers", ["priority", "faab"])
def test_a_seat_whose_new_week_is_full_of_claims_in_flight_is_refused_under_the_rule(waivers):
    """The queue's ``NO_ADDS`` reads the week the claim is charged to: the new week's claims in
    flight. With two in flight charged to it (the limit) the Monday claim is refused; with one it
    is placed, the new week's second."""
    _, full, *_ = sunday_claim(waivers, TODAY, in_flight=2)
    assert len(full.claims[1]) == 2
    _, one, _, _, nxt, x = sunday_claim(waivers, TODAY, in_flight=1)
    assert [c.week for c in one.claims[1]] == [nxt.number, nxt.number]
    assert one.claims[1][-1].move.add == x


@pytest.mark.parametrize("waivers", ["priority", "faab"])
def test_a_claim_that_clears_inside_the_week_is_charged_as_before(waivers):
    """A claim placed on a Wednesday on a player who clears on Friday is that week's under both
    rules, and a seat at its limit has it refused under both."""
    for rule in (TOMORROW, TODAY):
        setup = replace(make_setup(teams=4, max_weekly_adds=2), waivers=waivers, waiver_days=2)
        setup = replace(setup, lineup_from=rule)
        spots, _ = spots_of(setup)
        week = setup.calendar.weeks[1]
        wednesday, friday = week.start + 2 * DAY, week.start + 4 * DAY
        s = initial(setup)
        x = min(s.pool)
        s = replace(s, day=wednesday, waivers={x: Waiting(friday, 2)})
        claim = policy.Decision((mv.Move(x, setup.rosters[1][-1][0]),))
        room = policy.queue(replace(s, adds_used={1: 1}), 1, claim, 1, 2, False, spots, setup)
        assert [c.week for c in room.claims[1]] == [week.number], rule
        full = policy.queue(replace(s, adds_used={1: 2}), 1, claim, 1, 2, False, spots, setup)
        assert full.claims.get(1, ()) == (), rule


def test_the_weekly_rule_counts_a_claim_in_the_week_it_is_charged_to():
    """``weekly_adds`` follows ``Claim.week``: on the Sunday a claim charged to the new week is
    not the ending week's (two landed on a cap of two holds), and on a Monday a claim in flight
    charged to that week is counted with its adds, so two landed and the claim break the rule."""
    setup, after, monday, week, *_ = sunday_claim("priority", TODAY)
    sunday = audit.Day(week.end, 0, after, {}, {})
    assert list(audit.weekly_adds(setup, sunday, None)) == []
    flight = replace(after, day=monday, adds_used={1: 2})
    assert list(audit.weekly_adds(setup, audit.Day(monday, 0, flight, {}, {}), None)) == [
        (1, "3 adds this week on a cap of 2")
    ]
    landed = replace(flight, claims={})
    assert list(audit.weekly_adds(setup, audit.Day(monday, 0, landed, {}, {}), None)) == []


@pytest.mark.parametrize("waivers", ["priority", "faab"])
def test_a_monday_claim_lands_as_the_new_weeks_first_add_and_a_held_return_is_no_add(waivers):
    """The runner under the rule, two scripted teams, a cap of one add a week. Team 1 adds a free
    agent on week one's Tuesday (its week is full); team 2 adds one on Saturday and its drop waits
    until Monday; on Sunday team 1 claims him, charged to week two. On Monday the week starts
    over before the morning: the claim lands as week two's first add, so team 1's free agent that
    Monday is refused (week two has none left), and team 2's held player who comes back that
    morning is no add; team 2's free agent added that Monday lands that day, week two's. The
    counts charge both Monday adds to week two, and the audit finds nothing."""
    mon = MONDAY_ONE
    setup = make_setup(
        teams=2, spots=6, pool=6, weeks=2, playoff_weeks=1, max_weekly_adds=1, held_slots=("IL",)
    )
    free = sorted(setup.pool)
    hurt = free[-1]
    rosters = dict(setup.rosters)
    rosters[2] = (*rosters[2], (hurt, "IL"))
    setup = replace(
        setup,
        rosters=rosters,
        pool=tuple(free[:-1]),
        statuses={hurt: "O"},
        returns={hurt: mon + 7 * DAY},
        waivers=waivers,
        waiver_days=2,
        lineup_from=TODAY,
    )
    one = [k for k, _ in setup.rosters[1]]
    two = [k for k, _ in setup.rosters[2] if k != hurt]
    f1, f2, f3, f4 = free[:4]
    sunday, monday = mon + 6 * DAY, mon + 7 * DAY
    plans = {
        1: Script(
            (
                (mon + DAY, (mv.Move(f1, one[0]),)),
                (sunday, (mv.Move(two[0], one[1]),)),
                (monday, (mv.Move(f3, one[2]),)),
            )
        ),
        2: Script(((mon + 5 * DAY, (mv.Move(f2, two[0]),)), (monday, (mv.Move(f4, two[1]),)))),
    }
    (res,), recs = played(setup, replay_of(setup, 2, 0), [plans])
    assert not res.breaches, res.breaches[:2]
    (claim,) = recs[(sunday, 0)].claims[1]
    assert claim.move.add == two[0] and claim.clears == monday and claim.week == 2
    rec = recs[(monday, 0)]
    assert [(r.team, r.add, r.outcome) for r in rec.cleared] == [(1, two[0], WON)]
    assert hurt in rec.state.active(2) or hurt not in rec.state.pool
    assert rec.state.adds_used.get(1, 0) == 1 and rec.queued.get(1, ()) == ()
    assert f3 not in rec.state.active(1)
    # Team 2's free agent that Monday lands that day as week two's only add: the held
    # player back that morning took none.
    assert rec.landed[2] == (mv.Move(f4, two[1]),) and rec.state.adds_used.get(2, 0) == 1
    # The counts charge each Monday add to week two (the claim at the morning, the free agent
    # at the day's landing): one add in each week for each team, each week at the cap.
    for t in (1, 2):
        assert res.counts[t]["adds_per_week"] == 1.0 and res.counts[t]["weeks_at_cap"] == 1.0, t


def test_a_plans_step_of_a_free_agent_is_due_today_and_a_claims_on_its_clear_date():
    setup = replace(make_setup(teams=4), waivers="priority", waiver_days=2)
    day = setup.start + DAY
    s = replace(initial(setup), day=day)
    x, f = sorted(s.pool)[:2]
    s = replace(s, waivers={x: Waiting(day + 3 * DAY, 2)})
    assert policy.due_by(s, f, day + DAY) == day + DAY
    assert policy.due_by(s, f, day + DAY, day) == day
    assert policy.due_by(s, x, day + DAY, day) == policy.due_by(s, x, day + DAY) == day + 3 * DAY


def test_the_surrogate_and_the_ranking_count_a_candidates_games_from_the_day_he_plays():
    """Read through the ranking's one swap: under the rule a candidate's games are counted from
    today, so on a day his team plays he is worth that game more than under the default rule.
    The ranking's choice is held against a hand count on both rules."""
    base = make_setup(teams=4)
    for setup in (base, same_day(base)):
        day = setup.start + 2 * DAY
        built = built_on(setup, day)
        start = day + setup.lands_after
        assert built.lands == setup.lands_after
        p = built.problem
        games = {
            k: sum(1 for d in p.horizons["week"][0].days if d >= start and m.nba_team in p.schedule.get(d, ()))
            for k, m in p.candidates
        }  # fmt: skip
        decision = policy.ranking(built)
        if decision.moves:
            add = decision.moves[0].add
            best = max(p.value.get(k, 0.0) * games[k] for k, _ in p.candidates)
            assert p.value.get(add, 0.0) * games[add] == best


def test_a_plans_step_dated_tomorrow_waits_for_tomorrow_under_the_rule():
    """An arm that executes its plan: under the rule a step of a free agent dated today is sent
    today and one dated tomorrow is not (it is sent tomorrow, to land then); under the default
    rule a step dated tomorrow is sent today, to land tomorrow."""
    base = make_setup(teams=4)
    spots, _ = spots_of(base)
    day = base.start + DAY
    f, g = sorted(initial(base).pool)[:2]
    one, two = base.rosters[1][-1][0], base.rosters[1][-2][0]
    plan = (mv.Move(f, one, day), mv.Move(g, two, day + DAY))
    sent = {}
    for setup in (base, same_day(base)):
        s = replace(initial(setup), day=day)
        s = policy.queue(s, 1, policy.Decision(plan=plan), 2, 4, True, spots, setup)
        sent[setup.lineup_from] = [m.add for m in s.pending[1]]
    assert sent == {TOMORROW: [f, g], TODAY: [f]}


def test_the_surrogates_pool_and_the_rankings_swap_count_games_from_the_day_he_plays():
    """The surrogate's candidates are the best by value times games this week from the day a
    candidate would first play, and so is the ranking's add: under the rule from today, under
    the default rule from tomorrow. Each is held to a hand count on both rules, on a day (found
    in the first week, asserted) where the two rules' pools differ."""
    base = make_setup(teams=4, pool=12)
    fields = replace(policy.DEFAULT_FIELDS, pool=3)

    def hand(built, day):
        p = built.problem
        days = [d for d in p.horizons["week"][0].days if d >= day]
        games = {
            k: sum(1 for d in days if m.nba_team in p.schedule.get(d, ())) for k, m in p.candidates
        }
        order = sorted(
            p.candidates, key=lambda m: (-p.value.get(m[0], 0.0) * max(1, games[m[0]]), m[0])
        )
        best = max(p.candidates, key=lambda m: (p.value.get(m[0], 0.0) * games[m[0]], -m[0]))
        return [k for k, _ in order[: fields.pool]], best[0], games

    differ = 0
    for i in range(6):
        pools = {}
        for setup in (base, same_day(base)):
            day = setup.start + i * DAY
            built = built_on(setup, day)
            pool, best, games = hand(built, day + setup.lands_after)
            assert policy._surrogate_pool(built, fields) == pool, (i, setup.lineup_from)
            swap = policy.ranking(built)
            if swap.moves and games[best] > 0:
                assert swap.moves[0].add == best, (i, setup.lineup_from)
            pools[setup.lineup_from] = pool
        differ += pools[TODAY] != pools[TOMORROW]
    assert differ, "no day of the first week where the two rules' pools differ"


# --------------------------------------------------------------------------- the day's landing
def test_two_seats_on_one_free_agent_the_same_day_the_rotation_decides_and_the_loser_keeps_its_drop():
    """Both seats decide on the morning's wire and queue the same free agent; the day's landing
    takes them in the day's rotation: the first gets him today, the other's move is lost (its
    drop stays) and counted gone. The audit's rule finds nothing on that day."""
    setup = same_day(make_setup(teams=4))
    spots, counts = spots_of(setup)
    day = setup.start
    s = replace(initial(setup), day=day)
    f = min(s.pool)
    d2, d3 = setup.rosters[2][-1][0], setup.rosters[3][-1][0]
    for team, drop in ((2, d2), (3, d3)):
        s = policy.queue(s, team, policy.Decision((mv.Move(f, drop),)), 1, 4, False, spots, setup)
    decided = s
    assert decided.pending[2] == (mv.Move(f, d2),) and decided.pending[3] == (mv.Move(f, d3),)
    after = policy.land(s, [3, 4, 1, 2], spots, counts, arrived=True)
    on = {t: {k for k, _ in r} for t, r in after.rosters.items()}
    assert f in on[3] and d3 not in on[3] and d3 in after.pool
    assert f not in on[2] and d2 in on[2]
    assert after.gone_by.get(2, 0) == 1 and after.executed_by.get(3, 0) == 1
    assert after.adds_used.get(3, 0) == 1 and after.pending == {}
    today = audit.Day(day, 0, after, {}, {}, decided=decided)
    assert list(audit.lands_same_day(setup, today, None)) == []


def test_an_arm_at_its_weeks_limit_sends_no_add_on_the_weeks_last_day():
    setup = same_day(make_setup(teams=4, max_weekly_adds=2))
    spots, _ = spots_of(setup)
    sunday = setup.calendar.weeks[0].end
    s = replace(initial(setup), day=sunday, adds_used={1: 2, 2: 1})
    f, g = sorted(s.pool)[:2]
    one, two = setup.rosters[1][-1][0], setup.rosters[2][-1][0]
    s = policy.queue(s, 1, policy.Decision((mv.Move(f, one),)), 1, 2, False, spots, setup)
    s = policy.queue(s, 2, policy.Decision((mv.Move(g, two),)), 1, 2, False, spots, setup)
    assert s.pending[1] == () and s.pending[2] == (mv.Move(g, two),)


def test_a_seat_at_five_adds_in_a_week_sends_no_sixth_and_the_audits_weekly_rule_holds_it():
    """The user's league allows five adds a week (``--league adds=5``): a seat with five charged
    this week queues no sixth, one with four queues its fifth, which lands the same day, and the
    audit's weekly rule finds nothing on that day and names a sixth."""
    setup = same_day(make_setup(teams=4, max_weekly_adds=5))
    spots, counts = spots_of(setup)
    day = setup.start + DAY
    s = replace(initial(setup), day=day, adds_used={1: 5, 2: 4})
    f, g = sorted(s.pool)[:2]
    one, two = setup.rosters[1][-1][0], setup.rosters[2][-1][0]
    s = policy.queue(s, 1, policy.Decision((mv.Move(f, one),)), 1, 5, False, spots, setup)
    s = policy.queue(s, 2, policy.Decision((mv.Move(g, two),)), 1, 5, False, spots, setup)
    assert s.pending[1] == () and s.pending[2] == (mv.Move(g, two),)
    after = policy.land(s, setup.teams, spots, counts, arrived=True)
    assert g in {k for k, _ in after.rosters[2]} and not after.pending.get(2)
    clean = audit.Day(day, 0, after, {}, {1: {}}, decided=s)
    assert list(audit.weekly_adds(setup, clean, None)) == []
    sixth = replace(after, adds_used={**after.adds_used, 2: after.adds_used.get(2, 0) + 1})
    found = list(audit.weekly_adds(setup, replace(clean, state=sixth), None))
    assert found == [(2, "6 adds this week on a cap of 5")]


def dropped_the_same_day(setup, after, winner, x):
    """The clear morning ``after`` in a same-day league: ``winner``, which took ``x`` by a claim
    that morning, drops him the same day for a free agent. The state the seats decided on and
    the state after the day's landing."""
    setup = same_day(setup)
    spots, counts = spots_of(setup)
    f = min(k for k in after.pool if k not in after.waivers)
    decided = policy.queue(after, winner, policy.Decision((mv.Move(f, x),)), 1, 4, False, spots, setup)  # fmt: skip
    assert decided.pending[winner] == (mv.Move(f, x),)
    landed = policy.land(decided, setup.teams, spots, counts, arrived=True)
    assert x not in landed.active(winner) and f in landed.active(winner)
    return setup, decided, landed


@pytest.mark.parametrize("kind", ["priority", "faab"])
def test_a_claim_won_in_the_morning_and_dropped_the_same_day_is_held_to_the_morning(kind):
    """A team wins a claim in the morning and, the same day, drops him for a free agent (a
    market rival's drop is its weakest, which a player it took among the best few can be): the
    claim rules hold the winner to its roster after the morning (``Day.decided``), as the default
    rule's audit holds it on the day of the claim, before a move it queues lands the next
    morning. Read on the state after the day's landing, the old reading, the rule finds the
    breach the look's dry run met on real data."""
    if kind == "priority":
        setup, before, after, x, _ = contested()
        winner, rule = 3, audit.claim_priority
    else:
        setup, before, after, x, _, _ = faab_morning()
        winner, rule = 2, audit.bid_order
    setup, decided, landed = dropped_the_same_day(setup, after, winner, x)
    prior = audit.Day(before.day, 0, before, {}, {})
    today = audit.Day(after.day, 0, landed, {}, {}, decided=decided)
    assert list(rule(setup, today, prior)) == []
    old = list(rule(setup, replace(today, decided=None), prior))
    assert old == [(winner, f"won claim on player {x} not on its roster")]


# --------------------------------------------------------------------------- the league's adds
def test_a_league_of_five_adds_a_week_parses_and_the_grids_axis_does_not_move():
    """``--league adds=`` takes any positive whole count or ``none`` (PR today): the user's
    league allows five. The other keys take the grid's values as before, the grid's own adds axis
    is the same, and a one-shape grid's visit rule plays every seat in turn as before."""
    five = shapes.parse_league("adds=5")
    assert five == replace(shapes.FIXED, weekly_adds=5)
    assert five.label() == "12 teams, 13 slots, 5 adds a week, 6 playoff teams over 3 weeks"
    assert shapes.parse_league("adds=none").weekly_adds is None
    assert shapes.parse_league("teams=10,adds=12").weekly_adds == 12
    assert [shapes.parse_league(f"adds={a}").weekly_adds for a in (2, 3, 4)] == [2, 3, 4]
    assert shapes.FULL.adds == (2, 3, 4, None) and len(shapes.FULL.shapes) == 72
    grid = shapes.one("league", five)
    assert [shapes.visit(i, grid) for i in range(3)] == [shapes.Visit(five, 0, i) for i in range(3)]
    with pytest.raises(ValueError, match="the grid's teams are 10, 12, 14"):
        shapes.parse_league("teams=11,adds=5")


@pytest.mark.parametrize("value", ["0", "-1", "five", "2.5", ""])
def test_adds_of_zero_a_negative_or_a_word_are_refused_by_name(value):
    why = f"--league adds={value}: a positive whole count of adds a week, or none"
    with pytest.raises(ValueError, match=re.escape(why)):
        shapes.parse_league(f"adds={value}")


# --------------------------------------------------------------------------- the audit's rule
def test_the_rule_takes_the_place_of_lands_next_day():
    plain = [r.name for r in audit.rules_of()]
    today = [r.name for r in audit.rules_of(same_day=True)]
    assert today == [n if n != "lands_next_day" else "lands_same_day" for n in plain]
    assert audit.Auditor(same_day(make_setup())).rules == audit.rules_of(
        same_day=True, bracket=True
    )
    assert audit.Auditor(make_setup()).rules == audit.rules_of(bracket=True)
    claims = replace(same_day(make_setup()), waivers="priority", waiver_rule=CONTINUOUS)
    assert audit.Auditor(claims).rules == audit.rules_of("priority", CONTINUOUS, True)


def landed_day():
    """A same-day league's first day: team 1 queues a free agent for its last player, and the
    day's landing makes it. The state before the landing, the one after, and the move."""
    setup = same_day(make_setup(teams=4))
    spots, counts = spots_of(setup)
    s = replace(initial(setup), day=setup.start)
    f, drop = min(s.pool), setup.rosters[1][-1][0]
    move = mv.Move(f, drop)
    decided = policy.queue(s, 1, policy.Decision((move,)), 1, 4, False, spots, setup)
    return setup, decided, policy.land(decided, setup.teams, spots, counts, arrived=True), move


def test_the_audits_rule_finds_nothing_on_a_clean_landing_and_each_break_by_its_clause():
    setup, decided, after, move = landed_day()
    day = setup.start
    clean = audit.Day(day, 0, after, {}, {1: {}}, decided=decided)
    assert list(audit.lands_same_day(setup, clean, None)) == []
    # Under the default rule's audit the same day breaks: the add joined with no move queued
    # the day before.
    assert [w for _, w in audit.lands_next_day(setup, clean, None)] == [
        f"player {move.add} joined without a move queued the day before"
    ]
    # A player who joined with no move queued today.
    other = min(after.pool)
    joined = replace(after, rosters={**after.rosters, 2: (*after.rosters[2], (other, "BN"))})
    found = list(audit.lands_same_day(setup, replace(clean, state=joined), None))
    assert found == [(2, f"player {other} joined without a move queued today or a claim clearing")]
    # A move queued today whose add is not on the roster, and no loss counted.
    lost = replace(decided, pending={1: (mv.Move(other, setup.rosters[1][0][0]),)})
    found = list(audit.lands_same_day(setup, replace(clean, decided=lost), None))
    assert (1, "1 of today's adds not on the roster, 0 lost at the landing") in found
    # The player a landed move dropped starts for that team the same day.
    started = replace(clean, starters={1: {move.drop: "UTIL"}})
    found = list(audit.lands_same_day(setup, started, None))
    assert found == [(1, f"player {move.drop} starts the day his drop landed")]


# --------------------------------------------------------------------------- seasons
def market(rate: float = 0.3):
    return op.of({"kind": "market", "rate": rate}, KNOBS, 0.1)


#: The made-up user's league: four seats, two IL slots, waivers by priority with only a dropped
#: player waiting, two waiver days, five adds a week, one win a matchup, a final.
def users_league():
    return replace(
        make_setup(teams=4, held_slots=("IL", "IL"), max_weekly_adds=5),
        waivers="priority",
        waiver_days=2,
    )


def kinds():
    """The league rules the rule is crossed with: the plain league, two held slots, points,
    waivers by priority and by FAAB (only a dropped player waits), every category counted, and
    the user's own (:func:`users_league`)."""
    plain = make_setup(teams=4)
    return {
        "plain": plain,
        "held": make_setup(teams=4, held_slots=("IL", "IL")),
        "points": points_league(),
        "priority": replace(plain, waivers="priority", waiver_days=2),
        "faab": replace(plain, waivers="faab", waiver_days=2),
        "each_category": every_category(plain),
        "users": users_league(),
    }


ON_WEEK = bp.of({"week": 0.5})


def seats():
    """The seat kinds the rule is crossed with: each tier, the queue's rule, the weighted set
    with a plan drawn, a stash threshold, a season term, and (in a FAAB league) a ``bid`` that
    weighs the week. A seat that executes its plan beside its set on plan floors of -1 is
    played by :func:`test_an_arm_that_executes_its_plan_beside_its_set_plays_steps_the_same_day`."""
    return {
        "exact": op.Seat("E", "exact", dict(KNOBS)),
        "surrogate": op.Seat("S", "surrogate", dict(KNOBS)),
        "ranking": op.Seat("R", "ranking", dict(KNOBS)),
        "queue": op.Seat("Q", "exact", dict(KNOBS), policy.QUEUE),
        "weighted": op.Seat("W", "exact", dict(KNOBS), policy.WEIGHTED),
        "stash": op.Seat("T", "exact", {**KNOBS, "stash_threshold": 0.0}),
        "term": op.Seat("V", "surrogate", {**KNOBS, "season_weight": 0.0005}),
        "bid_week": op.Seat("B", "exact", dict(KNOBS), bid=ON_WEEK),
    }


@cache
def season(kind: str, seat: str, rule: str, rivals: str = "market", seed: int = 5):
    setup = kinds()[kind] if seat != "bid_week" else kinds()["faab"]
    setup = replace(setup, lineup_from=rule)
    rival = market() if rivals == "market" else op.Mirror(dict(KNOBS))
    variant = {**{t: rival for t in setup.teams}, 1: seats()[seat]}
    (res,), recs = played(setup, replay_of(setup, seed, 0), [variant])
    return setup, res, recs


def same_day_landings(recs, team: int):
    """The days on which ``team``'s add queued that day landed that day, each with the moves."""
    return {day: rec.landed[team] for (day, _), rec in sorted(recs.items()) if rec.landed.get(team)}


def check_same_day(setup, res, recs, me: int = 1):
    """A season under the rule: the audit (with its rule) finds nothing; every add that landed
    was queued the same day, by its own team; the seat moved, and one of its adds started on the
    day it was made (a found path, asserted)."""
    assert audit.LANDS_SAME_DAY in audit.Auditor(setup).rules
    assert not res.breaches, res.breaches[:2]
    for (day, _), rec in recs.items():
        for t, moves in rec.landed.items():
            assert set(moves) <= set(rec.queued.get(t, ())), (day, t)
    landed = same_day_landings(recs, me)
    assert landed, "the seat landed no add"
    started = [
        (day, m.add)
        for day, moves in landed.items()
        for m in moves
        if m.add in recs[(day, 0)].starters.get(me, {})
    ]
    return landed, started


@pytest.mark.parametrize("kind", sorted(kinds()))
def test_every_league_kind_plays_the_rule_clean_and_the_rule_changes_the_season(kind):
    """The exact seat (the three weeks' set, its plan drawn and not executed) among market
    rivals, under each league kind: the audit finds nothing, every add landed the day it was
    queued, and the season under the rule is not the default rule's (an add plays a day sooner,
    so a day's lineups differ). About 2 s each."""
    setup, res, recs = season(kind, "exact", TODAY)
    check_same_day(setup, res, recs)
    _, before, then = season(kind, "exact", TOMORROW)
    assert not before.breaches
    assert any(recs[k].starters != then[k].starters for k in recs), "no lineup moved"


@pytest.mark.parametrize("seat", sorted(seats()))
def test_every_seat_kind_plays_the_rule_in_the_users_league(seat):
    """Each seat kind in the made-up user's league (a ``bid`` on the week in the FAAB league):
    the audit finds nothing and the seat's adds land the day they are made. About 2 s each."""
    setup, res, recs = season("users", seat, TODAY)
    check_same_day(setup, res, recs)


def test_mirror_rivals_follow_the_league_rule():
    """Mirror rivals in every other seat: each rival's adds land the day they are made too."""
    setup, res, recs = season("users", "surrogate", TODAY, "mirror")
    check_same_day(setup, res, recs)
    for t in (2, 3, 4):
        assert same_day_landings(recs, t), t


def test_an_add_starts_on_the_day_it_is_made_and_a_day_later_under_the_default_rule():
    """A found path (the plain league, the exact seat, seed 5): an add of the seat's starts on
    the day it was made under the rule; under the default rule an add starts at the earliest the
    morning after it was queued, never the day it was made."""
    setup, res, recs = season("plain", "exact", TODAY)
    _, started = check_same_day(setup, res, recs)
    assert started, "no same-day add started"
    _, _, then = season("plain", "exact", TOMORROW)
    for (day, _), rec in then.items():
        for t, moves in rec.queued.items():
            on = {k for k, _ in rec.state.rosters.get(t, ())}
            assert not {m.add for m in moves} & on, (day, t)


@pytest.mark.parametrize("waivers", ["priority", "faab"])
def test_under_continuous_waivers_the_rule_moves_nothing(waivers):
    """Every add is a claim: the season under the rule is the default rule's, day for day."""
    base = replace(make_setup(teams=4), waivers=waivers, waiver_days=2, waiver_rule=CONTINUOUS)
    out = []
    for rule in (TOMORROW, TODAY):
        setup = replace(base, lineup_from=rule)
        variant = {**{t: market() for t in setup.teams}, 1: seats()["exact"]}
        out.append(played(setup, replay_of(setup, 5, 0), [variant]))
    (a,), ra = out[0]
    (b,), rb = out[1]
    assert not a.breaches and a == b and ra == rb


def test_an_arm_that_executes_its_plan_beside_its_set_plays_steps_the_same_day():
    """An exact arm that executes its plan beside its set on plan floors of -1 (every plan a
    step can take is drawn), in the made-up user's league counting every category (a one-win
    league's plan floor is the engine's own, so the knob is read only there): the audit finds
    nothing, and a step of a plan, not a move of the set, landed the day it was queued. A found
    path: seed 7, on which four such steps land (on seeds 5 to 8 one to four do; in the one-win
    league no plan is drawn). About 3 s."""
    setup = same_day(every_category(users_league()))
    knobs = {**KNOBS, "plan_floor_cats": -1.0, "plan_floor_points": -1.0}
    variant = {**{t: market() for t in setup.teams}, 1: op.Seat("P", "exact", knobs)}
    (res,), recs = played(setup, replay_of(setup, 7, 0), [variant], [True])
    landed, _ = check_same_day(setup, res, recs)
    steps = 0
    for day, moves in landed.items():
        decision = recs[(day, 0)].decisions[1]
        plan = {(m.add, m.drop) for m in decision.plan}
        own = {(m.add, m.drop) for m in decision.moves}
        steps += sum(1 for m in moves if (m.add, m.drop) in plan - own)
    assert steps, "no plan's step landed"


def test_a_pair_with_a_split_seat_plays_the_rule_on_its_own_table():
    """A rule that reads a seat's own forecaster, on a pair with a split seat (a ``blend`` arm
    and a ``yahoo`` arm, each in seat 1 in turn): the audit finds nothing and the split seat's
    adds land the day they are made. About 3 s."""
    base, lines = two_rounds()
    setup = same_day(base)
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    arms = armed(("Y", "yahoo", None), ("L", "blend", 0.25))
    w = world_of(setup, lines, first, second_of(first), arms)
    variants = [variant_of(setup, arms, {1: name}) for name in ("Y", "L")]
    results, recs = played(setup, w, variants)
    for vi, res in enumerate(results):
        assert not res.breaches, res.breaches[:2]
        for (day, v), rec in recs.items():
            if v == vi:
                for t, moves in rec.landed.items():
                    assert set(moves) <= set(rec.queued.get(t, ())), (day, t)
    # The split seat moved in at least one of its two arms, and the day's landing made it.
    assert any(r.landed.get(1) for r in recs.values())


@dataclass(frozen=True)
class SplitScript(Script):
    """A scripted seat that holds a split table (``forecaster``)."""

    forecaster: str | None = None


def test_a_split_seats_same_day_add_is_started_on_the_table_read_after_the_landing():
    """A split seat (``yahoo``) reads a player on no roster on the second's line and a rostered
    one on the first's. The recorded league starts three of each team's four (PG, C, Util). On
    the first day from the second on that three of team 1's players of one kind play (two slots
    hold them), team 1 adds a free agent of that kind who plays that day, whom the second rates
    at four times his line and the first at a twentieth, dropping one of the three. On the
    morning's table he starts; on the table read on the rosters after the landing he is the
    least of the three, and the day's lineup, set on that table, sits him (a hand-built day: the
    two lineups differ, asserted). About 2 s."""
    base, lines = recorded()
    setup = same_day(base)
    one = [k for k, _ in setup.rosters[1]]

    def playing(d):
        return [k for k in one if lines.get(k, {}).get(d)]

    def kinds(d):
        return {setup.players[k].positions for k in playing(d)}

    day = next(d for d in setup.days[1:] if len(playing(d)) == 3 and len(kinds(d)) == 1)
    (kind,) = kinds(day)
    f = min(
        k for k in setup.pool if lines.get(k, {}).get(day) and setup.players[k].positions == kind
    )
    d = playing(day)[0]
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    second = second_of(first)
    first[f] = {s: v * 0.05 for s, v in first[f].items()}
    second[f] = {s: v * 4.0 for s, v in setup.projection[f].items()}
    arms = armed(("Y", "yahoo", None))
    label = arms["Y"].forecaster
    w = world_of(setup, lines, first, second, arms)
    seat = SplitScript(((day, (mv.Move(f, d),)),), forecaster=label)
    variant = {**{t: op.Static() for t in setup.teams}, 1: seat}
    (res,), recs = played(setup, w, [variant])
    assert not res.breaches, res.breaches[:2]
    rec = recs[(day, 0)]
    assert rec.holds == {1: label} and rec.landed[1] == (mv.Move(f, d),)
    points = None
    fresh = rn._Tables(w, day, [label], setup.cats, points).of(label, rec.state)[1]
    morning = wk.per_game_values(rec.held[label], setup.cats, points)
    on_fresh = policy.starters_of(setup, rec.state, 1, day, rec.status, fresh)
    on_morning = policy.starters_of(setup, rec.state, 1, day, rec.status, morning)
    assert f in on_morning and f not in on_fresh
    assert dict(rec.starters[1]) == dict(on_fresh)


def test_a_seats_same_day_add_lands_inside_a_bracket_round_and_on_its_first_morning():
    """A made-up league whose last two weeks are a bracket of two rounds for all four, under the
    rule, the exact seat among market rivals. Each round is seeded on its first morning, before
    the seats decide; the seat's adds of the rounds land the day they are made (each in that
    day's queue), one of them on the first round's first day, after its seeding (a found path,
    asserted), and the audit finds nothing. About 2 s."""
    setup = same_day(make_setup(teams=4, weeks=6, playoff_weeks=2, playoff_teams=4))
    first = setup.calendar.weeks[setup.spec.playoff_weeks[0] - 1].start
    variant = {**{t: market() for t in setup.teams}, 1: seats()["exact"]}
    (res,), recs = played(setup, replay_of(setup, 1, 0), [variant])
    assert not res.breaches, res.breaches[:2]
    rounds = set(setup.spec.playoff_weeks)
    days = sorted(
        d for (d, _), r in recs.items() if r.landed.get(1) and setup.week_of(d).number in rounds
    )
    assert days and days[0] == first, days
    for day in days:
        rec = recs[(day, 0)]
        assert set(rec.landed[1]) <= set(rec.queued.get(1, ())), day


def test_a_pair_in_lockstep_is_the_pair_played_apart():
    """The rule is the setup's, the same in every season of a run, so nothing new is keyed:
    a pair played in lockstep (one cache) gives what the same pair played apart gives."""
    setup = same_day(users_league())
    w = replay_of(setup, 5, 0)
    a = rn.Arm("A", "exact", dict(KNOBS), {"kind": "market", "rate": 0.3})
    b = rn.Arm("B", "surrogate", dict(KNOBS), {"kind": "market", "rate": 0.3})
    together = rn.paired(setup, w, a, b, 1)
    apart = rn.paired_apart(setup, w, setup, replay_of(setup, 5, 0), a, b, 1)
    assert together == apart


# --------------------------------------------------------------------------- no peek
def test_no_peek_with_the_rule_on_over_a_day_a_same_day_add_played():
    """The no-peek check on a day on which the seat's add played the day it was made (a found
    day, asserted): with every line from that day on redrawn, no record changes up to and on
    that day (the seat decided on the morning's beliefs, before the day's lines), and the
    records do change after it. About 4 s."""
    base, lines = two_rounds()
    setup = same_day(base)
    variant = {**{t: market() for t in setup.teams}, 1: seats()["exact"]}

    def records_of(these):
        w = rn.replay_world(setup, these, 1, SEED, 0, WEIGHTS)
        (res,), recs = played(setup, w, [variant])
        assert not res.breaches
        return {at: nopeek.digest(r) for at, r in recs.items()}, recs

    digests, recs = records_of(lines)
    landed = same_day_landings(recs, 1)
    days = [d for d in landed if d >= setup.start + 7 * DAY]
    assert days, "no same-day add from the second week on"
    day = days[0]
    got, _ = records_of(nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    first = nopeek.first_difference(digests, got)
    assert first is not None and first[0] > day


# --------------------------------------------------------------------------- the command
def without_clock(p: dict) -> dict:
    return {k: v for k, v in p.items() if k not in WHEN}


def test_the_lineup_rule_out_of_its_words_is_refused_by_name_before_any_path(wire: Path):  # noqa: F811
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    code, out = replay(wire, *room, "--lineup-from", "noon")
    assert code == 2 and "refused: --lineup-from noon: one of tomorrow, today" in out, out
    assert "tasks (" not in out


def test_rule_1_with_tomorrow_named_nothing_moves(wire: Path):  # noqa: F811
    """Rule 1: ``--lineup-from tomorrow`` named and nothing named give one payload: the league
    block's rules name no lineup rule, no note says one, the execution model and the audit's
    rules are the default rule's."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--waivers", "priority")
    runs = []
    for extra in ((), ("--lineup-from", "tomorrow")):
        code, out = replay(wire, *room, *extra)
        assert code == 0, out
        runs.append(written(out))
    one, two = runs
    assert without_clock(one) == without_clock(two)
    assert "lineup_from" not in one["league"]["rules"] and "lineup_note" not in one["league"]
    assert one["executions"] == policy.EXECUTIONS_PRIORITY
    assert "lands_next_day" in [r["name"] for r in one["audit"]["rules"]]


@pytest.mark.parametrize("waivers", ["none", "priority"])
def test_a_same_day_run_records_its_rule_its_model_its_note_and_its_audit(wire: Path, waivers):  # noqa: F811
    """``--lineup-from today``: the line that says the rules says it, the league block's rules
    name it, its note says what it does and does not model, the execution model has a name of
    its own, and the audit holds ``lands_same_day`` in ``lands_next_day``'s place and finds
    nothing."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--lineup-from", "today")
    extra = () if waivers == "none" else ("--waivers", waivers)
    code, out = replay(wire, *room, *extra)
    assert code == 0, out
    rules = shapes.LeagueRules(waivers=waivers, lineup_from=TODAY)
    assert f"league rules, on every path: {rules.label()}" in out
    p = written(out)
    assert p["league"]["rules"] == rules.payload() and p["league"]["rules"]["lineup_from"] == TODAY
    assert p["league"]["lineup_note"] == ss.LINEUP_NOTE
    assert p["executions"] == policy.executions_of(waivers, DROPPED, True)
    names = [r["name"] for r in p["audit"]["rules"]]
    assert "lands_same_day" in names and "lands_next_day" not in names
    assert p["audit"]["paths_voided"] == 0


def test_the_command_plays_the_rule_and_the_setup_it_builds_says_it(wire: Path):  # noqa: F811
    """The rule reaches the season, by what the run did and not by what it names: the same room
    under ``today`` and under ``tomorrow`` gives figures or counts that differ (a found path,
    asserted), and the setup the command builds for a path (``cli.replay_setup_of``) says
    ``today`` and plays the same day, the default rule's setup ``tomorrow``."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1")
    figures = {}
    for rule in (TOMORROW, TODAY):
        code, out = replay(wire, *room, "--lineup-from", rule)
        assert code == 0, out
        p = written(out)
        figures[rule] = (p["results"], p["counts"]["by_season"])
    assert figures[TODAY] != figures[TOMORROW]
    lines, members, scheduled = reader.replay_lines(wire, 2024)
    prior = reader.prior_rates(wire, 2024)
    rules = shapes.LeagueRules(lineup_from=TODAY)
    setup = ss.replay_setup_of(2024, lines, members, scheduled, prior, league_rules=rules)
    assert setup.lineup_from == TODAY and setup.same_day
    plain = ss.replay_setup_of(2024, lines, members, scheduled, prior)
    assert plain.lineup_from == TOMORROW and not plain.same_day


def test_the_users_league_of_five_adds_runs_and_its_record_names_five(wire: Path):  # noqa: F811
    """The user's league on the command line: five adds a week (``--league adds=5``), two IL
    slots, waivers by priority on which only a dropped player waits two days, and adds that play
    the same day. The record names five, the audit (its weekly rule among the rest) finds
    nothing, and zero adds is refused by name before any path."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--league", "adds=5")
    rules = ("--held", "IL=2", "--waivers", "priority", "--waiver-days", "2")
    code, out = replay(wire, *room, *rules, "--lineup-from", "today")
    assert code == 0, out
    p = written(out)
    assert p["league"]["shapes"] == [replace(shapes.FIXED, weekly_adds=5).payload()]
    assert p["league"]["rules"]["lineup_from"] == TODAY and p["league"]["rules"]["held"]
    names = [r["name"] for r in p["audit"]["rules"]]
    assert "weekly_adds" in names and "lands_same_day" in names
    assert p["audit"]["paths_voided"] == 0
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--paths", "1", "--league", "adds=0")
    assert code == 2 and "--league adds=0: a positive whole count of adds a week, or none" in out
    assert "tasks (" not in out


def test_under_continuous_waivers_the_record_says_the_rule_moves_nothing(wire: Path):  # noqa: F811
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--waivers", "faab")
    room += ("--waiver-rule", "continuous", "--lineup-from", "today")
    code, out = replay(wire, *room)
    assert code == 0, out
    p = written(out)
    assert p["league"]["rules"]["lineup_from"] == TODAY
    assert p["league"]["lineup_note"] == ss.LINEUP_NOTE_CONTINUOUS
    assert p["executions"] == policy.EXECUTIONS_CONTINUOUS_FAAB
    assert "lands_next_day" in [r["name"] for r in p["audit"]["rules"]]


def test_the_rule_is_part_of_the_league_kind_and_a_screens_world_names_it_only_when_named():
    """A screen and a tune are held to the league kind (H2's ``league_kind``): a same-day league
    is another kind, the default rule the kind it was. A screen's world records the flag only
    when it is named, so a screen that names none records the world it did before."""
    assert "lineup_from" in ss.KIND_FLAGS and "lineup_from" in ss.SCREEN_WORLD
    assert ss.WORLD_IF_NAMED == ("lineup_from",)
    grid = shapes.FIXED_GRID

    def kind(rule):
        return ss.league_kind(SimpleNamespace(grid=grid, league_rules=shapes.LeagueRules(lineup_from=rule)))  # fmt: skip

    assert kind(TOMORROW) == ss.league_kind(SimpleNamespace(grid=grid, league_rules=shapes.PLAIN))
    assert kind(TODAY) != kind(TOMORROW) and kind(TODAY)["rules"]["lineup_from"] == TODAY


def test_the_version_says_the_rule():
    """``replay_version`` 21 says the rule; no screen version moves: a screen that names no
    lineup rule records the world it did before."""
    why = ss.REPLAY_VERSION_WHY
    assert ss.REPLAY_VERSION >= 21
    assert "21: a league whose free-agent adds play the same day: " in why
    mine = why.split("21: a league whose free-agent adds")[1].split("20: the union pool")[0]
    for said in ("lineup_from", "lands_same_day", "free_agents_same_day", "version 20's"):
        assert said in mine, said
