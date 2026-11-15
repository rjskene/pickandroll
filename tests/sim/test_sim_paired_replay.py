"""The paired design on a replay (#172, PR D2): ``replay --arms A.json B.json`` puts arm A in one
seat in one season and arm B in the same seat in a second, through one world, the seat following
the path; the eleven other seats are each arm's rivals on the run's forecaster.

The pair's own properties are checked on the no-peek test's small replay season (four teams);
the command's on the synthetic data folder, with static seats so a task is quick."""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import belief as bf
from pickandroll.sim import cli as ss
from pickandroll.sim import forecast as fc
from pickandroll.sim import run as rn
from tests.sim.sim_league import KNOBS, arm, make_data_dir
from tests.sim.test_no_peek import SEED, WEIGHTS, recorded

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
WHEN = ("started_at", "finished_at")


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


@pytest.fixture(scope="module")
def season():
    return recorded()


def world(setup, lines, **kw):
    return rn.replay_world(setup, lines, 1, SEED, 0, WEIGHTS, **kw)


# --------------------------------------------------------------------------- the pair itself
def test_the_same_arm_as_a_and_b_differs_in_nothing_and_b_solves_nothing(season):
    setup, lines = season
    a = arm("A", "surrogate", "static")
    out = rn.paired(setup, world(setup, lines), a, replace(a), 1)
    assert all(v == 0.0 for v in out["delta"].values() if v is not None)
    assert out["a"] == out["b"] and out["counts"]["a"] == out["counts"]["b"]
    solves_a, solves_b = out["solves_by_arm"]
    assert solves_a > 0 and solves_b == 0 and out["shared"] == solves_a


def test_swapping_a_and_b_changes_every_differences_sign_and_nothing_else(season):
    setup, lines = season
    a, b = arm("A", "surrogate", "static"), arm("B", "ranking", "static")
    ab = rn.paired(setup, world(setup, lines), a, b, 1)
    ba = rn.paired(setup, world(setup, lines), b, a, 1)
    assert ab["a"] == ba["b"] and ab["b"] == ba["a"]
    assert any(v for v in ab["delta"].values())  # the two arms differ somewhere
    for k, v in ab["delta"].items():
        assert ba["delta"][k] == (None if v is None else -v)
    assert ab["counts"]["a"] == ba["counts"]["b"] and ab["counts"]["b"] == ba["counts"]["a"]
    assert ab["counts"]["rivals"] == ba["counts"]["rivals"]
    assert ab["scale"]["a"] == ba["scale"]["b"] and ab["scale"]["b"] == ba["scale"]["a"]
    assert ab["breaches"] == [] == ba["breaches"]


def test_with_stand_ins_the_seat_holds_each_arms_label_and_the_rivals_the_runs(season):
    """A ``bbm`` arm against a ``yahoo`` arm: seat ``me`` holds the first stand-in's label in A's
    season and the yahoo label in B's, every rival holds the run's, and no decision is shared."""
    setup, lines = season
    first = dict(setup.projection)
    second = {k: {s: v * (1.4 if k % 3 else 0.7) for s, v in r.items()} for k, r in first.items()}
    sources = (fc.Forecaster("first"), fc.Forecaster("second"))
    a = arm("A", "surrogate", "static")
    b = replace(a, name="B", knobs={**a.knobs, "system": "yahoo"})
    arms = ss.believing({"a": a, "b": b}, sources)
    forecasts = {
        x.forecaster: fc.system_rates(str(x.knobs["system"]), x.knobs["blend"], first, second)
        for x in arms.values()
    }
    split = ss.splits_of(sources, arms)
    w = world(setup, lines, label="run", forecasts=forecasts, split=split)
    holds: dict[int, set] = {0: set(), 1: set()}

    def keep(r: rn.DayRecord) -> None:
        holds[r.variant].add(tuple(sorted(r.holds.items())))

    out = rn.paired(setup, w, arms["a"], arms["b"], 3, on_day=keep)
    assert holds[0] == {((3, "first"),)}
    assert holds[1] == {((3, "yahoo(second else first)"),)}
    assert out["shared"] == 0 and out["breaches"] == []


# --------------------------------------------------------------------------- the command
@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    folder = make_data_dir(tmp_path_factory.mktemp("paired"))
    assert ss.main(["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    specs = {
        "S": {"tier": "static", "opponents": {"kind": "static"}},
        "R": {"tier": "ranking", "opponents": {"kind": "static"}},
        "M": {"tier": "ranking", "opponents": {"kind": "market"}},
        "Mr": {"tier": "ranking", "opponents": {"kind": "market", "rate": 0.2}},
    }
    for name, spec in specs.items():
        (folder / f"{name}.json").write_text(json.dumps({"name": name, "knobs": KNOBS, **spec}))
    return folder


def replay(data: Path, *extra: str) -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--seed", "5", *extra])
    return code, buf.getvalue()


def spec(data: Path, *names: str) -> list[str]:
    return [str(data / f"{n}.json") for n in names]


def test_the_command_names_seats_or_arms_and_a_market_rival_names_its_rate(data: Path):
    for flags, why in (
        (("--seats", *spec(data, "S", "R"), "--arms", *spec(data, "S", "R")), "never both"),
        ((), "never both and never neither"),
        (("--arms", *spec(data, "S", "R", "S")), "--arms names exactly two spec files"),
        (("--arms", *spec(data, "M", "R")), "arm A (M) has market rivals without a rate"),
    ):
        code, out = replay(data, *flags, "--paths", "1", "--dry-run")
        assert code == 2 and why in out, out
    code, out = replay(data, "--arms", *spec(data, "Mr", "R"), "--paths", "1", "--dry-run")
    assert code == 0, out


def test_the_paths_are_a_multiple_of_the_seats_and_the_seat_follows_the_path(data: Path):
    assert [ss.paths_for_pair(n) for n in (1, 12, 20, 24, 25)] == [12, 12, 24, 24, 36]
    code, out = replay(data, "--arms", *spec(data, "R", "S"), "--paths", "20", "--dry-run")
    assert code == 0, out
    assert "--paths 20 rounded up to 24, a multiple of the league's 12 seats" in out
    assert "24 tasks (1 cells x 24 paths)" in out and "pair, the first task: seat 1;" in out
    # Path 13's task puts the pair in the second seat.
    sources, named = None, fc.parse("prior")
    a, b = (rn.arm_of(json.loads(Path(p).read_text())) for p in spec(data, "R", "S"))
    arms = ss.believing({"a": a, "b": b}, sources)
    r = ss.read_season(data, 2024, named, sources, arms, 5, "stat")
    out13 = ss.task_paired(
        2024, r.lines, r.members, r.scheduled, named[0], r.fixed, "stat", sources, 1,
        r.weights, 2.0, arms, ss.PAIR, 5, 13,
    )  # fmt: skip
    assert out13["seat"] == 2 and set(out13["unprojected"]) == {"a", "b"}


def test_the_same_seed_twice_gives_the_same_payload(data: Path):
    """Twelve paths of the same static arm as A and B: every seat once, every difference zero,
    each path distinct by its seat; run twice, the payloads agree apart from their times."""
    runs = []
    for _ in range(2):
        code, out = replay(data, "--arms", *spec(data, "S", "S"), "--paths", "12")
        assert code == 0, out
        (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
        runs.append(json.loads(Path(line.removeprefix("written: ")).read_text()))
    one, two = runs
    assert {k: v for k, v in one.items() if k not in WHEN} == {
        k: v for k, v in two.items() if k not in WHEN
    }
    assert one["design"] == "paired" and one["seat"]["by_path"] == list(range(1, 13))
    cell = one["results"]["2024"]["prior"]
    assert cell["paths"] == 12 and cell["distinct"] == 12
    assert all(d["mean"] == 0.0 for d in cell["difference"].values() if d["mean"] is not None)
    assert set(one["counts"]["by_season"]["2024"]["prior"]) == {"a", "b", "rivals"}
    assert one["rivals"]["a"] == {"kind": "static"} and "run's forecaster" in one["rivals"]["note"]
    assert set(one["unprojected"]["by_season"]["2024"]["prior"]) == {"a", "b"}
    assert one["arms"] == {"a": "S", "b": "S"} and set(one["specs"]) == {"a", "b"}
    # The verdict reads the one cell: a change of exactly zero is not above zero.
    v = one["verdict"]
    assert v["passes"] is False and v["failed"] == ["prior pooled: +0.0000 is not above zero"]
    assert v["rows"]["prior"]["cells"]["2024"]["se"] == 0.0 and "SE in a cell" in v["notes"][0]


def test_the_no_peek_check_on_the_pair(data: Path, monkeypatch):
    """The check compares both seasons' day records on path 0: they agree through the day, and
    a belief that counts the day's own line parts them on or before it."""
    flags = ("--arms", *spec(data, "R", "Mr"), "--no-peek", "2023-11-06")
    code, out = replay(data, *flags)
    assert code == 0 and "agree through 2023-11-06" in out, out
    monkeypatch.setattr(
        bf.CausalBelief,
        "games_before",
        lambda self, player, d: sum(1 for x in self._dates.get(player, []) if x <= d),
    )
    code, out = replay(data, *flags)
    assert code == 1 and "FAILED: the records part on" in out, out
    parted = date.fromisoformat(out.split("FAILED: the records part on ")[1][:10])
    assert parted <= date(2023, 11, 6)
