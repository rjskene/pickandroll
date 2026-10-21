# Draft day: the cash-league runbook (#67)

This is the runbook a scheduled Claude session follows for one Yahoo league's live draft. It is written for a fresh
session that has seen nothing else. A person running a draft by hand follows the same steps. The API side is
`scripts/draft_day.py`; the browser side is a few clicks in the user's own Chrome with the Claude in Chrome tools.

Paths are relative to the main checkout, `~/code/pickandroll`. Run the script with
`.venv/bin/python scripts/draft_day.py <command> <league>` from there.

## The drafts

| league | format | draft (PDT) | on this Mac (CDT) | scheduled task fires (PDT) |
|---|---|---|---|---|
| 238174 | H2H points | Sat 2026-10-17 11:00 | 13:00 | 10:30 (`draft-day-238174`) |
| 15953 | H2H points | Sun 2026-10-18 11:00 | 13:00 | 10:30 (`draft-day-15953`) |
| 208649 | H2H points | Sun 2026-10-18 14:00 | 16:00 | 13:30 (`draft-day-208649`) |
| 230585 | H2H categories | Mon 2026-10-19 18:00 | 20:00 | 17:30 (`draft-day-230585`) |

All four have 12 teams, 13 rounds and a 60-second pick clock. Each league's folder `data/leagues/<id>/` (local,
never committed) holds `settings.json` (scoring, roster, points weights or categories, draft time, the user's
Yahoo team id `my_team_id`), `yahoo_players.json` (Yahoo's public player list for the league), and
`armed.json` once the user has armed the draft.

## Rules for the session

- **Arm nothing.** The room comes up in autopilot only if the user armed the league in the dashboard
  (`armed.json`, their own click; CLAUDE.md, the 2026-10-16 exception). The script's attach names no mode, so the
  user's choice decides. A league the user did not arm runs in mirror, and Yahoo autopicks the user's turns. Never
  call `PATCH /rooms`, `PUT /leagues/<id>/arm` or the dashboard's arm buttons. Never click Yahoo's Draft button, its
  queue or its Autodraft switch. The scheduled task's prompt says "the runbook arms it". In this runbook, that arm
  is the user's pre-arm, nothing more.
- **Credentials.** Never type or handle credentials. If Yahoo shows a sign-in page, stop the browser steps and
  write that down (see "Report"). If Basketball Monster shows one, skip the export and keep the projections file
  on disk (see "Projections").
- **One client per seat.** Open the draft room in one tab of the user's Chrome only. Never open a second draft tab
  for the same league, and never connect to the draft socket any other way. Yahoo kicks the user's seat when a second
  client joins.
- **Servers.** Start dev servers only from `~/code/.claude/launch.json`: `pickandroll-api-draft`
  (:8000, no reload) and `pickandroll-web` or `pickandroll-web-tailnet` (:5173; since 2026-10-19 15:17 PDT both
  allow the tailnet host the user watches the dashboard from, which the plain entry rejected twice on 2026-10-18).
  Prefer `servers --start`, which detaches the process: a server started with `preview_start` is stopped by the
  app when its session goes idle, which took the web server down three times this weekend. No pulls, checkouts
  or `src/` edits while any room is live.
  Never restart the API while another league's room is live: on Sunday the 11:00 draft can still be running when the
  14:00 task fires.
- Do not use the superpowers plugin. Never commit anything under `data/`.

## Steps

### 1. Check the league

```
.venv/bin/python scripts/draft_day.py status <league> --accept-move
```

This prints Yahoo's public view of the league: teams joined, draft status and draft time. It also prints
whether the user armed it, and the newest projection file with its export time.

- `ALERT projections ...` means that file is more than two days old. The export below replaces it, ALERT or not.
  If Chrome is not signed in to Basketball Monster, the run goes ahead on the newest file, and the report says so.

- Exit 2, "Yahoo has no such league now": the league dissolved. Go to "Dissolved league".
- Exit 3, "the draft moved": the new time is six hours away or more, or already past. Go to "Draft moved".
- "Yahoo says the draft is over": go to "Report" and say so.
- A move of under six hours: `--accept-move` writes Yahoo's time into `settings.json`, and the run below waits
  for it.
- `adjustments.json: N games haircuts applied at attach (...)`: the user prepared haircuts for this league (see
  "News sweep and games haircuts"). An `ALERT adjustments.json` line names an entry the attach will skip; the
  attach goes ahead without it. Say so in the report.

Then export this morning's projections through the user's Chrome (see "Projections", "Export through the user's
Chrome") and import them:

```
.venv/bin/python scripts/draft_day.py projections
```

It prints the file it saved and the movers, or that the export equals the newest file. Do this before the news
sweep, which reads the projection file's time. Skip it, and say so in the report, only when Chrome is not signed in
to Basketball Monster or the export fails twice.

Then sweep the news and post the block on the league's issue (#67 for the cash leagues):

```
.venv/bin/python scripts/draft_day.py news <league>
gh issue comment 67 --repo rjskene/pickandroll --body-file data/draft_day/<league>/news_<stamp>.md
```

The command prints the file it saved. The block lists the injury news newer than the projection file for the
players the plan may take (see "News sweep and games haircuts"). The session posts it and changes nothing: a
haircut is the user's call. An `ALERT news` line means a page did not read; the block says which, and the sweep
still runs on the other. Exit 1 means neither page read: post that one line instead.

### 2. Servers and the run

Start both servers with `preview_start` and the names `pickandroll-api-draft` and `pickandroll-web-tailnet`. If they are
already up, they are reused. Then check them:

```
.venv/bin/python scripts/draft_day.py servers
```

- Exit 0 means both answer, and the API has the league endpoints (#67). It also lists any live rooms. A complete
  room the API still holds is listed apart, as not live: it does not stop a restart.
- Exit 4 with "predates #67" means the API on :8000 runs older code. Restart it on main only if `servers`
  listed no live room: `preview_stop` it if this session started it, otherwise stop that one process by its PID
  (`lsof -ti tcp:8000 -sTCP:LISTEN`), then `preview_start` it again.
- Exit 4 with "down": if `preview_start` is not available, `servers --start` starts the missing ones from the
  same launch.json entries.

Then start the API side in the background. The Bash tool's `run_in_background` re-invokes the session when it
exits:

```
.venv/bin/python scripts/draft_day.py run <league> --accept-move
```

`run` does the following in order:

1. Refreshes `yahoo_players.json` from Yahoo's public endpoint. A bad response keeps the file on disk.
2. Repeats the projections ALERT, if there is one. With `--bbm-fetch`, it first refreshes the projections
   headless (see "Projections"). That flag is off by default.
3. Refits the format's survival table from the season's earlier drafts and reports what the archive holds (see
   "Refit"). A failure prints `ALERT refit failed` and the tables on disk stand.
4. Waits for the draft tab (step 3) to report its seat. It waits until 15 minutes after the draft's start, and
   checks every 2 minutes that the league still exists.
5. Attaches the room with the league's settings and the newest `data/bbm_projections_*` file, and prints its
   name. A categories league with enough drafts in the archive asks for the league curve and says so.
6. Monitors the draft to the last pick, with the Mac kept awake (`caffeinate -dimsu`).
7. Saves the ledger and the snapshots and writes the comment for #67. A finished draft goes into its format's
   archive.

Its log is the background task's output, and `data/fidelity/draft_day_<league>.log` keeps a copy. The attach
prints the mode: `autopilot (the user's pre-arm)` or `mirror (not armed)`.

### 3. Open the draft room in the user's Chrome

Use the Claude in Chrome tools: load them in one ToolSearch call, then call `tabs_context_mcp` first.

1. If a tab is already on `https://basketball.fantasysports.yahoo.com/draftclient/nba/<league>/...`, that is the
   draft tab. Do not open another one; skip to item 5.
2. Open a new tab at `https://basketball.fantasysports.yahoo.com/nba`, the user's Yahoo NBA home. It lists the
   user's leagues. A sign-in page here means stop: see "Report".
3. Click the league whose link goes to `https://basketball.fantasysports.yahoo.com/nba/<league>`, or navigate to
   that URL.
4. On the league page, click **Enter Live Draft** (Yahoo also words it "Enter live league draft"; its link goes
   through `enterdraft` to the draft client). The draft client opens at
   `https://basketball.fantasysports.yahoo.com/draftclient/nba/<league>/<my_team_id>`, where `my_team_id` is in
   `settings.json`. If there is no button yet, the room is not open: wait two minutes and reload the league page.
   If the button opens a new tab, use that tab. **Never navigate to a typed draftclient URL.** The button's link
   carries an `?auth=` token; a tab opened at the bare URL can sit on "Connecting to draft server" indefinitely.
   On 2026-10-18 (league 224319) such a tab hung from T−29 to T+15, the run log said `seen, no seat yet` the whole
   time, and the user's first four picks went to Yahoo's autopick before the session re-entered through the button.
5. Leave the draft tab alone. Click nothing in it, do not navigate it, and do not reload it once the draft has
   started. Keep it open in its window until the run has finished. The extension (pickandroll 0.4.0) runs in that
   tab, and its timers run on a Worker, so the tab need not stay in front. Yahoo draws the order about 30 minutes
   before the start. The tab reports the seat once the order is known, and within seconds the run log says
   `attaching room <league>: seat N of 12`.
6. If after 5 minutes on the draftclient page the run log still says `waiting for the draft tab: not seen`, the
   extension is not running in the tab. Reload the draft tab once; before the draft starts that is safe.
   Two minutes after the client opens it must show the pre-draft board, or the draft board with the pick clock. If
   it still says "Connecting to draft server", close that tab and enter again through the league page's button;
   repeat until the client shows the board. After the draw, `seen, no seat yet` for more than a few minutes means
   the same thing: the client never connected. Re-enter through the button, do not wait for the start.
7. Close the other tabs this session opened (the NBA home and the league page) once the draft tab is in the room.

Open the draft tab well before the draw, not at the start. The scheduled task fires at T−30, before Yahoo draws
the order, which leaves the tab minutes in the room before pick 1. The 2026-10-16 points mock entered 30 s before
its start, and its G6 entry lead failed.

In mirror (a league the user did not arm), the extension clicks nothing. When a turn of the user's runs out, Yahoo
autopicks it and switches the seat to autodraft for inactivity. That is the expected autopick path, not a fault:
the scorecard counts it as a G5 autopick flip, so say why in the report. Leave autodraft as Yahoo set it.

### 4. While the draft runs

The run prints a line per pick, with the mode, the user's next pick and the tab's heartbeat age. It also prints
`the draft tab runs extension X.Y.Z` once. An extension older than 0.3.0 is an ALERT: the seat may be wrong in a
real league room (the team-id fix, #54). Write it in the report.

- `ALERT the draft tab has been quiet`: see "Quiet tab".
- `ALERT the room does not answer`: the API is down. Start it again (`preview_start pickandroll-api-draft`),
  then run `draft_day.py attach <league>`, which rebuilds the room from its log with the mode it had. Then run
  `draft_day.py monitor <league>` in the background, and `draft_day.py finish <league>` when it exits 0.
- A draft whose log already holds every pick is not rebuilt after a restart. The draft tab's calls get "no
  room" and the tab reads not attached. `attach` and `monitor` say it is complete, and `finish` replays it from
  its log to save it.

### 5. Report

When `run` exits 0, post its comment:

```
gh issue comment 67 --repo rjskene/pickandroll --body-file data/fidelity/<league>_<date>_session_<sid>/comment.md
```

`run` prints the exact path. The comment is the room's scorecard under one line: league, format, mode (armed by
the user or not) and picks taken. It has no team names; keep it that way.

For any other outcome, post a short comment on #67 that says what happened, with the exit code and the last
lines of the run log. Write the same lines to `data/fidelity/draft_day_<league>.log`. Then send fantasyMASTER a
one-line note if it is listed by `ListAgents`. End with a short written summary.

## When it goes wrong

### Dissolved league

Yahoo dissolves an under-filled public league at the order draw, about 30 minutes before the start. The members
are dropped, and the league page shows an error (115 and 152 were seen on 2026-10-12). `status` or the run
then exits 2. Confirm in Chrome:

- the league is gone from `https://basketball.fantasysports.yahoo.com/nba`, or
- its page shows the error.

Then post "League <id> dissolved at the draw; nothing was drafted" on #67 and stop. Leave `data/leagues/<id>/` as
it is.

### Draft moved

- Under six hours away: `--accept-move` handles it. The run waits for the new time, and the report says the
  draft moved.
- Six hours or more away, or on another day: post the new time on #67, tell fantasyMASTER (its scheduled task
  needs a new time), and stop. A session does not create or change scheduled tasks.

### Quiet tab (exit 6)

The draft tab has sent no heartbeat for 20 minutes. Look at Chrome with `tabs_context_mcp`:

- If the draft tab is gone, open exactly one new one through the league page's **Enter Live Draft** button (step 3),
  never at a typed draftclient URL. The old client is gone, so this is not a second client.
- If the tab is there but frozen, reload it once.

Then run `draft_day.py monitor <league>` in the background, and `draft_day.py finish <league>` when it ends.
Yahoo autopicks any of the user's turns that pass meanwhile, from the plan's queue when the extension had queued
it.

### No seat in time (exit 5)

No draft tab reported a seat by 15 minutes after the start. Check Chrome: is the tab on the draftclient page, is
the league still there, and does the tab show the board rather than "Connecting to draft server"? If it shows the
latter, close it and re-enter through the league page's button (step 3). Once the tab shows the room, run
`draft_day.py attach <league> --wait 600`. Then run `monitor` and `finish`.

### Yahoo finished first (exit 7)

Yahoo says the draft is over but the room is missing picks. The tab stopped syncing at some point. `finish` still
runs and saves what the room has. Report the gap.

### An earlier run's log (exit 8)

`data/fidelity/<league>.jsonl` was first attached six hours or more before this draft. It is an earlier run's log,
for example a rehearsal under the league's id. Rebuilt, it would bring back that run's session and mode. The
user's pre-arm is read only at a log's first attach, so the room would keep that run's mode, not the user's
pre-arm. `attach` and `run` stop before touching the API, and the message gives the `mv` that moves the log aside.
Run that `mv`. If `GET /rooms` lists the league's room, `DELETE /rooms/<league>` first. Then start `run` again in
the background. Say in the report that an earlier log was moved aside, and name the file.

## Refit (#77)

Each finished draft is evidence for the next one in its format. The archive is
`data/leagues/_shared/<points|categories>/` (local, never committed):

- `picks.csv`: every pick of every archived draft, in the history archive's shape. It records the season, the
  league, the draft date, the round, the overall pick, the seat, the Yahoo team, the Yahoo player id and name,
  and Yahoo's ADP and rank at draft time.
- `adp.csv`: Yahoo's ADP list at draft time for each draft, drafted or not.
- `survival_by_adp.csv` and `survival_by_adp.json`: the survival table, and the refit's report on it.

```
.venv/bin/python scripts/draft_day.py refit <league>                   # report the archive, rewrite the table
.venv/bin/python scripts/draft_day.py refit <league> --add-draft DIR   # archive a finished draft first
```

- **Archive.** `finish` archives the draft it just saved. Only a real draft goes in: one of a league with a
  folder under `data/leagues/`, whose ledger holds every pick. Mocks have no league folder. The ADP comes from
  the league's `yahoo_players.json`, refreshed at T−30, and a copy goes into the draft's folder in
  `data/fidelity/`. Archiving a draft again replaces its rows. An incomplete room says `not archived (...)`, and
  `finish` goes on.
- **Survival.** `refit` fits the table from the archived drafts of the league's size in both formats, then
  reports the drafts and the ADP rows the table answers for:

  ```
  archive _shared/points: 1 draft of 12 x 13 (238174 2026-10-17); categories: 1 draft at x0.5 (251146 2026-10-17)
    survival: wrote ..., answering ADP 90-N (at least 20 players within the bandwidth), blend: 1.5 drafts toward the ADP formula; the ADP formula elsewhere
    curve: league, from the rosters of 1.5 drafts, blended toward today's simulated run
  ```

  - **Pooling.** The league's own format counts at weight 1 and the other format at 0.5:
    `--cross-format-weight`, or `"refit": {"cross_format_weight": W}` in the league's `settings.json`. `D`, the
    drafts, is the sum of the weights.
  - **Blend.** The table is `D/(D+1)` of the drafts and `1/(D+1)` of the ADP formula, the ADP model the
    simulation drafts with, so the first draft already counts, at half. The undrafted share is `D/(D+1)` of the
    drafts'.
  - **Players per row.** A row carries the drafts only while at least 20 weighted players have an ADP within its
    bandwidth: `--min-count`, or `"refit": {"min_count": N}`. Past the last such row the ADP formula answers
    alone.

  Without a table (no draft of the size, or a first row already thin, as with half a draft from the other format
  alone), `refit` removes any old one and keeps the report with its reason. The league's sessions then simulate,
  and their survival note says why, for example `archive: no drafts of 12 x 13 yet`. `status` prints the reason,
  or the table's rows and its blend: `blend: 1.5 drafts (1 of the format, 1 of the other at x0.5)`.
- **Which table a session reads.** The league's own folder's table first, then this shared one if it covers
  the draft, then a simulation. The session's survival `source` names the file, its `availability_source` is
  `league`, and `survival.blend` carries the blend. The dashboard words the odds as "the league's drafts
  (blend: 1.5 drafts)".
- **Curve.** Once its format has a table, a league in either format asks for `curve: league`. The curve comes
  from both formats' rosters on the session's projections, at the same weights, blended toward today's simulated
  run by the same `D/(D+1)`. The session runs that simulation in the background for its curve alone and keeps
  the league table as its survival. The static curve (categories) or the flat one (points) stands in until the
  run lands, and the dashboard refreshes when it does. If the league curve cannot be fit at the attach, the run
  prints an ALERT and attaches with the simulated curve.
- **This weekend's order.** In points, 238174 (Saturday 11:00) is the archive's first draft, then 15953 and
  208649. In categories, 251146 (Saturday 20:00) starts the archive, then 252098, 31153, 224319 and 230585.
  Each draft is archived for the ones after it and counts from the first, the other format's at half weight.

## Projections (#75)

Every draft should run on that morning's Basketball Monster export. The user exports it by hand, or the session
exports it through the user's signed-in Chrome (below). Nothing in the project signs in to Basketball Monster.

```
.venv/bin/python scripts/draft_day.py projections                 # the newest Projections*.csv
.venv/bin/python scripts/draft_day.py projections --export FILE   # this file instead
```

- **Where it looks.** The newest `Projections*.csv` by file time, in `~/Downloads` or the checkout's root
  (`PICKANDROLL_DOWNLOADS` names another folder). The root's copy is gitignored.
- **What it saves.** It loads the export with the session's own loader, then copies it to
  `data/bbm_projections_<date>.csv`, dated by the export's file time. The copy keeps that time, which the session
  reads as the projections' `as_of`. A second export on the same day gets the time in its name as well. The
  attach takes the newest file by the date in its name.
- **What it refuses**, saying why and saving nothing:
  - a file that fails the schema;
  - a file with under 300 players who have games (a filtered page, or a cut-off download);
  - an export older than the newest saved file.
- **An identical export.** One equal to the newest saved file saves nothing either: Basketball Monster has not
  changed its projections. The newest file stands, and is dated at the new export's time, so it counts as this
  morning's.
- **The movers.** It lists the players whose games or value moved most since the previous file. Value here is
  nine-category total z over a 12-team, 13-round pool, and the lists come from the top 200 by value in either
  file. Each list holds up to eight names: games down, games up, value down, value up, new to the export, gone
  from it. Names and directions only, no numbers. A player listed for games is not listed again for value.
- **Staleness.** `status` prints the newest file and its export time. When the file is more than two days old,
  the line starts with `ALERT`, and `run` repeats it before the attach.

### Export through the user's Chrome

When the user's Chrome is signed in to Basketball Monster, the session exports with the Claude in Chrome tools, the
same way it opens the draft room. Done this way on 2026-10-19 at 10:26 PDT while the 258332 room was live in
another tab, which it never touched.

1. Open `https://basketballmonster.com/projections.aspx` in a new tab of the user's Chrome, never in a draft tab.
   The header must show the account menu with a Logout link inside it. A Login link or a sign-in page means the
   user is signed out: close the tab, keep the file on disk, say so in the report. Never type credentials.
2. Under Filters set the player select to **All Players** (the page opens on Only Top Players, too few for the
   import), and set **Stats Display Format** to **Total Stats** (the layout the loader reads; the page's default
   is per game). Projection Source stays Josh Projections. The page re-renders after the first select, so find
   the second one again before setting it. The page opens on its defaults every time; set both on every export.
3. Click **Refresh**, wait for the table, then **Export to CSV**. Chrome saves `~/Downloads/Projections.csv` (a
   later one gets ` (1)`, ` (2)`; `projections` takes the newest by file time).
4. Run `.venv/bin/python scripts/draft_day.py projections`, then close the tab.

The export holds over 500 players with games. The Excel button gives the `.xls` layout, which `projections` does
not read.

### The headless refresh (`--bbm-fetch`, off by default)

`scripts/bbm_fetch.py` drives Basketball Monster through its own browser profile, `data/bbm-profile`. The user
logs in to that profile once, in a headed window: `.venv/bin/python scripts/bbm_fetch.py --ros`.

- **What it does.** With `--bbm-fetch`, `run` downloads the projections page's export through that profile
  before the attach (T−30), and imports it as above. `projections --bbm-fetch` does the same by hand.
- **The fallback.** With no profile, a logged-out profile, or any failure, it prints an `ALERT --bbm-fetch` line
  and the newest file on disk stands. It never signs in on its own.
- **Not yet tested.** The flag stays off until the headed login has been done and tested against the live site.
  That export is the page's Excel file (`.xls`), the layout the session's other loader reads. It is not the CSV
  the user downloads.

## News sweep and games haircuts (#76)

Basketball Monster folds news into its projections within hours. The sweep covers the gap between this morning's
export and the draft, and the haircut is how the user acts on what it finds.

### The sweep

```
.venv/bin/python scripts/draft_day.py news <league>                  # read both pages now
.venv/bin/python scripts/draft_day.py news <league> --news-from DIR  # saved pages instead
```

- **What it reads.** Two public pages, without signing in: ESPN's NBA injuries page, through the JSON it is
  built from, and Rotowire's latest NBA headlines. `--news-from DIR` reads `espn_injuries.json` and
  `rotowire_news.html` from DIR instead.
- **Who it lists.** Every player among the top 200 by projected value on the league's own scoring (`--news-top N`
  for another count) whose news is newer than the projection file's export time. A Rotowire headline has a day,
  not a time, so one dated the export's day counts as newer.
- **What it prints.** A markdown block, newest first: name, status, date and source. ESPN's status carries the
  injury and the estimated return where ESPN gives them. There are no player stats: a headline that reads like a
  game line is printed as "game line (not shown)", and the block has no projection numbers or ranks. The block is
  also saved as `data/draft_day/<league>/news_<stamp>.md`.
- **Names.** Names are matched to the projections the way the room matches Yahoo's, through
  `data/aliases.json`. A name nothing matches is listed under the table, not dropped. If it is a projected player
  under another name, pin it there: the source's key (`espn:<id>`, `rotowire:<id>`) or the name, to the
  projection id.
- A headline is not a projection. The sweep suggests nothing; the user decides what, if anything, to cut.

### The haircut

A haircut scales one player's projected totals to the games he is now expected to play. Projections are per
game times games, so every counting stat, the makes and attempts, the minutes and the games are scaled together;
his per-game line and his percentages stay as projected. The z-scores are recomputed over the whole pool and the
plan solves again. The pick log is never touched.

Each entry names a player, by name or projection id, and either `games_out` (the games he misses) or
`games_fraction` (the share of his projected games he plays). "Out about four weeks" is about fifteen games out
(3.75 a week). `note` is optional free text.

- **Before the draft:** write `data/leagues/<id>/adjustments.json`, a list of entries. It is applied when the
  league's session is made, at the room's attach. `status` checks it against the newest projections. An entry
  that does not read or match is skipped with its reason, never stopping the attach, and the room view lists the
  skipped ones.

  ```json
  [
    {"player": "First Last", "games_out": 15, "note": "out 4 weeks"},
    {"player": "Other Name", "games_fraction": 0.8}
  ]
  ```

- **During the draft:** the board's **Out** column sets "out N weeks" on a row (N × 3.75 games, rounded). "—"
  clears it. The GP cell then shows the games left, and the room's Sync card lists the active haircuts, each with
  a **clear** button. The API call is `PATCH /sessions/<id>/adjustments` with
  `{"adjustments": [...], "replace": false}`. Each row sets or clears its player's haircut; a row of no games out,
  or a fraction of one, clears it. `replace: true` makes the rows the whole table. A session can also be created
  with `adjustments` in its body.
- **The record.** Each PATCH in a room writes an `adjustments` event to the room's ledger: the table, the names,
  the players changed and the board it was set on. A rebuild after an API restart drafts on the last table. The
  attach record names the haircuts the room started under. The session summary lists them, and the scorecard
  adds a "Games haircuts" line naming the turns of mine that were solved under one.

## Before the user leaves (the user's checklist)

These are the user's own steps.

- **Stay signed in to Basketball Monster in Chrome.** The session exports this morning's projections itself at
  T−30 through that sign-in (see "Projections", "Export through the user's Chrome"). To do it by hand instead: on
  basketballmonster.com, Member, Projections 26-27, All Players, Total Stats, Export to CSV, then
  `.venv/bin/python scripts/draft_day.py projections` in `~/code/pickandroll`. It prints the file it saved and
  the movers. A refusal says why (see "Projections").
- **Optional: haircuts from the news.** Run `.venv/bin/python scripts/draft_day.py news <league>` and read the
  block. Where the news is clear (out for weeks), add the player to `data/leagues/<id>/adjustments.json` (see
  "News sweep and games haircuts"). The scheduled session posts the sweep again at T−30, but it never writes
  haircuts.
- **Arm each league you want drafted for you.** On the dashboard's landing page (http://localhost:5173), each
  league whose draft is ahead has a card under **Drafts ahead** (the draft-season layout, which the Layout
  control's auto shows while a draft is less than fourteen days away; in season, the **Drafts** button opens
  the same cards in a drawer). Click **Arm draft**, then **Confirm: arm <id>**. Disarm the same way. A
  finished draft has no card and no Arm.
  - The arm is read once, at the first attach, so arm before the scheduled task fires (T−30).
  - After the attach, the room's Sync card arms or disarms the live room.
  - An unarmed league mirrors, and Yahoo autopicks your turns.
- Chrome is open and **signed in to Yahoo, with a Yahoo tab left open in a window**. On 2026-10-17 the T-30 run
  found Chrome with no windows and Yahoo signed out, and the draft went to Yahoo's autopick: a session cannot sign
  in for you. Sign in on the Mac before you leave, and a sign-in check about 90 minutes before each draft (run by
  fantasyMASTER) pushes a notification to your phone if Yahoo is signed out. The pickandroll extension shows 0.4.0
  at `chrome://extensions`; if it shows an older version, load `~/code/pickandroll/extension` and reload it.
- **Remote unlock works only if Screen Sharing was switched on from System Settings** (General > Sharing)
  while someone was at the Mac. Loading the daemon with `launchctl` over SSH starts a sharing agent without the
  Screen Recording and Accessibility grants, so a viewer sees a black screen and its keystrokes are dropped; nothing
  from a shell, kickstart or MDM can add those grants. A locked Mac then cannot be unlocked remotely, and a session
  never types the Mac password or signs in to Yahoo for you. On 2026-10-18 the Sunday points drafts went to Yahoo's
  autopick this way. Before leaving: Screen Sharing on from System Settings, and the lock off
  (`sysadminctl -screenLock off -password -`, set 2026-10-18) or the Mac kept awake so it never locks.
- The Claude desktop app is open: scheduled tasks fire only while it runs. The Mac is plugged in and awake at
  each T−30. The run keeps it awake from then on, but cannot wake a sleeping Mac. To keep it awake until Monday
  night, run `caffeinate -ims -t 320000` in a terminal (about 89 hours).
- Do not open a draft room in the Yahoo app on your phone while the Mac's tab is in it: that is a second client,
  and Yahoo kicks one of them. Follow the draft on the dashboard instead (next section).

## Following the draft from a phone (tailnet)

The dashboard is the web app on :5173. It calls the API through Vite's proxy at the relative path `/api`, so
the page's own origin is the API base, and only :5173 has to reach the phone. The API stays on 127.0.0.1. A
config value, `VITE_PICKANDROLL_API_BASE` at build time, points the app at an API elsewhere. An API called
directly that way admits the extra origins in `PICKANDROLL_CORS_ORIGINS`, an exact comma-separated list.

On the Mac (Tailscale is installed; it was stopped on 2026-10-16):

1. Connect Tailscale from its menu bar icon, with the phone on the same tailnet.
2. **Tailscale Serve (recommended).** The Mac keeps `localhost`, and only the tailnet sees the dashboard, over
   HTTPS:
   - Run `tailscale serve --bg 5173` in a terminal. The first time, it links to the admin console to turn on
     HTTPS certificates.
   - Vite checks the Host header, so the web server must allow the tailnet's names. Add this launch.json entry
     (the user or fantasyMASTER adds it; sessions do not edit launch.json; `<home>` is the absolute home folder,
     as in the other entries) and start it instead of `pickandroll-web`:

     ```json
     {
       "name": "pickandroll-web-tailnet",
       "runtimeExecutable": "/usr/bin/env",
       "runtimeArgs": ["PICKANDROLL_WEB_ALLOWED_HOSTS=.ts.net", "npm", "run", "dev", "--prefix",
                       "<home>/code/pickandroll/web", "--", "--host", "127.0.0.1"],
       "port": 5173
     }
     ```

   - The phone opens `https://<mac-name>.<tailnet>.ts.net/`. `tailscale serve status` prints the address.
3. **Without Serve.** Bind Vite to the Mac's tailnet address. Use a launch entry like the one above with
   `--host <tailnet IPv4>` (`tailscale ip -4`), or set `PICKANDROLL_WEB_HOST` with no `--host`. The phone then
   opens `http://<tailnet IPv4>:5173/`. Vite admits a bare IP without `allowedHosts`. On the Mac the dashboard is
   then at that address too, not `localhost`. Avoid `--host 0.0.0.0`, which also opens the dashboard to the local
   network.

What the phone shows (#74):

- **The landing page.** In draft season (#108) it leads with the drafts ahead, then the live drafts, one card
  per attached room: the league, your seat, the room's mode and your pre-arm, the picks made, your next pick,
  the clock, and **Open draft**. With no room it names the next league draft. The leagues in season follow as
  chips, and the New draft form sits beside them (below on a phone). When exactly one room is live, the page
  opens straight into its draft; **switch draft** comes back.
- **The draft's top bar.** Beside the time since the last pick, it counts the picks to your turn: "7 picks to
  your turn", "you're next", then "your pick" with the pick clock's time left in the warning colour, or "your
  pick, then again" when your next pick follows at once.
- **The log card (6).** The picks are listed in draft order, the earliest at the top. The list stays where you
  scrolled while picks come in and follows them only while it shows the latest; **Latest** jumps back there.
- **The start form's League chooser.** A draft started by hand for a league takes what the runbook's attach
  takes: the teams, roster and scoring from its folder, ADP and positions from its `yahoo_players.json`, the
  survival its folder and format resolve to, and the league curve once the format's table has rosters. The form
  shows each before the start (`GET /leagues` carries them as `resolved`). When the league curve cannot be fit,
  the draft is made on the simulated curve and the form says why, as the attach does.

The dashboard has no sign-in. Anyone who reaches it can arm or disarm a room, which is why it is kept to the
tailnet.

## What a cloud VM would take (not this weekend)

The sync side cannot leave the Mac: the draft room has to run in the user's own signed-in Chrome, where the
extension reads the seat. A VM could host only the API and the dashboard. That needs:

- The extension's `host_permissions` and API base pointed at the VM, over HTTPS on the tailnet.
- An API with authentication. Today anyone who reaches it can arm a room.
- `data/` on the VM: projections, league folders and survival tables. That is subscriber data, which must stay
  private and off git.
- Enough CPU for the solver's process pool.
- The round trip inside the sync budget: G2 lag p95 under 2 s, measured today on localhost at under 100 ms.

The Mac and its browser stay in the loop either way.
