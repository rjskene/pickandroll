"""SEASON SIM (#172, PR lab): the lab's model, pure.

The records the simulator already writes and the lead's notes in, one dict out (:func:`build`).
Nothing here reads a file, plays a season or writes anything: the server (``lab/server.py``)
reads the records and hands them over, and the page draws what this returns. Every number the
page shows is here.

The sections, as the page has them:

- **rulesets**: the runs grouped by their league's rules less the rivals' (:func:`ruleset_key`),
  each with its baseline (from a screen row that sets nothing but its tier in both arms), what its
  screens tried, its strongest row, the four stages of "is the seat getting better?", and its
  checks;
- **knobs**: every row of every screen, with each outcome's paired difference, its SE and its
  ratio; and the rows two rulesets share;
- **checks**: the luck figures and the flags (:data:`LUCK`), by ruleset and in all;
- **runs** and **tunes**: each run's pieces, pairs, audit and code; a tune's search and its
  confirmation;
- **seasons**: the seasons' ledger, from the records and the notes' roles;
- **capabilities** (PR capabilities): the simulator's log of marks (``sim/capabilities.py``),
  the live engine's changes from the notes, what each run was played on and was behind live
  in, and where a ruleset's figures cross a mark;
- **notes**: the lead's notes as given (:func:`notes_of` checks them);
- **generated**: when, on what code, what was read and what was refused.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from itertools import pairwise
from statistics import NormalDist
from typing import Any

from .. import capabilities as cap
from .. import screen as sc

#: The model's own version (its shape, for the page): no record's version moves with it. 2 since
#: PR live screen: a screen's run names its folder and its state as played (:func:`live_state`),
#: and the notes' ``state`` may name the planned pieces.
LAB_VERSION = 2

#: The outcomes a pair records, in the page's order, with their words and which way is better.
OUTCOMES: Mapping[str, Mapping[str, Any]] = {
    "matchup_wins": {"label": "Matchup wins", "better": 1, "share": False},
    "category_wins": {"label": "Category wins", "better": 1, "share": False},
    "made_playoffs": {"label": "Playoff odds", "better": 1, "share": True},
    "rank": {"label": "Final rank", "better": -1, "share": False},
    "title": {"label": "Title odds", "better": 1, "share": True},
}
#: The counts a row's tip shows, by the record's names.
COUNTS = ("adds_per_week", "landed", "claims_placed", "claims_won", "claims_lost", "weeks_at_cap")
#: The rules' keys that are the rivals' and not the league's: left out of a ruleset's key.
RIVAL_KEYS = ("rival_bids", "rival_scale")

OK, WATCH, PROBLEM = "ok", "watch", "problem"
LEVELS = (OK, WATCH, PROBLEM)

#: The share of tries with no real effect whose difference clears one SE, two SE: both sides of
#: the normal, about 0.317 and 0.0455.
ONE_SE = 2.0 * (1.0 - NormalDist().cdf(1.0))
TWO_SE = 2.0 * (1.0 - NormalDist().cdf(2.0))
#: The corrected bar's two-sided share for the whole family of tries: the bar for n tries is
#: the normal quantile of ``FAMILY / 2 / n`` (0.025 over n), and luck alone clears it
#: ``FAMILY`` times in all, whatever n.
FAMILY = 0.05
LUCK = (
    "a try is a played pair's cell that did something (a row that did nothing is no try); with "
    "no real effect a difference over its SE is about normal, so about 0.317 of tries clear one "
    "SE (0.159 each way), about 0.0455 clear two SE, and the corrected bar, the normal quantile "
    "of 0.025 over the number of tries, is cleared by luck alone 0.05 times in all"
)

#: The levers by name: a label, and what the lever is in the README's own words. A lever not
#: here shows its name.
LEVERS: Mapping[str, Mapping[str, str]] = {
    "protection_floor": {
        "label": "Protection floor",
        "words": "the engine's protection floor; its step is a game by scoring",
    },
    "daily_cap": {
        "label": "Daily add cap",
        "words": "the moves a seat may queue in a day, a whole number from 1 to 3",
    },
    "plan_floor_cats": {
        "label": "Plan floor (categories)",
        "words": "the gain a week plan must clear in a categories league, the gate a plan clears",
    },
    "plan_floor_points": {
        "label": "Plan floor (points)",
        "words": "the gain a week plan must clear in a points league",
    },
    "horizon_weight": {
        "label": "Horizon weight",
        "words": "the weighted search's mix of horizons: even, natural or season",
    },
    "three_weight": {
        "label": "Three weeks' weight",
        "words": "under the queue's rule, the weight of the three weeks in the queue's score",
    },
    "stash_threshold": {
        "label": "Stash threshold",
        "words": (
            "by how much the player who keeps a spot must beat a returning player's value net "
            "of his return before the returning player may leave"
        ),
    },
    "faab_sizing": {
        "label": "FAAB bid sizing",
        "words": "the live bid rule's multiplier, read in a FAAB run by a seat that bids",
    },
    "season_weight": {
        "label": "Rest-of-season weight",
        "words": (
            "the season term's weight: a set's score gains season_weight times its worth over "
            "the rest of the season; the baseline's is 0 and the nudges add a weight"
        ),
    },
    "playoff_weight": {
        "label": "Playoff weeks' weight",
        "words": "how many times a game in the bracket's weeks counts in the season term",
    },
    "pool": {
        "label": "Candidate pool size",
        "words": "the candidates the exact tier's set and week plan search, and the surrogate's",
    },
    "min_gain": {
        "label": "Minimum gain for a move",
        "words": "the least gain a candidate or a set must make, in the league's measure",
    },
    "weeks_ahead": {
        "label": "Weeks looked ahead",
        "words": "the weeks a problem looks ahead, this one included",
    },
    "surrogate_days": {
        "label": "Decision days (fast tier)",
        "words": "the days the surrogate solves",
    },
    "executes": {
        "label": "What the seat executes",
        "words": "three (the recommended set), weighted (the strategy route) or queue",
    },
    "execute_plan": {
        "label": "Execute the week plan",
        "words": "whether the streaming plan's due steps are queued beside the set",
    },
    "system": {
        "label": "Projection source",
        "words": "which of the two stand-ins the seat's own forecast reads, or a mix",
    },
    "blend": {
        "label": "Projection mix",
        "words": "the mix of the two stand-ins when the system is blend",
    },
    "guard": {
        "label": "Season guard",
        "words": "block (the default, as live) or off: whether a set that loses on the rest of the season may be queued",
    },
    "stake": {
        "label": "Week's stake",
        "words": "how much the week's stake for the seat scales down the season term after this week",
    },
    "bid.week": {
        "label": "Bid: this week's weight",
        "words": "the weight of the move's gain on the week",
    },
    "bid.season": {
        "label": "Bid: season's weight",
        "words": "the weight of the move's gain over the rest of the season",
    },
    "bid.pace.k": {
        "label": "Bid pacing strength",
        "words": "bid up when ahead of a spending path, down when behind: how hard",
    },
    "bid.pace.reserve": {
        "label": "Bid pacing reserve",
        "words": "the share of the budget the spending path keeps back",
    },
    "bid.routine": {
        "label": "Bid routine",
        "words": "what a claim worth no more than a typical one bids: 0 or 1 dollars",
    },
    "bid.rival_cap": {
        "label": "Bid cap at rivals' level",
        "words": "never more than the richest other team's dollars left, plus one",
    },
    "bid.shade": {
        "label": "Bid shading",
        "words": "never more than a quantile of the other teams' winning bids, plus one",
    },
    "guard_pool": {
        "label": "Guard's list size",
        "words": "the size of the guard's list the exact tier's pools take beside their best pool",
    },
}
#: A tier in the page's words.
TIERS = {
    "surrogate": "fast tier",
    "exact": "exact tier",
    "ranking": "ranking tier",
    "static": "static",
}
#: A season's roles, as the notes and the ledger name them.
ROLES = ("search", "confirm", "holdout", "current", "replay")
#: What the season's view is (PR viewer): it plays a trace the ``trace`` command wrote.
VIEWER = (
    "One path of one pair, both arms at once, played day by day from a trace: what differs "
    "between the arms, the knobs in force, each arm's move of the day, the week's matchup and "
    "the season's race. A trace is made by the trace command; the lab plays nothing."
)


#: The line the Season tab never drops (PR viewer).
VIEWER_NOTE = (
    "One path proves nothing: a pair is judged on its record's figures over every path, on the "
    "Knobs page."
)
#: What the Screen tab is (PR live screen): a screen as it is played, read from its record.
SCREEN_VIEW = (
    "A screen as it is played: every pair of its list on one board, the pair in play as its two "
    "arms, the clock of its pieces, and its story from the first piece to now. Read from what the "
    "screen writes when each pair ends; the lab plays nothing."
)


class NotesError(ValueError):
    """A notes file that is not the schema (:func:`notes_of`), by name."""


# --------------------------------------------------------------------------- the notes
#: The notes' sections: each a list of items with these fields (required, then optional), or
#: for ``state`` one item, for ``rulesets`` a mapping by ruleset key.
NOTE_ITEMS: Mapping[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "queue": (("title", "what", "state"), ("size", "say")),
    "assessments": (("date", "level", "text"), ("run", "ruleset")),
    "looks": (("name", "date", "what", "result"), ("issue",)),
    "openings": (("title", "why", "state"), ("cost",)),
    "proposals": (("date", "title", "text"), ("state",)),
    "seasons": (("id", "role"), ("note",)),
    # The live engine's changes (PR capabilities): the lead writes one for each word the master
    # posts on #172; ``taken_in`` is the replay version that took it in, or null.
    "engine": (("date", "issue", "title", "words"), ("taken_in",)),
}
NOTE_CHOICES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "queue": {"state": ("word", "running", "later", "done", "planned")},
    "assessments": {"level": LEVELS},
    "openings": {"state": ("asked", "planned", "idea", "later", "done")},
    "proposals": {"state": ("asked", "taken", "declined")},
    "seasons": {"role": ROLES},
}
NOTE_KEYS = ("state", *NOTE_ITEMS, "rulesets")
_SEASON_ID = re.compile(r"^(\d{4})-(\d{2})$")


def season_words(season: int) -> str:
    """An ESPN season id as the page says it: 2023 is 2022-23."""
    return f"{season - 1}-{str(season)[2:]}"


def season_of(text: str) -> int | None:
    """A season said as "2022-23", by its ESPN id (2023); None when it is not one."""
    m = _SEASON_ID.match(text)
    if m is None:
        return None
    start, end = int(m.group(1)), int(m.group(2))
    return start + 1 if (start + 1) % 100 == end else None


def _text(x: Any, where: str) -> str:
    if not isinstance(x, str) or not x.strip():
        raise NotesError(f"notes: {where}: a non-empty text")
    return x


def _item(x: Any, section: str, i: int) -> dict[str, Any]:
    where = f"{section}[{i}]"
    if not isinstance(x, Mapping):
        raise NotesError(f"notes: {where}: an object")
    need, may = NOTE_ITEMS[section]
    unknown = sorted(set(x) - set(need) - set(may))
    if unknown:
        raise NotesError(f"notes: {where}: {unknown[0]!r} is not a field of {section}")
    out: dict[str, Any] = {}
    for key in (*need, *may):
        if key not in x:
            if key in need:
                raise NotesError(f"notes: {where}: {key!r} is missing")
            continue
        if section == "engine" and key == "taken_in":
            v = x[key]
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 1):
                raise NotesError(
                    f"notes: {where}.taken_in: a replay version (a whole number from 1) or null"
                )
            out[key] = v
            continue
        out[key] = _text(x[key], f"{where}.{key}")
    if section == "engine" and not cap.ISSUE.fullmatch(out["issue"]):
        raise NotesError(f"notes: {where}.issue: {out['issue']!r} is not an issue like #485")
    if "date" in out:
        try:
            date.fromisoformat(out["date"])
        except ValueError:
            raise NotesError(
                f"notes: {where}.date: {out['date']!r} is not a date (YYYY-MM-DD)"
            ) from None
    for key, choices in NOTE_CHOICES.get(section, {}).items():
        if key in out and out[key] not in choices:
            raise NotesError(
                f"notes: {where}.{key}: {out[key]!r} is not one of {', '.join(choices)}"
            )
    if section == "seasons":
        season = season_of(out["id"])
        if season is None:
            raise NotesError(f"notes: {where}.id: {out['id']!r} is not a season like 2022-23")
        out["season"] = season
    return out


def notes_of(x: Any) -> dict[str, Any]:
    """The lead's notes, checked: an object of :data:`NOTE_KEYS`, each optional. ``state`` is
    ``{"running": text or null, "text": text}`` and may add ``"pieces"``, the planned pieces of
    the screen in play in words (PR live screen); each list section's items have the fields of
    :data:`NOTE_ITEMS` (required, then optional), texts all but an ``engine`` item's
    ``taken_in`` (a replay version or null), a ``date`` as YYYY-MM-DD and the choices of
    :data:`NOTE_CHOICES`; a season's ``id`` is said as 2022-23, an ``engine`` item's ``issue``
    as #485. ``rulesets`` maps a
    ruleset's key to ``{"name", "order", "flags"}``, each optional, a flag ``{"level", "title",
    "text"}``. Anything else is refused by name (:class:`NotesError`)."""
    if not isinstance(x, Mapping):
        raise NotesError("notes: the file holds no object")
    unknown = sorted(set(x) - set(NOTE_KEYS))
    if unknown:
        raise NotesError(f"notes: {unknown[0]!r} is not a section (one of {', '.join(NOTE_KEYS)})")
    out: dict[str, Any] = {k: [] for k in NOTE_ITEMS}
    out["state"] = None
    out["rulesets"] = {}
    if "state" in x:
        s = x["state"]
        if not isinstance(s, Mapping) or set(s) - {"running", "text", "pieces"}:
            raise NotesError("notes: state: an object of running, text and pieces")
        running = s.get("running")
        if running is not None:
            running = _text(running, "state.running")
        out["state"] = {"running": running, "text": _text(s.get("text"), "state.text")}
        # The planned pieces of the screen in play, in words (PR live screen): the record knows
        # when its pieces ran, never when the next will.
        if "pieces" in s:
            out["state"]["pieces"] = _text(s["pieces"], "state.pieces")
    for section in NOTE_ITEMS:
        if section not in x:
            continue
        items = x[section]
        if not isinstance(items, list):
            raise NotesError(f"notes: {section}: a list")
        out[section] = [_item(item, section, i) for i, item in enumerate(items)]
    rs = x.get("rulesets", {})
    if not isinstance(rs, Mapping):
        raise NotesError("notes: rulesets: an object by ruleset key")
    for key, v in rs.items():
        where = f"rulesets.{key}"
        if not isinstance(v, Mapping) or set(v) - {"name", "order", "flags"}:
            raise NotesError(f"notes: {where}: an object of name, order and flags")
        got: dict[str, Any] = {"flags": []}
        if "name" in v:
            got["name"] = _text(v["name"], f"{where}.name")
        if "order" in v:
            if isinstance(v["order"], bool) or not isinstance(v["order"], int):
                raise NotesError(f"notes: {where}.order: a whole number")
            got["order"] = v["order"]
        flags = v.get("flags", [])
        if not isinstance(flags, list):
            raise NotesError(f"notes: {where}.flags: a list")
        for i, f in enumerate(flags):
            fw = f"{where}.flags[{i}]"
            if not isinstance(f, Mapping) or set(f) != {"level", "title", "text"}:
                raise NotesError(f"notes: {fw}: an object of level, title and text")
            if f["level"] not in LEVELS:
                raise NotesError(
                    f"notes: {fw}.level: {f['level']!r} is not one of {', '.join(LEVELS)}"
                )
            got["flags"].append(
                {
                    "level": f["level"],
                    "title": _text(f["title"], f"{fw}.title"),
                    "text": _text(f["text"], f"{fw}.text"),
                    "from": "notes",
                }
            )
        out["rulesets"][str(key)] = got
    return out


# --------------------------------------------------------------------------- figures
def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(x)


def stat(block: Mapping[str, Any] | None, key: str) -> dict[str, Any]:
    """One outcome's ``{mean, se, n}`` from a record's block of them."""
    v = (block or {}).get(key) or {}
    n = v.get("n")
    return {
        "mean": _num(v.get("mean")),
        "se": _num(v.get("se")),
        "n": n if isinstance(n, int) else None,
    }


def diff_of(block: Mapping[str, Any] | None, outcome: str) -> dict[str, Any]:
    """A paired difference on ``outcome`` (B less A), with its ratio to its SE, the ratio signed
    so that above zero is better for the seat (``z``), whether it clears one SE (as the screen
    reads its measure: the mean's size above the SE; never without an SE) and which side it is
    on. An SE of zero gives no ratio."""
    d = stat(block, outcome)
    mean, se, better = d["mean"], d["se"], OUTCOMES[outcome]["better"]
    ratio = mean / se if mean is not None and se else None
    d["ratio"] = ratio
    d["z"] = None if ratio is None else ratio * better
    d["clears"] = mean is not None and se is not None and abs(mean) > se
    d["side"] = "none" if not mean else ("better" if mean * better > 0 else "worse")
    return d


def outcomes_of(block: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {o: stat(block, o) for o in OUTCOMES}


def diffs_of(block: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {o: diff_of(block, o) for o in OUTCOMES}


def domain(rows: Sequence[Mapping[str, Any]], outcome: str) -> dict[str, float]:
    """The forest's half-width for ``outcome`` over the rows that did something: in the
    outcome's units, the largest mean plus two SE rounded up at its first digit; in SEs, the
    largest ratio plus two, whole, at least four."""
    raw, z = 0.0, 0.0
    for r in rows:
        d = (r.get("diff") or {}).get(outcome) or {}
        if d.get("mean") is None or r.get("did_nothing"):
            continue
        raw = max(raw, abs(d["mean"]) + 2 * (d["se"] or 0.0))
        if d.get("ratio") is not None:
            z = max(z, abs(d["ratio"]) + 2)
    if raw > 0:
        p = 10 ** math.floor(math.log10(raw))
        raw = math.ceil(raw / p - 1e-9) * p
    else:
        raw = 1.0
    return {"raw": raw, "se": float(max(4, math.ceil(z)))}


def luck(zs: Sequence[float | None]) -> dict[str, Any]:
    """Seen against luck alone over the tries ``zs`` (each try's difference over its SE): at one
    SE, at two, and at the bar corrected for their number (:data:`LUCK`)."""
    n = len(zs)
    sizes = [abs(z) for z in zs if z is not None]
    bar = -NormalDist().inv_cdf(FAMILY / 2 / n) if n else None
    bars = [
        {
            "name": "Clears 1 SE",
            "bar": 1.0,
            "note": None,
            "seen": sum(1 for z in sizes if z > 1),
            "luck": n * ONE_SE,
        },
        {
            "name": "Clears 2 SE",
            "bar": 2.0,
            "note": None,
            "seen": sum(1 for z in sizes if z > 2),
            "luck": n * TWO_SE,
        },
    ]
    if bar is not None:
        bars.append(
            {
                "name": f"Clears {bar:.1f} SE",
                "bar": bar,
                "note": f"the bar corrected for {n} tries",
                "seen": sum(1 for z in sizes if z > bar),
                "luck": FAMILY,
            }
        )
    return {"tries": n, "bar": bar, "bars": bars, "rule": LUCK}


# --------------------------------------------------------------------------- rulesets
def ruleset_key(rules: Mapping[str, Any]) -> str:
    """A stable key from a run's league rules less the rivals' (:data:`RIVAL_KEYS`): a short
    hash of their canonical JSON."""
    kept = {k: v for k, v in rules.items() if k not in RIVAL_KEYS}
    blob = json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)
    return "rs-" + hashlib.sha256(blob.encode()).hexdigest()[:8]


def ruleset_name(rules: Mapping[str, Any]) -> str:
    """A ruleset's name when the notes give none: its format and its waivers."""
    if rules.get("scoring") == "points":
        fmt = "Points"
    elif rules.get("h2h") == "each_category":
        fmt = "Every category"
    else:
        fmt = "One win a matchup"
    waivers = {"faab": "FAAB", "priority": "waivers by priority"}.get(
        str(rules.get("waivers")), "no waivers"
    )
    return f"{fmt}, {waivers}"


def rules_label(label: str | None) -> str:
    """A record's league label less the rivals' clause (its last, in a FAAB league)."""
    text = str(label or "")
    cut = text.find(", the rivals' bids")
    return text if cut < 0 else text[:cut]


def _league_of(world: Mapping[str, Any]) -> dict[str, str]:
    """The ``--league`` flag's parts (``teams=12,slots=13,...``), as typed; empty without one."""
    out = {}
    for part in str(world.get("league") or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def chips(
    rules: Mapping[str, Any], world: Mapping[str, Any], shapes: Sequence[Mapping[str, Any]] | None
) -> list[str]:
    """A ruleset's chips, in words: its league's shape (from a pair's record, else the flag),
    its held slots, its format, its waivers and its lineup rule."""
    out: list[str] = []
    shape = shapes[0] if shapes and len(shapes) == 1 else None
    flag = _league_of(world)
    if shapes and len(shapes) > 1:
        out.append(f"a grid of {len(shapes)} league shapes")
    # A shape's ``slots`` is its list of positions: the chip counts them.
    teams = _count((shape or {}).get("teams", flag.get("teams")))
    slots = _count((shape or {}).get("slots", flag.get("slots")))
    adds = _count((shape or {}).get("weekly_adds", flag.get("adds")))
    if teams is not None:
        out.append(f"{teams} teams")
    if slots is not None:
        out.append(f"{slots} roster spots")
    held = list(rules.get("held") or [])
    for kind in dict.fromkeys(held):
        n = held.count(kind)
        out.append(f"{n} {kind} slot{'s' if n > 1 else ''}")
    if adds is not None:
        out.append(f"{adds} adds a week")
    if rules.get("scoring") == "points":
        out.append("points")
    else:
        out.append(
            "every category counts"
            if rules.get("h2h") == "each_category"
            else "one win per matchup"
        )
    waivers = rules.get("waivers")
    if waivers == "faab":
        out.append(f"FAAB, ${_words(rules.get('budget'))}")
    elif waivers == "priority":
        out.append("waivers by priority")
    else:
        out.append("no waivers")
    if waivers in ("faab", "priority"):
        out.append(
            "every add is a claim"
            if rules.get("waiver_rule") == "continuous"
            else f"a dropped player waits {_words(rules.get('waiver_days'))} days"
        )
    if rules.get("lineup_from") == "today":
        out.append("an add plays the same day")
    po_teams = (shape or {}).get("playoff_teams")
    po_weeks = (shape or {}).get("playoff_weeks")
    if po_teams is None and "playoffs" in flag and "/" in flag["playoffs"]:
        po_teams, po_weeks = flag["playoffs"].split("/", 1)
    if po_teams is not None:
        out.append(f"{_words(po_teams)} playoff teams, {_words(po_weeks)} weeks")
    return out


def teams_of(world: Mapping[str, Any], shapes: Sequence[Mapping[str, Any]] | None) -> int | None:
    """The league's teams, when its runs played one shape (a rank is out of them); else None."""
    if shapes:
        got = {sh.get("teams") for sh in shapes}
        return got.pop() if len(got) == 1 and isinstance(next(iter(got)), int) else None
    t = _league_of(world).get("teams")
    return int(t) if t and t.isdigit() else None


# --------------------------------------------------------------------------- a screen
def _cells(result: Mapping[str, Any]) -> list[tuple[str, str, Mapping[str, Any]]]:
    return [
        (t, label, cell)
        for t, by_label in (result.get("cells") or {}).items()
        for label, cell in by_label.items()
    ]


def _counts(payload: Mapping[str, Any] | None, t: str, label: str) -> dict[str, dict[str, Any]]:
    by = (((payload or {}).get("counts") or {}).get("by_season") or {}).get(t, {}).get(label, {})
    return {
        side: {c: _num(((by.get(side) or {}).get(c) or {}).get("mean")) for c in COUNTS}
        for side in ("a", "b", "rivals")
    }


def _audit(payload: Mapping[str, Any] | None) -> tuple[int, int]:
    a = (payload or {}).get("audit") or {}
    return len(a.get("breaches") or []), int(a.get("paths_voided") or 0)


def _shown(x: Any) -> str:
    return sc.shown(x)


def lever_label(name: str) -> str:
    return (LEVERS.get(name) or {}).get("label", name)


def screen_rows(
    run: str,
    rk: str,
    record: Mapping[str, Any],
    pairs: Mapping[str, Mapping[str, Any]],
    lacks: list[str],
) -> list[dict[str, Any]]:
    """A screen's rows for the Knobs page: one for each row not played, one for each cell of a
    played row, with both arms' outcomes from the pair's record, the difference on every
    outcome, the record's own "survives" (on the league's measure, in that cell) and "did
    nothing", the counts the tip shows and the pair's audit."""
    measure = record.get("measure") or "matchup_wins"
    out = []
    for row in record.get("rows") or []:
        values = row.get("values")
        base = {
            "run": run,
            "ruleset": rk,
            "lever": row.get("lever"),
            "label": lever_label(str(row.get("lever"))),
            "key": row.get("key"),
            "nudge": row.get("nudge"),
            "values": None
            if not values
            else {"a": _shown(values.get("a")), "b": _shown(values.get("b"))},
            "tier": row.get("tier"),
            "both": {k: _shown(v) for k, v in (row.get("both") or {}).items() if k != "tier"},
            "status": row.get("status"),
            "why": row.get("why"),
            "note": row.get("note"),
            "measure": measure,
        }
        result = row.get("result")
        if not result:
            out.append(base | {"played": False, "cell": None})
            continue
        payload = pairs.get(str(row.get("file") or f"{row.get('key')}.json"))
        if payload is None:
            lacks.append(f"screen {run}: the pair {row.get('key')}'s record is not in the folder")
        breaches, voided = _audit(payload)
        for t, label, cell in _cells(result):
            res = (((payload or {}).get("results") or {}).get(t) or {}).get(label) or {}
            out.append(
                base
                | {
                    "played": True,
                    "cell": f"{t} {label}",
                    "season": int(t),
                    "forecaster": label,
                    "paths": cell.get("paths"),
                    "did_nothing": bool(result.get("did_nothing")),
                    "survives": bool(result.get("survives")) and bool(cell.get("clears")),
                    "a": outcomes_of(res.get("a")) if res else None,
                    "b": outcomes_of(res.get("b")) if res else None,
                    "diff": diffs_of(cell.get("difference")),
                    "counts": _counts(payload, t, label),
                    "breaches": breaches,
                    "voided": int(result.get("voided") or voided),
                }
            )
    return out


def baseline_of(
    run: str, record: Mapping[str, Any], pairs: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    """The baseline's outcomes in a screen: arm A of a played row whose ``both`` is empty but for
    its ``tier`` (every row's ``both`` records the tier it plays on; a row that sets anything
    else in both arms plays another baseline), the first such row in the list's order; None
    when the screen has none, or its record is not in the folder."""
    for row in record.get("rows") or []:
        if not row.get("result") or set(row.get("both") or {}) - {"tier"}:
            continue
        payload = pairs.get(str(row.get("file") or f"{row.get('key')}.json"))
        if payload is None:
            continue
        cells = []
        for t, by_label in (payload.get("results") or {}).items():
            for label, res in by_label.items():
                cells.append(
                    {
                        "cell": f"{t} {label}",
                        "season": int(t),
                        "season_words": season_words(int(t)),
                        "forecaster": label,
                        "paths": res.get("paths"),
                        "outcomes": outcomes_of(res.get("a")),
                        "counts": _counts(payload, t, label)["a"],
                    }
                )
        return {"run": run, "row": row.get("key"), "tier": row.get("tier"), "cells": cells}
    return None


# --------------------------------------------------------------------------- a tune
def tune_summary(
    run: str, rk: str, record: Mapping[str, Any], pairs: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """A tune as the Runs page's table has it: its order, each step's values and choice, the
    final set, the confirmation's cells and verdict, and the gains: the search's (the sum of the
    taken steps' means; the steps share paths, so their SEs do not add and the sum has none),
    the confirmation's in each kind of rivals, and the share of the search's kept."""
    measure = record.get("measure") or "matchup_wins"
    steps = []
    gain = 0.0
    taken_any = False
    for step in record.get("steps") or []:
        standings = (step.get("choice") or {}).get("standings") or {}
        taken = (step.get("choice") or {}).get("key")
        values = []
        for v in step.get("values") or []:
            res = v.get("result") or {}
            vals = v.get("values")
            values.append(
                {
                    "key": v.get("key"),
                    "nudge": v.get("nudge"),
                    "values": None
                    if not vals
                    else {"a": _shown(vals.get("a")), "b": _shown(vals.get("b"))},
                    "status": v.get("status"),
                    "why": v.get("why"),
                    "mean": _num(res.get("mean")),
                    "se": _num(res.get("se")),
                    "signs": res.get("signs"),
                    "voided": int(res.get("voided") or 0),
                    "standing": standings.get(v.get("key")),
                    "taken": v.get("key") == taken and taken is not None,
                }
            )
            if v.get("key") == taken and taken is not None and _num(res.get("mean")) is not None:
                gain += float(res["mean"])
                taken_any = True
        steps.append(
            {
                "pass": step.get("pass"),
                "lever": step.get("lever"),
                "label": lever_label(str(step.get("lever"))),
                "from": _shown(step.get("from")),
                "why": step.get("why"),
                "values": values,
                "taken": taken,
            }
        )
    final = record.get("final")
    conf = record.get("confirmation") or {}
    cells = []
    confirm_gain: dict[str, Any] = {}
    for kind, by_label in (conf.get("cells") or {}).items():
        for label, c in by_label.items():
            d = c.get("difference") or {}
            entry = {
                "kind": kind,
                "forecaster": label,
                "read": bool(c.get("read")),
                "measure": diff_of(d, measure),
                "made_playoffs": diff_of(d, "made_playoffs"),
                "rank": diff_of(d, "rank"),
                "finish": c.get("finish"),
            }
            cells.append(entry)
            if entry["read"] and kind not in confirm_gain:
                confirm_gain[kind] = {"forecaster": label, **entry["measure"]}
    search = {"mean": gain if taken_any else 0.0, "se": None, "moved": taken_any}
    kept = {}
    for kind, g in confirm_gain.items():
        kept[kind] = (
            g["mean"] / search["mean"]
            if taken_any and search["mean"] > 0 and g["mean"] is not None
            else None
        )
    left = record.get("left")
    verdict = conf.get("verdict") or {}
    breaches = voided = 0
    for p in pairs.values():
        b, v = _audit(p)
        breaches, voided = breaches + b, voided + v
    world = (record.get("spec") or {}).get("world") or {}
    return {
        "name": run,
        "ruleset": rk,
        "measure": measure,
        "status": "left for the next piece" if left else "finished",
        "left": None if not left else {"next": left.get("next"), "stopped": left.get("stopped")},
        "order": [
            {
                "lever": o.get("lever"),
                "label": lever_label(str(o.get("lever"))),
                "from": _shown(o.get("from")),
                "strength": _num(o.get("strength")),
                "place": o.get("place"),
            }
            for o in record.get("order") or []
        ],
        "searched": [season_words(int(t)) for t in world.get("seasons") or []],
        "steps": steps,
        "final": None
        if not final
        else {
            "set": {k: _shown(v) for k, v in (final.get("set") or {}).items()},
            "levers": list(final.get("levers") or []),
            "tier": final.get("tier"),
            "unread": dict(final.get("unread") or {}),
        },
        "confirmation": {
            "status": conf.get("status"),
            "season": conf.get("season"),
            "season_words": None if not conf.get("season") else season_words(int(conf["season"])),
            "cells": cells,
            "verdict": None
            if not verdict
            else {
                "state": verdict.get("state"),
                "words": verdict.get("words"),
                "flags": list(verdict.get("flags") or []),
            },
        },
        "gains": {"search": search, "confirm": confirm_gain, "kept": kept},
        "audit": {"breaches": breaches, "voided": voided},
    }


# --------------------------------------------------------------------------- runs
def _when(x: Any) -> datetime | None:
    """A record's time; one written without an offset is read as UTC (the records write theirs
    with one), so times with and without an offset sort and subtract together."""
    if x is None:
        return None
    try:
        t = datetime.fromisoformat(str(x))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=UTC)


def _iso(x: Any) -> str | None:
    """A record's time as the page reads it: with its offset, or None when it is no time."""
    t = _when(x)
    return None if t is None else t.isoformat()


def _t(x: Any) -> float:
    """A record's time for ordering: its timestamp, or after every time when it has none."""
    t = _when(x)
    return math.inf if t is None else t.timestamp()


def _words(x: Any) -> str:
    """A record's list, mapping (its keys) or value as words, never a repr."""
    if x is None:
        return ""
    if isinstance(x, Mapping):
        return ", ".join(str(k) for k in x)
    if isinstance(x, list | tuple | set):
        return ", ".join(str(v) for v in x)
    return str(x)


def _count(x: Any) -> int | None:
    """How many: a list's length, or a whole number as given; None otherwise."""
    if isinstance(x, list | tuple):
        return len(x)
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, str) and x.strip().isdigit():
        return int(x)
    return None


def _hours(pieces: Sequence[Mapping[str, Any]]) -> float | None:
    total, any_ = 0.0, False
    for p in pieces:
        a, b = _when(p.get("started_at")), _when(p.get("finished_at"))
        if a is not None and b is not None:
            total += (b - a).total_seconds() / 3600.0
            any_ = True
    return total if any_ else None


def _pieces(timing: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    return [
        {
            "started_at": _iso(p.get("started_at")),
            "finished_at": _iso(p.get("finished_at")),
            "played": len(p.get("played") or []),
            "stopped": p.get("stopped"),
            "code_sha": (p.get("code_sha") or "")[:7] or None,
        }
        for p in (timing or {}).get("pieces") or []
    ]


#: A screen's state as played (:func:`live_state`, PR live screen).
IN_PLAY, PAUSED, FINISHED, NOT_STARTED = (
    "in play",
    "paused between pieces",
    "finished",
    "not started",
)


def live_state(record: Mapping[str, Any]) -> dict[str, Any]:
    """A screen's state as its record says it (PR live screen): ``in play`` while its last piece
    is open (no ``finished_at``), with the pair in play the first of ``left``; ``paused between
    pieces`` when no piece is open and pairs are left; ``finished`` when none is left; ``not
    started`` with no piece. A piece stopped from outside before it wrote its end reads as open
    while it is the last: the record cannot tell the two apart."""
    pieces = (record.get("timing") or {}).get("pieces") or []
    left = [str(k) for k in record.get("left") or []]
    played = sum(1 for r in record.get("rows") or [] if r.get("result"))
    if not pieces:
        state = NOT_STARTED
    elif pieces[-1].get("finished_at") is None:
        state = IN_PLAY
    elif left:
        state = PAUSED
    else:
        state = FINISHED
    return {
        "state": state,
        "in_play": left[0] if state == IN_PLAY and left else None,
        "played": played,
        "left": len(left),
        "pieces": len(pieces),
    }


def _seasons(xs: Any) -> list[int]:
    """A record's seasons, from a list of them or one alone."""
    if isinstance(xs, int | str):
        xs = [xs]
    return [
        int(t)
        for t in xs or []
        if isinstance(t, int | str) and not isinstance(t, bool) and str(t).isdigit()
    ]


# --------------------------------------------------------------------------- the build
# --------------------------------------------------------------------------- capabilities
def capability_of(replay_version: Any) -> dict[str, Any] | None:
    """The capability a run of ``replay_version`` was played on (``capabilities.at``), as the
    page shows it; None for a run that records no version."""
    m = cap.at(replay_version)
    if m is None:
        return None
    return {
        "id": m.id,
        "replay_version": m.replay_version,
        "title": m.title,
        "date": m.date,
        "kind": m.kind,
    }


def cap_words(c: Mapping[str, Any] | None) -> str:
    """A capability in words: its version and title."""
    return "no recorded version" if not c else f"version {c['replay_version']} ({c['title']})"


def engine_changes(notes: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The live engine's changes (the notes' ``engine``), oldest first, each with the replay
    version that took it in: the log's mark that names its issue (``capabilities.taken_in``,
    ``closed_by`` that mark), else the notes' own ``taken_in``; None while the simulator has not
    taken it in."""
    out = []
    for e in (notes or {}).get("engine") or []:
        mark = cap.taken_in(e["issue"])
        if mark is not None and mark.replay_version is not None:
            v, by = mark.replay_version, mark.id
        else:
            v = e.get("taken_in")
            by = None if v is None else "notes"
        out.append(
            {
                "date": e["date"],
                "issue": e["issue"],
                "title": e["title"],
                "words": e["words"],
                "taken_in": v,
                "closed_by": by,
            }
        )
    return sorted(out, key=lambda e: (e["date"], e["issue"]))


def _live_of(
    started: Any, replay_version: Any, engine: Sequence[Mapping[str, Any]], before: bool
) -> list[dict[str, Any]] | None:
    when = _when(started)
    if when is None or isinstance(replay_version, bool) or not isinstance(replay_version, int):
        return None
    day = cap.central_day(when)
    return [
        {"issue": e["issue"], "title": e["title"], "date": e["date"]}
        for e in engine
        if (e["date"] < day) == before and (e["taken_in"] is None or e["taken_in"] > replay_version)
    ]


def behind_live(
    started: Any, replay_version: Any, engine: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]] | None:
    """The live engine's changes a run was behind when it started: dated before the (Central)
    day it started, and not taken in by its version. None when the run records no start or no
    version."""
    return _live_of(started, replay_version, engine, True)


def live_since(
    started: Any, replay_version: Any, engine: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]] | None:
    """The live engine's changes since a run: dated on or after the (Central) day it started,
    and not taken in by its version, so its figures are of the engine live has left. None when
    the run records no start or no version."""
    return _live_of(started, replay_version, engine, False)


def _place_on(day: str, span: Mapping[str, str] | None) -> float | None:
    """A dated mark's place on the runs' time line, at the start of its (Central) day; None
    when there is no line or the day is off it."""
    if not span:
        return None
    t0, t1 = _when(span["start"]), _when(span["end"])
    t = cap.central_midnight(day)
    if t0 is None or t1 is None or t is None:
        return None
    width = (t1 - t0).total_seconds() or 1.0
    x = (t - t0).total_seconds() / width
    return x if 0.0 <= x <= 1.0 else None


def _arm_of(arm: Any) -> Any:
    return None if not isinstance(arm, Mapping) else {k: v for k, v in arm.items() if k != "name"}


def _shift(before: Mapping[str, Any], after: Mapping[str, Any]) -> float | None:
    a, b = before.get("mean"), after.get("mean")
    return None if a is None or b is None else b - a


def shifts_of(
    mine: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    info: Mapping[str, Mapping[str, Any]],
    measure: str,
) -> list[dict[str, Any]]:
    """Where two screens of one ruleset, one after the other, were played on different
    capabilities: what moved between them that no knob did, the capability's effect. The
    baseline, when both screens' baseline arms are the same arm (its name aside), cell by cell
    (season and forecaster); and each row both played with the same values, its difference B
    less A in each (a row that did nothing in both is left out). ``same_world`` says whether the seed and the paths are the same too: when
    not, part of a shift is the draw."""
    screens = [x for x in mine if x["kind"] == "screen" and x.get("capability")]
    out = []
    for s1, s2 in pairwise(screens):
        c1, c2 = s1["capability"], s2["capability"]
        if c1["id"] == c2["id"]:
            continue
        i1, i2 = info.get(s1["name"]) or {}, info.get(s2["name"]) or {}
        base = []
        b1, b2 = i1.get("baseline"), i2.get("baseline")
        if b1 and b2 and _arm_of(i1.get("arm")) == _arm_of(i2.get("arm")):
            before = {c["cell"]: c for c in b1["cells"]}
            for c in b2["cells"]:
                b = before.get(c["cell"])
                if b is None:
                    continue
                x, y = b["outcomes"][measure], c["outcomes"][measure]
                base.append(
                    {
                        "cell": c["cell"],
                        "season_words": c["season_words"],
                        "forecaster": c["forecaster"],
                        "before": {"mean": x["mean"], "se": x["se"]},
                        "after": {"mean": y["mean"], "se": y["se"]},
                        "shift": _shift(x, y),
                    }
                )
        earlier = {(r["key"], r["cell"]): r for r in rows if r["run"] == s1["name"] and r["played"]}
        same = []
        for r in rows:
            if r["run"] != s2["name"] or not r["played"]:
                continue
            q = earlier.get((r["key"], r["cell"]))
            if q is None or q["values"] != r["values"] or (q["did_nothing"] and r["did_nothing"]):
                continue
            x, y = q["diff"][measure], r["diff"][measure]
            same.append(
                {
                    "key": r["key"],
                    "label": r["label"],
                    "nudge": r["nudge"],
                    "values": r["values"],
                    "cell": r["cell"],
                    "before": {"mean": x["mean"], "se": x["se"]},
                    "after": {"mean": y["mean"], "se": y["se"]},
                    "shift": _shift(x, y),
                }
            )
        if base or same:
            out.append(
                {
                    "from": {"run": s1["name"], "capability": c1},
                    "to": {"run": s2["name"], "capability": c2},
                    "same_world": s1["seed"] == s2["seed"] and s1["paths"] == s2["paths"],
                    "baseline": base,
                    "rows": same,
                    "words": "the simulator's change between these screens, not a knob's",
                }
            )
    return out


def _names(xs: Sequence[str]) -> str:
    return ", ".join(xs)


def _changes(items: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(f"{e['issue']} {e['title']} ({e['date']})" for e in items)


def _behind_flag(
    mine: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None,
    engine: Sequence[Mapping[str, Any]],
    noted: bool,
) -> dict[str, Any]:
    """The "Behind live" flag: a problem when a tune started behind live (it tuned an engine
    live had left); a watch when the latest screen was played before the simulator took a live
    change in, or live has changed since it was played, or it records no version; ok
    otherwise."""
    said = []
    for t in mine:
        if t["kind"] == "tune" and t.get("behind_live"):
            said.append(
                f"{t['name']} ({cap_words(t['capability'])}) tuned an engine live had left: "
                f"{_changes(t['behind_live'])}."
            )
    level = PROBLEM if said else OK
    if run is None:
        said.append("No screen yet.")
    elif run.get("behind_live") is None:
        level = level if level == PROBLEM else WATCH
        said.append(
            f"Its latest screen, {run['name']}, records no version or start, so whether live had "
            "moved is not known."
        )
    elif run["behind_live"] or run.get("live_since"):
        level = level if level == PROBLEM else WATCH
        head = f"Its latest screen, {run['name']} ({cap_words(run['capability'])}),"
        if run["behind_live"]:
            said.append(f"{head} was played before the simulator took in: "
                        f"{_changes(run['behind_live'])}.")  # fmt: skip
        if run.get("live_since"):
            said.append(
                (
                    "Live has changed since it was played: "
                    if run["behind_live"]
                    else f"{head[:-1]}: live has changed since it was played: "
                )
                + f"{_changes(run['live_since'])}; its figures are of the earlier engine."
            )
    else:
        said.append(
            f"Its latest screen, {run['name']}, was played with nothing from live outstanding"
            + (
                "."
                if engine
                else (
                    " (the notes list no live-engine change)."
                    if noted
                    else " (no notes file: live's changes are not listed)."
                )
            )
        )
    return {"level": level, "title": "Behind live", "text": " ".join(said)}


def capability_flags(
    mine: Sequence[Mapping[str, Any]],
    latest: str | None,
    engine: Sequence[Mapping[str, Any]],
    noted: bool,
    by_name: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """A ruleset's three capability flags: whether its figures span more than one capability
    (a watch, saying which run sits where); whether its latest screen was played on an engine
    behind live or live has changed since (a watch, naming the changes), or a tune started
    behind live (a problem); and whether a tune reads a screen of another capability (a
    problem)."""
    out = []
    groups: dict[str, tuple[Mapping[str, Any], list[str]]] = {}
    unknown = []
    for x in mine:
        c = x.get("capability")
        if c is None:
            unknown.append(x["name"])
        else:
            groups.setdefault(c["id"], (c, []))[1].append(x["name"])
    tail = f" {len(unknown)} run(s) record no version: {_names(unknown)}." if unknown else ""
    if len(groups) > 1:
        out.append(
            {
                "level": WATCH,
                "title": "Capabilities",
                "text": "Its figures were played on more than one capability: "
                + "; ".join(f"{cap_words(c)}: {_names(ns)}" for c, ns in groups.values())
                + ". A difference across them is the simulator's change, not a knob's."
                + tail,
            }
        )
    elif groups:
        c, _ = next(iter(groups.values()))
        out.append(
            {
                "level": OK,
                "title": "Capabilities",
                "text": f"Every run with a version was played on {cap_words(c)}." + tail,
            }
        )
    else:
        out.append(
            {
                "level": WATCH,
                "title": "Capabilities",
                "text": "No run of it records the replay's version, so what it was played on "
                "is not known.",
            }
        )
    out.append(_behind_flag(mine, by_name.get(latest) if latest else None, engine, noted))
    tunes = [x for x in mine if x["kind"] == "tune"]
    if tunes:
        bad = []
        for t in tunes:
            sc_ = t.get("screen") or {}
            if not sc_.get("name"):
                continue
            theirs = capability_of(sc_.get("replay_version"))
            mine_c = t.get("capability")
            if theirs and mine_c and theirs["id"] != mine_c["id"]:
                bad.append(
                    f"{t['name']} ({cap_words(mine_c)}) reads the screen {sc_['name']}, played "
                    f"on {cap_words(theirs)}"
                )
        out.append(
            {
                "level": PROBLEM if bad else OK,
                "title": "Tune's screen",
                "text": "; ".join(bad) + ": its order and values come from another simulator."
                if bad
                else "Each tune reads a screen of its own capability.",
            }
        )
    return out


def build(
    screens: Sequence[Mapping[str, Any]],
    tunes: Sequence[Mapping[str, Any]],
    replays: Sequence[Mapping[str, Any]],
    looks: Sequence[Mapping[str, Any]],
    notes: Mapping[str, Any] | None,
    *,
    hold_out: int,
    confirmation: int,
    generated: Mapping[str, Any],
    traces: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The lab's model. ``screens`` and ``tunes``: each ``{"folder", "record", "pairs"}``, the
    folder's record and its pairs' records by file name; ``replays``: each ``{"file",
    "record"}``, a written replay's record; ``looks``: the confirmation ledger's lines;
    ``notes``: :func:`notes_of`'s, or None; ``hold_out`` and ``confirmation``: the code's two
    seasons; ``generated``: what the reader says of the build (when, the code's commit, what it
    read and refused), kept as given; ``traces``: each trace's line as ``trace_view.summary``
    makes it (PR viewer), listed, counted in the seasons' ledger and read by its two flags."""
    lacks: list[str] = []
    notes_rs = (notes or {}).get("rulesets") or {}
    runs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    tune_list: list[dict[str, Any]] = []
    by_rs: dict[str, dict[str, Any]] = {}
    info: dict[str, dict[str, Any]] = {}  # a screen's baseline arm and baseline, by name

    def ruleset(
        rules: Mapping[str, Any], label: Any, world: Mapping[str, Any], shapes: Any, started: Any
    ) -> str:
        rk = ruleset_key(rules)
        rs = by_rs.setdefault(
            rk,
            {
                "key": rk,
                "rules": {k: v for k, v in rules.items() if k not in RIVAL_KEYS},
                "label": rules_label(label),
                "measure": sc.measure_of(
                    str(rules.get("scoring", "categories")), str(rules.get("h2h", "one_win"))
                ),
                "screens": [],
                "tunes": [],
                "replays": [],
                "first": started,
                "world": dict(world),
                "shapes": shapes,
            },
        )
        if started and _t(started) < _t(rs["first"]):
            rs["first"] = started
        if shapes and not rs["shapes"]:
            rs["shapes"] = shapes
        return rk

    def first_shapes(pairs: Mapping[str, Mapping[str, Any]]) -> Any:
        for p in pairs.values():
            got = (p.get("league") or {}).get("shapes")
            if got:
                return got
        return None

    # Screens.
    for s in screens:
        rec, pairs = s["record"], s.get("pairs") or {}
        spec = rec.get("spec") or {}
        world = spec.get("world") or {}
        pieces = _pieces(rec.get("timing"))
        started = pieces[0]["started_at"] if pieces else None
        rules = (rec.get("league") or {}).get("rules") or {}
        rk = ruleset(
            rules, (rec.get("league") or {}).get("label"), world, first_shapes(pairs), started
        )
        name = str(rec.get("name") or s["folder"])
        mine = screen_rows(name, rk, rec, pairs, lacks)
        rows += mine
        played = [r for r in mine if r["played"]]
        breaches = sum(r["breaches"] for r in played)
        voided = sum(r["voided"] for r in played)
        not_played = [
            r
            for r in (rec.get("rows") or [])
            if r.get("status") in (sc.NOT_PLAYED, sc.NOT_READ, sc.REFUSED)
        ]
        tiers = sorted({str(r.get("tier")) for r in rec.get("rows") or [] if r.get("result")})
        runs.append(
            {
                "name": name,
                "kind": "screen",
                "folder": s["folder"],
                "live": live_state(rec),
                "ruleset": rk,
                "seasons": _seasons(world.get("seasons")),
                "forecasters": _words(world.get("forecasters")),
                "paths": world.get("paths"),
                "seed": world.get("seed"),
                "tiers": tiers,
                "code_sha": (rec.get("code_sha") or "")[:7] or None,
                "versions": {
                    "screen": rec.get("screen_version"),
                    "replay": spec.get("replay_version"),
                },
                "pairs_done": len({r["key"] for r in played}),
                "pairs_left": len(rec.get("left") or []),
                "not_played": len(not_played),
                "cleared": len(
                    {r["key"] for r in played if r["survives"] and not r["did_nothing"]}
                ),
                "pieces": pieces,
                "hours": _hours(pieces),
                "audit": {
                    "breaches": breaches,
                    "voided": voided,
                    "level": PROBLEM if breaches or voided else OK,
                },
                "status": "left for the next piece" if rec.get("left") else "finished",
                "started_at": started,
                "hold_out": rec.get("hold_out"),
            }
        )
        by_rs[rk]["screens"].append(name)
        bl = baseline_of(name, rec, pairs)
        by_rs[rk].setdefault("baselines", []).append((started, bl))
        info[name] = {"arm": spec.get("arm"), "baseline": bl}

    # Tunes.
    for t in tunes:
        rec, pairs = t["record"], t.get("pairs") or {}
        spec = rec.get("spec") or {}
        world = spec.get("world") or {}
        pieces = _pieces(rec.get("timing"))
        started = pieces[0]["started_at"] if pieces else None
        rules = (rec.get("league") or {}).get("rules") or {}
        rk = ruleset(
            rules, (rec.get("league") or {}).get("label"), world, first_shapes(pairs), started
        )
        name = str(rec.get("name") or t["folder"])
        summary = tune_summary(name, rk, rec, pairs)
        tune_list.append(summary)
        played = sum(1 for st in summary["steps"] for v in st["values"] if v["status"] == sc.PLAYED)
        played += sum(1 for k in pairs if k.startswith("confirm-"))
        # The screen its order came from, and that screen's replay version: the tune's record
        # names what the screen was played under that the tune is not (``cli.screen_differs``).
        read = (spec.get("screen") or {}).get("name")
        apart = (rec.get("screen") or {}).get("replay_version")
        read_rv = apart.get("screen") if isinstance(apart, Mapping) else spec.get("replay_version")
        runs.append(
            {
                "name": name,
                "kind": "tune",
                "ruleset": rk,
                "seasons": _seasons(world.get("seasons")),
                "confirm": spec.get("confirm"),
                "forecasters": _words(world.get("forecasters")),
                "paths": world.get("paths"),
                "seed": world.get("seed"),
                "tiers": sorted(
                    {str(st.get("tier")) for st in [summary["final"] or {}] if st.get("tier")}
                ),
                "code_sha": (rec.get("code_sha") or "")[:7] or None,
                "versions": {"tune": rec.get("tune_version"), "replay": spec.get("replay_version")},
                "screen": None if not read else {"name": read, "replay_version": read_rv},
                "pairs_done": played,
                "pairs_left": 1 if rec.get("left") else 0,
                "not_played": 0,
                "cleared": sum(1 for st in summary["steps"] if st["taken"]),
                "pieces": pieces,
                "hours": _hours(pieces),
                "audit": summary["audit"]
                | {
                    "level": PROBLEM
                    if summary["audit"]["breaches"] or summary["audit"]["voided"]
                    else OK
                },
                "status": summary["status"],
                "started_at": started,
                "hold_out": rec.get("hold_out"),
            }
        )
        by_rs[rk]["tunes"].append(name)

    # Written replays.
    for r in replays:
        rec = r["record"]
        rules = (rec.get("league") or {}).get("rules") or {}
        started = _iso(rec.get("started_at"))
        rk = ruleset(
            rules,
            (rec.get("league") or {}).get("label"),
            {},
            (rec.get("league") or {}).get("shapes"),
            started,
        )
        name = str(rec.get("name") or r["file"])
        breaches, voided = _audit(rec)
        specs = rec.get("specs") or {}
        runs.append(
            {
                "name": name,
                "kind": "replay",
                "design": rec.get("design"),
                "ruleset": rk,
                # A replay writes ``seasons`` and ``cells``; one written before them, ``season``
                # and ``forecasters``. Both are read.
                "seasons": _seasons(rec.get("seasons") if "seasons" in rec else rec.get("season")),
                "forecasters": _words(rec.get("forecasters"))
                if rec.get("forecasters")
                else ", ".join(
                    sorted({lab for by in (rec.get("cells") or {}).values() for lab in by})
                ),
                "paths": rec.get("paths"),
                "seed": rec.get("seed"),
                "tiers": sorted(
                    {
                        str(s.get("tier"))
                        for s in specs.values()
                        if isinstance(s, Mapping) and s.get("tier")
                    }
                ),
                "code_sha": (rec.get("code_sha") or "")[:7] or None,
                "versions": {"replay": rec.get("replay_version")},
                "pairs_done": 1,
                "pairs_left": 0,
                "not_played": 0,
                "cleared": None,
                "pieces": [
                    {
                        "started_at": started,
                        "finished_at": _iso(rec.get("finished_at")),
                        "played": 1,
                        "stopped": None,
                        "code_sha": (rec.get("code_sha") or "")[:7] or None,
                    }
                ],
                "hours": _hours([{"started_at": started, "finished_at": rec.get("finished_at")}]),
                "audit": {
                    "breaches": breaches,
                    "voided": voided,
                    "level": PROBLEM if breaches or voided else OK,
                },
                "status": "written",
                "started_at": started,
                "hold_out": rec.get("hold_out"),
                "look": (rec.get("confirmation") or {}).get("look"),
            }
        )
        by_rs[rk]["replays"].append(name)

    runs.sort(key=lambda x: (_t(x.get("started_at")), str(x["name"])))
    engine = engine_changes(notes)
    for run in runs:
        run["season_words"] = [season_words(t) for t in run["seasons"]]
        rv = (run.get("versions") or {}).get("replay")
        run["capability"] = capability_of(rv)
        run["behind_live"] = behind_live(run.get("started_at"), rv, engine)
        run["live_since"] = live_since(run.get("started_at"), rv, engine)
    by_name = {run["name"]: run for run in runs}
    timeline = _span(runs)

    # Rulesets, in the notes' order, else by their first run.
    keys = sorted(
        by_rs,
        key=lambda k: (
            notes_rs.get(k, {}).get("order", 10**6),
            _t(by_rs[k]["first"]),
            k,
        ),
    )
    # A ruleset with no screen and no tune is not listed on Overview or Checks: its runs stay
    # on Runs under its name. The listed come first, and take the first colours.
    listed = [k for k in keys if by_rs[k]["screens"] or by_rs[k]["tunes"]]
    keys = listed + [k for k in keys if k not in listed]
    rulesets = []
    shared_runs: dict[str, str] = {}
    for tone, rk in enumerate(keys):
        rs = by_rs[rk]
        mine = [x for x in runs if x["ruleset"] == rk]
        screens_here = [x for x in mine if x["kind"] == "screen"]
        latest = screens_here[-1]["name"] if screens_here else None
        if latest:
            shared_runs[rk] = latest
        baselines = [b for _, b in sorted(rs.get("baselines", []), key=lambda p: _t(p[0]))]
        baseline = next((b for b in reversed(baselines) if b is not None), None)
        if screens_here and baseline is None:
            lacks.append(
                f"ruleset {rk}: no played screen row sets nothing but its tier in both arms, "
                "so no baseline"
            )
        here = [r for r in rows if r["ruleset"] == rk and r["run"] == latest]
        card = _ruleset_card(rs, rk, tone, mine, here, baseline, notes_rs.get(rk, {}), tune_list)
        card["listed"] = rk in listed
        groups: dict[str, dict[str, Any]] = {}
        for x in mine:
            c = x.get("capability")
            key = c["id"] if c else ""
            groups.setdefault(key, {"capability": c, "runs": []})["runs"].append(x["name"])
        card["capabilities"] = list(groups.values())
        card["shifts"] = shifts_of(mine, rows, info, rs["measure"])
        for st in card["stages"]:
            src = by_name.get(st.get("run") or "")
            st["capability"] = None if src is None else src.get("capability")
        held = {}
        for st in card["stages"]:
            if st["capability"]:
                held.setdefault(st["capability"]["id"], (st["capability"], []))[1].append(
                    st["title"]
                )
        card["crosses"] = (
            None
            if len(held) < 2
            else "These figures were played on more than one capability: "
            + "; ".join(f"{_names(ts)} on {cap_words(c)}" for c, ts in held.values())
            + ". A gain across them is partly the simulator's change."
        )
        rulesets.append(card)

    # Knobs: every screen row, the domains, the rows two rulesets' latest screens share.
    domains = {
        run["name"]: {
            o: domain([r for r in rows if r["run"] == run["name"] and r["played"]], o)
            for o in OUTCOMES
        }
        for run in runs
        if run["kind"] == "screen"
    }
    shared = _shared(rows, shared_runs, {rs["key"]: rs["measure"] for rs in rulesets})

    # Checks in all, the seasons' ledger.
    tries = [r for r in rows if r["played"] and not r["did_nothing"]]
    all_luck = luck([r["diff"][r["measure"]]["ratio"] for r in tries])
    trace_list = sorted(
        (dict(t) for t in traces), key=lambda t: (-_t(t.get("made")), str(t.get("name")))
    )
    seasons = _ledger(runs, tune_list, looks, notes, hold_out, confirmation, trace_list)
    for t in trace_list:
        # A trace records the replay version it was played under from PR capabilities on; an
        # earlier one takes its source's, when its check found the code at that version.
        rv, how = t.get("replay_version"), "the trace"
        src = by_name.get(str(t.get("from") or ""))
        if rv is None and t.get("from_source") and src is not None:
            rv, how = (src.get("versions") or {}).get("replay"), "its source's record"
        t["capability"] = capability_of(rv)
        t["capability_from"] = how if t["capability"] else None
    for rs in rulesets:
        rs["checks"]["flags"] += _season_flags(
            rs["key"], runs, seasons, hold_out, looks, tune_list, trace_list
        )
        rs["checks"]["flags"] += capability_flags(
            [x for x in runs if x["ruleset"] == rs["key"]],
            rs["screen"],
            engine,
            notes is not None,
            by_name,
        )
        rs["checks"]["level"] = _worst(f["level"] for f in rs["checks"]["flags"])
    if not (notes or {}).get("seasons"):
        lacks.append(
            "a withheld season (kept for a tune's confirmation) is in no record: the seasons' "
            "roles come from the notes, and there are none"
        )
    return {
        "lab_version": LAB_VERSION,
        "outcomes": {k: dict(v) for k, v in OUTCOMES.items()},
        "levers": {k: dict(v) for k, v in LEVERS.items()},
        "tiers": dict(TIERS),
        "rulesets": rulesets,
        "knobs": {"rows": rows, "domains": domains, "shared": shared},
        "checks": {
            "all": all_luck,
            "comparisons": {
                "by_ruleset": {
                    rs["key"]: {
                        "screen_tries": rs["checks"]["luck"]["tries"],
                        "tune_values": sum(
                            1
                            for t in tune_list
                            if t["ruleset"] == rs["key"]
                            for st in t["steps"]
                            for v in st["values"]
                            if v["mean"] is not None
                        ),
                    }
                    for rs in rulesets
                },
                "screen_tries": all_luck["tries"],
            },
            "rule": LUCK,
        },
        "runs": runs,
        "timeline": timeline,
        "tunes": tune_list,
        "seasons": seasons,
        "traces": trace_list,
        "capabilities": _capabilities(engine, timeline, notes is not None, runs),
        "notes": None if notes is None else dict(notes),
        "viewer": {"title": "Season", "words": VIEWER, "note": VIEWER_NOTE},
        "screen_view": {"title": "Screen", "words": SCREEN_VIEW},
        "generated": dict(generated) | {"lacks": sorted(dict.fromkeys(lacks))},
    }


def _capabilities(
    engine: Sequence[Mapping[str, Any]],
    span: Mapping[str, str] | None,
    noted: bool,
    runs: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The simulator's capabilities as the page shows them: the log (each mark placed on the
    runs' time line), the live engine's changes (placed too), the capability now, the last
    update of any kind, what the simulator is behind live in, and ``earlier``: the runs whose
    figures are of an engine live has left (behind it when they started, or live changed
    since), with ``of`` the runs that record a version."""
    now = cap.current()
    latest = cap.latest()
    behind = [
        dict(e)
        for e in engine
        if e["taken_in"] is None or (now is not None and e["taken_in"] > (now.replay_version or 0))
    ]
    return {
        "log": [m.payload() | {"at": _place_on(m.date, span)} for m in cap.LOG],
        "engine": [dict(e) | {"at": _place_on(e["date"], span)} for e in engine],
        "current": None if now is None else now.payload(),
        "latest": None if latest is None else latest.payload(),
        "behind": behind,
        "earlier": [
            r["name"] for r in runs if (r.get("behind_live") or []) + (r.get("live_since") or [])
        ],
        "of": sum(1 for r in runs if r.get("behind_live") is not None),
        "kinds": dict(cap.KINDS),
        "noted": noted,
    }


def _span(runs: list[dict[str, Any]]) -> dict[str, str] | None:
    """Each piece's place on the runs' common time line, from 0 to 1; the line's two ends."""
    times = [
        t
        for run in runs
        for p in run["pieces"]
        for t in (_when(p["started_at"]), _when(p["finished_at"]))
        if t is not None
    ]
    if not times:
        return None
    t0, t1 = min(times), max(times)
    width = (t1 - t0).total_seconds() or 1.0
    for run in runs:
        for p in run["pieces"]:
            a, b = _when(p["started_at"]), _when(p["finished_at"])
            p["at"] = (
                None
                if a is None or b is None
                else [
                    (a - t0).total_seconds() / width,
                    (b - t0).total_seconds() / width,
                ]
            )
    return {"start": t0.isoformat(), "end": t1.isoformat()}


def _worst(levels: Any) -> str:
    got = set(levels)
    return PROBLEM if PROBLEM in got else WATCH if WATCH in got else OK


def _ruleset_card(
    rs: Mapping[str, Any],
    rk: str,
    tone: int,
    mine: Sequence[Mapping[str, Any]],
    here: Sequence[Mapping[str, Any]],
    baseline: Mapping[str, Any] | None,
    noted: Mapping[str, Any],
    tunes: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    m = rs["measure"]
    done = [r for r in here if r["played"] and not r["did_nothing"]]
    cleared = [r for r in done if r["survives"]]
    better = [r for r in cleared if r["diff"][m]["side"] == "better"]
    worse = [r for r in cleared if r["diff"][m]["side"] == "worse"]

    def z(r: Mapping[str, Any]) -> float:
        v = r["diff"][m]["z"]
        return -math.inf if v is None else v

    spark = [
        {
            "key": r["key"],
            "label": r["label"],
            "nudge": r["nudge"],
            "z": r["diff"][m]["z"],
            "cleared": r["survives"],
            "side": r["diff"][m]["side"],
        }
        for r in sorted(done, key=z, reverse=True)
    ]
    sized = [r for r in done if r["diff"][m]["ratio"] is not None]
    strongest = max(sized, key=lambda r: abs(r["diff"][m]["ratio"]), default=None)
    best_up = max(better, key=z, default=None)
    screens = [x for x in mine if x["kind"] == "screen"]
    latest = screens[-1] if screens else None
    base_cell = (baseline or {}).get("cells", [None])[0] if baseline else None
    stages = _stages(rs, rk, m, base_cell, best_up, tunes)
    tuned = [t["name"] for t in tunes if t["ruleset"] == rk]
    for st, run in zip(
        stages,
        (
            (baseline or {}).get("run"),
            (best_up or {}).get("run"),
            tuned[-1] if tuned else None,
            tuned[-1] if tuned else None,
        ),
        strict=True,
    ):
        st["run"] = None if st.get("ghost") else run
    luck_here = luck([r["diff"][m]["ratio"] for r in done])
    flags = _flags(rs, m, mine, here, done, cleared, better, worse, luck_here)
    flags[4:4] = [dict(f) for f in noted.get("flags", [])]
    world_line = None
    if latest is not None:
        tiers = latest["tiers"] or []
        world_line = {
            "seasons": [season_words(t) for t in latest["seasons"]],
            "paths": latest["paths"],
            "seed": latest["seed"],
            "tiers": [TIERS.get(t, t) for t in tiers],
            "forecasters": latest["forecasters"],
        }
    return {
        "key": rk,
        "name": noted.get("name") or ruleset_name(rs["rules"]),
        "named": "notes" if noted.get("name") else "rules",
        "tone": tone,
        "label": rs["label"],
        "rules": rs["rules"],
        "chips": chips(rs["rules"], rs["world"], rs["shapes"]),
        "teams": teams_of(rs["world"], rs["shapes"]),
        "measure": m,
        "runs": [x["name"] for x in mine],
        "screens": [x["name"] for x in screens],
        "screen": None if latest is None else latest["name"],
        "world": world_line,
        "baseline": baseline,
        "tried": {
            "done": len(done),
            "did_nothing": sum(1 for r in here if r["played"] and r["did_nothing"]),
            "not_played": sum(1 for r in here if not r["played"]),
            "cleared": len(cleared),
            "better": len(better),
            "worse": len(worse),
            "luck": len(done) * ONE_SE,
        },
        "spark": spark,
        "strongest": None
        if strongest is None
        else {
            "key": strongest["key"],
            "lever": strongest["lever"],
            "label": strongest["label"],
            "nudge": strongest["nudge"],
            "values": strongest["values"],
            "diff": strongest["diff"][m],
            "words": "a screen's row, not a recommendation",
        },
        "stages": stages,
        "checks": {"luck": luck_here, "flags": flags, "level": OK},
        "tunes": [t["name"] for t in tunes if t["ruleset"] == rk],
    }


def _stages(
    rs: Mapping[str, Any],
    rk: str,
    m: str,
    base: Mapping[str, Any] | None,
    best_up: Mapping[str, Any] | None,
    tunes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The four stages of "is the seat getting better?": the baseline, the strongest gain a
    screen saw upward, the tuned set on the searched season and on the season it confirmed on."""
    out = [
        {
            "tag": "played" if base else "not recorded",
            "id": "baseline",
            "title": "Current settings",
            "value": None if not base else base["outcomes"][m],
            "words": "the baseline"
            if base
            else "no played screen row sets nothing but its tier in both arms",
            "ghost": base is None,
        },
        {
            "tag": "unconfirmed" if best_up else "none",
            "id": "screen",
            "title": "Strongest single gain, screen",
            "value": None if not best_up or not best_up.get("b") else best_up["b"][m],
            "diff": None if not best_up else best_up["diff"][m],
            "label": None if not best_up else best_up["label"],
            "nudge": None if not best_up else best_up["nudge"],
            "words": "a screen's row, not a recommendation"
            if best_up
            else "no change cleared one SE upward",
            "ghost": best_up is None,
        },
    ]
    mine = [t for t in tunes if t["ruleset"] == rk]
    tune = mine[-1] if mine else None
    if tune is None or tune["final"] is None:
        out.append(
            {
                "tag": "not run" if tune is None else "in progress",
                "id": "searched",
                "title": "Tuned set, searched season",
                "value": None,
                "words": "what a tune finds on the seasons it searches",
                "ghost": True,
            }
        )
        out.append(
            {
                "tag": "not run" if tune is None else "in progress",
                "id": "unseen",
                "title": "Tuned set, unseen season",
                "value": None,
                "words": "a season no search has seen, played once: the figure that counts",
                "ghost": True,
            }
        )
        return out
    g = tune["gains"]
    out.append(
        {
            "tag": "searched",
            "id": "searched",
            "title": "Tuned set, searched season",
            "value": g["search"],
            "set": tune["final"]["set"],
            "tune": tune["name"],
            "words": (
                "the sum of the taken steps' gains on "
                + ", ".join(tune["searched"])
                + "; the steps share paths, so their SEs do not add"
                if g["search"]["moved"]
                else "no lever moved: the final set is the baseline"
            ),
            "ghost": False,
        }
    )
    conf = tune["confirmation"]
    run_gain = g["confirm"].get("run")
    out.append(
        {
            "tag": "played" if conf["status"] == "played" else "not played",
            "id": "unseen",
            "title": "Tuned set, unseen season",
            "value": None if run_gain is None else {"mean": run_gain["mean"], "se": run_gain["se"]},
            "static": g["confirm"].get("static"),
            "kept": g["kept"],
            "season": conf["season_words"],
            "verdict": conf["verdict"],
            "words": conf["status"] or "no confirmation",
            "ghost": run_gain is None,
        }
    )
    return out


def _flags(
    rs: Mapping[str, Any],
    m: str,
    mine: Sequence[Mapping[str, Any]],
    here: Sequence[Mapping[str, Any]],
    done: Sequence[Mapping[str, Any]],
    cleared: Sequence[Mapping[str, Any]],
    better: Sequence[Mapping[str, Any]],
    worse: Sequence[Mapping[str, Any]],
    lk: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """A ruleset's flags from its records (the seasons' two, the confirmation season and the
    hold-out, are added once the ledger is built)."""
    searched = [x for x in mine if x["kind"] in ("screen", "tune")]
    seasons = sorted({t for x in searched for t in x["seasons"]})
    seeds = sorted({x["seed"] for x in searched if x["seed"] is not None})
    tiers = sorted({r["tier"] for r in here if r["played"]})
    out = []
    if len(seasons) <= 1:
        out.append(
            {
                "level": WATCH,
                "title": "One season",
                "text": (
                    f"Every figure is from {season_words(seasons[0])}. A second season would show what carries over."
                    if seasons
                    else "No screen or search has played a season yet."
                ),
            }
        )
    else:
        out.append(
            {
                "level": OK,
                "title": "Seasons",
                "text": f"{len(seasons)} seasons searched: "
                + ", ".join(season_words(t) for t in seasons)
                + ".",
            }
        )
    paths = sorted({x["paths"] for x in searched if x["paths"] is not None})
    if len(seeds) <= 1:
        out.append(
            {
                "level": WATCH,
                "title": "One seed",
                "text": (
                    f"Seed {seeds[0]} draws one set of injuries and schedules across "
                    + " and ".join(str(p) for p in paths)
                    + " paths."
                    if seeds
                    else "No screen or search names a seed."
                ),
            }
        )
    else:
        out.append(
            {
                "level": OK,
                "title": "Seeds",
                "text": f"{len(seeds)} seeds: " + ", ".join(str(s) for s in seeds) + ".",
            }
        )
    if tiers and all(t != "exact" for t in tiers):
        out.append(
            {
                "level": WATCH,
                "title": "Fast tier only",
                "text": "The slow, exact tier has not played these rows.",
            }
        )
    elif tiers:
        n = len({r["key"] for r in here if r["played"] and r["tier"] == "exact"})
        out.append({"level": OK, "title": "Tiers", "text": f"{n} row(s) played on the exact tier."})
    if len({r["key"] for r in here if r["played"]}) > 1:
        out.append(
            {
                "level": WATCH,
                "title": "Shared baseline",
                "text": "Every pair is measured against the same baseline paths, so the rows are not independent tries.",
            }
        )
    mid = sum(
        1 for r in cleared if r["diff"][m]["ratio"] is not None and abs(r["diff"][m]["ratio"]) <= 2
    )
    out.append(
        {
            "level": WATCH if cleared and mid * 2 > len(cleared) else OK,
            "title": "Size of what cleared",
            "text": f"{mid} of the {len(cleared)} that cleared one SE are within two SE."
            if cleared
            else "Nothing cleared one SE.",
        }
    )
    strict = lk["bars"][2] if len(lk["bars"]) > 2 else None
    if strict is None:
        out.append({"level": OK, "title": "Strict bar", "text": "No try yet."})
    else:
        out.append(
            {
                "level": OK if strict["seen"] else WATCH,
                "title": "Strict bar",
                "text": (
                    f"{strict['seen']} clear the bar corrected for {lk['tries']} tries ({lk['bar']:.1f} SE): more than luck's {FAMILY:g}."
                    if strict["seen"]
                    else f"None clears the bar corrected for {lk['tries']} tries ({lk['bar']:.1f} SE)."
                ),
            }
        )
    few = min(len(better), len(worse))
    out.append(
        {
            "level": WATCH if len(cleared) >= 2 and few * 3 >= len(cleared) else OK,
            "title": "Direction",
            "text": (
                f"{len(better)} better, {len(worse)} worse among those that cleared. Luck alone would split them about evenly."
            ),
        }
    )
    played = [r for r in here if r["played"]]
    bad = sum(r["breaches"] + r["voided"] for r in {r["key"]: r for r in played}.values())
    out.append(
        {
            "level": PROBLEM if bad else OK,
            "title": "Audit",
            "text": f"{bad} breaches or voided paths across {len({r['key'] for r in played})} pairs.",
        }
    )
    return out


def _shared(
    rows: Sequence[Mapping[str, Any]], latest: Mapping[str, str], measures: Mapping[str, str]
) -> list[dict[str, Any]]:
    """The rows two or more rulesets' latest screens share, by key: each ruleset's values, side
    on its own measure and whether it cleared; ``signs``, whether the rows that did something
    point one way (agree), both ways (differ), or there is one or none; ``cleared``, the same
    among those that cleared one SE (agree, split, or None with fewer than two)."""
    by_key: dict[str, dict[str, Any]] = {}
    for r in rows:
        if latest.get(r["ruleset"]) != r["run"]:
            continue
        k = by_key.setdefault(
            r["key"], {"key": r["key"], "lever": r["lever"], "label": r["label"], "by_ruleset": {}}
        )
        m = measures[r["ruleset"]]
        k["by_ruleset"].setdefault(
            r["ruleset"],
            {
                "run": r["run"],
                "values": r["values"],
                "nudge": r["nudge"],
                "played": r["played"],
                "did_nothing": r.get("did_nothing", False),
                "side": r["diff"][m]["side"]
                if r["played"] and not r.get("did_nothing")
                else "none",
                "cleared": bool(r.get("survives")) and not r.get("did_nothing"),
            },
        )
    out = []
    for k in by_key.values():
        if len(k["by_ruleset"]) < 2:
            continue
        sides = {v["side"] for v in k["by_ruleset"].values() if v["side"] != "none"}
        k["signs"] = (
            "differ"
            if len(sides) > 1
            else "agree"
            if len(sides) == 1
            and sum(1 for v in k["by_ruleset"].values() if v["side"] != "none") > 1
            else "one or none"
        )
        live = [v["side"] for v in k["by_ruleset"].values() if v["cleared"]]
        k["cleared"] = None if len(live) < 2 else ("agree" if len(set(live)) == 1 else "split")
        out.append(k)
    return out


def _ledger(
    runs: Sequence[Mapping[str, Any]],
    tunes: Sequence[Mapping[str, Any]],
    looks: Sequence[Mapping[str, Any]],
    notes: Mapping[str, Any] | None,
    hold_out: int,
    confirmation: int,
    traces: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The seasons' ledger: for each season a record or the notes name, its role (the notes',
    else the hold-out's, a confirmation season's, a searched one's, else a replay's) and how
    many screens, searches, confirmations, written replays and traces (PR viewer) played it,
    and the ledger's looks at it."""
    noted = {s["season"]: s for s in (notes or {}).get("seasons") or []}
    seasons: set[int] = set(noted) | {hold_out, confirmation}
    count: dict[int, dict[str, int]] = {}

    def add(t: int, what: str) -> None:
        seasons.add(t)
        count.setdefault(
            t,
            {
                "screens": 0,
                "searches": 0,
                "confirmations": 0,
                "replays": 0,
                "looks": 0,
                "traces": 0,
            },
        )[what] += 1

    for run in runs:
        what = {"screen": "screens", "tune": "searches", "replay": "replays"}[run["kind"]]
        for t in run["seasons"]:
            add(t, what)
    confirms = set()
    for t in tunes:
        if t["confirmation"]["season"] is not None:
            confirms.add(int(t["confirmation"]["season"]))
            if t["confirmation"]["status"] == "played":
                add(int(t["confirmation"]["season"]), "confirmations")
    for line in looks:
        for t in _seasons(line.get("seasons")):
            add(t, "looks")
    for tr_ in traces:
        if isinstance(tr_.get("season"), int):
            add(int(tr_["season"]), "traces")
    out = []
    for t in sorted(seasons):
        c = count.get(
            t,
            {
                "screens": 0,
                "searches": 0,
                "confirmations": 0,
                "replays": 0,
                "looks": 0,
                "traces": 0,
            },
        )
        if t in noted:
            role, note, source = noted[t]["role"], noted[t].get("note"), "notes"
        elif t == hold_out:
            role, note, source = (
                "holdout",
                "the code's hold-out: never replayed, fitted or tuned on",
                "code",
            )
        elif t in confirms:
            role, note, source = "confirm", "a season a tune confirms on", "records"
        elif t == confirmation:
            role = "confirm"
            note = "the code's confirmation season: a written run that names it is a look on the ledger"
            source = "code"
        elif c["screens"] or c["searches"]:
            role, note, source = "search", None, "records"
        else:
            role, note, source = "replay", None, "records"
        out.append(
            {"season": t, "words": season_words(t), "role": role, "note": note, "from": source, **c}
        )
    return out


def _season_flags(
    rk: str,
    runs: Sequence[Mapping[str, Any]],
    seasons: Sequence[Mapping[str, Any]],
    hold_out: int,
    looks: Sequence[Mapping[str, Any]] = (),
    tunes: Sequence[Mapping[str, Any]] = (),
    traces: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """The two flags the seasons' ledger gives every ruleset (any ruleset's runs: a season seen
    is seen). The confirmation season's: a problem when a screen or a search played a season
    kept to confirm on; else a watch, naming them, when a written replay played one or a look on
    the confirmation ledger names one (a tune's own confirmation, the ledger's lines of design
    ``tune``, is what the season is kept for and is not one), or when this ruleset's tunes
    confirmed on it more than once (it was unseen only the first time; another ruleset's
    confirmation is not counted here) (the lead's decisions), or when a trace played one (PR
    viewer, the lead's decision); else ok. The hold-out's: a problem when it is in any record's
    seasons (a trace's included), a watch when a record names another hold-out."""
    confirm = [s for s in seasons if s["role"] == "confirm"]
    seen = [s for s in confirm if s["screens"] or s["searches"]]
    watched = []
    for s in confirm:
        reps = [r["name"] for r in runs if r["kind"] == "replay" and s["season"] in r["seasons"]]
        lks = [
            str(line.get("name") or f"look {line.get('look')}")
            for line in looks
            if line.get("design") != "tune"
            and s["season"] in _seasons(line.get("seasons", line.get("season")))
        ]
        again = [
            t["name"]
            for t in tunes
            if t["ruleset"] == rk
            and t["confirmation"]["status"] == "played"
            and t["confirmation"]["season"] is not None
            and int(t["confirmation"]["season"]) == s["season"]
        ]
        again = again if len(again) > 1 else []
        trs = [str(t.get("name")) for t in traces if t.get("season") == s["season"]]
        if not reps and not lks and not again and not trs:
            continue
        said = [f"{len(reps)} written replay(s) played it ({', '.join(reps)})"] if reps else []
        if trs:
            said.append(f"{len(trs)} trace(s) played it ({', '.join(trs)})")
        if lks:
            said.append(f"{len(lks)} look(s) on the confirmation ledger name it ({', '.join(lks)})")
        if again:
            said.append(
                f"this ruleset's tunes confirmed on it {len(again)} times ({', '.join(again)}): "
                "it was unseen only the first time"
            )
        watched.append(
            f"{s['words']} is kept to confirm on: " + "; ".join(said) + ". No screen or search "
            "has played it."
        )
    out = []
    if seen:
        out.append(
            {
                "level": PROBLEM,
                "title": "Confirmation season",
                "text": " and ".join(s["words"] for s in seen)
                + (" is" if len(seen) == 1 else " are")
                + " kept to confirm on, and a screen or a search has played it.",
            }
        )
    elif watched:
        out.append({"level": WATCH, "title": "Confirmation season", "text": " ".join(watched)})
    elif confirm:
        out.append(
            {
                "level": OK,
                "title": "Confirmation season",
                "text": " and ".join(s["words"] for s in confirm)
                + (" has" if len(confirm) == 1 else " have")
                + " not been played by any screen or search.",
            }
        )
    else:
        out.append(
            {
                "level": WATCH,
                "title": "Confirmation season",
                "text": "No season is named to confirm on.",
            }
        )
    played = [r["name"] for r in runs if hold_out in r["seasons"]]
    played += [str(t.get("name")) for t in traces if t.get("season") == hold_out]
    other = [r["name"] for r in runs if r.get("hold_out") not in (None, hold_out)]
    held = [
        s
        for s in seasons
        if s["role"] == "holdout"
        and s["season"] != hold_out
        and (s["screens"] or s["searches"] or s["replays"])
    ]
    if played or held:
        out.append(
            {
                "level": PROBLEM,
                "title": "Hold-out",
                "text": "A run played a held-out season: "
                + ", ".join(played + [s["words"] for s in held])
                + ".",
            }
        )
    elif other:
        out.append(
            {
                "level": WATCH,
                "title": "Hold-out",
                "text": "A record names another hold-out than the code's: "
                + ", ".join(other)
                + ".",
            }
        )
    else:
        out.append(
            {
                "level": OK,
                "title": "Hold-out",
                "text": f"{season_words(hold_out)} is in no run's seasons: never replayed, fitted or tuned on.",
            }
        )
    return out


__all__ = [
    "COUNTS",
    "FAMILY",
    "FINISHED",
    "IN_PLAY",
    "LAB_VERSION",
    "LEVERS",
    "LUCK",
    "NOTE_ITEMS",
    "NOTE_KEYS",
    "NOT_STARTED",
    "ONE_SE",
    "OUTCOMES",
    "PAUSED",
    "RIVAL_KEYS",
    "TWO_SE",
    "NotesError",
    "baseline_of",
    "build",
    "capability_of",
    "chips",
    "diff_of",
    "domain",
    "lever_label",
    "live_state",
    "luck",
    "notes_of",
    "rules_label",
    "ruleset_key",
    "ruleset_name",
    "screen_rows",
    "season_of",
    "season_words",
    "stat",
    "teams_of",
    "tune_summary",
]
