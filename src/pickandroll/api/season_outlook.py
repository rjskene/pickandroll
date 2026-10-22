"""The Season view (#116): every week left of my season as win odds, and each week's scoreboard
and what my players add to it.

This week is the move model's own (``season_moves.build``'s week span: the week so far, the
named opponent, the same first day), so its chip agrees with the Matchup view. A later week is
projected the same way from its first day, with today's rosters: nobody is added or dropped,
and an O sits out this week only (``weekly.is_out``). Its opponent is the one the league page
shown for that week pairs me with (``Season.pairings``); a week whose pairs were never read,
or a playoff week, is played against the field: every other team whose roster was read, its
odds and its finals the average over them (the move model's later weeks).

A week counts toward the summary when it is a regular week (before
``Season.first_playoff_week``): its matchup odds summed are the wins expected, and a week is
favoured, a toss-up or an underdog by the 60 % and 40 % lines when its opponent is named. A
player's contribution is the week played without him from its first day, his starts going to
the bench (``moves.project_mine``, as in the Matchup view).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from ..season import Matchup, Season
from ..season import moves as mv
from ..season import weekly as wk
from . import season_week as sw
from .season_moves import Built

#: The matchup odds a named week is favoured from, and an underdog below.
FAVOURED = 0.6
UNDERDOG = 0.4


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None else round(x, n)


def _mean(xs: Sequence[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def lean(win: float | None) -> str | None:
    """A named week's lean by its matchup odds."""
    if win is None:
        return None
    return "favoured" if win >= FAVOURED else "underdog" if win <= UNDERDOG else "toss_up"


def payload(built: Built, season: Season, today: date, data_dir: Path) -> dict[str, Any] | None:
    """Every week left from this one, or None without my team or the season's weeks."""
    p = built.problem
    s = season.settings
    mine = s.my_team_id
    if mine is None or season.calendar is None:
        return None
    cats = p.cats
    this = p.horizons["week"][0]
    matchup, _ = sw.matchup_read(season, mine)
    players = sw.season_players(season)
    ahead = sw.spans(season, today, data_dir, len(season.calendar.weeks), players, p.first_day)
    playoffs_from = season.first_playoff_week
    others = [t for t in season.rosters if t != mine]
    slots = {sp.player.yahoo_id: sp.slot for sp in season.rosters.get(mine, ())}

    def project(team: int, span: mv.WeekSpan) -> wk.TeamWeek:
        # As ``season_moves.build`` projects an opponent.
        members = [(sp.player.yahoo_id, sp.player) for sp in season.rosters.get(team, ())]
        return wk.project_week(
            members,
            p.rates,
            span.days,
            p.schedule,
            p.slots,
            p.value,
            span.this_week,
            games=span.games,
            points=p.points,
            no_games=p.no_games,
        )

    weeks = []
    for i, sp in enumerate(ahead):
        if not sp.days:
            continue
        if i == 0:
            span = this
            opponent = matchup.opponent_of(mine) if matchup is not None else None
        else:
            span = mv.WeekSpan(tuple(sp.days), False, (), games=sp.games)
            opponent = season.opponent_in(mine, sp.week.number)
        if i == 0 and opponent is not None and this.opponents:
            # The move model's projection of the named opponent, and his week so far.
            so_far = this.so_far_theirs[0] if this.so_far_theirs else {}
            read = opponent in season.rosters
            theirs = [wk.finals(this.opponents[0], so_far, cats)] if read else []
        else:
            facing = [opponent] if opponent is not None else others
            theirs = [wk.finals(project(t, span), {}, cats) for t in facing if t in season.rosters]
        playoffs = playoffs_from is not None and sp.week.number >= playoffs_from
        weeks.append(
            _week(p, span, sp, opponent, theirs, slots, playoffs, matchup if i == 0 else None, mine)
        )

    me = season.team(mine)
    regular = [w for w in weeks if not w["playoffs"]]
    leans = [lean(w["win"]) for w in regular if w["opponent"] is not None]
    return {
        "system": built.system,
        "today": today.isoformat(),
        "team": mine,
        "record": me.record if me else None,
        "first_playoff_week": playoffs_from,
        "summary": {
            "weeks": len(regular),
            "expected_wins": _r(sum(w["win"] for w in regular if w["win"] is not None), 2),
            "expected_cats": _r(
                sum(w["expected"] for w in regular if w["expected"] is not None), 2
            ),
            "favoured": leans.count("favoured"),
            "toss_up": leans.count("toss_up"),
            "underdog": leans.count("underdog"),
            "field": sum(1 for w in regular if w["opponent"] is None),
            "unread": sum(1 for w in regular if w["win"] is None),
        },
        "weeks": weeks,
    }


def _week(
    p: mv.MoveProblem,
    span: mv.WeekSpan,
    sp: sw.Span,
    opponent: int | None,
    theirs: Sequence[Mapping[str, wk.Final]],
    slots: Mapping[int, str],
    playoffs: bool,
    matchup: Matchup | None,
    mine: int,
) -> dict[str, Any]:
    """One week: my finals against each team faced (one, or the field), averaged."""
    cats = p.cats
    full = mv.project_mine(p, span)
    fm = wk.finals(full, span.so_far, cats)

    def against(finals: Mapping[str, wk.Final]) -> tuple[list[list[wk.CategoryOdds]], float, float]:
        odds = [wk.odds_of(finals, t, cats) for t in theirs]
        expected = _mean([wk.expected_won(o) for o in odds]) or 0.0
        win = _mean([wk.matchup_won(o) for o in odds]) or 0.0
        return odds, expected, win

    read = bool(theirs)
    odds, expected, win = against(fm) if read else ([], 0.0, 0.0)
    first = span.days[0]
    rows = []
    for key, _ in [*p.held, *p.roster]:
        pw = full.players.get(key, wk.PlayerWeek(0, 0))
        cats_ = odds_ = 0.0
        if read and pw.started:
            gone = mv.project_mine(p, span, gone={key: first})
            _, e, w = against(wk.finals(gone, span.so_far, cats))
            cats_, odds_ = expected - e, win - w
        rows.append(
            {
                "player": key,
                "slot": slots.get(key, ""),
                "games": pw.games,
                "started": pw.started,
                "cats": round(cats_, 4),
                "matchup": round(odds_, 4),
            }
        )
    rows.sort(key=lambda r: (r["games"] == 0, -r["matchup"], -r["cats"]))

    cat_rows = []
    for j, cat in enumerate(cats):
        per = [o[j] for o in odds]
        given = [o.theirs for o in per if o.theirs is not None]
        cat_rows.append(
            {
                "cat": cat,
                "mine": _r(fm[cat][0]),
                "theirs": _r(_mean(given)),
                "p_win": _r(_mean([o.p_win for o in per])),
            }
        )
    score = tied = None
    if matchup is not None and matchup.score:
        score = list(matchup.score) if matchup.teams[0] == mine else list(matchup.score)[::-1]
        if p.points is None:
            tied = max(0, len(cats) - int(score[0]) - int(score[1]))
    return {
        "week": sp.week.number,
        "start": sp.week.start.isoformat(),
        "end": sp.week.end.isoformat(),
        "from": first.isoformat(),
        "days": len(span.days),
        "this_week": span.this_week,
        "playoffs": playoffs,
        "opponent": opponent,
        # The teams averaged over when the week is played against the field.
        "field": None if opponent is not None else len(theirs),
        "rosters_read": read,
        # Whether the NBA schedule covers every day the week counts games on.
        "scheduled": span.games is not None or all(d in p.schedule for d in span.days),
        "score": score,
        "tied": tied,
        "expected": round(expected, 4) if read else None,
        "win": round(win, 4) if read else None,
        "games": sum(r["games"] for r in rows),
        "started": sum(r["started"] for r in rows),
        "cats": cat_rows,
        "players": rows,
    }
