"""The simulator's readers (#172, PR 2b) on a fixture data folder: the newest fit, a replay's
lines and the run's record."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.season import weekly as wk
from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from tests.sim.sim_league import make_data_dir

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    """The commands' clock reads a weekday morning outside the routines' window, whatever the hour
    the suite runs at (see ``test_season_sim_script.BUSINESS_HOURS``)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            ss,
            "now_local",
            lambda: datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto")),
        )
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    folder = make_data_dir(tmp_path_factory.mktemp("sim"))
    assert ss.main(["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    return folder


def test_the_newest_fit_is_checked_against_its_hash(data: Path):
    payload, sha, path = reader.newest_fit(data)
    assert path.name == "fit.json" and len(sha) == 64 and payload["hold_out"] == 2025
    assert reader.fit_hash(payload) == sha
    beside = path.with_name("fit.sha256")
    kept = beside.read_text()
    beside.write_text("0" * 64 + "\n")
    with pytest.raises(reader.SimReadError):
        reader.newest_fit(data)
    beside.write_text(kept)
    with pytest.raises(reader.SimReadError):
        reader.newest_fit(data / "nowhere")


def test_a_replays_lines_members_and_schedule(data: Path):
    lines, members, scheduled = reader.replay_lines(data, 2024)
    assert reader.period_date(2024, 1) == date(2023, 10, 24)
    assert reader.period_date(2024, 3) == date(2023, 10, 26)
    with pytest.raises(reader.SimReadError):
        reader.period_date(1999, 1)
    assert len(members) == 93 and all(m.positions for m in members.values())
    pid = next(iter(lines))
    assert pid in members and set(scheduled[pid]) >= set(lines[pid])
    assert all(set(ln) <= set(wk.STATS) for ln in lines[pid].values())
    prior = reader.prior_rates(data, 2025)
    assert set(prior) <= set(members) and all("pts" in r for r in prior.values())
    weeks = [(date(2023, 10, 23), date(2023, 10, 29)), (date(2023, 10, 30), date(2023, 11, 5))]
    missed = reader.missed_games(lines, scheduled, weeks)
    assert all(0 <= m <= n for rows in missed.values() for m, n in rows)
    with pytest.raises(reader.SimReadError):
        reader.replay_lines(data, 2020)


def test_the_run_record_names_the_fit_and_the_hold_out(data: Path, tmp_path: Path):
    with pytest.raises(ValueError):
        reader.write_run(tmp_path, {"kind": "replay", "started_at": "2026-10-24T10:00:00+00:00"})
    path = reader.write_run(
        tmp_path,
        {
            "kind": "replay",
            "name": "A vs B/1",
            "started_at": "2026-10-24T10:00:00+00:00",
            "fit_sha": "x",
            "hold_out": 2025,
        },
    )
    assert (
        path.parent == tmp_path / reader.RUNS_DIR
        and path.name == "20261024T100000Z-replay-A-vs-B-1.json"
    )
    assert json.loads(path.read_text())["hold_out"] == 2025
    assert reader.code_sha(ROOT) is None or len(reader.code_sha(ROOT)) == 40
    assert reader.code_sha(tmp_path) is None
