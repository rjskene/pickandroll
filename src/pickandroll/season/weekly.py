"""Weekly projections of a league's rosters (docs/ADD_DROP.md, phase 2, #93): the games each
player plays in a matchup week, the slots that can start him, each category's weekly total and
spread, and the odds of winning each category against the week's opponent. Pure: the per-game
rates, the schedule and the rosters come in from the sources.

A player's weekly total is his per-game rate times the games he starts. On each day the
players with a game fill the league's starting slots (positions respected), most valuable
first; a day with more players than slots leaves the rest on the bench. The spread of a counting
category's weekly total is ``phi`` times its mean (per-game variance over mean, from game logs);
a percentage's spread is the binomial spread of the makes given the attempts.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from ..projections.schema import eligible_slots
from .state import Player

#: The per-game stats a projection system gives, in our names.
STATS = ("pts", "threes", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta")
COUNTING = ("pts", "threes", "reb", "ast", "stl", "blk", "tov")
#: A percentage category's makes and attempts.
PCT = {"fg_pct": ("fgm", "fga"), "ft_pct": ("ftm", "fta")}
LOWER_WINS = frozenset({"tov"})
FPTS = "fpts"

#: Where ``PHI`` and ``BINOMIAL`` come from. The fit is per game around each player's own season
#: mean, so it leaves out the projection's own error; the league's weekly totals re-fit it once
#: the weekly recorder (#97) keeps each week's projection.
PHI_SOURCE = (
    "ESPN public game logs (site.web.api.espn.com athlete gamelog), 2025-26 regular season, "
    "245 players with 30+ games and 20+ minutes a game, 15,767 games; fitted 2026-10-21 "
    "(pickandroll-scratch/emissary/phi-2026-10-21)"
)
#: Per-game variance over mean of each stat, pooled over the players (``PHI_SOURCE``), floored
#: at 1 (Poisson).
PHI: Mapping[str, float] = {
    "pts": 3.17,
    "threes": 1.18,
    "reb": 1.34,
    "ast": 1.27,
    "stl": 1.07,
    "blk": 1.12,
    "tov": 1.03,
    "fga": 1.49,
    "fta": 2.24,
}
#: The makes' variance around the player's percentage times his attempts, over the binomial
#: variance ``p (1 - p) attempts`` (FG 0.91 and FT 1.01 measured), floored at 1.
BINOMIAL: Mapping[str, float] = {"fgm": 1.0, "ftm": 1.01}

#: Slots that never start.
NOT_STARTING = frozenset({"BN", "IL", "IL+", "NA"})
#: Statuses that keep a player out of every week of the horizon, and the one that keeps him out
#: of the rest of this week. D, Q and P keep their games.
OUT_ALL = frozenset({"INJ", "OFS", "SUSP", "NA"})
OUT_THIS_WEEK = frozenset({"O"})

Rates = Mapping[str, float]


def starting_slots(roster: Iterable[str]) -> tuple[str, ...]:
    """The league's daily starting slots (``PG`` ... ``Util``), bench and IL left out."""
    return tuple(s for s in roster if s.upper() not in NOT_STARTING)


def accepts(slot: str, positions: Iterable[str]) -> bool:
    return slot.upper() == "UTIL" or slot.upper() in eligible_slots(positions)


@lru_cache(maxsize=4096)
def _fits(slots: tuple[str, ...], positions: tuple[str, ...]) -> tuple[int, ...]:
    """The indexes of ``slots`` a player with ``positions`` can start in (the move search asks
    this for every day of every roster it values)."""
    return tuple(i for i, s in enumerate(slots) if accepts(s, positions))


def starters[K: Hashable](
    candidates: Sequence[tuple[K, Sequence[str]]],
    slots: Sequence[str],
    value: Mapping[K, float],
) -> dict[K, str]:
    """The players who start on one day, by slot: ``candidates`` are the players with a game
    (key and positions), ``value`` ranks them. The most valuable set the slots can hold, found
    greedily with augmenting paths (the sets of players the slots can hold form a transversal
    matroid, so the greedy set is the best one). A player can move to another slot to make room
    for a more valuable one; nobody is benched for a less valuable player."""
    order = sorted(candidates, key=lambda c: (-value.get(c[0], 0.0), str(c[0])))
    fits = [_fits(tuple(slots), tuple(pos)) for _, pos in order]
    holder: dict[int, int] = {}  # slot index -> candidate index

    def place(ci: int, seen: set[int]) -> bool:
        for si in fits[ci]:
            if si in seen:
                continue
            seen.add(si)
            if si not in holder or place(holder[si], seen):
                holder[si] = ci
                return True
        return False

    for ci in range(len(order)):
        place(ci, set())
    return {order[ci][0]: slots[si] for si, ci in holder.items()}


def is_out(player: Player, this_week: bool, zero_games: bool = False) -> bool:
    """Whether ``player`` misses a week's games: every week for ``INJ``, ``OFS``, ``SUSP`` and
    ``NA``; the rest of this week for ``O``, and for a game-time decision that another
    projection gives no games (``zero_games``)."""
    if player.status in OUT_ALL:
        return True
    return this_week and (player.status in OUT_THIS_WEEK or (player.status == "GTD" and zero_games))


def game_days(
    nba_team: str | None, days: Iterable[date], schedule: Mapping[date, frozenset[str]]
) -> list[date]:
    """The days of ``days`` on which ``nba_team`` plays (a day the schedule lacks counts none)."""
    if not nba_team:
        return []
    return [d for d in days if nba_team in schedule.get(d, frozenset())]


@dataclass(frozen=True)
class PlayerWeek:
    #: Games he plays in the week (the schedule after the out rule, or a weekly export's count).
    games: int
    #: Of those, games in a starting slot (a roster's projection; an available player's is his
    #: games).
    started: int

    def to_dict(self) -> dict[str, int]:
        return {"games": self.games, "started": self.started}


@dataclass(frozen=True)
class TeamWeek:
    """A roster's projection for one week: each player's games, the stats' totals over the
    started games and the variance of each category's total (a percentage's in makes squared,
    a points league's ``fpts`` in points squared)."""

    players: Mapping[Any, PlayerWeek]
    totals: Mapping[str, float]
    variance: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "players": {str(k): v.to_dict() for k, v in self.players.items()},
            "totals": dict(self.totals),
            "variance": dict(self.variance),
        }


def project_week[K: Hashable](
    roster: Sequence[tuple[K, Player]],
    rates: Mapping[K, Rates],
    days: Sequence[date],
    schedule: Mapping[date, frozenset[str]],
    slots: Sequence[str],
    value: Mapping[K, float],
    this_week: bool,
    games: Mapping[K, int] | None = None,
    points: Mapping[str, float] | None = None,
    no_games: Collection[K] = (),
    available_from: Mapping[K, date] | None = None,
    gone_from: Mapping[K, date] | None = None,
) -> TeamWeek:
    """One roster's week over ``days``.

    ``games`` overrides the schedule and the out rule for the players it names (a weekly export
    that already folds in the news): such a player plays the last ``games`` of his game days.
    ``no_games`` are the players another projection gives no games (the out rule's game-time
    decisions). ``available_from`` holds back the players it names until that day (a waiver
    claim's clear date) and ``gone_from`` stops them from that day on (a drop). A player
    without rates plays but adds nothing. Starters are chosen per day by ``value``."""
    playing = playing_days(
        roster, days, schedule, this_week, games, no_games, available_from, gone_from
    )
    started = {key: 0 for key, _ in roster}
    for lineup in daily_starters(roster, playing, days, slots, value).values():
        for key in lineup:
            started[key] += 1
    players = {key: PlayerWeek(len(playing[key]), started[key]) for key, _ in roster}
    return _team_week(players, rates, points)


def playing_days[K: Hashable](
    roster: Sequence[tuple[K, Player]],
    days: Sequence[date],
    schedule: Mapping[date, frozenset[str]],
    this_week: bool,
    games: Mapping[K, int] | None = None,
    no_games: Collection[K] = (),
    available_from: Mapping[K, date] | None = None,
    gone_from: Mapping[K, date] | None = None,
) -> dict[K, list[date]]:
    """The days of ``days`` each player of ``roster`` plays, as :func:`project_week` counts
    them (the schedule, the out rule or a weekly export's games, and the days he is held back
    or gone)."""
    playing: dict[K, list[date]] = {}
    for key, player in roster:
        played = game_days(player.nba_team, days, schedule)
        if games is not None and key in games:
            n = max(0, min(int(games[key]), len(played)))
            played = played[len(played) - n :]
        elif is_out(player, this_week, key in no_games):
            played = []
        if available_from is not None and key in available_from:
            played = [d for d in played if d >= available_from[key]]
        if gone_from is not None and key in gone_from:
            played = [d for d in played if d < gone_from[key]]
        playing[key] = played
    return playing


def daily_starters[K: Hashable](
    roster: Sequence[tuple[K, Player]],
    playing: Mapping[K, Sequence[date]],
    days: Sequence[date],
    slots: Sequence[str],
    value: Mapping[K, float],
) -> dict[date, dict[K, str]]:
    """Each day's starters by slot (:func:`starters` over the players of ``roster`` who play
    that day): the lineup the projection counts."""
    positions = {key: player.positions for key, player in roster}
    return {
        day: starters(
            [(key, positions[key]) for key, played in playing.items() if day in played],
            slots,
            value,
        )
        for day in days
    }


def standalone_week(
    player: Player,
    days: Sequence[date],
    schedule: Mapping[date, frozenset[str]],
    this_week: bool,
    games: int | None = None,
    zero_games: bool = False,
) -> PlayerWeek:
    """A free agent's week on his own: every game he plays counts (whom he would sit is the
    move optimiser's question)."""
    played = len(game_days(player.nba_team, days, schedule))
    if games is not None:
        played = max(0, min(int(games), played))
    elif is_out(player, this_week, zero_games):
        played = 0
    return PlayerWeek(played, played)


def _team_week[K: Hashable](
    players: Mapping[K, PlayerWeek], rates: Mapping[K, Rates], points: Mapping[str, float] | None
) -> TeamWeek:
    totals = {s: 0.0 for s in STATS}
    for key, week in players.items():
        r = rates.get(key)
        if r is None or not week.started:
            continue
        for s in STATS:
            totals[s] += week.started * float(r.get(s, 0.0))
    variance: dict[str, float] = {}
    for s in COUNTING:
        variance[s] = PHI.get(s, 1.0) * totals[s]
    for cat, (made, att) in PCT.items():
        team = totals[made] / totals[att] if totals[att] else 0.0
        v = 0.0
        for key, week in players.items():
            r = rates.get(key)
            if r is None or not week.started:
                continue
            a = float(r.get(att, 0.0))
            p = float(r.get(made, 0.0)) / a if a else 0.0
            v += (
                week.started
                * a
                * (BINOMIAL.get(made, 1.0) * p * (1 - p) + PHI.get(att, 1.0) * (p - team) ** 2)
            )
        variance[cat] = v
    if points:
        totals[FPTS] = sum(float(w) * totals.get(s, 0.0) for s, w in points.items())
        variance[FPTS] = sum(
            float(w) ** 2 * PHI.get(s, 1.0) * totals.get(s, 0.0) for s, w in points.items()
        )
    return TeamWeek(players, totals, variance)


def player_totals(
    week: PlayerWeek, rates: Rates | None, points: Mapping[str, float] | None = None
) -> dict[str, float] | None:
    """A player's projected totals for the week (his started games times his rates), with his
    percentages and, in a points league, his fantasy points."""
    if rates is None:
        return None
    out = {s: week.started * float(rates.get(s, 0.0)) for s in STATS}
    for cat, (made, att) in PCT.items():
        out[cat] = out[made] / out[att] if out[att] else None  # type: ignore[assignment]
    if points:
        out[FPTS] = sum(float(w) * out.get(s, 0.0) for s, w in points.items())
    return out


# --------------------------------------------------------------------------- odds
@dataclass(frozen=True)
class CategoryOdds:
    cat: str
    #: Projected finals: the week so far plus the rest of the week.
    mine: float | None
    theirs: float | None
    #: The spread of the difference of the two finals.
    sd: float
    p_win: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cat": self.cat,
            "mine": self.mine,
            "theirs": self.theirs,
            "sd": self.sd,
            "p_win": self.p_win,
        }


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def final(week: TeamWeek, so_far: Mapping[str, float], cat: str) -> tuple[float | None, float]:
    """A category's projected final and its spread: the week so far (``so_far``, the matchup
    page's totals in our stat names) plus the projection of the rest of the week."""
    if cat in PCT:
        made, att = PCT[cat]
        m = so_far.get(made, 0.0) + week.totals.get(made, 0.0)
        a = so_far.get(att, 0.0) + week.totals.get(att, 0.0)
        if not a:
            return None, 0.0
        return m / a, math.sqrt(week.variance.get(cat, 0.0)) / a
    return so_far.get(cat, 0.0) + week.totals.get(cat, 0.0), math.sqrt(week.variance.get(cat, 0.0))


Final = tuple[float | None, float]


def finals(week: TeamWeek, so_far: Mapping[str, float], cats: Sequence[str]) -> dict[str, Final]:
    """Each category's :func:`final`."""
    return {cat: final(week, so_far, cat) for cat in cats}


def odds_of(
    mine: Mapping[str, Final], theirs: Mapping[str, Final], cats: Sequence[str]
) -> list[CategoryOdds]:
    """The odds of winning each category from both teams' finals (:func:`finals`): normal
    finals, lower wins for turnovers. A category with no spread is won, lost or tied (one half)
    outright."""
    out = []
    for cat in cats:
        a, sa = mine[cat]
        b, sb = theirs[cat]
        sd = math.hypot(sa, sb)
        if a is None or b is None:
            p = 0.5 if a is None and b is None else (0.0 if a is None else 1.0)
        else:
            d = (b - a) if cat in LOWER_WINS else (a - b)
            p = _phi(d / sd) if sd > 0 else (1.0 if d > 0 else 0.0 if d < 0 else 0.5)
        out.append(CategoryOdds(cat, a, b, sd, p))
    return out


def category_odds(
    mine: TeamWeek,
    theirs: TeamWeek,
    cats: Sequence[str],
    so_far_mine: Mapping[str, float] | None = None,
    so_far_theirs: Mapping[str, float] | None = None,
) -> list[CategoryOdds]:
    """The odds of winning each category of the week (:func:`odds_of` on the two weeks)."""
    return odds_of(
        finals(mine, so_far_mine or {}, cats), finals(theirs, so_far_theirs or {}, cats), cats
    )


def expected_won(odds: Iterable[CategoryOdds]) -> float:
    return sum(o.p_win for o in odds)


def matchup_won(odds: Sequence[CategoryOdds]) -> float:
    """The odds of winning the matchup: more of its categories won than lost, each category
    won with its own odds and independently of the others (a Poisson binomial over the
    categories), a tie on categories counted half. A points league's one category is its own
    odds. The categories are not independent (points and threes move together), so this is a
    headline, not the standings' measure: expected categories is."""
    counts = [1.0]
    for o in odds:
        nxt = [0.0] * (len(counts) + 1)
        for k, q in enumerate(counts):
            nxt[k] += q * (1.0 - o.p_win)
            nxt[k + 1] += q * o.p_win
        counts = nxt
    n = len(odds)
    return sum(q * (1.0 if 2 * k > n else 0.5 if 2 * k == n else 0.0) for k, q in enumerate(counts))


# --------------------------------------------------------------------------- values
def per_game_values[K: Hashable](
    rates: Mapping[K, Rates],
    cats: Sequence[str],
    points: Mapping[str, float] | None = None,
    pool: int = 156,
) -> dict[K, float]:
    """Each player's per-game value, to rank who starts on a crowded day: fantasy points in a
    points league; in a categories league the sum of his per-game z-scores over the ``pool``
    best players (percentages by impact, makes over a pool-average shooter on his attempts;
    turnovers negated), the pool chosen in two passes."""
    score = line_value(rates, cats, points, pool)
    return {k: score(r) for k, r in rates.items()}


def line_value[K: Hashable](
    rates: Mapping[K, Rates],
    cats: Sequence[str],
    points: Mapping[str, float] | None = None,
    pool: int = 156,
) -> Callable[[Rates], float]:
    """The per-game value of any line against the players of ``rates``, as
    :func:`per_game_values` values them (the trade margin values a received player's line
    scaled down this way)."""
    if points:
        weights = dict(points)
        return lambda r: sum(float(w) * float(r.get(s, 0.0)) for s, w in weights.items())
    keys = list(rates)
    first = _z_scorer(rates, keys, cats)
    z = {k: first(rates[k]) for k in keys}
    return _z_scorer(rates, sorted(keys, key=lambda k: -z[k])[:pool], cats)


def _column(cat: str, p: float = 0.0) -> Callable[[Rates], float] | None:
    """A category's column of the z-scores: a percentage's makes over a shooter at ``p`` on his
    attempts, a counting stat signed so that more is better; None for a category of neither."""
    if cat in PCT:
        made, att = PCT[cat]
        return lambda r: float(r.get(made, 0.0)) - p * float(r.get(att, 0.0))
    if cat in COUNTING:
        sign = -1.0 if cat in LOWER_WINS else 1.0
        return lambda r: sign * float(r.get(cat, 0.0))
    return None


def _columns[K: Hashable](
    rates: Mapping[K, Rates], chosen: Sequence[K], cats: Sequence[str]
) -> list[tuple[str, float, float, float]]:
    """Each category's column over the ``chosen`` players: the category, a percentage's pool
    average (0 for a counting stat), the column's mean and its spread (1 for none)."""
    out = []
    for cat in cats:
        p = 0.0
        if cat in PCT:
            made, att = PCT[cat]
            m = sum(float(rates[k].get(made, 0.0)) for k in chosen)
            a = sum(float(rates[k].get(att, 0.0)) for k in chosen)
            p = m / a if a else 0.0
        col = _column(cat, p)
        if col is None:
            continue
        xs = [col(rates[k]) for k in chosen]
        mean = sum(xs) / len(xs) if xs else 0.0
        sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs)) if xs else 0.0
        out.append((cat, p, mean, sd or 1.0))
    return out


def _z_scorer[K: Hashable](
    rates: Mapping[K, Rates], chosen: Sequence[K], cats: Sequence[str]
) -> Callable[[Rates], float]:
    """A line's sum of per-game z-scores over the ``chosen`` players' columns."""
    cols = [(_column(cat, p), mean, sd) for cat, p, mean, sd in _columns(rates, chosen, cats)]

    def score(r: Rates) -> float:
        z = 0.0
        for col, mean, sd in cols:
            z += (col(r) - mean) / sd
        return z

    return score


def scorer_of[K: Hashable](
    rates: Mapping[K, Rates],
    cats: Sequence[str],
    points: Mapping[str, float] | None = None,
    pool: int = 156,
) -> dict[str, Any]:
    """The scorer :func:`line_value` builds, as data a decision log entry keeps (#126): a points
    league's weights, or for each category over the pool chosen the same way its column's spread
    and, for a percentage, the pool's rate (its makes over its attempts, which the impact column
    weighs a line's attempts by). Unrounded, so that :func:`net_value` values a line exactly as
    the live scorer does net of an empty line; the columns' means are left out, as that needs
    none."""
    if points:
        return {"points": {stat: float(w) for stat, w in points.items()}}
    keys = list(rates)
    first = _z_scorer(rates, keys, cats)
    z = {k: first(rates[k]) for k in keys}
    chosen = sorted(keys, key=lambda k: -z[k])[:pool]
    return {"cats": {cat: {"p": p, "sd": sd} for cat, p, _, sd in _columns(rates, chosen, cats)}}


def net_value(scorer: Mapping[str, Any], line: Mapping[str, float]) -> float:
    """A line's value under ``scorer`` (:func:`scorer_of`) net of an empty line's: per game for a
    per-game line, and for the total of several games their sum (the value is linear)."""
    if "points" in scorer:
        return sum(w * float(line.get(stat, 0.0)) for stat, w in scorer["points"].items())
    total = 0.0
    for cat, c in scorer["cats"].items():
        col = _column(cat, c["p"])
        if col is not None:
            total += col(line) / c["sd"]
    return total
