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
   wins on a genuine conflict: `_walk` replaces the pick in place as it does today and logs `conflict`,
   because the Yahoo record is the truth and the keeper table was wrong; the keeper entry is then
   dropped from the table and the event says so.

### 1.1 Availability in keeper space

Phase 2 (after the invariants above are green). Keepers change what the market can take:

- **Effective ADP.** `adp'(p) = adp(p) - #{keepers q : adp(q) < adp(p)}`, computed over the keepers not
  yet in the log. `effective_adp()` returns `adp'` when keepers exist (`adp_source` unchanged, add
  `adp_keepers_ahead` to the summary for the UI).
- **Market picks.** `m(k) = k - #{keeper slots s : s < k}`. `availability()` calls
  `conditional_availability(adp', now=m(next_overall), picks=[m(k) for k in my_remaining_picks])` and
  the survival table likewise, so the normal model and a league table are read in market space.
- **Spread.** The league's robust sd of pick minus ADP is about `0.9 + 0.136*ADP`; the product's
  `spread_for_adp` is `3.0 + 0.15*adp` (2.7x too wide at ADP 1-12, right from ADP ~60). Make `base` and
  `growth` settable on the state (`spread_base`, default 3.0 for now) and expose them on
  `SessionCreate`; the master will set the practice default after a keeper sim comparison (candidate
  1.5).
- **League survival table.** `data/yahoo_history/survival_by_adp_adjusted.csv` is S(market pick |
  effective ADP) for this league, 2017-2025, keepers removed, with a `undrafted` column. A
  `survival: league` option that reads such a table (rows ADP 1..160, columns 1..157) and looks players
  up by `adp'` gives the late rounds their real undrafted mass. The table is league data (gitignored);
  the loader is product code and gets a fixture.

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
- `PATCH /sessions/{id}/keepers` replaces the keeper table before pick 1 only (409 once picks exist;
  the room's conflict path handles the rest). This is what the user fills in on draft night when the
  order is drawn and the other teams' keepers are visible on the board.
- `GET /sessions/{id}/board` rows carry `keeper: team | null`; a keeper row is `taken`.
- `POST /sessions/{id}/picks` and `/sync` behave per invariant 7; `/autopick` and `league_sim` fill
  keeper slots through the invariant without code of their own (add a test that proves it).
- Room (`api/yahoo_room.py`): `attach_room` keeps `position=None` keepers on the new slot; `ingest` and
  `_walk` need no change beyond invariant 7's conflict handling. Record keeper picks in the fidelity log
  with `src: "keeper"` and exclude my keeper rounds from compliance's denominator
  (`fidelity/scorecard.py` uses `snake_picks` for "my turns"; `fidelity/replay.py` the same).
- Extension (`extension/lib/room.js` `mine`, `content.js takeTurn`): a `D|` frame for my slot at a keeper
  overall must not arm a draft attempt. The room's keeper overalls come from the attach response.

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
- `tests/test_api.py`: create with `keepers`, summary shows them, board marks them, sync of a Yahoo feed
  that includes the keeper pick at its slot is idempotent, a conflicting room pick at a keeper slot is
  logged as `conflict` and the keeper entry is dropped.
- `tests/test_yahoo_room.py`: Tier 1 replay fixture with two keeper slots (synthesised from an existing
  board file: move two picks to the owner's earlier round and mark them keepers), compliance excludes my
  keeper rounds.
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

## 6. Order of work

1. Invariants 1-7 in `DraftState` with tests (one PR, `feat(keepers): draft state`).
2. API fields, summary, PATCH, undo, board flag, autopick/sim test (`feat(keepers): api`).
3. Web setup block, log/plan/team cards (`feat(keepers): web`).
4. Room: fidelity `src: keeper`, scorecard denominator, extension turn guard (`feat(keepers): room`).
5. Phase 2 availability (`feat(keepers): market-space availability`), after a master decision on the
   spread base from the practice runs.

Issue numbers follow once the user approves filing them (the repo is public; league data stays out of
the issues, as everywhere).
