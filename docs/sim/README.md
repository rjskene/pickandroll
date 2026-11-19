# SEASON SIM: a standalone whole-season simulator

Tracker #172. The simulator plays whole fantasy seasons, from the draft to the final, on recorded
NBA seasons: a made-up league (twelve teams by default, or a grid of league shapes) is drafted on a
forecaster's projection and played through a recorded season's game lines, the engine's own code
deciding each seat's moves, and the league scores the weeks, the standings and the bracket. It is
standalone (the user's ruling of 2026-11-07): it reads no live league, writes no knob file and is no
part of a live decision. A **path** in a replay varies only in its seats (which arm sits where), in
the told return dates of the absences, in a market rival's draw and in an oracle forecaster's draw;
the season's games are the same on every path. A run is a **room** (the arms rotated around the
table, `--seats`) or a **pair** (arm A and arm B in one seat in two seasons through one world, B
less A, `--arms`), on one or several recorded seasons and forecasters. The design study is the
master's note in the scratch repo; the user's rulings of 2026-10-23 amended it (five seasons behind
the fit, no data mining, projections taken as given), and those of 2026-11-07 made it standalone and
whole-season.

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
is empty, and a new one fails it. Nothing under `tests/sim/` imports `pickandroll.api` or
`pickandroll.sources` either (PR D4a2): the made-up league parses its own players fixture. The
same test reads the core (`world`, `state`, `league`, `opponents`, `policy`, `run`, `fit`,
`checks`, `validate`, `engine`, `belief`, `nopeek`, `audit`, `counts`, `forecast`, `adp`,
`shapes`, `bids`, `screen`, `tune`) for any way to a file, a process or the network: none of them
imports `pathlib`, `io`, `shutil`, `tempfile`, `socket`, `ssl`, `urllib`, `http`, `requests`,
`httpx`, `subprocess`, `sqlite3` or `pickle`, none calls `open`, and only `run.py` uses `os`, for
the worker count and the workers' priority. The policy and the opponents reach nothing of `run.py`,
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

## The rivals' book (`sim/bids.py`, `fit-bids`, PR Fd)

`python -m pickandroll.sim fit-bids [--data DIR] [--dry-run]` makes the **price book** the market
rivals bid on under `--rival-bids book` ("FAAB", below) from the public leagues' winning-bids
table, `data/external/bids/winning_bids.csv` (written on the box by the live code, never
committed). It checks the table's `.sha256` first and refuses by name a table without one or one
it does not match. Of the table's columns it reads only `league`, `teams`, `faab_budget`, `at`,
`amount`, `ours` and `our_bid` (`bids.READ`): no player, no team, and nothing from
`pickandroll.api` (the column names are restated). It reads no game log, so no season is
involved and the hold-out is not near it. It writes `data/sim/bids/<date>/book.json` and
`book.sha256` (canonical JSON, the hash the fit's), and `--dry-run` prints what it would write
and writes nothing. A run on the book reads the newest one, its hash checked, as it reads the
fit. The book holds:

- the table's hash, the rows read and kept, the leagues, the first and last claim date;
- `prices`: **the rivals' wins** (the rows whose `ours` is empty) as shares of their league's
  budget, `amount ÷ faab_budget`, as the distinct shares with their counts: the whole empirical
  distribution. A `lost` row repeats a rival's win already in the table, beside the user's losing
  bid, and a `won` row is the user's own rule, so neither is a price;
- `adds`: the rivals' wins per rival team (`teams − 1`) per league-week, Monday to Sunday by the
  claim's date, over the whole weeks inside a league's first and last claim dates in the table,
  a week with no rival win counted 0 (a working default): the median and the quartiles over the
  league-weeks. It is a lower bound: each read of a league keeps a limited number of
  transactions, so a busy week's wins can be missed;
- `ours`: the user's claims won and lost in the table;
- `notes`: what the book does not model, the list below.

What the book does not model, each plainly (its `notes` say the first six; the last two are of
a run on the book, not of the table):

1. **It is of winning bids, not of all bids.** Where several claims meet, a rival drawn on it bids
   as a winner did, so the simulated winning prices sit above the book.
2. **A few weeks of one season**, the public leagues' own sizes and budgets. Late-season bidding
   is assumed alike; `--rival-scale` is the sweep.
3. **A bid does not read the rival's dollars left** beyond the clamp, nor the player.
4. **The rate and `among` are the arm's**, set by hand against the book's `adds` and `ours`. No
   measured figure is a default in the code. As a working default the rate is chosen on the weeks
   the book covers only: the rivals' wins a rival team in each simulated path's first whole
   weeks, as many as a league of the table holds, against the book's median. A rate so chosen
   holds for the `among` it was chosen at: `among` changes how often the rivals' claims meet one
   another, and so their adds, more than it changes how often the seat's claims are lost, which
   the book's `ours` does not settle.
5. **One view for every rival**; `among` stands for the managers' different tastes and needs.
6. **`adds` is a lower bound**, as above.
7. **The rivals' adds fall through the season, at every rate tried.** A rival that draws a move
   makes one only when one of its best few is worth more than its weakest, and under `view`
   `season` such mornings grow rarer as the weeks pass: the wire's best are soon on a roster, and
   a belief is a running mean (`sim/belief.py`), which moves less with each game played. So a
   rate that matches the book's `adds` in a season's first weeks gives fewer adds a week later
   on, and a higher rate lifts the season's figure by much less than its own rise. The book holds
   only a season's first weeks, so whether real managers slow the same way is not known here; a
   refit when the table holds later weeks is the check.
8. **A bid's rank reads the fortnight before, which is not like today while the season is
   young.** In a season's first weeks the wire's best are being taken, so a move gains less than
   the fortnight's before it, ranks low, and the rivals' bids sit a little under the book. Over
   all their wins the simulated winning prices then sit about on the book, and above it only
   where claims meet (item 1).

## The league (`sim/league.py`)

Weeks are scored as the record scores a real one: percentages from makes and attempts to Yahoo's
three decimals, the lower turnovers winning, a tie half. Standings order by win percentage, then
a parameterised tiebreak (total category wins, then head to head; the settings page does not print
the regular season's rule). The bracket seeds the top `playoff_teams` with the byes the rounds
need (`2^rounds − playoff_teams`), reseeds each round or plays the fixed bracket as the league
does, and sends the higher seed through a tie. A points league scores on the weighted points: a
week is one result on its fantasy points, which the week's result and the standings keep (points
for), and a tie on win percentage goes to points for, then head to head (`TIEBREAK_POINTS`, PR
D4c): its category wins are its wins again, so the team's number would decide it otherwise.

**The head-to-head format** (`LeagueSpec.h2h`, the format PR; the user's ruling of 2026-11-17, #172
comment 6956804083: "lets do win per matchup for now; but we should be able to run sims just as
easily on every category as well"). A categories league counts **one win per matchup** by
default (`one_win`): a week is one result, won by the side with more categories, and the
standings order as above. A league that counts **every category** (`each_category`) scores each
category of each week as a win, a loss or a tie, and orders its teams by the category percentage
(category wins, a tie half, over the categories played), then head to head (the weeks' results
between the tied teams), then the team's number (`TIEBREAK_EACH`). That tiebreak is a working
default: a league may break a tie otherwise, and none is read. Each team's `matchup_wins`,
`category_wins` and record are kept in either format: only the rank, and what rests on it (the
playoffs made, the title, the verdict), reads the format. The playoffs are the same bracket play
in both: a playoff matchup goes to the side with more categories, the higher seed through a tie.
A points league's week is one result already, and it names no format. The names are the engine's
(`season.state.ONE_WIN`, `EACH_CATEGORY`, through `sim/engine.py`).

A replay's league is made up, so its bracket is the replay's own: on the fixed shape the top six of
twelve over the last three weeks (a league shape names its own, **The league shapes**), the byes the
rounds need, reseeded, the higher seed through a tie (`run.replay_setup`).
`LeagueSpec.from_settings` builds a spec from a league's settings and refuses (`BracketUnread`) one
with divisions or a tie-breaker the bracket does not play; since the standalone cut no command reads
a league's settings, and a run without a spec writes no playoff odds and reports rank and category
wins only.

## The gates (`sim/validate.py`)

`validate` is gate 5 alone: the surrogate's set equal to the exact set on four of five sampled
league-days, for seats 1, 6 and 12, on a replay of a recorded season (**The gates as they stand**),
in the head-to-head format named (`--h2h`, one win per matchup by default, the format PR), so the
two tiers are compared in the measure the seats weigh.
Gates 1 and 4 tested the drawn world (team-week totals and missed games under its noise and its
hazard) and went with it; gates 2, 3 and 6 read a live league's recorded weeks, scorecard and
exports (**What was removed and when**).

## The state and the policy (`sim/state.py`, `sim/policy.py`)

A **setup** is one league as a run starts it: the calendar and pairings, the rosters, the
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
weakest active player is dropped), was not taken: it breaks the executor's one rule. Without
waivers every add is a free agent landing the next day (`EXECUTIONS = "free_agents_next_day"`): no
clear dates, no bids, the caps the autopilot's; a waiver league's adds are "The waivers" (below),
and under continuous waivers every add is a claim ("Continuous waivers", below). An add is charged to the week of the day it is made, as Yahoo
charges a free agent, never the week it lands in: one made on Sunday spends the ending week's adds
and plays from Monday, and Monday's count starts over only once it is in. Each day's starters are
the most valuable set the slots hold among the players whose team plays and whom the policy has not
heard are out; their lines are the week's totals.

**The seat's measure** (the format PR). In a categories league that counts one win per matchup
(the default) the problem says so (`MoveProblem.one_win`, as `api.season_moves.build` passes
`SeasonSettings.one_win`), and every tier that weighs (the exact and the surrogate tiers, a mirror
rival) values a week as the matchup's win odds (`weekly.matchup_won`, averaged over the week's
opponents and summed over the horizon's weeks) instead of its expected categories won, through
the engine's own `Evaluator`: the simulator names neither. The exact tier executing `weighted`
follows the format too, one measure a seat; live, the Strategy panel stays on expected
categories in every league (`api/season_strategy.py`, the master's ruling on #397), a working
default here. In a one-win league the plan's floor is the engine's own (`stream.floor_of`:
`PLAN_FLOOR_ODDS`, 3 points of the matchup's odds), ahead of the `plan_floor_cats` knob, which
nobody reads there. A league that counts every category, and a points league, are valued as
before. The ranking tier, a market rival and a static seat read no odds and do not change. The
record names the measure once, beside `executions` (`measure`: `matchup`, `categories` or
`points`, `moves.measure_of`'s words, `policy.measure`): what the format gives a seat that
weighs, recorded even when no seat of the run does.

What the format does not model, each plainly:

1. **The lineup.** Live, a one-win league's crowded-day lineup is picked on the matchup's odds
   (`lineup.win_starters`); the simulator's lineup (`policy.starters_of`) has never been that
   optimiser, in either format.
2. **The Strategy panel's measure** is not the simulator's: live it stays on expected
   categories; here the exact tier executing `weighted` weighs the format's measure (above).
3. **A league's own tiebreak** for every category is not read: the standings break a tie on head
   to head, then the team's number (**The league**).

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
  the arm executes and with the season term when it is on, so it is the combined figure's. The
  gain is in the league's measure: 0.01 is a point of the matchup's win odds in a one-win league
  (of a matchup won on the points in a points league) and a hundredth of a category under
  `--h2h each_category`, so a `min_gain` set in one format is not the other's, as with
  `season_weight`, while its default is one number in every format, as the live build's is;
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
outcome and is no part of a solve. Its gain is in the league's measure: in a one-win league the
matchup's win odds (the note says so in every one-win run, the format PR), as it is in matchups
won on the points in a points league, so its `ratio` differs by format: a `season_weight` set in
one format is not the other's. The term itself (a value times games) is the same in both.

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
| `plan_floor_cats` | exact drawing and executing the week plan, in a categories league that counts every category; in such a FAAB run any exact or surrogate seat and a mirror rival (the typical gain until ten moves, PR Fb) | any other arm or league; in a one-win league nobody: the engine's plan floor is its own there (the format PR) |
| `plan_floor_points` | the same, points | any other arm or league |
| `season_weight` | exact, surrogate | the ranking tier holds no odds |
| `playoff_weight` | `season_weight` above 0 on exact or surrogate, bracket read | no term, or no bracket |
| `three_weight` | nobody | the queue's rule, PR E |
| `system` | the arm's own seat, on a replay that names the two sources' stand-ins | a run without stand-ins |
| `blend` | the same, when the arm's `system` is `blend` | no stand-ins, or another system |
| `faab_sizing` | in a FAAB run (PR Fb), a seat that bids by the live rule: exact, surrogate, a mirror rival | no budget in the world (no waivers, or waivers by priority); the ranking tier holds no gain in the engine's units and bids $0 |
| `stash_threshold` | nobody | the engine reads it (#373); the simulator passes it, PR G |
| `pool`, `min_gain`, `weeks_ahead` | exact, surrogate | the ranking tier |
| `surrogate_days` | surrogate, or a mirror rival | the exact tier decides every day |

`rival_claim_rate` (the autopilot settings file's assumed chance that a team ahead claims a player)
gets no knob and no reader: live it only labels a claim's odds in the moves answer
(`moves.priority_claim`), and no decision reads it.

Every replay payload carries the table, one per arm (`reads`): no league shape moves what a seat
reads, and the league rules (the scoring, the held slots and the waivers, "The league shapes") are
the run's, one set for every path. In a points run (`--scoring points`) `plan_floor_points` is read where
`plan_floor_cats` was, and `plan_floor_cats` is not, with the reason. In a one-win league (the
default since the format PR) nobody reads `plan_floor_cats`: the engine's floor there is its own
constant (`stream.PLAN_FLOOR_ODDS`), ahead of the knob; a seat that would read it under
`--h2h each_category` says so, and every other reason is the same in both formats. A pair that
differs only on `plan_floor_cats` is refused in a one-win run and runs under `each_category` on
an arm that executes the plan. The shape's label leaves the format out: one format a run, named in
`league.rules.h2h`. A replay refuses two arms
that differ only in knobs and fields that neither reads in the run: they are the same seat, and
the message names each such knob, why it is not read and what would read it (a pair that
differs only on `plan_floor_points` is refused in a categories run and runs in a points run on
an arm that executes the plan; a pair that differs only on `faab_sizing` is refused without
`--waivers faab` and runs with it, PR Fb). Two arms alike in everything are a check that the difference is
zero and run.

## The other seats (`sim/opponents.py`)

The ladder from the design note. **Static** makes no move. **Market** moves on a day with the
setup's rate (a replay records none, so a market rival names its `rate`) and takes the pool's best
by the market's view for its weakest by the same view, within the caps; on a replay the view is the
run's forecaster's draft-day ranking, or under a table of average draft positions the table's
(PR D4a). **Mirror** runs the surrogate on the shared beliefs. **Seat**
is a named arm in another seat: the equal room's opponent.

A market rival's block reads two more keys (PR Fd, `opponents.of`), each off by default and each
working in every kind of league (no waivers, by priority, FAAB, either waiver rule):

- **`view`**: `draft` (the default: the view above, all season) or `season`. Under `season` its
  view on a day is each player's per-game value on the run's forecaster's beliefs that morning
  (`wk.per_game_values`, the figure the runner values the day by and lands forced drops on,
  computed once a morning for every rival): a rival still believes the run's forecaster, whatever
  the arm believes. It picks no player whose status that morning is one a seat never starts
  (`O`, `INJ`, `OFS`, `SUSP`, `NA`, as `policy.starters_of` leaves out), its drop is its weakest
  by the same view, and a table of draft positions plays no part after the draft.
- **`among`**: a whole number, 1 or more (default 1: the best it may add). With K above 1 it
  keeps, of the best K it may add by its view, those worth more than its weakest it may drop,
  and takes one of them, each as likely; none left, no move. The one number it draws is from its
  day's generator, after the rate's draw and before the bid's noise, and is drawn whenever a
  candidate is left, even a single one (a working default), so what it draws never depends on
  how many are left; with 1 none is drawn. With one view and no spread every rival that moves on
  a day claims the same player: `among` is how often two claims meet.

A value out of those, or either key on a kind other than `market`, is refused by name. The rate
and `among` are set by hand against the price book ("The rivals' book"); no figure of it is a
default.

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
when it is unset), and replay, validate, screen and tune print one line on stderr when it is
unset and the run is not a dry run.

## The readers (`sim/readers.py`) and the runs (`sim/cli.py`)

The core is pure; the readers bring the inputs, from ESPN's cached logs and the frozen fit only. The
newest frozen fit is read with its hash checked against the file. A replay reads a season's log:
every player is his own team in the schedule, his game days his own entries, played or not, so a
trade or a team read later than the season moves nothing; scoring period `p` is the season's first
period plus `p − 1` days, the first periods verified against ESPN's scoreboard on 2026-10-24 (named
in every payload).

Each command runs as `python -m pickandroll.sim <command>`:

- `replay --seasons 2022,2023,2024 --forecasters prior,espn,marcel,oracle:0.1 --seats A.json
  B.json`: a made-up league on each recorded season named (below; twelve teams by default, "The
  league shapes"), the arms rotated across paths, once for each season and forecaster that serves it
  (a **cell**; default forecaster `prior`). The hold-out anywhere in the list, a season named twice
  or a season with no log on file is refused by name before anything runs. Before any path each
  season is read on its own (its lines, the forecasters' figures, each label's weights, the league's
  shape) and the cells are printed as a table, seasons across and forecasters down: a forecaster
  that cannot serve a season leaves that cell skipped, with the reader's reason; a stand-in that
  cannot serve a season refuses the run by name (a system label cannot be built there); a run with
  no cell left is refused. The tasks are the served cells by the paths, and the estimate counts
  them; `--dry-run` runs one task of the first served cell (path 0; on a grid the timed one, "The
  league shapes"). `--shape stat|minutes` sets how an oracle's error is drawn (default `stat`).
  `--news-sd` sets the told return date's spread in days (default 2). `--no-peek YYYY-MM-DD` runs
  the no-peek check instead, on one season only and its first served forecaster, and writes nothing.
  `--bbm-as espn --yahoo-as marcel` names the two live sources' stand-ins, and each arm then
  believes by its `system` (below). `--adp espn --adp-spread <base>,<growth>` drafts the league on
  the season's table of average draft positions instead ("The draft market"); `--adp none` is the
  default. `--grid full` visits the grid of league shapes and `--league` names one, and
  `--scoring points` (with `--points`), `--held`, `--waivers` (with `--waiver-days` and
  `--waiver-rule`, and under `faab` `--budget`, `--rival-scale` and `--rival-bids`) and `--h2h` set
  the run's league rules ("The league shapes"). The payload (`replay_version` 13) keys by season what is one season's: the forecasters,
  the sources, the weights, the players, the shape, the results, the counts, the season scale and
  the unprojected count; `cells` says which were served and why the others were not, and `adp` what
  the league was drafted on, and `league` the league shapes the paths played and the league rules.
- `replay --seasons 2022,2023,2024 --arms A.json B.json`: the paired design on a replay, arm A and
  arm B in one seat through one recorded season's world. A run names `--seats` (a room, as above) or
  `--arms` (exactly two spec files), never both and never neither. Each task drafts the league on
  its cell's forecaster as a room does, then puts arm A in seat `teams[path mod 12]` (on a league
  shape, `teams[turn mod n]`) in one season and arm B in the same seat in a second, through one
  world in lockstep (`run.paired`), each arm believing by its own label; the other seats (eleven on
  the fixed shape) are each arm's `opponents` block and believe the run's forecaster, whatever the
  arm believes. `--paths` is rounded up to a multiple of the league's seats (twelve on the fixed
  shape; on a grid, of its shapes), and the command says so (20 becomes 24), so every seat is taken
  equally often in every cell. A replay records no market rate, so a `market` rival without a `rate`
  would never move: it is refused by name. A market rival's view is the run's forecaster's draft-day
  ranking, or under `--adp espn` the season's table (PR D4a, "The draft market"), or with `view`
  `season` the day's beliefs (PR Fd, "The other seats"). A pair that is one
  seat by construction is refused by name, the knobs and fields it differs in listed with why none
  is read (**What each knob reads**); the same arm twice stays allowed (a check that the difference
  is zero). `--no-peek` checks the design the run names: with `--arms` it compares both arms'
  seasons' day records on path 0. The payload (`design: paired`) carries the seat rule and each
  path's seat, and per cell each arm's outcomes, the `difference` (B less A) with its standard error
  over the paths, the count of paths and how many are distinct (by the seat, both arms' metrics and
  their mechanism counts: the season's games are the same on every path, so paths repeat when
  nothing is drawn, and an SE over repeats is over copies), the counts by arm and for the rivals,
  each arm's season scale, the unprojected count by arm, and the rivals each arm faced with the line
  that they believe the run's forecaster. A dry run prints its first task's pair.
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
  no-peek check add no line. A search never plays the season: a screen refuses it by name, and a
  tune refuses it in its search and reads it once, at the end, as one more line of the same
  ledger (**The tune**).
- `validate --season 2024 --forecaster prior`: gate 5 on a replay of the season named (default
  the latest replayable season on file; the hold-out is refused as the replay refuses it, the
  confirmation season because a gate needs no look at it), drafted on the forecaster named
  (default `prior`); since the standalone cut it is the only gate (**The gates as they stand**).
  `--h2h one_win|each_category` names the format it plays (default `one_win`).
- `screen --arm BASE.json [--levers NAME ...]`: each lever of a fixed list nudged once against
  the baseline arm, every pair played as `replay --arms` plays one, and a table of what moved
  (**The screen**). It takes `replay`'s flags for the cells and the world, `--max-minutes` to play
  a piece of it, and writes a folder under `data/sim/screens/`.
- `tune --arm BASE.json --screen NAME [--levers NAME ...]`: the values of the levers a screen left
  standing, searched one lever at a time on the seasons named, then the final set played against
  the baseline once on a season the search never played (**The tune**). It takes `replay`'s flags
  for the cells and the world, `--passes`, `--confirm`, `--max-minutes`, and writes a folder under
  `data/sim/tunes/`. It recommends; it promotes nothing.

An arm's spec file names its tier, every one of the twelve knobs, its opponents and what it
executes, may name its four fields (their defaults otherwise) and may name the fit it was written
for (`fit_sha`; another fit on disk refuses the run). Every run writes
`data/sim/runs/<stamp>-<kind>-<name>.json` with the code's commit, the fit's hash and file (whose
`lag` the run reads), on the book the book's hash, file and table's hash (`book_sha`, `book_file`,
`book_table_sha256`, PR Fd), the hold-out, the spec files verbatim, the execution model, each arm's
fields and its surrogate's pool and days, the reads table, the season scale, the period calendar's
source, and the results. A run first times one task and estimates the whole; the guard then refuses
a span that would touch 04:45-06:45 in the machine's local time, a draft room open on the API, or a
run over an hour without `--announced` (such a run is announced on the tracker and starts on the
user's word).

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
version 4's; 6 since the draft market (PR D4a), its figures version 5's under `--adp none`; 7
since the league shapes (PR D4b), its figures version 6's on the fixed shape; and 8 since the
league rules (PR D4c), its figures version 7's with nothing named (the nine categories, no held
slot); 9 since the waivers (PR Fa), its figures version 8's with nothing named (no waivers); 10
since FAAB (PR Fb), its figures version 9's with nothing named and by priority; 11 since the
head-to-head format (the format PR), its figures version 10's under `--h2h each_category` and in
a run whose seats weigh nothing, while with nothing named a seat that weighs now weighs the
matchup's odds; 12 since continuous waivers (PR Fc), its figures version 11's with the rule not
named; 13 since the rivals' adds and bids (PR Fd), its figures version 12's with nothing new named
(a FAAB run's league block now records `rival_bids`, `assumed` by default).

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
digests as it did. A waiver league's record carries the claims each team placed that day and the
morning's claims decided (`claims`, `cleared`, PR Fa), hashed the same way when not empty; in a
FAAB league each claim and each decision carries its bid (PR Fb), so a bid is part of the day. The season scale reads the arm's own forecaster. Under `--adp none` the draft
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

Under a table of average draft positions (`--adp espn`, PR D4a2) the check's league is drafted
as the run's path 0 drafts it, and a pair whose two arms draft apart has two leagues, both built
before either world, both leagues' seasons compared. What the check shows, and what it does not:
the league is built once, before either world, so the check is about the season's decisions never
reading a later line. That the draft reads nothing of the season rests on what it is built from
(the table, the forecasters' draft-day figures and the schedule of the opening days), not on the
check.

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
- `--no-peek` under a table (PR D4a2) builds the league as the run's path 0 drafts it: the table,
  the spread and the seats' own boards; a pair whose arms draft apart has its two leagues, both
  built before either world, and both leagues' seasons are compared ("The no-peek check", above).

`--adp none`, the default, is the draft as it was: a snake on the run's forecaster's values, the
market's view the same values. It is there so that a run before PR D4a can be run again and
compared: what the market changes is read against it.

**What a run records.** The payload's `adp` block names the source. Under a table it adds the
spread as given, the rules above in words, the limit of the seat's draft rule in words (`limit`,
"Its limits" below), and per season the table in counts (the players the
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
never refreshed. The table pools drafts of every scoring (above), so it is not a nine-category
league's. And the figure is the season's average as the log holds it, so the few drafts held after
the season began are pooled in: it is not strictly a preseason figure.

The arm's seat drafts on per-game value alone, with no regard for the games a player is expected to
miss or for where the room would take him; a market prices both. On the logs on file the effect ran
both ways by forecaster: under `espn` the seat's rosters held clearly more players who then barely
played than a rival's, under `prior` it ran the other way or nearly even. So the seat can finish
near the top or near the bottom of the room on every path. The paired change in playoff odds is
then zero with no spread, and the advisory verdict cannot hold in that cell; rank and category wins
still separate two arms. How the arm's seat should draft is open with the user.

## The league shapes (`sim/shapes.py`, PR D4b)

Every league a policy was judged in had twelve teams, thirteen slots, four adds a week and six
playoff teams over three weeks, so a result could hold only there. The user's ruling of
2026-11-06 has a league generator vary the team count, the roster slots, the weekly add limit
and the playoff format over modest ranges, and the ruling of 2026-11-07 makes the add limit a
parameter with the rest and sets the grid.

- **A league shape** (`LeagueShape`): the team count, the roster slots, the weekly add limit (or
  none) and the playoff format (how many teams, over how many weeks). A shape says nothing of the
  scoring or the held slots: those are the run's league rules (below). The season stays 22
  weeks; the playoffs are its last weeks and the regular season is what they leave. (The name
  `shape` is taken twice already: `replay --shape` is the oracle's error shape and `policy.Shape`
  decides which knobs a seat reads.)
- **The fixed shape**, the default (`replay --grid fixed`): the league before, twelve teams, the
  thirteen slots, four adds a week, six playoff teams over three weeks. On it nothing moves: a
  replay's record equals the one before PR D4b key for key, apart from the added `league` block,
  the version and its reason, and what names the run.
- **The grid** (`replay --grid full`): ten, twelve or fourteen teams; the thirteen slots or
  fifteen (two more bench); two, three or four adds a week or no limit; four playoff teams over
  two weeks, six over three or eight over three. Seventy-two shapes, in the order of
  `itertools.product(playoffs, adds, slots, teams)`, the team count fastest. The order is part of
  the record and is never changed (a test pins it).
- **One shape for a run** (`--league teams=10,slots=15,adds=none,playoffs=4/2`): each value one of
  the grid's, a key left out the fixed shape's; refused with `--grid full`. A pair's paths round
  up to that shape's team count. It is for the tests, a real look and a question about one shape.

**The visit rule** (`shapes.visit`, a pure function of the path and the grid). With N shapes, path
`i` plays shape `c = i mod N` in round `j = i div N`. Inside a round each team count's 24 shapes
take 24 turns in a row, each at its place `x = (16·p + 9·y) mod 24`, where `p` is the playoff
format's index and `y = 2·a + r` with `a` and `r` the adds' and the slots' indices: so `x mod 3` is
the playoff format and `x mod 8` is `y`. The turn is `24·j + (x + 5·j) mod 24`, the pair's seat is
`teams[turn mod n]` and the room's rotation is by the turn. Both arms of a pair share the shape, the
seat and the world, and the world's draws stay on `(seed, path)`: the turn decides seats only. On
one shape the turn is the path, so the fixed shape's seats are as before.

What it balances: at every whole round each shape is played once, a team count's seats are taken
within one visit of even (a room's seats and arms too), and a shape moves to a new seat each
round for at least five rounds. The places keep each axis's values near even draft positions;
the grid's own order in their place would put one playoff format on the first picks and another
on the last, and a test keeps that as the reason. The tie is small, not zero: the team count
itself sits 24 turns over 10 or 14 seats, the slots ride the seat's parity at an odd number of
rounds, and the adds keep a small tie that does not shrink with more rounds.

**A run on the grid.** `--grid full` rounds `--paths` up to a multiple of 72 (100 becomes 144), for
a pair and for a room. One round is one path a shape: it can say how the grid as a whole treats two
arms, and next to nothing about one shape. The verdict does not change: per forecaster and season
over all the run's paths, pooled as before, and on the grid those paths vary the league as well as
the seat and the draft. A pair on a grid adds the **by-axis table** (`by_axis`): for each cell, each
axis and each of its values, the paired change's mean, standard error and paths for every metric. No
verdict reads it; it is a description, not a test, the paths behind a value are few, and an axis's
values sit on nearly but not exactly even seats. The dry run times one path on the grid's largest
draft (fourteen teams of fifteen) with no add limit, so its estimate errs long; a full-grid run on
real seasons is far over an hour, and the guard's rule stands: it is announced and starts on the
user's word. `validate` stays on the fixed shape and says so.

**A draft that cannot be filled.** A draft takes the teams times the slots that are not held.
`cli.short_drafts` finds each draft of the run's shapes that may not fill: the season's draftable
players on the cell's forecaster are fewer, or under a table an arm's seat's own board (the
players its forecaster projects) is. Rivals could take every player on that board, so it is held
to the whole draft's need, and a draft refused on it might have filled; the pool's and a rival's
board are exact. A run that names a shape (`--grid full`, `--league`) is refused on any of them,
by name, before any path. On the fixed shape a short draft is played as it always was (the
made-up folder's 85 projected players fill seven or eight spots a seat; the pins rest on it),
and the run prints it and records it (`league.short_draft`).

**What a run records.** The `league` block: the grid's name, its axes, its shapes in order, the
visit rule in a sentence, each path's shape index and turn, the short drafts, and the league
rules (`rules`: the scoring, the points table or null, the held slots, and in a waiver run the
waivers, the wait and the waiver rule, `waiver_rule` (PR Fc), in a FAAB run the budget and the
rivals' bid scale, and in a categories run the head-to-head format, `h2h`; a points run adds
`points_note`, what its metrics are, and its season scale's note says what the gain is there; a
FAAB run adds `faab_note`, how the bids are made, and that the live rule's flags are not modelled;
a run that counts every category adds `h2h_note`, how its standings rank; a run under continuous
waivers adds `waiver_rule_note`, that every add is a claim and how the morning decides it, and in
a FAAB run its `faab_note` says, in the one clause that differs, that every add is bid on). Beside `executions` every replay records its `measure`, what
the format gives a seat that weighs (**The state and the policy**). A pair's
`seat.by_path` is each path's seat (on the fixed shape, as before). The knob reads table is one
per arm, as before: no axis of the grid changes what a seat reads (`policy.Shape`), and a test
says so.

**The league rules** (`shapes.LeagueRules`, PR D4c, PR Fa, PR Fb, the format PR). How the run's
league scores, what it holds, how it waives and how its standings count: one set for every path of a run, never an axis of the grid. The grid is the user's ruling
and its order is part of every record; as axes they would multiply it by twelve (two scorings,
six sets of held slots); a week in a points league and one in a categories league are different
quantities, and one verdict pooled over both would mix them; and the knobs they exist for are
read in one kind only (a run that asks about `plan_floor_points` is a points run).

- **The scoring** (`--scoring categories|points`, default `categories`). A points league scores a
  line on its table, a stat's points per unit (`--points pts=1,reb=1.2,...`: each key a stat of a
  line, a stat left out scoring nothing; a table that scores nothing is refused). Without
  `--points` the table is ESPN's published default for head-to-head points leagues: points 1,
  threes 1, field goals made 2 and attempted −1, free throws made 1 and attempted −1, rebounds 1,
  assists 2, steals 4, blocks 4, turnovers −2. It is a platform's default, a working default the
  user may replace. The draft values players by fantasy points (each seat's own board under a
  table too), a week is one result on the week's points, and the standings break a tie on points
  for ("The league"). A seat that weighs its moves (the exact and the surrogate tiers, a mirror
  rival) reads a week as the live build does: its odds are on fantasy points alone, each
  opponent's projected week carries its fantasy points and their spread, and the week so far is
  each side's score, the sum the standings count. PR 2b's move problem gave the opponents' weeks
  no table, a gap only a points league reaches: every week looked won and no move gained, so
  those seats stood still until PR D4c filled it. No new metric: `category_wins` is the week's
  one result (a win, a half, nothing), so it equals `matchup_wins`; the verdict's rule is
  untouched.
- **The held slots** (`--held IL=2,IL+=1`): `IL` 0 to 2 and `IL+` 0 or 1, after the bench; `NA`
  is refused. The draft takes the active spots only, so a held slot starts the season empty; a
  short draft's rule is unchanged, and under points the draftable players are the same players
  in another order.
- **The waivers** (`--waivers none|priority|faab`, default `none`; `--waiver-days N`, 1 to 7,
  default 2, named only with `priority` or `faab`). Below, "The waivers".
- **The waiver rule** (PR Fc, `--waiver-rule dropped|continuous`, default `dropped`, named only
  with `priority` or `faab`): which adds are claims. `dropped`, a dropped player's in his wait,
  every other add a free agent's; `continuous`, every add. The run's, never an axis of the grid,
  as the waivers themselves. The label says `continuous waivers` and leaves the default unsaid, so
  today's labels hold. Below, "Continuous waivers".
- **The budget and the rivals' bids** (PR Fb, named only with `--waivers faab`): `--budget`, the
  whole dollars each team starts with, 1 to 1000, default 100; `--rival-scale`, what a market
  rival's bid is multiplied by, above 0, default 1; `--rival-bids assumed|book` (PR Fd, default
  `assumed`), whether a market rival bids by the assumed form or on the price book ("The rivals'
  book"), refused by name without `--waivers faab` and when no book is on file. All three are the
  run's settings, never axes of the grid. The label says `on the book` and leaves the default
  unsaid; a FAAB run's league block records `rival_bids` either way. Below, "FAAB".
- **The head-to-head format** (the format PR, `--h2h one_win|each_category`, default `one_win`,
  refused by name with `--scoring points`: a points league's week is one result already). One
  win per matchup, or every category ("The league"). It is the run's, never an axis of the grid:
  a sweep over both formats is two runs. The label says `every category counted` under
  `each_category` and nothing under the default, as it says nothing of a league without waivers,
  so today's label is unchanged. The format moves the standings and the seats together: a seat
  that weighs weighs the format's measure (**The state and the policy**), so no run can name
  the mix every replay played before it (one-win standings, seats on expected categories).
- **The default** (`shapes.PLAIN`): the nine categories counted one win per matchup, no held
  slot, no waivers. With nothing named nothing moves: a replay's record equals the one before PR
  D4c key for key, apart from `league.rules`, the version and its reason (the claim counts and
  the waivers' keys in `league.rules` are a waiver run's only, PR Fa; the bid counts, the
  budget's keys and `faab_note` a FAAB run's, PR Fb, and a run by priority records as it did
  before; since the format PR a categories run's `league.rules` names its format, `one_win` by
  default, and `h2h_note` is an `each_category` run's; since PR Fc a waiver run's `league.rules`
  names its waiver rule, `dropped` by default, and `waiver_rule_note` is a continuous run's: with
  the rule not named every other key, `faab_note` among them, is as before, byte for byte, and a
  test pins it). A run that names rules prints one line
  with them, and the no-peek check and the dry run say them too. `validate` takes none of the three:
  it plays the fixed shape, the nine categories and no held slot, and says so; it takes `--h2h`
  (the format PR), one win per matchup by default. Since the format PR a seat that weighs moves
  under the default, which it weighs in the matchup's odds; under `--h2h each_category`, and in a
  run whose seats weigh nothing, the figures are the ones before it.

What a replay with them does not model, each plainly:

1. **A replay hears one status, `O`.** An absence is heard its lag after it begins and until its
   told return. `IL` and `IL+` both accept `O`, so in a replay an `IL+` slot is one more `IL`
   slot. Nothing is ever heard as questionable or game-time.
2. **Every absence is heard that way**, a single missed game too, so a held stint can be a day
   long. The counts (`held_stints`, `held_days`, `forced_drops`, `held_refused`) say how many and
   how long.
3. **Who uses a held slot:** a seat on the exact or the surrogate tier, and a mirror rival. The
   ranking tier queues one plain swap and never holds a player. A `market` rival swaps on the
   market's view and reads no status, so it never holds one either; a static rival makes no
   move. A league of market rivals with held slots is one where only the arm's seat uses them;
   no rule for the rivals is built here.
4. **Gate five has never seen such a league.** `validate` plays the fixed shape, nine categories,
   no held slot. What the surrogate tier does in a points league or with held slots rests on a
   gate that did not test it.
5. `stash_threshold` is unread until PR G. Without waivers a dropped player is on the wire the
   next morning, held or not; with them he waits ("The waivers").
6. The points table is the run's, and the default a platform's; a league's own table is given
   with `--points`.
7. **What the executor does not see.** When a cleared held player comes back over the spots, the
   executor (`policy._activate`) drops the least valuable active player by the day's per-game
   values, him included, a tie broken by the id as text as the engine breaks it. The engine's
   plan (`moves.comebacks`) can charge another player, in two ways: the keep rule (it never sends
   a kept player while another can go), and the day's choice of an activation's drop
   (`moves.choose_activation`, #360), which the simulator never calls, so the engine falls to its
   weakest. On such a morning the seat's queue was planned on one roster and lands on another.
   The held player's return is PR G's to finish, with `stash_threshold`.

**The waivers** (`policy.clear_waivers`, `policy.queue`, PR Fa). Under `--waivers priority` a player
who leaves a roster on the morning of day `d` (a seat's drop, a churn's held drop, a drop the world
forces) is on waivers until `d` plus the waiver days, his clear date, and nobody adds him as a free
agent before it. The draft's leftovers and a player who enters the league are free agents at once: a
free agent lands the next morning, a contested one by the day's rotation. An add of a player on
waivers is a **claim**: it waits for his clear date, and its drop and its held-slot moves are made
only if it is won, but for a churn on a claim: its held player leaves the next morning, won or not,
as the autopilot drops him on his own before the claim (which is why the engine offers a churn on a
claim only when the held player is worth nothing net of his return). **The morning's order**, in
every waiver league (`run.simulate`; Fc's review): first each team's cleared held players come
back, its active roster is trimmed to its spots and the held players its churns' claims drop
leave (`policy.arrive`); then the claims due are decided (`policy.clear_waivers`); then the rest
of yesterday's queue lands (`policy.land`). A claim so meets the roster its team has that
morning: a trim cannot take the player just claimed (it takes its weakest before he comes, and
a claim whose drop it took fails), and a churn's claim finds the slot its held player leaves.
Until Fc's review the claims came first, which let both happen; it moved only a league with held
slots, on a morning a held player came back or a churn's held player left. On the clear morning
the claims on him are decided by rolling priority: the team with the best
priority that still has a claim open that morning wins its first (in the order it placed them) and
goes to the back of the order; every other claim on that player is lost (no drop, counted as lost);
repeat until no claim is open. A player nobody claimed is a free agent from that morning. A won
claim its roster cannot take (its drop gone, no active spot open) fails, is counted apart from a
lost one and among the moves gone, and the player goes to the next claim on him. The first order is
the reverse of the draft's. The executor mirrors the autopilot's claim rules in its own code
(`READD`, a claim on a player the team dropped who still waits; `DROP_CLAIMED`, a move whose drop an
open claim takes; `ALREADY_CLAIMED`, a second claim on one add; `NO_ADDS`, a claim whose week has no
add left, the claims in flight counted), and the daily cap counts claims and free agents alike. The
seat's problem is built as the live build builds it: a candidate on waivers takes effect on his
clear date and is among `claims` (a churn on one only when the held player is worth nothing net of
his return), and the seat's claims in flight are folded in (`moves.with_pending`, as the live build
folds the queue's open claims). A market rival's pick may be a claim; its rate and view do not
change, and in a waiver league it picks among what it may add and drop (limit 4). The payload names
the model (`executions`), the audit holds two more rules and the counts count the claims (below).

What the waivers do not model, each plainly:

1. **A claim is charged to the week of the day before it lands.** Yahoo charges a claim to the
   week it clears in. They agree except on a Monday clear, which the simulator charges to the
   week before, as the engine's plan does: its add windows are shifted a day for a move that
   lands the next morning, and it shares them with the claims.
2. **The first order is the draft's reverse**, and a league that sets its own (last season's
   standings, a continual list) is not read. A failed claim keeps its team's place.
3. **A budget and bids** are FAAB's, below.
4. **Rivals claim on their own rules.** A market rival claims its view's best when he waits (or
   one of its best few, `among`, PR Fd).
   Its pick is the best player it may add, not one it already claims and not its own drop still
   waiting, and its drop the weakest it may drop, not one an open claim of its takes: the
   executor would refuse either (`ALREADY_CLAIMED`, `READD`, `DROP_CLAIMED`), and the rival would
   idle while its claim waits. Without waivers its pick is the pool's best and its weakest, as
   before. No rival is fitted to a league's claims: its rate and `among` are the arm's, set by
   hand against the book (PR Fd).
5. **Waivers run at one clear time, the morning.** Game-time waivers (a player locked until his
   game ends) and a clear time read from a league are not modelled.
6. `validate` plays the fixed league without waivers.
7. **Only a dropped player is claimed**, with the rule not named; under continuous waivers every
   add is a claim (below).

**FAAB** (`--waivers faab`, `policy.clear_waivers`, `policy.queue`, PR Fb). The wait, the claims and
the executor's claim rules are as by priority. Each team starts the season with the budget
(`--budget`, default $100), and its dollars left are on the state (`SimState.dollars`). A free
agent costs nothing: only a claim carries a bid. A bid is sealed when its claim is placed and
clamped then to its team's dollars left that day; the bids of its claims still open are not taken
out, as the live queue clamps to the budget the league reports (`season_queue.budget_of` returns
the team's FAAB balance as Yahoo gives it, and nothing there subtracts the bids in flight). On the
clear morning the claims are decided one at a time: the highest bid first, a tie by waiver priority
(best first), a team's own claims in the order placed. A claim whose player is gone is lost; one
whose roster cannot take him (its drop gone, no active spot open) or whose team's dollars left are
below its bid fails, and the player goes to the next; otherwise it is won, the team pays exactly
its bid and the claim is made as by priority. The order rolls (the winner to the back) only when
the win broke a tie, another claim on him open with the same bid. That is a working default: a
league may set it otherwise (rolling on every win, or never). The payload names the model
(`executions`: `free_agents_next_day_claims_by_sealed_bids`).

Who bids, and how:

- **The seat on the exact or the surrogate tier, and a mirror rival,** bid as the live queue bids:
  `autopilot.bid_of`, called through `sim/engine.py` with `typical_gain` and their constants, never
  copied. Its six inputs:

  | input | here | live |
  |---|---|---|
  | `gain` | the move's own gain on the judging horizon from the seat's own solve: the set's value less the set without it (`policy.gains_of`), on the engine's evaluator without the season term; a week-plan step's week increment (`stream.step_gains`) | the logged gain on `three` (`marginal`, the same difference); a plan step's score, its week increment plus the queue's weight times its three weeks' increment (`plans.step_score`) |
  | `typical` | `typical_gain` over the gains of the moves the seat recommended in the last 14 days, today's included: the plan floor until ten (the engine's, `stream.floor_of`: the knob, or in a one-win league its own floor in the matchup's odds, the format PR) | `typical_gain` over `season_queue.recent_gains`, the last 14 days' recommended three weeks' sets, today's included |
  | `budget` | the seat's dollars left that day | `season_queue.budget_of`, the league's FAAB balance |
  | `flag` | none: the live rule's flags are not modelled, and the payload says so | the day's flag on the player |
  | `sizing` | the arm's `faab_sizing` | the knob |
  | `availability` | `W` for a claim; a free agent places none | the player's mark (`W`, or `FA`, which bids $0) |

  Live scores a step as its week increment plus the queue's weight (`plans.THREE_WEIGHT`, the
  `three_weight` knob) times its three weeks' increment; the simulator has no queue weight until
  PR E, so a step here bids on its week increment alone (below). The decision carries what its claims bid on
  (`policy.Basis`): the bid is set in the queue on the state's dollars that day, so two arms
  still share a decision while their states agree.
- **The ranking tier** holds no gain in the engine's units (it ranks by per-game value) and bids
  $0. Its claims go by priority among the $0 bids.
- **A market rival** bids by an assumed form (`--rival-bids assumed`, the default) or on the
  price book (`--rival-bids book`, PR Fd, below). The assumed form is
  `round(rival_scale × gain ÷ typical × noise)` whole dollars, half up, clamped to its dollars
  left, where `gain` is its move's gain on its own view (the add's market value less the drop's),
  `typical` the median of every market rival's moves' gains in the 14 days before today (pooled
  over the rivals, today's left out, so the order the rivals decide in moves nothing), its own
  gain until there are ten (a bid of `rival_scale × noise`), and `noise` uniform on [0.5, 1.5) from
  the path's draw for its team and day, drawn after the pick (so nothing else it draws moves). The
  form's parameters sit in one place (`policy.RivalBids`), so a fit replaces them and not the
  world. `--rival-scale` sweeps it: a result whose sign flips across 0.5, 1 and 2 depends on how
  the league bids, which the simulator does not know.

  **On the book** its bid is `round(rival_scale × budget × Q(u))` whole dollars, half up, clamped
  to its dollars left (`bids.book_bid`), where `Q` is the book's quantile over its prices (the
  least share at or below which a fraction `u` of the rivals' winning bids falls) and
  `u = (below + U) ÷ (n + 1)`: `below` counts the market rivals' moves of the 14 days before
  today whose gain on the view is under this move's (the pool `typical` is read from, today's
  left out), `n` how many there are, and `U` the rival's draw on [0, 1) for its team and day,
  the one draw a claim the assumed form takes too (it takes `0.5 + U`). Until there are ten such
  moves, `u = U`. So a bigger move than the fortnight's usual bids higher on the book, and the
  book's spread is kept whole while the gains of one fortnight are like the next's ("The rivals'
  book", item 8, says when they are not). The prices travel with the run's rules and are never
  recorded but by the book's hash; `--rival-scale` multiplies the price as it multiplies the
  assumed form, and the seat's bids do not change.
- **A static seat** never claims.

In a FAAB run `faab_sizing` is read by a seat that bids, and the plan floor of the league's scoring
by the same seats (the typical gain until ten moves); in a one-win league that floor is the
engine's own and `plan_floor_cats` is read by nobody (the format PR). The audit holds the bids to three rules in
place of `claim_priority` and the counts count the dollars (below).

What FAAB does not model, each plainly:

1. **The rivals' bids are assumed**, their form and their typical gain alike, unless
   `--rival-bids book` names the price book, whose limits are its own ("The rivals' book"). The
   counts of what the seat paid above the next bid and fell short by are the world's
   knowledge of every bid: no seat reads them.
2. **Flags are not modelled**: live, a flagged player's bid is raised by its flag's factor; here
   no player is flagged.
3. **Only a dropped player waiting his days is bid on**, with the rule not named. A free agent
   lands the next morning at $0, contested by the day's rotation. Under continuous waivers every
   add is a claim and is bid on (below).
4. **The order rolls only on a tie** (above), the first order the draft's reverse.
5. **No pacing, cap or shading** on the seat's bid: the bid policy family is PR F2's.
6. **A week-plan step bids on its week increment**, where live bids on its score (the week
   increment plus the queue's weight times its three weeks' increment), until PR E brings the
   queue's weight.
7. `validate` plays the fixed league without waivers.
8. **A one-win league's bid has no live rule.** Live, the one league that counts one win per
   matchup never enters the queue, and the queue's floors stay in categories
   (`docs/AUTOPILOT.md`, #412). Here its gain is the matchup's odds and its typical gain until ten
   moves the engine's floor in odds, a working default (the format PR).

**Continuous waivers** (`--waiver-rule continuous`, with `--waivers priority` or `faab`, PR Fc).
The nine public leagues of the winning-bids table run them (the master, #172, 2026-11-17): every
unowned player is on waivers at all times, so **every add is a claim**, and no add is a free
agent's. The draft's leftovers and a player who enters the league are claimable from the first
morning, with no wait. A claim is placed today and decided on the morning its player clears: one
on a player nobody dropped lately the next morning (the daily run), one on a dropped player on his
clear date, the drop's morning plus the waiver days, as above. The next-morning landing and the
day's rotation decide nothing. The clear morning (`policy.clear_waivers`), once the cleared held
players are back, the rosters trimmed and the churns' held players gone (the morning's order,
above; under the rule nothing else lands, so a claim meets the morning's roster), decides every
claim due that morning in one pass, the claims on a free agent and on a dropped player alike, by the
league's waivers as above: by priority the best priority with a claim open takes its first and
goes to the back; by FAAB the highest bid first, a tie by priority, the winner paying its bid, the
order rolling only on a tie. Won, lost and failed mean what they mean above, a claim's drop and
its held-slot moves are made only if it is won, and a churn's held player leaves the next
morning, won or not. The executor's claim rules (`READD`, `DROP_CLAIMED`, `ALREADY_CLAIMED`,
`NO_ADDS`) apply to every add, the daily cap counts claims as before, and a claim is charged to
the week of the day before it lands (one placed on a Sunday on a player nobody dropped lands
Monday and spends the ending week's adds, as a free agent's add made that Sunday did).

- **The seat's problem** (`policy.problem_of`): every candidate is among `claims` and takes effect
  tomorrow, or on his clear date when later, as the live build marks the wire in such a league:
  every entry of the live queue in the nine leagues is a waiver entry. So the engine offers a
  churn (an add dropping a held player) on any add only when the held player is worth nothing net
  of his return (#221): a lost claim then costs nothing.
- **The bids**, in a FAAB run: every add carries one. The seat on the exact or the surrogate tier
  and a mirror rival bid by the live rule (`policy.live_bid`, the mark `W`), the ranking tier $0,
  a market rival by the assumed form (`policy.rival_bid`) or on the book (`bids.book_bid`),
  drawing its noise on every pick since every pick is a claim (with the rule not named it draws
  only on a pick on waivers, as before).
- **A market rival's pick** is among what it may claim, as in a waiver league. **A static seat**
  never claims.
- **The record**: `league.rules.waiver_rule`; `executions` names the model,
  `claims_only_by_priority` or `claims_only_by_sealed_bids`; the league block's
  `waiver_rule_note` says every add is a claim and how the morning decides it, and a FAAB run's
  `faab_note` says so in its clause on which adds are bid on. The dry run and the no-peek check
  print the rule with the others. The reads table is unchanged: no knob gains or loses a reader,
  so `policy.Shape` does not carry the rule.
- **The audit** holds what it holds by the league's waivers, and `claims_only` after them
  (below). **The counts** gain no key: the claim counts cover every add, so `landed` equals
  `claims_won` and `gone` equals `claims_failed` (no free agent's move is lost); no count is
  always zero.

What continuous waivers do not model, each plainly (the brief's working defaults):

1. **A player nobody dropped clears the next morning**, at the daily run; no league's clear time
   is read, and game-time waivers are not modelled.
2. **The draft's leftovers wait no days**: they are claimable from the first morning.
3. **The order** rolls as above, the first order the draft's reverse.
4. `validate` plays the fixed league without waivers.

**Not yet.** The ruling of 2026-11-07
makes the market rivals' add rate a parameter of the league shape, with a default written as a
number; it is not one yet. As a working default, open with the user, the rate stays what the
arm's file names (`{"kind": "market", "rate": ...}`), and a market block with no rate never
adds: the default was to come from a live league's record, the box holds no league, and a
measured figure does not go in the code. Since PR Fd the price book's `adds` says how often the
public leagues' rivals win a claim (a lower bound, "The rivals' book"), and an arm's rate and
`among` are set by hand against it and its `ours`; the rate is still the arm's, and no figure of
the book is a default in the code.

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
- `weekly_adds`: the adds charged to the week, landed and queued today, and in a waiver league the
  claims in flight charged to it, within the cap.
- `lands_next_day`: every player who joined a roster today is the add of a move the same team
  queued the day before, or of a claim it had open whose player clears today (the auditor keeps
  each variant's day before; on day one the setup's rosters stand for it, with nothing queued).
- `held_kind`: a player placed in a held slot today is one the slot's kind accepts
  (`moves.eligible`) under the status heard today.
- `lineup`: each starter on his team's active roster and eligible for his slot, no more starters
  in a slot than the league starts, every starter's team playing that day, nobody started whom the
  seat had heard was out. The lineup is a function of the setup, the state, the team, the day, the
  statuses and the values (`policy.starters_of`): no line reaches it, and changing a day's lines
  changes nobody's starters that day.

A waiver league is held to two rules more (`audit.WAIVER_RULES`, PR Fa; a run without waivers
reads only the six, and the payload lists the rules it read):

- `waiver_wait`: nobody who left a roster joins one before his clear date.
- `claim_priority`: every contested claim went to the best priority that morning (the day before's
  order replayed through the morning's decisions, a failed claim's team passed over), each winner
  then last, every lost claim's player to another team, and the order after the morning the
  state's.

A FAAB league is held to the wait and three rules in place of `claim_priority`, a run by priority's
rule only (`audit.BID_RULES`, PR Fb):

- `budget_floor`: no team's dollars go below zero.
- `bid_paid`: a won claim costs exactly its bid as placed, and nothing else moves the dollars:
  each team's dollars left are the day before's (the budget on day one) less its won bids.
- `bid_order`: each player went to the highest bid among the claims open on him that could be
  taken, a tie to the better priority: every claim on a won player that stood ahead of the winner
  (a higher bid, or the same bid and a better place in the day before's order) failed; every lost
  claim's player went to another team on a bid at least its own; the order rolls only on a win
  that broke a tie, and the order after the morning is the state's.

A league under continuous waivers (PR Fc) is held to one rule more, after its waivers' rules
(`audit.CLAIMS_ONLY`; the rule not named reads none):

- `claims_only`: nobody joins a roster but by a claim won that morning (the morning's decisions,
  `state.resolved`); the draft's rosters stand for the day before the first. `waiver_wait` still
  holds for a dropped player, and `claim_priority`, or the three bid rules, over every player
  decided.

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
held-slot stints and their days; and the starters' games played. In a waiver league only (a run
without waivers has no such keys, so its counts are as before PR Fa): the claims placed, won, lost
to a better priority and failed, and of those decided, how many had a team ahead of the seat's
when their player was decided and how many of those were lost (by priority under continuous
waivers, PR Fc, that is nearly every claim, a team being ahead in the order on almost every
morning: it is not a count of contests). In a FAAB league only (PR Fb; a
run by priority has none, so its counts are as before), after those: the dollars spent and the
dollars left at the season's end; the claims won at $0, lost to a higher bid, lost on a tie and
won with no other claim on the player that morning; the dollars won claims paid above the next
bid that could have been taken (the whole bid when there was none); and the dollars lost claims
fell short of the winning bid by. A claim is "behind" there when another claim on its player was
decided before it (the winner's, or one that failed). Under continuous waivers (PR Fc) the claim
counts cover every add, so `landed` equals `claims_won` and `gone` equals `claims_failed`; no key
is added. These counts are the world's knowledge of
every bid, not the seat's: no decision reads them. A pair (`--arms`) adds the rivals'
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
- What gate 5 compared (PR D4a2, `checks.surrogate_records`): each seat's row carries, in
  `detail.records`, a record for each sampled day.
  - It holds the exact tier's set and the surrogate's set as moves (the add and the drop, by
    id), and whether they are equal, which is what the gate counts.
  - It holds each set's worth by the exact tier's own objective: one evaluator of the exact
    tier's, on the key it searches (`QUEUE_SET`), with the season term when the knobs carry
    one, scores both sets on that day's problem, beside the worth of standing still.
  - A day left out says why instead: outside the calendar's weeks, or no problem built.

  `validate` prints a line for each seat and day: equal or not, and the two worths to four
  decimals. It names no player. The worths do not enter the gate's rule: a seat still passes on
  its matches alone, and `validate`'s exit code is what it was.
- The format (the format PR): `--h2h one_win|each_category`, default `one_win`. Gate 5 builds its
  league in the format named, so the two tiers solve the problem the seats play and the worths
  are in its measure (the matchup's odds by default). Under `each_category` its answers are the
  ones before the format PR. The block's `rules` names the format; the record holds no
  `measure` (the format's words say it).

## The screen (`sim/screen.py`, `cli.cmd_screen`, PR H1)

A screen answers one question: **which levers move a season at all?** It nudges each lever once
against a baseline arm, on the same paths, and lists what moved. It chooses no value, writes no
knob file and reads no live league.

    python -m pickandroll.sim screen --arm BASE.json [--levers NAME ...] [replay's flags]

- `--arm` is the baseline. For each lever, arm A is the baseline on the cheapest tier that reads
  the lever, set to whatever else makes it read, and arm B is A with the one nudge. The row and
  the pair's record say what both arms were set to.
- `--levers` names a subset; the default is the whole list. The rows always come in the list's
  order.
- The cells and the world are named with `replay`'s flags: `--seasons` (default the latest season
  on file that is neither the hold-out nor the confirmation season), `--forecasters`, `--paths`
  (default 48), `--seed`, `--workers`, the league's shape and rules, the table, the waivers,
  `--rival-bids`, `--name`, `--dry-run`, `--announced`.
- The hold-out is refused as everywhere. The confirmation season is refused too: a screen is a
  search.

**A screen is replays.** Each pair is planned, played, audited and recorded by the code `replay`
plays a pair with (`cli.replay_plan`, `replay_tasks`, `replay_payload`, which `cmd_replay` now
calls too): the same world, the same paired paths, the same audit, counts and record. `screen`
adds the list, the loop and the table, and nothing to a season. A `replay` run is main's, key for
key, and `replay_version` did not move.

**The list** is a table in the code (`screen.LEVERS`), written before any result. A lever is
added by the PR that builds it, and no flag invents a nudge.

| lever | nudge | tier | both arms are set to |
|---|---|---|---|
| `protection_floor` | one step down and one step up | surrogate | |
| `daily_cap` | minus 1 and plus 1 | surrogate | |
| `plan_floor_cats`, `plan_floor_points` | one step each way | exact | the week plan drawn and executed |
| `horizon_weight` | to each neighbour on the frontier | exact | `executes: weighted` |
| `faab_sizing` | to 0.5 and to 2 | surrogate | |
| `season_weight` | plus a quarter of the run's season scale, and plus a half | surrogate | |
| `playoff_weight` | to 1.5 | surrogate | a season weight: the baseline's, or with none a quarter of the season scale |
| `pool` | to 45 | surrogate | |
| `min_gain` | twice the baseline's | surrogate | |
| `weeks_ahead` | to 6 | surrogate | |
| `surrogate_days` | Monday only | surrogate | |
| `executes` | to `weighted` | exact | |
| `with_plan`, `execute_plan` | each flipped | exact | |
| `system` | to each other source; to the mix at 0.5 | surrogate | |
| `blend` | to 0.25 and to 0.75 | surrogate | `system: blend` (the mix at 0.5 when the baseline names none) |

The tier each lever is played on, in both arms, whatever tier the baseline names (the cheapest
that reads the lever):

- **the surrogate tier**, eleven levers: `protection_floor`, `daily_cap`, `faab_sizing`,
  `season_weight`, `playoff_weight`, `pool`, `min_gain`, `weeks_ahead`, `surrogate_days`,
  `system`, `blend`;
- **the exact tier**, six levers: `plan_floor_cats`, `plan_floor_points`, `horizon_weight`,
  `executes`, `with_plan`, `execute_plan`.

No lever is played on the static or the ranking tier.

- A lever with two nudges is two pairs.
- A floor's step is the Monday step's own grid, read through `sim/engine.py` and never run: the
  protection floor's step a game (0.05 in a categories league, 0.5 in a points league); a plan
  floor times 1.5 up, never above four times its default, and divided by 1.5 down.
- The frontier's order is the engine's (`week`, `even`, `natural`, `season`).
- **The season scale** is measured once, before any pair: the mean, over the first cell's paths
  that have one, of the baseline's scale on the surrogate tier on the path's first simulated day
  (the ratio: the `season_weight` at which the season term is the week gain's size). No day is
  played for it. The record keeps the figure, and a later piece uses the one on file.
  - **A path can have no scale.** The scale is read from the seat's single swaps on that first
    day. A path whose seat keeps its whole roster that day (the engine's keep rule protecting
    every player it holds) has no swap to read, and so no ratio. The mean rests on the paths that
    have one, and the record (`scale.paths` of `scale.of`) and the run's output say on how many
    of how many, so a nudge sized on few paths is seen as one.
  - A screen with no such path lists the season weight's nudges **not played**, and the playoff
    weight's too when the baseline holds no season weight.
  - Under a draft table this is common today: the arm's seat drafts on per-game value among
    rivals who draft from the board, so on the first day every player it holds beats the best
    free agent. The PR that makes the seat draft as a rival should thin it out.

What a row can be:

- **played**: the pair's figures (below).
- **not read here**, with the reason: the run's league does not read the lever. A knob and a field
  go by the reads table (`policy.reads`, `policy.field_reads`) on arm A as the pair would play
  it. `executes` is read on the exact tier. A week plan that is only recorded changes no season,
  so `with_plan` is read only by a baseline that executes the plan, and `execute_plan` only by
  one that draws it.
- **not played**, with the reason: the knob's own bounds refuse the nudge (the protection floor
  below its minimum, a daily cap of 0 or 4, the `week` weight), the grid has no step (a plan
  floor at its cap or at zero, twice a `min_gain` of 0), or no path has a season scale. The
  lever's other nudge is still played.
- **refused**: a nudge equal to the baseline's value (`pool` to 45 from 45) refuses the whole
  screen by name, before any path. Leave the lever out with `--levers`, or screen another
  baseline.
- In a FAAB run a plan floor's row adds one sentence: a seat that bids also reads the floor as
  its typical gain until ten moves, on the surrogate tier too, and that is not what the row
  screens.

**What a played row reports.** The paired difference B less A and its SE on every outcome the
verdict knows (category wins, matchup wins, rank, playoff odds, title), by cell, and both arms'
mechanism counts.

- **A lever survives** when its difference clears one SE, either way, on the measure the league's
  standings count: matchup wins in a one-win league and in a points league, category wins where
  every category is a result. With more than one cell, clearing it in one is enough.
- **Mechanism first.** A lever whose two arms' counts (the same adds, claims, bids and stints)
  and outcomes are equal on every standing path is marked "did nothing" and does not survive:
  the two arms played one season, and its difference is zero by construction. Both arms play
  one world, so equal counts with an outcome that differs is a lever that changed which moves
  were made, not how many; it did something, and the row keeps both facts (`counts_equal`,
  `outcomes_equal`).
- The table prints every row in the list's order, then the survivors.

**What a screen cannot say.** One season, one forecaster and forty-eight paths by default, and a
lenient bar by design. A survivor is a candidate for the tune (**The tune**), not a finding; a
lever that does not survive one screen is not shown to be idle in another league, season or
baseline. The SE is over the paths, not over the season's own chance.

**It survives the quiet windows.** A long screen is hours, and no job crosses a window.

- Each pair is its own unit. When it ends its record is written to
  `data/sim/screens/<name>/<lever>-<nudge>.json`: the pair's record as `replay` writes it, with
  one `screen` block (the screen's name and version, the row, and its result).
- `screen.json` in the same folder is the screen's record: the spec, `screen_version` 1, the
  code's commit, the fit's hash, the season scale, the measure and the rule, every row, the
  survivors and what is left. Everything that is a time sits under its `timing` (each pair's
  estimate, each piece's start and end), so a screen played in pieces records what one played
  unbroken does, apart from `timing`. It is written when a piece starts, after every pair and
  when the piece ends.
- Running the same command again plays only the pairs with no record yet. It first checks the
  spec against the one the folder was started with: the baseline arm, the levers named, the
  world's flags, `screen_version`, `replay_version`, the fit's hash and, when the rivals bid on
  the price book (`--rival-bids book`), the book's. Another spec is refused by name. Each piece records the code's commit it ran on, and a piece on another commit than
  the first says so. A run with nothing left to play is no piece: it writes the record again
  from the pairs' files and prints the table.
- `--max-minutes N` starts no pair whose estimate would pass N minutes from the start; the screen
  stops cleanly and says what is left.
- **The estimate.** Before any pair is played, one task of each pair still to play is timed, on
  the run's workers (a pair timed by an earlier piece is not timed again; the task timed is the
  pair's first, so it is not played twice). `--dry-run` prints the list as it would be played,
  each pair's estimate and the total, audits the timed tasks and writes nothing.
- **The guard.** The rule for a run over an hour (`--announced`) reads the whole screen's
  estimate, pairs already played included, whatever a piece of it takes. The routines' window
  is read against the piece: what is left, or `--max-minutes` when that is less.

## The tune (`sim/tune.py`, `cli.cmd_tune`, PR H2)

A tune answers the question after the screen's: **for the levers that moved a season, which values
does the simulator recommend, and does that hold on a season it never searched?** It recommends.
It promotes nothing, writes no knob file and reads no live league. Live changes only on the user's
word.

    python -m pickandroll.sim tune --arm BASE.json --screen NAME [--levers ...] [replay's flags]

- `--arm` is the baseline: the search starts from it, and the final set is played against it.
- `--screen NAME` names a finished screen of the same baseline arm in the same league kind. The
  tune takes its survivors, **the strongest first** by the size of the difference over its SE (a
  lever's place is its strongest surviving row's; a tie goes in the list's order).
  - **A screen that played the season the tune confirms on is refused by name.** Its survivors
    and their order were chosen on that season, so the season would not be withheld from what
    chose the levers. (A screen never plays the confirmation season itself; this is about
    `--confirm` naming another one.)
  - The league kind is read in force: the screen's shapes as its flags name them, whatever
    order they were typed in, and its rules.
  - A screen played under another `replay_version`, `screen_version`, fit, seed, paths or cells
    than the tune's is **not refused: it is said**. The tune prints what differs and keeps it in
    its record (`screen.differs`). The survivors and their order are taken as they stand, and
    each step rests on the tune's own pairs. An early screen stays usable after a lever PR
    lands; whether its order is still the right one to search in is the reader's call.
- `--levers` names levers by hand. With a screen they take the screen's order, the ones it did
  not play after them; with none, the list's order.
- `--seasons` names the search's seasons (default every season on file that is neither the
  hold-out, the confirmation season nor `--confirm`'s), `--forecasters` its forecasters; the
  world is named with `replay`'s flags, as a screen's.
- `--passes N` (default 1): the passes over the levers. A pass that moves no lever ends the
  search.
- `--confirm SEASON` (default the confirmation season, 2025-26): the season the final set is
  played on. `--confirm none` plays no confirmation: a look at the machinery, marked in the
  record and the output as "no confirmation, not a verdict".
  - **Whether that season can be played in the tune's world is asked before the first pair**,
    and in the dry run, not after the search. The check reads what is on file of the season
    before it begins, and plans no pair of it: the ledger's own lines, the season's draft table
    under `--adp`, the stand-ins' figures and each forecaster's. A refusal names the reason and
    the way out (another `--confirm` season, or `--confirm none`).
  - **Under a draft table the confirmation season is refused today**: its log carries one draft
    position for every player ("The draft market"), so it has no table. A tune under a table
    names another season to confirm on, which counts no look, or none.
  - **A forecaster the search reads must serve the season confirmed on.** The verdict is stated
    for every forecaster the search read, so a tune whose `prior` or `marcel` has no earlier
    season there is refused by name before anything is played.

**A tune is replays**, as a screen is. Every pair, the search's and the confirmation's, is
planned, played, audited and recorded by the code `replay` plays a pair with. A `replay` run is
main's, key for key, and `replay_version` did not move.

**Every choice is fixed before a result**: the levers and their order, each lever's values, the
measure, the seasons, the passes and the season confirmed on. They are the tune's spec, written
when its folder is started, and no flag lets a caller pick after seeing a figure.

**The search** goes one lever at a time, in the order above.

- **A lever's values** are the current one, each of the list's nudges, and **each nudge again**:
  three values a direction, and a lever with two directions is tried both ways, so up to five.
  The second step is derived from the list's row as it is:
  - a nudge written from the arm's own value is taken again by asking the lever from the nudged
    arm (a floor's step, the cap's, twice the `min_gain`, a share of the season scale);
  - a step along the frontier goes on to the next neighbour;
  - a step to a fixed number goes on by the same difference (`pool` 30 to 45, then 60);
  - a switch, a choice and a list (`executes`, `system`, `surrogate_days`, a flip) have no second
    step. The sizing's two start from no value at all, so they are written out in the code
    (`tune.SECOND`: half again is a quarter, double again is four);
  - the knob's own bounds refuse a second step as they refuse a first, a nudge equal to the
    current value is not played, and neither is a second step that lands on a value already
    listed. Each is listed with its reason.
- **Each value is a pair against the current arm**, on the same paths, on every season and
  forecaster the search names. Arm A is the current arm on the cheapest tier that reads the
  lever, set to whatever else makes it read, exactly as a screen's row.
- **A value's difference** is the mean over those cells of the paired difference B less A on the
  measure the league's standings count (matchup wins in a one-win league and in a points league,
  category wins where every category is a result). Its SE is over the paths: a path shares its
  seat and its draws across the cells, so a path's figure is the mean over its cells. The record
  keeps every outcome for every pair (category wins, matchup wins, rank, playoff odds, title)
  and both arms' mechanism counts.
- **The sign rule.** A value counts only when its difference is above zero in **every** cell. A
  value that helps in one season and hurts in another does not count however large its mean, and
  the step says so: "depends on the season" ("depends on the forecaster" when it is one season's
  forecasters that disagree).
- **The step.** A value is eligible when it counts and its mean is above one SE. The lever takes
  the eligible value with the largest mean (a tie to the first in the lever's order); with none
  eligible it stays. A noisy value does not block a sure one: a value with a larger mean that
  is not above one SE is passed over, and the step says so in words. A value with no SE at all
  (fewer than two paths stand) is not "passed over": its standing says it has none. The step is
  lenient by design, and the confirmation at the end is what guards it. The record keeps each
  value's pair, its standing and the reason for the choice. A value whose two arms played one
  season on every path "did nothing", as in a screen.
- An oracle's cells and a season that fails `espn`'s freeze check are shown and not read, as in
  a replay's own verdict.
- **What the current arm carries** is the lever's own value and nothing else. A value found on
  the exact tier, or with something else set in both arms, is recorded with what it was found
  under; the final set says which of its values the final arm does not read, and a final arm
  that reads none of them is the baseline's seat and is not confirmed.
- The season scale, where a lever waits on it, is the baseline's, measured once before the first
  pair and kept in the record. Two figures within the rounding a measured figure is kept to
  (four significant digits) are one value: a quarter of the scale taken twice is the half, and
  is not played beside it.
- **A later pass does not play a pair again.** A lever whose current arm no step has changed
  since its last try would be the same two arms on the same paths. The step takes the earlier
  pass's result, says so, and names that pair's file (`same_as`).

**The confirmation, and why a season is withheld.** A search picks the values that did best on
the seasons it played. Some of that is the values and some is those seasons' luck, and the search
cannot tell the two apart. So one season is kept out of every search and read once, at the end.

- **The hold-out (2024-25) is refused everywhere**, in the search and as `--confirm`, by name.
- **The confirmation season (2025-26) is refused in the search** by name, as is whatever season
  `--confirm` names, in the search's seasons and in the seasons of the screen named.
- When the search has ended, the final set (arm B) is played against the baseline (arm A) on
  that season, once, for each forecaster that serves it, on the cheapest tier that reads every
  value that moved. **Both arms are on that tier**, and the output says which it is, and which
  the baseline's own is when the two differ (an exact baseline whose only moved lever is the
  surrogate's is confirmed surrogate against surrogate).
- A named forecaster with no cell on that season is listed in the record
  (`confirmation.skipped`) and under the printed table, with `replay`'s reason. If the search
  read it, there is **no verdict**: the rule does not rest on the forecasters left. (The check
  before the first pair refuses such a tune, so this is met only when the files changed under a
  tune in flight.)
- **A cell that is there and not read is another thing.** It is `espn`'s when that season
  fails its freeze check, which only the season's own games show. (An oracle's row is a
  yardstick in the search too, so it is never one the search read.) The two cases side by side,
  for a forecaster the search read:
  - **no cell at all** on the season confirmed on: no verdict;
  - **a cell there and not read**: its row is in the table, marked "not read", and the verdict
    is stated on the other forecasters. Its line never says "recommended" alone: it says which
    forecasters the set was confirmed on and names each one that went unconfirmed, with why
    ("confirmed on prior alone, not confirmed on espn (its stored projection of that season
    fails the freeze check), which the search read"). The record's verdict block lists the two
    (`verdict.read`, `verdict.unconfirmed`).

  A set confirmed that way is confirmed under fewer forecasters than it was searched under,
  and the line is there so that it is read so.
- **The rivals.** The pair is played against the run's rivals, and again against static ones
  when the baseline's rivals are not static. Both cells are in the record. An edge against one
  kind of rivals only is flagged: against rivals that never move it may be an edge over nobody,
  and against one model of rivals only it may be an edge over that model.
- **A pair that is one seat is not planned.** Against static rivals the final arm can be the
  baseline's seat: what moved is read there only through the run's rivals (a mirror reads the
  surrogate's days on the exact tier). `replay` would refuse that pair, so the tune asks before
  the look is counted, plays the pair against the run's rivals alone, records the other kind as
  "the baseline's seat" (`confirmation.one_seat`, with each name the two arms differ in), and
  flags an edge against the run's rivals as one kind's only.
- **What only the pair's own plan finds** (a draft a named league shape cannot fill on that
  season) is met at the end. The tune then ends refused, with the final set in its record and
  `confirmation.status` saying why it was not played. No look is counted: the line is appended
  after the pair is planned and before it is played.
- **The verdict is stated on the finish**, the user's aim: playoff odds and final rank. A cell is
  ahead when its change in playoff odds is above zero, or its change in final rank below zero
  (a better finish), by more than one SE, and neither is the other way by more than one SE. The
  final set **holds** when every forecaster read is ahead against the run's rivals, is
  **against** when one is behind, and is **not shown** otherwise. The standings' measure is
  printed beside and decides nothing here. A path the audit voided, a forecaster the search
  read with no cell, or a cell with no SE, is no verdict.

**What a verdict means, and what it does not.**

- It is advisory. The words are "recommended" and "not recommended", never more.
- **One withheld season is one realization of the world.** Its SE is over the paths (the seats
  and the draws), not over the season's own chance: another season could have gone the other
  way. A verdict that holds is evidence, not proof.
- It is one league kind's. The flags name the league (its shapes, its scoring and format, its
  held slots, its waivers and budget), a tune's search and confirmation are played in it, and
  nothing is pooled across kinds. The kind is the shapes as played and the rules, not the name
  a flag gave them: one shape named with `--grid fixed` or with `--league` is one kind, and
  its looks are counted together.
- It is the forecasters' the search read, every one of them. A set ahead under one forecaster
  and not under another does not hold, and a forecaster with no cell on the season is no
  verdict. The one exception is a cell the season's freeze check leaves out: the verdict is
  stated on the others, and its line names that forecaster as not confirmed ("The
  confirmation", above).
- A tune with `--confirm none`, or one whose search moved nothing, has no verdict. A search's
  set alone is no recommendation: it was chosen on the seasons it was searched on.

**The ledger.** A look at the confirmation season spends it: after enough looks a set can be
chosen to suit it. So every look is counted.

- The ledger is `data/sim/confirmation-looks.jsonl`, the one a written `replay` of the season
  already appends to. It lives under the data folder a run names, never in the repo.
- A tune appends one line before its first confirmation pair is played: when, the tune's name,
  its spec's hash, the code's commit, the fit's hash, the search's seasons and forecasters, and
  the league kind. One line covers both kinds of rivals.
- The record (`confirmation.look`) and the printed verdict say **"look n for this league kind"**
  and the line's number in the whole ledger, where a replay's looks are counted too.
- A second look is counted, never hidden and never refused.
- A tune taken up again counts once. The same tune started again in a new folder reads the season
  again and is another look.
- A piece learns whether it may play the confirmation's pair (the hour's rule, the routines'
  window, `--max-minutes`) before that pair is planned, so a piece that is stopped there has
  read none of the season's games. What the check before the first pair reads of the season is
  what was on file before it began (its draft table, a stored projection), in every piece and
  in the dry run.
- A finished tune whose line the ledger no longer holds (the file removed, the folder copied
  without it) says which look it was from its confirmation pair's own record, says the ledger
  lost it, and adds no line. A folder with pairs and no `tune.json` is refused by name: the
  record says when the tune was started, which is how its look is found again.
- A dry run writes no line. Neither does `--confirm none`, nor a tune confirmed on another
  season: the ledger's numbers are looks at the confirmation season.

**Pieces, the estimate and the guard** are a screen's.

- Each pair is its own unit, written when it ends to `data/sim/tunes/<name>/`: a value's pair as
  `p<pass>-<lever>-<nudge>.json`, the confirmation's as `confirm-run.json` and
  `confirm-static.json`. Each is the pair's record as `replay` writes it with one `tune` block.
- `tune.json` is the tune's record: the spec, `tune_version` 1, the order and where each place
  comes from, what the screen named was played under that the tune is not, every step (each
  value's pair with its result, the choice and why), the final set, the confirmation (each
  cell's differences, finish, mechanism counts and `replay`'s mark when the rule does not read
  it, a forecaster with no cell, a kind of rivals that is one seat, the look, the verdict) and
  what is left. Everything that is a time sits under `timing`.
- Running the same command again plays only what has no record yet. It first checks the spec
  against the one the folder was started with (a screen's spec, and the tune's own: the levers
  in their order, the passes, the season confirmed on, the screen named, `tune_version`).
  Another spec is refused by name.
- `--max-minutes N` starts no pair whose estimate would pass N minutes from the start.
- **The estimate.** One task of each lever's first pair is timed before anything is played. The
  whole tune's estimate is every value of every lever, as the baseline lists them, for every
  pass, **and the confirmation's pairs**. `--dry-run` prints the order, the values, the
  confirmation and the total, and writes nothing, the ledger included. The total is "about":
  a later pass from a moved value can list more pairs, and a lever that has no pair from the
  baseline (it is read only once another has moved) is timed inside the search, when it first
  has one.
- **The guard.** The rule for a run over an hour (`--announced`) reads the whole tune's estimate,
  the confirmation included, whatever a piece of it takes. The routines' window is read against
  the piece. Because a search can grow past its plan, **the hour's rule is read again before
  every pair**: the pairs met so far, this one and the confirmation still ahead. A tune that
  comes past the hour that way stops refused, its record written, until it is announced. A
  tune that was announced, or whose estimate the caller gave (`--expected-hours`), is not asked
  again. `--announced` is passed only on the user's word: it says the run was announced on the
  tracker and that the user said to start it.

**What a tune cannot say.** It searches one lever at a time, so it does not see two levers that
only help together. It tries a few values a lever, so "the best of those tried" is all a step
claims. The estimate lists the values from the baseline, and a later pass may play values it did
not list. The check before the first pair asks what a season's files say; what only a whole plan
of the confirmation's pair finds is still met at the end.

## Runs

Every command runs through the commands' guard: low priority, never when its span touches 04:45
to 06:45 in the machine's local time, never while a draft room is open on the API, and a run
expected over an hour is announced on the tracker and starts on the user's word (`--announced`
says that has happened, and is passed only then). The no-peek check runs two seasons before it
can time one, so the guard gives it a span of a quarter of an hour (`NO_PEEK_HOURS`) and refuses
it when that span touches the window.

**A tune under a draft table names its `--confirm` season.** The default, the confirmation season
(2025-26), cannot serve such a tune today: its log carries one draft position for every player,
so it has no draft table ("The draft market"), and a league drafted on a table cannot be played
on it. The tune is refused before its first pair, and in its dry run, until it names a season
that has a table and that neither its search nor the screen it names played, or `--confirm none`.
A confirmation on another season counts no look. Which season that is belongs to the run's plan,
not to the command.

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
