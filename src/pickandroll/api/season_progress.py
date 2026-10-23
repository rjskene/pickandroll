"""The Progress view's payload (#129; docs/AUTOPILOT.md section 6): the hill-climb over time,
read-only. From every league's scorecard (#126) it builds one row a week per league and the
public leagues pooled, each with its running sums; every move with its projected and realized
value; the knob file's changes on their weeks with each one's A/B halves; the Monday notes;
and the sentences written from the numbers.

The knob file (``data/autopilot/knobs.json``) and the notes (``data/autopilot/notes/<monday>.md``)
are written by the master, by hand until the hill-climb step of phase 3 does; this module only
reads them, and what it cannot read is listed in ``problems``.

A move's values are in its league's scorer's units, fantasy points in a points league and the
z-sum of the categories in a categories league, so the moves are pooled by scoring, never
summed across the two; their realized share of the projection is what compares across them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from ..season import progress as pg
from ..season import scorecard as sc
from ..season.calendar import Week
from .season_scorecard import moves_summary

AUTOPILOT_DIR = "autopilot"
KNOBS_FILE = "knobs.json"
NOTES_DIR = "notes"


# --------------------------------------------------------------------------- the files
def autopilot_dir(data_dir: Path) -> Path:
    return data_dir / AUTOPILOT_DIR


def load_knobs(data_dir: Path) -> tuple[Any, list[str]]:
    """The knob file's JSON, None when there is none; a file that is not JSON is a problem."""
    path = autopilot_dir(data_dir) / KNOBS_FILE
    try:
        return json.loads(path.read_text()), []
    except FileNotFoundError:
        return None, []
    except ValueError as exc:
        return None, [f"{KNOBS_FILE} is not JSON: {exc}"]


def load_notes(data_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The Monday notes, oldest first, each read by ``season.progress.note``; a file not named
    for a date is a problem."""
    folder = autopilot_dir(data_dir) / NOTES_DIR
    notes, problems = [], []
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        try:
            monday = date.fromisoformat(path.stem).isoformat()
        except ValueError:
            problems.append(f"notes/{path.name} is not named for a date")
            continue
        note, found = pg.note(path.read_text(), monday)
        notes.append(note)
        problems += found
    return notes, problems


# --------------------------------------------------------------------------- the series
def _won(card: Mapping[str, Any]) -> float | None:
    return (card.get("actual") or {}).get("won")


def week_row(card: Mapping[str, Any]) -> dict[str, Any]:
    """A league's week: the odds of winning the matchup against the result, the categories
    expected against won, the Brier score, the standing after it, and its moves (how many, by
    group, their value projected and realized on the week, and the scored ones compared on the
    horizon each was recommended for once it is over, ``compared``, #143), and the games lost
    to the lineup (#149) with the days read, None when no day was."""
    proj, act = card.get("projected"), card.get("actual")
    won = _won(card)
    expected = proj["matchup"] if proj and won is not None else None
    summary = moves_summary(card["moves"])
    standing = card.get("standing") or {}
    lineup = card.get("lineup") or {}
    return {
        "week": card["week"],
        "start": card["start"],
        "end": card["end"],
        "scoring": card.get("scoring"),
        "expected": expected,
        "won": won,
        "outcome": (act or {}).get("result", {}).get("outcome"),
        "expected_categories": proj["expected"] if proj else None,
        "categories": (act or {}).get("categories"),
        "brier": round((expected - won) ** 2, 4) if expected is not None else None,
        "rank": standing.get("rank"),
        "teams": standing.get("teams"),
        "record": standing.get("record"),
        "moves": {
            "made": summary["made"],
            **{g: summary[g] for g in ("scored", "realized_only", "unscored")},
            "projected": summary["projected_value"].get("week"),
            "realized": summary["realized_value"].get("week"),
            "compared": summary["compared"],
            "paid": sum(m.get("bid") or 0 for m in card["moves"]),
        },
        "lineup_lost": lineup.get("lost") if lineup.get("days_read") else None,
        "lineup_days_read": lineup.get("days_read") or 0,
        "lineup_days": lineup.get("days") or 0,
    }


def _sum(rows: Iterable[Mapping[str, Any]], key: str) -> float:
    return round(sum(r[key] for r in rows), 4)


def _lineup(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The games lost to the lineup over some week rows, summed over the weeks that read a day
    (None when none did), and the days read and the days over all of them."""
    counted = [r["lineup_lost"] for r in rows if r["lineup_lost"] is not None]
    return {
        "lost": sum(counted) if counted else None,
        "days_read": sum(r["lineup_days_read"] for r in rows),
        "days": sum(r["lineup_days"] for r in rows),
    }


def _running(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The sums of some week rows: wins and the matchup odds over the projected weeks, every
    win, the categories expected and won over the weeks with both, and the games lost to the
    lineup (:func:`_lineup`)."""
    projected = [r for r in rows if r["expected"] is not None]
    cats = [r for r in rows if r["expected_categories"] is not None and r["categories"] is not None]
    return {
        "weeks": len(projected),
        "expected": _sum(projected, "expected"),
        "won": _sum(projected, "won"),
        "won_all": _sum([r for r in rows if r["won"] is not None], "won"),
        "expected_categories": _sum(cats, "expected_categories") if cats else None,
        "categories": _sum(cats, "categories") if cats else None,
        "lineup": _lineup(rows),
    }


def _moves_to(cards: Sequence[Mapping[str, Any]], week: int) -> dict[str, Any]:
    rows = [m for c in cards if c["week"] <= week for m in c["moves"]]
    s = moves_summary(rows)
    return {k: s[k] for k in ("made", "realized_value", "compared")}


def league_series(cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """A league's weeks in order, each with the running sums to it (``cum``): the wins and
    categories as :func:`_running` sums them, and its moves to it (how many, the realized value
    on each horizon, and the scored moves compared)."""
    rows = [week_row(c) for c in cards]
    return [
        {**r, "cum": {**_running(rows[: i + 1]), "moves": _moves_to(cards, r["week"])}}
        for i, r in enumerate(rows)
    ]


def _by_scoring(cards: Iterable[Mapping[str, Any]], week: int | None = None) -> dict[str, Any]:
    """The scored moves compared over ``cards`` (to ``week``) by the scoring of their league,
    and the season check's counts (``season_costly``, #144)."""
    rows: dict[str, list[Mapping[str, Any]]] = {}
    for c in cards:
        if week is None or c["week"] <= week:
            rows.setdefault(c.get("scoring") or "categories", []).extend(c["moves"])
    out = {}
    for scoring, ms in rows.items():
        s = moves_summary(ms)
        out[scoring] = {
            "made": s["made"],
            "realized": s["realized_value"].get("week"),
            "compared": s["compared"],
            "season_costly": s["season_costly"],
        }
    return out


def pooled_series(
    cards: Mapping[str, Sequence[Mapping[str, Any]]],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    weeks: Sequence[int],
) -> list[dict[str, Any]]:
    """The public leagues pooled by week: the leagues recorded and projected, the odds of
    winning against the wins, the categories, the Brier score and the category odds' buckets
    of the week, the record, and the moves by scoring; then the same summed to the week."""
    out = []
    for w in weeks:
        this = [r for lg in rows for r in rows[lg] if r["week"] == w]
        if not this:
            continue
        upto = [r for lg in rows for r in rows[lg] if r["week"] <= w]
        week_cards = [c for lg in cards for c in cards[lg] if c["week"] == w]
        cal = sc.calibration(week_cards)
        outcomes = [r["outcome"] for r in this if r["outcome"]]
        out.append(
            {
                "week": w,
                "leagues": len(this),
                **_running(this),
                "brier": cal["brier"],
                "buckets": cal["buckets"],
                "record": "-".join(str(outcomes.count(x)) for x in "WLT"),
                "moves": _by_scoring(week_cards),
                "cum": {
                    **_running(upto),
                    "moves": _by_scoring((c for lg in cards for c in cards[lg]), w),
                },
            }
        )
    return out


def move_list(payloads: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every move of every league's recorded weeks, oldest first, each with its league, its
    week, its scoring and its players' names."""
    out = []
    for p in payloads:
        names = p.get("players") or {}
        for c in p.get("weeks") or []:
            for m in c["moves"]:
                out.append(
                    {
                        "league": p["league"],
                        "public": p["public"],
                        "week": c["week"],
                        "scoring": c.get("scoring"),
                        **m,
                        "names": {
                            k: names.get(str(m[k])) if m.get(k) is not None else None
                            for k in ("add", "drop")
                        },
                    }
                )
    return sorted(out, key=lambda m: (m.get("at") or m.get("day") or "", m["league"]))


def _calendar(weeks: Sequence[Week], cards: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The season's weeks: the calendar's, else the recorded weeks'."""
    if weeks:
        return [
            {"week": w.number, "start": w.start.isoformat(), "end": w.end.isoformat()}
            for w in weeks
        ]
    seen = {c["week"]: {"week": c["week"], "start": c["start"], "end": c["end"]} for c in cards}
    return [seen[k] for k in sorted(seen)]


# --------------------------------------------------------------------------- the payload
def payload(
    payloads: Sequence[Mapping[str, Any]],
    knobs_raw: Any,
    notes: Sequence[Mapping[str, Any]],
    today: date,
    calendar: Sequence[Week] = (),
    problems: Sequence[str] = (),
    skipped: Sequence[Mapping[str, str]] = (),
    system: str = "bbm",
) -> dict[str, Any]:
    """The Progress view: the season's weeks to this one, each league's week rows (the private
    league among them, ``public`` false, and never pooled), the public leagues pooled by week
    and their calibration over the season, every move, the knob file with its changes placed on
    their weeks and their A/B halves, the Monday notes under their weeks with the newest one's
    action items, the sentences, what was read and the problems met reading it."""
    recorded = [p for p in payloads if p.get("status") == "recorded"]
    all_cards = [c for p in recorded for c in p["weeks"]]
    weeks = _calendar(calendar, all_cards)
    today_s = today.isoformat()
    current = pg.week_at(weeks, today_s)
    last = max((c["week"] for c in all_cards), default=None)
    shown_to = max(x for x in (current, last, 0) if x is not None)
    weeks = [w for w in weeks if w["week"] <= shown_to]

    cards = {p["league"]: p["weeks"] for p in recorded}
    rows = {lg: league_series(cs) for lg, cs in cards.items()}
    public = [p["league"] for p in recorded if p["public"]]
    pub_cards = {lg: cards[lg] for lg in public}
    pub_rows = {lg: rows[lg] for lg in public}
    pooled = pooled_series(pub_cards, pub_rows, [w["week"] for w in weeks])
    calibration = sc.calibration(c for lg in public for c in cards[lg])

    knobs, knob_problems = pg.knob_file(knobs_raw)
    for change in knobs["changes"]:
        change["week"] = pg.week_at(weeks, change["monday"]) if weeks else None
        change["ab"] = pg.ab(change, change["week"], pub_rows, last)
    shown_notes = []
    for n in notes:
        week = pg.week_at(weeks, n["monday"])
        shown_notes.append(
            {**n, "week": week, "scored_week": week - 1 if week and week > 1 else None}
        )
    newest = shown_notes[-1] if shown_notes else None

    leagues = [
        {
            "league": p["league"],
            "public": p["public"],
            "status": p.get("status"),
            "scoring": (p["weeks"][-1].get("scoring") if p.get("weeks") else None),
            "weeks": rows.get(p["league"], []),
            "to_date": p.get("to_date"),
        }
        for p in payloads
    ]
    to_date = pooled[-1]["cum"] if pooled else None
    league_sums = [
        {"league": lg["league"], **lg["weeks"][-1]["cum"]} for lg in leagues if lg["weeks"]
    ]
    moves_pooled = {
        s: m["compared"] for s, m in (to_date or {}).get("moves", {}).items() if m["compared"]
    }
    season_pooled = {
        s: m["season_costly"]
        for s, m in (to_date or {}).get("moves", {}).items()
        if m.get("season_costly")
    }
    say = pg.sentences(
        to_date, league_sums, calibration, moves_pooled, knobs["changes"], season_pooled
    )
    kinds = moves_summary(m for c in all_cards for m in c["moves"])
    return {
        "system": system,
        "today": today_s,
        "week": current,
        "last_recorded": last,
        "weeks": weeks,
        "leagues": leagues,
        "pooled": {"weeks": pooled, "to_date": to_date, "calibration": calibration},
        "moves": move_list(recorded),
        "knobs": knobs,
        "notes": shown_notes,
        "action_items": {"monday": newest["monday"], "items": newest["actions"]}
        if newest
        else None,
        "sentences": say,
        "sources": {
            "leagues": len(payloads),
            "recorded": len(recorded),
            "public": len(public),
            "moves": {
                k: kinds[k]
                for k in (
                    "made",
                    "as_recommended",
                    "differently",
                    "not_recommended",
                    "no_entry",
                    "near",
                )
            },
            "knob_file": knobs_raw is not None,
            "notes": len(notes),
        },
        "problems": [*problems, *knob_problems],
        "skipped": list(skipped),
    }
