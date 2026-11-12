"""My claims placed and not yet processed, counted in the moves solve (#360): a no-drop claim
takes its open spot, a claim's drop is gone and its add is mine from the clear day, so no
later solve places a second claim into one spot (223259 and 31153, 2026-11-09) and the
re-judge cancels a no-drop claim the room no longer fits. A claim the read says Yahoo's run
already settled is not pending. Nothing here opens a page.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

from pickandroll.api import season_moves
from pickandroll.season import Player
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from tests.test_held_cleared import hold
from tests.test_moves import WEEKS, build, player, rates, streaming_league
from tests.test_moves_queue import queued
from tests.test_season import LEAGUE, client  # noqa: F401 - the fixture

CLEAR = WEEKS[0][1]


def one_spot(**kw):
    """The streaming league with four active spots for three players: one spot open."""
    roster, cands, rate, sched, opponent, field = streaming_league()
    cands = [*cands, player(12, "HLD")]
    rate = {**rate, 12: rates(0.8)}
    return build(roster, cands, rate, sched, opponent, field, spots=4, **kw), dict(cands)


def claim(players, add: int, drop: int | None = None) -> mv.Pending:
    return mv.Pending(add, players[add], drop, CLEAR)


def folded(p, pending):
    return season_moves.fold(p, pending)[0]


# --------------------------------------------------------------------------- the fold
def test_a_no_drop_claim_takes_the_open_spot_so_no_second_add_fits_it():
    p, players = one_spot()
    assert mv.open_spots(p) == 1 and mv.feasible(p, [mv.Move(11)])
    q = folded(p, [claim(players, 10)])
    # 10 is on the roster from the clear day, out of the candidates, and kept.
    assert 10 in dict(q.roster) and 10 not in dict(q.candidates)
    assert q.returns[10] == CLEAR and q.pending == {10} and 10 in q.kept
    assert mv.open_spots(q) == 0
    # A second no-drop add has no spot left; an add with a drop still fits.
    assert not mv.feasible(q, [mv.Move(11)])
    assert mv.feasible(q, [mv.Move(11, 3)])
    # The claim's add is never a drop option: Yahoo's run has not made him mine.
    assert 10 not in mv.drop_options(q)
    assert mv.overfull(q) == 0


def test_a_claim_with_a_drop_leaves_the_room_as_it_was_and_its_drop_is_no_option():
    p, players = one_spot()
    q = folded(p, [claim(players, 10, 3)])
    assert 3 not in dict(q.roster) and 3 not in mv.drop_options(q)
    assert mv.open_spots(q) == mv.open_spots(p) == 1
    assert mv.feasible(q, [mv.Move(11)])


def test_the_solve_values_a_set_with_the_claim_made():
    p, players = one_spot()
    q = folded(p, [claim(players, 10)])
    # The base is the roster with the claim made: the streamer plays from his clear day.
    with_claim = mv.Evaluator(p).value("week", [mv.Move(10, None, CLEAR)])
    assert mv.Evaluator(q).base["week"] == with_claim
    # Nothing pending: the problem is the same one.
    assert mv.with_pending(p, ()) is p


def test_a_claims_add_on_the_way_never_goes_to_a_held_slot():
    p, _ = one_spot(held_open={"IL": 1})
    hurt = mv.Pending(10, Player(10, "P10", "STR", ("C",), status="O"), None, CLEAR)
    q = folded(p, [hurt])
    assert 10 not in mv.room(q).eligible
    assert all(k != 10 for k, _ in mv.held_moves(q))


def test_two_no_drop_claims_for_one_spot_leave_the_roster_overfull():
    p, players = one_spot()
    q = folded(p, [claim(players, 10), claim(players, 11)])
    assert mv.overfull(q) == 1 and mv.open_spots(q) == 0


# --------------------------------------------------------------------------- what is pending
def pool_row(add: int, availability: str = "W", clears: date | None = CLEAR):
    return SimpleNamespace(
        player=Player(add, f"P{add}", "STR", ("C",)), availability=availability, clears=clears
    )


def entry(add: int, drop: int | None = None, **kw):
    return {"id": f"x:{add}:{drop or 0}", "add": add, "drop": drop, "outcome": "claimed", **kw}


def test_a_claim_the_read_says_was_settled_is_not_pending():
    mine = {1, 2, 3}
    pool = {10: pool_row(10), 11: pool_row(11), 12: pool_row(12, "FA"), 13: pool_row(13)}
    claims = [
        entry(10, None, **{"from": CLEAR.isoformat()}),  # pending
        entry(1),  # landed: his add is on my roster, never counted twice
        entry(11, 9),  # its drop is off my roster: Yahoo voids it
        entry(12),  # a free agent again: the claim failed, it holds no spot
        entry(14),  # out of the pool: another team took him
        entry(13, resolved="lost"),
        entry(13, outcome="added"),  # a free agent added at once is on the roster read
        entry(10, None),  # the same add once
    ]
    got = season_moves.pending_claims(mine, pool, claims)
    assert got == (mv.Pending(10, pool[10].player, None, CLEAR),)
    # The clear day is the entry's, else the pool's.
    later = CLEAR + timedelta(days=1)
    [c] = season_moves.pending_claims(mine, {13: pool_row(13, clears=later)}, [entry(13, 2)])
    assert (c.drop, c.day) == (2, later)


# --------------------------------------------------------------------------- the re-judge
def built_of(p, pending):
    q, rule = season_moves.fold(p, pending)
    return season_moves.Built(
        problem=q,
        system={},
        horizons={},
        adds={},
        unprojected=0,
        rule=rule,
        pending=tuple(pending),
        base=p,
        real=p,
    )


def test_two_no_drop_claims_for_one_spot_keep_the_better_and_cancel_the_other():
    p, players = one_spot()
    built = built_of(p, [claim(players, 10), claim(players, 11)])
    first = {**entry(10), "id": "a", "judged": "week"}
    second = {**entry(11), "id": "b", "judged": "week"}
    out = season_moves.rejudge_claims(built, [first, second], {})
    # The streamer wins the week: he keeps the spot and is judged with nothing else made.
    assert "no_room" not in out["a"] and out["a"]["gain"] > 0
    assert out["b"] == {
        "judged": "week",
        "gain": None,
        "value": None,
        "season_costly": None,
        "comeback_drops": {},
        "no_room": [10],
        "il_need": None,
    }
    verdict = qa.rejudge_verdict(11, [], None, None, qa.Floor(-100.0, None, 0), None, {}, [10])
    assert verdict == (qa.CANCEL, "no open spot left for it: 10 takes the room")
    # Judged on the three weeks, the holder wins instead: the streamer's claim goes.
    out = season_moves.rejudge_claims(
        built, [{**first, "judged": "three"}, {**second, "judged": "three"}], {}
    )
    assert out["a"]["no_room"] == [11] and out["b"]["gain"] is not None


def test_a_claim_is_judged_with_the_other_claims_made_and_not_itself():
    p, players = one_spot()
    built = built_of(p, [claim(players, 10, 3)])
    [j] = season_moves.rejudge_claims(built, [{**entry(10, 3), "judged": "week"}], {}).values()
    assert j["gain"] == mv.Evaluator(p).gain("week", [mv.Move(10, 3)])


# --------------------------------------------------------------------------- the build (#360)
def test_the_build_judges_the_claims_when_the_room_is_overfull_and_cancels_only_the_extra(
    client,  # noqa: F811
    monkeypatch,
):
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    base = {"league": LEAGUE, "outcome": "claimed", "resolved": None, "from": "2026-10-22"}
    stays = {**base, "id": f"2026-10-20:{LEAGUE}:9001:0", "add": 9001, "drop": None}
    extra = {**base, "id": f"2026-10-20:{LEAGUE}:9002:0", "add": 9002, "drop": None}
    old = {"verdict": qa.CANCEL, "reason": "an older verdict", "at": "2026-10-20T03:00:00+00:00"}
    (folder / "2026-10-20.json").write_text(
        json.dumps({"entries": [{**stays, "rejudge": old}, extra]})
    )

    def judge(built, claims, statuses):
        assert statuses == {}  # nobody cleared: judged for the room alone
        j = {"judged": "three", "value": None, "season_costly": None, "comeback_drops": {}}
        return {
            stays["id"]: {**j, "gain": 0.4},
            extra["id"]: {**j, "gain": None, "no_room": [9001]},
        }

    monkeypatch.setattr(season_moves, "rejudge_claims", judge)
    # Not overfull: nothing judged, an older verdict lapses as before.
    monkeypatch.setattr(mv, "overfull", lambda p: 0)
    queued(client)
    written = {e["id"]: e for e in json.loads((folder / "2026-10-20.json").read_text())["entries"]}
    assert written[stays["id"]]["rejudge"]["reason"] == qa.NO_CLEARED
    assert "rejudge" not in written[extra["id"]]
    # Overfull: the claim with no room is cancelled, the one that fits keeps its place.
    monkeypatch.setattr(mv, "overfull", lambda p: 1)
    client.post("/autopilot/queue/build")
    written = {e["id"]: e for e in json.loads((folder / "2026-10-20.json").read_text())["entries"]}
    got = written[extra["id"]]["rejudge"]
    assert (got["verdict"], got["reason"], got["no_room"], got["gain"]) == (
        qa.CANCEL,
        "no open spot left for it: 9001 takes the room",
        [9001],
        None,
    )
    assert written[stays["id"]]["rejudge"]["verdict"] is None


def test_a_cleared_player_and_a_crowded_room_judge_every_claim(client, monkeypatch):  # noqa: F811
    folder = client.data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True)
    base = {"league": LEAGUE, "outcome": "claimed", "resolved": None, "from": "2026-10-22"}
    a = {**base, "id": f"2026-10-20:{LEAGUE}:9001:7", "add": 9001, "drop": 7}
    (folder / "2026-10-20.json").write_text(json.dumps({"entries": [a]}))
    j = {"judged": "three", "gain": 0.5, "value": None, "season_costly": None}
    monkeypatch.setattr(
        season_moves,
        "rejudge_claims",
        lambda built, claims, statuses: {a["id"]: {**j, "comeback_drops": {6406: 3}}},
    )
    queued(client)
    hold(client, 6406, "Q")
    client.post("/autopilot/queue/build")
    [e] = json.loads((folder / "2026-10-20.json").read_text())["entries"]
    assert e["rejudge"]["verdict"] == qa.KEEP and "no_room" not in e["rejudge"]
