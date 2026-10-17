"""Games haircuts (#76): the scaling of a player's totals, the z recompute, the session fields,
the PATCH mid-draft (picks untouched, the plan re-solved, the ledger and a rebuild), a league's
adjustments.json at attach, and the scorecard's note. Synthetic players only."""

from __future__ import annotations

import json
from concurrent.futures import Future

import pytest

from pickandroll.api.presolve import BranchBook, branch_boards, likely_next
from pickandroll.projections.adjustments import SCALED_COLS, games_fraction, scale_games
from pickandroll.projections.schema import STAT_COLS
from pickandroll.projections.zscores import zscores

from .test_draft_state import make_state
from .test_leagues import QUICK, write_league
from .test_yahoo_room import SESSION, app_for, attach, build_league, post_picks


# --------------------------------------------------------------------------- the scaling
def test_a_haircut_scales_his_totals_and_nothing_else(pool):
    pool = pool.assign(fpts=pool["pts"] + pool["reb"])
    out = scale_games(pool, {"p3": 0.75})
    for col in (*STAT_COLS, "minutes", "games", "fpts"):
        assert out.at["p3", col] == pytest.approx(0.75 * pool.at["p3", col])
    # Per game and the percentages stay as projected.
    assert out.at["p3", "pts"] / out.at["p3", "games"] == pytest.approx(
        pool.at["p3", "pts"] / pool.at["p3", "games"]
    )
    assert out.at["p3", "fgm"] / out.at["p3", "fga"] == pytest.approx(
        pool.at["p3", "fgm"] / pool.at["p3", "fga"]
    )
    others = pool.index != "p3"
    assert out.loc[others].equals(pool.loc[others])
    assert set(SCALED_COLS) >= {*STAT_COLS, "games", "minutes", "fpts"}
    assert scale_games(pool, {}).equals(pool)


def test_games_out_is_a_share_of_his_games_and_bad_input_is_refused(pool):
    assert games_fraction(60.0, 15.0) == pytest.approx(0.75)
    assert games_fraction(60.0, 90.0) == 0.0 and games_fraction(0.0, 5.0) == 0.0
    with pytest.raises(ValueError):
        games_fraction(60.0, -1.0)
    with pytest.raises(KeyError):
        scale_games(pool, {"nobody": 0.5})
    with pytest.raises(ValueError):
        scale_games(pool, {"p1": 1.5})


def test_the_state_recomputes_z_over_the_scaled_table_and_can_undo_it(pool):
    state = make_state(pool)
    base_z = state.z.copy()
    top = base_z["total"].idxmax()
    state.apply_pick("Team 1", top, 1)
    picks = list(state.picks)
    state.set_adjustments({top: 0.5, "p5": 1.0})
    # A fraction of one is no haircut.
    assert state.adjustments == {top: 0.5}
    assert state.projections.df.at[top, "games"] == pytest.approx(0.5 * pool.at[top, "games"])
    assert state.base_projections.df.equals(pool)
    expected = zscores(
        scale_games(pool, {top: 0.5}), state.settings.cats, pool_size=state.settings.total_picks
    )
    assert state.z.equals(expected)
    assert state.z.at[top, "pts"] < base_z.at[top, "pts"]
    assert state.z.at[top, "total"] < base_z.at[top, "total"]
    assert state.picks == picks
    state.set_adjustments({})
    assert state.adjustments == {} and state.z.equals(base_z)
    assert state.projections.df.equals(pool)


def test_a_cleared_branch_book_drops_old_plans_and_late_ones(pool):
    state = make_state(pool, position=3)
    pairs = branch_boards(state, likely_next(state, None))
    book = BranchBook()
    queued = Future()
    book.add(pairs[0], future=queued)
    epoch = book.epoch
    book.clear()
    assert queued.cancelled() and not book.entries and book.epoch == epoch + 1
    # A branch built on a board copied before the clear is not booked.
    book.add(pairs[1], future=None, epoch=epoch)
    assert not book.entries
    book.add(pairs[1], future=None, epoch=book.epoch)
    assert set(book.entries) == {pairs[1].key}


# --------------------------------------------------------------------------- the session
@pytest.fixture
def league(tmp_path):
    picks = build_league(tmp_path)
    return tmp_path, picks


def _best(client, sid, n=5):
    return client.get(f"/sessions/{sid}/board?limit={n}").json()["players"]


def test_adjustments_at_create_show_in_the_summary_and_on_the_board(league):
    directory, _ = league
    with app_for(directory) as c:
        plain = c.post("/sessions", json=SESSION).json()
        top, second = _best(c, plain["id"], 2)
        body = {
            **SESSION,
            "adjustments": [
                {"player": top["name"], "games_out": 14, "note": "out 4 weeks"},
                {"player_id": second["player_id"], "games_fraction": 0.5},
            ],
        }
        s = c.post("/sessions", json=body)
        assert s.status_code == 201, s.text
        s = s.json()
        cuts = {a["player_id"]: a for a in s["adjustments"]}
        assert cuts[top["player_id"]]["games_out"] == 14
        assert cuts[top["player_id"]]["games_left"] == pytest.approx(top["games"] - 14)
        assert cuts[top["player_id"]]["note"] == "out 4 weeks"
        assert cuts[second["player_id"]]["fraction"] == 0.5
        board = {p["player_id"]: p for p in _best(c, s["id"], 300)}
        assert board[top["player_id"]]["games"] == pytest.approx(top["games"] - 14)
        assert board[top["player_id"]]["total"] < top["total"]
        assert board[top["player_id"]]["adjustment"]["games_out"] == 14
        assert board[second["player_id"]]["adjustment"]["fraction"] == 0.5
        assert all(
            p["adjustment"] is None
            for pid, p in board.items()
            if pid not in (top["player_id"], second["player_id"])
        )
        # The request's own rows are strict.
        bad = c.post("/sessions", json={**SESSION, "adjustments": [{"player": "Nobody Here"}]})
        assert bad.status_code == 422
        bad = c.post(
            "/sessions",
            json={**SESSION, "adjustments": [{"player": "Nobody Here", "games_out": 3}]},
        )
        assert bad.status_code == 400 and "Nobody Here" in bad.json()["detail"]


def test_a_patch_mid_draft_rescales_resolves_and_leaves_the_picks(league):
    directory, picks = league
    with app_for(directory) as c:
        room = attach(c)
        sid = room["session_id"]
        post_picks(c, "d1", picks[:30])
        before = c.get(f"/sessions/{sid}/picks").json()
        version = c.get(f"/sessions/{sid}").json()["version"]
        player = next(p for p in _best(c, sid, 300) if not p["taken"])
        r = c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": player["player_id"], "games_out": 35}]},
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["changed"] == [player["player_id"]] and out["version"] > version
        assert c.get(f"/sessions/{sid}/picks").json() == before
        now = {p["player_id"]: p for p in _best(c, sid, 300)}[player["player_id"]]
        assert now["games"] == pytest.approx(player["games"] - 35)
        assert now["total"] < player["total"] and now["adjustment"]["games_out"] == 35
        summary = c.get(f"/sessions/{sid}").json()
        assert summary["picks_made"] == 30 and len(summary["adjustments"]) == 1
        # The plan solves again on the new board, with the pick log as it was.
        plan = c.get("/rooms/d1/plan?wait=15").json()
        assert plan["fresh"] is True and plan["candidates"]
        # A second row adds to the table; a haircut of nothing clears his.
        other = next(
            p
            for p in _best(c, sid, 300)
            if not p["taken"] and p["player_id"] != player["player_id"]
        )
        c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": other["player_id"], "games_fraction": 0.9}]},
        )
        r = c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": player["player_id"], "games_out": 0}]},
        ).json()
        assert [a["player_id"] for a in r["adjustments"]] == [other["player_id"]]
        back = {p["player_id"]: p for p in _best(c, sid, 300)}[player["player_id"]]
        assert back["games"] == pytest.approx(player["games"]) and back["adjustment"] is None
        bad = c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": "nobody", "games_out": 3}]},
        )
        assert bad.status_code == 400
        assert c.get(f"/sessions/{sid}/picks").json() == before
    log = [json.loads(line) for line in (directory / "fidelity" / "d1.jsonl").open()]
    cuts = [e for e in log if e["type"] == "adjustments"]
    assert len(cuts) == 3 and cuts[0]["changed"] == [player["player_id"]]
    assert cuts[0]["names"][player["player_id"]] == player["name"] and cuts[0]["board"] == 30


def test_a_rebuild_keeps_the_haircuts_set_mid_draft(league):
    directory, picks = league
    with app_for(directory) as c:
        sid = attach(c)["session_id"]
        post_picks(c, "d1", picks[:12])
        player = next(p for p in _best(c, sid, 300) if not p["taken"])
        c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": player["player_id"], "games_fraction": 0.6}]},
        )
    with app_for(directory) as c:
        room = c.post("/rooms", json={"draft_id": "d1"}).json()
        assert room["resumed"] is True and room["picks_applied"] == 12
        cuts = room["session"]["adjustments"]
        assert [(a["player_id"], a["fraction"]) for a in cuts] == [(player["player_id"], 0.6)]


def test_the_scorecard_notes_the_turns_solved_under_a_haircut(league):
    directory, picks = league
    with app_for(directory) as c:
        sid = attach(c, slot=1)["session_id"]
        post_picks(c, "d1", picks[:23])
        assert c.get("/rooms/d1/plan?wait=15").json()["fresh"]
        post_picks(c, "d1", picks[23:24])  # my pick 24
        player = next(p for p in _best(c, sid, 300) if not p["taken"])
        c.patch(
            f"/sessions/{sid}/adjustments",
            json={"adjustments": [{"player_id": player["player_id"], "games_out": 20}]},
        )
        assert c.get("/rooms/d1/plan?wait=15").json()["fresh"]
        post_picks(c, "d1", picks[24:25])  # my pick 25
        card = c.get("/rooms/d1/fidelity").json()
        md = c.get("/rooms/d1/fidelity?format=md").text
    rows = {r["overall"]: r for r in card["rows"]}
    assert rows[24]["adjusted"] == [] and rows[25]["adjusted"] == [player["name"]]
    assert card["adjusted_turns"] == [{"overall": 25, "players": [player["name"]]}]
    assert f"Games haircuts: pick 25 solved under one ({player['name']})." in md


def test_a_card_without_haircuts_says_nothing_of_them(league):
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:2])
        card = c.get("/rooms/d1/fidelity").json()
        md = c.get("/rooms/d1/fidelity?format=md").text
    assert card["haircuts"] is False and card["adjusted_turns"] == []
    assert "haircut" not in md


# --------------------------------------------------------------------------- the league file
def test_a_league_file_is_applied_at_attach_and_a_bad_entry_is_skipped(tmp_path):
    build_league(tmp_path)
    folder = write_league(tmp_path)
    with app_for(tmp_path) as c:
        plain = c.post("/sessions", json={**QUICK, "league": "555"}).json()
        top = _best(c, plain["id"], 1)[0]
    (folder / "adjustments.json").write_text(
        json.dumps(
            [
                {"player": top["name"], "games_out": 15, "note": "out 4 weeks"},
                {"player": "Nobody Here", "games_out": 3},
                {"player": top["name"]},
            ]
        )
    )
    with app_for(tmp_path) as c:
        body = {"draft_id": "555", "slot": 4, "session": {**QUICK, "league": "555"}}
        r = c.post("/rooms", json=body)
        assert r.status_code == 201, r.text
        session = r.json()["session"]
        assert [(a["player_id"], a["games_out"]) for a in session["adjustments"]] == [
            (top["player_id"], 15)
        ]
        notes = " | ".join(session["adjustments_note"])
        assert "Nobody Here" in notes and "entry 3" in notes
    log = [json.loads(line) for line in (tmp_path / "fidelity" / "555.jsonl").open()]
    record = next(e for e in log if e["type"] == "attach")
    assert record["adjustments"] == [{"player_id": top["player_id"], "name": top["name"]}]
    # Resolved by id on the record: a rebuild never re-reads the file.
    assert record["session"]["adjustments_file"] is None
    (folder / "adjustments.json").write_text("not json")
    with app_for(tmp_path) as c:
        room = c.post("/rooms", json={"draft_id": "555"}).json()
        assert [a["player_id"] for a in room["session"]["adjustments"]] == [top["player_id"]]
        # A file that does not read never stops a new league session.
        fresh = c.post("/sessions", json={**QUICK, "league": "555"})
        assert fresh.status_code == 201, fresh.text
        assert fresh.json()["adjustments"] == []
        assert "does not read" in fresh.json()["adjustments_note"][0]


def test_a_session_from_before_haircuts_rebuilds_without_any(league):
    """An attach record from before #76 has no adjustments in its session: none apply."""
    directory, picks = league
    with app_for(directory) as c:
        attach(c)
        post_picks(c, "d1", picks[:3])
    path = directory / "fidelity" / "d1.jsonl"
    log = [json.loads(line) for line in path.open()]
    for e in log:
        if e["type"] == "attach":
            e.pop("adjustments", None)
            for key in ("adjustments", "adjustments_file"):
                e["session"].pop(key, None)
    path.write_text("".join(json.dumps(e) + "\n" for e in log))
    with app_for(directory) as c:
        room = c.post("/rooms", json={"draft_id": "d1"}).json()
        assert room["session"]["adjustments"] == [] and room["picks_applied"] == 3
        assert c.get("/rooms/d1/fidelity").json()["haircuts"] is False


def test_replace_swaps_the_whole_table(pool):
    """PATCH replace semantics, on the resolver itself."""
    from pickandroll.api.adjustments import AdjustmentIn, resolve

    rows = [("r0", AdjustmentIn(player_id="p1", games_out=5))]
    table, _ = resolve(rows, pool, [{"player_id": "p2", "games_fraction": 0.5}])
    assert [e["player_id"] for e in table] == ["p2", "p1"]
    table, _ = resolve(rows, pool, ())
    assert table == [{"player_id": "p1", "games_out": 5.0}]
    unmatched = [("r1", AdjustmentIn(player="Nobody", games_out=5))]
    table, skipped = resolve(unmatched, pool, (), strict=False)
    assert table == [] and "Nobody" in skipped[0]
