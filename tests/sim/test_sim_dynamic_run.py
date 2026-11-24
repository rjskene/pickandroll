"""SEASON SIM (#172, PR dynamic knobs): the commands with overrides.

A replay's record keeps each arm's knobs as played (``resolved``) beside the specs as given, and
in a run where an arm names an override, every arm's seat's days in each situation. A screen
names a split lever by ``--levers`` alone: its rows are the lever's nudges in each situation,
each an override, played as a replay plays them; its record keeps the baseline's knobs as
played. The split rows' rules are pinned on ``screen.rows_of``; the tune's second stage is
``test_sim_tune_run``'s. Played on the tests' made-up data folder with the league made small, as
``test_sim_screen_run.py`` plays the screen."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import policy, shapes
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from tests.sim.sim_league import KNOBS, make_data_dir

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
#: Four seats of six slots, four adds a week, two in a one-week final: a league with a cut line,
#: so ``standing`` names a situation (with two seats both in the final it names none).
SMALL = shapes.one("fixed", shapes.LeagueShape(4, ("PG", "SG", "G", "C", "Util", "BN"), 4, 2, 1))
WEEKS = 4
BASE = {
    "name": "B",
    "tier": "surrogate",
    "knobs": {**KNOBS, "daily_cap": 2, "plan_floor_cats": 0.1, "plan_floor_points": 0.01},
    "opponents": {"kind": "static"},
}
#: The baseline with an override: a third add on a day the seat is behind the cut line.
DYN = {**BASE, "name": "D", "knobs": {**BASE["knobs"], "daily_cap@standing.behind": 3}}


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
    folder = make_data_dir(tmp_path_factory.mktemp("dynamic"), wire=120)
    fit = folder / "sim" / "fit" / "2026-01-01"
    fit.mkdir(parents=True)
    (fit / "fit.json").write_text(
        json.dumps({"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}})
    )
    for spec in (BASE, DYN):
        (folder / f"{spec['name']}.json").write_text(json.dumps(spec))
    (folder / "bad.json").write_text(
        json.dumps({**BASE, "name": "X", "knobs": {**BASE["knobs"], "daily_cap@phase.late": 3}})
    )
    return folder


def run(data: Path, *argv: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(["--data", str(data), "--rooms", "0", *argv])
    return code, buf.getvalue()


def common(*more: str) -> list[str]:
    return ["--workers", "1", "--seed", "5", "--paths", "2", "--seasons", "2024", *more]


@pytest.fixture(scope="module")
def replayed(data: Path) -> dict:
    code, out = run(data, "replay", "--arms", str(data / "B.json"), str(data / "D.json"), *common())
    assert code == 0, out
    (path,) = sorted((data / reader.RUNS_DIR).glob("*.json"))
    return json.loads(path.read_text())


def test_a_replay_keeps_each_arm_s_knobs_as_played_beside_the_specs(replayed):
    p = replayed
    assert p["replay_version"] == ss.REPLAY_VERSION == 23
    assert p["specs"] == {"a": BASE, "b": DYN}
    a, b = p["resolved"]["a"]["knobs"], p["resolved"]["b"]["knobs"]
    # Every knob, the take-in's five at live's default where the spec leaves them out, then the
    # override.
    assert list(a) == list(policy.KNOBS) and list(b) == [*policy.KNOBS, "daily_cap@standing.behind"]
    assert {k: a[k] for k in policy.TAKEIN_KNOBS} == {k: KNOBS[k] for k in policy.TAKEIN_KNOBS}
    assert b["daily_cap@standing.behind"] == 3 and b["daily_cap"] == a["daily_cap"] == 2


def test_a_run_that_names_an_override_counts_both_arms_days_in_each_situation(replayed):
    text = json.dumps(replayed)
    for name in ct.SITUATIONS:
        assert f'"{name}"' in text
    assert "days_line" in ct.metrics_in([{"days_line": 1.0}])


def test_an_override_with_a_bad_name_is_refused_before_any_path(data: Path):
    code, out = run(
        data, "replay", "--arms", str(data / "B.json"), str(data / "bad.json"), *common()
    )
    assert code == 2 and "'late' is not a situation of phase" in out


# --------------------------------------------------------------------------- the screen
def test_a_screen_plays_a_split_lever_only_when_named(data: Path):
    lever = "daily_cap@standing.line"
    code, out = run(
        data, "screen", "--arm", str(data / "B.json"), *common("--levers", lever), "--name", "split"
    )
    assert code == 0, out
    rec = reader.read_screen(data, "split")
    assert rec["screen_version"] == sc.SCREEN_VERSION == 8
    assert rec["resolved"] == {"knobs": dict(rn.arm_of(BASE).knobs)}
    rows = {r["key"]: r for r in rec["rows"]}
    assert set(rows) == {f"{lever}-minus", f"{lever}-plus"}
    for tag, value in (("minus", 1), ("plus", 3)):
        row = rows[f"{lever}-{tag}"]
        assert row["status"] == sc.PLAY and row["override"] == lever
        assert row["values"] == {"a": 2, "b": value}
        pair = reader.read_screen_pair(data, "split", f"{lever}-{tag}")
        assert pair["specs"]["b"]["knobs"][lever] == value
        assert pair["resolved"]["b"]["knobs"][lever] == value
    # A screen of the list names no split lever.
    flags = common("--levers", "daily_cap", "--name", "plain", "--dry-run")
    code, out = run(data, "screen", "--arm", str(data / "B.json"), *flags)
    assert code == 0 and "daily_cap@" not in out, out


def test_a_name_that_is_no_split_lever_is_refused_by_name(data: Path):
    for name, says in (
        ("system@phase", "is no split lever"),
        ("daily_cap@phase.late", "is no split lever"),
        ("pol", "is not in the screen's list"),
    ):
        code, out = run(
            data, "screen", "--arm", str(data / "B.json"), *common("--levers", name), "--dry-run"
        )
        assert code == 2 and says in out, (name, out)
