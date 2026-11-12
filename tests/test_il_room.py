"""The IL room a placed claim needs (#364, items 1 and 2). A no-drop claim pending beyond the open
spots makes its room through a held-slot move: the fold makes that move in the problem, so one
IL spot backs one add only (251146 and 258332, 2026-11-11: a second claim "fit" on an IL move
another needed, and nothing made it); the re-judge names the move a kept claim needs
(``il_need``), the next moves pass makes it before the cancels, and a move that fails has its
claim cancelled in the same pass. Nothing here opens a page.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_moves, season_queue
from pickandroll.routine.routines import run
from pickandroll.routine.steps import moves_plan
from pickandroll.season import Player
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from tests.test_cancel import ALL, PAGE
from tests.test_il_move import a_player, il_body
from tests.test_moves import build, player, rates, streaming_league
from tests.test_moves_queue import DAY, live_league, queued
from tests.test_pending import CLEAR, built_of, claim, entry, folded
from tests.test_routine import YAHOO, Clock, FakeAPI, FakeBrowser, due_answers, make_ctx
from tests.test_season import LEAGUE, NOW, season_client

OUT = 3  # the third of mine, Out: the one an IL slot takes
DUE = f"/seasons/{LEAGUE}/autopilot/moves/due"
IL = f"/seasons/{LEAGUE}/autopilot/il"


def il_league(spots: int = 3, status: str | None = "O", **kw):
    """The streaming league with player 3 Out and one IL slot open: no active spot open with
    three spots, one with four."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    roster = [*roster[:2], player(OUT, "MIN", status)]
    cands = [*cands, player(12, "HLD")]
    rate = {**rate, 12: rates(0.8)}
    p = build(roster, cands, rate, sched, opponent, field, spots=spots, held_open={"IL": 1}, **kw)
    return p, dict(cands)


# --------------------------------------------------------------------------- the fold (item 2)
def test_a_claim_beyond_the_open_spots_takes_the_il_move_so_no_second_add_fits_it():
    p, players = il_league()
    assert mv.open_spots(p) == 0 and mv.feasible(p, [mv.Move(11)])  # 3 can go to IL
    q = folded(p, [claim(players, 10)])
    # The fold makes the move the claim needs: 3 is held, the IL slot taken, the roster full.
    assert q.il_owed == ((OUT, "IL"),) and q.held_slots[OUT] == "IL"
    assert OUT not in dict(q.roster) and q.held_open["IL"] == 0 and mv.overfull(q) == 0
    # The IL spot backs that claim alone: a second no-drop add finds no room.
    assert not mv.feasible(q, [mv.Move(11)])
    assert mv.feasible(q, [mv.Move(11, 2)])  # an add with a drop still fits


def test_two_claims_on_one_il_spot_leave_the_second_over_the_roster():
    p, players = il_league()
    q = folded(p, [claim(players, 10), claim(players, 11)])
    assert q.il_owed == ((OUT, "IL"),) and mv.overfull(q) == 1


# --------------------------------------------------------------------------- the re-judge
def judge(built, *ids):
    claims = [{**entry(add), "id": i, "judged": "week"} for i, add in ids]
    return season_moves.rejudge_claims(built, claims, {})


def test_the_claim_admitted_on_the_il_spot_names_the_move_and_the_second_has_no_room():
    p, players = il_league()
    built = built_of(p, [claim(players, 10), claim(players, 11)])
    out = judge(built, ("a", 10), ("b", 11))
    kept, cut = (out["a"], out["b"]) if "no_room" in out["b"] else (out["b"], out["a"])
    assert kept["il_need"] == {"player": OUT, "slot": "IL"} and kept["gain"] is not None
    assert cut["gain"] is None and cut["il_need"] is None and len(cut["no_room"]) == 1


def test_with_an_open_spot_the_first_claim_takes_it_and_the_second_the_il_move():
    p, players = il_league(spots=4)
    built = built_of(p, [claim(players, 10), claim(players, 11)])
    out = judge(built, ("a", 10), ("b", 11))
    assert "no_room" not in out["a"] and "no_room" not in out["b"]
    needs = sorted((out["a"]["il_need"] is None, out["b"]["il_need"] is None))
    assert needs == [False, True]  # one on the open spot, one on the IL move


def test_a_claim_whose_il_player_is_no_longer_out_is_judged_on_the_open_room():
    # 3 back to healthy: no held-slot move; on a full roster the claim has no room at all.
    p, players = il_league(status=None)
    out = judge(built_of(p, [claim(players, 10)]), ("a", 10))
    assert out["a"]["no_room"] == [] and out["a"]["il_need"] is None
    assert qa.rejudge_verdict(10, [], None, None, qa.Floor(0, None, 0), None, {}, [])[0] == (
        qa.CANCEL
    )
    # With a spot open it fits there, and needs no move.
    p, players = il_league(spots=4, status=None)
    out = judge(built_of(p, [claim(players, 10)]), ("a", 10))
    assert "no_room" not in out["a"] and out["a"]["il_need"] is None


# --------------------------------------------------------------------------- the queue's rules
EARLIER = (DAY - timedelta(days=1)).isoformat()


def placed_claim(add: int, il: dict | None = None, **kw) -> dict:
    e = {
        "id": f"{EARLIER}:{LEAGUE}:{add}:0",
        "league": LEAGUE,
        "add": add,
        "drop": None,
        "outcome": "claimed",
        "resolved": None,
        "queued": True,
        "il_need": {"player": 77, "slot": "IL", "at": f"{DAY}T02:00:00+00:00"},
        **kw,
    }
    if il is not None:
        e["il"] = il
    return e


def test_the_placed_claims_il_moves_are_due_once_a_player_until_made_or_failed():
    a, b = placed_claim(10), placed_claim(11)
    assert [x["entry"] for x in ap.placed_il_due([b, a], LEAGUE, DAY)] == [a["id"]]
    assert ap.placed_il_due([a], LEAGUE, DAY)[0] == {
        "entry": a["id"],
        "player": 77,
        "slot": "IL",
        "placed": True,
    }
    moved = placed_claim(10, il={"outcome": "moved", "at": f"{DAY}T15:00:00+00:00"})
    failed = placed_claim(10, il={"outcome": "failed", "at": f"{DAY}T15:00:00+00:00"})
    cancel = placed_claim(10, rejudge={"verdict": qa.CANCEL, "at": f"{DAY}T15:00:00+00:00"})
    for e in (moved, failed, cancel, {**a, "resolved": "won"}, {**a, "il_need": None}):
        assert ap.placed_il_due([e], LEAGUE, DAY) == []
    # A failure on an earlier day does not stop today's try.
    yesterday = placed_claim(10, il={"outcome": "failed", "at": f"{EARLIER}T03:00:00+00:00"})
    assert len(ap.placed_il_due([yesterday], LEAGUE, DAY)) == 1


def test_a_failed_il_move_makes_its_claims_cancel_due_and_a_made_one_does_not():
    at = f"{DAY}T15:40:00+00:00"
    failed = placed_claim(10, il={"outcome": "failed", "at": at})
    [c] = ap.cancel_due([failed], LEAGUE, DAY)
    assert (c["entry"], c["reason"], c["verdict_at"]) == (failed["id"], ap.IL_FAILED, at)
    moved = placed_claim(10, il={"outcome": "moved", "at": at})
    assert ap.cancel_due([moved], LEAGUE, DAY) == []
    # Pressed already: never again.
    assert ap.cancel_due([{**failed, "cancel": {"outcome": "cancelled"}}], LEAGUE, DAY) == []


# --------------------------------------------------------------------------- the routes
@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def placed(client) -> list[dict]:
    return [i for i in client.get(DUE).json()["il_first"] if i.get("placed")]


def earlier_claim(client, add: int, player_id: int) -> dict:
    folder = client.data_dir / "autopilot" / "queue"
    e = placed_claim(add, il_need={"player": player_id, "slot": "IL", "at": NOW.isoformat()})
    (folder / f"{EARLIER}.json").write_text(json.dumps({"date": EARLIER, "entries": [e]}))
    return e


def test_the_due_route_names_a_placed_claims_il_move_first_and_logs_it_on_its_own_day(client):
    queued(client)
    k, _ = a_player(client)
    e = earlier_claim(client, 9001, k)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    first = client.get(DUE).json()["il_first"]
    [x] = [i for i in first if i.get("placed")]
    assert first[0] == x  # before any due entry's own IL move
    assert (x["entry"], x["player"], x["slot"]) == (e["id"], k, "IL")
    assert x["accepts"] == ["O", "OFS"] and x["date"] == DAY.isoformat()
    # A live move that lands goes on the claim's entry in its own day's file: the claim stays
    # placed, nothing is cancelled, and the player is not listed again.
    live_league(client)
    moved = il_body(e["id"], k, mode="live", outcome="moved", trigger="routine_evening")
    r = client.post(IL, json=moved)
    assert r.status_code == 200, r.text
    [got] = season_queue.read(client.data_dir, DAY - timedelta(days=1))["entries"]
    assert got["il"]["outcome"] == "moved" and got["outcome"] == "claimed"
    assert placed(client) == []
    cancels = client.get(f"/seasons/{LEAGUE}/autopilot/cancels").json()
    assert cancels["cancels"] == []


def test_a_placed_claims_il_move_that_fails_has_its_cancel_due_in_the_same_pass(client):
    queued(client)
    k, _ = a_player(client)
    e = earlier_claim(client, 9001, k)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    live_league(client)
    failed = il_body(e["id"], k, mode="live", outcome="failed", reason="not saved")
    assert client.post(IL, json=failed).status_code == 200
    [c] = client.get(f"/seasons/{LEAGUE}/autopilot/cancels").json()["cancels"]
    assert (c["entry"], c["reason"]) == (e["id"], ap.IL_FAILED)
    assert placed(client) == []
    # Never retried that day, and another move than the claim's is refused.
    r = client.post(IL, json={**failed, "outcome": "moved"})
    assert r.status_code == 409 and "never retried that day" in r.json()["detail"]
    r = client.post(IL, json=il_body(e["id"], k + 1, mode="live", outcome="moved"))
    assert r.status_code == 409 and "another IL move" in r.json()["detail"]


def test_the_build_writes_the_il_need_on_the_claim_and_takes_it_off_once_none_is_needed(
    client, monkeypatch
):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    base = {"league": LEAGUE, "outcome": "claimed", "resolved": None, "from": "2026-10-22"}
    a = {**base, "id": f"2026-10-20:{LEAGUE}:9001:0", "add": 9001, "drop": None}
    (folder / "2026-10-20.json").write_text(json.dumps({"entries": [a]}))
    j = {"judged": "three", "value": None, "season_costly": None, "comeback_drops": {}}
    need = {"player": 6406, "slot": "IL"}
    monkeypatch.setattr(
        season_moves,
        "rejudge_claims",
        lambda built, claims, statuses: {a["id"]: {**j, "gain": 0.4, "il_need": need}},
    )
    monkeypatch.setattr(mv, "overfull", lambda p: 1)
    queued(client)
    [e] = json.loads((folder / "2026-10-20.json").read_text())["entries"]
    assert {k: e["il_need"][k] for k in ("player", "slot")} == need and e["il_need"]["at"]
    assert (e.get("rejudge") or {}).get("verdict") is None  # Q2 (a): no verdict for the room
    # The next build finds the room open (the move made, or a spot freed): the need goes.
    monkeypatch.setattr(mv, "overfull", lambda p: 0)
    client.post("/autopilot/queue/build")
    [e] = json.loads((folder / "2026-10-20.json").read_text())["entries"]
    assert "il_need" not in e


def test_a_claim_to_an_unheld_player_is_never_owed_a_move():
    # A claim's add on the way is never the player a held slot takes (#360).
    p, _ = il_league(spots=3)
    hurt = mv.Pending(10, Player(10, "P10", "STR", ("C",), status="O"), None, CLEAR)
    q = folded(p, [hurt])
    assert q.il_owed == ((OUT, "IL"),)


# --------------------------------------------------------------------------- the evening pass
def test_the_evening_pass_makes_the_placed_claims_il_moves_before_its_cancels(tmp_path):
    team = f"{YAHOO}/nba/252098/2?date=2026-11-10"
    placed_item = {"entry": "p1", "player": 7, "slot": "IL", "date": "2026-11-10", "page": team}
    answers = due_answers()
    route = ("GET", "/seasons/252098/autopilot/moves/due")
    code, body = answers[route]
    answers[route] = (code, {**body, "il_first": [{**placed_item, "placed": True}]})
    answers[("GET", ALL)] = (
        200,
        {"leagues": [{"league": "252098", "page": PAGE, "cancels": ["a"]}]},
    )
    clock = Clock("2026-11-10 22:40")
    browser = FakeBrowser(clock=clock)
    ctx = make_ctx(FakeAPI(answers), clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    names = [s.name for s in report.steps]
    assert names.index("placed_il") < names.index("cancel") < names.index("moves")
    urls = [u for u, _ in browser.opened]
    assert urls[0] == f"{team}#pickandroll-il-evening" and urls[1].endswith(ap.CANCEL_FRAGMENT)
    # A placed claim's IL move has no add page after it, and is no reason a page is missing.
    plan = moves_plan(ctx, ["252098"], "pickandroll-moves", "pickandroll-il")
    [il] = [o for o in plan.openings if o.entry == "p1"]
    assert il.then is None and "252098:p1" not in plan.reasons
    # With nothing to do the steps say what they found.
    answers[route] = (code, body)
    answers[("GET", ALL)] = (200, {"leagues": [], "reason": "no claim to cancel"})
    ctx = make_ctx(FakeAPI(answers), clock, tmp_path, routine="evening-pass", browser=browser)
    report = run("evening-pass", ctx, "http://api")
    assert report.find("placed_il").detail == "no placed claim needs an IL move"
    assert report.find("cancel").detail == "no claim to cancel"
