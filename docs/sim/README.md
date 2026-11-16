# SEASON SIM: a standalone whole-season simulator

Tracker #172. The simulator plays whole fantasy seasons, from the draft to the final, on recorded
NBA seasons: a made-up twelve-team league is drafted on a forecaster's projection and played
through a recorded season's game lines, the engine's own code deciding each seat's moves, and the
league scores the weeks, the standings and the bracket. It is standalone (the user's ruling of
2026-11-07): it reads no live league, writes no knob file and is no part of a live decision. A
**path** in a replay varies only in its seats (which arm sits where), in the told return dates
of the absences, in a market rival's draw and in an oracle forecaster's draw; the season's games
are the same on every path. A run is a **room** (the arms rotated around the table, `--seats`) or
a **pair** (arm A and arm B in one seat in two seasons through one world, B less A, `--arms`),
on one or several recorded seasons and forecasters. The design study is the master's note in the
scratch repo; the user's rulings of 2026-10-23 amended it (five seasons behind the fit, no data
mining, projections taken as given), and those of 2026-11-07 made it standalone and whole-season.

## Where it lives

The simulator is its own package, `src/pickandroll/sim/`, beside the in-season engine
(`src/pickandroll/season/`), not inside it. Its tests are in `tests/sim/`, this doc in `docs/sim/`
and its fits and runs under `data/sim/` (local, as all of `data/`). The commands run as
`python -m pickandroll.sim <command>`. The direction of imports is held by a test
(`tests/sim/test_boundary.py`): nothing outside the package imports it; it reaches the engine
through `sim/engine.py` only, the whole list of engine code it calls as library code (the
engine's files are never edited from here); only `sim/readers.py`, `sim/gamelogs.py` and
`sim/cli.py` may import `pickandroll.sources`, and since the standalone cut none does; and the
simulator imports nothing from `pickandroll.api`: the test's list of such imports (`API_TIES`)
is empty, and a new one fails it. The same test reads the core (`world`, `state`,
`league`, `opponents`, `policy`, `run`, `fit`, `checks`, `validate`, `engine`, `belief`, `nopeek`,
`audit`, `counts`) for any way to a file, a process or the network: none of them imports
`pathlib`, `io`, `shutil`, `tempfile`, `socket`, `ssl`, `urllib`, `http`, `requests`, `httpx`,
`subprocess`, `sqlite3` or `pickle`, none calls `open`, and only `run.py` uses `os`, for the
worker count and the workers' priority. The policy and the opponents reach nothing of `run.py`,
directly or through another module: the world is never among a seat's inputs.

## The world (`sim/world.py`, `run.World`)

A replay's world is the recorded season (`run.replay_world`): the recorded lines are the truth of
every game, and a game day without a line is an absence. What a path draws, every draw seeded by
`(seed, path, player, game, stream)` so two arms of a pair see one world and a stream added later
moves no other draw: the told return date of an absence (the `news` stream), a market rival's
moves (`market`) and an oracle forecaster's error (`error` and `forecast`: `world.errors` and
`world.true_rates`, the realized rate times `e^ε` a stat at a time; **The forecasters**). The
streams keep their numbers, those of the removed layers included.

**Beliefs** are what the policy decides on, never the truth: the forecaster's projection updated
each day with the games already played (the causal belief, **The replay: what a seat knows**),
and an absence heard only `lag` days after it began, with a told return date.

The drawn world went with the standalone cut (**What was removed and when**): a persistent error
on the projection shrunk toward a market view, game noise around the erred rate with a fitted
dispersion and minutes factor, absences from a fitted hazard, and a weekly refresh of the beliefs.

## The fit (`sim/fit.py`, `sim/gamelogs.py`, `sim/cli.py`)

ESPN's player view serves per-game logs for whole seasons, one request a season (`fetch-logs`),
cached under `data/external/espn/gamelogs/` and never committed. The fit (`fit`) estimates, per
season: the residual dispersion of each stat after the minutes factor (pooled, and per player
with thirty or more games, shrunk to the pool), the minutes factor's spread, the absence hazard
and its run-length mixture (runs before a player's first game are dropped, a run still open at
his last is censored). Games under five minutes are dropped and each player's share of them is
kept. Seasons are compared on the hazard and the
minutes spread and pooled where they agree within a fifth; a season that disagrees is kept apart
under its own id. The result is frozen as `data/sim/fit/<date>/fit.json` with its
SHA-256 beside it, naming every parameter and the hold-out season.

**What a run reads of the frozen fit** (`run.inputs_of`, since the standalone cut): the days
before an absence is heard (`lag`: the fitted refresh's when one is frozen, else the defaults',
else 1), the hold-out season and the file's hash, which every run records. The dispersions, the
minutes spread, the hazard and its mixture are still estimated and frozen by `fit` (`fit.py` is
unchanged) but no run reads them: they were the drawn world's. A frozen fit with or without `tau`
loads alike.

**The hold-out** is 2024-25 (ESPN season id 2025): the `fit` command refuses to fit on it, and a
replay and `validate` refuse to play it. **No data mining**: the fit is made once
and frozen; every comparison is one pre-registered A against B with its seed; the simulator never
proposes a change and writes no knob file. The frozen fit's figures stay under `data/` and are
described in words anywhere public.

## The league (`sim/league.py`)

Weeks are scored as the record scores a real one: percentages from makes and attempts to Yahoo's
three decimals, the lower turnovers winning, a tie half. Standings order by win percentage, then
a parameterised tiebreak (total category wins, then head to head; the settings page does not print
the regular season's rule). The bracket seeds the top `playoff_teams` with the byes the rounds
need (`2^rounds − playoff_teams`), reseeds each round or plays the fixed bracket as the league
does, and sends the higher seed through a tie. A points league scores on the weighted points.

A replay's league is made up, so its bracket is the replay's own: the top six of twelve over the
last three weeks, the byes the rounds need, reseeded, the higher seed through a tie
(`run.replay_setup`). `LeagueSpec.from_settings` builds a spec from a league's settings and
refuses (`BracketUnread`) one with divisions or a tie-breaker the bracket does not play; since the
standalone cut no command reads a league's settings, and a run without a spec writes no playoff
odds and reports rank and category wins only.

## The gates (`sim/validate.py`)

`validate` is gate 5 alone: the surrogate's set equal to the exact set on four of five sampled
league-days, for seats 1, 6 and 12, on a replay of a recorded season (**The gates as they stand**).
Gates 1 and 4 tested the drawn world (team-week totals and missed games under its noise and its
hazard) and went with it; gates 2, 3 and 6 read a live league's recorded weeks, scorecard and
exports (**What was removed and when**).

## The state and the policy (`sim/state.py`, `sim/policy.py`)

A **setup** is one league as a run starts it: the calendar and pairings, the twelve rosters, the
free agents, the shared projection, the schedule, the statuses and return dates on day one, the
market's view and rate, and the bracket. A **state** is one arm's position on a day: rosters, pool,
adds used this week, the moves queued to land tomorrow and every week's totals so far. Beliefs,
lines, absences and news belong to the world and are shared by every arm; two arms whose states
agree share one solve.

The policy is the engine's own code on that state. `problem_of` builds the live moves route's
`MoveProblem` from the setup and the state, in memory, as `api.season_moves.build` builds it from a
live league's recorded season: the week against the pairing's opponent, three weeks against the
field, the free agents landing tomorrow, the weekly add limit net of the adds made, the keep rule,
the protection floor, the plan floor and the daily cap from the knobs (every one of the twelve is
checked against the engine's own bounds; a missing knob is refused, below **The knobs**). Three
tiers decide on it. **Exact** is the live route: single swaps on every candidate, the recommended
set on the three-week horizon with the season guard, the streaming plan beside it (or the strategy
route's weighted set when the arm executes `weighted`). **Surrogate** is the same evaluator on the
arm's `pool` (thirty by default) best candidates by value times games this week, the greedy search
alone, on the arm's `surrogate_days` (Mondays and Thursdays by default). **Ranking** swaps the
pool's best for the roster's worst the keep rule does not keep, when it gains, with no evaluator.
The executor lands yesterday's queue team by team in a rotating order. First its return rule: a held
player whose status no longer fits his slot comes back to the bench that morning and, while the
active roster is then over the league's spots, the least valuable active player by the day's value
goes to the pool, the returning player included (counted as a forced drop; the keep rule stays out
of the executor). Then a churn's held drop goes first, on his own, the held-slot moves a set needs
are made, and the adds land: a drop goes to the pool and the add takes his slot, an add that needs
an active spot takes a bench slot or is gone when none is open, an add another team took first is
gone and counted. A queued move is carried out against the day it lands: a held-slot move is made
only while the slot has room and accepts the status the player has that morning (`moves.eligible`,
the engine's own test). A player queued for IL while he was out whose status has cleared overnight
stays active and the move is refused (counted in `held_refused`); it frees no spot, so an add that
needed it meets the same check and is gone when no spot is open. The alternative, honouring the
status of the day the move was decided and activating him the same morning (the add lands and the
weakest active player is dropped), was not taken: it breaks the executor's one rule. Every add is a
free agent landing the next day (`EXECUTIONS = "free_agents_next_day"`): no waiver clear dates, no
bids, the caps the autopilot's. An add is charged to the week of the day it is made, as Yahoo
charges a free agent, never the week it lands in: one made on Sunday spends the ending week's adds
and plays from Monday, and Monday's count starts over only once it is in. Each day's starters are
the most valuable set the slots hold among the players whose team plays and whom the policy has not
heard are out; their lines are the week's totals.

## The knobs, the fields and the season term (`sim/policy.py`, PR C)

**Twelve knobs.** An arm's spec names every knob: the engine's ten live ones
(`season.progress.LIVE_KNOBS`, read through `sim/engine.py`) and the simulator's two.
`policy.check_knobs` refuses a missing knob, a name that is not one, and a value outside the
engine's own bounds (`progress.refused`), naming the knob and the reason:

| knob | kind | bounds | default |
|---|---|---|---|
| `system` | choice | `bbm`, `yahoo`, `blend` | `bbm` |
| `blend` | number or None | 0.25 to 0.75 | None |
| `horizon_weight` | choice | `even`, `natural`, `season` | `natural` |
| `protection_floor` | number | 0 or more | 0 |
| `plan_floor_cats`, `plan_floor_points` | number | any | 0.10, 0.01 |
| `stash_threshold` | number or None | 0 or more | None |
| `faab_sizing` | any value or None | none (the engine checks nothing) | None |
| `daily_cap` | whole number | 1 to 3 | 2 |
| `three_weight` | number | 0 to 1 | 0.33 |
| `season_weight` | number | 0 or more, finite | 0 |
| `playoff_weight` | number | 0 or more, finite | 1 |

None stays a value only where the engine's default is None (`blend`, `stash_threshold`,
`faab_sizing`); anywhere else it is refused. Gate 5 runs at the twelve defaults
(`policy.KNOB_DEFAULTS`); no knob file is read.

**Four fields.** An arm may also name four fields of its own, on the arm and on its seat
(`policy.Fields`, in the seat's repr, so two seats that differ in one never share a solve):

- `pool` (30, a whole number, 1 or more): the candidates the exact tier's recommended set and
  week plan search, the weighted search's, and the surrogate's best by value times games;
- `min_gain` (0.01, a number, 0 or more): the least gain a candidate or a set must make, on the key
  the arm executes and with the season term when it is on, so it is the combined figure's;
- `weeks_ahead` (4, a whole number, 2 or more): the weeks a problem looks ahead, this one included;
  the "three weeks" horizon is the `weeks_ahead − 1` after it (fewer near the season's end), so a
  gain on it, and what `min_gain` asks of one, grows with `weeks_ahead`;
- `surrogate_days` (Monday and Thursday, a non-empty set of weekdays 0 to 6): the days the
  surrogate solves.

A mirror rival takes the arm whole, knobs and fields. Every payload records the four fields of
every arm and, under `surrogate`, the surrogate's pool and days as the arm sets them; gate 5's
check (`checks.surrogate_matches`) takes the arm's. Nothing in the engine that the moves route
reaches assumes exactly three later weeks.

**The season term.** At `season_weight` above 0 an arm's score on the key it executes gains
`season_weight × ROS_w(moves)`. A player's `worth_w` is his season value above a dead spot (the
keep rule's per-game figure, `season_value − dead`) times his team's games from the day he counts
from to the season's last day, a game in one of the bracket's weeks counted `playoff_weight` times.
He counts from the move's day, or from his return when that is later (`moves.back_from`); one who
does not return this season is worth 0, one without a season value has none. A move's `ROS_w` is
the add's less the drop's (the add's alone without a drop; none when either has no value, and
that move counts 0); a set's is the sum. The games are the schedule's and none is extrapolated: a
league's schedule reaches the season's last day (the reader refuses one that does not). A replay's
schedule is the season's log: a day with no entry has no game (an off day for the whole league,
and in the synthetic logs every day after the log ends, before the replay's calendar does), and
there the engine's own figures extrapolate games the term does not count. So the unit is per-game value times games, the unit of the stash threshold
(#373): at `playoff_weight` 1 a healthy player's `worth_w` is `moves.worth_from` and an absent
one's `moves.net_of_return` wherever the schedule keys every day. The season guard's figure
(`decisions.move_projection`'s season horizon) is also per-game value times games, but it counts
every game once and extrapolates past the schedule read; the term does not touch it.

The term is a wrapper (`policy.Seasoned`, the engine's evaluator shape) that adds it on the
executed key only; at `season_weight` 0 it is never built, so every decision is the engine's as it
was. It enters the exact tier's single swaps, the candidates' ranking for its set and the
recommended set (`three`), the weighted search's key (`weighted`), and the surrogate's search. It
does not enter the ranking tier, the week plan (the streaming plan stays the engine's, PR E), the
season guard, or the stream's spots.

**The season scale.** On each path's first simulated day, in the arm's own seat, the payload takes
each candidate's best single swap over the arm's pool on the executed key, without the term, and
records four figures: `gain`, the median of their gains; `ros`, the median of their `ROS_w` at
the arm's `playoff_weight` (both signed); `ratio`, the median size of the gain over the median
size of `ROS_w`, over the swaps that have a `ROS_w`, 0 or more by construction: the
`season_weight` at which the term is the week gain's size; and `against`, the share of those
swaps whose `ROS_w` is below 0, where the week's best swap costs season value (PR C2: the ratio
was the signed medians' quotient, which flips sign or blows up when the season figures straddle
zero). It is recorded per arm (`season_scale.by_arm`: the mean over paths of each figure, and how
many paths gave one) for every replay, at any `season_weight`, 0 included; null on
the ranking tier and a static seat. A dry run prints the four. It draws nothing, changes no
outcome and is no part of a solve.

**What each knob reads.** `policy.reads(arm, shape)` says for each knob `read` (a different value
can change what the seat queues in a league of that shape) or why not; a change that only alters
what is recorded, such as a plan drawn and not executed, is not read. The shape is the league's
scoring, whether it has held slots, whether its bracket is read and whether the run names the two
sources' stand-ins (below). A rival that mirrors the arm reads what the surrogate reads, but
believes by the run's forecaster: `system` and `blend` are read by the arm's own seat only. As
built:

| knob or field | read by | otherwise, and the PR that makes it read |
|---|---|---|
| `protection_floor` | any seat that moves (exact, surrogate, ranking) | a static seat makes no move |
| `daily_cap` | exact, surrogate | the ranking tier queues one move a day, under any cap |
| `horizon_weight` | exact executing `weighted` | any other arm |
| `plan_floor_cats` | exact drawing and executing the week plan, categories | any other arm or league |
| `plan_floor_points` | the same, points | any other arm or league |
| `season_weight` | exact, surrogate | the ranking tier holds no odds |
| `playoff_weight` | `season_weight` above 0 on exact or surrogate, bracket read | no term, or no bracket |
| `three_weight` | nobody | the queue's rule, PR E |
| `system` | the arm's own seat, on a replay that names the two sources' stand-ins | a run without stand-ins |
| `blend` | the same, when the arm's `system` is `blend` | no stand-ins, or another system |
| `faab_sizing` | nobody | no waivers and no budget in the world, PR F |
| `stash_threshold` | nobody | the engine reads it (#373); the simulator passes it, PR G |
| `pool`, `min_gain`, `weeks_ahead` | exact, surrogate | the ranking tier |
| `surrogate_days` | surrogate, or a mirror rival | the exact tier decides every day |

Every replay payload carries the table per arm per league shape (`reads`). A replay refuses
two arms that differ only in knobs and fields that neither reads
in any shape of the run: they are the same seat, and the message names each such knob, why it is
not read and what would read it. Two arms alike in everything are a check that the difference is
zero and run.

## The other seats (`sim/opponents.py`)

The ladder from the design note. **Static** makes no move. **Market** moves on a day with the
setup's rate (a replay records none, so a market rival names its `rate`) and takes the pool's best
by the market's view for its weakest by the same view, within the caps; on a replay the view is the
run's forecaster's draft-day ranking, or under a table of average draft positions the table's
(PR D4a). **Mirror** runs the surrogate on the shared beliefs. **Seat**
is a named arm in another seat: the equal room's opponent.

## The runner (`sim/run.py`)

One **world** a path, a replay of a recorded season: the recorded lines are the truth of every game
(no game noise, no hazard: the logs happened), a player's game days are his team's, a game day
without a line is an absence, and the world says what the policy has heard of each absence (an `O`
with the told return date, `lag` days after it began; a status read on day one stands until its
return). Every draw comes from `(seed, path, player, game, stream)` and never from an arm, so a
roster change in one arm reshuffles nothing: common random numbers. What its seats believe is below
(**The replay**): the causal belief, read every day from the games already played, one for each
forecaster a seat names. `simulate` can hand a caller a **day record** for each variant and day,
taken after the lineup is set and before the day's lines are scored: the beliefs, the statuses and
return dates heard, the moves that landed, each seat's decision, the queue, every team's starters
and the state.

`simulate` advances variants of one league through one world a day at a time: yesterday's queue
lands (a held player whose status has cleared comes back to the bench first and the roster is
trimmed to the league's spots, then a churn's held drop, the held-slot moves and the adds, an add
with no active spot gone), Monday resets the adds, each seat decides (a decision cached by team
and state, so arms in lockstep solve once), the day is played and scored; the season is then
scored by the league. `paired` runs arm A and arm B in one seat and returns each outcome (playoff
odds, rank, category wins, matchup wins, title) and their difference. **The difference is B less
A**: arm B's outcome less arm A's, path by path, so a positive difference is what B gains over A
in playoff odds, category wins, matchup wins and titles; rank is better when lower, so there a
negative difference is B finishing higher. `room` seats the arms given around the table, seat
`i` taking arm `(i + path) mod n` so every arm sits in every seat across paths. The process pool
is the simulator's own (cores less two workers at `nice 10`; the API's pools are untouched). Its
workers start by `spawn` on every machine: Linux's default, `fork`, copies a parent that has
already solved (each command runs its first task in the parent), and a HiGHS solve in such a
worker can spin for ever; a spawned worker is a fresh process, as on macOS by default.

**Determinism.** The same spec, seed and fit give the same outcomes in one process and across
worker counts, except at an exact tie: there an order-dependent sum in the engine's evaluator can
fall either way with the process's hash seed (a week plan whose gap over its set is 0.0 in one
process and 1e-16 in another, against a plan floor of exactly 0, is taken in one and not the
other). A real run sets `PYTHONHASHSEED=0`. The run record keeps the value (`hash_seed`, `"random"`
when it is unset), and replay and validate print one line on stderr when it is unset and the
run is not a dry run.

## The readers (`sim/readers.py`) and the runs (`sim/cli.py`)

The core is pure; the readers bring the inputs, from ESPN's cached logs and the frozen fit only. The
newest frozen fit is read with its hash checked against the file. A replay reads a season's log:
every player is his own team in the schedule, his game days his own entries, played or not, so a
trade or a team read later than the season moves nothing; scoring period `p` is the season's first
period plus `p − 1` days, the first periods verified against ESPN's scoreboard on 2026-10-24 (named
in every payload).

Each command runs as `python -m pickandroll.sim <command>`:

- `replay --seasons 2022,2023,2024 --forecasters prior,espn,marcel,oracle:0.1 --seats A.json
  B.json`: a made-up twelve-team league on each recorded season named (below), the arms rotated
  across paths, once for each season and forecaster that serves it (a **cell**; default
  forecaster `prior`). The hold-out anywhere in the list, a season named twice or a season with
  no log on file is refused by name before anything runs. Before any path each season is read on
  its own (its lines, the forecasters' figures, each label's weights, the league's shape) and the
  cells are printed as a table, seasons across and forecasters down: a forecaster that cannot
  serve a season leaves that cell skipped, with the reader's reason; a stand-in that cannot serve
  a season refuses the run by name (a system label cannot be built there); a run with no cell
  left is refused. The tasks are the served cells by the paths, and the estimate counts them;
  `--dry-run` runs the first task of the first served cell. `--shape stat|minutes` sets how an
  oracle's error is drawn (default `stat`). `--news-sd` sets the told return date's spread in
  days (default 2). `--no-peek YYYY-MM-DD` runs the no-peek check instead, on one season only and
  its first served forecaster, and writes nothing. `--bbm-as espn --yahoo-as marcel` names the
  two live sources' stand-ins, and each arm then believes by its `system` (below). `--adp espn
  --adp-spread <base>,<growth>` drafts the league on the season's table of average draft
  positions instead ("The draft market"); `--adp none` is the default. The payload
  (`replay_version` 6) keys by season what is one season's: the forecasters, the sources, the
  weights, the players, the shape, the results, the counts, the season scale and the unprojected
  count; `cells` says which were served and why the others were not, and `adp` what the league
  was drafted on.
- `replay --seasons 2022,2023,2024 --arms A.json B.json`: the paired design on a replay, arm A and
  arm B in one seat through one recorded season's world. A run names `--seats` (a room, as above) or
  `--arms` (exactly two spec files), never both and never neither. Each task drafts the league on
  its cell's forecaster as a room does, then puts arm A in seat `teams[path mod 12]` in one season
  and arm B in the same seat in a second, through one world in lockstep (`run.paired`), each arm
  believing by its own label; the eleven other seats are each arm's `opponents` block and believe
  the run's forecaster, whatever the arm believes. `--paths` is rounded up to a multiple of the
  league's twelve seats, and the command says so (20 becomes 24), so every seat is taken equally
  often in every cell. A replay records no market rate, so a `market` rival without a `rate` would
  never move: it is refused by name. A market rival's view is the run's forecaster's draft-day
  ranking, or under `--adp espn` the season's table (PR D4a, "The draft market"). A pair that is one seat by construction is refused by name, the knobs and
  fields it differs in listed with why none is read (**What each knob reads**); the same arm twice
  stays allowed (a check that the difference is zero). `--no-peek` checks the design the run names:
  with `--arms` it compares both arms' seasons' day records on path 0. The payload (`design:
  paired`) carries the seat rule and each path's seat, and per cell each arm's outcomes, the
  `difference` (B less A) with its standard error over the paths, the count of paths and how many
  are distinct (by the seat, both arms' metrics and their mechanism counts: the season's games are
  the same on every path, so paths repeat when nothing is drawn, and an SE over repeats is over
  copies), the counts by arm and for the rivals, each arm's season scale, the unprojected count by
  arm, and the rivals each arm faced with the line that they believe the run's forecaster. A dry run
  prints its first task's pair.
- **The pair's verdict, by forecaster and season** (`run.replay_verdict`, pure; `--arms` only, a
  room compares levels and gets none). Per cell, the paired change in every metric with its SE
  over the paths. Per forecaster, the pooled change: the mean of its season means, with the SE
  taken from those means (the seasons are the clusters); with one season it is that season's
  mean, without an SE, and says so, and it says "over k of n seasons" when a cell was skipped
  or left out. Two kinds of figure are shown and marked but not read by the rule: an oracle's
  row (`[y]`, a labelled yardstick) and an `espn` season whose projection fails the freeze check
  (`[f]`, left out of `espn`'s pooled figure too). The advisory rule (ruled 2026-11-07: no grand
  figure across forecasters) holds when the change in playoff odds is not below zero by more
  than one SE in any cell the rule reads and every forecaster's pooled change is above zero; it
  gives no verdict, with the reason, when the audit voided a path, a cell it reads has no SE, or
  no forecaster is left for it to rest on. No block and no promotion: the simulator never
  writes a live knob file. The command prints the table (a row a forecaster, a column a season
  and the pooled column, each figure in points with its SE, "n/a" for a skipped cell, the marks
  under it), then the notes and the verdict's line; the payload's `verdict` carries the same
  and every metric's pooled figure. The notes say, every time, what each SE is over (in a cell:
  the paths, that is the seats and the draws, not the season's own chance, one recorded season
  being one draw of the world; in the pooled column: the seasons), how many paths of each cell
  are distinct when fewer than all, and against which rivals, who believe the run's forecaster;
  with stand-ins named, that both stand-ins learn from the same played games, so a `system`
  difference fades through the season while the live sources stay apart all year, and that
  under `--arms` it is the one seat's result against rivals on the run's forecaster. Under
  `--seats` it is a room's result (an arm's outcome moves with the seats it shares the room
  with), and a room's payload with stand-ins carries that line (`result_is`).
- **Guidance for a `system` comparison**: run it with the run's forecaster equal to the first
  stand-in (`--forecasters prior --bbm-as prior --yahoo-as espn`). The draft then reads the
  first stand-in's projection, a `bbm` seat believes it and a `yahoo` or `blend` seat reads it
  for every rostered player, so no seat holds a drafted player its belief does not project (the
  unprojected count is zero for every arm); with another run's forecaster a seat can, and the
  command says so.
- **The confirmation season's ledger.** The confirmation season (2025-26, ESPN id 2026,
  `cli.CONFIRMATION`) is looked at sparingly: a written replay that names it appends one line to
  `data/sim/confirmation-looks.jsonl` (when it started, the run's name, the design, the seasons,
  the forecasters, a hash of each spec, the fit's hash, the code's commit), and its payload
  (`confirmation`) and its last printed lines say "look n", n the line's number. A dry run and a
  no-peek check add no line. Refusing the season inside a search set is PR H's.
- `validate --season 2024 --forecaster prior`: gate 5 on a replay of the season named (default
  the latest replayable season on file; the hold-out is refused as the replay refuses it, the
  confirmation season because a gate needs no look at it), drafted on the forecaster named
  (default `prior`); since the standalone cut it is the only gate (**The gates as they stand**).

An arm's spec file names its tier, every one of the twelve knobs, its opponents and what it
executes, may name its four fields (their defaults otherwise) and may name the fit it was written
for (`fit_sha`; another fit on disk refuses the run). Every run writes
`data/sim/runs/<stamp>-<kind>-<name>.json` with the code's commit, the fit's hash and file (whose
`lag` the run reads), the hold-out, the spec files verbatim, the execution model, each arm's fields
and its surrogate's pool and days, the reads table, the season scale, the period calendar's source,
and the results. A run first times one task and estimates the whole; the guard then refuses a span
that would touch 04:45-06:45 in the machine's local time, a draft room open on the API, or a run
over an hour without `--announced` (such a run is announced on the tracker and starts on the user's
word).

## The forecasters (`sim/forecast.py`, PR D1)

A replay's **forecaster** is its projection source: the figure each projected player's belief
starts from and the draft's ranking. A run names one or several (`--forecasters`, comma
separated, in order) for one or several seasons (`--seasons`); a **cell** is a season under one
forecaster, and every path is played once in each cell served. A forecaster that cannot serve a
season leaves that cell skipped, by name and with the reader's reason, before any path; a run
with no cell left is refused, and so is a run whose stand-in (`--bbm-as`, `--yahoo-as`) cannot
serve a season named. The payload keys its results and counts by season, then by the
forecaster's label. Four names:

- `prior`: the prior season's per-game rates of the players with twenty played games in it. It
  needs the prior season's log.
- `espn`: ESPN's stored season projection for the replayed season, from the cached log's season
  block (split 0, source 1), per game, for every player whose block has games above zero; a block
  without a games count is left out. It needs that block in the log.
- `marcel`: the seasons before the replayed one, back from the one just before while each is on
  file, up to three, most recent first, weighted 5, 4 and 3 by recency (5 and 4 with two seasons,
  not renormalized). Per player and stat, `(Σ wᵢ · totalᵢ + 100 · mean) / (Σ wᵢ · gamesᵢ + 100)`
  over the seasons he played in, makes and attempts each a stat of their own; `mean` is the mean
  per-game rate over the players with twenty games in the most recent season read. A player with
  twenty games in at least one season read is projected. It needs two earlier seasons. The
  constants are named in the module and not fitted. A replay of 2025-26 reads 2024-25's lines
  here as preseason information, as `prior` does; the hold-out is never a replayed season.
- `oracle:σ`: the replayed season's realized rates of the players with twenty played games,
  noised on the log scale: a labelled look-ahead whose error is known. `--shape stat` (the
  default) draws `ε = σ · z_stat` a player and stat, the draws the first replays used, bit for
  bit. `--shape minutes` draws `ε = σ · (√0.7 · z_player + √0.3 · z_stat)`: `z_stat` the same
  draw and `z_player` one draw a player from the world's `forecast` stream, shared by every stat,
  makes and attempts included, so the shared part leaves his percentages alone.

`espn`, `marcel` and the oracle pass their rates through `consistent` (makes within attempts,
threes within field goals). `prior` stays as the first replays read it: a recorded season keeps
those identities on its own.

Two diagnostics go to the payload's `forecasters` block and never to a seat. **The error**
(`error_of`): over the projected players with twenty played games in the replayed season, per
stat, the mean and the spread of `log(realized rate / forecast rate)` where both are above zero,
with the count; how many players the forecaster projects and how many of them played twenty; the
median spread over the stats. An oracle's is measured on path 0 and should sit at its spread, a
check of the draw. **The freeze check** (`freeze_of`, `espn` only, the replayed season only):
ESPN updates its stored block through the season, so it may not be the preseason figure. Among
the projected players who played thirty games or fewer, the check takes their count and the
median of their projected games, and it counts the projected players whose projected games equal
the games they played. A preseason projection cannot know who will miss the season, so a median
below 50 means the block was updated in season: it is flagged, never refused.

## The replay: what a seat knows (`sim/belief.py`, `sim/nopeek.py`)

A replay plays a made-up league on a season that happened, so its seats must know only what a
manager could have known on each day. Before #172's PR B1 they did not: every seat's belief moved
each week toward the season's realized rates, its whole-season average, and the draft and the pool
took only players who went on to play twenty games. Replay figures from before it (payloads with
no `replay_version`) are superseded. A replay wrote `replay_version: 2` from then; 3 since a run
names its forecasters (PR D1), its results and counts keyed by the forecaster's label (`prior`,
`oracle:0.1`) where version 2 keyed them `prior:0`; it writes 4 since a run names several seasons
(PR D2), what is one season's keyed by season; 5 since the standalone cut (PR D3), its figures
version 4's; and 6 since the draft market (PR D4a), its figures version 5's under `--adp none`.

**The belief.** On day `d`, stat by stat, a seat believes
`(w · the forecaster's figure + the sum of his lines dated before d) / (w + his games before d)`,
read every day. "Before" is strict: the line of a game played on `d` is in the belief of `d + 1`.
Makes and attempts are shrunk as stats of their own and the percentages follow from them; the
result keeps makes within attempts and threes within field goals. The forecaster's figure is the
run's forecaster's (`sim/forecast.py`, above); each forecaster gets its own belief.

**The weights.** One `w` per stat, in games, from the grid 2, 4, 6, 10, 16, 25, 40, 65, 100,
chosen by the least squared error of each projected player's next game against the belief before
it, summed over his games in date order; a tie takes the larger weight. Since PR D2 each belief
label (each of the run's forecasters, each system label an arm holds, and the first stand-in's
when a label is split) gets its own weights, fitted on that label's own projection of every
season on file earlier than the one replayed that the label can serve (`readers.label_weights`):

- `prior`: the season before's rates, as before PR D2 and bit for bit;
- `espn`: the season's stored projection; a season whose projection fails the freeze check gives
  no sample, its projection having seen part of its own season;
- `marcel`: its projection of the season, where two seasons before it are on file;
- an oracle: a draw of the season at the label's spread and shape, on keys of its own on the
  `forecast` stream (`forecast.FIT_KEYS`, one for the run's oracle and one for each role, the
  fitted season a last key), so no path of any run shares a draw with it;
- a system label: the system's table (`forecast.system_rates`) on the two stand-ins' projections
  of the season, where both serve it.

A sample names every season its projection read (`prior` the season before, `espn` and an
oracle the season itself, `marcel` the seasons it read, a system label its two stand-ins'
together); the fit refuses one whose season or whose read seasons hold the hold-out, and the
reader never makes one or opens what it would read. A label with no sample takes the prior
forecaster's weights for this replay when those were fitted, else 10 for every stat. Each label's
record (`belief.weights`, by label) says which of the three it is (`own`, `the prior
forecaster's`, `the default`), the seasons fitted on and, for each earlier season that gave no
sample, why; the command prints one line a label. The weights are computed once per command,
from the logs alone; the frozen fit is not touched.

**What a belief does not project.** A seat whose belief has no line for a drafted player values
him at zero until he plays. For each belief label an arm holds, each path counts the drafted
players its table has no line for on the first day (a split label: its rostered side's), on the
rosters of the seats that hold the label and on all twelve; the payload's `unprojected` block
gives the mean and the largest over paths. The run's own label counts zero by construction (the
draft read its projection). When stand-ins are named and none of the run's forecasters is the
first stand-in, the command prints a line saying a seat can hold such players.

**The league and the draft.** The league is everyone the season's log lists with a scheduled game.
The draft is a snake on the run's forecaster's values over the projected players with a scheduled
game in the season's first seven days, as an opening-night roster shows; everyone else is on the
wire. Who is projected is the forecaster's (above). Under a table of average draft positions
(`--adp espn`, PR D4a) the seats draft on boards instead ("The draft market", below).

**A belief for each seat (PR D1).** A replay's world holds a causal belief for each forecaster a
seat names, each from its own projection with its own newcomer's prior (the mean of its own
projected players left undrafted), at its own weights (above). A seat names its forecaster
(`opponents.Seat.forecaster`, set from the arm's `forecaster`, which a run sets and a spec file
does not name); None is the run's. Each day such a seat decides, sets its lineup, is charged its
forced drops and is scored (the lineup's fallback) on its own forecaster's beliefs and per-game
values; every other seat, the market, mirror and static rivals among them, on the run's. The label
is part of the seat and so of the decision cache's key: two arms on different forecasters share no
decision and both seasons are played in full, while the world's draws (lines, absences, news, the
market's generator) stay common to them. A day record carries the other forecasters' beliefs a
variant's seats hold and which team holds which (`held`, `holds`), and the no-peek digest hashes
them when they are not empty, so a run whose seats all hold the run's forecaster records and
digests as it did. The season scale reads the arm's own forecaster. Under `--adp none` the draft
and the market's ranking stay the run's forecaster's: an arm on a forecaster of its own reads it
from the season's first day. Under a table its seat drafts on it (PR D4a, "The draft market").

**The two sources' stand-ins (PR D1).** The live engine reads two projection systems, Basketball
Monster and Yahoo, and an arm's `system` knob picks the one it believes (`blend`, a mix at the
`blend` share). The simulator holds neither, so a replay may name a forecaster to stand in for
each: `replay --bbm-as F --yahoo-as G`. It names both or neither, the two differ, and each must
serve the season, else the run is refused by name before any path. With them named, each arm's
seat believes by its `system`. As modelled:

- `bbm`: the first stand-in's forecast.
- `yahoo`: a player on no roster that morning reads the second's line where the second projects
  him and the first's elsewhere; every rostered player, the seat's own and every opponent's,
  reads the first's.
- `blend`: the same split; on the available side, for every player the second projects,
  `share · second + (1 − share) · first` stat by stat (the second's alone where the first has
  none), the first's for everyone else; `share` is the arm's `blend`, or the engine's default
  (`progress.BLEND`) when it is None.

The split is the live route's: there the second source's table holds the available players
only, so an add is judged on the second source against a drop on the first. The available
side's table is `forecast.system_rates` (a mix passes through `consistent`), believed causally
like any forecaster; a `yahoo` or `blend` seat's day table (`run.split_beliefs`) takes the first
stand-in's belief of every player on any roster of its own league that morning, held slots
included, and that table's belief of every other player. The table follows the rosters: the
forced drops at the landing are weighed on the rosters as they stand before anything lands, and
the decision, the lineup, the day record and the score on the rosters after it, so a player
dropped yesterday reads the available side today and one added yesterday the first's. The seat
reads one table a day and its values are that table's. The world holds the first stand-in's
belief whenever an arm's system is `yahoo` or `blend`, with or without a `bbm` arm (the run's
own belief when the first stand-in is the run's forecaster).

The belief's label names it: `espn`, `yahoo(marcel else espn)`, `blend:0.5(marcel with espn)`,
and each label gets its own belief (above). The run's forecaster still drafts, runs the market
and believes for every rival. With stand-ins named, `system` is read by the arm's own seat and
`blend` when its system is `blend`; without, neither is, and two arms that differ only in them
are the same seat. A rival never reads them: a mirror believes by the run's forecaster.

What still differs from the live route (`forecast.LIVE_DIFFERENCES`, and the payload's
`sources.differs`):

1. The second stand-in is a season forecaster; the live second source is a line for the next
   seven days, so it moves with the week's news and schedule.
2. Live values each source on its own table (the second's holds only the available players, so
   its values are scaled within the available pool) and a blended player at the mix of the two;
   the simulator values the seat's one mixed table, under `yahoo` as under `blend`.
3. Both stand-ins learn from the same played games (each at its own weights since PR D2), so
   their beliefs close on each other as the season goes, where the two live sources stay apart
   all year: a `system` difference measured here is weighted to the early weeks.
4. "Available" is "on no roster in the seat's own league that morning".

An oracle stand-in draws from its role's own keys on the `forecast` stream (labelled
`oracle:0.2@bbm`, `oracle:0.2@yahoo`), so two oracle stand-ins have independent errors and
neither shares the run's oracle's draws; two real sources' errors are correlated, so with oracle
stand-ins the mix's benefit is an upper bound. The payload's `sources` block names the two
stand-ins, the rule as modelled, what still differs, each system's label, share and rostered
side (the first stand-in's label for `yahoo` and `blend`, null for `bbm`) with the error of its
table (the available side's for a split label), and that the result is about two sources with
these errors, not about the two real sources; `beliefs` names each arm's label, and the
`forecasters` block carries each stand-in, which role it stands for and its error.

**A newcomer.** A player nobody projected (a rookie, a player who missed most of the prior season)
is on the wire from day one but in no belief, so no seat can add him, until the day after his first
recorded game; from then his prior is the mean projection, stat by stat, over the projected players
left undrafted: an average wire player until his games say otherwise. The opponents' market view
stays the projected players' values.

**The no-peek check.** Two replay worlds that agree on the preseason inputs, the schedule, every
line dated before `d` and every absence that begins on or before `d` (its start and its end), and
differ in the lines dated `d` or later and in the absences that begin after it, must hand every
seat the same day records through `d`. `tests/sim/test_no_peek.py` holds this on a small league
with seats that move, on three days, one a Monday; it also shows the check catches a belief that
counts the day's own line and news heard a day early. `replay --no-peek YYYY-MM-DD` runs it on the
real log: it builds the second season from the first by a seeded change with exactly that
agreement, runs one path of each, prints whether they agree through the date and where they first
part, writes nothing, and exits non-zero on a difference at or before the date.

**What a replay still assumes.**

- The date a seat is told for a return is the true one, the day after the last missed game, plus a
  rounded normal error of `--news-sd` days (default 2), never before the absence is heard; the
  absence is heard `lag` days after it begins.
- A player's game days are those of the team the log records him on, all season: the schedule of
  a player who was later traded is known from day one.
- The prior forecaster knows no rookie and nobody who missed the prior season; they arrive by the
  newcomer's rule. The oracle is a labelled look-ahead: its figures are the replayed season's own
  realized rates, noised. `espn`'s stored block may have moved through the season (its freeze
  check).
- A replay reads no status on day one, so a drafted player out from opening night is heard to be
  out only `lag` days after his first missed game.

## The draft market (`sim/adp.py`, PR D4a)

**The table.** ESPN's season logs, the files a replay already reads, carry each player's average
draft position over ESPN's drafts (`player.ownership.averageDraftPosition`). A season's table is
read from its own log, by ESPN's ids, so it needs no request, no file of its own and no matching of
names. Three things were settled on the logs on file before anything was built on the figure:

- **It is that season's own draft position.** Players in their first season on file carry
  figures off the ceiling, so it is no earlier season's draft. Players in their last season on
  file do too, so it is no later season's; this was checked where a later log is on file (the
  hold-out's log was not opened for it). And the order agrees with the season's own stored
  projection at least as well as with another season's.
- **An undrafted player carries the ceiling:** the figure the most players share, at the top of
  the range, with an auction value of about nothing and, nearly always, almost no ownership. Such
  a player is not listed; every listed player sits ahead of him. A few players carry figures a
  little past the ceiling (drafted late somewhere); they are listed.
- **Whose drafts:** `ownership.leagueType` is one value for every player of every season, so the
  figure pools ESPN's drafts whatever their scoring. Its order sits close to both of ESPN's own
  preseason ranks, the points one and the categories one, nearer one in one season and the other
  in the next. So this market is ESPN's public drafts, not a nine-category league's: a limit.

A log whose players all carry one and the same figure holds no table, and a run that asks for it
is refused by name before any path. The confirmation season's log is such a log today. The hold-out
is refused before its log is opened. The table's counts (players, listed, at the ceiling, with no
figure) and the log's hash are what a run records of it; the figures stay in the log.

**The draft on a table** (`replay --adp espn --adp-spread <base>,<growth>`). Every seat picks, in
the snake, the best player left on its own board:

- **A rival's board.** A listed player's place is his average pick plus a normal draw at
  `base + growth × pick` picks, with no bias; one draw for every listed player of the table, in
  the order of his pick, drafted or not. The players the table does not list sit below every
  listed one, by the run's forecaster's value. Each seat draws its board from a generator of its
  own on the path's `(seed, path)` and the `draft` stream (appended to `world.STREAMS`, so no
  other stream moved): two arms' seasons on a path meet the same rivals' boards.
- **An arm's seat's board** is its own forecaster's per-game value on draft day: the run's
  forecaster's when the arm names none, a `system` or `blend` seat's stand-in belief as the run
  builds it for the first day. A player that forecaster does not project is not on it: the seat
  cannot value him and never drafts him.
- **Who can be drafted:** every member with a game in the season's first seven days who is
  projected by the run's forecaster or listed by the table. So a rival may draft a player the
  run's forecaster does not project (a rookie under `prior`), who is then valued at zero by the
  seats on that forecaster until he plays.
- **The spread is given, not fitted here.** `--adp espn` without `--adp-spread` is refused, and
  both figures are at least zero. No default sits in the code.
- **The market's view** (what a `market` rival ranks its adds and drops by) is the table's: a
  listed player's view is the negative of his average pick, and an unlisted one sits below every
  listed one, by the run's forecaster's value. It is the preseason's and does not refresh through
  the season: a limit.
- **The room** (`--seats`): every seat holds an arm, so every seat drafts on its arm's own board
  and no board is a rival's. The table reaches a room only through the market's view.
- **The pair** (`--arms`): the arm's seat drafts on the arm's board and the other eleven on rivals'
  boards. When arm A's and arm B's draft-day beliefs are one label, there is one draft and one
  league, and the pair shares what it always shared. When they differ, each arm's season is its
  own league from the draft on: two setups and two worlds on the same `(seed, path)`, so the
  world's draws and the rivals' boards stay common. The world's newcomer prior reads who went
  undrafted, so one world cannot serve two drafts. The seat still rotates with the path.
- `--no-peek` checks the draft on the run's forecaster, so it is refused with `--adp espn`.

`--adp none`, the default, is the draft as it was: a snake on the run's forecaster's values, the
market's view the same values. It is there so that a run before PR D4a can be run again and
compared: what the market changes is read against it.

**What a run records.** The payload's `adp` block names the source. Under a table it adds the
spread as given, the rules above in words, and per season the table in counts (the players the
log lists, those listed, those at the ceiling, those with no figure), the log's hash, and the
drafted players the run's forecaster does not project over the drafts of the paths that stand.
A pair also says whether its two arms shared one draft or each drafted apart. The figures stay
in the log. A dry run prints each season's table in counts and the first task's drafts.

**The two rules.**

1. With `--adp none`, nothing moves: a replay's record equals the record before PR D4a key for
   key, apart from the added `adp` block, the version and its reason, and what names the run (its
   sha, times, host, path and name). Every pin the replay's tests held before stands unedited
   but the version's.
2. The tables are data. No player's name, no average draft position and no count measured on a
   real log goes into the code, the tests, these docs, a PR or an issue: the tests draw made-up
   positions (`tests/sim/sim_league.py`), and public text says in words what a real log shows.

**Its limits.** The rivals' error is one spread for every rival, given and not fitted; nobody
reaches for a position, a need or a run on a category. The market's view is the preseason's and
never refreshed. And the table pools drafts of every scoring (above), so it is not a nine-category
league's.

## The audit and the counts (`sim/audit.py`, `sim/counts.py`)

The policy decides and the world checks. On every simulated day of every run of every command
(a replay and the no-peek check, dry runs too), for each variant and every seat, the
rivals' included, the audit reads the day at the point the day record is taken: yesterday's queue
landed, the day's moves queued, the lineup set, the day's lines not yet read. No hook is needed;
`simulate` runs it. Its rules are a list (`audit.RULES`), each named, each a function of the
setup, the day and the same variant's day before; a later rule is one more entry.

- `roster_slots`: a roster within the league's slots, its active players within the active spots,
  each held kind within its count.
- `one_place`: nobody on two rosters, nobody on a roster and on the wire.
- `weekly_adds`: the adds charged to the week, landed and queued today, within the cap.
- `lands_next_day`: every player who joined a roster today is the add of a move the same team
  queued the day before (the auditor keeps each variant's day before; on day one the setup's
  rosters stand for it, with nothing queued).
- `held_kind`: a player placed in a held slot today is one the slot's kind accepts
  (`moves.eligible`) under the status heard today.
- `lineup`: each starter on his team's active roster and eligible for his slot, no more starters
  in a slot than the league starts, every starter's team playing that day, nobody started whom the
  seat had heard was out. The lineup is a function of the setup, the state, the team, the day, the
  statuses and the values (`policy.starters_of`): no line reaches it, and changing a day's lines
  changes nobody's starters that day.

A breach (path, day, variant, seat, rule, what was found) voids its path: the runner records it,
the command leaves the task out of every aggregate (a replay voids a season, forecaster and
path), lists every breach and the voided tasks in
the payload's `audit` block with the rules, writes the payload and exits 3. A dry run audits its
one task and exits 3 on a breach too; the no-peek check prints the breaches of either season and
exits 3 before it reads a difference. Nothing is repaired.

**The counts.** An edge that comes from an artefact (four adds a week against rivals who never move)
shows in what happened, so every replay payload carries, per arm and pooled like the outcomes (a
seat's season, the mean over the arm's seats a path, then over the paths that stand): the moves
landed; the moves lost because the add or the drop was gone or no active spot was open; the adds
charged to each week, their mean and the share of weeks at the cap (an add counts in the week it was
made, the adds made before day one in week one); the drops forced by a returning held player; the
held-slot moves refused because the slot no longer accepted the player the morning they landed; the
held-slot stints and their days; and the starters' games played. A pair (`--arms`) adds the rivals'
seats as one row, both arms' seasons pooled. The landing counters are per seat on the state
(`SimState.executed_by`, `gone_by`, `forced_by`, `held_refused_by`, their sums the whole-state
counters); the rest is tallied by `sim/counts.py`.

## The gates as they stand (PR 2b; gate 5 alone since PR D3)

`validate` is gate 5 on a replay of one recorded season (`--season`, by default the latest
replayable season on file, never the hold-out or the confirmation season) drafted on one
forecaster (`--forecaster`, default `prior`), at `--seed` (default 1). A season it cannot replay,
or a forecaster that cannot serve it, is refused before the gate runs; nothing is reported as not
run.

- Gate 5 on a replay: the league, the belief's weights and the world built as `replay` builds
  them for the season and forecaster named (`cli.read_season`, `replay_setup_of`,
  `run.replay_world` at the label's own weights), path 0. For three seats, the first, the middle
  (the lower of two) and the last of the draft order, on the season's first simulated day and the
  3rd, 7th, 10th and 14th days after it (`GATE_DAYS`), from day one's rosters and on the day's
  belief, whether the surrogate's set equals the exact set: fifteen league-days. A seat passes
  with four matches of five, one gate row a seat, and the gate passes when every seat does. The
  knobs are `policy.KNOB_DEFAULTS` and the fields `policy.DEFAULT_FIELDS`, both in the payload's
  `surrogate_gate` block with the season, the forecaster, the seats, the days and the label's
  weights; no knob file is read.

## Runs

Every command runs through the commands' guard: low priority, never when its span touches 04:45
to 06:45 in the machine's local time, never while a draft room is open on the API, and a run
expected over an hour is announced on the tracker and starts on the user's word (`--announced`
says that has happened). The no-peek check runs two seasons before it can time one, so
the guard gives it a span of a quarter of an hour (`NO_PEEK_HOURS`) and refuses it when that span
touches the window.

## What was removed and when

The simulator began as a forward run from each live league's state today, meant to sit beside the
Monday scorecard. The user's ruling of 2026-11-07 made it standalone and whole-season, and PR D3
(#172) removed what only a live league could feed:

- `compare` (arm A against arm B in my seat in each league, at three shrinks of the projection
  error, with its one-SE line) and `room` (the arms around a league's recorded table). The paired
  design and the room both live on in `replay` (`--arms`, `--seats`).
- `validate --league`, gate 2 (the matchup odds against the engine's), gate 1's rows on a
  league's recorded weeks, gate 3's not-run line (the scorecard's realized share) and gate 6
  (the fitted refresh against the exports); gate 5 moved onto a replay of a recorded season.
- `fit --tau residual`, `--refresh` and `--league` (week six's re-freeze from the exports), and
  `--today` and `--system` from every command.
- The readers of a league's recorded state, settings, week records, decisions, exports, the two
  systems' gap and spread, and the ESPN ids; every import from `pickandroll.api` and from
  `pickandroll.sources`. The run record's `gap`, `today`, `system`, `leagues` and `skipped` keys
  went with them, and `replay_version` is 5 (a replay's figures are version 4's).

The same PR then removed the drawn world, which a whole season on a recorded season does not use:

- `run.forward_world`: the projection with a persistent error as the truth (`ε` around
  `−s·gap`, the shrinks `SHRINKS`), game lines with game noise and a minutes factor
  (`world.game_line`, `minutes_factor`), absences from the fitted hazard (`world.absences`,
  `run.hazard_of`, a day-one status's run), the weekly `refresh` belief (`κ`, `σ_η`) and the
  `fixed` belief, with `world.refresh`, `news`, `player_season` and `team_week` and the world's
  `truth`, `kind`, `beliefs(week)` and `week_index`. Every world is a replay.
- Gates 1 and 4 (team-week totals and missed games under the drawn world, on the hold-out and
  the cached logs, gate 1 in a league of its own: `cli.hold_out_setup`,
  `gate_hold_out_team_weeks`, `gate_absences`, `GATE_PATHS`, `readers.missed_games`) and
  `validate`'s list of gates not run. Their first reading, on the hold-out with the frozen fit
  of 2026-10-24: gate 4 passed; gate 1 failed, realized team-weeks above the simulator's
  distribution, the drafted population healthier than the pool the hazard was fitted on.
  `validate` is gate 5 alone.
- The run record's `refresh` and `tau` keys (and `validate`'s `not_run`); a run reads the frozen
  fit's `lag` and hash only, and `fit.py` is unchanged (**The fit**).
- The setup's `league`, `gap`, `espn_ids` and `assumed_pairings`, which nothing read, and the
  aliases `Season`, `KNOBS`, `BINOMIAL` and `starters` in `sim/engine.py`, which nothing used.
