from types import SimpleNamespace as NS

import pandas as pd

from pickandroll.sources.matching import match_players, normalize_name
from pickandroll.sources.yahoo import YahooLeague, player_row, slots_from_positions


class FakeQuery:
    """Stands in for yfpy's YahooFantasySportsQuery with canned NBA-shaped responses."""

    def get_league_key(self):
        return "466.l.12345"

    def get_league_metadata(self):
        return NS(league_key="466.l.12345", name=b"JKR Cup", num_teams=12, draft_status="draft")

    def get_league_settings(self):
        return NS(
            draft_type="live",
            is_auction_draft=0,
            draft_time=1760000000,
            scoring_type="headone",
            roster_positions=[
                NS(position="PG", count=1),
                NS(position="SG", count=1),
                NS(position="G", count=1),
                NS(position="SF", count=1),
                NS(position="PF", count=1),
                NS(position="F", count=1),
                NS(position="C", count=2),
                NS(position="Util", count=2),
                NS(position="BN", count=3),
                NS(position="IL", count=2),
            ],
            stat_categories=NS(
                stats=[
                    NS(display_name=n, is_only_display_stat=0)
                    for n in ["FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO"]
                ]
                + [NS(display_name="FGM/A", is_only_display_stat=1)]
            ),
        )

    def get_league_teams(self):
        return [
            NS(
                team_key="466.l.12345.t.1",
                team_id=1,
                name=b"Me",
                draft_position=3,
                is_owned_by_current_login=1,
            ),
            NS(
                team_key="466.l.12345.t.2",
                team_id=2,
                name=b"Them",
                draft_position=1,
                is_owned_by_current_login=0,
            ),
        ]

    def get_league_draft_results(self):
        return [
            NS(pick=2, round=1, team_key="466.l.12345.t.1", player_key="466.p.6", cost=None),
            NS(pick=1, round=1, team_key="466.l.12345.t.2", player_key="466.p.5", cost=None),
        ]

    def query(self, url, keys):
        assert "sort=AR" in url and "draft_analysis" in url
        start = int(url.split("start=")[1].split(";")[0])
        if start > 0:
            return []
        return [
            NS(
                player_key="466.p.5",
                player_id=5,
                full_name="Nikola Jokic",
                editorial_team_abbr="DEN",
                eligible_positions=["C", "Util"],
                status="",
                draft_analysis=NS(average_pick="1.3", average_round="1.0", percent_drafted="100"),
            ),
            NS(
                player_key="466.p.6",
                player_id=6,
                full_name="Luka Dončić",
                editorial_team_abbr="LAL",
                eligible_positions=["PG", "SG", "G", "Util"],
                status="",
                draft_analysis=NS(average_pick="2.9", average_round="1.0", percent_drafted="100"),
            ),
            NS(
                player_key="466.p.7",
                player_id=7,
                full_name="Jaren Jackson Jr.",
                editorial_team_abbr="MEM",
                eligible_positions=["PF", "C", "F"],
                status="GTD",
                draft_analysis=NS(average_pick="-", average_round="-", percent_drafted="-"),
            ),
        ]


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
    assert teams[0].draft_position == 3


def test_players_and_draft_results():
    league = YahooLeague(league_id="12345", query=FakeQuery())
    players = league.players()
    assert list(players.index) == ["466.p.5", "466.p.6", "466.p.7"]
    assert players.at["466.p.6", "positions"] == "PG/SG"
    assert players.at["466.p.5", "adp"] == 1.3
    assert players.at["466.p.7", "adp"] is None or pd.isna(players.at["466.p.7", "adp"])
    assert league.draft_results() == [
        (1, "466.l.12345.t.2", "466.p.5"),
        (2, "466.l.12345.t.1", "466.p.6"),
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
