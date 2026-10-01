"""Yahoo player list saved from the draft client, and the Yahoo id map built from it.

The draft room speaks Yahoo player ids (``0|overall|yahooId|slot|pos|0``) and its Board tab
shows "F. Last" with an NBA team. ``data/yahoo_players_<league>.json`` is the client's
``/fantasy/v3/players/nba/<league>`` response, saved from a logged-in tab: id, player key, first
and last name, team, eligible positions and Yahoo's average pick. It is data and stays local.

:class:`YahooIdMap` turns those ids into projection ids through :mod:`..matching` (and the
user's alias table), and resolves a Board label to a Yahoo id. Labels are not unique (S. Curry
GSW is Stephen and Seth, J. Williams OKC is Jalen and Jaylin): ties go to the player drafters
value most, the lowest Yahoo average pick.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from ...projections.names import SUFFIXES
from ..matching import MatchResult, match_players

#: Positions in Yahoo's list that are roster slots rather than eligibility.
SLOT_ONLY = {"Util", "UTIL", "BN", "IL", "IL+", "NA", "G", "F"}


def load_players_file(path: Path) -> pd.DataFrame:
    """Read a saved players response into one row per player, indexed by Yahoo id (a string):
    ``player_key, name, first, last, team, positions, adp, o_rank``. ``o_rank`` is Yahoo's
    own ranking, the order its autodraft (and the room's default sort) follows."""
    raw = json.loads(Path(path).read_text())
    items: Any = raw
    if isinstance(raw, dict):
        items = raw.get("service", raw).get("player_list", [])
    rows = []
    for p in items:
        first = str(p.get("fname") or "").strip()
        last = str(p.get("lname") or "").strip()
        positions = [x for x in p.get("pos") or [] if x not in SLOT_ONLY]
        rows.append(
            {
                "yahoo_id": str(p["id"]),
                "player_key": str(p.get("player_key") or p["id"]),
                "name": f"{first} {last}".strip(),
                "first": first,
                "last": last,
                "team": str(p.get("team_abbr") or "").upper(),
                "positions": "/".join(positions),
                "adp": _float(p.get("average-pick")),
                "o_rank": _float(p.get("o_rank")),
            }
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "yahoo_id",
            "player_key",
            "name",
            "first",
            "last",
            "team",
            "positions",
            "adp",
            "o_rank",
        ],
    )
    return df.drop_duplicates("yahoo_id").set_index("yahoo_id")


def label_key(name: str) -> str:
    """``"V. Wembanyama"`` and ``"Victor Wembanyama"`` both become ``"v wembanyama"``: the first
    initial and the normalized rest of the name (suffixes, accents and hyphens dropped)."""
    # Suffixes are dropped after the first token only: "V." is Victor, not a fifth.
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[.'’\-]", "", text.lower()).split()
    if not tokens:
        return ""
    return " ".join([tokens[0][:1], *(t for t in tokens[1:] if t not in SUFFIXES)])


@dataclass
class YahooIdMap:
    players: pd.DataFrame
    mapping: dict[str, str]  # Yahoo id -> projection id
    match: MatchResult
    #: Pins added during the session (Yahoo id -> projection id), on top of the matcher.
    pinned: dict[str, str] = field(default_factory=dict)
    _labels: dict[tuple[str, str | None], list[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for yid, row in self.players.iterrows():
            key = label_key(row["name"])
            self._labels.setdefault((key, row["team"] or None), []).append(yid)
            self._labels.setdefault((key, None), []).append(yid)

    @property
    def reverse(self) -> dict[str, str]:
        return {pid: yid for yid, pid in self.mapping.items()}

    def pid(self, yid: str | int | None) -> str | None:
        return None if yid is None else self.mapping.get(str(yid))

    def yid(self, pid: str) -> str | None:
        return self.reverse.get(pid)

    def known(self, yid: str | int) -> bool:
        return str(yid) in self.players.index

    def name(self, yid: str | int | None) -> str | None:
        if yid is None or str(yid) not in self.players.index:
            return None
        return str(self.players.at[str(yid), "name"])

    def row_name(self, yid: str) -> dict[str, str]:
        """What the drafter matches a Yahoo table row on: initial, last name, NBA team."""
        row = self.players.loc[yid]
        first, last = str(row["first"]), str(row["last"])
        if not last:
            first, _, last = str(row["name"]).partition(" ")
        return {"ini": first[:1], "last": last or str(row["name"]), "team": str(row["team"])}

    def resolve_label(self, label: str, team: str | None = None) -> str | None:
        """Board label ("S. Curry", "GSW") to a Yahoo id: same team first, then any team; a
        tie goes to the lower Yahoo average pick. ``None`` when nothing matches."""
        key = label_key(label)
        team = (team or "").upper() or None
        hits = self._labels.get((key, team)) or self._labels.get((key, None)) or []
        if not hits:
            return None
        if len(hits) == 1:
            return hits[0]
        adp = self.players["adp"]
        return min(hits, key=lambda y: (pd.isna(adp.get(y)), adp.get(y) or 0.0, y))

    def pin(self, yid: str, pid: str) -> None:
        old = self.reverse.get(pid)
        if old is not None and old != yid:
            self.mapping.pop(old, None)
        self.mapping[yid] = pid
        self.pinned[yid] = pid

    def unmatched(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Yahoo players with no projection, the likeliest to be drafted first."""
        rows = self.players.loc[[y for y in self.players.index if y not in self.mapping]]
        rows = rows.sort_values("adp", na_position="last")
        if limit is not None:
            rows = rows.head(limit)
        return [
            {"yahoo_player_id": yid, "name": r["name"], "team": r["team"], "adp": _float(r["adp"])}
            for yid, r in rows.iterrows()
        ]


def build_id_map(
    players: pd.DataFrame,
    projections: pd.DataFrame,
    aliases: Mapping[str, str] | None = None,
) -> YahooIdMap:
    """Match Yahoo players to projection ids. Aliases may be keyed by Yahoo player key, Yahoo
    id or Yahoo name."""
    aliases = dict(aliases or {})
    by_key = players.reset_index().set_index("player_key")
    for yid, key in players["player_key"].items():
        if yid in aliases and key not in aliases:
            aliases[key] = aliases[yid]
    match = match_players(by_key[["name", "team"]], projections, aliases=aliases)
    key_to_yid = dict(zip(players["player_key"], players.index, strict=True))
    mapping = {key_to_yid[k]: pid for k, pid in match.mapping.items()}
    return YahooIdMap(players=players, mapping=mapping, match=match)


def _float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out
