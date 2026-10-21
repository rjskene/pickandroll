"""The breakout flag (#95, docs/ADD_DROP.md): signs that an available player may be a long-term
asset, ahead of the projections, which lag a role change by days.

Four signals, each a score from 0 to 1 with its evidence:

* **Adds surge** (:func:`adds_surge`): the day's change in percent rostered against his own
  level (2% to 7% is louder than a star gaining five points), and Yahoo-wide adds today against
  his own median over the earlier days kept, or, until enough days are kept, his rank by adds
  on Yahoo's buzz index. The louder part counts.
* **Minutes trend** (:func:`minutes_trend`): minutes per game over the last 7 and 14 days
  against his rest-of-season projection, the smaller gain of the windows with enough games; a
  usage gain counts at half weight.
* **Value gap** (:func:`value_gap`): ranked inside the top 120 on the league's own scoring and
  rostered in under half of Yahoo's leagues.
* **Opportunity** (:func:`opportunity`): teammates at his position out for weeks, weighted by
  their projected minutes; nothing for a player out himself.

The level comes from the sum of the four (:data:`LEVELS`); opportunity counts toward it only
beside another signal (:data:`OPPORTUNITY_NEEDS_ANOTHER`). Every constant is a first guess, to be
tuned once two weeks of buzz-index history are kept. The flag never adds anyone.

Each signal's evidence comes as two texts: ``reason``, with every number, for the dashboard, and
``public``, for the digest posted on a public issue, which carries no number derived from
Basketball Monster (its value rank, its projected or recent minutes and usage); a signal built on
those is named there and nothing more.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from ..projections.names import normalize_name
from .state import OUT_CODES

# --------------------------------------------------------------------------- constants
#: Adds surge: the day's gain in percent rostered over yesterday's level that scores 1 (2% to 7%
#: is 5 over 2); yesterday's level is floored at this many percent, so 0% to 1% is not infinite.
JUMP_FULL = 2.5
JUMP_FLOOR = 1.0
#: Adds today against his median over at least this many earlier days; this many times his median
#: scores 1, and a median under :data:`ADDS_FLOOR` counts as that.
HISTORY_DAYS = 3
ADDS_FULL = 8.0
ADDS_FLOOR = 25.0
#: Without that history, his rank by adds on the buzz index: the first scores 1, the last of its
#: rows :data:`BUZZ_LAST`.
BUZZ_ROWS = 50
BUZZ_LAST = 0.3
#: Minutes trend: this many minutes a game over the projection scores 1, this many points of
#: usage the same at :data:`USAGE_WEIGHT`; a window counts with at least its floor of games.
MINUTES_FULL = 8.0
USAGE_FULL = 5.0
USAGE_WEIGHT = 0.5
MIN_GAMES: Mapping[int, int] = {7: 2, 14: 4}
#: Value gap: ranked inside this on the league's scoring and rostered in under this percent of
#: Yahoo's leagues; the score falls with the rank over :data:`VALUE_RANK_SCALE`.
VALUE_RANK = 120
VALUE_PCT = 50.0
VALUE_RANK_SCALE = 240.0
#: Opportunity: a teammate out at least this many days from today; this many projected minutes a
#: game out at his position scores 1, and a teammate without a projection counts this many.
OUT_DAYS = 14
OPPORTUNITY_FULL = 30.0
UNKNOWN_MPG = 15.0
#: Opportunity counts toward the flag only beside another signal: alone it explains minutes no
#: other sign says he is getting (on 2026-10-21 it made 14 of the watches in each of two leagues
#: by itself). Its own score and evidence stay in the flag either way.
OPPORTUNITY_NEEDS_ANOTHER = True
#: The levels by the sum of the four scores, highest first.
LEVELS: tuple[tuple[str, float], ...] = (("must-add", 2.2), ("add", 1.5), ("watch", 0.8))
SIGNALS = ("surge", "minutes", "value", "opportunity")
SIGNAL_NAMES: Mapping[str, str] = {
    "surge": "adds surge",
    "minutes": "minutes up",
    "value": "value gap",
    "opportunity": "opportunity",
}
#: Yahoo's and ESPN's positions in the three groups an injury opens minutes in.
GROUPS: Mapping[str, str] = {
    "PG": "G",
    "SG": "G",
    "G": "G",
    "SF": "F",
    "PF": "F",
    "F": "F",
    "C": "C",
}


# --------------------------------------------------------------------------- inputs
@dataclass(frozen=True)
class Pickup:
    """An available player as the flag reads him: his Yahoo-wide ownership and adds today."""

    yahoo_id: int
    name: str
    nba_team: str | None
    positions: tuple[str, ...]
    pct_rostered: float | None = None
    pct_rostered_change: float | None = None
    adds: int | None = None
    #: Yahoo's injury or availability code (``O``, ``INJ``, ``GTD``, ...).
    status: str | None = None


@dataclass(frozen=True)
class Window:
    """What he did over the last ``days`` days: games, total minutes and usage."""

    days: int
    games: float
    minutes: float
    usage: float | None = None


@dataclass(frozen=True)
class Projection:
    """His rest-of-season minutes a game and usage."""

    mpg: float | None
    usage: float | None = None


@dataclass(frozen=True)
class Injury:
    """A player on the injury report: his NBA team, position groups, status and return date."""

    name: str
    nba_team: str
    groups: frozenset[str]
    status: str
    returns: date | None
    #: His projected minutes a game, when the projection has him.
    mpg: float | None = None


@dataclass(frozen=True)
class Inputs:
    today: date
    #: Yahoo-wide adds on earlier days, by Yahoo id, oldest first.
    history: Mapping[int, Sequence[int]] = field(default_factory=dict)
    #: Today's rank by adds on the buzz index, by Yahoo id (1 for the most added).
    buzz_rank: Mapping[int, int] = field(default_factory=dict)
    recent: Mapping[int, Sequence[Window]] = field(default_factory=dict)
    projected: Mapping[int, Projection] = field(default_factory=dict)
    #: His rank on the league's scoring among every projected player (1 for the best).
    value_rank: Mapping[int, int] = field(default_factory=dict)
    injuries: Sequence[Injury] = ()


@dataclass(frozen=True)
class Signal:
    score: float
    #: The evidence with every number (None when the signal says nothing).
    reason: str | None = None
    #: The evidence as the public digest may print it.
    public: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)


NOTHING = Signal(0.0)


@dataclass(frozen=True)
class Flag:
    level: str | None
    score: float
    signals: Mapping[str, Signal]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": round(self.score, 3),
            "signals": {
                k: {"score": round(s.score, 3), "reason": s.reason, "facts": dict(s.facts)}
                for k, s in self.signals.items()
            },
        }


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def _num(x: float) -> str:
    """A percent or a count as Yahoo prints it: no trailing zeros."""
    return f"{x:g}"


def _day(d: date) -> str:
    return f"{d:%b} {d.day}"


def position_groups(positions: Iterable[str]) -> frozenset[str]:
    """The guard, forward and centre groups of a list of positions (``G-F`` reads as both)."""
    out = set()
    for p in positions:
        for part in str(p).replace("/", "-").split("-"):
            group = GROUPS.get(part.strip().upper())
            if group:
                out.add(group)
    return frozenset(out)


# --------------------------------------------------------------------------- the signals
def adds_surge(p: Pickup, inputs: Inputs) -> Signal:
    """The louder of his ownership jump against his own level and his adds against his own
    baseline (his median over the earlier days kept, else his buzz-index rank)."""
    texts = []
    facts: dict[str, Any] = {}
    jump = 0.0
    change, pct = p.pct_rostered_change, p.pct_rostered
    if change is not None and change > 0 and pct is not None:
        before = pct - change
        jump = _clip(change / max(before, JUMP_FLOOR) / JUMP_FULL)
        facts |= {"pct_rostered": pct, "change": change}
        texts.append(f"+{_num(change)} % rostered today ({_num(before)}% to {_num(pct)}%)")
    adds = 0.0
    history = list(inputs.history.get(p.yahoo_id, ()))
    if p.adds is not None and len(history) >= HISTORY_DAYS:
        base = max(float(median(history)), ADDS_FLOOR)
        ratio = p.adds / base
        adds = _clip(math.log(ratio) / math.log(ADDS_FULL)) if ratio > 0 else 0.0
        facts |= {"adds": p.adds, "median": base, "days": len(history)}
        if adds > 0:
            texts.append(f"{p.adds:,} adds today, {ratio:.1f}x his {len(history)}-day median")
    else:
        rank = inputs.buzz_rank.get(p.yahoo_id)
        if rank is not None and 1 <= rank <= BUZZ_ROWS:
            adds = 1.0 - (1.0 - BUZZ_LAST) * (rank - 1) / (BUZZ_ROWS - 1)
            facts |= {"adds": p.adds, "buzz_rank": rank}
            count = f"{p.adds:,} adds today, " if p.adds is not None else ""
            texts.append(f"{count}#{rank} by adds on Yahoo's buzz index")
    score = max(jump, adds)
    if score <= 0:
        return Signal(0.0, facts=facts)
    text = "; ".join(texts)
    return Signal(score, text, text, facts)


def minutes_trend(p: Pickup, inputs: Inputs) -> Signal:
    """Minutes a game over the windows with enough games against his projection: the smaller
    gain, over :data:`MINUTES_FULL`; a usage gain likewise at :data:`USAGE_WEIGHT`."""
    proj = inputs.projected.get(p.yahoo_id)
    windows = [
        w
        for w in inputs.recent.get(p.yahoo_id, ())
        if w.games >= MIN_GAMES.get(w.days, 1) and w.games > 0
    ]
    if proj is None or proj.mpg is None or not windows:
        return NOTHING
    gains = {w.days: w.minutes / w.games - proj.mpg for w in windows}
    minutes = _clip(min(gains.values()) / MINUTES_FULL)
    usage = {
        w.days: w.usage - proj.usage
        for w in windows
        if w.usage is not None and proj.usage is not None
    }
    usage_part = _clip(min(usage.values()) / USAGE_FULL) if usage else 0.0
    score = max(minutes, USAGE_WEIGHT * usage_part)
    facts = {
        "projected_mpg": round(proj.mpg, 1),
        "windows": {
            w.days: {
                "games": w.games,
                "mpg": round(w.minutes / w.games, 1),
                "usage": None if w.usage is None else round(w.usage, 1),
            }
            for w in windows
        },
    }
    if score <= 0:
        return Signal(0.0, facts=facts)
    parts = [
        f"{w.minutes / w.games:.1f} min over the last {w.days} days ({_num(w.games)} games)"
        for w in sorted(windows, key=lambda w: w.days)
    ]
    reason = f"{', '.join(parts)} against {proj.mpg:.1f} projected"
    if usage and usage_part > 0:
        reason += f"; usage +{min(usage.values()):.1f}"
    return Signal(score, reason, SIGNAL_NAMES["minutes"], facts)


def value_gap(p: Pickup, inputs: Inputs) -> Signal:
    """Inside the top :data:`VALUE_RANK` on the league's scoring and rostered in under
    :data:`VALUE_PCT` percent of Yahoo's leagues."""
    rank, pct = inputs.value_rank.get(p.yahoo_id), p.pct_rostered
    if rank is None or pct is None or rank > VALUE_RANK or pct >= VALUE_PCT:
        return NOTHING
    score = _clip((1.0 - rank / VALUE_RANK_SCALE) * (1.0 - pct / VALUE_PCT))
    reason = f"ranked {rank} on the league's scoring, rostered in {_num(pct)}% of Yahoo leagues"
    return Signal(score, reason, SIGNAL_NAMES["value"], {"rank": rank, "pct_rostered": pct})


def opportunity(p: Pickup, inputs: Inputs) -> Signal:
    """Teammates at his position out at least :data:`OUT_DAYS` days, by their projected minutes
    over :data:`OPPORTUNITY_FULL`; nothing while he is out himself (Yahoo's status or ESPN's
    report), since the minutes are not his to take."""
    mine = position_groups(p.positions)
    if not p.nba_team or not mine or (p.status or "").upper() in OUT_CODES:
        return NOTHING
    me = normalize_name(p.name)
    team = p.nba_team.upper()
    if any(
        normalize_name(i.name) == me
        and i.nba_team.upper() == team
        and i.status.strip().lower() == "out"
        for i in inputs.injuries
    ):
        return NOTHING
    until = inputs.today + timedelta(days=OUT_DAYS)
    out = [
        i
        for i in inputs.injuries
        if i.nba_team.upper() == team
        and normalize_name(i.name) != me
        and i.status.strip().lower() == "out"
        and i.returns is not None
        and i.returns >= until
        and i.groups & mine
    ]
    if not out:
        return NOTHING
    minutes = sum(UNKNOWN_MPG if i.mpg is None else i.mpg for i in out)
    score = _clip(minutes / OPPORTUNITY_FULL)

    def who(i: Injury) -> str:
        return f"{i.name} ({'/'.join(sorted(i.groups))}) out, est. return {_day(i.returns)}"  # type: ignore[arg-type]

    reason = "; ".join(
        who(i) + ("" if i.mpg is None else f", {i.mpg:.0f} projected min") for i in out
    )
    public = "; ".join(who(i) for i in out)
    facts = {
        "out": [
            {"name": i.name, "returns": i.returns.isoformat() if i.returns else None} for i in out
        ]
    }
    return Signal(score, reason, public, facts)


def level_of(score: float) -> str | None:
    for name, floor in LEVELS:
        if score >= floor - 1e-9:
            return name
    return None


def flag(p: Pickup, inputs: Inputs) -> Flag:
    """The four signals and their sum; with :data:`OPPORTUNITY_NEEDS_ANOTHER`, a sum of 0 when
    opportunity is the only one that spoke."""
    signals = {
        "surge": adds_surge(p, inputs),
        "minutes": minutes_trend(p, inputs),
        "value": value_gap(p, inputs),
        "opportunity": opportunity(p, inputs),
    }
    others = sum(s.score for k, s in signals.items() if k != "opportunity")
    alone = OPPORTUNITY_NEEDS_ANOTHER and others <= 0
    score = others + (0.0 if alone else signals["opportunity"].score)
    return Flag(level_of(score), score, signals)


def flags(pool: Iterable[Pickup], inputs: Inputs) -> dict[int, Flag]:
    """Every player's flag that any signal speaks for (opportunity alone included, scored 0, so
    the dashboard can show its evidence)."""
    out = {}
    for p in pool:
        f = flag(p, inputs)
        if any(s.score > 0 for s in f.signals.values()):
            out[p.yahoo_id] = f
    return out


# --------------------------------------------------------------------------- the digest
def public_line(p: Pickup, f: Flag) -> str:
    """One flagged player as the public digest prints him: the level, his name and the signals
    that spoke, with the public evidence only."""
    reasons = []
    for key in SIGNALS:
        s = f.signals.get(key)
        if s is None or s.score <= 0:
            continue
        name = SIGNAL_NAMES[key]
        reasons.append(name if not s.public or s.public == name else f"{name} ({s.public})")
    where = ", ".join(x for x in (p.nba_team, "/".join(p.positions)) if x)
    return (
        f"- **{f.level}** {p.name}" + (f" ({where})" if where else "") + f": {'; '.join(reasons)}"
    )


def digest_markdown(
    day: date,
    leagues: Sequence[tuple[str, Sequence[tuple[Pickup, Flag]]]],
    notes: Sequence[str] = (),
) -> str:
    """The day's digest across leagues, for a public issue: leagues by id, no team names, no
    number derived from Basketball Monster; ``notes`` on missing or old inputs. The add and
    must-add players come with their evidence, the watch level as one line of names (the
    route's JSON carries every player's evidence)."""
    lines = [
        f"## Breakout flags, {day:%a} {_day(day)}",
        "",
        (
            "Levels from four signals (adds surge, minutes trend, value gap, opportunity) over "
            "each league's available players; the thresholds are first guesses until two weeks "
            "of buzz-index history are kept. Nothing is added automatically."
        ),
    ]
    if notes:
        lines += ["", "Inputs: " + "; ".join(notes) + "."]
    for league, flagged in leagues:
        lines += ["", f"### League {league}"]
        loud = [(p, f) for p, f in flagged if f.level in ("must-add", "add")]
        watch = [p for p, f in flagged if f.level == "watch"]
        if not loud and not watch:
            lines.append("No flagged player among the available ones.")
            continue
        lines += [public_line(p, f) for p, f in loud]
        if watch:
            names = ", ".join(f"{p.name} ({p.nba_team})" if p.nba_team else p.name for p in watch)
            lines.append(f"- watch ({len(watch)}): {names}")
    return "\n".join(lines) + "\n"
