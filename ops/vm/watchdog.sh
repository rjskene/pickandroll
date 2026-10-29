#!/usr/bin/env bash
# watchdog.sh: the morning check (06:45 Central). Did today's daily finish with no failed
# step, does the API answer, is the Mac's copy fresh? Prints each answer; exit 1 on any
# failure, and systemd's OnFailure= posts the alert. The copy stamp (data/routine/.copied-at,
# written by the Mac's rsync agent) is checked only once it exists: before cut-over there is
# no copy to be stale.
set -u
data=${PICKANDROLL_DATA:-$HOME/pickandroll/data}
api=${PICKANDROLL_API:-http://127.0.0.1:8000}
copy_max_h=${PICKANDROLL_COPY_MAX_H:-72}
py=${PICKANDROLL_PYTHON:-$HOME/pickandroll/.venv/bin/python}
[ -x "$py" ] || py=python3
bad=0

marker=$data/routine/daily.json
if [ ! -f "$marker" ]; then
  echo "daily marker: missing ($marker)"
  bad=1
elif ! "$py" - "$marker" "$(date +%F)" <<'PY'
import json
import sys

path, today = sys.argv[1], sys.argv[2]
try:
    m = json.load(open(path))
except Exception as exc:
    print(f"daily marker: unreadable ({exc})")
    raise SystemExit(1)
finished = str(m.get("finished_at") or "")[:10]
if finished != today:
    print(f"daily marker: finished {finished or 'never'}, not today ({today})")
    raise SystemExit(1)
steps = m.get("steps") or {}
failed = [k for k, s in steps.items() if isinstance(s, dict) and s.get("status") == "failed"]
if failed:
    what = ", ".join(f"{k} ({str(steps[k].get('detail', ''))[:120]})" for k in failed)
    print(f"daily marker: failed steps: {what}")
    raise SystemExit(1)
print(f"daily marker: finished {m.get('finished_at')} with no failed step")
PY
then
  bad=1
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$api/seasons" 2>/dev/null || echo 000)
if [ "$code" = "200" ]; then
  echo "api: 200 on GET $api/seasons"
else
  echo "api: $code on GET $api/seasons"
  bad=1
fi

stamp=$data/routine/.copied-at
if [ -f "$stamp" ]; then
  if ! "$py" - "$stamp" "$copy_max_h" <<'PY'
import os
import sys
import time

age_h = (time.time() - os.stat(sys.argv[1]).st_mtime) / 3600
limit = float(sys.argv[2])
if age_h > limit:
    print(f"mac copy: last copied {age_h:.0f} h ago, over {limit:.0f} h")
    raise SystemExit(1)
print(f"mac copy: {age_h:.0f} h ago")
PY
  then
    bad=1
  fi
else
  echo "mac copy: no stamp yet (before cut-over)"
fi
exit $bad
