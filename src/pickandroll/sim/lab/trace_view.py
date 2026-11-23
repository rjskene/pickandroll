"""SEASON SIM (#172, PR viewer): a trace as the lab's Season tab draws it.

Pure. A trace's record (``sim/trace.py``, written by the ``trace`` command) goes in and one dict
comes out. Everything the tab shows that the trace does not hold as such is worked out here:

- a category's share of the matchup and who leads it, and the week's score so far;
- which roster spots differ between the arms, and the day's arrivals and departures;
- each knob chart's series, and which keys get one;
- the day's line in words.

The page script draws and animates; it works nothing out. :func:`summary` is one trace's line
in the list (``/api/traces``, the Runs page, the seasons' ledger); :func:`view` is the whole
trace as the tab plays it (``/api/trace/<name>``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from .. import screen as sc
from .. import trace as tr
from ..engine import PCT, total, won
from . import model as md

#: The trace's check as the ``trace`` command words it (``cli.CHECKED`` and the rest; a test
#: holds the two equal), with the level the page shows and the words it says.
CHECKED = "checked"
WORLD_ONLY = "world and seat only: the record keeps no path's outcome"
DRIFTED = "drifted"
UNCHECKED = "not from a record"
CHECKS: Mapping[str, tuple[str, str]] = {
    CHECKED: (md.OK, "checked: the path's outcomes equal its record's"),
    WORLD_ONLY: (
        md.WATCH,
        (
            "checked on its world, fit, versions, hash seed, seat and league shape only: its "
            "record keeps no path's outcome"
        ),
    ),
    DRIFTED: (
        md.PROBLEM,
        "drifted: something differs from its record, so this is not the path the record played",
    ),
    UNCHECKED: (
        md.WATCH,
        "not from a record: two arms named at the command line, nothing to check on",
    ),
}
#: A category as the page heads it; one not here shows its name.
CATS: Mapping[str, str] = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "threes": "3PM",
    "fg_pct": "FG%",
    "ft_pct": "FT%",
    "tov": "TO",
}
#: A knob key of the days' ``knobs`` as its chart heads it: a label and what it is. A key not
#: here is drawn under its own name, so a knob that becomes a schedule needs no change here.
KNOBS: Mapping[str, tuple[str, str]] = {
    "season_weight": (
        "Season weight, this week's games",
        "the season term's weight as the arm sets it",
    ),
    "season_weight_later": (
        "Season weight, the games after this week",
        "the weight times one less the stake times the week's stake level",
    ),
    "later_share": (
        "Share kept for the later weeks",
        "one less the stake times the week's stake level",
    ),
    "playoff_weight": (
        "Playoff weeks' weight",
        "how many times a bracket week's game counts in the season term",
    ),
    "stake": ("Week's stake", "how much the week's stake level bends the season weight"),
    "stake_level": ("Week's stake level", "the week's stake level, as the seat reads it or would"),
    "adds_week": ("Adds used this week", "against the week's cap"),
    "adds_today": ("Adds queued or claimed today", "against the day's cap"),
    "faab_left": ("FAAB dollars left", "against the budget"),
    "pace": ("Bid pace factor", "the pace's factor on a bid this morning; one is no change"),
}
#: A count and its cap, drawn on one chart; a cap gets no chart of its own.
CAPS: Mapping[str, str] = {
    "adds_week": "adds_week_cap",
    "adds_today": "adds_today_cap",
    "faab_left": "faab_budget",
}
#: A key drawn only when an arm reads it: the flag, a day's knob, that says the arm does. Where
#: neither arm reads it on any day, a line says it moves and is not read.
READ_BY: Mapping[str, str] = {"stake_level": "reads_stake"}
#: A whole-number key, drawn without decimals.
WHOLE = frozenset({"adds_week", "adds_today", "faab_left", *CAPS.values()})
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
#: The line the tab never drops (the model's, so the tab says it before a trace is read).
NOTE = md.VIEWER_NOTE


# --------------------------------------------------------------------------- small parts
def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _r(x: float | None, d: int = 3) -> float | None:
    return None if x is None else round(x, d)


def check_of(check: Mapping[str, Any] | None) -> dict[str, Any]:
    """The trace's check: its status as written, the level and words the page shows, and what
    differed (a drifted trace's)."""
    c = check or {}
    status = str(c.get("status") or "")
    level, words = CHECKS.get(status, (md.WATCH, f"a check the lab does not know: {status}"))
    return {
        "status": status,
        "level": level,
        "words": words,
        "drift": [str(x) for x in c.get("drift") or []],
    }


def short_name(name: Any) -> str:
    """A player's name as a chip shows it: the first name's initial and the rest."""
    parts = str(name or "").split()
    if len(parts) < 2:
        return " ".join(parts)
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def week_label(week: Mapping[str, Any], first_bracket: int | None) -> str:
    n = int(week["week"])
    if week.get("bracket") and first_bracket is not None:
        return f"PO{n - first_bracket + 1}"
    return f"W{n}"


def summary(name: str, rec: Mapping[str, Any]) -> dict[str, Any]:
    """One trace's line: its name, where it came from, its season and path, the pair's lever and
    values, the days the arms differ, its check, the code and when it was made, and the
    ruleset its league's rules make (the seasons' ledger counts it there)."""
    src = rec.get("source") or {}
    pair = rec.get("pair") or {}
    season = rec.get("season")
    rules = (rec.get("league") or {}).get("rules") or {}
    differ = rec.get("differ") or {}
    values = pair.get("values")
    return {
        "name": name,
        "form": src.get("form"),
        "from": src.get("name"),
        "row": src.get("row"),
        "season": season,
        "season_words": md.season_words(int(season)) if isinstance(season, int) else None,
        "forecaster": rec.get("forecaster"),
        "path": rec.get("path"),
        "seed": rec.get("seed"),
        "lever": pair.get("lever"),
        "label": md.lever_label(str(pair.get("lever"))) if pair.get("lever") else None,
        "nudge": pair.get("nudge"),
        "values": None
        if not isinstance(values, Mapping)
        else {k: sc.shown(values.get(k)) for k in tr.SIDES},
        "arms": {k: str((pair.get("arms") or {}).get(k, k)) for k in tr.SIDES},
        "differ_days": differ.get("count"),
        "first_differ": differ.get("first"),
        "check": check_of(rec.get("check")),
        "code_sha": (str(rec.get("code_sha") or ""))[:7] or None,
        "made": rec.get("finished_at"),
        "trace_version": rec.get("trace_version"),
        # PR capabilities: the replay version it was played under (version 2 traces), and
        # whether its check found the code at its source's version (the model then reads the
        # source's for a version 1 trace).
        "replay_version": rec.get("replay_version"),
        "from_source": (rec.get("check") or {}).get("status") in (CHECKED, WORLD_ONLY),
        "ruleset": md.ruleset_key(rules) if rules else None,
        "confirmation": rec.get("confirmation"),
    }


# --------------------------------------------------------------------------- the pair
def _flat(x: Any, at: str = "") -> dict[str, Any]:
    if isinstance(x, Mapping):
        out: dict[str, Any] = {}
        for k, v in x.items():
            out |= _flat(v, f"{at}.{k}" if at else str(k))
        return out
    return {at: x}


def _knob_name(key: str) -> str:
    return key.removeprefix("knobs.")


def pair_of(rec: Mapping[str, Any]) -> dict[str, Any]:
    """What differs between the arms: the lever and its values, every setting of the two specs
    A against B (the knobs, the bid rule, the tier, the rivals' view), differing first, and the
    ones the two share folded."""
    pair = rec.get("pair") or {}
    specs = pair.get("specs") or {}
    fa = {k: v for k, v in _flat(specs.get("a") or {}).items() if k != "name"}
    fb = {k: v for k, v in _flat(specs.get("b") or {}).items() if k != "name"}
    rows = []
    for k in sorted(set(fa) | set(fb)):
        name = _knob_name(k)
        rows.append(
            {
                "key": name,
                "label": md.lever_label(name),
                "a": sc.shown(fa.get(k)) if k in fa else "the default",
                "b": sc.shown(fb.get(k)) if k in fb else "the default",
                "differs": fa.get(k) != fb.get(k) or (k in fa) != (k in fb),
            }
        )
    values = pair.get("values")
    lever = pair.get("lever")
    return {
        "lever": lever,
        "label": md.lever_label(str(lever)) if lever else "no lever",
        "nudge": pair.get("nudge"),
        "values": None
        if not isinstance(values, Mapping)
        else {k: sc.shown(values.get(k)) for k in tr.SIDES},
        "arms": {k: str((pair.get("arms") or {}).get(k, k)) for k in tr.SIDES},
        "differ": [r for r in rows if r["differs"]],
        "same": [r for r in rows if not r["differs"]],
    }


# --------------------------------------------------------------------------- the matchup
def cat_value(totals: Mapping[str, Any], cat: str) -> float:
    """A category's value as a week is scored (``league.week_result``): a percentage from its
    makes and attempts, a count as it stands (none is 0)."""
    if cat in PCT:
        v = total(totals, cat)
        return 0.0 if v is None else float(v)
    return float(totals.get(cat, 0.0) or 0.0)


def lower_wins(cat: str) -> bool:
    """Whether the lower value wins ``cat``, by the engine's own rule."""
    return won(cat, 0.0, 1.0) == 1.0


def matchup(
    cats: Sequence[str], me: Mapping[str, Any] | None, them: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """The matchup as it stands: each category's share for the seat (past one half it leads;
    a category the lower value wins counts the opponent's share), who leads it (1, 0, a tie
    half), and the score so far, won-lost-tied. None with no opponent; in a points league (no
    categories) the shares and score are empty."""
    if me is None or them is None:
        return None
    share, lead = [], []
    for c in cats:
        a, b = cat_value(me, c), cat_value(them, c)
        s = 0.5 if a + b <= 0 else (b if lower_wins(c) else a) / (a + b)
        share.append(round(s, 3))
        w = won(c, a, b)
        lead.append(0.5 if w is None else w)
    score = [lead.count(1.0), lead.count(0.0), lead.count(0.5)]
    return {"share": share, "lead": lead, "score": score}


# --------------------------------------------------------------------------- the day's words
class _Names:
    def __init__(self, players: Mapping[str, Any]) -> None:
        self.players = players

    def __call__(self, pid: Any) -> str:
        if pid is None:
            return "nobody"
        p = self.players.get(str(pid)) or {}
        return str(p.get("name") or f"player {pid}")


def _move_words(m: Sequence[Any], name: _Names) -> str:
    add, drop = (list(m) + [None, None])[:2]
    if add is not None and drop is not None:
        return f"add {name(add)} for {name(drop)}"
    if add is not None:
        return f"add {name(add)}"
    return f"drop {name(drop)}"


def day_line(d: Mapping[str, Any], name: _Names) -> list[str]:
    """What the arm did on the day, in words: the tier and its solves, the set, the plan, what
    was queued and claimed, what landed or was decided, what was lost, and what the queue left
    out with the rule that stopped it."""
    out = []
    tier = md.TIERS.get(str(d.get("tier")), str(d.get("tier") or "no tier"))
    solves = int(d.get("solves") or 0)
    out.append(
        f"{tier}: "
        + (f"{solves} solve{'s' if solves != 1 else ''}" if solves else "no solve today")
    )
    moves = d.get("set") or []
    if moves:
        out.append("the set: " + "; ".join(_move_words(m, name) for m in moves))
    elif solves:
        out.append("found nothing to do")
    if d.get("held"):
        out.append(
            "held slots: " + "; ".join(f"{name(h[0])} to {h[1]}" for h in d["held"] if len(h) > 1)
        )
    if d.get("plan_leads"):
        out.append("the week plan led")
    if d.get("past_guard"):
        out.append("a set the season guard would refuse (the guard is off)")
    if d.get("union_refused"):
        out.append(f"the guard's list refused {d['union_refused']}")
    if d.get("queued"):
        out.append("queued: " + "; ".join(_move_words(m, name) for m in d["queued"]))
    for c in d.get("claims") or []:
        out.append(
            f"claim: {_move_words([c.get('add'), c.get('drop')], name)}"
            + (f", ${c['bid']}" if c.get("bid") is not None else "")
        )
    if d.get("landed"):
        out.append("landed: " + "; ".join(_move_words(m, name) for m in d["landed"]))
    for c in d.get("cleared") or []:
        out.append(
            f"claim {'won' if c.get('won') else 'lost'}: {name(c.get('add'))}"
            + (f", ${c['bid']}" if c.get("bid") is not None else "")
        )
    for m in d.get("lost") or []:
        out.append(f"lost: {_move_words(m, name)}")
    for u in d.get("unqueued") or []:
        out.append(f"not queued: {_move_words(u[:2], name)} ({u[2] if len(u) > 2 else 'no rule'})")
    return out


def _decided(d: Mapping[str, Any]) -> tuple[Any, ...]:
    """A day's decision as the trace's ``differ`` compares it."""
    return (
        d.get("set") or [],
        d.get("queued") or [],
        [(c.get("add"), c.get("drop")) for c in d.get("claims") or []],
    )


def _did(d: Mapping[str, Any], rides: Sequence[Mapping[str, Any]]) -> bool:
    return bool(d.get("set") or d.get("queued") or d.get("claims") or rides)


# --------------------------------------------------------------------------- the roster
def _moves_of(decision: Mapping[str, Any] | None) -> list[tuple[Any, Any]]:
    """The day's moves that changed the roster, add and drop: the landed adds, then the claims
    won that day."""
    d = decision or {}
    out = [(m[0], m[1]) for m in d.get("landed") or [] if len(m) >= 2]
    out += [(c.get("add"), c.get("drop")) for c in d.get("cleared") or [] if c.get("won")]
    return out


def roster_spots(days: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each day's roster in a steady order of spots (a player keeps his spot while he stays; one
    who arrives takes a spot one who left gave up), with the day's arrivals (``in``, the spot,
    and whom he took it from) and the players gone with no one in their spot. An arrival takes
    the spot of the player the day's own move dropped for him (a landed add, a claim won);
    only what no move names is paired by order. The first day's roster before is its roster
    less that day's landed adds, plus their drops, so a move that lands on day one rides too."""
    out: list[dict[str, Any]] = []
    order: list[Any] = []
    for i, day in enumerate(days):
        now = [r[0] for r in day.get("roster") or []]
        slot = {r[0]: r[1] for r in day.get("roster") or []}
        here = set(now)
        moves = [(a, b) for a, b in _moves_of(day.get("decision")) if a in here]
        if i == 0:
            back = {a: b for a, b in moves if b is not None and b not in here}
            order = [back.get(p, p) for p in now]
        kept = [p if p in here else None for p in order]
        freed = [j for j, p in enumerate(kept) if p is None]
        new = [p for p in now if p not in set(order)]
        rides: list[dict[str, Any]] = []
        took: dict[Any, int] = {}
        for add, drop in moves:
            if add in new and add not in took and drop in order:
                j = order.index(drop)
                if j in freed:
                    took[add] = j
                    freed.remove(j)
        rest = [p for p in new if p not in took]
        for p in rest:
            if freed:
                took[p] = freed.pop(0)
        for p in new:
            if p in took:
                kept[took[p]] = p
                rides.append({"in": p, "out": order[took[p]], "spot": took[p]})
            else:
                kept.append(p)
                rides.append({"in": p, "out": None, "spot": len(kept) - 1})
        gone = [order[j] for j in freed]
        order = [p for p in kept if p is not None]
        spot_of = {p: j for j, p in enumerate(order)}
        for r in rides:
            r["spot"] = spot_of[r["in"]]
        out.append({"order": order, "slot": slot, "rides": rides, "gone": gone})
    return out


# --------------------------------------------------------------------------- the knobs
def _series(days: Sequence[Mapping[str, Any]], key: str) -> list[float | None]:
    return [_num((d.get("knobs") or {}).get(key)) for d in days]


def _fmt(x: float | None, whole: bool) -> str:
    """A knob's value in words: whole, or to three significant digits without an exponent, so
    a small fraction never reads as zero (the ticks and the legend say the same)."""
    if x is None:
        return "none"
    if whole or x == 0 or abs(x) >= 1000:
        return f"{x:.0f}"
    t = f"{x:.{max(0, 2 - math.floor(math.log10(abs(x))))}f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _say(xs: Sequence[float | None], caps: Sequence[float | None] | None, whole: bool) -> list[str]:
    """A chart's legend at each day: the value, and "of" the cap's when the chart has one."""
    return [
        _fmt(x, whole) + ("" if not caps or caps[i] is None else " of " + _fmt(caps[i], whole))
        for i, x in enumerate(xs)
    ]


def knob_charts(
    da: Sequence[Mapping[str, Any]], db: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The knobs' charts, the knobs constant all season, and the knobs that move but no arm
    reads. A key of the days' ``knobs`` gets a chart when it changes through the season in
    either arm's own series (the lead's decision: charts are for what moves); one the same every
    day in each arm is a constant, its two values said in one row, marked when the arms differ.
    A key of :data:`READ_BY` gets a chart only when an arm reads it on some day. A cap is drawn
    on its count's chart, never alone; a key that is not a number gets none. Each chart is one
    axis (its low and high), both arms' series by day, the cap's when it has one, and the words
    the legend says at each day (``say``), the ticks' own."""
    keys: list[str] = []
    for d in (*da, *db):
        for k, v in (d.get("knobs") or {}).items():
            if k not in keys and _num(v) is not None:
                keys.append(k)
    caps = set(CAPS.values())

    def reads(flag: str) -> bool:
        return any(bool((d.get("knobs") or {}).get(flag)) for d in (*da, *db))

    charts, constant, unread = [], [], []
    for k in keys:
        if k in caps:
            continue
        a, b = _series(da, k), _series(db, k)
        differs = any(x != y for x, y in zip(a, b, strict=False)) or len(a) != len(b)
        moves = len({x for x in a if x is not None}) > 1 or len({x for x in b if x is not None}) > 1
        label, words = KNOBS.get(k, (k, ""))
        whole = k in WHOLE
        if not moves:
            va = next((x for x in a if x is not None), None)
            vb = next((x for x in b if x is not None), None)
            constant.append(
                {
                    "key": k,
                    "label": label,
                    "a": _fmt(va, whole),
                    "b": _fmt(vb, whole),
                    "differs": differs,
                }
            )
            continue
        if k in READ_BY and not reads(READ_BY[k]):
            unread.append(
                {
                    "key": k,
                    "label": label,
                    "words": "moves through the season; neither arm reads it",
                }
            )
            continue
        cap = None
        if k in CAPS:
            ca, cb = _series(da, CAPS[k]), _series(db, CAPS[k])
            if any(x is not None for x in (*ca, *cb)):
                cap = {"a": ca, "b": cb, "same": ca == cb}
        seen = [x for x in (*a, *b, *(cap["a"] + cap["b"] if cap else [])) if x is not None]
        lo, hi = (min(seen), max(seen)) if seen else (0.0, 1.0)
        if lo > 0 and (whole or k in CAPS):
            lo = 0.0

        charts.append(
            {
                "key": k,
                "label": label,
                "words": words,
                "a": a,
                "b": b,
                "cap": cap,
                "lo": lo,
                "hi": hi,
                "ticks": [[lo, _fmt(lo, whole)], [hi, _fmt(hi, whole)]],
                "say": {
                    "a": _say(a, cap["a"] if cap else None, whole),
                    "b": _say(b, cap["b"] if cap else None, whole),
                },
                "differs": differs,
                "moves": moves,
            }
        )
    return charts, constant, unread


# --------------------------------------------------------------------------- the view
def _place(rows: Sequence[Mapping[str, Any]], seat: int) -> dict[str, Any] | None:
    """The seat's place and record in a standings table; None before any week is played."""
    if not rows or all(not (r.get("wins") or r.get("losses") or r.get("ties")) for r in rows):
        return None
    for r in rows:
        if r.get("team") == seat:
            return {
                "rank": r.get("rank"),
                "record": [r.get("wins") or 0, r.get("losses") or 0, r.get("ties") or 0],
            }
    return None


def _bracket_words(end: Mapping[str, Any] | None, seat: int) -> list[str]:
    """The seat's bracket in words: its seed, each round it played or had a bye in, and the
    champion. A round's matchups are seeds (higher seed, lower seed, winner's seed), as
    ``league.Playoffs`` keeps them; ``seeds`` maps a seed to its team; the champion is a team."""
    if not end:
        return []
    b = end.get("bracket") or {}
    seeds = {int(k): int(t) for k, t in (b.get("seeds") or {}).items()}
    mine = next((s for s, t in seeds.items() if t == seat), None)
    out = [f"seeded {mine}" if mine is not None else "missed the playoffs"]
    if mine is not None:
        for i, rd in enumerate(b.get("rounds") or []):
            m = next((m for m in rd if len(m) >= 3 and mine in (m[0], m[1])), None)
            if m is None:
                out.append(f"round {i + 1}: a bye")
                continue
            other = seeds.get(m[1] if m[0] == mine else m[0])
            won = m[2] == mine
            out.append(f"round {i + 1}: {'won' if won else 'lost'} against team {other}")
            if not won:
                break
    if b.get("champion") is not None:
        out.append(
            "champion: " + ("the seat" if b["champion"] == seat else f"team {b['champion']}")
        )
    return out


def view(name: str, rec: Mapping[str, Any]) -> dict[str, Any]:
    """The trace as the Season tab plays it (the module's docstring says what is worked out)."""
    seat = int(rec.get("seat") or 0)
    cats = [str(c) for c in rec.get("cats") or []]
    players = rec.get("players") or {}
    names = _Names(players)
    weeks_tab = rec.get("weeks") or []
    first_bracket = next((int(w["week"]) for w in weeks_tab if w.get("bracket")), None)
    labels = {int(w["week"]): week_label(w, first_bracket) for w in weeks_tab}
    arms = rec.get("arms") or {}
    days = {s: list((arms.get(s) or {}).get("days") or []) for s in tr.SIDES}
    blocks = {s: list((arms.get(s) or {}).get("weeks") or []) for s in tr.SIDES}
    ends = {s: (arms.get(s) or {}).get("end") for s in tr.SIDES}
    dates = [d["date"] for d in days["a"]]
    by_date = {s: {d["date"]: d for d in days[s]} for s in tr.SIDES}
    spots = {s: roster_spots(days[s]) for s in tr.SIDES}
    spot_at = {
        s: {d["date"]: sp for d, sp in zip(days[s], spots[s], strict=True)} for s in tr.SIDES
    }
    finals = {s: {int(b["week"]): b.get("final") for b in blocks[s]} for s in tr.SIDES}

    out_days = []
    for i, t in enumerate(dates):
        da = by_date["a"].get(t) or {}
        wk = int(da.get("week") or 0)
        day = {
            "date": t,
            "week": wk,
            "label": labels.get(wk, f"W{wk}"),
            "dow": DAYS[date.fromisoformat(t).weekday()],
            "bracket": bool(da.get("bracket")),
        }
        sides = {}
        for s in tr.SIDES:
            d = by_date[s].get(t)
            if d is None:
                sides[s] = None
                continue
            sp = spot_at[s][t]
            other = by_date["b" if s == "a" else "a"].get(t)
            theirs = {r[0] for r in (other or {}).get("roster") or []}
            fresh = {r["in"] for r in sp["rides"]}
            m = d.get("matchup") or {}
            nxt = by_date[s].get(dates[i + 1]) if i + 1 < len(dates) else None
            if nxt is not None and nxt.get("week") == d.get("week"):
                pm_me, pm_them = (
                    (nxt.get("matchup") or {}).get("me"),
                    (nxt.get("matchup") or {}).get("them"),
                )
            else:
                f = finals[s].get(int(d.get("week") or 0)) or {}
                pm_me, pm_them = f.get("me"), f.get("them")
            dec = d.get("decision") or {}
            sides[s] = {
                "roster": [
                    [p, sp["slot"].get(p), other is not None and p not in theirs, p in fresh]
                    for p in sp["order"]
                ],
                "rides": sp["rides"],
                "gone": sp["gone"],
                "line": day_line(dec, names),
                "did": _did(dec, sp["rides"]),
                "opponent": m.get("opponent"),
                "am": matchup(cats, m.get("me"), m.get("them")),
                "pm": matchup(cats, pm_me, pm_them),
                "adds": [
                    _num((d.get("knobs") or {}).get("adds_week")),
                    _num((d.get("knobs") or {}).get("adds_week_cap")),
                ],
            }
        a, b = by_date["a"].get(t), by_date["b"].get(t)
        same = (
            a is not None
            and b is not None
            and _decided(a.get("decision") or {}) == _decided(b.get("decision") or {})
            and [r["in"] for r in sides["a"]["rides"]] == [r["in"] for r in sides["b"]["rides"]]
        )
        either = any(sides[s] is not None and sides[s]["did"] for s in tr.SIDES)
        day["sides"] = sides
        day["same"] = same
        day["compare"] = (
            "no move in either arm today"
            if same and not either
            else "the same decision in both arms today"
            if same
            else "the arms decide differently today"
        )
        out_days.append(day)

    index = {t: i for i, t in enumerate(dates)}
    weeks = []
    for w in weeks_tab:
        n = int(w["week"])
        days_in = [i for i, t in enumerate(dates) if out_days[i]["week"] == n]
        row: dict[str, Any] = {
            "week": n,
            "label": labels[n],
            "bracket": bool(w.get("bracket")),
            "first": days_in[0] if days_in else None,
            "last": days_in[-1] if days_in else None,
        }
        for s in tr.SIDES:
            blk = next((b for b in blocks[s] if int(b["week"]) == n), None)
            res = (blk or {}).get("result")
            row[s] = {
                "opponent": (blk or {}).get("opponent"),
                "outcome": None if not res else res.get("outcome"),
                "score": None if not res else [res.get("won"), res.get("lost"), res.get("tied")],
                "points": None if not res else res.get("points"),
                "before": _place((blk or {}).get("standings_before") or [], seat),
            }
        weeks.append(row)

    playoff_teams = None
    for s in tr.SIDES:
        b = (ends[s] or {}).get("bracket") or {}
        if b.get("seeds"):
            playoff_teams = len(b["seeds"])
            break
    end = {}
    for s in tr.SIDES:
        e = ends[s] or {}
        o = e.get("outcome") or {}
        end[s] = {
            "rank": o.get("rank"),
            "made_playoffs": o.get("made_playoffs"),
            "title": o.get("title"),
            "record": o.get("record"),
            "bracket": _bracket_words(e, seat),
            "breaches": len(e.get("breaches") or []),
        }

    charts, flat, unread = knob_charts(days["a"], days["b"])
    differ = rec.get("differ") or {}
    jumps = [
        {"day": index[t], "label": f"{out_days[index[t]]['label']} {out_days[index[t]]['dow']}"}
        for t in differ.get("days") or []
        if t in index
    ]
    league = rec.get("league") or {}
    return {
        "name": name,
        "summary": summary(name, rec),
        "check": check_of(rec.get("check")),
        "seat": seat,
        "teams": len(rec.get("teams") or []),
        "league": {"label": league.get("label"), "shape": league.get("shape_label")},
        "scoring": rec.get("scoring"),
        "points_league": not cats,
        "cats": [{"key": c, "label": CATS.get(c, c), "lower": lower_wins(c)} for c in cats],
        "players": {
            str(k): {
                "name": str(p.get("name") or k),
                "short": short_name(p.get("name")) or str(k),
                "team": p.get("team"),
                "positions": list(p.get("positions") or []),
            }
            for k, p in players.items()
        },
        "pair": pair_of(rec),
        "days": out_days,
        "weeks": weeks,
        "jumps": jumps,
        "differ": {"count": differ.get("count"), "first": index.get(differ.get("first"))},
        "charts": charts,
        "flat": flat,
        "unread": unread,
        "playoff_teams": playoff_teams,
        "end": end,
        "outcomes": rec.get("outcomes"),
        "note": NOTE,
    }


__all__ = [
    "CAPS",
    "CATS",
    "CHECKED",
    "CHECKS",
    "DRIFTED",
    "KNOBS",
    "NOTE",
    "UNCHECKED",
    "WORLD_ONLY",
    "cat_value",
    "check_of",
    "day_line",
    "knob_charts",
    "lower_wins",
    "matchup",
    "pair_of",
    "roster_spots",
    "short_name",
    "summary",
    "view",
]
