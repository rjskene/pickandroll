"""The screen on a run (#172, PR H1, ``cli.cmd_screen``): the loop, the table and the record, a
pair against the same pair run by ``replay``, a screen played in pieces, the refusals, the guard on
the whole screen's estimate, every league kind once and the season scale.

The command is played on the tests' made-up data folder with the league made small (``small``):
two seats of six slots over three weeks, so a surrogate pair's path is a second or two. Only the
league's size and the season's length are the tests'; the reading, the plan, the task, the audit
and the record are the command's own. The list's own rules are ``test_sim_screen.py``'s."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import audit, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from tests.sim.sim_league import KNOBS, make_data_dir
from tests.sim.test_sim_rivals import fit_bids, table_rows, write_table

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
#: Two seats of six slots, four adds a week, both in a one-week final.
SMALL = shapes.one("fixed", shapes.LeagueShape(2, ("PG", "SG", "G", "C", "Util", "BN"), 4, 2, 1))
WEEKS = 3
#: What differs between two runs of one pair: its name, its times, and a screen's own block.
RUN_KEYS = ("name", "started_at", "finished_at", "screen")
#: The levers the unbroken screen and the one in pieces name: a nudge the knob refuses and one it
#: takes, a lever that cannot matter in a season of three weeks, one that does, and one the league
#: does not read.
LEVERS = ("protection_floor", "weeks_ahead", "surrogate_days", "system")
KEYS = ["protection_floor-down", "protection_floor-up", "weeks_ahead-6", "surrogate_days-monday"]
BASE = {
    "name": "B",
    "tier": "surrogate",
    "knobs": {**KNOBS, "daily_cap": 2, "plan_floor_cats": 0.1, "plan_floor_points": 0.01},
    "opponents": {"kind": "static"},
}


@pytest.fixture(scope="module", autouse=True)
def small():
    """The clock pinned to business hours, and the league made small: the fixed shape two seats
    of six slots, and a season of three weeks (``run.replay_setup``'s ``weeks``)."""
    real = rn.replay_setup
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        mp.setitem(ss.GRIDS, "fixed", SMALL)
        mp.setattr(rn, "replay_setup", lambda *a, **k: real(*a, **{**k, "weeks": WEEKS}))
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120, a made-up frozen fit (a replay reads its lag and
    its hash) and the baseline arms' spec files."""
    folder = make_data_dir(tmp_path_factory.mktemp("screen"), wire=120)
    fit = folder / "sim" / "fit" / "2026-01-01"
    fit.mkdir(parents=True)
    made_up = {"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}}
    (fit / "fit.json").write_text(json.dumps(made_up))
    (folder / "B.json").write_text(json.dumps(BASE))
    (folder / "W.json").write_text(json.dumps({**BASE, "pool": 45}))
    (folder / "bad.json").write_text(json.dumps({**BASE, "pol": 45}))
    return folder


def screen(
    data: Path,
    *extra: str,
    levers: tuple[str, ...] | None = LEVERS,
    name: str | None = None,
    arm: str = "B",
    seasons: str | None = "2024",
    paths: str = "2",
) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "screen", "--arm", str(data / f"{arm}.json")]
    argv += ["--workers", "1", "--seed", "5", "--paths", paths]
    argv += [] if seasons is None else ["--seasons", seasons]
    argv += [] if levers is None else ["--levers", *levers]
    argv += [] if name is None else ["--name", name]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, *extra])
    return code, buf.getvalue()


def record(data: Path, name: str) -> dict:
    got = reader.read_screen(data, name)
    assert got is not None
    return got


def pair_of(data: Path, name: str, key: str) -> dict:
    got = reader.read_screen_pair(data, name, key)
    assert got is not None
    return got


def rows_of(rec: dict) -> dict[str, dict]:
    return {r["key"]: r for r in rec["rows"]}


def folders(data: Path) -> set[str]:
    root = data / reader.SCREENS_DIR
    return {p.name for p in root.iterdir()} if root.is_dir() else set()


@pytest.fixture(scope="module")
def whole(data: Path) -> tuple[dict, str]:
    """An unbroken screen of :data:`LEVERS`: its record and what it printed."""
    code, out = screen(data, name="whole")
    assert code == 0, out
    return record(data, "whole"), out


# --------------------------------------------------------------------------- the loop
def test_every_flag_of_a_run_s_cells_and_world_is_a_key_of_the_screen_s_spec():
    """A world's flag the spec did not keep would let a folder started under one value of it be
    carried on under another (#172, the draft PR, whose ``--seat-draft`` is such a flag): every
    flag ``_cell_args`` and ``_world_args`` give a parser is a key of ``SCREEN_WORLD``, and the
    spec's other keys are the paths and the seed."""
    p = argparse.ArgumentParser(add_help=False)
    ss._cell_args(p, None)
    ss._world_args(p)
    flags = {a.dest for a in p._actions}
    assert "seat_draft" in flags and flags <= set(ss.SCREEN_WORLD)
    assert set(ss.SCREEN_WORLD) - flags == {"paths", "seed"}


def test_the_loop_plays_each_pair_and_lists_every_row_in_the_list_s_order(data: Path, whole):
    rec, out = whole
    assert (rec["kind"], rec["name"], rec["screen_version"]) == ("screen", "whole", 2)
    assert rec["note"] == ss.SCREEN_NOTE and rec["rule"] == sc.RULE
    assert rec["measure"] == "matchup_wins" and rec["hold_out"] == 2025
    assert len(rec["fit_sha"]) == 64 and rec["fit_file"].endswith("fit.json")
    assert rec["league"]["rules"] == {
        "scoring": "categories",
        "points": None,
        "held": [],
        "h2h": "one_win",
    }
    # The spec: the baseline verbatim, the levers in the list's order, the world's flags.
    spec = rec["spec"]
    assert spec["arm"] == BASE and spec["screen_version"] == 2 and spec["fit_sha"] == rec["fit_sha"]
    assert spec["replay_version"] == ss.REPLAY_VERSION
    assert set(spec) == {"screen_version", "replay_version", "arm", "levers", "world", "fit_sha"}
    assert spec["levers"] == ["protection_floor", "weeks_ahead", "surrogate_days", "system"]
    assert set(spec["world"]) == set(ss.SCREEN_WORLD)
    assert (
        spec["world"] | {"seasons": [2024], "paths": 2, "seed": 5, "waivers": "none"}
        == (spec["world"])
    )
    # Every row, in the list's order whatever the order named.
    rows = rec["rows"]
    assert [r["key"] for r in rows] == [*KEYS, "system"]
    assert [r["status"] for r in rows] == [
        sc.NOT_PLAYED,
        sc.PLAYED,
        sc.PLAYED,
        sc.PLAYED,
        sc.NOT_READ,
    ]
    assert rows[0]["why"] == "protection_floor -0.05 is below its minimum 0.0"
    assert rows[4]["why"].startswith("the run names no stand-ins for the two sources")
    assert "result" not in rows[0] and "result" not in rows[4]
    for r in rows[1:4]:
        assert (data / reader.SCREENS_DIR / "whole" / r["file"]).is_file()
        cell = r["result"]["cells"]["2024"]["prior"]
        assert set(cell["difference"]) == set(rn.METRICS) and cell["paths"] == 2
        assert all(d["n"] == 2 for d in cell["difference"].values())
        assert set(cell["counts"]) == {"a", "b"} and "landed" in cell["counts"]["a"]
        assert r["result"]["paths"] == 2 and r["result"]["voided"] == 0
    assert rec["left"] == []
    assert rec["survivors"] == [r["key"] for r in rows if (r.get("result") or {}).get("survives")]
    # Everything that is a time is under ``timing``: each pair's estimate and the one piece.
    assert set(rec["timing"]["estimates"]) == set(KEYS[1:])
    assert all(
        e["tasks"] == 2 and e["seconds_one"] > 0 for e in rec["timing"]["estimates"].values()
    )
    (piece,) = rec["timing"]["pieces"]
    assert piece["played"] == KEYS[1:] and piece["stopped"] is None
    assert piece["started_at"] < piece["finished_at"] and piece["workers"] == 1
    # What it printed: the list as it would be played, each pair as it ended, then the table.
    assert "the screen whole, its list as it would be played:" in out
    assert out.count("to play: 2 tasks, one took") == 3
    assert "3 pair(s) to play, about" in out and "the whole screen (3 pairs) about" in out
    table = out[out.index("the screen whole: matchup wins, B less A, one SE either way") :]
    assert table.splitlines()[1:-1] == sc.table(rows)
    assert (
        table.splitlines()[-1] == f"written: {data / reader.SCREENS_DIR / 'whole' / 'screen.json'}"
    )
    assert table.splitlines()[-2].startswith("survivors: ")
    assert "left for the next piece" not in out and "cells (seasons across" in out


def test_a_lever_that_cannot_matter_did_nothing_and_one_that_can_moved_the_counts(whole):
    """The lesson of PR D4c, for a screen: a lever does something at all. In a season of three
    weeks a look four weeks ahead and one six weeks ahead are one look, so both arms play one
    season on every path; a surrogate that solves on Monday only lands fewer adds than one that
    solves on Monday and Thursday."""
    rows = rows_of(whole[0])
    idle = rows["weeks_ahead-6"]["result"]
    assert idle["did_nothing"] and idle["counts_equal"] and idle["outcomes_equal"]
    assert not idle["survives"]
    cell = idle["cells"]["2024"]["prior"]
    assert all(d["mean"] == 0.0 for d in cell["difference"].values() if d["mean"] is not None)
    assert cell["counts"]["a"] == cell["counts"]["b"]
    assert "did nothing (both arms' counts and outcomes are equal on every path)" in whole[1]
    moved = rows["surrogate_days-monday"]["result"]
    assert not moved["did_nothing"] and not moved["counts_equal"]
    counts = moved["cells"]["2024"]["prior"]["counts"]
    assert 0 < counts["b"]["landed"]["mean"] < counts["a"]["landed"]["mean"]


def test_a_pair_s_record_is_a_replay_s_with_one_screen_block(data: Path, whole):
    rec = whole[0]
    got = pair_of(data, "whole", "surrogate_days-monday")
    assert (got["kind"], got["design"], got["name"]) == (
        "replay",
        "paired",
        "whole-surrogate_days-monday",
    )
    assert got["replay_version"] == ss.REPLAY_VERSION and got["confirmation"] is None
    assert got["specs"]["a"] == BASE
    assert got["specs"]["b"] == {**BASE, "name": "B:surrogate_days-monday", "surrogate_days": [0]}
    row = rows_of(rec)["surrogate_days-monday"]
    assert got["screen"] == {
        "name": "whole",
        "screen_version": 2,
        **{k: v for k, v in row.items() if k != "file"},
    }
    assert got["screen"]["both"] == {} and got["screen"]["tier"] == "surrogate"
    assert got["screen"]["values"] == {"a": [0, 3], "b": [0]}
    assert got["audit"]["paths_voided"] == 0 and got["paths"] == 2


# --------------------------------------------------------------------------- Rule 1
def same_by_replay(data: Path, name: str, key: str, flags: tuple[str, ...]) -> dict:
    """The screen ``name``'s pair ``key``, held equal to the same pair run by ``replay --arms``
    on the pair's own two specs under the same flags: key for key, apart from the run's name and
    times and the screen's own block."""
    mine = pair_of(data, name, key)
    files = []
    for side in ss.PAIR:
        files.append(data / f"{name}-{key}-{side}.json")
        files[-1].write_text(json.dumps(mine["specs"][side]))
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    argv += ["--seed", "5", "--paths", "2", *flags, "--arms", *map(str, files)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert ss.main(argv) == 0, buf.getvalue()
    (line,) = [x for x in buf.getvalue().splitlines() if x.startswith("written: ")]
    theirs = json.loads(Path(line.removeprefix("written: ")).read_text())
    assert set(mine) - set(theirs) == {"screen"} and set(theirs) <= set(mine)
    assert {k: v for k, v in mine.items() if k not in RUN_KEYS} == {
        k: v for k, v in theirs.items() if k not in RUN_KEYS
    }
    return mine


@pytest.mark.parametrize(
    ("flags", "lever", "key", "count"),
    [
        (("--waivers", "priority"), "surrogate_days", "surrogate_days-monday", "landed"),
        (
            ("--waivers", "faab", "--waiver-rule", "continuous"),
            "faab_sizing",
            "faab_sizing-2",
            "dollars_spent",
        ),
    ],
    ids=["priority", "faab"],
)
def test_rule_1_a_lever_s_pair_in_a_screen_is_the_same_pair_run_by_replay(
    data: Path, flags, lever, key, count
):
    """By priority and by FAAB: the pair a screen plays, written out as two spec files and run by
    ``replay --arms`` under the same flags, gives the screen's record key for key (the results,
    the counts, the audit, the league, the verdict), apart from the run's name and times and the
    screen's own block. The seat moves in both (by FAAB under continuous waivers, where every
    add is a bid, so the sizing is read), and the lever moves the count it is there to move."""
    name = f"rule1-{flags[1]}"
    code, out = screen(data, *flags, levers=(lever,), name=name)
    assert code == 0, out
    mine = same_by_replay(data, name, key, flags)
    assert mine["league"]["rules"]["waivers"] == flags[1]
    assert mine["audit"]["paths_voided"] == 0
    counts = mine["counts"]["by_season"]["2024"]["prior"]
    assert counts["a"]["landed"]["mean"] > 0
    assert counts["a"][count]["mean"] > 0 and counts["a"][count] != counts["b"][count]
    row = rows_of(record(data, name))[key]
    assert not row["result"]["counts_equal"] and not row["result"]["did_nothing"]


def test_the_two_sources_lever_is_played_under_the_run_s_stand_ins(data: Path):
    """With the two sources' stand-ins named, ``system`` is read, on the surrogate tier: a pair
    to the other source and one to the mix at 0.5. The screen reads a season once for each pair
    of beliefs its arms hold, and a pair whose arms hold two beliefs is still the same pair run
    by ``replay`` (Rule 1). ``blend``'s pairs are made in ``test_sim_screen.py`` and not played
    here: an oracle's stand-in is drawn a path, which is slow for a test."""
    flags = ("--bbm-as", "prior", "--yahoo-as", "oracle:0.2")
    code, out = screen(data, *flags, levers=("system",), name="sources")
    assert code == 0, out
    rows = rows_of(record(data, "sources"))
    assert list(rows) == ["system-yahoo", "system-blend"]
    assert all(r["status"] == sc.PLAYED and r["tier"] == "surrogate" for r in rows.values())
    assert all(r["both"] == {} for r in rows.values())
    assert rows["system-blend"]["values"] == {"a": "bbm", "b": "blend"}
    mine = same_by_replay(data, "sources", "system-blend", flags)
    assert mine["specs"]["b"]["knobs"]["blend"] == 0.5 and mine["audit"]["paths_voided"] == 0


# --------------------------------------------------------------------------- in pieces
def test_a_screen_played_in_pieces_records_what_one_played_unbroken_does(
    data: Path, whole, monkeypatch
):
    """Stopped after one pair by ``--max-minutes`` and run again: the second piece times nothing,
    plays only the pairs with no record, and the screen's record and every pair's are the
    unbroken screen's apart from the names and the times. The first piece's estimates are made
    up here (nothing for the first pair, twenty minutes for each other), so it stops where the
    test says."""
    timed: list[float] = []

    def fake(task, *args):
        timed.append(0.0 if not timed else 600.0)
        return timed[-1], task(*args)

    monkeypatch.setattr(ss, "timed_task", fake)
    code, out = screen(data, "--max-minutes", "15", name="pieces")
    assert code == 0, out
    assert timed == [0.0, 600.0, 600.0]
    assert (
        "stopped: --max-minutes 15: the pair of weeks_ahead-6, about 20.0 min, would pass it" in out
    )
    assert "left for the next piece: weeks_ahead-6, surrogate_days-monday; the same command" in out
    first = record(data, "pieces")
    assert [r["status"] for r in first["rows"]] == [
        sc.NOT_PLAYED,
        sc.PLAYED,
        sc.LEFT,
        sc.LEFT,
        sc.NOT_READ,
    ]
    assert first["left"] == ["weeks_ahead-6", "surrogate_days-monday"]
    (piece,) = first["timing"]["pieces"]
    assert piece["played"] == ["protection_floor-up"] and piece["finished_at"] is not None
    assert piece["stopped"].startswith("--max-minutes 15: the pair of weeks_ahead-6")
    assert sc.table(first["rows"])[3].endswith(sc.LEFT)
    # The second piece: no pair is timed again, and the first pair is not replayed.
    played: list[str] = []
    real = ss.task_paired

    def spy(*args, **kwargs):
        played.append(args[11]["b"].name)
        return real(*args, **kwargs)

    monkeypatch.setattr(ss, "task_paired", spy)
    code, out = screen(data, name="pieces")
    assert code == 0, out
    assert timed == [0.0, 600.0, 600.0]
    assert played == ["B:weeks_ahead-6"] * 2 + ["B:surrogate_days-monday"] * 2
    assert "played before" in out and "timed in" not in out and "stopped:" not in out
    again = record(data, "pieces")
    rest = ("name", "timing")
    assert {k: v for k, v in again.items() if k not in rest} == {
        k: v for k, v in whole[0].items() if k not in rest
    }
    pieces = again["timing"]["pieces"]
    assert [p["played"] for p in pieces] == [KEYS[1:2], KEYS[2:]]
    assert pieces[0] == piece and pieces[1]["stopped"] is None
    for key in KEYS[1:]:
        mine, theirs = pair_of(data, "pieces", key), pair_of(data, "whole", key)
        named = {**mine["screen"], "name": "whole"}
        assert named == theirs["screen"]
        assert {k: v for k, v in mine.items() if k not in RUN_KEYS} == {
            k: v for k, v in theirs.items() if k not in RUN_KEYS
        }
    # A third run has nothing left to play, says so, and is no piece: the record stands.
    code, out = screen(data, name="pieces")
    assert code == 0 and "0 pair(s) to play" in out and out.count("played before") == 3
    assert "the screen pieces: matchup wins, B less A" in out
    assert record(data, "pieces") == again


def test_a_screen_is_resumed_only_on_the_spec_it_was_started_with(data: Path, whole):
    for flags, kw, why in (
        (("--paths", "4"), {"paths": None}, "paths: started with 2, now 4"),
        (("--waivers", "priority"), {}, "waivers: started with 'none', now 'priority'"),
        ((), {"arm": "W"}, "the baseline arm's spec"),
        ((), {"levers": ("weeks_ahead", "system")}, "levers: started with ['protection_floor'"),
    ):
        kw = dict(kw)
        if "paths" in kw:
            flags, kw = flags[2:], {"paths": flags[1]}
        code, out = screen(data, *flags, name="whole", **kw)
        assert code == 2, out
        assert f"refused: the screen 'whole' was started with another spec ({why}" in out
        assert "name this one another (--name)" in out and "to play" not in out
    # The code's replay_version is part of the spec: a pair played under another is another pair.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "REPLAY_VERSION", ss.REPLAY_VERSION + 1)
        code, out = screen(data, name="whole")
    assert code == 2 and "replay_version: started with" in out, out
    assert record(data, "whole") == whole[0]


def test_a_screen_under_a_table_is_held_to_the_seat_s_draft_rule_in_force(data: Path, whole):
    """The spec holds the seat's draft rule in force, not the flag as typed (#172, the draft
    PR): a screen started under a table with no rule named is the market's, so it is taken up
    by the same command naming ``--seat-draft market`` and refused by one naming ``own``, by
    name. Without a table no rule is in force and the spec says none."""
    assert whole[0]["spec"]["world"]["seat_draft"] is None
    table = ("--adp", "espn", "--adp-spread", "2,0.1")
    kw = {"levers": ("surrogate_days",), "name": "table"}
    code, out = screen(data, *table, **kw)
    assert code == 0, out
    rec = record(data, "table")
    assert rec["spec"]["world"]["seat_draft"] == "market"
    assert set(rec["spec"]["world"]) == set(ss.SCREEN_WORLD)
    code, out = screen(data, *table, "--seat-draft", "market", **kw)
    assert code == 0 and "0 pair(s) to play" in out and "refused" not in out, out
    assert record(data, "table") == rec
    code, out = screen(data, *table, "--seat-draft", "own", **kw)
    assert code == 2, out
    assert "started with another spec (seat_draft: started with 'market', now 'own'" in out
    assert "to play" not in out and record(data, "table") == rec


def test_a_screen_on_the_price_book_is_held_to_the_book(data: Path, whole):
    """``--rival-bids book`` (PR Fd): the screen's spec and its record name the book the rivals
    bid on, as each pair's record does, and a piece under a newer book is refused: a newer book
    is another world. A screen that names no book holds none."""
    assert "book_sha" not in whole[0]["spec"] and "book_sha" not in whole[0]
    assert whole[0]["spec"]["world"]["rival_bids"] is None
    write_table(data, table_rows())
    assert fit_bids(data)[0] == 0
    flags = ("--waivers", "faab", "--waiver-rule", "continuous", "--rival-bids", "book")
    code, out = screen(data, *flags, levers=("surrogate_days",), name="book")
    assert code == 0, out
    rec = record(data, "book")
    _, sha, where = reader.newest_book(data)
    assert rec["spec"]["book_sha"] == rec["book_sha"] == sha and rec["book_file"] == str(where)
    assert rec["spec"]["world"]["rival_bids"] == "book"
    got = pair_of(data, "book", "surrogate_days-monday")
    assert got["book_sha"] == sha and got["league"]["rules"]["rival_bids"] == "book"
    # A newer book: the table without one of the rivals' wins, fitted again.
    rows = table_rows()
    del rows[2]
    write_table(data, rows)
    assert fit_bids(data)[0] == 0 and reader.newest_book(data)[1] != sha
    code, out = screen(data, *flags, levers=("surrogate_days",), name="book")
    assert code == 2 and "started with another spec (book_sha: started with" in out, out
    assert record(data, "book") == rec


def test_a_folder_that_is_not_this_screen_s_is_refused(data: Path):
    """A pair's file holding other arms than this screen's row, and a record that cannot be read,
    refuse the run by name: nothing is played over them and nothing is rewritten."""
    code, out = screen(data, levers=("weeks_ahead",), name="held")
    assert code == 0, out
    folder = data / reader.SCREENS_DIR / "held"
    file = folder / "weeks_ahead-6.json"
    kept = file.read_text()
    other = json.loads(kept)
    other["specs"]["b"]["weeks_ahead"] = 5
    file.write_text(json.dumps(other))
    code, out = screen(data, levers=("weeks_ahead",), name="held")
    assert code == 2, out
    assert "refused: the screen 'held' holds a pair weeks_ahead-6 of other arms" in out
    assert "to play" not in out
    file.write_text(kept)
    record_file = folder / reader.SCREEN_FILE
    whole_record = record_file.read_text()
    record_file.write_text(whole_record[: len(whole_record) // 2])
    code, out = screen(data, levers=("weeks_ahead",), name="held")
    assert code == 2 and f"refused: {record_file} is not JSON" in out, out
    record_file.write_text(whole_record)
    code, out = screen(data, levers=("weeks_ahead",), name="held")
    assert code == 0 and "0 pair(s) to play" in out and "played before" in out, out


# --------------------------------------------------------------------------- the audit
def plant(mp: pytest.MonkeyPatch, path: int) -> None:
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


def test_a_pair_whose_audit_voids_a_path_keeps_the_screen_s_exit_code(data: Path):
    """A breach voids its path in the pair it is found in, as in a replay: the pair's figures are
    over the paths left (here one, which has no SE, so nothing clears the bar), the table says a
    path was voided, and the screen exits with the audit's code, in that piece and in any later
    run of the folder."""
    with pytest.MonkeyPatch.context() as mp:
        plant(mp, 1)
        code, out = screen(data, levers=("surrogate_days",), name="voided")
    assert code == ss.AUDIT_EXIT, out
    assert "voided 1 path(s); they are listed in the payload" in out
    got = pair_of(data, "voided", "surrogate_days-monday")
    assert got["audit"]["voided"] == [{"season": 2024, "forecaster": "prior", "path": 1}]
    result = rows_of(record(data, "voided"))["surrogate_days-monday"]["result"]
    assert (result["paths"], result["voided"]) == (1, 1) and not result["survives"]
    cell = result["cells"]["2024"]["prior"]
    assert cell["paths"] == 1 and not cell["clears"]
    assert cell["difference"]["matchup_wins"]["se"] is None
    assert "(SE n/a) over 1 paths; 1 path(s) voided" in out
    # A later run of the folder plays nothing and keeps the code.
    code, out = screen(data, levers=("surrogate_days",), name="voided")
    assert code == ss.AUDIT_EXIT and "0 pair(s) to play" in out, out


# --------------------------------------------------------------------------- the refusals
def test_a_screen_refuses_by_name_before_any_path(data: Path, monkeypatch):
    def never(*a, **k):
        raise AssertionError("a path was played")

    monkeypatch.setattr(ss, "task_paired", never)
    before = folders(data)
    for kw, flags, why in (
        ({"seasons": "2025"}, (), "refused: 2025 is the hold-out; no run plays it"),
        ({"seasons": "2024,2025"}, (), "refused: 2025 is the hold-out; no run plays it"),
        ({"seasons": "2026"}, (), "refused: 2026 is the confirmation season; a screen is a search"),
        ({"seasons": "2024,2026"}, (), "refused: 2026 is the confirmation season"),
        ({"seasons": "soon"}, (), "refused: --seasons 'soon': ESPN season ids"),
        (
            {"levers": ("pool", "pol")},
            (),
            "refused: lever 'pol' is not in the screen's list: one of",
        ),
        ({}, ("--max-minutes", "0"), "refused: --max-minutes is a span in minutes, above 0"),
        ({"arm": "nowhere"}, (), "refused: --arm: "),
        ({"arm": "bad"}, (), "refused: --arm: spec key 'pol' is not one the simulator reads"),
        ({}, ("--waivers", "sealed"), "refused: --waivers sealed: one of none, priority, faab"),
        ({}, ("--waiver-days", "3"), "refused: --waiver-days 3: a dropped player's wait is"),
    ):
        code, out = screen(data, *flags, name="refused", **kw)
        assert code == 2 and why in out, out
        assert "to play" not in out
    # A nudge equal to the baseline's value refuses the whole screen, the lever named.
    code, out = screen(data, levers=("pool", "weeks_ahead"), arm="W", name="refused")
    assert code == 2, out
    assert "refused: lever pool: its nudge to 45 is the baseline's value (45)" in out
    assert "leave the lever out with --levers" in out and "to play" not in out
    assert folders(data) == before


def test_the_default_season_is_the_latest_a_search_may_play(data: Path):
    """With no season named: the latest on file that is neither the hold-out (2025) nor the
    confirmation season (2026). A list with no pair to play is a list all the same."""
    before = folders(data)
    code, out = screen(data, "--dry-run", levers=("system", "faab_sizing"), seasons=None)
    assert code == 0, out
    assert "the screen screen-2024, its list as it would be played:" in out
    assert "0 pair(s) to play, about 0.00 h" in out and "dry run, nothing written" in out
    assert out.count("not read here: ") == 2 and folders(data) == before


def test_a_dry_run_prints_the_list_and_each_pair_s_estimate_and_writes_nothing(data: Path):
    before = folders(data)
    code, out = screen(data, "--dry-run", name="dry")
    assert code == 0, out
    assert "one task of each of 3 pair(s) timed in" in out
    assert out.count("to play: 2 tasks, one took") == 3
    assert "3 pair(s) to play, about" in out and out.rstrip().endswith("dry run, nothing written")
    assert "written:" not in out and folders(data) == before


# --------------------------------------------------------------------------- the guard
def test_the_time_guard_reads_the_whole_screen_s_estimate(data: Path, monkeypatch):
    """A screen whose pairs are a little under an hour each is over an hour as a whole: it is
    refused without ``--announced``, whatever a piece of it would take. Announced, the routines'
    window is read against the piece."""
    monkeypatch.setattr(ss, "timed_task", lambda task, *args: (1700.0, task(*args)))
    before = folders(data)
    levers = ("weeks_ahead", "surrogate_days")
    code, out = screen(data, levers=levers, name="guarded")
    assert code == 2, out
    assert "2 pair(s) to play, about 1.89 h" in out
    assert "refused: a screen of about 1.88889 h is announced on the tracker" in out
    assert "whatever a piece of it takes" in out
    code, out = screen(data, "--max-minutes", "10", levers=levers, name="guarded")
    assert code == 2 and "is announced on the tracker" in out, out
    assert folders(data) == before
    # The estimate's override is the whole screen's too.
    code, out = screen(data, "--expected-hours", "0.5", "--max-minutes", "10", levers=levers, name="guarded")  # fmt: skip
    assert code == 0, out
    assert "stopped: --max-minutes 10: the pair of weeks_ahead-6, about 56.7 min" in out
    assert record(data, "guarded")["left"] == ["weeks_ahead-6", "surrogate_days-monday"]
    # Announced: a piece that would run into the routines' window is refused, a capped one is not.
    early = BUSINESS_HOURS.replace(hour=4, minute=0)
    monkeypatch.setattr(ss, "now_local", lambda: early)
    code, out = screen(data, "--announced", levers=levers, name="guarded")
    assert code == 2 and "touches the routines' window" in out, out
    code, out = screen(data, "--announced", "--max-minutes", "30", levers=levers, name="guarded")
    assert code == 0 and "stopped: --max-minutes 30" in out, out
    assert record(data, "guarded")["left"] == ["weeks_ahead-6", "surrogate_days-monday"]


# --------------------------------------------------------------------------- every league kind
@pytest.mark.parametrize(
    ("flags", "measure", "rules"),
    [
        (("--held", "IL=1"), "matchup_wins", {"held": ["IL"]}),
        (("--scoring", "points"), "matchup_wins", {"scoring": "points"}),
        (
            ("--waivers", "priority", "--waiver-rule", "continuous"),
            "matchup_wins",
            {"waivers": "priority", "waiver_rule": "continuous"},
        ),
        (("--h2h", "each_category"), "category_wins", {"h2h": "each_category"}),
    ],
    ids=["held", "points", "continuous-priority", "each-category"],
)
def test_a_screen_plays_every_kind_of_league_and_reads_its_standings_measure(
    data: Path, flags, measure, rules
):
    """Held slots, points, continuous waivers by priority and the format that counts every
    category (waivers by priority under the default rule and by FAAB under the continuous one
    are Rule 1's): the pair is played under the run's rules, the seat moves, the audit voids no
    path, and the screen reads the measure that league's standings count."""
    name = "kind-" + "-".join(flags).replace("--", "").replace("=", "-")
    code, out = screen(data, *flags, levers=("surrogate_days",), name=name)
    assert code == 0, out
    rec = record(data, name)
    assert rec["measure"] == measure and rec["league"]["rules"] | rules == rec["league"]["rules"]
    assert f"the screen {name}: {sc.MEASURE_WORDS[measure]}, B less A" in out
    (row,) = rec["rows"]
    assert row["status"] == sc.PLAYED and row["result"]["measure"] == measure
    got = pair_of(data, name, "surrogate_days-monday")
    assert got["league"]["rules"] == rec["league"]["rules"]
    assert got["audit"]["paths_voided"] == 0 and got["audit"]["breaches"] == []
    cell = row["result"]["cells"]["2024"]["prior"]
    assert cell["counts"]["a"]["landed"]["mean"] > 0
    d = cell["difference"][measure]
    assert cell["clears"] == sc.clears(d["mean"], d["se"])
    assert row["result"]["survives"] == (cell["clears"] and not row["result"]["did_nothing"])


# --------------------------------------------------------------------------- the season scale
def test_the_season_scale_is_measured_once_and_the_nudges_are_shares_of_it(data: Path, monkeypatch):
    """The scale is the mean of the baseline's ratio over the first cell's paths, read without
    playing a day: the figure the pair's own record gives arm A. The two nudges are a quarter and
    a half of it, and a second run reads the figure on file."""
    measured: list[int] = []
    real = ss.task_scale

    def spy(*args, **kwargs):
        measured.append(args[14])
        return real(*args, **kwargs)

    monkeypatch.setattr(ss, "task_scale", spy)
    code, out = screen(data, levers=("season_weight",), name="scaled")
    assert code == 0, out
    assert measured == [0, 1]
    assert "season scale: measured on 2 of 2 paths of the first cell (2024 prior)" in out
    rec = record(data, "scaled")
    scale = rec["scale"]
    assert f"s: {scale['ratio']:.4g}\n" in out
    assert scale["ratio"] > 0 and (scale["paths"], scale["of"]) == (2, 2)
    assert (
        scale["cell"] == {"season": 2024, "forecaster": "prior"} and scale["note"] == sc.SCALE_NOTE
    )
    rows = rows_of(rec)
    assert list(rows) == ["season_weight-quarter", "season_weight-half"]
    assert rows["season_weight-quarter"]["values"] == {
        "a": 0.0,
        "b": float(f"{scale['ratio'] / 4:.4g}"),
    }
    assert rows["season_weight-half"]["values"] == {
        "a": 0.0,
        "b": float(f"{scale['ratio'] / 2:.4g}"),
    }
    got = pair_of(data, "scaled", "season_weight-half")
    assert got["specs"]["b"]["knobs"]["season_weight"] == rows["season_weight-half"]["values"]["b"]
    own = got["season_scale"]["by_season"]["2024"]["a"]
    assert own["paths"] == 2 and own["ratio"] == pytest.approx(scale["ratio"], rel=1e-12)
    # Again: nothing to play, and the scale on file is the one used.
    code, out = screen(data, levers=("season_weight",), name="scaled")
    assert code == 0 and measured == [0, 1], out
    assert "season scale: measured" not in out and record(data, "scaled")["scale"] == scale
    assert (scale["paths"], scale["of"]) == (2, 2)
    assert (
        f"season scale: {scale['ratio']:.4g}, on 2 of 2 paths of the first cell, as the screen "
        "measured it when it was started" in out
    )


# --------------------------------------------------------------------------- the exact tier
def test_a_lever_of_the_exact_tier_is_played_on_it_in_both_arms(data: Path):
    """``execute_plan`` flipped: the baseline is a surrogate arm, and the pair is played on the
    exact tier in both arms, which the row and the pair's record say; ``with_plan`` beside it is
    not read, since the baseline does not execute the plan it draws. (What the pair finds is not
    pinned: on this league the two arms landed as many adds and finished apart, the case the
    rule for "did nothing" was corrected on, which ``test_sim_screen.py`` pins in made-up
    figures.)"""
    code, out = screen(data, levers=("execute_plan", "with_plan"), name="exact")
    assert code == 0, out
    rows = rows_of(record(data, "exact"))
    assert rows["with_plan"]["status"] == sc.NOT_READ
    assert rows["with_plan"]["why"] == "the plan is drawn and not executed"
    row = rows["execute_plan-flipped"]
    assert row["tier"] == "exact" and row["both"] == {"tier": "exact"}
    assert row["values"] == {"a": False, "b": True}
    got = pair_of(data, "exact", "execute_plan-flipped")
    assert got["specs"]["a"] == {**BASE, "tier": "exact"}
    assert got["specs"]["b"] == {
        **BASE,
        "tier": "exact",
        "execute_plan": True,
        "name": "B:execute_plan-flipped",
    }
    assert got["audit"]["paths_voided"] == 0 and got["screen"]["tier"] == "exact"
    result = row["result"]
    assert result["did_nothing"] == (result["counts_equal"] and result["outcomes_equal"])
    assert result["cells"]["2024"]["prior"]["counts"]["a"]["landed"]["mean"] > 0
