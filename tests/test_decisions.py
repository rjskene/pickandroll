"""The decision log (#125): each solve of the moves and strategy routes kept as an entry, my moves
read from the transactions page and matched to the entry before them, the route and the script.

The transactions page is the season fixture (another league's page, renamed), with teams moved
to mine where a test needs my moves. Nothing here is from Basketball Monster: the projection is
the season tests' made-up one.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import season_decisions
from pickandroll.api.season_week import NBA_TZ
from pickandroll.api.seasons import season_dir
from pickandroll.season import decisions as dl
from pickandroll.season.state import Player, Transaction
from pickandroll.sources.yahoo import pages, public
from tests.test_season import (
    CATS,
    LEAGUE,
    NOW,
    TODAY,
    fixture,
    fixture_names,
    projection_csv,
    season_client,
    strategy_league,
    wait_for_job,
)

SITE = "https://basketball.fantasysports.yahoo.com/nba"


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


def transactions(*teams: int) -> list[Transaction]:
    """The fixture page's rows, with ``teams`` made mine (team 4)."""
    return [
        Transaction.from_dict(r)
        for r in pages.parse_transactions_page(mine(fixture("transactions.html"), *teams))["rows"]
    ]


def mine(html: str, *teams: int, me: int = 4) -> str:
    """The transactions page with ``teams``' rows made mine (team ``me``)."""
    for team in teams:
        html = html.replace(f'/nba/{LEAGUE}/{team}"', f'/nba/{LEAGUE}/{me}"')
    return html


def et(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=NBA_TZ)


def entry(at: datetime, *sets: list[tuple[int, int | None]], source: str = "moves") -> dict:
    """A logged solve at ``at`` (kept in UTC, as the API's clock gives it) with ``sets``."""
    at = at.astimezone(UTC)
    return {
        "id": f"{at:%Y%m%dT%H%M%S%f}-{source}-bbm",
        "at": at.isoformat(),
        "source": source,
        "system": {"key": "bbm"},
        "sets": [
            {
                "key": f"set{i}",
                "weight": None,
                "moves": [{"add": a, "drop": d, "from": None} for a, d in moves],
                "gain": {f"set{i}": 0.5},
            }
            for i, moves in enumerate(sets)
        ],
    }


# --------------------------------------------------------------------------- value units (#126)
def test_a_recommended_move_is_logged_in_the_scorers_units_with_the_games_assumed():
    from tests.test_moves import WEEKS, build, player, rates, schedule

    # The add plays Tue, Thu, Sat and four games later; the drop Mon, Wed, Fri, Sun and three.
    sched = schedule({"ADD": [1, 3, 5, 7, 9, 14, 21], "DRP": [0, 2, 4, 6, 8, 15, 22]})
    rate = {1: rates(1.0), 2: rates(1.0), 9: rates(2.0)}
    p = build(
        [player(1, "DRP"), player(2, "DRP")],
        [player(9, "ADD")],
        rate,
        sched,
        [player(5, "DRP")],
        effective={9: WEEKS[0][2]},  # his claim clears on Wednesday
        returns={1: WEEKS[0][4]},  # the drop is out until Friday
    )
    scorer = {"points": {"pts": 1.0}}
    out = dl.move_projection(p, scorer, 9, 1)
    assert (out["add"], out["drop"]) == (20.0, 10.0)
    # This week the add's games from Wednesday (Thu, Sat), the drop's from his return (Fri, Sun).
    assert out["horizons"]["week"] == {
        "from": WEEKS[0][0].isoformat(),
        "to": WEEKS[0][6].isoformat(),
        "add_games": 2,
        "drop_games": 2,
        "value": 2 * 20.0 - 2 * 10.0,
    }
    three = out["horizons"]["three"]
    assert (three["from"], three["to"]) == (WEEKS[1][0].isoformat(), WEEKS[3][6].isoformat())
    assert (three["add_games"], three["drop_games"], three["value"]) == (4, 3, 4 * 20.0 - 3 * 10.0)
    # A lone add gives up nobody's games; no scorer, or no such candidate, logs nothing.
    lone = dl.move_projection(p, scorer, 9, None)
    assert lone["drop"] is None and lone["horizons"]["week"]["drop_games"] is None
    assert lone["horizons"]["week"]["value"] == 40.0
    assert dl.move_projection(p, None, 9, 1) is None and dl.move_projection(p, scorer, 7, 1) is None


def test_a_plans_steps_are_valued_from_their_days_and_sum_to_the_plan():
    """A streaming plan (#136): Thursday's add for one of mine, then Saturday's for him. Each
    step's add counts from its day and its drop gives up his games from that day, so the steps'
    values sum to the first add's Thursday and Friday, the second's Saturday on, less the
    drop's from Thursday."""
    from tests.test_moves import WEEKS, build, player, rates, schedule

    thu, sat = WEEKS[0][3], WEEKS[0][5]
    sched = schedule({"MIN": list(range(28)), "EAR": [3, 4, 9], "LAT": [5, 6, 10]})
    rate = {1: rates(1.0), 2: rates(1.0), 10: rates(2.0), 11: rates(3.0)}
    p = build(
        [player(1, "MIN"), player(2, "MIN")],
        [player(10, "EAR"), player(11, "LAT")],
        rate,
        sched,
        [player(5, "MIN")],
        first_day=thu,
    )
    scorer = {"points": {"pts": 1.0}}
    first = dl.move_projection(p, scorer, 10, 1, thu)
    second = dl.move_projection(p, scorer, 11, 10, sat)
    assert first["horizons"]["week"]["add_games"] == 2  # Thursday and Friday
    assert first["horizons"]["week"]["drop_games"] == 4  # Thursday to Sunday
    # The second step drops the first's add, a candidate: his Saturday and Sunday (none).
    assert (second["drop"], second["horizons"]["week"]["drop_games"]) == (20.0, 0)
    assert second["horizons"]["week"]["add_games"] == 2
    total = first["horizons"]["week"]["value"] + second["horizons"]["week"]["value"]
    assert total == 2 * 20.0 + 2 * 30.0 - 4 * 10.0
    # Undated, a move counts from its add's effective day, as before.
    assert dl.move_projection(p, scorer, 11, 1) == dl.move_projection(p, scorer, 11, 1, thu)


# --------------------------------------------------------------------------- the moves made
def test_a_moves_time_is_read_on_the_leagues_clock_and_its_bid_from_yahoos_words():
    assert dl.when_at("Oct 20, 3:57 am", TODAY, NBA_TZ) == et(20, 3, 57)
    assert dl.when_at("Oct 20, 12:05 pm", TODAY, NBA_TZ) == et(20, 12, 5)
    assert dl.when_at("Oct 20, 12:30 am", TODAY, NBA_TZ) == et(20, 0, 30)
    assert dl.when_at("Oct 20, 9:15 PM", TODAY, NBA_TZ) == et(20, 21, 15)
    # A date without a time is its midnight; no date is no time.
    assert dl.when_at("Oct 20", TODAY, NBA_TZ) == et(20, 0)
    assert dl.when_at(None, TODAY, NBA_TZ) is None
    assert dl.when_at("yesterday", TODAY, NBA_TZ) is None
    # A date after today is last year's.
    assert dl.when_at("Dec 30, 1:00 pm", TODAY, NBA_TZ).year == 2025
    assert dl.bid_of("$5 Waiver") == 5.0 and dl.bid_of("$0 Waiver") == 0.0
    assert dl.bid_of("Free Agent") is None and dl.bid_of("To Waivers") is None
    assert dl.bid_of(None) is None


def test_my_moves_are_each_group_of_my_teams_rows_on_the_transactions_page():
    rows = transactions()
    # Team 8's claim: an add with the drop that came with it, its bid in Yahoo's words.
    assert dl.moves_made(rows, 8, TODAY, NBA_TZ) == [
        dl.Made(1, date(2026, 10, 20), et(20, 3, 57), 6402, 10272, "$0 Waiver", 0.0)
    ]
    # Team 9's: a lone drop, then two lone adds (a FAAB claim each), newest first.
    made = dl.moves_made(rows, 9, TODAY, NBA_TZ)
    assert [(m.group, m.add, m.drop, m.bid) for m in made] == [
        (0, None, 5600, None),
        (4, 6433, None, 1.0),
        (5, 5600, None, 2.0),
    ]
    assert made[0].at == et(20, 8, 53) and made[0].detail is None
    assert made[1].to_dict() == {
        "group": 4,
        "day": "2026-10-20",
        "at": et(20, 3, 57).isoformat(),
        "add": 6433,
        "drop": None,
        "detail": "$1 Waiver",
        "bid": 1.0,
    }
    # A trade is not a move here; another team's rows are not mine.
    trade = Transaction(
        "trade", Player(1, "Player One", "ATL", ("PG",)), 9, "Team 9", None, None, 9
    )
    assert [m.group for m in dl.moves_made([*rows, trade], 9, TODAY, NBA_TZ)] == [0, 4, 5]
    assert dl.moves_made(rows, 4, TODAY, NBA_TZ) == []


def test_a_move_matches_the_latest_entry_logged_before_it():
    claim = dl.Made(1, date(2026, 10, 20), et(20, 3, 57), 6402, 10272, "$0 Waiver", 0.0)
    early = entry(et(20, 1), [(6402, 10272)], [(6433, 11)])
    later = entry(et(20, 8), [(12, None)])
    # The entry after the move is not the one it is matched to, whatever their order.
    got = dl.match(claim, [later, early])
    assert got == {
        "kind": dl.AS_RECOMMENDED,
        "entry": early["id"],
        "move": {"add": 6402, "drop": 10272},
        "near": False,
    }
    # The same add for another drop, or the same drop for another add: differently.
    other_drop = dl.Made(2, claim.day, claim.at, 6433, 99)
    assert dl.match(other_drop, [early]) == {
        "kind": dl.DIFFERENTLY,
        "entry": early["id"],
        "move": {"add": 6433, "drop": 11},
        "near": False,
    }
    other_add = dl.Made(3, claim.day, claim.at, 77, 10272)
    assert dl.match(other_add, [early])["move"] == {"add": 6402, "drop": 10272}
    # An add into an open spot is recommended only as one: nobody dropped is a drop of its own.
    open_spot = dl.Made(4, claim.day, et(20, 9), 12, None)
    assert dl.match(open_spot, [early, later])["kind"] == dl.AS_RECOMMENDED
    assert dl.match(dl.Made(5, claim.day, claim.at, 12, None), [early])["kind"] == (
        dl.NOT_RECOMMENDED
    )
    # A lone drop of a player no set names; a move with nothing logged before it.
    lone = dl.Made(6, claim.day, et(20, 8, 53), None, 5600)
    # It is 53 minutes after the 8 am solve: near one, so a zone off by an hour would match it
    # to the 1 am solve instead.
    assert dl.match(lone, [early, later]) == {
        "kind": dl.NOT_RECOMMENDED,
        "entry": later["id"],
        "move": None,
        "near": True,
    }
    assert dl.match(claim, [later]) == {
        "kind": dl.NO_ENTRY,
        "entry": None,
        "move": None,
        "near": False,
    }
    assert dl.match(dl.Made(7, None, None, 6402, 10272), [early])["kind"] == dl.NO_ENTRY
    # Near is either side: a solve 40 minutes after the move flags it too.
    assert dl.match(claim, [early, entry(et(20, 4, 37), [(12, None)])])["near"] is True
    assert dl.match(claim, [early, entry(et(20, 4, 58), [(12, None)])])["near"] is False


# --------------------------------------------------------------------------- the log
def solved_league(client) -> None:
    projection_csv(
        client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names(), star="Kevin Durant"
    )
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202, r.text


def logged(client, day: str = "2026-10-21") -> list[dict]:
    path = season_dir(client.data_dir, LEAGUE) / "decisions" / f"{day}.json"
    return json.loads(path.read_text()) if path.exists() else []


def snapshot(client, league: str, url: str, html: str, at: datetime | None = None) -> None:
    page = {"url": url, "html": html}
    if at is not None:
        page["fetched_at"] = at.isoformat()
    r = client.post(f"/seasons/{league}/snapshot", json={"pages": [page]})
    assert r.status_code == 200, r.text
    assert r.json()["accepted"], r.json()


def test_each_solve_of_the_moves_route_appends_an_entry_to_its_days_log(client):
    # The strategy tests' league: a pool of players better than some of mine.
    strategy_league(client)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    [first] = logged(client)
    assert first["at"] == NOW.isoformat() and first["source"] == "moves"
    assert first["id"] == f"{NOW:%Y%m%dT%H%M%S%f}-moves-bbm"
    # The system and its export, the day the moves start, the adds left, the pool.
    assert first["system"] == m["system"]
    assert first["system"]["file"] == "bbm_projections_2026-10-21.csv"
    # The knobs in force: the solve's system and the keep rule's floor, the others unset until
    # the knob file (phase 3).
    assert first["knobs"] == {
        "system": "bbm",
        "blend": None,
        "horizon_weight": None,
        "protection_floor": 0.0,
        "plan_floor_cats": 0.1,
        "plan_floor_points": 0.01,
        "stash_threshold": None,
        "faab_sizing": None,
        "daily_cap": None,
    }
    assert first["first_day"] == "2026-10-21" and first["adds"] == m["adds"]
    assert first["horizons"] == {k: v["label"] for k, v in m["horizons"].items()}
    assert first["pool"] == {
        "size": m["search"]["pool"],
        "candidates": len(m["candidates"]),
        "min_gain": m["search"]["min_gain"],
    }
    # Each horizon's recommended set: its moves, the held slots, the comebacks, the gains.
    assert [s["key"] for s in first["sets"]] == ["week", "three"]
    for s in first["sets"]:
        rec = m["recommended"][s["key"]]
        # Each move with the bid to make, none until the FAAB sizing (phase 2), and (#126) its
        # own gain on each horizon as the solve priced it.
        assert [{k: x[k] for k in ("add", "drop", "from", "bid")} for x in s["moves"]] == [
            {**{k: x[k] for k in ("add", "drop", "from")}, "bid": None} for x in rec["moves"]
        ]
        assert [x["gain"] for x in s["moves"]] == [x["marginal"] for x in rec["moves"]]
        assert (s["weight"], s["held"], s["comebacks"]) == (None, rec["held"], rec["comebacks"])
        assert s["gain"] == rec["gain"]
        # This week before and after the set: each category's finals and odds.
        before, after = s["week"]["before"], s["week"]["after"]
        assert set(before["cats"]) == set(after["cats"]) == set(CATS)
        for block in (before, after):
            assert all(0 <= c["p_win"] <= 1 for c in block["cats"].values())
            assert 0 <= block["expected"] <= len(CATS) and 0 <= block["matchup"] <= 1
            assert block["expected"] == pytest.approx(
                sum(c["p_win"] for c in block["cats"].values()), abs=1e-3
            )
    week = first["sets"][0]
    assert week["moves"], "the fixture league has a move this week"
    assert week["week"]["after"]["expected"] > week["week"]["before"]["expected"]
    # The scorer the scorecard values the moves made with (#126), and each move in its units:
    # the add's games less the drop's over each horizon, each game at his per-game value.
    assert set(first["scorer"]["cats"]) == set(CATS)
    value = week["moves"][0]["value"]
    assert value["add"] is not None and set(value["horizons"]) == {"week", "three"}
    this = value["horizons"]["week"]
    assert this["from"] == "2026-10-21" and this["add_games"] > 0
    drop = (this["drop_games"] or 0) * (value["drop"] or 0.0)
    assert this["value"] == pytest.approx(this["add_games"] * value["add"] - drop, abs=1e-3)
    assert value["horizons"]["three"]["from"] > this["to"]
    # The same answer again is the cached one: nothing new to log.
    client.get(f"/seasons/{LEAGUE}/moves")
    assert len(logged(client)) == 1
    # New inputs the same day solve again, and the entry goes after the first one.
    later = NOW + timedelta(minutes=5)
    client.app.state.seasons.clock = lambda: later
    snapshot(client, LEAGUE, f"{SITE}/{LEAGUE}/transactions", fixture("transactions.html"))
    client.get(f"/seasons/{LEAGUE}/moves")
    entries = logged(client)
    assert [e["at"] for e in entries] == [NOW.isoformat(), later.isoformat()]
    assert entries[0] == first


def test_the_moves_route_carries_the_weeks_streaming_plan(client):
    """The fixture league's plan (#136) beside the week's set: its stream spots, its steps and
    the set's moves it keeps, my started games and the values with no move, the set and the
    plan. Every add of the week goes to the set, so the plan is the set and is not recommended,
    and nothing more is logged."""
    strategy_league(client)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    plan, week = m["plan"], m["recommended"]["week"]
    # The stream spots: below the best add's value and kept by nothing.
    rule = {x["player"]: x for x in m["keep_rule"]["players"]}
    best = m["keep_rule"]["best"]["value"]
    assert plan["spots"]
    for s in plan["spots"]:
        x = rule[s["player"]]
        assert not (x["protected"] or x["bench"]) and (x["value"] is None or x["value"] < best)
    set_moves = {(x["add"], x["drop"]) for x in week["moves"]}
    planned = [*plan["base"], *plan["steps"]]
    assert {(x["add"], x["drop"]) for x in planned} == set_moves
    for step in plan["steps"]:
        assert step["spot"] in {s["player"] for s in plan["spots"]}
        assert step["from"] >= m["horizons"]["week"]["from"] and set(step["marginal"]) == {
            "week",
            "three",
        }
    assert plan["adds"] == {"set": len(week["moves"]), "plan": len(planned)}
    assert plan["games"]["none"] < plan["games"]["set"] == plan["games"]["plan"]
    value = plan["value"]
    for h in ("week", "three"):
        assert value["set"][h] - value["none"][h] == pytest.approx(week["gain"][h], abs=2e-3)
        assert plan["gain"][h] == pytest.approx(value["plan"][h] - value["set"][h], abs=2e-3)
    assert (plan["recommended"], plan["short"], plan["floor"]) == (False, 0.1, 0.1)
    # The entry logs what the plan was worth against the set, whatever the verdict, with no
    # steps unless it is recommended.
    [entry] = logged(client)
    assert [s["key"] for s in entry["sets"]] == ["week", "three"]
    assert entry["plan"] == {
        "recommended": False,
        "value": value["plan"],
        "set": value["set"],
        "short": 0.1,
        "floor": 0.1,
    }


def test_a_recommended_plan_is_logged_as_one_more_set_its_steps_by_day(client, monkeypatch):
    from pickandroll.season import stream

    # Any plan that is not behind the set clears a floor below zero.
    monkeypatch.setattr(stream, "PLAN_FLOOR_CATS", -1.0)
    strategy_league(client)
    m = client.get(f"/seasons/{LEAGUE}/moves").json()
    plan = m["plan"]
    assert plan["recommended"] and plan["short"] is None
    [entry] = logged(client)
    assert [s["key"] for s in entry["sets"]] == ["week", "three", "plan"]
    logged_plan = entry["sets"][2]
    rows = [*plan["base"], *plan["steps"]]
    assert [{k: x[k] for k in ("add", "drop", "from")} for x in logged_plan["moves"]] == [
        {k: x[k] for k in ("add", "drop", "from")} for x in rows
    ]
    # Each move's own gain, and (#126) its value from its day.
    assert [x["gain"] for x in logged_plan["moves"]] == [x["marginal"] for x in rows]
    for x in logged_plan["moves"]:
        assert x["value"]["horizons"]["week"]["add_games"] >= 0
    none = plan["value"]["none"]
    assert logged_plan["gain"] == pytest.approx(
        {h: plan["value"]["plan"][h] - none[h] for h in ("week", "three")}, abs=2e-3
    )
    assert (logged_plan["held"], logged_plan["comebacks"]) == (plan["held"], plan["comebacks"])
    assert entry["plan"]["recommended"] and entry["plan"]["floor"] == -1.0
    assert logged_plan["week"]["after"]["expected"] == pytest.approx(
        plan["value"]["plan"]["week"], abs=2e-3
    )


def test_a_strategy_run_that_solved_is_logged_with_each_weights_set(client):
    strategy_league(client)
    s = client.post(
        f"/seasons/{LEAGUE}/strategy",
        params={"wait": True, "pool": 12, "weights": "week,natural"},
    ).json()
    assert s["status"] == "solved"
    entries = logged(client)
    # The run solved the moves it ranks its pool by first: their entry, then its own.
    assert [e["source"] for e in entries] == ["moves", "strategy"]
    run = entries[1]
    assert run["system"] == s["system"] and run["settings"] == s["settings"]
    assert run["knobs"]["system"] == "bbm" and run["knobs"]["daily_cap"] is None
    assert run["pool"] == {"size": len(s["pool"]), "players": s["pool"]}
    assert [x["key"] for x in run["sets"]] == ["week", "natural"]
    for logged_set, point in zip(run["sets"], s["points"], strict=True):
        assert logged_set["weight"] == point["lambda"]
        assert logged_set["natural"] == point["natural"]
        assert logged_set["source"] == point["source"]
        assert logged_set["gain"] == point["gain"]
        assert [{k: x[k] for k in ("add", "drop", "from", "bid")} for x in logged_set["moves"]] == [
            {**{k: x[k] for k in ("add", "drop", "from")}, "bid": None} for x in point["moves"]
        ]
        assert [x["gain"] for x in logged_set["moves"]] == [
            x.get("marginal") for x in point["moves"]
        ]
        assert set(logged_set["week"]["after"]["cats"]) == set(CATS)
    # The same run asked again is found, not solved: nothing new to log.
    client.post(
        f"/seasons/{LEAGUE}/strategy", params={"wait": True, "pool": 12, "weights": "week,natural"}
    )
    assert len(logged(client)) == 2


def test_a_failure_to_log_loses_the_entry_never_the_answer(client, monkeypatch):
    solved_league(client)

    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(season_decisions, "append", broken)
    r = client.get(f"/seasons/{LEAGUE}/moves")
    assert r.status_code == 200 and r.json()["recommended"]["week"]
    assert logged(client) == []


# --------------------------------------------------------------------------- the route
def matched_league(client) -> tuple[dict, dict]:
    """The fixture league with teams 8 and 9's moves made mine, and two solves logged before
    them on Oct 20: one at 1 am that recommends team 8's claim and team 9's first add for
    another drop, one at 8 am that recommends neither."""
    snapshot(
        client,
        LEAGUE,
        f"{SITE}/{LEAGUE}/transactions",
        mine(fixture("transactions.html"), 8, 9),
        NOW,
    )
    early = entry(et(20, 1), [(6402, 10272)], [(6433, 11)])
    later = entry(et(20, 8), [(12, None)])
    folder = season_dir(client.data_dir, LEAGUE)
    for e in (later, early):
        season_decisions.append(folder, e)
    return early, later


def test_the_decisions_route_matches_each_of_my_moves_to_the_entry_before_it(client):
    early, later = matched_league(client)
    # Both entries are Oct 20's in US Eastern, the 1 am one too (Oct 20 05:00 UTC).
    assert [e["id"] for e in logged(client, "2026-10-20")] == [later["id"], early["id"]]
    r = client.get(
        f"/seasons/{LEAGUE}/decisions", params={"from": "2026-10-20", "to": "2026-10-20"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["league"], body["from"], body["to"]) == (LEAGUE, "2026-10-20", "2026-10-20")
    assert body["transactions_read"] == NOW.isoformat()
    # The entries oldest first.
    assert [e["id"] for e in body["entries"]] == [early["id"], later["id"]]
    made = {m["group"]: m for m in body["made"]}
    assert sorted(made) == [0, 1, 4, 5]
    assert made[1]["match"] == {
        "kind": "as_recommended",
        "entry": early["id"],
        "move": {"add": 6402, "drop": 10272},
        "near": False,
    }
    assert (made[1]["detail"], made[1]["bid"]) == ("$0 Waiver", 0.0)
    assert made[4]["match"] == {
        "kind": "differently",
        "entry": early["id"],
        "move": {"add": 6433, "drop": 11},
        "near": False,
    }
    assert made[5]["match"]["kind"] == "not_recommended"
    # The lone drop at 8:53 is matched to the 8 am solve, which named neither player, and is
    # within an hour of it.
    assert made[0]["match"] == {
        "kind": "not_recommended",
        "entry": later["id"],
        "move": None,
        "near": True,
    }
    assert body["summary"] == {
        "as_recommended": 1,
        "differently": 1,
        "not_recommended": 2,
        "no_entry": 0,
        "near": 1,
    }
    # The names of the players in the moves, where the season knows them.
    names = body["players"]
    assert names["6402"] == "Jalen Smith" and names["10272"] == "Kyshawn George"
    assert {"6433", "5600"} <= set(names) and "11" not in names
    # By default the last week to today; a day before the moves shows none of them.
    assert client.get(f"/seasons/{LEAGUE}/decisions").json()["made"] == body["made"]
    early_day = client.get(f"/seasons/{LEAGUE}/decisions", params={"to": "2026-10-19"}).json()
    assert (early_day["from"], early_day["entries"], early_day["made"]) == ("2026-10-13", [], [])
    assert early_day["summary"]["as_recommended"] == 0
    assert client.get("/seasons/9/decisions").status_code == 404


def test_a_move_with_nothing_logged_before_it_says_so(client):
    snapshot(
        client,
        LEAGUE,
        f"{SITE}/{LEAGUE}/transactions",
        mine(fixture("transactions.html"), 8),
        NOW,
    )
    body = client.get(f"/seasons/{LEAGUE}/decisions").json()
    assert body["entries"] == []
    assert [(m["group"], m["match"]["kind"]) for m in body["made"]] == [(1, "no_entry")]
    assert body["summary"]["no_entry"] == 1


def test_a_private_leagues_record_lists_its_transactions_page_until_read_today(client):
    solved_league(client)
    snapshot(client, "100002", f"{SITE}/100002", fixture("league.html"))
    wait_for_job(client, "100002")
    later = NOW + timedelta(days=7)
    client.app.state.seasons.clock = lambda: later

    def record() -> dict:
        r = client.post("/seasons/100002/record")
        return r.json()["detail"] if r.status_code == 409 else r.json()

    assert record()["transactions_page"] == public.transactions_url("100002")
    # Read today, it is not asked for again until tomorrow.
    snapshot(client, "100002", f"{SITE}/100002/transactions", fixture("transactions.html"), later)
    assert record()["transactions_page"] is None


def test_a_private_leagues_moves_are_read_from_its_posted_transactions_page(client):
    """The private league has no public page: the user's Chrome posts its transactions page,
    and the route matches my moves (team 7) from it."""
    site = f"{SITE}/100002"
    snapshot(client, "100002", site, fixture("league.html"))
    snapshot(client, "100002", f"{site}/transactions", mine(fixture("transactions.html"), 8, me=7))
    wait_for_job(client, "100002")
    claim = entry(et(20, 1), [(6402, 10272)])
    season_decisions.append(season_dir(client.data_dir, "100002"), claim)
    body = client.get("/seasons/100002/decisions").json()
    assert [(m["group"], m["match"]["kind"], m["match"]["entry"]) for m in body["made"]] == [
        (1, "as_recommended", claim["id"])
    ]
    assert body["entries"] == [claim]


# --------------------------------------------------------------------------- the script
def test_the_decisions_command_prints_each_solve_then_each_move(client):
    from tests.test_record import load_script

    script = load_script()
    matched_league(client)

    def call(method: str, path: str) -> tuple[int, object]:
        r = client.request(method, path)
        return r.status_code, r.json()

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert script.decisions_all(call, [LEAGUE, "9"], "2026-10-20", "2026-10-20") == 0
    lines = buf.getvalue().strip().splitlines()
    # Each set's gain and moves, by name where the season knows the player.
    assert lines[0].startswith(
        f"{LEAGUE} 2026-10-20 01:00 moves bbm: set0 +0.50: add Jalen Smith for Kyshawn George; "
        "set1 +0.50: add "
    )
    assert lines[0].endswith(" for 11") and "add 6433" not in lines[0]
    assert lines[1] == f"{LEAGUE} 2026-10-20 08:00 moves bbm: set0 +0.50: add 12"
    claim = next(x for x in lines if "Jalen Smith" in x and "made:" in x)
    assert claim == (
        f"{LEAGUE} 2026-10-20 03:57 made: add Jalen Smith for Kyshawn George ($0 Waiver): "
        "as recommended (moves 2026-10-20 01:00)"
    )
    assert any(
        x.endswith("not recommended (moves 2026-10-20 08:00) [near a solve]") and " drop " in x
        for x in lines
    )
    assert lines[-1].startswith("9: skipped (404)")
    # The record's line lists the private league's transactions page with the others to open.
    url = public.transactions_url("100002")
    needs = {"needs": [f"{SITE}/100002"], "week": 1, "transactions_page": url}
    assert script.describe("100002", 409, {"detail": needs}).endswith(f"; transactions page: {url}")
    # A streaming plan's set (#136) reads as the week's gain, its moves by day.
    plan = {
        "id": "x",
        "at": "2026-10-22T16:00:00+00:00",
        "source": "moves",
        "system": {"key": "bbm"},
        "sets": [
            {
                "key": "plan",
                "weight": None,
                "gain": {"week": 0.42, "three": 0.1},
                "moves": [
                    {"add": 1, "drop": 2, "from": "2026-10-22"},
                    {"add": 3, "drop": 1, "from": "2026-10-24"},
                ],
            }
        ],
    }
    body = {"entries": [plan], "made": [], "players": {"1": "Brooks", "2": "Grant", "3": "Hale"}}
    assert script.decision_lines(body) == [
        "2026-10-22 12:00 moves bbm: plan +0.42: Thu: add Brooks for Grant, Sat: add Hale for Brooks"
    ]
    # Nothing logged and nothing made reads as such.
    assert script.decision_lines({"entries": [], "made": [], "players": {}}) == ["nothing logged"]
