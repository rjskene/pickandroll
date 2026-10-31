"""The routine host's units and scripts (``ops/vm``) and the Mac's agents (``ops/mac``): the
unit files parse and say what the runbook says, the timers match the runner's routines and
windows, the shell scripts parse, the watchdog and the alert do what their comments say
against a marker, a run log and fakes of curl, gh and journalctl on PATH."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import plistlib
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

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
    # gh takes the issue's repository from the working directory: without it every comment
    # fails with "could not determine base repo".
    assert one(alert, "Service", "WorkingDirectory") == "%h/pickandroll"
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


# ----------------------------------------------------------------------------------- update
def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


@pytest.fixture
def update(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    """The host's checkout as a clone of a bare origin, with a seed clone to move the origin
    from; fake curl (the rooms and /seasons), systemctl (the units) and npm (the build) on the
    PATH, every call logged. Returns the checkout, the seed, the log and the environment."""
    seed, origin, repo = tmp_path / "seed", tmp_path / "origin.git", tmp_path / "repo"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    for rel, text in (
        ("web/index.html", "<html>"),
        ("src/x.py", "x = 1\n"),
        ("pyproject.toml", "[p]\n"),
    ):
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    git(seed, "add", ".")
    git(seed, "commit", "-q", "-m", "seed")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(origin)], check=True)
    git(seed, "remote", "add", "origin", str(origin))
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(
        bin_dir,
        "curl",
        f"""echo "curl $*" >> "{log}"
case "$*" in
  *"/rooms"*) printf '%s' "${{FAKE_ROOMS-[]}}" ;;
  *"-w"*"/seasons"*) printf '%s' "${{FAKE_SEASONS_CODE:-200}}" ;;
  *"/seasons"*) echo "[]" ;;
esac
""",
    )
    fake(
        bin_dir,
        "systemctl",
        f"""echo "systemctl $*" >> "{log}"
case "$*" in *list-units*) printf '%s\\n' "${{FAKE_ACTIVE:-}}" ;; esac
""",
    )
    fake(
        bin_dir,
        "npm",
        f"""echo "npm $* VITE_PICKANDROLL_API_BASE=${{VITE_PICKANDROLL_API_BASE-unset}}" >> "{log}"
case "$*" in *build*) mkdir -p dist && echo built > dist/index.html ;; esac
""",
    )
    env = env_with(
        bin_dir,
        PICKANDROLL_REPO=str(repo),
        PICKANDROLL_API="http://127.0.0.1:8000",
        XDG_RUNTIME_DIR="/tmp",
    )
    return repo, seed, log, env


def move_origin(seed: Path, rel: str, text: str) -> str:
    (seed / rel).write_text(text)
    git(seed, "add", rel)
    git(seed, "commit", "-q", "-m", f"change {rel}")
    git(seed, "push", "-q", "origin", "main")
    return git(seed, "rev-parse", "HEAD")


def test_update_refuses_under_a_live_room_or_a_running_routine(update) -> None:
    repo, _seed, log, env = update
    done = run(VM / "update.sh", {**env, "FAKE_ROOMS": '[{"id": "r1"}]'})
    assert done.returncode == 3 and "refused: http://127.0.0.1:8000/rooms answers" in done.stdout
    done = run(VM / "update.sh", {**env, "FAKE_ACTIVE": "pickandroll-routine@morning.service"})
    assert done.returncode == 3
    assert "refused: a routine runs (pickandroll-routine@morning.service)" in done.stdout
    assert "npm" not in log.read_text() and "restart" not in log.read_text()
    assert not (repo / "web" / "dist").exists()
    assert run(VM / "update.sh", env, "--bogus").returncode == 2


def test_update_builds_a_missing_dashboard_and_leaves_the_api_when_nothing_changed(update) -> None:
    repo, _seed, log, env = update
    head = git(repo, "rev-parse", "HEAD")
    done = run(VM / "update.sh", env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"main: {head[:7]} (unchanged)" in done.stdout
    assert f"dashboard: built from web/ at {head[:7]}, served under /app" in done.stdout
    assert "api: not restarted (no src/ or pyproject.toml change)" in done.stdout
    calls = log.read_text()
    assert "npm ci --no-audit --no-fund --silent VITE_PICKANDROLL_API_BASE=unset" in calls
    assert (
        "npm run build --silent -- --base=/app/ VITE_PICKANDROLL_API_BASE=\n" in calls
    )  # set, empty
    assert "restart" not in calls and (repo / "web" / "dist" / "index.html").is_file()
    # built already and nothing moved: nothing done
    done = run(VM / "update.sh", env)
    assert done.returncode == 0 and "dashboard: unchanged" in done.stdout
    assert log.read_text().count("npm run build") == 1


def test_update_fast_forwards_rebuilds_on_a_web_change_and_restarts_on_a_src_change(update) -> None:
    repo, seed, log, env = update
    old = git(repo, "rev-parse", "HEAD")
    assert run(VM / "update.sh", env).returncode == 0  # the first build
    new = move_origin(seed, "web/index.html", "<html>v2")
    done = run(VM / "update.sh", env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"main: {new[:7]} (was {old[:7]})" in done.stdout
    assert git(repo, "rev-parse", "HEAD") == new
    assert (
        f"dashboard: built from web/ at {new[:7]}" in done.stdout
        and "api: not restarted" in done.stdout
    )
    assert "restart" not in log.read_text()
    newer = move_origin(seed, "src/x.py", "x = 2\n")
    done = run(VM / "update.sh", env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "dashboard: unchanged" in done.stdout
    assert "api: restarted, GET /seasons 200" in done.stdout
    assert "systemctl --user restart pickandroll-api.service" in log.read_text()
    assert git(repo, "rev-parse", "HEAD") == newer
    assert log.read_text().count("npm run build") == 2


def test_update_restarts_on_request_and_fails_when_the_api_does_not_answer(update) -> None:
    _repo, _seed, log, env = update
    done = run(VM / "update.sh", env, "--restart")
    assert done.returncode == 0 and "api: restarted, GET /seasons 200" in done.stdout
    assert "systemctl --user restart pickandroll-api.service" in log.read_text()
    done = run(VM / "update.sh", {**env, "FAKE_SEASONS_CODE": "503"}, "--restart")
    assert done.returncode == 1 and "api: restarted, GET /seasons 503" in done.stdout


def test_update_says_when_npm_is_missing(update) -> None:
    repo, _seed, _log, env = update
    bin_dir = Path(env["PATH"].split(os.pathsep)[0])
    (bin_dir / "npm").unlink()  # and the real one is off this PATH
    env = {**env, "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"}
    done = run(VM / "update.sh", env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "dashboard: npm is missing, not built (the API serves none)" in done.stdout
    assert not (repo / "web" / "dist").exists()


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
    assert "--delete" not in text  # the Mac's data/ holds folders that exist nowhere else
    assert text.count("/rooms") >= 2 and ".copied-at" in text


# ------------------------------------------------------------------- the Mac's re-sign-in (#238)
DEVTOOLS_LIST = json.dumps(
    [
        {
            "type": "page",
            "url": "https://basketball.fantasysports.yahoo.com/nba/31822",
            "devtoolsFrontendUrl": "https://chrome-devtools-frontend.appspot.com/serve_rev/@abc/inspector.html?ws=127.0.0.1:9222/devtools/page/Y1",
        },
        {
            "type": "service_worker",
            "url": "chrome-extension://abc/background.js",
            "devtoolsFrontendUrl": "/devtools/inspector.html?ws=127.0.0.1:9222/devtools/page/SW",
        },
        {
            "type": "page",
            "url": "https://basketballmonster.com/",
            "devtoolsFrontendUrl": "/devtools/inspector.html?ws=localhost:9222/devtools/page/B1",
        },
    ]
)


@pytest.fixture
def mac_signin(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str]]:
    """The Mac script against fakes of ssh (tmux, pgrep, the log and the tunnel on the droplet),
    curl (the DevTools list) and open; the state of the droplet is a few files."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    log = tmp_path / "calls.log"
    fake(
        bin_dir,
        "ssh",
        f'''cmd="${{@: -1}}"
echo "ssh $*" >> "{log}"
for a in "$@"; do [ "$a" = "-N" ] && exec sleep 30; done
case "$cmd" in
  *"tmux has-session"*) [ -f "{state}/session" ] ;;
  *"tmux new-session"*) touch "{state}/session"; exit 0 ;;
  *"tmux kill-session"*) rm -f "{state}/session"; exit 0 ;;
  *"tmux send-keys"*) touch "{state}/enter"; exit 0 ;;
  *pgrep*) [ -f "{state}/browser" ] ;;
  *"list-units"*) printf '%s' "${{FAKE_ACTIVE:-}}"; exit 0 ;;
  *"sed -n"*)
    if [ -f "{state}/enter" ]; then
      printf '%s\\n' "browser closed" "the signin routine confirms:" "- bbm: ${{FAKE_BBM:-ok, signed in}}" "- yahoo: ${{FAKE_YAHOO:-ok, signed in}}" "finished 07:17:00"
    else
      echo "browser up"
    fi
    exit 0 ;;
  *) exit 0 ;;
esac
''',
    )
    fake(
        bin_dir,
        "curl",
        f"""case "$*" in *json/list*) printf '%s' '{DEVTOOLS_LIST}' ;; *) echo '{{}}' ;; esac\n""",
    )
    fake(bin_dir, "open", f'echo "open $*" >> "{log}"\n')
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "droplet").write_text("pickandroll@box\n")
    return MAC / "signin.sh", state, log, env_with(bin_dir, PICKANDROLL_CONF=str(conf))


def signin_run(
    script: Path, env: dict[str, str], *args: str, stdin: str = "\n"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=60,
    )


def test_the_mac_signin_starts_the_droplet_in_tmux_opens_devtools_relays_enter_and_reads_the_result(
    mac_signin,
) -> None:
    script, _state, log, env = mac_signin
    done = signin_run(script, env)
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "started ops/vm/signin.sh on the droplet in tmux session 'signin'" in out
    assert "tunnel: 127.0.0.1:9222 on this Mac is the droplet browser's DevTools port" in out
    assert (
        "opened DevTools: https://chrome-devtools-frontend.appspot.com/serve_rev/@abc/inspector.html?ws=127.0.0.1:9222/devtools/page/Y1"
        in out
    )
    assert (
        "opened DevTools: http://127.0.0.1:9222/devtools/inspector.html?ws=127.0.0.1:9222/devtools/page/B1"
        in out
    )
    assert "page/SW" not in out  # the extension's worker is not a sign-in page
    assert "document.querySelector('input[type=password]').value" in out
    assert "- bbm: ok, signed in" in out and "- yahoo: ok, signed in" in out
    assert out.rstrip().endswith("signed in on the droplet: both sites")
    calls = log.read_text()
    assert "-o BatchMode=yes -o ConnectTimeout=10 pickandroll@box true" in calls
    assert "pickandroll@box command -v tmux" in calls
    assert (
        "tmux new-session -d -s signin 'cd ~/pickandroll && bash ops/vm/signin.sh 2>&1 | tee -a ~/.config/pickandroll/signin.log'"
        in calls
    )
    assert "=== mac signin" in calls and ">> ~/.config/pickandroll/signin.log" in calls
    assert "-o ExitOnForwardFailure=yes -L 127.0.0.1:9222:127.0.0.1:9222 pickandroll@box" in calls
    assert "tmux send-keys -t signin Enter" in calls
    assert "open -a Google Chrome https://chrome-devtools-frontend.appspot.com" in calls
    assert (
        calls.index("tmux new-session")
        < calls.index("-L 127.0.0.1:9222")
        < calls.index("send-keys")
    )
    assert "sed -n '/=== mac signin " in calls


def test_the_mac_signin_waits_for_a_routine_that_holds_the_profile(mac_signin) -> None:
    script, _state, log, env = mac_signin
    done = signin_run(script, {**env, "FAKE_ACTIVE": "pickandroll-routine@morning.service\n"})
    assert done.returncode == 1
    assert (
        "a routine holds the browser profile on the droplet right now (pickandroll-routine@morning.service )"
        in done.stderr
    )
    assert "tmux new-session" not in log.read_text() and "-L 127.0.0.1" not in log.read_text()


def test_the_mac_signin_fails_when_a_site_stays_signed_out(mac_signin) -> None:
    script, _state, _log, env = mac_signin
    done = signin_run(script, {**env, "FAKE_YAHOO": "failed, signed out"})
    assert done.returncode == 1
    assert "- yahoo: failed, signed out" in done.stdout
    assert "not signed in on both sites yet: run this again" in done.stderr


def test_the_mac_signin_reattaches_a_running_session_and_replaces_a_stale_one(mac_signin) -> None:
    script, state, log, env = mac_signin
    (state / "session").touch()
    (state / "browser").touch()
    done = signin_run(script, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "reattaching: the droplet's signin.sh is already running" in done.stdout
    assert (
        "pgrep -u $(id -u) -f 'ops/vm/signin_browser[.]py'" in log.read_text()
    )  # never its own shell
    assert "tmux new-session" not in log.read_text() and "kill-session" not in log.read_text()

    log.unlink()
    (state / "browser").unlink()
    (state / "enter").unlink()
    done = signin_run(script, env)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "a stale tmux session 'signin' with no sign-in browser in it: removing it" in done.stdout
    calls = log.read_text()
    assert calls.index("tmux kill-session -t signin") < calls.index("tmux new-session -d -s signin")


def test_the_mac_signin_moves_the_local_port_and_can_print_instead_of_opening(mac_signin) -> None:
    script, _state, log, env = mac_signin
    done = signin_run(script, env, "--port", "9333", "--no-open", "--host", "me@elsewhere")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        "DevTools: https://chrome-devtools-frontend.appspot.com/serve_rev/@abc/inspector.html?ws=127.0.0.1:9333/devtools/page/Y1"
        in done.stdout
    )
    assert (
        "DevTools: http://127.0.0.1:9333/devtools/inspector.html?ws=127.0.0.1:9333/devtools/page/B1"
        in done.stdout
    )
    calls = log.read_text()
    assert (
        "-L 127.0.0.1:9333:127.0.0.1:9222 me@elsewhere" in calls and "pickandroll@box" not in calls
    )
    assert "open " not in calls


def test_the_mac_signin_needs_the_droplet_address_and_refuses_a_bad_flag(
    mac_signin, tmp_path: Path
) -> None:
    script, _state, log, env = mac_signin
    empty = tmp_path / "empty"
    empty.mkdir()
    done = signin_run(script, {**env, "PICKANDROLL_CONF": str(empty)})
    assert (
        done.returncode == 2
        and "no droplet address" in done.stderr
        and str(empty / "droplet") in done.stderr
    )
    (empty / "rsync.env").write_text("DROPLET=pickandroll@fromenv\nREMOTE_DATA=pickandroll/data\n")
    done = signin_run(script, {**env, "PICKANDROLL_CONF": str(empty)})
    assert done.returncode == 0 and "pickandroll@fromenv true" in log.read_text()
    done = signin_run(script, env, "--bogus")
    assert done.returncode == 2 and "usage:" in done.stderr and "[--keychain]" in done.stderr
    done = signin_run(script, env, "--port")
    assert done.returncode == 2 and "usage:" in done.stderr


def test_the_alert_for_the_signin_unit_names_the_mac_command(alert) -> None:
    script, conf, log, env = alert
    (conf / "ops_issue").write_text("225\n")
    done = run(script, env, "pickandroll-routine@signin.service")
    assert done.returncode == 0
    assert "no run log for signin yet" in done.stdout
    assert "re-sign-in from the Mac: bash ops/mac/signin.sh (docs/OPS.md §3)" in done.stdout
    assert "bash ops/mac/signin.sh" in log.read_text().split("gh issue comment 225")[1]


# --------------------------------------------------------------- the sign-in browser (#238)


def test_the_sign_in_browser_opens_its_devtools_port_to_the_frontend_the_mac_opens() -> None:
    """Chrome 111+ refuses a DevTools websocket from an origin not in --remote-allow-origins;
    the Mac command opens the frontend that /json/list names, so its origin is allowed."""
    spec = importlib.util.spec_from_file_location("signin_browser", VM / "signin_browser.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    args = module.launch_args(Path("/srv/extension"))
    assert "--remote-debugging-port=9222" in args
    assert "--remote-allow-origins=https://chrome-devtools-frontend.appspot.com" in args
    assert "--load-extension=/srv/extension" in args and "--no-first-run" in args
    assert not any(a.startswith("--headless") for a in args)


# ------------------------------------------------- the --keychain mode (#238 item 5, #249)
SITE_URLS = {
    "Y1": "https://login.yahoo.com/?done=https%3A%2F%2Fbasketball.fantasysports.yahoo.com",
    "B1": "https://basketballmonster.com/",
    "X1": "https://example.com/?q=yahoo.com",  # another host that only names the site
}
VALUES = {"pickandroll-bbm": "bbm-test-value", "pickandroll-yahoo": "yahoo-test-value"}
ACCOUNTS = {"pickandroll-bbm": "bbm-user", "pickandroll-yahoo": "yahoo-user"}
#: Where the fake browser draws each element; a click there is a click on it. The helper knows
#: the first seven; Sign in and Remove are drawn to prove they are never clicked.
SPOTS = {
    "username": (100.0, 100.0),
    "password": (100.0, 200.0),
    "next": (100.0, 300.0),
    "another": (100.0, 400.0),
    "option": (100.0, 500.0),
    "login": (100.0, 600.0),
    "account": (100.0, 650.0),
    "signin": (100.0, 700.0),
    "remove": (100.0, 750.0),
}
KNOWN = ("username", "password", "next", "another", "option", "login", "account")
#: Each page's states: path → what it shows and where a click on a shown element moves; a state
#: with a third and fourth member is a page still drawing itself, which turns into the page at
#: that path after that many looks.
YAHOO_STATES = {
    "/": ({"username", "next", "signin"}, {"next": "/account/challenge/web-authn"}),
    "/account/challenge/web-authn": (
        {"another"},
        {"another": "/account/challenge/challenge-selector"},
    ),
    "/account/challenge/challenge-selector": (
        {"another", "option"},  # the page keeps the link; the option is the way on
        {"option": "/account/challenge/password", "another": "/account/challenge/web-authn"},
    ),
    "/account/challenge/password": ({"password", "signin"}, {}),
    "/account/challenge/verify-code": (set(), {}),  # a page the helper does not know
    # The account chooser after a sign-out: the signed-out account's tile, its Remove button
    # and a "Use a different account" link; the tile leads on with the username already known.
    "/manage_account": ({"account", "remove"}, {"account": "/account/challenge/web-authn"}),
}
BBM_STATES = {
    "/": ({"login"}, {"login": "/login.aspx-loading"}),
    # The login page right after the click: its nav Login link is drawn before the form (the
    # master's run of 2026-10-30 saw the helper click Login twice); two looks later the form.
    "/login.aspx-loading": ({"login"}, {}, "/login.aspx", 2),
    # Both fields at once, a Sign in button and a Retrieve Password button that the helper's
    # own script already leaves out; the fake shows it as the option to prove it stays unclicked.
    "/login.aspx": ({"username", "password", "option", "signin"}, {}),
}
REPORTED = {"/login.aspx-loading": "/login.aspx"}  # what location.pathname says meanwhile


@pytest.fixture(scope="module")
def kf():
    """The helper as a module: the fake browser below speaks its websocket frames back."""
    spec = importlib.util.spec_from_file_location("keychain_fill", MAC / "keychain_fill.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeDevTools:
    """Chrome's DevTools endpoint on a free local port: ``/json/list`` over HTTP (its websocket
    URLs name the browser's own port 9222, as the real one's do) and one websocket per page that
    answers the helper's calls from the page's state. A look reports the path and what the page
    shows, a locate gives the element's spot, a click on a spot moves the page to the next
    state, a click on a field focuses it, the inserted text is kept per field. Every call is
    kept per page."""

    def __init__(self, kf: Any, starts: dict[str, str]) -> None:
        self.kf = kf
        self.states = {"Y1": YAHOO_STATES, "B1": BBM_STATES, "X1": {"/": (set(), {})}}
        self.path = {pid: starts.get(pid, "/") for pid in SITE_URLS}
        self.turning: dict[str, list[Any]] = {}  # pid → [path it becomes, looks left]
        self.focused: dict[str, str | None] = {pid: None for pid in SITE_URLS}
        self.values: dict[str, dict[str, str]] = {pid: {} for pid in SITE_URLS}
        self.calls: dict[str, list[tuple[str, dict[str, Any]]]] = {pid: [] for pid in SITE_URLS}
        self.clicked: dict[str, list[str]] = {pid: [] for pid in SITE_URLS}
        self.inserted: dict[str, list[tuple[str, str]]] = {pid: [] for pid in SITE_URLS}
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self) -> None:
                fake.serve(self.request)

        socketserver.ThreadingTCPServer.allow_reuse_address = True
        self.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def listing(self) -> bytes:
        targets: list[dict[str, str]] = [
            {
                "type": "page",
                "url": url,
                "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{pid}",
            }
            for pid, url in SITE_URLS.items()
        ]
        targets.append(
            {
                "type": "service_worker",
                "url": "chrome-extension://abc/background.js",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/SW",
            }
        )
        return json.dumps(targets).encode()

    def serve(self, sock: socket.socket) -> None:
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                return
            head += chunk
        head, _, leftover = head.partition(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        path = lines[0].split(" ")[1]
        headers = {
            k.lower(): v.strip()
            for k, v in (line.split(":", 1) for line in lines[1:] if ":" in line)
        }
        if path == "/json/list":
            body = self.listing()
            sock.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            sock.close()
            return
        pid = path.rsplit("/", 1)[1]
        digest = hashlib.sha1((headers["sec-websocket-key"] + self.kf.GUID).encode()).digest()
        accept = base64.b64encode(digest).decode()
        sock.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        reader = self.kf.Reader(sock, leftover, mask=False)
        while True:
            try:
                request = json.loads(reader.message())
            except OSError:
                sock.close()
                return
            params = request.get("params") or {}
            self.calls[pid].append((request["method"], params))
            reply = {"id": request["id"], "result": self.answer(pid, request["method"], params)}
            self.kf.send_frame(sock, 0x1, json.dumps(reply).encode(), mask=False)

    def shows(self, pid: str) -> set[str]:
        return self.states[pid][self.path[pid]][0]

    def answer(self, pid: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        def value(v: Any) -> dict[str, Any]:
            return {"result": {"type": "object", "value": v}}

        if method == "Runtime.evaluate":
            expression = params["expression"]
            if expression == self.kf.page_expression(None):
                shows = {kind: kind in self.shows(pid) for kind in KNOWN}
                path = REPORTED.get(self.path[pid], self.path[pid])
                if pid in self.turning:
                    self.turning[pid][1] -= 1
                    if self.turning[pid][1] == 0:
                        self.path[pid] = self.turning.pop(pid)[0]
                return value({"path": path, "shows": shows})
            for kind, spot in SPOTS.items():
                if expression == self.kf.page_expression(kind):
                    if kind not in self.shows(pid):
                        return {"result": {"type": "object", "subtype": "null", "value": None}}
                    return value({"x": spot[0], "y": spot[1]})
            for kind, script in self.kf.FOCUS_JS.items():
                if expression == script:
                    return value(self.focused[pid] == kind)
            if expression == self.kf.LENGTH_JS:
                focused = self.focused[pid]
                return value(len(self.values[pid].get(focused or "", "")))
            raise AssertionError(expression)
        if method == "Input.dispatchMouseEvent" and params.get("type") == "mousePressed":
            spot = (params["x"], params["y"])
            kind = next(k for k, s in SPOTS.items() if s == spot)
            assert kind in self.shows(pid), f"a click on {kind}, which {self.path[pid]} hides"
            self.clicked[pid].append(kind)
            self.focused[pid] = kind if kind in ("username", "password") else None
            moves = self.states[pid][self.path[pid]][1]
            if kind in moves:
                self.path[pid] = moves[kind]
                self.focused[pid] = None
                state = self.states[pid][self.path[pid]]
                if len(state) == 4:
                    self.turning[pid] = [state[2], state[3]]
        if method == "Input.insertText":
            focused = self.focused[pid]
            assert focused in ("username", "password"), "text with no field focused"
            self.values[pid][focused] = params["text"]
            self.inserted[pid].append((focused, params["text"]))
        return {}


def attributes(service: str) -> str:
    """What ``security find-generic-password -s <service>`` prints (the account name among the
    attributes), as a printf format for the fake."""
    acct = ACCOUNTS[service]
    return (
        f'keychain: \\"login.keychain-db\\"\\nattributes:\\n    \\"acct\\"<blob>=\\"{acct}\\"\\n'
        f'    \\"svce\\"<blob>=\\"{service}\\"\\n'
    )


@pytest.fixture
def keychain(mac_signin, tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str], Path]:
    """The Mac script's fakes plus a fake ``security``: the two items exist with an account
    name (FAKE_MISSING names one that does not), ``-w`` prints a test value, every call's
    arguments go to a log."""
    script, state, log, env = mac_signin
    calls = tmp_path / "security.calls"
    fake(
        tmp_path / "bin",
        "security",
        f'''echo "security $*" >> "{calls}"
case "$*" in
  *"-s ${{FAKE_MISSING:-no-such-item}}"*) exit 44 ;;
  *"-s pickandroll-bbm -w") echo "{VALUES["pickandroll-bbm"]}" ;;
  *"-s pickandroll-yahoo -w") echo "{VALUES["pickandroll-yahoo"]}" ;;
  *"-s pickandroll-bbm") printf "{attributes("pickandroll-bbm")}" ;;
  *"-s pickandroll-yahoo") printf "{attributes("pickandroll-yahoo")}" ;;
  *) echo 'keychain: "login.keychain-db"' ;;
esac
''',
    )
    return script, state, log, env, calls


def security_reads(calls: Path) -> list[str]:
    return [line.removeprefix("security ") for line in calls.read_text().splitlines()]


def test_the_keychain_mode_refuses_a_missing_item_before_touching_the_droplet(keychain) -> None:
    script, _state, log, env, calls = keychain
    done = signin_run(script, {**env, "FAKE_MISSING": "pickandroll-yahoo"}, "--keychain")
    assert done.returncode == 2
    assert (
        "no Keychain item 'pickandroll-yahoo': create it with"
        "  security add-generic-password -s pickandroll-yahoo -a <account> -w" in done.stderr
    )
    assert not log.exists()  # no ssh, no tunnel, no window
    assert " -w" not in calls.read_text()  # and no password read


def test_the_keychain_mode_walks_each_site_from_its_front_page_to_the_filled_password_field(
    keychain, kf
) -> None:
    script, _state, log, env, calls = keychain
    browser = FakeDevTools(kf, starts={})
    try:
        # Enter for Basketball Monster, Enter for Yahoo, the final Enter.
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="\n\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "press Enter here: the username and the password go in from this Mac's Keychain" in out
    assert "Basketball Monster: with its page on screen, press Enter" in out
    assert (
        "bbm: Login clicked, username in, the password field holds the Keychain item"
        " 'pickandroll-bbm'; click Sign in" in out
    )
    assert (
        "yahoo: username in, Next clicked, passkey page passed, password option taken,"
        " the password field holds the Keychain item 'pickandroll-yahoo'; click Sign in" in out
    )
    assert "Yahoo may ask for a verification code first: type it into the screencast" in out
    assert out.rstrip().endswith("signed in on the droplet: both sites")
    # The pages walked, the clicks and the texts: Sign in never, the retrieve button never.
    assert browser.path == {"Y1": "/account/challenge/password", "B1": "/login.aspx", "X1": "/"}
    assert browser.clicked["B1"] == ["login", "username", "password"]  # Login once
    assert browser.clicked["Y1"] == ["username", "next", "another", "option", "password"]
    assert browser.inserted["B1"] == [("username", "bbm-user"), ("password", "bbm-test-value")]
    assert browser.inserted["Y1"] == [("username", "yahoo-user"), ("password", "yahoo-test-value")]
    assert browser.calls["X1"] == []  # a URL that only names the site is not the site
    # The page is brought to the front and made to count as focused before the first look and
    # click (a synthesized click does not focus an input on a page the OS has not focused);
    # each click lands on the element's spot after a locate that scrolled it into view.
    for pid in ("B1", "Y1"):
        methods = [m for m, _ in browser.calls[pid]]
        assert methods[:3] == [
            "Page.bringToFront",
            "Emulation.setFocusEmulationEnabled",
            "Runtime.evaluate",
        ]
        assert browser.calls[pid][1][1] == {"enabled": True}
        assert methods.index("Input.dispatchMouseEvent") > 2
        scripts = [p["expression"] for m, p in browser.calls[pid] if m == "Runtime.evaluate"]
        assert scripts[0] == kf.page_expression(None)
        assert kf.page_expression("password") in scripts and kf.FOCUS_JS["password"] in scripts
        pressed = [p for m, p in browser.calls[pid] if p.get("type") == "mousePressed"]
        assert all(p["button"] == "left" and p["clickCount"] == 1 for p in pressed)
    # No value and no account name appears anywhere: not in the output, not in a call to ssh
    # or open; the Keychain's password is read once per site, after the account name.
    for secret in list(VALUES.values()) + list(ACCOUNTS.values()):
        assert secret not in out + done.stderr and secret not in log.read_text()
    reads = security_reads(calls)
    assert reads == [
        "find-generic-password -s pickandroll-bbm",  # the script's two existence checks
        "find-generic-password -s pickandroll-yahoo",
        "find-generic-password -s pickandroll-bbm",  # the account name, then the password
        "find-generic-password -s pickandroll-bbm -w",
        "find-generic-password -s pickandroll-yahoo",
        "find-generic-password -s pickandroll-yahoo -w",
    ]


def test_the_keychain_mode_stops_on_a_page_it_does_not_know_and_fills_a_field_already_there(
    keychain, kf
) -> None:
    script, _state, _log, env, calls = keychain
    # Yahoo sits on a verification-code page; Basketball Monster already on its sign-in page.
    browser = FakeDevTools(kf, starts={"Y1": "/account/challenge/verify-code", "B1": "/login.aspx"})
    try:
        # Enter for Basketball Monster; Enter for Yahoo (unknown page), then s to skip it; Enter.
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="\n\ns\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        "yahoo: a page this does not know, /account/challenge/verify-code; nothing more typed:"
        " continue by hand in the DevTools window, then Enter here again" in done.stderr
    )
    assert "skipped Yahoo: use the Console line there" in done.stdout
    assert browser.clicked["Y1"] == [] and browser.inserted["Y1"] == []
    assert browser.clicked["B1"] == ["username", "password"]  # no Login click on the sign-in page
    assert browser.inserted["B1"] == [("username", "bbm-user"), ("password", "bbm-test-value")]
    reads = security_reads(calls)
    assert "find-generic-password -s pickandroll-yahoo -w" not in reads  # unknown page: no read
    assert reads.count("find-generic-password -s pickandroll-bbm -w") == 1


def test_the_keychain_mode_takes_yahoos_account_chooser_and_never_its_remove_button(
    keychain, kf
) -> None:
    script, _state, _log, env, calls = keychain
    # Yahoo lands on its account chooser after a sign-out; Basketball Monster on its front page.
    browser = FakeDevTools(kf, starts={"Y1": "/manage_account"})
    try:
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="\n\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    assert (
        "yahoo: account chosen, passkey page passed, password option taken,"
        " the password field holds the Keychain item 'pickandroll-yahoo'; click Sign in"
        in done.stdout
    )
    assert browser.clicked["Y1"] == ["account", "another", "option", "password"]
    assert browser.inserted["Y1"] == [("password", "yahoo-test-value")]  # no username step
    assert browser.path["Y1"] == "/account/challenge/password"
    reads = security_reads(calls)
    assert "find-generic-password -s pickandroll-yahoo -w" in reads
    assert reads.count("find-generic-password -s pickandroll-yahoo") == 1  # the script's check only


def test_the_keychain_mode_skips_a_site_on_s(keychain, kf) -> None:
    script, _state, _log, env, calls = keychain
    browser = FakeDevTools(kf, starts={})
    try:
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="s\ns\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skipped Basketball Monster: use the Console line there" in done.stdout
    assert "skipped Yahoo: use the Console line there" in done.stdout
    assert "document.querySelector('input[type=password]').value = '...'" in done.stdout
    assert all(not texts for texts in browser.inserted.values())
    assert all(not clicks for clicks in browser.clicked.values())
    assert " -w" not in calls.read_text()


def test_the_helper_reads_the_keychain_in_its_own_process_and_names_the_add_line(
    kf, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    fake(
        bin_dir,
        "security",
        f'''echo "security $*" >> "{calls}"
case "${{FAKE_SECURITY:-ok}}" in
  ok) case "$*" in
        *" -w") printf "a value with spaces\\\\n" ;;
        *) printf 'attributes:\\n    0x00000007 <blob>="svc"\\n    "acct"<blob>="the user"\\n    "svce"<blob>="svc"\\n' ;;
      esac ;;
  hex) printf 'attributes:\\n    "acct"<blob>=0x7573C3A972  "us\\\\303\\\\251r"\\n' ;;
  noacct) printf 'attributes:\\n    "acct"<blob>=<NULL>\\n' ;;
  empty) printf "" ;;
  missing) exit 44 ;;
  denied) echo "security: SecKeychainItemCopyContent: User canceled the operation." >&2; exit 128 ;;
esac
''',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert kf.keychain_password("pickandroll-bbm") == ("a value with spaces", "")
    assert kf.keychain_account("pickandroll-bbm") == ("the user", "")
    assert calls.read_text().splitlines() == [
        "security find-generic-password -s pickandroll-bbm -w",
        "security find-generic-password -s pickandroll-bbm",
    ]
    monkeypatch.setenv("FAKE_SECURITY", "hex")
    assert kf.keychain_account("pickandroll-bbm") == ("usér", "")
    monkeypatch.setenv("FAKE_SECURITY", "noacct")
    value, line = kf.keychain_account("pickandroll-bbm")
    assert value is None and "has no account name" in line and "-a <account> -w -U" in line
    monkeypatch.setenv("FAKE_SECURITY", "missing")
    for read in (kf.keychain_password, kf.keychain_account):
        value, line = read("pickandroll-yahoo")
        assert value is None
        assert "security add-generic-password -s pickandroll-yahoo -a <account> -w" in line
    monkeypatch.setenv("FAKE_SECURITY", "denied")
    value, line = kf.keychain_password("pickandroll-yahoo")
    assert value is None and "security exit 128" in line and "canceled" not in line
    monkeypatch.setenv("FAKE_SECURITY", "empty")
    value, line = kf.keychain_password("pickandroll-yahoo")
    assert value is None and "empty" in line
    assert kf.main(["9222", "elsewhere", "pickandroll-bbm"]) == 2
    assert kf.main(["port", "bbm", "pickandroll-bbm"]) == 2


#: Yahoo's account chooser tiles as the page JS meets them, with where the account click must
#: land. The fake browser answers by kind, so the rule that picks the element inside the tile is
#: checked in a real DOM: the venv's Playwright Chromium evaluates the helper's own PAGE_JS.
#: Each tile is 600 px wide and 80 px tall with its Remove button drawn across the centre, so a
#: click at the tile's centre would remove the account.
TILE = (
    "<li style='position:relative;width:600px;height:80px;list-style:none'>{inner}"
    "<button id='rm' style='position:absolute;left:260px;top:20px;width:80px;height:40px'>"
    "Remove</button></li>"
)
CHOOSER_TILES = {
    # The tile's own link carries the account: the link is clicked.
    "link": (
        (
            "<a id='go' href='#go' style='position:absolute;left:10px;top:10px'>"
            "<span>Test Person</span> <span>test@example.com</span> <span>Signed out</span></a>"
        ),
        "go",
    ),
    # No link or button but the e-mail in a span of its own: the span is clicked.
    "span": (
        (
            "<img alt='' style='position:absolute;left:10px;top:10px;width:40px;height:40px'>"
            "<div style='position:absolute;left:60px;top:10px'><div>Test Person</div>"
            "<span id='mail'>test@example.com</span><div>Signed out</div></div>"
        ),
        "mail",
    ),
    # A link wrapping the whole row holds the Remove button: not the link, the e-mail span.
    "wrapping": (
        (
            "<a href='#go' style='position:absolute;left:0;top:0;width:600px;height:80px'>"
            "<span id='mail' style='position:absolute;left:10px;top:30px'>test@example.com</span>"
            "<span style='position:absolute;left:180px;top:30px'>Signed out</span>"
            "<button style='position:absolute;left:400px;top:20px'>Remove</button></a>"
        ),
        "mail",
    ),
    # Only bare text beside the Remove button: nothing safe to click, the page stays unknown.
    "bare": ("Test Person test@example.com Signed out", None),
}


def test_the_chooser_click_lands_on_the_account_never_on_remove(kf) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except sync_api.Error as exc:  # the browser is not installed here
            pytest.skip(f"no Playwright Chromium: {exc}")
        page = browser.new_page()
        centre = (
            "sel => { const r = document.querySelector(sel).getBoundingClientRect();"
            " return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }"
        )
        for name, (inner, target) in CHOOSER_TILES.items():
            page.set_content(
                "<h1>Welcome back!</h1><ul style='padding:0;margin:0'>"
                + TILE.format(inner=inner)
                + "</ul><a href='#other'>Use a different account</a>"
            )
            # The tile's centre is the Remove button: the layout the rule protects against.
            assert page.evaluate(centre, "li") == pytest.approx(page.evaluate(centre, "#rm")), name
            look = page.evaluate(kf.page_expression(None))
            assert look["shows"]["account"] is (target is not None), name
            spot = page.evaluate(kf.page_expression("account"))
            if target is None:
                assert spot is None, name
                continue
            assert spot == pytest.approx(page.evaluate(centre, f"#{target}")), name
            hit = page.evaluate(
                "([x, y]) => document.elementFromPoint(x, y).outerHTML.slice(0, 80)",
                [spot["x"], spot["y"]],
            )
            assert page.evaluate(
                "([x, y, id]) => document.elementFromPoint(x, y).closest('#' + id) !== null",
                [spot["x"], spot["y"], target],
            ), (name, hit)
            assert "Remove" not in hit, (name, hit)
        browser.close()
