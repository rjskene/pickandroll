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
    traded pick lands on the roster that used it; keepers are ordinary picks). The shared
    archive of a format (``data/leagues/_shared/<format>/``, #77) holds many leagues' drafts
    of one season, told apart by a ``league_id`` column: each league's draft is a draft of its
    own there, as each season is in the user's league's archive.
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

The shared archive pools the formats (#77): a categories league's fit takes the points
leagues' rosters too, scored the session's way, each at a lighter weight (``others``), and
vice versa. ``drafts`` is the sum of the weights fitted, the ``D`` the session blends the fit
toward the simulated league with (``CategoryCurve.blend``).
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
    #: The sum of the fitted drafts' weights (one each in the folder's own archive).
    drafts: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "seasons": self.seasons,
            "skipped": self.skipped,
            "check": {c: None if v is None else round(float(v), 3) for c, v in self.check.items()},
            "check_seasons": self.check_seasons,
            "drafts": round(float(self.drafts), 3),
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


def _draft_label(entry: Mapping[str, Any]) -> str:
    """A fitted or skipped draft as the source names it: its year, its league in a shared
    archive, and the format and weight of a draft pooled from another format's archive."""
    label = f"{entry['year']} {entry['league']}" if "league" in entry else str(entry["year"])
    if "format" in entry:
        label += f" ({entry['format']} x{entry['weight']:g})"
    return label


def _archive(folder: Path) -> pd.DataFrame | None:
    path = folder / PICKS
    if not path.exists():
        return None
    picks = pd.read_csv(path)
    needed = {"draft_year", "n_teams", "round", "overall", "player", "team"}
    if not needed <= set(picks.columns):
        raise ValueError(
            f"{folder.name}/{path.name} lacks columns {sorted(needed - set(picks.columns))}"
        )
    return picks


def fit_league_curve(
    folder: Path,
    scores: SeasonScores,
    cats: Sequence[Cat],
    num_teams: int,
    roster_size: int,
    season: int,
    aliases: Mapping[str, str] | None = None,
    others: Sequence[tuple[Path, float]] = (),
) -> LeagueCurveFit:
    """The curve from the archive in ``folder``, and from each of ``others`` (another format's
    archive) at its weight. ``scores(year)`` gives a season's projections and z (``season``'s
    are the session's own); the check's pool spread is ``season``'s. Raises ``ValueError``
    when no season can be fitted, naming why for each."""
    archives = [(folder, 1.0, _archive(folder))]
    archives += [(other, float(w), _archive(other)) for other, w in others if w > 0]
    if all(picks is None for _, _, picks in archives):
        raise ValueError(f"no drafted rosters: {PICKS} is not in {folder.name}/")
    totals: list[pd.DataFrame] = []
    weights: list[float] = []
    seasons: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for where, weight, picks in archives:
        if picks is None:
            continue
        fitted = _fit_archive(
            picks, scores, cats, num_teams, roster_size, aliases, where.name, weight
        )
        for frame, entry in fitted[0]:
            totals.append(frame)
            weights += [weight] * len(frame)
            seasons.append(entry)
        skipped += fitted[1]
    if not totals:
        why = "; ".join(f"{_draft_label(s)}: {s['reason']}" for s in skipped) or "no drafts"
        raise ValueError(f"no season to fit the curve on ({why})")
    years = ", ".join(_draft_label(s) for s in seasons)
    rosters = sum(s["rosters"] for s in seasons)
    scored = sum(s["scored"] for s in seasons)
    every = sum(s["picks"] for s in seasons)
    source = f"league rosters {years} ({rosters} rosters, {scored} of {every} picks scored)"
    pooled = len(archives) > 1
    curve = CategoryCurve.from_totals(
        pd.concat(totals), cats, source=source, weights=weights if pooled else None
    )
    check: dict[str, float | None] = {}
    check_seasons: list[str] = []
    standings = folder / STANDINGS
    own = scores(season)
    if standings.exists() and own is not None:
        spread = pool_spread(own[0], own[1], cats)
        check, check_seasons = standings_check(pd.read_csv(standings), spread, cats, num_teams)
    return LeagueCurveFit(
        curve=curve,
        seasons=seasons,
        skipped=skipped,
        check=check,
        check_seasons=check_seasons,
        drafts=sum(s.get("weight", 1.0) for s in seasons),
    )


def _fit_archive(
    picks: pd.DataFrame,
    scores: SeasonScores,
    cats: Sequence[Cat],
    num_teams: int,
    roster_size: int,
    aliases: Mapping[str, str] | None,
    name: str,
    weight: float,
) -> tuple[list[tuple[pd.DataFrame, dict[str, Any]]], list[dict[str, Any]]]:
    """One archive's drafts: each fitted draft's roster totals with its entry, and the skipped.
    A draft of another archive than the folder's own carries its archive's name and weight."""
    fitted: list[tuple[pd.DataFrame, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    by = ["draft_year", "league_id"] if "league_id" in picks.columns else ["draft_year"]
    for key, draft in picks.groupby(by, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        year = int(key[0])
        which: dict[str, Any] = {"year": year}
        if len(key) > 1:
            which["league"] = str(key[1])
        if weight != 1.0:
            which.update(format=name, weight=weight)
        label = ":".join(str(v) for v in (name, *key))
        teams, rounds = int(draft["n_teams"].iloc[0]), int(draft["round"].max())
        if teams != num_teams or rounds != roster_size:
            skipped.append(
                {
                    **which,
                    "reason": f"{teams} teams x {rounds} rounds, the session drafts "
                    f"{num_teams} x {roster_size}",
                }
            )
            continue
        scored = scores(year)
        if scored is None:
            missing = SEASON_PROJECTIONS.format(year=year)
            skipped.append({**which, "reason": f"no projection file ({missing})"})
            continue
        projections, z = scored
        rosters, unmatched = season_rosters(draft, projections, aliases)
        if len(rosters) < 2:
            skipped.append({**which, "reason": "fewer than two rosters scored"})
            continue
        frame = roster_totals(z, rosters, cats)
        frame.index = [f"{label}:{team}" for team in frame.index]
        entry = {
            **which,
            "rosters": len(rosters),
            "picks": len(draft),
            "scored": len(draft) - len(unmatched),
            "unmatched": unmatched,
        }
        fitted.append((frame, entry))
    return fitted, skipped
