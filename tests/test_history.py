"""The History screen's record (#334): the join of the week records, the snapshot, the queue's day
files, the run logs and the decision log, and ``GET /history``. Every value is made up; the trade
is a fixture, since no trade has been seen live."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_decisions, season_queue, season_scorecard
from pickandroll.api import season_record as rec
from pickandroll.api.seasons import season_dir
from pickandroll.season import decisions as dl
from pickandroll.season import history as hs
from pickandroll.season.state import Player, Transaction
from tests.test_season import LEAGUE, season_client

PRIVATE = "100002"
ME = 4
MINE = "Fixture Team"
TODAY = date(2026, 11, 6)
ZONE = season_decisions.TRANSACTIONS_TZ
OTHER = 9
NO_RUNS = hs.Runs()


def tx(
    kind: str,
    player: int,
    when: str,
    group: int,
    team: int | None = ME,
    detail: str | None = None,
) -> Transaction:
    words = detail if detail is not None else {"add": "$3 Waiver", "drop": "To Waivers"}.get(kind)
    return Transaction(kind, Player(player, f"P{player}"), team, None, words, when, group)


def queued(add: int, drop: int | None, day: str = "2026-11-02", **over: Any) -> dict[str, Any]:
    return {
        "id": f"{day}:{LEAGUE}:{add}:{drop}",
        "date": day,
        "league": LEAGUE,
        "set": "three",
        "decision": f"e-{add}",
        "add": add,
        "drop": drop,
        "availability": "W",
        "judged": "three",
        "gain": 0.4,
        "season": 1.5,
        "plan": None,
        "bid": {"amount": 3, "reason": "$3: over the typical gain"},
        "claim": None,
        "outcome": "claimed",
        "outcome_at": f"{day}T12:00:00+00:00",
        "resolved": None,
        **over,
    }


def entry(add: int, drop: int | None, at: str = "2026-11-02T10:00:00+00:00", **over: Any) -> dict:
    move = {
        "add": add,
        "drop": drop,
        "gain": {"week": 0.2, "three": 0.4},
        "value": {"three": 1.0},
        "season_costly": False,
    }
    return {
        "id": f"e-{add}",
        "at": at,
        "sets": [
            {
                "key": over.get("key", "three"),
                "moves": [move],
                "week": {"after": {"matchup": 0.61, "expected": 5.2}},
            }
        ],
    }


def rows(
    transactions: list[Transaction] = (),  # type: ignore[assignment]
    queue: list[dict[str, Any]] = (),  # type: ignore[assignment]
    entries: list[dict[str, Any]] = (),  # type: ignore[assignment]
    runs: hs.Runs = NO_RUNS,
    me: int | None = ME,
    settled_by: date | None = None,
) -> list[dict[str, Any]]:
    return hs.rows_of(
        LEAGUE,
        me,
        MINE,
        transactions,
        queue,
        entries,
        runs,
        season_scorecard.logged_move,
        TODAY,
        ZONE,
        settled_by,
    )


# --------------------------------------------------------------------------- the transactions
def test_a_group_on_a_week_record_and_the_snapshot_is_one_group():
    both = [tx("add", 1, "Nov 2, 4:00 am", 0), tx("drop", 2, "Nov 2, 4:00 am", 0)]
    only_week = [tx("add", 3, "Oct 27, 4:00 am", 0)]
    # The same group, numbered otherwise on the page read later.
    snapshot = [
        tx("add", 5, "Nov 3, 4:00 am", 0),
        tx("drop", 2, "Nov 2, 4:00 am", 1),
        tx("add", 1, "Nov 2, 4:00 am", 1),
    ]
    week = [t.to_dict() for t in [*only_week, *[_at(t, 1) for t in both]]]
    merged = hs.merged([week], snapshot)
    assert sorted(t.player.yahoo_id for t in merged) == [1, 2, 3, 5]
    groups = {t.player.yahoo_id: t.group for t in merged}
    assert groups[1] == groups[2] and len(set(groups.values())) == 3
    assert [(r["add"], r["drop"]) for r in rows(merged)] == [(5, None), (1, 2), (3, None)]


def _at(t: Transaction, group: int) -> Transaction:
    return Transaction(t.kind, t.player, t.team_id, t.team_name, t.detail, t.when, group)


# --------------------------------------------------------------------------- the queue's rows
def test_a_placed_claim_that_landed_says_where_it_came_from_and_how_it_was_bid():
    got = rows(
        [tx("add", 1, "Nov 3, 3:30 am", 0), tx("drop", 2, "Nov 3, 3:30 am", 0)],
        [queued(1, 2, resolved="won")],
        [entry(1, 2)],
    )
    assert len(got) == 1
    r = got[0]
    assert (r["date"], r["kind"], r["add"], r["drop"]) == ("2026-11-03", hs.CLAIM, 1, 2)
    assert (r["result"], r["who"], r["bid"]) == (hs.WON, hs.THE_QUEUE, 3)
    assert r["why"] == {
        "set": "three",
        "step": None,
        "steps_of": None,
        "week": 0.2,
        "three": 0.4,
        "season": 1.5,
        "matchup": 0.61,
        "against": None,
        "bid_reason": "$3: over the typical gain",
    }


def test_a_week_plans_step_keeps_its_step_and_the_plans_size():
    plan = {"id": "p", "step": 2, "steps": 3, "matchup": 0.7, "against": 0.6}
    r = rows(
        [tx("add", 1, "Nov 3, 3:30 am", 0)],
        [queued(1, None, set="week_plan", judged="week", plan=plan, gain=0.3, three=-0.1)],
    )[0]
    w = r["why"]
    assert (w["set"], w["step"], w["steps_of"]) == ("week_plan", 2, 3)
    assert (w["week"], w["three"], w["matchup"], w["against"]) == (0.3, -0.1, 0.7, 0.6)


def test_a_free_agent_add_lands_and_carries_no_bid():
    r = rows(
        [tx("add", 1, "Nov 2, 9:00 pm", 0, detail="Free Agent")],
        [queued(1, None, availability="FA", outcome="added", resolved="won")],
    )[0]
    assert (r["kind"], r["result"], r["bid"]) == (hs.FREE_AGENT, hs.LANDED, None)


@pytest.mark.parametrize("result", [hs.LOST, hs.LAPSED])
def test_a_claim_that_never_landed_is_a_row_of_its_own(result):
    got = rows([], [queued(1, 2, resolved=result)], [entry(1, 2)])
    assert [(r["add"], r["drop"], r["result"], r["who"]) for r in got] == [
        (1, 2, result, hs.THE_QUEUE)
    ]


def test_a_claim_lost_and_placed_again_leaves_the_add_to_the_second():
    got = rows(
        [tx("add", 1, "Nov 4, 3:30 am", 0)],
        [queued(1, 2, resolved="lost"), queued(1, 2, day="2026-11-03", resolved="won")],
    )
    assert [(r["date"], r["result"]) for r in got] == [
        ("2026-11-04", hs.WON),
        ("2026-11-02", hs.LOST),
    ]


def test_a_claim_nothing_settled_is_pending_until_the_queue_stops_looking():
    claim = queued(1, 2)
    assert rows([], [claim])[0]["result"] == hs.PENDING
    assert rows([], [claim], settled_by=date(2026, 11, 2))[0]["result"] == hs.PENDING
    assert rows([], [claim], settled_by=date(2026, 11, 3))[0]["result"] == hs.LAPSED


def test_a_move_the_queue_never_placed_is_no_row():
    assert rows([], [queued(1, 2, outcome="skipped"), queued(3, 4, outcome="would_claim")]) == []


# --------------------------------------------------------------------------- moves by hand
AS_LOGGED = [entry(1, 2, "2026-11-02T01:00:00+00:00", key="three")]


@pytest.mark.parametrize(
    ("add", "drop", "kind", "move"),
    [
        (1, 2, dl.AS_RECOMMENDED, {"add": 1, "drop": 2}),
        (1, 7, dl.DIFFERENTLY, {"add": 1, "drop": 2}),
        (8, 2, dl.DIFFERENTLY, {"add": 1, "drop": 2}),
        (8, 7, dl.NOT_RECOMMENDED, None),
    ],
)
def test_a_move_by_hand_is_compared_with_the_latest_recommendation(add, drop, kind, move):
    got = rows(
        [tx("add", add, "Nov 2, 9:00 am", 0), tx("drop", drop, "Nov 2, 9:00 am", 0)],
        entries=AS_LOGGED,
    )
    r = got[0]
    assert (r["result"], r["who"], r["why"]["match"], r["why"]["move"]) == (
        hs.BY_HAND,
        hs.THE_USER,
        kind,
        move,
    )
    if move is None:
        assert r["why"]["week"] is None and r["why"]["three"] is None
    else:
        assert (r["why"]["set"], r["why"]["week"], r["why"]["three"]) == ("three", 0.2, 0.4)


def test_a_lone_drop_by_hand_is_a_drop():
    r = rows([tx("drop", 2, "Nov 2, 9:00 am", 0)], entries=AS_LOGGED)[0]
    assert (r["kind"], r["add"], r["drop"], r["result"]) == (hs.DROP, None, 2, hs.BY_HAND)


def test_a_move_with_no_recommendation_says_so_plainly():
    early = rows([tx("add", 1, "Oct 22, 9:00 am", 0)])[0]
    assert early["why"] == {"match": dl.NO_ENTRY, "note": hs.NO_RECORD}
    late = rows([tx("add", 1, "Nov 2, 9:00 am", 0)])[0]
    assert late["why"] == {"match": dl.NO_ENTRY, "note": hs.NO_ENTRY}
    assert "Moves before 2026-10-24 have no queue record"[1:] in hs.NO_RECORD


def test_another_teams_moves_are_not_mine_and_a_league_with_no_team_has_none():
    theirs = [tx("add", 1, "Nov 2, 9:00 am", 0, team=OTHER)]
    assert rows(theirs) == []
    assert rows([tx("add", 1, "Nov 2, 9:00 am", 0)], me=None) == []


# --------------------------------------------------------------------------- the chains
def comeback(returned: str = "set") -> hs.Runs:
    entry_id = ap.comeback_entry(5)
    return hs.Runs(
        drops=[
            {
                "at": "2026-11-05T14:00:00+00:00",
                "outcome": "dropped",
                "entry": entry_id,
                "player": 6,
                "message": "dropped",
            }
        ],
        returns=[
            {
                "kind": "return",
                "player": 5,
                "drop": 6,
                "outcome": "failed",
                "at": "2026-11-05T13:00:00+00:00",
                "message": "over the max roster size",
            },
            {
                "kind": "return",
                "player": 5,
                "drop": 6,
                "outcome": returned,
                "at": "2026-11-05T15:00:00+00:00",
            },
        ],
    )


def test_a_comeback_chain_is_one_row_with_its_need_and_each_step():
    got = rows([tx("drop", 6, "Nov 5, 9:00 am", 0)], runs=comeback())
    assert len(got) == 1
    r = got[0]
    assert (r["kind"], r["player"], r["drop"]) == (hs.COMEBACK, 5, 6)
    assert (r["result"], r["who"]) == (hs.LANDED, hs.THE_COMEBACK)
    assert r["why"]["need"] == hs.COMEBACK_NEED
    assert [(s["stage"], s["outcome"]) for s in r["why"]["steps"]] == [
        ("move", "failed"),
        ("drop", "dropped"),
        ("move", "set"),
    ]


def test_a_comeback_stopped_after_its_drop_says_so():
    r = rows([tx("drop", 6, "Nov 5, 9:00 am", 0)], runs=comeback("failed"))[0]
    assert r["result"] == hs.PARTIAL


def test_a_comeback_that_moved_nobody_is_no_row():
    runs = hs.Runs(returns=[{"kind": "return", "player": 5, "drop": 6, "outcome": "failed"}])
    assert rows(runs=runs) == []


def test_an_il_move_says_which_claim_it_opened_the_spot_for():
    claim = queued(1, None, resolved="won", id="c")
    run = {
        "day": "2026-11-02",
        "at": "2026-11-02T15:00:00+00:00",
        "outcome": "moved",
        "entry": "c",
        "player": 7,
        "from_slot": "BN",
        "to_slot": "IL",
        "message": "All changes saved",
    }
    failed = {**run, "outcome": "failed", "player": 8}
    got = rows([tx("add", 1, "Nov 3, 3:30 am", 0)], [claim], runs=hs.Runs(il=[run, failed]))
    il = [r for r in got if r["kind"] == hs.IL]
    assert len(il) == 1 and il[0]["player"] == 7
    assert il[0]["why"]["need"] == {"for": 1, "slot": "IL"}
    assert [(s["stage"], s["outcome"]) for s in il[0]["why"]["steps"]] == [
        ("IL move", "moved"),
        ("claim", "won"),
    ]


def test_a_churns_held_drop_sits_under_its_claim():
    claim = queued(1, 2, resolved="won", id="c")
    run = {
        "day": "2026-11-02",
        "at": "2026-11-02T15:00:00+00:00",
        "outcome": "dropped",
        "entry": "c",
        "player": 2,
    }
    got = rows(
        [tx("drop", 2, "Nov 2, 10:00 am", 0), tx("add", 1, "Nov 3, 3:30 am", 1)],
        [claim],
        [entry(1, 2)],
        hs.Runs(drops=[run]),
    )
    assert [(r["kind"], r["add"], r["drop"], r["who"]) for r in got] == [
        (hs.CLAIM, 1, None, hs.THE_QUEUE),
        (hs.DROP, None, 2, hs.THE_QUEUE),
    ]
    assert got[1]["why"]["set"] == "three"


# --------------------------------------------------------------------------- the trades
def test_a_trade_is_a_row_with_its_sides_and_says_why_is_not_logged():
    got = rows(
        [
            tx("trade", 1, "Nov 2, 9:00 am", 0, detail=f"Traded to {MINE}"),
            tx("trade", 2, "Nov 2, 9:00 am", 0, detail="Traded to Their Team"),
        ]
    )
    assert len(got) == 1
    r = got[0]
    assert (r["kind"], r["unread"], r["who"]) == (hs.TRADE, False, hs.THE_USER)
    assert [(s["player"], s["side"]) for s in r["sides"]] == [(1, "got"), (2, "gave")]
    assert r["why"] == {"note": hs.TRADE_WHY}


def test_a_trade_on_my_teams_link_is_mine_however_the_words_read():
    r = rows([tx("trade", 1, "Nov 2, 9:00 am", 0, detail="Trade")])[0]
    assert (r["unread"], r["sides"][0]["side"]) == (False, None)


@pytest.mark.parametrize("team", [None, OTHER])
def test_a_trade_the_page_cannot_place_is_an_unread_trade_rather_than_nothing(team):
    r = rows([tx("trade", 1, "Nov 2, 9:00 am", 0, team=team, detail="")])[0]
    assert (r["kind"], r["unread"], r["who"]) == (hs.TRADE, True, None)
    assert r["why"] == {"note": hs.UNREAD_TRADE}


def test_two_other_teams_trade_is_not_listed():
    theirs = [tx("trade", 1, "Nov 2, 9:00 am", 0, team=OTHER, detail="Traded to Their Team")]
    assert rows(theirs) == []


def test_a_trade_is_never_taken_for_a_move():
    got = rows([tx("trade", 1, "Nov 2, 9:00 am", 0, detail="Trade")])
    assert [r["who"] for r in got] == [hs.THE_USER]
    assert (
        dl.moves_made([tx("trade", 1, "Nov 2, 9:00 am", 0, detail="Trade")], ME, TODAY, ZONE) == []
    )


# --------------------------------------------------------------------------- the order
def test_rows_are_newest_first_across_the_pages_clock_and_the_queues():
    late = queued(1, None, day="2026-11-03", resolved="lost")
    late["outcome_at"] = "2026-11-03T23:00:00+00:00"
    got = rows([tx("add", 2, "Nov 3, 9:00 pm", 0)], [late])
    # 9 pm Eastern is after 23:00 UTC, though it sorts first as a string of its own zone.
    assert [r["add"] for r in got] == [2, 1]


# --------------------------------------------------------------------------- GET /history
@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def seed(client) -> None:
    """The fixture league's snapshot, a week record, a queue day and a run log, written as the
    routine would."""
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    client.post(f"/seasons/{PRIVATE}/refresh", params={"wait": True})
    folder = season_dir(client.data_dir, LEAGUE)
    rec.write_record(
        folder,
        {
            "week": 1,
            "transactions": [
                {**tx("add", 900001, "Oct 20, 9:00 am", 40).to_dict(), "day": "2026-10-20"},
            ],
        },
    )
    season_queue._write(
        season_queue.queue_path(client.data_dir, date(2026, 10, 20)),
        {
            "date": "2026-10-20",
            "entries": [
                queued(900002, None, day="2026-10-20", resolved="lost"),
                queued(900003, None, day="2026-10-20", league=PRIVATE, resolved="lost"),
            ],
        },
    )


def test_the_route_joins_every_league_the_private_one_too(client):
    seed(client)
    r = client.get("/history")
    assert r.status_code == 200
    body = r.json()
    assert body["kinds"] == list(hs.KINDS) and body["results"] == list(hs.RESULTS)
    assert body["skipped"] == []
    by_add = {x["add"]: x for x in body["rows"]}
    assert by_add[900001]["league"] == LEAGUE and by_add[900001]["result"] == hs.BY_HAND
    assert by_add[900002]["result"] == hs.LOST
    assert by_add[900003]["league"] == PRIVATE
    assert body["names"]["900001"] == "P900001"
    dates = [x["date"] for x in body["rows"]]
    assert dates == sorted(dates, reverse=True)


def test_the_route_filters_on_league_and_dates(client):
    seed(client)
    only = client.get("/history", params={"league": PRIVATE}).json()["rows"]
    assert only and {x["league"] for x in only} == {PRIVATE}
    day = client.get("/history", params={"from": "2026-10-20", "to": "2026-10-20"}).json()["rows"]
    assert {x["date"] for x in day} == {"2026-10-20"}
    assert 900001 in {x["add"] for x in day}
    assert client.get("/history", params={"to": "2026-10-19"}).json()["rows"] == []
    assert client.get("/history", params={"from": "nonsense"}).status_code == 422


def test_a_league_that_does_not_read_leaves_the_others(client):
    seed(client)
    (client.data_dir / "leagues" / PRIVATE / "settings.json").write_text("{")
    body = client.get("/history").json()
    assert [s["league"] for s in body["skipped"]] == [PRIVATE]
    assert any(x["league"] == LEAGUE for x in body["rows"])


def test_the_route_writes_nothing(client):
    seed(client)
    before = _files(client.data_dir)
    client.get("/history")
    assert _files(client.data_dir) == before


def _files(root) -> dict[str, float]:
    return {str(p): p.stat().st_mtime for p in root.rglob("*") if p.is_file()}


def test_the_lineup_log_gives_a_comebacks_return_only(tmp_path):
    day = datetime(2026, 11, 5, 15, tzinfo=UTC)
    with season_client(tmp_path) as c:
        c.get("/history")
    path = ap.log_dir(tmp_path, LEAGUE)
    path.mkdir(parents=True, exist_ok=True)
    (path / "2026-11-05.json").write_text(
        json.dumps(
            {
                "lineup": [
                    {
                        "mode": "live",
                        "at": day.isoformat(),
                        "steps": [
                            {"kind": "return", "player": 5, "drop": 6, "outcome": "set"},
                            {"kind": "return", "player": 7, "drop": None, "outcome": "set"},
                            {"kind": "bench", "player": 8, "outcome": "set"},
                        ],
                    },
                    {
                        "mode": "dry_run",
                        "at": day.isoformat(),
                        "steps": [{"kind": "return", "player": 9, "drop": 6, "outcome": "set"}],
                    },
                ],
                "drop": [{"mode": "dry_run", "at": day.isoformat(), "player": 6}],
            }
        )
    )
    from pickandroll.api import season_history

    runs = season_history.runs_of(tmp_path, LEAGUE)
    assert [(s["player"], s["at"]) for s in runs.returns] == [(5, day.isoformat())]
    assert runs.drops == [] and runs.il == []
