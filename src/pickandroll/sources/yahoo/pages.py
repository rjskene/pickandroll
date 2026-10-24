"""Parsers for Yahoo's league pages, as served to anyone for a public league and as the user's
own Chrome sees them for a private one (the extension posts the page, docs/ADD_DROP.md).

Each parser takes the page's HTML and returns a season part's data (``pickandroll.season``):

* the league page ``/nba/<league>``: standings and this week's matchup pairs;
* a team page ``/nba/<league>/<team>``: the roster by slot;
* the players page ``/nba/<league>/players?status=A...``: available players, free agents and
  waivers with their clear date, percent rostered and started (with the day's change in the
  ``R_O`` "Research" view), adds and drops; in the ``S_PS7`` view, Yahoo's projection for the
  next seven days (``parse_projection_page``);
* a matchup page ``/nba/<league>/matchup?date=totals&week=<w>&mid1=<a>&mid2=<b>``: both
  teams' totals and games played (``mid1`` alone names the team's opponent that week). Without
  ``date=totals``, while games are live, Yahoo serves the Live tab, which names neither team;
* the players page in a season view (``S_S_<season>``, totals) and the player search
  ``/nba/<league>/playersearch?search=<name>``: every row's line with its owner
  (``parse_stat_lines``);
* the draft results ``/nba/<league>/draftresults``: every pick by round;
* the transactions page ``/nba/<league>/transactions``;
* the settings page ``/nba/<league>/settings``: the roster positions with the held slots
  (Yahoo's v3 settings leave those out), the lineup deadline and the playoff weeks
  (``parse_settings_page``, #107);
* Yahoo's buzz index ``/nba/buzzindex`` (every league's adds, drops and trades on a day, for
  the breakout flag): ``parse_buzz_page``.

The parsers find tables by their column labels rather than by position, so the stat view the
page shows (season totals, Yahoo's next-7-days projection, ...) does not matter to them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

from ...season.state import Player
from .html import Node, cells, parse, table_rows

_TEAM_POS = re.compile(r"^([A-Z]{2,4}) - ([A-Za-z,]+)$")
_PLAYER_HREF = re.compile(r"/nba/players/(\d+)(?:/|$)")
_TEAM_HREF = re.compile(r"/nba/(\d+)/(\d+)/?$")
_MATCHUP_HREF = re.compile(r"matchup\?week=(\d+)&(?:amp;)?mid1=(\d+)&(?:amp;)?mid2=(\d+)")
_WEEK = re.compile(r"Week (\d+) (?:stats may change|Matchups)")
_GAMES = re.compile(r"(\d+)\s*/\s*(\d+)\s*Games Played\s*(\d+)\s*/\s*(\d+)")
_ROUND = re.compile(r"^Round (\d+)$")
_PICK = re.compile(r"^(\d+)\.$")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CHANGE = re.compile(r"\(\s*([+-]?)\s*(\d+(?:\.\d+)?)\s*\)")
_NO_CHANGE = re.compile(r"\(\s*[–—-]\s*\)")
_CLEARS = re.compile(r"^W\s*\(\s*([A-Z][a-z]{2})\s+(\d{1,2})\s*\)")
_PLAYOFF_WEEKS = re.compile(r"Weeks?\s+([\d,\s]+(?:and\s+\d+)?)")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}

SITE = "https://basketball.fantasysports.yahoo.com/nba"


class PageError(ValueError):
    """A page that is not the page it was taken for (an empty body, a sign-in wall...)."""


# --------------------------------------------------------------------------- page kinds
def page_kind(url: str) -> tuple[str, dict[str, Any]]:
    """What a league page URL is: ``league`` (with ``matchup_week`` when it shows another
    week's pairs), ``team`` (with ``team_id``, and ``date`` when it shows that day's lineup),
    ``players`` (with its ``view`` and ``status`` filter), ``playersearch``, ``matchup``
    (``week``, ``teams``), ``draftresults``, ``transactions`` or ``settings``; with the
    ``league`` id."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "nba" or not parts[1].isdigit():
        raise PageError(f"not a Yahoo league page: {url}")
    league = parts[1]
    query = parse_qs(parsed.query)
    rest = parts[2:]
    if not rest:
        # ``?matchup_week=N`` shows week N's pairs: a schedule page, not this week's league page.
        week = (query.get("matchup_week") or [None])[0]
        if week and week.isdigit():
            return "league", {"league": league, "matchup_week": int(week)}
        return "league", {"league": league}
    if rest[0].isdigit() and len(rest) == 1:
        info: dict[str, Any] = {"league": league, "team_id": int(rest[0])}
        day = (query.get("date") or [None])[0]
        if day:
            try:
                info["date"] = date.fromisoformat(day)
            except ValueError as exc:
                raise PageError(f"a team page on no date it names: {url}") from exc
        return "team", info
    if rest[0] == "players":
        return "players", {
            "league": league,
            "view": (query.get("stat1") or [None])[0],
            "status": (query.get("status") or [None])[0],
        }
    if rest[0] == "playersearch":
        return "playersearch", {"league": league, "view": (query.get("stat1") or [None])[0]}
    if rest[0] == "matchup":
        week = (query.get("week") or [None])[0]
        teams = [int(v[0]) for k in ("mid1", "mid2") if (v := query.get(k))]
        return "matchup", {"league": league, "week": int(week) if week else None, "teams": teams}
    if rest[0] == "transactions":
        return "transactions", {"league": league}
    if rest[0] == "draftresults":
        return "draftresults", {"league": league}
    if rest[0] == "settings" and len(rest) == 1:
        return "settings", {"league": league}
    raise PageError(f"not a league page this module reads: {url}")


def week_label(html: str) -> int | None:
    """The matchup week a page shows (``Week 7 stats may change...`` on a team or matchup page,
    ``Week 7 Matchups`` on the league page)."""
    m = _WEEK.search(html)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- cells
def player_cell(cell: Node) -> Player | None:
    """The player in a roster or player-list cell: Yahoo id, name, NBA team, positions and the
    injury or availability code."""
    name_box = cell.find("div", cls="ysf-player-name") or cell
    link = name_box.find("a", attr="data-ys-playerid")
    if link is None:
        return None
    pid = int(link.get("data-ys-playerid") or 0)
    name = (link.get("title") or link.text()).strip()
    status = status_full = None
    flag = cell.find("span", cls="ysf-player-status")
    if flag is not None:
        inner = flag.find("span", attr="title") or flag
        status = inner.text() or None
        status_full = inner.get("title") or None
    team = None
    positions: tuple[str, ...] = ()
    for span in cell.find_all("span"):
        m = _TEAM_POS.match(span.text())
        if m:
            team, positions = m.group(1), tuple(p for p in m.group(2).split(",") if p)
            break
    return Player(pid, name, team, positions, status, status_full)


def _pct(text: str) -> tuple[float | None, float | None]:
    """``35% (+3)`` -> (35.0, 3.0); ``35% (–)`` -> (35.0, 0.0); ``35%`` -> (35.0, None)."""
    m = _PCT.search(text)
    if not m:
        return None, None
    value = float(m.group(1))
    c = _CHANGE.search(text)
    if c:
        change = float(c.group(2)) * (-1.0 if c.group(1) == "-" else 1.0)
    elif _NO_CHANGE.search(text):
        change = 0.0
    else:
        change = None
    return value, change


def _int(text: str) -> int | None:
    t = text.replace(",", "").strip()
    return int(t) if re.fullmatch(r"-?\d+", t) else None


def _float(text: str) -> float | None:
    t = text.replace(",", "").replace("$", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def clears_date(text: str, today: date) -> date | None:
    """``W (Oct 22)`` -> the waiver clear date, in the year that puts it nearest ``today``."""
    m = _CLEARS.match(text.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1)], int(m.group(2))
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    return min(candidates, key=lambda d: abs((d - today).days)) if candidates else None


#: Yahoo's icon font (the sort arrow), in Unicode's private use area.
_GLYPHS = re.compile("[\ue000-\uf8ff]")


def _column(labels: list[str], *names: str) -> int | None:
    """The column labelled ``name``, else the first whose label starts with it (``% Ros`` with
    the page's sort arrow after it); icon glyphs, which the sorted column's label carries
    (``Adds\ue004``), are ignored."""
    clean = [_GLYPHS.sub("", label).strip() for label in labels]
    for name in names:
        if name in clean:
            return clean.index(name)
        for i, label in enumerate(clean):
            if label.startswith(name + " "):
                return i
    return None


def _table_with(root: Node, *labels: str) -> tuple[list[str], list[Node]] | None:
    """The first table whose column labels include all of ``labels``."""
    for table in root.find_all("table"):
        cols, rows = table_rows(table)
        if all(_column(cols, label) is not None for label in labels):
            return cols, rows
    return None


def _title(root: Node) -> str:
    t = root.find("title")
    return t.text() if t is not None else ""


def _require(root: Node, what: str) -> None:
    if root.find("body") is None and root.find("table") is None:
        raise PageError(f"the {what} page came back empty (a private league, or signed out)")


# --------------------------------------------------------------------------- pages
def parse_team_page(html: str, team_id: int) -> dict[str, Any]:
    """A team page: the roster by slot as of the page's day, and the team's name."""
    root = parse(html)
    _require(root, "team")
    found = _table_with(root, "Pos", "Players")
    if found is None:
        raise PageError("no roster table on the team page")
    labels, rows = found
    pos_i, player_i = _column(labels, "Pos"), _column(labels, "Players")
    spots = []
    for row in rows:
        cs = cells(row)
        if player_i is None or pos_i is None or len(cs) <= max(pos_i, player_i):
            continue
        player = player_cell(cs[player_i])
        if player is None:
            continue
        label = cs[pos_i].find("span", attr="data-pos")
        slot = (label.get("data-pos") if label is not None else cs[pos_i].text()) or "BN"
        spots.append({"slot": slot, "player": player.to_dict()})
    title = _title(root).split(" | ")[0]
    name = title.split(" - ", 1)[1].strip() if " - " in title else None
    return {"team_id": team_id, "name": name, "spots": spots, "week": week_label(html)}


def lineup_rule(deadline: str | None) -> tuple[str | None, str | None]:
    """How often a lineup changes and from when, from the settings page's "Weekly Deadline"
    (``Daily - Today``: ``("daily", "today")``); ``(None, None)`` for a value not known."""
    text = (deadline or "").strip().lower()
    if text.startswith("daily"):
        return "daily", "today" if "today" in text else "tomorrow" if "tomorrow" in text else None
    if text.startswith("weekly"):
        return "weekly", None
    return None, None


def parse_settings_page(html: str) -> dict[str, Any]:
    """The settings page: the roster positions in order, held slots included (``IL``, ``IL+``,
    ``NA``: Yahoo's v3 settings leave them out), the lineup deadline as printed with what it
    means (:func:`lineup_rule`), the playoff weeks, whether an injured player can be added
    straight to an injury slot, and the bracket's rules (#172): the playoff tie-breaker as
    printed, whether the bracket reseeds each round, and whether the league has divisions.
    A row the page does not print is None."""
    root = parse(html)
    _require(root, "settings")
    rows: dict[str, str] = {}
    for tr in root.find_all("tr"):
        tds = tr.children_of("td")
        if len(tds) == 2:
            label = tds[0].text()
            if label.endswith(":"):
                rows.setdefault(label[:-1].strip().lower(), tds[1].text())
    positions = rows.get("roster positions")
    if not positions:
        raise PageError("no roster positions on the settings page")
    deadline = rows.get("weekly deadline") or None
    changes, effective = lineup_rule(deadline)
    playoffs = None
    m = _PLAYOFF_WEEKS.search(rows.get("playoffs") or "")
    if m:
        playoffs = [int(x) for x in re.findall(r"\d+", m.group(1))] or None
    direct = rows.get(
        "allow injured players from waivers or free agents to be added directly to injury slot"
    )
    tiebreak = rows.get("playoff tie-breaker")
    return {
        "roster": [x.strip() for x in positions.split(",") if x.strip()],
        "lineup_deadline": deadline,
        "lineup_changes": changes,
        "lineup_from": effective,
        "playoff_weeks": playoffs,
        "injured_add_to_slot": None if direct is None else direct.strip().lower() == "yes",
        "playoff_tiebreak": tiebreak.strip() if tiebreak else None,
        "playoff_reseeding": _yes_no(rows.get("playoff reseeding")),
        "divisions": _yes_no(rows.get("divisions")),
    }


def _yes_no(text: str | None) -> bool | None:
    """A settings row printed ``Yes`` or ``No``; None when not printed."""
    if text is None:
        return None
    return text.strip().lower() == "yes"


def parse_players_page(html: str, today: date) -> dict[str, Any]:
    """The players page filtered to available players (``status=A``, ``FA`` or ``W``): one row
    per player with his availability, clear date and ownership. Taken players (another
    status filter) are skipped."""
    root = parse(html)
    _require(root, "players")
    found = _table_with(root, "Players", "Roster Status")
    if found is None:
        raise PageError("no player table on the players page")
    labels, rows = found
    col = {
        "player": _column(labels, "Players"),
        "status": _column(labels, "Roster Status"),
        "ros": _column(labels, "% Ros"),
        "start": _column(labels, "% Start"),
        "adds": _column(labels, "Adds"),
        "drops": _column(labels, "Drops"),
    }
    out = []
    for row in rows:
        cs = cells(row)

        def text(key: str, cs: list[Node] = cs) -> str:
            i = col[key]
            return cs[i].text() if i is not None and i < len(cs) else ""

        i = col["player"]
        player = player_cell(cs[i]) if i is not None and i < len(cs) else None
        if player is None:
            continue
        status = text("status")
        if status == "FA":
            availability, clears = "FA", None
        elif status.startswith("W"):
            availability, clears = "W", clears_date(status, today)
        else:
            continue
        ros, ros_change = _pct(text("ros"))
        start, start_change = _pct(text("start"))
        out.append(
            {
                "player": player.to_dict(),
                "availability": availability,
                "clears": clears.isoformat() if clears else None,
                "pct_rostered": ros,
                "pct_rostered_change": ros_change,
                "pct_started": start,
                "pct_started_change": start_change,
                "adds": _int(text("adds")) if col["adds"] is not None else None,
                "drops": _int(text("drops")) if col["drops"] is not None else None,
            }
        )
    return {"rows": out}


def parse_buzz_page(html: str) -> dict[str, Any]:
    """Yahoo's buzz index for a day: every listed player with the percent of Yahoo's leagues that
    roster and start him and his adds, drops and trades across them, in the page's order (the
    sort the URL asked for)."""
    root = parse(html)
    _require(root, "buzz index")
    found = _table_with(root, "Player", "Adds", "Drops")
    if found is None:
        raise PageError("no table on the buzz index")
    labels, rows = found
    col = {
        "player": _column(labels, "Player"),
        "ros": _column(labels, "% Ros"),
        "start": _column(labels, "% Start"),
        "adds": _column(labels, "Adds"),
        "drops": _column(labels, "Drops"),
        "trades": _column(labels, "Trades"),
    }
    out = []
    for row in rows:
        cs = cells(row)

        def text(key: str, cs: list[Node] = cs) -> str:
            i = col[key]
            return cs[i].text() if i is not None and i < len(cs) else ""

        i = col["player"]
        player = player_cell(cs[i]) if i is not None and i < len(cs) else None
        if player is None:
            continue
        out.append(
            {
                "player": player.to_dict(),
                "pct_rostered": _pct(text("ros"))[0],
                "pct_started": _pct(text("start"))[0],
                "adds": _int(text("adds")),
                "drops": _int(text("drops")),
                "trades": _int(text("trades")),
            }
        )
    return {"rows": out}


#: Yahoo's stat columns, by their label with spaces and the projection's asterisk taken out.
_STAT_LABELS = {
    "GP": ("gp",),
    "FGM/A": ("fgm", "fga"),
    "FTM/A": ("ftm", "fta"),
    "3PTM": ("threes",),
    "PTS": ("pts",),
    "REB": ("reb",),
    "AST": ("ast",),
    "ST": ("stl",),
    "BLK": ("blk",),
    "TO": ("tov",),
}
#: The players page's view of Yahoo's projection for the next seven days.
PROJECTION_VIEW = "S_PS7"


def _stat_label(label: str) -> str:
    return re.sub(r"[\s*\ue000-\uf8ff]", "", label).upper()


def _stat_rows(
    labels: list[str], rows: list[Node]
) -> list[tuple[Player, list[Node], dict[str, float | None]]]:
    """Every player row of a stat table: the player, the row's cells and his stats in our names
    (``gp`` None when the table has no games column)."""
    cols = {_stat_label(label): i for i, label in enumerate(labels) if label}
    player_col = _column(labels, "Players")
    out = []
    for row in rows:
        cs = cells(row)
        player = (
            player_cell(cs[player_col]) if player_col is not None and player_col < len(cs) else None
        )
        if player is None:
            continue
        stats: dict[str, float | None] = {}
        for label, names in _STAT_LABELS.items():
            i = cols.get(label)
            text = cs[i].text() if i is not None and i < len(cs) else ""
            values = text.split("/") if len(names) == 2 else [text]
            for name, value in zip(names, values, strict=False):
                # "-": no games (Yahoo projects him none, or he has played none).
                stats[name] = 0.0 if value.strip() in ("-", "–") else _float(value)
        out.append((player, cs, stats))
    return out


def parse_projection_page(html: str) -> dict[str, Any]:
    """The players page in a projection view (``S_PS7``, Yahoo's next seven days): for every
    player row, his projected games (``gp``) and his totals over them, in our stat names.
    Whoever the rows are (available or taken), the projection is his."""
    root = parse(html)
    _require(root, "players")
    found = _table_with(root, "Players", "GP*") or _table_with(root, "Players", "GP")
    if found is None:
        raise PageError("no projection table on the players page")
    return {
        "rows": [
            {"player": player.to_dict(), **stats}
            for player, _, stats in _stat_rows(*found)
            if stats.get("gp") is not None
        ]
    }


def _minutes(text: str) -> float | None:
    """``31:30`` -> 31.5."""
    m = re.fullmatch(r"(\d+):(\d{2})", text.strip())
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def parse_stat_lines(html: str) -> dict[str, Any]:
    """The players page in a stat view (a season's totals, ``S_S_<season>``) or the player
    search: every row's line in our stat names with his minutes a game, and who has him (the
    fantasy team's id, or ``FA`` / ``W``). The search page prints no games column: its rows
    carry ``gp`` None."""
    root = parse(html)
    _require(root, "players")
    found = _table_with(root, "Players", "Roster Status", "PTS")
    if found is None:
        raise PageError("no stat table on the players page")
    labels, rows = found
    status_col, mpg_col = _column(labels, "Roster Status"), _column(labels, "MPG")
    out = []
    for player, cs, stats in _stat_rows(labels, rows):
        owner: int | None = None
        availability = None
        if status_col is not None and status_col < len(cs):
            cell = cs[status_col]
            link = next(
                (a for a in cell.find_all("a") if _TEAM_HREF.search(a.get("href") or "")), None
            )
            if link is not None:
                owner = int(_TEAM_HREF.search(link.get("href") or "").group(2))  # type: ignore[union-attr]
            elif cell.text() == "FA":
                availability = "FA"
            elif cell.text().startswith("W"):
                availability = "W"
        mpg = _minutes(cs[mpg_col].text()) if mpg_col is not None and mpg_col < len(cs) else None
        out.append(
            {
                "player": player.to_dict(),
                "team_id": owner,
                "availability": availability,
                "mpg": round(mpg, 2) if mpg is not None else None,
                **stats,
            }
        )
    return {"rows": out}


def parse_draft_results(html: str) -> dict[str, Any]:
    """The draft results by round: every pick's round, its number in the round and overall, the
    player and the fantasy team that made it, by name (the page links no team)."""
    root = parse(html)
    _require(root, "draft results")
    picks = []
    for table in root.find_all("table"):
        labels, rows = table_rows(table)
        m = _ROUND.match(labels[0]) if labels else None
        if m is None:
            continue
        number = int(m.group(1))
        for row in rows:
            cs = cells(row)
            if len(cs) < 3 or not (n := _PICK.match(cs[0].text())):
                continue
            link = cs[1].find("a", pred=lambda a: bool(_PLAYER_HREF.search(a.get("href") or "")))
            if link is None:
                continue
            pid = int(_PLAYER_HREF.search(link.get("href") or "").group(1))  # type: ignore[union-attr]
            team = positions = None
            span = cs[1].find("span")
            if span is not None and (tp := _TEAM_POS.match(span.text().strip("() "))):
                team, positions = tp.group(1), [p for p in tp.group(2).split(",") if p]
            picks.append(
                {
                    "round": number,
                    "in_round": int(n.group(1)),
                    "player": Player(pid, link.text(), team, tuple(positions or ())).to_dict(),
                    "team_name": cs[2].get("title") or cs[2].text(),
                }
            )
    if not picks:
        raise PageError("no picks on the draft results page")
    per_round = max(p["in_round"] for p in picks)
    for p in picks:
        p["pick"] = (p["round"] - 1) * per_round + p["in_round"]
    return {"picks": sorted(picks, key=lambda p: p["pick"])}


def parse_league_page(html: str) -> dict[str, Any]:
    """The league page: the standings (record, points for, waiver priority and budget, moves)
    and the week's matchup pairs, each with its live score when the matchups module prints one
    (categories won, or points)."""
    root = parse(html)
    _require(root, "league")
    found = _table_with(root, "Team", "W-L-T")
    if found is None:
        raise PageError("no standings on the league page")
    labels, rows = found
    col = {
        "rank": _column(labels, "Rank"),
        "team": _column(labels, "Team"),
        "wlt": _column(labels, "W-L-T"),
        "pts": _column(labels, "Pts"),
        "faab": _column(labels, "Waiver Bdgt"),
        "waiver": _column(labels, "Waiver"),
        "moves": _column(labels, "Moves"),
    }
    teams = []
    for row in rows:
        cs = cells(row)

        def text(key: str, cs: list[Node] = cs) -> str:
            i = col[key]
            return cs[i].text() if i is not None and i < len(cs) else ""

        i = col["team"]
        if i is None or i >= len(cs):
            continue
        link = next(
            (a for a in cs[i].find_all("a") if _TEAM_HREF.search(a.get("href") or "") and a.text()),
            None,
        )
        if link is None:
            continue
        team_id = int(_TEAM_HREF.search(link.get("href") or "").group(2))  # type: ignore[union-attr]
        wlt = [int(x) for x in re.findall(r"\d+", text("wlt"))]
        teams.append(
            {
                "team_id": team_id,
                "name": link.text(),
                "rank": _int(text("rank")),
                "wins": wlt[0] if len(wlt) == 3 else None,
                "losses": wlt[1] if len(wlt) == 3 else None,
                "ties": wlt[2] if len(wlt) == 3 else None,
                "points_for": _float(text("pts")) if col["pts"] is not None else None,
                "waiver_priority": _int(text("waiver")),
                "faab": _float(text("faab")) if col["faab"] is not None else None,
                "moves": _int(text("moves")),
            }
        )
    pairs: dict[tuple[int, tuple[int, int]], None] = {}
    for a in root.find_all("a"):
        m = _MATCHUP_HREF.search(a.get("href") or "")
        if m:
            pairs[(int(m.group(1)), (int(m.group(2)), int(m.group(3))))] = None
    # The matchups module: one item per pair, the two scores in the pair's order.
    scores: dict[tuple[int, tuple[int, int]], list[float]] = {}
    for li in root.find_all("li", attr="data-target"):
        m = _MATCHUP_HREF.search(li.get("data-target") or "")
        values = [_float(d.text()) for d in li.find_all("div", cls="Fz-lg")]
        if m and len(values) == 2 and None not in values:
            key = (int(m.group(1)), (int(m.group(2)), int(m.group(3))))
            scores[key] = [v for v in values if v is not None]
    matchups = [
        {"week": w, "teams": list(t), **({"score": scores[(w, t)]} if (w, t) in scores else {})}
        for w, t in pairs
    ]
    name = _title(root).split(" | ")[0].strip() or None
    return {"name": name, "teams": teams, "matchups": matchups, "week": week_label(html)}


def parse_pairings(html: str, week: int) -> dict[str, Any]:
    """The pairs of ``week`` from the league page shown for it (``?matchup_week=N``, #116): the
    schedule's source. A playoff week Yahoo has not seeded lists none."""
    matchups = [m for m in parse_league_page(html)["matchups"] if m["week"] == week]
    return {"week": week, "matchups": matchups}


def parse_matchup_page(
    html: str, week: int | None = None, pair: Sequence[int] | None = None
) -> dict[str, Any]:
    """A matchup page: the two teams (in the page's order), each one's totals by column, and the
    score lines (``vs``: categories won or points; a points league adds Yahoo's projections).
    ``pair``, the teams the URL asks for (``mid1``, and ``mid2`` when given), must be on it."""
    root = parse(html)
    _require(root, "matchup")
    found = _table_with(root, "Team", "FG%") or _table_with(root, "Team", "PTS")
    teams = _matchup_teams(root, found[1] if found is not None else [])
    if len(teams) != 2:
        raise PageError("the matchup page does not name two teams")
    asked = [int(t) for t in pair or ()]
    if not set(asked) <= set(teams):
        raise PageError(
            f"the matchup page shows teams {teams[0]} and {teams[1]};"
            f" its URL asks for {' and '.join(map(str, asked))}"
        )
    week = week if week is not None else week_label(html)
    if week is None:
        raise PageError("the matchup page does not say its week")
    totals: dict[str, dict[str, str]] = {}
    if found is not None:
        labels, rows = found
        for row in rows:
            cs = cells(row)
            link = next(
                (a for a in row.find_all("a") if _TEAM_HREF.search(a.get("href") or "")), None
            )
            if link is None:
                continue
            tid = int(_TEAM_HREF.search(link.get("href") or "").group(2))  # type: ignore[union-attr]
            totals[str(tid)] = {
                label: cs[i].text()
                for i, label in enumerate(labels)
                if label and label != "Team" and i < len(cs)
            }
    lines: dict[str, list[float]] = {}
    box = root.find("table", cls="M-a")
    if box is not None:
        for tr in box.find_all("tr"):
            tds, ths = tr.children_of("td"), tr.children_of("th")
            if len(tds) == 2 and ths:
                a, b = _float(tds[0].text()), _float(tds[1].text())
                if a is not None and b is not None:
                    lines[ths[0].text() or "vs"] = [a, b]
    score = lines.get("vs")
    out = {"week": week, "teams": teams, "totals": totals, "score": score, "lines": lines}
    if games := _games_played(root, teams):
        out["games"] = games
    if not totals and (sums := _roster_sums(root, teams)):
        out["roster_totals"] = sums
    return out


def _matchup_teams(root: Node, rows: Sequence[Node]) -> list[int]:
    """The matchup's two teams in the page's order: the header's (``#matchup-header``, the
    teams' names over the score), else the totals table's rows. Never the page's chrome: a
    signed-in page's navigation links to my team before either."""
    header = root.find("section", pred=lambda n: n.get("id") == "matchup-header")
    for scope in ([header] if header is not None else [], rows):
        teams: list[int] = []
        for node in scope:
            for a in node.find_all("a"):
                m = _TEAM_HREF.search(a.get("href") or "")
                if m and int(m.group(2)) not in teams:
                    teams.append(int(m.group(2)))
        if len(teams) == 2:
            return teams
    return []


def _games_played(root: Node, teams: list[int]) -> dict[str, dict[str, int]]:
    """Each team's games played and scheduled this week (``3/31 Games Played 2/32``: played over
    played and remaining), in the page's order of the teams."""
    box = root.find("div", pred=lambda n: n.get("id") == "remaining-games")
    m = _GAMES.search(box.text()) if box is not None else None
    if m is None:
        return {}
    a, b = teams
    return {
        str(a): {"played": int(m.group(1)), "scheduled": int(m.group(2))},
        str(b): {"played": int(m.group(3)), "scheduled": int(m.group(4))},
    }


def _roster_sums(root: Node, teams: list[int]) -> dict[str, dict[str, float]]:
    """Each team's week from the page's player table, summed by column: a points league's page
    prints no team totals. A player dropped during the week is not on the table."""
    table = root.find("table", pred=lambda n: (n.get("id") or "").startswith("statTable"))
    if table is None:
        return {}
    labels, rows = table_rows(table)
    players = [i for i, label in enumerate(labels) if label == "Player"]
    if len(players) != 2:
        return {}
    split = players[1]
    skip = {"Pos", "Player", ""}
    sums: dict[str, dict[str, float]] = {str(t): {} for t in teams}
    for row in rows:
        cs = cells(row)
        for i, label in enumerate(labels):
            if label in skip or i >= len(cs):
                continue
            value = _float(cs[i].text())
            if value is None:
                continue
            side = sums[str(teams[i >= split])]
            side[label] = round(side.get(label, 0.0) + value, 4)
    return sums


def parse_transactions_page(html: str) -> dict[str, Any]:
    """The league's recent transactions, newest first: one row per player moved, an add and its
    drop sharing a ``group``."""
    root = parse(html)
    _require(root, "transactions")
    table = root.find("table", cls="Tst-transaction-table")
    rows_out: list[dict[str, Any]] = []
    if table is None:
        return {"rows": rows_out}
    for group, tr in enumerate(tr for tr in table.find_all("tr") if tr.children_of("td")):
        tds = tr.children_of("td")
        if len(tds) < 3:
            continue
        kinds = [_kind(s.get("title") or "") for s in tds[0].find_all("span", attr="title")]
        team_link = tds[-1].find("a", cls="Tst-team-name")
        team_id = team_name = None
        if team_link is not None:
            m = _TEAM_HREF.search(team_link.get("href") or "")
            team_id = int(m.group(2)) if m else None
            team_name = team_link.text() or None
        stamp = tds[-1].find("span", cls="F-timestamp")
        when = stamp.text() if stamp is not None else None
        moves = [d for d in tds[1].find_all("div") if d.find("a", pred=_is_player_link)]
        for n, div in enumerate(moves):
            link = div.find("a", pred=_is_player_link)
            pid = int(_PLAYER_HREF.search(link.get("href") or "").group(1))  # type: ignore[union-attr]
            pos = div.find("span", cls="F-position")
            team, positions = None, ()
            if pos is not None and (m := _TEAM_POS.match(pos.text())):
                team, positions = m.group(1), tuple(m.group(2).split(","))
            inj = div.find("span", cls="F-injury")
            detail_node = div.find("h6")
            detail = detail_node.text() if detail_node is not None else None
            kind = kinds[n] if n < len(kinds) and kinds[n] else _kind_from_detail(detail)
            player = Player(
                pid,
                link.text(),  # type: ignore[union-attr]
                team,
                positions,
                inj.text() if inj is not None else None,
                inj.get("title") if inj is not None else None,
            )
            rows_out.append(
                {
                    "kind": kind,
                    "player": player.to_dict(),
                    "team_id": team_id,
                    "team_name": team_name,
                    "detail": detail,
                    "when": when,
                    "group": group,
                }
            )
    return {"rows": rows_out}


def _is_player_link(node: Node) -> bool:
    return bool(_PLAYER_HREF.search(node.get("href") or "")) and "playernote" not in node.classes


def _kind(title: str) -> str | None:
    t = title.lower()
    if "added" in t:
        return "add"
    if "dropped" in t:
        return "drop"
    if "trade" in t:
        return "trade"
    return None


def _kind_from_detail(detail: str | None) -> str:
    d = (detail or "").lower()
    if d.startswith("to "):
        return "drop"
    if "trade" in d:
        return "trade"
    return "add"
