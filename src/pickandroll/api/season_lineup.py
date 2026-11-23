"""The Lineup view (#107, #124): ``GET /seasons/{league}/lineup?week=N``, my recommended
lineup for each day of a week against Yahoo's lineup as read, with the held slots.

The lineup is the move model's own (``season_moves.build``: the same first day, rates, games,
out rule and returns), placed by ``season.lineup``: :func:`recommended`, which the Matchup and
Season views' projections of this week count too. A day before the first day a change counts
(today once its games began, or today in a league whose changes count tomorrow) shows Yahoo's
lineup only. Yahoo's lineup for a day is the team page shown for it (``lineup/<team>/<day>``),
or for today the team page read today. A day with neither is listed as not read, and a private
league's payload names the pages for the user's Chrome to open (``needs``).

Every recommended day is slot by slot with player ids, for whatever applies it later; nothing
here applies a lineup. The first alerts are the held players whose status cleared: each blocks
every add until he is activated (Yahoo's rule).

The weekly record's games lost to the lineup (#149, :func:`week_lost`) count only a day's
lineup read after the day, the cached box scores saying who played.
"""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import Player, Season
from ..season import lineup as lu
from ..season import moves as mv
from ..season import weekly as wk
from ..season.calendar import Week
from ..season.state import SLOTS_PAGE, RosterSpot, SeasonSettings, lineup_key, roster_key
from ..sources.yahoo import public
from . import season_week as sw
from .season_moves import Built, cleared_payload
from .season_scorecard import BoxScores
from .season_week import NBA_TZ

#: The days the digest's lineup line covers: today and tomorrow.
DIGEST_DAYS = 2


def _player(p: Player) -> dict[str, Any]:
    return {
        "name": p.name,
        "nba_team": p.nba_team,
        "positions": list(p.positions),
        "status": p.status,
    }


def _local(at: datetime) -> date:
    return at.astimezone(NBA_TZ).date()


Read = tuple[tuple[RosterSpot, ...], datetime, str]


def yahoo_reads(season: Season, team: int, today: date) -> dict[date, Read]:
    """``team``'s lineups read, by day, each with when it was read and from which page: the
    team page shown for the day, or for today the team page read today."""
    out = {
        day: (spots, season.fetched[lineup_key(team, day)][0], "dated page")
        for day, spots in season.lineups.get(team, {}).items()
    }
    read = season.fetched.get(roster_key(team))
    if today not in out and read is not None and _local(read[0]) == today:
        out[today] = (season.rosters.get(team, ()), read[0], "team page")
    return out


def final_reads(
    season: Season, team: int, days: Sequence[date]
) -> dict[date, tuple[RosterSpot, ...]]:
    """``team``'s lineups of ``days`` read after the day, the only final ones (#149): a page
    read on its own day may predate a change made later that day."""
    out = {}
    for day in days:
        spots = season.lineups.get(team, {}).get(day)
        read = season.fetched.get(lineup_key(team, day))
        if spots is not None and read is not None and _local(read[0]) > day:
            out[day] = spots
    return out


def week_lost(
    season: Season,
    week: Week,
    box: BoxScores,
    sat: Mapping[date, Collection[int]] | None = None,
) -> dict[str, Any] | None:
    """My games lost to the lineup over ``week`` (``season.lineup.week_lost``), from the
    lineups read after their day and the cached box scores: a player played when his line
    there is not empty. ``sat`` are each day's recommended sits as recorded (:func:`sits_read`,
    #482): sat, not lost. None when the league has no team of mine."""
    s = season.settings
    team = s.my_team_id
    if team is None:
        return None
    reads = final_reads(season, team, week.days())
    games = box.days(week.start, week.end)
    named = {
        sp.player.yahoo_id: (sp.player.name, sp.player.nba_team)
        for spots in reads.values()
        for sp in spots
    }
    espn = {k: e for k, (e, _) in box.match(named, [g for d in games.values() for g in d]).items()}
    played = {
        day: {
            k
            for k, e in espn.items()
            if any(
                ((g.get("players") or {}).get(e) or {}).get("line") is not None for g in day_games
            )
        }
        for day, day_games in games.items()
    }
    lineups = {
        day: [(sp.slot, sp.player.yahoo_id, sp.player.positions) for sp in spots]
        for day, spots in reads.items()
    }
    return lu.week_lost(week.days(), lineups, played, wk.starting_slots(s.roster), espn, sat)


#: Each day's recommended sits as the day's solves made them (#482), in the league's season
#: folder: what tells a sit from a game lost once the day is over, in every league, the
#: suggestions-only one included.
SITS_FILE = "sits.json"
_sits_lock = threading.Lock()


def record_sits(folder: Path, lineup: Mapping[str, Any], today: date, at: datetime) -> list[int]:
    """Record today's recommended sit from the Lineup view's payload (``lineup``, this week's),
    the players added to the day's record, if any: a day's record is every player a solve of
    that day sat, each with when he was first sat and the sit's gain and categories then. Written
    only when a player is new to it, whole to a temporary file and moved into place."""
    day = next((d for d in lineup.get("days", []) if d["date"] == today.isoformat()), None)
    sit = (day or {}).get("sits")
    if day is None or day["past"] or not sit:
        return []
    path = folder / SITS_FILE
    with _sits_lock:
        body = _read_sits(path)
        seen = body.setdefault(today.isoformat(), [])
        known = {k for entry in seen for k in entry["players"]}
        new = [k for k in sit["players"] if k not in known]
        if not new:
            return []
        seen.append({"at": at.isoformat(), **sit, "players": new, "with": sit["players"]})
        folder.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, indent=1) + "\n")
        os.replace(tmp, path)
    return new


def sits_read(folder: Path) -> dict[date, frozenset[int]]:
    """Each day's recorded recommended sits (:func:`record_sits`), by day."""
    return {
        date.fromisoformat(day): frozenset(k for entry in seen for k in entry["players"])
        for day, seen in _read_sits(folder / SITS_FILE).items()
    }


def _read_sits(path: Path) -> dict[str, list[dict[str, Any]]]:
    """The sits record, empty when there is none or it does not read: a record lost only counts
    those games as lost again, as before #482."""
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def begun_teams(tips: Mapping[str, str] | None, now: datetime) -> frozenset[str]:
    """The teams of a day's ``tips`` (the schedule copy's) whose game began by ``now``: none
    without tip-offs, and the executor still skips a group a passed tip-off holds."""
    out = set()
    for team, raw in (tips or {}).items():
        try:
            if datetime.fromisoformat(raw) <= now:
                out.add(team)
        except ValueError:
            continue
    return frozenset(out)


def first_change(p: mv.MoveProblem, s: SeasonSettings, today: date) -> date:
    """The first day of this week a lineup change counts."""
    if s.lineup_from == "tomorrow":
        return max(p.first_day, today + timedelta(days=1))
    return p.first_day


def _locked(read: Read | None, begun: Collection[str]) -> lu.Locked[int] | None:
    """Today's players as read whose team's game began (:class:`season.lineup.Locked`); None
    with no read of today, so nobody's place is known."""
    if read is None:
        return None
    gone = [sp for sp in read[0] if sp.player.nba_team in begun]
    on = {sp.player.yahoo_id: sp.slot for sp in gone if sp.slot.upper() not in wk.NOT_STARTING}
    return lu.Locked(on, frozenset(sp.player.yahoo_id for sp in gone) - set(on))


@dataclass(frozen=True)
class Recommended:
    """The recommended lineup of a week's days from the first a change counts."""

    days: Mapping[date, Mapping[int, str]]
    #: The crowded days' recommended starters who play, for a projection to rank first (every
    #: other day stays on the value path, a held player back this week counted as ever); None
    #: when the lineup is the one the projection already counts.
    chosen: Mapping[date, frozenset[int]] | None = None
    #: The days whose recommended lineup sits players with a game (#482).
    sits: Mapping[date, lu.Sit[int]] = field(default_factory=dict)


def recommended(
    built: Built,
    season: Season,
    today: date,
    span: mv.WeekSpan,
    first: date,
    begun: Collection[str] = (),
) -> Recommended:
    """``span``'s recommended lineup (#314): on this week's days against a named opponent whose
    roster is read, the most expected categories won (``season.lineup.win_starters``), or the
    best matchup odds in a one-win league (#397), anchored
    on Yahoo's lineup as read and with today's players of the ``begun`` teams where Yahoo has
    them. Any other week, an unread matchup and a points league rank by the general value, and a
    league whose lineups change weekly keeps its one lineup."""
    p = built.as_read
    s = season.settings
    mine = s.my_team_id
    ahead = [d for d in span.days if d >= first]
    active = list(p.roster)
    playing = wk.playing_days(
        active,
        span.days,
        p.schedule,
        span.this_week,
        games=span.games,
        no_games=p.no_games,
        available_from=p.returns,
    )
    if s.lineup_changes == "weekly":
        fixed = lu.weekly_lineup(active, playing, ahead, p.slots, p.value)
        return Recommended({d: fixed for d in ahead})
    by_value = wk.daily_starters(active, playing, ahead, p.slots, p.value)
    matchup, _ = sw.matchup_read(season, mine)
    other = matchup.opponent_of(mine) if matchup is not None else None
    if not span.this_week or not span.opponents or p.points or other not in season.rosters:
        return Recommended(by_value)
    reads = yahoo_reads(season, mine, today)
    done = wk.daily_starters(active, playing, [d for d in span.days if d < first], p.slots, p.value)
    locked = _locked(reads.get(today), begun) if today in ahead and begun else None
    theirs = span.so_far_theirs[0] if span.so_far_theirs else {}
    win = lu.win_lineup(
        active,
        playing,
        ahead,
        p.slots,
        p.value,
        p.rates,
        p.cats,
        span.so_far,
        wk.finals(span.opponents[0], theirs, p.cats),
        yahoo={
            day: [sp.player.yahoo_id for sp in read[0] if sp.slot.upper() not in wk.NOT_STARTING]
            for day, read in reads.items()
        },
        locked={today: locked} if locked is not None else None,
        started=Counter(k for lineup in done.values() for k in lineup),
        one_win=s.one_win,
    )
    days = win.days
    crowded = [
        d
        for d in ahead
        if sum(d in v for v in playing.values()) > len(by_value[d]) or d in win.sits
    ]
    return Recommended(
        days,
        {d: frozenset(k for k in days[d] if d in playing.get(k, ())) for d in crowded},
        win.sits,
    )


def payload(
    built: Built,
    season: Season,
    today: date,
    week: int | None = None,
    is_public: bool = True,
    begun: Collection[str] = (),
) -> dict[str, Any] | None:
    """The week's lineups, or None when the week is not one of the moves' four. ``begun`` are the
    teams whose game today began (:func:`begun_teams`)."""
    p = built.as_read
    s = season.settings
    mine = s.my_team_id
    if mine is None or season.calendar is None:
        return None
    numbers = [*built.horizons["week"]["weeks"], *built.horizons["three"]["weeks"]]
    spans = [*p.horizons["week"], *p.horizons["three"]]
    number = numbers[0] if week is None else week
    if number not in numbers:
        return None
    span = spans[numbers.index(number)]
    w = next(x for x in season.calendar.weeks if x.number == number)
    first = first_change(p, s, today) if span.this_week else w.start
    ahead = [d for d in span.days if d >= first]

    reads = yahoo_reads(season, mine, today)
    members: dict[int, Player] = dict(p.roster)
    for spots, _, _ in reads.values():
        for sp in spots:
            if sp.slot not in mv.HELD:
                members.setdefault(sp.player.yahoo_id, sp.player)
    roster = list(members.items())
    playing = wk.playing_days(
        roster,
        span.days,
        p.schedule,
        span.this_week,
        games=span.games,
        no_games=p.no_games,
        available_from=p.returns,
    )
    # A day before the first is as scheduled: whoever's team played.
    for k, player in roster:
        past = wk.game_days(player.nba_team, [d for d in w.days() if d < first], p.schedule)
        playing[k] = [*past, *playing.get(k, [])]
    active = list(p.roster)
    # The recommendation is the active roster's alone: a day page's player held now, or gone,
    # plays in the compare and never in the lineup (#196).
    rec = recommended(built, season, today, span, first, begun)
    recs = rec.days

    days = []
    mentioned: set[int] = {k for k, _ in p.roster} | {k for k, _ in p.held}
    positions = {k: pl.positions for k, pl in members.items()}
    for day in w.days():
        read = reads.get(day)
        sat = rec.sits.get(day)
        line = lu.compare(
            day,
            recs.get(day),
            read[0] if read else None,
            playing,
            p.slots,
            positions,
            sat.players if sat is not None else (),
        )
        mentioned |= {k for _, k in line.yahoo or ()}
        days.append(
            {
                "date": day.isoformat(),
                "past": day < first,
                "recommended": None
                if line.recommended is None
                else [{"slot": slot, "player": k} for slot, k in line.recommended],
                "bench": None
                if line.recommended is None
                else [k for k, _ in active if k not in recs.get(day, {})],
                "yahoo": None
                if read is None
                else {
                    "read_at": read[1].isoformat(),
                    "page": read[2],
                    "stale": _local(read[1]) < today and day >= today,
                    "slots": [{"slot": slot, "player": k} for slot, k in line.yahoo or ()],
                },
                "games": {
                    "recommended": len(line.started) if line.recommended is not None else None,
                    "yahoo": None if line.yahoo_started is None else len(line.yahoo_started),
                },
                "lost": line.lost,
                "start": list(line.start),
                "sit": list(line.sit),
                "sits": _sits(sat, s.one_win),
                # Whoever of mine plays that day: a bench player's game, a starter's none.
                "playing": sorted(k for k in members if day in playing.get(k, ())),
            }
        )

    held = _held(p, s, reads.get(today))
    cleared = cleared_payload(p)
    alerts = [{"kind": "cleared", **c} for c in cleared] + [
        {"kind": "unknown_status", "player": k, "status": pl.status}
        for k, pl in [*p.roster, *p.held]
        if pl.status is not None and pl.status not in mv.KNOWN_STATUSES
    ]
    if s.held_from != SLOTS_PAGE:
        alerts.append({"kind": "held_lower_bound", "slots": s.held_slots})
    if s.lineup_changes is None:
        alerts.append({"kind": "rule_unknown"})
    mentioned |= {c["drop"] for c in cleared if c["drop"] is not None}
    players = {**dict(p.held), **members}
    counted = [d for d in days if not d["past"] and d["lost"] is not None]
    return {
        "week": number,
        "weeks": numbers,
        "start": w.start.isoformat(),
        "end": w.end.isoformat(),
        "first": first.isoformat(),
        "this_week": span.this_week,
        "system": built.system,
        "rule": {
            "changes": s.lineup_changes,
            "from": s.lineup_from,
            "deadline": s.lineup_deadline,
            "source": "settings page"
            if s.held_from == SLOTS_PAGE and s.lineup_deadline
            else "v3 settings"
            if s.lineup_changes
            else None,
        },
        "slots": list(p.slots),
        "held": held,
        "alerts": alerts,
        "days": days,
        "summary": {
            "lost": sum(d["lost"] for d in counted),
            "differ": [d["date"] for d in counted if d["start"]],
            "unread": [d["date"] for d in days if not d["past"] and d["yahoo"] is None],
        },
        "needs": [] if is_public else _needs(s, mine, ahead, reads, today),
        "players": {str(k): _player(players[k]) for k in sorted(mentioned) if k in players},
    }


def _sits(sit: lu.Sit[int] | None, one_win: bool) -> dict[str, Any] | None:
    """A day's deliberate sit for the view (#482): the players sat together, their one joint
    gain in ``unit`` (expected categories, or the matchup's odds in a one-win league), and each
    category it moves, its odds before and after."""
    if sit is None:
        return None
    return {
        "players": list(sit.players),
        "gain": round(sit.gain, 4),
        "unit": "odds" if one_win else "categories",
        "cats": [
            {"cat": cat, "before": round(a, 4), "after": round(b, 4)} for cat, a, b in sit.cats
        ],
    }


def _held(p: mv.MoveProblem, s: SeasonSettings, today: Read | None) -> dict[str, Any]:
    """The held slots one by one with whoever sits in each (today's lineup when read, else the
    roster), cleared occupants marked; the open ones; the active players eligible for one; and
    where the slots come from (a lower bound unless the settings page was read).

    A player is listed eligible for every held kind the league has whose rule his status fits,
    a full one included: when the IL is full the user decides whom to swap (#124), so the view
    tells "eligible, IL full" from "eligible, 1 open" by ``open``."""
    statuses = dict(p.held)
    sitting = (
        [(sp.slot, sp.player.yahoo_id) for sp in today[0] if sp.slot in mv.HELD]
        if today is not None
        else [(slot, k) for k, slot in p.held_slots.items()]
    )
    rows = []
    open_: dict[str, int] = {}
    for kind, n in s.held_slots.items():
        here = [k for slot, k in sitting if slot == kind]
        for i in range(max(n, len(here))):
            k = here[i] if i < len(here) else None
            player = statuses.get(k) if k is not None else None
            rows.append(
                {
                    "slot": kind,
                    "player": k,
                    "cleared": player is not None
                    and mv.is_cleared(player.status, kind, p.held_accepts),
                }
            )
        open_[kind] = max(0, n - len(here))
    eligible = [
        {
            "player": k,
            "slots": [x for x in mv.held_slots_for(pl.status, p.held_accepts) if x in open_],
        }
        for k, pl in p.roster
    ]
    return {
        "slots": rows,
        "open": open_,
        "eligible": [e for e in eligible if e["slots"]],
        "source": s.held_from,
        "lower_bound": s.held_from != SLOTS_PAGE,
    }


def _needs(
    s: SeasonSettings, team: int, days: Sequence[date], reads: Mapping[date, Read], today: date
) -> list[str]:
    """The pages a private league's lineup still needs from the user's Chrome: the settings page
    until every field it gives was read (#316), and each day ahead whose lineup was not read
    today."""
    out = [] if s.page_rules_read else [public.settings_page_url(s.league)]
    for day in days:
        read = reads.get(day)
        if read is None or _local(read[1]) < today:
            out.append(public.team_url(s.league, team, day))
    return out


def digest_line(league: str, lineup: Mapping[str, Any], today: date) -> str | None:
    """The digest's line for a league: today's and tomorrow's games lost as set, with the
    players to start and to sit; None when nothing is lost (#107)."""
    names = {int(k): v["name"] for k, v in lineup["players"].items()}
    last = today + timedelta(days=DIGEST_DAYS - 1)
    parts = []
    for d in lineup["days"]:
        day = date.fromisoformat(d["date"])
        if d["past"] or not today <= day <= last or not d["lost"]:
            continue
        start = ", ".join(names.get(k, str(k)) for k in d["start"])
        sit = ", ".join(names.get(k, str(k)) for k in d["sit"])
        games = f"{d['lost']} game{'s' if d['lost'] != 1 else ''} lost"
        parts.append(f"{day:%a} start {start}" + (f" for {sit}" if sit else "") + f" ({games})")
    return f"- League {league}: " + "; ".join(parts) if parts else None


def cleared_line(league: str, lineup: Mapping[str, Any]) -> str | None:
    """The digest's line for a league whose held slot holds a player whose status cleared: he
    blocks every add until activated, and the activation's drop; None when there is none."""
    names = {int(k): v["name"] for k, v in lineup["players"].items()}
    parts = []
    for a in lineup["alerts"]:
        if a["kind"] != "cleared":
            continue
        who = names.get(a["player"], str(a["player"]))
        status = f"as {a['status']}" if a["status"] else "with no status"
        then = (
            f"the activation would drop {names.get(a['drop'], str(a['drop']))}"
            if a["drop"] is not None
            else "an active spot is open for them"
        )
        parts.append(
            f"{who} sits in {a['slot']} {status} and blocks every add until activated; {then}"
        )
    return f"- League {league}: " + "; ".join(parts) if parts else None


def digest_section(lines: Sequence[str]) -> str:
    """The digest's lineup section: a line per league with a held player whose status cleared,
    then one per league that loses a game as set; nothing when there is neither."""
    if not lines:
        return ""
    return "\n".join(["", "### Lineups", "", *lines]) + "\n"
