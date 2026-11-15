# pickandroll: working agreement for Claude sessions

Fantasy basketball draft optimizer for 9-category head-to-head leagues (the user's Yahoo league is 31822,
12 teams, 13 rounds, 30 s pick clock). Read `README.md`, `docs/DESIGN.md` and `docs/ROADMAP.md` first.

Current programme: **YAHOO SYNC**, tracker #11, built as #8 (API room endpoints) → #9 (Chrome extension)
and #10 (web UI). The metric, guardrails, event schema and hill-climb protocol are in `docs/YAHOO_SYNC.md`;
the proven scratch code to port is described in its §0 (archive at
`~/code/pickandroll-scratch/live-drafts-2026-09-27/`, outside the repo).
KEEPERS (`docs/KEEPERS.md`) shipped 2026-10-06; the real draft ran on 2026-10-14 (`docs/ROADMAP.md`, "Real draft").
The ownership map for traded picks and the draft-night dashboard fixes are merged (#55-#59). Now:
**survival from the league's own drafts** as the default, **more leagues**, and **ADD/DROP**
(`docs/ADD_DROP.md`), the in-season waiver engine (`docs/ROADMAP.md`, "Next programmes").

## Roles

Three Claude Desktop sessions share this checkout and reach each other with `ListAgents` / `SendMessage`.
The season simulator's three sessions run on the droplet as unix user `pnrsim`, in a clone of their own
(user, 2026-11-13); they are the second table.

| session | does | does not |
|---|---|---|
| **fantasyMASTER** | analysis, plans, metrics, spot checks, reviews and merges PRs, answers design questions; sends pnrsimLEAD updates on #172 (a merge that changes what the simulator calls, a ruling about the simulator, a change on the droplet) | implement; review, merge or direct the simulator's PRs |
| **fantasyEMISSARY** | implements, tests, hill-climbs `docs/YAHOO_SYNC.md`; owns #8, #9, #10; directs the drone | merge its own PRs |
| **fantasyMOCK** (the drone) | runs Yahoo mock drafts from the user's Chrome on instruction from the emissary or the master; posts the scorecard of every mock on #11 | change code |

On the droplet, as `pnrsim` (SEASON SIM, tracker #172; interactive sessions in tmux with Remote Control on):

| session | does | does not |
|---|---|---|
| **pnrsimLEAD** | leads the season simulator: plans, briefs, review; merges simulator PRs whose diff stays inside `src/pickandroll/sim/`, `tests/sim/` and `docs/sim/`, pinned to the head sha with the gates green; directs pnrsimBUILD and pnrsimEXPLAIN; posts a main-moved comment on #172 after each merge | build the PRs it merges; touch a file outside the simulator's folders, the live checkout, the routines, the API or the emissary's files |
| **pnrsimBUILD** | builds the simulator's PRs one at a time on pnrsimLEAD's brief, in its own worktrees; reports and stops after each | merge; touch non-simulator code |
| **pnrsimEXPLAIN** | edits the simulator's explainer page on pnrsimLEAD's brief | touch the repo |

The user may talk to any session, and rules on the simulator's design directly (since 2026-11-06). A session
that receives a decision from the user relays it to the others
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
  Exception (user, 2026-10-16) for the four cash leagues drafting 2026-10-17 to 2026-10-19 (238174, 15953, 208649,
  230585): the user may be away, so they pre-arm each league from the dashboard before its draft (their own click,
  recorded in `data/leagues/<id>/armed.json`, issue #67); the scheduled draft-day session then attaches, monitors and
  saves, and arms nothing itself. A league the user did not pre-arm runs in mirror and Yahoo autopicks their turns.
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

## Self-repair loop (user, 2026-11-12)

When a droplet routine fails, the sessions find the cause, fix it and merge the fix without asking the user first.
A failure means a failed step, an alert, a non-zero exit, a watchdog failure, or a step that did not do its job
(a claim that should have landed, a solve cut by its budget).

1. fantasyVM reports the failure to fantasyMASTER. It includes the run report's failed steps, their detail and
   the journal lines. It stays read only.
2. fantasyMASTER finds the cause from the reports, the journal and the code.
   - An outside failure (Yahoo 5xx, a rate limit) still gets a fix when the code handled it badly: no retry, a
     wrong verdict, or a reason it did not log.
3. When the cause is in the code, fantasyMASTER:
   - files the issue (a failure fix needs no yes);
   - briefs fantasyEMISSARY;
   - reviews the PR and merges it, pinned to its head sha, once its gates are green;
   - posts the main-moved note.
4. fantasyMASTER then tells the user the failure, the cause, the fix and the PR.

Limits:
- Reliability fixes only: making a run do what it was meant to do. These still need the user's ruling first:
  - a change to what the model recommends or how it scores (the objective, the rules, thresholds, knobs);
  - a new rule of the ad-hoc kind the user rejected.
- Deploy without asking too (user, 2026-11-12). After the merge, fantasyMASTER runs `ops/vm/update.sh` on the
  droplet. It deploys all of main.
  - Never while a routine unit is active (`systemctl --user list-units 'pickandroll-*' --state=active,activating`).
  - Never inside these quiet windows (CT): 04:45-05:50, 09:10-09:25, 14:50-15:15, a pretip slate's run,
    21:00-21:30, 22:35-23:00.
  - After it: the droplet's HEAD is the merged sha, the API answers 200, and fantasyVM watches the next run of
    the fixed routine.
  - A failed deploy, or an API that does not come back, goes to the user at once.
- The loop never touches:
  - credentials or sign-ins;
  - a browser's cookie or login stores;
  - the moves and lineup live switches or the executor knobs;
  - clicks on Yahoo.
  A real sign-out is the user's step.
- One fix PR per failure.
- If the same failure comes back after its fix is deployed, stop and ask the user instead of layering fixes.

## The simulator's sessions on the droplet (user, 2026-11-13)

The season simulator is standalone (user, 2026-11-07) and is built from the droplet by three sessions under
the unix user `pnrsim`: their own clone (`~pnrsim/pickandroll`), venv and worktrees, and a `data/` that holds
only the frozen fit and the ESPN game logs.

- `pnrsim` cannot read `~pickandroll`, and holds no league sign-in, cookie, league file or subscriber export.
  Its `gh` and Claude sign-ins are the user's steps.
- Its sessions never run `ops/vm/update.sh`, never touch a unit or a timer, and never write to the API. The
  simulator's guard asks the API one read-only question (`GET /rooms`).
- A heavy job (the suite, a replay) starts only outside the quiet windows above and while no routine is
  running, at low priority, one at a time, under the user slice's CPU and memory limits.
- A real run over an hour is announced on #172 and starts only on the user's word.
- The 2024-25 hold-out is never replayed, fitted or tuned on.
- A simulator merge moves `main`, so the master's next deploy carries it. `tests/sim/test_boundary.py` keeps
  it inert for the live code: nothing outside `src/pickandroll/sim/` imports the simulator.

## Workflow

- Branch per issue off `main`: `feat/yahoo-sync-<issue>`, in a git worktree under `.claude/worktrees/<name>` inside this
  repo (gitignored, the pipeline plugin's convention), never as a sibling folder of `~/code/pickandroll`. The checkout itself stays on `main`. Conventional-commit titles with scope `yahoo-sync`.
  One PR per issue with `Closes #N`; the master reviews and merges. Only the master commits straight to
  `main`, and only docs. One exception (user, 2026-11-13): a simulator PR whose diff stays inside
  `src/pickandroll/sim/`, `tests/sim/` and `docs/sim/` is reviewed and merged by pnrsimLEAD, pinned to its
  head sha, with the suite, ruff and `tests/sim/test_boundary.py` green on a branch that holds `origin/main`.
  pnrsimLEAD never merges a PR it built. A simulator PR that touches any other file is the master's to merge,
  and a change the simulator needs in the engine is asked on #172 (the master files it and briefs the emissary).
- Python: `.venv/bin/python -m pytest` and `.venv/bin/ruff check src tests` green before any PR. **In a worktree**
  the editable install resolves `pickandroll` to `~/code/pickandroll/src`, so run
  `PYTHONPATH=src ~/code/pickandroll/.venv/bin/python -m pytest` from the worktree root, or you test main's code.
  Web: `cd web && npm run build && npm run lint && npm test` (ESLint flat config in `web/eslint.config.js` since #19;
  the script carries `--max-warnings 0`; `npm test` runs `node --test` over `src/**/*.test.ts`, since #55).
  Extension (#9 onward): `node --test extension/test/*.test.js` from the repo root (Node, no dependencies;
  the bare directory form fails on Node 25).
- Dev servers only through `~/code/.claude/launch.json` (`pickandroll-api` on :8000, `pickandroll-web`
  on :5173), never with ad-hoc shell commands. uvicorn `--reload` drops the in-memory sessions on every
  source edit, and a `git pull` into this checkout is a source edit: no pulls, checkouts or `src/` edits
  while a practice run or a mock is on the server (ask fantasyMOCK first; it wiped a finished run on
  2026-10-06). Draft night runs `pickandroll-api-draft` (same port, no `--reload`) on a frozen checkout.
- Core packages `src/pickandroll/{projections,draft,optim,availability}` stay free of I/O.
- Keeping up with `main` (user, 2026-10-23): after every merge the master posts a "main moved" note to each
  building session on the Mac (fantasyEMISSARY) with the new sha, the PR and the files it touched. The
  simulator's sessions read `main` themselves at the start of each turn; what git cannot carry (a merge that
  changes what the simulator calls, a ruling about the simulator, a change on the droplet) the master posts
  on #172 as a comment opening `to pnrsimLEAD:`, and pnrsimLEAD posts one opening `to fantasyMASTER:` after
  each of its merges (sha, PR, files). A one-line `SendMessage` may follow as a wake-up; the comment is the
  record. A session
  with an open branch then runs `git fetch origin && git merge origin/main` in its worktree (merge, never rebase:
  force pushes are blocked), re-runs its gates and pushes; a session about to cut a worktree cuts it from the new
  main. Before opening any PR a session fetches and merges `origin/main` itself, and the PR body names the main it
  was tested against. A merge of one session's PR that touches a file another session builds on is called out in
  the note by name, with what changed.
- A change to #8 passes the Tier 1 replay (`docs/YAHOO_SYNC.md` §5) before review. A change to the room side
  (#9) ships with a Tier 2 scorecard from a live mock. The scorecard goes on #11 as a comment.
