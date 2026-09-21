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
    result.unmatched_projection = [pid for pid in projections.index if pid not in used]
    return result


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {str(k): str(v) for k, v in json.loads(path.read_text()).items()}
