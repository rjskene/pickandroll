"""The Matchup view (#116): my matchup this week as a scoreboard, and what each player adds to it.

The finals and the odds are the move model's own for the rest of the week (``season_moves.build``:
the same first day, starters, games and rates), so the view, the Moves card and the Strategy card
agree. A category's final is the week so far plus the rest of the week; the matchup odds are
:func:`weekly.matchup_won` on the category odds (independent categories, a headline), expected
categories their sum.

My week counts the recommended starters (``season_lineup.recommended``, #314), the Lineup view's.
A player's contribution is the week played without him from the first day on, his starts going
to the bench (the move model's drop path, ``moves.project_mine``; the other starters stay): Cats is
the expected categories he adds, Matchup the matchup odds he adds, and in a points league Points
the fantasy points. The opponent's players are valued the same way, for the opponent. A player
with no start left adds nothing and is not re-projected.

Each player's week comes as three lines (#304): ``so_far``, his line on that team as Yahoo
counts it (the matchup page's player table, its makes, attempts and games placed from his box
scores by ``season.so_far``), ``rest``, the move model's projection of his starts left, and
``total``, the two added; percentages are made over attempted, never an average. Each team's
lines sum them the scoreboard's way: ``so_far`` is Yahoo's count, ``gap`` what of it is on no
player's row (a player dropped this week, the makes and attempts of a player the box scores
could not place), ``rest`` the projection's totals and ``total`` the projected final; a finished
day the matchup page was read before is in neither half and listed in ``unread``.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import Season
from ..season import moves as mv
from ..season import so_far as sf
from ..season import weekly as wk
from ..sources import boxscores
from . import season_lineup as sl
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


#: A team line's keys: the stats, the percentages and the fantasy points.
_LINE = (*wk.STATS, *wk.PCT, wk.FPTS)


def box_days(season: Season, today: date) -> list[date]:
    """This matchup week's finished days, the ones the box scores may hold (none from today)."""
    week = season.calendar.week_of(today) if season.calendar else None
    if week is None:
        return []
    last = min(week.end, today - timedelta(1))
    return [week.start + timedelta(n) for n in range((last - week.start).days + 1)]


def box_lines(cache_dir: Path, season: Season, today: date) -> dict[int, list[dict[str, float]]]:
    """The box-score lines this week of every player on both rosters of my matchup that the
    cache (``sources.boxscores``, the refresh's) holds: the games he played, in date order. Reads
    the cache and the ids matched so far only: a player matched by name here is not kept."""
    days = boxscores.load_days(box_days(season, today), cache_dir)
    games = [g for day in sorted(days) for g in days[day]]
    if not games:
        return {}
    players = {
        s.player.yahoo_id: (s.player.name, s.player.nba_team)
        for spots in season.rosters.values()
        for s in spots
    }
    out: dict[int, list[dict[str, float]]] = {}
    for yahoo, (espn, _) in boxscores.match(players, games, boxscores.load_ids(cache_dir)).items():
        out[yahoo] = [
            dict(p["line"])
            for g in games
            if (p := (g.get("players") or {}).get(espn)) is not None and p.get("line")
        ]
    return out


def _with_pct(line: dict[str, Any]) -> dict[str, Any]:
    for cat, (made, att) in wk.PCT.items():
        if made not in line and att not in line:
            continue
        m, a = line.get(made), line.get(att)
        line[cat] = m / a if m is not None and a else None
    return line


def _rounded(line: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _r(v) if isinstance(v, float) else v for k, v in line.items()}


def rest_line(week: wk.PlayerWeek, rates: wk.Rates | None, points: Mapping[str, float] | None):
    """His starts left times his per-game line; None with no rates (the projection gives him
    nothing)."""
    line = wk.player_totals(week, rates, points)
    if line is None:
        return None
    return {**line, "games": week.games, "started": week.started}


def total_line(so: sf.SoFar, rest: Mapping[str, Any] | None) -> dict[str, Any]:
    """His week so far plus the rest of it: a stat unknown in either half is unknown, and a
    percentage is made over attempted, unknown without the attempts so far."""
    keys = [*wk.STATS, *([wk.FPTS] if wk.FPTS in so.line else [])]
    line: dict[str, Any] = {}
    for k in keys:
        a = so.line.get(k)
        b = 0.0 if rest is None else rest.get(k)
        line[k] = None if a is None or b is None else a + b
    _with_pct(line)
    left = 0 if rest is None else rest["games"]
    line["games"] = None if so.games is None else so.games + left
    return line


def team_lines(
    so_far: Mapping[str, float],
    played: int | None,
    rows: Sequence[Mapping[str, Any]],
    week: wk.TeamWeek,
    points: bool,
) -> dict[str, Any]:
    """A team's lines (``so_far``, ``gap``, ``rest``, ``total``): Yahoo's count, what of it is on
    no player's row (None when nothing), the projection's totals and the projected final. A
    points league's count is its fantasy points alone."""
    count: dict[str, Any] = dict(so_far)
    keys = [k for k in (*wk.STATS, wk.FPTS) if k in count]
    gap = {k: count[k] - sum(r["so_far"].get(k) or 0.0 for r in rows) for k in keys}
    known = [r["so_far"]["games"] for r in rows]
    if played is not None:
        gap["games"] = played - sum(g for g in known if g is not None)
    gap = _with_pct(gap) if any(abs(v) > 1e-6 for v in gap.values() if v is not None) else None
    count["games"] = played
    rest: dict[str, Any] = {k: float(week.totals.get(k, 0.0)) for k in (*wk.STATS, wk.FPTS)}
    if not points:
        rest.pop(wk.FPTS)
    rest["games"] = sum(pw.games for pw in week.players.values())
    rest["started"] = sum(pw.started for pw in week.players.values())
    total = {k: count.get(k, 0.0) + rest[k] for k in rest if k not in ("games", "started")}
    if points:
        total = {wk.FPTS: total[wk.FPTS]}
    total["games"] = None if played is None else played + rest["games"]
    return {
        "so_far": _rounded(_with_pct(count)),
        "gap": None if gap is None else _rounded(gap),
        "rest": _rounded(_with_pct(rest)),
        "total": _rounded(_with_pct(total)),
    }


def unread_days(
    read_at: datetime | None, first: date | None, week_start: date, week_end: date
) -> list[date]:
    """The finished days in neither half of the week: from the day the matchup page was read
    (the day after, when it was read once that day's games began) to the day before the first
    projected, within the week."""
    start = week_start
    if read_at is not None:
        local = read_at.astimezone(sw.NBA_TZ)
        start = max(start, local.date() + timedelta(1 if local.time() >= sw.GAMES_BEGIN else 0))
    stop = first if first is not None else week_end + timedelta(1)
    return [start + timedelta(n) for n in range((stop - start).days)]


def payload(
    built: Built,
    season: Season,
    today: date,
    box: Mapping[int, Sequence[Mapping[str, float]]] | None = None,
    begun: Collection[str] = (),
) -> dict[str, Any] | None:
    """The scoreboard and both teams' players, or None without a named opponent this week.
    ``begun`` are the teams whose game today began (``season_lineup.begun_teams``)."""
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

    chosen = sl.recommended(
        built, season, today, span, sl.first_change(p, season.settings, today), begun
    ).chosen
    full_mine = mv.project_mine(p, span, chosen=chosen)
    full_theirs = span.opponents[0]
    fm = wk.finals(full_mine, span.so_far, cats)
    ft = wk.finals(full_theirs, theirs_so_far, cats)
    odds = wk.odds_of(fm, ft, cats)
    expected, win = wk.expected_won(odds), wk.matchup_won(odds)
    # None on the week's last day read once its games began (#209): no day left, no player
    # started, so nobody is taken out.
    first = span.days[0] if span.days else None

    box = box or {}
    printed = {
        team: {int(r["player"]): r.get("line") or {} for r in matchup.players.get(team, ())}
        for team in (mine, other)
    }

    def row(
        key: int,
        team: int,
        slot: str,
        week: wk.TeamWeek,
        without: Sequence[wk.CategoryOdds] | None,
    ):
        pw = week.players.get(key, wk.PlayerWeek(0, 0))
        if without is None:
            cats_, odds_ = 0.0, 0.0
        else:
            cats_, odds_ = expected - wk.expected_won(without), win - wk.matchup_won(without)
        line = printed[team].get(key)
        so = (
            sf.not_read(p.points is not None)
            if line is None
            else sf.so_far(line, box.get(key), p.points)
        )
        rest = rest_line(pw, p.rates.get(key), p.points)
        return {
            "player": key,
            "slot": slot,
            "games": pw.games,
            "started": pw.started,
            "per_game": per_game(p.rates.get(key), p.points),
            "cats": round(cats_, 4),
            "matchup": round(odds_, 4),
            "so_far": _rounded(so.to_dict()),
            "rest": None if rest is None else _rounded(rest),
            "total": _rounded(total_line(so, rest)),
        }

    def order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # The largest Matchup first, the players with no game left last.
        return sorted(rows, key=lambda r: (r["games"] == 0, -r["matchup"], -r["cats"]))

    slots = {s.player.yahoo_id: s.slot for s in season.rosters.get(mine, ())}
    mine_rows = []
    for key, _ in [*p.held, *p.roster]:
        without = None
        if full_mine.players.get(key, wk.PlayerWeek(0, 0)).started:
            week = mv.project_mine(p, span, gone={key: first}, chosen=chosen)
            without = wk.odds_of(wk.finals(week, span.so_far, cats), ft, cats)
        mine_rows.append(row(key, mine, slots.get(key, ""), full_mine, without))
    their_slots = {s.player.yahoo_id: s.slot for s in season.rosters.get(other, ())}
    their_rows = []
    for key, _ in their_members:
        r = row(key, other, their_slots.get(key, ""), full_theirs, None)
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
    points = p.points is not None
    teams_ = {}
    for team, rows_, so_far_, full in (
        (mine, mine_rows, span.so_far, full_mine),
        (other, their_rows, theirs_so_far, full_theirs),
    ):
        played = (matchup.games.get(team) or {}).get("played")
        teams_[team] = team_lines(so_far_, played, rows_, full, points)
    unread = []
    if week is not None:
        rosters = {t: [s.player.nba_team for s in season.rosters.get(t, ())] for t in (mine, other)}
        for day in unread_days(read_at, first, week.start, week.end):
            playing = season.schedule.get(day, frozenset())
            unread.append(
                {
                    "day": day.isoformat(),
                    "games": [sum(1 for t in rosters[x] if t in playing) for x in (mine, other)],
                }
            )
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
        "team_lines": {"mine": teams_[mine], "theirs": teams_[other]},
        "unread": unread,
    }
