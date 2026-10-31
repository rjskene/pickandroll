"""The simulator's readers (#172, PR 2b) on a fixture data folder: the setup from the recorded
state, the gap and the market view, the newest fit, a replay's lines, the exports and the
run's record."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from pickandroll.api import season_sim as reader
from pickandroll.season import weekly as wk
from pickandroll.season.sim.state import initial
from tests.sim_league import LEAGUE, MY_TEAM, TODAY, make_data_dir

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import season_sim as ss


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    """The script's clock reads a weekday morning outside the routines' window, whatever the hour
    the suite runs at (see ``test_season_sim_script.BUSINESS_HOURS``)."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            ss,
            "now_local",
            lambda: datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Toronto")),
        )
        yield


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    folder = make_data_dir(tmp_path_factory.mktemp("sim"))
    assert ss.main(["--data", str(folder), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    return folder


def test_the_setup_comes_from_the_recorded_state(data: Path):
    setup = reader.setup_of(data, LEAGUE, TODAY)
    assert setup.league == LEAGUE and setup.start == TODAY
    assert setup.teams == tuple(range(1, 13)) and MY_TEAM in setup.teams
    assert len(setup.players) == 93 and len(setup.pool) == 21
    assert all(len(r) == 6 for r in setup.rosters.values())
    assert set(setup.projection) == set(setup.players)
    assert setup.roster_slots == ("PG", "SG", "G", "C", "Util", "BN") and setup.cats[0] == "fg_pct"
    assert setup.max_weekly_adds == 4
    # The bracket rows were read: the spec stands; week 3's pairings were not: assumed.
    assert setup.spec is not None and setup.bracket_unread is None
    assert setup.spec.playoff_weeks == (5, 6) and setup.spec.byes == 0 and setup.spec.reseed
    assert setup.assumed_pairings == (3,) and sorted(setup.pairings) == [1, 2, 3, 4]
    assert len(setup.pairings[3]) == 6
    # Adds this week from the transactions page; the market's rate over its days.
    assert setup.adds_used[4] == 1 and setup.adds_used[7] == 1 and setup.adds_used[1] == 0
    assert setup.market_rate == pytest.approx(2 / (2 * 12))
    # Statuses as read; my first player is out.
    out = setup.rosters[MY_TEAM][0][0]
    assert setup.statuses[out] == "O"
    # The gap is read between the two systems over the players both project (the pool).
    assert set(setup.gap) == set(setup.pool)
    assert all(abs(v) <= reader.GAP_CLIP for g in setup.gap.values() for v in g.values())
    assert len(setup.espn_ids) == 93 and len(setup.market) == 93


def test_setup_refuses_a_league_without_a_recorded_season(data: Path):
    (data / "leagues" / "200002").mkdir()
    (data / "leagues" / "200002" / "settings.json").write_text(
        json.dumps(
            {
                "league_id": "200002",
                "scoring": "categories",
                "num_teams": 12,
                "roster": ["PG", "BN"],
                "my_team_id": 1,
            }
        )
    )
    with pytest.raises(reader.SimReadError):
        reader.setup_of(data, "200002", TODAY)


def test_the_gap_the_market_view_and_the_systems_tau(data: Path):
    gap = reader.gap_of(
        {1: {"pts": 10.0, "reb": 2.0}, 2: {"pts": 5.0}},
        {1: {"pts": 5.0, "reb": 0.0}, 3: {"pts": 1.0}},
        clip=0.5,
    )
    assert gap == {1: {**dict.fromkeys(wk.STATS, 0.0), "pts": 0.5}}
    tau = reader.systems_tau(data, LEAGUE)
    assert set(tau) <= set(wk.STATS) and all(v >= 0 for v in tau.values())
    assert reader.systems_tau(data, "200002") == {}


def test_the_newest_fit_is_checked_against_its_hash(data: Path):
    payload, sha, path = reader.newest_fit(data)
    assert path.name == "fit.json" and len(sha) == 64 and payload["hold_out"] == 2025
    assert reader.fit_hash(payload) == sha
    beside = path.with_name("fit.sha256")
    kept = beside.read_text()
    beside.write_text("0" * 64 + "\n")
    with pytest.raises(reader.SimReadError):
        reader.newest_fit(data)
    beside.write_text(kept)
    with pytest.raises(reader.SimReadError):
        reader.newest_fit(data / "nowhere")


def test_a_replays_lines_members_and_schedule(data: Path):
    lines, members, scheduled = reader.replay_lines(data, 2024)
    assert reader.period_date(2024, 1) == date(2023, 10, 24)
    assert reader.period_date(2024, 3) == date(2023, 10, 26)
    with pytest.raises(reader.SimReadError):
        reader.period_date(1999, 1)
    assert len(members) == 93 and all(m.positions for m in members.values())
    pid = next(iter(lines))
    assert pid in members and set(scheduled[pid]) >= set(lines[pid])
    assert all(set(ln) <= set(wk.STATS) for ln in lines[pid].values())
    prior = reader.prior_rates(data, 2025)
    assert set(prior) <= set(members) and all("pts" in r for r in prior.values())
    days = reader.team_days(lines, members)
    assert set(days) == set(members)
    weeks = [(date(2023, 10, 23), date(2023, 10, 29)), (date(2023, 10, 30), date(2023, 11, 5))]
    missed = reader.missed_games(lines, scheduled, weeks)
    assert all(0 <= m <= n for rows in missed.values() for m, n in rows)
    with pytest.raises(reader.SimReadError):
        reader.replay_lines(data, 2020)


def test_the_exports_and_the_realized_rates(data: Path):
    assert reader.export_date(Path("bbm_projections_2026-10-19.csv")) == (date(2026, 10, 19), "")
    assert reader.export_date(Path("bbm_projections_2026-10-19T143209.csv")) == (
        date(2026, 10, 19),
        "143209",
    )
    assert reader.export_date(Path("bbm_ros_pergame_2026-09-21.xls")) is None
    exports, realized, games = ss.residual_inputs(data, LEAGUE)
    assert [d for d, _ in exports] == [date(2026, 10, 19), date(2026, 10, 22)]
    assert len(exports[0][1]) > 80 and all(set(r) == set(wk.STATS) for r in exports[0][1].values())
    assert set(realized) == set(games) and len(games) == 93
    ids = reader.espn_ids(data)
    assert len(ids) == 93 and reader.by_espn({k: 1 for k in ids}, ids) == {
        v: 1 for v in ids.values()
    }


def test_the_run_record_names_the_fit_and_the_hold_out(data: Path, tmp_path: Path):
    with pytest.raises(ValueError):
        reader.write_run(tmp_path, {"kind": "compare", "started_at": "2026-10-24T10:00:00+00:00"})
    path = reader.write_run(
        tmp_path,
        {
            "kind": "compare",
            "name": "A vs B/1",
            "started_at": "2026-10-24T10:00:00+00:00",
            "fit_sha": "x",
            "hold_out": 2025,
        },
    )
    assert (
        path.parent == tmp_path / reader.RUNS_DIR
        and path.name == "20261024T100000Z-compare-A-vs-B-1.json"
    )
    assert json.loads(path.read_text())["hold_out"] == 2025
    assert reader.code_sha(ROOT) is None or len(reader.code_sha(ROOT)) == 40
    assert reader.code_sha(tmp_path) is None


def test_the_recorded_weeks_readers_on_an_empty_folder(data: Path):
    assert reader.recorded_weeks(data, LEAGUE) == []
    record = {
        "teams": {"4": {"totals": {"pts": 100.0}}, "10": {"totals": {}}},
        "matchups": [
            {"teams": [4, 10], "score": [5, 4], "winner": 4},
            {"teams": [1, 2], "score": [4, 4], "winner": None},
            {"teams": [3, 5], "score": None},
        ],
    }
    assert reader.team_week_totals(record) == {4: {"pts": 100.0}}
    assert reader.matchup_outcomes(record) == [(4, 10, 1.0), (1, 2, 0.5), (3, 5, None)]
    assert reader.decisions(data, LEAGUE) == []
    settings = reader.settings_of(data, LEAGUE)
    assert settings.my_team_id == MY_TEAM and settings.playoff_reseeding is True
    assert initial(reader.setup_of(data, LEAGUE, TODAY)).day == TODAY
