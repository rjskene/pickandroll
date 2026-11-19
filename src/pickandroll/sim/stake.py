"""The week's stake (#172, the guard PR): how much a win this week moves a seat's playoff odds.

``L``, between 0 and 1, is read by an arm that names a ``stake`` (``policy.season_weight_of``):
the season weight in force that week is ``season_weight x (1 - stake x L)``, so a seat whose week
decides its season trades less of it for later. The ruling fixes the idea (the gap to the cut
line against the weeks left, and full in the playoffs); the formula is a working default.

**In a regular week** (:func:`level`). The standings are the league's own
(``league.standings`` over ``league.week_results``) of the regular weeks finished before this
one: the running week is not read. A team's :func:`measure` is its wins plus half its ties, or
where every category counts its category wins (a tie half) over the number of categories: its
standing in weeks. The seat's :func:`lead` is its measure less the cut line's team's: the best
team outside the field when the seat is inside it, the last team inside when it is outside; 0
with no week finished. ``delta`` is the lead in units of one week's spread, the lead over the
root of :func:`variance`, the variance of one team's one week at even odds: a quarter where a
week is one result, a quarter over the number of categories where every category counts (the
categories taken as independent, an assumption). With ``n`` regular weeks after this one
(:func:`swing`),

    L = [Phi((delta + 1) / sqrt(2n + 1)) - Phi((delta - 1) / sqrt(2n + 1))] / [Phi(1) - Phi(-1)]

the chance that everything else (both teams' later weeks and the line's team's this week, each
a draw of that spread) leaves the lead within one week's swing of zero, so that this week
decides it, scaled so that a seat level with the line in the last regular week has ``L`` 1. It
is small early, rises as the weeks run out for a seat near the line and falls to nothing for a
seat far from it, ahead or behind.

**In the bracket's weeks** it is 1 for a seat inside the field by the regular season's final
standings and 0 for a seat outside. Who is knocked out inside the bracket is not read (a limit).

``Phi`` is from ``math.erf``, and ``L`` is rounded to :data:`DECIMALS` places before anything
reads it, so two machines whose ``erf`` differs in the last bit decide alike (the lesson of
#387). Pure: a function of the finished weeks' totals, the league's spec, the team and the week.
No engine import.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from . import league as lg

#: The places ``L`` is rounded to before anything reads it.
DECIMALS = 12
#: The variance of one team's one week at even odds where a week is one result: a win or a loss,
#: each a half.
WEEK_VARIANCE = 0.25


def phi(x: float) -> float:
    """The standard normal's distribution function, from ``math.erf``."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


#: The chance a standard normal lies within one of zero: what :func:`swing` is scaled by, so a
#: lead of 0 with no week after this one gives 1.
WITHIN_ONE = phi(1.0) - phi(-1.0)


def swing(delta: float, weeks_after: int) -> float:
    """``L`` from ``delta``, the lead in units of one week's spread, and ``weeks_after``, the
    regular weeks after this one (the module's formula), rounded to :data:`DECIMALS` places and
    kept within 0 and 1."""
    spread = math.sqrt(2 * max(0, int(weeks_after)) + 1)
    raw = (phi((delta + 1.0) / spread) - phi((delta - 1.0) / spread)) / WITHIN_ONE
    return min(1.0, max(0.0, round(raw, DECIMALS)))


def measure(row: lg.Standing, spec: lg.LeagueSpec) -> float:
    """A team's standing in weeks: its wins plus half its ties (a league that counts one win a
    matchup, and a points league); where every category counts, its category wins, a tie half,
    over the number of categories."""
    if lg.each_category(spec) and spec.cats:
        return row.category_wins / len(spec.cats)
    return row.wins + 0.5 * row.ties


def variance(spec: lg.LeagueSpec) -> float:
    """The variance of one team's one week at even odds, in :func:`measure`'s unit: a quarter
    where a week is one result; a quarter over the number of categories where every category
    counts, the categories taken as independent."""
    if lg.each_category(spec) and spec.cats:
        return WEEK_VARIANCE / len(spec.cats)
    return WEEK_VARIANCE


def table_before(
    spec: lg.LeagueSpec, totals: Mapping[int, Mapping[int, lg.Totals]], week: int | None
) -> list[lg.Standing]:
    """The league's own standings over the regular weeks numbered before ``week`` (every regular
    week when ``week`` is None), from the weeks' ``totals`` (week to team to totals): the order,
    the format and the tiebreaks are ``league.standings``'s, on the league's spec with the
    pairings of those weeks alone (a head-to-head tiebreak then reads the meetings played, not
    the ones to come). A week with no totals is a week everyone tied, as the season's own
    standings read it."""
    finished = [w for w in spec.regular_weeks if week is None or w < week]
    played = replace(spec, pairings={w: spec.pairings[w] for w in finished})
    results = {w: lg.week_results(spec.pairings[w], totals.get(w, {}), spec) for w in finished}
    return lg.standings(results, played)


def lead(table: Sequence[lg.Standing], spec: lg.LeagueSpec, team: int) -> float | None:
    """``team``'s lead over the cut line in ``table``, in weeks (:func:`measure`): its measure
    less the line's team's, the best team outside the field when it is inside (rank
    ``playoff_teams + 1``), the last team inside when it is outside. None when the league has no
    line (no field, or every team in it) or the table does not hold the team."""
    by_rank = {row.rank: row for row in table}
    mine = next((row for row in table if row.team == team), None)
    field = int(spec.playoff_teams)
    if mine is None or field < 1 or field >= len(table):
        return None
    line = by_rank[field + 1] if mine.rank <= field else by_rank[field]
    return measure(mine, spec) - measure(line, spec)


def level(
    spec: lg.LeagueSpec, totals: Mapping[int, Mapping[int, lg.Totals]], team: int, week: int
) -> float:
    """``L``, the stake of week ``week`` for ``team``, from the weeks' ``totals`` (week to team to
    totals; only the regular weeks finished before ``week`` are read). In one of the bracket's
    weeks: 1 for a team inside the field by the regular season's final standings, 0 for one
    outside. In any other week the module's formula (:func:`swing` of the lead and the regular
    weeks after this one); 0 in a league with no cut line, where no win moves the field."""
    if week in spec.playoff_weeks:
        final = table_before(spec, totals, None)
        inside = {row.team for row in final if row.rank <= spec.playoff_teams}
        return 1.0 if team in inside else 0.0
    gap = lead(table_before(spec, totals, week), spec, team)
    if gap is None:
        return 0.0
    after = sum(1 for w in spec.regular_weeks if w > week)
    return swing(gap / math.sqrt(variance(spec)), after)


__all__ = [
    "DECIMALS",
    "WEEK_VARIANCE",
    "WITHIN_ONE",
    "lead",
    "level",
    "measure",
    "phi",
    "swing",
    "table_before",
    "variance",
]
