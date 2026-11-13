"""The simulator's commands (#172, PR 1; ``pickandroll.sim.cli``): the guard, the seasons
argument, the fit command on a synthetic cache."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import audit
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import run as rn
from tests.sim.sim_fixtures import synthetic_lines
from tests.sim.test_gamelogs import body, entry, line

MAC = ZoneInfo("America/Toronto")
#: What the commands' clock reads in every test here: a weekday morning outside the routines'
#: window. Without it a suite run between 04:45 and 06:45 Mac clock has the guard refuse every
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
    assert not ok and "fantasyMASTER" in why
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
from tests.sim.sim_league import LEAGUE, MY_TEAM, make_data_dir

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


def test_parse_standin_and_the_estimate():
    assert ss.parse_standin("prior") == [("prior", 0.0)]
    assert ss.parse_standin("oracle:0.1,0.3") == [("oracle", 0.1), ("oracle", 0.3)]
    with pytest.raises(ValueError):
        ss.parse_standin("gospel")
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


def test_compare_pairs_the_arms_and_records_the_run(run_data: Path, capsys):
    data = run_data
    args = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "compare",
        str(data / "A.json"),
        str(data / "B.json"),
    ]
    common = [
        "--leagues",
        LEAGUE,
        "--paths",
        "1",
        "--workers",
        "1",
        "--today",
        "2026-10-21",
        "--seed",
        "3",
    ]
    assert ss.main([*args, *common, "--shrink", "0", "--dry-run"]) == 0
    assert _runs(data) == []
    assert ss.main([*args, *common, "--shrink", "0,0.5", "--name", "first"]) == 0
    out = capsys.readouterr().out
    assert "verdict (one-SE, advisory)" in out and "playoff odds, B less A," in out
    (path,) = _runs(data)
    payload = json.loads(path.read_text())
    assert payload["kind"] == "compare" and payload["name"] == "first"
    assert (
        payload["fit_sha"]
        == (data / "sim" / "fit").glob("*/fit.sha256").__next__().read_text().strip()
    )
    assert payload["hold_out"] == 2025 and payload["executions"] == "free_agents_next_day"
    assert payload["gap"]["systems"] == ["bbm", "yahoo"] and payload["refresh"] == "defaults"
    assert payload["specs"]["a"]["tier"] == "exact" and payload["specs"]["b"]["tier"] == "ranking"
    assert payload["seats"] == {LEAGUE: MY_TEAM} and payload["shrinks"] == [0.0, 0.5]
    assert payload["period_calendar"]["period_one"]["2025"] == "2024-10-22"
    assert payload["tau"]["source"] == "systems"
    assert payload["leagues"][LEAGUE]["bracket"] == "read" and payload["leagues"][LEAGUE][
        "assumed_pairings"
    ] == [3]
    assert payload["results"]["difference"] == "b less a"
    assert set(payload["results"]["by_shrink"]) == {"0.0", "0.5"}
    assert payload["results"]["by_shrink"]["0.0"]["made_playoffs"]["n"] == 1
    assert (
        payload["verdict"]["rule"] == "one-SE" and payload["verdict"]["passes"] is None
    )  # one path: no SE
    assert payload["surrogate"] == {"pool": 30, "days": [0, 3], "plan": "daily"}
    assert "code_sha" in payload and "finished_at" in payload
    # A spec naming another fit is refused; so is a league without a seat of mine.
    (data / "C.json").write_text(
        json.dumps({**json.loads((data / "A.json").read_text()), "fit_sha": "0" * 64})
    )
    assert ss.main([*args[:-1], str(data / "C.json"), *common, "--dry-run"]) == 2
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "compare",
                str(data / "A.json"),
                str(data / "B.json"),
                "--leagues",
                "200002",
                "--paths",
                "1",
                "--dry-run",
            ]
        )
        == 2
    )


def test_replay_and_room_record_their_runs(run_data: Path):
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
                "--season",
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
                "--season",
                "2024",
                "--standin",
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
        payload["kind"] == "replay" and payload["season"] == 2024 and payload["seats"] == ["A", "B"]
    )
    assert payload["standins"] == [{"kind": "prior", "spread": 0.0}] and payload["tau"][
        "source"
    ].startswith("not used")
    assert set(payload["results"]["prior:0"]) == {"A", "B"} and payload["draft"].startswith("snake")
    # The seats believe only the games played: the payload names the belief, its weights and
    # where they came from (no season before 2024 has its prior season on file: the default),
    # the newcomer's rule, the pool and the news spread, and the weekly refresh as not used.
    assert payload["replay_version"] == 2 and payload["belief"]["kind"] == "causal"
    weights = payload["belief"]["weights"]
    assert weights["default"] is True and weights["seasons"] == []
    assert set(weights["weights"].values()) == {10.0} and weights["grid"][0] == 2
    assert "undrafted" in payload["newcomer"] and "first 7 days" in payload["pool"]["draft"]
    assert payload["news_sd_days"] == 2.0 and payload["refresh"].startswith("not used")
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--season",
                "2024",
                "--standin",
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
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "room",
                "--leagues",
                LEAGUE,
                "--seats",
                str(data / "A.json"),
                str(data / "B.json"),
                "--draft",
                "snake",
                "--paths",
                "1",
                "--workers",
                "1",
                "--today",
                "2026-10-21",
            ]
        )
        == 0
    )
    room = json.loads(_runs(data)[-1].read_text())
    assert (
        room["kind"] == "room"
        and room["draft"] == "snake"
        and room["rotation"].startswith("seat i")
    )
    assert (
        set(room["results"]["by_arm"]) == {"A", "B"}
        and room["results"]["by_arm"]["A"]["rank"]["n"] == 1
    )
    assert len(_runs(data)) == before + 2


def test_the_no_peek_check_agrees_through_its_date_and_writes_nothing(run_data: Path, capsys):
    data = run_data
    before = len(_runs(data))
    args = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--season",
        "2024",
        "--seats",
        str(data / "A.json"),
        str(data / "B.json"),
    ]
    assert ss.main([*args, "--no-peek", "2023-11-06"]) == 0
    out = capsys.readouterr().out
    assert "belief weights (the default)" in out and "agree through 2023-11-06" in out
    assert "nothing written" in out
    assert ss.main([*args, "--no-peek", "2022-01-01"]) == 2  # not a day of the season
    assert "not a day of the replayed season" in capsys.readouterr().out
    assert ss.main([*args, "--no-peek", "the sixth"]) == 2
    assert ss.main([*args, "--news-sd", "-1", "--dry-run"]) == 2
    assert ss.main([*args, "--news-sd", "0", "--paths", "1", "--dry-run"]) == 0
    assert len(_runs(data)) == before


def test_validate_runs_the_gates_side_by_side(run_data: Path, capsys):
    data = run_data
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "validate",
                "--league",
                LEAGUE,
                "--today",
                "2026-10-21",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "team_weeks" in out and "absences" in out and "not run" in out and "surrogate" in out
    assert (
        ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "validate",
                "--league",
                LEAGUE,
                "--today",
                "2026-10-21",
            ]
        )
        == 0
    )
    payload = json.loads(_runs(data)[-1].read_text())
    assert payload["kind"] == "validate" and payload["hold_out"] == 2025
    by = {(g["name"], str(g["season"])): g for g in payload["gates"]}
    assert by[("team_weeks", "2025")]["detail"]["layers"] == "game noise and absences"
    assert (
        by[("absences", "2025")]["passed"] is not None
        and by[("absences", "2026")]["detail"]["players"] > 0
    )
    assert (
        by[("team_weeks", LEAGUE)]["passed"] is None
        and "no recorded week" in by[("team_weeks", LEAGUE)]["detail"]["reason"]
    )
    assert by[("realized_share", LEAGUE)]["passed"] is None
    assert by[("surrogate", LEAGUE)]["detail"]["days"][0] == "2026-10-21"
    assert ("belief_refresh", LEAGUE) in by
    assert "realized_share" in payload["not_run"]


def test_fit_refits_the_refresh_and_the_residual_tau(run_data: Path, capsys):
    data = run_data
    base = ["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]
    assert ss.main([*base, "--refresh", "--dry-run"]) == 2  # needs --league
    assert ss.main([*base, "--refresh", "--tau", "residual", "--league", LEAGUE, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "tau: 11 stats (residual)" in out and "refresh: fitted over" in out
    payload, _sha, _ = ss.run_fit([2023, 2024], data)
    assert payload["tau"] is None and payload["refresh"] is None
    exports, realized, games = ss.residual_inputs(data, LEAGUE)
    assert len(exports) == 2 and len(realized) == 93 and len(games) == 93


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
        "--season",
        "2024",
        "--standin",
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
                out[f"{name}_tasks"] = _spy_tasks(mp, "task_replay", 12)
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
    counts = p["counts"]["by_standin"]["prior:0"]
    assert set(counts) == {"A", "B"} and p["counts"]["rivals"] is None
    assert set(counts["A"]) == set(ct.METRICS) and counts["A"]["landed"]["n"] == 3
    assert counts["A"]["starter_games"]["mean"] > 0
    assert set(p["counts"]["note"]) == {*ct.METRICS, "pooling"}


def test_a_breach_voids_its_path_and_only_its_path(run_data: Path, replays, capsys):
    data = run_data
    clean = replays["one_tasks"]
    with pytest.MonkeyPatch.context() as mp:
        seen = _spy_tasks(mp, "task_replay", 12)
        _plant(mp, 1)
        code = ss.main(_replay(data, "--paths", "3", "--seed", "5", "--workers", "1"))
    out = capsys.readouterr().out
    assert code == ss.AUDIT_EXIT and "AUDIT: 1 breach(es) voided 1 path(s)" in out
    payload = json.loads(_written(out).read_text())  # written all the same
    note = payload["audit"]
    assert note["paths_voided"] == 1 and note["voided"] == [{"standin": "prior:0", "path": 1}]
    ((b),) = note["breaches"]
    assert (b["standin"], b["path"], b["rule"], b["seat"]) == ("prior:0", 1, "planted", 1)
    # The paths that stand ran as they did without the breach, and only they are aggregated.
    for p in (0, 2):
        assert seen[p] == clean[p]
    for arm in ("A", "B"):
        want = rn.aggregate([clean[p]["by_arm"][arm] for p in (0, 2)])
        assert payload["results"]["prior:0"][arm] == json.loads(json.dumps(want))
        assert payload["results"]["prior:0"][arm]["made_playoffs"]["n"] == 2
        counts = ss.counts_of([clean[p]["counts"][arm] for p in (0, 2)])
        assert payload["counts"]["by_standin"]["prior:0"][arm] == json.loads(json.dumps(counts))


def test_compare_and_room_void_a_breached_path_and_carry_the_counts(run_data: Path, capsys):
    data = run_data
    compare = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "compare",
        str(data / "A.json"),
        str(data / "B.json"),
        "--leagues",
        LEAGUE,
        "--paths",
        "3",
        "--workers",
        "1",
        "--today",
        "2026-10-21",
        "--seed",
        "3",
        "--shrink",
        "0",
    ]
    with pytest.MonkeyPatch.context() as mp:
        clean = _spy_tasks(mp, "task_compare", 3)
        assert ss.main(compare) == 0
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    c = payload["counts"]["by_shrink"]["0.0"]
    assert set(c) == {"a", "b", "rivals"} and c["a"]["landed"]["n"] == 3
    assert c["a"]["landed"]["mean"] + c["b"]["landed"]["mean"] > 0  # the seats moved
    assert "seats other than mine" in payload["counts"]["rivals"]
    assert payload["audit"]["paths_voided"] == 0
    with pytest.MonkeyPatch.context() as mp:
        _plant(mp, 2)
        assert ss.main(compare) == ss.AUDIT_EXIT
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    assert payload["audit"]["voided"] == [{"league": LEAGUE, "shrink": 0.0, "path": 2}]
    assert payload["verdict"]["passes"] is None and "voided 1 path" in payload["verdict"]["why"]
    agg = payload["results"]["by_shrink"]["0.0"]
    want = rn.aggregate([clean[p]["delta"] for p in (0, 1)])
    assert agg == json.loads(json.dumps(want)) and agg["made_playoffs"]["n"] == 2
    room = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "room",
        "--leagues",
        LEAGUE,
        "--seats",
        str(data / "A.json"),
        str(data / "B.json"),
        "--paths",
        "2",
        "--workers",
        "1",
        "--today",
        "2026-10-21",
    ]
    with pytest.MonkeyPatch.context() as mp:
        _plant(mp, 0)
        assert ss.main(room) == ss.AUDIT_EXIT
    payload = json.loads(_written(capsys.readouterr().out).read_text())
    assert payload["audit"]["voided"] == [{"league": LEAGUE, "path": 0}]
    assert payload["results"]["by_arm"]["A"]["rank"]["n"] == 1
    assert payload["counts"]["by_arm"]["A"]["landed"]["n"] == 1


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
