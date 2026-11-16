#!/usr/bin/env bash
# update.sh: the guarded fast-forward of the routine host after a merge (docs/OPS.md §2a),
# lighter than install.sh (no venv, unit or timer work). Refused under a live draft room, while
# a routine unit runs (activating included, #398) or when a routine timer fires within 10 min.
# Then: main fast-forwarded; the dashboard rebuilt from web/ when
# web/ changed in the pull or its build is missing (served by the API under /app, built with
# --base=/app/ and the API at the page's own origin); the API restarted when src/ or
# pyproject.toml changed (or --restart). Prints what it did. Exit 3 when a guard holds, 1 when
# the API does not come back, 0 otherwise. The Mac's own room guard is the caller's.
#   usage: ops/vm/update.sh [--restart]
set -euo pipefail

restart=0
case ${1:-} in
  --restart) restart=1 ;;
  "") ;;
  *) echo "usage: update.sh [--restart]" >&2; exit 2 ;;
esac
repo=${PICKANDROLL_REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
api=${PICKANDROLL_API:-http://127.0.0.1:8000}
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}
say() { printf '%s\n' "$*"; }

# 1. the guards: no pull under a live room or a running routine
rooms=$(curl -s --max-time 5 "$api/rooms" 2>/dev/null || true)
if [ -n "$rooms" ] && [ "$rooms" != "[]" ]; then
  say "refused: $api/rooms answers $rooms (a draft room is live); run again when it answers []"
  exit 3
fi
# A routine is a oneshot: while it runs it is "activating", never "active" (#398). Any state but
# at rest (inactive or failed) holds the deploy. Asked again before the API's restart (step 4).
routines_busy() {
  systemctl --user list-units 'pickandroll-routine@*.service' --state=active,activating,deactivating,reloading --no-legend --plain 2>/dev/null | awk '{printf "%s%s %s", sep, $1, $3; sep=", "}'
}
busy=$(routines_busy)
if [ -n "$busy" ]; then
  say "refused: a routine runs ($busy); run again when it ends"
  exit 3
fi
# Nor just before one (#398): a routine timer due within $soon s holds it, so the API is never
# restarted under a routine that starts mid-deploy. The pre-tip check's timer fires every five
# minutes through the day and is left out of this; a pre-tip check that runs is held above.
soon=${PICKANDROLL_UPDATE_SOON:-600}
now=$(date +%s)
clock() { TZ=America/Chicago date -d "@$1" +%H:%M 2>/dev/null || TZ=America/Chicago date -r "$1" +%H:%M; }
# systemd 255 prints the next run as a date ("Tue 2026-11-17 11:00:00 UTC") whatever
# --timestamp says; older and newer ones may answer "@<unix>". GNU date reads the date; BSD date
# (the Mac's tests) reads only a UTC one. Anything else is not read, and holds the deploy.
epoch() {
  date -d "$1" +%s 2>/dev/null && return
  case $1 in *" UTC") date -ju -f "%a %Y-%m-%d %H:%M:%S" "${1% UTC}" +%s 2>/dev/null ;; *) return 1 ;; esac
}
for timer in $(systemctl --user list-units 'pickandroll-routine@*.timer' --all --no-legend --plain 2>/dev/null | awk '{print $1}'); do
  case $timer in pickandroll-routine@pretip.timer) continue ;; esac
  next=$(systemctl --user show "$timer" -p NextElapseUSecRealtime --value --timestamp=unix 2>/dev/null) || next="?"
  case $next in
    ""|n/a) continue ;;
    @[0-9]*) at=${next#@} ;;
    *) at=$(epoch "$next") || at="" ;;
  esac
  case $at in
    ""|*[!0-9]*) say "refused: the next run of $timer was not read ($next); run again once systemd answers"; exit 3 ;;
  esac
  left=$(( at - now ))
  if [ "$left" -ge 0 ] && [ "$left" -le "$soon" ]; then
    say "refused: $timer fires at $(clock "$at") CT, in $(( (left + 59) / 60 )) min; run again after its routine ends"
    exit 3
  fi
done

# 2. main, fast-forward only (the checkout stays on main; a diverged checkout is a stop)
before=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" fetch -q origin
git -C "$repo" merge -q --ff-only origin/main
after=$(git -C "$repo" rev-parse HEAD)
say "main: ${after:0:7}$([ "$before" = "$after" ] && echo ' (unchanged)' || echo " (was ${before:0:7})")"
changed() { [ "$before" != "$after" ] && ! git -C "$repo" diff --quiet "$before" "$after" -- "$@"; }

# 3. the dashboard the API serves under /app (docs/OPS.md §2a)
if ! command -v npm >/dev/null 2>&1; then
  say "dashboard: npm is missing, not built (the API serves none)"
elif [ ! -f "$repo/web/dist/index.html" ] || changed web; then
  (cd "$repo/web" && npm ci --no-audit --no-fund --silent && VITE_PICKANDROLL_API_BASE= npm run build --silent -- --base=/app/)
  say "dashboard: built from web/ at ${after:0:7}, served under /app"
else
  say "dashboard: unchanged"
fi

# 4. the API, restarted only on a code change (the room guard above covers it). A routine that
# started during the pull or the build (a pre-tip slate's run, #398) keeps the API: main and the
# dashboard stay as pulled, and the exit is 3, not a clean deploy.
if [ "$restart" = 1 ] || changed src pyproject.toml; then
  busy=$(routines_busy)
  if [ -n "$busy" ]; then
    say "api: not restarted: a routine runs ($busy); run update.sh --restart when it ends"
    exit 3
  fi
  systemctl --user restart pickandroll-api.service
  for _ in $(seq 1 30); do
    curl -s --max-time 3 "$api/seasons" >/dev/null 2>&1 && break
    sleep 2
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$api/seasons" 2>/dev/null || true)
  say "api: restarted, GET /seasons $code"
  [ "$code" = 200 ] || exit 1
else
  say "api: not restarted (no src/ or pyproject.toml change)"
fi
