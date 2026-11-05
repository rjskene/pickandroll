"""A cleared IL player's comeback that needs a drop (#318): the API's half. The steps route offers
it only in a live moves league under its guard, never with a protected drop or a game begun; the
league's log says which moved and still owe their drop, the due route and the drop log take it
from there, and the digest says each step. Nothing here opens a page: the runs are the
extension's, faked.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api.seasons import nba_today
from pickandroll.routine import steps as rs
from pickandroll.sources.yahoo import public
from tests.test_held_drop import DUE, URL, drop_body
from tests.test_il_move import a_player
from tests.test_lineup import lineup_league, moved
from tests.test_moves_queue import PRIVATE, live_league, queued
from tests.test_season import LEAGUE, NOW, fixture, season_client

DAY = date(2026, 10, 26)
AT = datetime(2026, 10, 26, 13, tzinfo=UTC)
BACK, STAY = 5, 3
ENTRY = ap.comeback_entry(BACK)


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def lineup_page(day: date = DAY) -> dict:
    return {
        "rule": {"changes": "daily"},
        "start": DAY.isoformat(),
        "slots": ["PG", "C"],
        "players": {
            "1": {"positions": ["PG"], "nba_team": "BOS"},
            "2": {"positions": ["C"], "nba_team": "GSW"},
            "3": {"positions": ["PG"], "nba_team": "BOS"},
            "5": {"positions": ["PG"], "nba_team": "NYK"},
        },
        "alerts": [{"kind": "cleared", "player": BACK, "slot": "IL", "status": None, "drop": STAY}],
        "days": [
            {
                "date": day.isoformat(),
                "past": False,
                "recommended": [{"slot": "PG", "player": 1}, {"slot": "C", "player": 2}],
                "yahoo": {
                    "read_at": "2026-10-26T12:00:00+00:00",
                    "page": "dated page",
                    "slots": [
                        {"slot": "PG", "player": 1},
                        {"slot": "C", "player": 2},
                        {"slot": "BN", "player": STAY},
                        {"slot": "IL", "player": BACK},
                    ],
                },
                "start": [],
                "sit": [],
                "games": {"recommended": 2, "yahoo": 2},
                "playing": [1, 2],
            }
        ],
    }


def gate(**over) -> dict:
    return {"protected": set(), "moved": set(), "pending": [], **over}


def steps(comeback, *, mode=None, stop=False, now=AT, tips=None, day=DAY, today=DAY) -> dict:
    return ap.steps_payload(
        LEAGUE,
        4,
        day,
        today,
        now,
        lineup_page(day),
        tips or {},
        mode or {"mode": "live"},
        stop,
        {"ok": True, "reason": None},
        comeback,
    )


# --------------------------------------------------------------------------- the steps
def test_a_comeback_is_offered_only_under_the_moves_gate():
    s = steps(gate())
    assert s["comebacks"] == [
        {"player": BACK, "slot": "IL", "status": None, "tip": None, "drop": STAY}
    ]
    assert (s["skipped"], s["returns"], s["pending_drop"]) == ([], [], False)
    # Outside a live moves league he stays the user's.
    s = steps(None)
    assert s["comebacks"] == []
    assert s["skipped"] == [{"reason": ap.NEEDS_DROP, "players": [BACK], "steps": []}]


def test_the_private_league_and_stop_run_no_comeback():
    assert steps(gate(), mode={"mode": "off", "private": True})["comebacks"] == []
    assert steps(gate(), stop=True)["comebacks"] == []
    pending = [{"player": BACK, "drop": STAY, "entry": ENTRY}]
    assert (
        steps(gate(pending=pending), mode={"mode": "off", "private": True})["pending_drop"] is False
    )


def test_no_legal_drop_skips_with_the_reason_and_never_offers_the_comeback():
    s = steps(gate(protected={STAY}))
    assert s["comebacks"] == []
    assert s["skipped"] == [
        {
            "reason": f"no legal drop: {STAY} is protected, never dropped",
            "players": [BACK],
            "steps": [],
        }
    ]


def test_a_game_that_began_waits_for_the_next_day_his_page_allows():
    tip = AT - timedelta(minutes=1)
    s = steps(gate(), tips={"NYK": tip.isoformat()})
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"].startswith("his game began")
    # Before the tip he runs; on another day's page he is no one's.
    assert steps(gate(), tips={"NYK": (AT + timedelta(hours=1)).isoformat()})["comebacks"]
    later = DAY + timedelta(days=1)
    assert steps(gate(), day=later)["comebacks"] == []


def test_a_moved_player_is_not_moved_again_and_his_drop_is_due():
    pending = [{"player": BACK, "drop": STAY, "entry": ENTRY}]
    s = steps(gate(moved={BACK}, pending=pending))
    assert (s["comebacks"], s["pending_drop"]) == ([], True)
    assert s["drop_page"] == public.drop_url(LEAGUE, 4)
    assert s["skipped"][0]["reason"] == "his move is on the log: the drop follows"
    # A drop protected since is no drop due.
    s = steps(gate(moved={BACK}, pending=pending, protected={STAY}))
    assert s["pending_drop"] is False


# --------------------------------------------------------------------------- the league's log
def move_run(at: datetime = AT, outcome: str = "set", drop: int | None = STAY) -> dict:
    return {
        "at": at.isoformat(),
        "mode": "live",
        "steps": [{"player": BACK, "kind": "return", "drop": drop, "outcome": outcome}],
    }


def drop_run(outcome: str, entry: str = ENTRY) -> dict:
    return {"at": AT.isoformat(), "mode": "live", "entry": entry, "outcome": outcome}


def roster(*players: int, held: tuple[int, ...] = ()) -> dict:
    return {"players": list(players), "held": list(held)}


def pending(tmp_path, roster_=None, read_at=None, spots=2, today=DAY):
    return ap.comeback_pending(tmp_path, LEAGUE, today, roster_, read_at, spots)


def test_only_a_set_comeback_move_of_a_live_run_is_on_the_log(tmp_path):
    ap.append_run(tmp_path, LEAGUE, move_run(outcome="skipped"), DAY)
    ap.append_run(tmp_path, LEAGUE, move_run(drop=None), DAY)
    ap.append_run(tmp_path, LEAGUE, {**move_run(), "mode": "dry_run"}, DAY)
    assert pending(tmp_path) == []
    ap.append_run(tmp_path, LEAGUE, move_run(), DAY)
    assert pending(tmp_path) == [{"player": BACK, "drop": STAY, "entry": ENTRY}]


def test_a_landed_move_with_a_failed_drop_resumes_at_the_drop_and_never_drops_twice(tmp_path):
    ap.append_run(tmp_path, LEAGUE, move_run(), DAY)
    # A skip stays due: the next pass takes it.
    ap.append_run(tmp_path, LEAGUE, drop_run("skipped"), DAY, ap.DROP)
    assert [p["entry"] for p in pending(tmp_path)] == [ENTRY]
    # A failure is not made again that day, and is the next day.
    ap.append_run(tmp_path, LEAGUE, drop_run("failed"), DAY, ap.DROP)
    assert pending(tmp_path) == []
    later = DAY + timedelta(days=1)
    over = roster(1, 2, STAY, BACK)
    read = AT + timedelta(hours=2)
    assert [p["entry"] for p in pending(tmp_path, over, read, 3, later)] == [ENTRY]
    # Once dropped, never again.
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), later, ap.DROP)
    assert pending(tmp_path, over, read, 3, later) == []


def test_a_hand_fix_read_after_the_move_ends_the_comeback(tmp_path):
    ap.append_run(tmp_path, LEAGUE, move_run(), DAY)
    read = AT + timedelta(hours=1)
    # Over the active spots with his drop still here: due.
    assert pending(tmp_path, roster(1, 2, STAY, BACK), read, 3)
    # The drop already gone, or the roster back within its spots: dropping would be a loss.
    assert pending(tmp_path, roster(1, 2, BACK), read, 3) == []
    assert pending(tmp_path, roster(1, STAY, BACK), read, 3) == []
    # With no read since the move, only today's move stands.
    earlier = AT - timedelta(hours=1)
    assert pending(tmp_path, roster(1, 2, BACK), earlier, 3)
    assert pending(tmp_path, roster(1, 2, BACK), earlier, 3, DAY + timedelta(days=1)) == []


# --------------------------------------------------------------------------- due and the drop log
def a_moved_comeback(client) -> tuple[date, int]:
    """A live league with a comeback of ``BACK`` moved today, its drop (a player of the fixture)
    still to go."""
    queued(client)
    drop = a_player(client)[0]
    live_league(client)
    today = nba_today(NOW)
    ap.append_run(client.data_dir, LEAGUE, move_run(NOW + timedelta(minutes=5), drop=drop), today)
    return today, drop


def test_the_due_route_names_the_drop_first_with_the_way_back(client):
    _, drop = a_moved_comeback(client)
    d = client.get(DUE).json()
    assert d["drop_first"] == [
        {
            "entry": ENTRY,
            "player": drop,
            "slot": None,
            "add": None,
            "comeback": BACK,
            "back": public.team_url(LEAGUE, 4),
            "page": public.drop_url(LEAGUE, 4),
        }
    ]


def test_the_drop_log_takes_the_comebacks_drop_and_refuses_any_other(client):
    today, drop = a_moved_comeback(client)
    body = drop_body(ENTRY, drop, day=today.isoformat(), mode="live", outcome="dropped")
    other = client.post(URL, json={**body, "player": drop + 1})
    assert other.status_code == 409 and "another drop" in other.json()["detail"]
    nobody = client.post(URL, json={**body, "entry": ap.comeback_entry(BACK + 1)})
    assert nobody.status_code == 409 and nobody.json()["detail"].endswith("has no drop pending")
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.text
    assert client.get(DUE).json()["drop_first"] == []


def test_stop_and_the_private_league_have_no_comeback_drop(client):
    a_moved_comeback(client)
    (client.data_dir / "autopilot").mkdir(exist_ok=True)
    (client.data_dir / "autopilot" / "STOP").write_text("")
    assert client.get(DUE).json().get("drop_first", []) == []
    (client.data_dir / "autopilot" / "STOP").unlink()
    assert client.get(f"/seasons/{PRIVATE}/autopilot/moves/due").json().get("drop_first", []) == []


# --------------------------------------------------------------------------- after the drop
def row_gone(html: str, name: str) -> str:
    """A team page without ``name``'s row: a player dropped."""
    return "<tr".join(r for r in html.split("<tr") if f'title="{name}"' not in r)


def test_after_the_drop_the_returned_player_starts_and_no_slot_stays_empty(client):
    """The chain's last run, through the real build: the page as it reads once the player is off
    the IL and his drop gone from a starting slot. The steps start him and fill the hole."""
    html = fixture("team4.html")
    day = "2026-10-24"  # the fixture's busy day
    lineup_league(client)

    def lineup_day():
        days = client.get(f"/seasons/{LEAGUE}/lineup").json()["days"]
        return next(d for d in days if d["date"] == day)

    def refresh(page):
        client.fake.team_pages[4] = page
        assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202

    roster = client.get(f"/seasons/{LEAGUE}").json()["roster"]
    names = {s["player"]["yahoo_id"]: s["player"]["name"] for s in roster}
    playing = lineup_day()["playing"]
    him = next(s for s in roster if s["slot"] != "BN" and s["player"]["yahoo_id"] in playing)
    back, slot = him["player"]["yahoo_id"], him["slot"]

    # He sits on the IL, cleared; the engine names the drop, who starts in the slot he left.
    refresh(moved(html, {names[back]: "IL"}))
    [alert] = [
        a
        for a in client.get(f"/seasons/{LEAGUE}/lineup").json()["alerts"]
        if a["kind"] == "cleared"
    ]
    assert alert["player"] == back
    drop = alert["drop"]
    assert drop != back

    # The chain ran: he is on the bench and the drop's row is gone, his slot empty.
    refresh(row_gone(moved(html, {names[back]: "BN", names[drop]: slot}), names[drop]))
    s = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": day}).json()
    assert s["yahoo"][str(back)] == "BN" and str(drop) not in s["yahoo"]
    filled = {x["slot"] for x in lineup_day()["recommended"] if x["player"] is not None}
    target = {int(k): v for k, v in s["target"].items()}
    assert drop not in target
    assert any(x["player"] == back and x["from_slot"] == "BN" for x in s["steps"])
    assert target[back] in filled
    # Nobody with a game is left on the bench for a slot he could fill: the hole is gone.
    d = lineup_day()
    started = {x["player"] for x in d["recommended"] if x["player"] is not None}
    assert set(d["playing"]) - {drop} == started
    assert s["games"]["after"] == d["games"]["recommended"] == len(started)


# --------------------------------------------------------------------------- the digest
def test_the_digest_says_each_step_of_a_comeback(tmp_path):
    ap.append_run(tmp_path, LEAGUE, move_run(), DAY)
    assert ap.comeback_digest_lines(tmp_path, [LEAGUE], DAY) == [
        f"- League {LEAGUE}: comeback of {BACK}: moved to the bench, drop of {STAY} still to make"
    ]
    ap.append_run(tmp_path, LEAGUE, {**drop_run("skipped"), "reason": "no row"}, DAY, ap.DROP)
    assert ap.comeback_digest_lines(tmp_path, [LEAGUE], DAY) == [
        f"- League {LEAGUE}: comeback of {BACK}: moved to the bench, drop of {STAY} skipped (no row)"
    ]
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert ap.comeback_digest_lines(tmp_path, [LEAGUE], DAY) == [
        f"- League {LEAGUE}: comeback of {BACK}: moved to the bench, {STAY} dropped"
    ]
    assert ap.comeback_digest_lines(tmp_path, [LEAGUE], DAY + timedelta(days=1)) == []


# --------------------------------------------------------------------------- the routine's wait
def test_a_lineup_page_with_a_comeback_stays_open_for_its_chain():
    class Ctx:
        def __init__(self, body):
            self.body = body
            self.notes = {}

        def get(self, path, timeout):
            return 200, self.body, {}

    body = {
        "mode": "live",
        "open": True,
        "date": "2026-10-26",
        "page": public.team_url(LEAGUE, 4),
    }

    def waits(b):
        return [o.wait_s for o in rs.lineup_plan(Ctx(b), [LEAGUE], False, "pickandroll-lineup")]

    assert waits(body) == [rs.LINEUP_WAIT_S]
    assert waits({**body, "comebacks": [{"player": BACK}]}) == [rs.COMEBACK_WAIT_S]
    assert waits({**body, "comebacks": [{}, {}], "pending_drop": True}) == [3 * rs.COMEBACK_WAIT_S]
