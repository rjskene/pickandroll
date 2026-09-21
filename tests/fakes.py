"""Fake Yahoo query with NBA-shaped responses, shared by client and API tests."""

from types import SimpleNamespace as NS


class FakeQuery:
    def __init__(self, picks=None, names=None):
        self.picks = picks if picks is not None else []
        self.names = names or ["Nikola Jokic", "Luka Doncic", "James Harden"]
        self.status = "draft"

    def get_league_key(self):
        return "466.l.12345"

    def get_league_metadata(self):
        return NS(league_key="466.l.12345", name=b"JKR Cup", num_teams=12, draft_status=self.status)

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
                draft_position=2,
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
            NS(pick=i + 1, round=1, team_key=tk, player_key=pk, cost=None)
            for i, (tk, pk) in enumerate(self.picks)
        ]

    def query(self, url, keys):
        assert "sort=AR" in url and "draft_analysis" in url
        start = int(url.split("start=")[1].split(";")[0])
        if start > 0:
            return []
        return [
            NS(
                player_key=f"466.p.{i}",
                player_id=i,
                full_name=name,
                editorial_team_abbr="XXX",
                eligible_positions=["PG", "Util"],
                status="",
                draft_analysis=NS(
                    average_pick=str(i + 1.0), average_round="1.0", percent_drafted="100"
                ),
            )
            for i, name in enumerate(self.names)
        ]
