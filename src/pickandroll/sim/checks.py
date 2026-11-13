"""What the gates are fed (#172, PR 2b): samples drawn from a world, pure.

The gates in ``validate`` are functions on arrays. These build the arrays: a team's week under
the simulator many times over (gate 1, and the simulator's matchup odds of gate 2 beside the
engine's analytic odds), player-games missed a week under the hazard (gate 4), and the
surrogate's set against the exact set on sampled league-days (gate 5). Gate 3's band is the
share's distribution over sampled moves (:func:`share_band`); its rows wait on the scorecard's
realized values (PR 3). The script reads the records and calls these with the season each
is scored on.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date

import numpy as np

from .. import weekly as wk
from . import league as lg
from . import policy, world
from .fit import Hazard
from .run import World
from .state import Roster, Setup, SimState, initial

#: The counting categories a team-week transform is read on (percentages are ratios of two).
COUNTING = ("pts", "threes", "reb", "ast", "stl", "blk", "tov")


def team_week(
    setup: Setup, w: World, roster: Roster, days: Sequence[date], value: Mapping[int, float]
) -> dict[str, float]:
    """One team's week in one world: each day's best starters among those playing and not
    heard out, their lines summed."""
    totals: dict[str, float] = {}
    slots = setup.starting_slots()
    for day in days:
        status, _ = w.status_on(day)
        playing = [
            (k, setup.players[k].positions)
            for k, slot in roster
            if slot not in policy.mv.HELD
            and k in setup.players
            and setup.players[k].nba_team in setup.schedule.get(day, frozenset())
            and status.get(k) not in wk.OUT_ALL
            and status.get(k) not in wk.OUT_THIS_WEEK
        ]
        for k in wk.starters(playing, slots, value):
            ln = w.line(k, day)
            if ln:
                for stat, x in ln.items():
                    if stat != "minutes_factor":
                        totals[stat] = totals.get(stat, 0.0) + float(x)
    return totals


def team_week_samples(
    setup: Setup,
    worlds: Callable[[int], World],
    roster: Roster,
    days: Sequence[date],
    paths: int,
) -> list[dict[str, float]]:
    """``paths`` draws of a team's week, one a world."""
    value = wk.per_game_values(setup.projection, setup.cats, setup.points)
    return [team_week(setup, worlds(p), roster, days, value) for p in range(paths)]


def transforms(
    realized: Mapping[str, float],
    samples: Sequence[Mapping[str, float]],
    stats: Sequence[str] = COUNTING,
) -> list[float]:
    """Where each realized counting total falls among the samples (gate 1's input)."""
    from .validate import pit

    out = []
    for stat in stats:
        if stat in realized:
            out.append(pit(float(realized[stat]), [float(s.get(stat, 0.0)) for s in samples]))
    return out


def simulated_odds(
    mine: Sequence[Mapping[str, float]],
    theirs: Sequence[Mapping[str, float]],
    spec: lg.LeagueSpec,
) -> float:
    """The share of paired samples in which I win the week (a tie half)."""
    if not mine or not theirs:
        return 0.5
    wins = 0.0
    for a, b in zip(mine, theirs, strict=True):
        r = lg.week_result(dict(a), dict(b), spec)
        wins += 1.0 if r.won > r.lost else 0.5 if r.won == r.lost else 0.0
    return wins / len(mine)


def engine_odds(
    setup: Setup, beliefs: Mapping[int, wk.Rates], me: Roster, other: Roster, days: Sequence[date]
) -> float:
    """The engine's analytic odds of my week against ``other`` on the same beliefs."""
    value = wk.per_game_values(beliefs, setup.cats, setup.points)
    slots = setup.starting_slots()

    def project(roster: Roster) -> wk.TeamWeek:
        members = [(k, setup.players[k].player()) for k, _ in roster if k in setup.players]
        return wk.project_week(members, beliefs, days, setup.schedule, slots, value, True)

    odds = wk.category_odds(project(me), project(other), setup.cats)
    return float(wk.matchup_won(odds))


def missed_samples(
    hazard: Hazard, scheduled: Sequence[Sequence[int]], paths: int, seed: int
) -> np.ndarray:
    """``scheduled[i]`` is one player's games a week over his season, in order; each path draws
    his whole season's availability under the hazard once and splits it into those weeks, so an
    absence that began in one week is still missed in the next (as it is in the logs). The rows
    are the player-weeks in order, flattened: gate 4's samples."""
    rows = sum(len(weeks) for weeks in scheduled)
    out = np.zeros((rows, paths), dtype=int)
    row = 0
    for i, weeks in enumerate(scheduled):
        sizes = [int(n) for n in weeks]
        total = sum(sizes)
        for p in range(paths):
            ok, _ = world.absences(seed, p, i, total, hazard)
            start = 0
            for j, n in enumerate(sizes):
                out[row + j, p] = n - int(ok[start : start + n].sum())
                start += n
        row += len(sizes)
    return out


def surrogate_matches(
    setup: Setup,
    w: World,
    team: int,
    days: Sequence[date],
    knobs: Mapping[str, object],
) -> list[bool]:
    """On each of ``days``, from day one's rosters, whether the surrogate's set equals the exact
    set (as sets of moves): gate 5's input."""
    out = []
    base = initial(setup)
    week0 = setup.calendar.week_of(setup.start)
    for day in days:
        week = setup.calendar.week_of(day)
        if week is None or week0 is None:
            continue
        beliefs = w.beliefs(week.number - week0.number)
        status, returns = w.status_on(day)
        state = SimState(day, base.rosters, base.pool, {})
        built = policy.problem_of(setup, state, team, knobs, beliefs, status, returns)
        if built is None:
            continue
        exact = set(policy.exact(built, with_plan=False).moves)
        surrogate = set(policy.surrogate(built).moves)
        out.append(exact == surrogate)
    return out


def share_band(
    projected: Sequence[float], realized_samples: Sequence[Sequence[float]]
) -> list[float]:
    """The share (realized over projected, summed over the moves) in each sampled path: gate
    3's samples, given each move's projected value and its realized value a path."""
    total = sum(projected)
    if total <= 0 or not realized_samples:
        return []
    return [sum(path) / total for path in zip(*realized_samples, strict=True)]


__all__ = [
    "COUNTING",
    "engine_odds",
    "missed_samples",
    "share_band",
    "simulated_odds",
    "surrogate_matches",
    "team_week",
    "team_week_samples",
    "transforms",
]
