# OPS: the routine host

The six AUTOPILOT routines (`docs/AUTOPILOT.md` §3), the sign-in check and the pre-tip check run on the user's
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
| dashboard | the API serves the web app's build (`web/dist`, made by `install.sh` and `update.sh`) under `/app`; reached over the tailnet only, through the host's `tailscale serve` entry to the API (§2a) |
| data | `~/pickandroll/data/`, the only copy that counts after cut-over; `data/routine/` holds the runner's marker, run logs, profile, downloads and screens |
| the extension's worker | the profile keeps a compiled copy of the extension's background worker (`Default/Service Worker`) and runs it on every launch: `--load-extension` reads the manifest and the content scripts from the checkout again, never the worker. The runner drops that folder before a launch whenever the extension's files changed since the stamp in the profile (`.pickandroll-extension`); the sign-ins and the extension's own records are kept. Until that guard, the droplet ran the worker of 2026-10-29 under extension 0.11.2, and the first live late pass (2026-11-02) skipped every lineup set with "no answer from the extension" (#301) |
| a lineup page | open thirty seconds (`LINEUP_WAIT_S`, as for Start Active): the extension posts the page about four seconds in, then sets each change and reads Yahoo's answer before the next. Eight seconds cut five of nine live late runs off mid-set on 2026-11-02 (#301); a run cut off leaves its record unlogged, the next visit logs it as failed a minute later, and the same pass does not set that league again that day |
| settings | `~/.config/pickandroll/`: `ntfy_topic`, `ops_issue`, `routine.env` (the user's files; `install.sh` writes a README there) |
| the moves solve | every league's, the private one's included, keeps to the moves budget (`moves_budget_s` in the autopilot settings file, 90 s by default, read at each solve: no restart) and answers the best sets found by then, its `search.note` saying how many searches finished, and the `solve` step's detail naming the leagues the budget cut or whose search stopped on a cycle (#364); a solve whose client went stops and is never kept, and the Moves view never waits on one (#306). Measured 2026-11-03: the private league's solve takes 13.6 s here against 3.7 s on the Mac (each evaluation about four times slower on this host), the largest public league's 6.1 s. Before the budget, `--skip-solve 31822` in `ROUTINE_FLAGS` left that league's solve out here, after a run of 2026-10-29 went thirty minutes without finishing; once #306 merged, the cut-over's `ROUTINE_FLAGS=--skip-solve 31822` in `routine.env` was emptied by hand on this host, the file before kept beside it as `routine.env.pre-306` |

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
the user rules another), builds the dashboard (§2a) and leaves the timers as they are. The same
command updates the host after a merge: run it again (it pulls `main` and restarts the API,
under the room guard). The lighter update after a merge is `ops/vm/update.sh` (§2a): the
fast-forward of `main` under the room and routine guards, the dashboard rebuilt when `web/`
changed, the API restarted when `src/` or `pyproject.toml` changed, nothing else touched.

`update.sh` copies no unit: a merge that adds a timer reaches systemd only by hand. The pre-tip
check's (#355, `pickandroll-routine@pretip.timer`, every five minutes 09:00 to 20:55 Central)
goes in once, by the user, after the `update.sh` that pulls it:

```bash
cp ~/pickandroll/ops/vm/pickandroll-routine@.service ~/pickandroll/ops/vm/pickandroll-routine@pretip.timer ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now pickandroll-routine@pretip.timer
```

(`install.sh --cutover` does the same with every unit, and restarts the API.) The timer is
harmless on its own: a check with no slate due is refused (exit 3, not a failure) before any
browser, lock or report, and no slate is due while `pretip.enabled` is false in
`data/autopilot/executor.json`, which stays false until the user turns the pass on.

Every Chromium on the profile takes `data/routine/browser.lock` (`flock`, #355): the routines
when their browser launches, and the sign-in browser (`ops/vm/signin_browser.py`), which
refuses while a routine holds it. A routine that cannot have it waits (the pre-tip pass 15
minutes, then skips; the others 20, then fail with an alert naming the holder; the evening pass
never past 22:58).

What stays the user's, printed at the end: `gh auth login` as `pickandroll` (the alert's issue
comments; gh itself is already installed), the ntfy topic in `~/.config/pickandroll/ntfy_topic` with the app subscribed to
it (a long random name: anyone who knows a topic's name can read it), the sign-in below, and
on the Mac the two agents of `ops/mac/README.md` at cut-over.

The runner's own fallback for a silent API (`scripts/draft_day.py servers --start`, the Mac's
launch entries) is a harmless no-op here: `~/code/.claude/launch.json` does not exist on the
host, and the API is the systemd service every routine instance `Wants=`.

## 2a. The dashboard on the tailnet (#262)

The host's API serves the web app's build when `web/dist/index.html` exists: the page under
`/app` (`/app/`, `/app/progress`, `/app/queue`, with `?league=` and `?session=` as on the Mac),
its files under `/app/assets`. The API's own routes are what they were, so `/progress` is
still the Progress screen's JSON. The build is made on the host by `install.sh` and by
`update.sh` (Node is on the host) with `vite build --base=/app/` and `VITE_PICKANDROLL_API_BASE`
set empty, which makes the page call the API at its own origin: no CORS, no second address.
The Mac's checkout holds no build (`web/dist` is gitignored), so the Mac's API serves none and
its dashboard stays the dev server with its `/api` proxy, unchanged.

The address is the host's `tailscale serve` entry to the API, tailnet only: `tailscale serve
status` on the host lists it (an HTTPS port of the host's MagicDNS name proxied to
`http://127.0.0.1:8000`), and the dashboard is that address with `/app/` appended. The API
itself binds 127.0.0.1 and nothing opens a port on the public interface; a device off the
tailnet reaches neither. Recreating the entry, should it be lost, is the user's command on the
host (`tailscale serve --bg --https=<port> http://127.0.0.1:8000`, as the Tailscale operator).

After a web PR merges, `update.sh` (or `install.sh`) rebuilds; the API serves the new files
without a restart. During the soak the host's dashboard shows the host's own copy of `data/`
(the dry run), and a switch clicked there is the host's, not the Mac's; after cut-over it is
the live one, and the Mac's tunnel of §5 is a second way in rather than the only one.

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Accept: text/html' http://127.0.0.1:8000/app/   # 200 on the host once built
```

## 3. The sign-in (the user, once, and again when the 04:50 check fails)

The routines' browser profile (`data/routine/profile`, mode 700) must hold the user's Yahoo
and Basketball Monster sessions. One command on the Mac does the whole re-sign-in (#238):

```bash
bash ~/code/pickandroll/ops/mac/signin.sh
```

It needs the droplet's address once, in `~/.config/pickandroll/droplet` on the Mac (one line,
`pickandroll@hts-digital-ocean`; `--host` overrides it), and a key that logs in without a
prompt. The script starts `ops/vm/signin.sh` on the droplet inside a tmux session named
`signin` (a dropped connection leaves it running; running the command again reattaches), holds
an ssh tunnel from the Mac's localhost to the browser's DevTools port while it runs, opens one
DevTools window per site in Chrome from the browser's own `/json/list` (the sign-in browser
allows that frontend's origin on its port with `--remote-allow-origins`; Chrome refuses every
other origin's websocket, which is what the first run on 2026-10-31 hit), and prints the steps:
in each window, type the username into the screencast's field, put the password in with one
Console line, `document.querySelector('input[type=password]').value = '…'` with the password
pasted between the quotes (Yahoo asks for it on its second page), and click Sign in. Enter on
the Mac closes the droplet's browser and runs the `signin` routine there; the script prints its
two result lines and exits 0 only when both say signed in. A few minutes in all; no port is
public, and nothing typed passes through a session, a routine or a log. `--port` moves the
Mac's end of the tunnel when 9222 is taken, `--no-open` prints the DevTools URLs instead of
opening them.

`--keychain` spares the typing. The user makes two Keychain items once, by hand,
`security add-generic-password -s pickandroll-bbm -a <account> -w` and the same with
`pickandroll-yahoo` (`<account>` is the sign-in name on the site; the command asks for the
password twice). Then, at each site's prompt, with the site's page on screen in the DevTools
window (its front page or its sign-in page), one Enter on the Mac has `ops/mac/keychain_fill.py`
walk to the password field and fill it: the item's account name goes into the username field; on
Yahoo it clicks Next and, when Yahoo answers with its passkey page, "Try signing in another way"
and the option that names the password (any visible option whose text contains "password",
never a forgot or reset link); on Yahoo's account chooser (`/manage_account`, where a sign-out
lands, with the account's tile saying "Signed out") it clicks that tile at the account's e-mail
(its link or button, else the innermost element showing the e-mail), never Remove, nothing that
holds the Remove button and never "Use a different account", and the username step is skipped
since the chooser carries it; on Basketball
Monster's front page it clicks Login (its sign-in page shows both fields at once). Every click is
a mouse event on an element found by its visible text, never a form submit, and Sign in is never
clicked: the user clicks it, and Yahoo may then ask for a verification code, typed into the
screencast by hand (seen on the first real run, 2026-10-31; whether the browser's persistent
profile spares it next time is open). The password is read
from the item in the helper's own process only once the field is on the page, and goes to the
websocket as one `Input.insertText`, never into a shell argument, an environment variable, a
line of output or a log; the account name is not printed either. A page the helper does not
know (a verification code, a captcha) stops it with the page's path and nothing more typed; the
user continues by hand in the window and presses Enter again, which also fills a password field
that is already on screen. A missing item stops the script before it touches the droplet and
prints the add line; `s` and Enter at a prompt skips that site (the Console line still works
there). Keychain may ask once whether `security` may read an item: allow it. Only the user runs
this command, by hand, from the Mac; no routine, timer or Claude session calls it.

VNC stays possible with a real VNC client on a free local port (TigerVNC at `127.0.0.1:5901`
over `ssh -L 5901:127.0.0.1:5900`), never macOS Screen Sharing: it refuses every address of the
Mac itself, its own service holds port 5900 on every local address, and on 2026-10-29 that path
cost two hours while the clipboard and right-click never reached x11vnc and the keys typed into
the VNC window drifted in case, which locked the Basketball Monster account for a while. The
DevTools route above is the one this runbook keeps.

The `signin` routine exits 0 with both sites signed in; its timer runs it at 04:50 every day
and a failure alerts (a session expired, a password changed) before the daily at 05:00, naming
the Mac command.

A site's check reads one page (Basketball Monster's front page, the private league's page) and
ends in one of three states (#364): signed in; signed out (the page loaded and shows it: the
sign-in redirect, the consent page, a sign-in form, no My Team or Logout link); or the page did
not load (the load raised, or it answered a server error, 429 or Yahoo's 999). Only signed out
is the user's re-sign-in. A page that did not load is tried three times, 15 s and 45 s apart, and
is not kept for the run, so each browser step after it checks again. In a long outage a step's
check costs the 60 s of waits plus its three loads: about a minute when the site answers 502 at
once, up to four minutes when each load hangs to its 60 s timeout. The daily has five such steps
(the exports on Basketball Monster; the private pages, the lineup pages, Start Active and the
lineups on Yahoo), so about 5 minutes and at worst 20 inside its 05:00-05:45 window; a pretip
slate has up to four. The step fails with "the <site> sign-in check page did not
load after 3 tries (<reason>): not a sign-out", its `signin` data has the state, the reason and
the tries, and its alert never asks for a sign-in. On 2026-11-12 Yahoo's 502 at 05:00 was read as
signed out for the whole daily.

## 4. The soak (from the first sign-in to the cut-over)

The droplet runs every routine on its own copy of `data/` in dry run, posting nothing, while
the Mac stays live. Start it:

```bash
~/pickandroll/ops/vm/install.sh --soak
```

which sets every league's lineup mode and every public league's moves mode to `dry_run`
through the local API (the private league is refused by the API, as always: suggestions only),
prints the modes read back, writes `ROUTINE_FLAGS=--no-post` to `routine.env` unless the
user's own exists (no posts), and enables the routine timers (eight since #355) and the watchdog. Until #306
the soak also left the private league's solve out (`--skip-solve 31822`, §1).

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
§3: daily 05:00 to 06:20, morning 07:45 to 14:30 with its timer at 09:15, after the user's
09:00 execute time, late 15:00 to 20:30, evening-build 21:00 to 21:30, evening-pass 22:40 to
22:58, monday 06:00 to 12:00, the pre-tip check every five minutes 09:00 to 20:55), and the
`signin` result. A
difference is a finding on #225. Through the soak the private league's solve was left out on
this host (`--skip-solve 31822`, §1): the solve step reported it as left out and stayed ok.

The comparison of the two hosts is one command on the Mac, read-only on both:

```bash
~/code/pickandroll/scripts/soak_compare.py --date 2026-10-31
```

It bundles the Mac's `data/` and the droplet's (its `bundle` form over ssh, with the system
python) and prints markdown: the daily marker step by step, the droplet's run logs, the five
exports' names and sizes, the refresh and solve codes, the queue by league and by entry id, the
decision log's last moves solve of each league (its sets by player id), the executors' log and
the pass records. Flagged: a marker step whose status differs, a failed step or an alert in a
droplet run log, a daily finished after 06:20, an export missing or more than 5% smaller on the
droplet, a refresh or solve code that is not a success, a queue entry (matched by league, add
and drop) on one side only or differing in set, judged horizon, start day, availability, queued
state, reason, bid, rank or struck state, a league row differing in status, cap, budget or adds
left, a recommended set whose moves differ or whose odds are apart by the tolerance or more
(`--tolerance`, default 0.01), and a lineup the droplet would set other than the Mac set it. Not
flagged: the private league's solve absent on the droplet, the droplet's post step skipped, the
pass records' and the executors' wording (live against dry run), timestamps, export file names
and each host's own decision ids (the solve a queue row names is compared by content under
Solves; a row built from an earlier solve than the day's last is a note). Odds apart by less
than the tolerance are notes: in the head, not in the exit code. Exit 0 when nothing is
flagged, 1 otherwise, 2 when a side could not be read; `--post` puts the markdown on #225 as
one comment. Player and league ids only, never a name.

## 5. Cut-over: Monday 2026-11-02, after the 06:00 recorder

Moved up from 2026-11-09 on 2026-10-31, on the condition that Saturday evening's and Sunday's
comparisons (§4) are clean: every substantive flag explained, none the droplet's. The Mac's 05:00
daily and 06:00 recorder of that Monday are the last live runs on the Mac and the data the copy
below carries; the step-by-step timetable is on #225.

Only with `GET http://127.0.0.1:8000/rooms` answering `[]` on both hosts, in this order:

1. The master pauses the Mac's six Desktop routines (they stay defined for the rollback).
2. Droplet: `~/pickandroll/ops/vm/install.sh --stop` (the soak's timers off).
3. Mac: the final copy of the live data onto the droplet, the routine folder left alone:

   ```bash
   rsync -az --delete --exclude=/routine/ ~/code/pickandroll/data/ pickandroll@hts-digital-ocean:pickandroll/data/
   ```

4. Droplet: `~/pickandroll/ops/vm/install.sh --cutover` (`ROUTINE_FLAGS` empty: the digests
   and recorder comments post again, every league solved within the moves budget (§1; on
   2026-11-02 it still wrote `--skip-solve 31822`, emptied by hand after #306, §1), the timers
   on). It sets no mode: the copy carries the Mac's switches, and any change is the
   user's own click on the dashboard. A timer whose time the pull changed runs once as soon as
   it is enabled (`Persistent=true` counts the new time's last occurrence as missed): on
   2026-11-02 the morning unit, 07:45 to 09:15, ran at 08:15 and found nothing due before the
   09:00 execute time, as the routines' own gates make such a run harmless.
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
7. The user checks the leagues' switches on the dashboard: the copy carries the Mac's own (on
   2026-10-31: moves and lineups live in the nine public leagues, the private league off), so
   both executors run live from the droplet at once; the live guard passes on the copied
   dry-run days. The first live pass from the droplet is the 09:15 morning pass, the same
   Monday when the cut-over ends before it, else the 15:00 late pass.

The dashboard needs no move: the droplet's API serves it under `/app` on the tailnet already
(§2a), and a Mac-side `npm run dev` keeps working through the tunnel.

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
  When its check page did not load (the alert says "not a sign-out"), it is the site's outage,
  not the profile: nothing to sign in; the daily checks again.
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
