"""The private league's suggestions pass the queue's own checks (#494, the user's ruling of
2026-11-23): ``season.autopilot.suggestions_of`` runs ``queue_of`` with only the execution-only
gates opened, and the pre-tip push, the landing row and the moves view list the moves that pass,
from the one record the solve keeps (``checks``). Every league here is made up."""

from __future__ import annotations

import json
from datetime import date

import pytest

from pickandroll.api import season_pretip as pt
from pickandroll.api import season_private as spv
from pickandroll.season import autopilot as qa
from tests.test_moves_queue import DAY, NEXT, PLAN, WEEK, entry, league_day, move, planned, step
from tests.test_recent_blend import knob_file
from tests.test_season import LEAGUE, season_client, strategy_league


def why(entries):
    return [(e["add"], e["reason"]) for e in entries]


# --------------------------------------------------------------------------- the checks
def test_the_suggestions_keep_every_check_but_the_execution_only_gates():
    e = entry(
        move(101, 201, 0.9),
        move(102, 202, 0.8),  # its drop on an open claim: an execution gate, opened
        move(103, 203, 0.7, costly=True),  # the season guard
        move(104, None, 0.6),  # dropped within the waiver days: the re-add rule
        move(105, 205, 0.05),  # under the plan floor
        move(106, 206, 0.5),  # its drop protected by the keep rule
        move(107, 207, 0.4),  # past the public cap of two: the cap is opened
    )
    day = league_day(
        e,
        private=True,
        mode="off",
        cap=2,
        done=1,
        protected={206: "kept"},
        dropped=frozenset({104}),
        open_claims=[{"add": 999, "drop": 202}],
    )
    # The queue refuses all of it in the private league ...
    assert {r for _, r in why(qa.queue_of(day, DAY, PLAN, (0.1, "x"), None))} == {qa.PRIVATE}
    # ... the suggestions keep the checks and open the gates.
    assert why(qa.suggestions_of(day, DAY, PLAN)) == [
        (101, None),
        (102, None),
        (103, qa.SEASON_COSTLY),
        (104, qa.READD),
        (106, qa.PROTECTED),
        (107, None),
        (105, qa.BELOW_FLOOR),
    ]


def test_a_week_plan_keeps_its_steps_and_a_later_step_waits_for_its_day():
    e = planned(
        step(111, 211, 0.5, "2026-10-21", 0, 3),
        step(112, 212, 0.5, "2026-10-23", 1, 3),
        step(113, 213, 0.5, "2026-10-21", 2, 3),
    )
    out = qa.suggestions_of(league_day(e, private=True), DAY, PLAN)
    # The plan, not the three weeks' set (101), and no fallback to it.
    assert why(out) == [(111, None), (112, qa.LATER_STEP), (113, qa.EARLIER_HELD)]


def test_a_week_with_its_adds_used_or_unread_suggests_nothing_in_it():
    e = entry(move(101, 201, 0.9), move(102, 202, 0.8), move(103, 203, 0.7, frm="2026-10-26"))
    out = qa.suggestions_of(league_day(e, adds_left={WEEK: 1, NEXT: 5}), DAY, PLAN)
    assert why(out) == [(101, None), (102, qa.NO_ADDS), (103, None)]
    out = qa.suggestions_of(league_day(e, unread=frozenset({WEEK})), DAY, PLAN)
    assert why(out) == [(101, qa.ADDS_UNREAD), (102, qa.ADDS_UNREAD), (103, None)]


def test_the_users_picks_are_not_the_suggestions():
    e = entry(move(101, 201, 0.9))
    e["sets"].append({"key": "pick", "moves": [move(150, 250, 0.01)], "held": []})
    assert why(qa.suggestions_of(league_day(e), DAY, PLAN)) == [(101, None)]


# --------------------------------------------------------------------------- the push
NAMES = {1: "Ayo Dosunmu", 2: "Jalen Smith", 3: "Kevin Love"}
TEAMS = {1: "CHI", 2: "CHI"}
EXPORTS = {"ros": None, "week_this": None, "week_next": None}
PUSH_DAY = date(2026, 11, 9)


def checked(*moves, floor=0.03, horizon="three", one_win=True, unread=False):
    return {
        "status": spv.CHECKED,
        "reason": None,
        "set": "three",
        "horizon": horizon,
        "floor": floor,
        "one_win": one_win,
        "adds_unread": unread,
        "moves": [
            {"add": a, "drop": d, "from": None, "passes": r is None, "reason": r, "on": None}
            for a, d, r in moves
        ],
    }


def push(moves, checks, status="solved"):
    return pt.markdown("31822", PUSH_DAY, moves, NAMES, TEAMS, EXPORTS, status, checks)


def test_the_push_lists_the_passing_moves_and_names_the_floor():
    c = checked((1, 2, None), (3, None, qa.BELOW_FLOOR))
    lines = push([{"add": 1, "drop": 2}], c).splitlines()
    assert lines[1:3] == [
        "- add Ayo Dosunmu (CHI), drop Jalen Smith (CHI)",
        "- each clears the checks: the floor is +3 points of the matchup's win odds over the "
        "three weeks",
    ]
    assert "Kevin Love" not in "\n".join(lines)


def test_the_push_says_why_nothing_is_suggested():
    none = checked((1, 2, qa.BELOW_FLOOR), (3, None, qa.SEASON_COSTLY), horizon="week")
    assert push([], none).splitlines()[1] == (
        "- no move clears the checks: the floor is +3 points of the matchup's win odds over the week"
    )
    cats = checked((1, 2, qa.BELOW_FLOOR), floor=0.1, one_win=False)
    assert push([], cats).splitlines()[1].endswith("+0.1 expected categories over the three weeks")
    unread = checked((1, 2, qa.ADDS_UNREAD), (3, None, qa.BELOW_FLOOR), unread=True)
    assert push([], unread).splitlines()[1] == "- adds not read today"
    assert push([], checked()).splitlines()[1] == "- no move recommended"
    failed = push([], spv.failed("KeyError: 'x'"))
    assert failed.splitlines()[1] == "- not checked (KeyError: 'x'): no suggestion"
    # A public league's push (no checks) is as before.
    assert push([], None).splitlines()[1] == "- no move recommended"


# --------------------------------------------------------------------------- the surfaces
@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def private(client) -> None:
    path = client.data_dir / "leagues" / LEAGUE / "settings.json"
    body = json.loads(path.read_text())
    path.write_text(json.dumps({**body, "public": False}))


def surfaces(client):
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    b = client.get(f"/seasons/{LEAGUE}/best").json()
    t = client.get(f"/seasons/{LEAGUE}/pretip").json()
    return m, b, t


def test_a_public_leagues_moves_and_line_carry_no_checks(client):
    strategy_league(client)
    public = client.get(f"/seasons/{LEAGUE}/moves").json()
    best = client.get(f"/seasons/{LEAGUE}/best").json()
    # A public league carries no checks: its payload and its line are as before.
    assert "checks" not in public and not {"checks", "gain_of"} & set(best)
    assert len(best["set"]) == len(public["recommended"]["three"]["moves"]) == best["moves"]


def test_the_push_the_landing_row_and_the_moves_view_agree_on_the_passing_moves(client):
    strategy_league(client)
    private(client)
    m, b, t = surfaces(client)
    c = m["checks"]
    assert c["status"] == "checked" and c["set"] == "three" and c["floor"] == 0.1
    three = m["recommended"]["three"]["moves"]
    assert [(x["add"], x["drop"]) for x in c["moves"]] == [(x["add"], x["drop"]) for x in three]
    passing = [(x["add"], x["drop"]) for x in c["moves"] if x["passes"]]
    refused = [x for x in c["moves"] if not x["passes"]]
    assert passing and refused, "the fixture's set straddles the floor"
    assert {x["reason"] for x in refused} == {qa.BELOW_FLOOR}
    # Every refused move is under the floor on the three weeks, every passing one clears it.
    gain = {(x["add"], x["drop"]): x["marginal"]["three"] for x in three}
    assert all(gain[(x["add"], x["drop"])] < 0.1 for x in refused)
    assert all(gain[k] >= 0.1 for k in passing)
    # The landing row, the push and the moves view list the same moves.
    assert [(x["add"], x["drop"]) for x in b["set"]] == passing
    assert [(x["add"], x["drop"]) for x in t["moves"]] == passing
    assert b["moves"] == len(passing) and b["checks"] == c
    # The row's gain is its move's own, not the set's.
    assert b["gain_of"] == "move" and b["gain"] == b["move"]["gain"] == max(gain[k] for k in passing)
    assert "each clears the checks: the floor is +0.1 expected categories" in t["markdown"]
    # Nothing is queued or clicked in the private league.
    assert client.post("/autopilot/queue/build").json()["leagues"][0]["status"] == "private"


def test_a_floor_no_move_clears_empties_every_surface(client):
    strategy_league(client)
    private(client)
    knob_file(client, {"plan_floor_cats": 5.0})
    m, b, t = surfaces(client)
    assert m["checks"]["moves"] and not any(x["passes"] for x in m["checks"]["moves"])
    assert b["set"] == [] and b["move"] is None and b["moves"] == 0 and b["gain"] is None
    assert t["moves"] == []
    assert "- no move clears the checks: the floor is +5 expected categories over the three weeks" in (
        t["markdown"]
    )


def test_a_failed_check_suggests_nothing_and_never_fails_the_solve(client, monkeypatch):
    strategy_league(client)
    private(client)

    def boom(*a, **k):
        raise RuntimeError("no flags")

    monkeypatch.setattr(spv, "checks", boom)
    m, b, t = surfaces(client)
    assert m["recommended"]["three"]["moves"] and m["checks"]["status"] == spv.FAILED
    assert b["set"] == [] and t["moves"] == []
    assert "- not checked (RuntimeError: no flags): no suggestion" in t["markdown"]
