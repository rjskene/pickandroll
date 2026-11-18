"""The draft market (#172, PR D4a): the rivals' boards on a table of average draft positions, the
arm's seat on its own forecaster, the market's view, and a pair whose arms draft apart."""

from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pickandroll.sim import adp, opponents, world
from pickandroll.sim import belief as bf
from pickandroll.sim import cli as ss
from pickandroll.sim import readers as reader
from pickandroll.sim import run as rn
from pickandroll.sim import state as sst
from pickandroll.sim.engine import mv
from tests.sim.sim_league import KNOBS, make_data_dir

CATS = ("fg_pct", "ft_pct", "threes", "pts", "reb", "ast", "stl", "blk", "tov")
#: The commands' clock in every test here: a weekday morning outside the routines' window, so
#: the guard lets a run through whenever the suite runs.
BUSINESS_HOURS = datetime(2026, 10, 27, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
#: What two runs of one replay differ in by construction: when they ran.
WHEN = ("started_at", "finished_at")


@pytest.fixture(scope="module", autouse=True)
def pinned_clock():
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(ss, "now_local", lambda: BUSINESS_HOURS)
        yield


SPREAD = adp.Spread(2.0, 0.1)
FLAT = adp.Spread(0.0, 0.0)


def test_a_spread_is_given_as_two_figures_at_least_zero():
    assert adp.parse_spread("2, 0.1") == adp.Spread(2.0, 0.1)
    assert adp.Spread(1.0, 0.5).at(10.0) == 6.0
    assert adp.Spread(0.0, 0.0).payload() == {
        "base": 0.0,
        "growth": 0.0,
        "given": "on the command line",
    }
    for bad in ("2", "a,b", "-1,0", "1,-0.1", "1,2,3", "nan,1"):
        with pytest.raises(ValueError):
            adp.parse_spread(bad)


def test_at_a_zero_spread_a_rival_takes_the_tables_order_exactly():
    picks = {5: 3.0, 2: 1.0, 9: 2.0, 4: 2.0, 30: 0.5}
    value = {7: 1.0, 8: 3.0, 2: 0.0}
    # 30 is listed but cannot be drafted: off the board, and its draw moves nobody else's.
    board = adp.rival_board(picks, [2, 4, 5, 7, 8, 9], value, FLAT, np.random.default_rng(1))
    assert board == [2, 4, 9, 5, 8, 7]
    # Every listed player is drawn for, draftable or not: who can be drafted moves no other
    # player's place.
    g1, g2 = np.random.default_rng(4), np.random.default_rng(4)
    some = adp.rival_board(picks, [2, 4, 5, 9], value, SPREAD, g1)
    more = adp.rival_board(picks, [2, 4, 5, 9, 30], value, SPREAD, g2)
    assert [k for k in more if k != 30] == some


def test_a_player_the_table_does_not_list_is_never_ahead_of_a_listed_one():
    picks = {k: float(k) for k in range(1, 41)}
    unlisted = list(range(41, 61))
    value = dict.fromkeys(unlisted, 100.0) | {k: 0.0 for k in picks}
    moved = False
    for path in range(20):
        g = world.rng(3, path, 1, 0, world.STREAMS["draft"])
        board = adp.rival_board(picks, list(range(1, 61)), value, adp.Spread(30.0, 1.0), g)
        assert set(board[:40]) == set(picks) and board[40:] == unlisted
        moved = moved or board[:40] != sorted(picks)
    assert moved  # not vacuous: the draws did reorder the listed players


def test_each_seat_takes_the_best_left_on_its_own_board_and_a_tie_goes_to_the_lower_id():
    boards = {1: [10, 11, 12, 13], 2: [10, 12, 11, 13], 3: [13, 12]}
    got = sst.board_draft(boards, (1, 2, 3), 2)
    # Round one: 1 takes 10, 2 its next (12), 3 takes 13. Round two, reversed: 3's board is
    # spent, 2 takes 11, 1's is spent.
    assert got == {1: ((10, "BN"),), 2: ((12, "BN"), (11, "BN")), 3: ((13, "BN"),)}
    # Every seat on one board is the snake draft on its order.
    value = {k: float((7 * k) % 11) for k in range(20)}
    ranked = adp.seat_board(value, list(range(20)))
    assert sst.board_draft(dict.fromkeys((1, 2, 3), ranked), (1, 2, 3), 4) == sst.snake_draft(
        list(range(20)), value, (1, 2, 3), 4
    )
    # A seat's own board: by its value, a tie to the lower id, one it cannot value left off.
    assert adp.seat_board({7: 1.0, 3: 1.0, 5: 2.0, 9: 0.5}, [9, 7, 5, 3, 4]) == [5, 3, 7, 9]


def test_draft_is_the_last_stream_and_no_other_moved():
    assert list(world.STREAMS)[-1] == "draft" and world.STREAMS["draft"] == 9
    assert sorted(world.STREAMS.values()) == list(range(10))


def test_the_market_view_is_the_tables_with_the_unlisted_below():
    view = adp.market_view({1: 5.0, 2: 1.0, 6: 3.0}, {3: 2.0, 4: 9.0, 1: 0.0}, [1, 2, 3, 4, 5])
    # 6 is no player of the league; 5 is neither listed nor valued: in no view.
    assert sorted(view, key=lambda k: -view[k]) == [2, 1, 4, 3]
    assert set(view) == {1, 2, 3, 4}


# --------------------------------------------------------------------------- on a made-up season
@pytest.fixture(scope="module")
def season(tmp_path_factory):
    data = make_data_dir(tmp_path_factory.mktemp("market"), wire=120)
    lines, members, scheduled = reader.replay_lines(data, 2024)
    projection = reader.prior_rates(data, 2024)
    table, _ = reader.adp_table(data, 2024, 2025)
    return lines, members, scheduled, projection, table


def _setup(season, draft=None):
    lines, members, scheduled, projection, _ = season
    return ss.replay_setup_of(2024, lines, members, scheduled, projection, draft)


def _boards(season, draft):
    members = season[1]
    setup = _setup(season)
    value = {k: setup.market[k] for k in setup.market}
    return rn.draft_boards(draft, list(members), value, ss.REPLAY_IDS, members, CATS)


def test_the_same_seed_and_path_give_the_same_boards_and_another_path_others(season):
    picks = season[4].picks
    one = _boards(season, adp.Draft(picks, SPREAD, 1, 0))
    assert one == _boards(season, adp.Draft(picks, SPREAD, 1, 0))
    assert one != _boards(season, adp.Draft(picks, SPREAD, 1, 1))
    assert one != _boards(season, adp.Draft(picks, SPREAD, 2, 0))
    # Each seat draws its own board.
    assert len({tuple(b) for b in one.values()}) == len(one)


def test_a_rival_can_draft_a_listed_player_the_forecaster_does_not_project(season):
    _, members, scheduled, projection, table = season
    first = reader.PERIOD_ONE[2024]
    opening = first + timedelta(rn.OPENING_DAYS - 1)
    unprojected = [
        k
        for k in members
        if k not in projection and any(first <= d <= opening for d in scheduled.get(k, []))
    ]
    assert unprojected  # not vacuous: the made-up season has such players
    k = min(unprojected)
    picks = {**table.picks, k: 0.5}
    setup = _setup(season, adp.Draft(picks, FLAT, 1, 0))
    assert setup.rosters[1][0][0] == k and rn.drafted_unprojected(setup) >= 1
    # The draft on the run's forecaster drafts no such player.
    assert rn.drafted_unprojected(_setup(season)) == 0
    # An arm's seat cannot value him and never drafts him; the next seat, a rival, does.
    own = _setup(season, adp.Draft(picks, FLAT, 1, 0, {1: projection}))
    assert all(x != k for x, _ in own.rosters[1]) and own.rosters[2][0][0] == k


def test_an_arm_on_a_forecaster_of_its_own_drafts_on_it(season):
    _, members, _, projection, table = season
    # A made-up second forecaster that disagrees: each projected player gets the rates of the
    # one at the mirrored place in the run's forecaster's order.
    setup = _setup(season)
    order = sorted((k for k in projection if k in members), key=lambda k: (-setup.market[k], k))
    other = {k: projection[order[-1 - i]] for i, k in enumerate(order)}
    mine = _setup(season, adp.Draft(table.picks, SPREAD, 1, 0, {1: projection}))
    theirs = _setup(season, adp.Draft(table.picks, SPREAD, 1, 0, {1: other}))
    assert mine.rosters[1] != theirs.rosters[1]
    # The rivals' boards are the same in both leagues.
    a = _boards(season, adp.Draft(table.picks, SPREAD, 1, 0, {1: projection}))
    b = _boards(season, adp.Draft(table.picks, SPREAD, 1, 0, {1: other}))
    assert a[1] != b[1] and all(a[t] == b[t] for t in ss.REPLAY_IDS if t != 1)


def test_a_market_rival_adds_and_drops_by_the_tables_view(season):
    table = season[4]
    setup = _setup(season, adp.Draft(table.picks, SPREAD, 1, 0))
    value = dict(_setup(season).market)  # the run's forecaster's draft-day values
    assert setup.market == adp.market_view(table.picks, value, list(setup.players))
    state = sst.initial(setup)
    view = setup.market
    # The seat whose weakest player is the market's least wanted.
    team = min(setup.teams, key=lambda t: min(view[k] for k in state.active(t) if k in view))
    pool = [k for k in state.pool if k in view]
    roster = [k for k in state.active(team) if k in view]
    add = max(pool, key=lambda k: (view[k], -k))
    drop = min(roster, key=lambda k: (view[k], k))
    assert view[add] > view[drop]  # not vacuous: the table's view wants a move
    got = opponents.Market(1.0).decide(setup, state, team, {}, {}, {}, np.random.default_rng(0))
    assert got.moves == (mv.Move(add, drop),)


# --------------------------------------------------------------------------- the pair
@pytest.fixture(scope="module")
def pair_data(tmp_path_factory) -> Path:
    data = make_data_dir(tmp_path_factory.mktemp("pair"))
    assert ss.main(["--data", str(data), "--rooms", "0", "fit", "--seasons", "2023-2024"]) == 0
    for name, system, tier in (
        ("A", "bbm", "ranking"),
        ("B", "yahoo", "ranking"),
        ("C", "bbm", "static"),
        ("D", "yahoo", "static"),
    ):
        spec = {
            "name": name,
            "tier": tier,
            "knobs": {**KNOBS, "system": system},
            "opponents": {"kind": "static"},
        }
        (data / f"{name}.json").write_text(json.dumps(spec))
    return data


def _pair(data: Path, a: str, b: str, mp: pytest.MonkeyPatch, *extra: str):
    results, boards = [], []
    task, drafted = ss.task_paired, rn.draft_boards

    def spy_task(*t):
        r = task(*t)
        results.append(r)
        return r

    def spy_boards(*t, **kw):
        out = drafted(*t, **kw)
        boards.append((t[0].path, out))
        return out

    mp.setattr(ss, "task_paired", spy_task)
    mp.setattr(rn, "draft_boards", spy_boards)
    args = [
        "--data",
        str(data),
        "--rooms",
        "0",
        "replay",
        "--seasons",
        "2024",
        "--arms",
        str(data / f"{a}.json"),
        str(data / f"{b}.json"),
        "--bbm-as",
        "prior",
        "--yahoo-as",
        "oracle:0.2",
        "--adp",
        "espn",
        "--adp-spread",
        "2,0.1",
        "--paths",
        "1",
        "--workers",
        "1",
        "--dry-run",
        *extra,
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        assert ss.main(args) == 0
    return results, boards


def test_two_arms_on_one_belief_give_one_draft(pair_data, monkeypatch):
    results, boards = _pair(pair_data, "A", "C", monkeypatch)
    (r,) = results  # a dry run plays the first task only
    assert r["drafts"] == 1 and len(boards) == 1 and len(r["drafted_unprojected"]) == 1


def test_two_arms_on_two_beliefs_give_two_leagues_on_the_same_rivals_boards(pair_data, monkeypatch):
    results, boards = _pair(pair_data, "A", "B", monkeypatch)
    (r,) = results
    me = r["seat"]
    assert r["drafts"] == 2 and len(r["drafted_unprojected"]) == 2
    (pa, ba), (pb, bb) = boards
    assert pa == pb == 0
    assert ba[me] != bb[me]  # each arm's seat on its own belief
    assert all(ba[t] == bb[t] for t in ba if t != me)
    assert all(r["delta"][k] is not None for k in rn.METRICS)


def test_the_market_flags_are_refused_by_name(pair_data, capsys):
    base = ["--data", str(pair_data), "--rooms", "0", "replay", "--seasons", "2024"]
    seats = ["--seats", str(pair_data / "A.json"), str(pair_data / "C.json")]
    cases = [
        (["--adp", "espn"], "names its rivals' spread"),
        (["--adp-spread", "1,0"], "--adp none drafts on the run's forecaster"),
        (["--adp", "espn", "--adp-spread", "1"], "two figures"),
        (["--adp", "espn", "--adp-spread=-1,0"], "at least zero"),
    ]
    for extra, words in cases:
        assert ss.main([*base, *seats, *extra]) == 2
        out = capsys.readouterr().out
        assert out.startswith("refused: ") and words in out, out
    # A season whose log carries one figure for everyone is refused by name, before any path.
    flat = ["--data", str(pair_data), "--rooms", "0", "replay", "--seasons", "2026", *seats]
    assert ss.main([*flat, "--adp", "espn", "--adp-spread", "1,0", "--dry-run"]) == 2
    out = capsys.readouterr().out
    assert "refused: --adp espn: season 2026 has no draft table" in out and "tasks" not in out


# --------------------------------------------------------------------------- the payload
def _run(data: Path, *extra: str) -> dict:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--seasons",
                "2024",
                "--paths",
                "1",
                "--seed",
                "5",
                "--workers",
                "1",
                *extra,
            ]
        )
    out = buf.getvalue()
    assert code == 0, out
    (line_,) = [x for x in out.splitlines() if x.startswith("written: ")]
    return json.loads(Path(line_.removeprefix("written: ")).read_text())


def _as_written(payload: dict) -> str:
    return json.dumps(
        {k: v for k, v in payload.items() if k not in WHEN}, indent=1, sort_keys=True, default=str
    )


def test_a_replay_with_adp_none_named_is_the_replay_with_nothing_named(pair_data):
    seats = ["--seats", str(pair_data / "A.json"), str(pair_data / "C.json")]
    named = _run(pair_data, *seats, "--name", "same", "--adp", "none")
    plain = _run(pair_data, *seats, "--name", "same")
    assert _as_written(named) == _as_written(plain)
    assert plain["replay_version"] == 11 and plain["adp"] == {"source": "none"}
    assert plain["draft"].startswith("snake on the run's forecaster's projection")


def test_a_replay_on_a_table_records_it_in_counts(pair_data):
    seats = ["--seats", str(pair_data / "A.json"), str(pair_data / "C.json")]
    p = _run(pair_data, *seats, "--adp", "espn", "--adp-spread", "2,0.1")
    block = p["adp"]
    assert block["source"] == "espn" and block["spread"] == {
        "base": 2.0,
        "growth": 0.1,
        "given": "on the command line",
    }
    table, sha = reader.adp_table(pair_data, 2024, 2025)
    season = block["seasons"]["2024"]
    assert season == {
        **table.payload(),
        "log_sha256": sha,
        "drafted_unprojected": season["drafted_unprojected"],
    }
    # A room's every seat drafts on its arm's board: no rival drafts a player nobody projects.
    assert season["drafted_unprojected"] == {"drafts": 1, "total": 0, "mean": 0.0, "max": 0}
    assert "pair" not in block and p["pool"]["draft"] == block["pool"]
    assert block["limit"] == ss.ADP_LIMIT and "open with the user" in block["limit"]
    assert p["draft"].startswith("snake in which each seat takes the best player left")
    # No figure of the table is in the payload: only counts and the log's hash.
    assert not any(str(x) in json.dumps(block) for x in table.picks.values() if x != int(x))


def test_a_pair_on_two_beliefs_records_that_it_shares_no_draft(pair_data):
    p = _run(
        pair_data,
        "--arms",
        str(pair_data / "C.json"),
        str(pair_data / "D.json"),
        "--bbm-as",
        "prior",
        "--yahoo-as",
        "oracle:0.2",
        "--adp",
        "espn",
        "--adp-spread",
        "2,0.1",
    )
    season = p["adp"]["seasons"]["2024"]
    assert p["adp"]["pair"].endswith("the pair shares no draft")
    assert season["drafts_per_path"] == [2]
    assert season["drafted_unprojected"]["drafts"] == 2 * p["paths"]
    # Every metric has a difference over the paths.
    diff = p["results"]["2024"]["prior"]["difference"]
    assert all(diff[m]["n"] == p["paths"] for m in rn.METRICS)


def test_a_pair_on_one_belief_records_its_one_draft():
    keys = [{"season": 2024, "forecaster": "prior", "path": p} for p in range(2)]
    results = [{"drafts": 1, "drafted_unprojected": [n]} for n in (3, 1)]
    table = adp.Table("espn", {1: 2.0, 2: 5.0}, 9.0, 4, 0, 6)
    block = ss.adp_block("espn", SPREAD, {2024: (table, "ab")}, keys, results, paired=True)
    assert block["pair"] == "one draft and one league, shared by both arms"
    assert block["limit"] == ss.ADP_LIMIT
    assert ss.adp_block("none", None, {}, keys, results, paired=True) == {"source": "none"}
    assert block["seasons"]["2024"] == {
        **table.payload(),
        "log_sha256": "ab",
        "drafted_unprojected": {"drafts": 2, "total": 4, "mean": 2.0, "max": 3},
        "drafts_per_path": [1],
    }


# --------------------------------------------------------------------------- the no-peek check
#: A day of the made-up season's second week: the check's day.
NO_PEEK_DAY = "2023-11-06"
TABLE = ("--adp", "espn", "--adp-spread", "2,0.1")


def _no_peek(data: Path, *extra: str) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ss.main(
            [
                "--data",
                str(data),
                "--rooms",
                "0",
                "replay",
                "--seasons",
                "2024",
                *extra,
                *TABLE,
                "--no-peek",
                NO_PEEK_DAY,
            ]
        )
    return code, buf.getvalue()


def test_the_no_peek_check_under_a_table_holds_for_a_room_and_a_pair_on_one_belief(pair_data):
    room = ("--seats", str(pair_data / "A.json"), str(pair_data / "C.json"))
    code, out = _no_peek(pair_data, *room)
    assert code == 0 and f"agree through {NO_PEEK_DAY}" in out, out
    assert "refused" not in out
    pair = ("--arms", str(pair_data / "A.json"), str(pair_data / "C.json"))
    code, out = _no_peek(pair_data, *pair, "--bbm-as", "prior", "--yahoo-as", "oracle:0.2")
    assert code == 0 and f"agree through {NO_PEEK_DAY}" in out, out


def _two_beliefs(pair_data, monkeypatch):
    calls = []
    real = rn.paired_apart

    def spy(sa, wa, sb, wb, a, b, me, on_day=None):
        seen = set()

        def keep(r):
            seen.add(r.variant)
            on_day(r)

        out = real(sa, wa, sb, wb, a, b, me, keep)
        calls.append((sa is not sb, seen))
        return out

    monkeypatch.setattr(rn, "paired_apart", spy)
    pair = ("--arms", str(pair_data / "A.json"), str(pair_data / "B.json"))
    code, out = _no_peek(pair_data, *pair, "--bbm-as", "prior", "--yahoo-as", "oracle:0.2")
    return code, out, calls


def test_the_no_peek_check_under_a_table_compares_both_leagues_of_a_pair_on_two_beliefs(
    pair_data, monkeypatch
):
    code, out, calls = _two_beliefs(pair_data, monkeypatch)
    assert code == 0 and f"agree through {NO_PEEK_DAY}" in out, out
    # Two leagues, on the recorded lines and on the changed ones, both arms' days compared.
    assert calls == [(True, {0, 1}), (True, {0, 1})]


def test_the_no_peek_check_under_a_table_catches_a_belief_that_reads_the_days_own_line(
    pair_data, monkeypatch
):
    monkeypatch.setattr(
        bf.CausalBelief,
        "games_before",
        lambda self, player, d: sum(1 for x in self._dates.get(player, []) if x <= d),
    )
    code, out, calls = _two_beliefs(pair_data, monkeypatch)
    assert code == 1 and f"FAILED: the records part on {NO_PEEK_DAY}" in out, out
    assert "beliefs" in out and len(calls) == 2
