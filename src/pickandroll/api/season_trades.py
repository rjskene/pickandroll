"""The season view's trade evaluator (docs/ADD_DROP.md phase 5, #96): the league built for
``season.trades`` from a league's season state, and the payload of
``POST /seasons/{league}/trade``.

The horizons are the moves' (``season_moves``): the rest of this week, each team against its
named opponent from the week so far, and the three weeks after it against the field. Every
rostered player keeps Basketball Monster's line in either system (Yahoo's view of the players
page lists the available players only), so the system only changes the free agent priced in a
spot the trade frees. The trade takes effect on the day Yahoo would process it if accepted
today: after the league's review window (``trade_reject_time`` days; none when the league does
not review trades; two when its settings do not say), or on the day the request names. Nothing
here proposes a trade or acts in Yahoo.

Beside the two horizons, the rest of the season (#151): each side's roster, each moved player
and the fill to the calendar's last day, on the moves' problem and scorer (``season_moves``):
each player's per-game value net of an empty line times his games, counted as the decision log
counts a move's (``decisions.season_games``). It is for the eye; the lead and the margin stay
on the horizons.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..season import Player, Season, SeasonSettings
from ..season import decisions as dl
from ..season import moves as mv
from ..season import trades as tr
from ..season import weekly as wk
from . import season_moves
from . import season_week as sw

#: The review window when the league's settings do not give one: Yahoo's default.
REVIEW_DAYS = 2


class Refused(Exception):
    """A trade the evaluator cannot take, with the HTTP status that says why."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class TradeLeague:
    league: tr.League
    #: Every team's unchanged weeks, projected once per snapshot.
    seed: tr.Evaluator
    me: int
    first_day: date
    review_days: int
    trade_end: date | None
    #: The free agents for a spot the trade frees on my side, each with the day his move counts.
    pool: tuple[tuple[tr.Member, date], ...]
    limits: tuple[mv.AddLimit, ...]
    system: dict[str, Any]
    horizons: dict[str, dict[str, Any]]
    #: This week's pairs and the teams whose week so far was read.
    pairs: dict[int, int]
    so_far_read: frozenset[int]
    names: dict[int, str]
    players: dict[int, Player]


def review_days(s: SeasonSettings) -> int:
    """The days an accepted trade waits for review: none when the league does not review
    trades, the league's window when Yahoo or the commissioner reviews them."""
    if s.trade_ratify == "none":
        return 0
    return s.trade_review_days if s.trade_review_days is not None else REVIEW_DAYS


def build(
    season: Season, today: date, data_dir: Path, system: str, blend: float | None = None
) -> TradeLeague | None:
    """The league as ``season.trades`` values it, or None when the season lacks my team or its
    weeks."""
    s = season.settings
    mine = s.my_team_id
    if mine is None or not season.calendar or mine not in season.rosters:
        return None
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = tuple(s.cats)
    rated = season_moves.system_rates(season, data_dir, system, blend)
    bbm_value = wk.per_game_values(rated.bbm.rates, cats, points)
    rostered = {sp.player.yahoo_id for spots in season.rosters.values() for sp in spots}
    rates = {**rated.rates, **{k: rated.bbm.rates[k] for k in rostered if k in rated.bbm.rates}}
    value = {**rated.value, **{k: bbm_value[k] for k in rostered if k in bbm_value}}
    matchup, read_at = sw.matchup_read(season, mine)
    since = sw.first_day(read_at, today) if matchup is not None else today
    ahead = sw.spans(season, today, data_dir, season_moves.WEEKS_AHEAD, rated.players, since)
    if not ahead or not ahead[0].days:
        return None
    pairs: dict[int, int] = {}
    so_far: dict[int, dict[str, float]] = {}
    for team in season.rosters:
        m = season.matchup_of(team)
        other = m.opponent_of(team) if m is not None else None
        if other is not None:
            pairs[team] = other
        if read := sw.so_far(m, team, points is not None):
            so_far[team] = read
    week = tr.Span(tuple(ahead[0].days), True, pairs, so_far, ahead[0].games)
    later = tuple(tr.Span(tuple(sp.days), False, None, {}, sp.games) for sp in ahead[1:])
    teams = {
        team: tr.TeamRoster(
            tuple((sp.player.yahoo_id, sp.player) for sp in spots if sp.slot not in mv.HELD),
            tuple((sp.player.yahoo_id, sp.player, sp.slot) for sp in spots if sp.slot in mv.HELD),
        )
        for team, spots in season.rosters.items()
    }
    slot_count = Counter(s.roster)
    league = tr.League(
        teams=teams,
        spots=sum(n for k, n in slot_count.items() if k not in mv.HELD),
        held_slots={k: slot_count[k] for k in mv.HELD if slot_count.get(k)},
        rates=rates,
        schedule=season.schedule,
        slots=wk.starting_slots(s.roster),
        value=value,
        cats=cats,
        points=points,
        no_games=rated.yahoo.zero,
        horizons={"week": (week,), "three": later},
        value_of=wk.line_value(rated.bbm.rates, cats, points),
    )
    seed = tr.Evaluator(league)
    seed.project_all()
    pool = tuple(
        (
            (a.player.yahoo_id, a.player),
            max(since, a.clears) if a.availability == "W" and a.clears else since,
        )
        for a in season.available
        if a.player.yahoo_id not in rostered and a.player.yahoo_id in rates
    )
    _, limits = season_moves.add_limits(season, mine, ahead, today)
    this = ahead[0].week
    horizons = {
        "week": {
            "label": f"rest of week {this.number}",
            "weeks": [this.number],
            "from": since.isoformat(),
        },
        "three": {
            "label": f"weeks {ahead[1].week.number}-{ahead[-1].week.number} against the field"
            if len(ahead) > 1
            else "no later weeks",
            "weeks": [sp.week.number for sp in ahead[1:]],
            "from": ahead[1].week.start.isoformat() if len(ahead) > 1 else None,
        },
    }
    return TradeLeague(
        league=league,
        seed=seed,
        me=mine,
        first_day=since,
        review_days=review_days(s),
        trade_end=s.trade_end_date,
        pool=pool,
        limits=limits,
        system={"key": system, **rated.info},
        horizons=horizons,
        pairs=pairs,
        so_far_read=frozenset(so_far),
        names={t.team_id: t.name for t in season.teams},
        players=rated.players,
    )


# --------------------------------------------------------------------------- the trade
def proposal(
    built: TradeLeague,
    team: int,
    give: list[int],
    get: list[int],
    effective: date | None,
    today: date,
) -> tuple[tr.Trade, str]:
    """The trade the request names, checked against the rosters, and how its date was set."""
    lg = built.league
    if built.trade_end is not None and today > built.trade_end:
        raise Refused(409, f"trades closed on {built.trade_end.isoformat()}")
    if team == built.me:
        raise Refused(400, "the counterparty is my own team")
    if team not in lg.teams:
        raise Refused(400, f"no roster read for team {team}")
    give, get = list(dict.fromkeys(give)), list(dict.fromkeys(get))
    if not give and not get:
        raise Refused(400, "a trade needs a player on at least one side")
    if both := sorted(set(give) & set(get)):
        raise Refused(400, f"players on both sides: {both}")

    def on(t: int) -> set[int]:
        r = lg.teams[t]
        return {k for k, _ in r.active} | {k for k, _, _ in r.held}

    if off := sorted(set(give) - on(built.me)):
        raise Refused(400, f"not on my roster: {off}")
    if off := sorted(set(get) - on(team)):
        raise Refused(400, f"not on team {team}'s roster: {off}")
    if effective is not None:
        day, rule = max(effective, built.first_day), "requested"
    else:
        day, rule = built.first_day + timedelta(days=built.review_days), "review"
    return tr.Trade(built.me, team, tuple(give), tuple(get), day), rule


def _r(x: float) -> float:
    return round(float(x), 3)


def _games(pw: wk.PlayerWeek) -> dict[str, int]:
    return pw.to_dict()


def ros_player(
    moves: season_moves.Built | None, key: int, player: Player | None, start: date
) -> dict[str, Any] | None:
    """A player's rest of the season from ``start`` (#151): his per-game value under the
    league's scorer, net of an empty line, times his games to the season's last day as the
    decision log counts a move's (``decisions.season_games``), with how many are extrapolated.
    None without the moves' problem, the scorer, his line or a season end ahead."""
    if moves is None or moves.scorer is None or player is None:
        return None
    line = moves.problem.rates.get(key)
    counted = dl.season_games(moves.problem, key, player, start)
    if line is None or counted is None:
        return None
    games, extrapolated = counted
    per_game = round(wk.net_value(moves.scorer, line), 4)
    return {
        "value": round(per_game * games, 4),
        "per_game": per_game,
        "games": round(games, 2),
        "extrapolated": round(extrapolated, 2),
    }


def _ros_side(
    built: TradeLeague,
    moves: season_moves.Built | None,
    side: tr.Side,
    rep: tr.Report,
) -> dict[str, Any] | None:
    """A side's rest of the season (#151) from the trade's day: its roster's before (every
    player of it, held ones from their return) and the change, the players it receives less
    those it sends and drops to fit (the fill is valued beside, as on the horizons); None
    without the moves' problem. A player with no line counts nothing and is counted in
    ``unvalued``."""
    if moves is None or moves.scorer is None:
        return None
    t = rep.trade
    day = t.effective
    roster = built.league.teams[side.team]
    on = [k for k, _ in roster.active] + [k for k, _, _ in roster.held]
    joins, leaves = (t.get, t.give) if side.team == t.mine else (t.give, t.get)
    unvalued = 0

    def total(keys: list[int] | tuple[int, ...], start: date = day) -> float:
        nonlocal unvalued
        out = 0.0
        for k in keys:
            r = ros_player(moves, k, built.players.get(k), start)
            if r is None:
                unvalued += 1
            else:
                out += r["value"]
        return out

    before = total(on)
    change = total(joins) - total(leaves) - total(side.roster.drops)
    return {
        "before": _r(before),
        "after": _r(before + change),
        "change": _r(change),
        "from": day.isoformat(),
        "unvalued": unvalued,
    }


def _side(
    built: TradeLeague,
    side: tr.Side,
    rep: tr.Report | None = None,
    moves: season_moves.Built | None = None,
) -> dict[str, Any]:
    opponent = built.pairs.get(side.team)
    return {
        "team": side.team,
        "name": built.names.get(side.team, f"team {side.team}"),
        "opponent": opponent,
        "opponent_name": built.names.get(opponent, f"team {opponent}") if opponent else None,
        "so_far_read": side.team in built.so_far_read,
        "horizons": {
            key: {
                "before": _r(sum(side.before[key].values())),
                "after": _r(sum(side.after[key].values())),
                "change": _r(side.change(key)),
                "cats": [
                    {
                        "cat": c,
                        "before": _r(side.before[key][c]),
                        "after": _r(side.after[key][c]),
                        "change": _r(side.after[key][c] - side.before[key][c]),
                    }
                    for c in built.league.cats
                ],
            }
            for key in built.league.horizons
        },
        "ros": None if rep is None else _ros_side(built, moves, side, rep),
        "roster": {
            "spots": side.roster.spots,
            "active": side.roster.active,
            "open": side.roster.open,
            "valid": side.roster.valid,
            "held_moves": [{"player": k, "slot": s} for k, s in side.roster.held_moves],
            "drops": [_player(built, k) for k in side.roster.drops],
        },
    }


def _player(built: TradeLeague, key: int) -> dict[str, Any]:
    p = built.players.get(key)
    return {
        "player": key,
        "name": p.name if p else str(key),
        "nba_team": p.nba_team if p else None,
        "positions": list(p.positions) if p else [],
        "status": p.status if p else None,
    }


def payload(
    built: TradeLeague, rep: tr.Report, rule: str, moves: season_moves.Built | None = None
) -> dict[str, Any]:
    """The trade's report; with the moves' problem (``moves``), the rest of the season beside
    the horizons (#151)."""
    t = rep.trade
    margin = rep.margin
    return {
        "trade": {"team": t.theirs, "give": list(t.give), "get": list(t.get)},
        "effective": t.effective.isoformat(),
        "effective_rule": rule,
        "review_days": built.review_days,
        "first_day": built.first_day.isoformat(),
        "system": built.system,
        "horizons": built.horizons,
        "lead": rep.key,
        "sides": {
            "mine": _side(built, rep.mine, rep, moves),
            "theirs": _side(built, rep.theirs, rep, moves),
        },
        "players": [
            {
                **_player(built, m.player),
                "from": m.old,
                "to": m.new,
                "games": {
                    key: {
                        "before": _games(m.before[key]),
                        "old": _games(m.on_old[key]),
                        "new": _games(m.on_new[key]),
                    }
                    for key in built.league.horizons
                },
                "ros": ros_player(moves, m.player, built.players.get(m.player), t.effective),
            }
            for m in rep.moved
        ],
        "margin": None
        if margin is None
        else {
            "horizon": margin.key,
            "neutral": margin.neutral,
            "reading": margin.reading,
            "change": _r(margin.change),
            "max": tr.MARGIN_MAX,
        },
        "fill": None
        if rep.fill is None
        else {
            **_player(built, rep.fill.add),
            "from": rep.fill.effective.isoformat(),
            "gain": {k: _r(v) for k, v in rep.fill.gain.items()},
            "ros": ros_player(
                moves, rep.fill.add, built.players.get(rep.fill.add), rep.fill.effective
            ),
        },
    }


def evaluate(
    built: TradeLeague,
    team: int,
    give: list[int],
    get: list[int],
    effective: date | None,
    today: date,
    moves: season_moves.Built | None = None,
) -> dict[str, Any]:
    trade, rule = proposal(built, team, give, get, effective, today)
    ev = tr.Evaluator(built.league, seed=built.seed)
    rep = tr.evaluate(built.league, trade, built.pool, built.limits, ev)
    return payload(built, rep, rule, moves)
