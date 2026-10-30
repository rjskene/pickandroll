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


# ------------------------------------------------------- the --keychain mode (#238, item 5)
SITE_URLS = {
    "Y1": "https://login.yahoo.com/?done=https%3A%2F%2Fbasketball.fantasysports.yahoo.com",
    "B1": "https://basketballmonster.com/login.aspx",
    "X1": "https://example.com/?q=yahoo.com",  # another host that only names the site
}
VALUES = {"pickandroll-bbm": "bbm-test-value", "pickandroll-yahoo": "yahoo-test-value"}


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
    answers the helper's calls. A page's password field appears once ``missing`` looks are
    spent; every call and every inserted text is kept per page."""

    def __init__(self, kf: Any, missing: dict[str, int]) -> None:
        self.kf = kf
        self.missing = dict(missing)
        self.calls: dict[str, list[tuple[str, dict[str, Any]]]] = {pid: [] for pid in SITE_URLS}
        self.inserted: dict[str, list[str]] = {pid: [] for pid in SITE_URLS}
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

    def answer(self, pid: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "Runtime.evaluate":
            expression = params["expression"]
            if expression == self.kf.FIND_JS:
                if self.missing.get(pid, 0) > 0:
                    self.missing[pid] -= 1
                    return {"result": {"type": "object", "subtype": "null", "value": None}}
                return {"result": {"type": "object", "value": {"x": 320.5, "y": 240}}}
            if expression == self.kf.FOCUS_JS:
                return {"result": {"type": "boolean", "value": True}}
            if expression == self.kf.LENGTH_JS:
                text = self.inserted[pid][-1] if self.inserted[pid] else ""
                return {"result": {"type": "number", "value": len(text)}}
            raise AssertionError(expression)
        if method == "Input.insertText":
            self.inserted[pid].append(params["text"])
        return {}


@pytest.fixture
def keychain(mac_signin, tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str], Path]:
    """The Mac script's fakes plus a fake ``security``: the two items exist (FAKE_MISSING names
    one that does not), ``-w`` prints a test value, every call's arguments go to a log."""
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
  *) echo 'keychain: "login.keychain-db"' ;;
esac
''',
    )
    return script, state, log, env, calls


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


def test_the_keychain_mode_fills_each_password_field_over_devtools_and_shows_no_value(
    keychain, kf
) -> None:
    script, _state, log, env, calls = keychain
    browser = FakeDevTools(kf, missing={"Y1": 1})
    try:
        # Enter for Basketball Monster; Enter for Yahoo (no field yet); Enter again; the final Enter.
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="\n\n\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "press Enter here: the password goes from this Mac's Keychain into that field" in out
    assert "Basketball Monster: with its password field on screen, press Enter" in out
    assert "bbm: the password field holds the Keychain item 'pickandroll-bbm'; click Sign in" in out
    assert "yahoo: the password field holds the Keychain item 'pickandroll-yahoo'" in out
    assert "yahoo: no password field on the yahoo.com page yet (Yahoo shows it" in done.stderr
    assert out.rstrip().endswith("signed in on the droplet: both sites")
    # The text went to the websocket of the right page, after a click on the field.
    assert browser.inserted == {"B1": ["bbm-test-value"], "Y1": ["yahoo-test-value"], "X1": []}
    for pid in ("B1", "Y1"):
        methods = [method for method, _ in browser.calls[pid] if method != "Runtime.evaluate"]
        assert methods[-4:] == ["Input.dispatchMouseEvent"] * 3 + ["Input.insertText"]
        pressed = [p for m, p in browser.calls[pid] if p.get("type") == "mousePressed"]
        assert pressed == [
            {"type": "mousePressed", "x": 320.5, "y": 240, "button": "left", "clickCount": 1}
        ]
        scripts = [p["expression"] for m, p in browser.calls[pid] if m == "Runtime.evaluate"]
        assert scripts[-3:] == [kf.FIND_JS, kf.FOCUS_JS, kf.LENGTH_JS]
    assert browser.calls["X1"] == []  # a URL that only names the site is not the site
    # The value appears nowhere: not in the output, not in a call to ssh or open, and the
    # Keychain is read only once a field is there (the first Yahoo look read nothing).
    for value in VALUES.values():
        assert value not in out + done.stderr and value not in log.read_text()
    reads = [line for line in calls.read_text().splitlines() if line.endswith(" -w")]
    assert reads == [
        "security find-generic-password -s pickandroll-bbm -w",
        "security find-generic-password -s pickandroll-yahoo -w",
    ]


def test_the_keychain_mode_skips_a_site_on_s(keychain, kf) -> None:
    script, _state, _log, env, calls = keychain
    browser = FakeDevTools(kf, missing={})
    try:
        done = signin_run(script, env, "--keychain", "--port", str(browser.port), stdin="s\ns\n\n")
    finally:
        browser.close()
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skipped Basketball Monster: use the Console line there" in done.stdout
    assert "skipped Yahoo: use the Console line there" in done.stdout
    assert "document.querySelector('input[type=password]').value = '...'" in done.stdout
    assert all(not texts for texts in browser.inserted.values())
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
  ok) printf "a value with spaces\\n" ;;
  empty) printf "" ;;
  missing) exit 44 ;;
  denied) echo "security: SecKeychainItemCopyContent: User canceled the operation." >&2; exit 128 ;;
esac
''',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    assert kf.keychain_password("pickandroll-bbm") == ("a value with spaces", "")
    assert calls.read_text() == "security find-generic-password -s pickandroll-bbm -w\n"
    monkeypatch.setenv("FAKE_SECURITY", "missing")
    value, line = kf.keychain_password("pickandroll-yahoo")
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
