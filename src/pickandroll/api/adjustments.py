"""Games haircuts for a session (#76): the rows a request, a PATCH mid-draft or a league's
``adjustments.json`` gives, resolved to projection ids.

A row names the player by projection id or by name (matched like keeper names, with
:func:`normalize_name`) and the haircut as ``games_fraction``, the share of his projected games
he will play, or ``games_out``, the games he will miss ("out about four weeks" is about fifteen
games). A haircut of nothing (a fraction of one, no games out) is no haircut: on a PATCH it
clears the player's. ``note`` is the user's own words for it (``out 4 weeks``).

The table a session keeps is the resolved rows by id, as the user gave them: a ``games_out`` row
stays one, so a rebuild from the room's log resolves it against the same projections. The
fractions the state scales by come from the projections as loaded
(:mod:`pickandroll.projections.adjustments`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, model_validator

from ..draft import DraftState
from ..projections.adjustments import games_fraction
from ..projections.names import normalize_name


class AdjustmentIn(BaseModel):
    player_id: str | None = Field(default=None, description="projection id")
    player: str | None = Field(default=None, description="or a name, matched like keeper names")
    games_fraction: float | None = Field(
        default=None, ge=0.0, le=1.0, description="the share of his projected games he plays"
    )
    games_out: float | None = Field(
        default=None,
        ge=0.0,
        le=200.0,
        description="or the games he misses (out about four weeks: about fifteen games)",
    )
    note: str | None = Field(default=None, max_length=200, description="e.g. out 4 weeks")

    @model_validator(mode="after")
    def _one_haircut(self) -> AdjustmentIn:
        if (self.games_fraction is None) == (self.games_out is None):
            raise ValueError("give games_fraction or games_out, not both or neither")
        if self.player_id is None and not self.player:
            raise ValueError("give player_id or player")
        return self

    @property
    def clears(self) -> bool:
        """No haircut at all: on a PATCH, the player's is cleared."""
        return self.games_fraction == 1.0 or self.games_out == 0.0


#: A row and where it came from (``adjustments[0]``, ``adjustments.json entry 2``).
Labelled = tuple[str, AdjustmentIn]


def listed(rows: Sequence[AdjustmentIn]) -> list[Labelled]:
    return [(f"adjustments[{i}]", row) for i, row in enumerate(rows)]


def read_adjustments_file(path: Path) -> tuple[list[Labelled], list[str]]:
    """The rows of an ``adjustments.json`` (a list of rows, or ``{"adjustments": [...]}``) and
    a reason for each entry that does not read. A file that does not read at all gives no rows
    and one reason: a prepared list must never stop a draft's attach."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return [], [f"{path.name} does not read ({exc}): no haircuts from it"]
    if isinstance(data, dict):
        data = data.get("adjustments")
    if not isinstance(data, list):
        return [], [f"{path.name} is not a list of adjustments: no haircuts from it"]
    rows: list[Labelled] = []
    problems: list[str] = []
    for i, entry in enumerate(data):
        label = f"{path.name} entry {i + 1}"
        try:
            rows.append((label, AdjustmentIn.model_validate(entry)))
        except ValidationError as exc:
            reason = "; ".join(e["msg"] for e in exc.errors())
            problems.append(f"{label}: {reason}; skipped")
    return rows, problems


def _player_id(label: str, row: AdjustmentIn, df: pd.DataFrame, by_name: dict) -> str:
    if row.player_id is not None:
        if row.player_id not in df.index:
            raise ValueError(f"{label}: unknown player id {row.player_id!r}")
        return row.player_id
    ids = by_name.get(normalize_name(str(row.player)), [])
    if not ids:
        raise ValueError(f"{label}: no projected player named {row.player!r}")
    if len(ids) > 1:
        raise ValueError(f"{label}: {row.player!r} matches {', '.join(ids)}; give player_id")
    return ids[0]


def resolve(
    rows: Sequence[Labelled],
    df: pd.DataFrame,
    table: Sequence[Mapping[str, Any]] = (),
    strict: bool = True,
) -> tuple[list[dict[str, Any]], list[str]]:
    """``rows`` applied over ``table`` (the session's current haircuts, by id): a row sets the
    player's haircut, or clears it (:attr:`AdjustmentIn.clears`); a later row for the same
    player wins. Returns the new table and, unless ``strict`` (which raises ``ValueError``
    naming the row), a reason for each row that was skipped."""
    by_name: dict[str, list[str]] = {}
    for pid, name in df["player"].items():
        by_name.setdefault(normalize_name(name), []).append(str(pid))
    out = {str(e["player_id"]): dict(e) for e in table}
    problems: list[str] = []
    for label, row in rows:
        try:
            pid = _player_id(label, row, df, by_name)
        except ValueError as exc:
            if strict:
                raise
            problems.append(f"{exc}; skipped")
            continue
        out.pop(pid, None)
        if row.clears:
            continue
        entry: dict[str, Any] = {"player_id": pid}
        if row.games_fraction is not None:
            entry["games_fraction"] = float(row.games_fraction)
        else:
            entry["games_out"] = float(row.games_out or 0.0)
        if row.note:
            entry["note"] = row.note
        out[pid] = entry
    return list(out.values()), problems


def fraction(entry: Mapping[str, Any], games: float) -> float:
    """The share of his projected ``games`` a table entry leaves the player."""
    if entry.get("games_fraction") is not None:
        return float(entry["games_fraction"])
    return games_fraction(games, float(entry.get("games_out") or 0.0))


def fractions(table: Sequence[Mapping[str, Any]], df: pd.DataFrame) -> dict[str, float]:
    """The table as the state's fractions, against ``df``'s projected games (as loaded)."""
    return {str(e["player_id"]): fraction(e, float(df.at[e["player_id"], "games"])) for e in table}


def adjustment_rows(state: DraftState, table: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The session's haircuts for the summary and the UI: the player, the games projected and
    left, and the haircut as given."""
    base = state.base_projections.df
    taken = state.taken
    rows = []
    for e in table:
        pid = str(e["player_id"])
        games = float(base.at[pid, "games"])
        share = fraction(e, games)
        rows.append(
            {
                "player_id": pid,
                "name": str(base.at[pid, "player"]),
                "team": str(base.at[pid, "team"] or ""),
                "games_fraction": e.get("games_fraction"),
                "games_out": e.get("games_out"),
                "note": e.get("note"),
                "fraction": round(share, 4),
                "games": round(games, 1),
                "games_left": round(games * share, 1),
                "taken": pid in taken,
            }
        )
    return rows
