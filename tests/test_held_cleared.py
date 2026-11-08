"""A player cleared to play sitting on IL or IL+ (#341): Yahoo refuses every claim while he is
there (Error 845). The due route names him (``held_cleared``) from his newest status in any
league's team-page read, so a status that turned from O to Q since this league's read still stops
the claim. Nothing here opens a page.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.season import autopilot as qa
from tests.test_moves_queue import queued
from tests.test_season import LEAGUE, NOW, season_client

DUE = f"/seasons/{LEAGUE}/autopilot/moves/due"
OTHER = "100002"


def part(at: str, *spots: tuple[int, str, str | None]) -> dict:
    return {
        "fetched_at": at,
        "source": "public",
        "data": {
            "spots": [
                {"slot": slot, "player": {"yahoo_id": pid, "status": status}}
                for pid, slot, status in spots
            ]
        },
    }


def test_the_newest_team_page_read_of_a_player_in_any_league_gives_his_status():
    states = [
        (
            "1",
            {"roster/4": part("2026-11-07T11:28:00+00:00", (10460, "IL", "O"), (5765, "IL", "O"))},
        ),
        (
            "2",
            {
                "roster/9": part("2026-11-07T15:15:19+00:00", (10460, "BN", "Q")),
                "lineup/9/2026-11-08": part("2026-11-07T15:15:19+00:00", (10460, "BN", "Q")),
                # Not a team page: never read for a status.
                "players/1": part("2026-11-07T16:00:00+00:00", (10460, "BN", "O")),
            },
        ),
        # An older read elsewhere loses; a time with no zone is UTC.
        ("3", {"roster/2": part("2026-11-06T10:00:00", (10460, "IL", "O"))}),
    ]
    got = qa.newest_statuses(states, [10460, 5765, 1])
    assert got == {
        10460: {"status": "Q", "read_at": "2026-11-07T15:15:19+00:00", "league": "2"},
        5765: {"status": "O", "read_at": "2026-11-07T11:28:00+00:00", "league": "1"},
    }
    # A part with no time or no spots says nothing.
    assert qa.newest_statuses([("1", {"roster/4": {"data": {"spots": []}}})], [1]) == {}
    assert qa.newest_statuses([("1", {"roster/4": {"fetched_at": "x"}})], [1]) == {}


def test_a_held_player_whose_newest_status_no_longer_fits_his_slot_is_named():
    newest = {10460: {"status": "Q", "read_at": "2026-11-07T15:15:19+00:00", "league": "2"}}
    # IL takes O and OFS; IL+ takes GTD, INJ, O and OFS; NA is never a cleared slot here.
    assert qa.held_cleared([(10460, "IL", "O")], newest) == [
        {
            "player": 10460,
            "slot": "IL",
            "status": "Q",
            "read_at": newest[10460]["read_at"],
            "league": "2",
        }
    ]
    assert qa.held_cleared([(10460, "IL+", "O")], newest) == [
        {
            "player": 10460,
            "slot": "IL+",
            "status": "Q",
            "read_at": newest[10460]["read_at"],
            "league": "2",
        }
    ]
    assert qa.held_cleared([(10460, "IL+", "O")], {10460: {**newest[10460], "status": "GTD"}}) == []
    assert qa.held_cleared([(10460, "NA", None)], newest) == []
    # No newer read: this league's own, with no time or league.
    assert qa.held_cleared([(1, "IL", None)], {}) == [
        {"player": 1, "slot": "IL", "status": None, "read_at": None, "league": None}
    ]
    assert qa.held_cleared([(1, "IL", "O")], {}) == []


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def put_parts(client, league: str, parts: dict) -> None:
    path = client.data_dir / "leagues" / league / "season" / "state.json"
    body = json.loads(path.read_text()) if path.exists() else {}
    body["parts"] = {**(body.get("parts") or {}), **parts}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def hold(client, player: int, status: str | None) -> None:
    """Put ``player`` of my roster on IL with ``status`` in every team-page part of the league."""
    path = client.data_dir / "leagues" / LEAGUE / "season" / "state.json"
    body = json.loads(path.read_text())
    for key, p in body["parts"].items():
        if key == "roster/4" or key.startswith("lineup/4/"):
            for sp in p["data"]["spots"]:
                if sp["player"]["yahoo_id"] == player:
                    sp.update(slot="IL")
                    sp["player"]["status"] = status
    path.write_text(json.dumps(body))


def test_the_due_route_names_a_held_player_cleared_in_his_newest_read(client):
    queued(client)
    client.app.state.seasons.clock = lambda: NOW + timedelta(hours=1)
    assert client.get(DUE).json()["held_cleared"] == []
    held = 6406
    hold(client, held, "O")
    assert client.get(DUE).json()["held_cleared"] == []
    # Another league's read an hour later says Q: the claims wait.
    later = "2026-10-21T19:00:00+00:00"
    put_parts(client, OTHER, {"roster/7": part(later, (held, "BN", "Q"))})
    assert client.get(DUE).json()["held_cleared"] == [
        {"player": held, "slot": "IL", "status": "Q", "read_at": later, "league": OTHER}
    ]
    # An older read elsewhere does not beat this league's own.
    put_parts(client, OTHER, {"roster/7": part("2026-10-21T08:00:00+00:00", (held, "BN", "Q"))})
    assert client.get(DUE).json()["held_cleared"] == []
    # This league's own read of Q names him too.
    hold(client, held, "Q")
    [x] = client.get(DUE).json()["held_cleared"]
    assert (x["player"], x["status"], x["league"]) == (held, "Q", LEAGUE)
