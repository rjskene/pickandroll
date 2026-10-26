"""The runner (#172, PR 2b): one world a path, common random numbers, arms in lockstep, the
paired difference, the room's rotation, a replay's league, the payload's verdict."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np
import pytest

from pickandroll.season import moves as mv
from pickandroll.season import weekly as wk
from pickandroll.season.sim import opponents as op
from pickandroll.season.sim import policy
from pickandroll.season.sim import run as rn
from pickandroll.season.sim.state import Member, initial
from tests.sim_league import HAZARD, KNOBS, PHI, arm, inputs, make_setup


# --------------------------------------------------------------------------- the world
def test_the_world_draws_once_a_path_whatever_the_arm_does():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 7, 0, 0.0)
    k = setup.pool[0]
    day = next(d for d in setup.days if setup.players[k].nba_team in setup.schedule[d])
    first = w.line(k, day)
    again = rn.forward_world(setup, inputs(), 7, 0, 0.0).line(k, day)
    assert first == again
    other = rn.forward_world(setup, inputs(), 7, 1, 0.0).line(k, day)
    assert other != first
    # A day his team does not play has no line; the truth is the projection at tau 0, s 0.
    off = next(d for d in setup.days if setup.players[k].nba_team not in setup.schedule[d])
    assert w.line(k, off) is None
    flat = rn.forward_world(setup, inputs(tau=0.0), 7, 0, 0.0)
    assert flat.truth[k] == pytest.approx(rn.consistent(setup.projection[k]))
    assert w.kind == "forward"


def test_the_error_shrinks_toward_the_market_by_the_gap():
    setup = make_setup()
    gap = {k: dict.fromkeys(wk.STATS, 0.5) for k in setup.projection}
    with_gap = replace(setup, gap=gap)
    k = setup.pool[0]
    plain = rn.forward_world(with_gap, inputs(tau=0.0), 1, 0, 0.0).truth[k]["pts"]
    shrunk = rn.forward_world(with_gap, inputs(tau=0.0), 1, 0, 0.5).truth[k]["pts"]
    assert shrunk == pytest.approx(plain * np.exp(-0.25))


def test_beliefs_refresh_weekly_and_are_shared():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(tau=0.3, kappa=0.5, sigma_eta=0.0), 2, 0, 0.0)
    k = setup.pool[0]
    b0, b1, b4 = w.beliefs(0), w.beliefs(1), w.beliefs(4)
    assert b0[k] == setup.projection[k]
    truth = w.truth[k]["pts"]
    assert abs(b1[k]["pts"] - truth) < abs(b0[k]["pts"] - truth) or truth == b0[k]["pts"]
    assert abs(b4[k]["pts"] - truth) <= abs(b1[k]["pts"] - truth) + 1e-9
    assert w.beliefs(1) is b1  # cached


def test_news_of_an_absence_arrives_after_the_lag_and_day_one_statuses_stand():
    out = 1
    setup = make_setup(statuses={out: "O"})
    setup = replace(setup, returns={out: setup.start + timedelta(3)})
    w = rn.forward_world(setup, inputs(lag=2), 3, 0, 0.0)
    status, returns = w.status_on(setup.start)
    assert status[out] == "O" and returns[out] == setup.start + timedelta(3)
    later, _ = w.status_on(setup.start + timedelta(3))
    assert out not in later
    # A simulated absence is heard ``lag`` days after it began, never before.
    for k in setup.players:
        for a in w.absences(k):
            if a.start == 0:
                continue
            began = w.game_days[k][a.start]
            s0, _ = w.status_on(began)
            s1, r1 = w.status_on(began + timedelta(2))
            if began + timedelta(2) <= setup.season_end and k not in setup.statuses:
                assert s0.get(k) != "O" or k in setup.statuses
                if began + timedelta(2) <= r1.get(k, began):
                    assert s1.get(k) == "O"
            break


def test_a_replay_world_plays_the_recorded_lines():
    setup = make_setup(teams=2, spots=3, pool=2, weeks=2, playoff_weeks=1)
    k = setup.pool[0]
    days = [d for d in setup.days if setup.players[k].nba_team in setup.schedule[d]]
    lines = {k: {days[0]: {"pts": 7.0}, days[2]: {"pts": 9.0}}}
    w = rn.replay_world(setup, lines, {k: {"pts": 8.0}}, 0.0, 0.0, 1, 1, 0)
    assert w.line(k, days[0]) == {"pts": 7.0}
    assert w.line(k, days[1]) is None  # a game day without a line: he sat out
    assert w.line(k, days[2]) == {"pts": 9.0}
    assert list(w.available(k)[:3]) == [True, False, True]
    assert w.kind == "replay"


# --------------------------------------------------------------------------- lockstep and pairing
def test_the_same_arm_twice_shares_every_solve_and_differs_by_nothing():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 11, 0, 0.25)
    a = arm("A", "exact")
    out = rn.paired(setup, w, a, a, me=1)
    assert all(v == 0 for v in out["delta"].values())
    assert out["shared"] == out["solves"] > 0  # every solve of A served B too
    assert out["executed"][0] == out["executed"][1]


def test_two_arms_diverge_and_the_pairing_reports_both():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 11, 0, 0.25)
    out = rn.paired(setup, w, arm("A", "exact"), arm("B", "ranking"), me=1)
    assert set(out["a"]) == set(rn.METRICS) == set(out["delta"])
    assert out["a"]["rank"] in {1.0, 2.0, 3.0, 4.0}
    assert out["delta"]["rank"] == out["a"]["rank"] - out["b"]["rank"]
    assert out["bracket_unread"] is None
    unread = replace(setup, spec=None, bracket_unread="the settings page has not been read")
    none = rn.paired(unread, w, arm("A", "ranking"), arm("B", "ranking"), me=1)
    assert none["a"]["made_playoffs"] is None and none["delta"]["rank"] is None
    assert none["bracket_unread"] == "the settings page has not been read"


def test_common_random_numbers_a_roster_change_moves_no_other_players_line():
    setup = make_setup()
    w = rn.forward_world(setup, inputs(), 5, 0, 0.0)
    me = 1
    day = setup.start + timedelta(8)
    static = {t: op.Static() for t in setup.teams}
    quiet = {**static, me: op.Seat("Q", "static", KNOBS)}
    busy = {**static, me: op.Seat("B", "ranking", KNOBS)}
    (rq, rb) = rn.simulate(setup, w, [quiet, busy])
    assert rb.executed >= rq.executed == 0
    k = next(k for k in setup.pool if setup.players[k].nba_team in setup.schedule[day])
    assert w.line(k, day) == rn.forward_world(setup, inputs(), 5, 0, 0.0).line(k, day)


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
    w = rn.forward_world(setup, inputs(), 5, 0, 0.0)
    static = {t: op.Static() for t in setup.teams}
    (both,) = rn.simulate(setup, w, [{**static, 1: OnDays((6, 0))}])
    assert both.executed == 2 and both.gone == 0
    (mondays,) = rn.simulate(setup, w, [{**static, 1: OnDays((0,))}])
    assert mondays.executed == 1


def test_the_room_rotates_arms_across_paths_and_pools_by_arm():
    setup = make_setup()
    arms = {"A": arm("A", "ranking"), "B": arm("B", "surrogate")}
    assert rn.rotate(["A", "B"], (1, 2, 3, 4), 0) == {1: "A", 2: "B", 3: "A", 4: "B"}
    assert rn.rotate(["A", "B"], (1, 2, 3, 4), 1) == {1: "B", 2: "A", 3: "B", 4: "A"}
    w = rn.forward_world(setup, inputs(), 9, 1, 0.0)
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
    payload = {
        "dispersion": {"pooled": PHI, "players": {"1001": {"pts": 2.0}}},
        "minutes": {"sigma": 0.2},
        "hazard": {
            "rate": HAZARD.rate,
            "components": [
                {
                    "lo": c.lo,
                    "hi": c.hi,
                    "weight": c.weight,
                    "lengths": {str(k): v for k, v in c.lengths.items()},
                }
                for c in HAZARD.components
            ],
            "runs": 100,
            "played": 1000,
            "players": 20,
        },
        "tau": None,
        "refresh": None,
        "parameters": {"refresh_defaults": {"kappa": 0.1, "sigma_eta": 0.05, "lag": 1}},
    }
    with pytest.raises(ValueError):
        rn.inputs_of(payload, "sha", None)
    got = rn.inputs_of(payload, "sha", {"pts": 0.2})
    assert got.hazard.rate == HAZARD.rate and got.hazard.components[0].lengths == {
        1: 0.5,
        2: 0.3,
        3: 0.2,
    }
    assert got.phi_players["1001"] == {"pts": 2.0}
    assert got.kappa == 0.1 and got.refresh_from == "defaults" and got.sha == "sha"
    fitted = rn.inputs_of(
        {
            **payload,
            "tau": {"pts": 0.3},
            "refresh": {"kappa": 0.2, "sigma_eta": 0.1, "fitted": True, "lag": 2},
        },
        "sha",
        None,
    )
    assert (
        fitted.tau == {"pts": 0.3}
        and fitted.kappa == 0.2
        and fitted.lag == 2
        and fitted.refresh_from == "fitted"
    )


# --------------------------------------------------------------------------- the aggregate and verdict
def test_aggregate_and_the_advisory_verdict():
    rows = [
        {"made_playoffs": 1.0, "rank": 2.0},
        {"made_playoffs": 0.0, "rank": 4.0},
        {"made_playoffs": None, "rank": 3.0},
    ]
    agg = rn.aggregate(rows)
    assert agg["made_playoffs"]["mean"] == 0.5 and agg["made_playoffs"]["n"] == 2
    assert agg["made_playoffs"]["se"] == pytest.approx(0.5)
    assert agg["rank"]["n"] == 3 and agg["title"] == {"mean": None, "se": None, "n": 0}
    good = {
        "0.0": {"made_playoffs": {"mean": 0.01, "se": 0.02}},
        "0.5": {"made_playoffs": {"mean": -0.01, "se": 0.02}},
    }
    assert rn.verdict(good)["passes"] is True
    bad = {**good, "0.25": {"made_playoffs": {"mean": -0.05, "se": 0.01}}}
    assert rn.verdict(bad)["passes"] is False
    unknown = {**good, "0.25": {"made_playoffs": {"mean": None, "se": None}}}
    assert rn.verdict(unknown)["passes"] is None
    assert rn.verdict(good)["rule"] == "one-SE" and "advisory" in rn.verdict(good)["line"]


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
    lines[40] = {first: {"pts": 1.0}}  # too few games for the pool
    truth = rn.realized_rates(lines)
    assert truth[1]["pts"] == 11.0 and set(truth[1]) <= set(wk.STATS)
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
    assert setup.teams == (1, 2, 3, 4) and len(setup.players) == 39
    assert 40 not in setup.players
    assert all(len(r) == 4 for r in setup.rosters.values())
    assert len(setup.pool) == 39 - 16
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
    noised = rn.oracle_standin(truth, 0.2, 1, 0)
    assert set(noised) == set(truth) and noised[1]["pts"] != truth[1]["pts"]
    assert all(v["fgm"] <= v["fga"] for v in noised.values() if "fga" in v)
    assert rn.oracle_standin(truth, 0.2, 1, 0) == noised


def test_simulate_runs_a_replay_league_end_to_end():
    first = date(2024, 10, 21)
    rng = np.random.default_rng(4)
    players = {
        k: Member(k, f"P{k}", "x", ("PG", "SG") if k % 2 else ("C", "PF")) for k in range(1, 25)
    }
    lines = {}
    for k in players:
        level = float(rng.uniform(0.6, 1.4))
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
    w = rn.replay_world(setup, lines, truth, 0.1, 0.0, 1, 1, 0)
    arms = {"A": arm("A", "surrogate", "static"), "B": arm("B", "ranking", "static")}
    out = rn.room(setup, w, arms, ["A", "B"], 0)
    assert set(out["by_arm"]) == {"A", "B"} and out["bracket_unread"] is None
    assert initial(setup).day == first
