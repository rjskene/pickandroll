"""Your picks (#434, the user's ruling of 2026-11-19): the players the user names are forced moves
of each league's solve, with the drop the user named or the one that costs least on the queue's
score, the keep rule kept, the season guard and the floor not applied; the queue carries them
first. Every league here is made up (``test_moves``'s, ``test_season_guard``'s and
``test_season``'s fixtures)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from pickandroll.api import season_decisions as sd
from pickandroll.api import season_moves as sm
from pickandroll.api import season_picks as store
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season import picks as pk

from .test_moves import WEEKS, build, player, streaming_league
from .test_moves_queue import DAY, NEXT, PLAN, TYPICAL, WEEK, entry, league_day, move, reasons
from .test_season import LEAGUE, client, fixture_names, projection_csv  # noqa: F401
from .test_season_guard import built_of, drop_clocks, resting_league

OBJECTIVE = sm.plan_value(0.33, False)
LAST = date(2026, 11, 30)


def pick(player_id: int, drop: int | None = None, **kw) -> pk.Pick:
    return pk.Pick(
        player_id, kw.pop("leagues", None), drop, kw.pop("bid", None), LAST, "test", "t", **kw
    )


def moves_of(made: list[pk.Forced]) -> list[mv.Move]:
    return [f.move for f in made]


# --------------------------------------------------------------------------- the solve
def test_a_pick_is_forced_with_the_drop_that_costs_least_and_a_named_drop_is_honoured():
    p = build(*streaming_league())
    # 3 barely plays: the cheapest drop for the streamer (10).
    made, skipped = pk.forced(p, [pick(10)], OBJECTIVE)
    assert moves_of(made) == [mv.Move(10, 3)] and skipped == []
    # The user named 1: honoured, though dropping him costs more.
    assert moves_of(pk.forced(p, [pick(10, 1)], OBJECTIVE)[0]) == [mv.Move(10, 1)]
    # A second pick takes the next cheapest drop, the first one's counted.
    assert moves_of(pk.forced(p, [pick(10), pick(11)], OBJECTIVE)[0]) == [
        mv.Move(10, 3),
        mv.Move(11, 2),
    ]
    # A named drop who is not mine in this league leaves the cheapest one.
    assert moves_of(pk.forced(p, [pick(10, 999)], OBJECTIVE)[0]) == [mv.Move(10, 3)]


def test_the_keep_rule_still_protects_from_a_picks_drop():
    p = replace(build(*streaming_league()), kept=frozenset({3}))
    assert moves_of(pk.forced(p, [pick(10)], OBJECTIVE)[0]) == [mv.Move(10, 2)]
    made, skipped = pk.forced(p, [pick(10, 3)], OBJECTIVE)
    assert made == [] and [(s.pick.player, s.reason) for s in skipped] == [(10, pk.DROP_KEPT)]


def test_a_pick_waits_for_the_next_weeks_adds_when_its_week_has_none():
    roster, cands, rate, sched, opponent, field = streaming_league()
    limits = (mv.AddLimit(WEEKS[0][0], WEEKS[0][6], 0), mv.AddLimit(WEEKS[1][0], WEEKS[1][6], 1))
    # 11 is a claim that clears next Monday; 10 is a free agent this week.
    effective = {10: WEEKS[0][0], 11: WEEKS[1][0]}
    p = build(roster, cands, rate, sched, opponent, field, limits=limits, effective=effective)
    made, skipped = pk.forced(p, [pick(10), pick(11)], OBJECTIVE)
    assert [(s.pick.player, s.reason) for s in skipped] == [(10, pk.NO_ADDS)]
    assert [f.move.add for f in made] == [11]
    # The fold takes next week's one add: the solve has none left to fill there.
    folded = pk.fold(p, made)
    assert [lim.adds for lim in folded.limits] == [0, 0]
    assert 11 in {k for k, _ in folded.roster} and 11 in folded.pending
    assert 11 not in {k for k, _ in folded.candidates}
    assert made[0].move.drop not in {k for k, _ in folded.roster}


def test_a_pick_not_in_the_pool_or_already_claimed_is_skipped():
    p = build(*streaming_league())
    claimed = mv.with_pending(p, [mv.Pending(10, player(10, "STR")[1], 3, WEEKS[0][0])])
    made, skipped = pk.forced(claimed, [pick(10), pick(99)], OBJECTIVE)
    assert made == []
    assert [(s.pick.player, s.reason) for s in skipped] == [
        (10, pk.CLAIMED),
        (99, pk.NOT_AVAILABLE),
    ]


def test_a_pick_leaves_a_league_once_its_player_is_on_a_team_there_and_all_at_its_expiry():
    a, b = pick(10), pick(11, leagues=("200",))
    assert pk.active([a, b], "100", DAY) == [a]
    assert pk.active([a, b], "200", DAY) == [a, b]
    marked = pk.left_in([a, b], "200", [11, 50], DAY)
    assert marked[1].left == {"200": DAY.isoformat()} and marked[0] == a
    assert pk.active(marked, "200", DAY) == [a]
    assert pk.active([a], "100", LAST) == [a] and pk.active([a], "100", date(2026, 12, 1)) == []
    assert pk.expiry(DAY) == date(2026, 10, 28) and pk.expiry(DAY, 2) == date(2026, 10, 23)
    assert pk.Pick.from_dict(marked[1].to_dict()) == marked[1]


# --------------------------------------------------------------------------- the payload
def picked_built(problem: mv.MoveProblem, picks: list[pk.Pick]) -> sm.Built:
    """``built_of`` with ``picks`` made as ``season_moves.build`` makes them."""
    made, skipped = pk.forced(problem, picks, OBJECTIVE)
    folded = pk.fold(problem, made)
    rule = mv.keep_rule(folded)
    folded = replace(folded, kept=rule.kept | folded.pending)
    return built_of(
        folded, picks=tuple(made), skipped_picks=tuple(skipped), unpicked=problem, rule=rule
    )


def test_the_season_guard_never_blocks_a_pick_and_the_solver_fills_around_it():
    p = resting_league()
    ros = sm.guard_ros(built_of(p))
    assert ros is not None and ros(mv.Move(10, 3)) < 0
    built = picked_built(p, [pick(10, 3), pick(77)])
    out = sm._payload(built)
    rows = out["picks"]["moves"]
    assert [(r["add"], r["drop"], r["decided_by"], r["named_drop"]) for r in rows] == [
        (10, 3, "pick", True)
    ]
    # The guard would refuse it; the pick is made anyway, its season cost shown.
    assert rows[0]["ros"]["value"] < 0
    assert set(rows[0]["marginal"]) == {"week", "three"}
    assert rows[0]["score"] == pytest.approx(
        rows[0]["marginal"]["week"] + 0.33 * rows[0]["marginal"]["three"], abs=2e-3
    )
    assert out["picks"]["skipped"] == [
        {
            "player": 77,
            "name": None,
            "reason": pk.NOT_AVAILABLE,
            "expires": "2026-11-30",
            "by": "test",
        }
    ]
    # The solver's sets are solved on the roster with the pick made.
    for key in sm.HORIZONS:
        for m in out["recommended"][key]["moves"]:
            assert m["add"] != 10 and m["drop"] != 3
    assert "10" not in out["candidates"]


def test_no_picks_gives_todays_payload_byte_for_byte():
    p = resting_league()
    plain, empty = sm._payload(built_of(p)), sm._payload(built_of(p, picks=(), skipped_picks=()))
    assert "picks" not in plain
    for out in (plain, empty):
        drop_clocks(out)
    assert json.dumps(plain) == json.dumps(empty)


def test_the_decision_log_records_the_picks_as_their_own_set_after_the_others():
    built = picked_built(resting_league(), [pick(10, 3, bid=7)])
    out = sm._payload(built)
    e = sd.moves_entry(built, out, datetime(2026, 10, 26, 12, tzinfo=UTC))
    assert e["sets"][0]["key"] == "week" and e["sets"][-1]["key"] == pk.PICK
    (m,) = e["sets"][-1]["moves"]
    assert (m["add"], m["drop"], m["decided_by"], m["bid"]) == (10, 3, "pick", 7)
    assert m["value"] is not None and m["basis"] == "drop" and "score" in m
    assert e["picks"] == {"skipped": []}
    at = datetime(2026, 10, 26, 12, tzinfo=UTC)
    plain = sd.moves_entry(built_of(resting_league()), sm._payload(built_of(resting_league())), at)
    assert "picks" not in plain and all(s["key"] != pk.PICK for s in plain["sets"])


# --------------------------------------------------------------------------- the queue
def with_picks(e, *moves):
    return {**e, "sets": [*e["sets"], {"key": pk.PICK, "moves": list(moves), "held": []}]}


def picked(add, drop, gain=0.001, bid=None, frm="2026-10-22", score=None):
    return {
        **move(add, drop, gain, frm=frm, costly=True),
        "bid": bid,
        "decided_by": "pick",
        "score": score,
    }


def test_the_queue_takes_the_picks_first_with_neither_floor_guard_nor_re_add_rule():
    e = with_picks(entry(move(101, 201, 0.9), move(102, 202, 0.8)), picked(301, 401))
    # 301 gains next to nothing, costs the season and was dropped within the waiver days.
    day = league_day(e, dropped=frozenset({301}))
    out = qa.queue_of(day, DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(301, None, 1), (101, None, 2), (102, qa.OVER_CAP, None)]
    first = out[0]
    assert (first["set"], first["decided_by"], first["judged"]) == ("pick", "pick", "week")
    assert first["floor"]["below"] is None
    # A pick's bid is the policy's on its score when the user set none: $0 for a routine gain.
    assert first["bid"]["amount"] == 0


def test_a_picks_bid_is_the_users_clamped_to_the_budget_and_a_free_agent_bids_nothing():
    e = with_picks(
        entry(), picked(301, 401, bid=12), picked(302, 402, bid=500), picked(303, None, bid=9)
    )
    day = league_day(e, cap=5, budget=40.0, availability={303: ("FA", None)})
    out = {x["add"]: x["bid"] for x in qa.queue_of(day, DAY, PLAN, TYPICAL, None)}
    assert out[301]["amount"] == 12 and out[301]["reason"] == "$12: your pick's bid"
    assert out[302]["amount"] == 40 and "clamped to the $40 left" in out[302]["reason"]
    assert out[303]["amount"] == 0
    # The policy's bid on a pick whose score is worth a few typicals.
    e = with_picks(entry(), picked(304, 404, gain=0.4, score=0.3))
    (x,) = qa.queue_of(league_day(e), DAY, PLAN, TYPICAL, None)
    assert x["bid"]["amount"] == 3 and x["score"] == 0.3


def test_a_pick_keeps_the_protected_drop_the_placed_claims_and_the_weeks_adds():
    e = with_picks(
        entry(),
        picked(301, 401),
        picked(302, 402),
        picked(303, 403),
        picked(304, 404, frm="2026-10-27"),
    )
    claims = [{"id": "x", "add": 302, "drop": None, "outcome": "claimed"}]
    day = league_day(
        e, protected={401: "kept"}, open_claims=claims, adds_left={WEEK: 0, NEXT: 1}, cap=5
    )
    assert reasons(qa.queue_of(day, DAY, PLAN, TYPICAL, None)) == [
        (301, qa.PROTECTED, None),
        (302, qa.ALREADY_CLAIMED, None),
        (303, qa.NO_ADDS, None),
        (304, None, 1),
    ]
    # The private league shows them as suggestions, never queued.
    assert reasons(qa.queue_of(league_day(e, private=True), DAY, PLAN, TYPICAL, None))[0] == (
        301,
        qa.PRIVATE,
        None,
    )


# --------------------------------------------------------------------------- the store
def test_the_store_sets_replaces_removes_and_marks_a_league_left(tmp_path):
    assert store.load(tmp_path) == [] and store.in_force(tmp_path, "1", DAY) == []
    store.set_pick(tmp_path, 10, "A", None, None, None, LAST, "dashboard")
    store.set_pick(tmp_path, 11, "B", ["2"], 3, 5, LAST, "master")
    store.set_pick(tmp_path, 10, "A", ["1"], None, 4, LAST, "dashboard")
    got = {p.player: p for p in store.load(tmp_path)}
    assert got[10].leagues == ("1",) and got[10].bid == 4 and got[11].by == "master"
    assert [p.player for p in store.in_force(tmp_path, "2", DAY)] == [11]
    assert store.mark_left(tmp_path, "2", [11], DAY) == []
    left = {p.player: p.left for p in store.load(tmp_path)}
    assert left == {10: {}, 11: {"2": DAY.isoformat()}}
    assert store.remove(tmp_path, 11) and not store.remove(tmp_path, 11)
    store.path_of(tmp_path).write_text("not json")
    assert store.in_force(tmp_path, "1", DAY) == []
    with pytest.raises(store.PicksError):
        store.load(tmp_path)


def test_a_pick_set_by_name_is_made_in_the_moves_and_removed_again(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    before = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert "picks" not in before
    brooks = next(a for a in v["available"] if a["player"]["name"] == "Dillon Brooks")
    pid = brooks["player"]["yahoo_id"]
    r = client.put("/autopilot/picks", json={"name": "dillon brooks", "bid": 3})
    assert r.status_code == 200, r.text
    (row,) = r.json()["picks"]
    assert (row["player"], row["name"], row["bid"], row["expires"]) == (
        pid,
        "Dillon Brooks",
        3,
        "2026-10-28",
    )
    assert row["by"] == "dashboard" and row["active"] is True
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    (made,) = m["picks"]["moves"]
    assert made["add"] == pid and made["decided_by"] == "pick" and made["bid"] == 3
    assert made["from"] == brooks["clears"]
    assert str(pid) not in m["candidates"]
    assert all(x["add"] != pid for k in sm.HORIZONS for x in m["recommended"][k]["moves"])
    assert client.put("/autopilot/picks", json={"name": "Nobody Atall"}).status_code == 422
    assert client.put("/autopilot/picks", json={}).status_code == 422
    assert client.delete(f"/autopilot/picks/{pid}").json() == {"picks": [], "days": pk.DAYS}
    assert client.delete(f"/autopilot/picks/{pid}").status_code == 404
    after = client.get(f"/seasons/{LEAGUE}/moves").json()
    for out in (before, after):
        drop_clocks(out)
    assert after == before


def test_a_pick_on_a_rostered_player_leaves_that_league(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    v = client.get(f"/seasons/{LEAGUE}").json()
    mine = v["roster"][0]["player"]["yahoo_id"]
    assert client.put("/autopilot/picks", json={"player": mine}).status_code == 200
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert "picks" not in m
    (row,) = client.get("/autopilot/picks").json()["picks"]
    assert row["left"] == {LEAGUE: "2026-10-21"}
