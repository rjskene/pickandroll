"""A trace (#172, PR trace): one path of one pair played again with a recorder watching.

The hooks only watch: ``policy.queue``'s ``why``, ``run.simulate``'s day records with
``unqueued``, ``run.paired``'s ``on_end`` and ``cli.task_paired``'s ``watch``. A season with the
recorder on is the season with it off, on both tiers. A pair record carries each path's
outcomes (``by_path``), and a trace of a screen's row checks itself on them; a record without
them is checked on its world and seat; one the code no longer gives stops the trace, or is
written marked. The command is played on the tests' made-up data folder with the league made
small, as ``test_sim_screen_run.py`` plays the screen."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import nopeek, policy, shapes
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import trace as tr
from pickandroll.sim.engine import mv
from pickandroll.sim.state import Waiting, initial
from tests.sim.sim_league import KNOBS, arm, make_data_dir, make_setup, replay_of

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
#: Two seats of six slots, four adds a week, both in a one-week final.
SMALL = shapes.one("fixed", shapes.LeagueShape(2, ("PG", "SG", "G", "C", "Util", "BN"), 4, 2, 1))
WEEKS = 3
BASE = {
    "name": "B",
    "tier": "surrogate",
    "knobs": {**KNOBS, "daily_cap": 2, "plan_floor_cats": 0.1, "plan_floor_points": 0.01},
    "opponents": {"kind": "static"},
}
SCREEN = "s"
ROW = "protection_floor-up"


# --------------------------------------------------------------------------- the queue's why
def test_why_names_each_move_the_queue_left_out_and_changes_nothing():
    setup = make_setup()
    state = initial(setup)
    mine = [k for k, _ in state.rosters[1]]
    theirs = state.rosters[2][0][0]
    wire = list(state.pool)
    moves = (
        mv.Move(wire[0], mine[0]),
        mv.Move(wire[0], mine[1]),  # the same add again
        mv.Move(theirs, mine[2]),  # a player on another roster
        mv.Move(wire[1], mine[3]),
        mv.Move(wire[2], mine[4]),  # past the day's cap of two
    )
    decision = policy.Decision(moves, source="exact")
    why: list = []
    with_why = policy.queue(state, 1, decision, 2, 4, False, setup.spots(), setup, why=why)
    assert with_why == policy.queue(state, 1, decision, 2, 4, False, setup.spots(), setup)
    assert [(m.add, w) for m, w in why] == [
        (wire[0], policy.ADDED_TWICE),
        (theirs, policy.NOT_ON_WIRE),
        (wire[2], policy.DAILY_CAP),
    ]
    assert [m.add for m in with_why.pending[1]] == [wire[0], wire[1]]
    # The week's adds spent: every move past them is left out on that rule.
    spent: list = []
    policy.queue(state, 1, decision, 5, 1, False, setup.spots(), setup, why=spent)
    assert {w for _, w in spent} == {policy.WEEK_ADDS}
    assert all(w in policy.UNQUEUED for _, w in why + spent)


def test_why_names_the_claim_rules_in_a_waiver_league():
    setup = replace(make_setup(), waivers="priority")
    state = initial(setup)
    mine = [k for k, _ in state.rosters[1]]
    wire = list(state.pool)
    day = setup.start
    waiting = {
        wire[0]: Waiting(day + timedelta(days=2), 1),
        wire[1]: Waiting(day + timedelta(days=2), 2),
        wire[2]: Waiting(day + timedelta(days=2), 2),
    }
    state = replace(state, waivers=waiting)
    moves = (
        mv.Move(wire[0], mine[0]),  # his own drop, still waiting
        mv.Move(wire[1], mine[0]),  # a claim placed
        mv.Move(wire[1], mine[1]),  # a second claim on one add
        mv.Move(wire[2], mine[0]),  # a drop an open claim takes
    )
    why: list = []
    out = policy.queue(
        state, 1, policy.Decision(moves, source="exact"), 5, 4, False, setup.spots(), setup, why=why
    )
    assert [w for _, w in why] == [policy.READD, policy.ALREADY_CLAIMED, policy.DROP_CLAIMED]
    assert [c.move.add for c in out.claims[1]] == [wire[1]]


# --------------------------------------------------------------------------- the recorder
def digests() -> tuple[dict, object]:
    kept: dict = {}

    def keep(r: rn.DayRecord) -> None:
        kept[(r.day, r.variant)] = nopeek.digest(r)

    return kept, keep


@pytest.mark.parametrize("tier", ["surrogate", "exact"])
def test_the_recorder_only_watches(tier):
    """The pair's result with no hook, with a digest keeper and with the recorder beside it are
    one result, and the day records' digests with and without the recorder are one."""
    setup = make_setup(weeks=3)
    a, b = arm("A", tier, "market"), arm("B", tier, "market", daily_cap=2)
    bare = rn.paired(setup, replay_of(setup, 7, 0), a, b, 1)
    first, keep = digests()
    kept = rn.paired(setup, replay_of(setup, 7, 0), a, b, 1, on_day=keep)
    second, keep2 = digests()
    rec = tr.Recorder({"a": setup, "b": setup}, 1, {"a": a, "b": b})

    def both(r: rn.DayRecord) -> None:
        keep2(r)
        rec.on_day(r)

    ends: list = []

    def end(ra: rn.VariantResult, rb: rn.VariantResult) -> None:
        ends.append((ra, rb))
        rec.on_end(ra, rb)

    watched = rn.paired(setup, replay_of(setup, 7, 0), a, b, 1, on_day=both, on_end=end)
    assert bare == kept == watched
    assert first and first == second
    ((ra, _rb),) = ends
    assert ra.summaries[1]["rank"] == watched["a"]["rank"]
    assert set(ra.totals) >= set(setup.spec.regular_weeks)
    payload = rec.payload()
    json.dumps(payload, allow_nan=False)
    days = [d for d in setup.days if setup.week_of(d) is not None]
    slots = set(setup.roster_slots) | set(mv.HELD)
    for side in tr.SIDES:
        arm_ = payload["arms"][side]
        assert [x["date"] for x in arm_["days"]] == [d.isoformat() for d in days]
        assert [w["week"] for w in arm_["weeks"]] == [w.number for w in setup.calendar.weeks]
        assert all("final" in w for w in arm_["weeks"])
        assert arm_["end"]["outcome"]["rank"] == watched[side]["rank"]
        for x in arm_["days"]:
            assert {p for p, _ in x["roster"]} <= {int(k) for k in payload["players"]}
            assert {s for _, s in x["roster"]} <= slots
            assert {w for *_, w in x["decision"]["unqueued"]} <= set(policy.UNQUEUED)
            assert x["decision"]["tier"] == tier
            assert x["knobs"]["adds_today_cap"] == (1 if side == "a" else 2)
            assert x["knobs"]["season_weight_later"] == 0.0
    assert payload["differ"]["count"] == len(payload["differ"]["days"])


def test_the_recorder_counts_each_side_s_stake_and_the_weeks_results():
    setup = make_setup(weeks=4)
    a, b = arm("A", "surrogate", "static"), arm("B", "surrogate", "static", season_weight=0.5)
    b = replace(b, stake=0.5, named=("stake",))
    rec = tr.Recorder({"a": setup, "b": setup}, 1, {"a": a, "b": b})
    rn.paired(setup, replay_of(setup, 3, 0), a, b, 1, on_day=rec.on_day, on_end=rec.on_end)
    payload = rec.payload()
    for side, reads in (("a", False), ("b", True)):
        days = payload["arms"][side]["days"]
        assert all(x["knobs"]["reads_stake"] is reads for x in days)
        assert all(x["knobs"]["stake_level"] is not None for x in days)
        for x in days:
            k = x["knobs"]
            assert k["season_weight_later"] == pytest.approx(
                k["season_weight"] * (1 - k["stake"] * k["stake_level"])
            )
    weeks = payload["arms"]["a"]["weeks"]
    regular = [w for w in weeks if w["week"] in setup.spec.regular_weeks]
    assert all(w["result"]["outcome"] in ("W", "L", "T") for w in regular)
    assert len(weeks[-1]["standings_before"]) == len(setup.teams)


# --------------------------------------------------------------------------- the command
@pytest.fixture(scope="module", autouse=True)
def small():
    real = rn.replay_setup
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        mp.setitem(ss.GRIDS, "fixed", SMALL)
        mp.setattr(rn, "replay_setup", lambda *a, **k: real(*a, **{**k, "weeks": WEEKS}))
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    """The made-up seasons, a made-up frozen fit, the arms' spec files, and a screen of one
    lever over two paths played on 2024."""
    folder = make_data_dir(tmp_path_factory.mktemp("trace"), wire=120)
    fit = folder / "sim" / "fit" / "2026-01-01"
    fit.mkdir(parents=True)
    (fit / "fit.json").write_text(
        json.dumps({"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}})
    )
    (folder / "B.json").write_text(json.dumps(BASE))
    (folder / "W.json").write_text(json.dumps({**BASE, "pool": 45}))
    argv = ["--data", str(folder), "--rooms", "0", "screen", "--arm", str(folder / "B.json")]
    argv += ["--workers", "1", "--seed", "5", "--paths", "2", "--seasons", "2024"]
    argv += ["--levers", "protection_floor", "--name", SCREEN]
    code, out = run(argv)
    assert code == 0, out
    return folder


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(argv)
    return code, buf.getvalue()


def trace(data: Path, *argv: str) -> tuple[int, str]:
    return run(["--data", str(data), "--rooms", "0", "trace", *argv])


def copy_screen(data: Path, name: str, change=None) -> str:
    """The screen's folder copied under ``name``, its pair's record changed by ``change``."""
    src, dst = reader.screen_dir(data, SCREEN), reader.screen_dir(data, name)
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
    if change is not None:
        path = reader.screen_pair_path(data, name, ROW)
        pair = json.loads(path.read_text())
        change(pair)
        path.write_text(json.dumps(pair))
    return name


def test_a_pair_record_keeps_each_path_s_outcomes_beside_its_means(data):
    pair = reader.read_screen_pair(data, SCREEN, ROW)
    cell = pair["by_path"]["by_season"]["2024"]["prior"]
    assert [x["path"] for x in cell] == [0, 1]
    means = pair["results"]["2024"]["prior"]
    for side in ("a", "b"):
        for k, agg in means[side].items():
            vals = [x[side][k] for x in cell]
            if agg["mean"] is not None:
                assert agg["mean"] == pytest.approx(sum(vals) / len(vals))
    assert "by_path" not in means  # beside the means, not among them


def test_a_trace_of_a_screen_s_row_checks_itself_on_the_path_s_outcomes(data):
    """The screen played the pair's task with no watch; the trace plays the same task with its
    recorder as the watch (``task_paired``'s hook), and the two give one outcome on the path."""
    code, out = trace(data, "--screen", SCREEN, "--row", ROW, "--path", "1")
    assert code == 0, out
    assert "the check: checked" in out
    name = f"screen-{SCREEN}-{ROW}-path1"
    got = reader.read_trace(data, name)
    assert got is not None
    assert reader.trace_path(data, name).parent == data / reader.TRACES_DIR
    assert got["kind"] == "trace" and got["trace_version"] == tr.TRACE_VERSION
    assert got["check"] == {"status": ss.CHECKED, "drift": [], "record_hash_seed": ss.hash_seed()}
    pair = reader.read_screen_pair(data, SCREEN, ROW)
    (on_path,) = [x for x in pair["by_path"]["by_season"]["2024"]["prior"] if x["path"] == 1]
    assert {k: got["outcomes"][k] for k in "ab"} == {"a": on_path["a"], "b": on_path["b"]}
    assert got["pair"]["lever"] == "protection_floor"
    assert got["pair"]["values"] == pair["screen"]["values"]
    assert got["pair"]["specs"] == pair["specs"]
    assert got["seat"] == pair["seat"]["by_path"][1]
    assert (got["season"], got["path"], got["forecaster"]) == (2024, 1, "prior")
    for side in ("a", "b"):
        days = got["arms"][side]["days"]
        assert days and days[0]["date"] < days[-1]["date"]
        assert {s for x in days for _, s in x["roster"]} <= set(SMALL.shapes[0].slots) | set(
            mv.HELD
        )
        assert got["arms"][side]["end"]["outcome"]["rank"] == got["outcomes"][side]["rank"]


def test_a_record_without_paths_outcomes_is_checked_on_its_world_and_seat(data):
    name = copy_screen(data, "old", lambda p: p.pop("by_path"))
    code, out = trace(data, "--screen", name, "--row", ROW, "--path", "0")
    assert code == 0, out
    got = reader.read_trace(data, f"screen-{name}-{ROW}-path0")
    assert got["check"]["status"] == ss.WORLD_ONLY


def test_a_path_the_code_no_longer_gives_stops_unless_drifted(data):
    def moved(p):
        cell = p["by_path"]["by_season"]["2024"]["prior"]
        cell[0]["a"]["rank"] = cell[0]["a"]["rank"] + 1

    name = copy_screen(data, "moved", moved)
    code, out = trace(data, "--screen", name, "--row", ROW, "--path", "0")
    assert code == 1 and "STOPPED" in out and "the path's outcomes" in out
    assert not reader.trace_path(data, f"screen-{name}-{ROW}-path0").exists()
    code, out = trace(data, "--screen", name, "--row", ROW, "--path", "0", "--drifted")
    assert code == 0, out
    got = reader.read_trace(data, f"screen-{name}-{ROW}-path0")
    assert got["check"]["status"] == ss.DRIFTED
    assert got["check"]["drift"] == ["the path's outcomes: the trace's are not the record's"]


def test_a_record_of_another_replay_version_stops_before_any_day(data, monkeypatch):
    name = copy_screen(data, "older", lambda p: p.update(replay_version=ss.REPLAY_VERSION - 1))
    monkeypatch.setattr(ss, "play_trace", lambda *a: pytest.fail("a day was played"))
    code, out = trace(data, "--screen", name, "--row", ROW, "--path", "0")
    assert code == 1 and "replay_version" in out and "nothing played" in out


def test_the_dry_run_plays_nothing_and_writes_nothing(data, monkeypatch):
    monkeypatch.setattr(ss, "play_trace", lambda *a: pytest.fail("a day was played"))
    code, out = trace(data, "--screen", SCREEN, "--row", ROW, "--path", "0", "--dry-run")
    assert code == 0, out
    assert "one task of the pair: about" in out and "nothing played, nothing written" in out
    assert not reader.trace_path(data, f"screen-{SCREEN}-{ROW}-path0").exists()


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--season", "2023"], "plays only a season it searched"),
        (["--h2h", "each_category"], "names no world flag (--h2h)"),
        (["--seed", "9"], "names no world flag (--seed)"),
        (["--path", "7"], "is not one of the pair's 2 paths"),
        (["--forecaster", "espn"], "--forecaster 'espn'"),
    ],
)
def test_a_trace_of_a_record_is_refused_by_name(data, argv, says):
    args = ["--screen", SCREEN, "--row", ROW, *(["--path", "0"] if "--path" not in argv else [])]
    code, out = trace(data, *args, *argv)
    assert code == 2 and says in out, out


def test_a_missing_row_a_missing_screen_and_another_hash_seed_are_refused(data):
    code, out = trace(data, "--screen", SCREEN, "--row", "nope", "--path", "0")
    assert code == 2 and "no played pair 'nope'" in out
    code, out = trace(data, "--screen", "none", "--row", ROW, "--path", "0")
    assert code == 2 and "no screen named 'none'" in out
    name = copy_screen(data, "seeded", lambda p: p.update(hash_seed="4242"))
    code, out = trace(data, "--screen", name, "--row", ROW, "--path", "0")
    assert code == 2 and "PYTHONHASHSEED=4242" in out


def test_a_tune_s_confirmation_pair_is_refused_and_its_search_seasons_leave_it_out(data):
    folder = reader.tune_dir(data, "t")
    folder.mkdir(parents=True)
    (folder / reader.TUNE_FILE).write_text(
        json.dumps({"spec": {"world": {"seasons": [2023, 2024]}, "confirm": 2024}})
    )
    (folder / "confirm-run.json").write_text(
        json.dumps({"design": "paired", "seasons": [2024], "tune": {"confirmation": "run"}})
    )
    code, out = trace(data, "--tune", "t", "--row", "confirm-run", "--path", "0")
    assert code == 2 and "never plays a tune's confirmation season" in out
    got = ss.TraceFrom(
        "tune", "t", "k", {"spec": {"world": {"seasons": [2023, 2024]}, "confirm": 2024}}, {}
    )
    assert got.seasons() == [2023]


def test_a_trace_s_name_on_file_is_refused(data):
    code, out = trace(data, "--screen", SCREEN, "--row", ROW, "--path", "0", "--name", "twice")
    assert code == 0, out
    code, out = trace(data, "--screen", SCREEN, "--row", ROW, "--path", "0", "--name", "twice")
    assert code == 2 and "is on file" in out


def test_the_arms_form_plays_one_season_unchecked_and_refuses_what_replay_refuses(data):
    arms = [str(data / "B.json"), str(data / "W.json")]
    code, out = trace(data, "--arms", *arms, "--seasons", "2024", "--path", "0", "--seed", "5")
    assert code == 0, out
    got = reader.read_trace(data, "arms-2024-path0")
    assert got["check"]["status"] == ss.UNCHECKED and got["source"] == {"form": "arms"}
    code, out = trace(data, "--arms", *arms, "--seasons", "2025", "--path", "0")
    assert code == 2 and "2025 is the hold-out" in out
    code, out = trace(data, "--arms", *arms, "--seasons", "2023,2024", "--path", "0")
    assert code == 2 and "a trace plays one season" in out
    code, out = trace(data, "--arms", *arms, "--path", "0")
    assert code == 2 and "names its one season" in out
