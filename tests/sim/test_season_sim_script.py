"""The simulator's commands (#172, PR 1; ``pickandroll.sim.cli``): the guard, the seasons
argument, the fit command on a synthetic cache."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import audit, checks, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import forecast as fc
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim.engine import EACH_CATEGORY, wk
from tests.sim.sim_fixtures import synthetic_lines
from tests.sim.test_gamelogs import body, entry, line

MAC = ZoneInfo("America/Toronto")
#: What the commands' clock reads in every test here: a weekday morning outside the routines'
#: window. Without it a suite run between 04:45 and 06:45 local time has the guard refuse every
#: command (one failed test and twelve errors on 2026-10-31).
BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=MAC)


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def test_guard_refuses_the_quiet_window_rooms_and_unannounced_long_runs():
    quiet = datetime(2026, 10, 27, 5, 30, tzinfo=MAC)
    ok, why = ss.guard(now=quiet, rooms=0, nice=None)
    assert not ok and "window" in why
    busy = datetime(2026, 10, 27, 9, 0, tzinfo=MAC)
    ok, why = ss.guard(now=busy, rooms=2, nice=None)
    assert not ok and "room" in why
    ok, why = ss.guard(expected_hours=6, now=busy, rooms=0, nice=None)
    assert not ok and "announced on the tracker" in why and "--announced" in why
    assert ss.guard(expected_hours=6, now=busy, rooms=0, announced=True, nice=None) == (True, "ok")
    lowered: list[int] = []
    assert ss.guard(now=busy, rooms=0, nice=lowered.append) == (True, "ok")
    assert lowered == [ss.NICE]
    assert ss.in_quiet_window(datetime(2026, 10, 27, 4, 45, tzinfo=MAC))
    assert not ss.in_quiet_window(datetime(2026, 10, 27, 6, 45, tzinfo=MAC))


def test_main_reads_the_guards_clock_through_the_seam(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ss, "now_local", lambda: datetime(2026, 10, 27, 5, 30, tzinfo=MAC))
    assert ss.main(["--data", str(tmp_path), "--rooms", "0", "fit"]) == 2
    assert "refused: inside the routines' window" in capsys.readouterr().out
    monkeypatch.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
    assert ss.main(["--data", str(tmp_path), "--rooms", "0", "fit"]) == 2  # no cache: refused later
    assert "routines' window" not in capsys.readouterr().out


def test_parse_seasons():
    assert ss.parse_seasons("2022-2026") == [2022, 2023, 2024, 2025, 2026]
    assert ss.parse_seasons("2022,2024") == [2022, 2024]


def _cache(data: Path, seasons: list[int]) -> None:
    folder = data / ss.LOGS_DIR
    folder.mkdir(parents=True)
    for i, season in enumerate(seasons):
        rows = synthetic_lines(seed=100 + i, players=12, games=40, season=season)
        players: dict[str, list] = {}
        for ln in rows:
            raw = (
                {
                    k: v
                    for k, v in {
                        "0": ln.stats.get("pts"),
                        "1": ln.stats.get("blk"),
                        "2": ln.stats.get("stl"),
                        "3": ln.stats.get("ast"),
                        "6": ln.stats.get("reb"),
                        "11": ln.stats.get("tov"),
                        "14": ln.stats.get("fga"),
                        "16": ln.stats.get("fta"),
                        "17": ln.stats.get("threes"),
                        "40": ln.minutes,
                    }.items()
                    if v is not None
                }
                if ln.played
                else {}
            )
            players.setdefault(ln.player, []).append(entry(season, ln.period, raw))
        body_ = {
            "players": [
                {"player": {"id": pid, "fullName": pid, "stats": stats}}
                for pid, stats in players.items()
            ]
        }
        (folder / f"{season}.json").write_text(json.dumps({"season": season, "body": body_}))


def test_fit_refuses_the_hold_out_and_writes_the_frozen_fit(tmp_path: Path):
    _cache(tmp_path, [2023, 2024, 2025])
    with pytest.raises(ss.fitmod.HoldOutError):
        ss.run_fit([2023, 2024, 2025], tmp_path)
    with pytest.raises(ss.fitmod.HoldOutError):
        ss.run_fit([2023, 2024], tmp_path, extra_hold_out=2024)
    payload, sha, pooled = ss.run_fit([2023, 2024], tmp_path)
    assert payload["seasons"] == [2023, 2024] and payload["hold_out"] == ss.HOLD_OUT == 2025
    assert payload["tau"] is None and payload["refresh"] is None
    assert "extra_hold_out" not in payload["parameters"]
    assert pooled.hazard.players == 24
    assert len(sha) == 64
    data = ["--data", str(tmp_path), "--rooms", "0"]
    assert ss.main([*data, "fit", "--seasons", "2023-2024"]) == 0
    written = list((tmp_path / ss.FIT_DIR).glob("*/fit.json"))
    assert len(written) == 1
    assert json.loads(written[0].read_text())["hold_out"] == 2025
    assert (written[0].parent / "fit.sha256").read_text().strip() == sha
    # The named hold-out is refused whatever the flags say: a typo in --hold-out does not
    # let 2025 into a fit, and the flag cannot remove it.
    assert ss.main([*data, "fit", "--seasons", "2022-2026", "--hold-out", "2024"]) == 2
    assert ss.main([*data, "fit", "--seasons", "2023-2025"]) == 2
    assert ss.main([*data, "fit", "--seasons", "2023-2025", "--hold-out", "2025"]) == 2
    # The flag adds a second hold-out, recorded in the payload's parameters.
    assert ss.main([*data, "fit", "--seasons", "2023", "--hold-out", "2024", "--dry-run"]) == 0
    extra, _, _ = ss.run_fit([2023], tmp_path, extra_hold_out=2024)
    assert extra["parameters"]["extra_hold_out"] == 2024 and extra["hold_out"] == 2025
    assert ss.main([*data, "fit", "--seasons", "2023-2024", "--hold-out", "2023"]) == 2
    assert ss.main(["--data", str(tmp_path / "empty"), "--rooms", "0", "fit"]) == 2
    assert ss.FIT_SEASONS == "2022,2023,2024,2026"
    # Week six's re-freeze read a live league's exports; its flags went with it (PR D3).
    for gone in (["--tau", "residual"], ["--refresh"], ["--league", "100001"]):
        with pytest.raises(SystemExit):
            ss.main([*data, "fit", "--seasons", "2023-2024", *gone, "--dry-run"])
    assert ss.parse_seasons(ss.FIT_SEASONS) == [2022, 2023, 2024, 2026]


def test_describe_names_counts_and_no_figures():
    _ = (body, line)
    payload = {
        "seasons": [2023, 2024],
        "separate": {"2025": {}},
        "hold_out": 2025,
        "dispersion": {"fitted_players": 7, "games": 300},
        "hazard": {"players": 12},
    }
    text = ss.describe(payload)
    assert "2023, 2024" in text and "2025" in text and "7" in text and "300" in text


# --------------------------------------------------------------------------- PR 2b: the runs
from tests.sim.sim_league import make_data_dir

KNOBS = {
    "system": "bbm",
    "blend": None,
    "horizon_weight": "natural",
    "protection_floor": 0.0,
    "plan_floor_cats": 0.0,
    "plan_floor_points": 0.0,
    "stash_threshold": None,
    "faab_sizing": None,
    "daily_cap": 1,
    "three_weight": 0.33,
    "season_weight": 0.0,
    "playoff_weight": 1.0,
}


def test_the_guard_refuses_a_span_that_touches_the_window():
    evening = datetime(2026, 10, 27, 22, 0, tzinfo=MAC)
    assert not ss.touches_quiet_window(evening, 1.0)
    assert ss.touches_quiet_window(evening, 7.0)  # 22:00 + 7 h runs past 04:45
    assert ss.touches_quiet_window(datetime(2026, 10, 27, 4, 0, tzinfo=MAC), 0.0) is False
    assert ss.touches_quiet_window(datetime(2026, 10, 27, 4, 0, tzinfo=MAC), 1.0)
    ok, why = ss.guard(expected_hours=7.0, now=evening, rooms=0, announced=True, nice=None)
    assert not ok and "touches" in why
    assert ss.guard(expected_hours=0.5, now=evening, rooms=0, nice=None) == (True, "ok")


def test_the_estimate():
    assert ss.estimate_hours(36.0, 100, 10) == pytest.approx(0.1)


@pytest.fixture(scope="module")
def run_data(tmp_path_factory) -> Path:
    data = make_data_dir(tmp_path_factory.mktemp("runs"))
    assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, tier in (("A", "exact"), ("B", "ranking")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "market"}}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def _runs(data: Path) -> list[Path]:
    return sorted((data / "sim" / "runs").glob("*.json"))


def test_a_dry_run_prints_each_arms_season_scale_where_it_has_one(capsys):
    """A dry run prints an arm's season scale when its first task has one (an exact arm's) and
    nothing for an arm without (a ranking arm's: ``policy.scale_of`` is None on that tier)."""
    first = {
        "scale": {
            "A": {"gain": 0.25, "ros": 1.5, "ratio": 0.2, "against": 0.1, "swaps": 4},
            "B": None,
        }
    }
    assert ss.dry_run({"season": 2024, "forecaster": "prior", "path": 0}, first) == 0
    out = capsys.readouterr().out
    assert (
        "season scale, A, the first task: gain 0.25, ros 1.5, ratio 0.2, against 0.1 over 4 swaps"
        in out
    )
    assert "season scale, B," not in out and "dry run, nothing written" in out


def test_a_replay_records_its_run(run_data: Path):
    data = run_data
    before = len(_runs(data))
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--seasons",
                "2025",
                "--seats",
                str(data / "A.json"),
                str(data / "B.json"),
            ]
        )
        == 2
    )
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--seasons",
                "2024",
                "--forecasters",
                "prior",
                "--seats",
                str(data / "A.json"),
                str(data / "B.json"),
                "--paths",
                "1",
                "--workers",
                "1",
            ]
        )
        == 0
    )
    payload = json.loads(_runs(data)[-1].read_text())
    assert (
        payload["kind"] == "replay"
        and payload["seasons"] == [2024]
        and payload["seats"] == ["A", "B"]
    )
    assert list(payload["forecasters"]["2024"]) == ["prior"]
    # Nothing of the drawn world is recorded (PR D3): no tau, no refresh, no gap.
    assert not {"tau", "refresh", "gap"} & set(payload)
    assert set(payload["results"]["2024"]["prior"]) == {"A", "B"}
    assert payload["draft"].startswith("snake") and payload["confirmation"] is None
    # The seats believe only the games played: the payload names the belief, its weights and
    # where they came from (no season before 2024 has its prior season on file: the default),
    # the newcomer's rule, the pool and the news spread.
    assert payload["replay_version"] == 13 and payload["belief"]["kind"] == "causal"
    weights = payload["belief"]["weights"]["2024"]["prior"]
    assert weights["source"] == "the default" and weights["left_out"] == {
        "2023": "prior: season 2022 is not on file"
    }
    assert weights["default"] is True and weights["seasons"] == []
    assert set(weights["weights"].values()) == {10.0} and weights["grid"][0] == 2
    assert "undrafted" in payload["newcomer"] and "first 7 days" in payload["pool"]["draft"]
    assert payload["news_sd_days"] == 2.0
    # What every run records: the fit's hash, the hold-out, the execution model, the specs
    # verbatim, the period calendar, each arm's fields and surrogate, the commit and the times.
    fit_sha = next((data / "sim" / "fit").glob("*/fit.sha256")).read_text().strip()
    assert payload["fit_sha"] == fit_sha and payload["hold_out"] == 2025
    assert payload["executions"] == "free_agents_next_day"
    assert payload["specs"]["A"]["tier"] == "exact" and payload["specs"]["B"]["tier"] == "ranking"
    assert payload["period_calendar"]["period_one"]["2025"] == "2024-10-22"
    assert payload["surrogate"] == {s: {"pool": 30, "days": [0, 3], "plan": "daily"} for s in "AB"}
    assert payload["fields"]["A"] == {
        "pool": 30,
        "min_gain": 0.01,
        "weeks_ahead": 4,
        "surrogate_days": [0, 3],
    }
    assert "code_sha" in payload and "finished_at" in payload
    # Nothing of a live league is in the record (PR D3).
    assert not {"gap", "today", "system", "leagues", "skipped"} & set(payload)
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--seasons",
                "2024",
                "--forecasters",
                "oracle:0.2",
                "--seats",
                str(data / "A.json"),
                str(data / "B.json"),
                "--paths",
                "1",
                "--workers",
                "1",
                "--dry-run",
            ]
        )
        == 0
    )
    # A spec naming another fit is refused.
    (data / "C.json").write_text(
        json.dumps({**json.loads((data / "A.json").read_text()), "fit_sha": "0" * 64})
    )
    other = _replay(data, "--dry-run")
    other[other.index(str(data / "B.json"))] = str(data / "C.json")
    assert ss.main(other) == 2
    assert len(_runs(data)) == before + 1


# --------------------------------------------------------------------------- forecasters (PR D1)
@pytest.fixture(scope="module")
def blocks_data(tmp_path_factory) -> Path:
    """The synthetic folder with ESPN's stored projection blocks in its logs, fitted, with the
    two arms."""
    data = make_data_dir(tmp_path_factory.mktemp("blocks"), projection=True)
    assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, tier in (("A", "exact"), ("B", "ranking")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "market"}}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def test_the_forecasters_block_names_each_forecaster(blocks_data: Path):
    named = fc.parse("prior,espn,marcel,oracle:0.2")
    lines, _, _ = reader.replay_lines(blocks_data, 2026)
    fixed = ss.fixed_of(blocks_data, 2026, named)
    assert fixed.marcel_seasons == (2025, 2024, 2023)  # 2025 read as preseason information
    fits = reader.label_weights(blocks_data, 2026, ss.HOLD_OUT, named, 5, "stat")
    block = ss.forecasters_block(named, fixed, lines, 5, "stat", weights=fits)
    assert list(block) == ["prior", "espn", "marcel", "oracle:0.2"]
    for label, b in block.items():
        want = {"name", "source", "projected", "played", "error", "weights"}
        assert set(b) == (want | {"freeze"} if label == "espn" else want), label
        assert b["played"] <= b["projected"] and b["weights"] == fits[label].payload()
        assert set(b["error"]["by_stat"]) == set(wk.STATS)
    assert block["prior"]["projected"] == len(reader.prior_rates(blocks_data, 2026))
    assert block["espn"]["projected"] == 79  # every seventh block has no games count
    assert block["espn"]["freeze"]["median_projected_games"] == 70.0
    assert block["espn"]["freeze"]["flagged"] is False
    assert "2025, 2024, 2023" in block["marcel"]["source"]
    # An oracle's error, measured on path 0, sits at its spread: a check of the draw.
    oracle = block["oracle:0.2"]["error"]
    assert oracle["measured_on"].startswith("path 0")
    assert oracle["median_spread"] == pytest.approx(0.2, abs=0.04)
    minutes = ss.forecasters_block(named[3:], fixed, lines, 5, "minutes")["oracle:0.2"]
    assert "minutes shape" in minutes["source"]


def test_a_replay_keys_its_figures_by_forecaster(blocks_data: Path, capsys):
    data = blocks_data
    base = ["--data", str(data), "--rooms", "0", "replay", "--seats"]
    seats = [str(data / "A.json"), str(data / "B.json")]
    run = [*base, *seats, "--seasons", "2024", "--paths", "1", "--workers", "1"]
    assert ss.main([*run, "--forecasters", "espn,oracle:0.2"]) == 0
    out = capsys.readouterr().out
    assert "2 tasks (2 cells x 1 paths)" in out
    payload = json.loads(_written(out).read_text())
    assert payload["replay_version"] == 13 and payload["oracle_shape"] == "stat"
    assert list(payload["forecasters"]["2024"]) == ["espn", "oracle:0.2"]
    assert set(payload["results"]["2024"]) == {"espn", "oracle:0.2"}
    assert set(payload["counts"]["by_season"]["2024"]) == {"espn", "oracle:0.2"}
    assert set(payload["results"]["2024"]["espn"]) == {"A", "B"}
    assert "standins" not in payload
    assert set(payload["belief"]["weights"]["2024"]) == {"espn", "oracle:0.2"}
    assert "own projection" in payload["belief"]["weights_rule"]
    # A forecaster that cannot serve the season leaves its cell skipped by name, and a run with
    # no cell left is refused before any path.
    for flags, why in (
        (["--forecasters", "marcel"], "marcel needs 2 earlier seasons on file, it has 1"),
        (["--forecasters", "prior", "--seasons", "2023"], "prior: season 2022: no cached log"),
        (["--forecasters", "gospel"], "forecaster 'gospel'"),
        (["--forecasters", "prior,prior"], "prior is named twice"),
    ):
        assert ss.main([*run, *flags]) == 2
        assert why in capsys.readouterr().out


def test_espn_cannot_serve_a_log_without_its_blocks(run_data: Path, capsys):
    data = run_data
    args = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024"]
    args += ["--forecasters", "espn", "--seats", str(data / "A.json"), str(data / "B.json")]
    assert ss.main(args) == 2
    assert "espn: season 2024's log holds no projection block" in capsys.readouterr().out


def test_the_no_peek_check_agrees_through_its_date_and_writes_nothing(run_data: Path, capsys):
    data = run_data
    before = len(_runs(data))
    args = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--seasons",
        "2024",
        "--seats",
        str(data / "A.json"),
        str(data / "B.json"),
    ]
    assert ss.main([*args, "--no-peek", "2023-11-06"]) == 0
    out = capsys.readouterr().out
    assert "belief weights, 2024, prior (the default)" in out and "agree through 2023-11-06" in out
    assert "nothing written" in out
    assert ss.main([*args, "--no-peek", "2022-01-01"]) == 2  # not a day of the season
    assert "not a day of the replayed season" in capsys.readouterr().out
    assert ss.main([*args, "--no-peek", "the sixth"]) == 2
    assert ss.main([*args, "--news-sd", "-1", "--dry-run"]) == 2
    assert ss.main([*args, "--news-sd", "0", "--paths", "1", "--dry-run"]) == 0
    assert len(_runs(data)) == before


def test_validate_is_gate_five_on_a_replay(run_data: Path, capsys):
    data = run_data
    assert ss.main(["--data", str(data), "--rooms", "0", "validate", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "surrogate" in out and "gate 5 on a replay of 2024" in out
    assert "team_weeks" not in out and "absences" not in out
    assert ss.main(["--data", str(data), "--rooms", "0", "validate"]) == 0
    payload = json.loads(_runs(data)[-1].read_text())
    assert payload["kind"] == "validate" and payload["hold_out"] == 2025
    # Gate 5 on a replay of the latest replayable season on file, one row a seat.
    rows = [g for g in payload["gates"] if g["name"] == "surrogate"]
    assert [(g["season"], g["detail"]["seat"]) for g in rows] == [(2024, 1), (2024, 6), (2024, 12)]
    assert payload["surrogate_gate"]["season"] == 2024
    assert payload["surrogate_gate"]["forecaster"] == "prior"
    # Gate 5 alone (PR D3): the drawn world's gates 1 and 4 went with it, and nothing is listed
    # as not run.
    assert payload["gates"] == rows and payload["passed"] == all(g["passed"] for g in rows)
    assert not {"not_run", "today", "leagues", "skipped", "gap", "refresh", "tau"} & set(payload)


# --------------------------------------------------------------------------- the audit (PR B2)
#: What two runs of one spec, seed and season may differ in: when they ran.
WHEN = ("started_at", "finished_at")


def _replay(data: Path, *extra: str) -> list[str]:
    return [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--seasons",
        "2024",
        "--forecasters",
        "prior",
        "--seats",
        str(data / "A.json"),
        str(data / "B.json"),
        *extra,
    ]


def _written(out: str) -> Path:
    (line_,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return Path(line_.removeprefix("written: "))


def _as_written(payload: dict, aside: tuple[str, ...] = WHEN) -> str:
    """The payload's bytes as the run writer writes them, ``aside`` left out."""
    return json.dumps(
        {k: v for k, v in payload.items() if k not in aside}, indent=1, sort_keys=True, default=str
    )


def _spy_tasks(mp: pytest.MonkeyPatch, name: str, at: int) -> dict[int, dict]:
    """Each task's result by its path (the task's argument ``at``), in this process."""
    seen: dict[int, dict] = {}
    real = getattr(ss, name)

    def task(*t):
        r = real(*t)
        seen[t[at]] = r
        return r

    mp.setattr(ss, name, task)
    return seen


def _plant(mp: pytest.MonkeyPatch, path: int) -> None:
    """One breach on the first day of ``path``, found as a rule's would be. Nothing else in the
    run changes: the audit only reads."""
    real = audit.Auditor.check

    def check(self, today):
        found = real(self, today)
        if self.path == path and not getattr(self, "planted", False):
            self.planted = True
            b = audit.Breach(today.day, today.variant, 1, "planted", "the test's breach", self.path)
            self.breaches.append(b)
            found = [*found, b]
        return found

    mp.setattr(audit.Auditor, "check", check)


@pytest.fixture(scope="module")
def replays(run_data: Path) -> dict:
    """One replay of three paths run three times: on one worker, again on one, on two (its
    first task in this process, the other two in the pool). The first run's tasks are kept (the
    pool cannot carry the spy, so the run on two has none)."""
    data = run_data
    out: dict = {}
    for name, workers in (("one", "1"), ("again", "1"), ("two", "2")):
        with pytest.MonkeyPatch.context() as mp:
            if workers == "1":
                out[f"{name}_tasks"] = _spy_tasks(mp, "task_replay", 14)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = ss.main(_replay(data, "--paths", "3", "--seed", "5", "--workers", workers))
            assert code == 0
            out[name] = json.loads(_written(buf.getvalue()).read_text())
    return out


def test_the_same_spec_seed_and_season_give_the_same_payload(replays):
    one, again, two = replays["one"], replays["again"], replays["two"]
    assert one["started_at"] != again["started_at"] or one["finished_at"] != again["finished_at"]
    assert _as_written(one) == _as_written(again)
    assert one["workers"] == 1 and two["workers"] == 2
    assert _as_written(one, (*WHEN, "workers")) == _as_written(two, (*WHEN, "workers"))
    assert sorted(replays["one_tasks"]) == [0, 1, 2] == sorted(replays["again_tasks"])
    assert replays["one_tasks"] == replays["again_tasks"]


def test_a_replay_payload_carries_the_counts_and_the_audit(replays):
    p = replays["one"]
    assert p["audit"]["paths_voided"] == 0 and p["audit"]["breaches"] == []
    assert [r["name"] for r in p["audit"]["rules"]] == [r.name for r in audit.RULES]
    counts = p["counts"]["by_season"]["2024"]["prior"]
    assert set(counts) == {"A", "B"} and p["counts"]["rivals"] is None
    assert set(counts["A"]) == set(ct.METRICS) and counts["A"]["landed"]["n"] == 3
    assert counts["A"]["starter_games"]["mean"] > 0
    assert set(p["counts"]["note"]) == {*ct.METRICS, "pooling"}


def test_a_breach_voids_its_path_and_only_its_path(run_data: Path, replays, capsys):
    data = run_data
    clean = replays["one_tasks"]
    with pytest.MonkeyPatch.context() as mp:
        seen = _spy_tasks(mp, "task_replay", 14)
        _plant(mp, 1)
        code = ss.main(_replay(data, "--paths", "3", "--seed", "5", "--workers", "1"))
    out = capsys.readouterr().out
    assert code == ss.AUDIT_EXIT and "AUDIT: 1 breach(es) voided 1 path(s)" in out
    payload = json.loads(_written(out).read_text())  # written all the same
    note = payload["audit"]
    assert note["paths_voided"] == 1
    assert note["voided"] == [{"season": 2024, "forecaster": "prior", "path": 1}]
    ((b),) = note["breaches"]
    assert (b["forecaster"], b["path"], b["rule"], b["seat"]) == ("prior", 1, "planted", 1)
    # The paths that stand ran as they did without the breach, and only they are aggregated.
    for p in (0, 2):
        assert seen[p] == clean[p]
    for arm in ("A", "B"):
        want = rn.aggregate([clean[p]["by_arm"][arm] for p in (0, 2)])
        assert payload["results"]["2024"]["prior"][arm] == json.loads(json.dumps(want))
        assert payload["results"]["2024"]["prior"][arm]["made_playoffs"]["n"] == 2
        counts = ss.counts_of([clean[p]["counts"][arm] for p in (0, 2)])
        assert payload["counts"]["by_season"]["2024"]["prior"][arm] == json.loads(
            json.dumps(counts)
        )


def test_a_paired_replay_voids_a_breached_path_and_carries_the_counts(run_data: Path, capsys):
    """On the paired design a breach voids its path and only its path: the difference is the
    clean run's over the paths left, there is no verdict, and the counts carry both arms and
    their rivals."""
    data = run_data
    for name, tier in (("Ps", "static"), ("Pr", "ranking")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "static"}}
        (data / f"{name}.json").write_text(json.dumps(spec))
    pair = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--seasons",
        "2024",
        "--arms",
        str(data / "Ps.json"),
        str(data / "Pr.json"),
        "--paths",
        "12",
        "--workers",
        "1",
        "--seed",
        "3",
    ]
    with pytest.MonkeyPatch.context() as mp:
        clean = _spy_tasks(mp, "task_paired", 14)
        assert ss.main(pair) == 0
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    c = payload["counts"]["by_season"]["2024"]["prior"]
    assert set(c) == {"a", "b", "rivals"} and c["a"]["landed"]["n"] == 12
    assert "seats other than the pair's" in payload["counts"]["rivals"]
    assert payload["audit"]["paths_voided"] == 0
    with pytest.MonkeyPatch.context() as mp:
        _plant(mp, 2)
        assert ss.main(pair) == ss.AUDIT_EXIT
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    assert payload["audit"]["voided"] == [{"season": 2024, "forecaster": "prior", "path": 2}]
    v = payload["verdict"]
    assert v["passes"] is None and "voided 1 path" in v["why"]
    cell = payload["results"]["2024"]["prior"]
    want = rn.aggregate([clean[p]["delta"] for p in range(12) if p != 2])
    assert cell["difference"] == json.loads(json.dumps(want)) and cell["paths"] == 11


def test_a_dry_run_prints_its_tasks_counts_and_exits_on_a_breach(run_data: Path, capsys):
    data = run_data
    before = len(_runs(data))
    assert ss.main(_replay(data, "--paths", "1", "--workers", "1", "--dry-run")) == 0
    out = capsys.readouterr().out
    assert "counts, A, the first task: landed" in out and "dry run, nothing written" in out
    with pytest.MonkeyPatch.context() as mp:
        _plant(mp, 0)
        assert ss.main(_replay(data, "--paths", "1", "--workers", "1", "--dry-run")) == 3
        out = capsys.readouterr().out
        assert "AUDIT: 1 breach(es) voided 1 path(s)" in out and "planted on" in out
        # The no-peek check stands only on runs the audit passes.
        assert ss.main(_replay(data, "--no-peek", "2023-11-06")) == ss.AUDIT_EXIT
        out = capsys.readouterr().out
        assert "AUDIT (recorded season): planted" in out and "AUDIT (changed season)" in out
    assert len(_runs(data)) == before


def test_the_no_peek_check_gives_the_guard_its_span(run_data: Path, monkeypatch, capsys):
    """Fifteen minutes before the routines' window: a plain replay starts, the no-peek check (two
    seasons, a few minutes) is refused because its span touches the window."""
    data = run_data
    at = datetime(2026, 10, 27, 4, 35, tzinfo=MAC)
    monkeypatch.setattr(ss, "now_local", lambda: at)
    assert ss.main(_replay(data, "--no-peek", "2023-11-06")) == 2
    assert "touches" in capsys.readouterr().out
    assert ss.guard(0.0, now=at, rooms=0, nice=None) == (True, "ok")  # a plain replay's start
    ok, why = ss.guard(ss.NO_PEEK_HOURS, now=at, rooms=0, nice=None)
    assert not ok and "touches" in why
    earlier = datetime(2026, 10, 27, 4, 25, tzinfo=MAC)
    assert ss.touches_quiet_window(earlier, ss.NO_PEEK_HOURS) is False


# --------------------------------------------------------------------------- a replay that moves (PR C)
#: Players the moving replay's logs add beyond the fixture's: enough that its draft leaves
#: projected players on the wire (``sim_league.make_data_dir``).
WIRE = 120


@pytest.fixture(scope="module")
def wire_data(tmp_path_factory) -> Path:
    """The fixture folder with :data:`WIRE` more players in its logs, fitted, and two arms: a
    ranking seat (it moves without an evaluator, so a path is a few seconds) and a static one."""
    data = make_data_dir(tmp_path_factory.mktemp("wire"), wire=WIRE)
    assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, tier in (("R", "ranking"), ("S", "static")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "market"}}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def test_a_replay_with_a_wire_lands_moves_and_voids_nothing(wire_data: Path, capsys):
    data = wire_data
    args = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--seasons",
        "2024",
        "--seats",
        str(data / "R.json"),
        str(data / "S.json"),
        "--paths",
        "1",
        "--workers",
        "1",
        "--seed",
        "5",
    ]
    assert ss.main(args) == 0
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    assert payload["audit"]["paths_voided"] == 0 and payload["audit"]["breaches"] == []
    counts = payload["counts"]["by_season"]["2024"]["prior"]
    assert counts["R"]["landed"]["mean"] >= 1 and counts["R"]["adds_per_week"]["mean"] > 0
    assert counts["S"]["landed"]["mean"] == 0


#: What ``checks.surrogate_matches`` returned on main before PR D4a2 on gate 5's replay of the
#: made-up season with a wire (seed 1, lag 1, path 0), by seat: one day differs for two seats. The
#: seats then weighed expected categories, as they do in a league that counts every category, so
#: the tests below name that format (the format PR); under the default, one win per matchup, the
#: two tiers agree on 14 of the 15 league-days, seat 6 differing on its fifth
#: (``test_sim_format.ONE_WIN_MATCHES``).
WIRE_MATCHES = {
    1: [True, True, True, False, True],
    6: [True, True, True, True, True],
    12: [True, True, True, False, True],
}


@pytest.fixture(scope="module")
def wire_validate(wire_data: Path) -> tuple[dict, str]:
    """One ``validate --h2h each_category`` of the season with a wire, for the tests of what gate
    5 records and prints (PR D4a2): the payload it wrote and what it printed."""
    argv = ["--data", str(wire_data), "--rooms", "0", "validate", "--season", "2024"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--h2h", EACH_CATEGORY])
    out = buf.getvalue()
    assert code == 0, out
    return json.loads(_written(out).read_text()), out


def test_gate_five_records_what_it_compared(wire_data: Path, wire_validate):
    """Gate 5's row carries, a seat and a day, the two sets and their worth by the exact tier's
    own objective (PR D4a2); its answers are what they were before."""
    payload, _ = wire_validate
    rows, block = payload["gates"], payload["surrogate_gate"]
    differ = 0
    for r in rows:
        d = r["detail"]
        records = d["records"]
        assert [x["day"] for x in records] == block["days"] == d["days"]
        assert [x["equal"] for x in records] == WIRE_MATCHES[d["seat"]]
        assert d["matched"] == sum(WIRE_MATCHES[d["seat"]])
        for x in records:
            worth = x["worth"]
            if x["equal"]:
                assert x["exact"] == x["surrogate"] and worth["exact"] == worth["surrogate"]
            else:
                # Two sets, two worths, by the one evaluator; which is larger is not asserted.
                differ += 1
                assert x["exact"] != x["surrogate"]
                assert isinstance(worth["exact"], float) and isinstance(worth["surrogate"], float)
    assert differ == 2  # not vacuous: the made-up season has differing days
    assert "records" in block and "worth" in block["records"]
    # ``surrogate_matches`` itself, on the same replay in the same format, returns what it did.
    rules = shapes.LeagueRules(h2h=EACH_CATEGORY)
    assert block["rules"] == rules.payload()
    r = ss.read_season(wire_data, 2024, [fc.parse_one("prior")], None, {}, 1, ss.GATE_SHAPE, rules)
    f = fc.parse_one("prior")
    projection = ss.projection_of(f, r.fixed, r.lines, 1, 0, "stat")
    setup = ss.replay_setup_of(
        2024, r.lines, r.members, r.scheduled, projection, league_rules=rules
    )
    w = rn.replay_world(
        setup, r.lines, 1, 1, 0, r.weights["prior"], label="prior", weights_of=r.weights
    )
    # Each day is solved from day one's rosters, so the differing day alone answers as it did in
    # the five: both its answers, for the two seats that differ and one that does not.
    day = date.fromisoformat(block["days"][3])
    knobs = policy.check_knobs(dict(policy.KNOB_DEFAULTS))
    for seat, matches in WIRE_MATCHES.items():
        assert checks.surrogate_matches(setup, w, seat, [day], knobs) == [matches[3]]


def test_validate_prints_each_seat_days_record_and_names_no_player(wire_data: Path, wire_validate):
    payload, out = wire_validate
    rows = payload["gates"]
    assert all(len(g["detail"]["records"]) == g["detail"]["of"] for g in rows)
    lines = [x for x in out.splitlines() if x.startswith("  seat ")]
    assert len(lines) == sum(len(g["detail"]["records"]) for g in rows)
    assert all(("equal;" in x or "differ;" in x) and "worth, exact " in x for x in lines)
    _, members, _ = reader.replay_lines(wire_data, 2024)
    names = {m.name for m in members.values() if m.name}
    assert names and not any(n in out for n in names)


def test_gate_five_runs_on_a_replay_of_the_season_named(wire_data: Path, capsys):
    """Gate 5 on a replay (PR D3): the league, the weights and the world are the replay's for the
    season and forecaster named; three seats of the draft order on five league-days each, at the
    knobs' and the fields' defaults. The hold-out, the confirmation season, a season with no log
    and a forecaster that cannot serve the season are refused before any solve."""
    rows, block = ss.gate_surrogate(wire_data, 2024, fc.parse_one("prior"), 1, 1)
    assert [r["detail"]["seat"] for r in rows] == [1, 6, 12] == block["seats"]
    assert all(r["name"] == "surrogate" and r["season"] == 2024 for r in rows)
    assert all(r["detail"]["of"] == 5 and r["detail"]["needed"] == 4 for r in rows)
    # The surrogate matches the exact tier on the synthetic replay, seat by seat.
    assert all(r["passed"] for r in rows), [r["detail"] for r in rows]
    days = [date.fromisoformat(d) for d in block["days"]]
    assert [(d - days[0]).days for d in days] == list(ss.GATE_DAYS)
    assert block["knobs"] == dict(policy.KNOB_DEFAULTS)
    assert block["fields"] == policy.DEFAULT_FIELDS.payload()
    assert block["forecaster"] == "prior" and block["weights"]["source"] == "the default"
    assert ss.gate_season(wire_data) == 2024
    base = ["--data", str(wire_data), "--rooms", "0", "validate"]
    for flags, why in (
        (["--season", "2025"], "2025 is the hold-out"),
        (["--season", "2026"], "2026 is the confirmation season; a gate needs no look at it"),
        (["--season", "2019"], "season 2019 has no log on file"),
        (["--forecaster", "marcel"], "marcel needs 2 earlier seasons on file, it has 1"),
        (["--forecaster", "gospel"], "forecaster 'gospel'"),
    ):
        assert ss.main([*base, *flags, "--dry-run"]) == 2
        assert why in capsys.readouterr().out


# --------------------------------------------------------------------------- the hash seed (PR C2)
def test_the_run_record_keeps_the_hash_seed(monkeypatch):
    """``hash_seed`` is a record field like ``host`` and ``workers``: the process's
    ``PYTHONHASHSEED``, or ``"random"`` when it is unset (or empty)."""

    def payload() -> dict:
        return ss.base_payload("replay", "x", datetime.now(UTC), "0" * 64, Path("fit.json"), {}, 1)

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    assert ss.hash_seed() == "0" and payload()["hash_seed"] == "0"
    monkeypatch.setenv("PYTHONHASHSEED", "")
    assert payload()["hash_seed"] == "random"
    monkeypatch.delenv("PYTHONHASHSEED")
    assert payload()["hash_seed"] == "random"


def test_a_simulating_run_without_a_hash_seed_says_so_on_stderr(
    run_data: Path, monkeypatch, capsys
):
    """One line on stderr when the hash seed is unset and the command simulates and is not a
    dry run; none when it is set, or on a dry run. The hold-out replay is refused right after,
    so the line is all the run does."""
    a = str(run_data / "A.json")
    argv = ["--data", str(run_data), "--rooms", "0", "replay", "--seasons", "2025", "--seats", a]
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    assert ss.main(argv) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "PYTHONHASHSEED is unset" in err
    assert "PYTHONHASHSEED=0" in err
    assert ss.main([*argv, "--dry-run"]) == 2
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    assert ss.main(argv) == 2
    assert capsys.readouterr().err == ""
    assert set(ss.SIMULATING) == {"replay", "validate", "screen"}
