"""The soak comparison (#225): two data folders, the Mac's live day and the droplet's dry run,
bundled and compared; the expected differences stay unflagged, the real ones are named by id.
Nothing here touches ssh, GitHub or the real data folder."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "soak_compare.py"
DAY = "2026-10-31"
PAGE = "/nba/251146/7?date=2026-10-31"
STEPS = ("api", "exports", "private_pages", "lineup_pages", "refresh", "solve", "digest", "post")
EXPORTS = {
    "ros": "bbm_projections_2026-10-31.csv",
    "week_this": "bbm_week_this_20261031-{t}.xls",
    "week_next": "bbm_week_next_20261031-{t}.xls",
    "actual_7d": "bbm_actual_7d_totals_20261031-{t}.xls",
    "actual_14d": "bbm_actual_14d_totals_20261031-{t}.xls",
}
LEAGUES = ("223259", "251146")
ENTRY_A = f"{DAY}:251146:6406:6751"
ENTRY_B = f"{DAY}:223259:10279:0"


@pytest.fixture(scope="module")
def sc():
    spec = importlib.util.spec_from_file_location("soak_compare", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(root: Path, rel: str, payload) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload))


def marker(side: str) -> dict:
    steps = {k: {"status": "ok", "detail": f"{k} done"} for k in STEPS}
    if side == "droplet":
        steps["post"] = {"status": "skipped", "detail": "posting off"}
        steps["solve"] = {"status": "ok", "detail": "9 leagues solved, all 200; left out: 31822"}
        finished, stamp = f"{DAY}T06:12:00-05:00", "0503"
    else:
        steps["solve"] = {"status": "ok", "detail": "10 of 10 leagues 200"}
        finished, stamp = f"{DAY}T06:30:00-05:00", "0501"
    exports = {k: v.format(t=stamp) for k, v in EXPORTS.items()}
    return {
        "started_at": f"{DAY}T05:00:10-05:00",
        "finished_at": finished,
        "steps": steps,
        "exports": exports,
    }


def daily_run() -> dict:
    codes = {league: 202 for league in LEAGUES}
    steps = [
        {"name": "window", "status": "ok", "detail": "05:00 is inside the daily window"},
        {"name": "api", "status": "ok", "detail": "200 on first check"},
        {"name": "exports", "status": "ok", "detail": "5 of 5 due saved"},
        {"name": "private_pages", "status": "ok", "detail": "4 pages opened"},
        {"name": "lineup_pages", "status": "ok", "detail": "9 pages opened"},
        {
            "name": "refresh",
            "status": "ok",
            "detail": "2 leagues refreshed",
            "data": {"codes": codes},
        },
        {
            "name": "solve",
            "status": "ok",
            "detail": "2 leagues solved, all 200; left out: 31822",
            "data": {
                "codes": {**{league: 200 for league in LEAGUES}, "31822": 599},
                "left_out": ["31822"],
            },
        },
        {"name": "queue_build", "status": "ok", "detail": "2 entries queued"},
        {"name": "digest", "status": "ok", "detail": "3 leagues, 0 skipped"},
        {"name": "post", "status": "skipped", "detail": "posting off"},
    ]
    return {
        "routine": "daily",
        "started_at": f"{DAY}T05:00:10-05:00",
        "finished_at": f"{DAY}T06:12:00-05:00",
        "refused": None,
        "stopped": False,
        "steps": steps,
        "alerts": [],
        "exports": {},
        "failed": False,
    }


def queue(side: str) -> dict:
    tag = "mac" if side == "mac" else "vm"
    rows = [
        {
            "league": league,
            "status": "queued",
            "decision": "go",
            "cap": 1,
            "budget": 93.0,
            "adds": {"limit": 4, "used": 3, "left": 1},
        }
        for league in LEAGUES
    ]
    entries = [
        {
            "id": ENTRY_A,
            "league": "251146",
            "set": "three",
            "judged": "three",
            "from": "2026-11-02",
            "availability": "W",
            "queued": True,
            "struck": False,
            "rank": 1,
            "bid": {"amount": 1, "reason": "$1: a routine stream"},
            "decision": f"2026103111275{tag}-moves-bbm",
            "outcome": "claimed" if side == "mac" else None,
        },
        {
            "id": ENTRY_B,
            "league": "223259",
            "set": "three",
            "judged": "three",
            "from": "2026-11-02",
            "availability": "FA",
            "queued": True,
            "struck": False,
            "rank": 1,
            "bid": {"amount": 0, "reason": "an open spot"},
            "decision": f"2026103111280{tag}-moves-bbm",
            "outcome": "skipped" if side == "mac" else None,
        },
    ]
    return {
        "date": DAY,
        "built": [f"{DAY}T11:29:00+00:00"],
        "execute_time": "09:00",
        "leagues": rows,
        "entries": entries,
    }


def decisions() -> list:
    moves = {
        "id": "20261031T112753-moves-bbm",
        "at": f"{DAY}T11:27:53+00:00",
        "source": "moves",
        "system": {"key": "bbm", "file": "bbm_projections_2026-10-31.csv"},
        "pool": {"size": 30, "candidates": 212},
        "plan": {"recommended": False, "reason": "short"},
        "sets": [
            {
                "key": "week",
                "moves": [{"add": 6406, "drop": 6751, "gain": {"week": 0.27, "three": -0.12}}],
            },
            {"key": "three", "moves": []},
        ],
    }
    strategy = {"id": "x-strategy", "at": f"{DAY}T12:00:00+00:00", "source": "strategy", "sets": []}
    return [moves, strategy]


def executor(side: str) -> dict:
    if side == "mac":
        return {
            "lineup": [
                {
                    "mode": "live",
                    "outcome": "set",
                    "page": PAGE,
                    "after": {"6173": "Util", "6047": "BN"},
                }
            ],
            "moves": [{"mode": "live", "outcome": "claimed"}],
        }
    return {
        "lineup": [
            {
                "mode": "dry_run",
                "outcome": "would_set",
                "page": PAGE,
                "controls": {"would_set": {"6173": "Util", "6047": "BN"}},
            }
        ],
        "moves": [{"mode": "dry_run", "outcome": "would_claim"}],
    }


def side(root: Path, name: str) -> Path:
    """One host's data folder for the day: the baseline pair differs only where the soak must."""
    data = root / name / "data"
    write(data, "routine/daily.json", marker(name))
    if name == "droplet":
        write(data, f"routine/runs/{DAY}-daily.json", daily_run())
        write(
            data,
            f"routine/runs/{DAY}-signin.json",
            {"routine": "signin", "steps": [], "alerts": []},
        )
    for template in EXPORTS.values():
        write(
            data,
            template.format(t="0501" if name == "mac" else "0503"),
            "x" * (1000 if name == "mac" else 990),
        )
    write(data, f"autopilot/queue/{DAY}.json", queue(name))
    summary = (
        "2 add pages opened in 2 leagues"
        if name == "mac"
        else "would open 2 add pages in 2 leagues"
    )
    write(
        data,
        f"autopilot/passes/{DAY}.json",
        {
            "passes": [
                {
                    "id": f"{DAY}:moves:1",
                    "kind": "moves",
                    "trigger": "routine",
                    "end": "done",
                    "summary": summary,
                    "outcomes": {ENTRY_A: "claimed" if name == "mac" else "would_claim"},
                }
            ]
        },
    )
    mode = "live" if name == "mac" else "dry_run"
    for league in LEAGUES:
        write(data, f"leagues/{league}/armed.json", {"moves": mode, "lineups": mode})
        write(data, f"leagues/{league}/season/decisions/{DAY}.json", decisions())
    write(data, f"leagues/251146/autopilot/{DAY}.json", executor(name))
    if name == "mac":
        write(data, f"leagues/31822/season/decisions/{DAY}.json", decisions())
    (data / "leagues" / "_shared").mkdir()
    return data


def pair(tmp_path: Path, sc) -> tuple[dict, dict]:
    return sc.bundle(side(tmp_path, "mac"), DAY), sc.bundle(side(tmp_path, "droplet"), DAY)


def compare(sc, mac: dict, vm: dict):
    return sc.Comparison(mac, vm, DAY, "31822").run()


# --------------------------------------------------------------------------- the bundle
def test_the_bundle_reads_only_the_day_and_sizes_the_marker_exports(tmp_path, sc):
    data = side(tmp_path, "droplet")
    write(data, "routine/runs/2026-10-30-daily.json", {"routine": "daily"})  # another day: not read
    b = sc.bundle(data, DAY)
    assert sorted(b["runs"]) == ["daily", "signin"]
    assert b["exports"]["ros"] == {"name": "bbm_projections_2026-10-31.csv", "size": 990}
    assert sorted(b["decisions"]) == list(LEAGUES) and sorted(b["executor"]) == ["251146"]
    assert b["armed"]["251146"] == {"moves": "dry_run", "lineups": "dry_run"}
    assert b["marker"]["steps"]["post"]["status"] == "skipped" and b["date"] == DAY
    # a marker from another day lends no export sizes
    write(
        data, "routine/daily.json", {**marker("droplet"), "started_at": "2026-10-30T05:00:10-05:00"}
    )
    assert sc.bundle(data, DAY)["exports"] == {}
    assert sc.bundle(tmp_path / "nowhere", DAY)["marker"] is None


# --------------------------------------------------------------------------- the comparison
def test_the_baseline_pair_has_nothing_flagged_and_names_the_expected_differences(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    c = compare(sc, mac, vm)
    assert c.flags == []
    text = c.render()
    assert "**nothing flagged**" in text
    assert "31822: not solved on the droplet (left out by design)" in text
    assert "251146: same sets" in text and "223259: same sets" in text
    assert "lineup /nba/251146/7?date=2026-10-31: the droplet's 2 would-set slots match" in text
    assert "| post | ok | skipped |" in text and "posting off" in text
    assert "entries: 2 on the mac, 2 on the droplet, 2 shared by id" in text
    assert "outcomes (shown, not counted): mac claimed x1, skipped x1; droplet None x2" in text
    assert "would open 2 add pages" in text and "would_claim x1" in text
    assert "no run log yet: morning, late, evening-build, evening-pass, monday" in text
    assert "moves live x2, lineups live x2; droplet moves dry_run x2, lineups dry_run x2" in text


def test_a_queue_entry_that_differs_or_exists_on_one_side_is_flagged_by_id(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    vm["queue"]["entries"][0]["bid"]["amount"] = 3
    vm["queue"]["entries"][0]["from"] = "2026-11-03"
    vm["queue"]["entries"].append({**vm["queue"]["entries"][1], "id": f"{DAY}:223259:5555:0"})
    vm["queue"]["leagues"][0]["adds"]["left"] = 0
    vm["queue"]["execute_time"] = "09:30"
    c = compare(sc, mac, vm)
    assert c.flags == [
        "queue execute time: mac 09:00, droplet 09:30",
        "queue league 223259 adds left: mac 1, droplet 0",
        f"queue entry {DAY}:223259:5555:0 only on the droplet",
        f"queue entry {ENTRY_A} differs in from, bid: from mac 2026-11-02 / droplet 2026-11-03; bid mac 1 / droplet 3",
    ]
    del vm["queue"]
    c = compare(sc, mac, {**vm, "queue": None})
    assert c.flags == [f"queue file for {DAY} only on the mac"]


def test_exports_missing_smaller_or_unsaved_on_the_droplet_are_flagged(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    del vm["exports"]["week_next"]
    vm["exports"]["actual_7d"]["size"] = 500
    vm["exports"]["ros"]["size"] = None
    c = compare(sc, mac, vm)
    assert c.flags == [
        "export ros on the droplet: the marker names bbm_projections_2026-10-31.csv but the file is missing",
        "export week_next missing on the droplet",
        "export actual_7d on the droplet is 50% smaller (500 against 1000 bytes)",
    ]
    assert "| week_next | bbm_week_next_20261031-0501.xls (1000) | - |" in c.render()


def test_a_failed_step_a_bad_code_an_alert_and_a_late_daily_on_the_droplet_are_flagged(
    tmp_path, sc
):
    mac, vm = pair(tmp_path, sc)
    vm["marker"]["steps"]["refresh"] = {
        "status": "failed",
        "detail": "1 of 2 ok; 251146 failed twice (999)",
    }
    vm["marker"]["finished_at"] = f"{DAY}T06:31:00-05:00"
    daily = vm["runs"]["daily"]
    refresh = next(s for s in daily["steps"] if s["name"] == "refresh")
    refresh.update(
        status="failed",
        detail="251146 failed twice (999)",
        data={"codes": {"223259": 202, "251146": 999}},
    )
    daily["alerts"] = ["the browser profile is signed out of bbm"]
    c = compare(sc, mac, vm)
    assert c.flags == [
        "the droplet's daily finished at 06:31, after the window's 06:20",
        "daily refresh: mac ok, droplet failed",
        "droplet daily: step refresh failed: 251146 failed twice (999)",
        "droplet daily alert: the browser profile is signed out of bbm",
        "droplet refresh of 251146 answered 999",
    ]
    text = c.render()
    assert "Details that differ:" in text and "- refresh: mac refresh done" in text


def test_the_private_league_and_the_droplets_post_step_are_never_findings(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    mac["marker"]["steps"]["post"] = {"status": "failed", "detail": "gh failed twice"}
    assert compare(sc, mac, vm).flags == []
    # the solve's 599 for the private league is left out by the step; once it is not, it is a finding
    solve = next(s for s in vm["runs"]["daily"]["steps"] if s["name"] == "solve")
    solve["data"]["left_out"] = []
    c = compare(sc, mac, vm)
    assert c.flags == []  # --private still covers it
    assert compare(sc, mac, vm).left_out() == {"31822"}
    c = sc.Comparison(mac, vm, DAY, "0").run()
    assert (
        "droplet solve of 31822 answered 599" in c.flags
        and "31822: no moves solve on the droplet today" in c.flags
    )


def test_lineup_set_and_system_differences_are_flagged(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    vm["executor"]["251146"]["lineup"][0]["controls"]["would_set"] = {
        "6173": "BN",
        "6047": "BN",
        "7000": "PG",
    }
    entry = vm["decisions"]["251146"][0]
    entry["sets"][0]["moves"] = [{"add": 6999, "drop": None, "gain": {"week": 0.31}}]
    entry["system"]["file"] = "bbm_projections_2026-10-30.csv"
    entry["plan"]["recommended"] = True
    c = compare(sc, mac, vm)
    assert c.flags == [
        "251146 solve system export: mac bbm_projections_2026-10-31.csv, droplet bbm_projections_2026-10-30.csv",
        "251146 set week: mac +6406/-6751 (0.27); droplet +6999/open (0.31)",
        "251146 week plan recommended: mac False, droplet True",
        "251146 lineup /nba/251146/7?date=2026-10-31: the droplet would set 6173 to BN (the mac has Util), 7000 to PG (the mac has no slot)",
    ]
    assert "251146: sets differ" in c.render()
    # the Mac in dry run too: its lineup is the one it read with its own would-set slots laid over
    mac["executor"]["251146"]["lineup"] = [
        {
            "mode": "dry_run",
            "outcome": "would_set",
            "page": PAGE,
            "before": {"6173": "BN", "6047": "Util", "7000": "PG"},
            "controls": {"would_set": {"6173": "BN"}},
            "after": {"6173": "BN", "6047": "Util", "7000": "PG"},
        }
    ]
    c = compare(sc, mac, vm)
    assert c.flags[-1] == (
        "251146 lineup /nba/251146/7?date=2026-10-31: the droplet would set 6047 to BN (the mac has Util)"
    )
    # a page the Mac never opened is shown, not counted
    vm["executor"]["251146"]["lineup"][0]["page"] = "/nba/251146/7?date=2026-11-01"
    c = compare(sc, mac, vm)
    assert "the mac has no entry for that page" in c.render() and not any(
        "lineup" in f for f in c.flags
    )


def test_a_marker_from_another_day_or_missing_is_flagged(tmp_path, sc):
    mac, vm = pair(tmp_path, sc)
    vm["marker"]["started_at"] = "2026-10-30T05:00:10-05:00"
    assert compare(sc, mac, vm).flags == [
        "the droplet's daily marker is from 2026-10-30, not 2026-10-31"
    ]
    assert compare(sc, {**mac, "marker": None}, vm).flags[0] == "no daily marker on the mac"
    assert "- mac refresh: no marker" in compare(sc, {**mac, "marker": None}, vm).render()


# --------------------------------------------------------------------------- the command
def test_the_command_bundles_compares_posts_and_reports_what_it_cannot_read(
    tmp_path, sc, capsys, monkeypatch
):
    mac_data, vm_data = side(tmp_path, "mac"), side(tmp_path, "droplet")
    assert sc.main(["bundle", "--date", DAY, "--data", str(vm_data)]) == sc.OK
    out = capsys.readouterr().out
    vm = json.loads(out)
    assert sorted(vm) == [
        "armed",
        "data",
        "date",
        "decisions",
        "executor",
        "exports",
        "host",
        "made_at",
        "marker",
        "passes",
        "queue",
        "runs",
    ]
    remote = tmp_path / "vm.json"
    remote.write_text(out)

    assert (
        sc.main(["--date", DAY, "--data", str(mac_data), "--remote-bundle", str(remote)]) == sc.OK
    )
    text = capsys.readouterr().out
    assert text.startswith(f"# Soak comparison {DAY}\n") and "**nothing flagged**" in text

    vm["exports"].pop("ros")
    remote.write_text(json.dumps(vm))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs.get("cwd")))
        return SimpleNamespace(
            returncode=0, stdout="https://github.com/o/r/issues/225#issuecomment-1\n", stderr=""
        )

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    code = sc.main(
        ["--date", DAY, "--data", str(mac_data), "--remote-bundle", str(remote), "--post"]
    )
    captured = capsys.readouterr()
    assert code == sc.FLAGGED and "export ros missing on the droplet" in captured.out
    assert (
        calls[0][0][:5] == ["gh", "issue", "comment", "225", "--body-file"]
        and calls[0][1] == sc.REPO
    )
    assert "issuecomment-1" in captured.err

    assert (
        sc.main(["--date", "2026-13-01", "--data", str(mac_data), "--remote-bundle", str(remote)])
        == sc.UNREAD
    )
    assert (
        sc.main(["--date", DAY, "--data", str(tmp_path / "none"), "--remote-bundle", str(remote)])
        == sc.UNREAD
    )
    assert (
        sc.main(
            ["--date", DAY, "--data", str(mac_data), "--remote-bundle", str(tmp_path / "no.json")]
        )
        == sc.UNREAD
    )
    assert "could not be read" in capsys.readouterr().err


def test_the_remote_bundle_runs_this_script_over_ssh_with_the_system_python(sc):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout='{"host": "vm"}', stderr="")

    assert sc.remote_bundle("pickandroll@box", "pickandroll", DAY, run=fake_run) == {"host": "vm"}
    assert calls[0][:5] == ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    assert calls[0][5] == "pickandroll@box"
    assert calls[0][6] == f"cd ~/pickandroll && python3 scripts/soak_compare.py bundle --date {DAY}"
    assert sc.remote_bundle("u@h", "/srv/pr", DAY, run=fake_run) and calls[1][6].startswith(
        "cd /srv/pr && "
    )

    def failing(argv, **kwargs):
        return SimpleNamespace(
            returncode=255, stdout="", stderr="ssh: connect to host box: refused"
        )

    with pytest.raises(RuntimeError, match="exit 255: ssh: connect"):
        sc.remote_bundle("u@h", "pickandroll", DAY, run=failing)
