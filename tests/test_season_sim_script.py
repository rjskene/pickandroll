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
