"""The no-peek test (#172, PR B1): a replay's seat on day ``d`` knows nothing dated after it.

Two replay worlds share the preseason inputs, the schedule, every line dated before ``d`` and
every absence that begins on or before ``d`` (its start and its end), and differ in the lines
dated ``d`` or later and in the absences that begin after it. Every day record (beliefs, what
was heard, what landed, the decisions, the queue, the starters, the state) must be the same
through ``d``, and some record after ``d`` must differ, or the second world tested nothing.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.sim import belief as bf
from pickandroll.sim import nopeek
from pickandroll.sim import run as rn
from pickandroll.sim.engine import wk
from pickandroll.sim.state import Member
from tests.sim.sim_league import arm

FIRST = date(2024, 10, 22)  # a Tuesday; the calendar starts on the Monday before
SLOTS = ("PG", "C", "Util", "BN")
WEIGHTS = dict.fromkeys(wk.STATS, 6.0)
SEED = 7


def recorded():
    """A small season: forty players every other day, a tenth of their games missed, each a
    level of his own; a stand-in that misses every level by a little; one player nobody
    projected who arrives in week two."""
    rng = np.random.default_rng(3)
    players = {
        k: Member(k, f"P{k}", "x", ("PG", "SG") if k % 2 else ("C", "PF")) for k in range(1, 42)
    }
    scheduled = {k: [FIRST + timedelta(2 * i + k % 2) for i in range(20)] for k in players}
    scheduled[41] = scheduled[41][4:]
    lines: dict[int, dict[date, dict[str, float]]] = {}
    standin = {}
    for k, days in scheduled.items():
        level = float(rng.uniform(0.5, 1.6))
        lines[k] = {}
        for d in days:
            if rng.random() < 0.1:
                continue
            fga = float(rng.poisson(9 * level))
            fta = float(rng.poisson(3 * level))
            fgm = float(min(fga, rng.poisson(0.47 * fga)))
            ftm = float(min(fta, rng.poisson(0.78 * fta)))
            threes = float(min(fgm, rng.poisson(1.2 * level)))
            lines[k][d] = {
                "pts": 2 * fgm + threes + ftm,
                "threes": threes,
                "reb": float(rng.poisson(5 * level)),
                "ast": float(rng.poisson(3 * level)),
                "stl": float(rng.poisson(1.0 * level)),
                "blk": float(rng.poisson(0.7 * level)),
                "tov": float(rng.poisson(1.8 * level)),
                "fgm": fgm,
                "fga": fga,
                "ftm": ftm,
                "fta": fta,
            }
        if k != 41:
            miss = float(np.exp(0.15 * rng.standard_normal()))
            standin[k] = {
                "pts": 9.0 * level * miss,
                "threes": 1.2 * level,
                "reb": 5 * level * miss,
                "ast": 3 * level,
                "stl": 1.0 * level,
                "blk": 0.7 * level,
                "tov": 1.8 * level,
                "fgm": 4.2 * level,
                "fga": 9 * level,
                "ftm": 2.3 * level,
                "fta": 3 * level,
            }
    setup = rn.replay_setup(
        2024,
        lines,
        players,
        standin,
        FIRST,
        scheduled,
        teams=4,
        slots=SLOTS,
        weeks=6,
        playoff_weeks=1,
        playoff_teams=2,
    )
    # The rivals trade at the market's pace: the seats' moves meet theirs.
    return replace(setup, market_rate=0.4), lines


def variants(setup):
    me = 1
    out = []
    for a in (arm("A", "exact", "market"), arm("B", "surrogate", "market")):
        out.append({**rn.opponents_of(setup, a, me), me: a.seat()})
    return out


def records(setup, lines, lag: int = 1):
    got: dict[tuple[date, int], dict[str, str]] = {}
    moved = [0]

    def keep(r: rn.DayRecord) -> None:
        got[(r.day, r.variant)] = nopeek.digest(r)
        moved[0] += sum(len(d.moves) for d in r.decisions.values())

    w = rn.replay_world(setup, lines, lag, SEED, 0, WEIGHTS)
    rn.simulate(setup, w, variants(setup), on_day=keep)
    return got, moved[0]


def absences(game_days, lines):
    """Each player's absences as (first missed day, last missed day)."""
    out = {}
    for k, days in game_days.items():
        runs, start = [], None
        for i, d in enumerate(days):
            missed = d not in lines.get(k, {})
            if missed and start is None:
                start = i
            if not missed and start is not None:
                runs.append((days[start], days[i - 1]))
                start = None
        if start is not None:
            runs.append((days[start], days[-1]))
        out[k] = runs
    return out


@pytest.fixture(scope="module")
def league():
    setup, lines = recorded()
    base, moved = records(setup, lines)
    return setup, lines, base, moved


DAYS = (
    date(2024, 11, 4),  # a Monday: the week's adds start over
    date(2024, 11, 14),  # a Thursday
    date(2024, 11, 23),  # a Saturday
)


def test_the_check_has_seats_that_move_and_a_monday_among_its_days(league):
    setup, _, _, moved = league
    assert moved > 0  # the seats and the rivals decide moves, so a peek could reach them
    assert DAYS[0].weekday() == 0 and all(d in setup.days for d in DAYS)
    assert 41 not in setup.projection and 41 in setup.players


@pytest.mark.parametrize("day", DAYS)
def test_the_second_world_agrees_on_everything_up_to_the_day_and_differs_after(league, day):
    setup, lines, _, _ = league
    game_days = rn.game_days_of(setup)
    other = nopeek.perturb(lines, game_days, day, SEED)
    # The lines before the day agree; some line on or after it does not.
    for k in lines:
        assert {d: x for d, x in lines[k].items() if d < day} == {
            d: x for d, x in other[k].items() if d < day
        }
    assert any(
        {d: x for d, x in lines[k].items() if d >= day}
        != {d: x for d, x in other[k].items() if d >= day}
        for k in lines
    )
    # Every absence that begins by the day agrees, its end too; one that begins later differs.
    a, b = absences(game_days, lines), absences(game_days, other)
    for k in lines:
        assert [r for r in a[k] if r[0] <= day] == [r for r in b[k] if r[0] <= day]
    assert any([r for r in a[k] if r[0] > day] != [r for r in b[k] if r[0] > day] for k in lines)
    # The schedule is the league's own and does not move.
    assert all(set(other[k]) <= set(game_days[k]) for k in other)


@pytest.mark.parametrize("day", DAYS)
def test_a_seats_days_through_the_day_do_not_depend_on_what_comes_after(league, day):
    setup, lines, base, _ = league
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, SEED)
    got, _ = records(setup, other)
    assert set(got) == set(base)
    first = nopeek.first_difference(base, got)
    assert first is not None, "the change after the day reached no record: it tested nothing"
    assert first[0] > day, f"a record on {first[0]} saw past {day}: {first[2]}"
    same = [key for key in base if key[0] <= day]
    assert same and all(base[key] == got[key] for key in same)


def test_a_belief_that_reads_the_days_own_line_is_caught(league, monkeypatch):
    """The check's power: a belief that counts the line dated on the day it is read (a peek of
    a few hours) parts the records on that very day."""
    setup, lines, _, _ = league
    day = DAYS[1]
    monkeypatch.setattr(
        bf.CausalBelief,
        "games_before",
        lambda self, player, d: sum(1 for x in self._dates.get(player, []) if x <= d),
    )
    peeking, _ = records(setup, lines)
    other = nopeek.perturb(lines, rn.game_days_of(setup), day, SEED)
    got, _ = records(setup, other)
    first = nopeek.first_difference(peeking, got)
    assert first is not None and first[0] == day and "beliefs" in first[2]


def test_news_heard_before_an_absence_begins_is_caught(league):
    """The check's power on the news: a lag of minus one hears an absence the day before its
    first missed game, which the second world changes after the day."""
    setup, lines, _, _ = league
    day = DAYS[2]
    early, _ = records(setup, lines, lag=-1)
    got, _ = records(setup, nopeek.perturb(lines, rn.game_days_of(setup), day, SEED), lag=-1)
    first = nopeek.first_difference(early, got)
    assert first is not None and first[0] <= day and "status" in first[2]


def test_the_digest_ignores_the_order_maps_were_built_in():
    a = {"x": {2: 1.0, 1: 2.0}, "s": frozenset({3, 1})}
    b = {"s": frozenset({1, 3}), "x": {1: 2.0, 2: 1.0}}
    assert nopeek.canonical(a) == nopeek.canonical(b)
    assert nopeek.canonical({"d": date(2024, 1, 1)}) == nopeek.canonical({"d": date(2024, 1, 1)})
    assert nopeek.canonical(np.float64(1.5)) == 1.5
    k = (date(2024, 1, 1), 0)
    assert nopeek.first_difference({k: {"state": "a"}}, {k: {"state": "a"}}) is None
    assert nopeek.first_difference({k: {"state": "a"}}, {}) == (k[0], 0, nopeek.FIELDS)
