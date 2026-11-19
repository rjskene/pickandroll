"""The seats no arm holds (#172, PR 2b): what each opponent does on a day.

The ladder from the design note. **Static** makes no move. **Market** is the heuristic: each day
with probability ``rate`` (adds per team-day: the arm's ``opponents.rate``, else the setup's,
which a replay leaves at zero) it adds
the pool's best by the market's view and drops its weakest by the same view, within the caps (in
a waiver league the best it may add and the weakest it may drop, :class:`Market`; in a FAAB
league it bids by an assumed form, ``policy.rival_bid``, or on the price book, ``bids.book_bid``,
PR Fd). Its view is the draft day's all season, or the season's that morning (``view``), and it
may pick among its best few (``among``), PR Fd.
**Mirror** runs the surrogate on the shared beliefs with the arm's knobs and fields (the arm
whole: at the defaults nothing changes; in a FAAB league it bids by the live rule on them). **Seat** is the equal room's: a named arm in another
seat, the same tiers the arm under test runs, with its fields. Each strategy is pure given the world's
draws (``run.World`` passes the day's generator), so two arms of a comparison see the same
opponents while their states agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

import numpy as np

from . import policy
from .engine import mv, wk
from .shapes import BOOK
from .state import Setup, SimState

KINDS = ("static", "market", "mirror", "seat")
#: A market rival's view (#172, PR Fd): ``draft``, the setup's ``market`` ranking all season (the
#: default, today's); ``season``, each player's per-game value on the run's forecaster's beliefs
#: that morning (``weekly.per_game_values``, what the runner lands forced drops on).
DRAFT, SEASON = "draft", "season"
VIEWS = (DRAFT, SEASON)
#: The statuses a seat that has heard them never starts (``policy.starters_of``): a rival that
#: follows the season picks no player heard so.
OUT = wk.OUT_ALL | wk.OUT_THIS_WEEK


class Strategy(Protocol):
    """What a seat does on a day: a decision from the problem's inputs."""

    kind: str

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision: ...


@dataclass(frozen=True)
class Static:
    kind: str = "static"

    def decide(self, *args: Any, **kwargs: Any) -> policy.Decision:
        return policy.NONE


@dataclass(frozen=True)
class Market:
    """The market heuristic. ``rate`` is the chance of a move on a day; the view, under ``view``
    ``draft`` (the default), is the setup's ``market`` ranking (the shared projection's per-game
    value, percent rostered breaking ties) all season.

    Under ``view`` ``season`` (#172, PR Fd) the view on a day is each player's per-game value on
    the run's forecaster's beliefs that morning (the beliefs a market rival is handed: it
    believes the run's forecaster whatever the arm believes), and it picks no player whose
    status that morning is one a seat never starts (:data:`OUT`); its drop is its weakest by the
    same view. A table of draft positions plays no part after the draft. With ``among`` K above 1
    it takes one of the best K players it may add that are worth more than its weakest it may
    drop, each as likely, by one number drawn from its day's generator after the rate's draw and
    before the bid's noise (drawn whenever one is left, even one alone); none left, no move.
    With ``among`` 1 (the default) it takes the best and draws nothing more.

    In a waiver league (#172, PR Fa) its pick is the best player it may add, not one it already
    claims and not its own drop still waiting, and its drop the weakest it may drop, not one an
    open claim of its takes: the executor would refuse either (``ALREADY_CLAIMED``, ``READD``,
    ``DROP_CLAIMED``), and the rival would idle while its claim waits. Without waivers it has no
    claim and nobody waits, so its pick is the pool's best and its weakest, as before.

    In a FAAB league (PR Fb) its decision carries what its bid is made on
    (``policy.rival_bid``, an assumed form, not a fit): its move's gain on its view, and, when the
    pick is a claim, a noise drawn after the pick from the path's draw for its team and day (a
    fresh draw of its own, so nothing else it draws moves). Under continuous waivers (PR Fc) every
    pick is a claim, so it draws its noise on every pick; with the rule not named it draws only
    on a pick on waivers, as before. A bid on the book (PR Fd, ``setup.rival_bids`` ``book``)
    takes the draw itself, on [0, 1), where the assumed form takes ``policy.market_noise`` of it:
    one draw a claim either way."""

    rate: float
    view: str = DRAFT
    among: int = 1
    kind: str = "market"

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        if g.random() >= self.rate:
            return policy.NONE
        limit = setup.max_weekly_adds
        if limit is not None and state.adds_used.get(team, 0) >= limit:
            return policy.NONE
        season = self.view == SEASON
        view = self._view(setup, beliefs) if season else setup.market
        mine = state.claims.get(team, ())
        claimed = {c.move.add for c in mine}
        promised = {c.move.drop for c in mine if c.move.drop is not None}
        own = {k for k, w in state.waivers.items() if w.by == team}
        pool = [
            k
            for k in state.pool
            if k in view
            and k not in claimed
            and k not in own
            and not (season and status.get(k) in OUT)
        ]
        roster = [k for k in state.active(team) if k in view and k not in promised]
        if not pool or not roster:
            return policy.NONE
        drop = min(roster, key=lambda k: (view[k], k))
        if self.among == 1:
            add = max(pool, key=lambda k: (view[k], -k))
            if view[add] <= view[drop]:
                return policy.NONE
        else:
            best = sorted(pool, key=lambda k: (-view[k], k))[: self.among]
            above = [k for k in best if view[k] > view[drop]]
            if not above:
                return policy.NONE
            add = above[min(len(above) - 1, int(g.random() * len(above)))]
        basis = None
        if setup.bidding:
            claim = setup.continuous or add in state.waivers
            noise: tuple[float, ...] = ()
            if claim:
                book = setup.rival_bids == BOOK
                noise = (float(g.random()),) if book else (policy.market_noise(g),)
            basis = policy.Basis(policy.MARKET, (float(view[add] - view[drop]),), noise=noise)
        return policy.Decision((mv.Move(add, drop),), (), (), 0, "market", basis)

    @staticmethod
    def _view(setup: Setup, beliefs: Mapping[int, Mapping[str, float]]) -> dict[int, float]:
        """The season's view: each believed player's per-game value that morning, on the league's
        categories or its points table (as the runner values the day)."""
        points = dict(setup.points) if setup.scoring == "points" and setup.points else None
        return _SEASON_VIEW.of(beliefs, setup.cats, points)


class _LastView:
    """The season's view of the last beliefs asked for, kept. The runner hands every market rival
    one mapping a morning (``World.beliefs_on``: built afresh each day, never changed after), so
    the view is computed once a morning, not once a rival's move: the same figures, a fraction
    of the time. The mapping itself is held, so its identity cannot be reused while it is the
    key. A caller that changes a mapping in place between two asks would be handed the old view;
    none does."""

    def __init__(self) -> None:
        self._key: tuple[Any, ...] | None = None
        self._view: dict[int, float] = {}

    def of(
        self,
        beliefs: Mapping[int, Mapping[str, float]],
        cats: tuple[str, ...] | list[str],
        points: Mapping[str, float] | None,
    ) -> dict[int, float]:
        table = None if points is None else tuple(sorted(points.items()))
        key = self._key
        if key is None or key[0] is not beliefs or key[1:] != (tuple(cats), table):
            self._view = wk.per_game_values(beliefs, cats, points)
            self._key = (beliefs, tuple(cats), table)
        return self._view


_SEASON_VIEW = _LastView()


@dataclass(frozen=True)
class Mirror:
    """The surrogate on the shared beliefs, with the knobs and fields given (the arm's), but for
    the stash threshold, which a rival keeps at None (``policy.rival_knobs``, PR G): the knob
    is the arm's own seat's. It is dropped when the rival is made, so two arms that differ only
    in it face one rival and share its decisions."""

    knobs: Mapping[str, Any]
    fields: policy.Fields = policy.DEFAULT_FIELDS
    kind: str = "mirror"

    def __post_init__(self) -> None:
        object.__setattr__(self, "knobs", policy.rival_knobs(self.knobs))

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        built = policy.problem_of(
            setup, state, team, self.knobs, beliefs, status, returns, self.fields.weeks_ahead
        )
        if built is None:
            return policy.NONE
        return policy.decide(built, "surrogate", fields=self.fields)


@dataclass(frozen=True)
class Seat:
    """An arm in a seat: its tier, knobs, what it executes and its fields, and the forecaster it
    believes by (#172, PR D1): a label the world holds, None for the run's. Static, market and
    mirror seats hold the run's. The label is part of the seat, so of the runner's decision
    cache's key: two seats on different forecasters share no decision."""

    name: str
    tier: str
    knobs: Mapping[str, Any]
    executes: str = policy.QUEUE_SET
    with_plan: bool = True
    fields: policy.Fields = policy.DEFAULT_FIELDS
    forecaster: str | None = None
    kind: str = "seat"

    def decide(
        self,
        setup: Setup,
        state: SimState,
        team: int,
        beliefs: Mapping[int, Mapping[str, float]],
        status: Mapping[int, str | None],
        returns: Mapping[int, date],
        g: np.random.Generator,
    ) -> policy.Decision:
        if self.tier == "static":
            return policy.NONE
        built = policy.problem_of(
            setup, state, team, self.knobs, beliefs, status, returns, self.fields.weeks_ahead
        )
        if built is None:
            return policy.NONE
        return policy.decide(built, self.tier, self.executes, self.with_plan, self.fields)


#: The keys of an arm's ``opponents`` block the simulator reads (:func:`of`); any other is
#: refused by name (:func:`check_spec`). ``view`` and ``among`` are a market rival's (PR Fd).
SPEC_KEYS = ("kind", "rate", "view", "among")
MARKET_KEYS = ("view", "among")


def check_spec(spec: Mapping[str, Any]) -> None:
    """Refuse an ``opponents`` block's key the simulator does not read, a market rival's key on
    another kind, a ``view`` out of :data:`VIEWS` and an ``among`` that is not a whole number of
    1 or more, each by name."""
    unknown = [k for k in spec if k not in SPEC_KEYS]
    if unknown:
        raise ValueError(
            f"opponents key {unknown[0]!r} is not one the simulator reads: one of {SPEC_KEYS}"
        )
    kind = str(spec.get("kind", "static"))
    named = [k for k in MARKET_KEYS if k in spec]
    if named and kind != "market":
        raise ValueError(f"opponents key {named[0]!r} is a market rival's: kind {kind} reads none")
    view = spec.get("view", DRAFT)
    if view not in VIEWS:
        raise ValueError(f"opponents view {view!r}: one of {', '.join(VIEWS)}")
    among = spec.get("among", 1)
    if not isinstance(among, int) or isinstance(among, bool) or among < 1:
        raise ValueError(f"opponents among {among!r}: a whole number, 1 or more")


def of(
    spec: Mapping[str, Any],
    knobs: Mapping[str, Any],
    market_rate: float,
    fields: policy.Fields = policy.DEFAULT_FIELDS,
) -> Strategy:
    """An opponent from an arm's ``opponents`` block: ``{"kind": "static"}``,
    ``{"kind": "market", "rate": 0.1}`` (the setup's ``market_rate`` when none is given; with
    ``view`` and ``among`` when named, PR Fd) or ``{"kind": "mirror"}`` (the arm's own knobs and
    fields)."""
    kind = str(spec.get("kind", "static"))
    if kind == "static":
        return Static()
    if kind == "market":
        rate = spec.get("rate")
        view = spec.get("view")
        among = spec.get("among")
        return Market(
            float(market_rate if rate is None else rate),
            DRAFT if view is None else str(view),
            1 if among is None else int(among),
        )
    if kind == "mirror":
        return Mirror(dict(knobs), fields)
    raise ValueError(f"unknown opponent kind {kind!r}: one of {KINDS[:3]}")
