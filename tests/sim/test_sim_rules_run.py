"""The league rules on a run (#172, PR D4c): ``replay --scoring``, ``--points`` and ``--held``,
the record, Rule 1 (with nothing named nothing moves), a points league's metrics, a held slot
used and given back, the reads table and its refusal both ways, and one set of rules on every
path of a grid."""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import forecast as fc
from pickandroll.sim import league as lg
from pickandroll.sim import policy, shapes
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, mv
from tests.sim.sim_league import KNOBS, POSITIONS, arm, make_data_dir
from tests.sim.test_sim_points import PERIOD_ONE, made_up_season

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
WHEN = ("started_at", "finished_at")
#: Four made-up shapes standing in for the full grid (as in ``test_sim_grid.py``).
SMALL = shapes.Grid("small", (10, 12), (shapes.SLOTS,), (2, None), ((6, 3),))
#: The world's seed and path on which the surrogate seat holds a player in IL and takes him back
#: (``test_a_surrogate_seat_holds_a_player_in_il_and_takes_him_back``, which says how it was found).
HELD_PATH = (1, 0)
#: The world's seed and path on which the surrogate seat moves in a points league
#: (``test_a_surrogate_seat_in_a_points_league_adds_and_holds``, which says how it was found).
POINTS_PATH = (1, 1)


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


SPECS = {
    "S": {"tier": "static"},
    "R": {"tier": "ranking"},
    # Two exact arms that execute the week plan and differ only on the points plan floor.
    "E": {"tier": "exact", "with_plan": True, "execute_plan": True},
    "F": {
        "tier": "exact",
        "with_plan": True,
        "execute_plan": True,
        "knobs": {**KNOBS, "plan_floor_points": 5.0},
    },
}


@pytest.fixture(scope="module")
def wire(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120 (191 draftable players in 2024)."""
    data = make_data_dir(tmp_path_factory.mktemp("rules-wire"), wire=120)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, extra in SPECS.items():
        spec = {"name": name, "knobs": KNOBS, "opponents": {"kind": "static"}, **extra}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def replay(data: Path, *extra: str, seed: str = "5") -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--seed", seed, *extra])
    return code, buf.getvalue()


def spec(data: Path, *names: str) -> list[str]:
    return [str(data / f"{n}.json") for n in names]


def written(out: str) -> dict:
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return json.loads(Path(line.removeprefix("written: ")).read_text())


def test_league_rules_out_of_the_plan_are_refused_by_name_before_any_path(wire: Path):
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--points", "pts=1"), "--points is a points league's table; it is read only with"),
        (("--held", "NA=1"), "--held NA: the held slots a league may hold here are IL, IL+"),
        (("--held", "IL=3"), "--held IL=3: IL is 0 to 2"),
        (("--scoring", "points", "--points", "fpts=1"), "--points fpts: the stats of a line"),
        (("--scoring", "points", "--points", "pts=0"), "--points 'pts=0': every weight is zero"),
    ):
        code, out = replay(wire, *room, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out


def test_with_nothing_named_nothing_moves(wire: Path):
    """Rule 1: ``--scoring categories`` named and nothing named give one payload, version 13, its
    league block naming today's rules; no line names them."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1")
    runs, outs = [], []
    for extra in ((), ("--scoring", "categories")):
        code, out = replay(wire, *room, *extra)
        assert code == 0, out
        runs.append(written(out))
        outs.append(out)
    one, two = runs
    assert {k: v for k, v in one.items() if k not in WHEN} == {
        k: v for k, v in two.items() if k not in WHEN
    }
    assert one["replay_version"] == 21
    assert one["league"]["rules"] == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": "one_win",
    }
    assert "points_note" not in one["league"]
    assert all("league rules" not in out for out in outs)


def test_a_points_run_scores_one_result_a_week_and_says_its_rules(wire: Path, monkeypatch):
    seen: list[dict] = []
    real = lg.summary

    def spy(result, me):
        out = real(result, me)
        seen.append(out)
        return out

    monkeypatch.setattr(lg, "summary", spy)
    code, out = replay(
        wire, "--seats", *spec(wire, "R", "S"), "--paths", "1", "--scoring", "points"
    )
    assert code == 0, out
    assert "league rules, on every path: points on ESPN's default table, no held slot" in out
    p = written(out)
    rules = p["league"]["rules"]
    assert rules == {"scoring": "points", "points": dict(shapes.POINTS_DEFAULT), "held": []}
    assert p["league"]["points_note"] == ss.POINTS_NOTE
    # Every team's season: its category wins are its matchup wins.
    assert len(seen) == 12
    assert all(s["category_wins"] == s["matchup_wins"] for s in seen)
    # A run's own table.
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--paths", "1", "--scoring", "points", "--points", "pts=1,reb=1.2,ast=1.5,stl=3,blk=3,tov=-1", "--dry-run")  # fmt: skip
    assert code == 0, out
    assert (
        "league rules, on every path: points on the table pts 1, reb 1.2, ast 1.5, stl 3, blk 3, "
        "tov -1, no held slot" in out
    )


def test_a_run_with_a_held_slot_drafts_the_active_spots_and_records_it(wire: Path, monkeypatch):
    """``--held IL=1``: every path's league has the slot after the bench, the draft took the
    active spots only (the slot starts the season empty), the audit voids no path and the record
    names the slot."""
    setups = []
    real = rn.replay_setup

    def spy(*a, **k):
        s = real(*a, **k)
        setups.append(s)
        return s

    monkeypatch.setattr(rn, "replay_setup", spy)
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--paths", "1", "--held", "IL=1")
    assert code == 0, out
    assert "league rules, on every path: the nine categories, one IL slot" in out
    p = written(out)
    assert p["league"]["rules"] == {
        "scoring": "categories",
        "points": None,
        "held": ["IL"],
        "h2h": "one_win",
    }
    assert p["audit"]["paths_voided"] == 0 and p["audit"]["breaches"] == []
    assert len(setups) == 2  # the run's read of what its seats read, then the path
    for played in setups:
        assert played.roster_slots == (*shapes.SLOTS, "IL")
        assert played.spots() == len(shapes.SLOTS)
        assert all(
            len(r) == played.spots() and all(slot not in mv.HELD for _, slot in r)
            for r in played.rosters.values()
        )


def absent_season(league_rules: shapes.LeagueRules):
    """The made-up season of ``test_sim_points`` with positions varied, in which a quarter of
    the players miss seven games in a row, every player's schedule given (so a gap is an
    absence), as the replay's league under ``league_rules``: two teams, six weeks. Returns the
    setup, the lines and the players who miss games."""
    lines, players, projection = made_up_season()
    players = {k: replace(m, positions=POSITIONS[k % len(POSITIONS)]) for k, m in players.items()}
    out = {k for k in lines if k % 4 == 1}
    for k in out:
        lines[k] = {d: x for d, x in lines[k].items() if not 10 <= (d - PERIOD_ONE).days < 24}
    scheduled = {k: [PERIOD_ONE + timedelta(2 * i) for i in range(80)] for k in lines}
    setup = rn.replay_setup(
        2024,
        lines,
        players,
        projection,
        PERIOD_ONE,
        scheduled,
        teams=2,
        slots=league_rules.slots(shapes.SLOTS),
        weeks=6,
        playoff_weeks=1,
        playoff_teams=2,
        scoring=league_rules.scoring,
        points=league_rules.table,
    )
    return setup, lines, out


def test_a_surrogate_seat_holds_a_player_in_il_and_takes_him_back():
    """The replay's league under ``LeagueRules(held=("IL",))`` on a made-up season (two teams,
    six weeks) in which a quarter of the players miss seven games in a row: the surrogate seat
    hears its player out, holds him in IL with an add into the spot that frees, and takes him
    back when he returns, the weakest player sent; the audit finds nothing. HELD_PATH is the
    first of seeds 1 to 3 and paths 0 and 1, tried in that order, on which the seat holds a
    player (when it was found two of the six did not: its players are out on days it does not
    decide; since the format PR, the seat weighing the matchup's odds, three of the six do
    not)."""
    setup, lines, out = absent_season(shapes.LeagueRules(held=("IL",)))
    assert all(slot not in mv.HELD for r in setup.rosters.values() for _, slot in r)
    u = arm("U", "surrogate", opponents="static")
    held: dict[int, list[date]] = {}
    back: dict[int, date] = {}

    def on_day(r: rn.DayRecord) -> None:
        for k, slot in r.state.rosters[1]:
            if slot in mv.HELD:
                held.setdefault(k, []).append(r.day)
            elif k in held:
                back.setdefault(k, r.day)

    w = rn.replay_world(setup, lines, 1, *HELD_PATH)
    (result,) = rn.simulate(setup, w, [{**rn.opponents_of(setup, u, 1), 1: u.seat()}], None, on_day)
    assert result.breaches == ()
    ((k, days),) = held.items()
    assert k in out and back[k] > days[-1]
    counts = result.counts[1]
    assert counts["held_stints"] == 1 and counts["held_days"] == len(days)
    assert counts["forced_drops"] == 1 and counts["held_refused"] == 0


def test_a_surrogate_seat_in_a_points_league_adds_and_holds():
    """The same season as a points league on ESPN's default table: with no held slot the
    surrogate seat lands an add, and with an IL slot it holds a player too; the audit finds
    nothing. The evaluator reads each opponent's projected fantasy points and each side's score
    so far. When it read the opponents' weeks with no table (``policy.problem_of``, PR 2b to PR
    D4c), every week looked won outright and no move gained: on each of seeds 1 to 3 and paths 0
    and 1 the seat landed nothing and held nobody. POINTS_PATH is the first of those six, in that
    order, on which it now lands an add (two of the six do)."""
    u = arm("U", "surrogate", opponents="static")
    for held, counts in (((), ("landed",)), (("IL",), ("landed", "held_stints"))):
        setup, lines, _ = absent_season(shapes.LeagueRules("points", shapes.POINTS_DEFAULT, held))
        assert setup.scoring == "points"
        w = rn.replay_world(setup, lines, 1, *POINTS_PATH)
        (result,) = rn.simulate(setup, w, [{**rn.opponents_of(setup, u, 1), 1: u.seat()}])
        assert result.breaches == ()
        assert all(result.counts[1][c] >= 1 for c in counts), (held, result.counts[1])


def test_the_reads_table_and_the_refusal_follow_the_run_s_scoring(wire: Path):
    """Two exact arms that execute the plan and differ only on ``plan_floor_points``: the same
    seat in a categories run, refused by name with what would make it read; two seats in a
    points run, where the knob is read and ``plan_floor_cats`` is not. In a categories run
    ``plan_floor_cats`` is read where every category counts, and in a one-win run nobody reads it
    (the format PR: the plan floor is the engine's own). The points side is read
    as the run reads it (``read_season``, ``same_seats``), before any path: a dry run would time
    a path of two exact arms."""
    code, out = replay(wire, "--arms", *spec(wire, "E", "F"), "--paths", "1", "--dry-run")
    assert code == 2, out
    assert (
        "refused: arms a and b are the same seat: they differ only in plan_floor_points (a "
        "categories league; read by the exact tier drawing and executing the week plan, or "
        "executing queue, in a points league)" in out
    )
    arms = {k: rn.arm_of(json.loads((wire / f"{n}.json").read_text())) for k, n in (("a", "E"), ("b", "F"))}  # fmt: skip
    points = shapes.LeagueRules("points", shapes.POINTS_DEFAULT)
    each = shapes.LeagueRules(h2h=EACH_CATEGORY)
    for league_rules, floors in (
        (shapes.PLAIN, (policy.ONE_WIN_FLOOR, "a categories league")),
        (each, (policy.READ, "a categories league")),
        (points, ("a points league", policy.READ)),
    ):
        r = ss.read_season(wire, 2024, fc.parse("prior"), None, arms, 5, "stat", league_rules)
        assert (r.shape.scoring, r.shape.h2h) == (league_rules.scoring, league_rules.h2h)
        table = policy.reads(arms["a"], r.shape, False)
        assert (table["plan_floor_cats"], table["plan_floor_points"]) == floors
        same = ss.same_seats(arms, [r.shape], rivals=True)
        assert (same is None) == (league_rules is points)


def test_every_path_of_a_grid_plays_the_run_s_rules(wire: Path, monkeypatch):
    """On the made-up grid of four shapes every path's league, whatever its shape, is played
    under the run's one set of rules; the no-peek check's league says them."""
    monkeypatch.setitem(ss.GRIDS, "full", SMALL)
    seen: list[tuple] = []
    real = rn.replay_setup

    def spy(*a, **k):
        s = real(*a, **k)
        seen.append((len(s.teams), s.scoring, s.points, s.roster_slots[len(shapes.SLOTS) :]))
        return s

    monkeypatch.setattr(rn, "replay_setup", spy)
    rules = ("--held", "IL=1,IL+=1", "--scoring", "points")
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--grid", "full", "--paths", "4", *rules)  # fmt: skip
    assert code == 0, out
    table = dict(shapes.POINTS_DEFAULT)
    played = seen[1:]  # the first is the run's read of what its seats read
    assert sorted(n for n, *_ in played) == [10, 10, 12, 12]
    assert all(x[1:] == ("points", table, ("IL", "IL+")) for x in seen)
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--grid", "full", "--no-peek", "2023-11-06", *rules)  # fmt: skip
    assert code == 0 and "agree through 2023-11-06" in out, out
    assert "points on ESPN's default table, one IL slot and one IL+ slot" in out


def test_waivers_out_of_the_plan_are_refused_by_name_before_any_path(wire: Path):
    """PR Fa: a wait is a waiver league's, a whole number of days from 1 to 7 (PR Fb lifts the
    refusal of ``--waivers faab``)."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--waivers", "fifo"), "--waivers fifo: one of none, priority"),
        (("--waiver-days", "2"), "--waiver-days 2: a dropped player's wait is a waiver league's"),
        (("--waivers", "priority", "--waiver-days", "0"), "--waiver-days 0: a dropped player"),
        (("--waivers", "priority", "--waiver-days", "8"), "--waiver-days 8: a dropped player"),
        (("--waivers", "priority", "--waiver-days", "two"), "--waiver-days two: a whole number"),
        # PR Fb: a budget and the rivals' scale are a FAAB league's.
        (("--budget", "50"), "--budget 50: a budget and the rivals' bids are a FAAB league's"),
        (("--rival-scale", "2"), "--rival-scale 2: a budget and the rivals' bids are a FAAB"),
        (("--waivers", "priority", "--budget", "50"), "--budget 50: a budget and the rivals'"),
        (("--waivers", "faab", "--budget", "0"), "--budget 0: a team starts with 1 to 1000"),
        (("--waivers", "faab", "--rival-scale", "0"), "--rival-scale 0: a number above 0"),
    ):
        code, out = replay(wire, *room, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out


def test_a_waiver_run_records_its_rules_its_audit_and_its_claims(wire: Path):
    """``--scoring points --waivers priority --waiver-days 3``: the league block's rules name
    the waivers and the wait, the execution model has a name of its own, the audit holds the
    two waiver rules, the counts count the claims and a points run's season scale says what its
    gain is."""
    code, out = replay(
        wire,
        "--seats",
        *spec(wire, "R", "S"),
        "--paths",
        "1",
        "--scoring",
        "points",
        "--waivers",
        "priority",
        "--waiver-days",
        "3",
    )
    assert code == 0, out
    rules = shapes.LeagueRules("points", shapes.POINTS_DEFAULT, (), "priority", 3)
    assert f"league rules, on every path: {rules.label()}" in out
    assert rules.label().endswith(", waivers by priority after 3 days")
    p = written(out)
    assert p["replay_version"] == 21
    assert p["league"]["rules"] == {
        "scoring": "points",
        "points": dict(shapes.POINTS_DEFAULT),
        "held": [],
        "waivers": "priority",
        "waiver_days": 3,
        "waiver_rule": "dropped",
    }
    assert p["executions"] == policy.EXECUTIONS_PRIORITY
    assert [r["name"] for r in p["audit"]["rules"]][-2:] == ["waiver_wait", "claim_priority"]
    assert p["audit"]["paths_voided"] == 0
    assert set(p["counts"]["note"]) == {*ct.METRICS, *ct.CLAIMS, "pooling"}
    for row in p["counts"]["by_season"]["2024"]["prior"].values():
        assert all(row[m]["mean"] is not None for m in ct.CLAIMS), row
    assert p["season_scale"]["note"] == ss.scale_note("points") != ss.SCALE_NOTE
    assert ss.scale_note("categories", EACH_CATEGORY) == ss.SCALE_NOTE
    assert ss.scale_note("categories") == ss.SCALE_NOTE + ss.SCALE_NOTE_ONE_WIN


def test_a_faab_run_records_its_rules_its_audit_and_its_bids(wire: Path):
    """``--waivers faab --budget 50 --rival-scale 2`` (PR Fb): the league block's rules name the
    budget and the scale and its note says how the bids are made, the execution model has a
    name of its own, the audit holds the wait and the three bid rules in place of
    ``claim_priority``, and the counts count the dollars and the bids after the claims."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1")
    faab = ("--waivers", "faab", "--budget", "50", "--rival-scale", "2")
    code, out = replay(wire, *room, *faab)
    assert code == 0, out
    rules = shapes.LeagueRules(waivers="faab", budget=50, rival_scale=2.0)
    assert f"league rules, on every path: {rules.label()}" in out
    p = written(out)
    assert p["replay_version"] == ss.REPLAY_VERSION == 21
    assert p["league"]["rules"] == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": "one_win",
        "waivers": "faab",
        "waiver_days": shapes.WAIVER_DAYS,
        "waiver_rule": "dropped",
        "budget": 50,
        "rival_scale": 2.0,
        "rival_bids": "assumed",
    }
    assert p["league"]["faab_note"] == ss.FAAB_NOTE and "flags are not modelled" in ss.FAAB_NOTE
    assert p["executions"] == policy.EXECUTIONS_FAAB
    names = [r["name"] for r in p["audit"]["rules"]]
    assert names[-4:] == ["waiver_wait", "budget_floor", "bid_paid", "bid_order"]
    assert "claim_priority" not in names and p["audit"]["paths_voided"] == 0
    assert set(p["counts"]["note"]) == {*ct.METRICS, *ct.CLAIMS, *ct.BIDS, "pooling"}
    for row in p["counts"]["by_season"]["2024"]["prior"].values():
        assert set(ct.BIDS) <= set(row), row
        assert row["dollars_spent"]["mean"] + row["dollars_left"]["mean"] == 50, row
    # By priority the league block has no note (its rules and counts are pinned by
    # ``test_a_waiver_run_records_its_rules_its_audit_and_its_claims``).
    priority = shapes.LeagueRules(waivers="priority")
    by_priority = ss.league_block(shapes.FIXED_GRID, [], [], priority)
    assert "faab_note" not in by_priority and "budget" not in by_priority["rules"]


def test_a_pair_that_differs_only_on_faab_sizing_is_one_seat_without_faab_and_two_with_it(
    wire: Path,
):
    """Two surrogate arms that differ only on ``faab_sizing`` (PR Fb): the same seat in a run
    without waivers or by priority, refused by name with what would make it read; two seats in
    a FAAB run, where a seat that bids reads it. Read as the run reads it (``read_season``,
    ``same_seats``), before any path."""
    for name, sizing in (("G", None), ("H", 2.0)):
        body = {"name": name, "tier": "surrogate", "knobs": {**KNOBS, "faab_sizing": sizing}}
        (wire / f"{name}.json").write_text(json.dumps({**body, "opponents": {"kind": "static"}}))
    code, out = replay(wire, "--arms", *spec(wire, "G", "H"), "--paths", "1", "--dry-run")
    assert code == 2, out
    assert "refused: arms a and b are the same seat: they differ only in faab_sizing (" in out
    arms = {k: rn.arm_of(json.loads((wire / f"{n}.json").read_text())) for k, n in (("a", "G"), ("b", "H"))}  # fmt: skip
    for waivers in ("none", "priority", "faab"):
        league_rules = shapes.LeagueRules(waivers=waivers)
        r = ss.read_season(wire, 2024, fc.parse("prior"), None, arms, 5, "stat", league_rules)
        assert r.shape.waivers == waivers
        read = policy.reads(arms["a"], r.shape, False)["faab_sizing"] == policy.READ
        assert read == (waivers == "faab")
        assert (ss.same_seats(arms, [r.shape], rivals=True) is None) == read


def test_the_waiver_rule_out_of_the_plan_is_refused_by_name_before_any_path(wire: Path):
    """PR Fc: which adds are claims is a waiver league's, dropped or continuous."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1", "--dry-run")
    for flags, why in (
        (("--waiver-rule", "continuous"), "--waiver-rule continuous: which adds are claims is a"),
        (("--waivers", "faab", "--waiver-rule", "fifo"), "--waiver-rule fifo: one of dropped, "),
    ):
        code, out = replay(wire, *room, *flags)
        assert code == 2 and f"refused: {why}" in out, out
        assert "tasks (" not in out


def test_a_continuous_run_records_its_rule_its_model_its_notes_and_its_audit(wire: Path):
    """``--waivers faab --waiver-rule continuous`` (PR Fc): the league block's rules name the
    rule, its notes say every add is a claim (``waiver_rule_note``, and ``faab_note``'s clause on
    which adds are bid on), the execution model has a name of its own, the audit holds
    ``claims_only`` last and finds nothing, and every add landed is a claim won. The line that
    says the rules is the one a dry run and the no-peek check print (``LeagueRules.label``)."""
    room = ("--seats", *spec(wire, "R", "S"), "--paths", "1")
    code, out = replay(wire, *room, "--waivers", "faab", "--waiver-rule", "continuous")
    assert code == 0, out
    rules = shapes.LeagueRules(waivers="faab", waiver_rule="continuous")
    assert f"league rules, on every path: {rules.label()}" in out and "continuous waivers" in out
    p = written(out)
    assert p["replay_version"] == 21 and "12: continuous waivers" in p["replay_version_why"]
    assert p["league"]["rules"] == {**rules.payload(), "waiver_rule": "continuous"}
    assert p["league"]["faab_note"] == ss.FAAB_NOTE_CONTINUOUS
    assert p["league"]["waiver_rule_note"] == ss.WAIVER_RULE_NOTE
    assert p["executions"] == policy.EXECUTIONS_CONTINUOUS_FAAB == "claims_only_by_sealed_bids"
    names = [r["name"] for r in p["audit"]["rules"]]
    assert names[-1] == "claims_only" and p["audit"]["paths_voided"] == 0
    for row in p["counts"]["by_season"]["2024"]["prior"].values():
        assert row["landed"]["mean"] == row["claims_won"]["mean"], row
        assert row["gone"]["mean"] == row["claims_failed"]["mean"], row
