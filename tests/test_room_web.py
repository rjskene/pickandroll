"""#10: what the web app's sync panel reads from a room. The session stream carries every client
event (heartbeats aside) as ``room_event`` and every room pick with its lag, promptly even when
published from a worker thread; the room summary carries the recent lags and whether the draft
is complete; the scorecard ranks each actual pick in the reco acted on."""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.fidelity import analyze

from .test_yahoo_room import SESSION, _ev, build_league


@pytest.fixture
def room(tmp_path):
    picks = build_league(tmp_path)
    store = SessionStore()
    client = TestClient(create_app(store, data_dir=tmp_path))
    with client:
        r = client.post("/rooms", json={"draft_id": "w1", "slot": 1, "session": SESSION})
        assert r.status_code == 201, r.text
        yield client, store.get(r.json()["session_id"]), picks


class Listener:
    """An event stream's queue on a loop of its own, as the API's stream holds it."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.queue = asyncio.run_coroutine_threadsafe(self._queue(), self.loop).result()

    async def _queue(self) -> asyncio.Queue:
        return asyncio.Queue()

    def get(self, timeout: float = 2.0) -> dict:
        return asyncio.run_coroutine_threadsafe(self.queue.get(), self.loop).result(timeout)

    def drain(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.get(timeout=0.3))
            except TimeoutError:
                return out

    def close(self):
        # drain() ends on a get that timed out and is still waiting: cancel it before the loop
        # stops, or it is collected later as "Event loop is closed" in another test.
        async def settle():
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(settle(), self.loop).result(2)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(2)
        self.loop.close()


def test_a_publish_from_a_worker_thread_reaches_a_waiting_stream_at_once(room):
    """Room picks are published from asyncio.to_thread. A queue's put from that thread did
    not wake the stream's loop, so a pick waited for the next keepalive (15 s)."""
    _, session, _ = room

    async def wait_for_one():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        session.listeners.append((queue, loop))
        try:
            threading.Timer(0.05, lambda: session.publish("probe", {}, bump=False)).start()
            started = loop.time()
            item = await asyncio.wait_for(queue.get(), 5.0)
            return loop.time() - started, item
        finally:
            session.listeners.remove((queue, loop))

    took, item = asyncio.run(wait_for_one())
    assert item["event"] == "probe"
    assert took < 1.0, f"the stream woke after {took:.2f} s"


def test_client_events_and_room_picks_reach_the_stream(room):
    client, session, picks = room
    listener = Listener()
    session.listeners.append((listener.queue, listener.loop))
    try:
        events = [
            {"type": "heartbeat", "vis": "visible"},
            {"type": "draft_attempt", "overall": 1, "yid": "a", "method": "row", "attempt": 1},
            {"type": "note", "what": "hand pick", "overall": 24},
        ]
        r = client.post("/rooms/w1/events", json={"events": events})
        assert r.status_code == 200, r.text
        items = [{"overall": 1, "yahoo_player_id": picks[0].yahoo_player_id, "slot": 1}]
        assert client.post("/rooms/w1/picks", json={"picks": items}).status_code == 200
        got = listener.drain()
    finally:
        session.listeners.remove((listener.queue, listener.loop))
        listener.close()
    room_events = [g for g in got if g["event"] == "room_event"]
    assert [e["entry"]["type"] for e in room_events] == ["draft_attempt", "note"]
    assert all(e["draft_id"] == "w1" and e["entry"]["src"] == "client" for e in room_events)
    pick = next(g for g in got if g["event"] == "pick")
    assert pick["source"] == "yahoo_room" and pick["pick"]["overall"] == 1
    assert isinstance(pick["lag_ms"], int)


def test_the_room_summary_carries_recent_lags_and_completion(room):
    client, _, picks = room
    view = client.get("/rooms/w1").json()
    assert view["recent_lags"] == [] and view["complete"] is False
    items = [
        {"overall": k, "yahoo_player_id": p.yahoo_player_id, "slot": 1}
        for k, p in enumerate(picks[:30], start=1)
    ]
    assert client.post("/rooms/w1/picks", json={"picks": items}).status_code == 200
    view = client.get("/rooms/w1").json()
    lags = view["recent_lags"]
    assert len(lags) == 24, "the latest 24 picks"
    assert [x["overall"] for x in lags] == list(range(7, 31))
    assert all(isinstance(x["lag_ms"], int) for x in lags)


def test_the_scorecard_ranks_the_actual_pick_in_the_reco_acted_on():
    events = [
        _ev("attach", 0, slot=1, num_teams=2, rounds=2, draft_id="r"),
        _ev("control", 0, state="armed"),
        _ev("reco", 0, board=0, top_yid="a", top_pid="pa", cands=["a", "b", "c"]),
        _ev("room_pick", 1, overall=1, yid="b", name="B"),
        _ev("session_pick", 1, overall=1, yid="b"),
        _ev("room_pick", 2, overall=2, yid="x"),
        _ev("session_pick", 2, overall=2, yid="x"),
        _ev("reco", 2, board=2, top_yid="c", top_pid="pc", cands=["c", "d"]),
        _ev("room_pick", 3, overall=3, yid="z"),
        _ev("session_pick", 3, overall=3, yid="z"),
        _ev("reco", 3, board=3, top_yid="e", top_pid="pe", cands=["e"]),
        _ev("room_pick", 4, overall=4, yid="e"),
        _ev("session_pick", 4, overall=4, yid="e"),
    ]
    rows = {r["overall"]: r for r in analyze(events)["rows"]}
    assert rows[1]["actual_rank"] == 2
    assert rows[4]["actual_rank"] == 1


def test_a_pin_repair_is_not_a_room_lag(room):
    """The sync card's lag is room message to session pick. A stand-in repaired by a pin
    minutes later is the same room pick again, not a slow one."""
    client, session, picks = room
    items = [
        {"overall": 1, "yahoo_player_id": picks[0].yahoo_player_id, "slot": 1},
        {"overall": 2, "yahoo_player_id": "800000", "slot": 2},
    ]
    assert client.post("/rooms/w1/picks", json={"picks": items}).status_code == 200
    assert client.get("/rooms/w1").json()["standins"][0]["overall"] == 2
    board = client.get(f"/sessions/{session.id}/board?limit=400").json()["players"]
    target = next(p for p in board if p["name"] == "Ponly Person")["player_id"]
    r = client.post("/rooms/w1/aliases", json={"yahoo_player_id": "800000", "player_id": target})
    assert r.status_code == 200 and r.json()["repaired"] == [2]
    view = client.get("/rooms/w1").json()
    assert view["standins"] == []
    assert [x["overall"] for x in view["recent_lags"]] == [1, 2]
