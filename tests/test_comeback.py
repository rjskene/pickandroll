"""A cleared IL player's comeback that needs a drop (#318), drop first: the API's half. The steps
route offers the drop only in a live moves league under its guard, never with a protected drop or
a game begun, and his move only once a read after the drop no longer shows it; the league's log
says which drops landed and still owe their move, and the digest says each step, whatever became
of it. Nothing here opens a page: the runs are the extension's, faked.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import season_autopilot as ap
from pickandroll.api import season_queue
from pickandroll.api.seasons import nba_today
from pickandroll.routine import steps as rs
from pickandroll.sources.yahoo import public
from tests.test_held_drop import DUE, URL, drop_body
from tests.test_lineup import lineup_league, moved
from tests.test_lineup_executor import benched_thursday, dry_runs, run_body
from tests.test_moves_queue import PRIVATE, live_league
from tests.test_season import LEAGUE, NOW, fixture, season_client

DAY = date(2026, 10, 26)
AT = datetime(2026, 10, 26, 13, tzinfo=UTC)
BACK, STAY = 5, 3
ENTRY = ap.comeback_entry(BACK)


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


#: The day's page as read before the drop, and as read after it.
BEFORE = {"PG": 1, "C": 2, "BN": STAY, "IL": BACK}
AFTER = {"PG": 1, "C": 2, "IL": BACK}
READ = "2026-10-26T12:00:00+00:00"


def lineup_page(day: date = DAY, spots: dict = BEFORE, read_at: str = READ) -> dict:
    return {
        "rule": {"changes": "daily"},
        "start": DAY.isoformat(),
        "slots": ["PG", "C"],
        "players": {
            "1": {"positions": ["PG"], "nba_team": "BOS"},
            "2": {"positions": ["C"], "nba_team": "GSW"},
            "3": {"positions": ["PG"], "nba_team": "BOS"},
            "5": {"positions": ["PG"], "nba_team": "NYK"},
        },
        "alerts": [{"kind": "cleared", "player": BACK, "slot": "IL", "status": None, "drop": STAY}],
        "days": [
            {
                "date": day.isoformat(),
                "past": False,
                "recommended": [{"slot": "PG", "player": 1}, {"slot": "C", "player": 2}],
                "yahoo": {
                    "read_at": read_at,
                    "page": "dated page",
                    "slots": [{"slot": k, "player": v} for k, v in spots.items()],
                },
                "start": [],
                "sit": [],
                "games": {"recommended": 2, "yahoo": 2},
                "playing": [1, 2],
            }
        ],
    }


def gate(**over) -> dict:
    return {"protected": set(), "pending": [], **over}


def steps(
    comeback,
    *,
    mode=None,
    stop=False,
    now=AT,
    tips=None,
    day=DAY,
    today=DAY,
    spots=BEFORE,
    read_at=READ,
    no_tips=False,
) -> dict:
    return ap.steps_payload(
        LEAGUE,
        4,
        day,
        today,
        now,
        lineup_page(day, spots, read_at),
        None if no_tips else tips or {},
        mode or {"mode": "live"},
        stop,
        {"ok": True, "reason": None},
        comeback,
    )


# --------------------------------------------------------------------------- the steps
def row(stage: str, drop: int = STAY) -> dict:
    return {
        "player": BACK,
        "slot": "IL",
        "status": None,
        "tip": None,
        "drop": drop,
        "entry": ENTRY,
        "stage": stage,
    }


def landed(outcome: str = "dropped", at: datetime = AT - timedelta(hours=2)) -> list[dict]:
    return [
        {"player": BACK, "drop": STAY, "entry": ENTRY, "at": at.isoformat(), "outcome": outcome}
    ]


def test_a_comeback_starts_at_its_drop_and_only_under_the_moves_gate():
    s = steps(gate())
    assert s["comebacks"] == [row("drop")]
    assert (s["skipped"], s["returns"]) == ([], [])
    assert s["drop_page"] == public.drop_url(LEAGUE, 4)
    assert s["back"] == public.team_url(LEAGUE, 4)
    # Outside a live moves league he stays the user's.
    s = steps(None)
    assert s["comebacks"] == []
    assert s["skipped"] == [
        {"reason": ap.NEEDS_DROP, "players": [BACK], "steps": [], "comeback": True}
    ]


def test_the_private_league_and_stop_run_no_comeback():
    assert steps(gate(), mode={"mode": "off", "private": True})["comebacks"] == []
    assert steps(gate(), stop=True)["comebacks"] == []
    done = gate(pending=landed())
    assert steps(done, mode={"mode": "off", "private": True}, spots=AFTER)["comebacks"] == []
    assert steps(done, stop=True, spots=AFTER)["comebacks"] == []


def test_no_legal_drop_skips_with_the_reason_and_never_offers_the_comeback():
    s = steps(gate(protected={STAY}))
    assert s["comebacks"] == []
    assert s["skipped"] == [
        {
            "reason": f"no legal drop: {STAY} is protected, never dropped",
            "players": [BACK],
            "steps": [],
            "comeback": True,
        }
    ]


def test_a_game_that_began_waits_for_the_next_day_his_page_allows():
    tip = AT - timedelta(minutes=1)
    s = steps(gate(), tips={"NYK": tip.isoformat()})
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"].startswith("his game began")
    # Before the tip he runs; on another day's page he is no one's.
    assert steps(gate(), tips={"NYK": (AT + timedelta(hours=1)).isoformat()})["comebacks"]
    later = DAY + timedelta(days=1)
    assert steps(gate(), day=later)["comebacks"] == []
    # A landed drop's move waits the same way.
    s = steps(gate(pending=landed()), tips={"NYK": tip.isoformat()}, spots=AFTER)
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"].startswith("his game began")


def test_a_drop_never_runs_blind_to_the_clock():
    s = steps(gate(), no_tips=True)
    assert s["comebacks"] == []
    assert "tip-offs are not read" in s["skipped"][0]["reason"]
    # The drop's own game began: he waits too.
    tip = AT - timedelta(minutes=1)
    s = steps(gate(), tips={"BOS": tip.isoformat()})
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"] == f"{STAY}'s game began: his drop waits for the next day"


def test_a_landed_drop_resumes_at_the_move_once_a_read_confirms_it():
    # The page read after the drop no longer shows him: the move, never a second drop.
    assert steps(gate(pending=landed()), spots=AFTER)["comebacks"] == [row("move")]
    # A read from before the drop confirms nothing.
    s = steps(gate(pending=landed(at=AT)), spots=AFTER)
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"] == f"no read since {STAY}'s drop: his move waits for one"
    # A drop on the log that the page still shows: no move, and no second drop.
    s = steps(gate(pending=landed()))
    assert s["comebacks"] == []
    assert "no second drop" in s["skipped"][0]["reason"]


def test_an_unread_drop_is_settled_by_the_page():
    # Gone: it landed, and the move goes on.
    assert steps(gate(pending=landed("unconfirmed")), spots=AFTER)["comebacks"] == [row("move")]
    # Still there: it did not land, so the drop is due again, under every gate.
    assert steps(gate(pending=landed("unconfirmed")))["comebacks"] == [row("drop")]
    keep = gate(pending=landed("unconfirmed"), protected={STAY})
    assert steps(keep)["comebacks"] == []


def test_the_page_ends_or_resumes_a_comeback_changed_by_hand():
    # The drop gone by hand: straight to the move, nothing to drop.
    assert steps(gate(), spots=AFTER)["comebacks"] == [row("move")]
    # He left the IL by hand: nothing is due, before or after the drop, and the steps say so
    # (#346).
    off = {"PG": 1, "C": 2, "BN": BACK, "UTIL": STAY}
    quiet = [{"reason": ap.OFF_HELD, "players": [BACK], "steps": [], "comeback": True}]
    for g, spots_ in (
        (gate(), off),
        (gate(pending=landed()), off),
        (gate(pending=landed()), {"PG": 1, "C": 2}),
    ):
        s = steps(g, spots=spots_)
        assert (s["comebacks"], s["skipped"]) == ([], quiet)


def test_no_cleared_held_player_leaves_the_steps_without_a_word():
    # #346: every path that runs no comeback for him puts him under skipped, marked comeback.
    tipped = {"NYK": (AT - timedelta(minutes=5)).isoformat()}
    cases = [
        steps(None),  # outside a live moves league
        steps(gate(), no_tips=True),
        steps(gate(), tips=tipped),
        steps(gate(protected={STAY})),
        steps(gate(), spots={"PG": 1, "C": 2, "BN": BACK, "UTIL": STAY}),
        steps(gate(), day=DAY + timedelta(days=1)),
    ]
    for s in cases:
        assert s["comebacks"] or any(
            BACK in g["players"] and g.get("comeback") for g in s["skipped"]
        )


def test_a_drop_of_the_player_himself_is_a_drop_and_then_nothing():
    page = lineup_page()
    page["alerts"][0]["drop"] = BACK
    args = (LEAGUE, 4, DAY, DAY, AT, page, {}, {"mode": "live"}, False, {"ok": True}, gate())
    assert [c["stage"] for c in ap.steps_payload(*args)["comebacks"]] == ["drop"]


# --------------------------------------------------------------------------- the league's log
def move_run(at: datetime = AT, outcome: str = "set", drop: int | None = STAY) -> dict:
    return {
        "at": at.isoformat(),
        "mode": "live",
        "steps": [{"player": BACK, "kind": "return", "drop": drop, "outcome": outcome}],
    }


def drop_run(outcome: str, entry: str = ENTRY, at: datetime = AT, player: int = STAY) -> dict:
    return {
        "at": at.isoformat(),
        "mode": "live",
        "entry": entry,
        "player": player,
        "outcome": outcome,
    }


def pending(tmp_path, today=DAY):
    return ap.comeback_pending(tmp_path, LEAGUE, today)


def entry_of(outcome: str) -> list[dict]:
    return landed(outcome, AT)


def test_a_landed_drop_owes_its_move(tmp_path):
    assert pending(tmp_path) == []
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert pending(tmp_path) == entry_of("dropped")


def test_only_a_live_drop_that_may_have_landed_is_on_the_log(tmp_path):
    ap.append_run(tmp_path, LEAGUE, {**drop_run("dropped"), "mode": "dry_run"}, DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, drop_run("skipped"), DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, drop_run("failed"), DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped", entry="c-1"), DAY, ap.DROP)
    assert pending(tmp_path) == []
    ap.append_run(tmp_path, LEAGUE, drop_run("unconfirmed"), DAY, ap.DROP)
    assert pending(tmp_path) == entry_of("unconfirmed")


def test_a_refused_drop_leaves_the_comeback_to_a_later_pass(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("failed"), DAY, ap.DROP)
    # Nothing landed: the steps offer the drop again, and the worker holds this pass only.
    assert pending(tmp_path) == []
    assert steps(gate(pending=pending(tmp_path)))["comebacks"] == [row("drop")]


def test_a_refused_move_after_a_landed_drop_resumes_at_the_move(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, move_run(AT + timedelta(minutes=1), "failed"), DAY)
    ap.append_run(tmp_path, LEAGUE, move_run(AT + timedelta(minutes=2), "skipped"), DAY)
    later = DAY + timedelta(days=1)
    assert pending(tmp_path, later) == entry_of("dropped")
    # Only a set move ends it.
    ap.append_run(tmp_path, LEAGUE, move_run(AT + timedelta(days=1)), later)
    assert pending(tmp_path, later) == []


def test_no_drop_is_made_twice_on_the_log(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    # On this pass or the next, on the read that confirms it: the move, no drop stage.
    for today in (DAY, DAY + timedelta(days=1)):
        fresh = (AT + timedelta(minutes=1)).isoformat()
        s = steps(gate(pending=pending(tmp_path, today)), spots=AFTER, read_at=fresh)
        assert [c["stage"] for c in s["comebacks"]] == ["move"]


def test_a_second_stint_is_a_comeback_of_its_own_and_drops_again(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, move_run(AT + timedelta(minutes=5)), DAY)
    assert pending(tmp_path) == []
    # Back on the IL, cleared again: nothing on the log answers for this stint.
    later = DAY + timedelta(days=9)
    assert steps(gate(pending=pending(tmp_path, later)))["comebacks"] == [row("drop")]
    # His new drop owes its own move.
    again = AT + timedelta(days=9)
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped", at=again, player=2), later, ap.DROP)
    assert [p["drop"] for p in pending(tmp_path, later)] == [2]


def test_a_landed_drop_with_no_move_goes_stale(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert pending(tmp_path, DAY + ap.COMEBACK_SPAN)
    assert pending(tmp_path, DAY + ap.COMEBACK_SPAN + timedelta(days=1)) == []


# --------------------------------------------------------------------------- the drop log
def test_the_due_route_never_lists_a_comebacks_drop(client):
    cleared_on_the_il(client)
    assert client.get(f"/seasons/{LEAGUE}/lineup/steps").json()["comebacks"]
    assert [x["entry"] for x in client.get(DUE).json()["drop_first"]] == []


def test_the_drop_log_takes_the_offered_drop_and_refuses_any_other(client):
    player, drop = cleared_on_the_il(client)
    today = nba_today(NOW)
    entry = ap.comeback_entry(player)
    body = drop_body(entry, drop, day=today.isoformat(), mode="live", outcome="failed")
    other = client.post(URL, json={**body, "player": drop + 1})
    assert other.status_code == 409 and "another drop" in other.json()["detail"]
    nobody = client.post(URL, json={**body, "entry": ap.comeback_entry(player + 1)})
    assert nobody.status_code == 409 and nobody.json()["detail"].endswith("has no drop due")
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.text
    # A drop that landed is logged whatever the steps say by now: it is what stops a second one.
    landed_ = {**body, "entry": ap.comeback_entry(player + 1), "outcome": "dropped"}
    r = client.post(URL, json=landed_)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("outcome", ["dropped", "unconfirmed"])
def test_a_landed_drop_is_logged_when_the_steps_now_name_another(client, outcome):
    """The landing's read reached the API first and the steps moved on to another drop: the log
    takes what landed, or the record that stops a second drop is never written."""
    player, drop = cleared_on_the_il(client)
    body = drop_body(
        ap.comeback_entry(player),
        drop + 1,
        day=nba_today(NOW).isoformat(),
        mode="live",
        outcome=outcome,
    )
    r = client.post(URL, json=body)
    assert r.status_code == 200, r.text
    assert ap.comeback_pending(client.data_dir, LEAGUE, nba_today(NOW)) == [
        {
            "player": player,
            "drop": drop + 1,
            "entry": ap.comeback_entry(player),
            "at": r.json()["at"],
            "outcome": outcome,
        }
    ]


def no_build(*_args, **_kw):
    raise RuntimeError("the build failed")


def cleared_on_the_il(client) -> tuple[int, int]:
    """A live league whose bench player sits cleared on the IL: his id and the engine's drop."""
    lineup_league(client)
    roster = client.get(f"/seasons/{LEAGUE}").json()["roster"]
    him = next(s["player"] for s in roster if s["slot"] == "BN")
    client.fake.team_pages[4] = moved(fixture("team4.html"), {him["name"]: "IL"})
    assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202
    live_league(client)
    alerts = client.get(f"/seasons/{LEAGUE}/lineup").json()["alerts"]
    [alert] = [a for a in alerts if a["kind"] == "cleared"]
    return alert["player"], alert["drop"]


def test_the_steps_route_offers_a_real_drop_and_never_without_the_keep_rule(client, monkeypatch):
    player, drop = cleared_on_the_il(client)
    url = f"/seasons/{LEAGUE}/lineup/steps"
    s = client.get(url).json()
    assert [(c["player"], c["drop"], c["stage"]) for c in s["comebacks"]] == [
        (player, drop, "drop")
    ]
    # The keep rule does not read, the rest of the page does: he stays the user's.
    monkeypatch.setattr(season_queue, "protected_of", no_build)
    s = client.get(url).json()
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"] == ap.NEEDS_DROP


def test_the_comeback_sees_at_least_what_the_days_queue_protects(client, monkeypatch):
    player, drop = cleared_on_the_il(client)
    seasons = client.app.state.seasons
    row_ = {"league": LEAGUE, "protected": {str(drop): "kept by the queue"}}
    monkeypatch.setattr(seasons, "_read_queue", lambda _day: {"leagues": [row_]})
    s = client.get(f"/seasons/{LEAGUE}/lineup/steps").json()
    assert s["comebacks"] == []
    assert s["skipped"][0]["reason"] == f"no legal drop: {drop} is protected, never dropped"
    assert s["skipped"][0]["players"] == [player]


def test_stop_and_the_private_league_offer_no_comeback_drop(client):
    cleared_on_the_il(client)
    (client.data_dir / "autopilot").mkdir(exist_ok=True)
    (client.data_dir / "autopilot" / "STOP").write_text("")
    assert client.get(f"/seasons/{LEAGUE}/lineup/steps").json()["comebacks"] == []
    (client.data_dir / "autopilot" / "STOP").unlink()
    assert client.get(f"/seasons/{PRIVATE}/lineup/steps").json().get("comebacks", []) == []


def test_no_keep_rule_no_drop_offered_and_none_on_the_log(client, monkeypatch):
    player, drop = cleared_on_the_il(client)
    monkeypatch.setattr(season_queue, "protected_of", no_build)
    assert client.get(f"/seasons/{LEAGUE}/lineup/steps").json()["comebacks"] == []
    today = nba_today(NOW)
    body = drop_body(
        ap.comeback_entry(player), drop, day=today.isoformat(), mode="live", outcome="dropped"
    )
    r = client.post(URL, json=body)
    assert r.status_code == 409 and r.json()["detail"] == ap.NO_KEEP_RULE
    # Saying it stopped needs no rule.
    r = client.post(URL, json={**body, "outcome": "stopped"})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- after the drop
def row_gone(html: str, name: str) -> str:
    """A team page without ``name``'s row: a player dropped."""
    return "<tr".join(r for r in html.split("<tr") if f'title="{name}"' not in r)


def test_after_the_drop_the_returned_player_starts_and_no_slot_stays_empty(client):
    """The chain's last run, through the real build: the page as it reads once the player is off
    the IL and his drop gone from a starting slot. The steps start him and fill the hole."""
    html = fixture("team4.html")
    day = "2026-10-24"  # the fixture's busy day
    lineup_league(client)

    def lineup_day():
        days = client.get(f"/seasons/{LEAGUE}/lineup").json()["days"]
        return next(d for d in days if d["date"] == day)

    def refresh(page):
        client.fake.team_pages[4] = page
        assert client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True}).status_code == 202

    roster = client.get(f"/seasons/{LEAGUE}").json()["roster"]
    names = {s["player"]["yahoo_id"]: s["player"]["name"] for s in roster}
    playing = lineup_day()["playing"]
    him = next(s for s in roster if s["slot"] != "BN" and s["player"]["yahoo_id"] in playing)
    back, slot = him["player"]["yahoo_id"], him["slot"]

    # He sits on the IL, cleared; the engine names the drop, who starts in the slot he left.
    refresh(moved(html, {names[back]: "IL"}))
    [alert] = [
        a
        for a in client.get(f"/seasons/{LEAGUE}/lineup").json()["alerts"]
        if a["kind"] == "cleared"
    ]
    assert alert["player"] == back
    drop = alert["drop"]
    assert drop != back

    # The chain ran: he is on the bench and the drop's row is gone, his slot empty.
    refresh(row_gone(moved(html, {names[back]: "BN", names[drop]: slot}), names[drop]))
    s = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": day}).json()
    assert s["yahoo"][str(back)] == "BN" and str(drop) not in s["yahoo"]
    filled = {x["slot"] for x in lineup_day()["recommended"] if x["player"] is not None}
    target = {int(k): v for k, v in s["target"].items()}
    assert drop not in target
    assert any(x["player"] == back and x["from_slot"] == "BN" for x in s["steps"])
    assert target[back] in filled
    # Nobody with a game is left on the bench for a slot he could fill: the hole is gone.
    d = lineup_day()
    started = {x["player"] for x in d["recommended"] if x["player"] is not None}
    assert set(d["playing"]) - {drop} == started
    assert s["games"]["after"] == d["games"]["recommended"] == len(started)


# --------------------------------------------------------------------------- the run's reason
def swap_page(alerts: list[dict] = ()) -> dict:
    """A day whose one change swaps a player who tipped off for the bench."""
    page = lineup_page()
    page["alerts"] = list(alerts)
    page["days"][0] |= {"start": [3], "sit": [1]}
    return page


def reason_of(page: dict, comeback: dict | None = None) -> dict:
    tips = {"BOS": (AT - timedelta(hours=1)).isoformat()}
    live = {"mode": "live"}
    return ap.steps_payload(LEAGUE, 4, DAY, DAY, AT, page, tips, live, False, None, comeback)


def test_a_day_with_only_a_comeback_skipped_says_why_not_a_game():
    assert steps(None)["reason"] == ap.NEEDS_DROP
    why = f"no legal drop: {STAY} is protected, never dropped"
    assert steps(gate(protected={STAY}))["reason"] == why


def test_a_day_with_only_tip_offs_skipped_keeps_its_words():
    s = reason_of(swap_page())
    assert [g["reason"] for g in s["skipped"]] == [ap.TIP_OFF_PASSED]
    assert (s["steps"], s["reason"]) == ([], "every change waits on a game that began")


def test_a_day_with_mixed_skips_names_each_reason_once():
    alert = lineup_page()["alerts"]
    s = reason_of(swap_page(alert))
    assert (s["steps"], [g["reason"] for g in s["skipped"]]) == (
        [],
        [ap.NEEDS_DROP, ap.TIP_OFF_PASSED],
    )
    assert s["reason"] == f"several reasons: {ap.NEEDS_DROP}; {ap.TIP_OFF_PASSED}"
    twice = [{"reason": ap.TIP_OFF_PASSED}, {"reason": "other"}, {"reason": ap.TIP_OFF_PASSED}]
    assert ap._no_steps_reason(twice) == f"several reasons: {ap.TIP_OFF_PASSED}; other"


def test_a_day_with_nothing_skipped_says_the_lineup_stands():
    assert ap._no_steps_reason([]) == "Yahoo's lineup already starts the recommended players"


def test_a_day_with_steps_has_no_reason():
    s = steps(gate())
    assert s["comebacks"] == [row("drop")] and s["steps"] == []
    tips = {"BOS": (AT + timedelta(hours=1)).isoformat()}
    live = {"mode": "live"}
    page = swap_page()
    s = ap.steps_payload(LEAGUE, 4, DAY, DAY, AT, page, tips, live, False)
    assert s["steps"] and s["skipped"] == [] and s["reason"] is None


# --------------------------------------------------------------------------- the digest
def digest(tmp_path, today=DAY, since=AT - timedelta(hours=1)) -> list[str]:
    return ap.comeback_digest_lines(tmp_path, [LEAGUE], today, since)


def line(words: str) -> list[str]:
    return [f"- League {LEAGUE}: comeback of {BACK}: {words}"]


def run_with(steps_: list[dict] = (), skipped: list[dict] = ()) -> dict:
    return {"at": AT.isoformat(), "mode": "live", "steps": list(steps_), "skipped": list(skipped)}


def test_the_digest_says_a_refused_drop(tmp_path):
    run = {**drop_run("failed"), "reason": 'Yahoo refused the drop: "Error #845"'}
    ap.append_run(tmp_path, LEAGUE, run, DAY, ap.DROP)
    assert digest(tmp_path) == line(f'drop of {STAY} failed (Yahoo refused the drop: "Error #845")')


def test_the_digest_says_a_refused_move_with_yahoos_words(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make")
    step = {**move_run(outcome="failed")["steps"][0], "message": "Error #160"}
    ap.append_run(tmp_path, LEAGUE, run_with([step]), DAY)
    assert digest(tmp_path) == line(f"{STAY} dropped, move failed (Error #160)")


def test_the_digest_says_a_move_that_failed_with_no_drop_on_the_log(tmp_path):
    # The first live run, drop still second: four leagues, and no line for any of them.
    step = {**move_run(outcome="failed")["steps"][0], "reason": 'Yahoo answered: "Error #160"'}
    ap.append_run(tmp_path, LEAGUE, run_with([step]), DAY)
    assert digest(tmp_path) == line('move failed (Yahoo answered: "Error #160")')


def test_the_digest_says_a_chain_that_ran_whole(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, move_run(), DAY)
    assert digest(tmp_path) == line(f"{STAY} dropped, moved to the bench")


def test_the_digest_says_a_comeback_dropped_a_player_added_that_day_or_the_day_before(tmp_path):
    # 31153, 2026-11-09: a claim won at 04:17 and its add dropped by the comeback at 05:31 (#345).
    yesterday = DAY - timedelta(days=1)

    def placed(day: date, **entry) -> None:
        path = season_queue.queue_path(tmp_path, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"entries": [{"league": LEAGUE, "add": STAY, **entry}]}))

    won = {"outcome": "claimed", "resolved": "won", "date": "2026-10-23"}
    placed(
        date(2026, 10, 23), **won, id=f"2026-10-23:{LEAGUE}:{STAY}:0", **{"from": str(yesterday)}
    )
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert digest(tmp_path) == line(f"{STAY} dropped (added {yesterday}), move still to make")
    # A free agent added that day says so too; one added three days before, or another league's
    # claim, or a claim still open, says nothing.
    placed(DAY, outcome="added", date=str(DAY), id=f"{DAY}:{LEAGUE}:{STAY}:0")
    assert ap.placed_adds(tmp_path, DAY)[LEAGUE] == {STAY: DAY}
    assert digest(tmp_path) == line(f"{STAY} dropped (added {DAY}), move still to make")
    season_queue.queue_path(tmp_path, DAY).unlink()
    placed(date(2026, 10, 23), **won, id="x", **{"from": "2026-10-23"})
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make")
    placed(date(2026, 10, 23), **{**won, "resolved": None}, id="x", **{"from": str(DAY)})
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make")
    placed(date(2026, 10, 23), **won, id="x", league="100009", **{"from": str(DAY)})
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make")


def test_the_digest_says_a_drop_that_was_skipped_or_unread(tmp_path):
    ap.append_run(tmp_path, LEAGUE, {**drop_run("skipped"), "reason": "no row"}, DAY, ap.DROP)
    assert digest(tmp_path) == line(f"drop of {STAY} skipped (no row)")
    ap.append_run(tmp_path, LEAGUE, drop_run("unconfirmed"), DAY, ap.DROP)
    assert digest(tmp_path) == line(f"drop of {STAY} unconfirmed")


def test_the_digest_says_why_a_comeback_ran_no_step(tmp_path):
    why = f"no legal drop: {STAY} is protected, never dropped"
    held = {"reason": why, "players": [BACK], "steps": [], "comeback": True}
    ap.append_run(tmp_path, LEAGUE, run_with(skipped=[held]), DAY)
    assert digest(tmp_path) == line(f"nothing ran ({why})")
    # A held move says why it waits; a player the user keeps is the Lineup alert's, not a line here.
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make ({why})")


def test_the_digest_leaves_the_users_own_comebacks_and_other_groups_to_their_lines(tmp_path):
    held = {"reason": ap.NEEDS_DROP, "players": [BACK], "steps": [], "comeback": True}
    other = {"reason": "tip-off passed", "players": [1, 2], "steps": []}
    ap.append_run(tmp_path, LEAGUE, run_with(skipped=[held, other]), DAY)
    assert digest(tmp_path) == []


def test_the_digest_leaves_out_a_comeback_with_nothing_to_run_on_its_page(tmp_path):
    # #346: another day's page and a page that shows him off the held slots say so on the run,
    # never in the digest.
    for why in (ap.COMEBACK_TODAY_ONLY, ap.OFF_HELD):
        held = {"reason": why, "players": [BACK], "steps": [], "comeback": True}
        ap.append_run(tmp_path, LEAGUE, run_with(skipped=[held]), DAY)
    assert digest(tmp_path) == []
    # The chain that came back without his move (the extension's words) is a line.
    why = "the chain came back without his move: the drop page's run says why"
    held = {"reason": why, "players": [BACK], "steps": [], "comeback": True}
    ap.append_run(tmp_path, LEAGUE, run_with(skipped=[held]), DAY)
    assert digest(tmp_path) == line(f"nothing ran ({why})")


def chain(tmp_path, at: datetime, day: date = DAY) -> None:
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped", at=at), day, ap.DROP)
    ap.append_run(tmp_path, LEAGUE, move_run(at), day)


#: The two digests: the first posted just after AT, the next a day on.
POSTED, NEXT = AT + timedelta(minutes=5), AT + timedelta(days=1)


def test_a_chain_before_the_digest_is_in_that_days_only(tmp_path):
    chain(tmp_path, AT)
    assert digest(tmp_path) == line(f"{STAY} dropped, moved to the bench")
    assert digest(tmp_path, DAY + timedelta(days=1), POSTED) == []


def test_a_chain_after_the_digest_is_in_the_next_only_and_names_its_day(tmp_path):
    chain(tmp_path, AT + timedelta(hours=9))
    assert digest(tmp_path, DAY + timedelta(days=1), POSTED) == [
        f"- League {LEAGUE} ({DAY}): comeback of {BACK}: {STAY} dropped, moved to the bench"
    ]
    assert digest(tmp_path, DAY + timedelta(days=2), NEXT + timedelta(hours=9)) == []


def test_chains_either_side_of_midnight_keep_their_own_lines_earlier_day_first(tmp_path):
    tomorrow = DAY + timedelta(days=1)
    chain(tmp_path, AT + timedelta(hours=9))
    chain(tmp_path, NEXT - timedelta(minutes=30), tomorrow)
    words = f"comeback of {BACK}: {STAY} dropped, moved to the bench"
    assert digest(tmp_path, tomorrow, POSTED) == [
        f"- League {LEAGUE} ({DAY}): {words}",
        f"- League {LEAGUE}: {words}",
    ]


def test_a_drop_said_in_one_digest_leaves_its_move_to_the_next(tmp_path):
    ap.append_run(tmp_path, LEAGUE, drop_run("dropped"), DAY, ap.DROP)
    assert digest(tmp_path) == line(f"{STAY} dropped, move still to make")
    ap.append_run(tmp_path, LEAGUE, move_run(AT + timedelta(hours=9)), DAY)
    assert digest(tmp_path, DAY + timedelta(days=1), POSTED) == [
        f"- League {LEAGUE} ({DAY}): comeback of {BACK}: moved to the bench"
    ]


def test_the_last_digest_is_the_end_of_the_last_daily_that_posted():
    end = NEXT.isoformat()
    posted = {"finished_at": end, "steps": {"post": {"status": "ok", "detail": "url"}}}
    assert ap.last_digest(posted, NEXT + timedelta(days=1)) == NEXT


@pytest.mark.parametrize(
    "marker",
    [
        None,
        {},
        {"finished_at": AT.isoformat(), "steps": {"post": {"status": "failed", "detail": "gh"}}},
        {"finished_at": AT.isoformat(), "steps": {"post": {"status": "skipped", "detail": "off"}}},
        {"finished_at": "not a time", "steps": {"post": {"status": "ok", "detail": "url"}}},
    ],
)
def test_a_daily_that_posted_nothing_reads_two_days_back(marker):
    assert ap.last_digest(marker, NEXT) == NEXT - ap.DIGEST_BACKSTOP


def test_the_digest_route_takes_its_line_from_the_routines_marker(client):
    now = client.app.state.seasons.clock()
    today = nba_today(now)
    late = now - timedelta(hours=3)
    chain(client.data_dir, late, today - timedelta(days=1))
    marker = client.data_dir / "routine" / "daily.json"
    marker.parent.mkdir()
    posted = {"post": {"status": "ok", "detail": "url"}}
    marker.write_text(
        json.dumps({"finished_at": (late - timedelta(hours=1)).isoformat(), "steps": posted})
    )
    words = f"comeback of {BACK}: {STAY} dropped, moved to the bench"
    said = f"- League {LEAGUE} ({today - timedelta(days=1)}): {words}"
    assert said in client.get("/flags/digest").json()["executor"]
    marker.write_text(json.dumps({"finished_at": now.isoformat(), "steps": posted}))
    assert said not in client.get("/flags/digest").json()["executor"]


# --------------------------------------------------------------------------- the routine's wait
def test_a_lineup_page_with_a_comeback_stays_open_for_its_chain():
    class Ctx:
        def __init__(self, body):
            self.body = body
            self.notes = {}

        def get(self, path, timeout):
            return 200, self.body, {}

    body = {
        "mode": "live",
        "open": True,
        "date": "2026-10-26",
        "page": public.team_url(LEAGUE, 4),
    }

    def waits(b):
        return [o.wait_s for o in rs.lineup_plan(Ctx(b), [LEAGUE], False, "pickandroll-lineup")]

    assert waits(body) == [rs.LINEUP_WAIT_S]
    assert waits({**body, "comebacks": [{"player": BACK}]}) == [rs.COMEBACK_WAIT_S]
    assert waits({**body, "comebacks": [{}, {}]}) == [2 * rs.COMEBACK_WAIT_S]


def test_the_press_of_a_chain_is_a_trigger_of_its_own():
    assert "after_comeback" in ap.StartActiveRun.model_fields["trigger"].annotation.__args__


def test_the_lineup_log_takes_a_comeback_move_and_ends_its_pending_drop(client):
    benched_thursday(client)
    dry_runs(client, days=7, checked=2)
    assert client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "live"}).status_code == 200
    step = {
        **run_body()["steps"][0],
        "player": BACK,
        "from_slot": "IL",
        "to_slot": "BN",
        "kind": "return",
        "drop": STAY,
        "outcome": "set",
        "message": "All changes saved",
    }
    body = run_body(mode="live", outcome="set", steps=[step], diff={}, after_start_active=True)
    r = client.post(f"/seasons/{LEAGUE}/autopilot/lineup", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["steps"][0]["drop"] == STAY
    moves = ap.comeback_moves(client.data_dir, LEAGUE)
    assert moves[BACK]["drop"] == STAY
    assert ap.comeback_pending(client.data_dir, LEAGUE, nba_today(NOW)) == []
