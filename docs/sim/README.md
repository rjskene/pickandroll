# SEASON SIM: a forward Monte Carlo season simulator for the in-season engine

Tracker #172. The engine's knobs are judged today by a two-week live A/B on the Monday scorecard
(#152). The simulator gives them a season-level instrument: it plays the rest of the season many
times from each league's state today, once for the knob set in force and once for the change, in
the same simulated worlds, and reports the paired difference. Phase 1 is the forward run; a
five-season replay on real game lines is the out-of-sample check; an equal room of twelve engines
is proposed as the strategy lab. The design study is the master's note in the scratch repo; the
user's rulings of 2026-10-23 amended it (five seasons behind the fit, beliefs that refresh, no
data mining, projections taken as given).

## Where it lives

The simulator is its own package, `src/pickandroll/sim/`, beside the in-season engine
(`src/pickandroll/season/`), not inside it. Its tests are in `tests/sim/`, this doc in `docs/sim/`
and its fits and runs under `data/sim/` (local, as all of `data/`). The commands run as
`python -m pickandroll.sim <command>`. The direction of imports is held by a test
(`tests/sim/test_boundary.py`): nothing outside the package imports it; it reaches the engine
through `sim/engine.py` only, the whole list of engine code it calls as library code (the
engine's files are never edited from here); only `sim/readers.py`, `sim/gamelogs.py` and
`sim/cli.py` import `pickandroll.sources`; and its imports from `pickandroll.api`, the live
league's readers the commands use today, are an explicit list in the test that shrinks to empty
when the simulator stops reading the live league. The same test reads the core (`world`, `state`,
`league`, `opponents`, `policy`, `run`, `fit`, `checks`, `validate`, `engine`, `belief`, `nopeek`,
`audit`, `counts`) for any way to a file, a process or the network: none of them imports
`pathlib`, `io`, `shutil`, `tempfile`, `socket`, `ssl`, `urllib`, `http`, `requests`, `httpx`,
`subprocess`, `sqlite3` or `pickle`, none calls `open`, and only `run.py` uses `os`, for the
worker count and the workers' priority. The policy and the opponents reach nothing of `run.py`,
directly or through another module: the world is never among a seat's inputs.

## The world (`sim/world.py`)

Three layers on the real schedule, every draw seeded by `(seed, path, player, game, stream)` so
two arms of a comparison see one world and a stream added later moves no other draw:

1. **A persistent projection error**, once a path per player and stat: the true rate is the
   projection times `e^ε`, `ε ~ N(−s·gap, τ²)`, `s` the shrink toward the market view (0, 0.25,
   0.5), `gap` the audit's gap between the policy's system and the consensus, `τ` the error
   spread (from the systems' disagreement until box-score residuals exist).
2. **Game noise**: one minutes factor per game shared across the player's stats (lognormal, mean
   one), each counting stat and attempt negative binomial around `rate × factor` with its
   dispersion, makes binomial on attempts, points from the makes.
3. **Availability**: today's status as read, then after each played game a new absence with the
   fitted hazard and a run length from the fitted mixture (days, weeks, season).

**Beliefs** are what the policy decides on, never the truth: the projection with its error,
refreshed once a week on the log scale, `b' = b + κ·(θ − b) + η`, `η ~ N(0, σ_η²)`, and an
absence seen only `lag` days after it began with a noisy return date. `κ`, `σ_η` and `lag` are
knobs passed in; their defaults stand until the refresh is fitted from the projection source's
successive exports.

## The fit (`sim/fit.py`, `sim/gamelogs.py`, `sim/cli.py`)

ESPN's player view serves per-game logs for whole seasons, one request a season (`fetch-logs`),
cached under `data/external/espn/gamelogs/` and never committed. The fit (`fit`) estimates, per
season: the residual dispersion of each stat after the minutes factor (pooled, and per player
with thirty or more games, shrunk to the pool), the minutes factor's spread, the absence hazard
and its run-length mixture (runs before a player's first game are dropped, a run still open at
his last is censored). Games under five minutes are dropped and each player's share of them is
kept, so a gate failure can be read against it. Seasons are compared on the hazard and the
minutes spread and pooled where they agree within a fifth; a season that disagrees is kept apart
under its own id. The result is frozen as `data/sim/fit/<date>/fit.json` with its
SHA-256 beside it, naming every parameter and the hold-out season.

**The hold-out** is 2024-25 (ESPN season id 2025): the `fit` command refuses to fit on it, and
the gates run against it as well as against this season's recorded weeks. **No data mining**: the
fit is made once and frozen; every comparison is one pre-registered A against B with its seed; the
simulator vetoes a change and never proposes one until four Mondays of passed gates and a ruling.
The frozen fit's figures stay under `data/` and are described in words anywhere public.

## The league (`sim/league.py`)

Weeks are scored as the record scores a real one: percentages from makes and attempts to Yahoo's
three decimals, the lower turnovers winning, a tie half. Standings order by win percentage, then
a parameterised tiebreak (total category wins, then head to head; the settings page does not print
the regular season's rule). The bracket seeds the top `playoff_teams` with the byes the rounds
need (`2^rounds − playoff_teams`), reseeds each round or plays the fixed bracket as the league
does, and sends the higher seed through a tie. A points league scores on the weighted points.

The bracket's rules come from the league's settings page, which prints `Playoff Tie-Breaker`,
`Playoff Reseeding` and `Divisions` beside the playoff weeks. The page reaches the season view the
way every page does: the API's own read for a public league, the user's Chrome posting the page
through the extension's league reader for the private one; `parse_settings_page` keeps the three
rows and `SeasonSettings` carries them, None until read. `LeagueSpec.from_settings` builds the
simulator's spec from those settings and refuses (`BracketUnread`) a league whose page has not been
read for them, one with divisions, or a tie-breaker the bracket does not play. No run trusts a
bracket it has assumed: until the read is on file a run writes no playoff odds and reports rank and
category wins only.

## The gates (`sim/validate.py`)

Before any verdict, on this season's recorded weeks and on the hold-out, side by side: (1) every
team's weekly totals as probability integral transforms under the simulator's team-week
distribution, no bucket of twenty points off by more than five; (2) the simulator's matchup odds
scored by Brier beside the engine's, not worse by more than a hundredth; (3) the scorecard's
realized share inside the simulator's central 80% band for the same moves; (4) player-games
missed a team-week against the hazard, as randomized transforms in buckets; (5) the surrogate's
set equal to the exact set on four of five sampled league-days; (6) the fitted refresh inside the
band the recorded week-to-week projection changes imply.

## The state and the policy (`sim/state.py`, `sim/policy.py`)

A **setup** is one league as a run starts it: the calendar and pairings, the twelve rosters, the
free agents, the shared projection, the schedule, the statuses and return dates read on day one,
the gap between the two systems, the market's view and rate, and the bracket as the settings page
gave it. A **state** is one arm's position on a day: rosters, pool, adds used this week, the moves
queued to land tomorrow and every week's totals so far. Beliefs, truth, lines, absences and news
belong to the world and are shared by every arm; two arms whose states agree share one solve.

The policy is the engine's own code on that state. `problem_of` builds the live moves route's
`MoveProblem` from the setup and the state, in memory, as `api.season_moves.build` builds it from
the recorded season: the week against the pairing's opponent, three weeks against the field, the
free agents landing tomorrow, the weekly add limit net of the adds made, the keep rule, the
protection floor, the plan floor and the daily cap from the knobs (every one of the twelve is
checked against the engine's own bounds; a missing knob is refused, below **The knobs**). Three
tiers decide on it. **Exact** is the live route: single swaps on every candidate, the recommended
set on the three-week horizon with the season guard, the streaming plan beside it (or the strategy
route's weighted set when the arm executes `weighted`). **Surrogate** is the same evaluator on the
arm's `pool` (thirty by default) best candidates by value times games this week, the greedy search
alone, on the arm's `surrogate_days` (Mondays and Thursdays by default). **Ranking** swaps the pool's best for the roster's worst the
keep rule does not keep, when it gains, with no evaluator. The executor lands yesterday's queue
team by team in a rotating order. First its return rule: a held player whose status no longer
fits his slot comes back to the bench that morning and, while the active roster is then over the
league's spots, the least valuable active player by the day's value goes to the pool, the returning
player included (counted as a forced drop; the keep rule stays out of the executor). Then a
churn's held drop goes first, on his own, the held-slot moves a set needs are made, and the adds
land: a drop goes to the pool and the add takes his slot, an add that needs an active spot takes
a bench slot or is gone when none is open, an add another team took first is gone and counted.
A queued move is carried out against the day it lands: a held-slot move is made only while the
slot has room and accepts the status the player has that morning (`moves.eligible`, the engine's
own test). A player queued for IL while he was out whose status has cleared overnight stays
active and the move is refused (counted in `held_refused`); it frees no spot, so an add that
needed it meets the same check and is gone when no spot is open. The alternative, honouring the
status of the day the move was decided and activating him the same morning (the add lands and
the weakest active player is dropped), was not taken: it breaks the executor's one rule.
Every add is a free agent landing the next day
(`EXECUTIONS = "free_agents_next_day"`): no waiver clear dates, no bids, the caps the autopilot's.
An add is charged to the week of the day it is made, as Yahoo charges a free agent, never the
week it lands in: one made on Sunday spends the ending week's adds and plays from Monday, and
Monday's count starts over only once it is in.
Each day's starters are the most valuable set the slots hold among the players whose team plays
and whom the policy has not heard are out; their lines are the week's totals.

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
`faab_sizing`); anywhere else it is refused. `cli.policy_knobs` reads a league's knobs in force
and adds the two simulator knobs at their defaults; a league without a knob file takes the twelve
defaults (`policy.KNOB_DEFAULTS`).

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
many paths gave one) for compare, replay and room, at any `season_weight`, 0 included; null on
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

Every compare, replay and room payload carries the table per arm per league shape (`reads`).
Compare, replay and room refuse two arms that differ only in knobs and fields that neither reads
in any shape of the run: they are the same seat, and the message names each such knob, why it is
not read and what would read it. Two arms alike in everything are a check that the difference is
zero and run.

## The other seats (`sim/opponents.py`)

The ladder from the design note. **Static** makes no move. **Market** moves on a day with the
recorded rate (adds per team-day over the transactions page's days) and takes the pool's best by
the market's view for its weakest by the same view, within the caps; the view is the shared
projection's per-game value with percent rostered breaking ties, since Yahoo's own rank is not in
the recorded state. **Mirror** runs the surrogate on the shared beliefs. **Seat** is a named arm
in another seat: the equal room's opponent.

## The runner (`sim/run.py`)

One **world** a path: the projection with its error as the truth, each player's game days, his
availability and lines, the beliefs refreshed weekly, and what the policy has heard of each
absence (an `O` with the told return date, `lag` days after it began; a status read on day one
stands until its return). Every draw comes from `(seed, path, player, game, stream)` and never from
an arm, so a roster change in one arm reshuffles nothing: common random numbers. A **replay** world
has the recorded lines as the truth of every game (no game noise, no hazard: the logs happened) and
a game day without a line an absence; what its seats believe is below (**The replay**). The
truth's makes never exceed its attempts (the errors are drawn a stat at a time).

A world's belief is one of three kinds: `refresh` (the forward world's: the projection moved toward
the drawn truth each Monday at `κ` with noise `σ_η`), `causal` (a replay's: read every day from
the games already played) and `fixed` (the projection all season: gate 1's). `simulate` can hand
a caller a **day record** for each variant and day, taken after the lineup is set and before the
day's lines are scored: the beliefs, the statuses and return dates heard, the moves that landed,
each seat's decision, the queue, every team's starters and the state.

`simulate` advances variants of one league through one world a day at a time: yesterday's queue
lands (a held player whose status has cleared comes back to the bench first and the roster is
trimmed to the league's spots, then a churn's held drop, the held-slot moves and the adds, an add
with no active spot gone), Monday resets the adds, each seat decides (a decision cached by team
and state, so arms in lockstep solve once), the day is played and scored; the season is then
scored by the league. `paired` runs arm A and arm B in my seat and returns each outcome (playoff
odds, rank, category wins, matchup wins, title) and their difference. **The difference is B less
A**: arm B's outcome less arm A's, path by path, so a positive difference is what B gains over A
in playoff odds, category wins, matchup wins and titles; rank is better when lower, so there a
negative difference is B finishing higher. `room` seats the arms given around the table, seat
`i` taking arm `(i + path) mod n` so every arm sits in every seat across paths. The process pool
is the simulator's own (cores less two workers at `nice 10`; the API's pools are untouched).

**Determinism.** The same spec, seed and fit give the same outcomes in one process and across
worker counts, except at an exact tie: there an order-dependent sum in the engine's evaluator can
fall either way with the process's hash seed (a week plan whose gap over its set is 0.0 in one
process and 1e-16 in another, against a plan floor of exactly 0, is taken in one and not the
other). A real run sets `PYTHONHASHSEED=0`. The run record keeps the value (`hash_seed`, `"random"`
when it is unset), and compare, replay, room and validate print one line on stderr when it is
unset and the run is not a dry run.

## The readers (`sim/readers.py`) and the runs (`sim/cli.py`)

The core is pure; the readers bring the inputs. `setup_of` builds a league's setup from the
recorded season state and the systems the moves route uses: the gap is `log(Basketball Monster)
− log(Yahoo)` per player and stat, zero where either is missing, clipped to ±1; a regular week
whose pairings were not read is filled by a round robin and named in the payload
(`assumed_pairings`); the bracket comes from `LeagueSpec.from_settings`, or its refusal's words. The
newest frozen fit is read with its hash checked against the file; `τ` comes from the fit when the
residual fit of week six is in it, else from the two systems' spread over the league's top 156
players by value (the payload names which). A replay reads a season's log: every player is his own
team in the schedule, his game days his own entries, played or not, so a trade or a team read later
than the season moves nothing; scoring period `p` is the season's first period plus `p − 1` days,
the first periods verified against ESPN's scoreboard on 2026-10-24 (named in every payload).

Each command runs as `python -m pickandroll.sim <command>`:

- `compare A.json B.json --leagues all --paths 100`: arm A against arm B in my seat, paired, per
  league, at shrinks 0, 0.25 and 0.5; the paired change in each outcome (B less A) with its
  standard error; the verdict line is **advisory**: a change (arm B) passes when its paired change
  in playoff odds is not below zero by more than one SE at any shrink; no block and no promotion
  before PR 3. A league whose bracket is unread reports rank and category wins and no playoff
  odds.
- `replay --season 2024 --forecasters prior,espn,marcel,oracle:0.1 --seats A.json B.json`: a
  made-up twelve-team league on a recorded season (below), the arms rotated across paths, once
  for each forecaster named (default `prior`); the hold-out is refused. `--shape stat|minutes`
  sets how an oracle's error is drawn (default `stat`). `--news-sd` sets the told return date's
  spread in days (default 2). `--no-peek YYYY-MM-DD` runs the no-peek check instead, on the first
  forecaster named, and writes nothing. `--bbm-as espn --yahoo-as marcel` names the two live
  sources' stand-ins, and each arm then believes by its `system` (below).
- `room --leagues all --seats A.json B.json ... --draft rosters|snake`: the arms around one
  league's table from the recorded rosters or a snake redraft.
- `validate --league all`: the six gates on this season's recorded weeks and on the hold-out, side
  by side (below).
- `fit --refresh --tau residual --league <id>`: week six's one re-freeze, the residual `τ` against
  the first export and the fitted refresh from the exports on disk together, both hashes on the
  issue; until then `REFRESH_DEFAULTS` stand and every payload says `refresh: defaults`.

An arm's spec file names its tier, every one of the twelve knobs, its opponents and what it
executes, may name its four fields (their defaults otherwise) and may name the fit it was written
for (`fit_sha`; another fit on disk refuses the run). Every run writes
`data/sim/runs/<stamp>-<kind>-<name>.json` with the code's commit, the fit's hash and
file, the hold-out, the spec files verbatim, the execution model, the gap's systems and clip, the
refresh's source, `τ`'s source, each arm's fields and its surrogate's pool and days, the reads
table, the season scale, the period calendar's source, and the results. A run first times one task and estimates the whole; the guard then refuses a span that
would touch 04:45-06:45 on the Mac's clock, a draft room open on the API, or a run over an hour
not announced to fantasyMASTER (`--announced`).

## The forecasters (`sim/forecast.py`, PR D1)

A replay's **forecaster** is its projection source: the figure each projected player's belief
starts from and the draft's ranking. A run names one or several (`--forecasters`, comma
separated, in order) and plays every path once for each; the payload keys its results and counts
by the forecaster's label. A forecaster that cannot serve the season refuses the run by name
before any path. Four names:

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
no `replay_version`) are superseded. A replay wrote `replay_version: 2` from then; it writes 3
since a run names its forecasters (PR D1), its results and counts keyed by the forecaster's label
(`prior`, `oracle:0.1`) where version 2 keyed them `prior:0`.

**The belief.** On day `d`, stat by stat, a seat believes
`(w · the forecaster's figure + the sum of his lines dated before d) / (w + his games before d)`,
read every day. "Before" is strict: the line of a game played on `d` is in the belief of `d + 1`.
Makes and attempts are shrunk as stats of their own and the percentages follow from them; the
result keeps makes within attempts and threes within field goals. The forecaster's figure is the
run's forecaster's (`sim/forecast.py`, above); each forecaster gets its own belief.

**The weights.** One `w` per stat, in games, from the grid 2, 4, 6, 10, 16, 25, 40, 65, 100,
chosen by the least squared error of each projected player's next game against the belief before
it, summed over his games in date order; a tie takes the larger weight. They are fitted on the
seasons on file earlier than the one replayed whose own prior season is on file, with the
prior-season forecaster, never on the hold-out (a season whose prior season is the hold-out is
skipped too). With no such season every stat takes 10. Every forecaster takes these weights, the
prior forecaster's: no fit per forecaster is made, and the payload says so for each. The weights
are computed once per command, from the logs alone, and the payload records them, the seasons
they came from and whether the default stood; the frozen fit is not touched.

**The league and the draft.** The league is everyone the season's log lists with a scheduled game.
The draft is a snake on the run's forecaster's values over the projected players with a scheduled
game in the season's first seven days, as an opening-night roster shows; everyone else is on the
wire. Who is projected is the forecaster's (above).

**A belief for each seat (PR D1).** A replay's world holds a causal belief for each forecaster a
seat names, each from its own projection with its own newcomer's prior (the mean of its own
projected players left undrafted), at the same weights. A seat names its forecaster
(`opponents.Seat.forecaster`, set from the arm's `forecaster`, which a run sets and a spec file
does not name); None is the run's. Each day such a seat decides, sets its lineup, is charged its
forced drops and is scored (the lineup's fallback) on its own forecaster's beliefs and per-game
values; every other seat, the market, mirror and static rivals among them, on the run's. The label
is part of the seat and so of the decision cache's key: two arms on different forecasters share no
decision and both seasons are played in full, while the world's draws (lines, absences, news, the
market's generator) stay common to them. A day record carries the other forecasters' beliefs a
variant's seats hold and which team holds which (`held`, `holds`), and the no-peek digest hashes
them when they are not empty, so a run whose seats all hold the run's forecaster records and
digests as it did. The season scale reads the arm's own forecaster. The draft and the market's
ranking stay the run's forecaster's: an arm on a forecaster of its own reads it from the season's
first day. A drawn world (`compare`, `room`) answers every label with its one shared belief.

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
3. Both stand-ins learn from the same played games at the same weights, so their beliefs close on
   each other as the season goes, where the two live sources stay apart all year: a `system`
   difference measured here is weighted to the early weeks.
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

## The audit and the counts (`sim/audit.py`, `sim/counts.py`)

The policy decides and the world checks. On every simulated day of every run of every command
(compare, replay, room and the no-peek check, dry runs too), for each variant and every seat, the
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
the command leaves the task out of every aggregate (compare voids a league, shrink and path;
replay a forecaster and path; room a league and path), lists every breach and the voided tasks in
the payload's `audit` block with the rules, writes the payload and exits 3. A dry run audits its
one task and exits 3 on a breach too; the no-peek check prints the breaches of either season and
exits 3 before it reads a difference. Nothing is repaired.

**The counts.** An edge that comes from an artefact (four adds a week against rivals who never
move) shows in what happened, so every compare, replay and room payload carries, per arm and
pooled like the outcomes (a seat's season, the mean over the arm's seats a path, then over the
paths that stand): the moves landed; the moves lost because the add or the drop was gone or no
active spot was open; the adds charged to each week, their mean and the share of weeks at the cap
(an add counts in the week it was made, the adds made before day one in week one); the drops
forced by a returning held player; the held-slot moves refused because the slot no longer
accepted the player the morning they landed; the held-slot stints and their days; and the
starters' games played. Compare adds the rivals' seats as one row, both arms' seasons pooled. The landing
counters are per seat on the state (`SimState.executed_by`, `gone_by`, `forced_by`,
`held_refused_by`, their sums the whole-state counters); the rest is tallied by `sim/counts.py`.

## The gates as they stand (PR 2b)

`validate` runs what the data on disk supports and writes what each gate had to work with; a gate
without its inputs is **not run** and says why, never passed.

- Gate 1 on the hold-out: twelve snake-drafted teams' realized weekly totals (their players'
  recorded lines) as transforms under the simulator's team-week distribution centred on the
  players' own realized rates, the game-noise and absence layers alone. It keeps its own league:
  the players with twenty played games, all drafted on their realized rates, a `fixed` belief.
  Gates 1 and 2 on this season's recorded weeks, the current rosters standing in for the week's,
  once the recorder has weeks.
- Gate 4 on the hold-out and on this season's log: each player's season under the hazard drawn
  once a path and split into his weeks, so an absence that began one week is still missed the next.
- Gate 5 on the league's setup: the surrogate's set against the exact set on five league-days.
- Gate 6 once two exports and players with ten or more games exist; gate 3 waits on the scorecard's
  realized rows (PR 3).

**First reading of the hold-out (2024-25, the frozen fit of 2026-10-24).** Gate 4 passes on all
players with twenty or more games. Gate 1 fails: realized team-weeks sit above the simulator's
distribution. Read apart by population, the pooled hazard over-predicts the games the top 156
players by value miss and under-predicts the rest's: the drafted population is healthier than the
pool the hazard was fitted on. The hazard wants conditioning on minutes or on the rostered
population at the week-six re-freeze; until then a forward run's teams miss a few more games than
real ones, in every arm alike (the comparison is paired, the bias shared).

## Runs

Every command runs through the commands' guard: low priority, never when its span touches 04:45
to 06:45 on the Mac's clock, never while a draft room is open on the API, and a run expected over
an hour is announced to fantasyMASTER first. The no-peek check runs two seasons before it can time one, so
the guard gives it a span of a quarter of an hour (`NO_PEEK_HOURS`) and refuses it when that span
touches the window.
