#!/usr/bin/env bash
# signin.sh: the one-time sign-in into the routine browser's profile, done by the user, never
# by a session. The routine's Chromium (the same profile and extension the routines use) comes
# up on the Xvfb display with a tab on each site; the user reaches it from the Mac one of two
# ways, signs in to Yahoo and Basketball Monster, presses Enter here, and the signin routine
# confirms. No password passes through this script or any log.
#   VNC (the primary path)  x11vnc on the host, installed once by the user (sudo apt install -y
#       x11vnc) with a password of their own (x11vnc -storepasswd, typed by them); this script
#       starts it on localhost only. On the Mac:
#         ssh -L 5900:127.0.0.1:5900 pickandroll@hts-digital-ocean
#       then Screen Sharing (Finder, Go, Connect to Server) at vnc://127.0.0.1:5900
#   DevTools (nothing to install)  on the Mac:
#         ssh -L 9222:127.0.0.1:9222 pickandroll@hts-digital-ocean
#       then chrome://inspect/#devices in Chrome, "Configure..." with localhost:9222, "inspect"
#       on the tab; the screencast takes clicks and keys.
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

vnc_pid=""
if command -v x11vnc >/dev/null 2>&1; then
  if [ -f "$HOME/.vnc/passwd" ]; then
    x11vnc -display "$DISPLAY" -localhost -rfbport 5900 -rfbauth "$HOME/.vnc/passwd" -forever -shared -quiet \
      -o "$HOME/.vnc/x11vnc.log" >/dev/null 2>&1 &
    vnc_pid=$!
    echo "VNC: x11vnc on 127.0.0.1:5900 (pid $vnc_pid, stopped when this script ends). On the Mac:"
    echo "  ssh -L 5900:127.0.0.1:5900 pickandroll@hts-digital-ocean    then Screen Sharing at vnc://127.0.0.1:5900"
  else
    echo "VNC: x11vnc is installed but ~/.vnc/passwd is missing: run 'x11vnc -storepasswd' once (you type the password), then this script again."
  fi
else
  echo "VNC: x11vnc is not installed (the user's one sudo line: sudo apt install -y x11vnc)."
fi
echo "DevTools (no install): on the Mac  ssh -L 9222:127.0.0.1:9222 pickandroll@hts-digital-ocean"
echo "  then chrome://inspect/#devices in Chrome, Configure... localhost:9222, inspect the tab."
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
