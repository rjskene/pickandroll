"""Match player names across sources (Yahoo keys to projection ids).

Names are normalized by stripping accents, punctuation, suffixes and case. Anything the
normalizer cannot reconcile goes into an alias table that the user edits by hand
(``data/aliases.json``, mapping a Yahoo name or key to a projection player id).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..projections.names import normalize_name


@dataclass
class MatchResult:
    mapping: dict[str, str] = field(default_factory=dict)  # yahoo key -> projection id
    unmatched_yahoo: list[str] = field(default_factory=list)
    unmatched_projection: list[str] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)

    @property
    def reverse(self) -> dict[str, str]:
        return {v: k for k, v in self.mapping.items()}


def match_players(
    yahoo: pd.DataFrame,
    projections: pd.DataFrame,
    aliases: Mapping[str, str] | None = None,
) -> MatchResult:
    """Map Yahoo ``player_key`` (index of ``yahoo``) to projection ids (index of ``projections``).

    ``yahoo`` needs ``name`` and optionally ``team``; ``projections`` needs ``player`` and
    optionally ``team``. Ties on name are broken by team when both sides have one.
    """
    aliases = dict(aliases or {})
    by_name: dict[str, list[str]] = {}
    for pid, name in projections["player"].items():
        by_name.setdefault(normalize_name(name), []).append(pid)

    result = MatchResult()
    used: set[str] = set()
    for key, row in yahoo.iterrows():
        alias = aliases.get(key) or aliases.get(str(row["name"]))
        if alias and alias in projections.index:
            result.mapping[key] = alias
            used.add(alias)
            continue
        candidates = by_name.get(normalize_name(row["name"]), [])
        if len(candidates) > 1 and "team" in row and "team" in projections:
            same_team = [
                c
                for c in candidates
                if str(projections.at[c, "team"]).upper() == str(row["team"]).upper()
            ]
            candidates = same_team or candidates
        if len(candidates) == 1:
            result.mapping[key] = candidates[0]
            used.add(candidates[0])
        elif candidates:
            result.ambiguous[key] = candidates
            result.unmatched_yahoo.append(key)
        else:
            result.unmatched_yahoo.append(key)
    _match_short_first_names(yahoo, projections, result, used)
    result.unmatched_projection = [pid for pid in projections.index if pid not in used]
    return result


def _match_short_first_names(
    yahoo: pd.DataFrame, projections: pd.DataFrame, result: MatchResult, used: set[str]
) -> None:
    """Second pass over what is left: same last name, and one first name starts with the other
    (Nic / Nicolas Claxton, Cam / Cameron Johnson, Lu / Luguentz Dort), unique on both sides.
    A plain first initial is not enough: it pairs Darius Brown with Dion Brown."""

    def split(name: str) -> tuple[str, str]:
        tokens = normalize_name(name).split()
        return (tokens[0], " ".join(tokens[1:])) if len(tokens) > 1 else ("", "")

    def short(a: str, b: str) -> bool:
        return bool(a and b) and (a.startswith(b) or b.startswith(a))

    left = [pid for pid in projections.index if pid not in used]
    by_last: dict[str, list[tuple[str, str]]] = {}
    for pid in left:
        first, last = split(projections.at[pid, "player"])
        if last:
            by_last.setdefault(last, []).append((first, pid))
    waiting = [k for k in result.unmatched_yahoo if k not in result.ambiguous]
    yahoo_by_last: dict[str, list[tuple[str, str]]] = {}
    for key in waiting:
        first, last = split(yahoo.at[key, "name"])
        if last:
            yahoo_by_last.setdefault(last, []).append((first, key))
    for last, keys in yahoo_by_last.items():
        for first, key in keys:
            hits = [pid for f, pid in by_last.get(last, []) if short(first, f) and pid not in used]
            if len(hits) != 1:
                continue
            target = projections.at[hits[0], "player"]
            rivals = [k for f, k in keys if short(f, split(target)[0])]
            if rivals != [key]:
                continue
            result.mapping[key] = hits[0]
            result.unmatched_yahoo.remove(key)
            used.add(hits[0])


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(path.read_text()).items()}
