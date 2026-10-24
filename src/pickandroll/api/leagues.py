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
    The league's own survival table. Without one a league session reads its format's shared
    table, ``data/leagues/_shared/<points|categories>/survival_by_adp.csv`` (fit from the
    season's earlier drafts by ``scripts/draft_day.py refit``, #77) when that covers the draft,
    and simulates its survival otherwise.
``armed.json`` (optional)
    Written only by the user's own clicks in the dashboard. ``armed`` (``PUT /leagues/{id}/arm``):
    the room for this league's draft comes up in autopilot. ``lineups`` (``PUT
    /leagues/{id}/lineups``, #170): the lineup executor's mode, ``off``, ``dry_run`` or
    ``live``, with ``lineups_at`` and ``lineups_by``. ``moves`` (``PUT /leagues/{id}/moves``,
    #171) the same for the moves executor, with ``moves_cap``, the user's own cap on the day's
    moves. Nothing else writes it.
``adjustments.json`` (optional)
    Games haircuts the user prepared from the news sweep (#76, ``api.adjustments``), applied
    when the league's session is made: at the room's attach.

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
#: The archive of each format's real drafts and the tables fit from it (#77):
#: data/leagues/_shared/<points|categories>/.
SHARED = "_shared"
#: The refit's report beside the shared table (or in its place, with the reason there is none).
SURVIVAL_REPORT = "survival_by_adp.json"
#: The archive's drafted rosters, one row per pick: the league curve's source (#65, #77).
PICKS = "picks.csv"
#: The weight of the other format's drafts in a format's survival table and curve (#77): its
#: market's ADP is another one, its rosters were drafted for another scoring.
CROSS_FORMAT_WEIGHT = 0.5
ARMED = "armed.json"
#: The lineup executor's modes (#170, docs/AUTOPILOT.md section 2): it does nothing, logs what it
#: would set, or sets the lineup. ``live`` is only ever the user's own click.
LINEUP_MODES = ("off", "dry_run", "live")
#: A public league's mode until the user sets one: every public league is armed in advance
#: (docs/AUTOPILOT.md section 1), and every executor starts in dry run.
LINEUP_DEFAULT = "dry_run"
#: The executors whose mode ``armed.json`` keeps: the lineup's (#170) and the moves' (#171).
LINEUPS = "lineups"
MOVES = "moves"
EXECUTORS = (LINEUPS, MOVES)
ADJUSTMENTS = "adjustments.json"
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


def shared_dir(data_dir: Path, scoring: str) -> Path:
    """The shared archive of a format's drafts (``points`` or ``categories``)."""
    return data_dir / LEAGUES_DIR / SHARED / str(scoring)


def table_picks(path: Path) -> int:
    """The picks a survival table covers, from its header (``adp, 1..N, undrafted``)."""
    columns = pd.read_csv(path, nrows=0).columns
    picks = [int(c) for c in columns if str(c).isdigit()]
    return max(picks, default=0)


def draft_picks(settings: dict[str, Any]) -> int | None:
    """The picks a league's draft makes (teams times drafted roster slots); ``None`` when its
    settings list no roster."""
    if not settings.get("roster"):
        return None
    return int(settings.get("num_teams") or 12) * len(league_slots(list(settings["roster"])))


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
    shared = shared_dir(data_dir, settings["scoring"]) / SURVIVAL
    if (league_dir(data_dir, league) / SURVIVAL).exists():
        out.update(survival="league", survival_file=f"{folder}/{SURVIVAL}")
    elif shared.exists() and _covers(shared, draft_picks(settings)):
        # The format's shared table: this season's earlier drafts in leagues like this one.
        out.update(
            survival="league",
            survival_file=f"{LEAGUES_DIR}/{SHARED}/{settings['scoring']}/{SURVIVAL}",
        )
    else:
        # Another league's table (31822's archive) is not this league's market.
        out["survival"] = "simulate"
    if (league_dir(data_dir, league) / ADJUSTMENTS).exists():
        out["adjustments_file"] = f"{folder}/{ADJUSTMENTS}"
    return out


def archive_note(data_dir: Path, league: str) -> str | None:
    """Why a league session simulates although its format has an archive: the refit's reason
    there is no shared table (``archive: no drafts of 12 x 13 yet``); ``None`` without a report
    or with a table."""
    try:
        report = shared_report(data_dir, load_settings(data_dir, league)["scoring"])
    except LeagueError:
        return None
    if report is None or report.get("table") or not report.get("reason"):
        return None
    return f"archive: {report['reason']}"


def shared_report(data_dir: Path, scoring: str) -> dict[str, Any] | None:
    """The refit's report beside a format's shared table; ``None`` before the first refit."""
    try:
        report = json.loads((shared_dir(data_dir, scoring) / SURVIVAL_REPORT).read_text())
    except (OSError, ValueError):
        return None
    return report if isinstance(report, dict) else None


def other_format(scoring: str) -> str:
    return "categories" if scoring == "points" else "points"


def league_curve_drafts(data_dir: Path, league: str) -> float | None:
    """The drafts (the sum of their weights) behind the league curve when a session for
    ``league`` should ask for ``curve: league`` (#77), else ``None``. It should when its own
    folder has no table (the session then reads its format's shared one and the rosters of both
    formats' archives), the shared table and its blended report stand, and an archive holds
    rosters. The draft-day attach (``scripts/draft_prep/refit.py``) and the dashboard's form
    (``resolved``) both ask this."""
    scoring = load_settings(data_dir, league)["scoring"]
    if (league_dir(data_dir, league) / SURVIVAL).exists():
        return None
    shared = shared_dir(data_dir, scoring)
    report = shared_report(data_dir, scoring)
    if report is None or not report.get("blend") or not (shared / SURVIVAL).exists():
        return None
    archives = (shared, shared_dir(data_dir, other_format(scoring)))
    if not any((folder / PICKS).exists() for folder in archives):
        return None
    drafts = float(report["blend"].get("drafts") or 0.0)
    return drafts if drafts > 0 else None


def resolved(data_dir: Path, league: str) -> dict[str, Any]:
    """What a session for ``league`` resolves to from its folder and its format's archive, for
    the dashboard's form (#74): the survival and its source, the curve the draft-day attach
    asks for, the players file behind ADP, positions and rank, and the rounds drafted."""
    settings = load_settings(data_dir, league)
    defaults = session_defaults(data_dir, league)
    survival_file = defaults.get("survival_file")
    shared = bool(survival_file) and survival_file.startswith(f"{LEAGUES_DIR}/{SHARED}/")
    report = shared_report(data_dir, settings["scoring"]) if shared else None
    drafts = league_curve_drafts(data_dir, league)
    picks = draft_picks(settings)
    return {
        "survival": defaults["survival"],
        "survival_file": survival_file,
        "note": archive_note(data_dir, league) if defaults["survival"] == "simulate" else None,
        "blend": (report or {}).get("blend"),
        "curve": "simulated" if drafts is None else "league",
        "curve_drafts": drafts,
        "adp_file": defaults.get("adp_file"),
        "positions_file": defaults.get("positions_file"),
        "rounds": None if picks is None else picks // defaults["num_teams"],
    }


def _covers(path: Path, picks: int | None) -> bool:
    try:
        return picks is not None and table_picks(path) >= picks
    except (OSError, ValueError):
        return False


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


def _armed_file(data_dir: Path, league: str) -> tuple[Path, dict[str, Any]]:
    """The league's ``armed.json`` and what it holds (empty when missing or not JSON)."""
    folder = league_dir(data_dir, league)
    if not (folder / SETTINGS).exists():
        raise LeagueError(f"no league settings: data/{LEAGUES_DIR}/{league}/{SETTINGS}")
    path = folder / ARMED
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        record = {}
    return path, record if isinstance(record, dict) else {}


def _write_armed(path: Path, record: dict[str, Any]) -> None:
    if record:
        path.write_text(json.dumps(record) + "\n")
    else:
        path.unlink(missing_ok=True)


def set_armed(data_dir: Path, league: str, on: bool, by: str) -> dict[str, Any] | None:
    """Record (or withdraw) the user's pre-arm. Only the dashboard's own control calls this.
    Withdrawing drops the draft's keys and keeps the lineup executor's mode (#170)."""
    path, record = _armed_file(data_dir, league)
    for key in ("armed", "at", "by"):
        record.pop(key, None)
    if on:
        record = {
            "armed": True,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "by": by,
            **record,
        }
    _write_armed(path, record)
    return armed(data_dir, league)


def executor_mode(data_dir: Path, league: str, kind: str) -> dict[str, Any]:
    """An executor's mode for ``league``: the lineup executor's (``lineups``, #170) or the moves
    executor's (``moves``, #171), ``{mode, at, by, set, private}``, the moves' with the user's own
    cap on the day's moves (``cap``, None for the knob's). The private league is always ``off``; a
    public league is its file's mode, else :data:`LINEUP_DEFAULT` (``set`` False)."""
    if kind not in EXECUTORS:
        raise LeagueError(f"an executor is one of {', '.join(EXECUTORS)}, not {kind!r}")
    extra = {"cap": None} if kind == MOVES else {}
    if not load_settings(data_dir, league).get("public", True):
        return {"mode": "off", "at": None, "by": None, "set": False, "private": True, **extra}
    _, record = _armed_file(data_dir, league)
    if kind == MOVES:
        cap = record.get(f"{kind}_cap")
        extra = {"cap": cap if isinstance(cap, int) and not isinstance(cap, bool) else None}
    mode = record.get(kind)
    if mode not in LINEUP_MODES:
        return {
            "mode": LINEUP_DEFAULT,
            "at": None,
            "by": None,
            "set": False,
            "private": False,
            **extra,
        }
    return {
        "mode": mode,
        "at": record.get(f"{kind}_at"),
        "by": record.get(f"{kind}_by"),
        "set": True,
        "private": False,
        **extra,
    }


def set_executor(
    data_dir: Path, league: str, kind: str, mode: str, by: str, cap: int | None = None
) -> dict[str, Any]:
    """Record an executor's mode, the dashboard's own click; the draft's keys and the other
    executor's stay. The moves executor's ``cap`` is the user's own cap on the day's moves (None:
    the knob's)."""
    if kind not in EXECUTORS:
        raise LeagueError(f"an executor is one of {', '.join(EXECUTORS)}, not {kind!r}")
    if mode not in LINEUP_MODES:
        raise LeagueError(f"a mode is one of {', '.join(LINEUP_MODES)}, not {mode!r}")
    path, record = _armed_file(data_dir, league)
    record.update(
        {
            kind: mode,
            f"{kind}_at": datetime.now(UTC).isoformat(timespec="seconds"),
            f"{kind}_by": by,
        }
    )
    if kind == MOVES:
        record.pop(f"{kind}_cap", None)
        if cap is not None:
            record[f"{kind}_cap"] = cap
    _write_armed(path, record)
    return executor_mode(data_dir, league, kind)


def lineup_mode(data_dir: Path, league: str) -> dict[str, Any]:
    """The lineup executor's mode for ``league`` (#170): :func:`executor_mode` of ``lineups``."""
    return executor_mode(data_dir, league, LINEUPS)


def set_lineups(data_dir: Path, league: str, mode: str, by: str) -> dict[str, Any]:
    """Record the lineup executor's mode, the dashboard's own click; the draft's keys stay."""
    return set_executor(data_dir, league, LINEUPS, mode, by)


def summary(data_dir: Path, league: str) -> dict[str, Any]:
    """One league for the dashboard: its settings, its files, the user's arm and what its
    session resolves to (``None``, with the ``error``, when the folder's roster does not read:
    the league still lists)."""
    settings = load_settings(data_dir, league)
    folder = league_dir(data_dir, league)
    try:
        session: dict[str, Any] | None = resolved(data_dir, league)
        error = None
    except LeagueError as exc:
        session, error = None, str(exc)
    return {
        "league": str(league),
        "scoring": settings["scoring"],
        "num_teams": settings.get("num_teams"),
        "draft_time": (settings.get("draft") or {}).get("time"),
        "pick_seconds": (settings.get("draft") or {}).get("pick_seconds"),
        "players_file": (folder / PLAYERS).exists(),
        "survival_file": (folder / SURVIVAL).exists(),
        "armed": armed(data_dir, league),
        "resolved": session,
        "error": error,
    }


def leagues(data_dir: Path) -> list[str]:
    root = data_dir / LEAGUES_DIR
    if not root.is_dir():
        return []
    return sorted(
        (p.name for p in root.iterdir() if (p / SETTINGS).exists()),
        key=lambda name: (len(name), name),
    )
