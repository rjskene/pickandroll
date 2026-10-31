# ops/vm: the routine host

The six AUTOPILOT routines and the sign-in check as systemd user units on the droplet, run
as the `pickandroll` user with no sudo. `install.sh` puts everything in place; `docs/OPS.md`
is the runbook (bootstrap, the sign-in, the soak, cut-over, rollback).

| file | what |
|---|---|
| `pickandroll-api.service` | uvicorn on 127.0.0.1:8000, always up, Central clock |
| `pickandroll-xvfb.service` | the virtual display the routine browser runs on |
| `pickandroll-routine@.service` | one routine run: `scripts/routine.py <instance> $ROUTINE_FLAGS` |
| `pickandroll-routine@<name>.timer` | daily 05:00, morning 07:45, late 15:00, evening-build 21:00, evening-pass 22:40, monday Mon 06:00, signin 04:50 (Central) |
| `pickandroll-alert@.service`, `alert.sh` | a failed unit posted to ntfy and the ops issue |
| `pickandroll-watchdog.service/.timer`, `watchdog.sh` | 06:45: the daily marker, the API, the Mac copy's age |
| `install.sh` | the setup, the dashboard's build (`web/dist`, served by the API under `/app` for the tailnet); `--soak`, `--cutover`, `--stop` for the timers |
| `update.sh` | the guarded fast-forward after a merge: `main`, the dashboard rebuilt when `web/` changed, the API restarted when `src/` changed |
| `signin.sh`, `signin_browser.py` | the user's sign-in into the browser profile, driven from the Mac by `ops/mac/signin.sh` |
