"""The winning-bids table for the season simulator (#416): every winning waiver claim the
stored reads of the nine public leagues show, frozen to a CSV with a meta file and its sha256.

The user ruled on 2026-11-17 (#172) that the table may go to the simulator's box. It is built by
hand on the droplet's live checkout (``scripts/sim_bids.py``) from what is already on disk, and
never calls Yahoo:

- the league's stored reads, ``season/snapshots/*.json``: the transactions page, the league page
  (each team's dollars left) and the available players (percent rostered). Only the public reads
  of the transactions page count (:data:`TIMES_FROM`): the extension's read prints the times in
  the user's profile zone (Pacific), so its claims would land three hours early under a second
  key;
- the autopilot queue files, ``autopilot/queue/*.json``: my claims, for my bid on a claim I lost.

A row is one winning waiver claim: the winner's ``add`` row whose detail is ``$N Waiver``, kept
once across reads by (time, player, team); a drop goes with it when the group has one. The page
prints no year, so each row's year comes from its read's ``fetched_at`` (the latest such date
not after the read, :func:`pickandroll.season.decisions.when_at`). The page keeps about 25
transactions, so the table is a lower bound of the claims made.

Never in it: the private league, a team's name or id, or anything from a subscriber source. The
winner is known only by whether it is my team (``ours``).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..season import decisions as dl
from . import leagues
from .season_decisions import TRANSACTIONS_TZ
from .season_queue import queue_dir
from .season_reads import snapshots_dir

#: The league that never goes in (the user's private league), whatever its settings say.
PRIVATE_LEAGUE = "31822"
#: The folder under ``data/`` the table and its meta go to (``.gitignore`` covers ``data/``).
SHARE_DIR = "sim_share"
TABLE = "winning_bids.csv"
META = "winning_bids.meta.json"
#: The table's columns, in order.
COLUMNS = (
    "league",
    "teams",
    "faab_budget",
    "at",
    "player",
    "name",
    "nba_team",
    "amount",
    "with_drop",
    "winner_faab_left",
    "winner_faab_read_at",
    "pct_rostered",
    "ours",
    "our_bid",
)
#: ``ours``: a rival's win (empty), my win, or my lost claim beside the rival's winning row.
RIVAL, WON, LOST = "", "won", "lost"
#: How old a read of the available players may be and still give a claim's percent rostered.
PCT_SPAN = timedelta(days=1)
#: The transactions reads whose times are the league's zone (America/New_York): the public
#: reads. The extension's prints the user's profile zone, so its reads are left out.
TIMES_FROM = "public"
#: How long after my claim was placed its winner's row may come (a claim waits two days).
LOST_SPAN = timedelta(days=4)


@dataclass(frozen=True)
class Win:
    """A winning waiver claim on the transactions page."""

    at: datetime
    player: int
    team: int
    amount: float
    with_drop: bool
    #: The player's name and NBA team as the row printed them (player names are public).
    name: str = ""
    nba_team: str = ""


@dataclass
class LeagueReads:
    """A league's stored reads, oldest first: its transactions' winning claims, each team's
    dollars left by read, and the available players' percent rostered by read."""

    reads: list[datetime] = field(default_factory=list)
    wins: dict[tuple[datetime, int, int], Win] = field(default_factory=dict)
    faab: list[tuple[datetime, dict[int, float]]] = field(default_factory=list)
    pct: list[tuple[datetime, dict[int, float]]] = field(default_factory=list)
    teams: int | None = None
    budget: float | None = None


def public_leagues(data_dir: Path) -> list[str]:
    """The leagues the table covers: every league whose settings do not say it is private, never
    :data:`PRIVATE_LEAGUE`."""
    out = []
    for league in leagues.leagues(data_dir):
        if league == PRIVATE_LEAGUE:
            continue
        if leagues.load_settings(data_dir, league).get("public", True) is False:
            continue
        out.append(league)
    return out


def _when(x: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(x)) if x else None
    except ValueError:
        return None


def waiver_amount(detail: str | None) -> float | None:
    """A won claim's price in Yahoo's words (``$5 Waiver``); None for any other add (``Free
    Agent``)."""
    if "waiver" not in (detail or "").lower():
        return None
    return dl.bid_of(detail)


def wins_of(rows: Sequence[Mapping[str, Any]], fetched_at: datetime) -> list[Win]:
    """A transactions read's winning waiver claims: each ``add`` row priced ``$N Waiver``, with
    its time in the league's zone (the year from ``fetched_at``) and whether its group has a
    drop."""
    today = fetched_at.astimezone(TRANSACTIONS_TZ).date()
    dropped = {(r.get("group"), r.get("team_id")) for r in rows if r.get("kind") == "drop"}
    out = []
    for r in rows:
        if r.get("kind") != "add" or r.get("team_id") is None:
            continue
        amount = waiver_amount(r.get("detail"))
        at = dl.when_at(r.get("when"), today, TRANSACTIONS_TZ)
        p = r.get("player") or {}
        player = p.get("yahoo_id")
        if amount is None or at is None or player is None:
            continue
        out.append(
            Win(
                at=at,
                player=int(player),
                team=int(r["team_id"]),
                amount=amount,
                with_drop=(r.get("group"), r.get("team_id")) in dropped,
                name=str(p.get("name") or ""),
                nba_team=str(p.get("nba_team") or ""),
            )
        )
    return out


def read_league(paths: Iterable[Path]) -> LeagueReads:
    """A league's stored reads from its snapshot files; a file that does not read is passed
    over."""
    out = LeagueReads()
    for path in sorted(paths):
        try:
            parts = json.loads(path.read_text()).get("parts") or {}
        except (OSError, ValueError):
            continue
        tx = parts.get("transactions") or {}
        at = _when(tx.get("fetched_at"))
        if at is not None and tx.get("source") == TIMES_FROM:
            out.reads.append(at)
            for w in wins_of((tx.get("data") or {}).get("rows") or [], at):
                out.wins.setdefault((w.at, w.player, w.team), w)
        lg = parts.get("league") or {}
        at = _when(lg.get("fetched_at"))
        teams = (lg.get("data") or {}).get("teams") or []
        if at is not None and teams:
            left = {
                int(t["team_id"]): float(t["faab"])
                for t in teams
                if t.get("team_id") is not None and t.get("faab") is not None
            }
            out.faab.append((at, left))
            out.teams = len(teams)
        av = parts.get("available") or {}
        at = _when(av.get("fetched_at"))
        rows = (av.get("data") or {}).get("rows") or []
        if at is not None and rows:
            pct = {
                int(r["player"]["yahoo_id"]): float(r["pct_rostered"])
                for r in rows
                if (r.get("player") or {}).get("yahoo_id") is not None
                and r.get("pct_rostered") is not None
            }
            out.pct.append((at, pct))
    out.reads.sort()
    out.faab.sort(key=lambda x: x[0])
    out.pct.sort(key=lambda x: x[0])
    # The starting budget: the most dollars any team had at the first league read (every
    # league's first read, 2026-10-21, shows a team that had spent nothing).
    if out.faab:
        out.budget = max(out.faab[0][1].values(), default=None)
    return out


def faab_before(
    reads: LeagueReads, team: int, at: datetime
) -> tuple[float | None, datetime | None]:
    """The team's dollars left at the latest league read before ``at``, and that read's time;
    (None, None) when no read before it names the team."""
    for when, left in reversed(reads.faab):
        if when < at and team in left:
            return left[team], when
    return None, None


def pct_on(reads: LeagueReads, player: int, at: datetime) -> float | None:
    """The player's percent rostered at the latest available read at or before ``at`` and within
    :data:`PCT_SPAN` of it; None when no such read lists him."""
    for when, pct in reversed(reads.pct):
        if when > at:
            continue
        if at - when > PCT_SPAN:
            return None
        if player in pct:
            return pct[player]
    return None


def my_claims(data_dir: Path, league: str) -> list[dict[str, Any]]:
    """My placed claims in ``league`` from the queue files, each ``{add, bid, at, resolved}``:
    ``at`` the time it was placed (``outcome_at``)."""
    folder = queue_dir(data_dir)
    out = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            entries = json.loads(path.read_text()).get("entries") or []
        except (OSError, ValueError):
            continue
        for e in entries:
            if str(e.get("league")) != league or e.get("outcome") != "claimed":
                continue
            at = _when(e.get("outcome_at"))
            if at is None or e.get("bid_placed") is None:
                continue
            out.append(
                {
                    "add": int(e["add"]),
                    "bid": e["bid_placed"],
                    "at": at,
                    "resolved": e.get("resolved"),
                }
            )
    return out


def _num(x: float | None) -> str:
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else str(x)


def league_rows(
    league: str, reads: LeagueReads, me: int | None, claims: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, str]], int]:
    """The league's rows, oldest first, and how many of my lost claims found no winner's row."""

    def row(w: Win, ours: str, our_bid: Any) -> dict[str, str]:
        left, read_at = faab_before(reads, w.team, w.at)
        return {
            "league": league,
            "teams": _num(reads.teams),
            "faab_budget": _num(reads.budget),
            "at": w.at.isoformat(),
            "player": str(w.player),
            "name": w.name,
            "nba_team": w.nba_team,
            "amount": _num(w.amount),
            "with_drop": "1" if w.with_drop else "0",
            "winner_faab_left": _num(left),
            "winner_faab_read_at": read_at.isoformat() if read_at else "",
            "pct_rostered": _num(pct_on(reads, w.player, w.at)),
            "ours": ours,
            "our_bid": _num(our_bid),
        }

    wins = sorted(reads.wins.values(), key=lambda w: (w.at, w.player, w.team))
    mine = {c["add"]: c for c in claims if c["resolved"] == "won"}
    out = []
    for w in wins:
        if me is not None and w.team == me:
            c = mine.get(w.player)
            out.append(row(w, WON, c["bid"] if c else None))
        else:
            out.append(row(w, RIVAL, None))
    unmatched = 0
    for c in claims:
        if c["resolved"] != "lost":
            continue
        rival = next(
            (
                w
                for w in wins
                if w.player == c["add"] and w.team != me and c["at"] <= w.at <= c["at"] + LOST_SPAN
            ),
            None,
        )
        if rival is None:
            unmatched += 1
            continue
        out.append(row(rival, LOST, c["bid"]))
    out.sort(key=lambda r: (r["at"], r["player"], r["ours"]))
    return out, unmatched


def table_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def build(data_dir: Path, sha: str, now: datetime, out_dir: Path | None = None) -> dict[str, Any]:
    """Build the table, its ``.sha256`` and its meta in ``out_dir`` (by default
    ``data/sim_share/``); returns the meta. ``sha`` is the checkout's main sha, ``now`` the build
    time."""
    rows: list[dict[str, str]] = []
    per_league = {}
    for league in public_leagues(data_dir):
        reads = read_league(snapshots_dir(data_dir, league).glob("*.json"))
        me = leagues.load_settings(data_dir, league).get("my_team_id")
        claims = my_claims(data_dir, league)
        got, unmatched = league_rows(league, reads, int(me) if me is not None else None, claims)
        rows += got
        ats = [w.at for w in reads.wins.values()]
        per_league[league] = {
            "reads": len(reads.reads),
            "first_read": reads.reads[0].isoformat() if reads.reads else None,
            "last_read": reads.reads[-1].isoformat() if reads.reads else None,
            "first_claim": min(ats).isoformat() if ats else None,
            "last_claim": max(ats).isoformat() if ats else None,
            "rows": len(got),
            "ours_lost_unmatched": unmatched,
        }
    data = table_bytes(rows)
    digest = hashlib.sha256(data).hexdigest()
    folder = out_dir if out_dir is not None else data_dir / SHARE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / TABLE).write_bytes(data)
    (folder / f"{TABLE}.sha256").write_text(f"{digest}  {TABLE}\n")
    meta = {
        "built_at": now.isoformat(timespec="seconds"),
        "main": sha,
        "table": TABLE,
        "sha256": digest,
        "rows": len(rows),
        "columns": list(COLUMNS),
        "leagues": per_league,
        "notes": [
            (
                "one row per winning waiver claim, kept once across reads by (time, player, team);"
                " each read keeps about 25 transactions, so the table is a lower bound"
            ),
            "at: the page's time in America/New_York, its year from the read's fetched_at",
            (
                "transactions: the public reads only; the extension's reads print the user's"
                " profile zone (Pacific) and are left out (reads in the meta count public ones)"
            ),
            "faab_budget: the most dollars any team had at the league's first stored read",
            "winner_faab_left: the latest league read before the claim (read about twice a day)",
            (
                "pct_rostered: the latest available-players read at or before the claim, within"
                " a day; empty when none lists him"
            ),
            (
                "ours: empty for a rival's win, 'won' for mine, 'lost' for my lost claim beside"
                " the rival's winning row (amount = the winning price, our_bid = my bid); a"
                " 'lost' row repeats a rival's win already in the table, so drop ours == 'lost'"
                " before counting the wins"
            ),
        ],
    }
    (folder / META).write_text(json.dumps(meta, indent=2) + "\n")
    return meta
