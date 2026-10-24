# SEASON SIM: a forward Monte Carlo season simulator for the in-season engine

Tracker #172. The engine's knobs are judged today by a two-week live A/B on the Monday scorecard
(#152). The simulator gives them a season-level instrument: it plays the rest of the season many
times from each league's state today, once for the knob set in force and once for the change, in
the same simulated worlds, and reports the paired difference. Phase 1 is the forward run; a
five-season replay on real game lines is the out-of-sample check; an equal room of twelve engines
is proposed as the strategy lab. The design study is the master's note in the scratch repo; the
user's rulings of 2026-10-23 amended it (five seasons behind the fit, beliefs that refresh, no
data mining, projections taken as given).

## The world (`season/sim/world.py`)

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

## The fit (`season/sim/fit.py`, `sources/gamelogs.py`, `scripts/season_sim.py`)

ESPN's player view serves per-game logs for whole seasons, one request a season (`fetch-logs`),
cached under `data/external/espn/gamelogs/` and never committed. The fit (`fit`) estimates, per
season: the residual dispersion of each stat after the minutes factor (pooled, and per player
with thirty or more games, shrunk to the pool), the minutes factor's spread, the absence hazard
and its run-length mixture (runs before a player's first game are dropped, a run still open at
his last is censored). Games under five minutes are dropped and each player's share of them is
kept, so a gate failure can be read against it. Seasons are compared on the hazard and the
minutes spread and pooled where they agree within a fifth; a season that disagrees is kept apart
under its own id. The result is frozen as `data/autopilot/sim/fit/<date>/fit.json` with its
SHA-256 beside it, naming every parameter and the hold-out season.

**The hold-out** is 2024-25 (ESPN season id 2025): the script refuses to fit on it, and the gates
run against it as well as against this season's recorded weeks. **No data mining**: the fit is
made once and frozen; every comparison is one pre-registered A against B with its seed; the
simulator vetoes a change and never proposes one until four Mondays of passed gates and a ruling.
The frozen fit's figures stay under `data/` and are described in words anywhere public.

## The league (`season/sim/league.py`)

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

## The gates (`season/sim/validate.py`)

Before any verdict, on this season's recorded weeks and on the hold-out, side by side: (1) every
team's weekly totals as probability integral transforms under the simulator's team-week
distribution, no bucket of twenty points off by more than five; (2) the simulator's matchup odds
scored by Brier beside the engine's, not worse by more than a hundredth; (3) the scorecard's
realized share inside the simulator's central 80% band for the same moves; (4) player-games
missed a team-week against the hazard, as randomized transforms in buckets; (5) the surrogate's
set equal to the exact set on four of five sampled league-days; (6) the fitted refresh inside the
band the recorded week-to-week projection changes imply.

## The state and the policy (`season/sim/state.py`, `season/sim/policy.py`)

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
protection floor, the plan floor and the daily cap from the knobs (every one of the nine; a missing
knob is refused). Three tiers decide on it. **Exact** is the live route: single swaps on every
candidate, the recommended set on the three-week horizon with the season guard, the streaming plan
beside it (or the strategy route's weighted set when the arm executes `weighted`). **Surrogate** is
the same evaluator on the thirty best candidates by value times games this week, the greedy search
alone, on Mondays and Thursdays only. **Ranking** swaps the pool's best for the roster's worst the
keep rule does not keep, when it gains, with no evaluator. The executor lands yesterday's queue
team by team in a rotating order: a drop goes to the pool, the add takes his slot, an add another
team took first is gone and counted. Every add is a free agent landing the next day
(`EXECUTIONS = "free_agents_next_day"`): no waiver clear dates, no bids, the caps the autopilot's.
Each day's starters are the most valuable set the slots hold among the players whose team plays
and whom the policy has not heard are out; their lines are the week's totals.

## The other seats (`season/sim/opponents.py`)

The ladder from the design note. **Static** makes no move. **Market** moves on a day with the
recorded rate (adds per team-day over the transactions page's days) and takes the pool's best by
the market's view for its weakest by the same view, within the caps; the view is the shared
projection's per-game value with percent rostered breaking ties, since Yahoo's own rank is not in
the recorded state. **Mirror** runs the surrogate on the shared beliefs. **Seat** is a named arm
in another seat: the equal room's opponent.

## The runner (`season/sim/run.py`)

One **world** a path: the projection with its error as the truth, each player's game days, his
availability and lines, the beliefs refreshed weekly, and what the policy has heard of each
absence (an `O` with the told return date, `lag` days after it began; a status read on day one
stands until its return). Every draw comes from `(seed, path, player, game, stream)` and never from
an arm, so a roster change in one arm reshuffles nothing: common random numbers. A **replay** world
has the recorded lines as the truth of every game (no game noise, no hazard: the logs happened), a
game day without a line an absence, and beliefs refreshing toward the season's realized rates. The
truth's makes never exceed its attempts (the errors are drawn a stat at a time).

`simulate` advances variants of one league through one world a day at a time: Monday resets the
adds, yesterday's queue lands, each seat decides (a decision cached by team and state, so arms in
lockstep solve once), the day is played and scored; the season is then scored by the league. `paired`
runs arm A and arm B in my seat and returns each outcome (playoff odds, rank, category wins, matchup
wins, title) and their difference; `room` seats the arms given around the table, seat `i` taking
arm `(i + path) mod n` so every arm sits in every seat across paths. The process pool is the
simulator's own (cores less two workers at `nice 10`; the API's pools are untouched).

## The readers (`api/season_sim.py`) and the runs (`scripts/season_sim.py`)

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

- `compare A.json B.json --leagues all --paths 100`: arm A against arm B in my seat, paired, per
  league, at shrinks 0, 0.25 and 0.5; the paired change in each outcome with its standard error;
  the verdict line is **advisory**: a change passes when the paired change in playoff odds is not
  below zero by more than one SE at any shrink; no block and no promotion before PR 3. A league
  whose bracket is unread reports rank and category wins and no playoff odds.
- `replay --season 2024 --standin prior|oracle:0.1,0.2,0.3 --seats A.json B.json`: a made-up
  twelve-team league on a recorded season, snake-drafted on the stand-in projection (the prior
  season's per-game rates, or the realized rates noised at a spread), the arms rotated across
  paths; the hold-out is refused.
- `room --leagues all --seats A.json B.json ... --draft rosters|snake`: the arms around one
  league's table from the recorded rosters or a snake redraft.
- `validate --league all`: the six gates on this season's recorded weeks and on the hold-out, side
  by side (below).
- `fit --refresh --tau residual --league <id>`: week six's one re-freeze, the residual `τ` against
  the first export and the fitted refresh from the exports on disk together, both hashes on the
  issue; until then `REFRESH_DEFAULTS` stand and every payload says `refresh: defaults`.

An arm's spec file names its tier, every knob, its opponents and what it executes, and may name the
fit it was written for (`fit_sha`; another fit on disk refuses the run). Every run writes
`data/autopilot/sim/runs/<stamp>-<kind>-<name>.json` with the code's commit, the fit's hash and
file, the hold-out, the spec files verbatim, the execution model, the gap's systems and clip, the
refresh's source, `τ`'s source, the surrogate's pool and days, the period calendar's source, and
the results. A run first times one task and estimates the whole; the guard then refuses a span that
would touch 04:45-06:45 on the Mac's clock, a draft room open on the API, or a run over an hour
not announced to fantasyMASTER (`--announced`).

## The gates as they stand (PR 2b)

`validate` runs what the data on disk supports and writes what each gate had to work with; a gate
without its inputs is **not run** and says why, never passed.

- Gate 1 on the hold-out: twelve snake-drafted teams' realized weekly totals (their players'
  recorded lines) as transforms under the simulator's team-week distribution centred on the
  players' own realized rates, the game-noise and absence layers alone. Gates 1 and 2 on this
  season's recorded weeks, the current rosters standing in for the week's, once the recorder has
  weeks.
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

Every command runs through the script's guard: low priority, never when its span touches 04:45
to 06:45 on the Mac's clock, never while a draft room is open on the API, and a run expected over
an hour is announced to fantasyMASTER first. PR 3 brings the Monday hook, the knob file's field
and the Progress card, after the user's rulings on the threshold, the block, the promotion and
which knobs the simulator may tune.
