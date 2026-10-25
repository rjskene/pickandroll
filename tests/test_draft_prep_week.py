"""The weekly projections (#117, scripts/draft_prep/week.py): the import of a Basketball Monster
weekly export, this week or next, its span, its refusals and the sidecar the week projection
reads. The exports here are synthetic (made-up names and numbers in the draft's CSV layout),
except the sample sheet in data/, of which only counts are read."""

import importlib.util
import itertools
import json
import os
import shutil
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pickandroll.api import season_week

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draft_day.py"
#: Thursday 2026-10-22, 11:00 in New York.
NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
THU, SUN = date(2026, 10, 22), date(2026, 10, 25)
MON, NEXT_SUN = date(2026, 10, 26), date(2026, 11, 1)
FIRST = ["Ari", "Bo", "Cal", "Dax", "Eli", "Fen", "Gus", "Hal", "Ivo", "Jem", "Kip", "Lou"]
LAST = [
    "Ash", "Birch", "Cedar", "Dune", "Elm", "Fern", "Glen", "Heath", "Iris", "Juniper",
    "Kestrel", "Larch", "Moss", "Nettle", "Oak", "Pine", "Quill", "Reed", "Sage", "Thorn",
    "Umber", "Vale", "Willow", "Yarrow", "Zinnia", "Alder", "Bramble", "Clover",
]  # fmt: skip


def lines(most: int, n: int = 330, seed: int = 0) -> pd.DataFrame:
    """``n`` synthetic players in the draft's CSV layout with 0 to ``most`` games each, one of
    them with ``most``."""
    rng = np.random.default_rng(seed)
    names = list(itertools.product(FIRST, LAST))[:n]
    games = rng.integers(0, most + 1, n).astype(float)
    games[0] = most
    minutes = games * rng.uniform(14, 36, n)
    fga = minutes * rng.uniform(0.25, 0.55, n)
    fta = minutes * rng.uniform(0.05, 0.25, n)
    tpa = fga * rng.uniform(0.1, 0.5, n)
    return pd.DataFrame(
        {
            "player_id": np.arange(1, n + 1),
            "last_name": [last for _, last in names],
            "first_name": [first for first, _ in names],
            "games": games,
            "minutes": minutes,
            "field_goals_attempted": fga,
            "field_goals": fga * 0.47,
            "free_throws_attempted": fta,
            "free_throws": fta * 0.78,
            "threes": tpa * 0.35,
            "threes_attempted": tpa,
            "offensive_rebounds": minutes * 0.05,
            "defensive_rebounds": minutes * 0.15,
            "assists": minutes * 0.12,
            "blocks": minutes * 0.02,
            "steals": minutes * 0.03,
            "turnovers": minutes * 0.06,
            "fouls": minutes * 0.05,
            "technicals": np.zeros(n),
            "double_doubles": np.zeros(n),
            "triple_doubles": np.zeros(n),
            "comments": [""] * n,
        }
    )


def write(path: Path, df: pd.DataFrame, at: datetime) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    os.utime(path, (at.timestamp(), at.timestamp()))
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
    monkeypatch.setattr(module.PREP["week"], "now", lambda: NOW)
    return module


def prep(runbook):
    return runbook.PREP["week"]


def command(runbook, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["draft_day.py", *argv])
    return runbook.main()


def download(runbook, name: str = "WeeklyProjections.csv") -> Path:
    return runbook.ROOT / "Downloads" / name


def sidecar(path: Path) -> dict:
    return json.loads(path.with_suffix(".json").read_text())


# --------------------------------------------------------------------------- the span
def test_this_week_runs_to_sunday_and_next_week_monday_to_sunday(runbook):
    span = prep(runbook).span
    assert span("this", THU, None, None) == (THU, SUN)
    assert span("this", date(2026, 10, 19), None, None) == (date(2026, 10, 19), SUN)  # Monday
    assert span("this", SUN, None, None) == (SUN, SUN)
    for today in (date(2026, 10, 19), THU, SUN):
        assert span("next", today, None, None) == (MON, NEXT_SUN)
    # --start and --end set either end; the Sunday follows a moved start.
    assert span("this", THU, date(2026, 10, 23), None) == (date(2026, 10, 23), SUN)
    assert span("this", THU, None, NEXT_SUN) == (THU, NEXT_SUN)
    assert span("next", THU, date(2026, 10, 28), None) == (date(2026, 10, 28), NEXT_SUN)


# --------------------------------------------------------------------------- the import
def test_this_weeks_export_is_saved_with_its_span_and_time(runbook, monkeypatch, capsys):
    write(download(runbook), lines(3, seed=1), NOW - timedelta(hours=3))
    newer = write(
        download(runbook, "WeeklyProjections (1).csv"), lines(3), NOW - timedelta(hours=1)
    )
    assert command(runbook, monkeypatch, "week", "--this") == runbook.OK
    saved = runbook.DATA / "bbm_week_this_20261022-1400.csv"
    assert saved.read_bytes() == newer.read_bytes()
    assert saved.stat().st_mtime == pytest.approx((NOW - timedelta(hours=1)).timestamp())
    assert sidecar(saved) == {
        "source": "bbm",
        "horizon": "week",
        "as_of": "2026-10-22T14:00:00+00:00",
        "start": "2026-10-22",
        "end": "2026-10-25",
        "file": saved.name,
    }
    out = capsys.readouterr().out
    assert f"saved data/{saved.name} from {newer}: the rest of this week, " in out
    assert "Thu 2026-10-22 to Sun 2026-10-25 (4 days), 330 players" in out
    assert "at most 3" in out and len(out.strip().splitlines()) == 1
    assert newer.exists()  # the user's Downloads are left as they were


def test_next_weeks_export_covers_monday_to_sunday(runbook, monkeypatch, capsys):
    write(download(runbook), lines(4), NOW - timedelta(days=3))  # Monday this week
    assert command(runbook, monkeypatch, "week", "--next") == runbook.OK
    (saved,) = runbook.DATA.glob("bbm_week_next_*.csv")
    meta = sidecar(saved)
    assert (meta["start"], meta["end"]) == ("2026-10-26", "2026-11-01")
    assert "next week, Mon 2026-10-26 to Sun 2026-11-01 (7 days)" in capsys.readouterr().out


def test_the_sample_sheet_is_validated_and_named(runbook, monkeypatch, capsys, bbm_pergame_path):
    week = prep(runbook)
    df = week.read(bbm_pergame_path)
    most = int(df["games"].max())
    source = download(runbook, "WeeklyProjections.xls")
    shutil.copy2(bbm_pergame_path, source)
    at = NOW - timedelta(hours=2)
    os.utime(source, (at.timestamp(), at.timestamp()))
    if len(df) < week.MIN_PLAYERS:
        # The sample is a top-players page: refused as partial at the real threshold.
        assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
        assert f"holds {len(df)} players, under {week.MIN_PLAYERS}" in capsys.readouterr().out
        monkeypatch.setattr(week, "MIN_PLAYERS", len(df))
    # A span shorter than its most games refuses it.
    end = (THU + timedelta(days=most - 2)).isoformat()
    assert command(runbook, monkeypatch, "week", "--this", "--end", end) == runbook.ERROR
    assert f"has a player with {most} games in a {most - 1}-day span" in capsys.readouterr().out
    assert command(runbook, monkeypatch, "week", "--next") == runbook.OK
    saved = runbook.DATA / "bbm_week_next_20261022-1300.xls"
    assert saved.read_bytes() == source.read_bytes()
    assert sidecar(saved)["file"] == saved.name
    assert week.read(saved).equals(df)


def test_a_season_export_saved_as_a_weekly_one_is_refused(runbook, monkeypatch, capsys):
    write(download(runbook), lines(5), NOW)
    assert command(runbook, monkeypatch, "week", "--this") == runbook.ERROR
    out = capsys.readouterr().out
    assert "has a player with 5 games in a 4-day span (Thu 2026-10-22 to Sun 2026-10-25)" in out
    assert "a season or longer export? Nothing saved" in out
    assert not list(runbook.DATA.glob("bbm_week_*"))
    # Five games fit next week's seven days.
    assert command(runbook, monkeypatch, "week", "--next") == runbook.OK


def test_the_season_sample_is_refused(runbook, monkeypatch, capsys, bbm_totals_path):
    shutil.copy2(bbm_totals_path, download(runbook, "WeeklyProjections.xls"))
    assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
    assert "games in a 7-day span" in capsys.readouterr().out
    assert not list(runbook.DATA.glob("bbm_week_*"))


def test_a_one_day_span_takes_a_seventh_of_the_floor(runbook, monkeypatch, capsys):
    """Sunday's Remaining Week lists only the players with a game that day (#181)."""
    sunday = datetime(2026, 10, 25, 15, 0, tzinfo=UTC)
    week = prep(runbook)
    monkeypatch.setattr(week, "now", lambda: sunday)
    assert [week.min_players("this", d) for d in (1, 2, 4, 7, 9)] == [43, 86, 172, 300, 300]
    assert week.min_players("next", 1) == week.min_players("next", 7) == 300
    write(download(runbook), lines(1, n=39), sunday)
    assert command(runbook, monkeypatch, "week", "--this") == runbook.ERROR
    out = capsys.readouterr().out
    assert "holds 39 players, under 43 for a 1-day span (300 × 1/7): a partial export" in out
    assert not list(runbook.DATA.glob("bbm_week_*"))
    write(download(runbook), lines(1, n=139), sunday)
    assert command(runbook, monkeypatch, "week", "--this") == runbook.OK
    (saved,) = runbook.DATA.glob("bbm_week_this_*.csv")
    assert (sidecar(saved)["start"], sidecar(saved)["end"]) == ("2026-10-25", "2026-10-25")
    assert "Sun 2026-10-25 to Sun 2026-10-25 (1 day), 139 players" in capsys.readouterr().out
    # Next week keeps the full floor.
    write(download(runbook), lines(3, n=299, seed=1), sunday)
    assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
    assert "holds 299 players, under 300: a partial export" in capsys.readouterr().out


def test_a_partial_or_unreadable_export_or_none_is_refused(runbook, monkeypatch, capsys, tmp_path):
    write(download(runbook), lines(3, n=40), NOW)
    assert command(runbook, monkeypatch, "week", "--this") == runbook.ERROR
    assert (
        "holds 40 players, under 172 for a 4-day span (300 × 4/7): a partial export"
        in capsys.readouterr().out
    )
    bad = write(tmp_path / "bad.csv", lines(3).drop(columns=["field_goals_attempted"]), NOW)
    assert command(runbook, monkeypatch, "week", "--this", "--export", str(bad)) == runbook.ERROR
    assert "is not a Basketball Monster weekly export" in capsys.readouterr().out
    download(runbook).unlink()
    assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
    out = capsys.readouterr().out
    assert "no WeeklyProjections* in" in out
    assert "Weekly Projections, Next Week, All Players, Refresh, Export to Excel" in out
    assert not list(runbook.DATA.glob("bbm_week_*"))


def test_an_older_download_is_refused(runbook, monkeypatch, capsys):
    yesterday = write(download(runbook), lines(4), NOW - timedelta(days=1))
    assert command(runbook, monkeypatch, "week", "--this") == runbook.ERROR
    assert "was exported Wed 2026-10-21, not today (Thu 2026-10-22)" in capsys.readouterr().out
    # Made last week, its Next Week was this week.
    write(yesterday, lines(4), NOW - timedelta(days=5))
    assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
    assert "not in the week before Mon 2026-10-26" in capsys.readouterr().out
    assert not list(runbook.DATA.glob("bbm_week_*"))
    # A span given by its first day is taken as given.
    args = ("week", "--next", "--start", "2026-10-26")
    assert command(runbook, monkeypatch, *args) == runbook.OK


def test_a_repeat_saves_nothing_and_the_other_kinds_export_is_refused(runbook, monkeypatch, capsys):
    write(download(runbook), lines(3), NOW - timedelta(hours=1))
    assert command(runbook, monkeypatch, "week", "--this") == runbook.OK
    capsys.readouterr()
    assert command(runbook, monkeypatch, "week", "--this") == runbook.OK
    assert (
        "not saved: WeeklyProjections.csv is identical to bbm_week_this_20261022-1400.csv, "
        "saved for Thu 2026-10-22 to Sun 2026-10-25; it stands"
    ) in capsys.readouterr().out
    # The Next Week download did not land: the newest download is still this week's.
    assert command(runbook, monkeypatch, "week", "--next") == runbook.ERROR
    out = capsys.readouterr().out
    assert "is identical to bbm_week_this_20261022-1400.csv (the rest of this week" in out
    assert "Check that the Next Week export landed; nothing saved" in out
    assert [p.name for p in runbook.DATA.glob("bbm_week_*.csv")] == [
        "bbm_week_this_20261022-1400.csv"
    ]


def test_the_start_and_end_set_the_span(runbook, monkeypatch, capsys):
    write(download(runbook), lines(2), NOW)
    argv = ("week", "--this", "--start", "2026-10-23", "--end", "2026-10-24")
    assert command(runbook, monkeypatch, *argv) == runbook.OK
    (saved,) = runbook.DATA.glob("bbm_week_this_*.csv")
    assert (sidecar(saved)["start"], sidecar(saved)["end"]) == ("2026-10-23", "2026-10-24")
    capsys.readouterr()
    assert command(runbook, monkeypatch, "week", "--this", "--start") == runbook.ERROR
    assert "week --start needs a date" in capsys.readouterr().out
    argv = ("week", "--next", "--start", "2026-10-28", "--end", "2026-10-27")
    assert command(runbook, monkeypatch, *argv) == runbook.ERROR
    assert "the span ends before it starts" in capsys.readouterr().out
    assert command(runbook, monkeypatch, "week", "--next", "--start", "Monday") == runbook.ERROR
    assert "not a date (YYYY-MM-DD): 'Monday'" in capsys.readouterr().out
    assert command(runbook, monkeypatch, "week") == runbook.ERROR
    assert "week needs --this or --next" in capsys.readouterr().out


def test_servers_start_is_still_a_switch(runbook, monkeypatch):
    seen = []
    monkeypatch.setattr(runbook, "servers", lambda start=False: seen.append(start) or runbook.OK)
    assert command(runbook, monkeypatch, "servers", "--start") == runbook.OK
    assert command(runbook, monkeypatch, "servers") == runbook.OK
    assert seen == [True, False]


# --------------------------------------------------------------------------- the week projection
def test_the_sidecar_round_trips_through_the_week_projection(runbook, monkeypatch):
    write(download(runbook), lines(3), NOW - timedelta(hours=1))
    assert command(runbook, monkeypatch, "week", "--this") == runbook.OK
    write(download(runbook, "WeeklyProjections (1).csv"), lines(4, seed=2), NOW)
    assert command(runbook, monkeypatch, "week", "--next") == runbook.OK
    data = runbook.DATA
    this = season_week._latest(data, (season_week.BBM_THIS_WEEK,))
    following = season_week._latest(data, (season_week.BBM_NEXT_WEEK,))
    assert this.name == "bbm_week_this_20261022-1400.csv"
    assert following.name == "bbm_week_next_20261022-1500.csv"
    assert season_week._covers(this, THU, SUN, THU)
    assert season_week._covers(following, MON, NEXT_SUN, THU)
    # After a 19:00 ET matchup read the week projects from Friday: this export is not counted
    # (its games include today's).
    assert not season_week._covers(this, THU + timedelta(days=1), SUN, THU)
    assert not season_week._covers(following, THU, SUN, THU)
