"""Keepers through the API (docs/KEEPERS.md §2): the create fields, the summary, the board and
pick flags, PATCH, undo, sync, autopick, the survival build and the Yahoo feed. Players are the
sample export's best by total z, by id; no keeper names."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pickandroll.api import SessionStore, create_app
from pickandroll.draft import Keeper

DATA = Path(__file__).resolve().parents[1] / "data"
SAMPLE = "bbm_sample_ros_totals.xls"


@pytest.fixture
def store():
    return SessionStore()


@pytest.fixture
def client(store):
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    with TestClient(create_app(store, data_dir=DATA)) as c:
        yield c


def create(client, status=201, **overrides):
    """Four teams, my seat 2 (my picks 2, 7, 10, 15, ...), background solving off."""
    body = {
        "projection_file": SAMPLE,
        "num_teams": 4,
        "my_position": 2,
        "solve_ahead": False,
        "time_limit": 4.0,
    }
    body.update(overrides)
    r = client.post("/sessions", json=body)
    assert r.status_code == status, r.text
    return r.json()


def best(client, n):
    """The ``n`` best players of the sample export: ``(id, name)``."""
    s = create(client)
    board = client.get(f"/sessions/{s['id']}/board?limit={n}").json()["players"]
    return [(p["player_id"], p["name"]) for p in board]


def pick(client, sid, team, pid):
    r = client.post(f"/sessions/{sid}/picks", json={"team": team, "player_id": pid})
    assert r.status_code == 201, r.text
    return r.json()


def events(store, sid, name):
    return [e for e in store.get(sid).log if e["event"] == name]


def test_keepers_on_create_show_in_summary_board_and_picks(client, store):
    (a, _), (b, _), (c, _), (d, _) = best(client, 4)
    s = create(
        client,
        keepers=[
            {"round": 2, "player_id": a},  # mine: pick 7
            {"position": 1, "round": 1, "player_id": b},  # pick 1, logged at once
            {"position": 3, "round": 1, "player_id": c},  # pick 3
        ],
    )
    sid = s["id"]
    assert s["picks_made"] == 1 and s["next_overall"] == 2 and s["on_the_clock"] is True
    assert s["my_slots"][:4] == [2, 7, 10, 15] and len(s["my_slots"]) == 13
    assert s["my_picks"][:3] == [2, 10, 15] and len(s["my_picks"]) == 12
    assert s["my_roster"] == [a]
    assert [
        (k["overall"], k["position"], k["round"], k["player_id"], k["mine"], k["applied"])
        for k in s["keepers"]
    ] == [(1, 1, 1, b, False, True), (3, 3, 1, c, False, False), (7, 2, 2, a, True, False)]
    assert [k["team"] for k in s["keepers"]] == ["Team 1", "Team 3", "me"]

    board = {p["player_id"]: p for p in client.get(f"/sessions/{sid}/board").json()["players"]}
    assert {pid: board[pid]["keeper"] for pid in (a, b, c, d)} == {
        a: "me",
        b: "Team 1",
        c: "Team 3",
        d: None,
    }
    assert all(board[pid]["taken"] for pid in (a, b, c)) and not board[d]["taken"]

    # My pick 2 logs team 3's keeper at pick 3 behind it; both are published.
    row = pick(client, sid, "me", d)
    assert row["overall"] == 2 and row["keeper"] is False
    log = client.get(f"/sessions/{sid}/picks").json()
    assert [(p["overall"], p["player_id"], p["keeper"]) for p in log] == [
        (1, b, True),
        (2, d, False),
        (3, c, True),
    ]
    assert [(e["pick"]["overall"], e["pick"]["keeper"]) for e in events(store, sid, "pick")] == [
        (2, False),
        (3, True),
    ]
    s = client.get(f"/sessions/{sid}").json()
    assert s["next_overall"] == 4 and s["my_roster"] == [d, a]
    assert [k["applied"] for k in s["keepers"]] == [True, True, False]


def test_undo_takes_back_the_real_pick_and_the_keepers_behind_it(client, store):
    (a, _), (b, _), (c, _) = best(client, 3)
    sid = create(
        client,
        keepers=[
            {"position": 1, "round": 1, "player_id": a},
            {"position": 3, "round": 1, "player_id": b},
        ],
    )["id"]
    pick(client, sid, "me", c)
    r = client.delete(f"/sessions/{sid}/picks/last")
    assert r.status_code == 200, r.text
    undone = r.json()
    assert (undone["overall"], undone["player_id"], undone["keeper"]) == (2, c, False)
    assert [(k["overall"], k["player_id"]) for k in undone["keepers_undone"]] == [(3, b)]
    (event,) = events(store, sid, "undo")
    assert event["pick"]["overall"] == 2 and [k["overall"] for k in event["keepers"]] == [3]
    s = client.get(f"/sessions/{sid}").json()
    assert s["picks_made"] == 1 and s["next_overall"] == 2
    # Pick 1 is a keeper: never the undo target (it would be logged again at once).
    r = client.delete(f"/sessions/{sid}/picks/last")
    assert r.status_code == 400 and "no picks to undo" in r.json()["detail"]


def test_a_keeper_slot_takes_only_the_keeper(client):
    (a, _), (b, _), (c, _) = best(client, 3)
    keepers = [
        {"position": 1, "round": 1, "player_id": a},
        {"position": 3, "round": 1, "player_id": c},
    ]
    sid = create(client, keepers=keepers)["id"]
    r = client.post(f"/sessions/{sid}/picks", json={"team": "x", "player_id": b, "overall": 1})
    assert r.status_code == 400 and "pick 1 is a keeper slot" in r.json()["detail"]
    # A keeper still to come cannot be drafted by anyone else.
    r = client.post(f"/sessions/{sid}/picks", json={"team": "me", "player_id": c})
    assert r.status_code == 400 and "is kept with pick 3" in r.json()["detail"]


def test_sync_passes_the_keepers_own_entry_and_refuses_anyone_else(client):
    (a, _), (b, _), (c, _), (d, _), (e, _) = best(client, 5)
    sid = create(client, keepers=[{"position": 3, "round": 1, "player_id": c}])["id"]
    feed = [[1, "a", a], [2, "me", b], [3, "c", c], [4, "d", d]]
    added = client.post(f"/sessions/{sid}/sync", json={"picks": feed}).json()["added"]
    assert [(p["overall"], p["keeper"]) for p in added] == [
        (1, False),
        (2, False),
        (3, True),
        (4, False),
    ]
    assert client.post(f"/sessions/{sid}/sync", json={"picks": feed}).json()["added"] == []
    # A feed without the keeper's entry fills his slot all the same.
    sid = create(client, keepers=[{"position": 3, "round": 1, "player_id": c}])["id"]
    gap = [[1, "a", a], [2, "me", b], [4, "d", d]]
    added = client.post(f"/sessions/{sid}/sync", json={"picks": gap}).json()["added"]
    assert [p["overall"] for p in added] == [1, 2, 3, 4]
    # Someone else at the keeper's slot: 400 naming the slot and the keeper.
    sid = create(client, keepers=[{"position": 3, "round": 1, "player_id": c}])["id"]
    wrong = [[1, "a", a], [2, "me", b], [3, "c", e]]
    r = client.post(f"/sessions/{sid}/sync", json={"picks": wrong})
    assert r.status_code == 400
    assert "pick 3 is a keeper slot" in r.json()["detail"]


def test_create_errors_name_the_keeper_row(client):
    (a, name), (b, _) = best(client, 2)
    cases = [
        (
            [
                {"position": 1, "round": 1, "player_id": a},
                {"position": 3, "round": 2, "player_id": a},
            ],
            "keepers[1] (position 3, round 2",
            "kept twice",
        ),
        ([{"round": 14, "player_id": a}], "keepers[0] (me, round 14", "round outside 1-13"),
        (
            [{"position": 5, "round": 1, "player_id": a}],
            "keepers[0] (position 5",
            "position outside 1-4",
        ),
        (
            [
                {"position": 1, "round": 2, "player_id": a},
                {"position": 3, "round": 1, "player_id": b},
                {"round": 1, "player": name},
            ],
            "keepers[2] (me, round 1",
            "kept twice",
        ),
        ([{"position": 1, "round": 1, "player_id": "nobody"}], "keepers[0]", "unknown player id"),
        (
            [{"position": 1, "round": 1, "player": "Not A Player"}],
            "keepers[0]",
            "no projected player by that name",
        ),
        ([{"position": 1, "round": 1}], "keepers[0]", "give player_id or player"),
        (
            [
                {"position": 1, "round": 1, "player_id": a},
                {"position": 1, "round": 1, "player_id": b},
            ],
            "keepers[1]",
            "pick 1 is already",
        ),
    ]
    for keepers, where, reason in cases:
        detail = create(client, status=400, keepers=keepers)["detail"]
        assert where in detail and reason in detail, detail


@pytest.fixture
def data_dir(tmp_path):
    """A data/ holding the sample export and keeper tables."""
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    (tmp_path / SAMPLE).symlink_to(DATA / SAMPLE)
    return tmp_path


def test_keepers_file_rows_listing_and_errors(data_dir):
    with TestClient(create_app(SessionStore(), data_dir=data_dir)) as c:
        (a, name), (b, other) = best(c, 2)
        (data_dir / "keepers_test.csv").write_text(
            f"Position,Round,Player\nme,7,{name}\n\n3,2,{other}\n"
        )
        (data_dir / "keepers_bad.csv").write_text(
            f"position,round,player\n1,1,{name}\n2,R7,{other}\n"
        )
        (data_dir / "keepers_dup.csv").write_text(
            f"position,round,player\n1,1,{name}\n,,\n2,3,{name}\n"
        )
        (data_dir / "notes.csv").write_text("a,b\n")
        files = {f["file"] for f in c.get("/files?kind=keepers").json()}
        assert files == {"keepers_test.csv", "keepers_bad.csv", "keepers_dup.csv"}
        # Never offered as projections (the newest CSV is the setup screen's default).
        assert {f["file"] for f in c.get("/projections").json()} == {SAMPLE, "notes.csv"}

        rows = c.get("/keepers-file?file=keepers_test.csv").json()["rows"]
        assert rows == [
            {
                "label": "keepers_test.csv line 2",
                "position": None,
                "round": 7,
                "player_id": None,
                "player": name,
            },
            {
                "label": "keepers_test.csv line 4",
                "position": 3,
                "round": 2,
                "player_id": None,
                "player": other,
            },
        ]
        r = c.get("/keepers-file?file=keepers_bad.csv")
        assert (
            r.status_code == 400
            and r.json()["detail"] == "keepers_bad.csv line 3: 'R7' is not a whole number"
        )
        assert c.get("/keepers-file?file=nope.csv").status_code == 400
        assert c.get("/keepers-file?file=../keepers_test.csv").status_code == 400
        assert c.get(f"/keepers-file?file={data_dir / 'keepers_test.csv'}").status_code == 400

        # The file's rows come first, then the list; an error names the line or the index.
        s = create(
            c,
            keepers_file="keepers_test.csv",
            keepers=[{"position": 1, "round": 1, "player_id": b}],
            status=400,
        )
        assert "keepers[0] (position 1, round 1" in s["detail"] and "kept twice" in s["detail"]
        s = create(c, keepers_file="keepers_dup.csv", status=400)
        assert "keepers_dup.csv line 4 (position 2, round 3" in s["detail"]
        assert "kept twice" in s["detail"]
        assert "not found" in create(c, keepers_file="nope.csv", status=400)["detail"]

        s = create(c, keepers_file="keepers_test.csv")
        assert [(k["overall"], k["player_id"]) for k in s["keepers"]] == [(6, b), (26, a)]


def test_create_params_keep_the_resolved_table(client, store, tmp_path):
    (a, name), (b, _) = best(client, 2)
    s = create(
        client, keepers=[{"round": 3, "player": name}, {"position": 4, "round": 1, "player_id": b}]
    )
    params = store.get(s["id"]).create_params
    assert params["keepers"] == [
        {"position": None, "round": 3, "player_id": a},
        {"position": 4, "round": 1, "player_id": b},
    ]
    assert params["keepers_file"] is None
    # A rebuild from the record gives the same table.
    rebuilt = create(
        client, **{k: v for k, v in params.items() if k != "keepers"}, keepers=params["keepers"]
    )
    assert rebuilt["keepers"] == s["keepers"]


def test_patch_keepers_any_slot_not_reached(client, store):
    (a, _), (b, _), (c, _), (d, name), (e, _) = best(client, 5)
    sid = create(client)["id"]
    url = f"/sessions/{sid}/keepers"
    r = client.patch(url, json={"keepers": [{"position": 1, "round": 1, "player_id": a}]})
    assert r.status_code == 200, r.text
    assert [(k["overall"], k["applied"]) for k in r.json()["keepers"]] == [(1, True)]
    assert client.get(f"/sessions/{sid}").json()["picks_made"] == 1
    # Before the first real pick the whole table may change; pick 1 is re-derived.
    table = [{"position": 3, "round": 1, "player_id": c}]
    assert client.patch(url, json={"keepers": table}).status_code == 200
    assert client.get(f"/sessions/{sid}").json()["picks_made"] == 0
    pick(client, sid, "Team 1", a)
    pick(client, sid, "me", b)  # team 3's keeper at pick 3 follows
    assert client.get(f"/sessions/{sid}").json()["next_overall"] == 4
    # An applied keeper cannot change: 409, the table unchanged.
    r = client.patch(url, json={"keepers": []})
    assert r.status_code == 409 and "pick 3 is in the log" in r.json()["detail"]
    r = client.patch(url, json={"keepers": [*table, {"position": 1, "round": 1, "player_id": a}]})
    assert r.status_code == 409 and "pick 1 is in the log" in r.json()["detail"]
    # Slots not reached may change at any time.
    table.append({"position": 1, "round": 2, "player": name})  # pick 8
    r = client.patch(url, json={"keepers": table})
    assert r.status_code == 200
    assert [(k["overall"], k["player_id"]) for k in r.json()["keepers"]] == [(3, c), (8, d)]
    assert store.get(sid).create_params["keepers"][1] == {"position": 1, "round": 2, "player_id": d}
    # A player already drafted cannot be kept later: 400 naming the row.
    r = client.patch(url, json={"keepers": [table[0], {"position": 1, "round": 2, "player_id": a}]})
    assert r.status_code == 400
    assert "keepers[1] (position 1, round 2" in r.json()["detail"]
    assert "drafted with pick 1" in r.json()["detail"]
    r = client.patch(
        url, json={"keepers": [table[0], {"position": 1, "round": 2, "player_id": "nobody"}]}
    )
    assert r.status_code == 400 and "keepers[1]" in r.json()["detail"]
    s = client.get(f"/sessions/{sid}").json()
    assert [k["player_id"] for k in s["keepers"]] == [c, d] and e not in s["my_roster"]
    assert [len(ev["keepers"]) for ev in events(store, sid, "keepers")] == [1, 1, 2]


def test_autopick_fills_keeper_slots_without_drafting_keepers(client):
    top = [pid for pid, _ in best(client, 6)]
    keepers = [
        {"round": 3, "player_id": top[0]},  # mine: pick 10
        {"position": 1, "round": 1, "player_id": top[1]},  # pick 1
        {"position": 4, "round": 2, "player_id": top[2]},  # pick 5
        {"position": 3, "round": 13, "player_id": top[3]},  # pick 51
    ]
    sid = create(client, keepers=keepers)["id"]
    # Round 1 first (picks 2-4): my turn at 2 stops it at once, so make my pick.
    pick(client, sid, "me", top[4])
    r = client.post(
        f"/sessions/{sid}/autopick",
        json={"until_my_pick": False, "noise": 0.0, "strategy": "z"},
    )
    assert r.status_code == 200, r.text
    added = {p["overall"]: p for p in r.json()["added"]}
    log = client.get(f"/sessions/{sid}/picks").json()
    assert [p["overall"] for p in log] == list(range(1, 53))
    kept = {p["overall"]: p["player_id"] for p in log if p["keeper"]}
    assert kept == {1: top[1], 5: top[2], 10: top[0], 51: top[3]}
    assert added[5]["keeper"] and added[10]["keeper"] and added[51]["keeper"]
    assert added[10]["team"] == "me"
    assert sum(p["player_id"] in kept.values() for p in log) == 4  # nobody drafted a keeper


def test_survival_build_gets_the_keepers_with_my_seat(client, monkeypatch):
    import importlib

    app_module = importlib.import_module("pickandroll.api.app")  # the package's ``app`` is FastAPI

    seen = []
    real = app_module.simulate_league

    def recording(*args, **kwargs):
        seen.append(kwargs.get("keepers"))
        settings, projections, _sims, *rest = args
        return real(settings, projections, 2, *rest, **{**kwargs, "workers": 1})  # 2 drafts do

    monkeypatch.setattr(app_module, "simulate_league", recording)
    (a, _), (b, _) = best(client, 2)
    s = create(
        client,
        survival="simulate",
        survival_sims=10,
        fit_curve=False,
        keepers=[{"round": 2, "player_id": a}, {"position": 1, "round": 1, "player_id": b}],
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        s = client.get(f"/sessions/{s['id']}").json()
        if s["survival"]["status"] != "building":
            break
        time.sleep(0.2)
    assert s["survival"]["status"] == "ready", s["survival"]
    assert seen == [[Keeper(2, 2, a), Keeper(1, 1, b)]]


def yahoo_client(fake, store):
    from pickandroll.sources.yahoo import YahooLeague

    app = create_app(store, data_dir=DATA, league_factory=lambda lid: YahooLeague(lid, query=fake))
    return TestClient(app)


@pytest.mark.parametrize("carried", [True, False])
def test_yahoo_feed_passes_a_keeper_slot(store, carried):
    """The feed may carry the keeper at his slot (a no-op) or leave the slot out; either way
    the feed goes on past it."""
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    from .fakes import FakeQuery

    fake = FakeQuery(
        names=["Nikola Jokic", "Luka Doncic", "James Harden", "Nobody Real", "Stephen Curry"]
    )
    with yahoo_client(fake, store) as c:
        # Yahoo seats me 2 ("Me"); team 3 keeps the third Yahoo player in round 1 (pick 3).
        s = create(c, num_teams=12, my_position=5, objective="sum")
        sid = s["id"]
        attached = c.post(
            f"/sessions/{sid}/yahoo", json={"league_id": "12345", "start": False}
        ).json()
        kept = store.get(sid).state.projections.df.index[
            store.get(sid).state.projections.df["player"] == "James Harden"
        ][0]
        assert attached["session"]["my_position"] == 2
        r = c.patch(
            f"/sessions/{sid}/keepers",
            json={"keepers": [{"position": 3, "round": 1, "player_id": kept}]},
        )
        assert r.status_code == 200, r.text
        third = ("466.l.12345.t.3", "466.p.2") if carried else ("466.l.12345.t.3", "466.p.3")
        fake.picks = [
            ("466.l.12345.t.2", "466.p.0"),
            ("466.l.12345.t.1", "466.p.1"),
            third,
            ("466.l.12345.t.4", "466.p.4"),
        ]
        applied = c.post(f"/sessions/{sid}/yahoo/poll").json()["applied"]
        assert [(p["overall"], p["keeper"]) for p in applied] == [
            (1, False),
            (2, False),
            (3, True),
            (4, False),
        ]
        assert c.post(f"/sessions/{sid}/yahoo/poll").json()["applied"] == []
        status = c.get(f"/sessions/{sid}/yahoo").json()
        assert status["last_error"] is None and status["polls"] == 2
        assert c.get(f"/sessions/{sid}").json()["next_overall"] == 5


def test_yahoo_feed_stops_at_someone_else_in_a_keeper_slot(store):
    if not (DATA / SAMPLE).exists():
        pytest.skip("no Basketball Monster sample export in data/")
    from .fakes import FakeQuery

    fake = FakeQuery(names=["Nikola Jokic", "Luka Doncic", "James Harden", "Stephen Curry"])
    with yahoo_client(fake, store) as c:
        sid = create(c, num_teams=12, my_position=5, objective="sum")["id"]
        c.post(f"/sessions/{sid}/yahoo", json={"league_id": "12345", "start": False})
        df = store.get(sid).state.projections.df
        kept = df.index[df["player"] == "James Harden"][0]
        c.patch(
            f"/sessions/{sid}/keepers",
            json={"keepers": [{"position": 3, "round": 1, "player_id": kept}]},
        )
        fake.picks = [
            ("466.l.12345.t.2", "466.p.0"),
            ("466.l.12345.t.1", "466.p.1"),
            ("466.l.12345.t.3", "466.p.3"),
        ]
        r = c.post(f"/sessions/{sid}/yahoo/poll")
        assert r.status_code == 200, r.text
        assert [(p["overall"], p["keeper"]) for p in r.json()["applied"]] == [
            (1, False),
            (2, False),
            (3, True),
        ]
        status = c.get(f"/sessions/{sid}/yahoo").json()
        assert status["last_error"].startswith("pick 3: pick 3 is a keeper slot")
        # The next poll stops at the same place: nothing applied, the error still shown.
        assert c.post(f"/sessions/{sid}/yahoo/poll").json()["applied"] == []
        assert c.get(f"/sessions/{sid}").json()["next_overall"] == 4


def test_projection_players_for_the_setup_typeahead(client):
    (a, name), _ = best(client, 2)
    players = client.get(f"/projections/players?file={SAMPLE}").json()
    assert [p["name"] for p in players] == sorted(p["name"] for p in players)
    (row,) = [p for p in players if p["player_id"] == a]
    assert row["name"] == name and row["team"]
    assert client.get(f"/projections/players?file={SAMPLE}").json() == players  # cached
    assert client.get("/projections/players?file=nope.xls").status_code == 400
    assert client.get(f"/projections/players?file=../data/{SAMPLE}").status_code == 400
    assert client.get(f"/projections/players?file={DATA / SAMPLE}").status_code == 400
