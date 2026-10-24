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

## Runs

Every command runs through the script's guard: low priority, never between 04:45 and 06:45 on
the Mac's clock, never while a draft room is open on the API, and a run expected over an hour is
announced to fantasyMASTER first. PR 2 brings the policy adapter, the runner on common random
numbers and the `compare`, `replay` and `room` modes; PR 3 the Monday hook, after the user's
rulings on the threshold, the block, the promotion and which knobs the simulator may tune.
