"""The tune on a run (#172, PR H2, ``cli.cmd_tune``): the search and its order, the sign rule,
the confirmation and the ledger, a pair against the same pair run by ``replay``, a tune played in
pieces, the refusals, the guard on the whole tune's estimate, the rivals' two cells and the
league's measure.

The command is played on the tests' made-up data folder with the league made small, as the
screen's tests make it. A lever built to help, one built to do nothing and one that depends on
the season need a world that says so, so most tests play a made-up one (:func:`made_up`): every
pair is planned, its tasks made, its record built, audited and written by the command's own
code, and what one task's season came to is what the made-up world says of its two arms. Rule
1's tests play the true task. A season is read by the command's own reader and remembered across
the module's commands (:data:`READS` keeps what each command asked for), so the made-up logs are
parsed once a season and league. The rules themselves are ``test_sim_tune.py``'s."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import shutil
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import audit, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import screen as sc
from pickandroll.sim import tune as tn
from pickandroll.sim.lab import server as sv
from tests.sim.sim_league import KNOBS, make_data_dir

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
#: Two seats of six slots, four adds a week, both in a one-week final.
SMALL = shapes.one("fixed", shapes.LeagueShape(2, ("PG", "SG", "G", "C", "Util", "BN"), 4, 2, 1))
WEEKS = 3
#: What differs between a tune's pair and the same pair run by ``replay``: its name, its times,
#: and the tune's own block.
RUN_KEYS = ("name", "started_at", "finished_at", "tune")
BASE = {
    "name": "B",
    "tier": "surrogate",
    "knobs": {**KNOBS, "daily_cap": 2, "plan_floor_cats": 0.1, "plan_floor_points": 0.01},
    "opponents": {"kind": "static"},
}
#: The baseline against rivals that move: its confirmation is played twice.
RIVALS = {**BASE, "name": "R", "opponents": {"kind": "market", "rate": 0.2}}
#: The baseline against its mirror: on the exact tier the mirror reads what the surrogate reads.
MIRROR = {**BASE, "name": "M", "opponents": {"kind": "mirror"}}
#: A baseline that executes a week plan it does not draw: ``execute_plan`` is read only once
#: ``with_plan`` has moved.
PLANLESS = {**BASE, "name": "P", "with_plan": False, "execute_plan": True}
LEVERS = ("weeks_ahead", "pool")
#: Every season a ``screen`` or ``tune`` command asked its reader for, in the order asked.
READS: list[int] = []


@pytest.fixture(scope="module", autouse=True)
def small():
    """The clock pinned to business hours, and the league made small: the fixed shape two seats
    of six slots, and a season of three weeks (``run.replay_setup``'s ``weeks``). The commands'
    reader of seasons (``cli.remembering``) is one for the module, and says what it is asked.
    A made-up log is parsed once for the module too (``readers.replay_lines``): every tune that
    confirms asks, before its first pair, what serves the season confirmed on (the season
    before it, for ``prior``), and no test here writes a log."""
    real = rn.replay_setup
    kept = ss.remembering()
    lines_of = reader.replay_lines
    parsed: dict[tuple[str, int], tuple] = {}

    def read(data, season, *a, **k):
        READS.append(season)
        return kept(data, season, *a, **k)

    def replay_lines(data, season):
        key = (str(data), season)
        if key not in parsed:
            parsed[key] = lines_of(data, season)
        return parsed[key]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        mp.setitem(ss.GRIDS, "fixed", SMALL)
        mp.setattr(rn, "replay_setup", lambda *a, **k: real(*a, **{**k, "weeks": WEEKS}))
        mp.setattr(ss, "remembering", lambda: read)
        mp.setattr(reader, "replay_lines", replay_lines)
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    """Five made-up seasons with a wire of 120 (2022 is there so that 2023 has a prior season),
    a made-up frozen fit and the baseline arms' spec files."""
    seasons = (2022, 2023, 2024, 2025, 2026)
    folder = make_data_dir(tmp_path_factory.mktemp("tune"), seasons=seasons, wire=120)
    fit = folder / "sim" / "fit" / "2026-01-01"
    fit.mkdir(parents=True)
    made = {"hold_out": 2025, "parameters": {"refresh_defaults": {"lag": 1}}}
    (fit / "fit.json").write_text(json.dumps(made))
    (folder / "B.json").write_text(json.dumps(BASE))
    (folder / "R.json").write_text(json.dumps(RIVALS))
    (folder / "W.json").write_text(json.dumps({**BASE, "pool": 45}))
    (folder / "bad.json").write_text(json.dumps({**BASE, "pol": 45}))
    (folder / "M.json").write_text(json.dumps(MIRROR))
    (folder / "X.json").write_text(json.dumps({**BASE, "name": "X", "tier": "exact"}))
    (folder / "P.json").write_text(json.dumps(PLANLESS))
    return folder


# --------------------------------------------------------------------------- the made-up world
#: Where ``task_paired``'s arguments hold the season, the forecaster, the arms, the pair's two
#: keys, the path and the league's rules (``cli.replay_tasks``).
SEASON, FORECASTER, ARMS, SIDES, PATH, RULES = 0, 4, 11, 12, 14, 17
TRUE_TASK = ss.task_paired
#: A made-up world's word for "play this task truly".
REALLY = "really"
#: One true task's result a forecaster, path and league: the record a made-up world's outcomes
#: are written on (its seat, its counts' keys, its scale; never its outcomes).
CARRIED: dict[tuple, dict] = {}


def made_up(world, log: list | None = None, breach: tuple[int, int] | None = None):
    """``task_paired`` in a made-up world. ``world(a, b, season, path)`` says what arm B's season
    came to against arm A's on that path: a number (the difference on the two measures of wins;
    a tenth of it on playoff odds; its opposite on the final rank, where lower is better), a
    difference by outcome, None when both arms played one season (equal counts, no difference),
    or :data:`REALLY`. Any other answer moves arm B's count of landed adds. ``log`` takes each
    task's season and arm B's name; ``breach`` plants one audit breach on a (season, path)."""

    def task(*args):
        season, label, path = args[SEASON], args[FORECASTER].label, args[PATH]
        a, b = (args[ARMS][k] for k in args[SIDES])
        if log is not None:
            log.append((season, b.name))
        said = world(a, b, season, path)
        if said is REALLY:
            return TRUE_TASK(*args)
        key = (label, path, repr(args[RULES]))
        if key not in CARRIED:
            CARRIED[key] = TRUE_TASK(*args)
        out = copy.deepcopy(CARRIED[key])
        if isinstance(said, dict):
            by = said
        elif said is None:
            by = {}
        else:
            by = {"matchup_wins": said, "category_wins": said, "made_playoffs": said / 10}
            by["rank"] = -said
        delta = {m: None if out["a"][m] is None else float(by.get(m, 0.0)) for m in rn.METRICS}
        out["delta"] = delta
        out["b"] = {
            **out["a"],
            **{m: d if d is None else out["a"][m] + d for m, d in delta.items()},
        }
        landed = out["counts"]["a"]["landed"]
        out["counts"]["b"] = {**out["counts"]["a"], "landed": landed + (said is not None)}
        out["breaches"] = []
        if breach == (season, path):
            planted = audit.Breach(date(2026, 1, 1), 1, 1, "planted", "the test's breach", path)
            out["breaches"] = [planted.payload()]
        return out

    return task


def pool(arm: rn.Arm) -> float:
    return float(sc.value_of(arm, "pool"))


def worth_world(worth, wobble=0.25):
    """The made-up world of an arm's ``worth(arm, season)``: a pair's difference is arm B's
    worth less arm A's, a share ``wobble`` wider on each later path, so that it has an SE (on
    two paths the difference over its SE is ``(2 + wobble) / wobble``: 9 at a quarter, 3 at
    one). Two arms worth the same played one season."""

    def world(a: rn.Arm, b: rn.Arm, season: int, path: int):
        d = worth(b, season) - worth(a, season)
        w = wobble(a, b) if callable(wobble) else wobble
        return None if d == 0 else d * (1 + w * path)

    return world


#: The world most tests play: a wider candidate pool is worth more, in every season.
WIDER = worth_world(lambda arm, season: pool(arm) / 15)


def run_of(command: str, data: Path, arm: str, *flags: str) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", command, "--arm", str(data / f"{arm}.json")]
    argv += ["--workers", "1", "--seed", "5", *flags]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(argv)
    return code, buf.getvalue()


def tune(
    data: Path,
    *extra: str,
    levers: tuple[str, ...] | None = LEVERS,
    name: str | None = None,
    arm: str = "B",
    seasons: str | None = "2024",
    screen: str | None = None,
    confirm: str | None = None,
) -> tuple[int, str]:
    """One ``tune`` command and what it printed. Whatever it prints recommends and never says
    more: no "optimal" anywhere, and a promotion only to say there is none."""
    flags = ["--paths", "2"]
    flags += [] if seasons is None else ["--seasons", seasons]
    flags += [] if levers is None else ["--levers", *levers]
    flags += [] if name is None else ["--name", name]
    flags += [] if screen is None else ["--screen", screen]
    flags += [] if confirm is None else ["--confirm", confirm]
    code, out = run_of("tune", data, arm, *flags, *extra)
    low = out.lower()
    assert "optimal" not in low and "optimum" not in low, out
    assert low.count("promot") == low.count("promotes nothing"), out
    return code, out


def record(data: Path, name: str) -> dict:
    got = reader.read_tune(data, name)
    assert got is not None
    return got


def pair_of(data: Path, name: str, key: str) -> dict:
    got = reader.read_tune_pair(data, name, key)
    assert got is not None
    return got


def files(data: Path, name: str) -> set[str]:
    return {p.name for p in reader.tune_dir(data, name).iterdir()}


def folders(data: Path) -> set[str]:
    out: set[str] = set()
    for root in (reader.TUNES_DIR, reader.SCREENS_DIR, reader.RUNS_DIR):
        if (data / root).is_dir():
            out |= {f"{root.name}/{p.name}" for p in (data / root).iterdir()}
    return out


def looks(data: Path) -> list[dict]:
    return reader.read_looks(data)


def of_kind(lines: list[dict], kind_sha: str) -> int:
    return sum(1 for x in lines if x.get("design") == "tune" and x["league_kind_sha"] == kind_sha)


@pytest.fixture(scope="module")
def whole(data: Path) -> tuple[dict, str, list, list, list]:
    """An unbroken tune of :data:`LEVERS` in the world where a wider pool is worth more: its
    record, what it printed, each task's season and arm B in the order played, the ledger's
    lines before it, and the seasons it asked its reader for."""
    log: list = []
    before, mark = looks(data), len(READS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER, log))
        code, out = tune(data, name="whole")
    assert code == 0, out
    return record(data, "whole"), out, log, before, READS[mark:]


# --------------------------------------------------------------------------- the search
def test_the_search_takes_the_lever_built_to_help_and_leaves_the_one_built_to_do_nothing(whole):
    """A wider pool is worth more, and the look ahead is worth nothing: the tune moves the pool
    to its nudge again, the better of its two values, and leaves the look ahead where it is,
    saying it did nothing."""
    rec, out = whole[:2]
    assert (rec["kind"], rec["name"], rec["tune_version"]) == ("tune", "whole", 2)
    assert rec["note"] == ss.TUNE_NOTE and rec["rule"] == tn.SEARCH_RULE
    assert rec["carry"] == tn.CARRY_NOTE and rec["hold_out"] == 2025 and rec["left"] is None
    assert rec["measure"] == "matchup_wins" and len(rec["fit_sha"]) == 64
    # Named by hand: the list's order, whatever the order named, fixed before any pair.
    assert [o["lever"] for o in rec["order"]] == ["pool", "weeks_ahead"]
    assert all(o["place"] == tn.BY_HAND for o in rec["order"])
    assert "order, fixed before any pair: pool, weeks_ahead" in out
    moved, stayed = rec["steps"]
    assert (moved["pass"], moved["lever"], moved["from"]) == (1, "pool", 30)
    assert [v["key"] for v in moved["values"]] == ["pool-45", "pool-45-again"]
    assert [v["values"] for v in moved["values"]] == [{"a": 30, "b": 45}, {"a": 30, "b": 60}]
    assert [v["file"] for v in moved["values"]] == ["p1-pool-45.json", "p1-pool-45-again.json"]
    once, twice = (v["result"] for v in moved["values"])
    assert 0 < once["mean"] < twice["mean"] and once["clears"] and twice["clears"]
    assert twice["signs"] == tn.ABOVE and twice["mean"] > twice["se"] > 0
    assert moved["choice"] == {
        "key": "pool-45-again",
        "passed": [],
        "standings": {"pool-45": tn.BEATEN, "pool-45-again": tn.TAKEN},
        "depends": [],
    }
    assert moved["change"] == {"pool": 60}
    assert moved["why"].startswith("pool moves from 30 to 60 (pool-45-again): matchup wins +")
    assert f"pass 1: {moved['why']}" in out
    # The lever that does nothing: both its values are played, and it stays.
    assert (stayed["lever"], stayed["from"], stayed["change"]) == ("weeks_ahead", 4, None)
    assert [v["key"] for v in stayed["values"]] == ["weeks_ahead-6", "weeks_ahead-6-again"]
    assert all(v["result"]["did_nothing"] and not v["result"]["clears"] for v in stayed["values"])
    assert stayed["choice"]["key"] is None
    assert stayed["why"] == (
        "weeks_ahead stays at 4: no value counts and clears one SE (weeks_ahead-6: "
        f"{tn.NOTHING}; weeks_ahead-6-again: {tn.NOTHING})"
    )
    assert f"pass 1: {stayed['why']}" in out
    # Every pair carries every outcome, the title among them.
    cell = twice["cells"]["2024"]["prior"]
    assert set(cell["difference"]) == set(rn.METRICS) and cell["read"]
    final = rec["final"]
    assert final["set"] == {"pool": 60} and final["arm"] == {**BASE, "pool": 60}
    assert (final["levers"], final["tier"], final["unread"]) == (["pool"], "surrogate", {})
    assert "the final set (what the search changed in the baseline): pool 60" in out


def test_each_value_is_a_pair_against_the_current_arm_with_one_tune_block(data: Path, whole):
    """A value's pair is a replay's record with a block of the tune's own; arm A is the arm the
    search stands on, so the lever after the pool's is tried from the pool's new value."""
    rec = whole[0]
    assert files(data, "whole") == {
        "tune.json",
        "p1-pool-45.json",
        "p1-pool-45-again.json",
        "p1-weeks_ahead-6.json",
        "p1-weeks_ahead-6-again.json",
        "confirm-run.json",
    }
    got = pair_of(data, "whole", "p1-pool-45-again")
    assert (got["kind"], got["design"], got["name"]) == (
        "replay",
        "paired",
        "whole-p1-pool-45-again",
    )
    assert got["confirmation"] is None and got["seasons"] == [2024] and got["paths"] == 2
    assert got["specs"] == {"a": BASE, "b": {**BASE, "name": "B:pool-45-again", "pool": 60}}
    value = rec["steps"][0]["values"][1]
    assert got["tune"] == {
        "name": "whole",
        "tune_version": 2,
        "stage": "static",
        "pass": 1,
        **{k: v for k, v in value.items() if k != "file"},
    }
    later = pair_of(data, "whole", "p1-weeks_ahead-6-again")
    assert later["specs"]["a"] == {**BASE, "pool": 60}
    assert tn.change_of(later["specs"]["a"], later["specs"]["b"]) == {"weeks_ahead": 8}


def test_the_confirmation_season_is_read_once_at_the_end_and_its_look_is_counted(data, whole):
    """No task of the search is the confirmation season's. The final set is played against the
    baseline on it after the last step, the ledger gains one line before that, and the record
    and the verdict say which look it is."""
    rec, out, log, before, reads = whole
    seasons = [t for t, _ in log]
    first = seasons.index(2026)
    assert set(seasons[:first]) == {2024} and set(seasons[first:]) == {2026}
    assert [b for t, b in log if t == 2026] == ["B:tuned"] * 2
    # The season is asked of the reader once, for the final pair, after every pair of the search.
    assert reads.count(2026) == 1 and reads[-1] == 2026 and set(reads[:-1]) == {2024}
    conf = rec["confirmation"]
    assert (conf["season"], conf["status"], conf["tier"]) == (2026, tn.CONFIRMED, "surrogate")
    # The baseline's rivals are static, so the two kinds of rivals are one pair.
    assert conf["files"] == {"run": "confirm-run.json"}
    assert conf["arms"] == {"run": {"a": BASE, "b": {**BASE, "name": "B:tuned", "pool": 60}}}
    cell = conf["cells"]["run"]["prior"]
    assert (cell["read"], cell["finish"], cell["paths"]) == (True, tn.AHEAD, 2)
    # The final pair's mechanism counts, both arms' and the rivals'.
    assert set(cell["counts"]) == {"a", "b", "rivals"}
    assert cell["counts"]["b"]["landed"]["mean"] == cell["counts"]["a"]["landed"]["mean"] + 1
    verdict = conf["verdict"]
    assert (verdict["state"], verdict["flags"], verdict["read"]) == (tn.HOLDS, [], ["prior"])
    assert "the final set is recommended" in out and tn.ADVISORY in out
    # The tier both arms are confirmed on is said: here the baseline's own.
    assert (
        "the confirmation, the final set against the baseline, both arms on the surrogate "
        "tier: confirmation season 2026: look"
    ) in out
    assert (conf["skipped"], conf["one_seat"], verdict["missing"]) == ({}, {}, {})
    assert verdict["unconfirmed"] == {} and conf["cells"]["run"]["prior"]["mark"] is None
    # One line more, written by this tune.
    after = looks(data)
    assert len(after) == len(before) + 1
    line = after[len(before)]
    assert (line["look"], line["design"], line["name"]) == (len(after), "tune", "whole")
    assert line["seasons"] == [2026] and line["search_seasons"] == [2024]
    assert line["tune_started_at"] == rec["timing"]["pieces"][0]["started_at"]
    assert line["spec_sha"] == ss.spec_hash(rec["spec"]) and line["code_sha"] == rec["code_sha"]
    assert line["league_kind"] == rec["league"]["kind"] and line["fit_sha"] == rec["fit_sha"]
    assert line["league_kind_sha"] == ss.spec_hash(rec["league"]["kind"])
    assert datetime.fromisoformat(line["started_at"]) is not None
    look = conf["look"]
    assert look["look"] == line["look_of_kind"] == 1 + of_kind(before, line["league_kind_sha"])
    assert (look["line"], look["season"], look["note"]) == (line["look"], 2026, ss.TUNE_LOOK_NOTE)
    assert look["others"] == len(before) - of_kind(before, line["league_kind_sha"])
    assert (
        f"confirmation season 2026: look {look['look']} for this league kind (line "
        f"{look['line']} of {data / reader.LEDGER}; {look['others']} earlier line(s) are other "
        "runs')"
    ) in out
    # The verdict's own line says both numbers.
    assert (
        f"verdict (advisory; look {look['look']} for this league kind, line {look['line']} of "
        f"the ledger): {tn.VERDICT_WORDS[tn.HOLDS]}"
    ) in out
    pair = pair_of(data, "whole", "confirm-run")
    assert pair["seasons"] == [2026] and pair["specs"] == conf["arms"]["run"]
    assert pair["confirmation"]["look"] == line["look"]
    assert pair["tune"]["confirmation"] == "run" and pair["tune"]["look"] == look


def test_a_second_tune_says_look_2_and_a_tune_taken_up_again_is_counted_once(data, whole):
    """A second tune of the same league kind is look 2, counted and not refused; a replay's line
    and another kind's tune are counted in the ledger and not in the kind's number; a tune run
    again, or taken up after it died in its confirmation, adds no line; the same tune started
    again in a new folder is one more look."""
    kind = whole[0]["league"]["kind"]
    kind_sha = ss.spec_hash(kind)
    reader.append_look(data, {"name": "a-replay", "design": "paired", "seasons": [2026]})
    before = looks(data)
    log: list = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER, log))
        code, out = tune(data, levers=("pool",), name="second")
        assert code == 0, out
        n = 1 + of_kind(before, kind_sha)
        assert n >= 2 and len(looks(data)) == len(before) + 1
        assert record(data, "second")["confirmation"]["look"]["look"] == n
        assert f"confirmation season 2026: look {n} for this league kind (line " in out
        assert f"{len(before) - of_kind(before, kind_sha)} earlier line(s) are other runs'" in out
        # Another league kind counts from its own first look.
        code, out = tune(data, "--scoring", "points", levers=("pool",), name="other-kind")
        assert code == 0, out
        other = record(data, "other-kind")
        assert other["league"]["kind"] != kind and other["confirmation"]["look"]["look"] == 1
        assert other["confirmation"]["look"]["line"] == len(before) + 2
        # Run again with nothing left to play: no task, no line, the same record.
        counted = looks(data)
        kept = record(data, "second")
        del log[:]
        code, out = tune(data, levers=("pool",), name="second")
        assert code == 0 and log == [] and looks(data) == counted, out
        assert out.count("played before") == 2 and "appended" not in out
        assert f"look {n} for this league kind" in out and record(data, "second") == kept
        # Died after its look was counted and before its pair was written: the pair is played,
        # and the look is the one it already has.
        (reader.tune_dir(data, "second") / "confirm-run.json").unlink()
        code, out = tune(data, levers=("pool",), name="second")
        assert code == 0 and [b for _, b in log] == ["B:tuned"] * 2, out
        assert looks(data) == counted and "appended" not in out
        again = record(data, "second")
        assert again["confirmation"] == kept["confirmation"]
        # The folder removed and the same tune started again: the season is read again, so it
        # is another look, counted and not hidden.
        shutil.rmtree(reader.tune_dir(data, "second"))
        code, out = tune(data, levers=("pool",), name="second")
        assert code == 0 and len(looks(data)) == len(counted) + 1, out
        assert record(data, "second")["confirmation"]["look"]["look"] == n + 1
        assert f"look {n + 1} for this league kind (line {len(counted) + 1} of " in out


def screen_worth(arm: rn.Arm, season: int) -> float:
    """The screen's world: a wider pool and a higher daily cap are each worth more."""
    return pool(arm) / 15 + float(sc.value_of(arm, "daily_cap")) / 2


def screen_wobble(a: rn.Arm, b: rn.Arm) -> float:
    """The pool's difference is the surer (9 SE on two paths), the cap's the less sure (3)."""
    return 0.25 if pool(a) != pool(b) else 1.0


#: The world the screen ``s1`` and the tunes that read it are played in.
SCREENED = worth_world(screen_worth, screen_wobble)


@pytest.fixture(scope="module")
def screened(data: Path) -> dict:
    """The screen ``s1`` of the baseline on 2024: the daily cap, the pool and the look ahead, in
    a world where the pool's nudge is the surer and the daily cap's the less sure, against the
    list's own order (the cap is ahead of the pool there), and the look ahead does nothing."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(SCREENED))
        flags = ("--paths", "2", "--seasons", "2024", "--name", "s1")
        code, out = run_of("screen", data, "B", *flags, "--levers", "daily_cap", *LEVERS)
    assert code == 0, out
    got = reader.read_screen(data, "s1")
    assert got is not None and got["left"] == []
    return got


def test_the_order_is_the_screen_s_strongest_first(data: Path, screened):
    """The tune takes the screen's survivors strongest first, whatever the list's order: the
    pool, the surer, ahead of the daily cap, which the list puts first. Each lever is searched
    from the arm the one before left."""
    assert sc.NAMES.index("daily_cap") < sc.NAMES.index("pool")
    before = looks(data)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(SCREENED))
        code, out = tune(data, levers=None, screen="s1", name="by-screen", confirm="none")
        assert code == 0, out
        # Levers named beside the screen take its order, survivors or not; and what the screen
        # was played under that this tune is not is said, not refused.
        named = ("weeks_ahead", "daily_cap", "pool")
        flags = {"levers": named, "screen": "s1", "name": "named", "seasons": "2023"}
        code, plan = tune(data, "--dry-run", confirm="none", **flags)
        assert code == 0, plan
        assert (
            "order, fixed before any pair: pool (pool-45, 9.00 SE), daily_cap (daily_cap-minus, "
            "3.00 SE), weeks_ahead (weeks_ahead-6, 0.00 SE)"
        ) in plan
        assert (
            "note: the screen s1 was played under another seasons ([2024] there, [2023] here): "
            "its survivors and their order are taken as they stand"
        ) in plan
    rec = record(data, "by-screen")
    assert [(o["lever"], o["from"], o["place"]) for o in rec["order"]] == [
        ("pool", "pool-45", tn.BY_SCREEN),
        ("daily_cap", "daily_cap-minus", tn.BY_SCREEN),
    ]
    assert [o["strength"] for o in rec["order"]] == pytest.approx([9.0, 3.0])
    assert (
        "order, fixed before any pair: pool (pool-45, 9.00 SE), daily_cap (daily_cap-minus, "
        "3.00 SE)"
    ) in out
    spec = rec["spec"]
    assert spec["levers"] == ["pool", "daily_cap"] and spec["tune_version"] == 2
    assert spec["screen"] == {"name": "s1", "spec_sha": ss.spec_hash(screened["spec"])}
    assert (spec["passes"], spec["confirm"], spec["arm"]) == (1, None, BASE)
    assert {k: v for k, v in spec.items() if k in screened["spec"] and k != "levers"} == {
        k: v for k, v in screened["spec"].items() if k != "levers"
    }
    # The same code, fit and world as the screen's: nothing to say of it.
    assert rec["screen"] == {"name": "s1", "differs": {}, "note": ss.SCREEN_DIFFERS_NOTE}
    assert "note: the screen s1" not in out
    wider, cap = rec["steps"]
    assert (wider["lever"], wider["from"], wider["change"]) == ("pool", 30, {"pool": 60})
    assert pair_of(data, "by-screen", "p1-pool-45")["specs"]["a"] == BASE
    # The cap is searched from the arm the pool's step left.
    assert (cap["lever"], cap["from"], cap["change"]) == ("daily_cap", 2, {"daily_cap": 3})
    assert {v["key"]: v["status"] for v in cap["values"]} == {
        "daily_cap-minus": sc.PLAYED,
        "daily_cap-minus-again": sc.NOT_PLAYED,
        "daily_cap-plus": sc.PLAYED,
        "daily_cap-plus-again": sc.NOT_PLAYED,
    }
    assert cap["choice"]["standings"] == {"daily_cap-minus": tn.WORSE, "daily_cap-plus": tn.TAKEN}
    assert pair_of(data, "by-screen", "p1-daily_cap-plus")["specs"]["a"] == {**BASE, "pool": 60}
    assert rec["final"]["set"] == {"daily_cap": 3, "pool": 60}
    # No confirmation: marked, no verdict, no look.
    assert rec["confirmation"] == {"season": None, "status": tn.NO_CONFIRMATION, "look": None}
    assert f"the confirmation: {tn.NO_CONFIRMATION}" in out and "verdict (advisory)" not in out
    assert "the search's set is no recommendation by itself" in out
    assert looks(data) == before and "confirm-run.json" not in files(data, "by-screen")


def test_a_screen_that_is_not_this_tune_s_is_refused_by_name(data: Path, screened, monkeypatch):
    """The screen named must be finished, this baseline arm's and this league kind's, must have
    a survivor, and must not have played the season the tune confirms on: the levers and their
    order would then be chosen on the season called withheld."""

    def never(*a, **k):
        raise AssertionError("a path was played")

    monkeypatch.setattr(ss, "task_paired", never)
    reader.write_screen(data, "s-left", {**screened, "name": "s-left", "left": ["pool-45"]})
    idle = copy.deepcopy(screened)
    for row in idle["rows"]:
        if row.get("result"):
            row["result"]["survives"] = False
    reader.write_screen(data, "s-idle", {**idle, "name": "s-idle"})
    before = folders(data)
    for kw, flags, why in (
        ({"screen": "nope"}, (), "refused: --screen nope: no screen of that name has a record"),
        (
            {"screen": "s-left"},
            (),
            (
                "refused: --screen s-left: it has pairs left to play (pool-45), so its survivors "
                "are not all known: finish the screen first"
            ),
        ),
        (
            {"screen": "s1", "arm": "W"},
            (),
            "refused: --screen s1: it screened another baseline arm than --arm",
        ),
        (
            {"screen": "s1"},
            ("--h2h", "each_category"),
            (
                "refused: --screen s1: it was played in another league kind (h2h: the screen's "
                "'one_win', this tune's 'each_category')"
            ),
        ),
        ({"screen": "s-idle"}, (), "refused: the screen 's-idle' has no survivor"),
        (
            {"screen": "s1", "seasons": "2023", "confirm": "2024"},
            (),
            (
                "refused: --screen s1: it was played on season 2024, the season this tune "
                "confirms on (--confirm): its survivors and their order were chosen there, so "
                "the season would not be withheld from what chose the levers"
            ),
        ),
    ):
        code, out = tune(data, *flags, **{"levers": None, "name": "refused", **kw})
        assert code == 2 and why in out, out
    assert folders(data) == before


# --------------------------------------------------------------------------- the sign rule
def test_a_lever_that_helps_in_one_season_and_hurts_in_another_is_left_and_named(data: Path):
    """A wider pool is worth three wins in one made-up season and costs one in the other: the
    mean over the two is well above its SE, and the value does not count. The lever stays, the
    output says it depends on the season, and the confirmation season is never read. With no
    season named the search plays every season on file but the hold-out and the confirmation
    season; the first on file has no prior season, so its cell is skipped."""

    def worth(arm: rn.Arm, season: int) -> float:
        return pool(arm) / 15 * (3.0 if season == 2023 else -1.0)

    log: list = []
    before, mark = looks(data), len(READS)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth), log))
        code, out = tune(data, levers=("pool",), name="flips", seasons=None)
    assert code == 0, out
    assert set(READS[mark:]) == {2022, 2023, 2024}
    rec = record(data, "flips")
    assert rec["spec"]["world"]["seasons"] == [2022, 2023, 2024]
    assert "the search's cells: season(s) 2022, 2023, 2024 by prior, 2 paths a cell" in out
    assert {t for t, _ in log} == {2023, 2024}
    (step,) = rec["steps"]
    once, twice = (v["result"] for v in step["values"])
    assert set(once["by_cell"]) == {"2023 prior", "2024 prior"}
    assert once["by_cell"]["2023 prior"] > 0 > once["by_cell"]["2024 prior"]
    assert once["signs"] == twice["signs"] == tn.FLIPS
    assert once["mean"] > 3 * once["se"] > 0 and not once["clears"] and not twice["clears"]
    assert step["choice"] == {
        "key": None,
        "passed": [],
        "standings": {"pool-45": tn.DEPENDS_SEASON, "pool-45-again": tn.DEPENDS_SEASON},
        "depends": ["pool-45", "pool-45-again"],
    }
    assert step["change"] is None
    assert (
        "pass 1: pool stays at 30: no value counts and clears one SE (pool-45: depends on the "
        "season; pool-45-again: depends on the season)"
    ) in out
    assert rec["final"]["set"] == {} and rec["final"]["arm"] == BASE
    assert rec["confirmation"] == {"season": 2026, "status": tn.NOTHING_TO_CONFIRM, "look": None}
    assert f"the confirmation: {tn.NOTHING_TO_CONFIRM}" in out and looks(data) == before
    assert files(data, "flips") == {"tune.json", "p1-pool-45.json", "p1-pool-45-again.json"}


def test_a_later_pass_tries_a_lever_again_and_a_pass_that_moves_nothing_ends_the_search(data):
    """The worth of the pool tops out at 60. Pass 1 moves it there; pass 2 tries it from there
    (back to 45, and back again to 30), finds nothing better and ends the search: the third
    pass named is not played."""

    def worth(arm: rn.Arm, season: int) -> float:
        return min(pool(arm), 60.0) / 15

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth)))
        code, out = tune(data, "--passes", "3", levers=("pool",), name="passes", confirm="none")
    assert code == 0, out
    rec = record(data, "passes")
    first, second = rec["steps"]
    assert (first["pass"], first["from"], first["change"]) == (1, 30, {"pool": 60})
    assert (second["pass"], second["from"], second["change"]) == (2, 60, None)
    assert {v["key"]: v["values"]["b"] for v in second["values"]} == {
        "pool-45": 45,
        "pool-45-again": 30,
    }
    assert set(second["choice"]["standings"].values()) == {tn.WORSE}
    assert pair_of(data, "passes", "p2-pool-45")["specs"]["a"] == {**BASE, "pool": 60}
    assert not any(f.startswith("p3-") for f in files(data, "passes"))
    assert rec["final"]["set"] == {"pool": 60} and rec["spec"]["passes"] == 3


def test_a_noisy_larger_mean_is_passed_over_and_the_run_says_so(data: Path):
    """The pool's nudge again swings between the two paths around a larger mean, and its nudge
    is a sure gain: the step takes the sure one and names the other as passed over."""

    def world(a: rn.Arm, b: rn.Arm, season: int, path: int):
        if pool(b) == 60:
            return (9.0, -5.0)[path]
        return (1.0, 2.0)[path]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(world))
        code, out = tune(data, levers=("pool",), name="noisy", confirm="none")
    assert code == 0, out
    (step,) = record(data, "noisy")["steps"]
    sure, noisy = (v["result"] for v in step["values"])
    assert noisy["mean"] > sure["mean"] > sure["se"] and noisy["mean"] < noisy["se"]
    assert step["choice"] == {
        "key": "pool-45",
        "passed": ["pool-45-again"],
        "standings": {"pool-45": tn.TAKEN, "pool-45-again": tn.PASSED},
        "depends": [],
    }
    assert step["change"] == {"pool": 45}
    assert "passed over, a larger mean that is not above one SE: pool-45-again (" in out
    assert f"pass 1: {step['why']}" in out


def test_a_lever_at_its_nudge_s_target_is_listed_as_the_current_value_and_not_refused(data):
    """The pool is worth most at 45, the list's own target. Pass 1 takes it. In pass 2 the row
    "to 45" is the current value: a screen would refuse that pair by name, and a tune lists it,
    plays nothing of it and goes on. And a baseline that already holds the target is a tune's
    baseline all the same."""

    def worth(arm: rn.Arm, season: int) -> float:
        return {30.0: 0.0, 45.0: 2.0, 60.0: 1.0}[pool(arm)]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth)))
        code, out = tune(data, "--passes", "2", levers=("pool",), name="target", confirm="none")
        assert code == 0, out
        rec = record(data, "target")
        first, second = rec["steps"]
        assert first["choice"]["key"] == "pool-45" and first["change"] == {"pool": 45}
        assert first["choice"]["standings"] == {"pool-45": tn.TAKEN, "pool-45-again": tn.BEATEN}
        assert (second["pass"], second["from"], second["change"]) == (2, 45, None)
        (value,) = second["values"]
        assert (value["key"], value["status"], value["why"]) == (
            "pool-45",
            sc.NOT_PLAYED,
            tn.CURRENT,
        )
        assert (
            "pass 2: pool stays at 45: no value to play (pool-45: not played (the current value))"
        ) in out
        assert "refused" not in out and rec["final"]["set"] == {"pool": 45}
        assert files(data, "target") == {"tune.json", "p1-pool-45.json", "p1-pool-45-again.json"}
        # From a baseline at the target: the plan lists the row, and the other lever is played.
        code, out = tune(data, "--dry-run", name="at-target", arm="W", confirm="none")
    assert code == 0 and "refused" not in out, out
    assert "not played: the current value" in out
    assert "the whole tune: about 2 pair(s) of the search, as the baseline lists them" in out


# --------------------------------------------------------------------------- what the final arm reads
def test_a_value_found_on_the_exact_tier_is_confirmed_on_the_exact_tier(data: Path):
    """``execute_plan`` is the exact tier's: its pair is played on that tier in both arms, the
    current arm takes the lever's value and keeps its own tier, and the final set is confirmed
    on the cheapest tier that reads everything that moved, in both arms."""

    def worth(arm: rn.Arm, season: int) -> float:
        return float(arm.execute_plan)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth)))
        code, out = tune(data, levers=("execute_plan", "pool"), name="exact")
    assert code == 0, out
    rec = record(data, "exact")
    wider, flipped = rec["steps"]
    assert (wider["lever"], wider["change"]) == ("pool", None)
    (value,) = flipped["values"]
    assert (value["key"], value["tier"], value["both"]) == (
        "execute_plan-flipped",
        "exact",
        {"tier": "exact"},
    )
    assert flipped["change"] == {"execute_plan": True}
    pair = pair_of(data, "exact", "p1-execute_plan-flipped")
    # Since PR E the row writes the plan drawn in both arms. Here that is the arm's default
    # written out, so it is no change from the baseline and ``both`` above does not name it.
    assert pair["specs"]["a"] == {**BASE, "tier": "exact", "with_plan": True}
    final = rec["final"]
    assert final["arm"] == {**BASE, "execute_plan": True} and final["set"] == {"execute_plan": True}
    assert (final["tier"], final["unread"]) == ("exact", {})
    conf = rec["confirmation"]
    assert (conf["status"], conf["tier"]) == (tn.CONFIRMED, "exact")
    assert conf["arms"]["run"] == {
        "a": {**BASE, "tier": "exact"},
        "b": {**BASE, "tier": "exact", "execute_plan": True, "name": "B:tuned"},
    }
    assert pair_of(data, "exact", "confirm-run")["tune"]["tier"] == "exact"


def test_the_season_scale_is_measured_once_and_a_final_arm_that_reads_nothing_is_not_confirmed(
    data: Path, monkeypatch
):
    """Two levers that wait on the season scale. The scale is the baseline's, measured once
    before the first pair, kept in the record and read from it when the tune is run again. The
    weight of the playoff weeks is found with the season term switched on in both arms, and the
    current arm takes the weight alone: the final arm, whose season term is off, does not read
    it, so it is the baseline's seat. That is said, nothing is confirmed, and the confirmation
    season is neither read nor counted."""
    measured: list[int] = []
    true_scale = ss.task_scale

    def spy(*args, **kwargs):
        measured.append(args[PATH])
        return true_scale(*args, **kwargs)

    def worth(arm: rn.Arm, season: int) -> float:
        return float(arm.knobs["playoff_weight"])

    monkeypatch.setattr(ss, "task_scale", spy)
    monkeypatch.setattr(ss, "task_paired", made_up(worth_world(worth)))
    levers = ("playoff_weight", "season_weight")
    before, mark = looks(data), len(READS)
    code, out = tune(data, levers=levers, name="scaled")
    assert code == 0, out
    assert measured == [0, 1]
    assert "season scale: measured on 2 of 2 paths of the first cell (2024 prior)" in out
    rec = record(data, "scaled")
    scale = rec["scale"]
    assert scale["ratio"] > 0 and (scale["paths"], scale["of"]) == (2, 2)
    term, weight = rec["steps"]
    # The season term's nudges are shares of the scale; a quarter again is the half, played once.
    values = {v["key"]: v for v in term["values"]}
    assert list(values) == [
        "season_weight-quarter",
        "season_weight-quarter-again",
        "season_weight-half",
        "season_weight-half-again",
    ]
    quarter, half = (float(f"{scale['ratio'] / n:.4g}") for n in (4, 2))
    assert values["season_weight-quarter"]["values"] == {"a": 0.0, "b": quarter}
    assert values["season_weight-half"]["values"] == {"a": 0.0, "b": half}
    assert values["season_weight-quarter-again"]["why"] == "the same value as season_weight-half"
    assert values["season_weight-half-again"]["values"]["b"] == pytest.approx(2 * half, rel=1e-3)
    assert term["change"] is None
    # The playoff weeks' weight: both arms hold a season term, and only the weight is carried.
    assert weight["change"] == {"playoff_weight": 2.0}
    assert all(v["both"] == {"season_weight": quarter} for v in weight["values"])
    pair = pair_of(data, "scaled", "p1-playoff_weight-1.5-again")
    assert pair["specs"]["a"]["knobs"]["season_weight"] == quarter
    final = rec["final"]
    assert final["set"] == {"playoff_weight": 2.0} and final["levers"] == ["playoff_weight"]
    assert final["arm"]["knobs"]["season_weight"] == 0.0 and list(final["unread"]) == [
        "playoff_weight"
    ]
    assert f"not read by the final arm on the surrogate tier: playoff_weight ({final['unread']['playoff_weight']})" in out  # fmt: skip
    assert rec["confirmation"] == {"season": 2026, "status": tn.SAME_SEAT, "look": None}
    assert f"the confirmation: {tn.SAME_SEAT}" in out
    assert looks(data) == before and 2026 not in READS[mark:]
    # Again: nothing to play, and the scale on file is the one used.
    code, out = tune(data, levers=levers, name="scaled")
    assert code == 0 and measured == [0, 1], out
    assert "season scale: measured" not in out and record(data, "scaled")["scale"] == scale
    assert (
        f"season scale: {scale['ratio']:.4g}, on 2 of 2 paths of the first cell, as the tune "
        "measured it when it was started"
    ) in out


def test_a_final_set_confirmed_on_another_withheld_season_counts_no_look(data: Path):
    """``--confirm`` names another season the search withheld: the final pair is played on it
    and the verdict is stated, the record says it is not the confirmation season, and the
    ledger, whose numbers are looks at that season, gains no line."""
    before = looks(data)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER))
        code, out = tune(data, levers=("pool",), name="other-season", confirm="2023")
    assert code == 0, out
    conf = record(data, "other-season")["confirmation"]
    assert (conf["season"], conf["status"], conf["look"]) == (2023, tn.CONFIRMED, None)
    assert conf["look_note"] == ss.TUNE_OTHER_SEASON.format(season=2026)
    assert conf["verdict"]["state"] == tn.HOLDS
    pair = pair_of(data, "other-season", "confirm-run")
    assert pair["seasons"] == [2023] and pair["confirmation"] is None
    assert f"season 2023: {conf['look_note']}" in out and "look 1" not in out
    assert f"verdict (advisory): {tn.VERDICT_WORDS[tn.HOLDS]}" in out
    assert looks(data) == before


# --------------------------------------------------------------------------- Rule 1
def same_by_replay(data: Path, name: str, key: str, season: int, flags: tuple[str, ...]) -> dict:
    """The tune ``name``'s pair ``key``, held equal to the same pair run by ``replay --arms`` on
    the pair's own two specs under the same flags: key for key, apart from the run's name and
    times and the tune's own block (and, on the confirmation season, which look each is)."""
    mine = pair_of(data, name, key)
    specs = []
    for side in ss.PAIR:
        specs.append(data / f"{name}-{key}-{side}.json")
        specs[-1].write_text(json.dumps(mine["specs"][side]))
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", str(season)]
    argv += ["--workers", "1", "--seed", "5", "--paths", "2", *flags, "--arms", *map(str, specs)]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert ss.main(argv) == 0, buf.getvalue()
    (line,) = [x for x in buf.getvalue().splitlines() if x.startswith("written: ")]
    theirs = json.loads(Path(line.removeprefix("written: ")).read_text())
    assert set(mine) - set(theirs) == {"tune"} and set(theirs) <= set(mine)
    apart = (*RUN_KEYS, "confirmation") if season == ss.CONFIRMATION else RUN_KEYS
    assert {k: v for k, v in mine.items() if k not in apart} == {
        k: v for k, v in theirs.items() if k not in apart
    }
    if season == ss.CONFIRMATION:
        assert theirs["confirmation"]["look"] == mine["confirmation"]["look"] + 1
        assert theirs["confirmation"]["ledger"] == mine["confirmation"]["ledger"]
    return mine


def test_rule_1_a_tune_s_pair_is_the_same_pair_run_by_replay(data: Path):
    """The true task, under waivers by priority: a value's pair in a tune, written out as two
    spec files and run by ``replay --arms`` under the same flags, gives the tune's record key
    for key. The seat moves, and the lever moves the count it is there to move. One format is
    named, the default (one win a matchup): what is held is that the two commands run one code
    on one pair, which no format changes; what a format changes is the measure, and its own test
    plays both formats and a points league."""
    flags = ("--waivers", "priority")
    code, out = tune(data, *flags, levers=("surrogate_days",), name="rule1", confirm="none")
    assert code == 0, out
    mine = same_by_replay(data, "rule1", "p1-surrogate_days-monday", 2024, flags)
    assert mine["league"]["rules"]["waivers"] == "priority" and mine["audit"]["paths_voided"] == 0
    counts = mine["counts"]["by_season"]["2024"]["prior"]
    assert counts["a"]["landed"]["mean"] > 0 and counts["a"]["landed"] != counts["b"]["landed"]
    (step,) = record(data, "rule1")["steps"]
    (value,) = step["values"]
    assert not value["result"]["did_nothing"] and not value["result"]["counts_equal"]
    assert value["result"]["cells"]["2024"]["prior"]["counts"]["a"] == counts["a"]


def test_rule_1_the_confirmation_s_pair_is_the_same_pair_run_by_replay(data: Path):
    """The search in the made-up world, so that there is a final set, and the confirmation
    season played by the true task: the confirmation's pair is the pair ``replay --arms`` plays
    on the final arm and the baseline, and a replay of the season after it is the next look.
    One format is named, the default, for the reason the test above gives."""

    def world(a: rn.Arm, b: rn.Arm, season: int, path: int):
        return REALLY if season == 2026 else WIDER(a, b, season, path)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(world))
        code, out = tune(data, levers=("pool",), name="rule1c")
    assert code == 0, out
    rec = record(data, "rule1c")
    assert rec["final"]["set"] == {"pool": 60} and rec["confirmation"]["status"] == tn.CONFIRMED
    mine = same_by_replay(data, "rule1c", "confirm-run", 2026, ())
    assert mine["audit"]["paths_voided"] == 0
    cell = rec["confirmation"]["cells"]["run"]["prior"]
    assert cell["difference"] == mine["results"]["2026"]["prior"]["difference"]
    assert cell["finish"] == tn.finish_of(cell["difference"])
    assert rec["confirmation"]["verdict"]["state"] in (tn.HOLDS, tn.NOT_SHOWN, tn.AGAINST)


# --------------------------------------------------------------------------- pieces
def test_a_tune_played_in_pieces_records_what_one_played_unbroken_does(data, whole, monkeypatch):
    """Stopped by ``--max-minutes`` before a pair it has no room for and taken up by the same
    command: no lever is timed again, no pair is played twice, and the record is the unbroken
    tune's apart from its name, its times and which look it is."""
    timed: list[float] = []

    def clocked(task, *args):
        timed.append(300.0 if timed else 0.0)
        return timed[-1], task(*args)

    log: list = []
    monkeypatch.setattr(ss, "timed_task", clocked)
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER, log))
    before = looks(data)
    code, out = tune(data, "--max-minutes", "5", name="pieces")
    assert code == 0, out
    assert "stopped: --max-minutes 5: the pair of p1-weeks_ahead-6, about 10.0 min" in out
    assert "left for the next piece, from p1-weeks_ahead-6 on; the same command plays it" in out
    first = record(data, "pieces")
    assert first["left"]["next"] == "p1-weeks_ahead-6" and first["final"] is None
    assert first["confirmation"] is None and [s["lever"] for s in first["steps"]] == ["pool"]
    assert first["timing"]["estimates"] == {
        "pool": {"seconds_one": 0.0, "tasks": 2},
        "weeks_ahead": {"seconds_one": 300.0, "tasks": 2},
    }
    (piece,) = first["timing"]["pieces"]
    assert piece["played"] == ["p1-pool-45", "p1-pool-45-again"] and piece["finished_at"]
    assert piece["stopped"].startswith("--max-minutes 5: the pair of p1-weeks_ahead-6")
    assert looks(data) == before and "verdict (advisory)" not in out
    # The second piece.
    del log[:]
    code, out = tune(data, name="pieces")
    assert code == 0, out
    assert timed == [0.0, 300.0] and "timed in" not in out and "stopped:" not in out
    assert [b for _, b in log] == (
        ["B:weeks_ahead-6"] * 2 + ["B:weeks_ahead-6-again"] * 2 + ["B:tuned"] * 2
    )
    assert out.count("played before") == 2
    again = record(data, "pieces")
    apart = ("name", "timing", "confirmation")
    assert {k: v for k, v in again.items() if k not in apart} == {
        k: v for k, v in whole[0].items() if k not in apart
    }
    assert {k: v for k, v in again["confirmation"].items() if k != "look"} == {
        k: v for k, v in whole[0]["confirmation"].items() if k != "look"
    }
    assert again["confirmation"]["look"]["line"] == len(before) + 1
    assert [p["played"] for p in again["timing"]["pieces"]] == [
        ["p1-pool-45", "p1-pool-45-again"],
        ["p1-weeks_ahead-6", "p1-weeks_ahead-6-again", "confirm-run"],
    ]
    assert files(data, "pieces") == files(data, "whole")


def test_a_tune_is_resumed_only_on_the_spec_it_was_started_with(data: Path, whole, monkeypatch):
    def never(*a, **k):
        raise AssertionError("a path was played")

    monkeypatch.setattr(ss, "task_paired", never)
    for flags, kw, why in (
        (("--seed", "6"), {}, "seed: started with 5, now 6"),
        (("--waivers", "priority"), {}, "waivers: started with 'none', now 'priority'"),
        ((), {"arm": "W"}, "the baseline arm's spec"),
        ((), {"levers": ("pool",)}, "levers: started with ['pool', 'weeks_ahead'], now ['pool']"),
        (("--passes", "2"), {}, "passes: started with 1, now 2"),
        ((), {"confirm": "none"}, "confirm: started with 2026, now None"),
        ((), {"seasons": "2023"}, "seasons: started with [2024], now [2023]"),
    ):
        code, out = tune(data, *flags, **{"name": "whole", **kw})
        assert code == 2, out
        assert f"refused: the tune 'whole' was started with another spec ({why}" in out
        assert "name this one another (--name)" in out and "its plan" not in out
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(tn, "TUNE_VERSION", tn.TUNE_VERSION + 1)
        code, out = tune(data, name="whole")
    assert code == 2 and "tune_version: started with 2, now 3" in out, out
    assert record(data, "whole") == whole[0]
    # A pair's file holding other arms than this tune's value refuses the run by name.
    file = reader.tune_pair_path(data, "whole", "p1-pool-45")
    kept = file.read_text()
    other = json.loads(kept)
    other["specs"]["b"]["pool"] = 50
    file.write_text(json.dumps(other))
    code, out = tune(data, name="whole")
    file.write_text(kept)
    assert code == 2, out
    assert "refused: the tune 'whole' holds a pair p1-pool-45 of other arms" in out


# --------------------------------------------------------------------------- the refusals
def test_a_tune_refuses_by_name_before_any_path(data: Path, monkeypatch):
    """The hold-out is refused wherever it is named, in the search and in the confirmation; the
    confirmation season is refused in the search; the season confirmed on is withheld from the
    search. Nothing is read of a season, written or counted."""

    def never(*a, **k):
        raise AssertionError("a season was read or a path played")

    monkeypatch.setattr(ss, "task_paired", never)
    monkeypatch.setattr(ss, "remembering", never)
    before, counted = folders(data), looks(data)
    for kw, flags, why in (
        ({"seasons": "2025"}, (), "refused: 2025 is the hold-out; no run plays it"),
        ({"seasons": "2024,2025"}, (), "refused: 2025 is the hold-out; no run plays it"),
        ({"seasons": "2023-2026"}, (), "refused: 2025 is the hold-out; no run plays it"),
        (
            {"confirm": "2025"},
            (),
            "refused: --confirm 2025: 2025 is the hold-out; no run plays it",
        ),
        (
            {"seasons": "2026"},
            (),
            (
                "refused: 2026 is the confirmation season; a tune's search never plays it: it "
                "is read once, at the end (--confirm)"
            ),
        ),
        ({"seasons": "2024,2026"}, (), "refused: 2026 is the confirmation season; a tune's"),
        (
            {"seasons": "2023,2024", "confirm": "2023"},
            (),
            (
                "refused: --confirm 2023 is one of the search's seasons (--seasons): the season "
                "a tune confirms on is withheld from its search"
            ),
        ),
        ({"confirm": "2021"}, (), "refused: --confirm 2021: season 2021 has no log on file"),
        ({"confirm": "soon"}, (), "refused: --confirm 'soon': an ESPN season id, or none"),
        (
            {"levers": ("pool", "pol")},
            (),
            "refused: lever 'pol' is not in the screen's list: one of",
        ),
        ({"levers": None}, (), "refused: a tune names its levers: --screen NAME"),
        ({}, ("--passes", "0"), "refused: --passes is a count of passes over the levers"),
        ({}, ("--max-minutes", "0"), "refused: --max-minutes is a span in minutes, above 0"),
        ({"arm": "bad"}, (), "refused: --arm: spec key 'pol' is not one the simulator reads"),
        ({"arm": "nope"}, (), "refused: --arm: "),
    ):
        code, out = tune(data, *flags, **{"name": "refused", **kw})
        assert code == 2 and why in out, out
        assert "its plan" not in out and "written" not in out
    assert folders(data) == before and looks(data) == counted


def test_a_dry_run_prints_the_plan_and_the_estimate_and_writes_nothing(data: Path, monkeypatch):
    """The plan: the order, each lever's values with each pair's estimate, the confirmation and
    the whole tune's total. Nothing is written, the ledger included, and no pair of the
    confirmation season is planned: the season is not read."""
    log: list = []
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER, log))
    held: list = []
    audited = ss.audited

    def spy(keys, results, rules=None):
        held.append(rules)
        return audited(keys, results, rules)

    monkeypatch.setattr(ss, "audited", spy)
    before, counted, mark = folders(data), looks(data), len(READS)
    code, out = tune(data, "--dry-run", levers=(*LEVERS, "system"), name="dry", arm="R")
    assert code == 0, out
    assert set(READS[mark:]) == {2024}
    # Each timed task is audited under the rules the run's pairs are held to, as a screen's is:
    # the league's bracket has a round, so PR bracket's rule is among them (``cli.audit_rules``).
    assert len(held) == 2 and all(audit.BRACKET_PAIRS in rules for rules in held)
    assert "one task of each of 2 lever(s) timed in" in out
    assert "the tune dry, its plan: 1 pass(es) over 3 lever(s) in this order" in out
    assert "the search's cells: season(s) 2024 by prior, 2 paths a cell; never the hold-out" in out
    assert out.count("a pair of 2 tasks, one of the lever's took") == 4
    assert out.count("not read here: ") == 1
    assert (
        "the confirmation: the final set against the baseline on 2026, once, against the run's "
        "rivals and against static rivals: up to 2 pair(s) of 2 tasks, about"
    ) in out
    assert "both arms on the cheapest tier that reads every value that moved" in out
    assert (
        "the whole tune: about 4 pair(s) of the search, as the baseline lists them, and the "
        "confirmation, about"
    ) in out
    assert "the search may play pairs this plan does not list" in out
    assert out.rstrip().endswith("dry run, nothing written") and "written:" not in out
    assert folders(data) == before and looks(data) == counted
    assert {t for t, _ in log} == {2024} and len(log) == 2


# --------------------------------------------------------------------------- the guard
def test_the_time_guard_reads_the_whole_tune_s_estimate_the_confirmation_included(
    data: Path, monkeypatch
):
    """One pair of a little under an hour: with its confirmation the tune is over an hour, and
    is refused without ``--announced`` whatever a piece of it would take; with no confirmation
    it is under the hour. Announced, the routines' window is read against the piece."""
    monkeypatch.setattr(ss, "timed_task", lambda task, *args: (1700.0, task(*args)))
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    before, counted = folders(data), looks(data)
    levers = ("surrogate_days",)
    code, out = tune(data, levers=levers, name="guarded")
    assert code == 2, out
    assert (
        "the whole tune: about 1 pair(s) of the search, as the baseline lists them, and the "
        "confirmation, about 1.89 h"
    ) in out
    assert "refused: a tune of about 1.88889 h is announced on the tracker" in out
    assert "whatever a piece of it takes" in out
    code, out = tune(data, "--max-minutes", "10", levers=levers, name="guarded")
    assert code == 2 and "is announced on the tracker" in out, out
    assert folders(data) == before and looks(data) == counted
    # Announced: a piece that would run into the routines' window is refused, a capped one not.
    early = BUSINESS_HOURS.replace(hour=4, minute=0)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: early)
        code, out = tune(data, "--announced", levers=levers, name="guarded")
        assert code == 2 and "touches the routines' window" in out, out
        assert folders(data) == before
        code, out = tune(data, "--announced", "--max-minutes", "30", levers=levers, name="guarded")
    assert code == 0 and "stopped: --max-minutes 30: the pair of p1-surrogate_days-monday" in out
    assert record(data, "guarded")["left"]["next"] == "p1-surrogate_days-monday"
    # The estimate's override is the whole tune's too; and without the confirmation the same
    # search is under the hour.
    code, out = tune(data, "--expected-hours", "0.5", "--max-minutes", "10", levers=levers, name="guarded")  # fmt: skip
    assert code == 0 and "stopped: --max-minutes 10" in out, out
    code, out = tune(data, "--max-minutes", "10", levers=levers, name="short", confirm="none")
    assert code == 0 and "about 0.94 h" in out and "stopped: --max-minutes 10" in out, out
    assert looks(data) == counted


# --------------------------------------------------------------------------- the rivals
def test_the_final_set_is_played_against_the_run_s_rivals_and_against_static_ones(data: Path):
    """A baseline whose rivals move: the final pair is played twice on the confirmation season,
    for one look, counted before the season is played. In this made-up world the wider pool
    finishes ahead against rivals that move and level against rivals that stand still: the
    verdict rests on the run's rivals, both cells are in the record, and the edge against one
    kind only is flagged."""

    counted: list[int] = []

    def world(a: rn.Arm, b: rn.Arm, season: int, path: int):
        if season == 2026:
            counted.append(len(looks(data)))
        still = str(a.opponents.get("kind")) == "static"
        return 0.0 if season == 2026 and still else WIDER(a, b, season, path)

    log: list = []
    before = looks(data)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(world, log))
        code, out = tune(data, levers=("pool",), name="rivals", arm="R")
    assert code == 0, out
    # The look is on the ledger before the first path of the season is played: every task of
    # the season, of both pairs, finds this tune's line already there.
    assert counted == [len(before) + 1] * 4
    rec = record(data, "rivals")
    conf = rec["confirmation"]
    assert conf["files"] == {"run": "confirm-run.json", "static": "confirm-static.json"}
    assert {"confirm-run.json", "confirm-static.json"} <= files(data, "rivals")
    final = {**RIVALS, "name": "R:tuned", "pool": 60}
    still = {"opponents": {"kind": "static"}}
    assert conf["arms"] == {
        "run": {"a": RIVALS, "b": final},
        "static": {"a": {**RIVALS, **still}, "b": {**final, **still}},
    }
    assert pair_of(data, "rivals", "confirm-static")["specs"] == conf["arms"]["static"]
    assert conf["cells"]["run"]["prior"]["finish"] == tn.AHEAD
    assert conf["cells"]["static"]["prior"]["finish"] == tn.LEVEL
    verdict = conf["verdict"]
    assert verdict["state"] == tn.HOLDS
    assert verdict["by_forecaster"] == {"prior": {"run": tn.AHEAD, "static": tn.LEVEL}}
    assert verdict["flags"] == ["prior: ahead against the run's rivals only"]
    assert "flag: prior: ahead against the run's rivals only" in out
    rows = [x for x in out.splitlines() if x.startswith("  prior") and " rivals " in x]
    assert ["the run's rivals" in x for x in rows] == [True, False]
    assert ["static rivals" in x for x in rows] == [False, True]
    # Two pairs, one look; and the season is read after the search, by the final arm only.
    assert len(looks(data)) == len(before) + 1
    assert [b for t, b in log if t == 2026] == ["R:tuned"] * 4
    assert pair_of(data, "rivals", "confirm-static")["tune"]["look"] == conf["look"]


def test_a_voided_path_of_the_confirmation_is_no_verdict_and_keeps_the_exit_code(data: Path):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER, breach=(2026, 1)))
        code, out = tune(data, levers=("pool",), name="voided")
        assert code == ss.AUDIT_EXIT, out
        assert "AUDIT: 1 breach(es) voided 1 path(s)" in out
        verdict = record(data, "voided")["confirmation"]["verdict"]
        assert verdict["state"] is None and "the audit voided 1 path(s)" in verdict["why"]
        assert "of the ledger): no verdict: the audit voided 1 path(s)" in out
        assert "is recommended" not in out
        # A later run of the folder plays nothing and keeps the code.
        code, out = tune(data, levers=("pool",), name="voided")
    assert code == ss.AUDIT_EXIT and "no verdict: the audit voided 1 path(s)" in out, out


# --------------------------------------------------------------------------- a season it can play
def test_a_confirmation_the_world_cannot_play_is_refused_before_the_first_pair(data, monkeypatch):
    """Whether the season confirmed on can be played in the tune's world is asked before the
    first pair, and in the dry run, not after the search. Under a draft table the confirmation
    season has none (its log carries one figure for everyone, as on the box), and a season
    ``prior`` cannot serve leaves no forecaster: each is refused by name, with nothing played,
    written or counted, and no pair of the season planned."""

    def never(*a, **k):
        raise AssertionError("a path was played")

    monkeypatch.setattr(ss, "task_paired", never)
    before, counted, mark = folders(data), looks(data), len(READS)
    table = ("--adp", "espn", "--adp-spread", "1,0")
    for flags, kw, why in (
        (
            (*table, "--dry-run"),
            {},
            (
                "refused: --confirm 2026: --adp espn: season 2026 has no draft table: its log "
                "carries one and the same draft position for every player; a tune under a "
                "draft table confirms on a season that has one; nothing of the search is "
                "played for a confirmation that cannot be: name another season with --confirm, "
                "or --confirm none"
            ),
        ),
        (table, {}, "refused: --confirm 2026: --adp espn: season 2026 has no draft table"),
        (
            ("--dry-run",),
            {"confirm": "2022"},
            "refused: --confirm 2022: no forecaster named serves season 2022 (prior: ",
        ),
        ((), {"confirm": "2022"}, "refused: --confirm 2022: no forecaster named serves season"),
    ):
        code, out = tune(data, *flags, **{"levers": ("pool",), "name": "unplayable", **kw})
        assert code == 2 and why in out, out
        assert "its plan" not in out and "written" not in out
    assert folders(data) == before and looks(data) == counted
    assert set(READS[mark:]) == {2024}


def test_the_early_check_reads_what_the_season_holds_before_it_begins(data: Path):
    """The check itself (``cli.confirm_unfit``): a forecaster the search reads must serve the
    season confirmed on, since the verdict is stated for every forecaster the search read; one
    the search never read may be skipped there too; a stand-in must serve it; under a table the
    season needs one; and the ledger must read, when the season is the confirmation season."""
    both = fc.parse("prior,marcel")

    def plan(served, spread=None, sources=None):
        reads = [SimpleNamespace(served=tuple(served))]
        return SimpleNamespace(spread=spread, sources=sources, named=both, reads=reads)

    args = SimpleNamespace(data=data, adp="espn")
    # 2023 has one earlier season on file: marcel cannot serve it, and prior can.
    why = ss.confirm_unfit(args, 2023, plan(both))
    assert why is not None and why.startswith(
        "the search reads marcel, which cannot serve season 2023 ("
    )
    assert "the verdict is stated for every forecaster the search read" in why
    assert ss.confirm_unfit(args, 2023, plan(both[:1])) is None
    assert ss.confirm_unfit(args, 2024, plan(both)) is None
    standins = ss.sources_of("prior", "marcel")
    assert "a stand-in cannot serve season 2023: " in str(
        ss.confirm_unfit(args, 2023, plan(both[:1], sources=standins))
    )
    assert ss.confirm_unfit(args, 2024, plan(both[:1], sources=standins)) is None
    # Under a table: a season whose log has one passes, the confirmation season's has none.
    assert ss.confirm_unfit(args, 2024, plan(both[:1], spread=object())) is None
    assert "--adp espn: season 2026 has no draft table" in str(
        ss.confirm_unfit(args, 2026, plan(both[:1], spread=object()))
    )
    assert ss.confirm_unfit(args, 2026, plan(both[:1])) is None
    # A ledger that cannot be read is found now, not after the search.
    ledger = data / reader.LEDGER
    kept = ledger.read_text() if ledger.exists() else None
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text((kept or "") + "not a line\n")
    try:
        assert "the ledger its look is counted on cannot be read: " in str(
            ss.confirm_unfit(args, 2026, plan(both[:1]))
        )
        assert ss.confirm_unfit(args, 2024, plan(both[:1])) is None
    finally:
        if kept is None:
            ledger.unlink()
        else:
            ledger.write_text(kept)


def test_what_only_the_confirmation_s_plan_finds_is_recorded_with_the_final_set(
    data: Path, whole, monkeypatch
):
    """What the early check does not find (here it is switched off, and the season is one no
    forecaster serves) is met when the confirmation's pair is planned: the tune ends refused,
    and its record keeps the final set and says why the confirmation was not played. No path of
    the season is played and no look is counted."""
    monkeypatch.setattr(ss, "confirm_unfit", lambda *a, **k: None)
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    before, mark = looks(data), len(READS)
    for _ in range(2):
        code, out = tune(data, levers=("pool",), name="unplanned", confirm="2022")
        assert code == 2, out
        assert "refused: no cell is left: no forecaster named serves any season named" in out
        assert "refused: the confirmation's pair against the run's rivals cannot be planned" in out
        rec = record(data, "unplanned")
        assert rec["final"]["set"] == {"pool": 60} and rec["left"] is None
        conf = rec["confirmation"]
        assert (conf["season"], conf["status"], conf["look"]) == (2022, tn.UNPLANNED, None)
        assert conf["why"] == "no cell is left: no forecaster named serves any season named"
        assert f"the confirmation: {tn.UNPLANNED} ({conf['why']})" in out
        assert "the final set (what the search changed in the baseline): pool 60" in out
        assert "verdict (advisory" not in out and "recommended" not in out
    assert looks(data) == before and "confirm-run.json" not in files(data, "unplanned")
    assert all(p["finished_at"] for p in rec["timing"]["pieces"])
    # The plan that refused asked for the season; nothing of it was played or kept.
    assert READS[mark:].count(2022) == 2


def test_a_tune_under_a_draft_table_confirms_on_a_season_that_has_one(data: Path, monkeypatch):
    """The way out the refusal names, played: a tune under a draft table, confirmed on a season
    whose log has a table and that the search did not play. The league is drafted on the table
    in the search's pairs and in the confirmation's, the verdict is stated, and no look is
    counted. The made-up world's carried seasons are this test's own: a season drafted on a
    table is another record than one drafted on the forecaster."""
    monkeypatch.setitem(globals(), "CARRIED", {})
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    table = ("--adp", "espn", "--adp-spread", "1,0")
    before = looks(data)
    code, out = tune(data, *table, levers=("pool",), name="table", confirm="2023")
    assert code == 0 and "refused" not in out, out
    rec = record(data, "table")
    world = rec["spec"]["world"]
    assert (world["adp"], world["adp_spread"], rec["spec"]["confirm"]) == ("espn", "1,0", 2023)
    for key, season in (("p1-pool-45-again", "2024"), ("confirm-run", "2023")):
        drafted = pair_of(data, "table", key)["adp"]
        assert drafted["source"] == "espn" and set(drafted["seasons"]) == {season}
    assert rec["final"]["set"] == {"pool": 60}
    conf = rec["confirmation"]
    assert (conf["status"], conf["verdict"]["state"]) == (tn.CONFIRMED, tn.HOLDS)
    assert conf["look"] is None and looks(data) == before
    assert conf["look_note"] == ss.TUNE_OTHER_SEASON.format(season=2026)
    assert "the final set is recommended" in out


def test_a_forecaster_the_search_read_with_no_cell_on_the_season_is_no_verdict_in_a_run(
    data: Path, whole, monkeypatch
):
    """Two forecasters, searched on a season both serve: the sign rule reads both cells. The
    season confirmed on has one earlier season on file, so ``marcel`` has no cell there. The
    check before the first pair refuses such a tune by name. With the check switched off (the
    files changed under a tune in flight) the confirmation is played for ``prior`` alone:
    ``marcel`` is listed with replay's reason, and there is no verdict, however ``prior``
    finished. (``marcel``'s carried seasons are ``prior``'s: the made-up world sets the
    outcomes.)"""

    def never(*a, **k):
        raise AssertionError("a path was played")

    flags = ("--forecasters", "prior,marcel")
    before = looks(data)
    monkeypatch.setattr(ss, "task_paired", never)
    code, out = tune(data, *flags, levers=("pool",), name="two", confirm="2023")
    assert code == 2, out
    assert (
        "refused: --confirm 2023: the search reads marcel, which cannot serve season 2023 (" in out
    )
    assert "tunes/two" not in folders(data)
    for (label, path, rules), kept in list(CARRIED.items()):
        if label == "prior":
            monkeypatch.setitem(CARRIED, ("marcel", path, rules), {**kept, "forecaster": "marcel"})
    monkeypatch.setattr(ss, "confirm_unfit", lambda *a, **k: None)
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    code, out = tune(data, *flags, levers=("pool",), name="two", confirm="2023")
    assert code == 0, out
    rec = record(data, "two")
    (step,) = rec["steps"]
    for value in step["values"]:
        assert set(value["result"]["by_cell"]) == {"2024 prior", "2024 marcel"}
        assert value["result"]["signs"] == tn.ABOVE
    conf = rec["confirmation"]
    assert conf["status"] == tn.CONFIRMED and set(conf["cells"]["run"]) == {"prior"}
    (why,) = conf["skipped"].values()
    assert list(conf["skipped"]) == ["marcel"] and why
    verdict = conf["verdict"]
    assert (verdict["state"], verdict["read"], verdict["missing"]) == (
        None,
        ["prior"],
        {"marcel": why},
    )
    assert verdict["by_forecaster"] == {"prior": {"run": tn.AHEAD}}
    assert f"  marcel: no cell on the season confirmed on ({why})" in out
    assert (
        f"verdict (advisory): no verdict: the search read marcel ({why}), and the season "
        "confirmed on has no cell for it"
    ) in out
    assert "the final set is recommended" not in out and looks(data) == before


def test_a_forecaster_whose_cell_is_there_and_not_read_is_named_beside_the_word_in_a_run(
    data: Path, whole, monkeypatch
):
    """Two forecasters, searched on a season where the rule reads both. On the season confirmed
    on, the second one's cell is there and replay's own verdict leaves it out, as it does
    ``espn``'s on a season that fails its freeze check. The made-up logs carry no stored
    projection, so the test plants that check's flag where the real one is written (the pair's
    ``forecasters`` block), on ``marcel``. The verdict is stated on ``prior``; its line and the
    record's verdict block name ``marcel`` as not confirmed, with why, and "recommended" does
    not stand alone. (``marcel``'s carried seasons are ``prior``'s: the made-up world sets the
    outcomes.)"""
    block_of = ss.verdict_block

    def verdict_block(payload, named, seasons, sources, note):
        if [int(t) for t in seasons] == [2026]:
            payload["forecasters"]["2026"]["marcel"]["freeze"] = {"flagged": True}
        return block_of(payload, named, seasons, sources, note)

    for (label, path, rules), kept in list(CARRIED.items()):
        if label == "prior":
            monkeypatch.setitem(CARRIED, ("marcel", path, rules), {**kept, "forecaster": "marcel"})
    monkeypatch.setattr(ss, "verdict_block", verdict_block)
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    before = looks(data)
    code, out = tune(data, "--forecasters", "prior,marcel", levers=("pool",), name="frozen")
    assert code == 0, out
    rec = record(data, "frozen")
    (step,) = rec["steps"]
    for value in step["values"]:
        assert set(value["result"]["by_cell"]) == {"2024 prior", "2024 marcel"}
    conf = rec["confirmation"]
    run = conf["cells"]["run"]
    assert (conf["status"], conf["skipped"]) == (tn.CONFIRMED, {})
    assert (run["prior"]["read"], run["prior"]["mark"]) == (True, None)
    assert (run["marcel"]["read"], run["marcel"]["mark"]) == (False, rn.FREEZE)
    why = tn.UNREAD_WHY[rn.FREEZE]
    verdict = conf["verdict"]
    assert (verdict["state"], verdict["read"], verdict["missing"]) == (tn.HOLDS, ["prior"], {})
    assert verdict["unconfirmed"] == {"marcel": why}
    said = (
        f"{tn.VERDICT_WORDS[tn.HOLDS]}; confirmed on prior alone, not confirmed on marcel "
        f"({why}), which the search read"
    )
    assert verdict["words"] == said
    lines = out.splitlines()
    (line,) = [x for x in lines if x.startswith("verdict (advisory")]
    assert line.endswith(f"of the ledger): {said}")
    assert any(x.startswith("  marcel [not read]") for x in lines)
    # The look is counted all the same: the season was read.
    assert len(looks(data)) == len(before) + 1 and conf["look"]["line"] == len(before) + 1


# --------------------------------------------------------------------------- one seat, one kind
def test_mirror_rivals_the_static_pair_that_is_one_seat_is_not_planned(data: Path, whole):
    """A baseline whose rivals are its mirror. The search moves the weight of the horizons
    (found with ``executes weighted`` in both arms, which the current arm does not carry) and
    the surrogate's days, which the exact tier reads only through the mirror. Against the run's
    rivals the final arm is another seat; against static ones it is the baseline's, and replay
    would refuse that pair. So it is not planned: the look is not spent on a refusal, the
    confirmation is played against the run's rivals, the record says the static pair is one
    seat, and the edge is flagged as one kind's only."""

    def worth(arm: rn.Arm, season: int) -> float:
        return float(arm.knobs["horizon_weight"] != BASE["knobs"]["horizon_weight"]) + float(
            list(sc.value_of(arm, "surrogate_days")) == [0]
        )

    levers = ("horizon_weight", "surrogate_days")
    log: list = []
    before = looks(data)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth), log))
        code, out = tune(data, levers=levers, name="mirror", arm="M")
        assert code == 0, out
        rec = record(data, "mirror")
        final, conf = rec["final"], rec["confirmation"]
        assert final["set"] == {"horizon_weight": "even", "surrogate_days": [0]}
        assert (final["levers"], final["tier"]) == (list(levers), "exact")
        assert list(final["unread"]) == ["horizon_weight"]
        assert conf["status"] == tn.CONFIRMED and conf["files"] == {"run": "confirm-run.json"}
        assert set(conf["arms"]) == {"run", "static"} and set(conf["cells"]) == {"run"}
        (static,) = conf["one_seat"].items()
        assert static[0] == "static" and len(static[1]) == 2
        assert static[1][0].startswith("horizon_weight (")
        assert static[1][1].startswith("surrogate_days (")
        assert "confirm-static.json" not in files(data, "mirror")
        verdict = conf["verdict"]
        assert verdict["state"] == tn.HOLDS
        assert verdict["by_forecaster"] == {"prior": {"run": tn.AHEAD, "static": tn.ONE_SEAT}}
        assert verdict["flags"] == [
            (
                "prior: ahead against the run's rivals only (against static rivals the final "
                "arm is the baseline's seat)"
            )
        ]
        assert f"  against static rivals: not played, {tn.ONE_SEAT} (the two arms differ" in out
        assert f"flag: {verdict['flags'][0]}" in out and "refused" not in out
        # One look, for the one pair played; and the same command again plays nothing.
        assert len(looks(data)) == len(before) + 1
        assert [b for t, b in log if t == 2026] == ["M:tuned"] * 2
        del log[:]
        code, out = tune(data, levers=levers, name="mirror", arm="M")
    assert code == 0 and log == [] and len(looks(data)) == len(before) + 1, out
    assert record(data, "mirror") == rec


def test_an_exact_baseline_confirmed_on_the_surrogate_tier_says_so(data: Path, whole):
    """Both arms of the confirmation are put on the cheapest tier that reads what moved. When
    that is not the baseline's own tier, the output says which it is and which the baseline's."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER))
        code, out = tune(data, levers=("pool",), name="exact-base", arm="X", confirm="2023")
    assert code == 0, out
    arms = record(data, "exact-base")["confirmation"]["arms"]["run"]
    assert (arms["a"]["tier"], arms["b"]["tier"]) == ("surrogate", "surrogate")
    assert (
        "the confirmation, the final set against the baseline, both arms on the surrogate tier "
        "(the cheapest that reads every value that moved; the baseline's own is the exact "
        "tier): season 2023: "
    ) in out


# --------------------------------------------------------------------------- a search that grows
def test_a_later_pass_does_not_play_again_a_pair_of_the_same_two_arms(data: Path, whole):
    """Pass 1 moves the pool and leaves the look ahead. In pass 2 the pool is tried from its new
    value, and the look ahead's pairs are the very pairs of pass 1 (no step has changed its
    current arm since): their results are known, so they are taken and nothing is played."""

    def worth(arm: rn.Arm, season: int) -> float:
        return min(pool(arm), 60.0) / 15

    log: list = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth), log))
        code, out = tune(data, "--passes", "2", name="twice", confirm="none")
        assert code == 0, out
        rec = record(data, "twice")
        assert [(s["pass"], s["lever"]) for s in rec["steps"]] == [
            (1, "pool"),
            (1, "weeks_ahead"),
            (2, "pool"),
            (2, "weeks_ahead"),
        ]
        first, again = rec["steps"][1], rec["steps"][3]
        assert [v.get("same_as") for v in first["values"]] == [None, None]
        assert [v["same_as"] for v in again["values"]] == [
            "p1-weeks_ahead-6",
            "p1-weeks_ahead-6-again",
        ]
        assert [v["file"] for v in again["values"]] == [v["file"] for v in first["values"]]
        assert [v["result"] for v in again["values"]] == [v["result"] for v in first["values"]]
        assert again["choice"] == first["choice"] and again["change"] is None
        assert (
            "pass 2, weeks_ahead-6: the same two arms as p1-weeks_ahead-6 on the same paths, "
            "not played again: "
        ) in out
        # Each pair of the look ahead is played once (two paths), and pass 2 has no file of it.
        # The nudge has one task more: the plan's timed one, from the baseline.
        names = [b for _, b in log]
        assert names.count("B:weeks_ahead-6") == 3 and names.count("B:weeks_ahead-6-again") == 2
        assert not any(f.startswith("p2-weeks_ahead") for f in files(data, "twice"))
        assert {"p2-pool-45.json", "p2-pool-45-again.json"} <= files(data, "twice")
        # Taken up again, the folder gives the same record and plays nothing.
        del log[:]
        code, out = tune(data, "--passes", "2", name="twice", confirm="none")
    assert code == 0 and log == [] and record(data, "twice") == rec, out


def test_a_lever_first_read_after_another_moved_is_timed_then_and_the_hour_s_rule_read_again(
    data: Path, whole, monkeypatch
):
    """A baseline that executes a week plan it does not draw: ``execute_plan`` has no pair until
    ``with_plan`` has moved, so the plan lists one pair and times one lever. Its first pair is
    timed inside the search, and the hour's rule is read again before it: the tune has grown
    past the hour, so it stops refused, with the record written, until it is announced. The two
    rows are made up here (each switch flipped, nothing else set), so the case does not rest on
    which rows the list holds."""

    def switch(name: str) -> sc.Lever:
        def flip(arm: rn.Arm, ctx: sc.Context):
            return {}, (sc.Step("flipped", "flipped", {name: not getattr(arm, name)}),)

        return sc.Lever(name, "exact", "flipped", flip)

    monkeypatch.setattr(sc, "LEVERS", (switch("with_plan"), switch("execute_plan")))
    monkeypatch.setattr(sc, "NAMES", ("with_plan", "execute_plan"))
    timed: list[float] = []

    def clocked(task, *args):
        timed.append(4000.0 if timed else 0.0)
        return timed[-1], task(*args)

    def worth(arm: rn.Arm, season: int) -> float:
        return float(arm.with_plan) + 0.5 * float(not arm.execute_plan)

    log: list = []
    monkeypatch.setattr(ss, "timed_task", clocked)
    monkeypatch.setattr(ss, "task_paired", made_up(worth_world(worth), log))
    levers = ("with_plan", "execute_plan")
    code, out = tune(data, levers=levers, name="late", arm="P", confirm="none")
    assert code == 2, out
    assert "one task of each of 1 lever(s) timed in" in out
    assert "the whole tune: about 1 pair(s) of the search, as the baseline lists them" in out
    assert out.count("not read here: the arm draws no week plan") == 1
    assert (
        "pass 1, execute_plan-flipped: lever execute_plan has its first pair here, none from "
        "the baseline: one task timed, 4000.0s, about 2.22 h a pair"
    ) in out
    assert (
        "refused: with the pair of p1-execute_plan-flipped the tune comes to about 2.22222 h, "
        "more than its plan listed (about 0 h) and past the hour: a tune of over an hour is "
        "announced on the tracker and starts on the user's word"
    ) in out
    assert "left, from p1-execute_plan-flipped on; the same command with --announced" in out
    rec = record(data, "late")
    assert rec["left"]["next"] == "p1-execute_plan-flipped" and rec["final"] is None
    assert [s["lever"] for s in rec["steps"]] == ["with_plan"]
    assert rec["timing"]["estimates"] == {
        "with_plan": {"seconds_one": 0.0, "tasks": 2},
        "execute_plan": {"seconds_one": 4000.0, "tasks": 2},
    }
    (piece,) = rec["timing"]["pieces"]
    assert piece["played"] == ["p1-with_plan-flipped"] and piece["finished_at"]
    assert piece["stopped"].startswith("with the pair of p1-execute_plan-flipped")
    # The same command is refused again, with nothing timed or played; announced, it goes on.
    del log[:]
    code, out = tune(data, levers=levers, name="late", arm="P", confirm="none")
    assert code == 2 and log == [] and timed == [0.0, 4000.0], out
    assert "refused: with the pair of p1-execute_plan-flipped the tune comes to" in out
    code, out = tune(data, "--announced", levers=levers, name="late", arm="P", confirm="none")
    assert code == 0 and timed == [0.0, 4000.0], out
    assert [b for _, b in log] == ["P:execute_plan-flipped"] * 2
    rec = record(data, "late")
    assert [(s["lever"], s["change"]) for s in rec["steps"]] == [
        ("with_plan", {"with_plan": True}),
        ("execute_plan", {"execute_plan": False}),
    ]
    assert rec["final"]["set"] == {"with_plan": True, "execute_plan": False}
    # Nothing of the final set is called unread: since PR E the screen's reads have no clause
    # for a plan drawn and not executed (``with_plan`` is no lever of a season; here it is one
    # of this test's two made-up switches). What a final arm does not read is held by the
    # tests of the season scale and of the horizon's weight, above.
    assert rec["left"] is None and rec["final"]["unread"] == {}


def test_a_piece_stopped_at_the_confirmation_s_pair_has_not_opened_the_season(
    data: Path, whole, monkeypatch
):
    """Whether a piece may play the confirmation's pair (the hour's rule, the window, the cap in
    minutes) is settled before the season is read. A tune whose confirmation is still to play,
    taken up by a piece with no room for it, stops there having asked its reader for no season
    but the search's; the next piece reads it and plays it, on the look the tune already has."""
    monkeypatch.setattr(ss, "timed_task", lambda task, *args: (300.0, task(*args)))
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    code, out = tune(data, levers=("pool",), name="capped")
    assert code == 0, out
    rec = record(data, "capped")
    (reader.tune_dir(data, "capped") / "confirm-run.json").unlink()
    counted, mark = looks(data), len(READS)
    code, out = tune(data, "--max-minutes", "5", levers=("pool",), name="capped")
    assert code == 0, out
    assert "stopped: --max-minutes 5: the pair of confirm-run, about 10.0 min" in out
    stopped = record(data, "capped")
    assert stopped["left"]["next"] == "confirm-run"
    assert stopped["confirmation"]["status"] == tn.NOT_YET
    assert stopped["confirmation"]["look"] == rec["confirmation"]["look"]
    assert set(READS[mark:]) == {2024} and looks(data) == counted
    # The next piece reads the season, once, and adds no line.
    mark = len(READS)
    code, out = tune(data, levers=("pool",), name="capped")
    assert code == 0 and READS[mark:].count(2026) == 1 and looks(data) == counted, out
    assert record(data, "capped")["confirmation"] == rec["confirmation"]


# --------------------------------------------------------------------------- a folder, a ledger
def test_a_tune_whose_ledger_line_or_record_is_gone_says_so_and_does_not_fall_over(
    data: Path, whole
):
    """A finished tune run again after the ledger lost its line (the file removed, or the
    folder copied without it) says which look it was from its confirmation pair's own record,
    and adds no line. A folder with pairs and no record is refused by name: the record says
    when the tune was started, which is how its look is found again."""
    ledger = data / reader.LEDGER
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(WIDER))
        code, out = tune(data, levers=("pool",), name="gone")
        assert code == 0, out
        rec = record(data, "gone")
        look = rec["confirmation"]["look"]
        kept = ledger.read_text()
        ledger.unlink()
        try:
            code, out = tune(data, levers=("pool",), name="gone")
            assert not ledger.exists()
        finally:
            ledger.write_text(kept)
        assert code == 0, out
        again = record(data, "gone")["confirmation"]
        assert again["look"] == look and again["look_lost"] == ss.TUNE_LOOK_LOST
        assert again["verdict"] == rec["confirmation"]["verdict"]
        assert f"look {look['look']} for this league kind (line {look['line']} of " in out
        assert ss.TUNE_LOOK_LOST in out and "appended" not in out
        # With its line back the tune is as it was.
        code, out = tune(data, levers=("pool",), name="gone")
        assert code == 0 and record(data, "gone") == rec, out
        # The record gone, the pairs still there.
        file = reader.tune_dir(data, "gone") / reader.TUNE_FILE
        text = file.read_text()
        file.unlink()
        try:
            counted, there = looks(data), files(data, "gone")
            code, out = tune(data, levers=("pool",), name="gone")
            assert code == 2, out
            assert "refused: the tune 'gone' has pairs on file under " in out
            assert f"and no record ({reader.TUNE_FILE})" in out and "its plan" not in out
            assert looks(data) == counted and files(data, "gone") == there
        finally:
            file.write_text(text)


# --------------------------------------------------------------------------- the public leagues' kind
def test_a_tune_in_a_faab_league_under_continuous_waivers_with_a_held_slot(data: Path):
    """The command played once in the kind of league the levers are for: a budget and sealed
    bids, every add a claim, a held slot, every category a result. The sizing's four values and
    the pool's two are played and audited, the search reads category wins, the confirmation is
    played, and the league kind is its own first look."""
    flags = ("--waivers", "faab", "--waiver-rule", "continuous", "--held", "IL=1")
    flags += ("--h2h", "each_category")

    def worth(arm: rn.Arm, season: int) -> float:
        return float(arm.knobs["faab_sizing"] or 1.0) + pool(arm) / 15

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth)))
        code, out = tune(data, *flags, levers=("pool", "faab_sizing"), name="public")
    assert code == 0, out
    rec = record(data, "public")
    rules = rec["league"]["rules"]
    assert (rules["waivers"], rules["waiver_rule"], rules["held"], rules["h2h"]) == (
        "faab",
        "continuous",
        ["IL"],
        "each_category",
    )
    assert rec["measure"] == "category_wins" and rec["league"]["kind"]["rules"]["budget"] > 0
    sizing, wider = rec["steps"]
    assert {v["key"]: v["status"] for v in sizing["values"]} == dict.fromkeys(
        ("faab_sizing-0.5", "faab_sizing-0.5-again", "faab_sizing-2", "faab_sizing-2-again"),
        sc.PLAYED,
    )
    assert (sizing["from"], sizing["change"]) == (None, {"faab_sizing": 4.0})
    assert sizing["choice"]["standings"] == {
        "faab_sizing-0.5": tn.WORSE,
        "faab_sizing-0.5-again": tn.WORSE,
        "faab_sizing-2": tn.BEATEN,
        "faab_sizing-2-again": tn.TAKEN,
    }
    assert wider["change"] == {"pool": 60}
    assert rec["final"]["set"] == {"faab_sizing": 4.0, "pool": 60} and not rec["final"]["unread"]
    for key in ("p1-faab_sizing-2-again", "p1-pool-45-again", "confirm-run"):
        pair = pair_of(data, "public", key)
        assert pair["league"]["rules"] == rules and pair["audit"]["paths_voided"] == 0
    conf = rec["confirmation"]
    assert conf["status"] == tn.CONFIRMED and conf["verdict"]["state"] == tn.HOLDS
    assert conf["look"]["look"] == 1 and "look 1 for this league kind" in out
    assert set(conf["cells"]["run"]["prior"]["counts"]) == {"a", "b", "rivals"}


# --------------------------------------------------------------------------- the league kind
def test_a_league_kind_is_the_league_s_shapes_and_rules_and_not_how_its_rivals_bid():
    """What a tune's looks are counted by: the league shapes and the league's rules. How the
    rivals bid in a FAAB league is the rivals', as the kind of rivals an arm names is, so two
    tunes that differ only there are one league kind; the budget, the waivers, the waiver rule,
    the held slots and the format each make another (a points league is the ledger test's)."""

    def kind(**rules) -> dict:
        plan = SimpleNamespace(grid=shapes.FIXED_GRID, league_rules=shapes.LeagueRules(**rules))
        return ss.league_kind(plan)

    faab = kind(waivers="faab", waiver_rule="continuous")
    assert set(faab) == {"shapes", "rules"}
    assert faab["shapes"] == [shapes.FIXED.payload()]
    assert faab["rules"]["waivers"] == "faab" and "budget" in faab["rules"]
    assert not set(ss.TUNE_RIVALS) & set(faab["rules"])
    assert set(ss.TUNE_RIVALS) <= set(shapes.LeagueRules(waivers="faab").payload())
    assert kind(waivers="faab", waiver_rule="continuous", rival_scale=0.5) == faab
    others = [
        kind(waivers="faab", waiver_rule="continuous", budget=200),
        kind(waivers="faab"),
        kind(waivers="priority", waiver_rule="continuous"),
        kind(),
        kind(held=("IL",)),
        kind(h2h="each_category"),
    ]
    hashes = {ss.spec_hash(k) for k in (faab, *others)}
    assert len(hashes) == len(others) + 1
    # The kind is the shapes as played, not the grid's name: one shape named two ways is one.
    named = shapes.one("league", shapes.parse_league("teams=12"))
    assert named.name != shapes.FIXED_GRID.name
    assert ss.league_kind(SimpleNamespace(grid=named, league_rules=shapes.LeagueRules())) == kind()


def test_a_screen_is_held_to_the_league_in_force_and_what_else_differs_is_said():
    """A screen's league kind is read as its flags name it, not as they were typed: one shape
    typed in another order of keys is the same kind, another shape is another. What else the
    screen was played under that the tune is not (the code's versions, the fit, the cells, the
    seed) is listed for the record and refuses nothing."""
    rules = shapes.LeagueRules()
    shape = shapes.one("league", shapes.parse_league("adds=2,teams=10"))
    kind = ss.league_kind(SimpleNamespace(grid=shape, league_rules=rules))
    world = {"grid": "fixed", "league": "teams=10,adds=2", "seasons": [2023], "seed": 5}
    spec = {"arm": BASE, "world": world, "screen_version": 1, "replay_version": 13, "fit_sha": "f"}
    screen = {"name": "s", "left": [], "spec": spec, "league": {"rules": rules.payload()}}
    assert ss.screen_unfit(screen, BASE, kind, 2026) is None
    assert ss.screen_unfit(screen, BASE, kind, None) is None
    other = {**screen, "spec": {**spec, "world": {**world, "league": "teams=12"}}}
    assert "it was played in another league kind (the league shapes: " in str(
        ss.screen_unfit(other, BASE, kind, 2026)
    )
    unread = {**screen, "spec": {**spec, "world": {**world, "league": "teams=many"}}}
    assert "another league kind (the league shapes" in str(ss.screen_unfit(unread, BASE, kind, 1))
    assert "it was played on season 2023, the season this tune confirms on" in str(
        ss.screen_unfit(screen, BASE, kind, 2023)
    )
    assert ss.shapes_in_force(world) == kind["shapes"]
    assert ss.shapes_in_force({"grid": "fixed", "league": None}) == [SMALL.shapes[0].payload()]
    assert ss.shapes_in_force({"grid": "nope"}) is None
    # What differs beside the kind: by name, with both values; the kind's own flags are not here.
    mine = {
        **spec,
        "replay_version": 14,
        "world": {"grid": "full", "league": None, "seasons": [2024], "seed": 5, "h2h": "one_win"},
    }
    assert ss.screen_differs(screen, mine) == {
        "replay_version": {"screen": 13, "tune": 14},
        "seasons": {"screen": [2023], "tune": [2024]},
    }
    assert ss.screen_differs(screen, spec) == {}
    assert ss.screen_differs(screen, {**spec, "fit_sha": "g", "book_sha": "b"}) == {
        "fit_sha": {"screen": "f", "tune": "g"},
        "book_sha": {"screen": None, "tune": "b"},
    }


# --------------------------------------------------------------------------- the league's measure
@pytest.mark.parametrize(
    ("flags", "measure", "moves"),
    [
        ((), "matchup_wins", False),
        (("--h2h", "each_category"), "category_wins", True),
        (("--scoring", "points"), "matchup_wins", False),
    ],
    ids=["one-win", "each-category", "points"],
)
def test_the_search_reads_the_measure_the_league_s_standings_count(data, flags, measure, moves):
    """In a world where a wider pool wins more categories and fewer matchups, the lever moves
    only in the league whose standings count every category: in both formats and in a points
    league the search reads the league's own measure, and each league kind is its own."""

    def world(a: rn.Arm, b: rn.Arm, season: int, path: int):
        d = (pool(b) - pool(a)) / 15 * (1 + 0.25 * path)
        return {"category_wins": d, "matchup_wins": -d}

    name = "kind-" + (flags[1] if flags else "plain")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(world))
        code, out = tune(data, *flags, levers=("pool",), name=name, confirm="none")
    assert code == 0, out
    rec = record(data, name)
    assert rec["measure"] == measure
    assert f"each lever's values from the baseline, on {sc.MEASURE_WORDS[measure]}:" in out
    rules = rec["league"]["rules"]
    assert rec["league"]["kind"] == {"shapes": [SMALL.shapes[0].payload()], "rules": rules}
    assert (rules["scoring"], rules["h2h"] if rules["scoring"] == "categories" else None) == (
        ("points", None) if "points" in flags else ("categories", flags[1] if flags else "one_win")
    )
    (step,) = rec["steps"]
    assert all(v["result"]["measure"] == measure for v in step["values"])
    assert step["change"] == ({"pool": 60} if moves else None)
    assert set(step["choice"]["standings"].values()) == (
        {tn.BEATEN, tn.TAKEN} if moves else {tn.WORSE}
    )
    pair = pair_of(data, name, "p1-pool-45")
    assert pair["league"]["rules"] == rules and pair["audit"]["paths_voided"] == 0


# --------------------------------------------------------------------------- the second stage
#: The overrides the second stage is given (PR dynamic knobs): four, each worth one in the world
#: below at one of its values; the league is small, so its axis is ``phase`` (two teams both in
#: the final have no cut line, and ``standing`` names no situation there).
OVERRIDES = (
    "daily_cap@phase.run_in",
    "daily_cap@phase.opening",
    "daily_cap@phase.bracket",
    "protection_floor@phase.opening",
)


def override_worth(arm: rn.Arm, season: int) -> float:
    """A wider pool is worth more, as :data:`WIDER` says, and so is each override at its value:
    a third add in the opening and the bracket, one in the run-in, a floor above 0 in the
    opening."""
    v = lambda name: sc.value_of(arm, name)
    return (
        pool(arm) / 15
        + (v("daily_cap@phase.opening") == 3)
        + (v("daily_cap@phase.run_in") == 1)
        + (v("daily_cap@phase.bracket") == 3)
        + (float(v("protection_floor@phase.opening")) > 0)
    )


def test_the_second_stage_searches_overrides_from_the_static_best_and_stops_at_three(data):
    """The first stage moves the pool; the second starts from there (the static best), takes
    the first three overrides in its order, each at the value that helps, and stops at the
    cap with the fourth unsearched. Its pairs are the ``d`` pass's, each step names its stage,
    and the confirmation sets the dynamic best against the static best beside the final set
    against the baseline."""
    order = [o["lever"] for o in tn.split_order_of(None, list(OVERRIDES))]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(override_worth)))
        code, out = tune(data, "--overrides", *OVERRIDES, levers=("pool",), name="dynamic")
    assert code == 0, out
    rec = record(data, "dynamic")
    assert rec["tune_version"] == tn.TUNE_VERSION == 2 and rec["dynamic_rule"] == tn.DYNAMIC_RULE
    assert rec["spec"]["overrides"] == order
    assert [o["lever"] for o in rec["overrides_order"]] == order
    stages = [s["stage"] for s in rec["steps"]]
    assert stages == [tn.STATIC_STAGE] * stages.count(tn.STATIC_STAGE) + [tn.DYNAMIC_STAGE] * 3
    final = rec["final"]
    taken = order[:3]
    assert set(final["overrides"]) == set(taken) and set(taken) <= set(final["levers"])
    # Each taken at the value that helps: the pool's worth and one for each.
    assert override_worth(rn.arm_of(final["arm"]), 2024) == pytest.approx(60 / 15 + 3)
    assert final["static_best"]["pool"] == 60 and not policy.overrides_of(
        final["static_best"]["knobs"]
    )
    assert final["dynamic_stop"] == tn.FULL.format(n=3)
    assert f"the second stage: {tn.FULL.format(n=3)}" in out
    # The first override's pairs are the dynamic pass's.
    first = next(s for s in rec["steps"] if s["stage"] == tn.DYNAMIC_STAGE)
    assert first["lever"] == order[0] and first["change"] is not None
    played = [v for v in first["values"] if v.get("file")]
    assert played and all(v["file"].startswith("d1-") for v in played)
    # Each names the file its pair is kept in (the key's ``@`` made safe), and it is there.
    folder = reader.tune_dir(data, "dynamic")
    for step in rec["steps"]:
        for v in step["values"]:
            if v.get("file"):
                assert "@" not in v["file"] and (folder / v["file"]).is_file(), v["file"]
    pair = pair_of(data, "dynamic", f"d1-{played[0]['key']}")
    assert pair["tune"]["stage"] == tn.DYNAMIC_STAGE
    assert reader.pair_file(f"d1-{played[0]['key']}") == played[0]["file"]
    # The lab lists the tune and says nothing of it missing (the folder's made-up screens aside).
    m = sv.Lab(data).model()
    assert "dynamic" in {t.get("name") for t in m["tunes"]}
    assert not [x for x in m["generated"]["lacks"] if "dynamic" in x]
    # The confirmation: the final set against the baseline, and the dynamic best against the
    # static best, each its own pair on the confirmation season.
    conf = rec["confirmation"]
    against = conf["against_static"]
    assert against["note"] == tn.AGAINST_STATIC
    assert against["files"] == {"run": "confirm-static-run.json"}
    assert against["arms"]["run"]["a"]["pool"] == 60
    assert against["arms"]["run"]["b"]["name"] == "B:dynamic"
    static = pair_of(data, "dynamic", "confirm-static-run")
    assert static["seasons"] == [2026] and static["specs"] == against["arms"]["run"]


def test_a_second_stage_from_the_baseline_says_the_static_best_is_the_baseline(data):
    """When the first stage moves nothing, the dynamic best is confirmed against the baseline
    alone, and the record says the static best is the baseline."""

    def worth(arm: rn.Arm, season: int) -> float:
        return float(sc.value_of(arm, "daily_cap@phase.opening") == 3)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "task_paired", made_up(worth_world(worth)))
        code, out = tune(
            data, "--overrides", "daily_cap@phase.opening", levers=("pool",), name="from-base"
        )
    assert code == 0, out
    rec = record(data, "from-base")
    assert rec["final"]["overrides"] == {"daily_cap@phase.opening": 3}
    assert rec["final"]["static_best"] == BASE and "dynamic_stop" not in rec["final"]
    assert rec["confirmation"]["against_static"] == {
        "note": tn.AGAINST_STATIC,
        "status": tn.STATIC_IS_BASE,
    }


# --------------------------------------------------------------------------- the progress file
def test_a_tune_keeps_its_pair_in_play_s_progress_file_and_records_as_without_it(
    data: Path, tmp_path: Path, monkeypatch
):
    """PR live screen: a tune's folder keeps the progress file while a search pair and a
    confirmation pair are played, removes it after each, and its records are byte for byte the
    ones a run with ``cli.PROGRESS`` off writes (two copies of the module's data root, the clock
    pinned; the tune's own record all but its measured ``timing``)."""
    from tests.sim.test_sim_progress import Pinned

    watched, unwatched = tmp_path / "watched", tmp_path / "unwatched"
    for root in (watched, unwatched):
        shutil.copytree(data, root, symlinks=True)
    monkeypatch.setattr(ss, "datetime", Pinned)
    monkeypatch.setattr(ss, "task_paired", made_up(WIDER))
    seen: list[tuple[str, str, bool, int | None]] = []
    start, done, close = ss.PairWatch.start, ss.PairWatch.done, ss.PairWatch.close

    def look(w: ss.PairWatch, step: str) -> None:
        f = w.folder / reader.PROGRESS_FILE
        seen.append(
            (step, w.key, f.exists(), json.loads(f.read_text())["done"] if f.exists() else None)
        )

    def watched_start(self, made, first):
        start(self, made, first)
        look(self, "start")

    def watched_done(self, index, result):
        done(self, index, result)
        look(self, "done")

    def watched_close(self):
        close(self)
        look(self, "close")

    monkeypatch.setattr(ss.PairWatch, "start", watched_start)
    monkeypatch.setattr(ss.PairWatch, "done", watched_done)
    monkeypatch.setattr(ss.PairWatch, "close", watched_close)
    code, out = tune(watched, levers=("pool",), name="progress")
    assert code == 0, out
    keys = list(dict.fromkeys(k for _, k, _, _ in seen))
    assert any(k.startswith("p1-") for k in keys) and any(k.startswith("confirm-") for k in keys)
    for key in keys:
        mine = [(step, there, n) for step, k, there, n in seen if k == key]
        assert mine[-1] == ("close", False, None), key  # gone once its record is written
        counts = [n for step, there, n in mine[:-1] if there]
        assert len(counts) == len(mine) - 1 and counts == sorted(counts) and counts[-1] >= 1, key
        assert reader.read_tune_pair(watched, "progress", key) is not None
    assert not (reader.tune_dir(watched, "progress") / reader.PROGRESS_FILE).exists()
    # The same tune with the writing off: the same records.
    monkeypatch.setattr(ss, "PROGRESS", False)
    code, out = tune(unwatched, levers=("pool",), name="progress")
    assert code == 0, out

    def kept(root: Path) -> dict[str, bytes]:
        folder = reader.tune_dir(root, "progress")
        return {
            f.name: f.read_bytes().replace(str(root).encode(), b"<root>")
            for f in sorted(folder.iterdir())
        }

    mine, theirs = kept(watched), kept(unwatched)
    assert set(mine) == set(theirs) and reader.TUNE_FILE in mine
    for f in sorted(set(mine) - {reader.TUNE_FILE}):
        assert mine[f] == theirs[f], f
    a, b = (json.loads(x[reader.TUNE_FILE]) for x in (mine, theirs))
    assert {k: v for k, v in a.items() if k != "timing"} == {
        k: v for k, v in b.items() if k != "timing"
    }
