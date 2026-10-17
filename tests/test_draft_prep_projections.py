"""This morning's projections (#75, scripts/draft_prep/projections.py): the import of the user's
Basketball Monster export, its refusals, the movers list, the staleness ALERT in status and run,
and the headless refresh's fallbacks. Every export here is synthetic: generated lines in the
export's column layout, no projection values."""

import importlib.util
import itertools
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "draft_day.py"
LEAGUE = "238174"
DAY = 86400.0

#: The CSV export's columns, in its order.
COLUMNS = [
    "player_id",
    "last_name",
    "first_name",
    "games",
    "minutes",
    "field_goals_attempted",
    "field_goals",
    "free_throws_attempted",
    "free_throws",
    "threes",
    "threes_attempted",
    "offensive_rebounds",
    "defensive_rebounds",
    "assists",
    "blocks",
    "steals",
    "turnovers",
    "fouls",
    "technicals",
    "double_doubles",
    "triple_doubles",
    "comments",
]
FIRST = ["Ari", "Bo", "Cal", "Dax", "Eli", "Fen", "Gus", "Hal", "Ivo", "Jem", "Kip", "Lou"]
LAST = [
    "Ash", "Birch", "Cedar", "Dune", "Elm", "Fern", "Glen", "Heath", "Iris", "Juniper",
    "Kestrel", "Larch", "Moss", "Nettle", "Oak", "Pine", "Quill", "Reed", "Sage", "Thorn",
    "Umber", "Vale", "Willow", "Yarrow", "Zinnia", "Alder", "Bramble", "Clover",
]  # fmt: skip


def lines(n: int = 330, seed: int = 0) -> pd.DataFrame:
    """``n`` synthetic players in the CSV layout, names made of letters only."""
    rng = np.random.default_rng(seed)
    names = list(itertools.product(FIRST, LAST))[:n]
    games = rng.integers(55, 80, n).astype(float)
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
            "field_goals": fga * rng.uniform(0.40, 0.58, n),
            "free_throws_attempted": fta,
            "free_throws": fta * rng.uniform(0.6, 0.9, n),
            "threes": tpa * rng.uniform(0.30, 0.40, n),
            "threes_attempted": tpa,
            "offensive_rebounds": minutes * rng.uniform(0.01, 0.1, n),
            "defensive_rebounds": minutes * rng.uniform(0.08, 0.25, n),
            "assists": minutes * rng.uniform(0.04, 0.25, n),
            "blocks": minutes * rng.uniform(0.005, 0.05, n),
            "steals": minutes * rng.uniform(0.01, 0.05, n),
            "turnovers": minutes * rng.uniform(0.03, 0.1, n),
            "fouls": minutes * rng.uniform(0.03, 0.08, n),
            "technicals": np.zeros(n),
            "double_doubles": np.zeros(n),
            "triple_doubles": np.zeros(n),
            "comments": [""] * n,
        },
        columns=COLUMNS,
    )


def write(path: Path, df: pd.DataFrame, at: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    os.utime(path, (at, at))
    return path


def day(at: float) -> str:
    return f"{datetime.fromtimestamp(at).astimezone():%Y-%m-%d}"


@pytest.fixture
def runbook(tmp_path, monkeypatch):
    """The script as a module, its root moved to a scratch folder with one league and an empty
    Downloads folder."""
    spec = importlib.util.spec_from_file_location("draft_day_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "data"
    (data / "leagues" / LEAGUE).mkdir(parents=True)
    (data / "fidelity").mkdir()
    settings = {
        "scoring": "points",
        "num_teams": 12,
        "draft": {"time": "2026-10-17T11:00:00-07:00"},
    }
    (data / "leagues" / LEAGUE / "settings.json").write_text(json.dumps(settings))
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    monkeypatch.setenv("PICKANDROLL_DOWNLOADS", str(tmp_path / "Downloads"))
    return module


def prep(runbook):
    return runbook.PREP["projections"]


def command(runbook, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["draft_day.py", *argv])
    return runbook.main()


# --------------------------------------------------------------------------- the import
def test_a_good_export_is_saved_under_its_date(runbook, monkeypatch, capsys):
    at = time.time() - 3600
    source = write(runbook.ROOT / "Downloads" / "Projections.csv", lines(), at)
    assert command(runbook, monkeypatch, "projections") == runbook.OK
    saved = runbook.DATA / f"bbm_projections_{day(at)}.csv"
    assert saved.read_bytes() == source.read_bytes()
    assert saved.stat().st_mtime == pytest.approx(at)  # the export's time is kept: the as_of
    assert source.exists()  # the user's Downloads are left as they were
    out = capsys.readouterr().out
    assert f"saved data/{saved.name} from {source}: 330 players" in out
    assert "movers" not in out  # nothing to compare with
    assert runbook.newest_projections() == saved.name


def test_the_newest_export_wins_between_downloads_and_the_repo_root(runbook, monkeypatch):
    now = time.time()
    write(runbook.ROOT / "Downloads" / "Projections.csv", lines(seed=1), now - 3 * DAY)
    newer = write(runbook.ROOT / "Projections (1).csv", lines(seed=2), now - 600)
    assert command(runbook, monkeypatch, "projections") == runbook.OK
    assert prep(runbook).newest(runbook.DATA).read_bytes() == newer.read_bytes()


def test_a_bad_schema_is_refused(runbook, monkeypatch, capsys):
    bad = lines().drop(columns=["field_goals_attempted"])
    write(runbook.ROOT / "Downloads" / "Projections.csv", bad, time.time())
    assert command(runbook, monkeypatch, "projections") == runbook.ERROR
    out = capsys.readouterr().out
    assert "is not a Basketball Monster projection export" in out
    assert "missing columns: ['field_goals_attempted']" in out and "nothing saved" in out
    assert prep(runbook).newest(runbook.DATA) is None


def test_a_partial_export_is_refused(runbook, monkeypatch, capsys):
    write(runbook.ROOT / "Downloads" / "Projections.csv", lines(n=40), time.time())
    assert command(runbook, monkeypatch, "projections") == runbook.ERROR
    assert "holds 40 players with games, under 300: a partial export" in capsys.readouterr().out
    assert prep(runbook).newest(runbook.DATA) is None


def test_no_export_anywhere_says_how_to_make_one(runbook, monkeypatch, capsys):
    assert command(runbook, monkeypatch, "projections") == runbook.ERROR
    assert "Member, Projections 26-27, Export CSV" in capsys.readouterr().out


def test_a_duplicate_saves_nothing_and_dates_the_newest_file(runbook, monkeypatch, capsys):
    now = time.time()
    df = lines()
    old = write(runbook.DATA / "bbm_projections_2026-10-14.csv", df, now - 3 * DAY)
    write(runbook.ROOT / "Downloads" / "Projections.csv", df, now - 600)
    assert command(runbook, monkeypatch, "projections") == runbook.OK
    assert prep(runbook).saved(runbook.DATA) == [old]
    assert "not saved: Projections.csv is identical to bbm_projections_2026-10-14.csv" in (
        capsys.readouterr().out
    )
    # The same projections as this morning's export: no longer stale.
    assert old.stat().st_mtime == pytest.approx(now - 600)
    assert prep(runbook).freshness(runbook)[1] is False


def test_the_same_lines_written_differently_are_a_duplicate(runbook, monkeypatch, capsys):
    now = time.time()
    df = lines()
    write(runbook.DATA / "bbm_projections_2026-10-14.csv", df, now - DAY)
    write(runbook.ROOT / "Downloads" / "Projections.csv", df[COLUMNS[::-1]], now)
    assert command(runbook, monkeypatch, "projections") == runbook.OK
    assert len(prep(runbook).saved(runbook.DATA)) == 1
    assert "is identical to" in capsys.readouterr().out


def test_an_export_older_than_the_newest_file_is_refused(runbook, monkeypatch, capsys):
    now = time.time()
    write(runbook.DATA / "bbm_projections_2026-10-17.csv", lines(seed=1), now - DAY)
    write(runbook.ROOT / "Downloads" / "Projections.csv", lines(seed=2), now - 3 * DAY)
    assert command(runbook, monkeypatch, "projections") == runbook.ERROR
    assert "is older than bbm_projections_2026-10-17.csv" in capsys.readouterr().out
    assert len(prep(runbook).saved(runbook.DATA)) == 1


def test_a_second_export_on_the_same_day_gets_its_time(runbook, monkeypatch):
    now = time.time()
    first = write(runbook.DATA / f"bbm_projections_{day(now)}.csv", lines(seed=1), now - 60)
    source = write(runbook.ROOT / "Downloads" / "Projections.csv", lines(seed=2), now)
    assert command(runbook, monkeypatch, "projections") == runbook.OK
    files = prep(runbook).saved(runbook.DATA)
    assert files[0] == first and len(files) == 2
    assert re.fullmatch(rf"bbm_projections_{day(now)}T\d{{6}}\.csv", files[1].name)
    assert files[1].read_bytes() == source.read_bytes()
    assert runbook.newest_projections() == files[1].name


def test_the_newest_file_counts_xls_by_its_date(runbook):
    for name in ("bbm_projections_2026-10-14.csv", "bbm_projections_2026-10-17.xls"):
        (runbook.DATA / name).write_text("")
    (runbook.DATA / "bbm_projections_2026-10-18.json").write_text("{}")  # not a projection
    assert runbook.newest_projections() == "bbm_projections_2026-10-17.xls"


# --------------------------------------------------------------------------- movers
def test_movers_are_names_and_directions(runbook, monkeypatch, capsys):
    now = time.time()
    before = lines()
    previous = write(runbook.DATA / "bbm_projections_2026-10-14.csv", before, now - DAY)
    # Players well inside the top 200 by value, by their rank in the previous export.
    ranked = prep(runbook).values(prep(runbook).load(previous))["value"].rank(ascending=False)
    at = {int(r): i for i, r in zip(range(len(before)), ranked, strict=True)}
    out, back, bigger, smaller, gone = at[5], at[12], at[40], at[30], at[50]
    after = before.copy()
    counts = [c for c in COLUMNS[4:21] if c != "games"]
    after.loc[out, counts] *= (after.loc[out, "games"] - 20) / after.loc[out, "games"]
    after.loc[out, "games"] -= 20  # out a month: games and totals down
    after.loc[back, "games"] += 12  # back sooner
    after.loc[bigger, counts] *= 1.6  # a bigger role
    after.loc[smaller, counts] *= 0.6  # a smaller one
    after = after.drop(index=[gone])  # gone from the export
    write(runbook.ROOT / "Downloads" / "Projections.csv", after, now)
    assert command(runbook, monkeypatch, "projections") == runbook.OK

    def name(i):
        return f"{before.loc[i, 'first_name']} {before.loc[i, 'last_name']}"

    moved = {}
    for line in capsys.readouterr().out.splitlines():
        found = re.search(r"\s{3}([a-z ]+): (.+)$", line)
        if found:
            moved[found.group(1)] = found.group(2).split(", ")
    assert moved["games down"] == [name(out)]
    assert moved["games up"] == [name(back)]
    assert name(bigger) in moved["value up"] and name(smaller) in moved["value down"]
    assert name(out) not in moved["value down"]  # listed once, for its games
    assert moved["gone from the export"] == [name(gone)]
    # Names and directions only: no number in any list.
    assert not any(re.search(r"\d", ", ".join(v)) for v in moved.values())


# --------------------------------------------------------------------------- staleness
def test_the_newest_file_older_than_two_days_raises_an_alert(runbook):
    path = runbook.DATA / "bbm_projections_2026-10-14.csv"
    write(path, lines(n=5), time.time() - 1.9 * DAY)
    line, stale = prep(runbook).freshness(runbook)
    assert not stale and line.startswith("projections bbm_projections_2026-10-14.csv, exported")
    os.utime(path, (time.time() - 2.1 * DAY,) * 2)
    line, stale = prep(runbook).freshness(runbook)
    assert stale and line.startswith("ALERT projections bbm_projections_2026-10-14.csv")
    assert "2.1 days ago" in line and "run `draft_day.py projections`" in line


def test_no_file_at_all_is_an_alert(runbook):
    line, stale = prep(runbook).freshness(runbook)
    assert stale and line.startswith("ALERT no data/bbm_projections_* file")


def test_status_prints_the_file_and_run_repeats_the_alert(runbook, monkeypatch, capsys):
    write(runbook.DATA / "bbm_projections_2026-10-14.csv", lines(n=5), time.time() - 3 * DAY)
    yahoo = {"num_teams": 12, "draft_status": "predraft", "settings": {"max_teams": 12}}
    monkeypatch.setattr(runbook, "yahoo_settings", lambda league: yahoo)
    for step in ("keep_awake", "servers", "refresh", "attach", "monitor", "finish"):
        monkeypatch.setattr(runbook, step, lambda *a, **k: runbook.OK)
    monkeypatch.setattr(runbook, "live_room", lambda league: None)
    assert command(runbook, monkeypatch, "run", LEAGUE) == runbook.OK
    alerts = [line for line in capsys.readouterr().out.splitlines() if "ALERT projections" in line]
    assert len(alerts) == 2  # status, then again before the attach
    log = (runbook.DATA / "fidelity" / f"draft_day_{LEAGUE}.log").read_text()
    assert log.count("ALERT projections bbm_projections_2026-10-14.csv") == 2


# --------------------------------------------------------------------------- the fetch
class Fetcher:
    """A stand-in for BBMFetcher: logged in or not, its download a synthetic export."""

    def __init__(self, download: Path | None, logged_in: bool = True) -> None:
        self.download, self.logged_in = download, logged_in

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ensure_login(self):
        if not self.logged_in:
            raise RuntimeError("not logged in to Basketball Monster; run once with headless=False")

    def rest_of_season(self, stat_type):
        assert stat_type == "totals"
        return self.download


def test_the_fetch_without_a_profile_keeps_the_file_on_disk(runbook, monkeypatch, capsys):
    old = write(runbook.DATA / "bbm_projections_2026-10-17.csv", lines(n=5), time.time())
    monkeypatch.setattr(prep(runbook), "open_fetcher", lambda *a: pytest.fail("no profile"))
    prep(runbook).before_attach(runbook, LEAGUE, type("Args", (), {"bbm_fetch": True})())
    assert "ALERT --bbm-fetch: no Basketball Monster profile" in capsys.readouterr().out
    assert prep(runbook).saved(runbook.DATA) == [old]


def test_a_logged_out_profile_never_signs_in(runbook, monkeypatch, capsys):
    (runbook.DATA / "bbm-profile").mkdir()
    old = write(runbook.DATA / "bbm_projections_2026-10-17.csv", lines(n=5), time.time())
    monkeypatch.setattr(prep(runbook), "open_fetcher", lambda *a: Fetcher(None, logged_in=False))
    prep(runbook).before_attach(runbook, LEAGUE, type("Args", (), {"bbm_fetch": True})())
    out = capsys.readouterr().out
    assert "ALERT --bbm-fetch: not logged in" in out and "the newest file on disk stands" in out
    assert prep(runbook).saved(runbook.DATA) == [old]


def test_the_fetch_imports_its_download(runbook, monkeypatch, capsys):
    (runbook.DATA / "bbm-profile").mkdir()
    now = time.time()
    write(runbook.DATA / "bbm_projections_2026-10-14.csv", lines(seed=1), now - 3 * DAY)
    download = write(runbook.DATA / "draft_day" / "bbm_fetch" / "ros.csv", lines(seed=2), now)
    seen = []

    def opener(profile, out):
        seen.append((profile, out))
        return Fetcher(download)

    monkeypatch.setattr(prep(runbook), "open_fetcher", opener)
    assert command(runbook, monkeypatch, "projections", "--bbm-fetch") == runbook.OK
    assert seen == [(runbook.DATA / "bbm-profile", runbook.DATA / "draft_day" / "bbm_fetch")]
    newest = prep(runbook).newest(runbook.DATA)
    assert newest.name == f"bbm_projections_{day(now)}.csv"
    assert newest.read_bytes() == download.read_bytes()
    assert "ALERT" not in capsys.readouterr().out
