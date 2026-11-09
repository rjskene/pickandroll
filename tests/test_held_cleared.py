"""A player cleared to play sitting on IL or IL+ (#341): Yahoo refuses every claim while he is
there (Error 845). The due route names him (``held_cleared``) from his newest status in any
league's team-page read, so a status that turned from O to Q since this league's read still stops
the claim. Nothing here opens a page.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_moves
from pickandroll.season import autopilot as qa
from tests.test_moves_queue import queued
from tests.test_season import LEAGUE, NOW, season_client, strategy_league

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


# --------------------------------------------------------------------------- a claim re-judged (#345)
def test_a_build_rejudges_the_placed_claims_once_a_held_player_clears_and_says_cancel_by_hand(
    client, monkeypatch
):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    claim = {"league": LEAGUE, "outcome": "claimed", "resolved": None, "from": "2026-10-22"}
    cancel = {**claim, "id": f"2026-10-20:{LEAGUE}:9001:7", "add": 9001, "drop": 7, "bid_placed": 2}
    keep = {**claim, "id": f"2026-10-20:{LEAGUE}:9002:0", "add": 9002, "drop": None}
    settled = {**claim, "id": f"2026-10-20:{LEAGUE}:9003:0", "add": 9003, "resolved": "won"}
    # A free agent added at once: landed, nothing to cancel, never judged.
    added = {**claim, "id": f"2026-10-20:{LEAGUE}:9004:0", "add": 9004, "outcome": "added"}
    entries = [cancel, keep, settled, added]
    (folder / "2026-10-20.json").write_text(json.dumps({"entries": entries}))
    seen = []

    def judge(built, claims, statuses):
        seen.append(([c["id"] for c in claims], dict(statuses)))
        base = {"judged": "three", "gain": 0.5, "value": None, "season_costly": None}
        return {
            cancel["id"]: {**base, "comeback_drops": {6406: 9001}},
            keep["id"]: {**base, "comeback_drops": {6406: 7}},
            added["id"]: {**base, "comeback_drops": {6406: 9004}},
        }

    monkeypatch.setattr(season_moves, "rejudge_claims", judge)
    # No one cleared: nothing judged, nothing written.
    queued(client)
    assert seen == []
    assert all(
        "rejudge" not in e for e in json.loads((folder / "2026-10-20.json").read_text())["entries"]
    )
    # He clears (Q on IL): the open claims are judged with his newest status; a settled one never.
    hold(client, 6406, "Q")
    q = client.post("/autopilot/queue/build").json()
    assert seen == [([cancel["id"], keep["id"]], {6406: "Q"})]
    written = {e["id"]: e for e in json.loads((folder / "2026-10-20.json").read_text())["entries"]}
    got = written[cancel["id"]]["rejudge"]
    assert (got["verdict"], got["reason"], got["held"]) == (
        qa.CANCEL,
        "with 6406 back his comeback would drop 9001, the claim's own add",
        [6406],
    )
    assert got["comeback_drops"] == {"6406": 9001} and got["floor"]["plan"] is not None
    assert written[keep["id"]]["rejudge"]["verdict"] == qa.KEEP
    assert "rejudge" not in written[settled["id"]]
    assert "rejudge" not in written[added["id"]]
    # The Queue screen's row carries each open claim's verdict and bid.
    row = next(r for r in q["leagues"] if r["league"] == LEAGUE)
    pending = {c["id"]: c for c in row["pending"]}
    assert pending[cancel["id"]]["rejudge"]["verdict"] == qa.CANCEL
    assert pending[cancel["id"]]["bid"] == 2
    # The digest: the user's to cancel by hand, with the reason.
    line = (
        f"- League {LEAGUE}: cancel by hand the pending claim add 9001, drop 7, $2: "
        "with 6406 back his comeback would drop 9001, the claim's own add"
    )
    assert ap.cancel_digest_lines(client.data_dir, NOW.date()) == [line]
    # A cancel verdict on a free agent's add (an older build's) prints no line either.
    stale = {**added, "rejudge": {"verdict": qa.CANCEL, "reason": "x"}}
    (folder / "2026-10-19.json").write_text(json.dumps({"entries": [stale]}))
    assert ap.cancel_digest_lines(client.data_dir, NOW.date()) == [line]
    (folder / "2026-10-19.json").unlink()
    assert line in client.get("/flags/digest").json()["moves_executor"]
    # Back to O: the verdict lapses on the next build, and the line goes.
    hold(client, 6406, "O")
    client.post("/autopilot/queue/build")
    written = {e["id"]: e for e in json.loads((folder / "2026-10-20.json").read_text())["entries"]}
    assert written[cancel["id"]]["rejudge"]["verdict"] is None
    assert written[cancel["id"]]["rejudge"]["reason"] == qa.NO_CLEARED
    assert ap.cancel_digest_lines(client.data_dir, NOW.date()) == []


def test_a_claim_the_real_build_cannot_judge_says_so_and_is_no_cancel(client):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    out_of_pool = {
        "id": f"2026-10-20:{LEAGUE}:999999:0",
        "league": LEAGUE,
        "add": 999999,
        "drop": None,
        "outcome": "claimed",
        "resolved": None,
        "from": "2026-10-22",
    }
    (folder / "2026-10-20.json").write_text(json.dumps({"entries": [out_of_pool]}))
    strategy_league(client)
    hold(client, 6406, "Q")
    assert client.get(f"/seasons/{LEAGUE}/moves").status_code == 200
    assert client.post("/autopilot/queue/build").status_code == 200
    [e] = json.loads((folder / "2026-10-20.json").read_text())["entries"]
    assert (e["rejudge"]["verdict"], e["rejudge"]["reason"]) == (None, qa.NOT_JUDGED)
    assert ap.cancel_digest_lines(client.data_dir, NOW.date()) == []
