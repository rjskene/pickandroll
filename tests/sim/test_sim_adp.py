"""The draft market (#172, PR D4a): a season's table of average draft positions, read from its
own log."""

from __future__ import annotations

import hashlib
import json

import pytest

from pickandroll.sim import adp
from pickandroll.sim import readers as reader
from tests.sim.sim_league import ADP_CEILING, make_data_dir


def _body(figures: list[object]) -> dict[str, object]:
    return {
        "players": [
            {"player": {"id": 100 + i, "ownership": {"averageDraftPosition": x}}}
            for i, x in enumerate(figures)
        ]
    }


def test_the_ceiling_is_the_figure_the_most_players_share_and_is_not_listed():
    table = adp.espn_table(_body([3.0, 1.5, 9.0, 9.0, 9.0, None, 9.5, True, -1.0, float("nan")]))
    assert table.ceiling == 9.0 and table.at_ceiling == 3
    # A player above the ceiling (drafted late somewhere) is listed; no figure, a flag, a
    # negative or NaN is no figure.
    assert dict(table.picks) == {100: 3.0, 101: 1.5, 106: 9.5}
    assert table.no_figure == 4 and table.players == 10
    assert table.payload() == {
        "source": "espn",
        "column": "ownership.averageDraftPosition",
        "players": 10,
        "listed": 3,
        "at_ceiling": 3,
        "no_figure": 4,
    }
    # No figure shared: no ceiling, everyone listed.
    alone = adp.espn_table(_body([2.0, 1.0, 4.0]))
    assert alone.ceiling is None and alone.at_ceiling == 0 and len(alone.picks) == 3


def test_a_log_with_one_figure_for_everyone_holds_no_table():
    with pytest.raises(adp.NoTable, match="one and the same draft position"):
        adp.espn_table(_body([7.0, 7.0, 7.0]))
    with pytest.raises(adp.NoTable, match="no draft position"):
        adp.espn_table(_body([None, None]))
    with pytest.raises(adp.NoTable, match="no draft position"):
        adp.espn_table({"players": []})


def test_a_seasons_table_comes_from_its_own_log(tmp_path):
    data = make_data_dir(tmp_path)
    table, sha = reader.adp_table(data, 2024, 2025)
    path = data / reader.LOGS_DIR / "2024.json"
    assert sha == hashlib.sha256(path.read_bytes()).hexdigest()
    body = json.loads(path.read_text())["body"]
    figures = {
        int(r["player"]["id"]): r["player"]["ownership"]["averageDraftPosition"]
        for r in body["players"]
    }
    assert table.source == "espn" and table.players == len(figures)
    assert table.ceiling == ADP_CEILING and table.no_figure == 0
    # Not vacuous: both groups are there, and they part the log.
    assert table.at_ceiling > 0 and len(table.picks) > 0
    assert len(table.picks) + table.at_ceiling == table.players
    assert all(figures[k] == x and x != ADP_CEILING for k, x in table.picks.items())
    assert sum(1 for x in figures.values() if x == ADP_CEILING) == table.at_ceiling
    # Each season's log is its own table.
    other, _ = reader.adp_table(data, 2023, 2025)
    assert dict(other.picks) != dict(table.picks)


def test_a_season_whose_log_carries_one_figure_is_refused_by_name(tmp_path):
    data = make_data_dir(tmp_path)
    with pytest.raises(
        reader.SimReadError, match="season 2026 has no draft table: its log carries"
    ):
        reader.adp_table(data, 2026, 2025)
    with pytest.raises(reader.SimReadError, match="season 2022: no cached log"):
        reader.adp_table(data, 2022, 2025)


def test_the_hold_out_is_refused_before_its_log_is_opened(tmp_path):
    data = make_data_dir(tmp_path)
    # Not a log at all: opening it would fail otherwise.
    (data / reader.LOGS_DIR / "2025.json").write_text("not json")
    with pytest.raises(reader.SimReadError, match="2025 is the hold-out; no run plays it"):
        reader.adp_table(data, 2025, 2025)
