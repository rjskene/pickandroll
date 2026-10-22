"""The Lineup view (#107, #124): ``GET /seasons/{league}/lineup?week=N``, my recommended
lineup for each day of a week against Yahoo's lineup as read, with the held slots.

The lineup is the move model's own (``season_moves.build``: the same first day, rates, games,
out rule and returns), placed by ``season.lineup``. A day before the first day a change counts
(today once its games began, or today in a league whose changes count tomorrow) shows Yahoo's
lineup only. Yahoo's lineup for a day is the team page shown for it (``lineup/<team>/<day>``),
or for today the team page read today. A day with neither is listed as not read, and a private
league's payload names the pages for the user's Chrome to open (``needs``).

Every recommended day is slot by slot with player ids, for whatever applies it later; nothing
here applies a lineup. The first alerts are the held players whose status cleared: each blocks
every add until he is activated (Yahoo's rule).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from ..season import Player, Season
from ..season import lineup as lu
from ..season import moves as mv
from ..season import weekly as wk
from ..season.state import SLOTS_PAGE, RosterSpot, SeasonSettings, lineup_key, roster_key
from ..sources.yahoo import public
from .season_moves import Built, cleared_payload
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


def payload(
    built: Built, season: Season, today: date, week: int | None = None, is_public: bool = True
) -> dict[str, Any] | None:
    """The week's lineups, or None when the week is not one of the moves' four."""
    p = built.problem
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
    first = p.first_day if span.this_week else w.start
    if span.this_week and s.lineup_from == "tomorrow":
        first = max(first, today + timedelta(days=1))
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
    weekly = s.lineup_changes == "weekly"
    if weekly:
        fixed = lu.weekly_lineup(active, playing, ahead, p.slots, p.value)
        recs: Mapping[date, Mapping[int, str]] = {d: fixed for d in ahead}
    else:
        recs = wk.daily_starters(active, playing, ahead, p.slots, p.value)

    days = []
    mentioned: set[int] = {k for k, _ in p.roster} | {k for k, _ in p.held}
    positions = {k: pl.positions for k, pl in members.items()}
    for day in w.days():
        read = reads.get(day)
        line = lu.compare(
            day, recs.get(day), read[0] if read else None, playing, p.slots, positions
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


def _held(p: mv.MoveProblem, s: SeasonSettings, today: Read | None) -> dict[str, Any]:
    """The held slots one by one with whoever sits in each (today's lineup when read, else the
    roster), cleared occupants marked; the open ones; the active players eligible for one; and
    where the slots come from (a lower bound unless the settings page was read)."""
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
                    and not mv.eligible(player.status, kind, p.held_accepts),
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
    until read, and each day ahead whose lineup was not read today."""
    out = [] if s.held_from == SLOTS_PAGE else [public.settings_page_url(s.league)]
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
            else "an active spot is open for him"
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
