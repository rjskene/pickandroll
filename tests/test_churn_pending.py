"""A churn's placed claim once its held drop landed (#411). A churn (#221) runs in three steps:
its held player H is dropped, the claim goes in on the add page with no drop, and it waits for
Yahoo's run. The queue entry keeps ``drop`` = H, but Yahoo holds the claim as an open-spot claim,
so the builds read it as one: still pending with H off my roster, folded into the roster it
will leave, judged again as a no-drop claim, and cancelled by its no-drop id.

Made-up leagues throughout (``test_pending``'s, ``test_moves``'s)."""

from __future__ import annotations

from datetime import UTC, datetime

from pickandroll.api import season_autopilot as sa
from pickandroll.api import season_moves
from pickandroll.season import autopilot as qa
from pickandroll.season import moves as mv
from tests.test_pending import CLEAR, built_of, entry, one_spot, pool_row

H = 9


def churn(add: int, **kw) -> dict:
    """A churn's entry dropping held player H for ``add``, placed: its drop run on record when
    ``ran`` is given."""
    ran = kw.pop("ran", qa.DROPPED)
    e = {
        **entry(add, H, **{"from": CLEAR.isoformat()}),
        "basis": qa.CHURN,
        "held_drop": {"player": H, "slot": "IL"},
        **kw,
    }
    return e if ran is None else {**e, "drop_run": {"outcome": ran}}


def test_the_drop_a_claim_carries_at_yahoo():
    assert qa.claim_drop(churn(10)) is None
    # Before its drop run, or with the drop not landed, the churn keeps H.
    assert qa.claim_drop(churn(10, ran=None)) == H
    assert qa.claim_drop(churn(10, ran="failed")) == H
    # Any other claim keeps its own drop.
    assert qa.claim_drop(entry(10, 3)) == 3
    assert qa.claim_drop(entry(10)) is None
    assert qa.claim_drop({**entry(10, 3), "drop_run": {"outcome": qa.DROPPED}}) == 3


def test_a_placed_churn_whose_held_drop_landed_is_pending_as_an_open_spot_claim():
    pool = {10: pool_row(10)}
    # H is off my roster: the churn's claim is pending with no drop, as the due list placed it.
    [c] = season_moves.pending_claims({1, 2, 3}, pool, [churn(10)])
    assert c == mv.Pending(10, pool[10].player, None, CLEAR)
    # Before its drop run the churn is as today: pending with H while H is mine, settled once
    # he is not.
    [c] = season_moves.pending_claims({1, 2, 3, H}, pool, [churn(10, ran=None)])
    assert c.drop == H
    assert season_moves.pending_claims({1, 2, 3}, pool, [churn(10, ran=None)]) == ()
    # A plain claim whose drop left my roster is settled, as today: Yahoo voids it.
    assert season_moves.pending_claims({1, 2, 3}, pool, [entry(10, H)]) == ()


def test_the_fold_makes_it_so_its_add_leaves_the_candidates_and_its_spot_is_taken():
    p, _ = one_spot()
    pending = season_moves.pending_claims({k for k, _ in p.roster}, {10: pool_row(10)}, [churn(10)])
    q, _ = season_moves.fold(p, pending)
    assert 10 in dict(q.roster) and 10 not in dict(q.candidates) and q.pending == {10}
    assert mv.open_spots(p) == 1 and mv.open_spots(q) == 0
    # A second open-spot add no longer fits the spot the churn's claim takes.
    assert not mv.feasible(q, [mv.Move(11)])


def test_the_rejudge_judges_it_as_a_no_drop_claim():
    p, players = one_spot()
    built = built_of(p, [mv.Pending(10, players[10], None, CLEAR)])
    e = {**churn(10), "id": "c", "judged": "week"}
    out = season_moves.rejudge_claims(built, [e], {})
    assert out["c"] is not None and "no_room" not in out["c"]
    assert out["c"]["gain"] == mv.Evaluator(p).gain("week", [mv.Move(10)])
    # A second open-spot claim competes with it for the one spot.
    built = built_of(
        p, [mv.Pending(10, players[10], None, CLEAR), mv.Pending(11, players[11], None, CLEAR)]
    )
    other = {**entry(11), "id": "o", "judged": "week"}
    out = season_moves.rejudge_claims(built, [e, other], {})
    assert [k for k in ("c", "o") if out[k].get("no_room")] == ["o"]


def test_a_cancel_names_the_claim_as_yahoo_holds_it():
    today = CLEAR
    at = datetime(today.year, today.month, today.day, 18, tzinfo=UTC).isoformat()
    verdict = {"verdict": qa.CANCEL, "reason": "worth less now", "at": at}
    e = {**churn(10), "league": "1", "rejudge": verdict}
    [c] = sa.cancel_due([e], "1", today)
    assert c["drop"] is None and sa.claim_id(4, c["add"], c["drop"]) == "4_10_0"
    # A plain claim's cancel keeps its drop.
    [c] = sa.cancel_due([{**entry(10, 3), "league": "1", "rejudge": verdict}], "1", today)
    assert c["drop"] == 3 and sa.claim_id(4, c["add"], c["drop"]) == "4_10_3"
