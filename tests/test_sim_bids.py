"""The winning-bids table for the simulator (#416): built from made-up stored reads."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from pickandroll.api import sim_bids

ME = 4


def _settings(data_dir: Path, league: str, public: bool = True) -> None:
    folder = data_dir / "leagues" / league
    folder.mkdir(parents=True, exist_ok=True)
    body = {"league_id": league, "scoring": "categories", "num_teams": 12, "my_team_id": ME}
    if not public:
        body["public"] = False
    (folder / "settings.json").write_text(json.dumps(body))


def _player(pid: int, name: str = "Some Player", team: str = "CHI") -> dict:
    return {"yahoo_id": pid, "name": name, "nba_team": team, "positions": ["PG"]}


def _row(kind, pid, team, detail, when, group, name="Some Player", nba="CHI"):
    return {
        "kind": kind,
        "player": _player(pid, name, nba),
        "team_id": team,
        "team_name": f"Team Name {team}",
        "detail": detail,
        "when": when,
        "group": group,
    }


def _snapshot(
    data_dir: Path,
    league: str,
    stamp: str,
    fetched_at: str,
    rows=None,
    faab=None,
    available=None,
) -> None:
    folder = data_dir / "leagues" / league / "season" / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    parts: dict = {}
    if rows is not None:
        parts["transactions"] = {"fetched_at": fetched_at, "data": {"rows": rows}}
    if faab is not None:
        parts["league"] = {
            "fetched_at": fetched_at,
            "data": {
                "name": "League Name",
                "teams": [
                    {"team_id": t, "name": f"Team Name {t}", "faab": f} for t, f in faab.items()
                ],
            },
        }
    if available is not None:
        parts["available"] = {
            "fetched_at": fetched_at,
            "data": {
                "rows": [
                    {"player": _player(p), "pct_rostered": v, "availability": "W"}
                    for p, v in available.items()
                ]
            },
        }
    (folder / f"{stamp}-public.json").write_text(
        json.dumps({"received_at": fetched_at, "source": "public", "parts": parts})
    )


def _queue(data_dir: Path, day: str, entries) -> None:
    folder = data_dir / "autopilot" / "queue"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(json.dumps({"date": day, "entries": entries}))


def _build(data_dir: Path):
    meta = sim_bids.build(data_dir, "abc123", datetime(2026, 11, 17, 20, tzinfo=UTC))
    text = (data_dir / "sim_share" / sim_bids.TABLE).read_text()
    return meta, list(csv.DictReader(io.StringIO(text))), text


def test_overlapping_reads_give_each_claim_once_and_only_waiver_adds(tmp_path):
    _settings(tmp_path, "224319")
    claim = _row("add", 10279, 2, "$0 Waiver", "Nov 14, 4:17 am", 1)
    _snapshot(
        tmp_path,
        "224319",
        "20261114T120000Z",
        "2026-11-14T12:00:00+00:00",
        [claim, _row("add", 5000, 3, "Free Agent", "Nov 14, 6:00 am", 0)],
    )
    # The next read shows the same claim at another group number: still one row.
    _snapshot(
        tmp_path,
        "224319",
        "20261115T120000Z",
        "2026-11-15T12:00:00+00:00",
        [_row("add", 7000, 5, "$3 Waiver", "Nov 15, 4:10 am", 0), {**claim, "group": 4}],
    )
    meta, rows, _ = _build(tmp_path)
    assert [(r["player"], r["amount"]) for r in rows] == [("10279", "0"), ("7000", "3")]
    assert rows[0]["at"] == "2026-11-14T04:17:00-05:00"
    assert meta["leagues"]["224319"]["rows"] == 2
    assert meta["leagues"]["224319"]["reads"] == 2


def test_the_year_comes_from_the_read_across_the_year_turn():
    jan_read = datetime(2027, 1, 2, 12, tzinfo=UTC)
    dec_read = datetime(2026, 12, 31, 12, tzinfo=UTC)
    # A January read of a December row: last year's December.
    (w,) = sim_bids.wins_of([_row("add", 1, 2, "$1 Waiver", "Dec 30, 4:00 am", 0)], jan_read)
    assert w.at.isoformat() == "2026-12-30T04:00:00-05:00"
    # A December read of a January row: the January before it, never the one to come.
    (w,) = sim_bids.wins_of([_row("add", 1, 2, "$1 Waiver", "Jan 3, 4:00 am", 0)], dec_read)
    assert w.at.isoformat() == "2026-01-03T04:00:00-05:00"


def test_the_drop_flag_follows_the_group():
    rows = [
        _row("add", 1, 2, "$4 Waiver", "Nov 14, 4:17 am", 0),
        _row("drop", 9, 2, "To Waivers", "Nov 14, 4:17 am", 0),
        _row("add", 3, 5, "$2 Waiver", "Nov 14, 4:17 am", 1),
        _row("drop", 8, 6, "To Waivers", "Nov 14, 4:17 am", 2),
    ]
    flags = {
        w.player: w.with_drop
        for w in sim_bids.wins_of(rows, datetime(2026, 11, 14, 12, tzinfo=UTC))
    }
    assert flags == {1: True, 3: False}


def test_a_row_carries_the_players_name_and_nba_team(tmp_path):
    _settings(tmp_path, "224319")
    _snapshot(
        tmp_path,
        "224319",
        "20261114T120000Z",
        "2026-11-14T12:00:00+00:00",
        [_row("add", 10279, 2, "$0 Waiver", "Nov 14, 4:17 am", 1, "Jaylon Tyson", "CLE")],
    )
    _, rows, _ = _build(tmp_path)
    assert (rows[0]["player"], rows[0]["name"], rows[0]["nba_team"]) == (
        "10279",
        "Jaylon Tyson",
        "CLE",
    )


def test_dollars_left_come_from_the_latest_league_read_before_the_claim(tmp_path):
    _settings(tmp_path, "224319")
    _snapshot(tmp_path, "224319", "20261113T120000Z", "2026-11-13T12:00:00+00:00", faab={2: 90})
    _snapshot(tmp_path, "224319", "20261114T020000Z", "2026-11-14T02:00:00+00:00", faab={2: 80})
    # After the claim (04:17 EST = 09:17 UTC): never this one.
    _snapshot(
        tmp_path,
        "224319",
        "20261114T120000Z",
        "2026-11-14T12:00:00+00:00",
        [_row("add", 10279, 2, "$7 Waiver", "Nov 14, 4:17 am", 1)],
        faab={2: 73},
        available={10279: 41.0},
    )
    _snapshot(
        tmp_path,
        "224319",
        "20261114T080000Z",
        "2026-11-14T08:00:00+00:00",
        available={10279: 38.0},
    )
    _, rows, _ = _build(tmp_path)
    r = rows[0]
    assert (r["winner_faab_left"], r["winner_faab_read_at"]) == ("80", "2026-11-14T02:00:00+00:00")
    assert r["pct_rostered"] == "38"  # the read before the claim, not the one after
    assert (r["teams"], r["faab_budget"]) == ("1", "90")


def test_the_private_league_and_every_team_name_are_absent(tmp_path):
    _settings(tmp_path, "224319")
    _settings(tmp_path, "31822", public=False)
    _settings(tmp_path, "99999", public=False)
    for league in ("224319", "31822", "99999"):
        _snapshot(
            tmp_path,
            league,
            "20261114T120000Z",
            "2026-11-14T12:00:00+00:00",
            [_row("add", 10279, 2, "$5 Waiver", "Nov 14, 4:17 am", 1)],
            faab={2: 80},
        )
    meta, rows, text = _build(tmp_path)
    assert {r["league"] for r in rows} == {"224319"}
    assert set(meta["leagues"]) == {"224319"}
    meta_text = (tmp_path / "sim_share" / sim_bids.META).read_text()
    for out in (text, meta_text):
        assert "31822" not in out and "99999" not in out
        assert "Team Name" not in out and "League Name" not in out
    assert not any(c in sim_bids.COLUMNS for c in ("team", "team_id", "team_name", "winner"))


def test_my_lost_claim_gives_an_ours_row_with_my_bid_and_the_winning_price(tmp_path):
    _settings(tmp_path, "224319")
    _snapshot(
        tmp_path,
        "224319",
        "20261114T120000Z",
        "2026-11-14T12:00:00+00:00",
        [
            _row("add", 10279, 2, "$9 Waiver", "Nov 14, 4:17 am", 0),
            _row("add", 6406, ME, "$8 Waiver", "Nov 14, 4:17 am", 1),
        ],
    )
    _queue(
        tmp_path,
        "2026-11-12",
        [
            {
                "league": "224319",
                "add": 10279,
                "outcome": "claimed",
                "outcome_at": "2026-11-12T09:20:00-06:00",
                "bid_placed": 6,
                "resolved": "lost",
            },
            {
                "league": "224319",
                "add": 6406,
                "outcome": "claimed",
                "outcome_at": "2026-11-12T09:20:00-06:00",
                "bid_placed": 8,
                "resolved": "won",
            },
            # Lost, but its winner's row is not on any read: left out, and counted.
            {
                "league": "224319",
                "add": 1234,
                "outcome": "claimed",
                "outcome_at": "2026-11-12T09:20:00-06:00",
                "bid_placed": 2,
                "resolved": "lost",
            },
            # Another league's claim never joins this one.
            {
                "league": "251146",
                "add": 10279,
                "outcome": "claimed",
                "outcome_at": "2026-11-12T09:20:00-06:00",
                "bid_placed": 3,
                "resolved": "lost",
            },
        ],
    )
    meta, rows, _ = _build(tmp_path)
    got = sorted((r["player"], r["amount"], r["ours"], r["our_bid"]) for r in rows)
    assert got == [
        ("10279", "9", "", ""),
        ("10279", "9", "lost", "6"),
        ("6406", "8", "won", "8"),
    ]
    assert meta["leagues"]["224319"]["ours_lost_unmatched"] == 1


def test_the_meta_sha256_matches_the_tables_bytes(tmp_path):
    _settings(tmp_path, "224319")
    _snapshot(
        tmp_path,
        "224319",
        "20261114T120000Z",
        "2026-11-14T12:00:00+00:00",
        [_row("add", 10279, 2, "$0 Waiver", "Nov 14, 4:17 am", 1)],
    )
    meta, _, _ = _build(tmp_path)
    data = (tmp_path / "sim_share" / sim_bids.TABLE).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert meta["sha256"] == digest
    assert (tmp_path / "sim_share" / f"{sim_bids.TABLE}.sha256").read_text() == (
        f"{digest}  {sim_bids.TABLE}\n"
    )
    on_disk = json.loads((tmp_path / "sim_share" / sim_bids.META).read_text())
    assert on_disk["sha256"] == digest and on_disk["main"] == "abc123"
    assert on_disk["leagues"]["224319"]["first_claim"] == "2026-11-14T04:17:00-05:00"
