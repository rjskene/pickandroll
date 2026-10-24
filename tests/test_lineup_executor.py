"""The lineup executor's API (#170): the steps from Yahoo's lineup as read to the recommended one,
the tip-offs, the mode in ``armed.json``, STOP, the log and the digest's line. Nothing here clicks
anything: the executor is the extension's content script.

The step builder's cases use made-up players (Yahoo-like ids, slot codes); the routes run on the
season tests' fixture league, Yahoo faked.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from pickandroll.api import leagues
from pickandroll.api import season_autopilot as ap
from pickandroll.season import Player, RosterSpot
from pickandroll.season import lineup as lu
from pickandroll.season import weekly as wk
from pickandroll.sources import schedule
from tests.test_lineup import lineup_league, moved
from tests.test_season import LEAGUE, NOW, fixture, season_client

PRIVATE = "100002"
SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "C", "Util", "Util"]
GUARD, WING, BIG, FC, ANY = ["PG", "SG"], ["SF", "PF"], ["C"], ["PF", "C"], ["PG", "SF"]


@pytest.fixture
def client(tmp_path):
    with season_client(tmp_path) as c:
        yield c


# --------------------------------------------------------------------------- the step builder
def legal(lineup: dict, positions: dict, slots=SLOTS) -> bool:
    """Every player where he may stand and no starting slot over its count (the bench takes
    anyone; a held slot stays as it was)."""
    counts: dict[str, int] = {}
    for k, slot in lineup.items():
        if slot.upper() in wk.NOT_STARTING:
            continue
        if not wk.accepts(slot, positions[k]):
            return False
        counts[slot] = counts.get(slot, 0) + 1
    return all(n <= slots.count(s) for s, n in counts.items())


def walk(spots, groups, positions):
    """Apply the steps one by one, every lineup on the way legal; the last one."""
    now = {k: slot for slot, k, _ in spots}
    for step in (s for g in groups for s in g):
        assert now[step.player] == step.from_slot
        if step.swapped is not None:
            assert now[step.swapped] == step.to_slot
        now[step.player] = step.to_slot
        if step.swapped is not None:
            now[step.swapped] = step.from_slot
        assert legal(now, positions), step
    return now


def plan(spots, start, sit, slots=SLOTS):
    target = lu.target_lineup(spots, start, sit, slots)
    assert target is not None
    groups = lu.lineup_steps(spots, target, slots)
    assert groups is not None
    positions = {k: p for _, k, p in spots}
    assert walk(spots, groups, positions) == target
    return target, groups


def test_a_bench_player_goes_to_an_empty_slot_in_one_move():
    spots = [("PG", 1, GUARD), ("C", 2, BIG), ("BN", 3, WING)]
    target, groups = plan(spots, start=[3], sit=[])
    assert groups == [[lu.Step(3, "BN", "SF", None)]]
    assert target == {1: "PG", 2: "C", 3: "SF"}


def test_a_bench_player_takes_a_sitting_starters_slot_in_one_swap():
    spots = [("SF", 1, WING), ("BN", 2, WING)]
    _, groups = plan(spots, start=[2], sit=[1])
    assert groups == [[lu.Step(2, "BN", "SF", 1)]]


def test_a_starter_moves_over_to_make_room_through_the_bench():
    """A centre on the bench must start; the only C slot holds a forward-centre who can move to
    an open PF, and the PF's starter sits."""
    slots = ["PF", "C"]
    spots = [("PF", 1, WING), ("C", 2, FC), ("BN", 3, BIG)]
    target, groups = plan(spots, start=[3], sit=[1], slots=slots)
    assert target == {1: "BN", 2: "PF", 3: "C"}
    # One group: the slots it touches are shared.
    assert len(groups) == 1 and len(groups[0]) == 2


def test_nothing_moves_only_to_match_the_recommended_slot_order():
    """Two lineups that start the same players count the same: no step."""
    spots = [("PG", 1, GUARD), ("SG", 2, GUARD), ("C", 3, BIG), ("C", 4, BIG), ("BN", 5, WING)]
    target, groups = plan(spots, start=[], sit=[])
    assert groups == [] and target == {1: "PG", 2: "SG", 3: "C", 4: "C", 5: "BN"}


def test_two_slots_of_a_kind_and_independent_changes_are_separate_groups():
    spots = [
        ("C", 1, BIG),
        ("C", 2, BIG),
        ("SF", 3, WING),
        ("BN", 4, BIG),
        ("BN", 5, WING),
    ]
    _, groups = plan(spots, start=[4, 5], sit=[2, 3])
    assert sorted(map(len, groups)) == [1, 1]
    moved_ = sorted((s.player, s.swapped) for g in groups for s in g)
    assert moved_ == [(4, 2), (5, 3)]


def test_a_held_player_never_moves_and_no_step_targets_a_held_slot():
    spots = [("SF", 1, WING), ("IL", 2, WING), ("BN", 3, WING)]
    target, groups = plan(spots, start=[3], sit=[1])
    assert target[2] == "IL"
    steps = [s for g in groups for s in g]
    assert all(2 not in (s.player, s.swapped) for s in steps)
    assert all(s.to_slot not in lu.HELD_SLOTS and s.from_slot not in lu.HELD_SLOTS for s in steps)
    # A player in a held slot cannot be started.
    assert lu.target_lineup(spots, [2], [1], SLOTS) is None


def test_a_lineup_the_slots_cannot_hold_has_no_steps():
    spots = [("PG", 1, GUARD), ("BN", 2, GUARD), ("BN", 3, GUARD), ("BN", 4, GUARD)]
    assert lu.target_lineup(spots, [2, 3, 4], [], ["PG", "SG", "C"]) is None
    # A starter in a slot the league does not have: the lineup as read does not fit.
    assert lu.lineup_steps([("SF", 1, WING)], {1: "SF"}, ["PG"]) is None


def test_random_lineups_always_reach_the_recommended_starters_legally():
    """The step builder against the recommendation's own placement, over random rosters: the
    target starts every recommended player who plays, and each step on the way is legal."""
    rng = random.Random(170)
    kinds = [["PG"], ["PG", "SG"], ["SG", "SF"], ["SF", "PF"], ["PF", "C"], ["C"], ["SF"]]
    for _ in range(300):
        roster = {k: rng.choice(kinds) for k in range(1, 14)}
        # Yahoo's lineup as read: a legal placement of a random ten, the rest benched.
        order = rng.sample(sorted(roster), len(roster))
        placed = wk.starters([(k, roster[k]) for k in order[:10]], SLOTS, {})
        spots = [(placed.get(k, "BN"), k, roster[k]) for k in order]
        playing = {k for k in roster if rng.random() < 0.6}
        value = {k: rng.random() for k in roster}
        rec = wk.starters([(k, roster[k]) for k in playing], SLOTS, value)
        day = lu.compare(
            date(2026, 10, 24),
            rec,
            [lu_spot(s, k, roster[k]) for s, k, _ in spots],
            {k: [date(2026, 10, 24)] for k in playing},
            SLOTS,
            roster,
        )
        target, _ = plan(spots, day.start, day.sit)
        started = {k for k, slot in target.items() if slot != "BN" and k in playing}
        assert started >= set(day.started)


def lu_spot(slot, k, positions):
    return RosterSpot(slot, Player(k, f"Player {k}", "AAA", tuple(positions)))


# --------------------------------------------------------------------------- the tip-offs
def scoreboard(*games: tuple[str, str, str]) -> dict:
    return {
        "events": [
            {
                "date": start,
                "status": {"type": {"name": "STATUS_SCHEDULED"}},
                "competitions": [
                    {"competitors": [{"team": {"abbreviation": a}}, {"team": {"abbreviation": b}}]}
                ],
            }
            for start, a, b in games
        ]
    }


def test_the_schedule_keeps_each_teams_tip_off_from_the_same_response(tmp_path):
    body = scoreboard(("2026-10-24T23:00Z", "GS", "LAL"), ("2026-10-25T02:30Z", "NY", "BOS"))
    assert schedule.tips_of(body) == {
        "BOS": "2026-10-25T02:30Z",
        "GSW": "2026-10-24T23:00Z",
        "LAL": "2026-10-24T23:00Z",
        "NYK": "2026-10-25T02:30Z",
    }
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return json.dumps(body)

    day = date(2026, 10, 24)
    schedule.schedule_days([day], fetch, tmp_path, now=NOW)
    assert len(calls) == 1 and schedule.load_tips(day, tmp_path)["GSW"] == "2026-10-24T23:00Z"
    # A copy written before the tip-offs were kept has none.
    (tmp_path / "2026-10-25.json").write_text(json.dumps({"fetched_at": "x", "teams": ["BOS"]}))
    assert schedule.load_tips(date(2026, 10, 25), tmp_path) is None
    assert schedule.load_tips(date(2026, 10, 26), tmp_path) is None


# --------------------------------------------------------------------------- the steps route
def benched_thursday(client) -> None:
    lineup_league(client, **{"2026-10-22": moved(fixture("team4.html"), bench_all=True)})


def benched_saturday(client) -> None:
    """Everyone benched on Saturday, a day most of my players play (the fixture's busy day)."""
    lineup_league(client, **{"2026-10-24": moved(fixture("team4.html"), bench_all=True)})


def lineup_slots(client) -> list[str]:
    """The league's starting slots, as the Lineup view's days list them."""
    lineup = client.get(f"/seasons/{LEAGUE}/lineup").json()
    day = next(d for d in lineup["days"] if d["recommended"] is not None)
    return [x["slot"] for x in day["recommended"]]


def test_the_steps_turn_yahoos_lineup_into_the_recommended_one(client):
    benched_thursday(client)
    r = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": "2026-10-22"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["mode"], s["stop"], s["open"], s["reason"]) == ("dry_run", False, True, None)
    assert s["page"].endswith(f"/{LEAGUE}/4?date=2026-10-22") and s["team"] == 4
    assert s["read"]["page"] == "dated page"
    day = next(
        d
        for d in client.get(f"/seasons/{LEAGUE}/lineup").json()["days"]
        if d["date"] == "2026-10-22"
    )
    # Everyone on the bench: every step starts one of the recommended players.
    assert all(x["from_slot"] == "BN" and x["with"] is None for x in s["steps"])
    assert sorted(x["player"] for x in s["steps"]) == sorted(day["start"])
    assert {int(k) for k in s["target"]} == set(day["start"])
    assert s["games"] == {
        "recommended": day["games"]["recommended"],
        "yahoo": 0,
        "after": day["games"]["recommended"],
    }
    # Each step names its group and its tip-off (the fixture scoreboards carry none).
    assert all(x["group"] is not None and x["tip"] is None for x in s["steps"])
    assert s["skipped"] == []
    # The page's own check: the league's starting slots and Yahoo's lineup as read.
    assert s["slots"] == lineup_slots(client)
    assert s["yahoo"] == {str(x["player"]): x["slot"] for x in day["yahoo"]["slots"]}
    assert all(s["yahoo"][str(x["player"])] == x["from_slot"] for x in s["steps"])


def test_a_group_whose_game_began_is_left_out_whole_and_the_rest_ordered_by_tip(client):
    benched_saturday(client)
    lineup = client.get(f"/seasons/{LEAGUE}/lineup").json()
    day = next(d for d in lineup["days"] if d["date"] == "2026-10-24")
    teams = {k: lineup["players"][str(k)]["nba_team"] for k in day["start"]}
    first, second, *_ = sorted(set(teams.values()))
    began = (NOW - timedelta(minutes=5)).isoformat()
    later = (NOW + timedelta(hours=2)).isoformat()
    # Saturday's copy says the first team's game began and the second tips later.
    path = client.data_dir / "schedule" / "2026-10-24.json"
    body = json.loads(path.read_text())
    path.write_text(json.dumps({**body, "tips": {first: began, second: later}}))
    s = client.get(f"/seasons/{LEAGUE}/lineup/steps", params={"date": "2026-10-24"}).json()
    locked = {k for k, t in teams.items() if t == first}
    assert {p for g in s["skipped"] for p in g["players"]} == locked
    assert all(g["reason"] == "tip-off passed" for g in s["skipped"])
    assert not locked & {x["player"] for x in s["steps"]}
    # The group that tips first runs first; one without a tip-off runs last.
    assert s["steps"][0]["tip"] == later and teams[s["steps"][0]["player"]] == second
    assert s["games"]["after"] == s["games"]["recommended"] - len(locked)


def test_no_steps_when_the_mode_is_off_stop_is_on_or_the_day_is_closed(client):
    benched_thursday(client)
    url = f"/seasons/{LEAGUE}/lineup/steps"
    # A past day, and a day outside the lineup's weeks.
    s = client.get(url, params={"date": "2026-10-20"}).json()
    assert (s["open"], s["steps"], s["reason"]) == (False, [], "the day takes no more changes")
    s = client.get(url, params={"date": "2026-12-30"}).json()
    assert s["reason"] == "the day is not one of the lineup's weeks" and s["steps"] == []
    # Off.
    assert client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "off"}).status_code == 200
    s = client.get(url, params={"date": "2026-10-22"}).json()
    assert (s["mode"], s["open"], s["steps"]) == ("off", True, [])
    assert s["reason"] == "the lineup executor is off in this league"
    # STOP.
    client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "dry_run"})
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    s = client.get(url, params={"date": "2026-10-22"}).json()
    assert (s["stop"], s["steps"]) == (True, []) and s["reason"].startswith("STOP is on")
    # The private league is never touched.
    s = client.get(f"/seasons/{PRIVATE}/lineup/steps").json()
    assert (s["mode"], s["steps"], s["reason"]) == (
        "off",
        [],
        "the private league is never touched",
    )


def test_a_weekly_lineup_is_set_on_the_weeks_first_day_only():
    lineup = {
        "rule": {"changes": "weekly"},
        "start": "2026-10-26",
        "days": [
            {"date": "2026-10-26", "past": False, "recommended": [], "yahoo": None},
            {"date": "2026-10-27", "past": False, "recommended": [], "yahoo": None},
        ],
    }
    mode = {"mode": "dry_run"}
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    args = (LEAGUE, 4)
    later = ap.steps_payload(
        *args, date(2026, 10, 27), date(2026, 10, 25), now, lineup, None, mode, False
    )
    assert later["reason"] == "a weekly lineup is set on the week's first day"
    first = ap.steps_payload(
        *args, date(2026, 10, 26), date(2026, 10, 25), now, lineup, None, mode, False
    )
    assert first["open"] and first["reason"] == "Yahoo's lineup for the day is not read"


# --------------------------------------------------------------------------- the mode
def test_every_public_league_starts_in_dry_run_and_the_private_one_is_off(client):
    assert leagues.lineup_mode(client.data_dir, LEAGUE)["mode"] == "dry_run"
    assert leagues.lineup_mode(client.data_dir, PRIVATE)["mode"] == "off"
    r = client.put(f"/leagues/{PRIVATE}/lineups", json={"mode": "dry_run"})
    assert r.status_code == 409 and "never touched" in r.json()["detail"]
    assert client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "on"}).status_code == 422
    assert client.put("/leagues/999/lineups", json={"mode": "off"}).status_code == 404
    r = client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "off"})
    assert r.status_code == 200 and r.json()["mode"]["mode"] == "off"
    record = json.loads((client.data_dir / "leagues" / LEAGUE / "armed.json").read_text())
    assert record["lineups"] == "off" and record["lineups_by"] == "dashboard"
    assert "armed" not in record and leagues.armed(client.data_dir, LEAGUE) is None


def test_the_drafts_disarm_keeps_the_lineup_mode_and_reads_as_not_armed(client):
    folder = client.data_dir / "leagues" / LEAGUE
    assert client.put(f"/leagues/{LEAGUE}/arm", json={"armed": True}).status_code == 200
    client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "off"})
    assert leagues.armed(client.data_dir, LEAGUE)["armed"] is True
    assert client.put(f"/leagues/{LEAGUE}/arm", json={"armed": False}).json()["armed"] is None
    record = json.loads((folder / "armed.json").read_text())
    assert "armed" not in record and "at" not in record and record["lineups"] == "off"
    # The draft's dropped key reads as not armed; the lineup mode stays.
    assert leagues.armed(client.data_dir, LEAGUE) is None
    assert leagues.lineup_mode(client.data_dir, LEAGUE)["mode"] == "off"


def dry_runs(client, days: int, checked: int) -> None:
    """``days`` days of dry-run logs, on ``checked`` of them a run whose steps all passed."""
    for n in range(days):
        day = date(2026, 10, 1) + timedelta(days=n)
        steps = (
            [{"player": 1, "from_slot": "BN", "to_slot": "SF", "outcome": "would_set"}]
            if n < checked
            else []
        )
        run = {"day": day.isoformat(), "mode": "dry_run", "outcome": "would_set", "steps": steps}
        ap.append_run(client.data_dir, LEAGUE, run, day)


def test_live_waits_for_seven_dry_run_days_two_of_them_with_steps_that_passed(client):
    def put(mode: str):
        return client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": mode})

    r = put("live")
    assert r.status_code == 409 and r.json()["detail"] == "a dry run on 7 days first: 0 so far"
    dry_runs(client, days=7, checked=1)
    r = put("live")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "2 dry-run days with steps that passed every check first: 1 so far"
    )
    # A failed step does not count as passing.
    day = date(2026, 10, 2)
    failed = {"player": 1, "from_slot": "BN", "to_slot": "SF", "outcome": "failed"}
    run = {"day": day.isoformat(), "mode": "dry_run", "outcome": "failed", "steps": [failed]}
    ap.append_run(client.data_dir, LEAGUE, run, day)
    assert put("live").status_code == 409
    dry_runs(client, days=7, checked=2)
    view = client.get(f"/seasons/{LEAGUE}/autopilot").json()
    assert view["live"] == {
        "ok": True,
        "reason": None,
        "dry_run_days": 7,
        "checked_days": 2,
        "needs": {"dry_run_days": 7, "checked_days": 2},
    }
    # STOP holds it back too.
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert put("live").json()["detail"].startswith("STOP is on")
    stop.unlink()
    r = put("live")
    assert r.status_code == 200 and r.json()["mode"]["mode"] == "live"


# --------------------------------------------------------------------------- the log
def run_body(**over) -> dict:
    body = {
        "day": "2026-10-22",
        "mode": "dry_run",
        "trigger": "routine",
        "outcome": "would_set",
        "page": f"/nba/{LEAGUE}/4?date=2026-10-22",
        "read_at": "2026-10-21T17:59:00+00:00",
        "steps": [
            {
                "player": 5161,
                "from_slot": "BN",
                "to_slot": "PG",
                "with": None,
                "tip": None,
                "group": 0,
                "outcome": "would_set",
                "control": {"kind": "select", "slot": "BN", "options": ["PG", "Util", "BN"]},
            }
        ],
        "controls": {"form": "editroster", "method": "post", "fields": ["5161", "date"]},
        "before": {"5161": "BN"},
        "after": {"5161": "PG"},
        "locked": [],
        "extension": "0.6.0",
    }
    return {**body, **over}


def test_a_run_is_appended_to_the_days_log_and_the_panel_shows_it(client):
    url = f"/seasons/{LEAGUE}/autopilot/lineup"
    r = client.post(url, json=run_body())
    assert r.status_code == 200, r.text
    assert r.json()["at"] == NOW.isoformat(timespec="seconds")
    path = client.data_dir / "leagues" / LEAGUE / "autopilot" / "2026-10-21.json"
    # Phase 2's moves beside the runs stay as they are; a second run appends.
    body = json.loads(path.read_text())
    path.write_text(json.dumps({**body, "moves": [{"kept": True}]}))
    assert client.post(url, json=run_body(trigger="panel")).status_code == 200
    body = json.loads(path.read_text())
    assert body["moves"] == [{"kept": True}]
    assert [x["trigger"] for x in body["lineup"]] == ["routine", "panel"]
    assert body["lineup"][0]["steps"][0]["with"] is None
    view = client.get(f"/seasons/{LEAGUE}/autopilot").json()
    assert view["mode"]["mode"] == "dry_run" and view["stop"] is False
    assert view["last"]["trigger"] == "panel" and len(view["today"]) == 2
    assert view["days"] == ["2026-10-21"]


def test_the_log_refuses_the_crumb_a_live_run_a_dry_set_and_anything_under_stop(client):
    url = f"/seasons/{LEAGUE}/autopilot/lineup"
    body = run_body(controls={"fields": ["date"], "crumb": "x"})
    r = client.post(url, json=body)
    assert r.status_code == 422 and "crumb" in r.json()["detail"]
    assert client.post(url, json=run_body(mode="live", outcome="set")).status_code == 409
    r = client.post(url, json=run_body(outcome="set"))
    assert r.status_code == 409 and r.json()["detail"] == "a dry run sets nothing"
    assert client.post(url, json=run_body(trigger="cron")).status_code == 422
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert client.post(url, json=run_body()).status_code == 409
    assert client.post(url, json=run_body(outcome="stopped", steps=[])).status_code == 200
    stop.unlink()
    client.put(f"/leagues/{LEAGUE}/lineups", json={"mode": "off"})
    assert client.post(url, json=run_body()).status_code == 409
    assert client.post(f"/seasons/{PRIVATE}/autopilot/lineup", json=run_body()).status_code == 409


def test_a_log_file_that_does_not_read_is_refused_never_overwritten(client):
    folder = client.data_dir / "leagues" / LEAGUE / "autopilot"
    folder.mkdir(parents=True)
    (folder / "2026-10-21.json").write_text("not json")
    r = client.post(f"/seasons/{LEAGUE}/autopilot/lineup", json=run_body())
    assert r.status_code == 409 and "does not read" in r.json()["detail"]
    assert (folder / "2026-10-21.json").read_text() == "not json"


# --------------------------------------------------------------------------- the digest
def test_the_digest_counts_the_executors_runs_in_one_line_and_names_skips_and_failures(client):
    benched_thursday(client)
    url = f"/seasons/{LEAGUE}/autopilot/lineup"
    client.post(url, json=run_body())
    skipped = {**run_body()["steps"][0], "outcome": "skipped", "reason": "the page did not match"}
    client.post(url, json=run_body(day="2026-10-23", outcome="skipped", steps=[skipped]))
    d = client.get("/flags/digest").json()
    assert d["executor"] == [
        (
            "- Lineup executor (dry run in 1): 1 with steps, 0 with none, 0 not run; 1 day would"
            " be set, 1 skipped, 0 failed."
        ),
        f"- League {LEAGUE}: Fri skipped (the page did not match)",
    ]
    section = d["markdown"][d["markdown"].index("### Lineups") :]
    assert d["executor"][0] in section and d["executor"][1] in section


def test_the_digest_says_when_nothing_ran_and_when_stop_is_on(client):
    modes = {LEAGUE: leagues.lineup_mode(client.data_dir, LEAGUE)}
    modes[PRIVATE] = leagues.lineup_mode(client.data_dir, PRIVATE)
    assert ap.digest_lines(client.data_dir, modes, NOW) == [
        (
            "- Lineup executor (dry run in 1): 0 with steps, 0 with none, 1 not run; 0 days would"
            " be set, 0 skipped, 0 failed."
        )
    ]
    stop = ap.stop_path(client.data_dir)
    stop.parent.mkdir(parents=True, exist_ok=True)
    stop.write_text("")
    assert ap.digest_lines(client.data_dir, modes, NOW) == [
        "- Lineup executor: STOP is on (data/autopilot/STOP); nothing runs."
    ]
    # No armed league: no line.
    assert ap.digest_lines(client.data_dir, {PRIVATE: modes[PRIVATE]}, NOW) == []
