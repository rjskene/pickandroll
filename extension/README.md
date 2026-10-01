# pickandroll draft-room extension (Chrome, MV3)

Mirrors your Yahoo fantasy basketball draft room into a pickandroll session running on this computer. Every pick
in the room reaches the session within a second or two, and pickandroll's plan for your next pick shows in the
draft page and in a side panel. This build only mirrors: it never clicks anything in Yahoo. Drafting for you
("armed") comes in the next build, and only you can arm it.

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
   seat**.
2. Enter the Yahoo draft room as usual. The extension starts on any
   `https://basketball.fantasysports.yahoo.com/draftclient/...` page and shows a strip at the bottom left.
3. Open the side panel (toolbar icon), choose the session and click **Attach**. The strip then shows the sync
   state ("synced 57/57" or "behind 2"), your next pick and the plan's top three with its freshness.
4. Draft in Yahoo as usual; pickandroll follows every pick.

The strip, by state:

| strip says | meaning |
|---|---|
| `synced n/n` | the session has every pick the room has |
| `behind k`, `waiting for #j` | picks still on their way, or one is missing; it resends on its own |
| `not attached` | open the side panel and attach a session |
| `API not reachable` | start `pickandroll-api`; picks are kept and sent when it is back |
| `YAHOO AUTOPICK ON` | Yahoo's Autodraft switch is on: Yahoo picks for this seat |
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
| `worker.js` | service worker: the only caller of the API; per-tab state for the panel in `chrome.storage.session` |
| `sidepanel/` | side panel: room state, attach a session, mode, plan, detach |
| `options/` | API and web app addresses (localhost only), Yahoo players file |
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
- `http://localhost:8765/extension/test/harness/panel.html?draft=<room id>`: the side panel, unchanged, against a
  room in the API.
