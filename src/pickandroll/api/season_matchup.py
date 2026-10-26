"""The Matchup view (#116): my matchup this week as a scoreboard, and what each player adds to it.

The finals and the odds are the move model's own for the rest of the week (``season_moves.build``:
the same first day, starters, games and rates), so the view, the Moves card and the Strategy card
agree. A category's final is the week so far plus the rest of the week; the matchup odds are
:func:`weekly.matchup_won` on the category odds (independent categories, a headline), expected
categories their sum.

A player's contribution is the week played without him from the first day on, his starts going
to the bench by the daily starters (the move model's drop path, ``moves.project_mine``): Cats is
the expected categories he adds, Matchup the matchup odds he adds, and in a points league Points
the fantasy points. The opponent's players are valued the same way, for the opponent. A player
with no start left adds nothing and is not re-projected.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ..season import Season
from ..season import moves as mv
from ..season import weekly as wk
from . import season_week as sw
from .season_moves import Built

#: The players' per-game line as sent: the counting stats, the makes and attempts, and the
#: percentages and fantasy points worked out from them.
_ONE_GAME = wk.PlayerWeek(1, 1)


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


def so_far_value(so_far: Mapping[str, float], cat: str) -> float | None:
    """A category's week so far from the matchup page's totals in our stat names."""
    if cat in wk.PCT:
        made, att = wk.PCT[cat]
        a = so_far.get(att, 0.0)
        return so_far.get(made, 0.0) / a if a else None
    return so_far.get(cat) if so_far else None


def per_game(rates: wk.Rates | None, points: Mapping[str, float] | None) -> dict[str, Any] | None:
    line = wk.player_totals(_ONE_GAME, rates, points)
    return None if line is None else {k: _r(v) for k, v in line.items()}


def payload(built: Built, season: Season) -> dict[str, Any] | None:
    """The scoreboard and both teams' players, or None without a named opponent this week."""
    p = built.problem
    span = p.horizons["week"][0]
    mine = season.settings.my_team_id
    matchup, read_at = sw.matchup_read(season, mine)
    if mine is None or matchup is None or not span.opponents:
        return None
    other = matchup.opponent_of(mine)
    if other is None:
        return None
    cats = p.cats
    theirs_so_far = span.so_far_theirs[0] if span.so_far_theirs else {}
    their_members = [(s.player.yahoo_id, s.player) for s in season.rosters.get(other, ())]

    def their_week(gone: Mapping[int, date]) -> wk.TeamWeek:
        # As ``season_moves.build`` projects the named opponent (``span.opponents``), less one.
        return wk.project_week(
            their_members,
            p.rates,
            span.days,
            p.schedule,
            p.slots,
            p.value,
            True,
            games=span.games,
            points=p.points,
            no_games=p.no_games,
            gone_from=gone,
        )

    full_mine = mv.project_mine(p, span)
    full_theirs = span.opponents[0]
    fm = wk.finals(full_mine, span.so_far, cats)
    ft = wk.finals(full_theirs, theirs_so_far, cats)
    odds = wk.odds_of(fm, ft, cats)
    expected, win = wk.expected_won(odds), wk.matchup_won(odds)
    # None on the week's last day read once its games began (#209): no day left, no player
    # started, so nobody is taken out.
    first = span.days[0] if span.days else None

    def row(key: int, slot: str, week: wk.TeamWeek, without: Sequence[wk.CategoryOdds] | None):
        pw = week.players.get(key, wk.PlayerWeek(0, 0))
        if without is None:
            cats_, odds_ = 0.0, 0.0
        else:
            cats_, odds_ = expected - wk.expected_won(without), win - wk.matchup_won(without)
        return {
            "player": key,
            "slot": slot,
            "games": pw.games,
            "started": pw.started,
            "per_game": per_game(p.rates.get(key), p.points),
            "cats": round(cats_, 4),
            "matchup": round(odds_, 4),
        }

    def order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # The largest Matchup first, the players with no game left last.
        return sorted(rows, key=lambda r: (r["games"] == 0, -r["matchup"], -r["cats"]))

    slots = {s.player.yahoo_id: s.slot for s in season.rosters.get(mine, ())}
    mine_rows = []
    for key, _ in [*p.held, *p.roster]:
        without = None
        if full_mine.players.get(key, wk.PlayerWeek(0, 0)).started:
            week = mv.project_mine(p, span, gone={key: first})
            without = wk.odds_of(wk.finals(week, span.so_far, cats), ft, cats)
        mine_rows.append(row(key, slots.get(key, ""), full_mine, without))
    their_slots = {s.player.yahoo_id: s.slot for s in season.rosters.get(other, ())}
    their_rows = []
    for key, _ in their_members:
        r = row(key, their_slots.get(key, ""), full_theirs, None)
        if full_theirs.players.get(key, wk.PlayerWeek(0, 0)).started:
            week = their_week({key: first})
            without = wk.odds_of(fm, wk.finals(week, theirs_so_far, cats), cats)
            # What he adds for them: my odds without him less my odds with him.
            r["cats"] = round(wk.expected_won(without) - expected, 4)
            r["matchup"] = round(wk.matchup_won(without) - win, 4)
        their_rows.append(r)

    score = list(matchup.score) if matchup.score else None
    if score and mine != matchup.teams[0]:
        score = score[::-1]
    tied = None
    if score is not None and p.points is None:
        tied = max(0, len(cats) - int(score[0]) - int(score[1]))
    week = season.calendar.week(matchup.week) if season.calendar else None
    return {
        "system": built.system,
        "week": matchup.week,
        "start": week.start.isoformat() if week else None,
        "end": week.end.isoformat() if week else None,
        "from": first.isoformat() if first else None,
        "days": len(span.days),
        "teams": [mine, other],
        # A team whose page was never read projects as an empty roster.
        "rosters_read": [mine in season.rosters, other in season.rosters],
        "so_far_at": read_at.isoformat() if read_at else None,
        "score": score,
        "tied": tied,
        "cats": [
            {
                "cat": o.cat,
                "mine": _r(o.mine),
                "theirs": _r(o.theirs),
                "so_far": [
                    _r(so_far_value(span.so_far, o.cat)),
                    _r(so_far_value(theirs_so_far, o.cat)),
                ],
                "sd": _r(o.sd),
                "p_win": _r(o.p_win),
            }
            for o in odds
        ],
        "expected": round(expected, 4),
        "win": round(win, 4),
        "players": {"mine": order(mine_rows), "theirs": order(their_rows)},
    }
