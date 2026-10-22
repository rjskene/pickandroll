"""A league's season: settings, the twelve rosters, the available pool, this week's matchups,
the league's transactions and the NBA schedule (docs/ADD_DROP.md, phase 1).

A season is assembled from *parts*, each the latest read of one source with the time it was
read and where it came from (``public`` for the API's own pull of Yahoo's public pages,
``extension`` for a page the user's Chrome posted for a private league). A part replaces the
older read of the same key; the available pool is the one exception, upserted row by row when
it arrives a page at a time. Everything here is pure: the loaders in ``sources`` produce the
parts' data and ``api.seasons`` stores them.

Part keys and their data:

``settings``
    :class:`SeasonSettings` fields read from Yahoo (name, weeks, waiver and add rules).
``league_settings``
    The league's settings page (#107): the roster positions with the held slots (IL, IL+, NA,
    which Yahoo's v3 settings leave out), the lineup deadline and the playoff weeks. The source
    of the held slots; without it they are the most any read roster fills, a lower bound.
``players``
    Yahoo's player pool for the league: a list of :class:`Player`.
``league``
    The league page: ``teams`` (:class:`Team` rows of the standings) and ``matchups`` (this
    week's pairs, ``{"week", "teams": [a, b]}`` with ``"score"`` once played). A pair's
    matchup page replaces its row, keeping the league page's score when that was read later.
``pairings/<week>``
    The league page shown for another week (``?matchup_week=N``): ``{"week", "matchups"}``.
    Never the league part, so it moves neither the standings nor the current week.
``roster/<team id>``
    One team page: ``{"team_id", "name", "spots": [{"slot", "player"}]}``.
``lineup/<team id>/<YYYY-MM-DD>``
    The team page shown for a day (``?date=``): that day's lineup, as ``roster/`` holds today's
    (#107).
``available``
    ``{"rows": [...]}``, :class:`Available` rows with the time each was seen.
``matchup/<week>/<a>-<b>``
    One matchup page: :class:`Matchup`.
``transactions``
    ``{"rows": [...]}``, :class:`Transaction` rows, newest first.
``calendar``
    :class:`~pickandroll.season.calendar.Calendar`.
``schedule``
    ``{"days": {"YYYY-MM-DD": ["ATL", ...]}}``: the NBA teams with a game on each day, in
    Yahoo's abbreviations.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from typing import Any

from .calendar import Calendar, Week

PUBLIC = "public"
EXTENSION = "extension"
#: The part holding Yahoo's own projection for the next seven days, by player (#93).
YAHOO_WEEK = "yahoo_week"
#: Yahoo's injury and availability codes that keep a player out of a game.
OUT_CODES = frozenset({"O", "INJ", "SUSP", "NA", "OFS"})
#: The roster slots whose players are off the active roster (``season.moves.HELD``).
HELD_SLOTS = ("IL", "IL+", "NA")
#: Where a season's held slot counts come from.
SLOTS_PAGE = "settings page"
SLOTS_ROSTERS = "rosters read"


def _opt_int(v: Any) -> int | None:
    return None if v is None or v == "" else int(v)


def _opt_float(v: Any) -> float | None:
    return None if v is None or v == "" else float(v)


def _opt_date(v: Any) -> date | None:
    return date.fromisoformat(v) if v else None


@dataclass(frozen=True)
class SeasonSettings:
    league: str
    scoring: str
    cats: tuple[str, ...]
    roster: tuple[str, ...]
    num_teams: int
    my_team_id: int | None
    points: Mapping[str, float] | None = None
    name: str | None = None
    current_week: int | None = None
    start_week: int | None = None
    end_week: int | None = None
    end_date: date | None = None
    weekly_deadline: str | None = None
    waiver_rule: str | None = None
    waiver_days: int | None = None
    uses_faab: bool | None = None
    max_weekly_adds: int | None = None
    trade_end_date: date | None = None
    #: Who reviews an accepted trade (``yahoo``, ``commish``, ``vote`` or ``none``).
    trade_ratify: str | None = None
    #: The days an accepted trade waits for review before it is processed.
    trade_review_days: int | None = None
    #: The teams the playoffs take.
    playoff_teams: int | None = None
    #: The playoff weeks as the settings page prints them.
    playoff_weeks: tuple[int, ...] = ()
    #: The settings page's "Weekly Deadline" as printed (``Daily - Today``), and what it means:
    #: lineups change ``daily`` or ``weekly``, a daily change counting ``today`` or ``tomorrow``.
    lineup_deadline: str | None = None
    lineup_changes: str | None = None
    lineup_from: str | None = None
    #: Where the held slots of ``roster`` come from: :data:`SLOTS_PAGE`, or :data:`SLOTS_ROSTERS`
    #: (the most any read roster fills: a lower bound); None before the season is read.
    held_from: str | None = None
    #: Whether an injured player can be added straight to an injury slot.
    injured_add_to_slot: bool | None = None

    @property
    def first_playoff_week(self) -> int | None:
        """The first playoff week: the settings page's, else estimated as one week a round of
        the bracket ending with the season's last week (six teams: three rounds, two of them
        with byes); None when neither is known. Yahoo's v3 settings do not name the week."""
        if self.playoff_weeks:
            return self.playoff_weeks[0]
        if not self.end_week or not self.playoff_teams or self.playoff_teams < 2:
            return None
        return self.end_week - math.ceil(math.log2(self.playoff_teams)) + 1

    @property
    def held_slots(self) -> dict[str, int]:
        """The league's held slots by kind (IL, IL+, NA), as ``roster`` holds them."""
        return {k: n for k in HELD_SLOTS if (n := sum(1 for x in self.roster if x == k))}

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("end_date", "trade_end_date"):
            d[k] = d[k].isoformat() if d[k] else None
        d["cats"], d["roster"] = list(self.cats), list(self.roster)
        d["playoff_weeks"] = list(self.playoff_weeks)
        d["points"] = dict(self.points) if self.points else None
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SeasonSettings:
        return cls(
            league=str(d["league"]),
            scoring=d["scoring"],
            cats=tuple(d.get("cats") or ()),
            roster=tuple(d.get("roster") or ()),
            num_teams=int(d["num_teams"]),
            my_team_id=_opt_int(d.get("my_team_id")),
            points=dict(d["points"]) if d.get("points") else None,
            name=d.get("name"),
            current_week=_opt_int(d.get("current_week")),
            start_week=_opt_int(d.get("start_week")),
            end_week=_opt_int(d.get("end_week")),
            end_date=_opt_date(d.get("end_date")),
            weekly_deadline=d.get("weekly_deadline"),
            waiver_rule=d.get("waiver_rule"),
            waiver_days=_opt_int(d.get("waiver_days")),
            uses_faab=None if d.get("uses_faab") is None else bool(d["uses_faab"]),
            max_weekly_adds=_opt_int(d.get("max_weekly_adds")),
            trade_end_date=_opt_date(d.get("trade_end_date")),
            trade_ratify=d.get("trade_ratify"),
            trade_review_days=_opt_int(d.get("trade_review_days")),
            playoff_teams=_opt_int(d.get("playoff_teams")),
            playoff_weeks=tuple(int(w) for w in d.get("playoff_weeks") or ()),
            lineup_deadline=d.get("lineup_deadline"),
            lineup_changes=d.get("lineup_changes"),
            lineup_from=d.get("lineup_from"),
            held_from=d.get("held_from"),
            injured_add_to_slot=None
            if d.get("injured_add_to_slot") is None
            else bool(d["injured_add_to_slot"]),
        )

    def merged(self, read: Mapping[str, Any]) -> SeasonSettings:
        """These settings (the league folder's) with what Yahoo's settings read adds; the
        folder's own scoring, categories, roster and team id win."""
        keep = {"league", "scoring", "cats", "roster", "num_teams", "my_team_id", "points"}
        fields = {k: v for k, v in read.items() if k not in keep and v is not None}
        return SeasonSettings.from_dict({**self.to_dict(), **fields})

    def with_slots(
        self, page: Mapping[str, Any] | None, rosters: Iterable[Iterable[str]]
    ) -> SeasonSettings:
        """These settings with the held slots and the lineup rule read: the settings page's
        positions and rule when it was read; else the folder's active slots with, for each held
        kind, the most any read roster (``rosters``, each its slots) fills, and the rule from
        v3's ``weekly_deadline``. The folder's own held slots (the draft's) are never used."""
        changes, effective = _lineup_rule(self.weekly_deadline)
        if page is not None:
            read = page.get("lineup_changes") is not None
            return replace(
                self,
                roster=tuple(str(x) for x in page.get("roster") or self.roster),
                playoff_weeks=tuple(int(w) for w in page.get("playoff_weeks") or ()),
                lineup_deadline=page.get("lineup_deadline"),
                lineup_changes=page.get("lineup_changes") if read else changes,
                lineup_from=page.get("lineup_from") if read else effective,
                held_from=SLOTS_PAGE,
                injured_add_to_slot=page.get("injured_add_to_slot"),
            )
        seen: dict[str, int] = {}
        any_read = False
        for slots in rosters:
            any_read = True
            for kind in HELD_SLOTS:
                seen[kind] = max(seen.get(kind, 0), sum(1 for x in slots if x == kind))
        active = tuple(x for x in self.roster if x not in HELD_SLOTS)
        held = tuple(kind for kind in HELD_SLOTS for _ in range(seen.get(kind, 0)))
        return replace(
            self,
            roster=active + held,
            lineup_changes=changes,
            lineup_from=effective,
            held_from=SLOTS_ROSTERS if any_read else None,
        )


@dataclass(frozen=True)
class Player:
    yahoo_id: int
    name: str
    nba_team: str | None = None
    positions: tuple[str, ...] = ()
    #: Yahoo's injury or availability code (``O``, ``Q``, ``D``, ``P``, ``GTD``, ``NA``, ...).
    status: str | None = None
    status_full: str | None = None
    note: str | None = None

    @property
    def out(self) -> bool:
        return self.status in OUT_CODES

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["positions"] = list(self.positions)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Player:
        return cls(
            yahoo_id=int(d["yahoo_id"]),
            name=d["name"],
            nba_team=d.get("nba_team"),
            positions=tuple(d.get("positions") or ()),
            status=d.get("status") or None,
            status_full=d.get("status_full") or None,
            note=d.get("note") or None,
        )

    def with_pool(self, pool: Player | None) -> Player:
        """This player as a page printed him, filled in from the league's pool: the longer of
        the two names (team pages abbreviate), the pool's team and positions where the page has
        none, the pool's status words when both name the same status, and the pool's note."""
        if pool is None:
            return self
        status = self.status or pool.status
        return Player(
            yahoo_id=self.yahoo_id,
            name=pool.name if len(pool.name) > len(self.name) else self.name,
            nba_team=self.nba_team or pool.nba_team,
            positions=self.positions or pool.positions,
            status=status,
            status_full=self.status_full or (pool.status_full if pool.status == status else None),
            note=self.note or (pool.note if pool.status == status else None),
        )


@dataclass(frozen=True)
class RosterSpot:
    #: The slot the player sits in on the day the page was read (``PG`` ... ``BN``, ``IL``).
    slot: str
    player: Player

    def to_dict(self) -> dict[str, Any]:
        return {"slot": self.slot, "player": self.player.to_dict()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RosterSpot:
        return cls(d["slot"], Player.from_dict(d["player"]))


@dataclass(frozen=True)
class Team:
    team_id: int
    name: str
    rank: int | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    #: A points league's points for, as the standings print them.
    points_for: float | None = None
    waiver_priority: int | None = None
    faab: float | None = None
    moves: int | None = None

    @property
    def record(self) -> str | None:
        if self.wins is None:
            return None
        return f"{self.wins}-{self.losses or 0}-{self.ties or 0}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Team:
        return cls(
            team_id=int(d["team_id"]),
            name=d["name"],
            rank=_opt_int(d.get("rank")),
            wins=_opt_int(d.get("wins")),
            losses=_opt_int(d.get("losses")),
            ties=_opt_int(d.get("ties")),
            points_for=_opt_float(d.get("points_for")),
            waiver_priority=_opt_int(d.get("waiver_priority")),
            faab=_opt_float(d.get("faab")),
            moves=_opt_int(d.get("moves")),
        )


@dataclass(frozen=True)
class Available:
    player: Player
    #: ``FA`` for a free agent, ``W`` for a player on waivers until ``clears``.
    availability: str
    clears: date | None = None
    pct_rostered: float | None = None
    pct_rostered_change: float | None = None
    pct_started: float | None = None
    pct_started_change: float | None = None
    adds: int | None = None
    drops: int | None = None
    seen_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["player"] = self.player.to_dict()
        d["clears"] = self.clears.isoformat() if self.clears else None
        d["seen_at"] = self.seen_at.isoformat() if self.seen_at else None
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Available:
        return cls(
            player=Player.from_dict(d["player"]),
            availability=d["availability"],
            clears=_opt_date(d.get("clears")),
            pct_rostered=_opt_float(d.get("pct_rostered")),
            pct_rostered_change=_opt_float(d.get("pct_rostered_change")),
            pct_started=_opt_float(d.get("pct_started")),
            pct_started_change=_opt_float(d.get("pct_started_change")),
            adds=_opt_int(d.get("adds")),
            drops=_opt_int(d.get("drops")),
            seen_at=datetime.fromisoformat(d["seen_at"]) if d.get("seen_at") else None,
        )


@dataclass(frozen=True)
class Matchup:
    week: int
    teams: tuple[int, int]
    #: Each team's totals for the week as Yahoo prints them, by column (``FG%``, ``PTS``, ...).
    totals: Mapping[int, Mapping[str, str]] = field(default_factory=dict)
    #: Categories won so far (a categories league) or points (a points league), per team.
    score: tuple[float, float] | None = None
    #: Every score line the page prints, by label: ``vs`` (the score) and, in a points league,
    #: Yahoo's own ``Orig Proj`` and ``Live Proj`` for the week.
    lines: Mapping[str, tuple[float, float]] = field(default_factory=dict)

    def opponent_of(self, team_id: int) -> int | None:
        a, b = self.teams
        return b if team_id == a else a if team_id == b else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "teams": list(self.teams),
            "totals": {str(k): dict(v) for k, v in self.totals.items()},
            "score": list(self.score) if self.score else None,
            "lines": {k: list(v) for k, v in self.lines.items()},
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Matchup:
        a, b = d["teams"]
        return cls(
            week=int(d["week"]),
            teams=(int(a), int(b)),
            totals={int(k): dict(v) for k, v in (d.get("totals") or {}).items()},
            score=(float(d["score"][0]), float(d["score"][1])) if d.get("score") else None,
            lines={k: (float(v[0]), float(v[1])) for k, v in (d.get("lines") or {}).items()},
        )


@dataclass(frozen=True)
class Transaction:
    #: ``add``, ``drop`` or ``trade``.
    kind: str
    player: Player
    team_id: int | None
    team_name: str | None
    #: Yahoo's own words for the move: ``$0 Waiver``, ``Free Agent``, ``To Waivers``.
    detail: str | None = None
    #: When, as the page prints it (``Oct 20, 3:57 am``, the league's time zone).
    when: str | None = None
    #: The transaction a row belongs to: an add and its drop share it.
    group: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["player"] = self.player.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Transaction:
        return cls(
            kind=d["kind"],
            player=Player.from_dict(d["player"]),
            team_id=_opt_int(d.get("team_id")),
            team_name=d.get("team_name"),
            detail=d.get("detail"),
            when=d.get("when"),
            group=int(d.get("group") or 0),
        )


@dataclass(frozen=True)
class Part:
    key: str
    fetched_at: datetime
    source: str
    data: Any

    def to_dict(self) -> dict[str, Any]:
        return {"fetched_at": self.fetched_at.isoformat(), "source": self.source, "data": self.data}

    @classmethod
    def from_dict(cls, key: str, d: Mapping[str, Any]) -> Part:
        return cls(key, datetime.fromisoformat(d["fetched_at"]), d["source"], d["data"])


def roster_key(team_id: int) -> str:
    return f"roster/{team_id}"


def matchup_key(week: int, teams: Iterable[int]) -> str:
    a, b = sorted(int(t) for t in teams)
    return f"matchup/{week}/{a}-{b}"


def lineup_key(team_id: int, day: date) -> str:
    """One day's lineup of a team, from its team page shown for that day."""
    return f"lineup/{team_id}/{day.isoformat()}"


def _lineup_rule(deadline: str | None) -> tuple[str | None, str | None]:
    """v3's ``weekly_deadline`` as a lineup rule: ``intraday`` is daily, counting today (the
    settings page's ``Daily - Today``); anything else is not known."""
    return ("daily", "today") if (deadline or "").strip().lower() == "intraday" else (None, None)


def pairings_key(week: int) -> str:
    """A week's pairs from the league page shown for that week (``?matchup_week=N``)."""
    return f"pairings/{week}"


#: The players page's ownership columns only its Research view (``R_O``) carries; a page in
#: another view leaves them empty.
OWNERSHIP_ONLY = ("pct_rostered_change", "pct_started", "pct_started_change", "adds", "drops")


def merge_part(parts: Mapping[str, Part], part: Part) -> dict[str, Part]:
    """``parts`` with ``part`` in: it replaces the older read of its key, except that available
    rows read a page at a time (the extension's) are upserted by player into the pool, keeping
    the ownership columns a page in another view did not carry, and so are Yahoo's projection
    rows."""
    out = dict(parts)
    old = parts.get(part.key)
    if part.key == YAHOO_WEEK and part.data.get("upsert") and old is not None:
        by_id = {r["player"]["yahoo_id"]: r for r in old.data.get("rows", [])}
        by_id.update({r["player"]["yahoo_id"]: r for r in part.data.get("rows", [])})
        fetched = max(old.fetched_at, part.fetched_at)
        out[part.key] = Part(part.key, fetched, part.source, {"rows": list(by_id.values())})
        return out
    if part.key == "available" and part.data.get("upsert") and old is not None:
        rows = {r["player"]["yahoo_id"]: r for r in old.data.get("rows", [])}
        for r in part.data.get("rows", []):
            was = rows.get(r["player"]["yahoo_id"]) or {}
            kept = {
                k: was[k] for k in OWNERSHIP_ONLY if r.get(k) is None and was.get(k) is not None
            }
            rows[r["player"]["yahoo_id"]] = {**r, **kept}
        fetched = max(old.fetched_at, part.fetched_at)
        out[part.key] = Part(part.key, fetched, part.source, {"rows": list(rows.values())})
    else:
        data = part.data
        if part.key in ("available", YAHOO_WEEK) and isinstance(data, dict) and "upsert" in data:
            data = {k: v for k, v in data.items() if k != "upsert"}
        out[part.key] = Part(part.key, part.fetched_at, part.source, data)
    return out


@dataclass(frozen=True)
class Season:
    settings: SeasonSettings
    calendar: Calendar | None
    teams: tuple[Team, ...]
    rosters: Mapping[int, tuple[RosterSpot, ...]]
    available: tuple[Available, ...]
    #: This week's pairs from the league page, with their totals where a matchup page was read.
    matchups: tuple[Matchup, ...]
    transactions: tuple[Transaction, ...]
    players: Mapping[int, Player]
    schedule: Mapping[date, frozenset[str]]
    #: When each part was read, and by whom.
    fetched: Mapping[str, tuple[datetime, str]]
    #: Yahoo's projection for the next seven days by player id: ``gp`` and the totals over those
    #: games, with when the row was read (``seen_at``).
    yahoo_week: Mapping[int, Mapping[str, Any]] = field(default_factory=dict)
    #: Each week's pairs as far as read: this week's from the league page, the others from the
    #: league page shown for that week (``pairings/<week>``). A week read with no pairs (a playoff
    #: week Yahoo has not seeded) is here and empty; a week never read is not here.
    pairings: Mapping[int, tuple[tuple[int, int], ...]] = field(default_factory=dict)
    #: Each team's lineups read by day (``lineup/<team>/<day>``), each as its team page lists it.
    lineups: Mapping[int, Mapping[date, tuple[RosterSpot, ...]]] = field(default_factory=dict)

    @classmethod
    def from_parts(cls, base: SeasonSettings, parts: Mapping[str, Part]) -> Season:
        """The season from the league folder's settings and the parts read so far."""
        settings = base
        if "settings" in parts:
            settings = base.merged(parts["settings"].data)
        league = _data(parts, "league") or {}
        # A private league has no settings read: its league page names the league and the week.
        fill = {
            "name": settings.name or league.get("name"),
            "current_week": settings.current_week or league.get("week"),
        }
        settings = replace(settings, **{k: v for k, v in fill.items() if v is not None})
        players = {
            p.yahoo_id: p for p in (Player.from_dict(d) for d in (_data(parts, "players") or []))
        }
        teams = tuple(Team.from_dict(t) for t in league.get("teams", []))
        rosters: dict[int, tuple[RosterSpot, ...]] = {}
        names: dict[int, str] = {}
        for key, part in parts.items():
            if key.startswith("roster/"):
                d = part.data
                spots = tuple(RosterSpot.from_dict(s) for s in d.get("spots", []))
                rosters[int(d["team_id"])] = tuple(
                    RosterSpot(s.slot, s.player.with_pool(players.get(s.player.yahoo_id)))
                    for s in spots
                )
                if d.get("name"):
                    names[int(d["team_id"])] = d["name"]
        known = {t.team_id for t in teams}
        teams += tuple(Team(tid, name) for tid, name in sorted(names.items()) if tid not in known)
        settings = settings.with_slots(
            _data(parts, "league_settings"), ([s.slot for s in r] for r in rosters.values())
        )
        lineups: dict[int, dict[date, tuple[RosterSpot, ...]]] = {}
        for key, part in parts.items():
            if key.startswith("lineup/"):
                _, team, day = key.split("/")
                lineups.setdefault(int(team), {})[date.fromisoformat(day)] = tuple(
                    RosterSpot(s.slot, s.player.with_pool(players.get(s.player.yahoo_id)))
                    for s in (RosterSpot.from_dict(x) for x in part.data.get("spots", []))
                )
        rostered = {s.player.yahoo_id for spots in rosters.values() for s in spots}
        available = tuple(
            sorted(
                (
                    replace(a, player=a.player.with_pool(players.get(a.player.yahoo_id)))
                    for a in (
                        Available.from_dict(r)
                        for r in (_data(parts, "available") or {}).get("rows", [])
                    )
                    if a.player.yahoo_id not in rostered
                ),
                key=lambda a: (-(a.pct_rostered or 0.0), a.player.name),
            )
        )
        pairs = {
            matchup_key(m["week"], m["teams"]): Matchup(
                int(m["week"]),
                (int(m["teams"][0]), int(m["teams"][1])),
                score=(float(m["score"][0]), float(m["score"][1])) if m.get("score") else None,
            )
            for m in league.get("matchups", [])
        }
        league_at = parts["league"].fetched_at if "league" in parts else None
        for key, part in parts.items():
            if key.startswith("matchup/"):
                read = Matchup.from_dict(part.data)
                listed = pairs.get(key)
                # The league page's live score when it was read after the matchup page.
                if listed and listed.score and league_at and league_at > part.fetched_at:
                    read = replace(read, score=listed.score)
                pairs[key] = read
        week = settings.current_week
        matchups = tuple(
            sorted(
                (m for m in pairs.values() if week is None or m.week == week),
                key=lambda m: m.teams,
            )
        )
        transactions = tuple(
            Transaction.from_dict(r) for r in (_data(parts, "transactions") or {}).get("rows", [])
        )
        calendar = Calendar.from_dict(parts["calendar"].data) if "calendar" in parts else None
        schedule = {
            date.fromisoformat(day): frozenset(teams_)
            for day, teams_ in ((_data(parts, "schedule") or {}).get("days") or {}).items()
        }
        fetched = {k: (p.fetched_at, p.source) for k, p in parts.items()}
        yahoo_week = {
            int(r["player"]["yahoo_id"]): r
            for r in (_data(parts, YAHOO_WEEK) or {}).get("rows", [])
        }
        pairings: dict[int, tuple[tuple[int, int], ...]] = {}
        for key, part in parts.items():
            if key.startswith("pairings/"):
                pairings[int(part.data["week"])] = tuple(
                    (int(m["teams"][0]), int(m["teams"][1]))
                    for m in part.data.get("matchups") or []
                )
        # This week's pairs are the league page's own.
        for week in {m.week for m in matchups}:
            pairings[week] = tuple(m.teams for m in matchups if m.week == week)
        return cls(
            settings=settings,
            calendar=calendar,
            teams=teams,
            rosters=rosters,
            available=available,
            matchups=matchups,
            transactions=transactions,
            players=players,
            schedule=schedule,
            fetched=fetched,
            yahoo_week=yahoo_week,
            pairings=pairings,
            lineups=lineups,
        )

    # ------------------------------------------------------------------ queries
    def team(self, team_id: int | None) -> Team | None:
        return next((t for t in self.teams if t.team_id == team_id), None)

    @property
    def my_team(self) -> Team | None:
        return self.team(self.settings.my_team_id)

    @property
    def my_roster(self) -> tuple[RosterSpot, ...]:
        mine = self.settings.my_team_id
        return self.rosters.get(mine, ()) if mine is not None else ()

    def matchup_of(self, team_id: int | None, week: int | None = None) -> Matchup | None:
        week = self.settings.current_week if week is None else week
        if team_id is None:
            return None
        return next(
            (m for m in self.matchups if team_id in m.teams and (week is None or m.week == week)),
            None,
        )

    def opponent_in(self, team_id: int | None, week: int) -> int | None:
        """``team_id``'s opponent in ``week`` as far as its pairs were read; None when not."""
        for a, b in self.pairings.get(week, ()):
            if team_id in (a, b):
                return b if team_id == a else a
        return None

    def weeks_unpaired(self, today: date, calendar: Calendar | None = None) -> list[int]:
        """The regular weeks after ``today``'s whose pairs were never read, or were read with
        none (a page read too soon): the reads the Season view's opponents still need. The
        season's calendar unless ``calendar`` is given (a private league's may not be saved yet)."""
        calendar = calendar or self.calendar
        if calendar is None:
            return []
        current = calendar.week_of(today)
        after = current.number if current is not None else (self.settings.current_week or 0)
        playoffs = self.first_playoff_week
        return [
            w.number
            for w in calendar.weeks
            if w.number > after
            and (playoffs is None or w.number < playoffs)
            and not self.pairings.get(w.number)
        ]

    @property
    def first_playoff_week(self) -> int | None:
        """The first playoff week: the settings page's, or the estimate from v3's settings; else
        (a private league whose settings page was not read) the first week read with no pairs
        when no later week lists any; None when not known."""
        known = self.settings.first_playoff_week
        if known is not None:
            return known
        paired = [w for w, pairs in self.pairings.items() if pairs]
        empty = [w for w, pairs in self.pairings.items() if not pairs]
        last = max(paired, default=0)
        return min((w for w in empty if w > last), default=None)

    @property
    def opponent(self) -> Team | None:
        """This week's opponent of my team."""
        mine = self.settings.my_team_id
        m = self.matchup_of(mine)
        if m is None or mine is None:
            return None
        other = m.opponent_of(mine)
        return self.team(other) or (Team(other, f"Team {other}") if other is not None else None)

    def current(self, today: date) -> Week | None:
        """The matchup week holding ``today``, when the calendar has been read."""
        return self.calendar.week_of(today) if self.calendar is not None else None

    def games(self, nba_team: str | None, days: Iterable[date]) -> int | None:
        """Games ``nba_team`` plays on ``days``; None when the schedule does not cover them all."""
        if not nba_team:
            return None
        count = 0
        for day in days:
            if day not in self.schedule:
                return None
            count += nba_team in self.schedule[day]
        return count

    @property
    def updated_at(self) -> datetime | None:
        times = [t for t, _ in self.fetched.values()]
        return max(times) if times else None


def _data(parts: Mapping[str, Part], key: str) -> Any:
    part = parts.get(key)
    return part.data if part is not None else None
