"""The History screen's payload (#334): every move and trade in a league, why it was made and how
it came out. Reads only, and nothing new is written: ``season.history`` joins what the week
records, the snapshot, the queue's day files, the run logs and the decision log already hold."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta, tzinfo
from pathlib import Path
from typing import Any

from pickandroll.season import history as hs
from pickandroll.season.state import Season

from . import season_autopilot, season_decisions, season_queue, season_record, season_scorecard


def queue_entries(data_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Every queue entry of every day, by league. A day file that does not read leaves the rest."""
    out: dict[str, list[dict[str, Any]]] = {}
    for day in season_queue.days(data_dir):
        try:
            queue = season_queue.read(data_dir, day)
        except season_queue.QueueError:
            continue
        for e in (queue or {}).get("entries") or []:
            out.setdefault(str(e.get("league")), []).append(e)
    return out


def _live(data_dir: Path, league: str, key: str) -> list[dict[str, Any]]:
    return [
        dict(run)
        for _, run in season_autopilot.runs(data_dir, league, key)
        if run.get("mode") == "live"
    ]


def runs_of(data_dir: Path, league: str) -> hs.Runs:
    """The league's live runs from its day logs: the drops, the IL moves and the comebacks'
    returns, each return with its run's ``at``."""
    returns = [
        {**s, "at": s.get("at") or run.get("at")}
        for run in _live(data_dir, league, season_autopilot.LINEUP)
        for s in run.get("steps") or []
        if s.get("kind") == "return" and s.get("drop") is not None
    ]
    return hs.Runs(
        drops=_live(data_dir, league, season_autopilot.DROP),
        il=_live(data_dir, league, season_autopilot.IL),
        returns=returns,
    )


def league_rows(
    league: str,
    season: Season,
    season_folder: Path,
    data_dir: Path,
    queue: Sequence[Mapping[str, Any]],
    today: date,
    zone: tzinfo,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """A league's rows and the names of the players its transactions mention."""
    me = season.settings.my_team_id
    transactions = hs.merged(
        (r.get("transactions") or [] for r in season_record.records(season_folder)),
        season.transactions,
    )
    team = season.my_team
    rows = hs.rows_of(
        league,
        me,
        team.name if team is not None else None,
        transactions,
        queue,
        season_decisions.load(season_folder, today),
        runs_of(data_dir, league),
        season_scorecard.logged_move,
        today,
        zone,
        today - timedelta(days=season_queue.PENDING_DAYS),
    )
    names = {str(t.player.yahoo_id): t.player.name for t in transactions}
    players = season.players
    for k in player_ids(rows):
        if str(k) not in names and k in players:
            names[str(k)] = players[k].name
    return rows, names


def player_ids(rows: Iterable[Mapping[str, Any]]) -> set[int]:
    """Every player the rows mention, the steps of their reasons too."""
    out: set[int] = set()
    for r in rows:
        why = r.get("why") or {}
        need = why.get("need")
        found = (
            r.get("player"),
            r.get("add"),
            r.get("drop"),
            *((need or {}).get("for") if isinstance(need, Mapping) else None,),
            *(s.get("player") for s in why.get("steps") or []),
            *((m := why.get("move") or {}).get("add"), m.get("drop")),
        )
        out |= {int(k) for k in found if k is not None}
    return out


def payload(
    rows: Iterable[dict[str, Any]],
    names: Mapping[str, str],
    league: str | None,
    start: date | None,
    end: date | None,
    skipped: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """The screen's rows, newest first, within the filters the route takes (the screen's kind and
    result filters work on what it holds); a row the page gives no date for stays unless a date
    filter is set, since no date can be said to fit."""
    day_set = start is not None or end is not None
    shown = [
        r
        for r in rows
        if (league is None or r["league"] == league)
        and (
            not day_set
            or (
                r["date"] is not None
                and (start is None or r["date"] >= start.isoformat())
                and (end is None or r["date"] <= end.isoformat())
            )
        )
    ]
    return {
        "rows": hs.newest_first(shown),
        "names": dict(names),
        "kinds": list(hs.KINDS),
        "results": list(hs.RESULTS),
        "first_record": hs.FIRST_RECORD.isoformat(),
        "skipped": list(skipped),
    }
