"""#10: a draft room open in Chrome with the extension and not attached is listed for the web
app for 30 s after the extension last said so, never attached by that alone."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app

from .test_yahoo_room import SESSION, build_league


@pytest.fixture
def client(tmp_path):
    build_league(tmp_path)
    with TestClient(create_app(SessionStore(), data_dir=tmp_path)) as c:
        yield c


def test_a_room_the_extension_sees_is_listed_until_attached(client):
    assert client.get("/rooms/seen").json() == []
    r = client.post("/rooms/seen", json={"draft_id": "s1", "slot": 4, "room_teams": None})
    assert r.status_code == 200, r.text
    r = client.post("/rooms/seen", json={"draft_id": "s1", "slot": 4, "room_teams": 12})
    seen = client.get("/rooms/seen").json()
    assert [(x["draft_id"], x["slot"], x["room_teams"]) for x in seen] == [("s1", 4, 12)]
    assert seen[0]["age_s"] < 5
    r = client.post("/rooms", json={"draft_id": "s1", "slot": 4, "session": SESSION})
    assert r.status_code == 201, r.text
    assert client.get("/rooms/seen").json() == [], "an attached room is not offered again"
    assert client.get("/rooms/s1").json()["draft_id"] == "s1", "/rooms/seen shadows no room route"


def test_a_room_unseen_for_the_ttl_drops_off(client, monkeypatch):
    # pickandroll.api.app is also the name of the ASGI app object: fetch the module itself.
    monkeypatch.setattr(importlib.import_module("pickandroll.api.app"), "SEEN_TTL_S", 0.0)
    client.post("/rooms/seen", json={"draft_id": "s2", "slot": None, "room_teams": None})
    assert client.get("/rooms/seen").json() == []


def test_a_seen_report_is_checked(client):
    assert client.post("/rooms/seen", json={"draft_id": "../x", "slot": 1}).status_code == 422
    assert client.post("/rooms/seen", json={"draft_id": "s3", "slot": 0}).status_code == 422
    assert client.post("/rooms/seen", json={"draft_id": "s3", "room_teams": 30}).status_code == 422


def test_a_detach_is_on_the_session_stream(client):
    """The web app learns of a detach made elsewhere (the side panel) from its stream."""
    r = client.post("/rooms", json={"draft_id": "s4", "slot": 1, "session": SESSION})
    session = client.app.state.store.get(r.json()["session_id"])
    published = []
    session.publish = lambda event, data, bump=True: published.append((event, data))
    assert client.delete("/rooms/s4").status_code == 200
    assert published == [("room_detached", {"draft_id": "s4"})]
