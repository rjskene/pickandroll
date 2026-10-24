"""The simulated league (#172, PR 1): weeks scored on simulated totals, standings by category
win-loss-tie, the playoff bracket and the title.

A week is scored as the record scores a real one (``season.scorecard``): percentages from the
makes and attempts to Yahoo's three decimals, the lower turnovers winning, a tie half. The
standings order teams by win percentage and then by the tiebreak, parameterised because the
settings page has not been read for it: total category wins, then head to head. The bracket
seeds the top ``playoff_teams`` with ``byes`` byes, reseeds each round (best against worst), and
a playoff tie sends the higher seed through. Pure: pairings, weeks and totals come in from the
league state and the world.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..scorecard import FPTS, total, won
from ..weekly import PCT

#: The tiebreak order the standings apply after win percentage.
TIEBREAK = ("category_wins", "head_to_head")
Totals = Mapping[str, float]


@dataclass(frozen=True)
class LeagueSpec:
    """A league as the simulator plays it: ``pairings`` week number to the matchups (team id
    pairs), ``playoff_weeks`` the weeks the rounds are played in order, ``cats`` the categories
    (a points league names none and carries ``points``, the weights a line's stats score at)."""

    teams: tuple[int, ...]
    pairings: Mapping[int, tuple[tuple[int, int], ...]]
    playoff_weeks: tuple[int, ...]
    cats: tuple[str, ...]
    scoring: str = "categories"
    points: Mapping[str, float] | None = None
    playoff_teams: int = 6
    byes: int = 2
    tiebreak: tuple[str, ...] = TIEBREAK

    @property
    def regular_weeks(self) -> tuple[int, ...]:
        return tuple(sorted(self.pairings))

    @property
    def rounds(self) -> int:
        return math.ceil(math.log2(self.playoff_teams)) if self.playoff_teams > 1 else 0


def fpts(totals: Totals, points: Mapping[str, float]) -> float:
    return sum(float(totals.get(stat, 0.0)) * w for stat, w in points.items())


@dataclass(frozen=True)
class WeekResult:
    """One team's week: categories won, lost and tied (a points league: 1-0-0 or 0-1-0 or
    0-0-1 on the points), and each category's outcome, a tie half."""

    won: float
    lost: float
    tied: float
    cats: Mapping[str, float] = field(default_factory=dict)

    @property
    def outcome(self) -> str:
        if self.won > self.lost:
            return "W"
        if self.won < self.lost:
            return "L"
        return "T"

    @property
    def category_wins(self) -> float:
        return self.won + 0.5 * self.tied


def week_result(mine: Totals, theirs: Totals, spec: LeagueSpec) -> WeekResult:
    """My week against theirs, scored as the record scores a real one."""
    if spec.scoring == "points":
        a, b = fpts(mine, spec.points or {}), fpts(theirs, spec.points or {})
        w = 1.0 if a > b else 0.0 if a < b else 0.5
        return WeekResult(float(w == 1.0), float(w == 0.0), float(w == 0.5), {FPTS: w})
    cats: dict[str, float] = {}
    for cat in spec.cats:
        a = total(mine, cat) if cat in PCT else float(mine.get(cat, 0.0))
        b = total(theirs, cat) if cat in PCT else float(theirs.get(cat, 0.0))
        w = won(cat, a, b)
        cats[cat] = 0.5 if w is None else w
    return WeekResult(
        sum(1.0 for w in cats.values() if w == 1.0),
        sum(1.0 for w in cats.values() if w == 0.0),
        sum(1.0 for w in cats.values() if w == 0.5),
        cats,
    )


def week_results(
    pairs: Sequence[tuple[int, int]], totals: Mapping[int, Totals], spec: LeagueSpec
) -> dict[int, WeekResult]:
    """Every team's result in one week from the week's pairs and totals; a team without a
    pair (a bye) has none."""
    out: dict[int, WeekResult] = {}
    for a, b in pairs:
        ta, tb = totals.get(a, {}), totals.get(b, {})
        out[a] = week_result(ta, tb, spec)
        out[b] = week_result(tb, ta, spec)
    return out


@dataclass(frozen=True)
class Standing:
    team: int
    wins: int
    losses: int
    ties: int
    category_wins: float
    rank: int = 0

    @property
    def pct(self) -> float:
        n = self.wins + self.losses + self.ties
        return (self.wins + 0.5 * self.ties) / n if n else 0.0


def _h2h(
    a: int,
    b: int,
    results: Mapping[int, Mapping[int, WeekResult]],
    pairs: Mapping[int, Sequence[tuple[int, int]]],
) -> float:
    """``a``'s wins (a tie half) over ``b`` in their meetings."""
    score = 0.0
    for week, ps in pairs.items():
        if (a, b) in ps or (b, a) in ps:
            r = results[week].get(a)
            if r is not None:
                score += {"W": 1.0, "T": 0.5, "L": 0.0}[r.outcome]
    return score


def standings(results: Mapping[int, Mapping[int, WeekResult]], spec: LeagueSpec) -> list[Standing]:
    """The teams ranked after the regular weeks in ``results`` (week to team to result): by win
    percentage, then the tiebreak in ``spec.tiebreak`` order, then the team id."""
    rows: dict[int, Standing] = {}
    for team in spec.teams:
        w = l = t = 0
        cw = 0.0
        for week in results:
            r = results[week].get(team)
            if r is None:
                continue
            w += r.outcome == "W"
            l += r.outcome == "L"
            t += r.outcome == "T"
            cw += r.category_wins
        rows[team] = Standing(team, w, l, t, cw)
    ordered = sorted(rows.values(), key=lambda s: (-s.pct, s.team))
    # Break ties level by level: a group tied on everything before a level is ordered by it.
    keys: dict[int, list[float]] = {s.team: [-s.pct] for s in ordered}
    for level in spec.tiebreak:
        groups: dict[tuple[float, ...], list[Standing]] = {}
        for s in ordered:
            groups.setdefault(tuple(keys[s.team]), []).append(s)
        for group in groups.values():
            if len(group) < 2:
                for s in group:
                    keys[s.team].append(0.0)
                continue
            for s in group:
                if level == "category_wins":
                    keys[s.team].append(-s.category_wins)
                elif level == "head_to_head":
                    others = [o.team for o in group if o.team != s.team]
                    keys[s.team].append(
                        -sum(_h2h(s.team, o, results, spec.pairings) for o in others)
                    )
                else:
                    raise ValueError(f"unknown tiebreak {level!r}")
        ordered.sort(key=lambda s: (*keys[s.team], s.team))
    return [
        Standing(s.team, s.wins, s.losses, s.ties, s.category_wins, i + 1)
        for i, s in enumerate(ordered)
    ]


# --------------------------------------------------------------------------- playoffs
def bracket(seeds: Sequence[int], playoff_teams: int, byes: int) -> list[tuple[int, int]]:
    """The first round's pairs by seed number (1 the best): the ``byes`` top seeds sit out and
    the rest pair best against worst. ``byes`` must make the field a power of two."""
    rounds = math.ceil(math.log2(playoff_teams))
    if 2**rounds - playoff_teams != byes:
        raise ValueError(
            f"{playoff_teams} teams with {byes} byes is not a bracket of {rounds} rounds"
        )
    playing = list(range(byes + 1, playoff_teams + 1))
    return [(playing[i], playing[-1 - i]) for i in range(len(playing) // 2)]


@dataclass(frozen=True)
class Playoffs:
    """``rounds`` lists each round's matchups as (higher seed, lower seed, winner's seed);
    ``seeds`` maps seed number to team; ``champion`` is the title's team."""

    seeds: Mapping[int, int]
    rounds: tuple[tuple[tuple[int, int, int], ...], ...]
    champion: int | None


def playoffs(
    seeds: Mapping[int, int],
    totals: Mapping[int, Mapping[int, Totals]],
    spec: LeagueSpec,
) -> Playoffs:
    """The bracket played out on ``totals`` (week to team to totals) over ``spec.playoff_weeks``,
    reseeded each round, a tie going to the higher seed."""
    rounds_needed = spec.rounds
    weeks = spec.playoff_weeks[:rounds_needed]
    if len(weeks) < rounds_needed:
        raise ValueError(
            f"{rounds_needed} playoff rounds need {rounds_needed} weeks, {len(weeks)} given"
        )
    alive = list(range(1, spec.playoff_teams + 1))
    first = bracket(alive, spec.playoff_teams, spec.byes)
    played: list[tuple[tuple[int, int, int], ...]] = []
    for i, week in enumerate(weeks):
        if i == 0:
            pairs = first
            resting = alive[: spec.byes]
        else:
            alive.sort()
            pairs = [(alive[j], alive[-1 - j]) for j in range(len(alive) // 2)]
            resting = []
        this: list[tuple[int, int, int]] = []
        survivors = list(resting)
        for hi, lo in pairs:
            a, b = seeds[hi], seeds[lo]
            r = week_result(totals.get(week, {}).get(a, {}), totals.get(week, {}).get(b, {}), spec)
            winner = hi if r.outcome in ("W", "T") else lo
            this.append((hi, lo, winner))
            survivors.append(winner)
        played.append(tuple(this))
        alive = survivors
    champion = seeds[alive[0]] if len(alive) == 1 else None
    return Playoffs(dict(seeds), tuple(played), champion)


# --------------------------------------------------------------------------- a season
@dataclass(frozen=True)
class Outcome:
    """One team's season: final regular-season rank, the playoffs made, the title, category
    wins and matchup wins (a tie half) over the regular weeks, and the record."""

    team: int
    rank: int
    made_playoffs: bool
    title: bool
    category_wins: float
    matchup_wins: float
    record: tuple[int, int, int]


@dataclass(frozen=True)
class SeasonResult:
    standings: tuple[Standing, ...]
    playoffs: Playoffs
    outcomes: Mapping[int, Outcome]
    results: Mapping[int, Mapping[int, WeekResult]]


def season(spec: LeagueSpec, totals: Mapping[int, Mapping[int, Totals]]) -> SeasonResult:
    """The season from every week's totals (week to team to totals): the regular weeks scored
    on the pairings, the standings, the bracket and each team's outcome."""
    results = {
        week: week_results(spec.pairings[week], totals.get(week, {}), spec)
        for week in spec.regular_weeks
    }
    table = standings(results, spec)
    seeds = {s.rank: s.team for s in table if s.rank <= spec.playoff_teams}
    post = (
        playoffs(seeds, totals, spec)
        if spec.playoff_teams and spec.playoff_weeks
        else Playoffs({}, (), None)
    )
    outcomes = {
        s.team: Outcome(
            s.team,
            s.rank,
            s.rank <= spec.playoff_teams,
            post.champion == s.team,
            s.category_wins,
            s.wins + 0.5 * s.ties,
            (s.wins, s.losses, s.ties),
        )
        for s in table
    }
    return SeasonResult(tuple(table), post, outcomes, results)


def summary(result: SeasonResult, me: int) -> dict[str, Any]:
    """My outcome as a plain dict, for a run's record."""
    o = result.outcomes[me]
    return {
        "rank": o.rank,
        "made_playoffs": o.made_playoffs,
        "title": o.title,
        "category_wins": o.category_wins,
        "matchup_wins": o.matchup_wins,
        "record": list(o.record),
    }
