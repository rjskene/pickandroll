"""The private league's suggestions pass the queue's own checks (#494, the user's ruling of
2026-11-23).

The private league is suggestions only: nothing is ever clicked there, and its moves reach the
user as a list (the pre-tip push, the landing row, the league page's moves view). Each move on
that list must pass the checks a public league's move passes before it is queued, in the same
code: :func:`season.autopilot.suggestions_of` runs :func:`season.autopilot.queue_of` on the
league's day with only the execution-only gates opened (the private stop, the moves mode and
STOP, the day's cap, the claims already open). So a move is judged on its horizon against the
plan floor (``stream.floor_of``: ``PLAN_FLOOR_ODDS`` in a one-win league), by the season guard,
the re-add rule, the drop the keep rule protects, the add reserve, a week plan's later and
waiting steps, and the adds each week has left. The scored floor is never applied: the private
league is never pooled.

:func:`checks` reads the day as the decision log would keep this solve
(``season_decisions.moves_entry``), so the list checked is the list the payload shows, and
rides on the solved payload as ``checks``: every surface reads that one record and they agree.
A public league's payload carries no ``checks``."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from ..season import Season
from ..season import autopilot as qa
from ..season import stream as st
from . import season_decisions, season_queue
from .season_moves import Built

CHECKED, FAILED = "checked", "failed"
#: The push's words when no move passes, and when the adds were not read (the master's ruling).
NONE_CLEAR = "no move clears the checks"
ADDS_NOT_READ = "adds not read today"


def checks(
    league: str,
    built: Built,
    payload: Mapping[str, Any],
    season: Season,
    flags: Mapping[int, str],
    today: date,
    at: datetime,
) -> dict[str, Any]:
    """The private league's moves of ``payload`` checked as the queue checks a public league's:
    the floor, the set checked (the week plan when the solve's queue takes one, else the three
    weeks' set), and each move with its ``reason`` (None when it passes) and, for a week plan's
    later step, the day it becomes today's (``on``)."""
    entry = season_decisions.moves_entry(built, payload, at)
    floor = qa.noise_floor([], st.floor_of(built.problem))
    day = season_queue.league_day(
        league,
        season.settings.scoring,
        entry,
        qa.SUGGESTIONS,
        season,
        built.rule,
        flags,
        today,
        cap=qa.UNCAPPED,
        left=season_queue.adds_left(entry.get("adds"), []),
    )
    entries = qa.suggestions_of(day, today, floor)
    plan = qa.week_plan(entry) is not None
    passes = any(e["reason"] is None for e in entries)
    unread = not passes and any(e["reason"] == qa.ADDS_UNREAD for e in entries)
    return {
        "status": CHECKED,
        "reason": None,
        "set": qa.WEEK_PLAN if plan else qa.QUEUE_SET,
        "horizon": qa.PLAN_JUDGED if plan else qa.JUDGED,
        "floor": floor.plan,
        "one_win": built.problem.one_win,
        # No move passes and the week's adds were not read: the push says so (the master's
        # ruling), not that no move clears; the other checks come first in the queue's order.
        "adds_unread": unread,
        "moves": [
            {
                "add": e["add"],
                "drop": e["drop"],
                "from": e["from"],
                "passes": e["reason"] is None,
                "reason": e["reason"],
                "on": e["from"] if e["reason"] == qa.LATER_STEP else None,
            }
            for e in entries
        ],
    }


def failed(reason: str) -> dict[str, Any]:
    """The checks when they could not be made: nothing is suggested, and the push says why."""
    return {
        "status": FAILED,
        "reason": reason,
        "set": None,
        "horizon": None,
        "floor": None,
        "one_win": None,
        "adds_unread": False,
        "moves": [],
    }
