"""The weekly recorder (docs/ADD_DROP.md phase 6, #97): one finished matchup week of a league as a
record, kept for the in-season test of the draft (#91).

A week's record holds the standings as of the week's end, each team's totals and games played
for the week with its result, the week's matchups, the season-to-date line of every drafted
player with the team that has him, and every add and drop of the week as the transactions pages
read through it listed them (a page lists the latest few dozen, so the week is the pages' union:
the Monday scorecard's moves, #126). It is built from the parsed pages (``sources.yahoo.pages``)
and written once per week by the API; recording a week again changes the file only when its
content changed (a stat correction), and says when (``revised_at``). Pure: the reads and the
file live in ``api.season_record``.

A section read after the week's end (the standings, the players' lines) carries ``through``,
the last NBA day it includes: the day before it was read. Only a read on the day after the week
ends is the week's own; a later read is kept only until one at the week's end arrives, and never
replaces it.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from .calendar import Week
from .moves import when_date
from .state import SeasonSettings

#: Yahoo's column labels, spaces and the non-scoring asterisk taken out, in our stat names.
_LABELS = {
    "FG%": "fg_pct",
    "FT%": "ft_pct",
    "3PTM": "threes",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "TO": "tov",
    "FANPTS": "fpts",
}
_PAIRS = {"FGM/A": ("fgm", "fga"), "FTM/A": ("ftm", "fta")}
#: The stats of a season line, as the players page gives them.
LINE_STATS = (
    "gp",
    "mpg",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "threes",
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "tov",
)
#: Keys that say when something was read or written, not what it holds.
TIMES = frozenset({"read_at", "recorded_at", "revised_at"})


def _num(text: Any) -> float | None:
    if isinstance(text, int | float):
        return float(text)
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


def _key(label: str) -> str:
    return re.sub(r"[\s*]", "", label).upper()


def team_totals(labels: Mapping[str, Any]) -> dict[str, float]:
    """A team's week from the matchup page's columns, in our stat names: makes and attempts
    apart, the percentages as printed; a column we have no name for keeps Yahoo's label."""
    out: dict[str, float] = {}
    for label, text in labels.items():
        key = _key(label)
        if key in _PAIRS and "/" in str(text):
            for name, value in zip(_PAIRS[key], str(text).split("/"), strict=False):
                if (v := _num(value)) is not None:
                    out[name] = v
        elif (v := _num(text)) is not None:
            out[_LABELS.get(key, label)] = v
    return out


def week_teams(
    matchups: Sequence[Mapping[str, Any]], cats: Sequence[str], points: bool
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Each team's week (opponent, totals, games, result) and the week's matchups, from the
    matchup pages (``pages.parse_matchup_page``). A categories league's result is categories won,
    lost and tied; a points league's is its points and the opponent's."""
    teams: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for m in matchups:
        a, b = (int(t) for t in m["teams"])
        score = [float(x) for x in m["score"]] if m.get("score") else None
        totals = m.get("totals") or m.get("roster_totals") or {}
        games = m.get("games") or {}
        winner = None
        if score is not None and score[0] != score[1]:
            winner = a if score[0] > score[1] else b
        pairs.append({"teams": [a, b], "score": score, "winner": winner})
        for i, (me, them) in enumerate(((a, b), (b, a))):
            if score is None:
                result = None
            elif points:
                result = {"points": score[i], "against": score[1 - i]}
            else:
                won, lost = int(score[i]), int(score[1 - i])
                result = {"won": won, "lost": lost, "tied": len(cats) - won - lost}
            if result is not None:
                result["outcome"] = "T" if winner is None else "W" if winner == me else "L"
            teams[str(me)] = {
                "opponent": them,
                "totals": team_totals(totals.get(str(me)) or {}),
                "totals_from": "team" if m.get("totals") else "players" if totals else None,
                "games": dict(games[str(me)]) if str(me) in games else None,
                "result": result,
            }
    return dict(sorted(teams.items(), key=lambda kv: int(kv[0]))), sorted(
        pairs, key=lambda p: p["teams"]
    )


def standings(teams: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keep = ("team_id", "name", "rank", "wins", "losses", "ties", "points_for")
    return [{k: t.get(k) for k in keep} for t in teams]


def _name(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def draft_teams(
    picks: Sequence[Mapping[str, Any]], teams: Iterable[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """The picks with the team that made each, matched by name to the standings (the draft
    results page names teams but links none), and the names that matched no team."""
    by_name = {_name(t["name"]): int(t["team_id"]) for t in teams if t.get("name")}
    out, unmatched = [], []
    for p in picks:
        team = by_name.get(_name(p.get("team_name") or ""))
        if team is None and p.get("team_name") and p["team_name"] not in unmatched:
            unmatched.append(p["team_name"])
        out.append({**p, "team_id": team})
    return out, unmatched


def drafted_lines(
    picks: Sequence[Mapping[str, Any]],
    lines: Mapping[int, Mapping[str, Any]],
    owners: Mapping[int, int | str | None] | None = None,
) -> tuple[list[dict[str, Any]], list[int]]:
    """One row per drafted player: his pick, the team that drafted him, who has him now (a team
    id, ``FA`` or ``W``; ``owners`` when given, else the line's own page) and his season line;
    and the drafted players no line was found for."""
    rows, missing = [], []
    for p in picks:
        pid = int(p["player"]["yahoo_id"])
        line = lines.get(pid)
        if owners is not None:
            now = owners.get(pid)
        elif line is not None:
            now = line.get("team_id") or line.get("availability")
        else:
            now = None
        rows.append(
            {
                "player": pid,
                "name": p["player"]["name"],
                "nba_team": (line or {}).get("player", {}).get("nba_team")
                or p["player"].get("nba_team"),
                "round": p["round"],
                "pick": p["pick"],
                "drafted_by": p.get("team_id"),
                "team": now,
                "line": None if line is None else {k: line.get(k) for k in LINE_STATS},
            }
        )
        if line is None:
            missing.append(pid)
    return rows, missing


def week_transactions(
    pages: Iterable[tuple[date, Sequence[Mapping[str, Any]]]], week: Week
) -> list[dict[str, Any]]:
    """Every transaction of ``week`` from the transactions pages read, each with the day it was
    read (which dates its rows): a group (an add and the drop with it) once however many pages
    listed it, numbered anew in the order first seen, each row with its ``day``."""
    seen: dict[tuple[Any, ...], int] = {}
    out: list[dict[str, Any]] = []
    for read, rows in pages:
        groups: dict[int, list[Mapping[str, Any]]] = {}
        for row in rows:
            groups.setdefault(int(row.get("group") or 0), []).append(row)
        for group in groups.values():
            day = when_date(group[0].get("when"), read)
            if day is None or not week.start <= day <= week.end:
                continue
            players = tuple(sorted((r["kind"], int(r["player"]["yahoo_id"])) for r in group))
            key = (group[0].get("team_id"), group[0].get("when"), players)
            if key in seen:
                continue
            seen[key] = len(seen)
            out += [{**r, "group": seen[key], "day": day.isoformat()} for r in group]
    return out


def week_record(
    league: str,
    week: Week,
    settings: SeasonSettings,
    *,
    teams: Mapping[str, Any],
    matchups: Sequence[Mapping[str, Any]],
    standings_: Mapping[str, Any] | None,
    players: Mapping[str, Any] | None,
    missing: Mapping[str, Any],
    sources: Mapping[str, str],
    transactions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The record of ``week`` (``recorded_at`` and ``revised_at`` are set by :func:`settle`)."""
    return {
        "league": str(league),
        "week": week.number,
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "scoring": settings.scoring,
        "cats": list(settings.cats),
        "sources": dict(sources),
        "standings": standings_,
        "teams": dict(teams),
        "matchups": list(matchups),
        "players": players,
        "transactions": [dict(t) for t in transactions],
        "missing": {k: v for k, v in missing.items() if v},
    }


def content(record: Mapping[str, Any] | None) -> Any:
    """What a record holds, without when its parts were read or written."""

    def strip(x: Any) -> Any:
        if isinstance(x, Mapping):
            return {k: strip(v) for k, v in x.items() if k not in TIMES}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    return strip(record)


def _through(section: Mapping[str, Any] | None) -> date | None:
    t = (section or {}).get("through")
    return date.fromisoformat(t) if t else None


def _better(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None, end: date) -> bool:
    """Whether the old section stays: it was read at the week's end or nearer it than the new
    one, which came later."""
    o, n = _through(old), _through(new)
    if old is None or o is None or o < end:
        return False
    return n is None or n > o


def settle(
    old: Mapping[str, Any] | None, new: Mapping[str, Any], now: datetime
) -> tuple[dict[str, Any] | None, str]:
    """The record to write and what happened: ``recorded`` (a first record), ``revised`` (its
    content changed: a stat correction, a late section replaced) or ``unchanged`` (nothing to
    write). A standings or players section read later than an old one at the week's end leaves
    the old one in place."""
    out = copy.deepcopy(dict(new))
    end = date.fromisoformat(out["end"])
    if old is not None:
        for key in ("standings", "players"):
            if _better(old.get(key), out.get(key), end):
                out[key] = copy.deepcopy(old[key])
                missing = {k: v for k, v in out["missing"].items() if k != key}
                if (old.get("missing") or {}).get(key):
                    missing[key] = old["missing"][key]
                out["missing"] = missing
                if key in (old.get("sources") or {}):
                    out["sources"] = {**out["sources"], key: old["sources"][key]}
        if content(old) == content(out):
            return None, "unchanged"
        out["recorded_at"] = old.get("recorded_at") or now.isoformat()
        out["revised_at"] = now.isoformat()
        return out, "revised"
    out["recorded_at"] = now.isoformat()
    out["revised_at"] = None
    return out, "recorded"


def summary(record: Mapping[str, Any], me: int | None) -> dict[str, Any]:
    """A recorded week for the season's history: my opponent, result and place after it."""
    mine = (record.get("teams") or {}).get(str(me)) if me is not None else None
    stand = record.get("standings") or {}
    row = next((t for t in stand.get("teams") or [] if t.get("team_id") == me), None)
    names = {t.get("team_id"): t.get("name") for t in stand.get("teams") or []}
    opponent = mine.get("opponent") if mine else None
    return {
        "week": record["week"],
        "start": record["start"],
        "end": record["end"],
        "recorded_at": record.get("recorded_at"),
        "revised_at": record.get("revised_at"),
        "opponent": opponent,
        "opponent_name": names.get(opponent) if opponent is not None else None,
        "result": mine.get("result") if mine else None,
        "games": mine.get("games") if mine else None,
        "rank": row.get("rank") if row else None,
        "record": f"{row['wins']}-{row['losses']}-{row['ties']}"
        if row and row.get("wins") is not None
        else None,
        "standings_through": stand.get("through"),
        "players": len((record.get("players") or {}).get("rows") or []),
        "missing": {
            k: len(v) if isinstance(v, list) else v
            for k, v in (record.get("missing") or {}).items()
        },
    }
