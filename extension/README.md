# pickandroll draft-room extension (Chrome, MV3)

Mirrors your Yahoo fantasy basketball draft room into a pickandroll session running on this computer. Every pick
in the room reaches the session within a second or two, and pickandroll's plan for your next pick shows in the
draft page and in a side panel. By default it only mirrors and never clicks anything in Yahoo. When you arm a
room from the side panel, it drafts pickandroll's pick on each of your turns. Only you can arm it, and a pick
you make by hand always wins. From 0.5.0 it also reads your league's own pages during the season, for the
season view (below): that is how a private league such as 31822 reaches pickandroll.

Spec and metrics: `docs/YAHOO_SYNC.md`. API side: the `/rooms/{draft_id}` routes (`docs/DESIGN.md`).

## Install (once, by you)

1. Start the pickandroll API (and the web app if you want the board) from `~/code/.claude/launch.json`:
   `pickandroll-api` on :8000, `pickandroll-web` on :5173.
2. In Chrome open `chrome://extensions`, turn on **Developer mode** (top right), click **Load unpacked** and pick
   this `extension/` folder.
3. Pin "pickandroll draft room" to the toolbar. Its icon opens the side panel.

After the extension's files change, click the reload arrow on its card in `chrome://extensions`, then reload any
open draft tab. Content scripts only start when a page loads.

## Use it in a draft

1. In the pickandroll web app create the session for the draft, with **your draft position equal to your Yahoo
   seat** and **the room's number of teams** (count the filled seats; a mock room can have fewer than 12).
2. Enter the Yahoo draft room as usual. The extension starts on any
   `https://basketball.fantasysports.yahoo.com/draftclient/...` page and shows a strip at the bottom left.
3. Open the side panel (toolbar icon), choose the session and click **Attach**. The strip then shows the sync
   state ("synced 57/57" or "behind 2"), your next pick and the plan's top three with its freshness.
4. Draft in Yahoo as usual; pickandroll follows every pick.

The extension works out the room's team count from where the snake turns (pick T+1 goes back to seat T). An
attach that disagrees with a count it already knows is refused. A disagreement found later turns the room to
mirror, and it cannot be armed again: plans for a 12-team draft are wrong in a 10-team room.

## Armed mode (opt-in)

Click **Armed** under Mode in the side panel and confirm. On each of your turns the drafter then:

1. waits for pickandroll's plan for this exact board, the board after the pick before yours. If the API does not
   answer (restarting, an error), it keeps asking until the wait is up, then acts on the newest plan it holds,
   including the one fetched ahead of the turn. The wait lasts up to 20 s, or the room's pick clock less 20 s
   when that is longer (40 s in a 60 s room), and always ends with 12 s left;
2. clicks the Draft button on the plan's first available player's row, checking that the row's label names that
   player. A row out of view is scrolled to. Yahoo's search box is used only when the search fallback is on, on
   the options page; it is off by default because in the September drafts the filtered table's Draft button
   drafted the wrong player;
3. re-clicks if a re-render swallowed the click, and falls through to the next candidate;
4. near the deadline only, falls back to Yahoo's own queue and Autodraft:
   - it queues this pick's player and switches Autodraft on;
   - when your next pick follows straight on (seats 1 and 12), it queues the plan's player for that pick too.

Autodraft is switched off again after every turn. The drafter's own switch is not Yahoo taking the seat: the room
stays armed, and a back-to-back turn still starts. A switch you turn on yourself is yours, and so is its queue;
the drafter leaves both alone between turns. A queue entry is removed only through a control labelled remove or
queue; when an entry has none, it is left and a note names its controls.

- **Your pick wins.** A Draft click of yours during your turn makes the pick yours, and the drafter stops at once.
- **Hand pick next**, in the page strip, skips the drafter for your next turn. Click it again to cancel.
- **Mirror** in the side panel disarms the room.
- **The queue probe.** Once per armed draft, by default on your first turn from round 3 whose next pick is not
  also yours, the drafter stars its top candidate before drafting it. It logs what Yahoo did: queued, drafted,
  dropped (a lost click on a Draft control) or failed. Both real outcomes take the player wanted. It also logs
  every control in the row (cell, place, labels) and whether the queue panel was found. Set the round, or `off`,
  on the options page.

The strip, by state:

| strip says | meaning |
|---|---|
| `synced n/n` | the session has every pick the room has |
| `behind k`, `waiting for #j` | picks still on their way, or one is missing; it resends on its own |
| `not attached` | open the side panel and attach a session |
| `API not reachable` | start `pickandroll-api`; picks are kept and sent when it is back |
| `YAHOO AUTOPICK ON` | Yahoo's Autodraft switch is on: Yahoo picks for this seat |
| `this room has N teams but the session M` | the session is for another draft: attach one with the room's team count |
| `the extension was reloaded` | reload the draft tab (only after a reload of the extension itself) |

Reloading the draft tab is the last resort in a live draft: the room resends its whole history on connect, so
nothing is lost, but the seat is away for a few seconds.

## League pages: the season view (0.5.0, #98)

A league whose pages answer only when you are signed in (31822 is private) cannot be refreshed by the API. Its
season view is fed from the pages you open in Chrome instead:

1. pickandroll needs the league's folder, `data/leagues/<id>/settings.json` with `"public": false` and your
   team id.
2. Open any of the league's own pages: the league page, a team's page, the players page, the matchup, the
   transactions or the draft results (0.5.2, #97: the weekly recorder reads the picks once), a team's page
   for a day or the settings page (0.5.3, #107: the lineup view)
   (`https://basketball.fantasysports.yahoo.com/nba/<id>/...`). A moment after the page loads,
   the extension posts it to pickandroll (`POST /seasons/<id>/snapshot`) and the API reads it. A public league's
   pages post the same way.
3. The side panel on such a tab shows the page, the season it fed (week, snapshot age), the last post of each
   page with what the API took from it or why it refused it, **Refresh this page** (reloads the tab) and a link
   to the league in the web app.
4. On the players page, **Read every page** opens the first page of the same view and follows its Next 25 link
   page by page, up to 12 pages (300 players). It then does the same in the Next 7 Days (proj) view, Yahoo's own
   weekly projections (0.5.1, #93), unless it started there, and stops. **Stop reading** ends it. Without that
   click the reader never navigates.
5. Yahoo's projections reach pickandroll only from that view: open Next 7 Days (proj) on the players page too,
   or let the read walk it. Its pages keep their own lines in the panel ("players 1-25 (next 7 days)").

After the first post of a private league the API also brings in the week calendar (from the cache any public
league's refresh writes) and the NBA schedule, so games left show on the roster. A team's page for a day
(`?date=`, 0.5.3) is posted as that day's lineup, kept apart from today's roster: the lineup view compares it
with the recommended lineup. The settings page gives the held slots (IL, IL+, NA) and when lineup changes
count; until it is posted the held slots are the most any roster read holds. The weekly recorder's response
and the season script list the pages still to open (`lineup pages`).

## The lineup executor's dry run (0.6.0, #170)

On your own team page the extension is also the lineup executor (docs/AUTOPILOT.md section 2). This build is its
dry run: it reads the page's lineup form and logs what it would set, and it sets nothing and submits nothing.

1. A run starts only when the page was opened from the routine's link, with the fragment `#pickandroll-lineup`
   (or `#pickandroll-lineup-late`, the pass before the day's first tip-off), or from the side panel's
   **Set lineup now**. The fragment never reaches Yahoo, and the run drops it so a reload is a plain visit. A
   plain visit posts the page as before and shows the strip, a small line at the foot of the page saying what a
   run would do.
2. A run posts the page, then fetches the day's steps (`GET /seasons/<id>/lineup/steps?date=`). It goes on only
   when the steps were built from that very post (their `read.at` is the post's time) and the page's lineup is
   the one they read. The page must be the league's team page for your team, with its own editable lineup form
   for the steps' day.
3. Each step is checked on the form: the player is on the page in the step's slot, with a select (a hidden field
   means his game began), the target slot is among his options, and the player swapped back may take the step's
   slot, or the target is open. A group whose step fails is skipped whole, with that step's reason.
4. The run goes to the league's log (`POST /seasons/<id>/autopilot/lineup`) with the form's action, its field
   names (never a value, never the crumb's), each moved player's control and the select values it would set.
   The strip and the side panel show the outcome.
5. Nothing runs in a league whose mode is off (the dashboard's Lineup view sets it), under the API's STOP file
   (a run logs that it stopped), or with **Lineup executor in this browser** off in the settings, this browser's
   brake.

The live click, the form's submit, is a later build after the dry-run week (#170, PR 3).

## The moves executor (0.7.0 dry run, 0.8.0 live claim, #171; 0.8.1 open spots, #199; 0.8.2 Yahoo's claim step)

On Yahoo's add page (`/nba/<id>/addplayer?apid=<player>`) the extension is also the moves executor's execute
pass (docs/AUTOPILOT.md section 2). In a dry run, on the add page of a queued move that is due, it reads the
rendered claim form and logs the claim it would place: it toggles no drop, sets no bid and submits nothing. It
fetches nothing from Yahoo and posts nothing about the add page but the pass. In a league switched live whose
guard holds, the same checks place the claim (below).

1. The routine opens each due entry's add page itself, in a tab of its own, with the fragment
   `#pickandroll-moves` (or `#pickandroll-moves-late` for a late pass). The side panel's **Check moves now** lists
   the league's due entries as links to their add pages with `#pickandroll-moves-panel`; you open them, nothing is
   opened for you. A plain visit to an add page runs no pass, and a reload of one is a plain visit: the fragment is
   dropped first.
2. A pass fetches the league's due entries (`GET /seasons/<id>/autopilot/moves/due`) and takes the one whose add
   is the page's. None: nothing is logged and the strip says so. Nothing is due in a league whose mode is off, in
   the private league or under STOP; under STOP the pass is logged as stopped.
3. The entry is checked against the queue: struck, a protected drop, a claim on the add still pending, the day's
   cap and the week's adds.
4. Then against the page: the claim form (`form#add-drop-players-form`) posts to this league's and my team's
   `/nba/<id>/<team>/addplayer` and carries `stage` and `apid`, naming the add; the heading is Yahoo's claim
   heading and the waiver date the queue's clear date; the drop is one checkbox in my roster's table with no
   can't-cut or locked icon; the add's row has no "no more roster moves" icon; the bid is a whole dollar inside
   the page's range and the budget; the claim submit is there. A failed check skips the entry with its reason
   (the heading's own text, or the drop's id and the icon found). The add is `gone` only when the page shows it on
   a team; a page with no claim form is skipped as not read, so the late pass tries again. An entry with no drop
   (0.8.1, #199) is read by the page's drop section instead: none shown (no drop-table row, no `dpid` box) is an
   open spot, logged as the claim it would place with no drop ("open spot", `dpid` null); one shown means the
   roster is full and the entry skips with the count ("the roster is full: <id> to IL first …" for an add waiting
   on an IL move). Never a fallback drop.
5. The pass goes to the league's log (`POST /seasons/<id>/autopilot/moves`) as a dry run: the outcome and reason,
   the form's action and field names (never a value, and never the anti-forgery field's), `token` (whether the
   form has that field), the heading, the waiver date, the budget, the range, the adds left, my roster's
   can't-cut ids, the add's row icons, when the page was read, and the fields the claim would fill (`apid`,
   `dpid`, `faab` and the submit's name). The waiver-order table is never read. A dry run sets no outcome on the queue. The strip and the side panel show
   the pass. **Moves executor in this browser** off in the settings is this browser's brake.

### The live claim (0.8.0, #171 PR 3; Yahoo's claim step 0.8.2)

`due` carries `live: {ok, reason}`, the live guard now. A pass runs live only when the league's mode is `live` and
`live.ok`; a live league whose guard refuses runs a dry run whose reason says "live refused: …". In live, a claim
that passes every check above is placed, on a page opened with a moves fragment only:

1. It is put on record first (the worker's `moves_submit:<entry>` in `chrome.storage.local`, kept across a
   restart): while it is there no pass submits that entry again, whatever the tab. Claims on record count as
   placed in the league's other pages (the day's cap, the pending claims, their week's adds), and the worker
   takes one record at a time, refusing one past the cap or on an add already in flight.
2. It clicks what a user clicks, twice and nothing else (0.8.2; 0.8.0 and 0.8.1 clicked the hidden `dpid` box,
   which Yahoo's script never hears, so the first live pass placed nothing):
   - the one `button.add-drop-trigger-btn` whose `data-check-box-value`, trimmed, is the drop. Yahoo's own script
     then ticks the box, posts the form's first stage and swaps its reply in, the final button with it; the
     extension fetches nothing itself;
   - after up to 15 s for that reply (the final button in `#add-drop-submit-container`, the container no longer
     `Hidden-submit`, the drop in the form's one `dpid` field, the hidden one the reply leaves in place of the boxes; a
     reply short of any is a skip naming what is missing), it types the
     whole-dollar bid into `faab`, checked first as Yahoo checks it (a whole number from $0 to the field's
     `data-faab-balance`), reads the form back (one `dpid` field and it is the drop, stage 3, `apid` the add, the bid
     as typed, the final button by its identity: still the one Yahoo drew, `#submit-add-drop-button`, shown and named
     `submit_add_player`) and clicks the final button once. The markers are a hand tick's read (2026-10-26).
   The form posts as Yahoo's script sends it; the anti-forgery field travels in the browser's own submission and is
   never read. A skip after the first click leaves the page as it is (no Cancel click). On an add page opened with
   a moves fragment, `addpage.js` (the page's own world, `document_start`) keeps Yahoo's alerts as text on the root
   element instead of letting them block the tab: an alert on the reply logs the entry `failed` in Yahoo's words, one
   on the final click a skip, and the final button is never clicked after one. A page opened by hand keeps Yahoo's
   alerts.
3. The page Yahoo lands on, any page of the league in the same tab within two minutes, is read: its words saying
   the claim went in, or the add shown with "pending", log `claimed` with Yahoo's message; an error, or the claim
   form back with a message, logs `failed` with it (never retried that day). Anything else, a confirm step
   included, logs `claimed` with "Yahoo's answer was not read: check the pending claims", so it counts against the
   cap and the adds and is never submitted again; the extension never clicks a second time.
4. A submit whose answer was never read (the tab closed, a page the reader missed) is logged the same way by the
   next pass in the league, before anything else. The record is dropped only once the API has the pass.

Held back in live: free-agent adds (the "Add Player" page) and open-spot claims. Since 0.8.1 an open spot is read
in live as in a dry run but never submitted ("open spot, read only: …"); nothing on the page is touched until
Yahoo's open-spot page has been seen. A live skip stays due,
so the late pass reads the page again. The panel's links read "claim: …" in a live league whose guard holds:
opening one places the claim. An entry with no drop reads "open spot" and never "claim". The first live claim is the user's own switch on the dashboard.

## What it reads and sends

- **Reads:** the text frames of the draft room's own WebSocket. The page script adds a listener to the socket
  Yahoo opens. It never opens a socket of its own and never sends on Yahoo's, so your seat has one reader, your
  own draft tab. From the client's hello frame it keeps only the slot number. It also reads whether Yahoo's
  Autodraft switch is on, and notices clicks you make on Draft buttons during your turn, to label your picks.
- **Sends:** the draft id, your seat, each pick (overall, Yahoo player id, team, arrival time), when each pick
  goes on the clock, and the fidelity events of `docs/YAHOO_SYNC.md` §4. Only to the pickandroll API on
  `localhost`/`127.0.0.1`, and only from the service worker; the Yahoo page itself never calls localhost.
- **League pages (0.5.0):** the page as Chrome rendered it, less its scripts, styles, frames and form fields, with its URL
  and the time it was read, to the same API through the service worker. Only the league's own pages under
  `/nba/<id>/` (above); never the draft client, and nothing on them is clicked but the live claim below.
- **Lineup executor (0.6.0):** on your team page, the lineup form's action, field names, players' slots and
  options, and the run's outcome, to the same API. The form's crumb is never read; no field is set and the form
  is never submitted.
- **Moves executor (0.7.0, live 0.8.0, open spots read 0.8.1, claim step 0.8.2):** on an add page opened from the routine's or the panel's link, the claim form's
  action and field names, what the page shows (the heading, the budget, the waiver date, the bid range, my
  roster's player ids and their icons) and the pass's outcome, to the same API. Nothing is fetched from Yahoo;
  the form's crumb is never read (the log's `token` says only whether it is there). In a dry run nothing is
  toggled, set or submitted; a live claim clicks its one drop button, types its bid and clicks Yahoo's final
  button, and the page Yahoo lands on sends its path, heading and Yahoo's message about the claim. On such a page
  Yahoo's alerts are kept as text and logged with the pass.
- **Never:** cookies, the `?auth=` part of the room URL, anything you type, or any page other than the draft
  client and the league pages above.

## Files

| file | role |
|---|---|
| `manifest.json` | MV3 manifest: content scripts on the draft client and the league pages, host permission for localhost only |
| `page.js` | page world, `document_start`: watches Yahoo's socket; hosts the timer worker (hidden tabs throttle timers) |
| `content.js` | isolated world: the room tracker, picks and events to the worker, the in-page strip |
| `lib/protocol.js` | the room's frame format and snake-draft arithmetic (pure) |
| `lib/room.js` | `RoomTracker`: picks, the pick on the clock, the sync cursor, how my picks landed (pure) |
| `lib/drafter.js` | armed mode: one turn at a time, a newer turn supersedes an older one, the queue backstop and the probe (pure, through a page adapter) |
| `lib/yahoo.js` | Yahoo's player table: row matching by headshot id and name, label checks, the plan's candidates (pure) |
| `addpage.js` | page world, `document_start`, league pages: on an add page opened with a moves fragment only, keeps Yahoo's alerts as text on the root element (0.8.2) |
| `league.js` | isolated world, league pages: posts the page to the worker, follows Next 25 only during an armed read; on my team page, the lineup executor's dry run; on an add page opened with the fragment, the moves executor's pass (dry run, or the live claim); their strips |
| `lib/league.js` | which league pages are read, the snapshot body, the multi-page read (pure) |
| `lib/lineup.js` | the lineup executor's page side: the form read, the steps' checks, the run for the log, the strip (pure) |
| `lib/moves.js` | the moves executor's page side: the add page read, the entries' checks, the pass for the log, the strip (pure) |
| `worker.js` | service worker: the only caller of the API; per-tab state for the panel in `chrome.storage.session` |
| `sidepanel/` | side panel: room state, attach a session, mode, plan, detach; on a league page, its posts and the read; on my team page, the lineup executor's last run and **Set lineup now**, the moves executor's last pass and **Check moves now** (the due entries' add pages as links) |
| `options/` | API and web app addresses (localhost only), Yahoo players file, the queue probe's round, the search fallback, the lineup and moves executors' brakes |
| `test/*.test.js` | unit tests (`node --test extension/test/*.test.js` from the repo root) |
| `test/harness/` | Tier 1 for the extension: a recorded room played through the real scripts against the API |

## Tests

```bash
node --test extension/test/*.test.js
```

The harness runs in the Claude browser pane or any browser. Start `pickandroll-api` and `pickandroll-ext-harness`
(launch.json; the latter serves this worktree on :8765), then open:

- `http://localhost:8765/extension/test/harness/index.html?speed=10`: plays room 2515267 at ten times its pace
  through `page.js` → `content.js` → `worker.js` (a stand-in replaces `chrome.*`), then prints the room's
  scorecard. `flip=1` also flips a stand-in Autodraft switch at pick 30 (G5 must read 1). Results are in
  `window.__harness`.
- Armed runs add `armed=1`: a stand-in player table with Draft buttons, where a click on your turn is the room's
  pick 300 ms later.
  - `drop=0.3` loses that share of first clicks.
  - `slot=N` and `fixture=2515267|2565888` choose the seat and the recorded room.
  - `lead=60` sets the seconds from the attach to pick 1.
  - `gap=15` plays one pick every 15 s of wall clock in place of the recorded pace.
  - `teams=10` creates and attaches the session for 10 teams while the recorded room keeps 12. The tracker
    then reports the room's count, and the API turns the room to mirror at pick 13 (#17).
  - `api=` and `draft=` set the API base and the room id.
- `http://localhost:8765/extension/test/harness/panel.html?draft=<room id>`: the side panel, unchanged, against a
  room in the API. `?league=<id>&page=players` shows it on that league's page instead (`page` is the path under
  the league; a Refresh or a read is recorded in `window.__store.tabs`, not done).
