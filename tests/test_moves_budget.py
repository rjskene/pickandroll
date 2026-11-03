"""The moves solve's budget at the route (#306): the settings file's ``moves_budget_s`` bounds
every solve, whose answer then says how far its search got; a client that goes stops its solve,
which is never kept or logged, and the next call solves again.

The league is the season tests' made-up one; nothing here is from Basketball Monster.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from fastapi import HTTPException

from pickandroll.api import season_knobs, season_moves, season_queue, seasons
from pickandroll.season import moves as mv
from tests.test_decisions import logged
from tests.test_season import LEAGUE, season_client, strategy_league

MOVES = f"/seasons/{LEAGUE}/moves"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        strategy_league(c)
        yield c


def put_settings(data_dir, body) -> None:
    path = season_knobs.autopilot_dir(data_dir) / season_queue.SETTINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body))


@pytest.mark.parametrize(
    ("body", "seconds"),
    [
        (None, 90.0),
        ({"moves_budget_s": 45}, 45.0),
        ({"moves_budget_s": 2.5, "rival_claim_rate": 0.4}, 2.5),
        ({"moves_budget_s": 0}, 90.0),
        ({"moves_budget_s": -1}, 90.0),
        ({"moves_budget_s": "60"}, 90.0),
        ({"moves_budget_s": True}, 90.0),
        ("{not json", 90.0),
    ],
)
def test_the_budget_is_the_settings_files_seconds_above_0_else_the_default(tmp_path, body, seconds):
    assert mv.MOVES_BUDGET_S == 90.0
    if body is not None:
        put_settings(tmp_path, body)
    assert season_queue.moves_budget_s(tmp_path) == seconds


def test_a_solve_inside_its_budget_says_so(client):
    search = client.get(MOVES).json()["search"]
    assert (search["budget_s"], search["cut"], search["note"]) == (90.0, False, None)
    assert search["finished"] == search["searches"] > 0


def test_a_solve_past_its_budget_answers_the_best_found_and_says_how_far_it_got(client):
    # Read at request time: no restart to change it.
    put_settings(client.data_dir, {"moves_budget_s": 1e-9})
    out = client.get(MOVES).json()
    search = out["search"]
    assert search["cut"] is True and search["finished"] < search["searches"]
    assert search["note"] == (
        f"searched {search['finished']} of {search['searches']} within the budget (1e-09 s):"
        " the best sets found by then"
    )
    # Still an answer: the table's candidates, the recommended sets, its decision entry.
    assert out["candidates"] and out["recommended"]
    assert len(logged(client)) == 1


def test_a_solve_whose_client_went_stops_and_is_never_kept_or_logged(client):
    service = client.app.state.seasons
    with pytest.raises(seasons.Abandoned):
        service.moves(LEAGUE, None, None, True, stop=lambda: True)
    assert service.moves_cache.latest((LEAGUE, "bbm", "moves")) is None
    assert logged(client) == []
    # The next call solves again, whole.
    assert client.get(MOVES).json()["search"]["cut"] is False
    assert len(logged(client)) == 1


class Client:
    """The route's request: its client goes after ``stays`` looks."""

    def __init__(self, stays: int) -> None:
        self.stays, self.looks = stays, 0

    async def is_disconnected(self) -> bool:
        self.looks += 1
        return self.looks > self.stays


def get_moves(client):
    return next(
        r.endpoint
        for r in client.app.routes
        if getattr(r, "path", None) == "/seasons/{league}/moves" and "GET" in r.methods
    )


def test_the_route_stops_the_solve_of_a_client_that_went_and_waits_for_it(client, monkeypatch):
    # A solve that runs until its budget is out; 5 s bounds it should the stop never come.
    put_settings(client.data_dir, {"moves_budget_s": 5})
    monkeypatch.setattr(seasons, "CLIENT_POLL_S", 0.01)
    real = season_moves.moves_payload
    running = threading.Event()

    def held(built, budget=None):
        running.set()
        while not budget.out():
            time.sleep(0.01)
        running.clear()
        return real(built, budget)

    monkeypatch.setattr(season_moves, "moves_payload", held)
    route, gone = get_moves(client), Client(stays=2)
    began = time.monotonic()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(route(gone, league=LEAGUE, system=None, source=None))
    # Stopped at the client's going, not the budget's end; nothing left computing.
    assert caught.value.status_code == 499 and gone.looks == 3
    assert time.monotonic() - began < 4 and not running.is_set()
    assert logged(client) == []
    # A client that stays gets the answer and its entry.
    monkeypatch.setattr(season_moves, "moves_payload", real)
    out = asyncio.run(route(Client(stays=10**6), league=LEAGUE, system=None, source=None))
    assert out["search"]["cut"] is False and len(logged(client)) == 1
