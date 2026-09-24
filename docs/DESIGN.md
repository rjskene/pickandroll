# pickandroll design

Fantasy basketball draft optimizer for 9-category head-to-head leagues, rebuilt from the 2019-2021
`puntgm` Django project. This document records the architecture, the data contracts and the
optimization models so the code can be judged against a stated plan.

## Goals

1. Recommend the next pick during a live Yahoo draft, re-solving after every pick.
2. Value every category by the odds of winning it, so a punt is an outcome the board forces,
   never a goal the user picks (the 2026-09-23 study: the category-win objective won 10.3 of 11
   simulated matchups against 5.9 for sum-of-z with an explicit two-category punt).
3. Use Basketball Monster projections, refreshed several times a day, as the primary input.
4. Reuse the same roster model for waiver moves, trades and weekly matchups after the draft.
5. Solve ahead of the clock: the answer for the next pick is computed while the other teams
   pick, so nothing waits on a solve when my turn comes.

## Pieces and the dependency rule

```
src/pickandroll/
  projections/   schema, z-scores                                  (core)
  optim/         roster MILP, horizon plan, category-win curve,
                 pricing, shared process pool                      (core)
  availability/  ADP availability curves, simulated survival table (core)
  draft/         league settings, snake-draft math, draft state,
                 simulated drafters, league simulation             (core)
  sources/bbm    Basketball Monster export parser and Playwright fetcher
  sources/yahoo  Yahoo Fantasy league, players, draft results
  api/           FastAPI app, background solver, server-sent event stream
web/             draft-day UI
```

Core packages import nothing from `sources` or `api`. `sources` never imports `api`. This keeps the
solver testable with synthetic data and lets any projection provider be swapped in.

## Data contract

Every source produces a `ProjectionSet`: metadata (`source`, `label`, `horizon`, `as_of`, `start`,
`end`) plus a DataFrame indexed by player id with these columns:

| column | meaning |
| --- | --- |
| `player`, `team`, `positions` | display name, team code, positions as `PG/SG` |
| `games`, `minutes` | projected games and total minutes over the horizon |
| `pts`, `threes`, `reb`, `ast`, `stl`, `blk`, `tov` | totals over the horizon |
| `fgm`, `fga`, `ftm`, `fta` | makes and attempts, so team percentages can be rebuilt exactly |

Stats are always totals over the horizon. Per-game exports are multiplied by games at parse time.
Extra columns are allowed and are carried through unchanged (Basketball Monster's own value
columns arrive as `bbm_z_*`, Yahoo ownership as `yahoo_owned_pct`).

Snapshots from paid sources live in `data/` and are gitignored.

## Z-scores

`projections.zscores.zscores` scores every player against a draft pool:

* Counting categories: `(x - mean) / std` over the pool. Turnovers are negated.
* Percentage categories: impact `makes - pool_pct * attempts`, then standardized. Summing impact
  over a roster and dividing by summed attempts reproduces the team percentage exactly, which is
  what makes FG% and FT% linear in the optimizer.
* The pool is chosen iteratively: score everyone, keep the top `pool_size` (teams times roster
  size) by total, recompute pool statistics, repeat.

The legacy code averaged the z-score of makes with the z-score of percentage. Impact replaces that.

## Model 1: roster MILP (`optim.roster`)

Variables: `x[p, s]` binary, player `p` fills slot `s` (only created for eligible pairs);
`y[c]` binary, category `c` is active; `w[p, c]` in `[0, 1]`, the linearized product
`x_p * y[c]`; `t` real, the floor on active category totals.

Objective: `max (1 - balance) * sum_c weight_c * sum_p z[p, c] * w[p, c] + balance * t`.

Constraints:

* every slot filled once, every player used at most once;
* `sum_c y[c] >= n_cats - max_punts` (auto-punt); when the punt is fixed, `y` are constants and
  `w` collapses to `x`;
* `w <= x_p`, `w <= y_c`, `w >= x_p + y_c - 1`;
* `t <= total_c + M_c (1 - y_c)` for every category (max-min balance);
* optional team percentage floors, linear in `x`: `sum_p x_p (makes_p - floor * attempts_p) >= 0`;
* optional minimum projected games;
* locks (must draft) and blocks (never draft);
* optional availability weights that scale a player's value by the probability they are still on
  the board, used for planning solves beyond the next pick.

Slots default to Yahoo's lineup: PG, SG, G, SF, PF, F, C, C, UTIL, UTIL and three bench spots.
Auction drafts add `sum_p price_p x_p <= budget`.

Solver: HiGHS through PuLP (`highspy` ships the binary in the wheel). Measured on a 188-player
Basketball Monster export with 13 slots (Apple Silicon, single thread):

| variant | time |
| --- | --- |
| fixed punt | ~70 ms |
| automatic punt, up to two categories, single model | ~350 ms |
| automatic punt with max-min balance, single model | ~7 s |
| `punt_scan`: all 46 punt sets as fixed-punt models in a process pool | ~1.0 to 1.3 s |
| `pick_pool` over 8 candidates, fixed punt | ~0.7 s |

The balance term weakens the LP relaxation badly when the punt is free, so `solve_roster` routes
balanced auto-punt solves through `punt_scan`, which is exact and also produces the strategy
table (best roster and objective under every punt). During a draft the punt is usually fixed
after the first few picks, and fixed-punt solves are what run on the clock.

Future speed-up if needed: build the HiGHS model once and re-solve with changed objective
coefficients per punt set instead of rebuilding through PuLP, which is most of the per-solve cost.

`draft.state.DraftState` holds the live board (settings, projection set, z-scores, pick log) and
builds the roster problem for the current state: my roster locked, everyone else's picks blocked.
`recommend` prices the top available candidates with `pick_pool`.

`pick_pool` forces each candidate onto the roster in turn and reports the objective lost versus the
unconstrained optimum. That difference is the price of taking the candidate now and is what the UI
shows as the pick recommendation list.

## Model 2: rolling-horizon draft (`optim.horizon`)

Plan one player for each of my remaining picks. Variables `y[p, j]` (player `p` is the plan for my
`j`-th remaining pick) and `x[p, s]` (slot assignment for the final roster, locked players
included), linked by `sum_j y[p, j] = sum_s x[p, s]`. Each pick gets exactly one player, each slot
exactly one player. The objective weights every planned player's z by `A[p, j]`, the probability
they are still on the board at that pick given they are on the board now, so stars go early and
late picks lean on players that will actually last. Only the first pick is acted on; after the
next real pick the plan is re-solved from the new state.

`horizon_pick_pool` forces each candidate to be the first pick and reports the objective lost,
which now includes the risk of waiting: a player the plan would take later with high probability
costs little to skip now, a player likely to vanish costs a lot. It also reports
`p_available_next`, the chance the candidate survives to my following pick.

The punt is fixed inside Model 2 and empty on the product's path; `punt_scan_horizon` and
Model 1's `punt_scan` remain for studies that want an explicit punt.

Measured on the 188-player export with the sum objective: one plan solves in about 300 ms, a
candidate pool of eight in about 2.6 s. Picks with too few plausible candidates keep the 25
most likely players so late picks in a thin pool stay feasible. When my remaining picks and
open slots disagree (traded picks, unusual manual entry) the API falls back to Model 1.

## The category-win objective (`optim.objective`)

The sum of category totals maximizes its own scale and piles surplus into categories already
won. The default objective instead values each category by the chance of winning it:

    max sum_c Phi((T_c - mu_c) / sigma_c)

where `T_c` is the roster's (expected) total in category `c` and `mu_c`, `sigma_c` are the mean
and spread of team totals across the league. The objective reads as the expected number of
categories won. A category the board has made unwinnable falls to near-zero marginal value and
the plan stops paying for it: the punt emerges, nobody chooses it.

* `Phi` is S-shaped, so the models carry a piecewise-linear version with breakpoints at ±0.5σ,
  ±1.5σ and ±2.5σ. The total is split into one bounded piece per segment; a binary per segment
  link forces pieces to fill in order wherever the next segment is steeper than an earlier one
  (with the flat tails of `Phi` that is every link).
* `mu` and `sigma` default to `CategoryCurve.simulated`: the fit over 36,000 teams from 3000
  simulated twelve-team drafts on Basketball Monster projections of 2026-09-21 (means −0.7 to
  +0.4 z, spreads 3.5 to 4.7 z). A session can refit them from its own league simulation, load
  them from a JSON file, or scale every sigma (`sigma_scale`; above one is flatter, a hedge for
  weekly noise: doubling sigma cost 0.2 matchups in the study, halving it cost 0.65).
* The plan measures totals above replacement level, so the curve is shifted by
  `-roster_size * level_c` for planning and evaluated on raw totals for display.
* The derivative `slope_c = phi((T_c - mu_c) / sigma_c) / sigma_c` is the marginal value of one
  more z-point in a category (categories won per z). It prices any deviation from the plan to
  first order in microseconds: `sum_c slope_c * (value of the alternative - value of the
  planned pick)`, and it is what the Categories card shows as "marginal".
* The curve MILP is much harder than the sum at early picks (the LP relaxation hedges between
  players). The plan keeps the 80 best availability-weighted candidates per pick (objective loss
  0.008 of 5.2 at pick one), solves to a 1% MIP gap and keeps its incumbent when the time limit
  (20 s by default) is hit; a curve solve with no incumbent at all falls back to the sum plan
  and says so.

Under the curve an explicit punt can only remove a non-negative term, so the roster model
requires a fixed punt and routes free-punt solves through the scan; the API never passes one.

## Availability

`availability.adp` models `P(available at pick k) = 1 - Phi((k - adp) / sd(adp))` with `sd`
widening for later picks, and the conditional form `S(k) / S(now)` during a draft. ADP comes from
Yahoo's player resource when the feed is attached; otherwise a stand-in ranks players by
Basketball Monster's rank column or by total z.

`availability.survival.SurvivalTable` replaces the formula with the record of simulated drafts:
`S[p, k]` is the share of drafts in which player `p` was still on the board when pick `k` came
up, used conditionally as `S[p, k] / S[p, now]`. `draft.league_sim.simulate_league` builds one
for a session: every team is a simulated drafter (`z`, `adp` or `lp` with a punt of its own,
the mix the study used), drafts run in the shared process pool (about 1.2 s per draft per core),
and the same run yields the league's `mu` and `sigma`. A session asks for it at setup
(`survival: simulate`, 300 drafts by default, under a minute on eight cores), loads a saved
table (`survival: file`), or keeps the formula. Players a table lacks fall back to the formula.
In the study the table changed nothing under the sum objective and recovered 2.5 z of value
under the curve with better-calibrated odds (Brier 0.07 against 0.11).

## Solve ahead of the clock (`api.solver`)

Time limits are a safety net, not the budget. The board before the draft is known, so the
session's background solver plans and prices as soon as the session exists, and again after
every change (`Session.publish` with a version bump wakes it):

1. Snapshot the board under the session lock (building the problem takes milliseconds) so
   picks can land while the solve runs.
2. Solve the plan (incumbent kept at the time limit).
3. Price every candidate to first order at once from the curve's slopes, then exactly by
   forcing each first in the shared process pool; the first-order price also covers the whole
   board (the `cost` column).
4. While someone else is on the clock, solve "if he is gone" scenarios for the best candidates
   who could be taken before my pick, so the answer for that case is ready before it is needed.
5. Publish a `recommendation` event; the UI shows the latest result and marks it stale (with a
   re-plan under way) when the board has moved since.

Changes that arrive during a solve coalesce into one more solve. A pick made while the solver
is mid-flight is at most one pick stale by the time my turn comes; measured on the 234-player
export a full round (plan, nine exact prices, three scenarios) takes about 20 s, and the round
leverage experiment showed pick one carries no alpha anyway.

## Scoreboard

Every number on the Team card is expected categories won on the session's curve (the z value
rides along): the plan before my first pick (the benchmark, frozen at the last solve before that
pick), the best plan seen during the draft, the latest, and once the roster is full the final
roster's odds. Matchups are tallied against the league's projected finals: each opponent's
drafted total plus replacement-level fill for their open slots, a matchup won when my expected
final leads in a majority of categories. The Categories card shows per category my drafted
total, the expected final, the odds and label (conceded below 15%, secured above 85%), the
opponents beaten now and at the end, and the marginal value.

## Live draft loop

Yahoo exposes no push API. During a draft the app polls the league resource's `draftresults` every
five to ten seconds, diffs the pick list, updates the draft state (taken players, my roster, next
pick number), wakes the background solver and pushes the recommendation to the UI over
server-sent events. Manual pick entry covers leagues on other platforms.

API surface: `POST /sessions` (projection, positions and ADP files, league shape, `objective`,
`sigma_scale`, `curve_file`, `survival` none/simulate/file, `solve_ahead`, `time_limit`),
`/board` (with the first-order `cost` per player), `/picks`, `/sync`, `/autopick`,
`POST /recommend` (synchronous), `POST /solve` (queue a background solve),
`GET /recommendation` (the latest, with `stale`), `/teams`, `/score`, `/solver`, `/events`
(`pick`, `undo`, `survival`, `solve` progress, `recommendation`), and the Yahoo feed routes.

## Sources

* Basketball Monster (primary): membership site with rest-of-season, weekly and daily projections
  that refresh several times a day. Exports are `.xls`; `sources.bbm.parse` handles both the totals
  and per-game layouts. A Playwright fetcher using the member's own login session will download
  the exports on a schedule. Exports are never committed.
* Yahoo Fantasy: `yfpy` for league settings, stat categories, roster slots, player list with ADP,
  rosters and draft results. Needs a Yahoo developer app (installed application, redirect
  `https://localhost:8080`) and a one-time browser OAuth handshake; tokens live outside the repo.
* CSV import: any table that maps onto the data contract (Elite Fantasy Basketball paste, custom
  projections).

Player identity across sources is by normalized name with an alias table for mismatches; Yahoo
`player_key` is attached once matched.

## What was kept from puntgm

| legacy | fate |
| --- | --- |
| `rank/zrank.py` z-scores | rewritten as `projections.zscores` with impact-based percentages |
| `draft/draftpath/basepath.py` MILP | rewritten as `optim.roster` with true slots, auto-punt, balance |
| `pua/main.py` WireTap locks/drops/keeps/blocks | `locks` and `blocks` on `RosterProblem` |
| `draft/draftpath/draftguide.py` draft-slot math | `draft.settings.snake_picks` |
| `greenroom` draft simulator and survival curves | `availability.adp` formula plus `draft.league_sim` and `availability.survival`, now weighting the objective instead of filtering candidates |
| `stats/spygate/bbmspy.py` Selenium exporter | export parsing kept in `sources.bbm.parse`; fetcher to be rebuilt on Playwright |
| Django, DRF, Celery, RabbitMQ, Redis, Postgres, ESPN scraper, notebooks, fixtures | dropped |

## Security

No credentials in the repository, ever. The legacy project hard-coded site passwords in source;
this project reads secrets from environment variables or files listed in `.gitignore`.
