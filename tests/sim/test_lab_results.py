"""SEASON SIM (#172, PR results tab): the lab's Results tab, each run's outcome in plain words.

Made-up records only (the helpers of ``test_lab.py``); the page is driven by the node harness.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pickandroll.sim import tune as tn
from pickandroll.sim.lab import model as md
from pickandroll.sim.lab import server as sv
from tests.sim.test_lab import (
    BANNED,
    ENGINE,
    GENERATED,
    GOOD,
    MARK,
    ONE_WIN,
    STATIC,
    block,
    built,
    marked,
    on_version,
    row,
    screen,
    tune,
)


def card(m: dict, name: str) -> dict:
    return next(c for c in m["results"]["cards"] if c["name"] == name)


def made_screen(name: str = "s-made", **kw) -> dict:
    """A screen of every kind of row: one that did nothing (the baseline), two that cleared
    upward, one inside one SE, four that cleared downward, one not played and the row that turns
    live's update off."""
    rows = [
        row("base", "pool", 0.0, did_nothing=True),
        row("up-a", "pool", 1.2, 0.5, values=(10, 20)),
        row("up-b", "min_gain", 2.0, 0.5),
        row("level", "daily_cap", 0.3, 0.5),
        row("down-1", "rate_cv", -0.6, 0.5),
        row("down-2", "miss_rate", -1.5, 0.5),
        row("down-3", "rate_shrink", -0.9, 0.5),
        row("down-4", "stash_threshold", -3.0, 0.5),
        row("never", "guard", None, status="not played"),
        row(md.ENGINE_ROW, "later_weeks", -0.8, 0.3),
    ]
    return screen(name, ONE_WIN, rows, **kw)


# --------------------------------------------------------------------------- a screen
def test_a_screen_s_card_counts_its_changes_and_lists_those_that_cleared():
    m = built([made_screen()])
    (c,) = m["results"]["cards"]
    assert (c["kind"], c["state"], c["state_words"]) == ("screen", md.FINISHED, "played")
    assert c["ruleset_name"] == m["rulesets"][0]["name"] and c["measure_words"] == "matchup wins"
    # Its title in plain words: the ruleset and the kind; its folder's name goes beside its days.
    assert c["title"] == f"{c['ruleset_name']}: screen" and c["name"] == "s-made"
    assert c["days"] == "Jan 2, 2026"  # 10:00 UTC is the same day in Central
    r = c["screen"]
    assert r["counts"] == {
        "listed": 9, "played": 8, "up": 2, "down": 4, "mixed": 0, "level": 1,
        "did_nothing": 1, "not_played": 1, "left": 0,
    }  # fmt: skip
    # Every row that cleared upward, best first; the three largest downward, and how many more.
    assert [e["key"] for e in r["up"]] == ["up-b", "up-a"]
    assert [e["key"] for e in r["down"]] == ["down-4", "down-2", "down-3"]
    assert r["down_more"] == 1
    up = r["up"][1]
    assert (up["label"], up["values"], up["nudge"]) == (
        "Candidate pool size",
        {"a": "10", "b": "20"},
        "pool: 10 to 20",
    )
    (cell,) = up["cells"]
    assert cell["measure"] == {
        "mean": 1.2, "se": 0.5, "side": "better", "words": "better, by more than one SE",
    }  # fmt: skip
    # The playoff odds' difference is inside its SE: level, never better or worse.
    assert cell["made_playoffs"] == {
        "mean": 0.01, "se": 0.02, "side": "level", "words": "level: inside one SE",
    }  # fmt: skip
    assert r["down"][0]["cells"][0]["measure"]["side"] == "worse"
    # The baseline's line: arm A of the row that sets nothing but its tier.
    (b,) = r["baseline"]
    assert (b["season_words"], b["forecaster"], b["paths"]) == ("2022-23", "prior", 8)
    assert b["measure"]["mean"] == 5.0 and b["made_playoffs"]["mean"] == 5.0
    assert r["baseline_tier"] == "fast tier" and r["no_baseline"] is None
    # What it did says the number played, and the one listed and not played apart: the
    # sentence and the counts under it add up.
    assert c["did"] == (
        "Played 8 single changes, one knob moved one step in each, each as a pair against "
        "today's settings on 8 paths of 2022-23 (prior forecaster). 1 more was listed and not "
        "played. It also played live's update switched off, as one more pair."
    )
    n = r["counts"]
    assert n["up"] + n["down"] + n["mixed"] + n["level"] + n["did_nothing"] == n["played"]
    assert n["played"] + n["not_played"] + n["left"] == n["listed"]


def test_the_row_that_turns_live_s_update_off_is_shown_apart_the_other_way_round():
    r = card(built([made_screen()]), "s-made")["screen"]
    assert md.ENGINE_ROW not in {e["key"] for e in r["up"] + r["down"]}
    e = r["engine"]
    assert e["played"] and not e["did_nothing"]
    # Arm B turned the update off and lost 0.8 a season: the update on less off is +0.8.
    (cell,) = e["cells"]
    assert cell["measure"]["mean"] == 0.8 and cell["measure"]["side"] == "better"
    assert cell["made_playoffs"]["mean"] == -0.01
    # Two plain sentences: what the update is (no day without the notes' engine section), and
    # the difference's head; the knobs it moves go to a tip.
    assert e["words"] == (
        "Live's update (#485, #486, #487), switched off as a whole in this one pair: the "
        "engine's change, not a knob's."
    )
    assert e["on"] == "With the update on, against it off:"
    assert e["knobs"] == [
        "Later weeks' roster", "Recent-form weight", "Line's error (spread)",
        "Missed games (spread)",
    ]  # fmt: skip
    assert md.cap.taken_in("#485").id == md.ENGINE_MARK
    # With the notes' dates of live's changes, the update is said by its day.
    took = [
        {"date": "2026-11-23", "issue": i, "title": "made up", "words": "w"}
        for i in ("#485", "#486", "#487")
    ]
    m = built([made_screen()], notes=md.notes_of({"engine": took}))
    assert card(m, "s-made")["screen"]["engine"]["words"].startswith(
        "Live's update of Nov 23, 2026 (#485, #486, #487), switched off"
    )
    # A screen without the row has none.
    one = screen("s-plain", ONE_WIN, [row("base", "pool", 0.0, did_nothing=True)])
    assert card(built([one]), "s-plain")["screen"]["engine"] is None


def test_a_row_that_cleared_both_ways_in_two_cells_is_listed_with_both():
    mix = row("mix", "pool", 1.0, 0.5, season="2023")
    mix["result"]["cells"]["2024"] = {
        "prior": {
            "paths": 8,
            "difference": block("matchup_wins", -1.0, 0.5),
            "clears": True,
            "counts": {},
        }
    }
    s = screen("s-two", ONE_WIN, [row("base", "pool", 0.0, did_nothing=True), mix], seasons=(2023, 2024))  # fmt: skip
    r = card(built([s]), "s-two")["screen"]
    assert r["counts"]["mixed"] == 1 and r["cells"] == 2
    (e,) = r["up"]
    assert e["kind"] == "mixed"
    assert [c["measure"]["side"] for c in e["cells"]] == ["better", "worse"]
    assert [c["season_words"] for c in e["cells"]] == ["2022-23", "2023-24"]


def test_a_screen_in_play_says_what_is_played_and_what_is_left():
    s = made_screen("s-live", finished=None)
    s["record"]["rows"].append(row("later", "pool", None, status=md.sc.LEFT))
    s["record"]["left"] = ["later"]
    c = card(built([s]), "s-live")
    assert (c["state"], c["state_words"]) == (md.IN_PLAY, "in play")
    assert c["screen"]["counts"]["left"] == 1 and c["screen"]["counts"]["listed"] == 10
    assert c["did"].startswith("Played 8 single changes so far, one knob")
    assert " 1 more was listed and not played. 1 is left to play. " in c["did"]


@pytest.mark.parametrize("version", [6, 8])
def test_a_screen_of_version_6_and_one_of_version_8_read_alike(version):
    """A version 6 screen's pair records hold no ``by_path``; the card reads none."""
    s = made_screen()
    s["record"]["screen_version"] = version
    if version == 8:
        for p in s["pairs"].values():
            p["by_path"] = {"note": "made up", "by_season": {}}
    got = card(built([s]), "s-made")["screen"]
    assert got == card(built([made_screen()]), "s-made")["screen"]


def test_a_screen_with_no_baseline_row_says_so():
    s = screen("s-nobase", ONE_WIN, [row("up", "pool", 1.2, 0.5, both={"season_weight": 0.5})])
    r = card(built([s]), "s-nobase")["screen"]
    assert r["baseline"] == [] and r["baseline_tier"] is None
    assert r["no_baseline"].startswith("The baseline is not recorded")


# --------------------------------------------------------------------------- a tune
def test_a_finished_tune_s_card_reads_its_search_its_set_and_its_test():
    m = built([], [tune("t-1", ONE_WIN)])
    c = card(m, "t-1")
    assert (c["kind"], c["state_words"], c["days"]) == ("tune", "played", "Jan 3, 2026")
    t = c["tune"]
    (lever,) = t["levers"]
    assert (lever["label"], lever["moved"], lever["words"]) == (
        "Candidate pool size",
        True,
        "moved to 20",
    )
    up, down = lever["values"]
    assert (up["side"], up["taken"], up["standing"]) == ("better", True, "taken")
    assert (down["side"], down["mean"], down["se"]) == ("level", -0.1, 0.2)
    assert t["final"] == {
        "set": [{"lever": "pool", "label": "Candidate pool size", "value": "20"}],
        "words": None,
    }
    cf = t["confirmation"]
    assert cf["played"] and cf["status"] == "played" and cf["season_words"] == "2023-24"
    run, static = cf["cells"]
    assert (run["rivals"], static["rivals"]) == tuple(tn.RIVALS_WORDS.values())
    assert run["measure"]["mean"] == 0.3 and run["measure"]["side"] == "better"
    assert static["measure"]["mean"] == 0.15
    assert run["made_playoffs"]["side"] == "level"
    assert cf["verdict"]["words"] == "made-up verdict"  # the record's own words
    assert t["left"] is None and t["next"] is None
    assert c["title"] == f"{c['ruleset_name']}: tune"
    assert c["did"] == (
        "Searches 1 lever (candidate pool size), one at a time, each over a few values on 8 "
        "paths of 2022-23; its test is 2023-24, a season no search has played, played once with "
        "the set it chose."
    )


def _second_lever(t: dict) -> dict:
    rec = t["record"]
    rec["order"].append({"lever": "min_gain", "from": 0.5, "strength": 1.0, "place": 2})
    rec["final"] = None
    rec["confirmation"] = None
    return t


def test_a_tune_in_play_says_what_is_done_and_what_is_left():
    """Its record leaves ``left`` empty while a piece plays: the open piece says it is in play."""
    t = _second_lever(tune("t-live", ONE_WIN))
    t["record"]["timing"]["pieces"][0]["finished_at"] = None
    m = built([], [t])
    c = card(m, "t-live")
    assert (c["state"], c["state_words"]) == (md.IN_PLAY, "in play")
    done, now = c["tune"]["levers"]
    assert done["searched"] and done["words"] == "moved to 20"
    assert (now["searched"], now["label"], now["words"], now["from"]) == (
        False,
        "Minimum gain for a move",
        "in play now",
        None,  # its order's ``from`` is the screen's row that placed it, never shown as a value
    )
    assert c["tune"]["final"] is None and c["tune"]["final_words"].startswith("not chosen yet")
    assert c["tune"]["confirmation"]["status"] == "not played yet; the search comes first"
    assert c["tune"]["confirmation"]["cells"] == [] and not c["tune"]["confirmation"]["played"]
    assert c["tune"]["left"] == {"searched": 1, "levers": 2, "confirmation": True}
    assert c["tune"]["next"] == (
        "Searching: 1 of 2 levers searched; the test comes after the search."
    )
    # The Runs page's line says it too (it said "finished" before: its record has no ``left``).
    assert m["tunes"][0]["status"] == "in play"
    assert m["runs"][0]["live"]["state"] == md.IN_PLAY


def test_a_tune_stopped_between_pieces_is_paused():
    t = _second_lever(tune("t-paused", ONE_WIN))
    t["record"]["left"] = {"next": "p1-min_gain-up", "stopped": "the piece's minutes ran out"}
    m = built([], [t])
    c = card(m, "t-paused")
    assert (c["state"], c["state_words"]) == (md.PAUSED, "paused between pieces")
    assert c["tune"]["levers"][1]["words"] == "not searched yet"
    assert c["tune"]["next"].startswith("Searching: 1 of 2 levers searched")
    assert m["tunes"][0]["status"] == "left for the next piece"


@pytest.mark.parametrize("paused", [False, True])
def test_a_tune_whose_search_is_done_says_the_test_is_next(paused):
    """The final set is chosen and the confirmation is not played: in play (its piece plays
    the confirmation now) or paused between pieces (the record says the confirmation is left)."""
    t = tune("t-next", ONE_WIN)
    rec = t["record"]
    if paused:
        rec["confirmation"] = {"status": tn.NOT_YET, "season": 2024, "cells": {}}
        rec["left"] = {"next": "confirm-run", "stopped": "the piece's minutes ran out"}
    else:
        rec["confirmation"] = None
        rec["timing"]["pieces"][0]["finished_at"] = None
    c = card(built([], [t]), "t-next")
    assert c["state_words"] == ("paused between pieces" if paused else "in play")
    tu = c["tune"]
    assert tu["next"] == "Search done; the test is next."
    assert tu["final"]["set"][0]["value"] == "20"
    assert tu["confirmation"]["status"] == (
        tn.NOT_YET if paused else "not played yet; the test is next"
    )
    assert not tu["confirmation"]["played"]


def test_a_tune_with_nothing_to_confirm_says_the_record_s_words():
    t = tune("t-none", ONE_WIN)
    t["record"]["confirmation"] = {"status": tn.NOTHING_TO_CONFIRM, "cells": {}}
    t["record"]["final"] = {"set": {}, "levers": [], "tier": "surrogate", "unread": {}}
    t["record"]["steps"][0]["choice"]["key"] = None
    for v in t["record"]["steps"][0]["values"]:
        v["result"]["mean"] = 0.05
    tu = card(built([], [t]), "t-none")["tune"]
    assert tu["levers"][0]["words"] == "stayed at 10" and not tu["levers"][0]["moved"]
    assert tu["final"] == {"set": [], "words": "no lever moved: the final set is today's settings"}
    assert tu["confirmation"]["status"] == tn.NOTHING_TO_CONFIRM
    assert tu["confirmation"]["verdict"] is None


# --------------------------------------------------------------------------- every card
def test_no_runs_at_all_says_so_and_a_replay_has_no_card():
    from tests.sim.test_lab import old_replay

    for m in (built(), built(replays=[old_replay()])):
        assert m["results"]["cards"] == []
        assert m["results"]["none"] == "No screen or tune is recorded yet."
        assert [h["term"] for h in m["results"]["how"]] == ["A pair", "A screen", "A tune"]
        assert m["results"]["stands"] is None  # no notes: the strip is not drawn
    assert built()["knobs"]["line"] == md.KNOBS_LINE
    assert built()["lab_version"] == md.LAB_VERSION == 3


def test_cards_are_newest_first_and_a_run_on_an_engine_live_has_left_is_folded():
    older = on_version(made_screen("s-old"), 21)
    newer = on_version(made_screen("s-new", started="2026-01-05T10:00:00+00:00",
                                   finished="2026-01-05T12:00:00+00:00"), 21)  # fmt: skip
    t = tune("t-1", ONE_WIN)
    t["record"]["spec"]["replay_version"] = 21
    m = built([older, newer], [t], notes=md.notes_of({"engine": ENGINE[3:]}))
    assert [c["name"] for c in m["results"]["cards"]] == ["s-new", "t-1", "s-old"]
    # Live changed on the old screen's day (#9487, 2026-01-02): its figures are of the earlier
    # engine. The later runs started after it, on a version that has not taken it in: behind it.
    old = card(m, "s-old")
    assert old["folded"] and old["earlier"] == md.EARLIER_WORDS.format(
        changes="#9487 dated the run's day (2026-01-02)"
    )
    assert old["capability_words"] == md.cap_words(md.capability_of(21))
    assert card(m, "s-new")["folded"]
    # Nothing outstanding: open.
    m = built([on_version(made_screen("s-now"), 21)], notes=md.notes_of({"engine": ENGINE[1:2]}))
    assert not card(m, "s-now")["folded"] and card(m, "s-now")["earlier"] is None


def test_the_lead_s_reading_is_the_newest_assessment_that_names_the_run():
    notes = md.notes_of(
        {
            "assessments": [
                {"date": "2026-01-06", "level": "ok", "text": "the newest", "run": "s-made"},
                {
                    "date": "2026-01-06",
                    "level": "watch",
                    "text": "same day, older",
                    "run": "s-made",
                },
                {"date": "2026-01-07", "level": "ok", "text": "another run", "run": "s-other"},
                {"date": "2026-01-05", "level": "problem", "text": "older", "run": "s-made"},
                {"date": "2026-01-08", "level": "ok", "text": "a ruleset", "ruleset": "rs-x"},
            ]
        }
    )
    c = card(built([made_screen()], notes=notes), "s-made")
    assert c["reading"] == {"date": "2026-01-06", "level": "ok", "text": "the newest"}
    c = card(built([made_screen()]), "s-made")
    assert c["reading"] is None and c["no_reading"] == "not written yet"


STANDS = {"date": "2026-01-06", "lines": ["the lead's first line", "a second, with 1.5 typed"]}


def test_where_it_stands_is_the_lead_s_own_summary_from_the_notes():
    m = built([made_screen()], notes=md.notes_of({"stands": STANDS}))
    assert m["results"]["stands"] == STANDS | {"label": md.STANDS_LABEL}
    assert "not read from a record" in md.STANDS_LABEL
    assert built([made_screen()], notes=md.notes_of({}))["results"]["stands"] is None


@pytest.mark.parametrize(
    ("stands", "words"),
    [
        ([], "notes: stands: an object of date and lines"),
        ({"date": "2026-01-06"}, "notes: stands: an object of date and lines"),
        (STANDS | {"by": "x"}, "notes: stands: an object of date and lines"),
        (STANDS | {"date": "6 Jan"}, "notes: stands.date: '6 Jan' is not a date (YYYY-MM-DD)"),
        (STANDS | {"lines": []}, "notes: stands.lines: a list of one line or more"),
        (STANDS | {"lines": "one"}, "notes: stands.lines: a list of one line or more"),
        (STANDS | {"lines": ["a", ""]}, "notes: stands.lines[1]: a non-empty text"),
    ],
)
def test_a_malformed_stands_is_refused_by_name(stands, words):
    with pytest.raises(md.NotesError, match=re.escape(words)):
        md.notes_of({"stands": stands})


def test_what_a_card_does_not_show_is_fixed_by_kind():
    m = built([made_screen()], [tune("t-1", ONE_WIN)])
    assert card(m, "s-made")["not_shown"] == [
        "One season and one seed: another season or another seed can move any row.",
        md.NOT_SHOWN["screen"],
        md.NO_LIVE,
    ]
    assert card(m, "t-1")["not_shown"] == [
        "One season searched and one seed; the test is one more season, played once.",
        md.NOT_SHOWN["tune"],
        md.NO_LIVE,
    ]
    assert md.not_shown_of("screen", [2023, 2024])[0].startswith("2 seasons and one seed")


def test_the_card_s_own_words_hold_no_banned_word():
    m = built([made_screen()], [tune("t-1", ONE_WIN)])
    words = [md.ENGINE_WORDS, md.EARLIER_WORDS, md.KNOBS_LINE, md.NO_LIVE, md.NO_RUNS]
    words += [h["words"] for h in md.READ_HOW] + list(md.NOT_SHOWN.values())
    words += [c["did"] for c in m["results"]["cards"]] + list(md.SIDE_WORDS.values())
    for w in words:
        assert not BANNED.search(w), (w, BANNED.search(w).group(0))


@pytest.mark.parametrize(
    ("pieces", "words"),
    [
        ([], None),
        ([{"started_at": "2026-11-24T15:00:00+00:00", "finished_at": None}], "Nov 24, 2026"),
        (
            [
                {"started_at": "2026-11-24T15:00:00+00:00", "finished_at": "2026-11-25T01:00:00+00:00"},
                {"started_at": "2026-11-26T15:00:00+00:00", "finished_at": "2026-11-26T20:00:00+00:00"},
            ],
            "Nov 24 to Nov 26, 2026",
        ),
        (
            [{"started_at": "2026-12-31T15:00:00+00:00", "finished_at": "2027-01-02T15:00:00+00:00"}],
            "Dec 31, 2026 to Jan 2, 2027",
        ),
        # 03:00 UTC on the 25th is the evening of the 24th in Central.
        ([{"started_at": "2026-11-25T03:00:00+00:00", "finished_at": None}], "Nov 24, 2026"),
    ],
)  # fmt: skip
def test_the_days_a_run_was_played_are_central_days(pieces, words):
    assert md.days_words(pieces) == words


# --------------------------------------------------------------------------- the page
def _model(tmp_path: Path) -> Path:
    t_live = _second_lever(tune("t-live", ONE_WIN))
    t_live["record"]["timing"]["pieces"][0]["finished_at"] = None
    notes = md.notes_of(
        GOOD
        | {
            "rulesets": {},
            "assessments": [{"date": "2026-01-06", "level": "ok", "text": "read", "run": "s-made"}],
            "stands": STANDS | {"lines": [MARK + " a line the lead typed"]},
        }
    )
    m = built([made_screen(), on_version(made_screen("s-old"), 21)], [tune("t-1", ONE_WIN), t_live],
              notes=notes)  # fmt: skip
    m = marked(json.loads(json.dumps(m, default=str)))
    f = tmp_path / "m.json"
    f.write_text(json.dumps(m))
    return f


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_results_tab_is_first_draws_every_card_and_escapes_every_value(tmp_path):
    f = _model(tmp_path)
    harness = Path(__file__).with_name("lab_page_harness.js")
    got = subprocess.run(
        ["node", str(harness), str(STATIC / "app.js"), str(f), str(f), str(STATIC / "season.js")],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    out = json.loads(got.stdout)
    assert out["problems"] == [] and out["marks"] == []
    page = out["pages"]["results"]
    assert page.count('<details class="panel res') == 4
    assert page.count("How to read this") == 1 and page.count("<li><b>A ") == 3
    assert "The engine's own update" in page and page.count("res-engine") == 2
    assert "not written yet" in page and "in play now" in page
    assert page.count('data-screen="') == 2  # each screen's card links to the Screen tab
    assert "&lt;x-mark&gt;" in page  # the record's values were drawn, escaped
    assert page.count("Where it stands") == 1 and html.escape(md.STANDS_LABEL) in page
    assert page.count("<h2>&lt;x-mark&gt;") == 4  # each card's title in plain words, escaped
    assert "Search done; the test is next." not in page and "Searching: 1 of 2" in page
    # The Knobs tab's line at its top.
    assert out["pages"]["knobs"].startswith('<p class="caution">' + html.escape(md.KNOBS_LINE))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_bare_address_opens_the_results_tab_and_no_run_says_so(tmp_path):
    m = json.loads(json.dumps(built(), default=str))
    f = tmp_path / "m.json"
    f.write_text(json.dumps(m))
    probe = tmp_path / "probe.js"
    # The harness's first draw is at a bare address: the tab it opens is the first.
    probe.write_text(
        Path(__file__)
        .with_name("lab_page_harness.js")
        .read_text()
        .replace(
            "  const pages = [",
            '  out.first = get("page").html; out.nav = get("nav").html;\n  const pages = [',
        )
    )
    got = subprocess.run(
        ["node", str(probe), str(STATIC / "app.js"), str(f), str(f), str(STATIC / "season.js")],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    out = json.loads(got.stdout)
    assert out["problems"] == []
    assert out["nav"].startswith('<a href="#results" class="on">Results</a>')
    assert "No screen or tune is recorded yet." in out["first"]
    assert "Where it stands" not in out["first"]


def test_lab_check_has_a_results_line():
    m = md.build(
        [made_screen(), on_version(made_screen("s-old"), 21)],
        [tune("t-1", ONE_WIN)],
        [],
        [],
        md.notes_of({"engine": ENGINE[3:]}),
        hold_out=2025,
        confirmation=2026,
        generated=GENERATED | {"at": "2026-01-04T00:00:00+00:00", "code_sha": None},
    )
    (line,) = [x for x in sv.check_lines(m) if x.startswith("results:")]
    assert line == "results: 3 card(s) (2 screen, 1 tune), 2 folded shut, 0 with the lead's reading"
