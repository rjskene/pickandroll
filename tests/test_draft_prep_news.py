"""The draft-day news sweep (#76, scripts/draft_prep/news.py): the two pages parsed from saved
fixtures (no live fetch), the matching through the aliases file and the session's matcher, the
top-by-value and newer-than-the-export filters, the block it prints, and the status check of a
league's adjustments.json. Every page, player and team here is synthetic."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from .test_draft_prep_projections import LEAGUE, SCRIPT, command, lines, write

PAGES = Path(__file__).resolve().parent / "fixtures" / "news"
#: The export's time: news after it is news the projections may not have.
EXPORTED = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
WEIGHTS = {"pts": 1.0, "reb": 1.2, "ast": 1.5, "stl": 3.0, "blk": 3.0, "tov": -1.0}
#: Players the pages name who are projected among the best; one who is projected far down.
STARS = ["Ari Ash", "Bo Birch", "Dax Dune", "Ivo Iris", "Jem Juniper", "Kip Kestrel", "Lou Larch"]
DEEP = "Cal Cedar"


def news(runbook):
    return runbook.PREP["news"]


@pytest.fixture
def runbook(tmp_path, monkeypatch):
    """The script as a module, its root moved to a scratch folder with one points league."""
    spec = importlib.util.spec_from_file_location("draft_day_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    data = tmp_path / "data"
    (data / "leagues" / LEAGUE).mkdir(parents=True)
    (data / "fidelity").mkdir()
    settings = {"scoring": "points", "num_teams": 12, "points": WEIGHTS}
    (data / "leagues" / LEAGUE / "settings.json").write_text(json.dumps(settings))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "DATA", data)
    return module


@pytest.fixture
def league(runbook):
    """A points league and an export from before the news: the pages' players at the top of
    it, one far down."""
    df = lines()
    name = df["first_name"] + " " + df["last_name"]
    counting = [c for c in df.columns if c not in ("player_id", "last_name", "first_name")]
    counting = [c for c in counting if c not in ("games", "comments")]
    df.loc[name.isin(STARS), counting] *= 3.0
    df.loc[name == DEEP, counting] *= 0.05
    write(runbook.DATA / "bbm_projections_2026-10-17.csv", df, EXPORTED.timestamp())
    return runbook


def projected(runbook):
    from pickandroll.sources.bbm import load_bbm

    return load_bbm(runbook.DATA / runbook.newest_projections()).df


# --------------------------------------------------------------------------- the pages
def test_espn_items_carry_status_injury_return_and_time():
    items = {
        i.name: i for i in news_module().parse_espn((PAGES / "espn_injuries.json").read_text())
    }
    assert len(items) == 6
    ash = items["Ari Ash"]
    assert ash.key == "espn:101" and ash.team == "AAA" and ash.source == "ESPN"
    assert ash.status == "Out (Ankle; est. return Nov 10)"
    assert ash.when == datetime(2026, 10, 17, 18, 0, tzinfo=UTC) and not ash.day_only
    assert items["Dax Dune Jr."].status == "Day-To-Day"


def test_rotowire_headlines_carry_their_day_and_hold_back_a_game_line():
    items = {
        i.name: i for i in news_module().parse_rotowire((PAGES / "rotowire_news.html").read_text())
    }
    assert set(items) == {"Jem Juniper", "Kip Kestrel", "Lou Larch", "Eli Elm & Co"}
    jem = items["Jem Juniper"]
    assert jem.key == "rotowire:7001" and jem.day_only and jem.status == "Questionable for opener"
    assert items["Kip Kestrel"].status == "game line (not shown)"


def news_module():
    import sys

    sys.path.insert(0, str(SCRIPT.parent))
    import draft_prep.news

    return draft_prep.news


# --------------------------------------------------------------------------- the sweep
def test_the_sweep_lists_the_top_players_news_and_the_unmatched_names(league, monkeypatch, capsys):
    df = projected(league)
    iris = df.index[df["player"] == "Ivo Iris"][0]
    # ESPN calls him Ivan: the pin by ESPN's key brings him in.
    (league.DATA / "aliases.json").write_text(json.dumps({"espn:109": str(iris)}))
    code = command(league, monkeypatch, "news", LEAGUE, "--news-from", str(PAGES))
    assert code == league.OK
    out = capsys.readouterr().out
    table = [line for line in out.splitlines() if line.startswith("| ") and "---" not in line]
    names = [line.split(" | ")[0].lstrip("| ") for line in table[1:]]
    # Newest first; newer than the export only (Bo Birch's and Lou Larch's are older); the top
    # players only (Cal Cedar is projected far down); matched by suffix (Dax Dune Jr.), by pin
    # (Ivan Iris) and by name.
    assert names == ["Ari Ash", "Dax Dune Jr.", "Ivan Iris", "Jem Juniper", "Kip Kestrel"]
    assert "| Ari Ash | Out (Ankle; est. return Nov 10) | Sat Oct 17 11:00 PDT | ESPN |" in out
    assert "| Jem Juniper | Questionable for opener | Sat Oct 17 | Rotowire |" in out
    assert "31 points" not in out and "game line (not shown)" in out
    assert "Names matching no projected player (2; " in out
    assert "Zed Nobody (ESPN), Eli Elm & Co (Rotowire)" in out
    assert "Sources: ESPN injuries 6 items; Rotowire headlines 4 items." in out
    assert "Cal Cedar" not in out and "Bo Birch" not in out and "Lou Larch" not in out
    saved = list((league.DATA / "draft_day" / LEAGUE).glob("news_*.md"))
    assert len(saved) == 1 and "| Ari Ash |" in saved[0].read_text()


def test_without_the_pin_the_renamed_player_is_unmatched_not_dropped(league, monkeypatch, capsys):
    assert command(league, monkeypatch, "news", LEAGUE, "--news-from", str(PAGES)) == league.OK
    out = capsys.readouterr().out
    assert "| Ivan Iris |" not in out
    assert "Zed Nobody (ESPN), Ivan Iris (ESPN), Eli Elm & Co (Rotowire)" in out


def test_a_top_of_one_and_a_page_that_does_not_read(league, monkeypatch, capsys, tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "espn_injuries.json").write_text((PAGES / "espn_injuries.json").read_text())
    (pages / "rotowire_news.html").write_bytes(b"")
    (pages / "rotowire_news.html").unlink()
    code = command(
        league, monkeypatch, "news", LEAGUE, "--news-from", str(pages), "--news-top", "1"
    )
    assert code == league.OK
    out = capsys.readouterr().out
    assert "for the top 1 by projected value" in out
    assert "Rotowire headlines NOT READ" in out and "ALERT news: Rotowire headlines" in out
    # Nothing read at all: the sweep did nothing, and says so.
    (pages / "espn_injuries.json").write_text("{not json")
    assert command(league, monkeypatch, "news", LEAGUE, "--news-from", str(pages)) == league.ERROR
    assert "ESPN injuries NOT READ (does not parse" in capsys.readouterr().out


def test_news_needs_a_league(runbook, monkeypatch, capsys):
    with pytest.raises(SystemExit):
        command(runbook, monkeypatch, "news")
    assert "news needs a league id" in capsys.readouterr().err


def test_newer_counts_a_headline_of_the_exports_day(league):
    mod = news(league)
    day = mod.Item("k", "n", "", "s", datetime(2026, 10, 17, 4, 0, tzinfo=UTC), "R", day_only=True)
    timed = mod.Item("k", "n", "", "s", datetime(2026, 10, 17, 11, 59, tzinfo=UTC), "E")
    assert mod.newer(day, EXPORTED) and not mod.newer(timed, EXPORTED)


# --------------------------------------------------------------------------- the haircuts
def test_status_checks_the_leagues_adjustments_file(league, capsys):
    path = league.DATA / "leagues" / LEAGUE / "adjustments.json"
    path.write_text(
        json.dumps(
            [
                {"player": "Ari Ash", "games_out": 15, "note": "out 4 weeks"},
                {"player": "Jem Juniper", "games_fraction": 0.5},
                {"player": "Zed Nobody", "games_out": 3},
            ]
        )
    )
    news(league).on_status(league, LEAGUE)
    out = capsys.readouterr().out
    assert (
        "adjustments.json: 2 games haircuts applied at attach "
        "(Ari Ash 15 games out, Jem Juniper 0.5 of his games)"
    ) in out
    assert "ALERT adjustments.json: adjustments.json entry 3: no projected player named" in out
