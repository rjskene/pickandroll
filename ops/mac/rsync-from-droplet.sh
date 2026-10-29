#!/usr/bin/env bash
# rsync-from-droplet.sh: the Mac's nightly copy of the routine host's data/ (one way, droplet
# to Mac, the rollback copy), run by the com.pickandroll.rsync launchd agent at 03:30, or by
# hand. The settings are ~/.config/pickandroll/rsync.env on the Mac:
#   DROPLET=pickandroll@hts-digital-ocean
#   REMOTE_DATA=pickandroll/data
#   LOCAL_DATA=/Users/<me>/code/pickandroll/data
# Without that file nothing is copied: it is the switch, written at cut-over (docs/OPS.md),
# because before it the Mac's data/ is the live one. The copy skips, with a line, while a draft
# room is live on either host (GET /rooms not []); the browser profile, downloads and screens
# are never copied. It never deletes: the Mac's data/ holds folders that exist nowhere else
# (studies, the external and fidelity archives, draft day, Yahoo history), so a rollback copy
# may carry stale extra files, which is harmless, and erases nothing. On success it stamps
# data/routine/.copied-at on the droplet, which the droplet's watchdog checks (an alert once it
# is older than 72 h).
set -u
conf=${PICKANDROLL_CONF:-$HOME/.config/pickandroll}
env_file=$conf/rsync.env
log=$conf/rsync.log
stamp() { date '+%Y-%m-%d %H:%M:%S %Z'; }
note() { printf '%s %s\n' "$(stamp)" "$*" | tee -a "$log" 2>/dev/null || printf '%s %s\n' "$(stamp)" "$*"; }

if [ ! -f "$env_file" ]; then
  echo "$(stamp) rsync: $env_file missing, nothing copied (not enabled before cut-over)"
  exit 0
fi
# shellcheck disable=SC1090
. "$env_file"
: "${DROPLET:?DROPLET missing in $env_file}" "${REMOTE_DATA:?REMOTE_DATA missing in $env_file}" "${LOCAL_DATA:?LOCAL_DATA missing in $env_file}"
if [ ! -d "$LOCAL_DATA" ]; then
  note "rsync: $LOCAL_DATA is not a folder, nothing copied"
  exit 1
fi

ssh_opts="-o BatchMode=yes -o ConnectTimeout=20"
# The guard on both hosts: a draft room is never copied under; an API that does not answer
# has no room.
# shellcheck disable=SC2086
remote_rooms=$(ssh $ssh_opts "$DROPLET" 'curl -s --max-time 5 http://127.0.0.1:8000/rooms' 2>/dev/null) || {
  note "rsync: $DROPLET did not answer over ssh, nothing copied (the droplet's watchdog alerts after 72 h)"
  exit 0
}
if [ -n "$remote_rooms" ] && [ "$remote_rooms" != "[]" ]; then
  note "rsync: a draft room is live on $DROPLET ($remote_rooms), nothing copied"
  exit 0
fi
local_rooms=$(curl -s --max-time 5 http://127.0.0.1:8000/rooms 2>/dev/null || true)
if [ -n "$local_rooms" ] && [ "$local_rooms" != "[]" ]; then
  note "rsync: a draft room is live on this Mac ($local_rooms), nothing copied"
  exit 0
fi

if rsync -az \
    --exclude=/routine/profile/ --exclude=/routine/downloads/ --exclude=/routine/screens/ \
    -e "ssh $ssh_opts" "$DROPLET:$REMOTE_DATA/" "$LOCAL_DATA/" >>"$log" 2>&1; then
  # shellcheck disable=SC2086
  ssh $ssh_opts "$DROPLET" "mkdir -p $REMOTE_DATA/routine && date -u +%FT%TZ > $REMOTE_DATA/routine/.copied-at" 2>/dev/null \
    && note "rsync: copied $DROPLET:$REMOTE_DATA/ into $LOCAL_DATA/ and stamped .copied-at" \
    || note "rsync: copied, but the stamp on $DROPLET failed"
  exit 0
fi
note "rsync: the copy failed (see $log)"
exit 1
