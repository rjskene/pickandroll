#!/usr/bin/env bash
# install.sh [--soak | --cutover | --stop] [--branch NAME]
#
# The routine host's setup, idempotent, as the pickandroll user, nothing with sudo: the
# checkout on main (or --branch NAME for a verification run), the venv, Playwright's Chromium,
# the user units in ~/.config/systemd/user, the API and Xvfb up and the API restarted on the
# new code (never under a live draft room: GET /rooms must be [] or the API down). The timers
# are left as they are unless asked:
#   --soak     every league's lineup mode and every public league's moves mode set to dry_run
#              through the local API and read back, ROUTINE_FLAGS=--no-post (unless the user's
#              routine.env exists), the seven routine timers and the watchdog enabled: the
#              soak, the Mac still live
#   --cutover  ROUTINE_FLAGS= (posts on), the timers enabled; the modes are the user's own
#              clicks on the dashboard
#   --stop     the timers disabled (the rollback's first step); the API and Xvfb stay up
# What stays the user's is printed at the end. The runbook is docs/OPS.md.
set -euo pipefail

mode=""
branch="main"
while [ $# -gt 0 ]; do
  case $1 in
    --soak|--cutover|--stop) mode=${1#--} ;;
    --branch) [ $# -ge 2 ] || { echo "--branch needs a name" >&2; exit 2; }; branch=$2; shift ;;
    *) echo "usage: install.sh [--soak | --cutover | --stop] [--branch NAME]" >&2; exit 2 ;;
  esac
  shift
done

repo=${PICKANDROLL_REPO:-$HOME/pickandroll}
conf=${PICKANDROLL_CONF:-$HOME/.config/pickandroll}
api=${PICKANDROLL_API:-http://127.0.0.1:8000}
units=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
py=$repo/.venv/bin/python
timers="pickandroll-routine@daily.timer pickandroll-routine@morning.timer pickandroll-routine@late.timer
pickandroll-routine@evening-build.timer pickandroll-routine@evening-pass.timer pickandroll-routine@monday.timer
pickandroll-routine@signin.timer pickandroll-watchdog.timer"

say() { printf '%s\n' "$*"; }

# 1. the draft-room guard: no pull and no restart under a live room
rooms=$(curl -s --max-time 5 "$api/rooms" 2>/dev/null || true)
if [ -n "$rooms" ] && [ "$rooms" != "[]" ]; then
  say "refused: $api/rooms answers $rooms (a draft room is live); run again when it answers []"
  exit 3
fi

# 2. the checkout
before=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" fetch -q origin
git -C "$repo" checkout -q "$branch"
git -C "$repo" pull -q --ff-only origin "$branch"
after=$(git -C "$repo" rev-parse HEAD)
say "checkout: $branch at ${after:0:7}$([ "$before" = "$after" ] && echo ' (unchanged)' || echo " (was ${before:0:7})")"

# 3. the venv and the browser
[ -x "$py" ] || python3 -m venv "$repo/.venv"
"$repo/.venv/bin/pip" install -q -e "$repo[api,bbm,dev]"
"$repo/.venv/bin/playwright" install chromium >/dev/null
say "venv: $("$py" --version 2>&1), playwright $("$py" -c 'import playwright; print(playwright.__version__)')"

# 4. the units, the display and the API
mkdir -p "$units" "$conf"
chmod 700 "$conf"
cp "$repo"/ops/vm/*.service "$repo"/ops/vm/*.timer "$units"/
chmod 755 "$repo"/ops/vm/*.sh
systemctl --user daemon-reload
systemctl --user enable -q pickandroll-xvfb.service pickandroll-api.service
systemctl --user restart pickandroll-xvfb.service
systemctl --user restart pickandroll-api.service
for _ in $(seq 1 30); do
  curl -s --max-time 3 "$api/seasons" >/dev/null 2>&1 && break
  sleep 2
done
if curl -s --max-time 3 "$api/seasons" >/dev/null 2>&1; then
  say "api: up on $api ($(systemctl --user show -p MainPID --value pickandroll-api.service) is the listener)"
else
  say "api: not answering on $api after 60 s (journalctl --user -u pickandroll-api)"
  exit 1
fi

# 5. the user's settings folder
[ -s "$conf/ops_issue" ] || echo 225 > "$conf/ops_issue"
cat > "$conf/README" <<'TXT'
pickandroll routine host: the user's settings (never in the repo; the runbook is docs/OPS.md)
  ntfy_topic   one line, the ntfy.sh topic the alerts post to; absent, alerts go to the journal and the issue only
  ops_issue    one line, the GitHub issue the alerts comment on (225, the VM tracker, until the user rules another)
  routine.env  ROUTINE_FLAGS=... for every routine run: --no-post through the soak, empty after cut-over
TXT
[ -s "$conf/ntfy_topic" ] && say "alerts: ntfy topic set, issue #$(cat "$conf/ops_issue")" \
  || say "alerts: no ntfy topic yet ($conf/ntfy_topic), issue #$(cat "$conf/ops_issue")"

# 6. the timers, as asked
read_mode() {  # the mode in an API answer, defensively
  "$py" -c 'import json, sys
try:
    r = json.load(sys.stdin)
except Exception:
    print("no answer"); raise SystemExit
m = r.get("mode")
print(m.get("mode") if isinstance(m, dict) else m if m is not None else r.get("detail", r))'
}
case $mode in
  soak)
    [ -s "$conf/routine.env" ] || echo "ROUTINE_FLAGS=--no-post" > "$conf/routine.env"
    say "routine.env: $(cat "$conf/routine.env")"
    say "modes set to dry_run through the API:"
    leagues=$(curl -s --max-time 10 "$api/seasons" | "$py" -c 'import json, sys
print(" ".join(str(s["league"]) for s in json.load(sys.stdin) if "league" in s))')
    for league in $leagues; do
      out=$(curl -s --max-time 60 -X PUT -H 'Content-Type: application/json' -d '{"mode":"dry_run"}' "$api/leagues/$league/lineups")
      say "  lineups $league: $(printf '%s' "$out" | read_mode)"
    done
    curl -s --max-time 120 -X PUT -H 'Content-Type: application/json' -d '{"mode":"dry_run"}' "$api/autopilot/moves/mode" >/dev/null || true
    for league in $leagues; do
      out=$(curl -s --max-time 30 "$api/seasons/$league/autopilot/moves")
      say "  moves $league: $(printf '%s' "$out" | read_mode)"
    done
    # shellcheck disable=SC2086
    systemctl --user enable -q --now $timers
    say "timers: enabled (the soak)"
    ;;
  cutover)
    echo "ROUTINE_FLAGS=" > "$conf/routine.env"
    say "routine.env: ROUTINE_FLAGS= (posts on)"
    # shellcheck disable=SC2086
    systemctl --user enable -q --now $timers
    say "timers: enabled (cut-over); the leagues' switches are the user's own clicks on the dashboard"
    ;;
  stop)
    # shellcheck disable=SC2086
    systemctl --user disable -q --now $timers
    say "timers: disabled; the API and Xvfb stay up"
    ;;
  "")
    say "timers: left as they are (install.sh --soak, --cutover or --stop changes them)"
    ;;
esac
systemctl --user list-timers --all --no-pager 'pickandroll-*' | sed 's/^/  /'

# 7. the trial folder of the first droplet runs
if [ "$(id -un)" = "pickandroll" ] && [ -d "$HOME/trial" ]; then
  rm -rf "$HOME/trial"
  say "removed ~/trial (the first runs' scratch)"
fi

say ""
say "still the user's (docs/OPS.md):"
say "  - gh auth login (as this user) so the alerts can comment on the issue"
say "  - the ntfy topic in $conf/ntfy_topic, the app subscribed to it"
say "  - the one-time sign-in: ops/vm/signin.sh (VNC after 'sudo apt install -y x11vnc', or DevTools over ssh)"
say "  - on the Mac: ops/mac/README.md (the tunnel at cut-over, the nightly copy)"
