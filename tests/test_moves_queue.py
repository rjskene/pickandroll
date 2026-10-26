"""The moves executor's queue (#171): each armed league's three weeks' set as entries, the reasons a
move is left out in the ruling's order, the noise floor, the bid, the veto window and the day's
rebuild; the store, the routes, the pass log under ``moves``, the live check and the digest's
line. Nothing here clicks anything: the execute pass is the extension's (PR 2).

The pure cases use made-up moves (Yahoo-like ids, dollar figures); the routes run on the season
tests' fixture league, Yahoo faked.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pickandroll.api import leagues, season_queue
from pickandroll.api import season_autopilot as ap
from pickandroll.season import autopilot as qa
from pickandroll.season.state import Player, Transaction
from tests.test_season import LEAGUE, NOW, season_client, strategy_league, write_folder

PRIVATE = "100002"
#: A points league: the landing hides it, the Queue screen's one switch does not (#205).
POINTS = "100003"
DAY = date(2026, 10, 21)
WEEK = (date(2026, 10, 19), date(2026, 10, 25))
NEXT = (date(2026, 10, 26), date(2026, 11, 1))
TYPICAL = (0.1, "the plan floor until 10 moves")


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


# --------------------------------------------------------------------------- the bid
def test_the_bid_is_the_gain_over_the_typical_times_the_flag_and_the_sizing():
    assert qa.bid_of(0.12, TYPICAL, 100, None, None, "W").amount == 1
    assert qa.bid_of(0.12, TYPICAL, 100, None, None, "W").reason == "$1: a routine stream"
    # Rounded half up, never below a dollar.
    assert qa.bid_of(0.25, TYPICAL, 100, None, None, "W").amount == 3
    assert qa.bid_of(0.01, TYPICAL, 100, None, None, "W").amount == 1
    # Doubled for a breakout flag, tripled for a strong one; a player only watched is routine.
    assert qa.bid_of(0.3, TYPICAL, 100, "add", None, "W").amount == 6
    assert qa.bid_of(0.3, TYPICAL, 100, "must-add", None, "W").amount == 9
    assert qa.bid_of(0.3, TYPICAL, 100, "watch", None, "W").amount == 3
    bid = qa.bid_of(0.3, TYPICAL, 100, "must-add", 0.5, "W")
    assert (bid.amount, bid.base, bid.factor, bid.sizing) == (5, 3, 3, 0.5)
    assert bid.reason == (
        "$5: gain 3x the typical (the plan floor until 10 moves), x3 for a strong breakout flag,"
        " x0.5 FAAB sizing"
    )
    # Clamped to the budget left and nothing else; a free agent is added for $0.
    bid = qa.bid_of(2.0, TYPICAL, 7.6, "add", None, "W")
    assert bid.amount == 7 and bid.reason.endswith(", clamped to the $7 left")
    assert qa.bid_of(0.5, TYPICAL, 0, None, None, "W").amount == 0
    assert qa.bid_of(2.0, TYPICAL, 100, "must-add", None, "FA").amount == 0
    assert qa.bid_of(0.5, TYPICAL, None, None, None, "W").amount == 5


def test_the_typical_gain_is_the_plan_floor_until_ten_moves_then_the_median():
    assert qa.typical_gain([0.5] * 9, 0.1) == TYPICAL
    assert qa.typical_gain([0.2] * 5 + [0.4] * 5, 0.1) == (0.3, "the fortnight's median")


# --------------------------------------------------------------------------- the floor
def test_the_floor_is_the_plan_floor_until_twenty_moves_are_scored_then_both_apply():
    few = qa.noise_floor([1.0, -1.0] * 9, 0.1)
    assert (few.scored, few.moves, few.to_dict()["applies"]) == (None, 18, "plan")
    assert few.below(0.09, 1000.0) == "plan" and few.below(0.1, -5.0) is None
    floor = qa.noise_floor([2.0, -2.0] * 10, 0.1)
    assert floor.scored == pytest.approx(2.052, abs=1e-3) and floor.moves == 20
    assert floor.to_dict()["applies"] == "plan and scored"
    # The scored floor is in the scorer's units, against the move's value; the plan floor still
    # holds whatever the spread.
    assert floor.below(0.2, 1.0) == "scored"
    assert floor.below(0.2, 3.0) is None
    assert floor.below(0.05, 300.0) == "plan"
    assert floor.below(None, 300.0) == "plan" and floor.below(0.2, None) == "scored"


def scored_row(projected: float, realized: float, complete: bool = True, own: bool = True):
    """A scorecard move row, scored on the three weeks after."""
    return {
        "judged": "three",
        "projected": {"set": "three", "value": {"horizons": {"three": {"value": projected}}}},
        "realized": {
            "valued": True,
            "scorer": {"own": own},
            "horizons": {"three": {"value": realized, "complete": complete}},
        },
    }


def test_the_spread_pools_the_public_leagues_scored_moves_by_scoring():
    rows = [scored_row(10.0, 4.0), scored_row(5.0, 9.0), scored_row(1.0, 0.0, complete=False)]
    rows.append(scored_row(1.0, 2.0, own=False))
    payloads = [
        {"league": "900001", "public": True, "weeks": [{"moves": rows}]},
        {"league": "900002", "public": True, "weeks": [{"moves": [scored_row(2.0, 1.0)]}]},
        {"league": "900003", "public": False, "weeks": [{"moves": [scored_row(9.0, 0.0)]}]},
    ]
    scoring = {"900001": "categories", "900002": "points", "900003": "categories"}
    # Only the scored moves whose horizon is over; the private league is never pooled.
    assert season_queue.scored_differences(payloads, scoring) == {
        "categories": [-6.0, 4.0],
        "points": [-1.0],
    }


# --------------------------------------------------------------------------- the entries
def move(add, drop, gain, value=None, season=1.0, costly=False, frm="2026-10-22"):
    value = gain * 1000 if value is None else value
    return {
        "add": add,
        "drop": drop,
        "from": frm,
        "bid": None,
        "gain": {"week": gain / 2, "three": gain},
        "value": {"horizons": {"three": {"value": value}, "season": {"value": season}}},
        "season_costly": costly,
    }


def entry(*moves, week=()):
    return {
        "id": "20261021T120000000000-moves-bbm",
        "at": "2026-10-21T12:00:00+00:00",
        "source": "moves",
        "system": {"key": "bbm"},
        "knobs": {"daily_cap": 2, "plan_floor_cats": 0.1, "faab_sizing": None},
        "sets": [
            {"key": "week", "moves": list(week)},
            {"key": "three", "moves": list(moves), "held": [{"player": 7001, "slot": "IL"}]},
        ],
    }


def league_day(e, **over):
    base = {
        "league": "900001",
        "scoring": "categories",
        "entry": e,
        "mode": "dry_run",
        "private": False,
        "protected": {},
        "availability": {},
        "flags": {},
        "dropped": frozenset(),
        "budget": 100.0,
        "cap": 2,
        "adds_left": {WEEK: 4, NEXT: 4},
    }
    return qa.LeagueDay(**{**base, **over})


PLAN = qa.noise_floor([], 0.1)


def reasons(entries):
    return [(e["add"], e["reason"], e["rank"]) for e in entries]


def test_the_queue_takes_the_three_weeks_set_and_leaves_moves_out_in_the_rulings_order():
    e = entry(
        move(101, 201, 0.9),
        move(102, 202, 0.8, costly=True),  # the drop protected too: protected comes first
        move(103, 203, 0.7, costly=True),
        move(104, None, 0.6),  # dropped within the waiver days
        move(105, 205, 0.05),  # below the plan floor
        move(106, 206, 0.5),
        move(107, 207, 0.4),  # the cap of two is reached
        week=[move(901, 902, 5.0)],
    )
    day = league_day(e, protected={202: "kept"}, dropped=frozenset({104}), flags={101: "add"})
    out = qa.queue_of(day, DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [
        (101, None, 1),
        (102, qa.PROTECTED, None),
        (103, qa.SEASON_COSTLY, None),
        (104, qa.READD, None),
        (106, None, 2),
        (107, qa.OVER_CAP, None),
        (105, qa.BELOW_FLOOR, None),
    ]
    first = out[0]
    # The week set's move is not the queue's; each entry records its set, its decision and the
    # knobs in force, its bid, its floor, the IL moves its set implies.
    assert first["id"] == "2026-10-21:900001:101:201" and first["set"] == "three"
    assert first["decision"] == e["id"] and first["knobs"] == e["knobs"]
    assert first["bid"]["amount"] == 18 and first["flag"] == "add"
    assert first["floor"] == {**PLAN.to_dict(), "below": None}
    assert first["held"] == [{"player": 7001, "slot": "IL"}]
    assert (first["gain"], first["value"], first["season"]) == (0.9, 900.0, 1.0)
    assert out[-1]["floor"]["below"] == "plan"
    assert out[3]["id"] == "2026-10-21:900001:104:0"


def test_a_week_with_no_adds_left_queues_nothing_that_clears_in_it():
    e = entry(move(101, 201, 0.9), move(102, 202, 0.8), move(103, 203, 0.7, frm="2026-10-26"))
    out = qa.queue_of(league_day(e, adds_left={WEEK: 1, NEXT: 4}, cap=3), DAY, PLAN, TYPICAL, None)
    assert reasons(out) == [(101, None, 1), (102, qa.NO_ADDS, None), (103, None, 2)]
    # No limit read: None.
    out = qa.queue_of(league_day(e, adds_left={WEEK: None}, cap=3), DAY, PLAN, TYPICAL, None)
    assert [x["queued"] for x in out] == [True, True, True]


def test_the_private_league_and_an_off_league_queue_nothing():
    e = entry(move(101, 201, 0.9))
    assert reasons(qa.queue_of(league_day(e, private=True), DAY, PLAN, TYPICAL, None)) == [
        (101, qa.PRIVATE, None)
    ]
    assert reasons(qa.queue_of(league_day(e, mode="off"), DAY, PLAN, TYPICAL, None)) == [
        (101, qa.OFF, None)
    ]


def test_a_rebuild_keeps_struck_and_executed_entries_and_a_new_entry_gets_its_full_hour():
    e = entry(move(101, 201, 0.9), move(102, 202, 0.8), move(103, 203, 0.7))
    early = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)  # 05:00 Central
    first = qa.merge([], qa.queue_of(league_day(e), DAY, PLAN, TYPICAL, None), DAY, "09:00", early)
    nine = "2026-10-21T14:00:00+00:00"  # 09:00 Central (#193)
    assert [(x["add"], x["queued"], x["executes_at"]) for x in first] == [
        (101, True, nine),
        (102, True, nine),
        (103, False, None),
    ]
    # The user strikes the first; a rebuild at 08:30 Central keeps it struck, leaves its move
    # out of the build and queues the next with a full window from now.
    first[0]["struck"] = True
    kept = [x for x in first if qa.kept(x)]
    later = datetime(2026, 10, 21, 13, 30, tzinfo=UTC)
    day = league_day(
        e,
        kept=frozenset(x["id"] for x in kept),
        done=sum(1 for x in kept if qa.holds_place(x)),
    )
    again = qa.merge(first, qa.queue_of(day, DAY, PLAN, TYPICAL, None), DAY, "09:00", later)
    by = {x["add"]: x for x in again}
    assert by[101]["struck"] and by[101]["executes_at"] == nine
    assert (by[102]["queued_at"], by[102]["executes_at"]) == (early.isoformat(), nine)
    assert by[103]["queued"] and by[103]["queued_at"] == later.isoformat()
    assert by[103]["executes_at"] == "2026-10-21T14:30:00+00:00"
    # Another execute time later: each not executed is timed again, never sooner than its hour.
    retimed = {x["add"]: x["executes_at"] for x in qa.retime(again, DAY, "08:00")}
    assert retimed[102] == "2026-10-21T13:00:00+00:00"
    assert retimed[103] == "2026-10-21T14:30:00+00:00"


def test_the_default_execute_time_is_07_00_on_the_central_clock_either_side_of_the_dst_change(
    tmp_path,
):
    # #193: 07:00 Central until the user sets another, 12:00 UTC in October (CDT) and 13:00 UTC
    # in December (CST).
    assert (qa.EXECUTE_TIME, qa.EXECUTE_TZ.key) == ("07:00", "America/Chicago")
    assert season_queue.settings(tmp_path) == {
        "execute_time": "07:00",
        "at": None,
        "by": None,
        "set": False,
        "sunday_execute_time": None,
        "sunday_at": None,
        "sunday_by": None,
    }
    early = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)
    assert qa.executes_at(early, DAY) == datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
    winter = date(2026, 12, 1)
    assert qa.executes_at(datetime(2026, 12, 1, 5, 0, tzinfo=UTC), winter) == datetime(
        2026, 12, 1, 13, 0, tzinfo=UTC
    )


def test_a_sunday_execute_time_holds_on_sundays_only():
    # #209: null until the user sets one, and then Sunday's alone.
    sunday, monday = date(2026, 10, 25), date(2026, 10, 26)
    assert qa.day_time(sunday, "09:00", None) == "09:00"
    assert qa.day_time(sunday, "09:00", "22:30") == "22:30"
    assert qa.day_time(monday, "09:00", "22:30") == "09:00"
    # A Sunday entry queued in the morning executes at 22:30 Central (03:30 UTC Monday).
    morning = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)
    at = qa.executes_at(morning, sunday, qa.day_time(sunday, "09:00", "22:30"))
    assert at == datetime(2026, 10, 26, 3, 30, tzinfo=UTC)


def test_a_rebuild_keeps_an_entry_its_solve_no_longer_has_as_superseded():
    # #209: the morning queues 101 and 102; the evening's solve has 102 and 104 instead.
    morning = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    first = qa.merge(
        [],
        qa.queue_of(
            league_day(entry(move(101, 201, 0.9), move(102, 202, 0.8))), DAY, PLAN, TYPICAL, None
        ),
        DAY,
        "09:00",
        morning,
    )
    first.append(
        {**first[0], "id": "x:900001:105:0", "add": 105, "queued": False, "reason": qa.BELOW_FLOOR}
    )
    evening = datetime(2026, 10, 22, 2, 30, tzinfo=UTC)
    new = qa.queue_of(
        league_day(entry(move(102, 202, 0.8), move(104, 204, 0.7))), DAY, PLAN, TYPICAL, None
    )
    again = qa.merge(first, new, DAY, "09:00", evening)
    by = {x["add"]: x for x in again}
    gone = by[101]
    assert (gone["queued"], gone["reason"], gone["rank"], gone["executes_at"]) == (
        False,
        qa.SUPERSEDED,
        None,
        None,
    )
    assert gone["superseded_at"] == evening.isoformat() and gone["queued_at"] == morning.isoformat()
    # It holds no place and is never due; the one kept keeps its time, the new one its hour.
    assert not qa.holds_place(gone)
    assert {x["add"] for x in qa.due(again, evening + timedelta(days=1))} == {102, 104}
    assert by[102]["queued_at"] == morning.isoformat()
    assert by[104]["queued_at"] == evening.isoformat()
    # An entry the morning never queued and the evening does not have is left out, as before.
    assert 105 not in by
    # Superseded again, it keeps its first time; queued again, a new window from that solve.
    later = evening + timedelta(minutes=30)
    third = qa.merge(again, new, DAY, "09:00", later)
    assert {x["add"]: x for x in third}[101]["superseded_at"] == evening.isoformat()
    back = qa.queue_of(league_day(entry(move(101, 201, 0.9))), DAY, PLAN, TYPICAL, None)
    fourth = {x["add"]: x for x in qa.merge(third, back, DAY, "09:00", later)}
    assert fourth[101]["queued"] and fourth[101]["queued_at"] == later.isoformat()
    assert fourth[101]["executes_at"] == (later + qa.WINDOW).isoformat()


def test_the_entries_due_are_the_queued_ones_past_their_window_with_the_bid_to_place():
    e = entry(move(101, 201, 0.3), move(102, 202, 0.2))
    now = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)  # 05:00 Central
    out = qa.merge([], qa.queue_of(league_day(e), DAY, PLAN, TYPICAL, None), DAY, "09:00", now)
    assert qa.due(out, now + timedelta(hours=3)) == []
    out[1]["bid_struck"] = True
    due = qa.due(out, datetime(2026, 10, 21, 14, 0, tzinfo=UTC))
    assert [x["add"] for x in due] == [101, 102]
    assert [qa.effective_bid(x) for x in due] == [3, 0]
    out[0]["struck"], out[1]["outcome"] = True, "would_claim"
    assert qa.due(out, datetime(2026, 10, 21, 17, 0, tzinfo=UTC)) == []


# --------------------------------------------------------------------------- what a build reads
def transaction(kind, player, team, when, group=0):
    return Transaction(
        kind, Player(player, f"Player {player}", "X", ("PG",)), team, None, None, when, group
    )


def league(transactions, waiver_days=2, me=4):
    settings = SimpleNamespace(my_team_id=me, waiver_days=waiver_days)
    return SimpleNamespace(settings=settings, transactions=transactions, teams=())


def test_a_drop_within_the_waiver_days_is_never_added_back():
    s = league(
        [
            transaction("drop", 301, 4, "Oct 20, 3:57 am"),
            transaction("drop", 302, 4, "Oct 18, 3:57 am"),
            transaction("drop", 303, 9, "Oct 21, 1:00 am"),
        ]
    )
    assert season_queue.dropped_recently(s, DAY) == {301}
    assert season_queue.dropped_recently(league(s.transactions, waiver_days=3), DAY) == {301, 302}


def test_a_claim_counts_against_its_week_when_placed_and_resolves_from_the_transactions():
    adds = {"weeks": [{"start": "2026-10-19", "end": "2026-10-25", "adds": 2}]}
    taken = [{"id": "2026-10-20:900001:101:0", "from": "2026-10-21"}, {"id": "x", "from": None}]
    assert season_queue.adds_left(adds, taken) == {WEEK: 1}
    placed = [
        {
            "id": "2026-10-20:900001:101:0",
            "league": "900001",
            "add": 101,
            "outcome": "claimed",
            "resolved": None,
        },
        {
            "id": "2026-10-20:900001:102:0",
            "league": "900001",
            "add": 102,
            "outcome": "claimed",
            "resolved": None,
        },
        {
            "id": "2026-10-20:900001:103:0",
            "league": "900001",
            "add": 103,
            "outcome": "claimed",
            "resolved": None,
        },
        {
            "id": "2026-10-20:900001:104:0",
            "league": "900001",
            "add": 104,
            "outcome": "would_claim",
            "resolved": None,
        },
    ]
    s = league(
        [
            transaction("add", 101, 4, "Oct 21, 4:15 am"),
            transaction("add", 102, 9, "Oct 21, 4:15 am"),
            transaction("add", 103, 4, "Oct 12, 4:15 am"),  # before the claim: another add
            transaction("add", 104, 4, "Oct 21, 4:15 am"),
        ]
    )
    queues = [{"entries": placed}]
    assert [x["add"] for x in season_queue.pending(queues, "900001")] == [101, 102, 103]
    pending = season_queue.pending(queues, "900001")
    assert season_queue.resolutions(s, pending, DAY) == {
        "2026-10-20:900001:101:0": "won",
        "2026-10-20:900001:102:0": "lost",
    }


# --------------------------------------------------------------------------- the routes
def queued(client) -> dict:
    """The fixture league solved and the day's queue built."""
    strategy_league(client)
    assert client.get(f"/seasons/{LEAGUE}/moves").status_code == 200
    r = client.post("/autopilot/queue/build")
    assert r.status_code == 200, r.text
    return r.json()


def three_set(client) -> dict:
    path = client.data_dir / "leagues" / LEAGUE / "season" / "decisions" / "2026-10-21.json"
    [logged] = json.loads(path.read_text())
    return logged, next(s for s in logged["sets"] if s["key"] == "three")


def row_of(q: dict, league: str = LEAGUE) -> dict:
    return next(r for r in q["leagues"] if r["league"] == league)


def test_the_build_reads_the_days_solve_and_never_solves(client):
    strategy_league(client)
    q = client.post("/autopilot/queue/build").json()
    assert row_of(q)["status"] == "not_solved" and row_of(q)["reason"].startswith("not solved")
    assert q["entries"] == []
    # Nothing was solved: the decision log has no entry.
    assert not (client.data_dir / "leagues" / LEAGUE / "season" / "decisions").exists()
    client.get(f"/seasons/{LEAGUE}/moves")
    q = client.post("/autopilot/queue/build").json()
    logged, three = three_set(client)
    row = row_of(q)
    assert row["status"] == "queued" and row["decision"] == logged["id"]
    assert (row["system"], row["cap"], row["cap_from"]) == ("bbm", 2, "the knob")
    assert row["budget"] == 100.0 and row["adds"] == logged["adds"]
    assert row["floor"]["applies"] == "plan" and row["floor"]["plan"] == 0.1
    assert row["typical"] == {"value": 0.1, "from": "the plan floor until 10 moves"}
    # Every move of the three weeks' set is an entry, queued or with its reason, none other.
    assert {(e["add"], e["drop"]) for e in q["entries"]} == {
        (m["add"], m["drop"]) for m in three["moves"]
    }
    assert all(e["set"] == "three" and e["knobs"] == logged["knobs"] for e in q["entries"])
    on = [e for e in q["entries"] if e["queued"]]
    assert [e["rank"] for e in on] == [1, 2] and row["queued"] == 2
    assert all(e["availability"] == "W" and e["bid"]["amount"] >= 1 for e in on)
    # Queued at 13:00 Central, after the day's execute time: a full hour from now.
    assert {e["executes_at"] for e in on} == {(NOW + timedelta(hours=1)).isoformat()}
    assert q["built"] == [NOW.isoformat(), NOW.isoformat()]
    # The private league is never queued.
    assert row_of(q, PRIVATE) == {
        "league": PRIVATE,
        "scoring": "categories",
        "mode": "off",
        "status": "private",
        "reason": qa.PRIVATE,
    }
    # The store holds what the route answered, less each entry's pass read from the logs (#200).
    stored = json.loads((client.data_dir / "autopilot" / "queue" / "2026-10-21.json").read_text())
    answered = [{k: v for k, v in e.items() if k != "pass"} for e in q["entries"]]
    assert stored["entries"] == answered and client.get("/autopilot/queue").json() == q


def test_an_off_league_queues_nothing_and_the_users_cap_replaces_the_knobs(client):
    put = client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert put.status_code == 200 and put.json()["mode"]["mode"] == "off"
    q = queued(client)
    assert row_of(q)["status"] == "off" and q["entries"] == []
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "dry_run", "cap": 1})
    q = client.post("/autopilot/queue/build").json()
    assert (row_of(q)["cap"], row_of(q)["cap_from"]) == (1, "the user")
    assert sum(e["queued"] for e in q["entries"]) == 1
    # The lineup executor's mode beside it is untouched; the private league is refused.
    assert leagues.lineup_mode(client.data_dir, LEAGUE)["mode"] == "dry_run"
    assert client.put(f"/leagues/{PRIVATE}/moves", json={"mode": "dry_run"}).status_code == 409
    assert client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "on"}).status_code == 422


def strike(client, entry_id: str, **body):
    return client.post(f"/autopilot/queue/{entry_id}/strike", json=body)


def test_the_queue_names_every_player_its_entries_mention_from_the_snapshot(client):
    # An empty day names nobody.
    assert client.get("/autopilot/queue").json()["names"] == {}
    q = queued(client)
    ids = {e["add"] for e in q["entries"]} | {
        e["drop"] for e in q["entries"] if e["drop"] is not None
    }
    ids |= {e["held_move"]["player"] for e in q["entries"] if e.get("held_move")}
    v = client.get(f"/seasons/{LEAGUE}").json()
    names = {a["player"]["yahoo_id"]: a["player"]["name"] for a in v["available"]}
    names |= {s["player"]["yahoo_id"]: s["player"]["name"] for s in v["roster"]}
    # Read at request time (#194): every id the entries mention, each by the snapshot's name.
    assert q["names"] == {str(k): names[k] for k in ids}
    assert client.get("/autopilot/queue").json()["names"] == q["names"]
    # The strike's answer is the same payload, names and all.
    assert strike(client, q["entries"][0]["id"]).json()["names"] == q["names"]


def test_the_user_strikes_an_entry_or_its_bid_and_a_rebuild_keeps_it(client):
    q = queued(client)
    first, second, third = q["entries"][:3]
    assert (first["queued"], second["queued"], third["reason"]) == (True, True, qa.OVER_CAP)
    r = strike(client, first["id"])
    assert r.status_code == 200
    struck = next(e for e in r.json()["entries"] if e["id"] == first["id"])
    assert struck["struck"] and struck["struck_by"] == "dashboard"
    assert strike(client, second["id"], bid_only=True).status_code == 200
    # A rebuild an hour later keeps both and queues the next move in the struck one's place,
    # with its own full hour.
    later = NOW + timedelta(hours=1)
    client.app.state.seasons.clock = lambda: later
    q = client.post("/autopilot/queue/build").json()
    by = {e["id"]: e for e in q["entries"]}
    assert by[first["id"]]["struck"] and by[second["id"]]["bid_struck"]
    assert by[third["id"]]["queued"] and by[third["id"]]["queued_at"] == later.isoformat()
    assert by[third["id"]]["executes_at"] == (later + timedelta(hours=1)).isoformat()
    # The cap is full again: the strike cannot be undone until another is struck.
    r = strike(client, first["id"], undo=True)
    assert r.status_code == 409 and "cap is full" in r.json()["detail"]
    assert strike(client, third["id"]).status_code == 200
    assert strike(client, first["id"], undo=True).status_code == 200
    # Nothing to strike in an entry not queued, nor in one unknown.
    out = next(e for e in q["entries"] if not e["queued"])
    assert strike(client, out["id"]).status_code == 409
    assert strike(client, "2026-10-21:100001:1:0").status_code == 404
    assert strike(client, "nonsense").status_code == 404


def test_the_due_entries_wait_for_the_window_and_the_mode(client):
    q = queued(client)
    url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    d = client.get(url).json()
    assert d["entries"] == [] and d["reason"] == "nothing due now"
    assert d["next"] == (NOW + timedelta(hours=1)).isoformat()
    assert (d["cap"], d["budget"]) == (2, 100.0) and d["adds_left"] == row_of(q)["adds_left"]
    on = [e for e in q["entries"] if e["queued"]]
    strike(client, on[1]["id"], bid_only=True)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    d = client.get(url).json()
    assert [e["id"] for e in d["entries"]] == [e["id"] for e in on]
    assert [e["bid_placed"] for e in d["entries"]] == [on[0]["bid"]["amount"], 0]
    # The extension's input: my team, each entry's add page, the claims open and the day so far.
    assert d["team"] == 4
    assert [e["page"] for e in d["entries"]] == [
        f"/nba/{LEAGUE}/addplayer?apid={e['add']}" for e in on
    ]
    assert (d["pending"], d["done"]) == ([], 0)
    # Another day, STOP, an off league and the private league have none.
    assert client.get(url, params={"date": "2026-10-22"}).json()["entries"] == []
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.get(url).json()["reason"].startswith("STOP is on")
    stop.unlink()
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert client.get(url).json()["reason"] == qa.OFF
    assert client.get(f"/seasons/{PRIVATE}/autopilot/moves/due").json()["reason"] == qa.PRIVATE


def test_the_due_route_counts_the_days_executed_entries_and_their_adds(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    before = client.get(url).json()
    # A dry run's would-claim moves nothing: the entry is still due.
    body = pass_body([check(on[0])])
    assert client.post(f"/seasons/{LEAGUE}/autopilot/moves", json=body).status_code == 200
    assert client.get(url).json()["entries"] == before["entries"]
    # A live claim takes its place under the cap and its week's adds, and is open until resolved.
    placed(client, on[0]["id"], "claimed")
    d = client.get(url).json()
    assert [e["id"] for e in d["entries"]] == [e["id"] for e in on[1:]]
    assert d["done"] == 1 and [c["id"] for c in d["pending"]] == [on[0]["id"]]
    assert d["pending"][0]["add"] == on[0]["add"]
    clear = on[0]["from"]
    week = next(w for w in d["adds_left"] if w["start"] <= clear <= w["end"])
    was = next(w for w in before["adds_left"] if w["start"] == week["start"])
    assert was["adds"] is not None and week["adds"] == max(0, was["adds"] - 1)


def test_a_sunday_evening_build_queues_monday_claims_on_the_new_weeks_adds(client):
    # #209: Sunday, 9:30 pm Central, the week's last games begun. The solve answers, and the
    # build queues claims that clear Monday, each counted in the new week.
    sunday = datetime(2026, 10, 26, 2, 30, tzinfo=UTC)
    client.app.state.seasons.clock = lambda: sunday
    q = queued(client)
    assert q["date"] == "2026-10-25" and row_of(q)["status"] == "queued"
    on = [e for e in q["entries"] if e["queued"]]
    assert on and all(e["from"] >= "2026-10-26" for e in on)
    assert row_of(q)["adds_left"][0]["start"] == "2026-10-26"
    # Due after the full window, before the Eastern midnight; each placed claim takes a new
    # week's add.
    client.app.state.seasons.clock = lambda: sunday + timedelta(hours=1)
    url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    d = client.get(url).json()
    assert [e["id"] for e in d["entries"]] == [e["id"] for e in on]
    placed(client, on[0]["id"], "claimed", date(2026, 10, 25))
    after = client.get(url).json()
    new = next(w for w in after["adds_left"] if w["start"] == "2026-10-26")
    was = next(w for w in d["adds_left"] if w["start"] == "2026-10-26")
    assert new["adds"] == was["adds"] - 1


def placed(client, entry_id: str, outcome: str, day: date = DAY) -> None:
    """Set ``outcome`` on a day's queue entry as a live pass would (PR 3)."""

    def change(q):
        for e in q["entries"]:
            if e["id"] == entry_id:
                e["outcome"] = outcome
        return q

    season_queue.update(client.data_dir, day, change)


def pass_body(entries, **over) -> dict:
    body = {
        "day": "2026-10-21",
        "mode": "dry_run",
        "trigger": "routine",
        "outcome": "would_claim",
        "entries": entries,
        "extension": "0.7.0",
    }
    return {**body, **over}


def check(e: dict, **over) -> dict:
    out = {
        "id": e["id"],
        "add": e["add"],
        "drop": e["drop"],
        "bid": e["bid"]["amount"],
        "outcome": "would_claim",
        "page": f"/nba/{LEAGUE}/addplayer",
        "controls": {"form": "addplayer", "method": "post", "fields": ["date"]},
    }
    return {**out, **over}


def test_a_pass_is_logged_under_moves_and_sets_the_entries_outcomes(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    # The lineup's runs beside it in the same file stay as they are.
    ap.append_run(client.data_dir, LEAGUE, {"day": "2026-10-21", "mode": "dry_run"}, DAY)
    gone = check(on[1], outcome="gone", reason="another team has him")
    r = client.post(url, json=pass_body([check(on[0]), gone]))
    assert r.status_code == 200, r.text
    log = json.loads(
        (client.data_dir / "leagues" / LEAGUE / "autopilot" / "2026-10-21.json").read_text()
    )
    assert len(log["lineup"]) == 1 and [x["outcome"] for x in log["moves"][0]["entries"]] == [
        "would_claim",
        "gone",
    ]
    # A dry run moves no outcome on the queue: the late pass reads the same entries again.
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert [by[e["id"]]["outcome"] for e in on[:2]] == [None, None]
    view = client.get(url).json()
    assert view["last"]["outcome"] == "would_claim" and len(view["entries"]) == len(q["entries"])
    assert view["live"]["dry_run_days"] == 1 and view["live"]["checked_days"] == 1
    late = pass_body([check(on[0])], trigger="routine_late")
    assert client.post(url, json=late).status_code == 200
    # An entry a live pass executed is never executed again, a rebuild keeps it, and a strike
    # comes too late.
    placed(client, on[0]["id"], "claimed")
    r = client.post(url, json=pass_body([check(on[0])]))
    assert r.status_code == 409 and "executed already" in r.json()["detail"]
    again = {e["id"]: e for e in client.post("/autopilot/queue/build").json()["entries"]}
    assert again[on[0]["id"]]["outcome"] == "claimed"
    assert strike(client, on[0]["id"]).status_code == 409


def test_the_queue_reads_each_entrys_latest_pass_and_the_days_tally_from_the_logs(client):
    q = queued(client)
    assert q["passes"] is None and all(e["pass"] is None for e in q["entries"])
    on = [e for e in q["entries"] if e["queued"]]
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    cut = check(on[1], outcome="skipped", reason="the drop 9 cannot be picked (cantcut)")
    first = pass_body([check(on[0]), cut], outcome="skipped")
    assert client.post(url, json=first).status_code == 200
    # A pass that found nothing due names no entry and counts no page.
    assert client.post(url, json=pass_body([], outcome="nothing_due")).status_code == 200
    again = check(on[0], outcome="skipped", reason="page not read")
    late = pass_body([again], trigger="routine_late", outcome="skipped", extension="0.7.1")
    assert client.post(url, json=late).status_code == 200
    # Only the queue day's lines: a line of another day in the file names no entry's pass.
    out = next(e for e in q["entries"] if not e["queued"])
    other = {"at": NOW.isoformat(), "day": "2026-10-20", "trigger": "routine", "entries": []}
    other["entries"] = [{"id": out["id"], "outcome": "would_claim", "reason": None}]
    ap.append_run(client.data_dir, LEAGUE, other, DAY, ap.MOVES)
    log = ap.read_log(client.data_dir, LEAGUE, DAY)["moves"]
    got = client.get("/autopilot/queue").json()
    by = {e["id"]: e for e in got["entries"]}
    # Each entry its latest line: the entry's own outcome and reason, the pass's time and trigger.
    assert by[on[0]["id"]]["pass"] == {
        "at": log[2]["at"],
        "trigger": "routine_late",
        "outcome": "skipped",
        "reason": "page not read",
        "extension": "0.7.1",
    }
    assert by[on[1]["id"]]["pass"]["reason"] == "the drop 9 cannot be picked (cantcut)"
    assert by[out["id"]]["pass"] is None
    # Each entry counted once by its latest line; every entry line a page; the last line's time.
    assert got["passes"] == {
        "last": log[2]["at"],
        "would_claim": 0,
        "claimed": 0,
        "skipped": 2,
        "gone": 0,
        "failed": 0,
        "pages": 3,
    }
    # A dry run still moves no outcome; the queue file keeps no pass.
    assert by[on[0]["id"]]["outcome"] is None
    assert all("pass" not in e for e in season_queue.read(client.data_dir, DAY)["entries"])
    # The Queue card's entries say the same, and so does the strike's answer.
    card = {e["id"]: e for e in client.get(url).json()["entries"]}
    assert card[on[0]["id"]]["pass"] == by[on[0]["id"]]["pass"]
    struck = strike(client, on[1]["id"]).json()
    assert struck["passes"] == got["passes"]
    assert {e["id"]: e["pass"] for e in struck["entries"]}[on[0]["id"]]["outcome"] == "skipped"


def open_spot(client, entry_id: str) -> None:
    """Make a day's queue entry an add with no drop, as the solve gives one with an open spot."""

    def change(q):
        for e in q["entries"]:
            if e["id"] == entry_id:
                e.update(drop=None, basis="open", held_move=None)
        return q

    season_queue.update(client.data_dir, DAY, change)


OPEN_SPOT_HELD = (
    "open spot, read only: an open-spot claim is not submitted until Yahoo's open-spot page has"
    " been seen"
)


def test_an_open_spot_claim_is_logged_with_no_drop_and_a_live_one_is_read_only(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    open_spot(client, on[0]["id"])
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    due_url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    entry = {**on[0], "drop": None}
    fill = {"apid": on[0]["add"], "dpid": None, "faab": on[0]["bid"]["amount"]}
    controls = {"form": "addplayer", "fields": ["apid", "faab"], "drops": 0, "would_fill": fill}
    # The page showed no drop section (#199): a dry run says it would claim into the open spot.
    claim = check(entry, reason="open spot", controls=controls)
    r = client.post(url, json=pass_body([claim], extension="0.8.1"))
    assert r.status_code == 200, r.text
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert by[on[0]["id"]]["drop"] is None and by[on[0]["id"]]["outcome"] is None
    assert by[on[0]["id"]]["pass"]["outcome"] == "would_claim"
    assert by[on[0]["id"]]["pass"]["reason"] == "open spot"
    # The entry is the queue's own: a pass naming a drop for it names another move.
    r = client.post(url, json=pass_body([check(entry, drop=on[1]["drop"])]))
    assert r.status_code == 409 and "another move" in r.json()["detail"]
    # Live, the open spot is read and never submitted: a skip, and it stays due for the late pass.
    live_league(client)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    held = check(entry, outcome="skipped", reason=OPEN_SPOT_HELD, controls=controls)
    body = pass_body([held], mode="live", outcome="skipped", extension="0.8.1")
    assert client.post(url, json=body).status_code == 200
    d = client.get(due_url).json()
    assert on[0]["id"] in [e["id"] for e in d["entries"]]
    assert next(e for e in d["entries"] if e["id"] == on[0]["id"])["drop"] is None
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert by[on[0]["id"]]["outcome"] is None
    assert by[on[0]["id"]]["pass"]["reason"] == OPEN_SPOT_HELD


def test_the_log_refuses_a_crumb_a_dry_claim_a_struck_entry_and_another_move(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    out = next(e for e in q["entries"] if not e["queued"])
    url = f"/seasons/{LEAGUE}/autopilot/moves"

    def refused(body, code=409):
        r = client.post(url, json=body)
        assert r.status_code == code, r.text
        return r.json()["detail"]

    assert "crumb" in refused(pass_body([check(on[0], controls={"crumb": "x"})]), 422)
    assert "crumb" in refused(pass_body([check(on[0], controls={"crumb": "present"})]), 422)
    # The page's note that its anti-forgery field is there is a flag under another name.
    noted = pass_body([check(on[0], controls={"token": True})])
    assert client.post(url, json=noted).status_code == 200
    assert refused(pass_body([check(on[0], outcome="claimed")])) == "a dry run claims nothing"
    assert refused(pass_body([], mode="live", outcome="claimed")).startswith("a live pass")
    assert "never executed" in refused(pass_body([check(out)]))
    assert "another move" in refused(pass_body([check(on[0], add=1)]))
    assert "not in the day's queue" in refused(pass_body([check(on[0], id="2026-10-21:1:1:0")]))
    strike(client, on[1]["id"])
    assert "never executed" in refused(pass_body([check(on[1])]))
    # A struck entry may be reported skipped; nothing due is a pass too.
    skipped = check(on[1], outcome="skipped", reason="struck")
    assert client.post(url, json=pass_body([skipped], outcome="skipped")).status_code == 200
    assert client.post(url, json=pass_body([], outcome="nothing_due")).status_code == 200
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert refused(pass_body([check(on[0])])).startswith("STOP is on")
    assert client.post(url, json=pass_body([], outcome="stopped")).status_code == 200
    stop.unlink()
    client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "off"})
    assert refused(pass_body([])) == qa.OFF
    r = client.post(f"/seasons/{PRIVATE}/autopilot/moves", json=pass_body([]))
    assert r.status_code == 409 and r.json()["detail"] == qa.PRIVATE


def test_live_waits_for_seven_dry_run_days_two_of_them_reading_the_add_page(client):
    def put(mode: str):
        return client.put(f"/leagues/{LEAGUE}/moves", json={"mode": mode})

    assert put("live").json()["detail"] == "a dry run on 7 days first: 0 so far"
    for n in range(7):
        day = date(2026, 10, 1) + timedelta(days=n)
        run = {"day": day.isoformat(), "mode": "dry_run", "outcome": "nothing_due", "entries": []}
        if n < 1:
            run["entries"] = [{"id": "x", "outcome": "would_claim", "controls": {"form": "x"}}]
        ap.append_run(client.data_dir, LEAGUE, run, day, ap.MOVES)
    # Seven days, but a pass that found nothing due is never a checked day.
    assert put("live").json()["detail"] == ("2 dry-run days that read the add page first: 1 so far")
    day = date(2026, 10, 2)
    run = {"day": day.isoformat(), "mode": "dry_run", "outcome": "skipped"}
    run["entries"] = [{"id": "y", "outcome": "skipped", "controls": {"form": "x"}}]
    ap.append_run(client.data_dir, LEAGUE, run, day, ap.MOVES)
    # The lineup executor's dry run does not count for the moves.
    assert (
        ap.live_check(client.data_dir, LEAGUE, leagues.lineup_mode(client.data_dir, LEAGUE))[
            "dry_run_days"
        ]
        == 0
    )
    r = put("live")
    assert r.status_code == 200 and r.json()["mode"]["mode"] == "live"


def settings_file(client, body) -> None:
    path = client.data_dir / "autopilot" / "executor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))


def test_the_live_guard_reads_its_counts_from_the_settings_file_at_request_time(client):
    url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    seven = {"dry_run_days": 7, "checked_days": 2}
    assert client.get(url).json()["live"] == {
        "ok": False,
        "reason": "a dry run on 7 days first: 0 so far",
        "dry_run_days": 0,
        "checked_days": 0,
        "needs": seven,
    }
    # Each count read on its own: one that is not a whole number of at least 0 keeps its default.
    settings_file(client, {"live_after": {"dry_run_days": 1, "checked_days": -1}})
    assert client.get(url).json()["live"]["needs"] == {"dry_run_days": 1, "checked_days": 2}
    for bad in ({"dry_run_days": True}, {"dry_run_days": "2"}, {"dry_run_days": 1.5}, [3, 1]):
        settings_file(client, {"live_after": bad})
        assert client.get(url).json()["live"]["needs"] == seven
    settings_file(client, "not json")
    assert client.get(url).json()["live"]["needs"] == seven
    # The reason names the counts in force; the lineup executor's guard keeps its own. Who set
    # the knob and when sit beside the counts.
    who = {"set_at": "2026-10-26T16:01:27+00:00", "by": "master on the user's word"}
    settings_file(client, {"live_after": {"dry_run_days": 1, "checked_days": 1, **who}})
    run = {"day": "2026-10-01", "mode": "dry_run", "outcome": "nothing_due", "entries": []}
    ap.append_run(client.data_dir, LEAGUE, run, date(2026, 10, 1), ap.MOVES)
    live = client.get(url).json()["live"]
    assert live["reason"] == "1 dry-run day that read the add page first: 0 so far"
    lineup = ap.live_check(client.data_dir, LEAGUE, leagues.lineup_mode(client.data_dir, LEAGUE))
    assert lineup["needs"] == seven
    # The dashboard's Set keeps the knob; the private league is never live.
    assert (
        client.put("/autopilot/queue/settings", json={"execute_time": "09:00"}).status_code == 200
    )
    assert client.get(url).json()["live"]["needs"] == {"dry_run_days": 1, "checked_days": 1}
    private = client.get(f"/seasons/{PRIVATE}/autopilot/moves/due").json()["live"]
    assert private["ok"] is False and private["reason"] == "the private league is never touched"


def live_league(client) -> None:
    """The fixture league switched live, its guard waived by the knob (the master's on the
    user's word)."""
    settings_file(client, {"live_after": {"dry_run_days": 0, "checked_days": 0}})
    r = client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "live"})
    assert r.status_code == 200, r.text


def test_a_live_pass_places_its_claims_and_a_skip_stays_due_for_the_late_pass(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    live_league(client)
    due_url = f"/seasons/{LEAGUE}/autopilot/moves/due"
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    # The execute time holds in live: nothing is due inside the window.
    d = client.get(due_url).json()
    assert d["mode"] == "live" and d["live"]["ok"] and d["entries"] == []
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    assert [e["id"] for e in client.get(due_url).json()["entries"]] == [e["id"] for e in on]

    def live(entries, **over):
        return pass_body(entries, mode="live", extension="0.8.0", **over)

    # A live pass places a claim or says why not, never that it would.
    r = client.post(url, json=live([check(on[0])]))
    assert r.status_code == 409 and "never says would" in r.json()["detail"]
    # The claim goes on its entry; the skip stays due, so the late pass reads its page again.
    claim = check(on[0], outcome="claimed", message="claim submitted")
    skip = check(on[1], outcome="skipped", reason="page not read")
    r = client.post(url, json=live([claim, skip], outcome="claimed"))
    assert r.status_code == 200, r.text
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert by[on[0]["id"]]["outcome"] == "claimed"
    assert by[on[0]["id"]]["bid_placed"] == on[0]["bid"]["amount"]
    assert by[on[1]["id"]]["outcome"] is None
    d = client.get(due_url).json()
    assert [e["id"] for e in d["entries"]] == [on[1]["id"]]
    assert d["done"] == 1 and [c["id"] for c in d["pending"]] == [on[0]["id"]]
    # A failure goes on its entry and is never retried that day.
    failed = check(on[1], outcome="failed", reason="Yahoo refused the claim", message="refused")
    late = live([failed], trigger="routine_late", outcome="failed")
    assert client.post(url, json=late).status_code == 200
    assert client.get(due_url).json()["entries"] == []
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert (by[on[1]["id"]]["outcome"], by[on[1]["id"]]["outcome_reason"]) == (
        "failed",
        "Yahoo refused the claim",
    )
    r = client.post(url, json=live([check(on[1], outcome="claimed")], outcome="claimed"))
    assert r.status_code == 409 and "never retried that day" in r.json()["detail"]
    # A guard that refuses now refuses the live pass too; so does STOP.
    settings_file(client, {"live_after": {"dry_run_days": 9}})
    r = client.post(url, json=live([], outcome="nothing_due"))
    assert r.status_code == 409
    assert r.json()["detail"] == "live refused: a dry run on 9 days first: 0 so far"
    assert client.get(due_url).json()["live"]["ok"] is False
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.get(due_url).json()["live"]["reason"] == "STOP is on (data/autopilot/STOP)"
    stop.unlink()


def test_a_claim_whose_answer_was_not_read_keeps_its_reason_on_the_screen_and_the_digest(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    live_league(client)
    strike(client, on[1]["id"])
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    # The strike holds in live: the struck entry is not due.
    due = client.get(f"/seasons/{LEAGUE}/autopilot/moves/due").json()
    assert [e["id"] for e in due["entries"]] == [on[0]["id"]]
    why = "submitted 10:00 AM CT; Yahoo's answer was not read: check the pending claims"
    body = pass_body(
        [check(on[0], outcome="claimed", reason=why)],
        mode="live",
        outcome="claimed",
        extension="0.8.0",
    )
    assert client.post(f"/seasons/{LEAGUE}/autopilot/moves", json=body).status_code == 200
    by = {e["id"]: e for e in client.get("/autopilot/queue").json()["entries"]}
    assert (by[on[0]["id"]]["outcome"], by[on[0]["id"]]["outcome_reason"]) == ("claimed", why)
    assert client.get("/flags/digest").json()["moves_executor"] == [
        "- Moves executor (live in 1): Wed's queue 1 queued, 1 struck; 1 claimed, 0 skipped, 0 failed.",
        f"- League {LEAGUE}: moves Wed claimed ({why})",
    ]


def armed_of(client, league: str) -> dict:
    return json.loads((client.data_dir / "leagues" / league / "armed.json").read_text())


def test_one_switch_sets_every_public_league_the_points_ones_too_and_never_the_private_one(client):
    write_folder(client.data_dir, POINTS, scoring="points", points={"pts": 1.0})
    url = "/autopilot/moves/mode"
    # The private league's file and the lineup executor's keys are never written; the user's
    # own cap stays.
    private = client.data_dir / "leagues" / PRIVATE / "armed.json"
    private.write_text(json.dumps({"lineups": "off", "moves": "off"}) + "\n")
    held = private.read_bytes()
    assert client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "off"}).status_code == 200
    r = client.put(f"/leagues/{LEAGUE}/moves", json={"mode": "dry_run", "cap": 2})
    assert r.status_code == 200, r.text
    lineups = {k: v for k, v in armed_of(client, LEAGUE).items() if k.startswith("lineups")}
    assert lineups["lineups"] == "off"
    r = client.put(url, json={"mode": "off"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "mode": "off",
        "leagues": [
            {"league": LEAGUE, "mode": "off", "ok": True, "reason": None},
            {"league": POINTS, "mode": "off", "ok": True, "reason": None},
        ],
    }
    mine = armed_of(client, LEAGUE)
    assert (mine["moves"], mine["moves_cap"], mine["moves_by"]) == (
        "off",
        2,
        "dashboard: every league",
    )
    assert datetime.fromisoformat(mine["moves_at"]).tzinfo is not None
    assert {k: v for k, v in mine.items() if k.startswith("lineups")} == lineups
    points = armed_of(client, POINTS)
    assert points["moves"] == "off" and not any(k.startswith("lineups") for k in points)
    # A league already in the mode is left as it is: its file is not written again.
    files = {lg: armed_of(client, lg) for lg in (LEAGUE, POINTS)}
    assert all(x["ok"] for x in client.put(url, json={"mode": "off"}).json()["leagues"])
    assert {lg: armed_of(client, lg) for lg in (LEAGUE, POINTS)} == files
    # The queue's rows are read with the modes now: a row the build left off says it was
    # switched on since, with the user's own cap and the live guard now.
    r = client.post("/autopilot/queue/build")
    assert r.status_code == 200, r.text
    assert {x["league"]: x["status"] for x in r.json()["leagues"]} == {
        LEAGUE: "off",
        PRIVATE: "private",
        POINTS: "off",
    }
    assert client.put(url, json={"mode": "dry_run"}).status_code == 200
    rows = {x["league"]: x for x in client.get("/autopilot/queue").json()["leagues"]}
    assert (rows[LEAGUE]["mode"], rows[LEAGUE]["user_cap"], rows[POINTS]["user_cap"]) == (
        "dry_run",
        2,
        None,
    )
    assert rows[LEAGUE]["status"] == "off" and rows[LEAGUE]["reason"] == qa.SWITCHED_ON
    assert rows[POINTS]["live"]["reason"] == "a dry run on 7 days first: 0 so far"
    assert "live" not in rows[PRIVATE] and rows[PRIVATE]["mode"] == "off"
    card = client.get(f"/seasons/{LEAGUE}/autopilot/moves").json()["row"]
    assert (card["mode"], card["reason"]) == ("dry_run", qa.SWITCHED_ON)
    # The stored queue keeps the build's rows.
    stored = {x["league"]: x for x in season_queue.read(client.data_dir, DAY)["leagues"]}
    assert stored[LEAGUE]["mode"] == "off" and "live" not in stored[LEAGUE]
    # Live is checked per league: STOP refuses it everywhere and every league keeps its mode.
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    out = client.put(url, json={"mode": "live"}).json()["leagues"]
    assert {(x["mode"], x["ok"], x["reason"]) for x in out} == {
        ("dry_run", False, "STOP is on (data/autopilot/STOP)")
    }
    stop.unlink()
    # A league whose guard holds goes live; one it refuses keeps its mode, with the reason.
    settings_file(client, {"live_after": {"dry_run_days": 1, "checked_days": 0}})
    run = {"day": "2026-10-20", "mode": "dry_run", "outcome": "nothing_due", "entries": []}
    ap.append_run(client.data_dir, LEAGUE, run, date(2026, 10, 20), ap.MOVES)
    out = {x["league"]: x for x in client.put(url, json={"mode": "live"}).json()["leagues"]}
    assert out[LEAGUE] == {"league": LEAGUE, "mode": "live", "ok": True, "reason": None}
    assert out[POINTS] == {
        "league": POINTS,
        "mode": "dry_run",
        "ok": False,
        "reason": "a dry run on 1 day first: 0 so far",
    }
    assert (armed_of(client, LEAGUE)["moves"], armed_of(client, POINTS)["moves"]) == (
        "live",
        "dry_run",
    )
    assert armed_of(client, LEAGUE)["moves_cap"] == 2
    rows = {x["league"]: x for x in client.get("/autopilot/queue").json()["leagues"]}
    assert (rows[LEAGUE]["mode"], rows[POINTS]["mode"]) == ("live", "dry_run")
    # Nothing here wrote the private league's file.
    assert private.read_bytes() == held
    assert PRIVATE not in {
        x["league"] for x in client.put(url, json={"mode": "off"}).json()["leagues"]
    }
    assert private.read_bytes() == held
    assert client.put(url, json={"mode": "on"}).status_code == 422


def test_the_execute_time_is_the_users_and_times_the_days_entries_again(client):
    q = queued(client)
    r = client.put("/autopilot/queue/settings", json={"execute_time": "15:30"})
    assert r.status_code == 200
    assert r.json()["settings"]["execute_time"] == "15:30" and r.json()["execute_time"] == "15:30"
    on = [e for e in r.json()["entries"] if e["queued"]]
    assert {e["executes_at"] for e in on} == {"2026-10-21T20:30:00+00:00"}  # 15:30 Central
    assert len(r.json()["entries"]) == len(q["entries"])
    assert client.put("/autopilot/queue/settings", json={"execute_time": "9am"}).status_code == 422
    # Earlier than the hour after queueing: the hour holds.
    r = client.put("/autopilot/queue/settings", json={"execute_time": "06:00"})
    assert {e["executes_at"] for e in r.json()["entries"] if e["queued"]} == {
        (NOW + timedelta(hours=1)).isoformat()
    }


def test_sundays_execute_time_is_set_alone_holds_on_sunday_and_clears(client):
    # #209: a weekday keeps the day's time; Sunday's entries wait for Sunday's.
    queued(client)
    url = "/autopilot/queue/settings"
    r = client.put(url, json={"sunday_execute_time": "22:30"})
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert (s["execute_time"], s["set"], s["sunday_execute_time"], s["sunday_by"]) == (
        "07:00",
        False,
        "22:30",
        "dashboard",
    )
    # Wednesday's entries are not timed again by it.
    assert s["in_force"] == "07:00"
    assert {e["executes_at"] for e in r.json()["entries"] if e["queued"]} == {
        (NOW + timedelta(hours=1)).isoformat()
    }
    # On a Sunday the build times every entry by it; the morning's pass finds none due.
    sunday = datetime(2026, 10, 25, 14, 0, tzinfo=UTC)  # 09:00 Central
    client.app.state.seasons.clock = lambda: sunday
    q = queued(client)
    assert q["date"] == "2026-10-25" and q["settings"]["in_force"] == "22:30"
    on = [e for e in q["entries"] if e["queued"]]
    assert on and {e["executes_at"] for e in on} == {"2026-10-26T03:30:00+00:00"}
    due = f"/seasons/{LEAGUE}/autopilot/moves/due"
    assert client.get(due).json()["entries"] == []
    client.app.state.seasons.clock = lambda: datetime(2026, 10, 26, 3, 31, tzinfo=UTC)
    assert [e["id"] for e in client.get(due).json()["entries"]] == [e["id"] for e in on]
    # Cleared, Sunday keeps the day's time and today's entries are timed by it again.
    client.app.state.seasons.clock = lambda: sunday
    r = client.put(url, json={"sunday_execute_time": None})
    assert r.json()["settings"]["sunday_execute_time"] is None
    assert r.json()["settings"]["in_force"] == "07:00"
    assert {e["executes_at"] for e in r.json()["entries"] if e["queued"]} == {
        (sunday + timedelta(hours=1)).isoformat()
    }
    # Both at once; neither is refused; a bad time is.
    r = client.put(url, json={"execute_time": "09:00", "sunday_execute_time": "21:45"})
    assert (r.json()["settings"]["execute_time"], r.json()["settings"]["in_force"]) == (
        "09:00",
        "21:45",
    )
    assert client.put(url, json={}).status_code == 422
    assert client.put(url, json={"sunday_execute_time": "10pm"}).status_code == 422
    # The Queue card says the same.
    assert client.get(f"/seasons/{LEAGUE}/autopilot/moves").json()["settings"]["in_force"] == (
        "21:45"
    )


def test_an_evening_rebuild_keeps_what_its_solve_dropped_as_superseded(client):
    # #209: the evening's solve no longer recommends a queued move; it stays, not queued.
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    assert len(on) >= 2
    path = client.data_dir / "leagues" / LEAGUE / "season" / "decisions" / "2026-10-21.json"
    logged = json.loads(path.read_text())
    three = next(s for s in logged[-1]["sets"] if s["key"] == "three")
    three["moves"] = [m for m in three["moves"] if m["add"] != on[0]["add"]]
    path.write_text(json.dumps(logged))
    client.app.state.seasons.clock = lambda: NOW + timedelta(minutes=30)
    r = client.post("/autopilot/queue/build")
    assert r.status_code == 200, r.text
    by = {e["id"]: e for e in r.json()["entries"]}
    gone = by[on[0]["id"]]
    assert (gone["queued"], gone["reason"], gone["executes_at"]) == (False, qa.SUPERSEDED, None)
    # It is struck by nobody, never due, and holds no place: the rest are due as they were.
    assert gone["struck"] is False
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=2)
    due = client.get(f"/seasons/{LEAGUE}/autopilot/moves/due").json()
    assert on[0]["id"] not in {e["id"] for e in due["entries"]}
    assert on[1]["id"] in {e["id"] for e in due["entries"]}
    # Nothing to strike in it.
    assert strike(client, on[0]["id"]).status_code == 409


def test_a_queue_file_that_does_not_read_is_refused_never_overwritten(client):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    (folder / "2026-10-21.json").write_text("not json")
    r = client.post("/autopilot/queue/build")
    assert r.status_code == 409 and "does not read" in r.json()["detail"]
    assert client.get("/autopilot/queue").status_code == 409
    assert strike(client, "2026-10-21:100001:1:0").status_code == 409
    assert (folder / "2026-10-21.json").read_text() == "not json"


def test_the_digest_counts_the_queue_and_the_passes_in_one_line(client):
    q = queued(client)
    on = [e for e in q["entries"] if e["queued"]]
    strike(client, on[1]["id"])
    url = f"/seasons/{LEAGUE}/autopilot/moves"
    client.post(url, json=pass_body([check(on[0])]))
    skipped = check(on[1], outcome="skipped", reason="the drop is protected")
    client.post(url, json=pass_body([skipped], outcome="skipped"))
    d = client.get("/flags/digest").json()
    assert d["moves_executor"] == [
        (
            "- Moves executor (dry run in 1): Wed's queue 1 queued, 1 struck; 1 would be claimed,"
            " 1 skipped, 0 failed."
        ),
        f"- League {LEAGUE}: moves Wed skipped (the drop is protected)",
    ]
    section = d["markdown"][d["markdown"].index("### Moves") :]
    assert all(line in section for line in d["moves_executor"])
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.get("/flags/digest").json()["moves_executor"] == [
        "- Moves executor: STOP is on (data/autopilot/STOP); nothing runs."
    ]


def test_the_digest_says_when_there_is_no_queue_and_nothing_when_nothing_is_armed(client):
    modes = {LEAGUE: leagues.executor_mode(client.data_dir, LEAGUE, leagues.MOVES)}
    assert ap.moves_digest_lines(client.data_dir, modes, None, NOW) == [
        "- Moves executor (dry run in 1): no queue; 0 would be claimed, 0 skipped, 0 failed."
    ]
    private = {PRIVATE: leagues.executor_mode(client.data_dir, PRIVATE, leagues.MOVES)}
    assert ap.moves_digest_lines(client.data_dir, private, None, NOW) == []


def test_a_build_resolves_the_earlier_days_placed_claims_and_counts_the_open_ones(
    client, monkeypatch
):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    claim = {"league": LEAGUE, "outcome": "claimed", "resolved": None, "from": "2026-10-22"}
    won = {**claim, "id": f"2026-10-20:{LEAGUE}:9001:0", "add": 9001}
    open_ = {**claim, "id": f"2026-10-20:{LEAGUE}:9002:0", "add": 9002}
    (folder / "2026-10-20.json").write_text(json.dumps({"entries": [won, open_]}))
    monkeypatch.setattr(season_queue, "resolutions", lambda s, e, d: {won["id"]: "won"})
    q = queued(client)
    earlier = json.loads((folder / "2026-10-20.json").read_text())["entries"]
    assert [(e["id"], e["resolved"]) for e in earlier] == [(won["id"], "won"), (open_["id"], None)]
    # The claim still open counts against its week.
    row = row_of(q)
    assert [c["id"] for c in row["pending"]] == [open_["id"]]
    assert row["pending"][0]["add"] == 9002 and row["pending"][0]["from"] == "2026-10-22"
    week = next(w for w in row["adds_left"] if w["start"] <= "2026-10-22" <= w["end"])
    solved = next(w for w in row["adds"]["weeks"] if w["start"] == week["start"])
    assert week["adds"] == solved["adds"] - 1
