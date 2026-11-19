"""The keep list (#442, the user's ruling of 2026-11-19): a player the user keeps for next season
is protected by the keep rule, "on the keep list", so no set, plan, comeback, pick's drop or
strategy run drops the player. Every league and id here is made up (``test_moves``'s,
``test_activation``'s and ``test_season``'s fixtures); no name from the user's list appears."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date

from pickandroll.api import season_keep, season_queue
from pickandroll.api import season_moves as sm
from pickandroll.api import season_strategy as ss
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from pickandroll.season import picks as pk

from .test_activation import BACK, PLAN, SCORE, STREAMER, WEAK
from .test_activation import league as cleared_league
from .test_lift import bump
from .test_moves import WEEKS, build, player, rates, schedule
from .test_season import LEAGUE, client, fixture_names, projection_csv  # noqa: F401
from .test_season_guard import built_of

#: My made-up player the plain solve drops.
KEEPER = 3


def two_adds() -> mv.MoveProblem:
    """Two adds worth making against my weakest two (3, then 2); no add limit."""
    sched = schedule({"MIN": list(range(28))})
    roster = [player(1, "MIN"), player(2, "MIN"), player(KEEPER, "MIN")]
    cands = [player(10, "MIN"), player(11, "MIN")]
    rate = {1: rates(1.0), 2: rates(0.5), KEEPER: rates(0.4), 10: rates(1.5), 11: rates(0.62)}
    opp = [player(20, "MIN"), player(21, "MIN"), player(22, "MIN")]
    rate |= {20: rates(1.0), 21: rates(0.9), 22: rates(0.7)}
    p = build(roster, cands, rate, sched, opp, [opp])
    return replace(
        p, season_end=WEEKS[-1][-1], season_value={1: 3.0, 2: 0.5, KEEPER: 0.2, 10: 2.0, 11: 1.0}
    )


def kept(p: mv.MoveProblem, listed=frozenset()) -> tuple[mv.MoveProblem, mv.KeepRule]:
    """``p`` with ``listed`` on the keep list and the keep rule applied, as the build does."""
    q = replace(p, listed=frozenset(listed))
    rule = mv.keep_rule(q)
    return replace(q, kept=rule.kept), rule


def drops_of(out: dict) -> set[int]:
    """Every drop the payload recommends or plans: the sets, the comebacks, the streaming plan
    and every week plan's steps."""
    found: set[int] = set()
    for rec in out["recommended"].values():
        found |= {m["drop"] for m in rec["moves"] if m["drop"] is not None}
        for rows in (rec.get("comebacks") or {}).values():
            found |= {c["drop"] for c in rows if c.get("drop") is not None}
    for s in ((out.get("plan") or {}).get("steps")) or []:
        found |= {s["drop"]} if s.get("drop") is not None else set()
    for plan in (out.get("week_plans") or {}).get("plans") or []:
        found |= {s["drop"] for s in plan["steps"] if s.get("drop") is not None}
    return found


# --------------------------------------------------------------------------- the engine
def test_a_listed_player_is_protected_and_no_set_or_plan_drops_them():
    plain, rule = kept(two_adds())
    assert not rule.players[KEEPER].protected
    out = sm._payload(built_of(plain, rule=rule))
    assert KEEPER in drops_of(out)
    p, rule = kept(two_adds(), {KEEPER})
    row = rule.players[KEEPER]
    assert row.protected and row.listed and KEEPER in p.kept
    out = sm._payload(built_of(p, rule=rule))
    assert KEEPER not in drops_of(out)
    # The page marks the player protected on the list, and the queue's reason says so.
    [k] = [r for r in out["keep_rule"]["players"] if r["player"] == KEEPER]
    assert k["protected"] and k["listed"]
    assert season_queue.protected_of(rule)[KEEPER] == qa.LISTED_REASON == "on the keep list"
    # Never one of the lift's marginal players.
    assert KEEPER not in mv.marginal_of(p, 3)


def test_a_strategy_run_never_drops_a_listed_player():
    p, rule = kept(two_adds(), {KEEPER})
    built = built_of(p, rule=rule)
    answer = sm._payload(built)
    run = ss.Run(("k",), built, lambda: answer, ss.Settings(weights=("week", "season")), 1)
    run.run()
    out = run.payload()
    assert out["status"] == "solved"
    for point in out["points"]:
        assert all(m["drop"] != KEEPER for m in point["moves"]), point


def test_no_comeback_sends_a_listed_player_even_when_every_other_is_kept():
    p, _ = kept(cleared_league())
    [c] = mv.comebacks(p, "week", ())
    assert (c.player, c.drop) == (BACK, STREAMER)
    p, _ = kept(cleared_league(), {STREAMER})
    [c] = mv.comebacks(p, "week", ())
    assert c.drop != STREAMER
    assert mv.choose_activation(p, SCORE, None, PLAN).get(BACK) != STREAMER
    # Everyone else kept too: the comeback sends a kept player, never the listed one.
    others = frozenset(k for k, _ in p.roster) - {STREAMER}
    assert WEAK in others
    [c] = mv.comebacks(replace(p, kept=p.kept | others), "week", ())
    assert c.drop != STREAMER


def test_a_pick_naming_a_listed_player_as_its_drop_is_skipped():
    p, _ = kept(two_adds(), {KEEPER})
    pick = pk.Pick(10, None, KEEPER, None, date(2026, 11, 30), "dashboard", "")
    made, skipped = pk.forced(p, [pick], SCORE)
    assert made == [] and [s.reason for s in skipped] == [pk.DROP_KEPT]
    # With no drop named, the pick takes another.
    made, _ = pk.forced(p, [replace(pick, drop=None)], SCORE)
    assert [f.move.drop for f in made] != [KEEPER]


def test_an_empty_list_gives_todays_payload_byte_for_byte():
    p, rule = kept(two_adds())
    q, rule_q = kept(two_adds(), frozenset())
    a, b = sm._payload(built_of(p, rule=rule)), sm._payload(built_of(q, rule=rule_q))
    for out in (a, b):
        out["search"].pop("seconds")
    assert json.dumps(a) == json.dumps(b)
    assert all("listed" not in r for r in a["keep_rule"]["players"])


# --------------------------------------------------------------------------- the store
def test_the_store_sets_replaces_and_removes_and_refuses_a_file_that_does_not_read(tmp_path):
    assert season_keep.load(tmp_path) == [] and season_keep.in_force(tmp_path, "1") == frozenset()
    season_keep.set_keep(tmp_path, 7, "P7", None, "dashboard")
    season_keep.set_keep(tmp_path, 8, "P8", ["2"], "dashboard")
    assert season_keep.in_force(tmp_path, "1") == {7}
    assert season_keep.in_force(tmp_path, "2") == {7, 8}
    season_keep.set_keep(tmp_path, 7, "P7", ["1"], "a session")
    rows = season_keep.payload(tmp_path)["keep"]
    assert [(r["player"], r["leagues"], r["by"]) for r in rows] == [
        (8, ["2"], "dashboard"),
        (7, ["1"], "a session"),
    ]
    assert season_keep.remove(tmp_path, 8) and not season_keep.remove(tmp_path, 8)
    path = season_keep.path_of(tmp_path)
    path.write_text("{not json")
    assert season_keep.in_force(tmp_path, "1") == frozenset()
    try:
        season_keep.set_keep(tmp_path, 9, None, None, "dashboard")
    except season_keep.KeepError:
        pass
    else:  # pragma: no cover - the refusal is the test
        raise AssertionError("a file that does not read was overwritten")
    assert path.read_text() == "{not json"


# --------------------------------------------------------------------------- the routes
def test_the_routes_set_and_remove_an_entry_and_the_moves_solve_again(client):  # noqa: F811
    projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
    client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    before = client.get(f"/seasons/{LEAGUE}/moves").json()
    assert client.get("/autopilot/keep").json() == {"keep": []}
    # An empty list on file: today's moves byte for byte.
    path = season_keep.path_of(client.data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"keep": []}))
    bump(client)
    empty = client.get(f"/seasons/{LEAGUE}/moves").json()
    for out in (before, empty):
        out["search"].pop("seconds")
        out.pop("stale", None)
    assert json.dumps(empty, sort_keys=True) == json.dumps(before, sort_keys=True)
    # List one of my players: the stamp moves, the solve marks them on the list.
    mine = [r["player"] for r in before["keep_rule"]["players"]]
    assert mine
    svc = client.app.state.seasons
    stamp = svc._moves_stamp(LEAGUE)
    r = client.put("/autopilot/keep", json={"player": mine[0], "leagues": [LEAGUE]})
    assert r.status_code == 200, r.text
    assert [e["player"] for e in r.json()["keep"]] == [mine[0]]
    assert svc._moves_stamp(LEAGUE) != stamp
    after = client.get(f"/seasons/{LEAGUE}/moves").json()
    [k] = [x for x in after["keep_rule"]["players"] if x["player"] == mine[0]]
    assert k["protected"] and k["listed"]
    assert mine[0] not in drops_of(after)
    assert client.delete(f"/autopilot/keep/{mine[0]}").json() == {"keep": []}
    assert client.delete(f"/autopilot/keep/{mine[0]}").status_code == 404
    assert client.put("/autopilot/keep", json={}).status_code == 422
    path.write_text("{not json")
    assert client.get("/autopilot/keep").status_code == 409
