"""The season view's breakout flag (docs/ADD_DROP.md phase 4, #95): its inputs, the flag of every
available player in a league, and the day's digest across leagues.

The inputs and where they are kept:

* Yahoo's buzz index (every league's adds, drops and trades on a day), one file per NBA day
  (US Eastern) in ``data/leagues/_shared/season/buzz/<day>.json`` holding the latest read:
  today's is read again past :data:`BUZZ_MAX_AGE`, yesterday's once more after the day ends,
  for its final count. The file also keeps every available player's Yahoo-wide adds seen that
  day in any league's pool (the players page's ``R_O`` view): the adds history the surge's
  baseline needs. The counts are kept by the hour they were read (US Eastern; ``24`` for a read
  after the day ended), so a morning's adds compare with earlier mornings' (#97).
* ESPN's injury report, ``data/leagues/_shared/season/injuries.json``, read again after
  :data:`INJURIES_MAX_AGE`.
* Basketball Monster's rest-of-season export (the season view's) and its past-days rankings
  exports, ``data/bbm_actual_7d_*`` and ``data/bbm_actual_14d_*`` (``scripts/draft_day.py
  past-days``), not read when older than :data:`PAST_DAYS_MAX_AGE`.

A public league's refresh reads the first two; so does a private league's extras job, and the
extension's snapshot adds its pool's adds. The flag is computed when the view or the digest asks,
from whichever inputs are newest (the exports land from Chrome on their own clock), and cached
per input.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from ..optim.roster import yahoo_default_slots
from ..projections.schema import NINE_CAT, POINTS_CAT, Cat, fantasy_points
from ..projections.zscores import zscores
from ..season import Available, Season
from ..season import flags as fl
from ..sources.bbm import PROJECTION_SUFFIXES
from ..sources.bbm.parse import normalize_bbm, read_bbm_export
from ..sources.injuries import ESPN_INJURIES_URL, Listed, parse_injuries
from ..sources.matching import load_aliases, match_players
from ..sources.yahoo import pages, public
from . import leagues
from . import season_week as sw

SEASON = "season"
BUZZ_DIR = "buzz"
INJURIES = "injuries.json"
#: A refresh reads the buzz index and the injury report again past these.
BUZZ_MAX_AGE = timedelta(hours=1)
INJURIES_MAX_AGE = timedelta(hours=1)
#: The past-days exports by window, as ``draft_day.py past-days`` and ``sources.bbm.fetch`` save
#: them.
PAST_DAYS_PREFIX = "bbm_actual_"
PAST_DAYS: Mapping[int, str] = {d: f"{PAST_DAYS_PREFIX}{d}d_*" for d in (7, 14)}
PAST_DAYS_MAX_AGE = timedelta(days=3)
#: The earlier days of adds the surge's baseline reads.
HISTORY_DAYS = 14
#: The digest says an input is stale past these.
BUZZ_STALE = timedelta(hours=12)
INJURIES_STALE = timedelta(hours=12)

#: An earlier day's count read at most this many hours before today's hour stands as that
#: day's count at the same time; else its final count is scaled to the share of the day gone.
SAME_HOUR_WINDOW = 2
#: The bucket of a read made after the day ended: its final count.
FINAL_HOUR = 24

_files = threading.Lock()


# --------------------------------------------------------------------------- the files
def shared_dir(data_dir: Path) -> Path:
    return data_dir / leagues.LEAGUES_DIR / leagues.SHARED / SEASON


def buzz_path(data_dir: Path, day: date) -> Path:
    return shared_dir(data_dir) / BUZZ_DIR / f"{day.isoformat()}.json"


def injuries_path(data_dir: Path) -> Path:
    return shared_dir(data_dir) / INJURIES


def _read(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(body, separators=(",", ":")))
    tmp.replace(path)


def read_hour(day: date, at: datetime) -> int:
    """The hour of ``day`` (US Eastern) a read at ``at`` belongs to: 0 to 23, or
    :data:`FINAL_HOUR` once the day is over."""
    local = at.astimezone(sw.NBA_TZ)
    return local.hour if local.date() <= day else FINAL_HOUR


def record_adds(
    data_dir: Path,
    day: date,
    adds: Mapping[int, int],
    *,
    buzz: list[dict[str, Any]] | None = None,
    read_at: datetime | None = None,
    at: datetime | None = None,
) -> None:
    """Merge Yahoo-wide ``adds`` by Yahoo id into ``day``'s file (a day's count only grows, so
    the larger stands), and into the hour they were read at (``at``, else ``read_at``); with
    ``buzz``, the day's buzz index as read at ``read_at``."""
    when = at or read_at
    with _files:
        path = buzz_path(data_dir, day)
        body = _read(path) or {}
        kept: dict[str, int] = dict(body.get("adds") or {})
        for yid, n in adds.items():
            kept[str(yid)] = max(int(n), int(kept.get(str(yid), 0)))
        body = {**body, "day": day.isoformat(), "adds": kept}
        if when is not None and adds:
            hours = dict(body.get("hours") or {})
            hour = f"{read_hour(day, when):02d}"
            bucket = dict(hours.get(hour) or {})
            for yid, n in adds.items():
                bucket[str(yid)] = max(int(n), int(bucket.get(str(yid), 0)))
            hours[hour] = bucket
            body["hours"] = hours
        if buzz is not None:
            body |= {"rows": buzz, "read_at": read_at.isoformat() if read_at else None}
        _write(path, body)


def pool_adds(season: Season, today: date) -> dict[int, int]:
    """The Yahoo-wide adds of the league's available players read today (US Eastern)."""
    out = {}
    for a in season.available:
        if a.adds is not None and _seen_today(a, today):
            out[a.player.yahoo_id] = a.adds
    return out


def _buzz_due(data_dir: Path, day: date, today: date, now: datetime) -> bool:
    """Whether to read ``day``'s buzz index: today's when the kept read is older than
    :data:`BUZZ_MAX_AGE`, yesterday's until it was read after the day ended (its final count)."""
    read_at = _when((_read(buzz_path(data_dir, day)) or {}).get("read_at"))
    if read_at is None:
        return True
    if day < today:
        return read_at.astimezone(sw.NBA_TZ).date() <= day
    return now - read_at > BUZZ_MAX_AGE


def read_inputs(data_dir: Path, fetch: public.Fetch, today: date, now: datetime) -> dict[str, str]:
    """The buzz index of today and yesterday when due (:func:`_buzz_due`) and ESPN's injury
    report when the kept one is older than :data:`INJURIES_MAX_AGE`. Returns what failed, by
    input; a failure never stops the refresh that asked."""
    errors: dict[str, str] = {}
    for day in (today - timedelta(days=1), today):
        if not _buzz_due(data_dir, day, today, now):
            continue
        try:
            rows = pages.parse_buzz_page(fetch(public.buzz_url(day)))["rows"]
            adds = {r["player"]["yahoo_id"]: r["adds"] for r in rows if r.get("adds") is not None}
            record_adds(data_dir, day, adds, buzz=rows, read_at=now, at=now)
        except Exception as exc:  # noqa: BLE001 - a flag input is not worth a failed refresh
            errors[f"buzz index {day.isoformat()}"] = f"{type(exc).__name__}: {exc}"
    kept = _read(injuries_path(data_dir)) or {}
    read_at = _when(kept.get("read_at"))
    if read_at is None or now - read_at > INJURIES_MAX_AGE:
        try:
            listed = parse_injuries(fetch(ESPN_INJURIES_URL))
            _write(
                injuries_path(data_dir),
                {"read_at": now.isoformat(), "players": [x.to_dict() for x in listed]},
            )
        except Exception as exc:  # noqa: BLE001 - a flag input is not worth a failed refresh
            errors["injury report"] = f"{type(exc).__name__}: {exc}"
    return errors


def _when(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text)) if text else None
    except ValueError:
        return None


def stamp(data_dir: Path, today: date) -> tuple[Any, ...]:
    """What the flags depend on beyond a league's own state: the kept days of the buzz index,
    the injury report and the Basketball Monster files, with their times."""

    def mtime(path: Path | None) -> tuple[str, int] | None:
        try:
            return (path.name, path.stat().st_mtime_ns) if path is not None else None
        except OSError:
            return None

    days = [today - timedelta(days=i) for i in range(HISTORY_DAYS + 1)]
    return (
        tuple(mtime(buzz_path(data_dir, d)) for d in days),
        mtime(injuries_path(data_dir)),
        mtime(sw._latest(data_dir, sw.BBM_ROS)),
        tuple(mtime(sw._latest(data_dir, (p,))) for p in PAST_DAYS.values()),
    )


# --------------------------------------------------------------------------- the inputs
def _past_frame(path: Path) -> pd.DataFrame:
    """A past-days export: Basketball Monster's sheet, or a CSV with the sheet's columns."""
    if path.suffix.lower() == ".csv":
        return normalize_bbm(pd.read_csv(path))
    return normalize_bbm(read_bbm_export(path))


def _per_game_minutes(row: pd.Series) -> float | None:
    games = float(row.get("games") or 0.0)
    return float(row.get("minutes") or 0.0) / games if games > 0 else None


def _usage(row: pd.Series) -> float | None:
    v = pd.to_numeric(row.get("usage"), errors="coerce")
    return None if v is None or pd.isna(v) else float(v)


def _hours(body: Mapping[str, Any]) -> list[tuple[int, dict[str, int]]]:
    return sorted((int(h), dict(c)) for h, c in (body.get("hours") or {}).items())


def at_hour(body: Mapping[str, Any], key: str, hour: int) -> tuple[float, bool] | None:
    """A day's count for player ``key`` as of ``hour`` and whether it was read then: its latest
    read at or before the hour, within :data:`SAME_HOUR_WINDOW` of it; else its last count
    scaled to the share of the time to its read gone by the hour (a file kept before the hours
    were holds final counts); None when the day never saw him."""
    seen = [(h, counts[key]) for h, counts in _hours(body) if key in counts]
    before = [x for x in seen if x[0] <= hour]
    if before and hour - before[-1][0] <= SAME_HOUR_WINDOW:
        return float(before[-1][1]), True
    last = (body.get("adds") or {}).get(key)
    if last is None:
        return None
    span = seen[-1][0] + 0.5 if seen and seen[-1][0] < FINAL_HOUR else FINAL_HOUR
    return float(last) * min(1.0, (hour + 0.5) / span), False


def _buzz(
    data_dir: Path, today: date, now: datetime | None = None
) -> tuple[dict[int, list[float]], dict[int, int], dict[int, int], dict[str, Any]]:
    """The adds history before today by player, each earlier day's count as of the hour his adds
    were read today (:func:`at_hour`), today's buzz-index rank and adds by player, and what was
    kept."""
    body = _read(buzz_path(data_dir, today)) or {}
    rows = body.get("rows") or []
    rank = {int(r["player"]["yahoo_id"]): i for i, r in enumerate(rows, 1)}
    adds = {int(k): int(v) for k, v in (body.get("adds") or {}).items()}
    # The hour each player's count was last read today; a file kept before the hours were, the
    # hour of now.
    fallback = read_hour(today, now) if now is not None else FINAL_HOUR - 1
    latest: dict[str, int] = {}
    for h, counts in _hours(body):
        for key in counts:
            latest[key] = h
    history: dict[int, list[float]] = {}
    days = []
    same = 0
    for i in range(HISTORY_DAYS, 0, -1):
        earlier = _read(buzz_path(data_dir, today - timedelta(days=i)))
        if not earlier:
            continue
        days.append(earlier.get("day"))
        for key in earlier.get("adds") or {}:
            hour = latest.get(key, fallback)
            got = at_hour(earlier, key, hour)
            if got is not None:
                history.setdefault(int(key), []).append(got[0])
                same += got[1]
    info = {
        "today": body.get("read_at"),
        "rows": len(rows),
        "earlier_days": len(days),
        "same_hour": same,
    }
    return history, rank, adds, info


def _recent(
    data_dir: Path, players: Mapping[int, Any], now: datetime
) -> tuple[dict[int, list[fl.Window]], dict[str, Any]]:
    out: dict[int, list[fl.Window]] = {}
    info: dict[str, Any] = {}
    for days, pattern in PAST_DAYS.items():
        files = [
            f
            for f in data_dir.glob(pattern)
            if f.suffix.lower() in PROJECTION_SUFFIXES and "sample" not in f.name
        ]
        path = max(files, key=lambda f: f.stat().st_mtime, default=None)
        if path is None:
            info[f"{days}d"] = None
            continue
        as_of = datetime.fromtimestamp(path.stat().st_mtime, now.tzinfo)
        info[f"{days}d"] = {"file": path.name, "as_of": as_of.isoformat()}
        if now - as_of > PAST_DAYS_MAX_AGE:
            info[f"{days}d"]["stale"] = True
            continue
        df = sw._frame(path, _past_frame)
        for yid, pid in sw._match(path, df, players, data_dir).items():
            row = df.loc[pid]
            games = float(row.get("games") or 0.0)
            if games <= 0:
                continue
            out.setdefault(yid, []).append(
                fl.Window(days, games, float(row.get("minutes") or 0.0), _usage(row))
            )
    return out, info


def _value_ranks(season: Season, df: pd.DataFrame) -> pd.Series:
    """Every projected player's rank on the league's own scoring (1 for the best): total z over a
    pool of the league's drafted rosters, a points league's fantasy points (as the draft-day news
    sweep ranks them, ``scripts/draft_prep/news.py``)."""
    s = season.settings
    try:
        slots = len(leagues.league_slots(list(s.roster))) if s.roster else 0
    except leagues.LeagueError:
        slots = 0
    pool = max(2, s.num_teams * (slots or len(yahoo_default_slots())))
    frame, cats = df, tuple(Cat(c) for c in s.cats) or NINE_CAT
    if s.scoring == "points" and s.points:
        weights = {str(k).lower(): float(v) for k, v in s.points.items()}
        frame = df.assign(**{Cat.FPTS.value: fantasy_points(df, weights)})
        cats = POINTS_CAT
    total = zscores(frame, cats, pool_size=pool)["total"]
    return total.rank(ascending=False, method="first").astype(int)


_ranks: dict[tuple[Any, ...], pd.Series] = {}


def _injuries(
    data_dir: Path, ros: pd.DataFrame | None, ros_path: Path | None
) -> tuple[list[fl.Injury], dict[str, Any]]:
    body = _read(injuries_path(data_dir)) or {}
    listed = [Listed.from_dict(d) for d in body.get("players") or []]
    mpg: dict[str, float] = {}
    if listed and ros is not None and ros_path is not None:
        frame = pd.DataFrame(
            {"name": [x.name for x in listed], "team": [x.team for x in listed]},
            index=[x.key for x in listed],
        )
        frame = frame[~frame.index.duplicated()]
        found = match_players(frame, ros, load_aliases(data_dir / "aliases.json")).mapping
        for key, pid in found.items():
            m = _per_game_minutes(ros.loc[pid])
            if m is not None:
                mpg[key] = m
    out = [
        fl.Injury(
            name=x.name,
            nba_team=x.team,
            groups=fl.position_groups([x.position]),
            status=x.status,
            returns=x.returns,
            mpg=mpg.get(x.key),
        )
        for x in listed
    ]
    return out, {"read_at": body.get("read_at"), "players": len(listed)}


def inputs_for(
    season: Season, today: date, data_dir: Path, now: datetime
) -> tuple[fl.Inputs, dict[int, int], dict[str, Any]]:
    """The flag's inputs for a league, today's buzz adds by player, and what was read."""
    players = sw.season_players(season)
    history, rank, adds, buzz_info = _buzz(data_dir, today, now)
    recent, past_info = _recent(data_dir, players, now)
    ros_path = sw._latest(data_dir, sw.BBM_ROS)
    projected: dict[int, fl.Projection] = {}
    value_rank: dict[int, int] = {}
    ros = None
    if ros_path is not None:
        ros = sw._frame(ros_path)
        mapping = sw._match(ros_path, ros, players, data_dir)
        s = season.settings
        points = tuple(sorted((s.points or {}).items()))
        key = (
            str(ros_path),
            ros_path.stat().st_mtime,
            s.scoring,
            s.cats,
            points,
            s.num_teams,
            s.roster,
        )
        ranks = _ranks.get(key)
        if ranks is None:
            ranks = sw._keep(_ranks, key, _value_ranks(season, ros))
        for yid, pid in mapping.items():
            row = ros.loc[pid]
            projected[yid] = fl.Projection(_per_game_minutes(row), _usage(row))
            value_rank[yid] = int(ranks[pid])
    injuries, injury_info = _injuries(data_dir, ros, ros_path)
    info = {
        "buzz": buzz_info,
        "injuries": injury_info,
        "projection": ros_path.name if ros_path else None,
        "past_days": past_info,
    }
    inputs = fl.Inputs(
        today=today,
        history=history,
        buzz_rank=rank,
        recent=recent,
        projected=projected,
        value_rank=value_rank,
        injuries=injuries,
    )
    return inputs, adds, info


def _seen_today(a: Available, today: date) -> bool:
    return a.seen_at is None or a.seen_at.astimezone(sw.NBA_TZ).date() == today


def pool(season: Season, today: date, adds_today: Mapping[int, int]) -> list[fl.Pickup]:
    """The league's available players as the flag reads them. A row read on an earlier day
    gives no ownership change; adds are the day's largest count seen, on this league's players
    page or any read kept today (another league's page, the buzz index), since the count only
    grows through the day."""
    out = []
    for a in season.available:
        fresh = _seen_today(a, today)
        counts = [
            n
            for n in (a.adds if fresh else None, adds_today.get(a.player.yahoo_id))
            if n is not None
        ]
        out.append(
            fl.Pickup(
                yahoo_id=a.player.yahoo_id,
                name=a.player.name,
                nba_team=a.player.nba_team,
                positions=tuple(a.player.positions),
                pct_rostered=a.pct_rostered,
                pct_rostered_change=a.pct_rostered_change if fresh else None,
                adds=max(counts, default=None),
                status=a.player.status,
            )
        )
    return out


def league_flags(
    season: Season, today: date, data_dir: Path, now: datetime
) -> tuple[list[fl.Pickup], dict[int, fl.Flag], dict[str, Any]]:
    """Every available player's flag that a signal speaks for, and the inputs read."""
    inputs, adds, info = inputs_for(season, today, data_dir, now)
    players = pool(season, today, adds)
    return players, fl.flags(players, inputs), info


def stale(info: Mapping[str, Any], now: datetime) -> list[str]:
    """What the digest should say about old or missing inputs."""
    out = []
    buzz = _when(info["buzz"].get("today"))
    if buzz is None:
        out.append("no buzz index read today")
    elif now - buzz > BUZZ_STALE:
        out.append(f"the buzz index was read {buzz:%H:%M} UTC")
    injuries = _when(info["injuries"].get("read_at"))
    if injuries is None:
        out.append("no injury report read")
    elif now - injuries > INJURIES_STALE:
        out.append("the injury report is over 12 hours old")
    fresh = [k for k, v in info["past_days"].items() if v and not v.get("stale")]
    if not fresh:
        out.append("no past-days export within 3 days: the minutes trend is silent")
    if not info.get("projection"):
        out.append("no rest-of-season projection: minutes, value and opportunity are silent")
    return out


def payload(flags: Mapping[int, fl.Flag]) -> dict[str, Any]:
    return {str(k): f.to_dict() for k, f in flags.items()}


def flagged(
    players: Sequence[fl.Pickup], flags: Mapping[int, fl.Flag]
) -> list[tuple[fl.Pickup, fl.Flag]]:
    """The players with a level, the highest score first."""
    out = [(p, flags[p.yahoo_id]) for p in players if p.yahoo_id in flags]
    return sorted(
        [(p, f) for p, f in out if f.level is not None], key=lambda pf: (-pf[1].score, pf[0].name)
    )


def digest_league(
    league: str, name: str | None, rows: Sequence[tuple[fl.Pickup, fl.Flag]]
) -> dict[str, Any]:
    return {
        "league": league,
        "name": name,
        "flagged": [
            {
                "yahoo_id": p.yahoo_id,
                "name": p.name,
                "nba_team": p.nba_team,
                "positions": list(p.positions),
                "pct_rostered": p.pct_rostered,
                "line": fl.public_line(p, f),
                **f.to_dict(),
            }
            for p, f in rows
        ],
    }
