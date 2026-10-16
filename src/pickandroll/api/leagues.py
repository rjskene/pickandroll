"""Per-league setup: a Yahoo league's files in ``data/leagues/<id>/`` (issue #67).

A league folder holds what a session for that league needs, all local and never committed:

``settings.json``
    From the league's Yahoo settings page: ``scoring`` (``points`` or ``categories``),
    ``num_teams``, ``roster`` (Yahoo's slot list, ``IL`` slots included), ``points`` (stat to
    points per unit) or ``categories``, ``draft`` (``time``, ``pick_seconds``) and
    ``my_team_id``.
``yahoo_players.json``
    Yahoo's players response for the league (``/fantasy/v3/players/nba/<id>``, public): the
    Yahoo ids the draft room speaks, eligible positions, Yahoo's ADP and ``o_rank``.
``survival_by_adp.csv`` (optional)
    The league's own survival table; without one a league session simulates its survival.
``armed.json`` (optional)
    Written only by the user's own click in the dashboard (``PUT /leagues/{id}/arm``): the room
    for this league's draft comes up in autopilot. Nothing else writes it.

A session names the folder with ``league``; fields the request sets itself win over the
folder's.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..optim.roster import ANY, FORWARDS, GUARDS, Slot, yahoo_default_slots
from ..projections.schema import NINE_CAT, Cat
from ..sources.matching import load_aliases
from ..sources.yahoo import build_id_map, load_players_file

LEAGUES_DIR = "leagues"
SETTINGS = "settings.json"
PLAYERS = "yahoo_players.json"
SURVIVAL = "survival_by_adp.csv"
ARMED = "armed.json"
#: A league id as Yahoo prints it, and as the draft client's path carries it.
LEAGUE_ID = r"^[0-9]{1,12}$"

#: Yahoo's names for the nine categories (settings page abbreviations) and ours.
YAHOO_CATS: dict[str, Cat] = {
    "FG%": Cat.FG_PCT,
    "FT%": Cat.FT_PCT,
    "3PTM": Cat.THREES,
    "PTS": Cat.PTS,
    "REB": Cat.REB,
    "AST": Cat.AST,
    "ST": Cat.STL,
    "BLK": Cat.BLK,
    "TO": Cat.TOV,
}
#: Roster tokens that are not drafted (injury and not-active slots).
UNDRAFTED_SLOTS = {"IL", "IL+", "NA"}


class LeagueError(ValueError):
    """A league folder that is missing or does not read."""


def league_dir(data_dir: Path, league: str) -> Path:
    return data_dir / LEAGUES_DIR / str(league)


def load_settings(data_dir: Path, league: str) -> dict[str, Any]:
    path = league_dir(data_dir, league) / SETTINGS
    if not path.exists():
        raise LeagueError(f"no league settings: data/{LEAGUES_DIR}/{league}/{SETTINGS}")
    try:
        settings = json.loads(path.read_text())
    except ValueError as exc:
        raise LeagueError(f"{path.name}: {exc}") from exc
    scoring = settings.get("scoring")
    if scoring not in ("points", "categories"):
        raise LeagueError(f"{path.name}: scoring must be points or categories, not {scoring!r}")
    if scoring == "points" and not settings.get("points"):
        raise LeagueError(f"{path.name}: a points league needs its points weights")
    return settings


def league_slots(roster: list[str]) -> list[Slot]:
    """Yahoo's roster list (``PG, SG, G, ..., Util, BN, IL``) as the slots a draft fills: the
    injury slots are left out; Util and bench take anyone."""
    slots: list[Slot] = []
    seen: dict[str, int] = {}
    for token in roster:
        name = str(token).strip()
        if name.upper() in UNDRAFTED_SLOTS:
            continue
        key = name.upper()
        if key in ("PG", "SG", "SF", "PF", "C"):
            eligible = frozenset({key})
        elif key == "G":
            eligible = GUARDS
        elif key == "F":
            eligible = FORWARDS
        elif key in ("UTIL", "BN"):
            eligible = ANY
        else:
            raise LeagueError(f"unknown roster slot {name!r}")
        seen[key] = seen.get(key, 0) + 1
        slots.append(Slot(f"{key}{seen[key]}", eligible))
    return slots


def league_cats(settings: dict[str, Any]) -> list[Cat] | None:
    """A categories league's categories, in our names (``None`` for a points league)."""
    if settings["scoring"] != "categories":
        return None
    cats = settings.get("categories") or [c.value for c in NINE_CAT]
    out = []
    for c in cats:
        cat = YAHOO_CATS.get(str(c)) or Cat(str(c))
        out.append(cat)
    return out


def session_defaults(data_dir: Path, league: str) -> dict[str, Any]:
    """What a session for ``league`` takes from its folder, as SessionCreate fields (paths
    relative to data/)."""
    settings = load_settings(data_dir, league)
    folder = f"{LEAGUES_DIR}/{league}"
    out: dict[str, Any] = {"num_teams": int(settings.get("num_teams") or 12)}
    if settings.get("roster"):
        slots = league_slots(list(settings["roster"]))
        bench = sum(1 for s in slots if s.name.startswith("BN"))
        if [s.eligible for s in slots] == [s.eligible for s in yahoo_default_slots(bench)]:
            out["bench"] = bench  # Yahoo's default lineup: its own slot names
        else:
            out["slots"] = [
                {"name": s.name, "eligible": [] if s.eligible == ANY else sorted(s.eligible)}
                for s in slots
            ]
    if settings["scoring"] == "points":
        out["points"] = {str(k): float(v) for k, v in settings["points"].items()}
    else:
        out["cats"] = league_cats(settings)
    if (league_dir(data_dir, league) / PLAYERS).exists():
        players = f"{folder}/{PLAYERS}"
        out.update(adp_file=players, positions_file=players, adp_fallback_file=players)
    if (league_dir(data_dir, league) / SURVIVAL).exists():
        out.update(survival="league", survival_file=f"{folder}/{SURVIVAL}")
    else:
        # Another league's table (31822's archive) is not this league's market.
        out["survival"] = "simulate"
    return out


def players_frame(path: Path, projections: pd.DataFrame, data_dir: Path) -> pd.DataFrame:
    """A Yahoo players JSON by projection id: ``adp`` (Yahoo's average pick), ``positions``
    (Yahoo's eligibility, ``PG/SG``) and ``o_rank``, through the room's id map and aliases.
    A projection Yahoo lists twice keeps its earliest row."""
    players = load_players_file(path)
    ids = build_id_map(players, projections, load_aliases(data_dir / "aliases.json"))
    rows = []
    for yid, row in players.iterrows():
        pid = ids.pid(str(yid))
        if pid is not None:
            rows.append({"pid": pid, **row[["adp", "positions", "o_rank"]].to_dict()})
    frame = pd.DataFrame(rows, columns=["pid", "adp", "positions", "o_rank"])
    frame = frame.sort_values("o_rank", na_position="last").drop_duplicates("pid")
    return frame.set_index("pid")


# --------------------------------------------------------------------------- the user's arm
def armed(data_dir: Path, league: str) -> dict[str, Any] | None:
    """The user's pre-arm for this league's draft, or ``None``."""
    path = league_dir(data_dir, league) / ARMED
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text())
    except ValueError:
        return None
    return record if record.get("armed") is True else None


def set_armed(data_dir: Path, league: str, on: bool, by: str) -> dict[str, Any] | None:
    """Record (or withdraw) the user's pre-arm. Only the dashboard's own control calls this."""
    folder = league_dir(data_dir, league)
    if not (folder / SETTINGS).exists():
        raise LeagueError(f"no league settings: data/{LEAGUES_DIR}/{league}/{SETTINGS}")
    path = folder / ARMED
    if not on:
        path.unlink(missing_ok=True)
        return None
    record = {"armed": True, "at": datetime.now(UTC).isoformat(timespec="seconds"), "by": by}
    path.write_text(json.dumps(record) + "\n")
    return record


def summary(data_dir: Path, league: str) -> dict[str, Any]:
    """One league for the dashboard: its settings, its files and the user's arm."""
    settings = load_settings(data_dir, league)
    folder = league_dir(data_dir, league)
    return {
        "league": str(league),
        "scoring": settings["scoring"],
        "num_teams": settings.get("num_teams"),
        "draft_time": (settings.get("draft") or {}).get("time"),
        "pick_seconds": (settings.get("draft") or {}).get("pick_seconds"),
        "players_file": (folder / PLAYERS).exists(),
        "survival_file": (folder / SURVIVAL).exists(),
        "armed": armed(data_dir, league),
    }


def leagues(data_dir: Path) -> list[str]:
    root = data_dir / LEAGUES_DIR
    if not root.is_dir():
        return []
    return sorted(
        (p.name for p in root.iterdir() if (p / SETTINGS).exists()),
        key=lambda name: (len(name), name),
    )
