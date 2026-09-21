from types import SimpleNamespace as NS

import pandas as pd

from pickandroll.sources.matching import match_players, normalize_name
from pickandroll.sources.yahoo import YahooLeague, player_row, slots_from_positions

from .fakes import FakeQuery


def test_slots_from_positions_expands_counts_and_skips_il():
    slots = slots_from_positions([("PG", 1), ("C", 2), ("Util", 2), ("BN", 3), ("IL", 2)])
    assert [s.name for s in slots] == ["PG", "C1", "C2", "Util1", "Util2", "BN1", "BN2", "BN3"]
    assert slots[0].eligible == frozenset({"PG"})
    assert slots[3].accepts(["SF"])


def test_league_info_and_teams():
    league = YahooLeague(league_id="12345", query=FakeQuery())
    info = league.info()
    assert info.num_teams == 12 and info.draft_status == "draft" and not info.is_auction
    assert len(info.slots) == 13
    assert info.cats == ["fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov"]
    teams = league.teams()
    assert [t.is_mine for t in teams] == [True, False]
    assert teams[0].draft_position == 2


def test_players_and_draft_results():
    fake = FakeQuery(picks=[("466.l.12345.t.2", "466.p.0"), ("466.l.12345.t.1", "466.p.1")])
    league = YahooLeague(league_id="12345", query=fake)
    players = league.players()
    assert list(players.index) == ["466.p.0", "466.p.1", "466.p.2"]
    assert players.at["466.p.1", "positions"] == "PG"
    assert players.at["466.p.0", "adp"] == 1.0
    assert league.draft_results() == [
        (1, "466.l.12345.t.2", "466.p.0"),
        (2, "466.l.12345.t.1", "466.p.1"),
    ]


def test_player_row_handles_name_object():
    row = player_row(
        NS(player_key="k", name=NS(full="A B"), eligible_positions="C", draft_analysis=None)
    )
    assert row["name"] == "A B" and row["positions"] == "C" and row["adp"] is None


def test_normalize_name():
    assert normalize_name("Luka Dončić") == "luka doncic"
    assert normalize_name("Jaren Jackson Jr.") == "jaren jackson"
    assert normalize_name("P.J. Washington") == "pj washington"


def test_match_players_with_aliases_and_team_tiebreak():
    yahoo = pd.DataFrame(
        {
            "name": ["Luka Dončić", "Jaren Jackson Jr.", "Nobody Here", "Jalen Williams"],
            "team": ["LAL", "MEM", "XXX", "OKC"],
        },
        index=["k1", "k2", "k3", "k4"],
    )
    proj = pd.DataFrame(
        {
            "player": [
                "Luka Doncic",
                "Jaren Jackson",
                "Jalen Williams",
                "Jalen Williams",
                "Extra Guy",
            ],
            "team": ["LAL", "MEM", "OKC", "PHX", "BOS"],
        },
        index=["luka", "jjj", "jdub", "jwill", "extra"],
    )
    result = match_players(yahoo, proj, aliases={"k3": "extra"})
    assert result.mapping == {"k1": "luka", "k2": "jjj", "k3": "extra", "k4": "jdub"}
    assert result.unmatched_yahoo == []
    assert result.unmatched_projection == ["jwill"]
