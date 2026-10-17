"""The season's earlier drafts (#77): each finished real draft goes into its format's archive, and
the tables a session reads are refit from it before the next draft.

    python scripts/draft_day.py refit 15953                    # report the archive, rewrite the tables
    python scripts/draft_day.py refit 238174 --add-draft DIR   # archive a finished draft first

``finish`` archives the draft it saved; ``run`` refits before the attach. The archive of a format
is ``data/leagues/_shared/<points|categories>/``:

``picks.csv``
    One row per pick of every archived draft: ``season, draft_year, league_id, draft_date,
    n_teams, rounds, round, pick_in_round, overall, slot, team, player_id, player, adp, rank``.
    ``slot`` is the draft seat, ``team`` the Yahoo team that made the pick, ``player_id`` the
    Yahoo id, ``adp`` and ``rank`` Yahoo's ADP and ``o_rank`` from the league's players file at
    draft time (refreshed at T-30 by ``run``).
``adp.csv``
    Every player with an ADP in that players file, per draft: ``league_id, draft_year,
    draft_date, player_id, player, adp, rank, overall`` (empty when undrafted). The undrafted
    are the survival fit's censored players.
``survival_by_adp.csv``, ``survival_by_adp.json``
    The survival table fit from the drafts of the league's size (no keepers in these leagues,
    so the overall pick is the market pick), and the fit's report. Two minimums apply together:
    the archive needs ``MIN_DRAFTS`` drafts of the size before there is a table at all (one
    draft gives one player per ADP value, noisier than the ADP formula of the market these
    leagues draft by), and a row answers only where ``MIN_COUNT`` players have an ADP within
    its bandwidth, the ADP formula past the boundary (``fit_survival_table``). Without a table
    the report stays, with the reason, and a league session simulates and says why. A league
    session reads the table after its own folder's and before simulating
    (``leagues.session_defaults``).

Real drafts only: a draft is archived from a finished room's folder of a league with a folder
under ``data/leagues/``, whose ledger holds every pick; mocks have no league folder. For a
categories league the attach asks for ``curve: league`` (fit from ``picks.csv`` beside the
table, #65) under the same draft minimum, and says so.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pickandroll.api import leagues
from pickandroll.api.league_curve import draft_year
from pickandroll.availability import LEAGUE_FROM_ADP, MIN_COUNT, fit_survival_table, survival_frame
from pickandroll.fidelity import read_events
from pickandroll.sources.yahoo import load_players_file

HELP = "refit <league>: archive finished drafts, refit the survival table and the curve's sources"
LEAGUE = True

PICKS = "picks.csv"
ADP = "adp.csv"
REPORT = leagues.SURVIVAL_REPORT
#: The archive's drafts of a size before it gives a survival table, and before a categories
#: attach asks for the league curve.
MIN_DRAFTS = 3
PICK_COLUMNS = [
    "season",
    "draft_year",
    "league_id",
    "draft_date",
    "n_teams",
    "rounds",
    "round",
    "pick_in_round",
    "overall",
    "slot",
    "team",
    "player_id",
    "player",
    "adp",
    "rank",
]
ADP_COLUMNS = [
    "league_id",
    "draft_year",
    "draft_date",
    "player_id",
    "player",
    "adp",
    "rank",
    "overall",
]
#: A draft in the archive.
DRAFT = ["league_id", "draft_date"]


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--add-draft",
        metavar="DIR",
        help="refit: archive this finished draft's folder (data/fidelity/<league>_<date>_"
        "session_<id>/) first",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        help=f"refit: players a survival row needs within its bandwidth (default {MIN_COUNT}, "
        "or the league's settings.json refit.min_count)",
    )
    parser.add_argument(
        "--min-drafts",
        type=int,
        help=f"refit, run: drafts before the archive gives a survival table and a categories "
        f"attach the league curve (default {MIN_DRAFTS}, or settings.json refit.min_drafts)",
    )


# --------------------------------------------------------------------------- the league
def shape(mine: dict[str, Any]) -> tuple[str, int, int]:
    """The league's format, team count and rounds."""
    picks = leagues.draft_picks(mine)
    teams = int(mine.get("num_teams") or 12)
    if picks is None:
        raise ValueError("settings.json lists no roster: the draft's size is unknown")
    return str(mine["scoring"]), teams, picks // teams


def minimum(mine: dict[str, Any], args: argparse.Namespace | None, name: str, default: int) -> int:
    given = getattr(args, name, None) if args is not None else None
    if given is not None:
        return int(given)
    return int((mine.get("refit") or {}).get(name, default))


def draft_day(mine: dict[str, Any]) -> str:
    planned = (mine.get("draft") or {}).get("time")
    if not planned:
        raise ValueError("settings.json has no draft time")
    return datetime.fromisoformat(planned).date().isoformat()


# --------------------------------------------------------------------------- the archive
def ledger_picks(
    league: str, mine: dict[str, Any], ledger: Path
) -> tuple[dict[int, dict[str, Any]], dict[int, Any]]:
    """The room's picks by overall and the Yahoo team on the clock at each. Raises
    ``ValueError`` for another league's ledger or one that does not hold every pick."""
    _, teams, rounds = shape(mine)
    events = read_events(ledger)
    attach = next((e for e in events if e.get("type") == "attach"), {})
    logged = str((attach.get("session") or {}).get("league") or attach.get("draft_id") or league)
    if logged != str(league):
        raise ValueError(f"{ledger.name} is league {logged}'s ledger, not {league}'s")
    picks = {int(e["overall"]): e for e in events if e.get("type") == "room_pick"}
    teams_by_pick = {
        int(e["overall"]): e.get("team") for e in events if e.get("type") == "turn_start"
    }
    total = teams * rounds
    if sorted(picks) != list(range(1, total + 1)):
        raise ValueError(f"{ledger.name} holds {len(picks)} of {total} picks: not a finished draft")
    return picks, teams_by_pick


def draft_rows(
    league: str, mine: dict[str, Any], ledger: Path, players: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A finished draft's picks and its ADP list, in the archive's shape."""
    _, teams, rounds = shape(mine)
    picks, teams_by_pick = ledger_picks(league, mine, ledger)
    total = teams * rounds
    yahoo = load_players_file(players)
    day = draft_day(mine)
    year = draft_year(datetime.fromisoformat(day))
    season = f"{year}-{(year + 1) % 100:02d}"
    rows = []
    for overall in range(1, total + 1):
        e = picks[overall]
        yid = str(e["yid"])
        known = yid in yahoo.index
        team = teams_by_pick.get(overall)
        rows.append(
            {
                "season": season,
                "draft_year": year,
                "league_id": str(league),
                "draft_date": day,
                "n_teams": teams,
                "rounds": rounds,
                "round": (overall - 1) // teams + 1,
                "pick_in_round": (overall - 1) % teams + 1,
                "overall": overall,
                "slot": e.get("slot"),
                "team": f"team {team}" if team is not None else f"seat {e.get('slot')}",
                "player_id": yid,
                "player": yahoo.at[yid, "name"] if known else e.get("name"),
                "adp": yahoo.at[yid, "adp"] if known else None,
                "rank": yahoo.at[yid, "o_rank"] if known else None,
            }
        )
    pick_frame = pd.DataFrame(rows, columns=PICK_COLUMNS)
    taken = dict(zip(pick_frame["player_id"], pick_frame["overall"], strict=True))
    listed = yahoo[yahoo["adp"].notna()]
    adp_frame = pd.DataFrame(
        {
            "league_id": str(league),
            "draft_year": year,
            "draft_date": day,
            "player_id": listed.index.astype(str),
            "player": listed["name"].to_numpy(),
            "adp": listed["adp"].to_numpy(float),
            "rank": listed["o_rank"].to_numpy(float),
            "overall": [taken.get(str(y)) for y in listed.index],
        },
        columns=ADP_COLUMNS,
    )
    return pick_frame, adp_frame


def read_archive(shared: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    picks = shared / PICKS
    adp = shared / ADP
    ids = {"league_id": str, "player_id": str, "draft_date": str}
    return (
        pd.read_csv(picks, dtype=ids) if picks.exists() else pd.DataFrame(columns=PICK_COLUMNS),
        pd.read_csv(adp, dtype=ids) if adp.exists() else pd.DataFrame(columns=ADP_COLUMNS),
    )


def archive(runbook: Any, league: str, saved: Path) -> int:
    """Add the finished draft saved in ``saved`` (``finish``'s folder) to its format's archive,
    replacing an earlier copy of the same draft; the drafts the archive then holds. The players
    file is the folder's copy, else the league's (refreshed at T-30, so the draft's), which is
    then copied into the folder."""
    mine = runbook.settings(league)
    ledger = saved / "ledger.jsonl"
    if not ledger.exists():
        raise ValueError(f"no ledger.jsonl in {saved}")
    ledger_picks(league, mine, ledger)
    players = saved / leagues.PLAYERS
    if not players.exists():
        source = runbook.folder(league) / leagues.PLAYERS
        if not source.exists():
            raise ValueError(f"no {leagues.PLAYERS} for league {league}")
        shutil.copy2(source, players)
        when = datetime.fromtimestamp(source.stat().st_mtime, UTC).astimezone()
        runbook.say(f"  ADP at draft time: the league's players file of {when:%a %Y-%m-%d %H:%M}")
    pick_frame, adp_frame = draft_rows(league, mine, ledger, players)
    shared = leagues.shared_dir(runbook.DATA, mine["scoring"])
    shared.mkdir(parents=True, exist_ok=True)
    old_picks, old_adp = read_archive(shared)
    key = (str(league), draft_day(mine))
    keep_picks = old_picks[[tuple(k) != key for k in old_picks[DRAFT].to_numpy()]]
    keep_adp = old_adp[[tuple(k) != key for k in old_adp[DRAFT].to_numpy()]]
    out_picks = pd.concat([keep_picks, pick_frame], ignore_index=True)
    out_adp = pd.concat([keep_adp, adp_frame], ignore_index=True)
    write_csv(out_picks, shared / PICKS)
    write_csv(out_adp, shared / ADP)
    count = len(out_picks.drop_duplicates(DRAFT))
    runbook.say(
        f"archived {league}'s draft of {key[1]} in {rel(runbook, shared)}: {len(pick_frame)} "
        f"picks, {int(adp_frame['adp'].notna().sum())} players with an ADP; the archive holds "
        f"{count} draft{'s' if count != 1 else ''}"
    )
    return count


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".part")
    frame.to_csv(tmp, index=False)
    tmp.replace(path)


def rel(runbook: Any, path: Path) -> str:
    return str(path.relative_to(runbook.DATA / leagues.LEAGUES_DIR))


# --------------------------------------------------------------------------- the refit
def refit(runbook: Any, league: str, args: argparse.Namespace | None = None) -> dict[str, Any]:
    """Report the archive for the league's format and size and rewrite the survival table (or
    remove a stale one when no row answers); the report written beside it."""
    mine = runbook.settings(league)
    scoring, teams, rounds = shape(mine)
    shared = leagues.shared_dir(runbook.DATA, scoring)
    table_path, report_path = shared / leagues.SURVIVAL, shared / REPORT
    min_count = minimum(mine, args, "min_count", MIN_COUNT)
    min_drafts = minimum(mine, args, "min_drafts", MIN_DRAFTS)
    picks, adp = read_archive(shared)
    same = picks[(picks["n_teams"] == teams) & (picks["rounds"] == rounds)]
    drafts = same.drop_duplicates(DRAFT)[DRAFT].astype(str).to_numpy().tolist()
    others = len(picks.drop_duplicates(DRAFT)) - len(drafts)
    names = ", ".join(f"{d[0]} {d[1]}" for d in drafts) or "none"
    runbook.say(
        f"archive {rel(runbook, shared)}: {len(drafts)} draft{'s' if len(drafts) != 1 else ''} "
        f"of {teams} x {rounds} ({names})"
        + (f"; {others} of another size left out" if others else "")
    )
    report: dict[str, Any] = {
        "built": datetime.now(UTC).isoformat(timespec="seconds"),
        "format": scoring,
        "teams": teams,
        "rounds": rounds,
        "drafts": [{"league": d[0], "date": d[1]} for d in drafts],
        "min_count": min_count,
        "from_adp": LEAGUE_FROM_ADP,
        "max_adp": None,
        "curve_min_drafts": min_drafts,
    }
    chosen = {tuple(d) for d in drafts}
    rows = adp[[tuple(k) in chosen for k in adp[DRAFT].astype(str).to_numpy()]]
    table = None
    many = f"{len(drafts)} draft{'s' if len(drafts) != 1 else ''}"
    reason = f"{many}, below the minimum of {min_drafts}"
    if len(drafts) >= min_drafts and len(rows):
        table, counts = fit_survival_table(
            rows["adp"].to_numpy(float),
            pd.to_numeric(rows["overall"], errors="coerce").to_numpy(float),
            picks=teams * rounds,
            min_count=min_count,
        )
        near = int(counts[LEAGUE_FROM_ADP])
        reason = f"{many}, {near} players near ADP {LEAGUE_FROM_ADP}, under {min_count}"
    if table is None:
        table_path.unlink(missing_ok=True)
        report.update(table=None, reason=reason)
        shared.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=1) + "\n")
        runbook.say(f"  survival: no table (archive: {reason}): league sessions simulate")
    else:
        write_csv(survival_frame(table).round(4), table_path)
        report.update(
            table=rel(runbook, table_path),
            max_adp=table.max_adp,
            counts={
                "at_from_adp": int(counts[LEAGUE_FROM_ADP]),
                "at_max_adp": int(counts[table.max_adp]),
            },
        )
        report_path.write_text(json.dumps(report, indent=1) + "\n")
        runbook.say(
            f"  survival: wrote {rel(runbook, table_path)}, answering ADP {LEAGUE_FROM_ADP}-"
            f"{table.max_adp} (at least {min_count} players within the bandwidth); the ADP "
            "formula elsewhere"
        )
    if scoring == "categories":
        if table is not None:
            runbook.say(f"  curve: league, from the {many}' rosters (#65)")
        else:
            runbook.say(f"  curve: simulated (archive: {reason})")
    return report


def league_curve_ready(runbook: Any, league: str, args: Any = None) -> int | None:
    """The drafts behind the shared table when a categories league's attach should ask for
    ``curve: league``: its own folder has no table (the session then reads the shared one and
    the ``picks.csv`` beside it), the shared report names at least the minimum of drafts."""
    mine = runbook.settings(league)
    if mine.get("scoring") != "categories":
        return None
    if (runbook.folder(league) / leagues.SURVIVAL).exists():
        return None
    shared = leagues.shared_dir(runbook.DATA, "categories")
    try:
        report = json.loads((shared / REPORT).read_text())
    except (OSError, ValueError):
        return None
    if not (shared / leagues.SURVIVAL).exists() or not (shared / PICKS).exists():
        return None
    drafts = len(report.get("drafts") or [])
    return drafts if drafts >= minimum(mine, args, "min_drafts", MIN_DRAFTS) else None


# --------------------------------------------------------------------------- hooks
def on_status(runbook: Any, league: str) -> None:
    mine = runbook.settings(league)
    shared = leagues.shared_dir(runbook.DATA, mine.get("scoring", ""))
    try:
        report = json.loads((shared / REPORT).read_text())
    except (OSError, ValueError):
        runbook.say(f"  archive {rel(runbook, shared)}: not refit yet")
        return
    if not report.get("table"):
        runbook.say(f"  archive {rel(runbook, shared)}: {report.get('reason')}: no survival table")
        return
    runbook.say(
        f"  archive {rel(runbook, shared)}: {len(report.get('drafts') or [])} drafts, the survival "
        f"table answering ADP {report.get('from_adp')}-{report.get('max_adp')}"
    )


def before_attach(runbook: Any, league: str, args: argparse.Namespace) -> None:
    try:
        refit(runbook, league, args)
    except (OSError, ValueError, KeyError) as exc:
        runbook.say(f"ALERT refit failed ({exc}): the tables on disk stand")


def session_fields(runbook: Any, league: str, args: Any = None) -> dict[str, Any]:
    drafts = league_curve_ready(runbook, league, args)
    if drafts is None:
        return {}
    runbook.say(f"curve: league, from the archive's {drafts} drafts")
    return {"curve": "league"}


def after_finish(runbook: Any, league: str, saved: Path) -> None:
    try:
        archive(runbook, league, saved)
    except (OSError, ValueError, KeyError) as exc:
        runbook.say(f"not archived ({exc})")


# --------------------------------------------------------------------------- the command
def run(runbook: Any, args: argparse.Namespace) -> int:
    league = str(args.league)
    if args.add_draft:
        try:
            archive(runbook, league, Path(args.add_draft).expanduser())
        except (OSError, ValueError, KeyError) as exc:
            raise runbook.Stop(runbook.ERROR, f"not archived: {exc}") from exc
    try:
        refit(runbook, league, args)
    except (OSError, ValueError, KeyError) as exc:
        raise runbook.Stop(runbook.ERROR, f"refit failed: {exc}") from exc
    return runbook.OK
