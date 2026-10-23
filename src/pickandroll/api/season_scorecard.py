"""The Monday scorecard (#126, docs/ADD_DROP.md "Scorecard"): ``GET /seasons/{league}/scorecard``,
a league's recorded weeks against what the decision log projected for them, and
``GET /seasons/scorecard``, every league's week with the odds' calibration pooled over the public
leagues, and the week as markdown for the AUTOPILOT tracker (#127).

The weeks are the weekly recorder's (#97), the projections the decision log's (#125), scored by
``season.scorecard``. My moves of a week are its record's transactions (for a week recorded before
the record kept them, the season's transactions page, which may have lost the oldest), each
matched to the entry logged before it (``season.decisions``). A move made as recommended carries
the entry's projection of it in value units, and every move its realized value (``season.realized``)
from the final box scores a refresh caches (``sources.boxscores``): the scorecard reads the
cache only, and keeps each ESPN id it matches. A move is valued with the scorer of the entry it
matched, or for a move with no entry, or one logged before entries kept their scorer, the scorer
of the entry nearest it on the system scored (master's ruling, 2026-10-22). A move is then in one
of three groups: ``scored`` (projected by its own entry and realized), ``realized_only`` (realized,
but with no projection of its own or a borrowed scorer) or ``unscored``; only the scored are set
against their projection, each on the horizon its set was recommended for (``judged``, #143): the
week's set and the streaming plan on the week, the three weeks' set and the strategy's on the three
weeks after, a move with no projection of its own on the week.

The private league is scored on its own and never pooled: its moves are suggestions only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import Season
from ..season import decisions as dl
from ..season import realized as rz
from ..season import scorecard as sc
from ..season.calendar import Calendar, Week
from ..season.state import Player, Transaction
from ..sources import boxscores
from .season_decisions import TRANSACTIONS_TZ, _names

#: The system scored by default: the one the routines solve with.
SYSTEM = "bbm"
KINDS = (dl.AS_RECOMMENDED, dl.DIFFERENTLY, dl.NOT_RECOMMENDED, dl.NO_ENTRY)
#: Where a refresh caches the box scores, under the data folder.
BOXSCORES_DIR = "boxscores"
#: A move's group: projected by its own entry and realized, realized only, or neither.
SCORED, REALIZED_ONLY, UNSCORED = "scored", "realized_only", "unscored"
#: The horizon a move is judged on when nothing says otherwise: its week.
WEEK = "week"
#: The moves route's sets recommended for the three weeks after the week.
_THREE_SETS = ("three",)
_REASONS = {
    rz.NO_TIME: "with no time on the page",
    rz.NO_SCORER: "with no scorer logged",
    rz.UNMATCHED: "with a player not matched to the box scores",
    rz.NOT_READ: "with no box score read yet",
}
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
    each horizon as the solve priced it, its projection in value units, and the week's odds of
    winning the matchup and expected categories before and after the set (``odds``, #129);
    None for any other match, or an entry logged before it kept them."""
    if match.get("kind") != dl.AS_RECOMMENDED or match.get("move") is None:
        return None
    entry = next((e for e in entries if e["id"] == match["entry"]), None)
    want = (match["move"]["add"], match["move"]["drop"])
    for s in (entry or {}).get("sets") or []:
        for m in s.get("moves") or []:
            if (m.get("add"), m.get("drop")) == want and m.get("value") is not None:
                week = s.get("week") or {}
                odds = {
                    side: {k: block.get(k) for k in ("matchup", "expected")}
                    if (block := week.get(side))
                    else None
                    for side in ("before", "after")
                }
                return {"set": s["key"], "gain": m.get("gain"), "value": m["value"], "odds": odds}
    return None


# --------------------------------------------------------------------------- realized value
@dataclass
class BoxScores:
    """What the realized values read: the box-score cache, each day of it read once, and the
    ESPN ids matched so far, a new match kept until :meth:`save`; ``today`` the NBA date."""

    cache_dir: Path
    today: date
    ids: dict[int, str] = field(default_factory=dict)
    _days: dict[date, list[dict[str, Any]]] = field(default_factory=dict)
    _seen: set[date] = field(default_factory=set)
    _new: bool = False

    @classmethod
    def at(cls, data_dir: Path, today: date) -> BoxScores:
        cache = data_dir / BOXSCORES_DIR
        return cls(cache, today, boxscores.load_ids(cache))

    def days(self, first: date, last: date) -> dict[date, list[dict[str, Any]]]:
        """The cached days from ``first`` to ``last``, none from today on."""
        last = min(last, self.today - timedelta(1))
        wanted = [first + timedelta(n) for n in range((last - first).days + 1)]
        todo = [d for d in wanted if d not in self._seen]
        self._days |= boxscores.load_days(todo, self.cache_dir)
        self._seen |= set(todo)
        return {d: self._days[d] for d in wanted if d in self._days}

    def match(
        self, players: Mapping[int, tuple[str, str | None]], games: Iterable[Mapping[str, Any]]
    ) -> dict[int, tuple[str, str]]:
        found = boxscores.match(players, games, self.ids)
        for k, (espn, by) in found.items():
            if by != "id":
                self.ids[k], self._new = espn, True
        return found

    def save(self) -> None:
        if self._new:
            boxscores.save_ids(self.cache_dir, self.ids)
            self._new = False


def scorer_for(
    made: dl.Made, match: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], system: str
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """The entry whose scorer values ``made`` and that scorer: the matched entry's, else the
    nearest entry's on ``system`` that keeps one; (None, None) when no entry does."""
    entry = next((e for e in entries if e["id"] == match.get("entry")), None)
    if entry is not None and entry.get("scorer"):
        return entry, entry["scorer"]
    kept = [e for e in entries if e.get("scorer") and (e.get("system") or {}).get("key") == system]
    if not kept or made.at is None:
        return None, None
    at = made.at
    nearest = min(kept, key=lambda e: abs(datetime.fromisoformat(e["at"]) - at))
    return nearest, nearest["scorer"]


def realized_move(
    made: dl.Made,
    match: Mapping[str, Any],
    week: Week,
    entries: Sequence[Mapping[str, Any]],
    players: Mapping[int, Player],
    box: BoxScores,
    calendar: Calendar | None = None,
    system: str = SYSTEM,
) -> dict[str, Any]:
    """A move's realized value (``season.realized``) from the cached box scores, its players
    matched by name and team, the entry whose scorer valued it (``own`` when it is the entry
    the move matched), and ``lag_days``, the days from the matched entry's first day to the
    move's (with none, the spans are the logged ones)."""
    entry, scorer = scorer_for(made, match, entries, system)
    wanted = {
        key: (pid, players.get(pid))
        for key, pid in (("add", made.add), ("drop", made.drop))
        if pid is not None
    }
    games: dict[date, list[dict[str, Any]]] = {}
    found: dict[int, tuple[str, str]] = {}
    if made.day is not None:
        ends = [last for _, last in rz.spans(week, made.day, calendar).values()]
        games = box.days(made.day, max(ends))
        named = {pid: (p.name, p.nba_team) for pid, p in wanted.values() if p is not None}
        found = box.match(named, [g for day in games.values() for g in day])
    sides = {
        key: rz.Side(pid, p.nba_team if p else None, *found.get(pid, (None, None)))
        for key, (pid, p) in wanted.items()
    }
    out = rz.realized(
        made.at,
        made.day,
        week,
        sides.get("add"),
        sides.get("drop"),
        scorer,
        games,
        box.today,
        calendar,
    )
    own = entry is not None and entry["id"] == match.get("entry")
    matched = next((e for e in entries if e["id"] == match.get("entry")), None)
    lag = None
    if matched is not None and matched.get("first_day") and made.day is not None:
        lag = (made.day - date.fromisoformat(matched["first_day"])).days
    return {
        **out,
        "scorer": {"entry": entry["id"], "own": own} if entry else None,
        "lag_days": lag,
    }


def judged_horizon(projected: Mapping[str, Any] | None, entry: Mapping[str, Any] | None) -> str:
    """The horizon a move is judged on (#143): the one its set was recommended for. The moves
    route's week set and streaming plan on the week, its three weeks' set on the three weeks
    after; a strategy set on the three weeks after (the season once #144's horizon exists); a
    move with no projection of its own on the week."""
    if not projected:
        return WEEK
    if (entry or {}).get("source") == "strategy" or projected.get("set") in _THREE_SETS:
        return "three"
    return WEEK


def group(row: Mapping[str, Any]) -> str:
    """A move row's group: ``scored`` when its own entry projected it and its own scorer
    realized it, ``realized_only`` when it is realized otherwise, else ``unscored``."""
    x = row.get("realized") or {}
    if not x.get("valued"):
        return UNSCORED
    own = (x.get("scorer") or {}).get("own")
    return SCORED if own and row.get("projected") else REALIZED_ONLY


def _players(season: Season | None, record: Mapping[str, Any]) -> dict[int, Player]:
    """The players a week's moves may name, the team a transaction gives first."""
    out: dict[int, Player] = {}
    if season is not None:
        out |= {p.yahoo_id: p for p in season.players.values()}
        for spots in season.rosters.values():
            out |= {sp.player.yahoo_id: sp.player for sp in spots}
        out |= {a.player.yahoo_id: a.player for a in season.available}
        out |= {t.player.yahoo_id: t.player for t in season.transactions}
    for row in record.get("transactions") or []:
        t = Transaction.from_dict(row)
        out[t.player.yahoo_id] = t.player
    return out


def move_rows(
    record: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    me: int,
    season: Season | None = None,
    box: BoxScores | None = None,
    system: str = SYSTEM,
) -> list[dict[str, Any]]:
    """My moves of the week, each with its match, the knobs in force at the entry it matched
    (#129), the entry's projection of it (for a move made as recommended), the horizon it is
    judged on (``judged``, #143) and its realized value (None without the box scores)."""
    week = sc.week_of(record)
    players = _players(season, record) if box is not None else {}
    calendar = season.calendar if season is not None else None
    out = []
    for m in week_moves(record, me, season):
        match = dl.match(m, entries)
        realized = None
        if box is not None:
            realized = realized_move(m, match, week, entries, players, box, calendar, system)
        entry = next((e for e in entries if e["id"] == match.get("entry")), None)
        projected = logged_move(entries, match)
        row = {
            **m.to_dict(),
            "match": match,
            "knobs": (entry or {}).get("knobs"),
            "projected": projected,
            "judged": judged_horizon(projected, entry),
            "realized": realized,
        }
        out.append({**row, "group": group(row)})
    return out


def _add(sums: dict[str, float], key: str, x: float) -> None:
    sums[key] = round(sums.get(key, 0.0) + x, 4)


def _same_way(projected: float, realized: float) -> bool:
    """Whether a move realized in the direction projected: the same sign, or both nothing."""
    return (projected > 0) == (realized > 0) and (projected < 0) == (realized < 0)


def moves_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The moves of some weeks: how many, by match and by group, how many the log projected
    and their projected value summed on each horizon; the realized value of every move
    realized summed on each horizon (through the days read) and the spans complete; the
    unscored by reason and the games of players not matched; and over the scored moves whose
    judging horizon is over (``compared``, None without one), each on the horizon its set was
    recommended for (#143): their projected and realized values summed, the realized share of
    the projected, how many realized in the projected direction and how many were judged on
    each horizon."""
    rows = list(rows)
    projected = [r["projected"] for r in rows if r.get("projected")]
    sums: dict[str, float] = {}
    for p in projected:
        for key, h in (p["value"].get("horizons") or {}).items():
            if h.get("value") is not None:
                _add(sums, key, h["value"])
    real: dict[str, float] = {}
    complete: dict[str, int] = {}
    compared: dict[str, Any] | None = None
    reasons: Counter[str] = Counter()
    gaps = 0
    for r in rows:
        x = r.get("realized") or {}
        if not x.get("valued"):
            reasons[x.get("reason") or rz.NOT_READ] += 1
        for key, h in (x.get("horizons") or {}).items():
            gaps += h.get("gaps") or 0
            if not x.get("valued") or h["value"] is None:
                continue
            _add(real, key, h["value"])
            complete[key] = complete.get(key, 0) + int(h["complete"])
        judged = r.get("judged") or judged_horizon(r.get("projected"), None)
        h = (x.get("horizons") or {}).get(judged)
        p = ((r.get("projected") or {}).get("value") or {}).get("horizons", {}).get(judged)
        if group(r) != SCORED or not h or not h["complete"] or h["value"] is None:
            continue
        if not p or p.get("value") is None:
            continue
        if compared is None:
            compared = {
                "moves": 0,
                "projected": 0.0,
                "realized": 0.0,
                "same_way": 0,
                "horizons": {},
            }
        compared["moves"] += 1
        compared["same_way"] += int(_same_way(p["value"], h["value"]))
        compared["horizons"][judged] = compared["horizons"].get(judged, 0) + 1
        _add(compared, "projected", p["value"])
        _add(compared, "realized", h["value"])
    if compared is not None:
        c = compared
        c["share"] = round(c["realized"] / c["projected"], 4) if c["projected"] > 0 else None
    groups = Counter(group(r) for r in rows)
    return {
        "made": len(rows),
        **{kind: sum(1 for r in rows if r["match"]["kind"] == kind) for kind in KINDS},
        "near": sum(1 for r in rows if r["match"].get("near")),
        "projected": len(projected),
        "projected_value": sums,
        SCORED: groups[SCORED],
        REALIZED_ONLY: groups[REALIZED_ONLY],
        UNSCORED: groups[UNSCORED],
        "realized_value": real,
        "complete": complete,
        "compared": compared,
        "unscored_by": dict(reasons),
        "gaps": gaps,
    }


def league_payload(
    league: str,
    season: Season,
    is_public: bool,
    records: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    system: str = SYSTEM,
    week: int | None = None,
    box: BoxScores | None = None,
) -> dict[str, Any]:
    """A league's scorecard: its week (``week``, by default the last recorded) and every
    recorded week to it, each against the projection, its moves valued from ``box``, the
    season to date, the odds' calibration over its weeks, and the names of the players its
    moves name."""
    me = season.settings.my_team_id
    base = {"league": league, "public": is_public, "system": system}
    shown = [r for r in records if week is None or int(r["week"]) <= week]
    if me is None:
        return {**base, "status": "no_team", "week": week, "card": None, "weeks": []}
    if not shown or (week is not None and int(shown[-1]["week"]) != week):
        return {**base, "status": "not_recorded", "week": week, "card": None, "weeks": []}
    cards = [
        sc.week_card(r, entries, me, system, move_rows(r, entries, me, season, box, system))
        for r in shown
    ]
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


def _realized_counts(rows: Sequence[Mapping[str, Any]]) -> str:
    """Moves realized as public text, counts and ratios only (master's ruling, 2026-10-22: no
    scorer-unit value, for a move or summed): the scored with their realized share of the
    projected and how many went the projected way, each on the horizon its set was recommended
    for (#143), the realized only, the unscored by reason."""
    s = moves_summary(rows)
    c = s["compared"]
    head = f"{s[SCORED]} move{'s' if s[SCORED] != 1 else ''} scored"
    if c:
        share = (
            "projected not positive"
            if c["share"] is None
            else f"realized {_pct(c['share'])} of projected"
        )
        some = (
            f" (the {c['moves']} with their recommended horizon over)"
            if c["moves"] != s[SCORED]
            else ""
        )
        head += f": {share}, {c['same_way']} of {c['moves']} in the projected direction{some}"
    parts = [head, f"{s[REALIZED_ONLY]} realized only", f"{s[UNSCORED]} unscored"]
    if s["unscored_by"]:
        why = ", ".join(f"{n} {_REASONS[r]}" for r, n in sorted(s["unscored_by"].items()))
        parts[-1] += f" ({why})"
    if s["gaps"]:
        parts.append(f"{s['gaps']} game{'s' if s['gaps'] != 1 else ''} of players not matched")
    return "; ".join(parts)


def _realized_line(label: str, payloads: Sequence[Mapping[str, Any]]) -> str | None:
    """The moves of ``payloads`` realized, this week's and the season's to date."""
    week = [m for p in payloads if p.get("card") for m in p["card"]["moves"]]
    season = [m for p in payloads for c in p.get("weeks") or [] for m in c["moves"]]
    if not season:
        return None
    this = _realized_counts(week) if week else "no moves"
    return f"- Realized, {label}: this week {this}. Season to date {_realized_counts(season)}."


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
    realized = [
        line
        for line in (
            _realized_line("the public leagues", public),
            _realized_line("the private league, suggestions only", private),
        )
        if line
    ]
    if moves or realized:
        lines += ["", "### Moves", *moves]
        lines += ["", *realized] if realized else []
    if skipped:
        lines += [
            "",
            "Not read: "
            + ", ".join(f"League {s['league']} ({s['reason']})" for s in skipped)
            + ".",
        ]
    return "\n".join(lines) + "\n"
