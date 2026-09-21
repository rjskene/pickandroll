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

from ..optim.roster import RosterProblem, RosterSolution, pick_pool, solve_roster
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

    def __post_init__(self) -> None:
        if not 1 <= self.my_position <= self.settings.num_teams:
            raise ValueError("my_position must be within the number of teams")
        pool = self.pool_size or self.settings.total_picks
        self.z = zscores(self.projections.df, cats=self.settings.cats, pool_size=pool)
        self.positions = self.projections.positions()

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
        return RosterProblem(
            z=self.z,
            positions=self.positions,
            slots=self.settings.slots,
            cats=self.settings.cats,
            punt=punt,
            max_punts=max_punts,
            balance=balance,
            weights=weights,
            locks=frozenset(self.my_roster),
            blocks=self.taken - frozenset(self.my_roster),
            raw=self.projections.df,
            availability=availability,
            **extra,
        )

    def best_roster(self, **kwargs) -> RosterSolution:
        return solve_roster(self.problem(**kwargs))

    def candidates(self, n: int = 8, punt: frozenset[Cat] | None = None) -> list[str]:
        """Top available players by total z (punt-adjusted when a punt is given)."""
        cols = [c.value for c in self.settings.cats if not punt or c not in punt]
        totals = self.z.loc[self.available, cols].sum(axis=1)
        return totals.nlargest(n).index.tolist()

    def recommend(self, n: int = 8, punt: frozenset[Cat] | None = None, **kwargs) -> pd.DataFrame:
        """Price the top ``n`` available candidates by forcing each onto the best roster."""
        problem = self.problem(punt=punt, **kwargs)
        table = pick_pool(problem, self.candidates(n, punt))
        if not table.empty:
            table.insert(1, "name", table["player"].map(self.projections.df["player"]))
        return table
