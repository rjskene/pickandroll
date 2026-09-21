from pickandroll.draft import LeagueSettings, pick_owner, snake_picks


def test_snake_picks_position_one():
    assert snake_picks(12, 1, 3) == [1, 24, 25]


def test_snake_picks_position_eleven_matches_legacy_draftguide():
    assert snake_picks(12, 11, 4) == [11, 14, 35, 38]


def test_pick_owner_inverts_snake_picks():
    for position in range(1, 13):
        for rnd, pick in enumerate(snake_picks(12, position, 13), start=1):
            assert pick_owner(12, pick) == (rnd, position)


def test_league_settings_defaults():
    s = LeagueSettings()
    assert s.roster_size == 13 and s.total_picks == 156
