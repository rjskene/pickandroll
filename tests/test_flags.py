"""The breakout flag (#95): each signal on a known answer, the levels, the parsers of its inputs
and the public digest. Player names are real, every number is made up."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import pytest

from pickandroll.season import flags as fl
from pickandroll.sources.injuries import parse_injuries
from pickandroll.sources.yahoo import pages, public

FIXTURES = Path(__file__).parent / "fixtures" / "season"
TODAY = date(2026, 10, 21)


def pickup(**kw) -> fl.Pickup:
    base = {
        "yahoo_id": 1,
        "name": "Duncan Robinson",
        "nba_team": "DET",
        "positions": ("SG", "SF"),
        "pct_rostered": 10.0,
        "pct_rostered_change": 0.0,
        "adds": None,
    }
    return fl.Pickup(**{**base, **kw})


def inputs(**kw) -> fl.Inputs:
    return fl.Inputs(today=TODAY, **kw)


# --------------------------------------------------------------------------- adds surge
@pytest.mark.parametrize(
    ("pct", "change", "score"),
    [
        (7.0, 5.0, 1.0),  # 2% to 7%: five over two, the full score
        (3.0, 1.0, 0.2),  # 2% to 3%: one over two, over 2.5
        (1.0, 1.0, 0.4),  # 0% to 1%: the level is floored at 1%, not infinite
        (60.0, 5.0, 5 / 55 / 2.5),  # a star gaining five is quiet
        (10.0, -2.0, 0.0),  # a fall says nothing
    ],
)
def test_the_surge_jump_is_the_change_over_his_own_level(pct, change, score):
    s = fl.adds_surge(pickup(pct_rostered=pct, pct_rostered_change=change), inputs())
    assert s.score == pytest.approx(score)


def test_the_surge_adds_part_reads_his_median_once_three_days_are_kept():
    history = {1: [100, 120, 80]}
    full = fl.adds_surge(pickup(adds=800), inputs(history=history))
    assert full.score == pytest.approx(1.0) and "8.0x his 3-day median" in full.reason
    third = fl.adds_surge(pickup(adds=200), inputs(history=history))
    assert third.score == pytest.approx(math.log(2) / math.log(8))
    # A median under 25 adds counts as 25: 10 a day to 200 is 8x the floor.
    floored = fl.adds_surge(pickup(adds=200), inputs(history={1: [10, 10, 10]}))
    assert floored.score == pytest.approx(1.0)
    quiet = fl.adds_surge(pickup(adds=50), inputs(history=history))
    assert quiet.score == 0.0 and quiet.reason is None


def test_before_three_days_the_surge_reads_the_buzz_rank():
    assert fl.adds_surge(pickup(adds=900), inputs(buzz_rank={1: 1})).score == pytest.approx(1.0)
    assert fl.adds_surge(pickup(adds=90), inputs(buzz_rank={1: 50})).score == pytest.approx(0.3)
    mid = fl.adds_surge(pickup(adds=400), inputs(buzz_rank={1: 25}, history={1: [5, 5]}))
    assert mid.score == pytest.approx(1 - 0.7 * 24 / 49)
    assert mid.public == "400 adds today, #25 by adds on Yahoo's buzz index"
    assert fl.adds_surge(pickup(), inputs()).score == 0.0


def test_the_surge_is_the_louder_part():
    s = fl.adds_surge(
        pickup(pct_rostered=3.0, pct_rostered_change=1.0, adds=900), inputs(buzz_rank={1: 50})
    )
    assert s.score == pytest.approx(0.3)
    assert s.reason == s.public  # every number in it is Yahoo's


# --------------------------------------------------------------------------- minutes trend
def windows(*ws: tuple[int, float, float, float | None]) -> dict[int, list[fl.Window]]:
    return {1: [fl.Window(d, g, m, u) for d, g, m, u in ws]}


def test_the_minutes_trend_is_the_smaller_gain_of_the_windows_with_games():
    proj = {1: fl.Projection(20.0)}
    # 28 a game over 7 days and 26 over 14 against 20: the smaller gain, 6 of 8.
    s = fl.minutes_trend(
        pickup(), inputs(projected=proj, recent=windows((7, 3, 84, None), (14, 6, 156, None)))
    )
    assert s.score == pytest.approx(0.75)
    assert s.public == "minutes up" and "28.0 min over the last 7 days" in s.reason
    # One game in 7 days is under its floor of two: the 14 days alone count.
    s = fl.minutes_trend(
        pickup(), inputs(projected=proj, recent=windows((7, 1, 40, None), (14, 4, 112, None)))
    )
    assert s.score == pytest.approx(1.0) and set(s.facts["windows"]) == {14}
    # Three games in 14 days is under four: nothing to read.
    s = fl.minutes_trend(pickup(), inputs(projected=proj, recent=windows((14, 3, 90, None))))
    assert s.score == 0.0
    # No projection: nothing to measure against.
    assert fl.minutes_trend(pickup(), inputs(recent=windows((7, 3, 84, None)))).score == 0.0


def test_usage_counts_at_half_weight_and_the_larger_part_stands():
    proj = {1: fl.Projection(20.0, usage=18.0)}
    # Minutes flat, usage up 5 or more on both windows: half of a full usage score.
    s = fl.minutes_trend(
        pickup(), inputs(projected=proj, recent=windows((7, 3, 60, 25.0), (14, 6, 120, 23.0)))
    )
    assert s.score == pytest.approx(0.5) and "usage +5.0" in s.reason
    # Minutes up 4 (0.5) and usage up 2.5 (0.25 at half weight): the minutes stand.
    s = fl.minutes_trend(pickup(), inputs(projected=proj, recent=windows((7, 2, 48, 20.5))))
    assert s.score == pytest.approx(0.5)


# --------------------------------------------------------------------------- value gap
@pytest.mark.parametrize(
    ("rank", "pct", "score"),
    [
        (60, 25.0, 0.75 * 0.5),
        (1, 0.0, 1 - 1 / 240),
        (120, 10.0, 0.5 * 0.8),
        (121, 10.0, 0.0),  # outside the top 120
        (40, 50.0, 0.0),  # rostered in half of Yahoo's leagues
    ],
)
def test_the_value_gap_falls_with_rank_and_ownership(rank, pct, score):
    s = fl.value_gap(pickup(pct_rostered=pct), inputs(value_rank={1: rank}))
    assert s.score == pytest.approx(score)
    if score:
        assert s.public == "value gap" and str(rank) not in s.public


# --------------------------------------------------------------------------- opportunity
def injury(name, team="DET", groups=("G",), status="Out", days=20, mpg=None) -> fl.Injury:
    returns = TODAY + timedelta(days=days) if days is not None else None
    return fl.Injury(name, team, frozenset(groups), status, returns, mpg)


def test_opportunity_counts_teammates_at_his_position_out_for_weeks():
    out = [injury("Cade Cunningham", mpg=34.0)]
    s = fl.opportunity(pickup(), inputs(injuries=out))
    assert s.score == pytest.approx(1.0)
    assert "34 projected min" in s.reason and "projected" not in s.public
    assert "Cade Cunningham (G) out, est. return Nov 10" in s.public
    # Without a projection a teammate counts 15 minutes.
    assert fl.opportunity(
        pickup(), inputs(injuries=[injury("Cade Cunningham")])
    ).score == pytest.approx(0.5)


@pytest.mark.parametrize(
    "hurt",
    [
        injury("Cade Cunningham", days=13),  # back inside two weeks
        injury("Cade Cunningham", days=None),  # no return date
        injury("Cade Cunningham", status="Day-To-Day"),
        injury("Jalen Duren", groups=("C",)),  # another position
        injury("Devin Vassell", team="SAS"),  # another team
        injury("Duncan Robinson", groups=("G", "F")),  # himself
    ],
)
def test_opportunity_ignores_other_cases(hurt):
    assert fl.opportunity(pickup(), inputs(injuries=[hurt])).score == 0.0


def test_a_player_out_himself_takes_no_opportunity():
    out = [injury("Cade Cunningham", mpg=34.0)]
    assert fl.opportunity(pickup(status="O"), inputs(injuries=out)).score == 0.0
    assert fl.opportunity(pickup(status="INJ"), inputs(injuries=out)).score == 0.0
    # On ESPN's report as out, whatever Yahoo says.
    hurt = [*out, injury("Duncan Robinson", groups=("G", "F"), days=30)]
    assert fl.opportunity(pickup(), inputs(injuries=hurt)).score == 0.0
    # A doubt is not out.
    assert fl.opportunity(pickup(status="GTD"), inputs(injuries=out)).score == pytest.approx(1.0)


def test_position_groups_read_yahoo_and_espn_positions():
    assert fl.position_groups(["PG", "SG"]) == {"G"}
    assert fl.position_groups(["G-F"]) == {"G", "F"}
    assert fl.position_groups(["PF", "C"]) == {"F", "C"}
    assert fl.position_groups(["Util"]) == frozenset()


# --------------------------------------------------------------------------- levels
@pytest.mark.parametrize(
    ("score", "level"),
    [(0.0, None), (0.79, None), (0.8, "watch"), (1.49, "watch"), (1.5, "add"), (2.2, "must-add")],
)
def test_the_levels(score, level):
    assert fl.level_of(score) == level


def test_the_flag_sums_the_signals_and_only_players_a_signal_speaks_for_are_kept():
    loud = pickup(yahoo_id=1, adds=900)
    quiet = pickup(yahoo_id=2, name="Pelle Larsson", nba_team="MIA")
    i = inputs(buzz_rank={1: 1}, value_rank={1: 60}, injuries=[injury("Cade Cunningham")])
    out = fl.flags([loud, quiet], i)
    assert set(out) == {1}
    assert out[1].score == pytest.approx(1.0 + 0.75 * 0.8 + 0.5)
    assert out[1].level == "add"
    d = out[1].to_dict()
    assert d["level"] == "add" and set(d["signals"]) == set(fl.SIGNALS)


# --------------------------------------------------------------------------- the digest
def test_the_digest_names_leagues_by_id_and_prints_no_basketball_monster_number():
    a = pickup(yahoo_id=1, adds=900)
    b = pickup(yahoo_id=2, name="Keldon Johnson", nba_team="SAS", positions=("SF", "PF"))
    i = inputs(
        buzz_rank={1: 1},
        value_rank={1: 37, 2: 88},
        projected={1: fl.Projection(19.0), 2: fl.Projection(23.0)},
        recent={1: [fl.Window(7, 3, 87, None)], 2: [fl.Window(14, 5, 160, None)]},
        injuries=[injury("Cade Cunningham", mpg=33.0), injury("Devin Vassell", "SAS", ("G", "F"))],
    )
    c = pickup(yahoo_id=3, name="Pelle Larsson", nba_team="MIA", adds=300)
    i = fl.Inputs(**{**i.__dict__, "buzz_rank": {1: 1, 3: 2}})
    fa, fb, fc = fl.flag(a, i), fl.flag(b, i), fl.flag(c, i)
    assert (fa.level, fb.level, fc.level) == ("must-add", "add", "watch")
    leagues = [("100001", [(a, fa), (c, fc)]), ("100002", [(b, fb)])]
    text = fl.digest_markdown(TODAY, leagues, ["no x"])
    assert text.startswith("## Breakout flags, Wed Oct 21")
    assert "### League 100001" in text and "### League 100002" in text
    assert "- **must-add** Duncan Robinson (DET, SG/SF): adds surge (900 adds today" in text
    assert "minutes up; value gap; opportunity (Cade Cunningham (G) out" in text
    assert "Inputs: no x." in text
    # The watch level is a line of names.
    assert "- watch (1): Pelle Larsson (MIA)\n" in text and "**watch**" not in text
    # Nothing from the projection: no rank, no minutes a game, no projected minutes.
    for number in ("37", "88", "19", "23", "29.0", "32.0", "33"):
        assert number not in text, number
    empty = fl.digest_markdown(TODAY, [("100003", [])])
    assert "No flagged player among the available ones." in empty


# --------------------------------------------------------------------------- the parsers
def test_the_buzz_index_parses_in_page_order():
    rows = pages.parse_buzz_page((FIXTURES / "buzz.html").read_text())["rows"]
    assert [r["player"]["name"] for r in rows[:2]] == ["Andre Drummond", "Zaccharie Risacher"]
    first = rows[0]
    assert first["player"]["yahoo_id"] == 5015 and first["player"]["positions"] == ["C"]
    assert (first["pct_rostered"], first["adds"], first["drops"]) == (18.0, 7206, 120)
    with pytest.raises(pages.PageError):
        pages.parse_buzz_page("<html><body><p>nothing</p></body></html>")


def test_the_buzz_url_names_the_day():
    url = public.buzz_url(TODAY)
    assert "/buzzindex?date=2026-10-21&" in url and "sort=BI_A" in url


def test_the_injury_report_parses_with_yahoo_teams_and_return_dates():
    listed = parse_injuries((FIXTURES / "espn_injuries.json").read_text())
    assert [x.name for x in listed][:2] == ["Cade Cunningham", "Jalen Duren"]
    vassell = next(x for x in listed if x.name == "Devin Vassell")
    assert vassell.team == "SAS" and vassell.position == "G-F"  # ESPN's SA
    assert vassell.returns == date(2026, 11, 20) and vassell.key == "espn:204"
    duren = next(x for x in listed if x.name == "Jalen Duren")
    assert duren.status == "Day-To-Day"
    assert listed[0].from_dict(listed[0].to_dict()) == listed[0]
