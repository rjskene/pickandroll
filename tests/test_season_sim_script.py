"""The simulator's script (#172, PR 1): the guard, the seasons argument, the fit command on a
synthetic cache."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import season_sim as ss

from tests.sim_fixtures import synthetic_lines
from tests.test_gamelogs import body, entry, line

MAC = ZoneInfo("America/Toronto")


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
from tests.sim_league import LEAGUE, MY_TEAM, make_data_dir

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
    return sorted((data / "autopilot" / "sim" / "runs").glob("*.json"))


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
    assert "verdict (one-SE, advisory)" in out
    (path,) = _runs(data)
    payload = json.loads(path.read_text())
    assert payload["kind"] == "compare" and payload["name"] == "first"
    assert (
        payload["fit_sha"]
        == (data / "autopilot" / "sim" / "fit").glob("*/fit.sha256").__next__().read_text().strip()
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
