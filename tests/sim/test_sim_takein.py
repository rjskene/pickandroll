"""SEASON SIM (#172, PR take-in): the live engine's odds calibration of 2026-11-23 taken in.

Three changes, each a knob of the arm with live's value by default:

- #485, ``later_weeks``: every team's later weeks on its whole roster, each player held to his
  told return date and each day's active spots to the most valuable who can play (``legal``), or
  the rule before (``uncapped``);
- #486, ``rate_shrink`` and ``rate_shrink_games``: the seat's beliefs blended toward the recent
  lines it has seen, for the near horizons, every team's week and the seat's lineup, the season's
  figures staying on the beliefs as read;
- #487, ``rate_cv`` and ``miss_rate``: the week's spread widened in every team's week and the
  seat's own weeks in the search.

Here: the recent lines and the blend, the problem's two lines, a returning player in a later
week, the split seats' available side, the rivals, the lineup and the no-peek check with the
blend on. Every change off is ``test_sim_takein_equality``'s; each change in every league is
``test_sim_takein_cross``'s. The knobs' bounds and reads are ``test_sim_knobs``'."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import nopeek, policy
from pickandroll.sim import opponents as op
from pickandroll.sim import run as rn
from pickandroll.sim.engine import rc, spr, wk
from pickandroll.sim.state import initial
from tests.sim.sim_league import KNOBS, arm, make_setup, recorded_lines
from tests.sim.test_no_peek import DAYS, SEED, WEIGHTS, recorded
from tests.sim.test_sim_split import FIRST, SECOND, SOURCES, fixed_of, second_of

#: The take-in's five at live's values (every change on).
ON = {k: policy.KNOB_DEFAULTS[k] for k in policy.TAKEIN_KNOBS}
BLEND = (ON["rate_shrink"], ON["rate_shrink_games"])
RUN = "run"


@pytest.fixture(scope="module")
def made_up():
    """The made-up league of three weeks on its recorded season, path 0 of seed 2, and a day in
    its second week."""
    setup = make_setup(weeks=3)
    lines = recorded_lines(setup, 11)
    w = rn.replay_world(setup, lines, 1, 2, 0)
    day = setup.calendar.weeks[1].start + timedelta(2)
    return setup, lines, w, day


# --------------------------------------------------------------------------- the recent lines
def test_the_recent_lines_are_the_games_played_in_each_window_before_the_day(made_up):
    setup, lines, w, day = made_up
    got = w.recent_on(day)
    assert set(got) == set(rc.WINDOWS)
    seen = 0
    for n in rc.WINDOWS:
        for k, by_day in lines.items():
            games = [x for d, x in by_day.items() if day - timedelta(n) <= d < day]
            if not games:
                assert k not in got[n]
                continue
            g, line = got[n][k]
            assert g == len(games) and list(line) == list(wk.STATS)
            for s in wk.STATS:
                assert line[s] == pytest.approx(sum(x[s] for x in games) / len(games))
            seen += 1
    assert seen > 0
    # A line dated on the day or after it is never read: the same lines before the day give
    # the same windows, whatever the day and after hold.
    later = {
        k: {d: ({s: 99.0 for s in x} if d >= day else x) for d, x in by_day.items()}
        for k, by_day in lines.items()
    }
    assert rn.replay_world(setup, later, 1, 2, 0).recent_on(day) == got
    # Before any game there is nothing to blend.
    assert w.recent_on(setup.days[0]) == {n: {} for n in rc.WINDOWS}


def test_the_blend_is_the_engine_s_own_in_the_line_s_order(made_up):
    _, _, w, day = made_up
    beliefs, windows = w.beliefs_on(day), w.recent_on(day)
    got = policy.blended(beliefs, windows, *BLEND)
    want, used = rc.blend(beliefs, windows, *BLEND)
    assert used and set(got) == set(want) == set(beliefs)
    for k in got:
        assert got[k] == want[k]
        if k in used:
            assert got[k] != beliefs[k]
            assert list(got[k]) == [s for s in dict.fromkeys([*beliefs[k], *wk.STATS])]
        else:
            assert got[k] is beliefs[k]
    # Nothing blended: the beliefs themselves.
    assert policy.blended(beliefs, windows, 0.0, 4.0) is beliefs
    assert policy.blended(beliefs, {n: {} for n in rc.WINDOWS}, *BLEND) is beliefs
    # The world's blended table for the run's forecaster is that one, kept for the day.
    table = w.blended_on(day, None, frozenset(), *BLEND)
    assert table == got and w.blended_on(day, None, frozenset(), *BLEND) is table
    assert w.blended_on(day, None, frozenset(), 0.0, 4.0) is w.beliefs_on(day)
    assert policy.blend_of(KNOBS) is None and policy.blend_of({**KNOBS, **ON}) == BLEND


# --------------------------------------------------------------------------- the problem
def test_the_problem_reads_the_blended_line_near_and_the_line_as_read_for_the_season(made_up):
    setup, _, w, day = made_up
    state = replace(initial(setup), day=day)
    beliefs = w.beliefs_on(day)
    status, returns = w.status_on(day)
    blended = w.blended_on(day, None, rn.rostered_of(state), *BLEND)
    knobs = {**KNOBS, **ON}
    built = policy.problem_of(setup, state, 1, knobs, beliefs, status, returns, blended=blended)
    p, cats = built.problem, setup.cats
    pool = len(setup.teams) * setup.spots()
    assert p.rates is blended and p.value == wk.per_game_values(blended, cats, None)
    assert p.season_rates is beliefs and p.drop_value == wk.per_game_values(beliefs, cats, None)
    assert p.season_value == wk.per_game_values(beliefs, cats, None, pool)
    assert built.scorer == wk.scorer_of(beliefs, cats, None, pool)
    assert p.noise == spr.noise_of(knobs) and p.noise is not None
    # Every team's week takes the spread, counted from the day, on the blended line.
    span = p.horizons["week"][0]
    opponent = policy.week_view(setup, state, 1, setup.week_of(day).number).opponent
    members = policy.members_of(setup, [k for k, _ in state.rosters[opponent]], status)
    assert span.opponents[0] == wk.project_week(
        members,
        blended,
        span.days,
        setup.schedule,
        setup.starting_slots(),
        p.value,
        True,
        points=None,
        returns=returns,
        spots=setup.spots(),
        noise=p.noise,
        today=day,
    )
    # Every change off: the problem of the version before.
    plain = policy.problem_of(setup, state, 1, KNOBS, beliefs, status, returns).problem
    assert plain.rates is beliefs and plain.noise is None
    assert plain.season_rates is None and plain.drop_value is None
    # A blend handed that blends nothing reads as none.
    same = policy.problem_of(setup, state, 1, knobs, beliefs, status, returns, blended=beliefs)
    assert same.problem.season_rates is None and same.problem.drop_value is None


def test_a_returning_player_takes_a_spot_from_the_least_valuable_in_a_later_week():
    """Team 2 holds six active players and its best in the held slot, out until a day of next
    week. Under ``legal`` its later week holds him out until that day and then gives him a spot,
    and the least valuable of the six plays none of his games from it; under ``uncapped`` the
    week is the six alone, as before the take-in."""
    setup = make_setup(teams=2, spots=6, pool=8, weeks=4, held_slots=("IL",))
    assert setup.spots() == 6
    beliefs = setup.projection
    value = wk.per_game_values(beliefs, setup.cats, None)
    two = [k for k, _ in setup.rosters[2]]
    best = max(two, key=lambda k: value[k])
    extra = max(setup.pool, key=lambda k: value[k])
    rosters = dict(setup.rosters)
    rosters[2] = (*((k, s) for k, s in setup.rosters[2] if k != best), (extra, "BN"), (best, "IL"))
    day = setup.calendar.weeks[0].start
    week = setup.calendar.weeks[1]
    back = week.start + timedelta(2)
    state = replace(
        initial(setup), day=day, rosters=rosters, pool=tuple(k for k in setup.pool if k != extra)
    )
    status, returns = {best: "O"}, {best: back}
    later = {**KNOBS, "later_weeks": policy.LEGAL}
    p = policy.problem_of(setup, state, 1, later, beliefs, status, returns).problem
    members = policy.members_of(setup, [k for k, _ in rosters[2]], status)
    days = tuple(week.days())
    slots = setup.starting_slots()
    assert p.horizons["three"][0].opponents[0] == wk.project_week(
        members, beliefs, days, setup.schedule, slots, value, False, returns=returns, spots=6
    )
    playing = wk.playing_days(
        members, days, setup.schedule, False, returns=returns, spots=6, value=value
    )
    active = [k for k, s in rosters[2] if s != "IL"]
    least = min(active, key=lambda k: value[k])
    games = [d for d in days if setup.players[least].nba_team in setup.schedule[d]]
    assert any(d >= back for d in games) and any(d < back for d in games)
    assert playing[least] == [d for d in games if d < back]
    assert playing[best] and min(playing[best]) >= back
    assert all(playing[k] == [d for d in days if setup.players[k].nba_team in setup.schedule[d]]
               for k in active if k != least)  # fmt: skip
    # The rule before: the six active players, no cap and no return date.
    uncapped = {**KNOBS, "later_weeks": policy.UNCAPPED}
    q = policy.problem_of(setup, state, 1, uncapped, beliefs, status, returns).problem
    six = policy.members_of(setup, active, status)
    assert q.horizons["three"][0].opponents[0] == wk.project_week(
        six, beliefs, days, setup.schedule, slots, value, False
    )
    assert q.horizons["three"][0].opponents[0] != p.horizons["three"][0].opponents[0]
    # The seat's own roster is its active players under either rule.
    assert p.roster == q.roster and [k for k, _ in p.roster] == list(state.active(1))


# --------------------------------------------------------------------------- the rivals and lineups
def test_a_mirror_rival_takes_the_arm_s_five_and_a_market_rival_none(made_up):
    setup, _, _, _ = made_up
    a = arm("A", "exact", "mirror", **ON)
    mirror = rn.opponents_of(setup, a, 1)[2]
    assert isinstance(mirror, op.Mirror)
    assert {k: policy.knob(mirror.knobs, k) for k in policy.TAKEIN_KNOBS} == ON
    assert rn.blend_of(mirror) == rn.blend_of(a.seat()) == BLEND
    assert rn.blend_of(op.Market(0.2)) is None and rn.blend_of(op.Static()) is None
    assert rn.blend_of(arm("B", "exact", "mirror").seat()) is None


def test_the_seat_and_its_mirror_rivals_start_on_the_blended_value_a_market_rival_on_its_own():
    """In the no-peek test's league (three starting slots, four players a team) a day's starters
    are chosen by value. A seat that blends, and a mirror rival of its arm, start the most
    valuable set on the blended value; a market rival on the run's beliefs as read. The blend
    chooses differently from the line as read on some day, or the test has no power."""
    setup, lines = recorded()
    w = rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS)
    a, m = arm("A", "surrogate", "mirror", **ON), arm("M", "surrogate", "market", **ON)
    variants = [
        {**rn.opponents_of(setup, a, 1), 1: a.seat()},
        {**rn.opponents_of(setup, m, 1), 1: m.seat()},
    ]
    apart = [0]

    def check(r: rn.DayRecord) -> None:
        read = wk.per_game_values(r.beliefs, setup.cats, None)
        mixed = wk.per_game_values(
            w.blended_on(r.day, None, rn.rostered_of(r.state), *BLEND), setup.cats, None
        )
        for t in setup.teams:
            blends = t == 1 or r.variant == 0
            want = policy.starters_of(setup, r.state, t, r.day, r.status, mixed if blends else read)
            assert r.starters[t] == want, (r.day, r.variant, t)
            plain = policy.starters_of(setup, r.state, t, r.day, r.status, read)
            apart[0] += blends and set(want) != set(plain)

    rn.simulate(setup, w, variants, on_day=check)
    assert apart[0] > 0


# --------------------------------------------------------------------------- the split seats
@pytest.fixture(scope="module")
def split_world():
    """The split test's season with a ``yahoo`` and a ``blend`` seat, the world handed their
    second stand-in (``cli.seconds_of``)."""
    setup, lines = recorded()
    first = {k: {s: v * 1.1 for s, v in r.items()} for k, r in setup.projection.items()}
    second = second_of(first)
    arms = {}
    for name, system, blend in (("Y", "yahoo", None), ("M", "blend", 0.25)):
        x = arm(name, "surrogate", "market")
        arms[name] = replace(x, knobs={**x.knobs, "system": system, "blend": blend})
    arms = ss.believing(arms, SOURCES)
    forecasts = ss.forecasts_of(SOURCES, fixed_of(first, second), lines, SEED, 0, "stat", arms)
    w = rn.replay_world(
        setup,
        lines,
        1,
        SEED,
        0,
        WEIGHTS,
        label=RUN,
        forecasts=forecasts,
        split=ss.splits_of(SOURCES, arms),
        seconds=ss.seconds_of(SOURCES, arms),
    )
    return setup, lines, arms, w, second


def test_the_run_hands_the_world_each_split_seat_s_second_stand_in(split_world):
    _, _, arms, w, second = split_world
    assert ss.seconds_of(SOURCES, arms) == {
        arms["Y"].forecaster: (SECOND, None),
        arms["M"].forecaster: (SECOND, 0.25),
    }
    assert ss.seconds_of(None, arms) == {}
    bbm = ss.believing({"B": arm("B", "surrogate", "market")}, SOURCES)
    assert ss.seconds_of(SOURCES, bbm) == {}
    assert w.seconds == ss.seconds_of(SOURCES, arms) and SECOND in w.others and FIRST in w.others
    assert w.others[SECOND].projected == frozenset(k for k in second if k in w.setup.players)


def test_a_split_yahoo_seat_keeps_the_second_s_line_for_the_available_players_it_projects(
    split_world,
):
    setup, _, arms, w, second = split_world
    day = DAYS[1]
    rostered = rn.rostered_of(initial(setup))
    label = arms["Y"].forecaster
    windows = w.recent_on(day)
    first_b = policy.blended(w.beliefs_on(day, FIRST), windows, *BLEND)
    own_b = policy.blended(w.beliefs_on(day, label), windows, *BLEND)
    read = w.seat_beliefs(day, label, rostered)
    table = w.blended_on(day, label, rostered, *BLEND)
    assert list(table) == list(read)
    kept = moved = 0
    for k in table:
        if k in rostered:
            assert table[k] == first_b[k]
        elif k in second:
            assert table[k] is read[k]
            kept += own_b[k] != read[k]
        else:
            assert table[k] == own_b[k]
            moved += table[k] != read[k]
    # Some available player the second projects would have moved, and one it does not did.
    assert kept > 0 and moved > 0
    # Without its second stand-in the world cannot blend a split seat's table.
    bare = rn.World(
        setup,
        SEED,
        0,
        w.game_days,
        w._available,
        w._line,
        1,
        w.causal,
        label=RUN,
        others=w.others,
        split=w.split,
    )
    with pytest.raises(ValueError, match="needs its second stand-in"):
        bare.blended_on(day, label, rostered, *BLEND)
    assert bare.blended_on(day, label, rostered, 0.0, 4.0) == read


def test_a_split_blend_seat_mixes_the_first_s_blended_line_with_the_second_s_own(split_world):
    setup, _, arms, w, _ = split_world
    day = DAYS[2]
    rostered = rn.rostered_of(initial(setup))
    label = arms["M"].forecaster
    windows = w.recent_on(day)
    first_b = policy.blended(w.beliefs_on(day, FIRST), windows, *BLEND)
    theirs = w.beliefs_on(day, SECOND)
    both = w.others[FIRST].projected & w.others[SECOND].projected
    table = w.blended_on(day, label, rostered, *BLEND)
    mixed = 0
    for k, line in table.items():
        if k in rostered or k not in both:
            continue
        want = {s: 0.75 * first_b[k].get(s, 0.0) + 0.25 * theirs[k].get(s, 0.0) for s in line}
        assert line == pytest.approx(want)
        mixed += 1
    assert mixed > 0


def test_a_pair_of_split_seats_plays_with_every_change_on_and_off(split_world):
    """A ``yahoo`` seat with every change off against one with every change on, through one
    world: both seasons play to their end with no breach, and the seat's days part (its
    starters or its moves)."""
    setup, _, arms, w, _ = split_world
    a = arms["Y"]
    b = replace(a, name="Yon", knobs={**a.knobs, **ON})
    days: dict[int, list[tuple[object, object]]] = {0: [], 1: []}
    ends = []

    def keep(r: rn.DayRecord) -> None:
        days[r.variant].append((r.starters[1], r.decisions.get(1)))

    got = rn.paired(setup, w, a, b, 1, on_day=keep, on_end=lambda ra, rb: ends.extend([ra, rb]))
    assert set(got) >= {"a", "b", "delta"}
    assert all(e.result is not None and e.breaches == () for e in ends) and len(ends) == 2
    assert len(days[0]) == len(days[1]) > 0 and days[0] != days[1]


# --------------------------------------------------------------------------- no peek
def blended_records(setup, lines):
    """The no-peek test's day digests with every change on, two arms and their mirror rivals."""
    got: dict[tuple[date, int], dict[str, str]] = {}
    w = rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS)
    variants = [
        {**rn.opponents_of(setup, x, 1), 1: x.seat()}
        for x in (arm("A", "exact", "mirror", **ON), arm("B", "surrogate", "mirror", **ON))
    ]

    def keep(r: rn.DayRecord) -> None:
        got[(r.day, r.variant)] = nopeek.digest(r)

    rn.simulate(setup, w, variants, on_day=keep)
    return got


@pytest.fixture(scope="module")
def no_peek_league():
    setup, lines = recorded()
    return setup, lines, blended_records(setup, lines)


@pytest.mark.parametrize("day", DAYS[1:])
def test_with_the_blend_on_a_seat_s_days_do_not_depend_on_what_comes_after(no_peek_league, day):
    setup, lines, base = no_peek_league
    got = blended_records(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    assert set(got) == set(base)
    first = nopeek.first_difference(base, got)
    assert first is not None, "the change after the day reached no record: it tested nothing"
    assert first[0] > day, f"a record on {first[0]} saw past {day}: {first[2]}"


def test_a_blend_that_reads_past_the_day_is_caught(no_peek_league, monkeypatch):
    """The check's power with the blend on: recent lines read a week late, so that a day's
    windows hold the week after it (a peek), part the records on the day or before it."""
    setup, lines, _ = no_peek_league
    day = DAYS[1]
    real = rn.World.recent_on
    monkeypatch.setattr(rn.World, "recent_on", lambda self, d: real(self, d + timedelta(7)))
    base = blended_records(setup, lines)
    got = blended_records(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED))
    first = nopeek.first_difference(base, got)
    assert first is not None and first[0] <= day, first
