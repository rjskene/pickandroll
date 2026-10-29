"""The routine host's units and scripts (``ops/vm``) and the Mac's agents (``ops/mac``): the
unit files parse and say what the runbook says, the timers match the runner's routines and
windows, the shell scripts parse, the watchdog and the alert do what their comments say
against a marker, a run log and fakes of curl, gh and journalctl on PATH."""

from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pickandroll.routine.routines import ROUTINES as RUNNER
from pickandroll.routine.routines import WINDOWS

ROOT = Path(__file__).resolve().parents[1]
VM = ROOT / "ops" / "vm"
MAC = ROOT / "ops" / "mac"
ZONE = "America/Chicago"
TIMERS = {
    "daily": "*-*-* 05:00:00",
    "morning": "*-*-* 07:45:00",
    "late": "*-*-* 15:00:00",
    "evening-build": "*-*-* 21:00:00",
    "evening-pass": "*-*-* 22:40:00",
    "monday": "Mon *-*-* 06:00:00",
    "signin": "*-*-* 04:50:00",
}


def unit(path: Path) -> dict[str, list[tuple[str, str]]]:
    """A unit file as sections of (key, value) pairs, duplicates kept (Environment= repeats)."""
    out: dict[str, list[tuple[str, str]]] = {}
    section = ""
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            out.setdefault(section, [])
            continue
        assert "=" in line, f"{path.name}: not key=value: {raw}"
        assert section, f"{path.name}: a key before any section: {raw}"
        key, value = line.split("=", 1)
        out[section].append((key.strip(), value.strip()))
    return out


def values(u: dict[str, list[tuple[str, str]]], section: str, key: str) -> list[str]:
    return [v for k, v in u.get(section, []) if k == key]


def one(u: dict[str, list[tuple[str, str]]], section: str, key: str) -> str:
    got = values(u, section, key)
    assert len(got) == 1, f"{section}.{key}: {got}"
    return got[0]


# ----------------------------------------------------------------------------- the unit files


def test_every_unit_file_parses_with_a_description() -> None:
    files = sorted(VM.glob("*.service")) + sorted(VM.glob("*.timer"))
    assert len(files) == 13
    for path in files:
        u = unit(path)
        assert one(u, "Unit", "Description")
        if path.suffix == ".timer":
            assert "Timer" in u and one(u, "Install", "WantedBy") == "timers.target"
        else:
            assert "Service" in u


def test_the_timers_are_the_runners_routines_on_the_central_clock() -> None:
    assert set(TIMERS) == set(RUNNER)
    for name, calendar in TIMERS.items():
        u = unit(VM / f"pickandroll-routine@{name}.timer")
        assert one(u, "Timer", "OnCalendar") == f"{calendar} {ZONE}"
        assert one(u, "Timer", "Persistent") == "true"
        assert one(u, "Timer", "Unit") == f"pickandroll-routine@{name}.service"
        # The timer fires at the routine's window start (routines.WINDOWS); the sign-in check's
        # window is the whole day, its timer 04:50, before the daily.
        if name != "signin":
            assert calendar.split()[-1][:5] == WINDOWS[name][0]
        else:
            assert calendar.split()[-1][:5] < WINDOWS["daily"][0]


def test_the_routine_template() -> None:
    u = unit(VM / "pickandroll-routine@.service")
    assert one(u, "Service", "Type") == "oneshot"
    assert one(u, "Service", "SuccessExitStatus") == "3 4"
    assert one(u, "Service", "TimeoutStartSec") == "2h"
    assert one(u, "Unit", "OnFailure") == "pickandroll-alert@%n.service"
    env = values(u, "Service", "Environment")
    assert (
        f"TZ={ZONE}" in env
        and "DISPLAY=:99" in env
        and "PICKANDROLL_API=http://127.0.0.1:8000" in env
    )
    assert one(u, "Service", "EnvironmentFile") == "-%h/.config/pickandroll/routine.env"
    assert one(u, "Service", "ExecStart").endswith("scripts/routine.py %i $ROUTINE_FLAGS")
    assert "Install" not in u  # instances are started by their timers, never enabled themselves
    for dep in ("pickandroll-api.service", "pickandroll-xvfb.service"):
        assert dep in one(u, "Unit", "After") and dep in one(u, "Unit", "Wants")


def test_the_api_unit() -> None:
    u = unit(VM / "pickandroll-api.service")
    assert one(u, "Service", "Restart") == "always"
    assert one(u, "Service", "OOMScoreAdjust") == "-500"
    assert (
        one(u, "Service", "KillMode") == "control-group"
    )  # the pool's workers die with the listener
    assert f"TZ={ZONE}" in values(u, "Service", "Environment")
    exec_start = one(u, "Service", "ExecStart")
    assert "pickandroll.api:app" in exec_start and "--host 127.0.0.1 --port 8000" in exec_start
    assert one(u, "Unit", "StartLimitIntervalSec") == "0"
    assert one(u, "Install", "WantedBy") == "default.target"


def test_the_display_the_alert_and_the_watchdog_units() -> None:
    xvfb = unit(VM / "pickandroll-xvfb.service")
    assert one(xvfb, "Service", "ExecStart").startswith("/usr/bin/Xvfb :99 ")
    assert one(xvfb, "Service", "Restart") == "always"
    alert = unit(VM / "pickandroll-alert@.service")
    assert one(alert, "Service", "ExecStart") == "%h/pickandroll/ops/vm/alert.sh %i"
    watchdog = unit(VM / "pickandroll-watchdog.service")
    assert one(watchdog, "Unit", "OnFailure") == "pickandroll-alert@%n.service"
    assert one(watchdog, "Service", "ExecStart") == "%h/pickandroll/ops/vm/watchdog.sh"
    timer = unit(VM / "pickandroll-watchdog.timer")
    assert one(timer, "Timer", "OnCalendar") == f"*-*-* 06:45:00 {ZONE}"
    assert one(timer, "Timer", "Persistent") == "true"
    # After the daily's window.
    assert "06:45" > WINDOWS["daily"][1]


# --------------------------------------------------------------------------------- the scripts


SCRIPTS = sorted(VM.glob("*.sh")) + sorted(MAC.glob("*.sh"))


@pytest.mark.parametrize("script", SCRIPTS, ids=[s.name for s in SCRIPTS])
def test_each_shell_script_parses_and_is_executable(script: Path) -> None:
    subprocess.run(["bash", "-n", str(script)], check=True)
    assert os.access(script, os.X_OK), f"{script.name} is not executable"
    assert script.read_text().startswith("#!/usr/bin/env bash\n")


def test_install_refuses_a_bad_flag_before_doing_anything(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", str(VM / "install.sh"), "--bogus"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PICKANDROLL_REPO": str(tmp_path),
            "PICKANDROLL_CONF": str(tmp_path / "conf"),
        },
    )
    assert done.returncode == 2 and "usage:" in done.stderr
    assert not (tmp_path / "conf").exists()


def fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


def env_with(bin_dir: Path, **extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PICKANDROLL_PYTHON": sys.executable,
        "TZ": ZONE,
        **extra,
    }


def run(script: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args], check=False, capture_output=True, text=True, env=env
    )


# ---------------------------------------------------------------------------------- watchdog


def marker(data: Path, finished: str, failed: str | None = None) -> None:
    steps = {
        k: {"status": "ok", "detail": "fine"}
        for k in ("api", "exports", "refresh", "solve", "digest")
    }
    if failed:
        steps[failed] = {"status": "failed", "detail": "the step's own line"}
    (data / "routine").mkdir(parents=True, exist_ok=True)
    (data / "routine" / "daily.json").write_text(
        json.dumps(
            {
                "started_at": f"{finished}T05:00:00-05:00",
                "finished_at": f"{finished}T05:40:00-05:00",
                "steps": steps,
            }
        )
    )


def today_central() -> str:
    done = subprocess.run(
        ["date", "+%F"], check=True, capture_output=True, text=True, env={**os.environ, "TZ": ZONE}
    )
    return done.stdout.strip()


@pytest.fixture
def watchdog(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(bin_dir, "curl", 'printf "%s" "${FAKE_HTTP_CODE:-200}"\n')
    data = tmp_path / "data"
    data.mkdir()
    return (
        VM / "watchdog.sh",
        data,
        env_with(bin_dir, PICKANDROLL_DATA=str(data), PICKANDROLL_API="http://api.test"),
    )


def test_watchdog_passes_on_todays_clean_marker_and_a_live_api(watchdog) -> None:
    script, data, env = watchdog
    marker(data, today_central())
    done = run(script, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "daily marker: finished" in done.stdout and "no failed step" in done.stdout
    assert "api: 200 on GET http://api.test/seasons" in done.stdout
    assert "mac copy: no stamp yet" in done.stdout


def test_watchdog_fails_on_a_failed_step_a_stale_marker_or_none(watchdog) -> None:
    script, data, env = watchdog
    marker(data, today_central(), failed="exports")
    done = run(script, env)
    assert done.returncode == 1 and "failed steps: exports (the step's own line)" in done.stdout
    marker(data, "2026-10-01")
    done = run(script, env)
    assert done.returncode == 1 and "finished 2026-10-01, not today" in done.stdout
    (data / "routine" / "daily.json").unlink()
    done = run(script, env)
    assert done.returncode == 1 and "daily marker: missing" in done.stdout


def test_watchdog_fails_when_the_api_is_down(watchdog) -> None:
    script, data, env = watchdog
    marker(data, today_central())
    done = run(
        script,
        {**env, "FAKE_HTTP_CODE": "000"},
    )
    assert done.returncode == 1 and "api: 000 on GET" in done.stdout


def test_watchdog_checks_the_mac_copy_stamp_once_it_exists(watchdog) -> None:
    script, data, env = watchdog
    marker(data, today_central())
    stamp = data / "routine" / ".copied-at"
    stamp.write_text("2026-10-29T08:30:00Z\n")
    done = run(script, env)
    assert done.returncode == 0 and "mac copy: 0 h ago" in done.stdout
    old = time.time() - 80 * 3600
    os.utime(stamp, (old, old))
    done = run(script, env)
    assert done.returncode == 1 and "mac copy: last copied 80 h ago, over 72 h" in done.stdout


# ------------------------------------------------------------------------------------- alert


@pytest.fixture
def alert(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    fake(bin_dir, "journalctl", 'printf "journal line one\\njournal line two\\n"\n')
    fake(bin_dir, "curl", f'{{ echo "curl $*"; cat; echo; }} >> "{log}"\n')
    fake(bin_dir, "gh", f'{{ echo "gh $*"; cat; echo; }} >> "{log}"\n')
    data = tmp_path / "data"
    runs = data / "routine" / "runs"
    runs.mkdir(parents=True)
    (runs / "2026-10-29-daily.json").write_text(
        json.dumps(
            {
                "routine": "daily",
                "started_at": "2026-10-29T05:00:00-05:00",
                "finished_at": "2026-10-29T05:41:10-05:00",
                "refused": False,
                "stopped": False,
                "failed": True,
                "steps": [
                    {"name": "api", "status": "ok", "detail": "200 on first check"},
                    {
                        "name": "exports",
                        "status": "failed",
                        "detail": "2 of 5 failed: ros (timed out), week_this (no file)",
                    },
                ],
                "alerts": ["the browser profile is signed out of bbm"],
            }
        )
    )
    conf = tmp_path / "conf"
    conf.mkdir()
    env = env_with(bin_dir, PICKANDROLL_DATA=str(data), PICKANDROLL_CONF=str(conf))
    return VM / "alert.sh", conf, log, env


def test_alert_posts_the_failed_unit_to_ntfy_and_the_issue(alert) -> None:
    script, conf, log, env = alert
    (conf / "ntfy_topic").write_text("the-users-topic\n")
    (conf / "ops_issue").write_text("225\n")
    done = run(script, env, "pickandroll-routine@daily.service")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("pickandroll-routine@daily.service failed on ")
    assert (
        "newest run log 2026-10-29-daily.json: daily failed, started 05:00:00, finished 05:41:10"
        in done.stdout
    )
    assert "- exports: failed, 2 of 5 failed: ros (timed out), week_this (no file)" in done.stdout
    assert "! the browser profile is signed out of bbm" in done.stdout
    assert "ntfy: posted to the topic" in done.stdout and "gh: commented on #225" in done.stdout
    calls = log.read_text()
    assert (
        "https://ntfy.sh/the-users-topic" in calls
        and "Title: pickandroll: pickandroll-routine@daily.service failed" in calls
    )
    assert "journal line two" in calls  # the journal goes to ntfy
    assert "gh issue comment 225 --body-file -" in calls
    comment = calls.split("gh issue comment 225")[1]
    assert "**pickandroll-routine@daily.service** failed on" in comment
    assert (
        "exports: failed" in comment and "journal line" not in comment
    )  # never the journal in public
    assert "journalctl --user -u pickandroll-routine@daily.service -n 40" in comment


def test_alert_skips_a_channel_that_is_not_set_and_never_fails(alert) -> None:
    script, _conf, log, env = alert
    done = run(script, env, "pickandroll-watchdog.service")
    assert done.returncode == 0
    assert "ntfy: no topic in" in done.stdout and "gh: no issue in" in done.stdout
    assert "newest run log" not in done.stdout  # the watchdog has no run log
    assert not log.exists()


def test_alert_says_when_a_routine_has_no_run_log_yet(alert) -> None:
    script, _conf, _log, env = alert
    done = run(script, env, "pickandroll-routine@monday.service")
    assert done.returncode == 0
    assert "no run log for monday yet" in done.stdout


# ------------------------------------------------------------------------------ the Mac side


def test_the_tunnel_agent() -> None:
    plist = plistlib.loads((MAC / "com.pickandroll.tunnel.plist").read_bytes())
    assert plist["Label"] == "com.pickandroll.tunnel"
    args = plist["ProgramArguments"]
    assert args[0] == "/usr/bin/ssh" and "-N" in args
    assert args[args.index("-L") + 1] == "8000:127.0.0.1:8000"
    assert args[-1] == "pickandroll@hts-digital-ocean"
    assert "ExitOnForwardFailure=yes" in args and "BatchMode=yes" in args
    assert plist["KeepAlive"] is True and plist["RunAtLoad"] is True


def test_the_nightly_copy_agent_runs_the_script_at_0330() -> None:
    plist = plistlib.loads((MAC / "com.pickandroll.rsync.plist").read_bytes())
    assert plist["StartCalendarInterval"] == {"Hour": 3, "Minute": 30}
    assert plist["ProgramArguments"][0] == "/bin/bash"
    assert plist["ProgramArguments"][1] == "__HOME__/code/pickandroll/ops/mac/rsync-from-droplet.sh"
    assert "__HOME__" in (MAC / "README.md").read_text()  # the install line replaces it


def test_the_copy_script_does_nothing_without_its_settings(tmp_path: Path) -> None:
    conf = tmp_path / "conf"
    conf.mkdir()
    done = run(MAC / "rsync-from-droplet.sh", {**os.environ, "PICKANDROLL_CONF": str(conf)})
    assert done.returncode == 0 and "nothing copied (not enabled before cut-over)" in done.stdout
    assert not (conf / "rsync.log").exists()


def test_the_copy_script_excludes_the_profile_and_guards_both_hosts() -> None:
    text = (MAC / "rsync-from-droplet.sh").read_text()
    for excluded in ("/routine/profile/", "/routine/downloads/", "/routine/screens/"):
        assert f"--exclude={excluded}" in text
    assert text.count("/rooms") >= 2 and ".copied-at" in text
