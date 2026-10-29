#!/usr/bin/env bash
# alert.sh <unit>: a failed unit (a routine instance or the watchdog) reported to the user's
# ntfy topic and as a comment on the ops issue. The channels are the user's files in
# ~/.config/pickandroll (ntfy_topic, ops_issue), never in the repo; a missing one skips that
# channel and says so. The comment carries the runner's own lines (step names, statuses, the
# details' counts and URLs); the journal stays on the host. Never fails: an alert that failed
# would only be noise on top of the failure.
set -u
unit=${1:?the failed unit}
conf=${PICKANDROLL_CONF:-$HOME/.config/pickandroll}
data=${PICKANDROLL_DATA:-$HOME/pickandroll/data}
py=${PICKANDROLL_PYTHON:-$HOME/pickandroll/.venv/bin/python}
[ -x "$py" ] || py=python3
host=$(hostname -s 2>/dev/null || hostname)
when=$(date '+%Y-%m-%d %H:%M %Z')

# The routine's name sits between the "@" and ".service"; the watchdog has none.
routine=${unit#pickandroll-routine@}
routine=${routine%.service}
summary=""
if [ "$routine" != "$unit" ]; then
  newest=$(ls -t "$data"/routine/runs/*-"$routine".json 2>/dev/null | head -n 1)
  if [ -n "$newest" ]; then
    summary=$("$py" - "$newest" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    r = json.load(open(path))
except Exception as exc:  # a half-written log is still worth a line
    print(f"run log {path.rsplit('/', 1)[-1]}: unreadable ({exc})")
    raise SystemExit(0)
state = (
    "refused" if r.get("refused") else "stopped" if r.get("stopped") else "failed" if r.get("failed") else "ok"
)
started = str(r.get("started_at") or "")[11:19]
finished = str(r.get("finished_at") or "")[11:19] or "never"
print(f"newest run log {path.rsplit('/', 1)[-1]}: {r.get('routine')} {state}, started {started}, finished {finished}")
for s in r.get("steps", []):
    if s.get("status") == "failed":
        print(f"- {s.get('name')}: failed, {str(s.get('detail', ''))[:200]}")
for a in r.get("alerts", []):
    print(f"! {str(a)[:200]}")
PY
    )
  else
    summary="no run log for $routine yet (a run that never reached the API writes none)"
  fi
fi
journal=$(journalctl --user -u "$unit" -n 40 --no-pager -o cat 2>/dev/null | tail -n 40)
[ -n "$journal" ] || journal="(no journal lines for $unit)"

headline="$unit failed on $host at $when"
echo "$headline"
[ -z "$summary" ] || echo "$summary"

if [ -s "$conf/ntfy_topic" ]; then
  topic=$(tr -d '[:space:]' < "$conf/ntfy_topic")
  if printf '%s\n\n%s\n\njournal (last lines):\n%s\n' "$headline" "$summary" "$journal" | head -c 3800 |
    curl -s --max-time 20 -H "Title: pickandroll: $unit failed" -H "Priority: high" -H "Tags: warning" \
      --data-binary @- "https://ntfy.sh/$topic" >/dev/null; then
    echo "ntfy: posted to the topic"
  else
    echo "ntfy: the post failed"
  fi
else
  echo "ntfy: no topic in $conf/ntfy_topic, skipped"
fi

if [ -s "$conf/ops_issue" ]; then
  issue=$(tr -d '[:space:]' < "$conf/ops_issue")
  if printf '**%s** failed on %s at %s.\n\n%s\n\nThe journal: `journalctl --user -u %s -n 40` on the host.\n' \
      "$unit" "$host" "$when" "${summary:-(no run log summary)}" "$unit" |
    gh issue comment "$issue" --body-file - >/dev/null 2>&1; then
    echo "gh: commented on #$issue"
  else
    echo "gh: the comment on #$issue failed (gh auth login as this user?)"
  fi
else
  echo "gh: no issue in $conf/ops_issue, skipped"
fi
exit 0
