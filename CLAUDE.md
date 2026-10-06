# pickandroll: working agreement for Claude sessions

Fantasy basketball draft optimizer for 9-category head-to-head leagues (the user's Yahoo league is 31822,
12 teams, 13 rounds, 30 s pick clock). Read `README.md`, `docs/DESIGN.md` and `docs/ROADMAP.md` first.

Current programme: **YAHOO SYNC**, tracker #11, built as #8 (API room endpoints) → #9 (Chrome extension)
and #10 (web UI). The metric, guardrails, event schema and hill-climb protocol are in `docs/YAHOO_SYNC.md`;
the proven scratch code to port is described in its §0 (archive at
`~/code/pickandroll-scratch/live-drafts-2026-09-27/`, outside the repo).
Next programme: **KEEPERS** (`docs/KEEPERS.md`, 2026-10-06): keeper-league support before the real draft on 2026-10-14.

## Roles

Three Claude Desktop sessions share this checkout and reach each other with `ListAgents` / `SendMessage`.

| session | does | does not |
|---|---|---|
| **fantasyMASTER** | analysis, plans, metrics, spot checks, reviews and merges PRs, answers design questions | implement |
| **fantasyEMISSARY** | implements, tests, hill-climbs `docs/YAHOO_SYNC.md`; owns #8, #9, #10; directs the drone | merge its own PRs |
| **fantasyMOCK** (the drone) | runs Yahoo mock drafts from the user's Chrome on instruction from the emissary or the master; posts the scorecard of every mock on #11 | change code |

The user may talk to any of the three. A session that receives a decision from the user relays it to the others
when it affects their work. Report outcomes faithfully: a failed test, a lost pick or a skipped step is stated
as such, with the evidence.

## Standing rules from the user

- **Do not use the superpowers plugin or any of its skills on this project.**
- Never commit `data/`, `.env`, tokens, cookies or anything derived from a subscriber source (Basketball Monster).
  `.gitignore` covers these; do not loosen it. The Yahoo players file (`data/yahoo_players_31822.json`) stays local.
- Claude never handles the user's credentials and never sees what the user types into a login form.
- No punts anywhere: the punt is an outcome of the objective, never a goal, and never an option in the API or UI.
- Nothing is auto-drafted for the user unless they armed it. In a mock the user has authorized as "armed", the drone
  arms at attach (`mode: autopilot`) under that authorization and the scorecard says so (decided 2026-10-02). On the
  real draft day the user arms it themselves from the side panel; no session arms the real draft for them. Manual picks, in Yahoo or in pickandroll, must
  always remain possible; they are mirrored into the session and never overridden.
- Never connect to the Yahoo draft socket as the user's slot from a second client (Yahoo kicks the user). The
  only reader of the user's seat is the user's own draft page (the extension's content script).
- One mock draft at a time, and at most two per day; a third needs the user's explicit approval in chat (the
  emissary cannot grant it). The user stays out of the mock room while the drone drives it. In Yahoo, queue
  only for the current pick and only when it is our turn. One exception (user, 2026-10-02): when the click
  backstop fires on a turn whose next pick is also ours (slots 1 and 12), it queues this pick's player and the
  plan's player for the next pick before switching Autodraft on, so Yahoo's instant autopick takes ours.
- Tune for the mocks, not the real league's clock (user, 2026-10-02): 30 s per pick is the design point for the
  drafter's wait, the solve budgets and every gate.
- Scratch experiments never go in `src/`. Reference material is ported, not imported; delete it once ported.

## Workflow

- Branch per issue off `main`: `feat/yahoo-sync-<issue>`, in a git worktree under `.claude/worktrees/<name>` inside this
  repo (gitignored, the pipeline plugin's convention), never as a sibling folder of `~/code/pickandroll`. The checkout itself stays on `main`. Conventional-commit titles with scope `yahoo-sync`.
  One PR per issue with `Closes #N`; the master reviews and merges. Only the master commits straight to
  `main`, and only docs.
- Python: `.venv/bin/python -m pytest` and `.venv/bin/ruff check src tests` green before any PR. **In a worktree**
  the editable install resolves `pickandroll` to `~/code/pickandroll/src`, so run
  `PYTHONPATH=src ~/code/pickandroll/.venv/bin/python -m pytest` from the worktree root, or you test main's code.
  Web: `cd web && npm run build && npm run lint` (ESLint flat config in `web/eslint.config.js` since #19; the
  script carries `--max-warnings 0`).
  Extension (#9 onward): `node --test extension/test/*.test.js` from the repo root (Node, no dependencies;
  the bare directory form fails on Node 25).
- Dev servers only through `~/code/.claude/launch.json` (`pickandroll-api` on :8000, `pickandroll-web`
  on :5173), never with ad-hoc shell commands. uvicorn `--reload` drops the in-memory sessions on every
  source edit, and a `git pull` into this checkout is a source edit: no pulls, checkouts or `src/` edits
  while a practice run or a mock is on the server (ask fantasyMOCK first; it wiped a finished run on
  2026-10-06). Draft night runs `pickandroll-api-draft` (same port, no `--reload`) on a frozen checkout.
- Core packages `src/pickandroll/{projections,draft,optim,availability}` stay free of I/O.
- A change to #8 passes the Tier 1 replay (`docs/YAHOO_SYNC.md` §5) before review. A change to the room side
  (#9) ships with a Tier 2 scorecard from a live mock. The scorecard goes on #11 as a comment.
