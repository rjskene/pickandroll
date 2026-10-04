# YAHOO SYNC: fidelity metrics and hill-climb protocol (2026-10-01)

Owner: fantasyMASTER (analysis, plans, spot checks). Builder: fantasyEMISSARY (implements, tests). Drone: fantasyMOCK (runs the Yahoo mock drafts, one at a time, directed by the emissary or the master).

## 0. What to port from the scratch archive

Three live drafts (5, 6, 7 on 2026-09-27) were driven with scratch code that now lives at `~/code/pickandroll-scratch/live-drafts-2026-09-27/`
(outside the repo; the user may copy it to `scratch/live-drafts-2026-09-27/`, nothing imports it). Its `README.md`
explains every file and `fidelity_summary_drafts5-7.md` is the cross-draft summary. It is the proven starting
point: port behaviour, not files.

| scratch file | what it proved | goes to |
|---|---|---|
| `hook6.js` (v16; `hook6_v15.js` for diffing) | in-page websocket hook (`0|overall|yid|slot|pos|0` picks, `D|pick|slot|clock` on-the-clock, `P|…` history on connect), turn detection from the clock message, taken-filter, row click + same-row re-click at 1.8 s then 2.5 s (Yahoo drops clicks that land during a re-render; a registered click confirms within 400 ms), search-box and scroll fallbacks for rows not in view, queue fallback for the current pick only, Web-Worker timers (hidden tabs throttle `setTimeout` to 1/min after 5 min), board-tab backfill of missed picks | #9 extension content script |
| `relay.py` | `/picks` idempotent + contiguous ingestion with PENDING stand-ins for gaps; `/board` "F. Last;TEAM" → Yahoo id with ADP disambiguation (S. Curry GSW, J. Williams OKC); `/reco` candidate list by Yahoo id; `/event` fidelity log per draft; `/status` | #8 API room endpoints |
| `bridge.py create` | session creation for a room: slot, draft id; time limit 5 s, n 3, scenarios 0 kept solves inside a 30 s clock | #8 attach endpoint |
| `report.py`, `fidelity_*.jsonl` | the scorecard and the event vocabulary; §4 below is the cleaned-up schema | #8 fidelity recorder + `fidelity report` |
| `yahoo_map.json` | Yahoo id → pickandroll player, name, team, ADP; derived from `data/yahoo_players_31822.json` (local only) through `sources/matching.py` | built at attach time, never committed |
| `board_*.txt`, `hook_times_*.txt` | real 156-pick orders with ms arrival times | Tier 1 replay fixtures (`tests/fixtures/rooms/`; pick order and timings only) |
| `progress_draft*.log`, `agent7_prompt.txt`, `cycle7.py`, `drain.py`, `watch.py`, `mapdom.py` | how the driver-mode loop worked; the extension replaces that loop entirely | read once, do not port |

Room facts that are not in the code: Yahoo autopicks instantly for an absent seat and at the 30 s expiry; one
missed pick flips the seat into autopick mode (must be turned off by hand); the filtered Draft button drafts the
wrong player; the lobby's Join button hijacks the draft tab; Chrome blocks every page→localhost request from
yahoo.com without a user gesture (why driver mode existed, and why the extension's service worker is the fix);
at the waiting-room countdown's zero Yahoo may reload the page and show an "Enter Draft" link instead of
redirecting into the draft client, and pick 1 goes on the clock about 60 s after zero (mocks 3 and 4).

## 1. Primary metric: compliance

For each of my seat's 13 picks k in a Yahoo draft:

- `ref_k` = the #1 candidate of the recommendation the drafter acted on: the most recent published pickandroll recommendation whose board contained exactly picks 1..k-1 (the fresh recommendation for my turn), as of the drafter's first draft attempt for pick k. When no attempt was logged (autopick, expiry, manual pick), it is the last such recommendation before the pick landed. If no such recommendation existed, `ref_k` is undefined.
- A recommendation for one board may be refined after it is served (branch or early plan, then priced table). Compliance judges the drafter against what it was served when it acted, never against a refinement that arrived while the click was in flight. Refinements that change the #1 candidate are counted separately as churn (D6) and each one needs a root cause.
- `actual_k` = the player Yahoo recorded for my seat at overall pick k.
- `compliant_k` = (`actual_k` == `ref_k`), by Yahoo player id.

**Compliance = Σ compliant_k / (13 − manual picks).** A pick the user (or the drone, standing in for the user) made by hand is excluded from both numerator and denominator and reported separately. Yahoo autopicks, expiries, rank-2 fallbacks and stale-plan picks all count as failures: the denominator is always every autopilot turn, never only the turns the tool attempted.

**Target: 13/13 (or 12/12 with one manual pick) in two consecutive mock drafts.**

### Failure taxonomy (one label per non-compliant pick; the hill-climb works on these counts)

| label | meaning |
|---|---|
| `absent` | the seat was not under autopilot control when the turn started (late entry, disconnect, autopick mode on) |
| `stale` | the drafter acted on a plan for a board older than k-1: either the session had not applied all picks 1..k-1 when the pick landed, or the drafter read the plan before the sync of pick k-1 (the plan's `board` on the attempt is < k-1) |
| `unsolved` | synced, but no fresh recommendation for board k-1 existed before the pick landed |
| `expired` | `ref_k` existed, no pick landed before the 30 s clock; Yahoo autopicked |
| `fallback` | a candidate other than `ref_k` landed (row not found / click lost, took rank 2+) |
| `wrong` | a player outside the candidate list landed (filter or click bug) |
| `manual` | user-made pick; excluded, see guardrail G4 |

Baseline from drafts 5-7 (2026-09-27, scratch hook in driver mode), loose count (plan top at turn start even when the session was behind): 12/13, 10/13, 4/13. Under this spec those would score lower, because the session was 1 to 15 picks behind at most turns (`stale`).

## 2. Guardrails (must hold for a draft to count as a pass)

| id | metric | definition | baseline (d5 / d6 / d7) | target |
|---|---|---|---|---|
| G1 | board agreement | session picks == Yahoo picks at draft end, by Yahoo id, all 156 | 156 only after hand fixes of 2 ambiguous names | 156/156 unaided |
| G2 | sync lag | per pick: t(applied in session) − t(socket message in the room); p50 / p95 / max | 40.6/121/191 s; 31.9/76/108 s; 13.0/21.9/24 s steady state | p50 ≤ 1 s, p95 ≤ 2 s, max ≤ 5 s |
| G3 | hands-off | interventions by a human or an agent during the draft (console calls, manual relay fixes) | many | 0 |
| G4 | manual respected | when a manual pick is made on my turn, the autopilot stands down (no draft attempt after it but the click of the user's own request, method `request`) and the session mirrors the manual pick within G2 | n/a | 1/1 per draft |
| G5 | autopick mode | times Yahoo flipped the seat into autopick mode | 1 (draft 7) | 0 |
| G7 | client timers | heartbeats while attached report `worker: true` (the page-world Worker timer host answered the content script); on `false` every drafter sleep is a DOM timer, which a hidden tab aligns to 1 s and, after minutes hidden, to 1 min, so a turn can silently miss the clock | false on all heartbeats in three harness runs (h13, h13b, h13c), true in mock 1 | true on every heartbeat |
| G6 | entry lead | seconds inside the draft client before pick 1 went on the clock; Yahoo opens the client only when the waiting-room countdown ends, about 60 s before pick 1, so the ceiling is ~59 s. At zero it may instead reload the waiting room with an "Enter Draft" link (room facts), and an immediate click leaves about 45–47 s (44.8 s in mock 4). The tab needs under 5 s of it (history frame, first heartbeat, the board-0 plan solved ahead), so 30 s is the target (user, 2026-10-03) | −210 s (draft 7) | ≥ 30 s |

## 3. Diagnostics (reported every draft, not pass/fail)

| id | metric | definition | baseline | goal |
|---|---|---|---|---|
| D1 | reco readiness | per my pick: t(fresh reco for board k-1) − t(turn start); negative = ready before the turn. Three classes per turn: hit = a pre-solved branch for board k-1 had converged before turn start; pending = the branch existed but was still solving at turn start (typically the own-choice branch behind the second pick of a back-to-back pair); miss = no branch, the board was solved cold at the turn | not measured | hits ≤ 1 s; pending and misses ≤ plan budget + price limit + 1 s (11 s on a 30 s clock, where a capped cold plan lands at budget plus pricing by construction); counts of all three reported, hit goal ≥ 9/13 at human pace |
| D2 | turn-to-land | t(Yahoo registers my pick) − t(turn start) | 1.3-1.6 s clean, 10-13 s with re-clicks | p50 ≤ 5 s, max ≤ 15 s |
| D3 | solve time | wall time of each recommendation solve during the draft | sum 0.3 s; curve up to 20 s limit | fits inside D1 |
| D4 | draft attempts | row clicks / queue uses per landed pick | up to 3 | 1 |
| D5 | final score | expected category wins of the final roster vs the benchmark (existing `/score`) | 5.24, 5.09, 5.30 | report only |
| D6 | reco churn | my turns where the last reco for board k-1 before the pick landed has a different #1 than `ref_k` (the reco acted on); listed per pick with both players and both reco kinds (plan / converged / priced), plus compliance recomputed against the final reco | not measured | 0; every churned turn gets a root cause before a cell or mock counts as green |

## 4. Event log (what the recorder must capture so the scorecard is computable)

One JSON object per line, per draft id, in `data/fidelity/<draft_id>.jsonl` (local, never committed), written by the API (#8). Times are ISO-8601 UTC with ms. Client events carry the client's `t` when it sends one (else the receive time) and `recv`, the server's receive time; `room_pick.t` is `t_room`, the room's own clock, when the client sends it. `src` is `api` on events the server writes for itself and `client` on posted ones.

Written by the server:

```
{"type":"attach",       "t":..., "draft_id":d, "slot":s, "mode":"mirror|autopilot", "num_teams":12, "rounds":13, "players_file":f, "session_id":..., "session":{...}, "resumed":bool, "mapped":n, "players":n}
{"type":"detach",       "t":..., "session_id":...}
{"type":"room_pick",    "t":..., "overall":n, "slot":s, "yid":id, "src":"socket|history|board", "name":...}
{"type":"session_pick", "t":..., "overall":n, "pid":..., "yid":id, "lag_ms":..., "standin":bool, "kind":"new|held|conflict|repair", "resume":true?}
{"type":"conflict",     "t":..., "overall":n, "session_pid":..., "session_yid":id, "room_yid":id, "room_pid":...}
{"type":"reco",         "t":..., "board":n_applied, "version":v, "fresh":bool, "top_yid":id, "top_name":..., "top_pid":..., "cands":[yid,...], "unmapped":[{"pid":...,"name":...}], "solve_ms":..., "mode":..., "model":"horizon|roster"}
{"type":"score",        "t":..., "wins":x, "benchmark":x, "vs_benchmark":x, "best":x, "matchups":{...}}
{"type":"control",      "t":..., "state":"armed|mirror|absent", "slot":s, "mode":"mirror|autopilot", "act_at_s":n|null, "src":"api"}  // at attach, on every PATCH /rooms/{d} and on a team-count mismatch; act_at_s (#10): armed turns click with n s left, null at once; a rebuild restores mode and act_at_s from the last one since a detach (#20)
{"type":"note", "what":"draft request", "t":..., "overall":n, "board":b, "yid":id, "request_id":r}  // the web app's "Draft in Yahoo" (#10), held for the draft tab; r is the request's id (#22)
```

Posted by the client (`POST /rooms/{draft_id}/events`):

```
{"type":"control",      "t":..., "state":"armed|mirror|absent", "slot":s, "reason":"autopick"?, "mode":..., "act_at_s":n|null}
{"type":"turn_start",   "t":..., "overall":n, "slot":s, "clock_s":30, "teams":T|null}  // T: the room's own team count, once the snake has turned
{"type":"draft_attempt","t":..., "overall":n, "yid":id, "method":"row|queue|search|request", "attempt":k, "board":b}  // b = board of the plan the drafter acted on; request: the user's "Draft in Yahoo" (#10), landing how "manual"
{"type":"note", "what":"queue_probe", "t":..., "overall":n, "yid":id, "name":..., "board":b, "outcome":"queued|drafted|dropped|no_control|failed", "panel":[...], "control":"...", "panel_found":bool, "controls":[{"cell":i,"pos":j,"tag":"button","labels":"..."}]}  // one per armed draft, §6; a note, not a new type, so no API version drops it
{"type":"pick_landed",  "t":..., "overall":n, "yid":id, "how":"row|queue|manual|expiry|autopick", "ms_from_turn":...}
{"type":"intervention", "t":..., "who":"master|emissary|drone|user", "what":"..."}
{"type":"heartbeat",    "t":..., "worker":bool, ...}  // worker: the Worker timer host is live (G7)
{"type":"note", "what":"request", "t":..., "overall":n, "yid":id, "request_id":r, "result":"landed|manual|other|stopped|failed", "attempts":k}  // a "Draft in Yahoo" served (#10); "request failed" (with attempts or msg, and request_id) drops it in the API only when it names the pending request (by request_id; overall and yid from a tab before #22), so a request the user made since, of the same player too, is kept; it hands an armed turn back, and a request that lands ends the armed turn that stood aside
{"type":"note",         "t":..., "what":"..."}
```

- `attach` carries the session settings, so `POST /rooms {draft_id}` rebuilds the room from the log after an API restart. A later `detach` stops that.
- `session_pick.kind`:
  - `new`: a pick the session did not have.
  - `held`: the session already had the same player.
  - `conflict`: the session had another player and the room wins. A `conflict` event names both players.
  - `repair`: a stand-in replaced by the real player once he became free.
- `standin` is true when the room's player had no projection id or was held elsewhere; the session holds the least useful free player in his place. The server writes `note` when the room reports two players for one overall, or an alias is pinned.
- `reco.model` is `roster` when the horizon plan could not be built and the single-roster model answered (the session's picks and open slots disagree; in a room, the session and the room disagree on the draft). Goal 0 in a room. The first one writes a `note` `roster fallback` with the reason. Logs before #17 carry only `mode`, with the same values.
- The attach may carry `room_teams`, the room's own team count. An attach that disagrees with it is refused (422) before a session is made. When a later `turn_start.teams` disagrees, the API sets the room to mirror once, writes a `note` `team count mismatch` and refuses to arm it again (409).
- `reco.board` is the number of picks the solve saw. `top_pid` is the solve's own first choice, mapped or not. `top_yid` is the first candidate the drafter is served, which skips players with no Yahoo id. Those are listed in `unmapped`.
- `score` (D5) is written once, when my last pick reaches the session.
- `turn_start` is accepted for any slot. The one for pick 1 lets the scorecard check G6 when pick 1 is not mine.
- `control` with `reason: "autopick"` counts as a G5 flip.
- Heartbeats are kept in memory and written at most once a minute.

Derivations:
- Landing time `t_land(k)` is `pick_landed.t`, else `room_pick.t`.
- Turn start is `turn_start.t`, else the `room_pick.t` of pick k-1.
- `ref_k` is the last `reco` with `board == k-1` and `t <= t_attempt(k)`, where `t_attempt(k)` is the first `draft_attempt` for overall k; without one, `t < t_land(k)`. When its `top_pid` is in `unmapped`, the drafter could not take it: the ref is shown by name and the pick is at best a `fallback`.
- `final_k` is the last `reco` with `board == k-1` and `t < t_land(k)`. D6 counts turns where `final_k.top_pid != ref_k.top_pid`; the scorecard also prints compliance against `final_k` as a diagnostic line.
- Labels apply in this order:
  1. `manual`: `pick_landed.how == "manual"`.
  2. `compliant`: the drafter made the pick and the actual player equals `ref_k`. The drafter made the pick when `pick_landed.how` is `row`, `queue` or `search`, or a `draft_attempt` for overall k with the landed `yid` precedes `t_land(k)` (a queued player taken by Yahoo at expiry counts; D2 shows the cost). An expiry or autopick that happens to equal `ref_k` is never compliant: it goes on to the labels below, which end in `expired`.
  3. `absent`: control was not `armed` at turn start, or the tab learned the pick from Yahoo's history frame (the tab was not in the room when it was made: a late entry or a reconnect). In mirror mode every non-compliant pick reads `absent`.
  4. `stale`: picks 1..k-1 were not all in the session when pick k landed, judged by the first `session_pick` time per overall (§1); or the first `draft_attempt` for k carries `board < k-1`. The drafter must only act on a plan whose `board == k-1`, so a `stale` label with a synced session is a drafter bug, not a sync bug.
  5. `unsolved`: synced, but no `ref_k` (no reco for board k-1 before landing).
  6. `expired`: `how` is `expiry` or `autopick`.
  7. `fallback`: the actual player is in `ref_k.cands`, or the ref had no Yahoo id.
  8. `wrong`: anything else.
- Sync lag (G2) is the first `session_pick.t − room_pick.t` per overall.
- Board agreement (G1) counts overalls whose latest `session_pick` has the room's `yid` and is not a stand-in.
- Client timers (G7): every `heartbeat` after the attach has `worker == true`; the scorecard prints the count of false heartbeats and the first time one appeared.
- Entry lead (G6) is pick 1's turn start minus the first client `control` or `heartbeat`. Without one, it falls back to the `attach` control, and the scorecard says "from attach".

Scorecard: `pickandroll fidelity report <draft_id>` (CLI or `GET /rooms/{draft_id}/fidelity`) prints the compliance line, the taxonomy counts, G1-G6, D1-D5, and a per-pick table (overall, ref, actual, label, lag, turn-to-land). Markdown, so it can be pasted into the tracker.

## 5. Two measurement tiers

- **Tier 1, replay (offline, seconds, deterministic, runs in tests).** Replay a recorded room (`board_*.txt` pick order + `hook_times_*.txt` timings from the scratch archive (§0), 156 picks each) into the API at real or accelerated speed. Measures G1, G2 (API side), D1, D3. Every change to #8 is checked here first.
- **Tier 2, live mock (the drone, ~45-75 min, one at a time).** A real Yahoo 12-team mock from the user's Chrome. Measures everything. Each mock includes exactly one manual pick at a turn the drone chooses (G4). No code change ships to main without a Tier 2 scorecard when it touches the room side (#9).

## 6. Hill-climb protocol

Room protocol for the drone: attach the room (`POST /rooms`, draft id = Yahoo's mlid, slot from the waiting
room) while still in the waiting room, at least 60 s before pick 1, and confirm the attach before reporting the
room; enter the draft client the moment it opens; Yahoo's Autodraft switch is disabled until pick 1 is on the clock.

Queue probe (every armed draft): the Yahoo queue path (the click backstop, one entry or two) has never been seen in a real room, and notes from drafts 5-6 say the row's first-cell button on our turn may be Draft rather than the queue star. So on one of our turns per draft, by default the first turn of round 3 that is not back-to-back, the drafter stars the plan's #1 candidate before clicking Draft, reads the queue panel, logs one `queue_probe` event and then proceeds normally. Both outcomes are harmless: the star queues our player, or it drafts the player we wanted. `dropped` means a Draft-labelled control took no effect inside 1.9 s (a lost click, as the harness simulates); `failed` is reserved for a control that was not Draft and produced neither. The scorecard prints the outcome. Configurable (round, or off) on the options page. The probe runs only with more than 14 s on the clock (8 s for it before the 6 s backstop), so with `act_at_s` at 14 s or less (#10) it never runs and the scorecard shows no probe: a draft that must probe keeps `act_at_s` null or at 16 s or more (the hold releases at 15 s or less, in 250 ms steps, and the last look's round trip comes before the probe's check). It does not run during the act_at_s hold either: on our turn the first-cell control is Draft (mock 2), so the probe would draft at once and close the window the user waits for.

Plan budget and the clock (#13): unless the attach gives a `time_limit`, the plan's budget follows the room's
pick clock. It is clock − 13 s (the drafter's margin) − 12 s (pricing), at least 5 s and at most 20 s: 30 s (the
mocks) gives 5 s, 40 s gives 15 s, and 45 s or more gives 20 s. The attach may pass `clock_s`. Otherwise the room
starts at 30 s and adopts the longest clock the client reports on its `turn_start` events (Yahoo's `D|` frame),
logging a `plan_budget` note. On a 30 s clock the plan is often a time-limited incumbent (rounds 1-6 need 6-16 s
to converge), and only the exact prices correct its first pick, so an unpriced plan is served only when it
converged.


1. The emissary states the hypothesis and the metric it expects to move before a mock starts.
2. The drone runs one mock, posts the scorecard (markdown from §4) on the tracker #11.
3. Compare against the best previous scorecard. Keep the change only if compliance did not drop and no guardrail regressed. Taxonomy counts say what to fix next; the order of attack is `absent` → `stale` → `unsolved` → `expired` → `fallback` → `wrong`.
4. **Value comparisons need a noise floor.** Under a capped plan (the 5 s limit of a 30 s clock) a single settled replay
   varies by up to 0.7 expected wins between runs of the same code, because capped incumbents depend on CPU timing
   and one early divergence changes the rest of the draft (measured 2026-10-01 on #13). A value gate is therefore
   judged on 3-run means per cell, or on a deterministic comparison with both sides uncapped (time limit 60 s), never
   on a single run. Timing measurements (harness cells) and value runs never share the CPU.
   The gate itself (2026-10-02): over the settled slots (both fixtures, slots 1/4/6/12), every slot 13/13 and the mean
   Δ ≥ −0.02 expected wins. A slot below −0.05 passes only if its first divergence is a within-gap decision: the two
   candidates' objectives on that board differ by less than the solver's MIP gap (1%), shown from the logged
   objectives. Below the gap the solver cannot tell the two apart, and the end-of-draft difference is path dependence
   with either sign (measured: −0.067 and +0.258 on two slots of the same change). Deterministic uncapped runs
   reproduce such a split exactly, so repeating them does not resolve it; the within-gap check does.
5. Done = two consecutive mocks at 13/13 (12/12 + 1 manual) with G1-G6 green. After that, mocks continue only to test new features, at least one per week until the real draft.

## 7. Standing rules for all three sessions

- No superpowers skills on pickandroll work.
- Never commit `data/`, `.env`, tokens. The Yahoo players file is data; the pick-order fixtures from the archive are fine in tests.
- Never join the Yahoo draft socket as the user's slot from a second client. The only reader of my seat is the user's own draft page (the extension's content script).
- Only one mock draft at a time. The user stays out of the mock room while the drone drives it.
- Queue only for the current pick, and only when it is our turn. One exception (user, 2026-10-02): when the click backstop fires on a turn whose next pick is also ours (slots 1 and 12), it queues this pick's player and the plan's player for the next pick before switching Autodraft on. Yahoo autopicks the next pick the instant it starts while Autodraft is on, so an empty queue there hands it Yahoo's choice. The second entry is consumed on the next frame and never sits across an opponent's pick; the attempt is logged with the plan's board and labels `stale` honestly.
- Tune for the mocks, not the real league's clock (user, 2026-10-02): 30 s per pick is the design point for the drafter's wait, the solve budgets and every gate. The attach still adopts the room's reported clock, but no run targets another clock.
- Branch per issue, PR to main, master reviews and merges.

## 8. Schedule and token budget (user decisions, 2026-10-01)

**Real draft: mid-October 2026**, about two weeks out. Milestone targets: #8 merged by 10-04; #9 mirror mode by
10-06 (first mock, mirror only, measures G1 and G2); #9 armed mode by 10-08 (compliance mocks); #10 by 10-10;
acceptance pair of mocks 10-11 to 10-13. **Freeze on 10-12:** after that no change to the room side (#9) unless a
scorecard shows the failure it fixes, and the last two clean mocks before the draft are the acceptance run.

**Token budget is a hard constraint.** The user's weekly usage limit can be burnt in a day by draft loops, so:

1. **At most two live mocks per day, hard cap.** A third mock on the same calendar day needs the user's explicit
   approval in chat, given to the drone or the master; the emissary cannot grant it. Every mock needs, before it starts: Tier 1 replay green, a hypothesis
   naming the taxonomy label or guardrail it targets, and a code change since the previous mock. The same build
   is never mocked twice, except the acceptance pair. A failure that appears in two consecutive scorecards stops
   mocking: fix it offline (replay tier, or a harness built from the recorded room) before the next mock.
2. **Abort early, do not ride out a lost mock.** The drone leaves the mock and writes a short scorecard (what
   failed, at which pick) when: the seat is not inside the draft client 30 s before pick 1 (G6); sync lag p95 over
   the first 24 picks is above 10 s; any pick is `absent` or `wrong`. An abandoned mock seat autopicks, which is
   fine in a mock.
3. **Drone discipline during a mock: the extension and the API do the work, the recorder keeps the evidence.**
   No screenshots after arming. At most one check per round (text tools or the status endpoint, never a
   screenshot), long waits between checks, target under 40 tool calls per mock. Read the scorecard at the end
   instead of watching picks.
4. **Emissary discipline.** Port from the §0 table instead of re-reading the archive; targeted tests while
   iterating, the full suite at milestones; comments on the issues only for plan, PR and scorecard, no running
   commentary; every iteration on #8 goes through the replay tier, not a mock.
5. **Master discipline.** Spot checks at plan, PR and scorecard time only.
