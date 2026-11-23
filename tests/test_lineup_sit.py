"""Sitting a player to protect close categories (#482): a day's chosen set gives way to a smaller
one when that gains :data:`season.lineup.SIT_MARGIN`, and nobody starts in a sat player's place.

Made-up players and lines throughout; nothing here is from Basketball Monster.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import season_lineup as sl
from pickandroll.api.seasons import season_dir
from pickandroll.season import Player
from pickandroll.season import lineup as lu
from pickandroll.season import weekly as wk
from pickandroll.season.state import RosterSpot
from tests.test_lineup import lineup_league, moved
from tests.test_season import LEAGUE, TODAY, fixture, season_client

SUN = date(2026, 10, 25)
WEEK = [SUN - timedelta(days=6 - i) for i in range(7)]
CATS = ("pts", "tov", "fg_pct")
SLOTS = ["Util", "Util"]


def line(pts=0.0, tov=0.0, fgm=0.0, fga=0.0) -> dict[str, float]:
    return {"pts": pts, "tov": tov, "fgm": fgm, "fga": fga}


#: 1 shoots well and rarely turns it over; 2 shoots badly and turns it over a lot. Points are
#: decided either way.
RATES = {1: line(20.0, 1.0, 8.0, 15.0), 2: line(12.0, 4.0, 4.0, 14.0)}
VALUE = {1: 2.0, 2: 1.0}
ROSTER = [(k, Player(k, f"P{k}", "AAA", ("PG",))) for k in RATES]
#: The week's last day: far ahead in points, a close TO and a close FG%.
SO_FAR = {"pts": 600.0, "tov": 20.0, "fgm": 180.0, "fga": 380.0}
THEIRS = {"pts": (400.0, 5.0), "tov": (26.0, 2.0), "fg_pct": (0.474, 0.01)}


def solve(days=(SUN,), rates=RATES, so_far=SO_FAR, theirs=THEIRS, **kw) -> lu.WinLineup[int]:
    playing = {k: list(days) for k in rates}
    roster = [(k, Player(k, f"P{k}", "AAA", ("PG",))) for k in rates]
    return lu.win_lineup(
        roster, playing, list(days), SLOTS, VALUE, rates, CATS, so_far, theirs, **kw
    )


def won(keys, rates=RATES, so_far=SO_FAR, theirs=THEIRS, how=wk.expected_won) -> float:
    week = wk.team_week({k: wk.PlayerWeek(1, 1) for k in keys}, rates, None)
    return how(wk.odds_of(wk.finals(week, so_far, CATS), theirs, CATS))


def test_a_low_percentage_high_turnover_player_sits_when_it_clears_the_margin():
    gain = won([1]) - won([1, 2])
    assert gain >= lu.SIT_MARGIN
    out = solve()
    # The slots hold both: a day with a single largest set is searched too.
    assert len(lu._legal_sets([(k, ("PG",)) for k in RATES], SLOTS)) == 1
    assert out.days[SUN] == {1: "Util"}
    sit = out.sits[SUN]
    assert sit.players == (2,)
    assert sit.gain == pytest.approx(gain)
    moved = {cat for cat, _, _ in sit.cats}
    assert moved == {"tov", "fg_pct"}
    assert all(after > before for _, before, after in sit.cats)


def test_nobody_sits_for_a_gain_under_the_margin():
    # A milder 2: the percentage and the turnovers move, by less than the margin.
    rates = {**RATES, 2: line(12.0, 2.0, 6.0, 13.0)}
    theirs = {**THEIRS, "tov": (30.0, 2.0)}
    gain = won([1], rates, theirs=theirs) - won([1, 2], rates, theirs=theirs)
    assert 0 < gain < lu.SIT_MARGIN
    out = solve(rates=rates, theirs=theirs)
    assert set(out.days[SUN]) == {1, 2} and out.sits == {}


def test_a_one_win_league_sits_on_the_matchups_odds():
    # Points are won either way, so the matchup is TO and FG%: on the odds, sitting both pays most,
    # where expected categories sit only 2.
    odds = {keys: won(keys, how=wk.matchup_won) for keys in [(), (1,), (2,), (1, 2)]}
    assert max(odds, key=odds.__getitem__) == ()
    assert solve().sits[SUN].players == (2,)
    out = solve(one_win=True)
    assert out.sits[SUN].players == (1, 2)
    assert out.sits[SUN].gain == pytest.approx(odds[()] - odds[(1, 2)])
    assert out.days[SUN] == {}


def test_a_one_win_gain_under_the_margin_on_the_odds_sits_nobody():
    # Points decide nothing and the matchup is won either way: the odds barely move.
    theirs = {**THEIRS, "tov": (40.0, 2.0), "fg_pct": (0.40, 0.01)}
    assert (
        won([1], theirs=theirs, how=wk.matchup_won) - won([1, 2], theirs=theirs, how=wk.matchup_won)
        < lu.SIT_MARGIN
    )
    assert solve(theirs=theirs, one_win=True).sits == {}


def test_a_locked_player_is_never_sat_or_moved():
    # 2's game began with him in a starting slot: he stays there, whatever sitting him would gain.
    out = solve(locked={SUN: lu.Locked(on={2: "Util"})})
    assert out.days[SUN] == {2: "Util", 1: "Util"}
    assert out.sits == {}
    # Off the lineup when his game began: he stays off, and 1 starts.
    out = solve(locked={SUN: lu.Locked(off=frozenset({2}))})
    assert out.days[SUN] == {1: "Util"} and out.sits == {}


def test_early_in_the_week_the_odds_are_wide_and_nobody_sits():
    # Monday with the whole week ahead and every race open, points too: a milder 2 costs a
    # little FG% and TO a day, and a day's points are worth more than that.
    rates = {**RATES, 2: line(14.0, 2.5, 6.0, 14.0)}
    so_far = {"pts": 0.0, "tov": 0.0, "fgm": 0.0, "fga": 0.0}
    theirs = {"pts": (238.0, 25.0), "tov": (25.0, 5.0), "fg_pct": (0.48, 0.02)}
    out = solve(days=WEEK, rates=rates, so_far=so_far, theirs=theirs)
    assert out.sits == {}
    assert all(set(out.days[d]) == {1, 2} for d in WEEK)


def test_the_set_is_searched_whole_where_no_single_sit_pays():
    # Two high-turnover players: TO is lost with either one, won only with both sat; sitting one
    # loses points for nothing. 1 keeps the points race alive.
    rates = {
        1: line(20.0, 1.0, 10.0, 16.0),
        2: line(10.0, 3.0, 4.0, 8.0),
        3: line(10.0, 3.0, 4.0, 8.0),
    }
    so_far = {"pts": 400.0, "tov": 30.0, "fgm": 180.0, "fga": 360.0}
    theirs = {"pts": (425.0, 8.0), "tov": (32.5, 0.5), "fg_pct": (0.45, 0.01)}
    full = won([1, 2, 3], rates, so_far, theirs)
    assert won([1, 2], rates, so_far, theirs) < full
    assert won([1], rates, so_far, theirs) - full >= lu.SIT_MARGIN
    assert won([1], rates, so_far, theirs) > won([], rates, so_far, theirs)
    playing = {k: [SUN] for k in rates}
    roster = [(k, Player(k, f"P{k}", "AAA", ("PG",))) for k in rates]
    value = {1: 3.0, 2: 2.0, 3: 1.0}
    out = lu.win_lineup(roster, playing, [SUN], ["Util"] * 3, value, rates, CATS, so_far, theirs)
    assert out.sits[SUN].players == (2, 3)
    assert out.days[SUN] == {1: "Util"}


def test_win_starters_is_win_lineups_days():
    playing = {k: [SUN] for k in RATES}
    args = (ROSTER, playing, [SUN], SLOTS, VALUE, RATES, CATS, SO_FAR, THEIRS)
    assert lu.win_starters(*args) == lu.win_lineup(*args).days


def test_compare_sits_a_deliberate_sit_yahoo_starts_with_nobody_to_start():
    spots = [RosterSpot("Util", Player(k, f"P{k}", "AAA", ("PG",))) for k in RATES]
    line_ = lu.compare(SUN, {1: "Util"}, spots, {1: [SUN], 2: [SUN]}, SLOTS, sits=(2,))
    assert line_.start == () and line_.sit == (2,)
    # Without the sit named, a starter left out with nobody to start is not asked to move.
    assert lu.compare(SUN, {1: "Util"}, spots, {1: [SUN], 2: [SUN]}, SLOTS).sit == ()


# --------------------------------------------------------------------------- the route and steps
THU = "2026-10-22"


def started_lineup_page(client, day: str) -> str:
    """Yahoo's team page for ``day`` as Start Active Players leaves it: every recommended starter
    who plays in his slot (the fixture's recommendation has no sit)."""
    lineup = client.get(f"/seasons/{LEAGUE}/lineup").json()
    d = next(x for x in lineup["days"] if x["date"] == day)
    slots = {
        lineup["players"][str(x["player"])]["name"]: x["slot"]
        for x in d["recommended"]
        if x["player"]
    }
    return moved(moved(fixture("team4.html"), bench_all=True), slots)


def test_after_start_active_the_steps_bench_the_sat_player_and_fill_nothing(tmp_path, monkeypatch):
    with season_client(tmp_path) as client:
        lineup_league(client, **{THU: moved(fixture("team4.html"), bench_all=True)})
        page = started_lineup_page(client, THU)
        lineup_league(client, **{THU: page})
        before = client.get(f"/seasons/{LEAGUE}/lineup").json()
        day = next(x for x in before["days"] if x["date"] == THU)
        # Start Active's lineup is the recommended one: nothing to change, nobody sat.
        assert day["start"] == [] and day["sit"] == [] and day["sits"] is None
        on = [x["player"] for x in day["recommended"] if x["player"] in day["playing"]]
        steps = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": THU}).json()
        assert steps["steps"] == []
        sat = on[0]

        real = lu.win_lineup
        thu = date.fromisoformat(THU)

        def with_a_sit(*args, **kwargs):
            out = real(*args, **kwargs)
            if thu not in out.days:
                return out
            days = {**out.days, thu: {k: s for k, s in out.days[thu].items() if k != sat}}
            sit = lu.Sit((sat,), 0.21, (("tov", 0.30, 0.86), ("fg_pct", 0.41, 0.55)))
            return lu.WinLineup(days, {**out.sits, thu: sit})

        monkeypatch.setattr(lu, "win_lineup", with_a_sit)
        after = client.get(f"/seasons/{LEAGUE}/lineup").json()
        day = next(x for x in after["days"] if x["date"] == THU)
        assert day["sits"] == {
            "players": [sat],
            "gain": 0.21,
            "unit": "categories",
            "cats": [
                {"cat": "tov", "before": 0.30, "after": 0.86},
                {"cat": "fg_pct", "before": 0.41, "after": 0.55},
            ],
        }
        assert sat not in {x["player"] for x in day["recommended"]}
        assert sat in day["bench"]
        assert day["start"] == [] and day["sit"] == [sat]
        steps = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": THU}).json()
        assert steps["open"] and steps["reason"] is None
        # One step: the sat player to the bench, nobody into his slot.
        assert [(x["player"], x["to_slot"], x["with"]) for x in steps["steps"]] == [
            (sat, "BN", None)
        ]
        assert steps["target"] == {str(sat): "BN"}
        assert steps["games"]["after"] == steps["games"]["yahoo"] - 1


# --------------------------------------------------------------------------- sat, not lost (#149)
def sits(players, gain=0.2) -> dict:
    return {"players": players, "gain": gain, "unit": "categories", "cats": []}


def test_the_days_sits_are_recorded_once_each_and_read_back_by_day(tmp_path):
    at = datetime(2026, 10, 25, 10, tzinfo=UTC)
    today = {"date": SUN.isoformat(), "past": False, "sits": sits([2, 3])}
    payload = {"days": [{"date": "2026-10-24", "past": True, "sits": sits([5])}, today]}
    assert sl.record_sits(tmp_path, payload, SUN, at) == [2, 3]
    # The same sit again writes nothing; a later solve's new player is added with its time.
    assert sl.record_sits(tmp_path, payload, SUN, at) == []
    later = {"days": [{**today, "sits": sits([3, 4], 0.3)}]}
    assert sl.record_sits(tmp_path, later, SUN, at.replace(hour=12)) == [4]
    assert sl.sits_read(tmp_path) == {SUN: frozenset({2, 3, 4})}
    body = (tmp_path / sl.SITS_FILE).read_text()
    assert '"with": [\n    3,\n    4\n   ]' in body
    # No sit today, a past day, or another day: nothing recorded.
    assert sl.record_sits(tmp_path, {"days": [{**today, "sits": None}]}, SUN, at) == []
    assert sl.record_sits(tmp_path, payload, SUN + timedelta(days=1), at) == []
    # A record that does not read counts as none.
    (tmp_path / sl.SITS_FILE).write_text("{not json")
    assert sl.sits_read(tmp_path) == {}


def test_the_lineup_route_records_todays_sit(tmp_path, monkeypatch):
    with season_client(tmp_path) as client:
        lineup_league(client)
        real = lu.win_lineup

        def with_a_sit(*args, **kwargs):
            out = real(*args, **kwargs)
            on = [k for k in out.days.get(TODAY, {}) if TODAY in args[1].get(k, ())]
            if not on:
                return out
            days = {**out.days, TODAY: {k: s for k, s in out.days[TODAY].items() if k != on[0]}}
            return lu.WinLineup(days, {**out.sits, TODAY: lu.Sit((on[0],), 0.2, ())})

        monkeypatch.setattr(lu, "win_lineup", with_a_sit)
        day = next(
            d
            for d in client.get(f"/seasons/{LEAGUE}/lineup").json()["days"]
            if d["date"] == TODAY.isoformat()
        )
        assert day["sits"] is not None
        recorded = sl.sits_read(season_dir(client.data_dir, LEAGUE))
        assert recorded == {TODAY: frozenset(day["sits"]["players"])}
        # Another week's view records nothing more.
        client.get(f"/seasons/{LEAGUE}/lineup", params={"week": 2})
        assert sl.sits_read(season_dir(client.data_dir, LEAGUE)) == recorded
