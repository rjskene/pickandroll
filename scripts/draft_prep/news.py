"""Draft-day news (#76): ESPN's injuries and Rotowire's headlines against the plan's players.

    python scripts/draft_day.py news 238174                    # read both pages, print the block
    python scripts/draft_day.py news 238174 --news-from DIR    # saved pages instead of the web

Basketball Monster folds news into its projections within hours; the sweep covers the gap
between the export and the draft. It lists every player among the top ``TOP`` by projected value
on the league's own scoring whose news item is newer than the projection file, with his status,
the item's date and its source, as the markdown block the scheduled session posts on the
league's issue at T-30. No player stats: names, statuses, dates and sources only, newest first.

The pages are public and read without signing in: ESPN's injuries page through the JSON it is
built from (``ESPN_URL``), and Rotowire's latest headlines (``ROTOWIRE_URL``; a headline carries
a day, not a time, so one dated the export's day counts as newer). ``--news-from DIR`` reads
``espn_injuries.json`` and ``rotowire_news.html`` from DIR instead. A page that does not read is
named in the block; the other still runs.

Names are matched to projection ids the way the session matches Yahoo's
(:func:`pickandroll.sources.matching.match_players`, with ``data/aliases.json``, where a source's
key such as ``espn:1234`` or a name may be pinned to a projection id). A name nothing matches is
listed, not dropped: it may be a projected player to pin.

A headline is not a projection. To act on an item, the user adds a games haircut to
``data/leagues/<id>/adjustments.json`` (applied at attach; ``status`` checks it) or sets
"out N weeks" on the board mid-draft (docs/DRAFT_DAY.md, "News sweep").
"""

from __future__ import annotations

import argparse
import html
import json
import re
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from pickandroll.optim.roster import yahoo_default_slots
from pickandroll.projections.schema import NINE_CAT, POINTS_CAT, Cat, fantasy_points
from pickandroll.projections.zscores import zscores
from pickandroll.sources.bbm import load_bbm
from pickandroll.sources.matching import load_aliases, match_players

HELP = "news <league>: ESPN injuries and Rotowire headlines newer than the projection file"
LEAGUE = True

#: The data behind https://www.espn.com/nba/injuries (public JSON, every team's list).
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
#: Rotowire's latest NBA headlines (public HTML).
ROTOWIRE_URL = "https://www.rotowire.com/basketball/news.php"
#: The saved pages ``--news-from`` reads.
ESPN_FILE = "espn_injuries.json"
ROTOWIRE_FILE = "rotowire_news.html"
#: A league's prepared haircuts (pickandroll.api.leagues.ADJUSTMENTS, read at attach).
ADJUSTMENTS = "adjustments.json"
#: Players the sweep looks at: the top this many by projected value.
TOP = 200
#: A headline's day is the US Eastern day; the block prints times in the draft's zone.
EASTERN = ZoneInfo("America/New_York")
PACIFIC = ZoneInfo("America/Los_Angeles")
#: A headline that reads like a game line ("Scores 31 points") is not printed: no player stats.
GAME_LINE = re.compile(
    r"\d+\s*(?:-|\s)?\s*(?:points?|pts|rebounds?|boards|assists?|dimes|steals?|blocks?|"
    r"threes|three-pointers|treys|minutes|turnovers?|fantasy)",
    re.IGNORECASE,
)
USER_AGENT = "Mozilla/5.0 (Macintosh) pickandroll-draft-day"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--news-from",
        metavar="DIR",
        help=f"news: read {ESPN_FILE} and {ROTOWIRE_FILE} from DIR instead of the web",
    )
    parser.add_argument(
        "--news-top",
        type=int,
        default=TOP,
        help=f"news: players looked at, the top N by projected value (default {TOP})",
    )


# --------------------------------------------------------------------------- the pages
@dataclass(frozen=True)
class Item:
    """One news item: ``key`` is the source's own id for the player (``espn:1234``)."""

    key: str
    name: str
    team: str
    status: str
    when: datetime
    source: str
    #: The source gives a day, not a time (Rotowire's headlines).
    day_only: bool = False


def _when(text: str) -> datetime:
    """ESPN's ``2026-10-17T19:01Z`` (seconds optional) as an aware datetime."""
    return datetime.fromisoformat(text).astimezone(UTC)


def parse_espn(text: str) -> list[Item]:
    """Every player on ESPN's injuries page: status (``Out``, ``Day-To-Day``), the injury and
    the estimated return where given, and the item's time."""
    items = []
    for team in json.loads(text).get("injuries") or []:
        for row in team.get("injuries") or []:
            athlete = row.get("athlete") or {}
            name = athlete.get("displayName") or ""
            if not name or not row.get("date"):
                continue
            links = " ".join(str(link.get("href", "")) for link in athlete.get("links") or [])
            found = re.search(r"/id/(\d+)", links)
            key = f"espn:{found.group(1)}" if found else f"espn:{row.get('id', name)}"
            details = row.get("details") or {}
            extra = [str(details["type"])] if details.get("type") else []
            if details.get("returnDate"):
                back = date.fromisoformat(str(details["returnDate"])[:10])
                extra.append(f"est. return {back:%b} {back.day}")
            status = str(row.get("status") or "listed")
            items.append(
                Item(
                    key=key,
                    name=str(name),
                    team=str((athlete.get("team") or {}).get("abbreviation") or ""),
                    status=status + (f" ({'; '.join(extra)})" if extra else ""),
                    when=_when(str(row["date"])),
                    source="ESPN",
                )
            )
    return items


_ROTO_FIELD = {
    "name": re.compile(r'news-update__player-link"[^>]*>([^<]+)<'),
    "href": re.compile(r'news-update__player-link"[^>]*href="[^"]*-(\d+)"'),
    "headline": re.compile(r'news-update__headline"[^>]*>([^<]+)<'),
    "day": re.compile(r'news-update__timestamp">([^<]+)<'),
    "team": re.compile(r'news-update__logo"[^>]*alt="([^"]*)"'),
}


def parse_rotowire(text: str) -> list[Item]:
    """Rotowire's latest headlines: the player, the headline (a game line is held back) and
    its day."""
    items = []
    for block in text.split('<div class="news-update">')[1:]:
        found = {k: rx.search(block) for k, rx in _ROTO_FIELD.items()}
        if not (found["name"] and found["headline"] and found["day"]):
            continue
        try:
            day = datetime.strptime(found["day"].group(1).strip(), "%B %d, %Y").replace(
                tzinfo=EASTERN
            )
        except ValueError:
            continue
        name = html.unescape(found["name"].group(1)).strip()
        headline = html.unescape(found["headline"].group(1)).strip()
        if GAME_LINE.search(headline):
            headline = "game line (not shown)"
        pid = found["href"].group(1) if found["href"] else name
        items.append(
            Item(
                key=f"rotowire:{pid}",
                name=name,
                team=html.unescape(found["team"].group(1)) if found["team"] else "",
                status=headline,
                when=day.astimezone(UTC),
                source="Rotowire",
                day_only=True,
            )
        )
    return items


def read_page(url: str, saved: Path | None) -> tuple[str | None, str | None]:
    """A page's text, from the web or a saved copy; otherwise ``None`` and why."""
    if saved is not None:
        try:
            return saved.read_text(encoding="utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"{saved} does not read ({exc})"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return None, str(getattr(exc, "reason", exc))


# --------------------------------------------------------------------------- the players
def league_values(data: Path, league: str, projections: pd.DataFrame) -> pd.Series:
    """Projected value on the league's own scoring, best first: total z over a pool of the
    league's drafted rosters (a points league's fantasy points, else its categories)."""
    # pickandroll.api loads the whole app: imported only when a command needs it.
    from pickandroll.api.leagues import league_cats, league_slots, load_settings

    settings = load_settings(data, league)
    slots = (
        league_slots(list(settings["roster"])) if settings.get("roster") else yahoo_default_slots()
    )
    pool = int(settings.get("num_teams") or 12) * len(slots)
    df = projections
    cats: Sequence[Cat] = league_cats(settings) or NINE_CAT
    if settings["scoring"] == "points":
        weights = {str(k).lower(): float(v) for k, v in settings["points"].items()}
        df = df.assign(**{Cat.FPTS.value: fantasy_points(df, weights)})
        cats = POINTS_CAT
    return zscores(df, cats, pool_size=pool)["total"].sort_values(ascending=False)


@dataclass
class Sweep:
    """What the block prints: the top players' items newer than the file, and the names that
    match no projected player."""

    rows: list[tuple[Item, str]]  # (item, projection id)
    unmatched: list[Item]
    read: dict[str, int]  # source -> items on its page
    failed: dict[str, str]  # source -> why its page did not read


def newer(item: Item, as_of: datetime) -> bool:
    if item.day_only:
        return item.when.astimezone(EASTERN).date() >= as_of.astimezone(EASTERN).date()
    return item.when > as_of


def sweep(
    items: Sequence[Item],
    projections: pd.DataFrame,
    top: Sequence[str],
    as_of: datetime,
    aliases: dict[str, str] | None = None,
) -> tuple[list[tuple[Item, str]], list[Item]]:
    """The items newer than ``as_of`` for players in ``top``, with their projection ids, newest
    first; and the newer items whose names match no projected player (ambiguous ones among
    them), in the same order."""
    fresh = sorted((i for i in items if newer(i, as_of)), key=lambda i: i.when, reverse=True)
    if not fresh:
        return [], []
    frame = pd.DataFrame(
        {"name": [i.name for i in fresh], "team": [i.team for i in fresh]},
        index=pd.Index([f"{n}#{i.key}" for n, i in enumerate(fresh)]),
    )
    # Aliases pin a source's key (espn:1234) or a name; the frame's index is unique per item.
    pins = dict(aliases or {})
    for n, i in enumerate(fresh):
        if i.key in pins:
            pins[f"{n}#{i.key}"] = pins[i.key]
    match = match_players(frame, projections[["player", "team"]], aliases=pins)
    wanted = set(top)
    rows, unmatched = [], []
    for n, item in enumerate(fresh):
        pid = match.mapping.get(f"{n}#{item.key}")
        if pid is None:
            unmatched.append(item)
        elif pid in wanted:
            rows.append((item, pid))
    return rows, unmatched


def markdown(
    league: str,
    file: str,
    as_of: datetime,
    top: int,
    result: Sweep,
    now: datetime | None = None,
) -> str:
    """The block for the league's issue: no projection numbers and no player stats."""
    now = now or datetime.now(UTC)

    def at(item: Item) -> str:
        if item.day_only:
            return f"{item.when.astimezone(EASTERN):%a %b} {item.when.astimezone(EASTERN).day}"
        local = item.when.astimezone(PACIFIC)
        return f"{local:%a %b} {local.day} {local:%H:%M %Z}"

    lines = [
        f"### News sweep, league {league}, {now.astimezone(PACIFIC):%a %Y-%m-%d %H:%M %Z}",
        "",
        (
            f"Projections `{file}`, exported {as_of.astimezone(PACIFIC):%a %Y-%m-%d %H:%M %Z}. "
            f"News newer than the export for the top {top} by projected value on the league's "
            "scoring, newest first. A headline is not a projection: a haircut goes in only where "
            "the news is clear (docs/DRAFT_DAY.md, News sweep)."
        ),
        "",
    ]
    if result.rows:
        lines += ["| player | status | date | source |", "|---|---|---|---|"]
        for item, _pid in result.rows:
            status = item.status.replace("|", "/")
            lines.append(f"| {item.name} | {status} | {at(item)} | {item.source} |")
    else:
        lines.append("No news newer than the export for these players.")
    lines.append("")
    if result.unmatched:
        names = ", ".join(f"{i.name} ({i.source})" for i in result.unmatched)
        lines += [
            (
                f"Names matching no projected player ({len(result.unmatched)}; pin a projected "
                f"one in data/aliases.json): {names}."
            ),
            "",
        ]
    read = [f"{src} {n} items" for src, n in result.read.items()]
    failed = [f"{src} NOT READ ({why})" for src, why in result.failed.items()]
    lines.append("Sources: " + "; ".join(read + failed) + ".")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- the command
def run(runbook: Any, args: argparse.Namespace) -> int:
    league = str(args.league)
    data: Path = runbook.DATA
    runbook.settings(league)  # the league folder must exist
    file = runbook.newest_projections()
    projections = load_bbm(data / file)
    df, as_of = projections.df, projections.as_of
    top_n = max(1, int(getattr(args, "news_top", TOP) or TOP))
    top = list(league_values(data, league, df).index[:top_n])
    saved = Path(args.news_from).expanduser() if getattr(args, "news_from", None) else None
    items: list[Item] = []
    result = Sweep(rows=[], unmatched=[], read={}, failed={})
    for source, url, name, parse in (
        ("ESPN injuries", ESPN_URL, ESPN_FILE, parse_espn),
        ("Rotowire headlines", ROTOWIRE_URL, ROTOWIRE_FILE, parse_rotowire),
    ):
        text, why = read_page(url, saved / name if saved else None)
        if text is None:
            result.failed[source] = why or "no page"
            runbook.say(f"ALERT news: {source} not read ({why})")
            continue
        try:
            found = parse(text)
        except (ValueError, KeyError, TypeError) as exc:
            result.failed[source] = f"does not parse: {exc}"
            runbook.say(f"ALERT news: {source} does not parse ({exc})")
            continue
        result.read[source] = len(found)
        items += found
    result.rows, result.unmatched = sweep(
        items, df, top, as_of, load_aliases(data / "aliases.json")
    )
    block = markdown(league, file, as_of, top_n, result)
    out = runbook.run_dir(league) / f"news_{datetime.now(UTC).astimezone():%Y-%m-%dT%H%M}.md"
    out.write_text(block)
    runbook.say(
        f"news: {len(result.rows)} items for the top {top_n}, {len(result.unmatched)} names "
        f"unmatched; saved {out.relative_to(runbook.ROOT)}"
    )
    print(block)
    return runbook.OK if result.read else runbook.ERROR


def on_status(runbook: Any, league: str) -> None:
    """The league's prepared haircuts, checked against the newest projections the way the
    attach will read them: an entry the attach would skip is an ALERT."""
    path = runbook.DATA / "leagues" / league / ADJUSTMENTS
    if not path.exists():
        return
    from pickandroll.api.adjustments import read_adjustments_file, resolve

    rows, problems = read_adjustments_file(path)
    try:
        df = load_bbm(runbook.DATA / runbook.newest_projections()).df
    except (runbook.Stop, OSError, ValueError) as exc:
        runbook.say(f"  ALERT {ADJUSTMENTS}: not checked ({exc})")
        return
    table, unmatched = resolve(rows, df, strict=False)

    def given(e: dict[str, Any]) -> str:
        if e.get("games_fraction") is not None:
            return f"{e['games_fraction']:g} of his games"
        return f"{e['games_out']:g} games out"

    names = ", ".join(f"{df.at[e['player_id'], 'player']} {given(e)}" for e in table)
    runbook.say(
        f"  {ADJUSTMENTS}: {len(table)} games haircuts applied at attach"
        + (f" ({names})" if names else "")
    )
    for line in problems + unmatched:
        runbook.say(f"  ALERT {ADJUSTMENTS}: {line}")
