"""The trade evaluator (#96, docs/ADD_DROP.md): a proposed trade between my roster and one other
team's, valued for both sides before and after as expected categories won.

The horizons and the odds are the move optimiser's (:mod:`season.moves`): the rest of this week
against each team's named opponent, from the week so far, and the weeks after it against the
field, every other team on its own projected roster. Both rosters change at once, so the whole
league is held here: the counterparty may be my opponent this week, and each side's field holds
the other side's roster as traded. The traded players change hands on the trade's effective
date, as a waiver claim does: each plays for his old team until that day and for his new one
from it, so a date past this week's end changes nothing this week.

A side left with more active players than spots (a two-for-one without an open spot) first moves
players to open held slots, then drops the players it misses least; the drops are named and the
trade as entered is not valid in Yahoo. A side that frees a spot reports it; on my side the best
single free-agent add for that spot is valued beside the trade, never inside it. The margin is
how much of its projection what I receive can lose (or must gain) for the trade to stay neutral
on my side. The reading is "no worse on our model", never "they will accept"; nothing here
proposes a trade or acts in Yahoo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from . import moves as mv
from . import weekly as wk
from .state import Player

Member = tuple[int, Player]
#: The scale on the received players' production that the margin's search covers.
MARGIN_MAX = 3.0
#: The margin's search stops when the scale is known to this width.
MARGIN_TOL = 0.005


@dataclass(frozen=True)
class TeamRoster:
    #: The players in active spots (starting slots and the bench).
    active: tuple[Member, ...]
    #: The players in held slots, each with its slot (``IL``, ``IL+``, ``NA``).
    held: tuple[tuple[int, Player, str], ...] = ()


@dataclass(frozen=True)
class Span:
    """One week of a horizon, for every team at once."""

    days: tuple[date, ...]
    this_week: bool
    #: This week's pairs, each team's named opponent; None for a later week (the field).
    pairs: Mapping[int, int] | None = None
    #: The week so far by team (this week only; a team whose matchup was not read has none).
    so_far: Mapping[int, Mapping[str, float]] = field(default_factory=dict)
    #: A weekly export's games for the week, by player (``project_week``'s ``games``).
    games: Mapping[int, int] | None = None


@dataclass(frozen=True)
class League:
    teams: Mapping[int, TeamRoster]
    #: Active roster spots: the league's slots less the held ones.
    spots: int
    #: The league's held slots by kind.
    held_slots: Mapping[str, int]
    rates: Mapping[int, wk.Rates]
    schedule: Mapping[date, frozenset[str]]
    slots: tuple[str, ...]
    value: Mapping[int, float]
    cats: tuple[str, ...]
    points: Mapping[str, float] | None
    no_games: frozenset[int]
    #: The horizons by key (``week``, ``three``).
    horizons: Mapping[str, tuple[Span, ...]]
    held_accepts: Mapping[str, frozenset[str]] = field(default_factory=lambda: mv.HELD_ACCEPTS)
    #: The per-game value of any line (:func:`weekly.line_value`), so a received player's line
    #: scaled by the margin's search starts as that line would; None keeps his value.
    value_of: Callable[[wk.Rates], float] | None = None


@dataclass(frozen=True)
class Trade:
    mine: int
    theirs: int
    #: My players who go to them.
    give: tuple[int, ...]
    #: Their players who come to me.
    get: tuple[int, ...]
    effective: date


@dataclass(frozen=True)
class Change:
    """A team's roster from a day on: the players who join it, the players who leave it, and a
    scale on the joiners' production (the margin's search)."""

    joins: Mapping[int, date] = field(default_factory=dict)
    leaves: Mapping[int, date] = field(default_factory=dict)
    scale: float = 1.0

    def key(self) -> tuple[frozenset[tuple[int, date]], frozenset[tuple[int, date]], float]:
        return frozenset(self.joins.items()), frozenset(self.leaves.items()), self.scale


Won = dict[str, float]


# --------------------------------------------------------------------------- the league's value
class Evaluator:
    """Each team's expected categories won over a horizon with some rosters changed. A team's
    week is projected once per roster it is asked for: the unchanged ones once per week, and
    once for every evaluator ``seed`` starts (the API keeps one per snapshot)."""

    def __init__(self, league: League, seed: Evaluator | None = None) -> None:
        self.league = league
        self.players: dict[int, Player] = {}
        for t in league.teams.values():
            self.players |= {k: p for k, p in t.active}
            self.players |= {k: p for k, p, _ in t.held}
        #: The players on some roster (a free agent valued for a freed spot joins ``players``).
        self.rostered = frozenset(self.players)
        self._weeks: dict[
            tuple[str, int, int, object], tuple[wk.TeamWeek, dict[str, wk.Final]]
        ] = {}
        if seed is not None:
            self._weeks |= {k: v for k, v in seed._weeks.items() if k[3] is None}

    def project_all(self) -> None:
        """Every team's unchanged week of every horizon (a seed's work)."""
        for key, spans in self.league.horizons.items():
            for i in range(len(spans)):
                for team in self.league.teams:
                    self.week(key, i, team)

    def week(
        self, key: str, i: int, team: int, change: Change | None = None
    ) -> tuple[wk.TeamWeek, dict[str, wk.Final]]:
        """Team ``team``'s projection for week ``i`` of horizon ``key``, and its finals."""
        memo = (key, i, team, change.key() if change else None)
        if memo not in self._weeks:
            lg = self.league
            span = lg.horizons[key][i]
            t = lg.teams[team]
            members = [*((k, p) for k, p, _ in t.held), *t.active]
            rates: Mapping[int, wk.Rates] = lg.rates
            value: Mapping[int, float] = lg.value
            if change is not None:
                members += [(k, self.players[k]) for k in change.joins]
                if change.scale != 1.0:
                    scaled = {
                        k: {s: v * change.scale for s, v in lg.rates[k].items()}
                        for k in change.joins
                        if k in lg.rates
                    }
                    rates = {**lg.rates, **scaled}
                    if lg.value_of is not None:
                        value = {**lg.value, **{k: lg.value_of(r) for k, r in scaled.items()}}
            tw = wk.project_week(
                members,
                rates,
                span.days,
                lg.schedule,
                lg.slots,
                value,
                span.this_week,
                games=span.games,
                points=lg.points,
                no_games=lg.no_games,
                available_from=change.joins if change else None,
                gone_from=change.leaves if change else None,
            )
            self._weeks[memo] = (tw, wk.finals(tw, span.so_far.get(team, {}), lg.cats))
        return self._weeks[memo]

    def opponents(self, span: Span, team: int) -> list[int]:
        if span.pairs is None:
            return [t for t in self.league.teams if t != team]
        other = span.pairs.get(team)
        return [other] if other is not None and other in self.league.teams else []

    def won(self, key: str, team: int, changes: Mapping[int, Change] | None = None) -> Won:
        """Team ``team``'s expected categories won over horizon ``key``, by category: each week's
        odds against its opponents, averaged over them, summed over the weeks."""
        changes = changes or {}
        out = {c: 0.0 for c in self.league.cats}
        for i, span in enumerate(self.league.horizons[key]):
            opps = self.opponents(span, team)
            if not opps:
                continue
            _, mine = self.week(key, i, team, changes.get(team))
            for o in opps:
                _, theirs = self.week(key, i, o, changes.get(o))
                for odds in wk.odds_of(mine, theirs, self.league.cats):
                    out[odds.cat] += odds.p_win / len(opps)
        return out

    def total(self, key: str, team: int, changes: Mapping[int, Change] | None = None) -> float:
        return sum(self.won(key, team, changes).values())

    def games(
        self, key: str, team: int, player: int, change: Change | None = None
    ) -> wk.PlayerWeek:
        """A player's games and starts for ``team`` over horizon ``key``."""
        games = started = 0
        for i in range(len(self.league.horizons[key])):
            tw, _ = self.week(key, i, team, change)
            pw = tw.players.get(player)
            if pw is not None:
                games, started = games + pw.games, started + pw.started
        return wk.PlayerWeek(games, started)


# --------------------------------------------------------------------------- the rosters
@dataclass(frozen=True)
class RosterAfter:
    """A side's roster once the trade is processed."""

    spots: int
    #: Active players after the trade and the held-slot moves, before any drop.
    active: int
    #: Players placed in open held slots (a received player or one of the side's own).
    held_moves: tuple[tuple[int, str], ...]
    #: The players the side must drop to fit, least missed first (chosen here, not entered).
    drops: tuple[int, ...]
    #: Active spots left free.
    open: int

    @property
    def valid(self) -> bool:
        """Whether the trade fits this roster as entered (no drop needed)."""
        return not self.drops


def _place(
    players: Iterable[Member], open_: dict[str, int], accepts: Mapping[str, frozenset[str]]
) -> list[tuple[int, str]]:
    """The players of ``players`` that go to an open held slot, most restrictive slot first."""
    out = []
    for key, player in players:
        for slot, ok in accepts.items():
            if open_.get(slot, 0) > 0 and player.status in ok:
                open_[slot] -= 1
                out.append((key, slot))
                break
    return out


def fit(league: League, team: int, out: Iterable[int], into: Sequence[Member]) -> RosterAfter:
    """Team ``team``'s roster with ``out`` gone and ``into`` come, drops not chosen yet: the
    received players who go to a held slot (one freed by the trade or open), then the side's
    own active players who could, while the roster is over."""
    lg = league
    t = lg.teams[team]
    gone = set(out)
    used: dict[str, int] = {}
    for k, _, slot in t.held:
        if k not in gone:
            used[slot] = used.get(slot, 0) + 1
    open_ = {s: n - used.get(s, 0) for s, n in lg.held_slots.items()}
    moves = _place(into, open_, lg.held_accepts)
    placed = {k for k, _ in moves}
    staying = [(k, p) for k, p in t.active if k not in gone]
    active = len(staying) + sum(1 for k, _ in into if k not in placed)
    over = active - lg.spots
    if over > 0:
        own = _place(staying, open_, lg.held_accepts)[:over]
        moves += own
        active -= len(own)
    return RosterAfter(lg.spots, active, tuple(moves), (), max(0, lg.spots - active))


def changes_of(trade: Trade, drops: Mapping[int, Sequence[int]] | None = None) -> dict[int, Change]:
    """Both sides' roster changes for the trade, each side's drops leaving on its date."""
    drops = drops or {}
    day = trade.effective
    mine = Change(
        {k: day for k in trade.get},
        {k: day for k in (*trade.give, *drops.get(trade.mine, ()))},
    )
    theirs = Change(
        {k: day for k in trade.give},
        {k: day for k in (*trade.get, *drops.get(trade.theirs, ()))},
    )
    return {trade.mine: mine, trade.theirs: theirs}


def best_drops(
    ev: Evaluator, trade: Trade, team: int, need: int, key: str, keep: Iterable[int]
) -> tuple[int, ...]:
    """The ``need`` players ``team`` misses least over horizon ``key`` with the trade made, one
    at a time: its own active players who stay and are not in ``keep`` (held-slot moves)."""
    gone = set(trade.give if team == trade.mine else trade.get) | set(keep)
    pool = [k for k, _ in ev.league.teams[team].active if k not in gone]
    chosen: list[int] = []
    for _ in range(min(need, len(pool))):
        best = max(
            (k for k in pool if k not in chosen),
            key=lambda k: (ev.total(key, team, changes_of(trade, {team: [*chosen, k]})), -k),
        )
        chosen.append(best)
    return tuple(chosen)


# --------------------------------------------------------------------------- the report
@dataclass(frozen=True)
class Side:
    team: int
    before: Mapping[str, Won]
    after: Mapping[str, Won]
    roster: RosterAfter

    def change(self, key: str) -> float:
        return sum(self.after[key].values()) - sum(self.before[key].values())


@dataclass(frozen=True)
class Moved:
    """A traded player's games and starts by horizon: on his old team as if no trade, and with
    the trade on his old team (until the effective date) and his new one (from it)."""

    player: int
    old: int
    new: int
    before: Mapping[str, wk.PlayerWeek]
    on_old: Mapping[str, wk.PlayerWeek]
    on_new: Mapping[str, wk.PlayerWeek]


@dataclass(frozen=True)
class Margin:
    """The scale on what I receive that leaves my change over the horizon at zero: ``neutral``
    when the search brackets it, else which end it falls past."""

    key: str
    neutral: float | None
    #: ``crosses``, ``wins_at_zero`` (no worse even if what I receive produces nothing) or
    #: ``loses_at_max`` (worse even at :data:`MARGIN_MAX` times its projection).
    reading: str
    #: My change with what I receive at its projection.
    change: float


@dataclass(frozen=True)
class Fill:
    """The best single free-agent add for a spot the trade frees on my side, valued beside the
    trade: its gain over my roster as traded."""

    add: int
    effective: date
    gain: Mapping[str, float]


@dataclass(frozen=True)
class Report:
    trade: Trade
    mine: Side
    theirs: Side
    moved: tuple[Moved, ...]
    margin: Margin | None
    fill: Fill | None
    #: The horizon that orders the drops and the fill, and that the margin is taken on.
    key: str


def lead_key(league: League) -> str:
    """The horizon the drops, the fill and the margin use: three weeks when it has weeks."""
    three = league.horizons.get("three") or ()
    return "three" if any(s.days for s in three) else "week"


def evaluate(
    league: League,
    trade: Trade,
    pool: Sequence[tuple[Member, date]] = (),
    limits: Sequence[mv.AddLimit] = (),
    ev: Evaluator | None = None,
) -> Report:
    """Both sides before and after ``trade``. ``pool`` holds the free agents for a spot the trade
    frees on my side, each with the day his move can count; ``limits`` the weekly add limits."""
    ev = ev or Evaluator(league)
    lead = lead_key(league)
    give = [(k, ev.players[k]) for k in trade.give]
    get = [(k, ev.players[k]) for k in trade.get]
    rosters = {
        trade.mine: fit(league, trade.mine, trade.give, get),
        trade.theirs: fit(league, trade.theirs, trade.get, give),
    }
    drops: dict[int, tuple[int, ...]] = {}
    for team, r in rosters.items():
        over = r.active - r.spots
        if over > 0:
            held = [k for k, _ in r.held_moves]
            drops[team] = best_drops(ev, trade, team, over, lead, held)
            rosters[team] = RosterAfter(r.spots, r.active, r.held_moves, drops[team], 0)
    changes = changes_of(trade, drops)
    sides = {
        team: Side(
            team,
            {key: ev.won(key, team) for key in league.horizons},
            {key: ev.won(key, team, changes) for key in league.horizons},
            rosters[team],
        )
        for team in (trade.mine, trade.theirs)
    }
    moved = tuple(
        Moved(
            k,
            old,
            new,
            {key: ev.games(key, old, k) for key in league.horizons},
            {key: ev.games(key, old, k, changes[old]) for key in league.horizons},
            {key: ev.games(key, new, k, changes[new]) for key in league.horizons},
        )
        for ks, old, new in (
            (trade.give, trade.mine, trade.theirs),
            (trade.get, trade.theirs, trade.mine),
        )
        for k in ks
    )
    margin = neutral_margin(ev, trade, changes, sides[trade.mine], lead) if trade.get else None
    fill = None
    if rosters[trade.mine].open > 0 and pool:
        fill = best_fill(ev, trade, changes, pool, limits, lead)
    return Report(trade, sides[trade.mine], sides[trade.theirs], moved, margin, fill, lead)


def neutral_margin(
    ev: Evaluator, trade: Trade, changes: Mapping[int, Change], mine: Side, key: str
) -> Margin:
    """The scale on the received players' production (every stat, makes and attempts together)
    that leaves my change over horizon ``key`` at zero, by bisection over [0, MARGIN_MAX]: my
    change rises with what I receive (turnovers aside)."""
    base = sum(mine.before[key].values())

    def change_at(scale: float) -> float:
        c = changes[trade.mine]
        scaled = {**changes, trade.mine: Change(c.joins, c.leaves, scale)}
        return ev.total(key, trade.mine, scaled) - base

    at_one = mine.change(key)
    if change_at(0.0) >= 0:
        return Margin(key, None, "wins_at_zero", at_one)
    if change_at(MARGIN_MAX) < 0:
        return Margin(key, None, "loses_at_max", at_one)
    lo, hi = 0.0, MARGIN_MAX
    while hi - lo > MARGIN_TOL:
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if change_at(mid) >= 0 else (mid, hi)
    return Margin(key, round((lo + hi) / 2, 3), "crosses", at_one)


def best_fill(
    ev: Evaluator,
    trade: Trade,
    changes: Mapping[int, Change],
    pool: Sequence[tuple[Member, date]],
    limits: Sequence[mv.AddLimit],
    key: str,
) -> Fill | None:
    """The free agent who adds most over horizon ``key`` in the spot the trade frees on my side,
    from the later of the trade's date and his own; a week with no adds left takes none."""
    me = trade.mine
    base = {k: ev.total(k, me, changes) for k in ev.league.horizons}
    best: tuple[float, Fill] | None = None
    for (cand, player), day in pool:
        if cand in ev.rostered:
            continue
        when = max(day, trade.effective)
        lim = next((x for x in limits if x.start <= when <= x.end), None)
        if lim is not None and lim.adds is not None and lim.adds <= 0:
            continue
        ev.players.setdefault(cand, player)
        c = changes[me]
        added = {**changes, me: Change({**c.joins, cand: when}, c.leaves, c.scale)}
        gain = {k: ev.total(k, me, added) - base[k] for k in ev.league.horizons}
        if best is None or gain[key] > best[0]:
            best = (gain[key], Fill(cand, when, gain))
    return best[1] if best is not None and best[0] > 0 else None
