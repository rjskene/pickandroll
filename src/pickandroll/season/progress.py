"""The Progress view's pure parts (#129; docs/AUTOPILOT.md section 6): the knob file and the
Monday notes as read, the A/B comparison of a knob change, and the sentences the view writes
from its numbers by rule.

Both files are hand-editable (the master writes the knob file by hand until the hill-climb step
of phase 3 does), so they are read leniently: whatever cannot be read is named in a list of
problems and left out, and never fails the page. Nothing here writes either file.

Pure: ``api.season_progress`` reads the files and builds the series these work on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

#: The knobs of docs/AUTOPILOT.md section 6, by the names the decision log records them under
#: (``api.season_decisions.knobs``), and no other.
KNOBS = (
    "system",
    "blend",
    "horizon_weight",
    "protection_floor",
    "plan_floor_cats",
    "plan_floor_points",
    "stash_threshold",
    "faab_sizing",
    "daily_cap",
)
VERDICTS = ("kept", "reverted")
SOURCES = ("master", "user")
#: The Monday note's sections, by their heading (lower case), and their keys.
SECTIONS = {
    "what is working": "working",
    "what is not": "not_working",
    "decision": "decision",
    "action items": "actions",
}
#: A change is judged on the weeks it ran, this many (docs/AUTOPILOT.md section 6).
JUDGED_WEEKS = 2

#: The sentences' thresholds: the pooled wins track their expectation within a game; a league
#: a game or more off its own is named; the moves track their projection when they realized
#: within 10% of it; an odds bucket with 30 categories or more is off by 5 points or more.
WINS_EVEN = 1.0
LEAGUE_GAP = 1.0
SHARE_BAND = (0.9, 1.1)
BUCKET_MIN = 30
BUCKET_GAP = 0.05

#: The units a league's moves are valued in, by its scoring.
UNITS = {"points": "fantasy points", "categories": "category value"}


# --------------------------------------------------------------------------- the knob file
def _day(x: Any) -> str | None:
    try:
        return date.fromisoformat(str(x)).isoformat()
    except ValueError:
        return None


def _known(where: str, raw: Any, problems: list[str]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        problems.append(f"{where} is not an object")
        return {}
    out = {}
    for k, v in raw.items():
        if k in KNOBS:
            out[k] = v
        else:
            problems.append(f"{where}: {k} is not a knob")
    return out


def _change(i: int, raw: Any, problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        problems.append(f"change {i + 1} is not an object")
        return None
    cid = str(raw.get("id") or f"change {i + 1}")
    monday = _day(raw.get("monday"))
    if monday is None:
        problems.append(f"{cid}: its monday is not a date")
        return None
    if raw.get("knob") not in KNOBS:
        problems.append(f"{cid}: {raw.get('knob')} is not a knob")
        return None
    verdict, source = raw.get("verdict"), raw.get("source")
    if verdict is not None and verdict not in VERDICTS:
        problems.append(f"{cid}: verdict {verdict} is neither kept nor reverted")
        verdict = None
    if source is not None and source not in SOURCES:
        problems.append(f"{cid}: source {source} is neither master nor user")
        source = None
    dates = {}
    for key in ("judged_on", "rolled_out"):
        dates[key] = _day(raw[key]) if raw.get(key) is not None else None
        if raw.get(key) is not None and dates[key] is None:
            problems.append(f"{cid}: its {key} is not a date")
    leagues = raw.get("leagues") or []
    if not isinstance(leagues, list):
        problems.append(f"{cid}: its leagues are not a list")
        leagues = []
    return {
        "id": cid,
        "monday": monday,
        "knob": raw["knob"],
        "from": raw.get("from"),
        "to": raw.get("to"),
        "leagues": [str(x) for x in leagues],
        "source": source,
        "reason": raw.get("reason"),
        "decided_at": raw.get("decided_at"),
        "verdict": verdict,
        **dates,
    }


def knob_file(raw: Any) -> tuple[dict[str, Any], list[str]]:
    """The knob file as read (None when there is none): the knobs in force, each league's own
    values and the knobs frozen in it, and the changes, oldest first; with the problems met."""
    problems: list[str] = []
    out: dict[str, Any] = {"in_force": {}, "leagues": {}, "frozen": {}, "changes": []}
    if raw is None:
        return out, problems
    if not isinstance(raw, Mapping):
        return out, ["the knob file is not an object"]
    out["in_force"] = _known("in_force", raw.get("in_force") or {}, problems)
    leagues = raw.get("leagues") or {}
    if isinstance(leagues, Mapping):
        out["leagues"] = {str(k): _known(f"league {k}", v, problems) for k, v in leagues.items()}
    else:
        problems.append("leagues is not an object")
    frozen = raw.get("frozen") or {}
    if isinstance(frozen, Mapping):
        for k, v in frozen.items():
            names = v if isinstance(v, list) else []
            bad = [x for x in names if x not in KNOBS]
            if bad or not isinstance(v, list):
                problems.append(f"frozen in league {k}: {', '.join(map(str, bad)) or v} not knobs")
            out["frozen"][str(k)] = [x for x in names if x in KNOBS]
    else:
        problems.append("frozen is not an object")
    changes = raw.get("changes") or []
    if not isinstance(changes, list):
        problems.append("changes is not a list")
        changes = []
    read = [c for i, raw_c in enumerate(changes) if (c := _change(i, raw_c, problems))]
    out["changes"] = sorted(read, key=lambda c: c["monday"])
    return out, problems


# --------------------------------------------------------------------------- the notes
_ITEM = re.compile(r"^\s*\d+[.)]\s+(.*)$")


def _items(lines: Sequence[str]) -> list[str]:
    """A numbered list's items, a line that continues one joined to it; without a number on
    any line, each line is an item (a bullet's dash dropped)."""
    items: list[str] = []
    numbered = any(_ITEM.match(x) for x in lines)
    for line in lines:
        if not line.strip():
            continue
        m = _ITEM.match(line)
        if m:
            items.append(m.group(1).strip())
        elif numbered and items:
            items[-1] = f"{items[-1]} {line.strip()}"
        elif not numbered:
            items.append(line.strip().removeprefix("- ").removeprefix("* "))
    return items


def _heading(line: str) -> str | None:
    name = line[3:].strip().rstrip(":").lower()
    if name.startswith("what is not"):
        return SECTIONS["what is not"]
    return SECTIONS.get(name)


def note(text: str, monday: str) -> tuple[dict[str, Any], list[str]]:
    """A Monday note as read: its four sections (``## `` headings, named as docs/AUTOPILOT.md
    section 6 names them), the action items as a list, and when it was posted on the tracker
    (an optional first line ``posted: <time>``); with the problems met."""
    problems: list[str] = []
    body: dict[str, list[str]] = {}
    current: str | None = None
    posted = None
    for i, line in enumerate(text.splitlines()):
        if i == 0 and line.lower().startswith("posted:"):
            posted = line.split(":", 1)[1].strip() or None
            continue
        if line.startswith("## "):
            current = _heading(line)
            if current is None:
                problems.append(f"note {monday}: {line[3:].strip()} is not a section")
                current = ""
            body.setdefault(current, [])
            continue
        if current:
            body[current].append(line)
    missing = [name for name, key in SECTIONS.items() if key not in body]
    if missing:
        problems.append(f"note {monday}: no section {', '.join(missing)}")
    sections = {
        key: "\n".join(body.get(key, [])).strip() or None
        for key in ("working", "not_working", "decision")
    }
    return {
        "monday": monday,
        "posted": posted,
        **sections,
        "actions": _items(body.get("actions", [])),
    }, problems


def week_at(weeks: Iterable[Mapping[str, Any]], day: str) -> int | None:
    """The number of the week (``week``, ``start``, ``end``) that holds ``day``."""
    return next((int(w["week"]) for w in weeks if w["start"] <= day <= w["end"]), None)


# --------------------------------------------------------------------------- a change's A/B
def _mean(xs: Sequence[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def _half(
    leagues: Sequence[str], rows: Mapping[str, Sequence[Mapping[str, Any]]], first: int, last: int
) -> dict[str, Any]:
    """One half of a change over weeks ``first`` to ``last``: the wins above expected a league
    (over the weeks it projected), the moves a league a week, the standing places climbed
    summed (from the week before ``first``), the Brier score, and the scored moves' realized
    value against their projected by unit."""
    above, briers, climbed, made = [], [], 0, 0
    units: dict[str, dict[str, float]] = {}
    for league in leagues:
        weeks = {r["week"]: r for r in rows.get(league, ())}
        shown = [weeks[w] for w in range(first, last + 1) if w in weeks]
        projected = [r for r in shown if r["expected"] is not None and r["won"] is not None]
        if projected:
            above.append(sum(r["won"] - r["expected"] for r in projected))
        briers += [r["brier"] for r in projected if r["brier"] is not None]
        made += sum(r["moves"]["made"] for r in shown)
        before, after = weeks.get(first - 1), shown[-1] if shown else None
        if before and after and before.get("rank") and after.get("rank"):
            climbed += before["rank"] - after["rank"]
        for r in shown:
            c = r["moves"].get("compared")
            if c:
                u = units.setdefault(r["scoring"], {"moves": 0, "projected": 0.0, "realized": 0.0})
                u["moves"] += c["moves"]
                u["projected"] = round(u["projected"] + c["projected"], 4)
                u["realized"] = round(u["realized"] + c["realized"], 4)
    for u in units.values():
        u["share"] = round(u["realized"] / u["projected"], 4) if u["projected"] > 0 else None
    weeks_run = max(last - first + 1, 0)
    return {
        "leagues": list(leagues),
        "wins_above": _mean(above),
        "moves_a_week": round(made / (len(leagues) * weeks_run), 4)
        if leagues and weeks_run
        else None,
        "standing_climbed": climbed,
        "brier": _mean(briers),
        "moves": units,
    }


def ab(
    change: Mapping[str, Any],
    week: int | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    last: int | None,
) -> dict[str, Any] | None:
    """A change against the setting it replaced: the leagues that took it (A) and the public
    leagues that kept the setting (B), each half's figures over the weeks the change is judged
    on (from its ``week``, :data:`JUDGED_WEEKS` of them, as far as recorded), and each recorded
    week's wins above expected a league for both halves, from two weeks before it. ``rows`` are
    the public leagues' week rows; None before its week is known."""
    if week is None:
        return None
    a = [lg for lg in rows if lg in change["leagues"]]
    b = [lg for lg in rows if lg not in change["leagues"]]
    end = min(week + JUDGED_WEEKS - 1, last) if last is not None else week - 1
    series = []
    for w in range(max(week - 2, 1), (last or 0) + 1):
        point: dict[str, Any] = {"week": w}
        for key, half in (("a", a), ("b", b)):
            xs = [
                r["won"] - r["expected"]
                for lg in half
                for r in rows.get(lg, ())
                if r["week"] == w and r["expected"] is not None and r["won"] is not None
            ]
            point[key] = _mean(xs)
        series.append(point)
    return {
        "window": [week, end] if end >= week else None,
        "a": _half(a, rows, week, end),
        "b": _half(b, rows, week, end),
        "series": series,
    }


# --------------------------------------------------------------------------- the sentences
def _games(x: float) -> str:
    return f"{x:.1f} {'win' if abs(x - 1) < 1e-9 else 'wins'}"


def _say(topic: str, scope: str, tone: str, text: str) -> dict[str, str]:
    return {"topic": topic, "scope": scope, "tone": tone, "text": text}


def wins_sentence(
    scope: str, won: float, expected: float, count: int, noun: str, even: float
) -> dict[str, str]:
    """Wins against their expectation over ``count`` projected ``noun``s (weeks of a league,
    matchups pooled): tracking it within ``even``, else ahead or behind by the gap."""
    gap = won - expected
    numbers = f"{won:g} won against {expected:.1f} expected over {count} projected {noun}{'s' * (count != 1)}"
    if abs(gap) < even:
        return _say("wins", scope, "neutral", f"{numbers}: actual tracks expected within a game.")
    side = "ahead of" if gap > 0 else "behind"
    return _say(
        "wins",
        scope,
        "good" if gap > 0 else "bad",
        f"{numbers}: {_games(abs(gap))} {side} expectation.",
    )


def moves_sentence(scope: str, scoring: str, c: Mapping[str, Any]) -> dict[str, str]:
    n, share = c["moves"], c.get("share")
    units = UNITS.get(scoring, "value units")
    head = f"The {n} scored move{'s' * (n != 1)} with a complete week ({units})"
    way = f"{c['same_way']} of {n} in the projected direction"
    if share is None:
        return _say("moves", scope, "neutral", f"{head} were projected at nothing or less; {way}.")
    low, high = SHARE_BAND
    if low <= share <= high:
        return _say(
            "moves",
            scope,
            "neutral",
            f"{head} realized {share:.0%} of their projection, tracking it; {way}.",
        )
    side, tone = ("trail", "bad") if share < low else ("beat", "good")
    gap = abs(1 - share)
    return _say(
        "moves",
        scope,
        tone,
        f"{head} realized {share:.0%} of their projection: they {side} it by {gap:.0%}; {way}.",
    )


def odds_sentences(scope: str, calibration: Mapping[str, Any]) -> list[dict[str, str]]:
    out = []
    if calibration.get("brier") is not None:
        weeks = calibration["weeks"]
        out.append(
            _say(
                "odds",
                scope,
                "neutral",
                f"The matchup odds' Brier score is {calibration['brier']:.2f} over {weeks} week{'s' * (weeks != 1)} (0.25 is a coin flip, lower is better).",
            )
        )
    for b in calibration.get("buckets") or []:
        if b["count"] < BUCKET_MIN or b["odds"] is None or abs(b["won"] - b["odds"]) < BUCKET_GAP:
            continue
        # Over-confident: the results fell nearer a coin flip than the odds said.
        bold = abs(b["won"] - 0.5) < abs(b["odds"] - 0.5)
        word = "over-confident" if bold else "timid"
        band = f"{b['from']:.0%} to {b['to']:.0%}"
        out.append(
            _say(
                "odds",
                scope,
                "bad",
                f"The category odds of {band} are {word}: they said {b['odds']:.0%} and {b['won']:.0%} came in, over {b['count']} categories.",
            )
        )
    return out


def change_sentence(change: Mapping[str, Any], week: int | None) -> dict[str, str]:
    what = f"{change['id']} ({change['knob']} {change['from']} → {change['to']})"
    if change["verdict"] is None:
        when = (
            f"after week {week + JUDGED_WEEKS - 1}"
            if week is not None
            else "two weeks after it starts"
        )
        return _say("knobs", "pooled", "neutral", f"{what} is pending: it is judged {when}.")
    ab_ = change.get("ab") or {}
    a, b = (ab_.get("a") or {}).get("wins_above"), (ab_.get("b") or {}).get("wins_above")
    figure = ""
    if a is not None and b is not None:
        figure = f": the leagues that took it ran {a - b:+.1f} wins a league against those that kept the setting over its weeks"
    tone = "good" if change["verdict"] == "kept" else "bad"
    return _say("knobs", "pooled", tone, f"{what} was {change['verdict']}{figure}.")


def sentences(
    pooled: Mapping[str, Any] | None,
    leagues: Sequence[Mapping[str, Any]],
    calibration: Mapping[str, Any] | None,
    moves: Mapping[str, Mapping[str, Any]],
    changes: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """The narrative by rule, each sentence with its topic (``wins``, ``league``, ``moves``,
    ``odds``, ``knobs``), its scope (``pooled`` or a league's id) and its tone (``good``,
    ``bad`` or ``neutral``): the public leagues' wins against expectation pooled, each league a
    game or more off its own, the scored moves' realized share of their projection by unit,
    the matchup odds' Brier score and any bucket of category odds off its results, and each
    knob change's verdict or when it is judged. ``pooled`` and each league carry ``won``,
    ``expected`` and ``weeks`` over their projected weeks."""
    out = []
    if pooled and pooled.get("weeks"):
        out.append(
            wins_sentence(
                "pooled", pooled["won"], pooled["expected"], pooled["weeks"], "matchup", WINS_EVEN
            )
        )
    for lg in leagues:
        if not lg.get("weeks") or abs(lg["won"] - lg["expected"]) < LEAGUE_GAP:
            continue
        s = wins_sentence(lg["league"], lg["won"], lg["expected"], lg["weeks"], "week", LEAGUE_GAP)
        out.append({**s, "topic": "league", "text": f"League {lg['league']}: {s['text']}"})
    for scoring, c in moves.items():
        if c.get("moves"):
            out.append(moves_sentence("pooled", scoring, c))
    if calibration:
        out += odds_sentences("pooled", calibration)
    out += [change_sentence(c, c.get("week")) for c in changes]
    return out
