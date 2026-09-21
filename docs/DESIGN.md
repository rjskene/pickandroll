# pickandroll design

Fantasy basketball draft optimizer for 9-category head-to-head leagues, rebuilt from the 2019-2021
`puntgm` Django project. This document records the architecture, the data contracts and the
optimization models so the code can be judged against a stated plan.

## Goals

1. Recommend the next pick during a live Yahoo draft, re-solving after every pick.
2. Choose punt strategies automatically instead of enumerating a fixed list.
3. Use Basketball Monster projections, refreshed several times a day, as the primary input.
4. Reuse the same roster model for waiver moves, trades and weekly matchups after the draft.
5. Keep the solver fast enough to run inside a draft clock: sub-second solves.

## Pieces and the dependency rule

```
src/pickandroll/
  projections/   schema, z-scores                      (core)
  optim/         roster MILP, pick pool                 (core)
  availability/  ADP-based availability curves          (core)
  draft/         league settings, snake-draft math      (core)
  sources/bbm    Basketball Monster export parser, later a Playwright fetcher
  sources/yahoo  Yahoo Fantasy league, players, draft results
  api/           FastAPI app with a server-sent event stream
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

Solver: HiGHS through PuLP (`highspy` ships the binary in the wheel). A 13-of-200 problem solves in
tens of milliseconds; the auto-punt variant with the `w` linearization is still well under a
second.

`pick_pool` forces each candidate onto the roster in turn and reports the objective lost versus the
unconstrained optimum. That difference is the price of taking the candidate now and is what the UI
shows as the pick recommendation list.

## Model 2: rolling-horizon draft (planned)

Extend Model 1 with a pick index `k` over the manager's remaining picks: `x[p, s, k]`, one player
per pick, value weighted by `P(available at pick k)`. Solve, act on pick `k = 1` only, then after
the next real pick arrives re-solve from the new state. Because only the first decision is acted
on, the horizon model can stay coarse (availability curves rather than opponent modelling).

## Availability

`availability.adp` models `P(available at pick k) = 1 - Phi((k - adp) / sd(adp))` with `sd`
widening for later picks. ADP comes from Yahoo's player resource. This replaces the legacy Monte
Carlo draft simulator plus Kaplan-Meier survival curves. If simulation is wanted again, sample
each draft as one vectorized Gumbel-top-k draw (a Plackett-Luce draft in one `argsort`).

## Live draft loop

Yahoo exposes no push API. During a draft the app polls the league resource's `draftresults` every
five to ten seconds, diffs the pick list, updates the draft state (taken players, my roster, next
pick number), re-solves and pushes the recommendation to the UI over server-sent events. Manual
pick entry covers leagues on other platforms.

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
| `greenroom` draft simulator and survival curves | replaced by `availability.adp` |
| `stats/spygate/bbmspy.py` Selenium exporter | export parsing kept in `sources.bbm.parse`; fetcher to be rebuilt on Playwright |
| Django, DRF, Celery, RabbitMQ, Redis, Postgres, ESPN scraper, notebooks, fixtures | dropped |

## Security

No credentials in the repository, ever. The legacy project hard-coded site passwords in source;
this project reads secrets from environment variables or files listed in `.gitignore`.
