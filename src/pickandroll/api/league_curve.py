"""The category curve from the league's own drafted rosters (``curve: league``, #65).

The simulated curve (:meth:`CategoryCurve.simulated`) fits mu and sigma to teams that bots
drafted on the projections. This one fits them to the teams the league's managers drafted:
every roster of every archived season that has both a draft and a projection file, each
roster's total the sum of its players' z on that season's projections
(:meth:`CategoryCurve.from_rosters`). The archive is the folder beside the league's survival
table (``data/yahoo_history`` for the user's league):

``picks.csv``
    Every archived draft, one row per pick: ``draft_year``, ``n_teams``, ``round``,
    ``overall``, ``player`` (Yahoo's name) and ``team`` (the team that made the pick, so a
    traded pick lands on the roster that used it; keepers are ordinary picks).
``projections_<year>.csv`` (optional)
    That season's preseason projections, in the session's projection format. The session's
    own projections score the season they are for, so the season being drafted needs no file.
``category_totals.csv`` (optional)
    The standings' per-season team spread: the check. A team's season total in a counting
    category, per game normalised (``<cat>_sd_pg``), over the per-player spread of the pool
    the session's z are measured on is the standings' sigma in z units. Percentages have no
    such conversion without the attempts, and a standing is the managed roster's season, not
    the drafted roster's, so the check runs wide of the fit; it is reported, never fitted.

A season is used only when its draft has the session's team count and roster size: a total
over twelve rounds is not on the scale of one over thirteen.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..optim.objective import CategoryCurve, roster_totals
from ..projections.schema import PCT_CATS, Cat
from ..sources.matching import match_players

PICKS = "picks.csv"
STANDINGS = "category_totals.csv"
SEASON_PROJECTIONS = "projections_{year}.csv"
#: A season's projections and their z, or ``None`` when the season has no projection file.
SeasonScores = Callable[[int], tuple[pd.DataFrame, pd.DataFrame] | None]


@dataclass(frozen=True)
class LeagueCurveFit:
    curve: CategoryCurve
    #: The seasons fitted: year, rosters, picks, and the picks whose player the season's
    #: projections score (the rest are left off their roster's total).
    seasons: list[dict[str, Any]]
    #: Seasons in the archive that were not fitted, and why.
    skipped: list[dict[str, Any]] = field(default_factory=list)
    #: The standings' sigma in z units per category, the mean over ``check_seasons``; ``None``
    #: for a category the standings cannot put in z units.
    check: dict[str, float | None] = field(default_factory=dict)
    check_seasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seasons": self.seasons,
            "skipped": self.skipped,
            "check": {c: None if v is None else round(float(v), 3) for c, v in self.check.items()},
            "check_seasons": self.check_seasons,
        }


def draft_year(as_of: datetime) -> int:
    """The draft a projection dated ``as_of`` is for: a season's drafts run from the summer to
    its opening night in October, so a date from July on is that year's draft, and one before
    July is the draft of the season under way."""
    return as_of.year if as_of.month >= 7 else as_of.year - 1


def season_rosters(
    picks: pd.DataFrame, projections: pd.DataFrame, aliases: Mapping[str, str] | None = None
) -> tuple[dict[str, list[str]], list[str]]:
    """One season's rosters by the team that made each pick, as projection ids, and the names
    the projections do not have."""
    names = pd.DataFrame(
        {"name": picks["player"].astype(str).to_numpy()},
        index=[f"pick {int(k)}" for k in picks["overall"]],
    )
    match = match_players(names, projections, aliases=aliases)
    rosters: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for key, team, name in zip(names.index, picks["team"].astype(str), names["name"], strict=True):
        pid = match.mapping.get(key)
        if pid is None:
            unmatched.append(name)
            continue
        rosters.setdefault(team, []).append(pid)
    return rosters, unmatched


def pool_spread(
    projections: pd.DataFrame, z: pd.DataFrame, cats: Sequence[Cat]
) -> dict[Cat, float]:
    """Per-player spread of each counting category in the pool ``z`` is measured on. A z is
    ``(raw - mean) / sd`` over that pool, so the slope of the raw value on the z is the sd."""
    active = projections.index[projections["games"] > 0].intersection(z.index)
    spread: dict[Cat, float] = {}
    for cat in cats:
        if cat in PCT_CATS or cat.value not in projections.columns:
            continue
        x = z.loc[active, cat.value].astype(float).to_numpy()
        y = projections.loc[active, cat.value].astype(float).to_numpy()
        if len(x) < 2 or float(np.var(x)) == 0.0:
            continue
        spread[cat] = abs(float(np.cov(x, y, bias=True)[0, 1] / np.var(x)))
    return spread


def standings_check(
    standings: pd.DataFrame, spread: Mapping[Cat, float], cats: Sequence[Cat], num_teams: int
) -> tuple[dict[str, float | None], list[str]]:
    """The standings' team spread in z units per category, averaged over the seasons with the
    session's team count; ``None`` where the standings have no per-game spread or the pool no
    spread (the percentages)."""
    rows = standings[standings["teams"] == num_teams]
    check: dict[str, float | None] = {}
    for cat in cats:
        column = f"{cat.value}_sd_pg"
        if rows.empty or cat not in spread or column not in rows.columns:
            check[cat.value] = None
            continue
        check[cat.value] = float((rows[column].astype(float) / spread[cat]).mean())
    return check, [str(s) for s in rows["season"]]


def fit_league_curve(
    folder: Path,
    scores: SeasonScores,
    cats: Sequence[Cat],
    num_teams: int,
    roster_size: int,
    season: int,
    aliases: Mapping[str, str] | None = None,
) -> LeagueCurveFit:
    """The curve from the archive in ``folder``. ``scores(year)`` gives a season's projections
    and z (``season``'s are the session's own); the check's pool spread is ``season``'s.
    Raises ``ValueError`` when no season can be fitted, naming why for each."""
    path = folder / PICKS
    if not path.exists():
        raise ValueError(f"no drafted rosters: {path.name} is not in {folder.name}/")
    picks = pd.read_csv(path)
    needed = {"draft_year", "n_teams", "round", "overall", "player", "team"}
    if not needed <= set(picks.columns):
        raise ValueError(f"{path.name} lacks columns {sorted(needed - set(picks.columns))}")
    totals: list[pd.DataFrame] = []
    seasons: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for year, draft in picks.groupby("draft_year", sort=True):
        year = int(year)
        teams, rounds = int(draft["n_teams"].iloc[0]), int(draft["round"].max())
        if teams != num_teams or rounds != roster_size:
            skipped.append(
                {
                    "year": year,
                    "reason": f"{teams} teams x {rounds} rounds, the session drafts "
                    f"{num_teams} x {roster_size}",
                }
            )
            continue
        scored = scores(year)
        if scored is None:
            name = SEASON_PROJECTIONS.format(year=year)
            skipped.append({"year": year, "reason": f"no projection file ({name})"})
            continue
        projections, z = scored
        rosters, unmatched = season_rosters(draft, projections, aliases)
        if len(rosters) < 2:
            skipped.append({"year": year, "reason": "fewer than two rosters scored"})
            continue
        frame = roster_totals(z, rosters, cats)
        frame.index = [f"{year}:{team}" for team in frame.index]
        totals.append(frame)
        seasons.append(
            {
                "year": year,
                "rosters": len(rosters),
                "picks": len(draft),
                "scored": len(draft) - len(unmatched),
                "unmatched": unmatched,
            }
        )
    if not totals:
        why = "; ".join(f"{s['year']}: {s['reason']}" for s in skipped) or "no drafts"
        raise ValueError(f"no season to fit the curve on ({why})")
    years = ", ".join(str(s["year"]) for s in seasons)
    rosters = sum(s["rosters"] for s in seasons)
    scored = sum(s["scored"] for s in seasons)
    every = sum(s["picks"] for s in seasons)
    source = f"league rosters {years} ({rosters} rosters, {scored} of {every} picks scored)"
    curve = CategoryCurve.from_totals(pd.concat(totals), cats, source=source)
    check: dict[str, float | None] = {}
    check_seasons: list[str] = []
    standings = folder / STANDINGS
    own = scores(season)
    if standings.exists() and own is not None:
        spread = pool_spread(own[0], own[1], cats)
        check, check_seasons = standings_check(pd.read_csv(standings), spread, cats, num_teams)
    return LeagueCurveFit(
        curve=curve, seasons=seasons, skipped=skipped, check=check, check_seasons=check_seasons
    )
