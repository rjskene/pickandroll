#!/usr/bin/env bash
# signin.sh (the Mac): one command to sign the routine host's browser profile in again (#238,
# docs/OPS.md §3). It starts ops/vm/signin.sh on the droplet inside a tmux session named
# "signin" (a dropped connection leaves it running; the same command reattaches), holds an ssh
# tunnel from this Mac's localhost to the browser's DevTools port while it runs, opens one
# DevTools window per site in Chrome from the browser's own /json/list, waits for Enter here
# once the user has signed in to both sites, relays it to the droplet (which closes the browser
# and runs the signin routine) and prints that routine's result lines. Exit 0 only when both
# sites report signed in. The droplet's address is the one line of ~/.config/pickandroll/droplet
# on the Mac (DROPLET= in rsync.env also serves; --host overrides), never written here.
# Nothing in this script reads, types or logs a credential: the password goes in through the
# DevTools Console line printed below, pasted by the user. With --keychain, keychain_fill.py
# beside this script reads each site's password from a Keychain item the user made by hand
# (pickandroll-bbm, pickandroll-yahoo) and puts it into the password field over the tunnel's
# DevTools websocket when the user presses Enter; the value is never an argument, a variable or a
# line of output of this script. Only the user runs this, by hand, from the Mac.
#   usage: ops/mac/signin.sh [--host USER@ALIAS] [--port 9222] [--no-open] [--remote-repo pickandroll] [--keychain]
set -u
conf=${PICKANDROLL_CONF:-$HOME/.config/pickandroll}
host=""
port=9222
open_windows=1
remote_repo=pickandroll
browser=${PICKANDROLL_BROWSER:-Google Chrome}
keychain=0
item_bbm=pickandroll-bbm
item_yahoo=pickandroll-yahoo
usage() { echo "usage: $0 [--host USER@ALIAS] [--port LOCAL_PORT] [--no-open] [--remote-repo DIR] [--keychain]" >&2; }
while [ $# -gt 0 ]; do
  case "$1" in
    --host|--port|--remote-repo)
      [ $# -ge 2 ] || { usage; exit 2; }
      case "$1" in
        --host) host=$2 ;;
        --port) port=$2 ;;
        --remote-repo) remote_repo=$2 ;;
      esac
      shift 2 ;;
    --no-open) open_windows=0; shift ;;
    --keychain) keychain=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [ -z "$host" ]; then
  if [ -s "$conf/droplet" ]; then
    host=$(tr -d '[:space:]' < "$conf/droplet")
  elif [ -s "$conf/rsync.env" ]; then
    host=$(sed -n 's/^DROPLET=//p' "$conf/rsync.env" | head -n 1 | tr -d '[:space:]')
  fi
fi
if [ -z "$host" ]; then
  echo "no droplet address: write it once with  mkdir -p $conf && echo pickandroll@<alias> > $conf/droplet  or pass --host" >&2
  exit 2
fi
py=${PICKANDROLL_PYTHON:-}
if [ -z "$py" ]; then
  if command -v python3 >/dev/null 2>&1; then py=python3; else py=$(cd "$(dirname "$0")/../.." && pwd)/.venv/bin/python; fi
fi
here=$(cd "$(dirname "$0")" && pwd)
if [ "$keychain" = 1 ]; then
  command -v security >/dev/null 2>&1 || { echo "--keychain needs the Mac's security command" >&2; exit 2; }
  for item in "$item_bbm" "$item_yahoo"; do
    # The item's existence only (no -w): the password itself is read by keychain_fill.py, in its
    # own process, when the field is on screen.
    if ! security find-generic-password -s "$item" >/dev/null 2>&1; then
      echo "no Keychain item '$item': create it with  security add-generic-password -s $item -a <account> -w  (<account> is your sign-in name on the site; it asks for the password twice)" >&2
      exit 2
    fi
  done
  [ -f "$here/keychain_fill.py" ] || { echo "$here/keychain_fill.py is missing" >&2; exit 2; }
fi
case "$remote_repo" in /*) rrepo=$remote_repo ;; *) rrepo="~/$remote_repo" ;; esac
rlog='~/.config/pickandroll/signin.log'
token="$(date +%Y%m%d-%H%M%S)-$$"

remote() { ssh -o BatchMode=yes -o ConnectTimeout=10 "$host" "$1"; }

remote true >/dev/null 2>&1 || { echo "ssh $host does not log in without a prompt (the key, ~/.ssh/config)" >&2; exit 2; }
remote "command -v tmux >/dev/null" || { echo "tmux is missing on the droplet (the user's sudo line: sudo apt install -y tmux)" >&2; exit 2; }

start=0
if remote "tmux has-session -t signin 2>/dev/null"; then
  # The [.] keeps the pattern from matching the remote shell's own command line.
  if remote "pgrep -u \$(id -u) -f 'ops/vm/signin_browser[.]py' >/dev/null"; then
    echo "reattaching: the droplet's signin.sh is already running in tmux session 'signin'"
  else
    echo "a stale tmux session 'signin' with no sign-in browser in it: removing it"
    remote "tmux kill-session -t signin"
    start=1
  fi
else
  start=1
fi
if [ "$start" = 1 ]; then
  active=$(remote "systemctl --user list-units 'pickandroll-routine@*.service' --state=active --no-legend --plain 2>/dev/null | awk '{print \$1}'")
  if [ -n "$active" ]; then
    echo "a routine holds the browser profile on the droplet right now ($(echo "$active" | tr '\n' ' ')); run this again once it ends" >&2
    exit 1
  fi
fi
remote "mkdir -p ~/.config/pickandroll && printf '=== mac signin %s\n' '$token' >> $rlog"
if [ "$start" = 1 ]; then
  remote "tmux new-session -d -s signin 'cd $rrepo && bash ops/vm/signin.sh 2>&1 | tee -a $rlog'" ||
    { echo "could not start signin.sh on the droplet" >&2; exit 1; }
  echo "started ops/vm/signin.sh on the droplet in tmux session 'signin' (to watch it: ssh -t $host tmux attach -t signin)"
fi

ssh -N -o BatchMode=yes -o ConnectTimeout=10 -o ExitOnForwardFailure=yes -L "127.0.0.1:$port:127.0.0.1:9222" "$host" &
tunnel=$!
trap 'kill $tunnel 2>/dev/null' EXIT
echo "tunnel: 127.0.0.1:$port on this Mac is the droplet browser's DevTools port (pid $tunnel, closed when this ends)"
list=""
for _ in $(seq 1 60); do
  kill -0 "$tunnel" 2>/dev/null || { echo "the tunnel ended: is local port $port in use? pass --port" >&2; exit 1; }
  if list=$(curl -s --max-time 3 "http://127.0.0.1:$port/json/list" 2>/dev/null) && [ -n "$list" ]; then break; fi
  sleep 1
done
[ -n "$list" ] || { echo "the droplet's browser did not answer on its DevTools port within 60 s (ssh -t $host tmux attach -t signin)" >&2; exit 1; }

read -r -d '' pycode <<'PY' || true
import json
import sys

port = sys.argv[1]
for page in json.load(sys.stdin):
    url = page.get("url") or ""
    front = page.get("devtoolsFrontendUrl") or ""
    if page.get("type") != "page" or not front:
        continue
    if not any(site in url for site in ("yahoo.com", "basketballmonster.com")):
        continue
    if front.startswith("/"):
        front = f"http://127.0.0.1:{port}{front}"
    for bound in ("127.0.0.1:9222/", "localhost:9222/"):
        front = front.replace(f"ws={bound}", f"ws=127.0.0.1:{port}/")
    print(front)
PY
urls=$(printf '%s' "$list" | "$py" -c "$pycode" "$port")
[ -n "$urls" ] || { echo "no Yahoo or Basketball Monster page in the browser's /json/list yet; run this again in a moment" >&2; exit 1; }
while IFS= read -r url; do
  [ -n "$url" ] || continue
  if [ "$open_windows" = 1 ]; then
    open -a "$browser" "$url" 2>/dev/null || open "$url"
    echo "opened DevTools: $url"
  else
    echo "DevTools: $url"
  fi
done <<< "$urls"

console_line="document.querySelector('input[type=password]').value = '...'"
if [ "$keychain" = 1 ]; then
  cat <<TEXT

In each DevTools window (the screencast is the droplet's browser; it takes clicks and keys):
  1. click the site's sign-in, type the username into the screencast's field and get to the
     password field (Yahoo asks for it on its second page);
  2. press Enter here: the password goes from this Mac's Keychain into that field over the tunnel
     (s + Enter skips the site: put it in with the Console line  $console_line  there instead);
  3. click Sign in and check the page shows you signed in.
TEXT
  for site in bbm yahoo; do
    case "$site" in
      bbm) item=$item_bbm; name="Basketball Monster" ;;
      yahoo) item=$item_yahoo; name="Yahoo" ;;
    esac
    while :; do
      printf '%s: with its password field on screen, press Enter to fill it from Keychain item %s (s + Enter skips): ' "$name" "$item"
      read -r answer || answer=s  # the end of input skips the site
      case "$answer" in s|S) echo "skipped $name: use the Console line there"; break ;; esac
      if "$py" "$here/keychain_fill.py" "$port" "$site" "$item"; then break; fi
    done
  done
  echo "When both sites are signed in, press Enter here: the droplet closes its browser and the signin routine confirms."
else
  cat <<TEXT

In each DevTools window (the screencast is the droplet's browser; it takes clicks and keys):
  1. click the site's sign-in, type the username into the screencast's field;
  2. click the password field, open the Console tab and run, with your password pasted between the quotes:
       $console_line
     (Yahoo asks for the password on its second page: do this there);
  3. click Sign in and check the page shows you signed in.
When both sites are signed in, press Enter here: the droplet closes its browser and the signin routine confirms.
TEXT
fi
read -r _
remote "tmux send-keys -t signin Enter" || echo "could not send Enter to the tmux session (press it there: ssh -t $host tmux attach -t signin)" >&2
result=""
for _ in $(seq 1 60); do
  result=$(remote "sed -n '/=== mac signin $token/,\$p' $rlog" 2>/dev/null) || result=""
  if printf '%s\n' "$result" | grep -q -E '^- yahoo:|did not run|^finished |^refused'; then break; fi
  sleep 3
done
lines=$(printf '%s\n' "$result" | grep -E '^- (bbm|yahoo):|did not run|^finished |^refused')
if [ -n "$lines" ]; then
  echo "the droplet's signin routine:"
  echo "$lines"
else
  echo "no result lines from the droplet within 3 minutes (ssh -t $host tmux attach -t signin)" >&2
fi
if printf '%s\n' "$result" | grep -q '^- bbm: ok' && printf '%s\n' "$result" | grep -q '^- yahoo: ok'; then
  echo "signed in on the droplet: both sites"
  exit 0
fi
echo "not signed in on both sites yet: run this again" >&2
exit 1
