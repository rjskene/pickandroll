"""The league generator on a run (#172, PR D4b): ``replay --grid`` and ``--league``, the record,
the weekly add limit, a draft that cannot be filled, and Rule 1 (on the fixed shape nothing
moves). No test plays seventy-two paths: a grid of four made-up shapes stands in for the full
one, which is tested on numbers alone (``test_sim_shapes.py``)."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.sim import adp, policy, shapes
from pickandroll.sim import cli as ss
from pickandroll.sim import counts as ct
from pickandroll.sim import run as rn
from tests.sim.sim_league import KNOBS, make_data_dir

BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto"))
WHEN = ("started_at", "finished_at")
#: Four made-up shapes standing in for the full grid: ten or twelve teams, two adds a week or no
#: limit, the thirteen slots and the fixed playoffs. Every draft of them fills on the season with
#: a wire (191 draftable).
SMALL = shapes.Grid("small", (10, 12), (shapes.SLOTS,), (2, None), ((6, 3),))


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


def _folder(tmp: Path, wire: int) -> Path:
    data = make_data_dir(tmp, wire=wire)
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, tier in (("S", "static"), ("R", "ranking")):
        spec = {"name": name, "tier": tier, "knobs": KNOBS, "opponents": {"kind": "static"}}
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


@pytest.fixture(scope="module")
def wire(tmp_path_factory) -> Path:
    """The made-up seasons with a wire of 120: 191 draftable players in 2024."""
    return _folder(tmp_path_factory.mktemp("grid-wire"), 120)


@pytest.fixture(scope="module")
def bare(tmp_path_factory) -> Path:
    """The made-up seasons as the pins have them: 85 draftable players in 2024."""
    return _folder(tmp_path_factory.mktemp("grid-bare"), 0)


def replay(data: Path, *extra: str, seed: str = "5") -> tuple[int, str]:
    argv = ["--data", str(data), "--rooms", "0", "replay", "--seasons", "2024", "--workers", "1"]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main([*argv, "--seed", seed, *extra])
    return code, buf.getvalue()


def spec(data: Path, *names: str) -> list[str]:
    return [str(data / f"{n}.json") for n in names]


def written(out: str) -> dict:
    (line,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return json.loads(Path(line.removeprefix("written: ")).read_text())


def test_league_and_grid_are_refused_by_name(wire: Path):
    pair = ("--arms", *spec(wire, "S", "R"))
    for flags, why in (
        (("--league", "teams=11"), "--league teams=11: the grid's teams are 10, 12, 14"),
        (("--league", "adds=0"), "--league adds=0: a positive whole count of adds a week, or none"),
        (("--league", "size=3"), "is not one of teams, slots, adds, playoffs="),
        (("--league", "teams=10", "--grid", "full"), "--league names one league shape"),
    ):
        code, out = replay(wire, *pair, *flags, "--paths", "1", "--dry-run")
        assert code == 2 and why in out, out
    # The full grid on the made-up season: fourteen teams of fifteen take 210 players and the
    # season has 191, so the run is refused by name before any path.
    code, out = replay(wire, *pair, "--grid", "full", "--paths", "1", "--dry-run")
    assert code == 2, out
    assert (
        "refused: 2024 on prior: the draft of 14 teams of 15 spots takes 210 players and the "
        "season has 191 draftable" in out
    )
    assert "tasks (" not in out


def test_on_the_fixed_shape_a_short_draft_is_noted_and_played_as_before(bare: Path):
    """Rule 1: ``--grid fixed`` named and nothing named give one payload; the made-up folder's
    85 players are fewer than the fixed shape's draft takes, which is noted and played as it
    always was."""
    room = ("--seats", *spec(bare, "R", "S"), "--paths", "2")
    runs = []
    for extra in ((), ("--grid", "fixed")):
        code, out = replay(bare, *room, *extra)
        assert code == 0, out
        assert (
            "short draft, played on the fixed shape with the rosters it cannot fill left short (a "
            "named league shape refuses it): 2024 on prior: the draft of 12 teams of 13 spots "
            "takes 156 players and the season has 85 draftable"
        ) in out
        runs.append(written(out))
    one, two = runs
    assert {k: v for k, v in one.items() if k not in WHEN} == {
        k: v for k, v in two.items() if k not in WHEN
    }
    league = one["league"]
    assert league["grid"] == "fixed" and league["shapes"] == [shapes.FIXED.payload()]
    assert league["by_path"] == [{"shape": 0, "turn": 0}, {"shape": 0, "turn": 1}]
    assert [x["holds"] for x in league["short_draft"]] == [85]
    assert one["replay_version"] == 21 and "by_axis" not in one


def test_a_pair_on_a_grid_plays_each_path_s_shape_and_seat(wire: Path, monkeypatch):
    monkeypatch.setitem(ss.GRIDS, "full", SMALL)
    seen = []
    real = rn.paired

    def spy(setup, w, a, b, me, on_day=None, on_end=None):
        seen.append((setup.teams, setup.max_weekly_adds, me))
        return real(setup, w, a, b, me, on_day, on_end)

    monkeypatch.setattr(rn, "paired", spy)
    code, out = replay(wire, "--arms", *spec(wire, "R", "S"), "--grid", "full", "--paths", "3")
    assert code == 0, out
    assert "--paths 3 rounded up to 4, a multiple of the grid's 4 league shapes" in out
    visits = [shapes.visit(p, SMALL) for p in range(4)]
    # The timed task runs first: the grid's largest draft (twelve teams) with no add limit.
    slow = next(
        p for p, v in enumerate(visits) if v.shape.teams == 12 and v.shape.weekly_adds is None
    )
    order = [slow, *(p for p in range(4) if p != slow)]
    # Both arms of a path hold the path's shape and one seat (``run.paired``: one league).
    want = [
        (visits[p].shape.ids, visits[p].shape.weekly_adds, visits[p].shape.ids[visits[p].turn % visits[p].shape.teams])
        for p in order
    ]  # fmt: skip
    assert seen == want
    payload = written(out)
    league = payload["league"]
    assert league["grid"] == "small" and len(league["shapes"]) == 4
    assert league["by_path"] == [{"shape": v.index, "turn": v.turn} for v in visits]
    assert payload["seat"]["by_path"] == [v.shape.ids[v.turn % v.shape.teams] for v in visits]
    assert payload["seat"]["rule"] == ss.SEAT_RULE_SHAPES
    assert "teams less one" in payload["rivals"]["note"]
    # Every note that counted twelve seats says the path's league's on a grid.
    note = payload["unprojected"]["note"]
    assert note != ss.UNPROJECTED_NOTE and "twelve" not in note and "league's seats" in note
    # The by-axis table: each axis's values, their paths and means give back the cell's mean.
    cell = payload["results"]["2024"]["prior"]["difference"]
    table = payload["by_axis"]["by_season"]["2024"]["prior"]
    assert set(table) == {"playoffs", "weekly_adds", "slots", "teams"}
    assert set(table["weekly_adds"]) == {"2", "none"} and set(table["teams"]) == {"10", "12"}
    assert table["teams"]["10"]["paths"] == 2 and table["slots"]["13"]["paths"] == 4
    for axis, values in table.items():
        for metric, whole in cell.items():
            if whole["mean"] is None:
                continue
            parts = [v["difference"][metric] for v in values.values() if v["paths"]]
            n = sum(x["n"] for x in parts)
            back = sum(x["n"] * x["mean"] for x in parts if x["mean"] is not None) / n
            assert n == whole["n"] and back == pytest.approx(whole["mean"]), (axis, metric)
    assert "not a test" in payload["by_axis"]["note"]


#: The path a dry run on :data:`SMALL` plays, its largest draft with no add limit, and its turn,
#: which is not its path: so a spy tells which of the two a step reads.
SLOW = 3
SLOW_TURN = 1


def _spies(monkeypatch) -> dict[str, list]:
    """Record every rotation's turn, every world's path and every table draft's path, seats and
    rule (``adp.Draft``) of a run."""
    seen: dict[str, list] = {"rotate": [], "world": [], "draft": [], "rule": []}
    rotate, world, draft = rn.rotate, rn.replay_world, adp.Draft

    def spy_rotate(arms, teams, turn):
        seen["rotate"].append((len(teams), turn))
        return rotate(arms, teams, turn)

    def spy_world(setup, lines, lag, seed, path, *rest, **kw):
        seen["world"].append(path)
        return world(setup, lines, lag, seed, path, *rest, **kw)

    def spy_draft(picks, spread, seed, path, seats, **rule):
        seen["draft"].append((path, tuple(sorted(seats))))
        seen["rule"].append(rule)
        return draft(picks, spread, seed, path, seats, **rule)

    monkeypatch.setitem(ss.GRIDS, "full", SMALL)
    monkeypatch.setattr(rn, "rotate", spy_rotate)
    monkeypatch.setattr(rn, "replay_world", spy_world)
    monkeypatch.setattr(adp, "Draft", spy_draft)
    return seen


def test_the_small_grid_s_timed_path_has_a_turn_that_is_not_its_path():
    v = shapes.visit(SLOW, SMALL)
    assert (v.shape.teams, v.shape.weekly_adds, v.turn) == (12, None, SLOW_TURN)


def test_a_room_on_a_grid_rotates_by_the_turn_and_draws_on_the_path(wire: Path, monkeypatch):
    """The room's dry run on the small grid plays path 3: its world on path 3, its twelve seats
    rotated by turn 1 (the unprojected count's and ``run.room``'s), no draft on a table."""
    seen = _spies(monkeypatch)
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--grid", "full", "--paths", "1", "--dry-run")  # fmt: skip
    assert code == 0, out
    assert "--paths 1 rounded up to 4, a multiple of the grid's 4 league shapes" in out
    assert f"the task timed is path {SLOW}" in out
    assert seen["world"] == [SLOW] and seen["draft"] == []
    assert seen["rotate"] and set(seen["rotate"]) == {(12, SLOW_TURN)}


def test_on_a_table_the_seat_follows_the_turn_and_the_rivals_draws_the_path(
    wire: Path, monkeypatch
):
    """Under a table on the small grid, the seats on their own boards (``--seat-draft own``,
    the rule before the draft PR, which names its seats in the draft): the pair's arm's seat is
    the shape's ``teams[turn mod
    n]`` (seat 2 of twelve) and the rivals' draws are keyed on path 3 (``adp.Draft``'s path); a
    room's every seat drafts on its arm's board, rotated by the turn, its draws on the path.
    Under the market's rule (the default) the draft names the same seat on the same path, and
    the rule; under ``own`` it names no rule, as before the PR."""
    table = (
        "--adp",
        "espn",
        "--adp-spread",
        "2,0.15",
        "--seat-draft",
        "own",
        "--grid",
        "full",
        "--paths",
        "1",
        "--dry-run",
    )
    seen = _spies(monkeypatch)
    code, out = replay(wire, "--arms", *spec(wire, "R", "S"), *table)
    assert code == 0, out
    seat = shapes.visit(SLOW, SMALL).shape.ids[SLOW_TURN % 12]
    assert seat == 2 and seen["draft"] == [(SLOW, (seat,))] and seen["world"] == [SLOW]
    seen = _spies(monkeypatch)
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), *table)
    assert code == 0, out
    assert seen["draft"] == [(SLOW, tuple(range(1, 13)))] and seen["world"] == [SLOW]
    assert seen["rotate"] and set(seen["rotate"]) == {(12, SLOW_TURN)}
    assert seen["rule"] == [{}]
    market = tuple(x for x in table if x not in ("--seat-draft", "own"))
    seen = _spies(monkeypatch)
    code, out = replay(wire, "--arms", *spec(wire, "R", "S"), *market)
    assert code == 0, out
    assert seen["draft"] == [(SLOW, (seat,))] and seen["world"] == [SLOW]
    assert seen["rule"] == [{"rule": "market"}]


def _week_most(data: Path, league: str, monkeypatch) -> tuple[int, set, dict]:
    """The most adds any seat landed in one week over one path of a room of R and S in
    ``league``, the weekly limits every queue call was given, and the run's payload."""
    most, given = [0], set()
    rows, queue = ct.Tally.rows, policy.queue

    def tally(self, state):
        for t in self.teams:
            most[0] = max([most[0], *self.adds[t].values()])
        return rows(self, state)

    def spy(state, team, decision, daily_cap, limit, *rest, **kw):
        given.add(limit)
        return queue(state, team, decision, daily_cap, limit, *rest, **kw)

    monkeypatch.setattr(ct.Tally, "rows", tally)
    monkeypatch.setattr(policy, "queue", spy)
    code, out = replay(data, "--seats", *spec(data, "R", "S"), "--league", league, "--paths", "1")
    assert code == 0, out
    return most[0], given, written(out)


def test_the_weekly_add_limit_is_the_league_s(wire: Path, monkeypatch):
    """Ten teams leave the made-up season's wire 61 projected players. Under a limit of two every
    move is queued under two and no seat lands a third add in a week (the audit's weekly rule
    would void the path); under no limit every move is queued under none and a ranking seat lands
    four in one week, which two forbids. On this season no seat wants more than four in a week
    (the ranking and the surrogate tier, daily caps up to three, seeds 1 to 8), so the fixed
    shape's four cannot be passed here: the queue's limit shows that none is not a number in
    disguise. The seed is the run's (5, as the other command tests)."""
    most, given, payload = _week_most(wire, "teams=10,adds=2", monkeypatch)
    assert given == {2} and most == 2 and payload["audit"]["paths_voided"] == 0
    assert payload["league"]["shapes"][0]["weekly_adds"] == 2
    most, given, payload = _week_most(wire, "teams=10,adds=none", monkeypatch)
    assert given == {None} and most > 2 and payload["audit"]["paths_voided"] == 0
    assert payload["league"]["shapes"][0]["weekly_adds"] is None


def test_one_league_for_a_whole_run(wire: Path):
    code, out = replay(wire, "--arms", *spec(wire, "S", "R"), "--league", "teams=10,playoffs=4/2", "--paths", "4", "--dry-run")  # fmt: skip
    assert code == 0, out
    assert "--paths 4 rounded up to 10, a multiple of the league's 10 seats" in out
    assert "10 tasks (1 cells x 10 paths)" in out and "pair, the first task: seat 1;" in out
    # The no-peek check plays path 0's league and says which.
    code, out = replay(wire, "--seats", *spec(wire, "R", "S"), "--league", "teams=10", "--no-peek", "2023-11-06")  # fmt: skip
    assert code == 0 and "agree through 2023-11-06" in out, out
    assert (
        "no-peek check's league: path 0's, 10 teams, 13 slots, 4 adds a week, 6 playoff teams "
        "over 3 weeks" in out
    )


def test_validate_stays_on_the_fixed_shape(bare: Path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert ss.main(["--data", str(bare), "--rooms", "0", "validate", "--dry-run"]) == 0
    assert f"gate 5 plays the fixed league shape: {shapes.FIXED.label()}" in buf.getvalue()
