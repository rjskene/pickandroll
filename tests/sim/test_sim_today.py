"""A league whose free-agent adds play the day they are made (#172, PR today): the league rule
``lineup_from`` (``tomorrow`` by default, ``today``), the seat's problem built as the live build
builds one (a free agent effective today, the weeks' own add windows), the day's adds landed
once every seat has decided and before the lineups, a claim decided as before, and the audit's
rule in the place of ``lands_next_day``. Made-up leagues, fixed seeds. Each season's test names
its time below."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import timedelta
from functools import cache

import pytest

from pickandroll.sim import audit, nopeek, policy, shapes
from pickandroll.sim import bid_policy as bp
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import mv
from pickandroll.sim.shapes import CONTINUOUS, DROPPED, TODAY, TOMORROW
from pickandroll.sim.state import Waiting, initial
from tests.sim.sim_league import KNOBS, every_category, make_setup, replay_of
from tests.sim.test_no_peek import SEED, WEIGHTS
from tests.sim.test_sim_bracket_run import points_league, two_rounds
from tests.sim.test_sim_split import armed, second_of, variant_of, world_of

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
