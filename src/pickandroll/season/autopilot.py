"""The moves executor's queue (#171, docs/AUTOPILOT.md sections 2, 3 and 5): the day's recommended
moves of each armed league as entries, each with its claim's bid and its place in the day's caps,
or the reason it is not queued; the noise floor a move must clear and the typical gain the bid
scales by. Pure: the API reads the decision log, the keep rule, the scorecard and the league's
pages, and keeps the queue.

The queue takes each league's three weeks' set (the ruling on #171, 2026-10-23: season first), as
the day's last moves solve logged it (#125), and judges each move on the three weeks after (#143)
with the rest of the season beside it (#144). Nothing here solves: an entry is the decision log's
move, read.

A move is left out, in this order, when:

1. the league is the private one, or its moves executor is off;
2. its drop is protected (the keep rule, #124: read, never re-solved);
3. it costs the season (#144; the guard never recommends one, the queue checks anyway);
4. its add is a player the league dropped within the waiver days, or one the set drops;
5. it is below the noise floor (:class:`Floor`);
6. the week of its clear date has no add left, the claims placed counted;
7. the day's cap is reached.

The rest are queued by their gain on the judging horizon, highest first. Every claim's bid is
:func:`bid_of`'s. A second build of a day keeps the entries struck or executed by id, leaves
their moves out of the new build, and gives any entry new to the queue its full veto window
(:func:`merge`).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

#: The set the queue takes, and the horizon it is judged on (#143): the three weeks after.
QUEUE_SET = "three"
JUDGED = "three"
SEASON = "season"
#: The scored moves the scorecard's spread needs before it is a floor; the moves the fortnight's
#: typical gain needs, over how many days.
SCORED_MIN = 20
TYPICAL_MIN = 10
TYPICAL_DAYS = 14
#: The veto window: an entry executes no sooner than this after it is queued, and no sooner than
#: the day's execute time (09:00 Pacific unless the user set another).
WINDOW = timedelta(minutes=60)
EXECUTE_TIME = "09:00"
EXECUTE_TZ = ZoneInfo("America/Los_Angeles")
#: The bid's factor for a breakout flag (``season.flags.LEVELS``): doubled for one, tripled for a
#: strong one; a player only watched is a routine stream.
FLAG_FACTOR: Mapping[str, int] = {"add": 2, "must-add": 3}
FREE_AGENT = "FA"

PRIVATE = "the private league is never touched"
OFF = "the moves executor is off in this league"
PROTECTED = "the drop is protected"
SEASON_COSTLY = "season-costly"
READD = "the add is a player this queue drops today or dropped within the waiver days"
BELOW_FLOOR = "below the noise floor"
NO_ADDS = "no adds left this week"
OVER_CAP = "over the day's cap"

#: An execution's outcome, from the extension's page check; ``won`` and ``lost`` resolve a claim
#: the morning after, from the league's transactions.
OUTCOMES = ("would_claim", "claimed", "added", "skipped", "failed", "gone")
EXECUTED = frozenset({"would_claim", "claimed", "added"})
PLACED = frozenset({"claimed", "added"})
RESOLUTIONS = ("won", "lost")


def entry_id(day: date, league: str, add: int, drop: int | None) -> str:
    """An entry's id: its day, league, add and drop, so a rebuild that finds the same move again
    finds its entry."""
    return f"{day.isoformat()}:{league}:{add}:{drop or 0}"


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


# --------------------------------------------------------------------------- the floor
@dataclass(frozen=True)
class Floor:
    """The noise floor (the ruling's point 2): the plan floor of the knob file against a move's
    gain on its judging horizon, always; once :data:`SCORED_MIN` moves are scored, also the
    scorecard's spread (the standard deviation of realized less projected value on each move's
    judging horizon) against the move's value there, in the scorer's units. The scored floor
    never opens the gate below the plan floor: a move clears both."""

    plan: float
    scored: float | None
    moves: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan,
            "scored": self.scored,
            "moves": self.moves,
            "needs": SCORED_MIN,
            "applies": "plan and scored" if self.scored is not None else "plan",
        }

    def below(self, gain: float | None, value: float | None) -> str | None:
        """Which floor the move is below (``plan``, ``scored``), None when it clears them."""
        if gain is None or gain < self.plan:
            return "plan"
        if self.scored is not None and (value is None or value < self.scored):
            return "scored"
        return None


def noise_floor(differences: Sequence[float], plan: float) -> Floor:
    """The floor from the scored moves' realized less projected values."""
    if len(differences) < SCORED_MIN:
        return Floor(plan, None, len(differences))
    return Floor(plan, round(statistics.stdev(differences), 4), len(differences))


def typical_gain(gains: Sequence[float], plan: float) -> tuple[float, str]:
    """The fortnight's typical recommended gain the bid scales by: the median gain on the judging
    horizon of the armed leagues' recommended moves over :data:`TYPICAL_DAYS` days, per scoring;
    the plan floor until :data:`TYPICAL_MIN` such moves exist. With its source."""
    if len(gains) < TYPICAL_MIN:
        return plan, f"the plan floor until {TYPICAL_MIN} moves"
    return round(statistics.median(gains), 4), "the fortnight's median"


# --------------------------------------------------------------------------- the bid
@dataclass(frozen=True)
class Bid:
    amount: int
    reason: str
    #: The multiple of the typical gain, the breakout factor, the sizing knob.
    base: int
    factor: int
    sizing: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": self.amount,
            "reason": self.reason,
            "base": self.base,
            "factor": self.factor,
            "sizing": self.sizing,
        }


def bid_of(
    gain: float,
    typical: tuple[float, str],
    budget: float | None,
    flag: str | None,
    sizing: float | None,
    availability: str | None,
) -> Bid:
    """A claim's bid (section 5, the ruling's point 3): ``max(1, round(gain / typical))`` dollars,
    doubled for a breakout flag and tripled for a strong one, times the FAAB sizing knob (1.0
    while unhooked), clamped to the budget left and nothing else. A free agent is added for $0."""
    size = 1.0 if sizing is None else float(sizing)
    if availability == FREE_AGENT:
        return Bid(0, "$0: a free agent is added at once", 0, 1, size)
    value, source = typical
    base = max(1, _half_up(gain / value)) if value > 0 else 1
    factor = FLAG_FACTOR.get(flag or "", 1)
    amount = _half_up(base * factor * size)
    left = None if budget is None else max(0, math.floor(budget))
    clamped = left is not None and amount > left
    if left is not None:
        amount = min(amount, left)
    if base == 1 and factor == 1 and size == 1.0:
        why = "a routine stream"
    else:
        why = f"gain {base}x the typical ({source})"
        if factor > 1:
            why += f", x{factor} for a {'strong ' if factor == 3 else ''}breakout flag"
        if size != 1.0:
            why += f", x{size:g} FAAB sizing"
    if clamped:
        why += f", clamped to the ${left} left"
    return Bid(amount, f"${amount}: {why}", base, factor, size)


# --------------------------------------------------------------------------- the entries
@dataclass(frozen=True)
class LeagueDay:
    """What the queue reads of one armed league for the day, all of it read, none of it solved."""

    league: str
    scoring: str
    #: The day's last moves entry of the decision log (#125).
    entry: Mapping[str, Any]
    mode: str
    private: bool
    #: My players the keep rule protects, with why (#124).
    protected: Mapping[int, str]
    #: The available players' ``FA`` or ``W`` and the day a claim clears.
    availability: Mapping[int, tuple[str, date | None]]
    #: The breakout flag's level by player.
    flags: Mapping[int, str]
    #: The players this league's team dropped within the waiver days.
    dropped: frozenset[int]
    budget: float | None
    cap: int
    #: The adds each week allows still, from the league's own page and transactions, the claims
    #: placed and not yet processed already taken out; None for no limit.
    adds_left: Mapping[tuple[date, date], int | None]
    #: The day's entries a rebuild keeps (:func:`kept`), by id: their moves are left out of the
    #: build, and those that hold a place (:func:`holds_place`) count toward the cap (``done``).
    kept: frozenset[str] = frozenset()
    done: int = 0


def three_set(entry: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return next((s for s in entry.get("sets") or () if s.get("key") == QUEUE_SET), None)


def _week_of(adds: Mapping[tuple[date, date], int | None], day: date) -> tuple[date, date] | None:
    return next((w for w in adds if w[0] <= day <= w[1]), None)


def _horizon(move: Mapping[str, Any], key: str) -> float | None:
    h = ((move.get("value") or {}).get("horizons") or {}).get(key) or {}
    return h.get("value")


def queue_of(
    lg: LeagueDay, day: date, floor: Floor, typical: tuple[float, str], sizing: float | None
) -> list[dict[str, Any]]:
    """The league's entries of the day: every move of its three weeks' set, queued or with the
    reason it is not, the queued ones ranked by gain on the judging horizon."""
    s = three_set(lg.entry)
    if s is None:
        return []
    moves = sorted(
        s.get("moves") or [],
        key=lambda m: (-((m.get("gain") or {}).get(JUDGED) or 0.0), m["add"]),
    )
    drops = {m["drop"] for m in moves if m.get("drop") is not None}
    left = dict(lg.adds_left)
    queued = 0
    out = []
    for m in moves:
        add, drop = int(m["add"]), m.get("drop")
        if entry_id(day, lg.league, add, drop) in lg.kept:
            continue
        gain = (m.get("gain") or {}).get(JUDGED)
        value = _horizon(m, JUDGED)
        kind, clears = lg.availability.get(add, (None, None))
        clear = date.fromisoformat(m["from"]) if m.get("from") else clears
        week = _week_of(left, clear) if clear is not None else None
        below = floor.below(gain, value)
        reason = None
        if lg.private:
            reason = PRIVATE
        elif lg.mode == "off":
            reason = OFF
        elif drop is not None and drop in lg.protected:
            reason = PROTECTED
        elif m.get("season_costly"):
            reason = SEASON_COSTLY
        elif add in lg.dropped or add in drops:
            reason = READD
        elif below is not None:
            reason = BELOW_FLOOR
        elif week is not None and left[week] is not None and left[week] <= 0:
            reason = NO_ADDS
        elif lg.done + queued >= lg.cap:
            reason = OVER_CAP
        if reason is None:
            queued += 1
            if week is not None and left[week] is not None:
                left[week] -= 1
        bid = bid_of(gain or 0.0, typical, lg.budget, lg.flags.get(add), sizing, kind)
        out.append(
            {
                "id": entry_id(day, lg.league, add, drop),
                "date": day.isoformat(),
                "league": lg.league,
                "scoring": lg.scoring,
                "set": QUEUE_SET,
                "decision": lg.entry.get("id"),
                "knobs": lg.entry.get("knobs"),
                "add": add,
                "drop": drop,
                "from": clear.isoformat() if clear else None,
                "availability": kind,
                "judged": JUDGED,
                "gain": gain,
                "value": value,
                "season": _horizon(m, SEASON),
                "season_costly": m.get("season_costly"),
                "held": list(s.get("held") or []),
                "flag": lg.flags.get(add),
                "floor": {**floor.to_dict(), "below": below},
                "bid": {**bid.to_dict(), "typical": typical[0], "typical_from": typical[1]},
                "queued": reason is None,
                "reason": reason,
                "rank": queued if reason is None else None,
                "queued_at": None,
                "executes_at": None,
                "struck": False,
                "bid_struck": False,
                "outcome": None,
                "outcome_reason": None,
                "outcome_at": None,
                "resolved": None,
            }
        )
    return out


def kept(e: Mapping[str, Any]) -> bool:
    """An entry a rebuild keeps as it is: struck, its bid struck, or executed."""
    return bool(e.get("struck") or e.get("bid_struck") or e.get("outcome"))


def holds_place(e: Mapping[str, Any]) -> bool:
    """An entry that takes a place under the day's cap: queued, not struck, and neither skipped,
    failed nor gone (those free their place for a rebuild)."""
    return (
        bool(e.get("queued"))
        and not e.get("struck")
        and e.get("outcome") not in ("skipped", "failed", "gone")
    )


def executes_at(queued_at: datetime, day: date, execute_time: str = EXECUTE_TIME) -> datetime:
    """When an entry executes, in UTC: the later of its queueing plus the veto window and the
    day's execute time on the Pacific clock (the ruling's addition: a window that closes while
    the user sleeps is no veto)."""
    hh, mm = (int(x) for x in execute_time.split(":"))
    at = datetime.combine(day, time(hh, mm), EXECUTE_TZ)
    return max(queued_at + WINDOW, at).astimezone(UTC)


def merge(
    old: Sequence[Mapping[str, Any]],
    new: Iterable[Mapping[str, Any]],
    day: date,
    execute_time: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """A rebuild of the day: the old entries struck or executed kept by id as they are; the new
    build's others, each queued one with when it was first queued (an entry the old build queued
    keeps its time; one new to the queue is queued now, with a full window) and when it
    executes (:func:`executes_at`)."""
    keep = {e["id"]: dict(e) for e in old if kept(e)}
    before = {e["id"]: e for e in old}
    out = list(keep.values())
    for e in new:
        if e["id"] in keep:
            continue
        queued_at = at = None
        if e["queued"]:
            prior = before.get(e["id"]) or {}
            queued_at = (prior.get("queued_at") if prior.get("queued") else None) or now.isoformat()
            at = executes_at(datetime.fromisoformat(queued_at), day, execute_time).isoformat()
        out.append({**e, "queued_at": queued_at, "executes_at": at})
    return out


def retime(
    entries: Iterable[Mapping[str, Any]], day: date, execute_time: str
) -> list[dict[str, Any]]:
    """The day's entries after the user set another execute time: each queued one not executed
    executes at the new time, never sooner than a full window after it was queued."""
    out = []
    for e in entries:
        e = dict(e)
        if e.get("queued") and not e.get("outcome") and e.get("queued_at"):
            queued_at = datetime.fromisoformat(e["queued_at"])
            e["executes_at"] = executes_at(queued_at, day, execute_time).isoformat()
        out.append(e)
    return out


def due(entries: Iterable[Mapping[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """The entries to execute now: queued, not struck, not executed, their window over."""
    return [
        dict(e)
        for e in entries
        if e.get("queued")
        and not e.get("struck")
        and not e.get("outcome")
        and e.get("executes_at")
        and datetime.fromisoformat(e["executes_at"]) <= now
    ]


def effective_bid(e: Mapping[str, Any]) -> int:
    """The bid a claim is placed with: $0 when the user struck the bid alone."""
    return 0 if e.get("bid_struck") else int((e.get("bid") or {}).get("amount") or 0)


def resolve(e: Mapping[str, Any], added: frozenset[int], elsewhere: frozenset[int]) -> str | None:
    """A placed claim's outcome the morning after, from the league's transactions: ``won`` when
    my team added the player, ``lost`` when another team has him; None while neither shows."""
    if e.get("outcome") not in PLACED or e.get("resolved"):
        return e.get("resolved")
    if e["add"] in added:
        return "won"
    if e["add"] in elsewhere:
        return "lost"
    return None


def keep_reason(net_positive: bool, beats_best: bool, returns: bool, bench: bool) -> str:
    """Why the keep rule protects a player, in words (#124)."""
    if bench and not (net_positive and beats_best and returns):
        return (
            "better than the best add over the season and back within a week: he stays on the bench"
        )
    return "net positive, not beaten by the best add by the floor, and back this season"
