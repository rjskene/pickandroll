"""Live draft state and next-pick recommendations.

A :class:`DraftState` is the single source of truth during a draft: league settings, the
projection set in play, the z-scores derived from it, and the ordered log of picks. Picks arrive
from the Yahoo feed or from manual entry; either way :meth:`DraftState.apply_pick` records them,
and :meth:`DraftState.recommend` re-solves the roster problem from the new board. That re-solve
after every pick is the "roll" in pickandroll.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from ..availability.adp import conditional_availability, pseudo_adp
from ..optim.horizon import HorizonProblem, HorizonSolution, horizon_pick_pool, solve_horizon
from ..optim.roster import RosterProblem, RosterSolution, pick_pool, punt_scan, solve_roster
from ..projections.schema import Cat, ProjectionSet
from ..projections.zscores import zscores
from .settings import LeagueSettings, pick_owner, snake_picks


@dataclass(frozen=True)
class Pick:
    overall: int
    team: str
    player_id: str


@dataclass
class DraftState:
    settings: LeagueSettings
    projections: ProjectionSet
    my_team: str
    my_position: int
    z: pd.DataFrame = field(init=False)
    positions: Mapping[str, Sequence[str]] = field(init=False)
    picks: list[Pick] = field(default_factory=list)
    pool_size: int | None = None
    adp: pd.Series | None = None
    adp_source: str = "none"
    solver_margin: int = 60

    def __post_init__(self) -> None:
        if not 1 <= self.my_position <= self.settings.num_teams:
            raise ValueError("my_position must be within the number of teams")
        pool = self.pool_size or self.settings.total_picks
        self.z = zscores(self.projections.df, cats=self.settings.cats, pool_size=pool)
        self.positions = self.projections.positions()
        self.effective_adp()  # records adp_source

    # ------------------------------------------------------------------ board state
    @property
    def taken(self) -> frozenset[str]:
        return frozenset(p.player_id for p in self.picks)

    @property
    def my_roster(self) -> list[str]:
        return [p.player_id for p in self.picks if p.team == self.my_team]

    @property
    def available(self) -> list[str]:
        taken = self.taken
        return [pid for pid in self.z.index if pid not in taken]

    def solver_players(self) -> list[str]:
        """Players worth modelling: my roster plus the best available by total z, enough to
        fill every remaining pick in the draft with a margin. Deep bench names only slow the
        solver down and never enter an optimal roster."""
        remaining = self.settings.total_picks - len(self.picks)
        keep = remaining + self.solver_margin
        best = self.z.loc[self.available, "total"].nlargest(keep).index.tolist()
        return list(dict.fromkeys(self.my_roster + best))

    @property
    def next_overall(self) -> int:
        return len(self.picks) + 1

    @property
    def my_picks(self) -> list[int]:
        return snake_picks(self.settings.num_teams, self.my_position, self.settings.roster_size)

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

    def availability(self, players: Sequence[str] | None = None) -> pd.DataFrame:
        """P(available at each of my remaining picks | still on the board now)."""
        adp = self.effective_adp()
        if players is not None:
            adp = adp.reindex(players)
        return conditional_availability(adp, now=self.next_overall, picks=self.my_remaining_picks)

    # ------------------------------------------------------------------ mutation
    def apply_pick(self, team: str, player_id: str, overall: int | None = None) -> Pick:
        """Record a pick. ``overall`` defaults to the next pick number."""
        if player_id not in self.z.index:
            raise KeyError(f"unknown player {player_id!r}")
        if player_id in self.taken:
            raise ValueError(f"{player_id!r} was already drafted")
        overall = self.next_overall if overall is None else overall
        if overall != self.next_overall:
            raise ValueError(f"expected pick {self.next_overall}, got {overall}")
        pick = Pick(overall=overall, team=team, player_id=player_id)
        self.picks.append(pick)
        return pick

    def sync(self, picks: Sequence[tuple[int, str, str]]) -> list[Pick]:
        """Apply any picks from a full ``(overall, team, player_id)`` feed not yet recorded."""
        known = {p.overall for p in self.picks}
        added = []
        for overall, team, player_id in sorted(picks):
            if overall in known:
                continue
            added.append(self.apply_pick(team, player_id, overall))
        return added

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

    def recommend(self, n: int = 8, punt: frozenset[Cat] | None = None, **kwargs) -> pd.DataFrame:
        """Price the top ``n`` available candidates by forcing each onto the best roster."""
        problem = self.problem(punt=punt, **kwargs)
        table = pick_pool(problem, self.candidates(n, punt))
        if not table.empty:
            table.insert(1, "name", table["player"].map(self.projections.df["player"]))
        return table

    # ------------------------------------------------------------------ rolling horizon
    def choose_punt(self, max_punts: int = 2, balance: float = 0.0) -> frozenset[Cat]:
        """Best punt set for the current board from the roster model (fast, exact)."""
        scan = punt_scan(self.problem(punt=None, max_punts=max_punts, balance=balance))
        return frozenset(scan.solutions[0].punted)

    def horizon_problem(
        self,
        punt: frozenset[Cat],
        balance: float = 0.0,
        weights: Mapping[Cat, float] | None = None,
    ) -> HorizonProblem:
        """Plan over my remaining picks. Raises ``ValueError`` when picks and open slots differ
        (traded picks, odd manual entry), in which case callers fall back to the roster model."""
        players = self.solver_players()
        return HorizonProblem(
            z=self.z.loc[players],
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
        )

    def plan(
        self, punt: frozenset[Cat] | None = None, max_punts: int = 2, balance: float = 0.0, **kwargs
    ) -> tuple[HorizonSolution, frozenset[Cat]]:
        """Solve the rolling-horizon plan; choose the punt first when none is given."""
        chosen = (
            punt if punt is not None else self.choose_punt(max_punts=max_punts, balance=balance)
        )
        solution = solve_horizon(self.horizon_problem(chosen, balance=balance, **kwargs))
        return solution, chosen

    def recommend_horizon(
        self,
        n: int = 8,
        punt: frozenset[Cat] | None = None,
        max_punts: int = 2,
        balance: float = 0.0,
        workers: int | None = None,
        **kwargs,
    ) -> tuple[pd.DataFrame, HorizonSolution, frozenset[Cat]]:
        """Candidates for my next pick priced with the waiting risk, plus the plan itself."""
        chosen = (
            punt if punt is not None else self.choose_punt(max_punts=max_punts, balance=balance)
        )
        problem = self.horizon_problem(chosen, balance=balance, **kwargs)
        solution = solve_horizon(problem)
        candidates = self.candidates(n, chosen, expected=True)
        if solution.first_pick and solution.first_pick not in candidates:
            candidates.append(solution.first_pick)
        table = horizon_pick_pool(problem, candidates, base=solution, workers=workers)
        if not table.empty:
            table.insert(1, "name", table["player"].map(self.projections.df["player"]))
        return table, solution, chosen
