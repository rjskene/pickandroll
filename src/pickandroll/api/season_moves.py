"""The season view's moves (docs/ADD_DROP.md phase 3, #94): the move problem built from a
league's season state, and the payloads of ``GET /seasons/{league}/moves`` and of the move
drawer.

Two horizons: the rest of this week against the named opponent, from the week so far, and the
three weeks after it against the field (the other teams, each on its projected roster). The
rates are the chosen system's: Basketball Monster's, or Yahoo's next seven days for the available
players (the only ones its players page lists) with Basketball Monster's line for everyone else. Every candidate's single moves are valued
exactly; the recommended set is a search (``season.moves``), priced by re-solves over the
candidates whose best single move gains most.

A player of mine listed O is held out past next Monday when ESPN's injury report gives a later
return date (#97): the day a held-slot move's deferred drop is charged from.

The keep rule (#124, ``season.moves``) reads Basketball Monster's rest-of-season per-game line
for my players and the candidates under every system, scored by the league's scorer: Yahoo's
values are seven-day projections, the wrong horizon for a season comparison. The players it keeps
are no drop anywhere; the payload names them with their values and the best add's, and advises
each player with an absence on the IL.

The streaming plan (#136, ``season.stream``) turns the weakest spots over inside the week: a
dated sequence of adds and drops the payload shows beside the week's recommended set, and
recommends only when its week beats the set's by the planner's floor.

The week plans (#221 part 2, ``season.plans``) are a few dated sequences of at most four moves
over the rest of this week, each step with what it adds to the plan before it on both horizons
and the roster's own changes on their day (``week_plans``): plan 1 the week set unless a plan
beats it by the plan floor; ``queue`` names the plan the queue takes instead of the three weeks'
set, when one beats it there by the floor. Their search's seconds sit beside the solve's.

The season guard (#164, ``season.moves.season_guard``) holds every recommended set, its re-solves
and the plan to a rest of the season of zero or more, on the log's own figure for each move
(:func:`ros_of`). When the search without it finds a set that beats the guarded one on the
horizon and costs the season, the horizon names that set (``season_guard``): shown flagged, never
recommended.

A churn (#221, ``season.moves``) drops a held player for an add: its rows name the held drop and
his slot (``held_drop``) beside the held-slot move that gives the add an active spot (``held``),
and its basis is ``churn``. Ties on a horizon go to the season (the guard's own figure); each
recommended move says which horizon decided it (``decided_by``): the season when keeping its
drop re-solves to a set worth the same on the horizon.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..season import Player, Season
from ..season import decisions as dl
from ..season import moves as mv
from ..season import plans as pl
from ..season import progress as pg
from ..season import stream as st
from ..season import weekly as wk
from ..sources.injuries import Listed
from ..sources.matching import match_players
from . import season_cantcut, season_flags
from . import season_week as sw

#: The weeks the moves look at: this week and the three after it.
WEEKS_AHEAD = 4
#: The candidates the recommended set and its re-solves search: those whose best single move
#: gains most on the horizon.
POOL = 30
#: A move must add at least this many expected categories to be recommended.
MIN_GAIN = 0.01
#: The alternative adds the drawer lists for a drop.
ALTERNATIVE_ADDS = 8
#: How far a protected player's rest-of-season per-game value must exceed the best add's: the
#: keep rule's protection floor, a knob the hill-climb may set within its minimum
#: (docs/AUTOPILOT.md, section 6; ``season.progress.KNOB_MINIMUMS``).
PROTECTION_FLOOR = mv.PROTECTION_FLOOR
HORIZONS = ("week", "three")


@dataclass(frozen=True)
class Built:
    problem: mv.MoveProblem
    system: dict[str, Any]
    horizons: dict[str, dict[str, Any]]
    adds: dict[str, Any]
    #: Available players in the pool without a projection in the system (no move is valued).
    unprojected: int
    #: The matchup weeks after this one in the league's calendar (the strategy engine's, #110).
    weeks_left: int = 0
    #: The keep rule on my active players (#124).
    rule: mv.KeepRule | None = None
    #: The league's scorer as data (``weekly.scorer_of``), the keep rule's: the decision log
    #: values each recommended move with it and the scorecard the moves made (#126). None
    #: without Basketball Monster's lines.
    scorer: dict[str, Any] | None = None
    #: The knobs the solve ran with (#152; ``season.progress.in_force_for``), its system
    #: among them.
    knobs: dict[str, Any] = field(default_factory=lambda: dict(pg.DEFAULTS))
    #: The system the knob file had in force for the league, which a route naming another
    #: overrode for this solve (#152); the scorecard scores each week on it.
    file_system: str = pg.DEFAULTS["system"]


@dataclass(frozen=True)
class Rated:
    """A system's rates and per-game values for the season's players."""

    rates: dict[int, wk.Rates]
    value: dict[int, float]
    info: dict[str, Any]
    players: dict[int, Player]
    bbm: sw.System
    yahoo: sw.System


def blend_rates(
    bbm: Mapping[int, wk.Rates], yahoo: Mapping[int, wk.Rates], weight: float
) -> dict[int, dict[str, float]]:
    """Each player Yahoo projects at ``weight`` Yahoo's and the rest Basketball Monster's, stat
    by stat (Yahoo's alone for a player Basketball Monster has no line for)."""
    out = {}
    for k, y in yahoo.items():
        b = bbm.get(k)
        if b is None:
            out[k] = dict(y)
            continue
        stats = set(b) | set(y)
        out[k] = {
            st_: (1 - weight) * float(b.get(st_, 0.0)) + weight * float(y.get(st_, 0.0))
            for st_ in stats
        }
    return out


def system_rates(season: Season, data_dir: Path, system: str, blend: float | None = None) -> Rated:
    """The rates of ``system``: Basketball Monster's; Yahoo's next seven days for the
    available players with Basketball Monster's line for everyone else; or the ``blend`` of the
    two (#152), Yahoo's share ``blend`` for each player Yahoo projects, each per-game value the
    same mix of the two systems' own."""
    s = season.settings
    players = sw.season_players(season)
    bbm = sw.bbm_system(data_dir, players)
    yahoo = sw.yahoo_system(season)
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = tuple(s.cats)
    if system == "blend":
        w = pg.BLEND if blend is None else float(blend)
        rates = {**bbm.rates, **blend_rates(bbm.rates, yahoo.rates, w)}
        value = wk.per_game_values(bbm.rates, cats, points)
        theirs = wk.per_game_values(yahoo.rates, cats, points)
        value |= {k: (1 - w) * value[k] + w * v if k in value else v for k, v in theirs.items()}
        info = {
            **yahoo.info,
            "label": f"Blend: Yahoo {w:.0%}, Basketball Monster {1 - w:.0%}",
            "blend": w,
            "file": bbm.info.get("file"),
            "fallback": "Basketball Monster for rostered players and anyone Yahoo does not project",
        }
    elif system == "yahoo":
        rates = {**bbm.rates, **yahoo.rates}
        value = {**wk.per_game_values(bbm.rates, cats, points)}
        value |= wk.per_game_values(yahoo.rates, cats, points)
        # Yahoo's view of the players page lists the available players only: my roster, the
        # opponents and anyone it does not project keep Basketball Monster's line.
        info = {
            **yahoo.info,
            "fallback": "Basketball Monster for rostered players and anyone Yahoo does not project",
        }
    else:
        rates = dict(bbm.rates)
        value = wk.per_game_values(bbm.rates, cats, points)
        info = dict(bbm.info)
    return Rated(rates, value, info, players, bbm, yahoo)


def espn_returns(data_dir: Path, members: list[mv.Member]) -> dict[int, date]:
    """ESPN's return dates for ``members`` listed O, matched by name and team."""
    out_ = [(k, p) for k, p in members if p.status in wk.OUT_THIS_WEEK]
    path = season_flags.injuries_path(data_dir)
    if not out_ or not path.exists():
        return {}
    body = season_flags._read(path) or {}
    listed = [Listed.from_dict(d) for d in body.get("players") or []]
    dated = [x for x in listed if x.returns is not None]
    if not dated:
        return {}
    espn = pd.DataFrame(
        {"name": [x.name for x in dated], "team": [x.team for x in dated]},
        index=[x.key for x in dated],
    )
    espn = espn[~espn.index.duplicated()]
    mine = pd.DataFrame(
        {"player": [p.name for _, p in out_], "team": [p.nba_team for _, p in out_]},
        index=[k for k, _ in out_],
    )
    found = match_players(espn, mine).mapping
    returns = {x.key: x.returns for x in dated}
    return {int(k): returns[key] for key, k in found.items()}


def add_limits(
    season: Season, team: int, ahead: list[sw.Span], today: date
) -> tuple[mv.AddsUsed, tuple[mv.AddLimit, ...]]:
    """The adds ``team`` made this week and each week's add limit, this week's net of them."""
    limit = season.settings.max_weekly_adds
    this = ahead[0].week
    used = mv.adds_used(season.transactions, team, this.start, this.end, today)
    limits = tuple(
        mv.AddLimit(
            sp.week.start,
            sp.week.end,
            None if limit is None else (max(0, limit - used.count) if i == 0 else limit),
        )
        for i, sp in enumerate(ahead)
    )
    return used, limits


def build(
    season: Season,
    today: date,
    data_dir: Path,
    system: str,
    knobs: Mapping[str, Any] | None = None,
) -> Built | None:
    """The move problem for my team, or None when the season lacks my team or its weeks; the
    solve runs on ``system`` with ``knobs``, the league's knobs as ``api.season_knobs`` reads
    them (the code's defaults when None), and Yahoo's can't-cut list as the executor last read
    it (``api.season_cantcut``, #220)."""
    s = season.settings
    mine = s.my_team_id
    if mine is None or not season.calendar or mine not in season.rosters:
        return None
    file_system = (knobs or {}).get("system") or pg.DEFAULTS["system"]
    knobs = {**pg.DEFAULTS, **(knobs or {}), "system": system}
    if system == "blend" and knobs["blend"] is None:
        knobs["blend"] = pg.BLEND
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = tuple(s.cats)
    rated = system_rates(season, data_dir, system, knobs["blend"])
    rates, value, info, yahoo = rated.rates, rated.value, rated.info, rated.yahoo
    players = rated.players
    matchup, read_at = sw.matchup_read(season, mine)
    since = sw.first_day(read_at, today) if matchup is not None else today
    ahead = sw.spans(season, today, data_dir, WEEKS_AHEAD, players, since)
    # This week with no days left (a Sunday read once its games began, #209) stays the week
    # horizon, an empty one no move changes; every move takes effect in the weeks after it.
    over = bool(ahead) and not ahead[0].days
    if not ahead or (over and len(ahead) < 2):
        return None
    slots = wk.starting_slots(s.roster)

    def project(team: int, i: int) -> wk.TeamWeek:
        members = [(sp.player.yahoo_id, sp.player) for sp in season.rosters.get(team, ())]
        return wk.project_week(
            members,
            rates,
            ahead[i].days,
            season.schedule,
            slots,
            value,
            i == 0,
            games=ahead[i].games,
            points=points,
            no_games=yahoo.zero,
        )

    other = matchup.opponent_of(mine) if matchup is not None else None
    week_span = mv.WeekSpan(
        tuple(ahead[0].days),
        True,
        (project(other, 0),) if other is not None else (),
        sw.so_far(matchup, mine, points is not None),
        (sw.so_far(matchup, other, points is not None),) if other is not None else (),
        ahead[0].games,
    )
    field_teams = [t for t in season.rosters if t != mine]
    later = tuple(
        mv.WeekSpan(
            tuple(ahead[i].days),
            False,
            tuple(project(t, i) for t in field_teams),
            games=ahead[i].games,
        )
        for i in range(1, len(ahead))
    )
    spots = [sp for sp in season.rosters[mine]]
    roster = tuple((sp.player.yahoo_id, sp.player) for sp in spots if sp.slot not in mv.HELD)
    held = tuple((sp.player.yahoo_id, sp.player) for sp in spots if sp.slot in mv.HELD)
    held_slots = {sp.player.yahoo_id: sp.slot for sp in spots if sp.slot in mv.HELD}
    slot_count = Counter(s.roster)
    # A held player whose status cleared is activated on the first day: his slot is open.
    taken = Counter(
        sp.slot
        for sp in spots
        if sp.slot in mv.HELD and not mv.is_cleared(sp.player.status, sp.slot)
    )
    held_open = {k: slot_count.get(k, 0) - taken.get(k, 0) for k in mv.HELD}
    on_roster = {k for k, _ in roster} | {k for k, _ in held}
    pool = [a for a in season.available if a.player.yahoo_id not in on_roster]
    candidates = tuple((a.player.yahoo_id, a.player) for a in pool if a.player.yahoo_id in rates)
    effective = {
        a.player.yahoo_id: max(since, a.clears) if a.availability == "W" and a.clears else since
        for a in pool
        if a.player.yahoo_id in rates
    }
    limit = s.max_weekly_adds
    this = ahead[0].week
    # The adds are counted from the first week a move can take effect in: the next one when
    # this week is over (a claim placed on Sunday clears on Monday, #209).
    used, limits = add_limits(season, mine, ahead[1:] if over else ahead, today)
    claims = frozenset(
        a.player.yahoo_id for a in pool if a.player.yahoo_id in rates and a.availability == "W"
    )
    problem = mv.MoveProblem(
        roster=roster,
        held=held,
        spots=sum(n for k, n in slot_count.items() if k not in mv.HELD),
        held_open={k: n for k, n in held_open.items() if n > 0},
        candidates=candidates,
        effective=effective,
        first_day=since,
        rates=rates,
        schedule=season.schedule,
        slots=slots,
        value=value,
        cats=cats,
        points=points,
        no_games=yahoo.zero,
        horizons={"week": (week_span,), "three": later},
        limits=limits,
        returns=espn_returns(data_dir, [*roster, *held]),
        held_slots=held_slots,
        claims=claims,
    )
    names = {t.team_id: t.name for t in season.teams}
    horizons = {
        "week": {
            "label": (
                f"week {this.number} has no days left"
                if over
                else f"rest of week {this.number}"
                + (f" against {names.get(other, f'team {other}')}" if other is not None else "")
            ),
            "weeks": [this.number],
            "from": None if over else since.isoformat(),
            "opponent": other,
        },
        "three": {
            "label": f"weeks {ahead[1].week.number}-{ahead[-1].week.number} against the field"
            if len(ahead) > 1
            else "no later weeks",
            "weeks": [sp.week.number for sp in ahead[1:]],
            "from": ahead[1].week.start.isoformat() if len(ahead) > 1 else None,
            "opponent": None,
        },
    }
    adds = {
        "limit": limit,
        "used": used.count,
        "complete": used.complete,
        "left": limits[0].adds,
        "weeks": [
            {"start": lim.start.isoformat(), "end": lim.end.isoformat(), "adds": lim.adds}
            for lim in limits
        ],
    }
    unprojected = sum(1 for a in pool if a.player.yahoo_id not in rates)
    weeks_left = sum(1 for w in season.calendar.weeks if w.number > this.number)
    problem = replace(
        problem,
        **keep_inputs(rated, cats, points, s.num_teams * problem.spots),
        season_end=max(w.end for w in season.calendar.weeks),
        floor=float(knobs["protection_floor"]),
        plan_floor=float(knobs["plan_floor_points" if points else "plan_floor_cats"]),
        daily_cap=int(knobs["daily_cap"]),
        cantcut=season_cantcut.load(data_dir, s.league),
    )
    rule = mv.keep_rule(problem)
    problem = replace(problem, kept=rule.kept)
    pool = max(1, s.num_teams * problem.spots)
    scorer = wk.scorer_of(rated.bbm.rates, cats, points, pool) if rated.bbm.rates else None
    return Built(
        problem,
        {"key": system, **info},
        horizons,
        adds,
        unprojected,
        weeks_left,
        rule,
        scorer,
        knobs,
        file_system,
    )


def keep_inputs(
    rated: Rated, cats: tuple[str, ...], points: dict[str, float] | None, pool: int
) -> dict[str, Any]:
    """The keep rule's values whatever the system: Basketball Monster's per-game line under the
    league's scorer, a dead spot's (an empty line) under the same scorer, and the pool's
    average, all over ``pool``, the players the league rosters (its teams times their active
    spots): the z-scores' pool, whose average is zero, or in a points league the best ``pool``'s
    mean."""
    bbm = rated.bbm.rates
    if not bbm:
        return {"season_value": {}, "dead": 0.0, "average": 0.0}
    pool = max(1, pool)
    values = wk.per_game_values(bbm, cats, points, pool)
    dead = wk.line_value(bbm, cats, points, pool)({})
    average = 0.0
    if points:
        best = sorted(values.values(), reverse=True)[:pool]
        average = sum(best) / len(best)
    return {"season_value": values, "dead": dead, "average": average}


# --------------------------------------------------------------------------- the payloads
def _move(m: mv.Move, problem: mv.MoveProblem) -> dict[str, Any]:
    return {"add": m.add, "drop": m.drop, **_day(m, problem)}


def _day(m: mv.Move, problem: mv.MoveProblem) -> dict[str, str]:
    return {"from": mv.day_of(problem, m).isoformat()}


def _r(x: float) -> float:
    return round(float(x), 3)


def ros_of(
    built: Built, add: int, drop: int | None, day: date | None = None
) -> dict[str, Any] | None:
    """A move's rest of the season (#151): the decision log's own figure for it
    (``decisions.move_projection``'s season horizon, #144), from its day to the calendar's last
    day, playoffs included, in the league's value units (category z or points, net of an empty
    line, over the games each plays), with those games and how many are extrapolated beyond the
    schedule read. The tables, the log and the scorecard so value a move alike; nothing ranks
    on it. None without the league's scorer or a season end; its value None when the add or
    the drop has no line."""
    proj = dl.move_projection(built.problem, built.scorer, add, drop, day)
    s = ((proj or {}).get("horizons") or {}).get(dl.SEASON)
    if s is None:
        return None
    return {
        "value": s["value"],
        "add_games": s["add_games"],
        "drop_games": s["drop_games"],
        "extrapolated": s["extrapolated_games"],
        "from": s["from"],
        "to": s["to"],
    }


def ros_move(built: Built, m: mv.Move) -> dict[str, Any] | None:
    """:func:`ros_of` for ``m`` from its day, the day the payload's row gives."""
    return ros_of(built, m.add, m.drop, mv.day_of(built.problem, m))


def ros_total(rows: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    """A set's rest of the season: the sum of its moves' (each valued on its own, as the log
    values them; a set's moves have distinct adds and drops); None when one has no value."""
    values = [None if r is None else r["value"] for r in rows]
    if any(v is None for v in values):
        return None
    return {"value": round(float(sum(v for v in values if v is not None)), 4)}


def guard_ros(built: Built) -> Callable[[mv.Move], float | None] | None:
    """Each move's rest of the season for the season guard (#164): :func:`ros_move`'s value,
    cached by add, drop and day; None without the league's scorer or a season end, when there is
    nothing to guard on."""
    p = built.problem
    if built.scorer is None or p.season_end is None:
        return None
    seen: dict[tuple[int, int | None, date], float | None] = {}

    def ros(m: mv.Move) -> float | None:
        k = (m.add, m.drop, mv.day_of(p, m))
        if k not in seen:
            r = ros_of(built, *k)
            seen[k] = None if r is None else r["value"]
        return seen[k]

    return ros


def season_of(ros: Callable[[mv.Move], float | None] | None) -> mv.Season | None:
    """The searches' tie-break (#221: ties go to the season): a set's rest of the season by the
    guard's own figure (``moves.season_total``); None without it."""
    if ros is None:
        return None
    return lambda moves: mv.season_total(ros, moves)[0]


def decided_by(pm: mv.PricedMove, key: str, season: mv.Season | None) -> str:
    """The horizon that decided a recommended move (#221): the season when keeping its drop
    re-solves to a set worth the same on ``key`` (the tie the season broke), else ``key``."""
    tied = pm.price_keep is not None and abs(pm.price_keep) <= mv.EPS
    return dl.SEASON if season is not None and tied else key


class Watched:
    """A guard that counts the sets it refused: a solve it never refused is the unguarded
    one's."""

    def __init__(self, allowed: mv.Allowed) -> None:
        self.allowed, self.refused = allowed, 0

    def __call__(self, moves: Sequence[mv.Move]) -> bool:
        ok = self.allowed(moves)
        self.refused += not ok
        return ok


def held_back(
    built: Built,
    ev: mv.Valued,
    key: str,
    moves: Sequence[mv.Move],
    ros: Callable[[mv.Move], float | None] | None,
    free: Sequence[mv.Move] | None,
    source: str = "moves",
    set_key: str | None = None,
) -> dict[str, Any] | None:
    """The season guard on horizon ``key``'s guarded set ``moves`` (#164): ``held_back`` when
    ``free``, the set the engine recommends without the guard, beats it on the horizon and its
    rest of the season is below zero. Then that set's moves, each with what it adds to the set, its rest of
    the season and the decision log's season-costly flag (judged as the log judges the set's,
    ``source`` and ``set_key``); its gain and its rest of the season (``partial`` when a move
    without a line counted as zero); and what the guarded set forgoes on each horizon and saves
    over the season. None without the guard; not held back without a ``free`` set (the guard
    refused nothing, so the solve was the unguarded one)."""
    if ros is None:
        return None
    if free is None:
        return {"held_back": False}
    total, partial = mv.season_total(ros, free)
    if total >= -mv.EPS or ev.value(key, free) <= ev.value(key, moves) + mv.EPS:
        return {"held_back": False}
    p = ev.problem
    mine, mine_partial = mv.season_total(ros, moves)
    by_add = held_by_add(p, list(free))
    horizons = list(ev.base)
    rows = []
    for m in free:
        rest = [x for x in free if x != m]
        proj = dl.move_projection(p, built.scorer, m.add, m.drop, mv.day_of(p, m))
        judged = dl.judging_horizon(source, set_key or key, proj)
        rows.append(
            {
                **_move(m, p),
                "held": by_add.get(m.add),
                "marginal": {h: _r(ev.value(h, free) - ev.value(h, rest)) for h in horizons},
                "ros": ros_move(built, m),
                "season_costly": dl.season_costly(proj, judged),
            }
        )
    gain = {h: ev.gain(h, free) for h in horizons}
    return {
        "held_back": True,
        "moves": rows,
        "gain": {h: _r(v) for h, v in gain.items()},
        "ros": {"value": round(total, 4), "partial": partial},
        "forgone": {h: _r(gain[h] - ev.gain(h, moves)) for h in horizons},
        "saved": {"value": round(mine - total, 4), "partial": partial or mine_partial},
    }


def comebacks_rows(cs: list[mv.Comeback] | tuple[mv.Comeback, ...]) -> list[dict[str, Any]]:
    return [
        {"player": c.player, "slot": c.slot, "from": c.day.isoformat(), "drop": c.drop} for c in cs
    ]


def cleared_payload(problem: mv.MoveProblem) -> list[dict[str, Any]]:
    """My held players whose status cleared, each with the slot, his status and the active
    player his activation drops on the first day (maybe himself): Yahoo refuses every add until
    he is activated (#124)."""
    players = dict(problem.held)
    sends = {c.player: c.drop for c in mv.comebacks(problem, "week", ())}
    return [
        {
            "player": k,
            "slot": slot,
            "status": players[k].status,
            "from": problem.first_day.isoformat(),
            "drop": sends.get(k),
        }
        for k, slot in mv.cleared(problem)
    ]


def room_payload(problem: mv.MoveProblem) -> dict[str, Any]:
    """The room an add without a drop has (#187, ``moves.room``): the open active spots, each
    held kind's open slots (a full one at zero) and my active players whose status fits one,
    so the web says which case applies without inferring it."""
    r = mv.room(problem)
    return {
        "open_spots": r.open_spots,
        "held_open": dict(r.held_open),
        "eligible": list(r.eligible),
    }


#: Why a candidate has no move: the week's adds are used, or no player can go for him.
NO_ADDS_LEFT = "no adds left that week"
NO_DROP = "no drop: every rostered player is protected or held"


def _held_for(problem: mv.MoveProblem, move: mv.Move) -> dict[str, Any] | None:
    """The held-slot move an add that needs an active spot takes (None: an open spot, or a drop
    of an active player)."""
    return held_by_add(problem, [move]).get(move.add)


def held_by_add(
    problem: mv.MoveProblem, moves: list[mv.Move] | tuple[mv.Move, ...]
) -> dict[int, Any]:
    """The held-slot move each add that needs an active spot (``moves.needs_spot``: no drop, or
    a churn's held one) takes, in the set's order once the open spots are taken
    (``moves.held_used``): who goes to which slot to make room for him."""
    free = [m.add for m in moves if mv.needs_spot(problem, m)][mv.open_spots(problem) :]
    used = mv.held_used(problem, moves)
    return {a: {"player": k, "slot": slot} for a, (k, slot) in zip(free, used, strict=False)}


def held_drop(problem: mv.MoveProblem, move: mv.Move) -> dict[str, Any] | None:
    """A churn's held drop and the slot he leaves (#221); None for any other move."""
    if not mv.is_churn(problem, move):
        return None
    return {"player": move.drop, "slot": problem.held_slots[move.drop]}


def basis(problem: mv.MoveProblem, move: mv.Move, held: Mapping[str, Any] | None) -> str:
    """A move's basis (#187, #221): ``decisions.basis_of`` with whether its drop is held."""
    return dl.basis_of(move.drop, held, mv.is_churn(problem, move))


def moves_with_held(
    problem: mv.MoveProblem, moves: list[mv.Move] | tuple[mv.Move, ...]
) -> list[dict[str, Any]]:
    """A set's moves, each add that needs an active spot naming the held-slot move that makes
    room for him (None: an open spot, or a drop of an active player), a churn its held drop."""
    held = held_by_add(problem, moves)
    return [
        {**_move(m, problem), "held": held.get(m.add), "held_drop": held_drop(problem, m)}
        for m in moves
    ]


def no_move(problem: mv.MoveProblem, cand: int) -> str:
    """Why ``cand`` has no feasible move."""
    lim = mv.limit_of(problem, problem.effective[cand])
    if lim is not None and lim.adds is not None and lim.adds <= 0:
        return NO_ADDS_LEFT
    return NO_DROP


def _kept_row(key: int, k: mv.Kept) -> dict[str, Any]:
    return {
        "player": key,
        "value": None if k.value is None else _r(k.value),
        "back": k.back.isoformat() if k.back else None,
        "net_positive": k.net_positive,
        "beats_best": k.beats_best,
        "returns": k.returns,
        "protected": k.protected,
        "bench": k.bench,
        "cantcut": k.cantcut,
    }


def keep_payload(built: Built) -> dict[str, Any]:
    """The keep rule (#124): the best add's rest-of-season per-game value, the floor, and each of
    my active players with his own value, when he is back and the three tests; my held players
    apart (``held``, #221), the churns' drops."""
    p, rule = built.problem, built.rule
    if rule is None:
        return {
            "floor": p.floor,
            "average": _r(p.average),
            "best": None,
            "players": [],
            "held": [],
        }
    best = None
    if rule.best is not None and rule.best_value is not None:
        best = {"player": rule.best, "value": _r(rule.best_value)}
    return {
        "floor": rule.floor,
        "average": _r(p.average),
        "best": best,
        "players": [_kept_row(key, k) for key, k in rule.players.items()],
        "held": [_kept_row(key, k) for key, k in rule.held.items()],
    }


def _freed(built: Built, swaps: dict[str, dict[int, list[mv.SwapGain]]]) -> dict[str, Any]:
    """The best add for a spot a held-slot move frees, on each horizon: the best single move
    with no drop, with its rest of the season (#151)."""
    out: dict[str, Any] = {}
    for key in HORIZONS:
        free = [(c, g.gain) for c, gs in swaps[key].items() for g in gs if g.drop is None]
        best = max(free, key=lambda x: (x[1], -x[0]), default=None)
        out[key] = (
            None
            if best is None
            else {
                "player": best[0],
                "gain": _r(best[1]),
                "ros": ros_move(built, mv.Move(best[0])),
            }
        )
    return out


def stash_payload(
    built: Built,
    swaps: dict[str, dict[int, list[mv.SwapGain]]] | None = None,
    recommended: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """The IL advice (#124, "can and should"): each of my players with an absence, the held slots
    his status allows and the one open for him, his value net of return, and what to do; a
    stash names the best add for the freed spot, a full slot who should leave it, and the churn
    of that player a recommended set holds (``churn``, #221: its add, what it adds to the set and
    the horizon, the three weeks' set first)."""
    p, rule = built.problem, built.rule
    if rule is None:
        return []
    freed = _freed(built, swaps) if swaps is not None else None
    out = []
    for a in mv.stash_advice(p, rule):
        row: dict[str, Any] = {
            "player": a.player,
            "status": a.status,
            "back": a.back.isoformat() if a.back else None,
            "slots": list(a.slots),
            "slot": a.slot,
            "protected": a.protected,
            "bench": a.bench,
            "net": None if a.net is None else _r(a.net),
            "advice": a.advice,
            "leave": None,
            "add": freed if a.advice == mv.STASH else None,
        }
        row["churn"] = None
        if a.leave is not None:
            lv = a.leave
            row["leave"] = {
                "player": lv.player,
                "slot": lv.slot,
                "how": lv.how,
                "drop": lv.drop,
                "net": None if lv.net is None else _r(lv.net),
                "protected": lv.protected,
            }
            row["churn"] = churn_of(recommended, lv.player) if lv.how == "drop" else None
        out.append(row)
    return out


def churn_of(recommended: Mapping[str, Any] | None, player: int) -> dict[str, Any] | None:
    """The recommended churn that drops held ``player`` (#221), the three weeks' set first: its
    add, what it adds to its set on that horizon and the horizon; None when no set holds one."""
    for key in ("three", "week"):
        for m in ((recommended or {}).get(key) or {}).get("moves") or []:
            if (m.get("held_drop") or {}).get("player") == player:
                return {"add": m["add"], "gain": m["marginal"][key], "horizon": key}
    return None


def moves_payload(built: Built) -> dict[str, Any]:
    """The table's gains for every candidate and the recommended set on each horizon, and first
    the held players whose cleared status blocks every add and the room a no-drop add has; the
    keep rule and the IL advice; the streaming plan and the week plans; the solve's seconds."""
    began = time.perf_counter()
    p = built.problem
    ev = mv.Evaluator(p)
    swaps = {key: mv.single_swaps(ev, key) for key in HORIZONS}
    candidates: dict[str, Any] = {}
    for cand, _ in p.candidates:
        row: dict[str, Any] = {"from": p.effective[cand].isoformat()}
        for key in HORIZONS:
            gains = swaps[key][cand]
            if not gains:
                row[key] = None
                continue
            best = gains[0]
            nxt = gains[1] if len(gains) > 1 else None
            move = mv.Move(cand, best.drop)
            row[key] = {
                "gain": _r(best.gain),
                "drop": best.drop,
                "held": _held_for(p, move) if mv.needs_spot(p, move) else None,
                "held_drop": held_drop(p, move),
                "next_drop": nxt.drop if nxt else None,
                "next_price": _r(best.gain - nxt.gain) if nxt else None,
                # This horizon's move to the season's end: the move the row's For shows.
                "ros": ros_move(built, mv.Move(cand, best.drop)),
            }
        if all(row[key] is None for key in HORIZONS):
            row["reason"] = no_move(p, cand)
        candidates[str(cand)] = row
    recommended = {}
    sets: dict[str, list[mv.Move]] = {}
    ros = guard_ros(built)
    guard = None if ros is None else mv.season_guard(ros)
    season = season_of(ros)
    for key in HORIZONS:
        ranked = sorted(
            (c for c, g in swaps[key].items() if g and g[0].gain > MIN_GAIN),
            key=lambda c: -swaps[key][c][0].gain,
        )
        watched = None if guard is None else Watched(guard)
        rec = mv.recommend(
            ev, key, ranked[:POOL], min_gain=MIN_GAIN, allowed=watched, season=season
        )
        sets[key] = [pm.move for pm in rec.moves]
        # The set the engine recommends without the guard, re-solves and all (a re-solve can
        # find the costly set the plain search misses), solved only when the guard refused a set:
        # else the guarded solve was the unguarded one.
        free = None
        if watched is not None and watched.refused:
            unguarded = mv.recommend(ev, key, ranked[:POOL], min_gain=MIN_GAIN, season=season)
            free = [pm.move for pm in unguarded.moves]
        held = held_by_add(p, sets[key])
        rows = [
            {
                **_move(pm.move, p),
                "held": held.get(pm.move.add),
                "held_drop": held_drop(p, pm.move),
                "decided_by": decided_by(pm, key, season),
                "marginal": {h: _r(v) for h, v in pm.marginal.items()},
                "ros": ros_move(built, pm.move),
                "price_without": _r(pm.price_without),
                "price_keep": None if pm.price_keep is None else _r(pm.price_keep),
                "instead_without": moves_with_held(p, pm.instead_without),
                "instead_keep": None
                if pm.instead_keep is None
                else moves_with_held(p, pm.instead_keep),
            }
            for pm in rec.moves
        ]
        recommended[key] = {
            "moves": rows,
            "gain": {h: _r(v) for h, v in rec.gain.items()},
            "ros": ros_total([r["ros"] for r in rows]),
            "held": [{"player": k, "slot": slot} for k, slot in rec.held],
            "comebacks": {h: comebacks_rows(cs) for h, cs in rec.comebacks.items()},
            "season_guard": held_back(built, ev, key, sets[key], ros, free),
        }
    stream = stream_of(built, ev, sets["week"], guard)
    return {
        "cleared": cleared_payload(p),
        "room": room_payload(p),
        "keep_rule": keep_payload(built),
        "stash": stash_payload(built, swaps, recommended),
        "system": built.system,
        "horizons": {key: {**built.horizons[key], "base": _r(ev.base[key])} for key in HORIZONS},
        "adds": built.adds,
        "candidates": candidates,
        "recommended": recommended,
        "plan": plan_payload(built, ev, sets["week"], recommended["week"]["moves"], stream, guard),
        "week_plans": week_plans_payload(
            built, ev, sets["week"], sets["three"], swaps["week"], stream, guard
        ),
        "unprojected": built.unprojected,
        "search": {
            "pool": POOL,
            "min_gain": MIN_GAIN,
            "seconds": round(time.perf_counter() - began, 3),
        },
    }


def _started(ev: mv.Evaluator, moves: list[mv.Move]) -> int:
    """My started games over the rest of this week with ``moves`` made."""
    return sum(pw.started for pw in ev.mine("week", moves)[0].players.values())


def stream_of(
    built: Built, ev: mv.Evaluator, against: list[mv.Move], allowed: mv.Allowed | None = None
) -> st.Plan | None:
    """The week's streaming plan (#136) against ``against``, solved once a moves solve for its
    section and the week plans' pool (#221 part 2); None without the league's scorer."""
    if built.rule is None or built.scorer is None:
        return None
    per_game = {k: wk.net_value(built.scorer, r) for k, r in built.problem.rates.items()}
    return st.plan(ev, built.rule, against, per_game, allowed=allowed)


def plan_payload(
    built: Built,
    ev: mv.Evaluator,
    against: list[mv.Move],
    rows: list[dict[str, Any]],
    plan: st.Plan | None,
    allowed: mv.Allowed | None = None,
) -> dict[str, Any] | None:
    """The week's streaming plan (#136, ``plan``: :func:`stream_of` on the same set and guard)
    against its recommended set (``against``, whose payload rows are ``rows``): the set's moves it keeps, its steps by day with each one's own gain on
    both horizons, the spots it turns over, my started games and the adds with no move, the set
    and the plan, and the plan's value beside the set's; recommended only when its week beats
    the set's by the floor (``season.stream.floor_of``), else by how much it falls short and
    why: ``short``, under the floor; ``guard``, when the plan with the best week would clear
    it but costs the three weeks after, which the planner never trades; or ``season``, when the
    season guard (``allowed``, #164) is what keeps it out, its rest of the season below zero.
    The refused plan's steps, games and gains are given (``guard``) so the user can make the
    trade by hand. None without a stream spot or the league's scorer (the keep rule's)."""
    p = built.problem
    if built.rule is None or built.scorer is None:
        return None
    per_game = {k: wk.net_value(built.scorer, r) for k, r in p.rates.items()}
    if plan is None:
        return None
    spot_of = {m: sp.occupant for sp in plan.spots for m in sp.steps}
    gains = st.step_gains(ev, plan)
    value = {
        name: {h: ev.value(h, moves) for h in HORIZONS}
        for name, moves in (("none", []), ("set", list(plan.against)), ("plan", list(plan.moves)))
    }
    gap = value["plan"]["week"] - value["set"]["week"]
    floor = st.floor_of(p)
    recommended = st.recommended(ev, plan)
    reason, guard = (None, None) if recommended else ("short", None)
    if not recommended:
        free = st.plan(ev, built.rule, against, per_game, guard=False, allowed=allowed)
        if free is not None and free.steps:
            gain = {h: ev.value(h, list(free.moves)) - value["set"][h] for h in HORIZONS}
            if gain["week"] > floor and gain["three"] < -mv.EPS:
                reason, guard = "guard", _guarded(built, ev, free, gain, rows)
    if reason == "short" and allowed is not None:
        # The plan with the season guard off: when it would clear the floor on the three-week
        # guard alone, the season guard is what refused it.
        wild = st.plan(ev, built.rule, against, per_game)
        if wild is not None and wild.steps and not allowed(wild.moves):
            gain = {h: ev.value(h, list(wild.moves)) - value["set"][h] for h in HORIZONS}
            if gain["week"] > floor:
                reason, guard = "season", _guarded(built, ev, wild, gain, rows)
    kept = set(plan.base)
    base = [
        {k: row[k] for k in ("add", "drop", "from", "held", "marginal", "ros")}
        for m, row in zip(against, rows, strict=True)
        if m in kept
    ]
    steps = [
        {
            **_move(m, p),
            "spot": spot_of[m],
            "marginal": {h: _r(g[h]) for h in HORIZONS},
            "ros": ros_move(built, m),
        }
        for m, g in zip(plan.steps, gains, strict=True)
    ]
    # Each move valued to the season's end as kept there, as the log values it: a streamer a
    # later step drops says which (#151); the plan's total telescopes over them.
    for row in base:
        row["dropped_by"] = _dropped_by(row["add"], plan.steps, p)
    for j, row in enumerate(steps):
        row["dropped_by"] = _dropped_by(row["add"], plan.steps[j + 1 :], p)
    return {
        "base": base,
        "steps": steps,
        "spots": [{"player": sp.occupant, "steps": len(sp.steps)} for sp in plan.spots],
        "games": {
            "none": _started(ev, []),
            "set": _started(ev, list(plan.against)),
            "plan": _started(ev, list(plan.moves)),
        },
        "held": [{"player": k, "slot": slot} for k, slot in mv.held_used(p, list(plan.moves))],
        "comebacks": {h: comebacks_rows(mv.comebacks(p, h, plan.moves)) for h in p.horizons},
        "adds": {"set": len(plan.against), "plan": len(plan.moves)},
        "value": {name: {h: _r(v) for h, v in vs.items()} for name, vs in value.items()},
        "gain": {h: _r(value["plan"][h] - value["set"][h]) for h in HORIZONS},
        "ros": {
            "set": ros_total([r["ros"] for r in rows]),
            "plan": ros_total([r["ros"] for r in (*base, *steps)]),
        },
        "recommended": recommended,
        "short": None if recommended else _r(max(0.0, floor - gap)),
        "floor": floor,
        "reason": reason,
        "guard": guard,
    }


def week_plans_payload(
    built: Built,
    ev: mv.Evaluator,
    week_set: list[mv.Move],
    three_set: list[mv.Move],
    swaps: dict[int, list[mv.SwapGain]],
    stream: st.Plan | None,
    allowed: mv.Allowed | None = None,
) -> dict[str, Any] | None:
    """The week plans (#221 part 2, ``season.plans``; ``stream``, the week's streaming plan whose
    chains join the pool): each plan's steps by day, each with its
    basis, its held moves, what it adds to the plan before it on both horizons, its rest of the
    season and the earlier steps it waits on (``after``, the ruling's condition: every earlier
    step), the roster's own changes on their day, the plan's total and its rest of the season;
    the plan the queue takes instead of the three weeks' set (``queue``, an index, None for
    none), the floor, the search's limits and its seconds. None with no day left in the week."""
    p = built.problem
    if not p.horizons["week"][0].days:
        return None
    began = time.perf_counter()
    plans = pl.week_plans(ev, week_set, swaps, stream, allowed, pl.held_out(ev))
    chosen = pl.for_queue(ev, plans, three_set)
    seconds = time.perf_counter() - began
    return {
        "plans": [_week_plan(built, w) for w in plans],
        "queue": None if chosen is None else plans.index(chosen),
        "floor": st.floor_of(p),
        "limits": {
            "plans": pl.WEEK_PLANS,
            "steps": pl.PLAN_STEPS,
            "beam": pl.BEAM,
            "exact": pl.EXACT,
        },
        "seconds": round(seconds, 3),
    }


def _week_plan(built: Built, w: pl.WeekPlan) -> dict[str, Any]:
    p = built.problem
    held = held_by_add(p, list(w.moves))
    steps = []
    for i, s in enumerate(w.steps):
        h = held.get(s.move.add) if mv.needs_spot(p, s.move) else None
        steps.append(
            {
                **_move(s.move, p),
                "held": h,
                "held_drop": held_drop(p, s.move),
                "basis": basis(p, s.move, h),
                "gain": {k: _r(v) for k, v in s.gain.items()},
                "ros": ros_move(built, s.move),
                "after": list(range(i)),
            }
        )
    backs = [
        {
            "player": b.player,
            "slot": b.slot,
            "day": b.day.isoformat(),
            "drop": b.drop,
            "returning": b.returning,
            "gain": None if b.gain is None else {k: _r(v) for k, v in b.gain.items()},
        }
        for b in w.backs
    ]
    return {
        "source": w.source,
        "steps": steps,
        "backs": backs,
        "total": {k: _r(v) for k, v in w.total.items()},
        "ros": ros_total([r["ros"] for r in steps]),
    }


def _dropped_by(add: int, later: tuple[mv.Move, ...], p: mv.MoveProblem) -> dict[str, Any] | None:
    """The first of the ``later`` steps that drops ``add``, with its day; None when none does."""
    step = next((m for m in later if m.drop == add), None)
    return None if step is None else {"add": step.add, **_day(step, p)}


def _guarded(
    built: Built,
    ev: mv.Evaluator,
    plan: st.Plan,
    gain: dict[str, float],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """The plan a guard refused (the three-week guard, or the season guard, #164): its steps by
    day with the spots they turn over, the spots, my started games with it and its gain on the
    set on both horizons, and on the rest of the season (#151) its moves' less the set's
    (``rows``)."""
    p = ev.problem
    spot_of = {m: sp.occupant for sp in plan.spots for m in sp.steps}
    mine = ros_total([ros_move(built, m) for m in plan.moves])
    theirs = ros_total([r["ros"] for r in rows])
    return {
        "steps": [{**_move(m, p), "spot": spot_of[m]} for m in plan.steps],
        "spots": [sp.occupant for sp in plan.spots if sp.steps],
        "games": _started(ev, list(plan.moves)),
        "gain": {h: _r(v) for h, v in gain.items()},
        "ros": None
        if mine is None or theirs is None
        else {"value": round(mine["value"] - theirs["value"], 4)},
    }


def best_payload(built: Built, payload: dict[str, Any]) -> dict[str, Any]:
    """The landing table's line for a league (#108, #191): the recommended move that adds most
    on the three weeks ahead (the rest of this week when no week follows), with the set's gain;
    for the row's panel the whole set on that horizon, each move with its basis and held move,
    the room, and the names of every player they mention."""
    key = "three" if built.horizons["three"]["weeks"] else "week"
    rec = payload["recommended"][key]
    p = built.problem
    names = {k: player.name for k, player in (*p.roster, *p.held, *p.candidates)}
    lines = [
        {
            "add": m["add"],
            "drop": m["drop"],
            "from": m["from"],
            "gain": m["marginal"][key],
            "basis": dl.basis_of(m["drop"], m["held"], m.get("held_drop") is not None),
            "held": m["held"],
            "held_drop": m.get("held_drop"),
        }
        for m in rec["moves"]
    ]
    room = payload.get("room")
    named = [
        *(k for m in lines for k in (m["add"], m["drop"])),
        *(m["held"]["player"] for m in lines if m["held"]),
        *(room["eligible"] if room else ()),
    ]
    best = max(rec["moves"], key=lambda m: m["marginal"][key], default=None)
    move = None
    if best is not None:
        move = {
            "add": best["add"],
            "add_name": names.get(best["add"]),
            "drop": best["drop"],
            "drop_name": None if best["drop"] is None else names.get(best["drop"]),
            "from": best["from"],
            "gain": best["marginal"][key],
        }
    return {
        "status": "solved",
        "system": built.system["key"],
        "horizon": key,
        "label": built.horizons[key]["label"],
        "move": move,
        "moves": len(rec["moves"]),
        "gain": rec["gain"][key],
        "min_gain": MIN_GAIN,
        "set": lines,
        "room": room,
        "names": {str(k): names[k] for k in named if k is not None and k in names},
    }


def _cats(ev: mv.Evaluator, key: str, moves: list[mv.Move]) -> dict[str, dict[str, Any]]:
    """Per category over horizon ``key``: expected wins summed over the weeks (each week's odds
    averaged over its opponents), and in a one-opponent week my final and theirs."""
    out: dict[str, dict[str, Any]] = {c: {"wins": 0.0} for c in ev.problem.cats}
    spans = ev.problem.horizons[key]
    for span, odds in zip(spans, ev.odds(key, moves), strict=True):
        for per_opp in odds:
            for o in per_opp:
                out[o.cat]["wins"] += o.p_win / len(odds)
        if len(spans) == 1 and len(odds) == 1:
            for o in odds[0]:
                out[o.cat] |= {"mine": o.mine, "theirs": o.theirs}
    return {
        c: {k: None if v is None else round(float(v), 4) for k, v in d.items()}
        for c, d in out.items()
    }


def detail_payload(built: Built, add: int, drop: int | None) -> dict[str, Any] | None:
    """The move drawer: per category before and after on both horizons, every drop the add can
    come with and the best other adds for this drop, each with both gains."""
    p = built.problem
    if add not in p.effective:
        return None
    ev = mv.Evaluator(p)
    move = [mv.Move(add, drop)]
    if not mv.feasible(p, move):
        return None
    horizons = {}
    for key in HORIZONS:
        horizons[key] = {
            "before": _r(ev.base[key]),
            "after": _r(ev.value(key, move)),
            "gain": _r(ev.gain(key, move)),
            "cats": {"before": _cats(ev, key, []), "after": _cats(ev, key, move)},
            "comebacks": comebacks_rows(mv.comebacks(p, key, move)),
        }
    # Every drop the add can come with, those the keep rule keeps too, marked: the drawer shows
    # what keeping them costs.
    drops = [
        {
            "drop": d,
            "kept": d in p.kept,
            "held": _held_for(p, mv.Move(add, d)) if mv.needs_spot(p, mv.Move(add, d)) else None,
            "held_drop": held_drop(p, mv.Move(add, d)),
            **{key: _r(ev.gain(key, [mv.Move(add, d)])) for key in HORIZONS},
            "ros": ros_move(built, mv.Move(add, d)),
        }
        for d in [None, *(k for k, _ in p.roster), *(k for k, _ in p.held)]
        if mv.feasible(p, [mv.Move(add, d)])
    ]
    drops.sort(key=lambda r: -r["three"])
    others = [
        {"add": c, **{key: _r(ev.gain(key, [mv.Move(c, drop)])) for key in HORIZONS}}
        for c, _ in p.candidates
        if c != add and mv.feasible(p, [mv.Move(c, drop)])
    ]
    others.sort(key=lambda r: -r["three"])
    shown = [
        {**r, "ros": ros_move(built, mv.Move(r["add"], drop))} for r in others[:ALTERNATIVE_ADDS]
    ]
    return {
        "add": add,
        "drop": drop,
        "from": p.effective[add].isoformat(),
        "held": [{"player": k, "slot": s} for k, s in mv.held_used(p, move)],
        "horizons": horizons,
        # The move to the season's end (#151), beside its two horizons.
        "ros": ros_move(built, move[0]),
        "drops": drops,
        "adds": shown,
    }


# --------------------------------------------------------------------------- the cache
class MovesCache:
    """The moves of a league per system, snapshot and day: the search takes seconds."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payloads: dict[tuple[Any, ...], Any] = {}
        self._building: dict[tuple[Any, ...], threading.Lock] = {}

    def peek(self, key: tuple[Any, ...]) -> Any:
        """The value for ``key`` when it was made, else None; nothing is made."""
        with self._lock:
            return self._payloads.get(key)

    def get(self, key: tuple[Any, ...], make: Callable[[], Any]) -> Any:
        """The value for ``key`` (``(league, system, kind, ...)``), made once; a newer key of
        the same league, system and kind replaces the older."""
        with self._lock:
            if key in self._payloads:
                return self._payloads[key]
            gate = self._building.setdefault(key, threading.Lock())
        with gate:
            with self._lock:
                if key in self._payloads:
                    return self._payloads[key]
            payload = make()
            with self._lock:
                # The latest only: an older snapshot's value is never asked again.
                for old in [k for k in self._payloads if k[:3] == key[:3]]:
                    del self._payloads[old]
                self._payloads[key] = payload
                self._building.pop(key, None)
            return payload
