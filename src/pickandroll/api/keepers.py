"""Keeper tables for a session (``docs/KEEPERS.md`` §2): the rows a request or a CSV inside
``data/`` gives, resolved to projection ids. A row names the team by draft position (``me`` or
none for mine), the round the keeper takes, and the player by projection id or by name (matched
like ADP names, with :func:`normalize_name`). With traded picks a team can hold two picks in a
round, so a row may name the overall pick instead (``overall``); the round then follows from it.

Every row travels with a label (``keepers.csv line 3``, ``keepers[0]``) so an error names the
row to fix and the reason."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from ..draft import DraftState, Keeper, KeeperInvalid
from ..draft.settings import round_of
from ..projections.names import normalize_name

KEEPER_COLUMNS = ("position", "round", "player")


class KeeperIn(BaseModel):
    position: int | None = Field(default=None, ge=1, description="draft slot; None = my position")
    round: int | None = Field(default=None, ge=1, description="the round of his pick")
    overall: int | None = Field(
        default=None,
        ge=1,
        description="his pick outright (a team with two picks in a round, traded picks); the "
        "round follows from it when left out",
    )
    player_id: str | None = Field(default=None, description="projection id")
    player: str | None = Field(default=None, description="or a name, matched like ADP names")


#: A keeper row and where it came from, for the error that names it.
Labelled = tuple[str, KeeperIn]


def listed(rows: Sequence[KeeperIn]) -> list[Labelled]:
    """Rows of a request's ``keepers`` list, labelled by index."""
    return [(f"keepers[{i}]", row) for i, row in enumerate(rows)]


def read_keepers_file(path: Path) -> list[Labelled]:
    """The rows of a keepers CSV (``position,round,player``, and an optional ``overall``
    column naming the pick outright, the round then optional; position ``me`` or empty for
    mine), labelled by line; blank lines are skipped. Raises ``ValueError`` naming the line
    that does not read."""
    rows: list[Labelled] = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [str(c).strip().lower() for c in next(reader, [])]
        missing = [c for c in KEEPER_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"{path.name} needs columns {', '.join(KEEPER_COLUMNS)}")
        for record in reader:
            if not any(cell.strip() for cell in record):
                continue
            label = f"{path.name} line {reader.line_num}"
            rec = {c: v.strip() for c, v in zip(header, record, strict=False)}
            position, rnd = rec.get("position", ""), rec.get("round", "")
            overall = rec.get("overall", "")
            try:
                row = KeeperIn(
                    position=None if position.lower() in {"", "me"} else _number(position),
                    round=_number(rnd) if rnd or not overall else None,
                    overall=_number(overall) if overall else None,
                    player=rec.get("player") or None,
                )
            except ValidationError as exc:
                reason = "; ".join(f"{e['loc'][0]} {e['msg'].lower()}" for e in exc.errors())
                raise ValueError(f"{label}: {reason}") from exc
            except ValueError as exc:
                raise ValueError(f"{label}: {exc}") from exc
            rows.append((label, row))
    return rows


def _number(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a whole number") from None


def describe(label: str, row: KeeperIn) -> str:
    team = "me" if row.position is None else f"position {row.position}"
    where = f"pick {row.overall}" if row.overall is not None else f"round {row.round}"
    return f"{label} ({team}, {where}, {row.player_id or row.player!r})"


def resolve_keepers(
    rows: Sequence[Labelled], df: pd.DataFrame, num_teams: int | None = None
) -> list[Keeper]:
    """Rows to keepers on the projection set ``df`` (index: projection id, column ``player``),
    in order; a row that names its pick and not its round gets the round from ``num_teams``.
    Raises ``ValueError`` naming the row whose player is unknown or ambiguous, or that names
    neither round nor pick."""
    by_name: dict[str, list[str]] = {}
    for pid, name in df["player"].items():
        by_name.setdefault(normalize_name(name), []).append(str(pid))
    out = []
    for label, row in rows:
        where = describe(label, row)
        if row.player_id is not None:
            if row.player_id not in df.index:
                raise ValueError(f"{where}: unknown player id")
            pid = row.player_id
        elif row.player:
            ids = by_name.get(normalize_name(row.player), [])
            if not ids:
                raise ValueError(f"{where}: no projected player by that name")
            if len(ids) > 1:
                raise ValueError(f"{where}: the name matches {', '.join(ids)}; give player_id")
            (pid,) = ids
        else:
            raise ValueError(f"{where}: give player_id or player")
        rnd = row.round
        if rnd is None:
            if row.overall is None:
                raise ValueError(f"{where}: give round or overall")
            if num_teams is None:
                raise ValueError(f"{where}: give round")
            rnd = round_of(num_teams, row.overall)
        out.append(Keeper(row.position, rnd, pid, row.overall))
    return out


def keeper_error(rows: Sequence[Labelled], exc: KeeperInvalid) -> str:
    """A refused keeper table's message, naming the row it came from."""
    return f"{describe(*rows[exc.index])}: {exc.reason}"


def keeper_params(keepers: Sequence[Keeper]) -> list[dict[str, Any]]:
    """A keeper table as session-create rows, by projection id (a rebuild resolves them)."""
    return [
        {"position": k.position, "round": k.round, "overall": k.overall, "player_id": k.player_id}
        for k in keepers
    ]


def keeper_rows(state: DraftState) -> list[dict[str, Any]]:
    """The session's keepers in draft order, for the summary and the UI."""
    names = state.projections.df["player"]
    teams = state.team_names()
    rows = []
    for overall, k in sorted(state.keeper_slots.items()):
        position = state.owner_of(overall)[1]
        rows.append(
            {
                "position": position,
                "round": k.round,
                "overall": overall,
                "player_id": k.player_id,
                "name": names.get(k.player_id, k.player_id),
                "team": teams[position],
                "mine": position == state.my_position,
                "applied": overall < state.next_overall,
                # The table named his pick outright (traded picks): it stays put when the
                # owner map changes, where a keeper by round moves with his team's pick.
                "by_overall": k.overall is not None,
            }
        )
    return rows
