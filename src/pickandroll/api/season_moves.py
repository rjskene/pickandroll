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
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ..season import Player, Season
from ..season import moves as mv
from ..season import weekly as wk
from ..sources.injuries import Listed
from ..sources.matching import match_players
from . import season_flags
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
HORIZONS = ("week", "three")


@dataclass(frozen=True)
class Built:
    problem: mv.MoveProblem
    system: dict[str, Any]
    horizons: dict[str, dict[str, Any]]
    adds: dict[str, Any]
    #: Available players in the pool without a projection in the system (no move is valued).
    unprojected: int


@dataclass(frozen=True)
class Rated:
    """A system's rates and per-game values for the season's players."""

    rates: dict[int, wk.Rates]
    value: dict[int, float]
    info: dict[str, Any]
    players: dict[int, Player]
    bbm: sw.System
    yahoo: sw.System


def system_rates(season: Season, data_dir: Path, system: str) -> Rated:
    """The rates of ``system``: Basketball Monster's, or Yahoo's next seven days for the
    available players with Basketball Monster's line for everyone else."""
    s = season.settings
    players = sw.season_players(season)
    bbm = sw.bbm_system(data_dir, players)
    yahoo = sw.yahoo_system(season)
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = tuple(s.cats)
    if system == "yahoo":
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


def build(season: Season, today: date, data_dir: Path, system: str) -> Built | None:
    """The move problem for my team, or None when the season lacks my team or its weeks."""
    s = season.settings
    mine = s.my_team_id
    if mine is None or not season.calendar or mine not in season.rosters:
        return None
    points = dict(s.points) if s.scoring == "points" and s.points else None
    cats = tuple(s.cats)
    rated = system_rates(season, data_dir, system)
    rates, value, info, yahoo = rated.rates, rated.value, rated.info, rated.yahoo
    players = rated.players
    matchup, read_at = sw.matchup_read(season, mine)
    since = sw.first_day(read_at, today) if matchup is not None else today
    ahead = sw.spans(season, today, data_dir, WEEKS_AHEAD, players, since)
    if not ahead or not ahead[0].days:
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
    slot_count = Counter(s.roster)
    taken = Counter(sp.slot for sp in spots if sp.slot in mv.HELD)
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
    used, limits = add_limits(season, mine, ahead, today)
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
    )
    names = {t.team_id: t.name for t in season.teams}
    horizons = {
        "week": {
            "label": f"rest of week {this.number}"
            + (f" against {names.get(other, f'team {other}')}" if other is not None else ""),
            "weeks": [this.number],
            "from": since.isoformat(),
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
    return Built(problem, {"key": system, **info}, horizons, adds, unprojected)


# --------------------------------------------------------------------------- the payloads
def _move(m: mv.Move, problem: mv.MoveProblem) -> dict[str, Any]:
    return {"add": m.add, "drop": m.drop, "from": problem.effective[m.add].isoformat()}


def _r(x: float) -> float:
    return round(float(x), 3)


def _comebacks(cs: list[mv.Comeback] | tuple[mv.Comeback, ...]) -> list[dict[str, Any]]:
    return [
        {"player": c.player, "slot": c.slot, "from": c.day.isoformat(), "drop": c.drop} for c in cs
    ]


def moves_payload(built: Built) -> dict[str, Any]:
    """The table's gains for every candidate and the recommended set on each horizon."""
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
            row[key] = {
                "gain": _r(best.gain),
                "drop": best.drop,
                "next_drop": nxt.drop if nxt else None,
                "next_price": _r(best.gain - nxt.gain) if nxt else None,
            }
        candidates[str(cand)] = row
    recommended = {}
    for key in HORIZONS:
        ranked = sorted(
            (c for c, g in swaps[key].items() if g and g[0].gain > MIN_GAIN),
            key=lambda c: -swaps[key][c][0].gain,
        )
        rec = mv.recommend(ev, key, ranked[:POOL], min_gain=MIN_GAIN)
        recommended[key] = {
            "moves": [
                {
                    **_move(pm.move, p),
                    "marginal": {h: _r(v) for h, v in pm.marginal.items()},
                    "price_without": _r(pm.price_without),
                    "price_keep": None if pm.price_keep is None else _r(pm.price_keep),
                    "instead_without": [_move(m, p) for m in pm.instead_without],
                    "instead_keep": None
                    if pm.instead_keep is None
                    else [_move(m, p) for m in pm.instead_keep],
                }
                for pm in rec.moves
            ],
            "gain": {h: _r(v) for h, v in rec.gain.items()},
            "held": [{"player": k, "slot": slot} for k, slot in rec.held],
            "comebacks": {h: _comebacks(cs) for h, cs in rec.comebacks.items()},
        }
    return {
        "system": built.system,
        "horizons": {key: {**built.horizons[key], "base": _r(ev.base[key])} for key in HORIZONS},
        "adds": built.adds,
        "candidates": candidates,
        "recommended": recommended,
        "unprojected": built.unprojected,
        "search": {"pool": POOL, "min_gain": MIN_GAIN},
    }


def best_payload(built: Built, payload: dict[str, Any]) -> dict[str, Any]:
    """The landing grid's line for a league (#108): the recommended move that adds most on the
    three weeks ahead (the rest of this week when no week follows), with the set's gain."""
    key = "three" if built.horizons["three"]["weeks"] else "week"
    rec = payload["recommended"][key]
    p = built.problem
    names = {k: player.name for k, player in (*p.roster, *p.held, *p.candidates)}
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
            "comebacks": _comebacks(mv.comebacks(p, key, move)),
        }
    drops = [
        {"drop": d, **{key: _r(ev.gain(key, [mv.Move(add, d)])) for key in HORIZONS}}
        for d in mv.drop_options(p)
        if mv.feasible(p, [mv.Move(add, d)])
    ]
    drops.sort(key=lambda r: -r["three"])
    others = [
        {"add": c, **{key: _r(ev.gain(key, [mv.Move(c, drop)])) for key in HORIZONS}}
        for c, _ in p.candidates
        if c != add and mv.feasible(p, [mv.Move(c, drop)])
    ]
    others.sort(key=lambda r: -r["three"])
    return {
        "add": add,
        "drop": drop,
        "from": p.effective[add].isoformat(),
        "held": [{"player": k, "slot": s} for k, s in mv.held_used(p, move)],
        "horizons": horizons,
        "drops": drops,
        "adds": others[:ALTERNATIVE_ADDS],
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
