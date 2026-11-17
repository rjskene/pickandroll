"""Several seasons in one replay (#172, PR D2): ``replay --seasons`` reads each season on its own
before any path, settles every cell (a season under one of the run's forecasters), skips by name a
cell whose forecaster cannot serve its season, and keys by season what is one season's; a written
run that names the confirmation season adds a line to its ledger.

The data folder is the synthetic one with every season from 2022 to 2026 (2025, the hold-out, is
on file as the preseason information a replay of 2026 reads, never replayed), with made-up wire
players so the ranking seat moves, and two quick arms: a ranking seat and a static one."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from tests.sim.sim_league import KNOBS, make_data_dir

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    folder = make_data_dir(
        tmp_path_factory.mktemp("seasons"), seasons=(2022, 2023, 2024, 2025, 2026), wire=120
    )
    assert ss.main(["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, tier in (("R", "ranking"), ("S", "static")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "market"}}
        (folder / f"{name}.json").write_text(json.dumps(spec))
    return folder


def replay(data: Path, *extra: str) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--workers", "1", "--seed", "5"]
    argv += ["--seats", str(data / "R.json"), str(data / "S.json"), *extra]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(argv)
    return code, buf.getvalue()


def written(out: str) -> dict:
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return json.loads(Path(line.removeprefix("written: ")).read_text())


def season_block(p: dict, t: str) -> dict:
    """Everything a payload holds for season ``t``."""
    return {
        "cells": p["cells"][t],
        "forecasters": p["forecasters"][t],
        "weights": p["belief"]["weights"][t],
        "players": p["players"][t],
        "shape": p["shape"][t],
        "results": p["results"][t],
        "counts": p["counts"]["by_season"][t],
        "scale": p["season_scale"]["by_season"][t],
        "unprojected": p["unprojected"]["by_season"][t],
    }


#: SHA-256 of ``replay --season 2024 --forecasters prior --paths 2 --seed 5`` on this folder as
#: the commit before ``--seasons`` gave it: its results, counts and season scale, each figure
#: rounded to nine places (they are means and SEs of whole outcomes over two paths; the rounding
#: keeps a last-bit difference in a sum's order from moving the digest).
BEFORE = "30ebecd583446e12627a88af7d7db320606e90a10fee57f75d936824ac5bf34c"


def rounded(x):
    if isinstance(x, float):
        return round(x, 9)
    if isinstance(x, dict):
        return {k: rounded(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [rounded(v) for v in x]
    return x


def figures_digest(results, counts, scale) -> str:
    figures = rounded({"results": results, "counts": counts, "scale": scale})
    return hashlib.sha256(json.dumps(figures, sort_keys=True).encode()).hexdigest()


def test_one_season_gives_what_the_commit_before_gave(data: Path):
    code, out = replay(data, "--seasons", "2024", "--forecasters", "prior", "--paths", "2")
    assert code == 0, out
    p = written(out)
    assert p["seasons"] == [2024] and p["name"] == "replay-2024" and p["replay_version"] == 10
    b = season_block(p, "2024")
    assert figures_digest(b["results"]["prior"], b["counts"]["prior"], b["scale"]) == BEFORE


def test_two_seasons_in_one_run_are_each_season_run_alone(data: Path):
    """Two seasons and two forecasters, marcel unable to serve 2023 (one season before it on
    file): its cell is skipped by name and the other three run. Each season's block equals that
    season run alone with the same seed."""
    both = ("--forecasters", "prior,marcel", "--paths", "1")
    code, out = replay(data, "--seasons", "2023,2024", *both)
    assert code == 0, out
    assert "3 tasks (3 cells x 1 paths)" in out
    assert "skipped: marcel in 2023: marcel needs 2 earlier seasons on file, it has 1" in out
    table = out[out.index("cells (seasons across") :].splitlines()[1:4]
    assert table[0].split() == ["2023", "2024"]
    assert table[1].split() == ["prior", "served", "served"]
    assert table[2].split() == ["marcel", "skipped", "served"]
    p = written(out)
    assert p["seasons"] == [2023, 2024] and p["name"] == "replay-2023-2024"
    assert p["cells"]["2023"]["marcel"] == {
        "served": False,
        "reason": "marcel needs 2 earlier seasons on file, it has 1",
    }
    assert p["cells"]["2024"]["marcel"] == {"served": True, "reason": None}
    assert set(p["results"]["2023"]) == {"prior"} and set(p["results"]["2024"]) == {
        "prior",
        "marcel",
    }
    assert p["audit"]["paths_voided"] == 0
    for t in ("2023", "2024"):
        code, alone = replay(data, "--seasons", t, *both)
        assert code == 0, alone
        assert season_block(written(alone), t) == season_block(p, t), t


def test_a_run_with_no_cell_left_or_a_stand_in_that_cannot_serve_is_refused(data: Path):
    code, out = replay(data, "--seasons", "2023", "--forecasters", "marcel", "--paths", "1")
    assert code == 2 and "refused: no cell is left" in out
    assert "skipped: marcel in 2023: marcel needs 2 earlier seasons" in out
    flags = ("--bbm-as", "marcel", "--yahoo-as", "prior", "--paths", "1")
    code, out = replay(data, "--seasons", "2023,2024", *flags)
    assert code == 2
    assert "refused: a stand-in cannot serve season 2023: marcel needs 2 earlier seasons" in out


@pytest.mark.parametrize(
    ("flags", "why"),
    [
        (("--seasons", "2024,2025"), "refused: 2025 is the hold-out"),
        (("--seasons", "2024,2023,2024"), "refused: --seasons names 2024 twice"),
        (("--seasons", "2021,2024"), "refused: season 2021 has no log on file"),
        (("--seasons", "twenty"), "refused: --seasons 'twenty'"),
        (
            ("--seasons", "2023,2024", "--no-peek", "2023-11-06"),
            "refused: --no-peek checks one season; --seasons names 2",
        ),
    ],
)
def test_the_seasons_are_refused_by_name_before_anything_runs(data: Path, flags, why):
    code, out = replay(data, *flags)
    assert code == 2 and why in out
    assert "cells (" not in out  # refused before any season was read


def ledger_lines(data: Path) -> list[dict]:
    path = data / reader.LEDGER
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


def test_a_written_run_on_the_confirmation_season_is_a_look_in_the_ledger(data: Path):
    assert ss.CONFIRMATION == 2026 and ledger_lines(data) == []
    one = ("--forecasters", "prior", "--paths", "1")
    # A dry run, a no-peek check and a run that does not name it add nothing.
    assert replay(data, "--seasons", "2026", *one, "--dry-run")[0] == 0
    assert replay(data, "--seasons", "2026", "--no-peek", "2025-11-03")[0] == 0
    assert replay(data, "--seasons", "2024", *one)[0] == 0
    assert ledger_lines(data) == []
    for n in (1, 2):
        code, out = replay(data, "--seasons", "2024,2026", *one)
        assert code == 0, out
        assert f"confirmation season 2026: look {n}, appended to" in out
        p = written(out)
        assert p["confirmation"]["look"] == n and p["confirmation"]["season"] == 2026
    first, second = ledger_lines(data)
    assert (first["look"], second["look"]) == (1, 2)
    assert set(first) == {
        "look",
        "started_at",
        "name",
        "design",
        "seasons",
        "forecasters",
        "specs",
        "fit_sha",
        "code_sha",
    }
    assert first["seasons"] == [2024, 2026] and first["forecasters"] == ["prior"]
    assert first["design"] == "room" and set(first["specs"]) == {"R", "S"}
    assert first["specs"]["R"] == ss.spec_hash(json.loads((data / "R.json").read_text()))
