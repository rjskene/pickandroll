"""Live draft state and next-pick recommendations.

A :class:`DraftState` is the single source of truth during a draft: league settings, the
projection set in play, the z-scores derived from it, and the ordered log of picks. Picks arrive
from the Yahoo feed or from manual entry; either way :meth:`DraftState.apply_pick` records them,
and :meth:`DraftState.recommend_horizon` re-solves the plan from the new board. That re-solve
after every pick is the "roll" in pickandroll.

The default objective is the category-win curve (:attr:`DraftState.curve`): the plan maximizes
the expected number of categories won and concedes a category only when the board has made it
unwinnable. No punt is ever chosen on this path; the punt arguments remain for studies. With
``curve`` set to ``None`` the plan maximizes the plain sum of category totals instead.

Keepers (``docs/KEEPERS.md``): a :class:`Keeper` takes his team's pick in the round he was kept
for. The log stays contiguous: his pick is appended the moment the draft reaches that slot, and
until then he counts as taken and, for his team, as rostered.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from ..availability.adp import SPREAD_BASE, SPREAD_GROWTH, conditional_availability, pseudo_adp
from ..availability.league import LeagueSurvivalTable
from ..availability.survival import SurvivalTable
from ..optim.horizon import (
    HorizonProblem,
    HorizonSolution,
    first_order_prices,
    first_order_table,
    horizon_pick_pool,
    scenarios_if_gone,
    solve_horizon,
)
from ..optim.objective import CategoryCurve, win_label
from ..optim.roster import RosterProblem, RosterSolution, pick_pool, punt_scan, solve_roster
from ..projections.schema import Cat, ProjectionSet
from ..projections.zscores import zscores
from .settings import LeagueSettings, pick_owner, snake_picks

#: Candidates per pick the plan keeps under the curve objective (see the 2026-09-23 study:
#: objective loss 0.008 of 5.2 at pick one, solve time a third).
CURVE_PLAN_CANDIDATES = 80


@dataclass(frozen=True)
class Pick:
    overall: int
    team: str
    player_id: str


class KeeperLogged(ValueError):
    """A keeper table change that would rewrite a keeper pick already in the log."""


class KeeperInvalid(ValueError):
    """A keeper table entry that cannot stand: ``index`` is its place in the table and
    ``reason`` says why (the message names the keeper too)."""

    def __init__(self, index: int, keeper: Keeper, reason: str) -> None:
        super().__init__(f"keeper {keeper}: {reason}")
        self.index = index
        self.reason = reason


@dataclass(frozen=True)
class Keeper:
    """A player kept by the team in draft ``position`` (``None``: mine, wherever my seat is), who
    takes that team's pick in ``round``."""

    position: int | None
    round: int
    player_id: str


def plan_fallback(problem: HorizonProblem, solution: HorizonSolution) -> str | None:
    """``"sum"`` when ``solution`` is the plain-sum fallback of a curve plan (it has no win
    probabilities), else ``None``."""
    return "sum" if problem.curve is not None and solution.expected_wins is None else None


@dataclass
class DraftState:
    settings: LeagueSettings
    projections: ProjectionSet
    my_team: str
    my_position: int
    z: pd.DataFrame = field(init=False)
    positions: Mapping[str, Sequence[str]] = field(init=False)
    picks: list[Pick] = field(default_factory=list)
    keepers: tuple[Keeper, ...] = ()
    pool_size: int | None = None
    adp: pd.Series | None = None
    adp_source: str = "none"
    solver_margin: int = 60
    replacement_window: int = 24
    #: Category-win objective for every solve; ``None`` keeps the sum of category totals.
    curve: CategoryCurve | None = None
    #: Simulated survival curves; ``None`` keeps the ADP model for availability.
    survival: SurvivalTable | None = None
    #: The league's own survival by ADP, read in market space (``availability``).
    league_survival: LeagueSurvivalTable | None = None
    #: The ADP model's spread, ``spread_base + spread_growth * adp`` picks.
    spread_base: float = SPREAD_BASE
    spread_growth: float = SPREAD_GROWTH
    #: Candidates per pick the plan considers (``HorizonProblem.max_candidates``); ``None``
    #: means every plausible player for the sum objective and 80 under the curve.
    plan_candidates: int | None = None
    #: Solver budgets. The plan keeps its incumbent when the limit is hit; a curve solve with no
    #: incumbent falls back to the sum objective.
    plan_time_limit: float = 20.0
    plan_gap: float = 0.01
    price_time_limit: float = 10.0
    last_punt_scan: pd.DataFrame | None = field(default=None, repr=False)
    last_timings: dict[str, float] = field(default_factory=dict, repr=False)
    #: ``"sum"`` when the last plan fell back from the curve to the sum objective.
    last_fallback: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not 1 <= self.my_position <= self.settings.num_teams:
            raise ValueError("my_position must be within the number of teams")
        pool = self.pool_size or self.settings.total_picks
        self.z = zscores(self.projections.df, cats=self.settings.cats, pool_size=pool)
        self.positions = self.projections.positions()
        self.effective_adp()  # records adp_source
        self.keepers = tuple(self.keepers)
        self._check_keepers()
        self._fill_keepers()

    # ------------------------------------------------------------------ keepers
    def keeper_overall(self, keeper: Keeper) -> int:
        """The overall pick a keeper takes: his team's pick in his round."""
        position = self.my_position if keeper.position is None else keeper.position
        return snake_picks(self.settings.num_teams, position, self.settings.roster_size)[
            keeper.round - 1
        ]

    def keeper_team(self, keeper: Keeper) -> str:
        """The team label a keeper's pick is logged under (as ``autopick.team_label``)."""
        mine = keeper.position is None or keeper.position == self.my_position
        return self.my_team if mine else f"Team {keeper.position}"

    @property
    def keeper_slots(self) -> dict[int, Keeper]:
        """Overall pick to the keeper who takes it."""
        return {self.keeper_overall(k): k for k in self.keepers}

    @property
    def pending_keepers(self) -> dict[int, Keeper]:
        """The keepers whose slots the draft has not reached yet, by overall pick."""
        return {o: k for o, k in self.keeper_slots.items() if o >= self.next_overall}

    def is_keeper_pick(self, pick: Pick) -> bool:
        keeper = self.keeper_slots.get(pick.overall)
        return keeper is not None and keeper.player_id == pick.player_id

    def _check_keepers(self) -> None:
        """Every keeper names a known player in a round of the draft and a seat in the league,
        one keeper per player and per slot, and agrees with the picks already logged."""
        self._check_table()
        self._check_log()

    def _check_table(self) -> None:
        """One keeper per player and per slot, each a known player in a round and a seat."""
        slots: dict[int, Keeper] = {}
        index: dict[str, int] = {}
        for i, k in enumerate(self.keepers):
            if k.player_id not in self.z.index:
                raise KeeperInvalid(i, k, "unknown player")
            if not 1 <= k.round <= self.settings.roster_size:
                raise KeeperInvalid(i, k, f"round outside 1-{self.settings.roster_size}")
            if k.position is not None and not 1 <= k.position <= self.settings.num_teams:
                raise KeeperInvalid(i, k, f"position outside 1-{self.settings.num_teams}")
            if k.player_id in index:
                raise KeeperInvalid(i, k, "the player is kept twice")
            overall = self.keeper_overall(k)
            if overall in slots:
                raise KeeperInvalid(i, k, f"pick {overall} is already {slots[overall]}")
            index[k.player_id] = i
            slots[overall] = k

    def _check_log(self) -> None:
        """The picks already logged agree with the keeper table."""
        slots = self.keeper_slots
        index = {k.player_id: i for i, k in enumerate(self.keepers)}
        for pick in self.picks:
            keeper = slots.get(pick.overall)
            if keeper is not None and keeper.player_id != pick.player_id:
                i = index[keeper.player_id]
                raise KeeperInvalid(i, keeper, f"pick {pick.overall} is {pick.player_id}")
            if pick.player_id in index and (keeper is None or keeper.player_id != pick.player_id):
                i = index[pick.player_id]
                raise KeeperInvalid(
                    i, self.keepers[i], f"the player was drafted with pick {pick.overall}"
                )

    def _fill_keepers(self) -> None:
        """Log the keepers' picks while the next pick is a keeper slot (two can follow on)."""
        slots = self.keeper_slots
        while not self.complete and self.next_overall in slots:
            keeper = slots[self.next_overall]
            self.picks.append(Pick(self.next_overall, self.keeper_team(keeper), keeper.player_id))

    def _only_keepers_logged(self) -> bool:
        return all(self.is_keeper_pick(p) for p in self.picks)

    def set_keepers(self, keepers: Sequence[Keeper], fixable: Collection[int] = ()) -> None:
        """Replace the keeper table. Before the first real pick the whole table may change (the
        keeper picks logged are re-derived); after it, only the slots the draft has not reached:
        a keeper in the log stays as he is (only the room's record can change him, see
        :meth:`replace_pick`). ``fixable``: reached picks with no keeper that a new keeper may
        take, his pick replacing the one logged there (a room's gap, a pick it never sent)."""
        old, n, picks = self.keepers, self.next_overall, list(self.picks)
        fresh = self._only_keepers_logged()
        logged = {o: k.player_id for o, k in self.keeper_slots.items() if o < n}
        if fresh:
            self.picks.clear()
        self.keepers = tuple(keepers)
        try:
            self._check_table()
            if not fresh:
                reached = {o: k.player_id for o, k in self.keeper_slots.items() if o < n}
                changed = sorted(
                    o for o in logged.keys() | reached.keys() if logged.get(o) != reached.get(o)
                )
                fixes = [o for o in changed if o in fixable and o not in logged]
                changed = [o for o in changed if o not in fixes]
                if changed:
                    raise KeeperLogged(f"pick {changed[0]} is in the log: its keeper cannot change")
                for o in fixes:
                    keeper = self.keeper_slots[o]
                    self.picks[o - 1] = Pick(o, self.keeper_team(keeper), keeper.player_id)
            self._check_log()
        except ValueError:
            self.keepers = old
            if not fresh:
                self.picks[:] = picks
            raise
        finally:
            self._fill_keepers()

    def set_my_position(self, position: int) -> None:
        """Move my seat (a room attach). Only before the first real pick: my keepers follow the
        seat, so the keeper picks already logged are re-derived."""
        if not 1 <= position <= self.settings.num_teams:
            raise ValueError("my_position must be within the number of teams")
        if position == self.my_position:
            return
        if not self._only_keepers_logged():
            raise ValueError(f"the session already has picks for draft position {self.my_position}")
        old = self.my_position
        self.picks.clear()
        self.my_position = position
        try:
            self._check_keepers()
        except ValueError:
            self.my_position = old
            raise
        finally:
            self._fill_keepers()

    def set_my_team(self, name: str) -> None:
        """Rename my team (a feed attach): my picks already in the log, keeper picks included,
        take the new name, since :attr:`my_roster` finds them by it."""
        old = self.my_team
        self.picks[:] = [
            Pick(p.overall, name, p.player_id) if p.team == old else p for p in self.picks
        ]
        self.my_team = name

    def drop_keeper(self, player_id: str) -> Keeper | None:
        """Remove a player's keeper entry (the room drafted him elsewhere: the table was
        wrong). Returns the entry removed, if any."""
        dropped = next((k for k in self.keepers if k.player_id == player_id), None)
        if dropped is not None:
            self.keepers = tuple(k for k in self.keepers if k is not dropped)
        return dropped

    def replace_pick(self, overall: int, team: str, player_id: str) -> list[Keeper]:
        """The room's record wins over the log at ``overall`` (a conflict): the pick is replaced
        in place, and the keeper entries it contradicts (the keeper of that slot, a keeper entry
        for the player now taken there) are dropped. Returns them."""
        if not 1 <= overall < self.next_overall:
            raise ValueError(f"pick {overall} is not in the log")
        dropped = []
        keeper = self.keeper_slots.get(overall)
        if keeper is not None and keeper.player_id != player_id:
            dropped.append(self.drop_keeper(keeper.player_id))
        if self.keeper_slots.get(overall) is None:
            mine = self.drop_keeper(player_id)
            if mine is not None:
                dropped.append(mine)
        self.picks[overall - 1] = Pick(overall=overall, team=team, player_id=player_id)
        return [k for k in dropped if k is not None]

    # ------------------------------------------------------------------ board state
    @property
    def taken(self) -> frozenset[str]:
        """Drafted players and the keepers still to come."""
        logged = {p.player_id for p in self.picks}
        return frozenset(logged | {k.player_id for k in self.pending_keepers.values()})

    @property
    def my_roster(self) -> list[str]:
        """My picks and my keepers still to come, in draft order."""
        mine = [(p.overall, p.player_id) for p in self.picks if p.team == self.my_team]
        mine += [
            (o, k.player_id)
            for o, k in self.pending_keepers.items()
            if self.keeper_team(k) == self.my_team
        ]
        return [pid for _, pid in sorted(mine)]

    @property
    def available(self) -> list[str]:
        taken = self.taken
        return [pid for pid in self.z.index if pid not in taken]

    def solver_players(self) -> list[str]:
        """Players worth modelling: my roster plus the best available by total z, enough to
        fill every remaining pick in the draft with a margin. Deep bench names only slow the
        solver down and never enter an optimal roster."""
        remaining = self.settings.total_picks - len(self.picks) - len(self.pending_keepers)
        keep = remaining + self.solver_margin
        best = self.z.loc[self.available, "total"].nlargest(keep).index.tolist()
        return list(dict.fromkeys(self.my_roster + best))

    @property
    def next_overall(self) -> int:
        return len(self.picks) + 1

    @property
    def my_slots(self) -> list[int]:
        """Every pick my seat owns in the snake, keeper rounds included."""
        return snake_picks(self.settings.num_teams, self.my_position, self.settings.roster_size)

    @property
    def my_picks(self) -> list[int]:
        """The picks I draft with: my slots less my keeper rounds."""
        kept = self.keeper_slots
        return [k for k in self.my_slots if k not in kept]

    @property
    def my_next_pick(self) -> int | None:
        upcoming = [k for k in self.my_picks if k >= self.next_overall]
        return upcoming[0] if upcoming else None

    @property
    def on_the_clock(self) -> bool:
        return self.my_next_pick == self.next_overall

    @property
    def complete(self) -> bool:
        return len(self.picks) >= self.settings.total_picks

    def owner_of(self, overall: int) -> tuple[int, int]:
        return pick_owner(self.settings.num_teams, overall)

    @property
    def my_remaining_picks(self) -> list[int]:
        return [k for k in self.my_picks if k >= self.next_overall]

    @property
    def open_slots(self) -> int:
        return self.settings.roster_size - len(self.my_roster)

    @property
    def objective(self) -> str:
        """``win`` with a category curve, else ``sum``."""
        return "win" if self.curve is not None else "sum"

    def team_names(self) -> dict[int, str]:
        """Draft position to team name: my team, the names seen in the pick log, and
        ``Team N`` for a position that has not picked yet."""
        names = {pos: f"Team {pos}" for pos in range(1, self.settings.num_teams + 1)}
        names[self.my_position] = self.my_team
        for pick in self.picks:
            _, pos = self.owner_of(pick.overall)
            if pos != self.my_position and not self.is_keeper_pick(pick):
                names[pos] = pick.team
        return names

    # ------------------------------------------------------------------ availability
    def set_adp(self, adp: pd.Series, source: str) -> None:
        """Market ADP keyed by projection id (for example from Yahoo). Missing players fall
        back to the pseudo ranking."""
        self.adp = adp.reindex(self.z.index)
        self.adp_source = source

    def effective_adp(self) -> pd.Series:
        """ADP for every player: market data where known, else a rank-based stand-in."""
        df = self.projections.df
        if "bbm_rank" in df.columns and df["bbm_rank"].notna().any():
            fallback = pseudo_adp(-df["bbm_rank"].astype(float).fillna(df["bbm_rank"].max() + 1))
            fallback_source = "bbm_rank"
        else:
            fallback = pseudo_adp(self.z["total"])
            fallback_source = "z_total"
        if "adp" in df.columns and df["adp"].notna().any():
            fallback = df["adp"].astype(float).fillna(fallback)
            fallback_source = "bbm_adp"
        if self.adp is None:
            self.adp_source = fallback_source
            return fallback
        return self.adp.fillna(fallback)

    def keepers_ahead(self, adp: pd.Series | None = None) -> pd.Series:
        """For each player, the keepers whose ADP is below his: they are not in the market, so
        the market reaches him that many picks sooner. Every keeper in the table counts, his
        slot reached or not, as every keeper slot counts in :meth:`market_pick`."""
        full = self.effective_adp()
        return self._keepers_ahead(full, full if adp is None else adp)

    def _keepers_ahead(self, full: pd.Series, adp: pd.Series) -> pd.Series:
        kept = np.sort(full.reindex([k.player_id for k in self.keepers]).dropna().to_numpy(float))
        ahead = np.searchsorted(kept, adp.to_numpy(float), side="left")
        return pd.Series(ahead, index=adp.index, dtype=int)

    def market_adp(self, adp: pd.Series | None = None) -> pd.Series:
        """ADP in keeper-adjusted space: the market's ADP minus the keepers ranked ahead. Equal to
        :meth:`effective_adp` without keepers."""
        full = self.effective_adp()
        adp = full if adp is None else adp
        return adp - self._keepers_ahead(full, adp)

    def market_pick(self, overall: int) -> int:
        """Overall pick ``overall`` counted among the market's picks: minus the keeper slots
        before it."""
        return overall - sum(1 for slot in self.keeper_slots if slot < overall)

    def spread(self, adp: pd.Series) -> pd.Series:
        """The ADP model's spread of each player's draft slot, in picks."""
        return self.spread_base + self.spread_growth * adp.astype(float)

    def availability(self, players: Sequence[str] | None = None) -> pd.DataFrame:
        """P(available at each of my remaining picks | still on the board now).

        The ADP model and the league table are read in market space (keeper-adjusted ADP at
        market picks), so keepers neither count as picks nor stand ahead of anyone. A simulated
        survival table already drafts the keepers at their slots and is read at overall picks.
        Either table overrides the ADP model where it knows the player."""
        adp = self.effective_adp()
        if players is not None:
            adp = adp.reindex(players)
        market = self.market_adp(adp)
        picks = self.my_remaining_picks
        now = self.market_pick(self.next_overall)
        at = [self.market_pick(k) for k in picks]
        frame = conditional_availability(market, now=now, picks=at, spread=self.spread(market))
        frame.columns = picks
        if self.league_survival is not None:
            league = self.league_survival.conditional(market, now=now, picks=at)
            league.columns = picks
            frame.update(league)
        if self.survival is not None:
            simulated = self.survival.conditional(
                list(adp.index), now=self.next_overall, picks=picks
            )
            frame.update(simulated)
        return frame

    @property
    def availability_source(self) -> str:
        if self.survival is not None:
            return "survival"
        return "league" if self.league_survival is not None else "adp"

    # ------------------------------------------------------------------ mutation
    def apply_pick(self, team: str, player_id: str, overall: int | None = None) -> Pick:
        """Record a pick. ``overall`` defaults to the next pick number. A keeper's slot takes
        only the keeper (his pick, logged when the draft reached it, is returned); any keeper
        whose slot comes next is logged at once."""
        if player_id not in self.z.index:
            raise KeyError(f"unknown player {player_id!r}")
        overall = self.next_overall if overall is None else overall
        keeper = self.keeper_slots.get(overall)
        if keeper is not None and overall < self.next_overall:
            if player_id != keeper.player_id:
                name = self.projections.df["player"].get(keeper.player_id, keeper.player_id)
                raise ValueError(f"pick {overall} is a keeper slot: {name}")
            return self.picks[overall - 1]
        kept = {k.player_id: o for o, k in self.pending_keepers.items()}
        if player_id in kept:
            raise ValueError(f"{player_id!r} is kept with pick {kept[player_id]}")
        if player_id in self.taken:
            raise ValueError(f"{player_id!r} was already drafted")
        if overall != self.next_overall:
            raise ValueError(f"expected pick {self.next_overall}, got {overall}")
        pick = Pick(overall=overall, team=team, player_id=player_id)
        self.picks.append(pick)
        self._fill_keepers()
        return pick

    def sync(self, picks: Sequence[tuple[int, str, str]]) -> list[Pick]:
        """Apply any picks from a full ``(overall, team, player_id)`` feed not yet recorded.
        A keeper's pick in the feed is checked against the keeper, never added twice."""
        known = {p.overall for p in self.picks if not self.is_keeper_pick(p)}
        added = []
        for overall, team, player_id in sorted(picks):
            if overall in known:
                continue
            kept = overall in self.keeper_slots
            pick = self.apply_pick(team, player_id, overall)
            if not kept:
                added.append(pick)
        return added

    def undo(self) -> list[Pick]:
        """Take back the last real pick and the keeper picks logged after it, which come back
        when the draft reaches their slots again. Returns them in draft order."""
        cut = len(self.picks)
        while cut and self.is_keeper_pick(self.picks[cut - 1]):
            cut -= 1
        if cut == 0:
            raise ValueError("no picks to undo")
        undone = self.picks[cut - 1 :]
        del self.picks[cut - 1 :]
        return undone

    # ------------------------------------------------------------------ solving
    def problem(
        self,
        punt: frozenset[Cat] | None = None,
        max_punts: int = 2,
        balance: float = 0.0,
        weights: Mapping[Cat, float] | None = None,
        availability: pd.Series | None = None,
        **extra,
    ) -> RosterProblem:
        """Roster problem for the current board: my roster locked, everyone drafted blocked."""
        players = self.solver_players()
        extra.setdefault("curve", self.curve)
        return RosterProblem(
            z=self.z.loc[players],
            positions={p: self.positions[p] for p in players},
            slots=self.settings.slots,
            cats=self.settings.cats,
            punt=punt,
            max_punts=max_punts,
            balance=balance,
            weights=weights,
            locks=frozenset(self.my_roster),
            blocks=frozenset(p for p in players if p in self.taken and p not in self.my_roster),
            raw=self.projections.df.loc[players],
            availability=availability,
            **extra,
        )

    def best_roster(self, **kwargs) -> RosterSolution:
        return solve_roster(self.problem(**kwargs))

    def candidates(
        self, n: int = 8, punt: frozenset[Cat] | None = None, expected: bool = False
    ) -> list[str]:
        """Top available players by punt-adjusted total z. With ``expected`` the total is
        weighted by the chance the player is still there at my next pick, which is what
        matters when someone else is on the clock."""
        cols = [c.value for c in self.settings.cats if not punt or c not in punt]
        totals = self.z.loc[self.available, cols].sum(axis=1)
        if expected and self.my_remaining_picks and not self.on_the_clock:
            avail = self.availability(self.available)[self.my_remaining_picks[0]]
            totals = totals.clip(lower=0) * avail
        return totals.nlargest(n).index.tolist()

    def recommend(
        self, n: int = 8, punt: frozenset[Cat] | None = frozenset(), **kwargs
    ) -> pd.DataFrame:
        """Price the top ``n`` available candidates by forcing each onto the best roster."""
        problem = self.problem(punt=punt, **kwargs)
        table = pick_pool(problem, self.candidates(n, punt))
        if not table.empty:
            table.insert(1, "name", table["player"].map(self.projections.df["player"]))
        return table

    # ------------------------------------------------------------------ rolling horizon
    def choose_punt(
        self,
        max_punts: int = 2,
        balance: float = 0.0,
        progress: Callable[[dict], None] | None = None,
        workers: int | None = None,
    ) -> frozenset[Cat]:
        """Best punt set for the current board from the roster model (fast, exact). The
        ranked strategy table is kept in ``last_punt_scan``. A study tool: the product's
        recommendation never chooses a punt."""
        scan = punt_scan(
            self.problem(punt=None, max_punts=max_punts, balance=balance),
            progress=progress,
            workers=workers,
        )
        self.last_punt_scan = scan.table
        return frozenset(scan.solutions[0].punted)

    def replacement_level(self) -> pd.Series:
        """Per-category z of a replacement-level player: the average over the players ranked
        just outside the draft (from the last pick to ``replacement_window`` past it). Values
        for planning are measured above this line so that a likely-available bench player is
        worth a little and an unlikely star is not worth more than nothing."""
        order = self.z.loc[self.available, "total"].sort_values(ascending=False).index
        # The keepers still to come take their slots without leaving the available board.
        start = max(0, self.settings.total_picks - len(self.picks) - len(self.pending_keepers) - 1)
        window = order[start : start + self.replacement_window]
        if len(window) == 0:
            window = order[-self.replacement_window :]
        cols = [c.value for c in self.settings.cats]
        return self.z.loc[window, cols].mean()

    def roster_value(self, punt: frozenset[Cat] | None = None, balance: float = 0.0) -> float:
        """What the sum objective is worth for the players already on my roster: their z above
        replacement level in the active categories (the locked part of the plan objective).
        With every pick made this is the final value of the draft on the z scale."""
        active = [c.value for c in self.settings.cats if not punt or c not in punt]
        if not self.my_roster or not active:
            return 0.0
        above = self.z.loc[self.my_roster, active] - self.replacement_level()[active]
        totals = above.sum(axis=0)
        return float((1.0 - balance) * totals.sum() + balance * totals.min())

    def wins_curve(self) -> CategoryCurve:
        """The curve wins are scored on: the session's, or the simulated league fit when the
        plan runs on the sum objective."""
        return self.curve if self.curve is not None else CategoryCurve.simulated(self.settings.cats)

    def horizon_curve(self, curve: CategoryCurve | None | str = "default") -> CategoryCurve | None:
        """The category curve on the plan's scale: plan totals are measured above replacement
        level, so the league's mean total moves down by ``roster_size * level``. ``curve``
        overrides the session's curve (``None`` for no curve at all)."""
        raw = self.curve if curve == "default" else curve
        if raw is None:
            return None
        level = self.replacement_level()
        size = self.settings.roster_size
        return raw.shift({c: -size * float(level[c.value]) for c in self.settings.cats})

    def roster_totals(self) -> pd.Series:
        """Raw z totals of the players already on my roster, per category."""
        cols = [c.value for c in self.settings.cats]
        if not self.my_roster:
            return pd.Series(0.0, index=cols)
        return self.z.loc[self.my_roster, cols].sum()

    def roster_wins(self, punt: frozenset[Cat] = frozenset()) -> float:
        """Expected categories won by the players already on my roster alone, on the wins
        curve and raw totals. With every pick made this is the draft's final expected wins."""
        totals = self.roster_totals()
        curve = self.wins_curve()
        return float(
            sum(
                curve.probability(c, float(totals[c.value]))
                for c in self.settings.cats
                if c not in punt
            )
        )

    def raw_finals(self, solution: HorizonSolution | None) -> pd.Series:
        """My expected final totals on the raw z scale: the plan's expected totals moved back
        from the replacement scale, or, without a plan, my drafted total plus replacement
        fill for every open slot."""
        level = self.replacement_level()
        cols = [c.value for c in self.settings.cats]
        if solution is not None:
            expected = pd.Series({c.value: float(v) for c, v in solution.expected_totals.items()})
            return expected.reindex(cols) + self.settings.roster_size * level[cols]
        return self.roster_totals() + self.open_slots * level[cols]

    def horizon_problem(
        self,
        punt: frozenset[Cat] = frozenset(),
        balance: float = 0.0,
        weights: Mapping[Cat, float] | None = None,
        curve: CategoryCurve | None | str = "default",
    ) -> HorizonProblem:
        """Plan over my remaining picks. Raises ``ValueError`` when picks and open slots differ
        (traded picks, odd manual entry), in which case callers fall back to the roster model.
        ``curve`` overrides the session's (``None`` plans on the sum objective)."""
        players = self.solver_players()
        cols = [c.value for c in self.settings.cats]
        z = self.z.loc[players, cols] - self.replacement_level()
        z["total"] = z.sum(axis=1)
        plan_curve = self.horizon_curve(curve)
        cap = self.plan_candidates
        if cap is None and plan_curve is not None:
            cap = CURVE_PLAN_CANDIDATES
        return HorizonProblem(
            z=z,
            positions={p: self.positions[p] for p in players},
            picks=self.my_remaining_picks,
            availability=self.availability(players),
            slots=self.settings.slots,
            cats=self.settings.cats,
            punt=punt,
            balance=balance,
            weights=weights,
            locks=frozenset(self.my_roster),
            blocks=frozenset(p for p in players if p in self.taken and p not in self.my_roster),
            max_candidates=cap,
            curve=plan_curve,
        )

    def solve_plan(
        self, problem: HorizonProblem, time_limit: float | None = None
    ) -> HorizonSolution:
        """Solve the plan within the session's budget (or ``time_limit``), keeping the incumbent
        at the time limit. A curve solve that produces no incumbent at all falls back to the sum
        objective (noted in ``last_fallback``)."""
        limit = self.plan_time_limit if time_limit is None else time_limit
        self.last_fallback = None
        try:
            return solve_horizon(problem, time_limit=limit, gap=self.plan_gap)
        except RuntimeError:
            if problem.curve is None:
                raise
        self.last_fallback = "sum"
        fallback = replace(problem, curve=None, max_candidates=self.plan_candidates)
        return solve_horizon(fallback, time_limit=limit, gap=self.plan_gap)

    def plan(
        self,
        punt: frozenset[Cat] | None = frozenset(),
        max_punts: int = 2,
        balance: float = 0.0,
        **kwargs,
    ) -> tuple[HorizonSolution, frozenset[Cat]]:
        """Solve the rolling-horizon plan. ``punt=None`` runs the study's punt scan first."""
        chosen = (
            punt if punt is not None else self.choose_punt(max_punts=max_punts, balance=balance)
        )
        solution = self.solve_plan(self.horizon_problem(chosen, balance=balance, **kwargs))
        return solution, chosen

    def recommend_horizon(
        self,
        n: int = 8,
        punt: frozenset[Cat] = frozenset(),
        workers: int | None = None,
        progress: Callable[[dict], None] | None = None,
        problem: HorizonProblem | None = None,
        candidates: Sequence[str] | None = None,
        plan_time_limit: float | None = None,
        on_plan: Callable[[HorizonSolution, pd.DataFrame, dict[str, float]], None] | None = None,
        base: HorizonSolution | None = None,
        timings: dict[str, float] | None = None,
        include: Callable[[], Sequence[str]] | None = None,
        **kwargs,
    ) -> tuple[pd.DataFrame, HorizonSolution, frozenset[Cat]]:
        """Candidates for my next pick priced with the waiting risk, plus the plan itself.

        Every candidate gets a first-order price the instant the plan is solved and an exact
        price when its forced re-solve finishes (in the process pool). ``progress`` receives
        staged updates (plan, first-order prices, each exact price); stage timings are kept in
        ``last_timings``. A caller that snapshots the board itself passes ``problem`` and
        ``candidates`` (see the API's background solver); the solve then never reads the pick
        log again and picks can land meanwhile.

        ``plan_time_limit`` overrides the plan's budget for this solve. ``on_plan`` receives the
        plan, its first-order candidate table (:func:`first_order_table`) and the timings so far
        before any exact price is solved; it may raise to stop the solve there. ``base`` is a
        plan already solved for ``problem`` (a pre-solved branch): it is priced, not solved
        again. ``timings``, when given, is filled with this solve's stage timings (solves that
        run at once on one state each read their own, not ``last_timings``). ``include`` is
        asked once the plan is solved for players the exact prices must also cover (the first
        pick of a plan already serving this board).
        """
        started = time.perf_counter()
        timings = {} if timings is None else timings
        self.last_punt_scan = None
        if problem is None:
            problem = self.horizon_problem(punt, **kwargs)
        solution = base if base is not None else self.solve_plan(problem, plan_time_limit)
        timings["plan_ms"] = (time.perf_counter() - started) * 1000
        if progress is not None:
            progress(
                {
                    "stage": "plan",
                    "done": 1,
                    "total": 1,
                    "objective": solution.objective,
                    "wins": solution.wins,
                    "first_pick": solution.first_pick,
                    "time_limited": solution.time_limited,
                    "fallback": plan_fallback(problem, solution),
                }
            )
        candidates = (
            list(candidates) if candidates is not None else self.candidates(n, punt, expected=True)
        )
        if solution.first_pick and solution.first_pick not in candidates:
            candidates.append(solution.first_pick)
        prices = first_order_prices(problem, solution, candidates)
        if on_plan is not None:
            early = first_order_table(problem, solution, candidates)
            if not early.empty:
                early.insert(1, "name", early["player"].map(self.projections.df["player"]))
            so_far = {**timings, "total_ms": timings["plan_ms"]}
            self.last_timings = so_far
            on_plan(solution, early, so_far)
        if include is not None:
            candidates += [
                p for p in include() if p not in candidates and p in problem.availability.index
            ]
        if progress is not None:
            progress(
                {
                    "stage": "prices",
                    "done": len(candidates),
                    "total": len(candidates),
                    "prices": {p: (None if pd.isna(v) else float(v)) for p, v in prices.items()},
                }
            )
        mark = time.perf_counter()
        table = horizon_pick_pool(
            problem,
            candidates,
            base=solution,
            workers=workers,
            progress=progress,
            time_limit=self.price_time_limit,
            gap=self.plan_gap,
        )
        timings["candidates_ms"] = (time.perf_counter() - mark) * 1000
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        timings["solver_players"] = float(len(problem.z))
        self.last_timings = timings
        if not table.empty:
            table.insert(1, "name", table["player"].map(self.projections.df["player"]))
        return table, solution, punt

    def scenarios(
        self,
        problem: HorizonProblem,
        table: pd.DataFrame,
        count: int = 3,
        threshold: float = 0.995,
        workers: int | None = None,
        progress: Callable[[dict], None] | None = None,
    ) -> list[dict]:
        """ "If he is gone" plans for the best-priced candidates who could be taken before my
        next pick (availability at my pick below ``threshold``), best candidates first: the
        answer for the case my first choice vanishes is ready before it is needed. Empty when
        the problem's first pick is on the clock (nobody can take anyone)."""
        if table.empty or count <= 0 or (problem.availability[problem.picks[0]] >= 1.0).all():
            return []
        likely_gone = table[table["p_available_first"] < threshold]["player"].head(count)
        players = [str(p) for p in likely_gone]
        if not players:
            return []
        rows = scenarios_if_gone(
            problem,
            players,
            time_limit=self.price_time_limit,
            gap=self.plan_gap,
            workers=workers,
            progress=progress,
        )
        names = self.projections.df["player"]
        for row in rows:
            row["gone_name"] = names.get(row["gone"], row["gone"])
            row["pick_name"] = names.get(row["pick"], row["pick"]) if row["pick"] else None
        return rows

    # ------------------------------------------------------------------ categories and league
    def board_prices(self, problem: HorizonProblem, solution: HorizonSolution) -> pd.Series:
        """First-order cost of taking each available player with my next pick instead of the
        plan's choice (NaN for players the solver never modelled)."""
        players = [p for p in problem.available]
        prices = first_order_prices(problem, solution, players)
        return prices.reindex(self.available)

    def team_totals(self) -> pd.DataFrame:
        """Every team's drafted category totals (raw z), indexed by team name, with the
        number of players on the roster (picks made and keepers still to come) and the draft
        position."""
        cols = [c.value for c in self.settings.cats]
        names = self.team_names()
        pending = self.pending_keepers
        rows = {}
        for pos, team in names.items():
            roster = [p.player_id for p in self.picks if self.owner_of(p.overall)[1] == pos]
            roster += [k.player_id for o, k in pending.items() if self.owner_of(o)[1] == pos]
            totals = self.z.loc[roster, cols].sum() if roster else pd.Series(0.0, index=cols)
            rows[team] = {"position": pos, "picks": len(roster), **totals.to_dict()}
        frame = pd.DataFrame.from_dict(rows, orient="index")
        frame.index.name = "team"
        return frame

    def projected_finals(self, my_final: Mapping[str, float] | None = None) -> pd.DataFrame:
        """Each team's projected final totals: drafted totals plus replacement-level fill for
        every open slot. My row uses ``my_final`` (the plan's expectation) when given."""
        cols = [c.value for c in self.settings.cats]
        level = self.replacement_level()[cols]
        totals = self.team_totals()
        open_slots = self.settings.roster_size - totals["picks"]
        finals = totals[cols].add(
            pd.DataFrame({c: open_slots * float(level[c]) for c in cols}, index=totals.index)
        )
        if my_final is not None and self.my_team in finals.index:
            for c in cols:
                finals.at[self.my_team, c] = float(my_final[c])
        return finals

    def matchups(self, my_final: Mapping[str, float] | None = None) -> dict:
        """Head-to-head tally against every opponent on projected finals: categories in which
        I lead, whether I win the matchup (a majority of the categories), and per category
        how many opponents I lead. Ties count against me."""
        cols = [c.value for c in self.settings.cats]
        finals = self.projected_finals(my_final)
        mine = finals.loc[self.my_team, cols]
        others = finals.drop(index=self.my_team)
        majority = len(cols) // 2 + 1
        opponents = []
        for team, row in others.iterrows():
            beaten = [c for c in cols if float(mine[c]) > float(row[c])]
            opponents.append(
                {
                    "team": team,
                    "cats_beaten": len(beaten),
                    "won": len(beaten) >= majority,
                    "leads": beaten,
                }
            )
        teams_beaten = {c: int((others[c] < float(mine[c])).sum()) for c in cols}
        return {
            "opponents": opponents,
            "matchups_won": sum(1 for o in opponents if o["won"]),
            "cats_beaten": (
                sum(o["cats_beaten"] for o in opponents) / len(opponents) if opponents else 0.0
            ),
            "teams_beaten": teams_beaten,
        }

    def category_report(self, finals: pd.Series | None = None) -> list[dict]:
        """One row per category: my drafted total, expected final total (``finals`` on the
        raw z scale, see :meth:`raw_finals`; replacement fill when ``None``), win odds and
        label, marginal value (categories won per z at the expected final), and the number of
        opponents my drafted total beats right now and my expected final beats at the end."""
        curve = self.wins_curve()
        drafted = self.roster_totals()
        if finals is None:
            finals = self.raw_finals(None)
        now = self.team_totals()
        others_now = now.drop(index=self.my_team) if self.my_team in now.index else now
        projected = self.matchups(finals)["teams_beaten"]
        rows = []
        for c in self.settings.cats:
            final = float(finals[c.value])
            odds = curve.probability(c, final)
            rows.append(
                {
                    "cat": c.value,
                    "drafted": round(float(drafted[c.value]), 3),
                    "expected": round(final, 3),
                    "odds": round(odds, 4),
                    "label": win_label(odds),
                    "slope": round(curve.slope(c, final), 4),
                    "beaten_now": int((others_now[c.value] < float(drafted[c.value])).sum()),
                    "beaten_expected": int(projected[c.value]),
                    "mu": round(float(curve.mu[c]), 3),
                    "sigma": round(float(curve.sigma[c]), 3),
                }
            )
        return rows

    def expected_wins(self, finals: pd.Series | None = None) -> float:
        """Expected categories won by my expected final totals (raw z scale, replacement fill
        when ``None``) on the wins curve."""
        if finals is None:
            finals = self.raw_finals(None)
        curve = self.wins_curve()
        return float(sum(curve.probability(c, float(finals[c.value])) for c in self.settings.cats))
