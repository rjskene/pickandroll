"""SEASON SIM (#172, PR capabilities): the log of what the simulator can do.

The rule that makes it stick: the code's versions are the last the log holds, so a PR that
steps ``REPLAY_VERSION``, ``SCREEN_VERSION`` or ``TUNE_VERSION`` cannot merge without its mark.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from pickandroll.sim import capabilities as cap
from pickandroll.sim import cli
from pickandroll.sim import screen as sc
from pickandroll.sim import tune as tn


def test_the_code_s_versions_are_the_last_the_log_holds():
    assert cap.last("replay_version") == cli.REPLAY_VERSION
    assert cap.last("screen_version") == sc.SCREEN_VERSION
    assert cap.last("tune_version") == tn.TUNE_VERSION


def test_the_log_is_well_made():
    assert cap.problems() == []
    assert [m.date for m in cap.LOG] == sorted(m.date for m in cap.LOG)
    assert cap.LOG[0].replay_version == 1


def test_a_stepped_version_without_its_mark_fails():
    # the code stepped the replay's version and no mark was written: the log's last is behind
    without = tuple(m for m in cap.LOG if m.replay_version != cli.REPLAY_VERSION)
    assert cap.last("replay_version", without) == cli.REPLAY_VERSION - 1
    assert cap.last("replay_version", without) != cli.REPLAY_VERSION
    # a version skipped, or held twice, is said by version
    gap = tuple(m for m in cap.LOG if m.replay_version != 3)
    assert cap.problems(gap) == ["replay_version 3: 0 marks hold it, one should"]
    twice = (*cap.LOG, replace(cap.LOG[-1], id="again", screen_version=1))
    assert "screen_version 1: 2 marks hold it, one should" in cap.problems(twice)


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"kind": "rules"}, "'rules' is not one of world, seat, engine, measure"),
        ({"words": "it doubled the bids"}, ""),
        ({"words": "two of them"}, ""),
        ({"words": "a figure, 3 of them"}, "its words holds a number"),
        ({"title": "Version 22"}, "its title holds a number"),
        ({"words": "x" * (cap.WORDS_MAX + 1)}, "its words are longer than two lines"),
        ({"words": "one\ntwo"}, "its words is not one plain line"),
        ({"takes_in": ("485",)}, "'485' is not an issue like #424"),
        ({"date": "23 Nov"}, "'23 Nov' is not a date"),
        ({"date": "2026-10-01"}, "dated before the mark above it"),
        ({"id": "replay-1"}, "its id is not unique"),
    ],
)
def test_a_badly_made_mark_is_said_by_name(change, words):
    log = (*cap.LOG, replace(cap.LOG[-1], **({"id": "new"} | change)))
    got = cap.problems(log)
    if words:
        assert any(words in g for g in got), got
    else:
        assert got == []


def test_the_capability_a_run_was_played_on():
    assert cap.at(cli.REPLAY_VERSION).id == f"replay-{cli.REPLAY_VERSION}"
    assert (
        cap.at(16).id == "replay-16" and cap.at(16).title == "The season guard and the week's stake"
    )
    # a version the log has no mark of reads the last mark below it
    assert cap.at(cli.REPLAY_VERSION + 5).replay_version == cli.REPLAY_VERSION
    for nothing in (None, 0, True, "21", 2.5):
        assert cap.at(nothing) is None
    assert cap.current().replay_version == cli.REPLAY_VERSION
    assert cap.latest() is cap.LOG[-1]
    # a mark that took a live change in closes it
    assert cap.taken_in("#424").id == "replay-20"
    assert cap.taken_in("#485") is None
    p = cap.at(20).payload()
    assert p["takes_in"] == ["#424"] and p["screen_version"] == 6 and p["kind"] == "engine"
