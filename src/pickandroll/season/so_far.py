"""A player's week so far on his fantasy team, as Yahoo counts it (#304): the matchup page's
player table prints his counting stats and his rounded percentages for the days he sat in an
active slot, never his makes and attempts or his games. Those come from his final box scores
this week (``sources.boxscores``, cached by the refresh): the one set of his games whose counting
stats sum exactly to Yahoo's row and whose makes over attempts round to Yahoo's percentages is
the games Yahoo counted, the empty set among them (he sat, or did not play, every day: Yahoo
prints his zeros). No such set, more than one, or no box scores for him: his line is Yahoo's as
printed, its percentages without the attempts behind them and its games unknown. A player not on
the page as read has nothing known (``not_read``).

Pure: the API hands over the page's row and his box-score lines.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from . import weekly as wk

#: The player table's counting columns in our stat names.
COLUMNS = {
    "3PTM": "threes",
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "ST": "stl",
    "BLK": "blk",
    "TO": "tov",
}
#: Its percentage columns, printed to three places.
PCT_COLUMNS = {"FG%": "fg_pct", "FT%": "ft_pct"}
FAN_PTS = "Fan Pts"
#: A matchup week's days: the most games a player has in one, so at most 2**7 sets to try.
MAX_GAMES = 7
#: Half a unit of the third place: a percentage printed as ``.556`` is in [.5555, .5565].
HALF = 0.0005 + 1e-9

NO_BOX = "no box scores for him this week"
NONE_ADDS_UP = "no set of his box-score games adds up to Yahoo's line"
TOO_MANY = "more games than a week has"
NOT_READ = "not on the matchup page as read"


def ambiguous(n: int) -> str:
    return f"{n} sets of his box-score games add up to Yahoo's line"


def _num(text: Any) -> float | None:
    try:
        return float(str(text).replace(",", "").strip())
    except ValueError:
        return None


@dataclass(frozen=True)
class SoFar:
    """His week so far: ``line`` in our stat names (``weekly.STATS``, the percentages and in a
    points league the fantasy points; None when not known), ``games`` counted (None when not
    known) and, when the box scores could not place his games, ``why``."""

    line: dict[str, float | None]
    games: int | None
    why: str | None = None

    @property
    def matched(self) -> bool:
        return self.why is None

    def to_dict(self) -> dict[str, Any]:
        return {**self.line, "games": self.games, "why": self.why}


def not_read(points: bool) -> SoFar:
    """A player not on the page's table (the page not read, read before its player table was, or
    he joined after it was): every stat and his games unknown."""
    keys = [*wk.STATS, *wk.PCT, *([wk.FPTS] if points else [])]
    return SoFar(dict.fromkeys(keys), None, NOT_READ)


def yahoo_line(row: Mapping[str, str]) -> dict[str, float | None]:
    """The page's row in our stat names: a ``-`` is None."""
    out: dict[str, float | None] = {}
    for label, name in (*COLUMNS.items(), *PCT_COLUMNS.items()):
        if label in row:
            out[name] = _num(row[label])
    if FAN_PTS in row:
        out[wk.FPTS] = _num(row[FAN_PTS])
    return out


def _sum(games: Sequence[Mapping[str, float]]) -> dict[str, float]:
    return {s: sum(float(g.get(s) or 0.0) for g in games) for s in wk.STATS}


def _with_pct(total: Mapping[str, float]) -> dict[str, float | None]:
    out: dict[str, float | None] = dict(total)
    for cat, (made, att) in wk.PCT.items():
        out[cat] = total[made] / total[att] if total[att] else None
    return out


def _fits(total: Mapping[str, float], yahoo: Mapping[str, float | None]) -> bool:
    for name in COLUMNS.values():
        if name in yahoo and abs(total[name] - (yahoo[name] or 0.0)) > 1e-9:
            return False
    for cat, (made, att) in wk.PCT.items():
        if cat not in yahoo:
            continue
        shown = yahoo[cat]
        if shown is None:
            if total[att]:
                return False
        elif not total[att] or abs(total[made] / total[att] - shown) > HALF:
            return False
    return True


def so_far(
    row: Mapping[str, str],
    games: Sequence[Mapping[str, float]] | None,
    points: Mapping[str, float] | None = None,
) -> SoFar:
    """His week so far from the page's ``row`` and ``games``, his box-score lines this week (the
    games he played, any team's), None when he is not matched to the box scores."""
    yahoo = yahoo_line(row)
    counting = [yahoo[n] for n in COLUMNS.values() if n in yahoo]
    if counting and all(v is None for v in counting):
        # No game counted: certain without the box scores.
        line = _with_pct(dict.fromkeys(wk.STATS, 0.0))
        if points is not None:
            line[wk.FPTS] = 0.0
        return SoFar(line, 0)
    fallback = {**dict.fromkeys(wk.STATS), **yahoo}
    for s in ("fgm", "fga", "ftm", "fta"):
        fallback[s] = None
    if games is None:
        return SoFar(fallback, None, NO_BOX)
    if len(games) > MAX_GAMES:
        return SoFar(fallback, None, TOO_MANY)
    found = [
        (n, total)
        for n in range(len(games) + 1)
        for subset in combinations(games, n)
        if _fits(total := _sum(subset), yahoo)
    ]
    if len(found) != 1:
        return SoFar(fallback, None, NONE_ADDS_UP if not found else ambiguous(len(found)))
    n, total = found[0]
    line = _with_pct(total)
    if points is not None:
        line[wk.FPTS] = yahoo.get(wk.FPTS)
        if line[wk.FPTS] is None:
            line[wk.FPTS] = sum(float(w) * total.get(s, 0.0) for s, w in points.items())
    return SoFar(line, n)
