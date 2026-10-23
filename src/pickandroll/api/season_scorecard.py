"""The Monday scorecard (#126, docs/ADD_DROP.md "Scorecard"): ``GET /seasons/{league}/scorecard``,
a league's recorded weeks against what the decision log projected for them, and
``GET /seasons/scorecard``, every league's week with the odds' calibration pooled over the public
leagues, and the week as markdown for the AUTOPILOT tracker (#127).

The weeks are the weekly recorder's (#97), the projections the decision log's (#125), scored by
``season.scorecard``. My moves of a week are its record's transactions (for a week recorded before
the record kept them, the season's transactions page, which may have lost the oldest), each
matched to the entry logged before it (``season.decisions``). A move made as recommended carries
the entry's projection of it in value units; its realized value, from the box scores of the games
the two players played, is not computed yet: every move is counted unscored.

The private league is scored on its own and never pooled: its moves are suggestions only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from ..season import Season
from ..season import decisions as dl
from ..season import scorecard as sc
from ..season.state import Transaction
from .season_decisions import TRANSACTIONS_TZ, _names

#: The system scored by default: the one the routines solve with.
SYSTEM = "bbm"
KINDS = (dl.AS_RECOMMENDED, dl.DIFFERENTLY, dl.NOT_RECOMMENDED, dl.NO_ENTRY)
#: Until the box scores are read (the second part of #126).
UNSCORED = (
    "The moves are not scored yet: their realized value needs the box scores of the games the "
    "players played."
)
_KIND_WORDS = {
    dl.AS_RECOMMENDED: "as recommended",
    dl.DIFFERENTLY: "differently",
    dl.NOT_RECOMMENDED: "not recommended",
    dl.NO_ENTRY: "no entry",
}


# --------------------------------------------------------------------------- one league
def week_moves(record: Mapping[str, Any], me: int, season: Season | None = None) -> list[dl.Made]:
    """My moves of ``record``'s week, oldest first: the record's transactions, or the season's
    page for a record without them."""
    week = sc.week_of(record)
    rows = record.get("transactions")
    if rows is not None:
        transactions = [Transaction.from_dict(r) for r in rows]
    else:
        transactions = list(season.transactions) if season is not None else []
    # Every day of the week resolves against its last; a later row resolves to the year before.
    made = dl.moves_made(transactions, me, week.end, TRANSACTIONS_TZ)
    shown = [m for m in made if m.day is not None and week.start <= m.day <= week.end]
    return sorted(
        shown, key=lambda m: (m.day, m.at or datetime.min.replace(tzinfo=TRANSACTIONS_TZ))
    )


def logged_move(entries: Sequence[Mapping[str, Any]], match: Mapping[str, Any]) -> dict | None:
    """The entry's own record of a move made as recommended: the set it came from, its gain on
    each horizon as the solve priced it and its projection in value units; None for any other
    match, or an entry logged before it kept them."""
    if match.get("kind") != dl.AS_RECOMMENDED or match.get("move") is None:
        return None
    entry = next((e for e in entries if e["id"] == match["entry"]), None)
    want = (match["move"]["add"], match["move"]["drop"])
    for s in (entry or {}).get("sets") or []:
        for m in s.get("moves") or []:
            if (m.get("add"), m.get("drop")) == want and m.get("value") is not None:
                return {"set": s["key"], "gain": m.get("gain"), "value": m["value"]}
    return None


def move_rows(
    record: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    me: int,
    season: Season | None = None,
) -> list[dict[str, Any]]:
    """My moves of the week, each with its match and the entry's projection of it (for a move
    made as recommended); ``realized`` stays None until the box scores are read."""
    out = []
    for m in week_moves(record, me, season):
        match = dl.match(m, entries)
        out.append(
            {
                **m.to_dict(),
                "match": match,
                "projected": logged_move(entries, match),
                "realized": None,
            }
        )
    return out


def moves_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The moves of some weeks: how many, by match, how many the log projected and their
    projected value summed on each horizon, and how many are scored (none until the box
    scores are read)."""
    rows = list(rows)
    projected = [r["projected"] for r in rows if r.get("projected")]
    sums: dict[str, float] = {}
    for p in projected:
        for key, h in (p["value"].get("horizons") or {}).items():
            if h.get("value") is not None:
                sums[key] = round(sums.get(key, 0.0) + h["value"], 4)
    scored = sum(1 for r in rows if r.get("realized") is not None)
    return {
        "made": len(rows),
        **{kind: sum(1 for r in rows if r["match"]["kind"] == kind) for kind in KINDS},
        "near": sum(1 for r in rows if r["match"].get("near")),
        "projected": len(projected),
        "projected_value": sums,
        "realized_value": None,
        "scored": scored,
        "unscored": len(rows) - scored,
    }


def league_payload(
    league: str,
    season: Season,
    is_public: bool,
    records: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    system: str = SYSTEM,
    week: int | None = None,
) -> dict[str, Any]:
    """A league's scorecard: its week (``week``, by default the last recorded) and every
    recorded week to it, each against the projection, the season to date, the odds'
    calibration over its weeks, and the names of the players its moves name."""
    me = season.settings.my_team_id
    base = {"league": league, "public": is_public, "system": system}
    shown = [r for r in records if week is None or int(r["week"]) <= week]
    if me is None:
        return {**base, "status": "no_team", "week": week, "card": None, "weeks": []}
    if not shown or (week is not None and int(shown[-1]["week"]) != week):
        return {**base, "status": "not_recorded", "week": week, "card": None, "weeks": []}
    cards = [sc.week_card(r, entries, me, system, move_rows(r, entries, me, season)) for r in shown]
    names = _names(season)
    for r in shown:
        for t in r.get("transactions") or []:
            names[int(t["player"]["yahoo_id"])] = t["player"]["name"]
    ids = {k for c in cards for m in c["moves"] for k in (m["add"], m["drop"]) if k is not None}
    card = cards[-1]
    return {
        **base,
        "status": "recorded",
        "week": card["week"],
        "card": card,
        "weeks": cards,
        "to_date": {
            **sc.to_date(cards),
            "moves": moves_summary(m for c in cards for m in c["moves"]),
        },
        "calibration": sc.calibration(cards),
        "players": {str(k): names[k] for k in sorted(ids) if k in names},
    }


# --------------------------------------------------------------------------- every league
def pooled(payloads: Sequence[Mapping[str, Any]], week: int) -> dict[str, Any]:
    """The public leagues' odds against their results: ``week``'s over the leagues that
    projected it (those that did not are named), and the season to it over every projected
    week."""
    public = [p for p in payloads if p["public"] and p.get("status") == "recorded"]
    this = [p for p in public if p["card"]["week"] == week]
    scored = [p for p in this if p["card"]["projected"] and p["card"]["actual"]]
    return {
        "week": {
            "leagues": len(scored),
            "left_out": [p["league"] for p in this if p not in scored],
            "not_recorded": [p["league"] for p in payloads if p["public"] and p not in this],
            **sc.calibration(p["card"] for p in scored),
        },
        "to_date": {
            "leagues": sum(1 for p in public if sc.scored(p["weeks"])),
            **sc.calibration(c for p in public for c in p["weeks"]),
        },
    }


def all_payload(
    payloads: Sequence[Mapping[str, Any]],
    week: int | None,
    skipped: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Every league's scorecard of ``week`` (by default the last any league recorded), the
    public leagues' odds pooled, the private league apart, and the week as markdown."""
    if week is None:
        weeks = [p["week"] for p in payloads if p.get("status") == "recorded"]
        week = max(weeks, default=None)
    if week is None:
        out = {"week": None, "leagues": list(payloads), "pooled": None, "skipped": list(skipped)}
        return {**out, "markdown": "## Scorecard\n\nNo week is recorded yet.\n"}
    shown = [_at_week(p, week) for p in payloads]
    pool = pooled(shown, week)
    return {
        "week": week,
        "leagues": shown,
        "pooled": pool,
        "skipped": list(skipped),
        "markdown": markdown(week, shown, pool, skipped),
    }


def _at_week(payload: Mapping[str, Any], week: int) -> dict[str, Any]:
    """A league's scorecard cut to ``week``: not recorded when its weeks stop before it."""
    weeks = [c for c in payload.get("weeks") or [] if c["week"] <= week]
    if payload.get("status") != "recorded" or not weeks or weeks[-1]["week"] != week:
        status = payload.get("status") if payload.get("status") != "recorded" else "not_recorded"
        return {**payload, "status": status, "week": week, "card": None, "weeks": weeks}
    if weeks == payload["weeks"]:
        return dict(payload)
    moves = moves_summary(m for c in weeks for m in c["moves"])
    return {
        **payload,
        "week": week,
        "card": weeks[-1],
        "weeks": weeks,
        "to_date": {**sc.to_date(weeks), "moves": moves},
        "calibration": sc.calibration(weeks),
    }


# --------------------------------------------------------------------------- the markdown
def _pct(x: float | None) -> str:
    return "-" if x is None else f"{round(100 * x)}%"


def _num(x: float | None, digits: int = 1) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _result(card: Mapping[str, Any]) -> str:
    actual = card.get("actual")
    if not actual:
        return "-"
    res = actual["result"]
    if card.get("scoring") == "points":
        return f"{res['outcome']} {_num(res.get('points'))}-{_num(res.get('against'))}"
    return f"{res['outcome']} {res['won']}-{res['lost']}-{res['tied']}"


def _row(p: Mapping[str, Any]) -> str:
    card = p.get("card")
    if not card:
        return f"| {p['league']} | not recorded | | | | |"
    proj = card.get("projected")
    projected = "-"
    if proj:
        projected = f"{_pct(proj['matchup'])} to win"
        if card.get("scoring") != "points":
            projected += f", {_num(proj['expected'])} categories"
    cats = "-"
    if card.get("actual") and card["actual"].get("categories") is not None:
        cats = _num(card["actual"]["categories"])
    st = card.get("standing") or {}
    standing = "-"
    if st.get("rank"):
        standing = f"{_ordinal(st['rank'])} of {st['teams']}" + (
            f", {st['record']}" if st.get("record") else ""
        )
    moves = len(card["moves"])
    recommended = sum(1 for m in card["moves"] if m["match"]["kind"] == dl.AS_RECOMMENDED)
    made = f"{moves} ({recommended} as recommended)" if moves else "none"
    return f"| {p['league']} | {projected} | {_result(card)} | {cats} | {standing} | {made} |"


def _buckets(cal: Mapping[str, Any]) -> str:
    parts = [
        f"{_pct(b['from'])}-{_pct(b['to'])}: {b['count']} at {_pct(b['odds'])}, won {_pct(b['won'])}"
        for b in cal["buckets"]
        if b["count"]
    ]
    return "; ".join(parts) if parts else "no category projected"


def _moves_line(p: Mapping[str, Any]) -> str | None:
    card = p.get("card")
    if not card or not card["moves"]:
        return None
    names = p.get("players") or {}

    def name(k: int | None) -> str:
        return names.get(str(k), f"player {k}") if k is not None else ""

    parts = []
    for m in card["moves"]:
        what = []
        if m["add"] is not None:
            what.append(f"added {name(m['add'])}")
        if m["drop"] is not None:
            what.append(f"dropped {name(m['drop'])}")
        kind = _KIND_WORDS[m["match"]["kind"]] + (", near a solve" if m["match"]["near"] else "")
        parts.append(f"{' and '.join(what)} ({kind})")
    return f"- League {p['league']}: " + "; ".join(parts)


def markdown(
    week: int,
    payloads: Sequence[Mapping[str, Any]],
    pool: Mapping[str, Any],
    skipped: Sequence[Mapping[str, str]] = (),
) -> str:
    """The week's scorecard for a public issue: leagues by id, no team names, no projected
    player line; the odds and results as aggregates, the moves by the players' names and how
    they matched the solve before them."""
    card = next((p["card"] for p in payloads if p.get("card")), None)
    span = ""
    if card:
        start, end = (datetime.fromisoformat(card[k]) for k in ("start", "end"))
        span = f" ({start:%b} {start.day} - {end:%b} {end.day})"
    w, td = pool["week"], pool["to_date"]
    lines = [f"## Scorecard, week {week}{span}", ""]
    if w["leagues"]:
        lines.append(
            f"- Pooled over {w['leagues']} public league{'s' if w['leagues'] != 1 else ''}: "
            f"matchup odds Brier {_num(w['brier'], 3)}; category odds by bucket: {_buckets(w)}."
        )
    else:
        lines.append("- No public league's week was projected: nothing pooled.")
    if w["left_out"]:
        lines.append(f"- Left out, no projection of the week: {', '.join(w['left_out'])}.")
    if w["not_recorded"]:
        lines.append(f"- Not recorded: {', '.join(w['not_recorded'])}.")
    if td["weeks"]:
        lines.append(
            f"- Season to date, {td['weeks']} projected league-week{'s' if td['weeks'] != 1 else ''}: "
            f"Brier {_num(td['brier'], 3)}."
        )
    public = [p for p in payloads if p["public"]]
    private = [p for p in payloads if not p["public"]]
    head = [
        "| League | Projected | Result | Categories | Standing | Moves |",
        "|---|---|---|---|---|---|",
    ]
    lines += ["", *head, *(_row(p) for p in public)]
    if private:
        lines += ["", "Private league, suggestions only, never pooled:", "", *head]
        lines += [_row(p) for p in private]
    moves = [line for p in payloads if (line := _moves_line(p))]
    if moves:
        lines += ["", "### Moves", *moves]
        lines += ["", UNSCORED]
    if skipped:
        lines += [
            "",
            "Not read: "
            + ", ".join(f"League {s['league']} ({s['reason']})" for s in skipped)
            + ".",
        ]
    return "\n".join(lines) + "\n"
