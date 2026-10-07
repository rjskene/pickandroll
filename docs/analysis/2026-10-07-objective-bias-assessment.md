# Bias and data-mining risks in the category-win objective (assessment, 2026-10-07)

Why: late-round picks from the planner look unlike what the room drafts around them (in the
slot-6 bot cell on main: a backup centre, two rookies, a role-playing wing and a shooting
specialist across rounds 8-13; in mock 7 a round-5 rookie forward). A pick can be right and look
strange, but the same mechanisms that make a model pick differently from the market also make
it overfit to its own inputs. This note lists where the objective could be biased or mined, how
each would show in late picks, and the test that would tell. It proposes no change; the tests
decide. Facts about the objective are from `optim/objective.py`, `optim/horizon.py`,
`projections/zscores.py`, `draft/state.py` and `api/solver.py` at main 331938d.

## How a late pick is valued today

* Totals are per-game z-scores times projected games, z-scored against a pool of
  `total_picks` players (156 here) chosen by total z over three passes; percentage categories
  use impact (makes above the pool's shooting on the player's attempts).
* The plan values a player above replacement level: the mean z, per category, of the players
  ranked just past the last pick by total z (`replacement_level`).
* The horizon plan picks one player per future pick and counts him at availability times value
  (`A[p, k] * z[p, c]`); the pool per pick is the 80 best by availability-weighted total z.
* The objective is `sum_c Phi((T_c - mu_c) / sigma_c)` with `mu`, `sigma` the mean and spread
  of team totals over 36,000 teams from 3,000 simulated drafts of z, ADP and LP bots on the
  same projections; piecewise-linear with breaks at ±0.5, ±1.5, ±2.5 sigma; 1 % MIP gap.
* The drafter takes `candidates[0]`; candidates within 0.05 expected categories of the best are
  flagged a tie, but the first one is still the one clicked.

## Mechanisms, symptoms, tests

Ordered by how likely each is to drive a late pick, with the test that would confirm or clear it.

### 1. The tie band hides arbitrary choices (cheap, pre-draft)

Late picks differ by hundredths of a category. Inside the 0.05 band the solver's incumbent
decides which candidate is first, and that depends on the search path, not on value. A
"strange" late pick may be one of six near-equal players, chosen by chance.

Symptom: the `tie` flag on `candidates[0]` in rounds 8-13; the first candidate changing between
two solves of the same board (the branch solve and the live solve).

Test: from the fidelity logs of mocks 3-7 and the settled replays, count the ties at
`candidates[0]` by round, and how often the branch's #1 and the live #1 differed on the same
board. If most late picks are ties, the fix is a tie-breaker, not a model change: inside the
band prefer the market (lower ADP) or the sturdier player, and show the band in the UI.

### 2. Cheap z in volume-blind categories (pre-draft, log-based)

Turnovers reward players who do not handle the ball; impact FG% rewards low-attempt bigs;
blocks and steals come cheaply from specialists. Late in a draft the roster sits near the
middle of several curves, where the slope is steepest, and the plan buys the cheapest z there.
That is the textbook z-drafting tilt toward low-usage bigs and 3-and-D wings.

Symptom: late picks whose value to the plan comes mostly from TOV, FG% and BLK while the market
favourite at the same pick leads in PTS, AST and 3PM.

Test: decompose each late pick's first-order price (`slope_c * (z_pick - z_alternative)` per
category) against the highest-ADP player available; report the share of late picks whose edge
is more than half TOV plus FG%. Sensitivity: rerun the settled replays with TOV weighted 0.5 and
with the percentage categories weighted 0.75 (the `weights` parameter exists) and list which
late picks change. A tilt that survives a modest reweighting is a model preference; one that
flips is noise amplified by the curve.

### 3. Projected games decide the late rounds (pre-draft, log-based; links to #2)

Totals multiply per-game value by projected games. A durable 78-game role player outscores a
better 62-game player, and in the late rounds the game count is the biggest single lever. This
is the mechanism behind the Doncic-Daniels tie recorded on #2, and it is strongest exactly
where the pool is full of healthy low-usage players.

Symptom: late picks with projected games well above their ADP neighbours.

Test: for each late pick in the cells and mocks, compare projected games with the median of the
ten players nearest in ADP. Sensitivity: rerun the settled replays with games capped at the
pool median and with per-game z times a flat 65 games; count the picks that change. The
durability study on #2 then decides what replaces the point estimate.

### 4. The curve and the pool come from the same projections (self-reference)

`mu` and `sigma` are fitted on teams built from the projections by bots that rank by the same
z. The z pool and the replacement level are also defined by that z. A systematic projection
error (say, projections that overrate rookies or underrate returning veterans) moves my totals
and the league's assumed totals together, so the odds look calibrated in-sample while the
picks lean into the error. Expected categories won on the scorecard (D5) is scored with the
same projections and curve that chose the roster: it is an in-sample number.

Symptom: none visible from inside the model; it shows only against real outcomes.

Test (post-draft unless past projections exist): refit the curve on the league's actual
category totals from `data/yahoo_history/category_totals.csv` for the seasons it covers and
compare `mu`, `sigma` and the late picks they produce with the simulated curve's. Out of sample:
replay a past league draft with that season's preseason projections, score the model's roster
on the season's actual totals against the league's actual teams, and compare with the teams
that finished top three. Projection-versus-actual by player type (the #2 comment's first item)
is the same test at the player level.

### 5. Availability shapes the plan's later rounds (pre-draft, data exists)

The plan counts a future player at `A * z`. A player 95 % likely to be there contributes nearly
all of his value; a 40 % player less than half. Later rounds of the plan therefore fill with
the market's unloved players by construction, the pool per pick keeps the 80 best by
availability-weighted z, and the current pick is priced against that plan. The survival table
comes from drafts of z, ADP and LP bots; if the bots take the projections' favourites earlier
than this league's humans do, `A` is too low for them and the plan steers away from players the
room would have left for us.

Symptom: the plan's rounds 9-13 listing players the league has historically drafted two or
three rounds later, or never.

Test: calibration of `S[p, k]` against the league's own eleven seasons of keeper-adjusted ADP
(`data/yahoo_history/adp_*.csv`): by round, the share of planned players actually gone by that
pick in the league's history. Sensitivity: `min_availability` 0.005 → 0.05 and the pool cap 80
→ 40 on the settled replays; a plan that changes its late rounds under either is leaning on
long shots or on the long tail.

### 6. Kinks in the piecewise curve

The LP parks totals at the breakpoints, where the slope steps. A late pick that nudges a total
across −0.5 sigma earns a step the smooth curve would not grant.

Symptom: category totals of the plan sitting within a few tenths of a breakpoint; a late pick
whose first-order price under the smooth curve is a fraction of its MILP value.

Test: re-evaluate every settled plan under exact Phi and list the late picks whose rank among
the candidates changes; try breaks at ±0.25 steps on one replay and compare picks.

### 7. The opponent model is a simulated league, not this room

Phi is against a random team from the simulation. By round 8 the other eleven rosters are
nearly known, and the Team card already tallies them. If the room's actual totals sit far from
the simulated `mu` in a category, the late picks target the wrong middle: buying a category the
room has conceded to us, or chasing one it has run away with.

Symptom: the room's projected team totals at pick 100 differing from the simulated `mu` by
more than a sigma in a category where the late picks concentrate.

Test: from the fidelity logs of mocks 5-7 and the cells (the API records the score and the
room's rosters), compare the room's distribution of projected totals at picks 60, 100 and 140
with `SIMULATED_MU` and `SIMULATED_SIGMA`; if they diverge, the refit-from-room option that
`CategoryCurve.from_totals` already supports becomes a live candidate, with the sigma scale as
the guard against over-trusting eleven data points.

### 8. The gates were run on two fixtures (data mining proper)

Every value gate of the pre-draft programme ran settled replays of two recorded rooms at four
slots, and the parameters that passed (pool cap, candidate counts, sigma scale, breaks) were
accepted on those. Nothing was held out.

Test: score the same parameter choices on the rooms of mocks 3-7 (five more rooms, different
drafters) as a hold-out; any parameter whose advantage disappears there was fitted to the two
fixtures. The historical replay in item 4 is the real hold-out.

## What can run before the draft (2026-10-14)

Items 1, 2, 3, 5 and 7 need only the fidelity logs, the settled-replay harness and files
already under `data/`; a day of CPU with no code change outside `data/scratch/`. Items 4 and 8
need past-season projections or the recorded mock rooms as hold-outs and are post-draft unless
the projections are at hand. No model change is proposed here; a change follows a test, in its
own issue, and the drafter's tie-breaker (item 1) is the only candidate small enough to ship
before the draft if the counts call for it.
