# pickandroll draft-room extension (Chrome, MV3)

Mirrors your Yahoo fantasy basketball draft room into a pickandroll session running on this computer. Every pick
in the room reaches the session within a second or two, and pickandroll's plan for your next pick shows in the
draft page and in a side panel. By default it only mirrors and never clicks anything in Yahoo. When you arm a
room from the side panel, it drafts pickandroll's pick on each of your turns. Only you can arm it, and a pick
you make by hand always wins.

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
   including the one fetched ahead of the turn;
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

## What it reads and sends

- **Reads:** the text frames of the draft room's own WebSocket. The page script adds a listener to the socket
  Yahoo opens. It never opens a socket of its own and never sends on Yahoo's, so your seat has one reader, your
  own draft tab. From the client's hello frame it keeps only the slot number. It also reads whether Yahoo's
  Autodraft switch is on, and notices clicks you make on Draft buttons during your turn, to label your picks.
- **Sends:** the draft id, your seat, each pick (overall, Yahoo player id, team, arrival time), when each pick
  goes on the clock, and the fidelity events of `docs/YAHOO_SYNC.md` §4. Only to the pickandroll API on
  `localhost`/`127.0.0.1`, and only from the service worker; the Yahoo page itself never calls localhost.
- **Never:** cookies, the `?auth=` part of the room URL, anything you type, or any page other than the draft
  client.

## Files

| file | role |
|---|---|
| `manifest.json` | MV3 manifest: content scripts on the draft client only, host permission for localhost only |
| `page.js` | page world, `document_start`: watches Yahoo's socket; hosts the timer worker (hidden tabs throttle timers) |
| `content.js` | isolated world: the room tracker, picks and events to the worker, the in-page strip |
| `lib/protocol.js` | the room's frame format and snake-draft arithmetic (pure) |
| `lib/room.js` | `RoomTracker`: picks, the pick on the clock, the sync cursor, how my picks landed (pure) |
| `lib/drafter.js` | armed mode: one turn at a time, a newer turn supersedes an older one, the queue backstop and the probe (pure, through a page adapter) |
| `lib/yahoo.js` | Yahoo's player table: row matching by headshot id and name, label checks, the plan's candidates (pure) |
| `worker.js` | service worker: the only caller of the API; per-tab state for the panel in `chrome.storage.session` |
| `sidepanel/` | side panel: room state, attach a session, mode, plan, detach |
| `options/` | API and web app addresses (localhost only), Yahoo players file, the queue probe's round, the search fallback |
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
  room in the API.
