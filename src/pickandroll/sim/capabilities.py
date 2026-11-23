"""SEASON SIM (#172, PR capabilities): the log of what the simulator can do.

The user's ask (2026-11-23): "we need to mark when there have been capability updates to the
sims so we can incorporated in analysis of changes in effectiveness". A change in a result
must be readable as "a knob did this" or "the simulator changed", never left to guess. So each
change to what the simulator can do (its world, what the seat can do, a live rule it mirrors,
how it counts) is a :class:`Mark` here, oldest first, and every run says which mark it was
played on (the lab reads this log).

- One mark for each step of ``REPLAY_VERSION``, ``SCREEN_VERSION`` and ``TUNE_VERSION``, from
  the first: a mark names the versions it is the first to have. A test fails when a version is
  not the last one the log holds, so a PR that steps a version cannot merge without its mark.
- A change that added a capability, or moved what a run plays, without stepping a version (a
  new command, a new record key, a fix that changed what a world does) has a mark too, with no
  version: it is dated, and a run's version cannot place it.
- ``takes_in`` names the live engine's changes a mark brought in, by issue: it closes those
  changes in the lead's notes (their ``engine`` section).
- One zone for days: Central. A mark's ``date`` is the Central day its PR merged (a merge late
  in the evening is the next day in UTC), the notes date live's changes the same way, and the
  lab compares them with the Central day a run started (:func:`central_day`). The US rule is
  written out here, not read from a zone database, so the module stays free of I/O.

Words only: no figure of a real run, and no number in a title or words (a version, an issue
and a date are fields). Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

#: A mark's kinds, with their words.
KINDS: Mapping[str, str] = {
    "world": "the simulated league: its rules, the rivals, the draft, waivers",
    "seat": "what the seat's policy can do, a knob given a reader",
    "engine": "a live rule the simulator mirrors, taken in",
    "measure": "how outcomes are counted or recorded",
}
#: The versions a mark can be the first to have, as the records name them.
VERSIONS = ("replay_version", "screen_version", "tune_version")
#: A live issue as the log and the notes write it.
ISSUE = re.compile(r"#[1-9]\d*")
#: The longest a mark's words may be: two lines of the page, plain.
WORDS_MAX = 220


@dataclass(frozen=True)
class Mark:
    """One change to what the simulator can do: ``date`` the day it landed on main, ``pr`` its
    pull request, ``kind`` one of :data:`KINDS`, the versions it is the first to have (none for
    a change that stepped none), and ``takes_in`` the live issues it brought in."""

    id: str
    date: str
    pr: int
    kind: str
    title: str
    words: str
    replay_version: int | None = None
    screen_version: int | None = None
    tune_version: int | None = None
    takes_in: tuple[str, ...] = ()

    def versions(self) -> dict[str, int]:
        return {k: v for k in VERSIONS if (v := getattr(self, k)) is not None}

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "date": self.date,
            "pr": self.pr,
            "kind": self.kind,
            "title": self.title,
            "words": self.words,
            **{k: getattr(self, k) for k in VERSIONS},
            "takes_in": list(self.takes_in),
        }


#: The log, oldest first (by the day it landed, then by pull request).
LOG: tuple[Mark, ...] = (
    Mark(
        "replay-1", "2026-10-24", 179, "world", "The replay",
        "Arms played in the seat of a made-up league on a recorded season's lines, the rivals "
        "by their habits; a seat of this version saw each season's rates.",
        replay_version=1,
    ),
    Mark(
        "pr-210", "2026-10-26", 210, "world", "An add charged to its week",
        "A free agent's add is charged to the week it is made. No version stepped.",
    ),
    Mark(
        "pr-236", "2026-10-29", 236, "engine", "Held-slot moves as live lands them",
        "The executor lands held-slot moves and churns as the live engine does, and brings a "
        "cleared held player back. No version stepped.",
    ),
    Mark(
        "replay-2", "2026-11-13", 377, "seat", "The seat knows only the past",
        "Each seat believes only the games played so far; before it, the seats saw each "
        "season's rates.",
        replay_version=2,
    ),
    Mark(
        "pr-378", "2026-11-13", 378, "world", "A held move needs its slot",
        "A held move lands only if the slot still accepts the player. No version stepped.",
    ),
    Mark(
        "pr-379", "2026-11-13", 379, "measure", "The daily audit and the counts",
        "The world audits every day, and each run records the counts of what happened.",
    ),
    Mark(
        "pr-380", "2026-11-13", 380, "seat", "A season term in the score",
        "The seat's score can weigh the games after the week beside the week's, a knob off by "
        "default; a table says what each knob reads.",
    ),
    Mark(
        "replay-3", "2026-11-14", 382, "seat", "Forecasters",
        "Each seat believes through a named forecaster, and a run's results are kept by the "
        "forecaster's label.",
        replay_version=3,
    ),
    Mark(
        "replay-4", "2026-11-15", 389, "measure", "Several seasons, paired",
        "A replay pairs two arms over several seasons, with a verdict by forecaster and "
        "season; what is one season's is kept by season.",
        replay_version=4,
    ),
    Mark(
        "replay-5", "2026-11-15", 394, "measure", "The standalone cut",
        "The record names nothing of a live league or a drawn world; its figures are as they "
        "were.",
        replay_version=5,
    ),
    Mark(
        "replay-6", "2026-11-16", 399, "world", "The draft market",
        "The rivals draft on average draft position, and each arm's seat on its own "
        "forecaster.",
        replay_version=6,
    ),
    Mark(
        "pr-402", "2026-11-16", 402, "measure", "Gate five's record",
        "Gate five records what it compared, and the no-peek check runs under a draft table.",
    ),
    Mark(
        "replay-7", "2026-11-16", 407, "world", "League shapes",
        "A grid of league shapes, cycled across the paths.",
        replay_version=7,
    ),
    Mark(
        "replay-8", "2026-11-17", 410, "world", "League rules",
        "Points leagues and held slots in a replay's league.",
        replay_version=8,
    ),
    Mark(
        "replay-9", "2026-11-17", 414, "world", "Waivers",
        "A dropped player waits before he can be added again, and claims are settled by "
        "priority.",
        replay_version=9,
    ),
    Mark(
        "replay-10", "2026-11-17", 418, "world", "FAAB",
        "Waivers by a budget and sealed bids.",
        replay_version=10,
    ),
    Mark(
        "replay-11", "2026-11-18", 420, "measure", "The head-to-head format",
        "A league counts one win per matchup, or every category, as a rule of the run.",
        replay_version=11,
    ),
    Mark(
        "replay-12", "2026-11-18", 423, "world", "Continuous waivers",
        "Every unowned player is on waivers at all times, so every add is a claim.",
        replay_version=12,
    ),
    Mark(
        "replay-13", "2026-11-18", 426, "world", "The rivals' adds and bids",
        "The rivals add and bid as a rule of the run, fitted on the public leagues' winning "
        "bids; off by default.",
        replay_version=13,
    ),
    Mark(
        "screen-1", "2026-11-19", 429, "measure", "The screen",
        "Each lever nudged once against a baseline arm, and what moved.",
        screen_version=1,
    ),
    Mark(
        "replay-14", "2026-11-19", 432, "seat", "The seat drafts from the market's board",
        "Under a draft table the arm's seat drafts as a rival does, from the market's board.",
        replay_version=14,
    ),
    Mark(
        "pr-444", "2026-11-19", 444, "measure", "Gate five on the kept gain",
        "Gate five passes on the share of the exact tier's gain the fast tier keeps.",
    ),
    Mark(
        "replay-15", "2026-11-19", 445, "seat", "The stash threshold",
        "An arm's stash threshold is read by the engine's searches; the screen gains its "
        "rows.",
        replay_version=15,
        screen_version=2,
    ),
    Mark(
        "replay-16", "2026-11-20", 447, "seat", "The season guard and the week's stake",
        "The season guard is an arm's choice, and the season term can read the week's stake; "
        "the screen gains their rows.",
        replay_version=16,
        screen_version=3,
    ),
    Mark(
        "replay-17", "2026-11-20", 448, "engine", "The queue's rule",
        "An exact arm can execute live's queue rule: the week plan in place of the set when "
        "it beats the set by the plan floor.",
        replay_version=17,
        screen_version=4,
        takes_in=("#221",),
    ),
    Mark(
        "replay-18", "2026-11-20", 449, "seat", "The bid policy",
        "Under FAAB an arm's seat bids by a family of rules whose default member is live's; "
        "the screen gains its levers.",
        replay_version=18,
        screen_version=5,
    ),
    Mark(
        "replay-19", "2026-11-20", 452, "world", "The bracket's rounds",
        "In a bracket week a seat's problem reads its round's opponent, seeded from the "
        "season so far.",
        replay_version=19,
    ),
    Mark(
        "replay-20", "2026-11-20", 454, "engine", "The union pool",
        "An arm may search the engine's union pool while its guard blocks, as live does; the "
        "screen gains its row.",
        replay_version=20,
        screen_version=6,
        takes_in=("#424",),
    ),
    Mark(
        "tune-1", "2026-11-20", 455, "measure", "The tune",
        "A search over a screen's survivors, lever by lever, and one confirmation on a season "
        "no search has seen.",
        tune_version=1,
    ),
    Mark(
        "replay-21", "2026-11-20", 456, "world", "Same-day adds",
        "A league whose free agents' adds play the same day, as a rule of the run; with the "
        "rule off, the figures are the previous version's.",
        replay_version=21,
    ),
    Mark(
        "pr-490", "2026-11-23", 490, "measure", "The trace",
        "One path of one pair played again with a recorder, day by day; a pair's record keeps "
        "each path's outcomes.",
    ),
)  # fmt: skip


def last(key: str = "replay_version", log: Sequence[Mark] = LOG) -> int | None:
    """The highest ``key`` the log holds: the version the code must be at."""
    got = [getattr(m, key) for m in log if getattr(m, key) is not None]
    return max(got) if got else None


def at(replay_version: Any, log: Sequence[Mark] = LOG) -> Mark | None:
    """The capability a run of ``replay_version`` was played on: the last mark at or below it
    that steps the replay's version; None for a run that records no version."""
    if isinstance(replay_version, bool) or not isinstance(replay_version, int):
        return None
    got = [m for m in log if m.replay_version is not None and m.replay_version <= replay_version]
    return max(got, key=lambda m: m.replay_version or 0) if got else None


def taken_in(issue: str, log: Sequence[Mark] = LOG) -> Mark | None:
    """The mark that brought live issue ``issue`` in, the first to name it; None while none
    has."""
    return next((m for m in log if issue in m.takes_in), None)


def current(log: Sequence[Mark] = LOG) -> Mark | None:
    """The simulator's capability now: the mark of the replay's last version."""
    return at(last("replay_version", log), log)


def latest(log: Sequence[Mark] = LOG) -> Mark | None:
    """The last update of any kind: the log's last mark."""
    return log[-1] if log else None


def _sunday(year: int, month: int, nth: int) -> date:
    """The ``nth`` Sunday of ``month``."""
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (nth - 1))


def central_offset(t: datetime) -> timedelta:
    """Central time's offset from UTC at ``t`` (aware): the US rule since 2007, daylight time
    from two in the morning on March's second Sunday to two in the morning on November's
    first, five hours behind UTC then and six otherwise."""
    u = t.astimezone(UTC)
    start = datetime.combine(_sunday(u.year, 3, 2), datetime.min.time(), UTC) + timedelta(hours=8)
    end = datetime.combine(_sunday(u.year, 11, 1), datetime.min.time(), UTC) + timedelta(hours=7)
    return timedelta(hours=-5) if start <= u < end else timedelta(hours=-6)


def central_day(t: datetime) -> str:
    """The Central day (YYYY-MM-DD) of ``t`` (aware)."""
    return (t.astimezone(UTC) + central_offset(t)).date().isoformat()


def central_midnight(day: str) -> datetime | None:
    """The start of Central day ``day``, in UTC; None for a text that is not a date. A change
    of the clocks falls at two in the morning, so midnight is one of the two offsets."""
    try:
        d = date.fromisoformat(day)
    except (TypeError, ValueError):
        return None
    for hours in (5, 6):
        u = datetime.combine(d, datetime.min.time(), UTC) + timedelta(hours=hours)
        if central_offset(u) == timedelta(hours=-hours):
            return u
    return None  # never: one of the two holds


def problems(log: Sequence[Mark] = LOG) -> list[str]:
    """What is wrong with the log, by mark: ids unique, dates in order, a known kind, plain
    words of two lines at most with no number, issues written ``#N``, and each version from one
    to its last held by exactly one mark."""
    out: list[str] = []
    seen: set[str] = set()
    before = ""
    for m in log:
        where = f"mark {m.id!r}"
        if m.id in seen:
            out.append(f"{where}: its id is not unique")
        seen.add(m.id)
        try:
            date.fromisoformat(m.date)
        except ValueError:
            out.append(f"{where}: {m.date!r} is not a date (YYYY-MM-DD)")
        if m.date < before:
            out.append(f"{where}: dated before the mark above it")
        before = max(before, m.date)
        if m.kind not in KINDS:
            out.append(f"{where}: {m.kind!r} is not one of {', '.join(KINDS)}")
        for field in ("title", "words"):
            text = getattr(m, field)
            if not text.strip() or "\n" in text:
                out.append(f"{where}: its {field} is not one plain line")
            if re.search(r"\d", text):
                out.append(f"{where}: its {field} holds a number")
        if len(m.words) > WORDS_MAX:
            out.append(f"{where}: its words are longer than two lines")
        for issue in m.takes_in:
            if not ISSUE.fullmatch(issue):
                out.append(f"{where}: {issue!r} is not an issue like #424")
    for key in VERSIONS:
        held = [getattr(m, key) for m in log if getattr(m, key) is not None]
        top = max(held, default=0)
        for v in range(1, top + 1):
            n = held.count(v)
            if n != 1:
                out.append(f"{key} {v}: {n} marks hold it, one should")
    return out


__all__ = [
    "ISSUE",
    "KINDS",
    "LOG",
    "VERSIONS",
    "WORDS_MAX",
    "Mark",
    "at",
    "central_day",
    "central_midnight",
    "central_offset",
    "current",
    "last",
    "latest",
    "problems",
    "taken_in",
]
