# KEEPERS: keeper-league support (2026-10-06)

Owner: fantasyMASTER (this spec, review, merge). Builder: fantasyEMISSARY. Drone: fantasyMOCK (keeper
practice runs against the local simulator; Yahoo mock drafts have no keepers).

League 31822 is a keeper league. The real draft is **Wed 2026-10-14, 6:00 pm PDT**. The user has two
keeper candidates (a round-7 and a round-13 player; the names stay in the local practice file). The tool has no notion of a
keeper today (`grep -ri keeper src tests web extension` is empty), so a keeper draft breaks the planner in
three ways: the keepers are still on the board, my keeper rounds are planned as open picks, and every
other team's keeper is priced as available. This document is the build spec. It should be practised in
local sims during the week of 2026-10-07 and be in `main` before the real draft.

## 0. What a keeper is, in this league

Facts from the league's Yahoo archive (`data/yahoo_history/`, local; report in
`data/scratch/yahoo-history-analysis-2026-10-06.md`, nine keeper seasons 2017-2025):

- A team keeps 0-3 players (max 3 per team was seen twice, 2 is the norm). The league kept 8-22 players per
  draft, median 16, so about 10% of the 156 picks are decided before the draft.
- A keeper occupies **the round the team drafted him the year before** (51 of 56 verified cases); a
  waiver pickup costs a late round (R10-R13, set by the commissioner). The keeper's pick is that team's
  pick in that round of the snake, so its overall number follows from the team's slot once the order is
  drawn.
- Yahoo's draft results list keeper picks as ordinary picks at those slots. In the draft room the pick
  is recorded for the team when the clock reaches the slot (**to verify on the night: whether the room
  pre-fills keeper picks in the `P|` history on connect, or emits `0|overall|yid|slot` frames as the
  slots pass; the extension must survive both**).
- Keepers are bargains: pick minus ADP averaged +22 to +58 picks per season. They remove good players
  from the market, so every remaining player's effective ADP moves up by the number of keepers ranked
  ahead of him; in that adjusted space the league drafts to ADP with no bias (|mean| <= 1.6 picks in
  every ADP bucket), while in raw overall-pick space it looks like the league takes ADP 37-108 players
  6-9 picks early. Many ADP 110+ players go undrafted: P(undrafted | effective ADP) is 0.22 at 90, 0.39
  at 100, 0.54 at 110, 0.68 at 130; the normal ADP model puts ~0 there.
- Yahoo lists the current season's keepers at
  `basketball.fantasysports.yahoo.com/nba/31822/players?status=K` once managers set them (the archive
  shows every past season this way). That page gives the player and the team, not the round; the round
  follows the rule above or the draft room's board.

## 1. Model

A keeper is `(team position, round, player)`. The derived overall pick is
`snake_picks(num_teams, position, roster_size)[round - 1]` (`draft/settings.py`). My keepers are given
with `position = None`, meaning "my position", so that they follow `my_position` when a room attach
changes it (`api/yahoo_room.py::attach_room` overwrites `state.my_position = slot`).

Invariants, in `DraftState` (`draft/state.py`):

1. **The pick log stays contiguous.** `next_overall == len(picks) + 1` is relied on by `apply_pick`,
   `sync`, `yahoo_room._walk` (`state.picks[k - 1]`), presolve and both simulators. Keepers do not get
   written into `picks` ahead of time. Instead, **whenever `next_overall` is a keeper slot the keeper's
   pick is appended automatically** (`Pick(overall, team, player_id)` with the same team labels as
   `autopick.team_label`: `my_team` for my position, `Team N` otherwise). This happens in
   `__post_init__` (a keeper at overall 1), at the end of `apply_pick`, and therefore inside `sync`,
   `simulate`, `draft_once`, `branch_boards` and `_walk`, none of which need to know. Loop, since
   consecutive slots can both be keepers.
2. **`taken` = players in `picks` ∪ every keeper not yet in `picks`.** That one change removes keepers
   from `available`, `solver_players`, `candidates`, the board rows, `yahoo_room.candidates`,
   `_standin` and `likely_next`.
3. **`my_roster` = my picks in the log ∪ my keepers not yet in the log**, in draft order (keeper at its
   round). `problem()` and `horizon_problem()` lock `my_roster`, so my keepers are on the roster from
   pick one; `open_slots`, `roster_totals`, `roster_value`, `projected_finals` count them.
4. **`my_picks` excludes my keeper overalls** (rename the full snake list `my_slots` if anything still
   needs it). `my_remaining_picks`, `my_next_pick`, `on_the_clock` follow, so
   `HorizonProblem.__post_init__`'s check `len(picks) == len(slots) - len(locks)` holds: 13 - 2 = 11.
5. **Other teams' keepers** are theirs: `team_totals`, `projected_finals` and `lp_choices`
   (`team_roster`) see them on the owning team's roster before the slot is reached, so the league table
   and the LP drafter plan around them. `replacement_level`'s window start
   (`total_picks - len(picks) - 1`) counts future keeper slots as spent.
6. **Undo** (`DELETE /sessions/{id}/picks/last`) pops trailing keeper picks and then one real pick, and
   says which; a keeper pick alone is never the undo target (it would be re-applied at once).
7. **`apply_pick` at a keeper slot** accepts only the keeper himself (idempotent, returns the existing
   pick) and rejects any other player with `ValueError("pick N is a keeper slot: <player>")`. The room
   wins on a genuine conflict, in either direction: another player recorded at the keeper's slot, or a
   pending keeper recorded at some other team's slot. `_walk` replaces or applies the room's pick as it
   does today, logs `conflict`, and the keeper entry is dropped (`DraftState.drop_keeper`) because the
   Yahoo record is the truth and the table was wrong; the event says so. `sync()` stays strict: a feed
   that names someone else at a filled keeper slot is a 400 naming the slot and the keeper.
8. **Keeper picks are recognised through the table** (overall -> entry), never by a flag that could
   outlive a conflict. `team_names()` skips them, so an auto-applied `Team N` label never overwrites a
   real team name from the feed. `solver_players`' remaining count and `replacement_level`'s window
   count pending keeper slots as spent.
9. **`set_my_position(slot)`** replaces the bare assignment in `attach_room`: it refuses only when real
   (non-keeper) picks exist, re-derives my keepers' overalls and re-runs the auto-append (a round-1
   keeper of mine at the new slot). `draft_once`'s "no picks" guard tests real picks the same way.
10. **presolve `branch_boards`** leaves keeper slots out of `between` (they are decided), so a keeper
    between now and my pick makes a one-away branch rather than a silently dropped two-away one; its
    back-to-back test reads the draftable `my_picks`.

### 1.1 Availability in keeper space

Phase 2 (after the invariants above are green). Keepers change what the market can take:

- **Effective ADP.** `adp'(p) = adp(p) - #{keepers q : adp(q) < adp(p)}`, over every keeper in the
  table, logged or still to come (a keeper dropped on a room conflict leaves the count; decided
  2026-10-06: counting only pending keepers would move every later player's `adp'` by one at the moment
  a keeper slot is logged while `m(now)` stays put). `effective_adp()` returns `adp'` when keepers
  exist (`adp_source` unchanged). Board rows carry `keepers_ahead` and `adp_eff`; `adp` stays Yahoo's
  number on rows and candidates ("ADP 52 → 49" on the board); the summary carries the count.
- **Market picks.** `m(k) = k - #{keeper slots s : s < k}`, over the same keepers. `availability()` calls
  `conditional_availability(adp', now=m(next_overall), picks=[m(k) for k in my_remaining_picks])` and
  the league table likewise, so the normal model and the league table are read in market space.
  Simulated and file survival tables (`survival: simulate | file`) come from drafts that include the
  keepers and stay keyed by real overall pick. The simulators (`autopick.latent_slots`, the survival
  build's drafters) use the session's spread too: one spread for model and simulation.
- **Spread.** The league's robust sd of pick minus ADP is about `0.9 + 0.136*ADP`; the product's
  `spread_for_adp` is `3.0 + 0.15*adp` (2.7x too wide at ADP 1-12, right from ADP ~60). Make `base` and
  `growth` settable on the state and expose them on `SessionCreate` (`spread_base`, `spread_growth`).
  **Decision (master, 2026-10-06): default `spread_base` 1.5, `spread_growth` 0.15 unchanged**, for every
  session (the archive is this league; mock rooms are a test bed). Evidence, keeper-adjusted space,
  nine seasons: MAE of S(market pick | effective ADP) for ADP <= 84 falls from 0.0124 (3.0 + 0.15) to
  0.0096 (1.5 + 0.15); the PIT deciles lose the mid hump (0.17 peak -> 0.14) with the |z| > 2 share at
  0.065 against a nominal 0.046, while the robust fit 0.9 + 0.136 under-covers the tails (0.103) and the
  censored MLE 0.5 + 0.265 is far too wide late (MAE 0.021). Scan: `data/scratch/spread_scan.py`.
- **League survival table.** `data/yahoo_history/survival_by_adp_adjusted.csv` is S(market pick |
  effective ADP) for this league, 2017-2025, keepers removed, with an `undrafted` column; a player never
  drafted survives every pick (the `SurvivalTable` convention, regenerated 2026-10-06), so S never
  rises with m and S(m) >= undrafted in every row. A `survival: league` option reads such a table
  (header `adp,1..N,undrafted`, integer ADP rows 1..160, columns 1..157; anything else is a 400 naming
  the problem), interpolates between integer rows, floors each row at its `undrafted`, falls back to
  the normal model for `adp'` outside the rows, and reads conditionally as S(m)/S(m_now) clipped to
  [0, 1] with the normal model's floor. **Hybrid (decided 2026-10-06):** the table answers only for
  `adp' >= 90`; below that the normal model (1.5 + 0.15·ADP) answers, through the same fill-in. The
  leave-one-season-out MAE of S by bucket is 0.015 normal vs 0.047 kernel at ADP 61-84 and 0.074 vs
  0.078 at 85-108 (the kernel's smoothing blurs sharp early survival), but 0.098 vs 0.034 at 109-132
  and 0.077 vs 0.049 at 133-156, where the normal has no undrafted mass (P(undrafted | adp') is 0.22
  at 90, 0.39 at 100, 0.54 at 110). The real draft runs `survival: league` with the archive table;
  mock rooms (no keepers) keep `simulate`. The table is league data (gitignored); the loader is product
  code and gets a small fixture in the same shape.

## 2. API (`api/app.py`)

```python
class KeeperIn(BaseModel):
    position: int | None = Field(default=None, description="draft slot; None = my position")
    round: int = Field(ge=1)
    player_id: str | None = None        # projection id (name slug)
    player: str | None = None           # or a name, resolved with normalize_name like ADP

class SessionCreate(BaseModel):
    ...
    keepers: list[KeeperIn] = Field(default_factory=list)
    keepers_file: str | None = None     # CSV inside data/: position,round,player ("me" allowed)
```

- `_build_state` resolves names to ids (unknown name, duplicate player, two keepers on one slot,
  round > roster_size, position out of range: HTTP 400 with the offending row). Keepers land in
  `session.create_params`, so a room rebuild after an API restart keeps them.
- `GET /sessions/{id}` summary adds `keepers: [{position, round, overall, player_id, team, mine,
  applied}]`, and `my_picks` now means draftable picks; add `my_slots` for the full snake list.
- `PATCH /sessions/{id}/keepers` replaces the keeper table for slots not yet reached at any time (409
  only for an applied keeper, which only the room's conflict path can change). This is what the user
  fills in on draft night when the order is drawn and the other teams' keepers are visible on the
  board, and the manual way out of a wrong entry in a practice session.
- `GET /sessions/{id}/board` rows carry `keeper: team | null`; a keeper row is `taken`.
- `POST /sessions/{id}/picks` and `/sync` behave per invariant 7; `_pick_row` carries `keeper: bool`;
  `/autopick` and `league_sim` fill keeper slots through the invariant without code of their own (add a
  test that proves it).
- Room (`api/yahoo_room.py`, done in #31): `attach_room` calls `set_my_position(slot)`, so `position=None`
  keepers follow the seat; `_walk` applies invariant 7 both ways (`replace_pick` at a keeper slot the room
  fills with someone else, `drop_keeper` for a keeper still to come whom the room records elsewhere), lists
  the dropped entries in `keepers_dropped` and never uses a pending keeper as a stand-in. Keeper picks the
  session logs from its table are `session_pick` `kind: keeper` / `src: keeper`, published with
  `source: keeper` and no lag. Insurance for a room that never sends a keeper's pick: `_walk` steps over a
  ledger gap at a logged keeper slot, `synced_through` counts those slots and a late room pick there is
  `held` or a `conflict`. A `room_pick` of the keeper at his slot carries `src: keeper` and `via`
  (socket | history), which settles on the night how Yahoo sends them; `waiting_for` ignores keeper picks
  sent ahead. The room summary and the attach record list the keeper slots (`keepers`).
- Fidelity (done in #31): `fidelity/scorecard.py` leaves my keeper slots out of the compliance denominator
  and the per-pick rows (`my_keepers`), counts keeper picks the room never sent towards G1
  (`kept_unseen`), leaves keeper slots out of G2, and treats a keeper pick logged before the attach as
  synced from the start; `fidelity/replay.py` takes `keepers="socket" | "history" | "none"` for the three
  ways a room may send keeper picks. Event fields in `docs/YAHOO_SYNC.md` §4.
- Extension (`extension/lib/room.js`, `content.js`, done in #31): the tracker takes the keeper slots from
  the room status; `mine`, `isMine`, `myTurnNow` and the on-deck turn leave my keeper slots out, so a `D|`
  frame for my slot at a keeper overall arms nothing; `contiguous()` steps over keeper slots; a keeper
  slot's `turn_start` carries `keeper: true`.
- Unknown keeper (`feat(keepers): gap stand-in`, #34, merged 2026-10-06 as bd3be28). A keeper the table
  does not know about leaves a gap in the room's ledger at his slot k: no room pick, k not a logged
  keeper slot, and the walk stalls there, parking every later pick and leaving the plan on a stale board.
  Rules: the room keeps the API time it first saw each overall put on the clock (a `turn_start`) or
  picked live (a room pick with src `socket`); a gap is evidenced by any such later overall. A history
  frame is not evidence: Yahoo may send every keeper's pick at connect, and a keeper pick at 31 must not
  evidence gaps at 1-30. Gaps start at `synced_through + 1` and are never a keeper-table slot. After
  `GAP_MARGIN_S` (4 s: a false fill is cheap, a late fill costs a stale board at my turn) the room
  writes a ledger entry `RoomPick(k, yid=None, slot=owner, src="gap", evidence=j)` and the walk fills
  it with a stand-in (never a pending keeper), or holds whatever the session already has there. The
  check runs on picks ingest, on the events POST and from a `loop.call_later` scheduled at first
  evidence (no side effect on GET; a GET fallback is acceptable if the loop handle is awkward, said in
  the PR). A real pick for k arriving later replaces the gap entry as a `repair` (not a conflict,
  outside the lag stats). A gap at one of my own slots gets the same stand-in on my roster. The user's
  way out: `PATCH /sessions/{id}/keepers` may add a keeper at a reached slot whose pick is a gap
  stand-in (the one exception to "slots not yet reached"); the stand-in is replaced by the keeper
  (`session_pick` kind `keeper_fix`, published with `replaced`) and he leaves the board. Web: the
  stand-in's rows carry a "?" marker ("unknown keeper at pick k, Team N round r: add him to the table")
  that opens the Log card editor with a row pre-filled with that position and round. Fidelity: `gaps`
  counted and listed like `kept_unseen`, part of completeness; an unfixed gap counts against G1, a
  fixed one counts as a keeper slot (out of my turns if mine); gaps are out of G2 and of my-turn rows.
  Extension: `contiguous()` also counts overalls at or below the API's `synced_through`; no protocol
  change. Tests in the PR: skip k then k+1..k+3 with turn_starts (nothing before the margin, then the
  stand-in and the rest), a racing events POST, a late real pick as repair, a held session pick,
  PATCH at a gap slot, rebuild from the log, the scorecard counts and G1, a replay with a gap at a
  slot of mine fixed mid-draft ending 156/156 green, and the extension's `contiguous()` with `sent`.

## 3. Web (`web/src`)

- `SessionSetup.tsx`: a "Keepers" block, one row per keeper: team (Me / slot 1..N), round, player
  (typeahead over the projection names, as the ADP warning already lists them). Rows pre-filled from
  `keepers_file`, each with a checkbox (my own keepers off until the user decides) so practice sessions
  are two clicks. A "paste from Yahoo" textarea that accepts `slot, round, name` lines
  is enough for draft night.
- `LogCard.tsx`: keeper picks marked `K`; "N of 156 picks" unchanged.
- `PlanCard.tsx` pairs `pastPicks[i]` with `my_roster[i]`; with keepers in `my_roster` it must pair by
  overall: use the summary's `keepers` and `my_slots`.
- `TeamCard.tsx`: keepers shown on my roster from pick one with the round they cost.
- `Board.tsx`: keeper rows hidden with `taken`, a filter toggle "show keepers".
- Top bar: when `next_overall` is a keeper slot the pick announcement says "Keeper: <team> keeps
  <player> (R7)".

## 4. Tests to add

- `tests/test_draft_state.py`: keeper at overall 1 is applied at construction; `taken` holds future
  keepers; `my_picks` has 11 entries for two keepers; `horizon_problem` builds (no "remaining picks"
  error) and locks both keepers; `apply_pick` at a keeper slot with another player raises; reaching a
  keeper slot appends the keeper; undo semantics; `replacement_level` window shifts.
- `tests/test_autopick.py`, `tests/test_league_sim.py`: a full simulated draft with keepers on three teams
  gives every team 13 players, keepers at their rounds, no keeper drafted elsewhere.
- `tests/test_api_keepers.py` (#29, #31): create with `keepers`, summary shows them, board marks them,
  sync of a Yahoo feed that includes the keeper pick at its slot is idempotent, the feed attach relabels
  my logged keeper pick and refuses another seat with a 400.
- `tests/test_yahoo_room.py` (#31): a conflicting room pick at a keeper slot is logged as `conflict` and
  the keeper entry is dropped (both directions); Tier 1 replay of room 2515267 with three keeper slots
  (two picks moved to the owner's earlier round, one kept in place so my last two picks are back to
  back) in the socket, history and none forms, compliance excludes my keeper rounds, G1 green in all
  three.
- `tests/test_presolve.py`: `branch_boards` across a keeper slot (my next pick two away, the pick in
  between a keeper) yields the right boards.
- Phase 2: `conditional_availability` in market space equals the unadjusted call when there are no
  keepers; `adp'` ranks; the league table loader rejects a table whose columns do not match.

## 5. Practice plan (fantasyMOCK, local only)

1. API + web on the launch.json servers; session with `keepers_file: keepers_practice_2026.csv`
   (local, supplied by the master: my two keeper candidates and 14 plausible keepers for the other
   slots, drawn from `adp_yahoo_31822.csv` with the historical discount), `survival: simulate`, slot 6.
2. `POST /autopick` to my first pick; check the Pick card shows 11 planned picks and both keepers on the
   Team card; draft the recommendation; repeat to the end. Expected: the plan never recommends a keeper,
   the keeper rounds pass with a "Keeper" announcement, the final roster has 13 players.
3. Repeat from slots 1 and 12 (back-to-back picks around keeper slots).
4. Scorecard on the tracker issue: picks planned vs made, any 400 from the API, solve times (keeper
   mode changes nothing in the MILP size, so the 30 s design point must still hold).
5. Consistency runs (from run 6 on): the Sim bar by ADP (the default since #35) with "normal"
   randomness, so the other teams draft as the availability model assumes (market ADP with the session
   spread) and the E[cats] trajectory is a consistency check. No seed: the web has no seed control, the
   API re-seeds per Sim call, and my own picks differ between runs anyway, so runs are compared on
   their trajectories, not their boards. The `z` strategy (the default for runs 1-5) ignores ADP, so
   its trajectory says nothing about the league's spread.

Results (2026-10-06, main 0f69468 for slot 6, 28b940b for slots 1 and 12, then bb20d2a with #32; all with the practice
file, `survival: simulate`, the top candidate drafted every turn):

| slot | keeper picks applied | planned = made | max solve | capped | E[cats] | notes |
|---|---|---|---|---|---|---|
| 6 | 78, 150 | 11/11 | 23.4 s | 0 | 4.97 → 5.18 | announcer silent at 139, Plan card stuck after 156 |
| 1 | 73, 145 | 11/11 | 30.6 s | 4 of 11 (rounds 2-4) | 5.31 → 5.60 | keeper right after my pick 72; 96/97 back to back handled |
| 12 | 84, 156 | 11/11 | 25.3 s | 2 of 11 | 4.95 → 5.05 | draft ends on my keeper; completion fired from the fill |
| 12 (confirmation, b1c8fa9 + #32) | 84, 156 | 11/11 | 25.1 s | 0 | 5.10 → 5.24 | done state on every card between 133 and 156 and at completion; announcer replayed 118-156 once each; history rows name the drafted players |
| 12 (phase 3, d7fa029, `survival: league`) | 84, 156 | 10/11 (one deliberate tie pick at 61) | 21.3 s | 1 | 5.16 → 4.79 | mechanics all pass (market-space board column, league source text, history hover); E[cats] fell during the other teams' sims for the first time: the local sim's z and roster drafters ignore ADP, so a model calibrated to the league's ADP noise (1.5 + 0.15) is optimistic against them; not evidence about the league, see the note below |

Note on run 5: the first four runs rose during the draft because the old spread (3.0 + 0.15) was
pessimistic against the local sim, so targets survived more than planned; run 5 fell (−0.37, all of it
during the other teams' sims, none at my picks) because the fitted spread expects the league's ADP
discipline while the local drafters (z, adp and roster-model mix) do not follow ADP. The archive is the
evidence about the league; the practice sim is not. Like-for-like practice comparisons need the other
teams drafted by the `adp` strategy with the session spread and a fixed seed (§5 item 5).

No keeper ever appeared in the candidates, the plan or the draftable board; keeper picks were
announced mid-draft and shown as kept on the Team, Log, Plan and Board cards. Defects, all UI or
stream, none in the keeper model: the announcer gap was the event stream's 120 s cap dropping a burst
with no replay (fixed in the endgame PR with drain and replay); the Team card history named the
plan's player, not the one drafted, and its "now" score could lag a solve; the Plan and Pick cards wait
for a solve past the last pick after completion; the K badge sits against the name. Capped solves came
from the instant sim leaving no pre-solve window, not from keeper mode. A "Team N" row in the practice
file whose N is my seat is a collision (slot 1 and slot 12 runs): the editor folds it into "Me".

## 6. Order of work

1. Invariants 1-10 in `DraftState`, `autopick.team_roster`, `league_sim.draft_once`'s guard and
   `presolve.branch_boards`, with tests; `undo()` and `drop_keeper()` as state methods (one PR,
   `feat(keepers): draft state`, branch `feat/keepers-state`; agreed with the emissary 2026-10-06).
2. API fields, summary, PATCH, undo, board flag, autopick/sim test (`feat(keepers): api`).
3. Web setup block, log/plan/team cards (`feat(keepers): web`).
4. Room: fidelity `src: keeper`, scorecard denominator, extension turn guard (`feat(keepers): room`,
   #31, merged 2026-10-06 as 28b940b; #28, #29 and #30 are steps 1-3, all merged the same day).
   From the practice runs: #32 (merged 2026-10-06 as b1c8fa9) fixed the event stream (drain at the
   cap, replay from `Last-Event-ID`; the silent announcer), the cards' done state after my last pick,
   the Team card history (named by the pick made, score recorded only for the recommendation shown)
   and the editor's fold of the team at my pick into "Me".
5. Phase 3 availability (`feat(keepers): market-space availability`, #33, merged 2026-10-06 as
   d7fa029): effective ADP and market picks over every keeper in the table, `spread_base` 1.5 /
   `spread_growth` 0.15 shared with the simulators, `survival: league` with the table answering from
   ADP 90. The overall-space archive table is kept two folders down so only the adjusted table is
   listed (`/files?kind=league` reads data/ and one folder down).
6. Follow-up (#34, merged 2026-10-06 as bd3be28): a keeper the table does not know about (§2), with
   three small items: no default league table when several are listed, `_in_data_dir` on `survival_file`
   for the file and league modes, and the web's mirrored constants naming their Python source. #35
   (merged 2026-10-06 as 74f20e7) makes "by ADP" the Sim bar's default strategy (§5 item 5).

Issues (filed 2026-10-06 after the merges, at the user's request, so the history matches the yahoo-sync
tracker #11; league data stays out of them, as everywhere): tracker #47; one issue per step, closed by
its PR: #36 (#28 state), #37 (#29 api), #38 (#30 web), #39 (#31 room), #40 (#32 stream and endgame),
#41 (#33 availability), #42 (#34 gap stand-in), #43 (#35 Sim default). Open follow-ups: #44 (two
timing-dependent tests), #45 (API autopick default still `z`), #46 ("Re-planning" seen once, watch item).
