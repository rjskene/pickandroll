"""The weekly recorder's reads and files (docs/ADD_DROP.md phase 6, #97): what
``POST /seasons/{league}/record`` reads for a finished week and where the record goes.

A public league's week comes from its public pages, read when the week is recorded:

* the league page, for the standings as of the week's end;
* one matchup page per pair, ``matchup?date=totals&week=<w>&mid1=<team>`` (the page names the
  opponent), for each team's totals, games played and result;
* the draft results, once per league (kept as the season's ``draft`` part);
* the players page in the season's totals view (``S_S_<season>``): the taken players until a
  short page, then the available ones by preseason rank (a dropped pick), then a player search
  for each drafted player still not found (the search page prints no games column: his games
  come from the same search in the averages view).

A private league's league page, matchup pages and draft results are the pages the extension
posted from the user's Chrome; until it has posted them for the week, the route answers 409 with
the pages still needed. Its players' lines are NBA statistics, the same in every league, so they
come from a public league's pages; who has each player comes from the private league's own
rosters.

Records live in ``data/leagues/<id>/season/weeks/<week>.json`` (never committed).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..season import EXTENSION, PUBLIC, Part, SeasonSettings, Week, unpaired_matchups
from ..season import record as rec
from ..sources.yahoo import pages, public
from .season_week import NBA_TZ

WEEKS = "weeks"
DRAFT = "draft"
PAGE_ROWS = public.PAGE_ROWS
#: The taken players' pages read at most (a 16-spot league rosters 192 players: 8 pages).
TAKEN_PAGES = 12
#: The available players' pages read by preseason rank, for the drafted players since dropped.
AVAILABLE_PAGES = 8
#: The player searches at most, per league, for the drafted players neither sweep found.
LOOKUPS = 25
#: How long after a week its moves are looked for in the transactions pages read (#126): a page
#: lists the latest few dozen, so a later one has nothing of the week a nearer one lacked.
MOVES_READ_AFTER = timedelta(days=7)


class NeedsPages(Exception):
    """A private league's week lacks pages only the user's Chrome can read."""

    def __init__(self, urls: list[str]) -> None:
        super().__init__(f"{len(urls)} pages needed")
        self.urls = urls


# --------------------------------------------------------------------------- urls
def opponent_url(league: str, week: int, team: int, other: int | None = None) -> str:
    """A matchup page by one team (Yahoo finds its opponent), or by the pair."""
    return public.matchup_url(league, week, [team] if other is None else [team, other])


def draft_url(league: str) -> str:
    return f"{public.SITE}/{league}/draftresults"


def season_year(week: Week) -> int:
    """The season a week belongs to, as Yahoo names its stat views (2026 for 2026-27)."""
    return week.start.year if week.start.month >= 7 else week.start.year - 1


def lines_url(league: str, status: str, offset: int, year: int) -> str:
    return (
        f"{public.SITE}/{league}/players?status={status}&pos=P&stat1=S_S_{year}"
        f"&sort=OR&sdir=1&count={offset}"
    )


def search_url(league: str, name: str, view: str) -> str:
    return f"{public.SITE}/{league}/playersearch?search={quote(name)}&stat1={view}"


# --------------------------------------------------------------------------- files
def weeks_dir(season_folder: Path) -> Path:
    return season_folder / WEEKS


def record_path(season_folder: Path, week: int) -> Path:
    return weeks_dir(season_folder) / f"{week}.json"


def load_record(season_folder: Path, week: int) -> dict[str, Any] | None:
    try:
        return json.loads(record_path(season_folder, week).read_text())
    except FileNotFoundError:
        return None


def write_record(season_folder: Path, record: Mapping[str, Any]) -> Path:
    path = record_path(season_folder, int(record["week"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
    tmp.replace(path)
    return path


def records(season_folder: Path) -> list[dict[str, Any]]:
    """Every recorded week, in week order."""
    out = []
    for path in weeks_dir(season_folder).glob("*.json"):
        if path.stem.isdigit():
            out.append(json.loads(path.read_text()))
    return sorted(out, key=lambda r: int(r["week"]))


# --------------------------------------------------------------------------- the week
def week_to_record(calendar_weeks: Sequence[Week], today: date, number: int | None) -> Week:
    """The week ``number``, or the latest one over by ``today``; ValueError when it is not
    over (a week is recorded once its last day has passed, US Eastern)."""
    if number is not None:
        week = next((w for w in calendar_weeks if w.number == number), None)
        if week is None:
            raise LookupError(f"no week {number} in the calendar")
        if week.end >= today:
            raise ValueError(
                f"week {number} ends on {week.end.isoformat()}: it is recorded once over"
            )
        return week
    over = [w for w in calendar_weeks if w.end < today]
    if not over:
        raise ValueError("no week is over yet")
    return over[-1]


def _et_date(at: datetime) -> date:
    return at.astimezone(NBA_TZ).date()


def through(read_at: datetime) -> date:
    """The last NBA day a read includes whole: the day before it was read (US Eastern)."""
    return _et_date(read_at) - timedelta(days=1)


def after_week(at: datetime, week: Week) -> bool:
    return _et_date(at) > week.end


# --------------------------------------------------------------------------- reads
@dataclass
class Inputs:
    #: The league page's standings rows and when the page was read.
    standings: list[dict[str, Any]] | None
    standings_at: datetime | None
    #: The week's matchup pages, parsed.
    matchups: list[dict[str, Any]]
    #: The draft's picks (``pages.parse_draft_results``), and whether they were read just now.
    picks: list[dict[str, Any]] | None
    picks_read: bool
    #: Every team of the league.
    teams: list[int]
    source: str
    missing: dict[str, Any] = field(default_factory=dict)


Fetch = Callable[[str], str]


def public_inputs(
    league: str, week: Week, fetch: Fetch, now: datetime, picks: list[dict[str, Any]] | None
) -> Inputs:
    """A public league's standings, its week's matchups (one page per pair) and, when the season
    has none yet, its draft."""
    page = pages.parse_league_page(fetch(public.league_url(league)))
    teams = [int(t["team_id"]) for t in page["teams"]]
    matchups: list[dict[str, Any]] = []
    covered: set[int] = set()
    for team in teams:
        if team in covered:
            continue
        m = pages.parse_matchup_page(fetch(opponent_url(league, week.number, team)), week.number)
        if team not in m["teams"] or int(m["week"]) != week.number:
            raise pages.PageError(f"the matchup page for team {team} is not its week {week.number}")
        matchups.append(m)
        covered |= set(m["teams"])
    read = picks is None
    if read:
        picks = pages.parse_draft_results(fetch(draft_url(league)))["picks"]
    missing = {"teams": sorted(set(teams) - covered)}
    return Inputs(page["teams"], now, matchups, picks, read, teams, PUBLIC, missing)


def private_inputs(
    league: str, week: Week, parts: Mapping[str, Part], settings: SeasonSettings
) -> Inputs:
    """A private league's week from the pages the extension posted after the week's end;
    :class:`NeedsPages` names the ones still to open in the user's Chrome."""
    needs: list[str] = []
    lg = parts.get("league")
    standings = standings_at = None
    if lg is not None and after_week(lg.fetched_at, week):
        standings, standings_at = lg.data.get("teams") or [], lg.fetched_at
    else:
        needs.append(public.league_url(league))
    teams = [int(t["team_id"]) for t in (lg.data.get("teams") or [])] if lg is not None else []
    teams = teams or list(range(1, settings.num_teams + 1))
    prefix = f"matchup/{week.number}/"
    misread = unpaired_matchups(parts)
    week_pages = {k: p for k, p in parts.items() if k.startswith(prefix) and k not in misread}
    fresh = [p.data for p in week_pages.values() if after_week(p.fetched_at, week)]
    covered = {int(t) for m in fresh for t in m["teams"]}
    # The week's pairs read before its end name both teams of a page still to read.
    known = [
        tuple(int(t) for t in p.data["teams"])
        for _, p in sorted(week_pages.items())
        if not after_week(p.fetched_at, week)
    ]
    for a, b in known:
        if a not in covered and b not in covered:
            needs.append(opponent_url(league, week.number, a, b))
            covered |= {a, b}
    needs += [opponent_url(league, week.number, t) for t in teams if t not in covered]
    draft = parts.get(DRAFT)
    if draft is None:
        needs.append(draft_url(league))
    if needs:
        raise NeedsPages(needs)
    return Inputs(
        standings,
        standings_at,
        sorted(fresh, key=lambda m: sorted(m["teams"])),
        draft.data["picks"] if draft is not None else None,
        False,
        teams,
        EXTENSION,
    )


def _games(totals: Mapping[str, Any], averages: Mapping[str, Any]) -> float | None:
    """His games from a season's totals and averages: the largest total over its average."""
    best = max(
        (s for s in ("fga", "pts", "reb", "fta", "ast") if (averages.get(s) or 0) > 0),
        key=lambda s: totals.get(s) or 0.0,
        default=None,
    )
    if best is None:
        return 0.0 if all(not totals.get(s) for s in ("fga", "pts", "reb")) else None
    return float(round((totals.get(best) or 0.0) / averages[best]))


def read_lines(
    source: str, wanted: Mapping[int, str], fetch: Fetch, year: int
) -> tuple[dict[int, dict[str, Any]], dict[str, int]]:
    """Season-to-date lines of the ``wanted`` players (id to name) from league ``source``'s
    players pages, and how many pages each sweep read."""
    found: dict[int, dict[str, Any]] = {}
    count = {"taken": 0, "available": 0, "searches": 0}
    for status, kind, limit in (("T", "taken", TAKEN_PAGES), ("A", "available", AVAILABLE_PAGES)):
        for n in range(limit):
            if not set(wanted) - set(found):
                break
            rows = pages.parse_stat_lines(fetch(lines_url(source, status, n * PAGE_ROWS, year)))[
                "rows"
            ]
            count[kind] += 1
            for r in rows:
                found.setdefault(int(r["player"]["yahoo_id"]), r)
            if len(rows) < PAGE_ROWS:
                break
    for pid in [p for p in wanted if p not in found][:LOOKUPS]:

        def row(view: str, pid: int = pid) -> dict[str, Any] | None:
            html = fetch(search_url(source, wanted[pid], view))
            rows = pages.parse_stat_lines(html)["rows"]
            return next((r for r in rows if int(r["player"]["yahoo_id"]) == pid), None)

        count["searches"] += 1
        totals = row(f"S_S_{year}")
        if totals is None:
            continue
        averages = row(f"S_AS_{year}") or {}
        found[pid] = {**totals, "gp": _games(totals, averages)}
    return found, count


def transaction_pages(
    snapshots: Path, week: Week, current: Part | None
) -> list[tuple[date, list[dict[str, Any]]]]:
    """Every transactions page read from the day before ``week`` to :data:`MOVES_READ_AFTER`
    after it, with the day (US Eastern) each was read: each snapshot's (named by its time in
    UTC), then the season's own part (``current``)."""
    out: list[tuple[date, list[dict[str, Any]]]] = []
    first = (week.start - timedelta(days=1)).strftime("%Y%m%d")
    last = (week.end + MOVES_READ_AFTER).strftime("%Y%m%d")
    for path in sorted(snapshots.glob("*.json")) if snapshots.exists() else []:
        if not first <= path.name[:8] <= last:
            continue
        try:
            part = (json.loads(path.read_text()).get("parts") or {}).get("transactions")
        except ValueError:
            continue
        if part and part.get("fetched_at"):
            at = datetime.fromisoformat(part["fetched_at"])
            out.append((_et_date(at), list((part.get("data") or {}).get("rows") or [])))
    if current is not None:
        out.append((_et_date(current.fetched_at), list((current.data or {}).get("rows") or [])))
    return out


def assemble(
    league: str,
    week: Week,
    settings: SeasonSettings,
    inputs: Inputs,
    lines: Mapping[int, Mapping[str, Any]] | None,
    lines_at: datetime | None,
    lines_from: str | None,
    owners: Mapping[int, int | str | None] | None,
    owners_at: datetime | None,
    transactions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """The week's record from what was read (``season.record.settle`` stamps it)."""
    points = settings.scoring == "points"
    teams, matchups = rec.week_teams(inputs.matchups, settings.cats, points)
    missing: dict[str, Any] = dict(inputs.missing)
    standings = None
    if inputs.standings is not None and inputs.standings_at is not None:
        standings = {
            "read_at": inputs.standings_at.isoformat(),
            "through": through(inputs.standings_at).isoformat(),
            "teams": rec.standings(inputs.standings),
        }
    else:
        missing["standings"] = "not read"
    players = None
    if inputs.picks is not None:
        picks, unmatched = rec.draft_teams(inputs.picks, inputs.standings or [])
        missing["draft_teams"] = unmatched
        if lines is not None and lines_at is not None:
            rows, gone = rec.drafted_lines(picks, lines, owners)
            players = {
                "read_at": lines_at.isoformat(),
                "through": through(lines_at).isoformat(),
                "from": lines_from,
                "owners": "rosters" if owners is not None else "pages",
                **({"owners_read_at": owners_at.isoformat()} if owners_at else {}),
                "rows": rows,
            }
            missing["players"] = gone
        else:
            missing["players"] = "no public league to read the lines from"
    else:
        missing["players"] = "no draft read"
    return rec.week_record(
        league,
        week,
        settings,
        teams=teams,
        matchups=matchups,
        standings_=standings,
        players=players,
        missing=missing,
        sources={"pages": inputs.source, **({"players": lines_from} if lines_from else {})},
        transactions=transactions,
    )
