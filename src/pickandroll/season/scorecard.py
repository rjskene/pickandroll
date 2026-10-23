"""The Monday scorecard (#126, docs/ADD_DROP.md "Scorecard"): a recorded week of a league against
what the decision log projected for it, my moves that week, the season to date, and the odds'
calibration pooled across leagues.

A week's projection is the decision log's last entry (#125) of the system scored whose first day
is the week's first: a solve that saw the whole week ahead, before its first game (once a day's
games begin, a solve's first day is the next). With no system named, the system scored is the one
in force when the week began (#152): the knob file's system for the league that the week's first
such entry recorded, so a change of system made on the week's Monday leaves the week projected on
the old one for both halves, whatever is solved after it. Its week block before any move gives
each category's finals and odds, the expected categories and the odds of winning the matchup. A week
without one is unprojected: shown, but in no sum. The result is the weekly record's (#97): my
categories won, lost and tied (a points league's points), and each category's totals, a
percentage from its makes and attempts to Yahoo's three decimals, the lower turnovers winning.
Pure: the records and the log are read by ``api.season_scorecard``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from .calendar import Week
from .progress import DEFAULTS

#: Percentages from their makes and attempts.
PCT = {"fg_pct": ("fgm", "fga"), "ft_pct": ("ftm", "fta")}
#: The categories the lower total wins.
LOWER = frozenset({"tov"})
#: A points league's one category (``weekly.FPTS``).
FPTS = "fpts"
#: The category odds' calibration buckets: five of 20 points each.
BUCKETS = 5
#: A week's outcome as a win counts it: a tie is half.
OUTCOME = {"W": 1.0, "T": 0.5, "L": 0.0}
#: The system in force for an entry logged before entries kept it: the knob file's default.
IN_FORCE = DEFAULTS["system"]


def _round(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(float(x), digits)


def _before(entry: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    sets = (entry or {}).get("sets") or []
    return (sets[0].get("week") or {}).get("before") if sets else None


def file_system(entry: Mapping[str, Any]) -> str:
    """The system the knob file had in force for the entry's league when it was logged
    (``knobs.file_system``, #152); :data:`IN_FORCE` for an entry logged before entries kept it."""
    return (entry.get("knobs") or {}).get("file_system") or IN_FORCE


def on_system(entry: Mapping[str, Any], system: str | None) -> bool:
    """Whether ``entry`` was solved on ``system``; with None, on the system the knob file had in
    force for its league when it was logged."""
    return (entry.get("system") or {}).get("key") == (system or file_system(entry))


def projection(
    entries: Iterable[Mapping[str, Any]], week: Week, system: str | None
) -> Mapping[str, Any] | None:
    """The entry that projects ``week``: the last one on ``system`` whose first day is the week's
    first and that holds a week block (a week without a named opponent has none). With None, on
    the system in force when the week began: the one its first such entry recorded, solved on
    the system the file then had in force."""
    start = week.start.isoformat()
    opening = sorted((e for e in entries if e.get("first_day") == start), key=lambda e: e["at"])
    if not opening:
        return None
    if system is None:
        began = file_system(opening[0])
        found = [e for e in opening if file_system(e) == began and on_system(e, None)]
    else:
        found = [e for e in opening if on_system(e, system)]
    return max((e for e in found if _before(e) is not None), key=lambda e: e["at"], default=None)


def total(totals: Mapping[str, Any], cat: str) -> float | None:
    """A team's total in ``cat``; a percentage from its makes and attempts where the record has
    them, to the three decimals Yahoo compares."""
    if cat in PCT:
        made, tried = (totals.get(k) for k in PCT[cat])
        if made is not None and tried:
            return round(float(made) / float(tried), 3)
    value = totals.get(cat)
    return None if value is None else float(value)


def won(cat: str, mine: float | None, theirs: float | None) -> float | None:
    """1 when I won ``cat``, 0 when I lost it, 0.5 for a tie; None when a total is missing."""
    if mine is None or theirs is None:
        return None
    if mine == theirs:
        return 0.5
    return float(mine < theirs if cat in LOWER else mine > theirs)


def result(record: Mapping[str, Any], me: int) -> dict[str, Any] | None:
    """My week in ``record``: the opponent, Yahoo's result, the outcome as a win counts it, the
    categories won (a tie half; None in a points league) and each category's totals and winner.
    None when the record has no result for me."""
    teams = record.get("teams") or {}
    mine = teams.get(str(me))
    if not mine or not mine.get("result"):
        return None
    res = mine["result"]
    theirs = teams.get(str(mine["opponent"])) or {}
    points = record.get("scoring") == "points"
    cats: dict[str, dict[str, Any]] = {}
    if points:
        cats[FPTS] = {
            "mine": res.get("points"),
            "theirs": res.get("against"),
            "won": OUTCOME[res["outcome"]],
        }
    else:
        for cat in record.get("cats") or []:
            a = total(mine.get("totals") or {}, cat)
            b = total(theirs.get("totals") or {}, cat)
            cats[cat] = {"mine": a, "theirs": b, "won": won(cat, a, b)}
    return {
        "opponent": mine["opponent"],
        "result": dict(res),
        "won": OUTCOME[res["outcome"]],
        "categories": None if points else res["won"] + 0.5 * res["tied"],
        "cats": cats,
    }


def standing(record: Mapping[str, Any], me: int) -> dict[str, Any] | None:
    """My place and record in the standings as of the week's end."""
    teams = (record.get("standings") or {}).get("teams") or []
    row = next((t for t in teams if t.get("team_id") == me), None)
    if row is None:
        return None
    wlt = (row.get("wins"), row.get("losses"), row.get("ties"))
    return {
        "rank": row.get("rank"),
        "record": None if None in wlt else "-".join(str(x) for x in wlt),
        "teams": len(teams),
    }


def week_of(record: Mapping[str, Any]) -> Week:
    return Week(
        int(record["week"]), date.fromisoformat(record["start"]), date.fromisoformat(record["end"])
    )


def week_card(
    record: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    me: int,
    system: str | None,
    moves: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """A league's week: its projection (None when unprojected), its result (None when the
    record has none for me), each category projected against actual, my standing after it, and
    ``moves``, my moves made that week as the decision log matched them, and ``lineup``, my
    games lost to the lineup as the record counted them (#149; None when not counted)."""
    week = week_of(record)
    entry = projection(entries, week, system)
    before = _before(entry)
    actual = result(record, me)
    projected = None
    if entry is not None and before is not None:
        projected = {
            "entry": entry["id"],
            "at": entry["at"],
            "source": entry.get("source"),
            "expected": _round(before.get("expected")),
            "matchup": _round(before.get("matchup")),
        }
    odds = (before or {}).get("cats") or {}
    got = (actual or {}).get("cats") or {}
    cats = [
        {
            "cat": cat,
            "p_win": _round((odds.get(cat) or {}).get("p_win")),
            "projected": {k: _round((odds.get(cat) or {}).get(k)) for k in ("mine", "theirs")}
            if cat in odds
            else None,
            "actual": {k: got[cat][k] for k in ("mine", "theirs")} if cat in got else None,
            "won": (got.get(cat) or {}).get("won"),
        }
        for cat in list(got) + [c for c in odds if c not in got]
    ]
    return {
        "week": week.number,
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "scoring": record.get("scoring"),
        "projected": projected,
        "actual": None if actual is None else {k: v for k, v in actual.items() if k != "cats"},
        "cats": cats,
        "standing": standing(record, me),
        "moves": [dict(m) for m in moves],
        "lineup": dict(record["lineup"]) if record.get("lineup") else None,
    }


def scored(cards: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The weeks with both a projection and a result."""
    return [c for c in cards if c.get("projected") and c.get("actual")]


def calibration(cards: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The odds against the results over ``cards`` (weeks of one league or many), the projected
    ones with a result: the matchup odds' Brier score (a tie half a win), and the category odds'
    hit rate in five buckets of 20 points, each with its count, mean odds and share won. A
    points league's one category is its matchup, scored by the Brier score only."""
    weeks = scored(cards)
    brier = [(c["projected"]["matchup"] - c["actual"]["won"]) ** 2 for c in weeks]
    rows: list[list[tuple[float, float]]] = [[] for _ in range(BUCKETS)]
    for c in weeks:
        if c.get("scoring") == "points":
            continue
        for row in c["cats"]:
            if row["p_win"] is None or row["won"] is None:
                continue
            i = min(int(row["p_win"] * BUCKETS), BUCKETS - 1)
            rows[i].append((row["p_win"], row["won"]))
    return {
        "weeks": len(weeks),
        "brier": _round(sum(brier) / len(brier)) if brier else None,
        "buckets": [
            {
                "from": i / BUCKETS,
                "to": (i + 1) / BUCKETS,
                "count": len(r),
                "odds": _round(sum(p for p, _ in r) / len(r)) if r else None,
                "won": _round(sum(w for _, w in r) / len(r)) if r else None,
            }
            for i, r in enumerate(rows)
        ],
    }


def to_date(cards: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The season so far from a league's weeks in order: the record from the results, and over
    the projected weeks the wins and categories expected against those won; the standing after
    the last week."""
    played = [c for c in cards if c.get("actual")]
    weeks = scored(cards)
    cats = [c for c in weeks if c["actual"]["categories"] is not None]
    outcome = [c["actual"]["result"]["outcome"] for c in played]
    return {
        "weeks": len(played),
        "projected": len(weeks),
        "record": "-".join(str(outcome.count(x)) for x in "WLT"),
        "expected_wins": _round(sum(c["projected"]["matchup"] for c in weeks)),
        "wins": sum(c["actual"]["won"] for c in weeks),
        "expected_categories": _round(sum(c["projected"]["expected"] for c in cats))
        if cats
        else None,
        "categories": sum(c["actual"]["categories"] for c in cats) if cats else None,
        "standing": cards[-1]["standing"] if cards else None,
    }
