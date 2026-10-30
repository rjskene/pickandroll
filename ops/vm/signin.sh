#!/usr/bin/env bash
# signin.sh: the one-time sign-in into the routine browser's profile, done by the user, never
# by a session. The routine's Chromium (the same profile and extension the routines use) comes
# up on the Xvfb display with a tab on each site and its DevTools port on localhost; the user
# signs in to Yahoo and Basketball Monster from the Mac, presses Enter here, and the signin
# routine confirms. No password passes through this script or any log.
#   From the Mac, one command does all of it (docs/OPS.md §3, #238):
#         bash ~/code/pickandroll/ops/mac/signin.sh
#       it runs this script in a tmux session, tunnels the DevTools port and opens the windows.
#   By hand, DevTools (nothing to install):  ssh -L 9222:127.0.0.1:9222 pickandroll@hts-digital-ocean
#       then chrome://inspect/#devices in Chrome, "Configure..." with localhost:9222, "inspect".
#   VNC stays possible: x11vnc on the host (sudo apt install -y x11vnc, x11vnc -storepasswd by
#       the user) is started below on localhost; on the Mac a real VNC client on a free local
#       port (ssh -L 5901:127.0.0.1:5900, TigerVNC at 127.0.0.1:5901), never Screen Sharing.
set -u
repo=${PICKANDROLL_REPO:-$HOME/pickandroll}
profile=${PICKANDROLL_PROFILE:-$repo/data/routine/profile}
extension=${PICKANDROLL_EXTENSION:-$repo/extension}
export DISPLAY=${DISPLAY:-:99}
export TZ=America/Chicago
export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
py=$repo/.venv/bin/python

if ! systemctl --user is-active -q pickandroll-xvfb.service; then
  systemctl --user start pickandroll-xvfb.service || { echo "Xvfb is not up (systemctl --user status pickandroll-xvfb)"; exit 1; }
  sleep 1
fi

echo "From the Mac, one command does the rest:  bash ~/code/pickandroll/ops/mac/signin.sh   (docs/OPS.md §3)"
echo "By hand: ssh -L 9222:127.0.0.1:9222 pickandroll@hts-digital-ocean, then chrome://inspect/#devices in Chrome,"
echo "  Configure... localhost:9222, inspect each tab; the screencast takes clicks and keys."
vnc_pid=""
if command -v x11vnc >/dev/null 2>&1 && [ -f "$HOME/.vnc/passwd" ]; then
  x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -rfbauth "$HOME/.vnc/passwd" -forever -shared -quiet \
    -o "$HOME/.vnc/x11vnc.log" >/dev/null 2>&1 &
  vnc_pid=$!
  echo "VNC too: x11vnc on 127.0.0.1:5900 (pid $vnc_pid, stopped when this script ends); a real VNC client on a free"
  echo "  local port (ssh -L 5901:127.0.0.1:5900, TigerVNC at 127.0.0.1:5901), never Screen Sharing."
fi
echo

"$py" "$repo/ops/vm/signin_browser.py" "$profile" "$extension"
rc=$?
[ -z "$vnc_pid" ] || kill "$vnc_pid" 2>/dev/null
if [ $rc -ne 0 ]; then
  echo "the browser did not run (exit $rc)"
  exit $rc
fi

echo
echo "the signin routine confirms:"
"$py" "$repo/scripts/routine.py" signin --force --no-post
