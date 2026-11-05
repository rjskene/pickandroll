"""The recommended starters on a crowded day (#314): the largest legal set with the most expected
categories won this week, Yahoo's starters kept on a near-tie and a player whose game began left
where Yahoo has him.

Made-up players and lines throughout; nothing here is from Basketball Monster.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from pickandroll.api import season_lineup as sl
from pickandroll.api import season_matchup as sm
from pickandroll.api.seasons import SCHEDULE_DIR, base_settings, load_parts
from pickandroll.season import Player, Season
from pickandroll.season import lineup as lu
from pickandroll.season import weekly as wk
from tests.test_lineup import moved
from tests.test_season import (
    LEAGUE,
    NOW,
    TODAY,
    fixture,
    fixture_names,
    projection_csv,
    season_client,
)

MON = date(2026, 10, 19)
TUE = date(2026, 10, 20)
CATS = ("pts", "ast", "reb")
#: Far ahead in points, a close race in assists and in rebounds.
SO_FAR = {"pts": 500.0, "ast": 50.0, "reb": 50.0}
THEIRS = {"pts": (100.0, 5.0), "ast": (52.0, 3.0), "reb": (52.0, 3.0)}


def p(key: int, *positions: str, team: str = "AAA") -> tuple[int, Player]:
    return key, Player(key, f"P{key}", team, positions)


def line(pts=0.0, ast=0.0, reb=0.0, fgm=0.0, fga=0.0) -> dict[str, float]:
    return {"pts": pts, "ast": ast, "reb": reb, "fgm": fgm, "fga": fga}


#: General value order 1, 2, 3; only 1 is strong in points, the decided category.
SCORER = line(pts=30.0, ast=0.5, reb=0.5)
PASSER = line(pts=6.0, ast=8.0)
BIG = line(pts=6.0, reb=8.0)
VALUE = {1: 10.0, 2: 5.0, 3: 4.0}
RATES = {1: SCORER, 2: PASSER, 3: BIG}


def win(roster, slots, days=(MON,), rates=RATES, value=VALUE, playing=None, **kw):
    if playing is None:
        playing = {k: list(days) for k, _ in roster}
    kw.setdefault("so_far", SO_FAR)
    kw.setdefault("theirs", THEIRS)
    cats = kw.pop("cats", CATS)
    so_far, theirs = kw.pop("so_far"), kw.pop("theirs")
    return lu.win_starters(
        roster, playing, list(days), slots, value, rates, cats, so_far, theirs, **kw
    )


def test_a_close_categorys_player_starts_over_a_higher_value_one_in_a_decided_category():
    roster = [p(1, "PG"), p(2, "PG")]
    assert wk.starters([(k, v.positions) for k, v in roster], ["Util"], VALUE) == {1: "Util"}
    assert win(roster, ["Util"]) == {MON: {2: "Util"}}


def test_the_set_is_searched_whole_not_ranked_player_by_player():
    # 2 and 4 each add more than 3 alone, but they run the same race: starting both wins less than
    # one of them and 3, so a gain per player would miss the best set.
    rates = {1: SCORER, 2: PASSER, 3: line(pts=6.0, reb=6.0), 4: line(pts=6.0, ast=7.5)}
    theirs = {**THEIRS, "ast": (53.0, 2.0), "reb": (54.0, 2.0)}

    def expected(*keys: int) -> float:
        week = wk.team_week({k: wk.PlayerWeek(1, 1) for k in keys}, rates, None)
        return wk.expected_won(wk.odds_of(wk.finals(week, SO_FAR, CATS), theirs, CATS))

    assert expected(2) > expected(4) > expected(3)
    assert expected(2, 3) > expected(2, 4)
    roster = [p(k, "PG") for k in rates]
    picked = win(roster, ["Util", "Util"], rates=rates, value={**VALUE, 4: 3.0}, theirs=theirs)
    assert set(picked[MON]) == {2, 3}


def test_days_run_in_order_and_an_earlier_days_starters_count_in_a_later_days():
    roster = [p(2, "PG"), p(3, "PG")]
    theirs = {**THEIRS, "ast": (54.0, 2.0), "reb": (54.0, 2.0)}
    out = win(roster, ["Util"], days=(MON, TUE), theirs=theirs)
    # Each race needs one start: the second day goes to the race the first day left open.
    assert {*out[MON], *out[TUE]} == {2, 3}


def test_a_near_tie_keeps_yahoos_starters_and_a_real_gain_does_not():
    roster = [p(2, "PG"), p(3, "PG")]
    theirs = {**THEIRS, "ast": (52.0, 3.0), "reb": (52.1, 3.0)}
    rates = {2: PASSER, 3: BIG}
    value = {2: 5.0, 3: 4.0}

    def expected(key: int) -> float:
        week = wk.team_week({key: wk.PlayerWeek(1, 1)}, rates, None)
        return wk.expected_won(wk.odds_of(wk.finals(week, SO_FAR, CATS), theirs, CATS))

    def picked(on_yahoo: int) -> dict[int, str]:
        yahoo = {MON: [on_yahoo]}
        return win(roster, ["Util"], rates=rates, value=value, theirs=theirs, yahoo=yahoo)[MON]

    # 3 is the better set, by less than TIE: Yahoo keeps 2, the worse one, and keeps 3 once he
    # is set, so neither the daily pass nor the late one moves anyone.
    assert 0 < expected(3) - expected(2) < lu.TIE
    assert picked(2) == {2: "Util"} and picked(3) == {3: "Util"}
    # Not read: the anchor is the value set, kept the same way.
    assert win(roster, ["Util"], rates=rates, value=value, theirs=theirs)[MON] == {2: "Util"}
    # A decided category's player on Yahoo does not hold his slot against a real gain.
    assert win([p(1, "PG"), p(2, "PG")], ["Util"], yahoo={MON: [1]})[MON] == {2: "Util"}


def test_a_day_with_no_surplus_comes_out_as_by_value_and_keeps_its_slots_filled():
    # 4 hurts the percentage, and nobody sits only to protect it.
    rates = {1: SCORER, 2: PASSER, 4: line(pts=4.0, fgm=1.0, fga=12.0)}
    value = {**VALUE, 4: 1.0}
    roster = [p(1, "PG"), p(2, "SG"), p(4, "C")]
    slots = ["PG", "SG", "C"]
    playing = {k: [MON] for k, _ in roster}
    theirs = {**THEIRS, "fg_pct": (0.5, 0.01)}
    out = win(roster, slots, rates=rates, value=value, cats=(*CATS, "fg_pct"), theirs=theirs)
    assert out == wk.daily_starters(roster, playing, [MON], slots, value)


def test_a_crowded_day_starts_the_most_players_the_slots_hold_each_where_he_may():
    roster = [p(1, "PG"), p(2, "C"), p(3, "C"), p(4, "SG"), p(5, "PG", "SG")]
    rates = {**RATES, 4: line(pts=9.0), 5: line(pts=9.0, ast=1.0)}
    value = {**VALUE, 4: 2.0, 5: 3.0}
    slots = ["PG", "SG", "C"]
    picked = win(roster, slots, rates=rates, value=value)[MON]
    assert len(picked) == 3 and len(set(picked.values())) == 3
    positions = dict(roster)
    assert all(wk.accepts(slot, positions[k].positions) for k, slot in picked.items())


def test_a_player_whose_game_began_stays_where_yahoo_has_him():
    roster = [p(1, "PG"), p(2, "PG"), p(3, "PG"), p(4, "PG")]
    rates = {**RATES, 4: line(pts=6.0, reb=9.0)}
    value = {**VALUE, 4: 3.0}
    slots = ["PG", "Util"]
    # Rebounds the one race left; unlocked, its two players start.
    theirs = {**THEIRS, "ast": (200.0, 5.0), "reb": (56.0, 3.0)}
    free = win(roster, slots, rates=rates, value=value, theirs=theirs, yahoo={MON: [1, 2]})
    assert set(free[MON]) == {3, 4}
    # 1 was on Yahoo's lineup and tipped off, 4 sat and tipped off. The search takes the best set
    # it can still reach, not the one it would have wanted: 3 replaces 2, the one free starter.
    locked = {MON: lu.Locked({1: "Util"}, frozenset({4}))}
    picked = win(
        roster, slots, rates=rates, value=value, theirs=theirs, yahoo={MON: [1, 2]}, locked=locked
    )
    assert picked[MON] == {1: "Util", 3: "PG"}


def test_a_starter_whose_game_began_holds_his_slot_without_a_game_of_his_own():
    # 1 is out, on Yahoo's Util slot, and his team tipped off: the slot is not open.
    roster = [p(1, "PG"), p(2, "PG"), p(3, "PG")]
    playing = {1: [], 2: [MON], 3: [MON]}
    locked = {MON: lu.Locked({1: "Util"})}
    picked = win(roster, ["PG", "Util"], playing=playing, locked=locked, yahoo={MON: [1, 2]})[MON]
    assert picked[1] == "Util" and len(picked) == 2


def test_the_week_counts_exactly_the_days_named_and_a_gone_player_is_replaced():
    roster = [p(1, "PG"), p(2, "PG"), p(3, "PG")]
    playing = {k: [MON] for k, _ in roster}
    # 1 outranks 2, but the day names 2.
    named = wk.daily_starters(roster, playing, [MON], ["Util"], VALUE, chosen={MON: {2}})
    assert set(named[MON]) == {2}
    # A slot the names leave open stays open.
    two = wk.daily_starters(roster, playing, [MON], ["PG", "Util"], VALUE, chosen={MON: {2}})
    assert set(two[MON]) == {2}
    # Without a named player the others stay and value fills his slot.
    playing[2] = []
    filled = wk.daily_starters(roster, playing, [MON], ["PG", "Util"], VALUE, chosen={MON: {2, 3}})
    assert set(filled[MON]) == {1, 3}


def test_the_teams_whose_game_began():
    now = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
    tips = {"AAA": "2026-10-24T23:00Z", "BBB": "2026-10-25T00:00:00+00:00", "CCC": "soon"}
    assert sl.begun_teams(tips, now) == {"AAA"}
    assert sl.begun_teams(None, now) == frozenset()


@pytest.fixture
def league(tmp_path):
    with season_client(tmp_path) as client:
        projection_csv(client.data_dir / "bbm_projections_2026-10-21.csv", fixture_names())
        client.fake.every_day = True
        yield client


def starts(lineup) -> dict[int, int]:
    out: dict[int, int] = {}
    for d in lineup["days"]:
        if d["past"]:
            continue
        for x in d["recommended"]:
            if x["player"] in d["playing"]:
                out[x["player"]] = out.get(x["player"], 0) + 1
    return out


def refresh(client) -> None:
    r = client.post(f"/seasons/{LEAGUE}/refresh", params={"wait": True})
    assert r.status_code == 202, r.text


def season_of(client) -> Season:
    base, _ = base_settings(client.data_dir, LEAGUE)
    return Season.from_parts(base, load_parts(client.data_dir, LEAGUE))


def test_the_lineup_and_the_week_projections_count_the_same_starters(league):
    refresh(league)
    built = league.app.state.seasons._built(LEAGUE, None)
    # Three slots for the fixture's seven who play: crowded days.
    crowded = replace(built, problem=replace(built.problem, slots=("PG", "F", "Util")))
    season = season_of(league)
    lineup = sl.payload(crowded, season, TODAY)
    assert any(len(d["playing"]) > 3 for d in lineup["days"] if not d["past"])
    counted = starts(lineup)
    mine = sm.payload(crowded, season, TODAY)["players"]["mine"]
    assert {r["player"]: r["started"] for r in mine if r["started"]} == counted


def test_the_outlook_counts_the_recommended_starters_this_week(league):
    refresh(league)
    lineup = league.get(f"/seasons/{LEAGUE}/lineup").json()
    outlook = league.get(f"/seasons/{LEAGUE}/outlook").json()
    this = next(w for w in outlook["weeks"] if w["week"] == lineup["week"])
    assert {r["player"]: r["started"] for r in this["players"] if r["started"]} == starts(lineup)


def test_a_later_week_ranks_by_value(league):
    refresh(league)
    built = league.app.state.seasons._built(LEAGUE, None)
    p_ = built.problem
    span = p_.horizons["three"][0]
    out = sl.recommended(built, season_of(league), TODAY, span, span.days[0])
    active = list(p_.roster)
    playing = wk.playing_days(
        active,
        span.days,
        p_.schedule,
        False,
        games=span.games,
        no_games=p_.no_games,
        available_from=p_.returns,
    )
    assert out.chosen is None
    assert out.days == wk.daily_starters(active, playing, list(span.days), p_.slots, p_.value)


def test_an_unread_matchup_ranks_by_value(league):
    refresh(league)
    built = league.app.state.seasons._built(LEAGUE, None)
    p_ = built.problem
    span = replace(p_.horizons["week"][0], opponents=(), so_far_theirs=())
    out = sl.recommended(built, season_of(league), TODAY, span, span.days[0])
    assert out.chosen is None


def test_the_route_keeps_a_begun_teams_players_where_yahoo_has_them(league):
    # Everyone benched today: Yahoo's lineup keeps nobody on it, and one team's game began.
    league.fake.lineups[4, TODAY] = moved(fixture("team4.html"), bench_all=True)
    refresh(league)
    before = league.get(f"/seasons/{LEAGUE}/lineup").json()
    today = next(d for d in before["days"] if d["date"] == TODAY.isoformat())
    assert today["recommended"] and today["yahoo"]
    starter = next(x["player"] for x in today["recommended"] if x["player"])
    team = before["players"][str(starter)]["nba_team"]
    began = NOW.replace(hour=NOW.hour - 1).isoformat()
    path = league.data_dir / SCHEDULE_DIR / f"{TODAY.isoformat()}.json"
    path.parent.mkdir(exist_ok=True)
    body = json.loads(path.read_text()) if path.exists() else {"teams": [team]}
    path.write_text(json.dumps({**body, "tips": {team: began}}))
    after = league.get(f"/seasons/{LEAGUE}/lineup").json()
    day = next(d for d in after["days"] if d["date"] == TODAY.isoformat())
    on = {x["player"] for x in day["recommended"] if x["player"]}
    # Nobody of that team starts: each is off the lineup as read and cannot move on.
    assert all(after["players"][str(k)]["nba_team"] != team for k in on)
    assert starter not in on
