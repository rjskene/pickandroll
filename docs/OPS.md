# OPS: the routine host

The six AUTOPILOT routines (`docs/AUTOPILOT.md` §3) and the sign-in check run on the user's
DigitalOcean droplet as systemd user units, off the Mac, since the VM move (#225). This is the
runbook: the host, the bootstrap, the one-time sign-in, the soak, cut-over, rollback, the alerts
and the morning check. The units and scripts are `ops/vm/`; the Mac's side is `ops/mac/`.

Standing rules apply unchanged: no session handles a credential or sees what the user types
into a login form; the browser profile, downloads and screens are never committed and never
copied to the Mac; the routines open pages and the extension acts, no session clicks on Yahoo;
`src/` is never pulled and the API never restarted under a live draft room.

## 1. The host

| | |
|---|---|
| host | the droplet, `ssh pickandroll@hts-digital-ocean` (the user's alias and key) |
| user | `pickandroll`, no sudo, `loginctl enable-linger` set, so its user units run with nobody logged in |
| checkout | `~/pickandroll` on `main`, venv `~/pickandroll/.venv` (Python 3.12, Playwright with its Chromium) |
| clock | the host is on UTC; every unit and timer carries `TZ=America/Chicago` and `OnCalendar=… America/Chicago`, so the routines keep their Central times |
| display | `Xvfb :99` (1440x900), a user service; the browser is headed on it |
| API | `uvicorn pickandroll.api:app` on 127.0.0.1:8000, a user service, `Restart=always`, `OOMScoreAdjust=-500` |
| data | `~/pickandroll/data/`, the only copy that counts after cut-over; `data/routine/` holds the runner's marker, run logs, profile, downloads and screens |
| settings | `~/.config/pickandroll/`: `ntfy_topic`, `ops_issue`, `routine.env` (the user's files; `install.sh` writes a README there) |

`systemctl --user` over ssh needs the user manager's environment:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u) DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
```

(`install.sh`, `signin.sh` and the units' scripts set it themselves.)

## 2. Bootstrap

Once, as `pickandroll` on the droplet (done on 2026-10-29 for the first runs; kept for a
rebuild):

```bash
git clone https://github.com/rjskene/pickandroll.git ~/pickandroll && ~/pickandroll/ops/vm/install.sh
```

`install.sh` is idempotent and needs no sudo. It refuses under a live draft room, pins the
checkout to `main` (`--branch NAME` for a verification run), makes the venv
(`pip install -e '.[api,bbm,dev]'`) and Playwright's Chromium, copies the units into
`~/.config/systemd/user`, enables and restarts Xvfb and the API, writes `ops_issue` (225 until
the user rules another) and leaves the timers as they are. The same command updates the host
after a merge: run it again (it pulls `main` and restarts the API, under the room guard).

What stays the user's, printed at the end: `gh auth login` as `pickandroll` (the alert's issue
comments), the ntfy topic in `~/.config/pickandroll/ntfy_topic` with the app subscribed to
it (a long random name: anyone who knows a topic's name can read it), the sign-in below, and
on the Mac the two agents of `ops/mac/README.md` at cut-over.

The runner's own fallback for a silent API (`scripts/draft_day.py servers --start`, the Mac's
launch entries) is a harmless no-op here: `~/code/.claude/launch.json` does not exist on the
host, and the API is the systemd service every routine instance `Wants=`.

## 3. The sign-in (the user, once, and again when the 04:50 check fails)

The routines' browser profile (`data/routine/profile`, mode 700) must hold the user's Yahoo
and Basketball Monster sessions. `ops/vm/signin.sh` brings the routine's own Chromium up on
the display with a tab on each site, waits for Enter, closes it and runs the `signin`
routine to confirm. The user drives the window from the Mac:

- **VNC, the primary path.** Once: `sudo apt install -y x11vnc` (the user's one sudo line)
  and `x11vnc -storepasswd` as `pickandroll` (they type the VNC password; it lives in
  `~/.vnc/passwd` on the droplet). `signin.sh` then starts x11vnc on localhost only. On the
  Mac: `ssh -L 5900:127.0.0.1:5900 pickandroll@hts-digital-ocean`, then Screen Sharing at
  `vnc://127.0.0.1:5900`.
- **DevTools, the fallback, nothing installed.** On the Mac:
  `ssh -L 9222:127.0.0.1:9222 pickandroll@hts-digital-ocean`, then `chrome://inspect/#devices`
  in Chrome, "Configure…" with `localhost:9222`, "inspect" on the tab: the screencast takes
  clicks and keys.

Either way no port is public and nothing of what is typed passes through a session or a log.
The `signin` routine exits 0 with both sites signed in; its timer runs it at 04:50 every day
and a failure alerts (a session expired, a password changed) before the daily at 05:00.

## 4. The soak (from the first sign-in to the cut-over)

The droplet runs every routine on its own copy of `data/` in dry run, posting nothing, while
the Mac stays live. Start it:

```bash
~/pickandroll/ops/vm/install.sh --soak
```

which sets every league's lineup mode and every public league's moves mode to `dry_run`
through the local API (the private league is refused by the API, as always: suggestions only),
prints the modes read back, writes `ROUTINE_FLAGS=--no-post` to `routine.env` unless the
user's own exists, and enables the seven routine timers and the watchdog.

During the soak both extensions act on Yahoo, the Mac's live and the droplet's in dry run,
from two addresses, and Basketball Monster is signed in from two places; the morning compare
watches for a sign-out on either (the `signin` check, the daily's `exports` step).

Each morning (the master, or the user), on the droplet:

```bash
ls -t ~/pickandroll/data/routine/runs/ | head; cat ~/pickandroll/data/routine/daily.json; systemctl --user list-timers --all 'pickandroll-*'; journalctl --user -u 'pickandroll-routine@*' --since yesterday -o cat | tail -60
```

against the Mac's own marker and run logs: the refresh codes, the export lines (the five
kinds, each saved or identical), the private league's pages opened and read back, the pass
summaries (entries due, pages opened), the run times against the windows (`docs/AUTOPILOT.md`
§3: daily 05:00 to 06:20, morning 07:45 to 14:30, late 15:00 to 20:30, evening-build 21:00 to
21:30, evening-pass 22:40 to 22:58, monday 06:00 to 12:00), and the `signin` result. A
difference is a finding on #225. The private league's solve outruns 300 s on this host (the
public ones take seconds); its ceiling is the runner's own follow-up, not a unit setting.

## 5. Cut-over: Monday 2026-11-09, after the 06:00 recorder

Only with `GET http://127.0.0.1:8000/rooms` answering `[]` on both hosts, in this order:

1. The master pauses the Mac's six Desktop routines (they stay defined for the rollback).
2. Droplet: `~/pickandroll/ops/vm/install.sh --stop` (the soak's timers off).
3. Mac: the final copy of the live data onto the droplet, the routine folder left alone:

   ```bash
   rsync -az --delete --exclude=/routine/ ~/code/pickandroll/data/ pickandroll@hts-digital-ocean:pickandroll/data/
   ```

4. Droplet: `~/pickandroll/ops/vm/install.sh --cutover` (`ROUTINE_FLAGS=` so the digests and
   recorder comments post again, the timers on). It sets no mode: the copy carries the Mac's
   switches, and any change is the user's own click on the dashboard.
5. Mac: stop the Mac's API (the port), load the tunnel agent (`ops/mac/README.md`), check
   `curl http://127.0.0.1:8000/seasons` answers from the droplet; the dashboard (`npm run
   dev` in `web/`, unchanged) and the Mac's Chrome extension now read the droplet's API.
   From here the Mac's launch entries `pickandroll-api` and `pickandroll-api-draft` must not
   be started while the tunnel holds :8000 (they would fail on the port, or take it from the
   tunnel after a drop), and `GET http://127.0.0.1:8000/rooms` on the Mac answers from the
   droplet, so the room guard reads the same answer on both hosts.
6. Mac: write `rsync.env` and load the nightly copy agent (`ops/mac/README.md`): from the
   next 03:30 the droplet's `data/` is copied into the Mac checkout's `data/` (the browser
   profile, downloads and screens excluded; the copy adds and updates, never deletes, so the
   Mac's own folders stay), and each copy stamps `data/routine/.copied-at` on the droplet,
   which its watchdog checks.
7. The user checks the leagues' switches on the dashboard; the first live pass is the 07:45
   morning pass of the next day.

The dashboard stays on the Mac: a droplet-hosted one over Tailscale (`tailscale serve`, sudo)
is a follow-up for the user, not part of the move.

## 6. Rollback

Any time, in this order: droplet `install.sh --stop` (the timers off, nothing else touched); Mac
`launchctl unload` of both agents and `rsync.env` deleted (`ops/mac/README.md`), which frees
:8000; one last copy droplet to Mac by hand (`bash ops/mac/rsync-from-droplet.sh` before the env
file goes, or the rsync line of §5 step 3 with the two hosts swapped and without `--delete`; the
copy adds and updates, never deletes, so the Mac's own folders stay); only then the Mac's API
started again through `launch.json` (`pickandroll-api`, never while the tunnel is loaded); the
master re-enables the six Desktop routines. The Mac's Chrome is still signed in to both sites; the
droplet keeps its profile for the next attempt.

## 7. Alerts and the watchdog

- A routine instance that exits 1 (a failed step) or 2 (the API never answered) is a failed
  unit; 3 (refused, outside its window, a timer catching up after a reboot) and 4 (STOP set)
  are not. systemd's `OnFailure=` starts `pickandroll-alert@<unit>`, and `ops/vm/alert.sh`
  posts the unit, the host, the time and the newest run log's failed steps and alerts to the
  ntfy topic and as a comment on the ops issue (#225 until the user rules another). The journal
  stays on the host: `journalctl --user -u pickandroll-routine@daily -n 40`.
- The watchdog (06:45 Central) fails, and so alerts, when `data/routine/daily.json` is
  missing, not today's or has a failed step, when `GET /seasons` is not 200, or when the Mac's
  copy stamp is older than 72 h (once it exists).
- The `signin` timer (04:50) fails, and so alerts, when either site is signed out: §3 again.
- The API restarts itself (`Restart=always`, no start limit); a restart loop shows as the
  routines' exit 2 and the watchdog's probe.

The alert comment carries the runner's own lines (step names, statuses, counts, URLs with
league and player ids), never a page's content.

## 8. Checks by hand

```bash
systemctl --user status pickandroll-api pickandroll-xvfb; systemctl --user list-timers --all 'pickandroll-*'; systemctl --user start pickandroll-routine@signin.service; journalctl --user -u pickandroll-routine@signin -o cat -n 20
```

A routine outside its window, for a check: `ROUTINE_FLAGS` aside,
`cd ~/pickandroll && TZ=America/Chicago DISPLAY=:99 .venv/bin/python scripts/routine.py daily --dry-run --no-post --no-marker --force`.

**On the Mac, before cut-over, a run is `--dry-run`, `--no-marker` or `--no-browser` only.** A
real daily there would overwrite the Desktop task's `data/routine/daily.json` and turn the
status light amber, and its browser profile is the host's own. The droplet's `data/` copy is its
own until the final copy at cut-over, so every routine may run there in full.
