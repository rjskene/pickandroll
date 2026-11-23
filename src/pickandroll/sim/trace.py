"""SEASON SIM (#172, PR trace): one path of one pair, written day by day.

A trace is arm A's and arm B's season on one path of a pair (the same seed, the same draws), as
the pair's task plays it, with :class:`Recorder` watching through the task's ``watch`` hook
(``cli.task_paired``): ``run.paired``'s ``on_day`` for each day record and ``on_end`` for the two
seasons' results. The recorder only reads. It writes nothing into a state, draws nothing, reads
no game's line and asks the engine nothing; what it calls besides the records is pure: the
week's view (``policy.week_view``), the standings before a week (``stake.table_before``), the
week's stake (``stake.level``), a week's result (``league.week_result``) and the pace's factor
(``bid_policy.pace`` on ``policy.bid_when``). A season played with it is the season played
without it (``tests/sim/test_sim_trace.py``).

What it holds, for each arm and each day (:meth:`Recorder.on_day`):

1. the day: its date, its week and whether the week is a bracket week;
2. ``knobs``, the values that move through a season, keyed by name: the season term's weight on
   this week's games and on the games after it (``season_weight`` and ``season_weight`` times
   ``1 - stake x L``, ``policy.later_share``'s), ``playoff_weight`` (a bracket day's games count
   that many times inside the term's figure), ``stake`` and the week's ``L`` as the seat reads
   it (as it would read it, for an arm that reads none), the adds this week and today against
   their caps, and under FAAB the dollars left and the pace's factor (None where the pace has
   no bound);
3. ``decision``: the tier and its solves, the set, its held-slot moves, the plan's steps,
   whether the plan led and whether the guard would have refused the set (``past_guard``,
   under the arm's guard ``off``), the union pool's refused count (at a ``guard_pool``), what
   was queued and the claims placed with their bids, what the queue left out and why
   (``policy.UNQUEUED``), what landed this morning, the claims decided this morning, and what
   was lost (a queued add that did not land, a claim not won). A tier that found nothing has
   an empty set; why it found nothing (the guard under ``block``, the floor, ``min_gain``) is
   the engine's and not here;
4. ``roster``: each player and his slot in the day's lineup (a starting slot, the bench
   :data:`BENCH`, or the held slot he is in);
5. ``matchup``: the opponent and both sides' totals as they stood that morning; the day's games
   show in the next morning's.

Each week, at its turn (and the last at the season's end): the week's final totals and its
result under the league's format, and every team's record and place in the standings before
the next week. At the season's end (:meth:`Recorder.on_end`): the whole league's standings,
the bracket and the seat's outcome and counts. For the pair: the days the two arms' decisions
differ (:meth:`Recorder.payload`).

A trace is a look at one path of its season: one path proves nothing, and a pair is judged on
its record's figures over every path."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from . import bid_policy as bp
from . import league as lg
from . import policy
from . import run as rn
from . import stake as stk
from .engine import mv
from .state import BENCH, LOST, WON, Setup, SimState

#: The trace record's own version: a change to what a trace holds or means moves it. A replay's
#: outcome never does (``replay_version`` is the replay's).
TRACE_VERSION = 1
#: The two arms, as a pair's record keys them; variant 0 is A's season and variant 1 is B's.
SIDES = ("a", "b")


def _move(m: mv.Move) -> list[Any]:
    return [m.add, m.drop]


def _finite(x: float) -> float | None:
    return x if math.isfinite(x) else None


def _totals(x: Mapping[str, float] | None) -> dict[str, float] | None:
    return None if x is None else {k: float(v) for k, v in sorted(x.items())}


def week_result(
    spec: lg.LeagueSpec | None, mine: Mapping[str, float], theirs: Mapping[str, float] | None
) -> dict[str, Any] | None:
    """A week's result under the league's format (``league.week_result``): categories won, lost
    and tied, each category's (a tie half), the matchup's outcome, and a points league's points;
    None with no opponent or no spec."""
    if spec is None or theirs is None:
        return None
    r = lg.week_result(mine, theirs, spec)
    return {
        "won": r.won,
        "lost": r.lost,
        "tied": r.tied,
        "outcome": r.outcome,
        "cats": dict(r.cats),
        **({"points": r.points_for} if spec.scoring == "points" else {}),
    }


def standing_rows(table: Sequence[lg.Standing]) -> list[dict[str, Any]]:
    """Every team's record and place, in the table's order."""
    return [
        {
            "team": s.team,
            "rank": s.rank,
            "wins": s.wins,
            "losses": s.losses,
            "ties": s.ties,
            "category_wins": s.category_wins,
            **({"points_for": s.points_for} if s.points_for else {}),
        }
        for s in table
    ]


def weeks_of(setup: Setup) -> list[dict[str, Any]]:
    """The season's weeks: number, first and last day, whether a bracket week, and a regular
    week's pairs."""
    bracket = set(setup.spec.playoff_weeks) if setup.spec is not None else set()
    return [
        {
            "week": w.number,
            "start": w.start.isoformat(),
            "end": w.end.isoformat(),
            "bracket": w.number in bracket,
            "pairs": [list(p) for p in setup.pairings.get(w.number, ())],
        }
        for w in setup.calendar.weeks
        if setup.week_of(w.start) is not None
    ]


class Recorder:
    """What :mod:`trace` holds of a pair's path, gathered from its day records and results. One
    recorder a path: ``setups`` are the two arms' leagues by :data:`SIDES` (one object when the
    two share a draft), ``me`` the seat, ``arms`` the two arms by :data:`SIDES`."""

    def __init__(self, setups: Mapping[str, Setup], me: int, arms: Mapping[str, rn.Arm]) -> None:
        self.setups = {s: setups[s] for s in SIDES}
        self.me = me
        self.arms = {s: arms[s] for s in SIDES}
        self.days: dict[str, list[dict[str, Any]]] = {s: [] for s in SIDES}
        self.weeks: dict[str, list[dict[str, Any]]] = {s: [] for s in SIDES}
        self.end: dict[str, dict[str, Any]] = {}
        self.players: set[int] = set()
        self._week: dict[str, int | None] = dict.fromkeys(SIDES)
        self._opponent: dict[str, int | None] = dict.fromkeys(SIDES)
        self._level: dict[str, float | None] = dict.fromkeys(SIDES)
        self._queued: dict[str, tuple[mv.Move, ...]] = {s: () for s in SIDES}

    # ------------------------------------------------------------------- the hooks
    def hooks(self) -> tuple[Any, Any]:
        """``on_day`` and ``on_end``, as ``cli.task_paired``'s ``watch`` returns them."""
        return self.on_day, self.on_end

    def on_day(self, r: rn.DayRecord) -> None:
        """One day of one arm's season (``run.DayRecord``: after the landing, the decisions, the
        queue and the lineup; before the day's games are scored)."""
        side = SIDES[r.variant]
        setup, me, state = self.setups[side], self.me, r.state
        week = setup.week_of(r.day)
        if week is None:  # the runner plays no such day
            return
        if self._week[side] != week.number:
            self._turn(side, setup, state, week.number)
        bracket = setup.spec is not None and week.number in setup.spec.playoff_weeks
        view = policy.week_view(setup, state, me, week.number)
        decision = self._decision(side, setup, r)
        self.days[side].append(
            {
                "date": r.day.isoformat(),
                "week": week.number,
                "bracket": bracket,
                "knobs": self._knobs(side, setup, state, r),
                "decision": decision,
                "roster": self._roster(state, r.starters.get(me, {})),
                "matchup": {
                    "opponent": view.opponent,
                    "me": _totals(dict(view.so_far)),
                    "them": None
                    if view.so_far_theirs is None
                    else _totals(dict(view.so_far_theirs)),
                },
            }
        )

    def on_end(self, ra: rn.VariantResult, rb: rn.VariantResult) -> None:
        """The two seasons' results: the last week closed on the season's final totals, and the
        season's end."""
        for side, v in zip(SIDES, (ra, rb), strict=True):
            setup = self.setups[side]
            if self._week[side] is not None:
                self._close(side, setup, v.totals, self._week[side])
            res = v.result
            self.end[side] = {
                "outcome": dict(v.summaries.get(self.me) or {}),
                "standings": [] if res is None else standing_rows(res.standings),
                "bracket": None
                if res is None
                else {
                    "seeds": {str(k): t for k, t in sorted(res.playoffs.seeds.items())},
                    "rounds": [[list(m) for m in rd] for rd in res.playoffs.rounds],
                    "champion": res.playoffs.champion,
                },
                "counts": dict(v.counts.get(self.me) or {}),
                "executed": v.executed,
                "gone": v.gone,
                "forced_drops": v.forced_drops,
                "breaches": [b.payload() for b in v.breaches],
                "bracket_unread": v.bracket_unread,
            }

    # ------------------------------------------------------------------- the parts
    def _turn(self, side: str, setup: Setup, state: SimState, number: int) -> None:
        """A week begins: the last one closed on this morning's totals (its days are all in),
        the standings before this one, the week's opponent and stake."""
        if self._week[side] is not None:
            self._close(side, setup, state.totals, self._week[side])
        self._week[side] = number
        self._opponent[side] = policy.opponent_of(setup, state, self.me, number)
        spec = setup.spec
        if spec is None:
            self._level[side] = None
        else:
            held = state.stakes.get(self.me)
            self._level[side] = (
                float(held) if held is not None else stk.level(spec, state.totals, self.me, number)
            )
        self.weeks[side].append(
            {
                "week": number,
                "opponent": self._opponent[side],
                "standings_before": []
                if spec is None
                else standing_rows(stk.table_before(spec, state.totals, number)),
            }
        )

    def _close(
        self,
        side: str,
        setup: Setup,
        totals: Mapping[int, Mapping[int, Mapping[str, float]]],
        number: int | None,
    ) -> None:
        if number is None or not self.weeks[side]:
            return
        block = self.weeks[side][-1]
        if "final" in block:
            return
        opp = self._opponent[side]
        mine = dict(totals.get(number, {}).get(self.me, {}))
        theirs = None if opp is None else dict(totals.get(number, {}).get(opp, {}))
        block["final"] = {"me": _totals(mine), "them": _totals(theirs)}
        block["result"] = week_result(setup.spec, mine, theirs)

    def _knobs(self, side: str, setup: Setup, state: SimState, r: rn.DayRecord) -> dict[str, Any]:
        arm, me = self.arms[side], self.me
        weight = float(policy.knob(arm.knobs, "season_weight"))
        level = self._level[side]
        share = 1.0 - arm.stake * (level or 0.0)
        today = len(r.queued.get(me, ())) + sum(
            1 for c in r.claims.get(me, ()) if c.placed == r.day
        )
        out: dict[str, Any] = {
            "season_weight": weight,
            "season_weight_later": weight * share,
            "later_share": share,
            "playoff_weight": float(policy.knob(arm.knobs, "playoff_weight")),
            "stake": float(arm.stake),
            "stake_level": level,
            "reads_stake": arm.stake > 0,
            "adds_week": int(state.adds_used.get(me, 0)),
            "adds_week_cap": setup.max_weekly_adds,
            "adds_today": today,
            "adds_today_cap": int(policy.knob(arm.knobs, "daily_cap")),
        }
        if setup.bidding:
            dollars = int(state.dollars.get(me, 0))
            out |= {"faab_left": dollars, "faab_budget": setup.budget}
            rule = arm.bid
            if rule is not None and rule.pace is not None:
                seen = bp.Seen(
                    0.0,
                    0.0,
                    float(dollars),
                    budget=setup.budget,
                    when=policy.bid_when(setup, r.day),
                )
                out["pace"] = _finite(bp.pace(rule, seen))
        return out

    def _decision(self, side: str, setup: Setup, r: rn.DayRecord) -> dict[str, Any]:
        me = self.me
        d = r.decisions.get(me)
        queued = tuple(r.queued.get(me, ()))
        landed = tuple(r.landed.get(me, ()))
        # What was queued to land this morning (yesterday's queue), or in a same-day league today.
        due = queued if setup.same_day else self._queued[side]
        on = {(m.add, m.drop) for m in landed}
        lost = [_move(m) for m in due if (m.add, m.drop) not in on]
        self._queued[side] = queued
        claims = tuple(r.claims.get(me, ()))
        cleared = [x for x in r.cleared if x.team == me]
        lost += [[x.add, x.drop] for x in cleared if x.outcome == LOST]
        moves = [] if d is None else [_move(m) for m in d.moves]
        plan = (
            [] if d is None else [[*_move(m), m.day.isoformat() if m.day else None] for m in d.plan]
        )
        for m in (*(d.moves if d else ()), *(d.plan if d else ()), *queued, *landed):
            self.players.update(x for x in (m.add, m.drop) if x is not None)
        self.players.update(c.move.add for c in claims)
        return {
            "tier": None if d is None else d.source,
            "solves": 0 if d is None else d.solves,
            "set": moves,
            "held": [] if d is None else [list(h) for h in d.held],
            "plan": plan,
            "plan_leads": bool(d and d.plan_leads),
            "past_guard": bool(d and d.past_guard),
            "union_refused": None if d is None or d.union is None else d.union.refused,
            "queued": [_move(m) for m in queued],
            "claims": [
                {
                    "add": c.move.add,
                    "drop": c.move.drop,
                    "clears": c.clears.isoformat(),
                    "bid": c.bid,
                    "churn": c.churn,
                }
                for c in claims
                if c.placed == r.day
            ],
            "unqueued": [[*_move(m), why] for m, why in r.unqueued.get(me, ())],
            "landed": [_move(m) for m in landed],
            "cleared": [
                {"add": x.add, "drop": x.drop, "won": x.outcome == WON, "bid": x.bid}
                for x in cleared
            ],
            "lost": lost,
        }

    def _roster(self, state: SimState, starters: Mapping[int, str]) -> list[list[Any]]:
        rows = []
        for p, slot in state.rosters.get(self.me, ()):
            self.players.add(p)
            rows.append([p, slot if slot in mv.HELD else starters.get(p, BENCH)])
        return rows

    # ------------------------------------------------------------------- the record
    def differ(self) -> dict[str, Any]:
        """The days the two arms' decisions for the seat differ: the set, what was queued or the
        claims placed (on a date both seasons hold)."""

        def key(day: Mapping[str, Any]) -> tuple[Any, ...]:
            d = day["decision"]
            return (
                d["set"],
                d["queued"],
                [(c["add"], c["drop"]) for c in d["claims"]],
            )

        a = {x["date"]: key(x) for x in self.days["a"]}
        b = {x["date"]: key(x) for x in self.days["b"]}
        days = sorted(t for t in set(a) & set(b) if a[t] != b[t])
        return {"days": days, "first": days[0] if days else None, "count": len(days)}

    def payload(self) -> dict[str, Any]:
        """What the trace holds of the path (the command adds the run's own keys): the league's
        weeks, teams and players, each arm's days, weeks and end, and the days they differ."""
        setup = self.setups["a"]
        members = {**self.setups["b"].players, **setup.players}
        return {
            "trace_version": TRACE_VERSION,
            "seat": self.me,
            "teams": list(setup.teams),
            "cats": list(setup.cats),
            "scoring": setup.scoring,
            "same_day": setup.same_day,
            "weeks": weeks_of(setup),
            "players": {
                str(k): {
                    "name": members[k].name,
                    "team": members[k].nba_team,
                    "positions": list(members[k].positions),
                }
                for k in sorted(self.players)
                if k in members
            },
            "arms": {
                s: {"days": self.days[s], "weeks": self.weeks[s], "end": self.end.get(s)}
                for s in SIDES
            },
            "differ": self.differ(),
        }


__all__ = [
    "SIDES",
    "TRACE_VERSION",
    "Recorder",
    "standing_rows",
    "week_result",
    "weeks_of",
]
