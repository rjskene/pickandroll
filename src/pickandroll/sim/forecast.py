"""The forecasters (#172, PR D1): where a replay's projection comes from.

A **forecaster** is the projection source of a run: the figure each projected player's belief
starts from (``sim.belief``) and the draft's ranking. A run names one or several
(``replay --forecasters prior,espn,oracle:0.1``, :func:`parse`) and plays each in turn on the same
season. Four names:

- ``prior``: the prior season's per-game rates of the players with :data:`MIN_GAMES` played
  games in it (``readers.prior_rates``);
- ``espn``: ESPN's stored season projection for the replayed season, per game, for every player
  whose block has games (``readers.espn_rates``). ESPN updates that block through the season, so
  it may not be the preseason figure; :func:`freeze_of` measures how far it moved;
- ``marcel``: a weighted mean of up to three earlier seasons' lines, regressed toward the mean
  (:func:`marcel`);
- ``oracle:σ``: the replayed season's realized rates noised on the log scale at ``σ``, a labelled
  look-ahead whose error is known (:func:`oracle`), in one of two :data:`SHAPES`.

A **stand-in** is a forecaster named to stand for one of the two live sources (``replay --bbm-as``,
``--yahoo-as``; :data:`ROLES`). An arm's seat then believes by its ``system`` knob: ``bbm`` the
first's forecast, ``yahoo`` and ``blend`` the live rule on the two (:func:`system_rates`). An oracle
named as a stand-in draws from its role's own stream, so two oracle stand-ins have independent
errors and neither shares the run's draws; a real forecaster is the same forecast wherever it is
named.

Two diagnostics go to the payload and never to a seat: :func:`error_of`, the forecaster's error
against the replayed season, and :func:`freeze_of`, for ``espn``. Pure: lines and figures come
in; the readers bring them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median

from . import world
from .belief import consistent
from .engine import BLEND, STATS

Rates = Mapping[str, float]
Lines = Mapping[int, Mapping[date, Mapping[str, float]]]

#: The forecasters a run may name.
NAMES = ("prior", "espn", "marcel", "oracle")
#: The live sources a stand-in stands for, first and second: the system knob's ``bbm`` is the
#: first, ``yahoo`` the second over the first, ``blend`` their mix.
ROLES = ("bbm", "yahoo")
#: The live systems an arm may name (``progress.KNOB_VALUES``).
SYSTEMS = ("bbm", "yahoo", "blend")
#: The generator key of each role's oracle draws on the ``forecast`` stream: a role's stat draws
#: at ``2 · key`` and its player draw at ``2 · key + 1``. The run's oracle (key 0) draws its
#: stats on the ``error`` stream, the first replays' draws, and its player draw at 0.
ROLE_KEYS = {None: 0, "bbm": 1, "yahoo": 2}
#: How an oracle's error is drawn: ``stat``, one draw a player and stat (the first replays'
#: draws, bit for bit); ``minutes``, a share of it common to the player's counting stats.
SHAPES = ("stat", "minutes")
#: A forecaster built from lines (``prior``, ``oracle``) projects a player with at least this
#: many played games in the season it reads.
MIN_GAMES = 20
#: Marcel's weights by recency, most recent first; with two seasons the first two, not
#: renormalized. Named, not fitted.
MARCEL_WEIGHTS = (5.0, 4.0, 3.0)
#: Marcel's regression: this many games of the mean are added to every player's record.
MARCEL_REGRESS_GAMES = 100.0
#: Marcel's mean is over the players with this many games in the most recent season read, and
#: it projects a player with this many in at least one season read.
MARCEL_MIN_GAMES = 20
#: Marcel needs this many earlier seasons on file.
MARCEL_SEASONS = 2
#: The minutes shape's share of an oracle's variance common to a player's counting stats.
MINUTES_SHARE = 0.7
#: The error is measured over the projected players with this many played games.
ERROR_MIN_GAMES = 20
#: The freeze check reads the projected players who played this many games or fewer...
FREEZE_GAMES = 30
#: ...and is flagged when the median of their projected games is below this line: a preseason
#: projection cannot know who will miss the season. Set after a look at the logs; a flag on a
#: diagnostic, never a refusal.
FREEZE_LINE = 50.0


class CannotServe(ValueError):
    """A forecaster cannot serve the season (a log or a block it needs is not on file)."""


# --------------------------------------------------------------------------- what a run names
@dataclass(frozen=True)
class Forecaster:
    """A forecaster a run names: its name, an oracle's spread and, for an oracle named as a
    stand-in, its role (:data:`ROLES`)."""

    name: str
    spread: float | None = None
    role: str | None = None

    @property
    def label(self) -> str:
        """``prior``, ``espn``, ``marcel``, ``oracle:σ`` or a stand-in oracle's ``oracle:σ@role``:
        the key of the payload's figures."""
        base = self.name if self.spread is None else f"{self.name}:{self.spread:g}"
        return base if self.role is None else f"{base}@{self.role}"


def standin(f: Forecaster, role: str) -> Forecaster:
    """``f`` named to stand for the live source ``role``: an oracle takes the role, and with it
    a stream of its own; a real forecaster is the same forecast wherever it is named."""
    if role not in ROLES:
        raise ValueError(f"role {role!r}: one of {ROLES}")
    return Forecaster(f.name, f.spread, role if f.name == "oracle" else None)


@dataclass(frozen=True)
class Forecast:
    """A forecaster's projection: ``rates`` by player in ``engine.STATS`` names (through
    ``belief.consistent``, the prior season's as recorded) and one sentence on where it comes
    from."""

    label: str
    rates: Mapping[int, Rates]
    source: str


def parse_one(item: str) -> Forecaster:
    """One forecaster from its name: ``prior``, ``espn``, ``marcel`` or ``oracle:<spread>``, the
    spread a number above zero. Anything else is refused by name."""
    text = item.strip()
    name, sep, arg = text.partition(":")
    if name not in NAMES:
        raise ValueError(f"forecaster {text!r}: one of {', '.join(NAMES[:3])} or oracle:<spread>")
    if name != "oracle":
        if sep:
            raise ValueError(f"forecaster {text!r}: {name} takes no spread")
        return Forecaster(name)
    if not sep:
        raise ValueError(f"forecaster {text!r}: an oracle names its spread, oracle:<spread>")
    try:
        spread = float(arg)
    except ValueError:
        raise ValueError(f"forecaster {text!r}: the spread {arg!r} is not a number") from None
    if not math.isfinite(spread) or spread <= 0:
        raise ValueError(f"forecaster {text!r}: the spread is a number above zero")
    return Forecaster(name, spread)


def parse(text: str) -> list[Forecaster]:
    """The forecasters a run names, in order: ``prior,espn,oracle:0.1``. An unknown name, a
    name twice or a spread that is not a number above zero is refused by name."""
    out: list[Forecaster] = []
    for item in text.split(","):
        if not item.strip():
            raise ValueError(f"forecasters {text!r}: an empty name")
        f = parse_one(item)
        if any(g.label == f.label for g in out):
            raise ValueError(f"forecasters {text!r}: {f.label} is named twice")
        out.append(f)
    return out


# --------------------------------------------------------------------------- the four
def realized_rates(lines: Lines, min_games: int = 1) -> dict[int, dict[str, float]]:
    """Each player's per-game rates over the games he played, for those with ``min_games``."""
    out: dict[int, dict[str, float]] = {}
    for k, by_day in lines.items():
        n = len(by_day)
        if not n or n < min_games:
            continue
        totals: dict[str, float] = {}
        for ln in by_day.values():
            for stat, x in ln.items():
                totals[stat] = totals.get(stat, 0.0) + float(x)
        out[k] = {stat: v / n for stat, v in totals.items() if stat in STATS}
    return out


def prior(lines: Lines, min_games: int = MIN_GAMES) -> dict[int, dict[str, float]]:
    """The prior season's per-game rates (``lines`` are its), for the players with ``min_games``
    played games in it: a player new that season, or who missed most of the last, has none and
    arrives by the newcomer's rule. Not passed through ``consistent``: a recorded season's
    makes never pass its attempts, and the first replays' figures stay as they were (the tests'
    made-up lines can have more threes than rounded makes)."""
    return {k: v for k, v in realized_rates(lines).items() if len(lines[k]) >= min_games}


def espn(per_game: Mapping[str, Rates]) -> dict[int, dict[str, float]]:
    """ESPN's stored projection as rates by player id (``gamelogs.per_game`` of its season
    totals: the blocks without games are already left out), in ``engine.STATS`` names."""
    return {
        int(pid): consistent({s: float(v) for s, v in r.items() if s in STATS})
        for pid, r in per_game.items()
    }


def marcel(seasons: Sequence[Lines]) -> dict[int, dict[str, float]]:
    """Up to three earlier seasons' lines, most recent first, as one projection. Per player and
    stat, ``(Σ wᵢ · totalᵢ + R · mean) / (Σ wᵢ · gamesᵢ + R)`` over the seasons he played in, the
    weights :data:`MARCEL_WEIGHTS` by recency and ``R`` :data:`MARCEL_REGRESS_GAMES`; makes and
    attempts are stats of their own. ``mean`` is the mean per-game rate over the players with
    :data:`MARCEL_MIN_GAMES` games in the most recent season; a player is projected when he has
    that many in at least one season read. Fewer than :data:`MARCEL_SEASONS` seasons cannot serve
    the season."""
    if len(seasons) < MARCEL_SEASONS:
        raise CannotServe(
            f"marcel needs {MARCEL_SEASONS} earlier seasons on file, it has {len(seasons)}"
        )
    read = list(seasons)[: len(MARCEL_WEIGHTS)]
    sums: list[dict[int, tuple[int, dict[str, float]]]] = []
    for lines in read:
        season: dict[int, tuple[int, dict[str, float]]] = {}
        for k, by_day in lines.items():
            if not by_day:
                continue
            totals = dict.fromkeys(STATS, 0.0)
            for ln in by_day.values():
                for s in STATS:
                    totals[s] += float(ln.get(s, 0.0))
            season[k] = (len(by_day), totals)
        sums.append(season)
    regulars = [t for n, t in sums[0].values() if n >= MARCEL_MIN_GAMES]
    regular_games = [n for n, _ in sums[0].values() if n >= MARCEL_MIN_GAMES]
    if not regulars:
        raise CannotServe(f"marcel: no player has {MARCEL_MIN_GAMES} games in the latest season")
    mean = {
        s: sum(t[s] / n for t, n in zip(regulars, regular_games, strict=True)) / len(regulars)
        for s in STATS
    }
    players = sorted({k for season in sums for k in season})
    out: dict[int, dict[str, float]] = {}
    for k in players:
        rows = [(w, season[k]) for w, season in zip(MARCEL_WEIGHTS, sums) if k in season]
        if not any(n >= MARCEL_MIN_GAMES for _, (n, _) in rows):
            continue
        games = sum(w * n for w, (n, _) in rows) + MARCEL_REGRESS_GAMES
        out[k] = consistent(
            {
                s: (sum(w * t[s] for w, (_, t) in rows) + MARCEL_REGRESS_GAMES * mean[s]) / games
                for s in STATS
            }
        )
    return out


def oracle(
    lines: Lines,
    spread: float,
    seed: int,
    path: int,
    shape: str = "stat",
    min_games: int = MIN_GAMES,
    role: str | None = None,
) -> dict[int, dict[str, float]]:
    """The replayed season's realized rates noised on the log scale: a projection whose error is
    known, a labelled look-ahead. It projects only the players with ``min_games`` played games
    in the replayed season (a stated part of that look-ahead); the others arrive by the
    newcomer's rule. ``shape`` ``stat``: ``ε = σ · z_stat``, one draw a player and stat (the
    first replays' draws, bit for bit). ``minutes``: ``ε = σ · (√s · z_player + √(1 − s) ·
    z_stat)``, ``s`` :data:`MINUTES_SHARE`, ``z_stat`` the same draw and ``z_player`` one draw a
    player from the ``forecast`` stream, shared by every stat, makes and attempts included, so
    the shared part leaves his percentages alone. ``role``: an oracle named as a stand-in for that
    live source draws both from its own keys on the ``forecast`` stream (:data:`ROLE_KEYS`), so
    its errors are independent of the run's oracle and of the other role's."""
    if shape not in SHAPES:
        raise ValueError(f"shape {shape!r}: one of {SHAPES}")
    if role not in ROLE_KEYS:
        raise ValueError(f"role {role!r}: one of {ROLES}")
    truth = realized_rates(lines, min_games)
    keys = sorted(truth)
    stats = list(STATS)
    key = ROLE_KEYS[role]
    forecast = world.STREAMS["forecast"]
    if role is None:
        z = world.errors(seed, path, keys, stats, 0.0, {}, dict.fromkeys(stats, 1.0))
    else:
        z = {
            k: dict(
                zip(stats, world.rng(seed, path, i, 2 * key, forecast).standard_normal(len(stats)))
            )
            for i, k in enumerate(keys)
        }
    if shape == "stat" and role is None:
        eps = world.errors(seed, path, keys, stats, 0.0, {}, dict.fromkeys(stats, spread))
    elif shape == "stat":
        eps = {k: {s: spread * float(z[k][s]) for s in stats} for k in keys}
    else:
        own, common = math.sqrt(1.0 - MINUTES_SHARE), math.sqrt(MINUTES_SHARE)
        eps = {}
        for i, k in enumerate(keys):
            at = 0 if role is None else 2 * key + 1
            shared = world.rng(seed, path, i, at, forecast).standard_normal()
            eps[k] = {s: spread * (common * float(shared) + own * float(z[k][s])) for s in stats}
    return {k: consistent(v) for k, v in world.true_rates({k: truth[k] for k in keys}, eps).items()}


# --------------------------------------------------------------------------- the two sources
def share_of(system: str, blend: float | None) -> float | None:
    """The second source's share in an arm's belief: ``blend`` (the engine's default
    ``progress.BLEND`` when it is None) under the ``blend`` system, None under the others."""
    if system != "blend":
        return None
    return BLEND if blend is None else float(blend)


def system_label(system: str, blend: float | None, first: str, second: str) -> str:
    """The label of the belief an arm with ``system`` holds when the run's stand-ins are
    ``first`` (bbm) and ``second`` (yahoo): ``bbm`` is the first's own label."""
    if system not in SYSTEMS:
        raise ValueError(f"system {system!r}: one of {SYSTEMS}")
    if system == "bbm":
        return first
    if system == "yahoo":
        return f"yahoo({second} else {first})"
    return f"blend:{share_of(system, blend):g}({second} with {first})"


def system_rates(
    system: str,
    blend: float | None,
    first: Mapping[int, Rates],
    second: Mapping[int, Rates],
) -> dict[int, dict[str, float]]:
    """The live rule (``api.season_moves.system_rates``, restated): ``bbm`` the first source's
    rates; ``yahoo`` the second's line for every player it projects and the first's for the
    rest; ``blend``, for every player the second projects, ``share · second + (1 − share) ·
    first`` stat by stat (a stat one of them lacks counted 0; the second's alone where the first
    has no line), the first's for everyone else, ``share`` :func:`share_of`. A mix passes
    through ``consistent``. One difference from the live route: it values a blended player at
    the mix of the two systems' own per-game values, the simulator at the mixed rates."""
    if system not in SYSTEMS:
        raise ValueError(f"system {system!r}: one of {SYSTEMS}")
    if system == "bbm":
        # The first's forecast as it is: a real forecaster is the same forecast wherever it is
        # named.
        return {k: dict(v) for k, v in first.items()}
    if system == "yahoo":
        out = {**{k: dict(v) for k, v in first.items()}, **{k: dict(v) for k, v in second.items()}}
    else:
        w = share_of(system, blend)
        assert w is not None
        out = {k: dict(v) for k, v in first.items()}
        for k, y in second.items():
            b = first.get(k)
            if b is None:
                out[k] = dict(y)
                continue
            # The first's stats in its order, then any only the second has: an order that does
            # not move with the hash seed.
            out[k] = {
                s: (1 - w) * float(b.get(s, 0.0)) + w * float(y.get(s, 0.0))
                for s in dict.fromkeys([*b, *y])
            }
    return {k: consistent(v) for k, v in out.items()}


# --------------------------------------------------------------------------- the diagnostics
def error_of(rates: Mapping[int, Rates], lines: Lines, min_games: int = ERROR_MIN_GAMES) -> dict:
    """The forecaster's error against the replayed season (``lines``): over the projected
    players with ``min_games`` played games, per stat, the mean and the spread of
    ``log(realized rate / forecast rate)`` where both are above zero, with the count; how many
    players it projects and how many of them played ``min_games``; the median spread over the
    stats. Never shown to a seat."""
    realized = realized_rates(lines, min_games)
    played = [k for k in rates if k in realized]
    by_stat: dict[str, dict[str, float | int | None]] = {}
    for s in STATS:
        xs = [
            math.log(realized[k][s] / float(rates[k][s]))
            for k in played
            if realized[k].get(s, 0.0) > 0 and float(rates[k].get(s, 0.0)) > 0
        ]
        n = len(xs)
        mean = sum(xs) / n if n else None
        sd = (
            math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))
            if n > 1 and mean is not None
            else None
        )
        by_stat[s] = {"mean": mean, "spread": sd, "n": n}
    spreads = [float(v["spread"]) for v in by_stat.values() if v["spread"] is not None]
    return {
        "projected": len(rates),
        "played": len(played),
        "min_games": min_games,
        "by_stat": by_stat,
        "median_spread": median(spreads) if spreads else None,
    }


FREEZE_NOTE = (
    f"among the projected players who played {FREEZE_GAMES} games or fewer, the median of their "
    f"projected games; flagged below {FREEZE_LINE:g}: a preseason projection cannot know who "
    "will miss the season, so a low median means the block was updated in season. A flag on a "
    "diagnostic, never a refusal"
)


def freeze_of(projected_games: Mapping[int, float], actual_games: Mapping[int, int]) -> dict:
    """How far ESPN's stored block moved through the replayed season: among the projected
    players who played :data:`FREEZE_GAMES` games or fewer (``actual_games``, none counted as
    0), their count and the median of their projected games; how many projected players have
    projected games equal to the games they played; ``flagged`` when that median is below
    :data:`FREEZE_LINE`."""
    short = [k for k in projected_games if actual_games.get(k, 0) <= FREEZE_GAMES]
    med = median(float(projected_games[k]) for k in short) if short else None
    return {
        "projected": len(projected_games),
        "short": len(short),
        "median_projected_games": med,
        "equal": sum(
            1 for k, g in projected_games.items() if float(g) == float(actual_games.get(k, 0))
        ),
        "flagged": med is not None and med < FREEZE_LINE,
        "note": FREEZE_NOTE,
    }


__all__ = [
    "ERROR_MIN_GAMES",
    "FREEZE_GAMES",
    "FREEZE_LINE",
    "MARCEL_MIN_GAMES",
    "MARCEL_REGRESS_GAMES",
    "MARCEL_SEASONS",
    "MARCEL_WEIGHTS",
    "MINUTES_SHARE",
    "MIN_GAMES",
    "NAMES",
    "ROLES",
    "ROLE_KEYS",
    "SHAPES",
    "SYSTEMS",
    "CannotServe",
    "Forecast",
    "Forecaster",
    "error_of",
    "espn",
    "freeze_of",
    "marcel",
    "oracle",
    "parse",
    "parse_one",
    "prior",
    "realized_rates",
    "share_of",
    "standin",
    "system_label",
    "system_rates",
]
