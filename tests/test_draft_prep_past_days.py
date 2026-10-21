"""The past-days rankings (#95, scripts/draft_prep/past_days.py): the import of a Basketball
Monster past 7 or 14 days export and its refusals. Every export here is synthetic: real player
names in the sheet's columns, made-up numbers."""

import importlib.util
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draft_day.py"
HEAD = "Name,Team,Pos,g,m,p,3,r,a,s,b,fg%,fga,ft%,fta,to,USG"
NAMES = [
    ("Andre Drummond", "NYK", "C"),
    ("Keldon Johnson", "SAS", "SF,PF"),
    ("Alex Caruso", "OKC", "SG,SF"),
]


def export(path: Path, games: list[int], at: float, head: str = HEAD) -> Path:
    lines = [head]
    for (name, team, pos), g in zip(NAMES, games, strict=True):
        lines.append(
            f'{name},{team},"{pos}",{g},{30 * g},{12 * g},{g},{5 * g},{3 * g},{g},0,0.5,{10 * g},0.8,{2 * g},{g},21.5'
        )
    path.write_text("\n".join(lines) + "\n")
    os.utime(path, (at, at))
    return path


@pytest.fixture
def runbook(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("draft_day_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "data"
    (data / "fidelity").mkdir(parents=True)
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setenv("PICKANDROLL_DOWNLOADS", str(tmp_path / "Downloads"))
    return module


def command(runbook, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["draft_day.py", *argv])
    return runbook.main()


def test_the_newest_export_is_saved_under_the_window_with_its_time(runbook, monkeypatch, capsys):
    now = time.time()
    downloads = runbook.ROOT / "Downloads"
    export(downloads / "BBM_PlayerRankings.csv", [2, 3, 3], now - 7200)
    newer = export(downloads / "BBM_PlayerRankings (1).csv", [3, 4, 3], now - 600)
    assert command(runbook, monkeypatch, "past-days", "--days", "7") == runbook.OK
    stamp = datetime.fromtimestamp(now - 600, UTC).strftime("%Y%m%d-%H%M")
    saved = runbook.DATA / f"bbm_actual_7d_totals_{stamp}.csv"
    assert saved.read_bytes() == newer.read_bytes()
    assert saved.stat().st_mtime == pytest.approx(now - 600)  # the flag reads it as the as_of
    meta = json.loads(saved.with_suffix(".json").read_text())
    assert meta["source"] == "bbm" and meta["file"] == saved.name
    out = capsys.readouterr().out
    assert (
        f"saved data/{saved.name}" in out and "3 players with games over 7 days, at most 4" in out
    )
    assert newer.exists()  # the user's Downloads are left as they were


def test_an_export_with_too_many_games_for_the_window_is_refused(runbook, monkeypatch, capsys):
    export(runbook.ROOT / "Downloads" / "BBM_PlayerRankings.csv", [6, 4, 3], time.time())
    assert command(runbook, monkeypatch, "past-days") == runbook.ERROR
    assert "more than a team plays in 7 days" in capsys.readouterr().out
    assert not list(runbook.DATA.glob("bbm_actual_*"))
    # The same file is a fair 14-day export.
    assert command(runbook, monkeypatch, "past-days", "--days", "14") == runbook.OK
    assert len(list(runbook.DATA.glob("bbm_actual_14d_totals_*.csv"))) == 1


def test_a_bad_schema_or_an_empty_window_is_refused(runbook, monkeypatch, capsys, tmp_path):
    bad = export(tmp_path / "bad.csv", [2, 2, 2], time.time(), head=HEAD.replace(",m,", ",min,"))
    assert command(runbook, monkeypatch, "past-days", "--export", str(bad)) == runbook.ERROR
    assert "is not a Basketball Monster rankings export" in capsys.readouterr().out
    empty = export(tmp_path / "empty.csv", [0, 0, 0], time.time())
    assert command(runbook, monkeypatch, "past-days", "--export", str(empty)) == runbook.ERROR
    assert "holds no player with a game" in capsys.readouterr().out
    assert command(runbook, monkeypatch, "past-days") == runbook.ERROR
    assert "no BBM_PlayerRankings* in" in capsys.readouterr().out
