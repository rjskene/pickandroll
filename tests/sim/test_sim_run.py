"""The runner (#172, PR 2b): a replay's world, common random numbers, arms in lockstep, the
paired difference, the room's rotation, a replay's league. The worlds are replays of a made-up
recorded season (``sim_league.replay_of``; PR D3)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.sim import forecast as fc
from pickandroll.sim import opponents as op
from pickandroll.sim import policy
from pickandroll.sim import run as rn
from pickandroll.sim.state import Member, initial
from tests.sim.draws import between
from tests.sim.sim_league import KNOBS, arm, make_setup, replay_of


# --------------------------------------------------------------------------- the world
def test_news_of_an_absence_arrives_after_the_lag_and_day_one_statuses_stand():
    out = 1
    setup = make_setup(statuses={out: "O"})
    setup = replace(setup, returns={out: setup.start + timedelta(3)})
    w = replay_of(setup, 3, 0, lag=2)
    status, returns = w.status_on(setup.start)
    assert status[out] == "O" and returns[out] == setup.start + timedelta(3)
    later, _ = w.status_on(setup.start + timedelta(3))
    assert out not in later
    # An absence in the recorded season is heard ``lag`` days after it began, never before,
    # with a told return no earlier than the day it is heard.
    heard = 0
    for k in setup.players:
        if k in setup.statuses:
            continue
        for i, a in enumerate(w.absences(k)):
            began = w.game_days[k][a.start]
            on = began + timedelta(2)
            if on > setup.season_end:
                continue
            if i == 0:
                assert w.status_on(began)[0].get(k) is None
                assert w.status_on(began + timedelta(1))[0].get(k) is None
            s1, r1 = w.status_on(on)
            assert s1.get(k) == "O" and r1[k] >= on
            heard += 1
    assert heard > 0


def test_a_replay_world_plays_the_recorded_lines():
    setup = make_setup(teams=2, spots=3, pool=2, weeks=2, playoff_weeks=1)
    k = setup.pool[0]
    days = [d for d in setup.days if setup.players[k].nba_team in setup.schedule[d]]
    lines = {k: {days[0]: {"pts": 7.0}, days[2]: {"pts": 9.0}}}
    w = rn.replay_world(setup, lines, 1, 1, 0)
    assert w.line(k, days[0]) == {"pts": 7.0}
    assert w.line(k, days[1]) is None  # a game day without a line: he sat out
    assert w.line(k, days[2]) == {"pts": 9.0}
    assert list(w.available(k)[:3]) == [True, False, True]
    # A day his team does not play has no line either.
    off = next(d for d in setup.days if setup.players[k].nba_team not in setup.schedule[d])
    assert w.line(k, off) is None
    # The seats read the causal belief: on the first day, the projection itself.
    assert w.beliefs_on(days[0]) == w.causal.on(days[0])
    assert w.beliefs_on(days[0])[k] == pytest.approx(setup.projection[k])


# --------------------------------------------------------------------------- lockstep and pairing
def test_the_same_arm_twice_shares_every_solve_and_differs_by_nothing():
    setup = make_setup()
    w = replay_of(setup, 11, 0)
    a = arm("A", "exact")
    out = rn.paired(setup, w, a, a, me=1)
    assert all(v == 0 for v in out["delta"].values())
    assert out["shared"] == out["solves"] > 0  # every solve of A served B too
    assert out["executed"][0] == out["executed"][1]


def test_two_arms_diverge_and_the_pairing_reports_both():
    setup = make_setup()
    w = replay_of(setup, 11, 0)
    out = rn.paired(setup, w, arm("A", "exact"), arm("B", "ranking"), me=1)
    assert set(out["a"]) == set(rn.METRICS) == set(out["delta"])
    assert out["a"]["rank"] in {1.0, 2.0, 3.0, 4.0}
    assert out["delta"]["rank"] == out["b"]["rank"] - out["a"]["rank"]
    assert out["bracket_unread"] is None
    unread = replace(setup, spec=None, bracket_unread="the settings page has not been read")
    none = rn.paired(unread, w, arm("A", "ranking"), arm("B", "ranking"), me=1)
    assert none["a"]["made_playoffs"] is None and none["delta"]["rank"] is None
    assert none["bracket_unread"] == "the settings page has not been read"


def test_the_paired_difference_is_b_less_a_on_every_metric():
    # Path 0 of seed 2 parts the two arms on all five metrics, so a reversed sign fails
    # each of them: A less B would equal B less A only where the arms agree.
    setup = make_setup()
    w = replay_of(setup, 2, 0)
    out = rn.paired(setup, w, arm("A", "exact"), arm("B", "ranking"), me=1)
    a, b, delta = out["a"], out["b"], out["delta"]
    assert all(a[k] is not None and b[k] is not None for k in rn.METRICS)
    assert all(a[k] != b[k] for k in rn.METRICS)
    for k in rn.METRICS:
        assert delta[k] == b[k] - a[k], k
    # Swapping the arms negates the difference.
    back = rn.paired(setup, w, arm("B", "ranking"), arm("A", "exact"), me=1)
    assert back["delta"] == {k: -delta[k] for k in rn.METRICS}


def test_common_random_numbers_a_roster_change_moves_no_other_players_line():
    setup = make_setup()
    w = replay_of(setup, 5, 0)
    me = 1
    day = setup.start + timedelta(8)
    static = {t: op.Static() for t in setup.teams}
    quiet = {**static, me: op.Seat("Q", "static", KNOBS)}
    busy = {**static, me: op.Seat("B", "ranking", KNOBS)}
    (rq, rb) = rn.simulate(setup, w, [quiet, busy])
    assert rb.executed >= rq.executed == 0
    k = next(k for k in setup.pool if setup.players[k].nba_team in setup.schedule[day])
    assert w.line(k, day) == replay_of(setup, 5, 0).line(k, day)


@dataclass(frozen=True)
class OnDays:
    """A seat that adds the pool's first player for its roster's first on the given weekdays."""

    days: tuple[int, ...]
    kind: str = "on_days"

    def decide(self, setup, state, team, beliefs, status, returns, g):
        pool, roster = sorted(state.pool), state.active(team)
        if state.day.weekday() not in self.days or not pool or not roster:
            return policy.NONE
        return policy.Decision((mv.Move(pool[0], roster[0]),), (), (), 0, self.kind)


def test_an_add_made_on_sunday_spends_the_ending_week_not_mondays():
    """One add a week. Made on Sunday it lands Monday and is charged to the week it was made in,
    as on Yahoo, so Monday's add is still there to make, and both land."""
    setup = make_setup(weeks=2, playoff_weeks=1, max_weekly_adds=1, bracket=False)
    sunday = setup.calendar.weeks[0].end
    setup = replace(setup, start=sunday)
    w = replay_of(setup, 5, 0)
    static = {t: op.Static() for t in setup.teams}
    (both,) = rn.simulate(setup, w, [{**static, 1: OnDays((6, 0))}])
    assert both.executed == 2 and both.gone == 0
    (mondays,) = rn.simulate(setup, w, [{**static, 1: OnDays((0,))}])
    assert mondays.executed == 1


@dataclass(frozen=True)
class Stasher:
    """A seat that adds the pool's best through a held-slot move whenever one of its active
    players is out and the IL slot is open, and records the active roster it sees each day."""

    seen: list = field(default_factory=list, repr=False)
    kind: str = "stasher"

    def decide(self, setup, state, team, beliefs, status, returns, g):
        self.seen.append((state.day, state.active(team), state.held(team), dict(status)))
        out = [k for k in state.active(team) if status.get(k) == "O"]
        pool = sorted(state.pool)
        if not out or state.held(team) or not pool or state.adds_used.get(team, 0) >= 4:
            return policy.NONE
        return policy.Decision((mv.Move(pool[0]),), ((out[0], "IL"),), (), 0, self.kind)


def test_held_slot_moves_land_and_a_returned_player_is_activated_in_a_run():
    """Through the runner: a day-one IL occupant is back on the active roster the morning of his
    return and plays again, the held-slot move is made and its add is active, the roster never
    exceeds the league's spots, and the stashed player comes back the same way, never parked in
    IL for the season; each return over the spots is a forced drop."""
    setup = make_setup(weeks=2, playoff_weeks=1, held_slots=("IL",), bracket=False)
    base = initial(setup)
    hurt, occupant = base.active(1)[0], min(base.pool)
    back, back_occ = setup.start + timedelta(4), setup.start + timedelta(2)
    projection = dict(setup.projection)
    projection[occupant] = {s: v * 2 for s, v in projection[occupant].items()}
    setup = replace(
        setup,
        rosters={**setup.rosters, 1: (*setup.rosters[1], (occupant, "IL"))},
        projection=projection,
        statuses={hurt: "O", occupant: "O"},
        returns={hurt: back, occupant: back_occ},
    )
    w = replay_of(setup, 11, 0)
    seat = Stasher()
    static = {t: op.Static() for t in setup.teams}
    (res,) = rn.simulate(setup, w, [{**static, 1: seat}])
    assert res.executed >= 1 and res.forced_drops >= 1
    assert max(len(active) for _, active, _, _ in seat.seen) <= setup.spots()
    stashed = [day for day, _, held, _ in seat.seen if (hurt, "IL") in held]
    assert stashed and min(stashed) < back
    # No held player whose status has cleared is ever seen still in his slot (he may be stashed
    # again later, when his recorded season has him out again).
    assert all(status.get(k) == "O" for _, _, held, status in seat.seen for k, _ in held)
    # The occupant, the best player here, is active from the morning of his return.
    assert all(occupant in active for day, active, _, _ in seat.seen if day == back_occ)
    assert all(occupant not in active for day, active, _, _ in seat.seen if day < back_occ)


def test_the_room_rotates_arms_across_paths_and_pools_by_arm():
    setup = make_setup()
    arms = {"A": arm("A", "ranking"), "B": arm("B", "surrogate")}
    assert rn.rotate(["A", "B"], (1, 2, 3, 4), 0) == {1: "A", 2: "B", 3: "A", 4: "B"}
    assert rn.rotate(["A", "B"], (1, 2, 3, 4), 1) == {1: "B", 2: "A", 3: "B", 4: "A"}
    w = replay_of(setup, 9, 1)
    out = rn.room(setup, w, arms, ["A", "B"], 1)
    assert out["seats"] == {"1": "B", "2": "A", "3": "B", "4": "A"}
    assert set(out["by_arm"]) == {"A", "B"}
    ranks = [out["by_arm"][a]["rank"] for a in ("A", "B")]
    assert sum(ranks) == pytest.approx(5.0)  # two seats each, ranks 1-4 shared out


# --------------------------------------------------------------------------- the arms and the fit
def test_an_arm_comes_from_its_spec_and_a_bad_one_is_refused():
    spec = {
        "name": "A",
        "tier": "exact",
        "knobs": KNOBS,
        "opponents": {"kind": "market", "rate": 0.2},
    }
    a = rn.arm_of(spec)
    assert a.name == "A" and a.tier == "exact" and a.seat().kind == "seat"
    with pytest.raises(ValueError):
        rn.arm_of({**spec, "tier": "oracle"})
    with pytest.raises(KeyError):
        rn.arm_of({**spec, "knobs": {"system": "bbm"}})
    with pytest.raises(ValueError):
        rn.arm_of({**spec, "executes": "all"})
    rn.check_fit({"fit_sha": "abc"}, "abc")
    rn.check_fit({}, "abc")
    with pytest.raises(ValueError):
        rn.check_fit({"name": "A", "fit_sha": "abc"}, "def")


def test_the_worlds_inputs_come_from_the_frozen_fit():
    """A run reads the frozen fit's lag and its hash, nothing else: a fit with or without a
    ``tau`` or a fitted refresh loads, the fitted lag before the defaults', 1 without either."""
    payload = {
        "dispersion": {"pooled": {"pts": 1.5}, "players": {}},
        "minutes": {"sigma": 0.2},
        "tau": None,
        "refresh": None,
        "parameters": {"refresh_defaults": {"kappa": 0.1, "sigma_eta": 0.05, "lag": 3}},
    }
    got = rn.inputs_of(payload, "sha")
    assert got == rn.WorldInputs(3, "sha")
    fitted = rn.inputs_of(
        {**payload, "tau": {"pts": 0.3}, "refresh": {"kappa": 0.2, "fitted": True, "lag": 2}},
        "sha",
    )
    assert fitted == rn.WorldInputs(2, "sha")
    assert rn.inputs_of({}, "other") == rn.WorldInputs(1, "other")


# --------------------------------------------------------------------------- the aggregate
def test_aggregate_takes_each_metrics_mean_se_and_count():
    rows = [
        {"made_playoffs": 1.0, "rank": 2.0},
        {"made_playoffs": 0.0, "rank": 4.0},
        {"made_playoffs": None, "rank": 3.0},
    ]
    agg = rn.aggregate(rows)
    assert agg["made_playoffs"]["mean"] == 0.5 and agg["made_playoffs"]["n"] == 2
    assert agg["made_playoffs"]["se"] == pytest.approx(0.5)
    assert agg["rank"]["n"] == 3 and agg["title"] == {"mean": None, "se": None, "n": 0}


# --------------------------------------------------------------------------- a replay's league
def test_a_replay_league_is_drafted_on_the_stand_in_and_keyed_to_each_players_games():
    first = date(2024, 10, 22)
    players = {
        k: Member(k, f"P{k}", str(1 + k % 3), ("PG",) if k % 2 else ("C",)) for k in range(1, 41)
    }
    lines = {
        k: {
            first + timedelta(2 * i + (k % 2)): {"pts": float(10 + k % 7), "fgm": 4.0, "fga": 8.0}
            for i in range(25)
        }
        for k in players
    }
    lines[40] = {first: {"pts": 1.0}}  # too few games for a stand-in to project
    truth = rn.realized_rates(lines, min_games=rn.STANDIN_MIN_GAMES)
    assert truth[1]["pts"] == 11.0 and set(truth[1]) <= set(wk.STATS) and 40 not in truth
    setup = rn.replay_setup(
        2025,
        lines,
        players,
        truth,
        first,
        teams=4,
        slots=("PG", "C", "Util", "BN"),
        weeks=8,
        playoff_weeks=1,
        playoff_teams=2,
    )
    # Everyone with a scheduled game is in the league; nobody projected 40, so he is on the wire.
    assert setup.teams == (1, 2, 3, 4) and len(setup.players) == 40
    assert 40 in setup.players and 40 not in setup.projection and 40 in setup.pool
    assert all(len(r) == 4 for r in setup.rosters.values())
    assert len(setup.pool) == 40 - 16
    assert setup.spec is not None and setup.spec.playoff_weeks == (8,) and setup.spec.byes == 0
    # Every player is his own team: his game days are the days he has a line.
    assert setup.players[1].nba_team == "p1"
    assert [d for d in setup.days if "p1" in setup.schedule.get(d, ())] == sorted(lines[1])
    scheduled = {1: sorted(lines[1]) + [first + timedelta(60)]}
    with_sched = rn.replay_setup(
        2025,
        lines,
        players,
        truth,
        first,
        scheduled,
        teams=4,
        slots=("PG", "C", "Util", "BN"),
        weeks=8,
        playoff_weeks=1,
        playoff_teams=2,
    )
    assert (
        first + timedelta(60) in with_sched.schedule
        and "p1" in with_sched.schedule[first + timedelta(60)]
    )
    noised = fc.oracle(lines, 0.2, 1, 0)
    assert set(noised) == set(truth) and noised[1]["pts"] != truth[1]["pts"]
    assert all(v["fgm"] <= v["fga"] for v in noised.values() if "fga" in v)
    assert fc.oracle(lines, 0.2, 1, 0) == noised


def test_simulate_runs_a_replay_league_end_to_end():
    first = date(2024, 10, 21)
    rng = np.random.default_rng(4)
    players = {
        k: Member(k, f"P{k}", "x", ("PG", "SG") if k % 2 else ("C", "PF")) for k in range(1, 25)
    }
    lines = {}
    for k in players:
        level = between(rng, 0.6, 1.4)
        lines[k] = {
            first + timedelta(i): {
                "pts": 10 * level,
                "reb": 5 * level,
                "ast": 3 * level,
                "fgm": 4.0,
                "fga": 8.0,
                "ftm": 2.0,
                "fta": 2.5,
                "threes": 1.0,
                "stl": 1.0,
                "blk": 1.0,
                "tov": 2.0,
            }
            for i in range(0, 28, 2 if k % 3 else 3)
        }
    truth = rn.realized_rates(lines)
    setup = rn.replay_setup(
        2025,
        lines,
        players,
        truth,
        first,
        teams=4,
        slots=("PG", "C", "Util", "BN"),
        weeks=4,
        playoff_weeks=1,
        playoff_teams=2,
    )
    w = rn.replay_world(setup, lines, 1, 1, 0)
    arms = {"A": arm("A", "surrogate", "static"), "B": arm("B", "ranking", "static")}
    out = rn.room(setup, w, arms, ["A", "B"], 0)
    assert set(out["by_arm"]) == {"A", "B"} and out["bracket_unread"] is None
    assert initial(setup).day == first
